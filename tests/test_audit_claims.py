from harness.audit_claims import check_claim


def test_matching_claim_passes():
    assert check_claim("live_targets", claimed=12, measured=12).ok is True


def test_drifted_claim_fails_and_names_both_numbers():
    r = check_claim("live_targets", claimed=12, measured=9)
    assert r.ok is False
    assert "12" in r.detail and "9" in r.detail


def test_a_claim_without_a_measurement_fails_rather_than_passes():
    r = check_claim("live_targets", claimed=12, measured=None)
    assert r.ok is False
