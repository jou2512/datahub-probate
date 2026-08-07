# Probate — an agent that tests lineage instead of trusting it

Probate reads the lineage a [DataHub](https://datahub.com) catalog **declares**, reads the query
usage the catalog **measured**, and reports the difference **per edge** — with a date attached:
covered until when, dead since when, and where no statement is possible at all.

Built for *Build with DataHub: The Agent Hackathon*, track **Agents That Do Real Work**
(*"reads DataHub…, takes action, and writes results back"*).

## What separates this from everything else

> Everyone else uses usage data to **weight** edges they already believe.
> This tool uses it to **test the edge itself**.

That is not a slogan, it is the result of a survey of the field. Seven projects were found that
read both sources. All seven attach usage to an edge as a weight, a hint, or an evidence string
on lineage they already accept. None of them ask whether the edge should exist.

**And DataHub's own blog post?** It pairs the two signals already — but it pairs them to judge a
*table*, once, by hand:

> "Lineage shows what's connected to what. Dataset usage and query history shows what's actually
> being read … Together they turn 'might still be used' into a binary."

The delimitation, in the words we want a juror to use:

> Others pair lineage and usage to decide whether a **table** can go — once, by hand.
> We check every **edge**, continuously, and say since when it stopped being covered.

## The four states

The unit of judgement is the edge, not the table.

| State | Meaning | Evidence carried with the verdict |
|---|---|---|
| `confirmed` | declared **and** measured | query URN + the time windows it was seen in |
| `dead` | declared, **never** measured inside the window | window length, number of buckets checked |
| `missing` | measured (query co-occurrence), **not** declared | query URN, number of co-occurrences |
| `unknown` | **no data in the window — no statement possible** | why: no usage data / no buckets |

### Why `unknown` is not `dead`

This is the failure the project exists to correct, and it was our own failure first.

In the earlier version, "we measured nothing" and "nothing was used" collapsed into the same
empty list, and the resulting category counted as *harmless*. So on a catalog with thin or
missing usage coverage, a real, active consumer would have been quietly overwritten by a tool
that sounded confident.

The distinction is present in the data and is now made explicitly: **no time windows at all**
means we cannot see; **time windows that exist and read zero** means we looked and nothing
happened. Before anything is classified, Probate runs a coverage check — how many usage windows
exist, how far back they reach — and reports thin coverage as a result, instead of selling it as
a measurement.

A tool whose whole claim is "assert nothing without evidence" does not get to guess here.

## Where is the agent?

Exactly one place, deliberately: **the model judges which deviation matters.**

A dead edge into a table whose description mentions the annual close is not the same as a dead
edge into a nameless intermediate table. That is judgement over unstructured text — description,
owners, glossary terms, domain — not a rule anyone can write. Everything else in the pipeline is
deterministic and testable offline.

The model works under a **citation duty**: no verbatim quote from the text it was given, no
judgement, and the deterministic finding stands unchanged. The fallback is the normal case, not
an error case.

Measured against the seeded four-state lab
([`harness/runs/judge-seedlab-matrix.json`](harness/runs/judge-seedlab-matrix.json)):

| Focus | State | Model judgement | Citation |
|---|---|---|---|
| confirmed | `confirmed` | not offered to the model | excluded by design — a confirmed edge needs no judgement |
| dead | `dead` | fell back to the deterministic finding | `fallback_reason: "kein Zitat geliefert"` (no quote supplied) |
| missing | `missing` | yes | quoted the downstream `description` |
| unknown | `unknown` | yes | quoted the upstream `description` |

So the citation duty bites: on one of the three edges offered, the model produced no usable
quote and was overruled by its own rule. We consider that the feature working, and we report it
rather than tuning the fixture until the number looks better
([`docs/entscheidungen/2026-08-07-seed-hinweis-nicht-zitierfaehig.md`](docs/entscheidungen/2026-08-07-seed-hinweis-nicht-zitierfaehig.md)
records a related decision: our own "this data is seeded" disclaimer was removed from the citable
corpus, because a quote from the label that marks data as fake proves nothing about the data).

## What DataHub does not do

Checked in source and against a live instance, not assumed.

| Finding | Evidence |
|---|---|
| **DataHub replaces lineage, it never compares it.** `sql_parsing_aggregator.py:1534` builds a fresh, empty edge list (`UpstreamLineageClass(upstreams=[])`), fills it only from the queries parsed in *this* run, and emits it as a full aspect. The file's only aspect read (`:665`) fetches `SchemaMetadataClass` — schema resolution, not lineage. | read in the cloned source, master @ `26a9f6c` |
| Both ingestion modes are blind: the default overwrites in full (dropping legitimate old edges), `incremental_lineage: true` only appends — dead edges accumulate forever, are never reported, never removed. | source + `docs/features/feature-guides/lineage.md:106` (the doc statement holds only with the `incremental_lineage` flag set) |
| `DatasetPatchBuilder.remove_upstream_lineage()` **exists and has zero callers** — grep over the cloned tree including all of `metadata-ingestion` finds nothing but the definition, not even a test. *Limitation: the clone is partial; trees we did not clone could contain callers.* | `metadata-ingestion/src/datahub/specific/dataset.py:167` |
| DataHub's own edge verdict `LineageMatchType` only checks URN resolvability, and its own docstring says: *"reflects DataHub's knowledge AT THE TIME THE LINEAGE EDGE WAS INGESTED, not the current state of the graph … not re-evaluated automatically"* | `dataset/LineageMatchType.pdl` |
| No assertion type targets lineage (OSS enum read live: `DATASET, FRESHNESS, VOLUME, SQL, FIELD, DATA_SCHEMA, CUSTOM`). | live introspection |
| `isManual` is self-declared, not enforced: an edge written over REST with `{"source":"UI"}` came back as `isManual: true` without ever passing through the UI. | live counter-check, three edges written and read back |

## Quickstart

Python on this machine must be pinned — a bare `python` hits a broken 3.9 alias, and DataHub
needs 3.10+. Every command below is verified to run as written.

```bash
# The edge ledger: declared lineage vs. measured usage, per edge, with timeline
uv run --python 3.11 probate ledger \
  --focus 'urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.dead_upstream,PROD)' \
  --gms http://localhost:28080

# ... with the model judging which deviations matter (the only model call in the project)
uv run --python 3.11 probate ledger --focus '<dataset-urn>' --judge --judge-limit 5

# The workbench: serves ui/ and proxies writes through the single write path
uv run --python 3.11 python -m ui.serve --gms http://localhost:28080 --focus '<dataset-urn>'
# then open http://localhost:8899

# The retirement flow that can follow from a ledger full of dead edges
uv run --python 3.11 probate start   --from '<predecessor-urn>' --to '<successor-urn>'
uv run --python 3.11 probate apply   --from '<predecessor-urn>' --to '<successor-urn>' \
                                     --old-rows N --new-rows N
uv run --python 3.11 probate confirm --entity '<consumer-urn>' --evidence '<written by a human>'
uv run --python 3.11 probate revert   # undo every journalled write of this session

# The continuous watcher (the subcommand is `actions`, not `run`)
uv run --python 3.11 --with acryl-datahub-actions \
  datahub-actions --debug actions -c probate_action/recipe.yml
```

Offline, against the committed artifacts, without a DataHub instance:

```bash
uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q
uv run --python 3.11 python harness/audit_claims.py
```

Two notes that cost us time and are therefore written down:
`python -m probate.cli` runs to completion and does **nothing** — `cli.py` has no
`if __name__ == "__main__"` block; use the `probate` entry point declared in `pyproject.toml`.
And `--debug` belongs **before** `actions`, otherwise the Kafka log lines stay invisible while
the pipeline is in fact running.

`--old-rows` / `--new-rows` are deliberately typed in by a human. Probate has no warehouse
connection to count rows itself, and an invented count would be worse than a missing one — the
same principle the tool enforces on everyone else.

Against a secured instance: `--token <PAT>` or `DATAHUB_TOKEN`. Without a token the actor is
`urn:li:corpuser:__datahub_system`, which only works against an instance without access control.

## The workbench

A dashboard that only shows numbers proves nothing — you cannot tell whether it computed them or
someone typed them in. So the UI is a lab, not a report: four panes (declared / measured / edge
ledger / live log) and six buttons that change the two truth sources for real, through the same
journalled write path as the CLI.

The demo, forty seconds, three directions:

1. **Add edge** — the edge appears as `dead` (declared, no traffic).
2. **Seed query** — the same edge turns `confirmed` (traffic now measured).
3. **Cut warehouse** — it turns `unknown`, **not** `dead`. This is the button that carries the
   demo: it shows in five seconds that the tool really distinguishes "nothing measured" from
   "nothing happened".

Opened without the proxy, `ui/werkbank.html` falls back to the recorded run in
[`ui/recorded/ledger.json`](ui/recorded/) and labels itself as a recording rather than
disguising itself as a live session.

## Measured numbers

Every number below is derived from a committed artifact in `harness/runs/` and re-checked by
`harness/audit_claims.py`, which exits 1 on any drift between prose and run. Nothing here is
estimated, rounded, or remembered.

**All usage data in these runs is seeded** ([`harness/seed_lineage_lab.py`](harness/seed_lineage_lab.py),
namespace `probate_seedlab`). DataHub's sample catalog ships none — live check: `totalSqlQueries:
null`, `buckets: []`. Every artifact carries `"seeded": true` for this reason.

### Four states, end to end

| Result | Value | Artifact |
|---|---|---|
| all four states matched the manifest's expectation | `true` | [`seedlab-verdicts.json`](harness/runs/seedlab-verdicts.json) |
| at least one edge judged by the model with a citation | `true` | [`judge-seedlab-matrix.json`](harness/runs/judge-seedlab-matrix.json) |

A single-focus ledger run against the confirmed pair
([`ledger.json`](harness/runs/ledger.json)): 1 edge total, 1 `confirmed`, 0 `dead`, 0 `missing`,
0 `unknown`, over 3 usage buckets spanning 2 days. The run flags its own coverage as thin — that
flag is the point.

### Write, verify, undo

Nothing is written without a proposal, a human, and a journal entry with a real reverse gear
([`correct-roundtrip.json`](harness/runs/correct-roundtrip.json),
[`upstream-properties-probe.json`](harness/runs/upstream-properties-probe.json)):

| Check | Value |
|---|---|
| the pre-existing edge survived the merge | `true` |
| the new edge was present after the write | `true` |
| column-level lineage survived the merge | `true` |
| custom properties survived the write-back | `true` |
| writes reverted | `2` |
| revert restored the aspect exactly | `true` |

### Load test

Two measurements, not one, and they should not be conflated.

**The coarse pass scales linearly with catalog size** — that half is genuinely supported. From S to
M the catalog grows ten-fold, 50 → 500 tables (`loadtest_s_datasets` / `loadtest_m_datasets`), and
the coarse pass grows with it, 1.235 s → 12.238 s (`loadtest_s_coarse_seconds` /
`loadtest_m_coarse_seconds`) — 0.0247 s versus 0.0245 s per dataset, one GraphQL call per table
either way (`loadtest_s_coarse_api_calls` / `loadtest_m_coarse_api_calls`), and an identical 93
characters of response per call across S, M and the independent smoke run
(`loadtest_s_coarse_response_chars` 4,650 / 50, `loadtest_m_coarse_response_chars` 46,500 / 500,
`loadtest_smoke_coarse_response_chars` 4,650 / 50).

**What the coarse pass flags as suspicious is a different question, and this test does not
demonstrate the two-stage cost saving it was originally read as showing.** Both runs flag *every
single dataset*: 50 of 50 at S, 500 of 500 at M (`loadtest_s_coarse_suspicious` /
`loadtest_m_coarse_suspicious`, both 100 %) — confirmed by an independent probe run against the
same scale (`loadtest_smoke_coarse_suspicious`, 50 of 50). The reason is structural, not a fluke of
one run: `coarse_pass()` flags a dataset whenever `statsSummary.queryCountLast30Days` is falsy, and
our synthetic fixtures are upserted straight through GMS — they never pass through DataHub's
usage-aggregation pipeline, so `statsSummary` essentially never populates for them. The coarse
triage does not triage anything on synthetic data; it marks all of it.

That also means the "41 suspicious edges in both S and M" figure that an earlier version of this
README treated as a finding was a **cap artifact**, not a result: `run_stage()` unconditionally
truncates the detail sample to `detail_sample` (41 by default,
`sample = (coarse.get("_suspicious") or [])[:41]`) regardless of how many datasets were actually
flagged. What the detail pass duration *does* show, honestly stated: it takes comparable time for a
**fixed-size 41-edge sample** regardless of catalog size — 35.614 s at S, 47.217 s at M
(`loadtest_s_detail_seconds_total` / `loadtest_m_detail_seconds_total`) — which is true by
construction, since `detail_pass` loops over whatever list it is handed, not because it is
selectively skipping a growing catalog. Per-edge time for that identical 41-edge sample rose
~32.6 % from S to M (0.8686 s → 1.1516 s, `loadtest_s_detail_seconds_per_edge` /
`loadtest_m_detail_seconds_per_edge`) — recorded as an **unexplained finding**, not glossed over as
"comparable": a plausible but unconfirmed factor is that `fetch_cooccurrence` queries against the
instance's entire query corpus, which is ten times larger at M, but no controlled counter-test
isolated this from general instance load during measurement.

Whether real-world suspicious-edge counts stay flat as a catalog grows is **not demonstrated by
this test** — our synthetic fixtures never populate `statsSummary` and are therefore all flagged,
by construction. That is a real limitation of our own measurement, not a property we can claim for
production data.

| Stage | Tables | Queries | Seed | Coarse pass | Coarse API calls | Coarse suspicious | Edges in detail pass | Detail pass | Per edge | Detail peak mem |
|---|---|---|---|---|---|---|---|---|---|---|
| S | 50 | 1,000 | 11.84 s | 1.235 s | 50 | 50/50 (100 %) | 41 (capped) | 35.614 s | 0.8686 s | 1.7 MB |
| M | 500 | 10,000 | 198.52 s | 12.238 s | 500 | 500/500 (100 %) | 41 (capped) | 47.217 s | 1.1516 s | 1.71 MB |
| L | 5,000 (fully seeded) | 100,000 planned, 5,600 written (5.6 %) | aborted at 735 s | not run | — | — | — | not run | — | — |

Artifacts: [`loadtest_s.json`](harness/runs/loadtest_s.json),
[`loadtest_m.json`](harness/runs/loadtest_m.json),
[`loadtest_l.json`](harness/runs/loadtest_l.json).

### Full run vs. daily delta

The design spec calls this the question that decides whether the tool is usable in a real company
or only in an example: a full reconciliation may take two hours, as long as the daily follow-up
takes minutes. It is now measured, not argued
([`full-vs-delta.json`](harness/runs/full-vs-delta.json)):

| Scale | Full run | Daily delta | Speed-up | API calls, full → delta |
|---|---|---|---|---|
| S, 50 datasets | 5.765 s | 0.077 s | **74.87×** | 91 → 2 |
| M, 500 datasets | 23.567 s | 1.377 s | **17.11×** | 541 → 20 |

**What "delta" means here, because a ratio without its definition is a number with an unknown
denominator.** A full run queries `statsSummary` for *every* dataset in the catalog and then runs
the detail pass over its suspicious edges. The daily delta runs the same two passes over the
**newest 2 %** of the plan list (`change_fraction`). That 2 % is an explicit **proxy** for "changed
since the last marker": our synthetic fixtures carry no real write-timestamp field, so there is
nothing to filter on honestly. When no marker is set at all, delta falls back to a full run and the
tool reports **"not cheaper"** rather than manufacturing a speed-up.

What dominates each side is not symmetrical, and it is worth saying: the full run is dominated by
the coarse pass scaling with catalog size (500 calls at M against 50 at S). The delta run is
dominated by nothing — the target set is too small to cost anything measurable.

So the ratio falls as the catalog grows, 74.87× to 17.11×, which is the expected shape: the delta's
cost is roughly fixed while the full run's grows. The number that matters for daily operation is
not the ratio but the absolute one — **1.377 s** for a delta pass on a 500-table catalog.

**Stage L did not finish seeding, and coarse/detail never started.** What actually happened, per
the artifact's own binary search against `get_aspect` (not the seed loop's own counters, and
deliberately not `search`, whose index lags ~30 s): the 5,000 datasets and their 5,000 lineage
edges were completely written (`loadtest_l_seed_measured_datasets_total`,
`loadtest_l_seed_measured_edges_total`) by the time the run was stopped at 735 s
(`loadtest_l_wall_clock_seconds_to_abort`) — but only 5,600 of the planned 100,000 queries had
landed (`loadtest_l_seed_measured_queries_written` of `loadtest_l_seed_measured_queries_total`),
5.6 %. In batches: **78 of 550 planned** (`loadtest_l_seed_measured_batches_completed` of
`loadtest_l_seed_measured_batches_total_planned`). The 78 is worth breaking down, because the two
numbers in it are easy to confuse and an earlier draft of this README did confuse them: 25 dataset
batches + 25 edge batches + **28 query batches**. The dataset and edge phases finished completely;
only the query phase was cut off, 28 of its **500** batches at a batch size of 200 — which is where
the 5,600 comes from. "28 of 550" would have been wrong in both halves. Coarse and detail passes
never ran because
there was nothing finished to hand them. The artifact also carries a projected full-seed duration
(≈86.4 min, nested under `loadtest_l_extrapolation`) — a **linear extrapolation** of this run's
own observed rate (`loadtest_l_seed_measured_seconds_per_batch`, 9.42 s/batch), not a second
measurement, and it is stored as a nested field precisely so `audit_claims.py` can never mistake
it for one — nested values are outside the audited scalar set by construction (see
`harness/audit_claims.py`'s `load_runs()`). Cleanup for stage L is verified with 0 leftover
(`loadtest_l_cleanup_verified`, `loadtest_l_cleanup_leftover`).

Cleanup, stated as it happened: stage S cleaned up and verified in one pass, 0 leftover
(`loadtest_s_cleanup_verified`, `loadtest_s_cleanup_leftover`). **Stage M did not** — one
`delete_aspect` call (of roughly 2,500) hit a transient HTTP 500 on `datasetUsageStatistics`, an
aspect `generate()` never writes for stage M in the first place. The read-back loop inside that
same `cleanup()` call still counted 0 leftover afterwards (`loadtest_m_cleanup_leftover`) —
correctly, since that aspect was never created — but `cleanup_verified` is still recorded as
`false` (`loadtest_m_cleanup_verified`), because `cleanup()` treats *any* delete error as
unverified regardless of the leftover count. That is the honest classification: an HTTP 500 is a
failure of the call, not evidence about the data, and folding "0 leftover" into "nothing went
wrong" would hide the failed call behind a read-back that happened to come back clean. A retry
cleaned up without error and verified (`loadtest_m_cleanup_retry_verified`), and an independent
full read-back over all 500 datasets and 10,000 queries — outside `cleanup()` entirely — confirmed
0 remaining before and after that retry (`loadtest_m_final_state_verified`). The first attempt is
recorded as failed rather than silently overwritten by the successful retry.

### The continuous watcher

Started live against the real Kafka broker
([`watcher-live.json`](harness/runs/watcher-live.json)): 80 events received, 1 relapse detected
and correctly refused as a dry run, 0 edges reclassified.

That last zero is honest and it is the weakest measured result in this repository — see the
limitation below.

### The retirement flow

Live against a real DataHub instance ([`campaign.json`](harness/runs/campaign.json)):
1 live consumer measured, parity proven (`parity_ok: true`), 1 consumer sign-off collected.
`apply` proposes and stops; `confirm` is a separate, explicit command with human-written
`--evidence` that Probate never calls for itself. Refusal is a result: a second table with a row
count deviating beyond tolerance was **not** switched over.

## Honest limitations

All of them. If a section like this is missing from a submission that claims "no assertion
without evidence", the submission has already contradicted itself.

**About the survey that produced the "nobody else does this" claim.** These counts come from the
competitive survey documented in the design spec, not from a run artifact — they are not covered
by `audit_claims.py`, and they are the softest figures in this document:

- The Devpost gallery is **unpublished** (2,708 participants). GitHub is only a proxy; private
  or unlinked repositories are invisible to us.
- Roughly 44 repositories were requested and never returned. They are **unread, not cleared**.
  The three most alarming names were fetched individually and are cleared.
- GitHub's repository search does not index READMEs, and code search covers default branches with
  a page limit. Our count of neighbouring projects is a **lower bound**, not a census.
- **"Metadata Tests" in DataHub Cloud is closed source.** The property table the docs promise does
  not exist in the markdown source. What is documented is that usage is already a predicate there.
  "Cloud cannot do this" is therefore **unprovable**, and we carry it as a risk, not as an
  all-clear.

**About the measurements:**

- **This submission does not use the Agent Context Kit.** The DataHub MCP server is not called
  anywhere in the shipped code. We planned to use it for co-occurrence and dropped it for the three
  measured reasons in the Architecture section — no time windows, no mutation tools at the pinned
  version, ~54 s of telemetry per call. We are stating this rather than leaving it to be found:
  it is a real gap against what a reviewer may expect, and "we could integrate it" would be a
  promise, not a result.
- **The workbench does not show the model's judgement.** The design calls for the edge ledger to
  expand to timeline *and* model assessment. Only the timeline is rendered (`ui/werkbank.js`); the
  quote, the reason and the fallback marker exist in the ledger output and in
  `harness/runs/judge-seedlab-matrix.json`, but you have to read them from the CLI or the artifact,
  not from the UI. The citation duty is implemented and measurable; it is just not visible where
  the design says it should be.
- **Usage data is seeded.** The sample catalog ships none. Every number above was measured against
  data we wrote ourselves, and every artifact says so.
- **No real warehouse connection has ever been tested.** The entire measurement chain ran against
  a local instance and our own fixtures.
- **Row counts at retirement are typed in by a human.** Deliberate — an invented count would be
  worse — but it means the single most consequential number in the retirement flow is typed, not
  measured.
- **Co-occurrence is undirected.** `QuerySubject` has no direction field. A `missing` edge
  therefore records its direction as **inferred**, not measured.
- **The load test does not demonstrate the two-stage cost saving it was designed to measure.** Both
  runs flag 100 % of datasets as suspicious (`loadtest_s_coarse_suspicious`,
  `loadtest_m_coarse_suspicious`) because our synthetic fixtures never populate `statsSummary` —
  they are written straight through GMS and never pass DataHub's usage-aggregation pipeline. What
  is demonstrated: the coarse pass scales linearly with catalog size, and the detail pass takes
  comparable time for a fixed-size sample regardless of catalog size. What is *not* demonstrated:
  that the number of suspicious edges stays flat as a real catalog grows — that would require usage
  data DataHub itself aggregated, which this test never had.
- **The full-vs-delta speed-up is measured against a proxy, not against real change detection.**
  The "daily delta" is the newest 2 % of the plan list (`change_fraction`), standing in for "changed
  since the last marker", because our synthetic fixtures carry no write-timestamp field to filter
  on. The ratios (74.87× at S, 17.11× at M) are real measurements of that proxy workload. What is
  *not* established is that a real catalog's daily change set is 2 %, or that DataHub exposes a
  reliable marker to select it — both are open. With no marker, the tool falls back to a full run
  and reports "not cheaper".
- **The GMS instance hung completely during this measurement.** Over two hours of silent logs and
  an unresponsive server, mid-run. It had to be restarted (volumes preserved) before the run could
  be completed. The published numbers are from the clean re-measurement *after* that restart; the
  contaminated run's numbers appear nowhere. We are recording this because someone reproducing the
  load test on the same quickstart stack may hit the same hang, and because "our benchmark
  environment fell over" is exactly the kind of fact that quietly disappears from a submission.
- **The detail pass got 32.6 % slower per edge from S to M on an identical 41-edge sample**
  (0.8686 s → 1.1516 s). This is recorded as an **unexplained finding**. A plausible factor is that
  `fetch_cooccurrence` queries against the instance's whole query corpus, ten times larger at M —
  but no counter-test isolated that from general instance load during the measurement, so it stays
  a correlation, not a cause.
- **Load test stage L never reached the coarse/detail passes.** Seeding was aborted at 735 s with
  datasets and edges fully written but only 5.6 % of planned queries in place; the full-seed
  duration in the artifact is an extrapolation from this run's own batch rate, not a measurement.
  See above.
- **`loadgen.cleanup()` does not know how far a seed run actually got.** It always walks the full
  *planned* set for the requested scale, not what `generate()` actually wrote
  (`harness/loadgen.py:131-162`). At scale L that is 5,000 datasets × 3 aspects
  (`DATASET_ASPECTS`, `harness/loadgen.py:53`) plus all 100,000 planned query URNs — 115,000
  delete calls — and the same function's own read-back loop repeats that full walk a second time,
  roughly 230,000 HTTP calls in total, to clean up a run that had actually written 5,600 queries.
  It happened to finish inside this measurement (`loadtest_l_cleanup_verified: true`, 0 leftover),
  but the cost does not scale with what was written, only with what was planned — a real scaling
  defect in our own harness, not in Probate.
- **The watcher's re-evaluation could not be shown changing a verdict.** The pipeline demonstrably
  receives real Kafka events and detects a relapse. But running `probate ledger` before and after
  a freshly emitted `datasetUsageStatistics` aspect returned **byte-identical** timeline and
  coverage blocks, twice, including after a wait. The write itself is proven (`get_aspect` read
  the new timestamp back); the GraphQL `usageStats` aggregation simply did not show it. `docker
  ps` on the stack used here shows no separate usage-statistics indexer container. We record this
  as "the aggregation layer lags or does not run in this GMS-only environment" — and explicitly
  not as "the watcher reclassifies edges", which we did not observe.
- **All containers of this quickstart stack report `unhealthy`** in `docker ps` (verbatim output
  in the watcher artifact), while GMS answers HTTP 200 on the same stack and the four-state check
  runs to completion. We state the flag and the working behaviour side by side. We do not claim
  the flag is harmless, and we do not claim it explains the aggregation lag above.

**A gap that remains in DataHub's model, not ours:** "which person reads which column" is not
expressible — user counts and column counts live in separate lists with no link between them.
Not a build item; a clean side finding for an upstream contribution.

## Architecture

| Module | Job |
|---|---|
| `probate/ledger.py` | the edge ledger: four states, coverage check, timeline (last covered, dead since, series per window) |
| `probate/judge.py` | the only model call in the project — judges which deviation matters, under citation duty, injectable transport, hard timeout, falls back to the deterministic finding on any error |
| `probate/correct.py` | proposals: add a missing edge, mark a dead one, enrich documentation from observed usage — never applied without confirmation |
| `probate/targets.py` | declared lineage vs. measured usage; the difference itself is the result |
| `probate/gms.py` | the only way out — locks two silent failure classes of DataHub's REST/GraphQL APIs |
| `probate/writeback.py` | the only write path — dry-run by default, every write journalled, real reverse gear (deletes aspects that did not exist before instead of writing back an invented `None`) |
| `probate/parity.py` | schema diff + row-count tolerance; abstention instead of a free pass when evidence is missing |
| `probate/ruleset.py` | the evaluator DataHub does not have — writes `testResults`, which DataHub only displays |
| `probate/campaign.py` | sign-off through DataHub's own form UI |
| `probate_action/watcher.py` | relapse detection over the aspect, not the actor |
| `ui/` | the workbench: live mode through the proxy, recorded mode without an instance |
| `harness/audit_claims.py` | re-derives every number in this README from the run artifacts; exit 1 on drift |

### One transport, and why it is not the MCP server

**Both paths — dead edges and missing edges — go through raw GraphQL against GMS.** The design
originally called for two transports, with co-occurrence coming from the DataHub MCP server's
`get_dataset_queries`. It does not. `grep -rn -i mcp probate/*.py` returns nothing; co-occurrence
is fetched with `searchAcrossEntities` in `probate/ledger.py` and `probate/targets.py`, the same
way as everything else. An earlier version of this paragraph described the plan instead of the
code, which in a document whose thesis is "claims carry evidence" is the worst possible place to
get it wrong.

The MCP server was evaluated and then not used, for three measured reasons:

| Reason | Measurement |
|---|---|
| **No time windows.** Dead-edge classification needs an N-day window; `get_dataset_queries` cannot express one — its timestamp fields are commented out in `gql/queries.gql`. | read in the server source |
| **No mutation tools at the pinned version.** `mcp-server-datahub@latest` resolves to 0.4.0 and registers zero mutation tools, so nothing could be written back through it. | tool list counted after pinning |
| **~54 s of telemetry per tool call.** Over a load run that is the difference between a night and a week. | measured per call |

So the honest architectural statement is: this is a single-transport tool, and the second
transport was dropped on evidence, not on preference. The consequence is stated in the
limitations below — **this submission does not use the Agent Context Kit.**

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
