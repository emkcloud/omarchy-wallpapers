#!/usr/bin/env python3
"""Lossless WebP optimization for wallpapers in images/, masters/ and previews/.

Re-encodes lossless WebP with Pillow (libwebp). Files that would not be
improved are left untouched. A per-group manifest (datasets/<theme>/optimization.json,
plus datasets/masters/optimization.json) caches per-file content hashes so
unchanged files are skipped on subsequent runs without re-encoding. This
script only writes the optimization manifests: the datasets regeneration is a
separate step (scripts/generate_dataset.py).

Groups:
- "masters" (fixed, processed first): masters/colors/ + masters/grayscale/,
  manifest datasets/masters/optimization.json
- one group per theme from images/ (dynamic): images/<theme>/ + previews/<theme>/,
  manifest datasets/<theme>/optimization.json

Two modes:
- worker:  --group <group> processes a single group
- dispatcher: no --group lists the groups (masters first, then themes), runs one
  worker process per group (optionally in parallel with --concurrency) and prints
  a summary.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platform
    fcntl = None

from PIL import Image, ImageChops

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES_DIR = os.path.join(ROOT, "images")
MASTERS_DIR = os.path.join(ROOT, "masters")
PREVIEWS_DIR = os.path.join(ROOT, "previews")
DATASETS_DIR = os.path.join(ROOT, "datasets")

TMP_DIR = os.path.join(ROOT, "working", "generate-temp", "optimization")


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


def acquire_group_lock(group):
    """Exclusive advisory lock per group. Concurrent runs targeting the same
    group serialize instead of clobbering each other's manifest. Released on
    explicit close or process exit (even after a hard kill)."""
    if fcntl is None:
        return None
    os.makedirs(TMP_DIR, exist_ok=True)
    fh = open(os.path.join(TMP_DIR, f"optimize-{group}.lock"), "w")
    fcntl.flock(fh, fcntl.LOCK_EX)
    return fh


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


def group_for(path):
    """Group name for a path: the theme, or 'masters'."""
    rel = rel_to_root(path)
    if rel.startswith("masters" + os.sep):
        return "masters"
    return rel.split(os.sep)[1]


def manifest_for_group(group):
    return os.path.join(DATASETS_DIR, group, "optimization.json")


def manifest_completion(group):
    """Return (entries, total_files) for a group, to gauge real progress."""
    total = len(webps_for_group(group))
    try:
        with open(manifest_for_group(group), encoding="utf-8") as f:
            entries = len(json.load(f))
    except OSError:
        entries = 0
    return entries, total


def webps_for_group(group):
    """All WebP paths belonging to a group. 'masters' covers masters/;
    a theme covers images/<theme>/ and previews/<theme>/."""
    if group == "masters":
        bases = [MASTERS_DIR]
    else:
        bases = [os.path.join(IMAGES_DIR, group), os.path.join(PREVIEWS_DIR, group)]
    out = []
    for base in bases:
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            for fn in sorted(files):
                if fn.endswith(".webp"):
                    out.append(os.path.join(root, fn))
    return sorted(out)


def group_list():
    """Ordered groups: 'masters' first (fixed), then the themes from images/
    (dynamic). Only groups with at least one WebP are returned."""
    themes = sorted(
        d for d in os.listdir(IMAGES_DIR) if os.path.isdir(os.path.join(IMAGES_DIR, d))
    )
    candidates = ["masters"] + themes
    return [g for g in candidates if webps_for_group(g)]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def optimize_one(path, method, apply=True):
    result = {"path": path, "status": "error", "detail": ""}
    tmp = None
    try:
        size_in = os.path.getsize(path)
        rgb = Image.open(path).convert("RGB")
        tmp = tmp_webp()
        rgb.save(tmp, "WEBP", lossless=True, method=method)
        size_out = os.path.getsize(tmp)
        if size_out >= size_in:
            result.update(status="optimal", detail="no size gain", size=size_in)
            return result
        decoded = Image.open(tmp).convert("RGB")
        if decoded.size != rgb.size or ImageChops.difference(rgb, decoded).getbbox():
            result.update(status="error", detail="pixel difference")
            return result
        if apply:
            os.replace(tmp, path)
            tmp = None
        result.update(
            status="optimized",
            detail=f"{size_in} -> {size_out} bytes",
            size=size_out,
            size_in=size_in,
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
    os.makedirs(TMP_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=TMP_DIR)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def record_manifest(manifests, paths):
    """Update the in-memory manifests with fresh sha256/size for the given files."""
    for p in paths:
        target = manifest_for_group(group_for(p))
        try:
            manifests.setdefault(target, {})[rel_to_root(p)] = {
                "sha256": sha256(p),
                "size": os.path.getsize(p),
            }
        except OSError:
            pass


def save_all(manifests):
    for target, manifest in manifests.items():
        save_manifest(target, manifest)


def result_path(group):
    return os.path.join(TMP_DIR, f"optimize-{group}.result.json")


def write_result(group, data):
    os.makedirs(TMP_DIR, exist_ok=True)
    with open(result_path(group), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_result(group):
    try:
        with open(result_path(group), encoding="utf-8") as f:
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


def run_worker(args):
    group = args.group
    lock = acquire_group_lock(group)
    try:
        return _worker(args)
    finally:
        if lock is not None:
            lock.close()


def _worker(args):
    group = args.group
    paths = webps_for_group(group)
    if not paths:
        print(f"[{group}] No WebP found", flush=True)
        write_result(
            group,
            {"group": group, "total": 0, "skipped": 0, "optimized": 0, "optimal": 0, "errors": 0, "bytes_saved": 0, "errors_detail": []},
        )
        return 0
    print(f"Scanning {group}: analyzing {len(paths)} WebP files ...", flush=True)

    target = manifest_for_group(group)
    manifests = {}
    if not args.force:
        manifests[target] = load_manifest(target)

    to_process = []
    skipped = 0
    checked = 0
    for p in paths:
        try:
            digest = sha256(p)
        except OSError:
            continue
        checked += 1
        cached = manifests.get(target, {}).get(rel_to_root(p))
        if cached and cached.get("sha256") == digest:
            skipped += 1
        else:
            to_process.append(p)

    pending_total = len(to_process)
    if args.limit and args.limit > 0:
        to_process = to_process[: args.limit]
    total = len(to_process)

    print(
        f"To process (this run): {total} | total remaining: {pending_total} | unchanged (skip): {skipped}",
        flush=True,
    )

    if args.dry_run:
        print("Dry run: no changes applied.", flush=True)

    optimized = []
    optimal = []
    errors = []
    saved = 0

    if to_process:
        done = 0
        next_report = args.report_every
        start = time.time()
        last_beat = start
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(optimize_one, p, args.method, not args.dry_run): p
                for p in to_process
            }
            for fut in as_completed(futures):
                res = fut.result()
                if res["status"] == "optimized":
                    optimized.append(res["path"])
                    saved += res["size_in"] - res["size"]
                elif res["status"] == "optimal":
                    optimal.append(res["path"])
                else:
                    errors.append((res["path"], res["detail"]))
                done += 1
                if not args.force and not args.dry_run and done % args.save_every == 0:
                    record_manifest(manifests, [res["path"]])
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
            record_manifest(manifests, optimized + optimal)
            save_all(manifests)

    for p, d in errors:
        print(f"  ERROR {rel_to_root(p)}: {d}", flush=True)

    print(
        f"[{group}] {checked} files | {skipped} skipped | {len(optimized)} optimized | "
        f"{len(optimal)} already optimal | {len(errors)} errors | {saved:,} bytes saved",
        flush=True,
    )

    write_result(
        group,
        {
            "group": group,
            "total": checked,
            "skipped": skipped,
            "optimized": len(optimized),
            "optimal": len(optimal),
            "errors": len(errors),
            "bytes_saved": saved,
            "errors_detail": [(rel_to_root(p), d) for p, d in errors],
        },
    )

    return 1 if errors else 0


def worker_cmd(group, args):
    cmd = [sys.executable, os.path.abspath(__file__), "--group", group]
    for name in ("workers", "method", "save_every", "report_every"):
        cmd += [f"--{name.replace('_', '-')}", str(getattr(args, name))]
    if args.force:
        cmd.append("--force")
    if args.dry_run:
        cmd.append("--dry-run")
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    return cmd


def run_dispatcher(args):
    groups = group_list()
    if not groups:
        sys.exit("No WebP found in masters/ or images/")

    rows = []
    total_webp = 0
    tracked = 0
    for g in groups:
        n = len(webps_for_group(g))
        total_webp += n
        entries, _ = manifest_completion(g)
        tracked += entries
        rows.append((g, n, f"{entries}/{n}"))
    print(f"Analyzing groups ... ({len(groups)} groups)", flush=True)
    print()
    print_table(
        ("Group", "WebP", "tracked"),
        rows,
        ("Total", total_webp, f"{tracked}/{total_webp}"),
    )

    print()
    print("Work plan:", flush=True)
    for g in groups:
        entries, total = manifest_completion(g)
        label = "done" if entries >= total else f"to do ({total - entries} remaining)"
        print(f"  - {g}: {label}", flush=True)
    if args.plan_only:
        print("\n(--plan-only: no workers launched)", flush=True)
        return 0

    results = {}
    failed = []

    if args.concurrency <= 1:
        print("Processing one group at a time (masters first).", flush=True)
        for i, g in enumerate(groups, 1):
            print(f"\n[{i}/{len(groups)}] {g} ...", flush=True)
            rc = subprocess.run(worker_cmd(g, args)).returncode
            results[g] = load_result(g)
            if rc != 0:
                failed.append(g)
    else:
        print(f"Processing {len(groups)} groups in parallel (live output, logs in working/generate-temp/optimization/).", flush=True)
        os.makedirs(TMP_DIR, exist_ok=True)

        rcs = {}

        def pump(g, proc, logf):
            tag = f"[{g}] "
            for line in proc.stdout:
                logf.write(line)
                logf.flush()
                if line.startswith(f"[{g}]"):
                    print(line, end="", flush=True)
                else:
                    print(tag + line, end="", flush=True)
            proc.wait()
            logf.close()
            rcs[g] = proc.returncode

        threads = []
        for g in groups:
            log_path = os.path.join(TMP_DIR, f"optimize-{g}.log")
            logf = open(log_path, "w", encoding="utf-8")
            proc = subprocess.Popen(
                worker_cmd(g, args),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            threads.append(threading.Thread(target=pump, args=(g, proc, logf)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for g in groups:
            results[g] = load_result(g)
            if rcs.get(g) != 0:
                failed.append(g)

    print()
    print("Final summary", flush=True)
    sum_opt = sum_already = sum_skip = sum_err = sum_saved = 0
    rows = []
    for g in groups:
        r = results.get(g)
        if not r:
            rows.append((g, "-", "-", "-", "-", "-"))
            continue
        rows.append((g, r["optimized"], r["optimal"], r["skipped"], r["errors"], f"{r['bytes_saved']:,}"))
        sum_opt += r["optimized"]
        sum_already += r["optimal"]
        sum_skip += r["skipped"]
        sum_err += r["errors"]
        sum_saved += r["bytes_saved"]
    print_table(
        ("Group", "Optimized", "Already optimal", "Skipped", "Errors", "Bytes saved"),
        rows,
        ("Total", sum_opt, sum_already, sum_skip, sum_err, f"{sum_saved:,}"),
    )

    if failed:
        print(f"Groups with errors: {', '.join(failed)}", flush=True)

    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description="Optimize wallpaper WebP (lossless)")
    parser.add_argument(
        "--group",
        help="process only this group (worker mode): a theme name or 'masters'",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="groups to process in parallel (dispatcher mode)",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="show the group list and the work plan without running any worker",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--method", type=int, default=6, help="libwebp method (0-6), higher = better compression")
    parser.add_argument("--force", action="store_true", help="ignore the manifest cache")
    parser.add_argument("--dry-run", action="store_true", help="report without applying changes")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="max files to process in this run (0 = all); use a small number for batched, resumable runs",
    )
    parser.add_argument(
        "--save-every",
        type=int,
        default=50,
        help="persist the manifests every N processed files so interrupted runs resume",
    )
    parser.add_argument(
        "--report-every",
        type=int,
        default=100,
        help="print a progress line every N processed files",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="delete this script's dedicated temp folder (working/generate-temp/optimization/) and exit",
    )
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)
    if args.clean:
        clean_tmp()
        return
    if args.group:
        sys.exit(run_worker(args))
    if not args.plan_only:
        clean_tmp()
    sys.exit(run_dispatcher(args))


if __name__ == "__main__":
    main()