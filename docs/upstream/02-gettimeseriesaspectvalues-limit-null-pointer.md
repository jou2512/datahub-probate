# `getTimeseriesAspectValues` returns HTTP 500 `NullPointerException` when `limit` is omitted

**Type:** Bug — Rest.li API
**Component:** `metadata-service` — `com.linkedin.metadata.resources.restli`, action
`getTimeseriesAspectValues`
**Severity:** Low impact, high friction. An unhandled NPE reaches the client instead of a
validation error, and the caller cannot tell a malformed request from a server fault.

## What I did

Called `POST /aspects?action=getTimeseriesAspectValues` with `urn`, `entity`, `aspect`,
`startTimeMillis` and `endTimeMillis`, but no `limit`.

## What I expected

Either a default page size applied, or an HTTP 400 naming the missing field. `limit` is a
paging parameter, so omitting it reads as "no explicit page size", not as a malformed request.

## What happened

HTTP 500, with a raw Java `NullPointerException` in the body:

```json
{
  "exceptionClass": "com.linkedin.restli.server.RestLiServiceException",
  "stackTrace": "com.linkedin.restli.server.RestLiServiceException [HTTP Status:500]: java.lang.NullPointerException: Cannot invoke \"java.lang.Integer.intValue()\" because \"limit\" is null\n\tat com.linkedin.metadata.resources.restli.RestliUtils.toTask(RestliUtils.java:49)\n\t…"
}
```

The message does at least name `limit`, which is better than finding 01. But it arrives as a
500 with a stack trace, so a client's error handling classifies it as "the server is broken"
and typically retries — which cannot succeed.

With `limit` supplied and everything else identical, the same call returns HTTP 200 and the
expected rows.

## Environment

- DataHub **v1.5.0.6** (`acryldata/datahub`, commit `d0fce948555c06b3083479d40e8fa270d156c71f`)
- `datahub docker quickstart`, `serverType: quickstart`
- GMS at `http://localhost:28080`, no auth (local quickstart)
- Measured 2026-08-07

## Reproduction

Any dataset with at least one `datasetUsageStatistics` row.

```bash
URN='urn:li:dataset:(urn:li:dataPlatform:postgres,mydb.mytable,PROD)'

# fails: HTTP 500 NullPointerException: "limit" is null
curl -s -X POST 'http://localhost:8080/aspects?action=getTimeseriesAspectValues' \
  -H 'Content-Type: application/json' \
  -d "{\"urn\":\"$URN\",\"entity\":\"dataset\",\"aspect\":\"datasetUsageStatistics\",
       \"startTimeMillis\":0,\"endTimeMillis\":4102444800000}"

# succeeds: identical, plus "limit"
curl -s -X POST 'http://localhost:8080/aspects?action=getTimeseriesAspectValues' \
  -H 'Content-Type: application/json' \
  -d "{\"urn\":\"$URN\",\"entity\":\"dataset\",\"aspect\":\"datasetUsageStatistics\",
       \"startTimeMillis\":0,\"endTimeMillis\":4102444800000,\"limit\":100}"
```

Scripted:

```bash
uv run --python 3.11 python harness/upstream_repro.py --no-seed \
    --sparse-urn "$URN" --dense-urn "$URN" --empty-urn "$URN"
```

→ probe `02-gettimeseriesaspectvalues-limit-null-pointer` in
`harness/runs/upstream-repro.json`. It asserts the 500 and the NPE text, then asserts that the
same call with `limit` returns exactly the rows present in the store.

## Suggested fix

Apply a default when `limit` is absent, in the same place the NPE is thrown. Something in the
spirit of:

```java
int effectiveLimit = limit != null ? limit : DEFAULT_TIMESERIES_LIMIT;
```

If a default is undesirable because an unbounded scan is expensive, then reject explicitly
with a 400 (`"limit is required"`) rather than dereferencing null. Either way, the NPE should
not reach the wire.

Note that this is the same shape of defect as finding 01 on the GraphQL side: a parameter that
is de facto required is presented as optional, and the omission surfaces as a 500 rather than
a validation error. If a general pass over "optional-looking but actually required" parameters
is of interest, these two are probably not the only instances.

## Willing to contribute

Yes — happy to submit the default-or-400 patch with a test.
