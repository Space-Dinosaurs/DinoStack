#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that mechanically enforces the ad-hoc Skeptic
         round-budget policy (content/sections/05-qa-gate.md §Re-route
         limits, content/references/skeptic-protocol.md §Round budget and
         value-per-round gate): a max of 3 Skeptic rounds per unit before the
         conductor must record an explicit `ship` or `escalate` decision.
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
         unit B's budget. Instead the key is derived from the "Diff under
         review" line that `content/references/skeptic-protocol.md` Section
         4.5 mandates in EVERY Skeptic spawn prompt (the `## Global-context
         inputs` block, item 6) - the one field that identifies the actual
         artifact under review and stays stable across re-review rounds of
         the SAME unit, even though the rest of the prompt (the pasted
         Worker output) changes every round. See `_extract_unit_identity()`.
         DS-180 added a conductor-supplied stable-key fast path within that same line (`<key> | <diff detail>`, see `_extract_stable_unit_key()` and the DS-180 paragraph below) - the diff-identity normalization described in the rest of this docstring is now the fallback path, exercised only when no such key is present.
         When that line cannot be found, the hook fails open (allows, writes
         no state) rather than falling back to a weaker key that could
         collide across unrelated units - see Failure modes below.

         **Two follow-up fixes to that same "Diff under review" line,
         found when this hook failed to fire on its own verification
         round:**
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
         (b) The extracted line's raw text was used as the identity
         verbatim, which is stable for the common branch-relative form
         (`git diff origin/main...<branch>`) but NOT for a literal
         `<base-sha>..<head-sha>` range - every rework round mints a new
         head SHA, so every round produced its own key and the cap never
         engaged (measured: 4 sequential rounds on one unit, 4 separate
         state files, ALLOW every time). `_normalize_diff_identity()` now
         extracts a stable token from the range (the branch/PR-like ref
         when one is present, else the base SHA) instead of hashing the
         full raw text - see that function's docstring for the exact
         precedence and the one documented residual collision case (also
         restated at the end of this paragraph group).

         **Three further fixes, found by re-measuring rather than
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
         (d) `_DIFF_RANGE_RE` is `^`-anchored and its ref charclass
         excludes backticks, so a realistic backtick-wrapped diff-range
         value (a spawn brief rendering the command as inline code, e.g.
         "`git diff 1232779c..b7a596d9`") fell through to "return raw
         text unchanged," leaving the SHA-range instability fix (b)
         unfixed on this common form (measured: 4 rounds with a changing
         head SHA inside backticks produced 4 separate state files and
         ALLOWed round 4). `_normalize_diff_identity()` now strips
         surrounding backticks before matching.
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

         **DS-180 fix: explicit stable per-unit key, closing the two failure
         shapes the heuristics above cannot cover.** `_normalize_diff_identity()`
         stabilizes a `base..head` range only when one ref is a non-SHA
         branch/PR token, or, in its documented residual case, by falling back to
         the base SHA. Neither covers a ROLLING range, where round N's base
         equals round N-1's head - the literal shape a sequential rework loop
         produces - because the "base" itself changes every round. Nor does
         either heuristic apply at all once free-form prose sits in front of the
         range (`_DIFF_RANGE_RE` is anchored at the start of the value), which
         falls through to "return raw text unchanged" and makes the conductor's
         own round-numbering text part of the "stable" key. Measured on PR #760:
         seven sequential rework rounds on one unit, each citing
         `<prior-round-head>..<new-head>` with a `"DS-177 rework N - "` prefix,
         produced seven distinct state files and the cap never engaged - recorded
         as KNW-20260814-022. Per `content/references/skeptic-protocol.md`
         Section 4.5 "Stable unit key contract," field 6 now MAY lead with an
         explicit `<key> | <diff detail>` form; `_extract_stable_unit_key()`
         below reads `key` directly when present, bypassing the range heuristics
         entirely. A first version of that function partitioned on the first `|`
         unconditionally and reintroduced the same instability on a plausible
         input (a diff command piped through `head`) - `_STABLE_KEY_SHAPE_RE`
         closes that regression; see the function's own docstring. Absent from
         the value (no `|`), extraction falls through to the pre-existing
         `_normalize_diff_identity()` path unchanged.

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
           - next_round <= 3: ALLOW. Persist round_count = next_round and
             clear any stale `decision` (a new round supersedes a prior
             ship/escalate record - each cap hit needs its own decision).
           - next_round >= 4 (cap reached):
               - decision == "escalate": ALLOW (human explicitly authorized
                 another round). Consumed on use - persist round_count =
                 next_round, decision reset to null, so a later cap hit
                 needs a fresh escalate record.
               - decision == "ship" AND NOT unresolved_critical: ALLOW,
                 and CONSUMED on use exactly like escalate - persist
                 round_count = next_round, decision reset to null. A stale
                 `ship` decision must never be a permanent global bypass:
                 before this fix, `ship` left round_count and decision
                 unchanged, so every subsequent spawn for that unit (or,
                 combined with the branch-keying bug above, every
                 subsequent spawn for ANY unit) was allowed forever with no
                 further check.
               - decision == "ship" AND unresolved_critical: DENY. This is
                 the literal enforcement of "an unresolved Critical always
                 blocks - the cap never ships a Critical" - a recorded ship
                 decision is invalid while a Critical is still open,
                 regardless of round count. NOT consumed (state unchanged) -
                 the conductor must still resolve the Critical or record
                 escalate.
               - decision is null/absent: DENY, naming the round count and
                 the exact two permitted actions (never a paraphrase the
                 conductor could satisfy by rewording).
         `unresolved_critical` and `decision` are written to the state file
         by the conductor directly (a plain Edit under `.agentic/`, which is
         exempt from `enforce-shippable-edit.py`'s shippable-file gate) -
         this hook only reads and advances `round_count`. Consequently
         `unresolved_critical` is conductor-attested, not independently
         derived from any actual Skeptic finding: the hook enforces that a
         recorded `ship` decision cannot silently bypass a Critical the
         conductor has already flagged, not that no Critical exists. Do not
         cite this hook as proof no Critical was missed - only that a
         flagged one cannot be shipped past.

         Scope: fires ONLY on `subagent_type == "skeptic"` Task/Agent spawns.
         Never denies conductor Read/Grep/Glob (those tools are never
         Task/Agent, so they never reach this hook's logic at all) and never
         gates on inferred session capability - flat prohibitions in
         hooks/AGENTS.md §No gating on inferred session capability.

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
               cwd. No external deps, no subprocess (the fix that dropped
               `_current_branch()`'s `git rev-parse` call also dropped the
               only subprocess dependency this hook had).

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
    - A field-6 value in the `<key> | <diff detail>` form (DS-180) whose
      `key` portion is empty, whitespace-only, contains `..`, fails the
      key-shape check (`_STABLE_KEY_SHAPE_RE`), or looks like a file path
      (`_LOOKS_LIKE_FILE_PATH_RE`, DS-180 round-2 rework): treated as if
      no `|` were supplied at all - falls through to
      `_normalize_diff_identity()` on the value's full raw text, not a
      distinct fail-open case.
    - A key-shaped left side that is actually a diff command containing
      an incidental pipe (e.g. `git diff <sha>..<sha> | head -200`): the
      shape gate rejects it (whitespace, and a literal `..`, both fail)
      and it normalizes via the pre-existing SHA-range heuristic exactly
      as it did before this fix - not a stable key, and not a new
      fail-open case.
    - A key-shaped left side that is actually the first of two or more
      pipe-separated file paths (a plausible misreading of the
      pre-implementation-review field-6 contract, `$UNIT_KEY | <paths>`,
      when `$UNIT_KEY` is omitted): `_LOOKS_LIKE_FILE_PATH_RE` rejects it
      (file-extension-shaped suffix) and it falls through to
      `_normalize_diff_identity()` on the full raw text, which keys off
      the whole (differing) string rather than the shared first path - not
      a stable key, and not a new collision. See
      `_extract_stable_unit_key()`'s docstring for the measured collision
      this closes.
    - Known residual, not a fail-open case: `_LOOKS_LIKE_FILE_PATH_RE`
      only rejects an extension-shaped suffix (`\\.[A-Za-z0-9]{1,5}$`), so a
      first path with no such suffix - a bare filename, a dotfile, or a
      directory path (e.g. `LICENSE | a.py`, `.gitignore | a.sh`,
      `content/references/ | a.py`) - still passes the shape gate and
      becomes a wrong-but-stable key shared with any other unit whose
      first path is identical. This IS a new collision relative to
      pre-DS-180 behaviour, not a degradation to it - `LICENSE | a.py`
      and `LICENSE | b.md` share this key while the pre-DS-180 fallback
      keys off the whole (differing) string and would not collide them.
      It is judged acceptable for the same reason as the SHA-range
      residual above.
    - Known residual, not a fail-open case: two DIFFERENT units both
      expressed as `git diff <same-base-sha>..<hex-head-sha>` - a bare
      SHA range with no branch or PR token anywhere in the value - key
      off the SAME base-SHA token (fix (b) above) and therefore share one
      round counter. This is a real, accepted collision, not a
      hypothetical - see `_normalize_diff_identity()`'s docstring
      strategy 3 for why the base is chosen over refusing to key at all.
    - State file present but unparsable JSON: treated as absent (round 0,
      no decision, no unresolved_critical) - a corrupt state file must
      never turn into a permanent block.
    - State file write failure (permissions, disk full): the ALLOW/DENY
      decision for THIS call still fires correctly; only the persisted
      round_count advance may be lost, so a retried call may see a stale
      (lower) round_count and be permitted again - fail-open, not fail-shut.
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
      SEPARATE tuid-index file below, which DOES now have a best-effort
      lock (M4, round-2 fix) around its own read-merge-write.
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
      own read-merge-write is now guarded by a short, best-effort `flock`
      (M4, round-2 fix - see `_tuid_index_lock()`): bounded at
      `_TUID_INDEX_LOCK_TIMEOUT_S` (0.2s), degrading to an UNLOCKED
      read-merge-write (not a skipped write) on timeout or when `fcntl` is
      unavailable (non-POSIX platforms). This closes the common case
      (measured pre-fix: 6 parallel writers produced 4 entries, losing 2)
      but is not a hard guarantee against a genuinely simultaneous race
      landing inside the same lock-wait window on two different processes
      that both time out - a residual, not claimed to be fully closed.

Performance: < 5 ms per call (no subprocess; one small JSON read/write
             under `.agentic/`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

_ROUND_CAP = 3
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
# Matches a git diff-range expression ANCHORED at the start of the
# (already stripped) "Diff under review" value - e.g.
# "git diff origin/main...feature/foo" or a bare "abc1234..def5678" - used
# by `_normalize_diff_identity()` below (MAJOR 2). Anchoring at `^`
# prevents false positives on ordinary prose containing an ellipsis
# ("...") that happens to sit between two word-like tokens.
#
# Deliberately DOES NOT include `~` or `^` (round-6 fix, reverting a
# round-5 change). `hooks/subagent-stop-spawn-emit.js`'s
# `_DIFF_RANGE_JS_RE` (round-4 Minor fix) widened its OWN charclass to
# admit ordinary git revision-suffix syntax like `<sha>~1..<sha>` so that
# regex could resolve a `diff_lines` measurement. Round-5 M3 widened this
# regex to match on the strength of a comment claiming the two "mirror"
# each other - they do not, and never should: that regex feeds
# `resolveDiffLines()`, a pure line-count measurement with no round-cap
# consequence, while THIS regex feeds `_normalize_diff_identity()`, which
# derives the round-cap UNIT KEY. Widening this charclass makes
# `<x>~n..HEAD` and `<x>^..HEAD` values normalize to the literal token
# `HEAD` (strategy 1 below: `ref2` is "HEAD", which is not SHA-like, so it
# is returned verbatim) for ANY `<x>`, collapsing every unit whose
# "Diff under review" value happens to use `~`/`^`-suffixed HEAD-relative
# syntax onto ONE shared counter - reproduced (round-6 review): two
# distinct units both citing `<base>~N..HEAD` collided onto
# `skeptic-round-HEAD-7138a51661.json`, and unit B's very FIRST spawn was
# denied because unit A had already spent the shared budget. This is
# exactly the collision class DS-180's stable-unit-key contract exists to
# eliminate (see `_extract_stable_unit_key()` above), reintroduced by a
# regex-vs-regex "mirrors" comparison that never checked decision-level
# behavior. If a future change needs this regex to admit `~`/`^`, it must
# be justified with decision-level evidence (two distinct units, several
# rounds each, proving no collision) - not a claim that another regex
# with a different consumer was widened for a different reason.
#
# `_SHA_LIKE_RE` residual (round-6 Minor): the round-5 widening also
# desynchronized this regex from `_SHA_LIKE_RE` (unchanged at
# `^[0-9a-fA-F]{7,40}$`), because a `~`/`^`-suffixed SHA (e.g.
# "1232779c~1") matched the widened ref charclass but was never
# recognized by `_SHA_LIKE_RE` as SHA-like - strategy 1's stated
# rationale ("ref2 is NOT a bare hex SHA, i.e. it looks like a branch
# name") was then FALSE for that value, and the wrong side of the range
# could be selected. Reverting the charclass resolves this too, and
# resolves it completely, not partially: `_DIFF_RANGE_RE` is `^`-anchored
# and requires `\.{2,3}` immediately after `ref1` with no `~`/`^`
# permitted inside either ref group, so a `~`/`^`-suffixed range now
# fails to match `_DIFF_RANGE_RE` AT ALL (no partial match on a bare-SHA
# prefix) and falls straight through to strategy 4 ("return raw text
# unchanged") - it never reaches the `ref1_sha`/`ref2_sha` classification
# in the first place, so `_SHA_LIKE_RE` is never consulted on a
# `~`/`^`-suffixed value and the desync cannot recur. No residual
# misclassification remains; the only remaining cost is the pre-existing
# one strategy 4 already accepted (see its docstring below): a
# `~`/`^`-suffixed range gets no round-stability benefit at all (a
# changing head SHA each round mints a fresh key each round), which is
# unchanged from this hook's behavior before the round-4 JS-side fix ever
# motivated the (mistaken) round-5 attempt to mirror it here.
_DIFF_RANGE_RE = re.compile(
    r"(?i)^(?:git diff[ \t]+)?([A-Za-z0-9._/-]+)[ \t]*\.{2,3}[ \t]*([A-Za-z0-9._/-]+)"
)
_SHA_LIKE_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


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


def _normalize_diff_identity(raw: str) -> str:
    """Reduce a "Diff under review" value to a token that stays stable
    across rework rounds of the SAME unit (MAJOR 2).

    The literal diff-command text is NOT a stable identity by
    construction: every rework round produces a new head commit, so a
    "Diff under review: git diff <base-sha>..<head-sha>" value mints a
    brand-new key on every single round (measured: 4 sequential rounds on
    one unit produced 4 separate state files and ALLOWed round 4). Only
    the branch-relative form (`git diff origin/main...<branch>`) happened
    to be round-stable by accident, and that is the only form the
    original tests exercised - which is why they passed.

    Strategy, in order:
      1. If the value is a `<ref1>..<ref2>` / `<ref1>...<ref2>` range
         (with an optional leading "git diff "), and `ref2` is NOT a
         bare hex SHA (i.e. it looks like a branch name, e.g.
         "feature/foo", or a ref like "origin/main"), use `ref2` - the
         common case per `skeptic-protocol.md` Section 4.5, and the one
         part of the range that actually names the unit rather than a
         shared merge-base.
      2. Else if `ref1` is not SHA-like (unusual, e.g. a bare "origin/
         main..<sha>" form with no branch name at all), use `ref1`.
      3. Else (both refs are bare hex SHAs - a "base-sha..head-sha" range
         with no branch or PR name anywhere in the value): use `ref1`
         (the base). The base is the one anchor that stays constant
         across rework rounds of the same unit (the head SHA changes on
         every fix commit) - this is the literal case measured in the
         round-stability regression. Known residual risk, deliberately
         accepted rather than fixing by never keying at all: two SIBLING
         units that both branch from the identical origin/main commit and
         are reviewed via a bare SHA-range (no branch/PR name) would
         coalesce onto one counter. Branch-name and PR-number forms -
         the common case - never reach this branch.
      4. If the value is not a recognizable diff-range at all (free text,
         file paths, a PR reference), return it unchanged - already
         stable across rounds as long as the conductor writes the same
         value each round, matching the pre-existing (working) behavior
         for those forms.
    """
    text = raw.strip()
    # Strip surrounding backticks (a realistic spawn-brief line renders the
    # command as inline code, e.g. "`git diff 1232779c..b7a596d9`") before
    # anchoring `_DIFF_RANGE_RE` - the regex is `^`-anchored and its ref
    # charclass excludes backticks, so a backticked value fell through to
    # "return raw text unchanged" (strategy 4) and the SHA-range
    # instability this function exists to fix was unfixed on this common
    # form. Measured: 4 rounds with a changing head SHA inside backticks
    # produced 4 separate state files and ALLOWed round 4.
    text = text.strip("`").strip()
    match = _DIFF_RANGE_RE.match(text)
    if not match:
        return text
    ref1, ref2 = match.group(1), match.group(2)
    ref1_sha = bool(_SHA_LIKE_RE.match(ref1))
    ref2_sha = bool(_SHA_LIKE_RE.match(ref2))
    if not ref2_sha:
        return ref2
    if not ref1_sha:
        return ref1
    return ref1


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
# path does, by construction. Known residual: a key literal like "v1.2"
# would false-positive here (documented, not a case any current field-6
# template produces).
_LOOKS_LIKE_FILE_PATH_RE = re.compile(r"\.[A-Za-z0-9]{1,5}$")


def _extract_stable_unit_key(raw: str) -> str | None:
    """Extract the operator-supplied stable unit key from a "Diff under
    review" value in the `<key> | <diff detail>` form mandated by
    skeptic-protocol.md Section 4.5 "Stable unit key contract" (DS-180).

    Root cause this closes: `_normalize_diff_identity()` above stabilizes
    a `base..head` range only when one ref is a non-SHA branch/PR token,
    or, in its documented residual case, by falling back to the base SHA.
    Neither covers a ROLLING range, where round N's base equals round
    N-1's head - the literal shape a sequential rework loop produces -
    because the "base" itself changes every round. Nor does either
    heuristic apply once free-form prose sits in front of the range
    (`_DIFF_RANGE_RE` is anchored at the start of the value), which falls
    through to "return raw text unchanged" and makes the conductor's own
    round-numbering text part of the "stable" key. Measured on PR #760:
    seven sequential rework rounds on one unit, each citing
    `<prior-round-head>..<new-head>` with a narrative prefix, produced
    seven distinct state files and the cap never engaged (KNW-20260814-022).

    A first version of this function partitioned on the first "|" and
    returned the left side unconditionally - this REINTRODUCED the exact
    defect it was meant to close on a plausible input: a conductor
    pasting `git diff <sha>..<sha> | head -200` (a realistic value if
    output is piped through a line limiter) returned the whole
    `git diff <sha>..<sha>` span as the "key", which changes every round
    exactly like the un-fixed case. `_STABLE_KEY_SHAPE_RE` below closes
    this: a left side containing whitespace, a `..`/`...` range, or any
    character outside the key charclass is rejected and falls through to
    `_normalize_diff_identity()` on the FULL raw text - unchanged from
    today's behavior for that value (the anchored `_DIFF_RANGE_RE` inside
    `_normalize_diff_identity()` still matches only the leading ref
    pattern and ignores trailing pipe garbage, so `git diff <sha>..<sha>
    | head -200` still normalizes to the base SHA exactly as before this
    function existed).

    Leading/trailing backticks are stripped before the pipe check (a
    conductor may render the WHOLE `<key> | <diff>` value as inline code)
    - this mirrors the backtick tolerance `_normalize_diff_identity()`
    already has.

    A second regression (DS-180 round-2 rework, this docstring paragraph):
    on a pre-implementation review, field 6's contract is `$UNIT_KEY | `
    followed by the FILE PATHS the plan proposes to modify - if the
    conductor forgets `$UNIT_KEY` and instead pipe-separates two or more
    file paths (a plausible misreading of "leads with the key, then the
    paths"), the FIRST path passes every check above (non-empty, no `..`,
    matches the key charclass - a path like `hooks/foo.py` is valid under
    all of them) and is silently accepted as the key. Two different units
    each listing a shared first file with a different second file then
    collide onto the same counter - measured: `"hooks/enforce-skeptic-
    round-cap.py | bin/tests/test_enforce_skeptic_round_cap.py"` and
    `"hooks/enforce-skeptic-round-cap.py | content/references/skeptic-
    protocol.md"` both normalized to key `hooks-enforce-skeptic-round-
    cap.py` under the pre-fix logic, while the pre-DS-180 fallback path
    (`_normalize_diff_identity()` on the full raw text) does NOT collide,
    because the two full strings differ. `_LOOKS_LIKE_FILE_PATH_RE` closes
    this: a left side ending in a file-extension-shaped suffix (`.py`,
    `.md`, `.ts`, ...) is rejected and falls through to
    `_normalize_diff_identity()` on the full raw value - unchanged
    pre-DS-180 behavior, and NOT a new collision, since the fallback keys
    off the whole (differing) string rather than a shared prefix. A real
    stable key (a ticket id, a branch name, `$UNIT_KEY`) is never
    file-extension-shaped by construction; see the regex's own comment for
    the one documented residual false-positive.

    Returns None (never a collidable placeholder) when: no `|` is
    present; the text before it is empty/whitespace-only; it contains
    `..`; it fails the shape check; or it looks like a file path (ends in
    a file-extension-shaped suffix). In every case the caller falls back
    to `_normalize_diff_identity()` on the whole value - the unchanged
    pre-DS-180 behavior.
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


def _extract_unit_identity(tinput: dict) -> str | None:
    """Extract a stable per-unit identity string from the Skeptic spawn's
    prompt text.

    Uses the "Diff under review:" line that `content/references/
    skeptic-protocol.md` Section 4.5 mandates in every Skeptic spawn's
    `## Global-context inputs` block (item 6) - the field that identifies
    the actual reviewed artifact (a branch, a PR, a SHA range, file
    paths, or, per DS-180, an explicit `<key> | <detail>` pair). DS-180
    precedence: `_extract_stable_unit_key()` is tried FIRST - a
    conductor-supplied key is authoritative and never needs range
    heuristics. Only when it returns None (no `|`, or a left side that
    fails the shape gate) does extraction fall through to
    `_normalize_diff_identity()` (MAJOR 2, pre-DS-180): the raw line text
    is NOT itself stable across re-review rounds of the SAME unit when it
    is a literal SHA range (a new head SHA every round mints a new raw
    string), so identity is derived from a stable token WITHIN the value
    rather than the value's full text. Falls back to `description` (also
    often unit-scoped) only when no such line exists in `prompt`. Returns
    None when neither yields anything, OR when a single field carries two
    or more "Diff under review" lines with DIFFERING values - an
    ambiguous prompt is never guessed at by picking the first match; the
    caller must fail open, never falling back to a weaker key such as the
    conductor's own branch.
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
        value = raw_values[0]
        stable_key = _extract_stable_unit_key(value)
        if stable_key:
            return stable_key
        return _normalize_diff_identity(value)
    return None


def _unit_key(tinput: dict) -> str | None:
    """Return a safe, bounded, collision-resistant .agentic/ key for the
    unit under review, or None when it cannot be determined."""
    identity = _extract_unit_identity(tinput)
    if not identity:
        return None
    sanitized = _sanitize_key(identity)[:_MAX_KEY_LEN]
    digest = hashlib.sha1(identity.encode("utf-8", "replace")).hexdigest()[:10]
    return f"{sanitized}-{digest}"


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
    "round_count", "decision", "unresolved_critical", "last_round_fingerprint",
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
        "decision": None,
        "unresolved_critical": False,
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
            "decision": raw.get("decision") if raw.get("decision") in ("ship", "escalate") else None,
            "unresolved_critical": bool(raw.get("unresolved_critical", False)),
            "last_round_fingerprint": fingerprint if isinstance(fingerprint, str) else None,
            "last_decision_allow": raw.get("last_decision_allow") if isinstance(raw.get("last_decision_allow"), bool) else None,
            "last_decision_reason": raw.get("last_decision_reason") if isinstance(raw.get("last_decision_reason"), str) else "",
            "tool_use_ids": tool_use_ids,
            "_extra": extra,
        }
    except Exception:
        return default


def _write_state(path: Path, unit_key: str, state: dict) -> None:
    """Best-effort atomic write - tmp file + os.replace, pid-suffixed.

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
    except Exception:
        # Fail-open: a lost persist means a retried call may see a stale
        # (lower) round_count and be permitted again - never a false deny.
        pass


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
# Bounds the best-effort lock wait below (M4) - a short, bounded budget, not
# a real blocking lock: this hook must never meaningfully delay a Skeptic
# spawn over index-maintenance contention, which is why the total wait is
# capped well under this hook's own <5ms performance target's neighborhood
# (10ms retry interval, up to 20 attempts).
_TUID_INDEX_LOCK_TIMEOUT_S = 0.2
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
      - M4: the read-merge-write sequence below is now guarded by a
        short, best-effort `flock` (POSIX only - see
        `_tuid_index_lock()`), closing the concurrent-write data loss a
        parallel multi-dimensional fan-out (several Skeptic-family spawns
        reviewing the same unit, each with its own SubagentStop) could
        previously produce: two processes could both read the
        pre-update index, each add their own entry, and whichever wrote
        LAST would silently clobber the other's entry entirely (measured:
        6 parallel writers produced 4 entries and lost 2). The lock is
        best-effort and bounded (`_TUID_INDEX_LOCK_TIMEOUT_S`) - on lock
        acquisition failure (timeout, or no `fcntl` on this platform),
        the read-merge-write still runs UNLOCKED rather than skipping the
        write outright, which is strictly no worse than the pre-fix
        behavior and still closes the common case where writers do not
        arrive in the exact same instant."""
    if not isinstance(tool_use_id, str) or not tool_use_id.strip():
        return
    tid = tool_use_id.strip()
    index_path = agentic_dir / _TUID_INDEX_NAME
    try:
        agentic_dir.mkdir(parents=True, exist_ok=True)
        with _tuid_index_lock(agentic_dir):
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
    """No-op context manager - used when a real lock cannot be acquired
    (timeout, or `fcntl` unavailable on this platform). The caller's
    read-merge-write still runs, unlocked, rather than being skipped."""

    def __enter__(self) -> "_NullLock":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _tuid_index_lock(agentic_dir: Path):
    """Best-effort `flock`-based mutual exclusion (M4) around the tuid
    index's read-merge-write sequence, bounded by
    `_TUID_INDEX_LOCK_TIMEOUT_S`. Returns a real lock context manager on
    success, or `_NullLock()` when `fcntl` is unavailable (non-POSIX) or
    the lock could not be acquired within the timeout - in both cases the
    caller proceeds unlocked rather than skipping the write. This is
    intentionally NOT a hard guarantee: see `_update_tuid_index`'s
    docstring for why a bounded best-effort lock is judged sufficient
    here (closes the common case; a genuinely simultaneous race is still
    possible and no worse than the pre-fix behavior)."""
    try:
        import fcntl as _fcntl
    except Exception:
        return _NullLock()

    lock_path = agentic_dir / (_TUID_INDEX_NAME + ".lock")
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    except Exception:
        return _NullLock()

    deadline = time.time() + _TUID_INDEX_LOCK_TIMEOUT_S
    locked = False
    while time.time() < deadline:
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
        return _NullLock()

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


_DENY_NO_DECISION_TEMPLATE = (
    "Skeptic round cap reached: {round_count} rounds already spent on "
    "this unit (max {cap}). Take exactly one of two actions "
    "before spawning another round: (a) record decision:\"ship\" in "
    "the .agentic/skeptic-round-*.json state file and ship, recording "
    "every unresolved non-Critical finding in the PR body as accepted "
    "debt (an unresolved Critical always blocks - never ship one), or "
    "(b) record decision:\"escalate\" stating cost-to-date and what "
    "the next round is expected to buy, then retry the spawn."
)

_DENY_SHIP_CRITICAL_TEMPLATE = (
    "Skeptic round cap: {round_count} rounds already spent on this "
    "unit (max {cap}), and a `ship` decision is recorded, "
    "but `unresolved_critical` is still true. An unresolved "
    "Critical always blocks - the cap never ships a Critical. "
    "Fix the Critical (set unresolved_critical:false once "
    "resolved) or record decision:\"escalate\" instead of "
    "\"ship\" in the .agentic/skeptic-round-*.json state file."
)


def _decide(state: dict, round_fingerprint: str | None) -> tuple[bool, dict, str]:
    """Return (allow, new_state, reason). reason is "" when allow is True
    and the round advanced normally (nothing informative to log)."""
    round_count = state["round_count"]
    decision = state["decision"]
    unresolved_critical = state["unresolved_critical"]

    # Fingerprint coalescing: a parallel multi-dimensional fan-out
    # (correctness-Skeptic + security-auditor + perf-analyst, all sharing
    # this unit's key because they all review the same diff AND the same
    # Worker output) must consume ONE round, not one per spawn. A call
    # whose "What to review" fingerprint matches the round this state
    # already recorded reuses that round's cached outcome verbatim instead
    # of re-deciding (and, on the allow-and-mutate paths, re-advancing
    # round_count or re-consuming a decision). `round_fingerprint is None`
    # (no "What to review:" section found) never coalesces - every such
    # call is treated as its own round.
    if (
        round_fingerprint is not None
        and state.get("last_round_fingerprint") == round_fingerprint
        and state.get("last_decision_allow") is not None
    ):
        return bool(state["last_decision_allow"]), state, state.get("last_decision_reason", "")

    next_round = round_count + 1

    if next_round <= _ROUND_CAP:
        new_state = dict(state)
        new_state["round_count"] = next_round
        new_state["decision"] = None
        new_state["last_round_fingerprint"] = round_fingerprint
        new_state["last_decision_allow"] = True
        new_state["last_decision_reason"] = ""
        return True, new_state, ""

    # Cap reached (next_round >= _ROUND_CAP + 1).
    if decision == "ship":
        if unresolved_critical:
            reason = _DENY_SHIP_CRITICAL_TEMPLATE.format(round_count=round_count, cap=_ROUND_CAP)
            # Not consumed: the conductor must still resolve the Critical
            # or record escalate before another spawn is possible.
            return False, state, reason
        # Ship, like escalate, is single-use: consume it so a *subsequent*
        # spawn for this unit does not fall through to an unconditional
        # bypass. Before this fix, `ship` left round_count/decision
        # unchanged, making every later spawn for this unit ALLOW forever
        # with no further check.
        new_state = dict(state)
        new_state["round_count"] = next_round
        new_state["decision"] = None
        new_state["last_round_fingerprint"] = round_fingerprint
        new_state["last_decision_allow"] = True
        new_state["last_decision_reason"] = ""
        return True, new_state, ""

    if decision == "escalate":
        new_state = dict(state)
        new_state["round_count"] = next_round
        new_state["decision"] = None
        new_state["last_round_fingerprint"] = round_fingerprint
        new_state["last_decision_allow"] = True
        new_state["last_decision_reason"] = ""
        return True, new_state, ""

    reason = _DENY_NO_DECISION_TEMPLATE.format(round_count=round_count, cap=_ROUND_CAP)
    return False, state, reason


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
            # Cannot determine which unit is under review - fail open.
            # Never fall back to a weaker key (e.g. the conductor's own
            # branch) that could collide across unrelated units.
            sys.exit(0)

        path = _state_path(cwd, unit_key)
        if path is None:
            # Repo root could not be resolved - skip the read/write entirely
            # rather than fall back to a raw (possibly drifted) cwd.
            sys.exit(0)
        state = _load_state(path)

        allow, new_state, reason = _decide(state, _round_fingerprint(tinput))

        if not allow:
            _deny(data, reason)
            return

        new_state = _append_tool_use_id(new_state, tool_use_id)
        _write_state(path, unit_key, new_state)
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
