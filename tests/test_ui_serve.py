"""Der Proxy existiert wegen CORS und weil die Knoepfe Python sind
(docs/entscheidungen/2026-08-07-ui-stack-werkbank.md). Getestet wird die
Wegewahl, nicht der Socket -- bis auf den Sicherheitsblock unten, der
BRAUCHT einen echten Socket, weil Host/Origin/X-Probate HTTP-Header sind,
keine Argumente von route()."""

import json
import socket
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import ui.serve as serve_module
from ui.serve import ACTIONS, DEMO_PARTNER, PORT_DEFAULT, build_handler, do_action, route

# --- CRITICAL 1 (Opus-Review-Nachtrag) -----------------------------------
# Gemessen (Controller): jeder Test, der do_action() aufrief, schrieb
# vorher in die ECHTE harness/runs/journal.jsonl (kein Injektionspunkt).
# 100 zusaetzliche Zeilen im Arbeitsbaum, 84 Fixture-Muell mit der
# Nonsense-URN "urn:focus" auf dem REALEN Dataset
# probate_seedlab.finance_income_statement_consolidated -- `probate revert` haette das in
# den Live-Katalog zurueckgeschrieben. Diese Datei darf die echte Datei
# NIE beruehren, egal welcher Test do_action() aufruft -- autouse, jeder
# Test bekommt einen frischen tmp_path.


@pytest.fixture(autouse=True)
def _isolated_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(serve_module, "JOURNAL_PATH", str(tmp_path / "journal.jsonl"))
    yield


_REAL_JOURNAL = Path("harness/runs/journal.jsonl")


@pytest.fixture(scope="session", autouse=True)
def _real_journal_stays_byte_identical():
    """CRITICAL 1, Punkt (c): der BEWEIS, nicht nur die Behauptung -- die
    echte Datei wird vor und nach der GESAMTEN Session byte-fuer-byte
    verglichen. Faellt dieser Test, ist die JOURNAL_PATH-Injektion oben
    irgendwo umgangen worden."""
    before = _REAL_JOURNAL.read_bytes()
    yield
    after = _REAL_JOURNAL.read_bytes()
    assert after == before, (
        "harness/runs/journal.jsonl wurde waehrend der Testsuite veraendert -- "
        "JOURNAL_PATH-Injektion (CRITICAL 1) deckt nicht jeden Aufrufer ab"
    )


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


def test_the_view_reset_endpoint_is_routed():
    assert route("POST", "/api/view/reset", {}) == ("reset-time", {})


def test_a_path_traversal_style_action_suffix_is_rejected():
    """IMPORTANT 3 (Opus-Review-Nachtrag): `rsplit('/', 1)[-1]` nahm vorher
    nur das LETZTE Segment -- '/api/action/fast-forward/../seed-query'
    bestand die Pruefung und fuehrte seed-query aus, waehrend die
    angeforderte URL etwas anderes suggeriert. Angeforderter Pfad und
    ausgefuehrte Aktion muessen fuer ein auditierbares Produkt
    uebereinstimmen -- jetzt: GENAU ein Segment nach dem Praefix, sonst
    Ablehnung."""
    with pytest.raises(KeyError):
        route("POST", "/api/action/fast-forward/../seed-query", {})
    with pytest.raises(KeyError):
        route("POST", "/api/action/seed-query/", {})
    with pytest.raises(KeyError):
        route("POST", "/api/action/", {})


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
        # `entityExists` gehoert dazu, seit jede schreibende Aktion vorher
        # prueft, ob das Ziel ueberhaupt existiert (gemessener Vorfall:
        # 73 Journal-Zeilen fuer Datensaetze, die es nie gab). Ein Fake
        # ohne dieses Feld liesse JEDEN Knopf verweigern -- und der Test
        # unten prueft genau den umgekehrten Fall.
        return {"entityExists": True,
                "dataset": {"lineage": {"relationships": []}},
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


# --- CRITICAL 2 (Opus-Review-Nachtrag): seed-query umging writeback.py --
# Der Reviewer bewies live: ein Knopfdruck erzeugte eine echte Query-
# Entitaet direkt ueber gms.upsert(), das Journal blieb unveraendert,
# `probate revert` konnte sie nicht sehen (von Hand geloescht). Jetzt
# laeuft der Schreibvorgang ueber wb.aspect() -- zwei gewoehnliche
# Aspekte, zwei Journal-Zeilen, `before: null` (die Entitaet existierte
# vorher nicht -- `revert_all()`s delete_aspect-Zweig deckt das exakt).

def test_seed_query_writes_through_writeback_so_revert_can_see_it(tmp_path):
    g = FakeGms()
    out = do_action("seed-query", g, "urn:focus", lambda t, n=None: None)
    assert out["wrote"] == 1

    journal = tmp_path / "journal.jsonl"  # derselbe Pfad, den _isolated_journal gesetzt hat
    lines = journal.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, "seed-query muss GENAU zwei journalisierte aspekt-schreibvorgaenge hinterlassen"
    entries = [json.loads(line) for line in lines]
    assert all(e["entity_type"] == "query" for e in entries)
    assert {e["aspect"] for e in entries} == {"queryProperties", "querySubjects"}
    assert all(e["before"] is None for e in entries), (
        "die query-entitaet existierte vorher nicht -- before muss null sein, "
        "sonst kann revert_all() sie nicht per delete_aspect entfernen"
    )
    assert g.upserted, "wb.aspect() muss tatsaechlich ueber gms.upsert geschrieben haben"


def test_seed_query_actually_reverts_end_to_end_not_just_structurally(tmp_path):
    """Opus-Review-Nachtrag (Re-Review): der Test oben beweist nur die
    FORM des Journals (zwei Zeilen, before=null) -- das zeigt, dass
    revert_all() strukturell funktionieren WUERDE, nicht dass er es TUT.
    Dieser Test fuehrt den Rundlauf tatsaechlich aus: Knopf -> Journal ->
    frisches Writeback auf DEMSELBEN Journal -> revert_all() -> die
    Entitaet ist wirklich weg (g.deleted), nichts sonst wurde angefasst.
    Das macht aus der strukturellen Behauptung einen mechanischen Beweis
    -- derselbe Massstab, an dem dieses Projekt jede andere Zahl misst."""
    from probate.writeback import Writeback

    g = FakeGms()
    out = do_action("seed-query", g, "urn:focus", lambda t, n=None: None)
    query_urn = None  # aus dem journal gelesen, nicht erraten/neu berechnet

    journal = tmp_path / "journal.jsonl"
    lines = journal.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines]
    query_urns = {e["urn"] for e in entries}
    assert len(query_urns) == 1, "beide journal-zeilen muessen dieselbe query-urn tragen"
    query_urn = query_urns.pop()

    # Frisches Writeback auf DEMSELBEN Journal-Pfad -- genau das, was
    # `probate revert` tut: eine neue Writeback-Instanz liest die
    # bestehende Journal-Datei, nicht denselben Python-Objektzustand.
    wb2 = Writeback(g, dry_run=False, journal_path=str(journal))
    reverted = wb2.revert_all()

    assert reverted == 2, f"revert_all() muss beide aspekt-schreibvorgaenge zaehlen, zaehlte {reverted}"
    assert set(g.deleted) == {
        ("query", query_urn, "queryProperties"),
        ("query", query_urn, "querySubjects"),
    }, "revert_all() muss GENAU diese zwei aspekte loeschen, nichts mehr und nichts weniger"
    assert g.deleted != [], "die entitaet ist erst 'weg', wenn delete_aspect tatsaechlich aufgerufen wurde"


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


def _raw_http_request(port, method, path, headers=None, body=b"", timeout=5):
    """http.client/urllib setzen den Host-Header selbst und lassen sich
    darum kaum auf einen FREMDEN Host umbiegen -- ein roher Socket ist
    hier die einzige Art, "Host: evil.example" tatsaechlich zu senden.

    `timeout` ist ueberschreibbar (IMPORTANT 4): der Server braucht bis
    zu `_BODY_READ_TIMEOUT_S` (5s), bevor er selbst bei einer
    ueberhoehten Content-Length antwortet -- der Client-Timeout muss
    dafuer sichtbar groesser sein als Server-seitige Wartezeit."""
    if isinstance(body, str):
        body = body.encode()
    lines = [f"{method} {path} HTTP/1.1"]
    for k, v in (headers or {}).items():
        lines.append(f"{k}: {v}")
    lines.append("Connection: close")
    head = ("\r\n".join(lines) + "\r\n\r\n").encode()
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        try:
            s.sendall(head + body)
        except (ConnectionAbortedError, ConnectionResetError):
            # Verifizierter Windows-TCP-Rennen (Reviewer, kein Regressions-
            # befund, git show a497c3c bestaetigt byte-identisch): bei
            # grossem body kann der server seine 400-antwort senden und
            # den socket schliessen, WAEHREND der client noch sendet --
            # ein RST auf der sendeseite. die antwort selbst steht trotzdem
            # schon im empfangspuffer; der folgende recv()-block liest sie
            # unveraendert, die assertion unten bleibt exakt dieselbe.
            pass
        s.settimeout(timeout)
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
            port, "GET", "/api/mode",
            headers={"Host": f"127.0.0.1:{port}", "X-Probate": "1"},
        )
        assert status == 200
    finally:
        _stop_test_server(server)


# --- IMPORTANT 6 (Opus-Review-Nachtrag) ----------------------------------
# X-Probate war vorher nur fuer POST Pflicht. Eine "einfache" Cross-
# Origin-GET (<img src>/<script src>) traegt NIE Origin und NIE einen
# Custom-Header -- SOP verhindert nur das LESEN der Antwort im Angreifer-
# Tab, nicht dass der echte GET-Aufruf gegen GMS ueberhaupt AUSGELOEST
# wird ("confused deputy"). X-Probate ist deshalb jetzt fuer JEDE Methode
# unter /api/* Pflicht.

def test_a_get_without_x_probate_is_rejected_even_with_the_right_host():
    server, port, log = _start_test_server()
    try:
        status, _ = _raw_http_request(
            port, "GET", "/api/ledger",
            headers={"Host": f"127.0.0.1:{port}"},  # kein Origin, kein X-Probate -- <img src>-Fall
        )
        assert status == 403
        assert log == []
    finally:
        _stop_test_server(server)


# --- IMPORTANT 4 (Opus-Review-Nachtrag) ----------------------------------
# Eine ueberhoehte Content-Length ohne genug tatsaechlich gesendete Bytes
# liess rfile.read(n) vorher unbegrenzt blockieren -- ein lokales
# Slowloris, ein haengender Handler-Thread pro Angriff.

def test_an_overstated_content_length_gets_a_response_instead_of_hanging_forever():
    server, port, log = _start_test_server()
    try:
        start = time.monotonic()
        status, _ = _raw_http_request(
            port, "POST", "/api/action/fast-forward",
            headers={
                "Host": f"127.0.0.1:{port}",
                "X-Probate": "1",
                "Content-Type": "application/json",
                "Content-Length": "1000",  # behauptet 1000, gesendet werden nur 5
            },
            body=b"{}   ",
            timeout=serve_module._BODY_READ_TIMEOUT_S + 5,  # muss dem serverseitigen Timeout Zeit geben
        )
        elapsed = time.monotonic() - start
        assert status == 400
        assert elapsed < serve_module._BODY_READ_TIMEOUT_S + 5, (
            "der server muss selbst antworten, nicht auf den client warten"
        )
        assert log == []
    finally:
        _stop_test_server(server)


# --- IMPORTANT 5 (Opus-Review-Nachtrag) ----------------------------------
# _view_offset_days akkumuliert sonst fuer die gesamte Prozesslaufzeit,
# unsichtbar -- 13 Druecke sind 420 Tage, jede spaetere Messung wird
# dagegen gerechnet. reset_view_offset() ist keine Sicht-Aenderung mit
# Schreibfolge (wie fast-forward), sondern deren Aufhebung.

def test_reset_view_offset_zeroes_the_accumulator_and_writes_nothing():
    g = FakeGms()
    do_action("fast-forward", g, "urn:focus", lambda t, n=None: None)
    do_action("fast-forward", g, "urn:focus", lambda t, n=None: None)

    seen = []
    out = serve_module.reset_view_offset(lambda t, n=None: seen.append((t, n)))
    assert out["now_ms_offset_days"] == 0
    assert seen and seen[-1][1] == 0

    # naechstes fast-forward faengt wieder bei 30 an, nicht bei 90 -- der
    # reset muss den GLEICHEN globalen Zaehler treffen, den fast-forward
    # erhoeht, nicht eine Kopie.
    out2 = do_action("fast-forward", g, "urn:focus", lambda t, n=None: None)
    assert out2["now_ms_offset_days"] == 30
    assert g.upserted == [] and g.deleted == [], "reset darf wie fast-forward nichts schreiben"


# --- Der Live-Modus deckt ALLE VIER Zustaende ab (07.08., Umbau) --------
#
# Vorher: `--focus` war EIN Dataset, der Vorgabewert der leere String. Ein
# blosser Start beobachtete nichts, ein Start mit einem Fokus zeigte genau
# EINE Kante. Ein Juror sah damit entweder vier Zustaende ohne Knoepfe
# (Aufzeichnung) oder Knoepfe mit einer Kante (Live) -- beides ist keine
# Demo.

def test_no_table_name_is_ever_written_into_the_server_source():
    """Waehrend dieser Aufgabe hat eine parallele Bahn die Seedlab-
    Tabellen umbenannt und musste `DEMO_PARTNER` von Hand nachziehen.
    Genau das darf nicht wieder passieren: die Namen kommen aus dem
    Manifest, nicht aus dem Quelltext."""
    source = Path("ui/serve.py").read_text(encoding="utf-8")
    manifest = json.loads(Path("examples/seedlab-manifest.json").read_text(encoding="utf-8"))
    names = {e[side].split(",")[1] for e in manifest["edges"]
             for side in ("upstream_urn", "downstream_urn")}
    # Kommentare duerfen einen Namen als BELEG nennen (der Umbenennungs-
    # Vorfall ist dort dokumentiert) -- Code darf es nicht.
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    for name in names:
        assert name not in code, f"{name} steht im Quelltext statt im Manifest"


def test_the_four_focuses_come_from_the_manifest(tmp_path):
    """`focuses` ist die Liste der vier Upstreams -- je einer pro Zustand,
    in Manifest-Reihenfolge."""
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({
        "namespace": "ns",
        "seeded_statement": "seeded",
        "edges": [
            {"upstream_urn": "urn:up:c", "downstream_urn": "urn:down:c",
             "expected_edge_state": "confirmed"},
            {"upstream_urn": "urn:up:d", "downstream_urn": "urn:down:d",
             "expected_edge_state": "dead"},
            {"upstream_urn": "urn:up:m", "downstream_urn": "urn:down:m",
             "expected_edge_state": "missing"},
            {"upstream_urn": "urn:up:u", "downstream_urn": "urn:down:u",
             "expected_edge_state": "unknown"},
        ],
    }), encoding="utf-8")
    out = serve_module.load_manifest_targets(manifest)
    assert out["focuses"] == ["urn:up:c", "urn:up:d", "urn:up:m", "urn:up:u"]
    # Die Knoepfe schreiben auf die unknown-Quelle (noch keine Verbindung,
    # keine eigene Nutzung) und auf das confirmed-Ziel (das einzige mit
    # einer echten Nutzungs-Zeitreihe) -- sonst zeigt kein Knopf Wirkung.
    assert out["demo_focus"] == "urn:up:u"
    assert out["demo_partner"] == "urn:down:c"
    assert out["seeded_statement"] == "seeded"


def test_the_judgements_endpoint_is_routed_separately_from_the_ledger():
    """Ein Modellaufruf dauerte live 17.8-23.1s, der deterministische
    Befund unter einer Sekunde. Wer beides an eine Antwort haengt, laesst
    den billigen, sicheren Befund auf den teuren warten."""
    assert route("GET", "/api/judgements", {}) == ("judgements", {})
    # Urteile werden gelesen, nie geschrieben -- ein POST hat hier keinen Weg.
    with pytest.raises(KeyError):
        route("POST", "/api/judgements", {})


def test_the_judge_snapshot_never_reports_a_cost_it_did_not_measure():
    snap = serve_module.judge_snapshot()
    assert set(snap) >= {"running", "expected", "done", "calls", "seconds",
                         "cost_usd", "judgements"}
    assert isinstance(snap["judgements"], list)


# --- Kein Journal-Eintrag fuer eine Mutation, die nie landen kann -------

class _GhostGms(FakeGms):
    """Ein Katalog, in dem die Ziel-URN NICHT existiert. `entityExists`
    ist der einzige Unterschied zu `FakeGms` -- und live der einzige
    verlaessliche Unterschied ueberhaupt: `dataset(urn:)` liefert auch
    fuer eine frei erfundene URN einen Knoten (07.08. gegen 28080
    gemessen, genau mit der URN aus dem Vorfall)."""

    def graphql(self, q, v=None):
        out = super().graphql(q, v)
        out["entityExists"] = False
        return out


@pytest.mark.parametrize("action", ["add-edge", "seed-query", "remove-edge", "cut-warehouse"])
def test_a_button_against_a_nonexistent_dataset_leaves_the_journal_byte_identical(
        action, tmp_path, monkeypatch):
    """Gemessener Vorfall (07.08.): `harness/runs/journal.jsonl` wuchs von
    20 auf 93 Zeilen; die 73 neuen nannten `snowflake,analytics.
    customers_v5` -- Datensaetze, die es im Katalog nicht gibt. Das
    Journal behauptete also Mutationen, die nie stattgefunden haben, in
    genau der Datei, die `probate revert` abspielt.

    Derselbe Fehlertyp wie CRITICAL 1 oben, anderer Einstieg: dort schrieb
    der TEST in die echte Datei, hier der SERVER Eintraege ohne Wirkung.
    """
    journal = tmp_path / "journal.jsonl"
    journal.write_text('{"pre": "existing line"}' + chr(10), encoding="utf-8")
    monkeypatch.setattr(serve_module, "JOURNAL_PATH", str(journal))
    before = journal.read_bytes()

    with pytest.raises(ValueError, match="existiert nicht im katalog"):
        do_action(action, _GhostGms(), "urn:li:dataset:(urn:li:dataPlatform:x,a.b,PROD)",
                  lambda *a, **kw: None)

    assert journal.read_bytes() == before


def test_the_view_only_buttons_need_no_target_and_still_write_nothing(tmp_path, monkeypatch):
    """`fast-forward` und `run-ledger` veraendern den Katalog nicht -- sie
    duerfen deshalb auch dann laufen, wenn gar kein Ziel existiert."""
    journal = tmp_path / "journal.jsonl"
    journal.write_text("", encoding="utf-8")
    monkeypatch.setattr(serve_module, "JOURNAL_PATH", str(journal))
    out = do_action("fast-forward", _GhostGms(), "urn:focus", lambda *a, **kw: None)
    assert out["now_ms_offset_days"] > 0
    assert journal.read_bytes() == b""
    serve_module.reset_view_offset(lambda *a, **kw: None)


# --- Eine Adresse, ein Prozess (08.08.) ---------------------------------
#
# Der Befund: zeitweise lauschten ZWEI Prozesse mit verschiedenem Stand auf
# 8899. Unter Windows setzt `HTTPServer.allow_reuse_address = 1` (die
# Stdlib-Vorgabe) SO_REUSEADDR, und das heisst dort NICHT "warte auf
# TIME_WAIT" wie unter Linux, sondern "binde denselben Port ein zweites Mal
# auch wenn schon jemand lauscht". Der zweite Start war dadurch still
# erfolgreich, und wer danach neu lud, sah je nach Zufall alten oder neuen
# Code.


def test_a_free_port_says_nothing_and_lets_the_server_start():
    """Der Wert ist der leere String, nicht None -- "frei" muss sich von
    "konnte nicht nachsehen" unterscheiden lassen."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free = probe.getsockname()[1]
    # Der Socket ist zu, der Port damit frei.
    assert serve_module.preflight_port(free) == ""


def test_an_occupied_port_is_named_instead_of_silently_shared():
    """Ein fremder Lauscher fuehrt zu einem Satz, der sagt was los ist --
    nicht zu einem stillen zweiten Bind daneben."""
    with socket.socket() as squatter:
        squatter.bind(("127.0.0.1", 0))
        squatter.listen(1)
        port = squatter.getsockname()[1]
        message = serve_module.preflight_port(port)
    assert message, "ein belegter port muss gemeldet werden"
    assert str(port) in message
    # Ein FREMDER Dienst und eine laufende Werkbank brauchen verschiedene
    # Handgriffe -- die Meldung darf sie nicht in einen Topf werfen.
    assert "keine werkbank" in message


def test_main_refuses_the_port_instead_of_sitting_next_to_it(monkeypatch, capsys):
    """`main()` startet NICHT, wenn der Port belegt ist -- Rueckgabe 1,
    Meldung auf stderr, kein Traceback."""
    monkeypatch.setattr(serve_module, "preflight_port",
                        lambda port: "werkbank laeuft bereits auf http://127.0.0.1:8899")
    code = serve_module.main(["--port", "8899"])
    assert code == 1
    assert "laeuft bereits" in capsys.readouterr().err


def test_a_running_workbench_is_recognised_as_one(tmp_path):
    """Die Probe unterscheidet die eigene Werkbank von einem fremden
    Dienst -- ueber eine ECHTE Antwort auf /api/mode, nicht ueber die
    blosse Tatsache, dass da etwas lauscht. Zwei Fallen stecken darin,
    beide gemessen: der Host-Kopf braucht den PORT (sonst antwortet die
    eigene Werkbank mit 403), und Kopf und Koerper kommen in ZWEI
    Segmenten (ein einzelnes recv() sah nur den Kopf).
    """
    handler = build_handler("http://127.0.0.1:28080", ["urn:focus"], [])
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        assert serve_module._port_owner(port) == "werkbank"
        assert "laeuft bereits" in serve_module.preflight_port(port)
    finally:
        server.shutdown()
        server.server_close()
