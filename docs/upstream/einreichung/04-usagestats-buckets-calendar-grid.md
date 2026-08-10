<!-- repo: datahub-project/datahub | title: Docs: `usageStats.buckets` is a dense calendar grid, and the null-vs-zero distinction inside it is undocumented -->

### Describe the bug

This is a documentation gap rather than wrong data — nothing in the response is incorrect, but
`buckets.length` means something quite different from what it looks like, and the one field that
separates "never measured" from "measured, and it was zero" is documented nowhere.

`Dataset.usageStats(range: ALL).buckets` returns a **contiguous per-day grid spanning the oldest
to the newest recorded row**, not the list of measurements. On a dataset with 8
`datasetUsageStatistics` rows written across a 125-day span:

```
rows in the timeseries store :   8   (2026-04-08 … 2026-08-10)
buckets from usageStats      : 125   = span in days, inclusive
of which padding             : 117
```

The padding is **not zeros**. Padded buckets carry `null` metrics; days that were measured with
no traffic carry `0`:

```json
// measured, no traffic that day
{"bucket": 1778544000000, "duration": "DAY",
 "metrics": {"totalSqlQueries": 0, "uniqueUserCount": 0, "topSqlQueries": null}}

// never written
{"bucket": 1775692800000, "duration": "DAY",
 "metrics": {"totalSqlQueries": null, "uniqueUserCount": null, "topSqlQueries": null}}
```

Counted over the same 125 buckets: 117 with null metrics (exactly the padding), 6 with
`totalSqlQueries: 0` (exactly the measured zero-traffic rows), 2 with real traffic.
`aggregations.totalSqlQueries` is unaffected — 52, matching the store exactly. The padding adds
shape, never traffic.

**It is a span, not a fixed window.** Two controls on the same instance:

| Dataset | rows | span of rows | buckets returned |
|---|---|---|---|
| gappy history | 8 | 125 days | **125** |
| 3 consecutive days | 3 | 3 days | **3** — not padded |
| no rows at all | 0 | — | **0** — no grid invented |

If the grid were a fixed window, the second dataset would come back padded too. It does not.
The grid is anchored on the oldest and newest real rows.

`startTimeMillis` clips the span before the grid is built, and does so exactly — every row
below is `newest − oldest_included + 1`, on the 8-row dataset:

| `startTimeMillis` | buckets | `aggregations.totalSqlQueries` | oldest bucket |
|---|---|---|---|
| none | 125 | 52 | 2026-04-08 |
| now − 124 d | 118 | 22 | 2026-04-15 |
| now − 100 d | 91 | 0 | 2026-05-12 |
| now − 30 d | 15 | 0 | 2026-07-27 |
| now − 5 d | 1 | 0 | 2026-08-10 |

The filtering itself is correct; it is mentioned only because a bucket count that moves with
the filter is easy to misread as data changing.

### To Reproduce

```bash
GMS=${GMS:-http://localhost:8080}
URN='urn:li:dataset:(urn:li:dataPlatform:postgres,mydb.gappy_table,PROD)'

# what the aggregation returns
curl -s -X POST "$GMS/api/graphql" -H 'Content-Type: application/json' -d "{\"query\":\"{
  dataset(urn: \\\"$URN\\\") { usageStats(range: ALL) {
    buckets { bucket metrics { totalSqlQueries } } aggregations { totalSqlQueries } } } }\"}"

# what was actually written
curl -s -X POST "$GMS/aspects?action=getTimeseriesAspectValues" \
  -H 'Content-Type: application/json' \
  -d "{\"urn\":\"$URN\",\"entity\":\"dataset\",\"aspect\":\"datasetUsageStatistics\",
       \"startTimeMillis\":0,\"endTimeMillis\":4102444800000,\"limit\":2000}"
```

Count the second response's rows against the first response's buckets.

### Expected behavior

The behaviour itself is defensible — a dense grid is convenient for charting. What is missing
is any statement of it. `len(buckets)` reads as "how many days do we have data for"; here it is
125 when the answer is 8, a factor of 15. Anyone computing coverage, confidence, "days
observed" or sparkline density from `buckets.length` walks into the same trap.

The null-versus-zero rule is load-bearing: it is the only thing separating "nobody wrote a row
for that day" from "we measured that day and there was no traffic". For a tool deciding whether
a table is still used, those are opposite conclusions.

### Suggested change

A schema description on `UsageQueryResult.buckets` (and a line in the usage docs) saying:

> Buckets form a contiguous per-`duration` grid spanning the oldest to the newest recorded
> measurement inside the requested range. A bucket whose metrics are `null` means no
> measurement was recorded for that interval; a bucket whose metrics are `0` means a
> measurement was recorded and it was zero. `buckets.length` is therefore a calendar span, not
> a count of measurements.

Filed as docs rather than as a bug because it is entirely possible the grid is deliberate and
only the documentation is missing. If the wording above is accurate, I am happy to open the
docs PR.

### Additional context

**Environment** — DataHub **v1.5.0.6** (`acryldata/datahub`, commit `d0fce948555c06b3083479d40e8fa270d156c71f`),
`datahub docker quickstart`, `serverType: quickstart`, no auth, client `acryl-datahub` 1.6.0.17
on Python 3.11.9. Measured **2026-08-10** (first observed 2026-08-07, re-verified today,
including both controls).
