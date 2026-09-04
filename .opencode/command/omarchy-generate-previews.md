---
description: Genera le preview WebP (640x360) dei wallpaper dei temi e aggiorna i dataset
agent: build
---

Genera le preview WebP dei wallpaper in `images/` (solo temi, non masters) e aggiorna i dataset:

1. Esegui `python3 scripts/generate_previews.py` dalla root (default: 8 worker, q80, `--method 6`).
   - Per ogni wallpaper viene creata `previews/<tema>/<sezione>/<nome-base>-preview.webp`, derivata dalla variante a risoluzione più bassa.
   - Opzioni utili: `--dry-run` per una prova senza scrivere, `--force` per ignorare la cache, `--workers N`, `--quality N`.
2. Esamina il report finale:
   - `Generate`: preview create.
   - `Invariate (saltate)`: file non rigenerati perché già registrati nel manifest con lo stesso hash del sorgente.
   - `Errori`: nessun file deve restare con errori; se presenti, non committare senza averli risolti.
3. Lo script rigenera automaticamente `datasets/` dopo la creazione (i catalog ora includono il campo `preview`). Verifica che `datasets/<tema>/catalog.json` abbia il campo `preview` per ogni entry e che `datasets/<tema>/previews.json` sia il manifest di cache.
4. Se l'ottimizzazione immagini è stata appena eseguita, lancia anche questo comando: gli hash dei sorgenti cambiano e le preview vanno rigenerate.
5. Committa con messaggio breve, es. `Generate wallpaper previews`.

**Regole**: solo generazione di preview lossy (WebP q80) da 640x360, mai modifica dei wallpaper originali. Le preview vanno create dal file a risoluzione più bassa.