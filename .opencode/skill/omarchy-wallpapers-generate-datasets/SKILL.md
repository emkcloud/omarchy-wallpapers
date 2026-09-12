---
name: omarchy-wallpapers-generate-datasets
description: Full pipeline to regenerate the datasets: generate the missing/stale previews, optimize any pending WebP images and previews (lossless), and rebuild the JSON indexes in datasets/ (catalog.json, collections.json, datasets.json) from images/ and masters/. The dataset index generation itself uses the plan-first, parallel-subagent technique (one subagent per group, then a single aggregation step). Use whenever datasets/ and previews/ must be fully rebuilt, after adding/renaming/removing wallpapers, or after optimizing images. Entry point for "regenerate everything".
---

# Omarchy Dataset and Preview Generation

## Goal

Keep `datasets/` and `previews/` in sync with the wallpapers in `images/` and the masters in `masters/`. This skill is the **single entry point for a full regeneration**, running the whole pipeline in sequence:

1. Generate the missing/stale preview WebP files (`previews/<theme>/<collection>/<base>-preview.webp`, 640x360 lossy q80, derived from the lowest-resolution variant).
2. Optimize any pending images **and previews** (lossless) — so every asset is optimized before the datasets are built.
3. Generate the JSON indexes (`datasets/<theme>/catalog.json`, `collections.json`, `previews.json`, `optimization.json` kept by other scripts, and `datasets/datasets.json`).

Never edit the JSON by hand: regenerate with the scripts.

## Non-negotiables

- **Each script writes only its own outputs.** `generate_dataset.py` writes the JSON indexes only (never previews or optimization manifests). `generate_previews.py` and `generate_optimization.py` have their own dedicated skills.
- **No temp files in the repository.** Temp files go exclusively in `working/generate-temp/` (gitignored). Never write scratch files inside `images/`, `masters/`, `previews/`, `datasets/` or anywhere else.
- **Never edit manifests/indexes by hand.** `datasets/` is regenerated only by `scripts/generate_dataset.py`.

## What a group is

Dataset generation runs on **groups**:

- **`masters`** (fixed): `masters/colors/` → `datasets/masters/catalog.json` + `collections.json`.
- **One group per theme from `images/`** (dynamic): `images/<theme>/` → `datasets/<theme>/catalog.json` + `collections.json`.

The group list is computed at run time: masters first, then the themes found in `images/`.

The top-level `datasets/datasets.json` is **not** a group: it is assembled once, after all group workers have written their catalogs, in the **aggregation** step (it needs the cross-theme preview de-duplication). Groups never touch `datasets.json`.

## Script modes — `scripts/generate_dataset.py`

| Mode | Invocation | Behavior |
|---|---|---|
| Worker | `--group <group>` | Generates `catalog.json` + `collections.json` for one group only (a theme name or `masters`). |
| Dispatcher | no `--group` | Lists groups (masters first), prints the plan, checks/generates missing previews, runs one worker per group (optionally parallel), then aggregates `datasets.json`. |
| Plan only | `--plan-only` | Prints the group table + work plan, launches **no** worker and does **not** aggregate. |
| Aggregate only | `--aggregate-only` | Assembles `datasets.json` from the catalogs already on disk and removes stale theme folders. No workers, no preview check. |
| Parallel groups | `--concurrency N` | Dispatcher runs up to N group-workers at once (per-group logs in `working/generate-temp/dataset/`). |
| Clean temp | `--clean` | Deletes this script's dedicated temp folder (`working/generate-temp/dataset/`) and exits. |

Other options: `--no-previews` (skip the missing-previews check/generation in the dispatcher).

The script keeps its temporary files in a dedicated folder `working/generate-temp/dataset/` (gitignored) and wipes it at the start of every full dispatcher run (not for `--group` workers, `--plan-only` or `--aggregate-only`).

## Recommended workflow (parallel subagents + live todo list)

Steps 1 and 2 (previews, optimization) are their own skills (`omarchy-wallpapers-generate-previews`, `omarchy-wallpapers-generate-optimization`), which already follow this same parallel technique. Step 3 (datasets) follows it too:

1. **Plan first, no work yet:**
   ```bash
   python3 scripts/generate_dataset.py --plan-only
   ```
   This prints the group table (group, item count, `catalog.json` YES/NO) and the per-group work plan. Show it to the user and confirm.

2. **Set up the todo list** (TodoWrite) with one step per group plus the aggregation and the total, e.g.:
   - Analysis + plan
   - Dataset: masters (250)
   - Dataset: gruvbox (250)
   - ... one per theme ...
   - Assemble datasets.json
   - Final summary
   Use these exact labels: the plan step is just `Analysis + plan` and the aggregation step is just `Assemble datasets.json`, with no command options shown. Mark the plan step completed, mark each group `in_progress` as it starts.

3. **Clean the temp folder** (fresh start, avoids stale results):
   ```bash
   python3 scripts/generate_dataset.py --clean
   ```

4. **Run one subagent per group, in parallel** (Task tool, `general` type). Each subagent runs exactly:
   ```bash
   python3 scripts/generate_dataset.py --group <group>
   ```
   Launch all of them in a single message so they run concurrently. Each writes only its own `catalog.json` + `collections.json` and reports back its `[<group>] N items | catalog.json + collections.json written` line.

5. **Wait for ALL subagents**, then mark each group todo `completed`.

6. **Assemble the index** (this is the "general task" that runs once everything finished):
   ```bash
   python3 scripts/generate_dataset.py --aggregate-only
   ```
   This reads the catalogs on disk, builds `datasets/datasets.json` with distinct per-theme previews, and removes stale theme folders. Run it **after** all groups, never in parallel with them.

7. **Verify on disk:**
   - `datasets/datasets.json` `count` = number of groups (themes + 1 masters).
   - Every theme with wallpapers has `catalog.json` + `collections.json`; `count` matches the number of WebP files.
   - Each entry has `path` pointing to an existing file and a correct raw GitHub `url`; `width`/`height` match actual resolutions.

8. **Report the final summary** as a table `Group | Items` plus the total, and confirm no errors.

## Sequential fallback (no subagents)

Run the dispatcher directly — it streams everything, one group at a time by default (`--concurrency 1`, masters first), then aggregates:
```bash
python3 scripts/generate_dataset.py
```
Use `--concurrency N` to parallelize the group workers in a single process; the aggregation still runs once at the end.

## Behavior details

- **Dispatcher output:** starts with the group analysis table, then per-group worker completion (`[done] <group> (rc=...)`), then the aggregation line (`datasets.json: N`) and the final `Final summary` table. Masters is always first in the group list.
- **Per-group result files:** each worker writes `working/generate-temp/dataset/dataset-<group>.result.json` (group + item count) and, in parallel mode, `dataset-<group>.log`. The dispatcher aggregates the final table from these.
- **Previews safety net:** the dispatcher checks for missing previews and generates them first (via `generate_previews.py`) so the datasets always reference existing preview URLs. This is a convenience; the previews themselves are managed by the dedicated previews skill.
- **Stale folders:** the aggregation removes any `datasets/<folder>` that is not a currently generated theme, not `masters`, and not `config.json`.

## Workflow (full pipeline)

This skill is the entry point for "regenerate everything". The full sequence is:

1. **Previews** — see `omarchy-wallpapers-generate-previews` (or `python3 scripts/generate_previews.py --plan-only` then the parallel subagent workflow).
2. **Optimization** — see `omarchy-wallpapers-generate-optimization` (or `python3 scripts/generate_optimization.py --plan-only` then the parallel subagent workflow).
3. **Datasets** — this skill's Step 3 above (plan → subagents per group → `--aggregate-only`).
4. **Summarize** — a concise report of the counts from each step.

## Rules

- Only regenerate via the scripts, never edit JSON by hand.
- If a new theme or collection was added, update `datasets/config.json` first (title/description) — it is the static source of truth and protected from stale-folder cleanup.
- Report discrepancies (non-standard files, missing paths) and do not force a commit if the scripts fail.
- Do **not** commit unless the user explicitly asks.
