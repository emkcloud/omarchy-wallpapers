#!/usr/bin/env python3
"""Generate grayscale masters under masters/grayscale/ from the color masters
in masters/colors/.

Grayscale versions are derived deterministically (luma) from the color masters
and stored lossless as WebP so they can be reused by downstream processing
(theme variants, omarchy-theme work) without recomputing them every time. They
are intentionally NOT exposed in the datasets catalog: they only feed other
derivations. A manifest (datasets/masters/grayscale.json) caches per-file
source hashes so unchanged masters are skipped on subsequent runs.
"""

import argparse
import hashlib
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLORS_DIR = os.path.join(ROOT, "masters", "colors")
GRAYSCALE_DIR = os.path.join(ROOT, "masters", "grayscale")
MANIFEST_PATH = os.path.join(ROOT, "datasets", "masters", "grayscale.json")

COLLECTIONS = ("countries", "cities", "figures")


def rel_to_root(path):
    return os.path.relpath(path, ROOT)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_sources():
    out = []
    for collection in COLLECTIONS:
        collection_dir = os.path.join(COLORS_DIR, collection)
        if not os.path.isdir(collection_dir):
            continue
        for fn in sorted(os.listdir(collection_dir)):
            if not fn.endswith(".webp"):
                continue
            out.append(os.path.join(collection_dir, fn))
    return out


def target_for(source):
    rel = os.path.relpath(source, COLORS_DIR)
    return os.path.join(GRAYSCALE_DIR, rel)


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


def grayscale_one(source, method, apply=True):
    rel = rel_to_root(source)
    result = {"path": source, "status": "error", "detail": ""}
    try:
        rgb = Image.open(source).convert("RGB")
        gray = rgb.convert("L").convert("RGB")
        target = target_for(source)
        if not apply:
            result.update(status="generated", detail="dry run")
            return result
        os.makedirs(os.path.dirname(target), exist_ok=True)
        gray.save(target, "WEBP", lossless=True, method=method)
        result.update(status="generated", detail=rel)
        return result
    except Exception as exc:  # pragma: no cover
        result["detail"] = str(exc)
        return result


def main():
    parser = argparse.ArgumentParser(description="Generate grayscale masters from color masters")
    parser.add_argument("paths", nargs="*", help="specific color master paths (default: all under masters/colors/)")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--method", type=int, default=6, help="libwebp method (0-6), higher = better compression")
    parser.add_argument("--force", action="store_true", help="ignore the manifest cache")
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args()

    sources = [os.path.abspath(p) for p in args.paths] or find_sources()
    sources = [p for p in sources if os.path.exists(p)]
    if not sources:
        sys.exit("No color masters found in masters/colors/")

    manifest = {} if args.force else load_manifest(MANIFEST_PATH)

    to_process = []
    skipped = 0
    for p in sources:
        rel = rel_to_root(p)
        digest = sha256(p)
        cached = manifest.get(rel)
        if cached and cached.get("sha256") == digest and os.path.exists(target_for(p)):
            skipped += 1
        else:
            to_process.append(p)

    print(f"Total: {len(sources)} | to generate: {len(to_process)} | unchanged (skip): {skipped}")

    if args.dry_run:
        print("Dry run: no files written.")

    generated = []
    errors = []
    if to_process:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(grayscale_one, p, args.method, not args.dry_run): p
                for p in to_process
            }
            for fut in as_completed(futures):
                res = fut.result()
                if res["status"] == "generated":
                    generated.append(res["path"])
                else:
                    errors.append((res["path"], res["detail"]))
                print(f"  [{res['status']}] {res['detail']}")

        if not args.force and not args.dry_run:
            for res_path in generated:
                try:
                    manifest[rel_to_root(res_path)] = {
                        "sha256": sha256(res_path),
                        "size": os.path.getsize(res_path),
                    }
                except OSError:
                    pass
            save_manifest(MANIFEST_PATH, manifest)

    print()
    print(f"Generated: {len(generated)}")
    print(f"Unchanged (skipped): {skipped}")
    print(f"Errors: {len(errors)}")
    for p, d in errors:
        print(f"  ERROR {rel_to_root(p)}: {d}")


if __name__ == "__main__":
    import sys
    main()