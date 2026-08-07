"""Der Korrektur-Modus: aus einem Befund wird ein Vorschlag.

Warum diese Datei existiert: das Register sagt, was nicht stimmt. Damit
daraus eine Handlung wird, braucht es einen Vorschlag mit Beleg, den ein
Mensch bestaetigt -- nicht ein Werkzeug, das den Katalog nach eigenem
Urteil umschreibt.

`writeback.py` bleibt unveraendert; dieses Modul ist ein Aufrufer, kein
zweiter Schreibweg. Und `propose()` bekommt bewusst kein gms und kein
Writeback: was nicht schreiben kann, schreibt auch nicht versehentlich.

Auf `unknown` wird NIE etwas vorgeschlagen. Bei fehlender Datenlage ist
jeder Schreibvorgang ein Schreibvorgang auf Verdacht -- genau der Fehler,
den Schicht 1 behebt.

Messschritt (07.08., `harness/runs/upstream-properties-probe.json`):
`UpstreamLineage.upstreams[].properties` (Map) uebersteht einen echten
Schreib-/Lesezyklus gegen 28080 (`properties_survived: true`, live
gemessen, seeded=true). Deshalb schreibt `mark_dead` kanten-genau auf
`upstreamLineage` mit `properties["probate.dead_since"]`, nicht auf ein
tabellenbezogenes Feld wie `deprecation` -- ein Marker auf der Tabelle
wuerde JEDE Kante als tot ausweisen, nicht nur die gemessene.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Proposal:
    """Ein Vorschlag traegt IMMER seinen Beleg -- `evidence` hat keinen
    Default, ein Proposal ohne Beleg laesst sich also nicht konstruieren
    (siehe tests/test_correct.py, test_a_proposal_cannot_be_constructed_
    without_evidence)."""

    kind: str
    edge_key: str
    target_urn: str
    aspect: str
    evidence: dict
    human_summary: str

    def to_json(self) -> dict:
        return {
            "kind": self.kind, "edge": self.edge_key, "target_urn": self.target_urn,
            "aspect": self.aspect, "evidence": self.evidence,
            "human_summary": self.human_summary,
        }


def propose(ledger: dict) -> list[Proposal]:
    """Liest ein `ledger.py::run()`-Artefakt (bzw. dessen Testform) und
    erzeugt aus jeder nicht-`unknown`-Kante genau einen Vorschlag.

    Signatur bewusst einparametrig (`ledger` allein) -- kein `gms`, kein
    `writeback`: diese Funktion kann strukturell nicht schreiben.
    """
    out: list[Proposal] = []
    for row in ledger.get("edges", []):
        state, ev = row.get("state"), row.get("evidence") or {}
        tl = row.get("timeline") or {}
        up, down, key = row["upstream"], row["downstream"], row["edge"]

        if state == "missing":
            out.append(Proposal(
                kind="add_edge", edge_key=key, target_urn=down,
                aspect="upstreamLineage",
                evidence={"query_urns": ev.get("query_urns", []),
                          "cooccurrence_count": ev.get("cooccurrence_count", 0),
                          "direction_evidence": ev.get("direction_evidence", "")},
                human_summary=(
                    f"Kante {key} in {ev.get('cooccurrence_count', 0)} Abfrage(n) beobachtet, "
                    f"aber nicht deklariert. Beleg: {', '.join(ev.get('query_urns', [])) or '-'}. "
                    f"Richtung ist ungerichtet aus Ko-Okkurrenz erschlossen, nicht gemessen."),
            ))
        elif state == "dead":
            out.append(Proposal(
                kind="mark_dead", edge_key=key, target_urn=down,
                aspect="upstreamLineage",
                evidence={"last_covered_ms": tl.get("last_covered_ms"),
                          "dead_since_days": tl.get("dead_since_days"),
                          "dead_since_is_lower_bound": tl.get("dead_since_is_lower_bound", False),
                          "buckets_checked": ev.get("buckets_checked", 0)},
                human_summary=(
                    f"Kante {key} seit {tl.get('dead_since_days')} Tagen ohne gemessenen "
                    f"Verkehr, geprueft ueber {ev.get('buckets_checked', 0)} Zeitfenster."),
            ))
        elif state == "confirmed":
            out.append(Proposal(
                kind="enrich_doc", edge_key=key, target_urn=down,
                aspect="editableDatasetProperties",
                evidence={"query_urns": ev.get("query_urns", []),
                          "last_covered_ms": tl.get("last_covered_ms")},
                human_summary=(
                    f"Beobachtete Nutzung von {up} dokumentieren "
                    f"({len(ev.get('query_urns', []))} Abfrage(n))."),
            ))
        # state == "unknown" (oder ein unbekannter Wert): bewusst kein
        # Zweig -- fehlende Datenlage erzeugt keinen Vorschlag.
    return out
