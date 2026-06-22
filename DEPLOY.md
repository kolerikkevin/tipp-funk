# Deployment: GitHub Pages + täglicher Cron

Die Seite läuft täglich automatisch um **08:30 (Sommerzeit)** über GitHub Actions
und veröffentlicht sich selbst via GitHub Pages. Dieses Tool wird als **eigenes Repo**
gepusht – nicht das ganze `claudecode`-Verzeichnis.

## Einmaliges Setup

1. **API-Key rotieren** (Pflicht, der alte stand im Chat):
   console.anthropic.com → alten Key widerrufen → neuen erzeugen.

2. **Leeres GitHub-Repo** anlegen (z. B. `tipp-funk`, privat oder öffentlich).

3. **Lokales Repo pushen** (im Tool-Ordner):
   ```bash
   cd tools/tippspiel-chronik
   git remote add origin git@github.com:<DEIN_USER>/tipp-funk.git
   git push -u origin main
   ```

4. **Secret hinterlegen**: Repo → Settings → Secrets and variables → Actions →
   *New repository secret* → Name `ANTHROPIC_API_KEY`, Wert = **neuer** Key.

5. **Pages aktivieren**: Repo → Settings → Pages → *Source* = **GitHub Actions**.

6. **Erststart**: Repo → Actions → „Tägliches Tipp-Funk Update" → *Run workflow*.
   Danach ist die Seite unter `https://<DEIN_USER>.github.io/tipp-funk/` live.

## Was die Action täglich tut
`scrape.py` → `build.py` → `headlines.py` (`update.py`), committet den neuen Stand
(inkl. täglichem Snapshot für den Verlauf) zurück und deployt `site/` zu Pages.

## Hinweise
- **Zeitzone:** Cron läuft in UTC (`30 6 * * *` = 08:30 CEST). Im Winter 07:30 Ortszeit –
  bei Bedarf in `.github/workflows/daily.yml` auf `30 7 * * *` ändern.
- **`.env` wird nie gepusht** (in `.gitignore`); der Key lebt nur als GitHub-Secret.
- **Cache** (`data/headline_cache.json`) wird mitcommittet → alte Ausgaben werden nicht
  neu getextet, nur der neue Tag.
