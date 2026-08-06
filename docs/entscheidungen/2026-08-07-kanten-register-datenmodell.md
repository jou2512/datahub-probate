# Entscheid: Datenmodell des Kanten-Registers

*2026-08-07 · betrifft `probate/ledger.py` (neu) und `probate/targets.py` (bestehend)*

## Was stand zur Wahl

**A — `targets.py` erweitern.** `Targets` bekommt Kanten-Objekte, Zeitstempel und einen
vierten Zustand. Ein Modul, das den Vergleich vollständig kennt.

**B — `ledger.py` daneben, `targets.py` unverändert.** Das Register benutzt
`targets.classify()` für die reine Mengenarithmetik und legt Abdeckung, Zeitachse und
den vierten Zustand darüber.

**C — Kanten als Tupel `(up, down)` statt eigenem Typ**, Zustände als `Enum`,
Zeitachse als flache Liste von Dicts.

## Was gewählt

**B, mit eigenen gefrorenen Typen (`Edge`, `Bucket`, `Coverage`, `Timeline`,
`EdgeVerdict`), Zuständen als Zeichenketten aus einer Modulkonstante, und der Zeitachse
als Tupel von `Bucket`.**

Konkret:

```python
STATES = ("confirmed", "dead", "missing", "unknown")

@dataclass(frozen=True)
class Edge:
    upstream: str
    downstream: str
    def key(self) -> str: return f"{self.upstream}->{self.downstream}"

@dataclass(frozen=True)
class Coverage:
    buckets_seen: int
    oldest_bucket_ms: int | None
    newest_bucket_ms: int | None
    reason: str                      # leer = abgedeckt, sonst warum nicht
    @property
    def has_window(self) -> bool: return self.buckets_seen > 0

@dataclass(frozen=True)
class Timeline:
    buckets: tuple[Bucket, ...]      # () = wir haben nichts gesehen
```

`targets.py` wird **nicht angefasst**. `ledger.classify_edges()` ruft es nicht einmal
auf — die Mengenarithmetik ist dort dreizeilig und die Kanten-Klassifikation braucht die
Abdeckung als Gate davor, also eine andere Reihenfolge.

## Warum

**1. Der vierte Zustand ist nicht aus Mengen ableitbar.** `targets.classify()` ist reine
Mengenarithmetik über zwei Mengen. `unknown` entsteht nicht aus dem Verhältnis von
`declared` zu `measured`, sondern aus einer **dritten** Information: gibt es überhaupt
Zeitfenster? Diesen Parameter in `classify()` zu schieben würde eine Funktion, die vier
grüne Tests hat und in `cli.py` an zwei Stellen (`start`, `apply`) hängt, drei Tage vor
der Frist umbauen. Der Nutzen wäre ein gesparter Import.

**2. Die Unterscheidung steckt im Typ, nicht in einem Flag.** Das ist der eigentliche
Grund für `Timeline.buckets: tuple[Bucket, ...]` statt `list[dict] | None`:

- `buckets == ()` → wir haben **nicht hingesehen** → `unknown`
- `buckets != ()` und alle `total_sql_queries == 0` → wir haben hingesehen, es ist
  **nichts passiert** → `dead`

Beides ergäbe bei einer Summierung `0`. Genau diese Summierung war der Fehler, den der
Umbau behebt (Spec, Zeile 108–110). Wer das als `queries: int = 0` modelliert, hat den
Fehler wieder eingebaut, egal was in der Dokumentation steht.

**3. Zeichenketten statt `Enum`, weil das Artefakt JSON ist.** `ledger.json` wird von
`audit_claims.py`, von der Werkbank (JavaScript) und von `examples/` gelesen. Ein `Enum`
kostet an jeder Grenze ein `.value` und bringt keine Sicherheit, die ein Test nicht
billiger liefert — der entscheidende Test lautet „`unknown` wird nie zu `dead`", und der
vergleicht ohnehin Werte.

**4. `Edge` als Typ statt Tupel, weil die Kante drei Rollen hat:** Dict-Schlüssel,
JSON-Schlüssel (`"up->down"`) und lesbare Feldzugriffe im Urteilscode
(`verdict.edge.downstream`). Ein Tupel kann das erste, aber `e[1]` in `judge.py` ist eine
Fehlerquelle, die man nicht sieht.

**5. Richtung ist ehrlich getrennt.** Deklarierte Kanten haben eine Richtung (die
Lineage-Abfrage liefert `DOWNSTREAM`). Ko-Okkurrenz hat **keine** —
`QuerySubject` nennt nur `entity`, kein Richtungsfeld. Eine `missing`-Kante trägt deshalb
das Feld `direction_evidence: "co-occurrence (undirected)"` und wird in der
Fokus-Richtung notiert, nicht als gemessene Richtung ausgegeben. Das gehört ins
Datenmodell, weil es sonst beim Schreiben (P3) als Tatsache in den Katalog wandert.

## Was müsste passieren, damit es falsch war

- **Wenn `targets.py` nach dem Umbau nirgends mehr aufgerufen wird**, ist die Trennung
  Ballast — dann sind es zwei Module, die dasselbe halb tun. Prüfpunkt: bleiben
  `cli.py start` und `cli.py apply` bestehen? Ja, sie tragen die Stilllegung als
  Folge-Handlung (Spec Schicht 3). Solange das gilt, trägt die Trennung.
- **Wenn der Lasttest zeigt, dass gefrorene Dataclasses bei 5'000 Kanten am Kopieraufwand
  scheitern** (Stufe L), muss das Register auf Dicts umgestellt werden. Messbar in P6,
  Aufgabe 21 — die Zahl steht dann im Artefakt, nicht in einer Vermutung.
- **Wenn sich herausstellt, dass Nutzungs-Buckets pro Kante existieren** (statt nur pro
  Dataset), ist `Timeline` am falschen Objekt aufgehängt. Nach heutigem Stand ist das
  widerlegt: `usageStats` hängt an `dataset(urn:)`, nicht an einer Kante. Falls die
  Detail-Ebene (Query-Entitäten) doch brauchbare Zeitstempel liefert, wird `Timeline`
  **ergänzt**, nicht ersetzt — das ist in P1 als Messschritt eingeplant, nicht als
  Annahme.
