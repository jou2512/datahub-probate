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
