# Devpost submission text — copy-paste ready

*This file is the text Joel pastes into the Devpost form. Nothing below is published until he
confirms. Everything between the rulers goes in as-is.*

---

## Field: Challenge category (pick one)

**Agents That Do Real Work**

*Why this one, in three sentences (not part of the pasted text):* the category asks for an agent
that "reads DataHub through the MCP Server or Agent Context Kit … takes action, and writes results
back so the next person or agent inherits the knowledge" — which is literally Probate's three
stages: it reads lineage and usage over both GraphQL **and** the pinned DataHub MCP server, judges
each edge, and writes the verdict back into the catalog as `testResults` and a dated `dead_since`
marker through a journalled, revertible write path. The other three categories fit worse on their
own terms: we generate no data code (Metadata-Aware Code Generation), touch no ML lineage
(Production ML Agents), and Open/Wildcard would throw away a fit we actually have. Our six upstream
findings in `docs/upstream/` are a judging boost inside this category, not a category of their own —
the organisers list open-source contributions as "looked on favorably", not as a track.

---

## Field: Text description

### Your catalog claims connections that nobody re-checks

DataHub tells you table A feeds table B. It never tells you whether anyone has used that path since
the day it was declared. So lineage rots quietly, and every migration, every deprecation, every
impact analysis inherits the rot.

**Probate re-checks it. Per edge. With a date.**

One run against our demo catalog — 618 tables, 4 platforms, 6 databases, 1,476 API calls:

| Verdict | Edges | What you do about it |
|---|---|---|
| `confirmed` | **266** | declared *and* measured — leave it alone |
| `dead` | **73** | declared, zero traffic in the window — and it tells you *since when* |
| `missing` | **29** | real query traffic, never declared — lineage your catalog doesn't know it has |
| `unknown` | **145** | no usage data at all — **no statement made** |
| **total** | **513** | |

That last row is the whole product. Every "lineage cleanup" tool on the market would have reported
those 145 edges as dead and invited you to delete them. Probate refuses: *we could not look* is not
*nothing happened*. It is the failure this project exists to correct, and it was our own bug first.

> The projects we found use usage data to **weight** edges they already believe.
> This tool uses it to **test the edge itself**.

We surveyed the field and found **seven projects that read both lineage and usage**. All seven
attach usage to an edge as a weight, a hint, or an evidence string on lineage they already accept —
none of the seven asks whether the edge should exist. That is a claim about seven projects, not
about the world: GitHub's search does not index READMEs and private repos are invisible, so the
survey is a lower bound, not a census. We would rather claim seven and be right than claim "nobody"
and be one counter-example away from wrong.

### It proves it re-measures, instead of asserting once

Four states existing is easy. An edge *moving* between them when the world changes is the actual
claim — so we measured it: **7 of 7 state transitions proven live**
(`harness/runs/demo-transitions.json`). Declare an edge → `dead`. Seed a query → `confirmed`. Cut
the usage data → `unknown`, **not** `dead`. Every mutation went through the same journalled write
path as the CLI and was taken back inside the same run: 3 journal lines added, 3 reverted.

### The model has to cite, or it is overruled

There is exactly one model call in the whole project: judging *which* deviation matters — a dead
edge into the annual-close table is not a dead edge into a nameless staging table. It runs under a
**citation duty**: no verbatim quote from the metadata it was given, no judgement, and the
deterministic finding stands unchanged. On our seeded four-state lab the rule fired against the
model on one of three offered edges (`fallback_reason: "kein Zitat geliefert"`). We publish the
abstention rate rather than tuning the fixture until it looks better.

### How it uses DataHub

- **Reads** declared lineage (`upstreamLineage`), measured usage buckets (`usageStats`,
  `getTimeseriesAspectValues`) and query co-occurrence (`QuerySubject`) over GraphQL and
  REST/OpenAPI v3.
- **Reads the same thing over DataHub's own MCP server** (`get_dataset_queries`, pinned
  `mcp-server-datahub==0.6.0`) as a second, switchable transport — and we measured what that costs:
  identical verdicts across all four states, 0.075 s end-to-end over GraphQL vs. 9.661 s over MCP,
  of which ~9.4 s is session start; 6 tools by default, 18 with `TOOLS_IS_MUTATION_ENABLED=true`;
  telemetry overhead 0.315 s per call. Where MCP stops is precise: `queries.gql` in 0.6.0 comments
  out `created` and `lastModified.time`, so query entities carry **no timestamp** — co-occurrence
  over MCP yes, the age judgement no.
- **Writes back** so the next agent inherits it: `testResults` (the evaluator DataHub displays but
  doesn't have), a `probate.dead_since` marker dated from the *measurement* not the run, and merged
  lineage edges — dry-run by default, journalled, with a real reverse gear that deletes aspects that
  didn't exist before instead of writing back an invented `None`.
- **Watches continuously** via `acryl-datahub-actions` on real Kafka (80 events received, 1 relapse
  detected and correctly refused as a dry run).

### The tech behind it

Python 3.11 pinned through `uv` · DataHub OSS quickstart (GMS over GraphQL + REST/OpenAPI v3) ·
DataHub MCP server `0.6.0` as second transport · `acryl-datahub` · `acryl-datahub-actions` + Kafka ·
Claude behind an injectable `str -> str` transport, so the judge is fully testable offline ·
plain HTML/CSS/JS console, no framework · `pytest` · Apache 2.0.

Each module has one job and one way out: `ledger.py` (four states, coverage check, timeline),
`judge.py` (the only model call), `gms.py` (the only read path), `writeback.py` (the only write
path), `audit_claims.py` (the gate below).

### Why you can believe any of these numbers

**`harness/audit_claims.py` re-derives every number in our prose from the committed run artifacts
and exits 1 on any drift. 140 numbers are under that gate right now.** It runs offline, without a
DataHub instance, in seconds — as does the full test suite, green in about 30. (We deliberately
don't quote a test count: it moves with every commit, and a number in prose that nothing checks is
the exact thing this project argues against.)

We ran that gate against ourselves and lost, repeatedly — and published the corrections instead of
the originals. Three claims we had made about DataHub's *own* MCP server ("`@latest` is 0.4.0",
"zero mutation tools", "~54 s telemetry per call") turned out to be wrong five days later; we
re-measured and replaced them. Our own write path was destroying column-level lineage — the exact
failure we accuse `sql_parsing_aggregator.py` of. Our citation rule was satisfiable with a
one-character quote. All of it is in the repo, in `docs/devpost.md` and the README's *Honest
limitations*, which is the longest section in it on purpose.

### Upstream contributions — filed, not just prepared

Seven contributions to DataHub, all filed today (2026-08-10), every one re-measured against a live
instance the same day before it went out:

| # | What | Where |
|---|---|---|
| 1 | `usageStats.aggregations.uniqueUserCount` is always 0 while buckets in the same response report 4 and 3 — a **wrong number** shown on the dataset page, not an error | [datahub#19066](https://github.com/datahub-project/datahub/issues/19066) |
| 2 | `Dataset.usageStats` returns HTTP 500 *"Name is null"* when the nullable `range` argument is omitted — with the line (`DatasetUsageStatsResolver.java:35`, `UsageTimeRange.valueOf(null)`) and a fix offer | [datahub#19067](https://github.com/datahub-project/datahub/issues/19067) |
| 3 | The root cause behind an existing report: `AspectResource` unboxes a null `limit`, while its `startTimeMillis`/`endTimeMillis` neighbours are null-guarded — plus a raw-`curl` confirmation that it is not SDK-specific | [comment on datahub#19016](https://github.com/datahub-project/datahub/issues/19016#issuecomment-5242013528) |
| 4 | Query entities carry no timestamp over MCP: `queries.gql` comments out `properties.created` and `lastModified.time`, while GMS serves both — a client defect, not a backend limit | [mcp-server-datahub#209](https://github.com/acryldata/mcp-server-datahub/issues/209) |
| 5 | Docs: `usageStats.buckets` is a dense calendar grid — 125 buckets for 8 measured days — and the `null` vs `0` distinction inside it is undocumented | [datahub#19068](https://github.com/datahub-project/datahub/issues/19068) |
| 6 | Docs: OpenAPI v3 get-aspect returns only the newest row for timeseries aspects, indistinguishable from a complete response | [datahub#19069](https://github.com/datahub-project/datahub/issues/19069) |
| 7 | **A correction to someone else's issue** — three claims about the MCP server (`@latest` → 0.4.0, zero mutation tools, ~54 s telemetry) that we had copied into our own notes as facts. Re-measured: 0.6.0, 6 tools / 18 with the flag, 0.315 s. The ~54 s was session start attributed to a call | [comment on mcp-server-datahub#167](https://github.com/acryldata/mcp-server-datahub/issues/167#issuecomment-5242043100) |

Number 3 is deliberately a comment, not an issue: the bug had already been reported on 2026-08-09,
and a duplicate helps nobody. Number 7 is the one we would point a juror at — we inherited three
wrong numbers from a search result, built on them for five days, measured them, and corrected the
source.

**The other optional boost:** `examples/` carries 21 sample outputs — ledgers, verdicts, the
write-back journal, refused campaigns, watcher logs.

### Honest, up front

All usage data in every run is **seeded** (`harness/seed_lineage_lab.py`) — DataHub's sample catalog
ships none, live-checked: `totalSqlQueries: null`, `buckets: []`. Every artifact carries
`"seeded": true`. No real warehouse has ever been connected. The load test does **not** demonstrate
the two-stage cost saving it was designed to measure, and says so. The watcher's re-evaluation could
not be shown changing a verdict, and says so. A tool whose claim is "assert nothing without
evidence" doesn't get an exception for itself.

**Repo:** `https://github.com/jou2512/datahub-probate` — Apache 2.0, clone-and-run in two commands with no DataHub instance
required.

---

## Field: Built With (tags)

`python` · `datahub` · `mcp` · `graphql` · `kafka` · `claude` · `pytest` · `uv` · `html` ·
`javascript` · `rest-api` · `apache-2.0`

---

## Checklist before submitting (not pasted)

- [ ] `LICENSE` — real Apache-2.0 file at repo root, 202 lines, so GitHub's About box detects it ✔ (present)
- [ ] Repo pushed **public**, `https://github.com/jou2512/datahub-probate` substituted above in both places
- [ ] Demo video **under 3:00**, public on YouTube, plays without sign-in — check in a private window
- [ ] Project URL = the public repo (the organisers state a repo with clear setup instructions is enough)
- [ ] Exactly **one** category selected: *Agents That Do Real Work*
- [ ] `examples/` (21 files) and `docs/upstream/` (6 findings) present ✔
