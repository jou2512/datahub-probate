# `usageStats.buckets` is an undocumented dense calendar grid, not a list of measurements

**Type:** Documentation
**Component:** `datahub-graphql-core` — `Dataset.usageStats` (`UsageQueryResult.buckets`), and
the usage docs
**Severity:** No data is wrong. But `len(buckets)` means something quite different from what it
looks like, and nothing says so.

## What I did

Read `usageStats(range: ALL)` for a dataset whose `datasetUsageStatistics` history has gaps —
8 rows written over a 125-day span, most days never written at all — and compared the response
against the rows in the timeseries store.

## What I expected

`buckets` to contain the measurements: 8 rows in, 8 buckets out.

## What happened

125 buckets. One per calendar day from the oldest written row to the newest, inclusive.

```
rows in the primary store  :   8   (2026-04-05 … 2026-08-07)
buckets from usageStats    : 125   = span in days, inclusive
of which padding           : 117
```

The padding is not zeros — this matters, and it is where our own first reading of this was
wrong. Padded buckets carry **null** metrics; measured zero-traffic days carry **0**:

```json
// a day that was measured, and had no traffic
{"bucket": 1778284800000, "duration": "DAY",
 "metrics": {"totalSqlQueries": 0, "uniqueUserCount": 0, "topSqlQueries": null}}

// a day that was never written
{"bucket": 1775433600000, "duration": "DAY",
 "metrics": {"totalSqlQueries": null, "uniqueUserCount": null, "topSqlQueries": null}}
```

Counted over the same 125 buckets: 117 with null metrics (exactly the padding), 6 with
`totalSqlQueries: 0` (exactly the measured zero-traffic rows), 2 with real traffic. So the two
*are* distinguishable — by null versus 0, a distinction that appears nowhere in the docs or the
schema descriptions.

`aggregations.totalSqlQueries` is unaffected: 52, matching the primary store exactly. The
padding adds shape, never traffic.

### It is a span, not a fixed window

Two controls on the same instance, which is what makes the behaviour precise rather than
merely observed:

| Dataset | rows | span of rows | buckets returned |
|---|---|---|---|
| gappy history | 8 | 125 days | **125** |
| 3 consecutive days | 3 | 3 days | **3** — not padded |
| no rows at all | 0 | — | **0** — no grid invented |

If the grid were a fixed window, the second dataset would come back padded too. It does not.
The grid is anchored on the oldest and newest real rows.

`startTimeMillis` clips the span before the grid is built, and does so exactly:

| `startTimeMillis` | buckets | aggregate | oldest row inside the filter |
|---|---|---|---|
| none | 125 | 52 | 2026-04-05 |
| now − 124 d | 118 | 22 | 2026-04-12 |
| now − 100 d | 91 | 0 | 2026-05-09 |
| now − 30 d | 15 | 0 | 2026-07-24 |
| now − 5 d | 1 | 0 | 2026-08-07 |

Every row is `newest − oldest_included + 1`. The filtering itself is correct; we mention it
only because the bucket count moving with the filter is easy to misread as data changing.

## Why this is worth documenting

`len(buckets)` looks like "how many days do we have data for". Here it is 125 when the answer
is 8 — a factor of 15. We used that number as a data-density signal and had to recalibrate the
threshold once we compared it against the store. Anyone computing coverage, confidence,
"days observed", or a sparkline density from `buckets.length` has the same trap ahead of them.

The null-versus-zero rule is load-bearing and undocumented: it is the only thing separating
"nobody wrote a row for that day" from "we measured that day and there was no traffic". For a
tool deciding whether a table is unused, those are opposite conclusions.

## Environment

- DataHub **v1.5.0.6** (`acryldata/datahub`, commit `d0fce948555c06b3083479d40e8fa270d156c71f`)
- `datahub docker quickstart`, `serverType: quickstart`
- GMS at `http://localhost:28080`, no auth (local quickstart)
- Measured 2026-08-07

## Reproduction

```bash
URN='urn:li:dataset:(urn:li:dataPlatform:postgres,mydb.gappy_table,PROD)'

# what the aggregation returns
curl -s -X POST http://localhost:8080/api/graphql -H 'Content-Type: application/json' \
  -d "{\"query\":\"{ dataset(urn: \\\"$URN\\\") { usageStats(range: ALL) { buckets { bucket metrics { totalSqlQueries } } aggregations { totalSqlQueries } } } }\"}"

# what was actually written
curl -s -X POST 'http://localhost:8080/aspects?action=getTimeseriesAspectValues' \
  -H 'Content-Type: application/json' \
  -d "{\"urn\":\"$URN\",\"entity\":\"dataset\",\"aspect\":\"datasetUsageStatistics\",
       \"startTimeMillis\":0,\"endTimeMillis\":4102444800000,\"limit\":2000}"
```

Scripted, with both controls:

```bash
uv run --python 3.11 python harness/upstream_repro.py            # seeds its own fixtures
```

→ probe `04-usagestats-buckets-are-a-dense-calendar-grid` in
`harness/runs/upstream-repro.json`. It asserts the padded count equals the calendar span, that
every padded bucket carries null metrics, that measured zeros stay 0, that the totals agree,
and both controls above.

## Proposed documentation change

See [`docs-patch.md`](docs-patch.md) for the exact wording. In short, `UsageQueryResult.buckets`
needs a schema description saying:

- buckets form a contiguous per-`duration` grid spanning the oldest to the newest recorded
  measurement within the requested range;
- a bucket with null metrics means no measurement was recorded for that interval;
- a bucket with zero metrics means a measurement was recorded and it was zero;
- therefore `buckets.length` is a calendar span, not a count of measurements.

## Willing to contribute

Yes — happy to open the docs PR with this wording if the description above is accurate. We
would rather have it confirmed than guess at intent: it is possible the grid is deliberate and
only the documentation is missing, which is why this is filed as a docs issue and not a bug.
