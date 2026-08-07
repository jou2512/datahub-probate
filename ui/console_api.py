"""Die Datenwege der Enterprise-Konsole -- serverseitig gefiltert,
sortiert und seitenweise.

WARUM diese Datei existiert (docs/werkbank-spec.md, "Der Massstab"): der
Katalog auf 28080 traegt **5.594 Datensaetze**. Eine Oberflaeche, die alles
holt und im Browser filtert, ist bei acht Zeilen huebsch und bei 5.594
unbenutzbar -- und genau das war Joels Befund. Jede Funktion hier nimmt
deshalb `start`/`count` entgegen und gibt IMMER `total` mit zurueck: die
Seite kann dann "N von 5.594" schreiben, ohne 5.594 Zeilen gesehen zu
haben.

Zwei harte Regeln aus der Sicherheits-Checkliste, die hier greifen:
  * KEIN f-String-GraphQL. Jede Abfrage ist eine Konstante, jeder Wert
    geht als Variable -- ein Tabellenname aus einem Suchfeld darf nie
    Teil des Abfragetexts werden.
  * Nur LESEN. Kein Weg in dieser Datei schreibt in den Katalog; die
    schreibenden Knoepfe bleiben in `ui/serve.py::do_action` hinter
    Journal und Rueckwaertsgang.
"""

from __future__ import annotations

import json
from pathlib import Path

# Facetten kommen aus den DATEN, nicht aus einer hartkodierten Liste
# (Spec: "Auswahlliste aus den Daten, nicht hartkodiert").
CATALOG_Q = """
query($q: String!, $start: Int!, $count: Int!) {
  searchAcrossEntities(input: {types: [DATASET], query: $q, start: $start, count: $count}) {
    start
    count
    total
    searchResults {
      entity {
        urn
        ... on Dataset {
          name
          platform { name }
          properties { name qualifiedName }
          subTypes { typeNames }
        }
      }
    }
    facets { field displayName aggregations { value count } }
  }
}
"""

# Der Zaehler allein -- `count: 0` liefert `total`, ohne eine einzige
# Zeile zu uebertragen. Das ist die billigste Art, "von 5.594" zu belegen.
CATALOG_COUNT_Q = """
query($q: String!) {
  searchAcrossEntities(input: {types: [DATASET], query: $q, start: 0, count: 0}) { total }
}
"""


def split_urn(urn: str) -> dict:
    """Ein Dataset-URN in seine Bestandteile -- Plattform, Datenbank,
    Schema, Tabelle, Umgebung.

    Spec, Spalte "Von"/"Nach": *"Die Herkunft steht klein UEBER dem
    Tabellennamen"*. Dafuer muss die Herkunft ueberhaupt getrennt
    vorliegen. Ein Name ohne seinen Ort ist bei 5.594 Datensaetzen
    wertlos -- und `probate_seedlab.store_sales_ranking_east` allein
    beantwortet die Frage "in welchem Katalog?" nicht.

    Robust gegen alles, was nicht dem Muster entspricht: was sich nicht
    zerlegen laesst, kommt vollstaendig als `table` zurueck, nie als
    erfundene Struktur.
    """
    out = {"platform": "", "database": "", "schema": "", "table": urn or "",
           "env": "", "qualified": "", "urn": urn or ""}
    if not urn or not urn.startswith("urn:li:dataset:("):
        return out
    inner = urn[len("urn:li:dataset:("):].rstrip(")")
    parts = inner.split(",")
    if len(parts) < 3:
        return out
    platform, qualified, env = parts[0], ",".join(parts[1:-1]), parts[-1]
    out["platform"] = platform.rsplit(":", 1)[-1]
    out["env"] = env
    out["qualified"] = qualified
    segs = qualified.split(".")
    out["table"] = segs[-1]
    if len(segs) == 2:
        out["database"] = segs[0]
    elif len(segs) >= 3:
        out["database"], out["schema"] = segs[0], ".".join(segs[1:-1])
    return out


def edge_row(edge: dict) -> dict:
    """Eine Register-Zeile in Tabellen-Form: beide Seiten zerlegt, die
    Belege gezaehlt, `last_covered` als DATUM oder als das Wort "nicht
    gemessen" -- nie als leeres Feld (Null-Regel der Spec)."""
    cov = edge.get("coverage") or {}
    tl = edge.get("timeline") or {}
    series = tl.get("series") or []
    return {
        "edge": edge.get("edge", ""),
        "state": edge.get("state", ""),
        "from": split_urn(edge.get("upstream", "")),
        "to": split_urn(edge.get("downstream", "")),
        "query_urns": (edge.get("evidence") or {}).get("query_urns") or [],
        "source": (edge.get("evidence") or {}).get("source", ""),
        "buckets_seen": cov.get("buckets_seen") or 0,
        "measured": cov.get("buckets_seen", 0) > 0,
        "traffic_total": sum(n for _, n in series),
        "zero_windows": sum(1 for _, n in series if n == 0),
        "days_span": cov.get("days_span"),
        "reason": cov.get("reason", ""),
        "last_covered_ms": tl.get("last_covered_ms"),
        "dead_since_days": tl.get("dead_since_days"),
        "dead_since_is_lower_bound": bool(tl.get("dead_since_is_lower_bound")),
        "series": series,
    }


_SORTS = {
    "state": lambda r: r["state"],
    "from": lambda r: (r["from"]["qualified"] or ""),
    "to": lambda r: (r["to"]["qualified"] or ""),
    "evidence": lambda r: (len(r["query_urns"]), r["buckets_seen"]),
    # Nicht gemessene Kanten sortieren ans ENDE, nicht an den Anfang: eine
    # fehlende Messung ist kein "sehr altes Datum".
    "last": lambda r: (r["last_covered_ms"] is None, r["last_covered_ms"] or 0),
    "traffic": lambda r: r["traffic_total"],
}


def filter_sort_page(edges: list[dict], judgements: dict, params: dict) -> dict:
    """Filtern, sortieren, seitenweise schneiden -- alles hier, nichts im
    Browser. Rueckgabe traegt IMMER `total` (nach Filter) und
    `total_unfiltered`, damit die Seite "N von M" schreiben kann.

    `judgements`: Kanten-Schluessel -> Urteil. Zwei Filter haengen daran
    ("nur mit Modellurteil", "nur Enthaltungen"); sie werden hier
    ausgewertet, damit der Browser die Urteile nicht komplett laden muss.
    """
    rows = [edge_row(e) for e in edges]
    for r in rows:
        j = judgements.get(r["edge"])
        r["judgement"] = (
            "none" if j is None
            else "model" if j.get("used_model")
            else "abstained"
        )
        r["important"] = bool(j.get("important")) if j else False

    total_unfiltered = len(rows)

    states = {s for s in (params.get("state") or "").split(",") if s}
    if states:
        rows = [r for r in rows if r["state"] in states]
    for key, side in (("platform", "platform"), ("database", "database")):
        want = (params.get(key) or "").strip()
        if want:
            rows = [r for r in rows
                    if r["from"][side] == want or r["to"][side] == want]
    table = (params.get("table") or "").strip()
    if table:
        rows = [r for r in rows
                if table in (r["from"]["qualified"], r["to"]["qualified"])]
    q = (params.get("q") or "").strip().lower()
    if q:
        rows = [r for r in rows
                if q in r["from"]["qualified"].lower()
                or q in r["to"]["qualified"].lower()]
    if (params.get("judged") or "") == "1":
        rows = [r for r in rows if r["judgement"] == "model"]
    if (params.get("abstained") or "") == "1":
        rows = [r for r in rows if r["judgement"] == "abstained"]

    sort_key = params.get("sort") or "state"
    reverse = (params.get("dir") or "asc") == "desc"
    rows.sort(key=_SORTS.get(sort_key, _SORTS["state"]), reverse=reverse)

    start = max(0, int(params.get("start") or 0))
    count = min(200, max(1, int(params.get("count") or 50)))
    page = rows[start:start + count]

    by_state = {s: 0 for s in ("confirmed", "dead", "missing", "unknown")}
    for r in (edge_row(e) for e in edges):
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1

    return {
        "rows": page,
        "start": start,
        "count": len(page),
        "total": len(rows),
        "total_unfiltered": total_unfiltered,
        "state_counts": by_state,
    }


def facets(edges: list[dict]) -> dict:
    """Die Auswahllisten der Filterzeile -- aus den Daten gezogen, nie
    hartkodiert (Spec)."""
    platforms: dict[str, int] = {}
    databases: dict[str, int] = {}
    for e in edges:
        for side in ("upstream", "downstream"):
            p = split_urn(e.get(side, ""))
            if p["platform"]:
                platforms[p["platform"]] = platforms.get(p["platform"], 0) + 1
            if p["database"]:
                databases[p["database"]] = databases.get(p["database"], 0) + 1
    return {
        "platforms": sorted(({"value": k, "count": v} for k, v in platforms.items()),
                             key=lambda x: -x["count"]),
        "databases": sorted(({"value": k, "count": v} for k, v in databases.items()),
                             key=lambda x: -x["count"]),
    }


def catalog_page(gms, q: str, start: int, count: int, known: dict) -> dict:
    """Eine SEITE des Katalogbaums -- niemals der ganze Katalog.

    `known`: Tabellen-URN -> Zustand, aus dem letzten Lauf. Der Baum
    zeigt einen Zustandspunkt nur, wo wirklich ein Urteil vorliegt; alle
    anderen Tabellen tragen ausdruecklich "nicht geprueft" statt eines
    grauen Punkts, der wie "unauffaellig" aussaehe.
    """
    count = min(200, max(1, count))
    data = gms.graphql(CATALOG_Q, {"q": q or "*", "start": max(0, start), "count": count})
    res = data.get("searchAcrossEntities") or {}
    out = []
    for hit in res.get("searchResults") or []:
        ent = hit.get("entity") or {}
        parts = split_urn(ent.get("urn", ""))
        props = ent.get("properties") or {}
        parts["display"] = props.get("name") or parts["table"]
        parts["state"] = known.get(ent.get("urn", ""), "")
        parts["checked"] = ent.get("urn", "") in known
        out.append(parts)
    return {
        "rows": out,
        "start": res.get("start", start),
        "count": res.get("count", len(out)),
        "total": res.get("total", 0),
        "facets": res.get("facets") or [],
    }


def catalog_total(gms, q: str = "*") -> int:
    data = gms.graphql(CATALOG_COUNT_Q, {"q": q or "*"})
    return int(((data.get("searchAcrossEntities") or {}).get("total")) or 0)


# --- Bereich "Laeufe": die Artefakte auf der Platte ---------------------
#
# Ein Lauf ist erst dann ein Lauf, wenn er ein Artefakt hinterlassen hat.
# Diese Liste liest deshalb das Verzeichnis, statt eine Historie im
# Speicher zu fuehren, die ein Neustart verschluckt.

_RUN_DIR = Path("harness/runs")
_RUN_FILES = ("demo-katalog-ledger.json", "ledger.json", "seedlab-verdicts.json",
              "judge-seedlab-matrix.json",
              "ledger-vor-ereignis.json", "ledger-nach-ereignis.json",
              "full-vs-delta.json", "correct-roundtrip.json", "campaign.json")
# demo-katalog-ledger.json (2026-08-07): der Lauf ueber den Demo-Katalog
# in Unternehmensgroesse (harness/run_demo_ledger.py) -- mehrere hundert
# Kanten ueber vier Plattformen und fuenf Datenbanken. Er steht bewusst
# ZUERST: die Liste wird nach Zeitstempel sortiert, aber wer sie liest,
# soll den Lauf, der die Konsole traegt, nicht suchen muessen.


def _summarise_run(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    row = {
        "artifact": str(path).replace("\\", "/"),
        "name": path.name,
        "at_iso": data.get("recorded_at_iso") or data.get("run_at_iso")
                   or data.get("generated_at") or "",
        "edges_total": data.get("edges_total"),
        "confirmed": data.get("edges_confirmed"),
        "dead": data.get("edges_dead"),
        "missing": data.get("edges_missing"),
        "unknown": data.get("edges_unknown"),
        "api_calls": data.get("api_calls"),
        "seeded": bool(data.get("seeded")),
        "size_bytes": path.stat().st_size,
    }
    judged = data.get("judged_edges")
    fallback = data.get("judged_fallback")
    if isinstance(judged, int) and judged:
        row["abstention_rate"] = round((fallback or 0) / judged, 3)
    return row


def runs(run_dir: Path = _RUN_DIR) -> list[dict]:
    out = []
    for name in _RUN_FILES:
        p = run_dir / name
        if p.exists():
            row = _summarise_run(p)
            if row:
                out.append(row)
    out.sort(key=lambda r: r["at_iso"], reverse=True)
    return out


def evidence(edges: list[dict], judgements: dict, q: str = "") -> list[dict]:
    """Bereich 5: alle gesammelten Belege an einem Ort, durchsuchbar.
    Drei Arten, jede mit ihrer Herkunft -- Zitat (mit Quellfeld),
    Abfrage-URN, Nutzungsfenster."""
    q = (q or "").strip().lower()
    out: list[dict] = []
    for e in edges:
        row = edge_row(e)
        label = f"{row['from']['table']} → {row['to']['table']}"
        for urn in row["query_urns"]:
            out.append({"kind": "query", "edge": row["edge"], "label": label,
                        "text": urn, "detail": "query touching both tables"})
        if row["measured"]:
            out.append({"kind": "usage", "edge": row["edge"], "label": label,
                        "text": f"{row['buckets_seen']} usage windows, "
                                 f"{row['traffic_total']} queries, "
                                 f"{row['zero_windows']} of them measured at zero",
                        "detail": f"span {row['days_span']} days"})
        else:
            out.append({"kind": "gap", "edge": row["edge"], "label": label,
                        "text": "not measured — no usage window at all",
                        "detail": row["reason"]})
        j = judgements.get(row["edge"])
        if j and j.get("used_model") and j.get("quote"):
            out.append({"kind": "quote", "edge": row["edge"], "label": label,
                        "text": j["quote"],
                        "detail": f"verbatim from field “{j.get('source_field') or 'unknown'}”"})
        elif j:
            out.append({"kind": "abstention", "edge": row["edge"], "label": label,
                        "text": j.get("fallback_reason") or "no reason recorded",
                        "detail": "model abstained — deterministic verdict stands"})
    if q:
        out = [r for r in out
               if q in r["text"].lower() or q in r["label"].lower()
               or q in (r["detail"] or "").lower()]
    return out
