"""Der Messlauf. Nicht die Behauptung, dass es skaliert -- die Zahl.

Der Lastentwurf aus der Spec, zweistufig: grober Durchgang ueber die
verdichteten Zahlen (eine Zahl pro Tabelle und Zeitfenster, unabhaengig
von der Abfragezahl), Detailblick nur bei auffaelligen Kanten. Damit
haengt der teure Teil an der Zahl VERDAECHTIGER Kanten, nicht an der
Gesamtzahl der Abfragen.

Wenn es kippt, kommt die Zahl trotzdem ins README -- mit der Groesse, ab
der es nicht mehr traegt. Eine benannte Grenze ist ein Ergebnis; eine
verschwiegene ist ein Fehler.

`STATS_SUMMARY_Q` fragt bewusst `statsSummary` (verdichtete Aggregate) ab,
nicht `usageStats` mit `startTimeMillis` -- Letzteres liefert nachweislich
falsche/null Aggregationen (UEBERGABE.md, bekannte Falle). Der grobe
Durchgang zaehlt jede Abfrage UND jede Antwortgroesse mit, damit Falle 12
(`get_lineage` >100'000 Zeichen ohne Pagination) sichtbar wird, bevor sie
den Detail-Durchgang trifft.

`detail_pass` ruft `probate.ledger.fetch_cooccurrence` bewusst lazy (innerhalb
der Funktion) auf, nicht beim Modulimport -- diese Funktion gehoert einer
anderen, noch laufenden Lane (progress.md: "Task 6"); ein fruehes Import
wuerde `harness.loadtest` an ihre Fertigstellung koppeln, obwohl das
Messgeruest selbst unabhaengig fertig werden kann. `detail_pass` bricht bei
einem einzelnen kaputten Aufruf zudem NICHT die ganze Stichprobe ab -- bei
41 Kanten waere ein Fehler sonst der Grund, warum die anderen 40 nie
gemessen werden (siehe Docstring dort).
"""

from __future__ import annotations

import time
import tracemalloc

STATS_SUMMARY_Q = """
query($urn: String!) {
  dataset(urn: $urn) {
    statsSummary { queryCountLast30Days uniqueUserCountLast30Days }
  }
}
"""


def measure(fn, *a, **kw) -> tuple[object, dict]:
    """Misst eine einzelne Aktion: echte Sekunden (perf_counter), echter
    Spitzenspeicher (tracemalloc) -- keine Schaetzung. Ein Fehler wird
    NICHT verschluckt: `broke`/`error` tragen ihn weiter, das Ergebnis wird
    `None` statt eine halbe Antwort vorzutaeuschen."""
    tracemalloc.start()
    t0 = time.perf_counter()
    result, broke, err = None, False, ""
    try:
        result = fn(*a, **kw)
    except Exception as exc:  # noqa: BLE001 - der Fehler MUSS sichtbar bleiben, nie verschwinden
        broke, err = True, f"{type(exc).__name__}: {exc}"[:500]
    seconds = round(time.perf_counter() - t0, 3)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, {"seconds": seconds,
                     "peak_memory_mb": round(peak / 1_048_576, 2),
                     "broke": broke, "error": err}


def coarse_pass(gms, scale: str) -> dict:
    """Eine Zahl pro Tabelle -- unabhaengig von der Abfragezahl.

    Ein Dataset ohne statsSummary (`None`, z.B. weil der Suchindex das
    Schreiben noch nicht nachgezogen hat -- Falle "graph/search index
    hinkt ~30s nach") gilt als AUFFAELLIG, nicht als Fehler: es ist ein
    Kandidat fuer den Detail-Durchgang, keine Ausnahme, die die ganze
    Messung abbricht.
    """
    from harness.loadgen import plan
    p = plan(scale)
    calls, suspicious, chars = 0, [], 0
    for urn in p["datasets"]:
        data = gms.graphql(STATS_SUMMARY_Q, {"urn": urn})
        calls += 1
        chars += len(str(data))
        summary = ((data.get("dataset") or {}).get("statsSummary") or {})
        if not summary.get("queryCountLast30Days"):
            suspicious.append(urn)
    return {"coarse_api_calls": calls, "coarse_response_chars": chars,
            "coarse_suspicious": len(suspicious), "_suspicious": suspicious}


def detail_pass(gms, edges: list[str]) -> dict:
    """Nur die auffaelligen Kanten -- der teure Teil.

    Ein einzelner kaputter Aufruf bricht die Stichprobe NICHT ab: sonst
    waere ein Fehler bei Kante 2 von 41 der Grund, warum Kanten 3-41 nie
    gemessen werden -- eine verschwiegene Abwesenheit von Daten statt eines
    Messergebnisses (global-constraints.md: "eine gescheiterte Abfrage ist
    keine Abwesenheit"). Stattdessen wird der ERSTE Bruchpunkt samt
    Fehlertext festgehalten (`detail_break_urn`/`detail_break_error`),
    zusaetzlich die Gesamtzahl gescheiterter Kanten (`detail_error_count`).
    Fehlgeschlagene Aufrufe zaehlen zu `detail_edges` (versucht), fliessen
    aber mit ihrer eigenen (meist kurzen) `seconds`-Messung in den
    Durchschnitt ein -- das ist ehrlicher als sie zu ignorieren, denn eine
    schnelle Antwort MIT Fehler ist trotzdem eine Antwort.
    """
    if not edges:
        return {"detail_edges": 0, "detail_seconds_total": 0.0, "detail_seconds_per_edge": 0.0,
                "detail_broke": False, "detail_break_urn": "", "detail_break_error": "",
                "detail_error_count": 0}

    from probate.ledger import fetch_cooccurrence

    per_edge_seconds = []
    break_urn, break_error, error_count = "", "", 0
    for urn in edges:
        _, m = measure(fetch_cooccurrence, gms, urn)
        per_edge_seconds.append(m["seconds"])
        if m["broke"]:
            error_count += 1
            if not break_urn:
                break_urn, break_error = urn, m["error"]

    total = round(sum(per_edge_seconds), 3)
    return {
        "detail_edges": len(edges),
        "detail_seconds_total": total,
        "detail_seconds_per_edge": round(total / len(edges), 4),
        "detail_broke": error_count > 0,
        "detail_break_urn": break_urn,
        "detail_break_error": break_error,
        "detail_error_count": error_count,
    }


def run_stage(gms, scale: str, detail_sample: int = 41) -> dict:
    """Eine vollstaendige Stufe: seeden, grob, detail, aufraeumen.

    `detail_sample` ist 41, weil das die Zahl aus dem Lastentwurf der Spec
    ist (41 Auffaelligkeiten bei 384 Kanten). Weicht die Messung davon ab,
    wird die TATSAECHLICHE Zahl ausgewiesen (`loadtest_<scale>_detail_edges`),
    nicht die geplante.

    Jede Stufe (Seed, Grob, Detail) wird einzeln mit `measure()` umschlossen,
    damit ein Absturz auf einer Stufe die anderen nicht verhindert und mit
    eigenem Fehlertext ausgewiesen wird -- die Bruchstelle bleibt benennbar,
    egal auf welcher Stufe sie liegt. Alle drei cleanup()-Zahlen
    (`leftover`/`verified`/`errors`) werden mit `loadtest_<scale>_` prefixed,
    nicht nur die ersten beiden wie im urspruenglichen Entwurf -- sonst
    kollidiert `cleanup_errors` bei mehreren Stufen in einem gemeinsamen
    Artefakt (Task 23 faehrt s/m/l nacheinander).
    """
    from harness.loadgen import cleanup, generate
    out = {"seeded": True, "scale": scale}

    seed, m_seed = measure(generate, gms, scale)
    out.update(seed or {})
    out[f"loadtest_{scale}_seed_broke"] = m_seed["broke"]
    if m_seed["broke"]:
        out[f"loadtest_{scale}_seed_error"] = m_seed["error"]

    coarse, m_coarse = measure(coarse_pass, gms, scale)
    coarse = coarse or {}
    out[f"loadtest_{scale}_coarse_seconds"] = m_coarse["seconds"]
    out[f"loadtest_{scale}_coarse_peak_mb"] = m_coarse["peak_memory_mb"]
    out[f"loadtest_{scale}_coarse_api_calls"] = coarse.get("coarse_api_calls", 0)
    out[f"loadtest_{scale}_coarse_response_chars"] = coarse.get("coarse_response_chars", 0)
    out[f"loadtest_{scale}_coarse_broke"] = m_coarse["broke"]
    if m_coarse["broke"]:
        out[f"loadtest_{scale}_coarse_error"] = m_coarse["error"]

    sample = (coarse.get("_suspicious") or [])[:detail_sample]
    detail, m_detail = measure(detail_pass, gms, sample)
    detail = detail or {}
    out[f"loadtest_{scale}_detail_edges"] = detail.get("detail_edges", 0)
    out[f"loadtest_{scale}_detail_seconds_total"] = detail.get("detail_seconds_total", 0.0)
    out[f"loadtest_{scale}_detail_seconds_per_edge"] = detail.get("detail_seconds_per_edge", 0.0)
    out[f"loadtest_{scale}_detail_peak_mb"] = m_detail["peak_memory_mb"]
    broke = m_detail["broke"] or detail.get("detail_broke", False)
    out[f"loadtest_{scale}_detail_broke"] = broke
    if broke:
        out[f"loadtest_{scale}_detail_error"] = m_detail["error"] or detail.get("detail_break_error", "")
        out[f"loadtest_{scale}_detail_break_urn"] = detail.get("detail_break_urn", "")

    clean = cleanup(gms, scale)
    out[f"loadtest_{scale}_cleanup_verified"] = clean["cleanup_verified"]
    out[f"loadtest_{scale}_cleanup_leftover"] = clean["cleanup_leftover"]
    out[f"loadtest_{scale}_cleanup_errors"] = clean["cleanup_errors"]
    return out
