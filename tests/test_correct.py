from probate.correct import Proposal, propose

LEDGER = {"focus": "urn:up", "edges": [
    {"edge": "urn:up->urn:c", "state": "confirmed", "upstream": "urn:up",
     "downstream": "urn:c", "evidence": {"query_urns": ["urn:li:query:q1"]},
     "coverage": {"buckets_seen": 30}, "timeline": {"last_covered_ms": 3, "dead_since_days": 1}},
    {"edge": "urn:up->urn:d", "state": "dead", "upstream": "urn:up",
     "downstream": "urn:d", "evidence": {"buckets_checked": 30},
     "coverage": {"buckets_seen": 30}, "timeline": {"last_covered_ms": 100,
                                                    "dead_since_days": 117,
                                                    "dead_since_is_lower_bound": False}},
    {"edge": "urn:up->urn:m", "state": "missing", "upstream": "urn:up",
     "downstream": "urn:m", "evidence": {"query_urns": ["urn:li:query:q7"],
                                         "cooccurrence_count": 1,
                                         "direction_evidence": "co-occurrence (undirected)"},
     "coverage": {"buckets_seen": 30}, "timeline": {}},
    {"edge": "urn:up->urn:u", "state": "unknown", "upstream": "urn:up",
     "downstream": "urn:u", "evidence": {"reason": "keine Nutzungs-Zeitfenster im Katalog"},
     "coverage": {"buckets_seen": 0}, "timeline": {}},
]}


def test_a_missing_edge_becomes_an_add_edge_proposal_with_the_query_urn():
    p = [x for x in propose(LEDGER) if x.kind == "add_edge"]
    assert len(p) == 1
    assert p[0].target_urn == "urn:m"          # geschrieben wird auf das Downstream
    assert p[0].aspect == "upstreamLineage"
    assert p[0].evidence["query_urns"] == ["urn:li:query:q7"]


def test_an_add_edge_proposal_carries_the_undirected_caveat_into_the_summary():
    """Die Richtung ist NICHT gemessen. Wer sie beim Schreiben als
    gemessen ausgibt, erzeugt genau die unbelegte Behauptung, gegen die
    dieses Werkzeug antritt."""
    p = [x for x in propose(LEDGER) if x.kind == "add_edge"][0]
    assert "co-occurrence (undirected)" in p.evidence["direction_evidence"]
    assert "ungerichtet" in p.human_summary


def test_a_dead_edge_becomes_a_mark_dead_proposal_carrying_the_last_covered_date():
    p = [x for x in propose(LEDGER) if x.kind == "mark_dead"]
    assert len(p) == 1
    assert p[0].evidence["dead_since_days"] == 117
    assert p[0].evidence["last_covered_ms"] == 100


def test_a_confirmed_edge_becomes_an_enrich_doc_proposal():
    p = [x for x in propose(LEDGER) if x.kind == "enrich_doc"]
    assert len(p) == 1
    assert p[0].target_urn == "urn:c"


def test_an_unknown_edge_produces_no_proposal_at_all():
    """DIE Regel, angewandt auf das Schreiben: bei fehlender Datenlage
    wird nichts vorgeschlagen. Ein Vorschlag auf unknown waere ein
    Schreibvorgang auf Verdacht."""
    assert not [x for x in propose(LEDGER) if x.edge_key == "urn:up->urn:u"]


def test_propose_writes_nothing_at_all():
    """propose() bekommt gar kein gms/wb -- schon die Signatur schliesst
    einen Schreibvorgang aus."""
    import inspect
    assert list(inspect.signature(propose).parameters) == ["ledger"]


def test_a_proposal_cannot_be_constructed_without_evidence():
    """Evidence ist Pflicht, nicht optional -- ein Vorschlag ohne Beleg
    darf nicht existieren koennen."""
    import inspect
    sig = inspect.signature(Proposal)
    assert sig.parameters["evidence"].default is inspect.Parameter.empty
