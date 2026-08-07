"""Das Urteil -- die einzige Stelle im Projekt mit einem Modellaufruf.

Warum diese Datei existiert: nicht jede Abweichung ist wichtig. Eine tote
Kante zu einer Tabelle mit "Jahresabschluss" in der Beschreibung ist etwas
anderes als eine zu einer namenlosen Zwischentabelle. Das ist Urteil ueber
unstrukturierten Text -- keine Regel, die man schreiben kann.

Die Gegenleistung fuer diese Freiheit ist die ZITATPFLICHT (Task 9): ein
Urteil ohne woertliches Zitat aus dem gelesenen Kontext wird verworfen,
und es bleibt beim deterministischen Befund. Ein Werkzeug, dessen
Kernaussage "nichts behaupten ohne Beleg" lautet, darf sich diese Regel
nicht selbst erlassen.

Dieses Modul (Task 8) ist der deterministische, modellfreie Teil davon:
es sammelt alles Lesbare zu einem Dataset in einen einzigen Text-Korpus.
Ueberall sonst gilt weiter: deterministisch, offline testbar. Ein
fehlgeschlagener GraphQL-Aufruf wird NICHT abgefangen -- `gms.graphql`
wirft `GmsError` bereits, und das muss bis zum Aufrufer durchreichen.
Eine gescheiterte Abfrage ist keine Abwesenheit: "keine Beschreibung" und
"Abfrage fehlgeschlagen" sind verschiedene Aussagen, und diese Funktion
gibt nur Ersteres zurueck -- Zweiteres ist eine Exception, kein leerer
Wert.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

# Live-Fund (07.08., gegen 28080 -- weicht vom Brief ab, siehe Docstring
# unten): `Owner.owner` ist `OwnerType`, eine UNION aus `CorpUser` und
# `CorpGroup` ohne eigenes `urn`-Feld -- ein direktes `owner { urn }` wie
# im Task-Brief scheitert live mit `FieldUndefined@[.../owner/urn]`
# (Validation error, HTTP 200, Falle 2 aus global-constraints.md).
# Introspektion (`__type(name: "OwnerType") { possibleTypes }`) bestaetigt
# die zwei moeglichen Typen; beide inline gefragt, weil ein Owner in der
# Praxis ein Mensch oder eine Gruppe ist.
CONTEXT_Q = """
query($urn: String!) {
  dataset(urn: $urn) {
    urn
    properties { name description }
    ownership {
      owners {
        owner {
          ... on CorpUser { urn }
          ... on CorpGroup { urn }
        }
      }
    }
    glossaryTerms { terms { term { urn } } }
    domain { domain { properties { name } } }
  }
}
"""


def gather_context(gms, urn: str) -> dict:
    """Alles Lesbare zu einem Dataset -- deterministisch, kein Modell.

    `text` ist der einzige Korpus, gegen den ein Zitat geprueft wird.
    Was hier nicht drinsteht, kann kein gueltiges Zitat sein.

    Ein fehlender `dataset`-Knoten (z.B. URN existiert nicht) liefert
    leere Felder, kein Absturz -- das ist ein gueltiges Ergebnis ("nichts
    zu zitieren"), keine Fehlerbedingung. Ein FEHLGESCHLAGENER Aufruf
    dagegen wirft `GmsError` aus `gms.graphql` und wird hier nicht
    gefangen -- das ist der Unterschied zwischen Abwesenheit und
    Fehlschlag.
    """
    d = (gms.graphql(CONTEXT_Q, {"urn": urn}).get("dataset")) or {}
    props = d.get("properties") or {}
    # `.get(key, "")` faellt nur bei FEHLENDEM Schluessel auf den Default
    # zurueck -- steht der Schluessel mit Wert `None` da (z.B. ein Owner,
    # der zu keinem der beiden Inline-Fragmente passt, oder ein Domain-
    # Name, der explizit null ist), liefert `.get()` `None` weiter. Darum
    # ueberall `or ""` statt eines Default-Arguments: das faengt sowohl
    # den fehlenden Schluessel als auch den expliziten `None`-Wert ab und
    # verhindert, dass ein `None` in einer Rueckgabe landet, die als
    # `str`/`list[str]` deklariert ist (Review Fix-Runde 1).
    owners = [
        (o.get("owner") or {}).get("urn") or ""
        for o in ((d.get("ownership") or {}).get("owners") or [])
    ]
    terms = [
        (t.get("term") or {}).get("urn") or ""
        for t in ((d.get("glossaryTerms") or {}).get("terms") or [])
    ]
    domain = (((d.get("domain") or {}).get("domain") or {}).get("properties") or {}).get("name") or ""
    parts = [props.get("name") or "", props.get("description") or "",
             *owners, *terms, domain]
    return {
        "urn": urn,
        "name": props.get("name") or "",
        "description": props.get("description") or "",
        "owners": [o for o in owners if o],
        "glossary_terms": [t for t in terms if t],
        "domain": domain,
        "text": "\n".join(p for p in parts if p),
    }


# --- Task 9: Zitatpflicht und Rueckfall ------------------------------------
#
# Ab hier der Modell-Teil. Der Transport ist eine injizierte Funktion
# (`str -> str`), nie ein konkreter Prozessaufruf -- das haelt dieses
# Modul komplett offline testbar; Task 10 liefert den echten `claude -p`-
# Transport separat.
#
# Die Kernregel, wieder: ein Urteil OHNE woertliches Zitat aus dem
# gelesenen Kontext (`gather_context`s `text`-Feld, s.o.) ist schlimmer
# als kein Urteil. Jeder Fehlweg -- kein Transport, Transport wirft,
# Antwort ist kein JSON, kein Zitat, Zitat nicht im Korpus -- endet in
# DERSELBEN Rueckfall-Form (`_fallback`) mit einem benannten
# `fallback_reason`. Ein stiller Rueckfall waere genau die Fehlerklasse,
# gegen die dieses Projekt insgesamt antritt (s. CLAUDE.md dieses
# Projekts: "jede generierte Metadaten-Aussage traegt ihr Beleg-Artefakt
# oder wird zu `unbekannt`").

JudgeTransport = Callable[[str], str]


class JudgeTransportError(RuntimeError):
    """Der Transport hat nicht geantwortet -- ein benannter Fehlschlag,
    keine Abwesenheit eines Urteils. Task 10s `claude -p`-Anbindung wirft
    diese Klasse (Prozess nicht gestartet, Exit-Code != 0, Timeout); jede
    andere Exception aus einem fremden Transport wird in `judge_edge`
    ebenfalls abgefangen, aber unter ihrem eigenen Typnamen benannt."""


@dataclass(frozen=True)
class Judgement:
    """Das Ergebnis EINER Kanten-Bewertung -- Modell-Urteil oder Rueckfall.

    Bewusst KEIN `state`-Feld: der deterministische Kanten-Zustand lebt
    ausschliesslich in `EdgeVerdict.state` (ledger.py) und ist frozen.
    Diese Klasse kann ihn strukturell nicht ueberschreiben, weil sie ihn
    gar nicht traegt -- ein Modell-Reply, das versucht, einen `state`
    mitzuschicken, landet nirgends (s. Test
    `test_a_state_field_smuggled_into_the_model_reply_cannot_alter_the_verdict`).
    Das Modell darf nur GEWICHTEN (`important`, `reason`), nie den Befund
    selbst aendern.
    """

    edge_key: str
    important: bool
    reason: str
    quote: str
    source_field: str
    used_model: bool
    fallback_reason: str

    def to_json(self) -> dict:
        return {
            "edge": self.edge_key,
            "important": self.important,
            "reason": self.reason,
            "quote": self.quote,
            "source_field": self.source_field,
            "used_model": self.used_model,
            "fallback_reason": self.fallback_reason,
        }


_PROMPT = """You are auditing one lineage edge in a data catalog.

EDGE: {edge}
DETERMINISTIC STATE: {state}
EVIDENCE: {evidence}

UPSTREAM CONTEXT (this is the only text you may quote from):
{up_text}

DOWNSTREAM CONTEXT (this is the only text you may quote from):
{down_text}

Decide whether this deviation matters enough for a human to look at it.

Answer with a single JSON object and nothing else:
{{"important": true|false,
  "reason": "one sentence",
  "quote": "a verbatim span copied from the context above",
  "source_field": "description|owner|glossary|domain|name"}}

The quote must appear character-for-character in the context above.
If nothing in the context justifies a judgement, answer with
{{"important": false, "reason": "no basis in the read context", "quote": "",
  "source_field": ""}}."""


def build_prompt(verdict, up_ctx: dict, down_ctx: dict) -> str:
    """Der einzige Ort, an dem ein Modell den Kontext zu sehen bekommt.

    Traegt den deterministischen Zustand EXPLIZIT mit ("DETERMINISTIC
    STATE") -- das Modell soll ihn kennen, um ihn einzuordnen, aber es
    gibt keine Instruktion, ihn zu aendern oder zurueckzugeben; `judge_edge`
    liest aus der Antwort auch keinen State-Wert. Der letzte Satz vor dem
    JSON-Schema ("If nothing ... justifies") ist die einzige Instruktion
    im Prompt, die auf ein leeres Ergebnis hinweist -- keine, die ein
    Zitat erfinden wuerde, wenn keins da ist.
    """
    return _PROMPT.format(
        edge=verdict.edge.key(), state=verdict.state,
        evidence=json.dumps(verdict.evidence, ensure_ascii=False),
        up_text=up_ctx.get("text", "") or "(no metadata)",
        down_text=down_ctx.get("text", "") or "(no metadata)",
    )


def _normalise(s: str) -> str:
    """Normalisierungs-Entscheid (dokumentiert, wie im Auftrag verlangt):

    NUR Whitespace wird zusammengefasst (mehrere Leerzeichen/Zeilenumbrueche
    -> ein Leerzeichen, Raender getrimmt) -- weil GraphQL-Text und ein
    Modell-Zitat sich in Zeilenumbruechen/Mehrfach-Leerzeichen unterscheiden
    koennen, ohne dass das Zitat deshalb erfunden waere (belegt durch
    `test_whitespace_differences_do_not_break_an_otherwise_valid_quote`).

    Gross-/Kleinschreibung wird DAGEGEN bewusst NICHT normalisiert: eine
    Kette, die den Case aendert, ist keine woertliche Uebernahme mehr,
    sondern eine Paraphrase -- und genau eine Paraphrase soll durchfallen
    (belegt durch
    `test_a_quote_that_only_matches_after_changing_case_is_discarded`).
    Case-insensitive zu pruefen wuerde die Zitatpflicht aufweichen: ein
    Modell koennte dann jedes Wort im Korpus in beliebiger Schreibung als
    "Beleg" ausgeben.
    """
    return re.sub(r"\s+", " ", s).strip()


def _fallback(verdict, why: str) -> Judgement:
    """Der EINE Rueckfall-Pfad. Jeder Fehlweg in `judge_edge` ruft genau
    diese Funktion auf -- das ist absichtlich keine Kopie pro Fehlerfall,
    damit ein neuer Fehlweg nicht versehentlich eine eigene, abweichende
    Rueckfall-Form erfindet. `reason` traegt IMMER den deterministischen
    Befund woertlich (`verdict.state`), nie eine Modell-Aussage -- das ist
    der Kern der Zitatpflicht: ohne Beleg bleibt nur, was ohnehin schon
    feststand."""
    return Judgement(
        edge_key=verdict.edge.key(), important=False,
        reason=f"deterministischer Befund: {verdict.state}",
        quote="", source_field="", used_model=False, fallback_reason=why,
    )


def judge_edge(verdict, up_ctx: dict, down_ctx: dict,
               transport: JudgeTransport | None = None) -> Judgement:
    """Ein Urteil pro Kante -- oder der deterministische Befund.

    Jeder Fehlweg endet in DERSELBEN Rueckfall-Antwort (`_fallback`), mit
    einem `fallback_reason`, der sagt, WELCHER Weg gescheitert ist. Das
    Register verliert dabei nichts: der Befund stand vorher fest, das
    Modell durfte ihn nur gewichten -- `Judgement` hat kein Feld, ueber
    das ein Reply ihn aendern koennte (s. `Judgement`-Docstring).

    Reihenfolge der Fehlwege, jeder mit eigenem `fallback_reason`:
      1. kein Transport injiziert                 -> "kein Transport konfiguriert"
      2. Transport wirft (JudgeTransportError o.ae.) -> "Transport gescheitert: <exc>"
      3. Antwort ist kein JSON-Objekt               -> "Antwort war kein JSON"
      4. kein (nutzbares) Zitat im JSON              -> "kein Zitat geliefert"
      5. Zitat ist kein woertlicher Teilstring des
         gelesenen Kontexts (nach Whitespace-Norm.)  -> "Zitat steht nicht im gelesenen Kontext"

    Garbage-Feldwerte (z.B. `quote` als Zahl statt Text, eine JSON-Antwort,
    die eine Liste statt eines Objekts ist) duerfen NICHT crashen -- sie
    werden strukturell wie der jeweils naechstliegende Fehlweg behandelt,
    nie mit einer unbehandelten Exception durchgereicht.
    """
    if transport is None:
        return _fallback(verdict, "kein Transport konfiguriert")

    try:
        raw = transport(build_prompt(verdict, up_ctx, down_ctx))
    except Exception as exc:  # jeder Transportfehler, nicht nur unserer
        return _fallback(verdict, f"Transport gescheitert: {exc}")

    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("kein Objekt")
    except Exception:
        return _fallback(verdict, "Antwort war kein JSON")

    quote_raw = parsed.get("quote")
    quote = quote_raw.strip() if isinstance(quote_raw, str) else ""
    if not quote:
        return _fallback(verdict, "kein Zitat geliefert")

    corpus = _normalise(f"{up_ctx.get('text', '')}\n{down_ctx.get('text', '')}")
    if _normalise(quote) not in corpus:
        return _fallback(verdict, "Zitat steht nicht im gelesenen Kontext")

    return Judgement(
        edge_key=verdict.edge.key(),
        important=bool(parsed.get("important")),
        reason=str(parsed.get("reason") or ""),
        quote=quote,
        source_field=str(parsed.get("source_field") or ""),
        used_model=True,
        fallback_reason="",
    )
