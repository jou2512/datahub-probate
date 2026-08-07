"""Rueckfall-Waechter.

Wer nach der Unterschrift wieder auf den Vorgaenger zugreift, verliert sie.

Belegte Falle: der naheliegende Schleifen-Schutz - Ereignisse vom eigenen
Actor ignorieren - traegt NICHT. Ingest, Propagation und eigene Schreibvorgaenge
sind ueber den Actor nicht unterscheidbar. Deshalb wird ueber den ASPEKT
gefiltert, nicht ueber den Actor.

Live gemessen (2026-08-07, Task 15, harness/runs/watcher-live.json):
der Pipeline-Start funktioniert -- `datahub-actions --debug actions -c
probate_action/recipe.yml` (Debug-Flag VOR `actions`, sonst bleibt die
gesamte datahub_actions-Logger-Hierarchie stumm, siehe watcher-live.json
"findings") registriert sich gegen den Kafka-Bootstrap `localhost:29192`
und abonniert `MetadataChangeLog_Versioned_v1`,
`MetadataChangeLog_Timeseries_v1`, `PlatformEvent_v1`. Ein echtes,
per REST-Emitter erzeugtes `datasetUsageStatistics`-Ereignis auf einer
in `closed_urns` gefuehrten URN wurde von der laufenden Pipeline
innerhalb derselben Sekunde empfangen (Protokollzeile:
"Kafka msg received: MetadataChangeLog_Timeseries_v1, 2, 52",
03:28:29,277 Uhr) und ohne folgenden Traceback verarbeitet. Insgesamt
wurden 10 Kafka-Nachrichten in diesem Lauf empfangen, davon erfuellt
exakt 1 beide `is_relapse()`-Bedingungen. Die Ledger-Neubewertung
(Schritt 6) blieb dagegen ohne sichtbare Aenderung -- `usageStats`
liest eine vorab aggregierte Sicht, keine rohen Zeitreihen-Aspekte, und
in dieser Umgebung laeuft nachweislich keine separate
Analytics-Indexierung. `is_relapse()` und `ProbateWatcher` sind auf
Unit-Ebene vollstaendig getestet (gefaelschte Events); der Pipeline-Start
selbst ist jetzt live geprueft, nicht nur unit-getestet -- Details und
Protokollzitate in `harness/runs/watcher-live.json`.
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
