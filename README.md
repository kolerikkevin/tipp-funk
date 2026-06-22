# Tippspiel-Chronik

Tägliches Dashboard für die Kicktipp-Tipprunde **„PortfolioundEntwicklung"** (Arbeits-Tippspiel, WM 2026).
Zieht die öffentlichen Kicktipp-Seiten, erkennt kleine Geschichten in den Daten und zeigt den
Platz-Verlauf aller Tipper als interaktives Liniendiagramm.

## Was es kann
- **Platz-Verlauf-Diagramm** (Bump-Chart): jede Linie ein Tipper, Hover, Ein-/Ausblenden, Fokus-Modus.
- **Schlagzeilen pro Tag** – von Claude getextet aus erkannten Ereignissen
  (Tagessieger, perfekter Spieltag, einsamer Volltreffer, Aufholjäger, Führungs-Serie, Pechvogel …).
- **Aktuelle Tabelle** + Spieltags-Details.
- **Dashboard-Layout**: Übersicht (alle Kacheln) ⇄ Fokus (eine Funktion füllt das Fenster).

## Datenquelle (kein Login nötig)
- `…/gesamtuebersicht` – Tabelle + Punkte-Matrix pro Spieltag
- `…/tippuebersicht?spieltagIndex=N` – Spiele+Ergebnisse + Einzeltipps (mit `t`/`f` = richtig/falsch, Punkte, `sptsieger`)
- Kumulative Platzierung steckt in der CSS-Klasse `kicktipp-pos<N>` → authoritative Historie.

## Pipeline
```
scrape.py   →  data/parsed/*.json        (Rohdaten ziehen + parsen)
build.py    →  site/data/*.json          (Platz-Verlauf + Story-Events berechnen)
headlines.py→  site/data/headlines.json  (LLM textet Schlagzeilen aus Events)
update.py   →  alles nacheinander         (der „tägliche" Befehl)
```
Frontend: statische Seite in `site/` – läuft lokal und später per GitHub Pages.

## Lokal starten
```bash
pip install -r requirements.txt
python3 update.py                 # scrape + build + headlines
python3 -m http.server -d site 8000   # → http://localhost:8000
```

## Status
🧪 Experiment / im Aufbau. Automatik zunächst lokal, später GitHub Action (Cron) + Pages.
Schlagzeilen brauchen einen LLM-Key (Anthropic bevorzugt, OpenAI-Fallback).
