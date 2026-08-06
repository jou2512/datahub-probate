from harness.seed_queries import build_query_records


def test_builds_one_record_per_pair_with_subject():
    pairs = [("SELECT 1 FROM orders", "urn:li:dataset:(urn:li:dataPlatform:snowflake,o,PROD)")]
    recs = build_query_records(pairs)
    assert len(recs) == 1
    assert recs[0]["urn"].startswith("urn:li:query:")
    assert recs[0]["queryProperties"]["value"]["statement"]["value"] == "SELECT 1 FROM orders"
    subjects = recs[0]["querySubjects"]["value"]["subjects"]
    assert subjects[0]["entity"].endswith(",o,PROD)")


def test_urns_are_stable_for_the_same_sql():
    pairs = [("SELECT 1", "urn:li:dataset:(urn:li:dataPlatform:snowflake,o,PROD)")]
    assert build_query_records(pairs)[0]["urn"] == build_query_records(pairs)[0]["urn"]
