<!-- repo: datahub-project/datahub | title: Docs: OpenAPI v3 get-aspect returns only the newest row for timeseries aspects, indistinguishable from a complete response -->

### Describe the bug

Reading a **timeseries** aspect through the generic OpenAPI v3 get-aspect route returns a
single value — the newest row — shaped exactly like a versioned aspect, with nothing in the
response indicating that a history exists.

```
GET /openapi/v3/entity/dataset/{urn}/datasetusagestatistics
```

on a dataset with **8** `datasetUsageStatistics` rows returns HTTP 200 and, verbatim, the
entire body:

```json
{
  "value": {
    "eventGranularity": {"multiple": 1, "unit": "DAY"},
    "timestampMillis": 1786320000000,
    "totalSqlQueries": 0,
    "partitionSpec": {"type": "FULL_TABLE", "partition": "FULL_TABLE_SNAPSHOT"},
    "uniqueUserCount": 0
  }
}
```

That is the newest of the 8 rows, and it is correct as far as it goes. The top-level object has
exactly one key, `value`. There is no count, no total, no `hasMore`, no `next` — nothing
distinguishes "this aspect has one value" from "this aspect has 8 values and you are looking at
the latest".

The route is not blind to timeseries data: on a dataset with no usage rows it returns `null`.
It reports presence and absence faithfully. It just never mentions depth.

| Dataset | rows in the timeseries store | rows returned | value returned |
|---|---|---|---|
| gappy history | 8 | 1 | newest row ✓ |
| no history | 0 | `null` | — |

### To Reproduce

```bash
GMS=${GMS:-http://localhost:8080}
URN='urn:li:dataset:(urn:li:dataPlatform:postgres,mydb.mytable,PROD)'   # URL-encode the URN

# one row, no indication that more exist
curl -s "$GMS/openapi/v3/entity/dataset/$URN/datasetusagestatistics"

# the series
curl -s -X POST "$GMS/aspects?action=getTimeseriesAspectValues" \
  -H 'Content-Type: application/json' \
  -d "{\"urn\":\"$URN\",\"entity\":\"dataset\",\"aspect\":\"datasetUsageStatistics\",
       \"startTimeMillis\":0,\"endTimeMillis\":4102444800000,\"limit\":2000}"
```

### Expected behavior

Either the history, or something in the response saying it cannot serve one.

The route is generic across aspect types, and for every versioned aspect "the value" is the
whole truth. For a timeseries aspect it is the most recent sample of a series. A client written
against the versioned case — which is most clients, since the route looks uniform — reads one
row and believes it has read the aspect.

Concretely: our verification code checked writes by reading the aspect back through this route.
Every read succeeded, every value was correct, and we were checking one row out of eight
without knowing it. The fix on our side was to use
`POST /aspects?action=getTimeseriesAspectValues`, which returns the series — nothing pointed us
there; we found it by comparing counts against the search index.

### Suggested change

Cheapest first:

1. **Document it.** In the OpenAPI v3 entity-aspect docs: for timeseries aspects this route
   returns the most recent value only; use `POST /aspects?action=getTimeseriesAspectValues` for
   the series. This alone closes it for us.
2. **Say it in the response** — a `latestOf` / `totalValues` field, or a link to the timeseries
   route — so the truncation is self-evident without reading docs first.
3. Optionally accept a `limit`/time-range parameter on this route for timeseries aspects.
   Larger change, probably not worth it given (1).

I am not arguing the current behaviour is wrong — returning the latest value is a reasonable
default. The issue is that the response is indistinguishable from a complete one. Happy to
write the docs PR for (1).

### Additional context

**Environment** — DataHub **v1.5.0.6** (`acryldata/datahub`, commit `d0fce948555c06b3083479d40e8fa270d156c71f`),
`datahub docker quickstart`, `serverType: quickstart`, no auth. Measured **2026-08-10** (first
observed 2026-08-07, re-verified today; the response body above is today's, copied verbatim).
