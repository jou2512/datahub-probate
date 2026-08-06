# Entscheid: Query-Quellen-Gate in classify_edges (Task 4, Fix-Runde 1)

*07.08.2026, 01:20, Controller (Fable) — Joel schläft, Entscheid nach Autonomie-Rahmen.*

## Anlass

Der Opus-Review von Task 4 fand: Das Abdeckungs-Gate beweist, dass wir auf die
**Nutzungs-Statistik** geschaut haben (`datasetUsageStatistics`-Buckets) — aber das
`dead`/`confirmed`-Urteil ruht auf der **Query-Ko-Okkurrenz**, einer anderen Quelle.
Ist der Query-Index leer oder nicht erreichbar (Falle 11 macht das realistisch), würde
jede deklarierte Kante mit Nutzungsfenstern als `dead` klassifiziert — der Ursprungsbug,
eine Ebene höher.

## Was stand zur Wahl

a) `coverage_by_urn` als Query-Index-Abdeckung umdefinieren (dann wäre
   `coverage_from_buckets` die falsche Fabrik, Task-2-Umbau).
b) Zusätzliches fokus-weites Gate `queries_seen: int` (Anzahl geholter Query-Entitäten,
   die den Fokus berühren) mit differenzierter Regel.
c) Nichts tun (Brief-Stand) und das Problem an Task 5 (Beschaffung) delegieren.

## Gewählt: (b), mit dieser Regel

Für eine deklarierte Kante fokus→ziel, deren Ziel Nutzungsfenster hat:

1. Zeitachse zeigt **null Verkehr** im Fenster → `dead` (Beleg: Fenster mit Null —
   nichts lief, also lief auch nichts über die Kante).
2. Verkehr **> 0** im Fenster **und** `queries_seen == 0` → `unknown`
   (Grund: „verkehr gemessen, aber query-quelle leer — kante nicht prüfbar").
   Wir können „keine Query-Ingestion" nicht von „Queries berühren den Fokus nicht"
   unterscheiden.
3. Verkehr **> 0** und `queries_seen > 0` und kein Paar-Query → `dead`
   (starker Beleg: die Query-Quelle wurde befragt und kennt die Kante nicht).

## Warum

`dead` braucht Beleg aus der Quelle, über die geurteilt wird. Nutzungsfenster belegen
nur die Nutzungs-Quelle. Die Regel setzt die Spec-Kernaussage („jede Aussage trägt ihr
Beleg-Artefakt oder wird zu `unbekannt`") auf Quellen-Ebene durch — genau das
Unterscheidungsmerkmal des Produkts.

## Was müsste passieren, damit es falsch war

Wenn in realen DataHub-Instanzen der Query-Index nie leer sein kann, solange Nutzung
gemessen wird (d.h. beide Quellen technisch gekoppelt sind), wäre Regel 2 totes
Gewicht — aber harmlos konservativ: sie erzeugt `unknown` statt einer falschen
Behauptung, nie umgekehrt.

[Einschätzung des Controllers: deckt sich mit Joels Spec-Kernregel; kein
„hätte-anders-gewollt"-Verdacht. Die Devpost-Erzählung gewinnt sogar: „unser Reviewer
fand die Bug-Klasse im eigenen Code, das Gate beweist die These".]
