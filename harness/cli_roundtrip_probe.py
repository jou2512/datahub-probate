"""Der committete Beweis fuer Task 14: die CLI-Verdrahtung selbst, nicht
nur die Logik darunter.

WARUM diese Datei existiert: `harness/correct_roundtrip_probe.py` (Task
12/13) belegt bereits, dass `probate/correct.py::apply_proposal` +
`Writeback.revert_all()` byte-genau revertierbar sind -- aber es ruft
`apply_proposal` DIREKT auf, nie den Parser oder die Handler aus
`probate/cli.py`. Task 14 verdrahtet genau diese beiden neu (`propose`,
`correct`) -- dieser Beweis muss also den PARSER treffen, nicht nur die
Bibliotheksfunktion. Jeder Schritt hier ruft `probate.cli.main()` mit
genau den Argumenten, die ein Mensch am Terminal eintippen wuerde (siehe
`task-14-report.md` fuer die woertlichen Befehle) -- kein Test-Double,
kein Direktimport von `correct.py`.

Nimmt das 'missing'-Paar aus `examples/seedlab-manifest.json`
(missing_upstream -> missing_downstream): keine deklarierte Kante, aber
eine Ko-Okkurrenz-Query existiert laut Manifest bereits. `ledger` klassifi-
ziert das Paar deshalb als 'missing', `propose` baut daraus einen
add_edge-Vorschlag, und `correct --confirm` traegt die Kante wirklich ein.

Journal: bewusst NICHT der geteilte Vorgabe-Pfad `harness/runs/
journal.jsonl` (den `apply`/`confirm` weiter hardkodiert benutzen), sondern
ein ISOLIERTER Pfad ueber das neue `--journal` (Task 14). Befund beim Bau
dieser Sonde: der geteilte Journal trug zu diesem Zeitpunkt bereits >80
kaputte Alt-Eintraege (Wert `"urn:focus"`, keine gueltige URN -- vermutlich
ein Test ausserhalb dieser Aufgabe, der versehentlich den Standardpfad
statt `tmp_path` traf), an denen `probate revert --journal
harness/runs/journal.jsonl` (ohne die Option, mit dem alten Vorgabewert)
live mit HTTP 400 abbrach, BEVOR es zurueckmeldete -- reproduzierbar,
siehe task-14-report.md. Das ist ein Befund ausserhalb des Datei-Umfangs
dieser Aufgabe (die verursachende Datei ist keine der hier erlaubten), kein
Bug in `probate/cli.py` selbst -- der isolierte Pfad umgeht ihn nur fuer
DIESE Sonde, er behebt ihn nicht. Der eigentliche Beweis ist ohnehin NICHT
"revert_count stimmt", sondern der byte-genaue Vergleich des Ziel-Aspekts
vor Schreibvorgang 1 gegen den Zustand nach dem Revert (`restored_exactly`).
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # fuer `probate.*` bei Direktlauf

import probate.cli as cli  # noqa: E402
from probate.gms import Gms  # noqa: E402

MANIFEST_PATH = Path("examples/seedlab-manifest.json")
RUNS_DIR = Path("harness/runs")


def _pair(manifest_path: Path, expected_state: str) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for edge in manifest["edges"]:
        if edge["expected_edge_state"] == expected_state:
            return edge
    raise ValueError(f"kein paar mit expected_edge_state={expected_state!r} im manifest")


def _cli(argv: list[str]) -> tuple[int, str]:
    """Ruft `probate.cli.main()` wie ein echter Terminal-Aufruf -- selbes
    Programm, selber Parser, dieselben Handler, die ein Mensch mit
    `uv run --python 3.11 probate <argv>` erreicht."""
    old_argv = sys.argv
    sys.argv = ["probate", *argv]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = cli.main()
    finally:
        sys.argv = old_argv
    return rc, buf.getvalue()


def _ledger_counts(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: data[k] for k in (
        "edges_total", "edges_confirmed", "edges_dead", "edges_missing", "edges_unknown")}


def _edge_state(path: Path, edge_key: str) -> str | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    for e in data["edges"]:
        if e["edge"] == edge_key:
            return e["state"]
    return None  # Kante taucht in diesem Lauf gar nicht auf -- ehrlich als None, nicht geraten


def run(manifest_path: Path = MANIFEST_PATH, out_path: Path | None = None) -> dict:
    if out_path is None:
        out_path = Path("harness/runs/cli-roundtrip.json")

    pair = _pair(manifest_path, "missing")
    focus = pair["upstream_urn"]
    target = pair["downstream_urn"]
    edge_key = f"{focus}->{target}"

    gms = Gms()
    true_original = gms.get_aspect("dataset", target, "upstreamLineage")

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ledger_before_path = RUNS_DIR / "_cli_roundtrip_ledger_before.json"
    ledger_after_path = RUNS_DIR / "_cli_roundtrip_ledger_after_write.json"
    ledger_reverted_path = RUNS_DIR / "_cli_roundtrip_ledger_after_revert.json"
    proposals_path = RUNS_DIR / "_cli_roundtrip_proposals.json"
    journal_path = RUNS_DIR / "_cli_roundtrip_journal.jsonl"
    for p in (ledger_before_path, ledger_after_path, ledger_reverted_path, proposals_path, journal_path):
        p.unlink(missing_ok=True)  # Rest eines abgebrochenen frueheren Laufs, nie stillschweigend mitlesen

    commands: list[dict] = []

    def _step(argv: list[str], label: str) -> str:
        rc, out = _cli(argv)
        commands.append({"argv": argv, "returncode": rc, "output": out.strip()})
        assert rc == 0, f"{label} schlug fehl (returncode {rc}):\n{out}"
        return out

    _step(["ledger", "--focus", focus, "--out", str(ledger_before_path)], "ledger (vorher)")
    state_before = _edge_state(ledger_before_path, edge_key)

    _step(["propose", "--ledger", str(ledger_before_path), "--out", str(proposals_path)], "propose")

    _step(["correct", "--edge", edge_key, "--kind", "add_edge",
           "--proposals", str(proposals_path), "--confirm", "--journal", str(journal_path)],
          "correct --confirm")
    after_write_aspect = gms.get_aspect("dataset", target, "upstreamLineage")

    _step(["ledger", "--focus", focus, "--out", str(ledger_after_path)], "ledger (nachher)")
    state_after_write = _edge_state(ledger_after_path, edge_key)

    revert_out = _step(["revert", "--journal", str(journal_path)], "revert")
    after_revert_aspect = gms.get_aspect("dataset", target, "upstreamLineage")

    _step(["ledger", "--focus", focus, "--out", str(ledger_reverted_path)], "ledger (nach revert)")
    state_after_revert = _edge_state(ledger_reverted_path, edge_key)

    restored_exactly = after_revert_aspect == true_original
    written_upstreams = {
        u.get("dataset") for u in (after_write_aspect or {}).get("value", {}).get("upstreams", [])
    }

    artifact = {
        "seeded": True,
        "seeded_statement": (
            "Laeuft gegen den geseedeten Beispielkatalog (namespace probate_seedlab, "
            "harness/seed_lineage_lab.py) -- jeder Schritt ruft probate.cli.main() "
            "wie ein echter Terminal-Aufruf ('uv run --python 3.11 probate <befehl>'), "
            "kein Test-Double und kein Direktimport von correct.py."
        ),
        "gms_url": gms.base,
        "manifest": str(manifest_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "focus": focus,
        "target": target,
        "edge": edge_key,
        "journal_note": (
            "Laeuft ueber 'correct --journal' / 'revert --journal' mit einem ISOLIERTEN "
            "Journal-Pfad, nicht dem geteilten Vorgabe-Pfad harness/runs/journal.jsonl -- "
            "der war zum Zeitpunkt dieses Laufs mit >80 kaputten Alt-Eintraegen "
            "('urn:focus', keine gueltige URN) verunreinigt und liess 'probate revert' ohne "
            "--journal live mit HTTP 400 abbrechen. Befund ausserhalb des Datei-Umfangs von "
            "Task 14, siehe task-14-report.md. Die 'correct'/'revert'-Handler selbst sind "
            "dieselben, die auch ohne --journal laufen (Vorgabewert unveraendert)."
        ),
        "commands": commands,
        "roundtrip_states_before": {"edge_state": state_before, **_ledger_counts(ledger_before_path)},
        "roundtrip_states_after_write": {"edge_state": state_after_write, **_ledger_counts(ledger_after_path)},
        "roundtrip_states_after_revert": {"edge_state": state_after_revert, **_ledger_counts(ledger_reverted_path)},
        "roundtrip_reverted_writes": int(revert_out.strip().split()[0]),
        "add_edge_visible_in_raw_aspect_after_write": focus in written_upstreams,
        "true_original_aspect": true_original,
        "after_write_aspect": after_write_aspect,
        "after_revert_aspect": after_revert_aspect,
        "restored_exactly": restored_exactly,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")

    for p in (ledger_before_path, ledger_after_path, ledger_reverted_path, proposals_path, journal_path):
        p.unlink(missing_ok=True)  # nur harness/runs/cli-roundtrip.json bleibt als Beleg

    return artifact


if __name__ == "__main__":
    result = run()
    summary = {k: v for k, v in result.items()
               if k not in ("true_original_aspect", "after_write_aspect", "after_revert_aspect")}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if not result["restored_exactly"]:
        sys.exit(1)  # verification.md: eine gescheiterte Pruefung ist kein stilles Weiterlaufen
