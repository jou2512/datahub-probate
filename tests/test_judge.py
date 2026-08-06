"""Tests fuer probate/judge.py -- gather_context.

Warum diese Datei existiert: `text` ist der Korpus, gegen den spaeter ein
Modell-Zitat geprueft wird (Task 9). Diese Tests belegen, dass jedes
lesbare Feld tatsaechlich in `text` landet -- und dass eine fehlende
Antwort (kein Dataset) leer ist, nicht abstuerzt.
"""

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
