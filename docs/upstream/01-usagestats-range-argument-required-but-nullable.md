# `Dataset.usageStats` declares every argument nullable, but returns HTTP 500 when `range` is omitted

**Type:** Bug — GraphQL API
**Component:** `datahub-graphql-core` — `Dataset.usageStats`
**Severity:** Low impact, high friction. Nothing is corrupted; the caller just gets a 500 with
no indication of which argument is missing.

## What I did

Called `Dataset.usageStats` without the `range` argument. The schema says all four of its
arguments are optional, so I expected either a default window or a validation error naming the
missing argument.

Schema, read straight from the running instance by introspection:

```graphql
usageStats(
  resource: String,          # SCALAR, nullable, no default
  range: TimeRange,          # ENUM,   nullable, no default
  startTimeMillis: Long,     # SCALAR, nullable, no default
  timeZone: String           # SCALAR, nullable, no default
): UsageQueryResult
```

None of the four is `NON_NULL`. None has a `defaultValue`.

## What I expected

One of:

1. a sensible default range applied, or
2. a GraphQL validation error of the "argument `range` is required" family, with a 4xx-class
   `extensions.code`.

## What happened

Every call that omits `range` returns a 500-class error:

```json
{
  "message": "Name is null",
  "path": ["dataset", "usageStats"],
  "extensions": { "code": 500, "type": "SERVER_ERROR" }
}
```

Note that GraphQL returns HTTP 200 with the error in the `errors` array, so a client checking
only the status code sees a success.

`"Name is null"` reads like an enum lookup on a null value (`TimeRange.valueOf(null)` or
equivalent). It names neither the field nor the argument, which is what makes it expensive:
there is nothing in the message to search for.

Measured, all five variants against the same dataset:

| Call | Result |
|---|---|
| `usageStats { aggregations { totalSqlQueries } }` | **HTTP 500** `Name is null` |
| `usageStats(startTimeMillis: <ms>) { … }` | **HTTP 500** `Name is null` |
| `usageStats(timeZone: "UTC") { … }` | **HTTP 500** `Name is null` |
| `usageStats(resource: "<urn>") { … }` | **HTTP 500** `Name is null` |
| `usageStats(range: ALL) { … }` | 200, `{"totalSqlQueries": 52}` |
| `usageStats(startTimeMillis: <ms>, range: ALL) { … }` | 200, `{"totalSqlQueries": 0}` |

So `range` is de facto required, while the schema advertises it as optional. Every other
argument is genuinely optional — but only in the presence of `range`.

Two smaller things noticed alongside, mentioned here rather than as separate reports:

- `Dataset.usageStats` has **no `endTimeMillis`** argument (`Unknown field argument
  'endTimeMillis'`), although its siblings `datasetProfiles` and `operations` on the same type
  both take `startTimeMillis` **and** `endTimeMillis`. So `usageStats` cannot express a closed
  interval, only an open-ended one.
- Neither `range` nor `startTimeMillis` carries a schema description explaining how they
  interact.

## Environment

- DataHub **v1.5.0.6** (`acryldata/datahub`, commit `d0fce948555c06b3083479d40e8fa270d156c71f`)
- `datahub docker quickstart`, `serverType: quickstart`
- GMS at `http://localhost:28080`, no auth (local quickstart)
- Measured 2026-08-07

## Reproduction

Any dataset works, including one with no usage data at all.

```bash
URN='urn:li:dataset:(urn:li:dataPlatform:postgres,mydb.mytable,PROD)'

# fails: HTTP 500 "Name is null"
curl -s -X POST http://localhost:8080/api/graphql \
  -H 'Content-Type: application/json' \
  -d "{\"query\":\"{ dataset(urn: \\\"$URN\\\") { usageStats { aggregations { totalSqlQueries } } } }\"}"

# succeeds: the only difference is `range`
curl -s -X POST http://localhost:8080/api/graphql \
  -H 'Content-Type: application/json' \
  -d "{\"query\":\"{ dataset(urn: \\\"$URN\\\") { usageStats(range: ALL) { aggregations { totalSqlQueries } } } }\"}"
```

Scripted, including the schema introspection that shows the arguments are nullable:

```bash
uv run --python 3.11 python harness/upstream_repro.py --no-seed \
    --sparse-urn "$URN" --dense-urn "$URN" --empty-urn "$URN"
```

→ probe `01-usagestats-range-argument-required-but-nullable` in
`harness/runs/upstream-repro.json`, which records the introspected argument kinds and the
outcome of each variant.

## Suggested fix

Any of these closes it; they are listed cheapest first.

1. **Give `range` a default** (`TimeRange.MONTH` would match the rest of the UI) so the
   nullable declaration becomes true.
2. **Make `range` non-null in the schema** (`range: TimeRange!`), so the requirement is
   enforced at validation time and the error names the argument.
3. **Keep it nullable and handle null explicitly**, returning a 4xx-class GraphQL error along
   the lines of `usageStats requires either 'range' or 'startTimeMillis'`.

Option 2 is a breaking schema change for clients that currently pass `range` anyway (all of
them, since anything else 500s), so it is less disruptive than it looks. Option 1 breaks
nothing.

Independently of which is chosen, the argument descriptions are worth filling in — see
`docs-patch.md`.

## Willing to contribute

Yes. Happy to open a PR for option 1 or 3 with a regression test.
