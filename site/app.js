'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const TYPE_ICON = {
  perfekter_spieltag: '🎯', einsamer_volltreffer: '🔮', unwahrscheinlicher_treffer: '🎲',
  tagessieger: '🥇', spieltag_fazit: '🏁', tipp_vergessen: '😴', aufsteiger: '🚀', absteiger: '📉',
  pechvogel: '🌧️', mittelfeld_dauergast: '🛋️', fuehrungsserie: '👑', enges_rennen: '🔥', saison_aufsteiger: '📈',
  rote_laterne: '🪫', bonus_aufloesung: '🎁', default: '⚽',
};

const state = { chart: null, history: null, standings: null, headlines: null, tipps: null, bonus: null,
                colors: {}, selected: new Set(), chartView: 'tage', tableView: 'spieltage' };

// distinct, pleasant palette via golden-angle HSL
function palette(n) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const h = (i * 137.508) % 360;
    const s = 70 + (i % 3) * 7;
    const l = 38 + (i % 2) * 5;
    out.push(`hsl(${h.toFixed(0)} ${s}% ${l}%)`);
  }
  return out;
}

async function loadJSON(p) {
  const r = await fetch(`${p}?t=${Date.now()}`);
  if (!r.ok) throw new Error(`${p}: ${r.status}`);
  return r.json();
}

async function init() {
  try {
    const [history, standings, headlines, tipps] = await Promise.all([
      loadJSON('data/history.json'), loadJSON('data/standings.json'),
      loadJSON('data/headlines.json'), loadJSON('data/tipps.json'),
    ]);
    state.history = history; state.standings = standings; state.headlines = headlines; state.tipps = tipps;
    state.bonus = await loadJSON('data/bonus.json').catch(() => null);  // optional, bricht nichts
    const cols = palette(history.series.length);
    history.series.forEach((s, i) => { state.colors[s.name] = cols[i]; });

    renderHeader();
    renderFeed();
    initChart();
    renderStandingsFull();
    setupTipps();
    renderBonus();
    wireUI();
  } catch (e) {
    console.error(e);
  }
}

function renderHeader() {
  const t = state.standings.tippers.filter(x => x.active !== false);
  const leader = t[0];
  if (leader) {
    $('#leaderChip').hidden = false;
    $('#leaderName').textContent = leader.name;
    $('#leaderSub').textContent = `${leader.total} Punkte · Platz 1`;
  }
  const when = (state.standings.scraped_at || '').replace('T', ' ').slice(0, 16);
  $('#footUpdate').textContent = `Stand: ${when}`;
}

function movement(series) {
  // Trend des letzten aktiven Tages: heutigen Snapshot (kein Spiel = gleich wie gestern)
  // überspringen, dann den letzten Spieltag-Tag mit dem davor vergleichen.
  const p = (series.positions || []).filter(x => x != null);
  if (p.length < 2) return { cls: 'same', sym: '–' };
  let i = p.length - 1;
  if (p[i] === p[i - 1]) i--;
  if (i < 1) return { cls: 'same', sym: '–' };
  const cur = p[i], prev = p[i - 1];
  if (cur === prev) return { cls: 'same', sym: '–' };
  return cur < prev ? { cls: 'up', sym: '▲' } : { cls: 'down', sym: '▼' };
}

const TYPE_LABEL = {
  perfekter_spieltag: 'VOLLTREFFER-TAG', einsamer_volltreffer: 'HELLSEHER', unwahrscheinlicher_treffer: 'SENSATIONS-TIPP',
  tagessieger: 'TAGESSIEGER', spieltag_fazit: 'SPIELTAG-FAZIT', tipp_vergessen: 'VERPENNT', aufsteiger: 'AUFSTEIGER', absteiger: 'ABSTURZ',
  pechvogel: 'PECHVOGEL', mittelfeld_dauergast: 'DAUERGAST MITTELFELD', fuehrungsserie: 'DAUER-CHEF', enges_rennen: 'KRIMI AN DER SPITZE',
  saison_aufsteiger: 'AUFHOLJAGD', rote_laterne: 'ROTE LATERNE', bonus_aufloesung: 'BONUS-AUFLÖSUNG', default: 'TIPP-TICKER',
};

const blockHasBonus = b => (b.headlines || []).some(h => typeof h === 'object' && h.type === 'bonus_aufloesung');

function editionHTML(b, bi, ii) {
  const clips = (b.headlines || []).map((h, hi) => {
    const txt = typeof h === 'string' ? h : h.text;
    const dek = (typeof h === 'object' && h.erklaerung) || '';
    const type = (typeof h === 'object' && h.type) || 'default';
    const ic = TYPE_ICON[type] || TYPE_ICON.default;
    const kicker = TYPE_LABEL[type] || TYPE_LABEL.default;
    const lead = bi === 0 && hi === 0;
    return `<article class="clip${lead ? ' lead' : ''}">
      <div class="kicker"><span class="ic">${ic}</span>${kicker}</div>
      <p class="head">${txt}</p>${dek ? `<p class="dek">${dek}</p>` : ''}</article>`;
  }).join('') || `<div class="quiet">Spielfreier Tag – die letzten Schlagzeilen bleiben stehen.</div>`;
  // pro Spieltag-Gruppe nur die neueste Ausgabe offen (ii === 0); ältere zu –
  // Ausgaben mit Bonus-Auflösung bleiben immer offen
  const collapsed = (ii > 0 && !blockHasBonus(b)) ? ' collapsed' : '';
  const time = b.published_at ? `<span class="time">online ${b.published_at.slice(11, 16)} Uhr</span>` : '';
  return `<section class="news-block${collapsed}">
    <div class="news-block-head">
      <span class="caret">▾</span><span class="st">${b.label || b.date || ''}</span>${time}
    </div>
    <div class="clips">${clips}</div></section>`;
}

function renderFeed() {
  const blocks = state.headlines.blocks || [];
  const spMap = Object.fromEntries((state.headlines.spieltage || []).map(s => [s.key, s]));
  if (!blocks.length) { $('#newsFeed').innerHTML = '<div class="quiet">Noch keine Schlagzeilen.</div>'; return; }

  // Ausgaben zu Spieltag-Gruppen bündeln (Reihenfolge = neueste zuerst)
  const groups = [];
  blocks.forEach((b, bi) => {
    let g = groups[groups.length - 1];
    if (!g || g.key !== b.group_key) { g = { key: b.group_key, label: b.group, gruppenphase: b.gruppenphase, items: [] }; groups.push(g); }
    g.items.push({ b, bi });
  });

  $('#newsFeed').innerHTML = groups.map((g, gi) => {
    const sp = spMap[g.key] || {};
    const fazit = sp.fazit_headline
      ? `<article class="clip fazit"><div class="kicker"><span class="ic">🏁</span>SPIELTAG-FAZIT</div>
          <p class="head">${sp.fazit_headline.text}</p>${sp.fazit_headline.erklaerung ? `<p class="dek">${sp.fazit_headline.erklaerung}</p>` : ''}</article>`
      : '';
    const body = fazit + g.items.map(({ b, bi }, ii) => editionHTML(b, bi, ii)).join('');
    const sub = g.gruppenphase ? '<span class="sp-sub">Gruppenphase</span>' : '';
    // neuester Spieltag offen; ältere zu – außer es steckt eine Bonus-Auflösung drin
    const groupHasBonus = g.items.some(({ b }) => blockHasBonus(b));
    const open = (gi === 0 || groupHasBonus) ? '' : ' collapsed';
    return `<section class="spieltag-group${open}">
      <div class="spieltag-head"><span class="sp-caret">▾</span><span class="sp-badge">${g.label || ''}</span>${sub}</div>
      <div class="spieltag-body">${body}</div>
    </section>`;
  }).join('');

  $$('#newsFeed .spieltag-head').forEach(h =>
    h.addEventListener('click', () => h.parentElement.classList.toggle('collapsed')));
  $$('#newsFeed .news-block-head').forEach(h =>
    h.addEventListener('click', () => h.parentElement.classList.toggle('collapsed')));
}

// ---------- Platz-Verlauf (Bump-Chart) ----------
function getCSS(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim() || '#888'; }

function currentSeries() {
  return state.chartView === 'spieltage' ? state.history.spieltage : state.history;
}

function seriesOption(s) {
  const bright = state.selected.size === 0 || state.selected.has(s.name);
  return {
    name: s.name, type: 'line', smooth: 0.25, connectNulls: true,
    symbol: 'circle', symbolSize: 7, data: s.positions, color: state.colors[s.name],
    triggerLineEvent: true,  // Klick/Hover auch direkt auf der LINIE (nicht nur auf Punkten/Namen)
    lineStyle: { width: s.rank === 1 ? 3.4 : 2, opacity: bright ? 1 : 0.12 },
    endLabel: { show: true, formatter: '{a}', fontSize: 11, color: 'inherit', distance: 6,
                opacity: bright ? 1 : 0.12, triggerEvent: true },
    labelLayout: { moveOverlap: 'shiftY', hideOverlap: false },
    emphasis: { disabled: true }, z: bright ? 3 : 1,
  };
}

// aktuellen Auswahlzustand (oder voll) auf alle Linien anwenden
function renderChart() {
  const v = currentSeries();
  state.chart.setOption({ xAxis: { data: v.axis.map(a => a.label) }, series: v.series.map(seriesOption) });
}

// transientes Hervorheben einer Linie (Hover) – Rest grau, ohne die Auswahl zu verändern
function highlight(name) {
  const v = currentSeries();
  state.chart.setOption({ series: v.series.map(s => {
    const on = s.name === name;
    return { lineStyle: { width: on ? (s.rank === 1 ? 4.6 : 3.4) : (s.rank === 1 ? 3.4 : 2), opacity: on ? 1 : 0.08 },
             endLabel: { opacity: on ? 1 : 0.08 }, z: on ? 6 : 1 };
  }) });
}

function initChart() {
  state.chart = echarts.init($('#chart'), null, { renderer: 'canvas' });
  const v = currentSeries();
  state.chart.setOption({
    animationDuration: 500,
    grid: { left: 42, right: 112, top: 16, bottom: 34 },
    tooltip: {
      trigger: 'item', confine: true,
      formatter: (p) => {
        const a = currentSeries().axis[p.dataIndex] || {};
        const tag = state.chartView === 'tage' ? (a.official ? ' · offiziell' : ' · geschätzt') : '';
        return `<b>${p.seriesName}</b><br/>${a.date || a.label || ''}${tag}<br/>Platz <b>${p.value}</b>`;
      },
    },
    xAxis: {
      type: 'category', boundaryGap: false, data: v.axis.map(a => a.label),
      axisLine: { lineStyle: { color: getCSS('--ink-3') } }, axisTick: { show: false },
      axisLabel: { color: getCSS('--ink-2'), fontFamily: 'VT323, monospace', fontSize: 15 },
    },
    yAxis: {
      type: 'value', inverse: true, min: 1, max: state.history.max_rank, interval: 1, name: 'Platz',
      nameTextStyle: { color: getCSS('--ink-3'), align: 'right' },
      axisLabel: { color: getCSS('--ink-2') }, splitLine: { lineStyle: { color: getCSS('--line') } },
    },
    series: v.series.map(seriesOption),
  });
  // Hover hebt hervor; Klick wählt aus (mehrere möglich) – auf Linie wie auf Namen
  state.chart.on('mouseover', (p) => { if (p.seriesName) highlight(p.seriesName); });
  state.chart.on('mouseout', () => renderChart());
  state.chart.on('click', (p) => {
    if (!p.seriesName) return;
    state.selected.has(p.seriesName) ? state.selected.delete(p.seriesName) : state.selected.add(p.seriesName);
    renderChart();
  });
  window.addEventListener('resize', () => state.chart.resize());
}

function wireUI() {
  // Top-Navigation: jede Funktion direkt erreichbar
  $$('.view-btn').forEach(b => b.addEventListener('click', () => setView(b.dataset.view)));
  // Chart: Tage / Spieltage umschalten
  $$('#chartView button').forEach(b => b.addEventListener('click', () => {
    state.chartView = b.dataset.cv;
    $$('#chartView button').forEach(x => x.classList.toggle('active', x === b));
    renderChart();
  }));
  // Chart-Quickauswahl
  $$('[data-chart]').forEach(b => b.addEventListener('click', () => {
    if (b.dataset.chart === 'all') state.selected.clear();
    else if (b.dataset.chart === 'top5') state.selected = new Set(state.history.series.filter(s => s.rank <= 5).map(s => s.name));
    renderChart();
  }));
  // Tipp-Historie Navigation
  $('#tippSel').addEventListener('change', e => renderTippMatrix(+e.target.value));
  $('#tippPrev').addEventListener('click', () => stepTipp(+1));  // +1 = älterer Spieltag (Liste absteigend)
  $('#tippNext').addEventListener('click', () => stepTipp(-1));
  // Tabelle: Spieltage / Tage umschalten
  $$('#tableView button').forEach(b => b.addEventListener('click', () => {
    state.tableView = b.dataset.tv;
    $$('#tableView button').forEach(x => x.classList.toggle('active', x === b));
    renderStandingsFull();
  }));

  setView('feed');  // Startseite = Schlagzeilen
}

function setView(view) {
  $$('.view-btn').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  $('#view-feed').hidden = view !== 'feed';
  $('#view-chart').hidden = view !== 'chart';
  $('#view-tabelle').hidden = view !== 'tabelle';
  $('#view-tipps').hidden = view !== 'tipps';
  $('#view-bonus').hidden = view !== 'bonus';
  if (view === 'tipps' && state.tippCurrent != null) renderTippMatrix(state.tippCurrent);
  window.scrollTo({ top: 0 });
  if (view === 'chart') setTimeout(() => state.chart && state.chart.resize(), 60);
}

// ---------- Tabelle (voller Stand) ----------
function renderStandingsFull() {
  // Umschaltbar: offizielle WM-Spieltage (Standard) oder pro Kalendertag
  const mode = state.tableView === 'tage' ? 'tage' : 'spieltage';
  const ptsKey = mode === 'tage' ? 'tag_points' : 'matchday_points';
  const sp = (mode === 'tage' ? state.standings.tage : state.standings.spieltage) || [];
  const byName = Object.fromEntries(state.history.series.map(s => [s.name, s]));
  const rows = state.standings.tippers.filter(t => t.active !== false);
  const hasBonus = rows.some(t => t.bonus != null);
  // Spalten = {key,kurz,lang}; altes Zahlenformat abfangen
  const cols = sp.map(u => (typeof u === 'object' && u) ? u : { key: u, kurz: String(u), lang: `Spieltag ${u}` });
  const head = `<thead><tr><th class="pos">#</th><th class="mv"></th><th class="nm">Name</th>` +
    cols.map(u => `<th class="md" title="${u.lang}">${u.kurz}</th>`).join('') +
    (hasBonus ? `<th class="bn" title="Bonuspunkte bisher">B</th>` : '') +
    `<th class="tot">Σ</th></tr></thead>`;
  const body = rows.map((t, i) => {
    const s = byName[t.name];
    const mv = s ? movement(s) : { cls: 'same', sym: '–' };
    const cls = i < 3 ? `top${i + 1}` : '';
    const mds = cols.map(u => {
      const p = (t[ptsKey] || {})[u.key];
      return `<td class="md">${p == null ? '·' : p}</td>`;
    }).join('');
    const bn = hasBonus ? `<td class="bn">${t.bonus ? t.bonus : '·'}</td>` : '';
    const dot = `<span class="seriesdot" style="background:${state.colors[t.name] || '#999'}"></span>`;
    return `<tr class="${cls}"><td class="pos">${i + 1}</td><td class="mv ${mv.cls}">${mv.sym}</td>` +
      `<td class="nm">${dot}${t.name}</td>${mds}${bn}<td class="tot">${t.total ?? ''}</td></tr>`;
  }).join('');
  $('#standingsFull').innerHTML = head + '<tbody>' + body + '</tbody>';
  const hint = $('#tabHint');
  if (hint) hint.innerHTML = mode === 'tage'
    ? 'Punkte je <b>Ausgabe-Tag</b> – Abend, Nacht und Morgen zählen als <b>eine Schicht</b> (gleicher Tag wie im News-Feed) · Gesamt rechts.'
    : 'Punkte je <b>WM-Spieltag</b> · Gesamt rechts · Bewegung = Veränderung zum Vorspieltag.';
  $('#tabUpdate').textContent = 'STAND ' + (state.standings.scraped_at || '').replace('T', ' ').slice(0, 16);
}

// ---------- Tipp-Historie (Matrix) ----------
function setupTipps() {
  const mds = (state.tipps.matchdays || []).map(m => m.matchday).sort((a, b) => b - a);
  state.tippMds = mds;
  $('#tippSel').innerHTML = mds.map(m => `<option value="${m}">Spieltag ${m}</option>`).join('');
  state.tippCurrent = mds[0] ?? null;
}

function stepTipp(dir) {
  const mds = state.tippMds || [];
  const i = mds.indexOf(state.tippCurrent);
  const ni = i + dir;
  if (ni < 0 || ni >= mds.length) return;
  renderTippMatrix(mds[ni]);
}

function abbr(s) { return s.length > 11 ? s.slice(0, 10) + '.' : s; }

function renderTippMatrix(md) {
  md = +md;
  state.tippCurrent = md;
  $('#tippSel').value = md;
  const data = (state.tipps.matchdays || []).find(m => m.matchday === md);
  if (!data) { $('#tippMatrix').innerHTML = ''; return; }
  const gh = data.games.map(g =>
    `<th class="game"><span class="g-teams">${abbr(g.home)}<br>${abbr(g.away)}</span><span class="g-res">${g.result || '–'}</span></th>`
  ).join('');
  const head = `<thead><tr><th class="pos">#</th><th class="nm">Name</th>${gh}<th class="pts">Pkt</th></tr></thead>`;
  const body = data.rows.map((r, i) => {
    const cells = r.picks.map(p => {
      if (!p.tip) return `<td class="tip none">–</td>`;
      const cl = p.points >= 4 ? 'exact' : (p.points > 0 ? 'hit' : 'miss');
      return `<td class="tip ${cl}">${p.tip}${p.points ? `<sup>${p.points}</sup>` : ''}</td>`;
    }).join('');
    const cls = i < 3 ? `top${i + 1}` : '';
    return `<tr class="${cls}"><td class="pos">${r.position ?? i + 1}</td><td class="nm">${r.name}</td>${cells}` +
      `<td class="pts">${r.spieltag_points ?? ''}</td></tr>`;
  }).join('');
  $('#tippMatrix').innerHTML = head + '<tbody>' + body + '</tbody>';
  $('#tippMeta').textContent = `${data.games.length} Spiele · ${data.rows.length} Tipper · ${data.date}` +
    (data.complete ? '' : ' · läuft noch');
}

// ---------- Bonus (Langfrist-Tipps) ----------
function renderBonus() {
  const navBtn = $('.view-btn[data-view="bonus"]');
  const b = state.bonus;
  if (!b || !b.questions) { if (navBtn) navBtn.hidden = true; return; }

  // Schon entschieden
  const decided = b.questions.filter(q => q.decided);
  $('#bonusDecided').innerHTML = decided.length ? decided.map(q => {
    const miss = q.missed || [], sc = q.scorers || [];
    const missTxt = miss.length === 0 ? '' : (miss.length <= 4 ? 'verzockt: ' + miss.join(', ') : `${miss.length} daneben`);
    return `<div class="bdec">
      <div class="bdec-q">${q.label}</div>
      <div class="bdec-r">${q.result_full || q.result}</div>
      <div class="bdec-s"><b>${sc.length}</b> kassieren · <span class="leer">${miss.length} leer</span></div>
      <div class="bdec-miss">${miss.length ? missTxt : '🎯 alle richtig'}</div>
    </div>`;
  }).join('') : '<div class="quiet">Noch keine Frage entschieden – kommt mit den ersten Gruppen-Abschlüssen.</div>';

  // Verteilungen
  const dists = [
    { t: 'Weltmeister', d: b.highlights.wm },
    { t: 'Torschützenkönig-Nation', d: b.highlights.tor },
    { t: 'Halbfinal-Stimmen (4 je Tipper)', d: b.highlights.hf },
  ];
  $('#bonusDists').innerHTML = dists.map(({ t, d }) => distCard(t, d)).join('');

  renderBonusMatrix();
}

function distCard(title, dist) {
  if (!dist || !dist.length) return '';
  const max = Math.max(...dist.map(d => d.count));
  const bars = dist.map(d => {
    const w = Math.max(6, Math.round(100 * d.count / max));
    return `<div class="bar-row${d.is_result ? ' hit' : ''}">
      <span class="bar-lab">${d.full || d.abbr}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${w}%"></span></span>
      <span class="bar-n">${d.count}</span></div>`;
  }).join('');
  return `<div class="dist-card"><div class="dist-t">${title}</div>${bars}</div>`;
}

function renderBonusMatrix() {
  const b = state.bonus;
  const qs = b.questions;
  const gh = qs.map(q => {
    const res = q.decided ? `<span class="g-res">${q.result}</span>` : '';
    return `<th class="game" title="${(q.frage || q.label || '').replace(/"/g, '')}"><span class="g-teams">${q.kurz}</span>${res}</th>`;
  }).join('');
  const head = `<thead><tr><th class="pos">#</th><th class="nm">Name</th>${gh}<th class="pts">B</th></tr></thead>`;
  const body = b.tippers.map((t, i) => {
    const byslot = Object.fromEntries(t.picks.map(p => [p.slot, p]));
    const cells = qs.map(q => {
      const p = byslot[q.slot];
      if (!p || !p.abbr) return `<td class="tip none">–</td>`;
      const cl = p.correct ? 'exact' : (q.decided ? 'missx' : 'open');
      return `<td class="tip ${cl}">${p.abbr}${p.correct ? '<sup>4</sup>' : ''}</td>`;
    }).join('');
    const cls = i < 3 ? `top${i + 1}` : '';
    return `<tr class="${cls}"><td class="pos">${t.position ?? i + 1}</td><td class="nm">${t.name}</td>${cells}` +
      `<td class="pts">${t.bonus_points || 0}</td></tr>`;
  }).join('');
  $('#bonusMatrix').innerHTML = head + '<tbody>' + body + '</tbody>';
}

init();
