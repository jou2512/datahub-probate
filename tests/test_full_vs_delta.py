"""Testet harness/full_vs_delta.py -- die Zusatzfrage der Spec: Vollabgleich
gegen Tagesdelta, beides gemessen gegen denselben geseedeten Katalog.

Handgeschriebene Fakes (kein Mock-Rahmenwerk, wie tests/test_loadtest.py).
Diese Datei ruehrt weder probate/ledger.py noch harness/loadtest.py noch
harness/loadgen.py an -- alle drei sind laut Auftrag aktive Fahrspuren
anderer Aufgaben in diesem Lauf (git status zeigt probate/ledger.py bereits
modifiziert, als dieser Task begann).
"""

from __future__ import annotations

import json

from harness.full_vs_delta import (
    CHANGE_FRACTION,
    _delta_targets,
    compare_full_vs_delta,
)


class CountingGms:
    """Deterministisch, schnell -- reine Struktur-Tests, keine echte
    Netzwerk-Latenz. `statsSummary` liefert immer einen Wert > 0, damit
    keine Kante als 'suspicious' markiert wird und detail_pass ueberall
    mit einer leeren Stichprobe durchlaeuft (kein Import von
    probate.ledger.fetch_cooccurrence noetig)."""

    def __init__(self):
        self.calls = 0

    def graphql(self, q, v=None):
        self.calls += 1
        return {"dataset": {"statsSummary": {"queryCountLast30Days": 5}},
                "searchAcrossEntities": {"total": 0, "searchResults": []}}

    def get_aspect(self, *a):
        self.calls += 1
        return None


# --- _delta_targets() -- die Auswahl -------------------------------------

def test_delta_targets_is_a_fixed_fraction_of_the_catalog_tail():
    from harness.loadgen import plan
    p = plan("s")
    out = _delta_targets("s")
    n = max(1, round(len(p["datasets"]) * CHANGE_FRACTION))
    assert out == p["datasets"][-n:]
    assert len(out) < len(p["datasets"])


# --- compare_full_vs_delta() -- die Zusatzfrage --------------------------

def test_the_delta_pass_touches_strictly_fewer_datasets_than_the_full_pass():
    out = compare_full_vs_delta(CountingGms(), "s", since_ms=1)
    assert out["delta_datasets"] < out["full_datasets"]


def test_the_speedup_factor_is_reported_as_a_number_not_as_a_word():
    out = compare_full_vs_delta(CountingGms(), "s", since_ms=1)
    assert isinstance(out["full_vs_delta_speedup"], float)


def test_a_missing_since_ms_marker_means_no_baseline_so_delta_equals_full():
    """since_ms falsy (None/0) heisst: kein Marker vom letzten Lauf bekannt
    -- ohne Baseline MUSS ein voller Scan laufen. Das Delta ist dann
    IDENTISCH mit dem Vollabgleich (kein erfundener Vorteil), und der
    Befund wird als 'nicht billiger' ausgewiesen statt versteckt."""
    out = compare_full_vs_delta(CountingGms(), "s", since_ms=0)
    assert "full_vs_delta_verdict" in out
    assert out["delta_datasets"] == out["full_datasets"]
    assert out["full_vs_delta_verdict"] == "delta is NOT cheaper — measured, not assumed (kein since_ms-Marker)"


def test_a_delta_that_is_not_cheaper_is_reported_as_such_instead_of_hidden():
    """Auch mit echtem Marker: wenn die Messung selbst keinen Vorteil
    zeigt (z.B. weil beide Passes im Fake-Fall auf ~0s rauschen), wird das
    benannt statt mit einem erfundenen '>1.0x' ueberdeckt."""
    out = compare_full_vs_delta(CountingGms(), "s", since_ms=1)
    assert "full_vs_delta_verdict" in out
    assert isinstance(out["full_vs_delta_verdict"], str)


def test_the_delta_definition_is_carried_in_the_result_not_just_in_a_docstring():
    """Eine unbenannte Definition macht die Zahl bedeutungslos (Auftrag).
    Die Definition steht deshalb im Messergebnis selbst, nicht nur im
    Moduldocstring."""
    out = compare_full_vs_delta(CountingGms(), "s", since_ms=1)
    assert "delta_definition" in out
    assert "change_fraction" in out
    assert out["change_fraction"] == CHANGE_FRACTION


def test_api_calls_are_counted_separately_for_full_and_delta():
    g = CountingGms()
    out = compare_full_vs_delta(g, "s", since_ms=1)
    assert out["loadtest_s_full_api_calls"] > out["loadtest_s_delta_api_calls"] > 0


# --- run_and_write() -- Merge-Sicherheit zweier Skalen in EINER Datei ----

class FakeGmsFull:
    """Deckt zusaetzlich upsert/delete_aspect/get_aspect ab (fuer
    generate()/cleanup() aus harness.loadgen), damit `run_and_write` end
    to end ohne echtes GMS laufen kann."""

    def __init__(self):
        self.calls = 0

    def graphql(self, q, v=None):
        self.calls += 1
        return {"dataset": {"statsSummary": {"queryCountLast30Days": 5}},
                "searchAcrossEntities": {"total": 0, "searchResults": []}}

    def get_aspect(self, *a):
        self.calls += 1
        return None

    def upsert(self, entity_type, records, sync=True):
        self.calls += 1
        return records

    def delete_aspect(self, *a):
        self.calls += 1


def test_two_scales_merged_into_one_file_do_not_clobber_each_others_numbers(tmp_path):
    """Der Bug, den dieser Test verhindert: `dict.update()` beim Mergen
    zweier `run_and_write()`-Aufrufe (Skala s, dann Skala m) in DIESELBE
    Datei liess bare Schluessel wie 'full_datasets'/'full_vs_delta_speedup'
    der zweiten Skala die der ersten stillschweigend ueberschreiben."""
    from harness.full_vs_delta import run_and_write

    out_path = tmp_path / "full-vs-delta.json"
    run_and_write(FakeGmsFull(), "s", since_ms=1, out_path=out_path)
    run_and_write(FakeGmsFull(), "m", since_ms=1, out_path=out_path)

    merged = json.loads(out_path.read_text(encoding="utf-8"))
    assert "loadtest_s_full_datasets" in merged
    assert "loadtest_m_full_datasets" in merged
    assert merged["loadtest_s_full_datasets"] != merged["loadtest_m_full_datasets"]
    assert "loadtest_s_full_vs_delta_speedup" in merged
    assert "loadtest_m_full_vs_delta_speedup" in merged
    # keine bare (unskalierten) Varianten der ambigen Schluessel im Artefakt
    for key in ("full_datasets", "delta_datasets", "full_vs_delta_speedup",
                "full_vs_delta_verdict", "since_ms"):
        assert key not in merged
