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
    run_file = RUNS / "campaign.json"
    if not run_file.exists():
        print("  Kein Lauf-Artefakt - es gibt nichts zu behaupten.")
        return 1
    run = json.loads(run_file.read_text(encoding="utf-8"))
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
