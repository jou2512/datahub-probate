# Entscheid: Der Seed-Hinweis ist kein zitierfähiger Beleg — und die Zahl wird nicht schöngerechnet

*07.08.2026, 03:40, Controller (Fable) — Joel schläft, Entscheid nach Autonomie-Rahmen.*

## Anlass

Die Vier-Fokus-Messung (`harness/runs/judge-seedlab-matrix.json`) beantwortet die Frage
„urteilt das Modell irgendwo im Demo-Datensatz zitierfähig?" mit **ja, 2 von 4**. Beim
genaueren Hinsehen ist eines der beiden Zitate aber wertlos:

| Fokus | Zustand | Urteil | Zitat |
|---|---|---|---|
| confirmed | confirmed | — | per Design ausgeschlossen |
| dead | dead | Rückfall | „Zitat zu kurz, kein Beleg" |
| missing | missing | Modell | **„probate-seedlab -- synthetische Demonstrationsdaten"** |
| unknown | unknown | Modell | „Temporaere Ablage eines Migrationstests, haelt dessen Zwischenstand." |

Das Modell hat bei `missing` **unseren eigenen Seed-Hinweis** zitiert — das Etikett, das sagt,
dass die Daten künstlich sind. Die Zitatpflicht ist formal erfüllt und inhaltlich leer: der
Beleg sagt nichts über die Tabelle, nur etwas über unser Testverfahren.

## Zwei Entscheide

### 1. Der Offenlegungs-Präfix wird aus dem zitierfähigen Korpus entfernt

Was stand zur Wahl: (a) so lassen, (b) den Präfix aus dem Korpus nehmen, den das Zitat
treffen muss, (c) den Präfix ganz weglassen.

**Gewählt: (b).** Der Hinweis *muss* stehen bleiben (Projektregel: geseedete Daten überall
ausweisen), aber er ist Metadatum über das Testverfahren, kein Geschäftsinhalt. Ein Beleg
darf nicht aus dem Etikett stammen, das die Daten als Attrappe kennzeichnet — sonst ist
jede beliebige Aussage „belegt", solange sie irgendein Wort des Disclaimers enthält.

Was müsste passieren, damit es falsch war: wenn ein echter Katalog Präfixe dieser Art
trägt, die tatsächlich urteilsrelevant sind. Unwahrscheinlich — der Präfix existiert nur,
weil wir seeden.

### 2. Der `dead`-Fokus wird NICHT angereichert, um die Zahl zu verbessern

Naheliegend wäre, die karge Beschreibung des `dead`-Fokus aufzufüllen (damals
`dead_upstream`, seit dem Umbenenn-Entscheid vom selben Tag
`store_revenue_weekly_east` — siehe `2026-08-07-seedlab-namen-ohne-etikett.md`),
damit auch dort
ein Urteil zustande kommt und die Einreichung „4 von 4" zeigt.

**Nicht gemacht.** Der Rückfallgrund lautet „Zitat zu kurz, kein Beleg" — das ist die
Zitatpflicht bei der Arbeit, nicht ein Mangel. Wer die Daten so lange verändert, bis die
Metrik gefällt, misst nichts mehr. Genau diesen Vorwurf erhebt dieses Projekt gegen
Werkzeuge, die Behauptungen ohne Beleg ausgeben.

**Ins README kommt die gemessene Zahl mitsamt Rückfallgründen**, nicht eine hergestellte.
Die Enthaltungsquote ist ein ausgewiesenes Ergebnis, kein Makel — so steht es in der
Projekt-`CLAUDE.md`, und hier gilt es zuerst für uns selbst.

[Einschätzung: hier hätte Joel vielleicht die Demo-Zahl hübscher gewollt. Ich halte die
ehrliche Zahl für das stärkere Verkaufsargument — sie ist der Beweis, dass die Zitatpflicht
beisst.]
