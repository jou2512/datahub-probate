"""Die ganze Konsole in EINER Datei -- ohne Server, ohne Python, ohne Netz.

Warum es das gibt: die Werkbank ist der Beweis dieser Einreichung, und ein
Beweis, den man erst nach `pip install` und einem laufenden DataHub sehen
kann, ist fuer einen Juror kein Beweis. `docs/werkbank-static.html` laesst
sich anklicken, weiterschicken und auf einer fremden Seite ausliefern.

Die harten Bedingungen, unter denen das gebaut ist:

  * **Keine einzige Anfrage nach draussen.** Keine Schrift von aussen, kein
    CDN, kein `fetch` ins Netz. Die Datei wird hinter einer strengen
    Sicherheitsrichtlinie ausgeliefert, die jede externe Anfrage abraeumt --
    eine Seite, die dort halb laedt, ist schlimmer als keine.
  * **Kein zweiter Bauweg fuer dieselbe Zahl.** Zeilen, Facetten, Belege und
    Laeufe kommen aus `ui/console_api.py`, also aus demselben Code, den der
    Server aufruft. Was hier eingebacken wird, hat der Server so
    ausgeliefert.
  * **Die schreibenden Knoepfe sind SICHTBAR ausser Betrieb.** Ein Knopf,
    der nichts tut und dabei aussieht, als taete er etwas, ist genau die
    stille Falschaussage, gegen die dieses Werkzeug antritt.
  * **Oben steht, dass es eine Aufzeichnung ist**, mit Zeitpunkt und
    Artefaktpfad -- dieselbe Wahrheitspflicht wie im Server.

Was NICHT eingebacken wird, und warum: der Katalogbaum. Er lebt in einer
laufenden Instanz (gemessen 07.08.: 6.205 Datensaetze), und ein Abzug davon
waere ein zweites, alterndes Artefakt neben dem Register. Die Datei zeigt
deshalb genau die Tabellen, die der aufgezeichnete Lauf beruehrt hat -- das
ist ohne Instanz belegbar --, und schreibt fuer den Rest hin, dass er eine
laufende Instanz braucht. Keine erfundene Zahl, keine stille Luecke.

Aufruf:

    uv run --python 3.11 python harness/export_static.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui import console_api as api  # noqa: E402
from ui import serve as srv  # noqa: E402

UI_DIR = ROOT / "ui"
OUT_DEFAULT = ROOT / "docs" / "werkbank-static.html"
REPLAY_PATH = UI_DIR / "recorded" / "replay.json"

# 16 MB ist die harte Grenze der Ausspielung. Wir pruefen sie hier, damit
# der Fehler beim Bauen auffaellt und nicht beim Hochladen.
SIZE_LIMIT_BYTES = 16 * 1024 * 1024


# --- Die eingebackenen Urteile ------------------------------------------
#
# `ui/recorded/replay.json` ist ein Modell-Lauf ueber das Vier-Zustaende-
# Labor. Das aufgezeichnete Register kann ein ANDERES sein (der Demo-
# Katalog mit 513 Kanten). Passen die Kanten-Schluessel nicht zusammen,
# gehoeren die Urteile nicht zu diesem Lauf -- dann werden sie NICHT
# mitgegeben. Ein Urteil ueber eine Kante, die in der Tabelle gar nicht
# vorkommt, waere ein Beleg ohne Gegenstand.
def load_judgements(ledger: dict) -> tuple[dict, dict, str]:
    """`(schluessel -> urteil, schnappschuss fuer /api/judgements, satz)`."""
    empty = {"running": False, "expected": 0, "done": 0, "calls": 0,
             "seconds": 0.0, "cost_usd": None, "error": "",
             "started_ms": None, "finished_ms": None, "judgements": [], "log": []}
    try:
        snap = json.loads(REPLAY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, empty, ("no recorded model run on disk (ui/recorded/replay.json) — "
                           "the judgement column reads 'not asked', which is the truth")
    keys = {e.get("edge", "") for e in (ledger.get("edges") or [])}
    kept = [j for j in (snap.get("judgements") or []) if j.get("edge") in keys]
    if not kept:
        return {}, empty, (
            f"the recorded model run ({REPLAY_PATH.name}) judged "
            f"{len(snap.get('judgements') or [])} edge(s) of a different run — none of "
            "them appears in this ledger, so none is shown. A judgement about an edge "
            "that is not in the table would be evidence without a subject.")
    snap["judgements"] = kept
    snap.setdefault("log", [])
    return {j["edge"]: j for j in kept}, snap, ""


# --- Der Katalog, soweit er ohne Instanz belegbar ist --------------------
def catalog_from_ledger(ledger: dict) -> list[dict]:
    """Jede Tabelle, die im aufgezeichneten Lauf als Kanten-Ende vorkommt.

    Dieselbe Zeilenform wie `console_api.catalog_page`, damit die Ansicht
    keinen Sonderfall braucht. `state`/`checked` kommen aus dem Lauf --
    eine Tabelle ohne Urteil traegt ausdruecklich `checked: False` und
    bekommt in der Ansicht das Wort "not checked" statt eines grauen
    Punkts, der wie ein Urteil aussaehe.
    """
    seen: dict[str, dict] = {}
    for edge in ledger.get("edges") or []:
        for urn in (edge.get("upstream", ""), edge.get("downstream", "")):
            if not urn or urn in seen:
                continue
            parts = api.split_urn(urn)
            parts["display"] = parts["table"]
            parts["state"] = edge.get("state", "")
            parts["checked"] = bool(edge.get("state"))
            seen[urn] = parts
    return sorted(seen.values(),
                  key=lambda r: (r["platform"], r["database"], r["schema"], r["table"]))


def build_payload(ledger: dict) -> dict:
    gov = api.load_governance()
    judged, judge_snapshot, judge_note = load_judgements(ledger)
    edges = ledger.get("edges") or []

    rows = api.all_rows(edges, judged, gov)
    state_counts = {s: 0 for s in ("confirmed", "dead", "missing", "unknown")}
    for e in edges:
        st = e.get("state", "")
        state_counts[st] = state_counts.get(st, 0) + 1

    provenance = srv._provenance(ledger)
    catalog_rows = catalog_from_ledger(ledger)

    return {
        # Was `/api/mode` in dieser Betriebsart antwortet. `mode: "static"`
        # ist eine EIGENE Betriebsart, nicht "live" mit gesperrten
        # Knoepfen -- die Oberflaeche soll lesen duerfen und trotzdem
        # wissen, dass nichts dahinter steht.
        "mode": {
            "mode": "static",
            "gms": "",
            "focus": "",
            "focuses": ledger.get("focuses") or ([ledger["focus"]] if ledger.get("focus") else []),
            "scope_focuses": len(ledger.get("focuses") or []),
            "scope_edges": ledger.get("edges_total"),
            "demo_focus": ledger.get("demo_focus", ""),
            "demo_partner": ledger.get("demo_partner", ""),
            "seeded_statement": ledger.get("seeded_statement", ""),
            "view_offset_days": 0,
            "recorded_from": ledger.get("recorded_from", ""),
            "recorded_at_iso": ledger.get("recorded_at_iso", ""),
            # Die Ueberschrift des Katalogbereichs wird in dieser
            # Betriebsart ERSETZT (`applyStaticMode`): "Everything the
            # instance holds" gilt hier nicht, es gibt keine Instanz.
            "catalog_note": (
                f"{len(catalog_rows)} tables — every dataset the recorded run touched. "
                "The catalog they live in is not in this file; browsing it needs a "
                "running instance (python -m ui.serve). Nothing here is estimated."),
        },
        "current": {**ledger, **provenance},
        "judgements": judge_snapshot,
        "judge_note": judge_note,
        "connections": {
            "rows": rows,
            "state_counts": state_counts,
            "total_unfiltered": len(rows),
            "facets": api.facets(edges, gov),
            "provenance": provenance,
        },
        "catalog": {
            "rows": catalog_rows,
            # Der Satz, der die Luecke BENENNT statt sie zu fuellen.
            "note": (
                f"This single file carries the {len(catalog_rows)} tables the recorded "
                "run touched — every dataset that is an endpoint of a checked "
                "connection. The catalog they live in is not baked in: browsing it "
                "needs a running instance (python -m ui.serve). Nothing here is "
                "estimated."),
        },
        "runs": api.runs(),
        "evidence": api.evidence(edges, judged, ""),
        # Das Protokoll sagt zuerst, WAS diese Datei ist. Danach kommt,
        # was im aufgezeichneten Modell-Lauf tatsaechlich passiert ist --
        # falls einer zu diesem Register gehoert. Eine leere Protokollkarte
        # saehe aus, als haette die Seite nichts getan; tatsaechlich hat sie
        # gelesen und nichts gemessen, und genau das steht jetzt da.
        "log": ([{
            "t": ledger.get("generated_at_ms"),
            "text": ("exported single file — every view below reads "
                     f"{ledger.get('recorded_from') or 'a recorded run'}, "
                     f"recorded {ledger.get('recorded_at_iso') or 'at an unknown time'}."
                     " Nothing has been measured since, and nothing here can measure."),
            "n": None,
        }] + (judge_snapshot.get("log") or [])),
    }


# --- Der Abfang-Schicht: jede /api/-Anfrage aus dem Dokument beantwortet --
#
# Bewusst `window.fetch` und nicht ein Umbau von werkbank.js: die Konsole
# soll in dieser Datei GENAU denselben Code laufen lassen wie gegen den
# Server. Ein zweiter Datenpfad waere ein zweiter Satz Fehler.
#
# Die Filter-/Sortier-/Gruppier-Logik spiegelt `console_api.filter_sort_page`
# und `console_api.groups`. Sie ist hier nachgebaut, weil in einer einzelnen
# HTML-Datei kein Python laeuft. Der Test
# `tests/test_export_static.py::test_the_shim_mirrors_every_filter_the_server_has`
# haelt beide Seiten Feld fuer Feld gegeneinander, damit die Doppelung nicht
# auseinanderlaeuft.
SHIM_JS = r"""
(function () {
  var P = window.__PROBATE_STATIC__;
  var GROUP_SEP = '\x1f';
  var STATE_RANK = { dead: 0, missing: 1, unknown: 2, confirmed: 3 };
  var NONE_VALUE = '__none__';

  function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
  function tupleCmp(a, b) {
    for (var i = 0; i < a.length; i++) {
      var c = cmp(a[i], b[i]);
      if (c) return c;
    }
    return 0;
  }

  var SORTS = {
    state: function (r) { return [r.state]; },
    from: function (r) { return [r.from.qualified || '']; },
    to: function (r) { return [r.to.qualified || '']; },
    evidence: function (r) { return [r.query_urns.length, r.buckets_seen]; },
    // Nicht gemessene Kanten ans ENDE -- eine fehlende Messung ist kein
    // sehr altes Datum (dieselbe Regel wie serverseitig).
    last: function (r) { return [r.last_covered_ms == null ? 1 : 0, r.last_covered_ms || 0]; },
    traffic: function (r) { return [r.traffic_total]; },
    group: function (r) {
      return [r.from.platform, r.from.database,
              STATE_RANK[r.state] == null ? 9 : STATE_RANK[r.state],
              r.from.qualified, r.to.qualified];
    },
  };

  function hasDomain(row, want) {
    var sides = [row.from, row.to];
    for (var i = 0; i < sides.length; i++) {
      var s = sides[i];
      if (want === NONE_VALUE ? (s.known && !s.domain) : s.domain === want) return true;
    }
    return false;
  }

  function hasOwner(row, want) {
    var sides = [row.from, row.to];
    for (var i = 0; i < sides.length; i++) {
      var s = sides[i], owners = s.owners || [];
      if (want === NONE_VALUE) { if (s.known && !owners.length) return true; continue; }
      for (var k = 0; k < owners.length; k++) if (owners[k].urn === want) return true;
    }
    return false;
  }

  function groupsOf(rows) {
    var out = {};
    rows.forEach(function (r) {
      var key = r.from.platform + GROUP_SEP + r.from.database;
      var g = out[key];
      if (!g) {
        g = out[key] = { key: key, platform: r.from.platform, database: r.from.database,
                         total: 0, confirmed: 0, dead: 0, missing: 0, unknown: 0 };
      }
      g.total += 1;
      if (g[r.state] != null) g[r.state] += 1;
    });
    return Object.keys(out).map(function (k) { return out[k]; })
      .sort(function (a, b) { return tupleCmp([a.platform, a.database], [b.platform, b.database]); });
  }

  function connections(q) {
    var rows = P.connections.rows.slice();
    var states = (q.get('state') || '').split(',').filter(Boolean);
    if (states.length) rows = rows.filter(function (r) { return states.indexOf(r.state) >= 0; });
    ['platform', 'database'].forEach(function (key) {
      var want = (q.get(key) || '').trim();
      if (want) {
        rows = rows.filter(function (r) { return r.from[key] === want || r.to[key] === want; });
      }
    });
    var domain = (q.get('domain') || '').trim();
    if (domain) rows = rows.filter(function (r) { return hasDomain(r, domain); });
    var owner = (q.get('owner') || '').trim();
    if (owner) rows = rows.filter(function (r) { return hasOwner(r, owner); });

    var unaged = 0;
    var idleRaw = (q.get('idle') || '').trim();
    if (idleRaw) {
      var idleMin = parseInt(idleRaw, 10);
      if (isNaN(idleMin) || idleMin < 0) idleMin = 0;
      unaged = rows.filter(function (r) { return r.dead_since_days == null; }).length;
      rows = rows.filter(function (r) {
        return r.dead_since_days != null && r.dead_since_days >= idleMin;
      });
    }

    var table = (q.get('table') || '').trim();
    if (table) {
      rows = rows.filter(function (r) {
        return r.from.qualified === table || r.to.qualified === table;
      });
    }
    var text = (q.get('q') || '').trim().toLowerCase();
    if (text) {
      rows = rows.filter(function (r) {
        return r.from.qualified.toLowerCase().indexOf(text) >= 0
            || r.to.qualified.toLowerCase().indexOf(text) >= 0;
      });
    }
    if (q.get('judged') === '1') rows = rows.filter(function (r) { return r.judgement === 'model'; });
    if (q.get('abstained') === '1') rows = rows.filter(function (r) { return r.judgement === 'abstained'; });

    var key = SORTS[q.get('sort')] || SORTS.state;
    var reverse = (q.get('dir') || 'asc') === 'desc';
    rows.sort(function (a, b) { return tupleCmp(key(a), key(b)) * (reverse ? -1 : 1); });

    var start = Math.max(0, parseInt(q.get('start') || '0', 10) || 0);
    var count = Math.min(200, Math.max(1, parseInt(q.get('count') || '50', 10) || 50));
    var page = rows.slice(start, start + count);

    var out = {
      rows: page, start: start, count: page.length, total: rows.length,
      total_unfiltered: P.connections.total_unfiltered,
      state_counts: P.connections.state_counts,
      groups: groupsOf(rows),
      unaged: unaged,
      facets: P.connections.facets,
    };
    Object.keys(P.connections.provenance).forEach(function (k) {
      out[k] = P.connections.provenance[k];
    });
    return out;
  }

  function catalog(q) {
    var text = (q.get('q') || '*').trim().toLowerCase();
    var rows = P.catalog.rows;
    if (text && text !== '*') {
      rows = rows.filter(function (r) {
        return (r.qualified || '').toLowerCase().indexOf(text) >= 0;
      });
    }
    var start = Math.max(0, parseInt(q.get('start') || '0', 10) || 0);
    var count = Math.min(200, Math.max(1, parseInt(q.get('count') || '50', 10) || 50));
    var out = {
      rows: rows.slice(start, start + count),
      start: start, count: Math.min(count, Math.max(0, rows.length - start)),
      total: rows.length, facets: [],
    };
    Object.keys(P.connections.provenance).forEach(function (k) {
      out[k] = P.connections.provenance[k];
    });
    if (!out.rows.length) {
      // Eine gemessene Null, kein fehlender Messwert -- und der Satz sagt
      // ausserdem, was diese Datei ueberhaupt tragen kann.
      out.empty_reason = 'No table of the recorded run matches this search. '
        + 'That is a measured zero, not a missing measurement. ' + P.catalog.note;
      out.fix_action = '';
    }
    return out;
  }

  function evidence(q) {
    var text = (q.get('q') || '').trim().toLowerCase();
    var items = P.evidence;
    if (text) {
      items = items.filter(function (r) {
        return (r.text || '').toLowerCase().indexOf(text) >= 0
            || (r.label || '').toLowerCase().indexOf(text) >= 0
            || (r.detail || '').toLowerCase().indexOf(text) >= 0;
      });
    }
    var out = { items: items };
    Object.keys(P.connections.provenance).forEach(function (k) {
      out[k] = P.connections.provenance[k];
    });
    if (!items.length) {
      out.empty_reason = 'No evidence in this recorded run matches that search. '
        + 'That is a measured zero — the run collected '
        + P.evidence.length + ' piece(s) of evidence in total.';
      out.fix_action = '';
    }
    return out;
  }

  var ROUTES = {
    '/api/mode': function () { return P.mode; },
    '/api/current': function () { return P.current; },
    '/api/judgements': function () { return P.judgements; },
    '/api/connections': connections,
    '/api/catalog': catalog,
    '/api/evidence': evidence,
    '/api/runs': function () {
      var out = { runs: P.runs };
      if (!P.runs.length) {
        out.empty_reason = 'This exported copy carries no run artifacts.';
        out.fix_action = '';
      }
      return out;
    },
    '/api/ledger/progress': function () { return { running: false, done: 0, total: 0 }; },
  };

  function json(body, status) {
    return new Response(JSON.stringify(body), {
      status: status || 200,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  // KEIN Durchreichen an das echte `fetch`. Die Datei wird hinter einer
  // strengen Sicherheitsrichtlinie ausgeliefert; jede Anfrage nach aussen
  // waere dort blockiert, und eine blockierte Anfrage sieht in der
  // Oberflaeche aus wie ein Defekt. Was hier nicht bekannt ist, bekommt
  // eine EHRLICHE Absage -- keinen stillen Fehlschlag.
  window.fetch = function (input, init) {
    var url = String((input && input.url) || input || '');
    var path = url.replace(/^[a-z]+:\/\/[^/]+/i, '').replace(/^\.\//, '/');
    var qs = '';
    var cut = path.indexOf('?');
    if (cut >= 0) { qs = path.slice(cut + 1); path = path.slice(0, cut); }
    var q = new URLSearchParams(qs);

    // Das Protokoll gibt es EINMAL: `since` ab der Laenge liefert nichts
    // mehr. Die Seite pumpt in dieser Betriebsart ohnehin nicht im Takt
    // (`ticksAllowed()` verlangt `live`), aber ein Protokoll, das sich bei
    // jedem Abruf wiederholt, waere eine erfundene Aktivitaet.
    if (path === '/api/log') {
      var since = Math.max(0, parseInt(q.get('since') || '0', 10) || 0);
      return Promise.resolve(json({ entries: P.log.slice(since), cursor: P.log.length }));
    }
    if (path.indexOf('/api/action/') === 0 || path === '/api/view/reset') {
      return Promise.resolve(json({
        error: 'this copy has no catalog behind it — run it locally to write',
      }, 403));
    }
    // Der Aufzeichnungs-Pfad von werkbank.js, falls jemals jemand hier
    // landet: dieselben Daten, nicht das Dateisystem.
    if (path.indexOf('/recorded/ledger.json') >= 0) return Promise.resolve(json(P.current));
    if (path.indexOf('/recorded/replay.json') >= 0) return Promise.resolve(json(P.judgements));

    var route = ROUTES[path];
    if (route) return Promise.resolve(json(route(q)));
    return Promise.resolve(json({ error: 'not available in the exported copy: ' + path }, 404));
  };

})();
"""


def _inline(html: str, css: str, js: str, payload: dict, shim: str) -> str:
    """Stil und Verhalten in das Dokument hinein, ohne eine einzige externe
    Anfrage uebrig zu lassen."""
    if '<link rel="stylesheet" href="werkbank.css" />' not in html:
        raise SystemExit("export: der Stil-Verweis in ui/werkbank.html hat sich geaendert")
    if '<script type="module" src="werkbank.js"></script>' not in html:
        raise SystemExit("export: der Skript-Verweis in ui/werkbank.html hat sich geaendert")

    html = html.replace('<link rel="stylesheet" href="werkbank.css" />',
                        "<style>\n" + css + "\n</style>")

    # `</script>` im JSON zerlegt sonst das Dokument. `<!--` ebenso.
    data = (json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            .replace("</", "<\\/").replace("<!--", "<\\!--"))
    head = ('<script>window.__PROBATE_STATIC__ = ' + data + ';</script>\n'
            '<script>' + shim + '</script>\n'
            '<script type="module">\n' + js + "\n</script>")
    return html.replace('<script type="module" src="werkbank.js"></script>', head)


def export(out_path: Path = OUT_DEFAULT) -> dict:
    ledger = srv.load_recorded_ledger()
    if ledger is None:
        raise SystemExit(
            "export: kein Lauf-Artefakt auf der Platte (harness/runs, ui/recorded). "
            "Eine Ein-Datei-Ausgabe ohne gemessenen Lauf waere eine leere Behauptung.")

    payload = build_payload(ledger)
    html = _inline(
        (UI_DIR / "werkbank.html").read_text(encoding="utf-8"),
        (UI_DIR / "werkbank.css").read_text(encoding="utf-8"),
        (UI_DIR / "werkbank.js").read_text(encoding="utf-8"),
        payload,
        SHIM_JS,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    size = out_path.stat().st_size
    return {
        "path": str(out_path).replace("\\", "/"),
        "bytes": size,
        "megabytes": round(size / (1024 * 1024), 2),
        "over_limit": size > SIZE_LIMIT_BYTES,
        "connections": len(payload["connections"]["rows"]),
        "catalog_tables": len(payload["catalog"]["rows"]),
        "evidence": len(payload["evidence"]),
        "runs": len(payload["runs"]),
        "recorded_from": ledger.get("recorded_from", ""),
        "recorded_at_iso": ledger.get("recorded_at_iso", ""),
        "judge_note": payload["judge_note"],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="harness.export_static",
        description="Die ganze Konsole als eine HTML-Datei ohne Server und ohne Netz.")
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args(argv)

    out = export(args.out)
    print(f"{out['path']} — {out['megabytes']} MB ({out['bytes']} bytes)")
    print(f"  {out['connections']} connections · {out['catalog_tables']} tables · "
          f"{out['evidence']} pieces of evidence · {out['runs']} run artifacts")
    print(f"  recorded run: {out['recorded_from']} ({out['recorded_at_iso']})")
    if out["judge_note"]:
        print(f"  model judgements: {out['judge_note']}")
    if out["over_limit"]:
        print(f"  ZU GROSS: {out['megabytes']} MB > {SIZE_LIMIT_BYTES // (1024 * 1024)} MB",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
