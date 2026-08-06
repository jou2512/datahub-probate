"""Testet harness/loadtest.py -- das Messgeruest, nicht den Lasttest selbst.

Handgeschriebene Fakes (kein Mock-Rahmenwerk, wie tests/test_writeback.py und
tests/test_loadgen.py). `detail_pass` importiert `fetch_cooccurrence` lazy aus
`probate.ledger` (noch nicht vorhanden -- Lane A ist daran, siehe
progress.md "Task 6" -- deshalb wird hier NICHT gegen die echte Funktion
getestet, sondern `probate.ledger.fetch_cooccurrence` per `monkeypatch`
gesetzt. Das ist ein Attribut-Patch zur Testzeit, keine Aenderung an
probate/ledger.py selbst -- die Datei bleibt unberuehrt (global-constraints.md:
Lane-Grenze).

Warum `detail_pass` trotz eines fehlschlagenden Aufrufs weiterzaehlt statt
abzubrechen: bei einer Stichprobe von 41 Kanten waere ein einzelner Fehler
sonst der Grund, warum die anderen 40 nie gemessen werden -- eine
verschwiegene Abwesenheit von Daten, kein Messergebnis. Deshalb sammelt
`detail_pass` selbst den ersten Bruchpunkt samt Fehlertext, statt ihn nach
oben durchzureichen.
"""

import json

import probate.ledger as ledger_module
from harness.loadgen import dataset_urn, plan
from harness.loadtest import coarse_pass, detail_pass, measure, run_smoke, run_stage


# --- measure() -- aus dem Brief, wortgetreu -----------------------------

def test_measure_reports_seconds_and_peak_memory_for_a_successful_call():
    out, m = measure(lambda: sum(range(10_000)))
    assert out == sum(range(10_000))
    assert m["seconds"] >= 0
    assert m["peak_memory_mb"] >= 0
    assert m["broke"] is False
    assert m["error"] == ""


def test_a_crash_is_recorded_with_its_error_text_instead_of_being_swallowed():
    """Spec: 'bricht etwas, und wo genau mit Fehlertext'. Ein
    verschluckter Fehler waere hier das Gegenteil eines Messergebnisses."""
    def boom():
        raise RuntimeError("payload too large: 137421 chars")

    out, m = measure(boom)
    assert out is None
    assert m["broke"] is True
    assert "137421" in m["error"]
    assert m["seconds"] >= 0


def test_measurements_are_flat_scalars_so_audit_claims_can_check_them():
    _, m = measure(lambda: 1)
    assert all(isinstance(v, (int, float, bool, str)) for v in m.values())


# --- coarse_pass() -- eine Zahl pro Tabelle -----------------------------

class FakeGmsCoarse:
    """graphql() antwortet deterministisch je URN -- 'quiet' simuliert die
    Tabellen ohne Abfrageaktivitaet, die coarse_pass als auffaellig markieren
    soll (Kandidaten fuer detail_pass)."""

    def __init__(self, quiet=(), missing=()):
        self.quiet = set(quiet)
        self.missing = set(missing)
        self.calls = []

    def graphql(self, query, variables=None):
        urn = variables["urn"]
        self.calls.append(urn)
        if urn in self.missing:
            return {"dataset": None}
        count = 0 if urn in self.quiet else 12
        return {"dataset": {"statsSummary": {
            "queryCountLast30Days": count, "uniqueUserCountLast30Days": 3}}}


def test_coarse_pass_makes_exactly_one_call_per_dataset_and_flags_zero_activity():
    p = plan("s")
    quiet = {dataset_urn("s", 0), dataset_urn("s", 7)}
    g = FakeGmsCoarse(quiet=quiet)

    out = coarse_pass(g, "s")

    assert out["coarse_api_calls"] == len(p["datasets"]) == 50
    assert len(g.calls) == 50
    assert out["coarse_suspicious"] == 2
    assert set(out["_suspicious"]) == quiet


def test_coarse_pass_treats_a_missing_dataset_summary_as_suspicious_not_a_crash():
    """Falle: eine Tabelle, die statsSummary noch nicht kennt (None statt
    Dict), darf coarse_pass nicht mit einem AttributeError abbrechen."""
    g = FakeGmsCoarse(missing={dataset_urn("s", n) for n in range(50)})

    out = coarse_pass(g, "s")

    assert out["coarse_suspicious"] == out["coarse_api_calls"] == 50


def test_coarse_pass_reports_response_chars_deterministically():
    g = FakeGmsCoarse()
    out = coarse_pass(g, "s")
    one_payload = str({"dataset": {"statsSummary": {
        "queryCountLast30Days": 12, "uniqueUserCountLast30Days": 3}}})
    assert out["coarse_response_chars"] == out["coarse_api_calls"] * len(one_payload)


# --- detail_pass() -- nur die auffaelligen Kanten -----------------------

def test_detail_pass_measures_seconds_per_edge_and_averages_them(monkeypatch):
    monkeypatch.setattr(ledger_module, "fetch_cooccurrence",
                         lambda gms, urn: {"other": ["urn:li:query:q1"]}, raising=False)

    out = detail_pass(object(), ["a", "b", "c"])

    assert out["detail_edges"] == 3
    assert out["detail_seconds_total"] >= 0
    assert out["detail_seconds_per_edge"] == round(out["detail_seconds_total"] / 3, 4)
    assert out["detail_broke"] is False
    assert out["detail_error_count"] == 0
    assert out["detail_break_urn"] == ""
    assert out["detail_break_error"] == ""


def test_detail_pass_with_no_edges_returns_zero_without_dividing_by_zero():
    out = detail_pass(object(), [])
    assert out == {
        "detail_edges": 0, "detail_seconds_total": 0.0, "detail_seconds_per_edge": 0.0,
        "detail_broke": False, "detail_break_urn": "", "detail_break_error": "",
        "detail_error_count": 0,
    }


def test_detail_pass_keeps_measuring_after_a_broken_edge_and_names_the_first_break(monkeypatch):
    """Der Punkt dieses Tests: EIN kaputter fetch_cooccurrence-Aufruf darf
    die Messung der uebrigen Kanten nicht verhindern -- sonst verschwindet
    genau die Information, die diese Aufgabe liefern soll."""
    def fake(gms, urn):
        if urn == "bad":
            raise RuntimeError("payload too large: 137421 chars")
        return {}

    monkeypatch.setattr(ledger_module, "fetch_cooccurrence", fake, raising=False)

    out = detail_pass(object(), ["good1", "bad", "good2"])

    assert out["detail_edges"] == 3
    assert out["detail_broke"] is True
    assert out["detail_break_urn"] == "bad"
    assert "137421" in out["detail_break_error"]
    assert out["detail_error_count"] == 1


def test_detail_pass_keeps_the_first_break_point_when_several_edges_fail(monkeypatch):
    def fake(gms, urn):
        raise RuntimeError(f"boom at {urn}")

    monkeypatch.setattr(ledger_module, "fetch_cooccurrence", fake, raising=False)

    out = detail_pass(object(), ["one", "two", "three"])

    assert out["detail_edges"] == 3
    assert out["detail_error_count"] == 3
    assert out["detail_break_urn"] == "one"
    assert "boom at one" in out["detail_break_error"]


def test_detail_stage_peak_memory_reflects_real_allocation_not_a_nested_reset(monkeypatch):
    """Regressionstest fuer Review-Runde 1 (CRITICAL): `run_stage` misst den
    Detail-Durchgang mit EINER aeusseren measure()/tracemalloc-Session um
    detail_pass(). Rief detail_pass() intern selbst measure() PRO KANTE auf,
    stoppte das innere tracemalloc.stop() die globale Tracing-Session vorzeitig
    -- die aeussere Messung sah danach fast immer ~0 MB, egal wie viel die
    Kante tatsaechlich alloziert hatte. `tracemalloc` ist global und nicht
    reentrant; verschachtelte measure()-Aufrufe ueber dieselbe Grenze sind
    deshalb verboten. Der Test allokiert bewusst eine Million Ints in der
    (gefakten) fetch_cooccurrence, um eine Messung zu erzwingen, die bei einem
    Nesting-Bug garantiert bei ~0 landet."""
    def allocates_a_million_ints(gms, urn):
        return [i for i in range(1_000_000)]

    monkeypatch.setattr(ledger_module, "fetch_cooccurrence", allocates_a_million_ints, raising=False)

    _, m = measure(detail_pass, object(), ["a"])

    assert m["peak_memory_mb"] > 1.0  # eine Million Python-Ints ist weit ueber Rundungsrauschen


# --- run_stage() -- eine vollstaendige Stufe -----------------------------

class FakeGmsStage:
    """Deckt alle vier Rollen ab, die run_stage braucht: upsert/delete_aspect/
    get_aspect fuer generate()+cleanup() (harness.loadgen), graphql fuer
    coarse_pass. get_aspect liefert immer None -- kein Leftover, cleanup_verified
    bleibt True, damit der Test sich auf run_stage's eigene Verdrahtung
    konzentriert statt auf cleanup()-Verhalten (das deckt tests/test_loadgen.py
    schon ab)."""

    def __init__(self, quiet_urns=()):
        self.quiet = set(quiet_urns)
        self.upserts = []
        self.deleted = []

    def upsert(self, entity_type, records, sync=True):
        assert isinstance(records, list)
        self.upserts.append((entity_type, len(records)))
        return records

    def delete_aspect(self, entity_type, urn, aspect):
        self.deleted.append((entity_type, urn, aspect))

    def get_aspect(self, entity_type, urn, aspect):
        return None

    def graphql(self, query, variables=None):
        urn = variables["urn"]
        count = 0 if urn in self.quiet else 9
        return {"dataset": {"statsSummary": {
            "queryCountLast30Days": count, "uniqueUserCountLast30Days": 1}}}


def test_run_stage_composes_seed_coarse_detail_cleanup_into_one_flat_dict(monkeypatch):
    monkeypatch.setattr(ledger_module, "fetch_cooccurrence", lambda gms, urn: {}, raising=False)
    quiet = {dataset_urn("s", i) for i in range(10)}
    g = FakeGmsStage(quiet_urns=quiet)

    out = run_stage(g, "s", detail_sample=5)

    assert out["scale"] == "s"
    assert out["seeded"] is True
    assert out["loadtest_s_seed_broke"] is False
    assert out["loadtest_s_coarse_api_calls"] == 50
    assert out["loadtest_s_coarse_broke"] is False
    assert out["loadtest_s_detail_edges"] == 5  # gedeckelt durch detail_sample, nicht durch die 10 Auffaelligen
    assert out["loadtest_s_detail_broke"] is False
    assert out["loadtest_s_cleanup_verified"] is True
    assert out["loadtest_s_cleanup_leftover"] == 0
    assert "cleanup_verified" not in out
    assert "cleanup_leftover" not in out


def test_run_stage_prefixes_cleanup_errors_with_the_scale_too(monkeypatch):
    """cleanup_errors ist im Brief-Code die einzige nicht umbenannte
    cleanup()-Zahl -- das haette bei mehreren Stufen in einem gemeinsamen
    Artefakt kollidiert. Hier wird auch sie mit loadtest_<scale>_ prefixed,
    konsistent mit leftover/verified."""
    monkeypatch.setattr(ledger_module, "fetch_cooccurrence", lambda gms, urn: {}, raising=False)
    g = FakeGmsStage()

    out = run_stage(g, "s", detail_sample=1)

    assert "cleanup_errors" not in out
    assert out["loadtest_s_cleanup_errors"] == []


def test_run_stage_surfaces_a_broken_seed_stage_with_its_error_text(monkeypatch):
    class BrokenSeedGms(FakeGmsStage):
        def upsert(self, entity_type, records, sync=True):
            raise RuntimeError("gms unreachable: connection refused")

    monkeypatch.setattr(ledger_module, "fetch_cooccurrence", lambda gms, urn: {}, raising=False)
    out = run_stage(BrokenSeedGms(), "s", detail_sample=1)

    assert out["loadtest_s_seed_broke"] is True
    assert "gms unreachable" in out["loadtest_s_seed_error"]


def test_run_stage_survives_a_cleanup_crash_and_still_reports_seed_coarse_detail(monkeypatch):
    """Review-Runde 1 (IMPORTANT 1): cleanup() war die einzige Stufe, die
    NICHT mit measure() umschlossen war -- ein einzelner nicht abgefangener
    Fehler in der Ruecklese-Schleife (get_aspect, bei Skala l >100k Aufrufe)
    haette den kompletten run_stage()-Aufruf zum Absturz gebracht und damit
    auch die bereits gemessenen Seed-/Grob-/Detail-Zahlen verloren."""
    class BrokenCleanupGms(FakeGmsStage):
        def get_aspect(self, entity_type, urn, aspect):
            raise RuntimeError("transient 503 during cleanup readback")

    monkeypatch.setattr(ledger_module, "fetch_cooccurrence", lambda gms, urn: {}, raising=False)

    out = run_stage(BrokenCleanupGms(), "s", detail_sample=1)

    # Seed/Grob/Detail sind unversehrt -- kein Absturz hat sie mitgerissen.
    assert out["loadtest_s_seed_broke"] is False
    assert out["loadtest_s_coarse_broke"] is False
    assert out["loadtest_s_coarse_api_calls"] == 50
    assert out["loadtest_s_detail_broke"] is False

    # Der Cleanup-Fehler ist sichtbar, nicht verschluckt.
    assert out["loadtest_s_cleanup_broke"] is True
    assert "transient 503" in out["loadtest_s_cleanup_error"]
    assert out["loadtest_s_cleanup_verified"] is False


# --- run_smoke() -- kleiner, lesender Live-Nachweis ----------------------

def test_run_smoke_writes_a_readonly_artifact_with_coarse_metrics(tmp_path):
    """run_smoke() ist read-only (nur coarse_pass, kein generate()/cleanup())
    -- Belegt in Fix-Runde 1 (IMPORTANT 2): jede Zahl in Prosa kommt aus einem
    Lauf-Artefakt in harness/runs/ (global-constraints.md), nicht nur aus
    einem Terminal-Mitschnitt."""
    g = FakeGmsCoarse()
    out_path = tmp_path / "loadtest_smoke.json"

    artifact = run_smoke(g, "s", out_path)

    assert out_path.exists()
    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert on_disk == artifact
    assert artifact["seeded"] is False
    assert artifact["scale"] == "s"
    assert artifact["loadtest_smoke_coarse_api_calls"] == 50
    assert artifact["loadtest_smoke_coarse_broke"] is False


def test_run_smoke_records_a_broken_coarse_pass_instead_of_crashing(tmp_path):
    class BrokenGraphqlGms:
        def graphql(self, query, variables=None):
            raise RuntimeError("GraphQL HTTP 500: upstream unavailable")

    out_path = tmp_path / "loadtest_smoke.json"
    artifact = run_smoke(BrokenGraphqlGms(), "s", out_path)

    assert artifact["loadtest_smoke_coarse_broke"] is True
    assert "upstream unavailable" in artifact["loadtest_smoke_coarse_error"]
