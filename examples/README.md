# Example runs

Every file in this folder is the **unedited output of a real command** against a
live DataHub instance (`http://localhost:28080`, DataHub v1.5.0.6). Nothing here
was hand-written or prettified. Where a file's numbers are seeded/synthetic
(catalog fixtures, not real warehouse traffic), the file says so itself with a
`"seeded": true` field and a `seeded_statement` — that disclosure is part of the
artifact, not something this README adds on top.

If you only have five minutes: read section 1 (the ledger correcting itself),
then section 3 (a write reverting to the exact original byte, including
column-level lineage). Those two are the thesis of this project.

---

## 1. The four-state proof — why an edge is confirmed / dead / missing / unknown

**`seedlab-manifest.json`** — the four lineage edges as seeded by
`harness/seed_lineage_lab.py`, one pair per expected state (`confirmed`,
`dead`, `missing`, `unknown`), each with a one-line description of what makes
it that state (e.g. "declared lineage, usage measured, last traffic ~117 days
ago, then zero").

**`seedlab-verdicts.json`** — command:
`uv run --python 3.11 probate ledger --focus <urn>` run once per seeded pair,
against `http://localhost:28080`, generated `2026-08-07T01:56:33Z`.
`all_four_states_matched_expected: true` — the ledger classified all four
pairs exactly as the manifest intended. Each pair carries its own `evidence`
block, not just a label:

| State | Evidence field | What it says |
|---|---|---|
| `confirmed` | `evidence.source: "declared lineage + query co-occurrence"`, `queries_seen: 1` | declared edge, and a query actually joined both sides |
| `dead` | `evidence.reason: "im geprueften Fenster nie gemessen"` (never measured in the checked window), `buckets_checked: 31`, `dead_since_is_lower_bound: true` | declared edge, 31 usage buckets checked, all zero |
| `missing` | `evidence.source: "query co-occurrence"`, `direction_evidence: "co-occurrence (undirected)"` | no declared edge, but a query touches both datasets — a candidate, not a fact |
| `unknown` | `evidence.reason: "keine Nutzungs-Zeitfenster im Katalog"` (no usage time windows in the catalog at all), `buckets_checked: 0` | declared edge, but zero usage buckets exist to check — this is exactly the state the sample catalog's usage gap forces, and it is not the same as `dead` |

The `dead` vs `unknown` distinction is the point of the whole rebuild: `dead`
means usage was measured and came back empty; `unknown` means there was
nothing to measure. Collapsing the two (treating "no data" as "no traffic")
is the bug this project exists to fix.

## 2. A model judgement with its citation, and a fallback with its reason

**`judge-seedlab-matrix.json`** — command: the judge run over all four seeded
focuses, `judge_limit: 5`, run at `2026-08-10T15:57:13Z`. This one file
contains both halves of the citation duty side by side, per edge:

- **Fallback, no model used** (`dead` focus): `used_model: false`,
  `fallback_reason: "quote only from the seeding notice, no evidence"`,
  `reason: "deterministischer Befund: dead"` — the model did answer and did
  supply a quote, but the only thing it quoted was our own
  `[probate-seedlab …]` seeding label, which is deliberately excluded from the
  citable corpus (see
  `docs/entscheidungen/2026-08-07-seed-hinweis-nicht-zitierfaehig.md`). A quote
  from the label that marks the data as fake is not evidence about the data, so
  the deterministic verdict stands as-is.
- **Model judgement with citation** (`missing` focus): `used_model: true`,
  `quote: "a core growth metric and the basis for marketing budget decisions
  as well as part of the monthly reporting to the executive board"`,
  `source_field: "description"`, `important: true`. The model's claim ("merits
  human review") is anchored to a verbatim quote from the dataset's own
  description field — not asserted on its own authority.
- A second model judgement (`unknown` focus) is included too, quoting a
  different description field, for a second real example of the same
  pattern.

**`judge-transport-probe.json`** — command: a raw transport check of the
`claude -p ... --output-format json` call itself (not a lineage judgement),
measured `2026-08-07T01:24:30Z`. Included because it shows the *other* kind
of fallback: `transport_call_ok: true` (the CLI call itself succeeded,
`raw_reply_len_chars: 235`) but `judged_with_model: false`,
`fallback_reason: "Zitat zu kurz, kein Beleg"` — quoted verbatim from the
artifact, which was recorded on 07.08. before the fallback reasons were
reworded to English; today the same path reads `"quote too short, no
evidence"` — the model answered, but its answer didn't meet the citation bar,
so the system fell back rather than accept an unanchored claim. Also documents
a real trap: `--system-prompt` is required, or the CLI loads this repo's own
`CLAUDE.md`/`AGENTS.md` and answers as a coding agent instead of a judge.

## 3. The correction round-trip — before, written, reverted, column-level lineage survives

**`correct-roundtrip.json`** — command: `probate correct` writing a new
upstream edge (with `probate.evidence` / `probate.direction` properties) onto
`probate_seedlab.finance_income_statement_consolidated`, then `probate revert` undoing it.
Generated `2026-08-07T01:35:25Z`, target has an existing declared upstream
edge and a `fineGrainedLineages` (column-level lineage) block already present
before the write:

1. **`true_original`** — the aspect exactly as it stood before anything ran:
   one upstream edge, no fine-grained lineage.
2. **`after_cll_seed`** — a fine-grained lineage block was seeded on top (one
   field-level edge, `confirmedDownstream.revenue` from
   `confirmedUpstream.amount`) so the round-trip has column-level lineage to
   possibly lose.
3. **`after_write`** — the new upstream edge is added (with evidence
   properties), and the fine-grained lineage block from step 2 is still
   present, unchanged (`cll_survived_the_merge: true`) — the write is a
   merge, not a full-aspect overwrite.
4. **`after_revert`** — back to exactly `true_original`
   (`revert_restored_exactly: true`, `existing_edge_survived_the_merge: true`).

The four flags at the bottom (`revert_restored_exactly`,
`existing_edge_survived_the_merge`, `new_edge_present_after_write`,
`cll_survived_the_merge`) are all `true` in this run — that is the claim this
file backs.

**`enrich-doc-remove-edge-roundtrip.json`** — a second, complementary
round-trip from the same session (generated `2026-08-07T01:56:22Z`): one half
writes a generated description onto a dataset that had none
(`true_original: null`) and reverts it back to absent; the other half removes
a declared upstream edge entirely (`upstreams: []`) and reverts it back to
present. Included as a second real example of the same revert discipline
applied to a different aspect (`institutionalMemory`/description) and to
edge *removal* rather than edge *addition*.

## 4. The watcher receiving a real event

**`watcher-live.json`** — command:
`PYTHONUNBUFFERED=1 uv run --python 3.11 --with acryl-datahub-actions datahub-actions --debug actions -c probate_action/recipe.yml`,
against Kafka `localhost:29192`. This file documents two runs and is honest
about why: the first run (`run_1_receipt_only`) proved the pipeline receives
real Kafka events but only *inferred* that a catalog change triggers a
re-evaluation (from timing + unit tests, not a literal log line). A review
pass caught that gap, `probate_action/watcher.py` was given real logging, and
the pipeline was run again — `run_2_with_logging` is the run with the actual
proof: `watcher_relapse_evidence_verbatim` holds three consecutive log
lines — Kafka receipt, the watcher's `relapse=True` decision, and the
resulting dry-run write result — for the same second
(`2026-08-07 03:51:25`). Both `acceptance_status` halves are marked `MET`
with the log lines that back each one.

**`watcher-stdout.log`** — the full raw stdout the above file quotes from
(173 lines, not trimmed). `grep -c "Kafka msg received"` against this exact
file is how `watcher_events_seen` was counted — an earlier draft of
`watcher-live.json` had this number wrong (10 instead of 11) until it was
recounted against this log; that correction is documented inside
`watcher-live.json` itself (`fix_round_1_note`) rather than silently fixed.

## 5. The load-test numbers that exist

Four separate runs, each a distinct kind of measurement — not four repeats of
the same thing:

| File | What it measured | Headline numbers |
|---|---|---|
| `loadgen_smoke.json` | seed 50 datasets / 1000 queries at scale `s`, then verify full cleanup | `loadtest_s_seed_seconds: 29.76` (7 API calls), full cleanup verified (properties/lineage/query-subjects all absent afterward) |
| `loadtest_smoke.json` | read-only coarse ledger check against the existing instance, no writes | `loadtest_smoke_coarse_seconds: 1.189`, 50 API calls, 0 breaks |
| `loadtest_s.json` | full three-stage run at scale `s` (seed → coarse → detail → cleanup) | seed 11.84s/7 calls, coarse 1.235s/50 calls, **detail 35.614s total across 41 edges (0.869s/edge)**, cleanup verified, 0 leftover |
| `loadtest_m.json` | same three-stage run at scale `m` (500 datasets / 10,000 queries) | seed 198.52s/56 calls, coarse 12.238s/500 calls, **detail 47.217s across 41 edges (1.152s/edge)**, one transient `HTTP 500` on a single `delete_aspect` call during cleanup (on an aspect that was never written) — `cleanup_verified: false` because the harness treats *any* cleanup error as unverified regardless of leftover count, and a manual full read-back before and after confirmed the namespace was actually empty (`loadtest_m_final_state_verified: true`). Reported as a transient GMS error, not a real inconsistency — see the file's own `loadtest_m_cleanup_note` / `loadtest_m_final_state_note` for the full account. |

`loadtest_l.json` (scale `l`, 5,000 datasets) is **deliberately not included
here** — at the time this folder was curated, a parallel lane was still
finalizing that run and its own file says so verbatim
(`cleanup_pending_note`). An in-progress artifact is not evidence; it will be
added once it is finished and its own numbers say so.

---

## Earlier example set — the correction-suggestion campaign

The files below (`campaign-start.json`, `campaign-apply.json`,
`campaign-refused.json`, `preflight.txt`, `testResults-vorher-nachher.json`,
`testResults-refused.json`, `journal.jsonl`, `seedlab-manifest.json` above)
are real runs from an earlier slice of this project: a migration campaign
that moves consumers from a predecessor dataset to a successor one
(`probate campaign start/apply/status`), using DataHub tests, forms, and
assertions as the write surface. They predate the four-state ledger work in
sections 1–5 above and demonstrate a different part of the tool (guided
correction campaigns rather than lineage-truth classification). Left in
place as-is — still real, unedited output, just a different story than the
one this task curated.

- `preflight.txt` — a capability probe against the live GMS: 10 API calls
  attempted, 8 succeeded, 2 failed (`submitFormPrompt`, `verifyForm`) with
  the verbatim GraphQL error bodies. The probe's own conclusion:
  "TOR GESCHLOSSEN" (gate closed) — the spec had to be adjusted before
  building further, and was.
- `campaign-start.json` / `campaign-apply.json` / `campaign-refused.json` —
  three real campaign runs: one dry-run status check, one full apply with a
  live consumer signing off, and one campaign the tool itself refused to
  apply because parity failed (`parity_ok: false`,
  `"Zeilenzahl weicht um 8.8% ab (100000 -> 91200), erlaubt sind 1%"` — row
  count drifted 8.8%, 1% was the allowed threshold).
- `testResults-vorher-nachher.json` / `testResults-refused.json` — DataHub
  `testResults` aspect before and after a successful campaign apply, and the
  same aspect for the refused campaign (both DataHub tests still failing,
  because the apply never happened).
- `journal.jsonl` — the write journal `probate correct`/campaign apply wrote
  as it went, one line per mutation, `"before"` capturing prior state for
  revertible aspect writes and `"reversible": false` for GraphQL mutations
  that have no read-back equivalent (forms, assertions, data contracts).
