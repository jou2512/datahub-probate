# `usageStats.aggregations.uniqueUserCount` reports 0 while buckets in the same response report 3, 4 and 5

**Type:** Bug — incorrect data returned
**Component:** `datahub-graphql-core` / `metadata-io` — usage aggregation
(`Dataset.usageStats.aggregations`, `Dataset.statsSummary`)
**Severity:** This one returns a wrong number rather than an error, and the wrong number is
surfaced in the UI. It is the only finding in this set that a user can act on without
noticing.

## What I did

Wrote `datasetUsageStatistics` rows using the documented Python SDK class, setting the
`uniqueUserCount` field that class exposes:

```python
DatasetUsageStatisticsClass(
    timestampMillis=ts,
    eventGranularity=TimeWindowSizeClass(unit="DAY", multiple=1),
    uniqueUserCount=5,
    totalSqlQueries=40,
)
```

Then read the dataset back through GraphQL, asking for both the per-bucket metrics and the
aggregate in a single query.

## What I expected

`aggregations.uniqueUserCount` to be *some* defensible summary of the per-bucket values — the
max, the last, or the count of distinct users if that can be computed. Failing that, `null`,
meaning "cannot be computed from what was written".

What I did not expect was a confident `0` sitting next to non-zero per-day values in the same
response.

## What happened

One response, contradicting itself:

```graphql
{
  dataset(urn: "…confirmed_upstream…") {
    usageStats(range: ALL) {
      buckets      { bucket metrics { totalSqlQueries uniqueUserCount } }
      aggregations { totalSqlQueries uniqueUserCount users { user { urn } count } }
    }
    statsSummary { queryCountLast30Days uniqueUserCountLast30Days }
  }
}
```

```
buckets[].metrics.uniqueUserCount     →  [3, 4, 5]
aggregations.uniqueUserCount          →  0        ← contradicts the line above
aggregations.users                    →  []
aggregations.totalSqlQueries          →  103      ← correct: 28 + 35 + 40
statsSummary.queryCountLast30Days     →  103      ← correct
statsSummary.uniqueUserCountLast30Days→  0        ← same wrong 0, and this one is on the UI
```

Reproduced on two independent datasets in the same instance (re-measured 2026-08-10; the
`confirmed_upstream`/`dead_upstream` fixtures of 2026-08-07 had lost their rows by then, so
these are the datasets that still carry history):

| Dataset | per-bucket `uniqueUserCount` | `aggregations.uniqueUserCount` | `aggregations.totalSqlQueries` |
|---|---|---|---|
| 8 rows, gappy | 4, 3, 0, 0, 0, 0, 0, 0 | **0** | 52 ✓ |
| 3 rows, consecutive | 1, 1, 1 | **0** | 103 ✓ |

The stored rows really do carry the field — this is the raw aspect straight out of
`getTimeseriesAspectValues`, no GraphQL involved:

```json
{"timestampMillis":1786060800000,"totalSqlQueries":40,
 "eventGranularity":{"unit":"DAY","multiple":1},
 "partitionSpec":{"partition":"FULL_TABLE_SNAPSHOT","type":"FULL_TABLE"},
 "uniqueUserCount":5}
```

So `totalSqlQueries` is aggregated from the scalar field and comes out right, while
`uniqueUserCount` — the scalar field sitting directly next to it in the same aspect — comes out
as 0. That asymmetry is the core of the report.

### Likely cause

`aggregations.users` is `[]`, which suggests the aggregate is derived from the optional
`userCounts` array rather than from the `uniqueUserCount` scalar. Our rows do not carry
`userCounts` — the SDK class does not require it, and nothing in the docs says the scalar is
inert without it.

If that is the design, the bug is narrower but still real: when `userCounts` is absent, the
correct answer is `null` ("not computable"), not `0` ("measured, and it was none"). Emitting 0
turns a missing input into a positive assertion, and this project exists precisely to argue
that those two must never be conflated.

## Why it matters

- `uniqueUserCountLast30Days` is displayed in the DataHub UI. A dataset used by five people
  every day shows as having no users.
- Any consumer treating "0 unique users over 30 days" as a signal — deprecation candidates,
  access review, cost attribution — gets a false positive on every dataset ingested this way.
- It fails silently. There is no error, no null, no warning, and the per-bucket data looks
  fine, so the contradiction is only visible if you request both in one query.

## Environment

- DataHub **v1.5.0.6** (`acryldata/datahub`, commit `d0fce948555c06b3083479d40e8fa270d156c71f`)
- `datahub docker quickstart`, `serverType: quickstart`
- GMS at `http://localhost:28080`, no auth (local quickstart)
- Writer: `acryl-datahub` 1.6.0.17, `DatahubRestEmitter` + `DatasetUsageStatisticsClass`
- Measured 2026-08-07

## Reproduction

Any dataset whose `datasetUsageStatistics` rows set `uniqueUserCount` and omit `userCounts`.

```bash
URN='urn:li:dataset:(urn:li:dataPlatform:postgres,mydb.mytable,PROD)'
curl -s -X POST http://localhost:8080/api/graphql \
  -H 'Content-Type: application/json' \
  -d "{\"query\":\"{ dataset(urn: \\\"$URN\\\") { usageStats(range: ALL) { buckets { metrics { uniqueUserCount } } aggregations { uniqueUserCount totalSqlQueries users { user { urn } count } } } statsSummary { uniqueUserCountLast30Days queryCountLast30Days } } }\"}"
```

From scratch, including writing the rows:

```bash
uv run --python 3.11 python harness/upstream_repro.py
```

Read-only, against datasets that already exist:

```bash
uv run --python 3.11 python harness/upstream_repro.py --no-seed \
    --sparse-urn "$URN" --dense-urn "$OTHER_URN" --empty-urn "$EMPTY_URN"
```

→ probe `03-usagestats-uniqueusercount-aggregation-is-always-zero` in
`harness/runs/upstream-repro.json`. It records, per dataset, the per-bucket values, the
aggregate, the `users` array, the sibling `totalSqlQueries` aggregate, and whether the stored
rows carry a `userCounts` array. The probe only passes if *every* dataset probed shows the
contradiction, so a single lucky dataset cannot produce a false positive.

## Suggested fix

In order of preference:

1. **Aggregate the scalar when `userCounts` is absent.** `max(uniqueUserCount)` over the
   window is a defensible lower bound and matches what the field means per bucket.
2. **Return `null` instead of `0`** when the aggregate cannot be computed, in both
   `aggregations.uniqueUserCount` and `statsSummary.uniqueUserCountLast30Days`. This is the
   minimal honest fix and probably the smallest patch.
3. If neither is acceptable, **document that `uniqueUserCount` is inert without `userCounts`**
   and say so in the `DatasetUsageStatistics` aspect docs and in the SDK docstring, so writers
   know the field they are setting will not survive aggregation. Proposed wording in
   `docs-patch.md`.

Option 2 alone would already have saved us the debugging time, because a `null` would have
sent us looking at our own writes instead of trusting the number.

## Willing to contribute

Yes. If you tell us which of the three you want, we will open a PR with a test that asserts the
aggregate and the buckets cannot disagree.
