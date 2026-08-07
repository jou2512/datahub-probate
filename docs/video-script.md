# Video script — Probate, under 3 minutes

*Draft. Nothing is recorded or published until Joel confirms.*
*Target runtime 2:55. Screen recording with voice-over, no face, no music bed under the demo.*

---

## Before you press record — the six preconditions

1. DataHub stack up, GMS answering on `http://localhost:28080`. **Never 18080, never 8080.**
2. Seed lab in place and green: `uv run --python 3.11 python harness/seed_lineage_lab.py`, then
   `seedlab_verdicts` exit 0. If the four states are not green, the demo is not filmable.
3. Workbench live: `uv run --python 3.11 python -m ui.serve --gms http://localhost:28080 --focus '<urn>'`,
   open `http://localhost:8899`. The mode badge must **not** read *Recording — no live instance*.
4. A second terminal, large font, ready with the `probate ledger --judge` command already typed.
5. Screen at 1920×1080, browser zoom such that all four panes are readable without scrolling.
6. A wall clock or an on-screen elapsed-time counter running for the whole take. It is what makes
   the sped-up waits verifiable rather than convenient.

## The timing facts this script is built on — read before shooting

Measured live, 2026-08-07. **These are not `claims.json` keys**; the third is backed by the
committed artifact `harness/runs/warehouse-cut-latency.json`, the first two are a live observation
from the same night.

| Button | Result | Time from press to visible state change |
|---|---|---|
| Declare an edge | edge appears as `dead` | ~20 s |
| Run a query | same edge turns `confirmed` | ~30 s |
| Disconnect warehouse | same edge turns `unknown`, `buckets_seen: 0` | ~2 s (a separate timing of the same transition: **1.309 s**) |

**The asymmetry is the shooting constraint and it must be stated out loud, not hidden.** Only the
usage path is fast. The first two transitions wait on DataHub's lineage index, and the camera
genuinely waits 20–30 s at each. Before tonight's fix the third was not observable at all at over
100 s.

Rule for the edit: **the third transition is filmed in one uninterrupted take.** The first two may
be sped up, and when they are, the screen carries a visible speed marker and a running elapsed
clock, and the voice-over says what was compressed. A juror who reproduces this will hit the same
wait; if the video implied it was instant, everything else in the submission becomes suspect.

---

## Shot list

Legend: **[E]** the shot can be filmed today with what exists · **[A]** needs an asset that does
not exist yet (listed at the end).

---

### 0:00 – 0:14 · The claim

**On screen [A]** Title card: `Probate — an agent that tests lineage instead of trusting it`,
below it in small type: *Build with DataHub — Agents That Do Real Work · Apache 2.0*. Hold 3 s,
then cut to the workbench at rest, all four panes visible.

**Spoken**
> DataHub tells you that table A feeds table B. It never tells you whether anyone has ever used
> that path. Every tool I could find takes usage data and uses it to weight edges it already
> believes. This one uses it to test the edge itself.

---

### 0:14 – 0:24 · The disclaimer, said out loud

**On screen [E]** Cursor moves over the *Measured* pane. Optionally a lower third [A]:
*seeded data — `probate_seedlab`*.

**Spoken**
> One thing before anything moves: all the usage data you are about to see is seeded. DataHub's
> sample catalog ships none — I wrote it myself, and every artifact in the repository says so.

*(Non-negotiable. This line stays in even if the video runs long.)*

---

### 0:24 – 0:47 · Transition 1 — declared, and immediately dead

**On screen [E]** Press **Declare an edge**. The live log writes a line. The camera stays on the
edge ledger. Speed the footage from the press to the state change to about ×6, with a visible
marker in the corner [A]: `×6 — waiting on DataHub's lineage index · elapsed 00:0X`. The edge row
appears carrying the chip `dead`.

**Spoken, over the wait**
> I declare a new lineage edge. It writes for real, through the same journalled path as the
> command line. Now the tool polls a live catalog, and DataHub's lineage index takes about twenty
> seconds to answer — I have sped that up, and nothing else in this shot is edited. There it is:
> declared, and no traffic in any window. The ledger says dead.

---

### 0:47 – 1:15 · Transition 2 — one real query, and it is confirmed

**On screen [E]** Press **Run a query**. Same treatment: speed marker and elapsed clock, ×6. The
*Measured* pane grows a bar. The same edge row flips to `confirmed` and its evidence expands to
show the query URN.

**Spoken, over the wait**
> Now one real query, touching two tables. Same wait, same reason, same speed-up — about thirty
> seconds this time. And the same edge is now confirmed, with the query URN carried along as the
> evidence. That URN is the difference between a verdict and an opinion.

---

### 1:15 – 1:34 · Transition 3 — the one that carries the demo, uncut

**On screen [E]** **No speed change, no cut, no overlay.** Press **Disconnect warehouse**. Hold
the frame on the edge ledger. Roughly two seconds later the chip changes from `confirmed` to
`unknown`, and the coverage line above the results reads `buckets_seen: 0`.

**Spoken**
> Now I take the usage data away. Watch what does *not* happen.
>
> *(beat — let the state flip on its own)*
>
> It does not become dead. It becomes unknown. We stopped being able to look, so we stop making a
> statement. That distinction is the entire product. The version of this tool that came before
> collapsed those two cases into one empty list and called the result harmless — which is exactly
> how a confident tool overwrites a table that somebody is still reading.

**Camera note:** this take is not sped up and must not be. If the state change lands slower than
about three seconds, reshoot — do not cut.

---

### 1:34 – 1:47 · The date

**On screen [E]** Expand the timeline on a `dead` edge from the seed lab. The row shows last
covered, days since, and the per-bucket series.

**Spoken**
> And it is not just dead. It is dead since a date, from the measurement itself, not from the
> moment I pressed a button. That is the difference between a check and a record.

---

### 1:47 – 2:08 · Where the model sits, and where it is overruled

**On screen [E]** Cut to the terminal. Run:

```
uv run --python 3.11 probate ledger --focus '<urn>' --judge --judge-limit 5
```

Let the JSON scroll and stop on a `judgements` block. Highlight `quote`, `source_field`,
`used_model`. Then scroll to the edge where `used_model: false` and
`fallback_reason: "kein Zitat geliefert"`.

**Spoken**
> There is exactly one model call in this project, and this is it: the model judges which
> deviation matters — that is judgement over description, owners, glossary terms. It works under a
> citation duty. No verbatim quote from what it read, no judgement, and the deterministic finding
> stands. Here it quoted. Here it did not, and it was overruled by its own rule. I am showing you
> that one rather than hiding it, because a rule that never fires is not a rule.

**Asset note [A]:** the workbench does **not** render the model's quote — `ui/werkbank.js` renders
the timeline, not the judgement. This shot has to be the terminal or the raw artifact
`harness/runs/judge-seedlab-matrix.json`. If the citation is wanted inside the UI, that UI does not
exist yet.

---

### 2:08 – 2:29 · Proposal, human, journal, reverse gear

**On screen [E]** Terminal, three commands in sequence, output visible each time:

```
uv run --python 3.11 probate propose --ledger harness/runs/ledger.json
uv run --python 3.11 probate correct --edge '<a>-><b>' --kind add_edge          # dry run, writes nothing
uv run --python 3.11 probate correct --edge '<a>-><b>' --kind add_edge --confirm
uv run --python 3.11 probate revert
```

Show the journal line appearing, then the revert output naming the number of writes undone.

**Spoken**
> Correcting the catalog is the second half. Proposal, human confirmation, journal entry, reverse
> gear. `propose` writes nothing at all. `correct` is dry-run by default — a bare invocation cannot
> touch the catalog. And `revert` undoes every write of the session, including deleting aspects
> that did not exist before, rather than writing back an invented empty value.

---

### 2:29 – 2:43 · The load test, including the part that failed

**On screen [E]** `harness/runs/loadtest_s.json` and `loadtest_m.json` side by side, or the
README's load-test table on screen. Highlight the two rows.

**Spoken**
> Ten times the catalog: the cheap pass grows with it, one and a quarter seconds to twelve. Same
> cost per table either way, one call each, and it does not care that the query volume also grew
> ten-fold. What this test does *not* show is the saving from the second stage — our seeded tables
> all look suspicious to it, so it has nothing to filter. That is in the README as a limitation,
> not a footnote. Stage L never finished seeding, and that row is published as an abort.

*(Numbers spoken here: 1.235 s and 12.238 s, both audited `claims.json` keys. Derived and safe if
you prefer them: 0.0247 vs 0.0245 s per dataset, 93 response characters per call at both scales.
**Do not say "forty-one suspicious edges" and do not claim the two-stage saving.** Measured: the
flag rate is 100 % at both scales — 50 of 50 at S, 500 of 500 at M
(`loadtest_s_coarse_suspicious` / `loadtest_m_coarse_suspicious`) — because the fixtures never
populate `statsSummary`. The 41 is a hardcoded `detail_sample` cap. An earlier draft of this script
claimed the saving; it was wrong, and it is exactly the kind of claim this project loses
credibility by making. **Also do not call the per-edge time "comparable"** — it rose 32.6 % from S
to M on an identical sample and is on the record as unexplained.)*

---

### Optional insert A · The MCP server — highest priority of the two inserts

**If exactly one insert fits, it is this one.** Seven simulated jurors asked "where is the Agent
Context Kit". Fifteen seconds that answer it with a measurement outrank any other fifteen seconds
available. It is *not* in the base cut only because the cut has no slack — not because it ranks
below anything.

**Where to find the room if Joel wants it in the base cut:** the propose/correct/revert shot at
2:08–2:29 runs 21 s and compresses to about 14 s by cutting the dry-run demonstration and keeping
`propose` → `correct --confirm` → `revert`. That is the cheapest 7 s in the script.

**On screen [E]** Terminal, run the same ledger twice, once per transport:

```
uv run --python 3.11 probate ledger --focus '<urn>' --cooccurrence-source graphql
uv run --python 3.11 probate ledger --focus '<urn>' --cooccurrence-source mcp
```

Put the two verdict blocks side by side. Then cut to `harness/runs/mcp-probe.json`.

**Spoken**
> And we do not only read this over GraphQL. The same reconciliation, once through DataHub's own
> MCP server — same verdict, every edge. What it costs and where it stops is a file in the repo:
> nine seconds of session start, one call instead of N, and no timestamps on query entities, which
> is why the age judgement stays on GraphQL. We did not assert that. We measured it and shipped the
> measurement.

**Two things not to say.** Do not say "MCP is 130× slower" — that is session start, not throughput.
And do not claim the age judgement works over MCP; it does not, and the file says why.

---

### Optional insert B · Full run vs. daily delta — only if the cut runs short

**Decision: this is NOT in the base cut, and it ranks below insert A.** The measurement is strong —
74.87× at S, 17.11× at M,
and a 1.377 s delta pass over a 500-table catalog (`full-vs-delta.json`, all audited keys). But the
ratio is meaningless without its definition: the "daily delta" is the newest **2 %** of the plan
list, a proxy for "changed since the last marker", because the fixtures carry no write timestamp.
Saying the ratio without the proxy takes about eight seconds; saying it *with* the proxy takes
closer to fifteen, and the cut has neither. **A spoken ratio without its definition would be worse
than silence** — so the base cut stays silent and the README carries it.

If a take comes in short and there are 12+ free seconds, use this and nothing shorter:

**On screen [E]** `harness/runs/full-vs-delta.json`, or the README's full-vs-delta table.

**Spoken**
> One number decides whether this is usable daily: a full check of a five-hundred-table catalog
> takes twenty-three seconds, the incremental pass one-point-four. That incremental set is the
> newest two percent of the catalog, standing in for "changed since last run" — our seeded tables
> have no write timestamp to filter on, and with no marker at all the tool runs the full check and
> says so.

**Forbidden shortening:** dropping the last sentence. Without it this becomes a benchmark with an
undisclosed denominator, which is the exact failure the rest of the video is about.

---

### 2:43 – 2:55 · Close

**On screen [E]** Scroll the README to *Honest limitations*, let two or three bullets be readable.
Then cut to the end card [A]: repository URL, `Apache 2.0`, and the line *All usage data in this
video is seeded.*

**Spoken**
> Seeded data. No real warehouse ever connected. A watcher whose re-evaluation I could not show
> changing a verdict. It is all in the README, because a tool that says "assert nothing without
> evidence" does not get to make an exception for itself.

---

## What has to exist before this can be filmed

**Exists today [E]** — the workbench in live mode, all six buttons writing for real, the three
transitions, the timeline expansion, `probate ledger --judge` with its citation output, the
propose/correct/revert round trip, all load-test artifacts, the README.

**Does not exist yet [A]** — every one of these is a make-it, not a find-it:

| # | Asset | Note |
|---|---|---|
| 1 | Title card (name, track, licence) | 3 s still, must not use a gradient header or centred-everything layout — the same design rules apply as to the UI |
| 2 | End card (repo URL, Apache 2.0, seeded-data line) | 5 s still |
| 3 | Speed marker + elapsed clock overlay | needed twice, for the ~20 s and ~30 s waits; the whole honesty of those two shots hangs on it |
| 4 | Lower third *seeded data — `probate_seedlab`* | optional; the spoken line is the mandatory part |
| 5 | The recording itself, against a live stack | the software exists; the footage does not |
| 6 | A UI view of the model's quote | **does not exist and is not planned** — `ui/werkbank.js` shows the timeline only. The script routes around it via the terminal. Do not promise it in the submission |

**One risk to check on the day of shooting:** `ui/` is under active change. The button labels this
script names — *Run a query · Declare an edge · Remove an edge · Disconnect warehouse ·
Fast-forward time · Run full check* — are the current ones. Re-read them from `ui/werkbank.html`
before recording the voice-over, not after.

## Two things that must be said out loud, in any cut

1. **The data is seeded.** (0:14)
2. **The waits are real and the footage was sped up, and nothing else was edited.** (0:24, restated
   at 0:47)

Everything else in this script can be shortened. These two cannot.
