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
