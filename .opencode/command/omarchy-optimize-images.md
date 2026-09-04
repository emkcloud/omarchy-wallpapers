---
description: Ottimizza le immagini WebP in images/ e masters/ (lossless)
agent: build
---

Ottimizza i wallpaper WebP in `images/` e i master in `masters/` in modo **lossless** e aggiorna i dataset:

1. Esegui `python3 scripts/optimize_images.py` dalla root (default: 8 worker, `--method 6`).
   - Opzioni utili: `--dry-run` per una prova senza modifiche, `--force` per ignorare la cache, `--workers N`, percorsi specifici per ottimizzare solo alcuni file.
2. Esamina il report finale:
   - `Ottimizzati`: file sostituiti con la versione più piccola.
   - `Già ottimali`: nessun guadagno, originali intatti.
   - `Invariati (saltati)`: file non ritoccati perché già registrati nel manifest con lo stesso contenuto (hash invariato).
   - `Errori`: nessun file deve restare con errori; se presenti, non committare senza averli risolti.
3. Lo script rigenera automaticamente `datasets/` dopo l'ottimizzazione (le dimensioni cambiano). Verifica che `datasets/*/catalog.json` e i manifest `datasets/<tema>/optimization.json` e `datasets/masters/optimization.json` siano coerenti.
4. Poiché l'ottimizzazione cambia gli hash dei sorgenti, rigenera anche le preview con `/omarchy-generate-previews` (o `python3 scripts/generate_previews.py`).
5. Committa con messaggio breve, es. `Optimize wallpaper images`.

**Regole**: solo ri-compressione lossless WebP via Pillow/libwebp (mai lossy). Il contenuto dei WebP non deve mai cambiare (verifica pixel AE=0).