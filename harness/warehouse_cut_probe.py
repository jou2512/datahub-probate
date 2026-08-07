"""Live-Beleg der dritten, demo-tragenden Transition: "Warehouse trennen".

Misst die Sekunden zwischen dem Purge der Nutzungs-Zeitreihe auf dem
seedlab-Zieldataset `confirmed_downstream` (`DEMO_PARTNER` in `ui/serve.py`,
derselbe Weg wie der "cut-warehouse"-Knopf: volle Zeitreihen-Loeschung ueber
`POST /entities?action=delete`, NICHT eine Aggregat-Schnappschuss-Loeschung
via `gms.delete_aspect()` -- die entfernt bei Zeitreihen-Aspekten nur die
"aktuellste" Zeile, siehe `harness/seed_lineage_lab.py`s eigener Kommentar
dazu) und dem Moment, in dem `probate/ledger.py::classify_edges` die Kante
`confirmed_upstream -> confirmed_downstream` danach korrekt als `unknown`
klassifiziert (NICHT `dead` -- kein Verkehr gesehen ist etwas anderes als
kein Fenster ueberhaupt, das ist die Kernregel des Moduls).

WARUM dieses Skript existiert: der eigentliche Ledger-Fix (`probate/
ledger.py::fetch_usage`, jetzt Rohablage statt `usageStats`-Aggregation)
loest den gemessenen >100s/>75s-Verzug der Aggregation. Dieses Skript ist
der Beleg DAFUER -- nicht Prosa, sondern ein committetes Artefakt mit einer
echten Sekundenzahl, genau wie `harness/seedlab_verdicts.py` der committete
Beleg fuer die Vier-Zustaende-Probe ist.

Ablauf:
  1. Ausgangszustand pruefen (muss `confirmed` sein -- sonst ist die Probe
     nicht aussagekraeftig, Abbruch statt Weiterlaufen mit falscher Basis).
  2. Purge (derselbe `/entities?action=delete`-Aufruf wie `ui/serve.py`
     `cut-warehouse`), Zeitstempel unmittelbar danach.
  3. Sofortige Neu-Klassifikation, mit `perf_counter` gemessen -- keine
     kuenstliche Wartezeit vor dem ersten Versuch, das waere die Frage
     verschenkt, die dieses Skript beantworten soll.
  4. Restore: kompletter Reseed ueber `harness/seed_lineage_lab.py` als
     Subprozess (idempotent: purged+schreibt alle acht Datasets neu) --
     dieses Skript aendert `seed_lineage_lab.py` NICHT, ruft es nur auf.
  5. Vier-Zustaende-Probe (`harness/seedlab_verdicts.py`) danach erneut,
     als Beleg dass der Restore vollstaendig war.

Schreibt `harness/runs/warehouse-cut-latency.json`.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # fuer `probate.*` bei Direktlauf

from probate.gms import Gms, _validate_urn  # noqa: E402
from probate.ledger import (  # noqa: E402
    classify_edges,
    fetch_cooccurrence,
    fetch_declared_edges,
    usage_evidence,
)

GMS_URL = "http://localhost:28080"
UPSTREAM = "urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.confirmed_upstream,PROD)"
# == DEMO_PARTNER in ui/serve.py -- dasselbe Ziel, das der "cut-warehouse"-
# Knopf trifft, aus demselben live gemessenen Grund (Kommentar dort): die
# Abdeckung der Kante haengt an `usage_evidence(downstream)`, nicht am
# Upstream, dessen eigene Nutzung nie in DIESE Kante einfliesst.
DOWNSTREAM = "urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.confirmed_downstream,PROD)"
FAR_FUTURE_MS = 4_102_444_800_000  # 2100-01-01 UTC, deckt jeden plausiblen Bucket ab
OUT_PATH = REPO_ROOT / "harness" / "runs" / "warehouse-cut-latency.json"
POLL_BUDGET = 30
POLL_INTERVAL_S = 0.5


def classify_pair(gms, now_ms: int):
    """Derselbe Drei-Schritt wie `harness/seedlab_verdicts.py::run()` fuer
    genau EIN Paar -- keine eigene Klassifikationslogik, nur die
    Beschaffungsfunktionen aus `probate/ledger.py` aufgerufen."""
    declared = fetch_declared_edges(gms, UPSTREAM, count=200)
    cooccurred, queries_seen = fetch_cooccurrence(gms, UPSTREAM)
    targets = declared | set(cooccurred)
    coverage_by_urn: dict = {}
    timeline_by_urn: dict = {}
    for t in targets:
        cov, tl = usage_evidence(gms, t)
        coverage_by_urn[t] = cov
        timeline_by_urn[t] = tl
    verdicts = classify_edges(
        UPSTREAM, declared, cooccurred, coverage_by_urn, timeline_by_urn,
        now_ms, queries_seen=queries_seen,
    )
    return next((v for v in verdicts if v.edge.downstream == DOWNSTREAM), None)


def purge_downstream_usage(gms: Gms) -> int:
    """Exakt derselbe Weg wie `ui/serve.py`s `cut-warehouse`-Aktion: volle
    Zeitreihen-Loeschung ueber `/entities?action=delete`, nicht ein
    einzelnes Aggregat-Snapshot-DELETE (das entfernt bei Zeitreihen-
    Aspekten nachweislich nur die letzte Zeile, siehe `seed_lineage_lab.py`
    Kommentar bei `purge_usage_history()`)."""
    _validate_urn(DOWNSTREAM)  # dieselbe Disziplin wie seed_lineage_lab.py/ui/serve.py
    payload = {
        "urn": DOWNSTREAM,
        "aspectName": "datasetUsageStatistics",
        "startTimeMillis": 0,
        "endTimeMillis": FAR_FUTURE_MS,
    }
    status, body = gms._send("POST", f"{gms.base}/entities?action=delete", payload)
    if status != 200:
        raise RuntimeError(f"purge fehlgeschlagen: HTTP {status}: {str(body)[:200]}")
    return int(((body or {}).get("value") or {}).get("timeseriesRows", 0))


def restore_seed(gms_url: str) -> tuple[bool, int]:
    """Vollstaendiger Reseed via Subprozess -- ruft `seed_lineage_lab.py`
    auf, aendert es aber nicht. Idempotent: purged+schreibt alle acht
    Datasets neu, egal wie diese Probe den Zustand hinterlassen hat."""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "harness" / "seed_lineage_lab.py"), "--gms-url", gms_url],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300,
    )
    return proc.returncode == 0, proc.returncode


def verify_four_states(gms_url: str) -> tuple[bool, int]:
    """Vier-Zustaende-Probe nach dem Restore -- Beleg, dass der Reseed
    vollstaendig war und der Katalog wieder auf dem verifizierten Stand ist."""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "harness" / "seedlab_verdicts.py"), "--gms-url", gms_url],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=300,
    )
    return proc.returncode == 0, proc.returncode


def main() -> int:
    gms = Gms(base_url=GMS_URL)

    now_ms = int(time.time() * 1000)
    before = classify_pair(gms, now_ms)
    if before is None or before.state != "confirmed":
        print(
            "ABBRUCH: Ausgangszustand ist nicht 'confirmed' "
            f"(ist: {before.state if before else 'kante nicht gefunden'}). "
            "Die Probe braucht einen bekannten Startzustand -- erst "
            "`harness/seed_lineage_lab.py` laufen lassen."
        )
        return 1

    removed_rows = purge_downstream_usage(gms)
    purge_wall_ms = int(time.time() * 1000)
    t_purge = time.perf_counter()

    attempts = []
    after = None
    elapsed_s = None
    for i in range(POLL_BUDGET):
        poll_now_ms = int(time.time() * 1000)
        v = classify_pair(gms, poll_now_ms)
        elapsed = round(time.perf_counter() - t_purge, 3)
        state = v.state if v is not None else "absent"
        attempts.append({"attempt": i + 1, "elapsed_s": elapsed, "state": state})
        if v is not None and v.state == "unknown":
            after = v
            elapsed_s = elapsed
            break
        time.sleep(POLL_INTERVAL_S)

    reseed_ok, reseed_code = restore_seed(GMS_URL)
    verdicts_ok, verdicts_code = verify_four_states(GMS_URL)

    artifact = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gms_url": GMS_URL,
        "edge": f"{UPSTREAM}->{DOWNSTREAM}",
        "purge_route": "POST /entities?action=delete (volle Zeitreihen-Loeschung, wie ui/serve.py cut-warehouse)",
        "usage_read_route": "POST /aspects?action=getTimeseriesAspectValues (Rohablage, seit dem Ledger-Fix in probate/ledger.py::fetch_usage)",
        "before_state": before.state,
        "purged_timeseries_rows": removed_rows,
        "purge_wall_clock_ms": purge_wall_ms,
        "attempts": attempts,
        "after_state": after.state if after is not None else None,
        "correct_classification_reached": after is not None,
        "elapsed_seconds_purge_to_correct_classification": elapsed_s,
        "restore": {
            "reseed_ran": True,
            "reseed_exit_code": reseed_code,
            "reseed_ok": reseed_ok,
            "seedlab_verdicts_exit_code": verdicts_code,
            "four_states_green_after_restore": verdicts_ok,
        },
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(artifact, indent=2, ensure_ascii=False))

    if after is None:
        print("\n  FEHLER: Kante hat sich nie zu 'unknown' geflippt innerhalb des Poll-Budgets.")
        return 1
    if not reseed_ok:
        print(f"\n  FEHLER: Restore (Reseed) fehlgeschlagen, exit {reseed_code}.")
        return 1
    if not verdicts_ok:
        print(f"\n  FEHLER: Vier-Zustaende-Probe nach Restore nicht gruen, exit {verdicts_code}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
