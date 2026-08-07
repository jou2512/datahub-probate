"""Die Kosten eines Modellaufrufs sind eine MESSUNG, keine Schaetzung --
und eine fehlende Messung darf nie als 0.0 durchgehen.

Alle Tests hier speisen einen handgeschriebenen Fake-Runner ein, nie einen
echten Prozess (Hard Rule: offline-only, kein Mock-Rahmenwerk).
"""

import json

import pytest

from probate.judge import JudgeTransportError
from ui.judging import deviating_rows, judge_edges_metered, metered_transport


def _envelope(result: str, **extra) -> str:
    body = {"result": result, "total_cost_usd": 0.1234, "duration_ms": 2000,
            "usage": {"input_tokens": 11, "output_tokens": 7}}
    body.update(extra)
    return json.dumps(body)


class _Proc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def test_the_cli_envelope_is_measured_instead_of_thrown_away():
    """`probate.judge.claude_cli_transport` reicht nur `result` durch und
    wirft den Umschlag weg -- genau dort stehen aber die Zahlen, die das
    Live-Protokoll laut Spec zeigen muss."""
    sink = []
    send = metered_transport(sink, runner=lambda *a, **kw: _Proc(_envelope('{"important": false}')))
    out = send("prompt")
    assert out == '{"important": false}'
    assert len(sink) == 1
    assert sink[0]["cost_usd"] == 0.1234
    assert sink[0]["input_tokens"] == 11
    assert sink[0]["output_tokens"] == 7
    assert sink[0]["ok"] is True
    assert sink[0]["seconds"] >= 0


def test_a_missing_cost_field_stays_none_and_never_becomes_zero():
    """Eine nicht gemessene Zahl als 0.0 auszugeben waere die Behauptung
    "der Aufruf war gratis" -- genau die Sorte Aussage, gegen die dieses
    Projekt antritt."""
    sink = []
    body = json.dumps({"result": "{}"})  # kein total_cost_usd
    send = metered_transport(sink, runner=lambda *a, **kw: _Proc(body))
    send("prompt")
    assert sink[0]["cost_usd"] is None


def test_a_failed_call_is_a_named_failure_and_still_leaves_a_measurement():
    """Eine gescheiterte Abfrage ist keine Abwesenheit: der Fehlschlag
    bekommt einen Namen UND einen Eintrag mit gemessener Dauer, sonst
    verschwindet er aus dem Protokoll."""
    sink = []
    send = metered_transport(sink, runner=lambda *a, **kw: _Proc("", "not logged in", 1))
    with pytest.raises(JudgeTransportError):
        send("prompt")
    assert sink[0]["ok"] is False
    assert "not logged in" in sink[0]["error"]


def test_only_deviating_edges_reach_the_model():
    """Der teure Teil haengt an der Zahl der ABWEICHUNGEN, nicht an der
    Gesamtzahl der Kanten -- eine bestaetigte Kante braucht kein Urteil."""
    ledger = {"edges": [
        {"state": "confirmed", "edge": "a->b"},
        {"state": "dead", "edge": "c->d"},
        {"state": "missing", "edge": "e->f"},
        {"state": "unknown", "edge": "g->h"},
    ]}
    assert [r["edge"] for r in deviating_rows(ledger)] == ["c->d", "e->f", "g->h"]


class _FakeGms:
    """Liefert einen Kontext ohne zitierfaehigen Text -- jedes Urteil
    faellt damit in den Rueckfall, was fuer diesen Test genau richtig ist:
    geprueft wird die Messung um den Aufruf herum, nicht das Urteil."""

    def graphql(self, q, v=None):
        return {"dataset": {}}


def test_every_judged_edge_reports_its_own_call_with_its_own_meter():
    """Ein gemeinsamer Aufruf-Stapel haette Urteil und Kosten nur ueber
    die Reihenfolge verknuepft -- also ueber eine Annahme. Jede Kante
    bekommt ihren eigenen gemessenen Aufruf."""
    ledger = {"edges": [
        {"state": "dead", "edge": "c->d", "upstream": "c", "downstream": "d", "evidence": {}},
        {"state": "missing", "edge": "e->f", "upstream": "e", "downstream": "f", "evidence": {}},
    ]}
    seen = []

    def factory(sink):
        return metered_transport(sink, runner=lambda *a, **kw: _Proc(
            _envelope(json.dumps({"important": True, "reason": "r", "quote": "nope",
                                   "source_field": "description"}))))

    totals = judge_edges_metered(_FakeGms(), ledger,
                                  lambda j, m: seen.append((j["edge"], m["cost_usd"])),
                                  transport_factory=factory)
    assert [e for e, _ in seen] == ["c->d", "e->f"]
    assert all(cost == 0.1234 for _, cost in seen)
    assert totals["calls"] == 2
    assert totals["cost_usd"] == pytest.approx(0.2468)


def test_the_total_cost_stays_none_when_a_single_call_did_not_report_one():
    """Teilweise gemessene Kosten sind keine Gesamtkosten. Eine zu
    kleine Zahl waere schlimmer als gar keine."""
    ledger = {"edges": [
        {"state": "dead", "edge": "c->d", "upstream": "c", "downstream": "d", "evidence": {}},
    ]}

    def factory(sink):
        return metered_transport(sink, runner=lambda *a, **kw: _Proc(json.dumps({"result": "{}"})))

    totals = judge_edges_metered(_FakeGms(), ledger, lambda j, m: None,
                                  transport_factory=factory)
    assert totals["cost_usd"] is None
    assert totals["calls"] == 1
