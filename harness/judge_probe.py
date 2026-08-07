"""Live-Probe fuer den `claude -p`-Transport (Task 10) -- ruft ihn GENAU
EINMAL gegen den echten Prozess auf, end-to-end durch `judge_edge`
(Prompt-Bau, Transport, Zitatpflicht), und schreibt das ehrliche Ergebnis
nach `harness/runs/judge-transport-probe.json`.

WARUM diese Datei existiert (Review-Nachtrag, Fix-Runde 1): das Artefakt
lag vorher ohne das erzeugende Skript im Repo -- fuer eine Pruefer:in
nicht reproduzierbar, anders als jede andere Probe in diesem Projekt
(`harness/seedlab_verdicts.py`, `harness/loadgen.py`,
`harness/seed_lineage_lab.py` haben alle ihr Skript committed). Dieses
Skript ist dieses fehlende Stueck.

Kontext ist bewusst SYNTHETISCH (unten hartkodiert), keine echte
GMS-Anfrage: die Frage, die diese Probe beantwortet, ist "antwortet die
CLI ueberhaupt brauchbar", nicht "was steht im Katalog" -- letzteres
prueft `harness/record_ledger.py`/die CLI selbst gegen den echten Seedlab
(`--judge` in `probate/cli.py`). `command_shape` im Artefakt bleibt ein
PLATZHALTER, kein woertlicher Prompt-Dump (Sicherheits-Review, Punkt 9:
Katalog-Metadaten sind kein Geheimnis, aber ein committetes Artefakt ist
trotzdem nicht der Ort dafuer, unbegrenzt Freitext zu sammeln).

Gemessener Fund, der zur `--system-prompt`-Haertung in
`probate/judge.py` gefuehrt hat (s. dortiger Modul-Kommentar): OHNE
`--system-prompt` laedt `claude -p` in diesem Repo-Ordner automatisch
`CLAUDE.md`/`AGENTS.md` und antwortet als Coding-Agent statt als reiner
JSON-Antworter -- diese Probe war das Werkzeug, mit dem der Fund gemacht
wurde, und bleibt das Werkzeug, mit dem er nachpruefbar bleibt.

Methodik-Falle, hier bereits behoben (nicht neu einschleppen): der
Transport darf fuer diese Probe nur EINMAL aufgerufen werden. Zwei
unabhaengige Modell-Samples desselben Prompts koennen sich in der
exakten Zitatlaenge unterscheiden -- ein zweiter Aufruf wuerde die
Aussage verfaelschen, nicht praezisieren.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from probate.judge import (
    JudgeTransportError,
    build_prompt,
    claude_cli_transport,
    judge_edge,
)
from probate.ledger import Bucket, Coverage, Edge, EdgeVerdict, Timeline

DEFAULT_OUT = Path("harness/runs/judge-transport-probe.json")

DAY = 86_400_000
_VERDICT = EdgeVerdict(
    edge=Edge("urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customers_v7,PROD)",
              "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.tmp_stage_42,PROD)"),
    state="dead",
    evidence={"reason": "im geprueften Fenster nie gemessen", "buckets_checked": 30},
    coverage=Coverage(30, 10 * DAY, 40 * DAY, ""),
    timeline=Timeline((Bucket(40 * DAY, 0, 0),)),
)
_UP_CTX = {
    "urn": _VERDICT.edge.upstream, "name": "customers_v7",
    "description": "Gepruefter Kundenstammdatensatz, revisionsrelevant fuer den Jahresabschluss",
    "owners": ["urn:li:corpuser:finance-owner"], "glossary_terms": ["urn:li:glossaryTerm:PII"],
    "domain": "Finance",
    "text": ("customers_v7\nGepruefter Kundenstammdatensatz, revisionsrelevant fuer den "
             "Jahresabschluss\nurn:li:corpuser:finance-owner\nurn:li:glossaryTerm:PII\nFinance"),
}
_DOWN_CTX = {
    "urn": _VERDICT.edge.downstream, "name": "tmp_stage_42", "description": "",
    "owners": [], "glossary_terms": [], "domain": "", "text": "tmp_stage_42",
}


def probe(timeout: int = 60) -> dict:
    """Genau EIN Transport-Aufruf, eingefangen ueber einen duennen
    Wrapper statt eines zweiten direkten Aufrufs (die urspruengliche
    Fassung dieses Skripts rief den Transport zweimal auf -- einmal fuer
    die rohe Antwortlaenge, einmal erneut in `judge_edge` -- und liess so
    zwei unabhaengige Modell-Samples in EIN Ergebnis einfliessen)."""
    out = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "binary": "claude",
        "command_shape": ["claude", "-p", "<prompt>", "--output-format", "json",
                           "--system-prompt", "<siehe judge.py:_JUDGE_SYSTEM_PROMPT>"],
        "timeout_s": timeout,
        "note": ("--system-prompt ist Pflicht: ohne ihn laedt die CLI in diesem "
                 "Repo-Ordner automatisch CLAUDE.md/AGENTS.md und antwortet als "
                 "Coding-Agent statt als reiner JSON-Antworter (gemessen, s. "
                 "judge.py Modul-Kommentar 'Task 10: der echte Transport')."),
    }

    captured: dict[str, str] = {}
    real_transport = claude_cli_transport(timeout=timeout)

    def transport_once(prompt: str) -> str:
        raw = real_transport(prompt)
        captured["raw"] = raw
        return raw

    t0 = time.perf_counter()
    try:
        j = judge_edge(_VERDICT, _UP_CTX, _DOWN_CTX, transport=transport_once)
        out["transport_call_ok"] = True
        out["transport_error"] = None
    except JudgeTransportError as exc:
        out["transport_call_ok"] = False
        out["transport_error"] = str(exc)
        j = None
    out["transport_duration_s"] = round(time.perf_counter() - t0, 2)
    out["raw_reply_len_chars"] = len(captured["raw"]) if "raw" in captured else None

    if j is not None:
        out["judged_with_model"] = j.used_model
        out["fallback_reason"] = j.fallback_reason
        out["important"] = j.important
        out["source_field"] = j.source_field
        # Zitat nur speichern, wenn used_model True ist -- sonst leer.
        # Kein echtes Geschaeftsgeheimnis: der Kontext oben ist synthetisch.
        out["quote_matched"] = j.quote if j.used_model else ""
    else:
        out["judged_with_model"] = False
        out["fallback_reason"] = f"Transport-Aufruf scheiterte vor jedem Urteil: {out['transport_error']}"
        out["important"] = None
        out["source_field"] = None
        out["quote_matched"] = ""

    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    result = probe(timeout=args.timeout)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
