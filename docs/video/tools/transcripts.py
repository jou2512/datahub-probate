"""Echte Befehle ausfuehren und ihre Ausgabe als Mitschrift ablegen.

Warum nicht einfach ein Terminalfenster filmen: `gdigrab -i title=…` liefert
bei einem Konsolenfenster unter Windows 11 ein SCHWARZES Bild -- gemessen
10.08.2026 an drei Aufnahmen. Der Konsolenhost zeichnet ueber DirectX, GDI
sieht davon nichts. Dasselbe galt fuer Chrome, dort half
`--disable-direct-composition`; fuer den Konsolenhost gibt es keinen
entsprechenden Schalter, den ein Skript setzen darf.

Der bequeme Ausweg waere die Desktop-Aufnahme gewesen. Der ist ausgeschlossen:
auf diesem Rechner liegen Recherche ueber andere Teams, Slack und Mail offen.

Also: die Befehle laufen WIRKLICH, ihre Ausgabe wird woertlich in eine
Textdatei geschrieben, und die Textdatei wird im Browserfenster gezeigt --
genauso wie die Lauf-Artefakte in den Abschnitten 1:17 und 2:23 schon gezeigt
werden. Was im Bild steht, ist damit kein nachgebautes Terminal, sondern die
Ausgabe selbst, mit Befehl, Rueckgabewert, Dauer und Zeitstempel darueber.
Ein Juror kann jede dieser Zeilen selbst erzeugen.

Aufruf:
    uv run --python 3.11 python docs/video/tools/transcripts.py --which 06,07,07b
    uv run --python 3.11 python docs/video/tools/transcripts.py --which 04c
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/video/transcripts"

FOCUS = ("urn:li:dataset:(urn:li:dataPlatform:postgres,"
         "probate_seedlab.gl_journal_entries_daily,PROD)")
SHORT = "'…probate_seedlab.gl_journal_entries_daily…'"


def run_block(shown: str, argv: list[str], *, keep: list[str] | None = None,
              limit: int = 22, from_end: bool = False) -> str:
    """Einen Befehl ausfuehren und als Block formatieren."""
    t0 = time.perf_counter()
    p = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    took = time.perf_counter() - t0
    lines = [l.rstrip() for l in ((p.stdout or "") + (p.stderr or "")).splitlines()
             if l.strip()]
    if keep:
        picked = [l for l in lines if any(k in l for k in keep)]
        lines = picked or lines[-limit:]
    lines = lines[-limit:] if from_end else lines[:limit]
    head = f"$ {shown}"
    tail = (f"  → exit {p.returncode} · {took:.2f} s · "
            f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    return "\n".join([head, ""] + lines + ["", tail])


def t_04c() -> str:
    """Die Kante, der gerade die Nutzungsdaten weggenommen wurden."""
    return run_block(
        f"probate ledger --focus {SHORT}",
        ["uv", "run", "--python", "3.11", "probate", "ledger", "--focus", FOCUS],
        keep=["\"focus\"", "edges_total", "edges_confirmed", "edges_dead",
              "edges_missing", "edges_unknown", "\"state\"", "buckets_seen",
              "\"reason\""],
        limit=16)


def t_06() -> str:
    """Das Modellurteil: einmal mit Zitat, einmal Enthaltung.

    Aus `harness/runs/judge-seedlab-matrix.json` -- dem festgehaltenen Lauf.
    Live waeren es 17.8-23.1 s pro Kante (README) und echte Modellkosten bei
    jedem Probelauf; das Artefakt liegt im Repo und faellt unter
    `audit_claims.py`, ist also nachrechenbar statt nur vorgefuehrt.
    """
    return run_block(
        "type harness\\runs\\judge-seedlab-matrix.json     "
        "# der festgehaltene Lauf",
        ["powershell", "-NoProfile", "-Command",
         "Get-Content harness/runs/judge-seedlab-matrix.json | Select-String "
         "-Pattern 'quote|source_field|used_model|fallback_reason'"],
        limit=18)


def t_07() -> str:
    """Das Beleg-Gate. Der Schnitt bleibt auf der LETZTEN Zeile stehen
    ("Alle 140 Zahlen decken sich mit den Laeufen.") -- deshalb vom Ende her
    abgeschnitten, nicht vom Anfang."""
    return run_block(
        "uv run --python 3.11 python harness/audit_claims.py",
        ["uv", "run", "--python", "3.11", "python", "harness/audit_claims.py"],
        limit=15, from_end=True)


def t_07b() -> str:
    """Beide Transportwege. GraphQL live, MCP aus dem Messlauf.

    MCP live geht in einem 15-Sekunden-Bild nicht: 9.4 s allein fuer den
    Sitzungsstart (`mcp_session_boot_seconds_warm`), dazu Telemetrie je
    Werkzeugaufruf. Nie sagen: "MCP ist 130x langsamer" (das ist der
    Sitzungsstart, nicht der Durchsatz) und nie: das Altersurteil gehe ueber
    MCP (es geht nicht, und das Artefakt sagt warum).
    """
    a = run_block(
        f"probate ledger --focus {SHORT} --cooccurrence-source graphql",
        ["uv", "run", "--python", "3.11", "probate", "ledger", "--focus", FOCUS,
         "--cooccurrence-source", "graphql"],
        keep=["cooccurrence_source", "edges_total", "edges_confirmed"], limit=4)
    b = run_block(
        "type harness\\runs\\mcp-probe.json      # beide Wege, gemessen",
        ["powershell", "-NoProfile", "-Command",
         "Get-Content harness/runs/mcp-probe.json | Select-String -Pattern "
         "'mcp_maps_identical_all_four_states|mcp_totals_identical_all_four_states|"
         "end_to_end_verdicts_identical|mcp_session_boot_seconds_warm|"
         "\"timestamps\"|query_entities'"],
        limit=10)
    return a + "\n\n" + b


MAKERS = {"04c": t_04c, "06": t_06, "07": t_07, "07b": t_07b}
NAMES = {"04c": "04c-reveal", "06": "06-model", "07": "07-gate", "07b": "07b-mcp"}


def make(which: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{NAMES[which]}.txt"
    path.write_text(MAKERS[which]() + "\n", encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", default="06,07,07b")
    args = ap.parse_args()
    for w in [x.strip() for x in args.which.split(",") if x.strip()]:
        if w not in MAKERS:
            raise SystemExit(f"unbekannt: {w}")
        p = make(w)
        n = len(p.read_text(encoding="utf-8").splitlines())
        print(f"  {NAMES[w]:<12} {n:>3} Zeilen  →  {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
