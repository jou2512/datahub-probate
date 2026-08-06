from probate.targets import Targets, classify


def test_splits_into_three_buckets():
    t = classify(declared={"a", "b"}, measured={"b", "c"})
    assert t.both == {"b"}
    assert t.declared_only == {"a"}
    assert t.measured_only == {"c"}


def test_live_is_measured_plus_both_never_declared_only():
    """Eine Karteileiche haelt die Abloesung nicht auf."""
    t = classify(declared={"karteileiche", "echt"}, measured={"echt", "unbekannt"})
    assert t.live == {"echt", "unbekannt"}
    assert "karteileiche" not in t.live


def test_measured_only_is_reported_as_missing_lineage():
    t = classify(declared=set(), measured={"x"})
    assert t.missing_lineage == {"x"}


def test_empty_inputs_are_not_an_error():
    t = classify(declared=set(), measured=set())
    assert t.live == set()
    assert t.summary()["live"] == 0
