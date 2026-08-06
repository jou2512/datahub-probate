import pytest
from probate.parity import SchemaDiff, verdict
from probate.succession import RefusedError, succeed


class RecordingWb:
    def __init__(self):
        self.calls = []
        self.dry_run = False

    def mutation(self, name, query):
        self.calls.append(name)
        return type("R", (), {"applied": True, "before": None, "detail": name})()

    def aspect(self, entity_type, urn, aspect, value):
        self.calls.append(f"aspect:{aspect}")
        self.last_aspect_value = value
        return type("R", (), {"applied": True, "before": None, "detail": aspect})()


GOOD = verdict(SchemaDiff([], [], []), counts={"old": 100, "new": 100})
BAD = verdict(SchemaDiff(["email"], [], []), counts={"old": 100, "new": 100})


def test_refuses_to_switch_without_proof():
    wb = RecordingWb()
    with pytest.raises(RefusedError) as exc:
        succeed(wb, "urn:a", "urn:b", BAD, ["urn:li:assertion:x"])
    assert "email" in str(exc.value)
    assert wb.calls == []


def test_switches_in_the_right_order_when_proven():
    wb = RecordingWb()
    succeed(wb, "urn:a", "urn:b", GOOD, ["urn:li:assertion:x"])
    assert wb.calls == ["upsertDataContract", "linkAssetVersion", "aspect:deprecation"]


def test_deprecation_names_the_successor():
    wb = RecordingWb()
    out = succeed(wb, "urn:a", "urn:b", GOOD, ["urn:li:assertion:x"])
    assert "urn:b" in out["deprecation_note"]


def test_deprecation_carries_a_structured_replacement_link():
    """Nicht nur Text im note-Feld -- Deprecation.replacement ist genau
    dafuer da und macht den Nachfolger filterbar/abfragbar."""
    wb = RecordingWb()
    succeed(wb, "urn:a", "urn:b", GOOD, ["urn:li:assertion:x"])
    assert wb.last_aspect_value["replacement"] == "urn:b"
