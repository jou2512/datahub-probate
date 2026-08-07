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
# Lauf-Skripts. Stand 2026-08-07 (Task 25): campaign (Formular-Kampagne),
# ledger (Vier-Zustaende-Kanten-Zaehlung), seedlab-verdicts (das geseedete
# Vier-Zustaende-Labor selbst), loadgen/loadtest (Lasttest-Fixtures und
# -Messungen je Groesse s/m/l), query-timestamp-probe (Zeitfeld-Sondierung),
# judge-seedlab-matrix (Modell-Urteile ueber alle vier Zustaende),
# correct-roundtrip (Revert-Rundlauf: schreiben, pruefen, exakt zurueck),
# watcher-live (der Live-Waechter gegen echten Kafka-Traffic),
# upstream-properties-probe (ueberleben Custom-Properties den Writeback).
# loadtest_l.json war hier bis 2026-08-07 ABSICHTLICH ausgeschlossen: die
# Datei trug ihr eigenes 'cleanup_pending_note', das woertlich sagte, der
# Lauf werde 'nach Abschluss des separaten Aufraeum-Laufs ... nachgetragen'
# -- eine andere Lane schrieb noch daran, und eine Zahl aus einem Artefakt
# zu behaupten, das laut eigener Aussage noch nicht fertig ist, waere keine
# Messung, sondern eine Wette auf den naechsten Schreibvorgang. Der Lauf ist
# seit derselben Nacht abgeschlossen (Stufe L: Seed-Abbruch bei 735s, danach
# vollstaendig verifiziertes Cleanup, 'cleanup_pending_note' ist aus der Datei
# verschwunden) -- die Datei ist jetzt eine fertige Behauptung wie jede
# andere hier und gehoert in dieselbe Liste. Beachte: 'loadtest_l_extrapolation'
# bleibt trotzdem unbehauptbar, weil es ein VERSCHACHTELTES Objekt ist (der
# Loader flacht nur Top-Level-Skalare ab, s. load_runs()-Docstring) -- die
# Hochrechnung kann so nie versehentlich als auditierte Messung erscheinen,
# nur die tatsaechlich gemessenen Top-Level-Zahlen der abgebrochenen Seed-Phase.
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
    "judge-seedlab-matrix.json",
    "correct-roundtrip.json",
    "watcher-live.json",
    "upstream-properties-probe.json",
    "full-vs-delta.json",
    "mcp-probe.json",
)
# mcp-probe.json (aufgenommen 2026-08-07): die eigene Messung von DataHubs
# MCP-Server, erzeugt von harness/mcp_probe.py. Sie traegt die Zahlen, mit
# denen das README ueberhaupt erst etwas ueber den MCP-Weg sagen darf --
# Werkzeug-Anzahl, Gleichheit beider Ko-Okkurrenz-Wege, Kosten je Weg.
# Zwei Namens-Entscheidungen sind Absicht, nicht Geschmack: der
# Erzeugungszeitstempel heisst hier 'probe_generated_at_ms' und nicht
# 'generated_at_ms', weil ledger.json denselben Namen mit einem anderen
# Wert traegt und der Merge sonst mit ConflictingClaim abbraeche -- zwei
# Laeufe, die zu verschiedenen Zeiten stattfanden, widersprechen sich
# nicht, sie sind nur zwei Laeufe. Und die generischen Namen
# ('all_maps_identical', 'session_boot_seconds', 'verdict', ...) tragen
# ein 'mcp_'- bzw. 'mcp_probe_'-Praefix, damit ein spaeteres Artefakt
# denselben Begriff ueber eine ANDERE Sache verwenden kann, ohne dass hier
# etwas kollidiert.
# full-vs-delta.json (aufgenommen 2026-08-07): beantwortet die Frage, die
# die Spezifikation selbst als entscheidend bezeichnet -- "ein Vollabgleich
# darf zwei Stunden dauern, solange der taegliche Nachlauf Minuten braucht".
# Aufgenommen erst NACH dem Neustart der haengenden GMS-Instanz und einer
# sauberen Neumessung; die Zahlen des kontaminierten Laufs stehen nirgends.
# Wichtig fuer jeden, der hier eine Zahl zitiert: 'change_fraction' (0.02)
# gehoert zwingend neben jedes Verhaeltnis. Das Delta ist NICHT "was sich
# wirklich geaendert hat", sondern die juengsten 2% der Plan-Liste als
# ausdruecklicher Stellvertreter -- die synthetischen Fixtures tragen kein
# echtes Schreib-Zeitstempel-Feld. Ein Verhaeltnis ohne diese Definition
# ist keine Messung, sondern eine Zahl mit unbekanntem Nenner. Die
# Definition selbst liegt als 'delta_definition' im Artefakt und ist als
# Freitext bewusst NICHT in claims.json -- sie ist der Kontext einer
# Behauptung, nicht die Behauptung.

# Schluessel, die NIE gemerged werden, obwohl sie skalar sind: sie sind
# Metadaten UEBER das einzelne Artefakt (eine Disclosure-Pflicht aus
# global-constraints.md -- "seeded" muss in JEDEM Artefakt einzeln
# stehen -- oder ein Zeitstempel/Label des jeweiligen Laufs), keine
# Tatsachenbehauptung, die ueber mehrere Laeufe hinweg identisch sein
# muesste. Empirisch belegt (Task 25, 2026-08-07): mit allen oben
# gelisteten Artefakten zusammen kollidieren genau vier Namen --
#   - "seeded": true in den meisten Laeufen, false in loadtest_smoke.json
#     (ein bewusst reiner Read-only-Check gegen die bestehende Instanz,
#     keine geseedeten Fixtures -- der Unterschied ist korrekt, kein Fehler)
#   - "scale": "s"/"m" je nach Lasttest-Groesse
#   - "seeded_statement": vier verschiedene Freitexte, die je erklaeren,
#     WAS in diesem einen Lauf geseedet wurde
#   - "generated_at": der Erzeugungszeitstempel des jeweiligen Laufs
# Keine dieser vier taucht je als Prosa-Zahl auf -- die eigentlichen
# Messwerte stehen unter eigenen, praefigierten Schluesseln (z. B.
# "loadtest_s_seed_broke", "loadtest_m_detail_edges"). Sie hier
# auszuschliessen ist darum kein Praezisionsverlust, sondern verhindert,
# dass zwei wahre, aber ueber verschiedene Dinge redende Aussagen als
# ConflictingClaim erscheinen.
NON_CLAIMABLE_METADATA_KEYS = frozenset(
    {"seeded", "scale", "seeded_statement", "generated_at"}
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
    seedlab-verdicts.json, das 'focuses'-Array in
    judge-seedlab-matrix.json) ist Beleg fuer eine Behauptung, keine
    Behauptung selbst -- es wird uebersprungen statt unter einem
    erfundenen gepunkteten Schluessel (z. B. 'pairs.confirmed.state') zu
    erscheinen, den ohnehin keine claims.json referenziert. Sollte eine
    verschachtelte Zahl je in der Prosa auftauchen, ist der richtige Ort
    dafuer ein eigener skalarer Schluessel im erzeugenden Lauf-Skript --
    nicht ein Auto-Flatten hier. Das gilt insbesondere fuer 'wie viele der
    vier Fokusse hat das Modell mit Zitat beurteilt' aus
    judge-seedlab-matrix.json: die Einzelwerte liegen nur je Fokus unter
    'judged_with_model' im 'focuses'-Array, kein Top-Level-Schluessel
    fasst sie zusammen -- diese Datei gehoert einer anderen Aufgabe, ein
    Aggregat dort ergaenzen waere ein fremdes Artefakt aendern, keine
    Beleg-Aufgabe (Task 25 Kontext). Ausserdem werden Schluessel aus
    NON_CLAIMABLE_METADATA_KEYS uebersprungen -- sie sind Metadaten UEBER
    das Artefakt, keine Tatsachenbehauptung (siehe Kommentar dort).

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
            if k in NON_CLAIMABLE_METADATA_KEYS:
                continue
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
