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


def test_a_proposal_cannot_be_constructed_without_state():
    """state ist Pflicht wie evidence -- die Task-12-Haertung braucht den
    rohen Kantenzustand an der Schreibstelle, nicht nur `kind`."""
    import inspect
    sig = inspect.signature(Proposal)
    assert sig.parameters["state"].default is inspect.Parameter.empty


# --- Task 12: fehlende Kante eintragen -- mergen, nie ersetzen -----------

from probate.correct import (  # noqa: E402
    DEAD_MARKER_KEY,
    _require_dead_state,
    _require_substantive_evidence,
    apply_proposal,
    merge_upstreams,
)


class _FakeGmsView:
    """Nur `get_aspect`, gegen dieselbe `existing`-Map wie RecordingWb.

    Der Brief-Hinweis fuer diese Aufgabe loest den scheinbaren Widerspruch
    ausdruecklich auf: `merge_upstreams` ist die Wahrheit, `apply_proposal`
    muss es mit dem ECHTEN `before` aufrufen -- eine `RecordingWb` ganz
    ohne `.gms` wuerde beim Mergen "urn:legit" verlieren, obwohl der Test
    genau dessen Erhalt prueft. Also traegt der Fake ein `.gms`, das
    dieselbe `existing`-Map liest wie `aspect()` selbst -- eine Wahrheit,
    kein zweiter Datensatz.
    """

    def __init__(self, existing: dict):
        self._existing = existing

    def get_aspect(self, entity_type, urn, aspect):
        return self._existing.get((entity_type, urn, aspect))


class RecordingWb:
    """Handgeschrieben, wie tests/test_writeback.py -- kein Mock-Rahmenwerk."""

    def __init__(self, existing=None):
        self.existing = existing or {}
        self.gms = _FakeGmsView(self.existing)
        self.written = []
        self.dry_run = False

    def aspect(self, entity_type, urn, aspect, value):
        before = self.existing.get((entity_type, urn, aspect))
        self.written.append((entity_type, urn, aspect, value, before))

        class R:
            applied, detail = True, "ok"

        R.before = before
        return R


EXISTING = {("dataset", "urn:m", "upstreamLineage"): {"value": {"upstreams": [
    {"dataset": "urn:legit", "type": "TRANSFORMED",
     "auditStamp": {"time": 1, "actor": "urn:li:corpuser:someone"}}]}}}


def test_adding_an_upstream_keeps_every_existing_one():
    """Der Fehler, den DataHub selbst macht: eine frische, leere Liste
    bauen und als vollen Aspekt emittieren. Wir mergen."""
    merged = merge_upstreams(EXISTING[("dataset", "urn:m", "upstreamLineage")],
                              add=[{"dataset": "urn:up", "type": "TRANSFORMED",
                                    "auditStamp": {"time": 2, "actor": "urn:li:corpuser:x"}}])
    assert {u["dataset"] for u in merged["upstreams"]} == {"urn:legit", "urn:up"}


def test_adding_an_upstream_that_is_already_there_does_not_duplicate_it():
    merged = merge_upstreams(EXISTING[("dataset", "urn:m", "upstreamLineage")],
                              add=[{"dataset": "urn:legit", "type": "TRANSFORMED",
                                    "auditStamp": {"time": 2, "actor": "urn:li:corpuser:x"}}])
    assert len(merged["upstreams"]) == 1


def test_merging_into_a_dataset_without_any_lineage_yet_starts_from_empty():
    merged = merge_upstreams(None, add=[{"dataset": "urn:up", "type": "TRANSFORMED",
                                          "auditStamp": {"time": 2, "actor": "urn:li:corpuser:x"}}])
    assert [u["dataset"] for u in merged["upstreams"]] == ["urn:up"]


def test_dropping_an_upstream_removes_only_that_one():
    merged = merge_upstreams(EXISTING[("dataset", "urn:m", "upstreamLineage")],
                              add=[{"dataset": "urn:up", "type": "TRANSFORMED",
                                    "auditStamp": {"time": 2, "actor": "urn:li:corpuser:x"}}],
                              drop=["urn:legit"])
    assert [u["dataset"] for u in merged["upstreams"]] == ["urn:up"]


def test_marking_dead_annotates_the_edge_and_leaves_the_others_untouched():
    before = {"value": {"upstreams": [
        {"dataset": "urn:a", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}},
        {"dataset": "urn:b", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}}]}}
    merged = merge_upstreams(before, mark_dead={"urn:a": "2026-04-11"})
    by_urn = {u["dataset"]: u for u in merged["upstreams"]}
    assert by_urn["urn:a"]["properties"][DEAD_MARKER_KEY] == "2026-04-11"
    assert "properties" not in by_urn["urn:b"]


def test_apply_add_edge_writes_through_writeback_with_a_list_payload():
    """Falle 1: POST /openapi/v3/entity/<typ> will eine LISTE. Der Weg
    darf nicht an gms.upsert() vorbeigehen, das die Liste erzwingt --
    also NIE direkt gms, immer wb.aspect()."""
    wb = RecordingWb(EXISTING)
    p = [x for x in propose(LEDGER) if x.kind == "add_edge"][0]
    apply_proposal(wb, p, actor="urn:li:corpuser:__datahub_system", now_ms=7)
    entity_type, urn, aspect, value, before = wb.written[0]
    assert (entity_type, urn, aspect) == ("dataset", "urn:m", "upstreamLineage")
    assert {u["dataset"] for u in value["upstreams"]} == {"urn:legit", "urn:up"}


def test_every_written_upstream_carries_an_auditstamp_with_an_actor():
    """Falle 3/10: Pflichtfelder und der richtige Handelnde. Ohne Token
    ist der Handelnde urn:li:corpuser:__datahub_system -- das wird
    hingeschrieben, nicht erfunden."""
    wb = RecordingWb(EXISTING)
    p = [x for x in propose(LEDGER) if x.kind == "add_edge"][0]
    apply_proposal(wb, p, actor="urn:li:corpuser:__datahub_system", now_ms=7)
    _, _, _, value, _ = wb.written[0]
    new = [u for u in value["upstreams"] if u["dataset"] == "urn:up"][0]
    assert new["auditStamp"]["actor"] == "urn:li:corpuser:__datahub_system"
    assert new["auditStamp"]["time"] == 7


# --- Haertung 1 (Task-11-Review, Fund 1): evidence={} ist konstruierbar,
# aber darf nicht geschrieben werden.

def test_require_substantive_evidence_rejects_an_add_edge_with_no_query_urns():
    p = Proposal(kind="add_edge", edge_key="urn:up->urn:m", target_urn="urn:m",
                 aspect="upstreamLineage", evidence={}, state="missing",
                 human_summary="leer")
    try:
        _require_substantive_evidence(p)
        assert False, "haette werfen muessen"
    except ValueError:
        pass


def test_require_substantive_evidence_rejects_an_add_edge_with_zero_cooccurrence():
    p = Proposal(kind="add_edge", edge_key="urn:up->urn:m", target_urn="urn:m",
                 aspect="upstreamLineage",
                 evidence={"query_urns": ["urn:li:query:q1"], "cooccurrence_count": 0},
                 state="missing", human_summary="leer")
    try:
        _require_substantive_evidence(p)
        assert False, "haette werfen muessen"
    except ValueError:
        pass


def test_require_substantive_evidence_accepts_a_real_add_edge_proposal():
    p = [x for x in propose(LEDGER) if x.kind == "add_edge"][0]
    _require_substantive_evidence(p)  # wirft nicht


def test_apply_proposal_refuses_to_write_an_add_edge_with_vacuous_evidence():
    wb = RecordingWb(EXISTING)
    p = Proposal(kind="add_edge", edge_key="urn:up->urn:m", target_urn="urn:m",
                 aspect="upstreamLineage", evidence={}, state="missing",
                 human_summary="leer")
    try:
        apply_proposal(wb, p, now_ms=7)
        assert False, "haette werfen muessen"
    except ValueError:
        pass
    assert wb.written == []


def test_apply_proposal_refuses_to_write_a_mark_dead_with_vacuous_evidence():
    wb = RecordingWb(EXISTING)
    p = Proposal(kind="mark_dead", edge_key="urn:up->urn:m", target_urn="urn:m",
                 aspect="upstreamLineage", evidence={}, state="dead",
                 human_summary="leer")
    try:
        apply_proposal(wb, p, now_ms=7)
        assert False, "haette werfen muessen"
    except ValueError:
        pass
    assert wb.written == []


# --- Haertung 2 (Task-11-Review, Fund 2): unknown darf NIE als tot
# geschrieben werden -- Sperre direkt getestet, nicht nur ueber propose().

def test_require_dead_state_accepts_exactly_the_string_dead():
    _require_dead_state("dead")  # wirft nicht


def test_require_dead_state_rejects_every_other_state():
    for bad in ("unknown", "confirmed", "missing", None, "DEAD", " dead", "dead "):
        try:
            _require_dead_state(bad)
            assert False, f"{bad!r} haette abgelehnt werden muessen"
        except ValueError:
            pass


def test_apply_proposal_refuses_to_mark_dead_an_edge_whose_state_is_not_dead():
    """Der eigentliche Verteidigungsfall: ein Proposal mit kind=mark_dead
    und vollstaendig plausibler Evidenz, aber state != 'dead' -- z.B. weil
    es (Bug oder Angriff) an propose() vorbei konstruiert wurde."""
    wb = RecordingWb({("dataset", "urn:m", "upstreamLineage"): {"value": {"upstreams": [
        {"dataset": "urn:up", "type": "TRANSFORMED",
         "auditStamp": {"time": 1, "actor": "x"}}]}}})
    p = Proposal(kind="mark_dead", edge_key="urn:up->urn:m", target_urn="urn:m",
                 aspect="upstreamLineage",
                 evidence={"dead_since_days": 117, "buckets_checked": 30},
                 state="unknown", human_summary="sollte nie ankommen")
    try:
        apply_proposal(wb, p, now_ms=7)
        assert False, "haette werfen muessen"
    except ValueError:
        pass
    assert wb.written == []


def test_apply_proposal_writes_a_well_formed_mark_dead_proposal_and_keeps_other_edges():
    wb = RecordingWb({("dataset", "urn:d", "upstreamLineage"): {"value": {"upstreams": [
        {"dataset": "urn:up", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}},
        {"dataset": "urn:other", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}},
    ]}}})
    p = [x for x in propose(LEDGER) if x.kind == "mark_dead"][0]
    apply_proposal(wb, p, now_ms=1_754_000_000_000)
    entity_type, urn, aspect, value, before = wb.written[0]
    assert (entity_type, urn, aspect) == ("dataset", "urn:d", "upstreamLineage")
    by_urn = {u["dataset"]: u for u in value["upstreams"]}
    assert DEAD_MARKER_KEY in by_urn["urn:up"]["properties"]
    assert "properties" not in by_urn["urn:other"]
