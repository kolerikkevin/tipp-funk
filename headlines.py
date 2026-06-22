#!/usr/bin/env python3
"""
Schlagzeilen-Generator: textet aus den erkannten Ereignissen (events.json)
freche Boulevard-Schlagzeilen im BILD-Stil – mit Claude (Opus 4.8).

- Die Regel-Engine liefert die VERIFIZIERTEN Fakten (Ergebnisse, Punkte, Quoten,
  vergessene Tipps). Claude wählt die besten Geschichten und textet sie kreativ.
- Pro abgeschlossenem Spieltag werden die Schlagzeilen EINMAL erzeugt und gecacht
  (data/headline_cache.json). Spielfreie Tage ändern nichts → kein neues Generieren,
  der letzte Block bleibt oben stehen.
- Ergebnis: site/data/headlines.json (source: "llm"), neuester Spieltag oben.

Schreibt nur über echte Tipper (Nicht-Tipper sind in build.py schon raus).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent
SITE_DATA = ROOT / "site" / "data"
CACHE = ROOT / "data" / "headline_cache.json"

MODEL = os.environ.get("HEADLINE_MODEL", "claude-opus-4-8")
MIN_HEADLINES = 3

SYSTEM = """Du bist der Schlagzeilen-Texter einer Boulevard-Sportredaktion (Mechanik wie BILD-Zeitung) \
für ein Büro-Tippspiel zur Fußball-WM 2026. Die Tipper sind die Stars – inszeniere sie wie \
Fußballhelden und Promis, mit Konkurrenz, Drama und Augenzwinkern.

So funktioniert eine Boulevard-Schlagzeile (genau dieser Aufbau pro Eintrag):
- SCHLAGZEILE ("text"): die fette Hauptzeile. EIN kurzer, zugespitzter Satz mit Reizwort/Wortwitz, \
der sofort Aufmerksamkeit packt. Knapp, laut, emotional. KEINE nüchterne Zusammenfassung.
- UNTERZEILE ("erklaerung"): GENAU ZWEI Sätze darunter, die die Schlagzeile auflösen und die harten \
Fakten sachlich-süffig nachliefern (konkrete Punkte, Ergebnisse, Plätze, Quoten). Sie erklärt, was \
wirklich passiert ist – ruhiger Ton als die Schlagzeile, aber immer noch lebendig.

Regeln:
- Nutze die (oft witzigen) Tipper-Namen für Wortspiele, wenn es sich anbietet.
- NUR die gelieferten Fakten verwenden. Niemals Ergebnisse, Punkte, Namen oder Platzierungen erfinden.
- Variiere Ton und Satzbau – nicht jede Zeile nach demselben Muster.
- Nimm auch die hinteren Plätze und die Verplanten (Tipp vergessen) liebevoll aufs Korn – \
nie beleidigend, immer mit Humor, sodass sich jeder freut, vorzukommen.
- Wer seinen Tipp vergessen hat: aufziehen, dass er verpennt/verplant war (nicht, dass er schlecht tippt) – \
je nach Lage "war eigentlich gut dabei und verschenkt's" oder "im Keller, verspielt die Aufholjagd".
- Deutsch. Keine Hashtags, keine Emojis."""


SCHEMA = {
    "type": "object",
    "properties": {
        "headlines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "erklaerung": {"type": "string"},
                    "type": {"type": "string"},
                    "tipper": {"type": "string"},
                },
                "required": ["text", "erklaerung", "type", "tipper"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["headlines"],
    "additionalProperties": False,
}


def load_env_key() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    for envf in (ROOT / ".env", ROOT.parent.parent / ".env"):
        if envf.exists():
            for line in envf.read_text("utf-8").splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def edition_context(ed, season_events, standings):
    ctx = {
        "ausgabe": ed["label"],
        "spiele_des_tages": ed.get("games", []),
        "erkannte_ereignisse": [{"typ": e["type"], "tipper": e["primary"], "fakten": e["facts"]}
                                for e in ed["events"]],
    }
    if season_events:
        ctx["saison_storylines"] = [{"typ": e["type"], "tipper": e["primary"], "fakten": e["facts"]}
                                    for e in season_events]
        akt = [t for t in standings["tippers"] if t.get("active", True)]
        if akt:
            ctx["aktuelle_tabelle"] = {
                "fuehrender": {"name": akt[0]["name"], "punkte": akt[0]["total"]},
                "verfolger": {"name": akt[1]["name"], "punkte": akt[1]["total"]} if len(akt) > 1 else None,
                "schlusslicht": {"name": akt[-1]["name"], "punkte": akt[-1]["total"]},
            }
    return ctx


def signature(ctx) -> str:
    return hashlib.sha256(json.dumps(ctx, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def generate(client, ctx):
    user = (
        "Hier die Daten EINER Tagesausgabe des Tippspiels (die Spiele dieses Abends/dieser Nacht). "
        f"Wähle die {MIN_HEADLINES}–6 besten Geschichten (mindestens {MIN_HEADLINES}) und texte je: "
        "eine fette Schlagzeile (text) PLUS zwei Sätze Unterzeile (erklaerung), die die Fakten nachliefert. "
        "Streue verschiedene Tipper – nicht nur die Spitze. "
        "Gib zu jedem Eintrag Ereignis-Typ (type) und gemeinten Tipper (tipper) an.\n\n"
        + json.dumps(ctx, ensure_ascii=False, indent=2)
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)["headlines"]


def run():
    key = load_env_key()
    if not key:
        print("Kein ANTHROPIC_API_KEY gefunden – überspringe LLM, behalte Vorlagen-Schlagzeilen.",
              file=sys.stderr)
        return
    client = anthropic.Anthropic(api_key=key)

    events = json.loads((SITE_DATA / "events.json").read_text("utf-8"))
    standings = json.loads((SITE_DATA / "standings.json").read_text("utf-8"))
    cache = json.loads(CACHE.read_text("utf-8")) if CACHE.exists() else {}

    blocks = []
    for ed in events.get("editions", []):
        if not ed.get("events"):
            continue  # spielfreier Tag -> keine neue Ausgabe
        D = ed["date"]
        ctx = edition_context(ed, ed.get("season_events"), standings)
        sig = signature(ctx)
        cached = cache.get(D)
        if cached and cached.get("sig") == sig:
            headlines, status = cached["headlines"], "cache"
        else:
            print(f"  {ed['label']}: generiere Schlagzeilen mit {MODEL} …")
            headlines = generate(client, ctx)
            cache[D] = {"sig": sig, "headlines": headlines}
            status = "neu"
        blocks.append({"date": D, "label": ed["label"], "complete": True, "headlines": headlines})
        print(f"  {ed['label']}: {len(headlines)} Schlagzeilen ({status})")

    blocks.sort(key=lambda b: b["date"], reverse=True)  # neuester Tag oben
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), "utf-8")
    (SITE_DATA / "headlines.json").write_text(
        json.dumps({"source": "llm", "model": MODEL, "blocks": blocks}, ensure_ascii=False, indent=2), "utf-8")
    print(f"✓ {sum(len(b['headlines']) for b in blocks)} Schlagzeilen über {len(blocks)} Tagesausgaben → site/data/headlines.json")


if __name__ == "__main__":
    run()
