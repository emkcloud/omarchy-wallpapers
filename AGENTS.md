# AGENTS.md

Guidelines for AI agents working on this repository. Read this file before making any changes.

## Project overview

Repository of personalized wallpapers inspired by the official **Omarchy** ones. They keep the visual style of the themes installed on Omarchy while offering more specific content variations. The project is in its early stages: new content will be added over time.

## Structure

Folders in alphabetical order, as seen in the repository root:

- `.opencode/` — agent commands and skills.
- `datasets/` — generated JSON indexes.
- `images/` — themed wallpapers, organized by theme.
- `masters/` — master source resources.
  - `masters/colors/` — full-color masters.
  - `masters/grayscale/` — grayscale derivatives.
  - `masters/prompts/` — source prompts.
- `previews/` — small WebP previews of the themed wallpapers.
- `readme/` — images and secondary pages for the README.
- `scripts/` — tooling.
- `testing/` — deterministic end-to-end tests for the tooling (e.g. `testing/wallpapers_installer.py`, run via the `omarchy-wallpapers-test-installer` skill).
- `working/` — local scratch space, not committed.
- `README.md` — general project documentation.

## Folder `datasets`

Generated JSON indexes, one folder per theme (`datasets/<theme>/catalog.json`, e.g. `datasets/tokyo-night/catalog.json`); each folder also holds `optimization.json` (optimization cache), `previews.json` (previews cache, themes only) and `collections.json` (per-collection stats: counts, sizes, resolutions, variants). `datasets/datasets.json` is the top-level index describing all themes and masters (catalog/optimization/previews/collections URLs and stats). Theme-level and per-collection entries expose a random `preview` (640x360) paired with `image`, the full 2K image of the same wallpaper. **Never edit by hand**: regenerate with `scripts/generate_dataset.py`.

`datasets/config.json` is the **static** source of truth for human-readable metadata (theme `title`/`description`/`palette` and collection `title`/`description` in English). The theme `palette` is an array of 5 hex colors, always in this order: `dark_background` (darkest base), `background` (base), `muted` (surface/gray), `foreground` (text), `accent` (signature color), taken from the theme's official `colors.toml`. `generate_dataset.py` reads it and injects the descriptions and the palette into `datasets.json`, `catalog.json` and `collections.json`. **Whenever a new theme or collection is added, update `datasets/config.json` first** (a missing entry just means no description/palette); it is protected from the stale-folder cleanup.

## Folder `images`

Wallpapers are organized **by theme** under `images/`, each theme containing per-content-type subfolders.

- `images/<theme>/` — a theme folder (e.g. `images/tokyo-night/`), one per theme.
  - `images/<theme>/countries/` — wallpapers by country.
  - `images/<theme>/cities/` — wallpapers for cities (e.g. `oslo/`).
  - `images/<theme>/figures/` — wallpapers of great historical figures.

## Folder `masters`

Master source images, one per content type, stored in **lossless** WebP under two variant trees:

- `masters/colors/<collection>/` — the full-color masters (e.g. `masters/colors/countries/omarchy-country-IT-Italy-2K.webp`). This is the source of truth consumed by the datasets catalog.
- `masters/grayscale/<collection>/` — the same images already converted to grayscale (same filenames as `colors/`), pre-computed so downstream processing (theme variants, omarchy-theme work) does not have to recompute them.

Both variant trees share identical filenames per collection, so mapping is trivial. `colors/` is the only one exposed in the datasets (`masters/catalog.json`); `grayscale/` is **excluded** from the catalog by `generate_dataset.py` and exists purely as an input for other derivations. Regenerate grayscale masters with `scripts/generate_masters_grayscale.py` (or the opencode skill `omarchy-wallpapers-generate-masters-grayscale`). Add a new master under `masters/colors/<collection>/` (not directly in `masters/<collection>/`).

## Folder `masters/prompts`

Source prompts used to generate the masters, organized **by content type**: `masters/prompts/countries/`, `masters/prompts/cities/`, `masters/prompts/figures/`. Each prompt is a plain-text file (`.txt`) whose name matches the master it produced (e.g. `masters/prompts/countries/omarchy-country-IT-Italy-2K.txt` for `masters/colors/countries/omarchy-country-IT-Italy-2K.webp`). **Always write the prompt for a new master** so the image can be recreated later if needed.

## File conventions

- **Image format:** WebP (`*.webp`), matching Omarchy 4 which renders WebP backgrounds. **Masters** are lossless WebP (pixel-exact source of truth); **themed wallpapers** are lossy WebP (q85) since they are derived artwork.
- **Resolution:** 2560x1440 (QHD / WQHD) for the 2K versions. 4K (3840x2160) and 8K (7680x4320).
- **Naming:** `omarchy-<collection>-<code>-<name>-<res>.webp` (full rules in [Naming conventions](#naming-conventions)).
- **Theme:** each wallpaper belongs to a specific theme folder (e.g. `tokyo-night/`) and is inspired by the official Omarchy wallpapers, but with identity/patriotic elements of the country (flag colors, landmarks, iconic landscapes).
- **Previews naming:** `previews/<theme>/<collection>/<nome-base>-preview.webp`, where `<nome-base>` is the wallpaper name without the resolution suffix (e.g. `omarchy-country-AD-Andorra-preview.webp`), fixed 640x360 lossy WebP (q80).

## Naming conventions

Wallpaper names follow the format `omarchy-<collection>-<code>-<name>-<res>.webp`, where `<code>` is optional:

- `<collection>` the collection in the singular (e.g. `country`, `figure`).
- `<code>` an optional code for collections that use one (e.g. countries): ISO 3166 alpha-2, uppercase.
- `<name>` name in English with the first letter capitalized; for multi-word names use a **hyphen** instead of an underscore.
- `<res>` resolution suffix, always present: `2K` (QHD/WQHD), `4K` and `8K`.
- Pre-existing name exception: `CZ` stays associated with `Czech` (not `Czechia`).

Examples: `omarchy-country-IT-Italy-2K.webp`, `omarchy-figure-Albert-Einstein-2K.webp`.

## Operational rules

- **No temporary files in the repository**: you do NOT have permission to write temporary files inside the repository (e.g. `images/`, `masters/`, `previews/`, `datasets/`, or anywhere else). Temporary files go exclusively in `working/generate-temp/`; that directory is yours, do whatever you need there. Each generation script keeps its own temporary files in a dedicated subfolder — `working/generate-temp/dataset/` (generate_dataset.py), `working/generate-temp/previews/` (generate_previews.py), `working/generate-temp/optimization/` (generate_optimization.py) — and wipes it at the start of every full run (`--clean` also deletes it on demand).
- Before generating a complete dataset, always check for pending optimizations and missing previews, since the dataset JSON files reference the optimized images and the previews.
- Keep `datasets/` and `previews/` in sync: after adding/renaming/removing wallpapers (and after optimizing images, since the source hashes change), regenerate them with the `omarchy-wallpapers-generate-datasets` skill (or `scripts/generate_dataset.py` / `scripts/generate_previews.py`) — never edit them by hand. `generate_dataset.py` checks for missing previews and generates them first (via `generate_previews.py`) because the datasets expose preview URLs, and adds the `preview` field to the catalog entries only for previews that already exist. `generate_dataset.py` uses the same plan-first + parallel-subagent technique as the other scripts: one worker per group (`--group <group>`, a theme or `masters`), then a single aggregation (`--aggregate-only`) that assembles `datasets/datasets.json`.

## Image convert

All theme images are WebP, but if you need to convert some PNG images to lossless WebP, use `python3 scripts/convert_to_webp.py`. Always keep the original name with the modified extension, unless explicitly asked otherwise.

## Omarchy wallpapers image optimization

Optimization of the Omarchy wallpapers' images is **lossless only** (never lossy re-encodes). Do not run it manually: use the opencode skill `omarchy-wallpapers-generate-optimization` (or `python3 scripts/generate_optimization.py`) (lossless WebP re-encode via Pillow/libwebp, parallel, with a per-group manifest cache in `datasets/<group>/optimization.json` that skips unchanged files). Groups are `masters` (fixed, processed first: `masters/colors/` + `masters/grayscale/`) and one per theme from `images/` (dynamic: `images/<theme>/` + `previews/<theme>/`). The script verifies output structurally (dimensions, pixels, size), supports `--group <gruppo>`, `--plan-only`, `--concurrency N` and `--clean` (deletes its temp folder `working/generate-temp/optimization/`), and writes **only** the optimization manifests — the datasets are regenerated separately with `generate_dataset.py`.

## Preview generation

Previews are **lossy** (WebP q80, 640x360) derived from the themed wallpapers, never from the masters. Do not run it manually: use the opencode skill `omarchy-wallpapers-generate-previews` (or `python3 scripts/generate_previews.py`), which supports a plan-first step (`--plan-only`), per-theme workers (`--theme <tema>`), a dispatcher mode (`--concurrency N` to parallelize themes), `--clean` (deletes its temp folder `working/generate-temp/previews/`), and a per-theme manifest cache in `datasets/<theme>/previews.json` that skips unchanged sources. Each wallpaper group (same base name across 2K/4K/8K variants) gets a single preview, derived from the **lowest resolution** variant, written to `previews/<theme>/<collection>/<nome-base>-preview.webp`. The script creates **only** the previews and the manifests; the datasets are regenerated separately with `scripts/generate_dataset.py` (which also checks for missing previews). Recommended parallel flow: launch one subagent per theme via the Task tool with a live todo list, and wait for all of them before reporting the total.

## Repository status

- Branch: `main`.
- Remote: `git@github.com:emkcloud/omarchy-wallpapers.git`.

## Notes for the agent

- **Commit messages:** write concise descriptions (short and to the point), not long paragraphs.
- **Language for public files:** whenever the user asks to write a **skill**, **command**, or **agent**, always write the file content in **English**, regardless of the language we are speaking in. These files are public and can be downloaded by anyone anywhere, so they must not contain Italian (or any other non-English) text.