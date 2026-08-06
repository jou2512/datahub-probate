import json
import pytest
from probate.gms import Gms, GmsError, _urllib_transport


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


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body
        self.status = 200

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_urllib_transport_sends_bearer_token_when_given(monkeypatch):
    """Live-Fund (Jury-Review 2026-08-06): ohne Token laeuft probate als
    __datahub_system -- funktioniert nur ohne Zugriffskontrolle. Das
    Personal Access Token muss als Authorization-Header ankommen."""
    captured = {}

    def fake_urlopen(req, timeout):
        captured["auth"] = req.get_header("Authorization")
        return _FakeResponse(json.dumps({"ok": True}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    send = _urllib_transport("secret-pat-123")
    send("GET", "http://x/api/graphql", None)
    assert captured["auth"] == "Bearer secret-pat-123"


def test_urllib_transport_sends_no_auth_header_without_a_token(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["auth"] = req.get_header("Authorization")
        return _FakeResponse(json.dumps({"ok": True}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    send = _urllib_transport(None)
    send("GET", "http://x/api/graphql", None)
    assert captured["auth"] is None


def test_gms_reads_token_from_environment_when_not_given_explicitly(monkeypatch):
    monkeypatch.setenv("DATAHUB_TOKEN", "env-token-456")
    g = Gms("http://x")
    assert g.token == "env-token-456"


def test_gms_explicit_token_wins_over_environment(monkeypatch):
    monkeypatch.setenv("DATAHUB_TOKEN", "env-token-456")
    g = Gms("http://x", token="explicit-token")
    assert g.token == "explicit-token"
