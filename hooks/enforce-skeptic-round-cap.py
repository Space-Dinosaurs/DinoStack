#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that mechanically enforces the ad-hoc Skeptic
         round-budget policy (content/sections/05-qa-gate.md §Re-route
         limits, content/references/skeptic-protocol.md §Round budget and
         value-per-round gate): a max of `_ROUND_CAP` Skeptic rounds per
         unit. Past the cap, exactly one more round is allowed per operator
         grant: a genuine operator turn in the session transcript containing
         the `skeptic-grant-<8 hex>` token the deny prints for that unit and
         round. Nothing the conductor writes to the state file reopens it.
         Before this hook, the cap was enforced only by "the conductor tracks
         re-route count in-context" - unenforced prose. A single session ran
         12 Skeptic rounds / 13 spawns on one unit with no mechanism firing.

         Persists round state at `.agentic/skeptic-round-<unit-key>.json`
         under the payload's `cwd`. **The key is deliberately NOT the
         conductor's own git branch.** In this repo's workflow the conductor
         stays on `main` for the whole session while engineers work in
         isolation worktrees, so every Skeptic spawn - across every unit,
         across the whole session - would share one `skeptic-round-main.json`
         counter if keyed off `cwd`'s branch: unit A's rounds would exhaust
         unit B's budget. Instead the key is the stable unit KEY that
         leads the "Diff under review" line `content/references/skeptic-
         protocol.md` Section 4.5 mandates in EVERY Skeptic spawn prompt
         (the `## Global-context inputs` block, item 6, in the form
         `<KEY> | <diff detail>`): the conductor writes the same KEY on
         every round of one unit, even though the rest of the prompt (the
         pasted Worker output) changes every round. See `_unit_key()`. A
         field 6 that is present but carries no valid KEY is DENIED
         (`_DENY_KEYLESS_TEMPLATE`, no round state written); when the line
         is absent or ambiguous the hook fails open (allows, writes no
         state) rather than falling back to a weaker key that could
         collide across unrelated units - see Failure modes below.

         **A follow-up fix to that same "Diff under review" line, found
         when this hook failed to fire on its own verification round:**
         (a) `_DIFF_UNDER_REVIEW_RE` originally only matched a numbered
         list-item form ("6. Diff under review: ..."). Real spawn
         prompts also use a hyphen bullet, an asterisk bullet, and bold
         markup with or without a bullet (e.g. "- **Diff under
         review:**") - all of which the original regex missed entirely,
         including the exact form the verification round's own prompt
         used. `_DIFF_UNDER_REVIEW_RE` now covers all of these. The same
         regex fix also closed a second bug: the whitespace class around
         the captured value used to cross newlines, so an EMPTY field followed by a
         blank line captured the NEXT line (typically the pasted Worker
         output under "What to review") as the identity instead of
         failing open. The whitespace around the capture is now
         `[ \t]*`, which cannot cross a newline.
         **Two further fixes, found by re-measuring rather than
         re-reading the round-3 fix, after round 3's own Minor-2 fix
         (bounding `_WHAT_TO_REVIEW_RE`) turned out to have disabled the
         cap entirely:**
         (c) Round 3 bounded `_WHAT_TO_REVIEW_RE` to stop the captured
         "What to review" body at the next bold-labeled section header,
         reasoning that a future template might place per-companion text
         after the Worker-output section. A realistic pasted Worker
         output routinely contains its OWN bold-labeled lines (e.g. a
         constant "Worker output below." sentence immediately followed by
         a "**Summary:**" line) - the bound's lookahead matched on that
         FIRST internal bold line and truncated every round's captured
         body down to the same constant prefix, so all rounds hashed
         identically and coalesced onto round 1's cached ALLOW forever
         (measured: 5 sequential rounds, round_count frozen at 1, ALLOW
         every time - total, silent disablement of the round cap).
         `_WHAT_TO_REVIEW_RE` is now unbounded again (the round-2 form);
         see the regex's own comment for why the bound is not coming
         back without a reproduction of the hypothetical it defended
         against.
         (e) On an empty bolded field with nothing after the closing bold
         marker (e.g. "- **Diff under review:**" with no trailing text),
         the closing-bold-markers portion of `_DIFF_UNDER_REVIEW_RE`
         could backtrack to consume only one of the two closing asterisks
         and still match overall, and the identity capture group (a bare
         non-whitespace character class, before this fix) then captured
         the single leftover asterisk as a valid one-character
         "identity" - every unit with this
         defect collided onto the SAME shared `*`-keyed counter, so
         malformed spawns on unrelated units produced a false DENY on an
         unrelated unit's legitimate spawn. The capture group's first
         character now excludes both whitespace and the asterisk itself,
         so that case yields no capture at all
         (correctly falls through to fail-open) instead of a collidable
         one-character key.

         **Mandatory stable unit key (DS-180, then round-cap Part B).**
         Fixes (b) and (d), now deleted with the code they described,
         derived the key by normalizing the diff range in field 6 (the
         branch token, else the base SHA). No such heuristic survives a
         ROLLING range, where round N's base equals round N-1's head, or a
         round-numbered prose prefix in front of the range: on PR #760
         seven rework rounds on one unit produced seven state files and the
         cap never engaged (KNW-20260814-022). DS-180 added the optional
         `<key> | <diff detail>` form, read by `_extract_stable_unit_key()`,
         with the normalization kept as a fallback for keyless values; the
         fallback kept splitting units across counters (AUT-1245 rounds 5-7,
         AUT-1178's five keys) and merging unrelated ones (two units on one
         base SHA, `<x>~N..HEAD` values on one `HEAD` key). The key is now
         the only identity: a present, unambiguous field 6 whose value has
         no valid key is denied with `_DENY_KEYLESS_TEMPLATE`, which names
         the form, the derivation rule and the value received. The deny
         writes no round state and no tuid-index entry, only the fire-log
         line `_deny()` always writes, so the retry with a key starts at
         the true round count.

         Decision algorithm (see `_decide()`):
           - round_count is the number of Skeptic rounds already recorded
             for this unit. On a spawn attempt, next_round = round_count + 1.
           - Round fingerprint coalescing: a `skeptic_strategy:
             multi-dimensional` fan-out (correctness-Skeptic +
             security-auditor + perf-analyst, all `subagent_type ==
             "skeptic"`, spawned in a single conductor message onto the
             SAME diff and the SAME Worker output) shares this hook's unit
             key, since all three prompts carry the same "Diff under
             review" line. Deliberately NOT time-window based (a fixed
             wall-clock window cannot distinguish "3 parallel companion
             spawns of one round" from "3 genuinely sequential rounds fired
             back-to-back," and is flaky under test). Instead, `_decide()`
             hashes the "What to review:" section of the prompt (the pasted
             Worker output) into a `round_fingerprint`: fan-out companions
             review the identical Worker output, so their fingerprints
             match and the call reuses the first spawn's cached ALLOW/DENY
             outcome verbatim instead of re-running the decision. A
             genuinely new round always carries new Worker output (the
             engineer's latest fix), so its fingerprint differs and the
             round advances normally. When no "What to review:" section is
             present, coalescing never triggers (every call is treated as
             its own round) - a conservative default that never
             under-counts a real cap violation. This does not add real
             cross-process locking; a true simultaneous race can still
             double-charge a round - see Failure modes below.
           - next_round <= _ROUND_CAP: ALLOW. Persist round_count =
             next_round.
           - next_round >= _ROUND_CAP + 1 (cap reached): ALLOW only when
             `_operator_granted()` finds `_grant_token(unit_key,
             next_round)` in a genuine operator turn of the main-session
             transcript; persist round_count = next_round. The token is
             sha1(`<unit_key>#<next_round>`)[:8], so it authorizes one round
             of one unit: advancing round_count retires it, and another
             unit's token never matches. A grant-allowed round whose state
             write fails is DENIED (with an unpersisted suffix), or the same
             grant would re-allow on every retry. Otherwise DENY with
             `_DENY_CAP_TEMPLATE`, which names the unit, the round count,
             the two permitted actions (ship with accepted debt, or stop and
             report to the operator) and the token.
         Legacy `decision` and unresolved-Critical keys a state file may
         still carry are ignored (preserved verbatim via the `_extra`
         passthrough, never read): a conductor could write them with a plain
         Edit, so they let a conductor reopen its own cap (KNW-20261009-002).
         The hook does not enforce Critical-never-ships; that rule stays
         with the conductor (content/references/skeptic-protocol.md §Round
         budget item 1).

         Pillar 8 (docs/overview/vision.md), keyless deny: (a) catches
         AUT-1245 rounds 5-7 (one unit, four keys), AUT-1178's five keys,
         AUT-1245's "architect plan only" vs "the revised architect plan
         only" split, PR #760 (KNW-20260814-022), DS-45's "as given above"
         (KNW-20260818-015) and KNW-20260905-004; (b) retirement: a
         permanent floor while the round cap exists, replaced if the harness
         supplies a native unit identity in the PreToolUse payload.

         Pillar 8 (docs/overview/vision.md), operator grant: (a) catches the AUT-1245 key-A
         rounds 3 and 4, each reopened by a self-written escalate while the
         session's only genuine operator turns carried no grant, and the
         KNW-20261009-002 class generally; (b) retirement: a permanent floor
         while the round cap exists, or replaced by a hook
         `permissionDecision: "ask"` once that is measured to hold under
         bypassPermissions and `claude -p`.

         Scope: fires ONLY on `subagent_type == "skeptic"` Task/Agent spawns.
         Never denies conductor Read/Grep/Glob (those tools are never
         Task/Agent, so they never reach this hook's logic at all) and never
         gates on inferred session capability - flat prohibitions in
         hooks/AGENTS.md §No gating on inferred session capability.

         Sibling-deny consultation (fix for a spurious-round-charge defect,
         content/references/skeptic-protocol.md §Round budget and
         value-per-round gate, item 1): Claude Code runs every matcher hook
         registered on a PreToolUse event regardless of order or another
         hook's decision - registering this hook first cannot prevent a
         sibling hook further down the matcher array from independently
         denying the same spawn. Before this fix, this hook's own ALLOW
         branch always persisted (advanced round_count) even when a sibling
         hook such as enforce-skeptic-neutrality.py or enforce-tier.py was
         about to deny the identical spawn - so a spawn that never ran as a
         review still spent a round, and past the cap, spent the operator's
         one-round grant on nothing. On the ALLOW branch, `main()`
         now calls `_sibling_would_deny(data, cwd)`, which for each
         `_SIBLING_MODULES` entry first calls `_sibling_registered()` -
         positively confirming that entry's basename is registered on the
         Task/Agent PreToolUse matcher in the user-level `settings.json`
         (under the resolved harness config dir) or the unit's own
         project-level `.claude/settings*.json` (round-2 rework, Major 1;
         does NOT read a higher-precedence managed/enterprise settings
         file - see `_sibling_registered`'s own docstring) - and consults
         that sibling's own pure `would_deny(data)` function (imported by path)
         ONLY when registration is confirmed. This closes the case a
         registration-blind consultation would have gotten backwards: an
         installed-but-unregistered sibling (e.g. an install between
         2026-08-12 and 2026-08-24 whose hooks-snapshot was refreshed by
         `ds-doctor --fix` without re-running `install.sh`, or an operator
         who hand-deleted the entry) would otherwise be treated as "would
         deny" even though the real, registered hook set lets the spawn
         run uncharged every time - the exact defect this consultation
         exists to prevent, reintroduced from the opposite direction. Every
         uncertain registration case (no settings file found, a candidate
         unreadable or malformed, or the basename simply absent) is NOT
         consulted, so this call persists exactly as it did before the
         consultation existed - the same fail-open discipline as a
         sibling's own import/call failure. All of this runs BEFORE any of
         `_write_state` / `_append_tool_use_id` / `_update_tuid_index`. A
         non-None result from any CONSULTED sibling skips ALL persistence
         for this call and exits 0 (allow, from this hook's own
         perspective - the sibling's independently-registered deny still
         blocks the spawn).

Public API: Run as a Claude Code PreToolUse hook (matcher: "Task" or
            "Agent"). Reads JSON from stdin, writes hookSpecificOutput JSON
            to stdout when denying, exits 0 always.

Upstream deps: Python 3 stdlib only (hashlib, json, os, re, sys, time,
               importlib.util for the best-effort `lib/enforcement_log.py`
               and `lib/repo_root.py` imports). hooks/lib/repo_root.py
               (resolve_agentic_cwd) anchors the state file below to the
               repo root instead of the raw payload cwd; on load failure
               _state_path returns None and the caller skips the round-cap
               check entirely (fail-open) rather than falling back to a raw
               cwd. hooks/lib/loop_guard.py (genuine_user_text), loaded
               the same way and only past the cap, classifies origin-less
               transcript lines for the operator grant; on load failure no
               grant is found and the cap deny stands. No external deps, no
               subprocess (the fix that dropped
               `_current_branch()`'s `git rev-parse` call also dropped the
               only subprocess dependency this hook had). Also a
               best-effort dynamic import (importlib by path, same
               mechanism as the two libs above) of `enforce-skeptic-
               neutrality.py`, `enforce-tier.py`, `enforce-background-
               spawn.py`, and `enforce-orchestrator-singularity.py` (the
               `_SIBLING_MODULES` listed below) for their own
               `would_deny(data)` functions - see the "Sibling-deny
               consultation" paragraph above.

Known trade-off (Minor 3, DS-180 round-2 rework): `content/references/
            skeptic-protocol.md` §Round budget and value-per-round gate items
            5 (self-inflicted-round rule) and 6 (continue-vs-reshape signal)
            have no counterpart in the always-loaded kernel
            (`content/sections/05-qa-gate.md` §Re-route limits) - unlike
            item 1's cost-to-date wording, which IS mirrored into both.
            Deliberate: `content/sections/05-qa-gate.md` is embedded
            verbatim into the generated `.claude/skills/dinostack/SKILL.md`,
            which sits close to `check-skill-embed-budget.sh`'s ceiling -
            items 5 and 6 are full paragraphs, not a clause, and do not
            fit. Read `skeptic-protocol.md` directly for those two items;
            do not assume kernel parity with this file's docstring.

DS-178 unit A addition: this hook now also reads the PreToolUse payload's
            top-level `tool_use_id` (best-effort, same convention
            hooks/pre-tool-use-spawn-emit.js already established), records
            it into the round-state file's `tool_use_ids` list (via
            `_append_tool_use_id()`), and maintains a SEPARATE, repo-wide,
            FIFO-capped (500 entries) index file at
            `.agentic/skeptic-tuid-index.json` mapping `{tool_use_id:
            {"unit_key": ..., "iteration": ...}}` (via
            `_update_tuid_index()`; round-2 fix, M3 - the round-1 shape was
            the bare string `{tool_use_id: unit_key}`; round-3 fix, m2
            removed the read-side tolerance for that legacy shape from
            `hooks/subagent-stop-spawn-emit.js`'s `readRoundState()` - this
            file's own `_valid_index_entry()` still ACCEPTS the legacy
            bare-string shape when merging an on-disk index at write time,
            so an old entry is preserved rather than dropped; only the
            reader treats it as a miss). Neither addition can affect the
            allow/deny decision: both run strictly AFTER `_decide()` has
            already produced its verdict, and both are individually
            wrapped fail-open. The index exists so
            `hooks/subagent-stop-spawn-emit.js`'s `readRoundState()` can
            resolve a completed Skeptic spawn's `tool_use_id` to its unit
            key AND the round number that spawn was allowed at in O(1) -
            a single index lookup - rather than scanning `.agentic/` for
            every `skeptic-round-*.json` file on every SubagentStop, and
            without re-reading the unit's LIVE (possibly since-advanced)
            round count for a spawn that may have completed out of order.
            As of the round-3 m2 fix, a legacy bare-string index entry or
            a pinned-but-non-positive iteration is treated as a hard miss
            on read, not a fallback to the round-state file.
            `_load_state`/`_write_state` previously rebuilt/persisted a
            hardcoded 6-key dict, silently dropping any key outside that set
            on the very next persist - `tool_use_ids` had to be added to the
            SCHEMA itself (both functions), not patched in at a call site,
            or it would have been dropped identically.

Downstream consumers: Claude Code hook runner (PreToolUse event for Task and
                      Agent tools, matching enforce-tier.py's dual-matcher
                      wiring). Wired via ~/.claude/settings.json by
                      .claude/install.sh using the GUARDED command form
                      (`test -f <path> && python3 <path> || exit 0`) - a
                      bare `python3 {path}` would exit 2 (BLOCKING on
                      PreToolUse) if this file were ever removed while the
                      registration survives, denying every guarded spawn.
                      `.agentic/skeptic-tuid-index.json` (DS-178 unit A) is
                      read by hooks/subagent-stop-spawn-emit.js's
                      `readRoundState()` for calibration-field lookup.

Failure modes:
    - `_sibling_registered()` cannot positively confirm a sibling's
      registration (no settings-file candidate exists, a candidate is
      unreadable or not valid JSON, or the basename is simply absent from
      every candidate that did parse): that sibling is NOT consulted at
      all for this call - `_sibling_would_deny` skips straight to the next
      sibling. When every sibling is unconfirmed this way, this hook
      persists exactly as it did before the sibling-deny consultation
      existed (charges the round). This is the SAME fail-open direction as
      the bullet immediately below (never a false deny), but the trigger
      is registration uncertainty rather than an import/call failure -
      round-2 rework, Major 1: a registration-blind consultation (the
      round-1 shape) would have treated an installed-but-genuinely-
      unregistered sibling as "would deny" even on a machine where the
      real, active hook set never runs it, silently under-counting real
      rounds an unbounded number of times.
    - A sibling module named in `_SIBLING_MODULES` fails to import
      (missing file, syntax error, a half-applied hooks-snapshot copy) or
      its `would_deny` call raises: `_load_sibling_would_deny_fns()` /
      `_sibling_would_deny()` swallow the error and treat that sibling as
      "would not deny" - this hook then persists exactly as it did before
      the sibling-deny consultation existed. A broken sibling can
      therefore reintroduce the spurious-round-charge defect this
      consultation exists to close, but it can never cause THIS hook to
      deny a spawn it would otherwise have allowed.
    - `_SIBLING_MODULES` covers every registered Task/Agent spawn-matcher
      hook that is deny-capable on a `subagent_type == "skeptic"` spawn
      specifically: `enforce-skeptic-neutrality.py`, `enforce-tier.py`,
      `enforce-background-spawn.py` (a cross-harness-team-active sentinel,
      or an unbackgrounded Task spawn), and `enforce-orchestrator-
      singularity.py` (a nested spawn issued from inside a subagent
      context) - each exposes its own `would_deny(data)`.
      `enforce-worktree-isolation-spawn.py` is also registered on the same
      matcher and is also deny-capable, but not on a skeptic spawn: its
      `MANDATED_ROLES` never includes "skeptic", so it is structurally
      unable to deny one and is deliberately NOT in `_SIBLING_MODULES`.
      See `bin/tests/test_enforce_skeptic_round_cap_sibling_deny.py`'s
      drift-guard test, which classifies every registered spawn-matcher
      hook explicitly (consulted, structurally unable to deny a skeptic
      spawn, or proven never to deny at all) rather than silently passing
      an unclassified one.
    - Malformed stdin, non-dict tool_input, non-Task/Agent tool_name,
      subagent_type != "skeptic": fail-open (exit 0), no enforcement.
    - `cwd` absent from payload: fail-open (exit 0) - the hook cannot
      determine where to persist state.
    - The "Diff under review:" line is absent, malformed (e.g. missing
      the colon), or ambiguous (two or more occurrences in the same field
      carrying DIFFERING values): unit identity unextractable, fail-open
      (exit 0), no state written. This never falls back to a weaker key
      (e.g. the conductor's own branch) that could collide across
      unrelated units - see the CRITICAL fix note at the top of this
      docstring.
    - A present, unambiguous field 6 with no valid key: no `|`, or a left
      side that is empty, contains `..`, fails `_STABLE_KEY_SHAPE_RE`
      (e.g. a diff command piped through `head`), or looks like a file
      path (`_LOOKS_LIKE_FILE_PATH_RE`, e.g. two pipe-separated paths):
      DENIED with `_DENY_KEYLESS_TEMPLATE`. No round state and no tuid
      index entry is written; `_deny()` appends one fire-log line.
    - Known residual: `_LOOKS_LIKE_FILE_PATH_RE` only rejects an
      extension-shaped suffix, so a first path without one (e.g.
      `LICENSE | a.py`, `.gitignore | a.sh`) is accepted as a key and
      shared with any other unit whose first path is identical.
    - State file present but unparsable JSON: treated as absent (round 0)
      - a corrupt state file must never turn into a permanent block.
    - State file write failure (permissions, disk full) within the cap:
      the ALLOW for THIS call still fires; only the persisted round_count
      advance may be lost, so a retried call may see a stale (lower)
      round_count and be permitted again - fail-open, not fail-shut.
    - State file write failure on a grant-allowed round past the cap:
      DENY, the one fail-closed path in this hook (hooks/AGENTS.md
      §Failure-mode discipline). Allowing it would let one grant re-allow
      every retry for as long as the write keeps failing.
    - Past the cap with no `transcript_path`, an unreadable transcript, or
      a failed loop_guard load: no grant is found and the cap deny stands.
      Recovery is option (a) ship, or the operator deleting the unit's
      state file.
    - Two truly concurrent spawns at the cap can both read the same
      pre-advance state and share one grant.
    - An SDK driver's prompt (`claude -p`) is recorded as a genuine user
      turn and counts as operator input. So does a conductor resuming its
      own session headlessly (`claude -p --resume <session> "<token>"`),
      and a hand-forged transcript line: the transcript is
      non-forgeable only against the conductor's ordinary tools, not
      against a deliberate self-resume or file edit.
    - Fingerprint coalescing runs before the cap check: a spawn whose
      "What to review" body is byte-identical to the last allowed round's
      reuses that round's cached ALLOW without a grant, the same way a
      fan-out companion does. The two are indistinguishable here.
    - Concurrent invocations (near-simultaneous parallel fan-out spawns
      landing close enough that one process's write has not yet landed
      before another process's read): fingerprint coalescing handles the
      common case (each companion spawn's hook invocation runs to
      completion - read, decide, write - well within the harness's
      per-spawn dispatch latency) but the ROUND-STATE file
      (`skeptic-round-<unit_key>.json`, `_write_state()`) still has no
      real file lock - a true simultaneous race there can still
      double-charge a round. This is a known residual risk, not claimed
      to be closed; it fails toward over-counting (extra rounds charged),
      never toward under-counting a genuine cap violation, and never
      toward a deny on malfunction. NOTE this is distinct from the
      SEPARATE tuid-index file below, which DOES have a bounded-wait
      lock (M4) around its own read-merge-write.
    - Best-effort dynamic import of `lib/enforcement_log.py` for
      `log_fire()`; any import error falls back to a no-op, matching every
      other enforce-*.py hook's fire-logging pattern.
    - `tool_use_id` absent from the PreToolUse payload, or the
      `.agentic/skeptic-tuid-index.json` write failing for any reason
      (permissions, disk full, corrupt existing index): both
      `_append_tool_use_id()` and `_update_tuid_index()` are individually
      fail-open no-ops - the round-cap allow/deny decision and the
      round-state write are already committed before either runs and are
      never rolled back or retried on this failure. `_update_tuid_index()`'s
      own read-merge-write is guarded by an `flock` (M4 - see
      `_tuid_index_lock()`) with a bounded wait of
      `_TUID_INDEX_LOCK_TIMEOUT_S` (2s, well inside the 5s timeout
      `.claude/install.sh` registers this hook with). If the lock is not
      acquired within that budget, or the lock file cannot be opened, the
      index write is SKIPPED: this spawn's entry is simply absent, so
      `readRoundState()` returns `null` for it. An unlocked write is never
      made on that path, because it would `os.replace` over whatever a
      concurrent locked writer just wrote and silently drop that writer's
      entry. Only on a platform without `fcntl` (non-POSIX), where no
      process can hold the lock at all, does the read-merge-write run
      unlocked.

Performance: measured median ~39 ms per Skeptic spawn (N=60, subprocess
             invocation via `sys.executable`, all four `_SIBLING_MODULES`
             registered on both matchers so `_sibling_would_deny` loads
             and calls all four) - dominated by interpreter startup, not
             this hook's own logic (no subprocess of its own; one small
             JSON read/write under `.agentic/`, plus up to four dynamic
             `importlib` loads of sibling modules on the allow path).
             Under tuid-index lock contention the index write can add up
             to `_TUID_INDEX_LOCK_TIMEOUT_S` (2s) of waiting.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

_ROUND_CAP = 2
_KEY_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
_MAX_KEY_LEN = 80
# Covers: numbered ("6. Diff under review: ..."), hyphen-bullet
# ("- Diff under review: ..."), asterisk-bullet, bold with/without a
# bullet ("- **Diff under review:** ..." / "**Diff under review:** ..."),
# and leading whitespace. The colon is mandatory but its position relative
# to the bold markers is not (`\*{0,2}Diff under review\*{0,2}:\*{0,2}`
# matches the colon whether it sits inside or outside the closing `**`).
# An earlier draft made the colon itself optional (`:?`), which let the
# engine choose NOT to consume it and instead capture the bare colon as
# the identity's first character on an empty field - deliberately not
# repeated. `[ \t]*` (never `\s*`) around the captured value keeps the
# match confined to a single line - `\s*` previously crossed the newline
# after an EMPTY field and captured the next line (e.g. the pasted Worker
# output under "What to review:") as the identity instead of failing open.
# The capture group's first character is `[^\s*]` (never a bare `\S`,
# which also matches `*`): on an empty bolded field with no trailing text
# (e.g. "- **Diff under review:**" with nothing after the closing bold
# marker), the preceding `\*{0,2}:\*{0,2}` can backtrack to consume only
# one of the two closing asterisks so the overall match still succeeds -
# `\S` would then capture the single leftover `*` as a one-character
# "identity", sanitizing to the literal key `*`. Every unit with an empty
# bolded field collided onto that one shared counter, so three malformed
# spawns on unrelated units produced a false DENY on a fourth, unrelated
# unit. Excluding `*` from the capture's first character means that
# leftover-asterisk case yields no capture at all (correctly falls
# through to fail-open) instead of a collidable one-character key.
_DIFF_UNDER_REVIEW_RE = re.compile(
    r"(?im)^[ \t]*(?:[-*][ \t]*)?(?:\d+\.[ \t]*)?\*{0,2}Diff under review\*{0,2}:\*{0,2}[ \t]*([^\s*][^\n]*)$"
)
# Captures everything from "What to review:" to end-of-prompt, deliberately
# UNBOUNDED. A prior draft tried bounding this to stop at the next
# bold-labeled section header (e.g. "**Resolved issues preflight:**"),
# reasoning that a future template might place per-companion text after the
# Worker-output section. That bound was reverted: a realistic pasted
# Worker-output body routinely CONTAINS its own bold-labeled lines (e.g.
# "**What to review:** Worker output below." followed by "**Summary:**
# ..." inside the pasted output itself), so the bound's lookahead matched
# on the FIRST such line and truncated the captured body down to the
# constant intro sentence on every round - measured: 5 sequential rounds
# with genuinely different Worker output all produced the same truncated
# body, hashed to the same fingerprint, and coalesced onto round 1's
# cached ALLOW forever (round_count stayed frozen at 1 across all 5). The
# hypothetical the bound guarded against (a future template reordering
# per-companion text after the Worker-output section) has no evidence of
# ever occurring; the failure it caused - total, silent disablement of the
# round cap - is measured and severe. Do not re-add a bound here without a
# reproduction of the hypothetical it defends against.
_WHAT_TO_REVIEW_RE = re.compile(r"(?is)what to review:?\**\s*(.*)")


def _load_log_fire():
    """Best-effort dynamic import of the shared fire-logging helper.

    Mirrors the identical lazy, try/except-wrapped import pattern used by
    every sibling enforce-*.py hook (see enforce-background-spawn.py) - a
    missing or broken sibling module must never crash this hook.
    """
    try:
        import importlib.util as _ilu

        here = Path(__file__).resolve().parent
        mod_path = here / "lib" / "enforcement_log.py"
        spec = _ilu.spec_from_file_location("enforcement_log", str(mod_path))
        mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)
        return mod.log_fire
    except Exception:
        return lambda *a, **k: None


def _sanitize_key(raw: str) -> str:
    """Map arbitrary text to a safe, bounded .agentic/ filename fragment."""
    safe = _KEY_SAFE_RE.sub("-", raw.strip())
    return safe or "unknown"


# Gates the text before the first "|" in a stable-key-form "Diff under
# review" value (DS-180) so a diff command containing an incidental pipe
# (e.g. a conductor pasting `git diff <sha>..<sha> | head -200`) is never
# mistaken for a key - see _extract_stable_unit_key()'s docstring for the
# measured regression this closes. Letters, digits, dot, underscore,
# hyphen, slash, and "#" only; no whitespace.
_STABLE_KEY_SHAPE_RE = re.compile(r"^[A-Za-z0-9._/#-]+$")

# Rejects a left side that ends in a file-extension-shaped suffix (e.g.
# ".py", ".md", ".ts") - see _extract_stable_unit_key()'s docstring for the
# measured collision this closes (DS-180 round-2 rework). A real stable key
# (ticket id, branch name, `$UNIT_KEY`) never ends this way; a bare file
# path does, by construction. A key that genuinely ends like "v1.2" is
# rejected too, which is why skeptic-protocol.md Section 4.5 has the
# conductor append `-review` to such a key.
_LOOKS_LIKE_FILE_PATH_RE = re.compile(r"\.[A-Za-z0-9]{1,5}$")


def _extract_stable_unit_key(raw: str) -> str | None:
    """Extract the stable unit key from a "Diff under review" value in the
    `<key> | <diff detail>` form mandated by skeptic-protocol.md Section 4.5
    "Stable unit key contract", or None when the value carries no valid key.

    The key is the only round-cap identity: no heuristic over the diff
    detail is tried, because none survives a rolling `<prior-head>..<new-head>`
    range or a round-numbered prose prefix (PR #760, KNW-20260814-022).

    Leading/trailing backticks are stripped first (a conductor may render
    the whole value as inline code). The left side of the first `|` is
    rejected when it is empty, contains `..`, fails `_STABLE_KEY_SHAPE_RE`
    (whitespace or a character outside the key charclass, e.g. a diff
    command piped through `head`: `git diff <sha>..<sha> | head -200`), or
    ends in a file-extension-shaped suffix (`_LOOKS_LIKE_FILE_PATH_RE`: two
    pipe-separated file paths would otherwise make the shared first path a
    key that collides across units). A None here for a present field 6 is
    denied by main(); it is never a collidable placeholder.
    """
    text = raw.strip().strip("`").strip()
    if "|" not in text:
        return None
    left, _, _rest = text.partition("|")
    left = left.strip()
    if (
        not left
        or ".." in left
        or not _STABLE_KEY_SHAPE_RE.match(left)
        or _LOOKS_LIKE_FILE_PATH_RE.search(left)
    ):
        return None
    return left


def _extract_field6_value(tinput: dict) -> str | None:
    """Return the single "Diff under review:" value of the Skeptic spawn,
    or None when it is absent or ambiguous.

    Reads the `## Global-context inputs` item 6 line that
    skeptic-protocol.md Section 4.5 mandates, from `prompt`, falling back
    to `description` only when `prompt` has no such line. Two or more lines
    with DIFFERING values in one field are ambiguous and return None: the
    caller fails open rather than guess, and never falls back to a weaker
    key such as the conductor's own branch.
    """
    for field in ("prompt", "description"):
        value = tinput.get(field)
        text = value if isinstance(value, str) else ""
        if not text:
            continue
        raw_values = []
        for match in _DIFF_UNDER_REVIEW_RE.finditer(text):
            candidate = match.group(1).strip()
            if candidate:
                raw_values.append(candidate)
        if not raw_values:
            continue
        if len(set(raw_values)) > 1:
            return None
        return raw_values[0]
    return None


def _unit_key(tinput: dict) -> str | None:
    """Return a safe, bounded, collision-resistant .agentic/ key for the
    unit under review, or None when field 6 is absent, ambiguous, or
    keyless."""
    value = _extract_field6_value(tinput)
    if not value:
        return None
    identity = _extract_stable_unit_key(value)
    if not identity:
        return None
    sanitized = _sanitize_key(identity)[:_MAX_KEY_LEN]
    digest = hashlib.sha1(identity.encode("utf-8", "replace")).hexdigest()[:10]
    return f"{sanitized}-{digest}"


def _keyless_field6_value(tinput: dict) -> str | None:
    """Return field 6's value when it is present and unambiguous but
    carries no valid key, else None."""
    value = _extract_field6_value(tinput)
    if value and _extract_stable_unit_key(value) is None:
        return value
    return None


def _round_fingerprint(tinput: dict) -> str | None:
    """Hash of the "What to review:" section (the pasted Worker output) of
    the spawn prompt, or None when that section is absent.

    Two Skeptic spawns reviewing the SAME Worker output (a
    `skeptic_strategy: multi-dimensional` fan-out: correctness-Skeptic +
    security-auditor + perf-analyst reviewing one round's diff from three
    angles) produce identical fingerprints and are companions of the same
    round. A genuinely new round always carries new Worker output (the
    latest engineer fix), so its fingerprint differs. Absence (None) means
    coalescing never triggers for that call - every call is its own round,
    the conservative default that never under-counts a real cap violation.
    """
    prompt = tinput.get("prompt")
    text = prompt if isinstance(prompt, str) else ""
    if not text:
        return None
    match = _WHAT_TO_REVIEW_RE.search(text)
    if not match:
        return None
    body = match.group(1).strip()
    if not body:
        return None
    return hashlib.sha1(body.encode("utf-8", "replace")).hexdigest()


def _load_repo_root():
    """Best-effort dynamic import of hooks/lib/repo_root.py (mirrors
    _load_log_fire above). Returns None on any load failure - callers
    must skip the .agentic/ read/write rather than fall back to a raw cwd.
    """
    try:
        import importlib.util as _ilu

        here = Path(__file__).resolve().parent
        mod_path = here / "lib" / "repo_root.py"
        spec = _ilu.spec_from_file_location("repo_root", str(mod_path))
        mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_REPO_ROOT = _load_repo_root()


def _load_loop_guard():
    """Best-effort dynamic import of hooks/lib/loop_guard.py (same pattern as
    _load_repo_root). Returns None on any load failure, which
    `_operator_granted` treats as "no grant found"."""
    try:
        import importlib.util as _ilu

        here = Path(__file__).resolve().parent
        mod_path = here / "lib" / "loop_guard.py"
        spec = _ilu.spec_from_file_location("loop_guard", str(mod_path))
        mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _grant_token(unit_key: str, next_round: int) -> str:
    """The token an operator types to authorize round `next_round` of
    `unit_key`. Binding both means a grant cannot be reused on another unit
    or, once round_count advances, on a later round of this one."""
    digest = hashlib.sha1(f"{unit_key}#{next_round}".encode("utf-8", "replace")).hexdigest()[:8]
    return f"skeptic-grant-{digest}"


def _origin_kind(record: dict) -> object:
    origin = record.get("origin")
    return origin.get("kind") if isinstance(origin, dict) else None


def _content_texts(content: object) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    return [
        b["text"]
        for b in content
        if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
    ]


def _operator_texts(obj: dict, loop_guard) -> list[str]:
    """Texts of one transcript line that record a genuine operator message.
    Three line shapes do (census of every main-session transcript on the
    authoring host):
      - a `user` line with `origin.kind` "human": a typed turn, image plus
        text, or a slash command with its arguments;
      - a `queued_command` attachment with `origin.kind` "human": a message
        typed while the conductor was mid-turn, which Claude Code records
        only in this shape;
      - an origin-less `user` line loop_guard classifies as genuine: `claude
        -p` prompts, Claude Desktop, and CLI builds that predate `origin`.
    A queued attachment without a human origin is a cross-session relay, and
    a `queue-operation` line carries no origin at all; neither counts."""
    kind = obj.get("type")
    if kind == "attachment":
        att = obj.get("attachment")
        if (
            isinstance(att, dict)
            and att.get("type") == "queued_command"
            and _origin_kind(att) == "human"
        ):
            return _content_texts(att.get("prompt"))
        return []
    if kind == "user" and _origin_kind(obj) == "human":
        msg = obj.get("message")
        return _content_texts(msg.get("content") if isinstance(msg, dict) else None)
    text = loop_guard.genuine_user_text(obj)
    return [text] if isinstance(text, str) else []


def _operator_granted(transcript_path: object, token: str) -> bool:
    """True when a genuine operator turn in the MAIN-SESSION transcript
    contains `token` (case-insensitive). Never raises; any error is False.

    Reads only the payload's `transcript_path`, never the SubagentStop-only
    agent transcript or a `subagents/` transcript: conductor-authored spawn
    briefs land as user-shaped lines there, which would make the grant
    self-issuable (same hazard as enforce-ticket-batching.py's
    non-forgeability note). Compaction summaries and sidechain lines pass
    loop_guard's classifier but are not operator input, so they are skipped
    here. See `_operator_texts` for the line shapes that count."""
    try:
        if not isinstance(transcript_path, str) or not transcript_path:
            return False
        if "/subagents/" in transcript_path.replace(os.sep, "/"):
            return False
        loop_guard = _load_loop_guard()
        if loop_guard is None:
            return False
        needle = token.lower()
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if needle not in line.lower():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                if obj.get("isCompactSummary") is True:
                    continue
                if obj.get("isSidechain") is True:
                    continue
                if any(needle in text.lower() for text in _operator_texts(obj, loop_guard)):
                    return True
        return False
    except Exception:
        return False


# Sibling PreToolUse hooks (registered on the SAME "Task"/"Agent" spawn
# matcher, .claude/install.sh ~:1249-1283) that can independently DENY a
# `subagent_type == "skeptic"` spawn this hook would otherwise ALLOW. Each
# exposes a pure `would_deny(data: dict) -> str | None` function (same
# top-level PreToolUse payload shape this hook's own `main()` reads from
# stdin) - see enforce-skeptic-neutrality.py's, enforce-tier.py's,
# enforce-background-spawn.py's, and enforce-orchestrator-singularity.py's
# own `would_deny` docstrings. Consulted in `main()` before any persistence
# call (`_write_state` / `_append_tool_use_id` / `_update_tuid_index`),
# and only when `_sibling_registered()` positively confirms that entry's
# registration: a spawn a CONSULTED sibling would deny must never advance
# round_count (which also spends an operator grant), or the operator's
# round budget or grant is spent on a review that never ran
# (content/references/skeptic-protocol.md §Round budget and value-per-round
# gate, item 1). See `bin/tests/test_enforce_skeptic_round
# _cap_sibling_deny.py`'s drift-guard test for the enumeration of
# registered spawn-matcher hooks this list is checked against.
_SIBLING_MODULES = (
    "enforce-skeptic-neutrality",
    "enforce-tier",
    "enforce-background-spawn",
    "enforce-orchestrator-singularity",
)

# Every OTHER hook registered on the same "Task"/"Agent" spawn matcher
# (.claude/install.sh) that is genuinely deny-capable but structurally
# CANNOT deny a `subagent_type == "skeptic"` spawn specifically - e.g.
# `enforce-worktree-isolation-spawn.py`, whose `MANDATED_ROLES`
# (`{"engineer", "qa-engineer", "release-orchestrator"}`) never includes
# "skeptic" - is out of scope for consultation, not a tracked gap. There is
# no "known unconsulted deny-capable" set here: a future deny-capable hook
# registered on the same matcher must be added to `_SIBLING_MODULES` above
# (if it can deny a skeptic spawn) or proven structurally unable to
# (`bin/tests/test_enforce_skeptic_round_cap_sibling_deny.py`'s
# `_CANNOT_DENY_SKEPTIC` classification) - the drift-guard test fails on
# an unclassified registered hook either way.

# Harness config-dir env vars, in detection precedence order - mirrors
# bin/_lib.py's resolve_claude_config_dir() / hooks/lib/config-dir.js's
# resolveClaudeConfigDir() (same four vars, same precedence). Duplicated
# here rather than imported: hooks/ is stdlib-only by convention (see this
# module's own Upstream deps) and bin/_lib.py is not part of that
# contract.
_CONFIG_DIR_ENV = ("AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "PI_CODING_AGENT_DIR")


def _resolve_claude_config_dir() -> Path:
    for var in _CONFIG_DIR_ENV:
        raw = os.environ.get(var, "").strip()
        if raw:
            return Path(os.path.abspath(os.path.expanduser(raw)))
    return Path(os.path.expanduser("~/.claude"))


def _settings_candidates(cwd: str) -> list[Path]:
    """User-level `settings.json` under the resolved harness config dir,
    plus every project-level `settings*.json` under the reviewed unit's
    OWN repo root's `.claude/` dir (resolved the same `.git`-ancestor way
    `_state_path` resolves `.agentic/`, never a raw possibly-drifted cwd).
    Order does not matter to the caller - `_sibling_registered` treats
    this as an unordered OR across every candidate."""
    candidates = [_resolve_claude_config_dir() / "settings.json"]
    if _REPO_ROOT is not None:
        try:
            diag = _REPO_ROOT.resolve_agentic_cwd_with_diagnostics(cwd)
        except Exception:
            diag = None
        if diag and diag.get("found_git_ancestor"):
            claude_dir = Path(diag["root"]) / ".claude"
            try:
                if claude_dir.is_dir():
                    candidates.extend(sorted(claude_dir.glob("settings*.json")))
            except Exception:
                pass
    return candidates


def _hook_registered_in_settings(raw: object, basename: str, tool_name: str) -> bool:
    """True iff *raw* (an already-parsed settings.json payload) carries a
    PreToolUse block matched EXACTLY on *tool_name* (the spawn's own
    "Task" or "Agent" - round-2 rework, Minor 2: a prior version accepted
    a match on EITHER matcher regardless of the spawn's actual tool_name,
    so a sibling registered only on "Task" would be treated as consulted
    for an "Agent" spawn it is never actually invoked for, and vice
    versa) containing a `hooks[]` entry whose `command` string references
    *basename* as a path segment (`/<basename>`) - the shape every real
    settings.json command takes, guarded (`test -f ... && python3 <path>
    || exit 0`) or bare. A malformed/unexpected shape at any level is
    treated as "not found in this candidate", never raises."""
    if not isinstance(raw, dict):
        return False
    hooks = raw.get("hooks")
    if not isinstance(hooks, dict):
        return False
    ptu = hooks.get("PreToolUse")
    if not isinstance(ptu, list):
        return False
    needle = "/" + basename
    for block in ptu:
        if not isinstance(block, dict) or block.get("matcher") != tool_name:
            continue
        entries = block.get("hooks")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            cmd = entry.get("command")
            if isinstance(cmd, str) and needle in cmd:
                return True
    return False


def _sibling_registered(basename: str, cwd: str, tool_name: str) -> bool:
    """True only when *basename* is POSITIVELY found registered on the
    Task/Agent PreToolUse matcher, on the matcher covering the spawn's own
    `tool_name`, in at least one of: the user-level `settings.json` under
    the resolved harness config dir, or this unit's own project-level
    `.claude/settings*.json`. A higher-precedence managed/enterprise
    settings file (e.g. macOS `/Library/Application Support/ClaudeCode/
    managed-settings.json`, Linux `/etc/claude-code/managed-settings.json`)
    is deliberately NOT read - a sibling registered ONLY there is treated
    as "not confirmed" and therefore NOT consulted (round-2 rework, Minor
    4): a disclosed, accepted residual (the original spurious-round-charge
    defect this whole consultation exists to close can still occur for
    that narrow case, since the sibling is genuinely active and will
    independently deny while round-cap still persists), traded for the
    stronger guarantee that this function never returns True on a
    registration it cannot actually verify. Every uncertain case - no
    candidate file
    exists, a candidate is unreadable, a candidate is malformed JSON, or
    the basename is simply absent from every candidate that DID parse -
    returns False, the SAME "not confirmed" outcome, by design (Major 1,
    round-2 rework): an unregistered sibling (an install between
    2026-08-12 and 2026-08-24 whose hooks-snapshot was refreshed by
    `ds-doctor --fix` without re-running `install.sh`, or an operator who
    hand-deleted the entry) must never be treated as "would deny" - that
    would silently charge no round for a Skeptic spawn that actually ran
    uncharged, an unbounded number of times. `_sibling_would_deny` treats
    False here identically to a sibling that raised on import/call:
    persist exactly as this hook did before the sibling-deny consultation
    existed."""
    for path in _settings_candidates(cwd):
        try:
            if not path.is_file():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if _hook_registered_in_settings(raw, basename, tool_name):
            return True
    return False


def _load_sibling_would_deny_fns():
    """Best-effort dynamic import of each `_SIBLING_MODULES` entry's
    `would_deny` function (importlib by path, mirroring `_load_log_fire`/
    `_load_repo_root` above). Returns a list of `(basename, fn)` pairs; a
    sibling that fails to import or lacks a `would_deny` attribute is
    silently skipped - never raises, never blocks this hook's own
    decision."""
    fns = []
    here = Path(__file__).resolve().parent
    for name in _SIBLING_MODULES:
        try:
            import importlib.util as _ilu

            mod_path = here / f"{name}.py"
            spec = _ilu.spec_from_file_location(name.replace("-", "_"), str(mod_path))
            mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
            spec.loader.exec_module(mod)
            fn = getattr(mod, "would_deny", None)
            if callable(fn):
                fns.append((f"{name}.py", fn))
        except Exception:
            continue
    return fns


def _sibling_would_deny(data: dict, cwd: str, tool_name: str) -> str | None:
    """Returns the first non-None deny reason any CONSULTED sibling hook's
    `would_deny(data)` returns for this exact payload, or None if none
    would deny (including when none is consulted at all). A sibling is
    consulted only when `_sibling_registered` positively confirms its
    registration, ON THE MATCHER COVERING *tool_name* specifically, for
    this unit's own settings files - see that function's docstring for
    why every uncertain case (including a registration on the OTHER
    matcher only) is treated as "not consulted" rather than "would not
    deny" vs. "would deny". Fail direction: an import or call failure on
    any sibling is swallowed and treated as "would not deny" for THAT
    sibling - a sibling failure must never change this hook's own
    persistence behavior (this hook persists exactly as it did before
    this consultation existed)."""
    for basename, fn in _load_sibling_would_deny_fns():
        if not _sibling_registered(basename, cwd, tool_name):
            continue
        try:
            reason = fn(data)
        except Exception:
            continue
        if reason:
            return reason
    return None


def _state_path(cwd: str, key: str) -> Path | None:
    """Returns None when the repo root cannot be resolved - callers must
    skip the read/write on None rather than fall back to a raw cwd.

    Round-3 rework (Major 2): this previously called the plain
    `resolve_agentic_cwd()` and never consulted `found_git_ancestor`, so
    the round counter still wrote at the unresolved fallback root (the
    realpath'd raw cwd) on a "no .git ancestor found" cwd - contradicting
    both this hook's own docstring and hooks/lib/repo_root.py's own
    Failure modes section, which name this hook as one of only two
    callers in the repo that genuinely implement the strict "write at the
    wrong location would actively corrupt cross-session state" SKIP
    discipline. Now consults `found_git_ancestor` explicitly via
    resolve_agentic_cwd_with_diagnostics and returns None (skip) when it
    is False, matching the manifest's stated tier."""
    if _REPO_ROOT is None:
        return None
    try:
        diag = _REPO_ROOT.resolve_agentic_cwd_with_diagnostics(cwd)
    except Exception:
        return None
    if not diag.get("found_git_ancestor"):
        return None
    return Path(diag["root"]) / ".agentic" / f"skeptic-round-{key}.json"


# Keys `_load_state`/`_write_state` know about and manage directly. Any
# OTHER top-level key found on disk is preserved verbatim via the `_extra`
# passthrough bucket below (round-2 fix, m4) - see both functions'
# docstrings for what this closes.
_KNOWN_STATE_KEYS = frozenset({
    "round_count", "last_round_fingerprint",
    "last_decision_allow", "last_decision_reason", "tool_use_ids",
    "unit_key", "last_updated",
})


def _load_state(path: Path) -> dict:
    """Round state for one unit. `tool_use_ids` (DS-178 unit A) is the
    ordered, deduped list of PreToolUse `tool_use_id` values seen for this
    unit's rounds - it exists so `main()` can maintain the
    `.agentic/skeptic-tuid-index.json` FIFO index that
    `hooks/subagent-stop-spawn-emit.js` reads for O(1) calibration lookup.

    Round-2 fix (m4): the round-1 commit message claimed `_load_state`/
    `_write_state` "no longer silently drop schema fields outside a
    hardcoded 6-key dict" - true only for `tool_use_ids` itself, which WAS
    added to the schema. A differential against `main` showed a state file
    carrying a genuinely unknown key (e.g. a hand-added `extra_key`, or a
    `nested` object) still lost it on the very next round-trip, on BOTH
    `main` and the round-1 branch - the hardcoded key list just grew from
    6 to 7. This function now preserves any top-level key NOT in
    `_KNOWN_STATE_KEYS` verbatim in an `_extra` passthrough bucket, which
    `_write_state()` merges back into the persisted JSON (not left as a
    literal `_extra` sub-object) on write - so the round-trip claim is
    actually true now, for any key, not just the ones this file happens to
    know about today."""
    default = {
        "round_count": 0,
        "last_round_fingerprint": None,
        "last_decision_allow": None,
        "last_decision_reason": "",
        "tool_use_ids": [],
        "_extra": {},
    }
    try:
        if not path.is_file():
            return default
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default
        fingerprint = raw.get("last_round_fingerprint")
        raw_tool_use_ids = raw.get("tool_use_ids")
        tool_use_ids = (
            [tid for tid in raw_tool_use_ids if isinstance(tid, str)]
            if isinstance(raw_tool_use_ids, list)
            else []
        )
        extra = {k: v for k, v in raw.items() if k not in _KNOWN_STATE_KEYS}
        return {
            "round_count": raw.get("round_count", 0) if isinstance(raw.get("round_count"), int) else 0,
            "last_round_fingerprint": fingerprint if isinstance(fingerprint, str) else None,
            "last_decision_allow": raw.get("last_decision_allow") if isinstance(raw.get("last_decision_allow"), bool) else None,
            "last_decision_reason": raw.get("last_decision_reason") if isinstance(raw.get("last_decision_reason"), str) else "",
            "tool_use_ids": tool_use_ids,
            "_extra": extra,
        }
    except Exception:
        return default


def _write_state(path: Path, unit_key: str, state: dict) -> bool:
    """Best-effort atomic write - tmp file + os.replace, pid-suffixed.
    Returns True only when os.replace succeeded.

    Round-2 fix (m4): unpacks the `_extra` passthrough bucket `_load_state`
    populated (any key that was present on disk but outside this file's
    own known-key schema) back into the top-level persisted payload,
    rather than persisting it as a literal `_extra` sub-object or dropping
    it - a genuinely unknown key now survives a load-then-write round trip
    unchanged, as long as it does not collide with a key this file
    actively manages (an active-schema key always wins over a stale
    passthrough value of the same name)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(state)
        extra = payload.pop("_extra", None)
        if isinstance(extra, dict):
            for k, v in extra.items():
                if k not in payload:
                    payload[k] = v
        payload["unit_key"] = unit_key
        payload["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tmp_path = path.with_suffix(f".tmp.{os.getpid()}")
        tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, path)
        return True
    except Exception:
        # Within the cap a lost persist fails open (a retry may see a stale
        # round_count). main() denies a grant-allowed round that this
        # returns False for, or one grant would re-allow on every retry.
        return False


def _append_tool_use_id(state: dict, tool_use_id: str | None) -> dict:
    """Return *state* with *tool_use_id* appended to `tool_use_ids` (deduped,
    order-preserving) when present. Never mutates the input dict. A missing
    or blank tool_use_id is a no-op - the harness is not guaranteed to
    thread it through on every PreToolUse call (see the DS-160 best-effort
    convention hooks/pre-tool-use-spawn-emit.js already documents)."""
    if not isinstance(tool_use_id, str) or not tool_use_id.strip():
        return state
    tid = tool_use_id.strip()
    existing = state.get("tool_use_ids")
    ids = list(existing) if isinstance(existing, list) else []
    if tid not in ids:
        ids.append(tid)
    new_state = dict(state)
    new_state["tool_use_ids"] = ids
    return new_state


_TUID_INDEX_NAME = "skeptic-tuid-index.json"
_TUID_INDEX_CAP = 500
# Bounded poll for the index lock (M4): 10ms retries for up to 2s. Must stay
# well under the 5s hook timeout `.claude/install.sh` registers; on expiry the
# index write is skipped, never made unlocked.
_TUID_INDEX_LOCK_TIMEOUT_S = 2.0
_TUID_INDEX_LOCK_RETRY_S = 0.01


def _valid_index_entry(value: object) -> bool:
    """True for either index-entry shape this file has ever written:
    a legacy bare `unit_key` string (pre-round-2), or the round-2
    `{"unit_key": str, "iteration": int}` pinned-iteration shape (M3).
    Used to sanitize an on-disk index before merging - an entry in neither
    shape is dropped rather than silently propagated."""
    if isinstance(value, str) and value:
        return True
    if (
        isinstance(value, dict)
        and isinstance(value.get("unit_key"), str)
        and value.get("unit_key")
        and isinstance(value.get("iteration"), int)
    ):
        return True
    return False


def _update_tuid_index(agentic_dir: Path, tool_use_id: str | None, unit_key: str, iteration: int) -> None:
    """Best-effort maintenance of `.agentic/skeptic-tuid-index.json`, an
    O(1)-lookup FIFO index capped at `_TUID_INDEX_CAP` entries (oldest
    evicted first) that `hooks/subagent-stop-spawn-emit.js`'s
    `readRoundState()` reads to find a completed spawn's round-state
    correlation without scanning the `.agentic/` directory. Fully
    fail-open: any error here must never affect the round-cap allow/deny
    decision, and this is called strictly AFTER that decision has already
    been made.

    Round-2 fixes:
      - M3: each entry now stores `{"unit_key": unit_key, "iteration":
        iteration}` - the round number THIS spawn was allowed at, pinned
        at spawn time - not just the bare `unit_key` string the round-1
        schema stored. Before this fix, `readRoundState()` had to re-read
        the unit's LIVE round-state file at SubagentStop time to get
        `iteration`, which is wrong for any out-of-order completion (a
        later round can complete before an earlier one, or the state can
        simply have advanced by the time SubagentStop fires) - it reports
        the CURRENT round count, not the round this particular spawn was
        actually allowed at. Round-3 fix (m2, `subagent-stop-spawn-emit.js`
        `readRoundState()`): the live-read fallback for a pre-existing
        LEGACY (bare-string) entry was REMOVED, not merely narrowed - a
        legacy entry, or any pinned entry whose `iteration` is missing,
        non-numeric, zero, or negative, is now treated as an outright miss
        (returns `null`), never re-read live. This function's own
        `_valid_index_entry()` filter still ACCEPTS a legacy bare-string
        entry when merging the on-disk index (so a pre-round-2 entry is
        not evicted or corrupted on write), but the READER on the JS side
        never resolves one to a hit - a legacy entry simply sits inert
        until it ages out of the FIFO cap or is overwritten by a fresh
        pinned-shape write for the same `tool_use_id`.
      - M4: the read-merge-write sequence below is guarded by an `flock`
        (POSIX only - see `_tuid_index_lock()`), closing the
        concurrent-write data loss a
        parallel multi-dimensional fan-out (several Skeptic-family spawns
        reviewing the same unit, each with its own SubagentStop) could
        previously produce: two processes could both read the
        pre-update index, each add their own entry, and whichever wrote
        LAST would silently clobber the other's entry entirely (measured:
        6 parallel writers produced 4 entries and lost 2). The lock wait
        is bounded (`_TUID_INDEX_LOCK_TIMEOUT_S`); when the lock cannot be
        acquired (timeout, or the lock file cannot be opened) the write is
        SKIPPED, because an unlocked write would clobber a concurrent
        locked writer's entry. A skipped write is a missing entry, which
        the reader already treats as a miss. Only when `fcntl` is
        unavailable does the write run unlocked."""
    if not isinstance(tool_use_id, str) or not tool_use_id.strip():
        return
    tid = tool_use_id.strip()
    index_path = agentic_dir / _TUID_INDEX_NAME
    try:
        agentic_dir.mkdir(parents=True, exist_ok=True)
        lock = _tuid_index_lock(agentic_dir)
        if lock is None:
            return
        with lock:
            index: dict = {}
            if index_path.is_file():
                try:
                    raw = json.loads(index_path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        index = {
                            k: v for k, v in raw.items()
                            if isinstance(k, str) and _valid_index_entry(v)
                        }
                except Exception:
                    index = {}
            # Move-to-end-on-update semantics: re-inserting an existing key
            # refreshes its FIFO position (dict insertion order in Python
            # 3.7+).
            index.pop(tid, None)
            index[tid] = {"unit_key": unit_key, "iteration": iteration}
            while len(index) > _TUID_INDEX_CAP:
                oldest_key = next(iter(index))
                index.pop(oldest_key, None)
            tmp_path = index_path.with_suffix(f".tmp.{os.getpid()}")
            tmp_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp_path, index_path)
    except Exception:
        pass


class _NullLock:
    """No-op context manager, used only when `fcntl` is unavailable
    (non-POSIX), where no process can hold the index lock."""

    def __enter__(self) -> "_NullLock":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _tuid_index_lock(agentic_dir: Path):
    """`flock`-based mutual exclusion (M4) around the tuid index's
    read-merge-write sequence, polling for up to
    `_TUID_INDEX_LOCK_TIMEOUT_S`. Returns a held lock context manager on
    success, `_NullLock()` when `fcntl` is unavailable (non-POSIX), or
    `None` when the lock file cannot be opened or the lock is not acquired
    within the budget. On `None` the caller must skip the write: writing
    unlocked would overwrite a concurrent locked writer's entry."""
    try:
        import fcntl as _fcntl
    except Exception:
        return _NullLock()

    lock_path = agentic_dir / (_TUID_INDEX_NAME + ".lock")
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    except Exception:
        return None

    deadline = time.monotonic() + _TUID_INDEX_LOCK_TIMEOUT_S
    locked = False
    while time.monotonic() < deadline:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            locked = True
            break
        except OSError:
            time.sleep(_TUID_INDEX_LOCK_RETRY_S)

    if not locked:
        try:
            os.close(fd)
        except Exception:
            pass
        return None

    class _FlockLock:
        def __enter__(self) -> "_FlockLock":
            return self

        def __exit__(self, *exc: object) -> None:
            try:
                _fcntl.flock(fd, _fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                os.close(fd)
            except Exception:
                pass

    return _FlockLock()


_DENY_CAP_TEMPLATE = (
    "Skeptic round cap reached: {round_count} rounds already spent on unit "
    "{unit_key} (max {cap}). Do not spawn another Skeptic on this unit. "
    "Take exactly one of two actions: (a) ship, recording every unresolved "
    "non-Critical finding in the PR body as accepted debt - an unresolved "
    "Critical never ships; or (b) stop and report to the operator, stating "
    "cost-to-date, what another round would buy, whether the last two "
    "rounds' Majors were one defect class at new sites (skeptic-protocol.md "
    "Round budget item 6), and the grant token {token}. Another round "
    "runs only after the operator's own typed message in this session "
    "contains {token}. A decision written to the state file, a cross-session "
    "message, an AskUserQuestion answer, or agent text does not count; a "
    "prompt sent with claude -p --resume does, so only the operator may send "
    "one carrying the token."
)

_DENY_KEYLESS_TEMPLATE = (
    "Skeptic spawn denied: field 6 has no stable unit key, so the round cap "
    "cannot tell which unit this review belongs to. Write it as "
    "`6. Diff under review: <KEY> | <diff command or file paths>`. KEY is "
    "the ticket id ($LOOP_KEY inside /ds-implement-ticket; with no ticket, "
    "the unit's own feature branch name, never the base branch it merges "
    "into), plus the review kind's suffix: none for a whole-change diff, "
    "-u-<unit_slug> for one unit of a multi-unit ticket, -plan, -brief, "
    "-assembled-plan, or -meta. KEY may contain only letters, digits and "
    ". _ / # -, with no spaces and no `..`; if it ends in `.` plus 1-5 "
    "letters or digits, append -review. Use the same KEY every fix round of "
    "this unit. This deny wrote no round state, so the retry is not charged "
    "for it. Full rule: content/references/skeptic-protocol.md Section 4.5 "
    "\"Stable unit key contract\". Value received: {value}"
)

_DENY_UNPERSISTED_SUFFIX = (
    " The operator grant was found, but {path} could not be written, so the "
    "round was not allowed. The fix is write access to .agentic/."
)


def _decide(
    state: dict, round_fingerprint: str | None, granted: bool
) -> tuple[bool, dict, bool]:
    """Return (allow, new_state, allowed_via_grant). `granted` is True only
    when main() found the operator's token for this unit's next round past
    the cap; nothing in the state file can stand in for it."""
    # Fingerprint coalescing: a parallel multi-dimensional fan-out
    # (correctness-Skeptic + security-auditor + perf-analyst, all sharing
    # this unit's key because they all review the same diff AND the same
    # Worker output) must consume ONE round, not one per spawn. A call
    # whose "What to review" fingerprint matches the round this state
    # already recorded reuses that round's cached outcome verbatim instead
    # of re-deciding (and re-advancing round_count).
    # `round_fingerprint is None` (no "What to review:" section found)
    # never coalesces - every such call is treated as its own round.
    if (
        round_fingerprint is not None
        and state.get("last_round_fingerprint") == round_fingerprint
        and state.get("last_decision_allow") is not None
    ):
        return bool(state["last_decision_allow"]), state, False

    next_round = state["round_count"] + 1
    if next_round > _ROUND_CAP and not granted:
        return False, state, False

    new_state = dict(state)
    new_state["round_count"] = next_round
    new_state["last_round_fingerprint"] = round_fingerprint
    new_state["last_decision_allow"] = True
    new_state["last_decision_reason"] = ""
    return True, new_state, next_round > _ROUND_CAP


def _deny(data: dict, reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    try:
        _load_log_fire()(data, "enforce-skeptic-round-cap", "deny", reason)
    except Exception:
        pass
    sys.exit(0)


def main() -> None:
    try:
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        if not isinstance(data, dict):
            sys.exit(0)

        tool_name = data.get("tool_name")
        if tool_name not in ("Task", "Agent"):
            sys.exit(0)

        raw_tinput = data.get("tool_input")
        tinput = raw_tinput if isinstance(raw_tinput, dict) else {}
        if tinput.get("subagent_type") != "skeptic":
            sys.exit(0)

        cwd = data.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            sys.exit(0)

        # Best-effort: the PreToolUse payload's top-level `tool_use_id`
        # field (same read the hook did not previously make - see
        # hooks/pre-tool-use-spawn-emit.js for the established convention).
        # Absent on some harness versions; never required for the round-cap
        # decision itself, only for the tuid-index calibration lookup.
        raw_tool_use_id = data.get("tool_use_id")
        tool_use_id = (
            raw_tool_use_id.strip()
            if isinstance(raw_tool_use_id, str) and raw_tool_use_id.strip()
            else None
        )

        unit_key = _unit_key(tinput)
        if unit_key is None:
            keyless = _keyless_field6_value(tinput)
            if keyless is not None:
                _deny(data, _DENY_KEYLESS_TEMPLATE.format(value=keyless[:120]))
                return
            # Field 6 absent or ambiguous - fail open. Never fall back to a
            # weaker key (e.g. the conductor's own branch) that could
            # collide across unrelated units.
            sys.exit(0)

        path = _state_path(cwd, unit_key)
        if path is None:
            # Repo root could not be resolved - skip the read/write entirely
            # rather than fall back to a raw (possibly drifted) cwd.
            sys.exit(0)
        state = _load_state(path)

        next_round = state["round_count"] + 1
        token = _grant_token(unit_key, next_round)
        granted = next_round > _ROUND_CAP and _operator_granted(data.get("transcript_path"), token)
        cap_reason = _DENY_CAP_TEMPLATE.format(
            round_count=state["round_count"], unit_key=unit_key, cap=_ROUND_CAP, token=token
        )

        allow, new_state, allowed_via_grant = _decide(state, _round_fingerprint(tinput), granted)

        if not allow:
            _deny(data, cap_reason)
            return

        # A REGISTERED sibling PreToolUse hook on this same spawn matcher
        # (see `_SIBLING_MODULES`) will independently deny this exact
        # spawn - Claude Code runs every matcher hook regardless of
        # another hook's decision, so the sibling's own deny still blocks
        # the spawn. Skip ALL persistence in that case: round_count
        # (and with it any operator grant) must not advance for a spawn
        # that never actually ran as a review. `_sibling_would_deny` only consults a sibling whose
        # registration `_sibling_registered` positively confirms - an
        # unconfirmed sibling (unregistered, or registration undetermined)
        # is never consulted, so this call persists exactly as today.
        if _sibling_would_deny(data, cwd, tool_name) is not None:
            sys.exit(0)

        new_state = _append_tool_use_id(new_state, tool_use_id)
        persisted = _write_state(path, unit_key, new_state)
        if allowed_via_grant and not persisted:
            _deny(data, cap_reason + _DENY_UNPERSISTED_SUFFIX.format(path=path))
            return
        # Index maintenance happens strictly AFTER the allow decision and
        # the round-state write, and is fully fail-open - it must never
        # influence the allow/deny path above. `new_state["round_count"]`
        # is the round number THIS spawn was just allowed at (M3) - pinned
        # into the index entry now, rather than left for
        # readRoundState() to re-derive from whatever the unit's round
        # count happens to be at SubagentStop time.
        _update_tuid_index(path.parent, tool_use_id, unit_key, new_state["round_count"])
        sys.exit(0)
    except Exception:
        # Any unexpected error anywhere in the decision path fails open -
        # a hook bug must never block Skeptic spawns outright.
        sys.exit(0)


if __name__ == "__main__":
    main()
