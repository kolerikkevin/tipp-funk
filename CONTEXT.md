# CONTEXT — tippspiel-chronik (Handoff für neue Chats)

> **Lies das zuerst.** Dieses Dokument enthält alles, was man braucht, um am Tool
> sauber weiterzuarbeiten — Architektur, Deploy-Runbook, Domänen-Logik, Stolperfallen.
> Stand: 2026-06-22 (komplett live geschaltet & mehrfach iteriert).

---

## 1. Was das ist

Tägliches Boulevard-Dashboard für Kevins Büro-Tippspiel auf **Kicktipp**
(„PortfolioundEntwicklung", WM 2026). Zieht die **öffentlichen** Kicktipp-Seiten (kein Login),
erkennt kleine Geschichten in den Daten und lässt **Claude Opus 4.8** Boulevard-Schlagzeilen
texten. Plus Platz-Verlauf-Chart, Tabelle, Tipp-Matrix, Bonus-Layer.

- **Live:** https://kolerikkevin.github.io/tipp-funk/
- **GitHub-Repo:** https://github.com/kolerikkevin/tipp-funk (öffentlich)
- **Lokaler Ordner:** `tools/tippspiel-chronik/` — **eigenständiges Git-Repo** (eigener `.git`,
  NICHT Teil des claudecode-Monorepos). `origin` = das GitHub-Repo, Branch `main`.

## 2. Wie es betrieben wird (vollautomatisch)

GitHub Actions Workflow `.github/workflows/daily.yml`:
- **Cron `30 6 * * *`** = 06:30 UTC = **08:30 Sommerzeit / 07:30 Winterzeit** (GitHub kann nur UTC).
- Job `update`: `pip install` → `python update.py` → committet neuen Stand zurück → lädt `site/` als Artifact.
- Job `deploy`: published `site/` zu GitHub Pages.
- Läuft in der Cloud, der Mac kann aus sein. Pages-Quelle = **GitHub Actions** (Settings → Pages).
- Repo-Settings nötig (sind gesetzt): Actions → Workflow permissions = **Read and write**;
  Secret **`ANTHROPIC_API_KEY`** (Settings → Secrets → Actions).

**Ohne Key läuft es trotzdem** — `headlines.run()` überspringt dann das LLM und behält die
vorhandenen Schlagzeilen (kein harter Abbruch).

**Inaktivitäts-Falle:** Geplante Workflows pausieren nach ~60 Tagen ohne *menschliche* Aktivität
(Bot-Commits zählen evtl. nicht). GitHub mailt vorher einen „Re-enable"-Knopf. Jeder echte Push
setzt die Uhr zurück. Die Seite selbst bleibt online (statisch), nur das Auto-Update pausiert.

## 3. Änderungen machen & live bringen (RUNBUCH)

Der normale Loop, wenn Kevin etwas verbessern will:

1. **Lokal editieren** in `tools/tippspiel-chronik/`. Frontend = `site/` (statisch, siehe §5).
2. **Lokal verifizieren** (siehe §6): bei Pipeline-Änderungen `python3 build.py` (ggf. 2× für
   Determinismus-Check), bei Frontend-Änderungen Vorschau-Server (`python3 -m http.server -d site 8011`).
3. **Bei JS/CSS-Änderungen: Cache-Version bumpen** in `site/index.html`
   (`app.js?v=N` / `styles.css?v=N`, N hochzählen) — sonst laden Browser das alte File aus dem Cache
   (Symptom: `[object Object]` o. kaputte Tabelle). Aktuell: `app.js?v=3`.
4. **Committen auf `main` + pushen** (`git push origin main`). Push-Auth liegt im macOS-Schlüsselbund
   (PAT „tipp-funk-push", siehe §4). Kein Token-Tippen mehr nötig.
5. **Deploy anstoßen:** Ein reiner Push deployt NICHT. Auf github.com → Repo → **Actions** →
   „Tägliches Tipp-Funk Update" → **Run workflow** (Branch main). Nach ~2–3 Min live.
   (Alternativ: einfach auf den nächsten 08:30-Lauf warten.)
6. **Live verifizieren.** Pages-CDN + Browsercache brauchen evtl. eine Minute; bei stalem Stand
   hart neu laden (Cmd+Shift+R).

## 4. Geheimnisse / Zugänge

- **Anthropic-Key:** lokal in `tools/tippspiel-chronik/.env` (`ANTHROPIC_API_KEY=…`), **gitignored**
  (wird nie gepusht). Auf GitHub als Repo-Secret hinterlegt. Modell: `claude-opus-4-8`
  (überschreibbar via Env `HEADLINE_MODEL`).
- **Push-Token (PAT classic „tipp-funk-push"):** liegt im macOS-Schlüsselbund (`osxkeychain`),
  Scopes `repo` + `workflow`. **Läuft ~2026-07-22 ab** → dann hakt der nächste Push.
  Erneuern: github.com → Settings → Developer settings → Personal access tokens (classic) →
  tipp-funk-push → **Regenerate token** → neuen Wert kopieren → einmal
  `printf "protocol=https\nhost=github.com\nusername=kolerikkevin\npassword=<TOKEN>\n\n" | git credential-osxkeychain store`.
  (Langfristig sauberer: SSH-Key einrichten, läuft nie ab — Kevin wollte das vorerst nicht.)
- **GitHub-User:** `kolerikkevin`.

## 5. Architektur & Datenfluss

```
scrape.py    →  data/parsed/*.json        Rohdaten ziehen + parsen (Kicktipp, öffentlich)
build.py     →  site/data/*.json          Platz-Verlauf, Story-Events, Tabelle, Bonus
headlines.py →  site/data/headlines.json  Claude textet Schlagzeilen aus Events (gecacht)
update.py    →  alles nacheinander         der EINE tägliche Befehl
```

**GENERIERT (von build/headlines, NICHT von Hand editieren):** `site/data/*.json`,
`data/parsed/*.json`, `data/history/*.json`, `data/headline_cache.json`.

**STATISCH (von Hand gepflegt, vom Frontend benutzt):** `site/index.html`, `site/app.js`,
`site/styles.css`, `site/favicon.svg`. ← Hier sitzt das ganze Frontend. `build.py` fasst diese NIE an.

- Frontend: eine Single-Page-App (`app.js`), lädt die `site/data/*.json` per fetch (cache-bust `?t=`).
  Views: News (Start), Tabelle, Tipps, Platz-Verlauf, Bonus.
- Look: 80er-BR-Retro (BR-Blau `#1488bc`, Creme, Fonts Anton+VT323+Archivo, Scanlines, Hard-Shadows).
  Titel-Banner: **„PFM Tippkick Daily"**. Menü-Reihenfolge: News / Tabelle / Tipps / Platz-Verlauf / Bonus.

## 6. Lokal testen

```bash
cd tools/tippspiel-chronik
pip install -r requirements.txt
python3 update.py                      # voller Lauf (scrape+build+headlines, braucht Key)
python3 build.py                       # nur neu rechnen (kein Key nötig, kein Netz für headlines)
python3 -m http.server -d site 8011    # → http://localhost:8011
```
**Determinismus-Check** (wichtig, siehe §8): `python3 build.py` zweimal laufen lassen, `site/data/events.json`
muss (ohne `generated_for`) identisch sein.

## 7. Domänen-Logik — TAG vs. SPIELTAG (Kevin legt großen Wert drauf!)

WM 2026 ist in den USA → Spiele laufen oft in der **deutschen Nacht**. Zwei Achsen:

- **TAG = eine Ausgabe-„Schicht" Abend → Nacht → Morgen = EINE Einheit.**
  Regel: Anstoß **< 10:00 Uhr zählt zum Vorabend** (`session_date()` in build.py). So gehören
  Sonntagabend- bis Montagfrüh-Spiele zu *einer* Schicht. Eine Schicht wird **auf den Morgen
  datiert (= session_date + 1)** — sie „erscheint" am nächsten Morgen.
  - News-Feed-Ausgabe: Label = Morgen-Datum (z. B. „Mo, 22.06.") + Spann „Spiele 21.–22.06.".
  - **Tabelle „Tage"-Ansicht: ebenfalls Morgen-Datum** (an den Feed angeglichen, damit dieselbe
    Schicht überall denselben Tag trägt). `daily_table()` keyed auf `session_date+1`.
  - ⚠️ Der Chart-Modus „Tage" nutzt aktuell noch reine session_date-Tage (NICHT angeglichen) —
    offener Punkt, falls Kevin Konsistenz auch dort will.
- **SPIELTAG = OFFIZIELLER WM-Spieltag, NICHT Kicktipps interne Zählung.**
  Kicktipp bündelt ~8 Spiele pro „Spieltag" (1–15) = nur Tipp-Runden. Wir leiten die echten ab:
  pro Gruppe Spiele nach Anstoß sortiert, je 2 = 1 offizieller Spieltag (Gruppenphase 1–3);
  K.-o. = Runden-Name. Funktionen: `assign_official_md()`, `unit_key()`.
  - **Tabelle „Spieltage"-Ansicht** (Standard): Spalten = offizielle Spieltage (1, 2, … / AF/VF/HF/FIN),
    Punkte aus Einzelspielen neu aggregiert (`official_matchday_table()`). Kicktipps 8er-Blöcke
    werden NICHT mehr angezeigt.
  - News-Feed-Gruppenkopf: „N. SPIELTAG · Gruppenphase". Chart-Modus „Spieltage" = offizielle Spieltage.
- **Tabelle hat einen Umschalter „Spieltage / Tage"** (oben rechts, wie der Chart). Spalten-Format
  ist `{key, kurz, lang}`; pro Tipper `matchday_points` (Spieltage) und `tag_points` (Tage).
  Beides summiert zu den Einzelspiel-Punkten; **Gesamt = Einzelspiel-Punkte + Bonus** (B-Spalte).

## 8. Cache & Determinismus (kritisch — sonst „texten bei jedem Deploy alles neu")

- Schlagzeilen sind **pro Tag gecacht** in `data/headline_cache.json`, Schlüssel = `signature(ctx)`
  (SHA-256 über den Kontext der Ausgabe). Cache-Hit → nicht neu texten. Nur neue/geänderte Tage texten.
- **Der Build MUSS deterministisch sein**, sonst ändert sich `ctx` bei jedem Lauf trotz gleichem
  Endstand → Cache verfehlt → alles wird neu getextet (kostet Geld+Zeit). Ursache war früher
  `compute_active()` als `set` (ungeordnet) → **gibt jetzt eine LISTE zurück**. Auch alle
  `max/min/sorted` über Tipper haben stabile Tiebreaker (Name). **NICHT wieder set-Iteration oder
  Sortierung ohne Tiebreaker einbauen.** Verifizieren: `build.py` 2× → identische `events.json`.
- **Prompt-Änderungen (SYSTEM-Text in headlines.py) ändern den Cache-Key NICHT** → alte
  Schlagzeilen bleiben, nur neu getextete bekommen die neue Regel. Das ist gewollt.
- **Einen einzelnen Tag gezielt neu texten:** dessen Datum-Key aus `data/headline_cache.json`
  entfernen → `python3 headlines.py` (braucht Key) → nur dieser Tag wird neu getextet.

## 9. Schlagzeilen-Regeln (headlines.py, SYSTEM-Prompt)

- Claude **Opus 4.8**, offizielles `anthropic`-SDK, Structured Output (Schlagzeile + 2-Satz-`erklaerung`),
  Bild-Mechanik. ≥3 Schlagzeilen/Tag, Tipper wie Stars/Teams, Konkurrenz-Vibe, auch hintere Plätze
  + Verplante („Tipp vergessen") liebevoll aufziehen, nicht beleidigend.
- **KEINE Tageszeit erfinden** (US-WM → Spiele oft deutsche Nacht): kein „am Montagabend", wenn die
  Uhrzeit nicht vorliegt → neutral „am Montag" / „an diesem Spieltag". (Regel im SYSTEM-Prompt.)
- **Namen sind Fußball-Wortspiele**, nicht Popkultur: z. B. „Schrammadonna" = **Maradona**, nicht Madonna.
  Im Zweifel Namen neutral lassen.
- **Geschlecht:** `genders.json` (m/w/neutral) fließt in den Prompt; „neutral" = strikt
  geschlechtsneutral formulieren (kein er/sie, kein Sieger/Siegerin). Datei ist gefüllt & getrackt.
- **Aussteiger** (2× in Folge nicht getippt) → ganz raus aus Schlagzeilen (1. Aussetzer noch „verplant"),
  zurück sobald wieder getippt. **Nicht-Tipper** (nie getippt) → raus aus Chart+Stories.
- **Spieltag-Fazit** = EIGENE Extra-Meldung pro abgeschlossenem Spieltag (`generate_fazit`, gecacht
  `fazit:<key>`), ersetzt keine Tages-Schlagzeile. `ground_types()` erdet LLM-Typ-Etiketten an echten Events.

## 10. Bonus-Layer (Langfrist-Tipps)

Eigene öffentliche Seite `tippuebersicht?bonus=true`. 18 Fragen: Torschützen-Nation(1) ·
Halbfinalisten(4) · Gruppensieger A–L(12) · Weltmeister(1), je 4 P/Treffer. **Punkte fließen nach
und nach** (Frage sobald entschieden) und **stecken schon in Gesamt-G + kicktipp-pos** → die
„Bonus-Falle": NICHT nachrechnen, Verlauf MUSS authoritativ aus Kicktipp kommen (siehe §11).
`scrape.parse_bonus()` → `data/parsed/bonus.json` (+ Snapshot `data/history/bonus_<date>.json` für
„erstmals entschieden"-Datum). `build.build_bonus()` → `site/data/bonus.json` + B-Spalte.
Auflösungs-Schlagzeilen (`type:bonus_aufloesung`, primary=Frage-Label) tröpfeln passend in den Feed;
`headlines.ensure_bonus()` garantiert je Auszahlung eine Meldung. Alles additiv/graceful
(Bonus-Seite weg → keine B-Spalte, Tab versteckt). Team-Kürzel→Name: `scrape.TEAM_FULL`.

## 11. Platz-Historie MUSS authoritativ sein (Bonus-Falle!)

Verlauf NUR aus echtem Kicktipp `kicktipp-pos<N>` (+ tägliche Snapshots
`data/history/standings_<date>.json`). **NICHT** aus Punkte-Summen nachrechnen — das ignoriert
Kicktipp-Bonus + Tie-Break und ist falsch. Chart „Spieltage" = authoritative kicktipp-pos pro
Spieltag; „Tage" = ein Punkt pro Spielabend (Enden+Snapshots exakt, dazwischen geschätzt, Tooltip „geschätzt").

## 12. Stolperfallen-Checkliste

- [ ] **Frontend-JS/CSS geändert?** → `?v=N` in `index.html` bumpen, sonst Cache-Leichen.
- [ ] **Push deployt nicht** → danach „Run workflow" in Actions (oder auf 08:30 warten).
- [ ] **Determinismus** nicht brechen (kein `set`-Iterieren / untie-Sortieren über Tipper).
- [ ] **Push schlägt fehl** → Token abgelaufen (~22.07.) → regenerieren (§4).
- [ ] **„Texten bei jedem Lauf"** → Determinismus kaputt (§8) ODER `ctx`-Feld geändert (invalidiert Cache).
- [ ] **Tabellen-Daten** = generiert; nur `build.py` ändern, nicht `standings.json` von Hand.
- [ ] **Zeitzone**: Cron ist UTC → Sommer 08:30 / Winter 07:30 Ortszeit. Kein Bug, GitHub-Eigenheit.

## 13. Offene Punkte / mögliche nächste Schritte

- Chart-Modus „Tage" an die Schicht-Logik (Morgen-Datum) angleichen, falls Kevin Konsistenz auch dort will.
- Optional SSH statt PAT (kein Ablauf mehr).
- K.-o.-Phase mit echten Daten gegenprüfen (Spalten AF/VF/HF/FIN, Bonus berührt K.O. nicht).

---
*Ergänzende Dateien: `README.md` (Kurzüberblick), `DEPLOY.md` (Erst-Setup-Schritte). Memory-Pointer:
`project-tippspiel-chronik`.*
