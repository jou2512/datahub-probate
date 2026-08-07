# Entscheid: ein zweiter, grosser Katalog neben dem Vier-Kanten-Labor

*07.08.2026, Nachtlauf. Anlass: Joel, wörtlich — „die DEMO!!!!! sie muss gut sein… ist sie
aber nicht!!!!" und davor „firmen haben evt 1000 sachen… das hier wird bei 4 schon
unübersichtlich."*

## Anlass

Das Werkzeug **kann** Enterprise, die Demo **zeigt** es nicht. Bei vier Kanten hat nichts an
der Konsole einen Grund zu existieren: Filter filtern nichts, der Katalogbaum hat einen Ast,
Sortierung ist sinnlos, Seitenaufteilung überflüssig. `docs/werkbank-spec.md` misst jedes
Bauteil an 5.594 Datensätzen — die Demo lief gegen acht.

## Entscheid 1 — daneben, nicht dazu

Das Labor `probate_seedlab` bleibt **unangetastet**. Es ist die Abnahme
(`harness/seedlab_verdicts.py`, Exit 0) und der Ort der bewiesenen Zustandsübergänge
(`harness/runs/demo-transitions.json`). Der neue Katalog liegt in einem eigenen Namensraum
(`probate_demo_*`, `harness/seed_demo_catalog.py`).

Was zur Wahl stand: (a) das Labor vergrössern, (b) einen zweiten Katalog daneben.
**Gewählt: (b).** Das Labor ist klein, weil jede seiner vier Kanten von Hand gegen ein
Manifest abgenommen ist. Wer es auf 500 Kanten aufbläst, verliert genau diese Eigenschaft.

## Entscheid 2 — der Offenlegungs-Hinweis steht in der URN, nicht nur im Artefakt

Jede Datenbank heisst `probate_demo_<domäne>` (`probate_demo_finance`, `…_marketing`, …).
Das liest sich weniger nach echtem Unternehmen als `finance` — und ist trotzdem richtig:

- Projektregel (`UEBERGABE.md` §7.3): geseedete Daten werden **überall** ausgewiesen. Eine
  Kennzeichnung, die nur im Manifest steht, überlebt keinen Screenshot.
- Kollisionsschutz: auf `28080` liegen 5.594 fremde Datensätze. `finance.core.fct_orders_daily`
  hätte mit dem Showcase kollidieren können, `probate_demo_finance.…` kann es nicht.
- Der Präfix trägt **kein Urteil**: er steht auf jeder Zeile gleich und unterscheidet damit
  keine Kante von einer anderen. Die Regel „kein Zustandswort im Bezeichner"
  (`2026-08-07-seedlab-namen-ohne-etikett.md`) bleibt unverletzt, maschinell geprüft in
  `_assert_names_are_clean()`.

Die Beschreibungen tragen zusätzlich `[probate-demo -- synthetische Demonstrationsdaten]` —
in **eckigen Klammern**, weil `probate/judge.py::_strip_disclosure_prefix` genau diese Form
aus dem zitierfähigen Korpus schneidet (`2026-08-07-seed-hinweis-nicht-zitierfaehig.md`).

[Einschätzung: hier hätte Joel vielleicht realistischere Datenbanknamen gewollt. Die
Offenlegungsregel ist eine harte Projektregel, und ein Screenshot ohne sichtbare
Kennzeichnung wäre der teurere Fehler.]

## Entscheid 3 — Fokusse und Paar-Partner sind disjunkt

Die Query-Ko-Okkurrenz ist **ungerichtet** (`probate/ledger.py::fetch_cooccurrence`). Eine
Paar-Query über `{A, B}` lässt A in Bs Ko-Okkurrenz auftauchen und umgekehrt. Wäre B selbst
ein Fokus, entstünde zu **jeder** bestätigten Kante eine gespiegelte `missing`-Kante `B→A`,
die niemand gemeint hat.

Deshalb: Fokusse sind ausschliesslich die Ebenen `raw` und `core`, Paar-Partner ausschliesslich
`staging` und `marts`. Der Preis: es gibt keine durchgehende Vier-Ebenen-Kette, sondern zwei
Zwei-Schritt-Strecken. Der Gewinn: **jede deklarierte Kante des Demo-Katalogs wird auch
geprüft** — 509 deklarierte, 509 im Register, keine stumme Restmenge.
`_assert_focus_partner_disjoint()` erzwingt es.

## Entscheid 4 — die vier Labor-Fokusse laufen im Demo-Lauf mit

`ui/serve.py::load_recorded_ledger` wählt den Startzustand der Konsole nach
`(passende Fokus-Tabellen, Umfang, Zeitstempel)` — `matched` **zuerst**. Ein Artefakt ohne die
Labor-Fokusse hätte `matched == 0` und verlöre gegen jedes Ein-Kanten-Protokoll, egal wie
gross es ist. Mit allen vieren ist `matched` maximal (4), der Umfang ohnehin, und der
`focus_mismatch`-Warnstreifen bleibt aus.

Das ist kein Trick, sondern die richtige Sicht: eine Konsole zeigt *alle* geprüften Kanten
einer Instanz, nicht die eines Teilprojekts. Nachgeprüft statt angenommen —
`harness/run_demo_ledger.py --verify-console` startet einen Server auf einem eigenen Port
(8901, **nicht** 8899/8898) und liest, welchen Stand er lädt.

## Entscheid 5 — der selbsterklärende `dead`-Fall überwiegt

`classify_edges` kennt zwei Wege zu `dead`:

1. **Fenster gemessen, im Fenster kein Verkehr** — fünf Messfenster, in allen null.
2. **Query-Quelle befragt, keine Paar-Abfrage gefunden** — Verkehr vorhanden, aber nichts
   belegt die Kante.

Beide sind richtig, beide gehören in die Demo. Der zweite liest sich in der **Tabelle** aber
widersprüchlich: Zustand „tot" neben „zuletzt belegt: gestern, 68 Abfragen". Die Erklärung
steht in der Detailspalte (die Zahl gehört der *Tabelle*, nicht der *Kante*), der Widerspruch
in der Zeile.

Erste Messung: 63 von 81 toten Kanten waren vom zweiten Typ. Nach Umgewichtung: **41 vom
ersten, 32 vom zweiten**. Nicht wegdefiniert — umverteilt, damit das Eröffnungsbild den
Fall zeigt, den man ohne Erklärung versteht.

**Offener Befund für die Konsolen-Spur:** die Spalte „Zuletzt belegt" zeigt bei dieser Sorte
`dead` ein frisches Datum. Das ist keine Falschaussage, aber es braucht in der Zeile ein
Wort dazu — heute muss man die Detailspalte öffnen, um es aufzulösen.

## Was gemessen wurde

| | |
|---|---|
| Datensätze | 610 über 4 Plattformen, 5 Datenbanken, 4 Schemata |
| geprüfte Kanten | 513 (509 Demo-Katalog + 4 Labor) |
| Zustände | 266 bestätigt · 145 unbekannt · 73 tot · 29 fehlend |
| Erwartung getroffen | 509 von 509, null Abweichungen |
| Seed | 76,3 s schreiben, alles zurückgelesen |
| Ledger-Lauf | 21,8 s, 1.476 API-Aufrufe, 0,066 s je Fokus |
| Konsole (HTTP, warm) | 16,6 ms je Seite über 513 Kanten |

Belege: `harness/runs/demo-katalog-seed.json` · `harness/runs/demo-katalog-ledger.json` ·
`harness/runs/demo-katalog-claims.json` (die zitierfähige Abschrift, in `audit_claims.py`
aufgenommen) · `examples/demo-catalog-manifest.json`.
