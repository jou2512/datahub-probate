import json

import pytest

from probate.gms import GmsError
from probate.ledger import STATES, Bucket, Coverage, Edge, Timeline, coverage_from_buckets


def test_edge_key_is_stable_and_directional():
    e = Edge(upstream="urn:li:dataset:A", downstream="urn:li:dataset:B")
    assert e.key() == "urn:li:dataset:A->urn:li:dataset:B"
    assert Edge("urn:li:dataset:B", "urn:li:dataset:A").key() != e.key()


def test_edge_is_hashable_and_usable_as_dict_key():
    e = Edge("A", "B")
    assert {e: 1}[Edge("A", "B")] == 1


def test_the_four_states_and_no_fifth():
    assert STATES == ("confirmed", "dead", "missing", "unknown")


def test_bucket_carries_traffic_and_users_separately():
    b = Bucket(bucket_ms=1_700_000_000_000, total_sql_queries=7, unique_user_count=2)
    assert b.total_sql_queries == 7
    assert b.unique_user_count == 2


def test_no_buckets_means_no_window_with_a_stated_reason():
    c = coverage_from_buckets(())
    assert c.has_window is False
    assert c.buckets_seen == 0
    assert c.reason == "keine Nutzungs-Zeitfenster im Katalog"
    assert c.days_span is None


def test_buckets_with_zero_traffic_still_count_as_a_window():
    """Wir haben hingesehen. Dass nichts passiert ist, ist ein Ergebnis."""
    day = 86_400_000
    c = coverage_from_buckets((Bucket(day, 0, 0), Bucket(2 * day, 0, 0)))
    assert c.has_window is True
    assert c.buckets_seen == 2
    assert c.reason == ""


def test_span_is_measured_from_oldest_to_newest_bucket():
    day = 86_400_000
    c = coverage_from_buckets((Bucket(10 * day, 3, 1), Bucket(40 * day, 1, 1)))
    assert c.oldest_bucket_ms == 10 * day
    assert c.newest_bucket_ms == 40 * day
    assert c.days_span == 30


def test_buckets_are_sorted_before_measuring_the_span():
    day = 86_400_000
    c = coverage_from_buckets((Bucket(40 * day, 1, 1), Bucket(10 * day, 3, 1)))
    assert c.oldest_bucket_ms == 10 * day


DAY = 86_400_000


def test_last_covered_is_the_newest_bucket_with_actual_traffic():
    t = Timeline((Bucket(10 * DAY, 5, 2), Bucket(20 * DAY, 0, 0), Bucket(30 * DAY, 0, 0)))
    assert t.last_covered_ms == 10 * DAY


def test_dead_since_counts_days_from_the_last_covered_bucket():
    t = Timeline((Bucket(10 * DAY, 5, 2), Bucket(30 * DAY, 0, 0)))
    days, at_least = t.dead_since(now_ms=40 * DAY)
    assert days == 30
    assert at_least is False


def test_never_covered_is_reported_as_at_least_since_the_oldest_observation():
    """Vor dem aeltesten Bucket wissen wir nichts. Also 'mindestens seit',
    nicht 'seit' -- eine Zahl, die mehr behauptet als die Daten hergeben,
    ist genau der Fehler, gegen den dieses Werkzeug antritt."""
    t = Timeline((Bucket(10 * DAY, 0, 0), Bucket(30 * DAY, 0, 0)))
    days, at_least = t.dead_since(now_ms=40 * DAY)
    assert days == 30
    assert at_least is True
    assert t.last_covered_ms is None


def test_empty_timeline_yields_no_age_at_all():
    """Ohne Zeitfenster gibt es kein Alter. None ist die richtige Antwort,
    0 waere eine Luege."""
    days, at_least = Timeline(()).dead_since(now_ms=40 * DAY)
    assert days is None
    assert at_least is False


def test_series_keeps_every_bucket_in_order_instead_of_summing_them():
    t = Timeline((Bucket(30 * DAY, 1, 1), Bucket(10 * DAY, 5, 2)))
    assert t.series == ((10 * DAY, 5), (30 * DAY, 1))


from probate.ledger import EdgeVerdict, classify_edges

NO_DATA = Coverage(0, None, None, "keine Nutzungs-Zeitfenster im Katalog")
LOOKED = Coverage(30, 10 * DAY, 40 * DAY, "")


def test_unknown_is_never_dead_when_no_windows_exist():
    """DIE Kernregel. Der Fehler, gegen den der ganze Umbau antritt.

    Links: keine Zeitfenster -> Aussage nicht moeglich -> unknown.
    Rechts: Zeitfenster da, Verkehr null -> Aussage moeglich -> dead.
    Summiert waeren beide dieselbe Null.
    """
    ohne = classify_edges(
        focus="urn:up", declared={"urn:down"}, cooccurred={},
        coverage_by_urn={"urn:down": NO_DATA},
        timeline_by_urn={"urn:down": Timeline(())},
        now_ms=50 * DAY)
    mit = classify_edges(
        focus="urn:up", declared={"urn:down"}, cooccurred={},
        coverage_by_urn={"urn:down": LOOKED},
        timeline_by_urn={"urn:down": Timeline((Bucket(40 * DAY, 0, 0),))},
        now_ms=50 * DAY)

    assert ohne[0].state == "unknown"
    assert mit[0].state == "dead"
    assert ohne[0].evidence["reason"] == "keine Nutzungs-Zeitfenster im Katalog"


def test_a_urn_missing_from_the_coverage_map_is_unknown_not_dead():
    """Ein Dataset, das wir gar nicht abgefragt haben, ist unknown.
    Ein stilles .get()-Default auf 'abgedeckt' waere ein Fehlbefund."""
    v = classify_edges(
        focus="urn:up", declared={"urn:down"}, cooccurred={},
        coverage_by_urn={}, timeline_by_urn={}, now_ms=50 * DAY)
    assert v[0].state == "unknown"
    assert v[0].evidence["reason"] == "nicht abgefragt"


def test_declared_and_measured_is_confirmed_with_the_query_urn_as_evidence():
    v = classify_edges(
        focus="urn:up", declared={"urn:down"},
        cooccurred={"urn:down": ["urn:li:query:q1", "urn:li:query:q2"]},
        coverage_by_urn={"urn:down": LOOKED},
        timeline_by_urn={"urn:down": Timeline((Bucket(40 * DAY, 9, 2),))},
        now_ms=50 * DAY)
    assert v[0].state == "confirmed"
    assert v[0].evidence["query_urns"] == ["urn:li:query:q1", "urn:li:query:q2"]


def test_measured_but_not_declared_is_missing_and_never_unknown():
    """Was wir gemessen haben, kann nicht 'nicht gemessen' sein --
    auch dann nicht, wenn die Aggregat-Abdeckung duenn ist."""
    v = classify_edges(
        focus="urn:up", declared=set(),
        cooccurred={"urn:other": ["urn:li:query:q9"]},
        coverage_by_urn={"urn:other": NO_DATA},
        timeline_by_urn={"urn:other": Timeline(())},
        now_ms=50 * DAY)
    assert v[0].state == "missing"
    assert v[0].edge.key() == "urn:up->urn:other"


def test_missing_edges_declare_their_direction_as_unproven():
    """QuerySubject nennt nur `entity`, kein Richtungsfeld. Ko-Okkurrenz
    ist ungerichtet -- das muss im Beleg stehen, sonst wandert eine
    geratene Richtung in P3 in den Katalog."""
    v = classify_edges(
        focus="urn:up", declared=set(),
        cooccurred={"urn:other": ["urn:li:query:q9"]},
        coverage_by_urn={}, timeline_by_urn={}, now_ms=50 * DAY)
    assert v[0].evidence["direction_evidence"] == "co-occurrence (undirected)"


def test_every_state_produced_is_one_of_the_four():
    v = classify_edges(
        focus="urn:up", declared={"a", "b"},
        cooccurred={"b": ["urn:li:query:q1"], "c": ["urn:li:query:q2"]},
        coverage_by_urn={"a": LOOKED, "b": LOOKED, "c": LOOKED},
        timeline_by_urn={"a": Timeline((Bucket(40 * DAY, 0, 0),)),
                         "b": Timeline((Bucket(40 * DAY, 4, 1),)),
                         "c": Timeline((Bucket(40 * DAY, 4, 1),))},
        now_ms=50 * DAY)
    assert {x.state for x in v} == {"dead", "confirmed", "missing"}
    assert all(x.state in STATES for x in v)


def test_verdict_json_carries_state_evidence_coverage_and_timeline():
    v = classify_edges(
        focus="urn:up", declared={"urn:down"}, cooccurred={},
        coverage_by_urn={"urn:down": LOOKED},
        timeline_by_urn={"urn:down": Timeline((Bucket(40 * DAY, 0, 0),))},
        now_ms=50 * DAY)[0].to_json(now_ms=50 * DAY)
    assert v["state"] == "dead"
    assert v["edge"] == "urn:up->urn:down"
    assert v["coverage"]["buckets_seen"] == 30
    assert v["timeline"]["dead_since_days"] == 10


# --- Fix-Runde 1 (Review) ---------------------------------------------


def test_an_empty_query_list_is_not_a_measurement_and_yields_no_missing_edge():
    """CRITICAL 1. Keine Messung ist kein Befund -- das Spiegelbild des
    urspruenglichen Fehlers waere eine erfundene Kante."""
    v = classify_edges(
        focus="urn:up", declared=set(), cooccurred={"urn:other": []},
        coverage_by_urn={}, timeline_by_urn={}, now_ms=50 * DAY)
    assert v == []


def test_a_zero_traffic_window_stays_dead_regardless_of_query_source():
    """Query-Quellen-Gate Regel 1: ein Fenster mit Null Verkehr ist
    Beleg genug -- unabhaengig von queries_seen."""
    v = classify_edges(
        focus="urn:up", declared={"urn:down"}, cooccurred={},
        coverage_by_urn={"urn:down": LOOKED},
        timeline_by_urn={"urn:down": Timeline((Bucket(40 * DAY, 0, 0),))},
        now_ms=50 * DAY, queries_seen=0)
    assert v[0].state == "dead"


def test_traffic_without_a_reachable_query_source_is_unknown_not_dead():
    """Query-Quellen-Gate Regel 2: Verkehr gemessen, aber queries_seen
    == 0 -- 'keine Query-Ingestion' ist von 'Queries beruehren die
    Kante nicht' nicht unterscheidbar, also unknown statt dead."""
    v = classify_edges(
        focus="urn:up", declared={"urn:down"}, cooccurred={},
        coverage_by_urn={"urn:down": LOOKED},
        timeline_by_urn={"urn:down": Timeline((Bucket(40 * DAY, 9, 2),))},
        now_ms=50 * DAY, queries_seen=0)
    assert v[0].state == "unknown"
    assert v[0].evidence["reason"] == (
        "verkehr gemessen, aber query-quelle leer — kante nicht pruefbar")


def test_traffic_with_a_queried_source_and_no_pair_is_dead():
    """Query-Quellen-Gate Regel 3: Verkehr gemessen, Query-Quelle
    befragt, keine Paar-Query fuer diese Kante -- starker Beleg."""
    v = classify_edges(
        focus="urn:up", declared={"urn:down"}, cooccurred={},
        coverage_by_urn={"urn:down": LOOKED},
        timeline_by_urn={"urn:down": Timeline((Bucket(40 * DAY, 9, 2),))},
        now_ms=50 * DAY, queries_seen=5)
    assert v[0].state == "dead"


def test_a_declared_self_edge_is_never_emitted():
    """IMPORTANT 3. Der Fokus ist niemals sein eigenes Ziel."""
    v = classify_edges(
        focus="urn:up", declared={"urn:up"}, cooccurred={},
        coverage_by_urn={"urn:up": LOOKED},
        timeline_by_urn={"urn:up": Timeline((Bucket(40 * DAY, 9, 2),))},
        now_ms=50 * DAY, queries_seen=5)
    assert v == []


def test_a_cooccurred_self_edge_is_never_emitted():
    """IMPORTANT 3, zweiter Zweig: auch ueber Ko-Okkurrenz nicht."""
    v = classify_edges(
        focus="urn:up", declared=set(),
        cooccurred={"urn:up": ["urn:li:query:q1"]},
        coverage_by_urn={}, timeline_by_urn={}, now_ms=50 * DAY)
    assert v == []


def test_coverage_and_timeline_disagreement_is_unknown_not_dead():
    """IMPORTANT 4. Abdeckung meldet Fenster, die Zeitachse ist leer --
    ein dead ohne Alters-Beleg waere ein Vertragsbruch dieses Moduls."""
    v = classify_edges(
        focus="urn:up", declared={"urn:down"}, cooccurred={},
        coverage_by_urn={"urn:down": LOOKED},
        timeline_by_urn={"urn:down": Timeline(())},
        now_ms=50 * DAY)
    assert v[0].state == "unknown"
    assert v[0].evidence["reason"] == "abdeckung und zeitachse widersprechen sich"


def test_state_sweep_over_declared_x_window_x_pair_query():
    """Reviewer minor 8, vom Controller befoerdert: die acht Kombinationen
    aus deklariert x Fenster-Abdeckung x Paar-Query, bei queries_seen > 0
    und (wo ein Fenster existiert) Verkehr > 0. Beweist das Kernversprechen
    ueber den vollen Kombinationsraum statt an Einzelbeispielen."""
    combos = {
        "t_dwq": (True, True, True),     # deklariert, Fenster, Paar-Query -> confirmed
        "t_dw": (True, True, False),     # deklariert, Fenster, keine Paar-Query -> dead (Regel 3)
        "t_dq": (True, False, True),     # deklariert, kein Fenster, Paar-Query -> unknown
        "t_d": (True, False, False),     # deklariert, kein Fenster, keine Paar-Query -> unknown
        "t_wq": (False, True, True),     # nicht deklariert, Fenster, Paar-Query -> missing
        "t_w": (False, True, False),     # nicht deklariert, Fenster, keine Paar-Query -> abwesend
        "t_q": (False, False, True),     # nicht deklariert, kein Fenster, Paar-Query -> missing
        "t_": (False, False, False),     # nichts davon -> abwesend
    }
    declared = {name for name, (d, _, _) in combos.items() if d}
    cooccurred = {
        name: (["urn:li:query:q1"] if q else [])
        for name, (_, _, q) in combos.items()
    }
    coverage_by_urn = {name: LOOKED for name, (_, w, _) in combos.items() if w}
    timeline_by_urn = {
        name: Timeline((Bucket(40 * DAY, 5, 1),))
        for name, (_, w, _) in combos.items() if w
    }

    v = classify_edges(
        focus="urn:up", declared=declared, cooccurred=cooccurred,
        coverage_by_urn=coverage_by_urn, timeline_by_urn=timeline_by_urn,
        now_ms=50 * DAY, queries_seen=5)

    by_target = {x.edge.downstream: x.state for x in v}
    assert by_target == {
        "t_dwq": "confirmed",
        "t_dw": "dead",
        "t_dq": "unknown",
        "t_d": "unknown",
        "t_wq": "missing",
        "t_q": "missing",
    }
    assert "t_w" not in by_target
    assert "t_" not in by_target


# --- Task 5: Beschaffung ------------------------------------------------

from probate.ledger import fetch_cooccurrence, fetch_declared_edges, fetch_usage, usage_evidence


class FakeGms:
    """Handgeschrieben, kein Mock-Rahmenwerk -- gleiches Muster wie
    tests/test_writeback.py.

    `send_by_call` bedient `_send()` -- den Weg, den `fetch_usage` jetzt
    nimmt (rohe Zeitreihen-Ablage statt `usageStats`-Aggregation, siehe
    `probate/ledger.py`). `graphql_by_call` bleibt fuer Lineage/Ko-
    Okkurrenz unveraendert, das sind weiterhin echte GraphQL-Aufrufe."""

    def __init__(self, graphql_by_call=None, aspects=None, send_by_call=None, base="urn:test:gms-base"):
        self.graphql_by_call = list(graphql_by_call or [])
        self.aspects = aspects or {}
        self.send_by_call = list(send_by_call or [])
        self.queries_sent = []
        self.sends_sent = []
        self.graphql_call_count = 0
        self.base = base

    def graphql(self, query, variables=None):
        self.queries_sent.append((query, variables))
        self.graphql_call_count += 1
        return self.graphql_by_call.pop(0)

    def get_aspect(self, entity_type, urn, aspect):
        return self.aspects.get((entity_type, urn, aspect))

    def _send(self, method, url, payload):
        self.sends_sent.append((method, url, payload))
        return self.send_by_call.pop(0)


def _raw_usage_send(entries, status=200):
    """Baut eine `(status, body)`-Antwort im Format von
    `getTimeseriesAspectValues`, wie sie `fetch_usage` jetzt liest
    (siehe live-vermessene Form in `probate/ledger.py`s Kommentar).

    `entries`: Liste von `(bucket_ms, total_sql_queries, unique_user_count)`
    -- `total_sql_queries`/`unique_user_count` duerfen `None` sein, um den
    Null-Metrik-Fall nachzubilden (der reale Aspekt-JSON-String traegt dann
    ein `null`, exakt wie `json.dumps` es fuer `None` erzeugt)."""
    values = []
    for bucket_ms, total, unique in entries:
        aspect_value = {
            "timestampMillis": bucket_ms,
            "totalSqlQueries": total,
            "uniqueUserCount": unique,
        }
        values.append({"aspect": {"value": json.dumps(aspect_value)}})
    return (status, {"value": {"values": values}})


_USAGE_URN = "urn:li:dataset:(urn:li:dataPlatform:postgres,test.x,PROD)"  # muss die
# Allowlist aus gms.py::_validate_urn erfuellen -- "urn:x" tut das nicht
# (kein drittes ":"-Segment) und faellt sonst VOR jedem `_send`-Aufruf durch.


def test_fetch_usage_turns_buckets_into_bucket_objects():
    g = FakeGms(send_by_call=[_raw_usage_send([(10 * DAY, 5, 2), (20 * DAY, 0, 0)])])
    got = fetch_usage(g, _USAGE_URN)
    assert got == (Bucket(10 * DAY, 5, 2), Bucket(20 * DAY, 0, 0))


def test_fetch_usage_returns_empty_tuple_when_the_raw_store_has_no_values():
    """Kein geschriebener Bucket im Fenster. Leer heisst hier
    'nicht gemessen' -- und genau so kommt es bei Coverage an."""
    g = FakeGms(send_by_call=[_raw_usage_send([])])
    assert fetch_usage(g, _USAGE_URN) == ()
    assert coverage_from_buckets(fetch_usage(
        FakeGms(send_by_call=[_raw_usage_send([])]), _USAGE_URN)).has_window is False


def test_fetch_usage_treats_a_missing_values_key_the_same_as_an_empty_list():
    """`body["value"]` kann fehlen, wenn die Rohablage fuer diese URN noch
    nie geschrieben hat -- kein Fehlerfall, dieselbe leere Antwort."""
    g = FakeGms(send_by_call=[(200, {"value": {}})])
    assert fetch_usage(g, _USAGE_URN) == ()


def test_fetch_usage_treats_a_null_metric_as_zero_traffic_not_as_a_missing_bucket():
    """Ein Bucket mit null Verkehr ist ein Beleg, dass hingesehen wurde.
    Er darf nicht wegfallen, sonst wird aus `dead` ein `unknown`."""
    g = FakeGms(send_by_call=[_raw_usage_send([(10 * DAY, None, None)])])
    assert fetch_usage(g, _USAGE_URN) == (Bucket(10 * DAY, 0, 0),)


def test_fetch_usage_sends_the_mandatory_limit_field():
    """Falle 14 (UEBERGABE.md): `getTimeseriesAspectValues` OHNE `limit`
    liefert HTTP 500 `NullPointerException: "limit" is null`."""
    g = FakeGms(send_by_call=[_raw_usage_send([])])
    fetch_usage(g, _USAGE_URN)
    _method, url, payload = g.sends_sent[0]
    assert "getTimeseriesAspectValues" in url
    assert payload["limit"] > 0


def test_fetch_usage_raises_instead_of_returning_empty_on_a_failed_fetch():
    """Requirement: ein fehlgeschlagener Fetch wirft GmsError. Eine leere
    Rueckgabe waere ununterscheidbar von 'wir haben hingesehen, nichts da'."""
    g = FakeGms(send_by_call=[(500, "kaputt")])
    with pytest.raises(GmsError):
        fetch_usage(g, _USAGE_URN)


def test_fetch_usage_raises_instead_of_silently_truncating_past_the_limit():
    """Pagination-Requirement: mehr Buckets als das Limit duerfen nicht
    rundgeschnitten werden -- das waere ein falsches `dead`/`unknown`
    statt eines sichtbaren Fehlers."""
    from probate.ledger import USAGE_TIMESERIES_LIMIT

    entries = [(i * DAY, 1, 1) for i in range(USAGE_TIMESERIES_LIMIT)]
    g = FakeGms(send_by_call=[_raw_usage_send(entries)])
    with pytest.raises(GmsError):
        fetch_usage(g, _USAGE_URN)


def test_fetch_usage_validates_the_urn_before_building_the_url():
    """`_validate_urn` (Finding C4, Pfad-Traversal-Allowlist) wird explizit
    wiederholt, weil diese Funktion `gms._send`/`gms.base` direkt benutzt,
    an der oeffentlichen, gehaerteten `Gms`-Methode vorbei."""
    g = FakeGms(send_by_call=[])
    with pytest.raises(GmsError):
        fetch_usage(g, "urn:li:dataset:../../etc/passwd")
    assert g.sends_sent == []  # gar nicht erst gesendet


def test_fetch_declared_edges_passes_the_count_limit_into_the_query():
    """Falle 12: get_lineage liefert >100k Zeichen ohne Vorgabe."""
    g = FakeGms([{"dataset": {"lineage": {"relationships": [
        {"entity": {"urn": "urn:d1"}}, {"entity": {"urn": "urn:d2"}}]}}}])
    assert fetch_declared_edges(g, "urn:x", count=50) == {"urn:d1", "urn:d2"}
    sent_query, sent_vars = g.queries_sent[0]
    assert sent_vars["count"] == 50
    assert "$count" in sent_query


def test_fetch_cooccurrence_keeps_the_query_urn_as_evidence_per_target():
    """targets.fetch_measured wirft die Query-URN weg. Genau die ist der
    Beleg, den jede confirmed/missing-Kante mitfuehren muss."""
    g = FakeGms(
        [{"searchAcrossEntities": {"total": 1, "searchResults": [
            {"entity": {"urn": "urn:li:query:q1"}}]}}],
        aspects={("query", "urn:li:query:q1", "querysubjects"): {
            "value": {"subjects": [{"entity": "urn:x"}, {"entity": "urn:other"}]}}},
    )
    cooc, total = fetch_cooccurrence(g, "urn:x")
    assert cooc == {"urn:other": ["urn:li:query:q1"]}
    assert total == 1


def test_fetch_cooccurrence_never_reports_the_focus_dataset_as_its_own_consumer():
    g = FakeGms(
        [{"searchAcrossEntities": {"total": 1, "searchResults": [
            {"entity": {"urn": "urn:li:query:q1"}}]}}],
        aspects={("query", "urn:li:query:q1", "querysubjects"): {
            "value": {"subjects": [{"entity": "urn:x"}]}}},
    )
    cooc, total = fetch_cooccurrence(g, "urn:x")
    assert cooc == {}
    assert total == 1


def test_fetch_cooccurrence_collects_every_query_that_touches_the_same_target():
    g = FakeGms(
        [{"searchAcrossEntities": {"total": 2, "searchResults": [
            {"entity": {"urn": "urn:li:query:q1"}},
            {"entity": {"urn": "urn:li:query:q2"}}]}}],
        aspects={
            ("query", "urn:li:query:q1", "querysubjects"): {
                "value": {"subjects": [{"entity": "urn:x"}, {"entity": "urn:o"}]}},
            ("query", "urn:li:query:q2", "querysubjects"): {
                "value": {"subjects": [{"entity": "urn:x"}, {"entity": "urn:o"}]}},
        },
    )
    cooc, total = fetch_cooccurrence(g, "urn:x")
    assert cooc == {"urn:o": ["urn:li:query:q1", "urn:li:query:q2"]}
    assert total == 2


def test_fetch_cooccurrence_total_is_the_search_total_not_the_page_length():
    """IMPORTANT 2 (Review Fix-Runde 1): COOCCURRENCE_Q begrenzt auf
    count=200. Bei mehr echten Treffern waere `len(searchResults)` eine
    Unterzaehlung -- `total` aus der Suchantwort ist die einzige Zahl,
    die als `queries_seen` gefahrlos in classify_edges darf."""
    g = FakeGms(
        [{"searchAcrossEntities": {"total": 350, "searchResults": [
            {"entity": {"urn": f"urn:li:query:q{i}"}} for i in range(200)]}}],
        aspects={},
    )
    cooc, total = fetch_cooccurrence(g, "urn:x")
    assert total == 350
    assert total != 200


def test_usage_evidence_fetches_buckets_exactly_once():
    """IMPORTANT 3 (Review Fix-Runde 1): Coverage und Timeline duerfen
    strukturell nicht aus zwei getrennten `fetch_usage`-Aufrufen stammen
    -- sonst koennte eine Race den Divergenz-Zweig in classify_edges
    ausloesen, ohne dass die Daten wirklich widerspruechlich sind.

    `fetch_usage` geht seit dem Ledger-Fix ueber `_send` (Rohablage), nicht
    mehr ueber `graphql` (Aggregation) -- der EIN-Fetch-Vertrag wird jetzt
    gegen `sends_sent` statt `graphql_call_count` geprueft."""
    g = FakeGms(send_by_call=[_raw_usage_send([(10 * DAY, 5, 2)])])
    cov, tl = usage_evidence(g, _USAGE_URN)
    assert len(g.sends_sent) == 1
    assert g.graphql_call_count == 0
    assert cov.buckets_seen == 1
    assert tl.buckets == (Bucket(10 * DAY, 5, 2),)


# --- Task 6: run() + Lauf-Artefakt --------------------------------------

import json as _json_task6

from probate.ledger import run


def _gms_for_run():
    """Fokus urn:x: deklariert d1 (mit Verkehr -> confirmed) und d2
    (Buckets, aber kein Verkehr -> dead); gemessen zusaetzlich o
    (-> missing).

    `run()` ruft `usage_evidence` (-> `fetch_usage` -> `_send`, jetzt mit
    `_validate_urn`) fuer `sorted(declared | set(cooccurred))` ==
    ["urn:li:dataset:d1", "urn:li:dataset:d2", "urn:li:dataset:o"] --
    dieselbe alphabetische Reihenfolge wie zuvor mit den kuerzeren
    Platzhaltern, nur URN-foermig (die Allowlist aus gms.py::_validate_urn
    verlangt ein drittes ":"-Segment; "urn:d1" hat keins). `send_by_call`
    steht in genau dieser Reihenfolge, seit `fetch_usage` die Rohablage
    statt der Aggregation liest."""
    return FakeGms(
        graphql_by_call=[
            {"dataset": {"lineage": {"relationships": [
                {"entity": {"urn": "urn:li:dataset:d1"}}, {"entity": {"urn": "urn:li:dataset:d2"}}]}}},
            {"searchAcrossEntities": {"total": 1, "searchResults": [
                {"entity": {"urn": "urn:li:query:q1"}}]}},
        ],
        send_by_call=[
            _raw_usage_send([(40 * DAY, 3, 1)]),  # urn:li:dataset:d1
            _raw_usage_send([(40 * DAY, 0, 0)]),  # urn:li:dataset:d2
            _raw_usage_send([(40 * DAY, 7, 1)]),  # urn:li:dataset:o
        ],
        aspects={("query", "urn:li:query:q1", "querysubjects"): {
            "value": {"subjects": [{"entity": "urn:x"}, {"entity": "urn:li:dataset:d1"},
                                   {"entity": "urn:li:dataset:o"}]}}},
    )


def test_run_counts_every_state_into_flat_top_level_keys():
    """Flach und ganzzahlig, weil audit_claims per Schluesselnamen
    vergleicht -- verschachtelt waere die Zahl nicht pruefbar."""
    out = run(_gms_for_run(), focus="urn:x", now_ms=50 * DAY)
    assert out["edges_total"] == 3
    assert out["edges_confirmed"] == 1
    assert out["edges_dead"] == 1
    assert out["edges_missing"] == 1
    assert out["edges_unknown"] == 0


def test_run_reports_coverage_above_the_result_not_inside_it():
    out = run(_gms_for_run(), focus="urn:x", now_ms=50 * DAY)
    assert out["coverage_buckets_seen"] == 3
    assert "coverage_thin" in out


def test_run_marks_the_data_as_seeded_because_the_sample_catalog_has_none():
    out = run(_gms_for_run(), focus="urn:x", now_ms=50 * DAY)
    assert out["seeded"] is True


def test_run_counts_api_calls_so_the_load_test_has_a_baseline():
    out = run(_gms_for_run(), focus="urn:x", now_ms=50 * DAY)
    assert out["api_calls"] == 6  # 1 lineage + 1 search + 1 aspect + 3 usage


def test_run_output_is_json_serialisable_without_a_custom_encoder():
    _json_task6.dumps(run(_gms_for_run(), focus="urn:x", now_ms=50 * DAY))


def test_run_threads_queries_seen_from_cooccurrence_total_not_page_length():
    """Waere `cooccurred` (der Tupel-Rueckgabewert von fetch_cooccurrence)
    versehentlich unentpackt an classify_edges durchgereicht worden, waere
    dieser Lauf schon an `set(cooccurred)` mit TypeError gescheitert
    (ein 2-Tupel aus dict und int ist nicht hashbar). Dieser Test haelt
    fest, dass queries_seen korrekt der zweite Rueckgabewert ist, nicht 0."""
    out = run(_gms_for_run(), focus="urn:x", now_ms=50 * DAY)
    d1_edge = next(e for e in out["edges"] if e["downstream"] == "urn:li:dataset:d1")
    assert d1_edge["state"] == "confirmed"
