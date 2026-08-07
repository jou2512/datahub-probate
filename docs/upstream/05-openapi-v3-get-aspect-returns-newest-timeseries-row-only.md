# `GET /openapi/v3/entity/{type}/{urn}/{aspect}` silently returns 1 of N rows for timeseries aspects

**Type:** Documentation (or a small API improvement)
**Component:** `metadata-service` — OpenAPI v3 entity endpoints
**Severity:** Nothing is wrong in the response. It is what the response does *not* say that
costs time.

## What I did

Read `datasetUsageStatistics` — a timeseries aspect — through the generic OpenAPI v3
get-aspect route, the same route used for versioned aspects like `datasetProperties` or
`upstreamLineage`:

```
GET /openapi/v3/entity/dataset/{urn}/datasetusagestatistics
```

on a dataset with 8 rows in its usage history.

## What I expected

Either the history, or an explicit signal that this route cannot serve one — a 400, or a
field saying how many rows exist.

## What happened

HTTP 200 and a single aspect value, shaped exactly like a versioned aspect:

```json
{
  "value": {
    "timestampMillis": 1786060800000,
    "totalSqlQueries": 0,
    "uniqueUserCount": 0,
    "eventGranularity": {"unit": "DAY", "multiple": 1},
    "partitionSpec": {"type": "FULL_TABLE", "partition": "FULL_TABLE_SNAPSHOT"}
  }
}
```

That is the newest of the 8 rows, and it is correct as far as it goes. There is no `count`, no
`total`, no `hasMore`, no `next` — nothing in the response distinguishes "this aspect has one
value" from "this aspect has 8 values and you are looking at the latest".

The endpoint also behaves sensibly at the boundary: on a dataset with no usage rows at all it
returns `null`. So it is not blind to timeseries data — it faithfully reports presence and
absence. It just never mentions depth.

Measured:

| Dataset | rows in the timeseries store | rows returned by get-aspect | value returned |
|---|---|---|---|
| gappy history | 8 | 1 | newest row ✓ |
| no history | 0 | 0 (`null`) | — |

## Why it matters

The route is generic across aspect types, and for every versioned aspect "the value" is the
whole truth. For a timeseries aspect it is the most recent sample of a series. A client written
against the versioned case — which is most clients, since the route looks uniform — reads one
row and believes it has read the aspect.

Concretely: our verification code checked writes by reading the aspect back through this route.
Every read succeeded, every value was correct, and we were checking one row out of eight
without knowing it. The fix on our side was to use
`POST /aspects?action=getTimeseriesAspectValues` instead, which returns the series. Nothing
pointed us there; we found it by comparing counts against Elasticsearch.

## Environment

- DataHub **v1.5.0.6** (`acryldata/datahub`, commit `d0fce948555c06b3083479d40e8fa270d156c71f`)
- `datahub docker quickstart`, `serverType: quickstart`
- GMS at `http://localhost:28080`, no auth (local quickstart)
- Measured 2026-08-07

## Reproduction

```bash
URN='urn:li:dataset:(urn:li:dataPlatform:postgres,mydb.mytable,PROD)'

# one row, no indication that more exist
curl -s "http://localhost:8080/openapi/v3/entity/dataset/$URN/datasetusagestatistics"

# the series
curl -s -X POST 'http://localhost:8080/aspects?action=getTimeseriesAspectValues' \
  -H 'Content-Type: application/json' \
  -d "{\"urn\":\"$URN\",\"entity\":\"dataset\",\"aspect\":\"datasetUsageStatistics\",
       \"startTimeMillis\":0,\"endTimeMillis\":4102444800000,\"limit\":2000}"
```

Scripted:

```bash
uv run --python 3.11 python harness/upstream_repro.py --no-seed \
    --sparse-urn "$URN" --dense-urn "$OTHER_URN" --empty-urn "$EMPTY_URN"
```

→ probe `05-openapi-v3-get-aspect-returns-newest-timeseries-row-only` in
`harness/runs/upstream-repro.json`. It asserts the store holds more than one row, that
get-aspect returns exactly one, that the one returned is the newest, that the response carries
no count/total/hasMore/next key, and that the same route returns `null` for a dataset with no
rows.

## Suggested fix

Cheapest first:

1. **Document it.** Add to the OpenAPI v3 entity-aspect docs: for timeseries aspects this route
   returns the most recent value only; use
   `POST /aspects?action=getTimeseriesAspectValues` for the series. Proposed wording is in
   [`docs-patch.md`](docs-patch.md). This alone closes the issue for us.
2. **Say it in the response.** A `latestOf` / `totalValues` field, or a link to the timeseries
   route, would make the truncation self-evident without anyone reading docs first.
3. Optionally, accept a `limit`/time-range parameter on this route for timeseries aspects so
   the generic route can serve the series too. Larger change, probably not worth it given
   option 1.

We are not arguing the current behaviour is wrong — returning the latest value is a reasonable
default. The issue is that the response is indistinguishable from a complete one.

## Willing to contribute

Yes, for option 1 — happy to write the docs PR.
