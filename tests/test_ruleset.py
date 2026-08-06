from probate.ruleset import Rule, evaluate
from probate.ruleset import test_results_aspect as build_test_results_aspect
# Alias noetig: ein importierter Name test_results_aspect wird von pytest
# selbst als Testfunktion eingesammelt (beginnt mit "test_") und schlaegt
# an fehlenden Fixture-Argumenten fehl -- live beobachtet (2026-08-06),
# nicht im Plantext bedacht.


RULES = [
    Rule("has-successor", "Nachfolger benannt", lambda f: bool(f.get("successor"))),
    Rule("parity-proven", "Gleichwertigkeit bewiesen", lambda f: f.get("parity_ok") is True),
]


def test_evaluate_splits_pass_and_fail():
    out = evaluate(RULES, {"successor": "urn:x", "parity_ok": False})
    by_id = {o.rule_id: o.passed for o in out}
    assert by_id == {"has-successor": True, "parity-proven": False}


def test_definition_md5_is_stable_for_the_same_rule():
    a = evaluate(RULES, {})[0].definition_md5
    b = evaluate(RULES, {})[0].definition_md5
    assert a == b and len(a) == 32


def test_aspect_has_passing_and_failing_lists():
    aspect = build_test_results_aspect(evaluate(RULES, {"successor": "urn:x"}), evaluated_at=123)
    assert [t["test"] for t in aspect["passing"]] == ["urn:li:test:has-successor"]
    assert [t["test"] for t in aspect["failing"]] == ["urn:li:test:parity-proven"]


def test_aspect_has_no_invented_fields_outside_the_real_schema():
    """TestResults.pdl kennt nur failing/passing -- kein Zeitstempelfeld.

    Ein erfundenes Feld wird von REST v3 stillschweigend verworfen
    (live gemessen 2026-08-06): HTTP 200 ohne Wirkung.
    """
    aspect = build_test_results_aspect(evaluate(RULES, {}), evaluated_at=123)
    assert set(aspect.keys()) == {"passing", "failing"}


def test_a_rule_that_raises_counts_as_failing_not_as_passing():
    boom = Rule("boom", "wirft", lambda f: 1 / 0)
    out = evaluate([boom], {})
    assert out[0].passed is False
