---
name: omarchy-wallpapers-generate-masters-grayscale
description: Generate the grayscale derivatives under masters/grayscale/ from the full-color masters in masters/colors/ via scripts/generate_masters_grayscale.py (deterministic luma conversion, lossless WebP). Use when asked to generate/regenerate the grayscale masters, or after adding/editing color masters. These derivatives are not exposed in the datasets catalog; they exist only as inputs for other derivations (theme variants, omarchy-theme work).
---

# Omarchy Grayscale Masters Generation

## Goal

Derive the grayscale version of every full-color master, stored lossless under `masters/grayscale/` (same filenames and folder layout as `masters/colors/`) so downstream processing can reuse them without recomputing. The conversion is deterministic (luma) and lossless; the color masters are never modified.

## Non-negotiables

- **Grayscale only.** This skill writes only `masters/grayscale/` and the manifest `datasets/masters/grayscale.json`. It never touches `masters/colors/`, the datasets catalogs, previews, or optimization manifests.
- **Deterministic + lossless.** Convert `RGB -> L` (luma) `-> RGB`, save lossless WebP. Never a lossy or stylistic transformation.
- **Never edit by hand.** Run `scripts/generate_masters_grayscale.py` only.

## The manifest (resume mechanism)

- `datasets/masters/grayscale.json` maps each source path to its `sha256` + `size`.
- A color master is skipped when its cached `sha256` matches **and** the grayscale target exists on disk; otherwise it is (re)generated.
- The manifest is written after a run, so an interrupted run resumes without redoing everything.

## Script modes — `scripts/generate_masters_grayscale.py`

| Option | Behavior |
|---|---|
| (no args) | Generate the grayscale for every color master under `masters/colors/`. |
| `paths...` | Generate only the given color master paths. |
| `--workers N` | Intra-group parallelism (default 8). |
| `--method N` | libwebp lossless method (default 6). |
| `--force` | Ignore the manifest cache and regenerate everything. |
| `--dry-run` | Report without writing (no grayscale files, no manifest). |

## Workflow

1. **Plan/report first (optional):**
   ```bash
   python3 scripts/generate_masters_grayscale.py --dry-run
   ```
   This prints `Total | to generate | unchanged (skip)` without writing, so you can review what will be produced.

2. **Run the generation:**
   ```bash
   python3 scripts/generate_masters_grayscale.py
   ```
   It writes `masters/grayscale/<collection>/` with names matching the color masters and updates `datasets/masters/grayscale.json`.

3. **Review the report:** `Generated`, `Unchanged (skipped)`, `Errors` — errors must be zero before committing.

4. **Do not regenerate the datasets** for this: the grayscale files are excluded from `datasets/masters/catalog.json` (which reads only `masters/colors/`).

## Rules

- Never edit `masters/colors/`; only derive into `masters/grayscale/`.
- No temporary files in the repository (only `working/generate-temp/`).
- Do **not** commit unless the user explicitly asks.
