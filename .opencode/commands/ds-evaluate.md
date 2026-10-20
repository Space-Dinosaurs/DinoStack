---
description: "/ds-evaluate"
agent: build
---
# /ds-evaluate

> Run the Activation preflight from `METHODOLOGY.md` before proceeding. If inactive, no-op and exit.

<!--
Purpose: Evaluate the methodology's effectiveness against the North Star pillars over a time
         window, and end with ranked methodology-refinement proposals, each naming its evidence
         figure and the route it goes to. Reads the pillar text LIVE from the DinoStack checkout's
         docs/overview/vision.md at runtime (never hardcoded), runs bin/ds-evaluate (the
         deterministic signal collector, over bin/_eval.py) for measured telemetry, spawns parallel
         per-pillar scoring subagents, writes a date-stamped report, and offers the operator up to
         5 samples per D2-flagged hook to label via ds-feedback.

Public API: /ds-evaluate [window] (conductor-invoked). One optional window argument: `Nd` (e.g.
            `14d`) or an ISO8601 date; default `30d`. Reads vision.md and the bin/ds-evaluate
            report; writes docs/planning/ds-evaluate-YYYY-MM-DD.md and, only for operator-labelled
            samples, ds-feedback items carrying a fire_label.

Upstream deps: docs/overview/vision.md (North Star pillar text); bin/ds-evaluate (signal collector);
               scripts/lib/repo-dir.sh (resolve_repo_dir); bin/ds-feedback (fire labels);
               METHODOLOGY.md (activation preflight); the operator's telemetry files (read by the
               collector).

Downstream consumers: build-all.sh (regenerates this command into all 11 adapter dirs); the operator,
                      who reads the conductor-presented digest and docs/planning/ds-evaluate-YYYY-MM-DD.md.

Failure modes: scores and proposals are advisory, never a gate. Sparse telemetry degrades to a
               finding or a telemetry gap, never a false 0. Self-report bias when a scoring model evaluates the methodology it runs under
               is mitigated by Step 3's non-dominant-model guidance.

Performance: one deterministic collector run plus N parallel lens spawns (N = number of pillars),
             each ~15 tool calls. Negligible at the intended cadence.
-->

Evaluates the methodology's effectiveness against the North Star pillars over a time window, and ends with ranked refinement proposals the operator can route. The conductor runs a deterministic signal collector (`bin/ds-evaluate`) over the current project's telemetry, spawns one parallel scoring subagent per pillar, merges the verdicts into a per-pillar scorecard, and closes with the proposals, the telemetry gaps, and an optional labelling pass over flagged hook denies. The pillar text is read LIVE from the DinoStack checkout's `docs/overview/vision.md` at runtime - it is never hardcoded here, so a pillar edit needs no command change.

**When to use:** periodically, after a methodology change, or when the operator wants to see what is working and what to refine, grounded in measured signals rather than impression. Run it from the project whose telemetry should be evaluated (its primary checkout - hook spawn rows land there, not in a linked worktree).

**Do not use to:** categorize failure modes per model/harness (use `/ds-failure-audit`), count tokens (use `/ds-cost`), or gate a merge - the scores are advisory by design.

## Positioning: the effectiveness-per-pillar axis

The methodology already measures three axes of agent work; this command adds the fourth:

| Axis | Command / tool | What it measures |
|---|---|---|
| Cost | `/ds-cost` (`bin/ds-cost`) | token and wall-time rollups per agent/session/task from `.agentic/events.jsonl` |
| Friction-to-skill | `/ds-skill-candidates` | recurring workflow-friction domains (lifetime counts, accumulate >= 3) |
| Failure modes | `/ds-failure-audit` | failure modes per model/harness with quantified frequency |
| **Pillar effectiveness** | **`/ds-evaluate`** | **methodology effectiveness against the North Star pillars, per pillar** |

This command is the effectiveness-per-pillar axis, alongside `/ds-failure-audit` (failure modes per model/harness), `/ds-skill-candidates` (friction-to-skill), and `/ds-cost` (tokens). It reuses their telemetry via the deterministic collector and cross-references them - it does NOT re-implement failure-mode categorization, friction-to-skill detection, or token rollups. `/ds-failure-audit` answers "which model/harness failed, how often, in what way"; `/ds-skill-candidates` answers "what workflow friction recurs"; this command answers "how well does the methodology serve each North Star pillar".

## Step 1 - Activation preflight

Run the Activation preflight from `METHODOLOGY.md`. If inactive, no-op and exit.

## Step 2 - Signal collection

Write the window into the command below in place of `<window>`: the command's argument when one was given (`14d`, `30d`, or an ISO8601 date), else `30d`. `REPO_DIR` is the DinoStack checkout, resolved by `resolve_repo_dir` from `scripts/lib/repo-dir.sh`; the first line only locates that library through the same config file the resolver reads. The telemetry repo is the current project's git toplevel.

```bash
AE_BOOT="$(python3 -c 'import json, os; print(json.load(open(os.path.expanduser("~/.agentic/agentic-engineering-config.json"))).get("repo_dir", ""))' 2>/dev/null)"
REPO_DIR=""
. "${AE_BOOT:-$HOME/DinoStack}/scripts/lib/repo-dir.sh" && resolve_repo_dir --quiet && REPO_DIR="$AE_REPO_DIR"
if [ -z "$REPO_DIR" ]; then
  echo "ds-evaluate: cannot resolve the DinoStack checkout (repo_dir in ~/.agentic/agentic-engineering-config.json, else ~/DinoStack) - nothing was evaluated" >&2
  false
else
  "$REPO_DIR/bin/ds-evaluate" --repo "$REPO_DIR" --telemetry-repo "$(git rev-parse --show-toplevel)" --since <window>
fi
```

A "cannot resolve the DinoStack checkout" line means the collector never ran: report that as a collector failure (see Edge cases), never as an empty result.

The report (stdout) is the single measured-signal input to every pillar lens; pass it verbatim to each lens. It opens with the proposal and gap counts, then the window and one line per transcript store, the measured sections (`[cost]`, `[agents]`, `[skeptic_rounds]`, `[work_items]`, `[hooks]`, `[mix]`), the DinoStack checkout's `[methodology]` signals (budget gates, resident floor, vision pillars), and ends with `Refinement proposals` and `Telemetry gaps` (Steps 5-6). Data-quality rules - state them in the report rather than "fixing" the numbers:

- **Every metric carries a status:** `OK`, `PARTIAL` (a named source or sample is incomplete, with its coverage) or `ABSENT` (no input, value null). An ABSENT figure is an absence of data, never a measurement of 0 - the report must say so.
- **Every figure is window-scoped:** sessions, spawns, hook denies and dollars count only the window; never present one as an all-time or per-session figure.
- **Dollars are reconciled, not summed tokens:** `[cost]` reconciles against the harness's own cost-state; sessions with no cost-state are a separate group, reported PARTIAL rather than folded into the total. Empty sessions (no usage record and no cost-state spend: the cost-state record is absent or $0) are counted on the `reconciled` and `no_cost_state` lines and left out of coverage: they add no dollars.
- **`by_iteration` has two coverages:** iteration-tagged (returns carrying an iteration) and findings-carrying (returns carrying `signed_off` or `findings_count`). A high first and a low second means the rounds are counted but most verdicts are not recorded - do not read yield from it.
- **`[work_items]` lists the top 10 keyed items by priced cost**, with one summary line. `spawn wall` is summed spawn time, not end-to-end duration, and `n/a (<reason>)` is an absent figure, never 0. `PR outcome` is the first of these that applies: `n/a (no merged-PR history)` (the base ref is unreadable); `merged #N`, with `, K follow-up` and `, reverted` when they apply (a PR merge in the window or its 7-day lookahead, by ticket id, key PR or the item's own PR); `merged #N (before window)` or `merged #N (after window)` (a PR commit on the base ref at another date); `no PR merge found (ticket id mentioned in K base commit(s))` (no PR commit, but K first-parent commits on the base ref carry the ticket id - a mention, not a landing); `no merge found in window (wider base history unreadable)` (the undated search failed); and `no merge found` (the base ref's first-parent history has neither the item's PR number nor its ticket id). None of them is a statement that the PR is unmerged. Each then gains `, H changes-requested` when gh shows H >= 1 CHANGES_REQUESTED reviews on the item's PRs, or `, changes-requested n/a (gh unavailable)` when gh is disabled, missing or failed or does not list one of those PRs, never 0. H counts reviews from any author, including automated ones such as `/ds-review-pr`, which posts from the operator's account, so it is not a count of human rejections.

If the collector fails or prints no report, treat the invocation as a sparsity finding (see Edge cases) - never proceed with an invented signal baseline.

## Step 3 - Pillar-lens scoring

Extract the North Star pillar list from the DinoStack checkout's `docs/overview/vision.md` (the "North Star" section; the report's `[methodology]` line names that checkout) at runtime. Spawn ONE `investigator` subagent per pillar, in parallel (background), each briefed with:

- the pillar's verbatim text (from the live vision.md read in this invocation - never from memory)
- the Step 2 report verbatim
- the compact verdict contract below
- every section of that brief that the conductor composes is a slot per `content/references/subagent-protocol.md` §11 Output Expectations, "**Brief section form**"

Prefer a non-dominant model for at least one lens (self-report bias mitigation, mirroring `/ds-failure-audit` Step 2). If the operator has only one model, run all lenses under it and note the bias in the report.

Keep the brief contract compact - this command's output is a report, not a PR. Each lens returns a structured verdict:

- **score:** 1-5 (5 = the methodology fully serves this pillar)
- **evidence:** the report figures (section and metric) that ground the score
- **gaps:** concrete weaknesses against this pillar
- **action:** ONE candidate action that would most improve this pillar's score

## Lens brief (verbatim - compact contract)

"Score the dinostack methodology against this North Star pillar. Read the pillar text and the signal report provided, and return a structured verdict: score (1-5), evidence naming the report figures used, gaps, and ONE action candidate. Ground every score in the signals; an ABSENT figure is missing data, not a 0, and where the report does not cover a pillar, say 'insufficient data' instead of inventing a score. You are producing a report input, not a PR - keep the verdict to a few paragraphs."

## Step 4 - Synthesis

After the lenses return, the conductor:

1. Merges the verdicts into a per-pillar scorecard.
2. Writes the report to `docs/planning/ds-evaluate-YYYY-MM-DD.md` (gitignored - never committed).
3. Returns a compact digest inline that leads with the refinement proposals (Step 5), then the per-pillar scores and the top action candidate.

## Step 5 - Refinement proposals

Present the report's `Refinement proposals` verbatim and in its order - it is `bin/_eval.py`'s Decision rules order (priced proposals by `rank_usd` descending, then unpriced ones by evidence count descending); never re-rank or drop one. Each line names the rule (D1a-D3), subject, evidence figure, value and count, `rank_usd` (or `unpriced`), and route. Name the route as the operator acts on it:

| Route | Where it goes |
|---|---|
| `update-agentic-engineering` | `/ds-update-agentic-engineering` (a methodology change: Skeptic round shape, D1a-D1c) |
| `prune-harness` | `/ds-prune-harness`, which applies its own floor-vs-dial pre-filter, so a floor hook is excluded there (D2) |
| `tracker-ticket` | a ticket in the project tracker, filed only on operator approval, as in `/ds-feedback-triage` (D3) |

No route is taken without the operator. `none` means no rule fired in the window.

## Step 6 - Telemetry gaps

Then list the report's `Telemetry gaps`: each input metric that was ABSENT or PARTIAL and the rules it disables (`blocks`). A gap has no route and no rank and is never a proposal; it says which rule could not be evaluated, not that the rule passed.

## Step 7 - Label flagged hook denies

For each D2 proposal that lists label samples, ask the operator ONE question per hook: a plain prose message that lists the hook's samples numbered from 1 (up to 5, each with its `ts` and reason) and asks for FP (false positive), TP (true positive) or skip per sample, plus an optional note:

```
enforce-x - label each deny: FP (it should not have fired), TP (it was right to fire), or skip.
  1. 2026-10-03T09:55:00Z  "reason text"
  2. 2026-10-03T09:50:00Z  "reason text"
Reply like "1 FP, 2 TP, 3 skip"; add a note after any answer if you want one recorded.
```

Ask in prose only. Never use a multiple-choice question tool for this, and never mark, order or word any answer as recommended or default: a suggested answer biases the labels, and five per-sample answers do not fit one single-select question. A sample the reply does not mention is a skip. A hook with no samples gets no question.

Write every FP or TP answer from this run in ONE `ds-feedback append` batch; a skipped sample writes nothing, and when every answer is skip, do not call `ds-feedback` at all. One draft per labelled sample:

- `category` `guardrail-fire`, `scope` `methodology`, `severity` `low`
- `evidence`: the sample's reason (`-` when the reason is empty)
- `suggested_title`: `fire label <hook> <verdict>`, where `<verdict>` is `false_positive` or `true_positive`
- `suggested_body`: the operator's note, or `-`
- `fire_label`: `{"hook": "<hook>", "fire_key": "<fire_key>", "fire_ts": "<ts>", "verdict": "<verdict>"}`

Use the repo printed on the samples line as `--repo` - `ds-eval` matches a label to its deny by that exact path. Write the drafts array into the heredoc in place of the placeholder:

```bash
LABELS_TMP="$(mktemp "${TMPDIR:-/tmp}/eval-labels.XXXXXX")"
cat > "$LABELS_TMP" << '__EVAL_LABELS_JSON__'
[...the drafts array...]
__EVAL_LABELS_JSON__
ds-feedback append --repo "<repo from the samples line>" --session-uuid "${CLAUDE_CODE_SESSION_ID:-unknown}" --file "$LABELS_TMP"
```

A labelled item is born `triaged`, so `/ds-feedback-triage` never lists it; the next `ds-eval` or `/ds-evaluate` run counts it in `hooks[<hook>].labelled`.

## Report template

```
# /ds-evaluate - YYYY-MM-DD

## Signals
- Window: [start .. end], telemetry repo, stores
- Caveats: [ABSENT/PARTIAL figures used, stated if used]

## Per-pillar scorecard

| Pillar | Score (1-5) | Evidence | Top gap | Action candidate |
|---|---|---|---|---|

## Refinement proposals
[the report's proposals verbatim, in order: rule, subject, evidence figure = value, n, rank_usd or unpriced, route]

## Telemetry gaps
[the report's gaps verbatim: input, status, blocks - no route, no rank]
```

## Edge cases

- **Signal sparsity:** insufficient data is a finding ("not enough telemetry to score this pillar"), never a false 0. A lens that cannot ground its score in the signal rollup says so, and the scorecard marks the pillar unrated.
- **Collector failure:** if `bin/ds-evaluate` errors or prints no report, the report records the failure as a finding and stops - it does not proceed with fabricated signals.
- **Not inside a git checkout:** `git rev-parse --show-toplevel` prints nothing, and `bin/ds-evaluate` exits 2 on the empty `--telemetry-repo`; run the command from the project's checkout.

## Non-goals

- **Raw-transcript mining is OUT of scope** - the same stance as `/ds-failure-audit`. If a gap needs transcript-level evidence, the report flags it as such rather than expanding its own read scope.
- **Scores are advisory** - no gate, no required status check. The report informs; it does not block.
- **On-demand, not CI-wired** - this is the first cut. Wiring `/ds-evaluate` into CI is a deliberate future decision, not a requirement of this command.

## Risks and failure modes

- **Self-report bias (primary):** a lens scoring the methodology it runs under may rate its own host generously. Mitigated by Step 3's non-dominant-model guidance for at least one lens.
- **Hardcoded-pillar drift:** if pillar text were pasted into a lens brief from memory instead of read live, a vision.md edit would silently desync the report. This command always reads `docs/overview/vision.md` in the same invocation.
- **Signal sparsity:** thin telemetry makes scores noisy. The report must state per-pillar signal coverage so the operator can judge confidence.
- **Over-precision:** a score with a single weak evidence item reads as more certain than it is. Lenses report evidence first, score second, and mark small samples explicitly.
