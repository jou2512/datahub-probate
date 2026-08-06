"""Der Proxy existiert wegen CORS und weil die Knoepfe Python sind
(docs/entscheidungen/2026-08-07-ui-stack-werkbank.md). Getestet wird die
Wegewahl, nicht der Socket."""

import pytest
from ui.serve import ACTIONS, PORT_DEFAULT, route


def test_the_port_is_never_one_of_the_taken_ones():
    """8080 ist Joels WhatsApp-Bridge, 8081 gibt es gar nicht,
    18080 traegt showcase-ecommerce."""
    assert PORT_DEFAULT == 8899


def test_mode_endpoint_answers_live_because_the_proxy_only_runs_live():
    assert route("GET", "/api/mode", {}) == ("mode", {})


def test_ledger_endpoint_is_routed():
    assert route("GET", "/api/ledger", {}) == ("ledger", {})


def test_log_endpoint_passes_the_since_cursor_through():
    assert route("GET", "/api/log", {"since": ["12"]}) == ("log", {"since": 12})


def test_every_one_of_the_six_buttons_has_an_action():
    assert set(ACTIONS) == {"seed-query", "add-edge", "remove-edge",
                            "cut-warehouse", "fast-forward", "run-ledger"}


def test_an_unknown_action_is_rejected_instead_of_silently_ignored():
    with pytest.raises(KeyError):
        route("POST", "/api/action/erfunden", {})


def test_a_get_on_an_action_path_is_not_a_write():
    """Schreiben nur per POST -- ein versehentlicher Seitenaufruf darf
    nichts veraendern."""
    with pytest.raises(ValueError):
        route("GET", "/api/action/add-edge", {})
