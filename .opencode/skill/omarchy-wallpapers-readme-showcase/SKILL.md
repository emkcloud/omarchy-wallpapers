---
name: omarchy-wallpapers-readme-showcase
description: Regenerate the README showcase table images by copying the theme previews into readme/images/. Use when the user asks to "regenerate the README showcase/previews", "update the README showcase table", or mentions "showcase", "readme/images", or "rigenera showcase". Copies existing previews only; it does NOT regenerate them.
---

# Omarchy README Showcase

## Workflow

1. Open `README.md` and locate the table under `## Showcase`. It can hold 3, 6, 9 or 12 entries (1, 2, 3 or 4 rows of 3 columns).
2. For every row take the link+image pair:
   - `<a href=".../images/<theme>/<collection>/<name>-<res>.webp">`
   - `<img src="readme/images/<target>.webp">`
3. From the link's destination derive the base name (drop the `-<res>` suffix):
   - `omarchy-country-BH-Bahrain-2K.webp` → base `omarchy-country-BH-Bahrain`
4. Compute the source preview (same path as the master, but under `previews/`):
   - `previews/<theme>/<collection>/<base>-preview.webp`
5. Copy that preview renaming it to the file the README points to:
   - `cp previews/<theme>/<collection>/<base>-preview.webp readme/images/<target>.webp` (overwrite)
6. Repeat for all rows, handling 3/6/9/12 entries generically.
7. At the end, show the user a summary table (Markdown) with one row per copied image: target file, source preview, and a status check (e.g. `OK` / `MISSING`) confirming the copy succeeded or that the source preview was missing.

## Rules

- Copy only: do NOT run `generate_previews.py`; do NOT touch `images/` or `datasets/`.
- If a source preview is missing, report it in the summary table (status `MISSING`) but keep going.
- Do NOT modify `README.md`, only the files in `readme/images/`.
- Summarize the copied pairs (target ← source preview) at the end.
- Leave a short commit message, e.g. "Refresh README showcase images".