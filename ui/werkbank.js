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

// Die Zahl rechts an einem Navigationspunkt (Referenz). `null` heisst
// NICHT null, sondern "noch nicht gezaehlt" -- und sieht deshalb anders
// aus als eine gemessene Null, mit dem Grund im title. Genau diese
// Verwechslung ist die Null-Regel der Spec.
function setNavCount(id, value, what) {
  const host = document.getElementById(id);
  if (!host) return;
  if (value == null) {
    host.textContent = '—';
    host.title = `not counted yet — open this section to count ${what}`;
    return;
  }
  host.textContent = num(value);
  host.title = `${num(value)} ${what}`;
}

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

// --- Der erklaerte Leerzustand ------------------------------------------
//
// Gemessener Defekt (07.08.): `/api/connections` antwortete nach dem
// Serverstart mit `rows: []`, und die Seite zeigte eine wortlos leere
// Tabelle -- von "kaputt" nicht zu unterscheiden. Die Null-Regel der Spec
// ("keine Daten" und "gemessene Null" sehen NIE gleich aus) war auf die
// Balken angewendet und auf dem Hauptbildschirm vergessen.
//
// Ab jetzt geht JEDER leere Bereich durch diese eine Funktion: was fehlt,
// warum, und der Knopf, der es behebt. Fuenf Bereiche, ein Bauteil --
// damit kann keiner die Erklaerung vergessen.
function blankNode({ what, why, action, label }) {
  const box = el('div', 'blank');
  box.append(el('p', 'blank__what', what));
  if (why) box.append(el('p', 'blank__why', why));
  if (action) {
    const btn = el('button', 'btn btn--primary', label || 'Run a check');
    btn.type = 'button';
    btn.dataset.action = action;
    // Ein Knopf, der im Aufzeichnungsmodus schreiben wuerde, waere eine
    // Luege ueber das, was gerade passiert.
    if (document.body.dataset.mode !== 'live') {
      btn.disabled = true;
      box.append(btn, el('p', 'blank__why',
        'Disabled: this page is replaying a stored run and writes nothing.'));
      return box;
    }
    box.append(btn);
  }
  return box;
}

function blankInto(host, spec) {
  host.innerHTML = '';
  host.append(blankNode(spec));
}

function blankRow(colspan, spec) {
  const tr = el('tr');
  const td = el('td');
  td.colSpan = colspan;
  td.append(blankNode(spec));
  tr.append(td);
  return tr;
}

// --- Zustand der Oberflaeche -------------------------------------------

const state = {
  mode: 'recording',
  info: {},
  ledger: null,
  // Warum nichts da ist -- WOERTLICH vom Server (`/api/current`), nie im
  // Browser erfunden. Ein Leerzustand ohne Grund ist von "kaputt" nicht
  // zu unterscheiden.
  emptyReason: '',
  judge: null,
  view: 'overview',
  selected: null,
  catalogTotal: null,
  filters: {
    states: new Set(),
    platform: '', database: '', table: '', q: '',
    // Domaene/Besitzer kommen aus dem Governance-Artefakt, `idle` ist die
    // Stillstandsdauer in Tagen (siehe console_api.filter_sort_page).
    domain: '', owner: '', idle: '',
    judged: false, abstained: false,
    // Gruppiert nach Plattform -> Datenbank (Referenz: "Projekte nach
    // Programm"). Voreingestellt AN: bei 513 Kanten ueber vier
    // Plattformen ist die flache Liste die Ansicht, in der man nicht
    // weiss, wovon die Rede ist -- genau Joels Kritik.
    grouped: true,
    sort: 'state', dir: 'asc', start: 0,
  },
  // Beschriftungen der Auswahllisten, gemerkt fuer die Chips: der Chip soll
  // "Finance (probate_demo)" zeigen, nicht die URN.
  facetLabels: { domain: new Map(), owner: new Map(), database: new Map() },
  catalog: { q: '', start: 0, total: 0 },
};

const STATE_WORD = { confirmed: 'CONFIRMED', dead: 'DEAD', missing: 'MISSING', unknown: 'NOT JUDGED' };
const STATE_ORDER = ['dead', 'missing', 'unknown', 'confirmed'];

// --- Drei Betriebsarten, nicht zwei -------------------------------------
//
// `live`      -- ein Server, ein Katalog, die Knoepfe schreiben.
// `static`    -- die Ein-Datei-Ausgabe (`harness/export_static.py`). Alle
//                Lesewege antworten, aber aus einem EINGEBACKENEN Lauf;
//                geschrieben wird nichts, und die Knoepfe sagen das.
// `recording` -- gar kein Antwortender (werkbank.html per file:// ohne
//                Ausgabe-Schritt). Nur der abgespeicherte Registerstand.
//
// Zwei verschiedene Fragen, die vorher dieselbe waren: "antwortet ein
// Leseweg?" (dann darf gefiltert, sortiert, geblaettert werden) und "darf
// geschrieben werden?". `static` beantwortet die erste mit ja und die
// zweite mit nein -- ohne die Trennung waere die Ein-Datei-Ausgabe auf den
// verkuemmerten Aufzeichnungs-Pfad gefallen und haette Filter, Gruppen und
// Seiten verloren.
const API_MODES = new Set(['live', 'static']);
const apiBacked = () => API_MODES.has(state.mode);
const writesAllowed = () => state.mode === 'live';

// --- Datenzugang --------------------------------------------------------

async function fetchModeInfo() {
  // Kein Server = Aufzeichnung. Der sichere Rueckfall, nie stillschweigend live.
  try {
    const body = await getJson('/api/mode');
    return API_MODES.has(body.mode) ? body : { mode: 'recording' };
  } catch {
    return { mode: 'recording' };
  }
}

// `measure`: `/api/ledger` ist ein ECHTER Lauf gegen GMS (Sekunden,
// API-Aufrufe, Kosten). Beim blossen Oeffnen oder Neuladen der Seite wird
// deshalb `/api/current` geholt -- der Stand, den der Server schon hat:
// der letzte Lauf dieses Prozesses, sonst das juengste Artefakt von der
// Platte, ausdruecklich als Aufzeichnung markiert. Gemessen wird erst,
// wenn jemand einen Knopf drueckt.
async function loadLedger(mode, { measure = false } = {}) {
  if (!API_MODES.has(mode)) {
    return (await fetch('./recorded/ledger.json', { cache: 'no-store' })).json();
  }
  // `/api/ledger` MISST. Das darf nur die Live-Betriebsart -- die
  // Ein-Datei-Ausgabe hat keinen Katalog hinter sich und wuerde hier eine
  // Messung behaupten, die nicht stattfinden kann.
  return getJson(measure && mode === 'live' ? '/api/ledger' : '/api/current');
}

async function loadJudgements(mode) {
  // Aufzeichnung: dieselbe Form wie live, aus `harness/record_replay.py`.
  // Fehlt die Datei, ist das kein Fehler -- es heisst "dieser Aufzeichnung
  // liegt kein Modell-Lauf bei".
  try {
    if (API_MODES.has(mode)) return await getJson('/api/judgements');
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

// Die vier Kennzahlkarten (Referenz: grosse Zahl oben, gedaempfte
// Beschriftung mit Nenner darunter, duenner Balken in der Karte).
//
// Eine Karte je Zustand, IMMER alle vier -- auch bei null. Das ist keine
// Kachelwand ohne Nenner (die verbietet die Spec), sondern die
// Umkehrung: ein Zustand, der nicht vorkommt, ist eine GEMESSENE NULL
// und muss als Ziffer dastehen. Ihn wegzulassen (so war es bis heute:
// `if (!count) continue`) macht aus der gemessenen Null ein Schweigen --
// genau die Verwechslung, gegen die dieses Produkt antritt.
//
// 08.08.: die Karte traegt nur noch, was die Referenz traegt -- grosse
// Zahl, kleine gedaempfte Beschriftung, duenner Balken. Weg sind die
// Zustands-Pille (sie war eine fuenfte Stelle mit Zustandsfarbe, die Spec
// zaehlt vier) und die Notizzeile. Die vier Notizsaetze standen ohnehin
// zweimal auf demselben Schirm: ausfuehrlicher in "What the four verdicts
// mean" zwei Abschnitte tiefer. Der Nenner bleibt -- ohne ihn ist die
// Zahl nicht interpretierbar.
function kpiCard(stateName, count, total) {
  const card = el('div', `kpi kpi--${stateName}`);
  card.append(el('p', 'kpi__value', num(count)));
  const label = el('p', 'kpi__label');
  label.append(el('span', 'kpi__state', STATE_WORD[stateName]));
  label.append(document.createTextNode(` of ${num(total)} checked`));
  card.append(label);
  const bar = el('div', 'kpi__bar');
  const fill = el('span');
  fill.style.width = total ? `${Math.round((count / total) * 100)}%` : '0';
  bar.append(fill);
  card.append(bar);
  return card;
}

// Der Deutungssatz (Referenz: "Groesster Abfall ... Dort ist der
// Engpass"). Er nennt NUR gemessene Groessen und erfindet keine
// Rangfolge, die die Zahlen nicht hergeben.
function overviewReading(l) {
  const total = (l.edges || []).length;
  if (!total) return '';
  const deadDays = (l.edges || []).filter((e) => e.state === 'dead')
    .map((e) => (e.timeline || {}).dead_since_days).filter((d) => d != null);
  const worst = deadDays.length ? Math.max(...deadDays) : null;
  const parts = [];
  // Bewusst NUR die beiden Zustaende, gegen die man etwas TUN kann. Der
  // dritte (`unknown`) steht im Warnstreifen direkt darunter -- ihn hier
  // noch einmal zu erzaehlen waere derselbe Satz an zwei Stellen, und der
  // Deutungssatz soll auf den Engpass zeigen, nicht ihn verdoppeln.
  const problems = [
    ['dead', l.edges_dead || 0],
    ['missing', l.edges_missing || 0],
  ].sort((a, b) => b[1] - a[1]);
  const [top, topN] = problems[0];
  if (topN > 0) {
    const phrase = {
      dead: `${topN} of ${total} connections are declared but carried nothing in the checked`
          + ` window${worst != null ? `, the longest idle for ${plural(worst, 'day', 'days')}` : ''}.`
          + ' That is the removal list — the bottleneck sits there.',
      missing: `${topN} of ${total} connections were measured but never declared.`
          + ' Your lineage is incomplete exactly there.',
    }[top];
    parts.push(`Biggest thing to act on: ${phrase}`);
    const other = problems[1];
    if (other && other[1] > 0) {
      parts.push(other[0] === 'missing'
        ? `A further ${other[1]} run undeclared.`
        : `A further ${other[1]} are declared but dead.`);
    }
  } else if ((l.edges_unknown || 0) < total) {
    parts.push(`Nothing to act on: every judged connection of the ${total} checked is confirmed`
             + ' by measured traffic.');
  }
  return parts.join(' ');
}

function renderOverview() {
  const l = state.ledger;
  const host = document.getElementById('run-verdict');
  const reading = document.getElementById('kpis-reading');
  host.innerHTML = '';
  reading.textContent = '';

  if (!l || !(l.edges || []).length) {
    // Auch die Uebersicht bekommt den erklaerten Leerzustand, nicht nur
    // einen Halbsatz: was fehlt, warum, und der Knopf dazu.
    host.append(blankNode(l ? {
      what: 'The check ran and found no connection to judge.',
      why: 'That is a measured zero: the observed source tables declare no'
         + ' upstream and no query joined them. It is not a missing measurement.',
    } : {
      what: 'Nothing has been measured yet.',
      why: state.emptyReason
         || 'No run has left an artifact yet, and none is stored on disk.'
         + ' Nothing is shown rather than something invented.',
      action: 'run-ledger',
    }));
  } else {
    const total = l.edges.length;
    host.append(
      kpiCard('confirmed', l.edges_confirmed, total),
      kpiCard('dead', l.edges_dead, total),
      kpiCard('missing', l.edges_missing, total),
      kpiCard('unknown', l.edges_unknown, total));
    reading.textContent = overviewReading(l);
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
      + (l.run_seconds != null ? ` · ${l.run_seconds}s` : '')
    : 'never';

  // Deutungssatz der zweiten Kennzahlgruppe: was die Abdeckung fuer die
  // Zahlen darueber bedeutet. Ohne ihn ist "454 of 513" eine Zahl, die
  // sich jeder Leser selbst deuten muss.
  const qr = document.getElementById('quality-reading');
  if (!l) {
    qr.textContent = '';
  } else {
    const totalEdges = (l.edges || []).length;
    const measured = (l.edges || []).filter((e) => (e.coverage || {}).buckets_seen > 0).length;
    const gap = totalEdges - measured;
    qr.textContent = gap > 0
      ? `Coverage is the ceiling for every number above: ${gap} of ${totalEdges} connections`
        + ' had no usage window, so no verdict about them could rest on a measurement.'
        + ' That gap is reported, not filled.'
      : `Every one of the ${totalEdges} checked connections had at least one usage window,`
        + ' so no verdict above rests on an absent measurement.';
  }

  // Die Seitenleiste traegt den Systemzustand unten (Referenz) und die
  // Zahl an jedem Navigationspunkt.
  document.getElementById('sidebar-last-run').textContent = l
    ? `${new Date(l.generated_at_ms).toLocaleTimeString()} · ${(l.edges || []).length}`
    : 'never';
  // Die Zahl an "Connections" steht schon hier fest -- sie ist die
  // Kantenzahl des gezeigten Laufs. Sie erst beim Oeffnen des Bereichs zu
  // setzen liesse in der Seitenleiste einen Gedankenstrich stehen, obwohl
  // die Zahl bekannt ist ("nicht gezaehlt" waere unwahr).
  setNavCount('nav-count-connections', l ? (l.edges || []).length : null,
              'checked connections');

  document.getElementById('status-run').textContent = l
    ? `last run ${new Date(l.generated_at_ms).toLocaleTimeString()}`
    : 'no run yet';
  document.getElementById('status-coverage').textContent = l
    ? `coverage ${l.coverage_buckets_seen || 0} windows / ${l.coverage_days_span || 0} days`
    : 'coverage: not measured';
  document.getElementById('status-abstention').textContent = (j && j.calls)
    ? `abstention ${(j.judgements || []).filter((x) => !x.used_model).length}/${j.calls}`
    : 'abstention: not measured';

  renderNotice();
}

// Zwei Saetze, die nie verschwinden duerfen -- auch nicht bei schmalem
// Fenster, auch nicht in einem anderen Bereich.
//
// (1) Zeigt die Seite gerade einen AUFGEZEICHNETEN Lauf? Der Server
//     startet seit 07.08. mit dem juengsten Artefakt von der Platte,
//     damit die Konsole nicht leer aussieht. Ein alter Stand, der wie
//     eine frische Messung aussieht, waere aber genau die Behauptung
//     ohne Beleg, gegen die dieses Projekt antritt -- also steht Herkunft
//     und Zeitpunkt hier, ueber allem, in jedem Bereich.
// (2) Sind die Daten eingespielt? (`seeded_statement` aus dem Manifest.)
function renderNotice() {
  const l = state.ledger;
  const bar = document.getElementById('notice');
  const replay = document.getElementById('replay-note');
  const seeded = document.getElementById('seeded-note');
  if (!bar) return;

  const isReplay = !!(l && l.recording);
  replay.hidden = !isReplay;
  if (isReplay) {
    // Eine Zeile, kein Absatz (08.08.). Dieselben Tatsachen -- dass es
    // eine Aufzeichnung ist, wann sie gemessen wurde, aus welchem
    // Artefakt --, nur ohne die beiden Saetze, die daneben schon
    // dastehen: "nicht live" sagt das Wort "Recorded" selbst, und was
    // "Run a check" tut, steht neben dem Knopf.
    replay.innerHTML = '';
    const when = l.recorded_at_iso ? new Date(l.recorded_at_iso) : new Date(l.generated_at_ms);
    replay.append(
      el('strong', null, state.mode === 'static'
        ? 'Exported single file · recorded run' : 'Recorded run'),
      el('span', null, ` · measured ${when.toLocaleString()}`
        + (l.recorded_from ? ` · ${l.recorded_from}` : '')
        + (l.focus_mismatch
           ? ' · covers tables this server does not currently observe'
             + ' (renamed after the recording)'
           : '')));
  }

  const statement = (l && l.seeded)
    ? (l.seeded_statement || state.info.seeded_statement
       || 'Seeded demonstration data — not real warehouse usage.')
    : '';
  seeded.hidden = !statement;
  seeded.textContent = statement;

  bar.hidden = replay.hidden && seeded.hidden;
}

// --- Bereich 2: Verbindungen -------------------------------------------

function filterQuery() {
  const f = state.filters;
  const p = new URLSearchParams();
  if (f.states.size) p.set('state', [...f.states].join(','));
  if (f.platform) p.set('platform', f.platform);
  if (f.database) p.set('database', f.database);
  if (f.domain) p.set('domain', f.domain);
  if (f.owner) p.set('owner', f.owner);
  if (f.idle) p.set('idle', f.idle);
  if (f.table) p.set('table', f.table);
  if (f.q) p.set('q', f.q);
  if (f.judged) p.set('judged', '1');
  if (f.abstained) p.set('abstained', '1');
  // Gruppiert heisst: der Server sortiert nach Plattform/Datenbank. Eine
  // Gruppierung ueber einer FREMDEN Sortierung waere keine -- die Gruppe
  // zerfiele ueber mehrere Seiten und ihre Kopfzeile erschiene mehrfach.
  p.set('sort', f.grouped ? 'group' : f.sort);
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

// --- Die Spalte "Zuletzt belegt" ---------------------------------------
//
// Gemessener Widerspruch (07.08., 513-Kanten-Register): 32 der 73 TOTEN
// Kanten zeigten hier ein frisches Datum -- "7 August (today)". Technisch
// richtig, in der Zeile aber unlesbar: tot, aber heute gemessen? Das
// Datum gehoert den TABELLEN, das Urteil gehoert der KANTE, und die
// Spalte zeigte nur das eine.
//
// Dazu kam ein zweiter, groesserer Fehlgriff: 55 Zeilen (41 tote, 12
// bestaetigte, 2 fehlende) hatten sehr wohl Messfenster, in denen JEDES
// Fenster NULL gemessen hat -- und die Spalte schrieb "not measured".
// Eine gemessene Null als fehlende Messung auszugeben ist genau der
// Verstoss gegen die Null-Regel, gegen den dieses Produkt antritt, nur in
// der eigenen Tabelle.
//
// Deshalb drei Faelle, die verschieden aussehen, und der Server sagt
// welcher (`row.measurement`), damit der Browser nichts ableiten muss:
//
//   traffic (399) -- es gibt ein Datum. Bei einer TOTEN Kante steht davor,
//                    was die Kante betrifft, und das Datum darunter als
//                    das, was es ist: Verkehr der Tabellen.
//   zero    ( 55) -- Fenster liefen, alle massen null. Gemessene Null.
//   none    ( 59) -- gar kein Fenster. Erst hier ist "nicht gemessen" wahr.
function lastMeasuredCell(row) {
  const td = el('td', 'lastcell');
  const days = row.window_days;
  const span = days ? `${days} days` : 'the checked window';

  if (row.measurement === 'none') {
    td.append(el('span', 'notmeasured', 'not measured'));
    td.append(el('span', 'lastcell__why', 'no usage window in the catalog'));
    return td;
  }

  if (row.measurement === 'zero') {
    // Die Ziffer 0 steht da, nicht ein leeres Feld: gemessene Null.
    td.append(el('span', 'numbers', `0 traffic in ${plural(row.buckets_seen, 'window', 'windows')}`));
    td.append(el('span', 'lastcell__why', 'measured zero — not a gap'));
    return td;
  }

  const stamp = `${dayStamp(row.last_covered_ms)} (${agoPhrase(row.dead_since_days)})`;
  if (row.dead_kind === 'no-pair') {
    // Die Aussage der Zeile betrifft die KANTE, nicht die Tabellen.
    td.append(el('span', 'lastcell__edge', `no query joined them in ${span}`));
    td.append(el('span', 'lastcell__why', `both tables active · last ${dayStamp(row.last_covered_ms)}`));
    return td;
  }
  td.append(el('span', 'numbers', stamp));
  return td;
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

  if (!apiBacked()) return renderConnectionsLocal();

  let data;
  try {
    data = await getJson(`/api/connections?${filterQuery()}`);
  } catch (err) {
    body.innerHTML = '';
    body.append(blankRow(6, {
      what: 'The server did not answer.',
      why: `${err.message}. Nothing is shown rather than something invented —`
         + ' a failed request is not an absence of connections.',
    }));
    return;
  }

  renderStateChips(data.state_counts);
  fillFacets(data.facets);

  // `unaged`: Kanten, die der Stillstands-Filter mangels Messung nicht
  // beurteilen kann. Sie werden GENANNT statt stillschweigend
  // weggefiltert -- ein Filter, der etwas wortlos verschwinden laesst, ist
  // derselbe Fehlertyp wie eine leere Ansicht ohne Grund.
  document.getElementById('connections-count').textContent = data.has_run
    ? `${data.total} of ${data.total_unfiltered} checked connections`
      + (data.unaged ? ` · ${data.unaged} never measured, so they cannot be aged` : '')
      + (state.catalogTotal ? ` · catalog holds ${num(state.catalogTotal)} datasets` : '')
    : 'no check has run yet';
  setNavCount('nav-count-connections',
    data.has_run ? data.total_unfiltered : null, 'checked connections');

  renderActiveFilters();
  renderPager('connections-pager', data.start, data.count, data.total, (start) => {
    state.filters.start = start;
    renderConnections();
  });

  body.innerHTML = '';
  if (!data.rows.length) {
    // `has_run: false` darf NIE zu einer wortlosen leeren Tabelle fuehren
    // -- genau daran ist die Konsole am 07.08. gescheitert. Der Grund
    // kommt vom Server mit (`empty_reason`), damit hier keine zweite,
    // moeglicherweise falsche Erklaerung erfunden wird.
    body.append(blankRow(6, data.has_run ? {
      what: 'No connection matches these filters.',
      why: `${data.total_unfiltered} connection(s) were checked in this run.`
         + (data.unaged
             ? ` ${data.unaged} of them were never measured, so no idle time can be`
               + ' computed for them — they are not hidden by accident, they are'
               + ' unanswerable for this filter.'
             : '')
         + ' Clear a filter above to see them.',
    } : {
      what: 'No connection has been checked yet.',
      why: data.empty_reason
         || 'Nothing is shown rather than something invented.',
      action: data.fix_action || 'run-ledger',
    }));
    return;
  }

  // Gruppenzeilen (Referenz): Plattform · Datenbank, mit den Summen der
  // GEFILTERTEN Menge (vom Server, `console_api.groups`) und dazu, wie
  // viele davon auf dieser Seite stehen. Eine Gruppenzeile, die nur die
  // 50 sichtbaren zaehlt, waere eine Summe, die nicht aufgeht.
  // Derselbe Trenner wie in `console_api.GROUP_SEP` -- ein Steuerzeichen,
  // damit ein Punkt im Datenbanknamen nie zwei Gruppen zusammenwirft.
  const groupKey = (ref) => `${ref.platform}\x1f${ref.database}`;
  const groups = new Map((data.groups || []).map((g) => [g.key, g]));
  const onPage = new Map();
  if (state.filters.grouped) {
    for (const row of data.rows) {
      const key = groupKey(row.from);
      onPage.set(key, (onPage.get(key) || 0) + 1);
    }
  }
  let lastGroup = null;

  for (const row of data.rows) {
    const key = groupKey(row.from);
    if (state.filters.grouped && key !== lastGroup) {
      lastGroup = key;
      body.append(groupRow(groups.get(key), row.from, onPage.get(key) || 0));
    }

    const tr = el('tr', `is-selectable${state.filters.grouped ? ' is-child' : ''}`);
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
    // ist ein WORT -- nie ein leeres Feld. Und bei einer toten Kante mit
    // Tabellenverkehr spricht die Zelle ueber die KANTE, nicht ueber die
    // Tabellen (siehe lastMeasuredCell).
    tr.append(lastMeasuredCell(row));

    const j = el('td');
    const tag = { model: 'model cited', abstained: 'abstained', none: 'not asked' }[row.judgement];
    j.append(el('span', `judge-tag judge-tag--${row.judgement}`, tag));
    tr.append(j);

    tr.addEventListener('click', () => selectEdge(row.edge));
    body.append(tr);
  }
}

// Die fette Gruppenzeile. Ohne Summen vom Server wird KEINE erfunden:
// dann nennt sie nur, was sie weiss (die Zeilen dieser Seite) und sagt
// das auch -- eine Summe ohne Beleg ist auf dieser Werkbank teurer als
// keine.
function groupRow(group, ref, pageCount) {
  const tr = el('tr', 'grouprow');
  const td = el('td');
  td.colSpan = 6;
  const head = el('div', 'grouprow__head');
  head.append(el('span', 'grouprow__name', ref.database || 'unknown database'));
  head.append(el('span', 'grouprow__where', ref.platform || 'unknown platform'));
  const sums = el('div', 'grouprow__sums');
  if (group) {
    sums.append(el('span', 'grouprow__sum',
      `${num(group.total)} connections`));
    for (const s of STATE_ORDER) {
      const seg = el('span', `grouprow__sum grouprow__sum--${s}`);
      seg.append(el('b', null, num(group[s])), el('span', null, STATE_WORD[s].toLowerCase()));
      sums.append(seg);
    }
    if (pageCount < group.total) {
      sums.append(el('span', 'grouprow__sum', `${num(pageCount)} on this page`));
    }
  } else {
    sums.append(el('span', 'grouprow__sum',
      `${num(pageCount)} on this page — no group total was measured`));
  }
  head.append(sums);
  td.append(head);
  tr.append(td);
  return tr;
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
  setNavCount('nav-count-connections', edges.length, 'connections in this recording');
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
    // Dieselbe Zelle wie im Server-Weg -- die drei Sorten Messung und die
    // zwei Sorten `dead` duerfen nicht davon abhaengen, ob gerade ein
    // Server antwortet. Die Herleitung entspricht
    // console_api.measurement_kind/DEAD_KIND; sie ist hier nachgebaut,
    // weil eine Aufzeichnung ohne Server keinen hat, der sie mitliefert.
    const measureKind = !measured ? 'none' : (tl.last_covered_ms ? 'traffic' : 'zero');
    tr.append(lastMeasuredCell({
      measurement: measureKind,
      dead_kind: e.state === 'dead'
        ? ({ zero: 'no-window', traffic: 'no-pair' }[measureKind] || '') : '',
      buckets_seen: cov.buckets_seen || 0,
      window_days: cov.window_days || (e.evidence || {}).window_days,
      last_covered_ms: tl.last_covered_ms,
      dead_since_days: tl.dead_since_days,
    }));
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
    body.append(blankRow(6, {
      what: 'No connection matches these filters.',
      why: `This recording holds ${((state.ledger || {}).edges || []).length} connection(s).`
         + ' Clear a filter above to see them.',
    }));
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

// Jede Zahl in einer Auswahlliste ist die Anzahl der ZEILEN, die man nach
// dem Anklicken sieht (console_api.facets). Bis 07.08. zaehlte sie
// Kanten-ENDEN: `probate_seedlab` stand mit "8" da und lieferte 4 Zeilen.
function fillFacets(facets) {
  if (!facets) return;
  const gov = facets.governance || {};
  for (const [id, list, key] of [['filter-platform', facets.platforms, null],
                                 ['filter-database', facets.databases, 'database'],
                                 ['filter-domain', facets.domains, 'domain'],
                                 ['filter-owner', facets.owners, 'owner']]) {
    const sel = document.getElementById(id);
    const rows = list || [];
    // `probate_seedlab` heisst so, weil es das Labor IST -- der Zusatz
    // kommt aus den Artefakten (console_api.lab_notes), nicht aus einem
    // getippten Satz. Ohne ihn sieht der Name in einer Liste aus fuenf
    // `probate_demo_*` wie ein Ausrutscher im Namensschema.
    const stamp = rows.map((f) => `${f.value}:${f.count}:${f.note || ''}`).join('|');
    if (sel.dataset.filled !== stamp) {
      const current = sel.value;
      sel.innerHTML = '<option value="">all</option>';
      for (const f of rows) {
        const label = f.label || f.value;
        const o = el('option', null, f.note ? `${label} — ${f.note} (${f.count})`
                                            : `${label} (${f.count})`);
        o.value = f.value;
        if (f.note) o.title = (facets.database_notes || {})[f.value]?.note || f.note;
        sel.append(o);
      }
      sel.value = current;
      sel.dataset.filled = stamp;
    }
    if (key) {
      const map = state.facetLabels[key];
      map.clear();
      for (const f of rows) map.set(f.value, f.label || f.value);
    }
    // Domaene/Besitzer ohne gemessenes Artefakt: gesperrt, nicht leer
    // angeboten. Eine offene Liste, die nur "all" kann, behauptet, es gebe
    // nichts zu filtern -- das ist eine Aussage, die niemand gemessen hat.
    if (id === 'filter-domain' || id === 'filter-owner') {
      sel.disabled = !gov.measured;
    }
  }

  const note = document.getElementById('filters-note');
  if (!gov.measured) {
    note.hidden = false;
    note.className = 'filters__note filters__note--gap';
    note.textContent = gov.reason || 'Domain and owner were never looked up.';
  } else {
    note.hidden = false;
    note.className = 'filters__note';
    note.textContent =
      `Domain and owner read from the catalog for ${num(gov.tables_looked_up)} tables`
      + ` — ${num(gov.tables_with_domain)} carry a domain, ${num(gov.tables_with_owner)} an owner`
      + `. “Idle for at least” counts days since this connection last carried anything;`
      + ` connections that were never measured cannot be aged and are reported separately.`;
  }
}

function renderActiveFilters() {
  const host = document.getElementById('active-filters');
  host.innerHTML = '';
  const f = state.filters;
  const chips = [];
  for (const s of f.states) chips.push([`verdict: ${STATE_WORD[s]}`, () => f.states.delete(s)]);
  const labelled = (key, value) => state.facetLabels[key].get(value) || value;
  if (f.platform) chips.push([`platform: ${f.platform}`, () => { f.platform = ''; }]);
  if (f.database) chips.push([`database: ${labelled('database', f.database)}`,
                              () => { f.database = ''; }]);
  // Der Chip zeigt die Beschriftung, nicht die URN -- "Finance
  // (probate_demo)" statt "urn:li:domain:probate_demo.finance".
  if (f.domain) chips.push([`domain: ${labelled('domain', f.domain)}`, () => { f.domain = ''; }]);
  if (f.owner) chips.push([`owner: ${labelled('owner', f.owner)}`, () => { f.owner = ''; }]);
  if (f.idle) chips.push([`idle ≥ ${plural(Number(f.idle), 'day', 'days')}`,
                          () => { f.idle = ''; }]);
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

const IDLE_PRESETS = new Set(['7', '30', '90']);

function syncControls() {
  const f = state.filters;
  document.getElementById('filter-platform').value = f.platform;
  document.getElementById('filter-database').value = f.database;
  document.getElementById('filter-domain').value = f.domain;
  document.getElementById('filter-owner').value = f.owner;
  document.getElementById('filter-q').value = f.q;
  document.getElementById('filter-judged').checked = f.judged;
  document.getElementById('filter-abstained').checked = f.abstained;
  document.getElementById('filter-grouped').checked = f.grouped;
  // Solange gruppiert wird, bestimmt die Gruppe die Reihenfolge. Die
  // Sortier-Auswahl wird deshalb GESPERRT und sagt warum -- ein
  // Bedienelement, das sichtbar nichts tut, ist eine Luege ueber die
  // Ansicht (dieselbe Regel wie bei den gesperrten Facetten).
  const sortSel = document.getElementById('filter-sort');
  sortSel.disabled = f.grouped;
  sortSel.title = f.grouped
    ? 'Grouping sets the order: platform · database, then verdict.'
      + ' Uncheck “Group by” to sort freely.'
    : '';

  // "eigener" Zeitraum: die Auswahlliste steht auf `custom`, das Zahlenfeld
  // traegt den Wert. Ein Wert, der zufaellig 7/30/90 ist, waehlt den
  // Voreinsteller -- sonst stuenden zwei Bedienelemente fuer denselben
  // Zustand.
  const sel = document.getElementById('filter-idle');
  const box = document.getElementById('filter-idle-custom-field');
  const inp = document.getElementById('filter-idle-custom');
  if (!f.idle) {
    sel.value = '';
    box.hidden = true;
  } else if (IDLE_PRESETS.has(f.idle)) {
    sel.value = f.idle;
    box.hidden = true;
  } else {
    sel.value = 'custom';
    box.hidden = false;
    if (inp.value !== f.idle) inp.value = f.idle;
  }
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

// Ein Tabellenname ist ein BEZEICHNER, kein Wort. Bis 10.08. lief er im
// Satz der Detailspalte in derselben Schrift, demselben Gewicht und
// derselben Farbe mit -- bei Namen wie `mart_spend_efficiency_by_market`
// entsteht daraus ein Block, in dem niemand sieht, wo der Name aufhoert und
// der Satz anfaengt. Joel woertlich: "man sieht nicht, was ist eine Tabelle,
// Namen oder so, was ist Normaltext".
//
// Ausgezeichnet wird deshalb wie ein Code-Schnipsel im Fliesstext:
// Festbreitenschrift plus ein sehr dezenter Grund. KEINE Farbe aus der
// Zustandspalette -- Rot bleibt den vier Stellen vorbehalten, die die Spec
// nennt (Punkt in der Tabelle, Chip im Filter, Wort in der Detailspalte,
// Balken im Verlauf).
function dsNameNode(ref) {
  const n = el('code', 'dsname', ref.table || ref.urn || '');
  // Der Ort im Katalog haengt am Namen, statt den Satz zu verlaengern --
  // "ein Name ohne seinen Ort ist bei 5.594 Datensaetzen wertlos" (Spec).
  const where = [ref.platform, ref.qualified].filter(Boolean).join(' · ');
  if (where) n.title = where;
  else if (ref.urn) n.title = ref.urn;
  return n;
}

// Der Satz als TEILE: Zeichenketten sind Fliesstext, Objekte sind
// Datensatz-Verweise. So steht die Auszeichnung an genau einer Stelle
// (`sentenceInto`) und kann in keiner Satzvariante vergessen werden.
function sentenceParts(edge) {
  const from = splitUrnClient(edge.upstream);
  const to = splitUrnClient(edge.downstream);
  const cov = edge.coverage || {}, tl = edge.timeline || {};
  const series = tl.series || [];
  const traffic = series.reduce((a, [, n]) => a + n, 0);
  const queries = ((edge.evidence || {}).query_urns || []).length;
  const buckets = cov.buckets_seen || 0;

  if (edge.state === 'confirmed') {
    return [to, ' draws from ', from, ' according to the catalog, and'
      + ` ${plural(queries, 'query touches', 'queries touch')} both tables. `,
      to, ` ran ${plural(traffic, 'query', 'queries')} across`
      + ` ${plural(buckets, 'measured window', 'measured windows')},`
      + ` most recently ${agoPhrase(tl.dead_since_days)}. The connection is alive.`];
  }
  if (edge.state === 'dead') {
    const last = dayStamp(tl.last_covered_ms);
    return [to, ' draws from ', from, ' according to the catalog.'
      + ` Across ${plural(buckets, 'measured window', 'measured windows')}`
      + ` (${plural(cov.days_span || 0, 'day', 'days')}), not one query touched both tables`
      + (traffic ? `, although the tables themselves were used (${traffic} queries)` : '')
      + `.${last ? ` Last measured traffic: ${last}.` : ''} The connection is dead.`];
  }
  if (edge.state === 'missing') {
    return [`${plural(queries, 'query joins', 'queries join')} `, from, ' and ', to,
      ', but nobody ever declared the connection in the catalog.'
      + ' Your lineage is incomplete here.'];
  }
  return ['There is no usage data for ', to, ' at all'
    + (cov.reason ? ` — ${humanReason(cov.reason)}` : '')
    + '. We do not guess. This is the case other tools report as “unused”.'];
}

// Baut aus den Teilen einen Absatz. Jeder Nicht-String wird zum
// ausgezeichneten Bezeichner -- es gibt keinen Weg, einen Namen roh in den
// Satz zu bekommen.
function sentenceInto(node, parts) {
  for (const part of parts) {
    node.append(typeof part === 'string' ? document.createTextNode(part) : dsNameNode(part));
  }
  return node;
}

// Rohe URNs muessen bleiben -- ein Beleg, den man nicht kopieren kann, ist
// keiner. Gekuerzt oder mit "…" abgeschnitten waeren sie wertlos. Sie
// duerfen die Spalte aber nicht beherrschen: vier Zeilen
// `urn:li:dataset:(urn:li:dataPlatform:bigquery,…,PROD)` haben bis 10.08.
// genau das getan. Darum: hinter EINER Zeile, vollstaendig, mit
// Umbruchgelegenheiten an den Trennzeichen.
const URN_BREAK_AFTER = new Set([':', ',', '.', '(', ')']);

function urnValueNode(urn) {
  const code = el('code', 'urn__value');
  const text = String(urn || '');
  code.title = text;
  // `<wbr>` ist eine GELEGENHEIT, kein Zeichen: beim Kopieren kommt der
  // URN Zeichen fuer Zeichen so heraus, wie er in den Daten steht.
  let buf = '';
  for (const ch of text) {
    buf += ch;
    if (URN_BREAK_AFTER.has(ch)) {
      code.append(document.createTextNode(buf), document.createElement('wbr'));
      buf = '';
    }
  }
  if (buf) code.append(document.createTextNode(buf));
  return code;
}

function urnsNode(edge) {
  const rows = [['upstream', edge.upstream], ['downstream', edge.downstream]];
  for (const q of ((edge.evidence || {}).query_urns || [])) rows.push(['query', q]);

  const box = el('details', 'urns');
  box.append(el('summary', 'urns__summary',
    `Show the raw identifiers (${plural(rows.length, 'URN', 'URNs')})`));
  box.append(el('p', 'urns__note',
    'Unabridged, exactly as the catalog stores them — paste one into DataHub'
    + ' or an API call and you land on the same object we measured.'));
  for (const [role, urn] of rows) {
    const line = el('div', 'urn');
    line.append(el('span', 'urn__role', role));
    line.append(urnValueNode(urn));
    box.append(line);
  }
  return box;
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
  body.append(sentenceInto(el('p', 'detail__sentence'), sentenceParts(edge)));

  const help = stateHelpNode(edge.state);
  if (help) { help.className = 'block__text'; body.append(help); }

  const declared = el('div', 'block');
  declared.append(el('p', 'block__label block__label--declared', 'Declared — what the catalog claims'));
  const src = (edge.evidence || {}).source || '';
  declared.append(sentenceInto(el('p', 'block__text'), src.includes('declared lineage')
    ? [to, ' lists ', from, ' as an upstream. Nobody has re-checked it since it was written.']
    : ['Nobody wrote this connection into the catalog.'
       + ' It exists only in what the queries did.']));
  declared.append(urnsNode(edge));
  body.append(declared);

  body.append(sparkNode(edge));
  body.append(judgementNode(edge));
}

// --- Bereich 3: Katalog -------------------------------------------------

async function renderCatalog() {
  const host = document.getElementById('catalog-tree');
  const countEl = document.getElementById('catalog-count');
  if (!apiBacked()) {
    blankInto(host, {
      what: 'The catalog tree needs a live instance.',
      why: 'A recording carries only the connections it measured, not the'
         + ' catalog it measured them in. Start the bench against a running'
         + ' DataHub (python -m ui.serve) to browse the tree.',
    });
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
    blankInto(host, {
      what: 'The catalog did not answer.',
      why: `${err.message}. A failed request is not an empty catalog —`
         + ' nothing is listed rather than something invented.',
    });
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
  if (!data.rows.length) {
    blankInto(host, {
      what: 'No dataset matches this search.',
      why: data.empty_reason
         || `The catalog answered and holds ${num(data.total)} dataset(s) in total.`
         + ' This is a measured zero for this search, not a missing measurement.',
    });
    return;
  }
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
    if (apiBacked()) data = await getJson('/api/runs');
  } catch { /* leere Liste ist unten ein eigener, benannter Zustand */ }

  setNavCount('nav-count-runs', data.runs.length, 'run artifacts on disk');

  if (!data.runs.length) {
    body.append(blankRow(6, apiBacked() ? {
      what: 'No run artifact on disk yet.',
      why: data.empty_reason
         || 'A run only counts here once it has left a file under harness/runs —'
         + ' nothing is listed from memory.',
      action: data.fix_action || 'run-ledger',
    } : {
      what: 'Run history needs a live instance.',
      why: 'This list reads the artifacts on disk through the server;'
         + ' a recording opened as a file cannot see them.',
    }));
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
  let meta = {};
  if (apiBacked()) {
    try {
      meta = await getJson(`/api/evidence?q=${encodeURIComponent(q)}`);
      items = meta.items;
    } catch (err) {
      // Eine gescheiterte Abfrage ist keine Abwesenheit von Belegen.
      blankInto(host, {
        what: 'The server did not answer.',
        why: `${err.message}. Nothing is listed rather than something invented.`,
      });
      countEl.textContent = 'not loaded';
      return;
    }
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
  // Die Zahl in der Seitenleiste gilt fuer die UNGEFILTERTE Menge -- eine
  // Suche darf die Navigation nicht umschreiben, sonst behauptet sie eine
  // andere Gesamtmenge, als es gibt.
  if (!q) setNavCount('nav-count-evidence', items.length, 'pieces of evidence in this run');
  if (!items.length) {
    const searching = !!q;
    blankInto(host, searching ? {
      what: 'No evidence matches that search.',
      why: 'Clear the search field above to see everything this run collected.',
    } : {
      what: 'No evidence collected yet.',
      why: meta.empty_reason
         || 'Evidence appears once a check has run: query URNs, usage windows,'
         + ' verbatim quotes — and the gaps where there is nothing.',
      action: meta.fix_action || (meta.has_run === false ? 'run-ledger' : ''),
    });
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

const LOG_MAX_LINES = 200;

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

  // Gedeckelt: das Protokoll wuchs unbegrenzt im DOM. Bei einer Demo von
  // zwanzig Minuten faellt das nicht auf, bei einem Server, der einen Tag
  // laeuft, ist es ein Leck -- und ein DOM, das nur waechst, macht jedes
  // Neuzeichnen teurer. Die aeltesten Zeilen fallen unten weg; wer sie
  // braucht, liest sie im Artefakt, nicht im Bildschirmprotokoll.
  while (host.childElementCount > LOG_MAX_LINES) host.lastElementChild.remove();
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
  // Der Systemzustand steht seit dem Referenz-Umbau unten in der
  // Seitenleiste, nicht mehr als Abzeichen in der Kopfzeile. Der volle
  // Satz ("buttons write to ...") wandert in den title -- die Spalte ist
  // 210px breit, ein Satz waere dort abgeschnitten und damit unwahr.
  const badge = document.getElementById('mode-badge');
  badge.dataset.mode = info.mode;
  badge.textContent = { live: 'live — buttons write',
                        static: 'single file — nothing writes',
                        recording: 'recording' }[info.mode] || info.mode;
  badge.title = { live: `Live — buttons write to ${info.gms}`,
                  static: 'A single exported file. Every view reads a recorded'
                        + ' run baked into this document; no catalog is behind it.',
                  recording: 'Recording — replaying a stored run, buttons disabled',
                }[info.mode] || '';
  const instance = document.getElementById('instance-label');
  instance.textContent = { live: String(info.gms || '').replace(/^https?:\/\//, ''),
                           static: 'no instance — exported copy',
                           recording: 'recorded run' }[info.mode] || 'unknown';
  instance.title = info.mode === 'live' ? info.gms : 'no live instance behind this page';
  // Was ein Lauf messen WUERDE -- nicht, was `--focus` nennt. Bis heute
  // stand hier "4 observed source tables", waehrend 513 Kanten auf dem
  // Schirm waren und der Knopf tatsaechlich nur vier gemessen hat. Die
  // Statusleiste hat den Defekt also mitgeteilt, ohne dass ihn jemand
  // lesen konnte.
  document.getElementById('status-instance').textContent = info.mode === 'live'
    ? `${info.gms} · a check measures ${num(info.scope_focuses)} source tables`
      + (info.scope_edges != null ? ` / ${num(info.scope_edges)} connections` : '')
    : info.mode === 'static'
      ? `exported single file · ${info.recorded_from || 'recorded run'}`
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

// --- Die Ein-Datei-Ausgabe sagt, dass sie nicht schreiben kann ----------
//
// Ein Knopf, der nichts tut und dabei aussieht, als taete er etwas, ist
// genau die stille Falschaussage, gegen die dieses Werkzeug antritt. Die
// schreibenden Knoepfe sind hier deshalb nicht heimlich wirkungslos,
// sondern SICHTBAR ausser Betrieb -- mit dem Satz, warum, an der Karte,
// zu der sie gehoeren.
function applyStaticMode(info) {
  const card = document.getElementById('controls');
  if (card) {
    const why = el('p', 'offline-note');
    why.append(
      el('strong', null, 'These buttons are out of service in this copy.'),
      document.createTextNode(
        ' This copy has no catalog behind it — run it locally'
        + ' (python -m ui.serve) to write. Everything below is the recorded run'
        + (info && info.recorded_from ? ` from ${info.recorded_from}` : '')
        + ', read exactly as the server would read it.'));
    card.parentNode.insertBefore(why, card);
    for (const btn of card.querySelectorAll('button')) {
      btn.disabled = true;
      btn.title = 'no catalog behind this copy — run it locally to write';
    }
  }
  const run = document.getElementById('run-check');
  if (run) run.title = 'no catalog behind this copy — run it locally to measure';

  // Der Katalogbereich sagt in der Live-Fassung "Everything the instance
  // holds". Diese Datei hat keine Instanz -- sie traegt die Tabellen, die
  // der aufgezeichnete Lauf beruehrt hat. Die Ueberschrift stehen zu
  // lassen waere die bequemste Art, mehr zu behaupten als da ist.
  const note = info && info.catalog_note;
  if (note) {
    const caption = document.querySelector('.pane[data-view="catalog"] .pane__caption');
    if (caption) caption.textContent = note;
  }
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = theme === 'dark' ? 'Light theme' : 'Dark theme';
  try { localStorage.setItem('werkbank-theme', theme); } catch { /* privater Modus */ }
}

const VIEWS = ['overview', 'connections', 'catalog', 'runs', 'evidence'];

function showView(name) {
  state.view = name;
  // Der Bereich steht in der Adresse. Eine Enterprise-Konsole, deren
  // Bereiche man niemandem schicken kann, ist ein Schaufenster -- und der
  // Nachweis "so sieht Bereich X bei 860px aus" laesst sich sonst nur von
  // Hand fuehren, nicht wiederholbar.
  if (location.hash.slice(1) !== name) {
    history.replaceState(null, '', `#${name}`);
  }
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
  renderRunScope();
  if (state.view === 'connections') renderConnections();
  if (state.view === 'evidence') renderEvidence();
  renderDetail();
}

async function refresh({ measure = false } = {}) {
  try {
    const body = await loadLedger(state.mode, { measure });
    // `/api/current` antwortet mit `has_run: false` und sagt AUSDRUECKLICH,
    // warum nichts da ist. Die Uebersicht reicht diesen Satz weiter, statt
    // einen eigenen zu erfinden.
    if (body && body.has_run === false) {
      state.ledger = null;
      state.emptyReason = body.empty_reason || '';
    } else {
      state.ledger = body;
      state.emptyReason = '';
    }
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
let judgeFingerprint = null;

// Jeder Takt zeichnete bisher Uebersicht UND Verbindungstabelle neu --
// auch dann, wenn das Modell noch am selben Urteil rechnete und sich
// nichts geaendert hatte. Ein Neuzeichnen der Tabelle ist zusaetzlich ein
// `/api/connections`-Aufruf; zwei Minuten Modelllauf waren so ~48
// ueberfluessige Anfragen und ~48 vollstaendige Neuaufbauten des DOM.
// Jetzt: nur bei echter Aenderung, und nur, solange jemand hinsieht.
function judgeStamp(j) {
  if (!j) return 'none';
  return JSON.stringify([j.running, j.calls, j.seconds, j.cost_usd,
                          (j.judgements || []).length]);
}

function watchJudgements() {
  if (judgePoll) return;
  judgeFingerprint = judgeStamp(state.judge);
  judgePoll = setInterval(async () => {
    if (document.visibilityState !== 'visible') return;
    state.judge = await loadJudgements('live');
    const stamp = judgeStamp(state.judge);
    if (stamp !== judgeFingerprint) {
      judgeFingerprint = stamp;
      renderOverview();
      if (state.view === 'connections') renderConnections();
      if (state.view === 'evidence') renderEvidence();
      renderDetail();
    }
    if (!state.judge || !state.judge.running) { clearInterval(judgePoll); judgePoll = null; }
  }, 2500);
}

// --- Was "Run a check" messen wird, VOR dem Druecken --------------------
//
// Der Defekt, gegen den das hier steht (07.08., gemessen): der Knopf lief
// ueber die vier Labor-Fokusse, waehrend 513 Kanten auf dem Schirm
// standen. Ein Druck -- und der ganze Demo-Katalog war weg. Der Server
// misst jetzt den SICHTBAREN Umfang (`ui/serve.py::scope_focuses`), und
// dieser Satz sagt vorher, was das heisst.
function renderRunScope() {
  const host = document.getElementById('run-check-scope');
  if (!host) return;
  const l = state.ledger;
  if (state.mode === 'static') {
    host.textContent = 'exported copy — this button cannot measure';
    return;
  }
  if (state.mode !== 'live') {
    host.textContent = 'recording — measures nothing';
    return;
  }
  if (!l) {
    host.textContent = 'nothing measured yet';
    return;
  }
  const edges = (l.edges || []).length;
  const sources = (l.focuses || [l.focus]).filter(Boolean).length;
  const secs = l.run_seconds != null ? l.run_seconds : l.demo_ledger_seconds;
  host.textContent = `re-measures ${num(edges)} connections · ${num(sources)} source tables`
    + (secs != null ? ` · took ${secs}s last time` : '');
}

// Der Fortschritt eines laufenden Registerlaufs. Ein voller Lauf ueber
// den sichtbaren Umfang dauert Sekunden (gemessen: 21,75s ueber 330
// Quelltabellen) -- die Alternative waere gewesen, den Umfang heimlich
// zu verkleinern, und genau das war der Defekt.
let progressPoll = null;

function stopRunProgress() {
  if (progressPoll) { clearInterval(progressPoll); progressPoll = null; }
  document.getElementById('run-progress').hidden = true;
}

function watchRunProgress() {
  if (progressPoll) return;
  const box = document.getElementById('run-progress');
  const fill = document.getElementById('run-progress-fill');
  const text = document.getElementById('run-progress-text');
  box.hidden = false;
  fill.style.width = '0';
  text.textContent = 'measuring…';
  progressPoll = setInterval(async () => {
    let p;
    try { p = await getJson('/api/ledger/progress'); } catch { return; }
    if (!p.running && !p.total) return;
    const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
    fill.style.width = `${pct}%`;
    text.textContent = p.running
      ? `measuring ${num(p.done)} of ${num(p.total)} source tables (${pct}%)`
      : `done — ${num(p.total)} source tables, ${p.seconds != null ? `${p.seconds}s` : 'duration not recorded'}`;
    if (!p.running) { clearInterval(progressPoll); progressPoll = null; }
  }, 600);
}

async function runAction(name, btn) {
  // Nur `live` schreibt. Die Ein-Datei-Ausgabe hat keinen Katalog
  // dahinter -- ihre Knoepfe sind sichtbar gesperrt (`applyStaticMode`),
  // diese Zeile ist die zweite Schranke dahinter.
  if (!writesAllowed()) return;
  if (btn) btn.disabled = true;
  // Jede Aktion endet in einem Registerlauf (die fuenf schreibenden
  // ueber `full_run`, "Run a check" direkt) -- der Balken gehoert also an
  // jede von ihnen, nicht nur an die Hauptaktion.
  watchRunProgress();
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
    // NACH einem Knopfdruck wird wirklich neu gemessen -- die Seite
    // behauptet "every verdict is re-measured afterwards", also muss
    // genau hier der echte Lauf stehen und nicht der Zwischenstand.
    //
    // AUSSER bei "run-ledger": diese Aktion IST der Lauf. Ein zweiter
    // `/api/ledger` danach hat den vollen Lauf ein zweites Mal bezahlt --
    // bei vier Fokussen unauffaellig, beim sichtbaren Umfang sind es
    // zweimal 21,75s und zweimal 1476 API-Aufrufe fuer dasselbe Ergebnis.
    // `/api/current` liefert genau den Lauf, der eben entstanden ist.
    await refresh({ measure: name !== 'run-ledger' });
    await pumpLog();
    renderModeBadge(await fetchModeInfo());
    if (state.judge && state.judge.running) watchJudgements();
  } finally {
    if (btn) btn.disabled = false;
    stopRunProgress();
  }
}

// --- Verdrahtung --------------------------------------------------------

for (const item of document.querySelectorAll('.sidenav__item')) {
  item.addEventListener('click', () => showView(item.dataset.view));
}

// Die Knoepfe in den Leerzustaenden liegen ueberall im Baum (Tabelle,
// Baum, Liste) und werden bei jedem Zeichnen neu gebaut -- ein Delegat am
// Dokument statt eines Zuhoerers pro Knopf.
document.addEventListener('click', (ev) => {
  const btn = ev.target.closest('.blank button[data-action]');
  if (!btn || btn.disabled || document.body.dataset.mode !== 'live') return;
  runAction(btn.dataset.action, btn);
});

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
  if (!writesAllowed()) return;
  await fetch('/api/view/reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...API_HEADERS },
    body: '{}',
  });
  renderModeBadge(await fetchModeInfo());
  // Die Sicht-Verschiebung aendert die INTERPRETATION, also muss neu
  // gerechnet werden -- ein Zwischenstand waere gegen das alte Fenster
  // gemessen.
  await refresh({ measure: true });
  await pumpLog();
});

for (const [id, key] of [['filter-platform', 'platform'], ['filter-database', 'database'],
                          ['filter-domain', 'domain'], ['filter-owner', 'owner'],
                          ['filter-sort', 'sort']]) {
  document.getElementById(id).addEventListener('change', (ev) => {
    state.filters[key] = ev.target.value;
    state.filters.start = 0;
    renderConnections();
  });
}

// Stillstandsdauer: die Voreinsteller setzen direkt, "custom…" klappt das
// Zahlenfeld auf und filtert erst, wenn dort eine Zahl steht.
document.getElementById('filter-idle').addEventListener('change', (ev) => {
  const box = document.getElementById('filter-idle-custom-field');
  const inp = document.getElementById('filter-idle-custom');
  if (ev.target.value === 'custom') {
    box.hidden = false;
    state.filters.idle = inp.value.trim();
    inp.focus();
  } else {
    box.hidden = true;
    state.filters.idle = ev.target.value;
  }
  state.filters.start = 0;
  renderConnections();
});

let idleTimer = null;
document.getElementById('filter-idle-custom').addEventListener('input', (ev) => {
  clearTimeout(idleTimer);
  const raw = ev.target.value.trim();
  // Eine leere oder unsinnige Eingabe schaltet den Filter AB, statt still
  // auf 0 zu fallen -- "0 Tage" waere ein echter Filter mit ganz anderem
  // Ergebnis.
  const value = /^\d+$/.test(raw) ? raw : '';
  idleTimer = setTimeout(() => {
    state.filters.idle = value;
    state.filters.start = 0;
    renderConnections();
  }, 250);
});
for (const [id, key] of [['filter-judged', 'judged'], ['filter-abstained', 'abstained'],
                          ['filter-grouped', 'grouped']]) {
  document.getElementById(id).addEventListener('change', (ev) => {
    state.filters[key] = ev.target.checked;
    state.filters.start = 0;
    syncControls();
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

// Takte laufen nur, solange jemand hinsieht. Ein verborgener Tab (Fenster
// minimiert, anderer Tab im Vordergrund) hat nichts davon, dass alle 1,5s
// eine Anfrage gegen den Server geht -- Chrome drosselt den Takt ohnehin,
// aber der Server sieht die Last trotzdem. Beim Zurueckkommen wird EINMAL
// nachgeholt; `logCursor` sorgt dafuer, dass keine Zeile doppelt kommt.
function ticksAllowed() {
  return document.body.dataset.mode === 'live' && document.visibilityState === 'visible';
}

setInterval(() => { if (ticksAllowed()) pumpLog(); }, 1500);

document.addEventListener('visibilitychange', () => {
  if (ticksAllowed()) pumpLog();
});

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
  if (info.mode === 'static') applyStaticMode(info);
  // Solange nichts gezaehlt ist, steht an jedem Punkt ein Gedankenstrich
  // MIT Grund -- nie eine 0, die wie eine Messung aussieht.
  for (const [id, what] of [['nav-count-connections', 'checked connections'],
                            ['nav-count-catalog', 'datasets in the catalog'],
                            ['nav-count-runs', 'run artifacts on disk'],
                            ['nav-count-evidence', 'pieces of evidence in this run']]) {
    setNavCount(id, null, what);
  }

  await refresh();
  if (apiBacked()) {
    await pumpLog();
    if (state.judge && state.judge.running) watchJudgements();
    // Die Gesamtzahl des Katalogs steht in der Seitenleiste, bevor jemand
    // den Bereich oeffnet -- "N von 5.594" ist die Einordnung, die der
    // alten Oberflaeche gefehlt hat.
    try {
      const cat = await getJson('/api/catalog?q=*&start=0&count=1');
      state.catalogTotal = cat.total;
      setNavCount('nav-count-catalog', cat.total, 'datasets in the catalog');
    } catch { /* der Bereich holt es beim Oeffnen selbst */ }
    // Die beiden Beleg-Zahlen im Hintergrund nachziehen, damit an JEDEM
    // Navigationspunkt eine Zahl steht (Referenz) -- ohne den Start zu
    // verzoegern. Scheitert der Abruf, bleibt der Gedankenstrich mit
    // seinem Grund stehen: eine gescheiterte Abfrage ist keine Null.
    getJson('/api/runs')
      .then((r) => setNavCount('nav-count-runs', (r.runs || []).length, 'run artifacts on disk'))
      .catch(() => {});
    getJson('/api/evidence')
      .then((e) => setNavCount('nav-count-evidence', (e.items || []).length,
                                'pieces of evidence in this run'))
      .catch(() => {});
  } else {
    replayRecordedLog();
  }
  const wanted = location.hash.slice(1);
  showView(VIEWS.includes(wanted) ? wanted : 'overview');
}

window.addEventListener('hashchange', () => {
  const wanted = location.hash.slice(1);
  if (VIEWS.includes(wanted) && wanted !== state.view) showView(wanted);
});

boot();
