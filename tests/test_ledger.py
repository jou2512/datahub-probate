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
