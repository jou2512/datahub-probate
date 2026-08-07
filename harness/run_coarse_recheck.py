"""Nachtrag zu Task 23, Review-Runde 1: `run_stage()` deckelt die Stichprobe fuer
`detail_pass` unbedingt auf `detail_sample` (Default 41) -- `loadtest_s_detail_edges`
und `loadtest_m_detail_edges` standen deshalb beide bei 41, OHNE dass das Artefakt
zeigte, ob das ein organischer Fund oder ein Kappungs-Artefakt ist. Der Sonden-Lauf
`loadgen_smoke`/`loadtest_smoke` (derselbe Coarse-Pass auf Skala S, separat) zeigt
50 von 50 -- 100% verdaechtig, was stark auf Kappung statt Befund hindeutet.

Dieses Skript fuellt die Luecke NACHTRAEGLICH und minimal-invasiv: ein frischer
Seed->Coarse->Cleanup-Zyklus (bewusst OHNE Detail-Pass -- der ist fuer die
Vorab-Zahl irrelevant und unnoetig teuer), und schreibt die daraus gemessenen
Coarse-Felder (inkl. der jetzt ungedeckelten `coarse_suspicious`, siehe
harness/loadtest.py `coarse_pass`/`run_stage`) in das bestehende
harness/runs/loadtest_<scale>.json hinein -- Seed-/Detail-/Cleanup-Zahlen aus dem
urspruenglichen Lauf bleiben unangetastet, nur die Coarse-Gruppe wird durch diese
neue, in sich konsistente Messung ersetzt.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.loadtest import coarse_pass, measure  # noqa: E402
from harness.loadgen import cleanup, generate  # noqa: E402
from probate.gms import Gms  # noqa: E402


def run(gms, scale: str) -> dict:
    seed, m_seed = measure(generate, gms, scale)
    seed = seed or {}

    coarse, m_coarse = measure(coarse_pass, gms, scale)
    coarse = coarse or {}

    clean, m_clean = measure(cleanup, gms, scale)
    clean = clean or {}

    return {
        f"loadtest_{scale}_coarse_seconds": m_coarse["seconds"],
        f"loadtest_{scale}_coarse_peak_mb": m_coarse["peak_memory_mb"],
        f"loadtest_{scale}_coarse_api_calls": coarse.get("coarse_api_calls", 0),
        f"loadtest_{scale}_coarse_response_chars": coarse.get("coarse_response_chars", 0),
        f"loadtest_{scale}_coarse_suspicious": len(coarse.get("_suspicious", [])),
        f"loadtest_{scale}_coarse_broke": m_coarse["broke"],
        f"loadtest_{scale}_coarse_recheck_seed_broke": m_seed["broke"],
        f"loadtest_{scale}_coarse_recheck_cleanup_verified": clean.get("cleanup_verified", False),
        f"loadtest_{scale}_coarse_recheck_cleanup_leftover": clean.get("cleanup_leftover", 0),
        f"loadtest_{scale}_coarse_recheck_cleanup_errors": clean.get("cleanup_errors", []),
        f"loadtest_{scale}_coarse_recheck_note": (
            "Nachtrags-Lauf, Review-Runde 1: separater Seed->Coarse->Cleanup-Zyklus "
            "(kein Detail-Pass), einzig um den UNGEKAPPTEN coarse_suspicious-Wert zu "
            "messen. Ersetzt die coarse_*-Gruppe im Hauptartefakt; seed_/detail_/"
            "cleanup_-Felder aus dem urspruenglichen Vollauf bleiben unveraendert."
        ),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scale", required=True, choices=["s", "m"])
    p.add_argument("--gms", default="http://localhost:28080")
    args = p.parse_args(argv)
    if "18080" in args.gms or ":8080" in args.gms:
        print("VERWEIGERT: Lasttest laeuft nur gegen 28080.")
        return 2

    out_path = Path(f"harness/runs/loadtest_{args.scale}.json")
    existing = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    fresh = run(Gms(args.gms), args.scale)
    existing.update(fresh)
    out_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(fresh, indent=2, ensure_ascii=False))
    ok = fresh[f"loadtest_{args.scale}_coarse_recheck_cleanup_verified"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
