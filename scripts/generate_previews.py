#!/usr/bin/env python3
"""Generate small WebP previews for themed wallpapers in images/.

For each wallpaper (grouped by base name, resolution suffix stripped) a
preview of fixed size (640x360, PREVIEW_WIDTH x PREVIEW_HEIGHT) is derived
from the lowest resolution variant and written to
previews/<theme>/<section>/<base>-preview.webp.

A per-theme manifest (datasets/<theme>/previews.json) caches the source
content hash so unchanged files are skipped on subsequent runs. After
generating, the wallpaper datasets are regenerated because the catalogs gain
the `preview` field.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES_DIR = os.path.join(ROOT, "images")
DATASETS_DIR = os.path.join(ROOT, "datasets")
PREVIEWS_DIR = os.path.join(ROOT, "previews")

PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 360

GENERATOR = os.path.join(ROOT, "scripts", "generate_dataset.py")

# base name = filename without the resolution suffix
# (e.g. omarchy-country-AD-Andorra-2K.webp -> omarchy-country-AD-Andorra)
BASE_RE = re.compile(r"^(.+)-(?:2K|4K|8K)\.webp$", re.IGNORECASE)


def rel_to_root(path):
    return os.path.relpath(path, ROOT)


def manifest_for(theme):
    return os.path.join(DATASETS_DIR, theme, "previews.json")


def preview_rel_for(theme, section, base):
    return os.path.join("previews", theme, section, f"{base}-preview.webp")


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


def find_sources():
    """Return (source_path, preview_path, preview_rel, theme) for each group,
    choosing the lowest resolution variant as the preview source."""
    groups = {}
    for theme in sorted(os.listdir(IMAGES_DIR)):
        theme_dir = os.path.join(IMAGES_DIR, theme)
        if not os.path.isdir(theme_dir):
            continue
        for section in sorted(os.listdir(theme_dir)):
            section_dir = os.path.join(theme_dir, section)
            if not os.path.isdir(section_dir):
                continue
            for fn in sorted(os.listdir(section_dir)):
                if not fn.endswith(".webp"):
                    continue
                m = BASE_RE.match(fn)
                if not m:
                    continue
                base = m.group(1)
                groups.setdefault((theme, section, base), []).append(
                    os.path.join(section_dir, fn)
                )

    sources = []
    for (theme, section, base), paths in sorted(groups.items()):
        with_area = [(p, image_area(p)) for p in paths]
        with_area = [(p, a) for p, a in with_area if a is not None]
        if not with_area:
            continue
        src = min(with_area, key=lambda pa: pa[1])[0]
        preview_rel = preview_rel_for(theme, section, base)
        sources.append((src, os.path.join(ROOT, preview_rel), preview_rel, theme))
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
        fd, tmp = tempfile.mkstemp(suffix=".webp", dir=os.path.dirname(preview))
        os.close(fd)
        os.remove(tmp)
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


def main():
    parser = argparse.ArgumentParser(
        description="Generate WebP previews (640x360) for themed wallpapers"
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--method", type=int, default=6, help="libwebp method (0-6)")
    parser.add_argument("--quality", type=int, default=80, help="lossy WebP quality")
    parser.add_argument("--force", action="store_true", help="ignore the manifest cache")
    parser.add_argument("--dry-run", action="store_true", help="report without writing files")
    parser.add_argument(
        "--no-datasets",
        action="store_true",
        help="skip the final datasets regeneration (used when invoked from generate_dataset.py)",
    )
    args = parser.parse_args()

    sources = find_sources()
    if not sources:
        sys.exit("Nessun WebP valido trovato in images/")

    manifests = {}
    if not args.force:
        for _, _, _, theme in sources:
            target = manifest_for(theme)
            if target not in manifests:
                manifests[target] = load_manifest(target)

    to_process = []
    skipped = 0
    for src, preview, preview_rel, theme in sources:
        try:
            digest = sha256(src)
        except OSError:
            continue
        target = manifest_for(theme)
        cached = manifests.get(target, {}).get(rel_to_root(src))
        if cached and cached.get("sha256") == digest and os.path.exists(preview):
            skipped += 1
        else:
            to_process.append((src, preview, preview_rel, theme))

    print(f"Totale: {len(sources)} | da generare: {len(to_process)} | già a posto (salta): {skipped}")

    if args.dry_run:
        print("Dry run: nessun file scritto.")

    generated = []
    errors = []
    total_bytes = 0

    if to_process:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(
                    generate_one, src, preview, args.quality, args.method, not args.dry_run
                ): (src, preview, theme)
                for src, preview, _, theme in to_process
            }
            for fut in as_completed(futures):
                res = fut.result()
                status = res["status"]
                if status == "generated":
                    generated.append(res)
                    total_bytes += res["size"]
                else:
                    errors.append((res["source"], res["detail"]))
                print(
                    f"  [{status}] {rel_to_root(res['preview'])} {res['detail']}"
                )

        if not args.force and not args.dry_run:
            for res in generated:
                target = manifest_for(rel_to_root(res["preview"]).split(os.sep)[1])
                try:
                    manifests[target][rel_to_root(res["source"])] = {
                        "sha256": sha256(res["source"]),
                        "size": res["source_size"],
                        "preview_sha256": sha256(res["preview"]),
                        "preview_size": res["size"],
                    }
                except OSError:
                    pass
            for target, manifest in manifests.items():
                save_manifest(target, manifest)

    print()
    print(f"Generate: {len(generated)}")
    print(f"Invariate (saltate): {skipped}")
    print(f"Errori: {len(errors)}")
    print(f"Totale bytes preview: {total_bytes:,}")
    for p, d in errors:
        print(f"  ERRORE {rel_to_root(p)}: {d}")

    if generated and not args.dry_run and not args.no_datasets:
        subprocess.run([sys.executable, GENERATOR, "--no-previews"])


if __name__ == "__main__":
    main()