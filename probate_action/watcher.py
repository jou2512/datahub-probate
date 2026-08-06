"""Rueckfall-Waechter.

Wer nach der Unterschrift wieder auf den Vorgaenger zugreift, verliert sie.

Belegte Falle: der naheliegende Schleifen-Schutz - Ereignisse vom eigenen
Actor ignorieren - traegt NICHT. Ingest, Propagation und eigene Schreibvorgaenge
sind ueber den Actor nicht unterscheidbar. Deshalb wird ueber den ASPEKT
gefiltert, nicht ueber den Actor.

Der Live-Start der Kafka-Action-Pipeline (Plantext Step 5,
`datahub-actions run -c probate_action/recipe.yml`) wurde in dieser Session
BEWUSST NICHT ausgefuehrt: dieser Task ist im Bauplan (STAND.md, Cutline)
der erste Streichkandidat bei Zeitmangel, und ein echter Pipeline-Lauf
haette eine zusaetzliche Kafka-Konsumentengruppe gegen eine der beiden
Instanzen offen gehalten, ohne dass in dieser Session Ereignisse erzeugt
wuerden, die ihn pruefbar machen. `is_relapse()` und `ProbateWatcher` sind
vollstaendig getestet (Unit-Ebene, gefaelschte Events); der reine
Pipeline-Start ist ungeprueft und wird als solcher gefuehrt, nicht als
funktionierend behauptet.
"""

from __future__ import annotations

import json
from pathlib import Path

from datahub_actions.action.action import Action

ACCESS_ASPECTS = {"operation", "datasetUsageStatistics", "queryUsageStatistics"}


def is_relapse(event: dict, closed_urns: set[str]) -> bool:
    urn = event.get("entityUrn")
    if not urn or urn not in closed_urns:
        return False
    return event.get("aspectName") in ACCESS_ASPECTS


def _relapse_incident_q(urn: str) -> str:
    return f'''mutation {{ raiseIncident(
        input: {{ resourceUrn: "{urn}", type: OPERATIONAL,
                  title: "Probate: Rueckfall auf abgeloeste Tabelle",
                  description: "Ein Konsument greift nach der Unterschrift wieder auf den Vorgaenger zu." }}
      ) }}'''


class ProbateWatcher(Action):
    """Reagiert auf Metadata-Change-Log-Events fuer bereits abgeschlossene
    (`closed_urns`) Ziel-Datasets. Ein Zugriffs-Ereignis (nicht: ein
    Metadaten-Schreibvorgang) auf ein geschlossenes Dataset ist ein
    Rueckfall und wird ueber Writeback als Incident gemeldet.
    """

    def __init__(self, closed_urns: set[str], wb) -> None:
        self.closed_urns = closed_urns
        self.wb = wb

    @classmethod
    def create(cls, config_dict: dict, ctx) -> "ProbateWatcher":
        from probate.gms import Gms
        from probate.writeback import Writeback

        path = Path(config_dict.get("closed_urns_file", "harness/runs/closed.json"))
        try:
            closed = set(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            # Kein Rueckfall-Katalog bedeutet keinen Rueckfall, nicht einen
            # Crash der Pipeline -- der Waechter startet leer und waechst,
            # sobald Task 9 (campaign.py) den ersten Abschluss journalisiert.
            closed = set()
        gms = Gms(base_url=config_dict.get("gms_url", "http://localhost:28080"))
        wb = Writeback(gms, dry_run=config_dict.get("dry_run", True))
        return cls(closed, wb)

    def act(self, event) -> bool | None:
        mcl = getattr(event, "event", event)
        as_dict = {
            "entityUrn": getattr(mcl, "entityUrn", None),
            "aspectName": getattr(mcl, "aspectName", None),
        }
        if is_relapse(as_dict, self.closed_urns):
            self.wb.mutation("raiseIncident", _relapse_incident_q(as_dict["entityUrn"]))
        return True

    def close(self) -> None:
        pass
