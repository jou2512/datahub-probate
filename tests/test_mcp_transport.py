"""Der MCP-Weg -- offline, ohne Server, ohne Netz.

Die Naht ist `ToolCaller`: eine ganz normale Funktion `(tool, args) -> JSON`.
Genau deshalb existiert sie. Alles, was hier geprueft wird, ist die
Uebersetzung einer `get_dataset_queries`-Antwort in den Vertrag von
`fetch_cooccurrence` -- und vor allem: dass eine kaputte oder
unvollstaendige Antwort LAUT scheitert statt eine leere Karte
zurueckzugeben. Eine leere Ko-Okkurrenz heisst "keine gemeinsame Query
gefunden" und wuerde eine `missing`-Kante verschwinden lassen; sie darf
nie aus einem Fehlschlag entstehen (.claude/rules/verification.md).

Die LIVE-Messung gegen einen echten Server steht nicht hier, sondern in
`harness/mcp_probe.py` -> `harness/runs/mcp-probe.json`. Ein Test, der
einen 20-Sekunden-Unterprozess hochfaehrt, waere kein Test mehr.
"""

import pytest

from probate.mcp_transport import (
    DEFAULT_QUERY_COUNT,
    McpError,
    McpSession,
    cooccurrence_from_mcp,
    make_cooccurrence_fetcher,
)

FOCUS = "urn:li:dataset:(urn:li:dataPlatform:postgres,ns.a,PROD)"
OTHER = "urn:li:dataset:(urn:li:dataPlatform:postgres,ns.b,PROD)"
THIRD = "urn:li:dataset:(urn:li:dataPlatform:postgres,ns.c,PROD)"


def caller(payload, record=None):
    def call(tool, args):
        if record is not None:
            record.append((tool, args))
        return payload
    return call


def test_maps_every_other_subject_to_the_query_that_proves_it():
    """Der Beleg ist die Query-URN. Eine Ko-Okkurrenz ohne sie waere eine
    Behauptung ueber eine Kante ohne das Artefakt, das sie stuetzt."""
    cooc, total = cooccurrence_from_mcp(caller({
        "total": 1,
        "queries": [{"urn": "urn:li:query:q1", "subjects": [FOCUS, OTHER]}],
    }), FOCUS)
    assert cooc == {OTHER: ["urn:li:query:q1"]}
    assert total == 1


def test_never_reports_the_focus_dataset_as_its_own_consumer():
    cooc, total = cooccurrence_from_mcp(caller({
        "total": 1,
        "queries": [{"urn": "urn:li:query:q1", "subjects": [FOCUS]}],
    }), FOCUS)
    assert cooc == {}
    assert total == 1


def test_collects_every_query_that_touches_the_same_target():
    cooc, _ = cooccurrence_from_mcp(caller({
        "total": 2,
        "queries": [
            {"urn": "urn:li:query:q1", "subjects": [FOCUS, OTHER]},
            {"urn": "urn:li:query:q2", "subjects": [FOCUS, OTHER, THIRD]},
        ],
    }), FOCUS)
    assert cooc == {
        OTHER: ["urn:li:query:q1", "urn:li:query:q2"],
        THIRD: ["urn:li:query:q2"],
    }


def test_empty_query_list_is_an_answer_not_an_error():
    """'gefragt und nichts gefunden' ist ein legitimes Ergebnis -- der
    dead- und der unknown-Fall des Labors sehen genau so aus."""
    cooc, total = cooccurrence_from_mcp(caller({"total": 0, "queries": []}), FOCUS)
    assert cooc == {}
    assert total == 0


def test_missing_queries_key_is_treated_as_empty_not_as_a_crash():
    cooc, total = cooccurrence_from_mcp(caller({"total": 0}), FOCUS)
    assert (cooc, total) == ({}, 0)


def test_truncated_page_raises_instead_of_claiming_completeness():
    """`get_dataset_queries` paginiert. Wenn `total` groesser ist als die
    Zahl gelieferter Queries, fehlen Belege -- die Karte waere still
    unvollstaendig und saehe trotzdem vollstaendig aus."""
    with pytest.raises(McpError, match="total=350"):
        cooccurrence_from_mcp(caller({
            "total": 350,
            "queries": [{"urn": f"urn:li:query:q{i}", "subjects": [FOCUS, OTHER]}
                        for i in range(200)],
        }), FOCUS)


def test_response_without_total_raises_because_queries_seen_would_be_guessed():
    with pytest.raises(McpError, match="ohne 'total'"):
        cooccurrence_from_mcp(caller({"queries": []}), FOCUS)


def test_non_object_response_raises():
    with pytest.raises(McpError, match="erwartet ein Objekt"):
        cooccurrence_from_mcp(caller(["nope"]), FOCUS)


def test_query_entry_without_urn_raises_because_the_evidence_would_be_missing():
    with pytest.raises(McpError, match="ohne 'urn'"):
        cooccurrence_from_mcp(caller({
            "total": 1, "queries": [{"subjects": [FOCUS, OTHER]}]}), FOCUS)


def test_subject_that_is_not_a_string_raises_instead_of_being_skipped():
    """Der Server dedupliziert `subjects` selbst auf flache Dataset-URNs
    (`_deduplicate_subjects`). Aendert sich das Format, waere stilles
    Ueberspringen eine leise Unterzaehlung von Kanten -- also lieber laut."""
    with pytest.raises(McpError, match="statt einer URN"):
        cooccurrence_from_mcp(caller({
            "total": 1,
            "queries": [{"urn": "urn:li:query:q1",
                         "subjects": [{"dataset": {"urn": OTHER}}]}],
        }), FOCUS)


def test_count_is_passed_through_to_the_tool_call():
    """Muss mit dem count der GraphQL-Suche (200) uebereinstimmen, sonst
    vergleicht der Doppellauf zwei verschieden tief geschoepfte Mengen."""
    seen = []
    cooccurrence_from_mcp(caller({"total": 0, "queries": []}, seen), FOCUS)
    assert seen == [("get_dataset_queries", {"urn": FOCUS, "count": DEFAULT_QUERY_COUNT})]


# --- Adapter auf die fetch_cooccurrence-Signatur -------------------------

class _CountingStub:
    def __init__(self):
        self.calls = 0


def test_fetcher_matches_fetch_cooccurrence_signature_and_counts_the_round_trip():
    """Ein MCP-Werkzeugaufruf ist ein Netz-Rundlauf wie jeder andere. Ein
    Lauf-Artefakt, das ihn nicht zaehlt, laesst den MCP-Weg guenstiger
    aussehen, als er ist."""
    fetch = make_cooccurrence_fetcher(caller({
        "total": 1,
        "queries": [{"urn": "urn:li:query:q1", "subjects": [FOCUS, OTHER]}],
    }))
    counting = _CountingStub()
    cooc, total = fetch(counting, FOCUS)
    assert cooc == {OTHER: ["urn:li:query:q1"]}
    assert total == 1
    assert counting.calls == 1


def test_fetcher_works_with_a_gms_object_that_has_no_call_counter():
    fetch = make_cooccurrence_fetcher(caller({"total": 0, "queries": []}))
    assert fetch(object(), FOCUS) == ({}, 0)


def test_fetcher_is_labelled_so_the_artifact_can_say_which_way_it_came():
    fetch = make_cooccurrence_fetcher(caller({"total": 0, "queries": []}))
    assert fetch.source_name == "mcp"


def test_a_failing_tool_call_propagates_and_never_becomes_an_empty_map():
    """Der Kern der ganzen Datei: ein Fehlschlag darf nicht wie 'keine
    gemeinsame Query gefunden' aussehen -- das wuerde eine missing-Kante
    stillschweigend loeschen."""
    def boom(tool, args):
        raise McpError("Verbindung weg")

    fetch = make_cooccurrence_fetcher(boom)
    with pytest.raises(McpError):
        fetch(_CountingStub(), FOCUS)


# --- Sitzungs-Konfiguration (ohne Prozessstart) --------------------------

def test_session_pins_the_version_and_the_interpreter_in_its_argv():
    """`@latest` ist kein Pin -- verschiedene Versionen registrieren
    verschiedene Werkzeugmengen. Und `python` ist auf dieser Maschine ein
    3.9-Alias: mcp-server-datahub >= 0.5.0 verlangt laut PyPI-Metadaten
    Python >= 3.11, 0.4.0 nur >= 3.10 -- ohne Interpreter-Pin kann uv
    also lautlos auf der aelteren Werkzeugmenge landen."""
    argv = McpSession("http://localhost:28080", version="0.6.0").server_argv()
    assert argv[:5] == ["uvx", "--python", "3.11", "--from",
                        "mcp-server-datahub==0.6.0"]
    assert "--transport" in argv and "stdio" in argv
    assert not any("latest" in a for a in argv)


def test_session_env_defaults_to_read_only_and_targets_the_given_gms():
    env = McpSession("http://localhost:28080").server_env()
    assert env["DATAHUB_GMS_URL"] == "http://localhost:28080"
    assert env["TOOLS_IS_MUTATION_ENABLED"] == "false"
    assert "DATAHUB_GMS_TOKEN" not in env


def test_session_env_enables_mutations_only_when_asked():
    env = McpSession("http://localhost:28080", mutation_enabled=True).server_env()
    assert env["TOOLS_IS_MUTATION_ENABLED"] == "true"


def test_session_env_passes_the_token_through_when_one_is_given():
    env = McpSession("http://localhost:28080", token="pat123").server_env()
    assert env["DATAHUB_GMS_TOKEN"] == "pat123"


def test_calling_a_tool_without_an_open_session_raises():
    with pytest.raises(McpError, match="nicht offen"):
        McpSession("http://localhost:28080").call_tool("search", {})
