"""Testet den Lasttest-Fixture-Generator (harness/loadgen.py) mit einem
handgeschriebenen Fake (kein Mock-Rahmenwerk, wie tests/test_writeback.py) --
gegen einen echten FakeGms lassen sich Fallen 1 und 12 UND die Ruecklese-
Pflicht der Loeschung erzwingen, ohne die echte Instanz fuer jede
Logikaenderung zu bemuehen. Der Live-Nachweis auf kleiner Stufe passiert
separat (harness/runs/loadgen_smoke.json), nicht hier.
"""

import pytest
from harness.loadgen import NAMESPACE, SCALES, cleanup, dataset_urn, generate, plan, query_urn


class FakeGms:
    def __init__(self, leftover=()):
        self.upserts, self.deleted = [], []
        self.leftover = set(leftover)

    def upsert(self, entity_type, records, sync=True):
        assert isinstance(records, list), "Falle 1: upsert will eine LISTE"
        self.upserts.append((entity_type, len(records)))
        return records

    def delete_aspect(self, t, u, a):
        self.deleted.append((t, u, a))

    def get_aspect(self, t, u, a):
        return {"value": {}} if u in self.leftover else None

    def graphql(self, q, v=None):
        return {"searchAcrossEntities": {"total": 0, "searchResults": []}}


def test_every_generated_urn_sits_under_the_dedicated_namespace():
    """Der Namensraum IST die Aufraeum-Garantie: cleanup muss nicht
    raten, was zum Test gehoerte."""
    assert NAMESPACE in dataset_urn("s", 3)
    assert NAMESPACE in query_urn("s", 3)


def test_the_three_scales_match_the_spec_table():
    assert SCALES == {"s": (50, 1_000), "m": (500, 10_000), "l": (5_000, 100_000)}


def test_the_plan_produces_the_promised_counts():
    p = plan("s")
    assert len(p["datasets"]) == 50
    assert len(p["queries"]) == 1_000


def test_every_query_touches_about_three_tables_like_the_spec_assumes():
    """Spec: '~3 Tabellen je Abfrage'. Wenn die Fixture das nicht
    einhaelt, misst der Lasttest etwas anderes als angenommen."""
    p = plan("s")
    sizes = {len(q["subjects"]) for q in p["queries"]}
    assert sizes == {3}


def test_generation_is_deterministic_for_a_given_scale():
    assert plan("s") == plan("s")


def test_generate_writes_in_batches_not_one_record_at_a_time():
    g = FakeGms()
    out = generate(g, "s", batch=200)
    assert out["seeded"] is True
    assert max(n for _, n in g.upserts) <= 200
    assert out["namespace"] == NAMESPACE


def test_cleanup_reads_back_and_reports_leftovers_instead_of_claiming_success():
    """Eine Loeschung, die niemand nachprueft, ist eine Behauptung."""
    g = FakeGms(leftover={dataset_urn("s", 0)})
    out = cleanup(g, "s")
    assert out["cleanup_verified"] is False
    assert out["cleanup_leftover"] >= 1


def test_cleanup_reports_success_only_when_nothing_reads_back():
    out = cleanup(FakeGms(), "s")
    assert out["cleanup_verified"] is True
    assert out["cleanup_leftover"] == 0


def test_an_unknown_scale_is_loud():
    with pytest.raises(KeyError):
        plan("xxl")
