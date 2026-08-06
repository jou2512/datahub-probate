"""Zwei Zielmengen, und ihre Differenz ist selbst ein Ergebnis.

deklariert ohne gemessen -> Karteileiche, kann mitsterben
gemessen ohne deklariert -> fehlende Lineage, wird ergaenzt
"""

from __future__ import annotations

from dataclasses import dataclass

from probate.gms import Gms


@dataclass(frozen=True)
class Targets:
    both: set[str]
    declared_only: set[str]
    measured_only: set[str]

    @property
    def live(self) -> set[str]:
        """Wer die Abloesung wirklich aufhaelt."""
        return self.both | self.measured_only

    @property
    def missing_lineage(self) -> set[str]:
        return self.measured_only

    @property
    def dead_wood(self) -> set[str]:
        return self.declared_only

    def summary(self) -> dict:
        return {
            "live": len(self.live),
            "dead_wood": len(self.dead_wood),
            "missing_lineage": len(self.missing_lineage),
        }


def classify(declared: set[str], measured: set[str]) -> Targets:
    return Targets(
        both=declared & measured,
        declared_only=declared - measured,
        measured_only=measured - declared,
    )


_LINEAGE_Q = """
query($urn: String!) {
  dataset(urn: $urn) {
    lineage(input: {direction: DOWNSTREAM, start: 0, count: 200}) {
      relationships { entity { urn } }
    }
  }
}
"""

# Gegen v1.5.0.6 verifiziert (2026-08-06). Die im Plantext vorgesehene
# _QUERIES_Q (Dataset.relationships mit types wie "IsAssociatedWith") gibt es
# NICHT -- fuenf Kandidaten-Namen live geprueft, alle 0 Treffer trotz eines
# real vorhandenen Query-Subjects. QuerySubject.entity ist stattdessen als
# @Searchable(fieldName: "entities") indexiert (Quelle gelesen, nicht geraten:
# metadata-models/src/main/pegasus/com/linkedin/query/QuerySubject.pdl auf
# github.com/datahub-project/datahub). Der funktionierende Weg ist eine Suche
# auf QUERY-Entitaeten gefiltert auf das Feld "entities", live bestaetigt:
# searchAcrossEntities lieferte total=1 fuer ein zuvor geschriebenes Query-Subject.
_QUERY_SEARCH_Q = """
query($urn: String!) {
  searchAcrossEntities(input: {
    types: [QUERY], query: "*", count: 200,
    orFilters: [{ and: [{ field: "entities", values: [$urn] }] }]
  }) {
    total
    searchResults { entity { urn } }
  }
}
"""


def fetch_declared(gms: Gms, urn: str) -> set[str]:
    data = gms.graphql(_LINEAGE_Q, {"urn": urn})
    rels = (data.get("dataset") or {}).get("lineage", {}).get("relationships", [])
    return {r["entity"]["urn"] for r in rels if r.get("entity")}


def fetch_measured(gms: Gms, urn: str) -> set[str]:
    """Konsumenten aus dem Query-Log.

    Ein Query-Subject nennt das gelesene Dataset; die Konsumenten sind die
    anderen Subjects derselben Queries (z.B. eine INSERT-INTO-SELECT-Query,
    die `urn` liest und ein Zieldataset schreibt -- beide stehen als
    Subjects auf derselben Query-Entitaet). Wo das Log leer ist, ist das
    Ergebnis leer - und das wird als 'nicht gemessen' berichtet, nicht als
    'niemand liest es'.
    """
    hits = gms.graphql(_QUERY_SEARCH_Q, {"urn": urn})
    query_urns = [
        r["entity"]["urn"]
        for r in (hits.get("searchAcrossEntities") or {}).get("searchResults", [])
    ]
    consumers: set[str] = set()
    for q_urn in query_urns:
        aspect = gms.get_aspect("query", q_urn, "querysubjects")
        if not aspect:
            continue
        subjects = (aspect.get("value") or {}).get("subjects", [])
        for s in subjects:
            other = s.get("entity")
            if other and other != urn:
                consumers.add(other)
    return consumers
