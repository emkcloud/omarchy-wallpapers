#!/usr/bin/env python3
"""Manage Omarchy wallpapers from this repository.

Subcommands:
    install <theme> [wallpaper]   Install a theme's wallpapers into Omarchy
                                  (downloads the images directly from GitHub,
                                  in parallel). An optional wallpaper name
                                  (e.g. "Italy" or "IT") installs only it.
    update <theme> [wallpaper]    Re-install a theme's wallpapers (same as
                                  install).
    list [theme]                  List the themes, or the wallpapers of a theme.
    remove <theme> [wallpaper]    Remove a theme's (or a single wallpaper's)
                                  installed wallpapers from Omarchy.

Checks are done before any download: the theme must exist both in this
repository (via datasets/datasets.json) and in Omarchy (stock or user theme).
Downloads happen only when both checks pass; files already up to date
(matching sha256) are skipped. install, update and remove refresh the Omarchy
background cache (`omarchy theme bg cache`) automatically.

Usage:
    python3 wallpapers.py install osaka-jade
    python3 wallpapers.py list

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


def refresh_bg_cache():
    if shutil.which("omarchy") is None:
        return
    try:
        subprocess.run(["omarchy", "theme", "bg", "cache"], check=True)
        print("Background cache refreshed.")
    except subprocess.CalledProcessError as exc:
        print(f"Could not refresh the background cache: {exc}", file=sys.stderr)


def cmd_install(theme, wallpaper=None):
    theme = normalize_theme(theme)
    data = fetch_json(DATASETS_URL)
    collections = data.get("collections", {})

    info = collections.get(theme)
    if not info or info.get("kind") != "theme":
        themes = sorted(
            name for name, item in collections.items() if item.get("kind") == "theme"
        )
        sys.exit(
            f"Theme '{theme}' not found. Available themes: {', '.join(themes) or 'none'}"
        )

    if not installed_in_omarchy(theme):
        sys.exit(
            f"Theme '{theme}' is not installed in Omarchy. "
            f"Install it first (`omarchy theme install <url>` or "
            f"create ~/.config/omarchy/themes/{theme}/)."
        )

    catalog = fetch_json(info["catalog"]["url"])
    wallpapers = catalog["wallpapers"]
    if wallpaper:
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


def cmd_list(theme=None):
    data = fetch_json(DATASETS_URL)
    collections = data.get("collections", {})

    if theme is None:
        for name in sorted(
            n for n, item in collections.items() if item.get("kind") == "theme"
        ):
            print(name)
        return

    theme = normalize_theme(theme)
    info = collections.get(theme)
    if not info or info.get("kind") != "theme":
        themes = sorted(
            n for n, item in collections.items() if item.get("kind") == "theme"
        )
        sys.exit(
            f"Theme '{theme}' not found. Available themes: {', '.join(themes) or 'none'}"
        )

    catalog = fetch_json(info["catalog"]["url"])
    for wallpaper in catalog["wallpapers"]:
        print(wallpaper["filename"])


def cmd_remove(theme, wallpaper=None):
    theme = normalize_theme(theme)
    data = fetch_json(DATASETS_URL)
    info = data.get("collections", {}).get(theme)
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

    if wallpaper:
        matches = select_wallpaper(list(repo.values()), theme, wallpaper)
        to_remove = {matches[0]["filename"]}
    else:
        to_remove = set(repo)

    removed = 0
    kept = 0
    for name in sorted(os.listdir(dest)):
        path = os.path.join(dest, name)
        if name in to_remove and os.path.isfile(path):
            os.remove(path)
            removed += 1
        else:
            kept += 1

    if not removed:
        if wallpaper:
            print(f"No matching wallpaper is installed for theme '{theme}'.")
        else:
            print(f"No repository wallpapers to remove for theme '{theme}'.")
        return

    if not os.listdir(dest):
        os.rmdir(dest)
        print(f"Removed {removed} wallpaper(s) and the empty {dest} folder.")
    else:
        print(
            f"Removed {removed} wallpaper(s) from {dest} "
            f"(kept {kept} non-repository file(s))."
        )
    refresh_bg_cache()


def main():
    parser = argparse.ArgumentParser(
        description="Manage Omarchy wallpapers from this repository"
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    p_install = sub.add_parser("install", help="install a theme's wallpapers into Omarchy")
    p_install.add_argument("theme", help='theme folder name, e.g. "osaka-jade"')
    p_install.add_argument(
        "wallpaper", nargs="?", help='single wallpaper, e.g. "Italy" or "IT"'
    )
    p_install.set_defaults(func=lambda a: cmd_install(a.theme, a.wallpaper))

    p_update = sub.add_parser("update", help="re-install a theme's wallpapers (same as install)")
    p_update.add_argument("theme", help='theme folder name, e.g. "osaka-jade"')
    p_update.add_argument(
        "wallpaper", nargs="?", help='single wallpaper, e.g. "Italy" or "IT"'
    )
    p_update.set_defaults(func=lambda a: cmd_install(a.theme, a.wallpaper))

    p_list = sub.add_parser(
        "list", help="list themes, or the wallpapers of a theme (list <theme>)"
    )
    p_list.add_argument("theme", nargs="?", help='theme folder name, e.g. "osaka-jade"')
    p_list.set_defaults(func=lambda a: cmd_list(a.theme))

    p_remove = sub.add_parser("remove", help="remove a theme's installed wallpapers")
    p_remove.add_argument("theme", help='theme folder name, e.g. "osaka-jade"')
    p_remove.add_argument(
        "wallpaper", nargs="?", help='single wallpaper, e.g. "Italy" or "IT"'
    )
    p_remove.set_defaults(func=lambda a: cmd_remove(a.theme, a.wallpaper))

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()