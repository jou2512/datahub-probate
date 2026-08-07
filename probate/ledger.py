"""Das Kanten-Register.

Warum diese Datei existiert: `targets.py` rechnet einen Dreier-Split ueber
zwei Mengen und kann deshalb strukturell nicht sagen, ob eine leere
Messung bedeutet "niemand hat es benutzt" oder "wir haben nicht
hingesehen". Beide Faelle ergaben bisher dieselbe leere Menge, und der
Fall "deklariert, nichts gemessen" galt als unbedenklich -- bei fehlender
Datenlage waere ein aktiver Konsument stillschweigend ueberfahren worden.

Dieses Modul urteilt deshalb pro KANTE, nicht pro Tabelle, und stellt der
Klassifikation eine Abdeckungs-Pruefung voran. Der vierte Zustand
`unknown` ist kein Sonderfall, sondern der Normalfall bei duenner
Datenlage -- und er darf NIE wie `dead` behandelt werden.

`targets.py` bleibt unveraendert; es traegt weiter die Stilllegung
(cli start/apply) und hat vier gruene Tests, die drei Tage vor der Frist
niemand anfassen muss.
"""

from __future__ import annotations

from dataclasses import dataclass

from probate.targets import _QUERY_SEARCH_Q as COOCCURRENCE_Q  # eine Wahrheit;
# targets.py bleibt unveraendert, der String wird nicht ein zweites Mal getippt.

STATES = ("confirmed", "dead", "missing", "unknown")


@dataclass(frozen=True)
class Edge:
    """Eine gerichtete Kante. Richtung ist Teil der Identitaet --
    A->B und B->A sind verschiedene Behauptungen."""

    upstream: str
    downstream: str

    def key(self) -> str:
        return f"{self.upstream}->{self.downstream}"


@dataclass(frozen=True)
class Bucket:
    """Ein Nutzungs-Zeitfenster, wie DataHub es liefert.

    Bewusst NICHT summiert: die Reihe der Buckets ist die Zeitachse
    (Schicht 1b), und ihre blosse EXISTENZ ist die Antwort auf
    "haben wir hingesehen?".
    """

    bucket_ms: int
    total_sql_queries: int
    unique_user_count: int


_DAY_MS = 86_400_000


@dataclass(frozen=True)
class Coverage:
    """Wie weit reicht unser Blick ueberhaupt?

    Diese Frage wird VOR jeder Klassifikation beantwortet. Ohne sie ist
    jede Aussage ueber eine Kante eine Behauptung ueber Daten, die es
    vielleicht gar nicht gibt.
    """

    buckets_seen: int
    oldest_bucket_ms: int | None
    newest_bucket_ms: int | None
    reason: str  # leer = abgedeckt; sonst warum nicht

    @property
    def has_window(self) -> bool:
        return self.buckets_seen > 0

    @property
    def days_span(self) -> int | None:
        if self.oldest_bucket_ms is None or self.newest_bucket_ms is None:
            return None
        return (self.newest_bucket_ms - self.oldest_bucket_ms) // _DAY_MS

    def to_json(self) -> dict:
        return {
            "buckets_seen": self.buckets_seen,
            "oldest_bucket_ms": self.oldest_bucket_ms,
            "newest_bucket_ms": self.newest_bucket_ms,
            "days_span": self.days_span,
            "reason": self.reason,
        }


def coverage_from_buckets(buckets: tuple[Bucket, ...]) -> Coverage:
    if not buckets:
        return Coverage(0, None, None, "keine Nutzungs-Zeitfenster im Katalog")
    ordered = sorted(buckets, key=lambda b: b.bucket_ms)
    return Coverage(len(ordered), ordered[0].bucket_ms, ordered[-1].bucket_ms, "")


@dataclass(frozen=True)
class Timeline:
    """Dieselben Buckets, nur nicht summiert.

    Der Unterschied zwischen einem Pruefwerkzeug und einem Nachweis:
    "diese Kante ist tot" ist eine Momentaufnahme, "diese Kante war bis
    zum 11. April gedeckt" ist eine Aussage, die man spaeter belegen kann.

    `buckets == ()` heisst NICHT "null Verkehr", sondern "wir haben nicht
    hingesehen". Wer das summiert, macht aus beidem dieselbe Null.
    """

    buckets: tuple[Bucket, ...]

    @property
    def _ordered(self) -> list[Bucket]:
        return sorted(self.buckets, key=lambda b: b.bucket_ms)

    @property
    def last_covered_ms(self) -> int | None:
        covered = [b.bucket_ms for b in self.buckets if b.total_sql_queries > 0]
        return max(covered) if covered else None

    def dead_since(self, now_ms: int) -> tuple[int | None, bool]:
        """(Tage, at_least). `at_least=True` heisst: vor dem aeltesten
        Bucket wissen wir nichts, die Zahl ist eine Untergrenze."""
        if not self.buckets:
            return None, False
        last = self.last_covered_ms
        if last is not None:
            return (now_ms - last) // _DAY_MS, False
        return (now_ms - self._ordered[0].bucket_ms) // _DAY_MS, True

    @property
    def series(self) -> tuple[tuple[int, int], ...]:
        return tuple((b.bucket_ms, b.total_sql_queries) for b in self._ordered)

    def to_json(self, now_ms: int) -> dict:
        days, at_least = self.dead_since(now_ms)
        return {
            "last_covered_ms": self.last_covered_ms,
            "dead_since_days": days,
            "dead_since_is_lower_bound": at_least,
            "series": [list(p) for p in self.series],
        }


_NOT_ASKED = Coverage(0, None, None, "nicht abgefragt")


@dataclass(frozen=True)
class EdgeVerdict:
    """Das Urteil ueber eine einzelne Kante, mitsamt seinem Beleg.

    `evidence` traegt immer, WORAUS der Zustand folgt -- nie nur das
    Wort selbst. Ein Zustand ohne Beleg waere genau die Behauptung,
    gegen die dieses Modul gebaut wurde.
    """

    edge: Edge
    state: str
    evidence: dict
    coverage: Coverage
    timeline: Timeline

    def to_json(self, now_ms: int) -> dict:
        return {
            "edge": self.edge.key(),
            "upstream": self.edge.upstream,
            "downstream": self.edge.downstream,
            "state": self.state,
            "evidence": self.evidence,
            "coverage": self.coverage.to_json(),
            "timeline": self.timeline.to_json(now_ms),
        }


def classify_edges(
    focus: str,
    declared: set[str],
    cooccurred: dict[str, list[str]],
    coverage_by_urn: dict[str, Coverage],
    timeline_by_urn: dict[str, Timeline],
    now_ms: int,
    queries_seen: int = 0,
) -> list[EdgeVerdict]:
    """Vier Zustaende, in dieser Reihenfolge geprueft.

    Die Abdeckung ist das GATE: ohne Zeitfenster wird gar nicht erst
    geprueft, ob gemessen wurde -- die Antwort waere bedeutungslos.
    Deshalb steht `has_window` VOR dem Blick in `cooccurred`, nicht
    danach. Ein fehlender Eintrag in `coverage_by_urn` ist "nicht
    abgefragt" und damit ebenfalls `unknown`; ein stilles Default auf
    "abgedeckt" waere genau der Fehlbefund, den dieses Modul verhindert.

    Fokus-Kanten werden nie erzeugt (`target == focus`): weder eine
    deklarierte Selbstreferenz noch eine Ko-Okkurrenz mit sich selbst
    ist eine sinnvolle Kante.

    `coverage_by_urn`/`timeline_by_urn` koennen sich widersprechen (eine
    Abdeckung meldet Fenster, die Zeitachse ist trotzdem leer) -- das ist
    ein Datenfehler, keine Grundlage fuer irgendein Urteil, und wird
    deshalb selbst zu `unknown`, bevor ein anderer Zweig greift.

    Query-Quellen-Gate (Entscheid `docs/entscheidungen/
    2026-08-07-query-quellen-gate.md`): das Abdeckungs-Gate belegt nur,
    dass wir die NUTZUNGS-Statistik angeschaut haben. `dead`/`confirmed`
    ruhen aber auf der QUERY-Ko-Okkurrenz, einer anderen Quelle. Fuer
    eine deklarierte Kante mit Fenstern und ohne Paar-Query gilt darum:
      1. Verkehr im Fenster == 0 -> `dead` bleibt lizenziert (ein Fenster
         mit Null heisst: es lief ueberhaupt nichts).
      2. Verkehr > 0 und `queries_seen == 0` -> `unknown` ("verkehr
         gemessen, aber query-quelle leer") -- wir koennen "keine
         Query-Ingestion" nicht von "Queries beruehren den Fokus nicht"
         unterscheiden.
      3. Verkehr > 0 und `queries_seen > 0` -> `dead` (starker Beleg: die
         Query-Quelle wurde befragt und kennt die Kante nicht).
    `confirmed` (Paar-Query existiert) ist von `queries_seen` unberuehrt.

    Eine leere `cooccurred[target]`-Liste ist keine Messung -- eine
    `missing`-Kante ohne Query-URN waere das Spiegelbild des
    urspruenglichen Fehlers: eine erfundene Kante statt eines
    verschwiegenen Zustands.
    """
    out: list[EdgeVerdict] = []

    for target in sorted(declared):
        if target == focus:
            continue

        cov = coverage_by_urn.get(target, _NOT_ASKED)
        tl = timeline_by_urn.get(target, Timeline(()))
        edge = Edge(focus, target)

        if not cov.has_window:
            out.append(EdgeVerdict(
                edge, "unknown",
                {"reason": cov.reason, "source": "declared lineage"},
                cov, tl))
            continue

        if not tl.buckets:
            out.append(EdgeVerdict(
                edge, "unknown",
                {"reason": "abdeckung und zeitachse widersprechen sich",
                 "source": "declared lineage"},
                cov, tl))
            continue

        queries = cooccurred.get(target, [])
        if queries:
            out.append(EdgeVerdict(
                edge, "confirmed",
                {"query_urns": list(queries),
                 "source": "declared lineage + query co-occurrence"},
                cov, tl))
            continue

        traffic = sum(b.total_sql_queries for b in tl.buckets)
        if traffic == 0:
            out.append(EdgeVerdict(
                edge, "dead",
                {"reason": "im geprueften Fenster nie gemessen",
                 "buckets_checked": cov.buckets_seen,
                 "source": "declared lineage"},
                cov, tl))
        elif queries_seen == 0:
            out.append(EdgeVerdict(
                edge, "unknown",
                {"reason": "verkehr gemessen, aber query-quelle leer — kante nicht pruefbar",
                 "traffic_in_window": traffic,
                 "queries_seen": queries_seen,
                 "source": "declared lineage"},
                cov, tl))
        else:
            out.append(EdgeVerdict(
                edge, "dead",
                {"reason": "query-quelle befragt, keine paar-abfrage fuer diese kante gefunden",
                 "traffic_in_window": traffic,
                 "queries_seen": queries_seen,
                 "buckets_checked": cov.buckets_seen,
                 "source": "declared lineage + query co-occurrence"},
                cov, tl))

    for target in sorted(set(cooccurred) - declared):
        if target == focus:
            continue

        queries = cooccurred[target]
        if not queries:
            continue

        out.append(EdgeVerdict(
            Edge(focus, target), "missing",
            {"query_urns": list(queries),
             "cooccurrence_count": len(queries),
             "direction_evidence": "co-occurrence (undirected)",
             "source": "query co-occurrence"},
            coverage_by_urn.get(target, _NOT_ASKED),
            timeline_by_urn.get(target, Timeline(()))))

    return out


# --- Beschaffung ---------------------------------------------------------
#
# Gemessenes Rezept (UEBERGABE Sec.4/5, live gegen v1.5.0.6 verifiziert):
# usageStats(range: MONTH) liefert Buckets UND Aggregat. Wir nehmen die
# Buckets -- das Aggregat waere genau die Summierung, die "nichts gemessen"
# und "nichts passiert" ununterscheidbar macht. Falle 13 (`range: ALL` mit
# gesetztem `startTimeMillis` liefert falsche/null Aggregationen) betrifft
# diese Abfrage nicht direkt (kein `startTimeMillis`, `range: MONTH`), aber
# aus demselben Grund wird hier bewusst KEIN `startTimeMillis` gesetzt.
USAGE_Q = """
query($urn: String!) {
  dataset(urn: $urn) {
    usageStats(range: MONTH) {
      buckets { bucket metrics { totalSqlQueries uniqueUserCount } }
      aggregations { totalSqlQueries uniqueUserCount }
    }
    statsSummary { queryCountLast30Days uniqueUserCountLast30Days }
  }
}
"""

# Wie targets._LINEAGE_Q, aber mit `count` als Variable: Falle 12 --
# get_lineage liefert nachweislich >100'000 Zeichen ohne Pagination-Vorgabe.
LINEAGE_Q = """
query($urn: String!, $count: Int!) {
  dataset(urn: $urn) {
    lineage(input: {direction: DOWNSTREAM, start: 0, count: $count}) {
      relationships { entity { urn } }
    }
  }
}
"""


def fetch_usage(gms, urn: str) -> tuple[Bucket, ...]:
    """Rohe Zeitfenster, nicht summiert.

    Ein Bucket mit `totalSqlQueries: null` ist ein Bucket mit null
    Verkehr, kein fehlender Bucket -- er belegt, dass hingesehen wurde.
    Wer ihn wegfiltert, macht aus `dead` ein `unknown`.

    Kein `range_`-Parameter mehr (Review Fix-Runde 1, IMPORTANT 4): `USAGE_Q`
    hat `range: MONTH` fest im Query-String stehen, ein frueherer
    `range_="ALL"`-Parameter wurde nie eingesetzt und haette still
    MONTH-Daten geliefert -- eine Falle-4-Klasse (erfundene/wirkungslose
    Felder werden verworfen, nicht abgelehnt). Wer einen anderen Bereich
    braucht, baut eine eigene Abfrage statt eines stummen Parameters.
    """
    data = gms.graphql(USAGE_Q, {"urn": urn})
    stats = (data.get("dataset") or {}).get("usageStats") or {}
    out = []
    for b in stats.get("buckets") or []:
        m = b.get("metrics") or {}
        out.append(Bucket(
            bucket_ms=int(b.get("bucket") or 0),
            total_sql_queries=int(m.get("totalSqlQueries") or 0),
            unique_user_count=int(m.get("uniqueUserCount") or 0),
        ))
    return tuple(out)


def fetch_declared_edges(gms, urn: str, count: int = 200) -> set[str]:
    data = gms.graphql(LINEAGE_Q, {"urn": urn, "count": count})
    rels = ((data.get("dataset") or {}).get("lineage") or {}).get("relationships") or []
    return {r["entity"]["urn"] for r in rels if r.get("entity")}


def fetch_cooccurrence(gms, urn: str) -> tuple[dict[str, list[str]], int]:
    """Ko-Okkurrenz MIT Beleg: Ziel-URN -> Liste der Query-URNs, plus die
    ECHTE Gesamtzahl der Query-Treffer fuer diesen Fokus.

    `targets.fetch_measured` liefert dieselbe Information als blosse
    Menge und wirft die Query-URN weg. Genau die ist aber der Beleg, den
    jede `confirmed`- und jede `missing`-Kante mitfuehren muss.

    Richtung: QuerySubject nennt nur `entity`, kein Richtungsfeld. Die
    Ko-Okkurrenz ist damit UNGERICHTET -- das steht im Beleg jeder
    missing-Kante und darf beim Schreiben (correct.py) nicht als
    gemessene Richtung ausgegeben werden.

    Rueckgabe `(dict, total)` (Review Fix-Runde 1, IMPORTANT 2): `total`
    ist das `total`-Feld der Suchantwort, NICHT `len(searchResults)`.
    `COOCCURRENCE_Q` (`_QUERY_SEARCH_Q` aus targets.py) begrenzt auf
    `count: 200` -- bei mehr Treffern waere ein `len()` der zurueck-
    gegebenen Seite eine Unterzaehlung. `total` ist die einzige Zahl, die
    `classify_edges` als `queries_seen` gefahrlos verwenden darf; ein
    Aufrufer, der bisher `len(searchResults)` selbst nachgezaehlt hat
    (siehe Task-5-Report, Concern 2), muss diesen zweiten Aufruf jetzt
    nicht mehr machen.

    Zeitstempel-Messschritt (Step 1, 07.08., `harness/runs/
    query-timestamp-probe.json`): eine Query-Entitaet TRAEGT einen
    verwertbaren Zeitstempel -- `queryproperties.value.created.time`
    (Epoch-ms, z.B. 1754300000000), live an drei gesuchten Query-URNs
    geprueft, zwei mit Wert, eine (Ingestion-generiert, kein manueller
    Eintrag) mit `queryproperties: null`. "Nicht geprueft" und "gibt es
    nicht" waeren hier verschiedene Aussagen gewesen -- es ist das erste:
    ein Teil der Query-Entitaeten traegt keine `queryproperties` und
    liefert dann keinen Zeitstempel. Fuer DIESE Runde bleibt die
    Zeitachse trotzdem an den Dataset-Buckets (`fetch_usage`), weil dort
    die gemessene, luecken-freiere Grundlage liegt; eine spaetere
    Detail-Ebene kann `created.time` pro Paar-Query zusaetzlich zeigen.
    """
    hits = gms.graphql(COOCCURRENCE_Q, {"urn": urn})
    search = hits.get("searchAcrossEntities") or {}
    total = int(search.get("total") or 0)
    query_urns = [
        r["entity"]["urn"]
        for r in search.get("searchResults", [])
        if r.get("entity")
    ]
    out: dict[str, list[str]] = {}
    for q_urn in query_urns:
        aspect = gms.get_aspect("query", q_urn, "querysubjects")
        if not aspect:
            continue
        for s in (aspect.get("value") or {}).get("subjects", []):
            other = s.get("entity")
            if other and other != urn:
                out.setdefault(other, []).append(q_urn)
    return out, total


def usage_evidence(gms, urn: str) -> tuple[Coverage, Timeline]:
    """Coverage UND Timeline aus genau EINEM `fetch_usage`-Aufruf.

    Review Fix-Runde 1, IMPORTANT 3: bislang war "aus denselben Bucket-
    Daten bauen" reine Aufrufer-Konvention (Task-4-Review-Obligation 2),
    nicht strukturell erzwungen -- ein Aufrufer haette `fetch_usage`
    versehentlich zweimal aufrufen koennen (einmal fuer Coverage, einmal
    fuer Timeline), und bei zwei Netzwerk-Antworten aus unterschiedlichen
    Momenten waere genau der Divergenz-Zweig in `classify_edges`
    ("Abdeckung und Zeitachse widersprechen sich" -> unknown) durch eine
    Race entstanden, nicht durch eine echte Dateninkonsistenz. Diese
    Funktion macht den Einzel-Fetch zur einzigen Schnittstelle.
    """
    buckets = fetch_usage(gms, urn)
    return coverage_from_buckets(buckets), Timeline(buckets)


# --- Task 6: run() + Lauf-Artefakt --------------------------------------

COVERAGE_THIN_BELOW_BUCKETS = 7


class _Counting:
    """Zaehlt die API-Aufrufe, ohne gms.py anzufassen.

    Der Lasttest braucht die Zahl, und sie gehoert ins Lauf-Artefakt --
    eine Behauptung ueber Aufrufzahlen ohne Zaehler waere geschaetzt.
    """

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def graphql(self, query, variables=None):
        self.calls += 1
        return self.inner.graphql(query, variables)

    def get_aspect(self, entity_type, urn, aspect):
        self.calls += 1
        return self.inner.get_aspect(entity_type, urn, aspect)


def run(gms, focus: str, now_ms: int, lineage_count: int = 200) -> dict:
    """Ein vollstaendiger Abgleich fuer ein Fokus-Dataset.

    Reihenfolge ist Absicht: erst beide Quellen holen, dann fuer JEDES
    beteiligte Ziel die Abdeckung bestimmen (per `usage_evidence`, EIN
    Fetch), DANN klassifizieren. Wer waehrend der Klassifikation
    nachlaedt, klassifiziert Kanten mit unterschiedlich alter Datenlage.

    Abweichung vom urspruenglichen Brief-Entwurf (aktueller Code gewinnt,
    s. Task-Auftrag): `fetch_cooccurrence` liefert seit Fix-Runde 1 ein
    Tupel `(map, total)`, kein blosses Mapping mehr. Der Brief-Entwurf
    reichte das Tupel unentpackt an `set(cooccurred)` durch -- das waere
    sofort mit `TypeError: unhashable type: 'dict'` gescheitert, noch vor
    jeder Netzwerk-Antwort. Hier wird entpackt, und `total` wird als
    `queries_seen` an `classify_edges` durchgereicht (Query-Quellen-Gate).

    Ein fehlgeschlagener Fetch wirft `GmsError` und laesst diese Funktion
    OHNE Rueckgabewert enden -- der Aufrufer (CLI) schreibt dann kein
    Artefakt. Eine Teil-Klassifikation, die Vollstaendigkeit behauptet,
    waere genau die Behauptung ohne Beleg, gegen die dieses Projekt
    antritt.
    """
    counting = _Counting(gms)
    declared = fetch_declared_edges(counting, focus, count=lineage_count)
    cooccurred, queries_seen = fetch_cooccurrence(counting, focus)

    coverage_by_urn: dict[str, Coverage] = {}
    timeline_by_urn: dict[str, Timeline] = {}
    for target in sorted(declared | set(cooccurred)):
        cov, tl = usage_evidence(counting, target)
        coverage_by_urn[target] = cov
        timeline_by_urn[target] = tl

    verdicts = classify_edges(
        focus, declared, cooccurred, coverage_by_urn, timeline_by_urn, now_ms,
        queries_seen=queries_seen,
    )
    counts = {s: sum(1 for v in verdicts if v.state == s) for s in STATES}
    buckets_seen = sum(c.buckets_seen for c in coverage_by_urn.values())
    spans = [c.days_span for c in coverage_by_urn.values() if c.days_span is not None]

    return {
        "focus": focus,
        "gms": getattr(gms, "base", ""),
        "seeded": True,  # der Beispielkatalog liefert keine echte Warehouse-Nutzung
        "generated_at_ms": now_ms,
        "edges_total": len(verdicts),
        "edges_confirmed": counts["confirmed"],
        "edges_dead": counts["dead"],
        "edges_missing": counts["missing"],
        "edges_unknown": counts["unknown"],
        "coverage_buckets_seen": buckets_seen,
        "coverage_days_span": max(spans) if spans else 0,
        "coverage_thin": buckets_seen < COVERAGE_THIN_BELOW_BUCKETS,
        "api_calls": counting.calls,
        "queries_seen": queries_seen,
        "edges": [v.to_json(now_ms) for v in verdicts],
    }
