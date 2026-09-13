#!/usr/bin/env python3
"""Generate the datasets/ JSON index from the wallpapers in images/ and the masters in masters/.

For each group ('masters' first, then one per theme from images/) it writes
datasets/<group>/catalog.json and datasets/<group>/collections.json. A separate
aggregation step assembles datasets/datasets.json from those catalogs (also
assigning distinct per-theme previews) and removes stale theme folders.

This script only writes the JSON indexes: previews and optimizations are
separate steps (generate_previews.py, generate_optimization.py), though the
dispatcher checks for missing previews and generates them first as a safety net.

Two modes:
- worker:  --group <group> generates a single group (a theme name or 'masters')
- dispatcher: no --group lists the groups, checks for missing previews, runs one
  worker per group (optionally in parallel with --concurrency), then aggregates
  datasets.json. Use --aggregate-only to run only the final assembly.
"""

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES_DIR = os.path.join(ROOT, "images")
MASTERS_DIR = os.path.join(ROOT, "masters")
MASTERS_COLORS_DIR = os.path.join(MASTERS_DIR, "colors")
DATASETS_DIR = os.path.join(ROOT, "datasets")
PREVIEWS_DIR = os.path.join(ROOT, "previews")

GENERATOR_PREVIEWS = os.path.join(ROOT, "scripts", "generate_previews.py")

TMP_DIR = os.path.join(ROOT, "working", "generate-temp", "dataset")

REPO = "emkcloud/omarchy-wallpapers"
BRANCH = "main"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"

FILENAME_RE = re.compile(r"^omarchy-(country|city)-([A-Z]{2})-(.+)-([248]K)\.webp$", re.IGNORECASE)
FIGURE_RE = re.compile(r"^omarchy-(figure)-(.+)-([248]K)\.webp$", re.IGNORECASE)
MASTER_RE = re.compile(r"^omarchy-(country|city)-([A-Z]{2})-(.+)-([248]K)\.webp$", re.IGNORECASE)
COLLECTIONS = ("countries", "cities", "figures")


PREVIEW_BASE_RE = re.compile(r"^(.+)-(?:2K|4K|8K)\.webp$", re.IGNORECASE)

CONFIG_PATH = os.path.join(DATASETS_DIR, "config.json")


def clean_tmp():
    """Delete this script's dedicated temp folder."""
    if os.path.isdir(TMP_DIR):
        shutil.rmtree(TMP_DIR)


def load_config():
    """Return the static datasets/config.json content (source of truth for
    theme and collection descriptions). Missing file or fields yield empty dicts."""
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def missing_previews():
    """Return the list of preview paths that should exist but are missing."""
    missing = []
    for theme in sorted(os.listdir(IMAGES_DIR)):
        theme_dir = os.path.join(IMAGES_DIR, theme)
        if not os.path.isdir(theme_dir):
            continue
        for collection in sorted(os.listdir(theme_dir)):
            collection_dir = os.path.join(theme_dir, collection)
            if not os.path.isdir(collection_dir):
                continue
            for fn in sorted(os.listdir(collection_dir)):
                if not fn.endswith(".webp"):
                    continue
                m = PREVIEW_BASE_RE.match(fn)
                if not m:
                    continue
                preview_path = os.path.join(
                    PREVIEWS_DIR, theme, collection, f"{m.group(1)}-preview.webp"
                )
                if not os.path.exists(preview_path):
                    missing.append(preview_path)
    return missing


def ensure_previews():
    """Generate missing previews (delegating to generate_previews.py) and
    return the list of generated paths."""
    missing = missing_previews()
    if not missing:
        return []
    print(f"Missing previews ({len(missing)}), generating...")
    subprocess.run([sys.executable, GENERATOR_PREVIEWS], check=True)
    return missing


def parse_entry(filename):
    m = FILENAME_RE.match(filename)
    if m:
        return m.groups()
    m = FIGURE_RE.match(filename)
    if m:
        kind, name, res = m.groups()
        return kind, None, name, res
    return None


def image_size(path):
    try:
        with Image.open(path) as im:
            return im.size
    except OSError:
        return None


def ucwords(value):
    return " ".join(word[:1].upper() + word[1:] for word in value.replace("-", " ").split())


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def preview_rel_for(filename, theme, collection):
    m = re.match(r"^(.+)-(?:2K|4K|8K)\.webp$", filename, re.IGNORECASE)
    if not m:
        return None
    return os.path.join("previews", theme, collection, f"{m.group(1)}-preview.webp")


def build_entry(rel_path, filename, theme, collection):
    parsed = parse_entry(filename)
    if not parsed:
        return None
    kind, code, name, res = parsed
    name = name.replace("-", " ")
    abs_path = os.path.join(ROOT, rel_path)
    size = os.path.getsize(abs_path)
    wh = image_size(abs_path)
    width, height = wh if wh else (None, None)
    entry = {
        "id": os.path.splitext(filename)[0],
        "title": f"{ucwords(theme)} \u2022 {ucwords(collection)} \u2022 {name}",
        "theme": theme,
        "collection": collection,
        "name": name,
        "code": code.upper() if code else None,
        "resolution": res.upper(),
        "filename": filename,
        "path": rel_path,
        "url": f"{RAW_BASE}/{rel_path}",
        "size_bytes": size,
        "sha256": sha256(abs_path),
        "width": width,
        "height": height,
        "format": "webp",
        "tags": [name.lower().replace(" ", "-")],
    }
    preview_rel = preview_rel_for(filename, theme, collection)
    if preview_rel and os.path.exists(os.path.join(ROOT, preview_rel)):
        entry["preview"] = f"{RAW_BASE}/{preview_rel}"
    return entry


def scan_theme(theme_dir):
    entries = []
    for collection in COLLECTIONS:
        collection_dir = os.path.join(theme_dir, collection)
        if not os.path.isdir(collection_dir):
            continue
        for filename in sorted(os.listdir(collection_dir)):
            if not filename.endswith(".webp"):
                continue
            rel_path = os.path.relpath(
                os.path.join(collection_dir, filename), ROOT
            )
            entry = build_entry(rel_path, filename, os.path.basename(theme_dir), collection)
            if entry:
                entries.append(entry)
    return entries


def build_master_entry(rel_path, filename, collection):
    m = MASTER_RE.match(filename)
    if m:
        kind, code, name, res = m.groups()
        variant = res.lower()
        resolution = res.upper()
    else:
        m = FIGURE_RE.match(filename)
        if not m:
            return None
        kind, name, res = m.groups()
        code = None
        variant = res.lower()
        resolution = res.upper()
    name = name.replace("-", " ")
    abs_path = os.path.join(ROOT, rel_path)
    size = os.path.getsize(abs_path)
    wh = image_size(abs_path)
    width, height = wh if wh else (None, None)
    return {
        "id": os.path.splitext(filename)[0],
        "type": kind.lower(),
        "collection": collection,
        "name": name,
        "code": code.upper() if code else None,
        "variant": variant,
        "resolution": resolution,
        "filename": filename,
        "path": rel_path,
        "url": f"{RAW_BASE}/{rel_path}",
        "size_bytes": size,
        "sha256": sha256(abs_path),
        "width": width,
        "height": height,
        "format": "webp",
        "tags": [name.lower().replace(" ", "-")],
    }


def scan_masters():
    entries = []
    for collection in COLLECTIONS:
        collection_dir = os.path.join(MASTERS_COLORS_DIR, collection)
        if not os.path.isdir(collection_dir):
            continue
        for filename in sorted(os.listdir(collection_dir)):
            if not filename.endswith(".webp"):
                continue
            rel_path = os.path.relpath(
                os.path.join(collection_dir, filename), ROOT
            )
            entry = build_master_entry(rel_path, filename, collection)
            if entry:
                entries.append(entry)
    return entries


def write_json(out, payload):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"{out}: {payload['count']}")


def file_info(path, extra=None):
    rel = os.path.relpath(path, ROOT)
    info = {
        "path": rel,
        "url": f"{RAW_BASE}/{rel}",
        "size_bytes": os.path.getsize(path),
    }
    if extra:
        info.update(extra)
    return info


def full_image_url(theme, collection, preview_filename):
    """Return the URL of the full-resolution image matching a preview filename.
    Prefers 2K, falling back to the lowest available resolution."""
    stem = preview_filename
    if stem.endswith("-preview.webp"):
        stem = stem[: -len("-preview.webp")]
    else:
        stem = os.path.splitext(stem)[0]
    image_dir = os.path.join(IMAGES_DIR, theme, collection)
    for res in ("2K", "4K", "8K"):
        candidate = f"{stem}-{res}.webp"
        if os.path.exists(os.path.join(image_dir, candidate)):
            return f"{RAW_BASE}/images/{theme}/{collection}/{candidate}"
    return None


def collection_preview(theme, collection):
    preview_dir = os.path.join(ROOT, "previews", theme, collection)
    if not os.path.isdir(preview_dir):
        return None, None
    files = [
        f
        for f in os.listdir(preview_dir)
        if f.endswith(".webp")
    ]
    if not files:
        return None, None
    chosen = random.choice(sorted(files))
    preview = f"{RAW_BASE}/previews/{theme}/{collection}/{chosen}"
    return preview, full_image_url(theme, collection, chosen)


def build_collections(theme, kind, images_dir, entries, collection_meta=None, palette=None):
    collection_meta = collection_meta or {}
    by_collection = {}
    for e in entries:
        by_collection.setdefault(e["collection"], []).append(e)
    collections = []
    for collection in sorted(by_collection):
        col_entries = by_collection[collection]
        variants = {}
        for e in col_entries:
            var_key = e["resolution"] or "full"
            variant = variants.setdefault(
                var_key,
                {"count": 0, "size_bytes": 0, "width": e["width"], "height": e["height"]},
            )
            variant["count"] += 1
            variant["size_bytes"] += e["size_bytes"]
        col_dir = os.path.join(images_dir, collection)
        preview, image = collection_preview(theme, collection)
        entry = {
            "collection": collection,
            "count": len(col_entries),
            "total_size_bytes": sum(e["size_bytes"] for e in col_entries),
            "directory": col_dir,
            "url": f"{RAW_BASE}/{col_dir}",
            "variants": variants,
        }
        meta = collection_meta.get(collection, {})
        if meta.get("title"):
            entry["title"] = meta["title"]
        if meta.get("description"):
            entry["description"] = meta["description"]
        if preview:
            entry["preview"] = preview
        if image:
            entry["image"] = image
        collections.append(entry)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": REPO,
        "branch": BRANCH,
        "theme": theme,
        "kind": kind,
        "count": len(entries),
        "total_size_bytes": sum(e["size_bytes"] for e in entries),
        "collections": collections,
    }
    if palette:
        payload["palette"] = palette
    return payload


def base_name_from_preview(url):
    """Extract the wallpaper base name from a preview URL/filename
    (e.g. '.../omarchy-country-IT-Italy-preview.webp' -> 'omarchy-country-IT-Italy')."""
    filename = os.path.basename(url)
    stem = os.path.splitext(filename)[0]
    if stem.endswith("-preview"):
        stem = stem[: -len("-preview")]
    return stem


def theme_preview(theme, collections, forbidden_bases=None):
    forbidden = forbidden_bases or set()
    candidates = []
    for collection in collections:
        preview_dir = os.path.join(ROOT, "previews", theme, collection)
        if not os.path.isdir(preview_dir):
            continue
        candidates.extend(
            (f"{RAW_BASE}/previews/{theme}/{collection}/{f}", collection, f)
            for f in os.listdir(preview_dir)
            if f.endswith(".webp")
        )
    if not candidates:
        return None, None
    free = [c for c in candidates if base_name_from_preview(c[0]) not in forbidden]
    pool = free if free else candidates
    preview, collection, filename = random.choice(sorted(pool))
    return preview, full_image_url(theme, collection, filename)


def base_from_reference(ref):
    """Extract the wallpaper base name from a config reference, tolerating a
    path, a resolution suffix (2K/4K/8K) and/or a -preview suffix."""
    base = os.path.splitext(os.path.basename(ref))[0]
    for pattern in (r"-(?:2K|4K|8K)$", r"-preview$", r"-(?:2K|4K|8K)$"):
        base = re.sub(pattern, "", base, flags=re.IGNORECASE)
    return base


def resolve_cover(theme, ref):
    """Resolve an explicit theme cover (config.json theme 'image') to a
    (preview_url, image_url) pair, or None if it cannot be found. The reference
    may be a base name, a filename with resolution, or a repo-relative path."""
    if not ref:
        return None
    base = base_from_reference(ref)
    for collection in COLLECTIONS:
        image_dir = os.path.join(IMAGES_DIR, theme, collection)
        if not os.path.isdir(image_dir):
            continue
        if not any(
            os.path.exists(os.path.join(image_dir, f"{base}-{res}.webp"))
            for res in ("2K", "4K", "8K")
        ):
            continue
        preview_file = f"{base}-preview.webp"
        preview_path = os.path.join(PREVIEWS_DIR, theme, collection, preview_file)
        preview = (
            f"{RAW_BASE}/previews/{theme}/{collection}/{preview_file}"
            if os.path.exists(preview_path)
            else None
        )
        return preview, full_image_url(theme, collection, preview_file)
    print(f"Warning: cover '{ref}' not found for theme '{theme}'", file=sys.stderr)
    return None


def build_collection(name, kind, images_dir, entries, catalog_path, description=None, forbidden_bases=None, palette=None, cover=None):
    opt_path = os.path.join(os.path.dirname(catalog_path), "optimization.json")
    opt_info = None
    if os.path.exists(opt_path):
        with open(opt_path, encoding="utf-8") as f:
            opt_manifest = json.load(f)
        opt_info = file_info(opt_path, {"entries": len(opt_manifest)})
    previews_path = os.path.join(os.path.dirname(catalog_path), "previews.json")
    previews_info = None
    if os.path.exists(previews_path):
        with open(previews_path, encoding="utf-8") as f:
            previews_manifest = json.load(f)
        previews_info = file_info(previews_path, {"entries": len(previews_manifest)})
    collections_path = os.path.join(os.path.dirname(catalog_path), "collections.json")
    collections_info = None
    if os.path.exists(collections_path):
        with open(collections_path, encoding="utf-8") as f:
            collections_manifest = json.load(f)
        collections_info = file_info(collections_path, {"collections": len(collections_manifest["collections"])})
    resolutions = sorted(
        {(e["width"], e["height"]) for e in entries if e["width"] and e["height"]}
    )
    collections = sorted({e["collection"] for e in entries})
    collection = {
        "name": name,
        # human-readable name for UIs ("tokyo-night" -> "Tokyo Night")
        "title": ucwords(name),
        "kind": kind,
        "images_dir": images_dir,
        "images_url": f"{RAW_BASE}/{images_dir}",
        "collections": collections,
        "catalog": file_info(catalog_path, {"entries": len(entries)}),
        "optimization": opt_info,
        "previews": previews_info,
        "collections_info": collections_info,
        "count": len(entries),
        "optimized": opt_info["entries"] if opt_info else 0,
        "total_size_bytes": sum(e["size_bytes"] for e in entries),
        "resolutions": resolutions,
    }
    if description:
        collection["description"] = description
    if palette:
        collection["palette"] = palette
    if cover:
        preview, image = cover
    else:
        preview, image = theme_preview(name, collections, forbidden_bases)
    if preview:
        collection["preview"] = preview
    if image:
        collection["image"] = image
    return collection


def print_table(header, rows, footer=None):
    all_rows = [header] + rows
    if footer:
        all_rows.append(footer)
    widths = [max(len(str(r[i])) for r in all_rows) for i in range(len(header))]
    for i, r in enumerate(all_rows):
        print("  ".join(str(c).ljust(widths[j]) for j, c in enumerate(r)), flush=True)
        if i == 0:
            print("  ".join("-" * w for w in widths), flush=True)


def result_path(group):
    return os.path.join(TMP_DIR, f"dataset-{group}.result.json")


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


def group_list():
    """Ordered groups: 'masters' first, then the themes found in images/."""
    themes = sorted(
        d for d in os.listdir(IMAGES_DIR) if os.path.isdir(os.path.join(IMAGES_DIR, d))
    )
    groups = []
    if os.path.isdir(MASTERS_COLORS_DIR):
        groups.append("masters")
    groups.extend(themes)
    return groups


def _count_webp(base):
    if not os.path.isdir(base):
        return 0
    n = 0
    for root, _, files in os.walk(base):
        n += sum(1 for f in files if f.endswith(".webp"))
    return n


def group_count(group):
    base = MASTERS_COLORS_DIR if group == "masters" else os.path.join(IMAGES_DIR, group)
    return _count_webp(base)


def worker_cmd(group, args):
    return [sys.executable, os.path.abspath(__file__), "--group", group]


def run_group(args):
    group = args.group
    config = load_config()
    collection_meta = config.get("collections", {})
    theme_meta = config.get("themes", {})

    if group == "masters":
        masters = scan_masters()
        if not masters:
            print("[masters] No WebP in masters/colors/", flush=True)
            write_result(group, {"group": group, "count": 0})
            return 0
        write_json(
            os.path.join(DATASETS_DIR, "masters", "catalog.json"),
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "repo": REPO,
                "branch": BRANCH,
                "count": len(masters),
                "masters": masters,
            },
        )
        write_json(
            os.path.join(DATASETS_DIR, "masters", "collections.json"),
            build_collections("masters", "masters", "masters/colors", masters, collection_meta),
        )
        write_result(group, {"group": group, "count": len(masters)})
        print(f"[masters] {len(masters)} masters | catalog.json + collections.json written", flush=True)
        return 0

    theme_dir = os.path.join(IMAGES_DIR, group)
    if not os.path.isdir(theme_dir):
        sys.exit(f"Group not found: {group}")
    entries = scan_theme(theme_dir)
    if not entries:
        print(f"[{group}] No wallpapers in images/{group}/", flush=True)
        write_result(group, {"group": group, "count": 0})
        return 0

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": REPO,
        "branch": BRANCH,
        "theme": group,
        "count": len(entries),
        "wallpapers": entries,
    }
    meta = theme_meta.get(group, {})
    if meta.get("title"):
        payload["title"] = meta["title"]
    if meta.get("description"):
        payload["description"] = meta["description"]
    if meta.get("palette"):
        payload["palette"] = meta["palette"]
    write_json(os.path.join(DATASETS_DIR, group, "catalog.json"), payload)
    write_json(
        os.path.join(DATASETS_DIR, group, "collections.json"),
        build_collections(
            group,
            "theme",
            f"images/{group}",
            entries,
            collection_meta,
            palette=meta.get("palette"),
        ),
    )
    write_result(group, {"group": group, "count": len(entries)})
    print(f"[{group}] {len(entries)} wallpapers | catalog.json + collections.json written", flush=True)
    return 0


def aggregate():
    """Assemble datasets.json from the catalogs already on disk and remove
    stale dataset folders. Runs once, after all group workers have finished."""
    config = load_config()
    theme_meta = config.get("themes", {})

    themes = sorted(
        d for d in os.listdir(IMAGES_DIR) if os.path.isdir(os.path.join(IMAGES_DIR, d))
    )

    theme_index = {}
    generated_themes = set()
    total = 0
    used_bases = set()
    for theme in themes:
        catalog_path = os.path.join(DATASETS_DIR, theme, "catalog.json")
        if not os.path.exists(catalog_path):
            continue
        with open(catalog_path, encoding="utf-8") as f:
            payload = json.load(f)
        entries = payload.get("wallpapers", [])
        if not entries:
            continue
        total += len(entries)
        generated_themes.add(theme)
        meta = theme_meta.get(theme, {})
        collection = build_collection(
            name=theme,
            kind="theme",
            images_dir=f"images/{theme}",
            entries=entries,
            catalog_path=catalog_path,
            description=meta.get("description"),
            forbidden_bases=used_bases,
            palette=meta.get("palette"),
            cover=resolve_cover(theme, meta.get("image")),
        )
        theme_index[theme] = collection
        preview = collection.get("preview")
        if preview:
            used_bases.add(base_name_from_preview(preview))

    for name in os.listdir(DATASETS_DIR):
        if name == "masters" or name in generated_themes or name == "config.json":
            continue
        path = os.path.join(DATASETS_DIR, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
            print(f"Removed stale dataset folder: {path}")

    masters_catalog = os.path.join(DATASETS_DIR, "masters", "catalog.json")
    masters = []
    if os.path.exists(masters_catalog):
        with open(masters_catalog, encoding="utf-8") as f:
            masters = json.load(f).get("masters", [])
    elif os.path.isdir(MASTERS_COLORS_DIR):
        masters = scan_masters()
    masters_entry = build_collection(
        name="masters",
        kind="masters",
        images_dir="masters/colors",
        entries=masters,
        catalog_path=masters_catalog,
    )

    index = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": REPO,
        "branch": BRANCH,
        "url_base": RAW_BASE,
        "count": len(theme_index) + (1 if masters_entry else 0),
        "themes": theme_index,
        "masters": masters_entry,
    }
    write_json(os.path.join(DATASETS_DIR, "datasets.json"), index)
    print(f"Total: {total} wallpapers")


def run_dispatcher(args):
    groups = group_list()
    if not groups:
        sys.exit("No groups found in masters/ or images/")

    rows = []
    total = 0
    for g in groups:
        n = group_count(g)
        total += n
        has_cat = os.path.exists(os.path.join(DATASETS_DIR, g, "catalog.json"))
        rows.append((g, n, "YES" if has_cat else "NO"))
    print(f"Analyzing groups ... ({len(groups)} groups)", flush=True)
    print()
    print_table(("Group", "Items", "catalog.json"), rows, ("Total", total, ""))

    print()
    print("Work plan:", flush=True)
    for g in groups:
        print(f"  - {g}: regenerate catalog.json + collections.json", flush=True)
    if args.plan_only:
        print("\n(--plan-only: no workers launched)", flush=True)
        return 0

    if not args.no_previews:
        ensure_previews()

    results = {}
    failed = []

    if args.concurrency <= 1:
        for i, g in enumerate(groups, 1):
            print(f"\n[{i}/{len(groups)}] {g} ...", flush=True)
            rc = subprocess.run(worker_cmd(g, args)).returncode
            results[g] = load_result(g)
            if rc != 0:
                failed.append(g)
    else:
        os.makedirs(TMP_DIR, exist_ok=True)

        def run_logged(g):
            log_path = os.path.join(TMP_DIR, f"dataset-{g}.log")
            with open(log_path, "w", encoding="utf-8") as logf:
                rc = subprocess.run(
                    worker_cmd(g, args), stdout=logf, stderr=subprocess.STDOUT
                ).returncode
            return g, rc

        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [pool.submit(run_logged, g) for g in groups]
            for fut in as_completed(futures):
                g, rc = fut.result()
                results[g] = load_result(g)
                print(f"[done] {g} (rc={rc}) | log: working/generate-temp/dataset/dataset-{g}.log", flush=True)
                if rc != 0:
                    failed.append(g)

    aggregate()

    print()
    print("Final summary", flush=True)
    rows2 = [(g, results[g]["count"] if results.get(g) else "-") for g in groups]
    print_table(
        ("Group", "Items"),
        rows2,
        ("Total", sum(r["count"] for r in results.values() if r)),
    )

    if failed:
        print(f"Groups with errors: {', '.join(failed)}", flush=True)
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description="Generate the datasets/ JSON index")
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
    parser.add_argument(
        "--aggregate-only",
        action="store_true",
        help="assemble datasets.json from existing catalogs and remove stale folders (no workers)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="delete this script's dedicated temp folder (working/generate-temp/dataset/) and exit",
    )
    parser.add_argument(
        "--no-previews",
        action="store_true",
        help="skip the missing-previews check/generation",
    )
    args = parser.parse_args()

    os.makedirs(DATASETS_DIR, exist_ok=True)
    sys.stdout.reconfigure(line_buffering=True)
    if args.clean:
        clean_tmp()
        return
    if args.aggregate_only:
        aggregate()
        return
    if args.group:
        sys.exit(run_group(args))
    if not args.plan_only:
        clean_tmp()
    sys.exit(run_dispatcher(args))


if __name__ == "__main__":
    main()