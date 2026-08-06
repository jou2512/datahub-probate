"""Synthetische Entitaeten fuer den Lasttest -- und ihre restlose Loeschung.

Warum die echte Instanz und kein Fake: die drei Bruchkandidaten sind
Abholen der Abfragen, Antwortgroesse und Speicher. Zwei davon sind
Netz-Eigenschaften (get_lineage liefert nachweislich >100'000 Zeichen
ohne Pagination-Vorgabe, Falle 12). Ein Fake antwortet mit dem, was wir
hineingeschrieben haben -- er wuerde die Zahl bestaetigen, die wir
behaupten wollen. Entscheid:
docs/entscheidungen/2026-08-07-lasttest-datenpfad.md

Der Namensraum ist die Aufraeum-Garantie: alles, dessen Name mit
`probate_load.` beginnt, gehoert zum Test -- cleanup() muss nicht raten,
was zu loeschen ist. NUR 28080 (global-constraints.md).

Review-Runde 1 (Findings CRITICAL 1/2, IMPORTANT 3) hat drei Luecken der
ersten Fassung behoben, alle drei live gegen 28080 nachgeprueft:

1. cleanup() liest jetzt auch `upstreamLineage` zurueck -- der Aspekt,
   um den diese ganze Spur geht. Die erste Fassung pruefte nur
   datasetProperties/querySubjects; eine stillschweigend fehlgeschlagene
   Loeschung der Lineage-Kante waere nie aufgefallen.
2. `run_smoke()`/`main()` schreiben ein echtes Artefakt nach
   harness/runs/loadgen_smoke.json -- vorher gab es nur ein
   Wegwerf-Skript im Scratchpad, das niemand nachpruefen konnte
   (Verstoss gegen global-constraints.md: "jede Zahl kommt aus einem
   Lauf-Artefakt in harness/runs/").
3. delete_aspect-Fehler werden gesammelt und im Ergebnis gemeldet statt
   in einem `except Exception: pass` zu verschwinden. Live geprueft
   (2026-08-07, gegen 28080): ein DELETE auf einen nie geschriebenen
   Aspekt liefert HTTP 200 (kein Fehler -- das war also nie der Fall,
   den das Verschlucken eigentlich abfangen sollte). Ein echter Fehler
   (z.B. unbekannter Entity-Typ) liefert HTTP 400 und wirft GmsError --
   genau der Fall, der vorher lautlos verschwand.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # fuer `probate.*` bei Direktlauf

from probate.gms import Gms  # noqa: E402

NAMESPACE = "probate_load"
PLATFORM = "urn:li:dataPlatform:snowflake"
SCALES = {"s": (50, 1_000), "m": (500, 10_000), "l": (5_000, 100_000)}
SUBJECTS_PER_QUERY = 3
DATASET_ASPECTS = ("upstreamLineage", "datasetProperties", "datasetUsageStatistics")


def dataset_urn(scale: str, n: int) -> str:
    return f"urn:li:dataset:({PLATFORM},{NAMESPACE}.{scale}.t{n:05d},PROD)"


def query_urn(scale: str, n: int) -> str:
    return f"urn:li:query:{NAMESPACE}-{scale}-{n:06d}"


def plan(scale: str) -> dict:
    """Deterministisch: gleiche Stufe, gleicher Plan. Ohne das ist eine
    Wiederholungsmessung keine Wiederholung."""
    tables, queries = SCALES[scale]
    datasets = [dataset_urn(scale, i) for i in range(tables)]
    edges = [(datasets[i], datasets[(i + 1) % tables]) for i in range(tables)]
    qs = []
    for q in range(queries):
        subs = [datasets[(q * 7 + k * 13) % tables] for k in range(SUBJECTS_PER_QUERY)]
        # Kollisionen aufloesen, damit wirklich 3 verschiedene Tabellen
        # beruehrt werden -- sonst misst der Test etwas anderes.
        seen, uniq = set(), []
        i = 0
        while len(uniq) < SUBJECTS_PER_QUERY:
            cand = subs[i] if i < len(subs) else datasets[(q + i) % tables]
            if cand not in seen:
                seen.add(cand)
                uniq.append(cand)
            i += 1
        qs.append({"urn": query_urn(scale, q), "subjects": uniq})
    return {"scale": scale, "datasets": datasets, "edges": edges, "queries": qs}


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def generate(gms, scale: str, batch: int = 200) -> dict:
    """Legt Datasets, Kanten und Query-Entitaeten an.

    Die SEED-Dauer wird getrennt gemessen und getrennt ausgewiesen --
    sonst verwechselt jemand sie mit der Abgleich-Dauer.
    """
    p = plan(scale)
    t0 = time.perf_counter()
    calls = 0

    for group in _chunks(p["datasets"], batch):
        gms.upsert("dataset", [
            {"urn": u, "datasetProperties": {"value": {
                "name": u.split(",")[1], "description": "synthetic load-test fixture (seeded)"}}}
            for u in group])
        calls += 1

    for group in _chunks(p["edges"], batch):
        gms.upsert("dataset", [
            {"urn": down, "upstreamLineage": {"value": {"upstreams": [
                {"dataset": up, "type": "TRANSFORMED",
                 "auditStamp": {"time": 0, "actor": "urn:li:corpuser:__datahub_system"}}]}}}
            for up, down in group])
        calls += 1

    for group in _chunks(p["queries"], batch):
        gms.upsert("query", [
            {"urn": q["urn"],
             "querySubjects": {"value": {"subjects": [{"entity": s} for s in q["subjects"]]}}}
            for q in group])
        calls += 1

    return {"seeded": True, "namespace": NAMESPACE, "scale": scale,
            f"loadtest_{scale}_datasets": len(p["datasets"]),
            f"loadtest_{scale}_queries": len(p["queries"]),
            f"loadtest_{scale}_seed_seconds": round(time.perf_counter() - t0, 2),
            f"loadtest_{scale}_seed_api_calls": calls}


def cleanup(gms, scale: str, batch: int = 200) -> dict:
    """Loescht alles und LIEST JEDEN GELOESCHTEN ASPEKT ZURUECK -- inklusive
    `upstreamLineage`, dem Aspekt, um den diese ganze Spur geht.

    Eine Loeschung, die niemand nachprueft, ist eine Behauptung. Bleibt
    auch nur eine Entitaet uebrig, ist der Lauf rot und die Messzahl gilt
    nicht (`batch` bleibt Teil der Signatur, damit generate()/cleanup()
    symmetrisch aufgerufen werden koennen -- die Loeschung selbst ist pro
    Aspekt/URN, nicht batchbar ueber die v3-DELETE-Route).

    Ein fehlgeschlagenes Loeschen wird GESAMMELT und im Ergebnis gemeldet,
    nie stillschweigend verschluckt: "nichts zu loeschen" (Aspekt nie
    geschrieben) und "Loeschung fehlgeschlagen" (Auth/5xx/Netz) sind zwei
    verschiedene Aussagen -- live gegen 28080 unterschieden (siehe
    Modul-Docstring): ersteres liefert HTTP 200, letzteres wirft.
    `cleanup_verified` ist nur dann True, wenn WEDER Leftover NOCH ein
    Loeschfehler vorliegt.
    """
    p = plan(scale)
    errors: list[str] = []

    for u in p["datasets"]:
        for aspect in DATASET_ASPECTS:
            try:
                gms.delete_aspect("dataset", u, aspect)
            except Exception as exc:  # noqa: BLE001 - Fehler MUSS sichtbar bleiben, nie vanishen
                errors.append(f"delete_aspect dataset {u}.{aspect}: {exc}")
    for q in p["queries"]:
        try:
            gms.delete_aspect("query", q["urn"], "querySubjects")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"delete_aspect query {q['urn']}.querySubjects: {exc}")

    leftover = sum(
        1 for u in p["datasets"]
        for aspect in DATASET_ASPECTS
        if gms.get_aspect("dataset", u, aspect)
    ) + sum(
        1 for q in p["queries"] if gms.get_aspect("query", q["urn"], "querySubjects")
    )
    return {
        "scale": scale,
        "cleanup_leftover": leftover,
        "cleanup_errors": errors,
        "cleanup_verified": leftover == 0 and not errors,
    }


def run_smoke(gms, scale: str = "s", batch: int = 200, out_path: Path | None = None) -> dict:
    """Fuehrt generate() -> Stichproben-Rueckleseung -> cleanup() gegen ein
    ECHTES GMS und schreibt das Ergebnis als Artefakt nach harness/runs/.

    Grund fuer diese Funktion (Review-Runde 1, CRITICAL 2): eine Zahl in
    Prosa ohne ein Artefakt unter harness/runs/ ist eine Behauptung, keine
    Messung (global-constraints.md). Die Stichprobe VOR dem Cleanup belegt,
    dass generate() wirklich etwas Lebendes angelegt hat (Falle 1: HTTP 200
    ohne Wirkung), die Stichprobe NACH dem Cleanup, dass es wieder weg ist
    -- fuer alle drei Aspekt-Arten (Dataset-Properties, Lineage, Query-Subjects).
    """
    if out_path is None:
        out_path = Path("harness/runs/loadgen_smoke.json")

    p = plan(scale)
    sample_ds = p["datasets"][0]
    sample_down = p["edges"][0][1]  # Ziel der ersten Kante -- traegt upstreamLineage
    sample_q = p["queries"][0]["urn"]

    t0 = time.perf_counter()
    gen = generate(gms, scale, batch=batch)

    before = {
        "dataset_properties_present": gms.get_aspect("dataset", sample_ds, "datasetProperties") is not None,
        "upstream_lineage_present": gms.get_aspect("dataset", sample_down, "upstreamLineage") is not None,
        "query_subjects_present": gms.get_aspect("query", sample_q, "querySubjects") is not None,
    }

    clean = cleanup(gms, scale, batch=batch)

    after = {
        "dataset_properties_absent": gms.get_aspect("dataset", sample_ds, "datasetProperties") is None,
        "upstream_lineage_absent": gms.get_aspect("dataset", sample_down, "upstreamLineage") is None,
        "query_subjects_absent": gms.get_aspect("query", sample_q, "querySubjects") is None,
    }
    total_seconds = round(time.perf_counter() - t0, 2)

    artifact = {
        "seeded": True,
        "namespace": NAMESPACE,
        "scale": scale,
        "generate": gen,
        "cleanup": clean,
        "sample_written_before_cleanup": before,
        "sample_absent_after_cleanup": after,
        f"loadtest_{scale}_smoke_total_seconds": total_seconds,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return artifact


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gms-url", default="http://localhost:28080")
    p.add_argument("--scale", default="s", choices=sorted(SCALES))
    p.add_argument("--batch", type=int, default=200)
    p.add_argument("--token", default=None)
    p.add_argument("--out", default="harness/runs/loadgen_smoke.json")
    args = p.parse_args()

    token = args.token if args.token is not None else os.environ.get("DATAHUB_TOKEN")
    gms = Gms(base_url=args.gms_url, token=token)

    artifact = run_smoke(gms, args.scale, args.batch, Path(args.out))
    print(json.dumps(artifact, indent=2, ensure_ascii=False))

    ok = artifact["cleanup"]["cleanup_verified"]
    if not ok:
        print(f"\nFEHLER: cleanup_verified=False -- leftover="
              f"{artifact['cleanup']['cleanup_leftover']}, errors={artifact['cleanup']['cleanup_errors']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
