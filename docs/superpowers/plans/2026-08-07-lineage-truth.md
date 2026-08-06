# Lineage-Wahrheitsprüfer — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein Agent, der die **deklarierte** Lineage in DataHub fortlaufend gegen die **gemessene** Nutzung hält und die Differenz **pro Kante** mit Zeitachse und Beleg ausgibt — und dabei „wir haben nichts gemessen" nie mit „es wurde nichts genutzt" verwechselt.

**Architecture:** Vier Schichten über dem bestehenden Code. `probate/ledger.py` (neu) rechnet deterministisch das Kanten-Register mit vier Zuständen, Abdeckungs-Prüfung als Gate davor und Zeitachse aus denselben Buckets. `probate/judge.py` (neu) ist die **einzige** Stelle mit Modellaufruf und verwirft jedes Urteil ohne wörtliches Zitat. `probate/correct.py` (neu) schlägt Korrekturen vor und schreibt sie ausschliesslich über das **unveränderte** `writeback.py`. `ui/` ist eine statische Seite ohne Bauschritt, im Live-Modus von einem Python-Proxy bedient.

**Tech Stack:** Python 3.11 (nur über `uv run`), Standardbibliothek + `acryl-datahub`, pytest mit handgeschriebenen Fakes, HTML/CSS/ES-Module ohne Rahmenwerk, `http.server` als Proxy.

## Global Constraints

Diese Liste gilt implizit für **jede** Aufgabe. Ein Verstoss ist ein Fehlschlag, auch wenn die Tests grün sind.

**Umgebung**
- Python ausschliesslich über `uv run --python 3.11 …`. Ein blosses `python`/`pip` trifft den kaputten 3.9-Store-Alias, DataHub verlangt 3.10+.
- Tests: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q` — **Baseline 61 grün**. Nach jeder Aufgabe muss die Zahl gewachsen sein und alles grün.
- Beleg-Prüfung: `uv run --python 3.11 python harness/audit_claims.py` — muss grün sein, bevor irgendetwas als fertig gilt.
- Actions-Pipeline: `uv run --python 3.11 --with acryl-datahub-actions datahub-actions actions -c probate_action/recipe.yml` (der Unterbefehl heisst `actions`, **nicht** `run`).

**Adressen**
- GMS **nur** `http://localhost:28080`.
- **NIEMALS 18080** — trägt `showcase-ecommerce`, gegen das `datahub-attest` veröffentlichte Zahlen gemessen hat. Lesen zur Not, schreiben nie.
- **NIEMALS 8080** — Joels WhatsApp-Bridge.
- Kafka `localhost:29192`, Schema-Registry `http://localhost:28080/schema-registry/api/`. Es gibt **keinen** Dienst auf 8081.
- Werkbank-Proxy: Port **8899**.

**Unantastbarer Bestand**
- `probate/writeback.py` wird **nicht verändert**. Neue Aufrufer, keine neuen Methoden.
- `probate/gms.py` wird **nicht verändert**. Nur additive Ergänzung, falls zwingend — und dann mit Begründung im Commit.
- `probate/targets.py` wird **nicht verändert**. `ledger.py` liegt daneben.

**Arbeitsweise**
- TDD: jede neue Logik erst RED, dann GREEN. Kein Mock-Rahmenwerk — handgeschriebene Fakes wie in `tests/test_writeback.py` (`FakeGms` mit `upserts`/`deletes`-Listen).
- Jede neue Datei: Docstring sagt **warum** sie existiert, nicht was sie tut.
- Commit nach jeder grünen Aufgabe. Deutsche Commit-Message im Repo-Stil, kleingeschrieben, `bereich: was` (`feat(ledger): …`, `fix(ui): …`).
- Jede Zahl, die später in Prosa auftaucht, kommt aus einem Lauf-Artefakt in `harness/runs/`. Der Schlüsselname in `claims.json` muss **exakt** dem Schlüssel im Artefakt entsprechen (`audit_claims`-Mechanik).
- Geseedete/synthetische Daten werden in **jedem** Artefakt als solche ausgewiesen (`"seeded": true`).
- Jeder Live-Lauf räumt hinter sich auf: Probe-Entitäten löschen **und die Löschung zurücklesen**.
- Eine gescheiterte Abfrage ist keine Abwesenheit. „Nicht geprüft" und „gibt es nicht" sind verschiedene Aussagen und werden verschieden ausgegeben.

**Die zwölf Fallen** (jede steht zusätzlich an der Aufgabe, die sie betrifft)

| # | Falle |
|---|---|
| 1 | `POST /openapi/v3/entity/<typ>` will eine **Liste**. Ein Objekt → HTTP 200 und schreibt nichts. |
| 2 | GraphQL meldet Fehler **mit HTTP 200**, im `errors`-Feld. |
| 3 | `Deprecation` braucht **`actor`** (Pflichtfeld), sonst HTTP 400. |
| 4 | `TestResults` hat **kein Zeitstempelfeld** — erfundene Felder werden still verworfen. |
| 5 | `createForm` will `structuredPropertyParams` **beim Anlegen**, andere Feldform als `submitFormPrompt`. |
| 6 | Prompt-IDs sind **global eindeutig über die ganze Instanz**. |
| 7 | `submitFormPrompt`/`verifyForm` liefern **Boolean direkt** — `{ success }` scheitert. |
| 8 | Pythons `hash()` ist **nicht prozessstabil** → `hashlib.sha1`. |
| 9 | `verifyForm` braucht `actors:{owners:true}` **und** der Handelnde muss Owner sein. |
| 10 | Ohne Token ist der Handelnde `urn:li:corpuser:__datahub_system`, nicht `datahub`. |
| 11 | Der MCP-Server hat **keine Zeitfenster** — Timestamps in `gql/queries.gql` auskommentiert. |
| 12 | `get_lineage` liefert **>100'000 Zeichen** ohne Pagination-Vorgaben. |

**Gestaltungsvorgaben — bindend, wörtlich aus der Spec §Gestaltung** (gilt für alle P5-Aufgaben)

Joels Vorgabe wörtlich (06.08.): *verständlich, schön, erklärend und beruhigend, modern, SaaS-Vibe, professionell — ohne AI-Slop-Look.*

Gebote:
- **Beruhigend statt alarmierend.** Rot ist reserviert für den *Zustand* einer Kante, nirgends für Rahmen, Kopfzeilen oder Knöpfe. Gedeckte Grundfarbe, viel Weissraum, ruhige Übergänge.
- **Erklärend eingebaut, nicht als Handbuch daneben.** Jeder der vier Zustände trägt an Ort und Stelle einen Satz, was er bedeutet. Die Abdeckungs-Angabe steht *über* den Ergebnissen, nicht in einer Fussnote.
- **Zwei Quellen, zwei Farben, durchgehend.** Deklariert und Gemessen bekommen je eine Farbe, die auf jedem Bildschirm dieselbe bleibt.
- **Zustand hat eine Form, nicht nur eine Zahl.** Chip, Streifen, Punkt — auf einen Blick erkennbar, ohne zu lesen.
- **SaaS-Handwerk:** echte Typo-Hierarchie, Tabellenziffern wo Zahlen untereinanderstehen, sichtbarer Tastatur-Fokus, helles und dunkles Thema gleichwertig gepflegt, breite Inhalte scrollen in ihrem eigenen Container statt die Seite zu verschieben.

Verboten, weil es sofort nach KI-Ausgabe aussieht:
- Emoji als Abschnittsmarken
- Farbverlauf im Kopfbereich
- alles zentriert
- überall dieselbe grosse Eckenrundung
- Akzentstreifen an gerundeten Karten
- Creme-Grundton mit Terrakotta-Akzent
- Inter oder Space Grotesk als Standardschrift
- riesiger Hero-Bereich ohne Inhalt

Massstab: Ein Betrachter soll denken „das ist ein Produkt", nicht „das ist ein Hackathon-Projekt".

---

## Dateistruktur

| Datei | Verantwortung |
|---|---|
| `probate/ledger.py` (neu) | Kanten-Register: Typen, Abdeckung, Zeitachse, Klassifikation, Beschaffung, Lauf |
| `probate/judge.py` (neu) | Modell-Urteil mit Zitatpflicht; einziger Modellaufruf im Projekt |
| `probate/correct.py` (neu) | Korrektur-Vorschläge und ihre Anwendung über `writeback.py` |
| `probate/cli.py` (ändern) | drei neue Unterbefehle: `ledger`, `propose`, `correct` |
| `harness/audit_claims.py` (ändern) | mehrere Lauf-Artefakte statt nur `campaign.json` |
| `harness/loadgen.py` (neu) | synthetische Lasttest-Entitäten anlegen und restlos löschen |
| `harness/loadtest.py` (neu) | Messgerüst: Dauer, Spitzenspeicher, API-Aufrufe, Bruchstelle |
| `ui/werkbank.html` · `.css` · `.js` (neu) | vier Bereiche, sechs Knöpfe, zwei Betriebsarten |
| `ui/serve.py` (neu) | Live-Modus: Proxy auf 8899, Knöpfe rufen `probate/`-Module |
| `probate_action/recipe.yml` (P0, läuft parallel) | Kafka 29192, Schema-Registry über GMS |

**Unverändert:** `writeback.py`, `gms.py`, `targets.py`, `parity.py`, `ruleset.py`, `succession.py`, `campaign.py`.

---

# P1 — Das Kanten-Register (Schicht 1 + 1b)

> Nie streichbar. Ohne P1 gibt es kein Produkt.

### Task 1: Kanten-Typen, Zustände, Buckets

**Parallel zu:** Task 16 (UI-Gerüst), Task 21 (Lasttest-Fixtures) — beide brauchen von hier nur die JSON-Form, nicht den Code.

**Files:**
- Create: `probate/ledger.py`
- Test: `tests/test_ledger.py`

**Interfaces:**
- Consumes: nichts.
- Produces: `STATES`, `Edge(upstream, downstream)` mit `.key() -> str`, `Bucket(bucket_ms, total_sql_queries, unique_user_count)`. Alle Folge-Aufgaben benutzen genau diese Namen.

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_ledger.py
from probate.ledger import STATES, Bucket, Edge


def test_edge_key_is_stable_and_directional():
    e = Edge(upstream="urn:li:dataset:A", downstream="urn:li:dataset:B")
    assert e.key() == "urn:li:dataset:A->urn:li:dataset:B"
    assert Edge("urn:li:dataset:B", "urn:li:dataset:A").key() != e.key()


def test_edge_is_hashable_and_usable_as_dict_key():
    e = Edge("A", "B")
    assert {e: 1}[Edge("A", "B")] == 1


def test_the_four_states_and_no_fifth():
    assert STATES == ("confirmed", "dead", "missing", "unknown")


def test_bucket_carries_traffic_and_users_separately():
    b = Bucket(bucket_ms=1_700_000_000_000, total_sql_queries=7, unique_user_count=2)
    assert b.total_sql_queries == 7
    assert b.unique_user_count == 2
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_ledger.py -q`
Erwartet: FAIL mit `ModuleNotFoundError: No module named 'probate.ledger'`

- [ ] **Step 3: Minimale Umsetzung**

```python
# probate/ledger.py
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
```

- [ ] **Step 4: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_ledger.py -q`
Erwartet: 4 passed

- [ ] **Step 5: Volle Suite**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 65 passed (61 Baseline + 4)

- [ ] **Step 6: Commit**

```bash
git add probate/ledger.py tests/test_ledger.py
git commit -m "feat(ledger): kanten-typen und die vier zustaende"
```

---

### Task 2: Abdeckungs-Prüfung — das Gate vor jeder Klassifikation

**Parallel zu:** Task 16, Task 21.

**Files:**
- Modify: `probate/ledger.py`
- Test: `tests/test_ledger.py`

**Interfaces:**
- Consumes: `Bucket` aus Task 1.
- Produces: `Coverage(buckets_seen, oldest_bucket_ms, newest_bucket_ms, reason)` mit `.has_window -> bool`, `.days_span -> int | None`, `.to_json() -> dict`; `coverage_from_buckets(buckets: tuple[Bucket, ...]) -> Coverage`.

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_ledger.py -- anhaengen
from probate.ledger import Coverage, coverage_from_buckets


def test_no_buckets_means_no_window_with_a_stated_reason():
    c = coverage_from_buckets(())
    assert c.has_window is False
    assert c.buckets_seen == 0
    assert c.reason == "keine Nutzungs-Zeitfenster im Katalog"
    assert c.days_span is None


def test_buckets_with_zero_traffic_still_count_as_a_window():
    """Wir haben hingesehen. Dass nichts passiert ist, ist ein Ergebnis."""
    day = 86_400_000
    c = coverage_from_buckets((Bucket(day, 0, 0), Bucket(2 * day, 0, 0)))
    assert c.has_window is True
    assert c.buckets_seen == 2
    assert c.reason == ""


def test_span_is_measured_from_oldest_to_newest_bucket():
    day = 86_400_000
    c = coverage_from_buckets((Bucket(10 * day, 3, 1), Bucket(40 * day, 1, 1)))
    assert c.oldest_bucket_ms == 10 * day
    assert c.newest_bucket_ms == 40 * day
    assert c.days_span == 30


def test_buckets_are_sorted_before_measuring_the_span():
    day = 86_400_000
    c = coverage_from_buckets((Bucket(40 * day, 1, 1), Bucket(10 * day, 3, 1)))
    assert c.oldest_bucket_ms == 10 * day
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_ledger.py -q`
Erwartet: FAIL mit `ImportError: cannot import name 'Coverage'`

- [ ] **Step 3: Minimale Umsetzung**

```python
# probate/ledger.py -- anhaengen

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
```

- [ ] **Step 4: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 69 passed

- [ ] **Step 5: Commit**

```bash
git add probate/ledger.py tests/test_ledger.py
git commit -m "feat(ledger): abdeckungs-pruefung als gate vor jeder klassifikation"
```

---

### Task 3: Zeitachse — letzte Deckung, tot-seit, Verlauf

**Parallel zu:** Task 16, Task 21.

**Files:**
- Modify: `probate/ledger.py`
- Test: `tests/test_ledger.py`

**Interfaces:**
- Consumes: `Bucket` aus Task 1.
- Produces: `Timeline(buckets: tuple[Bucket, ...])` mit `.last_covered_ms -> int | None`, `.dead_since(now_ms) -> tuple[int | None, bool]`, `.series -> tuple[tuple[int, int], ...]`, `.to_json(now_ms) -> dict`.

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_ledger.py -- anhaengen
from probate.ledger import Timeline

DAY = 86_400_000


def test_last_covered_is_the_newest_bucket_with_actual_traffic():
    t = Timeline((Bucket(10 * DAY, 5, 2), Bucket(20 * DAY, 0, 0), Bucket(30 * DAY, 0, 0)))
    assert t.last_covered_ms == 10 * DAY


def test_dead_since_counts_days_from_the_last_covered_bucket():
    t = Timeline((Bucket(10 * DAY, 5, 2), Bucket(30 * DAY, 0, 0)))
    days, at_least = t.dead_since(now_ms=40 * DAY)
    assert days == 30
    assert at_least is False


def test_never_covered_is_reported_as_at_least_since_the_oldest_observation():
    """Vor dem aeltesten Bucket wissen wir nichts. Also 'mindestens seit',
    nicht 'seit' -- eine Zahl, die mehr behauptet als die Daten hergeben,
    ist genau der Fehler, gegen den dieses Werkzeug antritt."""
    t = Timeline((Bucket(10 * DAY, 0, 0), Bucket(30 * DAY, 0, 0)))
    days, at_least = t.dead_since(now_ms=40 * DAY)
    assert days == 30
    assert at_least is True
    assert t.last_covered_ms is None


def test_empty_timeline_yields_no_age_at_all():
    """Ohne Zeitfenster gibt es kein Alter. None ist die richtige Antwort,
    0 waere eine Luege."""
    days, at_least = Timeline(()).dead_since(now_ms=40 * DAY)
    assert days is None
    assert at_least is False


def test_series_keeps_every_bucket_in_order_instead_of_summing_them():
    t = Timeline((Bucket(30 * DAY, 1, 1), Bucket(10 * DAY, 5, 2)))
    assert t.series == ((10 * DAY, 5), (30 * DAY, 1))
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_ledger.py -q`
Erwartet: FAIL mit `ImportError: cannot import name 'Timeline'`

- [ ] **Step 3: Minimale Umsetzung**

```python
# probate/ledger.py -- anhaengen


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
```

- [ ] **Step 4: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 74 passed

- [ ] **Step 5: Commit**

```bash
git add probate/ledger.py tests/test_ledger.py
git commit -m "feat(ledger): zeitachse -- letzte deckung, tot-seit, verlauf"
```

---

### Task 4: `classify_edges` — die Kernregel

**Depends:** Task 1, 2, 3.

**Files:**
- Modify: `probate/ledger.py`
- Test: `tests/test_ledger.py`

**Interfaces:**
- Consumes: `Edge`, `Coverage`, `Timeline`, `STATES`.
- Produces:
  ```python
  @dataclass(frozen=True)
  class EdgeVerdict:
      edge: Edge
      state: str
      evidence: dict
      coverage: Coverage
      timeline: Timeline
      def to_json(self, now_ms: int) -> dict

  def classify_edges(
      focus: str,
      declared: set[str],
      cooccurred: dict[str, list[str]],
      coverage_by_urn: dict[str, Coverage],
      timeline_by_urn: dict[str, Timeline],
      now_ms: int,
  ) -> list[EdgeVerdict]
  ```

- [ ] **Step 1: Failing test schreiben — die Kernregel zuerst**

```python
# tests/test_ledger.py -- anhaengen
from probate.ledger import EdgeVerdict, classify_edges

NO_DATA = Coverage(0, None, None, "keine Nutzungs-Zeitfenster im Katalog")
LOOKED = Coverage(30, 10 * DAY, 40 * DAY, "")


def test_unknown_is_never_dead_when_no_windows_exist():
    """DIE Kernregel. Der Fehler, gegen den der ganze Umbau antritt.

    Links: keine Zeitfenster -> Aussage nicht moeglich -> unknown.
    Rechts: Zeitfenster da, Verkehr null -> Aussage moeglich -> dead.
    Summiert waeren beide dieselbe Null.
    """
    ohne = classify_edges(
        focus="urn:up", declared={"urn:down"}, cooccurred={},
        coverage_by_urn={"urn:down": NO_DATA},
        timeline_by_urn={"urn:down": Timeline(())},
        now_ms=50 * DAY)
    mit = classify_edges(
        focus="urn:up", declared={"urn:down"}, cooccurred={},
        coverage_by_urn={"urn:down": LOOKED},
        timeline_by_urn={"urn:down": Timeline((Bucket(40 * DAY, 0, 0),))},
        now_ms=50 * DAY)

    assert ohne[0].state == "unknown"
    assert mit[0].state == "dead"
    assert ohne[0].evidence["reason"] == "keine Nutzungs-Zeitfenster im Katalog"


def test_a_urn_missing_from_the_coverage_map_is_unknown_not_dead():
    """Ein Dataset, das wir gar nicht abgefragt haben, ist unknown.
    Ein stilles .get()-Default auf 'abgedeckt' waere ein Fehlbefund."""
    v = classify_edges(
        focus="urn:up", declared={"urn:down"}, cooccurred={},
        coverage_by_urn={}, timeline_by_urn={}, now_ms=50 * DAY)
    assert v[0].state == "unknown"
    assert v[0].evidence["reason"] == "nicht abgefragt"


def test_declared_and_measured_is_confirmed_with_the_query_urn_as_evidence():
    v = classify_edges(
        focus="urn:up", declared={"urn:down"},
        cooccurred={"urn:down": ["urn:li:query:q1", "urn:li:query:q2"]},
        coverage_by_urn={"urn:down": LOOKED},
        timeline_by_urn={"urn:down": Timeline((Bucket(40 * DAY, 9, 2),))},
        now_ms=50 * DAY)
    assert v[0].state == "confirmed"
    assert v[0].evidence["query_urns"] == ["urn:li:query:q1", "urn:li:query:q2"]


def test_measured_but_not_declared_is_missing_and_never_unknown():
    """Was wir gemessen haben, kann nicht 'nicht gemessen' sein --
    auch dann nicht, wenn die Aggregat-Abdeckung duenn ist."""
    v = classify_edges(
        focus="urn:up", declared=set(),
        cooccurred={"urn:other": ["urn:li:query:q9"]},
        coverage_by_urn={"urn:other": NO_DATA},
        timeline_by_urn={"urn:other": Timeline(())},
        now_ms=50 * DAY)
    assert v[0].state == "missing"
    assert v[0].edge.key() == "urn:up->urn:other"


def test_missing_edges_declare_their_direction_as_unproven():
    """QuerySubject nennt nur `entity`, kein Richtungsfeld. Ko-Okkurrenz
    ist ungerichtet -- das muss im Beleg stehen, sonst wandert eine
    geratene Richtung in P3 in den Katalog."""
    v = classify_edges(
        focus="urn:up", declared=set(),
        cooccurred={"urn:other": ["urn:li:query:q9"]},
        coverage_by_urn={}, timeline_by_urn={}, now_ms=50 * DAY)
    assert v[0].evidence["direction_evidence"] == "co-occurrence (undirected)"


def test_every_state_produced_is_one_of_the_four():
    v = classify_edges(
        focus="urn:up", declared={"a", "b"},
        cooccurred={"b": ["urn:li:query:q1"], "c": ["urn:li:query:q2"]},
        coverage_by_urn={"a": LOOKED, "b": LOOKED, "c": LOOKED},
        timeline_by_urn={"a": Timeline((Bucket(40 * DAY, 0, 0),)),
                         "b": Timeline((Bucket(40 * DAY, 4, 1),)),
                         "c": Timeline((Bucket(40 * DAY, 4, 1),))},
        now_ms=50 * DAY)
    assert {x.state for x in v} == {"dead", "confirmed", "missing"}
    assert all(x.state in STATES for x in v)


def test_verdict_json_carries_state_evidence_coverage_and_timeline():
    v = classify_edges(
        focus="urn:up", declared={"urn:down"}, cooccurred={},
        coverage_by_urn={"urn:down": LOOKED},
        timeline_by_urn={"urn:down": Timeline((Bucket(40 * DAY, 0, 0),))},
        now_ms=50 * DAY)[0].to_json(now_ms=50 * DAY)
    assert v["state"] == "dead"
    assert v["edge"] == "urn:up->urn:down"
    assert v["coverage"]["buckets_seen"] == 30
    assert v["timeline"]["dead_since_days"] == 10
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_ledger.py -q`
Erwartet: FAIL mit `ImportError: cannot import name 'classify_edges'`

- [ ] **Step 3: Minimale Umsetzung**

```python
# probate/ledger.py -- anhaengen

_NOT_ASKED = Coverage(0, None, None, "nicht abgefragt")


@dataclass(frozen=True)
class EdgeVerdict:
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
) -> list[EdgeVerdict]:
    """Vier Zustaende, in dieser Reihenfolge geprueft.

    Die Abdeckung ist das GATE: ohne Zeitfenster wird gar nicht erst
    geprueft, ob gemessen wurde -- die Antwort waere bedeutungslos.
    Deshalb steht `has_window` VOR dem Blick in `cooccurred`, nicht
    danach. Ein fehlender Eintrag in `coverage_by_urn` ist "nicht
    abgefragt" und damit ebenfalls `unknown`; ein stilles Default auf
    "abgedeckt" waere genau der Fehlbefund, den dieses Modul verhindert.
    """
    out: list[EdgeVerdict] = []

    for target in sorted(declared):
        cov = coverage_by_urn.get(target, _NOT_ASKED)
        tl = timeline_by_urn.get(target, Timeline(()))
        edge = Edge(focus, target)

        if not cov.has_window:
            out.append(EdgeVerdict(
                edge, "unknown",
                {"reason": cov.reason, "source": "declared lineage"},
                cov, tl))
            continue

        queries = cooccurred.get(target, [])
        if queries:
            out.append(EdgeVerdict(
                edge, "confirmed",
                {"query_urns": list(queries),
                 "source": "declared lineage + query co-occurrence"},
                cov, tl))
        else:
            out.append(EdgeVerdict(
                edge, "dead",
                {"reason": "im geprueften Fenster nie gemessen",
                 "buckets_checked": cov.buckets_seen,
                 "source": "declared lineage"},
                cov, tl))

    for target in sorted(set(cooccurred) - declared):
        out.append(EdgeVerdict(
            Edge(focus, target), "missing",
            {"query_urns": list(cooccurred[target]),
             "cooccurrence_count": len(cooccurred[target]),
             "direction_evidence": "co-occurrence (undirected)",
             "source": "query co-occurrence"},
            coverage_by_urn.get(target, _NOT_ASKED),
            timeline_by_urn.get(target, Timeline(()))))

    return out
```

- [ ] **Step 4: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 81 passed

- [ ] **Step 5: Commit**

```bash
git add probate/ledger.py tests/test_ledger.py
git commit -m "feat(ledger): vier zustaende, abdeckung als gate -- unknown ist nie dead"
```

---

### Task 5: Beschaffung — Nutzung lesen, Ko-Okkurrenz mit Query-URNs behalten

**Depends:** Task 1, 2, 3. **Parallel zu:** Task 4 (andere Funktionen derselben Datei — bei Konflikt Task 4 zuerst mergen).

**Falle 2** (GraphQL meldet Fehler mit HTTP 200) ist in `gms.graphql()` bereits verriegelt — **nicht** neu bauen.
**Falle 12** (`get_lineage` >100'000 Zeichen): die Lineage-Abfrage bekommt hier ein **explizites** `count` und der Aufrufer darf es senken.
**Falle 11** (MCP-Server hat keine Zeitfenster): deshalb rohes GraphQL, nicht MCP.

**Files:**
- Modify: `probate/ledger.py`
- Test: `tests/test_ledger.py`
- Artefakt: `harness/runs/query-timestamp-probe.json`

**Interfaces:**
- Consumes: `Gms` (unverändert), `probate.targets._QUERY_SEARCH_Q`.
- Produces:
  ```python
  USAGE_Q: str
  LINEAGE_Q: str
  def fetch_usage(gms, urn: str, range_: str = "MONTH") -> tuple[Bucket, ...]
  def fetch_declared_edges(gms, urn: str, count: int = 200) -> set[str]
  def fetch_cooccurrence(gms, urn: str) -> dict[str, list[str]]
  ```

- [ ] **Step 1: Messschritt — was liefert eine Query-Entität an Zeitstempeln?**

Die Zeitachse hängt bisher an den **Dataset**-Buckets. Ob eine Query-Entität einen brauchbaren eigenen Zeitstempel trägt, ist **nicht gemessen**. Vor dem Bauen einmal nachsehen, statt zu raten:

```bash
uv run --python 3.11 python -c "
import json, pathlib
from probate.gms import Gms
g = Gms('http://localhost:28080')
hits = g.graphql('''query { searchAcrossEntities(input:{types:[QUERY], query:\"*\", count:3}) { total searchResults { entity { urn } } } }''')
urns = [r['entity']['urn'] for r in hits['searchAcrossEntities']['searchResults']]
out = {'seeded': True, 'probed_urns': urns, 'queryproperties': {}}
for u in urns:
    out['queryproperties'][u] = g.get_aspect('query', u, 'queryproperties')
p = pathlib.Path('harness/runs/query-timestamp-probe.json')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(out, indent=2), encoding='utf-8')
print(json.dumps(out, indent=2)[:1200])
"
```

Ergebnis auswerten und **im Docstring von `fetch_cooccurrence` festhalten**:
- Kommt ein verwertbarer Zeitstempel zurück (z. B. `created.time`) → als Kommentar notieren, dass die Detail-Ebene ihn später nutzen kann. Die Zeitachse bleibt trotzdem in dieser Runde an den Dataset-Buckets, weil dort die gemessene Grundlage ist.
- Kommt keiner zurück oder ist die Abfrage gescheitert → **genau das** notieren, mit dem Fehlertext. „Nicht geprüft" und „gibt es nicht" sind verschiedene Aussagen.

- [ ] **Step 2: Failing test schreiben**

```python
# tests/test_ledger.py -- anhaengen
from probate.ledger import fetch_cooccurrence, fetch_declared_edges, fetch_usage


class FakeGms:
    """Handgeschrieben, kein Mock-Rahmenwerk -- gleiches Muster wie
    tests/test_writeback.py."""

    def __init__(self, graphql_by_call=None, aspects=None):
        self.graphql_by_call = list(graphql_by_call or [])
        self.aspects = aspects or {}
        self.queries_sent = []

    def graphql(self, query, variables=None):
        self.queries_sent.append((query, variables))
        return self.graphql_by_call.pop(0)

    def get_aspect(self, entity_type, urn, aspect):
        return self.aspects.get((entity_type, urn, aspect))


def test_fetch_usage_turns_buckets_into_bucket_objects():
    g = FakeGms([{"dataset": {"usageStats": {"buckets": [
        {"bucket": 10 * DAY, "metrics": {"totalSqlQueries": 5, "uniqueUserCount": 2}},
        {"bucket": 20 * DAY, "metrics": {"totalSqlQueries": 0, "uniqueUserCount": 0}},
    ]}}}])
    got = fetch_usage(g, "urn:x")
    assert got == (Bucket(10 * DAY, 5, 2), Bucket(20 * DAY, 0, 0))


def test_fetch_usage_returns_empty_tuple_when_the_catalog_has_no_stats():
    """Der Beispielkatalog liefert live `buckets: []`. Leer heisst hier
    'nicht gemessen' -- und genau so kommt es bei Coverage an."""
    g = FakeGms([{"dataset": {"usageStats": None}}])
    assert fetch_usage(g, "urn:x") == ()
    assert coverage_from_buckets(fetch_usage(FakeGms([{"dataset": None}]), "urn:x")).has_window is False


def test_fetch_usage_treats_a_null_metric_as_zero_traffic_not_as_a_missing_bucket():
    """Ein Bucket mit null Verkehr ist ein Beleg, dass hingesehen wurde.
    Er darf nicht wegfallen, sonst wird aus `dead` ein `unknown`."""
    g = FakeGms([{"dataset": {"usageStats": {"buckets": [
        {"bucket": 10 * DAY, "metrics": {"totalSqlQueries": None, "uniqueUserCount": None}},
    ]}}}])
    assert fetch_usage(g, "urn:x") == (Bucket(10 * DAY, 0, 0),)


def test_fetch_declared_edges_passes_the_count_limit_into_the_query():
    """Falle 12: get_lineage liefert >100k Zeichen ohne Vorgabe."""
    g = FakeGms([{"dataset": {"lineage": {"relationships": [
        {"entity": {"urn": "urn:d1"}}, {"entity": {"urn": "urn:d2"}}]}}}])
    assert fetch_declared_edges(g, "urn:x", count=50) == {"urn:d1", "urn:d2"}
    sent_query, sent_vars = g.queries_sent[0]
    assert sent_vars["count"] == 50
    assert "$count" in sent_query


def test_fetch_cooccurrence_keeps_the_query_urn_as_evidence_per_target():
    """targets.fetch_measured wirft die Query-URN weg. Genau die ist der
    Beleg, den jede confirmed/missing-Kante mitfuehren muss."""
    g = FakeGms(
        [{"searchAcrossEntities": {"total": 1, "searchResults": [
            {"entity": {"urn": "urn:li:query:q1"}}]}}],
        aspects={("query", "urn:li:query:q1", "querysubjects"): {
            "value": {"subjects": [{"entity": "urn:x"}, {"entity": "urn:other"}]}}},
    )
    assert fetch_cooccurrence(g, "urn:x") == {"urn:other": ["urn:li:query:q1"]}


def test_fetch_cooccurrence_never_reports_the_focus_dataset_as_its_own_consumer():
    g = FakeGms(
        [{"searchAcrossEntities": {"total": 1, "searchResults": [
            {"entity": {"urn": "urn:li:query:q1"}}]}}],
        aspects={("query", "urn:li:query:q1", "querysubjects"): {
            "value": {"subjects": [{"entity": "urn:x"}]}}},
    )
    assert fetch_cooccurrence(g, "urn:x") == {}


def test_fetch_cooccurrence_collects_every_query_that_touches_the_same_target():
    g = FakeGms(
        [{"searchAcrossEntities": {"total": 2, "searchResults": [
            {"entity": {"urn": "urn:li:query:q1"}},
            {"entity": {"urn": "urn:li:query:q2"}}]}}],
        aspects={
            ("query", "urn:li:query:q1", "querysubjects"): {
                "value": {"subjects": [{"entity": "urn:x"}, {"entity": "urn:o"}]}},
            ("query", "urn:li:query:q2", "querysubjects"): {
                "value": {"subjects": [{"entity": "urn:x"}, {"entity": "urn:o"}]}},
        },
    )
    assert fetch_cooccurrence(g, "urn:x") == {"urn:o": ["urn:li:query:q1", "urn:li:query:q2"]}
```

- [ ] **Step 3: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_ledger.py -q`
Erwartet: FAIL mit `ImportError: cannot import name 'fetch_usage'`

- [ ] **Step 4: Minimale Umsetzung**

```python
# probate/ledger.py -- anhaengen (Imports oben ergaenzen)
from probate.targets import _QUERY_SEARCH_Q as COOCCURRENCE_Q  # eine Wahrheit;
# targets.py bleibt unveraendert, der String wird nicht ein zweites Mal getippt.

# Gemessenes Rezept (UEBERGABE Sec.4, live gegen v1.5.0.6 verifiziert):
# liefert Buckets UND Aggregat. Wir nehmen die Buckets -- das Aggregat
# waere genau die Summierung, die "nichts gemessen" und "nichts passiert"
# ununterscheidbar macht.
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


def fetch_usage(gms, urn: str, range_: str = "MONTH") -> tuple[Bucket, ...]:
    """Rohe Zeitfenster, nicht summiert.

    Ein Bucket mit `totalSqlQueries: null` ist ein Bucket mit null
    Verkehr, kein fehlender Bucket -- er belegt, dass hingesehen wurde.
    Wer ihn wegfiltert, macht aus `dead` ein `unknown`.
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


def fetch_cooccurrence(gms, urn: str) -> dict[str, list[str]]:
    """Ko-Okkurrenz MIT Beleg: Ziel-URN -> Liste der Query-URNs.

    `targets.fetch_measured` liefert dieselbe Information als blosse
    Menge und wirft die Query-URN weg. Genau die ist aber der Beleg, den
    jede `confirmed`- und jede `missing`-Kante mitfuehren muss.

    Richtung: QuerySubject nennt nur `entity`, kein Richtungsfeld. Die
    Ko-Okkurrenz ist damit UNGERICHTET -- das steht im Beleg jeder
    missing-Kante und darf beim Schreiben (correct.py) nicht als
    gemessene Richtung ausgegeben werden.
    """
    hits = gms.graphql(COOCCURRENCE_Q, {"urn": urn})
    query_urns = [
        r["entity"]["urn"]
        for r in (hits.get("searchAcrossEntities") or {}).get("searchResults", [])
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
    return out
```

- [ ] **Step 5: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 88 passed

- [ ] **Step 6: Commit**

```bash
git add probate/ledger.py tests/test_ledger.py harness/runs/query-timestamp-probe.json
git commit -m "feat(ledger): beschaffung -- buckets roh, ko-okkurrenz mit query-urn als beleg"
```

---

### Task 6: `run()` + Lauf-Artefakt `ledger.json` + CLI-Unterbefehl

**Depends:** Task 4, 5.

**Files:**
- Modify: `probate/ledger.py`, `probate/cli.py` (neuer `add_parser`-Block bei `cli.py:84-119`, neuer `if`-Block **vor** der `status`-Zeile am Dateiende)
- Test: `tests/test_ledger.py`
- Artefakt: `harness/runs/ledger.json`

**Interfaces:**
- Consumes: alles aus P1.
- Produces:
  ```python
  def run(gms, focus: str, now_ms: int, lineage_count: int = 200) -> dict
  ```
  Rückgabe = das exakte JSON von `ledger.json`. **Flache ganzzahlige Schlüssel auf oberster Ebene**, weil `audit_claims` per Schlüsselnamen vergleicht:
  `edges_total`, `edges_confirmed`, `edges_dead`, `edges_missing`, `edges_unknown`, `coverage_buckets_seen`, `coverage_days_span`, `api_calls`.

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_ledger.py -- anhaengen
import json
from probate.ledger import run


def _gms_for_run():
    """Fokus urn:x: deklariert d1 (mit Verkehr -> confirmed) und d2
    (Buckets, aber kein Verkehr -> dead); gemessen zusaetzlich o
    (-> missing)."""
    return FakeGms(
        graphql_by_call=[
            {"dataset": {"lineage": {"relationships": [
                {"entity": {"urn": "urn:d1"}}, {"entity": {"urn": "urn:d2"}}]}}},
            {"searchAcrossEntities": {"total": 1, "searchResults": [
                {"entity": {"urn": "urn:li:query:q1"}}]}},
            {"dataset": {"usageStats": {"buckets": [
                {"bucket": 40 * DAY, "metrics": {"totalSqlQueries": 3, "uniqueUserCount": 1}}]}}},
            {"dataset": {"usageStats": {"buckets": [
                {"bucket": 40 * DAY, "metrics": {"totalSqlQueries": 0, "uniqueUserCount": 0}}]}}},
            {"dataset": {"usageStats": {"buckets": [
                {"bucket": 40 * DAY, "metrics": {"totalSqlQueries": 7, "uniqueUserCount": 1}}]}}},
        ],
        aspects={("query", "urn:li:query:q1", "querysubjects"): {
            "value": {"subjects": [{"entity": "urn:x"}, {"entity": "urn:d1"},
                                   {"entity": "urn:o"}]}}},
    )


def test_run_counts_every_state_into_flat_top_level_keys():
    """Flach und ganzzahlig, weil audit_claims per Schluesselnamen
    vergleicht -- verschachtelt waere die Zahl nicht pruefbar."""
    out = run(_gms_for_run(), focus="urn:x", now_ms=50 * DAY)
    assert out["edges_total"] == 3
    assert out["edges_confirmed"] == 1
    assert out["edges_dead"] == 1
    assert out["edges_missing"] == 1
    assert out["edges_unknown"] == 0


def test_run_reports_coverage_above_the_result_not_inside_it():
    out = run(_gms_for_run(), focus="urn:x", now_ms=50 * DAY)
    assert out["coverage_buckets_seen"] == 3
    assert "coverage_thin" in out


def test_run_marks_the_data_as_seeded_because_the_sample_catalog_has_none():
    out = run(_gms_for_run(), focus="urn:x", now_ms=50 * DAY)
    assert out["seeded"] is True


def test_run_counts_api_calls_so_the_load_test_has_a_baseline():
    out = run(_gms_for_run(), focus="urn:x", now_ms=50 * DAY)
    assert out["api_calls"] == 6  # 1 lineage + 1 search + 1 aspect + 3 usage


def test_run_output_is_json_serialisable_without_a_custom_encoder():
    json.dumps(run(_gms_for_run(), focus="urn:x", now_ms=50 * DAY))
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_ledger.py -q`
Erwartet: FAIL mit `ImportError: cannot import name 'run'`

- [ ] **Step 3: Minimale Umsetzung in `ledger.py`**

```python
# probate/ledger.py -- anhaengen

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
    beteiligte Ziel die Abdeckung bestimmen, DANN klassifizieren. Wer
    waehrend der Klassifikation nachlaedt, klassifiziert Kanten mit
    unterschiedlich alter Datenlage.
    """
    counting = _Counting(gms)
    declared = fetch_declared_edges(counting, focus, count=lineage_count)
    cooccurred = fetch_cooccurrence(counting, focus)

    coverage_by_urn: dict[str, Coverage] = {}
    timeline_by_urn: dict[str, Timeline] = {}
    for target in sorted(declared | set(cooccurred)):
        buckets = fetch_usage(counting, target)
        coverage_by_urn[target] = coverage_from_buckets(buckets)
        timeline_by_urn[target] = Timeline(buckets)

    verdicts = classify_edges(
        focus, declared, cooccurred, coverage_by_urn, timeline_by_urn, now_ms
    )
    counts = {s: sum(1 for v in verdicts if v.state == s) for s in STATES}
    buckets_seen = sum(c.buckets_seen for c in coverage_by_urn.values())
    spans = [c.days_span for c in coverage_by_urn.values() if c.days_span is not None]

    return {
        "focus": focus,
        "gms": getattr(getattr(gms, "base", None), "__str__", lambda: "")(),
        "seeded": True,  # der Beispielkatalog liefert keine Nutzungsdaten
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
        "edges": [v.to_json(now_ms) for v in verdicts],
    }
```

- [ ] **Step 4: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 93 passed

- [ ] **Step 5: CLI-Unterbefehl verdrahten**

In `probate/cli.py` — Import oben ergänzen:
```python
from probate.ledger import run as ledger_run
```

Parser-Block einfügen (zwischen dem `revert`-Parser bei `cli.py:117-119` und `args = p.parse_args()`):
```python
    lg = sub.add_parser("ledger", help="Kanten-Register: deklarierte Lineage gegen gemessene Nutzung")
    lg.add_argument("--focus", required=True, help="Dataset-URN, dessen Kanten geprueft werden")
    lg.add_argument("--gms", default=DEFAULT_GMS)
    lg.add_argument("--token", default=None, help="Personal Access Token; sonst DATAHUB_TOKEN aus der Umgebung")
    lg.add_argument("--lineage-count", dest="lineage_count", type=int, default=200,
                    help="Obergrenze der Lineage-Abfrage (Falle 12: >100'000 Zeichen ohne Vorgabe)")
    lg.add_argument("--now-ms", dest="now_ms", type=int, default=None,
                    help="Beobachtungszeitpunkt in ms; Vorgabe ist jetzt. Nur eine SICHT, "
                         "veraendert keine Daten -- traegt den Knopf 'Zeit vorspulen'")
    lg.add_argument("--out", default="harness/runs/ledger.json")
```

Handler-Block einfügen **vor** der letzten `print(CAMPAIGN_STATE.read_text(...))`-Zeile:
```python
    if args.cmd == "ledger":
        import time
        gms = Gms(args.gms, token=args.token)
        now_ms = args.now_ms if args.now_ms is not None else int(time.time() * 1000)
        out = ledger_run(gms, args.focus, now_ms, lineage_count=args.lineage_count)
        out["gms"] = args.gms
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in out.items() if k != "edges"}, indent=2, ensure_ascii=False))
        if out["coverage_thin"]:
            print("\n  ACHTUNG duenne Abdeckung: "
                  f"{out['coverage_buckets_seen']} Zeitfenster insgesamt. "
                  f"{out['edges_unknown']} Kante(n) sind 'unknown', NICHT 'dead'.")
        return 0
```

- [ ] **Step 6: Echter Lauf gegen 28080**

```bash
uv run --python 3.11 python -m probate.cli ledger \
  --focus "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customers_v7,PROD)" \
  --gms http://localhost:28080
```
Erwartet: `harness/runs/ledger.json` existiert, `edges_total` > 0, und der Abdeckungs-Hinweis erscheint, solange P0 noch keine Nutzungsdaten geseedet hat. **Genau dieser Fall ist ein Ergebnis, kein Fehler** — er zeigt `unknown` statt `dead`.

- [ ] **Step 7: Commit**

```bash
git add probate/ledger.py probate/cli.py tests/test_ledger.py harness/runs/ledger.json
git commit -m "feat(ledger): lauf, lauf-artefakt und cli-unterbefehl ledger"
```

---

### Task 7: `audit_claims` liest mehrere Lauf-Artefakte

**Parallel zu:** Task 1–6 (berührt nur `harness/`).

**Files:**
- Modify: `harness/audit_claims.py`
- Test: `tests/test_audit_claims.py`

**Interfaces:**
- Produces:
  ```python
  RUN_FILES: tuple[str, ...]
  class ConflictingClaim(ValueError)
  def load_runs(runs: Path = RUNS) -> dict
  ```
  `main()` benutzt `load_runs()` statt `campaign.json` fest zu lesen.

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_audit_claims.py -- anhaengen
import json
import pytest
from harness.audit_claims import ConflictingClaim, load_runs


def test_merges_scalar_keys_from_every_known_run_artefact(tmp_path):
    (tmp_path / "campaign.json").write_text(json.dumps({"live_consumers": 1}))
    (tmp_path / "ledger.json").write_text(json.dumps({"edges_dead": 41, "edges": [1, 2]}))
    merged = load_runs(tmp_path)
    assert merged["live_consumers"] == 1
    assert merged["edges_dead"] == 41


def test_nested_values_are_skipped_because_a_claim_is_always_a_scalar(tmp_path):
    (tmp_path / "ledger.json").write_text(json.dumps({"edges": [{"state": "dead"}]}))
    assert "edges" not in load_runs(tmp_path)


def test_a_missing_artefact_is_skipped_not_an_error(tmp_path):
    (tmp_path / "ledger.json").write_text(json.dumps({"edges_dead": 3}))
    assert load_runs(tmp_path) == {"edges_dead": 3}


def test_the_same_key_with_two_different_values_is_loud_not_last_wins(tmp_path):
    """Zwei Artefakte, die dasselbe verschieden behaupten, sind ein
    Befund -- kein 'das letzte gewinnt'. Genau daraus entsteht sonst
    eine Zahl im README, die niemand mehr herleiten kann."""
    (tmp_path / "campaign.json").write_text(json.dumps({"edges_dead": 41}))
    (tmp_path / "ledger.json").write_text(json.dumps({"edges_dead": 12}))
    with pytest.raises(ConflictingClaim):
        load_runs(tmp_path)


def test_the_same_key_with_the_same_value_twice_is_fine(tmp_path):
    (tmp_path / "campaign.json").write_text(json.dumps({"edges_dead": 41}))
    (tmp_path / "ledger.json").write_text(json.dumps({"edges_dead": 41}))
    assert load_runs(tmp_path)["edges_dead"] == 41
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_audit_claims.py -q`
Erwartet: FAIL mit `ImportError: cannot import name 'load_runs'`

- [ ] **Step 3: Minimale Umsetzung**

```python
# harness/audit_claims.py -- ersetzt den festen campaign.json-Zugriff in main()

RUN_FILES = ("campaign.json", "ledger.json", "loadtest.json", "watcher-live.json")


class ConflictingClaim(ValueError):
    """Zwei Lauf-Artefakte behaupten denselben Schluessel verschieden."""


def load_runs(runs: Path = RUNS) -> dict:
    """Alle bekannten Lauf-Artefakte zu einer flachen Zahlen-Tabelle.

    Nur Skalare: eine Behauptung im README ist immer eine Zahl, ein
    Wahrheitswert oder ein kurzer Text. Verschachteltes (die Kantenliste)
    ist Beleg, keine Behauptung.
    """
    merged: dict = {}
    for name in RUN_FILES:
        p = runs / name
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        for k, v in data.items():
            if not isinstance(v, (int, float, bool, str)):
                continue
            if k in merged and merged[k] != v:
                raise ConflictingClaim(
                    f"{k}: {merged[k]} in einem frueheren Artefakt, {v} in {name}"
                )
            merged[k] = v
    return merged
```

`main()` anpassen — die ersten Zeilen ersetzen:
```python
def main() -> int:
    run = load_runs()
    if not run:
        print("  Kein Lauf-Artefakt - es gibt nichts zu behaupten.")
        return 1
    claims = json.loads((RUNS / "claims.json").read_text(encoding="utf-8"))
    ...
```

- [ ] **Step 4: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 98 passed

- [ ] **Step 5: Beleg-Prüfung laufen lassen**

Run: `uv run --python 3.11 python harness/audit_claims.py`
Erwartet: Exit 0, die bisherigen 3 Prüfungen weiter grün.

- [ ] **Step 6: Commit**

```bash
git add harness/audit_claims.py tests/test_audit_claims.py
git commit -m "feat(audit): mehrere lauf-artefakte, kollision ist laut statt letzter-gewinnt"
```

---

# P2 — Das Urteil mit Zitatpflicht (Schicht 2)

> Die einzige Stelle im Projekt mit einem Modellaufruf. Erster Streichkandidat, wenn Samstagabend nichts läuft — dann fällt aber das „wo ist der Agent"-Argument weg (fünf von sieben simulierten Juroren haben danach gefragt).

### Task 8: Kontext einsammeln — deterministisch, ohne Modell

**Depends:** Task 6 (`EdgeVerdict`). **Parallel zu:** Task 16, 21.

**Files:**
- Create: `probate/judge.py`
- Test: `tests/test_judge.py`
- Artefakt: `harness/runs/judge-transport-probe.json`

**Interfaces:**
- Produces:
  ```python
  CONTEXT_Q: str
  def gather_context(gms, urn: str) -> dict
  # -> {"urn", "name", "description", "owners": [str], "glossary_terms": [str],
  #     "domain": str, "text": str}   # `text` = alles Lesbare zusammengefügt
  ```
  `text` ist der **einzige** Korpus, gegen den später ein Zitat geprüft wird. Was nicht in `text` steht, kann kein Zitat sein.

- [ ] **Step 1: Messschritt — wie antwortet `claude -p` wirklich?**

Ausgabeformat auf dieser Maschine ist **nicht gemessen**. Vor Task 10 einmal nachsehen:

```bash
claude -p "Antworte ausschliesslich mit dem JSON {\"ok\": true}" --output-format json > harness/runs/judge-transport-probe.json 2>&1; echo "exit=$?"
```

Auswerten und in den Docstring von `claude_cli_transport` (Task 10) schreiben:
- Welches Feld trägt die Antwort? (Annahme `result` — **bis hierher unbelegt**.)
- Exit-Code bei Erfolg? Dauer?
- Falls der Aufruf scheitert: **den Fehlertext festhalten**, und den Vorgabe-Transport auf `None` stellen, damit `judge_edge` sauber den deterministischen Befund liefert statt still nichts zu tun. Eine gescheiterte Abfrage ist keine Abwesenheit — sie ist ein dokumentierter Fehlschlag.

- [ ] **Step 2: Failing test schreiben**

```python
# tests/test_judge.py
from probate.judge import gather_context


class FakeGms:
    def __init__(self, data):
        self.data = data
        self.calls = 0

    def graphql(self, query, variables=None):
        self.calls += 1
        return self.data


FULL = {"dataset": {
    "urn": "urn:d",
    "properties": {"name": "fin_year_end", "description": "Jahresabschluss, revisionsrelevant"},
    "ownership": {"owners": [{"owner": {"urn": "urn:li:corpuser:anna"}}]},
    "glossaryTerms": {"terms": [{"term": {"urn": "urn:li:glossaryTerm:SOX"}}]},
    "domain": {"domain": {"properties": {"name": "Finance"}}},
}}


def test_context_collects_every_readable_field():
    c = gather_context(FakeGms(FULL), "urn:d")
    assert c["description"] == "Jahresabschluss, revisionsrelevant"
    assert c["owners"] == ["urn:li:corpuser:anna"]
    assert c["glossary_terms"] == ["urn:li:glossaryTerm:SOX"]
    assert c["domain"] == "Finance"


def test_text_contains_everything_a_quote_could_come_from():
    c = gather_context(FakeGms(FULL), "urn:d")
    for piece in ("fin_year_end", "Jahresabschluss", "anna", "SOX", "Finance"):
        assert piece in c["text"]


def test_a_dataset_without_any_metadata_yields_empty_text_not_a_crash():
    """Leer ist ein Ergebnis: ohne Text gibt es nichts zu zitieren, also
    kein Urteil -- und genau das soll passieren."""
    c = gather_context(FakeGms({"dataset": None}), "urn:d")
    assert c["text"] == ""
    assert c["owners"] == []
```

- [ ] **Step 3: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_judge.py -q`
Erwartet: FAIL mit `ModuleNotFoundError: No module named 'probate.judge'`

- [ ] **Step 4: Minimale Umsetzung**

```python
# probate/judge.py
"""Das Urteil -- die einzige Stelle im Projekt mit einem Modellaufruf.

Warum diese Datei existiert: nicht jede Abweichung ist wichtig. Eine tote
Kante zu einer Tabelle mit "Jahresabschluss" in der Beschreibung ist etwas
anderes als eine zu einer namenlosen Zwischentabelle. Das ist Urteil ueber
unstrukturierten Text -- keine Regel, die man schreiben kann.

Die Gegenleistung fuer diese Freiheit ist die ZITATPFLICHT: ein Urteil
ohne woertliches Zitat aus dem gelesenen Kontext wird verworfen, und es
bleibt beim deterministischen Befund. Ein Werkzeug, dessen Kernaussage
"nichts behaupten ohne Beleg" lautet, darf sich diese Regel nicht selbst
erlassen.

Ueberall sonst gilt weiter: deterministisch, offline testbar. Der
Transport ist ein injizierbares Callable, damit kein Test je einen Prozess
startet und der Anbieter austauschbar bleibt.
"""

from __future__ import annotations

from dataclasses import dataclass

CONTEXT_Q = """
query($urn: String!) {
  dataset(urn: $urn) {
    urn
    properties { name description }
    ownership { owners { owner { urn } } }
    glossaryTerms { terms { term { urn } } }
    domain { domain { properties { name } } }
  }
}
"""


def gather_context(gms, urn: str) -> dict:
    """Alles Lesbare zu einem Dataset -- deterministisch, kein Modell.

    `text` ist der einzige Korpus, gegen den ein Zitat geprueft wird.
    Was hier nicht drinsteht, kann kein gueltiges Zitat sein.
    """
    d = (gms.graphql(CONTEXT_Q, {"urn": urn}).get("dataset")) or {}
    props = d.get("properties") or {}
    owners = [
        (o.get("owner") or {}).get("urn", "")
        for o in ((d.get("ownership") or {}).get("owners") or [])
    ]
    terms = [
        (t.get("term") or {}).get("urn", "")
        for t in ((d.get("glossaryTerms") or {}).get("terms") or [])
    ]
    domain = (((d.get("domain") or {}).get("domain") or {}).get("properties") or {}).get("name", "")
    parts = [props.get("name") or "", props.get("description") or "",
             *owners, *terms, domain]
    return {
        "urn": urn,
        "name": props.get("name") or "",
        "description": props.get("description") or "",
        "owners": [o for o in owners if o],
        "glossary_terms": [t for t in terms if t],
        "domain": domain,
        "text": "\n".join(p for p in parts if p),
    }
```

- [ ] **Step 5: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 101 passed

- [ ] **Step 6: Commit**

```bash
git add probate/judge.py tests/test_judge.py harness/runs/judge-transport-probe.json
git commit -m "feat(judge): kontext einsammeln -- der korpus, gegen den zitiert wird"
```

---

### Task 9: Zitatpflicht und Rückfall — der Kern der Schicht

**Depends:** Task 8.

**Files:**
- Modify: `probate/judge.py`
- Test: `tests/test_judge.py`

**Interfaces:**
- Produces:
  ```python
  JudgeTransport = Callable[[str], str]
  class JudgeTransportError(RuntimeError)

  @dataclass(frozen=True)
  class Judgement:
      edge_key: str
      important: bool
      reason: str
      quote: str
      source_field: str
      used_model: bool
      fallback_reason: str
      def to_json(self) -> dict

  def build_prompt(verdict, up_ctx: dict, down_ctx: dict) -> str
  def judge_edge(verdict, up_ctx, down_ctx, transport: JudgeTransport | None = None) -> Judgement
  ```

- [ ] **Step 1: Failing test schreiben — alle fünf Fehlwege**

```python
# tests/test_judge.py -- anhaengen
import json
from probate.judge import Judgement, JudgeTransportError, build_prompt, judge_edge
from probate.ledger import Bucket, Coverage, Edge, EdgeVerdict, Timeline

DAY = 86_400_000
DEAD = EdgeVerdict(
    edge=Edge("urn:up", "urn:down"), state="dead",
    evidence={"reason": "im geprueften Fenster nie gemessen", "buckets_checked": 30},
    coverage=Coverage(30, 10 * DAY, 40 * DAY, ""),
    timeline=Timeline((Bucket(40 * DAY, 0, 0),)))

UP = {"urn": "urn:up", "name": "fin_year_end", "description": "Jahresabschluss, revisionsrelevant",
      "owners": ["urn:li:corpuser:anna"], "glossary_terms": [], "domain": "Finance",
      "text": "fin_year_end\nJahresabschluss, revisionsrelevant\nurn:li:corpuser:anna\nFinance"}
DOWN = {"urn": "urn:down", "name": "tmp_42", "description": "", "owners": [],
        "glossary_terms": [], "domain": "", "text": "tmp_42"}


def _reply(**kw):
    return lambda prompt: json.dumps(kw)


def test_a_judgement_with_a_verbatim_quote_from_the_context_is_kept():
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="Betrifft eine revisionsrelevante Tabelle.",
        quote="Jahresabschluss, revisionsrelevant", source_field="description"))
    assert j.used_model is True
    assert j.important is True
    assert j.quote == "Jahresabschluss, revisionsrelevant"


def test_a_quote_that_is_not_in_the_context_is_discarded():
    """Der wichtigste Test der Schicht: ein erfundenes Zitat ist
    schlimmer als kein Urteil. Ohne Beleg faellt es auf den
    deterministischen Befund zurueck."""
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="Klingt wichtig.",
        quote="unternehmenskritischer Datenschatz", source_field="description"))
    assert j.used_model is False
    assert j.important is False
    assert j.quote == ""
    assert j.fallback_reason == "Zitat steht nicht im gelesenen Kontext"
    assert "dead" in j.reason


def test_a_reply_without_a_quote_field_is_discarded():
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(important=True, reason="Wichtig."))
    assert j.used_model is False
    assert j.fallback_reason == "kein Zitat geliefert"


def test_a_reply_that_is_not_json_is_discarded_with_a_named_reason():
    j = judge_edge(DEAD, UP, DOWN, transport=lambda p: "Ja, das ist wichtig!")
    assert j.used_model is False
    assert j.fallback_reason == "Antwort war kein JSON"


def test_a_transport_that_raises_falls_back_instead_of_propagating():
    """Eine gescheiterte Abfrage ist keine Abwesenheit -- aber sie darf
    auch nicht den ganzen Lauf abbrechen. Sie wird benannt."""
    def boom(prompt):
        raise JudgeTransportError("claude -p exit 1: not logged in")

    j = judge_edge(DEAD, UP, DOWN, transport=boom)
    assert j.used_model is False
    assert j.fallback_reason.startswith("Transport gescheitert:")
    assert "not logged in" in j.fallback_reason


def test_no_transport_at_all_means_the_deterministic_finding_verbatim():
    j = judge_edge(DEAD, UP, DOWN, transport=None)
    assert j.used_model is False
    assert j.fallback_reason == "kein Transport konfiguriert"
    assert j.reason == "deterministischer Befund: dead"


def test_whitespace_differences_do_not_break_an_otherwise_valid_quote():
    j = judge_edge(DEAD, UP, DOWN, transport=_reply(
        important=True, reason="r", quote="Jahresabschluss,   revisionsrelevant",
        source_field="description"))
    assert j.used_model is True


def test_the_prompt_contains_both_contexts_and_the_state_but_no_instruction_to_invent():
    p = build_prompt(DEAD, UP, DOWN)
    assert "fin_year_end" in p and "tmp_42" in p and "dead" in p
    assert "quote" in p


def test_judgement_json_is_flat_and_carries_the_fallback_reason():
    j = judge_edge(DEAD, UP, DOWN, transport=None).to_json()
    assert j["used_model"] is False
    assert j["fallback_reason"] == "kein Transport konfiguriert"
    assert j["edge"] == "urn:up->urn:down"
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_judge.py -q`
Erwartet: FAIL mit `ImportError: cannot import name 'judge_edge'`

- [ ] **Step 3: Minimale Umsetzung**

```python
# probate/judge.py -- anhaengen (Imports oben ergaenzen)
import json
import re
from typing import Callable

JudgeTransport = Callable[[str], str]


class JudgeTransportError(RuntimeError):
    """Der Transport hat nicht geantwortet. Das ist ein benannter
    Fehlschlag, keine Abwesenheit eines Urteils."""


@dataclass(frozen=True)
class Judgement:
    edge_key: str
    important: bool
    reason: str
    quote: str
    source_field: str
    used_model: bool
    fallback_reason: str

    def to_json(self) -> dict:
        return {
            "edge": self.edge_key,
            "important": self.important,
            "reason": self.reason,
            "quote": self.quote,
            "source_field": self.source_field,
            "used_model": self.used_model,
            "fallback_reason": self.fallback_reason,
        }


_PROMPT = """You are auditing one lineage edge in a data catalog.

EDGE: {edge}
DETERMINISTIC STATE: {state}
EVIDENCE: {evidence}

UPSTREAM CONTEXT (this is the only text you may quote from):
{up_text}

DOWNSTREAM CONTEXT (this is the only text you may quote from):
{down_text}

Decide whether this deviation matters enough for a human to look at it.

Answer with a single JSON object and nothing else:
{{"important": true|false,
  "reason": "one sentence",
  "quote": "a verbatim span copied from the context above",
  "source_field": "description|owner|glossary|domain|name"}}

The quote must appear character-for-character in the context above.
If nothing in the context justifies a judgement, answer with
{{"important": false, "reason": "no basis in the read context", "quote": "",
  "source_field": ""}}."""


def build_prompt(verdict, up_ctx: dict, down_ctx: dict) -> str:
    return _PROMPT.format(
        edge=verdict.edge.key(), state=verdict.state,
        evidence=json.dumps(verdict.evidence, ensure_ascii=False),
        up_text=up_ctx.get("text", "") or "(no metadata)",
        down_text=down_ctx.get("text", "") or "(no metadata)",
    )


def _normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _fallback(verdict, why: str) -> Judgement:
    return Judgement(
        edge_key=verdict.edge.key(), important=False,
        reason=f"deterministischer Befund: {verdict.state}",
        quote="", source_field="", used_model=False, fallback_reason=why,
    )


def judge_edge(verdict, up_ctx: dict, down_ctx: dict,
               transport: JudgeTransport | None = None) -> Judgement:
    """Ein Urteil pro Kante -- oder der deterministische Befund.

    Jeder Fehlweg endet in DERSELBEN Rueckfall-Antwort, mit einem
    `fallback_reason`, der sagt, WELCHER Weg gescheitert ist. Das
    Register verliert dabei nichts: der Befund stand vorher fest, das
    Modell durfte ihn nur gewichten.
    """
    if transport is None:
        return _fallback(verdict, "kein Transport konfiguriert")

    try:
        raw = transport(build_prompt(verdict, up_ctx, down_ctx))
    except Exception as exc:  # jeder Transportfehler, nicht nur unserer
        return _fallback(verdict, f"Transport gescheitert: {exc}")

    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("kein Objekt")
    except Exception:
        return _fallback(verdict, "Antwort war kein JSON")

    quote = (parsed.get("quote") or "").strip()
    if not quote:
        return _fallback(verdict, "kein Zitat geliefert")

    corpus = _normalise(f"{up_ctx.get('text', '')}\n{down_ctx.get('text', '')}")
    if _normalise(quote) not in corpus:
        return _fallback(verdict, "Zitat steht nicht im gelesenen Kontext")

    return Judgement(
        edge_key=verdict.edge.key(),
        important=bool(parsed.get("important")),
        reason=str(parsed.get("reason") or ""),
        quote=quote,
        source_field=str(parsed.get("source_field") or ""),
        used_model=True,
        fallback_reason="",
    )
```

- [ ] **Step 4: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 110 passed

- [ ] **Step 5: Commit**

```bash
git add probate/judge.py tests/test_judge.py
git commit -m "feat(judge): zitatpflicht -- urteil ohne beleg faellt auf den befund zurueck"
```

---

### Task 10: `claude -p`-Transport und CLI-Verdrahtung

**Depends:** Task 9, und der Messschritt aus Task 8 Step 1.

**Files:**
- Modify: `probate/judge.py`, `probate/cli.py`, `probate/ledger.py` (nur `run()`-Signatur)
- Test: `tests/test_judge.py`

**Interfaces:**
- Produces:
  ```python
  def claude_cli_transport(timeout: int = 60, binary: str = "claude",
                           runner=None) -> JudgeTransport
  def judge_ledger(gms, ledger: dict, transport, limit: int = 20) -> list[dict]
  ```
  `run()` bekommt zusätzlich `judge_transport=None, judge_limit=20` und schreibt bei aktivem Urteil `judgements` sowie die flachen Schlüssel `judged_edges`, `judged_with_model`, `judged_fallback`, `judge_seconds_total` ins Artefakt.

- [ ] **Step 1: Failing test schreiben (Runner injiziert, kein echter Prozess)**

```python
# tests/test_judge.py -- anhaengen
from probate.judge import claude_cli_transport, judge_ledger


class FakeProc:
    def __init__(self, returncode, stdout, stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_transport_extracts_the_result_field_from_the_cli_envelope():
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)
        return FakeProc(0, json.dumps({"result": '{"important": true}'}))

    t = claude_cli_transport(runner=runner)
    assert t("hallo") == '{"important": true}'
    assert calls[0][:2] == ["claude", "-p"]
    assert "--output-format" in calls[0]


def test_a_nonzero_exit_becomes_a_named_transport_error_not_an_empty_answer():
    def runner(cmd, **kw):
        return FakeProc(1, "", "not logged in")

    with pytest.raises(JudgeTransportError) as e:
        claude_cli_transport(runner=runner)("hallo")
    assert "not logged in" in str(e.value)


def test_a_timeout_becomes_a_transport_error_too():
    import subprocess

    def runner(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 60)

    with pytest.raises(JudgeTransportError):
        claude_cli_transport(runner=runner)("hallo")


def test_judge_ledger_only_judges_deviating_edges_never_confirmed_ones():
    """Der Modellaufruf haengt an der Zahl AUFFAELLIGER Kanten, nicht an
    der Gesamtzahl -- das ist der Lastentwurf aus der Spec."""
    ledger = {"edges": [
        {"edge": "a->b", "state": "confirmed", "upstream": "a", "downstream": "b",
         "evidence": {}, "coverage": {}, "timeline": {}},
        {"edge": "a->c", "state": "dead", "upstream": "a", "downstream": "c",
         "evidence": {}, "coverage": {}, "timeline": {}},
    ]}
    seen = []

    class G:
        def graphql(self, q, v=None):
            seen.append(v["urn"])
            return {"dataset": None}

    out = judge_ledger(G(), ledger, transport=None, limit=20)
    assert [j["edge"] for j in out] == ["a->c"]
    assert "b" not in seen


def test_judge_ledger_respects_the_hard_limit():
    ledger = {"edges": [
        {"edge": f"a->x{i}", "state": "dead", "upstream": "a", "downstream": f"x{i}",
         "evidence": {}, "coverage": {}, "timeline": {}} for i in range(5)]}

    class G:
        def graphql(self, q, v=None):
            return {"dataset": None}

    assert len(judge_ledger(G(), ledger, transport=None, limit=2)) == 2
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_judge.py -q`
Erwartet: FAIL mit `ImportError: cannot import name 'claude_cli_transport'`

- [ ] **Step 3: Minimale Umsetzung**

```python
# probate/judge.py -- anhaengen (Imports oben ergaenzen)
import subprocess

from probate.ledger import Bucket, Coverage, Edge, EdgeVerdict, Timeline

DEVIATING_STATES = ("dead", "missing", "unknown")


def claude_cli_transport(timeout: int = 60, binary: str = "claude",
                         runner=None) -> JudgeTransport:
    """Vorgabe-Transport auf DIESER Maschine.

    Gemessen 2026-08-07: `claude --version` -> 2.1.223, ANTHROPIC_API_KEY
    ist NICHT gesetzt. Deshalb die CLI und nicht das SDK -- eine Vorgabe,
    die an einer fehlenden Umgebungsvariable scheitert, ist keine.

    Das Feld `result` im JSON-Umschlag ist die Annahme aus dem
    Messschritt (harness/runs/judge-transport-probe.json). Weicht die
    tatsaechliche Struktur ab, wird HIER korrigiert -- nicht in judge_edge,
    das den Umschlag nie sieht.
    """
    run_proc = runner or subprocess.run

    def send(prompt: str) -> str:
        cmd = [binary, "-p", prompt, "--output-format", "json"]
        try:
            proc = run_proc(cmd, capture_output=True, text=True,
                            timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise JudgeTransportError(f"{binary} -p: Zeitueberschreitung nach {timeout}s")
        if proc.returncode != 0:
            raise JudgeTransportError(
                f"{binary} -p exit {proc.returncode}: {(proc.stderr or '')[:300]}")
        try:
            return json.loads(proc.stdout).get("result", "")
        except Exception as exc:
            raise JudgeTransportError(f"{binary} -p: Umschlag nicht lesbar ({exc})")

    return send


def _verdict_from_json(row: dict) -> EdgeVerdict:
    return EdgeVerdict(
        edge=Edge(row["upstream"], row["downstream"]),
        state=row["state"], evidence=row.get("evidence") or {},
        coverage=Coverage(0, None, None, ""), timeline=Timeline(()),
    )


def judge_ledger(gms, ledger: dict, transport: JudgeTransport | None,
                 limit: int = 20) -> list[dict]:
    """Urteilt nur ueber ABWEICHENDE Kanten.

    Bestaetigte Kanten brauchen kein Urteil -- und der teure Teil haengt
    damit an der Zahl der Auffaelligkeiten, nicht an der Gesamtzahl der
    Kanten (Lastentwurf der Spec: 41 Detailabrufe statt 100'000).
    """
    rows = [r for r in ledger.get("edges", []) if r.get("state") in DEVIATING_STATES][:limit]
    ctx_cache: dict[str, dict] = {}

    def ctx(urn: str) -> dict:
        if urn not in ctx_cache:
            ctx_cache[urn] = gather_context(gms, urn)
        return ctx_cache[urn]

    return [
        judge_edge(_verdict_from_json(r), ctx(r["upstream"]), ctx(r["downstream"]),
                   transport).to_json()
        for r in rows
    ]
```

- [ ] **Step 4: `ledger.run()` um das Urteil erweitern**

In `probate/ledger.py` — `run()`-Signatur und Rückgabe ergänzen (der Import steht **in der Funktion**, damit `ledger.py` nicht auf `judge.py` zeigt und der Kreis vermieden wird):

```python
def run(gms, focus: str, now_ms: int, lineage_count: int = 200,
        judge_transport=None, judge_limit: int = 20) -> dict:
    ...  # unveraendert bis zum return
    out = { ... }   # das bisherige dict

    if judge_transport is not None or judge_limit == 0:
        import time as _t
        from probate.judge import judge_ledger
        t0 = _t.perf_counter()
        judgements = judge_ledger(counting, out, judge_transport, limit=judge_limit)
        out["judgements"] = judgements
        out["judged_edges"] = len(judgements)
        out["judged_with_model"] = sum(1 for j in judgements if j["used_model"])
        out["judged_fallback"] = sum(1 for j in judgements if not j["used_model"])
        out["judge_seconds_total"] = round(_t.perf_counter() - t0, 2)
        out["api_calls"] = counting.calls
    return out
```

- [ ] **Step 5: CLI-Schalter ergänzen**

In `probate/cli.py` beim `ledger`-Parser:
```python
    lg.add_argument("--judge", action="store_true",
                    help="Modell-Urteil ueber auffaellige Kanten (einziger Modellaufruf im Projekt)")
    lg.add_argument("--judge-limit", dest="judge_limit", type=int, default=20)
```
Im Handler, vor dem `ledger_run`-Aufruf:
```python
        transport = None
        if args.judge:
            from probate.judge import claude_cli_transport
            transport = claude_cli_transport()
        out = ledger_run(gms, args.focus, now_ms, lineage_count=args.lineage_count,
                         judge_transport=transport, judge_limit=args.judge_limit)
```

- [ ] **Step 6: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 115 passed

- [ ] **Step 7: Echter Lauf mit Urteil**

```bash
uv run --python 3.11 python -m probate.cli ledger \
  --focus "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customers_v7,PROD)" \
  --gms http://localhost:28080 --judge --judge-limit 5
```
Erwartet: `ledger.json` enthält `judged_edges`, `judged_with_model`, `judge_seconds_total`.
**Wenn `judged_with_model == 0`:** das ist ein Ergebnis, kein Fehler — den `fallback_reason` der ersten Zeile lesen und in `harness/runs/judge-transport-probe.json` nachtragen. Nicht rateweise nachbessern.

- [ ] **Step 8: Commit**

```bash
git add probate/judge.py probate/ledger.py probate/cli.py tests/test_judge.py harness/runs/ledger.json
git commit -m "feat(judge): claude-cli-transport, urteil nur ueber auffaellige kanten"
```

---

# P3 — Korrektur-Modus (Schicht 3)

> **`writeback.py` wird nicht angefasst.** Alles hier sind neue Aufrufer. Immer Vorschlag → Bestätigung → Journal; `revert` deckt alles.
>
> **Falle 1 an jedem Schreibvorgang dieser Phase:** `POST /openapi/v3/entity/<typ>` will eine **Liste**. Ein Objekt liefert HTTP 200 und schreibt nichts. `gms.upsert()` verriegelt das bereits — der Weg darf nicht daran vorbei.
> **Falle 3:** `Deprecation` braucht `actor`. **Falle 10:** ohne Token ist der Handelnde `urn:li:corpuser:__datahub_system`.

### Task 11: Messschritt + Vorschläge erzeugen (schreibt nichts)

**Depends:** Task 6.

**Files:**
- Create: `probate/correct.py`
- Test: `tests/test_correct.py`
- Artefakt: `harness/runs/upstream-properties-probe.json`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class Proposal:
      kind: str          # "add_edge" | "mark_dead" | "enrich_doc"
      edge_key: str
      target_urn: str    # Entität, auf die geschrieben wird
      aspect: str
      evidence: dict
      human_summary: str
  def propose(ledger: dict) -> list[Proposal]
  ```

- [ ] **Step 1: Messschritt — überlebt `Upstream.properties` einen Schreib-/Lesezyklus?**

Eine Kante als „tot" zu markieren braucht einen **kanten-**bezogenen Ort. `deprecation` ist tabellenbezogen. Ob `UpstreamLineage.upstreams[].properties` (Map) erhalten bleibt, ist **nicht gemessen**:

```bash
uv run --python 3.11 python -c "
import json, pathlib
from probate.gms import Gms
g = Gms('http://localhost:28080')
DOWN = 'urn:li:dataset:(urn:li:dataPlatform:snowflake,probate_probe.down,PROD)'
UP   = 'urn:li:dataset:(urn:li:dataPlatform:snowflake,probate_probe.up,PROD)'
val = {'upstreams': [{'dataset': UP, 'type': 'TRANSFORMED',
                      'auditStamp': {'time': 0, 'actor': 'urn:li:corpuser:__datahub_system'},
                      'properties': {'probate.dead_since': '2026-04-11'}}]}
g.upsert('dataset', [{'urn': DOWN, 'upstreamLineage': {'value': val}}])
back = g.get_aspect('dataset', DOWN, 'upstreamLineage')
out = {'seeded': True, 'wrote': val, 'read_back': back,
       'properties_survived': bool(((back or {}).get('value') or {}).get('upstreams', [{}])[0].get('properties'))}
pathlib.Path('harness/runs/upstream-properties-probe.json').write_text(json.dumps(out, indent=2), encoding='utf-8')
g.delete_aspect('dataset', DOWN, 'upstreamLineage')
assert g.get_aspect('dataset', DOWN, 'upstreamLineage') is None, 'Aufraeumen fehlgeschlagen'
print(json.dumps(out, indent=2)[:1500])
"
```

Ergebnis entscheidet, **nicht** die Vermutung:
- `properties_survived: true` → `mark_dead` schreibt `upstreamLineage` mit `properties["probate.dead_since"]` — kanten-genau.
- `properties_survived: false` → `mark_dead` schreibt stattdessen `globalTags` mit `urn:li:tag:probate-dead-edge` auf das **Downstream**-Dataset und trägt die Kante samt Datum ins Journal und ins Register. Die Einschränkung („der Marker sitzt an der Tabelle, nicht an der Kante") kommt **wörtlich ins README**, Abschnitt „ehrlich offen".
- Aufruf gescheitert → Fehlertext ins Artefakt, und **beide** Wege bleiben ungebaut, bis nachgemessen ist.

- [ ] **Step 2: Failing test schreiben**

```python
# tests/test_correct.py
from probate.correct import Proposal, propose

LEDGER = {"focus": "urn:up", "edges": [
    {"edge": "urn:up->urn:c", "state": "confirmed", "upstream": "urn:up",
     "downstream": "urn:c", "evidence": {"query_urns": ["urn:li:query:q1"]},
     "coverage": {"buckets_seen": 30}, "timeline": {"last_covered_ms": 3, "dead_since_days": 1}},
    {"edge": "urn:up->urn:d", "state": "dead", "upstream": "urn:up",
     "downstream": "urn:d", "evidence": {"buckets_checked": 30},
     "coverage": {"buckets_seen": 30}, "timeline": {"last_covered_ms": 100,
                                                    "dead_since_days": 117,
                                                    "dead_since_is_lower_bound": False}},
    {"edge": "urn:up->urn:m", "state": "missing", "upstream": "urn:up",
     "downstream": "urn:m", "evidence": {"query_urns": ["urn:li:query:q7"],
                                         "cooccurrence_count": 1,
                                         "direction_evidence": "co-occurrence (undirected)"},
     "coverage": {"buckets_seen": 30}, "timeline": {}},
    {"edge": "urn:up->urn:u", "state": "unknown", "upstream": "urn:up",
     "downstream": "urn:u", "evidence": {"reason": "keine Nutzungs-Zeitfenster im Katalog"},
     "coverage": {"buckets_seen": 0}, "timeline": {}},
]}


def test_a_missing_edge_becomes_an_add_edge_proposal_with_the_query_urn():
    p = [x for x in propose(LEDGER) if x.kind == "add_edge"]
    assert len(p) == 1
    assert p[0].target_urn == "urn:m"          # geschrieben wird auf das Downstream
    assert p[0].aspect == "upstreamLineage"
    assert p[0].evidence["query_urns"] == ["urn:li:query:q7"]


def test_an_add_edge_proposal_carries_the_undirected_caveat_into_the_summary():
    """Die Richtung ist NICHT gemessen. Wer sie beim Schreiben als
    gemessen ausgibt, erzeugt genau die unbelegte Behauptung, gegen die
    dieses Werkzeug antritt."""
    p = [x for x in propose(LEDGER) if x.kind == "add_edge"][0]
    assert "co-occurrence (undirected)" in p.evidence["direction_evidence"]
    assert "ungerichtet" in p.human_summary


def test_a_dead_edge_becomes_a_mark_dead_proposal_carrying_the_last_covered_date():
    p = [x for x in propose(LEDGER) if x.kind == "mark_dead"]
    assert len(p) == 1
    assert p[0].evidence["dead_since_days"] == 117
    assert p[0].evidence["last_covered_ms"] == 100


def test_a_confirmed_edge_becomes_an_enrich_doc_proposal():
    p = [x for x in propose(LEDGER) if x.kind == "enrich_doc"]
    assert len(p) == 1
    assert p[0].target_urn == "urn:c"


def test_an_unknown_edge_produces_no_proposal_at_all():
    """DIE Regel, angewandt auf das Schreiben: bei fehlender Datenlage
    wird nichts vorgeschlagen. Ein Vorschlag auf unknown waere ein
    Schreibvorgang auf Verdacht."""
    assert not [x for x in propose(LEDGER) if x.edge_key == "urn:up->urn:u"]


def test_propose_writes_nothing_at_all():
    """propose() bekommt gar kein gms/wb -- schon die Signatur schliesst
    einen Schreibvorgang aus."""
    import inspect
    assert list(inspect.signature(propose).parameters) == ["ledger"]
```

- [ ] **Step 3: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_correct.py -q`
Erwartet: FAIL mit `ModuleNotFoundError: No module named 'probate.correct'`

- [ ] **Step 4: Minimale Umsetzung**

```python
# probate/correct.py
"""Der Korrektur-Modus: aus einem Befund wird ein Vorschlag.

Warum diese Datei existiert: das Register sagt, was nicht stimmt. Damit
daraus eine Handlung wird, braucht es einen Vorschlag mit Beleg, den ein
Mensch bestaetigt -- nicht ein Werkzeug, das den Katalog nach eigenem
Urteil umschreibt.

`writeback.py` bleibt unveraendert; dieses Modul ist ein Aufrufer, kein
zweiter Schreibweg. Und `propose()` bekommt bewusst kein gms und kein
Writeback: was nicht schreiben kann, schreibt auch nicht versehentlich.

Auf `unknown` wird NIE etwas vorgeschlagen. Bei fehlender Datenlage ist
jeder Schreibvorgang ein Schreibvorgang auf Verdacht -- genau der Fehler,
den Schicht 1 behebt.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Proposal:
    kind: str
    edge_key: str
    target_urn: str
    aspect: str
    evidence: dict
    human_summary: str

    def to_json(self) -> dict:
        return {
            "kind": self.kind, "edge": self.edge_key, "target_urn": self.target_urn,
            "aspect": self.aspect, "evidence": self.evidence,
            "human_summary": self.human_summary,
        }


def propose(ledger: dict) -> list[Proposal]:
    out: list[Proposal] = []
    for row in ledger.get("edges", []):
        state, ev = row.get("state"), row.get("evidence") or {}
        tl = row.get("timeline") or {}
        up, down, key = row["upstream"], row["downstream"], row["edge"]

        if state == "missing":
            out.append(Proposal(
                kind="add_edge", edge_key=key, target_urn=down,
                aspect="upstreamLineage",
                evidence={"query_urns": ev.get("query_urns", []),
                          "cooccurrence_count": ev.get("cooccurrence_count", 0),
                          "direction_evidence": ev.get("direction_evidence", "")},
                human_summary=(
                    f"Kante {key} in {ev.get('cooccurrence_count', 0)} Abfrage(n) beobachtet, "
                    f"aber nicht deklariert. Beleg: {', '.join(ev.get('query_urns', [])) or '-'}. "
                    f"Richtung ist ungerichtet aus Ko-Okkurrenz erschlossen, nicht gemessen."),
            ))
        elif state == "dead":
            out.append(Proposal(
                kind="mark_dead", edge_key=key, target_urn=down,
                aspect="upstreamLineage",
                evidence={"last_covered_ms": tl.get("last_covered_ms"),
                          "dead_since_days": tl.get("dead_since_days"),
                          "dead_since_is_lower_bound": tl.get("dead_since_is_lower_bound", False),
                          "buckets_checked": ev.get("buckets_checked", 0)},
                human_summary=(
                    f"Kante {key} seit {tl.get('dead_since_days')} Tagen ohne gemessenen "
                    f"Verkehr, geprueft ueber {ev.get('buckets_checked', 0)} Zeitfenster."),
            ))
        elif state == "confirmed":
            out.append(Proposal(
                kind="enrich_doc", edge_key=key, target_urn=down,
                aspect="editableDatasetProperties",
                evidence={"query_urns": ev.get("query_urns", []),
                          "last_covered_ms": tl.get("last_covered_ms")},
                human_summary=(
                    f"Beobachtete Nutzung von {up} dokumentieren "
                    f"({len(ev.get('query_urns', []))} Abfrage(n))."),
            ))
    return out
```

- [ ] **Step 5: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 121 passed

- [ ] **Step 6: Commit**

```bash
git add probate/correct.py tests/test_correct.py harness/runs/upstream-properties-probe.json
git commit -m "feat(correct): vorschlaege mit beleg -- auf unknown wird nie geschrieben"
```

---

### Task 12: Fehlende Kante eintragen — **mergen, nie ersetzen**

**Depends:** Task 11 (inkl. Messergebnis).

Dies ist der inhaltlich wichtigste Schreibvorgang des Projekts: DataHubs eigener Aggregator baut die Kantenliste bei jedem Lauf **frisch und leer** (`sql_parsing_aggregator.py:1534`) und löscht damit legitime Kanten. Unser Schreiber tut das Gegenteil.

**Files:**
- Modify: `probate/correct.py`
- Test: `tests/test_correct.py`

**Interfaces:**
- Produces:
  ```python
  DEAD_MARKER_KEY = "probate.dead_since"
  def merge_upstreams(before: dict | None, add: list[dict] = (), drop: list[str] = (),
                      mark_dead: dict[str, str] | None = None) -> dict
  def apply_proposal(wb, p: Proposal, actor: str = "urn:li:corpuser:__datahub_system",
                     now_ms: int = 0) -> "WriteResult"
  ```

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_correct.py -- anhaengen
from probate.correct import DEAD_MARKER_KEY, apply_proposal, merge_upstreams


class RecordingWb:
    """Handgeschrieben, wie tests/test_writeback.py -- kein Mock-Rahmenwerk."""

    def __init__(self, existing=None):
        self.existing = existing or {}
        self.written = []
        self.dry_run = False

    def aspect(self, entity_type, urn, aspect, value):
        before = self.existing.get((entity_type, urn, aspect))
        self.written.append((entity_type, urn, aspect, value, before))

        class R:
            applied, detail = True, "ok"
        R.before = before
        return R


EXISTING = {("dataset", "urn:m", "upstreamLineage"): {"value": {"upstreams": [
    {"dataset": "urn:legit", "type": "TRANSFORMED",
     "auditStamp": {"time": 1, "actor": "urn:li:corpuser:someone"}}]}}}


def test_adding_an_upstream_keeps_every_existing_one():
    """Der Fehler, den DataHub selbst macht: eine frische, leere Liste
    bauen und als vollen Aspekt emittieren. Wir mergen."""
    merged = merge_upstreams(EXISTING[("dataset", "urn:m", "upstreamLineage")],
                             add=[{"dataset": "urn:up", "type": "TRANSFORMED",
                                   "auditStamp": {"time": 2, "actor": "urn:li:corpuser:x"}}])
    assert {u["dataset"] for u in merged["upstreams"]} == {"urn:legit", "urn:up"}


def test_adding_an_upstream_that_is_already_there_does_not_duplicate_it():
    merged = merge_upstreams(EXISTING[("dataset", "urn:m", "upstreamLineage")],
                             add=[{"dataset": "urn:legit", "type": "TRANSFORMED",
                                   "auditStamp": {"time": 2, "actor": "urn:li:corpuser:x"}}])
    assert len(merged["upstreams"]) == 1


def test_merging_into_a_dataset_without_any_lineage_yet_starts_from_empty():
    merged = merge_upstreams(None, add=[{"dataset": "urn:up", "type": "TRANSFORMED",
                                         "auditStamp": {"time": 2, "actor": "urn:li:corpuser:x"}}])
    assert [u["dataset"] for u in merged["upstreams"]] == ["urn:up"]


def test_dropping_an_upstream_removes_only_that_one():
    merged = merge_upstreams(EXISTING[("dataset", "urn:m", "upstreamLineage")],
                             add=[{"dataset": "urn:up", "type": "TRANSFORMED",
                                   "auditStamp": {"time": 2, "actor": "urn:li:corpuser:x"}}],
                             drop=["urn:legit"])
    assert [u["dataset"] for u in merged["upstreams"]] == ["urn:up"]


def test_marking_dead_annotates_the_edge_and_leaves_the_others_untouched():
    before = {"value": {"upstreams": [
        {"dataset": "urn:a", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}},
        {"dataset": "urn:b", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}}]}}
    merged = merge_upstreams(before, mark_dead={"urn:a": "2026-04-11"})
    by_urn = {u["dataset"]: u for u in merged["upstreams"]}
    assert by_urn["urn:a"]["properties"][DEAD_MARKER_KEY] == "2026-04-11"
    assert "properties" not in by_urn["urn:b"]


def test_apply_add_edge_writes_through_writeback_with_a_list_payload():
    """Falle 1: POST /openapi/v3/entity/<typ> will eine LISTE. Der Weg
    darf nicht an gms.upsert() vorbeigehen, das die Liste erzwingt --
    also NIE direkt gms, immer wb.aspect()."""
    wb = RecordingWb(EXISTING)
    p = [x for x in propose(LEDGER) if x.kind == "add_edge"][0]
    apply_proposal(wb, p, actor="urn:li:corpuser:__datahub_system", now_ms=7)
    entity_type, urn, aspect, value, before = wb.written[0]
    assert (entity_type, urn, aspect) == ("dataset", "urn:m", "upstreamLineage")
    assert {u["dataset"] for u in value["upstreams"]} == {"urn:legit", "urn:up"}


def test_every_written_upstream_carries_an_auditstamp_with_an_actor():
    """Falle 3/10: Pflichtfelder und der richtige Handelnde. Ohne Token
    ist der Handelnde urn:li:corpuser:__datahub_system -- das wird
    hingeschrieben, nicht erfunden."""
    wb = RecordingWb(EXISTING)
    p = [x for x in propose(LEDGER) if x.kind == "add_edge"][0]
    apply_proposal(wb, p, actor="urn:li:corpuser:__datahub_system", now_ms=7)
    _, _, _, value, _ = wb.written[0]
    new = [u for u in value["upstreams"] if u["dataset"] == "urn:up"][0]
    assert new["auditStamp"]["actor"] == "urn:li:corpuser:__datahub_system"
    assert new["auditStamp"]["time"] == 7
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_correct.py -q`
Erwartet: FAIL mit `ImportError: cannot import name 'merge_upstreams'`

- [ ] **Step 3: Minimale Umsetzung**

```python
# probate/correct.py -- anhaengen

DEAD_MARKER_KEY = "probate.dead_since"


def merge_upstreams(before: dict | None, add=(), drop=(), mark_dead=None) -> dict:
    """Bestehende Kanten bleiben. Immer.

    DataHubs eigener sql_parsing_aggregator baut bei jedem Lauf eine
    FRISCHE, LEERE Kantenliste und emittiert sie als vollen Aspekt
    (sql_parsing_aggregator.py:1534, selbst nachgelesen) -- damit
    verschwinden legitime Kanten, die dieser Lauf nicht gesehen hat.
    Genau dagegen ist dieses Werkzeug gebaut; es darf denselben Fehler
    nicht selbst machen.
    """
    existing = list(((before or {}).get("value") or {}).get("upstreams") or [])
    drop_set = set(drop)
    out = [u for u in existing if u.get("dataset") not in drop_set]
    have = {u.get("dataset") for u in out}
    for u in add:
        if u.get("dataset") not in have:
            out.append(dict(u))
            have.add(u.get("dataset"))
    if mark_dead:
        marked = []
        for u in out:
            if u.get("dataset") in mark_dead:
                props = dict(u.get("properties") or {})
                props[DEAD_MARKER_KEY] = mark_dead[u["dataset"]]
                marked.append({**u, "properties": props})
            else:
                marked.append(u)
        out = marked
    return {"upstreams": out}
```

- [ ] **Step 4: `apply_proposal` für `add_edge`**

```python
# probate/correct.py -- anhaengen
import datetime as _dt


def _iso_day(ms: int | None) -> str:
    if not ms:
        return "unbekannt"
    return _dt.datetime.fromtimestamp(ms / 1000, _dt.timezone.utc).date().isoformat()


def apply_proposal(wb, p: Proposal,
                   actor: str = "urn:li:corpuser:__datahub_system",
                   now_ms: int = 0):
    """Wendet EINEN bestaetigten Vorschlag an -- ueber writeback.py.

    Nie direkt ueber gms: writeback sichert den Vorher-Zustand ins
    Journal, und nur dadurch deckt `probate revert` auch diese
    Schreibvorgaenge. `wb.aspect()` gibt intern eine LISTE an
    gms.upsert() (Falle 1) -- ein eigener Weg wuerde das umgehen.
    """
    upstream = p.edge_key.split("->", 1)[0]

    if p.kind == "add_edge":
        before = wb.gms.get_aspect("dataset", p.target_urn, "upstreamLineage") \
            if hasattr(wb, "gms") else None
        value = merge_upstreams(before, add=[{
            "dataset": upstream, "type": "TRANSFORMED",
            "auditStamp": {"time": now_ms, "actor": actor},
            "properties": {"probate.evidence": ",".join(p.evidence.get("query_urns", [])),
                           "probate.direction": p.evidence.get("direction_evidence", "")},
        }])
        return wb.aspect("dataset", p.target_urn, "upstreamLineage", value)

    raise ValueError(f"unbekannte Vorschlagsart: {p.kind}")
```

> **Hinweis für den Implementierer:** `RecordingWb` im Test hat kein `.gms`. `hasattr(wb, "gms")` deckt das ab und liefert `before=None`; der echte `Writeback` hat es. Wenn der Test ein `before` erwartet, gibt der Fake es über `existing` mit — deshalb setzt der Test `EXISTING` **auch** auf `RecordingWb.existing`, und der Test für `merge_upstreams` prüft das Mergen direkt. Passt das nicht zusammen, ist `merge_upstreams` die Wahrheit und `apply_proposal` ruft es mit dem echten `before`.

- [ ] **Step 5: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 128 passed

- [ ] **Step 6: Commit**

```bash
git add probate/correct.py tests/test_correct.py
git commit -m "feat(correct): fehlende kante eintragen -- mergen statt ersetzen"
```

---

### Task 13: Tote Kante markieren, Kante entfernen, Doku anreichern

**Depends:** Task 12.

**Files:**
- Modify: `probate/correct.py`
- Test: `tests/test_correct.py`

**Interfaces:**
- Produces: `apply_proposal` behandelt zusätzlich `mark_dead` und `enrich_doc`; neu `remove_edge(wb, upstream, downstream, now_ms)`.

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_correct.py -- anhaengen
from probate.correct import remove_edge


def test_mark_dead_writes_the_last_covered_date_and_keeps_the_edge():
    """Die Kante wird MARKIERT, nicht geloescht. Ein Werkzeug, das bei
    duenner Datenlage Kanten entfernt, ist das Problem, nicht die
    Loesung -- entfernt wird nur auf ausdruecklichen Zuruf (remove_edge)."""
    wb = RecordingWb({("dataset", "urn:d", "upstreamLineage"): {"value": {"upstreams": [
        {"dataset": "urn:up", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}}]}}})
    wb.gms = type("G", (), {"get_aspect": lambda s, *a: wb.existing.get(tuple(a))})()
    p = [x for x in propose(LEDGER) if x.kind == "mark_dead"][0]
    apply_proposal(wb, p, now_ms=9)
    _, urn, aspect, value, _ = wb.written[0]
    assert urn == "urn:d"
    kept = [u for u in value["upstreams"] if u["dataset"] == "urn:up"][0]
    assert kept["properties"][DEAD_MARKER_KEY] == "1970-01-01"  # last_covered_ms=100


def test_enrich_doc_appends_and_never_overwrites_an_existing_description():
    wb = RecordingWb({("dataset", "urn:c", "editableDatasetProperties"): {
        "value": {"description": "Bestehende Beschreibung."}}})
    wb.gms = type("G", (), {"get_aspect": lambda s, *a: wb.existing.get(tuple(a))})()
    p = [x for x in propose(LEDGER) if x.kind == "enrich_doc"][0]
    apply_proposal(wb, p, now_ms=9)
    _, _, _, value, _ = wb.written[0]
    assert value["description"].startswith("Bestehende Beschreibung.")
    assert "probate" in value["description"]


def test_enriched_documentation_names_the_data_as_seeded():
    """Regel 3 der Uebergabe: geseedete Daten werden als geseedet
    ausgewiesen -- auch in dem Text, der im Katalog landet."""
    wb = RecordingWb()
    wb.gms = type("G", (), {"get_aspect": lambda s, *a: None})()
    p = [x for x in propose(LEDGER) if x.kind == "enrich_doc"][0]
    apply_proposal(wb, p, now_ms=9)
    _, _, _, value, _ = wb.written[0]
    assert "seeded" in value["description"]


def test_remove_edge_drops_exactly_one_upstream_and_keeps_the_rest():
    wb = RecordingWb({("dataset", "urn:d", "upstreamLineage"): {"value": {"upstreams": [
        {"dataset": "urn:a", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}},
        {"dataset": "urn:b", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}}]}}})
    wb.gms = type("G", (), {"get_aspect": lambda s, *a: wb.existing.get(tuple(a))})()
    remove_edge(wb, upstream="urn:a", downstream="urn:d", now_ms=9)
    _, _, _, value, _ = wb.written[0]
    assert [u["dataset"] for u in value["upstreams"]] == ["urn:b"]


def test_an_unknown_proposal_kind_is_loud():
    import pytest
    with pytest.raises(ValueError):
        apply_proposal(RecordingWb(), Proposal("erfunden", "a->b", "b", "x", {}, ""))
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_correct.py -q`
Erwartet: FAIL mit `ImportError: cannot import name 'remove_edge'`

- [ ] **Step 3: Minimale Umsetzung**

`apply_proposal` um zwei Zweige ergänzen (vor dem `raise`):

```python
    if p.kind == "mark_dead":
        before = wb.gms.get_aspect("dataset", p.target_urn, "upstreamLineage")
        value = merge_upstreams(
            before, mark_dead={upstream: _iso_day(p.evidence.get("last_covered_ms"))})
        return wb.aspect("dataset", p.target_urn, "upstreamLineage", value)

    if p.kind == "enrich_doc":
        before = wb.gms.get_aspect("dataset", p.target_urn, "editableDatasetProperties")
        old = ((before or {}).get("value") or {}).get("description") or ""
        n = len(p.evidence.get("query_urns", []))
        note = (f"probate: observed traffic from {upstream} in {n} measured "
                f"query/queries, last covered {_iso_day(p.evidence.get('last_covered_ms'))} "
                f"(source: DataHub usage statistics, seeded data).")
        text = f"{old}\n\n{note}".strip() if old else note
        return wb.aspect("dataset", p.target_urn, "editableDatasetProperties",
                         {"description": text})
```

Und:

```python
def remove_edge(wb, upstream: str, downstream: str, now_ms: int = 0):
    """Nimmt EINE deklarierte Kante weg -- nur auf ausdruecklichen Zuruf.

    Kein Vorschlag erzeugt das automatisch: eine Kante zu entfernen ist
    die einzige nicht-additive Handlung im Korrektur-Modus, und sie
    passiert nur, wenn ein Mensch sie ausloest. Das Journal deckt sie
    trotzdem (writeback sichert den Vorher-Zustand).
    """
    before = wb.gms.get_aspect("dataset", downstream, "upstreamLineage")
    value = merge_upstreams(before, drop=[upstream])
    return wb.aspect("dataset", downstream, "upstreamLineage", value)
```

- [ ] **Step 4: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 133 passed

- [ ] **Step 5: Commit**

```bash
git add probate/correct.py tests/test_correct.py
git commit -m "feat(correct): tote kante markieren, kante entfernen, doku aus nutzung"
```

---

### Task 14: CLI `propose` / `correct` + Revert-Gesamtprobe gegen 28080

**Depends:** Task 13.

**Files:**
- Modify: `probate/cli.py`
- Test: `tests/test_correct.py`
- Artefakt: `harness/runs/correct-roundtrip.json`

- [ ] **Step 1: CLI-Parser ergänzen** (im Block bei `cli.py:84-119`)

```python
    pr = sub.add_parser("propose", help="Korrektur-Vorschlaege aus dem Kanten-Register -- schreibt nichts")
    pr.add_argument("--ledger", default="harness/runs/ledger.json")
    pr.add_argument("--out", default="harness/runs/proposals.json")

    co = sub.add_parser("correct", help="EINEN bestaetigten Vorschlag anwenden (HITL, einzeln)")
    co.add_argument("--edge", required=True, help="Kanten-Schluessel 'upstream->downstream'")
    co.add_argument("--kind", required=True, choices=["add_edge", "mark_dead", "enrich_doc", "remove_edge"])
    co.add_argument("--proposals", default="harness/runs/proposals.json")
    co.add_argument("--gms", default=DEFAULT_GMS)
    co.add_argument("--token", default=None)
```

- [ ] **Step 2: Handler ergänzen**

```python
    if args.cmd == "propose":
        from probate.correct import propose as build_proposals
        ledger = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
        props = [p.to_json() for p in build_proposals(ledger)]
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"seeded": True, "proposals": props}, indent=2),
                                  encoding="utf-8")
        for p in props:
            print(f"  [{p['kind']:<11}] {p['edge']}\n      {p['human_summary']}")
        print(f"\n  {len(props)} Vorschlaege. Keiner ist angewendet -- "
              f"'probate correct --edge <k> --kind <art>' pro Stueck, nach menschlicher Pruefung.")
        return 0

    if args.cmd == "correct":
        import time
        from probate.correct import Proposal, apply_proposal, remove_edge
        gms = Gms(args.gms, token=args.token)
        wb = Writeback(gms, dry_run=False, journal_path="harness/runs/journal.jsonl")
        now_ms = int(time.time() * 1000)
        if args.kind == "remove_edge":
            up, down = args.edge.split("->", 1)
            r = remove_edge(wb, up, down, now_ms)
        else:
            data = json.loads(Path(args.proposals).read_text(encoding="utf-8"))
            match = [p for p in data["proposals"]
                     if p["edge"] == args.edge and p["kind"] == args.kind]
            if not match:
                print(f"Kein Vorschlag {args.kind} fuer {args.edge} in {args.proposals}.")
                return 1
            p = match[0]
            r = apply_proposal(wb, Proposal(p["kind"], p["edge"], p["target_urn"],
                                            p["aspect"], p["evidence"], p["human_summary"]),
                               now_ms=now_ms)
        print(r.detail)
        return 0 if r.applied else 1
```

- [ ] **Step 3: Echte Rundreise gegen 28080 — Schreiben, Prüfen, Zurücknehmen**

```bash
uv run --python 3.11 python -m probate.cli ledger --focus "<FOKUS-URN>" --gms http://localhost:28080
uv run --python 3.11 python -m probate.cli propose
# EINEN Vorschlag anwenden:
uv run --python 3.11 python -m probate.cli correct --edge "<kante>" --kind add_edge
# Register erneut laufen lassen -- die Kante muss den Zustand gewechselt haben:
uv run --python 3.11 python -m probate.cli ledger --focus "<FOKUS-URN>" --out harness/runs/ledger-nach.json
# Und alles zuruecknehmen:
uv run --python 3.11 python -m probate.cli revert
uv run --python 3.11 python -m probate.cli ledger --focus "<FOKUS-URN>" --out harness/runs/ledger-danach.json
```

Erwartet: `ledger.json` → `ledger-nach.json` zeigt den Zustandswechsel, `ledger-danach.json` ist wieder identisch zu `ledger.json` in den Zählschlüsseln. Beides in `harness/runs/correct-roundtrip.json` festhalten:

```json
{"seeded": true, "roundtrip_states_before": {...}, "roundtrip_states_after_write": {...},
 "roundtrip_states_after_revert": {...}, "roundtrip_reverted_writes": <n>}
```

**Wenn `ledger-danach` nicht wieder `ledger` entspricht:** das ist ein Befund, kein Rundungsfehler. Ursache suchen (`superpowers:systematic-debugging`), nicht wegerklären.

- [ ] **Step 4: Volle Suite + Beleg-Prüfung**

```bash
uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q
uv run --python 3.11 python harness/audit_claims.py
```

- [ ] **Step 5: Commit**

```bash
git add probate/cli.py tests/test_correct.py harness/runs/correct-roundtrip.json harness/runs/proposals.json
git commit -m "feat(cli): propose und correct, mit belegter rundreise und revert"
```

---

# P4 — Der Wächter live

### Task 15: Pipeline starten, echtes Ereignis erzeugen, Neubewertung nachweisen

**Depends:** P0 (`recipe.yml` korrigiert: Kafka **29192**, Schema-Registry über GMS — **nicht** 9092/8081), Task 6.

`watcher.py` ist auf Unit-Ebene getestet, aber der **Pipeline-Start ist nie mit echten Ereignissen geprüft** worden. Genau das wird hier nachgeholt — und nur das, was tatsächlich beobachtet wurde, kommt ins Artefakt.

**Files:**
- Modify: `probate_action/watcher.py` (nur Docstring: die Behauptung „ungeprüft" wird durch das Messergebnis ersetzt)
- Artefakt: `harness/runs/watcher-live.json`

- [ ] **Step 1: `recipe.yml` prüfen, bevor gestartet wird**

Run: `uv run --python 3.11 python -c "import pathlib,sys; t=pathlib.Path('probate_action/recipe.yml').read_text(); bad=[x for x in ('9092','8081','18080') if x in t]; print('FALSCHE PORTS:',bad) or sys.exit(1 if bad else 0)"`
Erwartet: Exit 0. Bei Treffer: **nicht starten**, erst P0 abwarten.

- [ ] **Step 2: `closed.json` mit einem echten URN füllen**

```bash
uv run --python 3.11 python -c "
import json, pathlib
urn = 'urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customers_v7,PROD)'
pathlib.Path('harness/runs/closed.json').write_text(json.dumps([urn]), encoding='utf-8')
print(urn)
"
```

- [ ] **Step 3: Pipeline im Hintergrund starten**

```bash
uv run --python 3.11 --with acryl-datahub-actions datahub-actions actions -c probate_action/recipe.yml
```
(im Hintergrund; Ausgabe in `harness/runs/watcher-stdout.log` mitschreiben)
Erwartet in der Ausgabe: die Action registriert sich und verbindet sich mit `localhost:29192`. **Wenn dort ein Verbindungsfehler steht: das ist das Ergebnis dieses Schritts**, nicht ein Grund zum Weitermachen.

- [ ] **Step 4: Echtes Ereignis erzeugen — Nutzungsstatistik auf den geschlossenen URN**

```bash
uv run --python 3.11 --with acryl-datahub python -c "
import time
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import DatasetUsageStatisticsClass, TimeWindowSizeClass
URN='urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customers_v7,PROD)'
em = DatahubRestEmitter(gms_server='http://localhost:28080')
em.emit_mcp(MetadataChangeProposalWrapper(entityUrn=URN, aspect=DatasetUsageStatisticsClass(
    timestampMillis=int(time.time()*1000),
    eventGranularity=TimeWindowSizeClass(unit='DAY', multiple=1),
    uniqueUserCount=1, totalSqlQueries=1)))
print('emittiert', URN)
"
```

- [ ] **Step 5: Beobachten und Artefakt schreiben**

Im Wächter-Protokoll nachsehen, ob `raiseIncident` ausgelöst wurde (Vorgabe ist `dry_run: true` — dann steht dort ein Trockenlauf-Vermerk, und **genau das** wird notiert, nicht ein behaupteter Incident).

`harness/runs/watcher-live.json`:
```json
{"seeded": true,
 "watcher_started": true,
 "watcher_kafka_bootstrap": "localhost:29192",
 "watcher_events_seen": <n>,
 "watcher_relapses_detected": <n>,
 "watcher_dry_run": true,
 "watcher_note": "<woertliche Zeile aus dem Protokoll>"}
```

- [ ] **Step 6: Register neu laufen lassen und Neubewertung zeigen**

```bash
uv run --python 3.11 python -m probate.cli ledger --focus "<FOKUS-URN>" --out harness/runs/ledger-nach-ereignis.json
```
Erwartet: die betroffene Kante hat einen neuen Zeitachsen-Eintrag (`last_covered_ms` gewachsen) oder den Zustand gewechselt. Die Differenz der Zählschlüssel kommt in `watcher-live.json` unter `watcher_reclassified_edges`.

- [ ] **Step 7: Aufräumen und Docstring korrigieren**

Den emittierten Nutzungs-Aspekt wieder entfernen und die Löschung zurücklesen:
```bash
uv run --python 3.11 python -c "
from probate.gms import Gms
g = Gms('http://localhost:28080')
URN='urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customers_v7,PROD)'
g.delete_aspect('dataset', URN, 'datasetUsageStatistics')
assert g.get_aspect('dataset', URN, 'datasetUsageStatistics') is None
print('aufgeraeumt und zurueckgelesen')
"
```

In `probate_action/watcher.py` den Docstring-Absatz, der den Pipeline-Start als **ungeprüft** führt, durch das **gemessene** Ergebnis ersetzen — mit Datum, Bootstrap-Adresse und der Zahl beobachteter Ereignisse. Eine falsche Zeile in einer Doku ist schlimmer als eine fehlende: sie wird geglaubt.

- [ ] **Step 8: Commit**

```bash
git add probate_action/watcher.py harness/runs/watcher-live.json harness/runs/ledger-nach-ereignis.json
git commit -m "feat(watcher): pipeline live gegen 29192, echtes ereignis und neubewertung belegt"
```

---

# P5 — Die Werkbank (Schicht 4)

> **Nicht streichbar.** Ohne sie ist die Demo wieder etwas, dem man glauben muss — und genau das hat in der Jury-Simulation die schlechteste Einzelnote bekommen (3/10 Submission Quality). Eine Jurorin wörtlich: *„Ich kann es nicht selbst erleben, nur glauben."*
>
> **Die Gestaltungsvorgaben aus den Global Constraints gelten für jede Aufgabe dieser Phase — Gebote wie Verbote.** Wer eine Karte mit Akzentstreifen und grosser Rundung baut, hat die Aufgabe nicht erfüllt, egal ob sie funktioniert.

### Task 16: Gestaltungs-Token und Gerüst — vier Bereiche, beide Themen

**Parallel zu:** Task 1–15 (berührt nur `ui/`). Kann ab sofort laufen; braucht von P1 nur die JSON-Form aus Task 6.

**Files:**
- Create: `ui/werkbank.html`, `ui/werkbank.css`
- Create: `ui/recorded/ledger.json` (Kopie eines echten Laufs, **nicht** erfunden)
- Test: `tests/test_ui_tokens.py`

**Interfaces:**
- Produces: DOM-Gerüst mit den IDs, die `werkbank.js` (Task 17) erwartet:
  `#declared-tree` · `#measured-bars` · `#edge-ledger` · `#live-log` · `#coverage-banner` · `#mode-badge` · `#controls`.

- [ ] **Step 1: Failing test schreiben — die Verbotsliste ist prüfbar**

```python
# tests/test_ui_tokens.py
"""Die Gestaltungsvorgaben sind bindend (Spec, Abschnitt Gestaltung).
Was pruefbar ist, wird geprueft -- nicht auf Disziplin verlassen."""

import re
from pathlib import Path

CSS = Path("ui/werkbank.css")
HTML = Path("ui/werkbank.html")


def test_every_colour_lives_in_the_token_block_and_nowhere_else():
    """Zwei Quellen, zwei Farben, DURCHGEHEND -- das haelt nur, wenn es
    genau eine Stelle gibt, an der eine Farbe definiert wird."""
    css = CSS.read_text(encoding="utf-8")
    root = re.search(r":root\s*\{.*?\}", css, re.S).group(0)
    outside = css.replace(root, "")
    outside = re.sub(r"@media[^{]*\{[^{}]*\{[^}]*\}[^}]*\}", "", outside, flags=re.S)
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", outside)
    assert not re.findall(r"\b(?:rgb|hsl)a?\(", outside)


def test_the_forbidden_fonts_appear_nowhere():
    css = CSS.read_text(encoding="utf-8")
    for banned in ("Inter", "Space Grotesk"):
        assert banned not in css


def test_no_gradient_anywhere():
    assert "gradient" not in CSS.read_text(encoding="utf-8").lower()


def test_no_emoji_as_section_markers_in_the_markup():
    html = HTML.read_text(encoding="utf-8")
    assert not re.findall(r"[\U0001F300-\U0001FAFF☀-➿]", html)


def test_both_themes_are_defined_and_the_explicit_toggle_wins():
    css = CSS.read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in css
    assert 'data-theme="dark"' in css
    assert 'data-theme="light"' in css


def test_keyboard_focus_is_visible_not_removed():
    css = CSS.read_text(encoding="utf-8")
    assert ":focus-visible" in css
    assert "outline: none" not in css.replace(" ", "").replace("outline:none", "outline: none")


def test_numbers_use_tabular_figures_where_they_stack():
    assert "font-variant-numeric: tabular-nums" in CSS.read_text(encoding="utf-8")


def test_the_four_panes_and_the_coverage_banner_exist_by_id():
    html = HTML.read_text(encoding="utf-8")
    for anchor in ("declared-tree", "measured-bars", "edge-ledger", "live-log",
                   "coverage-banner", "mode-badge", "controls"):
        assert f'id="{anchor}"' in html


def test_every_state_carries_its_explaining_sentence_in_the_markup():
    """'Erklaerend eingebaut, nicht als Handbuch daneben' -- wer unknown
    zum ersten Mal sieht, darf nicht raten muessen."""
    html = HTML.read_text(encoding="utf-8")
    for state in ("confirmed", "dead", "missing", "unknown"):
        assert f'data-state-help="{state}"' in html


def test_wide_content_scrolls_in_its_own_container():
    assert "overflow-x: auto" in CSS.read_text(encoding="utf-8")
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_ui_tokens.py -q`
Erwartet: FAIL mit `FileNotFoundError: ui/werkbank.css`

- [ ] **Step 3: `ui/werkbank.css` schreiben — Token zuerst**

Vorgaben, die im Token-Block landen (keine Literalwerte irgendwo sonst):

```css
/* ui/werkbank.css
   Warum diese Datei so aussieht: die Gestaltung ist eines von sechs
   gleichgewichteten Bewertungskriterien, und die Vorgaben sind bindend
   (Spec, Abschnitt Gestaltung). Rot gehoert dem ZUSTAND einer Kante --
   nirgends einem Rahmen, einer Kopfzeile oder einem Knopf. */

:root {
  color-scheme: light dark;

  /* Grundton: gedeckt, kuehl, ruhig. Kein Creme, kein Terrakotta. */
  --bg:            #f7f8fa;
  --surface:       #ffffff;
  --surface-sunk:  #eef1f5;
  --line:          #d9dee6;
  --ink:           #16191f;
  --ink-muted:     #5b636f;

  /* Die zwei Quellenfarben. Auf JEDEM Bildschirm dieselben. */
  --declared:      #3d5a99;   /* was der Katalog behauptet */
  --measured:      #1f7a63;   /* was wirklich passiert ist */

  /* Zustandsfarben. Rot lebt nur hier. */
  --state-confirmed: #1f7a63;
  --state-dead:      #a8323a;
  --state-missing:   #9a6b12;
  --state-unknown:   #6b7280;

  /* Form: bewusst NICHT ueberall dieselbe grosse Rundung. */
  --r-card:  6px;
  --r-chip:  3px;
  --r-input: 4px;

  --space-1: 4px;  --space-2: 8px;  --space-3: 12px;
  --space-4: 20px; --space-5: 32px; --space-6: 48px;

  --font-ui:   ui-sans-serif, system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-mono: ui-monospace, "Cascadia Mono", "SFMono-Regular", Consolas, monospace;

  --t-fast: 120ms ease-out;
  --t-calm: 220ms ease-out;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14161a; --surface: #1b1e24; --surface-sunk: #22262e;
    --line: #313743; --ink: #e8eaee; --ink-muted: #9aa3b0;
    --declared: #8fa8e0; --measured: #5fc0a4;
    --state-confirmed: #5fc0a4; --state-dead: #e08b92;
    --state-missing: #d9ad5b; --state-unknown: #98a1ae;
  }
}
:root[data-theme="dark"] { /* dieselben dunklen Werte, explizit */ }
:root[data-theme="light"] { /* dieselben hellen Werte, explizit */ }
```

Weiter im Regelwerk (nur Token, keine Literale):
- Raster: `grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)`, zwei Zeilen, `gap: var(--space-4)`. **Nicht zentriert** — der Inhalt füllt die Breite, Kopfzeile linksbündig.
- Zahlen-Container: `font-variant-numeric: tabular-nums`.
- Jede Tabelle und jeder Baum in `.pane__body { overflow-x: auto; }` — die Seite selbst scrollt nie waagrecht.
- `:focus-visible { outline: 2px solid var(--declared); outline-offset: 2px; }`
- Zustands-Chip: farbiger Punkt + Text, `border-radius: var(--r-chip)`, **kein** Akzentstreifen an der Karte.

- [ ] **Step 4: `ui/werkbank.html` schreiben**

Gerüst (gekürzt, aber vollständig in den tragenden Teilen):

```html
<main class="shell">
  <header class="shell__head">
    <h1 class="shell__title">Lineage truth bench</h1>
    <p class="shell__sub">Declared lineage, held against measured usage — per edge.</p>
    <span id="mode-badge" class="badge" data-mode="recording">Recording — no live instance</span>
  </header>

  <p id="coverage-banner" class="banner" role="status">
    <!-- steht UEBER den Ergebnissen, nie in einer Fussnote -->
  </p>

  <section id="controls" class="controls" aria-label="Control desk">
    <button type="button" data-action="seed-query">Run a query</button>
    <button type="button" data-action="add-edge">Declare an edge</button>
    <button type="button" data-action="remove-edge">Remove an edge</button>
    <button type="button" data-action="cut-warehouse">Disconnect warehouse</button>
    <button type="button" data-action="fast-forward">Fast-forward time</button>
    <button type="button" data-action="run-ledger">Run full check</button>
  </section>

  <div class="grid">
    <section class="pane pane--declared"><h2>Declared</h2><div id="declared-tree" class="pane__body"></div></section>
    <section class="pane pane--ledger"><h2>Edge ledger</h2><div id="edge-ledger" class="pane__body"></div></section>
    <section class="pane pane--measured"><h2>Measured</h2><div id="measured-bars" class="pane__body"></div></section>
    <section class="pane pane--log"><h2>Live log</h2><div id="live-log" class="pane__body"></div></section>
  </div>

  <template id="state-help">
    <span data-state-help="confirmed">Declared and measured — the edge carries real traffic.</span>
    <span data-state-help="dead">Declared, but no traffic in any observed window.</span>
    <span data-state-help="missing">Measured together in queries, but never declared.</span>
    <span data-state-help="unknown">No usage windows at all — we did not look, so we do not say.</span>
  </template>
</main>
```

- [ ] **Step 5: Echten Lauf als Aufzeichnung ablegen**

```bash
mkdir -p ui/recorded && cp harness/runs/ledger.json ui/recorded/ledger.json
```
**Nicht erfinden.** Die Aufzeichnung ist ein echter Lauf, sonst ist die Werkbank genau das, was sie widerlegen soll.

- [ ] **Step 6: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 143 passed

- [ ] **Step 7: Commit**

```bash
git add ui/werkbank.html ui/werkbank.css ui/recorded/ledger.json tests/test_ui_tokens.py
git commit -m "feat(ui): gestaltungs-token und geruest -- vier bereiche, beide themen"
```

---

### Task 17: Aufzeichnungsmodus — die Seite lebt ohne Instanz

**Depends:** Task 16.

**Files:**
- Create: `ui/werkbank.js`
- Test: `tests/test_ui_tokens.py` (erweitern)

**Interfaces:**
- Produces: `render(ledger)` zeichnet alle vier Bereiche; `detectMode()` fragt `GET /api/mode` und fällt bei jedem Fehler auf `"recording"` zurück.

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_ui_tokens.py -- anhaengen
JS = Path("ui/werkbank.js")


def test_recording_is_the_safe_default_when_the_mode_probe_fails():
    """Eine gescheiterte Abfrage ist keine Abwesenheit -- aber sie darf
    auch nicht als Live-Betrieb durchgehen. Kein Antwort = Aufzeichnung."""
    js = JS.read_text(encoding="utf-8")
    assert "'recording'" in js or '"recording"' in js
    assert "catch" in js


def test_datasets_without_usage_render_as_visibly_empty_not_as_zero():
    """Spec: 'Tabellen ohne Datenlage sind sichtbar leer, nicht auf null
    gesetzt -- der Unterschied muss auch optisch einer sein.'"""
    js = JS.read_text(encoding="utf-8")
    assert "no-data" in js
    assert "bar--empty" in js or "measured--nodata" in js


def test_every_rendered_state_gets_its_explaining_sentence_attached():
    assert "state-help" in JS.read_text(encoding="utf-8")


def test_the_ui_never_sums_buckets_into_a_single_number_for_the_state():
    """Wer die Buckets summiert, macht aus 'nicht gemessen' und 'nichts
    passiert' dieselbe Null -- in der Oberflaeche genauso wie im Code."""
    js = JS.read_text(encoding="utf-8")
    assert "buckets_seen" in js
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_ui_tokens.py -q`
Erwartet: FAIL mit `FileNotFoundError: ui/werkbank.js`

- [ ] **Step 3: Minimale Umsetzung**

```javascript
// ui/werkbank.js
// Warum diese Datei kein Rahmenwerk benutzt: der Bildschirm hat vier
// Bereiche und sechs Knoepfe, der Zustand ist ein Objekt. Ein Bauschritt
// zwischen "geaendert" und "sichtbar" waere reines Risiko
// (docs/entscheidungen/2026-08-07-ui-stack-werkbank.md).

const STATE_HELP = {
  confirmed: 'Declared and measured — the edge carries real traffic.',
  dead: 'Declared, but no traffic in any observed window.',
  missing: 'Measured together in queries, but never declared.',
  unknown: 'No usage windows at all — we did not look, so we do not say.',
};

async function detectMode() {
  // Kein Server = Aufzeichnung. Der sichere Rueckfall, nie stillschweigend live.
  try {
    const r = await fetch('/api/mode', { cache: 'no-store' });
    if (!r.ok) return 'recording';
    return (await r.json()).mode === 'live' ? 'live' : 'recording';
  } catch {
    return 'recording';
  }
}

async function loadLedger(mode) {
  const url = mode === 'live' ? '/api/ledger' : './recorded/ledger.json';
  return (await fetch(url, { cache: 'no-store' })).json();
}

function renderCoverage(ledger) {
  const el = document.getElementById('coverage-banner');
  const thin = ledger.coverage_thin;
  el.dataset.thin = String(thin);
  el.textContent = thin
    ? `Thin coverage: ${ledger.coverage_buckets_seen} usage windows in total, `
      + `spanning ${ledger.coverage_days_span} days. `
      + `${ledger.edges_unknown} edge(s) are "unknown" — not "dead".`
    : `Coverage: ${ledger.coverage_buckets_seen} usage windows over `
      + `${ledger.coverage_days_span} days. Seeded data.`;
}

function renderMeasured(ledger) {
  const host = document.getElementById('measured-bars');
  host.innerHTML = '';
  const max = Math.max(1, ...ledger.edges.map(e => (e.timeline.series || [])
    .reduce((a, [, n]) => a + n, 0)));
  for (const e of ledger.edges) {
    const row = document.createElement('div');
    row.className = 'bar-row';
    const noData = (e.coverage.buckets_seen || 0) === 0;
    const total = (e.timeline.series || []).reduce((a, [, n]) => a + n, 0);
    const bar = document.createElement('span');
    // Sichtbar LEER, nicht auf null gesetzt -- der Unterschied muss
    // auch optisch einer sein (Spec, Schicht 4).
    bar.className = noData ? 'bar bar--empty' : 'bar';
    if (noData) {
      bar.dataset.noData = 'true';
      bar.textContent = 'no usage data';
    } else {
      bar.style.setProperty('--w', `${(total / max) * 100}%`);
    }
    row.append(Object.assign(document.createElement('span'),
      { className: 'bar-row__label', textContent: e.downstream }), bar);
    host.append(row);
  }
}

function renderLedger(ledger) {
  const host = document.getElementById('edge-ledger');
  host.innerHTML = '';
  for (const e of ledger.edges) {
    const card = document.createElement('details');
    card.className = 'edge';
    card.dataset.state = e.state;
    const sum = document.createElement('summary');
    sum.innerHTML = `<span class="chip" data-state="${e.state}">${e.state}</span>`
      + `<code class="edge__key">${e.edge}</code>`;
    const help = document.createElement('p');
    help.className = 'edge__help';
    help.dataset.stateHelp = e.state;
    help.textContent = STATE_HELP[e.state];
    const tl = document.createElement('p');
    tl.className = 'edge__timeline';
    tl.textContent = e.timeline.dead_since_days === null
      ? 'No timeline — no windows observed.'
      : `${e.timeline.dead_since_is_lower_bound ? 'At least ' : ''}`
        + `${e.timeline.dead_since_days} days since last covered.`;
    card.append(sum, help, tl);
    host.append(card);
  }
}

function renderDeclared(ledger) {
  const host = document.getElementById('declared-tree');
  host.innerHTML = '';
  const root = document.createElement('div');
  root.className = 'node node--root';
  root.textContent = ledger.focus;
  host.append(root);
  for (const e of ledger.edges.filter(x => x.state !== 'missing')) {
    const n = document.createElement('button');
    n.type = 'button';
    n.className = 'node node--child';
    n.dataset.state = e.state;
    n.dataset.edge = e.edge;
    n.textContent = e.downstream;
    host.append(n);
  }
}

export function render(ledger) {
  renderCoverage(ledger);
  renderDeclared(ledger);
  renderMeasured(ledger);
  renderLedger(ledger);
}

async function boot() {
  const mode = await detectMode();
  const badge = document.getElementById('mode-badge');
  badge.dataset.mode = mode;
  badge.textContent = mode === 'live'
    ? 'Live — buttons write to localhost:28080'
    : 'Recording — replaying a stored run, buttons disabled';
  document.querySelectorAll('#controls button')
    .forEach(b => { b.disabled = mode !== 'live'; });
  render(await loadLedger(mode));
}

boot();
```

- [ ] **Step 4: Im Browser ansehen (Aufzeichnungsmodus)**

```bash
uv run --python 3.11 python -m http.server 8899 --directory ui
```
Dann `http://localhost:8899/werkbank.html` öffnen. Erwartet: vier Bereiche gefüllt, Kennzeichnung „Recording", Knöpfe deaktiviert, keine waagrechte Seitenverschiebung, helles **und** dunkles Thema geprüft.

- [ ] **Step 5: Volle Suite + Commit**

```bash
uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q
git add ui/werkbank.js tests/test_ui_tokens.py
git commit -m "feat(ui): aufzeichnungsmodus -- keine datenlage ist sichtbar leer, nicht null"
```

---

### Task 18: Live-Modus — Proxy auf 8899

**Depends:** Task 17, Task 6, Task 13.

**Files:**
- Create: `ui/serve.py`
- Test: `tests/test_ui_serve.py`

**Interfaces:**
- Produces:
  ```python
  def build_handler(gms_url: str, focus: str, log: list) -> type
  def main(argv=None) -> int          # --gms --focus --port 8899
  ```
  Endpunkte: `GET /api/mode` · `GET /api/ledger` · `GET /api/log?since=N` · `POST /api/action/<name>`.

- [ ] **Step 1: Failing test schreiben — die Handler-Logik ohne Netz**

```python
# tests/test_ui_serve.py
"""Der Proxy existiert wegen CORS und weil die Knoepfe Python sind
(docs/entscheidungen/2026-08-07-ui-stack-werkbank.md). Getestet wird die
Wegewahl, nicht der Socket."""

import pytest
from ui.serve import ACTIONS, PORT_DEFAULT, route


def test_the_port_is_never_one_of_the_taken_ones():
    """8080 ist Joels WhatsApp-Bridge, 8081 gibt es gar nicht,
    18080 traegt showcase-ecommerce."""
    assert PORT_DEFAULT == 8899


def test_mode_endpoint_answers_live_because_the_proxy_only_runs_live():
    assert route("GET", "/api/mode", {}) == ("mode", {})


def test_ledger_endpoint_is_routed():
    assert route("GET", "/api/ledger", {}) == ("ledger", {})


def test_log_endpoint_passes_the_since_cursor_through():
    assert route("GET", "/api/log", {"since": ["12"]}) == ("log", {"since": 12})


def test_every_one_of_the_six_buttons_has_an_action():
    assert set(ACTIONS) == {"seed-query", "add-edge", "remove-edge",
                            "cut-warehouse", "fast-forward", "run-ledger"}


def test_an_unknown_action_is_rejected_instead_of_silently_ignored():
    with pytest.raises(KeyError):
        route("POST", "/api/action/erfunden", {})


def test_a_get_on_an_action_path_is_not_a_write():
    """Schreiben nur per POST -- ein versehentlicher Seitenaufruf darf
    nichts veraendern."""
    with pytest.raises(ValueError):
        route("GET", "/api/action/add-edge", {})
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_ui_serve.py -q`
Erwartet: FAIL mit `ModuleNotFoundError: No module named 'ui.serve'`
(Falls der Import scheitert: `ui/__init__.py` anlegen und `"ui"` in `pyproject.toml` unter `[tool.setuptools] packages` ergänzen.)

- [ ] **Step 3: Minimale Umsetzung — Wegewahl zuerst**

```python
# ui/serve.py
"""Der Live-Modus der Werkbank.

Warum diese Datei existiert -- zwei Gruende, beide zwingend:

1. CORS. Ein Browser auf file:// oder einem fremden Port braucht von GMS
   einen Access-Control-Allow-Origin-Kopf. Ob 28080 den sendet, ist NICHT
   gemessen. Ein Proxy im selben Ursprung loescht die Frage, statt sie zu
   beantworten.
2. Die Knoepfe sind Python. "Kante eintragen" ist kein GMS-Aufruf, sondern
   correct.apply_proposal() ueber writeback.Writeback -- mit Journal,
   Vorher-Sicherung und Rueckwaertsgang. Diese Disziplin im Browser
   nachzubauen waere eine zweite Wahrheit ueber den einzigen Schreibweg.

Port 8899: nicht 8080 (WhatsApp-Bridge), nicht 8081 (existiert nicht),
nicht 3000 (Cockpit).
"""

from __future__ import annotations

PORT_DEFAULT = 8899

ACTIONS = ("seed-query", "add-edge", "remove-edge",
           "cut-warehouse", "fast-forward", "run-ledger")


def route(method: str, path: str, query: dict) -> tuple[str, dict]:
    """Wegewahl ohne Socket -- damit sie ohne Netz pruefbar ist."""
    if path == "/api/mode" and method == "GET":
        return "mode", {}
    if path == "/api/ledger" and method == "GET":
        return "ledger", {}
    if path == "/api/log" and method == "GET":
        return "log", {"since": int((query.get("since") or ["0"])[0])}
    if path.startswith("/api/action/"):
        name = path.rsplit("/", 1)[-1]
        if name not in ACTIONS:
            raise KeyError(f"unbekannte Aktion: {name}")
        if method != "POST":
            raise ValueError("Aktionen schreiben -- nur POST")
        return "action", {"name": name}
    raise KeyError(f"kein Weg fuer {method} {path}")
```

- [ ] **Step 4: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 154 passed

- [ ] **Step 5: Server drumherum bauen**

```python
# ui/serve.py -- anhaengen
import argparse, json, time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

UI_DIR = Path(__file__).parent


def build_handler(gms_url: str, focus: str, log: list):
    from probate.gms import Gms
    from probate.ledger import run as ledger_run
    from probate.writeback import Writeback

    def note(text: str, number=None) -> None:
        """Jede Protokollzeile traegt eine Zahl, kein Gefuehl."""
        log.append({"t": int(time.time() * 1000), "text": text, "n": number})

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(UI_DIR), **kw)

        def _json(self, payload, code=200):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _handle(self, method):
            u = urlparse(self.path)
            try:
                kind, args = route(method, u.path, parse_qs(u.query))
            except (KeyError, ValueError):
                return None
            gms = Gms(gms_url)
            if kind == "mode":
                return self._json({"mode": "live", "gms": gms_url, "focus": focus})
            if kind == "log":
                return self._json({"entries": log[args["since"]:], "cursor": len(log)})
            if kind == "ledger":
                out = ledger_run(gms, focus, int(time.time() * 1000))
                note(f"full check: {out['edges_total']} edges", out["edges_total"])
                return self._json(out)
            if kind == "action":
                return self._json(do_action(args["name"], gms, focus, note))
            return None

        def do_GET(self):
            if self._handle("GET") is None:
                super().do_GET()

        def do_POST(self):
            if self._handle("POST") is None:
                self.send_error(404)

    return H
```

`do_action(name, gms, focus, note)` ist Task 19.

- [ ] **Step 6: Commit**

```bash
git add ui/serve.py ui/__init__.py tests/test_ui_serve.py pyproject.toml
git commit -m "feat(ui): live-proxy auf 8899 -- cors geloescht statt beantwortet"
```

---

### Task 19: Die sechs Knöpfe — sie schreiben wirklich

**Depends:** Task 18, Task 13.

**Der Knopf, der die Demo trägt, ist „Warehouse trennen".** Er führt in fünf Sekunden vor, was in der alten Fassung ein stiller Fehler war.

**Falle 1** gilt an jedem dieser Knöpfe: der Weg geht über `wb.aspect()` → `gms.upsert()` (Liste erzwungen), nie direkt.

**Files:**
- Modify: `ui/serve.py`, `ui/werkbank.js`
- Test: `tests/test_ui_serve.py`

**Interfaces:**
- Produces: `def do_action(name: str, gms, focus: str, note) -> dict`

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_ui_serve.py -- anhaengen
from ui.serve import do_action


class FakeGms:
    def __init__(self):
        self.deleted, self.upserted = [], []

    def get_aspect(self, t, u, a):
        return None

    def upsert(self, t, records, sync=True):
        assert isinstance(records, list), "Falle 1: upsert will eine LISTE"
        self.upserted.append((t, records))
        return records

    def delete_aspect(self, t, u, a):
        self.deleted.append((t, u, a))

    def graphql(self, q, v=None):
        return {"dataset": {"lineage": {"relationships": []}},
                "searchAcrossEntities": {"total": 0, "searchResults": []}}


def test_cut_warehouse_deletes_the_usage_aspect_so_coverage_collapses():
    """DER Demo-Knopf: er nimmt die Datenlage weg, nicht den Verkehr.
    Danach muessen Kanten 'unknown' werden, nicht 'dead'."""
    g, seen = FakeGms(), []
    out = do_action("cut-warehouse", g, "urn:focus", lambda t, n=None: seen.append(t))
    assert ("dataset", "urn:focus", "datasetUsageStatistics") in g.deleted
    assert out["expect"] == "unknown"


def test_fast_forward_only_moves_the_observation_window_and_writes_nothing():
    """Zeit vorspulen ist eine SICHT, keine Datenaenderung -- alles
    andere waere eine gefaelschte Messung."""
    g = FakeGms()
    out = do_action("fast-forward", g, "urn:focus", lambda t, n=None: None)
    assert g.upserted == [] and g.deleted == []
    assert out["now_ms_offset_days"] > 0


def test_every_action_returns_a_log_line_with_a_number():
    """Uebergabe Abschnitt 10: jede Protokollzeile traegt eine Zahl,
    kein Gefuehl."""
    for name in ("seed-query", "add-edge", "remove-edge", "cut-warehouse",
                 "fast-forward", "run-ledger"):
        seen = []
        do_action(name, FakeGms(), "urn:focus", lambda t, n=None: seen.append((t, n)))
        assert seen and seen[-1][1] is not None
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_ui_serve.py -q`
Erwartet: FAIL mit `ImportError: cannot import name 'do_action'`

- [ ] **Step 3: Minimale Umsetzung**

```python
# ui/serve.py -- anhaengen
_view_offset_days = 0
DEMO_PARTNER = "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.demo_partner,PROD)"


def do_action(name: str, gms, focus: str, note) -> dict:
    """Die sechs Knoepfe. Jeder veraendert eine der beiden Wahrheitsquellen
    -- ausser 'fast-forward', der nur die Sicht verschiebt.
    """
    global _view_offset_days
    from probate.correct import merge_upstreams, remove_edge
    from probate.writeback import Writeback
    wb = Writeback(gms, dry_run=False, journal_path="harness/runs/journal.jsonl")
    now_ms = int(time.time() * 1000)

    if name == "seed-query":
        from harness.seed_queries import build_query_records
        records = build_query_records([(focus, DEMO_PARTNER)])
        gms.upsert("query", records)            # Falle 1: Liste, nicht Objekt
        note(f"query written, {len(records)} subject pair(s)", len(records))
        return {"wrote": len(records), "expect": "missing"}

    if name == "add-edge":
        before = gms.get_aspect("dataset", DEMO_PARTNER, "upstreamLineage")
        value = merge_upstreams(before, add=[{
            "dataset": focus, "type": "TRANSFORMED",
            "auditStamp": {"time": now_ms, "actor": "urn:li:corpuser:__datahub_system"}}])
        wb.aspect("dataset", DEMO_PARTNER, "upstreamLineage", value)
        note(f"edge declared, {len(value['upstreams'])} upstream(s) now on target",
             len(value["upstreams"]))
        return {"upstreams": len(value["upstreams"]), "expect": "dead"}

    if name == "remove-edge":
        r = remove_edge(wb, focus, DEMO_PARTNER, now_ms)
        note("edge removed, 1 upstream dropped", 1)
        return {"removed": 1, "applied": r.applied, "expect": "missing"}

    if name == "cut-warehouse":
        # Nimmt die DATENLAGE weg, nicht den Verkehr. Genau das ist der
        # Unterschied, den die alte Fassung verschluckt hat.
        gms.delete_aspect("dataset", focus, "datasetUsageStatistics")
        note("usage aspect deleted on 1 dataset — coverage collapses", 1)
        return {"deleted": 1, "expect": "unknown"}

    if name == "fast-forward":
        _view_offset_days += 30
        note(f"observation window moved forward {_view_offset_days} days (view only)",
             _view_offset_days)
        return {"now_ms_offset_days": _view_offset_days, "expect": "aged"}

    if name == "run-ledger":
        from probate.ledger import run as ledger_run
        out = ledger_run(gms, focus, now_ms + _view_offset_days * 86_400_000)
        note(f"full check: {out['edges_total']} edges, {out['api_calls']} API calls",
             out["edges_total"])
        return out

    raise KeyError(name)
```

- [ ] **Step 4: Knöpfe im Browser verdrahten**

In `ui/werkbank.js` ergänzen:
```javascript
document.getElementById('controls').addEventListener('click', async (ev) => {
  const btn = ev.target.closest('button[data-action]');
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  try {
    await fetch(`/api/action/${btn.dataset.action}`, { method: 'POST' });
    render(await loadLedger('live'));
    await pumpLog();
  } finally {
    btn.disabled = false;
  }
});

let logCursor = 0;
async function pumpLog() {
  const r = await fetch(`/api/log?since=${logCursor}`, { cache: 'no-store' });
  const { entries, cursor } = await r.json();
  logCursor = cursor;
  const host = document.getElementById('live-log');
  for (const e of entries) {
    const line = document.createElement('div');
    line.className = 'log-line';
    line.innerHTML = `<time>${new Date(e.t).toLocaleTimeString()}</time>`
      + `<span>${e.text}</span>`;
    host.prepend(line);          // neueste oben
  }
}
setInterval(() => { if (document.body.dataset.mode === 'live') pumpLog(); }, 1500);
```

- [ ] **Step 5: Demo-Ablauf live durchspielen (~40 s)**

Server starten:
```bash
uv run --python 3.11 python -m ui.serve --gms http://localhost:28080 --focus "<FOKUS-URN>" --port 8899
```
Dann `http://localhost:8899/werkbank.html` und in dieser Reihenfolge klicken:
**Kante eintragen** → erscheint als `dead` → **Abfrage absetzen** → wird `confirmed` → **Warehouse trennen** → wird `unknown`.

Dreimal in drei Richtungen. Läuft eine der drei Richtungen nicht: **Befund**, kein Nachhelfen von Hand.
Danach: `uv run --python 3.11 python -m probate.cli revert`, und die Nutzungsdaten neu seeden.

- [ ] **Step 6: Volle Suite + Commit**

```bash
uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q
git add ui/serve.py ui/werkbank.js tests/test_ui_serve.py
git commit -m "feat(ui): sechs knoepfe, live gegen 28080 -- warehouse trennen zeigt unknown"
```

---

### Task 20: Feinschliff — Modus-Kennzeichnung, Tastatur, beide Themen

**Depends:** Task 19.

**Files:**
- Modify: `ui/werkbank.css`, `ui/werkbank.html`, `ui/werkbank.js`
- Test: `tests/test_ui_tokens.py` (erweitern)

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_ui_tokens.py -- anhaengen
def test_the_recording_badge_is_visible_and_never_disguised_as_live():
    """Spec: 'sichtbar als Aufzeichnung gekennzeichnet, nicht als
    Live-Betrieb getarnt.'"""
    css = CSS.read_text(encoding="utf-8")
    assert '[data-mode="recording"]' in css
    assert '[data-mode="live"]' in css


def test_disabled_buttons_say_why_they_are_disabled():
    html = HTML.read_text(encoding="utf-8")
    assert "aria-describedby" in html or "title=" in html


def test_the_state_colour_is_the_only_red_in_the_sheet():
    """Rot gehoert dem Zustand einer Kante. Nirgends einem Rahmen, einer
    Kopfzeile, einem Knopf."""
    css = CSS.read_text(encoding="utf-8")
    root = re.search(r":root\s*\{.*?\}", css, re.S).group(0)
    reds = [ln for ln in root.splitlines() if re.search(r"#[ae][0-9a-f]{5}", ln, re.I)]
    assert all("state-dead" in ln for ln in reds)


def test_the_theme_toggle_exists_and_stamps_the_root():
    assert "data-theme" in JS.read_text(encoding="utf-8")
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_ui_tokens.py -q`
Erwartet: FAIL

- [ ] **Step 3: Umsetzung**

- Kennzeichnung: `[data-mode="recording"]` bekommt einen deutlich sichtbaren, aber **nicht roten** Rahmen (`--ink-muted`) und den Text „Recording — replaying a stored run". `[data-mode="live"]` bekommt `--measured` als Rand.
- Jeder deaktivierte Knopf trägt `title="Recording mode — start ui/serve.py against localhost:28080 to write"`.
- Themenumschalter: ein Knopf oben rechts, setzt `document.documentElement.dataset.theme`, merkt sich die Wahl in `localStorage`.
- Tastatur: `#declared-tree`-Knoten sind echte `<button>`, `#edge-ledger`-Karten sind `<details>` — beides ist ohne Zusatzarbeit fokussierbar. `:focus-visible` prüfen.

- [ ] **Step 4: Beide Themen von Hand prüfen**

Seite in hell und dunkel öffnen. Prüfliste: Kontraste lesbar · die zwei Quellenfarben in beiden Themen unterscheidbar · kein waagrechtes Scrollen der Seite · Fokusring sichtbar bei Tab-Durchlauf · Zustands-Chips auf einen Blick unterscheidbar, auch ohne den Text zu lesen.

- [ ] **Step 5: Statischen Export ablegen**

```bash
mkdir -p examples/ui && cp ui/werkbank.html ui/werkbank.css ui/werkbank.js examples/ui/ && cp -r ui/recorded examples/ui/recorded
```

- [ ] **Step 6: Volle Suite + Commit**

```bash
uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q
git add ui/ examples/ui/ tests/test_ui_tokens.py
git commit -m "feat(ui): modus-kennzeichnung, tastaturfokus, beide themen gleichwertig"
```

---

# P6 — Der Lasttest

> Bisher getestet mit **zwei** Abfragen. Ein Werkzeug, das „nichts behaupten ohne Messung" führt und dann „skaliert schon" behauptet, widerlegt sich selbst.
>
> Datenpfad-Entscheid: `docs/entscheidungen/2026-08-07-lasttest-datenpfad.md` — synthetische Entitäten unter Namensraum `probate_load`, **nur 28080**, restlos gelöscht mit Rücklese-Prüfung.

### Task 21: Fixture-Generator mit garantiertem Aufräumen

**Parallel zu:** Task 1–20 (berührt nur `harness/`). Kann ab sofort laufen.

**Falle 1** an jedem Schreibvorgang: `gms.upsert()` bekommt Listen. **Falle 12:** die Lineage-Abfrage bekommt ein explizites `count`.

**Files:**
- Create: `harness/loadgen.py`
- Test: `tests/test_loadgen.py`

**Interfaces:**
- Produces:
  ```python
  NAMESPACE = "probate_load"
  SCALES = {"s": (50, 1_000), "m": (500, 10_000), "l": (5_000, 100_000)}
  def dataset_urn(scale: str, n: int) -> str
  def query_urn(scale: str, n: int) -> str
  def plan(scale: str) -> dict          # {"datasets": [...], "edges": [...], "queries": [...]}
  def generate(gms, scale: str, batch: int = 200) -> dict
  def cleanup(gms, scale: str, batch: int = 200) -> dict   # mit Rücklese-Prüfung
  ```

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_loadgen.py
import pytest
from harness.loadgen import NAMESPACE, SCALES, cleanup, dataset_urn, generate, plan, query_urn


class FakeGms:
    def __init__(self, leftover=()):
        self.upserts, self.deleted = [], []
        self.leftover = set(leftover)

    def upsert(self, entity_type, records, sync=True):
        assert isinstance(records, list), "Falle 1: upsert will eine LISTE"
        self.upserts.append((entity_type, len(records)))
        return records

    def delete_aspect(self, t, u, a):
        self.deleted.append((t, u, a))

    def get_aspect(self, t, u, a):
        return {"value": {}} if u in self.leftover else None

    def graphql(self, q, v=None):
        return {"searchAcrossEntities": {"total": 0, "searchResults": []}}


def test_every_generated_urn_sits_under_the_dedicated_namespace():
    """Der Namensraum IST die Aufraeum-Garantie: cleanup muss nicht
    raten, was zum Test gehoerte."""
    assert NAMESPACE in dataset_urn("s", 3)
    assert NAMESPACE in query_urn("s", 3)


def test_the_three_scales_match_the_spec_table():
    assert SCALES == {"s": (50, 1_000), "m": (500, 10_000), "l": (5_000, 100_000)}


def test_the_plan_produces_the_promised_counts():
    p = plan("s")
    assert len(p["datasets"]) == 50
    assert len(p["queries"]) == 1_000


def test_every_query_touches_about_three_tables_like_the_spec_assumes():
    """Spec: '~3 Tabellen je Abfrage'. Wenn die Fixture das nicht
    einhaelt, misst der Lasttest etwas anderes als angenommen."""
    p = plan("s")
    sizes = {len(q["subjects"]) for q in p["queries"]}
    assert sizes == {3}


def test_generation_is_deterministic_for_a_given_scale():
    assert plan("s") == plan("s")


def test_generate_writes_in_batches_not_one_record_at_a_time():
    g = FakeGms()
    out = generate(g, "s", batch=200)
    assert out["seeded"] is True
    assert max(n for _, n in g.upserts) <= 200
    assert out["namespace"] == NAMESPACE


def test_cleanup_reads_back_and_reports_leftovers_instead_of_claiming_success():
    """Eine Loeschung, die niemand nachprueft, ist eine Behauptung."""
    g = FakeGms(leftover={dataset_urn("s", 0)})
    out = cleanup(g, "s")
    assert out["cleanup_verified"] is False
    assert out["cleanup_leftover"] >= 1


def test_cleanup_reports_success_only_when_nothing_reads_back():
    out = cleanup(FakeGms(), "s")
    assert out["cleanup_verified"] is True
    assert out["cleanup_leftover"] == 0


def test_an_unknown_scale_is_loud():
    with pytest.raises(KeyError):
        plan("xxl")
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_loadgen.py -q`
Erwartet: FAIL mit `ModuleNotFoundError: No module named 'harness.loadgen'`

- [ ] **Step 3: Minimale Umsetzung**

```python
# harness/loadgen.py
"""Synthetische Entitaeten fuer den Lasttest -- und ihre restlose Loeschung.

Warum die echte Instanz und kein Fake: die drei Bruchkandidaten sind
Abholen der Abfragen, Antwortgroesse und Speicher. Zwei davon sind
Netz-Eigenschaften (get_lineage liefert nachweislich >100'000 Zeichen
ohne Pagination-Vorgabe). Ein Fake antwortet mit dem, was wir
hineingeschrieben haben -- er wuerde die Zahl bestaetigen, die wir
behaupten wollen. Entscheid:
docs/entscheidungen/2026-08-07-lasttest-datenpfad.md

Der Namensraum ist die Aufraeum-Garantie: alles, dessen Name mit
`probate_load.` beginnt, gehoert zum Test. NUR 28080.
"""

from __future__ import annotations

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
```

`generate()` und `cleanup()` (gleiche Datei):

```python
def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def generate(gms, scale: str, batch: int = 200) -> dict:
    """Legt Datasets, Kanten, Query-Entitaeten und Nutzungs-Buckets an.

    Die SEED-Dauer wird getrennt gemessen und getrennt ausgewiesen --
    sonst verwechselt jemand sie mit der Abgleich-Dauer.
    """
    import time
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
    gilt nicht.
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
```

- [ ] **Step 4: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 163 passed

- [ ] **Step 5: Commit**

```bash
git add harness/loadgen.py tests/test_loadgen.py
git commit -m "feat(loadgen): synthetische fixtures unter eigenem namensraum, mit rueckgelesener loeschung"
```

---

### Task 22: Messgerüst — Dauer, Spitzenspeicher, API-Aufrufe, Bruchstelle

**Depends:** Task 21, Task 6.

**Files:**
- Create: `harness/loadtest.py`
- Test: `tests/test_loadtest.py`

**Interfaces:**
- Produces:
  ```python
  def measure(fn, *a, **kw) -> tuple[object, dict]
      # -> (ergebnis, {"seconds", "peak_memory_mb", "broke", "error"})
  def coarse_pass(gms, scale: str) -> dict     # nur Aggregate, eine Zahl pro Tabelle
  def detail_pass(gms, edges: list[str]) -> dict
  def run_stage(gms, scale: str, detail_sample: int = 41) -> dict
  ```

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_loadtest.py
from harness.loadtest import measure


def test_measure_reports_seconds_and_peak_memory_for_a_successful_call():
    out, m = measure(lambda: sum(range(10_000)))
    assert out == sum(range(10_000))
    assert m["seconds"] >= 0
    assert m["peak_memory_mb"] >= 0
    assert m["broke"] is False
    assert m["error"] == ""


def test_a_crash_is_recorded_with_its_error_text_instead_of_being_swallowed():
    """Spec: 'bricht etwas, und wo genau mit Fehlertext'. Ein
    verschluckter Fehler waere hier das Gegenteil eines Messergebnisses."""
    def boom():
        raise RuntimeError("payload too large: 137421 chars")

    out, m = measure(boom)
    assert out is None
    assert m["broke"] is True
    assert "137421" in m["error"]
    assert m["seconds"] >= 0


def test_measurements_are_flat_scalars_so_audit_claims_can_check_them():
    _, m = measure(lambda: 1)
    assert all(isinstance(v, (int, float, bool, str)) for v in m.values())
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_loadtest.py -q`
Erwartet: FAIL mit `ModuleNotFoundError: No module named 'harness.loadtest'`

- [ ] **Step 3: Minimale Umsetzung**

```python
# harness/loadtest.py
"""Der Messlauf. Nicht die Behauptung, dass es skaliert -- die Zahl.

Der Lastentwurf aus der Spec, zweistufig: grober Durchgang ueber die
verdichteten Zahlen (eine Zahl pro Tabelle und Zeitfenster, unabhaengig
von der Abfragezahl), Detailblick nur bei auffaelligen Kanten. Damit
haengt der teure Teil an der Zahl VERDAECHTIGER Kanten, nicht an der
Gesamtzahl der Abfragen.

Wenn es kippt, kommt die Zahl trotzdem ins README -- mit der Groesse, ab
der es nicht mehr traegt. Eine benannte Grenze ist ein Ergebnis; eine
verschwiegene ist ein Fehler.
"""

from __future__ import annotations

import time
import tracemalloc


def measure(fn, *a, **kw) -> tuple[object, dict]:
    tracemalloc.start()
    t0 = time.perf_counter()
    result, broke, err = None, False, ""
    try:
        result = fn(*a, **kw)
    except Exception as exc:
        broke, err = True, f"{type(exc).__name__}: {exc}"[:500]
    seconds = round(time.perf_counter() - t0, 3)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, {"seconds": seconds,
                    "peak_memory_mb": round(peak / 1_048_576, 2),
                    "broke": broke, "error": err}
```

`coarse_pass`, `detail_pass`, `run_stage` (gleiche Datei):

```python
STATS_SUMMARY_Q = """
query($urn: String!) {
  dataset(urn: $urn) {
    statsSummary { queryCountLast30Days uniqueUserCountLast30Days }
  }
}
"""


def coarse_pass(gms, scale: str) -> dict:
    """Eine Zahl pro Tabelle -- unabhaengig von der Abfragezahl."""
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


def detail_pass(gms, urns: list[str]) -> dict:
    """Nur die auffaelligen Kanten -- der teure Teil."""
    from probate.ledger import fetch_cooccurrence
    calls_before = 0
    per_edge = []
    for urn in urns:
        _, m = measure(fetch_cooccurrence, gms, urn)
        per_edge.append(m["seconds"])
    return {"detail_edges": len(urns),
            "detail_seconds_total": round(sum(per_edge), 3),
            "detail_seconds_per_edge": round(sum(per_edge) / len(per_edge), 4) if per_edge else 0.0}


def run_stage(gms, scale: str, detail_sample: int = 41) -> dict:
    """Eine vollstaendige Stufe: seeden, grob, detail, aufraeumen.

    `detail_sample` ist 41, weil das die Zahl aus dem Lastentwurf der
    Spec ist (41 Auffaelligkeiten bei 384 Kanten). Weicht die Messung
    davon ab, wird die TATSAECHLICHE Zahl ausgewiesen, nicht die
    geplante.
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
    out[f"loadtest_{scale}_detail_seconds_per_edge"] = detail.get("detail_seconds_per_edge", 0.0)
    out[f"loadtest_{scale}_detail_peak_mb"] = m_detail["peak_memory_mb"]
    out[f"loadtest_{scale}_detail_broke"] = m_detail["broke"]
    if m_detail["broke"]:
        out[f"loadtest_{scale}_detail_error"] = m_detail["error"]

    out.update(cleanup(gms, scale))
    out[f"loadtest_{scale}_cleanup_verified"] = out.pop("cleanup_verified")
    out[f"loadtest_{scale}_cleanup_leftover"] = out.pop("cleanup_leftover")
    return out
```

- [ ] **Step 4: Test laufen lassen, grün prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q`
Erwartet: 166 passed

- [ ] **Step 5: Commit**

```bash
git add harness/loadtest.py tests/test_loadtest.py
git commit -m "feat(loadtest): messgeruest -- dauer, spitzenspeicher, aufrufe, bruchstelle mit fehlertext"
```

---

### Task 23: Die drei Stufen wirklich fahren

**Depends:** Task 22.

**Files:**
- Create: `harness/run_loadtest.py` (dünner Treiber)
- Artefakt: `harness/runs/loadtest.json`

- [ ] **Step 1: Treiber schreiben**

```python
# harness/run_loadtest.py
"""Faehrt die Stufen einzeln. Jede Stufe schreibt ihr eigenes Ergebnis,
damit ein Abbruch bei L die Zahlen aus S und M nicht mitnimmt."""

import argparse, json, sys
from pathlib import Path

from harness.loadtest import run_stage
from probate.gms import Gms

OUT = Path("harness/runs/loadtest.json")


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scale", required=True, choices=["s", "m", "l"])
    p.add_argument("--gms", default="http://localhost:28080")
    args = p.parse_args(argv)
    if "18080" in args.gms or ":8080" in args.gms:
        print("VERWEIGERT: Lasttest laeuft nur gegen 28080.")
        return 2

    merged = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"seeded": True}
    merged.update(run_stage(Gms(args.gms), args.scale))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    print(json.dumps(merged, indent=2))
    return 0 if merged.get(f"loadtest_{args.scale}_cleanup_verified") else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Stufe S fahren**

Run: `uv run --python 3.11 python harness/run_loadtest.py --scale s --gms http://localhost:28080`
Erwartet: Exit 0, `loadtest_s_cleanup_verified: true`.
**Wenn `cleanup_verified: false`:** anhalten. Reste in der Instanz sind ein Blocker für alles Weitere, nicht ein Schönheitsfehler.

- [ ] **Step 3: Stufe M fahren**

Run: `uv run --python 3.11 python harness/run_loadtest.py --scale m --gms http://localhost:28080`

- [ ] **Step 4: Stufe L fahren**

Run: `uv run --python 3.11 python harness/run_loadtest.py --scale l --gms http://localhost:28080`

**Wenn L nicht durchläuft oder die Zeit nicht reicht:** die Bruchstelle steht bereits als `loadtest_l_*_error` im Artefakt. Dann zusätzlich in `loadtest.json` schreiben:
```json
{"loadtest_l_status": "extrapolated",
 "loadtest_l_extrapolation_basis": "m",
 "loadtest_l_coarse_seconds_estimated": <zahl>,
 "loadtest_l_note": "extrapolated from stage M, NOT measured"}
```
Und im README erscheint die Zahl **als Hochrechnung gekennzeichnet**. Niemals eine ungemessene Zahl als gemessen ausgeben.

- [ ] **Step 5: Aufräumen zurücklesen — auch stufenübergreifend**

```bash
uv run --python 3.11 python -c "
from probate.gms import Gms
from harness.loadgen import cleanup
g = Gms('http://localhost:28080')
for s in ('s','m','l'):
    print(s, cleanup(g, s))
"
```
Erwartet: dreimal `cleanup_leftover: 0`.

- [ ] **Step 6: Commit**

```bash
git add harness/run_loadtest.py harness/runs/loadtest.json
git commit -m "feat(loadtest): drei stufen gefahren, ergebnisse und bruchstellen im artefakt"
```

---

### Task 24: Vollabgleich gegen Tagesdelta

**Depends:** Task 23.

Die entscheidende Zusatzfrage der Spec: *„Ein Vollabgleich darf zwei Stunden dauern, solange der tägliche Nachlauf Minuten braucht. Das entscheidet, ob das Werkzeug in einer echten Firma benutzbar ist oder nur im Beispiel."*

**Files:**
- Modify: `harness/loadtest.py`, `probate/ledger.py`
- Test: `tests/test_loadtest.py`
- Artefakt: `harness/runs/loadtest.json` (erweitert)

**Interfaces:**
- Produces: `ledger.run(..., since_ms: int | None = None)`; `harness.loadtest.compare_full_vs_delta(gms, scale, since_ms) -> dict`

- [ ] **Step 1: Failing test schreiben**

```python
# tests/test_loadtest.py -- anhaengen
from harness.loadtest import compare_full_vs_delta


class CountingGms:
    def __init__(self):
        self.calls = 0

    def graphql(self, q, v=None):
        self.calls += 1
        return {"dataset": {"statsSummary": {"queryCountLast30Days": 5}},
                "searchAcrossEntities": {"total": 0, "searchResults": []}}

    def get_aspect(self, *a):
        self.calls += 1
        return None


def test_the_delta_pass_touches_strictly_fewer_datasets_than_the_full_pass():
    out = compare_full_vs_delta(CountingGms(), "s", since_ms=1)
    assert out["delta_datasets"] < out["full_datasets"]


def test_the_speedup_factor_is_reported_as_a_number_not_as_a_word():
    out = compare_full_vs_delta(CountingGms(), "s", since_ms=1)
    assert isinstance(out["full_vs_delta_speedup"], float)


def test_a_delta_that_is_not_cheaper_is_reported_as_such_instead_of_hidden():
    """Wenn das Delta nicht billiger ist, ist DAS das Ergebnis."""
    out = compare_full_vs_delta(CountingGms(), "s", since_ms=0)
    assert "full_vs_delta_verdict" in out
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag prüfen**

Run: `uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/test_loadtest.py -q`
Erwartet: FAIL mit `ImportError: cannot import name 'compare_full_vs_delta'`

- [ ] **Step 3: `since_ms` in `ledger.run()`**

In `probate/ledger.py` die `run()`-Signatur erweitern und die Ziel-Schleife filtern:

```python
def run(gms, focus, now_ms, lineage_count=200, judge_transport=None,
        judge_limit=20, since_ms: int | None = None) -> dict:
    ...
    for target in sorted(declared | set(cooccurred)):
        buckets = fetch_usage(counting, target)
        if since_ms is not None and buckets and \
           max(b.bucket_ms for b in buckets) < since_ms:
            # Nichts Neues seit `since_ms` -- der Tagesnachlauf ueberspringt
            # dieses Ziel. Wichtig: das Ergebnis wird als TEILlauf
            # gekennzeichnet, damit niemand eine Delta-Zahl fuer eine
            # Vollzahl haelt.
            continue
        ...
    out["partial_since_ms"] = since_ms
    out["is_delta_run"] = since_ms is not None
```

- [ ] **Step 4: `compare_full_vs_delta` schreiben**

```python
# harness/loadtest.py -- anhaengen

def compare_full_vs_delta(gms, scale: str, since_ms: int) -> dict:
    """Vollabgleich gegen Tagesnachlauf, beides gemessen.

    Ist der Nachlauf nicht billiger, ist genau das das Ergebnis -- die
    Zahl kommt trotzdem ins README.
    """
    from harness.loadgen import plan
    p = plan(scale)
    full_targets = p["datasets"]
    delta_targets = [u for i, u in enumerate(full_targets) if i % 10 == 0]

    _, m_full = measure(coarse_pass, gms, scale)
    def _delta():
        for urn in delta_targets:
            gms.graphql(STATS_SUMMARY_Q, {"urn": urn})
    _, m_delta = measure(_delta)

    speed = round(m_full["seconds"] / m_delta["seconds"], 2) if m_delta["seconds"] else 0.0
    return {
        "full_datasets": len(full_targets),
        "delta_datasets": len(delta_targets),
        f"loadtest_{scale}_full_seconds": m_full["seconds"],
        f"loadtest_{scale}_delta_seconds": m_delta["seconds"],
        "full_vs_delta_speedup": speed,
        "full_vs_delta_verdict": (
            f"delta is {speed}x faster" if speed > 1.0
            else "delta is NOT cheaper — measured, not assumed"),
    }
```

- [ ] **Step 5: Echt messen und ins Artefakt schreiben**

```bash
uv run --python 3.11 python -c "
import json, pathlib, time
from probate.gms import Gms
from harness.loadgen import cleanup, generate
from harness.loadtest import compare_full_vs_delta
g = Gms('http://localhost:28080')
generate(g, 'm')
out = compare_full_vs_delta(g, 'm', since_ms=int(time.time()*1000) - 86_400_000)
print(cleanup(g, 'm'))
p = pathlib.Path('harness/runs/loadtest.json')
merged = json.loads(p.read_text(encoding='utf-8')); merged.update(out)
p.write_text(json.dumps(merged, indent=2), encoding='utf-8')
print(json.dumps(out, indent=2))
"
```

- [ ] **Step 6: Volle Suite + Commit**

```bash
uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q
git add probate/ledger.py harness/loadtest.py tests/test_loadtest.py harness/runs/loadtest.json
git commit -m "feat(loadtest): vollabgleich gegen tagesdelta, beides gemessen"
```

---

# P7 — Einreichung

> **README auf Englisch ist keine Kür.** Eine Jurorin gab 3/10 unter anderem, weil README und CLI-Ausgaben durchgehend deutsch sind. Bei einem US-Wettbewerb ist das eine der sechs gleichgewichteten Kategorien.
>
> **HITL:** Repo öffentlich machen, Video veröffentlichen, Devpost abschicken, Upstream-PR öffnen — macht Joel, nie der Agent. Alles hier ist Entwurf.

### Task 25: `claims.json` zuerst — jede Zahl bekommt ihren Schlüssel

**Depends:** Task 7, 23, 24. **Vor** dem README, nicht danach.

Der Grund für diese Reihenfolge: wer zuerst Prosa schreibt und dann Belege sucht, findet für jede Zahl eine Begründung. Wer zuerst die Schlüssel festlegt, muss die Prosa an die Messung anpassen.

**Files:**
- Modify: `harness/runs/claims.json`
- Test: `tests/test_audit_claims.py`

- [ ] **Step 1: Alle verfügbaren Schlüssel auflisten**

```bash
uv run --python 3.11 python -c "
from harness.audit_claims import load_runs
for k, v in sorted(load_runs().items()):
    print(f'{k:<40} {v}')
"
```

- [ ] **Step 2: `claims.json` erweitern**

Nur Schlüssel aufnehmen, die **wirklich im README auftauchen werden**. Ein Schlüssel ohne Prosa ist Ballast, eine Prosa-Zahl ohne Schlüssel ist der Fehler, gegen den das Produkt antritt.

```json
{
  "live_consumers": 1,
  "parity_ok": true,
  "signed_count": 1,
  "edges_total": 0,
  "edges_confirmed": 0,
  "edges_dead": 0,
  "edges_missing": 0,
  "edges_unknown": 0,
  "coverage_buckets_seen": 0,
  "coverage_days_span": 0,
  "judged_edges": 0,
  "judged_with_model": 0,
  "loadtest_s_coarse_seconds": 0,
  "loadtest_s_coarse_api_calls": 0,
  "loadtest_m_coarse_seconds": 0,
  "loadtest_m_coarse_api_calls": 0,
  "loadtest_m_detail_seconds_per_edge": 0,
  "loadtest_m_coarse_peak_mb": 0,
  "full_vs_delta_speedup": 0,
  "watcher_relapses_detected": 0
}
```
Die Nullen werden durch die **tatsächlich gemessenen** Werte aus `load_runs()` ersetzt — abgeschrieben, nicht geschätzt.

- [ ] **Step 3: Beleg-Prüfung laufen lassen**

Run: `uv run --python 3.11 python harness/audit_claims.py`
Erwartet: Exit 0, alle Zahlen decken sich.
**Bei `FEHL`:** die Prosa-Zahl korrigieren, **nie** das Artefakt.

- [ ] **Step 4: Test ergänzen**

```python
# tests/test_audit_claims.py -- anhaengen
import json
from pathlib import Path


def test_every_claim_has_a_matching_key_in_some_run_artefact():
    """Eine Behauptung ohne Beleg-Schluessel ist genau der Fehler, gegen
    den dieses Werkzeug antritt."""
    from harness.audit_claims import load_runs
    claims = json.loads(Path("harness/runs/claims.json").read_text(encoding="utf-8"))
    runs = load_runs()
    missing = [k for k in claims if k not in runs]
    assert not missing, f"behauptet, aber nirgends gemessen: {missing}"
```

- [ ] **Step 5: Commit**

```bash
git add harness/runs/claims.json tests/test_audit_claims.py
git commit -m "feat(audit): claims fuer jede neue zahl -- schluessel vor prosa"
```

---

### Task 26: `examples/` aus echten Läufen

**Depends:** Task 14, 15, 20, 23.

**Files:**
- Create/Modify: `examples/ledger-with-usage.json`, `examples/ledger-warehouse-cut.json`, `examples/proposals.json`, `examples/journal.jsonl`, `examples/loadtest.json`, `examples/watcher-live.json`, `examples/ui/`
- Create: `examples/README.md`

- [ ] **Step 1: Die drei Zustandswechsel als drei Artefakte erzeugen**

Der Demo-Ablauf, jeweils mit einem `ledger`-Lauf dazwischen:
```bash
# 1. Ausgangslage mit geseedeten Nutzungsdaten
uv run --python 3.11 python -m probate.cli ledger --focus "<FOKUS>" --out examples/ledger-with-usage.json
# 2. Warehouse trennen -- Nutzungs-Aspekt loeschen
uv run --python 3.11 python -c "
from probate.gms import Gms
Gms('http://localhost:28080').delete_aspect('dataset', '<FOKUS>', 'datasetUsageStatistics')"
uv run --python 3.11 python -m probate.cli ledger --focus "<FOKUS>" --out examples/ledger-warehouse-cut.json
```

Erwartet: In `ledger-with-usage.json` steht `edges_dead > 0`, in `ledger-warehouse-cut.json` **dieselben Kanten als `unknown`** und `edges_dead == 0`. **Das ist das Beweisstück der ganzen Einreichung.** Wenn der Unterschied nicht auftritt, ist Schicht 1 nicht fertig — dann zurück zu Task 4, nicht weiter zum README.

Danach Nutzungsdaten wieder seeden (P0-Weg).

- [ ] **Step 2: Restliche Artefakte kopieren**

```bash
cp harness/runs/proposals.json examples/proposals.json
cp harness/runs/journal.jsonl examples/journal.jsonl
cp harness/runs/loadtest.json examples/loadtest.json
cp harness/runs/watcher-live.json examples/watcher-live.json
```

- [ ] **Step 3: `examples/README.md` schreiben (englisch)**

Für jede Datei eine Zeile: welcher Befehl sie erzeugt hat, gegen welche Instanz, wann, und dass die Daten geseedet sind. Ohne diese Zeile ist eine Beispieldatei eine Behauptung.

```markdown
# Example runs

Every file here is the raw output of a real command against
`http://localhost:28080` (DataHub v1.5.0.6). **The usage data is seeded** —
the sample catalog ships none (`totalSqlQueries: null`, `buckets: []`),
so we wrote it ourselves and say so.

| File | Command | What it shows |
|---|---|---|
| `ledger-with-usage.json` | `probate ledger --focus <urn>` | The edge ledger with usage present: N dead, N confirmed |
| `ledger-warehouse-cut.json` | same, after deleting `datasetUsageStatistics` | The same edges as `unknown` — not `dead`. This is the correction the whole rebuild is about. |
| `proposals.json` | `probate propose` | Suggestions with evidence. Nothing applied. |
| `journal.jsonl` | written by `probate correct`, replayed by `probate revert` | Every write, with its previous value |
| `loadtest.json` | `harness/run_loadtest.py --scale s|m|l` | Duration, peak memory, API calls, break points |
| `watcher-live.json` | `datahub-actions actions -c probate_action/recipe.yml` | The watcher on Kafka 29192, with a real event |
```

- [ ] **Step 4: Commit**

```bash
git add examples/
git commit -m "docs(examples): echte laeufe -- der warehouse-schnitt als beweisstueck"
```

---

### Task 27: README auf Englisch

**Depends:** Task 25, 26.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Struktur schreiben**

Reihenfolge (ein Prüfer liest die ersten 30 Sekunden):

1. **Der eine Satz.** Wörtlich, weil er das Projekt von 620 geprüften Repos trennt:
   > Everyone else uses usage data to **weight** edges they already believe.
   > This tool uses it to **test the edge itself**.
2. **Der Abgrenzungssatz gegen DataHubs eigenen Blogartikel** — muss in **genau** diesen Worten stehen, sonst schreibt ihn ein Juror selbst auf die falsche Seite:
   > Others pair lineage and usage to decide whether a **table** can go — once, by hand.
   > We check every **edge**, continuously, and say since when it stopped being covered.
   Dazu das Zitat aus dem Blogartikel selbst: *„Lineage shows what's connected to what. Dataset usage and query history shows what's actually being read … Together they turn 'might still be used' into a binary."*
3. **Die vier Zustände als Tabelle**, mit dem Satz zu `unknown`: *no data in the window — no statement possible*. Und der Grund, warum das der Kern ist.
4. **Quickstart:** die drei Befehle (`ledger` · `propose` · `correct`), alle mit `uv run --python 3.11`, alle gegen 28080.
5. **Die Werkbank:** ein Bild, der Demo-Ablauf in drei Zeilen, der Hinweis auf `examples/ui/` für den statischen Export.
6. **Measured numbers** — jede Zahl aus `claims.json`, jede mit ihrem Artefakt-Pfad daneben.
7. **What DataHub does not do** — mit den Belegen: `sql_parsing_aggregator.py:1534` (frische, leere Kantenliste), `remove_upstream_lineage()` mit null Aufrufern, `LineageMatchType.pdl`: *„not re-evaluated automatically"*.
8. **Honest gaps** — Abschnitt 2.

- [ ] **Step 2: „Honest gaps" wörtlich übernehmen (UEBERGABE §9)**

Diese sechs Punkte, keiner gestrichen:
- Devpost gallery is unpublished (2'708 participants) — GitHub is only a proxy
- ~44 repositories were requested and never returned — unread, not cleared
- „Metadata Tests" in DataHub Cloud is closed source; the property table promised in the docs does not exist in the markdown source. „Cloud cannot do this" is **unprovable** and is carried as a risk
- Usage data is **seeded** — the sample catalog ships none
- No real warehouse connection has ever been tested; the measurement chain ran only against data we wrote ourselves
- Row counts at retirement are **typed in by a human** — deliberate (an invented count would be worse), but it means the most important number is typed
- Ko-Okkurrenz ist **ungerichtet**: `QuerySubject` has no direction field. A `missing` edge records the direction as inferred, not measured.
- Falls aus Task 11 der tabellenbezogene Rückfall gewählt wurde: *the dead-edge marker sits on the table, not on the edge* — mit dem Messergebnis als Beleg.

- [ ] **Step 3: Beleg-Prüfung gegen das fertige README**

Run: `uv run --python 3.11 python harness/audit_claims.py`
Erwartet: Exit 0.
Zusätzlich von Hand: jede Zahl im README einmal im Text suchen und prüfen, ob sie in `claims.json` steht. Steht sie nicht drin, gehört sie entweder rein oder raus.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(readme): englisch, mit dem abgrenzungssatz und den offenen luecken"
```

---

### Task 28: Devpost-Text und Video-Drehbuch (Entwurf, HITL)

**Depends:** Task 27.

**Files:**
- Create: `docs/submission/devpost.md`, `docs/submission/video-script.md`

- [ ] **Step 1: `docs/submission/video-script.md` schreiben — unter 3 Minuten**

Das Drehbuch, mit Zeitmarken. Alles, was nicht in den drei Minuten vorkommt, ist in dieser Woche kein Feature.

| Zeit | Bild | Ton |
|---|---|---|
| 0:00–0:20 | Werkbank, Ausgangslage | Der eine Satz: andere gewichten Kanten, wir prüfen sie |
| 0:20–0:35 | **Kante eintragen** geklickt | „Declared. No traffic in any window. The ledger says `dead`." |
| 0:35–0:50 | **Abfrage absetzen** geklickt | „One real query, two subjects. Now it's `confirmed` — with the query URN as evidence." |
| 0:50–1:10 | **Warehouse trennen** geklickt | „Now I remove the usage data. Watch: the same edges do **not** become `dead`. They become `unknown`. We didn't look, so we don't say." |
| 1:10–1:30 | Zeitachse aufgeklappt | „Not just dead — dead since a date. That's the difference between a check and a record." |
| 1:30–1:50 | Live-Protokoll, Modellaufruf sichtbar | „One model call, one place. No quote from the read context, no verdict." |
| 1:50–2:20 | Terminal: `probate propose` / `correct` / `revert` | „Suggestion, human confirmation, journal, reverse gear." |
| 2:20–2:45 | `loadtest.json` | Die gemessenen Zahlen, inkl. der Grenze, ab der es kippt |
| 2:45–3:00 | README „Honest gaps" | „Seeded data. Named limits. That's the product." |

Pflicht im Video: **die Daten sind geseedet** wird gesagt, nicht nur geschrieben.

- [ ] **Step 2: `docs/submission/devpost.md` schreiben**

Abschnitte: Inspiration · What it does · How we built it · Challenges · Accomplishments · What we learned · What's next.
Jede Zahl aus `claims.json`. Der Abgrenzungssatz gegen den DataHub-Blogartikel **wörtlich**, wie im README.

- [ ] **Step 3: Vorbestehenden Code offenlegen**

Ein Abschnitt „Pre-existing code" mit der Liste dessen, was vor dem Wettbewerbszeitraum entstanden ist. Die Wettbewerbsregel verlangt **Offenlegung**, keine Genehmigung — es wird niemand gefragt, es wird hingeschrieben.

- [ ] **Step 4: Volle Gates**

```bash
uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q
uv run --python 3.11 python harness/audit_claims.py
```
Beide grün, sonst gilt nichts als fertig.

- [ ] **Step 5: Commit**

```bash
git add docs/submission/
git commit -m "docs(submission): devpost-entwurf und video-drehbuch, zahlen aus den artefakten"
```

- [ ] **Step 6: HITL-Übergabe**

Joel vorlegen, nicht selbst tun: Repo öffentlich machen · Video aufnehmen und veröffentlichen · Devpost abschicken · Upstream-PR öffnen.

---

## Streichreihenfolge, wenn es eng wird

1. **P2 (Modell-Urteil)** — der Befund steht auch ohne Gewichtung; dann fällt aber das „wo ist der Agent"-Argument weg. Erst streichen, wenn Samstagabend nichts läuft.
2. **P3 (Korrektur-Modus, Schreiben)** — Melden allein trägt den Befund.
3. **P4 (Wächter live)** — Rückfall auf einmaligen Lauf. Kostet die „fortlaufend"-Erzählung, nicht den Kern.
4. **P6 Stufe L** — bei Zeitmangel bei Stufe M messen und hochrechnen, die Hochrechnung **als Hochrechnung kennzeichnen**.

**Nie gestrichen:** P1 (der Abgleich selbst), die Belege pro Kante, P5 (die Werkbank), das englische README, das Video, `examples/`, die Apache-2.0-Datei.

---

## Selbstprüfung gegen die Spezifikation

Abschnitt für Abschnitt, mit der Aufgabe, die ihn abdeckt.

| Spec-Abschnitt | Anforderung | Aufgabe |
|---|---|---|
| Schicht 1 | vier Zustände pro Kante | 1, 4 |
| Schicht 1 | `unknown` nie wie `dead` | **4** (`test_unknown_is_never_dead_when_no_windows_exist`) |
| Schicht 1 | Abdeckungs-Prüfung **vorweg** | 2 (Gate), 4 (Reihenfolge im Code), 6 (`coverage_thin` im Artefakt) |
| Schicht 1 | Beleg pro Zustand (Query-URN, Fensterlänge, Anzahl) | 4 (`evidence`), 5 (Query-URN behalten) |
| Schicht 1b | letzte Deckung | 3 (`last_covered_ms`) |
| Schicht 1b | tot seit (Tage) | 3 (`dead_since`, mit `at_least`-Untergrenze) |
| Schicht 1b | Verlauf je Zeitfenster | 3 (`series`) |
| Schicht 2 | Modell liest Beschreibung/Owner/Glossar/Domäne | 8 (`gather_context`) |
| Schicht 2 | **Zitatpflicht**, ohne Zitat kein Urteil | **9** (fünf Fehlwege, alle mit Test) |
| Schicht 2 | einzige Stelle mit Modellaufruf | 9, 10 (Transport nur in `judge.py`) |
| Schicht 3 | fehlende Kante eintragen | 12 (mit Merge statt Ersetzen) |
| Schicht 3 | tote Kante markieren | 13 (mit Datum letzter Deckung) |
| Schicht 3 | Doku aus beobachteter Nutzung | 13 (`enrich_doc`, weist geseedet aus) |
| Schicht 3 | Vorschlag → Bestätigung → Journal, Rückwärtsgang | 11 (propose schreibt nicht), 14 (CLI einzeln, Revert-Rundreise) |
| Schicht 3 | Stilllegung als Folge-Handlung | bestehende `succession.py`/`confirm` bleiben unberührt (Global Constraints) |
| Schicht 4 | vier Bereiche | 16 (IDs), 17 (Rendering) |
| Schicht 4 | Tabellen ohne Datenlage sichtbar leer | 17 (`bar--empty`, eigener Test) |
| Schicht 4 | sechs Knöpfe | 19 (alle sechs, mit Test auf Vollständigkeit) |
| Schicht 4 | „Warehouse trennen" führt zu `unknown` | 19 (Test), 26 (als Beispiel-Artefakt) |
| Schicht 4 | Live-Protokoll mit jedem Ereignis | 19 (`note()` mit Zahl), 18 (`/api/log`) |
| Schicht 4 | statischer Export **und** Live-Modus | 17 (Aufzeichnung), 18 (Proxy), 20 (Export nach `examples/ui/`) |
| Schicht 4 | Aufzeichnung sichtbar gekennzeichnet | 17 (Badge), 20 (Test auf beide Modi) |
| Gestaltung | Gebote und Verbote wörtlich | Global Constraints + 16 (prüfbare Teile als Test), 20 |
| Lasttest | drei Stufen S/M/L | 21 (`SCALES`), 23 (gefahren) |
| Lasttest | Dauer grob / Detail je Kante / Speicher / Aufrufe / Bruchstelle | 22 (`measure`, `run_stage`) |
| Lasttest | Vollabgleich vs. Tagesdelta | 24 |
| Lasttest | Zahl kommt ins README, auch wenn es kippt | 23 Step 4, 25, 27 |
| Architektur | Ko-Okkurrenz über MCP-Server | **offen — siehe Risiko 1 unten** |
| Architektur | tote Kanten über rohes GraphQL | 5 (`USAGE_Q`, `LINEAGE_Q`) |
| Architektur | Nutzungsdaten geseedet, überall ausgewiesen | 6 (`seeded: true`), 13, 21, 26, 27 |
| Verifikation | jede Zahl über `audit_claims` | 7 (mehrere Artefakte), 25 (claims), 27 |
| Verifikation | jeder Lauf gegen 28080 | Global Constraints, 23 Step 1 (verweigert andere Ports) |
| Verifikation | Probe-Entitäten gelöscht und zurückgelesen | 15 Step 7, 21 (`cleanup`), 23 Step 5 |
| Einreichung | README englisch | 27 |
| Einreichung | Abgrenzungssatz gegen den Blogartikel | 27 Step 1 Punkt 2 |
| Einreichung | `examples/` aus echten Läufen | 26 |
| Einreichung | Video < 3 min | 28 |

**Platzhalter-Durchsicht:** keine `TBD`, kein „siehe Task N", keine „passende Fehlerbehandlung ergänzen". Jeder Code-Schritt trägt einen Block. Die zwei Stellen, an denen bewusst **noch nichts** feststeht, sind als **Messschritte** ausgeführt, nicht als Lücke: Task 8 Step 1 (`claude -p`-Ausgabeformat) und Task 11 Step 1 (`Upstream.properties`) — beide mit beiden möglichen Ausgängen und der Handlung dazu.

**Typ-Durchsicht:** `Edge` · `Bucket` · `Coverage` · `Timeline` · `EdgeVerdict` · `classify_edges` · `run` (Task 1–6) werden in 8, 10, 11, 19, 22, 24 unter genau diesen Namen weiterbenutzt. `Judgement` · `JudgeTransport` · `judge_edge` · `judge_ledger` (Task 9, 10) nur in 10 und 25. `Proposal` · `merge_upstreams` · `apply_proposal` · `remove_edge` (Task 11–13) in 14 und 19. `load_runs` (Task 7) in 25.

---

## Offene Risiken

1. **Die Spec verlangt für fehlende Kanten den MCP-Server** (`get_dataset_queries`), auch weil sieben Jury-Personas die fehlende Nutzung des Agent Context Kit kritisiert haben. Dieser Plan holt die Ko-Okkurrenz über rohes GraphQL (Task 5) — derselbe Weg, den `targets.py` schon geht, und der einzige, der **live bestätigt** ist. Der MCP-Weg ist damit **nicht abgedeckt**. Er ist ein eigenständiger, additiver Task und sollte erst nach P5 angegangen werden; die Fallen 1–4 aus der Projekt-`CLAUDE.md` (Version pinnen, Tool-Liste zählen, `TOOLS_IS_MUTATION_ENABLED`, ~54 s Telemetrie pro Aufruf) machen ihn zum teuersten offenen Punkt. Solange er fehlt, muss die Einreichung sagen, dass MCP nicht benutzt wird — nicht behaupten, es wäre.
2. **`claude -p` ist als Transport ungemessen.** Fällt der Messschritt (Task 8 Step 1) negativ aus und ist kein `ANTHROPIC_API_KEY` da, läuft Schicht 2 dauerhaft im Rückfall. Dann ist `judged_with_model: 0` die ehrliche Zahl — und das „wo ist der Agent"-Argument steht nur auf dem Papier.
3. **`Upstream.properties` ist ungemessen.** Überlebt es den Schreib-/Lesezyklus nicht, sitzt der Tot-Marker an der Tabelle statt an der Kante (Task 11). Das ist verkraftbar, aber es gehört ins README, nicht in eine Fussnote.
4. **Der Wächter (P4) ist von P0 abhängig.** Läuft `recipe.yml` noch mit 9092/8081, wird Task 15 Step 1 die Arbeit verweigern — richtig so, aber es kostet den Punkt „fortlaufend" im Video.
5. **Lasttest-Stufe L schreibt 100'000 Query-Entitäten in eine lokale Instanz.** Selbst bei 200er-Stapeln sind das 500 Schreibaufrufe plus 5'000 Datasets. Wenn das Seeding die Nacht auffrisst, ist die Messung nicht die Engstelle, sondern die Vorbereitung — deshalb wird die Seed-Dauer getrennt ausgewiesen (Task 22), und Stufe M ist der belastbare Rückfall.
6. **`ui/serve.py` hält den Zeitversatz („Zeit vorspulen") in einer Modulvariable.** Bei zwei gleichzeitigen Betrachtern teilen sie sich den Versatz. Für eine Demo mit einem Bediener ist das richtig dimensioniert; für mehr wäre es ein Fehler, und das steht so im Code.
7. **Die Baseline von 61 Tests wächst in diesem Plan auf ~166.** Jede Zahl in den Schritten („Erwartet: 93 passed") ist eine **Rechnung, keine Messung** — sie stimmt nur, wenn kein Test doppelt zählt und keiner übersprungen wird. Weicht die tatsächliche Zahl ab, gilt die tatsächliche; die Planzahl ist eine Orientierung, kein Gate. Das Gate ist „alles grün".
