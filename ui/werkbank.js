// ui/werkbank.js — die Konsole (docs/werkbank-spec.md)
//
// Warum kein Rahmenwerk: fuenf Bereiche, eine Tabelle, eine Detailspalte.
// Der Zustand ist ein Objekt. Ein Bauschritt zwischen "geaendert" und
// "sichtbar" waere reines Risiko
// (docs/entscheidungen/2026-08-07-ui-stack-werkbank.md).
//
// Die eine Regel, die diese Fassung von der vom Vormittag trennt:
// **es wird nichts vollstaendig geladen.** Der Katalog haelt 5.594
// Datensaetze (gemessen). Filtern, Sortieren und Blaettern passieren
// serverseitig (`ui/console_api.py`); der Browser bekommt eine Seite und
// die Gesamtzahl -- daraus schreibt er "N von M". Eine Liste, die alles
// holt, ist bei acht Zeilen huebsch und bei 5.594 unbenutzbar.
//
// Zweite Regel: keine Zahl wird erfunden. "Nicht gemessen" bekommt ein
// WORT und eine eigene Form, nie eine Null und nie ein leeres Feld.

const API_HEADERS = { 'X-Probate': '1' };
const PAGE = 50;

// --- Helfer -------------------------------------------------------------

function el(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text != null) n.textContent = text;
  return n;
}

function stateHelpNode(state) {
  const tpl = document.getElementById('state-help');
  const src = tpl && tpl.content.querySelector(`[data-state-help="${state}"]`);
  return src ? src.cloneNode(true) : null;
}

function plural(n, one, many) { return `${n} ${n === 1 ? one : many}`; }

function num(n) { return (n == null ? '—' : Number(n).toLocaleString()); }

// Die Gruende kommen woertlich aus probate/ledger.py und probate/judge.py
// und sind dort DEUTSCH -- beide Dateien gehoeren anderen Bahnen. Diese
// Tabelle uebersetzt nur die ANZEIGE; der Originaltext bleibt im
// title-Attribut, damit sich die Oberflaeche weiter gegen den Quelltext
// halten laesst.
const REASON_EN = {
  'keine Nutzungs-Zeitfenster im Katalog': 'the catalog holds no usage window for this table',
  'abdeckung und zeitachse widersprechen sich': 'coverage and timeline contradict each other',
  'verkehr gemessen, aber query-quelle leer': 'traffic measured, but the query log came back empty',
  'kein Zitat geliefert': 'the model supplied no quote',
  'Zitat zu kurz, kein Beleg': 'the quote was too short to be evidence',
  'Zitat nicht im gelesenen Kontext': 'the quote does not appear in the text we read',
  'Zitat nur aus dem Seed-Hinweis, kein Beleg':
    'the quote came only from the seeding notice, not from the catalog entry',
  'important-Feld nicht boolesch': 'the model’s “important” field was not a real boolean',
  'keine Begruendung geliefert': 'the model gave no reason',
  'kein lesbarer Kontext vorhanden': 'there was no readable catalog text to quote from',
  'Antwort war kein JSON': 'the model’s answer was not valid JSON',
  'kein Transport konfiguriert': 'no model was configured for this run',
};

function humanReason(text) {
  if (!text) return '';
  if (REASON_EN[text]) return REASON_EN[text];
  const m = /^Transport gescheitert \(([^)]*)\)/.exec(text);
  return m ? `the model call failed (${m[1]})` : text;
}

function agoPhrase(days) {
  if (days == null) return 'never';
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  return `${days} days ago`;
}

function dayStamp(ms) {
  return ms ? new Date(ms).toLocaleDateString(undefined, { day: 'numeric', month: 'long' }) : null;
}

async function getJson(url) {
  const r = await fetch(url, { cache: 'no-store', headers: API_HEADERS });
  if (!r.ok) throw new Error(`${url} → HTTP ${r.status}`);
  return r.json();
}

// --- Zustand der Oberflaeche -------------------------------------------

const state = {
  mode: 'recording',
  info: {},
  ledger: null,
  judge: null,
  view: 'overview',
  selected: null,
  catalogTotal: null,
  filters: {
    states: new Set(),
    platform: '', database: '', table: '', q: '',
    judged: false, abstained: false,
    sort: 'state', dir: 'asc', start: 0,
  },
  catalog: { q: '', start: 0, total: 0 },
};

const STATE_WORD = { confirmed: 'CONFIRMED', dead: 'DEAD', missing: 'MISSING', unknown: 'NOT JUDGED' };
const STATE_ORDER = ['dead', 'missing', 'unknown', 'confirmed'];

// --- Datenzugang --------------------------------------------------------

async function fetchModeInfo() {
  // Kein Server = Aufzeichnung. Der sichere Rueckfall, nie stillschweigend live.
  try {
    const body = await getJson('/api/mode');
    return body.mode === 'live' ? body : { mode: 'recording' };
  } catch {
    return { mode: 'recording' };
  }
}

async function loadLedger(mode) {
  return mode === 'live'
    ? getJson('/api/ledger')
    : (await fetch('./recorded/ledger.json', { cache: 'no-store' })).json();
}

async function loadJudgements(mode) {
  // Aufzeichnung: dieselbe Form wie live, aus `harness/record_replay.py`.
  // Fehlt die Datei, ist das kein Fehler -- es heisst "dieser Aufzeichnung
  // liegt kein Modell-Lauf bei".
  try {
    if (mode === 'live') return await getJson('/api/judgements');
    const r = await fetch('./recorded/replay.json', { cache: 'no-store' });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

function judgementFor(edgeKey) {
  return ((state.judge && state.judge.judgements) || []).find((j) => j.edge === edgeKey) || null;
}

// --- Bereich 1: Uebersicht ---------------------------------------------

function renderOverview() {
  const l = state.ledger;
  const host = document.getElementById('run-verdict');
  host.innerHTML = '';

  if (!l || !(l.edges || []).length) {
    host.textContent = l ? 'The check ran and found no connection to judge.' : 'No check has run yet.';
  } else {
    const total = l.edges.length;
    const deadDays = l.edges.filter((e) => e.state === 'dead')
      .map((e) => (e.timeline || {}).dead_since_days).filter((d) => d != null);
    const worst = deadDays.length ? Math.max(...deadDays) : null;

    host.append(el('span', 'kpis__lead', `${plural(total, 'connection', 'connections')} checked`));
    const segs = [
      ['confirmed', l.edges_confirmed, 'confirmed'],
      ['dead', l.edges_dead, worst != null ? `dead for ${plural(worst, 'day', 'days')}` : 'dead'],
      ['missing', l.edges_missing, 'running undeclared'],
      ['unknown', l.edges_unknown, 'we cannot judge — no usage data'],
    ];
    for (const [s, count, label] of segs) {
      if (!count) continue;
      const seg = el('span', 'kpis__seg');
      seg.append(el('span', `chip chip--${s}`, STATE_WORD[s]),
                 el('span', 'kpis__count', String(count)),
                 el('span', 'kpis__label', label),
                 // Jede Zahl MIT Nenner -- eine nackte Kennzahl ist nicht
                 // interpretierbar (Spec).
                 el('span', 'kpis__denominator', `of ${total}`));
      host.append(seg);
    }
  }

  // Abdeckung als STATISTIK (was haben wir angesehen) ...
  const cov = document.getElementById('coverage-banner');
  if (!l) {
    cov.textContent = 'not measured yet';
  } else {
    const focusCount = (l.focuses || [l.focus]).filter(Boolean).length;
    const measured = (l.edges || []).filter((e) => (e.coverage || {}).buckets_seen > 0).length;
    cov.textContent = `${measured} of ${(l.edges || []).length} connections had a usage window`
      + ` — ${plural(l.coverage_buckets_seen || 0, 'window', 'windows')}`
      + ` over ${plural(l.coverage_days_span || 0, 'day', 'days')}`
      + `, ${plural(focusCount, 'source table', 'source tables')}`
      + `, ${plural(l.api_calls || 0, 'API call', 'API calls')}`;
  }

  // ... und die WARNUNG getrennt davon (wo unser Blick nicht hinreicht).
  const warn = document.getElementById('coverage-warning');
  const blind = l ? (l.edges_unknown || 0) : 0;
  if (!l || (!blind && !l.coverage_thin)) {
    warn.hidden = true;
  } else {
    warn.hidden = false;
    warn.innerHTML = '';
    warn.append(el('span', 'chip chip--unknown', 'NOT JUDGED'),
      el('span', null, blind
        ? `${plural(blind, 'connection has', 'connections have')} no usage data at all.`
          + ' We report them as not judged instead of guessing — that is the difference'
          + ' between a measurement and an opinion.'
        : 'Coverage is thin: some tables carry fewer usage windows than the observation window'
          + ' is wide. Every verdict below rests on what was measured, not on assumption.'));
  }

  // Enthaltungsquote -- ein ausgewiesenes Ergebnis, kein Makel.
  const abst = document.getElementById('abstention-rate');
  const j = state.judge;
  if (!j || !j.calls) {
    abst.textContent = j && j.running ? 'model is running…' : 'not measured yet';
  } else {
    const outs = (j.judgements || []).filter((x) => !x.used_model).length;
    const cost = typeof j.cost_usd === 'number' ? `$${j.cost_usd.toFixed(4)}` : 'cost not recorded';
    abst.textContent = `${outs} of ${j.calls} model calls abstained · ${j.seconds}s · ${cost}`;
  }

  const last = document.getElementById('last-run');
  last.textContent = l
    ? `${new Date(l.generated_at_ms).toLocaleString()} · `
      + `${plural((l.edges || []).length, 'connection', 'connections')} · `
      + `${l.recording ? 'recorded run' : 'live run'}`
    : 'never';

  document.getElementById('status-run').textContent = l
    ? `last run ${new Date(l.generated_at_ms).toLocaleTimeString()}`
    : 'no run yet';
  document.getElementById('status-coverage').textContent = l
    ? `coverage ${l.coverage_buckets_seen || 0} windows / ${l.coverage_days_span || 0} days`
    : 'coverage: not measured';
  document.getElementById('status-abstention').textContent = (j && j.calls)
    ? `abstention ${(j.judgements || []).filter((x) => !x.used_model).length}/${j.calls}`
    : 'abstention: not measured';

  const note = document.getElementById('seeded-note');
  if (note) {
    note.textContent = (l && l.seeded)
      ? (l.seeded_statement || state.info.seeded_statement
         || 'Seeded demonstration data — not real warehouse usage.')
      : '';
  }
}

// --- Bereich 2: Verbindungen -------------------------------------------

function filterQuery() {
  const f = state.filters;
  const p = new URLSearchParams();
  if (f.states.size) p.set('state', [...f.states].join(','));
  if (f.platform) p.set('platform', f.platform);
  if (f.database) p.set('database', f.database);
  if (f.table) p.set('table', f.table);
  if (f.q) p.set('q', f.q);
  if (f.judged) p.set('judged', '1');
  if (f.abstained) p.set('abstained', '1');
  p.set('sort', f.sort);
  p.set('dir', f.dir);
  p.set('start', String(f.start));
  p.set('count', String(PAGE));
  return p.toString();
}

function cellRef(ref) {
  const cell = el('div', 'cellref');
  // Die Herkunft steht KLEIN UEBER dem Namen -- ein Tabellenname ohne
  // seinen Ort ist bei 5.594 Datensaetzen wertlos.
  const where = [ref.platform, ref.database, ref.schema].filter(Boolean).join(' · ');
  cell.append(el('span', 'cellref__where', where || 'location unknown'));
  const name = el('span', 'cellref__name', ref.table);
  name.title = ref.urn;
  cell.append(name);
  return cell;
}

function splitUrnClient(urn) {
  const m = /^urn:li:dataset:\(urn:li:dataPlatform:([^,]+),(.+),([A-Za-z]+)\)$/.exec(urn || '');
  if (!m) return { platform: '', database: '', schema: '', table: urn || '', qualified: '', urn: urn || '' };
  const segs = m[2].split('.');
  return {
    platform: m[1],
    database: segs.length > 1 ? segs[0] : '',
    schema: segs.length > 2 ? segs.slice(1, -1).join('.') : '',
    table: segs[segs.length - 1],
    qualified: m[2],
    urn,
  };
}

async function renderConnections() {
  const body = document.getElementById('edge-rows');

  if (state.mode !== 'live') return renderConnectionsLocal();

  let data;
  try {
    data = await getJson(`/api/connections?${filterQuery()}`);
  } catch (err) {
    body.innerHTML = '';
    const tr = el('tr');
    const td = el('td', 'empty-state',
      `The server did not answer (${err.message}). Nothing is shown rather than something invented.`);
    td.colSpan = 6;
    tr.append(td);
    body.append(tr);
    return;
  }

  renderStateChips(data.state_counts);
  fillFacets(data.facets);

  document.getElementById('connections-count').textContent = data.has_run
    ? `${data.total} of ${data.total_unfiltered} checked connections`
      + (state.catalogTotal ? ` · catalog holds ${num(state.catalogTotal)} datasets` : '')
    : 'no check has run yet';
  document.getElementById('nav-count-connections').textContent =
    data.has_run ? String(data.total_unfiltered) : '';

  renderActiveFilters();
  renderPager('connections-pager', data.start, data.count, data.total, (start) => {
    state.filters.start = start;
    renderConnections();
  });

  body.innerHTML = '';
  if (!data.rows.length) {
    const tr = el('tr');
    const td = el('td', 'empty-state', data.has_run
      ? 'No connection matches these filters.'
      : 'No connection has been checked yet. Press “Run a check”.');
    td.colSpan = 6;
    tr.append(td);
    body.append(tr);
    return;
  }

  for (const row of data.rows) {
    const tr = el('tr', 'is-selectable');
    if (state.selected === row.edge) tr.classList.add('is-selected');

    const verdict = el('td');
    verdict.append(el('span', `chip chip--${row.state}`, STATE_WORD[row.state] || row.state));
    tr.append(verdict);

    const from = el('td'); from.append(cellRef(row.from)); tr.append(from);
    const to = el('td'); to.append(cellRef(row.to)); tr.append(to);

    const ev = el('td', 'numbers');
    ev.append(el('div', null, `${row.query_urns.length} queries`));
    ev.append(row.measured
      ? el('div', null, `${row.buckets_seen} usage windows`)
      : el('div', 'notmeasured', 'no usage window'));
    tr.append(ev);

    // Null-Regel: eine gemessene Null ist eine Ziffer, "nicht gemessen"
    // ist ein WORT -- nie ein leeres Feld.
    const last = el('td');
    last.append(row.measured && row.last_covered_ms
      ? el('span', 'numbers', `${dayStamp(row.last_covered_ms)} (${agoPhrase(row.dead_since_days)})`)
      : el('span', 'notmeasured', 'not measured'));
    tr.append(last);

    const j = el('td');
    const tag = { model: 'model cited', abstained: 'abstained', none: 'not asked' }[row.judgement];
    j.append(el('span', `judge-tag judge-tag--${row.judgement}`, tag));
    tr.append(j);

    tr.addEventListener('click', () => selectEdge(row.edge));
    body.append(tr);
  }
}

// Aufzeichnungsmodus: dieselbe Tabelle, lokal gefiltert. Vertretbar, weil
// eine Aufzeichnung per Definition klein ist -- die Live-Sicht, die gegen
// 5.594 Datensaetze laufen muss, geht ueber den Server.
function renderConnectionsLocal() {
  const edges = (state.ledger && state.ledger.edges) || [];
  const f = state.filters;
  const rows = edges.filter((e) => (!f.states.size || f.states.has(e.state))
    && (!f.q || (e.upstream + e.downstream).toLowerCase().includes(f.q.toLowerCase())));
  const counts = { confirmed: 0, dead: 0, missing: 0, unknown: 0 };
  for (const e of edges) counts[e.state] = (counts[e.state] || 0) + 1;

  renderStateChips(counts);
  document.getElementById('connections-count').textContent =
    `${rows.length} of ${edges.length} connections (recorded run)`;
  document.getElementById('nav-count-connections').textContent = String(edges.length);
  renderActiveFilters();
  document.getElementById('connections-pager').innerHTML = '';

  const body = document.getElementById('edge-rows');
  body.innerHTML = '';
  for (const e of rows) {
    const cov = e.coverage || {}, tl = e.timeline || {};
    const measured = (cov.buckets_seen || 0) > 0;
    const tr = el('tr', 'is-selectable');
    if (state.selected === e.edge) tr.classList.add('is-selected');
    const v = el('td'); v.append(el('span', `chip chip--${e.state}`, STATE_WORD[e.state])); tr.append(v);
    for (const urn of [e.upstream, e.downstream]) {
      const td = el('td');
      td.append(cellRef(splitUrnClient(urn)));
      tr.append(td);
    }
    const ev = el('td', 'numbers');
    ev.append(el('div', null, `${((e.evidence || {}).query_urns || []).length} queries`));
    ev.append(measured ? el('div', null, `${cov.buckets_seen} usage windows`)
                        : el('div', 'notmeasured', 'no usage window'));
    tr.append(ev);
    const last = el('td');
    last.append(measured && tl.last_covered_ms
      ? el('span', 'numbers', `${dayStamp(tl.last_covered_ms)} (${agoPhrase(tl.dead_since_days)})`)
      : el('span', 'notmeasured', 'not measured'));
    tr.append(last);
    const j = judgementFor(e.edge);
    const kind = !j ? 'none' : (j.used_model ? 'model' : 'abstained');
    const td = el('td');
    td.append(el('span', `judge-tag judge-tag--${kind}`,
      { model: 'model cited', abstained: 'abstained', none: 'not asked' }[kind]));
    tr.append(td);
    tr.addEventListener('click', () => selectEdge(e.edge));
    body.append(tr);
  }
  if (!rows.length) {
    const tr = el('tr');
    const td = el('td', 'empty-state', 'No connection matches these filters.');
    td.colSpan = 6; tr.append(td); body.append(tr);
  }
}

function renderStateChips(counts) {
  const host = document.getElementById('filter-states');
  host.innerHTML = '';
  for (const s of STATE_ORDER) {
    const on = state.filters.states.has(s);
    const b = el('button', `chip chip--${s}${state.filters.states.size && !on ? ' chip--off' : ''}`);
    b.type = 'button';
    b.textContent = `${STATE_WORD[s]} ${counts[s] || 0}`;
    b.setAttribute('aria-pressed', String(on));
    b.addEventListener('click', () => {
      if (on) state.filters.states.delete(s); else state.filters.states.add(s);
      state.filters.start = 0;
      renderConnections();
    });
    host.append(b);
  }
}

function fillFacets(facets) {
  if (!facets) return;
  for (const [id, list] of [['filter-platform', facets.platforms],
                            ['filter-database', facets.databases]]) {
    const sel = document.getElementById(id);
    if (sel.dataset.filled === String((list || []).length)) continue;
    const current = sel.value;
    sel.innerHTML = '<option value="">all</option>';
    for (const f of list || []) {
      const o = el('option', null, `${f.value} (${f.count})`);
      o.value = f.value;
      sel.append(o);
    }
    sel.value = current;
    sel.dataset.filled = String((list || []).length);
  }
}

function renderActiveFilters() {
  const host = document.getElementById('active-filters');
  host.innerHTML = '';
  const f = state.filters;
  const chips = [];
  for (const s of f.states) chips.push([`verdict: ${STATE_WORD[s]}`, () => f.states.delete(s)]);
  if (f.platform) chips.push([`platform: ${f.platform}`, () => { f.platform = ''; }]);
  if (f.database) chips.push([`database: ${f.database}`, () => { f.database = ''; }]);
  if (f.table) chips.push([`table: ${f.table.split('.').pop()}`, () => { f.table = ''; }]);
  if (f.q) chips.push([`contains: ${f.q}`, () => { f.q = ''; }]);
  if (f.judged) chips.push(['with model judgement', () => { f.judged = false; }]);
  if (f.abstained) chips.push(['abstentions only', () => { f.abstained = false; }]);
  for (const [label, clear] of chips) {
    const b = el('button', 'judge-tag', `${label} ✕`);
    b.type = 'button';
    b.addEventListener('click', () => {
      clear();
      f.start = 0;
      syncControls();
      renderConnections();
    });
    host.append(b);
  }
}

function syncControls() {
  document.getElementById('filter-platform').value = state.filters.platform;
  document.getElementById('filter-database').value = state.filters.database;
  document.getElementById('filter-q').value = state.filters.q;
  document.getElementById('filter-judged').checked = state.filters.judged;
  document.getElementById('filter-abstained').checked = state.filters.abstained;
}

function renderPager(hostId, start, count, total, go) {
  const host = document.getElementById(hostId);
  host.innerHTML = '';
  if (total <= count && start === 0) return;
  const from = total ? start + 1 : 0;
  const to = start + count;
  host.append(el('span', 'pager__label', `${from}–${to} of ${num(total)}`));
  const prev = el('button', 'btn', 'Previous');
  prev.type = 'button';
  prev.disabled = start <= 0;
  prev.addEventListener('click', () => go(Math.max(0, start - PAGE)));
  const next = el('button', 'btn', 'Next');
  next.type = 'button';
  next.disabled = to >= total;
  next.addEventListener('click', () => go(start + PAGE));
  host.append(prev, next);
}

// --- Detailspalte -------------------------------------------------------

function edgeByKey(key) {
  return ((state.ledger && state.ledger.edges) || []).find((e) => e.edge === key) || null;
}

function selectEdge(key) {
  state.selected = key;
  renderDetail();
  if (state.view === 'connections') renderConnections();
}

function sentenceFor(edge) {
  const from = splitUrnClient(edge.upstream);
  const to = splitUrnClient(edge.downstream);
  const cov = edge.coverage || {}, tl = edge.timeline || {};
  const series = tl.series || [];
  const traffic = series.reduce((a, [, n]) => a + n, 0);
  const queries = ((edge.evidence || {}).query_urns || []).length;
  const buckets = cov.buckets_seen || 0;

  if (edge.state === 'confirmed') {
    return `${to.table} draws from ${from.table} according to the catalog, and`
      + ` ${plural(queries, 'query touches', 'queries touch')} both tables.`
      + ` ${to.table} ran ${plural(traffic, 'query', 'queries')} across`
      + ` ${plural(buckets, 'measured window', 'measured windows')},`
      + ` most recently ${agoPhrase(tl.dead_since_days)}. The connection is alive.`;
  }
  if (edge.state === 'dead') {
    const last = dayStamp(tl.last_covered_ms);
    return `${to.table} draws from ${from.table} according to the catalog.`
      + ` Across ${plural(buckets, 'measured window', 'measured windows')}`
      + ` (${plural(cov.days_span || 0, 'day', 'days')}), not one query touched both tables`
      + (traffic ? `, although the tables themselves were used (${traffic} queries)` : '')
      + `.${last ? ` Last measured traffic: ${last}.` : ''} The connection is dead.`;
  }
  if (edge.state === 'missing') {
    return `${plural(queries, 'query joins', 'queries join')} ${from.table} and ${to.table},`
      + ` but nobody ever declared the connection in the catalog.`
      + ` Your lineage is incomplete here.`;
  }
  return `There is no usage data for ${to.table} at all`
    + (cov.reason ? ` — ${humanReason(cov.reason)}` : '')
    + `. We do not guess. This is the case other tools report as “unused”.`;
}

function sparkNode(edge) {
  const wrap = el('div');
  wrap.append(el('p', 'block__label block__label--measured', 'Timeline — what actually moved'));
  const series = (edge.timeline || {}).series || [];
  const buckets = (edge.coverage || {}).buckets_seen || 0;

  if (!buckets || !series.length) {
    const rail = el('div', 'spark--empty no-data');
    rail.dataset.noData = 'true';
    rail.append(el('span', 'bar--empty', 'not measured — no usage window was ever recorded'));
    wrap.append(rail);
    wrap.append(el('p', 'block__text',
      'An empty bar and a missing measurement are not the same claim. This one is missing.'));
    return wrap;
  }

  const max = Math.max(1, ...series.map(([, n]) => n));
  const strip = el('div', 'spark');
  for (const [ms, n] of series) {
    const bar = el('span', n === 0 ? 'spark__bar spark__bar--zero' : 'spark__bar');
    if (n > 0) bar.style.height = `${Math.max(3, Math.round((n / max) * 40))}px`;
    bar.title = `${new Date(ms).toLocaleDateString()} — ${plural(n, 'query', 'queries')}`;
    strip.append(bar);
  }
  wrap.append(strip);

  const axis = el('div', 'spark__axis');
  axis.append(el('span', null, dayStamp(series[0][0]) || ''),
              el('span', null, `peak ${max}/day`),
              el('span', null, dayStamp(series[series.length - 1][0]) || ''));
  wrap.append(axis);

  const zeros = series.filter(([, n]) => n === 0).length;
  const figures = el('div', 'figures');
  const add = (n, label) => {
    const s = el('span');
    s.append(el('b', null, String(n)), document.createTextNode(' ' + label));
    figures.append(s);
  };
  // buckets_seen bleibt EINZELN sichtbar statt in eine Zahl summiert --
  // "nicht gemessen" und "nichts passiert" sind verschiedene Aussagen.
  add(buckets, 'windows measured');
  add(series.reduce((a, [, n]) => a + n, 0), 'queries in total');
  add(zeros, 'windows measured at zero');
  wrap.append(figures);
  return wrap;
}

function judgementNode(edge) {
  const wrap = el('div');
  wrap.append(el('p', 'block__label', 'Model judgement — only with a verbatim quote'));

  if (edge.state === 'confirmed') {
    const box = el('div', 'judgement judgement--pending');
    box.append(el('span', 'judgement__badge', 'not asked'));
    box.append(el('p', 'judgement__reason',
      'The model is never asked about a confirmed connection. The deterministic finding is'
      + ' already the cheapest and strongest statement there is.'));
    wrap.append(box);
    return wrap;
  }

  const found = judgementFor(edge.edge);
  if (!found) {
    const running = state.judge && state.judge.running;
    const box = el('div', 'judgement judgement--pending');
    box.append(el('span', 'judgement__badge', running ? 'reading the catalog…' : 'not run yet'));
    box.append(el('p', 'judgement__reason', running
      ? 'The model is reading this connection’s catalog text right now. The verdict never'
        + ' depended on it.'
      : 'Press “Run a check” to send the deviating connections to the model.'));
    wrap.append(box);
    return wrap;
  }

  const cited = !!found.used_model;
  const box = el('div', `judgement ${cited ? 'judgement--cited' : 'judgement--abstained'}`);
  const head = el('div', 'judgement__head');
  head.append(el('span', 'judgement__badge',
    cited ? (found.important ? 'important — cited' : 'not important — cited') : 'abstained'));
  head.append(el('span', 'judgement__meta',
    `${found.seconds != null ? `${found.seconds}s` : 'duration not recorded'} · `
    + `${typeof found.cost_usd === 'number' ? `$${found.cost_usd.toFixed(4)}` : 'cost not recorded'}`));
  box.append(head);

  if (cited) {
    box.append(el('blockquote', 'judgement__quote', `“${found.quote}”`));
    const src = el('p', 'judgement__source');
    src.append(document.createTextNode('quoted verbatim from the '));
    src.append(el('code', null, found.source_field || 'catalog text'));
    src.append(document.createTextNode(' field of the catalog entry.'));
    box.append(src);
    box.append(el('p', 'judgement__reason', found.reason || ''));
  } else {
    const why = el('p', 'judgement__quote');
    why.textContent = 'No quote survived the check — '
      + `${humanReason(found.fallback_reason) || 'reason not recorded'}.`;
    if (found.fallback_reason) why.title = found.fallback_reason;
    box.append(why);
    box.append(el('p', 'judgement__reason',
      'The model may only call a deviation important if it quotes the catalog text verbatim.'
      + ' It did not, so its opinion was discarded and the measured verdict stands unchanged.'));
  }
  box.append(el('p', 'judgement__rule',
    'Citation duty: a judgement without a verbatim quote is dropped, never softened.'
    + ' The abstention rate is a result of this bench, not a defect.'));
  wrap.append(box);
  return wrap;
}

function renderDetail() {
  const panel = document.getElementById('detail');
  const body = document.getElementById('detail-body');
  const edge = state.selected ? edgeByKey(state.selected) : null;
  if (!edge) {
    panel.hidden = true;
    document.querySelector('.app__body').classList.remove('has-detail');
    return;
  }
  panel.hidden = false;
  document.querySelector('.app__body').classList.add('has-detail');

  const from = splitUrnClient(edge.upstream);
  const to = splitUrnClient(edge.downstream);
  document.getElementById('detail-title').textContent = `${from.table} → ${to.table}`;

  body.innerHTML = '';
  const verdict = el('div');
  verdict.append(el('span', `chip chip--${edge.state}`, STATE_WORD[edge.state]));
  body.append(verdict);
  body.append(el('p', 'detail__sentence', sentenceFor(edge)));

  const help = stateHelpNode(edge.state);
  if (help) { help.className = 'block__text'; body.append(help); }

  const declared = el('div');
  declared.append(el('p', 'block__label block__label--declared', 'Declared — what the catalog claims'));
  const src = (edge.evidence || {}).source || '';
  declared.append(el('p', 'block__text', src.includes('declared lineage')
    ? `${to.table} lists ${from.table} as an upstream. Nobody has re-checked it since it was written.`
    : 'Nobody wrote this connection into the catalog. It exists only in what the queries did.'));
  for (const urn of ((edge.evidence || {}).query_urns || [])) {
    declared.append(el('p', 'block__urn', urn));
  }
  declared.append(el('p', 'block__urn', edge.upstream));
  declared.append(el('p', 'block__urn', edge.downstream));
  body.append(declared);

  body.append(sparkNode(edge));
  body.append(judgementNode(edge));
}

// --- Bereich 3: Katalog -------------------------------------------------

async function renderCatalog() {
  const host = document.getElementById('catalog-tree');
  const countEl = document.getElementById('catalog-count');
  if (state.mode !== 'live') {
    host.innerHTML = '';
    host.append(el('p', 'empty-state',
      'The catalog tree needs a live instance — a recording carries only the connections it measured.'));
    countEl.textContent = 'recording';
    return;
  }
  host.innerHTML = '';
  host.append(el('p', 'empty-state', 'Loading a page of the catalog…'));
  let data;
  try {
    data = await getJson(`/api/catalog?q=${encodeURIComponent(state.catalog.q || '*')}`
                          + `&start=${state.catalog.start}&count=${PAGE}`);
  } catch (err) {
    host.innerHTML = '';
    host.append(el('p', 'empty-state', `The catalog did not answer (${err.message}).`));
    return;
  }
  state.catalog.total = data.total;
  state.catalogTotal = data.total;
  document.getElementById('nav-count-catalog').textContent = num(data.total);
  countEl.textContent =
    `${data.start + 1}–${data.start + data.rows.length} of ${num(data.total)} datasets`;
  renderPager('catalog-pager', data.start, data.rows.length, data.total, (start) => {
    state.catalog.start = start;
    renderCatalog();
  });

  host.innerHTML = '';
  const groups = new Map();
  for (const row of data.rows) {
    const key = `${row.platform || 'unknown platform'} / ${row.database || '(no database)'}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  for (const [key, rows] of groups) {
    const g = el('div', 'tree__group');
    g.append(el('p', 'tree__group-head',
      `${key} — ${plural(rows.length, 'table', 'tables')} on this page`));
    for (const row of rows) {
      const leaf = el('button', 'tree__leaf');
      leaf.type = 'button';
      leaf.title = row.urn;
      if (row.checked && row.state) {
        leaf.append(el('span', `chip chip--${row.state}`, STATE_WORD[row.state]));
      } else {
        // Kein grauer Punkt fuer "nie geprueft" -- ein Punkt saehe aus wie
        // ein Urteil. Es steht als Wort da.
        leaf.append(el('span', 'tree__unchecked', 'not checked'));
      }
      leaf.append(el('span', null, [row.schema, row.table].filter(Boolean).join('.')));
      leaf.addEventListener('click', () => {
        state.filters.table = row.qualified || '';
        state.filters.start = 0;
        showView('connections');
      });
      g.append(leaf);
    }
    host.append(g);
  }
}

// --- Bereich 4: Laeufe --------------------------------------------------

async function renderRuns() {
  const body = document.getElementById('runs-rows');
  body.innerHTML = '';
  let data = { runs: [] };
  try {
    if (state.mode === 'live') data = await getJson('/api/runs');
  } catch { /* leere Liste ist unten ein eigener, benannter Zustand */ }

  if (!data.runs.length) {
    const tr = el('tr');
    const td = el('td', 'empty-state', state.mode === 'live'
      ? 'No run artifact on disk yet.'
      : 'Run history needs a live instance — it reads the artifacts on disk.');
    td.colSpan = 6; tr.append(td); body.append(tr);
    return;
  }
  for (const r of data.runs) {
    const tr = el('tr');
    tr.append(el('td', 'numbers', r.at_iso ? new Date(r.at_iso).toLocaleString() : 'unknown'));
    const a = el('td'); a.append(el('span', 'block__urn', r.artifact)); tr.append(a);
    tr.append(el('td', 'numbers', r.edges_total == null ? 'n/a' : String(r.edges_total)));
    tr.append(el('td', 'numbers', r.confirmed == null ? 'n/a'
      : `${r.confirmed} confirmed · ${r.dead} dead · ${r.missing} missing · ${r.unknown} not judged`));
    tr.append(el('td', 'numbers', r.api_calls == null ? 'n/a' : String(r.api_calls)));
    tr.append(el('td', r.abstention_rate == null ? 'notmeasured' : 'numbers',
      r.abstention_rate == null ? 'not measured' : `${Math.round(r.abstention_rate * 100)}%`));
    body.append(tr);
  }
}

// --- Bereich 5: Belege --------------------------------------------------

async function renderEvidence() {
  const host = document.getElementById('evidence-list');
  const countEl = document.getElementById('evidence-count');
  host.innerHTML = '';
  const q = document.getElementById('evidence-q').value || '';
  let items = [];
  if (state.mode === 'live') {
    try {
      items = (await getJson(`/api/evidence?q=${encodeURIComponent(q)}`)).items;
    } catch { items = []; }
  } else {
    for (const j of (state.judge && state.judge.judgements) || []) {
      items.push({
        kind: j.used_model ? 'quote' : 'abstention',
        label: j.edge.split('->').map((u) => splitUrnClient(u).table).join(' → '),
        text: j.used_model ? j.quote : (j.fallback_reason || ''),
        detail: j.used_model ? `verbatim from field “${j.source_field}”`
                              : 'model abstained — deterministic verdict stands',
      });
    }
    const needle = q.toLowerCase();
    if (needle) items = items.filter((i) => (i.text + i.label).toLowerCase().includes(needle));
  }
  countEl.textContent = `${items.length} pieces of evidence`;
  if (!items.length) {
    host.append(el('p', 'empty-state', 'No evidence collected yet.'));
    return;
  }
  for (const i of items) {
    const row = el('div', `evidence-item evidence-item--${i.kind}`);
    const left = el('div');
    left.append(el('p', 'evidence-item__kind', i.kind));
    left.append(el('p', 'block__urn', i.label));
    const right = el('div');
    right.append(el('p', 'evidence-item__text',
      i.kind === 'quote' ? `“${i.text}”`
        : i.kind === 'abstention' ? humanReason(i.text) : i.text));
    if (i.detail) right.append(el('p', 'evidence-item__detail', i.detail));
    row.append(left, right);
    host.append(row);
  }
}

// --- Protokoll ----------------------------------------------------------

let lastLogText = null, lastLogNode = null, lastLogRepeat = 1;

function appendLogLine(t, text) {
  const host = document.getElementById('live-log');
  const stale = host.querySelector('.empty-state');
  if (stale) stale.remove();

  // Wiederholungen werden GEZAEHLT, nicht wiederholt: zwanzig identische
  // Zeilen beweisen nichts ausser einem mehrfach gedrueckten Knopf.
  if (text === lastLogText && lastLogNode && lastLogNode.isConnected) {
    lastLogRepeat += 1;
    let badge = lastLogNode.querySelector('.log-entry__repeat');
    if (!badge) {
      badge = el('span', 'log-entry__repeat');
      lastLogNode.querySelector('.log-entry__text').append(badge);
    }
    badge.textContent = `×${lastLogRepeat}`;
    return;
  }
  const line = el('div', 'log-entry');
  if (/model (call|run|queue)/.test(text)) line.classList.add('log-entry--model');
  line.append(el('span', 'log-entry__time', new Date(t).toLocaleTimeString()));
  line.append(el('span', 'log-entry__text', text));
  host.prepend(line);
  lastLogText = text; lastLogNode = line; lastLogRepeat = 1;
}

let logCursor = 0;
async function pumpLog() {
  try {
    const { entries, cursor } = await getJson(`/api/log?since=${logCursor}`);
    logCursor = cursor;
    for (const e of entries) appendLogLine(e.t, e.n != null ? `${e.text} (${e.n})` : e.text);
  } catch { /* der naechste Takt versucht es erneut */ }
}

function replayRecordedLog() {
  for (const e of ((state.judge && state.judge.log) || [])) {
    appendLogLine(e.t, e.n != null ? `${e.text} (${e.n})` : e.text);
  }
}

// --- Kopfzeile, Uhr, Thema, Navigation ---------------------------------

function renderModeBadge(info) {
  const badge = document.getElementById('mode-badge');
  badge.dataset.mode = info.mode;
  badge.textContent = info.mode === 'live'
    ? `Live — buttons write to ${info.gms}`
    : 'Recording — replaying a stored run, buttons disabled';
  document.getElementById('instance-label').textContent = info.mode === 'live'
    ? `catalog: ${info.gms}` : 'catalog: recorded run';
  document.getElementById('status-instance').textContent = info.mode === 'live'
    ? `${info.gms} · ${(info.focuses || []).length} observed source tables`
    : 'recorded run';

  const offset = document.getElementById('time-offset');
  if (info.mode !== 'live') { offset.hidden = true; return; }
  const days = info.view_offset_days || 0;
  offset.hidden = false;
  offset.dataset.shifted = String(days > 0);
  offset.querySelector('.time-offset__value').textContent =
    days > 0 ? `Clock moved +${plural(days, 'day', 'days')}` : 'Clock: now';
  offset.querySelector('.time-offset__reset').disabled = days === 0;
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = theme === 'dark' ? 'Light theme' : 'Dark theme';
  try { localStorage.setItem('werkbank-theme', theme); } catch { /* privater Modus */ }
}

function showView(name) {
  state.view = name;
  for (const pane of document.querySelectorAll('.pane')) {
    pane.hidden = pane.dataset.view !== name;
  }
  for (const item of document.querySelectorAll('.sidenav__item')) {
    item.classList.toggle('is-active', item.dataset.view === name);
  }
  if (name === 'connections') renderConnections();
  if (name === 'catalog') renderCatalog();
  if (name === 'runs') renderRuns();
  if (name === 'evidence') renderEvidence();
  if (name === 'overview') renderOverview();
}

// --- Laden und Neuzeichnen ---------------------------------------------

export function render() {
  renderOverview();
  if (state.view === 'connections') renderConnections();
  if (state.view === 'evidence') renderEvidence();
  renderDetail();
}

async function refresh() {
  try {
    state.ledger = await loadLedger(state.mode);
  } catch (err) {
    // Ein gescheiterter Abruf ist keine Abwesenheit von Kanten: die Seite
    // sagt das, statt eine leere Liste zu zeigen, die wie "alles in
    // Ordnung" aussieht.
    state.ledger = null;
    document.getElementById('run-verdict').textContent =
      `The catalog did not answer (${err.message}). Nothing is shown rather than something invented.`;
  }
  state.judge = await loadJudgements(state.mode);
  render();
}

let judgePoll = null;
function watchJudgements() {
  if (judgePoll) return;
  judgePoll = setInterval(async () => {
    state.judge = await loadJudgements('live');
    renderOverview();
    if (state.view === 'connections') renderConnections();
    if (state.view === 'evidence') renderEvidence();
    renderDetail();
    if (!state.judge || !state.judge.running) { clearInterval(judgePoll); judgePoll = null; }
  }, 2500);
}

async function runAction(name, btn) {
  if (state.mode !== 'live') return;
  if (btn) btn.disabled = true;
  try {
    const r = await fetch(`/api/action/${name}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...API_HEADERS },
      body: '{}',
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      appendLogLine(Date.now(), `action refused — ${body.error || r.status}`);
      return;
    }
    await refresh();
    await pumpLog();
    renderModeBadge(await fetchModeInfo());
    if (state.judge && state.judge.running) watchJudgements();
  } finally {
    if (btn) btn.disabled = false;
  }
}

// --- Verdrahtung --------------------------------------------------------

for (const item of document.querySelectorAll('.sidenav__item')) {
  item.addEventListener('click', () => showView(item.dataset.view));
}

document.getElementById('controls').addEventListener('click', (ev) => {
  const btn = ev.target.closest('button[data-action]');
  // Aufzeichnungsmodus: die Knoepfe sind bereits deaktiviert (boot()),
  // dieser zweite Riegel gilt jedem zukuenftigen Aufrufer -- eine
  // Aufzeichnung darf nie so tun, als schreibe sie.
  if (!btn || btn.disabled || document.body.dataset.mode !== 'live') return;
  runAction(btn.dataset.action, btn);
});

document.getElementById('run-check').addEventListener('click', (ev) => {
  if (document.body.dataset.mode !== 'live') return;
  runAction('run-ledger', ev.currentTarget);
});

document.getElementById('theme-toggle').addEventListener('click', () => {
  applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
});

document.getElementById('detail-close').addEventListener('click', () => {
  state.selected = null;
  renderDetail();
  if (state.view === 'connections') renderConnections();
});

document.getElementById('time-offset-reset').addEventListener('click', async () => {
  await fetch('/api/view/reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...API_HEADERS },
    body: '{}',
  });
  renderModeBadge(await fetchModeInfo());
  await refresh();
  await pumpLog();
});

for (const [id, key] of [['filter-platform', 'platform'], ['filter-database', 'database'],
                          ['filter-sort', 'sort']]) {
  document.getElementById(id).addEventListener('change', (ev) => {
    state.filters[key] = ev.target.value;
    state.filters.start = 0;
    renderConnections();
  });
}
for (const [id, key] of [['filter-judged', 'judged'], ['filter-abstained', 'abstained']]) {
  document.getElementById(id).addEventListener('change', (ev) => {
    state.filters[key] = ev.target.checked;
    state.filters.start = 0;
    renderConnections();
  });
}

let qTimer = null;
document.getElementById('filter-q').addEventListener('input', (ev) => {
  clearTimeout(qTimer);
  const value = ev.target.value.trim();
  qTimer = setTimeout(() => {
    state.filters.q = value;
    state.filters.start = 0;
    renderConnections();
  }, 200);
});

let gTimer = null;
document.getElementById('global-search').addEventListener('input', (ev) => {
  clearTimeout(gTimer);
  const value = ev.target.value.trim();
  gTimer = setTimeout(() => {
    state.catalog.q = value || '*';
    state.catalog.start = 0;
    document.getElementById('catalog-q').value = value;
    showView('catalog');
  }, 300);
});

let cTimer = null;
document.getElementById('catalog-q').addEventListener('input', (ev) => {
  clearTimeout(cTimer);
  const value = ev.target.value.trim();
  cTimer = setTimeout(() => {
    state.catalog.q = value || '*';
    state.catalog.start = 0;
    renderCatalog();
  }, 300);
});

let eTimer = null;
document.getElementById('evidence-q').addEventListener('input', () => {
  clearTimeout(eTimer);
  eTimer = setTimeout(renderEvidence, 250);
});

setInterval(() => { if (document.body.dataset.mode === 'live') pumpLog(); }, 1500);

async function boot() {
  try {
    const saved = localStorage.getItem('werkbank-theme');
    if (saved) applyTheme(saved);
    else document.getElementById('theme-toggle').textContent =
      matchMedia('(prefers-color-scheme: dark)').matches ? 'Light theme' : 'Dark theme';
  } catch { /* privater Modus */ }

  const info = await fetchModeInfo();
  state.mode = info.mode;
  state.info = info;
  document.body.dataset.mode = info.mode;
  renderModeBadge(info);
  const live = info.mode === 'live';
  document.querySelectorAll('#controls button').forEach((b) => { b.disabled = !live; });
  document.getElementById('run-check').disabled = !live;

  await refresh();
  if (live) {
    await pumpLog();
    if (state.judge && state.judge.running) watchJudgements();
    // Die Gesamtzahl des Katalogs steht in der Seitenleiste, bevor jemand
    // den Bereich oeffnet -- "N von 5.594" ist die Einordnung, die der
    // alten Oberflaeche gefehlt hat.
    try {
      const cat = await getJson('/api/catalog?q=*&start=0&count=1');
      state.catalogTotal = cat.total;
      document.getElementById('nav-count-catalog').textContent = num(cat.total);
    } catch { /* der Bereich holt es beim Oeffnen selbst */ }
  } else {
    replayRecordedLog();
  }
  showView('overview');
}

boot();
