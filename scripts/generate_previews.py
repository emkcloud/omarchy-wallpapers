#!/usr/bin/env python3
"""Generate small WebP previews for themed wallpapers in images/.

For each wallpaper (grouped by base name, resolution suffix stripped) a
preview of fixed size (640x360, PREVIEW_WIDTH x PREVIEW_HEIGHT) is derived
from the lowest resolution variant and written to
previews/<theme>/<collection>/<base>-preview.webp.

A per-theme manifest (datasets/<theme>/previews.json) caches the source
content hash so unchanged files are skipped on subsequent runs. This script
only creates the previews and the manifests: the datasets regeneration is a
separate step (scripts/generate_dataset.py).

Two modes:
- worker:  --theme <theme> processes a single theme
- dispatcher: no --theme lists the themes in images/, runs one worker process
  per theme (optionally in parallel with --concurrency) and prints a summary.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES_DIR = os.path.join(ROOT, "images")
DATASETS_DIR = os.path.join(ROOT, "datasets")
PREVIEWS_DIR = os.path.join(ROOT, "previews")

PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 360

TMP_DIR = os.path.join(ROOT, "working", "generate-temp", "previews")

# base name = filename without the resolution suffix
# (e.g. omarchy-country-AD-Andorra-2K.webp -> omarchy-country-AD-Andorra)
BASE_RE = re.compile(r"^(.+)-(?:2K|4K|8K)\.webp$", re.IGNORECASE)


def rel_to_root(path):
    return os.path.relpath(path, ROOT)


def clean_tmp():
    """Delete this script's dedicated temp folder."""
    if os.path.isdir(TMP_DIR):
        shutil.rmtree(TMP_DIR)


def tmp_webp():
    os.makedirs(TMP_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".webp", dir=TMP_DIR)
    os.close(fd)
    os.remove(tmp)
    return tmp


def fmt_time(seconds):
    m, s = divmod(int(seconds), 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}h{m:02d}m"
    return f"{m}m{s:02d}s"


def progress_line(done, total, start, interim=False):
    elapsed = time.time() - start
    rate = done / elapsed if elapsed else 0
    eta = (total - done) / rate if rate else 0
    label = "..." if interim else "Done"
    return (
        f"{label} {done}/{total} ({done / total:.0%}) "
        f"after {fmt_time(elapsed)} | {rate:.1f} files/s | ETA {fmt_time(eta)}"
    )


def manifest_for(theme):
    return os.path.join(DATASETS_DIR, theme, "previews.json")


def preview_rel_for(theme, collection, base):
    return os.path.join("previews", theme, collection, f"{base}-preview.webp")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def image_area(path):
    try:
        with Image.open(path) as im:
            width, height = im.size
        return width * height
    except OSError:
        return None


def scan_groups(theme):
    """Group the .webp files of a theme by base name (resolution suffix stripped)."""
    groups = {}
    theme_dir = os.path.join(IMAGES_DIR, theme)
    if not os.path.isdir(theme_dir):
        return groups
    for collection in sorted(os.listdir(theme_dir)):
        collection_dir = os.path.join(theme_dir, collection)
        if not os.path.isdir(collection_dir):
            continue
        for fn in sorted(os.listdir(collection_dir)):
            if not fn.endswith(".webp"):
                continue
            m = BASE_RE.match(fn)
            if not m:
                continue
            groups.setdefault((theme, collection, m.group(1)), []).append(
                os.path.join(collection_dir, fn)
            )
    return groups


def find_sources(theme=None):
    """Return (source_path, preview_path, preview_rel, theme) for each group,
    choosing the lowest resolution variant as the preview source. If a theme is
    given, only that theme is scanned."""
    themes = [theme] if theme else sorted(
        d for d in os.listdir(IMAGES_DIR) if os.path.isdir(os.path.join(IMAGES_DIR, d))
    )
    sources = []
    for t in themes:
        for (th, collection, base), paths in sorted(scan_groups(t).items()):
            with_area = [(p, image_area(p)) for p in paths]
            with_area = [(p, a) for p, a in with_area if a is not None]
            if not with_area:
                continue
            src = min(with_area, key=lambda pa: pa[1])[0]
            preview_rel = preview_rel_for(th, collection, base)
            sources.append((src, os.path.join(ROOT, preview_rel), preview_rel, th))
    return sources


def generate_one(src, preview, quality, method, apply=True):
    result = {
        "source": src,
        "preview": preview,
        "status": "error",
        "detail": "",
    }
    tmp = None
    try:
        size_in = os.path.getsize(src)
        im = Image.open(src).convert("RGB")
        im.thumbnail((PREVIEW_WIDTH, PREVIEW_HEIGHT), Image.LANCZOS)
        if im.size != (PREVIEW_WIDTH, PREVIEW_HEIGHT):
            im = im.resize((PREVIEW_WIDTH, PREVIEW_HEIGHT), Image.LANCZOS)
        os.makedirs(os.path.dirname(preview), exist_ok=True)
        tmp = tmp_webp()
        im.save(tmp, "WEBP", quality=quality, method=method)
        size_out = os.path.getsize(tmp)
        if apply:
            os.makedirs(os.path.dirname(preview), exist_ok=True)
            os.replace(tmp, preview)
            tmp = None
        result.update(
            status="generated",
            detail=f"{size_out} bytes",
            size=size_out,
            source_size=size_in,
        )
        return result
    except Exception as exc:  # pragma: no cover
        result["detail"] = str(exc)
        return result
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)


def load_manifest(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_manifest(path, manifest):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


def record_manifest(manifests, generated):
    """Update the in-memory manifests with fresh entries for generated previews."""
    for res in generated:
        theme = rel_to_root(res["preview"]).split(os.sep)[1]
        target = manifest_for(theme)
        try:
            manifests[target][rel_to_root(res["source"])] = {
                "sha256": sha256(res["source"]),
                "size": res["source_size"],
                "preview_sha256": sha256(res["preview"]),
                "preview_size": res["size"],
            }
        except OSError:
            pass


def save_all(manifests):
    for target, manifest in manifests.items():
        save_manifest(target, manifest)


def result_path(theme):
    return os.path.join(TMP_DIR, f"previews-{theme}.result.json")


def write_result(theme, data):
    os.makedirs(TMP_DIR, exist_ok=True)
    with open(result_path(theme), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_result(theme):
    try:
        with open(result_path(theme), encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return None


def print_table(header, rows, footer=None):
    all_rows = [header] + rows
    if footer:
        all_rows.append(footer)
    widths = [max(len(str(r[i])) for r in all_rows) for i in range(len(header))]
    for i, r in enumerate(all_rows):
        print("  ".join(str(c).ljust(widths[j]) for j, c in enumerate(r)), flush=True)
        if i == 0:
            print("  ".join("-" * w for w in widths), flush=True)


def run_theme(args):
    theme = args.theme
    if not os.path.isdir(os.path.join(IMAGES_DIR, theme)):
        sys.exit(f"Theme not found: {theme}")

    sys.stdout.reconfigure(line_buffering=True)
    print(f"Scanning {theme}: analyzing images/{theme}/ ...", flush=True)
    sources = find_sources(theme)
    if not sources:
        print(f"[{theme}] No valid WebP in images/{theme}/", flush=True)
        write_result(
            theme,
            {"theme": theme, "total": 0, "skipped": 0, "generated": 0, "errors": 0, "bytes": 0, "errors_detail": []},
        )
        return 0
    print(f"Analyzed {len(sources)} images.", flush=True)

    manifests = {}
    if not args.force:
        manifests[manifest_for(theme)] = load_manifest(manifest_for(theme))

    to_process = []
    skipped = 0
    checked = 0
    for src, preview, preview_rel, th in sources:
        try:
            digest = sha256(src)
        except OSError:
            continue
        checked += 1
        cached = manifests.get(manifest_for(th), {}).get(rel_to_root(src))
        if cached and cached.get("sha256") == digest and os.path.exists(preview):
            skipped += 1
        else:
            to_process.append((src, preview, preview_rel, th))

    pending_total = len(to_process)
    if args.limit and args.limit > 0:
        to_process = to_process[: args.limit]
    total = len(to_process)

    print(f"To generate: {total} previews (this run) | total remaining: {pending_total} | already ok (skip): {skipped}", flush=True)

    if args.dry_run:
        print("Dry run: no files written.", flush=True)

    generated = []
    errors = []
    total_bytes = 0

    if to_process:
        done = 0
        next_report = args.report_every
        start = time.time()
        last_beat = start
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(
                    generate_one, src, preview, args.quality, args.method, not args.dry_run
                ): (src, preview)
                for src, preview, _, _ in to_process
            }
            for fut in as_completed(futures):
                res = fut.result()
                if res["status"] == "generated":
                    generated.append(res)
                    total_bytes += res["size"]
                else:
                    errors.append((res["source"], res["detail"]))
                done += 1
                if not args.force and not args.dry_run and done % args.save_every == 0:
                    record_manifest(manifests, [res])
                    save_all(manifests)
                now = time.time()
                if done >= next_report:
                    print(progress_line(done, total, start), flush=True)
                    next_report += args.report_every
                    last_beat = now
                elif now - last_beat >= 3.0:
                    print(progress_line(done, total, start, interim=True), flush=True)
                    last_beat = now

        if not args.force and not args.dry_run:
            record_manifest(manifests, generated)
            save_all(manifests)

    for p, d in errors:
        print(f"  ERROR {rel_to_root(p)}: {d}", flush=True)

    print(
        f"[{theme}] {checked} images | {skipped} OK | {len(generated)} new previews generated | {len(errors)} errors",
        flush=True,
    )

    write_result(
        theme,
        {
            "theme": theme,
            "total": checked,
            "skipped": skipped,
            "generated": len(generated),
            "errors": len(errors),
            "bytes": total_bytes,
            "errors_detail": [(rel_to_root(p), d) for p, d in errors],
        },
    )

    return 1 if errors else 0


def worker_cmd(theme, args):
    cmd = [sys.executable, os.path.abspath(__file__), "--theme", theme]
    for name in ("workers", "method", "quality", "save_every", "report_every"):
        cmd += [f"--{name.replace('_', '-')}", str(getattr(args, name))]
    if args.force:
        cmd.append("--force")
    if args.dry_run:
        cmd.append("--dry-run")
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    return cmd


def theme_looks_done(theme):
    """True only if the manifest exists and every expected preview file exists
    on disk: the plan reflects reality, not the persisted run state."""
    if not os.path.exists(manifest_for(theme)):
        return False
    expected = len(scan_groups(theme))
    if expected == 0:
        return False
    preview_dir = os.path.join(PREVIEWS_DIR, theme)
    existing = 0
    if os.path.isdir(preview_dir):
        for entry in os.listdir(preview_dir):
            cdir = os.path.join(preview_dir, entry)
            if os.path.isdir(cdir):
                existing += sum(1 for f in os.listdir(cdir) if f.endswith(".webp"))
    return existing >= expected


def run_dispatcher(args):
    themes = sorted(
        d for d in os.listdir(IMAGES_DIR) if os.path.isdir(os.path.join(IMAGES_DIR, d))
    )
    if not themes:
        sys.exit("No themes found in images/")

    rows = []
    total_imgs = 0
    for theme in themes:
        n = len(scan_groups(theme))
        total_imgs += n
        rows.append((theme, n, "YES" if os.path.exists(manifest_for(theme)) else "NO"))
    print(f"Analyzing themes from images/ ... ({len(themes)} themes)", flush=True)
    print()
    print_table(
        ("Theme", "Images", "previews.json"),
        rows,
        ("Total", total_imgs, f"{sum(1 for r in rows if r[2] == 'YES')}/{len(themes)} YES"),
    )

    print()
    print("Work plan:", flush=True)
    for t in themes:
        if theme_looks_done(t):
            label = "already ok (previews present)"
        else:
            label = "to process"
        print(f"  - {t}: {label}", flush=True)
    if args.plan_only:
        print("\n(--plan-only: no workers launched)", flush=True)
        return 0
    print("Processing one theme at a time.", flush=True)

    results = {}
    failed = []

    if args.concurrency <= 1:
        for i, theme in enumerate(themes, 1):
            print(f"\n[{i}/{len(themes)}] {theme} ...", flush=True)
            rc = subprocess.run(worker_cmd(theme, args)).returncode
            results[theme] = load_result(theme)
            if rc != 0:
                failed.append(theme)
    else:
        os.makedirs(TMP_DIR, exist_ok=True)

        def run_logged(theme):
            log_path = os.path.join(TMP_DIR, f"previews-{theme}.log")
            with open(log_path, "w", encoding="utf-8") as logf:
                rc = subprocess.run(
                    worker_cmd(theme, args), stdout=logf, stderr=subprocess.STDOUT
                ).returncode
            return theme, rc

        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [pool.submit(run_logged, t) for t in themes]
            for fut in as_completed(futures):
                theme, rc = fut.result()
                results[theme] = load_result(theme)
                print(
                    f"[done] {theme} (rc={rc}) | log: working/generate-temp/previews/previews-{theme}.log",
                    flush=True,
                )
                if rc != 0:
                    failed.append(theme)

    print()
    print("Final summary", flush=True)
    sum_ok = sum_gen = sum_err = sum_bytes = 0
    rows = []
    for theme in themes:
        r = results.get(theme)
        if not r:
            rows.append((theme, "-", "-", "-", "-"))
            continue
        rows.append((theme, r["skipped"], r["generated"], r["errors"], f"{r['bytes']:,}"))
        sum_ok += r["skipped"]
        sum_gen += r["generated"]
        sum_err += r["errors"]
        sum_bytes += r["bytes"]
    print_table(
        ("Theme", "OK", "New", "Errors", "Bytes"),
        rows,
        ("Total", sum_ok, sum_gen, sum_err, f"{sum_bytes:,}"),
    )

    if failed:
        print(f"Themes with errors: {', '.join(failed)}", flush=True)

    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(
        description="Generate WebP previews (640x360) for themed wallpapers"
    )
    parser.add_argument("--theme", help="process only this theme (worker mode)")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="themes to process in parallel (dispatcher mode)",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="show the theme list and the work plan without running any worker",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--method", type=int, default=6, help="libwebp method (0-6)")
    parser.add_argument("--quality", type=int, default=80, help="lossy WebP quality")
    parser.add_argument("--force", action="store_true", help="ignore the manifest cache")
    parser.add_argument("--dry-run", action="store_true", help="report without writing files")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="max previews to generate in this run (0 = all); use a small number for batched, resumable runs",
    )
    parser.add_argument(
        "--save-every",
        type=int,
        default=50,
        help="persist the manifests every N generated previews so interrupted runs resume",
    )
    parser.add_argument(
        "--report-every",
        type=int,
        default=100,
        help="print a progress line every N generated previews",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="delete this script's dedicated temp folder (working/generate-temp/previews/) and exit",
    )
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)
    if args.clean:
        clean_tmp()
        return
    if args.theme:
        sys.exit(run_theme(args))
    if not args.plan_only:
        clean_tmp()
    sys.exit(run_dispatcher(args))


if __name__ == "__main__":
    main()