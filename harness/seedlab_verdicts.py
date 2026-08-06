"""Der P1-Akzeptanznachweis: "alle vier Zustaende treten in einem echten
Lauf auf" -- als Artefakt, nicht als Prosa.

WARUM diese Datei existiert (Review Fix-Runde 1, CRITICAL 1): der erste
Task-5-Bericht behauptete die vier Zustaende (`confirmed`/`dead`/`missing`/
`unknown`) aus einem Skript, das nur im Scratchpad lag -- ausserhalb des
Repos, nicht nachvollziehbar, nicht reproduzierbar. `global-constraints.md`
verlangt: jede Zahl in Prosa kommt aus einem committeten Artefakt unter
`harness/runs/`. Dieses Skript ist der committete Weg dorthin.

Es ruft ausschliesslich die drei Beschaffungs-Funktionen aus
`probate/ledger.py` (`fetch_declared_edges`, `fetch_cooccurrence`,
`usage_evidence`) und `classify_edges` auf -- keine eigene GraphQL-Logik,
keine Abkuerzung an den beiden Obligationen aus dem Task-4-Review:

1. `queries_seen` ist die ECHTE Gesamtzahl (`fetch_cooccurrence`s zweiter
   Rueckgabewert `total`, aus dem `total`-Feld der Suchantwort -- nicht
   `len(searchResults)`, das bei mehr als `count: 200` Treffern zu klein
   waere).
2. Coverage und Timeline pro Ziel-URN stammen aus GENAU EINEM
   `fetch_usage`-Aufruf (`usage_evidence`), nie aus zwei getrennten.

Die vier Manifest-Paare (`examples/seedlab-manifest.json`,
`"seeded": true`, Namespace `probate_seedlab`) sind je auf einen anderen
Zustand angelegt (siehe `harness/seed_lineage_lab.py`). Dieses Skript liest
die URNs aus dem Manifest -- nicht hartkodiert ein zweites Mal -- und
klassifiziert pro Paar den Fokus (Upstream) gegen alle deklarierten und
ko-okkurrenten Ziele, dann filtert es auf das im Manifest genannte
Downstream-Ziel.

Bei jedem Lauf koennen sich Zahlen wie `buckets_checked` leicht verschieben
(taegliche Buckets, Ingestion-Zeitpunkt) -- der `state` selbst soll bei
unveraendertem Katalog stabil bleiben. Weicht ein Re-Lauf beim `state` vom
hier zuletzt committeten Artefakt ab, gehoert das ehrlich ins naechste
Review, nicht stillschweigend ueberschrieben.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # fuer `probate.*` bei Direktlauf

from probate.gms import Gms
from probate.ledger import (
    classify_edges,
    fetch_cooccurrence,
    fetch_declared_edges,
    usage_evidence,
)

MANIFEST_PATH = Path("examples/seedlab-manifest.json")


def _label_for(edge: dict) -> str:
    return edge["expected_edge_state"]


def run(gms, manifest_path: Path = MANIFEST_PATH, out_path: Path | None = None) -> dict:
    """Klassifiziert alle Paare aus dem Seedlab-Manifest gegen ein
    ECHTES GMS und schreibt das Ergebnis als Artefakt nach harness/runs/.

    Ein Paar ist der Fokus (Upstream), gegen den EINMAL
    `fetch_declared_edges` und `fetch_cooccurrence` laufen; die Ziel-Menge
    daraus wird je einmal mit `usage_evidence` beliefert (Obligation 2),
    `queries_seen` kommt aus `fetch_cooccurrence`s `total` (Obligation 1).
    """
    if out_path is None:
        out_path = Path("harness/runs/seedlab-verdicts.json")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    now_ms = int(time.time() * 1000)
    generated_at = datetime.now(timezone.utc).isoformat()

    pairs: dict[str, dict] = {}
    all_match = True

    for edge in manifest["edges"]:
        label = _label_for(edge)
        upstream = edge["upstream_urn"]
        downstream = edge["downstream_urn"]

        declared = fetch_declared_edges(gms, upstream, count=200)
        cooccurred, queries_seen = fetch_cooccurrence(gms, upstream)

        targets = declared | set(cooccurred)
        coverage_by_urn: dict[str, object] = {}
        timeline_by_urn: dict[str, object] = {}
        for t in targets:
            cov, tl = usage_evidence(gms, t)
            coverage_by_urn[t] = cov
            timeline_by_urn[t] = tl

        verdicts = classify_edges(
            focus=upstream, declared=declared, cooccurred=cooccurred,
            coverage_by_urn=coverage_by_urn, timeline_by_urn=timeline_by_urn,
            now_ms=now_ms, queries_seen=queries_seen)

        match = next((v for v in verdicts if v.edge.downstream == downstream), None)
        state = match.state if match else "absent"
        matches_expected = state == edge["expected_edge_state"]
        all_match = all_match and matches_expected

        pairs[label] = {
            "upstream_urn": upstream,
            "downstream_urn": downstream,
            "expected_state": edge["expected_edge_state"],
            "state": state,
            "matches_expected": matches_expected,
            "evidence": match.evidence if match else None,
            "queries_seen": queries_seen,
            "buckets_checked": (
                match.coverage.buckets_seen if match else None
            ),
            "coverage": match.coverage.to_json() if match else None,
            "timeline": match.timeline.to_json(now_ms) if match else None,
        }

    artifact = {
        "seeded": True,
        "seeded_statement": (
            "Laeuft gegen den geseedeten Beispielkatalog (namespace "
            "probate_seedlab, harness/seed_lineage_lab.py) -- keine echte "
            "Warehouse-Nutzung."
        ),
        "gms_url": gms.base,
        "manifest": str(manifest_path),
        "generated_at": generated_at,
        "now_ms": now_ms,
        "all_four_states_matched_expected": all_match,
        "pairs": pairs,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return artifact


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gms-url", default="http://localhost:28080")
    p.add_argument("--manifest", default=str(MANIFEST_PATH))
    p.add_argument("--token", default=None)
    p.add_argument("--out", default="harness/runs/seedlab-verdicts.json")
    args = p.parse_args()

    token = args.token if args.token is not None else os.environ.get("DATAHUB_TOKEN")
    gms = Gms(base_url=args.gms_url, token=token)

    artifact = run(gms, Path(args.manifest), Path(args.out))
    print(json.dumps(artifact, indent=2, ensure_ascii=False))
    return 0 if artifact["all_four_states_matched_expected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
