#!/usr/bin/env python3
"""Manage Omarchy wallpapers from this repository.

Subcommands:
    install <theme> [collection] [wallpaper]
                                  Install a theme's wallpapers into Omarchy
                                  (downloads the images directly from GitHub,
                                  in parallel). With no extra argument it
                                  installs every wallpaper of the theme; a
                                  collection name (e.g. "countries") installs
                                  that whole collection; a single wallpaper
                                  (e.g. "Italy" or "IT") installs only that
                                  wallpaper; passing both installs only that
                                  wallpaper within that collection.
    update <theme> [collection] [wallpaper]
                                  Re-install a theme's wallpapers (same as
                                  install).
    list [theme] [target]         List the themes, or the wallpapers of a theme
                                  (optionally restricted to a collection).
    remove <theme> [collection] [wallpaper]
                                  Remove a theme's installed wallpapers from
                                  Omarchy: with no extra argument the whole
                                  theme, with a collection only its wallpapers,
                                  with a wallpaper only that one, with both
                                  that wallpaper within that collection.
    remove --all                  Remove every theme's installed wallpapers.

Checks are done before any download: the theme must exist both in this
repository (via datasets/datasets.json) and in Omarchy (stock or user theme).
Downloads happen only when both checks pass; files already up to date
(matching sha256) are skipped. install, update and remove refresh the Omarchy
background cache (`omarchy theme bg cache`) automatically.

Usage:
    python3 wallpapers.py install osaka-jade
    python3 wallpapers.py install osaka-jade countries
    python3 wallpapers.py install tokyo-night Italy
    python3 wallpapers.py install tokyo-night countries Italy
    python3 wallpapers.py list tokyo-night countries

It can also be run straight from the repository without cloning:
    curl -fsSL https://raw.githubusercontent.com/emkcloud/omarchy-wallpapers/main/scripts/wallpapers.py | python3 - install osaka-jade
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

DATASETS_URL = "https://raw.githubusercontent.com/emkcloud/omarchy-wallpapers/main/datasets/datasets.json"
DEST_BASE = os.path.expanduser("~/.config/omarchy/backgrounds")

USER_AGENT = "omarchy-wallpapers-installer"


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        sys.exit(f"Could not fetch {url}: {exc}")


def normalize_theme(name):
    return name.strip("/").lower().replace(" ", "-")


def installed_in_omarchy(theme):
    user = os.path.join(os.path.expanduser("~/.config/omarchy/themes"), theme)
    stock = os.path.join(
        os.environ.get("OMARCHY_PATH", "/usr/share/omarchy"), "themes", theme
    )
    return os.path.isdir(user) or os.path.isdir(stock)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp, open(path, "wb") as out:
        shutil.copyfileobj(resp, out)


def find_wallpaper(wallpapers, term):
    term = term.lower()
    matches = [
        w for w in wallpapers
        if term in (w["id"].lower(), w["name"].lower(), w["code"].lower(), w["filename"].lower())
    ]
    if not matches:
        matches = [w for w in wallpapers if term in w["name"].lower()]
    return matches


def select_wallpaper(wallpapers, theme, term):
    matches = find_wallpaper(wallpapers, term)
    if not matches:
        sys.exit(f"No wallpaper matching '{term}' found in theme '{theme}'.")
    if len(matches) > 1:
        ids = ", ".join(w["id"] for w in matches)
        sys.exit(f"'{term}' matches multiple wallpapers: {ids}. Be more specific.")
    return matches


def select_collection(wallpapers, theme, term):
    """Return all wallpapers of a collection matching term, or None if not one.

    A collection (a.k.a. content type, e.g. countries, cities, figures) is
    matched case-insensitively; both the plural identifier used in the data and
    its singular form are accepted. Returns None when term does not name a
    collection, so the caller can fall back to single-wallpaper selection.
    """
    term = term.strip().lower()
    singulars = {"countries": "country", "cities": "city", "figures": "figure"}
    for collection in sorted({w["collection"] for w in wallpapers}):
        if collection.lower() == term or singulars.get(collection, collection).lower() == term:
            return [w for w in wallpapers if w["collection"] == collection]
    return None


def refresh_bg_cache():
    if shutil.which("omarchy") is None:
        return
    try:
        subprocess.run(["omarchy", "theme", "bg", "cache"], check=True)
        print("Background cache refreshed.")
    except subprocess.CalledProcessError as exc:
        print(f"Could not refresh the background cache: {exc}", file=sys.stderr)


def cmd_install(theme, collection=None, wallpaper=None):
    theme = normalize_theme(theme)
    data = fetch_json(DATASETS_URL)
    themes = data.get("themes", {})

    info = themes.get(theme)
    if not info or info.get("kind") != "theme":
        available = sorted(
            name for name, item in themes.items() if item.get("kind") == "theme"
        )
        sys.exit(
            f"Theme '{theme}' not found. Available themes: {', '.join(available) or 'none'}"
        )

    if not installed_in_omarchy(theme):
        sys.exit(
            f"Theme '{theme}' is not installed in Omarchy. "
            f"Install it first (`omarchy theme install <url>` or "
            f"create ~/.config/omarchy/themes/{theme}/)."
        )

    catalog = fetch_json(info["catalog"]["url"])
    wallpapers = catalog["wallpapers"]
    if collection and wallpaper:
        selected = select_collection(wallpapers, theme, collection)
        if selected is None:
            collections = sorted({w["collection"] for w in wallpapers})
            sys.exit(
                f"No collection '{collection}' in theme '{theme}'. Available "
                f"collections: {', '.join(collections) or 'none'}."
            )
        wallpapers = select_wallpaper(selected, theme, wallpaper)
    elif collection:
        selected = select_collection(wallpapers, theme, collection)
        if selected is not None:
            wallpapers = selected
        else:
            wallpapers = select_wallpaper(wallpapers, theme, collection)
    elif wallpaper:
        wallpapers = select_wallpaper(wallpapers, theme, wallpaper)

    dest = os.path.join(DEST_BASE, theme)
    os.makedirs(dest, exist_ok=True)

    def fetch(w):
        filename = w["filename"]
        path = os.path.join(dest, filename)
        if os.path.isfile(path) and sha256_of(path) == w["sha256"]:
            return filename, None
        try:
            download_file(w["url"], path)
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            return filename, f"download failed: {exc}"
        if sha256_of(path) != w["sha256"]:
            os.remove(path)
            return filename, "sha256 mismatch"
        return filename, None

    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for filename, error in ex.map(fetch, wallpapers):
            if error:
                failures.append((filename, error))

    if failures:
        for filename, error in failures:
            print(f"FAILED {filename}: {error}", file=sys.stderr)
        sys.exit(f"{len(failures)} of {len(wallpapers)} wallpapers failed.")
    print(f"Installed {len(wallpapers)} wallpapers in {dest}")
    refresh_bg_cache()


def cmd_list(theme=None, target=None):
    data = fetch_json(DATASETS_URL)
    themes = data.get("themes", {})

    if theme is None:
        for name in sorted(
            n for n, item in themes.items() if item.get("kind") == "theme"
        ):
            print(name)
        return

    theme = normalize_theme(theme)
    info = themes.get(theme)
    if not info or info.get("kind") != "theme":
        themes = sorted(
            n for n, item in themes.items() if item.get("kind") == "theme"
        )
        sys.exit(
            f"Theme '{theme}' not found. Available themes: {', '.join(themes) or 'none'}"
        )

    catalog = fetch_json(info["catalog"]["url"])
    wallpapers = catalog["wallpapers"]
    if target:
        selected = select_collection(wallpapers, theme, target)
        if selected is None:
            collections = sorted({w["collection"] for w in wallpapers})
            sys.exit(
                f"'{target}' is not a wallpaper name and there is no collection "
                f"'{target}' in theme '{theme}'. Available collections: "
                f"{', '.join(collections) or 'none'}."
            )
        wallpapers = selected
    for wallpaper in wallpapers:
        print(wallpaper["filename"])


def remove_from_dir(dest, to_remove, label):
    removed = 0
    kept = 0
    for name in sorted(os.listdir(dest)):
        path = os.path.join(dest, name)
        if name in to_remove and os.path.isfile(path):
            os.remove(path)
            removed += 1
        else:
            kept += 1

    if removed:
        if not os.listdir(dest):
            os.rmdir(dest)
            print(f"Removed {removed} wallpaper(s) and the empty {dest} folder.")
        else:
            print(
                f"Removed {removed} wallpaper(s) from {dest} "
                f"(kept {kept} non-repository file(s))."
            )
    else:
        print(f"No repository wallpapers to remove {label}.")
    return removed


def cmd_remove(theme, collection=None, wallpaper=None):
    theme = normalize_theme(theme)
    data = fetch_json(DATASETS_URL)
    info = data.get("themes", {}).get(theme)
    if not info or info.get("kind") != "theme":
        sys.exit(
            f"Theme '{theme}' not found in the repository: cannot tell which "
            f"wallpapers belong to it."
        )
    catalog = fetch_json(info["catalog"]["url"])
    repo = {w["filename"]: w for w in catalog["wallpapers"]}

    dest = os.path.join(DEST_BASE, theme)
    if not os.path.isdir(dest):
        sys.exit(f"No wallpapers installed for theme '{theme}'.")

    if collection or wallpaper:
        if collection and wallpaper:
            selected = select_collection(list(repo.values()), theme, collection)
            if selected is None:
                collections = sorted({w["collection"] for w in repo.values()})
                sys.exit(
                    f"No collection '{collection}' in theme '{theme}'. Available "
                    f"collections: {', '.join(collections) or 'none'}."
                )
            matches = select_wallpaper(selected, theme, wallpaper)
            to_remove = {matches[0]["filename"]}
        elif collection:
            selected = select_collection(list(repo.values()), theme, collection)
            if selected is not None:
                to_remove = {w["filename"] for w in selected}
            else:
                matches = select_wallpaper(list(repo.values()), theme, collection)
                to_remove = {matches[0]["filename"]}
        else:
            matches = select_wallpaper(list(repo.values()), theme, wallpaper)
            to_remove = {matches[0]["filename"]}
        removed = remove_from_dir(dest, to_remove, f"for theme '{theme}'")
        if not removed:
            print(f"No matching wallpaper is installed for theme '{theme}'.")
    else:
        to_remove = set(repo)
        remove_from_dir(dest, to_remove, f"for theme '{theme}'")
    refresh_bg_cache()


def cmd_remove_all():
    data = fetch_json(DATASETS_URL)
    themes = data.get("themes", {})

    if not os.path.isdir(DEST_BASE):
        sys.exit("No wallpapers installed (backgrounds folder missing).")

    total = 0
    found_any = False
    for theme in sorted(os.listdir(DEST_BASE)):
        dest = os.path.join(DEST_BASE, theme)
        if not os.path.isdir(dest):
            continue
        info = themes.get(theme)
        if not info or info.get("kind") != "theme":
            print(f"Skipping non-theme folder '{theme}'.")
            continue
        catalog = fetch_json(info["catalog"]["url"])
        to_remove = {w["filename"] for w in catalog["wallpapers"]}
        removed = remove_from_dir(dest, to_remove, "in repository")
        total += removed
        found_any = True

    if not found_any:
        print("No repository theme folders found under " + DEST_BASE + ".")
        return
    print(f"Removed {total} wallpapers in total.")
    refresh_bg_cache()


def main():
    parser = argparse.ArgumentParser(
        description="Manage Omarchy wallpapers from this repository"
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    p_install = sub.add_parser("install", help="install a theme's wallpapers into Omarchy")
    p_install.add_argument("theme", help='theme folder name, e.g. "osaka-jade"')
    p_install.add_argument(
        "collection",
        nargs="?",
        help='collection to restrict to, e.g. "countries"',
    )
    p_install.add_argument(
        "wallpaper",
        nargs="?",
        help='single wallpaper name or code, e.g. "Italy" or "IT"',
    )
    p_install.set_defaults(func=lambda a: cmd_install(a.theme, a.collection, a.wallpaper))

    p_update = sub.add_parser("update", help="re-install a theme's wallpapers (same as install)")
    p_update.add_argument("theme", help='theme folder name, e.g. "osaka-jade"')
    p_update.add_argument(
        "collection",
        nargs="?",
        help='collection to restrict to, e.g. "countries"',
    )
    p_update.add_argument(
        "wallpaper",
        nargs="?",
        help='single wallpaper name or code, e.g. "Italy" or "IT"',
    )
    p_update.set_defaults(func=lambda a: cmd_install(a.theme, a.collection, a.wallpaper))

    p_list = sub.add_parser(
        "list", help="list themes, or the wallpapers of a theme (list <theme> [collection])"
    )
    p_list.add_argument("theme", nargs="?", help='theme folder name, e.g. "osaka-jade"')
    p_list.add_argument(
        "target", nargs="?", help='collection to list, e.g. "countries"'
    )
    p_list.set_defaults(func=lambda a: cmd_list(a.theme, a.target))

    p_remove = sub.add_parser("remove", help="remove a theme's installed wallpapers")
    p_remove.add_argument(
        "--all",
        action="store_true",
        help="remove every theme's installed wallpapers",
    )
    p_remove.add_argument("theme", nargs="?", help='theme folder name, e.g. "osaka-jade"')
    p_remove.add_argument(
        "collection",
        nargs="?",
        help='collection to restrict to, e.g. "countries"',
    )
    p_remove.add_argument(
        "wallpaper",
        nargs="?",
        help='single wallpaper name or code, e.g. "Italy" or "IT"',
    )
    p_remove.set_defaults(
        func=lambda a: cmd_remove_all() if a.all else cmd_remove(a.theme, a.collection, a.wallpaper)
    )

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()