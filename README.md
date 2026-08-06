# Probate

Ein Agent, der eine Datenbanktabelle in [DataHub](https://datahub.com) **richtig** stilllegt:
er misst die echten Abhängigen statt sie zu behaupten, beweist die Gleichwertigkeit des
Nachfolgers, holt pro Abhängigem eine Unterschrift ein, schaltet um — und hinterlässt eine
**stehende Regel** im Katalog statt eines Berichts, der morgen niemand mehr liest.

Gebaut für **„Build with DataHub: The Agent Hackathon"**, Track *Agents That Do Real Work*
(*„reads DataHub…, takes action, and writes results back"*).

## Die These

Ein Tabellenabbau scheitert selten an der Technik. Er scheitert daran, dass niemand mit
Sicherheit sagen kann: **„Nutzt das wirklich noch jemand?"** und **„Ist der Nachfolger wirklich
gleichwertig?"**. Beides wird meist behauptet, nicht gemessen — und DataHub selbst kann es
nicht: es speichert, zeigt und indiziert `testResults` auf 24 Entitätstypen und **führt keinen
einzigen Test aus**.

Probate bringt den fehlenden Auswerter mit und schreibt nichts zurück, was es nicht belegen
kann. Eine Enthaltung ist ein Ergebnis: fehlende Zeilenzahlen ergeben **kein** „ok", sondern ein
begründetes Nein.

## Der Ablauf, ein echter Lauf

```
$ probate start --from customers_v3 --to customers_v4
{ "live": 1, "dead_wood": 0, "missing_lineage": 1, "live_targets": 1 }        → examples/campaign-start.json

$ probate apply --from customers_v3 --to customers_v4 --old-rows 48213 --new-rows 48213
{ "live_consumers": 1, "parity_ok": true, "signed": 1 }                       → examples/campaign-apply.json
```

Live gegen eine echte DataHub-Instanz (v1.5.0.6) gemessen, 2026-08-06. Vorher/Nachher der
Regelauswertung, direkt aus dem Katalog zurückgelesen:

| Regel | vorher | nachher |
|---|---|---|
| `has-successor` | ❌ FAILURE | ✅ SUCCESS |
| `parity-proven` | ❌ FAILURE | ✅ SUCCESS |
| `all-consumers-signed` | ❌ FAILURE | ✅ SUCCESS |

→ [`examples/testResults-vorher-nachher.json`](examples/testResults-vorher-nachher.json),
jeder Schreibvorgang dahinter journalisiert in [`examples/journal.jsonl`](examples/journal.jsonl).

**Und der Verweigerungsfall, genauso echt:** eine zweite Tabelle mit 8,8 % Zeilenabweichung
wurde **nicht** umgeschaltet — kein Konsument angefragt, keine Unterschrift eingeholt, nichts
deprecated. → [`examples/campaign-refused.json`](examples/campaign-refused.json)

```
REFUSED - keine Umschaltung ohne Beweis:
  - Zeilenzahl weicht um 8.8% ab (100000 -> 91200), erlaubt sind 1%
```

## Architektur

| Modul | Aufgabe |
|---|---|
| `probate/gms.py` | einziger Weg nach draussen — verriegelt zwei stille Fehlschlagsklassen von DataHubs REST/GraphQL-APIs (siehe „Was live gefunden wurde") |
| `probate/targets.py` | deklarierte Lineage gegen gemessene Nutzung aus dem Query-Log — die Differenz selbst ist ein Ergebnis (Karteileiche vs. fehlende Lineage) |
| `probate/parity.py` | der Beweis: Schema-Diff + Zeilenzahl-Toleranz, Enthaltung statt Freibrief bei fehlendem Beleg |
| `probate/writeback.py` | einziger Schreibweg — dry-run als Vorgabe, jeder Schreibvorgang journalisiert, echter Rückwärtsgang (löscht Aspekte, die es vorher nicht gab, statt sie auf `None` zu setzen) |
| `probate/ruleset.py` | der Auswerter, den DataHub nicht hat — schreibt `testResults`, das DataHub nur anzeigt |
| `probate/succession.py` | Nachfolge nur gegen Beweis, feste Reihenfolge (Zusage → Version verknüpfen → erst dann abkündigen) |
| `probate/campaign.py` | die Unterschrift über DataHubs eigene Formular-Oberfläche, inkl. Owner-Absicherung |
| `probate_action/watcher.py` | Rückfall-Erkennung über den Aspekt, nicht über den Actor (Ingest/Propagation sind actor-seitig nicht von echten Zugriffen zu unterscheiden) |
| `probate/cli.py` | `start` (messen, dry-run) · `apply` (der ganze Ablauf) · `status` · `revert` |
| `harness/audit_claims.py` | prüft jede Zahl in diesem README gegen die Lauf-Artefakte, Exit 1 bei Drift |

## Nachprüfen, ohne irgendetwas zu installieren

```bash
uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q
# 55 passed

uv run --python 3.11 python harness/audit_claims.py
# Alle 3 Zahlen decken sich mit den Laeufen.
```

Beide Befehle laufen offline gegen die committeten Artefakte in `harness/runs/` und `examples/`.

## Selbst laufen lassen

Braucht eine echte DataHub-Instanz (`datahub docker quickstart`). **Standard-GMS ist
`http://localhost:28080`**, nicht 18080 — 18080 trägt in dieser Session die
`showcase-ecommerce`-Demodaten, gegen die eine zweite Einreichung (`datahub-attest`)
Zahlen misst, die nicht verunreinigt werden dürfen. Gegen die eigene Instanz mit `--gms`
umleiten.

```bash
probate start --from '<vorgaenger-urn>' --to '<nachfolger-urn>'
probate apply --from '<vorgaenger-urn>' --to '<nachfolger-urn>' --old-rows N --new-rows N
probate revert   # nimmt jeden journalisierten Schreibvorgang dieser Session zurueck
```

`--old-rows`/`--new-rows` sind bewusst manuelle Eingaben: Probate hat keine
Warehouse-Anbindung zum Selbstzählen eingebaut. Eine erfundene Zählung wäre schlimmer als eine
fehlende — genau das Prinzip, das dieses Projekt selbst durchsetzt.

## Was live gefunden wurde, nicht im Bauplan stand

Neun eigenständige Funde beim Bauen gegen eine echte Instanz, jeder mit Commit-Beleg in der
Git-Historie:

1. `POST /openapi/v3/entity/<typ>` verlangt eine **Liste** — ein Objekt liefert HTTP 200 mit
   leerem `[]` und schreibt nichts.
2. GraphQL meldet Fehler mit HTTP 200 im `errors`-Feld.
3. `_QUERIES_Q` aus der ursprünglichen Planung existiert nicht im Schema — die echte
   `QuerySubject.pdl` indiziert das Zieldataset als `@Searchable`-Feld, keine Graph-Relationship.
4. `Deprecation.actor` ist ein Pflichtfeld der Aspekt-Validierung.
5. **`revert_all()` übersprang im ursprünglichen Entwurf jeden Erst-Schreibvorgang**
   (`before=None`) — genau der Normalfall bei Probate, da die meisten Zieltabellen noch nicht
   deprecated sind. Ein Revert, der den häufigsten Fall lautlos nicht zurücknimmt, ist die
   Fehlerklasse, gegen die dieses Projekt selbst antritt. Korrigiert: Löschen statt ein
   erfundenes `None` zurückzuschreiben.
6. `TestResults.pdl` hat kein Zeitstempelfeld — ein geplantes `lastComputed` wurde von der
   REST-API mit HTTP 200 angenommen und beim Rücklesen stillschweigend verworfen.
7. `createForm` verlangt `structuredPropertyParams` schon beim Anlegen des Prompts, nicht erst
   bei `submitFormPrompt` — und in anderer Feldform als dort.
8. Prompt-IDs sind **global eindeutig über alle Formulare der Instanz**, nicht pro Formular.
9. Pythons eingebautes `hash()` ist für Strings **nicht stabil über Prozessläufe**
   (PYTHONHASHSEED) — eine VersionSet-URN, die darauf aufbaute, wäre bei jedem Neustart eine
   andere gewesen. Ersetzt durch `hashlib.sha1`.

## Bewusste Lücke

Der Kafka-Action-Pipeline-Start (`probate_action/recipe.yml`) wurde **nicht live gestartet** —
dieser Task ist im eigenen Bauplan der erste Streichkandidat bei Zeitmangel, und ein echter
Lauf hätte eine Kafka-Konsumentengruppe offen gehalten, ohne in dieser Session prüfbare
Ereignisse zu erzeugen. `is_relapse()` und `ProbateWatcher.act()` sind vollständig getestet
(Unit-Ebene); der reine Pipeline-Start ist ungeprüft und wird als solcher geführt.

## Lizenz

Apache 2.0, siehe [`LICENSE`](LICENSE).
