import json
from probate.writeback import Writeback


class FakeGms:
    def __init__(self, existing=None):
        self.existing = existing or {}
        self.upserts = []
        self.deletes = []

    def get_aspect(self, entity_type, urn, aspect):
        return self.existing.get((entity_type, urn, aspect))

    def upsert(self, entity_type, records, sync=True):
        self.upserts.append((entity_type, records))
        return records

    def delete_aspect(self, entity_type, urn, aspect):
        self.deletes.append((entity_type, urn, aspect))


def test_dry_run_writes_nothing(tmp_path):
    g = FakeGms()
    w = Writeback(g, dry_run=True, journal_path=str(tmp_path / "j.jsonl"))
    r = w.aspect("dataset", "urn:li:dataset:x", "deprecation", {"deprecated": True})
    assert r.applied is False
    assert g.upserts == []


def test_apply_writes_and_journals_the_previous_value(tmp_path):
    j = tmp_path / "j.jsonl"
    g = FakeGms(existing={("dataset", "urn:li:dataset:x", "deprecation"): {"value": {"deprecated": False}}})
    w = Writeback(g, dry_run=False, journal_path=str(j))
    r = w.aspect("dataset", "urn:li:dataset:x", "deprecation", {"deprecated": True})
    assert r.applied is True
    assert r.before == {"value": {"deprecated": False}}
    entry = json.loads(j.read_text().strip())
    assert entry["urn"] == "urn:li:dataset:x"
    assert entry["before"] == {"value": {"deprecated": False}}


def test_upsert_gets_a_list_not_an_object(tmp_path):
    g = FakeGms()
    w = Writeback(g, dry_run=False, journal_path=str(tmp_path / "j.jsonl"))
    w.aspect("dataset", "urn:li:dataset:x", "deprecation", {"deprecated": True})
    _, records = g.upserts[0]
    assert isinstance(records, list)


def test_revert_restores_every_journalled_write(tmp_path):
    j = tmp_path / "j.jsonl"
    g = FakeGms(existing={("dataset", "u", "deprecation"): {"value": {"deprecated": False}}})
    w = Writeback(g, dry_run=False, journal_path=str(j))
    w.aspect("dataset", "u", "deprecation", {"deprecated": True})
    g.upserts.clear()
    assert w.revert_all() == 1
    entity_type, records = g.upserts[0]
    assert records[0]["deprecation"]["value"] == {"deprecated": False}


def test_revert_deletes_a_first_time_write_instead_of_upserting_none(tmp_path):
    """Der Normalfall bei probate: der Aspekt gab es vorher nicht.

    Live gemessen (2026-08-06): ein Revert-Upsert mit before=None schlaegt
    an Pflichtfeldern der echten Aspekt-Validierung fehl (z.B.
    Deprecation.actor). Richtig ist LOESCHEN, nicht ein erfundenes None
    zurueckschreiben.
    """
    j = tmp_path / "j.jsonl"
    g = FakeGms()  # kein existing -> before ist None
    w = Writeback(g, dry_run=False, journal_path=str(j))
    w.aspect("dataset", "u", "deprecation", {"deprecated": True})
    g.upserts.clear()
    assert w.revert_all() == 1
    assert g.upserts == []
    assert g.deletes == [("dataset", "u", "deprecation")]
