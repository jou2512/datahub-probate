from probate.ledger import STATES, Bucket, Coverage, Edge, coverage_from_buckets


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
