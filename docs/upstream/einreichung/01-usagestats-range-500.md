<!-- repo: datahub-project/datahub | title: `Dataset.usageStats` returns HTTP 500 "Name is null" when the nullable `range` argument is omitted -->

### Describe the bug

`Dataset.usageStats` declares all four of its arguments as nullable in the GraphQL schema, but
`range` is required in practice. Any call that omits it fails with a 500-class GraphQL error
whose message is `Name is null` — a message that names neither the field nor the argument.

Introspected from the running instance, none of the four arguments is `NON_NULL` and none has a
`defaultValue`:

```graphql
usageStats(
  resource: String,          # SCALAR, nullable, no default
  range: TimeRange,          # ENUM,   nullable, no default
  startTimeMillis: Long,     # SCALAR, nullable, no default
  timeZone: String           # SCALAR, nullable, no default
): UsageQueryResult
```

### To Reproduce

Any dataset works, including one with no usage data at all. GMS below is the quickstart
default `http://localhost:8080`; on my instance it is mapped to `28080`, substitute your port.

```bash
GMS=${GMS:-http://localhost:8080}
URN='urn:li:dataset:(urn:li:dataPlatform:postgres,mydb.mytable,PROD)'

# fails
curl -s -X POST "$GMS/api/graphql" -H 'Content-Type: application/json' \
  -d "{\"query\":\"{ dataset(urn: \\\"$URN\\\") { usageStats { aggregations { totalSqlQueries } } } }\"}"

# succeeds — the only difference is `range`
curl -s -X POST "$GMS/api/graphql" -H 'Content-Type: application/json' \
  -d "{\"query\":\"{ dataset(urn: \\\"$URN\\\") { usageStats(range: ALL) { aggregations { totalSqlQueries } } } }\"}"
```

Actual response of the first call, verbatim:

```json
{"errors":[{"message":"Name is null","locations":[{"line":1,"column":114}],
  "path":["dataset","usageStats"],
  "extensions":{"code":500,"type":"SERVER_ERROR","classification":"DataFetchingException"}}],
 "data":{"dataset":{"usageStats":null}},"extensions":{}}
```

Note the HTTP status is 200 — a client that only checks the status code sees a success.

All five variants against the same dataset:

| Call | Result |
|---|---|
| `usageStats { aggregations { totalSqlQueries } }` | error `Name is null`, `code: 500` |
| `usageStats(startTimeMillis: <ms>) { … }` | error `Name is null`, `code: 500` |
| `usageStats(timeZone: "UTC") { … }` | error `Name is null`, `code: 500` |
| `usageStats(range: ALL) { … }` | 200, `{"totalSqlQueries": 52}` |
| `usageStats(startTimeMillis: <ms>, range: ALL) { … }` | 200 |

### Expected behavior

Either a default range applied, or a GraphQL validation error of the "argument `range` is
required" family with a 4xx-class `extensions.code` — not a 500 with a message that cannot be
searched for.

### Where it comes from

`datahub-graphql-core/src/main/java/com/linkedin/datahub/graphql/resolvers/dataset/DatasetUsageStatsResolver.java:35`
(as of `master` today):

```java
final UsageTimeRange range =
    UsageTimeRange.valueOf(environment.getArgument(Constants.RANGE_INPUT_FIELD));
```

`UsageTimeRange.valueOf(null)` is what produces `Name is null`. The very next lines read
`startTimeMillis` with `getArgumentOrDefault(..., null)`, so the null-tolerant pattern is
already in the same method — only `range` is dereferenced unguarded.

### Suggested fix

Cheapest first:

1. **Give `range` a default** (`TimeRange.MONTH` matches the rest of the UI), so the nullable
   declaration becomes true. Breaks nothing.
2. **Make it non-null in the schema** (`range: TimeRange!`), so validation catches it and the
   error names the argument. Nominally a breaking schema change, but every working client
   already passes `range` — anything else 500s.
3. **Keep it nullable and handle null explicitly**, returning a 4xx GraphQL error such as
   `usageStats requires 'range'`.

### Additional context

Two smaller things noticed alongside, mentioned here rather than as separate issues:

- `Dataset.usageStats` has no `endTimeMillis` argument (`Unknown field argument 'endTimeMillis'`),
  although `datasetProfiles` and `operations` on the same type both take `startTimeMillis` **and**
  `endTimeMillis`. So `usageStats` can only express an open-ended interval.
- Neither `range` nor `startTimeMillis` carries a schema description explaining how they interact.

This is the same defect shape as the `limit` NPE on
`POST /aspects?action=getTimeseriesAspectValues` (#19016): a parameter that is de facto required
is advertised as optional, and the omission surfaces as a 500 rather than a validation error.
A general pass over "optional-looking but actually required" parameters would probably find more.

**Environment** — DataHub **v1.5.0.6** (`acryldata/datahub`, commit `d0fce948555c06b3083479d40e8fa270d156c71f`),
`datahub docker quickstart`, `serverType: quickstart`, no auth, client `acryl-datahub` 1.6.0.17
on Python 3.11.9. Measured **2026-08-10** (first observed 2026-08-07, re-verified today).

Happy to open the PR for option 1 or 3 with a regression test.
