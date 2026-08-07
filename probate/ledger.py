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

import json
import time as _time
from dataclasses import dataclass

from probate.gms import GmsError, _validate_urn  # der einzige VALIDIERTE Weg
# nach draussen (probate/gms.py Docstring) -- ausserhalb des erlaubten
# Datei-Umfangs dieser Aufgabe, deshalb hier importiert statt dort ergaenzt.
# `_send`/`.base` werden unten direkt benutzt (wie `harness/seed_lineage_lab.py
# ::_raw_usage_values` es vormacht), weil `probate/gms.py` weder die Route
# "rohe Zeitreihen-Werte lesen" noch eine oeffentliche Methode dafuer anbietet.
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
    # Coordinator-Review 07.08. (IMPORTANT 2): "im geprueften Fenster nie
    # gemessen" ist eine Aussage UEBER ein Fenster, das vorher nirgends
    # stand -- weder im Artefakt noch in der Evidenz. `window_start_ms`/
    # `window_end_ms` sind die tatsaechlichen Grenzen, mit denen
    # `fetch_usage` GEFRAGT hat (siehe `usage_evidence`/`fetch_usage`
    # unten) -- `None`, wenn dieses Coverage-Objekt nicht aus einem echten
    # Fetch stammt (z.B. `_NOT_ASKED`: gar nicht abgefragt, kein Fenster
    # zu nennen).
    window_start_ms: int | None = None
    window_end_ms: int | None = None

    @property
    def has_window(self) -> bool:
        return self.buckets_seen > 0

    @property
    def days_span(self) -> int | None:
        if self.oldest_bucket_ms is None or self.newest_bucket_ms is None:
            return None
        return (self.newest_bucket_ms - self.oldest_bucket_ms) // _DAY_MS

    @property
    def window_days(self) -> int | None:
        """Die GROESSE des GEFRAGTEN Fensters -- nicht zu verwechseln mit
        `days_span` (der Spanne der TATSAECHLICH gefundenen Buckets, die
        bei duenner Datenlage viel kleiner als das Fenster sein kann)."""
        if self.window_start_ms is None or self.window_end_ms is None:
            return None
        return (self.window_end_ms - self.window_start_ms) // _DAY_MS

    def to_json(self) -> dict:
        return {
            "buckets_seen": self.buckets_seen,
            "oldest_bucket_ms": self.oldest_bucket_ms,
            "newest_bucket_ms": self.newest_bucket_ms,
            "days_span": self.days_span,
            "reason": self.reason,
            "window_start_ms": self.window_start_ms,
            "window_end_ms": self.window_end_ms,
            "window_days": self.window_days,
        }


def coverage_from_buckets(
    buckets: tuple[Bucket, ...],
    window_start_ms: int | None = None,
    window_end_ms: int | None = None,
) -> Coverage:
    """`window_start_ms`/`window_end_ms` sind optional (Vorgabe `None`) --
    bestehende Aufrufer (Tests, `classify_edges`-Fixtures), die kein
    Fenster kennen, bleiben unveraendert lauffaehig. `usage_evidence`
    unten ist der einzige Aufrufer, der ein echtes Fenster hat und es
    hier durchreicht."""
    if not buckets:
        return Coverage(0, None, None, "keine Nutzungs-Zeitfenster im Katalog",
                         window_start_ms, window_end_ms)
    ordered = sorted(buckets, key=lambda b: b.bucket_ms)
    return Coverage(len(ordered), ordered[0].bucket_ms, ordered[-1].bucket_ms, "",
                     window_start_ms, window_end_ms)


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
                # Coordinator-Review 07.08. (IMPORTANT 2): "im geprueften
                # Fenster nie gemessen" nannte bis dahin nirgends, WELCHES
                # Fenster gemeint ist -- die eine Praemisse, die dead von
                # unknown trennt, stand nicht im Beleg. `window_*` kommt
                # direkt aus `cov` (derselben Coverage, die `fetch_usage`
                # tatsaechlich abgefragt hat), nicht neu berechnet.
                {"reason": "im geprueften Fenster nie gemessen",
                 "buckets_checked": cov.buckets_seen,
                 "window_days": cov.window_days,
                 "window_start_ms": cov.window_start_ms,
                 "window_end_ms": cov.window_end_ms,
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
                 "window_days": cov.window_days,
                 "window_start_ms": cov.window_start_ms,
                 "window_end_ms": cov.window_end_ms,
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
# Ledger-Fix (07.08., ersetzt die fruehere `usageStats(range: MONTH)`-
# GraphQL-Aggregation): DIESE Aggregation ist ElasticSearch-gestuetzt und
# hinkt nach. GEMESSEN, nicht theoretisiert: die UI-Spur mass live >100s
# Verzug NACH einem Purge der Nutzungs-Zeitreihe (Rohablage zu diesem
# Zeitpunkt bereits 0 Zeilen), eine fruehere Spur mass >75s auf derselben
# API (UEBERGABE.md Falle 19, `harness/seed_lineage_lab.py::seed_usage`
# Kommentar: D/E/F blieben nach ueber 75s/15x Polling `null`, obwohl die
# Rohablage beim allerersten Versuch bereits korrekt war). Fuer den
# "Warehouse trennen"-Knopf -- die dritte, demo-tragende Transition der
# 40-Sekunden-Sequenz, MUSS live auf Kamera sichtbar werden -- ist eine
# Minute Verzug ein Blocker: der Schreibvorgang ist korrekt, die
# Klassifikation liest nur eine veraltete Sicht. Ein Werkzeug, dessen
# These "wir behaupten nur, was wir gemessen haben" ist, darf ohnehin nicht
# aus einer Ansicht urteilen, die eine Minute hinter der Primaerablage liegt.
#
# Deshalb liest `fetch_usage` jetzt die ROHE Zeitreihen-Ablage direkt
# (`POST {gms.base}/aspects?action=getTimeseriesAspectValues`) statt der
# Aggregation -- exakt die Route, die `harness/seed_lineage_lab.py::
# _raw_usage_values` bereits fuer die Seed-Verifikation nutzt (dort zuerst
# geloest: Rueckluse nach Purge+Rewrite gegen die Aggregation war live
# unzuverlaessig, gegen die Rohablage sofort korrekt).
#
# KORREKTUR 07.08.2026, 12:20 -- die urspruengliche Begruendung hier war
# falsch. Sie lautete, `get_aspect` liefere fuer Zeitreihen-Aspekte "IMMER
# None" und sei fuer diesen Aspekttyp blind (Falle 18, UEBERGABE.md). Die
# Gegenprobe widerlegt das: `get_aspect('dataset', <urn>,
# 'datasetUsageStatistics')` gab an `probate_writetest.t4` den Aspekt samt
# `totalSqlQueries` zurueck (geschrieben 123, gelesen 123).
#
# Der Griff zur Rohablage bleibt trotzdem richtig, aber aus dem anderen,
# tatsaechlich gemessenen Grund: `get_aspect` liefert nur den JUENGSTEN Wert,
# waehrend die Klassifikation ALLE Buckets im Fenster braucht -- und die
# Aggregation hinkt (Falle 19, >75 s beobachtet). Rohablage ist die einzige
# Route, die vollstaendig und ohne Verzug antwortet.
#
# `probate/gms.py` bleibt unveraendert (ausserhalb des Datei-Umfangs dieser
# Aufgabe) und bietet weder diese Route noch rohe Zeitreihen-Werte als
# oeffentliche Methode -- `gms._send`/`gms.base` werden deshalb wie in
# `seed_lineage_lab.py` direkt benutzt, und `_validate_urn` (Finding C4,
# Pfad-Traversal-Allowlist aus gms.py) wird VOR der Interpolation explizit
# wiederholt, damit die Umgehung der oeffentlichen, gehaerteten Methoden
# nicht lautlos passiert.
#
# Fenster (bewusst NICHT die volle Historie): `classify_edges` urteilt
# "im gepruften Fenster nie gemessen" -> `dead`. Eine Kante mit Verkehr vor
# >100 Tagen und seither nur Null-Buckets soll `dead` bleiben, nicht durch
# pure Alt-Summierung wieder wie "Verkehr gemessen" aussehen. Live vermessen
# (07.08., seedlab-Kante `store_revenue_weekly_east`, acht Buckets, davon
# zwei mit echtem Verkehr vor 117/124 Tagen): ein ungefiltertes
# `startTimeMillis=0` auf der Rohablage liefert ALLE acht Buckets, Summe 52
# -- das haette diese `dead`-Kante der Vier-Zustaende-Probe zu `unknown`
# kollabieren lassen (kein Datenfehler, ein Fenster-Fehler dieser Funktion).
# Die vorherige `usageStats(range: MONTH)` lieferte dagegen live exakt 31
# Tages-Buckets (heute minus 30 Tage 00:00 UTC bis heute 00:00 UTC), alle
# mit `totalSqlQueries: 0` fuer dieselbe Kante -- diese Fenster-Semantik
# reproduziert `USAGE_WINDOW_DAYS` unten: ein straffes 30-Tage-Fenster ab
# dem exakten Wall-Clock-`jetzt` (ohne Tages-Rundung wie GraphQL sie intern
# macht) haette den aeltesten Tages-Bucket je nach Tageszeit des Laufs knapp
# abgeschnitten (live geprueft: 30 Tage exakt -> 3 Treffer, 31 Tage -> 4
# Treffer fuer dieselbe Kante) -- deshalb 32 Tage (30 + 2 Tage Puffer gegen
# genau diesen Tageszeit-Rand), weit unterhalb der 117/124-Tage-Marke, die
# NICHT wieder hereinkommen darf.
_DAY_MS_USAGE = _DAY_MS  # dieselbe Konstante, hier nur lokal referenziert
USAGE_WINDOW_DAYS = 32
# Coordinator-Review 07.08. (IMPORTANT 3): 500 war gegen TAEGLICHE
# Granularitaet kalibriert (<=34 moegliche Buckets im 32-Tage-Fenster) --
# aber `eventGranularity` in der Rohablage ist HOUR genauso gueltig wie
# DAY (live gesehen: `{"unit":"DAY","multiple":1}`, aber die Aspekt-
# Definition erlaubt andere Werte). Bei stuendlicher Granularitaet sind es
# 32 * 24 = 768 moegliche Buckets -- ueber dem alten Limit, also haette
# `fetch_usage` fuer ein einzelnes Dataset mit dieser (legitimen)
# Ingestion-Einstellung `GmsError` geworfen und DEN GANZEN LAUF ohne
# Artefakt beendet (`run()` propagiert, siehe Docstring dort). 2000 liegt
# weit ueber 768 (bliebe auch bei 15-Minuten-Granularitaet unter dem
# Limit: 32*96=3072 waere die einzige Granularitaet, die es noch reisst --
# unwahrscheinlich fuer `datasetUsageStatistics`, aber falls doch: derselbe
# sichtbare `GmsError` statt eines stillen Rundschnitts, siehe unten).
USAGE_TIMESERIES_LIMIT = 2000

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


def _usage_window_ms(now_ms: int) -> tuple[int, int]:
    """Reine Fenster-Berechnung, getrennt von der Netzwerk-Schicht -- damit
    `fetch_usage` (Payload) UND `usage_evidence` (Evidenz-Beleg, Coordinator-
    Review IMPORTANT 2) exakt dieselben Grenzen aus derselben Quelle lesen,
    statt sie an zwei Stellen unabhaengig zu berechnen und minimal
    auseinanderlaufen zu lassen."""
    return now_ms - USAGE_WINDOW_DAYS * _DAY_MS_USAGE, now_ms + _DAY_MS_USAGE


def fetch_usage(gms, urn: str, now_ms: int | None = None) -> tuple[Bucket, ...]:
    """Rohe Zeitfenster aus der PRIMAERABLAGE, nicht summiert -- und NICHT
    aus der `usageStats`-GraphQL-Aggregation. Siehe der lange Kommentar
    ueber `USAGE_WINDOW_DAYS` oben fuer das WARUM (gemessene Verzugszahlen,
    >100s/>75s) und das Fenster-Argument (warum nicht die volle Historie).

    Route: `POST {gms.base}/aspects?action=getTimeseriesAspectValues` mit
    `limit` (Falle 14, UEBERGABE.md: Pflichtfeld, sonst HTTP 500
    `NullPointerException: "limit" is null`). Fenster: die letzten
    `USAGE_WINDOW_DAYS` Tage.

    `now_ms` (optional, Vorgabe `None` -> tatsaechliches Wall-Clock-`jetzt`
    dieses Aufrufs): Signatur/Vertrag bleiben fuer bestehende Aufrufer
    unveraendert (zwei Positionsargumente reichen weiterhin), aber
    `usage_evidence`/`run()` reichen jetzt EIN gemeinsames `now_ms` durch,
    damit alle Ziele eines Laufs dasselbe Fenster sehen UND das Fenster
    fuer die Evidenz (Coordinator-Review IMPORTANT 2) exakt dem entspricht,
    das tatsaechlich an GMS geschickt wurde -- keine zweite, leicht
    versetzte Wall-Clock-Messung.

    Limit/Pagination: `USAGE_TIMESERIES_LIMIT` (2000, siehe Kommentar dort
    -- deckt auch stuendliche Granularitaet ab, 500 hatte das nicht).
    Kommen trotzdem `>= USAGE_TIMESERIES_LIMIT` Werte zurueck, ist das ein
    Signal fuer mehr Historie/Granularitaet als erwartet -- diese Funktion
    wirft dann `GmsError` statt die Liste still auf das Limit abzuschneiden.
    Ein stilles Abschneiden waere ein falsches `dead`/`unknown` durch
    Trunkierung, exakt dieselbe Fehlerklasse wie ein zu enges Fenster, nur
    unauffaelliger.

    `eventGranularity` (Coordinator-Review IMPORTANT 3, zweiter Teil): jede
    zurueckgelieferte Zeile traegt dieses Feld (live gesehen:
    `{"unit":"DAY","multiple":1}`), aber diese Funktion liest es NICHT und
    dedupliziert NICHT ueber unterschiedliche Granularitaeten. Wuerde ein
    Producer fuer denselben Zeitraum SOWOHL eine DAY- ALS AUCH mehrere
    HOUR-Zeilen schreiben (unueblich, aber vom Schema nicht verboten), sind
    das in der Rohablage zwei Zeilen fuer denselben zugrunde liegenden
    Verkehr -- `classify_edges`s `traffic = sum(b.total_sql_queries for b
    in tl.buckets)` wuerde dann doppelt zaehlen, und `coverage_buckets_seen`
    waere ueberzaehlt. NICHT geloest hier, bewusst dokumentiert statt still
    ignoriert (dieselbe Disziplin wie beim Fenster-Limit oben): der
    Katalog dieses Projekts (seedlab, live gegen 28080) schreibt
    ausschliesslich DAY-Granularitaet, gemischte Granularitaet ist unbelegt
    und ausserhalb des Umfangs dieses Fixes. Ein Aufrufer mit bekannter
    gemischter Granularitaet muesste `parsed.get("eventGranularity")`
    selbst auswerten (das Feld steht im rohen Aspekt-JSON, geht hier nur
    nicht in `Bucket` ein).

    Ein Bucket mit `totalSqlQueries: null` ist ein Bucket mit null Verkehr,
    kein fehlender Bucket -- er belegt, dass hingesehen wurde. Wer ihn
    wegfiltert, macht aus `dead` ein `unknown`. (Bislang nur an der
    Aggregation beobachtet; die Rohablage schrieb in jedem bisherigen Test
    stets konkrete Zahlen -- der Null-Schutz bleibt trotzdem, dieselbe
    defensive Regel wie zuvor, `int(x or 0)`.)

    Ein Fehlschlag (HTTP != 200, keine JSON-Antwort) wirft `GmsError` und
    propagiert -- keine Abwesenheit von Daten wird durch einen stillen
    Fehlschlag vorgetaeuscht (verification.md: "eine gescheiterte Abfrage
    ist keine Abwesenheit").
    """
    _validate_urn(urn)
    if now_ms is None:
        now_ms = int(_time.time() * 1000)
    start_ms, end_ms = _usage_window_ms(now_ms)
    payload = {
        "urn": urn,
        "entity": "dataset",
        "aspect": "datasetUsageStatistics",
        "startTimeMillis": start_ms,
        "endTimeMillis": end_ms,
        "limit": USAGE_TIMESERIES_LIMIT,
    }
    status, body = gms._send(
        "POST", f"{gms.base}/aspects?action=getTimeseriesAspectValues", payload)
    if status != 200 or not isinstance(body, dict):
        raise GmsError(f"getTimeseriesAspectValues HTTP {status}: {str(body)[:200]}")

    values = ((body.get("value") or {}).get("values")) or []
    if len(values) >= USAGE_TIMESERIES_LIMIT:
        raise GmsError(
            f"getTimeseriesAspectValues fuer {urn}: {len(values)} Werte >= "
            f"Limit {USAGE_TIMESERIES_LIMIT} -- moegliche Trunkierung, wird "
            "nicht stillschweigend als vollstaendig behandelt."
        )

    out = []
    for v in values:
        raw = (v.get("aspect") or {}).get("value")
        parsed = json.loads(raw) if isinstance(raw, str) else (raw or {})
        out.append(Bucket(
            bucket_ms=int(parsed.get("timestampMillis") or 0),
            total_sql_queries=int(parsed.get("totalSqlQueries") or 0),
            unique_user_count=int(parsed.get("uniqueUserCount") or 0),
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


def usage_evidence(gms, urn: str, now_ms: int | None = None) -> tuple[Coverage, Timeline]:
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

    `now_ms` (optional, Vorgabe `None` -> Wall-Clock-`jetzt`): wird EINMAL
    hier bestimmt, an `fetch_usage` durchgereicht (dasselbe `now_ms`, nicht
    zwei unabhaengige Zeitmessungen) und liefert die Fenstergrenzen fuer
    `coverage_from_buckets` -- Coordinator-Review IMPORTANT 2: die Coverage
    (und damit jede `dead`-Evidenz, die `cov.window_*` liest) traegt jetzt
    exakt das Fenster, mit dem tatsaechlich gefragt wurde, nicht irgendein
    spaeter neu berechnetes."""
    if now_ms is None:
        now_ms = int(_time.time() * 1000)
    start_ms, end_ms = _usage_window_ms(now_ms)
    buckets = fetch_usage(gms, urn, now_ms=now_ms)
    return coverage_from_buckets(buckets, window_start_ms=start_ms, window_end_ms=end_ms), Timeline(buckets)


# --- Task 6: run() + Lauf-Artefakt --------------------------------------

# Coordinator-Review 07.08. (IMPORTANT 1): 7 war gegen die AGGREGATION
# kalibriert. `usageStats(range: MONTH)` zeigt fast immer nahe an 31
# Buckets, weil sie den Kalender-Zeitraum zwischen dem AELTESTEN und dem
# NEUESTEN echten Datenpunkt luecken-frei mit Null-Werten auffuellt -- ein
# Dataset mit nur EINEM echten Schreibvorgang vor einer Woche zeigte
# trotzdem ~7 Buckets (der interpolierte Kalender-Zwischenraum), nicht 1.
# "< 7" bedeutete darum praktisch "die beobachtete Kalender-Spanne ist
# kuerzer als eine Woche", nicht "wenige echte Messungen".
#
# Die Rohablage interpoliert NICHT: `buckets_seen` ist jetzt die Anzahl
# ECHT GESCHRIEBENER Zeilen im Fenster. Live gemessen (seedlab, nach dem
# Ledger-Fix): `dead`-Fokus 31 -> 4 (acht geschriebene Zeilen, vier davon
# im 32-Tage-Fenster), `confirmed`/`missing` je 3. Bei unveraendertem
# Schwellwert 7 waeren damit ALLE VIER Demo-Kanten "duenn" -- inklusive der
# beiden, die ihre volle geplante Nutzungshistorie zeigen. Das ist keine
# duennere Datenlage als vorher, nur eine ehrlichere Zaehlung (die
# Aggregation hat den Judge/Reviewer bisher ueber die tatsaechliche Dichte
# getaeuscht, nicht umgekehrt).
#
# Neuer Schwellwert 3: unter drei ECHTEN Messfenstern ist ein Verdikt kaum
# vertrauenswuerdig zu stuetzen (ein oder zwei Datenpunkte koennten eine
# Ingestion-Luecke sein, kein beobachteter Zustand) -- drei unabhaengige
# Fenster sind das Minimum fuer einen Trend statt eines Einzelwerts. Kein
# Versuch, den alten Schwellwert proportional umzurechnen (die neue
# Groessenordnung -- Schreibereignisse statt Kalendertage -- ist nicht
# linear zur alten uebertragbar); [hier haette Joel vielleicht anders
# gewollt] ist die ehrliche Einordnung dieser Zahl.
#
# Re-Review 07.08. (Nachtrag, bindend fuer jeden spaeteren Leser dieser
# Zeile): 3 ist ein ERMESSENSENTSCHEID, KEIN GEMESSENER WERT. Kalibriert
# an genau EINEM Katalog (seedlab, ein einziger Lauf) -- und liegt dort
# exakt auf der Kippkante: `confirmed`/`missing` zeigen je GENAU 3
# Buckets, also GENAU an der Schwelle "noch nicht duenn". Eine andere
# Datenlage (mehr oder weniger geplante Seed-Buckets) haette denselben
# Schwellwert anders ausschlagen lassen. NIEMAND soll diese 3 spaeter als
# empirisch hergeleitet zitieren -- es ist die plausibelste kleine
# Ganzzahl fuer "ein Trend statt ein Einzelwert", nicht das Ergebnis einer
# Messreihe ueber mehrere Kataloge.
COVERAGE_THIN_BELOW_BUCKETS = 3


class _Counting:
    """Zaehlt die API-Aufrufe, ohne gms.py anzufassen.

    Der Lasttest braucht die Zahl, und sie gehoert ins Lauf-Artefakt --
    eine Behauptung ueber Aufrufzahlen ohne Zaehler waere geschaetzt.
    """

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    @property
    def base(self):
        # `fetch_usage` braucht `gms.base` fuer die Rohablage-URL und
        # bekommt hier die `_Counting`-Huelle statt des echten `Gms`-
        # Objekts durchgereicht (`run()` uebergibt `counting`, nicht
        # `gms`) -- ohne Weiterleitung waere `gms.base` in fetch_usage
        # ein AttributeError, sobald run() misst statt direkt zu rufen.
        return self.inner.base

    def graphql(self, query, variables=None):
        self.calls += 1
        return self.inner.graphql(query, variables)

    def get_aspect(self, entity_type, urn, aspect):
        self.calls += 1
        return self.inner.get_aspect(entity_type, urn, aspect)

    def _send(self, method, url, payload):
        # `fetch_usage` geht jetzt ueber `_send` statt `graphql` (Ledger-
        # Fix: rohe Zeitreihen-Ablage statt Aggregation) -- ohne diese
        # Weiterleitung wuerden die drei Nutzungs-Aufrufe pro `run()` aus
        # `api_calls` verschwinden, obwohl sie echte GMS-Aufrufe sind.
        self.calls += 1
        return self.inner._send(method, url, payload)


def run(gms, focus: str, now_ms: int, lineage_count: int = 200,
        judge_transport=None, judge_limit: int = 20,
        cooccurrence_fn=None) -> dict:
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

    Task 10, zweite Fix-Runde: das Modell-Urteil (`judge.py`) ist AUS,
    solange `judge_transport` `None` bleibt -- der Vorgabe-Wert. Zweite
    Abweichung vom Brief-Entwurf (der eine `or judge_limit == 0`-Bedingung
    vorsah, die den Urteils-Zweig auch OHNE Transport ausgeloest haette):
    ein Lauf ohne `--judge` soll die bestehende Artefakt-Form exakt
    unveraendert lassen, nicht mit leeren `judged_*`-Feldern aufgeblaeht
    werden, die niemand angefordert hat -- bestehende Konsumenten (Tests,
    `audit_claims.py`) lesen sonst Schluessel, die vorher nie da waren.
    `judge_transport is not None` ist das einzige Signal, ob der Zweig
    laeuft; `judge_limit` bleibt reine Obergrenze, kein Schalter.

    `cooccurrence_fn` (Vorgabe `None` -> `fetch_cooccurrence`, der
    GraphQL-Weg): die EINZIGE Stelle, an der die Ko-Okkurrenz-Quelle
    ausgetauscht werden kann. `probate.mcp_transport` liefert eine
    Funktion mit derselben Signatur `(gms, urn) -> (map, total)`, die
    stattdessen DataHubs eigenen MCP-Server befragt. Bewusst ein
    Parameter und kein Modul-Schalter: globaler Zustand haette bedeutet,
    dass ein Vergleichslauf die Quelle des naechsten beeinflusst. Der
    Vorgabewert bleibt der GraphQL-Weg -- ein Aufrufer, der nichts
    angibt, bekommt exakt den Lauf von vorher, Feld fuer Feld.

    Ein Fehlschlag beim Urteilen EINER Kante darf den Lauf nicht abbrechen
    (Auftragsvorgabe) -- das haelt bereits `judge_edge`/`judge_ledger`
    selbst: jeder Transport-Fehlschlag faellt PRO KANTE auf den
    deterministischen Befund zurueck (`fallback_reason`), nichts davon
    wird hier erneut abgefangen oder wiederholt. Was hier NICHT abgefangen
    wird, ist ein fehlgeschlagener `gather_context`-Aufruf (GMS-Fetch) --
    das ist dieselbe Klasse Fehler wie oben (`GmsError` propagiert), keine
    Modell-Frage: eine gescheiterte Katalog-Abfrage ist auch im Urteils-
    Zweig keine Abwesenheit.
    """
    counting = _Counting(gms)
    declared = fetch_declared_edges(counting, focus, count=lineage_count)
    cooccurred, queries_seen = (cooccurrence_fn or fetch_cooccurrence)(counting, focus)

    # WICHTIG: eigene Wall-Clock-Messung, NICHT das `now_ms`-Argument von
    # `run()`. `now_ms` kann eine simulierte Zeit sein (`ui/serve.py`s
    # "fast-forward"-Knopf ruft `run(gms, focus, now_ms + offset_days*DAY)`
    # -- eine reine ANSICHTS-Verschiebung fuer die Alters-Rechnung in
    # `classify_edges`, kein Signal, dass die Rohablage eine andere Zeit
    # abfragen soll). Wuerde diese Funktion `now_ms` an `usage_evidence`
    # durchreichen, wuerde "fast-forward" das GMS-Abfragefenster tatsaechlich
    # in die Zukunft verschieben und reale Buckets verfehlen -- ein Fehler,
    # der bis zum naechsten Live-Test unsichtbar geblieben waere. Die
    # Rohablage wird immer zur ECHTEN aktuellen Zeit abgefragt; nur die
    # Alters-Interpretation der gefundenen Daten darf simuliert werden.
    usage_fetch_now_ms = int(_time.time() * 1000)
    coverage_by_urn: dict[str, Coverage] = {}
    timeline_by_urn: dict[str, Timeline] = {}
    for target in sorted(declared | set(cooccurred)):
        cov, tl = usage_evidence(counting, target, now_ms=usage_fetch_now_ms)
        coverage_by_urn[target] = cov
        timeline_by_urn[target] = tl

    verdicts = classify_edges(
        focus, declared, cooccurred, coverage_by_urn, timeline_by_urn, now_ms,
        queries_seen=queries_seen,
    )
    counts = {s: sum(1 for v in verdicts if v.state == s) for s in STATES}
    buckets_seen = sum(c.buckets_seen for c in coverage_by_urn.values())
    spans = [c.days_span for c in coverage_by_urn.values() if c.days_span is not None]
    usage_window_start_ms, usage_window_end_ms = _usage_window_ms(usage_fetch_now_ms)

    out = {
        "focus": focus,
        "gms": getattr(gms, "base", ""),
        # Welcher Weg die Ko-Okkurrenz geliefert hat. Steht im Artefakt,
        # weil zwei Laeufe mit identischen Zahlen sonst nicht mehr
        # unterscheidbar waeren -- und der Vergleich der beiden Wege genau
        # davon lebt, dass man hinterher noch weiss, welcher welcher war.
        "cooccurrence_source": (
            "graphql" if cooccurrence_fn is None
            else getattr(cooccurrence_fn, "source_name", "custom")
        ),
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
        # Coordinator-Review 07.08. (IMPORTANT 2): dasselbe Fenster, das
        # jede `dead`-Kante in ihrer Evidenz einzeln traegt (`cov.window_*`),
        # hier zusaetzlich EINMAL auf Artefakt-Ebene -- die eine Praemisse,
        # die `dead` von `unknown` trennt, muss nicht mehr aus jeder
        # einzelnen Kante rekonstruiert werden.
        #
        # Re-Review 07.08. (Nachtrag): `window_days` NIE als der blosse
        # `USAGE_WINDOW_DAYS`-Konstantenwert (32) schreiben -- das Fenster
        # ist tatsaechlich `USAGE_WINDOW_DAYS` Tage RUECKWAERTS plus 1 Tag
        # Puffer VORWAERTS (`_usage_window_ms`), also 33 Tage `end - start`.
        # `Coverage.window_days` (und damit jede `dead`-Evidenz) leitet das
        # bereits korrekt aus `end - start` her; ein hart eingetragener
        # Konstantenwert waere dieselbe Klasse Fehler wie die urspruengliche
        # `usageStats`-Aggregation -- eine Zahl, die neben ihrem eigenen
        # Beleg steht und ihm widerspricht. Live gemessen: Artefakt zeigte
        # `window_days=32` neben identischen `window_start_ms`/
        # `window_end_ms`, deren Differenz 33 ergibt -- genau die Kante-
        # Evidenz zeigte korrekt 33. Jetzt aus DENSELBEN zwei Zahlen
        # hergeleitet wie jede `Coverage`, nicht aus der Konstante.
        "window_days": (usage_window_end_ms - usage_window_start_ms) // _DAY_MS,
        "window_start_ms": usage_window_start_ms,
        "window_end_ms": usage_window_end_ms,
        "api_calls": counting.calls,
        "queries_seen": queries_seen,
        "edges": [v.to_json(now_ms) for v in verdicts],
    }

    if judge_transport is not None:
        # Spaeter Import (nicht am Modulkopf): `judge.py` importiert
        # bereits von `ledger.py` (Edge/EdgeVerdict/Coverage/Timeline) --
        # ein Import am Kopf dieser Datei waere ein echter Kreis. Der
        # Import hier drin bleibt EINMALIG pro `run()`-Aufruf mit
        # aktivem Urteil, nicht pro Kante.
        import time as _t

        from probate.judge import judge_ledger

        t0 = _t.perf_counter()
        judgements = judge_ledger(counting, out, judge_transport, limit=judge_limit)
        out["judgements"] = judgements
        out["judged_edges"] = len(judgements)
        out["judged_with_model"] = sum(1 for j in judgements if j["used_model"])
        out["judged_fallback"] = sum(1 for j in judgements if not j["used_model"])
        out["judge_seconds_total"] = round(_t.perf_counter() - t0, 2)
        # `counting.calls` waechst waehrend `judge_ledger` weiter (jeder
        # `gather_context`-Aufruf laeuft ueber denselben Zaehler) -- diese
        # Zeile MUSS nach `judge_ledger` stehen, sonst zaehlt `api_calls`
        # die Kontext-Abfragen des Urteils nicht mit.
        out["api_calls"] = counting.calls

    return out
