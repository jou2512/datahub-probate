Re-measured this today (2026-08-10) because we had **copied all three of these claims into our own
project notes as facts** and built decisions on them. All three no longer hold. Posting the numbers
here so the next person who finds this issue doesn't inherit them the way we did.

Measured with `uvx`, against a local DataHub OSS quickstart, on Windows / Python 3.11.

### 1. `@latest` no longer resolves to 0.4.0

| Invocation | Resolved version | Resolution time |
|---|---|---|
| `uvx mcp-server-datahub@latest` (no Python pin) | **0.6.0** | 8.74 s |
| `uvx --python 3.11 mcp-server-datahub@latest` | **0.6.0** | 12.4 s |

Both paths land on 0.6.0. Whatever pinned 0.4.0 at the time this issue was written is gone.

### 2. Mutation tools are present — they are off by default, not absent

| `TOOLS_IS_MUTATION_ENABLED` | Tools registered |
|---|---|
| unset (default) | **6** |
| `true` | **18** |

So **12 mutation tools** appear once the flag is set. Of the 18, 6 carry `readOnlyHint`. The
original report of "zero mutation tools" is consistent with running without the environment
variable — the tools are gated, not missing. That distinction matters: it turns "the server can't
write" into "the server won't write until you say so", which is a very different thing to build on.

### 3. The ~54 s per-call telemetry figure does not reproduce

Measured **0.315 s** of telemetry overhead per tool call. What *is* slow is **session start**:
**13.76 s cold, 9.4 s warm**. Across a small run — 4 tool calls, 1.893 s of tool time total,
9.661 s end to end — session start dominates everything else.

Our reading: the ~54 s was very likely session start being attributed to per-call cost. For an
agent that opens a session once and keeps it, the per-call figure is the one that matters, and it
is sub-second.

### Caveats, so this comment doesn't become the next stale fact

Small sample: 4–6 calls, one machine, one local single-node instance, one OS. The session-start
figures in particular say little about a long-lived session, and the end-to-end ratio is not a
throughput claim. Raw numbers and the probe that produced them are in a run artifact we're happy to
share if it's useful.

### Why we bothered

We're building a tool whose entire premise is *don't assert without evidence*, and we had these
three claims sitting in our own documentation, unmeasured, for five days — sourced from here. That
was our mistake, not this issue's. But the same numbers are still the first thing a search turns
up, so: measured, corrected, posted.
