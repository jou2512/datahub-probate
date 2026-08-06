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
"""

from __future__ import annotations

import time

NAMESPACE = "probate_load"
PLATFORM = "urn:li:dataPlatform:snowflake"
SCALES = {"s": (50, 1_000), "m": (500, 10_000), "l": (5_000, 100_000)}
SUBJECTS_PER_QUERY = 3


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
    """Loescht alles und LIEST DIE LOESCHUNG ZURUECK.

    Eine Loeschung, die niemand nachprueft, ist eine Behauptung. Bleibt
    auch nur eine Entitaet uebrig, ist der Lauf rot und die Messzahl
    gilt nicht (batch bleibt Teil der Signatur, damit generate()/cleanup()
    symmetrisch aufgerufen werden koennen -- die Loeschung selbst ist pro
    Aspekt/URN, nicht batchbar ueber die v3-DELETE-Route).
    """
    p = plan(scale)
    for u in p["datasets"]:
        for aspect in ("upstreamLineage", "datasetProperties", "datasetUsageStatistics"):
            try:
                gms.delete_aspect("dataset", u, aspect)
            except Exception:
                pass
    for q in p["queries"]:
        try:
            gms.delete_aspect("query", q["urn"], "querySubjects")
        except Exception:
            pass

    leftover = sum(
        1 for u in p["datasets"] if gms.get_aspect("dataset", u, "datasetProperties")
    ) + sum(
        1 for q in p["queries"] if gms.get_aspect("query", q["urn"], "querySubjects")
    )
    return {"scale": scale, "cleanup_leftover": leftover,
            "cleanup_verified": leftover == 0}
