# Entscheid: Seed-Beschreibungen dürfen den Zielzustand nicht verraten

*07.08.2026, 02:10, Controller (Fable) — Joel schläft, Entscheid nach Autonomie-Rahmen.*

## Anlass

Der Review von Task 8 (Judge-Kontext) las die Live-Antwort und fand: die einzige nicht-leere
Textquelle, die das Modell je sieht, lautet sinngemäss

> `[probate-seedlab] Kuenstlich eingespielte Demonstrationsdaten. Rolle=upstream,
> Ziel-Kanten-Zustand=confirmed.`

Die Beschreibung nennt also **das Ergebnis, das der Prüfer erst herleiten soll**. Zusätzlich
setzt `harness/seed_lineage_lab.py` gar keine `ownership`/`glossaryTerms`/`domain`-Aspekte
(per Grep belegt: null Treffer) — das Modell hätte ausserhalb dieser einen Zeile nichts.

Damit wäre Schicht 2 eine Attrappe: ein Modell, das ein Etikett zurückliest, das im Feld steht.
Genau der Vorwurf, den ein Juror in dreissig Sekunden formuliert.

## Was stand zur Wahl

a) So lassen und in der Demo erklären, dass die Beschreibungen selbst-etikettiert sind.
b) Beschreibungen organisch umschreiben (echte Geschäftssprache) und `ownership`,
   `glossaryTerms`, `domain` als echte Aspekte seeden — der Zustand bleibt unverändert, weil
   er aus Lineage + Nutzung + Queries stammt, nicht aus Text.
c) Ein zweites, „realistisches" Labor daneben bauen.

## Gewählt: (b)

Der Zielzustand verschwindet aus jedem Textfeld. Die Seed-Kennzeichnung als künstliche Daten
**bleibt** (Regel: geseedete Daten überall ausweisen) — aber sie steht künftig in einem
eigenen Feld/Präfix, das den Zustand nicht verrät. Die vier Zustände dürfen sich durch diese
Änderung nicht verschieben; das wird nachgemessen, nicht angenommen.

## Warum nicht (a)

Weil die Erklärung den Mangel nicht heilt: Wenn die einzige urteilsfähige Quelle die Antwort
enthält, ist das Urteil kein Urteil. Und (c) kostet eine Nacht für etwas, das eine
Textänderung erledigt.

## Was müsste passieren, damit es falsch war

Wenn sich zeigt, dass die vier Zustände doch von den Beschreibungen abhängen (dürfen sie
nicht — sie kommen aus Kanten, Buckets und Query-Subjects), wäre die Änderung riskant. Die
Gegenprobe ist Pflicht: `harness/seedlab_verdicts.py` muss nach der Anreicherung dieselben
vier Zustände liefern wie vorher, sonst ist der Klassifikator textabhängig und das wäre ein
schwerer Befund über das Produkt, nicht über die Seeds.

[Einschätzung: hier hätte Joel vermutlich genauso entschieden — die Regel „nichts behaupten,
was nicht gemessen ist" verbietet ein Urteil, dessen Antwort in der Frage steht.]
