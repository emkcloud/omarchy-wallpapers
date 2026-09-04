#!/usr/bin/env python3
"""Generate the datasets/ JSON index from the wallpapers in images/ and the masters in masters/."""

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES_DIR = os.path.join(ROOT, "images")
MASTERS_DIR = os.path.join(ROOT, "masters")
DATASETS_DIR = os.path.join(ROOT, "datasets")
PREVIEWS_DIR = os.path.join(ROOT, "previews")

GENERATOR_PREVIEWS = os.path.join(ROOT, "scripts", "generate_previews.py")

REPO = "emkcloud/omarchy-wallpapers"
BRANCH = "main"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"

FILENAME_RE = re.compile(r"^omarchy-(country|city)-([A-Z]{2})-(.+)-([248]K)\.webp$", re.IGNORECASE)
FIGURE_RE = re.compile(r"^omarchy-(figure)-(.+)-([248]K)\.webp$", re.IGNORECASE)
MASTER_RE = re.compile(r"^omarchy-(country|city)-([A-Z]{2})-(.+)-([248]K)\.webp$", re.IGNORECASE)
MASTER_FULL_RE = re.compile(r"^(country|city)-([A-Z]{2})-(.+)-full\.webp$", re.IGNORECASE)
SECTIONS = ("countries", "cities", "figures")


PREVIEW_BASE_RE = re.compile(r"^(.+)-(?:2K|4K|8K)\.webp$", re.IGNORECASE)

CONFIG_PATH = os.path.join(DATASETS_DIR, "config.json")


def load_config():
    """Return the static datasets/config.json content (source of truth for
    theme and section descriptions). Missing file or fields yield empty dicts."""
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
        for section in sorted(os.listdir(theme_dir)):
            section_dir = os.path.join(theme_dir, section)
            if not os.path.isdir(section_dir):
                continue
            for fn in sorted(os.listdir(section_dir)):
                if not fn.endswith(".webp"):
                    continue
                m = PREVIEW_BASE_RE.match(fn)
                if not m:
                    continue
                preview_path = os.path.join(
                    PREVIEWS_DIR, theme, section, f"{m.group(1)}-preview.webp"
                )
                if not os.path.exists(preview_path):
                    missing.append(preview_path)
    return missing


def ensure_previews():
    """Generate missing previews (delegating to generate_previews.py, which
    also regenerates the datasets) and return the list of generated paths."""
    missing = missing_previews()
    if not missing:
        return []
    print(f"Preview mancanti ({len(missing)}), generazione in corso...")
    subprocess.run([sys.executable, GENERATOR_PREVIEWS, "--no-datasets"], check=True)
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


def preview_rel_for(filename, theme, section):
    m = re.match(r"^(.+)-(?:2K|4K|8K)\.webp$", filename, re.IGNORECASE)
    if not m:
        return None
    return os.path.join("previews", theme, section, f"{m.group(1)}-preview.webp")


def build_entry(rel_path, filename, theme, section):
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
        "title": f"{ucwords(theme)} \u2022 {ucwords(section)} \u2022 {name}",
        "theme": theme,
        "section": section,
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
    preview_rel = preview_rel_for(filename, theme, section)
    if preview_rel and os.path.exists(os.path.join(ROOT, preview_rel)):
        entry["preview"] = f"{RAW_BASE}/{preview_rel}"
    return entry


def scan_theme(theme_dir):
    entries = []
    for section in SECTIONS:
        section_dir = os.path.join(theme_dir, section)
        if not os.path.isdir(section_dir):
            continue
        for filename in sorted(os.listdir(section_dir)):
            if not filename.endswith(".webp"):
                continue
            rel_path = os.path.relpath(
                os.path.join(section_dir, filename), ROOT
            )
            entry = build_entry(rel_path, filename, os.path.basename(theme_dir), section)
            if entry:
                entries.append(entry)
    return entries


def build_master_entry(rel_path, filename, section):
    m = MASTER_RE.match(filename)
    if m:
        kind, code, name, res = m.groups()
        variant = res.lower()
        resolution = res.upper()
    else:
        m = FIGURE_RE.match(filename)
        if m:
            kind, name, res = m.groups()
            code = None
            variant = res.lower()
            resolution = res.upper()
        else:
            m = MASTER_FULL_RE.match(filename)
            if not m:
                return None
            kind, code, name = m.groups()
            variant = "full"
            resolution = None
    name = name.replace("-", " ")
    abs_path = os.path.join(ROOT, rel_path)
    size = os.path.getsize(abs_path)
    wh = image_size(abs_path)
    width, height = wh if wh else (None, None)
    return {
        "id": os.path.splitext(filename)[0],
        "type": kind.lower(),
        "section": section,
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
    for section in SECTIONS:
        section_dir = os.path.join(MASTERS_DIR, section)
        if not os.path.isdir(section_dir):
            continue
        for filename in sorted(os.listdir(section_dir)):
            if not filename.endswith(".webp"):
                continue
            rel_path = os.path.relpath(
                os.path.join(section_dir, filename), ROOT
            )
            entry = build_master_entry(rel_path, filename, section)
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


def section_preview(theme, section):
    preview_dir = os.path.join(ROOT, "previews", theme, section)
    if not os.path.isdir(preview_dir):
        return None
    files = [
        f
        for f in os.listdir(preview_dir)
        if f.endswith(".webp")
    ]
    if not files:
        return None
    chosen = random.choice(sorted(files))
    return f"{RAW_BASE}/previews/{theme}/{section}/{chosen}"


def build_sections(theme, kind, images_dir, entries, section_meta=None):
    section_meta = section_meta or {}
    by_section = {}
    for e in entries:
        by_section.setdefault(e["section"], []).append(e)
    sections = []
    for section in sorted(by_section):
        sec_entries = by_section[section]
        variants = {}
        for e in sec_entries:
            var_key = e["resolution"] or "full"
            variant = variants.setdefault(
                var_key,
                {"count": 0, "size_bytes": 0, "width": e["width"], "height": e["height"]},
            )
            variant["count"] += 1
            variant["size_bytes"] += e["size_bytes"]
        sec_dir = os.path.join(images_dir, section)
        preview = section_preview(theme, section)
        entry = {
            "section": section,
            "count": len(sec_entries),
            "total_size_bytes": sum(e["size_bytes"] for e in sec_entries),
            "directory": sec_dir,
            "url": f"{RAW_BASE}/{sec_dir}",
            "variants": variants,
        }
        meta = section_meta.get(section, {})
        if meta.get("title"):
            entry["title"] = meta["title"]
        if meta.get("description"):
            entry["description"] = meta["description"]
        if preview:
            entry["preview"] = preview
        sections.append(entry)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": REPO,
        "branch": BRANCH,
        "theme": theme,
        "kind": kind,
        "count": len(entries),
        "total_size_bytes": sum(e["size_bytes"] for e in entries),
        "sections": sections,
    }


def collection_preview(theme, sections):
    candidates = []
    for section in sections:
        preview_dir = os.path.join(ROOT, "previews", theme, section)
        if not os.path.isdir(preview_dir):
            continue
        candidates.extend(
            f"{RAW_BASE}/previews/{theme}/{section}/{f}"
            for f in os.listdir(preview_dir)
            if f.endswith(".webp")
        )
    return random.choice(sorted(candidates)) if candidates else None


def build_collection(name, kind, images_dir, entries, catalog_path, description=None):
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
    sections_path = os.path.join(os.path.dirname(catalog_path), "sections.json")
    sections_info = None
    if os.path.exists(sections_path):
        with open(sections_path, encoding="utf-8") as f:
            sections_manifest = json.load(f)
        sections_info = file_info(sections_path, {"sections": len(sections_manifest["sections"])})
    resolutions = sorted(
        {(e["width"], e["height"]) for e in entries if e["width"] and e["height"]}
    )
    sections = sorted({e["section"] for e in entries})
    collection = {
        "name": name,
        # human-readable name for UIs ("tokyo-night" -> "Tokyo Night")
        "title": ucwords(name),
        "kind": kind,
        "images_dir": images_dir,
        "images_url": f"{RAW_BASE}/{images_dir}",
        "sections": sections,
        "catalog": file_info(catalog_path, {"entries": len(entries)}),
        "optimization": opt_info,
        "previews": previews_info,
        "sections_info": sections_info,
        "count": len(entries),
        "optimized": opt_info["entries"] if opt_info else 0,
        "total_size_bytes": sum(e["size_bytes"] for e in entries),
        "resolutions": resolutions,
    }
    if description:
        collection["description"] = description
    preview = collection_preview(name, sections)
    if preview:
        collection["preview"] = preview
    return collection


def main():
    parser = argparse.ArgumentParser(description="Generate the datasets/ JSON index")
    parser.add_argument(
        "--no-previews",
        action="store_true",
        help="skip the missing-previews check (used when called from generate_previews.py)",
    )
    args = parser.parse_args()

    os.makedirs(DATASETS_DIR, exist_ok=True)

    if not args.no_previews:
        ensure_previews()

    config = load_config()
    theme_meta = config.get("themes", {})
    section_meta = config.get("sections", {})

    themes = sorted(
        d
        for d in os.listdir(IMAGES_DIR)
        if os.path.isdir(os.path.join(IMAGES_DIR, d))
    )
    if not themes:
        sys.exit(f"Nessuna cartella tema trovata in {IMAGES_DIR}")

    collections = {}
    generated_themes = set()
    total = 0
    for theme in themes:
        entries = scan_theme(os.path.join(IMAGES_DIR, theme))
        if not entries:
            continue
        total += len(entries)
        generated_themes.add(theme)
        meta = theme_meta.get(theme, {})
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "repo": REPO,
            "branch": BRANCH,
            "theme": theme,
            "count": len(entries),
            "wallpapers": entries,
        }
        if meta.get("title"):
            payload["title"] = meta["title"]
        if meta.get("description"):
            payload["description"] = meta["description"]
        catalog_path = os.path.join(DATASETS_DIR, theme, "catalog.json")
        write_json(catalog_path, payload)
        sections_path = os.path.join(DATASETS_DIR, theme, "sections.json")
        write_json(
            sections_path,
            build_sections(theme, "theme", f"images/{theme}", entries, section_meta),
        )
        collections[theme] = build_collection(
            name=theme,
            kind="theme",
            images_dir=f"images/{theme}",
            entries=entries,
            catalog_path=catalog_path,
            description=meta.get("description"),
        )

    for name in os.listdir(DATASETS_DIR):
        if name == "masters" or name in generated_themes or name == "config.json":
            continue
        path = os.path.join(DATASETS_DIR, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
            print(f"Rimossa cartella dataset stantia: {path}")

    print(f"Totale: {total} wallpaper")

    masters = scan_masters()
    masters_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": REPO,
        "branch": BRANCH,
        "count": len(masters),
        "masters": masters,
    }
    masters_catalog = os.path.join(DATASETS_DIR, "masters", "catalog.json")
    write_json(masters_catalog, masters_payload)
    masters_sections = os.path.join(DATASETS_DIR, "masters", "sections.json")
    write_json(masters_sections, build_sections("masters", "masters", "masters", masters, section_meta))
    collections["masters"] = build_collection(
        name="masters",
        kind="masters",
        images_dir="masters",
        entries=masters,
        catalog_path=masters_catalog,
    )

    index = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": REPO,
        "branch": BRANCH,
        "url_base": RAW_BASE,
        "count": len(collections),
        "collections": collections,
    }
    write_json(os.path.join(DATASETS_DIR, "datasets.json"), index)


if __name__ == "__main__":
    main()