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

# LEDGER traegt bewusst KEIN top-level "seeded" -- deckt den Fall
# "Herkunft unbekannt" ab (ein handgeschriebenes Test-Ledger, das
# `ledger.run()`s Feld nicht mitfuehrt). LEDGER_SEEDED ist dieselbe
# Kantenmenge, nur mit der Herkunfts-Behauptung, die `ledger.run()` fuer
# den geseedeten Beispielkatalog tatsaechlich setzt (Review, CRITICAL 1:
# propose() reicht dieses Feld jetzt in jedes enrich_doc-Proposal durch).
LEDGER_SEEDED = {**LEDGER, "seeded": True}


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
    Abstention,
    _dead_since_iso,
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


# --- Fix-Runde 1 (Opus-Review, Task-12), CRITICAL 1: merge_upstreams las
# nur value.upstreams und loeschte damit STILL jeden anderen Top-Level-
# Schluessel des Aspekts bei JEDEM Schreibvorgang -- am gravierendsten
# fineGrainedLineages (spaltengenaue Lineage von dbt/BigQuery/Snowflake/
# Looker/Spark & Co.). Reproduktion: before mit upstreams+CLL -> nach dem
# Schreiben war CLL weg. Jetzt wird der GANZE aufgeloeste Wert als Basis
# genommen und nur upstreams ersetzt.

def test_merge_upstreams_carries_fine_grained_lineages_through_unchanged():
    cll = [{"upstreamType": "FIELD_SET", "downstreamType": "FIELD",
            "downstreams": ["urn:li:schemaField:(urn:m,customer_id)"],
            "upstreams": ["urn:li:schemaField:(urn:legit,cust_id)"],
            "confidenceScore": 1.0}]
    before = {"value": {"upstreams": [
        {"dataset": "urn:legit", "type": "TRANSFORMED",
         "auditStamp": {"time": 1, "actor": "urn:li:corpuser:someone"}}],
        "fineGrainedLineages": cll}}
    merged = merge_upstreams(before, add=[{"dataset": "urn:up", "type": "TRANSFORMED",
                                            "auditStamp": {"time": 2, "actor": "x"}}])
    assert merged["fineGrainedLineages"] == cll
    assert {u["dataset"] for u in merged["upstreams"]} == {"urn:legit", "urn:up"}


def test_merge_upstreams_carries_fine_grained_lineages_through_a_mark_dead_too():
    cll = [{"upstreamType": "FIELD_SET", "downstreamType": "FIELD",
            "downstreams": ["urn:li:schemaField:(urn:d,x)"],
            "upstreams": ["urn:li:schemaField:(urn:up,x)"]}]
    before = {"value": {"upstreams": [
        {"dataset": "urn:up", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}}],
        "fineGrainedLineages": cll}}
    merged = merge_upstreams(before, mark_dead={"urn:up": "2026-04-11"})
    assert merged["fineGrainedLineages"] == cll


def test_apply_proposal_add_edge_preserves_fine_grained_lineages_on_the_target():
    cll = [{"upstreamType": "FIELD_SET", "downstreamType": "FIELD",
            "downstreams": ["urn:li:schemaField:(urn:m,x)"],
            "upstreams": ["urn:li:schemaField:(urn:legit,x)"]}]
    wb = RecordingWb({("dataset", "urn:m", "upstreamLineage"): {"value": {"upstreams": [
        {"dataset": "urn:legit", "type": "TRANSFORMED",
         "auditStamp": {"time": 1, "actor": "x"}}], "fineGrainedLineages": cll}}})
    p = [x for x in propose(LEDGER) if x.kind == "add_edge"][0]
    apply_proposal(wb, p, now_ms=7)
    _, _, _, value, _ = wb.written[0]
    assert value["fineGrainedLineages"] == cll


# --- Fix-Runde 1, IMPORTANT 4: ein 'before' ohne 'value'-Wrapper wurde
# still zu einer leeren Liste -- totaler, stiller Datenverlust. Jetzt wird
# entweder aufgeloest (wie writeback.py:79 es beim Revert selbst tut) oder
# laut abgelehnt, nie geraten.

def test_merge_upstreams_accepts_an_unwrapped_before_like_writebacks_revert_does():
    before = {"upstreams": [{"dataset": "urn:legit", "type": "TRANSFORMED",
                              "auditStamp": {"time": 1, "actor": "x"}}]}
    merged = merge_upstreams(before, add=[{"dataset": "urn:up", "type": "TRANSFORMED",
                                            "auditStamp": {"time": 2, "actor": "x"}}])
    assert {u["dataset"] for u in merged["upstreams"]} == {"urn:legit", "urn:up"}


def test_merge_upstreams_raises_on_a_before_from_which_no_upstreams_can_be_resolved():
    try:
        merge_upstreams({"someOtherField": True})
        assert False, "haette werfen muessen"
    except ValueError:
        pass


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


# --- Fix-Runde 1, IMPORTANT 2: mark_dead schrieb den MOMENT DES
# SCHREIBENS (`_iso_day(now_ms)`) als "seit wann tot", nicht das gemessene
# Datum. Ledger sagte 117 Tage tot (last_covered_ms=100), Katalog bekam
# "heute" -- eine unbelegte Behauptung. Jetzt wird last_covered_ms aus der
# Evidenz verwendet; der alte Test pruefte nur, DASS der Schluessel
# existiert, nie seinen WERT -- deshalb bestand er trotz des Fehlers.

def test_apply_proposal_writes_the_measured_last_covered_date_not_the_write_moment():
    wb = RecordingWb({("dataset", "urn:d", "upstreamLineage"): {"value": {"upstreams": [
        {"dataset": "urn:up", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}}]}}})
    p = [x for x in propose(LEDGER) if x.kind == "mark_dead"][0]
    assert p.evidence["last_covered_ms"] == 100  # LEDGER-Fixture, zur Kontrolle
    # now_ms liegt absichtlich WEIT in der Zukunft -- wuerde es verwendet,
    # ergaebe das ein Datum weit nach 1970, und der Test wuerde das sofort zeigen.
    apply_proposal(wb, p, now_ms=9_999_999_999_999)
    _, _, _, value, _ = wb.written[0]
    by_urn = {u["dataset"]: u for u in value["upstreams"]}
    assert by_urn["urn:up"]["properties"][DEAD_MARKER_KEY] == "1970-01-01"  # aus ms=100, nicht aus now_ms


# --- Fix-Runde 2 (Opus-Re-Review), Fund 1: der reine Untergrenzen-Fall
# (dead_since_is_lower_bound=True, kein last_covered_ms) ist KEINE
# Ablehnung mehr, sondern eine ENTHALTUNG -- eigener Typ, eigenes
# Ergebnis, kein `raise`. Ablehnung (ValueError) bleibt fuer echte Fehler
# reserviert (kaputte Evidenz, manipuliertes Proposal, fehlende Kante).

def test_dead_since_iso_returns_none_when_no_last_covered_ms_is_measured():
    assert _dead_since_iso({"dead_since_days": 40, "dead_since_is_lower_bound": True}) is None


def test_dead_since_iso_returns_the_measured_date_when_last_covered_ms_is_present():
    assert _dead_since_iso({"last_covered_ms": 100}) == "1970-01-01"


def test_apply_proposal_abstains_on_a_mark_dead_without_a_measured_last_covered_timestamp():
    """Reiner Untergrenzen-Fall (dead_since_is_lower_bound=True): es gibt
    kein gemessenes Datum, nur eine Tage-Untergrenze. Ein now_ms-basierter
    Ersatz waere dieselbe unbelegte Behauptung -- das Werkzeug enthaelt
    sich, statt zu schaetzen. Das ist KEIN Fehler: `apply_proposal` gibt
    eine `Abstention` zurueck, wirft NICHTS, und schreibt nichts."""
    wb = RecordingWb({("dataset", "urn:d", "upstreamLineage"): {"value": {"upstreams": [
        {"dataset": "urn:up", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}}]}}})
    p = Proposal(kind="mark_dead", edge_key="urn:up->urn:d", target_urn="urn:d",
                 aspect="upstreamLineage",
                 evidence={"last_covered_ms": None, "dead_since_days": 40,
                           "dead_since_is_lower_bound": True, "buckets_checked": 5},
                 state="dead", human_summary="nur untergrenze, kein exaktes datum")
    result = apply_proposal(wb, p, now_ms=7)
    assert isinstance(result, Abstention)
    assert result.kind == "no_measured_dead_since_date"
    assert result.edge_key == p.edge_key
    assert result.to_json()["abstained"] is True
    assert wb.written == []


def test_abstention_is_structurally_distinct_from_a_rejection():
    """Der eigentliche Punkt des Reviews: eine Enthaltung (kein Beleg fuer
    ein Datum) und eine Ablehnung (z.B. manipuliertes Proposal) muessen
    sich PROGRAMMATISCH unterscheiden lassen -- nicht nur am Fehlertext.
    Diese Enthaltung wirft nicht; eine echte Ablehnung wirft weiterhin."""
    wb = RecordingWb({("dataset", "urn:d", "upstreamLineage"): {"value": {"upstreams": [
        {"dataset": "urn:up", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}}]}}})
    abstained_proposal = Proposal(
        kind="mark_dead", edge_key="urn:up->urn:d", target_urn="urn:d",
        aspect="upstreamLineage",
        evidence={"last_covered_ms": None, "dead_since_days": 40, "buckets_checked": 5},
        state="dead", human_summary="untergrenze")
    result = apply_proposal(wb, abstained_proposal, now_ms=7)
    assert isinstance(result, Abstention)  # kein raise

    rejected_proposal = Proposal(
        kind="add_edge", edge_key="urn:up->urn:victim", target_urn="urn:d",
        aspect="upstreamLineage",
        evidence={"query_urns": ["urn:li:query:q1"], "cooccurrence_count": 1},
        state="missing", human_summary="manipuliert")
    try:
        apply_proposal(wb, rejected_proposal, now_ms=7)
        assert False, "eine echte ablehnung haette werfen muessen"
    except ValueError:
        pass  # Ablehnung bleibt eine Exception, keine Abstention


# --- Fix-Runde 1, IMPORTANT 3: zwei stille Fehlschlaege bei mark_dead.
# (a) Upstream nicht in der bestehenden Liste -> identische Liste zurueck,
# applied=True, kein Marker irgendwo -- der Mensch bestaetigt, nichts
# passiert. (b) gar kein Aspekt vorhanden -> {"upstreams": []} geschrieben,
# eine nie gemessene Behauptung "keine Upstreams". Beide muessen laut
# scheitern.

def test_apply_proposal_refuses_to_mark_dead_an_edge_not_present_in_the_aspect():
    wb = RecordingWb({("dataset", "urn:d", "upstreamLineage"): {"value": {"upstreams": [
        {"dataset": "urn:someone_else", "type": "TRANSFORMED",
         "auditStamp": {"time": 1, "actor": "x"}}]}}})
    p = [x for x in propose(LEDGER) if x.kind == "mark_dead"][0]  # upstream=urn:up, fehlt hier
    try:
        apply_proposal(wb, p, now_ms=7)
        assert False, "haette werfen muessen"
    except ValueError:
        pass
    assert wb.written == []


def test_apply_proposal_refuses_to_mark_dead_when_the_dataset_has_no_aspect_at_all():
    wb = RecordingWb({})  # kein upstreamLineage fuer urn:d ueberhaupt
    p = [x for x in propose(LEDGER) if x.kind == "mark_dead"][0]
    try:
        apply_proposal(wb, p, now_ms=7)
        assert False, "haette werfen muessen"
    except ValueError:
        pass
    assert wb.written == []


# --- Fix-Runde 1, MINOR 8: edge_key und target_urn wurden nie
# gegeneinander geprueft -- ein manipuliertes Proposal koennte eine
# beliebige Upstream-URN auf ein beliebiges Ziel-Dataset schreiben.

def test_apply_proposal_refuses_when_edge_key_downstream_does_not_match_target_urn():
    wb = RecordingWb(EXISTING)
    p = Proposal(kind="add_edge", edge_key="urn:up->urn:victim", target_urn="urn:m",
                 aspect="upstreamLineage",
                 evidence={"query_urns": ["urn:li:query:q1"], "cooccurrence_count": 1,
                           "direction_evidence": "co-occurrence (undirected)"},
                 state="missing", human_summary="manipuliert")
    try:
        apply_proposal(wb, p, now_ms=7)
        assert False, "haette werfen muessen"
    except ValueError:
        pass
    assert wb.written == []


# --- Fix-Runde 1, MINOR 9: query_urns=[""] ist eine nicht-leere Liste,
# aber keine Substanz.

def test_require_substantive_evidence_rejects_add_edge_with_only_blank_query_urns():
    p = Proposal(kind="add_edge", edge_key="urn:up->urn:m", target_urn="urn:m",
                 aspect="upstreamLineage",
                 evidence={"query_urns": ["", "   "], "cooccurrence_count": 1},
                 state="missing", human_summary="leer")
    try:
        _require_substantive_evidence(p)
        assert False, "haette werfen muessen"
    except ValueError:
        pass


# --- Task 13: tote kante markieren (bereits mit Task 12 gebaut, hier nur
# nochmal am eigentlichen mark_dead-Proposal aus propose() belegt), kante
# entfernen (remove_edge, neu), doku aus beobachteter nutzung (enrich_doc,
# neu -- propose() erzeugte diese Vorschlagsart bereits, apply_proposal
# warf bisher ValueError darauf).

from probate.correct import remove_edge  # noqa: E402


def test_mark_dead_writes_the_last_covered_date_and_keeps_the_edge():
    """Die Kante wird MARKIERT, nicht geloescht. Ein Werkzeug, das bei
    duenner Datenlage Kanten entfernt, ist das Problem, nicht die
    Loesung -- entfernt wird nur auf ausdruecklichen Zuruf (remove_edge)."""
    wb = RecordingWb({("dataset", "urn:d", "upstreamLineage"): {"value": {"upstreams": [
        {"dataset": "urn:up", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}}]}}})
    p = [x for x in propose(LEDGER) if x.kind == "mark_dead"][0]
    apply_proposal(wb, p, now_ms=9)
    _, urn, aspect, value, _ = wb.written[0]
    assert urn == "urn:d"
    assert aspect == "upstreamLineage"
    kept = [u for u in value["upstreams"] if u["dataset"] == "urn:up"][0]
    assert kept["properties"][DEAD_MARKER_KEY] == "1970-01-01"  # last_covered_ms=100


def test_enrich_doc_appends_and_never_overwrites_an_existing_description():
    wb = RecordingWb({("dataset", "urn:c", "editableDatasetProperties"): {
        "value": {"description": "Bestehende Beschreibung."}}})
    p = [x for x in propose(LEDGER) if x.kind == "enrich_doc"][0]
    apply_proposal(wb, p, now_ms=9)
    _, urn, aspect, value, _ = wb.written[0]
    assert urn == "urn:c"
    assert aspect == "editableDatasetProperties"
    assert value["description"].startswith("Bestehende Beschreibung.")
    assert "probate" in value["description"]


def test_enrich_doc_preserves_other_top_level_keys_on_the_aspect():
    """Derselbe Grundsatz wie fineGrainedLineages bei merge_upstreams:
    ein unbekannter Top-Level-Schluessel des Aspekts wird nicht still
    geloescht, nur weil enrich_doc nur description kennt."""
    wb = RecordingWb({("dataset", "urn:c", "editableDatasetProperties"): {
        "value": {"description": "Bestehende Beschreibung.",
                   "customProperties": {"owner_team": "analytics"}}}})
    p = [x for x in propose(LEDGER) if x.kind == "enrich_doc"][0]
    apply_proposal(wb, p, now_ms=9)
    _, _, _, value, _ = wb.written[0]
    assert value["customProperties"] == {"owner_team": "analytics"}


def test_enriched_documentation_names_the_data_as_seeded():
    """Regel 3 der Uebergabe: geseedete Daten werden als geseedet
    ausgewiesen -- auch in dem Text, der im Katalog landet. Nur der Fall,
    in dem `ledger["seeded"]` das tatsaechlich MISST (LEDGER_SEEDED),
    darf diese Behauptung tragen (Review, CRITICAL 1)."""
    wb = RecordingWb()  # kein bestehender Aspekt
    p = [x for x in propose(LEDGER_SEEDED) if x.kind == "enrich_doc"][0]
    assert p.evidence["seeded"] is True  # propose() hat es durchgereicht, nicht erfunden
    apply_proposal(wb, p, now_ms=9)
    _, _, _, value, _ = wb.written[0]
    assert "seeded" in value["description"]


def test_enrich_doc_says_nothing_about_provenance_when_the_ledger_does_not_measure_it():
    """Gegenprobe zum Test oben (Review, CRITICAL 1): `LEDGER` traegt kein
    top-level "seeded" -- die Herkunft ist UNBEKANNT, nicht "nicht
    geseedet". Der geschriebene Text darf dann WEDER "seeded" behaupten
    NOCH das Gegenteil -- er schweigt zur Herkunft. Die beiden Texte
    muessen sich unterscheiden, sonst waere "seeded" nie tatsaechlich aus
    der Evidenz gerendert, sondern weiterhin ein Literal."""
    wb_unknown = RecordingWb()
    wb_seeded = RecordingWb()
    p_unknown = [x for x in propose(LEDGER) if x.kind == "enrich_doc"][0]
    p_seeded = [x for x in propose(LEDGER_SEEDED) if x.kind == "enrich_doc"][0]
    assert p_unknown.evidence["seeded"] is None
    apply_proposal(wb_unknown, p_unknown, now_ms=9)
    apply_proposal(wb_seeded, p_seeded, now_ms=9)
    unknown_text = wb_unknown.written[0][3]["description"]
    seeded_text = wb_seeded.written[0][3]["description"]
    assert "seeded" not in unknown_text
    assert "source: DataHub usage statistics" in unknown_text  # quelle bleibt genannt
    assert unknown_text != seeded_text


def test_enrich_doc_abstains_when_no_last_covered_date_is_measured():
    """Wie mark_dead (Review, IMPORTANT 3): ohne last_covered_ms waere
    die 'last covered'-Aussage im Katalogtext unbelegt -- Enthaltung,
    kein erfundenes Datum, kein deutsches Wort in einem englischen Satz."""
    wb = RecordingWb({("dataset", "urn:c", "editableDatasetProperties"): {
        "value": {"description": "Bestehende Beschreibung."}}})
    p = Proposal(kind="enrich_doc", edge_key="urn:up->urn:c", target_urn="urn:c",
                 aspect="editableDatasetProperties",
                 evidence={"query_urns": ["urn:li:query:q1"], "last_covered_ms": None},
                 state="confirmed", human_summary="kein datum gemessen")
    result = apply_proposal(wb, p, now_ms=9)
    assert isinstance(result, Abstention)
    assert result.kind == "no_measured_last_covered_date"
    assert wb.written == []


def test_enrich_doc_is_idempotent_a_second_run_replaces_not_duplicates():
    """Wie merge_upstreams' Dubletten-Schutz (`if u.get("dataset") not in
    have`), nur fuer den probate-Block in der Beschreibung (Review,
    IMPORTANT 2): eine Korrektur-Runde laeuft wiederholt gegen denselben
    Ledger -- der zweite Lauf ersetzt den ersten probate-Block, haengt
    keinen zweiten an."""
    p = [x for x in propose(LEDGER_SEEDED) if x.kind == "enrich_doc"][0]

    wb = RecordingWb({("dataset", "urn:c", "editableDatasetProperties"): {
        "value": {"description": "Bestehende Beschreibung."}}})
    apply_proposal(wb, p, now_ms=9)
    first_value = wb.written[0][3]

    # Simuliert, was ein echtes GMS nach dem ersten Schreibvorgang
    # zurueckgeben wuerde -- RecordingWb.aspect() aktualisiert `existing`
    # nicht von selbst (siehe dessen Docstring), der Test tut es hier,
    # um den zweiten Lauf gegen den ECHTEN neuen Zustand laufen zu lassen.
    wb.existing[("dataset", "urn:c", "editableDatasetProperties")] = {"value": first_value}
    apply_proposal(wb, p, now_ms=99)
    second_value = wb.written[1][3]

    assert second_value["description"].count("[probate:enrich_doc]") == 1
    assert second_value["description"].startswith("Bestehende Beschreibung.")
    # nicht unbegrenzt gewachsen -- der zweite Lauf ERSETZT den Block,
    # haengt keinen zweiten an (grob: laenge bleibt in derselben Groessenordnung)
    assert len(second_value["description"]) < len(first_value["description"]) * 2


def test_enrich_doc_replaces_an_old_format_probate_block_not_just_the_current_tag():
    """Review, Fixrunde 2, IMPORTANT: der Detektor erkannte urspruenglich
    nur `_ENRICH_DOC_TAG` -- ein Block im literalen VORHER-Format
    ("probate: observed usage...", ohne Tag, exakt das, was dieser
    Task-13-Fix selbst ersetzt hat) waere fuer ihn unsichtbar gewesen,
    haette als menschlicher Text gegolten, und ein zweiter Block waere
    darunter angehaengt worden. Belegt die Gegenprobe: ein bestehendes
    Alt-Format-Feld wird ERSETZT, nicht dupliziert."""
    old_format_block = (
        "probate: observed usage from urn:li:dataset:(urn:li:dataPlatform:postgres,"
        "old_upstream,PROD) in 3 measured queries, last covered 2026-01-01 "
        "(source: DataHub usage statistics, seeded data)."
    )
    wb = RecordingWb({("dataset", "urn:c", "editableDatasetProperties"): {
        "value": {"description": f"Bestehende Beschreibung.\n\n{old_format_block}"}}})
    p = [x for x in propose(LEDGER_SEEDED) if x.kind == "enrich_doc"][0]
    apply_proposal(wb, p, now_ms=9)
    _, _, _, value, _ = wb.written[0]
    desc = value["description"]
    assert desc.startswith("Bestehende Beschreibung.")
    assert "old_upstream" not in desc            # alter block ist WEG, nicht nur ergaenzt
    assert desc.count("probate:") == 1            # kein zweiter block daneben
    assert desc.count("observed usage from") == 1


def test_apply_proposal_refuses_to_write_an_enrich_doc_with_vacuous_evidence():
    wb = RecordingWb({("dataset", "urn:c", "editableDatasetProperties"): {
        "value": {"description": "Bestehende Beschreibung."}}})
    p = Proposal(kind="enrich_doc", edge_key="urn:up->urn:c", target_urn="urn:c",
                 aspect="editableDatasetProperties", evidence={}, state="confirmed",
                 human_summary="leer")
    try:
        apply_proposal(wb, p, now_ms=9)
        assert False, "haette werfen muessen"
    except ValueError:
        pass
    assert wb.written == []


def test_remove_edge_drops_exactly_one_upstream_and_keeps_the_rest():
    wb = RecordingWb({("dataset", "urn:d", "upstreamLineage"): {"value": {"upstreams": [
        {"dataset": "urn:a", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}},
        {"dataset": "urn:b", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}}]}}})
    remove_edge(wb, upstream="urn:a", downstream="urn:d", now_ms=9)
    _, urn, aspect, value, _ = wb.written[0]
    assert urn == "urn:d"
    assert aspect == "upstreamLineage"
    assert [u["dataset"] for u in value["upstreams"]] == ["urn:b"]


def test_remove_edge_refuses_on_a_dataset_with_no_lineage_aspect_at_all():
    """Review, IMPORTANT 4 -- korrigiert die vorherige Fassung dieses
    Tests, die den Fehlschlag als beabsichtigtes Verhalten kodierte:
    `merge_upstreams(None, drop=[...])` haette ein leeres
    `{"upstreams": []}` GESCHRIEBEN -- eine nie gemessene Behauptung
    "keine Upstreams", nur weil eine Kante entfernt werden sollte, die es
    dort nie gab. Wie `mark_dead` (Task 12) verweigert remove_edge das
    jetzt laut, bevor irgendetwas geschrieben wird."""
    wb = RecordingWb({})
    try:
        remove_edge(wb, upstream="urn:a", downstream="urn:ohne-lineage", now_ms=9)
        assert False, "haette werfen muessen"
    except ValueError:
        pass
    assert wb.written == []


def test_remove_edge_refuses_when_the_upstream_was_never_declared():
    """Review, IMPORTANT 4, zweiter Fehlschlag: der Aspekt existiert,
    aber der zu entfernende Upstream steht nicht drin -- ohne Sperre
    schriebe merge_upstreams die IDENTISCHE Liste zurueck, applied=True,
    ohne jedes Signal, dass nichts passiert ist."""
    wb = RecordingWb({("dataset", "urn:d", "upstreamLineage"): {"value": {"upstreams": [
        {"dataset": "urn:someone_else", "type": "TRANSFORMED",
         "auditStamp": {"time": 1, "actor": "x"}}]}}})
    try:
        remove_edge(wb, upstream="urn:a", downstream="urn:d", now_ms=9)
        assert False, "haette werfen muessen"
    except ValueError:
        pass
    assert wb.written == []


def test_an_unknown_proposal_kind_is_loud():
    import pytest
    with pytest.raises(ValueError):
        apply_proposal(RecordingWb(), Proposal("erfunden", "a->b", "b", "x", {}, "state", ""))
