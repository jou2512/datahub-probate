"""Zeichnet einen Lauf gegen die vier geseedeten Fokus-Datensaetze auf und
kombiniert sie zu EINEM Register-Artefakt fuer die Aufzeichnungsmodus-UI.

WARUM diese Datei existiert: `probate/ledger.py:run()` urteilt pro FOKUS,
und der bislang committete Lauf (`harness/runs/ledger.json`) deckt genau
einen Fokus ab -- `edges_total: 1`, ein einziger Zustand. Ohne diese Datei
zeigen die Werkbank-Aufzeichnung und damit Demo und README ein Register mit
EINER Kante statt der vier, die das Projekt unterscheiden soll (Controller-
Auftrag zu Task 17). `examples/seedlab-manifest.json` legt genau vier
Fokus->Ziel-Paare an, je eines pro Zustand (`harness/seed_lineage_lab.py`);
dieses Skript ruft `ledger.run()` deshalb VIERMAL live gegen ein echtes GMS
auf (kein Mock, keine erfundene Zahl) und haengt die Ergebnisse aneinander.

Kombinationsregel -- warum ein Concat und keine zweite Klassifikation:
jede Kante traegt in `edge["upstream"]` bereits ihren eigenen Fokus
(`Edge(focus, target)` in `classify_edges`). Die vier Laeufe koennen sich
deshalb gefahrlos nebeneinanderlegen; `combine_runs()` fasst nur die
edges-Listen zusammen und zaehlt die Zustands-Summen NEU aus genau diesen
kombinierten Kanten (nicht aus den vier Einzel-Zaehlern -- eine blinde
Summe koennte drift-tolerant eine doppelte Kante verschlucken, die
Neuzaehlung nicht). `tests/test_record_ledger.py` prueft mit Fake-run()-
Ausgaben, dass kein einzelnes Kanten-Urteil dabei veraendert wird
(byte-identischer Vergleich) -- der Live-Nachweis dazu steht im
Task-17-Bericht: die vier Solo-Laeufe wurden vor dem kombinierten Lauf
separat mitgeschrieben und Zustand-fuer-Zustand gegen das kombinierte
Artefakt verglichen.

Ehrlichkeits-Markierung (`global-constraints.md`, "Geseedete/synthetische
Daten werden in JEDEM Artefakt als solche ausgewiesen"): `seeded: true`
plus `recorded_runs_at_ms`, die Zeitstempel aller vier Einzel-Laeufe --
damit ist das Artefakt als Aufzeichnung erkennbar, nicht als Live-Sicht,
auch ohne den `#mode-badge` der UI zu lesen.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from probate.gms import Gms
from probate.ledger import STATES, run as ledger_run

# Die vier Upstream-URNs aus examples/seedlab-manifest.json -- je eine pro
# Zustand (harness/seed_lineage_lab.py legt sie so an; live bestaetigt in
# harness/runs/seedlab-verdicts.json, all_four_states_matched_expected:
# true). Nicht hartkodiert ein zweites Mal ohne Beleg: die Uebereinstimmung
# mit dem Manifest ist ein Test (test_focuses_list_matches_the_four_
# seedlab_pairs), kein blosses Vertrauen in diese Liste.
FOCUSES = [
    "urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.gl_journal_entries_daily,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.store_revenue_weekly_east,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.checkout_events_raw,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.customer_dedup_stage,PROD)",
]

DEFAULT_OUT = Path("ui/recorded/ledger.json")


def combine_runs(runs: list[dict]) -> dict:
    """Reines Concat + Neuzaehlung, siehe Modul-Docstring. Keine
    Netzwerk-Seiteneffekte -- deshalb mit Fake-run()-Ausgaben testbar,
    ohne GMS zu brauchen."""
    edges = [e for r in runs for e in r["edges"]]
    counts = {s: sum(1 for e in edges if e["state"] == s) for s in STATES}
    return {
        "focus": f"{len(runs)} seeded focuses (see edges[].upstream)",
        "focuses": [r["focus"] for r in runs],
        "gms": runs[0]["gms"] if runs else "",
        "seeded": True,
        "recording": True,
        "recorded_runs_at_ms": [r["generated_at_ms"] for r in runs],
        "generated_at_ms": max((r["generated_at_ms"] for r in runs), default=0),
        "edges_total": len(edges),
        "edges_confirmed": counts["confirmed"],
        "edges_dead": counts["dead"],
        "edges_missing": counts["missing"],
        "edges_unknown": counts["unknown"],
        "coverage_buckets_seen": sum(r["coverage_buckets_seen"] for r in runs),
        # Breiteste Spanne, keine Summe -- vier ueberlappende Fenster
        # addiert waeren eine erfundene Zahl, kein gemessenes "wie weit
        # reicht unser Blick".
        "coverage_days_span": max((r["coverage_days_span"] for r in runs), default=0),
        # "any": ehrlich, wenn auch nur EINER der vier Laeufe duenn gedeckt
        # war -- ein "all" wuerde eine duenne Kante hinter drei dicken
        # verstecken, ein "none" (bool(sum)) waere keine echte Aggregation.
        "coverage_thin": any(r["coverage_thin"] for r in runs),
        "api_calls": sum(r["api_calls"] for r in runs),
        "queries_seen": sum(r["queries_seen"] for r in runs),
        "edges": edges,
    }


def record(gms: Gms, focuses: list[str], now_ms: int) -> dict:
    """Vier echte `ledger.run()`-Aufrufe, ein kombiniertes Artefakt.
    Wie `ledger.run()` selbst: ein fehlgeschlagener Fetch wirft `GmsError`
    und laesst diese Funktion ohne Rueckgabewert enden -- kein Teil-
    Artefakt, das Vollstaendigkeit behaupten wuerde."""
    runs = [ledger_run(gms, focus, now_ms) for focus in focuses]
    return combine_runs(runs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="harness.record_ledger",
        description="Zeichnet die vier geseedeten Fokus-Laeufe zu einem "
                     "Vier-Zustaende-Register fuer den Aufzeichnungsmodus "
                     "der Werkbank auf.",
    )
    parser.add_argument("--gms", default="http://localhost:28080",
                         help="GMS-Basis-URL (Standard: http://localhost:28080)")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    gms = Gms(args.gms)
    now_ms = int(time.time() * 1000)
    out = record(gms, FOCUSES, now_ms)
    out["recorded_at_iso"] = datetime.now(timezone.utc).isoformat()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    summary = {k: v for k, v in out.items() if k != "edges"}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
