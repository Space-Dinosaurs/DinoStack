#!/usr/bin/env python3
"""
Regression tests for hooks/enforce-skeptic-round-cap.py.

Test groups:
  0. test_round_cap_constant_is_two                   - DS-232: pins `_ROUND_CAP == 2` literally, so the
                                                         cap is guarded by something other than itself.
  1. test_round_1_2_allowed                          - rounds 1-2 all ALLOW, round_count advances
                                                         (each round carries DIFFERENT "What to
                                                         review" content, matching the real
                                                         sequential-rounds shape - a fresh Worker
                                                         output every round).
  2. test_round_3_denied_without_grant               - 3rd round with no operator grant -> DENY; the
                                                         reason names the unit, the grant token, both
                                                         permitted actions and item 6, never `decision:"`.
  3. test_hand_written_decision_never_reopens_cap     - a hand-written escalate/ship (with or without an
                                                         operator_quote) in the state file never reopens the cap.
  4. test_operator_grant_allows_exactly_one_round     - the deny's token in a typed operator turn allows
                                                         round 3 only; round 4 needs a new token.
     test_grant_is_bound_to_its_unit                  - unit A's token never opens unit B's cap.
     test_non_operator_lines_never_grant              - the token in a peer relay, compaction summary,
                                                         sidechain line, tool_result, assistant text,
                                                         task-notification, queued relay or peer attachment,
                                                         or queue-operation line never grants.
     test_every_operator_line_shape_grants            - every real line shape of a genuine operator message
                                                         (typed, image+text, slash-command args, the three
                                                         mid-turn queued attachments, SDK, Desktop, pre-origin
                                                         CLI) grants.
     test_subagent_transcript_never_grants            - a token in a `subagents/` transcript never grants.
  5. test_unreadable_transcript_keeps_deny            - absent, directory or nonexistent transcript_path
                                                         keeps the deny.
  6. test_grant_requires_successful_persist           - a grant whose round cannot be written to the
                                                         state file denies, on every retry.
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
 28. test_stable_key_empty_before_pipe_is_denied       - a `| <diff>` value with nothing before the pipe has no
                                                         key and is denied with no round state written.
 29. test_diff_command_with_pipe_is_denied             - a diff command piped through `head` is rejected by the
                                                         shape gate and denied, never accepted as a key.
 30. test_stable_key_two_units_of_one_ticket_get_independent_budgets - Major 3 (round 2): a multi-unit ticket
                                                         using per-unit keys (`<TICKET>-u<N>`, never a bare
                                                         ticket id) gives each unit its own independent round
                                                         budget.
 31. test_stable_key_backticked_whole_value_accepts    - Minor 4 (round 3) / Minor 2 (round 4) regression: a
                                                         whole-value-backticked field 6 carrying a VALID key,
                                                         with a ROLLING base..head SHA range that changes every
                                                         round, must accumulate on one counter and deny at
                                                         round 4; also asserts the state FILENAME directly.
 32. test_pipe_separated_file_paths_are_denied       - field 6 with `$UNIT_KEY` omitted and two pipe-separated
                                                         file paths is denied, so a shared first path never
                                                         becomes a key two units collide on.
 33. test_pipe_no_range_caught_only_by_shape_gate       - Major 2 (round 2) regression: a piped diff command with
                                                         NO `..`/`...` range in the left side (so the `".." in
                                                         left` guard cannot catch it) is rejected solely by
                                                         `_STABLE_KEY_SHAPE_RE` (the whitespace in the piped
                                                         command) - confirms the shape gate is independently
                                                         load-bearing, not merely redundant with the `..` check;
                                                         the spawn is denied.
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
 36. test_tuid_index_concurrent_writes_not_lost         - M4 (round-3) regression: 40 parallel hook invocations
                                                         for the same unit all get a distinct
                                                         skeptic-tuid-index.json entry - `_update_tuid_index()`'s
                                                         read-merge-write is guarded by a best-effort flock so
                                                         concurrent writers never clobber each other's entries.
 37. test_state_file_preserves_unknown_keys_round_trip  - m4 regression: a genuinely unknown top-level key on a
                                                         hand-edited state file (e.g. `extra_key`, a `nested`
                                                         object) survives a load-then-write round trip via
                                                         `_load_state`/`_write_state`'s `_extra` passthrough
                                                         bucket, while the active schema still advances normally.
 T1. test_keyless_field6_is_denied_without_state   - 15 verbatim keyless field-6 values (AUT-1245, AUT-1178,
                                                         DS-45, piped, file-path, `.x`-suffixed, `~`/`^` ranges)
                                                         are denied; no round state, no tuid index, exactly one
                                                         fire-log `deny` line; the reason carries every element
                                                         a conductor needs to form a key.
 T2. test_keyed_detail_variants_share_one_counter  - AUT-1245's four detail wordings behind one key: allow,
                                                         allow, deny, deny; one state file at round_count 2.
 T3. test_review_kind_suffixes_get_own_counters    - `-plan`, `-assembled-plan`, diff and `-meta` reviews of
                                                         one ticket each keep their own counter.
 T4. test_unit_key_literal                         - `AUT-1245 | x` maps to the literal state file
                                                         `skeptic-round-AUT-1245-decefac675.json`.

Run with: python3 -m pytest bin/tests/test_enforce_skeptic_round_cap.py -x
       or: python3 bin/tests/test_enforce_skeptic_round_cap.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

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
    *unit*: the unit's stable key, then the diff command."""
    return f"{unit} | git diff origin/main...{unit}"


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


def _run_hook(
    payload: dict, run_cwd: str | None = None, timeout: float | None = None
) -> tuple[int, dict | None]:
    """Invoke the hook as a subprocess. *run_cwd* pins the SUBPROCESS's own
    OS-level cwd - distinct from payload["cwd"], the JSON field the hook's
    own logic reads. Default None preserves prior behavior (inherits the
    ambient test-runner cwd) for every existing call site. Any test
    exercising a payload-cwd-missing/fallback path MUST pin this on every
    invocation - an unpinned call under a `cwd = cwd or os.getcwd()`-style
    mutation would otherwise write a real state file into whatever this
    process's own cwd happens to be (see test_missing_cwd_failopen)."""
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=run_cwd,
        timeout=timeout,
    )
    out = result.stdout.strip()
    parsed = json.loads(out) if out else None
    return result.returncode, parsed


@pytest.fixture(autouse=True)
def _isolate_claude_config(monkeypatch, tmp_path):
    """Round-3 rework, Minor 3: the hook's sibling-deny consultation (see
    `_sibling_registered` in the hook itself) reads settings.json files
    off `CLAUDE_CONFIG_DIR` (falling back to `~/.claude`). Without this
    fixture, EVERY `_run_hook` call in this file inherits the real
    ambient environment, so a local run on a machine whose real
    `~/.claude/settings.json` genuinely registers enforce-skeptic-
    neutrality.py/enforce-tier.py reads that file on every invocation -
    diverging from a CI run (no such file exists there) and violating
    "never read the real settings.json in tests." Autouse: applies to
    every test in this module without touching individual call sites.
    Clears all four harness config-dir env vars and points
    `CLAUDE_CONFIG_DIR` (and `HOME`, so the same-machine fallback path an
    unset config-dir var would otherwise take also lands off-machine) at
    a fresh, empty, per-test scratch directory - no settings.json exists
    there, so every sibling registration in this file's tests is
    "unconfirmed" (today's pre-consultation persist behavior), matching
    what every test in this file already asserts."""
    scratch = tmp_path / "claude-config-isolated"
    scratch.mkdir()
    for var in ("AGENTIC_CONFIG_DIR", "CODEX_HOME", "PI_CODING_AGENT_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(scratch))
    monkeypatch.setenv("HOME", str(scratch))


def _is_denied(parsed: dict | None) -> bool:
    if not parsed:
        return False
    return parsed.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def _deny_reason(parsed: dict | None) -> str:
    if not parsed:
        return ""
    return parsed.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


def _unit_key(unit: str) -> str:
    """Mirrors `_unit_key()` in the hook for `_diff_identity(unit)`, whose
    stable key is `unit` itself."""
    identity = unit
    sanitized = _KEY_SAFE_RE.sub("-", identity.strip())[:_MAX_KEY_LEN]
    digest = hashlib.sha1(identity.encode("utf-8", "replace")).hexdigest()[:10]
    return f"{sanitized}-{digest}"


def _unit_key_for_raw_identity(identity: str) -> str:
    """Same sanitize+digest as `_unit_key()`, for a test that writes its
    own "Diff under review" line with *identity* as the stable key."""
    sanitized = _KEY_SAFE_RE.sub("-", identity.strip())[:_MAX_KEY_LEN]
    digest = hashlib.sha1(identity.encode("utf-8", "replace")).hexdigest()[:10]
    return f"{sanitized}-{digest}"


def _state_path(cwd: str, unit: str) -> Path:
    return Path(cwd) / ".agentic" / f"skeptic-round-{_unit_key(unit)}.json"


def _read_state(cwd: str, unit: str) -> dict:
    return json.loads(_state_path(cwd, unit).read_text())


# --------------------------------------------------------------------------- #
# 0. The cap CONSTANT itself, pinned independently of the behavioral tests
# --------------------------------------------------------------------------- #
def test_round_cap_constant_is_two():
    """DS-232 moved the default Skeptic round cap from 3 to 2. Every other
    test in this file derives its round boundaries from the hook's OWN
    behavior, so all of them would stay green if `_ROUND_CAP` silently
    drifted back to 3 and the boundaries were shifted to match. This test
    pins the literal value, so the cap is guarded by something other than
    itself. Change it only alongside a deliberate policy change to
    `content/sections/05-qa-gate.md` §Re-route limits."""
    spec = importlib.util.spec_from_file_location("_round_cap_hook", _HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._ROUND_CAP == 2


# --------------------------------------------------------------------------- #
# 1. Rounds 1-2 permitted (each round has different Worker output, the real
#    sequential-rounds shape)
# --------------------------------------------------------------------------- #
def test_round_1_2_allowed():
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        for expected_round in (1, 2):
            rc, parsed = _run_hook(
                _skeptic_payload(tmp, unit, what_to_review=f"worker output round {expected_round}")
            )
            assert rc == 0
            assert not _is_denied(parsed), f"round {expected_round} unexpectedly denied: {parsed}"
            state = _read_state(tmp, unit)
            assert state["round_count"] == expected_round


# --------------------------------------------------------------------------- #
# 2-6. Past the cap only an operator grant in the main-session transcript
#      reopens review; nothing written to the state file does.
# --------------------------------------------------------------------------- #
_TOKEN_RE = re.compile(r"skeptic-grant-[0-9a-f]{8}")


def _typed_user_line(text: str) -> dict:
    return {
        "type": "user",
        "isSidechain": False,
        "message": {"role": "user", "content": text},
        "uuid": "u-typed",
        "sessionId": "s-1",
    }


def _write_transcript(directory: str, lines: list[dict]) -> str:
    """Write a JSONL transcript with real Claude Code line shapes and return
    its path (outside `.agentic/`)."""
    path = Path(directory) / "session-transcript.jsonl"
    path.write_text("".join(json.dumps(obj) + "\n" for obj in lines))
    return str(path)


def _spend_two_rounds(tmp: str, unit: str) -> None:
    for i in (1, 2):
        rc, parsed = _run_hook(_skeptic_payload(tmp, unit, what_to_review=f"worker output round {i}"))
        assert rc == 0
        assert not _is_denied(parsed), f"round {i} unexpectedly denied: {parsed}"


def _token_from_deny(parsed: dict | None) -> str:
    match = _TOKEN_RE.search(_deny_reason(parsed))
    assert match, f"deny reason carries no grant token: {parsed}"
    return match.group(0)


def test_round_3_denied_without_grant():
    """Mutation that reddens it: revert `_DENY_CAP_TEMPLATE` to the
    pre-grant ship/escalate text."""
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        _spend_two_rounds(tmp, unit)

        rc, parsed = _run_hook(_skeptic_payload(tmp, unit, what_to_review="worker output round 3"))
        assert rc == 0
        assert _is_denied(parsed), "3rd round with no operator grant must be denied"
        reason = _deny_reason(parsed)
        assert "2 rounds" in reason
        assert _TOKEN_RE.search(reason)
        assert _unit_key(unit) in reason
        assert "Do not spawn another Skeptic" in reason
        assert "accepted debt" in reason
        assert "item 6" in reason
        assert 'decision:"' not in reason
        assert _read_state(tmp, unit)["round_count"] == 2


@pytest.mark.parametrize(
    "hand_written",
    [
        {"decision": "escalate"},
        {"decision": "ship", "unresolved_critical": False},
        {"decision": "escalate", "operator_quote": "operator approves another round"},
    ],
    ids=["escalate", "ship-no-critical", "escalate-with-quote"],
)
def test_hand_written_decision_never_reopens_cap(hand_written):
    """Mutation that reddens it: load `decision` in `_load_state` again
    and allow on `decision == "escalate"` in the cap branch of `_decide`."""
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        _spend_two_rounds(tmp, unit)
        path = _state_path(tmp, unit)
        state = json.loads(path.read_text())
        state.update(hand_written)
        path.write_text(json.dumps(state))

        rc, parsed = _run_hook(_skeptic_payload(tmp, unit, what_to_review="worker output round 3"))
        assert rc == 0
        assert _is_denied(parsed), f"a hand-written {hand_written} reopened the cap"
        assert _read_state(tmp, unit)["round_count"] == 2


def test_operator_grant_allows_exactly_one_round():
    """Mutation that reddens it: drop `next_round` from `_grant_token`,
    so round 4 reuses round 3's token and is allowed."""
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        _spend_two_rounds(tmp, unit)

        _, denied = _run_hook(_skeptic_payload(tmp, unit, what_to_review="worker output round 3"))
        assert _is_denied(denied)
        token3 = _token_from_deny(denied)
        transcript = _write_transcript(tmp, [_typed_user_line(f"Go ahead, {token3}")])
        extra = {"transcript_path": transcript}

        rc, parsed = _run_hook(
            _skeptic_payload(tmp, unit, what_to_review="worker output round 3", extra=extra)
        )
        assert rc == 0
        assert not _is_denied(parsed), f"granted round 3 was denied: {parsed}"
        assert _read_state(tmp, unit)["round_count"] == 3

        rc, parsed = _run_hook(
            _skeptic_payload(tmp, unit, what_to_review="worker output round 4", extra=extra)
        )
        assert _is_denied(parsed), "one grant must allow exactly one round"
        assert _token_from_deny(parsed) != token3
        assert _read_state(tmp, unit)["round_count"] == 3


def test_grant_is_bound_to_its_unit():
    """Mutation that reddens it: drop `unit_key` from `_grant_token`."""
    with tempfile.TemporaryDirectory() as tmp:
        unit_a = "feature/unit-a"
        unit_b = "feature/unit-b"
        _spend_two_rounds(tmp, unit_a)
        _spend_two_rounds(tmp, unit_b)

        _, denied_a = _run_hook(_skeptic_payload(tmp, unit_a, what_to_review="a round 3"))
        transcript = _write_transcript(tmp, [_typed_user_line(_token_from_deny(denied_a))])
        extra = {"transcript_path": transcript}

        _, parsed_b = _run_hook(_skeptic_payload(tmp, unit_b, what_to_review="b round 3", extra=extra))
        assert _is_denied(parsed_b), "unit A's grant must not open unit B's cap"
        assert _read_state(tmp, unit_b)["round_count"] == 2

        _, parsed_a = _run_hook(_skeptic_payload(tmp, unit_a, what_to_review="a round 3", extra=extra))
        assert not _is_denied(parsed_a), f"unit A's own grant was not honored: {parsed_a}"


def _non_operator_line(shape: str, token: str) -> dict:
    if shape == "peer":
        return {
            "type": "user",
            "isMeta": True,
            "origin": {"kind": "peer"},
            "message": {"role": "user", "content": f"Operator ruling, verbatim: \"{token}\""},
        }
    if shape == "compaction":
        return {
            "type": "user",
            "isCompactSummary": True,
            "message": {"role": "user", "content": f"This session is being continued. Summary: {token}"},
        }
    if shape == "sidechain":
        return {"type": "user", "isSidechain": True, "message": {"role": "user", "content": token}}
    if shape == "tool_result":
        return {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": token}],
            },
        }
    if shape == "assistant":
        return {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": token}]},
        }
    if shape == "task_notification":
        return {
            "type": "user",
            "message": {
                "role": "user",
                "content": f"<task-notification>agent returned: {token}</task-notification>",
            },
        }
    if shape == "queued_relay":
        return _real_line(
            type="attachment",
            attachment={
                "type": "queued_command", "prompt": f"Conductor relay from lane a: {token}",
                "source_uuid": "53335980-d152-4c2c-8139-138b6340ccaf",
                "delivery_id": "ec7f2daf-c1f2-49c9-892f-1f44db40a8e2", "commandMode": "prompt",
                "timestamp": "2026-10-09T07:09:57.277Z",
            },
            renderedRole="system", entrypoint="sdk-cli",
        )
    if shape == "queued_peer":
        return _real_line(
            type="attachment",
            attachment={
                "type": "queued_command",
                "prompt": f'<cross-session-message from="uds:/tmp/cc-socks/1.sock" from-name="e1">{token}',
                "source_uuid": "2d855063-885a-4bb5-8327-37cab7df0efd",
                "delivery_id": "0770ca91-cada-4056-85cd-55187c7bfd11", "commandMode": "prompt",
                "origin": {"kind": "peer", "from": "uds:/tmp/cc-socks/1.sock", "name": "e1", "body": token},
                "timestamp": "2026-10-03T18:01:24.143Z", "isMeta": True,
            },
            entrypoint="cli",
        )
    if shape == "queue_operation":
        return {
            "type": "queue-operation", "operation": "enqueue", "timestamp": "2026-10-05T20:28:10.904Z",
            "sessionId": "489b65f7-badb-4727-b526-dc4384536a85", "content": f"approved: {token}",
        }
    raise AssertionError(shape)


@pytest.mark.parametrize(
    "shape",
    [
        "peer", "compaction", "sidechain", "tool_result", "assistant", "task_notification",
        "queued_relay", "queued_peer", "queue_operation",
    ],
)
def test_non_operator_lines_never_grant(shape):
    """Mutations that redden it: delete the `isCompactSummary` skip
    (compaction); delete the `isSidechain` skip (sidechain); replace
    `genuine_user_text` with a `type == "user"` check (tool_result,
    task_notification); accept any line containing the token (all); accept
    a queued attachment whatever its origin (queued_relay, queued_peer);
    read a `queue-operation` line's content (queue_operation)."""
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        _spend_two_rounds(tmp, unit)
        _, denied = _run_hook(_skeptic_payload(tmp, unit, what_to_review="worker output round 3"))
        token = _token_from_deny(denied)
        transcript = _write_transcript(tmp, [_non_operator_line(shape, token)])

        _, parsed = _run_hook(
            _skeptic_payload(
                tmp, unit, what_to_review="worker output round 3", extra={"transcript_path": transcript}
            )
        )
        assert _is_denied(parsed), f"a {shape} line granted a round"
        assert _read_state(tmp, unit)["round_count"] == 2


_REAL_LINE_ENVELOPE = {
    "parentUuid": "8d6857ee-f88c-4c65-9b5e-74023579af82",
    "isSidechain": False,
    "uuid": "da82772d-3071-42cc-b746-7c6230200117",
    "timestamp": "2026-10-09T04:24:25.112Z",
    "userType": "external",
    "cwd": "/repo",
    "sessionId": "02b24d2a-785d-45a9-a50f-4dd2260bc890",
    "version": "2.1.287",
    "gitBranch": "develop",
}


def _real_line(**fields) -> dict:
    line = dict(_REAL_LINE_ENVELOPE)
    line.update(fields)
    return line


def _image_block() -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}


def _operator_line(shape: str, token: str) -> dict:
    """One genuine operator message per line shape found in real transcripts."""
    text = f"one more round on this unit: {token}"
    if shape == "typed":
        return _real_line(
            type="user", promptId="p-1", message={"role": "user", "content": text},
            permissionMode="bypassPermissions", origin={"kind": "human"}, promptSource="typed",
            entrypoint="cli",
        )
    if shape == "typed_image_text":
        return _real_line(
            type="user", promptId="p-1",
            message={"role": "user", "content": [{"type": "text", "text": f"[Image #1] {text}"}, _image_block()]},
            imagePasteIds=[1], origin={"kind": "human"}, promptSource="typed", entrypoint="cli",
        )
    if shape == "slash_command_args":
        return _real_line(
            type="user", promptId="p-1",
            message={
                "role": "user",
                "content": (
                    "<command-message>ds-implement-ticket</command-message>\n"
                    "<command-name>/ds-implement-ticket</command-name>\n"
                    f"<command-args>DS-1 {token}</command-args>"
                ),
            },
            origin={"kind": "human"}, entrypoint="cli",
        )
    if shape == "queued_mid_turn":
        return _real_line(
            type="attachment",
            attachment={
                "type": "queued_command", "prompt": text, "source_uuid": "a2810fb1-1698-477c-b20e-24ea7862ff52",
                "commandMode": "prompt", "origin": {"kind": "human"},
                "timestamp": "2026-10-09T04:24:25.112Z", "humanTurn": True,
            },
            rendered=[{"content": "<system-reminder>\nThe user sent a new message while you were working"}],
            session_id="02b24d2a-785d-45a9-a50f-4dd2260bc890", entrypoint="cli",
        )
    if shape == "queued_mid_turn_legacy":
        return _real_line(
            type="attachment",
            attachment={
                "type": "queued_command", "prompt": text, "commandMode": "prompt",
                "origin": {"kind": "human"}, "timestamp": "2026-10-09T04:24:25.112Z",
            },
            session_id="02b24d2a-785d-45a9-a50f-4dd2260bc890", entrypoint="cli",
        )
    if shape == "queued_mid_turn_image_text":
        return _real_line(
            type="attachment",
            attachment={
                "type": "queued_command",
                "prompt": [{"type": "text", "text": f"[Image #14] {text}"}, _image_block()],
                "imagePasteIds": [14], "commandMode": "prompt", "origin": {"kind": "human"},
                "timestamp": "2026-10-09T04:24:25.112Z",
            },
            session_id="02b24d2a-785d-45a9-a50f-4dd2260bc890", entrypoint="cli",
        )
    if shape == "sdk_prompt":
        return _real_line(
            type="user", promptId="p-1", message={"role": "user", "content": text},
            permissionMode="bypassPermissions", promptSource="sdk", turnOrigin="sdk",
            turnPosition={"promptIndex": 0, "turnIndex": 1}, entrypoint="sdk-cli",
        )
    if shape == "desktop":
        return _real_line(
            type="user", promptId="p-1", message={"role": "user", "content": text},
            permissionMode="bypassPermissions", entrypoint="claude-desktop",
        )
    if shape == "cli_pre_origin_text_block":
        return _real_line(
            type="user", promptId="p-1", message={"role": "user", "content": [{"type": "text", "text": text}]},
            session_id="02b24d2a-785d-45a9-a50f-4dd2260bc890", entrypoint="cli",
        )
    raise AssertionError(shape)


_OPERATOR_SHAPES = [
    "typed", "typed_image_text", "slash_command_args", "queued_mid_turn", "queued_mid_turn_legacy",
    "queued_mid_turn_image_text", "sdk_prompt", "desktop", "cli_pre_origin_text_block",
]


@pytest.mark.parametrize("shape", _OPERATOR_SHAPES)
def test_every_operator_line_shape_grants(shape):
    """Every line shape real transcripts use for a genuine operator message
    carries a grant. Mutations that redden it: make `_operator_texts` return
    [] for attachments (the three queued shapes); delete its human-origin
    `user` branch (slash_command_args); make `_content_texts` return [] for
    lists (typed_image_text, queued_mid_turn_image_text)."""
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        _spend_two_rounds(tmp, unit)
        _, denied = _run_hook(_skeptic_payload(tmp, unit, what_to_review="worker output round 3"))
        transcript = _write_transcript(tmp, [_operator_line(shape, _token_from_deny(denied))])

        _, parsed = _run_hook(
            _skeptic_payload(
                tmp, unit, what_to_review="worker output round 3", extra={"transcript_path": transcript}
            )
        )
        assert not _is_denied(parsed), f"a {shape} operator line did not grant: {parsed}"
        assert _read_state(tmp, unit)["round_count"] == 3


def test_subagent_transcript_never_grants():
    """A grant is read only from the main-session transcript. Mutation that
    reddens it: replace the `/subagents/` path check in `_operator_granted`
    with `if False:`."""
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        _spend_two_rounds(tmp, unit)
        _, denied = _run_hook(_skeptic_payload(tmp, unit, what_to_review="worker output round 3"))
        token = _token_from_deny(denied)
        sub_dir = Path(tmp) / "session" / "subagents"
        sub_dir.mkdir(parents=True)
        transcript = _write_transcript(str(sub_dir), [_operator_line("typed", token)])

        _, parsed = _run_hook(
            _skeptic_payload(
                tmp, unit, what_to_review="worker output round 3", extra={"transcript_path": transcript}
            )
        )
        assert _is_denied(parsed), "a token in a subagent transcript granted a round"
        assert _read_state(tmp, unit)["round_count"] == 2


@pytest.mark.parametrize("variant", ["absent", "directory", "nonexistent"])
def test_unreadable_transcript_keeps_deny(variant):
    """Mutation that reddens it: remove the try/except in
    `_operator_granted` - the directory case then raises into main()'s
    catch-all, which exits 0 and allows."""
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        _spend_two_rounds(tmp, unit)
        extra: dict = {}
        if variant == "directory":
            transcript_dir = Path(tmp) / "transcript-dir"
            transcript_dir.mkdir()
            extra["transcript_path"] = str(transcript_dir)
        elif variant == "nonexistent":
            extra["transcript_path"] = str(Path(tmp) / "missing.jsonl")

        rc, parsed = _run_hook(
            _skeptic_payload(tmp, unit, what_to_review="worker output round 3", extra=extra)
        )
        assert rc == 0
        assert _is_denied(parsed), f"{variant} transcript must keep the cap deny"


def test_grant_requires_successful_persist():
    """Mutation that reddens it: ignore `_write_state`'s return value in
    main(), so a grant whose round cannot be recorded allows every retry."""
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/round-cap-test"
        _spend_two_rounds(tmp, unit)
        _, denied = _run_hook(_skeptic_payload(tmp, unit, what_to_review="worker output round 3"))
        transcript = _write_transcript(tmp, [_typed_user_line(_token_from_deny(denied))])
        extra = {"transcript_path": transcript}

        agentic_dir = Path(tmp) / ".agentic"
        agentic_dir.chmod(0o555)
        try:
            for attempt in (1, 2):
                rc, parsed = _run_hook(
                    _skeptic_payload(tmp, unit, what_to_review=f"round 3 try {attempt}", extra=extra)
                )
                assert rc == 0
                assert _is_denied(parsed), f"attempt {attempt}: unpersisted grant must deny"
                assert "could not be written" in _deny_reason(parsed)
        finally:
            agentic_dir.chmod(stat.S_IRWXU)
        assert _read_state(tmp, unit)["round_count"] == 2


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
            ("first fix attempt", "second fix attempt"), start=1
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
        for i in range(2):
            _run_hook(_skeptic_payload(tmp, unit_a, what_to_review=f"unit-a fix {i + 1}"))
        rc, parsed = _run_hook(_skeptic_payload(tmp, unit_a, what_to_review="unit-a fix 3"))
        assert _is_denied(parsed), "unit A must be denied its 3rd round"

        # Unit B's first spawn, from the SAME cwd, must still be allowed -
        # this is the exact bug: before the fix, both units shared one
        # `skeptic-round-<branch>.json` counter keyed off the conductor's
        # own branch, so unit A's exhaustion silently denied unit B too.
        rc, parsed = _run_hook(_skeptic_payload(tmp, unit_b, what_to_review="unit-b fix 1"))
        assert not _is_denied(parsed), "unit B's first round must not inherit unit A's exhausted budget"
        state_b = _read_state(tmp, unit_b)
        assert state_b["round_count"] == 1
        state_a = _read_state(tmp, unit_a)
        assert state_a["round_count"] == 2
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

    with tempfile.TemporaryDirectory() as tmp2:
        # DS-181 AC4 repair: the case above is vacuous against its own
        # named gate (`if tool_name not in ("Task", "Agent"): sys.exit(0)`)
        # - removing that gate entirely still reddens 0 tests, because
        # tool_input={"file_path": "/x"} has no subagent_type, so the very
        # next gate independently produces the same exit-0/no-deny
        # outcome. This second sub-case uses a subagent-shaped tool_input
        # with tool_name deliberately overridden to "Read" so ONLY the
        # tool_name gate can be what stops it.
        unit = "feature/round-cap-test"
        payload2 = _skeptic_payload(tmp2, unit, what_to_review="x")
        payload2["tool_name"] = "Read"
        rc2, parsed2 = _run_hook(payload2)
        assert rc2 == 0
        assert not _is_denied(parsed2)
        assert not _state_path(tmp2, unit).exists(), (
            "a Read tool_name must never be treated as an Agent/Task "
            "skeptic spawn even when tool_input looks like one"
        )


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
    """DS-181 repair: a bare no-cwd payload run WITHOUT pinning run_cwd
    would inherit the test-runner's own OS-level cwd - masking the
    `cwd = data.get("cwd")` gate via `_state_path`'s independent fail-open
    on any real repo it happens to run inside. Both sub-cases below pin
    run_cwd to a throwaway TemporaryDirectory so neither can ever write
    into this repo's own live .agentic/ (see Constraints in the DS-181
    plan - an unpinned first call in an earlier draft did exactly that)."""
    payload = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "skeptic", "prompt": _prompt("x")},
    }
    with tempfile.TemporaryDirectory() as bare:
        rc, parsed = _run_hook(payload, run_cwd=bare)
        assert rc == 0
        assert not _is_denied(parsed)
    with tempfile.TemporaryDirectory() as controlled:
        _ensure_git_marker(controlled)
        rc2, parsed2 = _run_hook(payload, run_cwd=controlled)
        assert rc2 == 0
        assert not _is_denied(parsed2)
        assert not (Path(controlled) / ".agentic").exists(), (
            "a missing payload cwd must never fall back to the hook "
            "process's own OS-level working directory"
        )


def test_unextractable_identity_failopen():
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
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
    """Round-2 review fix (Major 2): the mutation that reddens this is a
    4-part combination, not the 3-part one originally recorded - (1) drop
    the `found_git_ancestor` gate in `_state_path` (treat it as always
    True), (2) strip `_write_state`'s own internal `try/except: pass`
    guard, (3) drop `parents=True` from its `mkdir` call, AND (4) remove
    `main()`'s outer `except Exception: sys.exit(0)` catch-all. Parts
    (1)-(3) alone still redden nothing in *this* test, because `main()`'s
    outer catch-all swallows whatever exception (1)-(3) cause and still
    exits 0 - part (4) is required for the resulting exception to actually
    propagate past `main()` as a nonzero process exit code. (Part (1) alone
    does redden a different test, `test_state_resolution_fails_open_with_no_git_ancestor`
    - not via a nonzero exit code, but because dropping the
    `found_git_ancestor` gate makes `_state_path` write a state file that
    test's own assertion requires to be absent.) Confirmed failing pre-fix
    (i.e. with the mutation applied): rc == 1, not 0."""
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
    """DS-181 AC4 strengthening: the original version of this test only
    asserted rc==0/not-denied for both shapes, which is vacuous against
    what it names - a hook branching on `"agent_id" in data` to skip
    state-write for the main-session shape only would still pass both of
    those weak assertions (a skipped write is not a deny). Strengthened
    to assert the state file was actually written with round_count == 1
    for BOTH shapes, so a shape-conditional write-skip is caught."""
    with tempfile.TemporaryDirectory() as tmp:
        # Main-session shape: no agent_id/agent_type keys at all.
        main_payload = _skeptic_payload(tmp, "unit-main", what_to_review="x")
        rc1, parsed1 = _run_hook(main_payload)
        assert rc1 == 0
        assert not _is_denied(parsed1)
        assert _state_path(tmp, "unit-main").exists()
        assert _read_state(tmp, "unit-main")["round_count"] == 1

    with tempfile.TemporaryDirectory() as tmp2:
        # Subagent shape: agent_id/agent_type present (should behave the same -
        # the hook does not branch on their presence).
        sub_payload = _skeptic_payload(
            tmp2, "unit-sub", what_to_review="x", extra={"agent_id": "agent-abc123", "agent_type": "skeptic"}
        )
        rc2, parsed2 = _run_hook(sub_payload)
        assert rc2 == 0
        assert not _is_denied(parsed2)
        assert _state_path(tmp2, "unit-sub").exists()
        assert _read_state(tmp2, "unit-sub")["round_count"] == 1


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
    """Round-2 review fix (Major 3): the mutation that reddens this is a
    2-part combination - (1) strip `_write_state`'s own internal
    `try/except: pass` guard, so the real `PermissionError` raised by
    `mkdir`/`os.replace` against the chmod'd read-only `.agentic/` dir
    propagates out of the function instead of being swallowed, AND (2)
    remove `main()`'s outer `except Exception: sys.exit(0)` catch-all, so
    that propagated error is not re-swallowed one level up. A
    call-site-only deny-wrapper (raising unconditionally where
    `_write_state` is invoked, without also removing part (2)) reddens
    nothing - `main()`'s outer catch-all still swallows it and the
    process still exits 0. Confirmed failing pre-fix with parts (1)+(2)
    together: rc == 1, not 0."""
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
    1-2 each carrying genuinely different Worker output must produce 2
    DISTINCT fingerprints and round_count must advance every round
    (1, 2), and a 3rd round with yet another distinct Worker output
    must DENY at the cap. Pre-fix (bounded `_WHAT_TO_REVIEW_RE`), the
    lookahead matched the first internal bold line and every round's
    captured body reduced to the same short prefix, coalescing every
    round onto round 1's cached ALLOW forever (measured: round_count
    frozen at 1 across 5 real sequential spawns, never denying)."""
    diff_line = "6. Diff under review: " + _diff_identity("feature/round-cap-test")
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
        for i in range(1, 3):
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

        # Round 3's genuinely new Worker output must be denied at the cap -
        # proves round_count actually advanced past 2 rather than
        # coalescing forever on round 1's cached ALLOW.
        worker_output = "Worker output below.\n**Summary:** round 3 final cleanup."
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
        assert _is_denied(parsed), "round 3 of a genuinely-advancing unit must be denied at the cap"


# DS-181 (M1/M2 correction): a plain `for label, prompt_text in
# cases.items(): ... assert ...` loop can only ever report the FIRST
# failing case in dict-insertion order - pytest aborts the whole test at
# the first assertion failure, so which case's name is ever reported
# depends on dict position, not on which cases are actually broken. This
# was measured to mask a second broken case (`reflowed_across_lines`)
# behind whichever case sits earlier in the dict. Rewritten as a
# parametrize so each case gets its own independent pytest node -
# ordering can never mask a second broken case again. No case was added
# or removed relative to the pre-rewrite dict (still exactly 5).
_DIFF_UNDER_REVIEW_EDGE_CASES = {
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


@pytest.mark.parametrize(
    "label,prompt_text", list(_DIFF_UNDER_REVIEW_EDGE_CASES.items())
)
def test_diff_under_review_edge_cases_failopen(label, prompt_text):
    """MAJOR 1 + MAJOR 3 combined fail-open matrix: an absent field, a
    malformed field (missing colon), a field carrying two DIFFERING
    values, an empty value followed by a blank line then other prose (the
    literal MAJOR 3 defect - the old `\\s*` crossed the newline and
    captured the Worker output as the identity), and a value reflowed
    onto the next line must all allow and write NO state at all."""
    with tempfile.TemporaryDirectory() as tmp:
        _ensure_git_marker(tmp)
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
    counter and round 3 must DENY."""
    key = "DS-177"
    shas = ["a" * 40, "b" * 40, "c" * 40, "d" * 40]
    with tempfile.TemporaryDirectory() as tmp:
        expected_path = (
            Path(tmp) / ".agentic" / f"skeptic-round-{_unit_key_for_raw_identity(key)}.json"
        )
        for i in range(1, 3):
            base, head = shas[i - 1], shas[i]
            diff_line = f"- **Diff under review:** {key} | git diff {base}..{head}"
            rc, parsed = _run_hook(
                _raw_payload(tmp, diff_line, what_to_review=f"worker output round {i}")
            )
            assert not _is_denied(parsed), f"round {i} unexpectedly denied: {parsed}"
            assert expected_path.exists()
            state = json.loads(expected_path.read_text())
            assert state["round_count"] == i

        diff_line = f"- **Diff under review:** {key} | git diff {shas[2]}..{shas[3]}"
        rc, parsed = _run_hook(
            _raw_payload(tmp, diff_line, what_to_review="worker output round 3")
        )
        assert _is_denied(parsed), "round 3 of a stable-keyed unit must deny at the cap"

        state_files = list((Path(tmp) / ".agentic").glob("skeptic-round-*.json"))
        assert len(state_files) == 1, f"expected ONE state file, got {[p.name for p in state_files]}"


def test_stable_key_two_distinct_units_no_collision():
    """DS-180: two distinct units, even sharing an identical rolling SHA
    range shape, must get INDEPENDENT round budgets."""
    with tempfile.TemporaryDirectory() as tmp:
        for key in ("DS-180", "DS-181"):
            for i in range(1, 3):
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


def test_stable_key_empty_before_pipe_is_denied():
    """A `| <diff>` value with nothing before the pipe carries no key and
    is denied, writing no round state - never a collidable placeholder key
    such as a constant "EMPTY-KEY"."""
    with tempfile.TemporaryDirectory() as tmp:
        _assert_keyless_denied(tmp, "6. Diff under review:  | git diff origin/main...feature/x")


def test_diff_command_with_pipe_is_denied():
    """A value that looks pipe-keyed but is a diff command piped through
    `head` (`git diff <sha>..<sha> | head -200`) is rejected by the shape
    gate and denied, never accepted as the key `git diff <sha>..<sha>`,
    which would change every round."""
    with tempfile.TemporaryDirectory() as tmp:
        _assert_keyless_denied(
            tmp, f"6. Diff under review: git diff {'1' * 40}..{'2' * 40} | head -200"
        )


def test_stable_key_two_units_of_one_ticket_get_independent_budgets():
    """Major 3 (round 2): a multi-unit ticket using per-unit keys
    (`<TICKET>-u<N>`, never a bare ticket id) must give each unit its
    own independent round budget."""
    with tempfile.TemporaryDirectory() as tmp:
        for key in ("DS-180-u1", "DS-180-u2"):
            for i in range(1, 3):
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
    SHA range that changes every round, accumulates on the key's counter.
    Without backtick-stripping the left side starts with a backtick, fails
    the shape gate, and the spawn is denied as keyless. Asserts the state
    FILENAME directly, not just round_count."""
    key = "DS-180"
    shas = ["a" * 40, "b" * 40, "c" * 40, "d" * 40]
    with tempfile.TemporaryDirectory() as tmp:
        expected_path = (
            Path(tmp) / ".agentic" / f"skeptic-round-{_unit_key_for_raw_identity(key)}.json"
        )
        for i in range(1, 3):
            base, head = shas[i - 1], shas[i]
            diff_line = f"- **Diff under review:** `{key} | git diff {base}..{head}`"
            rc, parsed = _run_hook(
                _raw_payload(tmp, diff_line, what_to_review=f"worker output round {i}")
            )
            assert not _is_denied(parsed), f"round {i} unexpectedly denied: {parsed}"
            assert expected_path.exists(), (
                f"round {i}: expected the backtick-stripped stable-key state file"
            )
            state = json.loads(expected_path.read_text())
            assert state["round_count"] == i

        diff_line = f"- **Diff under review:** `{key} | git diff {shas[2]}..{shas[3]}`"
        rc, parsed = _run_hook(
            _raw_payload(tmp, diff_line, what_to_review="worker output round 3")
        )
        assert _is_denied(parsed), "round 3 must deny at the cap"

        state_files = list((Path(tmp) / ".agentic").glob("skeptic-round-*.json"))
        assert len(state_files) == 1, f"expected ONE state file, got {[p.name for p in state_files]}"


def test_pipe_separated_file_paths_are_denied():
    """Field 6 on a pre-implementation review is `$UNIT_KEY | <paths>`. With
    `$UNIT_KEY` omitted, the first of two pipe-separated paths must not be
    accepted as a key: two units sharing that first path would collide on
    one counter. `_LOOKS_LIKE_FILE_PATH_RE` rejects it, so each is denied."""
    for value in (
        "hooks/enforce-skeptic-round-cap.py | bin/tests/test_enforce_skeptic_round_cap.py",
        "hooks/enforce-skeptic-round-cap.py | content/references/skeptic-protocol.md",
    ):
        with tempfile.TemporaryDirectory() as tmp:
            _assert_keyless_denied(tmp, f"- **Diff under review:** {value}")


def test_pipe_no_range_caught_only_by_shape_gate():
    """`_STABLE_KEY_SHAPE_RE` is the SOLE guard for a piped command with no
    `..` in its left side, so the `".." in left` check cannot fire. Widening
    `_STABLE_KEY_SHAPE_RE` to admit whitespace (`^[A-Za-z0-9._/# -]+$`)
    reddens this test: `git diff HEAD` would then be accepted as the key."""
    with tempfile.TemporaryDirectory() as tmp:
        _assert_keyless_denied(tmp, "6. Diff under review: git diff HEAD | head -200")


# --------------------------------------------------------------------------- #
# T1-T4. Part B: the stable unit key is mandatory
# --------------------------------------------------------------------------- #
_AUT_1245_DETAILS = [
    "origin/develop...fix/AUT-1245-light-palette-without-template-tag",
    "origin/fix/AUT-1245-light-palette-without-template-tag at 8aeb25be33a50e3fe0eefb506d4b4e0c0092ad99 vs origin/develop.",
    "origin/fix/AUT-1245-light-palette-without-template-tag at 8294fa11593479b87ee582173bb2d79f8f8bb0e1 vs origin/develop.",
    "origin/fix/AUT-1245-light-palette-without-template-tag at dd53fc46d3c89d6acc8b7ac30794ebe3012c4d88 vs origin/develop.",
]

_AUT_1178_DETAILS = [
    "n/a - plan stage, AUT-1178 plan review (no diff yet)",
    "n/a - plan stage, AUT-1178 plan review round 2 (no diff yet)",
    "origin/develop...origin/feature/AUT-1178-history-tiles (PR #2191, head 3439b09bc)",
    "origin/feature/AUT-1178-history-tiles 3439b09bc..fb38e01d9 (PR #2191 round 2)",
    "origin/feature/AUT-1178-history-tiles fb38e01d9..b371adafd (PR #2191 QA fix)",
]

# Verbatim field-6 values from real sessions that split or merged units
# under the removed diff-normalization fallback, plus the shapes that
# fallback special-cased. Every one carries no valid key.
_UNPREFIXED_FIELD6_VALUES = _AUT_1245_DETAILS + _AUT_1178_DETAILS + [
    "as given above",
    "hooks/x.py | a.md",
    "git diff a1b2c3d..e4f5a6b | head -200",
    "fix/node-20.x | git diff",
    "1232779c~1..HEAD",
    "b7a596d9^..HEAD",
]


def _fire_log_lines(tmp: str) -> list[dict]:
    log = Path(tmp) / ".agentic" / ".enforcement-fires.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def _assert_keyless_denied(tmp: str, diff_line: str) -> None:
    value = diff_line.split(":", 1)[1].lstrip("* \t")
    rc, parsed = _run_hook(_raw_payload(tmp, diff_line, what_to_review="worker output round 1"))
    assert rc == 0
    assert _is_denied(parsed), f"keyless field 6 {value!r} was not denied: {parsed}"
    reason = _deny_reason(parsed)
    for element in (
        "6. Diff under review: <KEY> | <diff command or file paths>",
        "same KEY every fix round of this unit",
        "Stable unit key contract",
        "-review",
        "no spaces",
        value.strip()[:120],
    ):
        assert element in reason, f"deny reason lacks {element!r}: {reason}"
    agentic = Path(tmp) / ".agentic"
    assert list(agentic.glob("skeptic-round-*.json")) == [], "keyless deny wrote round state"
    assert not (agentic / "skeptic-tuid-index.json").exists(), "keyless deny wrote a tuid index"
    fires = _fire_log_lines(tmp)
    assert len(fires) == 1 and fires[0].get("decision") == "deny", fires


@pytest.mark.parametrize("value", _UNPREFIXED_FIELD6_VALUES)
def test_keyless_field6_is_denied_without_state(value):
    """T1: a present, unambiguous field 6 without a valid key is denied. The
    deny names the form, the derivation and shape rules, and the value; it
    writes no round state and no tuid index, only one fire-log line."""
    with tempfile.TemporaryDirectory() as tmp:
        _assert_keyless_denied(tmp, f"6. Diff under review: {value}")


def test_keyed_detail_variants_share_one_counter():
    """T2: AUT-1245's four detail wordings behind one key share one
    counter. Rounds 1-2 are allowed; the 3rd and 4th spawns are both
    denied at the cap; exactly one state file ends at round_count 2."""
    with tempfile.TemporaryDirectory() as tmp:
        outcomes = []
        for i, detail in enumerate(_AUT_1245_DETAILS, start=1):
            rc, parsed = _run_hook(
                _raw_payload(
                    tmp,
                    f"6. Diff under review: AUT-1245 | {detail}",
                    what_to_review=f"worker output round {i}",
                )
            )
            outcomes.append("deny" if _is_denied(parsed) else "allow")
        assert outcomes == ["allow", "allow", "deny", "deny"], outcomes
        files = list((Path(tmp) / ".agentic").glob("skeptic-round-*.json"))
        assert [p.name for p in files] == [f"skeptic-round-{_unit_key_for_raw_identity('AUT-1245')}.json"]
        assert json.loads(files[0].read_text())["round_count"] == 2


def test_review_kind_suffixes_get_own_counters():
    """T3: plan, assembled-Plan, diff and meta reviews of one ticket each
    get their own counter, and the diff rounds share one counter whatever
    the detail says."""
    spawns = [
        ("AUT-1178-plan", _AUT_1178_DETAILS[0], True),
        ("AUT-1178-plan", _AUT_1178_DETAILS[1], True),
        ("AUT-1178-assembled-plan", _AUT_1178_DETAILS[1], True),
        ("AUT-1178", _AUT_1178_DETAILS[2], True),
        ("AUT-1178", _AUT_1178_DETAILS[3], True),
        ("AUT-1178", _AUT_1178_DETAILS[4], False),
        ("AUT-1178-meta", _AUT_1178_DETAILS[2], True),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for i, (key, detail, allowed) in enumerate(spawns, start=1):
            rc, parsed = _run_hook(
                _raw_payload(
                    tmp,
                    f"6. Diff under review: {key} | {detail}",
                    what_to_review=f"worker output spawn {i}",
                )
            )
            assert _is_denied(parsed) is not allowed, f"spawn {i} ({key}): {parsed}"
        counts = {
            key: json.loads(
                (Path(tmp) / ".agentic" / f"skeptic-round-{_unit_key_for_raw_identity(key)}.json").read_text()
            )["round_count"]
            for key in ("AUT-1178-plan", "AUT-1178-assembled-plan", "AUT-1178", "AUT-1178-meta")
        }
        assert counts == {
            "AUT-1178-plan": 2,
            "AUT-1178-assembled-plan": 1,
            "AUT-1178": 2,
            "AUT-1178-meta": 1,
        }, counts


def test_unit_key_literal():
    """T4: the state filename for `AUT-1245 | x` is pinned literally, so a
    change to the digest or the sanitizer cannot pass by moving the test's
    own mirror of them along with it."""
    with tempfile.TemporaryDirectory() as tmp:
        rc, parsed = _run_hook(
            _raw_payload(tmp, "6. Diff under review: AUT-1245 | x", what_to_review="r1")
        )
        assert not _is_denied(parsed)
        names = [p.name for p in (Path(tmp) / ".agentic").glob("skeptic-round-*.json")]
        assert names == ["skeptic-round-AUT-1245-decefac675.json"], names


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
    the correct unit_key AND the round number that spawn was allowed at
    (round-2 rework, M3: `{"unit_key": ..., "iteration": ...}`, pinned at
    spawn time - see `_update_tuid_index()`'s docstring for why the round-1
    bare-string shape could not answer "what round was THIS spawn" for an
    out-of-order completion). Two distinct units get correctly separated
    entries in the SAME index file, and a second round on one unit updates
    (not duplicates) that unit's entries with a NEW pinned iteration.
    Executed mutation: removing the `_update_tuid_index(path.parent,
    tool_use_id, unit_key, new_state["round_count"])` call from `main()`
    reddens this test - the index file would never be created."""
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
        assert index.get("toolu_a1") == {"unit_key": _unit_key(unit_a), "iteration": 1}, index
        assert index.get("toolu_b1") == {"unit_key": _unit_key(unit_b), "iteration": 1}, index

        # A second round on unit_a with a NEW tool_use_id adds a new entry
        # pointing at the SAME unit_key with a PINNED iteration of 2 (not
        # 1 again - each spawn's own round number, not a copy of the
        # first), without disturbing unit_b's entry.
        rc, parsed = _run_hook(
            _skeptic_payload(
                tmp, unit_a, what_to_review="unit-a round 2",
                extra={"tool_use_id": "toolu_a2"},
            )
        )
        assert not _is_denied(parsed)
        index_after = json.loads(index_path.read_text())
        assert index_after.get("toolu_a1") == {"unit_key": _unit_key(unit_a), "iteration": 1}, index_after
        assert index_after.get("toolu_a2") == {"unit_key": _unit_key(unit_a), "iteration": 2}, index_after
        assert index_after.get("toolu_b1") == {"unit_key": _unit_key(unit_b), "iteration": 1}, index_after


def test_tuid_index_concurrent_writes_not_lost():
    """M4 regression: `_update_tuid_index()`'s read-merge-write is now
    guarded by a best-effort `flock` (`_tuid_index_lock()`). 40 PARALLEL
    hook invocations for the SAME unit (mirroring a real
    `skeptic_strategy: multi-dimensional` fan-out - correctness-Skeptic +
    security-auditor + perf-analyst, each a genuinely separate SubagentStop
    with its own `tool_use_id`, all sharing this unit's round-fingerprint
    coalescing so they all ALLOW as the same round) must produce 40
    distinct index entries, not fewer.

    Round-3 fix (m4): n was previously 6, which made this guard
    INTERMITTENT rather than deterministic - re-running the pre-fix
    (unlocked) code at n=6 five times gave 4 failed / 1 passed, a ~20%
    false-green rate on a real revert. n=40 (matching the reviewer's own
    out-of-band measurement: pre-fix `lost=6/40`, post-fix `lost=0/40`,
    three consecutive runs) is at a scale where the write-write race
    reliably manifests pre-fix and reliably does not post-fix. Executed
    pre-fix at n=6: 6 parallel writers against the unlocked
    read-merge-write produced 4 entries (2 lost to a write-write race).
    Executed mutation: reverting `_update_tuid_index()` to call
    `_write_state`-style unlocked write (skip `_tuid_index_lock()`
    entirely) reproduces loss under this same test - the lock is what
    this test asserts exists and is exercised, not merely declared in a
    docstring."""
    import threading

    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/tuid-index-concurrent"
        n = 40
        results: list[tuple[int, dict | None]] = [None] * n  # type: ignore[list-item]

        def _spawn(i: int) -> None:
            results[i] = _run_hook(
                _skeptic_payload(
                    tmp, unit, what_to_review="concurrent round",
                    extra={"tool_use_id": f"toolu_concurrent_{i}"},
                ),
                timeout=30,
            )

        threads = [threading.Thread(target=_spawn, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        for i, result in enumerate(results):
            assert result is not None, f"writer {i} did not complete"
            rc, parsed = result
            assert not _is_denied(parsed), f"writer {i} unexpectedly denied: {parsed}"

        index_path = Path(tmp) / ".agentic" / "skeptic-tuid-index.json"
        assert index_path.is_file(), "expected skeptic-tuid-index.json to be created"
        index = json.loads(index_path.read_text())
        missing = [f"toolu_concurrent_{i}" for i in range(n) if f"toolu_concurrent_{i}" not in index]
        assert not missing, f"lost {len(missing)}/{n} concurrent writer entries: {missing} (full index: {index})"
        for i in range(n):
            assert index[f"toolu_concurrent_{i}"]["unit_key"] == _unit_key(unit)


def _hold_tuid_index_lock(agentic_dir: Path):
    """Take the hook's own index lock from the test process. Returns
    `(fcntl, fd)`; the caller releases with `fcntl.flock(fd, LOCK_UN)` and
    `os.close(fd)`."""
    fcntl = pytest.importorskip("fcntl")

    agentic_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(agentic_dir / "skeptic-tuid-index.json.lock"), os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fcntl, fd


def _start_hook(payload: dict, payload_dir: str) -> subprocess.Popen:
    payload_path = Path(payload_dir) / "payload.json"
    payload_path.write_text(json.dumps(payload))
    with payload_path.open() as stdin:
        return subprocess.Popen(
            [sys.executable, str(_HOOK_PATH)],
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )


def test_tuid_index_waits_for_held_lock_instead_of_writing_unlocked():
    """A writer that holds the index lock for 1s (longer than the old 0.2s
    budget, shorter than the 2s budget) and then writes a read-merge-write
    based on what it read BEFORE the hook ran must not lose the hook's
    entry: the hook waits for the lock and merges on top. Red on the old
    0.2s budget with unlocked fallback, where the hook writes unlocked
    and the holder's stale write then drops its entry."""

    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        index_path = agentic / "skeptic-tuid-index.json"
        fcntl, fd = _hold_tuid_index_lock(agentic)
        try:
            stale = {"toolu_seed": {"unit_key": "seed", "iteration": 1}}
            index_path.write_text(json.dumps(stale))
            proc = _start_hook(
                _skeptic_payload(
                    tmp, "feature/tuid-lock-wait",
                    extra={"tool_use_id": "toolu_child"},
                ),
                tmp,
            )
            time.sleep(1.0)
            stale["toolu_holder"] = {"unit_key": "holder", "iteration": 1}
            tmp_path = index_path.with_suffix(".tmp.holder")
            tmp_path.write_text(json.dumps(stale))
            os.replace(tmp_path, index_path)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        proc.communicate(timeout=30)

        index = json.loads(index_path.read_text())
        assert "toolu_holder" in index, index
        assert "toolu_seed" in index, index
        assert index.get("toolu_child") == {
            "unit_key": _unit_key("feature/tuid-lock-wait"), "iteration": 1,
        }, index


def test_tuid_index_write_skipped_when_lock_held_past_budget():
    """When the index lock stays held for the hook's whole run, the hook
    skips the index write (fail-open: no entry, index bytes unchanged)
    and still allows the spawn. Red on the old unlocked fallback, which
    rewrites the index without the lock."""

    with tempfile.TemporaryDirectory() as tmp:
        agentic = Path(tmp) / ".agentic"
        index_path = agentic / "skeptic-tuid-index.json"
        fcntl, fd = _hold_tuid_index_lock(agentic)
        try:
            index_path.write_text(json.dumps({"toolu_seed": {"unit_key": "seed", "iteration": 1}}))
            before = index_path.read_bytes()
            proc = _start_hook(
                _skeptic_payload(
                    tmp, "feature/tuid-lock-skip",
                    extra={"tool_use_id": "toolu_child"},
                ),
                tmp,
            )
            out, _ = proc.communicate(timeout=30)
            after = index_path.read_bytes()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

        parsed = json.loads(out) if out.strip() else None
        assert proc.returncode == 0
        assert not _is_denied(parsed)
        assert after == before


def test_state_file_preserves_unknown_keys_round_trip():
    """m4 regression: `_load_state`/`_write_state` now preserve a
    genuinely UNKNOWN top-level key through a load-then-write round trip
    via the `_extra` passthrough bucket, correcting the round-1 commit
    message's claim ("no longer silently drop schema fields outside a
    hardcoded 6-key dict") which was false for any key beyond
    `tool_use_ids` itself - a differential against `main` showed an
    `extra_key`/`nested` pair lost on BOTH `main` and the round-1 branch.
    Executed mutation: removing the `_extra` unpack loop in
    `_write_state()` (or the `extra = {k: v for k, v in raw.items() if k
    not in _KNOWN_STATE_KEYS}` line in `_load_state()`) reddens this test -
    `extra_key`/`nested` would vanish from the state file after one more
    round."""
    with tempfile.TemporaryDirectory() as tmp:
        unit = "feature/unknown-key-preservation"
        _ensure_git_marker(tmp)
        state_path = Path(tmp) / ".agentic" / f"skeptic-round-{_unit_key(unit)}.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "round_count": 1,
            "decision": None,
            "unresolved_critical": False,
            "last_round_fingerprint": None,
            "last_decision_allow": True,
            "last_decision_reason": "",
            "tool_use_ids": [],
            "extra_key": "some forensic value a human hand-added",
            "nested": {"a": 1, "b": [2, 3]},
        }, indent=2))

        rc, parsed = _run_hook(
            _skeptic_payload(tmp, unit, what_to_review="round after hand-edit")
        )
        assert not _is_denied(parsed)

        state_after = json.loads(state_path.read_text())
        assert state_after.get("extra_key") == "some forensic value a human hand-added", state_after
        assert state_after.get("nested") == {"a": 1, "b": [2, 3]}, state_after
        # The active schema still advanced normally alongside the
        # preserved unknown keys.
        assert state_after.get("round_count") == 2, state_after


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
