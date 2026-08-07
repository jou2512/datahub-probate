"""Der committete Beweis fuer Task 13: `enrich_doc` schreibt (und
revertiert) eine Doku-Notiz, `remove_edge` nimmt eine deklarierte Kante
weg -- beides ueber den echten Produktweg, gegen ein echtes GMS.

WARUM diese Datei existiert -- zweifach:

1. `global-constraints.md`: jede Zahl in Prosa kommt aus einem
   committeten Artefakt unter `harness/runs/`, kein Wegwerf-Skript.
   Ohne dieses Skript waere `harness/runs/enrich-doc-remove-edge-
   roundtrip.json` ein Artefakt, das niemand nachvollziehen oder erneut
   erzeugen kann -- derselbe Fehler, den `harness/correct_roundtrip_
   probe.py` (Task 12) fuer `add_edge` bereits vermeidet, und den jeder
   andere Beweis in diesem Repo vermeidet (`harness/seedlab_verdicts.py`,
   `harness/loadgen.py`, `harness/judge_probe.py`,
   `harness/judge_matrix.py`). Folgt demselben Muster: schreiben, lesen,
   revert, zurueck lesen -- NIE per Suche (Index hinkt ~30s nach), immer
   per `get_aspect()`.
2. Die auditierbare Begruendung fuer eine Design-Entscheidung in
   `probate/correct.py`, die sonst nur im Code-Kommentar stuende:
   `enrich_doc` schreibt in `editableDatasetProperties.description`
   (nicht in ein separates, probate-exklusives Feld) UND ausschliesslich
   anhaengend, nie ersetzend. Beide Haelften der Begruendung:
   - **Warum dieses Feld:** `description` ist im DataHub-UI die
     kuratierte Beschreibung, die Nutzer tatsaechlich lesen. Ein
     verstecktes Feld (z.B. `customProperties["probate.note"]`) waere
     "sicherer" im Sinn von nie-vermischt, aber fuer den eigentlichen
     Zweck -- beobachtete Nutzung SICHTBAR dokumentieren -- nutzlos.
   - **Warum ausschliesslich anhaengend:** es gibt auf diesem Aspekt
     kein zweites, probate-exklusives Feld (anders als
     `upstreamLineage.upstreams[].properties["probate.dead_since"]`
     bei `mark_dead`, Task 12). Eine bestehende, von einem Menschen
     geschriebene Beschreibung zu ersetzen waere dieselbe Fehlerklasse
     wie das stille Loeschen von `fineGrainedLineages` beim Mergen
     (Task-12-Review, CRITICAL 1) -- nur auf einem Aspekt, den Menschen
     lesen statt nur BI-Tools. Anhaengen ist die einzige Operation, die
     das strukturell ausschliesst.
   Dieses Skript belegt beide Haelften live: Beweis 1 unten laeuft
   gegen ein Dataset OHNE bestehende Beschreibung (`true_original` ist
   `None`) -- der Append-vs-Ersetzen-Fall selbst ist bereits in
   `tests/test_correct.py` gruendlich getestet
   (`test_enrich_doc_appends_and_never_overwrites_an_existing_
   description`).

Nachtrag (Review, Fix-Runde 1): drei weitere Haertungen in
`probate/correct.py`, hier live mitbelegt statt nur in Unit-Tests:
- Die "seeded data"-Klausel kommt jetzt AUS der Evidenz
  (`p.evidence["seeded"]`), nie als Literal -- dieses Skript setzt sie
  von Hand auf `True`, weil es tatsaechlich gegen den geseedeten
  Katalog laeuft (siehe Proposal-Konstruktion unten).
- Fehlt `last_covered_ms`, enthaelt sich `enrich_doc` (Abstention) statt
  ein unbelegtes Datum zu schreiben -- dieser Lauf liefert es, deshalb
  wird hier der Schreibpfad, nicht der Enthaltungspfad belegt.
- Ein zweiter `enrich_doc`-Lauf gegen dieselbe Kante ersetzt den
  probate-Block, statt ihn zu verdoppeln -- dieser Live-Beweis schreibt
  nur einmal; die Idempotenz selbst ist in `tests/test_correct.py`
  (`test_enrich_doc_is_idempotent_a_second_run_replaces_not_duplicates`)
  belegt.

Zwei getrennte Beweise in einem Lauf, weil beide denselben
Journal-Mechanismus nutzen:

1. `enrich_doc` auf `finance_income_statement_consolidated` (Manifest-Paar "confirmed"):
   `editableDatasetProperties` existiert dort noch nicht (`None`) --
   deckt den Fall "vorher kein Aspekt" live ab.
2. `remove_edge` auf `store_sales_ranking_east` (Manifest-Paar "dead"): nimmt die
   ECHTE, bereits deklarierte Kante von `store_revenue_weekly_east` weg -- kein
   Wegwerf-Test-Edge, sondern die tatsaechliche Demo-Kante, revertiert
   danach exakt zurueck.

Kein neues Entity wird angelegt. `wb.revert_all()` rollt beide
Schreibvorgaenge in umgekehrter Reihenfolge zurueck; das Artefakt
vergleicht den Endzustand byte-genau mit dem WAHREN Originalzustand.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # fuer `probate.*` bei Direktlauf

from probate.correct import Proposal, apply_proposal, remove_edge  # noqa: E402
from probate.gms import Gms  # noqa: E402
from probate.writeback import Writeback  # noqa: E402

MANIFEST_PATH = Path("examples/seedlab-manifest.json")
JOURNAL_PATH = Path("harness/runs/_enrich_doc_remove_edge_journal.jsonl")


def _pair_from_manifest(manifest_path: Path, expected_state: str) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for edge in manifest["edges"]:
        if edge["expected_edge_state"] == expected_state:
            return edge
    raise ValueError(f"kein paar mit expected_edge_state={expected_state!r} im manifest")


def run(gms, manifest_path: Path = MANIFEST_PATH, out_path: Path | None = None) -> dict:
    if out_path is None:
        out_path = Path("harness/runs/enrich-doc-remove-edge-roundtrip.json")

    confirmed_pair = _pair_from_manifest(manifest_path, "confirmed")
    dead_pair = _pair_from_manifest(manifest_path, "dead")
    enrich_target = confirmed_pair["downstream_urn"]        # finance_income_statement_consolidated
    enrich_upstream = confirmed_pair["upstream_urn"]         # gl_journal_entries_daily
    remove_target = dead_pair["downstream_urn"]               # store_sales_ranking_east
    remove_upstream = dead_pair["upstream_urn"]                # store_revenue_weekly_east

    if JOURNAL_PATH.exists():
        JOURNAL_PATH.unlink()

    true_original_doc = gms.get_aspect("dataset", enrich_target, "editableDatasetProperties")
    true_original_lineage = gms.get_aspect("dataset", remove_target, "upstreamLineage")

    wb = Writeback(gms, dry_run=False, journal_path=str(JOURNAL_PATH))

    # --- Schreibvorgang 1: enrich_doc ueber den echten Produktweg ---------
    now_ms = int(time.time() * 1000)
    p = Proposal(
        kind="enrich_doc", edge_key=f"{enrich_upstream}->{enrich_target}",
        target_urn=enrich_target, aspect="editableDatasetProperties", state="confirmed",
        # "seeded": True von Hand gesetzt, nicht ueber propose() gelesen --
        # dieses Skript konstruiert das Proposal direkt (kein echter
        # ledger.run()-Lauf). Review-Fix CRITICAL 1: `apply_proposal`
        # rendert die "seeded data"-Klausel NUR, wenn die Evidenz das
        # traegt -- dieser Lauf laeuft tatsaechlich gegen den geseedeten
        # Beispielkatalog (siehe `seeded_statement` unten), also gehoert
        # der Wert hier hin, nicht als Literal in correct.py.
        evidence={"query_urns": ["urn:li:query:probate-enrich-doc-probe"],
                  "last_covered_ms": now_ms, "seeded": True},
        human_summary="harness/enrich_doc_probe.py -- committeter beweis",
    )
    enrich_result = apply_proposal(wb, p, now_ms=now_ms)
    after_enrich = gms.get_aspect("dataset", enrich_target, "editableDatasetProperties")

    # --- Schreibvorgang 2: remove_edge auf einer ECHTEN deklarierten Kante -
    remove_edge(wb, upstream=remove_upstream, downstream=remove_target, now_ms=now_ms)
    after_remove = gms.get_aspect("dataset", remove_target, "upstreamLineage")

    reverted = wb.revert_all()
    after_revert_doc = gms.get_aspect("dataset", enrich_target, "editableDatasetProperties")
    after_revert_lineage = gms.get_aspect("dataset", remove_target, "upstreamLineage")

    if JOURNAL_PATH.exists():
        JOURNAL_PATH.unlink()

    after_enrich_desc = ((after_enrich or {}).get("value") or {}).get("description", "")
    after_remove_upstreams = ((after_remove or {}).get("value") or {}).get("upstreams", [])

    artifact = {
        "seeded": True,
        "seeded_statement": (
            "Laeuft gegen den geseedeten Beispielkatalog (namespace probate_seedlab, "
            "harness/seed_lineage_lab.py) -- kein neues Entity angelegt, nur bestehende "
            "Aspekte geschrieben und vollstaendig zurueckgerollt."
        ),
        "gms_url": gms.base,
        "manifest": str(manifest_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "enrich_doc": {
            "target": enrich_target,
            "upstream": enrich_upstream,
            "true_original": true_original_doc,
            "applied": getattr(enrich_result, "applied", None),
            "after_write": after_enrich,
            "after_revert": after_revert_doc,
            "revert_restored_exactly": after_revert_doc == true_original_doc,
            "description_mentions_probate": "probate" in after_enrich_desc,
            "description_mentions_seeded": "seeded" in after_enrich_desc,
            "description_did_not_overwrite_because_there_was_nothing_to_overwrite": (
                true_original_doc is None
            ),
        },
        "remove_edge": {
            "target": remove_target,
            "removed_upstream": remove_upstream,
            "true_original": true_original_lineage,
            "after_write": after_remove,
            "after_revert": after_revert_lineage,
            "revert_restored_exactly": after_revert_lineage == true_original_lineage,
            "upstream_absent_after_remove": remove_upstream not in {
                u.get("dataset") for u in after_remove_upstreams
            },
        },
        "revert_count": reverted,
        "all_reverted_exactly": (
            after_revert_doc == true_original_doc
            and after_revert_lineage == true_original_lineage
        ),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    return artifact


if __name__ == "__main__":
    result = run(Gms())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["all_reverted_exactly"]:
        sys.exit(1)  # Regel verification.md: eine gescheiterte Pruefung ist kein stilles Weiterlaufen
