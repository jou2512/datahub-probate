"""Der Demo-Katalog wird geplant, bevor er geschrieben wird -- und der
Plan ist reine Datenstruktur (`harness/seed_demo_catalog.build_plan`).
Genau deshalb ist er ohne GMS pruefbar, und genau das wird hier getan.

Der wichtigste Test dieser Datei ist `test_expected_state_matches_the_real
_classifier`: die Erwartung im Manifest darf nicht aus einer zweiten,
handgeschriebenen Regel stammen, die neben `probate/ledger.py::
classify_edges` herlaeuft und irgendwann auseinanderdriftet. Sie wird
deshalb gegen den ECHTEN Klassifikator gehalten -- fuer jede Kombination
aus Paar-Query, Bucket-Profil und `queries_seen`.

Kein Mock-Rahmenwerk (global-constraints.md): handgeschriebene Fakes.
"""

from __future__ import annotations

import pytest

from harness import seed_demo_catalog as seed
from probate.ledger import (
    Bucket,
    Timeline,
    classify_edges,
    coverage_from_buckets,
)
from probate.judge import _strip_disclosure_prefix
from ui.console_api import split_urn

SIZES = seed.SMOKE_SIZES


@pytest.fixture(scope="module")
def plan():
    return seed.build_plan(SIZES, seed=20260807)


# --- Plan-Grundeigenschaften ---------------------------------------------


def test_plan_is_deterministic():
    """Ohne das waere eine Wiederholungsmessung keine Wiederholung."""
    a = seed.build_plan(SIZES, seed=99)
    b = seed.build_plan(SIZES, seed=99)
    assert [d.urn for d in a.datasets] == [d.urn for d in b.datasets]
    assert [(e.upstream, e.downstream, e.expected_state) for e in a.edges] == \
           [(e.upstream, e.downstream, e.expected_state) for e in b.edges]
    assert [q["urn"] for q in a.queries] == [q["urn"] for q in b.queries]


def test_different_seed_gives_a_different_catalog():
    a = seed.build_plan(SIZES, seed=1)
    b = seed.build_plan(SIZES, seed=2)
    assert [d.urn for d in a.datasets] != [d.urn for d in b.datasets]


def test_all_four_states_are_planned(plan):
    states = {e.expected_state for e in plan.edges}
    assert states == {"confirmed", "dead", "missing", "unknown"}


def test_distribution_is_not_uniform(plan):
    """Eine Demo, in der alle vier Zustaende zu je 25 % vorkommen, sieht
    gestellt aus -- `confirmed` muss klar ueberwiegen, `missing` klar
    selten sein (Auftrag: 'realistisch, nicht gleichverteilt')."""
    total = len(plan.edges)
    counts = {s: sum(1 for e in plan.edges if e.expected_state == s)
              for s in ("confirmed", "dead", "missing", "unknown")}
    assert counts["confirmed"] / total > 0.40
    assert counts["missing"] / total < 0.12
    assert counts["unknown"] / total > 0.15


def test_urns_are_unique(plan):
    urns = [d.urn for d in plan.datasets]
    assert len(urns) == len(set(urns))


def test_edges_are_unique(plan):
    keys = [(e.upstream, e.downstream) for e in plan.edges]
    assert len(keys) == len(set(keys))


def test_several_platforms_and_databases(plan):
    """Ein Plattform-Filter ueber einer einzigen Plattform filtert nichts."""
    assert len({d.platform for d in plan.datasets}) >= 4
    assert len({d.database for d in plan.datasets}) >= 5
    assert len({d.schema for d in plan.datasets}) >= 4


# --- Die zwei Regeln, die maschinell erzwungen sind -----------------------


def test_no_identifier_reveals_the_verdict(plan):
    for d in plan.datasets:
        low = d.table.lower()
        for tok in seed.FORBIDDEN_NAME_TOKENS:
            assert tok not in low, f"{d.table} enthaelt {tok!r}"
    for q in plan.queries:
        low = q["urn"].lower().replace(seed.NAMESPACE_PREFIX, "")
        for tok in seed.FORBIDDEN_NAME_TOKENS:
            assert tok not in low, f"{q['urn']} enthaelt {tok!r}"


def test_name_guard_actually_fires():
    """Eine Wache, die nie ausloest, ist keine Wache."""
    bad = seed.Plan(datasets=[seed.DatasetSpec(
        urn="urn:li:dataset:(urn:li:dataPlatform:postgres,x.y.dead_upstream,PROD)",
        platform="postgres", database="x", schema="y", table="dead_upstream",
        domain="finance", layer="raw", description="")])
    with pytest.raises(ValueError, match="verraten den Zustand"):
        seed._assert_names_are_clean(bad)


def test_no_pair_query_between_two_focuses(plan):
    """Die Ko-Okkurrenz ist ungerichtet. Waere ein Paar-Partner selbst ein
    Fokus, entstuende zu JEDER bestaetigten Kante eine gespiegelte
    `missing`-Kante -- der teuerste stille Fehler dieses Katalogs."""
    focuses = set(plan.focuses)
    for q in plan.queries:
        a, b = q["subjects"]
        assert not (a in focuses and b in focuses), q["urn"]


def test_query_urns_are_unique(plan):
    urns = [q["urn"] for q in plan.queries]
    assert len(urns) == len(set(urns))


def test_duplicate_query_guard_fires():
    dupe = seed.Plan(queries=[{"urn": "urn:li:query:a", "subjects": ["x", "y"]},
                              {"urn": "urn:li:query:a", "subjects": ["x", "z"]}])
    with pytest.raises(ValueError, match="doppelte Query-URNs"):
        seed._assert_no_duplicate_queries(dupe)


# --- Offenlegung ----------------------------------------------------------


def test_every_description_carries_the_disclosure(plan):
    for d in plan.datasets:
        assert d.description.startswith(seed.DESC_PREFIX)


def test_disclosure_is_not_part_of_the_citable_corpus(plan):
    """`probate/judge.py` schneidet einen fuehrenden `[...]`-Block aus dem
    Text, den ein Modellzitat treffen darf. Der Praefix hier hat GENAU
    diese Form -- sonst koennte das Modell die Offenlegung zitieren und
    formal 'belegt' urteilen (Entscheid vom 07.08.)."""
    for d in plan.datasets[:20]:
        citable = _strip_disclosure_prefix(d.description)
        assert seed.DESC_PREFIX not in citable
        assert "probate-demo" not in citable
        assert citable.strip()


def test_every_database_is_marked_as_seeded(plan):
    for d in plan.datasets:
        assert d.database.startswith(seed.NAMESPACE_PREFIX + "_")


# --- Die Konsole muss die URNs zerlegen koennen ---------------------------


def test_urns_split_into_platform_database_schema_table(plan):
    for d in plan.datasets[:30]:
        parts = split_urn(d.urn)
        assert parts["platform"] == d.platform
        assert parts["database"] == d.database
        assert parts["schema"] == d.schema
        assert parts["table"] == d.table


# --- Erwartung gegen den echten Klassifikator -----------------------------


def _classify_once(pair_query: bool, usage_profile: str, focus_has_query: bool) -> str:
    """Eine einzelne deklarierte Kante durch den ECHTEN
    `classify_edges` schicken -- mit genau den Daten, die der Seeder fuer
    diese Kombination anlegen wuerde."""
    import random

    focus, target = "urn:li:dataset:(a,b.c,PROD)", "urn:li:dataset:(a,b.d,PROD)"
    buckets = tuple(Bucket(ts, total, uniq) for ts, total, uniq
                    in seed.USAGE_PROFILES[usage_profile](random.Random(1)))
    cov = coverage_from_buckets(buckets, window_start_ms=0, window_end_ms=10**13)
    verdicts = classify_edges(
        focus=focus,
        declared={target},
        cooccurred={target: ["urn:li:query:pair"]} if pair_query else {},
        coverage_by_urn={target: cov},
        timeline_by_urn={target: Timeline(buckets)},
        now_ms=seed.days_ago_ms(0),
        queries_seen=1 if focus_has_query else 0,
    )
    return next(v.state for v in verdicts if v.edge.downstream == target)


@pytest.mark.parametrize("pair_query", [True, False])
@pytest.mark.parametrize("usage_profile", ["fresh", "traffic", "zero", "none"])
@pytest.mark.parametrize("focus_has_query", [True, False])
def test_expected_state_matches_the_real_classifier(pair_query, usage_profile,
                                                    focus_has_query):
    """Die Erwartung des Manifests darf keine zweite, danebenlaufende
    Regel sein. Eine Paar-Query impliziert `queries_seen > 0` -- die
    Kombination (Paar-Query, aber Query-Quelle leer) ist keine mogliche
    Welt und wird uebersprungen."""
    if pair_query and not focus_has_query:
        pytest.skip("Paar-Query ohne Query-Quelle ist keine mogliche Welt")
    want = seed._expected_state(pair_query, usage_profile, focus_has_query, True)
    assert want == _classify_once(pair_query, usage_profile, focus_has_query)


def test_undeclared_edge_is_missing():
    assert seed._expected_state(True, "fresh", True, False) == "missing"


# --- Bucket-Profile -------------------------------------------------------


def test_zero_profile_has_windows_but_no_traffic():
    """'Gemessene Null' und 'nicht gemessen' duerfen nie dasselbe sein --
    das ist die Null-Regel der Spezifikation, hier in den Daten."""
    import random

    zero = seed.USAGE_PROFILES["zero"](random.Random(1))
    assert len(zero) >= 3
    assert sum(total for _, total, _ in zero) == 0
    assert seed.USAGE_PROFILES["none"](random.Random(1)) == []


def test_all_buckets_are_inside_the_classifier_window():
    """Ein Bucket ausserhalb der 32 Tage, die `probate/ledger.py` abfragt,
    waere verschwendete Schreibzeit -- und schlimmer: er wuerde in der
    Rueckluse gezaehlt, aber nie klassifiziert."""
    import random

    from probate.ledger import USAGE_WINDOW_DAYS

    oldest_allowed = seed.days_ago_ms(USAGE_WINDOW_DAYS - 1)
    for name, fn in seed.USAGE_PROFILES.items():
        for ts, _, _ in fn(random.Random(3)):
            assert ts >= oldest_allowed, f"{name}: Bucket ausserhalb des Fensters"


def test_only_targets_carry_usage(plan):
    """Nutzungsfenster kosten Schreibzeit. Der Klassifikator liest sie
    ausschliesslich am ZIEL einer Kante -- an einem Fokus waeren sie
    bezahlt und ungelesen."""
    targets = {e.downstream for e in plan.edges}
    for d in plan.datasets:
        if d.usage:
            assert d.urn in targets, f"{d.urn} traegt Buckets, ist aber kein Ziel"


# --- Zusammenfassung ------------------------------------------------------


def test_plan_summary_counts_match(plan):
    s = seed.plan_summary(plan)
    assert s["datasets"] == len(plan.datasets)
    assert s["edges"] == len(plan.edges)
    assert s["declared_edges"] == sum(1 for e in plan.edges if e.declared)
    assert s["usage_buckets"] == sum(len(d.usage) for d in plan.datasets)
    assert sum(s["expected_states"].values()) == len(plan.edges)


def test_full_scale_reaches_enterprise_size():
    """Der Auftrag verlangt mehrere hundert GEPRUEFTE Kanten -- bei vier
    Zeilen hat kein Filter einen Grund zu existieren."""
    s = seed.plan_summary(seed.build_plan(seed.FULL_SIZES))
    assert s["datasets"] >= 500
    assert s["edges"] >= 400
    assert len(s["platforms"]) >= 4
    assert len(s["databases"]) >= 5
