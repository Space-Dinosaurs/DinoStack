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
               import). No external deps, no subprocess (the fix that
               dropped `_current_branch()`'s `git rev-parse` call also
               dropped the only subprocess dependency this hook had).

Downstream consumers: Claude Code hook runner (PreToolUse event for Task and
                      Agent tools, matching enforce-tier.py's dual-matcher
                      wiring). Wired via ~/.claude/settings.json by
                      .claude/install.sh using the GUARDED command form
                      (`test -f <path> && python3 <path> || exit 0`) - a
                      bare `python3 {path}` would exit 2 (BLOCKING on
                      PreToolUse) if this file were ever removed while the
                      registration survives, denying every guarded spawn.

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
      per-spawn dispatch latency) but this hook has no real file lock - a
      true simultaneous race can still double-charge a round. This is a
      known residual risk, not claimed to be closed; it fails toward
      over-counting (extra rounds charged), never toward under-counting a
      genuine cap violation, and never toward a deny on malfunction.
    - Best-effort dynamic import of `lib/enforcement_log.py` for
      `log_fire()`; any import error falls back to a no-op, matching every
      other enforce-*.py hook's fire-logging pattern.

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


def _extract_unit_identity(tinput: dict) -> str | None:
    """Extract a stable per-unit identity string from the Skeptic spawn's
    prompt text.

    Uses the "Diff under review:" line that `content/references/
    skeptic-protocol.md` Section 4.5 mandates in every Skeptic spawn's
    `## Global-context inputs` block (item 6) - the field that identifies
    the actual reviewed artifact (a branch, a PR, a SHA range, or file
    paths). The extracted value is then run through
    `_normalize_diff_identity()` (MAJOR 2) before being returned: the raw
    line text is NOT itself stable across re-review rounds of the SAME
    unit when it is a literal SHA range (a new head SHA every round mints
    a new raw string), so identity is derived from a stable token WITHIN
    the value rather than the value's full text. Falls back to
    `description` (also often unit-scoped) only when no such line exists
    in `prompt`. Returns None when neither yields anything, OR when a
    single field carries two or more "Diff under review" lines with
    DIFFERING values - an ambiguous prompt is never guessed at by picking
    the first match; the caller must fail open, never falling back to a
    weaker key such as the conductor's own branch.
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
        return _normalize_diff_identity(raw_values[0])
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


def _state_path(cwd: str, key: str) -> Path:
    return Path(cwd) / ".agentic" / f"skeptic-round-{key}.json"


def _load_state(path: Path) -> dict:
    default = {
        "round_count": 0,
        "decision": None,
        "unresolved_critical": False,
        "last_round_fingerprint": None,
        "last_decision_allow": None,
        "last_decision_reason": "",
    }
    try:
        if not path.is_file():
            return default
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default
        fingerprint = raw.get("last_round_fingerprint")
        return {
            "round_count": raw.get("round_count", 0) if isinstance(raw.get("round_count"), int) else 0,
            "decision": raw.get("decision") if raw.get("decision") in ("ship", "escalate") else None,
            "unresolved_critical": bool(raw.get("unresolved_critical", False)),
            "last_round_fingerprint": fingerprint if isinstance(fingerprint, str) else None,
            "last_decision_allow": raw.get("last_decision_allow") if isinstance(raw.get("last_decision_allow"), bool) else None,
            "last_decision_reason": raw.get("last_decision_reason") if isinstance(raw.get("last_decision_reason"), str) else "",
        }
    except Exception:
        return default


def _write_state(path: Path, unit_key: str, state: dict) -> None:
    """Best-effort atomic write - tmp file + os.replace, pid-suffixed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(state)
        payload["unit_key"] = unit_key
        payload["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tmp_path = path.with_suffix(f".tmp.{os.getpid()}")
        tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception:
        # Fail-open: a lost persist means a retried call may see a stale
        # (lower) round_count and be permitted again - never a false deny.
        pass


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

        unit_key = _unit_key(tinput)
        if unit_key is None:
            # Cannot determine which unit is under review - fail open.
            # Never fall back to a weaker key (e.g. the conductor's own
            # branch) that could collide across unrelated units.
            sys.exit(0)

        path = _state_path(cwd, unit_key)
        state = _load_state(path)

        allow, new_state, reason = _decide(state, _round_fingerprint(tinput))

        if not allow:
            _deny(data, reason)
            return

        _write_state(path, unit_key, new_state)
        sys.exit(0)
    except Exception:
        # Any unexpected error anywhere in the decision path fails open -
        # a hook bug must never block Skeptic spawns outright.
        sys.exit(0)


if __name__ == "__main__":
    main()
