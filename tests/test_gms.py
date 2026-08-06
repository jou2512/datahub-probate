import pytest
from probate.gms import Gms, GmsError


class FakeTransport:
    """Nimmt auf, was gesendet wurde, und gibt vorbereitete Antworten zurueck."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, payload):
        self.calls.append((method, url, payload))
        return self.responses.pop(0)


def test_graphql_raises_on_errors_despite_http_200():
    t = FakeTransport([(200, {"data": None, "errors": [{"message": "boom"}]})])
    with pytest.raises(GmsError) as exc:
        Gms("http://x", transport=t).graphql("{ me { urn } }")
    assert "boom" in str(exc.value)


def test_graphql_returns_data_when_clean():
    t = FakeTransport([(200, {"data": {"me": {"urn": "u"}}})])
    assert Gms("http://x", transport=t).graphql("{ me { urn } }") == {"me": {"urn": "u"}}


def test_upsert_rejects_a_bare_dict():
    """Die Falle: ein Objekt statt einer Liste gibt HTTP 200 und schreibt nichts."""
    t = FakeTransport([])
    with pytest.raises(GmsError) as exc:
        Gms("http://x", transport=t).upsert("dataset", {"urn": "u"})
    assert "Liste" in str(exc.value)
    assert t.calls == []


def test_upsert_sends_a_list_and_uses_sync():
    t = FakeTransport([(200, [{"urn": "u"}])])
    out = Gms("http://x", transport=t).upsert("dataset", [{"urn": "u"}])
    assert out == [{"urn": "u"}]
    method, url, payload = t.calls[0]
    assert method == "POST"
    assert url.endswith("/openapi/v3/entity/dataset?async=false")
    assert isinstance(payload, list)


def test_upsert_raises_when_nothing_was_written():
    """HTTP 200 mit leerer Liste ist ein Fehlschlag, kein Erfolg."""
    t = FakeTransport([(200, [])])
    with pytest.raises(GmsError):
        Gms("http://x", transport=t).upsert("dataset", [{"urn": "u"}])


def test_delete_aspect_sends_delete_to_the_aspect_url():
    t = FakeTransport([(200, None)])
    Gms("http://x", transport=t).delete_aspect("dataset", "u", "deprecation")
    method, url, payload = t.calls[0]
    assert method == "DELETE"
    assert url == "http://x/openapi/v3/entity/dataset/u/deprecation"
    assert payload is None


def test_delete_aspect_raises_on_non_200():
    t = FakeTransport([(404, "not found")])
    with pytest.raises(GmsError):
        Gms("http://x", transport=t).delete_aspect("dataset", "u", "deprecation")
