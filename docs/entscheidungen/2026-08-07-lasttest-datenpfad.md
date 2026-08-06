# Entscheid: Datenpfad des Lasttests

*2026-08-07 · betrifft `harness/loadgen.py` und `harness/loadtest.py` (beide neu)*

## Was stand zur Wahl

**A — Gegen die vorhandenen Katalog-Entitäten messen.** Nichts anlegen, nichts aufräumen.

**B — Gegen ein `FakeGms` im Speicher messen.** Kein Netz, beliebig grosse Zahlen,
Sekunden statt Stunden.

**C — Synthetische Entitäten in die echte Instanz 28080 schreiben**, unter eigenem
Namensraum, messen, restlos löschen und die Löschung zurücklesen.

## Was gewählt

**C.** Namensraum `probate_load` — jedes Dataset heisst
`probate_load.<stufe>.t<NNNN>`, jede Query-Entität trägt die Kennung
`probate-load-<stufe>-<n>` im URN. Drei Stufen (S 50/1'000 · M 500/10'000 ·
L 5'000/100'000), jede einzeln anlegbar und einzeln löschbar.

Aufräumen ist Teil der Messung, nicht ein Anhang: `cleanup(stufe)` löscht und **liest
danach jede gelöschte URN zurück**; bleibt auch nur eine übrig, ist der Lauf rot und die
Zahl gilt nicht.

## Warum

**1. B misst nichts von dem, was bricht.** Die drei Bruchkandidaten aus der Spec sind
Abholen der Abfragen, Antwortgrösse und Speicher. Zwei davon sind Netz-Eigenschaften:
`get_lineage` liefert nachweislich über 100'000 Zeichen ohne eingebaute Seitenbegrenzung
(Falle 12), und die Frage „ab wann brauche ich Pagination" ist eine Frage an die echte
GraphQL-Antwort. Ein Fake antwortet mit dem, was wir hineingeschrieben haben — er würde
die Zahl bestätigen, die wir behaupten wollen. Das ist genau der Selbstwiderspruch, gegen
den das Produkt antritt.

**2. A verunreinigt den Demo-Lauf und ist nicht rückbaubar.** Der Katalog auf 28080 trägt
die Entitäten, aus denen `examples/` und das Video entstehen. 5'000 fremde Tabellen darin
sind nicht „hinterher aufräumen", sondern ein Katalog, dem man ansieht, dass jemand darin
Lasttests gefahren hat. Ausserdem gibt es keine Zahl, gegen die man aufräumen könnte —
ohne eigenen Namensraum weiss niemand hinterher, was zum Test gehörte.

**3. Der Namensraum ist die Aufräum-Garantie.** `cleanup()` muss nicht raten, was zu
löschen ist: alles, dessen Name mit `probate_load.` beginnt. Das ist der Grund für ein
Präfix statt zufälliger URNs — Aufräumen wird eine Suche, kein Buchhaltungsproblem.

**4. Nur 28080.** Nie 18080 (trägt `showcase-ecommerce`, gegen das `datahub-attest`
veröffentlichte Zahlen gemessen hat), nie 8080 (WhatsApp-Bridge). Das ist keine
Wiederholung aus Höflichkeit: der Lasttest ist der einzige Schritt der ganzen Woche, der
fünfstellig viele Schreibvorgänge absetzt, und ein Tippfehler in der Adresse wäre hier
teurer als überall sonst.

**5. Geseedet heisst geseedet.** Jedes Lasttest-Artefakt trägt `"seeded": true` und
`"namespace": "probate_load"`. Die Zahlen im README sagen „gemessen gegen 5'000
synthetische Tabellen", nicht „gemessen gegen 5'000 Tabellen". Der Unterschied ist der
Unterschied zwischen einem Ergebnis und einer Übertreibung.

## Was müsste passieren, damit es falsch war

- **Stufe L dauert länger als die verbleibende Zeit.** Wahrscheinlichster Fall. Der Plan
  behandelt ihn ausdrücklich: die Stufen laufen S → M → L getrennt, jede schreibt ihr
  eigenes Artefakt, und wenn L nicht fertig wird, steht im README die M-Messung plus eine
  **als Hochrechnung gekennzeichnete** Fortschreibung. Eine benannte Grenze ist ein
  Ergebnis (Spec, Streichliste Punkt 4).
- **Das Anlegen selbst ist der Engpass, nicht das Messen.** Wenn 100'000 Query-Entitäten
  zu schreiben acht Stunden dauert, misst der Lasttest die Seed-Geschwindigkeit statt der
  Werkzeug-Geschwindigkeit. Gegenmittel im Plan: die Seed-Dauer wird **getrennt**
  gemessen und getrennt ausgewiesen (`loadtest_<stufe>_seed_seconds`), damit niemand sie
  mit der Abgleich-Dauer verwechselt.
- **Die Löschung geht nicht vollständig zurück.** Dann bleibt Müll in der Instanz, gegen
  die anschliessend die Demo läuft. Deshalb ist die Rücklese-Prüfung Abbruchbedingung und
  nicht Zusatz — und deshalb läuft der Lasttest im Zeitplan **nach** dem Demo-Material
  (P7-Beispiele werden aus P1–P5-Läufen erzeugt, nicht danach).
- **Ein Fake wäre doch aussagekräftig genug gewesen**, weil der Engpass rein rechnerisch
  ist (Ko-Okkurrenz-Paare). Die Spec hält selbst dagegen: *„Für sich harmlos; der Aufwand
  steckt im Beschaffen, nicht im Rechnen."* Falls die Messung das Gegenteil zeigt — der
  Beschaffungsteil ist billig, die Rechnung teuer — war der echte Datenpfad Aufwand ohne
  Erkenntnisgewinn.
