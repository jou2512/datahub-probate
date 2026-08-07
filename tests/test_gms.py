import http.server
import json
import threading

import pytest
from probate.gms import _OPENER, Gms, GmsError, _urllib_transport


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
    t = FakeTransport([(200, [{"urn": "urn:li:dataset:u"}])])
    out = Gms("http://x", transport=t).upsert("dataset", [{"urn": "urn:li:dataset:u"}])
    assert out == [{"urn": "urn:li:dataset:u"}]
    method, url, payload = t.calls[0]
    assert method == "POST"
    assert url.endswith("/openapi/v3/entity/dataset?async=false")
    assert isinstance(payload, list)


def test_upsert_raises_when_nothing_was_written():
    """HTTP 200 mit leerer Liste ist ein Fehlschlag, kein Erfolg."""
    t = FakeTransport([(200, [])])
    with pytest.raises(GmsError):
        Gms("http://x", transport=t).upsert("dataset", [{"urn": "urn:li:dataset:u"}])


def test_delete_aspect_sends_delete_to_the_aspect_url():
    t = FakeTransport([(200, None)])
    Gms("http://x", transport=t).delete_aspect("dataset", "urn:li:dataset:u", "deprecation")
    method, url, payload = t.calls[0]
    assert method == "DELETE"
    assert url == "http://x/openapi/v3/entity/dataset/urn:li:dataset:u/deprecation"
    assert payload is None


def test_delete_aspect_raises_on_non_200():
    t = FakeTransport([(404, "not found")])
    with pytest.raises(GmsError):
        Gms("http://x", transport=t).delete_aspect("dataset", "urn:li:dataset:u", "deprecation")


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
    Personal Access Token muss als Authorization-Header ankommen.

    Patcht _OPENER.open() statt urllib.request.urlopen() (Review-Runde 2,
    2026-08-07): send() ruft seit dem Wegfall von install_opener() den
    module-level Opener explizit auf, nicht mehr die globale Funktion."""
    captured = {}

    def fake_open(req, timeout):
        captured["auth"] = req.get_header("Authorization")
        return _FakeResponse(json.dumps({"ok": True}).encode())

    monkeypatch.setattr(_OPENER, "open", fake_open)
    send = _urllib_transport("secret-pat-123")
    send("GET", "http://x/api/graphql", None)
    assert captured["auth"] == "Bearer secret-pat-123"


def test_urllib_transport_sends_no_auth_header_without_a_token(monkeypatch):
    captured = {}

    def fake_open(req, timeout):
        captured["auth"] = req.get_header("Authorization")
        return _FakeResponse(json.dumps({"ok": True}).encode())

    monkeypatch.setattr(_OPENER, "open", fake_open)
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


# --- Finding I1: default base_url ---------------------------------------


def test_default_base_url_is_28080_not_the_forbidden_18080():
    """18080 = showcase-ecommerce, die fremde Messdaten-Instanz von
    datahub-attest -- dort schreiben entwertet zwei Einreichungen."""
    g = Gms(transport=lambda m, u, p: (200, {}))
    assert g.base == "http://localhost:28080"


# --- Finding C4: URN-Validierung vor Pfad-Interpolation ------------------


@pytest.mark.parametrize(
    "bad_urn",
    [
        'urn:li:dataset:(urn:li:dataPlatform:x,"injected",PROD)',
        "urn:li:dataset:(urn:li:dataPlatform:x,../../etc/passwd,PROD)",
        "urn:li:dataset:with space",
        "urn:li:dataset:with?query=1",
        "urn:li:dataset:with#fragment",
        "urn:li:dataset:with{brace}",
    ],
)
def test_get_aspect_rejects_dangerous_urns_before_any_transport_call(bad_urn):
    t = FakeTransport([])
    with pytest.raises(GmsError):
        Gms("http://x", transport=t).get_aspect("dataset", bad_urn, "datasetProperties")
    assert t.calls == []


def test_delete_aspect_rejects_dangerous_urns_before_any_transport_call():
    t = FakeTransport([])
    with pytest.raises(GmsError):
        Gms("http://x", transport=t).delete_aspect("dataset", "urn:li:dataset:a/../../b", "deprecation")
    assert t.calls == []


def test_upsert_rejects_a_record_with_a_dangerous_urn_before_any_transport_call():
    t = FakeTransport([])
    with pytest.raises(GmsError):
        Gms("http://x", transport=t).upsert(
            "dataset", [{"urn": 'urn:li:dataset:"quoted"'}]
        )
    assert t.calls == []


LEGIT_NESTED_URN = "urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.a,PROD)"


def test_get_aspect_accepts_a_legit_nested_urn_with_parens_commas_colons_slash():
    t = FakeTransport([(200, {"value": {}})])
    body = Gms("http://x", transport=t).get_aspect("dataset", LEGIT_NESTED_URN, "datasetProperties")
    assert body == {"value": {}}
    method, url, payload = t.calls[0]
    assert url == f"http://x/openapi/v3/entity/dataset/{LEGIT_NESTED_URN}/datasetproperties"


def test_upsert_accepts_a_record_with_a_legit_nested_urn():
    t = FakeTransport([(200, [{"urn": LEGIT_NESTED_URN}])])
    out = Gms("http://x", transport=t).upsert("dataset", [{"urn": LEGIT_NESTED_URN}])
    assert out == [{"urn": LEGIT_NESTED_URN}]


# --- Finding C4, Review-Runde 2: Allowlist statt Denylist -----------------
#
# Miss aus Runde 1: eine reine Denylist ("verboten: " \ Leerraum {} ? # ..")
# liess Prozent-Encoding durch, weil "%2e%2e" keines der verbotenen Zeichen
# enthaelt -- urllib dekodiert %2e erst beim eigentlichen Request, nicht
# beim String-Vergleich hier. Diese Tests pinnen genau die live gemeldeten
# Bypaesse plus den NUL-Byte-Fall, den die neue Allowlist automatisch
# mitschliesst.


@pytest.mark.parametrize(
    "bad_urn",
    [
        "urn:li:dataset:%2e%2e%2fadmin%2fsecret",
        "urn:li:dataset:%2e%2e/%2e%2e/etc/passwd",
        "urn:li:dataset:\x00nul-byte",
        "urn:li:dataset:with%20percent",
    ],
)
def test_get_aspect_rejects_percent_encoded_and_nul_urns_before_any_transport_call(bad_urn):
    """Live widerlegter Fund (Review-Runde 1): validate() mit der alten
    Denylist akzeptierte 'urn:li:dataset:%2e%2e%2fadmin%2fsecret' und
    'urn:li:dataset:%2e%2e/%2e%2e/etc/passwd'. Die Allowlist verbietet "%"
    kategorisch (kein einziges "%" in irgendeiner URN im Repo, siehe
    URN_RE-Kommentar) -- und schliesst damit auch NUL-Bytes automatisch
    mit, ohne einen eigenen Sonderfall dafuer zu brauchen."""
    t = FakeTransport([])
    with pytest.raises(GmsError):
        Gms("http://x", transport=t).get_aspect("dataset", bad_urn, "datasetProperties")
    assert t.calls == []


def test_validate_urn_rejects_a_non_string_urn_with_gmserror_not_typeerror():
    """MINOR (Review-Runde 2): record.get('urn') kann in einem malformten
    Record alles sein. Ohne isinstance-Guard wirft URN_RE.match() ein
    TypeError statt eines GmsError -- der 'loud, not crash'-Vertrag gilt
    auch hier."""
    from probate.gms import _validate_urn

    with pytest.raises(GmsError):
        _validate_urn(12345)
    with pytest.raises(GmsError):
        _validate_urn(None)
    with pytest.raises(GmsError):
        _validate_urn(["urn:li:dataset:x"])


def test_upsert_rejects_a_record_with_a_non_string_urn_before_any_transport_call():
    t = FakeTransport([])
    with pytest.raises(GmsError):
        Gms("http://x", transport=t).upsert("dataset", [{"urn": 42}])
    assert t.calls == []


# Repo-weiter Grep (2026-08-07): `grep -rohE "urn:li:[A-Za-z]+:..." probate/
# harness/ examples/ probate_action/ ui/` fand keine URN-Literale mit "/"
# im Identifier-Teil (nur in Kommentaren/Docstrings ueber Plattform-
# Datensatznamen erwaehnt) -- "/" bleibt trotzdem erlaubt, weil die
# Aufgabenstellung fuer Finding C4 das ausdruecklich fuer manche
# Plattform-Datensatznamen verlangt; es gibt im aktuellen Repo nur keinen
# Beleg dafuer, der als zweites Beispiel dienen koennte.
LEGIT_SEEDLAB_URNS = [
    "urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.gl_journal_entries_daily,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customer_ltv_report_v3,PROD)",
    "urn:li:query:probate_load-s-000000",
    "urn:li:versionSet:(probate-probe,dataset)",
]


@pytest.mark.parametrize("legit_urn", LEGIT_SEEDLAB_URNS)
def test_get_aspect_accepts_every_legit_urn_shape_found_in_the_repo(legit_urn):
    t = FakeTransport([(200, {"value": {}})])
    body = Gms("http://x", transport=t).get_aspect("dataset", legit_urn, "datasetProperties")
    assert body == {"value": {}}


# --- Finding C3: kein Redirect folgen -------------------------------------


class _RedirectAndCaptureHandler(http.server.BaseHTTPRequestHandler):
    """/redirect antwortet 302 auf /steal (anderer Port = anderer Host aus
    urllib-Sicht). /steal merkt sich, ob es je erreicht wurde und mit
    welchem Authorization-Header."""

    captured = {"hit": False, "auth": None}
    attacker_port = None

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.attacker_port}/steal")
            self.end_headers()
        elif self.path == "/steal":
            _RedirectAndCaptureHandler.captured["hit"] = True
            _RedirectAndCaptureHandler.captured["auth"] = self.headers.get("Authorization")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")
        else:
            self.send_response(404)
            self.end_headers()


def test_urllib_transport_does_not_follow_a_cross_host_redirect():
    """Miss C3 live: ohne den Fix laeuft dieser Test rot, weil urlopen()
    dem 302 folgt und den Bearer-Token an /steal weiterreicht (Handler auf
    einem zweiten Port = anderer Host aus urllib-Sicht)."""
    _RedirectAndCaptureHandler.captured = {"hit": False, "auth": None}
    redirect_srv = http.server.HTTPServer(("127.0.0.1", 0), _RedirectAndCaptureHandler)
    attacker_srv = http.server.HTTPServer(("127.0.0.1", 0), _RedirectAndCaptureHandler)
    _RedirectAndCaptureHandler.attacker_port = attacker_srv.server_port
    threading.Thread(target=redirect_srv.serve_forever, daemon=True).start()
    threading.Thread(target=attacker_srv.serve_forever, daemon=True).start()
    try:
        send = _urllib_transport("secret-pat-should-never-leave-this-host")
        status, _body = send("GET", f"http://127.0.0.1:{redirect_srv.server_port}/redirect", None)
        assert status == 302
        assert _RedirectAndCaptureHandler.captured["hit"] is False
        assert _RedirectAndCaptureHandler.captured["auth"] is None
    finally:
        redirect_srv.shutdown()
        attacker_srv.shutdown()


def test_gms_get_aspect_turns_an_unfollowed_redirect_into_a_loud_gmserror():
    """Der 302, den _urllib_transport jetzt als Status statt als Folge-
    Request zurueckgibt, muss in der bestehenden non-200-Behandlung
    landen -- lauter GmsError, kein stiller None-Rueckgabewert."""
    t = FakeTransport([(302, None)])
    with pytest.raises(GmsError):
        Gms("http://x", transport=t).get_aspect("dataset", LEGIT_NESTED_URN, "datasetProperties")
