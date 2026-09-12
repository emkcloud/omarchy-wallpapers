#!/usr/bin/env python3
"""End-to-end deterministic test for scripts/wallpapers.py.

Runs install / update / list / remove inside an isolated sandbox under
working/generate-temp/testing (HOME redirected there), verifies every phase
against the local datasets catalogs, prints a markdown summary table and exits
non-zero if any phase fails.

The sandbox lives in the repository's scratch area (working/generate-temp/,
gitignored) so no system paths are touched; it is deleted before the test runs.
The real Omarchy configuration is never touched. Real wallpapers are downloaded
from GitHub, so network access is required.

It can run every step in one shot, or a single step at a time (recommended when
driving the test from an agent, so each step can be tracked separately):

Usage:
    python3 testing/wallpapers_installer.py                  # run every step
    python3 testing/wallpapers_installer.py --step <name>    # run one step
    python3 testing/wallpapers_installer.py --list-steps     # list the steps
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "wallpapers.py")
DATASETS_JSON = os.path.join(REPO, "datasets", "datasets.json")
SANDBOX = os.path.join(REPO, "working", "generate-temp", "testing")
OMARCHY_ROOT = os.path.join(SANDBOX, ".config", "omarchy")
BACKGROUNDS = os.path.join(OMARCHY_ROOT, "backgrounds")
RESULTS_FILE = os.path.join(SANDBOX, "results.json")
FAKE_BIN = os.path.join(SANDBOX, ".local", "bin")
FAKE_OMARCHY = os.path.join(FAKE_BIN, "omarchy")
STATE_DIR = os.path.join(SANDBOX, ".local", "state", "omarchy", "current")
CURRENT_BG_LINK = os.path.join(STATE_DIR, "background")
OMARCHY_CALLS = os.path.join(STATE_DIR, ".omarchy-calls.log")

FAKE_OMARCHY_SRC = """#!/usr/bin/env python3
import os
import sys

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, ".local", "state", "omarchy", "current")
LINK = os.path.join(STATE, "background")
LOG = os.path.join(STATE, ".omarchy-calls.log")
EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
        ".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi"}

args = sys.argv[1:]
os.makedirs(STATE, exist_ok=True)
with open(LOG, "a") as f:
    f.write(" ".join(args) + "\\n")

if args[:3] == ["theme", "bg", "next"]:
    theme = ""
    name_file = os.path.join(STATE, "theme.name")
    if os.path.isfile(name_file):
        theme = open(name_file).read().strip()
    directories = [
        os.path.join(STATE, "theme", "backgrounds"),
        os.path.join(HOME, ".config", "omarchy", "backgrounds", theme),
    ]
    files = []
    for directory in directories:
        if os.path.isdir(directory):
            for name in os.listdir(directory):
                if os.path.splitext(name)[1].lower() in EXTS:
                    files.append(os.path.join(directory, name))
    files.sort()
    if files:
        if os.path.lexists(LINK):
            os.remove(LINK)
        os.symlink(files[0], LINK)
sys.exit(0)
"""

STEPS = ["setup", "install", "verify", "update", "list", "remove", "summary"]


def catalog(theme):
    with open(os.path.join(REPO, "datasets", theme, "catalog.json")) as f:
        return json.load(f)["wallpapers"]


def themes():
    with open(DATASETS_JSON) as f:
        data = json.load(f)
    return sorted(
        name for name, item in data["themes"].items() if item["kind"] == "theme"
    )


def run(*args, with_omarchy=False):
    env = dict(os.environ, HOME=SANDBOX)
    if with_omarchy:
        env["PATH"] = FAKE_BIN + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(
        [sys.executable, SCRIPT, *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def count_webp(theme):
    root = os.path.join(BACKGROUNDS, theme)
    if not os.path.isdir(root):
        return 0
    return sum(1 for _, _, files in os.walk(root) for f in files if f.endswith(".webp"))


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def installed_ok(theme):
    root = os.path.join(BACKGROUNDS, theme)
    expected = {w["filename"]: w["sha256"] for w in catalog(theme)}
    if not os.path.isdir(root):
        return False
    installed = {f for _, _, fs in os.walk(root) for f in fs}
    return installed == set(expected)


def check(results, name, expected, actual, ok):
    results.append((name, expected, actual, ok))


def verify_integrity(results, themes):
    for theme in themes:
        entries = catalog(theme)
        expected_names = {w["filename"] for w in entries}
        root = os.path.join(BACKGROUNDS, theme)
        installed = {f for _, _, fs in os.walk(root) for f in fs}
        missing = sorted(expected_names - installed)
        extra = sorted(installed - expected_names)
        ok = not missing and not extra
        check(
            results,
            f"verify files {theme}",
            f"{len(expected_names)} exact set",
            f"{len(installed)} ({len(missing)} missing, {len(extra)} extra)",
            ok,
        )
        sample = entries[:2] + entries[-2:]
        bad = []
        for w in sample:
            path = os.path.join(root, w["filename"])
            if not os.path.isfile(path) or sha256_of(path) != w["sha256"]:
                bad.append(w["filename"])
        check(
            results,
            f"verify sha256 {theme}",
            f"{len(sample)} match",
            f"{len(sample) - len(bad)} match",
            not bad,
        )


def load_results():
    if not os.path.isfile(RESULTS_FILE):
        return []
    with open(RESULTS_FILE) as f:
        return [tuple(r) for r in json.load(f)]


def save_results(results):
    os.makedirs(SANDBOX, exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump([list(r) for r in results], f)


def require_sandbox():
    if not os.path.isdir(OMARCHY_ROOT):
        sys.exit("Sandbox not set up: run `--step setup` first.")


def print_rows(rows):
    if not rows:
        return
    print()
    print("| Phase | Expected | Actual | Status |")
    print("|-------|----------|--------|--------|")
    for name, expected, actual, ok in rows:
        print(f"| {name} | {expected} | {actual} | {'OK' if ok else 'FAILED'} |")


def step_setup(results):
    if os.path.isdir(SANDBOX):
        shutil.rmtree(SANDBOX)
    theme_list = themes()
    for t in theme_list:
        os.makedirs(os.path.join(OMARCHY_ROOT, "themes", t), exist_ok=True)
    os.makedirs(FAKE_BIN, exist_ok=True)
    with open(FAKE_OMARCHY, "w") as f:
        f.write(FAKE_OMARCHY_SRC)
    os.chmod(FAKE_OMARCHY, 0o755)
    check(results, "setup sandbox", f"{len(theme_list)} theme dirs",
          f"{len(theme_list)} theme dirs", True)
    return results


def step_install(results):
    require_sandbox()
    theme_list = themes()
    for theme in theme_list:
        code, out, err = run("install", theme)
        count = count_webp(theme)
        check(
            results,
            f"install {theme}",
            "250 files, exit 0",
            f"{count} files, exit {code}",
            code == 0 and "Installed 250 wallpapers" in out and count == 250,
        )
    col = sorted({w["collection"] for w in catalog("tokyo-night")})[0]
    code, out, err = run("install", "tokyo-night", col)
    count = count_webp("tokyo-night")
    check(
        results,
        f"install tokyo-night {col} (collection)",
        "250 files",
        f"{count} files",
        code == 0 and "Installed 250 wallpapers" in out and count == 250,
    )
    sel = next(w for w in catalog("tokyo-night") if w.get("code"))
    code, out, err = run("install", "tokyo-night", sel["code"])
    count = count_webp("tokyo-night")
    check(
        results,
        f"install {sel['code']} (selector)",
        "Installed 1 wallpapers, 250 files",
        f"{count} files, exit {code}",
        code == 0 and "Installed 1 wallpapers" in out and count == 250,
    )
    code, out, err = run("install", "tokyo-night", sel["collection"], sel["code"])
    count = count_webp("tokyo-night")
    check(
        results,
        f"install tokyo-night {sel['collection']} {sel['code']} (collection+wallpaper)",
        "Installed 1 wallpapers, 250 files",
        f"{count} files, exit {code}",
        code == 0 and "Installed 1 wallpapers" in out and count == 250,
    )
    return results


def step_verify(results):
    require_sandbox()
    verify_integrity(results, themes())
    return results


def step_update(results):
    require_sandbox()
    code, out, err = run("update", "tokyo-night")
    count = count_webp("tokyo-night")
    check(
        results,
        "update tokyo-night",
        "250 files (no dup), exit 0",
        f"{count} files, exit {code}",
        code == 0 and count == 250,
    )
    return results


def step_list(results):
    require_sandbox()
    theme_list = themes()
    code, out, err = run("list")
    listed = [l for l in out.splitlines() if l.strip()]
    check(
        results,
        "list themes",
        theme_list,
        listed,
        code == 0 and listed == theme_list,
    )
    for theme in theme_list:
        code, out, err = run("list", theme)
        names = sorted(l for l in out.splitlines() if l.strip())
        expected = sorted(w["filename"] for w in catalog(theme))
        check(
            results,
            f"list {theme}",
            f"{len(expected)} filenames",
            f"{len(names)} filenames",
            code == 0 and names == expected,
        )
    col = sorted({w["collection"] for w in catalog("tokyo-night")})[0]
    code, out, err = run("list", "tokyo-night", col)
    names = sorted(l for l in out.splitlines() if l.strip())
    expected = sorted(
        w["filename"] for w in catalog("tokyo-night") if w["collection"] == col
    )
    check(
        results,
        f"list tokyo-night {col}",
        f"{len(expected)} filenames",
        f"{len(names)} filenames",
        code == 0 and names == expected,
    )
    return results


def write_active_background(theme, filename):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "theme.name"), "w") as f:
        f.write(theme)
    shipped = os.path.join(STATE_DIR, "theme", "backgrounds")
    os.makedirs(shipped, exist_ok=True)
    source = os.path.join(BACKGROUNDS, theme, filename)
    if not os.path.isfile(source):
        return
    default = os.path.join(shipped, "omarchy-theme-default.webp")
    if not os.path.isfile(default):
        shutil.copyfile(source, default)
    if os.path.lexists(CURRENT_BG_LINK):
        os.remove(CURRENT_BG_LINK)
    os.symlink(source, CURRENT_BG_LINK)


def background_ok():
    if not os.path.islink(CURRENT_BG_LINK):
        return False
    return os.path.exists(os.path.realpath(CURRENT_BG_LINK))


def omarchy_calls():
    if not os.path.isfile(OMARCHY_CALLS):
        return ""
    with open(OMARCHY_CALLS) as f:
        return f.read()


def step_remove(results):
    require_sandbox()
    sel = next(w for w in catalog("tokyo-night") if w.get("code"))
    col = sel["collection"]
    write_active_background("tokyo-night", sel["filename"])
    code, out, err = run("remove", "tokyo-night", col, sel["code"])
    count = count_webp("tokyo-night")
    check(
        results,
        f"remove tokyo-night {col} {sel['code']} (collection+wallpaper)",
        "249 files",
        f"{count} files",
        code == 0 and count == 249,
    )
    check(
        results,
        "reset background after remove (manual fallback)",
        "valid background",
        "valid" if background_ok() else "dangling",
        code == 0 and background_ok(),
    )
    sel2 = next(
        w for w in catalog("tokyo-night") if w.get("code") and w["id"] != sel["id"]
    )
    write_active_background("tokyo-night", sel2["filename"])
    code, out, err = run("remove", "tokyo-night", sel2["code"], with_omarchy=True)
    count = count_webp("tokyo-night")
    check(
        results,
        f"remove tokyo-night {sel2['code']} (by code)",
        "248 files",
        f"{count} files",
        code == 0 and count == 248,
    )
    check(
        results,
        "reset background after remove (omarchy theme bg next)",
        "valid background",
        "valid" if background_ok() else "dangling",
        code == 0 and background_ok() and "theme bg next" in omarchy_calls(),
    )
    sel3 = next(w for w in catalog("osaka-jade") if w.get("code"))
    code, out, err = run("remove", "osaka-jade", sel3["code"])
    count = count_webp("osaka-jade")
    check(
        results,
        f"remove osaka-jade {sel3['code']} (by code)",
        "249 files",
        f"{count} files",
        code == 0 and count == 249,
    )
    code, out, err = run("remove", "gruvbox")
    check(
        results,
        "remove gruvbox",
        "folder removed",
        "folder removed" if not os.path.isdir(os.path.join(BACKGROUNDS, "gruvbox"))
        else "folder present",
        code == 0 and not os.path.isdir(os.path.join(BACKGROUNDS, "gruvbox")),
    )
    sel_all = next(
        w for w in catalog("tokyo-night")
        if w.get("code") and w["id"] not in {sel["id"], sel2["id"]}
    )
    write_active_background("tokyo-night", sel_all["filename"])
    code, out, err = run("remove", "--all")
    remaining = [
        d for d in os.listdir(BACKGROUNDS) if os.path.isdir(os.path.join(BACKGROUNDS, d))
    ] if os.path.isdir(BACKGROUNDS) else []
    check(
        results,
        "remove --all",
        "backgrounds empty",
        f"{len(remaining)} dir(s)",
        code == 0 and not remaining,
    )
    check(
        results,
        "reset background after remove --all",
        "valid background",
        "valid" if background_ok() else "dangling",
        code == 0 and background_ok(),
    )
    return results


def run_summary(results, keep):
    print()
    print("| Phase | Expected | Actual | Status |")
    print("|-------|----------|--------|--------|")
    failures = 0
    for name, expected, actual, ok in results:
        print(f"| {name} | {expected} | {actual} | {'OK' if ok else 'FAILED'} |")
        if not ok:
            failures += 1
    print()
    if failures:
        print(f"{failures} phase(s) FAILED.")
    else:
        print("All phases OK.")
    if not keep:
        shutil.rmtree(SANDBOX, ignore_errors=True)
    if failures:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--step",
        help="run only one step of the test (see --list-steps)",
    )
    parser.add_argument(
        "--list-steps",
        action="store_true",
        help="list the available steps and exit",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the sandbox after the run (for debugging)",
    )
    args = parser.parse_args()

    if args.list_steps:
        for s in STEPS:
            print(s)
        return

    step_funcs = {
        "setup": step_setup,
        "install": step_install,
        "verify": step_verify,
        "update": step_update,
        "list": step_list,
        "remove": step_remove,
    }

    if args.step:
        if args.step == "summary":
            run_summary(load_results(), args.keep)
            return
        if args.step not in step_funcs:
            sys.exit(
                f"Unknown step '{args.step}'. Available steps: {', '.join(STEPS)}"
            )
        results = load_results()
        before = len(results)
        results = step_funcs[args.step](results)
        save_results(results)
        new_rows = results[before:]
        print_rows(new_rows)
        if any(not ok for _, _, _, ok in new_rows):
            sys.exit(1)
        return

    results = []
    for s in STEPS:
        if s == "summary":
            break
        results = step_funcs[s](results)
    run_summary(results, args.keep)


if __name__ == "__main__":
    main()