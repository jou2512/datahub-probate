"""Seedt ein Vier-Zustaende-Labor fuer den spaeteren Kanten-Abgleich.

WARUM: der Beispielkatalog (showcase-ecommerce auf 18080, das eigene Labor
auf 28080) hat keine Nutzungsdaten -- live geprueft, `statsSummary` liefert
`totalSqlQueries: null` fuer jedes Dataset (UEBERGABE.md SS3/SS9). Ohne
Nutzungsdaten kann `probate/ledger.py` (Schicht 1) nie alle vier Kanten-
Zustaende vorfuehren, die es unterscheiden soll:

  confirmed  deklarierte Kante + Ko-Okkurrenz-Query + frische Nutzung auf beiden Enden
  dead       deklarierte Kante, Nutzung existiert (wir haben hingesehen), aber der
             letzte Verkehr liegt ~117 Tage zurueck, danach nur noch Null-Buckets
  missing    Ko-Okkurrenz-Query + frische Nutzung, aber KEINE deklarierte Kante
  unknown    deklarierte Kante, aber ueberhaupt keine Nutzungs-Buckets -- keine
             Daten ist NICHT dasselbe wie tot, und genau diese Verwechslung ist
             der Fehler, den Schicht 1 laut UEBERGABE.md SS6 beheben soll

Alle Schreibvorgaenge sind live gegen 28080 vorab einzeln geprueft worden
(Dataset-Anlage, upstreamLineage-Aspekt-Form, Nutzungs-Bucket ueber 124 Tage
zurueck per usageStats(range: ALL, startTimeMillis:...), Idempotenz bei
gleichem Tages-Zeitstempel, vollstaendiges Entity-Delete inkl. Zeitreihen)
gegen Wegwerf-Entitaeten unter `probate_seedlab_probe.*` und wieder geloescht
-- siehe Abschlussbericht des Agenten-Laufs, nicht Teil dieses Skripts.

Namespace: PLATFORM = postgres, alle URNs unter `probate_seedlab.*` -- klar
als Labor erkennbar, kollidiert nicht mit echten Warehouse-Namen. Jede
Dataset-Beschreibung traegt das Praefix `[probate-seedlab]` und den Satz,
dass es sich um kuenstlich eingespielte Demonstrationsdaten handelt
(Regel UEBERGABE.md SS7.3: geseedete Daten werden als geseedet ausgewiesen).

Idempotent: alle Nicht-Zeitreihen-Aspekte (Dataset, upstreamLineage, Query)
haben feste URNs/IDs und werden bei jedem Lauf einfach ueberschrieben, nicht
dupliziert (v3-REST-Semantik: gleiche URN + gleicher Aspekt = Ersetzen).
Nutzungs-Buckets sind Zeitreihen, aber ihr Zeitstempel wird auf Mitternacht
UTC relativ zu "heute minus N Tage" gerundet -- ein zweiter Lauf am selben
Tag schreibt denselben Zeitstempel erneut und ueberschreibt (live geprueft:
zweimal derselbe Bucket ergab totalSqlQueries=10, nicht 20). Ein Lauf an
einem anderen Kalendertag erzeugt neue Tages-Buckets fuer die "aktuellen"
Zustaende (confirmed/missing) -- das ist fuer Zeitreihendaten das erwartete
Verhalten, kein Duplikat im Sinne der Aufgabe.

Jede Schreiboperation wird zurueckgelesen. Ein Rueckleseversagen ist ein
FEHLER (Exit 1), kein stilles Weiterlaufen -- Regel `verification.md`:
"Eine gescheiterte Abfrage ist keine Abwesenheit".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    DatasetUsageStatisticsClass,
    TimeWindowSizeClass,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # fuer `probate.*` bei Direktlauf

from probate.gms import Gms, GmsError  # noqa: E402

GMS_DEFAULT = "http://localhost:28080"
PLATFORM = "urn:li:dataPlatform:postgres"
NAMESPACE = "probate_seedlab"
ACTOR = "urn:li:corpuser:datahub"
STAMP = {"time": 1754300000000, "actor": ACTOR}  # fest, wie preflight.py/seed_queries.py
MANIFEST_PATH = Path("examples/seedlab-manifest.json")

NOW = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def days_ago_ms(n: int) -> int:
    return int((NOW - timedelta(days=n)).timestamp() * 1000)


def ds_urn(name: str) -> str:
    return f"urn:li:dataset:({PLATFORM},{NAMESPACE}.{name},PROD)"


# --- die acht Datasets, gruppiert nach Ziel-Zustand ihrer Kante ---------

NAMES: dict[str, str] = {
    "A": "confirmed_upstream",
    "B": "confirmed_downstream",
    "C": "dead_upstream",
    "D": "dead_downstream",
    "E": "missing_upstream",
    "F": "missing_downstream",
    "G": "unknown_upstream",
    "H": "unknown_downstream",
}
URNS: dict[str, str] = {k: ds_urn(v) for k, v in NAMES.items()}

EDGE_STATE_OF_PAIR = {
    ("A", "B"): "confirmed",
    ("C", "D"): "dead",
    ("E", "F"): "missing",
    ("G", "H"): "unknown",
}

# --- Nutzungs-Bucket-Plaene ------------------------------------------------

CONFIRMED_BUCKETS = [
    (days_ago_ms(2), 28, 3),
    (days_ago_ms(1), 35, 4),
    (days_ago_ms(0), 40, 5),
]
MISSING_BUCKETS = [
    (days_ago_ms(2), 19, 2),
    (days_ago_ms(1), 24, 3),
    (days_ago_ms(0), 31, 4),
]
DEAD_BUCKETS = [
    # letzter Verkehr -- ~117 Tage zurueck ist der juengere der beiden
    (days_ago_ms(124), 30, 4),
    (days_ago_ms(117), 22, 3),
    # danach: wir haben hingesehen, es war nichts mehr da
    (days_ago_ms(90), 0, 0),
    (days_ago_ms(60), 0, 0),
    (days_ago_ms(30), 0, 0),
    (days_ago_ms(14), 0, 0),
    (days_ago_ms(7), 0, 0),
    (days_ago_ms(0), 0, 0),
]
UNKNOWN_BUCKETS: list[tuple[int, int, int]] = []  # bewusst leer

USAGE_PLAN: dict[str, list[tuple[int, int, int]]] = {
    "A": CONFIRMED_BUCKETS,
    "B": CONFIRMED_BUCKETS,
    "C": DEAD_BUCKETS,
    "D": DEAD_BUCKETS,
    "E": MISSING_BUCKETS,
    "F": MISSING_BUCKETS,
    "G": UNKNOWN_BUCKETS,
    "H": UNKNOWN_BUCKETS,
}

LINEAGE_PAIRS: list[tuple[str, str]] = [("A", "B"), ("C", "D"), ("G", "H")]  # missing hat KEINE
COOCCURRENCE_PAIRS: list[tuple[str, str]] = [("A", "B"), ("E", "F")]  # dead/unknown haben KEINE


@dataclass
class WriteResult:
    what: str
    written: Any
    readback: Any
    ok: bool
    detail: str = ""


RESULTS: list[WriteResult] = []


def record(what: str, written: Any, readback_fn, expect_fn, retries: int = 6, delay_s: float = 2.0) -> None:
    """Liest zurueck und vergleicht. GraphQL-Lineage und usageStats haengen
    an Elasticsearch/Graph-Indizes, die per Kafka-MCL asynchron NACH dem
    synchronen REST-Schreibvorgang nachziehen -- live beobachtet (2026-08-07):
    ein Rücklese-Versuch direkt nach dem Schreiben lieferte fuer upstreamLineage
    und usageStats den alten (leeren) Stand, derselbe Aufruf Sekunden spaeter
    den korrekten. Das ist Index-Verzug, kein Schreibfehler -- darum retry mit
    Backoff, bevor ein FEHLER gemeldet wird (verification.md: eine gescheiterte
    Abfrage ist keine Abwesenheit, aber ein zu frueher Blick ist auch keine)."""
    last_readback = None
    last_err: str | None = None
    for attempt in range(retries):
        try:
            last_readback = readback_fn()
        except GmsError as exc:
            last_err = f"Rueckleseversagen: {exc}"
            time.sleep(delay_s)
            continue
        if expect_fn(last_readback):
            RESULTS.append(WriteResult(what, written, last_readback, True, f"(nach {attempt + 1}. Versuch)" if attempt else ""))
            return
        time.sleep(delay_s)
    detail = last_err or "Rueckgelesener Wert weicht auch nach Wiederholungen ab"
    RESULTS.append(WriteResult(what, written, last_readback, False, f"{detail} ({retries}x versucht)"))


# --- Schreibvorgaenge --------------------------------------------------


def seed_datasets(gms: Gms) -> None:
    records = []
    for letter, name in NAMES.items():
        state = next((s for (a, b), s in EDGE_STATE_OF_PAIR.items() if letter in (a, b)), "?")
        role = "upstream" if letter in "ACEG" else "downstream"
        desc = (
            f"[probate-seedlab] Kuenstlich eingespielte Demonstrationsdaten. "
            f"Rolle={role}, Ziel-Kanten-Zustand={state}. Kein echtes Warehouse-Dataset."
        )
        records.append(
            {"urn": URNS[letter], "datasetProperties": {"value": {"name": name, "description": desc}}}
        )
    gms.upsert("dataset", records)

    def readback():
        out = {}
        for letter in NAMES:
            data = gms.graphql(
                "query($urn: String!) { dataset(urn: $urn) { urn properties { name } } }",
                {"urn": URNS[letter]},
            )
            out[letter] = (data.get("dataset") or {}).get("properties")
        return out

    record(
        "datasets (8x datasetProperties)",
        [r["urn"] for r in records],
        readback,
        lambda rb: all(v and v.get("name") == NAMES[k] for k, v in rb.items()),
    )


def seed_lineage(gms: Gms) -> None:
    records = []
    for up, down in LINEAGE_PAIRS:
        records.append(
            {
                "urn": URNS[down],
                "upstreamLineage": {
                    "value": {
                        "upstreams": [
                            {"dataset": URNS[up], "type": "TRANSFORMED", "auditStamp": STAMP}
                        ]
                    }
                },
            }
        )
    gms.upsert("dataset", records)

    _LINEAGE_Q = """
    query($urn: String!) {
      dataset(urn: $urn) {
        lineage(input: {direction: DOWNSTREAM, start: 0, count: 200}) {
          relationships { entity { urn } }
        }
      }
    }
    """

    def readback():
        out = {}
        for up, down in LINEAGE_PAIRS:
            data = gms.graphql(_LINEAGE_Q, {"urn": URNS[up]})
            rels = (data.get("dataset") or {}).get("lineage", {}).get("relationships", [])
            out[f"{up}->{down}"] = {r["entity"]["urn"] for r in rels if r.get("entity")}
        return out

    def expect(rb):
        return all(URNS[down] in rb[f"{up}->{down}"] for up, down in LINEAGE_PAIRS)

    record("upstreamLineage (3x deklarierte Kanten: A->B, C->D, G->H)", [r["urn"] for r in records], readback, expect)


def seed_queries(gms: Gms) -> None:
    plans = [
        (
            "probate-seedlab-confirmed",
            "INSERT INTO probate_seedlab.confirmed_downstream SELECT * FROM probate_seedlab.confirmed_upstream",
            ("A", "B"),
        ),
        (
            "probate-seedlab-missing",
            "INSERT INTO probate_seedlab.missing_downstream SELECT * FROM probate_seedlab.missing_upstream",
            ("E", "F"),
        ),
    ]
    records = []
    for qid, sql, (up, down) in plans:
        records.append(
            {
                "urn": f"urn:li:query:{qid}",
                "queryProperties": {
                    "value": {
                        "statement": {"value": sql, "language": "SQL"},
                        "source": "MANUAL",
                        "created": STAMP,
                        "lastModified": STAMP,
                    }
                },
                "querySubjects": {"value": {"subjects": [{"entity": URNS[up]}, {"entity": URNS[down]}]}},
            }
        )
    gms.upsert("query", records)

    def readback():
        out = {}
        for qid, _sql, _pair in plans:
            aspect = gms.get_aspect("query", f"urn:li:query:{qid}", "querysubjects")
            subjects = (aspect or {}).get("value", {}).get("subjects", [])
            out[qid] = {s.get("entity") for s in subjects}
        return out

    def expect(rb):
        for qid, _sql, (up, down) in plans:
            if rb[qid] != {URNS[up], URNS[down]}:
                return False
        return True

    record("query-Entitaeten (2x: confirmed A+B, missing E+F)", [r["urn"] for r in records], readback, expect)


def seed_usage(gms: Gms, emitter: DatahubRestEmitter) -> None:
    written_counts: dict[str, int] = {}
    for letter, buckets in USAGE_PLAN.items():
        n = 0
        for ts_ms, total, unique in buckets:
            aspect = DatasetUsageStatisticsClass(
                timestampMillis=ts_ms,
                eventGranularity=TimeWindowSizeClass(unit="DAY", multiple=1),
                uniqueUserCount=unique,
                totalSqlQueries=total,
            )
            try:
                emitter.emit_mcp(MetadataChangeProposalWrapper(entityUrn=URNS[letter], aspect=aspect))
                n += 1
            except Exception as exc:  # noqa: BLE001 - Schreibfehler MUSS laut werden
                RESULTS.append(
                    WriteResult(f"usage bucket {letter}@{ts_ms}", ts_ms, None, False, f"{type(exc).__name__}: {exc}")
                )
        written_counts[letter] = n

    # Live-Falle (2026-08-07, dieser Lauf): usageStats(range: ALL, startTimeMillis: N)
    # mit einem NICHT-Null startTimeMillis liefert null/falsche Aggregationen, obwohl
    # die Rohdaten nachweislich da sind (per /aspects?action=getTimeseriesAspectValues
    # gegengeprueft: die Buckets liegen vollstaendig in der Primaerablage). Erst mit
    # range: ALL OHNE startTimeMillis (oder startTimeMillis weggelassen) kommt die
    # korrekte Summe zurueck -- live an D (52) und F (74) verglichen. Also: NIE
    # startTimeMillis mitschicken, wenn range: ALL genuegt.
    _USAGE_Q = """
    query($urn: String!) {
      dataset(urn: $urn) {
        usageStats(range: ALL) {
          aggregations { totalSqlQueries uniqueUserCount }
        }
      }
    }
    """

    def readback():
        out = {}
        for letter in USAGE_PLAN:
            data = gms.graphql(_USAGE_Q, {"urn": URNS[letter]})
            agg = ((data.get("dataset") or {}).get("usageStats") or {}).get("aggregations") or {}
            out[letter] = agg.get("totalSqlQueries")
        return out

    def expect(rb):
        for letter, buckets in USAGE_PLAN.items():
            expected_total = sum(b[1] for b in buckets)
            got = rb.get(letter)
            if buckets and got != expected_total:
                return False
            if not buckets and got not in (None, 0):
                # unknown-Zustand: keine Buckets geschrieben. DataHub liefert je
                # nach Instanzstand entweder null oder 0 fuer "keine Daten" --
                # beides ist der erwartete Nicht-Fund, ein anderer Wert waere ein Fehler.
                return False
        return True

    record(
        f"Nutzungs-Buckets ({sum(written_counts.values())} Aufrufe ueber 8 Datasets)",
        written_counts,
        readback,
        expect,
    )


def check_cooccurrence(gms: Gms) -> dict[str, int]:
    """Teil 3: der Weg, den der spaetere Abgleich benutzt -- searchAcrossEntities
    auf QUERY-Entitaeten, gefiltert auf das Feld 'entities'. Wird für die
    beiden Datasets berichtet, die tatsaechlich in einer Seed-Query stehen."""
    _Q = """
    query($urn: String!) {
      searchAcrossEntities(input: {
        types: [QUERY], query: "*", count: 200,
        orFilters: [{ and: [{ field: "entities", values: [$urn] }] }]
      }) { total searchResults { entity { urn } } }
    }
    """
    out = {}
    for up, down in COOCCURRENCE_PAIRS:
        data = gms.graphql(_Q, {"urn": URNS[up]})
        out[f"{up}(+{down})"] = (data.get("searchAcrossEntities") or {}).get("total", 0)
    return out


# --- Manifest -----------------------------------------------------------


def write_manifest(cooccurrence: dict[str, int]) -> None:
    entries = []
    for (up, down), state in EDGE_STATE_OF_PAIR.items():
        entries.append(
            {
                "upstream_urn": URNS[up],
                "downstream_urn": URNS[down],
                "declared_lineage": (up, down) in LINEAGE_PAIRS,
                "cooccurrence_query": (up, down) in COOCCURRENCE_PAIRS,
                "usage_buckets_upstream": len(USAGE_PLAN[up]),
                "usage_buckets_downstream": len(USAGE_PLAN[down]),
                "expected_edge_state": state,
                "represents": {
                    "confirmed": "Kante deklariert + Ko-Okkurrenz-Query + frische Nutzung beidseitig",
                    "dead": "Kante deklariert, Nutzung gemessen, letzter Verkehr ~117 Tage zurueck, danach Null",
                    "missing": "Ko-Okkurrenz-Query + frische Nutzung, aber KEINE deklarierte Kante",
                    "unknown": "Kante deklariert, aber KEINE Nutzungs-Buckets ueberhaupt",
                }[state],
            }
        )
    manifest = {
        "seeded": True,
        "seeded_statement": (
            "Dies sind kuenstlich eingespielte Demonstrationsdaten (harness/seed_lineage_lab.py), "
            "keine echte Warehouse-Nutzung. Namespace probate_seedlab, Plattform postgres."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gms_url": GMS_DEFAULT,
        "namespace": NAMESPACE,
        "edges": entries,
        "cooccurrence_search_results": cooccurrence,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --- CLI ------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gms-url", default=GMS_DEFAULT)
    p.add_argument("--token", default=None)
    args = p.parse_args()

    token = args.token if args.token is not None else os.environ.get("DATAHUB_TOKEN")
    gms = Gms(base_url=args.gms_url, token=token)
    emitter = DatahubRestEmitter(gms_server=args.gms_url, token=token)

    seed_datasets(gms)
    seed_lineage(gms)
    seed_queries(gms)
    seed_usage(gms, emitter)
    cooccurrence = check_cooccurrence(gms)
    write_manifest(cooccurrence)

    print(f"\n  Seedlab gegen {args.gms_url}, Namespace {NAMESPACE}\n")
    print(f"  {'Schreibvorgang':<55} {'Status':<6} Detail")
    print(f"  {'-' * 55} {'-' * 6} {'-' * 30}")
    failed = []
    for r in RESULTS:
        status = "OK" if r.ok else "FEHL"
        if not r.ok:
            failed.append(r.what)
        print(f"  {r.what:<55} {status:<6} {r.detail}")

    print("\n  Ko-Okkurrenz-Suche (searchAcrossEntities, types:[QUERY]):")
    for k, v in cooccurrence.items():
        print(f"    {k}: {v} Treffer")

    print(f"\n  Manifest: {MANIFEST_PATH}")

    if failed:
        print(f"\n  {len(failed)} Schreibvorgang/-vorgaenge ohne erfolgreiches Ruecklesen: {failed}")
        return 1
    print(f"\n  Alle {len(RESULTS)} Schreibvorgaenge zurueckgelesen und bestaetigt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
