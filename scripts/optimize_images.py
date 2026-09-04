#!/usr/bin/env python3
"""Lossless WebP optimization for wallpapers in images/ and masters/.

Re-encodes lossless WebP with Pillow (libwebp). Files that would not be
improved are left untouched. A per-theme manifest (datasets/<theme>/optimization.json,
plus datasets/masters/optimization.json) caches per-file content hashes so
unchanged files are skipped on subsequent runs without re-encoding. After
optimizing, the wallpaper datasets are regenerated because size_bytes change.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed

from PIL import Image, ImageChops

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES_DIR = os.path.join(ROOT, "images")
MASTERS_DIR = os.path.join(ROOT, "masters")
DATASETS_DIR = os.path.join(ROOT, "datasets")

GENERATOR = os.path.join(ROOT, "scripts", "generate_dataset.py")


def rel_to_root(path):
    return os.path.relpath(path, ROOT)


def manifest_for(path):
    rel = rel_to_root(path)
    if rel.startswith("images" + os.sep):
        theme = rel.split(os.sep)[1]
        return os.path.join(DATASETS_DIR, theme, "optimization.json")
    if rel.startswith("masters" + os.sep):
        return os.path.join(DATASETS_DIR, "masters", "optimization.json")
    return None


def find_webps():
    out = []
    for base in (IMAGES_DIR, MASTERS_DIR):
        for root, _, files in os.walk(base):
            for fn in sorted(files):
                if fn.endswith(".webp"):
                    out.append(os.path.join(root, fn))
    return out


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
        fd, tmp = tempfile.mkstemp(suffix=".webp", dir=os.path.dirname(path))
        os.close(fd)
        os.remove(tmp)
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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Optimize wallpaper WebP (lossless)")
    parser.add_argument("paths", nargs="*", help="specific WebP paths (default: all under images/ and masters/)")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--method", type=int, default=6, help="libwebp method (0-6), higher = better compression")
    parser.add_argument("--force", action="store_true", help="ignore the manifest cache")
    parser.add_argument("--dry-run", action="store_true", help="report without applying changes")
    args = parser.parse_args()

    paths = [os.path.abspath(p) for p in args.paths] or find_webps()
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        sys.exit("Nessun WebP trovato")

    manifests = {}
    if not args.force:
        for p in paths:
            target = manifest_for(p)
            if target and target not in manifests:
                manifests[target] = load_manifest(target)

    to_process = []
    skipped = 0
    for p in paths:
        try:
            digest = sha256(p)
        except OSError:
            continue
        target = manifest_for(p)
        cached = manifests.get(target, {}).get(rel_to_root(p)) if target else None
        if cached and cached.get("sha256") == digest:
            skipped += 1
        else:
            to_process.append(p)

    print(f"Totale: {len(paths)} | da processare: {len(to_process)} | invariati (salta): {skipped}")

    if args.dry_run:
        print("Dry run: nessuna modifica applicata.")

    optimized = []
    optimal = []
    errors = []
    saved = 0

    if to_process:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(optimize_one, p, args.method, not args.dry_run): p
                for p in to_process
            }
            for fut in as_completed(futures):
                res = fut.result()
                status = res["status"]
                if status == "optimized":
                    optimized.append(res["path"])
                    saved += res["size_in"] - res["size"]
                elif status == "optimal":
                    optimal.append(res["path"])
                else:
                    errors.append((res["path"], res["detail"]))
                print(f"  [{status}] {os.path.relpath(res['path'], ROOT)} {res['detail']}")

        if not args.force and not args.dry_run:
            for res_path in optimized + optimal:
                target = manifest_for(res_path)
                if not target:
                    continue
                try:
                    manifests[target][rel_to_root(res_path)] = {
                        "sha256": sha256(res_path),
                        "size": os.path.getsize(res_path),
                    }
                except OSError:
                    pass
            for target, manifest in manifests.items():
                save_manifest(target, manifest)

    print()
    print(f"Ottimizzati: {len(optimized)}")
    print(f"Già ottimali: {len(optimal)}")
    print(f"Invariati (saltati): {skipped}")
    print(f"Errori: {len(errors)}")
    print(f"Byte risparmiati: {saved:,}")
    for p, d in errors:
        print(f"  ERRORE {os.path.relpath(p, ROOT)}: {d}")

    if optimized and not args.dry_run:
        subprocess.run([sys.executable, GENERATOR])


if __name__ == "__main__":
    main()