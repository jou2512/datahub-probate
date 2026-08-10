# Upstream contribution package — DataHub

**Nothing in this folder has been filed. No issue is open, no pull request exists, nothing
has been posted anywhere.** These are drafts, ready for a human to submit. Filing them is a
deliberate act by the author, not a side effect of generating them.

## What this is

While building [datahub-probate](../../README.md) — a tool that checks declared lineage
against measured usage — we hit a series of DataHub behaviours that are either undocumented
or documented incorrectly. Each cost real debugging time. Rather than keeping the workarounds
in our own code, we wrote them up so the next person does not have to rediscover them.

Every finding here is **measured against a live instance and re-verified before publication**,
not recalled from notes. Several claims we started with did **not** survive that re-check and
were dropped or rewritten — see [Rejected claims](#rejected-claims) below. A wrong report
upstream is worse than no report, and the point of this project is that a claim without
evidence is not a claim.

## Environment for every measurement here

| | |
|---|---|
| DataHub | **v1.5.0.6** (`acryldata/datahub`, commit `d0fce948555c06b3083479d40e8fa270d156c71f`) |
| Deployment | `datahub docker quickstart`, `serverType: quickstart`, `serverEnv: core` |
| GMS | `http://localhost:28080` |
| Client | Python 3.11.9, `acryl-datahub` 1.6.0.17, plus raw HTTP via `curl`/`urllib` |
| Auth | none (local quickstart, no access control) |
| Measured | 2026-08-07, **re-verified 2026-08-10** — all six probes `OK`, exit 0 |

> **Re-verification note (2026-08-10).** The fixtures of 2026-08-07
> (`probate_seedlab.confirmed_upstream`, `…dead_upstream`) had lost their timeseries rows by
> then, so the first re-run reported findings 03–05 as *not reproduced*. That was an absent
> dataset, not a refuted claim: pointed at datasets that still carry history
> (`probate_seedlab.store_revenue_weekly_east`, 8 rows / 125-day span, and
> `probate_upstream.dense_control`, 3 consecutive days), all six reproduce unchanged. The
> numbers in the submission-ready bodies under [`einreichung/`](einreichung/) are today's, not
> Thursday's.

## Ready to file

[`einreichung/`](einreichung/) holds one submission-ready body per finding plus
[`einreichung/ABSCHICKEN.md`](einreichung/ABSCHICKEN.md) with the exact `gh` commands, in order.
**Finding 02 is not filed as its own issue** — it was reported independently on 2026-08-09 as
[datahub-project/datahub#19016](https://github.com/datahub-project/datahub/issues/19016), so our
version became a comment adding the root cause (`AspectResource`, `response.setLimit(limit)`
unboxing a null while the neighbouring `startTimeMillis`/`endTimeMillis` are null-guarded).

## The findings

| # | File | Kind | One line |
|---|---|---|---|
| 01 | [`01-usagestats-range-argument-required-but-nullable.md`](01-usagestats-range-argument-required-but-nullable.md) | Bug | Every argument of `Dataset.usageStats` is nullable in the schema, but omitting `range` returns HTTP 500 `"Name is null"` |
| 02 | [`02-gettimeseriesaspectvalues-limit-null-pointer.md`](02-gettimeseriesaspectvalues-limit-null-pointer.md) | Bug | `getTimeseriesAspectValues` without `limit` returns HTTP 500 `NullPointerException` |
| 03 | [`03-usagestats-uniqueusercount-aggregation-is-always-zero.md`](03-usagestats-uniqueusercount-aggregation-is-always-zero.md) | **Bug (data)** | `aggregations.uniqueUserCount` is `0` while buckets in the *same response* report 3, 4, 5 |
| 04 | [`04-usagestats-buckets-are-a-dense-calendar-grid.md`](04-usagestats-buckets-are-a-dense-calendar-grid.md) | Docs | `usageStats.buckets` is a padded per-day grid (125 buckets for 8 rows), not a list of measurements |
| 05 | [`05-openapi-v3-get-aspect-returns-newest-timeseries-row-only.md`](05-openapi-v3-get-aspect-returns-newest-timeseries-row-only.md) | Docs | `GET /openapi/v3/entity/.../<timeseries aspect>` silently returns 1 of N rows |
| 06 | [`06-mcp-server-datahub-comments-out-query-timestamps.md`](06-mcp-server-datahub-comments-out-query-timestamps.md) | Bug | **Different repo:** `mcp-server-datahub` 0.6.0 comments out every query timestamp the server happily serves |

Findings 01–05 belong on the main **`datahub`** repository. Finding 06 belongs on
**`acryldata/mcp-server-datahub`** — it is a defect in the client's bundled GraphQL documents,
not in GMS. Do not file them together.

Proposed documentation wording for 04 and 05 (and the schema-description half of 01, 02 and
03) is collected in [`docs-patch.md`](docs-patch.md).

The message to paste when filing is [`cover-note.md`](cover-note.md).

## Reproduction

One script covers all six, and it is the same script that produced the numbers quoted in
each write-up:

```bash
# seeds its own throwaway namespace (probate_upstream.*), measures, deletes it again
uv run --python 3.11 python harness/upstream_repro.py

# read-only: measure against datasets that already exist
uv run --python 3.11 python harness/upstream_repro.py --no-seed \
    --sparse-urn <urn with a gappy usage history> \
    --dense-urn  <urn with consecutive-day usage history> \
    --empty-urn  <urn with no usage history>
```

Exit 0 means every probe that ran reproduced its claim. The machine-readable result lands in
[`harness/runs/upstream-repro.json`](../../harness/runs/upstream-repro.json), and each
findings file names the probe that backs it.

Findings **01–06 need no writes at all** — they reproduce read-only against any dataset that
already has some usage history. That is deliberate: a maintainer can check every one of them
against their own instance without letting our script write anything. Finding 06 additionally
needs the MCP package present:

```bash
uv run --python 3.11 --with mcp-server-datahub==0.6.0 \
    python harness/upstream_repro.py --no-seed \
    --sparse-urn … --dense-urn … --empty-urn …
```

## Rejected claims

These were on our list from earlier sessions. Re-measured on 2026-08-07, they did **not**
hold. They are recorded here rather than deleted, because a corrected claim is worth as much
as a confirmed one, and because our own notes still carried them.

| Claim as we had recorded it | What re-measurement showed |
|---|---|
| `usageStats(range: ALL)` with a non-zero `startTimeMillis` returns wrong or `null` aggregations; omitting it returns the correct sum | **Refuted.** `startTimeMillis` filters correctly and exactly. On a dataset with 8 rows spanning 125 days: `-124d` → 118 buckets / sum 22, `-100d` → 91 / 0, `-30d` → 15 / 0, no filter → 125 / 52. Every one of those matches the rows in the primary store. The real defect nearby is finding 01: omitting `range` is a 500. |
| `get_aspect` (openapi/v3) is blind to timeseries aspects — returns nothing whether or not data exists | **Refuted.** It returns the newest row, correctly, and returns `null` only when there genuinely are no rows. The defect is narrower and is filed as finding 05. |
| The `usageStats` aggregation **zero-fills** the span between its oldest and newest real rows, so interpolated zeros are indistinguishable from measured zeros | **Half right, and the important half is wrong.** The padding is real and large (117 padded buckets around 8 real rows). But padded buckets carry `totalSqlQueries: null`, while a measured zero carries `totalSqlQueries: 0` — so they *are* distinguishable. Downgraded from "data corruption" to a documentation gap, finding 04. |
| `mcp-server-datahub` pinned at 0.4.0 registers **zero** mutation tools; `@latest` resolves to 0.4.0; ~54 s of telemetry per tool call | **Refuted, three times over.** `@latest` resolves to **0.6.0** (with and without a Python pin); 0.6.0 registers 6 tools by default and **18** with `TOOLS_IS_MUTATION_ENABLED=true`; per-call overhead measured at **0.315 s**. Evidence: `harness/runs/mcp-probe.json`. Only the commented-out query timestamps survived re-measurement — that is finding 06. |

Most of those were true when we first measured them and are no longer true — the three MCP
ones went stale inside a single week, because the package moved from 0.4.0 to 0.6.0
underneath us. That is the whole argument for re-verifying before filing: a stale report costs
a maintainer time and costs the reporter credibility. Every findings file in this folder
therefore states the version and the date it was verified on.

## Measured but not filed

Three further behaviours could not be measured on the instance available at the time of
writing, and therefore have **no findings file**. They are named here so nobody mistakes
silence for confirmation.

The blocker is the same for all three: on this instance the timeseries ingestion consumer had
stopped making progress. GMS accepted every timeseries write with HTTP 200 — the
`?async=false` variant even echoed the aspect back — while the row never became readable and
never appeared in the `dataset_datasetusagestatisticsaspect_v1` index. The GMS log showed the
`generic-mce-consumer-job-client` group in a continuous rejoin loop
(`COORDINATOR_NOT_AVAILABLE`, generation 4209). Any probe needing freshly written history had
nothing to measure.

| Behaviour | Status |
|---|---|
| `DELETE /openapi/v3/entity/.../<timeseries aspect>` removes only the newest row, not the history | **Unverified.** Needs a multi-row history to delete from; none could be created. |
| The `usageStats` aggregation trails the primary store after a write | **Unverified.** Needs a write whose propagation can be timed. |
| The graph/search index trails lineage writes and deletes, and `restoreIndices` resyncs it | **Unverified, and partly contradicted.** The write half did diverge (primary store had the edge, `dataset.lineage` did not, for the full 90 s budget). But `POST /operations?action=restoreIndices` answered HTTP 200 and the graph index was *still* wrong 90 s later — so the remedy we had on file did not work under these conditions. Publishing either half would mean publishing an artefact of a broken message bus as a property of DataHub. |

The probes for all three are in `harness/upstream_repro.py` under `unconfirmed-*` names. On a
healthy instance they run automatically; here they report `reproduced: null` with a reason,
which is neither confirmation nor refutation.

## What we changed on our side instead of reporting

Not everything belongs upstream. These are our workarounds, listed so the findings above are
not mistaken for a demand that DataHub change:

- We read usage from `/aspects?action=getTimeseriesAspectValues` rather than from GraphQL
  `usageStats`, because we need the rows that were actually written, not a calendar grid.
- We never treat absence from `searchAcrossEntities` or `dataset.lineage` as absence from the
  catalog; deletions are verified against the primary store.
- We never read `uniqueUserCount` from an aggregate.
- We reach GMS GraphQL directly for query timestamps instead of going through MCP.
