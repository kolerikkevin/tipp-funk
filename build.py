#!/usr/bin/env python3
"""
Baut aus den geparsten Rohdaten die Datensätze fürs Frontend – TAGESBASIERT.

Eine "Ausgabe" = ein Spieltag im Kalender-Sinn: alle Spiele eines Abends inkl.
der Nachtspiele bis in den frühen Morgen (Anstoß < 10 Uhr zählt zum Vorabend).
So gibt es jeden Morgen eine neue Ausgabe mit dem, was über Nacht passiert ist.

  site/data/standings.json  – aktuelle Tabelle (+ Spieltag-Spalten, authoritative)
  site/data/history.json    – Platz-Verlauf pro TAG (Bump-Chart)
  site/data/events.json      – Story-Ereignisse pro Tagesausgabe (+ Saison-Storylines)
  site/data/tipps.json       – Tipp-Matrix pro Kicktipp-Spieltag (Referenz)
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARSED = ROOT / "data" / "parsed"
SITE_DATA = ROOT / "site" / "data"

EXACT = 4  # Punkte für exaktes Ergebnis
WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def load():
    standings = json.loads((PARSED / "standings.json").read_text("utf-8"))
    matchdays = json.loads((PARSED / "matchdays.json").read_text("utf-8"))
    meta = json.loads((PARSED / "meta.json").read_text("utf-8"))
    return standings, matchdays, meta


def compute_active(matchdays):
    submitted = defaultdict(int)
    names = []
    for m in matchdays:
        for t in m["tips"]:
            if t["name"] not in submitted:
                names.append(t["name"])
            submitted[t["name"]] += sum(1 for p in t["picks"] if p["tip"])
    return {nm for nm in names if submitted[nm] > 0}


def _kickoff_dt(kickoff: str) -> dt.datetime:
    return dt.datetime.strptime(kickoff[:14].strip(), "%d.%m.%y %H:%M")


def session_date(kickoff: str) -> str:
    """Anstoß < 10 Uhr (Nacht-/Morgenspiel) zählt zum Vorabend -> dessen Ausgabe."""
    d = _kickoff_dt(kickoff)
    if d.hour < 10:
        d -= dt.timedelta(days=1)
    return d.date().isoformat()


def day_short(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.day:02d}.{d.month:02d}."


def day_long(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{WD[d.weekday()]}, {d.day:02d}.{d.month:02d}."


def result_str(g):
    r = g["result"]
    return f"{r['home']}:{r['away']}" if r else "—"


# --------------------------------------------------------------------------- #
# Spiele flach + pro Tipper, chronologisch, mit Tages-Zuordnung
# --------------------------------------------------------------------------- #
def flatten_games(matchdays, active):
    games = []
    for m in matchdays:
        for gi, g in enumerate(m["games"]):
            if not g["played"]:
                continue
            tippers = {}
            for t in m["tips"]:
                if t["name"] not in active:
                    continue
                if gi < len(t["picks"]):
                    p = t["picks"][gi]
                    tippers[t["name"]] = {"tip": p["tip"], "points": p["points"], "correct": p["correct"]}
            games.append({
                "date": session_date(g["kickoff"]), "ko": _kickoff_dt(g["kickoff"]),
                "home": g["home"], "away": g["away"], "group": g["group"],
                "result": g["result"], "tippers": tippers,
            })
    games.sort(key=lambda x: x["ko"])
    return games


def last_played_date(m):
    played = [g for g in m["games"] if g["played"]]
    if not played:
        return None
    return session_date(max(played, key=lambda g: _kickoff_dt(g["kickoff"]))["kickoff"])


def authoritative_timeline(matchdays, active):
    """AUTHORITATIVE Platz-Historie aus Kicktipp (kicktipp-pos je Spieltag, datiert
    auf den letzten Spieltag) + täglichen Snapshots (Live-Stand). KEINE Nachrechnung."""
    nodes = {}
    for m in matchdays:
        if not m["any_played"]:
            continue
        D = last_played_date(m)
        if not D:
            continue
        nodes[D] = {t["name"]: t["position"] for t in m["tips"]
                    if t["name"] in active and t["position"]}
    histdir = ROOT / "data" / "history"
    if histdir.exists():
        for f in sorted(histdir.glob("standings_*.json")):
            snap = json.loads(f.read_text("utf-8"))
            D = snap.get("date")
            ranks = {t["name"]: t["rank"] for t in snap.get("tippers", []) if t["name"] in active}
            if D and ranks:
                nodes[D] = ranks  # täglicher Snapshot = authoritativer Live-Stand des Tages
    return sorted(nodes), nodes


def position_events(timeline_days, nodes, active):
    """Auf-/Absteiger zwischen aufeinanderfolgenden authoritativen Ständen."""
    out, prev = {}, {}
    for D in timeline_days:
        cur, evs = nodes[D], []
        if prev:
            deltas = [(nm, prev[nm] - cur[nm], prev[nm], cur[nm])
                      for nm in active if nm in prev and nm in cur]
            if deltas:
                up = max(deltas, key=lambda x: x[1])
                dn = min(deltas, key=lambda x: x[1])
                if up[1] >= 2:
                    evs.append(("aufsteiger", up[0], {"von": up[2], "auf": up[3], "plaetze": up[1]}, 0.55 + 0.05 * up[1]))
                if dn[1] <= -2:
                    evs.append(("absteiger", dn[0], {"von": dn[2], "auf": dn[3], "plaetze": -dn[1]}, 0.45 + 0.04 * -dn[1]))
        out[D] = evs
        prev = cur
    return out


def build_history(days, pos_by_day, standings, active):
    axis = [{"index": i + 1, "label": day_short(D), "date": day_long(D), "iso": D}
            for i, D in enumerate(days)]
    rank_now = {t["name"]: t["rank"] for t in standings["tippers"]}
    total_now = {t["name"]: t["total"] for t in standings["tippers"]}
    series = []
    for nm in sorted(active, key=lambda n: rank_now.get(n, 99)):
        series.append({"name": nm, "positions": [pos_by_day[D].get(nm) for D in days],
                       "rank": rank_now.get(nm), "total": total_now.get(nm)})
    return {"axis": axis, "n_tippers": len(series), "max_rank": len(standings["tippers"]), "series": series}


# --------------------------------------------------------------------------- #
# Ereignis-Erkennung pro Tagesausgabe
# --------------------------------------------------------------------------- #
def detect_day_events(D, idx, games_today, active):
    events = []

    def ev(type_, primary, facts, score, **extra):
        e = {"type": type_, "date": day_long(D), "edition": idx, "primary": primary,
             "facts": facts, "score": score}
        e.update(extra)
        events.append(e)

    daily_pts = defaultdict(int)
    exact_cnt = defaultdict(int)
    tipped_today = set()
    for g in games_today:
        for nm, p in g["tippers"].items():
            if p["tip"] is not None:
                tipped_today.add(nm)
                daily_pts[nm] += p["points"]
                if p["points"] >= EXACT:
                    exact_cnt[nm] += 1

    # Tagessieger
    if tipped_today:
        mx = max(daily_pts[nm] for nm in tipped_today)
        if mx > 0:
            for nm in tipped_today:
                if daily_pts[nm] == mx:
                    ev("tagessieger", nm, {"punkte": mx, "exakte_treffer": exact_cnt[nm]}, 0.8)

    # Perfekter Tag (alle Spiele des Tages richtig getippt)
    for nm in active:
        picks = [g["tippers"].get(nm) for g in games_today]
        if picks and all(p and p["tip"] is not None and p["correct"] for p in picks):
            ev("perfekter_spieltag", nm, {"spiele": len(games_today), "punkte": daily_pts[nm]}, 0.95)

    # Pro Spiel: Seltenheits-Stories
    for g in games_today:
        subs = {nm: p for nm, p in g["tippers"].items() if p["tip"] is not None}
        denom = len(subs)
        if denom == 0:
            continue
        exact = [nm for nm, p in subs.items() if p["points"] >= EXACT]
        anyp = [nm for nm, p in subs.items() if p["points"] > 0]
        partie = f"{g['home']}–{g['away']}"
        if len(exact) == 1:
            ev("einsamer_volltreffer", exact[0], {"spiel": partie, "ergebnis": result_str(g)}, 0.9)
        hit = len(anyp) / denom
        if 0 < hit <= 0.25 and anyp:
            for nm in anyp:
                ev("unwahrscheinlicher_treffer", nm,
                   {"spiel": partie, "ergebnis": result_str(g),
                    "quote": f"nur {len(anyp)} von {denom} lagen richtig", "punkte": subs[nm]["points"]},
                   0.7 + (0.25 - hit))

    # (Auf-/Absteiger laufen über die authoritative Timeline, nicht hier.)

    # Pechvogel (schwächster, der heute getippt hat)
    if tipped_today:
        worst = min(tipped_today, key=lambda nm: daily_pts[nm])
        ev("pechvogel", worst, {"punkte": daily_pts[worst]}, 0.4)

    return events, tipped_today


def detect_season_events(history, standings, active):
    events = []
    axis = history["axis"]
    if not axis:
        return events
    last_date = axis[-1]["date"]
    tip = [t for t in standings["tippers"] if t["name"] in active]

    def ev(type_, primary, facts, score):
        events.append({"type": type_, "date": last_date, "edition": len(axis),
                       "primary": primary, "facts": facts, "score": score})

    leader = next((t for t in tip if t["rank"] == 1), None)
    if leader:
        s = next((x for x in history["series"] if x["name"] == leader["name"]), None)
        streak = 0
        if s:
            for p in reversed(s["positions"]):
                if p == 1:
                    streak += 1
                else:
                    break
        if streak >= 2:
            ev("fuehrungsserie", leader["name"], {"tage": streak, "punkte": leader["total"]}, 0.8)

    if len(tip) >= 2:
        gap = (tip[0]["total"] or 0) - (tip[1]["total"] or 0)
        if gap <= 4:
            ev("enges_rennen", tip[0]["name"],
               {"erster": tip[0]["name"], "zweiter": tip[1]["name"], "abstand": gap}, 0.65)

    best = None
    for s in history["series"]:
        ps = [p for p in s["positions"] if p]
        if len(ps) >= 2 and (best is None or ps[0] - ps[-1] > best[1]):
            best = (s["name"], ps[0] - ps[-1], ps[0], ps[-1])
    if best and best[1] >= 3:
        ev("saison_aufsteiger", best[0], {"von": best[2], "auf": best[3], "plaetze": best[1]}, 0.6)

    if tip:
        last = max(tip, key=lambda t: t["rank"])
        ev("rote_laterne", last["name"], {"platz": last["rank"], "punkte": last["total"]}, 0.35)

    return events


# --------------------------------------------------------------------------- #
# Tipp-Matrix pro Kicktipp-Spieltag (Referenz-Ansicht)
# --------------------------------------------------------------------------- #
def build_tipps(matchdays, active):
    out = []
    for m in matchdays:
        if not m["any_played"]:
            continue
        games = [{"home": g["home"], "away": g["away"], "group": g["group"],
                  "result": (f"{g['result']['home']}:{g['result']['away']}" if g["result"] else None)}
                 for g in m["games"]]
        rows = []
        for t in m["tips"]:
            if t["name"] not in active:
                continue
            picks = [{"tip": (f"{p['tip']['home']}:{p['tip']['away']}" if p["tip"] else None),
                      "points": p["points"], "correct": p["correct"]} for p in t["picks"]]
            rows.append({"name": t["name"], "position": t["position"],
                         "spieltag_points": t["spieltag_points"], "picks": picks})
        rows.sort(key=lambda r: r["position"] if r["position"] else 999)
        out.append({"matchday": m["spieltag_index"], "date": (m["date"] or ""),
                    "complete": m["all_played"], "games": games, "rows": rows})
    return out


# --------------------------------------------------------------------------- #
# Schlagzeilen-Vorlage (Fallback, falls kein LLM)
# --------------------------------------------------------------------------- #
_TEMPLATES = {
    "perfekter_spieltag": "Perfekt-Tag! {primary} trifft alle {spiele} Spiele – {punkte} Punkte.",
    "einsamer_volltreffer": "Hellseher {primary}: Als Einziger {ergebnis} bei {spiel} getippt.",
    "unwahrscheinlicher_treffer": "{primary} traut sich was: {spiel} {ergebnis} – {quote}.",
    "tagessieger": "{primary} räumt ab: Tagessieg mit {punkte} Punkten.",
    "tipp_vergessen": "Verplant! {primary} vergisst heute glatt zu tippen.",
    "aufsteiger": "Raketenstart: {primary} klettert von Platz {von} auf {auf}.",
    "absteiger": "Absturz: {primary} rutscht von Platz {von} auf {auf}.",
    "pechvogel": "Gebrauchter Tag für {primary}: magere {punkte} Punkte.",
    "fuehrungsserie": "{primary} thront weiter oben – {tage} Tage in Folge Platz 1.",
    "enges_rennen": "Es wird eng: {erster} nur {abstand} Punkte vor {zweiter}.",
    "saison_aufsteiger": "{primary} dreht auf: von Platz {von} auf {auf} seit Turnierstart.",
    "rote_laterne": "Rote Laterne: {primary} ziert das Tabellenende.",
}


def render_headlines(editions, limit=5):
    blocks = []
    for d in reversed(editions):
        pool = list(d["events"]) + list(d.get("season_events", []))
        pool.sort(key=lambda e: -e["score"])
        lines, seen = [], set()
        for e in pool:
            if e["type"] in seen or e["type"] not in _TEMPLATES:
                continue
            seen.add(e["type"])
            try:
                lines.append(_TEMPLATES[e["type"]].format(primary=e["primary"], **e["facts"]))
            except KeyError:
                continue
            if len(lines) >= limit:
                break
        blocks.append({"date": d["date"], "label": d["label"], "complete": True, "headlines": lines})
    return blocks


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def run():
    standings, matchdays, meta = load()
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    active = compute_active(matchdays)
    inactive = [t["name"] for t in standings["tippers"] if t["name"] not in active]

    games = flatten_games(matchdays, active)
    game_days = sorted({g["date"] for g in games})
    timeline_days, nodes = authoritative_timeline(matchdays, active)
    history = build_history(timeline_days, nodes, standings, active)
    pos_ev = position_events(timeline_days, nodes, active)

    editions = []
    tipped_ever = set()
    field = len(active)
    for i, D in enumerate(game_days, start=1):
        games_today = [g for g in games if g["date"] == D]
        evs, tipped_today = detect_day_events(D, i, games_today, active)
        # authoritative Auf-/Absteiger, falls für diesen Tag ein echter Stand vorliegt
        for typ, prim, facts, score in pos_ev.get(D, []):
            evs.append({"type": typ, "date": day_long(D), "edition": i, "primary": prim, "facts": facts, "score": score})
        # jüngster authoritativer Stand <= D (für "Tipp vergessen"-Einordnung)
        auth = {}
        for TD in timeline_days:
            if TD <= D:
                auth = nodes[TD]
            else:
                break
        cutoff = max(3, field // 3)
        for nm in active:
            if nm in tipped_ever and nm not in tipped_today:
                pos = auth.get(nm)
                lage = "keller" if pos and pos > field - cutoff else ("war_oben" if pos and pos <= cutoff else "mittelfeld")
                evs.append({"type": "tipp_vergessen", "date": day_long(D), "edition": i, "primary": nm,
                            "facts": {"jetzt_platz": pos, "lage": lage}, "score": 0.85, "lage": lage})
        tipped_ever |= tipped_today
        editions.append({
            "date": D, "label": day_long(D),
            "games": [{"partie": f"{g['home']}–{g['away']}", "ergebnis": result_str(g)} for g in games_today],
            "events": sorted(evs, key=lambda e: -e["score"]),
        })

    season = sorted(detect_season_events(history, standings, active), key=lambda e: -e["score"])
    if editions:
        editions[-1]["season_events"] = season

    events_out = {"generated_for": meta["scraped_at"],
                  "latest": day_long(game_days[-1]) if game_days else None, "editions": editions}

    table = [{**t, "active": t["name"] in active} for t in standings["tippers"]]
    (SITE_DATA / "standings.json").write_text(json.dumps(
        {"tippers": table, "scraped_at": meta["scraped_at"], "inactive": inactive,
         "spieltage": meta["played_matchdays"]}, ensure_ascii=False, indent=2), "utf-8")
    (SITE_DATA / "history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), "utf-8")
    (SITE_DATA / "tipps.json").write_text(json.dumps(
        {"matchdays": build_tipps(matchdays, active)}, ensure_ascii=False, indent=2), "utf-8")
    (SITE_DATA / "events.json").write_text(json.dumps(events_out, ensure_ascii=False, indent=2), "utf-8")

    hl = SITE_DATA / "headlines.json"
    if not hl.exists():
        hl.write_text(json.dumps({"source": "template", "generated_at": meta["scraped_at"],
                                  "blocks": render_headlines(editions)}, ensure_ascii=False, indent=2), "utf-8")

    n_ev = sum(len(d["events"]) for d in editions)
    print(f"✓ aktiv:   {len(active)} Tipper · ignoriert: {inactive or '–'}")
    print(f"✓ history: {history['n_tippers']} Tipper, {len(timeline_days)} authoritative Stände (Verlauf)")
    print(f"✓ events:  {n_ev} Ereignisse über {len(editions)} Tagesausgaben + {len(season)} Saison-Storylines")
    return events_out


if __name__ == "__main__":
    run()
