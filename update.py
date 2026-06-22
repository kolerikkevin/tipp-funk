#!/usr/bin/env python3
"""
Der EINE Befehl fürs tägliche Update:

    python3 update.py

Läuft: Daten ziehen (scrape) → aufbereiten + Stories erkennen (build) →
Schlagzeilen texten (headlines). Matchday-bewusst:
- gescrapt wird täglich (Stände ändern sich live),
- neue Schlagzeilen entstehen NUR für frisch abgeschlossene Spieltage (Cache),
- an spielfreien Tagen bleibt einfach alles vom letzten Mal stehen.

Danach Seite lokal ansehen:
    python3 -m http.server -d site 8000   →   http://localhost:8000
"""
from __future__ import annotations

import sys
import time

import scrape
import build
import headlines


def main():
    t0 = time.time()
    print("① Daten ziehen (Kicktipp) …")
    scrape.run()

    print("\n② Aufbereiten + Geschichten erkennen …")
    build.run()

    print("\n③ Schlagzeilen texten …")
    headlines.run()

    print(f"\n✓ Update fertig in {time.time() - t0:.0f}s.")
    print("  Seite ansehen:  python3 -m http.server -d site 8000  →  http://localhost:8000")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 – ein Tagesjob soll klar sagen, was kaputt war
        print(f"\n✗ Update abgebrochen: {e}", file=sys.stderr)
        sys.exit(1)
