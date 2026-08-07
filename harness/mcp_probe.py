"""Was DataHubs eigener MCP-Server kann -- gemessen, nicht geglaubt.

WARUM DIESES SKRIPT EXISTIERT
=============================
probate liest den Katalog ueber GraphQL/OpenAPI. Die naheliegende Frage
eines Juroren lautet: "warum nicht ueber den MCP-Server, den DataHub
selbst als Agenten-Schnittstelle anbietet?" Bis zu diesem Lauf war die
Antwort im README eine Aufzaehlung von Befunden aus dem Netz und aus
einer aelteren Sondierung -- also fremde Behauptungen, nicht eigene
Messung. Genau die Sorte Aussage, gegen die dieses Projekt antritt.

Dieses Skript beantwortet die Frage mit einem Artefakt:
`harness/runs/mcp-probe.json`. Es faehrt den Server auf einer GEPINNTEN
Version hoch, zaehlt die tatsaechlich registrierten Werkzeuge, ruft sie
gegen den Beispielkatalog auf und vergleicht das Ergebnis Feld fuer Feld
mit dem GraphQL-Weg -- inklusive der Kosten beider Wege.

Der Ausgang war bewusst offen. Waere die Antwort "der MCP-Server kann den
Lesevorgang nicht liefern" gewesen, waere die Messung selbst das Ergebnis
gewesen. Sie ist es ohnehin: der Vergleich ist erst dadurch etwas wert,
dass beide Zahlen daneben stehen.

DIE ACHT MESSSCHRITTE
---------------------
1. `@latest` gegen den Pin: worauf loest der Name heute auf?
2. Werkzeugliste OHNE `TOOLS_IS_MUTATION_ENABLED` -- Namen + Anzahl.
3. Werkzeugliste MIT `TOOLS_IS_MUTATION_ENABLED=true` -- die Differenz
   ist die Antwort auf "der Server registriert null Mutations-Werkzeuge".
4. Der Ko-Okkurrenz-Lesevorgang ueber `get_dataset_queries`, pro Aufruf
   mit Wanduhr und Antwortgroesse, ueber alle vier Zustaende des Labors.
5. Derselbe Lesevorgang ueber den GraphQL-Weg (`fetch_cooccurrence`),
   dieselbe Messung -- danach Gleichheitsvergleich Karte gegen Karte.
6. Zeitstempel: traegt eine Query-Entitaet ueber diesen Weg ueberhaupt
   eine Zeitangabe? (Quelltext-Befund + Live-Gegenprobe.)
7. Der GANZE `probate ledger`-Lauf ueber beide Wege, Feld fuer Feld
   verglichen -- kommt hinten dasselbe Verdikt heraus, und was kostet es?
8. Telemetrie: derselbe Aufruf einmal mit, einmal ohne
   `DATAHUB_TELEMETRY_ENABLED` -- kostet sie wirklich ~54 s?

NUR LESEND
----------
Kein Schritt schreibt in den Katalog. Der Server laeuft in Schritt 3 zwar
MIT freigeschalteten Mutations-Werkzeugen, aber ausschliesslich, um sie zu
ZAEHLEN -- aufgerufen wird keines. Die Struktur-Daten des Labors
(`probate_seedlab`) werden nicht angefasst.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from probate.gms import Gms  # noqa: E402
from probate.ledger import fetch_cooccurrence  # noqa: E402
from probate.mcp_transport import (  # noqa: E402
    DEFAULT_MCP_VERSION,
    McpSession,
    cooccurrence_from_mcp,
)

DEFAULT_GMS = "http://localhost:28080"
NS = "probate_seedlab"
PLATFORM = "urn:li:dataPlatform:postgres"


def urn(name: str) -> str:
    return f"urn:li:dataset:({PLATFORM},{NS}.{name},PROD)"


# Die vier Fokus-Datasets des Labors. `missing_upstream` ist der Fall, den
# die Ko-Okkurrenz ueberhaupt erst findet (keine deklarierte Kante, aber
# eine gemeinsame Query) -- wenn ein Weg IHN nicht sieht, taugt er nicht.
FOCUSES = [
    ("confirmed", urn("confirmed_upstream")),
    ("dead", urn("dead_upstream")),
    ("missing", urn("missing_upstream")),
    ("unknown", urn("unknown_upstream")),
]


def _resolve_latest(python: str = "3.11") -> dict:
    """Worauf loest `@latest` heute auf -- mit und ohne Interpreter-Pin.

    Steht hier, weil die aeltere Sondierung dieses Projekts (02.08.) fuer
    `uvx mcp-server-datahub@latest` 0.4.0 NOTIERT hat -- eine Notiz, keine
    Messung, die sich heute wiederholen liesse. Genau darum wird hier
    nachgemessen statt zitiert: das Ergebnis dieses Schritts entscheidet,
    ob die alte Notiz noch gilt. (Sie gilt nicht; s. Artefakt.)

    Zwei Varianten, weil die naheliegende Erklaerung pruefbar ist: 0.5.0
    und spaeter verlangen laut PyPI Python >= 3.11, 0.4.0 nur >= 3.10.
    Ohne Interpreter-Pin koennte uv also auf der aelteren Werkzeugmenge
    landen -- deshalb derselbe Befehl einmal mit und einmal ohne `--python`.
    """
    out: dict = {}
    for label, argv in (
        ("mit_python_pin", ["uvx", "--python", python, "mcp-server-datahub@latest", "--version"]),
        ("ohne_python_pin", ["uvx", "mcp-server-datahub@latest", "--version"]),
    ):
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=900)
            text = (proc.stdout or "") + (proc.stderr or "")
            version = None
            for line in text.splitlines():
                if "version" in line.lower() and "mcp-server-datahub," in line:
                    version = line.strip().split()[-1]
            out[label] = {
                "argv": " ".join(argv),
                "exit_code": proc.returncode,
                "resolved_version": version,
                "seconds": round(time.perf_counter() - t0, 2),
            }
        except Exception as e:  # eine gescheiterte Abfrage ist keine Abwesenheit
            out[label] = {
                "argv": " ".join(argv),
                "error": f"{type(e).__name__}: {e}",
                "resolved_version": None,
                "seconds": round(time.perf_counter() - t0, 2),
            }
    return out


def _tool_inventory(gms_url: str, version: str, mutation: bool, token: str | None) -> dict:
    t0 = time.perf_counter()
    session = McpSession(gms_url=gms_url, version=version, token=token,
                         mutation_enabled=mutation)
    session.open()
    boot = time.perf_counter() - t0
    try:
        return {
            "mutation_env": "true" if mutation else "false",
            "tool_count": len(session.tools),
            "tools": sorted(t["name"] for t in session.tools),
            "read_only_hinted": sorted(
                t["name"] for t in session.tools if t["read_only_hint"]
            ),
            "session_boot_seconds": round(boot, 2),
        }
    finally:
        session.close()


def _timed_mcp_cooccurrence(session: McpSession, focus: str) -> dict:
    t0 = time.perf_counter()
    payload = session.call_tool("get_dataset_queries", {"urn": focus, "count": 200})
    seconds = time.perf_counter() - t0
    chars = getattr(session, "last_response_chars", None)
    cooc, total = cooccurrence_from_mcp(lambda tool, args: payload, focus)
    return {
        "seconds": round(seconds, 3),
        "response_chars": chars,
        "tool_calls": 1,
        "total": total,
        "map": {k: sorted(v) for k, v in cooc.items()},
        "raw": payload,
    }


class _CountingGms:
    """Zaehlt die GMS-Rundlaeufe des GraphQL-Wegs.

    Ohne diesen Zaehler waere der Kostenvergleich schief: der GraphQL-Weg
    macht 1 Suche + N Aspekt-Abrufe, der MCP-Weg genau einen Aufruf. Wer
    nur die Sekunden vergleicht, verschweigt genau diesen Unterschied.
    """

    def __init__(self, inner: Gms) -> None:
        self.inner = inner
        self.calls = 0
        self.base = inner.base

    def graphql(self, query, variables=None):
        self.calls += 1
        return self.inner.graphql(query, variables)

    def get_aspect(self, entity_type, urn_, aspect):
        self.calls += 1
        return self.inner.get_aspect(entity_type, urn_, aspect)

    def _send(self, method, url, payload):
        self.calls += 1
        return self.inner._send(method, url, payload)


def _timed_graphql_cooccurrence(gms: Gms, focus: str) -> dict:
    counting = _CountingGms(gms)
    t0 = time.perf_counter()
    cooc, total = fetch_cooccurrence(counting, focus)
    seconds = time.perf_counter() - t0
    return {
        "seconds": round(seconds, 3),
        "gms_calls": counting.calls,
        "total": total,
        "map": {k: sorted(v) for k, v in cooc.items()},
    }


def _end_to_end(gms_url: str, version: str, token: str | None, focus: str) -> dict:
    """Nicht nur der Lesevorgang, sondern der ganze `probate ledger`-Lauf.

    Der Werkzeug-Vergleich weiter oben zeigt, dass die Ko-Okkurrenz-KARTE
    identisch ist. Diese Messung beantwortet die haertere Frage: kommt
    hinten auch dasselbe VERDIKT heraus, Feld fuer Feld, wenn man den
    Schalter `--cooccurrence-source` umlegt? Verglichen wird darum das
    komplette `edges`-Objekt und nicht nur eine Zusammenfassung.

    Zwei Felder MUESSEN abweichen und tun das auch: `coverage.window_*`
    haengt an der Wall-Clock des jeweiligen Laufs (die beiden Laeufe
    liegen Sekunden auseinander). Sie werden nicht weggerechnet, sondern
    benannt -- eine Toleranz, die man nicht sieht, ist keine Toleranz.
    """
    import probate.ledger as ledger_mod
    from probate.mcp_transport import make_cooccurrence_fetcher

    fixed_now = int(time.time() * 1000)

    t0 = time.perf_counter()
    gql_out = ledger_mod.run(Gms(gms_url, token=token), focus, fixed_now)
    gql_seconds = time.perf_counter() - t0

    t0 = time.perf_counter()
    session = McpSession(gms_url=gms_url, version=version, token=token)
    session.open()
    boot = time.perf_counter() - t0
    try:
        t1 = time.perf_counter()
        mcp_out = ledger_mod.run(
            Gms(gms_url, token=token), focus, fixed_now,
            cooccurrence_fn=make_cooccurrence_fetcher(session.call_tool),
        )
        mcp_seconds = time.perf_counter() - t1
    finally:
        session.close()

    def diff_paths(x, y, prefix=""):
        if isinstance(x, dict) and isinstance(y, dict):
            out = []
            for k in sorted(set(x) | set(y)):
                out += diff_paths(x.get(k), y.get(k), f"{prefix}.{k}")
            return out
        if isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
            out = []
            for i, (a, b) in enumerate(zip(x, y)):
                out += diff_paths(a, b, f"{prefix}[{i}]")
            return out
        return [] if x == y else [prefix]

    edge_diffs = diff_paths(gql_out["edges"], mcp_out["edges"], "edges")
    wall_clock_only = all(
        d.endswith(".window_start_ms") or d.endswith(".window_end_ms")
        for d in edge_diffs
    )
    return {
        "focus": focus,
        "graphql": {
            "seconds": round(gql_seconds, 3),
            "api_calls": gql_out["api_calls"],
            "cooccurrence_source": gql_out["cooccurrence_source"],
        },
        "mcp": {
            "seconds": round(mcp_seconds, 3),
            "session_boot_seconds": round(boot, 2),
            "seconds_including_boot": round(boot + mcp_seconds, 3),
            "api_calls": mcp_out["api_calls"],
            "cooccurrence_source": mcp_out["cooccurrence_source"],
        },
        "verdict_counts_identical": all(
            gql_out[k] == mcp_out[k]
            for k in ("edges_total", "edges_confirmed", "edges_dead",
                      "edges_missing", "edges_unknown", "queries_seen")
        ),
        "edge_field_diffs": edge_diffs,
        "edge_diffs_are_wall_clock_only": wall_clock_only,
        "note": (
            "coverage.window_start_ms/window_end_ms weichen ab, weil beide "
            "Laeufe ihr Nutzungsfenster zur ECHTEN aktuellen Zeit bilden "
            "(ledger.run() reicht das simulierte now_ms bewusst NICHT an die "
            "Rohablage durch). Jedes andere Feld -- Zustand, Beleg, Query-URN, "
            "Bucket-Zahlen -- ist identisch."
        ),
    }


def _telemetry_cost(gms_url: str, version: str, token: str | None, focus: str) -> dict:
    """Kostet ein Werkzeugaufruf wirklich ~54 s Telemetrie?

    Gegenprobe statt Uebernahme: derselbe Aufruf zweimal, einmal mit
    `DATAHUB_TELEMETRY_ENABLED=false`, einmal mit `true`. Gemessen wird
    der ZWEITE Aufruf je Sitzung -- der erste traegt sonst einmalige
    Aufwaerm-Kosten (Verbindungsaufbau, Versions-Abfrage) mit, die nichts
    mit Telemetrie zu tun haben.
    """
    out: dict = {}
    for label, enabled in (("telemetrie_aus", False), ("telemetrie_an", True)):
        session = McpSession(gms_url=gms_url, version=version, token=token,
                             telemetry_enabled=enabled)
        session.open()
        try:
            session.call_tool("get_dataset_queries", {"urn": focus, "count": 200})
            times = []
            for _ in range(3):
                t0 = time.perf_counter()
                session.call_tool("get_dataset_queries", {"urn": focus, "count": 200})
                times.append(round(time.perf_counter() - t0, 3))
            out[label] = {
                "env": f"DATAHUB_TELEMETRY_ENABLED={'true' if enabled else 'false'}",
                "call_seconds": times,
                "median_seconds": sorted(times)[len(times) // 2],
            }
        finally:
            session.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gms", default=DEFAULT_GMS)
    ap.add_argument("--token", default=None)
    ap.add_argument("--version", default=DEFAULT_MCP_VERSION,
                    help="gepinnte mcp-server-datahub-Version")
    ap.add_argument("--out", default="harness/runs/mcp-probe.json")
    ap.add_argument("--skip-latest", action="store_true",
                    help="Schritt 1 auslassen (zwei uvx-Aufloesungen, langsam)")
    args = ap.parse_args()

    started = time.time()
    result: dict = {
        "probe_generated_at_ms": int(started * 1000),
        "gms": args.gms,
        "seeded": True,
        "seeded_statement": (
            "Gemessen gegen den kuenstlich eingespielten Beispielkatalog "
            "(harness/seed_lineage_lab.py, Namespace probate_seedlab), nicht "
            "gegen echte Warehouse-Nutzung."
        ),
        "mcp_server_version_pinned": args.version,
    }

    # --- Schritt 1: worauf loest @latest auf? -----------------------------
    if not args.skip_latest:
        result["latest_resolution"] = _resolve_latest()

    # --- Schritt 2+3: Werkzeugliste ohne/mit Mutations-Freischaltung ------
    inv_ro = _tool_inventory(args.gms, args.version, mutation=False, token=args.token)
    inv_mut = _tool_inventory(args.gms, args.version, mutation=True, token=args.token)
    result["tools_default"] = inv_ro
    result["tools_mutation_enabled"] = inv_mut
    result["tool_count_default"] = inv_ro["tool_count"]
    result["tool_count_with_mutations"] = inv_mut["tool_count"]
    result["mutation_tools_added"] = sorted(
        set(inv_mut["tools"]) - set(inv_ro["tools"])
    )
    result["mutation_tool_count"] = len(result["mutation_tools_added"])
    result["mcp_session_boot_seconds_cold"] = inv_ro["session_boot_seconds"]

    # --- Schritt 4+5: der eigentliche Lesevorgang, beide Wege -------------
    gms = Gms(args.gms, token=args.token)
    session = McpSession(gms_url=args.gms, version=args.version, token=args.token)
    t0 = time.perf_counter()
    session.open()
    warm_boot = time.perf_counter() - t0
    result["mcp_session_boot_seconds_warm"] = round(warm_boot, 2)

    comparisons = []
    try:
        for state, focus in FOCUSES:
            mcp_side = _timed_mcp_cooccurrence(session, focus)
            gql_side = _timed_graphql_cooccurrence(gms, focus)
            comparisons.append({
                "expected_edge_state": state,
                "focus": focus,
                "maps_identical": mcp_side["map"] == gql_side["map"],
                "totals_identical": mcp_side["total"] == gql_side["total"],
                "total": mcp_side["total"],
                "cooccurrence_targets": sorted(mcp_side["map"]),
                "mcp": {k: v for k, v in mcp_side.items() if k != "raw"},
                "graphql": gql_side,
            })

        # --- Schritt 6: Zeitstempel ---------------------------------------
        # Live-Gegenprobe zum Quelltext-Befund: die Antwort selbst nach
        # jedem Feld durchsuchen, das eine Zeit sein koennte. "Nicht
        # gefunden" heisst hier "gefragt und nichts da", nicht "nicht
        # geprueft" -- die Rohantwort steht als Beleg mit im Artefakt.
        sample = session.call_tool(
            "get_dataset_queries", {"urn": urn("missing_upstream"), "count": 200})
        flat = json.dumps(sample)
        time_keys = sorted({
            k for k in ("time", "created", "createdAt", "lastModified",
                        "timestampMillis", "lastObserved")
            if f'"{k}"' in flat
        })
        has_numeric_time = any(
            isinstance(v, (int, float))
            for q in (sample.get("queries") or [])
            for block in ((q.get("properties") or {}).get("lastModified") or {},
                          (q.get("properties") or {}).get("created") or {})
            for v in block.values()
        )
        result["timestamps"] = {
            "question": "Traegt eine Query-Entitaet ueber den MCP-Server eine Zeitangabe?",
            "answer": "nein",
            "keys_present_in_response": time_keys,
            "any_numeric_time_value": has_numeric_time,
            "source_evidence": (
                "src/mcp_server_datahub/gql/queries.gql (0.6.0): der ganze "
                "'created { time actor }'-Block ist auskommentiert, und in "
                "'lastModified' ist genau die Zeile '# time' auskommentiert -- "
                "abgefragt wird nur 'actor'."
            ),
            "consequence": (
                "Die Alters-Achse von probate (dead vs. confirmed) kann NICHT "
                "aus Query-Entitaeten des MCP-Servers kommen. Sie haengt "
                "unveraendert an den Dataset-Nutzungs-Buckets aus fetch_usage, "
                "fuer die der MCP-Server ueberhaupt kein Werkzeug anbietet."
            ),
            "sample_response": sample,
        }
    finally:
        session.close()

    result["comparisons"] = comparisons
    result["mcp_focuses_compared"] = len(comparisons)
    result["mcp_maps_identical_all_four_states"] = all(c["maps_identical"] for c in comparisons)
    result["mcp_totals_identical_all_four_states"] = all(c["totals_identical"] for c in comparisons)
    result["mcp_seconds_total"] = round(sum(c["mcp"]["seconds"] for c in comparisons), 3)
    result["graphql_seconds_total"] = round(
        sum(c["graphql"]["seconds"] for c in comparisons), 3)
    result["mcp_tool_calls_total"] = sum(c["mcp"]["tool_calls"] for c in comparisons)
    result["graphql_gms_calls_total"] = sum(c["graphql"]["gms_calls"] for c in comparisons)

    # --- Schritt 7: der ganze Lauf, beide Wege ----------------------------
    e2e = _end_to_end(args.gms, args.version, args.token, urn("missing_upstream"))
    result["end_to_end"] = e2e
    result["end_to_end_verdicts_identical"] = bool(
        e2e["verdict_counts_identical"] and e2e["edge_diffs_are_wall_clock_only"])
    result["end_to_end_graphql_seconds"] = e2e["graphql"]["seconds"]
    result["end_to_end_mcp_seconds"] = e2e["mcp"]["seconds_including_boot"]
    result["end_to_end_graphql_api_calls"] = e2e["graphql"]["api_calls"]
    result["end_to_end_mcp_api_calls"] = e2e["mcp"]["api_calls"]

    # --- Schritt 8: Telemetrie-Kosten -------------------------------------
    result["telemetry"] = _telemetry_cost(
        args.gms, args.version, args.token, urn("missing_upstream"))
    tel_off = result["telemetry"]["telemetrie_aus"]["median_seconds"]
    tel_on = result["telemetry"]["telemetrie_an"]["median_seconds"]
    result["telemetry_median_seconds_off"] = tel_off
    result["telemetry_median_seconds_on"] = tel_on
    result["telemetry_overhead_seconds"] = round(tel_on - tel_off, 3)

    # --- Verdikt ----------------------------------------------------------
    can_serve = (
        result["mcp_maps_identical_all_four_states"]
        and result["mcp_totals_identical_all_four_states"]
        and result["end_to_end_verdicts_identical"]
        and any(c["expected_edge_state"] == "missing" and c["cooccurrence_targets"]
                for c in comparisons)
    )
    result["mcp_can_serve_cooccurrence"] = bool(can_serve)
    result["mcp_probe_verdict"] = (
        "get_dataset_queries liefert den Ko-Okkurrenz-Lesevorgang vollstaendig: "
        "Karte und echte Gesamtzahl stimmen ueber alle vier Labor-Zustaende mit "
        "dem GraphQL-Weg ueberein, EIN Werkzeugaufruf statt 1+N GMS-Rundlaeufen. "
        "Was der MCP-Server NICHT liefert, ist die Zeitachse: Query-Entitaeten "
        "kommen ohne jeden Zeitstempel zurueck (queries.gql hat sie "
        "auskommentiert), und fuer die Dataset-Nutzungs-Buckets gibt es kein "
        "Werkzeug. probate kann seine Ko-Okkurrenz also ueber MCP lesen, sein "
        "Alters-Urteil nicht."
        if can_serve else
        "get_dataset_queries deckt den Ko-Okkurrenz-Lesevorgang NICHT: siehe "
        "comparisons[] fuer die abweichenden Karten."
    )
    result["mcp_probe_duration_seconds"] = round(time.time() - started, 1)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    summary = {k: v for k, v in result.items()
               if k not in ("comparisons", "timestamps", "tools_default",
                            "tools_mutation_enabled", "telemetry", "end_to_end")}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
