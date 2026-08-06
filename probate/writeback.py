"""Der einzige Schreibweg. Nichts geht daran vorbei.

Vorgabe ist dry-run. Jeder echte Schreibvorgang sichert vorher den
bestehenden Aspekt in ein Journal, damit ein Rueckwaertsgang existiert.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WriteResult:
    applied: bool
    before: dict | None
    detail: str = ""


class Writeback:
    def __init__(self, gms, dry_run: bool = True, journal_path: str = "harness/runs/journal.jsonl"):
        self.gms = gms
        self.dry_run = dry_run
        self.journal_path = Path(journal_path)

    def _journal(self, entry: dict) -> None:
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def aspect(self, entity_type: str, urn: str, aspect: str, value: dict) -> WriteResult:
        before = self.gms.get_aspect(entity_type, urn, aspect)
        if self.dry_run:
            return WriteResult(False, before, f"dry-run: {aspect} auf {urn}")
        self._journal(
            {"entity_type": entity_type, "urn": urn, "aspect": aspect, "before": before}
        )
        self.gms.upsert(entity_type, [{"urn": urn, aspect: {"value": value}}])
        return WriteResult(True, before, f"{aspect} auf {urn} geschrieben")

    def mutation(self, name: str, query: str) -> WriteResult:
        """GraphQL-Mutations sind nicht aspektweise rueckrollbar.

        Sie werden trotzdem journalisiert, damit im Nachhinein sichtbar ist,
        was passiert ist - mit einem ausdruecklichen Vermerk.
        """
        if self.dry_run:
            return WriteResult(False, None, f"dry-run: {name}")
        self._journal({"mutation": name, "before": None, "reversible": False})
        self.gms.graphql(query)
        return WriteResult(True, None, f"{name} ausgefuehrt")

    def revert_all(self) -> int:
        """Rollt jeden journalisierten Aspekt-Schreibvorgang zurueck.

        Ein Aspekt, der vorher NICHT existierte (before is None), ist der
        Normalfall bei probate -- die meisten Ziel-Datasets sind noch nicht
        deprecated. Live gemessen (2026-08-06): ein zurueckgeschriebenes
        None ergibt keinen leeren Aspekt, sondern eine 400er-Validierung
        (z.B. Deprecation.actor ist Pflichtfeld) -- der Revert wuerde also
        entweder fehlschlagen oder einen erfundenen Leerwert erzeugen.
        Richtig ist: den Aspekt LOESCHEN, nicht auf None schreiben.
        """
        if not self.journal_path.exists():
            return 0
        entries = [
            json.loads(line)
            for line in self.journal_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        count = 0
        for e in reversed(entries):
            if "aspect" not in e:
                continue
            if e.get("before") is None:
                self.gms.delete_aspect(e["entity_type"], e["urn"], e["aspect"])
            else:
                before_value = e["before"].get("value", e["before"])
                self.gms.upsert(
                    e["entity_type"], [{"urn": e["urn"], e["aspect"]: {"value": before_value}}]
                )
            count += 1
        return count
