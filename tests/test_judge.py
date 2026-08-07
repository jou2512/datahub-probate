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

# Fix-Runde 1 (C1): die Beschreibung braucht mindestens drei durch
# Whitespace getrennte Woerter, sonst wuerde jedes woertliche Zitat
# daraus an der eigenen Mindestlaenge scheitern, bevor es ueberhaupt zum
# Kontext-Abgleich kommt. "Jahresabschluss, revisionsrelevant" (die
# urspruengliche Brief-Fixture) hatte nur zwei -- deshalb "Geprüfter"
# ergaenzt.
UP = {"urn": "urn:up", "name": "fin_year_end",
      "description": "Geprüfter Jahresabschluss, revisionsrelevant",
      "owners": ["urn:li:corpuser:anna"], "glossary_terms": [], "domain": "Finance",
      "text": "fin_year_end\nGeprüfter Jahresabschluss, revisionsrelevant\nurn:li:corpuser:anna\nFinance"}
DOWN = {"urn": "urn:down", "name": "tmp_42", "description": "", "owners": [],
        "glossary_terms": [], "domain": "", "text": "tmp_42"}


def _reply(**kw):
    return lambda prompt: json.dumps(kw)


def test_a_judgement_with_a_verbatim_quote_from_the_context_is_kept():
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="Betrifft eine revisionsrelevante Tabelle.",
        quote="Geprüfter Jahresabschluss, revisionsrelevant", source_field="description"))
    assert j.used_model is True
    assert j.important is True
    assert j.quote == "Geprüfter Jahresabschluss, revisionsrelevant"


def test_a_quote_that_is_not_in_the_context_is_discarded():
    """Der wichtigste Test der Schicht: ein erfundenes Zitat ist
    schlimmer als kein Urteil. Ohne Beleg faellt es auf den
    deterministischen Befund zurueck. Drei Woerter, damit der Test die
    C2-Kontextpruefung trifft statt vorher an der C1-Mindestlaenge
    abzuprallen (siehe Fix-Runde-1-Tests weiter unten fuer C1 isoliert)."""
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="Klingt wichtig.",
        quote="unternehmenskritischer strategischer Datenschatz", source_field="description"))
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
    # Fix-Runde 1 (I4): der Exception-Typname wird jetzt vorangestellt,
    # damit "unsere eigene Prompt-Baustelle" nie mit "der Transport hat
    # geantwortet und einen Fehler gemeldet" verwechselt werden kann.
    assert j.fallback_reason == (
        "Transport gescheitert (JudgeTransportError): claude -p exit 1: not logged in")
    assert "not logged in" in j.fallback_reason


def test_no_transport_at_all_means_the_deterministic_finding_verbatim():
    j = judge_edge(DEAD, UP, DOWN, transport=None)
    assert j.used_model is False
    assert j.fallback_reason == "kein Transport konfiguriert"
    assert j.reason == "deterministischer Befund: dead"


def test_whitespace_differences_do_not_break_an_otherwise_valid_quote():
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="r", quote="Geprüfter   Jahresabschluss,   revisionsrelevant",
        source_field="description"))
    assert j.used_model is True
    # M1: gespeichert wird der TATSAECHLICHE Katalog-Ausschnitt (einfache
    # Leerzeichen), nicht die Mehrfach-Leerzeichen-Schreibung des Modells.
    assert j.quote == "Geprüfter Jahresabschluss, revisionsrelevant"


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
        important=True, reason="r", quote="GEPRÜFTER JAHRESABSCHLUSS, REVISIONSRELEVANT",
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
        important=True, reason="r", quote="Geprüfter Jahresabschluss, revisionsrelevant",
        source_field="description", state="confirmed"))
    assert not hasattr(j, "state")
    assert DEAD.state == "dead"


# --- Fix-Runde 1 (Opus-Review, 07.08.) --------------------------------
#
# Fuenf gemessene Luecken in der Zitatpflicht selbst -- der
# Rueckfall-Mechanismus (Trichter, Zustands-Immunitaet, Fail-Closed bei
# Case/Homoglyph/ZWSP) wurde bestaetigt und bleibt unveraendert. Diese
# Tests belegen je EINE der fuenf Luecken UND ihre exakte Grenze.

def test_c1_a_one_character_quote_is_rejected_the_measured_exploit():
    """Der exakte Exploit aus dem Review: `quote="e"` erfuellte vorher
    die Zitatpflicht syntaktisch (ein einzelnes Zeichen findet sich
    fast immer im Text) und lieferte ein voll erfundenes Urteil mit "e"
    als Beleg aus. Das ist die BILLIGSTE Art, wie ein schwaches Modell
    die Anweisung "character-for-character" erfuellt -- der erwartete
    Produktionsfehler, keine Exotik."""
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="Unternehmenskritisch, Revision betroffen.",
        quote="e", source_field="description"))
    assert j.used_model is False
    assert j.important is False
    assert j.fallback_reason == "Zitat zu kurz, kein Beleg"


def test_c1_boundary_eleven_chars_fails_twelve_chars_passes_the_length_gate():
    """Grenzwert Zeichenanzahl: 11 vs. 12 Zeichen, Wortzahl (3) konstant
    gehalten. Beide Zitate sind frei erfunden (nicht im Kontext) --
    genau DESHALB zeigt der Uebergang von "Zitat zu kurz" zu "Zitat
    steht nicht im gelesenen Kontext" eindeutig, dass 12 Zeichen die
    Laengen-Pruefung ueberhaupt erst passieren laesst, unabhaengig vom
    spaeteren Kontext-Abgleich."""
    eleven = "aaa bbb ccc"  # 3+1+3+1+3 = 11 Zeichen, 3 Tokens
    assert len(eleven) == 11
    j_short = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="r", quote=eleven, source_field="description"))
    assert j_short.fallback_reason == "Zitat zu kurz, kein Beleg"

    twelve = "aaaa bbb ccc"  # 4+1+3+1+3 = 12 Zeichen, 3 Tokens
    assert len(twelve) == 12
    j_ok_length = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="r", quote=twelve, source_field="description"))
    assert j_ok_length.fallback_reason == "Zitat steht nicht im gelesenen Kontext"


def test_c1_boundary_two_tokens_fails_three_tokens_passes_the_token_gate():
    """Grenzwert Wortzahl: 2 vs. 3 durch Whitespace getrennte Tokens,
    Zeichenzahl komfortabel ueber 12 gehalten. Zeigt, dass die
    Zeichen-Untergrenze allein NICHT genuegt -- eine lange Kette ohne
    genug Wortgrenzen ("aaaaaaaaaaaabbbbbbbbbbbb" in zwei Tokens) waere
    sonst genauso ein Fragment wie ein einzelnes Zeichen."""
    two_tokens = "aaaaaaaaaaaa bbbbbbbbbbbb"  # 25 Zeichen, 2 Tokens
    assert len(two_tokens) > 12 and len(two_tokens.split()) == 2
    j_short = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="r", quote=two_tokens, source_field="description"))
    assert j_short.fallback_reason == "Zitat zu kurz, kein Beleg"

    three_tokens = "aaaaaaaaaaaa bbbbbbbbbbbb cc"  # 28 Zeichen, 3 Tokens
    assert len(three_tokens.split()) == 3
    j_ok_length = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="r", quote=three_tokens, source_field="description"))
    assert j_ok_length.fallback_reason == "Zitat steht nicht im gelesenen Kontext"


def test_c2_a_quote_welded_across_two_fields_of_the_same_side_is_rejected():
    """Vorher wurde `name + "\\n" + description + ...` zu einem String
    verschmolzen und DANACH normalisiert -- ein Zitat, das am Ende von
    `name` beginnt und am Anfang von `description` weitergeht, sah
    danach wie ein zusammenhaengender Treffer aus, obwohl es das in
    KEINEM einzelnen Feld je war. Drei Tokens, damit C1 nicht vorher
    greift."""
    welded = "fin_year_end Geprüfter Jahresabschluss,"  # name + Anfang description
    assert len(welded) >= 12 and len(welded.split()) == 3
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="r", quote=welded, source_field="description"))
    assert j.used_model is False
    assert j.fallback_reason == "Zitat steht nicht im gelesenen Kontext"


def test_c2_a_quote_welded_across_upstream_and_downstream_is_rejected():
    """Derselbe Fehler ueber die DATENSATZ-Grenze: `owner` (upstream) +
    `domain` (upstream) + `name` (downstream) waren im alten,
    verschmolzenen Korpus contiguous ("...anna Finance tmp_42") und
    haetten dort validiert -- keins der beiden Segmente (upstream ODER
    downstream, je einzeln) enthaelt den vollen String."""
    welded = "urn:li:corpuser:anna Finance tmp_42"  # UP.owner + UP.domain + DOWN.name
    assert len(welded) >= 12 and len(welded.split()) == 3
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="r", quote=welded, source_field="owner"))
    assert j.used_model is False
    assert j.fallback_reason == "Zitat steht nicht im gelesenen Kontext"


def test_i2_important_as_the_string_false_is_parsed_as_false_not_coerced_to_true():
    """Der gemessene Fehler: `bool("false")` ist `True`, weil jeder
    nichtleere String truthy ist -- das haette die Gewichtung, die
    einzige Aussage, die dieses Modul treffen darf, exakt umgedreht.
    Die explizite String-Zuordnung liest "false" korrekt als das echte
    Bool `False`, kein Rueckfall noetig -- das Urteil bleibt gueltig,
    nur eben nicht wichtig."""
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important="false", reason="r",
        quote="Geprüfter Jahresabschluss, revisionsrelevant",
        source_field="description"))
    assert j.used_model is True
    assert j.important is False


def test_i2_important_as_the_string_true_is_accepted():
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important="true", reason="r",
        quote="Geprüfter Jahresabschluss, revisionsrelevant",
        source_field="description"))
    assert j.used_model is True
    assert j.important is True


def test_i2_important_as_a_non_boolean_type_is_rejected():
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=["ja"], reason="r",
        quote="Geprüfter Jahresabschluss, revisionsrelevant",
        source_field="description"))
    assert j.used_model is False
    assert j.fallback_reason == "important-Feld nicht boolesch"


def test_i3_source_field_is_derived_from_the_actual_match_never_trusted_from_the_model():
    """Eine falsche Beleg-BEZEICHNUNG ist dieselbe Fehlerklasse wie ein
    falsches Zitat (I3). Das Modell behauptet `source_field="owner"`,
    obwohl das Zitat woertlich aus `description` stammt -- die
    zurueckgegebene Antwort traegt trotzdem das WAHRE Label, weil es aus
    dem Treffer abgeleitet wird statt vom Modell uebernommen."""
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="r",
        quote="Geprüfter Jahresabschluss, revisionsrelevant",
        source_field="owner"))
    assert j.used_model is True
    assert j.source_field == "description"


def test_i4_a_non_serialisable_evidence_value_is_our_own_bug_not_a_transport_failure():
    """`build_prompt(...)` liegt jetzt AUSSERHALB des Transport-try: ein
    Fehler beim Prompt-Bau (hier `json.dumps` an einem `datetime`-Wert in
    `verdict.evidence`) ist ein Bug in UNSEREM Code, kein Transport-
    Fehlschlag, und darf nicht als "Transport gescheitert" getarnt
    werden -- er schlaegt durch, der Transport wird nie aufgerufen."""
    import datetime

    bad = EdgeVerdict(
        edge=Edge("urn:up", "urn:down"), state="dead",
        evidence={"when": datetime.datetime(2026, 1, 1)},
        coverage=Coverage(1, 0, 0, ""), timeline=Timeline(()))

    def never_called(prompt):
        raise AssertionError("Transport haette nie aufgerufen werden duerfen")

    with pytest.raises(TypeError):
        judge_edge(bad, UP, DOWN, transport=never_called)


def test_m2_a_context_with_nothing_readable_on_either_side_gets_its_own_reason():
    """"Nichts wurde gelesen" und "im Gelesenen nicht gefunden" sind
    verschiedene Aussagen (M2). Ein Kontext ganz ohne lesbare Felder auf
    BEIDEN Seiten bekommt eine eigene Meldung statt der generischen
    "nicht gefunden"."""
    empty_up = {"urn": "urn:up", "name": "", "description": "", "owners": [],
                "glossary_terms": [], "domain": "", "text": ""}
    empty_down = {"urn": "urn:down", "name": "", "description": "", "owners": [],
                  "glossary_terms": [], "domain": "", "text": ""}
    j = judge_edge(DEAD, empty_up, empty_down, transport=_reply(
        important=True, reason="r", quote="irgendein laengeres Zitat",
        source_field="description"))
    assert j.used_model is False
    assert j.fallback_reason == "kein lesbarer Kontext vorhanden"


def test_m4_important_with_an_empty_reason_is_discarded():
    """`used_model=True` mit leerem `reason` war erreichbar (M4) -- eine
    Gewichtung ohne Begruendung ist keine verwertbare Aussage."""
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="",
        quote="Geprüfter Jahresabschluss, revisionsrelevant",
        source_field="description"))
    assert j.used_model is False
    assert j.fallback_reason == "keine Begruendung geliefert"


# --- Task 10: `claude -p`-Transport und judge_ledger ----------------------
#
# Offline-only, wie ueberall in dieser Datei: kein Test hier ruft je den
# echten Prozess auf. `runner` ist die injizierte Stelle, an der
# `claude_cli_transport` einen Fake statt `subprocess.run` bekommt. Das
# Live-Zeugnis fuer die echte CLI liegt in
# `harness/runs/judge-transport-probe.json`, nicht hier.

from probate.judge import claude_cli_transport, judge_ledger


class FakeProc:
    def __init__(self, returncode, stdout, stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_transport_extracts_the_result_field_from_the_cli_envelope():
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)
        return FakeProc(0, json.dumps({"result": '{"important": true}'}))

    t = claude_cli_transport(runner=runner)
    assert t("hallo") == '{"important": true}'
    assert calls[0][:2] == ["claude", "-p"]
    assert "--output-format" in calls[0]


def test_a_nonzero_exit_becomes_a_named_transport_error_not_an_empty_answer():
    def runner(cmd, **kw):
        return FakeProc(1, "", "not logged in")

    with pytest.raises(JudgeTransportError) as e:
        claude_cli_transport(runner=runner)("hallo")
    assert "not logged in" in str(e.value)


def test_a_timeout_becomes_a_transport_error_too():
    import subprocess

    def runner(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 60)

    with pytest.raises(JudgeTransportError):
        claude_cli_transport(runner=runner)("hallo")


def test_a_missing_binary_becomes_a_transport_error_not_an_uncaught_oserror():
    """Ein OSError (Binary nicht gefunden, z.B. `claude` nicht im PATH) ist
    strukturell derselbe Fehlweg wie ein Timeout oder ein Exit != 0 -- der
    Aufrufer soll nie eine nackte `FileNotFoundError` sehen muessen, nur
    den einen benannten Transport-Fehler."""
    def runner(cmd, **kw):
        raise FileNotFoundError("[WinError 2] Das System kann die angegebene Datei nicht finden")

    with pytest.raises(JudgeTransportError) as e:
        claude_cli_transport(runner=runner)("hallo")
    assert "nicht startbar" in str(e.value)


def test_an_envelope_without_a_readable_result_field_yields_an_empty_string_not_a_crash():
    """Ein Umschlag, der zwar gueltiges JSON ist, aber kein `result`-Feld
    traegt, ist kein Transport-Fehlschlag (der Prozess hat geantwortet,
    exit 0) -- er liefert einen leeren rohen Text. `judge_edge` faengt das
    bereits als eigenen, benannten Fehlweg ab ("Antwort war kein JSON" bei
    einem leeren String) -- der Transport selbst crasht hier nicht."""
    def runner(cmd, **kw):
        return FakeProc(0, json.dumps({"something_else": 1}))

    assert claude_cli_transport(runner=runner)("hallo") == ""


def test_judge_ledger_only_judges_deviating_edges_never_confirmed_ones():
    """Der Modellaufruf haengt an der Zahl AUFFAELLIGER Kanten, nicht an
    der Gesamtzahl -- das ist der Lastentwurf aus der Spec."""
    ledger = {"edges": [
        {"edge": "a->b", "state": "confirmed", "upstream": "a", "downstream": "b",
         "evidence": {}, "coverage": {}, "timeline": {}},
        {"edge": "a->c", "state": "dead", "upstream": "a", "downstream": "c",
         "evidence": {}, "coverage": {}, "timeline": {}},
    ]}
    seen = []

    class G:
        def graphql(self, q, v=None):
            seen.append(v["urn"])
            return {"dataset": None}

    out = judge_ledger(G(), ledger, transport=None, limit=20)
    assert [j["edge"] for j in out] == ["a->c"]
    assert "b" not in seen


def test_judge_ledger_respects_the_hard_limit():
    ledger = {"edges": [
        {"edge": f"a->x{i}", "state": "dead", "upstream": "a", "downstream": f"x{i}",
         "evidence": {}, "coverage": {}, "timeline": {}} for i in range(5)]}

    class G:
        def graphql(self, q, v=None):
            return {"dataset": None}

    assert len(judge_ledger(G(), ledger, transport=None, limit=2)) == 2


def test_judge_ledger_caches_context_per_urn_not_per_edge():
    """Ein Dataset, das auf beiden Seiten mehrerer Kanten auftaucht, darf
    nur EINMAL abgefragt werden -- API-Aufrufzahl ist eine gemessene
    Groesse in diesem Projekt, kein Nebenschauplatz (s. `_Counting` in
    `ledger.py`)."""
    ledger = {"edges": [
        {"edge": "a->shared", "state": "dead", "upstream": "a", "downstream": "shared",
         "evidence": {}, "coverage": {}, "timeline": {}},
        {"edge": "shared->b", "state": "dead", "upstream": "shared", "downstream": "b",
         "evidence": {}, "coverage": {}, "timeline": {}},
    ]}

    class G:
        def __init__(self):
            self.calls = 0

        def graphql(self, q, v=None):
            self.calls += 1
            return {"dataset": None}

    g = G()
    judge_ledger(g, ledger, transport=None, limit=20)
    # 3 eindeutige URNs (a, shared, b) -> 3 gather_context-Aufrufe, nicht 4
    assert g.calls == 3
