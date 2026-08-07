"""Duenner Treiber fuer Task 23: faehrt EINE Stufe und schreibt ihr EIGENES
Artefakt (harness/runs/loadtest_<scale>.json) -- nicht eine gemeinsame Datei
fuer alle drei Stufen. Grund: ein Abbruch bei L darf die bereits gemessenen
Zahlen aus S und M nicht mitreissen; getrennte Dateien koennen nicht
kollidieren, auch wenn L abstuerzt, waehrend S/M schon committet sind
(passt zur Parallel-Lane-Vorgabe fuer Task 23: nur loadtest_s/m/l.json
anfassen, nicht die gemeinsame loadtest.json aus dem urspruenglichen Brief).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness.loadtest import run_stage
from probate.gms import Gms


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scale", required=True, choices=["s", "m", "l"])
    p.add_argument("--gms", default="http://localhost:28080")
    args = p.parse_args(argv)
    if "18080" in args.gms or ":8080" in args.gms:
        print("VERWEIGERT: Lasttest laeuft nur gegen 28080.")
        return 2

    out = Path(f"harness/runs/loadtest_{args.scale}.json")
    result = run_stage(Gms(args.gms), args.scale)
    result["seeded"] = True
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get(f"loadtest_{args.scale}_cleanup_verified") else 1


if __name__ == "__main__":
    sys.exit(main())
