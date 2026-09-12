---
name: omarchy-wallpapers-generate-previews
description: Generate or revalidate the WebP previews in previews/ from the themed wallpapers in images/. Covers the plan-first step (theme list + work plan), the recommended parallel execution (one subagent per theme via the Task tool, with a live todo list), the sequential dispatcher fallback, verification, and the resume behavior via the per-theme previews.json manifest. Use whenever previews must be generated, checked, or regenerated after adding/removing wallpapers. This skill does NOT regenerate the datasets: that is the job of generate_dataset.py (see omarchy-wallpapers-generate-datasets).
---

# Omarchy Preview Generation

## Goal

Create/revalidate the small preview images in `previews/` for every wallpaper in `images/`. This skill is the **single entry point for preview work**. It creates **only** the preview files and the per-theme manifests; it never regenerates the JSON datasets.

## Non-negotiables

- **Previews only.** Never run `generate_dataset.py` from this workflow. Datasets are a separate step (`omarchy-wallpapers-generate-datasets` / `scripts/generate_dataset.py`).
- **No temp files in the repository.** Temp files go exclusively in `working/generate-temp/` (gitignored). The scripts already do this; you must never write scratch files inside `images/`, `masters/`, `previews/`, `datasets/` or anywhere else in the repo.
- **Never edit by hand.** Previews are written only by `scripts/generate_previews.py`; `datasets/<theme>/previews.json` is only written by that script. Never hand-edit `previews/` or the manifests.

## What a preview is

- One preview per wallpaper group. A group = all files sharing the same base name (resolution suffix stripped): `omarchy-country-AD-Andorra-2K/4K/8K.webp` → base `omarchy-country-AD-Andorra`.
- Derived from the **lowest resolution** variant of the group.
- Fixed size 640x360, lossy WebP q80.
- Written to `previews/<theme>/<collection>/<base>-preview.webp`.

## The manifest (resume mechanism)

- `datasets/<theme>/previews.json` maps each source file to its `sha256` + the produced preview's hash/size.
- A source is "already ok" (skipped) only when the cached sha256 matches **and** the preview file exists on disk. Otherwise it is generated.
- The manifest is persisted every `--save-every` (default 50) generated previews and at the end of a theme, so an interrupted run resumes without redoing everything.
- No global state file is needed: the plan always reflects reality (files on disk). A missing manifest just means "to process" (create from scratch).

## Script modes — `scripts/generate_previews.py`

| Mode | Invocation | Behavior |
|---|---|---|
| Worker | `--theme <theme>` | Processes a single theme only (scan its folder, read its own manifest, generate, write result). |
| Dispatcher | no `--theme` | Lists themes in `images/`, prints the plan, runs one worker per theme. |
| Plan only | `--plan-only` | Prints theme list + work plan, launches **no** worker. |
| Parallel themes | `--concurrency N` | Dispatcher runs up to N theme-workers at once (per-theme logs in `working/generate-temp/previews/`). |
| Clean temp | `--clean` | Deletes this script's dedicated temp folder (`working/generate-temp/previews/`) and exits. |

Other options: `--workers N` (intra-theme parallelism, default 8), `--force` (ignore manifest), `--dry-run` (report, write nothing), `--limit N`, `--save-every N`, `--report-every N`.

The script keeps its temporary files in a dedicated folder `working/generate-temp/previews/` (gitignored) and wipes it at the start of every full dispatcher run (not for `--theme` workers or `--plan-only`).

## Recommended workflow (parallel subagents + live todo list)

1. **Plan first, no work yet:**
   ```bash
   python3 scripts/generate_previews.py --plan-only
   ```
   This prints the theme table (theme, image count, `previews.json` YES/NO) and the per-theme plan (`already ok` / `to process`). Show it to the user and confirm before generating.

2. **Set up the todo list** (TodoWrite) with one step per theme, e.g.:
   - Theme analysis + plan (`--plan-only`)
   - Worker preview: gruvbox (250)
   - Worker preview: matte-black (250)
   - ... one per theme ...
   - Final summary
   Mark the plan step completed, mark each theme `in_progress` as it starts. The user watches this panel live.

3. **Clean the temp folder** (fresh start, avoids stale results):
   ```bash
   python3 scripts/generate_previews.py --clean
   ```

4. **Run one subagent per theme, in parallel** (Task tool, `general` type). Each subagent runs exactly:
   ```bash
   python3 scripts/generate_previews.py --theme <theme>
   ```
   Launch all of them in a single message so they run concurrently. Each subagent reports back the verbatim summary line `[<theme>] N images | M OK | K new previews generated | E errors` plus any `ERROR` lines and the exit code.

5. **Wait for ALL subagents** before presenting the total. Mark each todo `completed` as its subagent returns.

6. **Verify on disk:**
   ```bash
   find previews -name "*.webp" | wc -l        # must equal the expected total
   ls datasets/*/previews.json | wc -l          # must equal the number of themes
   git status --short | grep tmp                 # must be empty
   ```

7. **Report the final summary** as a table `Theme | OK | New | Errors` plus the grand total. Errors must be zero.

## Sequential fallback (no subagents)

If parallel subagents are not desired, run the dispatcher directly — it streams everything live, one theme at a time (default `--concurrency 1`), and prints the same per-theme lines plus the final `Final summary`:
```bash
python3 scripts/generate_previews.py
```

## Behavior details

- **Dispatcher output:** starts with the theme analysis table, then `[i/N] <theme> ...`, then per-theme progress, then the final `Final summary` table. With `--concurrency N > 1` it writes per-theme logs to `working/generate-temp/previews/previews-<theme>.log` and prints a `[done] <theme>` line for each.
- **Per-theme result files:** each worker writes `working/generate-temp/previews/previews-<theme>.result.json` (skipped/generated/errors/bytes). The dispatcher aggregates the final table from these.
- **Empty theme:** a theme with no valid WebP groups is reported as "No valid WebP" and skipped with no error.
- **Errors:** any preview that fails is listed as `ERROR <path>: <detail>`; the worker exits 1 if a theme had errors. The dispatcher continues with the other themes and reports failed themes at the end.

## Datasets separation

After the previews are correct, regenerating the JSON datasets is a **separate, explicit step** — `python3 scripts/generate_dataset.py` (which also generates missing previews itself, delegating to this script). The preview workflow never calls it.

## Rules

- Only regenerate via the scripts, never edit `previews/` or `datasets/<theme>/previews.json` by hand.
- No temp files in the repository: only `working/generate-temp/`.
- Missing `previews.json` for a theme is normal (`NO` in the plan): the worker creates it from scratch.
- Do **not** commit unless the user explicitly asks.