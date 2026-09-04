---
description: Rigenera i dataset JSON in datasets/ dai wallpaper in images/
agent: build
---

Esegui la rigenerazione dei dataset dei wallpaper:

1. Lancia `python3 scripts/generate_dataset.py` dalla root del progetto. Lo script controlla automaticamente se mancano preview in `previews/` e, se necessario, le genera prima (via `generate_previews.py --no-datasets`) perché i dataset espongono gli URL dei preview.
2. Verifica l'output:
   - Il JSON in `datasets/` è valido e ogni tema con wallpaper ha la sua cartella (`datasets/<tema>/catalog.json`, `datasets/<tema>/sections.json`), più `datasets/masters/catalog.json` e `datasets/masters/sections.json` per i master. Le cartelle di temi senza wallpaper vengono rimosse.
   - `datasets/datasets.json` (indice top-level) elenca tutte le collezioni con URL e statistiche e `count` coincide col numero di collezioni.
   - `count` coincide con il numero di WebP in `images/<tema>/<sezione>/`.
   - Ogni entry ha `path` che punta a un file esistente e `url` raw GitHub corretto (`https://raw.githubusercontent.com/emkcloud/omarchy-wallpapers/main/images/...`).
   - Tutti i `width`/`height` corrispondono alle risoluzioni effettive dei WebP (2560x1440 per `-2K`, 3840x2160 per `-4K`).
3. Se la verifica passa, committa i file in `datasets/` (e lo script se modificato) con messaggio breve, es. `Regenerate wallpaper datasets`.

Non modificare a mano i JSON: la fonte di verità sono i file in `images/`. Se trovi discrepanze (file non standard, path mancanti), segnalale e non forzare il commit.