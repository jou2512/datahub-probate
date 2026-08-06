"""Der fehlende Auswerter.

DataHub speichert testResults auf 24 Entitaetstypen, indiziert sie
(hasFailingTests, failingTests) und zeigt sie an - fuehrt aber keinen
einzigen Test aus. createTest nimmt sogar nicht-parsbaren Muell an.
Wer den Auswerter mitbringt, erbt Oberflaeche und Suche geschenkt.
"""

from __future__ import annotations

import hashlib
import inspect
import sys
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    check: Callable[[dict], bool]

    @property
    def urn(self) -> str:
        return f"urn:li:test:{self.id}"

    @property
    def definition_md5(self) -> str:
        try:
            src = inspect.getsource(self.check)
        except (OSError, TypeError):
            src = repr(self.check)
        return hashlib.md5(f"{self.id}|{self.description}|{src}".encode()).hexdigest()


@dataclass(frozen=True)
class RuleOutcome:
    rule_id: str
    urn: str
    passed: bool
    definition_md5: str
    errored: str | None = None
    """Live-Fund (2026-08-06, Jury-Review): eine werfende Regel wurde bisher
    lautlos zu FAILURE -- nicht unterscheidbar von einer Regel, die
    tatsaechlich geprueft hat und Nein sagt. Ein kaputtes Rule-Objekt
    (z.B. KeyError nach einer Schema-Aenderung) haette fuer immer wie ein
    sauberes, gepruftes Nein ausgesehen. TestResults.pdl kennt nur
    SUCCESS/FAILURE (kein drittes Feld moeglich), also bleibt der
    DataHub-Aspekt bei FAILURE -- aber lokal (hier, in errored) und auf
    stderr wird der Fehler laut, statt sich in der stillen Mehrheit der
    echten Failures zu verstecken."""


def evaluate(rules: list[Rule], facts: dict) -> list[RuleOutcome]:
    outcomes = []
    for rule in rules:
        errored = None
        try:
            passed = bool(rule.check(facts))
        except Exception as exc:  # noqa: BLE001 - eine geworfene Regel ist ein Nein, kein Ja,
            # aber ein LAUTES Nein: siehe RuleOutcome.errored oben.
            passed = False
            errored = f"{type(exc).__name__}: {exc}"
            print(f"  WARNUNG: Regel '{rule.id}' ist gescheitert, nicht fehlgeschlagen: "
                  f"{errored}", file=sys.stderr)
        outcomes.append(RuleOutcome(rule.id, rule.urn, passed, rule.definition_md5, errored))
    return outcomes


def test_results_aspect(outcomes: list[RuleOutcome], evaluated_at: int) -> dict:
    """Baut den `testResults`-Aspekt.

    `evaluated_at` wird NICHT in den Aspekt geschrieben: die echte
    TestResults.pdl (metadata-models/.../com/linkedin/test/TestResults.pdl,
    Quelle gelesen 2026-08-06) kennt nur `failing` und `passing`, kein
    Zeitstempelfeld. Ein frueherer Versuch mit einem erfundenen
    `lastComputed`-Feld wurde von REST v3 stillschweigend akzeptiert und
    beim Ruecklesen verworfen -- HTTP 200 ohne Wirkung, exakt die
    Fehlerklasse, die dieses Projekt vermeiden will. `evaluated_at` bleibt
    Teil der Signatur, weil der Aufrufer (Task 8/11) den Zeitpunkt fuer
    das eigene Journal/`examples/`-Artefakt braucht - nur eben nicht als
    DataHub-Aspektfeld.
    """
    def entry(o: RuleOutcome) -> dict:
        return {"test": o.urn, "type": "SUCCESS" if o.passed else "FAILURE"}

    return {
        "passing": [entry(o) for o in outcomes if o.passed],
        "failing": [entry(o) for o in outcomes if not o.passed],
    }
