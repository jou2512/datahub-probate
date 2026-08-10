# Video script — FINAL, shooting version

*Read this one, not `docs/video-script.md`. That draft is superseded: it measured **709 spoken
words = 4:43** at 150 wpm (3:48 even without its two optional inserts), and it describes a console
that no longer exists — "four panes" and six loose buttons, from before the enterprise-console
rebuild. Both problems are fixed here.*

**Measured length of this script: 394 spoken words** (main cut, excluding the optional insert). At
**150 words per minute** — a calm, clearly-articulated English pace, the assumption this whole
budget rests on — that is **2:38 of speech**, plus one deliberate 3-second silent beat and a
3-second end-card hold: **2:44 total**, inside the 2:45 target and 16 seconds inside the hard 3:00
limit. If you read faster than 150 wpm you gain slack; you cannot lose it. Every section heading
below carries its own measured word count, so you can see where the slack is if a take runs long.

**Why this order.** Benefit first. A juror watching submission number sixty decides in fifteen
seconds whether to keep watching. So the first sentence is not what the tool *is*, it is what it
*found*: 73 dead connections out of 513, with dates. Method comes after the payoff, never before.

---

## Before you press record — preconditions

1. DataHub stack up, GMS answering on `http://localhost:28080`. **Never 18080, never 8080.**
2. Seed lab green: `uv run --python 3.11 python harness/seed_lineage_lab.py`, then
   `uv run --python 3.11 python harness/seedlab_verdicts.py` must exit 0. If the four states are not
   green, the demo is not filmable.
3. Console up: `uv run --python 3.11 python -m ui.serve` → open
   **`http://127.0.0.1:8899/werkbank.html`**. No flags needed.
4. **Check the sidebar `mode` badge reads `live`, not `recording`.** If it says `recording`, the
   proxy is not reaching GMS and every shot below is a lie.
5. Press the blue **Run check** button in the top bar once and let it finish, so the Overview cards
   carry real numbers before the take starts.
6. In **Connections**, type the demo target table's name into the **Search** box and leave it there.
   Filters live in JS state and survive switching views (`showView` only toggles `hidden`), so this
   filter stays set for the whole take — you do not retype it.
7. Second terminal ready, large font, two commands pre-typed but **not** run:
   `probate ledger --focus '<urn>' --judge --judge-limit 5` and
   `uv run --python 3.11 python harness/audit_claims.py`.
8. Screen 1920×1080. Browser zoom so the Overview cards are readable without scrolling.

**One honesty rule for the edit:** the 0:44 shot is filmed in **one uninterrupted take, no
speed-up**. Nothing else in this cut waits on DataHub's lineage index, which is why the slow
transitions (~20–30 s) are not filmed at all any more — they are shown as an artifact at 1:17
instead. Nothing in this video is sped up, so nothing needs a speed marker.

---

## The cut

Legend: **[E]** exists today · **[A]** an asset you must make (all listed at the end).

---

### 0:00 – 0:13 · The payoff (34 words, 13.6 s)

**On screen [E]** Open on the **Overview** pane, already loaded. The four KPI cards fill the top:
*Confirmed 266 · Dead 73 · Missing 29 · Not judged 145*, over 513. Do not click anything. Let the
cursor rest, then slowly drag it across the **Dead 73** card as you say the number.

**Spoken**
> This catalog has six hundred eighteen tables, and claims five hundred thirteen connections
> between them. Nobody ever re-checks those claims. Probate just did — seventy-three of them are
> dead, and it says since when.

---

### 0:13 – 0:25 · The disclaimer, out loud (29 words, 11.6 s)

**On screen [E]** Scroll up one notch so the yellow **seeded note** under the top bar is readable.
Cursor rests on it.

**Spoken**
> One thing before anything moves: every bit of usage data here is seeded. DataHub's sample catalog
> ships none. I wrote it, and every artifact in the repo says so.

*(Non-negotiable. This line stays in even if the take runs long.)*

---

### 0:25 – 0:44 · One dead edge, and its receipt (49 words, 19.6 s)

**On screen [E]** Three clicks, slowly:
1. Click **Connections** in the left sidebar.
2. Click the **Dead** chip in the verdict filter row.
3. Click any dead row. The detail panel opens on the right.

Hold on the detail panel. Point the cursor at **Last measured**, then at the per-bucket series.

**Spoken**
> Here's one of the dead ones. The catalog declares it. In thirty-three days of usage windows, not
> one query touched both tables. Last covered is a date — taken from the measurement, not from the
> moment I pressed a button. That's the difference between a check and a record.

---

### 0:44 – 1:17 · The flip that carries the demo — UNCUT (75 words, 30 s + 3 s beat)

**On screen [E]** This is the shot. No cut, no speed change, no overlay.

1. In **Connections** (search filter still set from precondition 6), click the demo target row —
   it reads **Confirmed**. Say the first two sentences here.
2. Click **Overview** in the sidebar.
3. In the card *What you can do to this catalog*, click the **Disconnect** button on the row
   *"Disconnect the warehouse — deletes the usage timeseries on the demo target"*.
4. **Hold the frame.** The Live log at the bottom writes a line. Say *"Watch what does not happen"*,
   then **stay silent for three seconds.**
5. Click **Connections** again. The same row now reads **Not judged**.

**Spoken**
> Now the one that matters. This edge is confirmed — real measured traffic. I'm taking its usage
> data away. Watch what does not happen.
>
> *(silent beat — 3 s, let the state land)*
>
> It did not become dead. It became not-judged. We stopped being able to look, so we stop making a
> statement. Every other tool I found calls that dead and invites you to delete the table. And that
> button wrote to a live catalog — same journalled path as the command line.

**Camera note:** this transition measured ~2 s live and 1.309 s in
`harness/runs/warehouse-cut-latency.json`. If it lands slower than about three seconds, **reshoot —
do not cut.** A cut here destroys the only claim the video cannot make any other way.

---

### 1:17 – 1:36 · Seven of seven, proven (46 words, 18.4 s)

**On screen [E]** Click **Runs** in the sidebar and let the run rows be readable for two seconds,
then cut to `harness/runs/demo-transitions.json` open in the editor, scrolled so
`"transitions_attempted": 7`, `"transitions_proven": 7`,
`"transitions_journal_lines_added": 3` and `"transitions_journal_lines_reverted": 3` are all on
screen at once.

**Spoken**
> Four states existing is easy. An edge moving between them when the world changes is the actual
> claim — so we measured it instead of describing it. Seven transitions attempted, seven proven,
> every one written to a live catalog and taken back in the same run.

---

### 1:36 – 2:01 · The model, and where it gets overruled (64 words, 25.6 s)

**On screen [E]** Cut to the terminal. Run the pre-typed command:

```
uv run --python 3.11 probate ledger --focus '<urn>' --judge --judge-limit 5
```

Let the JSON settle on a `judgements` block. Highlight `quote` and `source_field` on one edge, then
scroll to the edge carrying `"used_model": false` and
`"fallback_reason": "kein Zitat geliefert"` and leave it on screen while you finish the line.

**Spoken**
> There's exactly one model call in this project: judging which deviation matters. It runs under a
> citation duty — no verbatim quote from the metadata it read, no judgement, and the deterministic
> finding stands. Here it quoted. Here it did not, and it was overruled by its own rule. I'm
> showing you that one, because a rule that never fires is not a rule.

**Do not** try to show this in the console. `ui/werkbank.js` renders the timeline, not the
judgement — the quote exists only in the CLI output and in
`harness/runs/judge-seedlab-matrix.json`. This is a known, documented gap; routing around it is
correct, promising a UI for it is not.

---

### 2:01 – 2:23 · The gate under everything (55 words, 22 s)

**On screen [E]** Same terminal. Run:

```
uv run --python 3.11 python harness/audit_claims.py
```

Let it scroll. **Stop on the last line** — `Alle 140 Zahlen decken sich mit den Laeufen.` — and
leave it up. Then cut to the README's *"Three things we believed, published, and then disproved by
re-measuring"* table and let the three rows be readable.

**Spoken**
> Every number you just saw sits under a gate. This script re-derives all one hundred and forty of
> them from the committed run artifacts, and exits one on any drift. It runs offline, with no
> DataHub instance. We ran it against ourselves and lost — including three claims we'd published
> about DataHub's own MCP server.

---

### 2:23 – 2:43 · Close (42 words, 16.8 s + 3 s card hold)

**On screen [E]** Scroll the README to *Honest limitations*, let two or three bullets be readable.
Then cut to the end card **[A]**: repository URL, `Apache 2.0`, and the line
*All usage data in this video is seeded.* Hold 3 s.

**Spoken**
> Seeded data. No real warehouse ever connected. A watcher whose re-evaluation I could not show
> changing a verdict. All of it is in the README — because a tool that says "assert nothing without
> evidence" does not get an exception for itself.

---

## If a take comes in short — the one insert worth adding

**Only this one, and only if you have 15+ free seconds.** Simulated jurors repeatedly asked "where
is the Agent Context Kit". Fifteen seconds answering that with a *measurement* outranks anything
else available. Slot it between 2:01 and 2:23.

**On screen [E]** Terminal, the same ledger run twice, once per transport:

```
uv run --python 3.11 probate ledger --focus '<urn>' --cooccurrence-source graphql
uv run --python 3.11 probate ledger --focus '<urn>' --cooccurrence-source mcp
```

Two verdict blocks side by side, then cut to `harness/runs/mcp-probe.json`.

**Spoken** (34 words ≈ 14 s)
> We read this over DataHub's own MCP server too — same verdict, every edge. What it costs and
> where it stops is a file in the repo: nine seconds of session start, and no timestamps on query
> entities.

**Two things not to say.** Never "MCP is 130× slower" — that is session start, not throughput. And
never claim the age judgement works over MCP; it does not, and the artifact says why.

---

## Numbers spoken in this cut — all audited, all safe

| Spoken | `claims.json` key | Value |
|---|---|---|
| 618 tables | `demo_ledger_tables` | 618 |
| 513 connections | `demo_ledger_edges_total` | 513 |
| 73 dead | `demo_ledger_edges_dead` | 73 |
| seven attempted, seven proven | `transitions_attempted` / `transitions_proven` | 7 / 7 |
| 140 numbers | count of `claims.json` keys | 140 |
| nine seconds session start *(insert only)* | `mcp_session_boot_seconds_warm` | 9.4 |

**Forbidden in any cut:** "forty-one suspicious edges" (a hardcoded `detail_sample` cap, not a
finding) · any claim of the two-stage cost saving (measured flag rate is 100 % at both scales) ·
calling the per-edge detail time "comparable" (it rose 32.6 % from S to M, unexplained) · any
full-vs-delta ratio without its 2 % proxy definition (which does not fit in this cut, so the ratio
stays out entirely).

---

## Assets to make before shooting

| # | Asset | Note |
|---|---|---|
| 1 | End card: repo URL · `Apache 2.0` · *All usage data in this video is seeded.* | 3 s still. The only required asset. |
| 2 | Title card | **Dropped on purpose.** A title card costs 3 s at the exact moment a juror decides to keep watching. The name and licence are on the end card and in the Devpost form. |
| 3 | Speed-marker overlay | **No longer needed** — nothing in this cut is sped up, because the two slow transitions were cut and replaced by the artifact shot at 1:17. |
| 4 | A UI view of the model's quote | **Does not exist and is not planned.** The script routes to the terminal. Do not promise it in the submission. |

**Check on the day:** re-read the five action-row labels from `ui/werkbank.html` before recording
the voice-over. They are currently *Declare · Run · Disconnect · Remove · Move*, with the full
sentence in the row text beside each. The `unknown` verdict is labelled **Not judged** in the UI —
say "not-judged", not "unknown", so the words match the screen.

## Two things that must be said out loud, in any cut

1. **The data is seeded.** (0:13)
2. **`unknown` is not `dead`** — the 0:44 shot. If only one thing survives, it is this one.
