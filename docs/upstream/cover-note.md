# Cover note — paste when filing

Two versions below. **A** is the short one for the top of an individual issue. **B** is the
longer one for a discussion thread, a Slack message to the maintainers, or the first issue if
you file them as a group.

Both assume the reproduction script is reachable. Before pasting either, decide whether the
repository is public — if it is not yet, replace the repo link with an offer to send the
script, or paste the relevant `curl` commands from the individual finding inline. **Do not
paste a link that a maintainer cannot open.**

---

## A · Short version — one issue

> Found this while building a tool on top of DataHub that compares declared lineage against
> measured usage. Reproduced on **DataHub v1.5.0.6** (`datahub docker quickstart`) on
> **2026-08-07**; details, exact queries and outputs below.
>
> I have a small script that reproduces this and four related findings against a plain
> quickstart instance — it seeds its own throwaway namespace and deletes it afterwards, or runs
> fully read-only against datasets you already have. Happy to share it or to open a PR if you
> tell me which fix you would prefer.

---

## B · Longer version — group of findings

> Hi — while building a tool on DataHub over the past week I ran into a handful of behaviours
> that cost me real debugging time, mostly around usage statistics and the timeseries aspect
> APIs. Rather than keep the workarounds to myself I wrote them up. Each one is measured
> against a live instance with the exact queries and outputs, and each points at a script you
> can run.
>
> **Environment for all of them:** DataHub **v1.5.0.6** (commit `d0fce948`), `datahub docker
> quickstart`, GMS on localhost, no auth, client `acryl-datahub` 1.6.0.17 on Python 3.11.9.
> Measured **2026-08-07**.
>
> The findings, roughly in the order I would prioritise them:
>
> 1. **`usageStats.aggregations.uniqueUserCount` returns 0 while the buckets in the same
>    response report 3, 4 and 5.** The sibling field `totalSqlQueries` aggregates correctly
>    from the same rows. The same 0 also reaches `statsSummary.uniqueUserCountLast30Days`,
>    which is shown in the UI. This is the only one that returns a wrong number rather than an
>    error, so it is the one I would look at first.
> 2. **`Dataset.usageStats` declares all four arguments nullable but returns HTTP 500 `"Name is
>    null"` when `range` is omitted.** The error names neither the field nor the argument.
> 3. **`POST /aspects?action=getTimeseriesAspectValues` without `limit` returns HTTP 500
>    `NullPointerException: "limit" is null`.** Same shape as the previous one: an
>    optional-looking parameter that is required in practice.
> 4. **`usageStats.buckets` is a dense per-day calendar grid, not a list of measurements** —
>    125 buckets for 8 recorded days. Padded buckets carry null metrics, measured zero-traffic
>    days carry 0. That distinction is load-bearing and undocumented. Filed as a docs issue.
> 5. **`GET /openapi/v3/entity/{type}/{urn}/{aspect}` returns only the newest row for a
>    timeseries aspect**, shaped identically to a versioned aspect and with nothing indicating
>    that more rows exist. Also a docs issue.
>
> Separately, for `mcp-server-datahub` (0.6.0): the bundled `queries.gql` comments out
> `QueryProperties.created` entirely and `lastModified.time` as well, so query entities reach
> MCP clients with no timestamp at all. I verified that GMS resolves both fields and returns
> real values for them, so this looks like a client-side leftover rather than a backend
> limitation. I will file that one on the `mcp-server-datahub` repo.
>
> **On reproduction.** There is one script covering all of the above. It can seed its own
> throwaway namespace and clean up after itself, or run entirely read-only against datasets
> you already have — findings 1 through 5 need no writes at all, so you can check them against
> your own instance without letting anything of mine touch it. It writes a machine-readable
> result file and exits non-zero if any claim fails to reproduce.
>
> **On what I left out.** Three further behaviours were on my list and are not here. Two I
> could not measure, because the timeseries ingestion consumer on my instance had stalled
> (GMS returned HTTP 200 for writes that never landed) and I was not willing to report an
> artefact of a broken message bus as a property of DataHub. Three others I had written down
> earlier in the month and dropped after re-measuring: they did not reproduce, or reproduced
> differently enough that the original claim was wrong. I mention this only so you know the
> list has been filtered rather than dumped.
>
> Happy to open PRs. Several of these are one-liners and I would rather do the work than add
> to your backlog — just say which fix you prefer, particularly for (1), where "aggregate the
> scalar", "return null instead of 0" and "document that the field is inert" are all defensible
> and I do not want to guess.

---

## Before sending — checklist for Joel

- [ ] Decide public repo link vs. inline `curl` commands. Never link something unreachable.
- [ ] Check whether any of these already exist as issues upstream. If one does, comment on it
      with the measurement instead of opening a duplicate — a fresh reproduction on a current
      version is worth more on an existing thread than a new issue.
- [ ] File finding 06 on **`acryldata/mcp-server-datahub`**, the other five on the main
      DataHub repo. Do not mix the two.
- [ ] Re-run `harness/upstream_repro.py` on the day you file and update the "measured" date in
      each file if it has moved. Three of our own trap-list entries went stale inside a week;
      these can too.
- [ ] Files are English and self-contained. Nothing references our internal ticket numbers,
      lane names, or the hackathon.
