"""combine_runs() ist die einzige Stelle, die vier Einzel-Laeufe von
probate.ledger.run() zu einem Register zusammenfuegt (harness/record_ledger.py).
Getestet wird mit handgeschriebenen Fake-run()-Ausgaben, nicht gegen GMS --
das eigentliche Aufzeichnen ist ein Live-Lauf, keine Unit-Logik
(global-constraints.md: "Kein Mock-Rahmenwerk -- handgeschriebene Fakes")."""

from harness.record_ledger import FOCUSES, combine_runs


def _run(focus, state, buckets_seen=3, days_span=2, thin=True,
         api_calls=4, queries_seen=1, generated_at_ms=1000):
    """Baut einen Fake-run()-Rueckgabewert mit genau einer Kante -- reicht,
    um Kombinationslogik zu pruefen, ohne probate.ledger.run() nachzubauen."""
    edge = {
        "edge": f"{focus}->target-for-{state}",
        "upstream": focus,
        "downstream": f"target-for-{state}",
        "state": state,
        "evidence": {"source": "fake"},
        "coverage": {"buckets_seen": buckets_seen},
        "timeline": {"series": []},
    }
    return {
        "focus": focus,
        "gms": "http://localhost:28080",
        "seeded": True,
        "generated_at_ms": generated_at_ms,
        "edges_total": 1,
        "edges_confirmed": 1 if state == "confirmed" else 0,
        "edges_dead": 1 if state == "dead" else 0,
        "edges_missing": 1 if state == "missing" else 0,
        "edges_unknown": 1 if state == "unknown" else 0,
        "coverage_buckets_seen": buckets_seen,
        "coverage_days_span": days_span,
        "coverage_thin": thin,
        "api_calls": api_calls,
        "queries_seen": queries_seen,
        "edges": [edge],
    }


def test_four_runs_combine_into_one_edge_per_state():
    runs = [
        _run(FOCUSES[0], "confirmed"),
        _run(FOCUSES[1], "dead"),
        _run(FOCUSES[2], "missing"),
        _run(FOCUSES[3], "unknown"),
    ]
    out = combine_runs(runs)
    states = sorted(e["state"] for e in out["edges"])
    assert states == ["confirmed", "dead", "missing", "unknown"]
    assert out["edges_total"] == 4
    assert out["edges_confirmed"] == 1
    assert out["edges_dead"] == 1
    assert out["edges_missing"] == 1
    assert out["edges_unknown"] == 1


def test_combining_never_touches_a_single_edge_dict():
    """Die Kombination ist ein Concat, keine zweite Klassifikation -- jede
    Kante muss danach byte-identisch mit dem sein, was ihr EIGENER run()
    geliefert hat."""
    runs = [_run(FOCUSES[0], "confirmed"), _run(FOCUSES[1], "dead")]
    out = combine_runs(runs)
    expected = [e for r in runs for e in r["edges"]]
    assert out["edges"] == expected


def test_counts_are_recomputed_from_the_combined_edges_not_summed_blind():
    """Ein Zaehler, der stur aus den Einzel-Laeufen summiert wird, koennte
    driften, sobald irgendwo eine Kante doppelt vorkaeme. Die Zaehlung
    zaehlt die tatsaechliche kombinierte edges-Liste."""
    runs = [_run(FOCUSES[0], "confirmed"), _run(FOCUSES[1], "dead")]
    out = combine_runs(runs)
    assert out["edges_confirmed"] == sum(1 for e in out["edges"] if e["state"] == "confirmed")
    assert out["edges_dead"] == sum(1 for e in out["edges"] if e["state"] == "dead")


def test_bucket_and_call_counters_sum_across_runs():
    runs = [
        _run(FOCUSES[0], "confirmed", buckets_seen=3, api_calls=4, queries_seen=1),
        _run(FOCUSES[1], "dead", buckets_seen=31, api_calls=5, queries_seen=0),
    ]
    out = combine_runs(runs)
    assert out["coverage_buckets_seen"] == 34
    assert out["api_calls"] == 9
    assert out["queries_seen"] == 1


def test_days_span_takes_the_widest_of_the_four_windows_not_the_sum():
    runs = [
        _run(FOCUSES[0], "confirmed", days_span=2),
        _run(FOCUSES[1], "dead", days_span=30),
    ]
    out = combine_runs(runs)
    assert out["coverage_days_span"] == 30


def test_thin_coverage_is_honest_if_any_single_run_was_thin():
    thin = _run(FOCUSES[0], "confirmed", thin=True)
    covered = _run(FOCUSES[1], "dead", thin=False)
    assert combine_runs([thin, covered])["coverage_thin"] is True
    assert combine_runs([covered, covered])["coverage_thin"] is False


def test_the_artifact_is_marked_seeded_and_carries_every_run_timestamp():
    """Der Controller-Auftrag verlangt eine ehrliche Markierung, dass dies
    eine Aufzeichnung echter Laeufe gegen Seed-Daten ist, keine Live-Sicht."""
    runs = [_run(FOCUSES[0], "confirmed", generated_at_ms=111),
            _run(FOCUSES[1], "dead", generated_at_ms=222)]
    out = combine_runs(runs)
    assert out["seeded"] is True
    assert out["recorded_runs_at_ms"] == [111, 222]
    assert out["focuses"] == [FOCUSES[0], FOCUSES[1]]


def test_focuses_list_matches_the_four_seedlab_pairs():
    """FOCUSES muss auf die tatsaechlichen Manifest-URNs zeigen, sonst
    zeichnet das Skript vier beliebige, nicht die vier praeparierten
    Zustaende auf (examples/seedlab-manifest.json)."""
    import json
    from pathlib import Path
    manifest = json.loads(Path("examples/seedlab-manifest.json").read_text(encoding="utf-8"))
    manifest_upstreams = {e["upstream_urn"] for e in manifest["edges"]}
    assert set(FOCUSES) == manifest_upstreams
