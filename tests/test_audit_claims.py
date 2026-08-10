import json
from pathlib import Path

import pytest

import harness.audit_claims as audit_claims
from harness.audit_claims import (
    ConflictingClaim,
    _run_file_status,
    check_claim,
    load_runs,
    main,
)


def test_matching_claim_passes():
    assert check_claim("live_targets", claimed=12, measured=12).ok is True


def test_drifted_claim_fails_and_names_both_numbers():
    r = check_claim("live_targets", claimed=12, measured=9)
    assert r.ok is False
    assert "12" in r.detail and "9" in r.detail


def test_a_claim_without_a_measurement_fails_rather_than_passes():
    r = check_claim("live_targets", claimed=12, measured=None)
    assert r.ok is False


def test_merges_scalar_keys_from_every_known_run_artefact(tmp_path):
    (tmp_path / "campaign.json").write_text(json.dumps({"live_consumers": 1}))
    (tmp_path / "ledger.json").write_text(json.dumps({"edges_dead": 41, "edges": [1, 2]}))
    merged = load_runs(tmp_path)
    assert merged["live_consumers"] == 1
    assert merged["edges_dead"] == 41


def test_nested_values_are_skipped_because_a_claim_is_always_a_scalar(tmp_path):
    (tmp_path / "ledger.json").write_text(json.dumps({"edges": [{"state": "dead"}]}))
    assert "edges" not in load_runs(tmp_path)


def test_a_missing_artefact_is_skipped_not_an_error(tmp_path):
    (tmp_path / "ledger.json").write_text(json.dumps({"edges_dead": 3}))
    assert load_runs(tmp_path) == {"edges_dead": 3}


def test_the_same_key_with_two_different_values_is_loud_not_last_wins(tmp_path):
    """Zwei Artefakte, die dasselbe verschieden behaupten, sind ein
    Befund -- kein 'das letzte gewinnt'. Genau daraus entsteht sonst
    eine Zahl im README, die niemand mehr herleiten kann."""
    (tmp_path / "campaign.json").write_text(json.dumps({"edges_dead": 41}))
    (tmp_path / "ledger.json").write_text(json.dumps({"edges_dead": 12}))
    with pytest.raises(ConflictingClaim):
        load_runs(tmp_path)


def test_the_same_key_with_the_same_value_twice_is_fine(tmp_path):
    (tmp_path / "campaign.json").write_text(json.dumps({"edges_dead": 41}))
    (tmp_path / "ledger.json").write_text(json.dumps({"edges_dead": 41}))
    assert load_runs(tmp_path)["edges_dead"] == 41


def test_conflicting_claim_names_both_files_and_both_values(tmp_path):
    (tmp_path / "campaign.json").write_text(json.dumps({"edges_dead": 41}))
    (tmp_path / "ledger.json").write_text(json.dumps({"edges_dead": 12}))
    with pytest.raises(ConflictingClaim) as exc_info:
        load_runs(tmp_path)
    message = str(exc_info.value)
    assert "campaign.json" in message
    assert "ledger.json" in message
    assert "41" in message
    assert "12" in message


def test_a_run_file_that_is_not_valid_json_is_reported_as_broken_not_missing(tmp_path):
    (tmp_path / "campaign.json").write_text("{not json")
    with pytest.raises(ValueError) as exc_info:
        load_runs(tmp_path)
    assert "campaign.json" in str(exc_info.value)


def test_run_file_status_distinguishes_present_from_absent(tmp_path):
    (tmp_path / "campaign.json").write_text(json.dumps({"live_consumers": 1}))
    (tmp_path / "ledger.json").write_text(json.dumps({"edges_dead": 3}))
    found, missing = _run_file_status(tmp_path)
    assert "campaign.json" in found
    assert "ledger.json" in found
    assert "seedlab-verdicts.json" in missing
    assert set(found).isdisjoint(missing)
    assert set(found) | set(missing) == set(audit_claims.RUN_FILES)


def test_main_reports_which_files_it_read_and_which_it_did_not_find(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(audit_claims, "RUNS", tmp_path)
    (tmp_path / "campaign.json").write_text(json.dumps({"live_consumers": 1}))
    (tmp_path / "claims.json").write_text(json.dumps({"live_consumers": 1}))
    main()
    out = capsys.readouterr().out
    assert "campaign.json" in out
    assert "ledger.json" in out  # als 'nicht vorhanden' genannt, nicht verschwiegen


def test_main_exits_1_and_names_both_artefacts_on_a_conflict(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(audit_claims, "RUNS", tmp_path)
    (tmp_path / "campaign.json").write_text(json.dumps({"edges_dead": 41}))
    (tmp_path / "ledger.json").write_text(json.dumps({"edges_dead": 12}))
    (tmp_path / "claims.json").write_text(json.dumps({}))
    assert main() == 1
    out = capsys.readouterr().out
    assert "CONTRADICT" in out
    assert "campaign.json" in out and "ledger.json" in out


def test_metadata_keys_that_legitimately_differ_per_artefact_are_not_merged(tmp_path):
    """'seeded' und 'scale' beschreiben DIESEN Lauf, nicht eine geteilte
    Tatsache -- ein Read-only-Smoke-Check (seeded=false) neben einem
    geseedeten Lasttest (seeded=true) ist kein Widerspruch, sondern zwei
    wahre Aussagen ueber zwei verschiedene Laeufe. Belegt am echten Fall
    aus Task 25: loadtest_smoke.json vs. loadgen_smoke.json."""
    (tmp_path / "campaign.json").write_text(json.dumps({"seeded": True, "scale": "s"}))
    (tmp_path / "ledger.json").write_text(json.dumps({"seeded": False, "scale": "m"}))
    merged = load_runs(tmp_path)
    assert "seeded" not in merged
    assert "scale" not in merged


def test_seeded_statement_and_generated_at_are_also_excluded_as_per_artefact_prose(tmp_path):
    """Freitext-Erklaerungen und Erzeugungszeitstempel sind je Lauf
    verschieden und sollen es sein -- kein Fall fuer ConflictingClaim."""
    (tmp_path / "campaign.json").write_text(
        json.dumps({"seeded_statement": "laeuft gegen A", "generated_at": "2026-08-07T01:00:00Z"})
    )
    (tmp_path / "ledger.json").write_text(
        json.dumps({"seeded_statement": "laeuft gegen B", "generated_at": "2026-08-07T02:00:00Z"})
    )
    merged = load_runs(tmp_path)
    assert "seeded_statement" not in merged
    assert "generated_at" not in merged


def test_every_run_file_from_task_25_is_read_without_a_conflict():
    """Regressionsschutz fuer die eigentliche Aufgabe: load_runs() ueber
    die echten, committeten Artefakte in harness/runs/ darf nicht mehr
    an 'seeded'/'scale'/'seeded_statement'/'generated_at' scheitern."""
    merged = load_runs()
    assert merged  # es gibt etwas zu behaupten
    assert "seeded" not in merged
    assert "scale" not in merged


def test_main_still_passes_the_three_existing_campaign_claims(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(audit_claims, "RUNS", tmp_path)
    (tmp_path / "campaign.json").write_text(
        json.dumps({"live_consumers": 1, "parity_ok": True, "signed_count": 1})
    )
    (tmp_path / "claims.json").write_text(
        json.dumps({"live_consumers": 1, "parity_ok": True, "signed_count": 1})
    )
    assert main() == 0
    out = capsys.readouterr().out
    assert "All 3 numbers match the recorded runs" in out


def test_every_claim_has_a_matching_key_in_some_run_artefact():
    """Eine Behauptung ohne Beleg-Schluessel ist genau der Fehler, gegen
    den dieses Werkzeug antritt."""
    from harness.audit_claims import load_runs
    claims = json.loads(Path("harness/runs/claims.json").read_text(encoding="utf-8"))
    runs = load_runs()
    missing = [k for k in claims if k not in runs]
    assert not missing, f"behauptet, aber nirgends gemessen: {missing}"
