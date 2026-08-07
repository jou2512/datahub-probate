# Entscheid: Auch die Tabellennamen dürfen den Zielzustand nicht verraten

*07.08.2026, Lane „Seedlab-Umbenennung" — Fortsetzung von
[`2026-08-07-seed-beschreibungen-ohne-etikett.md`](2026-08-07-seed-beschreibungen-ohne-etikett.md).*

## Anlass

Drei Fix-Runden haben das Zustandswort aus den **Beschreibungen** der acht Seed-Datasets
entfernt. Die **Bezeichner** blieben unangetastet:

```
probate_seedlab.dead_upstream -> probate_seedlab.dead_downstream   Urteil: dead
```

Die Werkbank zeigt die URN direkt neben dem Urteil. Ein Prüfer liest also wörtlich einen
Namen, der die Antwort ansagt — und der stärkste Beleg der Einreichung (alle vier Zustände
in einem echten Lauf) sieht damit zirkulär aus. Der Mangel ist derselbe wie bei den
Beschreibungen, nur eine Ebene höher und deutlich sichtbarer: wir haben die Prosa saniert
und ihn in den Identifikatoren stehen lassen.

Dasselbe galt für die beiden Query-IDs (`probate-seedlab-confirmed`,
`probate-seedlab-missing`). `probate/ledger.py` schreibt die Query-URN als **Beleg** in jedes
Kanten-Urteil (`evidence.query_urns`) — das Zustandswort stand damit als Beweisstück neben
dem Urteil, das es erst herleiten soll.

## Gewählt

Acht realistische Namen aus **einem** kohärenten Geschäftsdomänen-Set (Handel mit Filialen
und Online-Checkout), passend zu den bereits geschriebenen, zustandsfreien Beschreibungen:

| Paar | Upstream | Downstream | erwarteter Zustand |
|---|---|---|---|
| A→B | `gl_journal_entries_daily` | `finance_income_statement_consolidated` | confirmed |
| C→D | `store_revenue_weekly_east` | `store_sales_ranking_east` | dead |
| E→F | `checkout_events_raw` | `customer_lifetime_value_by_segment` | missing |
| G→H | `customer_dedup_stage` | `crm_migration_staging` | unknown |

Query-IDs: `probate-seedlab-gl-consolidation` und `probate-seedlab-clv-build`.

**Namensregel, ab jetzt bindend** (steht im Code am Ort der Wirkung, `harness/
seed_lineage_lab.py` bei `NAMES`): ein Tabellenname sagt, WAS in der Tabelle steht — nie,
wie die Kante darüber ausfällt. Verboten sind `dead`/`stale`/`unused`/`orphan`/`confirmed`/
`missing`/`unknown` sowie `test`/`demo`; die letzten beiden, weil sie eine Tabelle als
Wegwerf-Artefakt markieren und damit auf dünne Nutzung deuten.

## Was ausdrücklich bleibt

- **Der Namespace `probate_seedlab`.** Er ist die ehrliche Markierung „hier wurde geseedet"
  (UEBERGABE.md §7.3) und muss sichtbar bleiben. Nur der Tabellenteil ist geändert. Ein
  Prüfer soll sofort sehen, dass das ein Labor ist — er soll nur nicht die Antwort sehen.
- **`expected_edge_state` im Manifest.** Das ist die Test-Erwartung, die
  `harness/seedlab_verdicts.py` gegen das gemessene Urteil hält. Sie erscheint nirgends in
  der Oberfläche. `examples/seedlab-manifest.json` trägt jetzt ein `naming_note`-Feld, das
  genau das sagt — sonst liest der nächste Lauf die Erwartung als Etikett und „korrigiert"
  die Namen zurück.

## Warum nicht nur die Anzeige ändern

Naheliegende Alternative: die URN in der Werkbank kürzen oder durch ein Label ersetzen. Das
wäre Kosmetik am Symptom — die alten Namen stünden weiter in jedem committeten Artefakt
unter `harness/runs/` und `examples/`, also genau dort, wo ein Prüfer die Belege nachliest.
Der Name muss in den Daten falsch sein, nicht nur in der Ansicht.

## Was müsste passieren, damit es falsch war

Wenn sich die vier Zustände durch die Umbenennung verschieben. Dürfen sie nicht — sie
entstehen aus Lineage, Nutzungs-Buckets und Query-Subjects, nicht aus Bezeichnern. Die
Gegenprobe ist Pflicht und dieselbe wie beim Beschreibungs-Entscheid:
`harness/seedlab_verdicts.py` muss Exit 0 mit allen vier passenden Zuständen liefern.
Täte es das nicht, wäre der Klassifikator namensabhängig — ein schwerer Befund über das
Produkt, nicht über die Seeds.

Zweiter Weg, auf dem es falsch wird: ein Name, der den Zustand nur subtiler ansagt.
`customer_dedup_stage` und `crm_migration_staging` (das `unknown`-Paar) sind der Grenzfall —
Zwischentabellen sind in einem echten Katalog normal, deuten aber auf geringe Nutzung. Sie
stehen so, weil die bereits abgenommenen Beschreibungen genau das sagen („Zwischentabelle
eines Deduplizierungs-Skripts", „temporäre Ablage eines Migrationstests"); die Namen
erfinden kein Signal dazu, sie bleiben nur konsistent.
[hier hätte Joel vielleicht anders gewollt — er hätte für dieses Paar womöglich zwei ganz
gewöhnliche Fachtabellen genommen und die Beschreibungen mitgezogen.]
