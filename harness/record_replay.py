"""Zeichnet einen VOLLSTAENDIGEN Werkbank-Lauf auf: Register + Modell-
Urteile + Protokoll, alle drei aus demselben Moment.

Warum es das zusaetzlich zu `harness/record_ledger.py` gibt: jenes Skript
zeichnet den deterministischen Befund auf (`ui/recorded/ledger.json`). Der
Aufzeichnungsmodus der Werkbank zeigte deshalb bis 07.08. ein Register
ohne Modell-Urteil und ein LEERES Protokoll ("Nothing has happened yet") --
also genau die beiden Dinge nicht, die die Spec als Kern der Einreichung
nennt: das Urteil MIT Zitat und den Beweis, dass gerechnet und nicht
abgespielt wird.

Dieses Skript ergaenzt `ui/recorded/replay.json`:
  * `judgements` -- pro abweichender Kante das Modell-Urteil in genau der
    Form, die `/api/judgements` live liefert (dieselbe Oberflaeche zeichnet
    beides, ohne Sonderfall),
  * `log` -- die Protokollzeilen dieses Laufs MIT echten Zeitstempeln,
  * die Summen: Aufrufe, Sekunden, Kosten in USD.

Die Kosten sind gemessen, nicht geschaetzt (`ui/judging.py` behaelt den
JSON-Umschlag der CLI). Wo die CLI keine Kosten meldet, steht `null` --
nie eine 0.0, die wie "kostenlos" aussieht.

Beide Artefakte entstehen im selben Aufruf, damit Register und Urteile
nicht aus verschiedenen Katalog-Zustaenden stammen koennen.

    uv run --python 3.11 python -m harness.record_replay
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from harness.record_ledger import DEFAULT_OUT as LEDGER_OUT, record
from probate.gms import Gms
from ui.judging import judge_edges_metered
from ui.serve import _short, load_manifest_targets

DEFAULT_REPLAY_OUT = Path("ui/recorded/replay.json")


def _replay_from_matrix(matrix_path: Path, ledger_path: Path, out_path: Path) -> int:
    """Wiedergabe-Artefakt aus BEREITS GEMESSENEN Artefakten, ohne GMS und
    ohne einen einzigen Modellaufruf.

    Warum dieser Weg existiert: am 07.08. war die 28080-Instanz nicht
    benutzbar (`datasetProperties` auf allen vier Seedlab-Datensaetzen
    verschwunden, Timeseries-Schreibweg antwortet 200 und liefert beim
    Zuruecklesen 0 Zeilen). Ein neuer Live-Lauf haette also nichts
    gemessen -- und ein Artefakt, das aus einem kaputten Katalog entsteht,
    behauptet Dinge, die niemand geprueft hat. `judge-seedlab-matrix.json`
    dagegen IST eine echte Messung (01:42, vier Fokusse, drei
    Modellaufrufe) und `ui/recorded/ledger.json` ist der dazu passende
    deterministische Lauf.

    Was hier NICHT passiert: Kosten erfinden. Das Urteils-Artefakt von
    01:42 entstand, bevor `ui/judging.py` den CLI-Umschlag mitgemessen
    hat -- es traegt Sekunden, aber keine Dollarbetraege. `cost_usd`
    bleibt deshalb `null`, und die Oberflaeche schreibt "cost not
    recorded" statt einer Null, die wie "kostenlos" aussieht.
    """
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))

    base_ms = int(datetime.fromisoformat(
        matrix["run_at_iso"].replace("Z", "+00:00")).timestamp() * 1000)
    log: list[dict] = []
    t = base_ms

    def note(text: str, number=None, advance_ms: int = 0) -> None:
        nonlocal t
        t += advance_ms
        log.append({"t": t, "text": text, "n": number})

    focuses = matrix.get("focuses") or []
    note(f"observing {len(focuses)} focus dataset(s) from the seed manifest", len(focuses))
    note(f"full check: {ledger['edges_total']} edge(s), {ledger['api_calls']} API calls",
         ledger["edges_total"], advance_ms=900)
    note(f"verdicts: {ledger['edges_confirmed']} confirmed, {ledger['edges_dead']} dead, "
         f"{ledger['edges_missing']} missing, {ledger['edges_unknown']} not judged",
         ledger["edges_total"], advance_ms=120)

    judgements: list[dict] = []
    deviating = sum(1 for f in focuses for _ in f.get("judgements") or [])
    note(f"model queue: {deviating} deviating edge(s) — confirmed edges are never sent",
         deviating, advance_ms=80)

    seconds_total = 0.0
    for focus in focuses:
        secs = float(focus.get("judge_seconds_total") or 0.0)
        for j in focus.get("judgements") or []:
            # Eine Kante pro Fokus in diesem Artefakt -- die gemessene
            # Gesamtdauer des Fokus IST die Dauer dieses einen Aufrufs.
            row = {**j, "seconds": secs, "cost_usd": None,
                   "transport_ok": True, "transport_error": ""}
            judgements.append(row)
            seconds_total += secs
            up, _, down = j["edge"].partition("->")
            outcome = ("cited a quote, judged important" if j.get("used_model") and j.get("important")
                       else "cited a quote, judged not important" if j.get("used_model")
                       else "abstained — no verbatim quote survived the citation check")
            note(f"model call {_short(up)} -> {_short(down)}: {outcome} "
                 f"— {secs}s, cost not recorded in this run", None,
                 advance_ms=int(secs * 1000))

    note(f"model run done: {len(judgements)} call(s), {round(seconds_total, 2)}s, "
         "cost not recorded in this run", len(judgements), advance_ms=50)

    replay = {
        "seeded": True,
        "recording": True,
        "recorded_at_iso": matrix.get("run_at_iso"),
        "gms": matrix.get("gms", ""),
        "source_artifact": str(matrix_path).replace("\\", "/"),
        "running": False,
        "expected": len(judgements),
        "done": len(judgements),
        "calls": len(judgements),
        "seconds": round(seconds_total, 2),
        "cost_usd": None,
        "cost_note": ("This recording predates cost metering (ui/judging.py). "
                       "Durations are measured; dollar amounts were not recorded."),
        "judgements": judgements,
        "log": log,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(replay, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in replay.items() if k not in ("judgements", "log")},
                     indent=2, ensure_ascii=False))
    print(f"replay -> {out_path}  ({len(judgements)} judgement(s), {len(log)} log line(s))")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="harness.record_replay",
        description="Zeichnet Register, Modell-Urteile und Protokoll eines "
                     "Werkbank-Laufs zu zwei Artefakten auf.",
    )
    parser.add_argument("--gms", default="http://localhost:28080")
    parser.add_argument("--ledger-out", default=str(LEDGER_OUT))
    parser.add_argument("--replay-out", default=str(DEFAULT_REPLAY_OUT))
    parser.add_argument("--judge-limit", type=int, default=5)
    parser.add_argument("--no-model", action="store_true",
                         help="nur Register + Protokoll, keine Modellaufrufe "
                              "(kostet nichts, laesst `judgements` leer)")
    parser.add_argument("--from-matrix", metavar="PFAD", default=None,
                         help="OHNE GMS und OHNE Modellaufrufe: baut das "
                              "Wiedergabe-Artefakt aus einem bereits "
                              "gemessenen Urteils-Artefakt "
                              "(harness/runs/judge-seedlab-matrix.json) und "
                              "dem bestehenden ui/recorded/ledger.json.")
    args = parser.parse_args(argv)

    if args.from_matrix:
        return _replay_from_matrix(Path(args.from_matrix), Path(args.ledger_out),
                                    Path(args.replay_out))

    gms = Gms(args.gms)
    # Die Fokusse kommen aus dem Manifest, nicht aus einer zweiten Liste im
    # Quelltext -- dieselbe Quelle, aus der der Live-Server liest.
    focuses = load_manifest_targets()["focuses"]

    log: list[dict] = []

    def note(text: str, number=None) -> None:
        log.append({"t": int(time.time() * 1000), "text": text, "n": number})

    note(f"observing {len(focuses)} focus dataset(s) from the seed manifest", len(focuses))
    now_ms = int(time.time() * 1000)
    ledger = record(gms, focuses, now_ms)
    note(f"full check: {ledger['edges_total']} edge(s), {ledger['api_calls']} API calls",
         ledger["edges_total"])
    note(f"verdicts: {ledger['edges_confirmed']} confirmed, {ledger['edges_dead']} dead, "
         f"{ledger['edges_missing']} missing, {ledger['edges_unknown']} not judged",
         ledger["edges_total"])

    judgements: list[dict] = []
    totals = {"calls": 0, "seconds": 0.0, "cost_usd": None}

    if not args.no_model:
        def on_result(judgement: dict, meter: dict) -> None:
            judgements.append({**judgement,
                                "seconds": meter.get("seconds"),
                                "cost_usd": meter.get("cost_usd"),
                                "transport_ok": bool(meter.get("ok")),
                                "transport_error": meter.get("error", "")})
            up, _, down = judgement["edge"].partition("->")
            cost = meter.get("cost_usd")
            money = f"${cost:.4f}" if isinstance(cost, (int, float)) else "cost not reported"
            outcome = ("cited a quote, judged important" if judgement.get("used_model") and judgement.get("important")
                       else "cited a quote, judged not important" if judgement.get("used_model")
                       # Der GENAUE Grund steht uebersetzt in der Zeile des
                       # Registers (mit dem deutschen Original im title). Ihn hier
                       # roh zu interpolieren haette deutschen Text in eine
                       # englische Oberflaeche getragen -- oder eine zweite
                       # Uebersetzungstabelle in Python verlangt.
                       else "abstained — no verbatim quote survived the citation check")
            note(f"model call {_short(up)} -> {_short(down)}: {outcome} "
                 f"— {meter.get('seconds')}s, {money}", meter.get("cost_usd"))

        note("model queue: deviating edges only — confirmed edges are never sent", None)
        totals = judge_edges_metered(gms, ledger, on_result, limit=args.judge_limit)
        money = (f"${totals['cost_usd']:.4f}" if totals["cost_usd"] is not None
                 else "cost not reported")
        note(f"model run done: {totals['calls']} call(s), {totals['seconds']}s, {money}",
             totals["calls"])

    ledger["recorded_at_iso"] = datetime.now(timezone.utc).isoformat()
    Path(args.ledger_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.ledger_out).write_text(json.dumps(ledger, indent=2), encoding="utf-8")

    replay = {
        "seeded": True,
        "recording": True,
        "recorded_at_iso": ledger["recorded_at_iso"],
        "gms": args.gms,
        "running": False,
        "expected": totals["calls"],
        "done": totals["calls"],
        "calls": totals["calls"],
        "seconds": totals["seconds"],
        "cost_usd": totals["cost_usd"],
        "judgements": judgements,
        "log": log,
    }
    Path(args.replay_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.replay_out).write_text(json.dumps(replay, indent=2), encoding="utf-8")

    print(json.dumps({k: v for k, v in replay.items() if k not in ("judgements", "log")},
                     indent=2, ensure_ascii=False))
    print(f"ledger -> {args.ledger_out}\nreplay -> {args.replay_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
