# Skill: omarchy-wallpapers-test-installer

# Omarchy wallpapers.py Installer Test

## Goal

Prove that `scripts/wallpapers.py` works end-to-end (install / update / list / remove / remove --all) inside an isolated sandbox, without touching the real Omarchy configuration. The script is invoked with `HOME=<sandbox>` so the install destination (`~/.config/omarchy/backgrounds`) and the "theme installed in Omarchy" check (`~/.config/omarchy/themes/<theme>`) land inside the sandbox. Real wallpapers are downloaded from GitHub and verified against their sha256, so network access is required.

The sandbox lives in `working/generate-temp/testing/` (the repository's scratch area, gitignored), so no system paths are touched and the agent already has write permissions there. It is deleted before the test starts.

## Run the test step-by-step (recommended)

Do **not** launch the whole test in one shot. Instead, create a sequential todo list (one item per step, ordered) and run each step **one at a time** by calling `testing/wallpapers_installer.py --step <name>`, so the user can follow each task as it completes. Steps must run in order and **never in parallel** (each step depends on the sandbox state left by the previous one). After each step, mark its todo item completed; if a step fails, stop and report — do not continue, since later steps rely on the sandbox state.

The steps and the command for each:

1. `setup` — clean sandbox:
   `python3 testing/wallpapers_installer.py --step setup`
2. `install` — all install types:
   `python3 testing/wallpapers_installer.py --step install`
3. `verify` — check files and sha256:
   `python3 testing/wallpapers_installer.py --step verify`
4. `update` — all update types:
   `python3 testing/wallpapers_installer.py --step update`
5. `list` — all listing operations:
   `python3 testing/wallpapers_installer.py --step list`
6. `remove` — all remove types:
   `python3 testing/wallpapers_installer.py --step remove`
7. `summary` — final results:
   `python3 testing/wallpapers_installer.py --step summary`

Each step prints its own result rows and exits non-zero if that step fails. The `summary` step prints the complete table; present it to the user. To see the available steps: `python3 testing/wallpapers_installer.py --list-steps`.

## Run the test (single command)

The whole flow can also be automated in one command (quick runs / CI):

```bash
python3 testing/wallpapers_installer.py
```

It sets up the sandbox, installs **every theme** fully (catching missing/corrupt files for all of them), verifies the exact file set and sha256 per theme against the local `datasets/<theme>/catalog.json`, then tests update, list, collections (list/install/remove by collection), remove-by-code, reinstall-by-code (selector), install-by-collection+wallpaper, remove-by-collection+wallpaper, remove-full-theme and remove --all. It prints a `Phase | Expected | Actual | Status` table and exits 0 only if every phase passes; it wipes the sandbox at the end.

Useful flags:
- `--step <name>` — run a single step.
- `--list-steps` — list the available steps.
- `--keep` — keep the sandbox after the run for debugging.

## Rules

- Never touch the real `~/.config/omarchy`; the sandbox (`working/generate-temp/testing/`) is the only place written.
- Do NOT edit `scripts/wallpapers.py` during the test (this skill verifies it, it does not modify it).
- The test script reads only local catalogs (`datasets/`) and the remote datasets.json via `wallpapers.py`; do not edit `datasets/` during the test either.
- Run the steps sequentially (never in parallel) and stop at the first failure.
- If network is unavailable, the install phase fails — report it as such and stop.
- The skill does not commit: the user requests the commit explicitly.