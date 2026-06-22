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

import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent
SITE_DATA = ROOT / "site" / "data"
CACHE = ROOT / "data" / "headline_cache.json"
GENDERS = ROOT / "genders.json"

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
- Beim Typ "spieltag_fazit": schreib eine zusammenfassende Schlagzeile, die den abgeschlossenen Kicktipp-Spieltag bilanziert (Spieltagssieger + Lage an der Spitze) – das ist die Abschluss-Story des Spieltags.
- GESCHLECHT: Hinter den Spitznamen stecken echte Personen. Nutze die mitgelieferte Zuordnung "geschlechter" \
(m = männlich → er/sein, w = weiblich → sie/ihr). Bei "neutral" oder fehlender Angabe formuliere strikt \
geschlechtsneutral – keine geschlechtsspezifischen Pronomen oder Endungen (kein "Sieger/Siegerin", lieber \
"holt den Tagessieg"; kein "er/sie").
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


def load_genders(standings):
    """Spitzname -> 'm' | 'w' | 'neutral'. Legt Vorlage an, falls nicht vorhanden."""
    if GENDERS.exists():
        return json.loads(GENDERS.read_text("utf-8"))
    g = {t["name"]: "neutral" for t in standings["tippers"] if t.get("active", True)}
    GENDERS.write_text(json.dumps(g, ensure_ascii=False, indent=2), "utf-8")
    return g


def edition_context(ed, season_events, standings, genders):
    names = {e["primary"] for e in ed["events"]} | {e["primary"] for e in (season_events or [])}
    ctx = {
        "ausgabe": ed["label"],
        "phase": ed.get("phase"),
        "geschlechter": {nm: genders.get(nm, "neutral") for nm in names},
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
        "Gib zu jedem Eintrag den EXAKTEN Ereignis-Typ (type = 'typ' aus erkannte_ereignisse) und den "
        "gemeinten Tipper (tipper) an. 'spieltag_fazit' NUR, wenn ein Ereignis dieses Typs vorliegt. "
        "WICHTIG: Für JEDE Bonus-Auflösung (typ 'bonus_aufloesung') MUSST du eine eigene Schlagzeile "
        "schreiben – zusätzlich zu den anderen Geschichten, im selben Stil. Bei 'bonus_aufloesung' ist "
        "'tipper' das Frage-Label (z. B. 'Gruppe E'), kein Personenname. "
        "ACHTUNG zu 'leer_detail': Wer leer ausging, hat NICHT zwingend vergessen zu tippen! Steht bei "
        "'tipp' ein Land, hat die Person genau DARAUF (falsch) gesetzt – schreib dann z. B. 'setzte auf X' "
        "oder 'verzockte sich mit X', NIEMALS 'vergaß zu tippen'. Nur wenn 'tipp' null ist, hat die Person "
        "diese Frage gar nicht getippt.\n\n"
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


FAZIT_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "erklaerung": {"type": "string"}},
    "required": ["text", "erklaerung"], "additionalProperties": False,
}


def generate_fazit(client, fazit, genders):
    names = {fazit.get("sieger"), fazit.get("fuehrender")}
    for kk in ("groesster_aufsteiger", "groesster_absteiger"):
        if fazit.get(kk):
            names.add(fazit[kk]["name"])
    ctx = {**fazit, "geschlechter": {n: genders.get(n, "neutral") for n in names if n}}
    user = (
        "Schreib EINE zugespitzte Boulevard-Schlagzeile (text) PLUS zwei Sätze Unterzeile (erklaerung), die den "
        "abgeschlossenen Spieltag INSGESAMT bilanziert – Spieltagssieger, Lage an der Spitze und die größten "
        "Bewegungen über den ganzen Spieltag. Nur diese Fakten verwenden:\n\n"
        + json.dumps(ctx, ensure_ascii=False, indent=2)
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=700, thinking={"type": "adaptive"},
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": FAZIT_SCHEMA}},
        system=SYSTEM, messages=[{"role": "user", "content": user}],
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def bonus_fallback(ev):
    """Deterministische Bonus-Schlagzeile aus den Fakten (gleicher Clip-Look),
    falls der LLM die Auflösung mal nicht selbst getextet hat."""
    f = ev["facts"]
    was, erg = f.get("was", "Bonus"), f.get("ergebnis", "")
    treffer, leer = f.get("treffer", 0), f.get("leer", 0)
    text = f"Bonus {was}: {erg} steht fest"
    teil = f"{was} ist aufgelöst – {erg} bringt {treffer} Tippern je 4 Punkte."
    det = f.get("leer_detail")
    if det:
        teil_namen = [f"{d['name']} (kein Tipp)" if not d.get("tipp")
                      else f"{d['name']} (tippte {d['tipp']})" for d in det]
        teil += " Leer ausgegangen: " + ", ".join(teil_namen) + "."
    elif leer:
        teil += f" {leer} gingen leer aus."
    return {"text": text, "erklaerung": teil, "type": "bonus_aufloesung",
            "tipper": ev.get("primary", was)}


def ensure_bonus(headlines, events):
    """Garantiert für JEDE Bonus-Auflösung des Tages eine Schlagzeile (additiv).
    Liefert eine neue Liste, mutiert die Eingabe (Cache) nicht."""
    out = list(headlines)
    have = {h.get("tipper") for h in out
            if isinstance(h, dict) and h.get("type") == "bonus_aufloesung"}
    for ev in events:
        if ev.get("type") == "bonus_aufloesung" and ev.get("primary") not in have:
            out.append(bonus_fallback(ev))
            have.add(ev.get("primary"))
    return out


def ground_types(headlines, events):
    """Erdet den Schlagzeilen-Typ an den ECHTEN Ereignissen des Tages.
    Verhindert z. B. ein 'spieltag_fazit'-Etikett an Tagen ohne echten Spieltag-Abschluss."""
    valid = {e["type"] for e in events}
    top_by_tipper = {}
    for e in sorted(events, key=lambda e: -e.get("score", 0)):
        top_by_tipper.setdefault(e["primary"], e["type"])
    for h in headlines:
        if h.get("type") not in valid:
            h["type"] = top_by_tipper.get(h.get("tipper"), "default")
    return headlines


def run():
    key = load_env_key()
    if not key:
        print("Kein ANTHROPIC_API_KEY gefunden – überspringe LLM, behalte Vorlagen-Schlagzeilen.",
              file=sys.stderr)
        return
    client = anthropic.Anthropic(api_key=key)

    events = json.loads((SITE_DATA / "events.json").read_text("utf-8"))
    standings = json.loads((SITE_DATA / "standings.json").read_text("utf-8"))
    genders = load_genders(standings)
    cache = json.loads(CACHE.read_text("utf-8")) if CACHE.exists() else {}

    run_now = dt.datetime.now().isoformat(timespec="minutes")
    blocks = []
    for ed in events.get("editions", []):
        if not ed.get("events"):
            continue  # spielfreier Tag -> keine neue Ausgabe
        D = ed["date"]
        ctx = edition_context(ed, ed.get("season_events"), standings, genders)
        sig = signature(ctx)
        cached = cache.get(D)
        if cached and cached.get("sig") == sig:
            headlines = cached["headlines"]
            cached.setdefault("published_at", run_now)  # Online-Zeit einmal setzen, dann stabil
            published, status = cached["published_at"], "cache"
        else:
            print(f"  {ed['label']}: generiere Schlagzeilen mit {MODEL} …")
            headlines = generate(client, ctx)
            published = run_now
            cache[D] = {"sig": sig, "headlines": headlines, "published_at": published}
            status = "neu"
        headlines = ground_types(headlines, ed["events"] + (ed.get("season_events") or []))
        headlines = ensure_bonus(headlines, ed["events"])  # jede Bonus-Auflösung garantiert
        blocks.append({"date": D, "label": ed["label"], "phase": ed.get("phase"), "span": ed.get("span"),
                       "group_key": ed.get("group_key"), "group": ed.get("group"), "gruppenphase": ed.get("gruppenphase"),
                       "published_at": published, "complete": True, "headlines": headlines})
        print(f"  {ed['label']}: {len(headlines)} Schlagzeilen ({status})")

    blocks.sort(key=lambda b: b["date"], reverse=True)  # neuester Tag oben

    # Eigene Fazit-Schlagzeile je abgeschlossenem Spieltag (EXTRA, ersetzt keine Tages-Schlagzeile)
    spieltage_out = []
    for s in events.get("spieltage", []):
        entry = {k: s.get(k) for k in ("key", "label", "gruppenphase", "complete", "end_date")}
        if s.get("complete") and s.get("fazit"):
            ck = "fazit:" + s["key"]
            sig = signature(s["fazit"])
            cached = cache.get(ck)
            if cached and cached.get("sig") == sig:
                entry["fazit_headline"] = cached["headline"]
            else:
                print(f"  Spieltag-Fazit {s['label']}: generiere …")
                hl = generate_fazit(client, s["fazit"], genders)
                cache[ck] = {"sig": sig, "headline": hl}
                entry["fazit_headline"] = hl
        spieltage_out.append(entry)

    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), "utf-8")
    (SITE_DATA / "headlines.json").write_text(
        json.dumps({"source": "llm", "model": MODEL, "blocks": blocks, "spieltage": spieltage_out},
                   ensure_ascii=False, indent=2), "utf-8")
    nf = sum(1 for s in spieltage_out if s.get("fazit_headline"))
    print(f"✓ {sum(len(b['headlines']) for b in blocks)} Schlagzeilen über {len(blocks)} Tagesausgaben "
          f"+ {nf} Spieltag-Fazits → site/data/headlines.json")


if __name__ == "__main__":
    run()
