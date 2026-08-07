# Werkbank — Spezifikation einer Enterprise-Konsole

> Diese Datei ist bindend für jeden, der an `ui/` arbeitet. Sie ersetzt alle
> früheren Beschreibungen der Werkbank.
>
> Anlass: Joel, 07.08.2026, nach drei erfolglosen Anläufen — *„firmen haben evt
> 1000 sachen… das hier wird bei 4 schon unübersichtlich, man weiss nicht von
> welchen tables man redet, man weiss nicht in welchem katalog… es ist einfach
> nicht auf enterprise ausgelegt, es wirkt 0 professionell und SaaS gedacht… wo
> sind filter, wo sind kategorien wo sind die trees, wo sind sidebars, wo ist
> navigation… wo ist das live dashboard"*

## Der Massstab

Der Katalog auf `localhost:28080` enthält **5.594 Datensätze** (gemessen
07.08.2026, `searchAcrossEntities(types:[DATASET], count:0).total`). Jede
Entscheidung in dieser Oberfläche wird gegen diese Zahl geprüft, nicht gegen die
acht Datensätze des Demo-Labors.

**Die Prüffrage für jedes Bauteil:** Funktioniert es noch bei 5.594 Zeilen? Eine
Liste ohne Filter, ohne Sortierung und ohne Seitenaufteilung besteht diesen Test
nicht — auch dann nicht, wenn sie mit vier Zeilen hübsch aussieht.

## Ebene 1 — Informationsarchitektur

Regel `.claude/rules/design-reference.md`: Erst die Struktur, dann die
Interaktion, dann der Stil. Wer beim Stil anfängt, baut etwas Hübsches am Ziel
vorbei.

### Rahmen

```
┌────────────────────────────────────────────────────────────────────────┐
│ Kopfzeile: Instanz · Modus · Suche · [Prüfung starten]                  │
├──────────────┬─────────────────────────────────────────────────────────┤
│              │                                                          │
│  Seiten-     │   Inhaltsbereich                        ┌──────────────┐│
│  leiste      │   (je nach Bereich)                     │  Detail-     ││
│              │                                          │  spalte      ││
│  5 Bereiche  │                                          │  (bei Aus-   ││
│              │                                          │   wahl)      ││
│              │                                          └──────────────┘│
├──────────────┴─────────────────────────────────────────────────────────┤
│ Statusleiste: letzter Lauf · Abdeckung · Enthaltungsquote               │
└────────────────────────────────────────────────────────────────────────┘
```

Die Seitenleiste ist **immer da** und zeigt immer, wo man ist. Kein Bereich wird
über einen Knopf im Fliesstext erreicht.

### Fensterbreiten (Nachtrag 07.08.2026, gemessen)

Der Rahmen oben gilt **ab 1280 px unverändert**: Seitenleiste 210 px links,
genau **ein** senkrechter Bildlauf, nämlich im Inhaltsbereich.

Darunter darf er nicht zerfallen. Die Seitenleiste wird **schmaler** (150 px
unter 1280, 144 px unter 1024, Hinweissätze fallen weg), die Detailspalte legt
sich **über** den Inhalt statt ihn zu zerquetschen. Sie wird **nie** zu einem
waagerechten, selbst scrollenden Kasten über dem Inhalt, und es gibt **nie zwei
senkrechte Bildlaufleisten nebeneinander**.

Anlass: bei 838 × 674 lag die Navigation als 838 × 273-Kasten über dem Inhalt,
mit eigener Bildlaufleiste (`scrollHeight` 399 > `clientHeight` 273) — „Belege"
war ohne Scrollen in diesem Kasten gar nicht erreichbar. Gegenprobe nach dem Fix
bei 1440 / 1100 / 860 / 838 px in `docs/screenshots/konsole-breite-*.png`.

### Die fünf Bereiche

| Bereich | Frage, die er beantwortet | Hauptsache auf dem Schirm |
|---|---|---|
| **Übersicht** | „Wie steht es um meinen Katalog?" | Live-Kennzahlen, Verlauf, letzter Lauf |
| **Verbindungen** | „Welche Kante stimmt, welche nicht?" | Filterbare, sortierbare Tabelle |
| **Katalog** | „Wo liegt das bei uns?" | Baum Plattform → Datenbank → Schema → Tabelle |
| **Läufe** | „Was wurde wann gemessen?" | Lauf-Historie mit Beleg-Artefakten |
| **Belege** | „Woher weiss das Ding das?" | Zitate, Abfragen, Nutzungsfenster |

## Bereich 1 — Übersicht (das Live-Dashboard)

Vier Kennzahlkarten, darunter Verlauf und letzter Lauf.

| Karte | Zahl | Nenner dazu, immer |
|---|---|---|
| Bestätigt | `confirmed` | „von N geprüften Kanten" |
| Tot | `dead` | dito |
| Fehlend | `missing` | dito |
| Unbekannt | `unknown` | dito |

Darunter, gleichrangig und **nicht** kleingedruckt:

- **Abdeckung** — für wie viele Kanten lagen überhaupt Nutzungsfenster vor.
  Ohne diese Zahl ist jede andere Zahl nicht interpretierbar.
- **Enthaltungsquote** — wie oft das Modell kein zitierfähiges Urteil abgeben
  konnte. Das ist ein ausgewiesenes Ergebnis, kein Makel.
- **Letzter Lauf** — Zeitpunkt, Dauer, geprüfte Kanten, Artefaktpfad.

### Die Null-Regel (nicht verhandelbar)

**„Keine Daten" und „gemessene Null" sehen NIE gleich aus.** Ein leerer Balken,
eine `0` oder ein leeres Feld, wo in Wahrheit nicht gemessen wurde, ist genau die
Behauptung ohne Beleg, gegen die dieses Produkt antritt.

- Gemessene Null → die Ziffer `0`, normale Darstellung.
- Nicht gemessen → das Wort **„nicht gemessen"** plus, warum: „kein
  Nutzungsfenster im gewählten Zeitraum".

**Die Regel gilt für jede der fünf Ansichten, nicht nur für die Balken**
(Nachtrag 07.08.2026, nach einem gemessenen Fehlgriff: `GET /api/connections`
antwortete direkt nach dem Serverstart mit `rows: []`, und die Konsole zeigte
eine wortlos leere Tabelle — von „kaputt" nicht zu unterscheiden). Konkret:

- Eine leere Ansicht sagt immer drei Dinge: **was fehlt, warum, und welcher
  Knopf es behebt.** Der Grund kommt vom Server (`empty_reason`, `fix_action`),
  damit keine Ansicht ihn vergessen und keine ihn erfinden kann.
- Der Server startet **nicht leer**: er lädt beim Start das passendste
  Lauf-Artefakt von der Platte (`harness/runs/`, `ui/recorded/`).
- Dieser Stand wird **als Aufzeichnung ausgewiesen** — Zeitpunkt und
  Artefaktpfad stehen in einem Streifen unter der Kopfzeile, in jedem Bereich
  und auf jeder Fensterbreite. Deckt die Aufzeichnung andere Tabellen ab als die
  beobachteten, steht auch das dort. Ein alter Stand, der wie eine frische
  Messung aussieht, ist dieselbe Behauptung ohne Beleg wie eine erfundene Null.
- Das blosse Öffnen der Seite misst nicht (`/api/current` statt `/api/ledger`).
  Gemessen wird auf Knopfdruck — ein Neuladen darf nicht kosten.

## Bereich 2 — Verbindungen (das Herzstück)

### Kopfzeile des Bereichs: Filter, sichtbar, nicht in einem Menü versteckt

| Filter | Form |
|---|---|
| Zustand | vier Chips zum An-/Abwählen, mit Anzahl je Zustand |
| Plattform | Auswahlliste aus den Daten, nicht hartkodiert |
| Datenbank / Namespace | Auswahlliste |
| Domäne | Auswahlliste (DataHub-Domänen) |
| Besitzer | Auswahlliste |
| Zeitraum | 7 / 30 / 90 Tage / eigener |
| Nur mit Modellurteil · Nur Enthaltungen | Schalter |
| Freitext | sucht in Tabellen- und Spaltennamen |

Aktive Filter stehen als entfernbare Chips über der Tabelle. Daneben immer:
**„N von 5.594 Kanten"**.

### Die Tabelle

Sortierbar je Spalte, seitenweise (50 pro Seite) oder virtualisiert. **Niemals
5.594 Zeilen auf einmal ins DOM.**

| Spalte | Inhalt | Warum |
|---|---|---|
| Von | `plattform · datenbank · schema`<br>**`tabellenname`** | Joels Kritik wörtlich: man muss sehen, *von welchen Tables* die Rede ist und *in welchem Katalog* |
| Nach | dito | |
| Zustand | Wort + Farbe | Rot **ausschliesslich** hier |
| Belege | Anzahl + Art (Abfragen, Nutzungsfenster) | |
| Zuletzt belegt | Datum, oder „nicht gemessen" | |
| Urteil | Modell / Regel / Enthaltung | |

Die Herkunft steht **klein über** dem Tabellennamen, nicht dahinter in Klammern.
Ein Name ohne seinen Ort ist bei 5.594 Datensätzen wertlos.

### Detailspalte (bei Auswahl einer Zeile)

Von oben nach unten, in dieser Reihenfolge:

1. **Der Satz.** Urteil zuerst, in normalem Deutsch, ohne Fachwort:
   > „`store_sales_ranking_east` bezieht laut Katalog Daten aus
   > `store_revenue_weekly_east`. In den letzten 33 Tagen hat **keine einzige
   > Abfrage** beide zusammen berührt, obwohl beide Tabellen benutzt wurden
   > (4 Nutzungsfenster). Die Kante ist **tot**."
2. **Die Belege**, einzeln aufgelistet und anklickbar: Abfrage-URN,
   Nutzungsfenster mit Datum und Zahl, Ko-Okkurrenz-Treffer.
3. **Der Zeitverlauf** — Balken je Tag, mit der Null-Regel oben.
4. **Das Modellurteil** — entweder mit **wörtlichem Zitat**, sichtbar als Zitat
   ausgezeichnet und mit Quellfeld benannt, oder der **Grund der Enthaltung** im
   Klartext („Zitat zu kurz, kein Beleg").
5. **Aktionen** — was das Werkzeug zurückschreiben würde, mit Journal und
   Rücknahme. Jede Aktion nennt vorher, was genau sie schreibt.

## Bereich 3 — Katalog (der Baum)

Beantwortet Joels Satz *„wenn ich jetzt denken oder schauen will wo das bei uns
so ist"*.

```
postgres
└── probate_seedlab
    ├── gl_journal_entries_daily            ● bestätigt
    ├── finance_income_statement_consolidated
    ├── store_revenue_weekly_east           ● tot
    └── …
```

Aufklappbar, durchsuchbar, mit Zustandspunkt je Tabelle. Klick auf eine Tabelle
filtert **Verbindungen** auf diese Tabelle. Der Baum ist Navigation, keine
Dekoration — er lebt in der Seitenleiste-Ebene, nicht auf einer Arbeitsfläche.

## Bereich 4 — Läufe

Tabelle der Läufe: Zeitpunkt · Modus (voll/delta) · geprüfte Kanten · Dauer ·
Enthaltungsquote · Artefaktpfad. Klick öffnet den Lauf. Zwei Läufe vergleichen
zeigt, was sich geändert hat — das ist der Beweis, dass das Werkzeug wiederholbar
misst.

## Bereich 5 — Belege

Alle gesammelten Belege durchsuchbar: wörtliche Zitate mit Quelldatei und Feld,
Abfrage-Texte, Nutzungsfenster. Das ist der Bereich, den ein Prüfer aufschlägt,
wenn er dem Werkzeug nicht glaubt. Er muss existieren.

## Ebene 3 — Stil (erst jetzt)

Joels Vorgabe, wörtlich bindend:

> *Verständlich, schön, erklärend, beruhigend, modern, SaaS-Vibe, professionell.
> Rot ausschliesslich für Kanten-Zustände, nie für Rahmen, Kopfzeilen oder
> Knöpfe. Kein AI-Slop: keine Emoji-Marken, kein Farbverlauf-Hero, nicht alles
> zentriert, kein Creme+Terrakotta, kein Inter/Space Grotesk, nicht überall
> dieselbe grosse Rundung. Massstab: „das ist ein Produkt", nicht „das ist ein
> Hackathon-Projekt".*

Dazu:

- **Dichte statt Luft.** Eine Enterprise-Konsole zeigt viel auf wenig Platz.
  Grosszügige Weissräume sind hier kein Qualitätsmerkmal, sondern verschenkter
  Bildschirm.
- **Linksbündig.** Zentrierte Fliesstexte gibt es in Datenwerkzeugen nicht.
- **Zahlen tabellarisch** (`font-variant-numeric: tabular-nums`), damit Spalten
  untereinander stehen.
- **Zustandsfarben nur an vier Stellen**: Punkt in der Tabelle, Chip im Filter,
  Wort in der Detailspalte, Balken im Verlauf. Sonst neutral.

## Was NICHT gebaut wird

- Keine Kachel-Wand aus Kennzahlen ohne Nenner.
- Keine Fachwörter als Überschrift. „Edge Ledger", „Declared", „Measured",
  „Co-Occurrence" kommen als Überschrift **nicht** vor. Wenn ein Fachwort nötig
  ist, steht die Erklärung daneben, nicht in einem Tooltip.
- Kein Knopf, dessen Wirkung man erst nach dem Drücken erfährt.

## Abnahme

Die Oberfläche ist fertig, wenn ein Fremder ohne Erklärung:

1. sagen kann, wie viele Verbindungen geprüft wurden und wie viele davon tot sind,
2. eine tote Verbindung findet, **ohne** zu wissen, wonach er sucht,
3. bei dieser Verbindung sagen kann, **welche zwei Tabellen in welcher Datenbank**
   gemeint sind,
4. den Beleg dafür sieht, dass sie tot ist — inklusive wörtlichem Zitat oder dem
   Grund, warum es keines gibt,
5. den Unterschied zwischen „gemessene Null" und „nicht gemessen" erkennt,
6. und das alles bei **5.594 Datensätzen** tut, ohne dass die Seite hängt.

Punkt 6 wird gemessen, nicht geschätzt: Ladezeit und Bildwiederholrate bei
vollem Katalog gehören ins Abnahmeprotokoll.
