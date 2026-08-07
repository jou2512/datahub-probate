"""Modell-Urteile fuer die Werkbank -- mit GEMESSENEN Kosten.

Warum diese Datei existiert, obwohl `probate/judge.py` das Urteilen schon
kann: `claude_cli_transport()` dort wirft den JSON-Umschlag der CLI weg und
reicht nur `result` durch (probate/judge.py:700-705). Der Umschlag traegt
aber genau die Zahlen, die die Spec fuer das Live-Protokoll verlangt --
"jeder Modellaufruf mit Kosten". Live gemessen (07.08., `claude -p ...
--output-format json` auf dieser Maschine, Feldliste aus der echten
Antwort):

    total_cost_usd   0.246659
    duration_ms      3890
    duration_api_ms  1807
    usage.input_tokens / output_tokens / cache_read_input_tokens ...

Der Transport hier ist deshalb derselbe Aufruf mit demselben System-Prompt
(aus `probate.judge` importiert, nicht ein zweites Mal getippt), nur dass er
den Umschlag BEHAELT. `probate/judge.py` bleibt unangetastet -- es traegt
40+ Tests und gehoert einer anderen Bahn.

Kein zweiter Urteilsweg: die eigentliche Bewertung laeuft weiterhin durch
`probate.judge.judge_ledger()`. Diese Datei ruft sie pro Kante EINZELN auf
(`{"edges": [row]}`, limit=1), damit jedem Urteil genau ein gemessener
Aufruf zugeordnet werden kann -- eine gemeinsame Liste haette Urteile und
Kosten nur ueber die Reihenfolge verknuepft, also ueber eine Annahme.
Der Preis dafuer ist der verlorene Kontext-Cache (2 GraphQL-Aufrufe pro
Kante statt geteilt); bei den drei abweichenden Kanten dieser Demo sind das
vier Aufrufe mehr, und sie werden mitgezaehlt statt versteckt.
"""

from __future__ import annotations

import json
import subprocess
import time

from probate.judge import (
    DEVIATING_STATES,
    JudgeTransportError,
    _JUDGE_SYSTEM_PROMPT,
    judge_ledger,
)

# 90s statt der 60s aus probate/judge.py: die Urteils-Prompts dieser Demo
# lagen live bei 17.8s / 19.9s / 23.1s (harness/runs/judge-seedlab-matrix.json,
# judge_seconds_total je Fokus). 60s waeren ~2.6x der langsamsten gemessenen
# Antwort -- genug, aber der Lauf hier haengt an EINEM Knopfdruck vor Publikum,
# und ein Abbruch kostet mehr als 30 Sekunden Geduld.
MODEL_TIMEOUT_S = 90


def metered_transport(sink: list, binary: str = "claude",
                      timeout: int = MODEL_TIMEOUT_S, runner=None):
    """Wie `probate.judge.claude_cli_transport`, aber der Umschlag wird
    gemessen statt weggeworfen. Jeder Aufruf haengt EIN dict an `sink`:

        {"seconds": float, "cost_usd": float | None,
         "input_tokens": int | None, "output_tokens": int | None,
         "ok": bool, "error": str}

    `cost_usd` ist `None`, wenn die CLI das Feld nicht liefert -- eine
    fehlende Messung wird NIE als 0.0 ausgegeben (eine gescheiterte
    Abfrage ist keine Abwesenheit, `.claude/rules/verification.md`).

    `runner` ist injizierbar (Vorgabe `subprocess.run`), damit Tests nie
    einen echten Prozess starten.
    """
    run_proc = runner or subprocess.run

    def send(prompt: str) -> str:
        cmd = [binary, "-p", prompt, "--output-format", "json",
               "--system-prompt", _JUDGE_SYSTEM_PROMPT]
        started = time.monotonic()
        record = {"seconds": 0.0, "cost_usd": None, "input_tokens": None,
                  "output_tokens": None, "ok": False, "error": ""}
        sink.append(record)
        try:
            proc = run_proc(cmd, capture_output=True, text=True,
                            timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            record["seconds"] = round(time.monotonic() - started, 2)
            record["error"] = f"Zeitueberschreitung nach {timeout}s"
            raise JudgeTransportError(f"{binary} -p: {record['error']}")
        except OSError as exc:
            record["seconds"] = round(time.monotonic() - started, 2)
            record["error"] = f"Prozess nicht startbar ({exc})"
            raise JudgeTransportError(f"{binary} -p: {record['error']}")

        record["seconds"] = round(time.monotonic() - started, 2)

        if proc.returncode != 0:
            record["error"] = f"exit {proc.returncode}: {(proc.stderr or '')[:300]}"
            raise JudgeTransportError(f"{binary} -p {record['error']}")

        try:
            parsed = json.loads(proc.stdout)
            result = parsed.get("result", "")
        except Exception as exc:
            record["error"] = f"Umschlag nicht lesbar ({exc})"
            raise JudgeTransportError(f"{binary} -p: {record['error']}")

        usage = parsed.get("usage") or {}
        cost = parsed.get("total_cost_usd")
        record["cost_usd"] = float(cost) if isinstance(cost, (int, float)) else None
        record["input_tokens"] = usage.get("input_tokens")
        record["output_tokens"] = usage.get("output_tokens")
        record["ok"] = True
        return result

    return send


def deviating_rows(ledger: dict, limit: int = 20) -> list[dict]:
    """Die Kanten, fuer die ein Modellaufruf ueberhaupt stattfindet --
    dieselbe Regel wie `judge_ledger` (`confirmed` braucht kein Urteil),
    hier nur vorgezogen, damit die Oberflaeche VOR dem ersten Aufruf sagen
    kann, wie viele Aufrufe kommen."""
    return [r for r in ledger.get("edges", []) if r.get("state") in DEVIATING_STATES][:limit]


def judge_edges_metered(gms, ledger: dict, on_result, limit: int = 20,
                        transport_factory=None) -> dict:
    """Urteilt ueber jede abweichende Kante EINZELN und meldet jedes
    Ergebnis sofort per `on_result(judgement, meter)` -- nicht erst am
    Ende. Das Live-Protokoll soll waehrend der Rechnung wachsen, nicht
    danach erscheinen.

    Rueckgabe: die Summen des Laufs (Aufrufe, Kosten, Sekunden). Kosten
    werden NUR summiert, wenn jeder Aufruf eine Zahl gemeldet hat --
    sonst bleibt `cost_usd` None und die Oberflaeche sagt "nicht
    gemessen" statt einer zu kleinen Zahl.
    """
    rows = deviating_rows(ledger, limit)
    calls, seconds, costs, complete = 0, 0.0, 0.0, True

    for row in rows:
        sink: list = []
        transport = (transport_factory or metered_transport)(sink)
        judgement = judge_ledger(gms, {"edges": [row]}, transport, limit=1)[0]
        meter = sink[-1] if sink else {"seconds": 0.0, "cost_usd": None,
                                       "ok": False, "error": "kein Aufruf erfolgt"}
        calls += 1
        seconds += meter.get("seconds") or 0.0
        if isinstance(meter.get("cost_usd"), (int, float)):
            costs += meter["cost_usd"]
        else:
            complete = False
        on_result(judgement, meter)

    return {
        "calls": calls,
        "seconds": round(seconds, 2),
        "cost_usd": round(costs, 6) if (complete and calls) else None,
    }
