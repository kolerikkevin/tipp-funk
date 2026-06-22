'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const TYPE_ICON = {
  perfekter_spieltag: '🎯', einsamer_volltreffer: '🔮', unwahrscheinlicher_treffer: '🎲',
  tagessieger: '🥇', tipp_vergessen: '😴', aufsteiger: '🚀', absteiger: '📉',
  pechvogel: '🌧️', fuehrungsserie: '👑', enges_rennen: '🔥', saison_aufsteiger: '📈',
  rote_laterne: '🪫', default: '⚽',
};

const state = { chart: null, history: null, standings: null, headlines: null, colors: {}, selected: {}, isolated: null };

// distinct, pleasant palette via golden-angle HSL
function palette(n) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const h = (i * 137.508) % 360;
    const s = 64 + (i % 3) * 8;
    const l = 42 + (i % 2) * 7;
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
    const cols = palette(history.series.length);
    history.series.forEach((s, i) => { state.colors[s.name] = cols[i]; state.selected[s.name] = true; });

    renderHeader();
    renderFeed();
    renderLegend();
    initChart();
    renderStandingsFull();
    setupTipps();
    wireUI();
  } catch (e) {
    $('#statusText').textContent = 'Fehler beim Laden';
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
  $('#statusText').textContent = `aktualisiert ${when}`;
  $('#footUpdate').textContent = `Stand: ${when}`;
  if (state.headlines.source) {
    const b = $('#srcBadge'); b.hidden = false;
    b.textContent = state.headlines.source === 'llm' ? '✨ KI-getextet' : 'Entwurf (Vorlage)';
  }
}

function movement(series) {
  // letzte vs. vorletzte Position
  const p = series.positions.filter(x => x != null);
  if (p.length < 2) return { cls: 'same', sym: '–' };
  const d = p[p.length - 2] - p[p.length - 1];
  if (d > 0) return { cls: 'up', sym: '▲' };
  if (d < 0) return { cls: 'down', sym: '▼' };
  return { cls: 'same', sym: '–' };
}

function renderTable() {
  const byName = Object.fromEntries(state.history.series.map(s => [s.name, s]));
  const rows = state.standings.tippers.filter(t => t.active !== false);
  $('#standings').innerHTML = rows.map((t, i) => {
    const s = byName[t.name];
    const mv = s ? movement(s) : { cls: 'same', sym: '–' };
    const cls = i < 3 ? ` top${i + 1}` : '';
    const dot = `<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${state.colors[t.name] || '#bbb'};margin-right:7px;vertical-align:-1px"></span>`;
    return `<tr data-name="${t.name}" class="row${cls}">
      <td class="pos">${i + 1}</td>
      <td class="mv ${mv.cls}">${mv.sym}</td>
      <td class="nm">${dot}${t.name}</td>
      <td class="pts">${t.total ?? ''}</td></tr>`;
  }).join('');
  $$('#standings tr').forEach(tr => tr.addEventListener('click', () => toggleIsolate(tr.dataset.name)));
}

const TYPE_LABEL = {
  perfekter_spieltag: 'VOLLTREFFER-TAG', einsamer_volltreffer: 'HELLSEHER', unwahrscheinlicher_treffer: 'SENSATIONS-TIPP',
  tagessieger: 'TAGESSIEGER', tipp_vergessen: 'VERPENNT', aufsteiger: 'AUFSTEIGER', absteiger: 'ABSTURZ',
  pechvogel: 'PECHVOGEL', fuehrungsserie: 'DAUER-CHEF', enges_rennen: 'KRIMI AN DER SPITZE',
  saison_aufsteiger: 'AUFHOLJAGD', rote_laterne: 'ROTE LATERNE', default: 'TIPP-TICKER',
};

function renderFeed() {
  const blocks = state.headlines.blocks || [];
  const latest = blocks[0];
  if (latest) { $('#newsDate').textContent = latest.label || latest.date || ''; $('#newsIssue').textContent = 'NR. ' + blocks.length; }
  if (state.headlines.source) {
    const b = $('#srcBadge'); b.hidden = false;
    b.textContent = state.headlines.source === 'llm' ? 'KI-REDAKTION' : 'ENTWURF';
  }
  if (!blocks.length) { $('#newsFeed').innerHTML = '<div class="quiet">Noch keine Schlagzeilen.</div>'; return; }

  $('#newsFeed').innerHTML = blocks.map((b, bi) => {
    const clips = (b.headlines || []).map((h, hi) => {
      const txt = typeof h === 'string' ? h : h.text;
      const dek = (typeof h === 'object' && h.erklaerung) || '';
      const type = (typeof h === 'object' && h.type) || 'default';
      const ic = TYPE_ICON[type] || TYPE_ICON.default;
      const kicker = TYPE_LABEL[type] || TYPE_LABEL.default;
      const lead = bi === 0 && hi === 0;
      return `<article class="clip${lead ? ' lead' : ''}">
        <div class="kicker"><span class="ic">${ic}</span>${kicker}</div>
        <p class="head">${txt}</p>
        ${dek ? `<p class="dek">${dek}</p>` : ''}</article>`;
    }).join('') || `<div class="quiet">Spielfreier Tag – die letzten Schlagzeilen bleiben stehen.</div>`;
    const tag = b.complete === false ? '<span class="badge">läuft noch</span>' : '';
    return `<section class="news-block">
      <div class="news-block-head"><span class="st">AUSGABE</span><span class="dt">${b.label || b.date || ''}</span>${tag}</div>
      <div class="clips">${clips}</div></section>`;
  }).join('');
}

function renderLegend() {
  $('#legendRow').innerHTML = state.history.series.map(s =>
    `<span class="leg" data-name="${s.name}"><span class="swatch" style="background:${state.colors[s.name]}"></span>${s.name}</span>`
  ).join('');
  $$('#legendRow .leg').forEach(el => {
    el.addEventListener('click', () => toggleSeries(el.dataset.name));
    // Über einen Namen fahren = nur dessen Verlauf hervorheben (stabil, kein Flackern)
    el.addEventListener('mouseenter', () => emphasizeSeries(el.dataset.name));
    el.addEventListener('mouseleave', () => emphasizeSeries(null));
  });
}

// Hebt eine Linie hervor, indem alle anderen ausgegraut werden (manuell, silent-sicher)
function emphasizeSeries(name) {
  const series = state.history.series.map(s => {
    const dim = name && s.name !== name;
    return {
      lineStyle: { width: s.name === name ? (s.rank === 1 ? 4.5 : 3.4) : (s.rank === 1 ? 3.4 : 2), opacity: dim ? 0.1 : 1 },
      endLabel: { opacity: dim ? 0.1 : 1 },
    };
  });
  state.chart.setOption({ series });
}

function seriesOption(s) {
  return {
    name: s.name, type: 'line', smooth: 0.25, connectNulls: true,
    symbol: 'circle', symbolSize: 6, sampling: 'none',
    data: s.positions, color: state.colors[s.name],
    silent: true,  // Linien reagieren nicht auf Maus-Hover -> kein Flackern; Hervorheben läuft über die Legende
    lineStyle: { width: s.rank === 1 ? 3.4 : 2, opacity: 1 },
    endLabel: { show: true, formatter: '{a}', fontSize: 11, color: 'inherit', distance: 6, opacity: 1 },
    labelLayout: { moveOverlap: 'shiftY', hideOverlap: false },
    emphasis: { disabled: true },
  };
}

function initChart() {
  const el = $('#chart');
  state.chart = echarts.init(el, null, { renderer: 'canvas' });
  const h = state.history;
  const opt = {
    animationDuration: 600,
    grid: { left: 44, right: 96, top: 16, bottom: 36 },
    tooltip: {
      trigger: 'item',
      formatter: (p) => `<b>${p.seriesName}</b><br/>${h.axis[p.dataIndex].label} · ${h.axis[p.dataIndex].date || ''}<br/>Platz <b>${p.value}</b>`,
    },
    legend: { show: false, data: h.series.map(s => s.name), selected: state.selected },
    xAxis: {
      type: 'category', boundaryGap: false,
      data: h.axis.map(a => a.label),
      axisLine: { lineStyle: { color: '#cfd6e0' } }, axisTick: { show: false },
      axisLabel: { color: getCSS('--ink-2') },
    },
    yAxis: {
      type: 'value', inverse: true, min: 1, max: h.max_rank || h.n_tippers, interval: 1, name: 'Platz',
      nameTextStyle: { color: getCSS('--ink-3'), align: 'right' },
      axisLabel: { color: getCSS('--ink-2') },
      splitLine: { lineStyle: { color: getCSS('--line') } },
    },
    series: h.series.map(seriesOption),
  };
  state.chart.setOption(opt);
  window.addEventListener('resize', () => state.chart.resize());
}

function getCSS(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim() || '#888'; }

function toggleSeries(name) {
  state.selected[name] = !state.selected[name];
  state.chart.dispatchAction({ type: state.selected[name] ? 'legendSelect' : 'legendUnSelect', name });
  const el = $(`#legendRow .leg[data-name="${cssEsc(name)}"]`);
  if (el) el.classList.toggle('off', !state.selected[name]);
}

function setVisibility(pred) {
  state.history.series.forEach(s => {
    const on = pred(s);
    state.selected[s.name] = on;
    state.chart.dispatchAction({ type: on ? 'legendSelect' : 'legendUnSelect', name: s.name });
    const el = $(`#legendRow .leg[data-name="${cssEsc(s.name)}"]`);
    if (el) el.classList.toggle('off', !on);
  });
}

function toggleIsolate(name) {
  state.isolated = state.isolated === name ? null : name;
  if (state.isolated) setVisibility(s => s.name === name);
  else setVisibility(() => true);
  $$('#standings tr').forEach(tr => tr.classList.toggle('active-row', state.isolated && tr.dataset.name === name));
  if (state.isolated) state.chart.dispatchAction({ type: 'highlight', seriesName: name });
}

function cssEsc(s) { return (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/"/g, '\\"'); }

function wireUI() {
  // Top-Navigation: jede Funktion direkt erreichbar
  $$('.view-btn').forEach(b => b.addEventListener('click', () => setView(b.dataset.view)));
  // Chart-Quickbuttons
  $$('[data-chart]').forEach(b => b.addEventListener('click', () => {
    const m = b.dataset.chart;
    if (m === 'all') setVisibility(() => true);
    else if (m === 'none') setVisibility(() => false);
    else if (m === 'top5') setVisibility(s => s.rank <= 5);
  }));
  // Legenden-Suche
  $('#chartSearch').addEventListener('input', e => {
    const q = e.target.value.toLowerCase();
    $$('#legendRow .leg').forEach(el => { el.style.display = el.dataset.name.toLowerCase().includes(q) ? '' : 'none'; });
  });
  // Tipp-Historie Navigation
  $('#tippSel').addEventListener('change', e => renderTippMatrix(+e.target.value));
  $('#tippPrev').addEventListener('click', () => stepTipp(+1));  // +1 = älterer Spieltag (Liste absteigend)
  $('#tippNext').addEventListener('click', () => stepTipp(-1));

  setView('feed');  // Startseite = Schlagzeilen
}

function setView(view) {
  $$('.view-btn').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  $('#view-feed').hidden = view !== 'feed';
  $('#view-chart').hidden = view !== 'chart';
  $('#view-tabelle').hidden = view !== 'tabelle';
  $('#view-tipps').hidden = view !== 'tipps';
  if (view === 'tipps' && state.tippCurrent != null) renderTippMatrix(state.tippCurrent);
  window.scrollTo({ top: 0 });
  if (view === 'chart') setTimeout(() => state.chart && state.chart.resize(), 60);
}

// ---------- Tabelle (voller Stand) ----------
function renderStandingsFull() {
  const sp = state.standings.spieltage || [];   // echte Kicktipp-Spieltage
  const byName = Object.fromEntries(state.history.series.map(s => [s.name, s]));
  const rows = state.standings.tippers.filter(t => t.active !== false);
  const head = `<thead><tr><th class="pos">#</th><th class="mv"></th><th class="nm">Name</th>` +
    sp.map(n => `<th class="md" title="Spieltag ${n}">${n}</th>`).join('') +
    `<th class="tot">Σ</th></tr></thead>`;
  const body = rows.map((t, i) => {
    const s = byName[t.name];
    const mv = s ? movement(s) : { cls: 'same', sym: '–' };
    const cls = i < 3 ? `top${i + 1}` : '';
    const mds = sp.map(n => {
      const p = (t.matchday_points || {})[n];
      return `<td class="md">${p == null ? '·' : p}</td>`;
    }).join('');
    const dot = `<span class="seriesdot" style="background:${state.colors[t.name] || '#999'}"></span>`;
    return `<tr class="${cls}"><td class="pos">${i + 1}</td><td class="mv ${mv.cls}">${mv.sym}</td>` +
      `<td class="nm">${dot}${t.name}</td>${mds}<td class="tot">${t.total ?? ''}</td></tr>`;
  }).join('');
  $('#standingsFull').innerHTML = head + '<tbody>' + body + '</tbody>';
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

init();
