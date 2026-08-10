"""Misst das Modell-Urteil (Task 10) gegen ALLE VIER Seedlab-Fokusse,
nicht nur einen -- und beantwortet damit die Demo-Risikofrage des
Koordinators: gibt es ueberhaupt EINE Kante im Seedlab, bei der das
Modell erfolgreich mit echtem Zitat urteilt, oder faellt jede auffaellige
Kante zurueck?

WARUM diese Datei existiert: `harness/judge_probe.py` prueft den
Transport gegen SYNTHETISCHEN Kontext (fest hartkodiert, reich an
Metadaten) -- das beantwortet "funktioniert der Transport", nicht "sieht
das Urteil im ECHTEN Seedlab je etwas Zitierbares". Ein einzelner Live-
Lauf gegen `store_revenue_weekly_east` (Task-10-Fix-Runde-1-Bericht) fiel
zurueck, WEIL `store_revenue_weekly_east`/`customer_dedup_stage` im Seedlab
absichtlich SPARSAM angereichert sind (verwaiste Pipeline, Scratch-Tabelle)
-- waehrend `gl_journal_entries_daily`/`checkout_events_raw` REICH sind (Owner +
Domain + Glossar + Beschreibung). `judge_ledger` urteilt aber NUR ueber
abweichende Zustaende (`dead`/`missing`/`unknown`) -- `confirmed` ist per
Design ausgeschlossen. Der `missing`-Fokus ist deshalb der einzige der
vier, der sowohl REICHE Metadaten als auch einen ABWEICHENDEN Zustand
kombiniert -- ob das reicht, ist eine Messfrage, keine Vermutung.

Dieses Skript laeuft `ledger.run(..., judge_transport=..., judge_limit=5)`
GENAU EINMAL pro Fokus (kein zweiter, „nachbessernder" Versuch, egal wie
das erste Ergebnis ausfaellt -- Auftragsvorgabe: das Ergebnis wird
berichtet, nicht kuratiert) und schreibt die volle Matrix nach
`harness/runs/judge-seedlab-matrix.json`. Kein Fix der Demo-Daten hier --
das ist explizit NICHT die Aufgabe dieses Skripts, sondern eine
Entscheidung, die der Koordinator anhand der gemessenen Zahlen trifft.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from probate.gms import Gms
from probate.judge import claude_cli_transport
from probate.ledger import run as ledger_run

DEFAULT_OUT = Path("harness/runs/judge-seedlab-matrix.json")

# Die vier Seedlab-Upstream-URNs, je einer pro Zustand -- woertlich aus
# `examples/seedlab-manifest.json` uebernommen, nicht ein zweites Mal frei
# getippt (dieselbe Vorsicht wie in `harness/record_ledger.py`).
FOCUSES = [
    ("confirmed", "urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.gl_journal_entries_daily,PROD)"),
    ("dead", "urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.store_revenue_weekly_east,PROD)"),
    ("missing", "urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.checkout_events_raw,PROD)"),
    ("unknown", "urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.customer_dedup_stage,PROD)"),
]


def run_matrix(gms_url: str, judge_limit: int = 5) -> dict:
    """Ein `ledger.run()` MIT aktivem Urteil pro Fokus -- derselbe
    `claude_cli_transport()`, viermal wiederverwendet (jeder interne
    Aufruf ist ein eigener Prozessstart, das Wiederverwenden des
    Callables aendert daran nichts)."""
    transport = claude_cli_transport()
    now_ms = int(time.time() * 1000)
    results = []

    for expected_state, focus in FOCUSES:
        gms = Gms(gms_url)
        out = ledger_run(gms, focus, now_ms, judge_transport=transport, judge_limit=judge_limit)
        judgements = out.get("judgements", [])
        results.append({
            "expected_state_per_manifest": expected_state,
            "focus": focus,
            "edges_total": out["edges_total"],
            "edges": [{"edge": e["edge"], "state": e["state"]} for e in out["edges"]],
            "judged_edges": out.get("judged_edges", 0),
            "judged_with_model": out.get("judged_with_model", 0),
            "judged_fallback": out.get("judged_fallback", 0),
            "judge_seconds_total": out.get("judge_seconds_total", 0.0),
            "judgements": judgements,
        })

    any_real_citation = any(
        j["used_model"] for r in results for j in r["judgements"]
    )

    return {
        "seeded": True,
        "seeded_statement": ("All four focuses are the synthetic "
                             "Seedlab-Datensaetze (harness/seed_lineage_lab.py), "
                             "keine echte Warehouse-Nutzung."),
        "run_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gms": gms_url,
        "judge_limit": judge_limit,
        "focuses": results,
        "any_edge_judged_with_model": any_real_citation,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gms", default="http://localhost:28080")
    parser.add_argument("--judge-limit", dest="judge_limit", type=int, default=5)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    matrix = run_matrix(args.gms, judge_limit=args.judge_limit)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {
        "any_edge_judged_with_model": matrix["any_edge_judged_with_model"],
        "focuses": [
            {"expected_state_per_manifest": f["expected_state_per_manifest"],
             "edges_total": f["edges_total"],
             "judged_edges": f["judged_edges"],
             "judged_with_model": f["judged_with_model"],
             "judged_fallback": f["judged_fallback"]}
            for f in matrix["focuses"]
        ],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
