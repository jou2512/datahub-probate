from probate.parity import SchemaDiff, compare_schemas, verdict


def _f(path, type_):
    return {"fieldPath": path, "type": type_}


def test_missing_column_is_detected():
    d = compare_schemas([_f("id", "NUMBER"), _f("email", "STRING")], [_f("id", "NUMBER")])
    assert d.missing == ["email"]
    assert d.added == []


def test_type_change_is_detected():
    d = compare_schemas([_f("id", "NUMBER")], [_f("id", "STRING")])
    assert d.type_changed == [("id", "NUMBER", "STRING")]


def test_added_column_is_not_a_failure():
    v = verdict(compare_schemas([_f("id", "NUMBER")], [_f("id", "NUMBER"), _f("new", "STRING")]),
                counts={"old": 100, "new": 100})
    assert v.ok is True


def test_missing_column_fails_the_verdict():
    v = verdict(compare_schemas([_f("id", "NUMBER"), _f("email", "STRING")], [_f("id", "NUMBER")]),
                counts={"old": 100, "new": 100})
    assert v.ok is False
    assert any("email" in r for r in v.reasons)


def test_row_count_gap_beyond_one_percent_fails():
    v = verdict(SchemaDiff([], [], []), counts={"old": 1000, "new": 900})
    assert v.ok is False
    assert any("Zeilenzahl" in r for r in v.reasons)


def test_unknown_counts_abstain_rather_than_pass():
    """Kein Beleg heisst nicht 'in Ordnung'."""
    v = verdict(SchemaDiff([], [], []), counts={})
    assert v.ok is False
    assert any("unbekannt" in r for r in v.reasons)


def test_evidence_is_always_attached():
    v = verdict(SchemaDiff([], [], []), counts={"old": 10, "new": 10})
    assert v.evidence["counts"] == {"old": 10, "new": 10}
