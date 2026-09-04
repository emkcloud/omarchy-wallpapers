#!/usr/bin/env python3
"""Convert PNG wallpapers to lossless WebP.

Reads PNGs under images/ and masters/, re-encodes them as lossless WebP with
Pillow (libwebp), verifies the output is bit-identical (pixel AE=0) and keeps
the same dimensions, then removes the original PNG. The basename is kept with
a .webp extension.
"""

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

from PIL import Image, ImageChops

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = (
    os.path.join(ROOT, "images"),
    os.path.join(ROOT, "masters"),
)


def find_pngs():
    out = []
    for base in SCAN_DIRS:
        for root, _, files in os.walk(base):
            for fn in sorted(files):
                if fn.endswith(".png"):
                    out.append(os.path.join(root, fn))
    return out


def convert_one(path, method, apply=True):
    result = {"path": path, "status": "error", "detail": ""}
    tmp = None
    try:
        rgb = Image.open(path).convert("RGB")
        out_path = os.path.splitext(path)[0] + ".webp"
        tmp = out_path + ".tmp"
        rgb.save(tmp, "WEBP", lossless=True, method=method)
        decoded = Image.open(tmp).convert("RGB")
        if decoded.size != rgb.size:
            result.update(detail=f"size mismatch {rgb.size} vs {decoded.size}")
            return result
        if ImageChops.difference(rgb, decoded).getbbox():
            result.update(detail="pixel difference")
            return result
        size_in = os.path.getsize(path)
        size_out = os.path.getsize(tmp)
        if apply:
            os.replace(tmp, out_path)
            tmp = None
            os.remove(path)
        result.update(
            status="converted",
            detail=f"{size_in} -> {size_out} bytes",
            size=size_in,
            size_out=size_out,
            out_path=out_path,
        )
        return result
    except Exception as exc:  # pragma: no cover
        result["detail"] = str(exc)
        return result
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)


def main():
    parser = argparse.ArgumentParser(
        description="Convert PNG wallpapers to lossless WebP"
    )
    parser.add_argument(
        "paths", nargs="*", help="specific PNG paths (default: all under images/ and masters/)"
    )
    parser.add_argument(
        "--method", type=int, default=6, help="libwebp method (0-6), higher = better compression"
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true", help="report without applying changes")
    args = parser.parse_args()

    paths = [os.path.abspath(p) for p in args.paths] or find_pngs()
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        sys.exit("Nessun PNG trovato")

    converted = []
    errors = []
    if len(paths) == 1:
        results = [convert_one(paths[0], args.method, not args.dry_run)]
    else:
        results = []
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(convert_one, p, args.method, not args.dry_run): p
                for p in paths
            }
            for fut in as_completed(futures):
                results.append(fut.result())

    for res in results:
        if res["status"] == "converted":
            converted.append(res)
        else:
            errors.append((res["path"], res["detail"]))
        print(f"  [{res['status']}] {os.path.relpath(res['path'], ROOT)} {res['detail']}")

    print()
    print(f"Convertiti: {len(converted)}")
    print(f"Errori: {len(errors)}")
    saved = sum(r["size"] - r["size_out"] for r in converted)
    print(f"Byte risparmiati: {saved:,}")
    for p, d in errors:
        print(f"  ERRORE {os.path.relpath(p, ROOT)}: {d}")
    if args.dry_run:
        print("Dry run: nessuna modifica applicata.")


if __name__ == "__main__":
    main()