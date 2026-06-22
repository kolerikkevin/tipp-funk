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
from collections import Counter, defaultdict
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
# Offizieller WM-Spieltag / K.-o.-Runde ableiten (NICHT Kicktipps interne Zählung)
# --------------------------------------------------------------------------- #
def assign_official_md(matchdays):
    """Gruppenphase: pro Gruppe Spiele nach Anstoß sortiert, je 2 = 1 offizieller Spieltag (1–3).
    K.-o.: Runden-Name aus dem Gruppe-Feld. Mutiert die Spiel-Dicts."""
    bygrp = defaultdict(list)
    for m in matchdays:
        for g in m["games"]:
            grp = g.get("group") or ""
            if grp.startswith("Gruppe"):
                bygrp[grp].append(g)
            else:
                g["official_md"], g["round"], g["phase_kind"] = None, (grp or "K.-o.-Runde"), "ko"
    for grp, gs in bygrp.items():
        gs.sort(key=lambda g: _kickoff_dt(g["kickoff"]))
        for i, g in enumerate(gs):
            g["official_md"], g["round"], g["phase_kind"] = i // 2 + 1, "Gruppenphase", "gruppe"
    return matchdays


def unit_key(g):
    """Eindeutiger Schlüssel der offiziellen Einheit (Gruppen-Spieltag oder K.-o.-Runde)."""
    if g.get("phase_kind") == "gruppe":
        return ("g", g["official_md"])
    if g.get("phase_kind") == "ko":
        return ("k", g["round"])
    return None


def unit_label(key):
    return f"{key[1]}. Spieltag" if key[0] == "g" else key[1]


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
                "spieltag": m["spieltag_index"],
                "official_md": g.get("official_md"), "round": g.get("round"), "phase_kind": g.get("phase_kind"),
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


def daily_reconstruction(games, day, active):
    """Tages-Stand nach kumulierten Spiel-Punkten bis einschließlich `day` (ohne Bonus)."""
    cum = defaultdict(int)
    for g in games:
        if g["date"] <= day:
            for nm, p in g["tippers"].items():
                cum[nm] += p["points"]
    ranked = sorted(active, key=lambda nm: (-cum.get(nm, 0), nm))
    return {nm: i + 1 for i, nm in enumerate(ranked)}


def build_history_tage(games, game_days, nodes, standings, active):
    """TAGES-Verlauf: ein Punkt pro Spielabend. Offizielle Stände (Spieltag-Ende + Snapshots)
    sind exakt (nodes); Tage dazwischen werden aus den Tagespunkten geschätzt."""
    all_days = sorted(set(game_days) | set(nodes))
    pos = {D: (nodes[D] if D in nodes else daily_reconstruction(games, D, active)) for D in all_days}
    axis = [{"index": i + 1, "label": day_short(D), "date": day_long(D), "iso": D, "official": D in nodes}
            for i, D in enumerate(all_days)]
    rank_now = {t["name"]: t["rank"] for t in standings["tippers"]}
    total_now = {t["name"]: t["total"] for t in standings["tippers"]}
    series = []
    for nm in sorted(active, key=lambda n: rank_now.get(n, 99)):
        series.append({"name": nm, "positions": [pos[D].get(nm) for D in all_days],
                       "rank": rank_now.get(nm), "total": total_now.get(nm)})
    return {"axis": axis, "n_tippers": len(series), "max_rank": len(standings["tippers"]), "series": series}


def build_history_spieltag(matchdays, standings, active):
    """Diagramm-Ansicht 'Spieltage' = OFFIZIELLE Spieltage/K.-o.-Runden, verankert am
    Kicktipp-Spieltag, der sie abschließt (authoritative kicktipp-pos) + aktueller Stand."""
    unit_kt = {}   # offizielle Einheit -> abschließender Kicktipp-Spieltag
    for m in matchdays:
        for g in m["games"]:
            k = unit_key(g)
            if k:
                unit_kt[k] = max(unit_kt.get(k, 0), m["spieltag_index"])
    kt_done = {m["spieltag_index"]: m["all_played"] for m in matchdays}
    kt_pos = {m["spieltag_index"]: {t["name"]: t["position"] for t in m["tips"]} for m in matchdays}
    rank_now = {t["name"]: t["rank"] for t in standings["tippers"]}
    total_now = {t["name"]: t["total"] for t in standings["tippers"]}

    done = sorted([k for k in unit_kt if kt_done.get(unit_kt[k])], key=lambda k: unit_kt[k])
    axis = [{"index": i + 1, "label": unit_label(k), "date": "", "official": True} for i, k in enumerate(done)]
    nodes = [kt_pos[unit_kt[k]] for k in done]
    axis.append({"index": len(axis) + 1, "label": "jetzt", "date": "", "official": False})
    nodes.append(rank_now)

    series = []
    for nm in sorted(active, key=lambda n: rank_now.get(n, 99)):
        series.append({"name": nm, "positions": [nd.get(nm) for nd in nodes],
                       "rank": rank_now.get(nm), "total": total_now.get(nm)})
    return {"axis": axis, "series": series}


def build_spieltage(matchdays, games, active):
    """Übergeordnete Spieltag-Gruppen (offiziell) + Fazit-Fakten über den GANZEN Spieltag
    (Sieger, Führung, größte Bewegungen vom Spieltag-Start zum -Ende)."""
    kt_pos = {m["spieltag_index"]: {t["name"]: t["position"] for t in m["tips"] if t["name"] in active}
              for m in matchdays}
    kt_done = {m["spieltag_index"]: m["all_played"] for m in matchdays}
    units, end_kt = defaultdict(list), {}
    for m in matchdays:
        for g in m["games"]:
            k = unit_key(g)
            if k:
                units[k].append(g)
                end_kt[k] = max(end_kt.get(k, 0), m["spieltag_index"])
    present = sorted([k for k in units if any(g["played"] for g in units[k])], key=lambda k: end_kt[k])
    out = []
    for idx, k in enumerate(present):
        gs = units[k]
        played = [g for g in gs if g["played"]]
        complete = all(g["played"] for g in gs) and kt_done.get(end_kt[k], False)
        end_date = session_date(max(played, key=lambda g: _kickoff_dt(g["kickoff"]))["kickoff"]) if played else None
        entry = {"key": f"{k[0]}:{k[1]}", "label": unit_label(k), "gruppenphase": k[0] == "g",
                 "complete": complete, "end_date": end_date}
        if complete:
            pts = defaultdict(int)
            for fg in games:
                if unit_key(fg) == k:
                    for nm, p in fg["tippers"].items():
                        pts[nm] += p["points"]
            if pts:
                sieger = max(pts, key=pts.get)
                end_pos = kt_pos.get(end_kt[k], {})
                start_pos = kt_pos.get(end_kt[present[idx - 1]], {}) if idx > 0 else {}
                fuehrender = min(end_pos, key=end_pos.get) if end_pos else None
                movers = [(nm, start_pos[nm] - end_pos[nm]) for nm in end_pos if nm in start_pos]
                auf = max(movers, key=lambda x: x[1]) if movers else None
                ab = min(movers, key=lambda x: x[1]) if movers else None
                fazit = {"spieltag": unit_label(k), "sieger": sieger, "sieger_punkte": pts[sieger]}
                if fuehrender:
                    fazit["fuehrender"] = fuehrender
                if auf and auf[1] >= 2:
                    fazit["groesster_aufsteiger"] = {"name": auf[0], "plaetze": auf[1]}
                if ab and ab[1] <= -2:
                    fazit["groesster_absteiger"] = {"name": ab[0], "plaetze": -ab[1]}
                entry["fazit"] = fazit
        out.append(entry)
    out.sort(key=lambda e: e["end_date"] or "0", reverse=True)
    return out


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
    "spieltag_fazit": "{spieltag} ist Geschichte: {sieger} schnappt sich den Spieltagssieg.",
    "tipp_vergessen": "Verplant! {primary} vergisst heute glatt zu tippen.",
    "aufsteiger": "Raketenstart: {primary} klettert von Platz {von} auf {auf}.",
    "absteiger": "Absturz: {primary} rutscht von Platz {von} auf {auf}.",
    "pechvogel": "Gebrauchter Tag für {primary}: magere {punkte} Punkte.",
    "mittelfeld_dauergast": "Dauergast Mittelfeld: {primary} hängt seit Tagen rund um Platz {platz} fest.",
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
    assign_official_md(matchdays)   # offizielle WM-Spieltage / K.-o.-Runden ableiten
    active = compute_active(matchdays)
    inactive = [t["name"] for t in standings["tippers"] if t["name"] not in active]

    games = flatten_games(matchdays, active)
    game_days = sorted({g["date"] for g in games})
    timeline_days, nodes = authoritative_timeline(matchdays, active)
    history = build_history_tage(games, game_days, nodes, standings, active)   # Tage = Standard
    history["spieltage"] = build_history_spieltag(matchdays, standings, active)
    pos_ev = position_events(timeline_days, nodes, active)

    # Übergeordnete Spieltag-Gruppen + Fazit über den GANZEN Spieltag (separat, ersetzt keine Tages-Schlagzeile)
    spieltage = build_spieltage(matchdays, games, active)

    pos_by_day = {D: (nodes[D] if D in nodes else daily_reconstruction(games, D, active)) for D in game_days}

    editions = []
    tipped_ever = set()
    miss_streak = defaultdict(int)
    last_dropped = set()
    field = len(active)
    for i, D in enumerate(game_days, start=1):
        games_today = [g for g in games if g["date"] == D]
        pub = (dt.date.fromisoformat(D) + dt.timedelta(days=1)).isoformat()  # Ausgabe = nächster Morgen
        pub_label = day_long(pub)
        evs, tipped_today = detect_day_events(D, i, games_today, active)

        # Aussetzer-Serie: wer 2x in Folge nicht tippt, gilt als ausgestiegen
        for nm in active:
            miss_streak[nm] = 0 if nm in tipped_today else miss_streak[nm] + 1
        dropped = {nm for nm in active if miss_streak[nm] >= 2}
        last_dropped = dropped

        for typ, prim, facts, score in pos_ev.get(D, []):
            evs.append({"type": typ, "date": pub_label, "edition": i, "primary": prim, "facts": facts, "score": score})

        auth = {}
        for TD in timeline_days:
            if TD <= D:
                auth = nodes[TD]
            else:
                break
        cutoff = max(3, field // 3)
        # "Tipp vergessen" NUR beim ersten Aussetzer (ab dem zweiten gilt er als raus)
        for nm in active:
            if miss_streak[nm] == 1 and nm in tipped_ever:
                pos = auth.get(nm)
                lage = "keller" if pos and pos > field - cutoff else ("war_oben" if pos and pos <= cutoff else "mittelfeld")
                evs.append({"type": "tipp_vergessen", "date": pub_label, "edition": i, "primary": nm,
                            "facts": {"jetzt_platz": pos, "lage": lage}, "score": 0.85, "lage": lage})
        tipped_ever |= tipped_today

        # Mittelfeld-Dauergast: alle paar Tage einen würdigen, der lange im Mittelfeld dümpelt (rotierend)
        if i % 3 == 0:
            recent = game_days[max(0, i - 4):i]
            lo, hi = field // 4, field - field // 4
            mids = []
            for nm in active:
                if nm in dropped:
                    continue
                poss = [pos_by_day[d].get(nm) for d in recent]
                if len(poss) >= 3 and all(p and lo < p <= hi for p in poss):
                    mids.append((nm, pos_by_day[D].get(nm), len(poss)))
            if mids:
                mids.sort()
                nm, pos, tage = mids[(i // 3) % len(mids)]
                evs.append({"type": "mittelfeld_dauergast", "date": pub_label, "edition": i, "primary": nm,
                            "facts": {"platz": pos, "tage": tage}, "score": 0.5})

        # Ausgestiegene Tipper komplett aus den Schlagzeilen nehmen
        evs = [e for e in evs if e["primary"] not in dropped]

        # Offizielle Phase des Tages (offizieller WM-Spieltag bzw. K.-o.-Runde)
        if any(g.get("phase_kind") == "ko" for g in games_today):
            phase = next((g["round"] for g in games_today if g.get("phase_kind") == "ko"), "K.-o.-Runde")
        else:
            mds = sorted({g["official_md"] for g in games_today if g.get("official_md")})
            phase = (f"Gruppenphase · {mds[0]}. Spieltag" if len(mds) == 1
                     else f"Gruppenphase · {mds[0]}.–{mds[-1]}. Spieltag") if mds else None

        # Übergeordnete Spieltag-Gruppe (dominanter offizieller Spieltag des Tages)
        if any(g.get("phase_kind") == "ko" for g in games_today):
            rnd = next((g["round"] for g in games_today if g.get("phase_kind") == "ko"), "K.-o.-Runde")
            grp_key, grp_label, grp_gruppe = f"k:{rnd}", rnd, False
        else:
            dom = Counter(g["official_md"] for g in games_today if g.get("official_md")).most_common(1)
            grp_key, grp_label, grp_gruppe = ((f"g:{dom[0][0]}", f"{dom[0][0]}. Spieltag", True)
                                              if dom else ("g:?", "Spieltag", True))

        # Zwei-Kalender-Tage-Spann der Spiele (Abend -> Nacht -> Morgen)
        gdates = sorted({g["ko"].date() for g in games_today})
        span = (f"{gdates[0].day:02d}.–{gdates[-1].day:02d}.{gdates[-1].month:02d}."
                if len(gdates) > 1 else f"{gdates[0].day:02d}.{gdates[0].month:02d}.") if gdates else None

        editions.append({
            "date": pub, "label": pub_label, "phase": phase, "span": span,
            "group_key": grp_key, "group": grp_label, "gruppenphase": grp_gruppe,
            "games": [{"partie": f"{g['home']}–{g['away']}", "ergebnis": result_str(g)} for g in games_today],
            "events": sorted(evs, key=lambda e: -e["score"]),
        })

    season = [e for e in sorted(detect_season_events(history, standings, active), key=lambda e: -e["score"])
              if e["primary"] not in last_dropped]
    if editions:
        editions[-1]["season_events"] = season

    events_out = {"generated_for": meta["scraped_at"],
                  "latest": editions[-1]["label"] if editions else None,
                  "editions": editions, "spieltage": spieltage}

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
