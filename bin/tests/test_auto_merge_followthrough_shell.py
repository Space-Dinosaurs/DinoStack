"""
Purpose: Executes the shell blocks the auto-merge follow-through feature added
         to content/commands/ds-implement-ticket.md
         (`@harness:phase10-timeout-auto-merge-queue`,
         `@harness:phase10-resume-auto-merge-check`) and to
         content/references/conventions-detail.md
         (`@harness:sibling-pr-sweep`) against a stubbed `gh`/`jq`, instead of
         only ever reading them as prose. Every test is written from the shape
         of a DEFECT the block must not have: queuing a merge when the toggle
         is off, claiming "merged" when `--auto` only queued, re-queuing an
         already-queued or already-merged PR on resume, and the sibling-PR
         sweep making any `gh` call at all when the toggle is off or reaching
         beyond the agent's own PRs.

Public API: none (pytest test module).

Upstream deps: bin/tests/lib/md_shell_extract.py (extraction + non-exported
               shell assignment injection + completion marker),
               content/commands/ds-implement-ticket.md and
               content/references/conventions-detail.md (the blocks under
               test).

Downstream consumers: .github/workflows/bin-tests.yml (auto-discovered by the
               generic `pytest bin/tests/ -q` step; no per-file floor is
               registered for this module).

Failure modes: n/a (test module). Every `gh` invocation is logged to a file
               via a stub script placed first on PATH; assertions read that
               log rather than trusting the block's own stdout claims.

Performance: standard; each test forks one or two subprocesses against a tiny
             stub `gh`/`jq` pair, no real git repo involved.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib.md_shell_extract as mse  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CMD_MD = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"
CONV_MD = REPO_ROOT / "content" / "references" / "conventions-detail.md"

MARKER_TIMEOUT_QUEUE = "phase10-timeout-auto-merge-queue"
MARKER_RESUME_CHECK = "phase10-resume-auto-merge-check"
MARKER_SIBLING_SWEEP = "sibling-pr-sweep"

BLOCK_TIMEOUT_SECONDS = 30

# Same stub shape as test_phase11e_knowledge_commit_shell.py's _GH_STUB: every
# argv is logged (unit-separator joined) so assertions can inspect exact call
# shape, and behavior is env-var-controlled per test.
_GH_STUB = r"""#!/bin/sh
AE_GH_LOG='__LOG__'
line=""
for a in "$@"; do line="$line$a$(printf '\037')"; done
printf '%s\n' "$line" >> "$AE_GH_LOG"

case "$1 $2" in
  "pr merge")
    exit "${AE_GH_MERGE_EXIT:-0}" ;;
  "pr view")
    case "$*" in
      *"--json state"*)
        printf '%s\n' "${AE_GH_PR_STATE:-OPEN}"
        exit 0 ;;
    esac
    exit 1 ;;
  "pr list")
    [ "$AE_GH_FAIL_LIST" = "1" ] && exit 1
    printf '%s\n' "${AE_GH_PR_LIST_JSON:-[]}"
    exit 0 ;;
  "pr update-branch")
    exit "${AE_GH_REBASE_EXIT:-0}" ;;
esac
exit 1
"""

_JQ_STUB = r"""#!/bin/sh
exec python3 -c '
import sys, json
flt = sys.argv[1]
default = None
if "//" in flt:
    flt, default = flt.split("//", 1)
    flt, default = flt.strip(), default.strip().strip("\"")
try:
    data = json.load(sys.stdin)
except Exception:
    print(default if default is not None else "null"); raise SystemExit(0)
value = data.get(flt.lstrip("."))
if value is None:
    value = default if default is not None else "null"
if isinstance(value, bool):
    value = "true" if value else "false"
print(value)
' "$2"
"""

# A separate jq stub for the sibling-pr-sweep block, which pipes an ARRAY
# through a jq filter (select + map to .number), not a single-object field
# lookup - the phase11e-style _JQ_STUB above only handles `.field` lookups.
_JQ_ARRAY_STUB = r"""#!/bin/sh
exec python3 -c '
import sys, json
data = json.load(sys.stdin)
behind = sorted(
    item["number"] for item in data
    if item.get("mergeStateStatus") == "BEHIND" and item.get("isDraft") is False
)
for n in behind:
    print(n)
'
"""


def _block(marker: str, md_path: Path) -> str:
    return mse.extract_marked_block(str(md_path), marker)


def _gh_stub_env(tmp_path: Path, jq_body: str, **overrides: str) -> tuple[dict, Path]:
    bin_dir = tmp_path / "gh-stub-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log_path = bin_dir / "gh-argv.log"
    log_path.write_text("", encoding="utf-8")
    for name, body in (("gh", _GH_STUB.replace("__LOG__", str(log_path))), ("jq", jq_body)):
        stub = bin_dir / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env.update(overrides)
    return env, log_path


def _gh_argv(log_path: Path) -> list[list[str]]:
    raw = log_path.read_text(encoding="utf-8")
    return [
        [f for f in line.split("\x1f") if f != ""] for line in raw.splitlines() if line.strip()
    ]


def _run(tmp_path: Path, script: str, env: dict) -> subprocess.CompletedProcess:
    full = mse.with_completion_marker(script)
    return subprocess.run(
        ["bash", "-c", full],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=BLOCK_TIMEOUT_SECONDS,
        stdin=subprocess.DEVNULL,
    )


def _assert_completed(result: subprocess.CompletedProcess) -> None:
    assert mse.COMPLETION_MARKER in result.stdout, (
        f"block did not run to completion.\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# (a) timeout + false: zero gh calls, AUTO_MERGE_QUEUED stays false.
# ---------------------------------------------------------------------------


def test_timeout_toggle_false_makes_no_gh_call_and_leaves_queued_false(tmp_path):
    """Mutation this catches: dropping the `if [ "$AUTO_MERGE_ON_CI_GREEN" =
    "true" ]` guard (or inverting it) would call `gh pr merge` even with the
    toggle off - this is the single most dangerous possible defect for a
    feature whose entire safety story is "false means fully inert"."""
    env, log_path = _gh_stub_env(tmp_path, _JQ_STUB)
    script = mse.with_shell_assignments(
        _block(MARKER_TIMEOUT_QUEUE, CMD_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "false", "PR_NUMBER": "42", "GH_REPO": "acme/widget"},
    )
    script += '\necho "RESULT_AUTO_MERGE_QUEUED=$AUTO_MERGE_QUEUED"\n'
    result = _run(tmp_path, script, env)
    _assert_completed(result)

    assert _gh_argv(log_path) == [], "toggle=false must make zero gh calls"
    assert "RESULT_AUTO_MERGE_QUEUED=false" in result.stdout, result.stdout


# ---------------------------------------------------------------------------
# (b) timeout + true + gh succeeds: --auto called exactly once, queued=true.
# ---------------------------------------------------------------------------


def test_timeout_toggle_true_and_merge_succeeds_queues_exactly_once(tmp_path):
    """Mutation this catches: calling `gh pr merge` a second time, or omitting
    `--auto` (which would attempt an immediate merge against a PR whose CI is
    still pending, contradicting the whole point of the timeout branch)."""
    env, log_path = _gh_stub_env(tmp_path, _JQ_STUB, AE_GH_MERGE_EXIT="0")
    script = mse.with_shell_assignments(
        _block(MARKER_TIMEOUT_QUEUE, CMD_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "PR_NUMBER": "42", "GH_REPO": "acme/widget"},
    )
    script += '\necho "RESULT_AUTO_MERGE_QUEUED=$AUTO_MERGE_QUEUED"\n'
    result = _run(tmp_path, script, env)
    _assert_completed(result)

    merges = [c for c in _gh_argv(log_path) if c[:2] == ["pr", "merge"]]
    assert len(merges) == 1, merges
    assert "--auto" in merges[0], merges
    assert "RESULT_AUTO_MERGE_QUEUED=true" in result.stdout, result.stdout
    assert "auto-merge-queued: true" in result.stdout, result.stdout
    assert "auto-merged" not in result.stdout, (
        f"--auto exiting 0 means QUEUED, never MERGED - the block must not "
        f"claim 'auto-merged': {result.stdout}"
    )


# ---------------------------------------------------------------------------
# (c) timeout + true + gh FAILS: falls through to unchanged human-review
#     message, no queued state, no merge-promise text.
# ---------------------------------------------------------------------------


def test_timeout_toggle_true_and_merge_fails_falls_through_cleanly(tmp_path):
    """Mutation this catches: reporting `auto-merge-queued: true` (or leaving
    AUTO_MERGE_QUEUED set to true) on the failure branch, which would falsely
    persuade the resume-check (test below) to skip re-polling a PR that was
    never actually queued."""
    env, log_path = _gh_stub_env(tmp_path, _JQ_STUB, AE_GH_MERGE_EXIT="1")
    script = mse.with_shell_assignments(
        _block(MARKER_TIMEOUT_QUEUE, CMD_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "PR_NUMBER": "42", "GH_REPO": "acme/widget"},
    )
    script += '\necho "RESULT_AUTO_MERGE_QUEUED=$AUTO_MERGE_QUEUED"\n'
    result = _run(tmp_path, script, env)
    _assert_completed(result)

    merges = [c for c in _gh_argv(log_path) if c[:2] == ["pr", "merge"]]
    assert len(merges) == 1, merges
    assert "RESULT_AUTO_MERGE_QUEUED=false" in result.stdout, result.stdout
    assert "auto-merge-queued: true" not in result.stdout, result.stdout
    assert "auto-merge-queue-failed" in result.stdout, result.stdout


# ---------------------------------------------------------------------------
# (d) resume with auto_merge_queued=true and PR already MERGED skips to
#     Phase 10b with no second merge call.
# ---------------------------------------------------------------------------


def test_resume_when_already_merged_skips_without_a_second_merge_call(tmp_path):
    """Mutation this catches: calling `gh pr merge` again on resume instead of
    only `gh pr view` - a second merge attempt against an already-merged PR is
    at best a wasted call and at worst a confusing error surfaced to the
    human for no reason."""
    env, log_path = _gh_stub_env(tmp_path, _JQ_STUB, AE_GH_PR_STATE="MERGED")
    script = mse.with_shell_assignments(
        _block(MARKER_RESUME_CHECK, CMD_MD),
        {"AUTO_MERGE_QUEUED": "true", "PR_NUMBER": "42", "GH_REPO": "acme/widget"},
    )
    result = _run(tmp_path, script, env)
    _assert_completed(result)

    argv = _gh_argv(log_path)
    assert [c for c in argv if c[:2] == ["pr", "merge"]] == [], (
        f"no gh pr merge call is permitted on the resume-check path: {argv}"
    )
    views = [c for c in argv if c[:2] == ["pr", "view"]]
    assert len(views) == 1, argv
    assert "action: skip-to-phase-10b" in result.stdout, result.stdout


def test_resume_when_still_open_reenters_poll_without_requeuing(tmp_path):
    """Companion negative control for (d): confirms the MERGED-state assertion
    above is a genuine branch, not a vacuous pass - the still-OPEN case must
    reach the opposite action string and still make no merge call."""
    env, log_path = _gh_stub_env(tmp_path, _JQ_STUB, AE_GH_PR_STATE="OPEN")
    script = mse.with_shell_assignments(
        _block(MARKER_RESUME_CHECK, CMD_MD),
        {"AUTO_MERGE_QUEUED": "true", "PR_NUMBER": "42", "GH_REPO": "acme/widget"},
    )
    result = _run(tmp_path, script, env)
    _assert_completed(result)

    argv = _gh_argv(log_path)
    assert [c for c in argv if c[:2] == ["pr", "merge"]] == [], argv
    assert "action: re-enter-poll-no-requeue" in result.stdout, result.stdout


def test_resume_when_not_queued_takes_the_absent_branch(tmp_path):
    """Mutation this catches: collapsing the three-way branch (queued+merged,
    queued+open, not-queued) into two, which would silently misroute a resume
    on a loop-state file written before auto_merge_queued existed (absent
    field, back-compat case)."""
    env, log_path = _gh_stub_env(tmp_path, _JQ_STUB)
    script = mse.with_shell_assignments(
        _block(MARKER_RESUME_CHECK, CMD_MD),
        {"AUTO_MERGE_QUEUED": "false", "PR_NUMBER": "42", "GH_REPO": "acme/widget"},
    )
    result = _run(tmp_path, script, env)
    _assert_completed(result)

    assert _gh_argv(log_path) == [], "not-queued path must not call gh at all"
    assert "action: re-enter-poll]" in result.stdout, result.stdout


# ---------------------------------------------------------------------------
# (e) sibling-PR sweep makes zero gh calls when the toggle is false.
# ---------------------------------------------------------------------------


def test_sibling_sweep_toggle_false_makes_zero_gh_calls(tmp_path):
    """Mutation this catches: any restructuring that hoists the `gh pr list`
    call above (or outside) the `auto_merge_on_ci_green` guard - the sweep's
    entire safety story for an ad-hoc, non-/ds-implement-ticket session is
    that the toggle being false makes it a complete no-op."""
    env, log_path = _gh_stub_env(tmp_path, _JQ_ARRAY_STUB)
    script = mse.with_shell_assignments(
        _block(MARKER_SIBLING_SWEEP, CONV_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "false", "GH_REPO": "acme/widget", "BASE_BRANCH": "main"},
    )
    result = _run(tmp_path, script, env)
    _assert_completed(result)

    assert _gh_argv(log_path) == [], "toggle=false must make zero gh calls"


def test_sibling_sweep_toggle_true_rebases_and_queues_behind_prs_in_order(tmp_path):
    """Positive control for the assertion above, and confirms FIFO ordering
    plus the --author "@me" ownership scope. Mutation this catches: dropping
    the --author "@me" flag from the gh pr list call (which would sweep PRs
    the agent does not own), or losing the ascending-order guarantee."""
    pr_list_json = (
        '[{"number":12,"mergeStateStatus":"BEHIND","isDraft":false},'
        '{"number":7,"mergeStateStatus":"BEHIND","isDraft":false},'
        '{"number":9,"mergeStateStatus":"CLEAN","isDraft":false},'
        '{"number":3,"mergeStateStatus":"BEHIND","isDraft":true}]'
    )
    env, log_path = _gh_stub_env(
        tmp_path, _JQ_ARRAY_STUB, AE_GH_PR_LIST_JSON=pr_list_json
    )
    script = mse.with_shell_assignments(
        _block(MARKER_SIBLING_SWEEP, CONV_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "GH_REPO": "acme/widget", "BASE_BRANCH": "main"},
    )
    result = _run(tmp_path, script, env)
    _assert_completed(result)

    argv = _gh_argv(log_path)
    lists = [c for c in argv if c[:2] == ["pr", "list"]]
    assert len(lists) == 1, argv
    assert "@me" in lists[0], (
        f"the sibling-PR sweep must scope to PRs the agent owns: {lists[0]}"
    )

    rebases = [c for c in argv if c[:2] == ["pr", "update-branch"]]
    merges = [c for c in argv if c[:2] == ["pr", "merge"]]
    # Only 7 and 12 are BEHIND and non-draft; 9 is CLEAN, 3 is a draft.
    assert [c[2] for c in rebases] == ["7", "12"], argv
    assert [c[2] for c in merges] == ["7", "12"], argv
    assert all("--auto" in c for c in merges), merges
    assert "pr=7" in result.stdout and "pr=12" in result.stdout, result.stdout
    assert "pr=3" not in result.stdout and "pr=9" not in result.stdout, result.stdout


# ---------------------------------------------------------------------------
# Ad-hoc reachability: none of these three blocks are conditioned on a
# /ds-implement-ticket invocation, a loop-state file, or a LOOP_KEY existing.
# ---------------------------------------------------------------------------


def test_timeout_queue_block_has_no_dependency_on_loop_state_or_loop_key(tmp_path):
    """Mutation this catches: introducing a read of `.agentic/loop-state-
    $LOOP_KEY.json` (or any file under `.agentic/`) into the queue decision
    itself - the whole point of the scope correction is that this block must
    fire correctly for an ad-hoc session that never created a loop-state file
    at all. Run with no .agentic/ directory present and LOOP_KEY unset;
    the block must still queue on the toggle alone."""
    assert not (tmp_path / ".agentic").exists()
    env, log_path = _gh_stub_env(tmp_path, _JQ_STUB, AE_GH_MERGE_EXIT="0")
    env.pop("LOOP_KEY", None)
    script = mse.with_shell_assignments(
        _block(MARKER_TIMEOUT_QUEUE, CMD_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "PR_NUMBER": "99", "GH_REPO": "acme/widget"},
    )
    result = _run(tmp_path, script, env)
    _assert_completed(result)

    assert not (tmp_path / ".agentic").exists(), (
        "the queue decision must not have created or required .agentic/"
    )
    merges = [c for c in _gh_argv(log_path) if c[:2] == ["pr", "merge"]]
    assert len(merges) == 1 and "--auto" in merges[0], merges


def test_sibling_sweep_block_has_no_dependency_on_loop_state_or_loop_key(tmp_path):
    """Same reachability property as above, for the sibling-PR sweep: it must
    run correctly at session start before any ticket loop has ever started in
    this session, with no .agentic/ directory and no LOOP_KEY."""
    assert not (tmp_path / ".agentic").exists()
    env, log_path = _gh_stub_env(
        tmp_path,
        _JQ_ARRAY_STUB,
        AE_GH_PR_LIST_JSON='[{"number":5,"mergeStateStatus":"BEHIND","isDraft":false}]',
    )
    env.pop("LOOP_KEY", None)
    script = mse.with_shell_assignments(
        _block(MARKER_SIBLING_SWEEP, CONV_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "GH_REPO": "acme/widget", "BASE_BRANCH": "main"},
    )
    result = _run(tmp_path, script, env)
    _assert_completed(result)

    assert not (tmp_path / ".agentic").exists()
    merges = [c for c in _gh_argv(log_path) if c[:2] == ["pr", "merge"]]
    assert [c[2] for c in merges] == ["5"], merges
