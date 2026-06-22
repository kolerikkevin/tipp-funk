#!/usr/bin/env python3
"""
Kicktipp-Scraper für die Tipprunde "PortfolioundEntwicklung".

Zieht zwei öffentliche Seiten (kein Login nötig):
  - /gesamtuebersicht            -> aktuelle Tabelle + Punkte-Matrix pro Spieltag
  - /tippuebersicht?spieltagIndex=N -> Spiele+Ergebnisse + Einzeltipps je Tipper

Speichert:
  - data/raw/<YYYY-MM-DD>/*.html      (roher Snapshot, Beweis-/Audit-Kette)
  - data/parsed/standings.json        (aktuelle Tabelle)
  - data/parsed/matchdays.json        (alle Spieltage: Spiele + Tipps)
  - data/parsed/meta.json             (Scrape-Zeit, Tipperliste, Spieltag-Status)
  - data/history/standings_<date>.json(tägliche authoritative Tabelle, wächst mit)

Nur Standardbibliothek + requests.
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import json
import re
import sys
import time
from pathlib import Path

import requests

BASE = "https://www.kicktipp.de"
ROUND = "portfolioundentwicklung"
TOTAL_MATCHDAYS_FALLBACK = 15

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"
PARSED = DATA / "parsed"
HISTORY = DATA / "history"

HEADERS = {
    "User-Agent": "tippspiel-chronik/0.1 (privates Tippspiel-Dashboard; kontakt: kevin)",
    "Accept-Language": "de-DE,de;q=0.9",
}


# --------------------------------------------------------------------------- #
# HTML-Helfer
# --------------------------------------------------------------------------- #
def _clean(s: str) -> str:
    """Tags raus, Entities auflösen, Whitespace normalisieren."""
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _rows(html_doc: str) -> list[str]:
    """Liefert die Inhalte aller <tr>…</tr> als Liste (per Split, robust)."""
    return ["<tr" + c for c in html_doc.split("<tr")[1:]]


def _cells(row: str) -> list[tuple[str, str]]:
    """Liefert (klassen, innerHTML) je <td|th> einer Zeile, in Reihenfolge."""
    out = []
    for tag, attrs, inner in re.findall(r"<(t[dh])([^>]*)>(.*?)</\1>", row, re.S):
        cls = re.search(r'class="([^"]*)"', attrs)
        out.append((cls.group(1) if cls else "", inner))
    return out


def _int(s: str):
    s = s.strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else None


# --------------------------------------------------------------------------- #
# Netzwerk
# --------------------------------------------------------------------------- #
def fetch(path: str, params: dict | None = None) -> str:
    url = f"{BASE}/{ROUND}/{path}"
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


# --------------------------------------------------------------------------- #
# Parser: Gesamtübersicht
# --------------------------------------------------------------------------- #
def parse_gesamtuebersicht(doc: str) -> dict:
    """
    Tabelle: Pos | Name | 1..N (Spieltag-Punkte) | <Bonus> | <Quote> | Gesamt
    Spieltag-Spalten = numerische Header. Letzte Datenzelle = Gesamtpunkte.
    """
    header_cells, matchday_cols = None, []
    for row in _rows(doc):
        labels = [_clean(inner) for _, inner in _cells(row)]
        if any(l == "Name" for l in labels):
            header_cells = labels
            matchday_cols = [i for i, l in enumerate(labels) if re.fullmatch(r"\d+", l)]
            break

    tippers = []
    for row in _rows(doc):
        cells = _cells(row)
        vals = [_clean(inner) for _, inner in cells]
        if len(vals) < 4 or not re.fullmatch(r"\d+\.?", vals[0]):
            continue  # keine Datenzeile (Position muss vorne stehen)
        name = next((_clean(inner) for cls, inner in cells if "mg_class" in cls), None)
        if not name:
            # Fallback: zweite Zelle
            name = vals[1]
        md_points = {}
        if matchday_cols:
            for n, ci in enumerate(matchday_cols, start=1):
                v = _int(vals[ci]) if ci < len(vals) else None
                if v is not None:
                    md_points[n] = v
        tippers.append(
            {
                "name": name,
                "rank": int(vals[0].rstrip(".")),
                "matchday_points": md_points,
                "total": _int(vals[-1]),
            }
        )
    return {"tippers": tippers, "header": header_cells}


# --------------------------------------------------------------------------- #
# Parser: Tippübersicht (ein Spieltag)
# --------------------------------------------------------------------------- #
_RESULT_RE = re.compile(r"(\d+)\s*:\s*(\d+)")
_TIP_RE = re.compile(r"(\d+)\s*:\s*(\d+)(?:\s+(\d+))?")


def parse_tippuebersicht(doc: str, spieltag_index: int) -> dict:
    rows = _rows(doc)

    # ---- Tabelle A: Spiele + Ergebnisse ----------------------------------- #
    games = []
    for row in rows:
        vals = [_clean(inner) for _, inner in _cells(row)]
        # Zeile: Termin | Heim | Gast | Gruppe | Ergebnis
        if len(vals) >= 5 and re.match(r"\d{2}\.\d{2}\.\d{2}", vals[0]):
            res = _RESULT_RE.search(vals[4])
            games.append(
                {
                    "idx": len(games),
                    "kickoff": vals[0],
                    "home": vals[1],
                    "away": vals[2],
                    "group": vals[3],
                    "result": {"home": int(res.group(1)), "away": int(res.group(2))}
                    if res
                    else None,
                    "played": res is not None,
                }
            )
    n_games = len(games)

    # ---- Tabelle B: Tipp-Matrix ------------------------------------------- #
    tips = []
    for row in rows:
        if "ereignis" not in row:  # nur Tipper-Zeilen haben ereignis-Zellen
            continue
        cells = _cells(row)
        tid = re.search(r"teilnehmer(\d+)", row)
        name = next((_clean(inner) for cls, inner in cells if "mg_class" in cls), None)
        if not name:
            continue
        # kumulative Platzierung nach diesem Spieltag steckt in 'kicktipp-pos<N>'
        posm = re.search(r"kicktipp-pos(\d+)", row)
        position = int(posm.group(1)) if posm else None
        if position is None:  # Fallback: Positions-Zelle "1." -> 1
            raw = next((_clean(inner) for cls, inner in cells if "position" in cls and "differenz" not in cls), "")
            position = _int(raw.rstrip("."))
        sptsieger = "sptsieger" in row

        picks = []
        for cls, inner in cells:
            if "ereignis" not in cls:
                continue
            k = re.search(r"ereignis(\d+)", cls)
            gi = int(k.group(1)) if k else len(picks)
            text = _clean(inner)
            m = _TIP_RE.search(text)
            tokens = cls.split()
            correct = "t" in tokens  # 'nw t ereignis…' = Treffer
            if m:
                picks.append(
                    {
                        "game_idx": gi,
                        "tip": {"home": int(m.group(1)), "away": int(m.group(2))},
                        "points": int(m.group(3)) if m.group(3) else 0,
                        "correct": correct,
                    }
                )
            else:
                picks.append(
                    {"game_idx": gi, "tip": None, "points": 0, "correct": False}
                )

        spt = next((_int(_clean(inner)) for cls, inner in cells if "spieltagspunkte" in cls), None)
        bonus = next((_int(_clean(inner)) for cls, inner in cells if "bonus" in cls), None)

        tips.append(
            {
                "id": tid.group(1) if tid else None,
                "name": name,
                "position": position,
                "matchday_winner": sptsieger,
                "spieltag_points": spt,
                "bonus": bonus,
                "picks": picks,
            }
        )

    return {
        "spieltag_index": spieltag_index,
        "games": games,
        "n_games": n_games,
        "tips": tips,
        "all_played": n_games > 0 and all(g["played"] for g in games),
        "any_played": any(g["played"] for g in games),
        "date": games[-1]["kickoff"][:8] if games else None,
    }


# --------------------------------------------------------------------------- #
# Orchestrierung
# --------------------------------------------------------------------------- #
def discover_matchday_count(tippueb_doc: str) -> int:
    idx = [int(x) for x in re.findall(r"spieltagIndex=(\d+)", tippueb_doc)]
    return max(idx) if idx else TOTAL_MATCHDAYS_FALLBACK


def run() -> dict:
    today = _dt.date.today().isoformat()
    raw_dir = RAW / today
    for d in (raw_dir, PARSED, HISTORY):
        d.mkdir(parents=True, exist_ok=True)

    # 1) Gesamtübersicht
    ges_doc = fetch("gesamtuebersicht")
    (raw_dir / "gesamtuebersicht.html").write_text(ges_doc, encoding="utf-8")
    standings = parse_gesamtuebersicht(ges_doc)

    # 2) Tippübersicht: erst Default holen, Spieltag-Zahl ermitteln
    first_doc = fetch("tippuebersicht")
    n_md = discover_matchday_count(first_doc)

    matchdays = []
    for i in range(1, n_md + 1):
        time.sleep(0.4)  # höflich
        doc = fetch("tippuebersicht", {"spieltagIndex": i})
        (raw_dir / f"tippuebersicht_st{i:02d}.html").write_text(doc, encoding="utf-8")
        md = parse_tippuebersicht(doc, i)
        matchdays.append(md)
        flag = "✓" if md["all_played"] else ("…" if md["any_played"] else "·")
        print(f"  Spieltag {i:>2} {flag}  {md['n_games']:>2} Spiele, {len(md['tips'])} Tipper")

    played = [m["spieltag_index"] for m in matchdays if m["any_played"]]
    meta = {
        "scraped_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "round": ROUND,
        "total_matchdays": n_md,
        "played_matchdays": played,
        "tippers": [{"name": t["name"], "rank": t["rank"]} for t in standings["tippers"]],
    }

    (PARSED / "standings.json").write_text(json.dumps(standings, ensure_ascii=False, indent=2), "utf-8")
    (PARSED / "matchdays.json").write_text(json.dumps(matchdays, ensure_ascii=False, indent=2), "utf-8")
    (PARSED / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    # tägliche authoritative Tabelle archivieren (für späteren genauen Verlauf)
    (HISTORY / f"standings_{today}.json").write_text(
        json.dumps({"date": today, "tippers": standings["tippers"]}, ensure_ascii=False, indent=2),
        "utf-8",
    )

    print(f"\n✓ {len(standings['tippers'])} Tipper, {len(played)}/{n_md} Spieltage gespielt.")
    print(f"  Rohdaten: {raw_dir.relative_to(ROOT)}")
    print(f"  Geparst:  {PARSED.relative_to(ROOT)}")
    return {"standings": standings, "matchdays": matchdays, "meta": meta}


if __name__ == "__main__":
    try:
        run()
    except requests.HTTPError as e:
        print(f"HTTP-Fehler: {e}", file=sys.stderr)
        sys.exit(1)
