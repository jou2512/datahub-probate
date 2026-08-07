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

import pytest

from probate.gms import GmsError
from probate.judge import gather_context


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
