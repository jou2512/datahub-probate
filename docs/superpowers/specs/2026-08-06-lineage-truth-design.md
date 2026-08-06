# Entwurf: Vom Stilllegungs-Werkzeug zum Lineage-Wahrheitsprüfer

*2026-08-06 · Frist 10.08.2026, 23:00 MESZ · verbleibende Bautage: Fr 07., Sa 08., So 09.*

## Warum dieser Umbau

Das bisherige Produkt (`probate`) prüft **einmal, zum Löschzeitpunkt**, ob eine Tabelle noch
genutzt wird. Zwei Einwände haben das gekippt, beide berechtigt:

**Joels Einwand (06.08.):** Die „Nutzung messen"-Hälfte ist im Kern ein Auslese-Skript für eine
DataHub-eigene Funktion. Wenn eine Firma DataHub richtig eingerichtet hat, kann sie dieselbe
Frage direkt im Werkzeug nachsehen. Wir klonen, statt zu erfinden.

**Der Folgefehler, den das aufdeckte:** Der Code kann „wir haben nichts gemessen" nicht von
„es wurde wirklich nichts genutzt" unterscheiden. Beide Fälle geben eine leere Liste zurück.
Und die Kategorie `dead_wood` (deklariert, nichts gemessen) galt bisher als *unbedenklich* —
also wird bei fehlender Datenlage ein echter, aktiver Konsument stillschweigend überschrieben.
Ein Kommentar im Code behauptete die Vorsicht, die der Code nicht einlöst.

**Der Umbau:** Nicht eine einmalige Prüfung vor dem Löschen, sondern ein **fortlaufender
Abgleich zweier unabhängiger Wahrheitsquellen** — was der Katalog *behauptet* (Lineage-Kanten)
gegen was *wirklich passiert ist* (gemessene Abfragen). Die Stilllegung wird eine Handlung, die
daraus folgen kann, nicht das ganze Produkt.

## Die Beweislage (geprüft, nicht angenommen)

Alles hier ist belegt — Live-Aufruf, gelesener Quellcode oder zitierte Doku. Reihenfolge nach
der Projektregel: Live-Aufruf > Quellcode > Doku.

### DataHub kann es selbst nicht

| Befund | Beleg |
|---|---|
| **DataHub ersetzt Lineage, vergleicht sie nie.** `sql_parsing_aggregator.py:1534` baut eine **frische, leere** Kantenliste (`UpstreamLineageClass(upstreams=[])`), füllt sie nur aus den in *diesem* Lauf geparsten Abfragen und emittiert sie als vollen Aspekt. Der einzige Aspekt-Lesezugriff der Datei (`:665`) holt `SchemaMetadataClass` — Schema-Auflösung, nicht Lineage. | **selbst nachgelesen** im geklonten Quellcode, master @ `26a9f6c` |
| Zwei Ingestion-Modi, beide blind: Standard überschreibt voll (löscht auch legitime alte Kanten), `incremental_lineage: true` hängt nur an — **tote Kanten wachsen ewig, werden nie gemeldet, nie entfernt** | Quellcode + `docs/features/feature-guides/lineage.md:106` (Doku-Zitat gilt ausdrücklich nur bei gesetztem `incremental_lineage`-Schalter — Bedingung muss mitzitiert werden) |
| `DatasetPatchBuilder.remove_upstream_lineage()` **existiert und hat null Aufrufer** — Grep über den geklonten Baum (inkl. vollständigem `metadata-ingestion`) findet ausser der Definition keine einzige Fundstelle, nicht einmal in Tests. *Einschränkung: der Klon ist partiell (`metadata-models`, `metadata-io`, `metadata-service`, `datahub-graphql-core`, `metadata-ingestion`, `docs`); nicht geprüfte Bäume könnten Aufrufer enthalten.* | **selbst nachgeprüft**, `metadata-ingestion/src/datahub/specific/dataset.py:167` |
| DataHubs eigenes Kanten-Urteil `LineageMatchType` prüft nur URN-Auflösbarkeit, und sein Docstring sagt: *„reflects DataHub's knowledge AT THE TIME THE LINEAGE EDGE WAS INGESTED, not the current state of the graph … not re-evaluated automatically"* | `dataset/LineageMatchType.pdl` |
| Kein Assertion-Typ zielt auf Lineage (OSS-Enum live gemessen: `DATASET, FRESHNESS, VOLUME, SQL, FIELD, DATA_SCHEMA, CUSTOM`) | Live-Introspektion auf 28080 |
| `MetadataAttribution` (strukturierte Herkunft) ist in genau 6 von 688 `.pdl`-Dateien eingebunden — Lineage-Aspekte sind **nicht** dabei | Grep über alle 688, drei Lineage-Dateien vollständig gelesen |
| `isManual` ist **selbstdeklariert, nicht erzwungen**: eine per REST geschriebene Kante mit `{"source":"UI"}` kam als `isManual: true` zurück, obwohl sie nie durch die UI ging. Kann „dbt-deklariert" nicht von „im Query-Log beobachtet" unterscheiden (beide `false`). Nur Ausgabe, kein Filter-Input. | Live-Gegenprobe, drei Kanten geschrieben und zurückgelesen |
| **DataHub Cloud macht das Gegenteil:** Docs-Propagation schiebt Beschreibungen *entlang* deklarierter Kanten, ohne je zu prüfen, ob die Kante das verdient. Eine tote Kante drückt dort aktiv eine falsche Beschreibung nach unten. | `docs/automations/docs-propagation` |

### Das Feld hat es nicht

620 Repos erfasst, 22 tief gelesen, plus 11 aus früheren Durchgängen.

**Sieben Projekte lesen beide Quellen. Alle sieben benutzen Nutzung als Gewicht, Hinweis oder
Beleg-Text an Kanten, denen sie ohnehin glauben. Keines prüft die Kante selbst.**

Die nächsten Nachbarn, jeder mit dem Grund, warum er es nicht ist:

- **`assay`** — stärkster Fund: kontinuierlich über Actions, schreibt zurück, nutzt beide
  Quellen. Beurteilt aber den **wirtschaftlichen Wert einer Tabelle**; vertraut der Lineage,
  um Abhängigkeit zu berechnen.
- **`notary`** — Tagline fast unsere („cross-examines your data catalog's claims against
  measured reality"), aber die „measured reality" sind **Warehouse-SQL-Proben gegen
  Beschreibungs-Behauptungen** (Einheiten, Frische, Enums), nicht Kanten. Nutzung ist nur
  Schweregrad-Schwelle.
- **`datahub-rail-agent`** — einziges echtes Strukturvorbild: `dangling = [u for u in declared
  if u not in resolved]`. Aber `resolved` ist DataHubs **eigener Graph-Index** — fängt Kanten
  auf gelöschte Tabellen, nie eine Kante, die sauber auflöst und die niemand je benutzt hat.
  Keine Gegenrichtung.
- **`sidq`** — `lineage_rot` vergleicht gegen **SQL-Quelltext aus dem Repo**, nicht gegen
  Laufzeit. Scheiterte auf DataHubs eigenem Beispiel zu **32 von 32** („unverifiable"), weil
  der Datapack kein Modell-SQL mitliefert. Unsere Quelle existiert genau dann noch.
- **`deprecation-janitor`** — summiert Signale zu einem Deadness-Score, bildet keine Differenz.
  Kampagne auf Zuruf, nicht fortlaufend.
- **`canon`**, **`lineage-drift-triage`**, **`cauzon`**, **`blast-radar`** — geprüft, jeweils
  anderer Mechanismus (Vertrauens-Punktzahl / Blast-Radius / Beleg-String).

**Die Ko-Okkurrenz-Richtung (fehlende Kanten aus gemeinsamen Abfragen) hat null Vorbild.**

### Ehrlich offen — gehört in jede Aussage

- **Devpost-Galerie ist nicht veröffentlicht** (2'708 Teilnehmer). GitHub ist der einzige
  sichtbare Stellvertreter; private oder nicht verlinkte Repos sind unsichtbar.
- **GitHubs Repo-Suche indexiert keine READMEs**, Code-Suche nur Default-Branches mit
  Seitenlimit. „7 Fenster-Repos berühren die Nutzungs-API" ist eine **Untergrenze**, keine
  Zählung.
- **~44 Repos wurden angefragt und kamen nie zurück** — ungelesen, nicht entlastet. Die drei
  alarmierendsten Namen daraus wurden einzeln nachgeholt und sind entwarnt
  (`lineage-drift-triage`, `canon`, `assay`).
- **„Metadata Tests" (DataHub Cloud) ist Closed Source.** Die in der Doku versprochene
  Eigenschaftstabelle existiert im Markdown-Quelltext **gar nicht**. Belegt ist: Nutzung *ist*
  dort bereits ein Prädikat (*„all datasets in the top 25% of query usage in the past 30 days
  must have an owner"*). „Cloud kann das nicht" ist **unbelegbar** — als Risiko formulieren,
  nicht als Entwarnung.
- **DataHubs eigener Blogartikel** zur Pipeline-Optimierung paart die Signale bereits: *„Lineage
  shows what's connected to what. Dataset usage and query history shows what's actually being
  read … Together they turn 'might still be used' into a binary."* Unterschied: dort ist das
  Urteilsobjekt immer die **Tabelle**, nie die **Kante**, und der Ablauf ist manuell
  zusammengesetzt. **Muss in der Einreichung in genau diesen Worten stehen**, sonst schreibt
  ein Juror es selbst auf die falsche Seite.

## Was gebaut wird

### Schicht 1 — Der Abgleich (deterministisch)

Pro Kante, nicht pro Tabelle. Vier Zustände:

| Zustand | Bedeutung | Beleg, der mitgeführt wird |
|---|---|---|
| `confirmed` | deklariert **und** gemessen | Abfrage-URN + Zeitfenster |
| `dead` | deklariert, im Fenster **nie** gemessen | Fensterlänge, geprüfte Abfragen |
| `missing` | gemessen (Ko-Okkurrenz), **nicht** deklariert | Abfrage-URN, Anzahl gemeinsamer Vorkommen |
| `unknown` | **keine Daten im Fenster** — Aussage nicht möglich | warum: keine Nutzungsdaten / keine Buckets |

`unknown` ist der Kern der Korrektur. Es darf **nie** wie `dead` behandelt werden. Die
Unterscheidung ist in den Daten angelegt: gar keine Zeitfenster = wir sehen nichts;
Zeitfenster vorhanden aber auf null = wir haben hingesehen und es ist nichts passiert.

**Abdeckungs-Prüfung vorweg:** Bevor irgendetwas klassifiziert wird — wie viele
Nutzungs-Zeitfenster gibt es im Katalog überhaupt, und wie weit reichen sie zurück? Ist die
Abdeckung dünn, wird das Ergebnis als solches ausgewiesen, nicht stillschweigend als „gemessen"
verkauft.

### Schicht 1b — Die Zeitachse (aus dem Abgleich, ohne Zusatzquelle)

Nutzungsdaten kommen ohnehin in Zeitfenstern mit Zeitstempeln. Bisher wird die zeitliche
Dimension **weggeworfen** — der Abgleich sagt „heute ist diese Kante tot", nicht „sie war bis
zum 11. April gedeckt".

Das ist der Unterschied zwischen einem **Prüfwerkzeug** und einem **Nachweis**, und er kostet
fast nichts: dieselben Buckets, nur nicht summiert, sondern behalten.

Daraus fallen drei Angaben pro Kante:
- **letzte Deckung** — der jüngste Zeitpunkt mit gemessenem Verkehr
- **tot seit** — Alter der Abweichung in Tagen
- **Verlauf** — Abfragen pro Zeitfenster, als Reihe

Der Nutzen ist nicht Statistik, sondern Beweiskraft: „Diese Kante war zu diesem Zeitpunkt
gedeckt" ist eine Aussage, die man später belegen kann. Ein datierter Befund ist der Anfang
eines Audit-Trails; ein undatierter ist eine Momentaufnahme.

Herkunft dieser Ergänzung: Joel brachte am 06.08. eine Analyse aus einem früheren Gespräch ein
(Compliance-Produkt auf Graph-Infrastruktur). Deren Kernbeobachtung — *alle bauen Vorhersage,
niemand baut Beweis* — deckt sich unabhängig mit unserer Feldzählung (36 Blast-Radius-Klone,
alle zukunftsgerichtet). Die dort genannten Rechtsbehauptungen (DSGVO Art. 30, NIS2, EU AI Act,
Beraterkosten) sind **ungeprüft** und gehören vor jeder Verwendung einzeln gegen den Gesetzestext
belegt. Übernommen wird hier ausschliesslich die strukturelle Beobachtung, nicht der Markt-Teil.

### Schicht 2 — Das Urteil (hier sitzt das Modell, und nur hier)

Nicht jede Abweichung ist wichtig. Eine tote Kante zu einer Tabelle mit „Jahresabschluss" in
der Beschreibung ist etwas anderes als eine zu einer namenlosen Zwischentabelle. Das ist
Urteil über unstrukturierten Text — keine Regel, die man schreiben kann.

Der Agent liest Beschreibung, Eigentümer, Glossar-Begriffe, Domäne der betroffenen Tabellen und
begründet, **warum diese Abweichung wichtig ist oder nicht — mit Zitat aus dem Gelesenen.**
Ohne Zitat kein Urteil; dann bleibt es beim deterministischen Befund.

Das ist die einzige Stelle mit einem Modellaufruf. Überall sonst gilt weiter: deterministisch,
offline testbar.

### Schicht 3 — Die Handlung (beide Modi)

- **Melden:** Bericht mit Kanten-Register, nach Wichtigkeit sortiert
- **Korrigieren:** fehlende Kante eintragen, tote Kante markieren, Doku aus beobachteter
  Nutzung anreichern

Immer Vorschlag mit Beleg → Mensch bestätigt → Journal mit Rückwärtsgang. Die Disziplin aus
dem bestehenden `writeback.py` bleibt unverändert. **Kein automatisches Schreiben.**

Die **Stilllegung** wird eine Handlung, die der Agent vorschlagen kann, wenn eine Tabelle nur
noch tote Kanten hat — mit dem bestehenden Beweis-Ablauf (`parity.py`, `confirm`).

### Schicht 4 — Die Werkbank (Oberfläche)

**Kein Bericht, ein Labor.** Ein Dashboard, das nur Zahlen anzeigt, beweist nichts — man kann
nicht unterscheiden, ob es rechnet oder ob jemand die Zahlen hingeschrieben hat. Eine Jurorin
der letzten Runde wörtlich: *„Ich kann es nicht selbst erleben, nur glauben."* Bei einem
Werkzeug, dessen Kernaussage „nichts behaupten ohne Beleg" lautet, ist eine Demo, der man
glauben muss, ein Selbstwiderspruch.

**Vier Bereiche, ein Bildschirm:**
- **Deklariert** (links oben) — der Lineage-Baum, Kanten anklickbar
- **Gemessen** (links unten) — Abfragen pro Tabelle als Balken. Tabellen ohne Datenlage sind
  *sichtbar leer*, nicht auf null gesetzt — der Unterschied muss auch optisch einer sein
- **Kanten-Register** (rechts oben) — das Urteil pro Kante, live, aufklappbar zu Zeitachse und
  Modell-Einschätzung
- **Live-Protokoll** (rechts unten) — jedes Ereignis, jede Neubewertung, jeder Schreibvorgang,
  jeder Modellaufruf mit Kosten. *Der Beweis, dass gerechnet und nicht abgespielt wird.*

**Steuerpult — sechs Knöpfe, die beide Wahrheitsquellen verändern:**

| Knopf | Tut | Sichtbare Folge |
|---|---|---|
| Abfrage absetzen | schreibt echte Query-Entität mit 2 subjects | Kante wird `missing` |
| Kante eintragen | schreibt Lineage-Kante | Kante wird sofort `dead` |
| Kante entfernen | nimmt deklarierte Kante weg | bei Verkehr → `missing` |
| **Warehouse trennen** | simuliert fehlende Nutzungsanbindung | alle betroffenen → **`unknown`, nicht `dead`** |
| Zeit vorspulen | verschiebt Beobachtungsfenster | Kanten altern sichtbar |
| Lauf starten | vollständiger Abgleich | Fortschritt, Dauer, Abdeckung |

**Der Knopf, der die Demo trägt, ist „Warehouse trennen"** — er führt in fünf Sekunden vor, was
in der alten Fassung ein stiller Fehler war. Ein Prüfer sieht unmittelbar, dass das Werkzeug den
Unterschied zwischen „nichts gemessen" und „nichts passiert" wirklich macht.

**Demo-Ablauf fürs Video (~40 s):** Kante eintragen → erscheint als `dead` → Abfrage absetzen →
wird `confirmed` → Warehouse trennen → wird `unknown`. Dreimal in drei Richtungen, ohne dass
jemand etwas erklären muss.

**Technisch:** statischer Export (wie beim Schwesterprojekt, damit ohne laufende Instanz
aufrufbar), plus Betriebsmodus gegen eine echte DataHub-Instanz, wenn eine da ist — dann
schreiben die Knöpfe wirklich. Ohne Instanz läuft dieselbe Oberfläche gegen aufgezeichnete
Läufe, **sichtbar als Aufzeichnung gekennzeichnet**, nicht als Live-Betrieb getarnt.

### Gestaltung — bindend, nicht Geschmackssache

Joels Vorgabe wörtlich (06.08.): *verständlich, schön, erklärend und beruhigend, modern,
SaaS-Vibe, professionell — ohne AI-Slop-Look.*

**Was das konkret heisst:**

- **Beruhigend statt alarmierend.** Das Werkzeug meldet Probleme; wenn die Oberfläche selbst
  auch noch schreit, wird sie unbenutzbar. Rot ist reserviert für den *Zustand* einer Kante,
  nirgends für Rahmen, Kopfzeilen oder Knöpfe. Gedeckte Grundfarbe, viel Weissraum, ruhige
  Übergänge.
- **Erklärend eingebaut, nicht als Handbuch daneben.** Jeder der vier Zustände trägt an Ort und
  Stelle einen Satz, was er bedeutet. Wer `unknown` zum ersten Mal sieht, muss nicht raten. Die
  Abdeckungs-Angabe steht *über* den Ergebnissen, nicht in einer Fussnote.
- **Zwei Quellen, zwei Farben, durchgehend.** Deklariert und Gemessen bekommen je eine Farbe,
  die auf jedem Bildschirm dieselbe bleibt. Das ist Informationsgestaltung, keine Dekoration —
  wer die Farbe einmal gelernt hat, liest jede weitere Ansicht schneller.
- **Zustand hat eine Form, nicht nur eine Zahl.** Chip, Streifen, Punkt — was Aufmerksamkeit
  braucht, muss auf einen Blick erkennbar sein, ohne zu lesen.
- **SaaS-Handwerk:** echte Typo-Hierarchie, Tabellenziffern wo Zahlen untereinanderstehen,
  sichtbarer Tastatur-Fokus, helles und dunkles Thema gleichwertig gepflegt, breite Inhalte
  scrollen in ihrem eigenen Container statt die Seite zu verschieben.

**Verboten, weil es sofort nach KI-Ausgabe aussieht:** Emoji als Abschnittsmarken, Farbverlauf
im Kopfbereich, alles zentriert, überall dieselbe grosse Eckenrundung, Akzentstreifen an
gerundeten Karten, Creme-Grundton mit Terrakotta-Akzent, Inter oder Space Grotesk als
Standardschrift, riesiger Hero-Bereich ohne Inhalt.

**Der Massstab:** Ein Betrachter soll denken „das ist ein Produkt", nicht „das ist ein
Hackathon-Projekt". Beim Schwesterprojekt gab eine Jurorin 3/10, weil die Demo statisch war
und nichts erklärte — die Gestaltung ist hier keine Kür, sie ist eines der sechs
Bewertungskriterien.

**Nicht streichbar.** Ohne Werkbank ist die Demo wieder etwas, dem man glauben muss — und genau
das hat in der Jury-Simulation die schlechteste Einzelnote bekommen (3/10 Submission Quality).

## Der Lasttest — Pflicht, nicht Kür

Bisher getestet mit **zwei** Abfragen. Eine echte Firma erzeugt sechsstellige Zahlen täglich.
Ein Werkzeug, das „nichts behaupten ohne Messung" führt und dann „skaliert schon" behauptet,
widerlegt sich selbst.

**Drei Bruchkandidaten:**
1. **Abholen der Abfragen** — der offensichtliche Engpass. Bekannte Vorbelastung: die
   Lineage-Abfrage liefert nachweislich über 100'000 Zeichen ohne eingebaute Seitenbegrenzung.
   Bei Abfragen mit Volltext ist dasselbe zu erwarten.
2. **Ko-Okkurrenz-Rechnung** — bei ~3 Tabellen je Abfrage sind 100'000 Abfragen rund 300'000
   Paare. Für sich harmlos; der Aufwand steckt im Beschaffen, nicht im Rechnen.
3. **Speicher** — alle Abfragen gleichzeitig halten ist der naive Weg. Alternative: strömend
   verarbeiten mit laufender Zählung.

**Geplanter Ausweg (Architektur, kein Messergebnis):** grober Durchgang über die verdichteten
Zahlen (eine Zahl pro Tabelle und Zeitfenster, unabhängig von der Abfragezahl), Detailblick nur
bei auffälligen Kanten. Damit hängt der teure Teil an der Zahl *verdächtiger Kanten*, nicht an
der Gesamtzahl der Abfragen — bei 384 Kanten und 41 Auffälligkeiten also 41 Detailabrufe statt
100'000.

**Messplan, drei Stufen:**

| Stufe | Tabellen | Abfragen | Zweck |
|---|---|---|---|
| S | 50 | 1'000 | Grundlinie, alles im Speicher |
| M | 500 | 10'000 | erste Seitenbegrenzung nötig? |
| L | 5'000 | 100'000 | der Ernstfall |

Je Stufe zu messen: Dauer grober Durchgang · Dauer Detailblick je Kante · Spitzenspeicher ·
Anzahl Schnittstellen-Aufrufe · **bricht etwas, und wo genau mit Fehlertext**.

**Die entscheidende Zusatzfrage:** vollständiger Lauf gegen Tagesdelta — wie viel billiger? Ein
Vollabgleich darf zwei Stunden dauern, solange der tägliche Nachlauf Minuten braucht. Das
entscheidet, ob das Werkzeug in einer echten Firma benutzbar ist oder nur im Beispiel.

**Wenn es kippt: die Zahl kommt trotzdem ins README**, mit der Grösse, ab der es nicht mehr
trägt. Eine benannte Grenze ist ein Ergebnis; eine verschwiegene ist ein Fehler. Reicht die Zeit
nur für Stufe M, wird hochgerechnet — und die Hochrechnung **als solche gekennzeichnet**.

## Architektur-Entscheidungen

**Zwei Transportwege, bewusst:**
- **Fehlende Kanten** (Ko-Okkurrenz) laufen über den **MCP-Server** (`get_dataset_queries`
  liefert `subjects` = alle berührten Tabellen). Das ist zugleich die Nutzung des Agent Context
  Kit, deren Fehlen sieben Jury-Personas unabhängig kritisiert haben.
- **Tote Kanten** (N-Tage-Fenster) brauchen **rohes GraphQL** — der MCP-Server hat 21 Werkzeuge,
  keines liefert aggregierte Nutzung, und bei `get_dataset_queries` sind die Zeitstempel-Felder
  in `gql/queries.gql` **auskommentiert**. Das ist keine Bequemlichkeit, sondern eine gemessene
  Grenze des Werkzeugs.

**Nutzungsdaten müssen geseedet werden.** Der Beispielkatalog liefert keine (live geprüft:
`totalSqlQueries: null`, `buckets: []`). Das Schreiben funktioniert (live verifiziert:
3 Buckets geschrieben, `aggregations.totalSqlQueries: 150` zurückgelesen). **Im Video und im
README muss stehen, dass die Daten geseedet sind** — eine unbeschriftete Zahl widerspricht dem
eigenen Produkt.

**Lastverhalten, zweistufig:** Grober Durchgang über die Aggregate (`statsSummary
.queryCountLast30Days`, eine Zahl pro Tabelle), erst bei auffälligen Kanten in die einzelnen
Abfragen hinein. `get_lineage` liefert nachweislich über 100'000 Zeichen ohne
Pagination-Vorgaben — das ist bekannt und wird begrenzt. **Muss gemessen werden**, bisher nur
mit 2 Abfragen getestet.

## Was weiterlebt, was gestrichen wird

**Weiterverwendet aus dem bestehenden Code:**
- `targets.py` — rechnet den Dreier-Split bereits, wird auf Kanten-Ebene erweitert
- `writeback.py` — Journal + echter Rückwärtsgang, unverändert
- `gms.py` — beide Stille-Fallen verriegelt, `--token`-Unterstützung neu
- `parity.py`, `campaign.py`, `confirm` — für die Stilllegung als Folge-Handlung
- `probate_action/watcher.py` — läuft nachweislich (drei Konfigfehler gefunden und behoben:
  Kafka `29192` statt `9092`, Schema-Registry über GMS statt `8081`, Befehl `actions` statt `run`)

**Gestrichen, weil es fertig existiert:**
- „Wer nutzt diese Tabelle" — vollständig in OSS inklusive UI-Tabelle „Top Users"
- Query-Deduplizierung — `get_query_fingerprint` existiert, wird übernommen

**Eine Rest-Lücke, die bleibt:** „welche Person liest welche Spalte" ist im Datenmodell nicht
darstellbar (Nutzerzahlen und Spaltenzahlen in getrennten Listen ohne Verbindung). Kein
Bauvorhaben, aber ein sauberer Nebenbefund für den Upstream-Beitrag.

## Tagesplan

| Tag | Was |
|---|---|
| **Rest 06.08.** | `recipe.yml` korrigieren, Nutzungsdaten seeden, erster echter Abgleich auf 28080 |
| **Fr 07.08.** | Schicht 1 vollständig: Kanten-Register, vier Zustände, Abdeckungs-Prüfung, **Zeitachse (1b)**, Tests |
| **Sa 08.08.** | Schicht 2 (Modell-Urteil mit Zitatpflicht) + Schicht 3 (Korrektur-Modus) + Wächter live + **Schicht 4 (Werkbank mit Steuerpult)** |
| **So 09.08.** | **Lasttest (3 Stufen)**, **englisches** README, `examples/`, Video, Devpost-Text, Upstream-Beitrag |
| **Mo 10.08.** | Nur Abgabe. Kein Bauen. |

**README auf Englisch** ist keine Kür: eine Jurorin gab 3/10 unter anderem, weil README und
CLI-Ausgaben durchgehend deutsch sind. Bei einem US-Wettbewerb ist das eine der sechs
gleichgewichteten Kategorien.

## Streichreihenfolge, wenn es eng wird

1. **Schicht 2 (Modell-Urteil)** — der Befund steht auch ohne Gewichtung; dann fällt aber das
   „wo ist der Agent"-Argument weg. Erst streichen, wenn Sa abends nichts läuft.
2. **Korrektur-Modus** (Schicht 3, Schreiben) — Melden allein trägt den Befund.
3. **Kontinuierlicher Wächter** — Rückfall auf einmaligen Lauf. Kostet die
   „fortlaufend"-Erzählung, nicht den Kern.
4. **Lasttest-Stufe L** (100'000) — bei Zeitmangel bei Stufe M messen und hochrechnen, die
   Hochrechnung **als Hochrechnung kennzeichnen**. Niemals eine ungemessene Zahl als gemessen
   ausgeben.

**Nie gestrichen:** der Abgleich selbst (Schicht 1), die Belege pro Kante, **die Werkbank**
(ohne sie ist die Demo wieder Glaubenssache — schlechteste Einzelnote der letzten Runde), das
englische README, das Video, der `examples/`-Ordner, die Apache-2.0-Datei.

## Verifikation

- **Jede Zahl** in README/Devpost/Video wird von `harness/audit_claims.py` gegen die
  Lauf-Artefakte nachgerechnet, Exit 1 bei Abweichung (Muster steht, aktuell 3 Prüfungen —
  wird auf die neuen Zahlen erweitert)
- **Jeder Abgleich-Lauf** gegen die echte Instanz `http://localhost:28080` (v1.5.0.6), nie
  gegen 18080 (trägt `showcase-ecommerce`, gegen das `datahub-attest` veröffentlichte Zahlen
  gemessen hat)
- **Probe-Entitäten** werden nach jedem Lauf gelöscht und die Löschung zurückgelesen
- **Der geseedete Zustand** wird als geseedet ausgewiesen, in jedem Artefakt

## Was diese Spezifikation nicht klärt

- Ob der Ko-Okkurrenz-Ansatz bei 10'000 Abfragen trägt — muss gemessen werden, nicht behauptet
- Ob „Metadata Tests" in DataHub Cloud eine Teilüberschneidung darstellt — Closed Source,
  bleibt als erklärte Unwissenheit stehen
- Ob `attest` und `probate` zusammengelegt werden sollten — offene strategische Frage, aktuell
  bewusst getrennt (zwei Chancen auf vier Sparten-Preise, Regeln verlangen „substantially
  different", `attest` ist fertig und würde durch einen Umbau riskiert)
