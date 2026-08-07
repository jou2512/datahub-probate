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

# --- Governance: Domaene und Besitzer -----------------------------------
#
# Die Spec (Bereich 2, Filtertabelle) verlangt eine Auswahlliste "Domaene"
# und eine "Besitzer". Beides steht im KATALOG, nicht im Register: ein
# Lauf misst Kanten, keine Governance. `harness/fetch_governance.py` liest
# es einmal aus GMS und legt es als Artefakt hin; hier wird nur noch
# gelesen.
#
# Die drei Faelle, die verschieden aussehen MUESSEN (Null-Regel):
#   Artefakt fehlt          -> `measured: False` + Grund; die Konsole bietet
#                              den Filter gar nicht erst an.
#   Tabelle drin, kein Wert -> gemessene Abwesenheit ("keine Domaene").
#   Tabelle nicht drin      -> "nicht nachgeschlagen".
GOVERNANCE_PATH = Path("harness/runs/demo-katalog-governance.json")

_NO_GOVERNANCE = (
    "Domain and owner were never looked up: no governance artifact on disk "
    "(harness/runs/demo-katalog-governance.json). Run "
    "`python -m harness.fetch_governance` against the catalog. The filters "
    "stay closed rather than offering values nobody measured."
)

# Kein Wert, aber GEMESSEN. Bewusst ein Sonderwert und kein leerer String:
# "alle" (kein Filter) und "die ohne Domaene" (ein Filter) sind zwei
# verschiedene Fragen, und ein leerer String kann nur eine davon stellen.
NONE_VALUE = "__none__"

_gov_cache: dict = {"key": None, "data": None}


def load_governance(path=None) -> dict:
    """Das Governance-Artefakt -- oder eine ehrliche Fehlanzeige.

    Zwischengespeichert ueber (Pfad, mtime, Groesse): der Weg
    `/api/connections` laeuft bei jedem Seitenwechsel, und die Datei
    einmal je Klick zu lesen waere eine erfundene Last. Ein neu
    geschriebenes Artefakt wird trotzdem sofort gesehen, weil sich mtime
    und Groesse aendern -- kein Neustart noetig.
    """
    p = Path(path or GOVERNANCE_PATH)
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        return {"measured": False, "reason": _NO_GOVERNANCE, "tables": {}}
    if _gov_cache["key"] == key:
        return _gov_cache["data"]
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # Eine unlesbare Datei ist NICHT dasselbe wie eine fehlende: der
        # Grund nennt sie, damit niemand nach einem Artefakt sucht, das da
        # ist.
        return {"measured": False, "tables": {},
                "reason": f"The governance artifact exists but could not be read ({exc})."}
    data = {
        "measured": True,
        "reason": "",
        "tables": raw.get("tables") or {},
        "generated_at_iso": raw.get("generated_at_iso", ""),
        "source": str(p).replace("\\", "/"),
        "tables_looked_up": raw.get("tables_looked_up", 0),
        "tables_with_domain": raw.get("tables_with_domain", 0),
        "tables_with_owner": raw.get("tables_with_owner", 0),
    }
    _gov_cache.update(key=key, data=data)
    return data


# --- Der Namensraum, der kein Ausrutscher ist ---------------------------
#
# In der Datenbank-Auswahlliste steht `probate_seedlab` neben fuenf
# `probate_demo_*`-Datenbanken und sieht dort aus wie ein Tippfehler im
# Namensschema. Es ist das Gegenteil: dort liegen die vier BEWIESENEN
# Zustaende (je eine Kante pro Urteil) und die gemessenen Uebergaenge --
# das kleine Labor, an dem sich die Aussagen der Werkbank nachrechnen
# lassen.
#
# Der Hinweis wird NICHT hier getippt, sondern aus den Artefakten
# abgeleitet: Namensraum und Kantenzahl aus dem Seedlab-Manifest, die Zahl
# der Uebergaenge aus dem Uebergangs-Protokoll. Ein hartkodierter Satz
# waere morgen falsch, ohne dass es jemand merkt.
LAB_MANIFEST_PATH = Path("examples/seedlab-manifest.json")
LAB_TRANSITIONS_PATH = Path("harness/runs/demo-transitions.json")


def lab_notes(manifest=None, transitions=None) -> dict:
    """`{datenbankname: {"label": ..., "note": ...}}` -- leer, wenn die
    Artefakte fehlen. Lieber gar kein Hinweis als ein erfundener."""
    try:
        m = json.loads(Path(manifest or LAB_MANIFEST_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    namespace = m.get("namespace") or ""
    edges = m.get("edges") or []
    states = sorted({e.get("expected_edge_state") for e in edges
                     if e.get("expected_edge_state")})
    if not namespace or not states:
        return {}
    proven = None
    try:
        t = json.loads(Path(transitions or LAB_TRANSITIONS_PATH).read_text(encoding="utf-8"))
        if t.get("transitions_all_proven"):
            proven = t.get("transitions_proven")
    except (OSError, ValueError):
        proven = None
    note = (f"The {len(states)}-state lab: one proven edge per verdict "
            f"({', '.join(states)}), seeded on purpose so every claim on this "
            f"bench can be recomputed by hand.")
    if proven:
        note += f" {proven} state transitions were measured here."
    return {namespace: {"label": f"{len(states)}-state lab", "note": note}}


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


def _governed(ref: dict, gov: dict) -> dict:
    """Domaene und Besitzer an eine zerlegte Tabellen-Angabe haengen.

    `known` unterscheidet "nachgeschlagen, nichts dran" von "nie
    nachgeschlagen" -- ohne dieses Feld sehen beide wie `None` aus, und
    genau das verbietet die Null-Regel.
    """
    tables = gov.get("tables") or {}
    info = tables.get(ref.get("urn") or "")
    ref["known"] = info is not None
    ref["domain"] = (info or {}).get("domain") or ""
    ref["domain_name"] = (info or {}).get("domain_name") or ""
    ref["owners"] = (info or {}).get("owners") or []
    return ref


# Die drei Sorten Messung, die eine Zeile auseinanderhalten MUSS.
#
# Gemessen am 07.08. ueber die 513 Kanten des Demo-Registers:
#   "traffic" (399) -- es gibt ein juengstes Datum mit Verkehr.
#   "zero"    ( 55) -- Fenster wurden geprueft, JEDES hat null gemessen.
#                      Das ist eine GEMESSENE NULL, kein fehlender Wert.
#   "none"    ( 59) -- gar kein Nutzungsfenster im Katalog. Erst hier ist
#                      "nicht gemessen" die Wahrheit.
#
# Bis dahin fielen "zero" und "none" in der Spalte "Zuletzt belegt"
# zusammen auf das Wort "not measured" -- 55 Zeilen behaupteten damit eine
# fehlende Messung, wo in Wahrheit gemessen und nichts gefunden wurde.
# Das ist derselbe Fehler, den dieses Produkt bei anderen anprangert, nur
# in der eigenen Tabelle.
def measurement_kind(buckets_seen: int, last_covered_ms) -> str:
    if not buckets_seen:
        return "none"
    return "traffic" if last_covered_ms else "zero"


# Zwei Sorten `dead`, und die Zeile muss sie unterscheiden koennen, ohne
# dass jemand die Detailspalte oeffnet.
#
#   "no-window" (41) -- die Fenster liefen, alle massen null. Nichts ist
#                       geflossen, an keinem der beiden Enden.
#   "no-pair"   (32) -- beide Tabellen hatten sehr wohl Verkehr, aber
#                       KEINE Abfrage hat sie zusammen beruehrt. Genau
#                       diese Zeilen zeigten bisher ein frisches Datum in
#                       "Zuletzt belegt" und lasen sich als Widerspruch:
#                       tot, aber heute gemessen? Das Datum gehoerte den
#                       TABELLEN, die Aussage der Zeile aber der KANTE.
DEAD_KIND = {"zero": "no-window", "traffic": "no-pair"}


def edge_row(edge: dict, gov: dict | None = None) -> dict:
    """Eine Register-Zeile in Tabellen-Form: beide Seiten zerlegt, die
    Belege gezaehlt, `last_covered` als DATUM oder als das Wort "nicht
    gemessen" -- nie als leeres Feld (Null-Regel der Spec)."""
    cov = edge.get("coverage") or {}
    tl = edge.get("timeline") or {}
    series = tl.get("series") or []
    gov = gov or {"tables": {}}
    buckets = cov.get("buckets_seen") or 0
    kind = measurement_kind(buckets, tl.get("last_covered_ms"))
    state = edge.get("state", "")
    return {
        "edge": edge.get("edge", ""),
        "state": state,
        "measurement": kind,
        "dead_kind": DEAD_KIND.get(kind, "") if state == "dead" else "",
        "from": _governed(split_urn(edge.get("upstream", "")), gov),
        "to": _governed(split_urn(edge.get("downstream", "")), gov),
        "query_urns": (edge.get("evidence") or {}).get("query_urns") or [],
        "source": (edge.get("evidence") or {}).get("source", ""),
        "buckets_seen": cov.get("buckets_seen") or 0,
        "measured": cov.get("buckets_seen", 0) > 0,
        "traffic_total": sum(n for _, n in series),
        "zero_windows": sum(1 for _, n in series if n == 0),
        "days_span": cov.get("days_span"),
        # Wie lang das gepruefte Fenster war. Die Zeile braucht es, um
        # "keine Abfrage hat beide beruehrt" zu begrenzen: ohne die Zahl
        # klaenge es nach "nie in der Geschichte", gemessen sind aber 33
        # Tage.
        "window_days": cov.get("window_days") or (edge.get("evidence") or {}).get("window_days"),
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


def _has_domain(row: dict, want: str) -> bool:
    """Eine Kante gehoert zu einer Domaene, wenn EINES ihrer Enden dazu
    gehoert -- dieselbe Regel wie bei Plattform und Datenbank.

    `__none__` fragt nach den Enden, die nachgeschlagen wurden und trotzdem
    keine Domaene tragen. Eine Tabelle, die nie nachgeschlagen wurde
    (`known: False`), zaehlt hier ausdruecklich NICHT mit: sonst waere
    "keine Domaene" ein Sammelbecken aus gemessener Abwesenheit und
    Unwissen.
    """
    sides = (row["from"], row["to"])
    if want == NONE_VALUE:
        return any(s["known"] and not s["domain"] for s in sides)
    return any(s["domain"] == want for s in sides)


def _has_owner(row: dict, want: str) -> bool:
    sides = (row["from"], row["to"])
    if want == NONE_VALUE:
        return any(s["known"] and not s["owners"] for s in sides)
    return any(any(o.get("urn") == want for o in s["owners"]) for s in sides)


def _idle_days(row: dict):
    """Wie lange die Kante schon nichts mehr getragen hat -- oder `None`,
    wenn das mangels Messung nicht sagbar ist."""
    return row.get("dead_since_days")


def filter_sort_page(edges: list[dict], judgements: dict, params: dict,
                     gov: dict | None = None) -> dict:
    """Filtern, sortieren, seitenweise schneiden -- alles hier, nichts im
    Browser. Rueckgabe traegt IMMER `total` (nach Filter) und
    `total_unfiltered`, damit die Seite "N von M" schreiben kann.

    `judgements`: Kanten-Schluessel -> Urteil. Zwei Filter haengen daran
    ("nur mit Modellurteil", "nur Enthaltungen"); sie werden hier
    ausgewertet, damit der Browser die Urteile nicht komplett laden muss.

    `gov`: das Governance-Artefakt (`load_governance()`). Ohne es bleiben
    Domaenen- und Besitzer-Filter wirkungslos statt zu raten.
    """
    gov = gov if gov is not None else load_governance()
    rows = [edge_row(e, gov) for e in edges]
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
    domain = (params.get("domain") or "").strip()
    if domain:
        rows = [r for r in rows if _has_domain(r, domain)]
    owner = (params.get("owner") or "").strip()
    if owner:
        rows = [r for r in rows if _has_owner(r, owner)]

    # --- Zeitraum (Spec: "7 / 30 / 90 Tage / eigener") ------------------
    #
    # ABWEICHUNG, bewusst und hier begruendet: die Spec nennt einen
    # Zeitraum, gemeint ist ueblicherweise das MESSFENSTER. Das kann diese
    # Ansicht nicht anbieten, ohne zu luegen -- sie blaettert ein
    # aufgezeichnetes Register, dessen Fenster mit 33 Tagen feststeht
    # (gemessen: `window_days` ist bei allen 513 Kanten 33). Eine
    # Auswahl "7 Tage" wuerde behaupten, es sei ein 7-Tage-Fenster
    # gemessen worden; tatsaechlich waere nur weniger angezeigt.
    #
    # Die Gegenprobe dazu ist gemessen, nicht vermutet: filtert man nach
    # "juengster Beleg innerhalb von N Tagen", liefern 7, 30 und 90 alle
    # dieselben 399 Zeilen. Drei Knoepfe, die immer dasselbe tun, sind
    # schlimmer als keiner -- sie sehen aus wie eine Einschraenkung.
    #
    # Gebaut ist deshalb die Frage, die ein Betreiber wirklich stellt und
    # die die Daten beantworten koennen: **wie lange traegt diese Kante
    # schon nichts mehr?** (`timeline.dead_since_days`, eine gemessene
    # Groesse). Kanten ohne jede Messung koennen nicht gealtert werden --
    # sie verschwinden nicht stillschweigend, sondern werden als
    # `unaged` GEZAEHLT und von der Oberflaeche benannt.
    idle_raw = (params.get("idle") or "").strip()
    unaged = 0
    if idle_raw:
        try:
            idle_min = max(0, int(idle_raw))
        except ValueError:
            idle_min = 0
        if idle_raw and idle_min >= 0:
            unaged = sum(1 for r in rows if _idle_days(r) is None)
            rows = [r for r in rows
                    if _idle_days(r) is not None and _idle_days(r) >= idle_min]

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
    for e in edges:
        st = e.get("state", "")
        by_state[st] = by_state.get(st, 0) + 1

    return {
        "rows": page,
        "start": start,
        "count": len(page),
        "total": len(rows),
        "total_unfiltered": total_unfiltered,
        "state_counts": by_state,
        # Nur gesetzt, wenn nach Stillstandsdauer gefiltert wurde: so viele
        # Kanten liessen sich mangels Messung nicht altern. Ohne diese Zahl
        # waeren sie einfach weg -- und ein Filter, der schweigend etwas
        # verschwinden laesst, ist genau der Fehlertyp dieser Werkbank.
        "unaged": unaged,
    }


def _facet_list(counts: dict, labels: dict | None = None,
                notes: dict | None = None) -> list[dict]:
    labels = labels or {}
    notes = notes or {}
    out = []
    for value, count in counts.items():
        row = {"value": value, "count": count, "label": labels.get(value, value)}
        if value in notes:
            row["note"] = notes[value]
        out.append(row)
    # Nach Anzahl, bei Gleichstand nach Beschriftung -- damit die Reihenfolge
    # zwischen zwei Aufrufen dieselbe ist und die Auswahlliste nicht springt.
    out.sort(key=lambda r: (-r["count"], r["label"]))
    return out


def _domain_labels(gov: dict) -> dict:
    """Anzeigenamen fuer Domaenen -- eindeutig gemacht, wo noetig.

    GEMESSEN am 07.08.: zwei verschiedene Domaenen heissen beide "Finance"
    (`urn:li:domain:probate_demo.finance` mit 146 Tabellen und
    `urn:li:domain:probate_seedlab.finance` mit 2). Zweimal "Finance" in
    einer Auswahlliste sieht aus wie ein Fehler und ist trotzdem die
    Wahrheit -- also wird der Namensraum dazugeschrieben, aber NUR wo ein
    Name doppelt vorkommt. Sonst traegt jede Zeile Ballast wegen zweier
    Ausnahmen.
    """
    names: dict[str, str] = {}
    for info in (gov.get("tables") or {}).values():
        urn = info.get("domain")
        if urn:
            names[urn] = info.get("domain_name") or urn
    seen: dict[str, int] = {}
    for name in names.values():
        seen[name] = seen.get(name, 0) + 1
    out = {}
    for urn, name in names.items():
        if seen.get(name, 0) > 1:
            # `urn:li:domain:probate_demo.finance` -> "probate_demo"
            ident = urn.rsplit(":", 1)[-1]
            out[urn] = f"{name} ({ident.split('.')[0]})" if "." in ident else f"{name} ({ident})"
        else:
            out[urn] = name
    return out


def facets(edges: list[dict], gov: dict | None = None,
           notes: dict | None = None) -> dict:
    """Die Auswahllisten der Filterzeile -- aus den Daten gezogen, nie
    hartkodiert (Spec).

    Jede Zahl ist die Anzahl der KANTEN, die man nach dem Anklicken sieht.
    Bis 07.08. zaehlte sie stattdessen die Vorkommen an Kanten-ENDEN: die
    Datenbank `probate_seedlab` stand mit "8" in der Liste und lieferte
    dann 4 Zeilen, weil beide Enden jeder ihrer 4 Kanten mitzaehlten. Eine
    Zahl, die nicht haelt, was sie ankuendigt, ist auf dieser Werkbank
    besonders teuer -- sie ist genau die Sorte Behauptung, gegen die das
    Produkt antritt.
    """
    gov = gov if gov is not None else load_governance()
    notes = notes if notes is not None else lab_notes()
    rows = [edge_row(e, gov) for e in edges]

    def tally(pick) -> dict:
        counts: dict[str, int] = {}
        for r in rows:
            for value in sorted(pick(r)):  # eine Kante zaehlt je Wert EINMAL
                counts[value] = counts.get(value, 0) + 1
        return counts

    platforms = tally(lambda r: {s["platform"] for s in (r["from"], r["to"]) if s["platform"]})
    databases = tally(lambda r: {s["database"] for s in (r["from"], r["to"]) if s["database"]})

    out = {
        "platforms": _facet_list(platforms),
        "databases": _facet_list(databases, notes={
            db: info["label"] for db, info in notes.items() if db in databases}),
        "database_notes": {db: info for db, info in notes.items() if db in databases},
    }

    # Domaene und Besitzer gibt es NUR gegen ein gemessenes Artefakt. Ohne
    # es bleiben die Listen leer und tragen den Grund -- die Oberflaeche
    # sperrt dann die Auswahl, statt "alle" anzuzeigen und so zu tun, als
    # gaebe es nichts zu filtern.
    out["governance"] = {
        "measured": bool(gov.get("measured")),
        "reason": gov.get("reason", ""),
        "generated_at_iso": gov.get("generated_at_iso", ""),
        "source": gov.get("source", ""),
        "tables_looked_up": gov.get("tables_looked_up", 0),
        "tables_with_domain": gov.get("tables_with_domain", 0),
        "tables_with_owner": gov.get("tables_with_owner", 0),
    }
    if not gov.get("measured"):
        out["domains"] = []
        out["owners"] = []
        return out

    def domains_of(r):
        vals = set()
        for s in (r["from"], r["to"]):
            if s["domain"]:
                vals.add(s["domain"])
            elif s["known"]:
                vals.add(NONE_VALUE)
        return vals

    def owners_of(r):
        vals = set()
        for s in (r["from"], r["to"]):
            if s["owners"]:
                vals.update(o["urn"] for o in s["owners"] if o.get("urn"))
            elif s["known"]:
                vals.add(NONE_VALUE)
        return vals

    owner_names = {}
    for info in (gov.get("tables") or {}).values():
        for o in info.get("owners") or []:
            if o.get("urn"):
                owner_names[o["urn"]] = o.get("name") or o["urn"]

    dom_labels = _domain_labels(gov)
    dom_labels[NONE_VALUE] = "— no domain assigned —"
    owner_names[NONE_VALUE] = "— no owner assigned —"

    out["domains"] = _facet_list(tally(domains_of), labels=dom_labels)
    out["owners"] = _facet_list(tally(owners_of), labels=owner_names)
    return out


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
