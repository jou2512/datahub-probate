"""Prueft die Prosa gegen die Lauf-Artefakte.

Jede Zahl im README, im Devpost-Text und im Video-Drehbuch wird aus
harness/runs/ neu hergeleitet. Bei Abweichung Exit 1.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

RUNS = Path("harness/runs")

# Explizite Liste statt Glob ueber harness/runs/*.json: eine Datei, die
# zufaellig im Ordner landet (ein Scratch-Dump, ein Log-Rest), soll nie
# stillschweigend zur Behauptungs-Quelle werden. Ein neuer Eintrag hier
# ist eine bewusste Entscheidung, nicht ein Nebeneffekt eines neuen
# Lauf-Skripts. Stand 2026-08-07: campaign (Formular-Kampagne), ledger
# (Vier-Zustaende-Kanten-Zaehlung), seedlab-verdicts (das geseedete
# Vier-Zustaende-Labor selbst), loadgen/loadtest (Lasttest-Fixtures und
# -Messungen je Groesse s/m/l), query-timestamp-probe (Zeitfeld-Sondierung).
RUN_FILES = (
    "campaign.json",
    "ledger.json",
    "seedlab-verdicts.json",
    "loadgen_smoke.json",
    "loadtest_smoke.json",
    "loadtest_s.json",
    "loadtest_m.json",
    "loadtest_l.json",
    "query-timestamp-probe.json",
)


class ConflictingClaim(ValueError):
    """Zwei Lauf-Artefakte behaupten denselben Schluessel verschieden.

    Das Modell ist 'ein Artefakt = eine Behauptung eines Laufs'. Tragen
    zwei Artefakte denselben Schluessel mit unterschiedlichem Wert, ist
    das ein Befund -- zwei Laeufe widersprechen sich, oder ein
    Schluesselname wurde versehentlich zweimal vergeben -- und kein Fall
    fuer 'der letzte gewinnt'. Eine Zahl im README, die aus einem
    stillschweigend ueberschriebenen Wert entstuende, waere nicht mehr
    herleitbar.
    """


def _run_file_status(runs: Path = RUNS) -> tuple[list[str], list[str]]:
    """Welche der bekannten Lauf-Artefakte gerade existieren.

    Getrennt von 'nicht geprueft': jede Datei in RUN_FILES wird explizit
    auf Existenz getestet und landet in genau einer der beiden Listen.
    Ein fehlendes Artefakt ist kein Fehler (nicht jeder Lauf hat schon
    stattgefunden) -- aber 'ich habe nachgesehen, es ist nicht da' ist
    etwas anderes als 'ich habe nie nachgesehen', und der Aufrufer soll
    das unterscheiden koennen.
    """
    found = [name for name in RUN_FILES if (runs / name).exists()]
    missing = [name for name in RUN_FILES if name not in found]
    return found, missing


def load_runs(runs: Path = RUNS) -> dict:
    """Alle bekannten Lauf-Artefakte zu einer flachen Zahlen-Tabelle.

    Nur Skalare (Zahl, Wahrheitswert, kurzer Text) werden gemerged: eine
    Behauptung in der Prosa ist immer eine dieser drei Formen. Verschach-
    teltes (Kantenlisten, Zeitreihen, das 'pairs'-Objekt in
    seedlab-verdicts.json) ist Beleg fuer eine Behauptung, keine
    Behauptung selbst -- es wird uebersprungen statt unter einem
    erfundenen gepunkteten Schluessel (z. B. 'pairs.confirmed.state') zu
    erscheinen, den ohnehin keine claims.json referenziert. Sollte eine
    verschachtelte Zahl je in der Prosa auftauchen, ist der richtige Ort
    dafuer ein eigener skalarer Schluessel im erzeugenden Lauf-Skript --
    nicht ein Auto-Flatten hier.

    Fehlende Dateien werden uebersprungen (siehe _run_file_status).
    Findet sich eine Datei, laesst sich aber nicht als JSON lesen, ist
    das kein 'fehlt' -- es wird laut als eigener Fehler gemeldet, damit
    'da, aber kaputt' nicht wie 'nicht da' aussieht.
    """
    merged: dict = {}
    origin: dict[str, str] = {}
    for name in RUN_FILES:
        p = runs / name
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{name}: gefunden, aber nicht als JSON lesbar ({exc})"
            ) from exc
        for k, v in data.items():
            if not isinstance(v, (int, float, bool, str)):
                continue
            if k in merged and merged[k] != v:
                raise ConflictingClaim(
                    f"{k}: {origin[k]} behauptet {merged[k]!r}, "
                    f"{name} behauptet {v!r}"
                )
            merged[k] = v
            origin[k] = name
    return merged


@dataclass(frozen=True)
class ClaimResult:
    name: str
    ok: bool
    detail: str


def check_claim(name: str, claimed, measured) -> ClaimResult:
    if measured is None:
        return ClaimResult(name, False, f"behauptet {claimed}, aber nicht gemessen")
    ok = claimed == measured
    return ClaimResult(name, ok, f"behauptet {claimed}, gemessen {measured}")


def main() -> int:
    # RUNS explizit durchreichen statt auf den Default-Parameter zu
    # verlassen: ein Default wird beim def einmal gebunden, ein
    # spaeteres Ueberschreiben des Modul-Attributs (z. B. per monkeypatch
    # in Tests) wuerde ihn sonst nie erreichen.
    found, missing = _run_file_status(RUNS)
    print(f"  gelesen:          {', '.join(found) if found else '(keine)'}")
    print(f"  nicht vorhanden:  {', '.join(missing) if missing else '(keine)'}")

    try:
        run = load_runs(RUNS)
    except ConflictingClaim as exc:
        print(f"\n  WIDERSPRUCH ZWISCHEN LAUF-ARTEFAKTEN: {exc}")
        return 1
    except ValueError as exc:
        print(f"\n  LAUF-ARTEFAKT NICHT LESBAR: {exc}")
        return 1

    if not run:
        print("  Kein Lauf-Artefakt - es gibt nichts zu behaupten.")
        return 1

    claims = json.loads((RUNS / "claims.json").read_text(encoding="utf-8"))
    results = [
        check_claim(k, claims.get(k), run.get(k)) for k in sorted(claims)
    ]
    for r in results:
        print(f"  {'OK  ' if r.ok else 'FEHL'}  {r.name:<24} {r.detail}")
    failed = [r.name for r in results if not r.ok]
    if failed:
        print(f"\n  DRIFT: {', '.join(failed)}")
        return 1
    print(f"\n  Alle {len(results)} Zahlen decken sich mit den Laeufen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
