---
name: omarchy-wallpapers-generate-optimization
description: Optimize the WebP images of the Omarchy wallpapers in this repository losslessly (wallpapers in images/, masters in masters/ and previews in previews/) via scripts/generate_optimization.py. Use when asked to optimize wallpapers/masters/previews, check if images are already optimized, or re-optimize after adding/editing images. Covers the plan-first step (group list + work plan), the recommended parallel execution (one subagent per group via the Task tool, with a live todo list), the sequential dispatcher fallback, verification, and the resume behavior via the per-group optimization.json manifest. This skill only writes the optimization manifests: it does NOT regenerate the datasets (that is generate_dataset.py, see omarchy-wallpapers-generate-datasets).
---

# Omarchy Wallpapers Image Optimization

## Goal

Losslessly re-encode WebP wallpapers (`images/`), masters (`masters/`) and previews (`previews/`) with `scripts/generate_optimization.py` to reduce file size. **Lossless only** — never lossy re-encodes; pixels must never change (verified structurally: dimensions, pixel difference = 0, size). Previews are lossy q80, so they typically report `no size gain` and are left untouched, but they are covered by the same manifest.

## Non-negotiables

- **Optimization only.** This skill writes only the per-group `optimization.json` manifests. It never regenerates the datasets — that is `omarchy-wallpapers-generate-datasets` / `scripts/generate_dataset.py`.
- **No temp files in the repository.** Temp files go exclusively in `working/generate-temp/` (gitignored). The script already does this; you must never write scratch files inside `images/`, `masters/`, `previews/`, `datasets/` or anywhere else in the repo.
- **Never edit manifests by hand.** `datasets/<group>/optimization.json` is written only by the script.

## What a group is

Optimization runs on groups, not on a global list:
- **`masters`** (fixed, processed first): `masters/colors/` + `masters/grayscale/` → `datasets/masters/optimization.json`.
- **One group per theme from `images/`** (dynamic, today N tomorrow more): `images/<theme>/` + `previews/<theme>/` → `datasets/<theme>/optimization.json`.

The group list is computed at run time: masters first, then the themes found in `images/`, only groups that contain at least one WebP.

## The manifest (resume mechanism)

- `datasets/<group>/optimization.json` maps each relative path to `{sha256, size}`.
- A file is skipped when its cached `sha256` matches; otherwise it is (re-)optimized.
- The manifest is persisted every `--save-every` (default 50) files and at the end of a group, so an interrupted run resumes without redoing everything.
- No global state file: the plan always reflects reality (manifest present = previously optimized; absent = to do).

## Script modes — `scripts/generate_optimization.py`

| Mode | Invocation | Behavior |
|---|---|---|
| Worker | `--group <group>` | Processes a single group only (theme name or `masters`), writes only its own manifest + result. |
| Dispatcher | no `--group` | Lists groups (masters first, then themes), prints the plan, runs one worker per group. |
| Plan only | `--plan-only` | Prints group list + work plan, launches **no** worker. |
| Parallel groups | `--concurrency N` | Dispatcher runs up to N group-workers at once (per-group logs in `working/generate-temp/optimization/`). |
| Clean temp | `--clean` | Deletes this script's dedicated temp folder (`working/generate-temp/optimization/`) and exits. |

Other options: `--workers N` (intra-group parallelism, default 8), `--method N` (libwebp method, default 6), `--force` (ignore manifest), `--dry-run` (report, change nothing), `--limit N`, `--save-every N`, `--report-every N`.

The script keeps its temporary files in a dedicated folder `working/generate-temp/optimization/` (gitignored) and wipes it at the start of every full dispatcher run (not for `--group` workers or `--plan-only`).

## Recommended workflow (parallel subagents + live todo list)

1. **Plan first, no work yet:**
   ```bash
   python3 scripts/generate_optimization.py --plan-only
   ```
   This prints the group table (group, WebP count, `optimization.json` YES/NO) and the per-group plan (`to do` / `already done`). Show it to the user and confirm before optimizing.

2. **Set up the todo list** (TodoWrite) with one step per group plus plan and total, e.g.:
   - Analysis + plan (`--plan-only`)
   - Optimize: masters (500)
   - Optimize: gruvbox (500)
   - ... one per theme ...
   - Final summary
   Mark the plan step completed, mark each group `in_progress` as it starts. The user watches this panel live.

3. **Clean the temp folder** (fresh start, avoids stale results):
   ```bash
   python3 scripts/generate_optimization.py --clean
   ```

4. **Run one subagent per group, in parallel** (Task tool, `general` type). Each subagent runs exactly:
   ```bash
   python3 scripts/generate_optimization.py --group <group>
   ```
   Launch all of them in a single message so they run concurrently. Each subagent reports back the verbatim summary line `[<group>] N files | M skipped | K optimized | L already optimal | E errors | B bytes saved` plus any `ERROR` lines and the exit code.

5. **Wait for ALL subagents** before presenting the total. Mark each todo `completed` as its subagent returns.

6. **Verify on disk:**
   ```bash
   ls datasets/*/optimization.json datasets/masters/optimization.json | wc -l   # must equal the number of groups
   git status --short | grep tmp                                                # must be empty
   ```
   Optimization is lossless, so previews stay valid and do NOT need regeneration.

7. **Report the final summary** as a table `Group | Optimized | Already optimal | Skipped | Errors | Bytes saved` plus the grand total. Errors must be zero.

## Sequential fallback (no subagents)

If parallel subagents are not desired, run the dispatcher directly — it streams everything live, one group at a time (default `--concurrency 1`, masters first), and prints the same per-group lines plus the final `Final summary` table:
```bash
python3 scripts/generate_optimization.py
```

## Behavior details

- **Dispatcher output:** starts with the group analysis table, then per-group progress, then the final `Final summary` table. With `--concurrency N > 1` the worker output is streamed live to the terminal (each line prefixed with `[<group>]`) and also saved to `working/generate-temp/optimization/optimize-<group>.log`; sequential mode prints `[i/N] <group> ...` before each group. Masters is always first in the group list.
- **Per-group result files:** each worker writes `working/generate-temp/optimization/optimize-<group>.result.json` (skipped/optimized/already-optimal/errors/bytes saved). The dispatcher aggregates the final table from these.
- **Empty group:** a group with no WebP is reported as "No WebP found" and skipped with no error.
- **Errors:** any file that fails is listed as `ERROR <path>: <detail>`; the worker exits 1 if a group had errors. The dispatcher continues with the other groups and reports failed groups at the end.

## Datasets separation

After the optimization is correct, regenerating the JSON datasets is a **separate, explicit step** — `python3 scripts/generate_dataset.py`. The optimization workflow never calls it.

## Rules

- Lossless re-compression only (Pillow/libwebp). Content must never change (pixel difference = 0).
- Only regenerate via the script, never edit the manifests by hand.
- No temp files in the repository: only `working/generate-temp/`.
- Do **not** commit unless the user explicitly asks.