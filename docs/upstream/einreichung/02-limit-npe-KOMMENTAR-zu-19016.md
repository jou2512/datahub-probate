<!-- KEIN neues Issue. Kommentar zu datahub-project/datahub#19016 -->
<!-- repo: datahub-project/datahub | issue: 19016 | mode: comment -->

I hit the GMS half of this independently while building a lineage/usage checker, and I can add
a root cause and a second data point in case it saves you a look.

**Re-measured today, 2026-08-10**, on DataHub **v1.5.0.6** (`datahub docker quickstart`, commit
`d0fce948555c06b3083479d40e8fa270d156c71f`), no auth, raw `curl` — so this is not specific to
the Python helper:

```bash
curl -s -X POST "$GMS/aspects?action=getTimeseriesAspectValues" \
  -H 'Content-Type: application/json' \
  -d '{"urn":"<dataset urn>","entity":"dataset","aspect":"datasetUsageStatistics",
       "startTimeMillis":0,"endTimeMillis":4102444800000}'
```

```
HTTP 500
com.linkedin.restli.server.RestLiServiceException [HTTP Status:500]:
java.lang.NullPointerException: Cannot invoke "java.lang.Integer.intValue()" because "limit" is null
  at com.linkedin.metadata.resources.restli.RestliUtils.toTask(RestliUtils.java:49)
  at com.linkedin.metadata.resources.entity.AspectResource.getTimeseriesAspectValues(AspectResource.java:198)
  …
```

The identical request with `"limit": 100` returns HTTP 200 and exactly the 8 rows the store
holds for that dataset.

**Where it unboxes.** `metadata-service/restli-servlet-impl/src/main/java/com/linkedin/metadata/resources/entity/AspectResource.java`
on `master` today:

```java
@ActionParam(PARAM_LIMIT) @Optional @Nullable Integer limit,     // line 182
…
if (latestValue) {
  response.setLimit(1);                                          // line 221
} else {
  response.setLimit(limit);                                      // line 223  ← unboxes null
}
```

(Line numbers are from `master` as of today; the stack trace above is from the shipped
v1.5.0.6 image, which reports `AspectResource.java:198`.)

The generated Pegasus setter takes a primitive `int`, so a null `Integer` unboxes and throws.
The interesting part is the asymmetry a few lines above: `startTimeMillis` and `endTimeMillis`
are both null-guarded (`if (startTimeMillis != null) { response.setStartTimeMillis(startTimeMillis); }`
and the same for `endTimeMillis`), `limit` is not — even though all three are declared
`@Optional @Nullable` on the same signature. So this reads
like an oversight rather than an intentional requirement, which would make "apply a default"
the fix that matches the declared contract:

```java
if (limit != null) {
  response.setLimit(limit);
}
```

Note that `limit` is *also* passed straight through to
`timeseriesAspectService.getAspectValues(..., limit, ...)` in the same block, so whichever way
this goes, the downstream path needs to agree about what a missing limit means.

**One more instance of the same shape**, if a general pass is of interest: on the GraphQL side,
`Dataset.usageStats` declares all four arguments nullable but
`DatasetUsageStatsResolver.java:35` calls `UsageTimeRange.valueOf(environment.getArgument(...))`
unguarded, so omitting `range` returns a 500 with the message `Name is null`. I have filed that
separately rather than piling it onto this thread.

I have a small script that reproduces both read-only against a plain quickstart — no writes at
all — and exits non-zero if either claim fails to reproduce. Happy to share it, or to open the
PR for the null-guard here with a test.
