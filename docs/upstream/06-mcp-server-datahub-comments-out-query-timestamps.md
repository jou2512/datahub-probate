# `mcp-server-datahub` strips every timestamp from query entities, so an MCP client can never tell when a query ran

**Type:** Bug — client query documents
**Repository:** `acryldata/mcp-server-datahub` (**not** the main `datahub` repo — this one is
filed separately)
**Version:** `mcp-server-datahub` **0.6.0** (current release as of 2026-08-07)
**Severity:** Silent capability loss. Nothing errors; the data simply never arrives.

## What I did

Used the MCP server to find which queries touch a given dataset, then tried to judge how
recently those queries ran. The tool returns the queries. It never returns a time.

Looking at the packaged GraphQL documents explains why.

## What happened

In the installed 0.6.0 package, `mcp_server_datahub/gql/queries.gql`:

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
}
```

`created` is commented out in full. Inside `lastModified`, `time` is commented out while
`actor` is kept — so the document asks who last touched the query but not when.

`mcp_server_datahub/gql/query_entity.gql` has the same effect without the comments:

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

After stripping comments, neither document requests `created` or `time` anywhere.

## The server offers these fields

This is the half that makes it a client bug rather than a backend limitation. Against DataHub
GMS v1.5.0.6, introspection of `QueryProperties`:

```
statement : QueryStatement
source    : QuerySource
name      : String
description : String
created   : AuditStamp     ← available
createdOn : ResolvedAuditStamp
lastModified : AuditStamp  ← available
origin    : Entity
customProperties : …

AuditStamp: { time: Long, actor: String }
```

And the same query the MCP server issues, with the commented-out fields restored, works and
returns real values:

```graphql
query {
  listQueries(input: {start: 0, count: 3}) {
    total
    queries { urn properties { created { time actor } lastModified { time actor } } }
  }
}
```

```json
{
  "urn": "urn:li:query:bdc4b851a09917e3",
  "properties": {
    "created":      {"time": 1754300000000, "actor": "urn:li:corpuser:datahub"},
    "lastModified": {"time": 1754300000000, "actor": "urn:li:corpuser:datahub"}
  }
}
```

So the fields exist, resolve, and carry data. They are simply not asked for.

## Why it matters

An MCP client can establish **which** queries touch a dataset but never **when** any of them
ran. Every question of the form "is this still used", "when was this last read", "has traffic
stopped since the migration" is unanswerable over MCP, and unanswerable in a way that gives no
hint: the tool returns results, the results are just permanently undated.

There is also no tool for usage buckets, so there is no second route to a timestamp — the
information is not merely inconvenient to get, it is absent from the interface.

Our own tool needs query recency, so we bypassed MCP and went to GraphQL directly. That works,
but it means the MCP server cannot be used for the class of task it looks best suited to.

## Environment

- `mcp-server-datahub` **0.6.0**, installed via `uvx --python 3.11 mcp-server-datahub==0.6.0`
  (0.5.0+ requires Python ≥ 3.11)
- DataHub GMS **v1.5.0.6** (`datahub docker quickstart`), `http://localhost:28080`, no auth
- Measured **2026-08-07**

A note on version, because it bit us: our own notes from earlier in the month recorded
`@latest` resolving to 0.4.0 with zero mutation tools registered. Re-measured on 2026-08-07,
`@latest` resolves to **0.6.0**, which registers 6 tools by default and 18 with
`TOOLS_IS_MUTATION_ENABLED=true`. Those older observations are stale and are **not** part of
this report. The commented-out timestamps are the one thing that still holds in 0.6.0, and
that is why it is the only MCP item here.

## Reproduction

```bash
# 1. the client side: no timestamp is requested
python - <<'PY'
import pathlib, mcp_server_datahub
gql = pathlib.Path(mcp_server_datahub.__file__).parent / "gql"
for name in ("queries.gql", "query_entity.gql"):
    text = (gql / name).read_text()
    effective = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    print(name,
          "requests created:", any(l.strip() == "created" for l in effective.splitlines()),
          "| requests time:", any(l.strip() == "time" for l in effective.splitlines()))
PY

# 2. the server side: the fields are there and populated
curl -s -X POST http://localhost:8080/api/graphql -H 'Content-Type: application/json' \
  -d '{"query":"{ listQueries(input:{start:0,count:3}) { total queries { urn properties { created { time actor } lastModified { time actor } } } } }"}'
```

Scripted, both halves checked together:

```bash
uv run --python 3.11 --with mcp-server-datahub==0.6.0 \
  python harness/upstream_repro.py --no-seed \
    --sparse-urn "$URN" --dense-urn "$URN" --empty-urn "$URN"
```

→ probe `06-mcp-server-datahub-comments-out-query-timestamps` in
`harness/runs/upstream-repro.json`. It reads the `.gql` files out of the **installed package**
rather than the GitHub repo (so the finding is about the artifact people actually run),
strips comments, and asserts that no timestamp is requested — then introspects the server and
performs a live fetch to prove the fields are available. Both halves must hold or the probe
fails.

Related artifacts from our own measurements of the MCP server: `harness/mcp_probe.py` and
`harness/runs/mcp-probe.json`.

## Suggested fix

Uncomment the fields:

```graphql
lastModified {
  time
  actor
}
created {
  time
  actor
}
```

If they were commented out to work around an older GMS that did not resolve them, that
constraint no longer applies on v1.5.0.6 — the live fetch above is the evidence. If the
concern is response size on large result sets, requesting `lastModified.time` only (four extra
bytes per query) would already restore the capability.

A short comment in the file saying *why* they are commented out would also have saved this
investigation, whatever the answer turns out to be.

## Willing to contribute

Yes — this is a two-line change and we are happy to open the PR, once you confirm the fields
were not disabled for a reason we cannot see from outside.
