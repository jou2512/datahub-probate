# Übergabe — alles, was ein frischer Agent braucht

*Geschrieben 2026-08-06 abends. Für einen Lauf ohne den vorherigen Chatverlauf.*

**Frist: Montag 10.08.2026, 23:00 MESZ.** Bautage: Fr 07., Sa 08., So 09. Der 10. ist Puffer.

**Lies zuerst:** [`docs/superpowers/specs/2026-08-06-lineage-truth-design.md`](docs/superpowers/specs/2026-08-06-lineage-truth-design.md)
— das ist die Spezifikation, sie ist vollständig und geprüft. Diese Datei hier ist die
Betriebsanleitung dazu.

---

## 1 · Was in einem Satz gebaut wird

Ein Agent, der **fortlaufend** die **deklarierte Lineage** in DataHub gegen die **gemessene
Nutzung** hält und die Differenz **pro Kante** ausgibt — tote Kanten (behauptet, nie benutzt),
fehlende Kanten (benutzt, nie behauptet), mit Zeitachse („tot seit 117 Tagen").

**Der Satz, der es von allem anderen trennt** (620 Repos geprüft, gehört ins README und ins Video):

> Alle anderen benutzen Nutzungsdaten, um Kanten zu **gewichten**, denen sie ohnehin glauben.
> Dieses Werkzeug benutzt sie, um die Kante selbst zu **prüfen**.

---

## 2 · Umgebung — hart geprüft, nicht raten

```
Python        NUR uv run --python 3.11 …
              ("python" im PATH ist ein kaputter 3.9-Store-Alias, DataHub braucht 3.10+)

GMS           http://localhost:28080     ← IMMER diese Instanz benutzen
Kafka         localhost:29192            ← NICHT 9092 (das ist Instanz 1)
Schema-Reg    http://localhost:28080/schema-registry/api/   ← es gibt KEINEN Dienst auf 8081

NIEMALS 18080  — trägt showcase-ecommerce, gegen das datahub-attest veröffentlichte
                 Zahlen gemessen hat. Lesen ok, schreiben nie.
NIEMALS 8080   — Joels WhatsApp-Bridge.
```

**Actions-Pipeline starten** (der Befehl heisst `actions`, nicht `run`):
```bash
uv run --python 3.11 --with acryl-datahub-actions datahub-actions actions -c probate_action/recipe.yml
```

**Tests + Beleg-Prüfung** (beide müssen grün sein, bevor irgendetwas als fertig gilt):
```bash
uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q
uv run --python 3.11 python harness/audit_claims.py
```
Aktueller Stand: **61 Tests grün, 3 Beleg-Prüfungen grün.**

---

## 3 · Was schon steht und funktioniert

| Datei | Zeilen | Zustand |
|---|---|---|
| `probate/gms.py` | 111 | Einziger Weg nach draussen. Beide Stille-Fallen verriegelt, `--token`/`DATAHUB_TOKEN` drin |
| `probate/targets.py` | 112 | **Rechnet den Vergleich schon** — Dreier-Split. Wird auf Kanten-Ebene erweitert |
| `probate/parity.py` | 85 | Gleichwertigkeitsbeweis, Enthaltung statt Freibrief |
| `probate/writeback.py` | 84 | Journal + echter Rückwärtsgang. **Nicht anfassen, funktioniert** |
| `probate/ruleset.py` | 91 | Regel-Auswerter, schreibt `testResults`. Fehler werden laut (`errored`) |
| `probate/succession.py` | 78 | Nachfolge, feste Reihenfolge |
| `probate/campaign.py` | 100 | Formulare + `ensure_owner` |
| `probate/cli.py` | 281 | `start` · `apply` · `confirm` · `revert` |
| `probate_action/watcher.py` | 86 | Rückfall-Wächter. **Startet nachweislich** (3 Konfigfehler behoben) |
| `harness/audit_claims.py` | 53 | Prüft README-Zahlen gegen Lauf-Artefakte, Exit 1 bei Drift |
| `harness/seed_queries.py` | 39 | Legt Query-Entitäten an (Katalog hat keine) |
| `harness/preflight.py` | 150 | 9 Mutations gegen die echte Instanz |

---

## 4 · Gemessene Wahrheiten — nicht neu herausfinden

**Nutzungsdaten schreiben** (live verifiziert: 3 Buckets geschrieben, 150 aggregiert zurückgelesen):
```python
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import DatasetUsageStatisticsClass, TimeWindowSizeClass

em = DatahubRestEmitter(gms_server='http://localhost:28080')
aspect = DatasetUsageStatisticsClass(
    timestampMillis=<ms>,
    eventGranularity=TimeWindowSizeClass(unit='DAY', multiple=1),
    uniqueUserCount=2, totalSqlQueries=50)
em.emit_mcp(MetadataChangeProposalWrapper(entityUrn=URN, aspect=aspect))
```

**Nutzungsdaten lesen** (GraphQL, liefert Buckets *und* Aggregat):
```graphql
dataset(urn: $urn) {
  usageStats(range: MONTH) {
    buckets { bucket metrics { totalSqlQueries uniqueUserCount } }
    aggregations { totalSqlQueries uniqueUserCount }
  }
  statsSummary { queryCountLast30Days uniqueUserCountLast30Days }
}
```

**Konsumenten aus Ko-Okkurrenz** (der Weg, der funktioniert — fünf andere wurden live
durchprobiert und liefern null):
```graphql
searchAcrossEntities(input: {
  types: [QUERY], query: "*", count: 200,
  orFilters: [{ and: [{ field: "entities", values: [$urn] }] }]
}) { total searchResults { entity { urn } } }
```
Dann pro Treffer `get_aspect("query", urn, "querysubjects")` → alle berührten Tabellen.

**Aspekt löschen** (für den Rückwärtsgang bei Erst-Schreibvorgängen):
`DELETE /openapi/v3/entity/<typ>/<urn>/<aspekt>` → HTTP 200, danach ist er weg.

---

## 5 · Fallen, die schon Blut gekostet haben

| # | Falle |
|---|---|
| 1 | `POST /openapi/v3/entity/<typ>` will eine **Liste**. Objekt → HTTP 200, schreibt nichts |
| 2 | GraphQL meldet Fehler **mit HTTP 200**, im `errors`-Feld |
| 3 | `Deprecation` braucht **`actor`** (Pflichtfeld), sonst HTTP 400 |
| 4 | `TestResults` hat **kein Zeitstempelfeld** — erfundene Felder werden still verworfen |
| 5 | `createForm` will `structuredPropertyParams` **beim Anlegen**, andere Feldform als `submitFormPrompt` |
| 6 | Prompt-IDs sind **global eindeutig über die ganze Instanz** |
| 7 | `submitFormPrompt`/`verifyForm` liefern **Boolean direkt** — `{ success }` scheitert |
| 8 | Pythons `hash()` ist **nicht prozessstabil** → `hashlib.sha1` |
| 9 | `verifyForm` braucht `actors:{owners:true}` **und** Handelnder muss Owner sein |
| 10 | Ohne Token ist der Handelnde `urn:li:corpuser:__datahub_system`, nicht `datahub` |
| 11 | Der MCP-Server hat **keine Zeitfenster** — Timestamps in `gql/queries.gql` auskommentiert |
| 12 | `get_lineage` liefert **>100'000 Zeichen** ohne Pagination-Vorgaben |

---

## 6 · Die Reihenfolge

### Freitag — Schicht 1 + 1b (Fundament, nie streichbar)
1. `probate/ledger.py` (neu): Kanten-Register. Pro Kante vier Zustände:
   `confirmed` · `dead` · `missing` · **`unknown`**
2. **Abdeckungs-Prüfung vor jeder Klassifikation**: wie viele Nutzungs-Zeitfenster gibt es
   überhaupt, wie weit reichen sie zurück? Dünne Abdeckung wird ausgewiesen, nicht verschwiegen
3. **Zeitachse**: letzte Deckung · tot-seit (Tage) · Verlauf je Zeitfenster
4. Tests für alles davon

> **Der Fehler, den Schicht 1 behebt:** In der alten Fassung fielen „nichts gemessen" und
> „nichts genutzt" in dieselbe leere Antwort, und der Fall „deklariert, nichts gemessen" galt
> als *unbedenklich*. Bei fehlender Datenlage wäre ein aktiver Konsument stillschweigend
> überfahren worden. `unknown` darf **nie** wie `dead` behandelt werden.

### Samstag — Schicht 2, 3, 4
5. **Modell-Urteil** (`probate/judge.py`): welche Abweichung ist wichtig? Liest Beschreibung,
   Owner, Glossar, Domäne. **Zitatpflicht** — ohne benannte Quelle kein Urteil, dann bleibt es
   beim deterministischen Befund. Einzige Stelle im Projekt mit Modellaufruf.
6. **Korrektur-Modus**: fehlende Kante eintragen · tote markieren · Doku aus Nutzung. Immer
   Vorschlag → Mensch bestätigt → Journal. Über das bestehende `writeback.py`.
7. **Wächter live** mit korrigierter `recipe.yml` (29192 / GMS-Schema-Registry)
8. **Werkbank** (`ui/`): vier Bereiche + sechs Knöpfe. Details in der Spec, Abschnitt „Schicht 4"

   > **Gestaltung ist bindend, nicht Geschmackssache.** Joels Vorgabe: *verständlich, schön,
   > erklärend und beruhigend, modern, SaaS-Vibe, professionell — ohne AI-Slop-Look.*
   > Vollständige Auslegung in der Spec unter „Gestaltung". Kurzfassung:
   > **beruhigend** (Rot nur für Kanten-Zustände, nie für Rahmen/Kopf/Knöpfe) ·
   > **erklärend eingebaut** (jeder Zustand trägt seinen Satz an Ort und Stelle) ·
   > **zwei Quellen, zwei Farben, durchgehend gleich** ·
   > **Zustand hat eine Form, nicht nur eine Zahl** ·
   > **verboten:** Emoji-Marken, Farbverlauf-Hero, alles zentriert, Creme+Terrakotta,
   > Inter/Space Grotesk, überall gleiche grosse Rundung.
   > Massstab: „das ist ein Produkt", nicht „das ist ein Hackathon-Projekt".

### Sonntag — messen und einreichen
9. **Lasttest**, drei Stufen (S 1'000 / M 10'000 / L 100'000 Abfragen). Messplan in der Spec.
   Ergebnis kommt ins README, **auch wenn es kippt**
10. **README auf Englisch** (die alte Fassung war deutsch — 3/10 in der Jury-Simulation)
11. `examples/` mit echten Läufen · Video <3 min · Devpost-Text · Upstream-Beitrag

---

## 7 · Regeln, die nicht verhandelbar sind

1. **Nichts behaupten, was nicht gemessen ist.** Das ist nicht nur Hausregel — es ist der
   Gegenstand der Einreichung. Eine Zahl ohne Beleg widerlegt das eigene Produkt.
2. **Jeder Live-Lauf räumt hinter sich auf.** Probe-Entitäten löschen und die Löschung
   zurücklesen.
3. **Geseedete Daten werden als geseedet ausgewiesen** — in jedem Artefakt, im README, im Video.
4. **Rangfolge der Wahrheit:** Live-Aufruf > Quellcode > Doku > Blogartikel.
5. **Eine gescheiterte Abfrage ist keine Abwesenheit.** „Nicht geprüft" und „gibt es nicht"
   sind verschiedene Aussagen.
6. **HITL:** Repo öffentlich machen, Video veröffentlichen, Devpost abschicken, Upstream-PR
   öffnen — macht Joel, nie der Agent.

---

## 8 · Was der Prüfer sonst fragt — vorbereitete Antworten

**„Wo ist der Agent?"** — Fünf von sieben simulierten Juroren fragten das bei der alten
Fassung. Antwort: das Modell entscheidet, *welche* Abweichung wichtig ist — Urteil über
unstrukturierten Text, keine Regel. Alles andere bleibt deterministisch, und das ist Absicht.

**„Macht DataHub das nicht selbst?"** — Nein, geprüft: `sql_parsing_aggregator.py:1534` baut
die Kantenliste bei jedem Lauf **frisch und leer**, liest nie bestehende Kanten.
`remove_upstream_lineage()` existiert und hat **null Aufrufer**. DataHubs eigener Kommentar in
`LineageMatchType.pdl`: *„not re-evaluated automatically"*.

**„Gibt es das nicht schon?"** — 620 Repos erfasst, 33 tief gelesen. Sieben lesen beide
Quellen, alle sieben als Gewicht an Kanten, denen sie glauben. Ko-Okkurrenz-Richtung: null
Vorbild.

**„Und DataHubs eigener Blogartikel?"** — Der paart die Signale bereits, aber immer auf
**Objekt**-Ebene und von Hand. Der Satz muss ins README, sonst schreibt ihn ein Prüfer selbst
auf die falsche Seite:
> Andere paaren Lineage und Nutzung, um zu entscheiden, ob eine **Tabelle** weg kann — einmal,
> von Hand. Wir prüfen laufend jede **Kante** und sagen, seit wann sie nicht mehr gedeckt ist.

---

## 9 · Ehrlich offen — muss im README stehen

- **Devpost-Galerie unveröffentlicht** (2'708 Teilnehmer) — GitHub ist nur Stellvertreter
- **~44 Repos ungelesen**, nicht entlastet (die drei alarmierendsten einzeln nachgeholt, entwarnt)
- **„Metadata Tests" in DataHub Cloud ist Closed Source** — die versprochene Doku-Tabelle
  existiert im Quelltext gar nicht. „Cloud kann das nicht" ist **unbelegbar**, gilt als Risiko
- **Lasttest offen** bis Sonntag
- **Echte Warehouse-Anbindung nie getestet** — die Messkette lief nur gegen selbst eingespielte
  Daten
- **Zeilenzahl bei der Stilllegung wird von Hand eingegeben** — bewusst (erfundene Zählung wäre
  schlimmer), aber es heisst, dass die wichtigste Zahl getippt wird

---

## 10 · Das Dashboard — laufend pflegen

**Joel liest das morgens als erstes.** Es muss den echten Stand zeigen, nicht den geplanten.

- **URL:** https://claude.ai/code/artifact/c818e1b1-583d-4be1-bfd4-c71e4961049b
- **Datei:** `C:\Users\joel2\AppData\Local\Temp\claude\C--AI-OS-projects-datahub-hackathon-2026\c2a8c457-0804-4ea8-9a14-b89f8823b51c\scratchpad\probate-bauplan.html`
- **Anleitung:** steht als HTML-Kommentar ganz oben in der Datei

**Nach jedem abgeschlossenen Schritt:** Datei bearbeiten, dann Artifact-Tool mit
`file_path` **und** `url` (beide oben) — dann bleibt die URL gleich und Joel sieht den
Fortschritt an derselben Stelle.

Zu aktualisieren: Zeitstempel (`#stamp`) · Phasenstatus (`pstate-open|run|done|block`) ·
Abnahme-Häkchen (`class="ok"` am `<li>`) · neue Protokollzeile **oben** in `#protokoll` ·
Gates (`#gates`) · Blocker (`#blocker`).

**Zwei Regeln dazu:** Jede Protokollzeile trägt eine **Zahl**, kein Gefühl („41 tote Kanten
gefunden", nicht „läuft gut"). Und keine Phase wird auf `done` gesetzt, solange ihre Abnahme
nicht abgehakt ist.

## 11 · Zwei Artefakte zum Nachlesen

Für Menschen geschrieben, nicht für den Bau — aber sie erklären das Warum vollständig:

- **Ist-Zustand, alles erklärt:** https://claude.ai/code/artifact/4f495f6c-3b2c-4d11-b9e7-01ce3d64cfab
- **Zielzustand mit Werkbank und Lasttest:** https://claude.ai/code/artifact/87990576-73b4-43cf-8085-97eaece09bbe
