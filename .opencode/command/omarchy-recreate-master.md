---
description: Ricrea un master a partire dal prompt in prompts/ (per un paese/nuovo contenuto)
agent: build
---

Ricrea un'immagine master da un prompt salvato, utile quando un master deve essere rigenerato o quando se ne crea uno nuovo:

1. Identifica la master da creare/ricreare (es. `masters/countries/country-IT-Italy-full.webp`).
2. Cerca il prompt corrispondente in `prompts/` per contenuto: `prompts/countries/<nome>.md`, `prompts/cities/<nome>.md`, `prompts/figures/<nome>.md`. Il nome del file del prompt deve coincidere con la master che produce (es. `prompts/countries/IT-Italy.md`).
   - Se il prompt **non esiste**, prima di generare la master scrivi il prompt (Markdown, in inglese, con tutti i dettagli: soggetto, stile, composizione, identità/colori del paese) e salvane una copia in `prompts/<sezione>/`.
   - Se il prompt **esiste**, seguilo fedelmente.
3. Genera l'immagine seguendo il prompt e salvane il risultato come **WebP lossless** in `masters/<sezione>/` (es. `masters/countries/country-IT-Italy-full.webp`), pixel-exact (source of truth). Se serve convertire da PNG, usa `python3 scripts/convert_to_webp.py`.
4. Verifica la risoluzione (2560x1440 per il master `-full` 2K, o 4K/8K se richiesto).
5. Dopo aver aggiunto/aggiornato il master, rigenera i dataset con `/omarchy-generate-datasets` (o `python3 scripts/generate_dataset.py`) e ottimizza con `/omarchy-optimize-images`.
6. Committa con messaggio breve, es. `Recreate IT-Italy master`.

**Regole**: la master è sempre a colori pieni (full-color) e lossless; il prompt è obbligatorio per ogni nuova master.