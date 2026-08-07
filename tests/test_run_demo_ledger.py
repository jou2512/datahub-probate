"""Die Nicht-Netz-Teile des Demo-Laufs (`harness/run_demo_ledger.py`).

Der Lauf selbst ist live und gehoert nicht in einen Unit-Test. Was hier
geprueft wird, ist die Stelle, an der aus dem Lauf eine BEHAUPTUNG wird:
der Abgleich gegen das Manifest. Wuerde er eine fehlende Kante als
Uebereinstimmung durchgehen lassen, waere das Artefakt eine Zahl ohne
Deckung -- genau die Fehlerklasse, gegen die dieses Projekt antritt.

Kein Mock-Rahmenwerk (global-constraints.md): handgeschriebene Fakes.
"""

from __future__ import annotations

import json

from harness.run_demo_ledger import compare_with_manifest, load_focuses, measure_console


def _manifest(tmp_path, edges, focuses=("urn:li:dataset:(p,a.f,PROD)",)):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"focuses": list(focuses), "edges": edges}),
                 encoding="utf-8")
    return p


def _edge(up, down, state):
    return {"edge": f"{up}->{down}", "upstream": up, "downstream": down,
            "state": state, "evidence": {"source": "fake"},
            "coverage": {"buckets_seen": 3, "days_span": 2, "reason": ""},
            "timeline": {"series": [[1, 5]], "last_covered_ms": 1,
                         "dead_since_days": 0}}


def test_all_matched(tmp_path):
    m = _manifest(tmp_path, [
        {"upstream_urn": "a", "downstream_urn": "b", "expected_state": "confirmed"},
        {"upstream_urn": "a", "downstream_urn": "c", "expected_state": "dead"},
    ])
    out = compare_with_manifest(
        [_edge("a", "b", "confirmed"), _edge("a", "c", "dead")], m)
    assert out["manifest_all_matched"] is True
    assert out["manifest_edges_matched"] == 2
    assert out["manifest_edges_mismatched"] == 0


def test_wrong_state_is_a_finding_not_a_pass(tmp_path):
    m = _manifest(tmp_path, [
        {"upstream_urn": "a", "downstream_urn": "b", "expected_state": "confirmed"}])
    out = compare_with_manifest([_edge("a", "b", "unknown")], m)
    assert out["manifest_all_matched"] is False
    assert out["manifest_confusion"] == {"confirmed->unknown": 1}


def test_absent_edge_is_not_silently_a_match(tmp_path):
    """Eine Kante, die der Lauf gar nicht gefunden hat, ist NICHT
    'stimmt ueberein'. Fehlend und falsch sind zwei Befunde, nicht einer."""
    m = _manifest(tmp_path, [
        {"upstream_urn": "a", "downstream_urn": "b", "expected_state": "confirmed"}])
    out = compare_with_manifest([], m)
    assert out["manifest_all_matched"] is False
    assert out["manifest_edges_absent"] == 1
    assert out["manifest_edges_matched"] == 0
    assert out["manifest_absent_sample"] == ["a -> b"]


def test_extra_measured_edges_do_not_break_the_comparison(tmp_path):
    """Der Lauf umfasst zusaetzlich die vier Labor-Fokusse. Sie stehen
    nicht im Demo-Manifest und duerfen den Abgleich nicht kippen."""
    m = _manifest(tmp_path, [
        {"upstream_urn": "a", "downstream_urn": "b", "expected_state": "confirmed"}])
    out = compare_with_manifest(
        [_edge("a", "b", "confirmed"), _edge("lab", "lab2", "dead")], m)
    assert out["manifest_all_matched"] is True
    assert out["manifest_edges"] == 1


def test_load_focuses_keeps_both_lists_separate(tmp_path):
    demo_dir = tmp_path / "d"
    demo_dir.mkdir()
    demo = _manifest(demo_dir, [], focuses=["f2", "f1"])
    lab = tmp_path / "lab.json"
    lab.write_text(json.dumps({"edges": [
        {"upstream_urn": "L1", "downstream_urn": "x"},
        {"upstream_urn": "L2", "downstream_urn": "y"}]}), encoding="utf-8")
    demo_focuses, lab_focuses = load_focuses(demo, lab)
    assert demo_focuses == ["f1", "f2"]      # sortiert, damit reproduzierbar
    assert lab_focuses == ["L1", "L2"]       # Manifest-Reihenfolge


def test_measure_console_works_without_gms():
    """Die Messung der serverseitigen Konsolen-Arbeit braucht kein GMS --
    nur der Katalog-Baum tut das, und der wird dann ausgelassen statt
    erfunden."""
    edges = [_edge("urn:li:dataset:(urn:li:dataPlatform:postgres,db.sch.t1,PROD)",
                   "urn:li:dataset:(urn:li:dataPlatform:snowflake,db2.sch.t2,PROD)",
                   "confirmed")]
    out = measure_console(edges, None, repeats=2)
    assert out["console_edges_measured"] == 1
    assert out["console_ms_page_unfiltered"] >= 0
    assert "console_ms_catalog_page" not in out
