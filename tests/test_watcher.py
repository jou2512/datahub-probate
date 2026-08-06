import json

from probate_action.watcher import ProbateWatcher, is_relapse


def _ev(urn, aspect="operation"):
    return {"entityUrn": urn, "aspectName": aspect}


def test_access_to_a_closed_asset_is_a_relapse():
    assert is_relapse(_ev("urn:li:dataset:a"), closed_urns={"urn:li:dataset:a"}) is True


def test_access_to_an_open_asset_is_not():
    assert is_relapse(_ev("urn:li:dataset:b"), closed_urns={"urn:li:dataset:a"}) is False


def test_our_own_metadata_writes_are_not_a_relapse():
    """Sonst loest der Waechter sich selbst aus."""
    assert is_relapse(_ev("urn:li:dataset:a", "deprecation"), closed_urns={"urn:li:dataset:a"}) is False


def test_an_event_without_urn_is_ignored_not_crashed():
    assert is_relapse({}, closed_urns={"urn:li:dataset:a"}) is False


class FakeCtx:
    graph = object()


class RecordingWb:
    def __init__(self):
        self.mutations = []
        self.dry_run = True

    def mutation(self, name, query):
        self.mutations.append((name, query))
        return type("R", (), {"applied": True, "before": None, "detail": name})()


class FakeMcl:
    def __init__(self, urn, aspect):
        self.entityUrn = urn
        self.aspectName = aspect


class FakeEnvelope:
    def __init__(self, urn, aspect):
        self.event = FakeMcl(urn, aspect)


def test_create_loads_closed_urns_from_file(tmp_path):
    f = tmp_path / "closed.json"
    f.write_text(json.dumps(["urn:li:dataset:a", "urn:li:dataset:b"]))
    w = ProbateWatcher.create({"closed_urns_file": str(f)}, FakeCtx())
    assert w.closed_urns == {"urn:li:dataset:a", "urn:li:dataset:b"}


def test_create_tolerates_a_missing_file(tmp_path):
    """Kein Rueckfall-Katalog bedeutet keinen Rueckfall, nicht einen Crash."""
    w = ProbateWatcher.create({"closed_urns_file": str(tmp_path / "nope.json")}, FakeCtx())
    assert w.closed_urns == set()


def test_act_journals_a_relapse_via_writeback():
    w = ProbateWatcher(closed_urns={"urn:li:dataset:a"}, wb=RecordingWb())
    w.act(FakeEnvelope("urn:li:dataset:a", "operation"))
    assert w.wb.mutations
    assert w.wb.mutations[0][0] == "raiseIncident"


def test_act_ignores_a_non_relapse_event():
    w = ProbateWatcher(closed_urns={"urn:li:dataset:a"}, wb=RecordingWb())
    w.act(FakeEnvelope("urn:li:dataset:b", "operation"))
    assert w.wb.mutations == []
