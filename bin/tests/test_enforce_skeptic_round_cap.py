#!/usr/bin/env python3
"""
Regression tests for hooks/enforce-skeptic-round-cap.py.

Test groups:
  1. test_round_1_2_3_allowed                        - rounds 1-3 all ALLOW, round_count advances
                                                         (each round carries DIFFERENT "What to
                                                         review" content, matching the real
                                                         sequential-rounds shape - a fresh Worker
                                                         output every round).
  2. test_round_4_denied_no_decision                 - 4th round with no recorded decision -> DENY,
                                                         message names round count and both permitted actions.
  3. test_round_4_allowed_with_escalate_decision      - decision:"escalate" recorded -> ALLOW, consumed
                                                         (decision reset to null after use).
  4. test_round_4_allowed_with_ship_decision_no_critical - decision:"ship", unresolved_critical:false -> ALLOW.
  5. test_round_4_denied_ship_with_unresolved_critical   - decision:"ship" AND unresolved_critical:true
                                                         -> DENY always, regardless of round/decision.
  6. test_ship_decision_is_consumed_on_use            - MAJOR 1 regression: after a `ship` decision is
                                                         consumed by one spawn, the NEXT spawn (a genuinely
                                                         new round) is NOT unconditionally allowed - it must
                                                         deny absent a fresh decision. Before the fix, `ship`
                                                         left round_count/decision unchanged and every later
                                                         spawn was allowed forever.
  7. test_parallel_fanout_consumes_one_round          - MAJOR 3 regression: a 3-spawn
                                                         `skeptic_strategy: multi-dimensional` fan-out
                                                         (same diff, same Worker output, different
                                                         Adversarial brief) must consume exactly ONE round,
                                                         not three.
  8. test_sequential_rounds_are_not_coalesced         - fingerprint coalescing must never suppress a
                                                         GENUINE new round: three spawns sharing the same
                                                         unit but each carrying different Worker output
                                                         ("What to review") must each charge its own round.
  9. test_two_different_units_get_independent_round_budgets - CRITICAL regression: two different units
                                                         (different "Diff under review" identity) reviewed
                                                         from the SAME conductor cwd/branch never share a
                                                         counter - unit A exhausting its budget must not
                                                         affect unit B's first round.
 10. test_branch_of_cwd_does_not_affect_unit_key      - CRITICAL regression: switching the conductor's own
                                                         git branch (or using a cwd that is not a git repo
                                                         at all) never changes which unit-state file a given
                                                         "Diff under review" identity resolves to.
 11. test_non_skeptic_subagent_passthrough            - subagent_type == "engineer" -> allow, no state file written.
 12. test_non_agent_tool_passthrough                  - tool_name == "Read" -> allow, no crash.
 13. test_malformed_stdin_failopen                    - bad JSON on stdin -> exit 0, no deny.
 14. test_missing_cwd_failopen                        - payload with no cwd -> allow (cannot key rounds).
 15. test_unextractable_identity_failopen             - prompt has no "Diff under review:" line -> allow,
                                                         no state file written (the unit cannot be
                                                         determined - never falls back to a weaker key).
 16. test_state_resolution_fails_open_with_no_git_ancestor - the unit key (round-counter identity) comes
                                                         from the prompt, not `git rev-parse` - proven by
                                                         switching branches on a real (`.git`-anchored) repo
                                                         without disturbing round state (see item 10,
                                                         test_branch_of_cwd_does_not_affect_unit_key). A cwd
                                                         with NO `.git` ancestor at all is a genuinely
                                                         separate, distinct case - see
                                                         test_state_resolution_fails_open_with_no_git_ancestor
                                                         below (round-3 rework, Major 2: this file's own
                                                         docstring and hooks/lib/repo_root.py's Failure modes
                                                         section both already documented this hook as one of
                                                         only two callers in the repo implementing the strict
                                                         "skip rather than write at an unresolved cwd"
                                                         discipline; the code did not actually implement it
                                                         until this rework, and this test previously asserted
                                                         the opposite of the documented, now-fixed behavior).
 17. test_nonexistent_cwd_failopen_no_crash           - cwd path does not exist -> never crashes, never
                                                         denies (state directory creation is best-effort).
 18. test_main_session_and_subagent_payload_shapes    - hook behaves identically whether agent_id/agent_type
                                                         are present (measured subagent payload) or absent
                                                         (measured main-session payload) - it never reads those keys.
 19. test_corrupt_state_file_treated_as_round_zero    - unparsable JSON on disk -> round 0, not a permanent block.
 20. test_read_only_agentic_dir_failopen              - state write failure (read-only .agentic/) -> the
                                                         ALLOW/DENY decision for that call still fires
                                                         correctly, never a false deny.
 21. test_diff_under_review_format_matrix             - MAJOR 1 regression: numbered, hyphen-bullet,
                                                         asterisk-bullet, bold-with-bullet, and bold-no-bullet
                                                         "Diff under review" forms all produce state - not just
                                                         the numbered form the original tests happened to use.
 22. test_round_stability_across_sha_range_rounds     - MAJOR 2 regression, extended (round-4 FIX 5) to the
                                                         bold-no-bullet and backticked-bold-bullet forms: a
                                                         `git diff <base>..<head>` identity resolves to ONE key
                                                         across 4 sequential rework rounds (changing head SHA,
                                                         same base) and actually DENIES at round 4, in every
                                                         real spawn-line shape - not just the numbered non-bold
                                                         form the round-3 version covered.
 23. test_diff_under_review_edge_cases_failopen       - MAJOR 1 + MAJOR 3 combined: absent field, malformed
                                                         (missing colon), field present twice with differing
                                                         values, empty value + blank line + prose (the literal
                                                         MAJOR 3 defect), and a value reflowed onto the next
                                                         line all allow and write NO state.
 24. test_empty_bolded_diff_field_failopen            - round-4 FIX 3 regression: an empty bolded "Diff under
                                                         review" field (a real, literal, unfilled spawn-brief
                                                         line) fails open with no state written, instead of
                                                         capturing the leftover `*` as a collidable
                                                         one-character identity shared by every unit with the
                                                         same defect.
 25. test_realistic_worker_output_with_internal_bold_headers_not_coalesced -
                                                         round-4 FIX 1 regression: a realistic pasted Worker
                                                         output containing its own bold-labeled lines (e.g.
                                                         "**Summary:**"), using the literal `ds-skeptic.md`
                                                         template shape (Worker output followed by a fixed
                                                         "**Resolved issues preflight:**" section), produces a
                                                         DISTINCT fingerprint per round and round_count advances
                                                         normally - not the round-3 bounded regex's silent
                                                         coalescing of every round onto round 1's cached ALLOW.
 26. test_stable_key_survives_rolling_sha_ranges       - DS-180 regression: PR #760's exact failure shape -
                                                         each rework round's diff line cites a rolling
                                                         <prior-round-head>..<new-head> range with a narrative
                                                         prefix. With the conductor supplying the new
                                                         `<key> | <diff>` form, round count accumulates on ONE
                                                         counter and round 4 denies.
 27. test_stable_key_two_distinct_units_no_collision   - DS-180: two distinct units, even sharing an identical
                                                         rolling SHA range shape, get INDEPENDENT round budgets.
 28. test_stable_key_empty_before_pipe_falls_back      - DS-180: a `| <diff>` value with nothing before the
                                                         pipe is not a valid key - falls through to
                                                         `_normalize_diff_identity()` on the full raw value.
 29. test_diff_command_with_pipe_normalizes_to_legacy_base - Major 2 (round 3) regression: a value that looks
                                                         like it has a pipe-prefixed key but is actually a diff
                                                         command piped through `head` must be REJECTED by the
                                                         shape gate and normalize to the base SHA exactly as
                                                         before `_extract_stable_unit_key` existed.
 30. test_stable_key_two_units_of_one_ticket_get_independent_budgets - Major 3 (round 2): a multi-unit ticket
                                                         using per-unit keys (`<TICKET>-u<N>`, never a bare
                                                         ticket id) gives each unit its own independent round
                                                         budget.
 31. test_stable_key_backticked_whole_value_accepts    - Minor 4 (round 3) / Minor 2 (round 4) regression: a
                                                         whole-value-backticked field 6 carrying a VALID key,
                                                         with a ROLLING base..head SHA range that changes every
                                                         round, must accumulate on one counter and deny at
                                                         round 4; also asserts the state FILENAME directly.
 32. test_pipe_separated_file_paths_no_key_no_collision - Major 1 (round 2) regression: field 6's
                                                         pre-implementation-review shape (`$UNIT_KEY | <paths>`)
                                                         with `$UNIT_KEY` omitted and TWO pipe-separated file
                                                         paths supplied instead - a plausible misreading of the
                                                         contract - must NOT let the shared first path become a
                                                         collidable stable key for two otherwise-distinct units;
                                                         each falls back to its own (differing) legacy identity.
 33. test_pipe_no_range_caught_only_by_shape_gate       - Major 2 (round 2) regression: a piped diff command with
                                                         NO `..`/`...` range in the left side (so the `".." in
                                                         left` guard cannot catch it) is rejected solely by
                                                         `_STABLE_KEY_SHAPE_RE` (the whitespace in the piped
                                                         command) - confirms the shape gate is independently
                                                         load-bearing, not merely redundant with the `..` check.
 34. test_tool_use_ids_round_trip_through_load_state    - DS-178 unit A: a `tool_use_id` supplied on the
                                                         PreToolUse payload survives into the round-state
                                                         file's `tool_use_ids` list across two rounds (deduped,
                                                         order-preserving) - proves `_load_state`/`_write_state`
                                                         no longer silently drop a schema field outside the
                                                         original hardcoded 6 keys.
 35. test_tuid_index_round_trip                         - DS-178 unit A: `.agentic/skeptic-tuid-index.json` maps
                                                         each spawn's `tool_use_id` to the correct unit_key, is
                                                         updated (not merely appended) across rounds of the same
                                                         unit, and correctly separates two distinct units'
                                                         tool_use_ids in the same index file.

Run with: python3 -m pytest bin/tests/test_enforce_skeptic_round_cap.py -x
       or: python3 bin/tests/test_enforce_skeptic_round_cap.py
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

_HOOK_PATH = Path(__file__).parent.parent.parent / "hooks" / "enforce-skeptic-round-cap.py"
_KEY_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
_MAX_KEY_LEN = 80


def _init_repo(tmp_path: Path, branch: str = "main") -> str:
    """Create a throwaway git repo at tmp_path checked out on *branch*.

    Only used by tests that specifically want to prove branch-independence
    (the round-counter KEY comes from the prompt, not from `git
    rev-parse`). Most other tests rely on `_ensure_git_marker`'s cheaper
    `.git`-existence-only marker instead of a full git init - round-3
    rework: _state_path now genuinely requires a `.git` ancestor to
    resolve (fail-open discipline, Major 2), so unlike this file's
    pre-round-3 design, no test can leave cwd with neither a `.git`
    marker nor an `_init_repo` real repo and still expect the hook to
    enforce.
    """
    subprocess.run(["git", "init", "-q", "-b", branch, str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True
    )
    (tmp_path / "README.md").write_text("x\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True
    )
    return branch


def _diff_identity(unit: str) -> str:
    """The literal "Diff under review" value a conductor would write for
    *unit* (a branch name, PR reference, or SHA range)."""
    return f"git diff origin/main...{unit}"


def _prompt(unit: str, what_to_review: str | None = None) -> str:
    lines = [
        "## Global-context inputs",
        "1. Architect plan: n/a - Trivial",
        "6. Diff under review: " + _diff_identity(unit),
        "",
    ]
    if what_to_review is not None:
        lines.append(f"**What to review:** {what_to_review}")
    lines.append("Evaluate and return your findings using the sign-off format.")
    return "\n".join(lines)


def _ensure_git_marker(cwd: str) -> None:
    """Best-effort: create a `.git` EXISTENCE marker (file-or-dir, matching
    hooks/lib/repo_root.py's existence-only check - never os.path.isdir())
    at cwd so _state_path resolves via the `.git`-ancestor walk instead of
    fail-opening.

    Round-3 rework (Major 2): _state_path now genuinely implements the
    manifest-mandated strict SKIP-on-no-`.git`-ancestor discipline (it
    previously fell back to writing at the raw unresolved cwd, contrary
    to both this hook's own docstring and hooks/lib/repo_root.py's
    Failure modes section). Every test below that exercises real
    round-counting behavior needs SOME `.git` ancestor to resolve against
    now, or the hook fails open and none of the state-file assertions
    below it would ever fire - a full `_init_repo` git init is unneeded
    for tests that don't care about branch identity; existence of a
    `.git` path is the entire check. Silently no-ops (not a failure) when
    cwd does not exist or `.git` already exists (e.g. `_init_repo`'s real
    git repos) - `test_state_resolution_fails_open_with_no_git_ancestor` and
    `test_nonexistent_cwd_failopen_no_crash` build their payloads directly
    rather than through this helper precisely because they test the
    absence of a `.git` ancestor."""
    try:
        Path(cwd, ".git").mkdir(exist_ok=True)
    except OSError:
        pass


def _skeptic_payload(
    cwd: str,
    unit: str = "feature/round-cap-test",
    what_to_review: str | None = None,
    extra: dict | None = None,
) -> dict:
    _ensure_git_marker(cwd)
    payload = {
        "tool_name": "Agent",
        "cwd": cwd,
        "tool_input": {
            "subagent_type": "skeptic",
            "description": "review",
            "prompt": _prompt(unit, what_to_review),
        },
    }
    if extra:
        payload.update(extra)
    return payload


def _run_hook(payload: dict) -> tuple[int, dict | None]:
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    out = result.stdout.strip()
    parsed = json.loads(out) if out else None
    return result.returncode, parsed


def _is_denied(parsed: dict | None) -> bool:
    if not parsed:
        return False
    return parsed.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def _deny_reason(parsed: dict | None) -> str:
    if not parsed:
        return ""
    return parsed.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


def _unit_key(unit: str) -> str:
    """Mirrors `_unit_key()` in the hook, INCLUDING the MAJOR 2
    normalization step: for the branch-relative form used by
    `_diff_identity()` (`git diff origin/main...<unit>`), the hook's
    `_normalize_diff_identity()` extracts the branch token (`unit`
    itself) rather than hashing the full "git diff origin/main..." text -
    see `test_round_stability_across_sha_range_rounds` for the bare
    SHA-range form, which normalizes differently (to the base SHA)."""
    identity = unit
    sanitized = _KEY_SAFE_RE.sub("-", identity.strip())[:_MAX_KEY_LEN]
    digest = hashlib.sha1(identity.encode("utf-8", "replace")).hexdigest()[:10]
    return f"{sanitized}-{digest}"


def _unit_key_for_raw_identity(identity: str) -> str:
    """Same sanitize+digest as `_unit_key()`, but takes an ALREADY
    NORMALIZED identity string directly (used by tests that construct a
    "Diff under review" value the hook's normalizer reduces to something
    other than the plain unit/branch name, e.g. a bare SHA range)."""
    sanitized = _KEY_SAFE_RE.sub("-", identity.strip())[:_MAX_KEY_LEN]
    digest = hashlib.sha1(identity.encode("utf-8", "replace")).hexdigest()[:10]
    return f"{sanitized}-{digest}"


def _state_path(cwd: str, unit: str) -> Path:
    return Path(cwd) / ".agentic" / f"skeptic-round-{_unit_key(unit)}.json"


def _read_state(cwd: str, unit: str) -> dict:
    return json.loads(_state_path(cwd, unit).read_text())


# --------------------------------------------------------------------------- #
# 1. Rounds 1-3 permitted (each round has different Worker output, the real
#    sequential-rounds shape)
# --------------------------------------------------------------------------- #
def test_round_1_2_3_allowed():
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        for expected_round in (1, 2, 3):
            rc, parsed = _run_hook(
                _skeptic_payload(tmp, unit, what_to_review=f"worker output round {expected_round}")
            )
            assert rc == 0
            assert not _is_denied(parsed), f"round {expected_round} unexpectedly denied: {parsed}"
            state = _read_state(tmp, unit)
            assert state["round_count"] == expected_round


# --------------------------------------------------------------------------- #
# 2. 4th round denied with no decision recorded
# --------------------------------------------------------------------------- #
def test_round_4_denied_no_decision():
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        for i in range(3):
            rc, parsed = _run_hook(
                _skeptic_payload(tmp, unit, what_to_review=f"worker output round {i + 1}")
            )
            assert not _is_denied(parsed)

        rc, parsed = _run_hook(
            _skeptic_payload(tmp, unit, what_to_review="worker output round 4")
        )
        assert rc == 0
        assert _is_denied(parsed), "4th round with no decision must be denied"
        reason = _deny_reason(parsed)
        assert "3 rounds" in reason
        assert '"ship"' in reason
        assert '"escalate"' in reason
        # round_count on disk must NOT have advanced past the cap.
        state = _read_state(tmp, unit)
        assert state["round_count"] == 3


# --------------------------------------------------------------------------- #
# 3. escalate decision unblocks the 4th round, then is consumed
# --------------------------------------------------------------------------- #
def test_round_4_allowed_with_escalate_decision():
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        for i in range(3):
            _run_hook(_skeptic_payload(tmp, unit, what_to_review=f"worker output round {i + 1}"))

        path = _state_path(tmp, unit)
        state = json.loads(path.read_text())
        state["decision"] = "escalate"
        path.write_text(json.dumps(state))

        rc, parsed = _run_hook(
            _skeptic_payload(tmp, unit, what_to_review="worker output round 4")
        )
        assert rc == 0
        assert not _is_denied(parsed), f"escalate-authorized round 4 was denied: {parsed}"
        new_state = _read_state(tmp, unit)
        assert new_state["round_count"] == 4
        assert new_state["decision"] is None, "escalate must be consumed (single-use)"

        # A subsequent 5th-round attempt with no fresh escalate must deny again.
        rc, parsed = _run_hook(
            _skeptic_payload(tmp, unit, what_to_review="worker output round 5")
        )
        assert _is_denied(parsed), "round 5 without a fresh escalate must deny"


# --------------------------------------------------------------------------- #
# 4. ship decision (no unresolved critical) unblocks the 4th round
# --------------------------------------------------------------------------- #
def test_round_4_allowed_with_ship_decision_no_critical():
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        for i in range(3):
            _run_hook(_skeptic_payload(tmp, unit, what_to_review=f"worker output round {i + 1}"))

        path = _state_path(tmp, unit)
        state = json.loads(path.read_text())
        state["decision"] = "ship"
        state["unresolved_critical"] = False
        path.write_text(json.dumps(state))

        rc, parsed = _run_hook(
            _skeptic_payload(tmp, unit, what_to_review="worker output round 4")
        )
        assert rc == 0
        assert not _is_denied(parsed), f"ship decision with no Critical was denied: {parsed}"


# --------------------------------------------------------------------------- #
# 5. Critical always blocks - ship + unresolved_critical -> DENY regardless
# --------------------------------------------------------------------------- #
def test_round_4_denied_ship_with_unresolved_critical():
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        for i in range(3):
            _run_hook(_skeptic_payload(tmp, unit, what_to_review=f"worker output round {i + 1}"))

        path = _state_path(tmp, unit)
        state = json.loads(path.read_text())
        state["decision"] = "ship"
        state["unresolved_critical"] = True
        path.write_text(json.dumps(state))

        rc, parsed = _run_hook(
            _skeptic_payload(tmp, unit, what_to_review="worker output round 4")
        )
        assert rc == 0
        assert _is_denied(parsed), "ship must never bypass an unresolved Critical"
        reason = _deny_reason(parsed)
        assert "Critical" in reason
        # A denied ship-with-Critical must not be consumed either.
        state_after = _read_state(tmp, unit)
        assert state_after["decision"] == "ship"
        assert state_after["round_count"] == 3


# --------------------------------------------------------------------------- #
# 6. MAJOR 1 regression: `ship` is single-use, not a permanent bypass
# --------------------------------------------------------------------------- #
def test_ship_decision_is_consumed_on_use():
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        for i in range(3):
            _run_hook(_skeptic_payload(tmp, unit, what_to_review=f"worker output round {i + 1}"))

        path = _state_path(tmp, unit)
        state = json.loads(path.read_text())
        state["decision"] = "ship"
        state["unresolved_critical"] = False
        path.write_text(json.dumps(state))

        # 4th spawn: ship consumed, round_count advances to 4.
        rc, parsed = _run_hook(
            _skeptic_payload(tmp, unit, what_to_review="worker output round 4")
        )
        assert not _is_denied(parsed)
        state_after_ship = _read_state(tmp, unit)
        assert state_after_ship["round_count"] == 4
        assert state_after_ship["decision"] is None, "ship must be consumed (single-use), matching escalate"

        # 5th spawn: no fresh decision recorded - must NOT be unconditionally
        # allowed. Before the Major 1 fix, `ship` never advanced state, so
        # every later spawn kept re-reading decision:"ship" and allowed
        # forever.
        rc, parsed = _run_hook(
            _skeptic_payload(tmp, unit, what_to_review="worker output round 5")
        )
        assert _is_denied(parsed), "a spent ship decision must not unconditionally allow a later round"


# --------------------------------------------------------------------------- #
# 7. MAJOR 3 regression: parallel multi-dimensional fan-out consumes ONE
#    round, not one per spawn
# --------------------------------------------------------------------------- #
def test_parallel_fanout_consumes_one_round():
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        worker_output = "worker output round 1 (identical across the fan-out)"

        # Three companion spawns of ONE round: correctness-Skeptic,
        # security-auditor, perf-analyst - same diff, same Worker output,
        # different Adversarial brief/description (which the fingerprint
        # deliberately ignores - only "What to review" content matters).
        for description in ("correctness review", "security review", "perf review"):
            payload = _skeptic_payload(tmp, unit, what_to_review=worker_output)
            payload["tool_input"]["description"] = description
            rc, parsed = _run_hook(payload)
            assert rc == 0
            assert not _is_denied(parsed), f"{description} unexpectedly denied: {parsed}"

        state = _read_state(tmp, unit)
        assert state["round_count"] == 1, (
            f"3 fan-out spawns of ONE round must charge round_count == 1, got {state['round_count']}"
        )

        # A genuinely new round (different Worker output) still charges
        # normally afterward.
        rc, parsed = _run_hook(
            _skeptic_payload(tmp, unit, what_to_review="worker output round 2")
        )
        assert not _is_denied(parsed)
        state2 = _read_state(tmp, unit)
        assert state2["round_count"] == 2


# --------------------------------------------------------------------------- #
# 8. Fingerprint coalescing must never suppress a GENUINE new round
# --------------------------------------------------------------------------- #
def test_sequential_rounds_are_not_coalesced():
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        for expected_round, output in enumerate(
            ("first fix attempt", "second fix attempt", "third fix attempt"), start=1
        ):
            rc, parsed = _run_hook(_skeptic_payload(tmp, unit, what_to_review=output))
            assert not _is_denied(parsed)
            state = _read_state(tmp, unit)
            assert state["round_count"] == expected_round, (
                "each round carries different Worker output and must charge "
                "its own round, never coalesced with the prior one"
            )


# --------------------------------------------------------------------------- #
# 9. CRITICAL regression: two different units never share a round budget,
#    even from the identical conductor cwd/branch
# --------------------------------------------------------------------------- #
def test_two_different_units_get_independent_round_budgets():
    with tempfile.TemporaryDirectory() as tmp:
        unit_a = "feature/unit-a"
        unit_b = "feature/unit-b"

        # Unit A burns its whole budget from this cwd (which stays on
        # whatever branch the conductor happens to be on - no git repo
        # even exists at `tmp`).
        for i in range(3):
            _run_hook(_skeptic_payload(tmp, unit_a, what_to_review=f"unit-a fix {i + 1}"))
        rc, parsed = _run_hook(_skeptic_payload(tmp, unit_a, what_to_review="unit-a fix 4"))
        assert _is_denied(parsed), "unit A must be denied its 4th round"

        # Unit B's first spawn, from the SAME cwd, must still be allowed -
        # this is the exact bug: before the fix, both units shared one
        # `skeptic-round-<branch>.json` counter keyed off the conductor's
        # own branch, so unit A's exhaustion silently denied unit B too.
        rc, parsed = _run_hook(_skeptic_payload(tmp, unit_b, what_to_review="unit-b fix 1"))
        assert not _is_denied(parsed), "unit B's first round must not inherit unit A's exhausted budget"
        state_b = _read_state(tmp, unit_b)
        assert state_b["round_count"] == 1
        state_a = _read_state(tmp, unit_a)
        assert state_a["round_count"] == 3
        assert _state_path(tmp, unit_a) != _state_path(tmp, unit_b)


# --------------------------------------------------------------------------- #
# 10. CRITICAL regression: the conductor's own git branch never affects the
#     unit key
# --------------------------------------------------------------------------- #
def test_branch_of_cwd_does_not_affect_unit_key():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _init_repo(tmp_path, branch="main")
        unit = "feature/round-cap-test"

        rc, parsed = _run_hook(_skeptic_payload(tmp, unit, what_to_review="round 1"))
        assert not _is_denied(parsed)
        state_on_main = _read_state(tmp, unit)
        assert state_on_main["round_count"] == 1

        # Switch the CONDUCTOR's own checkout branch (as would happen if
        # the conductor moved between sessions) - the unit's round state
        # must be unaffected, because the key no longer derives from it.
        subprocess.run(
            ["git", "-C", tmp, "checkout", "-q", "-b", "some-other-branch"], check=True
        )
        rc, parsed = _run_hook(_skeptic_payload(tmp, unit, what_to_review="round 2"))
        assert not _is_denied(parsed)
        state_after_switch = _read_state(tmp, unit)
        assert state_after_switch["round_count"] == 2, (
            "round_count must continue advancing for the SAME unit regardless "
            "of which branch the conductor's own cwd happens to be on"
        )
        assert _state_path(tmp, unit) == _state_path(tmp, unit)


# --------------------------------------------------------------------------- #
# 11/12. Passthrough for non-skeptic / non-Task-Agent tool calls
# --------------------------------------------------------------------------- #
def test_non_skeptic_subagent_passthrough():
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        payload = _skeptic_payload(tmp, unit, what_to_review="x")
        payload["tool_input"]["subagent_type"] = "engineer"
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed)
        assert not _state_path(tmp, unit).exists()


def test_non_agent_tool_passthrough():
    with tempfile.TemporaryDirectory() as tmp:
        payload = {"tool_name": "Read", "cwd": tmp, "tool_input": {"file_path": "/x"}}
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed)


# --------------------------------------------------------------------------- #
# 13/14/15/16/17. Fail-open cases
# --------------------------------------------------------------------------- #
def test_malformed_stdin_failopen():
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input="not json{{{",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_missing_cwd_failopen():
    payload = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "skeptic", "prompt": _prompt("x")},
    }
    rc, parsed = _run_hook(payload)
    assert rc == 0
    assert not _is_denied(parsed)


def test_unextractable_identity_failopen():
    with tempfile.TemporaryDirectory() as tmp:
        payload = {
            "tool_name": "Agent",
            "cwd": tmp,
            "tool_input": {
                "subagent_type": "skeptic",
                "description": "review",
                "prompt": "review the diff, no structured fields here",
            },
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed)
        assert not (Path(tmp) / ".agentic").exists(), (
            "an unextractable unit identity must never fall back to a "
            "weaker key - no state file should be written at all"
        )


def test_state_resolution_fails_open_with_no_git_ancestor():
    """Round-3 rework regression (adversarial review Major 2): when cwd has
    NO `.git` ancestor anywhere up the tree, _state_path must resolve to
    None and the hook must fail open (never deny, never write a state
    file at the unresolved cwd) - matching both this hook's own docstring
    ("on load failure _state_path returns None and the caller skips the
    round-cap check entirely (fail-open) rather than falling back to a raw
    cwd") and hooks/lib/repo_root.py's Failure modes section, which names
    this hook as one of only two callers that genuinely implement the
    strict skip discipline because a write at the wrong location would
    actively corrupt cross-session state. Before the fix, _state_path
    called the plain resolve_agentic_cwd() and never consulted
    found_git_ancestor, so it silently wrote the round counter at the
    realpath'd raw cwd instead of skipping - confirmed failing pre-fix:
    running this test against the unfixed _state_path produced a written
    state file with round_count == 1 at tmp/.agentic/, not the required
    absence of any .agentic/ tree.

    Builds the payload directly (not via _skeptic_payload/
    _ensure_git_marker) so no `.git` marker is created - this is the one
    test in this suite that specifically needs cwd to have NO `.git`
    ancestor."""
    with tempfile.TemporaryDirectory() as tmp:
        # Deliberately NOT a git repo - no _ensure_git_marker call.
        unit = "feature/round-cap-test"
        payload = {
            "tool_name": "Agent",
            "cwd": tmp,
            "tool_input": {
                "subagent_type": "skeptic",
                "description": "review",
                "prompt": _prompt(unit, "round 1"),
            },
        }
        rc, parsed = _run_hook(payload)
        assert rc == 0
        assert not _is_denied(parsed)
        assert not (Path(tmp) / ".agentic").exists(), (
            "a cwd with no .git ancestor must never get a round-cap state "
            "file written at the unresolved cwd - the hook must skip "
            "(fail open) entirely"
        )


def test_nonexistent_cwd_failopen_no_crash():
    tmp = tempfile.mkdtemp()
    nonexistent = str(Path(tmp) / "does" / "not" / "exist")
    unit = "feature/round-cap-test"
    rc, parsed = _run_hook(_skeptic_payload(nonexistent, unit, what_to_review="round 1"))
    assert rc == 0
    assert not _is_denied(parsed)


# --------------------------------------------------------------------------- #
# 18. Payload key-shape independence (measured main-session vs subagent
#     payloads - hook must never assume either shape)
# --------------------------------------------------------------------------- #
def test_main_session_and_subagent_payload_shapes():
    with tempfile.TemporaryDirectory() as tmp:
        # Main-session shape: no agent_id/agent_type keys at all.
        main_payload = _skeptic_payload(tmp, "unit-main", what_to_review="x")
        rc1, parsed1 = _run_hook(main_payload)
        assert rc1 == 0
        assert not _is_denied(parsed1)

    with tempfile.TemporaryDirectory() as tmp2:
        # Subagent shape: agent_id/agent_type present (should behave the same -
        # the hook does not branch on their presence).
        sub_payload = _skeptic_payload(
            tmp2, "unit-sub", what_to_review="x", extra={"agent_id": "agent-abc123", "agent_type": "skeptic"}
        )
        rc2, parsed2 = _run_hook(sub_payload)
        assert rc2 == 0
        assert not _is_denied(parsed2)


# --------------------------------------------------------------------------- #
# 19. Corrupt state file is treated as round 0, not a permanent block
# --------------------------------------------------------------------------- #
def test_corrupt_state_file_treated_as_round_zero():
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        path = _state_path(tmp, unit)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json")

        rc, parsed = _run_hook(_skeptic_payload(tmp, unit, what_to_review="round 1"))
        assert rc == 0
        assert not _is_denied(parsed)
        state = _read_state(tmp, unit)
        assert state["round_count"] == 1


# --------------------------------------------------------------------------- #
# 20. State write failure (read-only .agentic/) still fails open
# --------------------------------------------------------------------------- #
def test_read_only_agentic_dir_failopen():
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        agentic_dir = Path(tmp) / ".agentic"
        agentic_dir.mkdir(parents=True, exist_ok=True)
        agentic_dir.chmod(stat.S_IREAD | stat.S_IEXEC)
        try:
            rc, parsed = _run_hook(_skeptic_payload(tmp, unit, what_to_review="round 1"))
            assert rc == 0
            assert not _is_denied(parsed), "a state-write failure must never turn into a deny"
        finally:
            agentic_dir.chmod(stat.S_IRWXU)


# --------------------------------------------------------------------------- #
# 21-23. Round-2 review fixes: real-shape "Diff under review" format matrix
# (MAJOR 1), SHA-range round stability (MAJOR 2), and the extended
# fail-open matrix (MAJOR 1 + MAJOR 3 combined).
# --------------------------------------------------------------------------- #
def _raw_prompt(diff_line: str, what_to_review: str | None = None) -> str:
    """Build a spawn prompt from a literal "Diff under review" line,
    mirroring the real `content/commands/ds-skeptic.md` template shape
    (`## Global-context inputs` block, item 6, followed by "What to
    review")."""
    lines = [
        "## Global-context inputs",
        "1. Architect plan: n/a - Trivial",
        diff_line,
        "",
    ]
    if what_to_review is not None:
        lines.append(f"**What to review:** {what_to_review}")
    lines.append("Evaluate and return your findings using the sign-off format.")
    return "\n".join(lines)


def _raw_payload(tmp: str, diff_line: str, what_to_review: str | None = None) -> dict:
    _ensure_git_marker(tmp)
    return {
        "tool_name": "Agent",
        "cwd": tmp,
        "tool_input": {
            "subagent_type": "skeptic",
            "description": "review",
            "prompt": _raw_prompt(diff_line, what_to_review),
        },
    }


# The exact hyphen-bullet form at content/references/skeptic-protocol.md:371
# ("- Diff under review: <STABLE-UNIT-KEY> | <as today>") and the bold-bullet form real spawn
# briefs use ("- **Diff under review:**") are both included below - the
# verification round's own prompt used the latter and the pre-fix hook
# never fired on it.
_DIFF_LINE_FORMS = {
    "numbered": "6. Diff under review: {value}",
    "hyphen_bullet": "- Diff under review: {value}",
    "asterisk_bullet": "* Diff under review: {value}",
    "bold_with_hyphen_bullet": "- **Diff under review:** {value}",
    "bold_no_bullet": "**Diff under review:** {value}",
}


def test_diff_under_review_format_matrix():
    """MAJOR 1 regression: every real spawn-prompt format for the "Diff
    under review" line must produce state, not just the numbered form the
    original tests happened to use."""
    unit = "feature/round-cap-test"
    for label, template in _DIFF_LINE_FORMS.items():
        with tempfile.TemporaryDirectory() as tmp:
            diff_line = template.format(value=_diff_identity(unit))
            rc, parsed = _run_hook(
                _raw_payload(tmp, diff_line, what_to_review="worker output round 1")
            )
            assert rc == 0
            assert not _is_denied(parsed), f"{label} form unexpectedly denied: {parsed}"
            state_path = _state_path(tmp, unit)
            assert state_path.exists(), (
                f"{label} form ({diff_line!r}) produced NO state file - the hook did "
                f"not extract an identity from this real spawn-prompt shape"
            )
            state = json.loads(state_path.read_text())
            assert state["round_count"] == 1, f"{label} form: unexpected state {state}"


# SHA-range "Diff under review" line templates the round-stability test
# below is parametrized over. `numbered` is the original (already-working)
# form; `bold_no_bullet` and `backticked_bold_bullet` are the forms
# introduced by the round-3 fix (FIX 2) - `backticked_bold_bullet` is
# copied verbatim from a realistic spawn-brief line (this ticket's own
# "## Base" section used the identical
# "- **Diff under review:** `git diff 1232779c..b7a596d9`" shape), the
# exact form that fell through `_DIFF_RANGE_RE`'s `^`-anchor before the
# backtick-strip fix because the ref charclass excludes backticks.
_SHA_RANGE_LINE_FORMS = {
    "numbered": "6. Diff under review: git diff {base}..{head}",
    "bold_no_bullet": "**Diff under review:** git diff {base}..{head}",
    "backticked_bold_bullet": "- **Diff under review:** `git diff {base}..{head}`",
}


def test_round_stability_across_sha_range_rounds():
    """MAJOR 2 regression, extended to the bold and backticked forms
    (FIX 5): a `git diff <base-sha>..<changing-head-sha>` identity (the
    form the Skeptic sign-off contract's own `Reviewed: <base-sha>..
    <head-sha>` shape mirrors) must resolve to ONE key across sequential
    rework rounds and actually DENY at round 4, in EVERY real spawn-line
    shape - not just the numbered non-bold form the round-3 regression
    test happened to cover, which never exercised the backticked form
    FIX 2 fixes."""
    for label, template in _SHA_RANGE_LINE_FORMS.items():
        with tempfile.TemporaryDirectory() as tmp:
            base_sha = "a" * 40
            heads = ["b" * 40, "c" * 40, "d" * 40, "e" * 40]
            expected_path = (
                Path(tmp)
                / ".agentic"
                / f"skeptic-round-{_unit_key_for_raw_identity(base_sha)}.json"
            )

            for i, head in enumerate(heads[:3], start=1):
                diff_line = template.format(base=base_sha, head=head)
                rc, parsed = _run_hook(
                    _raw_payload(tmp, diff_line, what_to_review=f"worker output round {i}")
                )
                assert not _is_denied(parsed), f"{label} round {i} unexpectedly denied: {parsed}"
                assert expected_path.exists(), (
                    f"{label}: all rounds of the SAME unit must resolve to the "
                    f"base-SHA-keyed state file"
                )
                state = json.loads(expected_path.read_text())
                assert state["round_count"] == i, (
                    f"{label}: base..head SHA range must resolve to ONE stable "
                    f"key across rounds - got round_count={state['round_count']} at round {i}"
                )

            # 4th round (yet another new head SHA) must DENY - proves the cap
            # actually engages instead of minting a fresh key every round.
            diff_line = template.format(base=base_sha, head=heads[3])
            rc, parsed = _run_hook(
                _raw_payload(tmp, diff_line, what_to_review="worker output round 4")
            )
            assert _is_denied(parsed), f"{label}: round 4 of a SHA-range-keyed unit must be denied at the cap"

            state_files = list((Path(tmp) / ".agentic").glob("skeptic-round-*.json"))
            assert len(state_files) == 1, (
                f"{label}: expected exactly ONE state file across all 4 rounds, "
                f"got {[p.name for p in state_files]}"
            )


def test_empty_bolded_diff_field_failopen():
    """FIX 3 regression: an empty bolded "Diff under review" field (a
    real, literal spawn-brief line - e.g. a conductor pastes the item-6
    template line from `content/commands/ds-skeptic.md` bolded but never
    fills it in) must fail open with NO state written, not capture the
    single leftover `*` character as a one-character identity. Pre-fix,
    `\\*{0,2}:\\*{0,2}` backtracked to consume only one of the two closing
    asterisks, and the bare `\\S` capture then matched the remaining `*`
    as a valid one-character identity - every unit with this defect
    collided onto the SAME shared `*`-keyed counter, so unrelated units'
    malformed spawns produced a false DENY on an unrelated unit's
    legitimate spawn."""
    empty_field_lines = [
        "- **Diff under review:**",
        "**Diff under review:**",
        "- **Diff under review:** ",
    ]
    for line in empty_field_lines:
        with tempfile.TemporaryDirectory() as tmp:
            rc, parsed = _run_hook(
                _raw_payload(tmp, line, what_to_review="worker output round 1")
            )
            assert rc == 0
            assert not _is_denied(parsed), f"{line!r} must allow: {parsed}"
            assert not (Path(tmp) / ".agentic").exists(), (
                f"{line!r} must fail open with NO state written, but a state "
                f"file (or `.agentic/`) was created - likely captured the "
                f"leftover '*' as a one-character identity"
            )


# Literal "What to review:" / "**Resolved issues preflight:**" section
# shape copied verbatim from `content/commands/ds-skeptic.md` Step 2's
# spawn-prompt template - the real ordering: pasted Worker output first,
# then a fixed "**Resolved issues preflight:**" section. A realistic
# Worker output routinely contains its OWN bold-labeled lines (e.g. a
# "**Summary:**" section), which is exactly what triggered the round-3
# bounded-regex bug (FIX 1): the bound's lookahead matched on the FIRST
# such internal bold line and truncated every round's captured body down
# to the same short prefix.
def _realistic_skeptic_prompt(diff_line: str, worker_output: str) -> str:
    lines = [
        "## Global-context inputs",
        "1. Architect plan: n/a - Trivial",
        diff_line,
        "",
        f"**What to review:** {worker_output}",
        "",
        "**Resolved issues preflight:**",
        "- Round 1: \"No prior rounds. This is round 1.\"",
    ]
    return "\n".join(lines)


def test_realistic_worker_output_with_internal_bold_headers_not_coalesced():
    """FIX 1 regression: a realistic pasted Worker output that itself
    contains bold-labeled lines (e.g. "**Summary:**") must NOT truncate
    the fingerprinted body down to a constant prefix across rounds. Using
    the real `ds-skeptic.md` template shape (Worker output immediately
    followed by a fixed "**Resolved issues preflight:**" section), rounds
    1-3 each carrying genuinely different Worker output must produce 3
    DISTINCT fingerprints and round_count must advance every round
    (1, 2, 3), and a 4th round with yet another distinct Worker output
    must DENY at the cap. Pre-fix (bounded `_WHAT_TO_REVIEW_RE`), the
    lookahead matched the first internal bold line and every round's
    captured body reduced to the same short prefix, coalescing every
    round onto round 1's cached ALLOW forever (measured: round_count
    frozen at 1 across 5 real sequential spawns, never denying)."""
    diff_line = "6. Diff under review: git diff origin/main...feature/round-cap-test"
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        for i in range(1, 4):
            # The constant intro line ("Worker output below.") before the
            # varying content is deliberate - it reproduces the exact
            # measured shape of the round-3 defect: a bounded regex
            # truncates the captured body at the FIRST internal bold
            # header, which sits right after this constant sentence in
            # every round, so only the (identical) intro text survives
            # into the fingerprint regardless of what actually changed.
            worker_output = (
                "Worker output below.\n"
                f"**Summary:** round {i} changed function foo_{i}() to handle "
                f"edge case {i}."
            )
            prompt = _realistic_skeptic_prompt(diff_line, worker_output)
            payload = {
                "tool_name": "Agent",
                "cwd": tmp,
                "tool_input": {
                    "subagent_type": "skeptic",
                    "description": "review",
                    "prompt": prompt,
                },
            }
            rc, parsed = _run_hook(payload)
            assert not _is_denied(parsed), f"round {i} unexpectedly denied: {parsed}"
            state = _read_state(tmp, "feature/round-cap-test")
            assert state["round_count"] == i, (
                f"FIX 1 regression: round {i}'s distinct Worker output must "
                f"advance round_count to {i} - got {state['round_count']} "
                f"(coalesced with a prior round's fingerprint)"
            )

        # Round 4's genuinely new Worker output must be denied at the cap -
        # proves round_count actually advanced past 3 rather than
        # coalescing forever on round 1's cached ALLOW.
        worker_output = "Worker output below.\n**Summary:** round 4 final cleanup."
        prompt = _realistic_skeptic_prompt(diff_line, worker_output)
        payload = {
            "tool_name": "Agent",
            "cwd": tmp,
            "tool_input": {
                "subagent_type": "skeptic",
                "description": "review",
                "prompt": prompt,
            },
        }
        rc, parsed = _run_hook(payload)
        assert _is_denied(parsed), "round 4 of a genuinely-advancing unit must be denied at the cap"


def test_diff_under_review_edge_cases_failopen():
    """MAJOR 1 + MAJOR 3 combined fail-open matrix: an absent field, a
    malformed field (missing colon), a field carrying two DIFFERING
    values, an empty value followed by a blank line then other prose (the
    literal MAJOR 3 defect - the old `\\s*` crossed the newline and
    captured the Worker output as the identity), and a value reflowed
    onto the next line must all allow and write NO state at all."""
    cases = {
        "absent_field": "no structured fields here, just prose about the change",
        "malformed_missing_colon": "6. Diff under review git diff origin/main...feature/x",
        "field_present_twice_differing_values": (
            "6. Diff under review: git diff origin/main...feature/a\n"
            "6. Diff under review: git diff origin/main...feature/b"
        ),
        "empty_value_then_blank_line_then_prose": (
            "6. Diff under review:\n\n**What to review:** <worker output round 1>"
        ),
        "reflowed_across_lines": "6. Diff under review:\ngit diff origin/main...feature/x",
    }
    for label, prompt_text in cases.items():
        with tempfile.TemporaryDirectory() as tmp:
            payload = {
                "tool_name": "Agent",
                "cwd": tmp,
                "tool_input": {
                    "subagent_type": "skeptic",
                    "description": "review",
                    "prompt": prompt_text,
                },
            }
            rc, parsed = _run_hook(payload)
            assert rc == 0
            assert not _is_denied(parsed), f"{label} must allow: {parsed}"
            assert not (Path(tmp) / ".agentic").exists(), (
                f"{label} must fail open with NO state written at all, but "
                f".agentic/ was created"
            )


def test_stable_key_survives_rolling_sha_ranges():
    """DS-180 regression: PR #760's exact failure shape - each rework
    round's diff line cites <prior-round-head>..<new-head> (a rolling
    range) with a narrative prefix. Pre-DS-180 this produced N distinct
    state files and the cap never engaged. With the conductor supplying
    the new `<key> | <diff>` form, round count must accumulate on ONE
    counter and round 4 must DENY."""
    key = "DS-177"
    shas = ["a" * 40, "b" * 40, "c" * 40, "d" * 40, "e" * 40]
    with tempfile.TemporaryDirectory() as tmp:
        expected_path = (
            Path(tmp) / ".agentic" / f"skeptic-round-{_unit_key_for_raw_identity(key)}.json"
        )
        for i in range(1, 4):
            base, head = shas[i - 1], shas[i]
            diff_line = f"- **Diff under review:** {key} | git diff {base}..{head}"
            rc, parsed = _run_hook(
                _raw_payload(tmp, diff_line, what_to_review=f"worker output round {i}")
            )
            assert not _is_denied(parsed), f"round {i} unexpectedly denied: {parsed}"
            assert expected_path.exists()
            state = json.loads(expected_path.read_text())
            assert state["round_count"] == i

        diff_line = f"- **Diff under review:** {key} | git diff {shas[3]}..{shas[4]}"
        rc, parsed = _run_hook(
            _raw_payload(tmp, diff_line, what_to_review="worker output round 4")
        )
        assert _is_denied(parsed), "round 4 of a stable-keyed unit must deny at the cap"

        state_files = list((Path(tmp) / ".agentic").glob("skeptic-round-*.json"))
        assert len(state_files) == 1, f"expected ONE state file, got {[p.name for p in state_files]}"


def test_stable_key_two_distinct_units_no_collision():
    """DS-180: two distinct units, even sharing an identical rolling SHA
    range shape, must get INDEPENDENT round budgets."""
    with tempfile.TemporaryDirectory() as tmp:
        for key in ("DS-180", "DS-181"):
            for i in range(1, 4):
                diff_line = f"- **Diff under review:** {key} | git diff {'a'*40}..{'b'*40}"
                rc, parsed = _run_hook(
                    _raw_payload(tmp, diff_line, what_to_review=f"{key} worker output round {i}")
                )
                assert not _is_denied(parsed), f"{key} round {i} unexpectedly denied: {parsed}"
                path = (
                    Path(tmp) / ".agentic"
                    / f"skeptic-round-{_unit_key_for_raw_identity(key)}.json"
                )
                state = json.loads(path.read_text())
                assert state["round_count"] == i

        state_files = sorted(p.name for p in (Path(tmp) / ".agentic").glob("skeptic-round-*.json"))
        assert len(state_files) == 2, f"expected 2 independent state files, got {state_files}"


def test_stable_key_empty_before_pipe_falls_back():
    """DS-180: a `| <diff>` value with nothing before the pipe is not a
    valid key - falls through to `_normalize_diff_identity()` on the
    full raw value, matching pre-DS-180 behavior for a malformed value.

    Round-2 rework (Minor 1): the original version of this test asserted
    only rc==0, not-denied, and that SOME `.agentic/` tree exists - none
    of which distinguishes the required "falls back to the legacy raw-text
    identity" behavior from a bug that captures a collidable placeholder
    key (e.g. a constant "EMPTY-KEY" string) on an empty left side; both
    shapes satisfy those three assertions and both write *a* state file.
    Asserting the exact expected state FILENAME (derived from the raw,
    un-keyed "Diff under review" value, matching every other stable-key
    test in this file) closes that gap - confirmed failing pre-fix (see
    the module docstring's regression-test obligation): mutating
    `_extract_stable_unit_key()` to `return "EMPTY-KEY"` on an empty left
    side reddens this assertion, because the written filename then derives
    from the placeholder instead of the raw value."""
    with tempfile.TemporaryDirectory() as tmp:
        diff_line = "6. Diff under review:  | git diff origin/main...feature/x"
        # The regex captures from the first non-whitespace, non-"*" char -
        # here that is the "|" itself, so the raw identity text handed to
        # `_normalize_diff_identity()` (and therefore hashed into the
        # filename) is this exact string, unchanged (not a diff-range
        # shape, so strategy 4 - "return raw text unchanged" - applies).
        raw_identity = "| git diff origin/main...feature/x"
        expected_path = (
            Path(tmp) / ".agentic" / f"skeptic-round-{_unit_key_for_raw_identity(raw_identity)}.json"
        )
        rc, parsed = _run_hook(
            _raw_payload(tmp, diff_line, what_to_review="worker output round 1")
        )
        assert rc == 0
        assert not _is_denied(parsed)
        assert expected_path.exists(), (
            "an empty key before the pipe must fall back to the legacy "
            "raw-text-derived state filename, not a collidable placeholder "
            f"key - expected {expected_path.name!r}, found "
            f"{[p.name for p in (Path(tmp) / '.agentic').glob('skeptic-round-*.json')]}"
        )


def test_diff_command_with_pipe_normalizes_to_legacy_base():
    """Major 2 (round 3) regression: a value that LOOKS like it has a
    pipe-prefixed key but is actually a diff command piped through `head`
    (e.g. `git diff <sha>..<sha> | head -200`) must be REJECTED by the
    shape gate and normalize to the base SHA exactly as it did before
    _extract_stable_unit_key existed - proving the naive
    partition-on-first-pipe regression is closed."""
    base = "1" * 40
    head = "2" * 40
    with tempfile.TemporaryDirectory() as tmp:
        diff_line = f"6. Diff under review: git diff {base}..{head} | head -200"
        rc, parsed = _run_hook(
            _raw_payload(tmp, diff_line, what_to_review="worker output round 1")
        )
        assert not _is_denied(parsed)
        expected_path = (
            Path(tmp) / ".agentic" / f"skeptic-round-{_unit_key_for_raw_identity(base)}.json"
        )
        assert expected_path.exists(), (
            "expected the value to normalize to the base SHA (legacy "
            "behavior), not to be treated as a stable key"
        )
        state = json.loads(expected_path.read_text())
        assert state["round_count"] == 1


def test_stable_key_two_units_of_one_ticket_get_independent_budgets():
    """Major 3 (round 2): a multi-unit ticket using per-unit keys
    (`<TICKET>-u<N>`, never a bare ticket id) must give each unit its
    own independent round budget."""
    with tempfile.TemporaryDirectory() as tmp:
        for key in ("DS-180-u1", "DS-180-u2"):
            for i in range(1, 4):
                diff_line = f"- **Diff under review:** {key} | git diff {'a'*40}..{'b'*40}"
                rc, parsed = _run_hook(
                    _raw_payload(tmp, diff_line, what_to_review=f"{key} worker output round {i}")
                )
                assert not _is_denied(parsed), f"{key} round {i} unexpectedly denied: {parsed}"
                path = (
                    Path(tmp) / ".agentic"
                    / f"skeptic-round-{_unit_key_for_raw_identity(key)}.json"
                )
                state = json.loads(path.read_text())
                assert state["round_count"] == i

        state_files = sorted(p.name for p in (Path(tmp) / ".agentic").glob("skeptic-round-*.json"))
        assert len(state_files) == 2, f"expected 2 independent state files, got {state_files}"


def test_stable_key_backticked_whole_value_accepts():
    """Minor 4 (round 3) / Minor 2 (round 4) regression: a whole-value-
    backticked field 6 carrying a VALID key, with a ROLLING base..head
    SHA range that changes every round - a constant backticked value
    would pass even without backtick-stripping (the pre-fix fallback
    path also accumulates on a constant raw string), which was the
    original test's vacuous-satisfiability defect. The rolling range
    genuinely distinguishes fixed vs unfixed behavior. Also asserts the
    state FILENAME directly (not just round_count), so a silent
    fall-through to the legacy path cannot pass by accident."""
    key = "DS-180"
    shas = ["a" * 40, "b" * 40, "c" * 40, "d" * 40, "e" * 40]
    with tempfile.TemporaryDirectory() as tmp:
        expected_path = (
            Path(tmp) / ".agentic" / f"skeptic-round-{_unit_key_for_raw_identity(key)}.json"
        )
        for i in range(1, 4):
            base, head = shas[i - 1], shas[i]
            diff_line = f"- **Diff under review:** `{key} | git diff {base}..{head}`"
            rc, parsed = _run_hook(
                _raw_payload(tmp, diff_line, what_to_review=f"worker output round {i}")
            )
            assert not _is_denied(parsed), f"round {i} unexpectedly denied: {parsed}"
            assert expected_path.exists(), (
                f"round {i}: expected the backtick-stripped stable-key state "
                f"file, not a legacy-normalized one"
            )
            state = json.loads(expected_path.read_text())
            assert state["round_count"] == i

        diff_line = f"- **Diff under review:** `{key} | git diff {shas[3]}..{shas[4]}`"
        rc, parsed = _run_hook(
            _raw_payload(tmp, diff_line, what_to_review="worker output round 4")
        )
        assert _is_denied(parsed), "round 4 must deny at the cap"

        state_files = list((Path(tmp) / ".agentic").glob("skeptic-round-*.json"))
        assert len(state_files) == 1, f"expected ONE state file, got {[p.name for p in state_files]}"


def test_pipe_separated_file_paths_no_key_no_collision():
    """Major 1 (round 2) regression: field 6's pre-implementation-review
    contract is `$UNIT_KEY | <file paths>` (content/commands/
    ds-implement-ticket.md's Architect-plan-review substitution). A
    conductor who omits `$UNIT_KEY` and instead pipe-separates two file
    paths (a plausible misreading - "leads with the key, then the paths")
    must NOT have the shared first path silently accepted as a stable
    key: two otherwise-distinct units sharing that first path (but
    differing in their second path) would then collide onto ONE round
    counter, denying the second unit's first review at a cap it never
    reached. Executed proof this closes: pre-fix, both values below
    normalized to the SAME key (`hooks-enforce-skeptic-round-cap.py-<hash
    of that literal string>`); the pre-DS-180 fallback path
    (`_normalize_diff_identity()` on the FULL raw text) does not collide,
    because the two full strings differ - confirmed by this test failing
    (both units landing on one state file, unit B denied at round 1) when
    run against the pre-fix `_extract_stable_unit_key()` with
    `_LOOKS_LIKE_FILE_PATH_RE`'s check removed."""
    value_a = "hooks/enforce-skeptic-round-cap.py | bin/tests/test_enforce_skeptic_round_cap.py"
    value_b = "hooks/enforce-skeptic-round-cap.py | content/references/skeptic-protocol.md"
    with tempfile.TemporaryDirectory() as tmp:
        path_a = (
            Path(tmp) / ".agentic" / f"skeptic-round-{_unit_key_for_raw_identity(value_a)}.json"
        )
        path_b = (
            Path(tmp) / ".agentic" / f"skeptic-round-{_unit_key_for_raw_identity(value_b)}.json"
        )
        assert path_a != path_b, "test setup bug: the two fallback identities must differ"

        # Unit A burns its whole budget.
        for i in range(1, 4):
            diff_line = f"- **Diff under review:** {value_a}"
            rc, parsed = _run_hook(
                _raw_payload(tmp, diff_line, what_to_review=f"unit-a fix {i}")
            )
            assert not _is_denied(parsed), f"unit A round {i} unexpectedly denied: {parsed}"
        diff_line = f"- **Diff under review:** {value_a}"
        rc, parsed = _run_hook(
            _raw_payload(tmp, diff_line, what_to_review="unit-a fix 4")
        )
        assert _is_denied(parsed), "unit A must be denied its 4th round"

        # Unit B's first round, from the SAME cwd, sharing unit A's first
        # pipe-segment, must still be allowed - the exact collision this
        # fix closes.
        diff_line = f"- **Diff under review:** {value_b}"
        rc, parsed = _run_hook(
            _raw_payload(tmp, diff_line, what_to_review="unit-b fix 1")
        )
        assert not _is_denied(parsed), (
            "unit B's first round must not inherit unit A's exhausted "
            "budget merely because both values share a leading file path"
        )
        assert path_a.exists() and path_b.exists()
        state_a = json.loads(path_a.read_text())
        state_b = json.loads(path_b.read_text())
        assert state_a["round_count"] == 3
        assert state_b["round_count"] == 1

        state_files = sorted(p.name for p in (Path(tmp) / ".agentic").glob("skeptic-round-*.json"))
        assert len(state_files) == 2, f"expected 2 independent state files, got {state_files}"


def test_pipe_no_range_caught_only_by_shape_gate():
    """Major 2 (round 2) regression: `_STABLE_KEY_SHAPE_RE` is the SOLE
    guard for a piped command containing no `..`/`...` range anywhere in
    the left side - the `".." in left` check cannot fire on this shape.
    Confirmed load-bearing by direct mutation: widening
    `_STABLE_KEY_SHAPE_RE` to admit whitespace (`^[A-Za-z0-9._/# -]+$`,
    the round-1 review's exact executed mutation) reddens this test,
    because the left side `git diff HEAD` then passes every remaining
    check and is accepted as the stable key `git-diff-HEAD` instead of
    falling back to `_normalize_diff_identity()`'s legacy path."""
    with tempfile.TemporaryDirectory() as tmp:
        diff_line = "6. Diff under review: git diff HEAD | head -200"
        # No ".." anywhere in "git diff HEAD | head -200" - only the shape
        # gate's whitespace rejection can catch this. The fallback
        # (_normalize_diff_identity on the full raw text) does not match
        # _DIFF_RANGE_RE (no ".." range at all), so it returns the raw
        # text unchanged (strategy 4).
        raw_identity = "git diff HEAD | head -200"
        expected_path = (
            Path(tmp) / ".agentic" / f"skeptic-round-{_unit_key_for_raw_identity(raw_identity)}.json"
        )
        rc, parsed = _run_hook(
            _raw_payload(tmp, diff_line, what_to_review="worker output round 1")
        )
        assert not _is_denied(parsed)
        assert expected_path.exists(), (
            "expected the value to fall back to the full-raw-text legacy "
            f"identity, not be accepted as a stable key - found "
            f"{[p.name for p in (Path(tmp) / '.agentic').glob('skeptic-round-*.json')]}"
        )
        state = json.loads(expected_path.read_text())
        assert state["round_count"] == 1


# --------------------------------------------------------------------------- #
# 34. DS-178 unit A: tool_use_ids round-trip through _load_state/_write_state
# --------------------------------------------------------------------------- #
def test_tool_use_ids_round_trip_through_load_state():
    """A `tool_use_id` supplied on the PreToolUse payload is recorded into
    the round-state file's `tool_use_ids` list and survives a second round
    (deduped, order-preserving) - proves the schema fix (both `_load_state`
    and `_write_state` previously handled a hardcoded 6-key dict only) is
    load-bearing. Executed mutation: reverting `_load_state`'s default dict
    and its `raw.get(...)` reconstruction to the pre-fix 6-key form (drop
    the `tool_use_ids` key entirely) reddens this test - the second round's
    state would carry no `tool_use_ids` key at all, or at best a
    fresh/truncated one, never the accumulated 2-entry list asserted below."""
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        rc1, parsed1 = _run_hook(
            _skeptic_payload(
                tmp, unit, what_to_review="worker output round 1",
                extra={"tool_use_id": "toolu_round1"},
            )
        )
        assert not _is_denied(parsed1)
        state1 = _read_state(tmp, unit)
        assert state1["tool_use_ids"] == ["toolu_round1"], state1

        rc2, parsed2 = _run_hook(
            _skeptic_payload(
                tmp, unit, what_to_review="worker output round 2",
                extra={"tool_use_id": "toolu_round2"},
            )
        )
        assert not _is_denied(parsed2)
        state2 = _read_state(tmp, unit)
        assert state2["tool_use_ids"] == ["toolu_round1", "toolu_round2"], state2

        # A repeated tool_use_id (e.g. a retried call) must not duplicate.
        rc3, parsed3 = _run_hook(
            _skeptic_payload(
                tmp, unit, what_to_review="worker output round 2",
                extra={"tool_use_id": "toolu_round2"},
            )
        )
        state3 = _read_state(tmp, unit)
        assert state3["tool_use_ids"] == ["toolu_round1", "toolu_round2"], state3


# --------------------------------------------------------------------------- #
# 35. DS-178 unit A: skeptic-tuid-index.json round trip
# --------------------------------------------------------------------------- #
def test_tuid_index_round_trip():
    """`.agentic/skeptic-tuid-index.json` maps each spawn's `tool_use_id` to
    the correct unit_key. Two distinct units get correctly separated
    entries in the SAME index file, and a second round on one unit updates
    (not duplicates) that unit's entries. Executed mutation: removing the
    `_update_tuid_index(path.parent, tool_use_id, unit_key)` call from
    `main()` reddens this test - the index file would never be created."""
    with tempfile.TemporaryDirectory() as tmp:
        unit_a = "feature/tuid-index-a"
        unit_b = "feature/tuid-index-b"

        rc, parsed = _run_hook(
            _skeptic_payload(
                tmp, unit_a, what_to_review="unit-a round 1",
                extra={"tool_use_id": "toolu_a1"},
            )
        )
        assert not _is_denied(parsed)
        rc, parsed = _run_hook(
            _skeptic_payload(
                tmp, unit_b, what_to_review="unit-b round 1",
                extra={"tool_use_id": "toolu_b1"},
            )
        )
        assert not _is_denied(parsed)

        index_path = Path(tmp) / ".agentic" / "skeptic-tuid-index.json"
        assert index_path.is_file(), "expected skeptic-tuid-index.json to be created"
        index = json.loads(index_path.read_text())
        assert index.get("toolu_a1") == _unit_key(unit_a), index
        assert index.get("toolu_b1") == _unit_key(unit_b), index

        # A second round on unit_a with a NEW tool_use_id adds a new entry
        # pointing at the SAME unit_key, without disturbing unit_b's entry.
        rc, parsed = _run_hook(
            _skeptic_payload(
                tmp, unit_a, what_to_review="unit-a round 2",
                extra={"tool_use_id": "toolu_a2"},
            )
        )
        assert not _is_denied(parsed)
        index_after = json.loads(index_path.read_text())
        assert index_after.get("toolu_a1") == _unit_key(unit_a), index_after
        assert index_after.get("toolu_a2") == _unit_key(unit_a), index_after
        assert index_after.get("toolu_b1") == _unit_key(unit_b), index_after


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
