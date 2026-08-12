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
 16. test_non_git_cwd_still_enforces                  - cwd is NOT a git repo -> the hook no longer calls
                                                         git at all, so rounds are still tracked normally
                                                         (this is the fix, not a fail-open case).
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
 22. test_round_stability_across_sha_range_rounds     - MAJOR 2 regression: a `git diff <base>..<head>` identity
                                                         resolves to ONE key across 4 sequential rework rounds
                                                         (changing head SHA, same base) and actually DENIES at
                                                         round 4, instead of minting a fresh key every round.
 23. test_diff_under_review_edge_cases_failopen       - MAJOR 1 + MAJOR 3 combined: absent field, malformed
                                                         (missing colon), field present twice with differing
                                                         values, empty value + blank line + prose (the literal
                                                         MAJOR 3 defect), and a value reflowed onto the next
                                                         line all allow and write NO state.

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

    Only used by tests that specifically want to prove branch-independence;
    most tests use a plain (non-git) tempdir to prove the hook no longer
    depends on git at all.
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


def _skeptic_payload(
    cwd: str,
    unit: str = "feature/round-cap-test",
    what_to_review: str | None = None,
    extra: dict | None = None,
) -> dict:
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


def test_non_git_cwd_still_enforces():
    """The fix's whole point: cwd no longer needs to be a git repo at all -
    the unit key comes from the prompt, not `git rev-parse`."""
    with tempfile.TemporaryDirectory() as tmp:
        # Deliberately NOT a git repo.
        unit = "feature/round-cap-test"
        rc, parsed = _run_hook(_skeptic_payload(tmp, unit, what_to_review="round 1"))
        assert rc == 0
        assert not _is_denied(parsed)
        state = _read_state(tmp, unit)
        assert state["round_count"] == 1


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
    return {
        "tool_name": "Agent",
        "cwd": tmp,
        "tool_input": {
            "subagent_type": "skeptic",
            "description": "review",
            "prompt": _raw_prompt(diff_line, what_to_review),
        },
    }


# The exact hyphen-bullet form at content/references/skeptic-protocol.md:340
# ("- Diff under review: <as today>") and the bold-bullet form real spawn
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


def test_round_stability_across_sha_range_rounds():
    """MAJOR 2 regression: a `git diff <base-sha>..<changing-head-sha>`
    identity (the form the Skeptic sign-off contract's own `Reviewed:
    <base-sha>..<head-sha>` shape mirrors) must resolve to ONE key across
    sequential rework rounds and actually DENY at round 4 - pre-fix, each
    round's new head SHA minted its own state file and the cap never
    engaged (measured: round 4 ALLOWed, 4 separate state files)."""
    with tempfile.TemporaryDirectory() as tmp:
        base_sha = "a" * 40
        heads = ["b" * 40, "c" * 40, "d" * 40, "e" * 40]
        expected_path = (
            Path(tmp) / ".agentic" / f"skeptic-round-{_unit_key_for_raw_identity(base_sha)}.json"
        )

        for i, head in enumerate(heads[:3], start=1):
            diff_line = f"6. Diff under review: git diff {base_sha}..{head}"
            rc, parsed = _run_hook(
                _raw_payload(tmp, diff_line, what_to_review=f"worker output round {i}")
            )
            assert not _is_denied(parsed), f"round {i} unexpectedly denied: {parsed}"
            assert expected_path.exists(), (
                "all rounds of the SAME unit must resolve to the base-SHA-keyed state file"
            )
            state = json.loads(expected_path.read_text())
            assert state["round_count"] == i, (
                f"MAJOR 2 regression: base..head SHA range must resolve to ONE stable "
                f"key across rounds - got round_count={state['round_count']} at round {i}"
            )

        # 4th round (yet another new head SHA) must DENY - proves the cap
        # actually engages instead of minting a fresh key every round.
        diff_line = f"6. Diff under review: git diff {base_sha}..{heads[3]}"
        rc, parsed = _run_hook(
            _raw_payload(tmp, diff_line, what_to_review="worker output round 4")
        )
        assert _is_denied(parsed), "round 4 of a SHA-range-keyed unit must be denied at the cap"

        state_files = list((Path(tmp) / ".agentic").glob("skeptic-round-*.json"))
        assert len(state_files) == 1, (
            f"expected exactly ONE state file across all 4 rounds, got {[p.name for p in state_files]}"
        )


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


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
