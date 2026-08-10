<!-- repo: acryldata/mcp-server-datahub | title: Query entities have no timestamp over MCP: `queries.gql` comments out `properties.created` and `lastModified.time` -->

### Summary

No MCP tool returns a timestamp for a **query** entity. `gql/queries.gql` comments out
`QueryProperties.created` in full and `lastModified.time` as well; `gql/query_entity.gql` has
the same effect without the comments. GMS resolves both fields and returns real values for
them, so this looks like a client-side leftover rather than a backend limitation.

The failure is silent: the tools return queries, the queries are simply always undated.

### Root cause

`src/mcp_server_datahub/gql/queries.gql`, `fragment query on QueryEntity` — current `main`,
unchanged in the shipped 0.6.0 wheel:

```graphql
fragment query on QueryEntity {
  urn
  properties {
    name
    description
    source
    statement { value language }
    # created {
    #   time
    #   actor
    # }
    lastModified {
      # time
      actor
    }
  }
  …
```

`created` is commented out in full. Inside `lastModified`, `time` is commented out while `actor`
is kept — so the document asks *who* last touched the query but not *when*.

`src/mcp_server_datahub/gql/query_entity.gql` reaches the same result without comments:

```graphql
properties {
  name
  description
  source
  statement { value language }
  lastModified {
    actor        # no `time`, and no `created` block at all
  }
}
```

After stripping comments, neither document requests `created` or `time` anywhere. I checked this
against the `.gql` files inside the **installed 0.6.0 package**, not only the repo, so it is the
artifact people actually run.

### The server offers these fields

Introspection of `QueryProperties` against DataHub Core **v1.5.0.6**:

```
statement        : QueryStatement
source           : QuerySource
name             : String
description      : String
created          : AuditStamp        ← available
createdOn        : ResolvedAuditStamp
lastModified     : AuditStamp        ← available
origin           : Entity
customProperties : …

AuditStamp: { time: Long, actor: String }
```

The same query the MCP server issues, with the commented-out fields restored, works and returns
real values:

```bash
curl -s -X POST "$GMS/api/graphql" -H 'Content-Type: application/json' \
  -d '{"query":"{ listQueries(input:{start:0,count:3}) { total queries { urn properties { created { time actor } lastModified { time actor } } } } }"}'
```

```json
{"urn": "urn:li:query:bdc4b851a09917e3",
 "properties": {
   "created":      {"time": 1754300000000, "actor": "urn:li:corpuser:datahub"},
   "lastModified": {"time": 1754300000000, "actor": "urn:li:corpuser:datahub"}}}
```

So the fields exist, resolve, and carry data. They are simply not asked for.

### Impact

An MCP client can establish **which** queries touch a dataset but never **when** any of them
ran. Every question of the form "is this still used", "when was this last read", "has traffic
stopped since the migration" is unanswerable over MCP — and unanswerable in a way that gives no
hint, because the tool returns results and the results are just permanently undated.

There is no tool for usage buckets either (#171), so there is no second route to a timestamp:
the information is not merely inconvenient to get, it is absent from the interface.

This is the same shape as #168 (`Dataset.properties.lastModified` never requested, so freshness
is unanswerable for datasets) — a field GMS resolves, requested for some entity types and missed
for another. There it is Dataset; here it is QueryEntity, and here the fields were explicitly
commented out rather than overlooked, which is why I am filing it separately rather than as a
comment on #168.

### Reproduction

```bash
# 1. the client side: no timestamp is requested
python - <<'PY'
import pathlib, mcp_server_datahub
gql = pathlib.Path(mcp_server_datahub.__file__).parent / "gql"
for name in ("queries.gql", "query_entity.gql"):
    text = (gql / name).read_text()
    effective = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    print(name,
          "| requests created:", any(l.strip() == "created" for l in effective.splitlines()),
          "| requests time:", any(l.strip() == "time" for l in effective.splitlines()))
PY
# queries.gql     | requests created: False | requests time: False
# query_entity.gql| requests created: False | requests time: False

# 2. the server side: the fields are there and populated — see the curl above
```

### Suggested fix

Uncomment them:

```graphql
created {
  time
  actor
}
lastModified {
  time
  actor
}
```

If they were commented out to work around an older GMS that did not resolve them, that
constraint does not apply on v1.5.0.6 — the live fetch above is the evidence. If the concern is
response size on large result sets, requesting `lastModified.time` alone would already restore
the capability.

A one-line comment saying *why* they are disabled would also have saved this investigation,
whatever the answer turns out to be.

### Environment

- `mcp-server-datahub` **0.6.0** (current release on PyPI as of 2026-08-10), installed via
  `uvx --python 3.11 mcp-server-datahub==0.6.0`
- DataHub Core **v1.5.0.6** (`datahub docker quickstart`), no auth
- Measured **2026-08-10** (first observed 2026-08-07, re-verified today against both the
  installed package and `main`)

Happy to open the PR — it is a two-line change — once you confirm the fields were not disabled
for a reason not visible from outside.
