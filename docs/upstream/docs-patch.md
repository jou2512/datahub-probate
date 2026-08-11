# Proposed documentation changes

Concrete wording for the findings in this folder that are documentation defects rather than
bugs, plus the schema-description half of the two that are bugs.

**No documentation pull request has been opened.** The findings this wording belongs to were
filed as issues on 2026-08-10 — see [`README.md`](README.md) for the six links. Turning this
wording into a PR against the docs is a separate, deliberate act and has not happened.

Where we quote current wording, we quote what the running
instance and the published docs actually say on 2026-08-07 against **DataHub v1.5.0.6** /
**mcp-server-datahub 0.6.0**; where a description is simply absent, we say "absent" rather
than inventing a strawman to correct.

---

## 1 · `UsageQueryResult.buckets` — say that it is a calendar grid

**Finding:** [04](04-usagestats-buckets-are-a-dense-calendar-grid.md)
**Where:** the GraphQL schema description for `UsageQueryResult.buckets` (and
`UsageAggregation`), plus the usage section of the docs site.

### Current

The field carries **no description at all**. Introspecting `UsageQueryResult` on a running
instance returns `buckets` with a null `description`, and the docs describe usage stats in
terms of what they measure, never in terms of the shape of the returned series.

Because there is no wording to correct, the change is an addition, not a rewrite.

### Proposed

> **`buckets`** — The usage series for the requested range, as a contiguous grid: one bucket
> per `duration` interval from the oldest to the newest recorded measurement inside the range.
> Intervals for which no measurement was recorded are present as buckets with **null**
> metrics; intervals that were measured and had no activity carry **zero** metrics. The two
> are different statements and must not be conflated.
>
> Consequently `buckets.length` is the number of intervals **spanned**, not the number of
> measurements recorded. A dataset with 8 recorded days spread over four months returns ~125
> daily buckets, of which ~117 have null metrics. To count or inspect the recorded
> measurements themselves, read the timeseries aspect directly via
> `POST /aspects?action=getTimeseriesAspectValues`.
>
> The grid is anchored on real measurements: a dataset with no recorded usage returns no
> buckets, and a dataset whose measurements are consecutive returns exactly as many buckets as
> measurements.

### Why this wording

The last paragraph is not padding — it is what distinguishes "grid spanning the data" from
"grid spanning the requested range", and we could only tell the two apart by running a
control. A reader should not have to.

---

## 2 · The OpenAPI v3 entity-aspect route on timeseries aspects

**Finding:** [05](05-openapi-v3-get-aspect-returns-newest-timeseries-row-only.md)
**Where:** the OpenAPI v3 entity API documentation, on
`GET /openapi/v3/entity/{entityType}/{urn}/{aspectName}`.

### Current

The route is documented generically for "an aspect" of an entity, with no distinction between
versioned and timeseries aspects. Nothing in the description, and nothing in the response
schema, mentions that timeseries aspects behave differently.

### Proposed

Add a note to the route description:

> **Timeseries aspects.** For a timeseries aspect (for example `datasetUsageStatistics`,
> `datasetProfile`, `operation`), this route returns the **most recent value only**. The
> response is shaped identically to a versioned aspect and contains no indication that further
> values exist. To read the series, use
> `POST /aspects?action=getTimeseriesAspectValues` with `urn`, `entity`, `aspect`,
> `startTimeMillis`, `endTimeMillis` and `limit`.
>
> A `null` response from this route means the aspect has no values at all, which is
> distinguishable from "one value exists".

The same note belongs in whatever page lists which aspects are timeseries, since that list is
what tells a reader whether the note applies to them.

---

## 3 · `Dataset.usageStats` arguments — describe them, and say `range` is required

**Finding:** [01](01-usagestats-range-argument-required-but-nullable.md)
**Where:** GraphQL schema argument descriptions on `Dataset.usageStats`.

### Current

All four arguments — `resource`, `range`, `startTimeMillis`, `timeZone` — carry **no
description** and **no default value**, and all four are nullable. Nothing states that `range`
must be supplied.

### Proposed

Alongside the code fix (a default, or a non-null declaration), add descriptions:

> **`range`** — The time window to report on. **Required in practice:** omitting it currently
> results in a server error. Prefer `ALL` when you want the full recorded history.
>
> **`startTimeMillis`** — Optional lower bound, applied **in addition to** `range`. Buckets and
> aggregations are computed over the intersection. Has no effect unless `range` is also given.
>
> **`resource`** — Optional; defaults to the dataset the field is resolved on.
>
> **`timeZone`** — Optional; affects bucket boundary alignment.
>
> Note that `usageStats` has no `endTimeMillis` argument, unlike the sibling fields
> `datasetProfiles` and `operations` on the same type. Only open-ended windows can be
> expressed.

If the code fix chosen is "give `range` a default", replace *"Required in practice: omitting it
currently results in a server error"* with the default value.

---

## 4 · `getTimeseriesAspectValues` — mark `limit` as required

**Finding:** [02](02-gettimeseriesaspectvalues-limit-null-pointer.md)
**Where:** the Rest.li action documentation for `getTimeseriesAspectValues`.

### Current

`limit` is listed alongside the other request fields with nothing marking it as mandatory. It
reads as an ordinary paging parameter.

### Proposed

If the code keeps requiring it:

> **`limit`** *(required)* — Maximum number of aspect values to return. **Must be supplied**;
> omitting it currently results in an HTTP 500. There is no default.

If a default is introduced instead, document the default value and drop the "required" marker.
Our preference is the default — see the finding — but the documentation should match whichever
is chosen rather than describing the intent.

---

## 5 · `DatasetUsageStatistics.uniqueUserCount` — say what actually aggregates it

**Finding:** [03](03-usagestats-uniqueusercount-aggregation-is-always-zero.md)
**Where:** the `DatasetUsageStatistics` aspect documentation and the Python SDK docstring for
`DatasetUsageStatisticsClass`.

**This one is a fallback, not our preferred outcome.** The finding is a bug, and the right fix
is in code. The wording below is only worth adding if the maintainers decide the current
behaviour is intended.

### Current

The aspect documents `uniqueUserCount` and `userCounts` as independent optional fields.
Nothing states that the aggregates and `statsSummary` are derived from `userCounts` alone, nor
that a writer setting only `uniqueUserCount` will see `0` in every aggregate.

### Proposed (only if the behaviour is intended)

> **`uniqueUserCount`** — Number of distinct users in this interval. Reported back per bucket
> as written. **Not** used to compute `usageStats.aggregations.uniqueUserCount` or
> `statsSummary.uniqueUserCountLast30Days`: those are derived from the `userCounts` array. If
> you write `uniqueUserCount` without `userCounts`, both aggregates report `0` — meaning
> "cannot be derived", not "no users".
>
> To make unique-user aggregates meaningful, populate `userCounts` with one entry per user.

The last sentence is the part that would have saved us the debugging: the current docs give a
writer no reason to suspect that setting the obvious field is insufficient.

---

## 6 · `mcp-server-datahub` — a comment saying why the timestamps are off

**Finding:** [06](06-mcp-server-datahub-comments-out-query-timestamps.md)
**Repository:** `acryldata/mcp-server-datahub`
**Where:** `mcp_server_datahub/gql/queries.gql`

This is a code fix (uncomment the fields), not a docs fix. But if the fields must stay
disabled, the file should say why:

```graphql
    # `created` and `lastModified.time` are omitted deliberately: <reason>.
    # Consequence: query entities reach MCP clients without any timestamp, so
    # recency cannot be judged over MCP. See <issue link>.
```

A commented-out field with no explanation is indistinguishable from a leftover, which is why
we spent time confirming the server could serve it before reporting anything.
