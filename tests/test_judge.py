"""Tests fuer probate/judge.py -- gather_context.

Warum diese Datei existiert: `text` ist der Korpus, gegen den spaeter ein
Modell-Zitat geprueft wird (Task 9). Diese Tests belegen, dass jedes
lesbare Feld tatsaechlich in `text` landet -- und dass eine fehlende
Antwort (kein Dataset) leer ist, nicht abstuerzt.

Fix-Runde 1 (Review): zwei Luecken behoben.
1. Kein Test belegte, dass ein FEHLGESCHLAGENER Aufruf (`GmsError`) durch
   `gather_context` durchschlaegt statt geschluckt zu werden -- die
   haerteste Regel im Brief ("eine gescheiterte Abfrage ist keine
   Abwesenheit"). Ohne einen solchen Test wuerde ein kuenftiges
   `except Exception: return {}` lautlos durch die Suite rutschen.
2. Nur Alles-vorhanden und Alles-leer waren getestet, keine Teilzustaende
   (leere Owner-Liste bei vorhandenem `ownership`, fehlende/null/leere
   `description`, mehrere Owner/Terms, ein Owner, der zu keinem der
   beiden Inline-Fragmente passt -- der Unions-Fall aus dem Live-Fund).
"""

import json

import pytest

from probate.gms import GmsError
from probate.judge import (
    Judgement,
    JudgeTransportError,
    build_prompt,
    gather_context,
    judge_edge,
)
from probate.ledger import Bucket, Coverage, Edge, EdgeVerdict, Timeline


class FakeGms:
    def __init__(self, data):
        self.data = data
        self.calls = 0

    def graphql(self, query, variables=None):
        self.calls += 1
        return self.data


FULL = {"dataset": {
    "urn": "urn:d",
    "properties": {"name": "fin_year_end", "description": "Jahresabschluss, revisionsrelevant"},
    "ownership": {"owners": [{"owner": {"urn": "urn:li:corpuser:anna"}}]},
    "glossaryTerms": {"terms": [{"term": {"urn": "urn:li:glossaryTerm:SOX"}}]},
    "domain": {"domain": {"properties": {"name": "Finance"}}},
}}


def test_context_collects_every_readable_field():
    c = gather_context(FakeGms(FULL), "urn:d")
    assert c["description"] == "Jahresabschluss, revisionsrelevant"
    assert c["owners"] == ["urn:li:corpuser:anna"]
    assert c["glossary_terms"] == ["urn:li:glossaryTerm:SOX"]
    assert c["domain"] == "Finance"


def test_text_contains_everything_a_quote_could_come_from():
    c = gather_context(FakeGms(FULL), "urn:d")
    for piece in ("fin_year_end", "Jahresabschluss", "anna", "SOX", "Finance"):
        assert piece in c["text"]


def test_a_dataset_without_any_metadata_yields_empty_text_not_a_crash():
    """Leer ist ein Ergebnis: ohne Text gibt es nichts zu zitieren, also
    kein Urteil -- und genau das soll passieren."""
    c = gather_context(FakeGms({"dataset": None}), "urn:d")
    assert c["text"] == ""
    assert c["owners"] == []


# --- IMPORTANT 1: ein Fehlschlag ist keine Abwesenheit --------------------
#
# `gms.graphql` wirft `GmsError` fuer zwei Faelle, die beide durch
# `gather_context` durchschlagen muessen, nicht als leeres Ergebnis
# ankommen duerfen: einen Transport-/HTTP-Fehlschlag und einen
# GraphQL-Fehler im `errors`-Feld bei HTTP 200 (Falle 2). Der Fake
# reproduziert genau das, was `Gms.graphql` in beiden Faellen wirft --
# `gather_context` selbst hat keinen eigenen try/except und darf keins
# bekommen.

class FakeGmsHttpFailure:
    """Simuliert einen Transport-Fehlschlag (z.B. HTTP 500)."""

    def graphql(self, query, variables=None):
        raise GmsError("GraphQL HTTP 500: internal error")


class FakeGmsBodyErrors:
    """Simuliert HTTP 200 mit Fehlern im `errors`-Feld (Falle 2) -- genau
    die Form, in der `Gms.graphql` GraphQL-Validierungsfehler wirft."""

    def graphql(self, query, variables=None):
        raise GmsError(
            'GraphQL meldet Fehler: [{"message": "Validation error"}]'
        )


def test_a_failed_fetch_raises_and_is_not_swallowed():
    with pytest.raises(GmsError, match="HTTP 500"):
        gather_context(FakeGmsHttpFailure(), "urn:d")


def test_graphql_errors_with_http_200_also_propagate_unmodified():
    """Belegt, dass `gather_context` sich auf `gms.graphql`s eigenes
    Werfen verlaesst -- keine eigene Pruefung des `errors`-Felds hier,
    also auch keine Stelle, die es je verschlucken koennte."""
    with pytest.raises(GmsError, match="meldet Fehler"):
        gather_context(FakeGmsBodyErrors(), "urn:d")


# --- IMPORTANT 2: Teilzustaende ---------------------------------------

def test_ownership_present_but_owners_list_empty():
    data = {"dataset": {
        "urn": "urn:d",
        "properties": {"name": "t"},
        "ownership": {"owners": []},
        "glossaryTerms": {"terms": []},
        "domain": None,
    }}
    c = gather_context(FakeGms(data), "urn:d")
    assert c["owners"] == []
    assert c["glossary_terms"] == []
    assert c["domain"] == ""


@pytest.mark.parametrize("props", [
    {"name": "t"},                     # description-Schluessel fehlt ganz
    {"name": "t", "description": None},  # description explizit null
    {"name": "t", "description": ""},    # description explizit leer
])
def test_description_missing_null_or_empty_all_yield_empty_string(props):
    data = {"dataset": {
        "urn": "urn:d", "properties": props,
        "ownership": None, "glossaryTerms": None, "domain": None,
    }}
    c = gather_context(FakeGms(data), "urn:d")
    assert c["description"] == ""
    assert "None" not in c["text"]


def test_multiple_owners_and_glossary_terms_all_collected_in_order():
    data = {"dataset": {
        "urn": "urn:d",
        "properties": {"name": "t", "description": "d"},
        "ownership": {"owners": [
            {"owner": {"urn": "urn:li:corpuser:anna"}},
            {"owner": {"urn": "urn:li:corpGroup:finance-team"}},
        ]},
        "glossaryTerms": {"terms": [
            {"term": {"urn": "urn:li:glossaryTerm:SOX"}},
            {"term": {"urn": "urn:li:glossaryTerm:GDPR"}},
        ]},
        "domain": {"domain": {"properties": {"name": "Finance"}}},
    }}
    c = gather_context(FakeGms(data), "urn:d")
    assert c["owners"] == ["urn:li:corpuser:anna", "urn:li:corpGroup:finance-team"]
    assert c["glossary_terms"] == ["urn:li:glossaryTerm:SOX", "urn:li:glossaryTerm:GDPR"]
    for piece in ("anna", "finance-team", "SOX", "GDPR"):
        assert piece in c["text"]


def test_owner_matching_neither_union_branch_is_dropped_not_none():
    """Der Live-Fund: `owner` ist eine Union aus CorpUser/CorpGroup. Passt
    keins der beiden Inline-Fragmente (z.B. ein dritter, unbekannter
    Typ), liefert GraphQL ein leeres `{}` zurueck -- das darf weder als
    `None` in `owners` landen noch abstuerzen, sondern wird stillschweigend
    ausgefiltert (Review Fix-Runde 1: `or ""` statt `.get(key, "")`,
    das ein explizites `None` sonst durchgelassen haette)."""
    data = {"dataset": {
        "urn": "urn:d",
        "properties": {"name": "t"},
        "ownership": {"owners": [{"owner": {}}]},
        "glossaryTerms": {"terms": [{"term": {}}]},
        "domain": {"domain": {"properties": {"name": None}}},
    }}
    c = gather_context(FakeGms(data), "urn:d")
    assert c["owners"] == []
    assert c["glossary_terms"] == []
    assert c["domain"] == ""
    assert None not in c["owners"]
    assert "None" not in c["text"]


def test_text_has_no_blank_line_artifacts_and_no_none_leakage():
    """Jedes leere/None-Feld wird VOR dem Join herausgefiltert -- ein
    doppelter Zeilenumbruch waere ein Zeichen dafuer, dass ein leerer
    Platzhalter statt eines echten Wertes eingezogen ist."""
    data = {"dataset": {
        "urn": "urn:d",
        "properties": {"name": "t", "description": None},
        "ownership": {"owners": []},
        "glossaryTerms": {"terms": []},
        "domain": {"domain": {"properties": {"name": None}}},
    }}
    c = gather_context(FakeGms(data), "urn:d")
    assert c["text"] == "t"
    assert "\n\n" not in c["text"]
    assert "None" not in c["text"]


# --- Task 9: Zitatpflicht und Ruecfall ------------------------------------
#
# Der Kern der Schicht: ein Urteil OHNE woertliches Zitat aus dem
# gelesenen Kontext ist schlimmer als kein Urteil und wird verworfen --
# der deterministische Befund (EdgeVerdict.state) bleibt unangetastet
# stehen. Jeder Fehlweg (kein Transport, Transport wirft, Antwort ist
# kein JSON, kein Zitat, Zitat nicht im Korpus) endet in derselben
# Rueckfall-Form mit einem benannten `fallback_reason` -- ein stiller
# Rueckfall ist die Fehlerklasse, gegen die dieses Modul gebaut ist.

DAY = 86_400_000
DEAD = EdgeVerdict(
    edge=Edge("urn:up", "urn:down"), state="dead",
    evidence={"reason": "im geprueften Fenster nie gemessen", "buckets_checked": 30},
    coverage=Coverage(30, 10 * DAY, 40 * DAY, ""),
    timeline=Timeline((Bucket(40 * DAY, 0, 0),)))

UP = {"urn": "urn:up", "name": "fin_year_end", "description": "Jahresabschluss, revisionsrelevant",
      "owners": ["urn:li:corpuser:anna"], "glossary_terms": [], "domain": "Finance",
      "text": "fin_year_end\nJahresabschluss, revisionsrelevant\nurn:li:corpuser:anna\nFinance"}
DOWN = {"urn": "urn:down", "name": "tmp_42", "description": "", "owners": [],
        "glossary_terms": [], "domain": "", "text": "tmp_42"}


def _reply(**kw):
    return lambda prompt: json.dumps(kw)


def test_a_judgement_with_a_verbatim_quote_from_the_context_is_kept():
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="Betrifft eine revisionsrelevante Tabelle.",
        quote="Jahresabschluss, revisionsrelevant", source_field="description"))
    assert j.used_model is True
    assert j.important is True
    assert j.quote == "Jahresabschluss, revisionsrelevant"


def test_a_quote_that_is_not_in_the_context_is_discarded():
    """Der wichtigste Test der Schicht: ein erfundenes Zitat ist
    schlimmer als kein Urteil. Ohne Beleg faellt es auf den
    deterministischen Befund zurueck."""
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="Klingt wichtig.",
        quote="unternehmenskritischer Datenschatz", source_field="description"))
    assert j.used_model is False
    assert j.important is False
    assert j.quote == ""
    assert j.fallback_reason == "Zitat steht nicht im gelesenen Kontext"
    assert "dead" in j.reason


def test_a_reply_without_a_quote_field_is_discarded():
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(important=True, reason="Wichtig."))
    assert j.used_model is False
    assert j.fallback_reason == "kein Zitat geliefert"


def test_a_reply_that_is_not_json_is_discarded_with_a_named_reason():
    j = judge_edge(DEAD, UP, DOWN, transport=lambda p: "Ja, das ist wichtig!")
    assert j.used_model is False
    assert j.fallback_reason == "Antwort war kein JSON"


def test_a_transport_that_raises_falls_back_instead_of_propagating():
    """Eine gescheiterte Abfrage ist keine Abwesenheit -- aber sie darf
    auch nicht den ganzen Lauf abbrechen. Sie wird benannt."""
    def boom(prompt):
        raise JudgeTransportError("claude -p exit 1: not logged in")

    j = judge_edge(DEAD, UP, DOWN, transport=boom)
    assert j.used_model is False
    assert j.fallback_reason.startswith("Transport gescheitert:")
    assert "not logged in" in j.fallback_reason


def test_no_transport_at_all_means_the_deterministic_finding_verbatim():
    j = judge_edge(DEAD, UP, DOWN, transport=None)
    assert j.used_model is False
    assert j.fallback_reason == "kein Transport konfiguriert"
    assert j.reason == "deterministischer Befund: dead"


def test_whitespace_differences_do_not_break_an_otherwise_valid_quote():
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="r", quote="Jahresabschluss,   revisionsrelevant",
        source_field="description"))
    assert j.used_model is True


def test_the_prompt_contains_both_contexts_and_the_state_but_no_instruction_to_invent():
    p = build_prompt(DEAD, UP, DOWN)
    assert "fin_year_end" in p and "tmp_42" in p and "dead" in p
    assert "quote" in p


def test_judgement_json_is_flat_and_carries_the_fallback_reason():
    j = judge_edge(DEAD, UP, DOWN, transport=None).to_json()
    assert j["used_model"] is False
    assert j["fallback_reason"] == "kein Transport konfiguriert"
    assert j["edge"] == "urn:up->urn:down"


# --- Ergaenzungen ueber den Brief hinaus (Hard Rules aus dem Auftrag) -----
#
# Der Brief deckt die fuenf Fehlwege ab, aber zwei Haerten aus dem
# Auftrag verlangen eigene Tests: (a) die Normalisierungsgrenze bei
# GROSS-/Kleinschreibung -- der Brief testet nur die Whitespace-Grenze --
# und (b) den strukturellen Beweis, dass kein Modell-Antwortfeld je den
# deterministischen Zustand einer Kante veraendern kann, selbst wenn es
# das versucht (garbage-Feld "state").

def test_a_quote_that_only_matches_after_changing_case_is_discarded():
    """Normalisierung ist bewusst NUR Whitespace, nicht Gross-/Klein-
    schreibung -- eine Kette, die den Case aendert, ist keine woertliche
    Uebernahme mehr und faellt darum wie ein erfundenes Zitat zurueck."""
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="r", quote="JAHRESABSCHLUSS, REVISIONSRELEVANT",
        source_field="description"))
    assert j.used_model is False
    assert j.fallback_reason == "Zitat steht nicht im gelesenen Kontext"


def test_a_quote_field_that_is_not_a_string_is_treated_as_missing():
    """Garbage-Form (Zahl statt Text) darf nicht crashen -- sie ist
    strukturell kein Zitat und faellt wie ein fehlendes zurueck."""
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="r", quote=12345, source_field="description"))
    assert j.used_model is False
    assert j.fallback_reason == "kein Zitat geliefert"


def test_a_json_reply_that_is_not_an_object_is_discarded_not_crashed():
    """`json.loads` akzeptiert auch Zahlen und Listen als gueltiges JSON
    -- beides ist kein Objekt mit Feldern und muss denselben benannten
    Rueckfall wie unparsbarer Text auslösen, nicht eine AttributeError."""
    j = judge_edge(DEAD, UP, DOWN, transport=lambda p: "42")
    assert j.used_model is False
    assert j.fallback_reason == "Antwort war kein JSON"

    j2 = judge_edge(DEAD, UP, DOWN, transport=lambda p: json.dumps(["important", True]))
    assert j2.used_model is False
    assert j2.fallback_reason == "Antwort war kein JSON"


def test_a_state_field_smuggled_into_the_model_reply_cannot_alter_the_verdict():
    """Haerteste Regel des Auftrags: das Modell darf NIE den
    deterministischen Zustand aendern -- nur gewichten. `Judgement` hat
    strukturell gar kein `state`-Feld, das ein solches Reply setzen
    koennte, und das Original-`EdgeVerdict` bleibt unveraendert (es ist
    ohnehin frozen)."""
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="r", quote="Jahresabschluss, revisionsrelevant",
        source_field="description", state="confirmed"))
    assert not hasattr(j, "state")
    assert DEAD.state == "dead"
