<!--
Purpose: Canonical reference for the ticket-rework alert - the notice that
         fires when /ds-implement-ticket starts work on a ticket AE already
         carried to an opened PR. Contains: what the alert deliberately does
         and does not do (with the measured reason no continuation-vs-rework
         discriminator exists); the ledger schema, its nullability column,
         and the null-render rule; why pr_number is the sole identity key;
         why the write lives at Phase 9 and not Phase 12 or Phase 11c; the
         append-plus-dedupe-on-read concurrency rationale; the dual-branch
         anchoring pattern (recorded so a future editor recognises the
         shape); the command-scoped-notice disclaimer; the trigger rule,
         notice template, escalation table, and known limitations.

Public API: Read-only reference document. Planned consumers (ship in units
            U2-U4 of the ticket-rework Plan; not yet live on main as of U1):
            content/commands/ds-implement-ticket.md (Phase 1 detection +
            notice, Phase 9 ledger write, Phase 2/3 risk floor, Phase 6
            Skeptic-brief callout, Tier-3 escalation at 2+ prior attempts);
            content/commands/ds-ticket-triage.md (per-entry ledger read,
            [REWORK xN] badge, lane rule).

Upstream deps: docs/planning/ticket-rework/architect-plan.md (Skeptic-
               approved, 3 rounds, source of the design decisions this doc
               records); docs/planning/ticket-rework/brief.md (problem
               framing and success criteria); content/rules/module-
               manifest.md (this header's format); content/references/
               regression-test-obligation.md and content/references/
               qa-regression-obligation.md (structural precedent for a new
               reference doc with no prior art in this domain).

Downstream consumers: Planned (ship in units U2-U4 of the ticket-rework
                      Plan; not yet live on main as of U1):
                      content/commands/ds-implement-ticket.md,
                      content/commands/ds-ticket-triage.md. Read on trigger
                      only - nothing in this file enters an always-loaded
                      path; it is never assembled into METHODOLOGY.md by
                      scripts/build-methodology.sh, which reads only
                      content/sections/.

Failure modes: this is documentation, not executable code - no runtime
               failure mode of its own. Staleness risk: if the ledger
               schema, write anchor, or concurrency mechanism described here
               changes in ds-implement-ticket.md or ds-ticket-triage.md
               without a matching update to this file, the doc becomes
               active misinformation per the module-manifest staleness
               rule - treat any such drift as a doc-sync obligation.

Performance: Standard (static reference text; no runtime cost).
-->

# Ticket rework alert

The mechanism described in this reference ships across units U2-U5 of the ticket-rework Plan; as of U1 it is not yet live on `main`.

## What this is, and deliberately is not

The rework alert tells the operator when `/ds-implement-ticket` starts work on a ticket that AE already carried to an opened PR in a prior invocation. It does **not** attempt to tell the difference between genuine rework (something is broken or incomplete and needs fixing) and planned continuation (a multi-wave ticket where a second, third, or later invocation was always expected). It fires on both, identically.

This is a deliberate scope cut, not an oversight, and the reason is measured rather than assumed: **the discriminating datum does not exist in this ecosystem.** At the time this feature was designed:

- Jira (project DS) recorded zero `Done -> non-Done` transitions across 93 tickets.
- GitHub Issues had zero issues ever created across all five consumer repos.
- Linear (project THU) had 80 issues, all sitting in `backlog`, with zero state transitions.

There is no tracker-side signal anywhere in this ecosystem that distinguishes "this ticket regressed and came back" from "this ticket always needed another wave." Building a discriminator against data that doesn't exist would mean guessing, and a guessed discriminator that's wrong in either direction is worse than no discriminator: a false "this is fine, just continuation" suppresses exactly the case the operator asked to be told about.

**The operator decided a second invocation on the same ticket IS the event worth flagging, discriminator or not.** Historically this fires on 8 of 37 tickets (22%) - not rare, but far from every ticket, and the operator accepted that rate rather than asking for a smarter filter. If the notice turns out to read as noise on planned multi-wave work, the fix is to raise the Tier-3 threshold (currently 2+ prior attempts), not to retrofit a discriminator onto data that isn't there.

## Ledger schema

The alert is backed by one local, gitignored, append-only file: `.agentic/ticket-ledger.jsonl`. One line is appended per PR-opening attempt.

```json
{"ticket_id":"DS-87","pr_number":458,"opened_ts":"2026-07-17T11:54:58Z",
 "branch":"feature/ds-87-pr-template","risk_class":"Elevated","skeptic_rounds":2,
 "qa_status":"PASS","unit_count":5}
```

A Trivial-path record legitimately carries two null fields:

```json
{"ticket_id":"DS-91","pr_number":462,"opened_ts":"2026-07-20T09:10:00Z",
 "branch":"fix/ds-91-label-typo","risk_class":"Trivial","skeptic_rounds":null,
 "qa_status":"skipped:Trivial path","unit_count":1}
```

**Nullability column** - which fields can legitimately be null, and why:

| Field | Can be null on a legitimate path? | Why |
|---|---|---|
| `ticket_id` | No | The write contract skips the append entirely when `TICKET_ID` is null/empty. |
| `pr_number` | No in the ledger | Derived from `$BRANCH_NAME` at the write site; the write is skipped when that derivation yields nothing. Never read from an in-context variable. |
| `opened_ts` | No | Generated at write time. |
| `branch` | No | `BRANCH_NAME` is resolved early in every ticket's flow, regardless of path. |
| `risk_class` | No | Declared before any spawn happens. |
| `skeptic_rounds` | **Yes** | The Trivial path bypasses the Skeptic loop entirely; the only durable iteration-count source is written by the Skeptic loop itself, which a Trivial ticket never enters. |
| `qa_status` | **Yes, on two paths** | Trivial tickets never run QA. Elevated tickets with a `qa_skip` value also never run QA - the write records the skip rationale instead of a status. |
| `unit_count` | No | **Derived, not read** - there is no `unit_count` variable anywhere in the command. Derivation rule: count of `.agentic/tasks.jsonl` records matching this `ticket_id` on the Phase 5 fan-out path; `1` on a single-engineer path; `1` when `tasks.jsonl` is absent or unreadable. |

**Null-render rule.** Any null field renders `n/a` in the notice and the triage badge - the same rendering convention `/ds-implement-ticket` already uses elsewhere for an unresolved iteration count. `qa_status` is the one exception: it prefers its skip rationale (`"skipped:<rationale>"`) over `n/a`, because "QA never ran, here's why" is exactly what an operator doing manual verification needs to know - a bare `n/a` would hide that QA was intentionally skipped rather than simply unavailable. The skip-rationale string is collision-free against the QA result vocabulary (`PASS`/`FAIL`/`PARTIAL`/`BLOCKED`/`INCONCLUSIVE`): none of those values, nor any of the `qa_skip` enum values, nor the literal `"Trivial path"`, contain a colon, so a first-colon parse of `qa_status` unambiguously separates the `skipped:` prefix from its rationale.

## `pr_number` as the sole identity key

`pr_number` is the only field the detector uses to identify a distinct attempt. `branch` is recorded for forensic purposes only and must never be treated as an identity key, for two independent reasons - both branch-name failure modes:

1. **Collision after branch deletion.** The standard AE workflow deletes the feature branch after merge (`--delete-branch`). A later rework attempt on the same ticket derives the same branch-name slug from the same ticket ID, and would collide with the deleted branch's name if branch name were used as identity - two distinct attempts would look like one.
2. **Splitting under a rename.** A branch can be renamed mid-flow (for example, a `-v2` suffix appended after a conflict). A rename mid-attempt would make one real attempt look like two if branch name were the key.

`pr_number` is assigned externally by GitHub and is immune to both failure modes - it doesn't get deleted, reused, or renamed the way a branch does.

**`$BRANCH_NAME` is a lookup key, never the identity itself.** At the Phase 9 write site, the ledger writer derives `pr_number` by looking up the currently-resolved branch name against GitHub (the same `gh pr view "$BRANCH_NAME" ... --json number -q .number` pattern already used elsewhere in the command for exactly this kind of live PR-number recovery). That lookup produces the `pr_number` that gets stored. `$BRANCH_NAME` itself is never written to the ledger as, or treated as, an identity key - it is consumed at write time and then discarded from the identity question entirely. This distinction matters: it would be easy to conflate "we used the branch name to find the record" with "the branch name is the record's identity," and the two are not the same thing.

One residual, deliberately accepted case: after a branch name is reused (a prior attempt was merged and its branch deleted, then a new attempt reuses the same slug), if the *new* `gh pr create` call itself fails, the lookup by branch name could resolve the *prior*, already-merged PR on that name instead of nothing. This does not create a false record, because that PR belongs to the same ticket and was already recorded on its own prior write - the read-side dedupe (see Concurrency below) collapses the duplicate `pr_number` rather than inflating `PRIOR_ATTEMPTS`. Same-ticket staleness is absorbed; cross-ticket contamination - a different ticket's failed create resolving to *this* ticket's PR - is the case the derivation-from-branch-name design actually eliminates, because the lookup is always scoped to the ticket currently in flight's own resolved branch name, never to a stale in-context variable that might still be holding a previous ticket's value from earlier in the same batch.

## Phase 9 write point

The ledger write happens once, at the `/ds-implement-ticket` Phase 9 PR-creation step - specifically at the capture point immediately after the PR is created and its number is captured, downstream of PR creation regardless of which body-composition path was used (see Dual-branch anchoring pattern below).

**Why Phase 9 and not later.** The exits that actually discriminate between Phase 9 and a later anchor are the ones that fire after a PR already exists but before the run reaches a clean finish: the Phase 10 CI timeout and the Phase 10a fix-loop cap. A first invocation that successfully opened a PR and then died on red CI, or exhausted its CI-fix budget, is precisely the kind of prior attempt a later re-invocation should be told about - and Phase 9 is the earliest point at which "a PR now exists for this ticket" becomes true, so anchoring there catches every run that got that far, independent of what happens afterward. (The Skeptic-loop cap, the QA-loop cap, and fix-loop exhaustion earlier in the flow do not discriminate between Phase 9 and any later anchor - no PR exists yet on those exits, so neither anchor would record them; see "Pre-PR failures are never recorded" in Known limitations below.)

**Why not Phase 12.** Phase 12 sits downstream of all of the escalation exits described above. Anchoring the write there would silently drop every attempt that opened a PR but then stalled or was escalated before reaching Phase 12 - exactly the runs where a manual-verification pointer matters most, because those are the ones that ended in an unresolved state rather than a clean finish.

**Why not Phase 11c.** Phase 11c is skipped on the Trivial path, which never reaches it. Anchoring the write there would drop the Trivial-path record shown above, which is exactly the record this doc uses to illustrate the null-render rule.

**Open-goal dry-run is correctly silent.** When an open-goal loop runs in dry-run mode, Phase 9 (along with the rest of the ship-side phases) is skipped for every iteration - no PR is ever opened, so there is nothing to derive a `pr_number` from, and no record is written. Synthetic per-iteration identifiers used internally by an open-goal loop never enter the ledger.

## Concurrency rationale

The ledger is written with an unconditional append (`O_APPEND` semantics) and never read before writing. All deduplication happens on read, not on write.

**Why this is safe, stated on the correct grounds.** For a regular file, `O_APPEND` guarantees that the seek-to-end and the subsequent write are atomic with respect to the file's offset - two concurrent appenders cannot have their writes interleave into a single corrupted position, because each individual `write()` call's data lands atomically at whatever the end-of-file offset was at the moment that call executed. This is a per-`write()`-call guarantee, not a per-logical-record one, and the design depends on that distinction: the write contract appends **one ledger line via a single `O_APPEND` `write()` call**, never composed from multiple separate writes, so the offset-atomicity guarantee covers the whole line as one unit. A writer that split one line across several `write()` calls would lose this guarantee and could interleave with a concurrent writer's output. This atomicity guarantee is specific to regular files; it does **not** extend to pipes or FIFOs, where a different atomicity bound (`PIPE_BUF`) applies instead. `.agentic/ticket-ledger.jsonl` is a regular file, so `O_APPEND` offset atomicity is the correct and sufficient guarantee here - **do not cite `PIPE_BUF`** for this file; that bound governs a different kind of file object and citing it here would be citing the wrong guarantee for what is actually being relied on. (An earlier draft of this design made exactly that mistake during review; it is recorded here so it is not reintroduced.)

One caveat worth carrying forward: `O_APPEND`'s atomicity guarantee does **not** hold over NFS. A ledger on a networked filesystem could, in principle, see interleaved writes from truly concurrent appenders. This is accepted as a known limitation rather than solved with a lock, because a lock protocol would reintroduce exactly the contention this design avoids, and the read side already tolerates a duplicated or malformed line without harm (a duplicate `pr_number` collapses under dedupe; a malformed line causes detection to soft-fail rather than crash).

**Because dedupe is read-side, no write-time lock is needed.** A reader collapses records by `pr_number`, so a benign duplicate (see the branch-reuse case above) or a genuinely concurrent double-write never inflates the attempt count. This is why the write contract is "append unconditionally, dedupe on read" rather than "read-then-append" - a read-then-append pattern would introduce a check-then-act race the unconditional append avoids entirely.

## The dual-branch anchoring pattern

This pattern was found twice during review of this feature's design, in two unrelated commands, and is recorded here explicitly so a future editor recognizes the shape before repeating it.

**The rule: anchor downstream of every branch, never inside one.** When a command has two (or more) mutually exclusive branches that both need to reach the same later step, the anchor for that later step must sit after every branch rejoins - not inside any single branch, even the branch that looks like "the main path."

**Instance 1 - `/ds-implement-ticket` Phase 9's two `gh pr create` calls.** Phase 9 composes the PR body two different ways depending on whether the unit is behavior-visible with QA evidence (Case A - QA Evidence leads the body) or not (Case B - Summary-first body, QA evidence appended afterward). These are the two branches of a single `if`/`else`. Case B is not a minor fallback - it is the branch every Trivial ticket takes, since a Trivial ticket never produces QA evidence in the first place. Anchoring the ledger write inside Case A specifically would have silently dropped every Trivial ticket's record. The write is anchored after the `if`/`else` closes, at the point where the PR number is captured regardless of which case created it - downstream of both.

**Instance 2 - `/ds-ticket-triage` Phase 0's two entry branches.** Phase 0 resolves the ticket list one of two mutually exclusive ways: the no-args branch (which resolves the operator's currently-assigned open tickets from the tracker, and - on finding two or more results - explicitly proceeds "into Phase 1+ exactly as for an explicit list input," with its own terminal breadcrumb) or the explicit-input branch (an operator-supplied list or URL, with its own terminal breadcrumb). No-args is a first-class, documented invocation form, not a fallback - it is the default shape for a tracker-connected operator with no arguments to type. Anchoring a per-entry read to the explicit-input branch's breadcrumb alone would have silently skipped the rework badge for every no-args invocation. The read is anchored after `entries[]` is resolved by *either* branch, before the next phase begins - downstream of both.

The common failure shape: a change that needs to run "after ticket list resolution" or "after PR creation" gets written against whichever branch the author happened to be looking at, and the other branch - often the more common one - silently never sees it. Check for this explicitly whenever a new step needs to follow a multi-branch structure: does the anchor point sit after every branch rejoins, or only after one of them?

## Command-scoped notice, not a session-start notice

The REWORK notice fires inside `/ds-implement-ticket`'s Phase 1, once per ticket, when that specific ticket has one or more prior PR-opening attempts recorded in the ledger. **It is not a session-start stacked notice.** `content/rules/conventions.md` documents an exact count of stacked first-user-turn notices that fire at session start regardless of what the session is about (meta-divergence, skill-candidate, identity-provisional-confirm - explicitly enumerated as "the 4th stacked first-user-turn notice" for the most recently added one). The REWORK notice is a different mechanism entirely: it is scoped to a specific command and a specific ticket, fires mid-flow rather than at session start, and does not add to that count. A future editor updating the stacked-notice count in `content/rules/conventions.md` should not include this notice in that tally - it was never part of that enumeration and doesn't belong in it.

## Trigger rule

Detection makes zero tracker and zero network calls - it is a single local file read, so it works identically whether `TRACKER` is configured or `none`. At the per-entry level of Phase 1, after the tracker sub-section dispatch:

1. If `rework_detection` is disabled (see the config toggle below), or the current ticket ID is null/empty, skip detection entirely - `PRIOR_ATTEMPTS` is `0` and nothing is emitted.
2. Otherwise, read `.agentic/ticket-ledger.jsonl` and collect every record whose `ticket_id` matches, exact string match, deduping by `pr_number`.
3. `PRIOR_ATTEMPTS` is the size of that deduped set. `IS_REWORK` is `PRIOR_ATTEMPTS >= 1`.
4. If the ledger is absent or a line is malformed, detection soft-fails to `PRIOR_ATTEMPTS = 0` rather than erroring - a missing or corrupt ledger must never block the ticket it's trying to help with.

## Notice template

```
REWORK: ticket <ID> has <N> prior AE attempt(s) that opened a PR - prior work on this ticket may need verification.
  Last attempt: PR #<n> (<date>), risk <class>, <r> Skeptic round(s), QA <status>, <u> unit(s).
Risk floored to Elevated; architect and Skeptic briefed on the prior attempt.
Manual verification of PR #<n> is recommended.
[phase: rework-detected]
```

Applying the null-render rule: `<r>` renders `n/a` when `skeptic_rounds` is null; `<status>` renders the skip rationale when QA never ran, otherwise the actual QA result, otherwise `n/a`. On a Trivial-path prior record the second line reads `risk Trivial, n/a Skeptic round(s), QA skipped:Trivial path` - which correctly tells the operator no adversarial review ran on the prior attempt, rather than hiding that fact behind a bare `n/a`. When `PRIOR_ATTEMPTS > 1`, the notice appends `(+<N-1> earlier: PR #<a>, #<b>)` listing the older attempts by PR number only - the most recent attempt is the only one described inline.

`/ds-ticket-triage` renders the same detection as a compact per-ticket badge: `[REWORK xN]`.

## Escalation table

| `PRIOR_ATTEMPTS` | Risk floor | Tier | Architect / Skeptic brief |
|---|---|---|---|
| 0 | No change - normal classification applies | No change | No callout |
| 1 | Floored to Elevated (never Trivial, never Low) | Tier 2 (role default) | Independent top-level callout naming the prior PR, risk class, Skeptic rounds, and QA status; architect is instructed to identify what the prior attempt missed and add a `qa_criteria` scenario exercising the regression; the same callout is added to the Skeptic brief instructing it to verify that failure mode is addressed, not only review the new diff |
| 2+ | Floored to Elevated | **Tier 3**, explicit `model: opus` | Same callout as the 1-attempt row |

The Elevated floor and the Tier-3 escalation at 2+ attempts are both command-scoped triggers, not additions to the global Elevated-signal list or the Mandatory Tier-3 escalation category count - neither widens the always-loaded signal tables that other parts of the methodology reference by exact count. The architect callout is deliberately an independent top-level block in the brief, not nested inside a "prior ticket context" section that gets omitted whenever there's nothing to summarize from tracker comments - the two situations are unrelated, and gating the rework callout on tracker-comment presence would silently drop it in the single most common case: a `TRACKER=none` project, where the ledger is exactly the kind of prior-attempt signal that has no tracker-comment equivalent to omit alongside.

## Known limitations

- **Tier-3 cost on planned multi-wave tickets.** A ticket that always needed several invocations (not rework in the everyday sense, just a big ticket) will draw an Opus-tier Skeptic on its third and later waves, because `PRIOR_ATTEMPTS >= 2` cannot distinguish "this needed three waves all along" from "this came back twice because something broke." This is advisory-only, with no mechanical hook backstop - a command-scoped trigger like this one is invisible to the hook that backstops the five *global* Tier-3 signal categories, so the conductor's explicit `model: opus` declaration is the only enforcement here. If this proves costly in practice, the fix is a one-number reversal of the threshold, not a new discriminator.
- **Pre-PR failures are never recorded.** A run that stalls before any PR opens (a Skeptic-loop cap, a QA-loop cap, a fix-loop exhaustion, before Phase 9 is ever reached) writes nothing to the ledger. This is deliberate - there is no PR number to anchor a record to - but it means "no notice" does not mean "no prior work was ever attempted," only "no prior work reached the point of opening a PR."
- **Cold start.** Only attempts that open a PR after this feature was adopted are ever recorded; there is no backfill from git or tracker history.
- **Machine-local ledger.** The ledger file is gitignored and local to the machine that ran the attempt. A teammate's prior attempt on the same ticket, run from a different machine, is invisible to this detector.
- **No ticket identity, no detection.** Pure-freeform work with no ticket ID (`TRACKER=none` with no ticket reference at all) is inert by design - there is nothing to key a ledger lookup on, and that is semantically correct rather than a gap.
- **A human fix with no AE attempt is invisible.** If a human fixed the ticket by hand and AE is now asked to work on it again, there is no ledger record to find, because AE never opened a PR for it.
- **The notice fires on planned continuation by design, and that's accepted, not a bug.** See "What this is, and deliberately is not" above - if this reads as noisy in practice, raise the Tier-3 threshold; do not add a discriminator against data this ecosystem does not produce.
- **`O_APPEND` is not atomic over NFS.** See Concurrency rationale above.
- **Always-loaded cost.** This feature adds effectively nothing to the always-loaded methodology body - the read-on-trigger reference you are reading now lives entirely under `content/references/`, which `scripts/build-methodology.sh` does not touch (it assembles only from `content/sections/`). Any cost that does land in an always-loaded file (a config-toggle-count bump, a Tier-3 category note) is deliberately minimal and tracked by the doc-sync obligation.

## Config toggle

`rework_detection` - boolean, default `true`. Absent key resolves to `true`. When `false`, the Phase 9 write, the Phase 1 detection read, the notice, the triage badge, and the escalation (risk floor and Tier-3 bump) are all disabled - the feature goes fully dark with a single toggle. See `content/references/risk-config-and-tiers.md` §Config Toggle Catalog (behavioral) for the canonical toggle-count entry.
