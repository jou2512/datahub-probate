"""Der Proxy existiert wegen CORS und weil die Knoepfe Python sind
(docs/entscheidungen/2026-08-07-ui-stack-werkbank.md). Getestet wird die
Wegewahl, nicht der Socket -- bis auf den Sicherheitsblock unten, der
BRAUCHT einen echten Socket, weil Host/Origin/X-Probate HTTP-Header sind,
keine Argumente von route()."""

import socket
import threading
from http.server import ThreadingHTTPServer

import pytest
from ui.serve import ACTIONS, DEMO_PARTNER, PORT_DEFAULT, build_handler, do_action, route


def test_the_port_is_never_one_of_the_taken_ones():
    """8080 ist Joels WhatsApp-Bridge, 8081 gibt es gar nicht,
    18080 traegt showcase-ecommerce."""
    assert PORT_DEFAULT == 8899


def test_mode_endpoint_answers_live_because_the_proxy_only_runs_live():
    assert route("GET", "/api/mode", {}) == ("mode", {})


def test_ledger_endpoint_is_routed():
    assert route("GET", "/api/ledger", {}) == ("ledger", {})


def test_log_endpoint_passes_the_since_cursor_through():
    assert route("GET", "/api/log", {"since": ["12"]}) == ("log", {"since": 12})


def test_every_one_of_the_six_buttons_has_an_action():
    assert set(ACTIONS) == {"seed-query", "add-edge", "remove-edge",
                            "cut-warehouse", "fast-forward", "run-ledger"}


def test_an_unknown_action_is_rejected_instead_of_silently_ignored():
    with pytest.raises(KeyError):
        route("POST", "/api/action/erfunden", {})


def test_a_get_on_an_action_path_is_not_a_write():
    """Schreiben nur per POST -- ein versehentlicher Seitenaufruf darf
    nichts veraendern."""
    with pytest.raises(ValueError):
        route("GET", "/api/action/add-edge", {})


# --- Die sechs Knoepfe schreiben wirklich (Task 19, Brief Step 1) -------

class FakeGms:
    def __init__(self):
        self.deleted, self.upserted, self.sent = [], [], []
        self.base = "http://fake-gms"

    def get_aspect(self, t, u, a):
        # remove-edge braucht eine bestehende upstreamLineage MIT der zu
        # entfernenden Kante, sonst verweigert es jetzt (Opus-Review-
        # Nachtrag, siehe test_remove_edge_refuses_* unten) -- fuer
        # jeden ANDEREN Aspekt bleibt None der ehrliche "existiert nicht".
        if a == "upstreamLineage":
            return {"value": {"upstreams": [
                {"dataset": "urn:focus", "type": "TRANSFORMED",
                 "auditStamp": {"time": 0, "actor": "urn:li:corpuser:__datahub_system"}},
            ]}}
        return None

    def upsert(self, t, records, sync=True):
        assert isinstance(records, list), "Falle 1: upsert will eine LISTE"
        self.upserted.append((t, records))
        return records

    def delete_aspect(self, t, u, a):
        self.deleted.append((t, u, a))

    def _send(self, method, url, payload):
        # cut-warehouse spricht /entities?action=delete direkt an (wie
        # harness/seed_lineage_lab.py::purge_usage_history) -- kein
        # Public-Method-Aequivalent auf Gms, siehe do_action-Kommentar.
        self.sent.append((method, url, payload))
        return 200, {"value": {"timeseriesRows": 3}}

    def graphql(self, q, v=None):
        return {"dataset": {"lineage": {"relationships": []}},
                "searchAcrossEntities": {"total": 0, "searchResults": []}}


def test_cut_warehouse_purges_the_full_usage_timeseries_on_the_downstream_target():
    """DER Demo-Knopf: er nimmt die GESAMTE Datenlage weg (alle
    Zeitfenster, nicht nur das aktuelle), auf dem DOWNSTREAM-Ziel -- dessen
    Abdeckung die Klassifikation traegt, nicht focus (das upstream).

    Abweichung vom Brief-Entwurf (07.08., "aktueller Code gewinnt" bei
    widerlegtem Entwurf -- live gemessen: der Entwurf loeschte
    `gms.delete_aspect("dataset", focus, ...)`, EIN Zeitreihen-Dokument,
    auf dem falschen Dataset -- die GraphQL-Aggregation, die ledger.py
    liest, blieb bei buckets_seen=3 und die Kante blieb 'confirmed'. Siehe
    task-19-report.md fuer den vollen Befund). Danach muessen Kanten
    'unknown' werden, nicht 'dead'."""
    g, seen = FakeGms(), []
    out = do_action("cut-warehouse", g, "urn:focus", lambda t, n=None: seen.append(t))
    assert g.sent, "cut-warehouse muss die zeitreihe purgen, nicht nur eine aspekt-momentaufnahme loeschen"
    method, url, payload = g.sent[0]
    assert method == "POST" and url.endswith("/entities?action=delete")
    assert payload["aspectName"] == "datasetUsageStatistics"
    assert payload["urn"] == DEMO_PARTNER  # das downstream-ziel, nicht "urn:focus"
    assert payload["startTimeMillis"] == 0
    assert out["expect"] == "unknown"


def test_fast_forward_only_moves_the_observation_window_and_writes_nothing():
    """Zeit vorspulen ist eine SICHT, keine Datenaenderung -- alles
    andere waere eine gefaelschte Messung."""
    g = FakeGms()
    out = do_action("fast-forward", g, "urn:focus", lambda t, n=None: None)
    assert g.upserted == [] and g.deleted == []
    assert out["now_ms_offset_days"] > 0


def test_every_action_returns_a_log_line_with_a_number():
    """Uebergabe Abschnitt 10: jede Protokollzeile traegt eine Zahl,
    kein Gefuehl."""
    for name in ("seed-query", "add-edge", "remove-edge", "cut-warehouse",
                 "fast-forward", "run-ledger"):
        seen = []
        do_action(name, FakeGms(), "urn:focus", lambda t, n=None: seen.append((t, n)))
        assert seen and seen[-1][1] is not None


# --- Opus-Review-Nachtrag waehrend Task 19: remove-edge darf keine nie
# gemessene "keine upstreams"-Behauptung schreiben (dieselbe Fehlerklasse
# wie der behobene mark_dead-Fund in probate/correct.py) -------------------

def test_remove_edge_refuses_instead_of_asserting_empty_upstreams_when_no_aspect_exists():
    class NoAspectGms(FakeGms):
        def get_aspect(self, t, u, a):
            return None

    g = NoAspectGms()
    with pytest.raises(ValueError):
        do_action("remove-edge", g, "urn:focus", lambda t, n=None: None)
    assert g.upserted == []


def test_remove_edge_refuses_when_the_edge_is_not_in_the_existing_upstreams():
    class OtherUpstreamGms(FakeGms):
        def get_aspect(self, t, u, a):
            if a == "upstreamLineage":
                return {"value": {"upstreams": [{"dataset": "urn:someone-else"}]}}
            return None

    g = OtherUpstreamGms()
    with pytest.raises(ValueError):
        do_action("remove-edge", g, "urn:focus", lambda t, n=None: None)
    assert g.upserted == []


def test_remove_edge_actually_removes_when_the_precondition_holds():
    """Gegenprobe: existiert die Kante wirklich, schreibt remove-edge
    tatsaechlich (die zwei Verweigerungen oben sind keine Generalsperre)."""
    g = FakeGms()  # get_aspect liefert "urn:focus" als bestehenden upstream
    out = do_action("remove-edge", g, "urn:focus", lambda t, n=None: None)
    assert out["removed"] == 1
    assert g.upserted  # wb.aspect() hat tatsaechlich geschrieben


# --- Security-Checkliste (Opus-Review, 07.08.) --------------------------
# Punkt 13: sechs Pflicht-Regressionstests. Vier davon (Cross-Origin,
# X-Probate, fremder Host, uebergrosser Body) sind HTTP-Header-Fragen und
# brauchen deshalb einen echten Socket -- route() sieht keine Header.

def test_a_urn_containing_a_quote_is_rejected_before_it_reaches_gms():
    """Punkt 3: jeder URN-Parameter wird gegen verbotene Zeichen geprueft,
    BEVOR er FakeGms/echtes GMS erreicht."""
    g = FakeGms()
    poisoned = 'urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab."x,PROD)'
    with pytest.raises(ValueError):
        do_action("add-edge", g, poisoned, lambda t, n=None: None)
    assert g.upserted == [] and g.deleted == []


def _start_test_server(gms_url="http://127.0.0.1:28080", focus="urn:focus"):
    """Ein echter Server auf einem OS-vergebenen Port -- nicht 8899, damit
    parallele Testlaeufe sich nicht in die Quere kommen. gms_url zeigt auf
    28080 (Punkt 7 laesst 8080/18080/3000 gar nicht erst zu), wird aber
    fuer keinen der Sicherheitstests unten tatsaechlich kontaktiert: die
    Ablehnung passiert VOR jedem Gms-Aufruf."""
    log: list = []
    handler_cls = build_handler(gms_url, focus, log)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, log


def _stop_test_server(server):
    server.shutdown()
    server.server_close()


def _raw_http_request(port, method, path, headers=None, body=b""):
    """http.client/urllib setzen den Host-Header selbst und lassen sich
    darum kaum auf einen FREMDEN Host umbiegen -- ein roher Socket ist
    hier die einzige Art, "Host: evil.example" tatsaechlich zu senden."""
    if isinstance(body, str):
        body = body.encode()
    lines = [f"{method} {path} HTTP/1.1"]
    for k, v in (headers or {}).items():
        lines.append(f"{k}: {v}")
    lines.append("Connection: close")
    head = ("\r\n".join(lines) + "\r\n\r\n").encode()
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(head + body)
        s.settimeout(5)
        data = b""
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
    status_line = data.split(b"\r\n", 1)[0].decode(errors="replace")
    status = int(status_line.split(" ", 2)[1])
    return status, data


def test_cross_origin_post_is_rejected_before_dispatch():
    """Der gemessene Befund aus dem Opus-Review: ein Cross-Origin-POST
    erreichte vorher die do_action-Zeile. Host ist hier korrekt, nur der
    Origin-Header zeigt auf ein fremdes Ziel."""
    server, port, log = _start_test_server()
    try:
        status, _ = _raw_http_request(
            port, "POST", "/api/action/fast-forward",
            headers={
                "Host": f"127.0.0.1:{port}",
                "Origin": "http://evil.example",
                "X-Probate": "1",
                "Content-Type": "application/json",
                "Content-Length": "2",
            },
            body=b"{}",
        )
        assert status == 403
        assert log == []  # do_action wurde nie erreicht
    finally:
        _stop_test_server(server)


def test_post_without_x_probate_header_is_rejected():
    server, port, log = _start_test_server()
    try:
        status, _ = _raw_http_request(
            port, "POST", "/api/action/fast-forward",
            headers={
                "Host": f"127.0.0.1:{port}",
                "Content-Type": "application/json",
                "Content-Length": "2",
            },
            body=b"{}",
        )
        assert status == 403
        assert log == []
    finally:
        _stop_test_server(server)


def test_a_foreign_host_header_is_rejected():
    server, port, log = _start_test_server()
    try:
        status, _ = _raw_http_request(
            port, "GET", "/api/mode",
            headers={"Host": "evil.example"},
        )
        assert status == 403
        assert log == []
    finally:
        _stop_test_server(server)


def test_an_oversized_body_is_rejected():
    server, port, log = _start_test_server()
    try:
        big = b"x" * (65 * 1024)
        status, _ = _raw_http_request(
            port, "POST", "/api/action/fast-forward",
            headers={
                "Host": f"127.0.0.1:{port}",
                "X-Probate": "1",
                "Content-Type": "application/json",
                "Content-Length": str(len(big)),
            },
            body=big,
        )
        assert status == 400
        assert log == []
    finally:
        _stop_test_server(server)


def test_a_same_origin_post_with_the_right_headers_actually_dispatches():
    """Gegenprobe zu den vier Ablehnungen oben (verification.md: ein
    Verbot ohne Gegenprobe ist nur eine Vermutung): mit korrektem Host,
    Origin und X-Probate-Header laesst der Server die Aktion durch --
    Punkt 1 darf den echten Browser-Klick nicht mit-abweisen."""
    server, port, log = _start_test_server()
    try:
        status, _ = _raw_http_request(
            port, "POST", "/api/action/fast-forward",
            headers={
                "Host": f"127.0.0.1:{port}",
                "Origin": f"http://127.0.0.1:{port}",
                "X-Probate": "1",
                "Content-Type": "application/json",
                "Content-Length": "2",
            },
            body=b"{}",
        )
        assert status == 200
        assert log  # note() wurde aufgerufen -- do_action lief tatsaechlich
    finally:
        _stop_test_server(server)


def test_the_mode_endpoint_answers_200_over_a_real_socket():
    """Live-Fund beim Bau dieser Aufgabe (curl -i gegen einen echten Task-
    18-Server, 07.08.): _handle() gab bei Erfolg IMMER None zurueck (weil
    _json() nichts zurueckgab), also fiel jede API-Antwort auf
    super().do_GET() durch und wurde von einem zweiten 404 ueberschrieben.
    /api/mode hat nie 200 geliefert. route() (reine Funktion) konnte das
    nicht fangen -- nur ein echter Socket kann es."""
    server, port, _ = _start_test_server()
    try:
        status, _ = _raw_http_request(
            port, "GET", "/api/mode", headers={"Host": f"127.0.0.1:{port}"}
        )
        assert status == 200
    finally:
        _stop_test_server(server)
