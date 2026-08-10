# Probate — an agent that tests lineage instead of trusting it

**Your [DataHub](https://datahub.com) catalog claims which table feeds which. Nobody re-checks
those claims, so they rot — and every migration, deprecation and impact analysis inherits the rot.**

Probate re-checks them, one edge at a time, and attaches a date to every verdict. One run against
the demo catalog in this repo — 618 tables, 4 platforms, 6 databases, 1,476 API calls:

| Verdict | Edges | What you do about it |
|---|---|---|
| `confirmed` | **266** | declared *and* measured — leave it alone |
| `dead` | **73** | declared, zero traffic in the window — **and it tells you since when** |
| `missing` | **29** | real query traffic, never declared — lineage your catalog doesn't know it has |
| `unknown` | **145** | no usage data at all — **no statement made** |
| **total** | **513** | |

That last row is the point. Every lineage-cleanup tool we could find would report those 145 edges
as dead and invite you to delete the tables behind them. Probate refuses: *we could not look* is
not *nothing happened*.

**Try it in two commands, without installing DataHub** → [Quickstart](#quickstart). Every number on
this page is re-derived from a committed run artifact by `harness/audit_claims.py`, which exits 1 on
any drift — 140 numbers are under that gate right now.

Built for *Build with DataHub: The Agent Hackathon*, category **Agents That Do Real Work**
(*"reads DataHub…, takes action, and writes results back"*). Apache 2.0 — see [`LICENSE`](LICENSE).

## What separates this from everything else

> The projects we found use usage data to **weight** edges they already believe.
> This tool uses it to **test the edge itself**.

We say *the projects we found*, and we mean it literally. A survey of the field turned up **seven
projects that read both lineage and usage**. All seven attach usage to an edge as a weight, a hint,
or an evidence string on lineage they already accept. **None of the seven asks whether the edge
should exist.**

That is a statement about seven projects, not about the world. The survey is a **lower bound, not a
census** — GitHub's search does not index READMEs, the Devpost gallery is unpublished, and private
repositories are invisible to anyone outside them. We would rather claim seven and be right than
claim "nobody" and be one counter-example away from wrong. The full limits of that survey are in
[Honest limitations](#honest-limitations).

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

### Prerequisites

- **[`uv`](https://docs.astral.sh/uv/) is the only thing you must install.** It fetches Python 3.11
  and every dependency on first run. Never invoke a bare `python`: on the build machine that
  resolves to a broken 3.9 store alias, and DataHub needs 3.10+. Every command on this page is
  verified to run exactly as written.
- **Only for the live half:** a DataHub OSS quickstart stack answering on `http://localhost:28080`
  (`datahub docker quickstart`). Everything under *Without a DataHub instance* needs no stack, no
  network and no credentials.

### Without a DataHub instance — start here

```bash
git clone <REPO-URL> && cd datahub-probate

# 1. The test suite — runs green in about 30 s, no network
#    (we deliberately do not quote a test count here: it moves with every commit, and a
#     number in prose that nothing checks is the exact thing this project argues against)
uv run --python 3.11 --with pytest --with acryl-datahub-actions python -m pytest tests/ -q

# 2. The evidence gate — re-derives all 140 numbers in this README from harness/runs/,
#    prints each one, exits 1 on any drift
uv run --python 3.11 python harness/audit_claims.py
```

Want to see the console without running anything? **Open
[`docs/werkbank-static.html`](docs/werkbank-static.html) in a browser** — the whole thing in one
self-contained file, all 513 connections from a recorded run with their evidence, no server and
no network. It says *recorded* at the top and shows its writing buttons visibly out of service
rather than pretending they still work. Regenerate it with
`uv run --python 3.11 python harness/export_static.py`. Twenty-one sample outputs from real runs are
in [`examples/`](examples/).

### Against a live DataHub instance

```bash
# The edge ledger: declared lineage vs. measured usage, per edge, with timeline
uv run --python 3.11 probate ledger \
  --focus 'urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.store_revenue_weekly_east,PROD)' \
  --gms http://localhost:28080

# ... with the model judging which deviations matter (the only model call in the project)
uv run --python 3.11 probate ledger --focus '<dataset-urn>' --judge --judge-limit 5

# ... reading co-occurrence through DataHub's own MCP server instead of raw GraphQL.
# Same verdict either way — that is the point. Default is graphql; see "The MCP server" below
# for what each costs and why the age judgement stays on GraphQL.
uv run --python 3.11 probate ledger --focus '<dataset-urn>' --cooccurrence-source mcp

# The workbench: serves ui/ and proxies writes through the single write path.
# No flags needed — see "Starting it" under "The workbench" for the one command
# and the one address.
uv run --python 3.11 python -m ui.serve
# then open http://127.0.0.1:8899/werkbank.html

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

**If a live run fails with `Failed to execute search … Connection refused`, your search backend is
down, not Probate.** GMS keeps answering HTTP 200 and its container keeps reporting `healthy` while
this is true, so the stack looks fine and every search-dependent path — co-occurrence, the `missing`
verdict, the console's *Connections* view — fails anyway. Measured on 2026-08-10: the OpenSearch
container had exited three hours earlier and nothing surfaced it.

```bash
docker ps -a | grep opensearch          # look for an Exited container
docker start <opensearch-container>     # then wait for the cluster to leave status "red"
docker exec <opensearch-container> curl -s localhost:9200/_cluster/health
```

`yellow` is normal and sufficient on a single node — replica shards stay unassigned by design.
Recovery took about a minute here. If verdicts stay wrong after that, the graph index disagrees
with the primary store; `POST /operations?action=restoreIndices` on the affected URN resyncs it,
and `check_es_drift()` detects the condition rather than letting it into a classification.

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
someone typed them in. So the UI is a lab, not a report: five sections (overview / connections /
catalog / runs / evidence) and buttons that change the two truth sources for real, through the
same journalled write path as the CLI.

### Starting it

**One command, one address. There is no second one.**

```bash
uv run --python 3.11 python -m ui.serve
```

Then open **<http://127.0.0.1:8899/werkbank.html>**. No flags are needed: the GMS defaults to
`http://localhost:28080` and the observed tables come from `examples/seedlab-manifest.json`.

If something is already on that port, the server **says so and refuses to start** instead of
sitting down next to it:

```
werkbank: werkbank laeuft bereits auf http://127.0.0.1:8899 (PID 208104) -- nicht zweimal starten.
werkbank: port 8899 ist belegt (PID 4711), und was dort lauscht ist keine werkbank.
```

That guard exists because it happened: on Windows the stdlib's `allow_reuse_address` lets a
second server bind a port that is already being listened on, so two builds of the same page
answered in turn and a reload showed whichever one won the race.

There is also a **single-file copy** of the whole console — no server, no Python, no network:

```bash
uv run --python 3.11 python harness/export_static.py
```

writes `docs/werkbank-static.html`. It carries a recorded run baked in, says so at the top, and
shows its writing buttons visibly out of service rather than pretending they still work.

The demo, forty seconds, three directions. All three buttons sit in the *What you can do to this
catalog* card on **Overview**; the verdict changes in **Connections**:

1. **Declare** (*declare an edge*) — the edge appears as `dead` (declared, no traffic). ~20 s, it
   waits on DataHub's lineage index.
2. **Run** (*run a query*) — the same edge turns `confirmed` (traffic now measured). ~30 s, same
   reason.
3. **Disconnect** (*disconnect the warehouse*) — it turns `unknown` — labelled **Not judged** in
   the UI — and **not** `dead`. This is the button that carries the demo: in about two seconds it
   shows that the tool really distinguishes "nothing measured" from "nothing happened".

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

### The states change when the world changes

Four states existing is not the same as an edge *moving* between them. That movement is the
product's actual claim — we re-measure instead of asserting once — so it is measured, not
described: **7 of 7 transitions proven**
([`demo-transitions.json`](harness/runs/demo-transitions.json),
[`harness/demo_transitions.py`](harness/demo_transitions.py)).

Each one runs the same way: read the state from the ledger → press the button → wait **at least
15 seconds** → read the state again. The state is never taken from the button's own response.
That confusion — HTTP 200, aspect echoed back, nothing written — cost this project a full day
(`UEBERGABE.md`, trap 21), and it is exactly the failure mode the tool exists to expose.

| # | Transition | What changed in the world |
|---|---|---|
| 1 | `missing` → `confirmed` | the edge was declared (`upstreamLineage`) |
| 2 | `confirmed` → `missing` | the declaration was taken back |
| 3 | `dead` → `confirmed` | a query touching both tables was created |
| 4 | `confirmed` → `dead` | that query was removed — the declaration stays, the evidence goes |
| 5 | `confirmed` → `unknown` | the usage timeseries was deleted |
| 6 | `unknown` → `confirmed` | the same usage rows were replayed, unchanged |
| 7 | `unknown` → `unknown` | the observation window moved 30 days forward |

**Row 5 is the one to read twice.** Cutting the usage data does *not* produce `dead`; it produces
`unknown`. Reporting `dead` there would be claiming "never used" without a single measurement —
so the transition is shown with the state it actually reaches, not the one that would have made a
neater demo. Row 7 is the same invariant from the other end: fast-forwarding time changes nothing
for an edge that never had usage data. `dead` is only ever reached the honest way, in row 4:
usage windows present, traffic measured, and no query joining the two tables.

Every mutation goes through the same write path as the buttons in the console — one lock, one
existence check, one journal — and is taken back inside the same run: **3 journal lines appended,
3 reverted**, the deleted usage timeseries replayed row for row (3 rows, identical timestamps and
counters), and all four lab edges measured back to their starting states. `harness/seedlab_verdicts.py`
exits 0 afterwards; if it did not, the transition run would be the thing that failed, not the gate.

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

**About the seven-project survey behind the claim above.** These counts come from the
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
  "DataHub Cloud cannot do this" is therefore **unprovable**, and we carry it as a risk, not as an
  all-clear.

**About the measurements:**

- **The MCP server serves co-occurrence, never the age judgement.** `--cooccurrence-source mcp`
  works and agrees with GraphQL edge for edge, but `queries.gql` in 0.6.0 returns query entities
  with no timestamp and offers no usage-bucket tool, so `dead` versus `confirmed` can only be
  decided over raw GraphQL. Half the pipeline can run on the Agent Context Kit; the half that
  carries the dates cannot.
- **The MCP cost figures are a small sample against a local single node.** Four to six calls, one
  machine. The session-start figure in particular says little about an agent that keeps the session
  open, and the end-to-end ratio should not be read as a throughput claim.
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
- **Container health flags on this quickstart stack are not a usable signal — in both directions,
  and we have now seen both.** During the watcher run, every container reported `unhealthy` in
  `docker ps` (verbatim output in the watcher artifact) while GMS answered HTTP 200 and the
  four-state check ran to completion. On 2026-08-10 the reverse happened: `docker ps` reported
  every running container `healthy`, GMS answered HTTP 200 — and the OpenSearch container had
  exited three hours earlier, so every search-dependent path was failing silently. We are
  correcting the earlier phrasing here rather than deleting it: what we wrote then ("all containers
  report `unhealthy`") was true of that run and is no longer true as a present-tense statement. The
  finding that survives both observations is narrower and more useful: **`docker ps` health and GMS
  returning 200 are both compatible with a broken stack.** See the search-backend note under
  *Quickstart*. We do not claim either flag explains the aggregation lag above.

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

### The MCP server: used, and measured

**We read DataHub over both interfaces.** `probate ledger --cooccurrence-source mcp` reads the
co-occurrence through DataHub's own MCP server (`get_dataset_queries`, pinned to
`mcp-server-datahub==0.6.0`); the default, `--cooccurrence-source graphql`, reads it over raw
GraphQL. The usage windows that carry the dead/confirmed judgement are served by raw GraphQL in
both cases, for the reason below.

**Both paths produce the same verdict, and that is the interesting result.** Run against the same
catalog state across all four lab states, the map and the totals are identical
(`mcp_maps_identical_all_four_states`, `mcp_totals_identical_all_four_states`,
`end_to_end_verdicts_identical`, over `mcp_focuses_compared` = 4 focuses). Every edge field
matches. The only difference is `coverage.window_*`, which is wall-clock from two runs at different
times and is disclosed as such in the artifact. **The transport does not change the finding** —
which is what you want from a transport, and is not something we could have asserted without
running both.

What it costs is in [`mcp-probe.json`](harness/runs/mcp-probe.json) rather than in an adjective:

| | GraphQL | MCP (0.6.0) |
|---|---|---|
| one end-to-end `ledger` run | 0.075 s | 9.661 s |
| API calls for it | 4 | 3 |
| session start (cold / warm) | — | 13.76 s / 9.4 s |
| the four probe reads themselves | 0.121 s over 6 GMS calls | 1.893 s over 4 tool calls |
| telemetry per call (off → on) | — | 0.086 s → 0.401 s, overhead **0.315 s** |

**What dominates is the session start, not the call.** Of the 9.661 s end-to-end MCP run, roughly
9.4 s is bringing the session up. For a one-shot reconciliation GraphQL is faster by orders of
magnitude. For an agent that holds the session open, the per-call picture is different and much
narrower — and the MCP read is **one tool call** where GraphQL needs 1+N. We are deliberately not
reducing this to a single ratio: a headline like "MCP is 130× slower" would be almost entirely
session start, and would be the exact kind of number this project exists to argue against.

**Where the MCP server stops.** In 0.6.0's `queries.gql` the whole `created` block is commented
out, and inside `lastModified` the `time` line as well. A query entity therefore comes back with
**no timestamp at all**, and there is no tool for dataset usage buckets. So co-occurrence over MCP:
yes. An *age* judgement over MCP — `dead` versus `confirmed`, "dead since N days" — no. That is why
GraphQL remains the default: a measured limit of the server, not an opinion about it.

Two statements that look contradictory and are both true, so they belong side by side: a query
entity *does* carry `queryproperties.value.created.time` when read over **GraphQL**
([`query-timestamp-probe.json`](harness/runs/query-timestamp-probe.json)). The field exists in GMS.
The MCP server simply does not ask for it.

**Three things we believed, published, and then disproved by re-measuring.** They were in this
README until 2026-08-07:

| We wrote | Re-measured (0.6.0, `mcp-probe.json`) |
|---|---|
| "`@latest` resolves to 0.4.0" | resolves to **0.6.0**, with *and* without an interpreter pin. Not reproducible. What does hold: 0.5.0+ requires Python ≥ 3.11 where 0.4.0 needed ≥ 3.10, so an unpinned run can land on a smaller tool set |
| "registers zero mutation tools" | **6 tools by default, 18 with `TOOLS_IS_MUTATION_ENABLED=true`** — 12 mutation tools (`tool_count_default`, `tool_count_with_mutations`, `mutation_tool_count`) |
| "~54 s of telemetry per tool call" | **0.315 s** (`telemetry_overhead_seconds`) |

We are naming these rather than quietly deleting them. They were claims about the organisers' own
product, in the one document whose thesis is that claims carry evidence — refuting them ourselves
is cheaper than having a juror do it, and the correction is part of the record.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
