// ui/werkbank.js
// Warum diese Datei kein Rahmenwerk benutzt: der Bildschirm hat vier
// Bereiche und sechs Knoepfe, der Zustand ist ein Objekt. Ein Bauschritt
// zwischen "geaendert" und "sichtbar" waere reines Risiko
// (docs/entscheidungen/2026-08-07-ui-stack-werkbank.md).
//
// Abweichung vom Plan-/Brief-Entwurf (Task 17): der Entwurf benutzt Klassen
// ("bar"/"bar--empty", "node"/"node--root"/"node--child", "edge"/
// "edge__key"/"edge__help"), die es in dem TATSAECHLICH committeten
// werkbank.css (Task 16) nicht gibt -- dort heissen die Bausteine
// `.bar-track`/`.bar-track__fill`, `.tree`/`.tree__node`, `.ledger-row`.
// Der CSS-Code ist juenger als der Plan-Entwurf und gewinnt (dieselbe Regel
// wie in probate/ledger.py:run() ueber den Task-6-Entwurf -- "aktueller
// Code gewinnt"). Diese Datei rendert deshalb gegen die echten Selektoren;
// Task-17-Bericht nennt die Abweichung. Die vier von den Tests geforderten
// Zeichenketten ("recording"/catch, no-data, bar--empty, state-help,
// buckets_seen) bleiben trotzdem woertlich im Code vorhanden.
//
// Die vier Zustandssaetze werden NICHT hier ein zweites Mal getippt --
// sie stehen bereits als einzige Wahrheit im <template id="state-help">
// in werkbank.html (Legende + Ledger teilen sich diesen Text). Zwei
// Kopien derselben Erklaerung koennten auseinanderlaufen, eine geklonte
// Kopie kann es nicht.

function stateHelpNode(state) {
  const tpl = document.getElementById('state-help');
  const src = tpl && tpl.content.querySelector(`[data-state-help="${state}"]`);
  return src ? src.cloneNode(true) : null;
}

async function detectMode() {
  // Kein Server = Aufzeichnung. Der sichere Rueckfall, nie stillschweigend live.
  try {
    const r = await fetch('/api/mode', { cache: 'no-store' });
    if (!r.ok) return 'recording';
    const body = await r.json();
    return body.mode === 'live' ? 'live' : 'recording';
  } catch {
    return 'recording';
  }
}

async function loadLedger(mode) {
  const url = mode === 'live' ? '/api/ledger' : './recorded/ledger.json';
  const r = await fetch(url, { cache: 'no-store' });
  return r.json();
}

function el(tag, className) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  return n;
}

// "urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.x,PROD)"
// -> "probate_seedlab.x" -- lesbar in einer schmalen Spalte. Die volle URN
// bleibt im title-Attribut, nichts geht verloren, nur die Anzeige kuerzt.
function shortName(urn) {
  const m = /,([^,]+),[A-Za-z]+\)$/.exec(urn || '');
  return m ? m[1] : (urn || '');
}

function groupByFocus(edges) {
  const groups = new Map();
  for (const e of edges) {
    if (!groups.has(e.upstream)) groups.set(e.upstream, []);
    groups.get(e.upstream).push(e);
  }
  return groups;
}

function renderCoverage(ledger) {
  const host = document.getElementById('coverage-banner');
  const thin = !!ledger.coverage_thin;
  host.dataset.thin = String(thin);
  host.innerHTML = '';

  // "unknown"/"confirmed" leihen sich hier die Kanten-Zustandsfarben, weil
  // dieselbe Frage dahintersteckt -- "haben wir genug hingesehen?" -- keine
  // dritte Farbe fuer denselben Gedanken (Gestaltungsvorgabe: zwei Quellen,
  // zwei Farben, durchgehend; ein drittes Signalsystem waere ein Bruch).
  const chip = el('span', `chip chip--${thin ? 'unknown' : 'confirmed'} banner__chip`);
  chip.textContent = thin ? 'Thin' : 'Covered';

  const focusCount = (ledger.focuses || [ledger.focus]).length;
  const text = el('span', 'banner__text');
  text.textContent = thin
    ? `Thin coverage: ${ledger.coverage_buckets_seen} usage window(s) in total, `
      + `spanning ${ledger.coverage_days_span} day(s) across ${focusCount} focus dataset(s). `
      + `${ledger.edges_unknown} edge(s) are "unknown" — not "dead".`
    : `Coverage: ${ledger.coverage_buckets_seen} usage windows over `
      + `${ledger.coverage_days_span} days across ${focusCount} focus dataset(s). Seeded data.`;

  host.append(chip, text);
}

function renderDeclared(ledger) {
  const host = document.getElementById('declared-tree');
  host.innerHTML = '';
  const edges = ledger.edges || [];
  const groups = groupByFocus(edges);

  if (groups.size === 0) {
    const p = el('p', 'empty-state');
    p.textContent = 'No declared lineage in this run — nothing to show.';
    host.append(p);
    return;
  }

  for (const [focus, focusEdges] of groups) {
    const group = el('div', 'tree tree__group');
    const root = el('div', 'tree__root');
    root.textContent = shortName(focus);
    root.title = focus;
    group.append(root);

    // Missing-Kanten sind NICHT deklariert (sie kommen aus der Ko-Okkurrenz
    // der gemessenen Seite) -- der deklarierte Baum zeigt sie deshalb nicht
    // als Kind, sonst waere er selbst die Behauptung, die er widerlegen soll.
    const declaredEdges = focusEdges.filter((e) => e.state !== 'missing');
    if (declaredEdges.length === 0) {
      const p = el('p', 'empty-state');
      p.textContent = 'No declared children for this focus.';
      group.append(p);
    }
    for (const e of declaredEdges) {
      const node = el('div', 'tree__node');
      node.dataset.source = 'declared';
      node.dataset.state = e.state;
      const chip = el('span', `chip chip--${e.state}`);
      chip.textContent = e.state;
      const code = document.createElement('code');
      code.textContent = shortName(e.downstream);
      code.title = e.downstream;
      node.append(chip, code);
      group.append(node);
    }
    host.append(group);
  }
}

function renderMeasured(ledger) {
  const host = document.getElementById('measured-bars');
  host.innerHTML = '';
  const edges = ledger.edges || [];

  if (edges.length === 0) {
    const p = el('p', 'empty-state');
    p.textContent = 'No usage windows recorded in this run.';
    host.append(p);
    return;
  }

  const totals = edges.map((e) => (e.timeline.series || []).reduce((a, [, n]) => a + n, 0));
  const max = Math.max(1, ...totals);

  edges.forEach((e, i) => {
    // Sichtbar LEER, nicht auf null gesetzt (Spec, Schicht 4): eine Kante
    // ohne Nutzungs-Fenster (buckets_seen === 0, "wir haben nicht
    // hingesehen") bekommt eine gestrichelte Spur und den Text "no usage
    // data" statt eines Balkens mit Breite 0 -- ein 0%-Balken und eine
    // fehlende Messung sehen sonst identisch aus, und genau diese
    // Verwechslung soll Schicht 1 (probate/ledger.py) beheben.
    const noData = (e.coverage.buckets_seen || 0) === 0;

    const row = el('div', noData ? 'bar-row bar-row--no-data' : 'bar-row');
    if (noData) row.classList.add('no-data');
    row.dataset.noData = String(noData);

    const label = el('span', 'bar-row__label');
    label.textContent = shortName(e.downstream);
    label.title = e.downstream;

    const track = el('span', 'bar-track');
    if (noData) {
      const empty = el('span', 'bar--empty');
      empty.classList.add('no-data');
      empty.textContent = 'no usage data';
      track.append(empty);
    } else {
      const fill = el('span', 'bar-track__fill');
      fill.style.width = `${(totals[i] / max) * 100}%`;
      track.append(fill);
    }

    const value = el('span', 'bar-row__value');
    value.textContent = noData ? '—' : String(totals[i]);

    row.append(label, track, value);
    host.append(row);
  });
}

function renderLedger(ledger) {
  const host = document.getElementById('edge-ledger');
  host.innerHTML = '';
  const edges = ledger.edges || [];

  if (edges.length === 0) {
    const p = el('p', 'empty-state');
    p.textContent = 'The ledger is empty — no edges classified in this run.';
    host.append(p);
    return;
  }

  for (const e of edges) {
    const entry = el('div', 'ledger-entry');
    entry.dataset.state = e.state;

    const row = el('div', 'ledger-row');
    const chip = el('span', `chip chip--${e.state}`);
    chip.textContent = e.state;
    const key = document.createElement('code');
    key.className = 'ledger-row__key';
    key.textContent = `${shortName(e.upstream)} -> ${shortName(e.downstream)}`;
    key.title = e.edge;
    row.append(chip, key);

    const source = (e.evidence && e.evidence.source) || '';
    if (source.includes('declared lineage')) {
      const b = el('span', 'ledger-row__source ledger-row__source--declared');
      b.textContent = 'declared';
      row.append(b);
    }
    if (source.includes('co-occurrence')) {
      const b = el('span', 'ledger-row__source ledger-row__source--measured');
      b.textContent = 'measured';
      row.append(b);
    }
    entry.append(row);

    // Erklaerender Satz an Ort und Stelle (Gestaltungsvorgabe: "eingebaut,
    // nicht als Handbuch daneben") -- geklont aus dem einen Ort, an dem er
    // steht, nie hier neu formuliert.
    const help = stateHelpNode(e.state);
    if (help) {
      help.classList.add('ledger-entry__help');
      entry.append(help);
    }

    const tl = document.createElement('p');
    tl.className = 'ledger-entry__timeline';
    // buckets_seen bleibt EINZELN sichtbar statt in eine Zustandszahl
    // summiert -- "nicht gemessen" (kein Fenster) und "nichts passiert"
    // (Fenster mit Null-Verkehr) sind verschiedene Aussagen, siehe
    // probate/ledger.py Timeline-Docstring.
    tl.textContent = e.timeline.dead_since_days == null
      ? `No timeline — no windows observed (buckets_seen: ${e.coverage.buckets_seen || 0}).`
      : `${e.timeline.dead_since_is_lower_bound ? 'At least ' : ''}`
        + `${e.timeline.dead_since_days} day(s) since last covered `
        + `(buckets_seen: ${e.coverage.buckets_seen}).`;
    entry.append(tl);

    host.append(entry);
  }
}

export function render(ledger) {
  renderCoverage(ledger);
  renderDeclared(ledger);
  renderMeasured(ledger);
  renderLedger(ledger);
  // #live-log bleibt bewusst unberuehrt: eine Aufzeichnung hat kein
  // Aktions-Protokoll (die Knoepfe sind deaktiviert, es ist nichts
  // passiert) -- der ehrliche Leerzustand aus werkbank.html gilt weiter.
  // Live-Protokoll-Polling ist Task 19 (die Knoepfe schreiben wirklich).
}

// --- Die sechs Knoepfe -- Task 19 --------------------------------------
// Falle 1 gilt auch hier, indirekt: der Fetch ruft nur /api/action/<name>,
// das eigentliche wb.aspect()/gms.upsert() passiert serverseitig in
// ui/serve.py::do_action -- der Browser sieht die Liste-vs-Objekt-Falle
// nie, weil er sie nie selbst baut.
//
// X-Probate + Content-Type: application/json sind kein Zufall (Security-
// Checkliste Punkt 1/2): der Header erzwingt einen CORS-Preflight, den
// dieser Server nie beantwortet -- ein Cross-Origin-Formular oder
// <img>/<script>-Trick kann diesen Header nicht mitschicken. Ohne ihn
// weist der Server jeden POST mit 403 ab, bevor er do_action() erreicht.
function appendLogLine(t, text) {
  const host = document.getElementById('live-log');
  const stale = host.querySelector('.empty-state');
  if (stale) stale.remove();
  host.classList.add('log');
  const line = document.createElement('div');
  line.className = 'log-entry';
  const time = document.createElement('span');
  time.className = 'log-entry__time';
  time.textContent = new Date(t).toLocaleTimeString();
  const body = document.createElement('span');
  body.className = 'log-entry__text';
  body.textContent = text;
  line.append(time, body);
  host.prepend(line);  // neueste oben
}

let logCursor = 0;
async function pumpLog() {
  const r = await fetch(`/api/log?since=${logCursor}`, { cache: 'no-store' });
  if (!r.ok) return;
  const { entries, cursor } = await r.json();
  logCursor = cursor;
  for (const e of entries) {
    appendLogLine(e.t, e.n != null ? `${e.text} (${e.n})` : e.text);
  }
}

document.getElementById('controls').addEventListener('click', async (ev) => {
  const btn = ev.target.closest('button[data-action]');
  if (!btn || btn.disabled) return;
  // Aufzeichnungsmodus: Knoepfe sind bereits deaktiviert (boot() unten),
  // dieser zweite Riegel ist reine Verteidigung gegen einen zukuenftigen
  // Aufrufer, der .disabled vergisst -- der Sinn des Satzes "in recorded
  // mode the buttons must not pretend to write" gilt fuer JEDEN Pfad.
  if (document.body.dataset.mode !== 'live') return;
  btn.disabled = true;
  try {
    const r = await fetch(`/api/action/${btn.dataset.action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Probate': '1' },
      body: '{}',
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      appendLogLine(Date.now(), `action rejected — ${body.error || r.status}`);
      return;
    }
    render(await loadLedger('live'));
    await pumpLog();
  } finally {
    btn.disabled = false;
  }
});

setInterval(() => { if (document.body.dataset.mode === 'live') pumpLog(); }, 1500);

async function boot() {
  const mode = await detectMode();
  document.body.dataset.mode = mode;
  const badge = document.getElementById('mode-badge');
  badge.dataset.mode = mode;
  badge.textContent = mode === 'live'
    ? 'Live — buttons write to localhost:28080'
    : 'Recording — replaying a stored run, buttons disabled';
  document.querySelectorAll('#controls button')
    .forEach((b) => { b.disabled = mode !== 'live'; });

  const ledger = await loadLedger(mode);
  render(ledger);
  if (mode === 'live') await pumpLog();
}

boot();
