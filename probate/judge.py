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
import subprocess
from dataclasses import dataclass
from typing import Callable

from probate.ledger import Coverage, Edge, EdgeVerdict, Timeline

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

# Fix-Runde 1 (Opus-Review, 07.08.): fuenf gemessene Luecken in der
# Zitatpflicht selbst, nicht im Rueckfall-Mechanismus (der wurde
# bestaetigt: Zustands-Immunitaet, Rueckfall-Trichter und das
# Fail-Closed bei Homoglyphen/ZWSP/Interpunktion sind unveraendert
# richtig). Konkret behoben:
#   C1 (kritisch) - ein Ein-Zeichen-Zitat wie "e" erfuellte die Pflicht
#       und machte sie wirkungslos; jetzt eine Mindestlaenge (s.
#       `_QUOTE_MIN_CHARS`/`_QUOTE_MIN_TOKENS`).
#   C2 - ein Zitat, das ueber Feld- ODER Datensatz-Grenzen hinweg
#       zusammengeschweisst war (weil `text` mit "\n" verschmolzen und
#       DANACH normalisiert wurde), validierte faelschlich; jetzt wird
#       PRO FELD-SEGMENT gesucht, upstream und downstream getrennt.
#   I2 - `bool(parsed.get("important"))` liess jeden nichtleeren String
#       (inkl. dem String "false") als True durch; jetzt nur ein echtes
#       Bool oder die exakten Strings "true"/"false".
#   I3 - `source_field` kam ungeprueft vom Modell; jetzt wird es aus dem
#       tatsaechlich TREFFENDEN Segment abgeleitet (faellt aus C2 ab).
#   I4 - `build_prompt(...)` lag INNERHALB des Transport-try; ein Fehler
#       beim Prompt-Bau (z.B. nicht-serialisierbare Evidence) hiess
#       faelschlich "Transport gescheitert". Jetzt ausserhalb -- ein
#       solcher Fehler ist ein Bug in UNSEREM Code und schlaegt durch.
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
    r"""Normalisierungs-Entscheid (dokumentiert, wie im Auftrag verlangt):

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

    Gemessenes Unicode-Verhalten (M6, 07.08., `re.sub(r"\s+", ...)` unter
    Python 3.11.9 mit Unicode-Strings, nicht ASCII-Modus):
    - GESCHUETZTES Leerzeichen (NBSP, U+00A0) FAELLT in ein normales
      Leerzeichen ZUSAMMEN -- `\s` matched es, weil Python-`str.isspace()`
      es als Whitespace fuehrt (Unicode-Kategorie Zs). Ein per Copy-Paste
      aus einer Webseite eingeschlepptes NBSP im Zitat bricht den
      Vergleich also NICHT.
    - Zero-Width-Space (ZWSP, U+200B) FAELLT NICHT zusammen -- Kategorie
      Cf (Format), kein Whitespace fuer `\s`. Ein Zitat mit eingeschmuggeltem
      ZWSP bleibt ein ANDERER String und findet im echten Katalogtext
      (der kein ZWSP enthaelt) keinen Treffer -- fail-closed, nicht
      fail-open.
    - Homoglyphen (z.B. kyrillisches "а" U+0430 statt lateinischem "a"
      U+0061) werden von `\s+`/`.strip()` ueberhaupt nicht beruehrt --
      unterschiedliche Codepoints bleiben unterschiedliche Codepoints,
      der Substring-Vergleich schlaegt fehl. Ebenfalls fail-closed.
    """
    return re.sub(r"\s+", " ", s).strip()


# --- Zitatpflicht: Mindestlaenge (C1) --------------------------------------
#
# Gemessener Exploit (Opus-Review, 07.08.): quote="e" erfuellte vorher
# "character-for-character im Kontext", weil ein einzelnes Zeichen fast
# immer irgendwo im Text vorkommt -- das ist die BILLIGSTE Art, wie ein
# schwaches Modell die Zitatpflicht syntaktisch erfuellt, ohne inhaltlich
# etwas zu belegen. Zwei UNABHAENGIGE Untergrenzen, beide muessen halten
# (kein XOR): eine lange Zeichenkette ohne Wortgrenzen ("aaaaaaaaaaaa")
# waere sonst genauso ein Fragment wie ein einzelnes Zeichen.
_QUOTE_MIN_CHARS = 12
_QUOTE_MIN_TOKENS = 3


def _quote_too_short(quote_norm: str) -> bool:
    """Prueft auf dem BEREITS whitespace-normalisierten Zitat -- sonst
    liesse sich die Zeichen-Untergrenze mit eingestreuten Leerzeichen
    ("a    b    c") erschleichen, ohne dass mehr Substanz drin waere."""
    return len(quote_norm) < _QUOTE_MIN_CHARS or len(quote_norm.split(" ")) < _QUOTE_MIN_TOKENS


def _parse_important(value) -> bool | None:
    """Nur ein ECHTES Bool zaehlt, oder die exakten Strings "true"/"false"
    (Gross-/Kleinschreibung gleichgueltig) -- alles andere ist ungueltig.

    `bool(x)` (die alte Pruefung, I2) haette JEDEN nichtleeren String als
    True gelesen -- den String "false" eingeschlossen, was die einzige
    Aussage, die dieses Modul ueberhaupt treffen darf (Gewichtung), genau
    umgedreht haette. LLMs geben JSON-Booleans routinemaessig als String
    aus, darum die explizite String-Zuordnung statt eines reinen
    `isinstance(value, bool)`-Verbots.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low == "true":
            return True
        if low == "false":
            return False
    return None


# --- Zitatpflicht: Segmente statt verschmolzenem Korpus (C2) --------------
#
# Vorher wurde `up_ctx["text"] + "\n" + down_ctx["text"]` zu EINEM String
# verschmolzen und DANACH normalisiert -- die Normalisierung ersetzt jeden
# Zeilenumbruch (auch den zwischen zwei FELDERN und den zwischen den
# beiden SEITEN) durch ein einzelnes Leerzeichen. Ein "Zitat", das am
# Ende von Feld A beginnt und am Anfang von Feld B endet (oder gar
# upstream mit downstream verschweisst), sah danach aus wie ein
# zusammenhaengender Treffer, obwohl es das an keiner einzelnen Stelle im
# Katalog je war. Jetzt wird PRO FELD-SEGMENT gesucht, nie ueber ein
# `\n` hinweg -- und upstream/downstream werden als zwei GETRENNTE
# Kontexte geprueft, nie gemeinsam verschmolzen. Die Feld-Labels selbst
# (name/description/owner/glossary/domain) stehen nur hier, direkt im
# `_segments`-Aufbau -- dieselben fuenf wie im `source_field`-Enum im
# Prompt oben, kein zweites Register dafuer.


def _segments(ctx: dict) -> list[tuple[str, str]]:
    """Labeled Feld-Segmente EINES Kontexts (eine Seite), direkt aus den
    STRUKTURIERTEN Feldern gebaut -- nicht aus dem `text`-Blob.

    Nur so laesst sich ein Treffer auf sein tatsaechliches Herkunftsfeld
    zurueckfuehren (I3): ein simples `text.split("\\n")` haette bei
    mehreren Ownern/Glossar-Begriffen mehrere gleich aussehende Zeilen
    geliefert, ohne dass man noch weiss, welche zu welchem Feld gehoert.
    Leere Felder werden nicht als Segment gefuehrt -- ein leerer String
    waere ein Substring von allem und wuerde jede Laengen-Pruefung ad
    absurdum fuehren.
    """
    segs: list[tuple[str, str]] = []
    if ctx.get("name"):
        segs.append(("name", ctx["name"]))
    if ctx.get("description"):
        segs.append(("description", ctx["description"]))
    for owner in ctx.get("owners") or []:
        if owner:
            segs.append(("owner", owner))
    for term in ctx.get("glossary_terms") or []:
        if term:
            segs.append(("glossary", term))
    if ctx.get("domain"):
        segs.append(("domain", ctx["domain"]))
    return segs


def _extract_span(quote_norm: str, original_text: str) -> str:
    """Liefert den TATSAECHLICHEN Ausschnitt aus dem Original-Segment, der
    zum normalisierten Zitat passt -- nicht die Schreibung des Modells
    (M1). Wer die Evidenz spaeter im Katalog nachschlaegt, soll den Text
    finden, der dort wirklich steht (Original-Whitespace inklusive); das
    Modell darf beim Abtippen umformatieren (Mehrfach-Leerzeichen), aber
    was gespeichert wird, bleibt wortwoertlich Katalog-Text.

    Baut ein Regex aus den normalisierten Toerten mit `\\s+` zwischen
    ihnen (statt genau EINEM Leerzeichen), damit auch ein Original mit
    mehrfachem/anderem Whitespace an dieser Stelle noch trifft. Ein
    Fehlschlag hier (sollte bei einem bereits bestaetigten Normalform-
    Treffer nicht vorkommen) faellt sicher auf das normalisierte Zitat
    selbst zurueck, statt eine Exception zu werfen.
    """
    tokens = quote_norm.split(" ")
    pattern = r"\s+".join(re.escape(t) for t in tokens)
    m = re.search(pattern, original_text)
    return m.group(0) if m else quote_norm


def _match_in_context(quote_norm: str, ctx: dict) -> tuple[str, str] | None:
    """Sucht das normalisierte Zitat in den Feld-Segmenten EINER Seite --
    nie ueber zwei Segmente hinweg (C2). Gibt `(Feld-Label,
    Original-Ausschnitt)` beim ersten Treffer zurueck, sonst `None`."""
    for label, text in _segments(ctx):
        if quote_norm in _normalise(text):
            return label, _extract_span(quote_norm, text)
    return None


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

    Reihenfolge der Fehlwege, jeder mit eigenem `fallback_reason` (Fix-
    Runde 1 fuegt Schritte 2b/3b/3c/5b ein, s. Modul-Kommentar oben):
      1. kein Transport injiziert                    -> "kein Transport konfiguriert"
      2. Prompt-Bau schlaegt fehl (I4)                -> KEIN Fallback, propagiert (Bug in unserem Code)
      2b. Transport wirft                             -> "Transport gescheitert (<ExceptionTyp>): <exc>"
      3. Antwort ist kein JSON-Objekt                 -> "Antwort war kein JSON"
      3a. kein (nutzbares) Zitat im JSON               -> "kein Zitat geliefert"
      3b. Zitat zu kurz (C1)                          -> "Zitat zu kurz, kein Beleg"
      3c. `important` ist kein echtes Bool (I2)        -> "important-Feld nicht boolesch"
      3d. `reason` fehlt/ist leer (M4)                 -> "keine Begruendung geliefert"
      5. kein Segment auf keiner Seite lesbar (M2)     -> "kein lesbarer Kontext vorhanden"
      5b. Zitat in keinem Feld-Segment gefunden (C2)   -> "Zitat steht nicht im gelesenen Kontext"

    Garbage-Feldwerte (z.B. `quote` als Zahl statt Text, eine JSON-Antwort,
    die eine Liste statt eines Objekts ist, ein `important` als Liste)
    duerfen NICHT crashen -- sie werden strukturell wie der jeweils
    naechstliegende Fehlweg behandelt, nie mit einer unbehandelten
    Exception durchgereicht. Die EINE Ausnahme ist Schritt 2 (I4): ein
    Fehler beim Bau UNSERES EIGENEN Prompts (z.B. nicht-JSON-serialisier-
    bare Evidence in `verdict.evidence`) ist kein Transport-Ereignis und
    wird nicht als eins getarnt -- er schlaegt durch, wie jeder andere
    Programmfehler auch.
    """
    if transport is None:
        return _fallback(verdict, "kein Transport konfiguriert")

    # I4: AUSSERHALB des try -- ein Fehler hier (z.B. `json.dumps` in
    # `build_prompt` scheitert an einem nicht-serialisierbaren Evidence-
    # Wert) ist ein Bug in UNSEREM Code, kein Transport-Fehlschlag, und
    # darf nicht als "Transport gescheitert" fehletikettiert werden.
    prompt = build_prompt(verdict, up_ctx, down_ctx)

    try:
        raw = transport(prompt)
    except Exception as exc:  # jeder Transportfehler, nicht nur unserer
        return _fallback(verdict, f"Transport gescheitert ({type(exc).__name__}): {exc}")

    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("kein Objekt")
    except Exception:
        return _fallback(verdict, "Antwort war kein JSON")

    quote_raw = parsed.get("quote")
    quote_norm = _normalise(quote_raw) if isinstance(quote_raw, str) else ""
    if not quote_norm:
        return _fallback(verdict, "kein Zitat geliefert")

    if _quote_too_short(quote_norm):
        return _fallback(verdict, "Zitat zu kurz, kein Beleg")

    important = _parse_important(parsed.get("important"))
    if important is None:
        return _fallback(verdict, "important-Feld nicht boolesch")

    reason_raw = parsed.get("reason")
    reason = reason_raw.strip() if isinstance(reason_raw, str) else ""
    if not reason:
        return _fallback(verdict, "keine Begruendung geliefert")

    if not _segments(up_ctx) and not _segments(down_ctx):
        return _fallback(verdict, "kein lesbarer Kontext vorhanden")

    match = _match_in_context(quote_norm, up_ctx) or _match_in_context(quote_norm, down_ctx)
    if match is None:
        return _fallback(verdict, "Zitat steht nicht im gelesenen Kontext")
    matched_field, matched_span = match

    return Judgement(
        edge_key=verdict.edge.key(),
        important=important,
        reason=reason,
        quote=matched_span,  # M1: der TATSAECHLICHE Katalog-Ausschnitt, nicht die Schreibung des Modells
        source_field=matched_field,  # I3: abgeleitet aus dem Treffer, nie vom Modell uebernommen
        used_model=True,
        fallback_reason="",
    )


# --- Task 10: der echte Transport -------------------------------------
#
# Alles oberhalb dieser Zeile ist der Modell-freie/injizierbare Teil und
# bleibt vollstaendig offline testbar. Ab hier: die EINE konkrete
# Anbindung an einen echten Prozess. `runner` existiert ausschliesslich,
# damit kein Test je `subprocess.run` selbst aufruft -- ein Fake steht
# an seiner Stelle, `claude_cli_transport` selbst bleibt ungetestet nur
# in dem Sinn, dass sie NIE mit dem echten Binary getestet wird; das
# Live-Zeugnis dafuer liegt in `harness/runs/judge-transport-probe.json`,
# nicht in der Test-Suite (Hard Rule: offline-only in Tests).
#
# Gemessener Zusatzfund (07.08., live gegen 2.1.223, Beleg im Probe-
# Artefakt): OHNE `--system-prompt` laedt `claude -p` in DIESEM Ordner
# automatisch dieses Repos `CLAUDE.md`/`AGENTS.md` und antwortet als
# volle Coding-Session -- erkennt den eigenen Prompt als Zitat aus
# `judge.py`, kommentiert ihn ("★ Insight ..."), haengt Markdown-Fences
# um das JSON und verfehlt damit die eigene Zitatpflicht-Pruefung, weil
# `raw` dann kein reines JSON-Objekt mehr ist (`judge_edge` faellt in
# genau diesem Fall auf "Antwort war kein JSON" zurueck -- kein Bug in
# `judge_edge`, sondern ein ungeeigneter Rohtext vom Transport). Ein
# expliziter `--system-prompt`, der Werkzeugnutzung und Prosa verbietet,
# behebt das messbar: derselbe Prompt liefert danach ein sauberes
# `{"important": ..., "quote": ...}` ohne Umhuellung. Ohne diesen Fund
# waere die Vorgabe aus dem Architektur-Entscheid (nur `-p` + `--output-
# format json`) auf DIESER Maschine lauffaehig, aber praktisch nutzlos
# gewesen -- jeder Aufruf haette am JSON-Parsing gescheitert, nicht am
# Transport selbst.
_JUDGE_SYSTEM_PROMPT = (
    "You are a strict JSON-only responder. Output only the requested JSON "
    "object and nothing else. Never explain, never use tools, never add "
    "commentary, headers, or markdown code fences."
)
#
# Timeout-Entscheid: 60s. Gemessen (07.08., live gegen `claude -p` mit
# einem trivialen Prompt): `duration_ms` im Umschlag lag bei ~7s fuer
# einen einzelnen Turn ohne Tool-Nutzung. 60s ist damit kein knapper,
# sondern ein grosszuegiger Puffer (~8x) fuer Netzwerk-/Modell-Varianz --
# und vor allem eine harte Grenze gegen den Fall, den die Aufgabe nennt:
# eine haengende CLI (z.B. ein interaktiver Login-Prompt, auf den nie
# jemand antwortet) darf den Ledger-Lauf nicht auf unbestimmte Zeit
# mitreissen. Ein `timeout`-Parameter bleibt injizierbar, falls ein
# Aufrufer mit mehr Kanten pro Lauf einen anderen Wert braucht.
def claude_cli_transport(timeout: int = 60, binary: str = "claude",
                         runner=None) -> JudgeTransport:
    """Vorgabe-Transport auf DIESER Maschine.

    Gemessen 2026-08-07: `claude --version` -> 2.1.223, ANTHROPIC_API_KEY
    ist NICHT gesetzt, `claude -p ... --output-format json` laeuft trotzdem
    (eigene Session-Authentifizierung, kein API-Key noetig) und liefert
    ein JSON-Objekt mit einem `result`-Feld -- LIVE bestaetigt, nicht nur
    aus der Doku uebernommen (Beleg: `harness/runs/judge-transport-probe.json`).
    Deshalb die CLI und nicht das SDK -- eine Vorgabe, die an einer
    fehlenden Umgebungsvariable scheitert, ist keine.

    `runner` ist injizierbar (Vorgabe `subprocess.run`) -- jeder Test in
    `tests/test_judge.py` uebergibt einen Fake, nie den echten Prozess
    (Hard Rule: offline-only). Drei Fehlwege, jeder wird zu einem
    benannten `JudgeTransportError` und NIE zu einer leeren Antwort:
      1. Timeout       -> eigene Meldung mit der Sekundenzahl
      2. Prozess nicht startbar (Binary fehlt) -> eigene Meldung
      3. Exit-Code != 0 -> Exit-Code + stderr woertlich (gekappt auf 300
         Zeichen, damit ein wortreicher Fehlertext das Artefakt nicht
         sprengt -- die ersten 300 Zeichen tragen bei einer CLI-
         Fehlermeldung fast immer schon die Ursache, z.B. "not logged in").
         Review-Notiz (Fix-Runde 1): der Auftrag verlangt "den EXAKTEN
         stderr/exit-code-Text" -- diese Kappung ist eine bewusste,
         benannte Abweichung davon, keine uebersehene. Eine unbegrenzte
         CLI-Fehlermeldung koennte theoretisch beliebig lang werden (z.B.
         ein voller Stacktrace); 300 Zeichen sind reichlich fuer jede
         bisher beobachtete Fehlerklasse dieser CLI (Login-Fehler,
         Netzwerkfehler, Rate-Limit), aber eine echte Grenze, kein
         Versehen.
      4. Umschlag kein lesbares JSON mit `result`-Feld -> eigene Meldung

    Das Feld `result` im JSON-Umschlag ist LIVE bestaetigt (s.o.), keine
    Annahme mehr. Weicht die Struktur auf einer anderen Maschine/Version
    ab, wird HIER korrigiert -- nicht in `judge_edge`, das den Umschlag
    nie sieht (der Transport reicht nur den rohen Modell-Text durch).

    `--system-prompt` ist Pflicht, kein Komfort (s. Modul-Kommentar oben):
    ohne ihn laedt die CLI dieses Repos eigene `CLAUDE.md` und antwortet
    als Coding-Agent statt als JSON-Antworter -- gemessen, nicht vermutet.
    """
    run_proc = runner or subprocess.run

    def send(prompt: str) -> str:
        cmd = [binary, "-p", prompt, "--output-format", "json",
               "--system-prompt", _JUDGE_SYSTEM_PROMPT]
        try:
            proc = run_proc(cmd, capture_output=True, text=True,
                            timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise JudgeTransportError(
                f"{binary} -p: Zeitueberschreitung nach {timeout}s")
        except OSError as exc:
            raise JudgeTransportError(
                f"{binary} -p: Prozess nicht startbar ({exc})")

        if proc.returncode != 0:
            raise JudgeTransportError(
                f"{binary} -p exit {proc.returncode}: {(proc.stderr or '')[:300]}")

        try:
            parsed = json.loads(proc.stdout)
            result = parsed.get("result", "")
        except Exception as exc:
            raise JudgeTransportError(f"{binary} -p: Umschlag nicht lesbar ({exc})")
        return result

    return send


# --- Task 10: nur AUFFAELLIGE Kanten bekommen ein Urteil ----------------
#
# Der Lastentwurf der Spec (s. Docstring unten): der teure Teil (ein
# Modellaufruf pro Kante) haengt an der Zahl der Abweichungen, nicht an
# der Gesamtzahl der Kanten. `confirmed` braucht kein Urteil -- der
# deterministische Befund steht bereits fest und ist die guenstigste,
# belastbarste Aussage, die es dazu gibt.
DEVIATING_STATES = ("dead", "missing", "unknown")


def _verdict_from_json(row: dict) -> EdgeVerdict:
    """Baut aus EINER bereits klassifizierten Ledger-Zeile (dict, wie sie
    `EdgeVerdict.to_json()` erzeugt hat) wieder ein `EdgeVerdict`, damit
    `judge_edge` denselben Typ bekommt wie im Direktaufruf.

    `coverage`/`timeline` werden bewusst mit leeren Platzhaltern gefuellt,
    nicht aus der Zeile rekonstruiert: weder `build_prompt` noch
    `judge_edge` lesen diese beiden Felder (s. `EdgeVerdict`-Nutzung oben
    in dieser Datei) -- sie tragen nur `edge.key()`, `state` und
    `evidence` in den Prompt. Eine vollstaendige Rekonstruktion aus der
    flachen `to_json()`-Form waere verlorene Arbeit fuer Werte, die nie
    gelesen werden.
    """
    return EdgeVerdict(
        edge=Edge(row["upstream"], row["downstream"]),
        state=row["state"], evidence=row.get("evidence") or {},
        coverage=Coverage(0, None, None, ""), timeline=Timeline(()),
    )


def judge_ledger(gms, ledger: dict, transport: JudgeTransport | None,
                 limit: int = 20) -> list[dict]:
    """Urteilt nur ueber ABWEICHENDE Kanten.

    Bestaetigte Kanten brauchen kein Urteil -- und der teure Teil haengt
    damit an der Zahl der Auffaelligkeiten, nicht an der Gesamtzahl der
    Kanten (Lastentwurf der Spec: wenige Detailabruf statt Zehntausende).
    `limit` ist ein hartes Sicherheitsnetz obendrauf, kein Ersatz fuer den
    Filter -- selbst bei vielen Abweichungen bricht ein Lauf nicht durch
    einen unbegrenzten Modell-Fächer.

    Kontext-Cache pro URN, nicht pro Kante: ein Dataset kann auf beiden
    Seiten mehrerer Kanten auftauchen (z.B. als Downstream von A und
    Upstream von B), und `gather_context` waere sonst ein wiederholter
    GraphQL-Aufruf fuer denselben Inhalt -- API-Aufrufzahl ist eine
    gemessene Groesse in diesem Projekt (`_Counting` in `ledger.py`),
    kein Nebenschauplatz.
    """
    rows = [r for r in ledger.get("edges", []) if r.get("state") in DEVIATING_STATES][:limit]
    ctx_cache: dict[str, dict] = {}

    def ctx(urn: str) -> dict:
        if urn not in ctx_cache:
            ctx_cache[urn] = gather_context(gms, urn)
        return ctx_cache[urn]

    return [
        judge_edge(_verdict_from_json(r), ctx(r["upstream"]), ctx(r["downstream"]),
                   transport).to_json()
        for r in rows
    ]
