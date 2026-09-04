# AGENTS.md

Guidelines for AI agents working on this repository. Read this file before making any changes.

## Project overview

Repository of personalized wallpapers inspired by the official **Omarchy** ones. They keep the visual style of the themes installed on Omarchy while offering more specific content variations. The project is in its early stages: new content will be added over time.

## Structure

Folders in alphabetical order, as seen in the repository root:

- `.opencode/` — agent commands and skills.
- `datasets/` — generated JSON indexes.
- `images/` — themed wallpapers, organized by theme.
- `masters/` — original full-color source images.
- `previews/` — small WebP previews of the themed wallpapers.
- `readme/` — images and secondary pages for the README.
- `scripts/` — tooling.
- `working/` — local scratch space, not committed.
- `README.md` — general project documentation.

## Folder `datasets`

Generated JSON indexes, one folder per theme (`datasets/<theme>/catalog.json`, e.g. `datasets/tokyo-night/catalog.json`); each folder also holds `optimization.json` (optimization cache), `previews.json` (previews cache, themes only) and `sections.json` (per-section stats: counts, sizes, resolutions, variants). `datasets/datasets.json` is the top-level index describing all collections (catalog/optimization/previews/sections URLs and stats). **Never edit by hand**: regenerate with `scripts/generate_dataset.py`.

`datasets/config.json` is the **static** source of truth for human-readable metadata (theme `title`/`description` and section `title`/`description` in English). `generate_dataset.py` reads it and injects the descriptions into `datasets.json`, `catalog.json` and `sections.json`. **Whenever a new theme or section is added, update `datasets/config.json` first** (a missing entry just means no description); it is protected from the stale-folder cleanup.

## Folder `images`

Wallpapers are organized **by theme** under `images/`, each theme containing per-content-type subfolders.

- `images/<theme>/` — a theme folder (e.g. `images/tokyo-night/`), one per theme.
  - `images/<theme>/countries/` — wallpapers by country.
  - `images/<theme>/cities/` — wallpapers for cities (e.g. `oslo/`).
  - `images/<theme>/figures/` — wallpapers of great historical figures.

## File conventions

- **Image format:** WebP (`*.webp`), matching Omarchy 4 which renders WebP backgrounds. **Masters** are lossless WebP (pixel-exact source of truth); **themed wallpapers** are lossy WebP (q85) since they are derived artwork.
- **Resolution:** 2560x1440 (QHD / WQHD) for the 2K versions. 4K (3840x2160) and 8K (7680x4320).
- **Naming:** `omarchy-<section>-<code>-<name>-<res>.webp` (full rules in [Naming conventions](#naming-conventions)).
- **Theme:** each wallpaper belongs to a specific theme folder (e.g. `tokyo-night/`) and is inspired by the official Omarchy wallpapers, but with identity/patriotic elements of the country (flag colors, landmarks, iconic landscapes).
- **Previews naming:** `previews/<theme>/<section>/<nome-base>-preview.webp`, where `<nome-base>` is the wallpaper name without the resolution suffix (e.g. `omarchy-country-AD-Andorra-preview.webp`), fixed 640x360 lossy WebP (q80).

## Naming conventions

Wallpaper names follow the format `omarchy-<section>-<code>-<name>-<res>.webp`, where `<code>` is optional:

- `<section>` the section in the singular (e.g. `country`, `figure`).
- `<code>` an optional code for sections that use one (e.g. countries): ISO 3166 alpha-2, uppercase.
- `<name>` name in English with the first letter capitalized; for multi-word names use a **hyphen** instead of an underscore.
- `<res>` resolution suffix, always present: `2K` (QHD/WQHD), `4K` and `8K`.
- Pre-existing name exception: `CZ` stays associated with `Czech` (not `Czechia`).

Examples: `omarchy-country-IT-Italy-2K.webp`, `omarchy-figure-Albert-Einstein-2K.webp`.

## Operational rules

- Before generating a complete dataset, always check for pending optimizations and missing previews, since the dataset JSON files reference the optimized images and the previews.
- Keep `datasets/` in sync: after adding/renaming/removing wallpapers, regenerate the JSON with `scripts/generate_dataset.py` (or via the opencode command `omarchy-generate-datasets`) — never edit the JSON by hand. `generate_dataset.py` checks for missing previews and generates them first (via `generate_previews.py --no-datasets`) because the datasets expose preview URLs.
- Keep `previews/` in sync: after adding/renaming/removing wallpapers (and after optimizing images, since the source hashes change), regenerate them with `scripts/generate_previews.py` (or via the opencode command `omarchy-generate-previews`) — never edit them by hand. `generate_dataset.py` adds the `preview` field to the catalog entries only for previews that already exist.

## Image convert

All theme images are WebP, but if you need to convert some PNG images to lossless WebP, use `python3 scripts/convert_to_webp.py`. Always keep the original name with the modified extension, unless explicitly asked otherwise.

## Image optimization

Optimization is **lossless only** (never lossy re-encodes). Do not run it manually: use the opencode command `/omarchy-optimize-images` or `python3 scripts/optimize_images.py` (lossless WebP re-encode via Pillow/libwebp, parallel, with a per-theme manifest cache in `datasets/<theme>/optimization.json` and `datasets/masters/optimization.json` that skips unchanged files). The script verifies output structurally (dimensions, pixels, size) and regenerates `datasets/` afterwards.

## Preview generation

Previews are **lossy** (WebP q80, 640x360) derived from the themed wallpapers, never from the masters. Do not run it manually: use the opencode command `/omarchy-generate-previews` or `python3 scripts/generate_previews.py` (parallel, with a per-theme manifest cache in `datasets/<theme>/previews.json` that skips unchanged sources). Each wallpaper group (same base name across 2K/4K/8K variants) gets a single preview, derived from the **lowest resolution** variant, written to `previews/<theme>/<section>/<nome-base>-preview.webp`. The script regenerates `datasets/` afterwards so the catalogs expose the `preview` field.

## Repository status

- Branch: `main`.
- Remote: `git@github.com:emkcloud/omarchy-wallpapers.git`.

## Notes for the agent

- **Commit messages:** write concise descriptions (short and to the point), not long paragraphs.