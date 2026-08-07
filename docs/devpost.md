# Probate — an agent that tests lineage instead of trusting it

*Draft for the Devpost submission. Nothing here is published until Joel confirms.*
*Track: Agents That Do Real Work. License: Apache 2.0.*

**Every number in this text is either a key in [`harness/runs/claims.json`](../harness/runs/claims.json),
re-derived from a committed run artifact by `harness/audit_claims.py` (exit 1 on any drift), or
explicitly labelled below as unaudited. All usage data in every run is seeded, and every artifact
carries `"seeded": true` for that reason.**

---

## Inspiration

We set out to build a table-retirement tool: before you delete a table, check whether anyone still
uses it. Two objections killed that product.

The first was that the "measure usage" half is, at its core, a read-out script for a feature
DataHub already ships. A company that has configured DataHub properly can look the same thing up
in the UI.

The second objection was the one that mattered. Our own code could not tell **"we measured
nothing"** from **"nothing was used"**. Both cases returned an empty list, and the resulting
category counted as *harmless*. On a catalog with thin or absent usage coverage, our tool would
have quietly waved through the deletion of a table with a live consumer — while sounding
confident. A comment in the code claimed the caution the code did not implement.

Fixing that properly meant changing two things at once: the unit of judgement, from the table to
the **edge**; and the question, from "can this go" to "is this edge real, and since when has it
not been".

## What it does

Probate reads the lineage a DataHub catalog **declares**, reads the query usage the catalog
**measured**, and reports the difference **per edge**, with a date attached.

The sentence that separates it from everything else we found:

> Everyone else uses usage data to **weight** edges they already believe.
> This tool uses it to **test the edge itself**.

That is not a slogan, it is the result of a survey of the field. Seven projects were found that
read both sources. All seven attach usage to an edge as a weight, a hint, or an evidence string on
lineage they already accept. None of them ask whether the edge should exist. (These survey counts
are **not** covered by `audit_claims.py` — see limitations.)

**And DataHub's own blog post?** It pairs the two signals already — but it pairs them to judge a
*table*, once, by hand:

> "Lineage shows what's connected to what. Dataset usage and query history shows what's actually
> being read … Together they turn 'might still be used' into a binary."

The delimitation, in the words we want a juror to use:

> Others pair lineage and usage to decide whether a **table** can go — once, by hand.
> We check every **edge**, continuously, and say since when it stopped being covered.

### Four states, each carrying its evidence

| State | Meaning | Evidence carried with the verdict |
|---|---|---|
| `confirmed` | declared **and** measured | query URN + the time windows it was seen in |
| `dead` | declared, **never** measured inside the window | window length, number of buckets checked |
| `missing` | measured (query co-occurrence), **not** declared | query URN, number of co-occurrences |
| `unknown` | **no data in the window — no statement possible** | why: no usage data / no buckets |

### Why `unknown` is not `dead`

This is the failure the project exists to correct, and it was our own failure first. The
predecessor version collapsed "we measured nothing" and "nothing happened" into the same empty
list and treated the result as harmless — which is exactly how a confident tool overwrites a live
consumer on a catalog with thin coverage.

The distinction is present in the data and is now made explicitly: **no time windows at all**
means we cannot see; **time windows that exist and read zero** means we looked and nothing
happened. Before anything is classified, Probate runs a coverage check — how many usage windows
exist, how far back they reach — and reports thin coverage as a result rather than selling it as
a measurement.

A tool whose whole claim is "assert nothing without evidence" does not get to guess here.

### A dated finding, not a snapshot

Usage arrives in time buckets with timestamps. The predecessor threw the time dimension away.
Keeping it costs almost nothing and changes what the output *is*: last covered (a date), dead
since (days, with an explicit `at_least` lower bound when the whole window is empty), and the
series per bucket. "This edge was covered on this date" is a statement you can still defend six
months later. An undated one is a snapshot.

### Where is the agent

Exactly one place, deliberately: **the model judges which deviation matters.**

A dead edge into a table whose description mentions the annual close is not the same as a dead
edge into a nameless intermediate table. That is judgement over unstructured text — description,
owners, glossary terms, domain — not a rule anyone can write. Everything else in the pipeline is
deterministic and testable offline.

The model works under a **citation duty**: no verbatim quote from the text it was given, no
judgement, and the deterministic finding stands unchanged. The fallback is the normal case, not an
error case. The model can only *weight* (`important`, `reason`); it structurally cannot change the
verdict, because the `Judgement` type carries no `state` field at all.

Measured against the seeded four-state lab
([`harness/runs/judge-seedlab-matrix.json`](../harness/runs/judge-seedlab-matrix.json) — the file
is audited for `any_edge_judged_with_model: true`; the per-edge breakdown below is read from the
same artifact but is not itself a `claims.json` key):

| Focus | State | Model judgement | Citation |
|---|---|---|---|
| confirmed | `confirmed` | not offered to the model | excluded by design — a confirmed edge needs no judgement |
| dead | `dead` | fell back to the deterministic finding | `fallback_reason: "kein Zitat geliefert"` (no quote supplied) |
| missing | `missing` | yes | quoted the downstream `description` |
| unknown | `unknown` | yes | quoted the upstream `description` |

So the citation duty bites: on one of the three edges offered, the model produced no usable quote
and was overruled by its own rule. We consider that the feature working, and we report it rather
than tuning the fixture until the number looks better.

### Acting on it

Reporting is one mode; correcting is the other. Probate can enter a missing edge, mark a dead one
with the date it was last covered, remove a declared edge, and enrich documentation from observed
usage. Every one of those is **proposal → human confirmation → journal entry → reverse gear**.
`probate propose` writes nothing to the catalog at all. `probate correct` is dry-run by default —
a bare invocation cannot write. `probate revert` undoes every journalled write of the session,
including deleting aspects that did not exist before rather than writing back an invented `None`.

### The workbench

A dashboard that only shows numbers proves nothing — you cannot tell whether it computed them or
someone typed them in. A juror of an earlier round put it exactly: *"I can't experience it myself,
I can only believe it."* For a tool whose core claim is "assert nothing without evidence", a demo
you have to believe is a self-contradiction.

So the UI is a lab, not a report: four panes (declared / measured / edge ledger / live log) and six
buttons that change the two truth sources for real, through the same journalled write path as the
CLI. Opened without the proxy, it falls back to a recorded run and labels itself *Recording — no
live instance* instead of disguising itself as a live session.

## How we built it

Python 3.11 throughout, pinned via `uv` (a bare `python` on the build machine resolves to a broken
3.9 alias, and DataHub needs 3.10+). Every module has one job and one way out:

- `probate/ledger.py` — the edge ledger: four states, coverage check before classification, timeline.
- `probate/judge.py` — the only model call in the project. Injectable transport (`str -> str`), so
  the whole module is testable offline; hard timeout; every failure path funnels into the same
  fallback shape with a named `fallback_reason`.
- `probate/correct.py` — proposals with evidence; never applied without confirmation; never writes
  on an `unknown` edge at all.
- `probate/gms.py` — the only way out; locks two silent failure classes of DataHub's APIs.
- `probate/writeback.py` — the only write path; dry-run by default, every write journalled.
- `probate_action/watcher.py` — relapse detection over the aspect, not the actor, on real Kafka.
- `harness/audit_claims.py` — re-derives every number in the prose from the run artifacts; exit 1
  on drift.

**One transport, and we say why it is not the MCP server.** The design called for two: raw GraphQL
for dead edges, the DataHub MCP server's `get_dataset_queries` for co-occurrence. The shipped code
has one. `grep -rn -i mcp probate/*.py` returns nothing; co-occurrence is fetched with the same raw
`searchAcrossEntities` path as everything else (`probate/ledger.py`, `probate/targets.py`).

The MCP server was evaluated and dropped on three measured grounds: it has **no time windows** (the
timestamp fields in `gql/queries.gql` are commented out, so a dead-edge window cannot be
expressed), it registers **zero mutation tools** at the pinned version 0.4.0, so nothing could be
written back through it, and it costs **~54 s of telemetry per tool call**, which over a load run
is the difference between a night and a week.

So: **this submission does not use the Agent Context Kit.** We are saying it plainly, in the README
and here, because it is a real gap against what a reviewer may expect, and because "we could
integrate it" would be a promise rather than a result.

**Load behaviour was designed two-stage before it was measured**, and then measured: a coarse pass
over the aggregates (one API call per table, independent of query volume), then a detail pass only
into the edges that look suspicious.

**Everything runs against one instance, `http://localhost:28080`, and nothing else.** Two other
ports on the same machine are explicitly banned in the project rules, one of them because a
sibling project published measured numbers against it.

## Challenges we ran into

These are the real ones, from the last two build nights. We are not sanitising them, because they
are the strongest available evidence that the review discipline is not decorative.

**1. Our own write path deleted column-level lineage — the exact failure we accuse DataHub of.**
`merge_upstreams` read the existing `upstreamLineage` aspect, merged the `upstreams[]` list and
wrote the aspect back. It did not carry `fineGrainedLineages` — the column-level lineage that dbt
and BigQuery ingestion produce. Writing the aspect back therefore destroyed it. That is precisely
the mechanism we document about `sql_parsing_aggregator.py`: rebuild the aspect, lose what you did
not model. Found in review on 2026-08-07, fixed in commit `0f07cea`, and it is now a claim rather
than a promise: `cll_survived_the_merge: true`.

**2. A `mark_dead` that stamped the run date instead of the measured date.** The dead marker
`probate.dead_since` was being written with the moment of writing. A record that dates itself by
when someone typed it is not a record — the whole point of the timeline is that the date comes
from the measurement (`last_covered_ms`, from the same measurement as `dead_since_days`). Fixed in
the same commit. And where no measurement date exists at all — the entire checked window empty —
the tool now **abstains** with a machine-readable reason instead of inventing a date.

**3. A citation duty satisfiable with a one-character quote.** `judge.py` required a verbatim
quote from the context it had been given. A quote of `"e"` passed. The rule existed, was tested,
and was worthless. The fix is a minimum length — `_QUOTE_MIN_CHARS = 12` **and**
`_QUOTE_MIN_TOKENS = 3`, ANDed rather than ORed, applied to the whitespace-normalised quote so the
character bound cannot be gamed with interspersed spaces. The same review round found four more
holes in the same rule: a quote spliced across field or record boundaries validated (the context
was joined with `\n` and normalised *after*, so it now matches per field segment, upstream and
downstream separately); `bool(parsed.get("important"))` let the string `"false"` through as `True`;
`source_field` was taken from the model unchecked and is now derived from the segment that actually
matched; and prompt-building errors were being reported as transport failures, hiding a bug in our
own code behind a plausible external one.

**4. Index drift made a `missing` edge read as `confirmed`.** At 04:30 on 2026-08-07 the claims
audit exited 1, and the cause was not a reporting error — it was a wrong verdict. Primary store: 0
declared edges on the `missing_downstream` dataset, which is correct. Graph index: 1 edge.
`fetch_declared_edges` asks the downstream direction, and that direction can only be answered by
the index, so the drift went straight into the classification. `POST
/operations?action=restoreIndices` on that single URN resynced 8 rows and the verdict was correct
again. The dangerous part came next: a report described this as "the read path lagged and healed
itself". It did not heal itself — the timing matches the manual repair exactly. The corrected
finding is that index drift **can persist until `restoreIndices` runs**, and the detection is now
built into `check_es_drift()`, which compares primary store against index for all eight lab
datasets and says so loudly rather than silently.

**Smaller ones, in one line each.** `claude -p` loads the repository's own `CLAUDE.md` and answers
as a coding agent (54.9 s, Markdown-wrapped, unparseable) unless given a strict `--system-prompt`
(20–27 s, clean JSON). `get_aspect` is blind to timeseries data, so bucket verification has to go
through `getTimeseriesAspectValues` — which returns HTTP 500 with a `NullPointerException` if you
omit the mandatory `limit` field. `gms.delete_aspect` on a timeseries aspect deletes only the most
recent value, not the history. And the GraphQL `usageStats` aggregation lagged the primary store by
more than 75 s, which is why the ledger reads usage from the raw store instead.

## Accomplishments we are proud of

Not features — results, each with the artifact it came from.

**Four states, end to end.** All four states matched the manifest's expectation
(`all_four_states_matched_expected: true`, `seedlab-verdicts.json`), and at least one edge was
judged by the model with a citation (`any_edge_judged_with_model: true`).

**Write, verify, undo.** The pre-existing edge survived the merge, the new edge was present after
the write, column-level lineage survived the merge, custom properties survived the write-back,
`revert_count: 2` writes were reverted, and the revert restored the aspect exactly — all six as
audited booleans and counts from `correct-roundtrip.json` and `upstream-properties-probe.json`.

**The coarse pass scales linearly with catalog size — measured, and this half is solid.** From S to
M the catalog grows ten-fold, 50 → 500 tables, and the coarse pass grows with it: 1.235 s →
12.238 s. That is 0.0247 s versus 0.0245 s per dataset, one API call per table either way, and an
identical 93 characters of response per call across S, M and an independent smoke run. Peak memory
in the coarse pass: 0.38 MB at S, 3.58 MB at M. Query volume grew ten-fold in the same step
(1,000 → 10,000) and the coarse pass did not notice, which is the property it was built for.

**The two-stage cost saving, however, is *not* demonstrated by this test, and we are correcting
that claim rather than shipping it.** The detail pass looks flat between the runs — 35.614 s →
47.217 s over 41 edges in both — but the 41 is not a finding. It is a hardcoded sample cap
(`detail_sample: int = 41`, `harness/loadtest.py`, applied as `suspicious[:detail_sample]`),
carried over from the design document's assumption of 41 suspicious edges out of 384. The
underlying flag rate is now measured rather than inferred, and it is **100 % at both scales: 50 of
50 tables at S, 500 of 500 at M**, matched by an independent probe run. The cause is structural,
not a fluke: `coarse_pass()` flags a dataset whenever `statsSummary.queryCountLast30Days` is falsy,
and our fixtures are upserted straight through GMS — they never pass DataHub's usage-aggregation
pipeline, so `statsSummary` never populates. On synthetic data the coarse triage does not triage;
it marks everything.

So the architecture may well do what it was designed to do. **This test cannot show it**, and a
flat number produced by a constant is not evidence. Demonstrating the saving needs usage data that
DataHub itself aggregated, which this measurement never had.

**One result we cannot explain, kept as such.** Per-edge time in the detail pass rose **32.6 %**
from S to M — 0.8686 s → 1.1516 s — on an *identical* 41-edge sample. We record it as an
unexplained finding rather than calling it comparable. A plausible factor is that
`fetch_cooccurrence` queries the instance's entire query corpus, ten times larger at M; no
controlled counter-test isolated that from general instance load during the measurement, so it
stays a correlation and is written down as one.

| Stage | Tables | Queries | Seed | Coarse | Coarse API calls | Coarse suspicious | Detail edges | Detail total | Per edge | Detail peak mem |
|---|---|---|---|---|---|---|---|---|---|---|
| S | 50 | 1,000 | 11.84 s | 1.235 s | 50 | 50/50 (100 %) | 41 (capped) | 35.614 s | 0.8686 s | 1.7 MB |
| M | 500 | 10,000 | 198.52 s | 12.238 s | 500 | 500/500 (100 %) | 41 (capped) | 47.217 s | 1.1516 s | 1.71 MB |
| L | 5,000 | 100,000 planned, 5,600 written | aborted at 735 s | not run | — | — | — | not run | — | — |

**Stage L did not finish, and we publish it as a failure rather than dropping the row.** Datasets
and lineage edges were fully written (5,000 and 5,000, verified by binary search against
`get_aspect`, deliberately not against `search`, whose index lags). Only 5,600 of 100,000 planned
queries had landed when the run was stopped at 735 s. Coarse and detail never ran because there was
nothing finished to hand them. The artifact also carries a projected full-seed duration — a
**linear extrapolation** of this run's own observed rate (9.42 s per batch), not a second
measurement, and it is stored as a nested field precisely so `audit_claims.py` cannot mistake it
for one.

**The watcher ran live against a real Kafka broker**: 80 events received, 1 relapse detected and
correctly refused as a dry run, 0 edges reclassified. That last zero is honest and it is the
weakest measured result in this repository — see the limitations.

**The retirement flow ran live**: 1 live consumer measured, parity proven, 1 consumer sign-off
collected, and a second table whose row count deviated beyond tolerance was **not** switched over.
Refusal is a result.

**Cleanup is reported as it happened, not as we would like it.** Stage S cleaned up and verified in
one pass, 0 leftover. Stage M did **not**: one `delete_aspect` call hit a transient HTTP 500 on an
aspect that stage M never creates in the first place. The read-back still counted 0 leftover — but
`cleanup_verified` is recorded as `false`, because an HTTP 500 is a failure of the call, not
evidence about the data. A retry verified clean, and an independent full read-back over all 500
datasets and 10,000 queries confirmed 0 remaining. The first attempt stays on the record.

Two commands reproduce all of this without a DataHub instance and without network access: the test
suite runs green in roughly fifteen seconds, and `harness/audit_claims.py` exits 0 with every
number in this text agreeing with the runs it came from. We deliberately do not quote a test count
here — it changes with every commit, and a number in prose that nothing checks is exactly what this
project is against.

## What we learned

**A rule you cannot fail is not a rule.** The citation duty was in the spec, in the code and in the
tests, and `"e"` satisfied it. We now assume that any constraint we have not actively tried to
break is decorative.

**A quotation from our own disclaimer is not evidence.** The seeded datasets originally carried a
"this data is seeded" note in their descriptions. The model could quote that note and satisfy the
citation duty with it — a quote from the label that marks data as fake proves nothing about the
data. The note was removed from the citable corpus and the matrix re-measured, which is also why
one edge now falls back rather than being judged. The number got worse and the result got true.

**A failed query is not an absence.** Three of our four hardest bugs looked like "there is nothing
there" and were in fact "we could not look": an index that disagreed with the primary store, an
aggregation lagging 75 s behind, a timeseries read that returns HTTP 500 without its mandatory
field. Each one, read carelessly, produces a confident wrong answer. That is the same failure class
the product is about, which is uncomfortable and instructive.

**One observation is not a law.** The index-drift incident nearly entered our own documentation as
"the read path heals itself if you wait" — a plausible, evidence-backed, wrong generalisation from
a single run, and one that would have cost the next person an hour of waiting for something that
never happens without `restoreIndices`.

**Publishing a number you dislike is cheaper than defending one you like.** `watcher_reclassified_
edges: 0` and `loadtest_m_cleanup_verified: false` are both in the audited set. Writing the
limitation was faster than making the number go away, and it is the only version of the claim we
can actually defend.

## What's next

- **The MCP server, if and only if the three blockers move.** Wiring `get_dataset_queries` is not
  waiting on our effort — it is waiting on time-window support, mutation tools at a pinned version,
  and a telemetry cost per call that a load run can absorb. Until then, integrating it would make
  the tool slower and less capable, which is why it is a *next* item with conditions attached
  rather than a to-do.
- **A real warehouse connection.** The entire measurement chain has only ever run against a local
  instance and data we seeded ourselves.
- **Full run vs. daily delta.** The spec asks how much cheaper an incremental run is than a full
  reconciliation; that comparison is designed but **not measured**, and it is the number that
  decides whether this is usable in a real company.
- **Stage L to completion**, so the extrapolation can be replaced by a measurement.
- **Two upstream contributions**, both side findings we did not build on:
  `DatasetPatchBuilder.remove_upstream_lineage()` exists with zero callers, not even a test; and
  "which person reads which column" is not expressible in the model at all — user counts and column
  counts live in separate lists with no link between them.

## Built with

Python 3.11 (pinned through `uv`) · DataHub OSS quickstart stack, GMS over REST/OpenAPI v3 and
GraphQL · `acryl-datahub` · `acryl-datahub-actions` for the continuous watcher · Apache Kafka ·
Claude, invoked through the `claude -p` CLI as an injected transport behind a `str -> str`
interface · plain HTML/CSS/JavaScript for the workbench, no framework · `pytest` · Apache 2.0.

## Pre-existing code — disclosure

The rules require pre-existing work to be **disclosed**, not approved. So, stated plainly:

- **All code in this repository was written during the competition period.** First commit
  `3c38ab7`, 2026-08-04; work continued through 2026-08-07.
- **Third-party dependencies** are used as libraries, unmodified: `acryl-datahub`,
  `acryl-datahub-actions`, `pytest`, and the DataHub OSS stack itself. Frameworks and libraries are
  explicitly permitted.
- **AI assistance was used throughout**, which the rules permit explicitly. Commits carry a
  `Co-Authored-By` trailer naming the model.
- **A sibling project by the same author, `datahub-attest`, exists** (first commit 2026-08-03) and
  is a separate submission. No file was copied between the two. The *idea* of an
  `audit_claims.py`-style harness that re-derives prose numbers from run artifacts appeared there
  first; the implementations are independent — 17 lines are common between the two files, out of
  298 and 217 respectively, and those are imports and boilerplate. The design notes reference that
  project when explaining why one local DataHub port is off-limits.
- **DataHub source code was read, not copied.** Findings cite file and line in a partial clone of
  `datahub-project/datahub` at master `26a9f6c`.

## Honest limitations

All of them. If a section like this is missing from a submission that claims "no assertion without
evidence", the submission has already contradicted itself.

**About the survey behind the "nobody else does this" claim.** These counts come from a competitive
survey documented in the design spec, not from a run artifact. They are **not** covered by
`audit_claims.py` and they are the softest figures in this document. The Devpost gallery is
unpublished (2,708 participants), so GitHub is only a proxy and private or unlinked repositories
are invisible to us. Roughly 44 repositories were requested and never returned — they are **unread,
not cleared** (the three most alarming names were fetched individually and are cleared). GitHub's
repository search does not index READMEs, so our count is a **lower bound**, not a census. And
"Metadata Tests" in DataHub Cloud is closed source: what is documented is that usage is already a
predicate there, so "Cloud cannot do this" is **unprovable**, and we carry it as a risk, not an
all-clear.

**About the measurements:**

- **Usage data is seeded.** DataHub's sample catalog ships none — live check: `totalSqlQueries:
  null`, `buckets: []`. Every number above was measured against data we wrote ourselves, and every
  artifact says so.
- **No real warehouse connection has ever been tested.**
- **The MCP server is not used.** See "How we built it".
- **Row counts at retirement are typed in by a human.** Deliberate — an invented count would be
  worse — but the single most consequential number in the retirement flow is typed, not measured.
- **Co-occurrence is undirected.** `QuerySubject` has no direction field, so a `missing` edge
  records its direction as **inferred**, not measured.
- **The load test does not demonstrate the two-stage cost saving it was designed to measure.** Both
  runs flag 100 % of datasets as suspicious, because our fixtures never populate `statsSummary`.
  Demonstrated: the coarse pass scales linearly with catalog size, and the detail pass takes
  comparable time for a fixed-size sample. Not demonstrated: that suspicious-edge counts stay flat
  as a real catalog grows.
- **The detail pass got 32.6 % slower per edge from S to M on an identical sample**, and we cannot
  say why. Named plausible factor, no counter-test, therefore a correlation.
- **Load stage L never reached the coarse or detail pass**, and the full-seed duration in its
  artifact is an extrapolation from that run's own batch rate.
- **Our own cleanup helper has a scaling defect.** `loadgen.cleanup()` always walks the full
  *planned* set for a scale, not what was actually written — at stage L that is roughly 230,000
  HTTP calls to clean up a run that had written 5,600 queries. It finished, but the cost scales
  with what was planned. That is a defect in our harness, not in Probate, and it is ours to fix.
- **The watcher's re-evaluation could not be shown changing a verdict.** The pipeline demonstrably
  receives real Kafka events and detects a relapse. But running the ledger before and after a
  freshly emitted usage aspect returned byte-identical timeline and coverage blocks, twice,
  including after a wait. The write itself is proven; the GraphQL aggregation did not show it, and
  the stack used here has no separate usage-statistics indexer container. We record this as "the
  aggregation layer lags or does not run in this environment" and explicitly **not** as "the watcher
  reclassifies edges", which we did not observe.
- **All containers of this quickstart stack report `unhealthy`** in `docker ps`, while GMS answers
  HTTP 200 on the same stack and the four-state check runs to completion. We state the flag and the
  working behaviour side by side. We do not claim the flag is harmless, and we do not claim it
  explains the aggregation lag above.
- **Index drift can silently change a verdict**, as it did on 2026-08-07. Detection is built in;
  the repair (`restoreIndices`) is manual.
- **The workbench's time offset lives in a module variable**, shared between concurrent viewers.
  Correct for a demo with one operator, wrong for anything else, and it says so in the code.
