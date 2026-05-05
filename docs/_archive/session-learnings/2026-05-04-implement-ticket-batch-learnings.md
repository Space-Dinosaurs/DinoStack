# /implement-ticket learnings — batch session 2026-05-04

Generic, project-agnostic learnings from a 12-ticket batch. To be folded into `~/agentic-engineering/content/commands/implement-ticket.md`. Polished after QA closes; this is the raw capture.

---

## 1. QA gaps (highest-impact category)

### 1.0. QA is PER-TICKET, in-flow — NOT batched at the end (most important)

**Protocol-correct flow (per ticket):**
```
architect → skeptic-on-plan → engineer → skeptic-on-diff → QA → quality-gate → commit → PR → tracker post
                                                          ↑
                                                Phase 6b lives HERE
```

**What I did this session (wrong):**
```
ticket 1: architect → skeptic → engineer → skeptic → quality-gate → commit → PR → tracker post
ticket 2: ...same flow, no QA either
...
ticket 10: ...same
[end of batch] → QA all 10 PRs
```

I deferred QA across all 10 tickets and ran a final batched verification pass. This is a deviation from `Phase 6b` which mandates QA between `Phase 6` Skeptic sign-off and `Phase 7` quality gate.

**Why I did it (and why the protocol should harden against it):**
- env file (`apps/<app>/.env.local`) was missing → dev server couldn't boot → Phase 6b silently fell back to static-only or got skipped → I rationalized this as "QA at the end when env arrives"
- batching parallel engineer/Skeptic spawns felt faster than serially gating each on QA
- Vercel preview was project-blocked → no preview-URL fallback either

Both issues are environmental, not protocol-level. But the protocol's response was implicitly permissive: Phase 6b says "static-only is acceptable when Skeptic has already signed off." That permission becomes a license for the conductor to skip in-flow QA across an entire batch.

**Fix for the protocol:**

1. **Phase 6b must be a hard gate, not advisory.** When the unit is Elevated AND `qa_skip == null` AND scenarios non-empty, Phase 6b runtime QA must execute before Phase 9 (PR open) — NOT deferred to a post-batch sweep. If runtime QA cannot run (env missing, dev server fails, no preview), the unit is held with `qa_blocked` status and surfaced to operator BEFORE the PR opens. Operator decides: provide env / authorize ship-as-INCONCLUSIVE / abandon the unit.

2. **Conductor MUST NOT batch QA at end of batch as a normal mode.** If Phase 6b can't fire for ticket N, that's a per-ticket blocker — surface it and stop advancing OR explicitly accept `qa_unverified=true` on that unit. Don't roll the deferred QA forward across N tickets.

3. **Add explicit anti-pattern documentation:** include in the Phase 6b spec a "Do NOT" callout: "Conductor must not aggregate Phase 6b across multiple tickets to run as a final batch step. Each ticket gets its own in-flow Phase 6b. If QA can't run for ticket N at the moment of its Phase 6b, that's a blocker for ticket N — not deferred work for the batch."

4. **Per-ticket QA in batch mode = parallel-by-worktree.** When the conductor is genuinely running multiple tickets in parallel (via worktree fan-out), each unit's Phase 6b runs in that unit's worktree on a unique port — concurrent with the unit's other phases on its own branch. This is the model that makes "in-flow" scale across a batch.

### 1a. Phase 6b cannot just assume the dev server boots
- **What happened:** qa-engineer spawned, attempted `pnpm dev:crocs`, env file missing → fell back to static-only Path C → reported INCONCLUSIVE → entire QA pass wasted.
- **Fix for the protocol:** Phase 6b MUST run an env preflight BEFORE spawning qa-engineer. The architect plan / Brief should declare the env requirement (e.g. `apps/<app>/.env.local` exists, OR list the env vars the dev server requires). Conductor checks → if missing, surface to operator with the exact `<env-pull-command>` (resolved from project config) before spawning. Do not let qa-engineer discover this at runtime.

### 1b. Preview-deploy path can be silently project-blocked
- **What happened:** Vercel previews were globally blocked on every PR in the batch (commit-author-email mismatch). Phase 10 polled 5 min per PR for a `Test URL` that never came. qa-engineer's Path A always failed.
- **Fix for the protocol:**
  - Phase 10 should call `gh pr view --json statusCheckRollup` once instead of polling comments. Detect "Vercel project blocked" status checks and skip the wait.
  - qa.md (per-track) should support a `preview_blocked: true` flag operator can set when this is the known state, so qa-engineer skips Path A entirely.
  - Document "Vercel preview can be globally blocked at the project level" as a generic project-knowledge pattern in the qa.md template.

### 1c. Static-only QA is ~0 signal but currently passes the gate
- **What happened:** when no dev server and no preview, qa-engineer returns INCONCLUSIVE with static analysis. The Phase 6b protocol says "static-only is acceptable when Skeptic has already signed off the diff." This downgrades QA to a rubber stamp.
- **Fix for the protocol:** for Elevated UI-visible changes, static-only QA should be `INCONCLUSIVE` and counted as `qa_unverified=true` on the unit. The unit ships but the operator must explicitly accept the unverified-runtime state. Don't auto-promote to PASS.

### 1d. Multi-PR QA can run in parallel — protocol assumes single-port serial
- **What happened:** qa-engineer ran serially against port 3000 across 8 PRs (~40 min). Each PR needed its own branch checkout, which blocked parallelism in the main worktree.
- **Fix for the protocol:** Phase 6b should explicitly support parallel-by-worktree QA when `len(prs_to_verify) > 1`. Pattern:
  - For each PR: `git worktree add .agentic/qa-worktrees/<unit-slug> <branch>`
  - Spawn qa-engineer per worktree with `PORT=<3000 + worktree-index>` (or any free port).
  - All run concurrently. End-of-run: `git worktree remove` each.
- Add this to the QA Gate section of METHODOLOGY.md as the default for batch invocations (`/implement-ticket` with N≥2 entries).

### 1e. QA scenarios should live in a structured per-unit file, not ad-hoc in spawn briefs
- **What happened:** I had to author per-PR QA scenarios in each qa-engineer spawn brief from memory of the architect plan. Brittle.
- **Fix for the protocol:** Phase 6b reads `qa_criteria.scenarios[]` directly from the architect plan / Brief. Architect plan template should mandate the YAML block. qa-engineer's brief is then mostly "here's the URL, here's the scenario list — verify and report."

### 1f. dev server boot time variance — qa-engineer should poll for readiness, not sleep
- **What happened:** my QA briefs used `sleep 30` / `sleep 45` to wait for boot. Sometimes too short (boot still going), sometimes too long (waste).
- **Fix for the protocol:** qa-engineer brief template should poll: `until curl -s -o /dev/null -w '%{http_code}' http://localhost:<port>/ | grep -qE '200|3'; do sleep 2; done` with a 90s timeout. Faster + more reliable.

---

### 1g. qa-engineer's branch-switching can clobber conductor's untracked scaffolding

- **What happened:** the serial qa-engineer needed to checkout each of 8 PR branches sequentially in the main worktree. Across the 8 checkouts, several conductor-local untracked files were silently dropped: `.claude/`, `CLAUDE.md`, `apps/crocs/.agentic/`, `apps/heydude/.agentic/`, `apps/heydude/AGENTS.md`, `glossary.md`. Some likely went into a stash; others are just gone.
- **Why this matters:** the conductor relies on those untracked files (qa.md project knowledge, scaffolding state). qa-engineer wiping them breaks subsequent runs.
- **Fix for the protocol:** Phase 6b qa-engineer brief must include an invariant: "Before any `git checkout`, snapshot conductor's untracked-or-modified set with `git stash push --include-untracked` (one per branch switch). After each branch's QA, `git stash pop` to restore. NEVER clobber untracked files." Better still: use `git worktree add` for each branch (per the parallel-by-worktree pattern from §1.0/§1d) so the main worktree's working state is never touched.

### 1h. dev server start command may differ per project — protocol assumes one form

- **What happened:** the project supports both `pnpm dev:crocs` (root script) and `pnpm --filter crocs dev` (workspace filter). qa-engineer used the latter. Both work, but the protocol's Phase 6b spec doesn't specify how to resolve the right command.
- **Fix for the protocol:** per-track qa.md should pin the canonical `command: <exact pnpm/yarn/npm invocation>` that qa-engineer uses verbatim. The Phase 6b spec already references this; tighten it to "MUST read from qa.md first, fall back to package.json `dev` script only if qa.md doesn't specify."

## 2. Concurrent engineer worktree contention

- **What happened:** DINO-648 and DINO-644 engineers spawned in parallel in the same main working tree. They stomped on each other's `git checkout` between Edit calls. DINO-644 returned BLOCKED. Recovery required worktree isolation.
- **Fix for the protocol:** make `isolation: "worktree"` MANDATORY for any concurrent engineer spawn. Update the Phase 5 spec to include a hard rule: "if conductor is spawning ≥2 engineers in the same message OR while another engineer is mid-flight, every engineer MUST use `isolation: 'worktree'`." Single-engineer flows can keep using the main worktree.
- Cross-reference: the existing methodology mentions worktree isolation but doesn't make it mandatory for concurrent spawns. The cost of contention (a hard BLOCKED) far exceeds the cost of always-isolating concurrent engineers.

---

## 3. Stale remote branches

- **What happened:** DINO-638's auto-generated branch name `fix/DINO-638-shop-all-size-href` already existed on origin pointing at an unrelated merge commit (#434). Engineer's `git push -u` reported "new branch" but `git ls-remote` afterwards still showed the stale SHA. Force-push was correctly refused. Manual rename to `fix/DINO-638-plp-href-size-fix` resolved it.
- **Fix for the protocol:** Phase 5 conductor preflight should run `git ls-remote origin <proposed-branch-name>` before passing the name to the engineer. If it exists with a SHA other than what we want to push, append `-v2` (or `-<short-sha>`) to make it unique. Engineer never has to handle the rename.

---

## 4. Premature pause / wallclock anxiety

- **What happened:** at ~54 min into a 90-min wallclock cap, I (conductor) wrote `pause_reason: "operator_pause"` to batch-state.json — but operator had NOT said pause. I conflated my own caution with a Phase 12a trigger.
- **Fix for the protocol:** add an explicit invariant to Phase 12a: "Conductor MUST NOT write `operator_pause` unless the operator's last message contains the literal substring 'pause the batch' (case-insensitive). Conductor self-doubt about remaining capacity is not a valid pause trigger; instead spawn the next ticket and let wallclock_cap fire mechanically if the cap is hit." Surfaces honest fail-soft instead of phantom pauses.

---

## 5. Architect plan blast-radius enforcement

- **What happened:** DINO-636's iter-1 plan proposed a DOM order swap in a shared `PriceDisplay` legacy branch. The plan acknowledged "10+ other consumers" but deferred per-consumer review to the engineer. Plan-level Skeptic correctly flagged 1 Critical + 2 Majors when it noticed `flex-row-reverse` compensation in one consumer + missing strikethrough on others. Iter-2 (gated approach) addressed all of them.
- **Fix for the protocol:** when an architect plan touches a shared component / utility, the plan MUST contain a per-consumer impact table with columns: `consumer_file:line | passes_relevant_prop? | uses_compensating_pattern? | current_visual | new_visual`. Make this a hard requirement in the architect agent spec; plan-level Skeptic rejects plans that defer this to engineer judgement.

---

## 6. Tracker write-back: protocol says delegate, conductor went direct for speed

- **What happened:** Phase 11 protocol says spawn a tracker-writeback subagent. I went conductor-direct via MCP for ~10 PRs to save the per-spawn overhead. Side effect: every MCP response printed a deprecation notice that polluted my context, and the protocol violation was unflagged.
- **Fix for the protocol:** either (a) tighten the rule with a stronger justification (so conductors don't shortcut it), or (b) explicitly allow conductor-direct for tracker writeback when N PRs > threshold (e.g. ≥3) since the per-spawn overhead exceeds the context-isolation benefit. Right now the rule is unclear about the trade-off.

---

## 7. Engineer return-shape variance

- **What happened:** engineers returned `quality_gate_results` in slightly different shapes — sometimes inline, sometimes after the notes block, sometimes prose instead of structured. Skeptics had to forgive variance.
- **Fix for the protocol:** require a fenced ```yaml or ```json block for the structured fields (status, files_modified, quality_gate_results, commit_sha, PR description body). Free-form notes only after the structured block. Provide a JSON-Schema fragment in the engineer agent spec.

---

## 8. Investigator-before-architect for shared utils — was selectively skipped, then bit us

- **What happened:** for shared-utility tickets (DINO-636 PriceDisplay, DINO-641 formatPrice, DINO-647 i18n), the conductor sometimes skipped the investigator step. DINO-636's iter-1 plan paid for it (missed cross-consumer regressions).
- **Fix for the protocol:** when a ticket's likely target file is in a `packages/<shared>` location AND has ≥5 importers, the investigator step is mandatory and produces the per-consumer impact table that the architect must consume. Conductor cannot skip-the-investigator on shared-utility surfaces.

---

## 9. Phase 0 JQL/filter URL — confirmation prompt vs autonomy

- **What happened:** Phase 0's confirmation policy mandates a "proceed/abort" prompt for JQL URLs. The user pushed back on this as anti-autonomy. We discussed and decided to soft-warn-and-auto-proceed (matching operator-enumerated >5 behavior).
- **Fix for the protocol:** Update Phase 0 confirmation policy table:
  ```
  | Trigger                              | Old              | New                                |
  | JQL/filter URL → any N entries       | hard prompt      | soft warn + auto-proceed           |
  ```
- Rationale: operator wrote the JQL deliberately; Phase 0a batch triage already provides a summary; "as autonomously as possible" is the stated goal.

---

## 10. CI Test URL polling — replace with status-check API call

- **What happened:** Phase 10 polls PR comments every 60s for `Test URL`. Wasteful and brittle (Vercel may post late, may not post at all if blocked).
- **Fix for the protocol:** `gh pr view <pr> --json statusCheckRollup,reviewRequests` returns deploy state directly. Poll the rollup, not comments. Detect "blocked" / "neutral" states early and short-circuit. Document this as the canonical polling pattern.

---

## 11. Per-ticket QA caught a real issue an architect+Skeptic missed (validation of §1.0)

- **What happened:** DINO-644 swapped Text variant `d-400` → `b-400` on the Size label. Architect plan + Skeptic both signed off (zero findings). qa-engineer running real browser inspection caught that **`<Text variant="b-400" bold>` produces `font-weight: 400` not 700** — the `bold` prop has no effect on `b-*` variants in the Text CVA. The Color label (`d-400`) honors `bold` correctly. This means the variant swap accidentally also dropped the bold weight that the operator likely wanted.
- **Why this matters:** runtime QA found a visual regression that ALL THREE prior gates (architect plan review, Skeptic on plan, Skeptic on diff) missed. The bug is in a different file (Text CVA wiring) than the diff (size-selector variant string). Static analysis cannot easily catch CVA-prop-interaction defects.
- **Why this validates the per-ticket-QA-in-flow rule:** if QA had been deferred to a post-batch sweep (as I did this session), the operator would discover this only on staging or production. Per-ticket runtime QA is the gate that catches CVA / styling / interaction defects no static gate finds.
- **Fix for the protocol:** add this as a standing example in the Phase 6b spec: "Runtime QA exists to catch defects the diff-Skeptic cannot. CVA prop-interaction defects, font-weight-vs-font-family conflicts, transition timing, focus order, and similar runtime properties cannot be reasoned about from the diff alone. Phase 6b is the line of defense; do not skip it."

## 12. Per-PR worktree isolation as the default for ALL agent spawns (biggest single fix)

- **Root cause of multiple session issues:** the main working tree was used as the dev-server / engineer / qa-engineer scratch space across multiple branches. Symptoms:
  - DINO-644 + DINO-648 engineers spawned concurrently → branch contention → BLOCKED.
  - DINO-638 engineer hit a stale-remote-branch collision because the main worktree had a leftover branch from a sibling spawn.
  - Serial qa-engineer running `git checkout` across 8 PRs wiped conductor untracked scaffolding (`CLAUDE.md`, `apps/heydude/AGENTS.md`, planning files, `.agentic/qa.md`, etc.). Recovery was possible only because the engineer happened to stash before checkout — relying on git's `stash@{N}^3` (untracked-files index) for retrieval.
- **Fix for the protocol:** make `isolation: "worktree"` the **default** for every `engineer`, `qa-engineer`, and `release-orchestrator` spawn — not opt-in. The main worktree stays on the conductor's branch with its untracked scaffolding intact. Each spawn gets `.agentic/worktrees/<unit-slug>/` (or harness-managed equivalent). Phase 5, Phase 6b, and Phase 7 spec must be updated to document this as MANDATORY rather than ADVISORY.
- **Secondary protection:** Phase 5/6b conductor preflight: before spawning, snapshot untracked-files state via `git stash push --include-untracked --keep-index --message "conductor-scaffolding-pre-spawn"`. Restore on return. This is a safety net for cases where worktree isolation is somehow not used.

## 13. /wrap must detect open PRs and defer AGENTS.md / memory.md updates that describe post-merge state

- **What happened:** /wrap authored AGENTS.md additions for `apps/crocs/`, `packages/commerce/`, `packages/ui/`, `packages/shared/`, `packages/contentstack/` describing helpers and namespaces (`apps/crocs/lib/metadata.ts`, `pageMetadata.*` namespace, `sitemap-noindex.test.ts`, etc.) that exist only on the in-flight feature branches — not on develop. Skeptic correctly flagged 5 Critical findings ("file does not exist", "fix did not land"). The conductor reverted all AGENTS.md edits.
- **Why this matters:** /wrap's current default is "land docs on conductor's current branch (develop)". When PRs are open, the docs describe future state. Engineers who pull develop see docs that lie until the source PRs merge.
- **Fix for the protocol:** /wrap Step 0 must run `gh pr list --state open --head '<current-branch>' --json files,number` (or the equivalent: enumerate every PR pointing at the conductor's current branch as base). For each AGENTS.md addition the draft Worker proposes:
  1. Cross-reference the proposed bullet's file paths against open PRs' modified files.
  2. If any cited path is in an open PR's diff, mark the addition as "post-merge-deferred".
  3. Write deferred additions to `.agentic/agents-md-pending.md` for a follow-up doc PR after merge.
  4. Apply non-deferred additions normally (durable facts about existing code).
- **Same logic applies to memory.md.** Entries that document a contract introduced this session by an open PR should be flagged "post-merge" in the entry itself OR moved to `.agentic/memory-pending.md`. Entries that document discovered facts (CVA quirks, external API formats) land normally.

## 14. Skeptic on hand-authored conductor output is mandatory — close the bypass loophole

- **What happened:** /wrap Worker iter 2 hallucinated badly (wrong PR numbers, invented paths, inverted ticket descriptions). Conductor invoked the "escape hatch" and authored the final outputs inline — but skipped the Skeptic-on-final-output round. A later Skeptic-on-disk run caught 5 Critical findings the conductor would have shipped without that adversarial check.
- **Fix for the protocol:** /wrap Step 4 must explicitly state: "if the conductor authors final outputs inline (e.g., after a Worker hallucination), spawn a Skeptic on the on-disk files BEFORE releasing the lock. The conductor's escape hatch from Worker iteration does NOT exempt the outputs from Skeptic review." Same applies to /implement-ticket Phase 4 trivial-path conductor-direct edits when blast radius warrants — the existing trivial-rule exemption from Skeptic should not extend to anything the Skeptic would have caught at runtime.
- **Bypass detector:** /wrap Step 6 confirmation must explicitly state which Skeptic rounds ran. If any draft Worker → Skeptic round was skipped, the message must say so and explain why.

## 15. Worker iter N briefs must use surgical-edit instructions, not regenerate-from-scratch

- **What happened:** /wrap iter 2 Worker brief said "Iteration 2 revision. Skeptic raised 3 Majors. Address each and return revised Output 1 / 2 / 3." The Worker, having no session memory, regenerated from scratch — confabulating PR numbers (#429-#437 instead of the actual #438-#447), inventing file paths, and inverting ticket descriptions. The conductor gave the Worker a high-level task it could not actually do without session context.
- **Fix for the protocol:** when /wrap (or any Worker-loop in /implement-ticket) re-spawns a Worker after Skeptic findings, the brief must include:
  1. The previous Worker's output VERBATIM (paste the iter N-1 outputs in full).
  2. The specific Skeptic findings to address.
  3. Instruction: "APPLY SURGICAL EDITS to the iter N-1 outputs above. Do NOT regenerate from scratch. Do NOT change anything not directly tied to a Skeptic finding."
- **Stronger alternative:** for iter 2+, the conductor authors the targeted edits inline (still subject to Skeptic per §14) rather than re-spawning a Worker. Trivial findings (typo, path correction) almost always fit this. The Worker should only be re-spawned when the iter 1 output was structurally wrong.

## Proposed structural changes to `/implement-ticket`

1. **New Phase 0c — Env preflight.** Before any engineer or QA spawn, verify env files exist for all apps the batch touches. Surface missing env to operator with exact pull command.
2. **Phase 5 — Mandatory worktree isolation for concurrent engineers.** Update Worker preamble to require `isolation: "worktree"` whenever ≥2 engineers run concurrently.
3. **Phase 5 — Pre-flight remote-branch existence check.** Conductor runs `git ls-remote origin <branch>` before passing branch name to engineer; renames if collision.
4. **Phase 6b — Parallel-by-worktree QA when len(PRs) > 1.** New default for batch flows.
5. **Phase 6b — Architect-plan-driven QA scenarios.** qa-engineer brief is generated from `qa_criteria.scenarios[]` in the architect plan, not hand-written by conductor.
6. **Phase 10 — Replace comment polling with status-check API.** `gh pr view --json statusCheckRollup` instead of grepping bot comments.
7. **Phase 12a — Tighten `operator_pause` trigger.** Literal substring match; conductor self-doubt is not a trigger.
8. **Architect plan template — mandatory per-consumer impact table for shared-component edits.** Plan-Skeptic rejects plans without it.
9. **Engineer return shape — fenced structured block required.** Free-form notes after.
10. **Phase 0 confirmation — JQL/filter URL → soft-warn-and-auto-proceed.** Match operator-enumerated >5 behavior.
