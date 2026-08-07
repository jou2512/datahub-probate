"""Der Live-Modus der Werkbank.

Warum diese Datei existiert -- zwei Gruende, beide zwingend:

1. CORS. Ein Browser auf file:// oder einem fremden Port braucht von GMS
   einen Access-Control-Allow-Origin-Kopf. Ob 28080 den sendet, ist NICHT
   gemessen. Ein Proxy im selben Ursprung loescht die Frage, statt sie zu
   beantworten.
2. Die Knoepfe sind Python. "Kante eintragen" ist kein GMS-Aufruf, sondern
   correct.merge_upstreams() ueber writeback.Writeback -- mit Journal,
   Vorher-Sicherung und Rueckwaertsgang. Diese Disziplin im Browser
   nachzubauen waere eine zweite Wahrheit ueber den einzigen Schreibweg.

Port 8899: nicht 8080 (WhatsApp-Bridge), nicht 8081 (existiert nicht),
nicht 3000 (Cockpit).

Task-19-Sicherheitsbefund (Opus-Review, 07.08. ~01:45, gemessener CSRF-
Test): ein Cross-Origin-POST erreichte die Dispatch-Zeile, weil `_handle`
Host/Origin nie prueft, und ein zweiter, unabhaengiger Fund beim Bau
dieser Aufgabe -- live gegen einen laufenden Server gemessen (curl -i
gegen /api/mode, 07.08.): `_json()` gab nichts zurueck, `_handle()` damit
immer `None`, jeder API-Aufruf fiel auf `super().do_GET()` durch und
antwortete 404 statt der JSON-Nutzlast. `/api/mode` hat also NIE 200
geliefert, seit es existiert -- ungefangen, weil test_ui_serve.py nur
`route()` als reine Funktion prueft, nie einen echten Socket. Beide
Befunde beheben dieselbe Methode: sie bekommt jetzt einen echten
Rueckgabewert ("behandelt" vs. "nicht behandelt") UND eine Zugriffsprüfung
davor.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
import threading
import time
from socket import timeout as _SocketTimeout
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT_DEFAULT = 8899

ACTIONS = ("seed-query", "add-edge", "remove-edge",
           "cut-warehouse", "fast-forward", "run-ledger")

UI_DIR = Path(__file__).parent

# Opus-Review-Nachtrag (CRITICAL 1): vorher ein String-Literal direkt im
# Writeback()-Aufruf unten -- kein Injektionspunkt, jeder Test, der
# do_action() aufruft, schrieb dadurch in die ECHTE Beweis-/Rueckweg-Datei.
# Gemessen (Controller): 100 zusaetzliche Zeilen im Arbeitsbaum, 84 davon
# Fixture-Muell mit der Nonsense-URN "urn:focus" auf dem REALEN Dataset
# probate_seedlab.finance_income_statement_consolidated -- ein `probate revert` haette das
# in den Live-Katalog zurueckgeschrieben. Jetzt ein Modul-Attribut, das
# Tests per `monkeypatch.setattr(ui.serve, "JOURNAL_PATH", ...)` auf
# `tmp_path` umbiegen -- nie auf die echte Datei.
JOURNAL_PATH = "harness/runs/journal.jsonl"

# --- Alle Tabellennamen kommen aus dem Manifest, KEINER steht hier -----
#
# `examples/seedlab-manifest.json` ist die einzige Wahrheit darueber, wie
# die geseedeten Tabellen heissen (`harness/seed_lineage_lab.py` schreibt
# es). Waehrend genau dieser Aufgabe hat eine parallele Bahn sie von
# `confirmed_upstream` auf `gl_journal_entries_daily` umbenannt und musste
# dafuer diese Konstante von Hand nachziehen -- der Beweis, dass ein
# Tabellenname im Quelltext hier eine Zeitbombe ist. Jetzt: Datei lesen,
# nicht tippen. Ist sie nicht lesbar, bleiben die Ziele LEER und jede
# Aktion verweigert laut (`_validate_action_urn`) -- kein Literal als
# "Rueckfall", das genau die Verwechslung erzeugt, gegen die dieses
# Projekt antritt.
MANIFEST_PATH = Path("examples/seedlab-manifest.json")


def load_manifest_targets(path=None) -> dict:
    """`focuses` + die beiden Demo-Ziele aus dem Seedlab-Manifest.

    * `focuses` -- die vier Upstream-URNs, je einer pro Zustand. Damit
      deckt ein blosser Start ALLE VIER Zustaende ab; mit genau einem
      Fokus zeigte das Register bisher genau EINE Kante -- der Grund,
      warum der Live-Modus als Demo unbrauchbar war (ein Juror sah
      entweder vier Zustaende ohne Knoepfe oder Knoepfe mit einer Kante).
    * `demo_focus` -- die Kante, auf die die Knoepfe schreiben: der
      Upstream des `unknown`-Paares. Er traegt selbst keine Nutzungsdaten
      und ist mit dem Demo-Partner noch nicht verbunden, also lassen sich
      an ihm alle drei Uebergaenge zeigen, ohne einen bestehenden Befund
      zu ueberschreiben.
    * `demo_partner` -- der Downstream des `confirmed`-Paares. Er traegt
      als einziger eine echte `datasetUsageStatistics`-Zeitreihe; ohne
      die kann "Kante eintragen" nie `dead` zeigen und "Warehouse
      trennen" nie etwas zu loeschen finden.
    """
    data = json.loads(Path(path or MANIFEST_PATH).read_text(encoding="utf-8"))
    edges = data.get("edges") or []
    by_state = {e.get("expected_edge_state"): e for e in edges}
    return {
        "focuses": [e["upstream_urn"] for e in edges if e.get("upstream_urn")],
        "demo_focus": (by_state.get("unknown") or edges[0])["upstream_urn"],
        "demo_partner": (by_state.get("confirmed") or edges[0])["downstream_urn"],
        "seeded_statement": data.get("seeded_statement", ""),
    }


try:
    _MANIFEST = load_manifest_targets()
except Exception as _exc:  # pragma: no cover -- nur ausserhalb des Repos erreichbar
    print(f"werkbank: manifest nicht lesbar ({_exc}) -- aktionen bleiben gesperrt",
          file=sys.stderr)
    _MANIFEST = {"focuses": [], "demo_focus": "", "demo_partner": "",
                 "seeded_statement": ""}

DEMO_PARTNER = _MANIFEST["demo_partner"]
DEMO_FOCUS = _MANIFEST["demo_focus"]
MANIFEST_FOCUSES = _MANIFEST["focuses"]
SEEDED_STATEMENT = _MANIFEST["seeded_statement"]


def route(method: str, path: str, query: dict) -> tuple[str, dict]:
    """Wegewahl ohne Socket -- damit sie ohne Netz pruefbar ist."""
    if path == "/api/mode" and method == "GET":
        return "mode", {}
    if path == "/api/ledger" and method == "GET":
        return "ledger", {}
    if path == "/api/judgements" and method == "GET":
        # Getrennt vom Register, weil die Modell-Urteile MINUTEN spaeter
        # fertig sind als der deterministische Befund (live gemessen:
        # 17.8-23.1s pro Kante). Sie an /api/ledger zu haengen hiesse, den
        # billigen, sicheren Befund hinter dem teuren zurueckzuhalten.
        return "judgements", {}
    if path == "/api/log" and method == "GET":
        return "log", {"since": int((query.get("since") or ["0"])[0])}
    # --- Die Konsole (docs/werkbank-spec.md): filtern, sortieren und
    # seitenweise liefern passiert SERVERSEITIG. Bei 5.594 Datensaetzen
    # kann der Browser nicht mehr alles holen und lokal aussortieren --
    # das ist der Grund, warum es diese vier Wege ueberhaupt gibt.
    if path == "/api/connections" and method == "GET":
        return "connections", {"params": {k: v[0] for k, v in query.items()}}
    if path == "/api/catalog" and method == "GET":
        return "catalog", {"params": {k: v[0] for k, v in query.items()}}
    if path == "/api/runs" and method == "GET":
        return "runs", {}
    if path == "/api/evidence" and method == "GET":
        return "evidence", {"params": {k: v[0] for k, v in query.items()}}
    if path == "/api/view/reset" and method == "POST":
        return "reset-time", {}
    if path.startswith("/api/action/"):
        # Opus-Review-Nachtrag (IMPORTANT 3): `rsplit("/", 1)[-1]` nahm nur
        # das LETZTE Segment -- "/api/action/fast-forward/../seed-query"
        # bestand die Pruefung und fuehrte seed-query aus, waehrend die
        # angeforderte URL etwas anderes suggeriert (Auditier-Anspruch
        # dieses Projekts verletzt: angeforderter Pfad und ausgefuehrte
        # Aktion muessen uebereinstimmen). Jetzt: alles nach dem Praefix
        # muss GENAU ein Segment sein, kein "/" darin, sonst Ablehnung.
        name = path[len("/api/action/"):]
        if not name or "/" in name or name not in ACTIONS:
            raise KeyError(f"unbekannte Aktion: {name}")
        if method != "POST":
            raise ValueError("Aktionen schreiben -- nur POST")
        return "action", {"name": name}
    raise KeyError(f"kein Weg fuer {method} {path}")


# --- Security-Checkliste Punkt 6: eine Aktion nach der anderen ------------
#
# get_aspect -> Journal -> upsert ist drei Netzwerk-Schritte lang. Ohne
# Sperre koennten zwei parallele Knopfdruecke denselben "before"-Zustand
# lesen und der zweite Journal-Eintrag wuerde den ersten Rueckwaertsgang
# ungueltig machen. Der Lock sitzt IM do_action-Body, nicht am Aufrufort
# in _handle -- jeder Aufrufer (Server, Test) ist damit automatisch
# geschuetzt, nicht nur der, der daran denkt.
_ACTION_LOCK = threading.Lock()

# Security-Checkliste Punkt 3: verbotene Zeichen in jedem URN-Parameter,
# der do_action() erreicht -- Anfuehrungszeichen, Backslash, Leerraum,
# geschweifte Klammern. Bewusst eine ERLAUBEN-was-nicht-verboten-ist-Liste
# statt der vollen urn:li:...-Grammatik aus probate/gms.py: die
# handgeschriebenen Tests in dieser Datei (test_ui_serve.py) speisen
# Fixture-Werte wie "urn:focus" durch do_action() -- keines der
# verbotenen Zeichen, also weiterhin gueltig. Eine echte Injektion (ein
# eingebettetes '"' oder '{') wird trotzdem VOR jedem gms-Aufruf
# abgewiesen, nicht erst an der GraphQL/REST-Stelle. probate/gms.py
# validiert danach noch einmal, strenger -- zwei unabhaengige Sperren,
# keine ersetzt die andere.
_FORBIDDEN_URN_CHARS = re.compile(r'["\\{}\s]')


def _validate_action_urn(urn: str) -> None:
    if not isinstance(urn, str) or not urn:
        raise ValueError("aktion verweigert: leere oder fehlende urn")
    if _FORBIDDEN_URN_CHARS.search(urn) or ".." in urn:
        raise ValueError(f"aktion verweigert: urn traegt verbotene zeichen: {urn[:80]!r}")


def do_action(name: str, gms, focus: str, note, full_run=None) -> dict:
    """Die sechs Knoepfe. Jeder veraendert eine der beiden Wahrheitsquellen
    -- ausser 'fast-forward', der nur die Sicht verschiebt.

    Serialisiert (Punkt 6): der gesamte Koerper laeuft unter einer Sperre,
    nicht nur der Schreibvorgang selbst -- der Vorher-Zustand fuer den
    Rueckwaertsgang muss zur Sperrzeit noch stimmen.
    """
    with _ACTION_LOCK:
        return _do_action_locked(name, gms, focus, note, full_run)


# Keine f-String-GraphQL: der URN geht als Variable, nie in den Abfragetext.
_ENTITY_EXISTS_Q = "query($urn: String!) { entityExists(urn: $urn) }"


def _require_dataset(gms, urn: str, role: str) -> None:
    """Kein Knopf gegen eine Entitaet, die es nicht gibt.

    Gemessener Vorfall (07.08., vom Controller gefunden):
    `harness/runs/journal.jsonl` war von 20 auf 93 Zeilen gewachsen. Die
    73 neuen Zeilen nannten `snowflake,analytics.customers_v5` und
    `analytics.customer_ltv_report_v3` -- Datensaetze, die es im Katalog
    NICHT gibt. Es waren also Journal-Eintraege fuer Mutationen, die nie
    stattgefunden haben, in genau der Datei, die `probate revert`
    abspielt. Ein Journal, das Mutationen behauptet, die nie passiert
    sind, ist derselbe Fehlertyp, den dieses Produkt anprangert.

    Die Pruefung sitzt VOR dem ersten Schreibweg, nicht danach: sobald
    `Writeback.aspect()` laeuft, ist die Zeile geschrieben, und
    `probate/writeback.py` gehoert einer anderen Bahn (nicht anfassen).

    WELCHE Abfrage -- und warum nicht die naheliegende: `dataset(urn:)`
    liefert fuer eine FREI ERFUNDENE URN trotzdem einen Knoten. Live
    gemessen (07.08., 28080, genau die URN aus dem Vorfall oben):

        dataset(urn: "...snowflake,analytics.customers_v5,PROD") { urn }
          -> {"dataset": {"urn": "...customers_v5..."}}        (!)
        entityExists(urn: "...customers_v5...")  -> false
        entityExists(urn: "...finance_income_statement...") -> true

    Ein `dataset`-Knoten ist also KEIN Existenzbeweis -- diese Pruefung
    haette den Vorfall nicht verhindert, nur so ausgesehen. `entityExists`
    unterscheidet beide Faelle nachweislich. (`dataset { exists }` tut es
    ebenfalls; `entityExists` ist die kleinere Antwort.)
    """
    data = gms.graphql(_ENTITY_EXISTS_Q, {"urn": urn})
    if not data.get("entityExists"):
        raise ValueError(
            f"aktion verweigert: {role} {urn!r} existiert nicht im katalog -- "
            "kein journal-eintrag fuer eine mutation, die nirgends landen kann"
        )


def _do_action_locked(name: str, gms, focus: str, note, full_run=None) -> dict:
    global _view_offset_days

    _validate_action_urn(focus)  # Punkt 3 -- vor JEDEM gms-Kontakt, jede Aktion.

    # Nur die schreibenden Knoepfe: `fast-forward` und `run-ledger`
    # veraendern den Katalog nicht und brauchen deshalb kein Ziel.
    if name in ("seed-query", "add-edge", "remove-edge", "cut-warehouse"):
        _require_dataset(gms, focus, "fokus")
        _require_dataset(gms, DEMO_PARTNER, "ziel")

    from probate.correct import merge_upstreams
    from probate.writeback import Writeback

    wb = Writeback(gms, dry_run=False, journal_path=JOURNAL_PATH)
    now_ms = int(time.time() * 1000)

    if name == "seed-query":
        # NICHT harness.seed_queries.build_query_records: die nimmt
        # (sql, dataset_urn)-Paare und setzt genau EIN Subject pro Record
        # (harness/seed_queries.py:15-33) -- live gemessen (07.08., GraphQL
        # searchAcrossEntities gegen den echten Fokus-URN nach einem Aufruf
        # mit build_query_records([(focus, DEMO_PARTNER)])): die neue Query
        # blieb unauffindbar, weil `focus` dort als SQL-Text landete und nie
        # als Subject. Ko-Okkurrenz braucht ZWEI Subjects auf EINER Query
        # (Beleg fuer die Form: harness/seed_lineage_lab.py:592,
        # subjects=[{entity: up}, {entity: down}]) -- hier direkt gebaut,
        # kein dritter Schreibweg, `harness/**` bleibt unveraendert.
        #
        # Opus-Review-Nachtrag (CRITICAL 2): vorher `gms.upsert("query",
        # [record])` DIREKT -- am Journal vorbei. Der Reviewer bewies live:
        # ein Knopfdruck erzeugte eine echte Query-Entitaet, das Journal
        # blieb unveraendert, `probate revert` konnte sie nicht sehen (von
        # Hand geloescht). Eine Query-Entitaet ist zwei GEWOEHNLICHE
        # Aspekte -- `wb.aspect()` deckt beide, `revert_all()`s
        # `before is None -> delete_aspect`-Zweig ist exakt der
        # Aufraeumschritt, der vorher manuell noetig war.
        import hashlib
        stamp = {"time": now_ms, "actor": "urn:li:corpuser:__datahub_system"}
        sql = f"SELECT * FROM {focus} JOIN {DEMO_PARTNER}"  # nur ID-Bildung (Falle 8: hashlib, nie hash())
        qid = hashlib.sha1(sql.encode()).hexdigest()[:16]
        query_urn = f"urn:li:query:probate-demo-{qid}"
        props_value = {
            "statement": {"value": sql, "language": "SQL"},
            "source": "MANUAL", "created": stamp, "lastModified": stamp,
        }
        subjects_value = {"subjects": [{"entity": focus}, {"entity": DEMO_PARTNER}]}
        wb.aspect("query", query_urn, "queryProperties", props_value)
        wb.aspect("query", query_urn, "querySubjects", subjects_value)
        note("query written, 2 subject(s)", 2)
        return {"wrote": 1, "expect": "missing"}

    if name == "add-edge":
        before = gms.get_aspect("dataset", DEMO_PARTNER, "upstreamLineage")
        value = merge_upstreams(before, add=[{
            "dataset": focus, "type": "TRANSFORMED",
            "auditStamp": {"time": now_ms, "actor": "urn:li:corpuser:__datahub_system"}}])
        wb.aspect("dataset", DEMO_PARTNER, "upstreamLineage", value)
        note(f"edge declared, {len(value['upstreams'])} upstream(s) now on target",
             len(value["upstreams"]))
        return {"upstreams": len(value["upstreams"]), "expect": "dead"}

    if name == "remove-edge":
        # probate.correct hat keine eigene remove_edge()-Funktion (Task-19-
        # Lane darf probate/** nicht anfassen) -- dieselben zwei Bausteine
        # (merge_upstreams(drop=...), wb.aspect()) direkt hier verdrahtet,
        # kein dritter Schreibweg.
        #
        # Opus-Review-Nachtrag (07.08., waehrend dieser Aufgabe): dieselbe
        # Fehlerklasse wie der behobene mark_dead-Fund in correct.py
        # (apply_proposal, Task-12-Review IMPORTANT 3) -- merge_upstreams(
        # before=None, drop=[...]) liefert {"upstreams": []}, eine NIE
        # gemessene Behauptung "dieses Dataset hat keine Upstreams". Zwei
        # Vorbedingungen werden deshalb geprueft, VOR jedem Schreiben, mit
        # derselben Disziplin: (a) es gibt ueberhaupt schon eine
        # upstreamLineage, (b) die zu entfernende Kante steht wirklich
        # drin. Beide Male: laut verweigern statt still nichts (oder etwas
        # Erfundenes) zu schreiben -- der Mensch druecke einen Knopf und
        # erwartet eine sichtbare Wirkung oder einen sichtbaren Fehler.
        before = gms.get_aspect("dataset", DEMO_PARTNER, "upstreamLineage")
        if before is None:
            raise ValueError(
                f"kante entfernen verweigert: {DEMO_PARTNER!r} hat noch keine "
                "upstreamLineage -- nichts zu entfernen, kein leerer aspekt wird erfunden"
            )
        existing_urns = {u.get("dataset") for u in (before.get("value") or {}).get("upstreams") or []}
        if focus not in existing_urns:
            raise ValueError(
                f"kante entfernen verweigert: {focus!r} steht nicht in der bestehenden "
                f"upstreamLineage von {DEMO_PARTNER!r} -- der knopf haette sonst nichts veraendert"
            )
        value = merge_upstreams(before, drop=[focus])
        result = wb.aspect("dataset", DEMO_PARTNER, "upstreamLineage", value)
        note(f"edge removed, {len(value['upstreams'])} upstream(s) remain on target",
             len(value["upstreams"]))
        return {"removed": 1, "applied": result.applied, "expect": "missing"}

    if name == "cut-warehouse":
        # Nimmt die DATENLAGE weg, nicht den Verkehr. Genau das ist der
        # Unterschied, den die alte Fassung verschluckt hat.
        #
        # Zwei live gemessene Korrekturen gegenueber dem Brief-Entwurf
        # (07.08., waehrend dieser Aufgabe -- "aktueller Code gewinnt" bei
        # widerlegtem Entwurf, derselbe Vorrang wie schon in ledger.py und
        # werkbank.js dokumentiert):
        #
        # 1. ZIEL: nicht `focus` (das UPSTREAM), sondern DEMO_PARTNER (das
        #    DOWNSTREAM). classify_edges() bestimmt die Abdeckung ueber
        #    `usage_evidence(target)` mit target=downstream (ledger.py:
        #    "for target in sorted(declared | set(cooccurred))") -- die
        #    Nutzungsdaten des UPSTREAMS fliessen in DIESE Kante nie ein.
        #    Mit `focus` als Ziel haette der Knopf sichtbar nichts bewirkt.
        # 2. MECHANIK: nicht `gms.delete_aspect()` (openapi/v3, EIN
        #    Zeitreihen-Dokument). Live gemessen: `datasetUsageStatistics`
        #    ist eine Zeitreihe mit MEHREREN Buckets (hier: 3); ein
        #    einzelnes DELETE entfernt nur den "aktuellen" Snapshot, die
        #    GraphQL-Aggregation (usageStats), die ledger.py tatsaechlich
        #    liest, sah danach unveraendert `buckets_seen: 3` und die Kante
        #    blieb "confirmed" statt "unknown" zu werden -- der Knopf haette
        #    behauptet zu wirken, ohne zu wirken (genau der Fehler, gegen
        #    den dieses Projekt antritt). `harness/seed_lineage_lab.py::
        #    purge_usage_history()` loest dasselbe Problem bereits ueber
        #    `/entities?action=delete` mit vollem Zeitfenster -- derselbe
        #    Weg hier, `gms._send()` direkt (wie dort begruendet: weder
        #    probate/gms.py noch harness/** duerfen in dieser Aufgabe
        #    angefasst werden, und probate/gms.py bietet diesen Endpunkt
        #    nicht als eigene Methode an).
        from probate.gms import _validate_urn as _gms_validate_urn
        _gms_validate_urn(DEMO_PARTNER)  # dieselbe Disziplin wie seed_lineage_lab.py:715-721
        far_future_ms = 4_102_444_800_000  # 2100-01-01 UTC, deckt jeden plausiblen Bucket ab
        payload = {"urn": DEMO_PARTNER, "aspectName": "datasetUsageStatistics",
                   "startTimeMillis": 0, "endTimeMillis": far_future_ms}
        status, body = gms._send("POST", f"{gms.base}/entities?action=delete", payload)
        if status != 200:
            raise ValueError(f"warehouse trennen fehlgeschlagen: HTTP {status}")
        removed = ((body or {}).get("value") or {}).get("timeseriesRows", 0)
        note(f"usage timeseries purged on 1 dataset ({removed} row(s)) — coverage collapses",
             removed)
        return {"deleted": removed, "expect": "unknown"}

    if name == "fast-forward":
        _view_offset_days += 30
        note(f"observation window moved forward {_view_offset_days} days (view only)",
             _view_offset_days)
        return {"now_ms_offset_days": _view_offset_days, "expect": "aged"}

    if name == "run-ledger":
        # `full_run` ist der Lauf ueber ALLE beobachteten Fokusse (der
        # Server reicht ihn herein). Ohne ihn -- z.B. in einem Test, der
        # do_action() direkt aufruft -- bleibt der Ein-Fokus-Lauf, damit
        # diese Funktion ohne Server-Kontext lauffaehig bleibt.
        now = now_ms + _view_offset_days * 86_400_000
        if full_run is not None:
            out = full_run(now)
        else:
            from probate.ledger import run as ledger_run
            out = ledger_run(gms, focus, now)
        note(f"full check: {out['edges_total']} edges, {out['api_calls']} API calls",
             out["edges_total"])
        return out

    raise KeyError(name)


_view_offset_days = 0


def reset_view_offset(note) -> dict:
    """Opus-Review-Nachtrag (IMPORTANT 5): `_view_offset_days` akkumuliert
    sonst fuer die gesamte Prozesslaufzeit, unsichtbar -- 13 Knopfdruecke
    sind 420 Tage, und jede SPAETERE Messung (`run-ledger`) wird gegen
    diese verschobene Sicht gerechnet. Ein Juror, der zweimal aus
    Neugier "Zeit vorspulen" drueckt, vergiftet lautlos den Rest der
    Demo. Kein siebter/sechster Knopf (die Spec bindet genau sechs) --
    eine Sicherheitsfunktion daneben, die wie `fast-forward` NICHTS
    schreibt (dieselbe Garantie, dieselbe Sperre)."""
    global _view_offset_days
    with _ACTION_LOCK:
        _view_offset_days = 0
    note("observation window reset to now (view only)", 0)
    return {"now_ms_offset_days": 0}


# --- Modell-Urteile, im Hintergrund, mit gemessenen Kosten ---------------
#
# WARUM im Hintergrund und nicht im /api/ledger-Aufruf: der
# deterministische Befund steht in ~1s, ein Modellaufruf dauerte live
# 17.8-23.1s (harness/runs/judge-seedlab-matrix.json). Drei abweichende
# Kanten sind also gut eine Minute. Wer das an die Register-Antwort
# haengt, laesst einen Juror eine Minute auf einen leeren Bildschirm
# schauen -- und versteckt genau das, was die Spec sehen will: dass hier
# gerechnet und nicht abgespielt wird. So waechst stattdessen das
# Protokoll waehrend der Rechnung, Zeile fuer Zeile, mit Sekunden und
# Kosten pro Aufruf.
#
# WARUM ein Zustand pro Prozess und keine Warteschlange: es gibt genau
# einen Bildschirm und einen Menschen davor. Ein zweiter Lauf, waehrend
# der erste rechnet, wird abgelehnt statt eingereiht -- zwei parallele
# Urteilslaeufe ueber dieselbe Kante wuerden sich gegenseitig
# ueberschreiben, und welcher gewinnt, waere Zufall.
_JUDGE_LOCK = threading.Lock()
_JUDGE_LIMIT = 5

_judge_state: dict = {
    "running": False, "expected": 0, "done": 0,
    "calls": 0, "seconds": 0.0, "cost_usd": 0.0, "cost_measured": True,
    "judgements": {}, "error": "", "started_ms": None, "finished_ms": None,
}


def judge_snapshot() -> dict:
    """Der aktuelle Stand als JSON-taugliche Kopie. `judgements` ist eine
    Liste, keine Map -- die Reihenfolge, in der die Urteile eintrafen, ist
    selbst eine Aussage (welche Kante das Modell zuerst beschaeftigt hat)."""
    with _JUDGE_LOCK:
        return {
            "running": _judge_state["running"],
            "expected": _judge_state["expected"],
            "done": _judge_state["done"],
            "calls": _judge_state["calls"],
            "seconds": round(_judge_state["seconds"], 2),
            "cost_usd": (round(_judge_state["cost_usd"], 6)
                          if _judge_state["cost_measured"] else None),
            "error": _judge_state["error"],
            "started_ms": _judge_state["started_ms"],
            "finished_ms": _judge_state["finished_ms"],
            "judgements": list(_judge_state["judgements"].values()),
        }


def _short(urn: str) -> str:
    """Nur fuer Protokollzeilen: der TABELLENNAME, ohne Namensraum und
    ohne URN-Huelle. Der Namensraum wiederholt sich in jeder Zeile
    identisch und drueckte die Protokollspalte in den Umbruch (im Browser
    gesehen, 07.08.). Die volle URN steht im Register, nichts geht
    verloren."""
    m = re.search(r",([^,]+),[A-Za-z]+\)$", urn or "")
    full = m.group(1) if m else (urn or "")
    return full.rsplit(".", 1)[-1] if "." in full else full


def start_judging(gms, ledger: dict, note, transport_factory=None) -> bool:
    """Startet den Urteilslauf, falls keiner laeuft. Rueckgabe: gestartet
    ja/nein -- ein `False` ist kein Fehler, sondern die Weigerung, zwei
    Laeufe uebereinanderzulegen."""
    from ui.judging import deviating_rows

    rows = deviating_rows(ledger, _JUDGE_LIMIT)
    with _JUDGE_LOCK:
        if _judge_state["running"]:
            return False
        _judge_state.update({
            "running": True, "expected": len(rows), "done": 0,
            "calls": 0, "seconds": 0.0, "cost_usd": 0.0, "cost_measured": True,
            "judgements": {}, "error": "",
            "started_ms": int(time.time() * 1000), "finished_ms": None,
        })

    if not rows:
        with _JUDGE_LOCK:
            _judge_state["running"] = False
            _judge_state["finished_ms"] = int(time.time() * 1000)
        note("no deviating edges — the model is not called for confirmed edges", 0)
        return True

    note(f"model queue: {len(rows)} deviating edge(s) — confirmed edges are not sent", len(rows))

    def worker():
        from ui.judging import judge_edges_metered

        def on_result(judgement: dict, meter: dict) -> None:
            row = {**judgement,
                   "seconds": meter.get("seconds"),
                   "cost_usd": meter.get("cost_usd"),
                   "transport_ok": bool(meter.get("ok")),
                   "transport_error": meter.get("error", "")}
            with _JUDGE_LOCK:
                _judge_state["judgements"][judgement["edge"]] = row
                _judge_state["done"] += 1
                _judge_state["calls"] += 1
                _judge_state["seconds"] += meter.get("seconds") or 0.0
                if isinstance(meter.get("cost_usd"), (int, float)):
                    _judge_state["cost_usd"] += meter["cost_usd"]
                else:
                    _judge_state["cost_measured"] = False
            up, _, down = judgement["edge"].partition("->")
            cost = meter.get("cost_usd")
            money = f"${cost:.4f}" if isinstance(cost, (int, float)) else "cost not reported"
            outcome = ("cited a quote, judged important" if judgement.get("used_model") and judgement.get("important")
                       else "cited a quote, judged not important" if judgement.get("used_model")
                       # Der GENAUE Grund steht uebersetzt in der Zeile des
                       # Registers (mit dem deutschen Original im title). Ihn hier
                       # roh zu interpolieren haette deutschen Text in eine
                       # englische Oberflaeche getragen -- oder eine zweite
                       # Uebersetzungstabelle in Python verlangt.
                       else "abstained — no verbatim quote survived the citation check")
            note(f"model call {_short(up)} -> {_short(down)}: {outcome} "
                 f"— {meter.get('seconds')}s, {money}", meter.get("cost_usd"))

        try:
            judge_edges_metered(gms, ledger, on_result, limit=_JUDGE_LIMIT,
                                transport_factory=transport_factory)
        except Exception as exc:  # der Thread darf nicht stumm sterben
            with _JUDGE_LOCK:
                _judge_state["error"] = f"{type(exc).__name__}: {exc}"[:200]
            note(f"model run stopped: {type(exc).__name__}", None)
        finally:
            with _JUDGE_LOCK:
                _judge_state["running"] = False
                _judge_state["finished_ms"] = int(time.time() * 1000)
                total = _judge_state["cost_usd"] if _judge_state["cost_measured"] else None
                calls = _judge_state["calls"]
                secs = round(_judge_state["seconds"], 2)
            money = f"${total:.4f}" if total is not None else "cost not reported"
            note(f"model run done: {calls} call(s), {secs}s, {money}", calls)

    threading.Thread(target=worker, name="werkbank-judge", daemon=True).start()
    return True


# --- Security-Checkliste Punkt 7: nie ohne validiertes Ziel schreiben -----

_FORBIDDEN_GMS_PORTS = {
    8080: "joels whatsapp-bruecke",
    18080: "showcase-ecommerce -- die messdaten-instanz einer geschwister-einreichung",
    3000: "das cockpit",
}
_ALLOWED_GMS_HOSTS = {"127.0.0.1", "localhost"}


def _validate_gms_target(gms_url: str) -> None:
    parsed = urlparse(gms_url)
    if parsed.hostname not in _ALLOWED_GMS_HOSTS:
        raise SystemExit(
            f"--gms verweigert: host {parsed.hostname!r} ist nicht 127.0.0.1/localhost"
        )
    if parsed.port in _FORBIDDEN_GMS_PORTS:
        raise SystemExit(
            f"--gms verweigert: port {parsed.port} traegt "
            f"{_FORBIDDEN_GMS_PORTS[parsed.port]} -- nie hierher schreiben"
        )


class ApiError(Exception):
    """Ein absichtlich abgelehnter Request. `text` ist IMMER ein fester,
    vorformulierter Satz -- nie eine interpolierte Exception-Nachricht
    (Punkt 11: kein str(GmsError) in der HTTP-Antwort)."""

    def __init__(self, code: int, text: str) -> None:
        super().__init__(text)
        self.code = code
        self.text = text


_ERROR_ID = itertools.count(1)
_MAX_BODY_BYTES = 64 * 1024
# Opus-Review-Nachtrag (IMPORTANT 4): eine ueberhoehte Content-Length ohne
# genug tatsaechlich gesendete Bytes liess `rfile.read(n)` unbegrenzt
# blockieren -- kein Socket-Timeout, keine Laengen-Gegenprobe. Ein
# lokales Slowloris: jeder haengende Handler-Thread ist ein Leck, auch
# wenn ThreadingHTTPServer andere Verbindungen weiterbedient.
_BODY_READ_TIMEOUT_S = 5.0


def build_handler(gms_url: str, focus: str, log: list):
    """Baut die Handler-Klasse erst hier, nicht auf Modulebene -- damit
    `import ui.serve` (fuer route()/ACTIONS/PORT_DEFAULT in den Tests)
    nicht schon ein GMS/Writeback-Geflecht mitzieht, das ohne laufende
    Instanz gar nicht existieren muss."""
    from probate.gms import Gms

    _validate_gms_target(gms_url)  # Punkt 7 -- an der einen Stelle, die JEDE Instanz durchlaeuft.

    # Ein Fokus oder viele -- der Rest des Servers kennt nur noch die
    # Liste. `--focus <urn>` (ein String) bleibt gueltig, weil genau so
    # jeder bestehende Aufruf und jeder Test diese Funktion betritt.
    focus_list = [focus] if isinstance(focus, str) else list(focus)
    focus_list = [f for f in focus_list if f]

    _cached_ledger: dict | None = None

    def note(text: str, number=None) -> None:
        """Jede Protokollzeile traegt eine Zahl, kein Gefuehl."""
        log.append({"t": int(time.time() * 1000), "text": text, "n": number})

    def run_full_ledger(gms, now_ms: int) -> dict:
        """Ein Lauf pro Fokus, zu EINEM Register zusammengelegt.

        Die Zusammenlege-Regel wird NICHT hier ein zweites Mal
        geschrieben: `harness.record_ledger.combine_runs` ist bereits die
        Stelle, die vier Einzel-Laeufe zu einem Register macht (mit
        Neuzaehlung der Zustands-Summen und der bewussten Entscheidung,
        `coverage_days_span` als Spanne statt als Summe zu fuehren), und
        sie hat eigene Tests. Zwei Zusammenlege-Regeln waeren zwei
        Wahrheiten -- und die Aufzeichnung saehe anders aus als der
        Live-Modus, obwohl beide dieselben Daten zeigen sollen.

        Die einzige Korrektur danach: `recording`/`seeded` beschreiben die
        HERKUNFT. `combine_runs` setzt beide fest auf True, weil es fuer
        die Aufzeichnung geschrieben wurde. Live ist der Lauf gerade
        entstanden -- `recording: False`. `seeded` bleibt True, denn die
        Daten sind wirklich eingespielt (`seeded_statement` im Manifest).
        """
        from harness.record_ledger import combine_runs
        from probate.ledger import run as ledger_run

        nonlocal _cached_ledger
        runs = [ledger_run(gms, f, now_ms) for f in focus_list]
        out = combine_runs(runs)
        out["recording"] = False
        out["live"] = True
        out["seeded_statement"] = SEEDED_STATEMENT
        out["demo_focus"] = DEMO_FOCUS
        out["demo_partner"] = DEMO_PARTNER
        # Der Lauf bleibt liegen: /api/connections filtert und blaettert
        # DIESEN Lauf, statt ihn pro Seitenwechsel neu zu messen (ein
        # Register-Lauf sind echte GMS-Aufrufe -- Bezahlung pro Klick
        # waere eine erfundene Last, keine Funktion).
        _cached_ledger = out
        return out

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(UI_DIR), **kw)

        def end_headers(self):
            """Kein Zwischenspeicher fuer die statischen Dateien.

            Gemessen 07.08.: nach dem Umbau der Oberflaeche lieferte der
            Browser auf Port 8899 weiter das ALTE werkbank.css und
            werkbank.js aus (SimpleHTTPRequestHandler schickt nur
            Last-Modified, Chrome speichert dann heuristisch zwischen) --
            sichtbar als voellig ungestylte Seite mit leerem Register,
            waehrend die Dateien auf der Platte laengst neu waren. Eine
            Werkbank, die eine alte Fassung ihrer selbst zeigt, ist genau
            die Sorte stiller Falschaussage, gegen die dieses Projekt
            antritt -- und ein Juror, der neu laedt, darf nie eine
            veraltete Oberflaeche sehen."""
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _json(self, payload, code=200) -> bool:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True  # "behandelt" -- ohne diesen Rueckgabewert faellt
            # do_GET/do_POST auf super().do_GET() durch und JEDE API-Antwort
            # wird von einem zweiten 404 ueberschrieben (siehe Moduldocstring).

        def _error(self, code: int, text: str) -> bool:
            # Punkt 11: struktierte Fehlerantwort, fester Text, eine Zaehl-ID
            # zum Zuordnen im Log -- niemals die rohe Exception im Body.
            self.close_connection = True  # der Request-Koerper wurde evtl.
            # nie gelesen (z.B. bei einer Host-Ablehnung vor jedem route()) --
            # die Verbindung wird nicht fuer ein Pipelining wiederverwendet.
            return self._json({"error": text, "id": next(_ERROR_ID)}, code)

        def _allowed_netlocs(self) -> set[str]:
            port = self.server.server_address[1]
            return {f"127.0.0.1:{port}", f"localhost:{port}"}

        def _enforce_request_origin(self, method: str) -> None:
            """Punkt 1: Cross-Origin VOR jedem Dispatch abweisen -- gemessener
            Befund war ein Cross-Origin-POST, der die do_action-Zeile erreichte.
            Reihenfolge: Host zuerst (haerteste Pruefung, jeder Request traegt
            ihn), dann Origin (nur wenn vorhanden -- gleicher-Ursprung-GETs
            schicken ihn oft gar nicht), dann X-Probate.

            Opus-Review-Nachtrag (IMPORTANT 6): X-Probate war nur fuer POST
            Pflicht. Eine "einfache" GET-Anfrage (`<img src>`/`<script src>`)
            traegt NIE einen Origin- und NIE einen Custom-Header -- SOP
            verhindert nur, dass die fremde Seite die ANTWORT lesen kann,
            nicht dass sie den echten GET ueberhaupt AUSLOEST ("confused
            deputy": jede fremde Seite koennte `/api/ledger` kostenpflichtig
            gegen GMS feuern lassen, ohne die Antwort je zu sehen). X-Probate
            ist deshalb jetzt fuer JEDE Methode unter /api/* Pflicht."""
            allowed_hosts = self._allowed_netlocs()
            host = self.headers.get("Host", "")
            if host not in allowed_hosts:
                raise ApiError(403, "host abgelehnt")
            origin = self.headers.get("Origin")
            if origin is not None:
                allowed_origins = {f"http://{h}" for h in allowed_hosts}
                if origin not in allowed_origins:
                    raise ApiError(403, "cross-origin abgelehnt")
            if self.headers.get("X-Probate") != "1":
                raise ApiError(403, "x-probate-header fehlt")

        def _read_json_body(self) -> None:
            """Punkt 2: Content-Length lesen und begrenzen, Content-Type
            erzwingen -- zweite CSRF-Barriere neben X-Probate. Der Inhalt
            wird bewusst nicht ausgewertet (kein Knopf braucht heute ein
            Client-Feld), nur seine FORM ist die Pruefung.

            Opus-Review-Nachtrag (IMPORTANT 4): eine ueberhoehte Content-
            Length ohne genug tatsaechlich gesendete Bytes liess
            `rfile.read(n)` vorher unbegrenzt blockieren. Socket-Timeout
            plus Laengen-Gegenprobe (`len(raw) != n`) schliessen beides --
            ein kurzer Read wird jetzt erkannt statt stillschweigend als
            vollstaendig behandelt."""
            length = self.headers.get("Content-Length")
            if length is None:
                raise ApiError(400, "content-length fehlt")
            try:
                n = int(length)
            except ValueError:
                raise ApiError(400, "content-length unlesbar")
            if n < 0 or n > _MAX_BODY_BYTES:
                raise ApiError(400, "body zu gross")
            ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if ctype != "application/json":
                raise ApiError(400, "content-type muss application/json sein")
            raw = b""
            if n:
                self.connection.settimeout(_BODY_READ_TIMEOUT_S)
                try:
                    raw = self.rfile.read(n)
                except (_SocketTimeout, OSError):
                    raise ApiError(400, "body-uebertragung abgebrochen oder zu langsam")
                finally:
                    self.connection.settimeout(None)  # restlichen Verbindungslebenszyklus nicht beeinflussen
                if len(raw) != n:
                    raise ApiError(400, "body kuerzer als angekuendigt")
            if raw:
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise ApiError(400, "body ist kein gueltiges json")
                if not isinstance(body, dict):
                    raise ApiError(400, "body muss ein json-objekt sein")

        def _console(self, kind: str, args: dict, gms):
            """Die vier Lese-Wege der Konsole. Alle vier antworten mit
            `total` neben den Zeilen -- ohne diese Zahl kann die Seite
            "N von 5.594" nicht schreiben, und genau diese Einordnung
            fehlte der alten Oberflaeche."""
            from ui import console_api as api

            params = args.get("params") or {}
            ledger = _cached_ledger
            edges = (ledger or {}).get("edges") or []
            judged = {j["edge"]: j for j in judge_snapshot()["judgements"]}

            if kind == "connections":
                out = api.filter_sort_page(edges, judged, params)
                out["facets"] = api.facets(edges)
                out["has_run"] = ledger is not None
                out["generated_at_ms"] = (ledger or {}).get("generated_at_ms")
                return self._json(out)

            if kind == "catalog":
                known = {}
                for e in edges:
                    known[e.get("upstream", "")] = e.get("state", "")
                    known.setdefault(e.get("downstream", ""), e.get("state", ""))
                out = api.catalog_page(
                    gms, params.get("q", "*"),
                    int(params.get("start") or 0), int(params.get("count") or 50),
                    known)
                return self._json(out)

            if kind == "runs":
                return self._json({"runs": api.runs()})

            return self._json({"items": api.evidence(edges, judged, params.get("q", ""))})

        def _handle(self, method):
            u = urlparse(self.path)
            try:
                if u.path.startswith("/api/"):
                    self._enforce_request_origin(method)
                try:
                    kind, args = route(method, u.path, parse_qs(u.query))
                except (KeyError, ValueError):
                    return None
                if kind == "reset-time":
                    # Vor `Gms(gms_url)`: reset schreibt nichts, braucht
                    # gar keine GMS-Verbindung (dieselbe Garantie wie
                    # fast-forward -- Opus-Review-Nachtrag Punkt 5).
                    return self._json(reset_view_offset(note))
                gms = Gms(gms_url)
                if kind == "mode":
                    # Opus-Review-Nachtrag (MINOR 9): `view_offset_days` mit
                    # ausliefern, damit werkbank.js die Sicht-Verschiebung
                    # sichtbar machen kann statt sie unsichtbar zu lassen.
                    return self._json({"mode": "live", "gms": gms_url,
                                        "focus": focus_list[0] if focus_list else "",
                                        "focuses": focus_list,
                                        "demo_focus": DEMO_FOCUS,
                                        "demo_partner": DEMO_PARTNER,
                                        "seeded_statement": SEEDED_STATEMENT,
                                        "view_offset_days": _view_offset_days})
                if kind == "log":
                    return self._json({"entries": log[args["since"]:], "cursor": len(log)})
                if kind == "judgements":
                    return self._json(judge_snapshot())
                if kind in ("connections", "catalog", "runs", "evidence"):
                    return self._console(kind, args, gms)
                if kind == "ledger":
                    out = run_full_ledger(gms, int(time.time() * 1000)
                                           + _view_offset_days * 86_400_000)
                    note(f"full check: {out['edges_total']} edge(s) over "
                         f"{len(focus_list)} focus dataset(s), {out['api_calls']} API calls",
                         out["edges_total"])
                    # KEIN Modellaufruf an dieser Stelle. Jeder Knopfdruck
                    # holt das Register neu -- ein Urteilslauf pro Abruf
                    # waere ein Modellaufruf je Kante je Klick (gemessen:
                    # 3 Aufrufe, $0.74, 52s pro Lauf). Das Modell laeuft
                    # nur, wenn jemand "Re-check everything" drueckt.
                    return self._json(out)
                if kind == "action":
                    self._read_json_body()
                    # Die Knoepfe schreiben immer auf DIESELBE Kante
                    # (`DEMO_FOCUS` -> `DEMO_PARTNER`, beide aus dem
                    # Manifest). Vorher war es `--focus`, und `--focus` ist
                    # jetzt die LISTE der beobachteten Datensaetze -- eine
                    # Aktion "auf alle vier" waere keine Demo, sondern vier
                    # gleichzeitige Schreibvorgaenge ohne sichtbaren Bezug.
                    result = do_action(args["name"], gms, DEMO_FOCUS, note,
                                        full_run=lambda now: run_full_ledger(gms, now))
                    if args["name"] == "run-ledger":
                        start_judging(gms, result, note)
                    return self._json(result)
                return None
            except ApiError as e:
                return self._error(e.code, e.text)
            except (ValueError, KeyError) as e:
                # z.B. eine abgelehnte URN aus _validate_action_urn -- ein
                # Anfrageproblem, kein Serverfehler.
                print(f"werkbank: anfrage abgelehnt -- {e}", file=sys.stderr)
                return self._error(400, "anfrage abgelehnt")
            except Exception as e:
                # Punkt 11 / geerbter Task-18-Befund: die alte Fassung liess
                # eine Exception hier die Verbindung stumm abbrechen statt
                # einer HTTP-Antwort. `str(e)` (kann bis zu 400 Zeichen GMS-
                # Rohantwort tragen, GmsError) geht NUR nach stderr, nie in
                # den Response-Body.
                print(f"werkbank: unerwarteter fehler -- {e}", file=sys.stderr)
                return self._error(500, "interner fehler")

        def do_GET(self):
            if self._handle("GET") is None:
                super().do_GET()

        def do_POST(self):
            if self._handle("POST") is None:
                self.send_error(404)

        def log_message(self, fmt, *a):
            """Stdlib loggt jeden Request auf stderr -- unterdrueckt, weil
            `note()`/log[] bereits das sichtbare Protokoll der Werkbank ist
            und ein zweites, unstrukturiertes Protokoll nur Rauschen waere."""
            pass

    return H


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="ui.serve",
        description="Werkbank-Proxy: serviert ui/ statisch und reicht "
                     "API-Aufrufe an GMS/probate weiter (CORS geloescht "
                     "statt beantwortet).",
    )
    parser.add_argument("--gms", default="http://localhost:28080",
                         help="GMS-Basis-URL (Standard: http://localhost:28080)")
    # WIEDERHOLBAR, und ohne Angabe die vier Seedlab-Fokusse aus dem
    # Manifest. Der Vorgabe-Wert war frueher der LEERE String: ein blosser
    # Start beobachtete damit nichts, und ein Start mit genau einem
    # `--focus` zeigte genau eine Kante -- also entweder vier Zustaende
    # ohne Knoepfe (Aufzeichnung) oder Knoepfe mit einer Kante (Live).
    # Beides ist keine Demo. Jetzt: `python -m ui.serve` reicht.
    parser.add_argument("--focus", action="append", default=None, metavar="URN",
                         help="URN einer beobachteten Tabelle; mehrfach angebbar. "
                              "Ohne Angabe: die vier Fokusse aus "
                              "examples/seedlab-manifest.json")
    parser.add_argument("--port", type=int, default=PORT_DEFAULT)
    args = parser.parse_args(argv)

    focuses = args.focus or MANIFEST_FOCUSES
    if not focuses:
        raise SystemExit(
            "werkbank: kein Fokus -- weder --focus noch ein lesbares "
            f"{MANIFEST_PATH}. Ein Register ueber nichts waere eine leere Behauptung."
        )

    log: list = []
    handler_cls = build_handler(args.gms, focuses, log)  # validiert --gms (Punkt 7)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_cls)
    print(f"werkbank live: http://127.0.0.1:{args.port} -- gms {args.gms}")
    print(f"  {len(focuses)} focus dataset(s): " + ", ".join(_short(f) for f in focuses))
    print(f"  buttons write on: {_short(DEMO_FOCUS)} -> {_short(DEMO_PARTNER)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
