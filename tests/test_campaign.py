import pytest
from probate.campaign import NoEvidenceError, create_campaign, ensure_owner, verify, autofill


class RecordingWb:
    def __init__(self, gms=None):
        self.queries = []
        self.dry_run = False
        self.gms = gms

    def mutation(self, name, query):
        self.queries.append((name, query))
        return type("R", (), {"applied": True, "before": None, "detail": name})()

    def aspect(self, entity_type, urn, aspect, value):
        self.queries.append((f"aspect:{aspect}", value))
        return type("R", (), {"applied": True, "before": None, "detail": aspect})()


class FakeGms:
    def __init__(self, existing=None):
        self.existing = existing or {}

    def get_aspect(self, entity_type, urn, aspect):
        return self.existing.get((entity_type, urn, aspect))


def test_create_campaign_puts_structured_property_params_on_the_prompt_itself():
    """Live-Fund: createForm lehnt einen STRUCTURED_PROPERTY-Prompt ohne
    eigene structuredPropertyParams mit HTTP 400 ab."""
    wb = RecordingWb()
    form_urn = create_campaign(wb, "f1", "Test-Kampagne", [("p1", "urn:li:structuredProperty:probate_migrated")])
    assert form_urn == "urn:li:form:f1"
    _, q = wb.queries[0]
    assert 'structuredPropertyParams: { urn: "urn:li:structuredProperty:probate_migrated" }' in q
    assert "actors: { owners: true }" in q


def test_verify_refuses_without_evidence():
    wb = RecordingWb()
    with pytest.raises(NoEvidenceError):
        verify(wb, "urn:li:form:f", "urn:li:dataset:d", evidence={})
    assert wb.queries == []


def test_verify_runs_with_evidence():
    wb = RecordingWb()
    verify(wb, "urn:li:form:f", "urn:li:dataset:d", evidence={"query_log": "3 Treffer auf v2"})
    assert wb.queries[0][0] == "verifyForm"


def test_autofill_puts_the_asset_urn_first_not_in_the_input():
    """submitFormPrompt nimmt das Asset als eigenes erstes Argument."""
    wb = RecordingWb()
    autofill(wb, "urn:li:form:f", "urn:li:dataset:d", "p1",
             "urn:li:structuredProperty:probate.status", "migriert",
             evidence={"query_log": "x"})
    _, q = wb.queries[0]
    assert 'urn: "urn:li:dataset:d"' in q
    assert '"urn:li:dataset:d"' not in q.split("input:")[1]


def test_ensure_owner_skips_write_when_already_owner():
    """Kein unnoetiger Schreibvorgang, wenn actor schon Owner ist."""
    g = FakeGms(existing={
        ("dataset", "urn:li:dataset:d", "ownership"):
            {"value": {"owners": [{"owner": "urn:li:corpuser:__datahub_system", "type": "TECHNICAL_OWNER"}]}}
    })
    wb = RecordingWb(gms=g)
    changed = ensure_owner(wb, "dataset", "urn:li:dataset:d", "urn:li:corpuser:__datahub_system")
    assert changed is False
    assert wb.queries == []


def test_ensure_owner_adds_actor_without_dropping_existing_owners():
    g = FakeGms(existing={
        ("dataset", "urn:li:dataset:d", "ownership"):
            {"value": {"owners": [{"owner": "urn:li:corpuser:someone_else", "type": "TECHNICAL_OWNER"}]}}
    })
    wb = RecordingWb(gms=g)
    changed = ensure_owner(wb, "dataset", "urn:li:dataset:d", "urn:li:corpuser:__datahub_system")
    assert changed is True
    name, value = wb.queries[0]
    assert name == "aspect:ownership"
    owner_urns = {o["owner"] for o in value["owners"]}
    assert owner_urns == {"urn:li:corpuser:someone_else", "urn:li:corpuser:__datahub_system"}


def test_ensure_owner_handles_no_prior_ownership_aspect():
    g = FakeGms()  # keine ownership-Aspekt vorhanden
    wb = RecordingWb(gms=g)
    changed = ensure_owner(wb, "dataset", "urn:li:dataset:d", "urn:li:corpuser:__datahub_system")
    assert changed is True
    _, value = wb.queries[0]
    assert value["owners"] == [{"owner": "urn:li:corpuser:__datahub_system", "type": "TECHNICAL_OWNER"}]
