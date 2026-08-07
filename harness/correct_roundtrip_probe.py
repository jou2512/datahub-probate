"""Der committete Beweis: eine Korrektur ist vollstaendig revertierbar --
inklusive spaltengenauer Lineage.

WARUM diese Datei existiert (Task-12-Review, Fix-Runde 2, Fund 2): der
Byte-fuer-Byte-Revert-Rundlauf war eine der staerksten Behauptungen der
Einreichung, ruhte aber nur auf einem geloeschten Wegwerf-Skript im
Live-Report -- unbelegt im selben Sinn, den `global-constraints.md`
verbietet ("jede Zahl in Prosa kommt aus einem committeten Artefakt unter
`harness/runs/`"). Jedes andere Beweis-Skript in diesem Repo ist committet
(`harness/seedlab_verdicts.py`, `harness/loadgen.py`,
`harness/judge_probe.py`) -- dieses schliesst dieselbe Luecke fuer
`probate/correct.py`.

Zielt bewusst NICHT auf ein Dataset ohne bestehenden Aspekt: dort ist
Mergen ein No-op, und genau das hatte Fund CRITICAL 1 (fineGrainedLineages
wird bei jedem Schreibvorgang geloescht) beim ersten Live-Lauf unsichtbar
gemacht. Dieses Skript nimmt stattdessen `probate_seedlab.
finance_income_statement_consolidated` (B, aus `examples/seedlab-manifest.json`, Paar
"confirmed") -- B traegt bereits eine deklarierte Kante von
`gl_journal_entries_daily` (A) -- und schreibt zusaetzlich eine
fineGrainedLineages-Spalten-Lineage dazu, BEVOR es ueber den echten
Produktweg (`correct.apply_proposal`) eine neue Kante eintraegt. Beide
Schreibvorgaenge laufen durch dasselbe `Writeback`-Journal und werden
danach ueber `revert_all()` zurueckgerollt.

Kein neues Entity wird angelegt -- nur ein bestehender Aspekt geschrieben
und wieder zurueckgerollt. "Aufraeumen" heisst hier: den echten
Endzustand per `get_aspect()` (NIE per Suche -- der Index hinkt nach
`UEBERGABE.md` Falle 15 ~30s hinterher) gegen den echten Originalzustand
pruefen, nicht nur `revert_count` glauben.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # fuer `probate.*` bei Direktlauf

from probate.correct import Proposal, apply_proposal  # noqa: E402
from probate.gms import Gms  # noqa: E402
from probate.writeback import Writeback  # noqa: E402

MANIFEST_PATH = Path("examples/seedlab-manifest.json")
JOURNAL_PATH = Path("harness/runs/_correct_roundtrip_journal.jsonl")


def _pair_from_manifest(manifest_path: Path, expected_state: str) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for edge in manifest["edges"]:
        if edge["expected_edge_state"] == expected_state:
            return edge
    raise ValueError(f"kein paar mit expected_edge_state={expected_state!r} im manifest")


def run(gms, manifest_path: Path = MANIFEST_PATH, out_path: Path | None = None) -> dict:
    """Zwei journalisierte Schreibvorgaenge gegen ein ECHTES GMS, dann
    ein vollstaendiger Revert -- als Artefakt, nicht als Prosa.

    Schreibvorgang 1 (Vorbedingung, nicht der eigentliche Produktweg):
    eine fineGrainedLineages-Spalten-Lineage auf B dazuschreiben, ueber
    `wb.aspect()` (journalisiert), die bestehende Kante von A bleibt
    unangetastet.

    Schreibvorgang 2 (der eigentliche Beweis): `correct.apply_proposal()`
    traegt eine NEUE Kante (von einem dritten Seedlab-Dataset) auf B ein.
    Falls `merge_upstreams` (Fund CRITICAL 1) je wieder nur `upstreams`
    zurueckgeben wuerde, waere die CLL aus Schreibvorgang 1 hier weg --
    das Artefakt zeigt den vollen Wert nach diesem Schritt.

    `wb.revert_all()` rollt beide Schreibvorgaenge in umgekehrter
    Reihenfolge zurueck; das Artefakt vergleicht den Endzustand
    byte-genau mit dem WAHREN Originalzustand (vor Schreibvorgang 1).
    """
    if out_path is None:
        out_path = Path("harness/runs/correct-roundtrip.json")

    confirmed_pair = _pair_from_manifest(manifest_path, "confirmed")
    dead_pair = _pair_from_manifest(manifest_path, "dead")
    target = confirmed_pair["downstream_urn"]              # B: finance_income_statement_consolidated
    existing_upstream = confirmed_pair["upstream_urn"]      # A: gl_journal_entries_daily
    new_upstream = dead_pair["upstream_urn"]                # ein DRITTES Dataset, unbeteiligt an B

    if JOURNAL_PATH.exists():
        JOURNAL_PATH.unlink()

    true_original = gms.get_aspect("dataset", target, "upstreamLineage")

    wb = Writeback(gms, dry_run=False, journal_path=str(JOURNAL_PATH))

    cll_entry = [{
        "upstreamType": "FIELD_SET", "downstreamType": "FIELD",
        "downstreams": [f"urn:li:schemaField:({target},revenue)"],
        "upstreams": [f"urn:li:schemaField:({existing_upstream},amount)"],
        "confidenceScore": 1.0,
    }]
    seed_value = dict((true_original or {}).get("value") or {})
    seed_value["fineGrainedLineages"] = cll_entry
    wb.aspect("dataset", target, "upstreamLineage", seed_value)
    after_cll_seed = gms.get_aspect("dataset", target, "upstreamLineage")

    now_ms = int(time.time() * 1000)
    p = Proposal(
        kind="add_edge", edge_key=f"{new_upstream}->{target}", target_urn=target,
        aspect="upstreamLineage", state="missing",
        evidence={"query_urns": ["urn:li:query:probate-correct-roundtrip-probe"],
                  "cooccurrence_count": 1,
                  "direction_evidence": "co-occurrence (undirected)"},
        human_summary="harness/correct_roundtrip_probe.py -- committeter revert-beweis",
    )
    apply_proposal(wb, p, actor="urn:li:corpuser:__datahub_system", now_ms=now_ms)
    after_write = gms.get_aspect("dataset", target, "upstreamLineage")

    reverted = wb.revert_all()
    after_revert = gms.get_aspect("dataset", target, "upstreamLineage")

    if JOURNAL_PATH.exists():
        JOURNAL_PATH.unlink()

    after_write_upstreams = (after_write or {}).get("value", {}).get("upstreams", [])
    after_write_cll = (after_write or {}).get("value", {}).get("fineGrainedLineages")

    artifact = {
        "seeded": True,
        "seeded_statement": (
            "Laeuft gegen den geseedeten Beispielkatalog (namespace probate_seedlab, "
            "harness/seed_lineage_lab.py) -- kein neues Entity angelegt, nur ein "
            "bestehender Aspekt geschrieben und vollstaendig zurueckgerollt."
        ),
        "gms_url": gms.base,
        "manifest": str(manifest_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "existing_upstream": existing_upstream,
        "new_upstream": new_upstream,
        "true_original": true_original,
        "after_cll_seed": after_cll_seed,
        "after_write": after_write,
        "revert_count": reverted,
        "after_revert": after_revert,
        "revert_restored_exactly": after_revert == true_original,
        "existing_edge_survived_the_merge": existing_upstream in {
            u.get("dataset") for u in after_write_upstreams
        },
        "new_edge_present_after_write": new_upstream in {
            u.get("dataset") for u in after_write_upstreams
        },
        "cll_survived_the_merge": after_write_cll == cll_entry,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    return artifact


if __name__ == "__main__":
    result = run(Gms())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["revert_restored_exactly"]:
        sys.exit(1)  # Regel verification.md: eine gescheiterte Pruefung ist kein stilles Weiterlaufen
