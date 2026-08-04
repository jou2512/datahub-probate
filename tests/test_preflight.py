from harness.preflight import ProbeResult, summarise


def test_summarise_counts_failures():
    results = [
        ProbeResult("linkAssetVersion", True, "urn:li:versionSet:x"),
        ProbeResult("raiseIncident", False, "HTTP 400"),
    ]
    summary = summarise(results)
    assert summary["total"] == 2
    assert summary["ok"] == 1
    assert summary["failed"] == ["raiseIncident"]
    assert summary["gate_passed"] is False


def test_gate_passes_only_when_all_ok():
    results = [ProbeResult("a", True, ""), ProbeResult("b", True, "")]
    assert summarise(results)["gate_passed"] is True
