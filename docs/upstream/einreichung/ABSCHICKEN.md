# Abschicken — fertige Befehle, einer nach dem anderen

**Nichts davon wurde ausgeführt.** Die sechs Befunde sind am **2026-08-10** gegen die laufende
Instanz nachgemessen worden (`harness/upstream_repro.py`, alle neun Proben `OK`, Exit 0), die
Bodies stehen fertig daneben. Was hier fehlt, ist genau ein Schritt: Joel kopiert eine Zeile
und drückt Enter.

Vorbedingung: `gh auth status` zeigt ein Konto mit Schreibrechten auf *eigene* Issues (das
Standard-`repo`-Scope genügt; beide Ziel-Repos nehmen Issues von aussen an). Arbeitsverzeichnis:
`D:\Programmieren\datahub-probate`.

> **Keine `--label`-Flags.** Labels darf nur setzen, wer Push-Rechte auf das Repo hat; ein
> `--label bug` von aussen lässt den Befehl fehlschlagen. Die Maintainer labeln selbst.

---

## Reihenfolge

Bugs vor Doku, und der Kommentar erst **nach** Schritt 2 — sein Text verweist darauf, dass der
GraphQL-Zwilling bereits als eigenes Issue liegt.

### 1 · Falsche Zahl in der UI (der wichtigste)

```
gh issue create --repo datahub-project/datahub --title '`usageStats.aggregations.uniqueUserCount` is always 0 while buckets in the same response report 4 and 3' --body-file docs/upstream/einreichung/03-uniqueusercount-aggregation-zero.md
```

Meldet den einzigen Befund, der eine **falsche Zahl** statt eines Fehlers liefert — und zwar
eine, die auf der Dataset-Seite angezeigt wird (`uniqueUserCountLast30Days`). Bittet um eine
Entscheidung zwischen drei Fixes, statt einen zu raten.

### 2 · 500 statt Validierungsfehler (GraphQL)

```
gh issue create --repo datahub-project/datahub --title '`Dataset.usageStats` returns HTTP 500 "Name is null" when the nullable `range` argument is omitted' --body-file docs/upstream/einreichung/01-usagestats-range-500.md
```

Meldet ein als optional deklariertes Argument, das faktisch Pflicht ist, **mit der Codestelle**
(`DatasetUsageStatsResolver.java:35`, `UsageTimeRange.valueOf(null)`). Enthält das Fix-Angebot.

### 3 · Kommentar, **kein** neues Issue

```
gh issue comment 19016 --repo datahub-project/datahub --body-file docs/upstream/einreichung/02-limit-npe-KOMMENTAR-zu-19016.md
```

Befund 02 (`getTimeseriesAspectValues` ohne `limit` → 500 NPE) ist am **09.08.2026** bereits von
jemand anderem gemeldet worden (Issue #19016). Ein zweites Issue wäre ein Duplikat. Der
Kommentar bringt, was dort fehlt: die **Codestelle** (`AspectResource.java`, `response.setLimit(limit)`
unboxt null, während `startTimeMillis`/`endTimeMillis` daneben null-geschützt sind), die
Bestätigung per rohem `curl` (also nicht SDK-spezifisch), und den Verweis auf denselben
Fehlertyp in GraphQL.

### 4 · Anderes Repository — der MCP-Server

```
gh issue create --repo acryldata/mcp-server-datahub --title 'Query entities have no timestamp over MCP: `queries.gql` comments out `properties.created` and `lastModified.time`' --body-file docs/upstream/einreichung/06-mcp-query-timestamps.md
```

Der einzige Befund, der **nicht** ins Haupt-Repo gehört. Zeigt auskommentierte Zeilen in den
mitgelieferten GraphQL-Dokumenten und beweist mit einem Live-Aufruf, dass GMS die Felder sehr
wohl liefert — also Client-Defekt, nicht Backend-Grenze. Verweist auf #168 und #171 als
Nachbarn, damit es nicht wie ein Duplikat aussieht.

### 5 · Doku: was `buckets.length` wirklich bedeutet

```
gh issue create --repo datahub-project/datahub --title 'Docs: `usageStats.buckets` is a dense calendar grid, and the null-vs-zero distinction inside it is undocumented' --body-file docs/upstream/einreichung/04-usagestats-buckets-calendar-grid.md
```

125 Buckets für 8 gemessene Tage. Bittet um eine Schema-Beschreibung und liefert die Formulierung
gleich mit — inklusive der eigentlich wichtigen Regel: `null` heisst *nie gemessen*, `0` heisst
*gemessen und war null*.

### 6 · Doku: eine Zeile von acht, ohne Hinweis

```
gh issue create --repo datahub-project/datahub --title 'Docs: OpenAPI v3 get-aspect returns only the newest row for timeseries aspects, indistinguishable from a complete response' --body-file docs/upstream/einreichung/05-openapi-v3-timeseries-latest-only.md
```

Der harmloseste Befund und der letzte in der Reihe: die Antwort ist korrekt, sie sagt nur nicht,
dass sie unvollständig ist.

---

## Danach

- **Nummern notieren.** Die sechs Links gehören in die Einreichung — Open-Source-Beiträge werden
  von den Veranstaltern ausdrücklich positiv gewertet.
- **Optional, Joels Entscheidung:** in jedes Issue eine Zeile mit dem Link auf das öffentliche
  Repo (`https://github.com/jou2512/datahub-probate`) nachtragen, damit Maintainer
  `harness/upstream_repro.py` selbst laufen lassen können. Bewusst **nicht** in die Bodies
  geschrieben: das README dort ist eine Hackathon-Einreichung, und ein Issue soll nach Befund
  aussehen, nicht nach Werbung. Der Satz „happy to share the script" steht stattdessen drin.
- **Nicht nachreichen, was nicht gemessen ist.** Drei weitere Verhaltensweisen liegen in
  `docs/upstream/README.md` unter *Measured but not filed* — die bleiben liegen, bis eine
  Instanz mit funktionierendem Timeseries-Consumer da ist.

## Was bewusst NICHT eingereicht wird

| Befund | Grund |
|---|---|
| 02 als eigenes Issue | Duplikat zu #19016 (09.08.2026). Wird Kommentar. |
| `uvx …@latest` löst auf 0.4.0 auf, 0 Mutations-Tools, ~54 s Telemetrie | War in unseren eigenen Notizen, hat die Nachmessung nicht überlebt (`@latest` → 0.6.0, 6/18 Tools, 0.315 s). Steht ausserdem schon als #167 im MCP-Repo — ein **fremdes** Issue, das inzwischen falsch ist. Ein Korrektur-Kommentar dort wäre freundlich, ist aber nicht Teil dieses Pakets. |
| Die drei `unconfirmed-*`-Proben | Auf dieser Instanz nicht messbar (Timeseries-Consumer hängt). Ein Artefakt eines kaputten Message-Bus als DataHub-Eigenschaft zu melden wäre genau der Fehler, gegen den dieses Projekt argumentiert. |
