<!-- repo: datahub-project/datahub | title: `usageStats.aggregations.uniqueUserCount` is always 0 while buckets in the same response report 4 and 3 -->

### Describe the bug

`Dataset.usageStats.aggregations.uniqueUserCount` returns `0` for datasets whose per-day
buckets — in the *same* response — report non-zero unique users. The sibling scalar
`totalSqlQueries`, stored in the same aspect and read in the same query, aggregates correctly.

The same `0` is repeated in `statsSummary.uniqueUserCountLast30Days`, which is displayed in the
DataHub UI. This is the only finding in this set that returns a wrong *number* rather than an
error, so it fails silently.

One response contradicting itself (dataset with 8 `datasetUsageStatistics` rows):

```
buckets[].metrics.uniqueUserCount      →  [4, 3, 0, 0, 0, 0, 0, 0]
aggregations.uniqueUserCount           →  0        ← contradicts the line above
aggregations.users                     →  []
aggregations.totalSqlQueries           →  52       ← correct, matches the store exactly
statsSummary.uniqueUserCountLast30Days →  0        ← same wrong 0, and this one is on the UI
```

Second dataset, 3 consecutive days, same instance, same instant:

| Dataset | per-bucket `uniqueUserCount` | `aggregations.uniqueUserCount` | `aggregations.totalSqlQueries` | store total |
|---|---|---|---|---|
| A (8 rows, gappy) | 4, 3, 0, 0, 0, 0, 0, 0 | **0** | 52 | 52 ✓ |
| B (3 rows, dense) | 1, 1, 1 | **0** | 103 | 103 ✓ |

The rows really do carry the field. Straight out of
`POST /aspects?action=getTimeseriesAspectValues`, no GraphQL involved:

```json
{"timestampMillis":1786320000000,"totalSqlQueries":30,
 "eventGranularity":{"unit":"DAY","multiple":1},
 "partitionSpec":{"partition":"FULL_TABLE_SNAPSHOT","type":"FULL_TABLE"},
 "uniqueUserCount":4}
```

### To Reproduce

Any dataset whose `datasetUsageStatistics` rows set `uniqueUserCount` and omit the optional
`userCounts` array. Rows were written with the documented SDK class:

```python
DatasetUsageStatisticsClass(
    timestampMillis=ts,
    eventGranularity=TimeWindowSizeClass(unit="DAY", multiple=1),
    uniqueUserCount=4,
    totalSqlQueries=30,
)
```

Read back — buckets and aggregate in one query, so the contradiction is in a single response:

```bash
GMS=${GMS:-http://localhost:8080}
URN='urn:li:dataset:(urn:li:dataPlatform:postgres,mydb.mytable,PROD)'

curl -s -X POST "$GMS/api/graphql" -H 'Content-Type: application/json' -d "{\"query\":\"{
  dataset(urn: \\\"$URN\\\") {
    usageStats(range: ALL) {
      buckets { metrics { uniqueUserCount } }
      aggregations { uniqueUserCount totalSqlQueries users { user { urn } count } }
    }
    statsSummary { uniqueUserCountLast30Days queryCountLast30Days }
  } }\"}"
```

### Expected behavior

Some defensible summary of the per-bucket values — max, last, or a true distinct count if it
can be computed. Failing that, `null`, meaning "cannot be computed from what was written".

A confident `0` next to non-zero per-day values in the same response is the one answer that
cannot be right.

### Likely cause

`aggregations.users` is `[]`, which suggests the aggregate is derived from the optional
`userCounts` array rather than from the `uniqueUserCount` scalar. The rows here do not carry
`userCounts` — the SDK class does not require it, and nothing in the docs says the scalar is
inert without it.

If that is the design, the bug is narrower but still real: when `userCounts` is absent the
correct answer is `null` ("not computable"), not `0` ("measured, and it was none").

### Why it matters

- `uniqueUserCountLast30Days` is on the dataset page. A table used by four people shows as
  having no users.
- Any consumer treating "0 unique users over 30 days" as a signal — deprecation candidates,
  access review, cost attribution — gets a false positive on every dataset ingested this way.
- There is no error, no null and no warning, and the per-bucket data looks fine, so the
  contradiction is only visible if you request both in one query.

### Suggested fix

In order of preference:

1. **Aggregate the scalar when `userCounts` is absent.** `max(uniqueUserCount)` over the window
   is a defensible lower bound and matches what the field means per bucket.
2. **Return `null` instead of `0`** when the aggregate cannot be computed, in both
   `aggregations.uniqueUserCount` and `statsSummary.uniqueUserCountLast30Days`. Probably the
   smallest patch, and it would already have saved the debugging time — a null sends you
   looking at your own writes instead of trusting the number.
3. If neither is acceptable, **document that `uniqueUserCount` is inert without `userCounts`**,
   in the `DatasetUsageStatistics` aspect docs and in the SDK docstring, so writers know the
   field they are setting will not survive aggregation.

I do not want to guess which of the three you want — all are defensible. Say which and I will
open the PR with a test asserting that the aggregate and the buckets cannot disagree.

### Additional context

**Environment** — DataHub **v1.5.0.6** (`acryldata/datahub`, commit `d0fce948555c06b3083479d40e8fa270d156c71f`),
`datahub docker quickstart`, `serverType: quickstart`, no auth. Writer: `acryl-datahub` 1.6.0.17,
`DatahubRestEmitter` + `DatasetUsageStatisticsClass`, Python 3.11.9. Measured **2026-08-10**
(first observed 2026-08-07, re-verified today on both datasets above).
