"""
Purpose: Executes the shell blocks the auto-merge follow-through feature added
         to content/commands/ds-implement-ticket.md
         (`@harness:phase10-timeout-auto-merge-queue`,
         `@harness:phase10-resume-auto-merge-check`) and to
         content/references/conventions-detail.md
         (`@harness:sibling-pr-sweep`) against a stubbed `gh` and the REAL
         system `jq`, instead of only ever reading them as prose or against a
         jq stub that reimplements the filter in Python (round-1 Skeptic Major
         2 - a stub filter tests the stub, not the doc). Every test is written
         from the shape of a DEFECT the block must not have: queuing a merge
         when the toggle is off, attempting `--auto` against a still-draft PR
         (round-1 Critical), claiming "merged" when `--auto` only queued,
         re-queuing an already-queued or already-merged PR on resume, the
         sibling-PR sweep making any `gh` call at all when the toggle is off,
         newly queuing a PR nobody opted in (round-1 Major 3 - blast radius),
         silently dropping a PR whose mergeability GitHub has not finished
         computing, and zsh word-splitting collapsing a multi-line PR list
         into one malformed argument (round-1 Major 1) - every block below is
         parametrized over both bash and zsh, matching the x2-shells floor
         sibling extracted-block suites already carry in bin-tests.yml.

Public API: none (pytest test module).

Upstream deps: bin/tests/lib/md_shell_extract.py (extraction + non-exported
               shell assignment injection + completion marker), the real `jq`
               binary on PATH (NOT stubbed - see the Major-2 note above),
               content/commands/ds-implement-ticket.md and
               content/references/conventions-detail.md (the blocks under
               test).

Downstream consumers: .github/workflows/bin-tests.yml (auto-discovered by the
               generic `pytest bin/tests/ -q` step; no per-file floor is
               registered for this module).

Failure modes: n/a (test module). Every `gh` invocation is logged to a file
               via a stub script placed first on PATH; assertions read that
               log rather than trusting the block's own stdout claims. `jq`
               is never stubbed - a mutation to the block's actual filter
               text is what reddens the sibling-sweep filter tests, not a
               change to test fixture code.

Performance: standard; each test forks one or two subprocesses against a tiny
             stub `gh` plus the real `jq`, no real git repo involved.
"""
from __future__ import annotations

import os
import shutil
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

SHELLS = ["bash", "zsh"]
BLOCK_TIMEOUT_SECONDS = 30


def _shell_or_skip(shell: str) -> str:
    """Skip locally when a shell is missing; hard-fail in CI so the zsh half
    of the matrix can never be silently dropped (same guard as
    test_phase11e_knowledge_commit_shell.py / test_knowledge_harness_smoke.py)."""
    if shutil.which(shell) is None:
        if os.environ.get("CI"):
            pytest.fail(f"{shell} not found in CI - the python-bin-tests job must install it")
        pytest.skip(f"{shell} not found on this machine")
    return shell


# Same stub shape as test_phase11e_knowledge_commit_shell.py's _GH_STUB: every
# argv is logged (unit-separator joined) so assertions can inspect exact call
# shape, and behavior is env-var-controlled per test. Deliberately covers only
# `gh` - `jq` is NEVER stubbed in this module (round-1 Skeptic Major 2).
_GH_STUB = r"""#!/bin/sh
AE_GH_LOG='__LOG__'
line=""
for a in "$@"; do line="$line$a$(printf '\037')"; done
printf '%s\n' "$line" >> "$AE_GH_LOG"

case "$1 $2" in
  "pr ready")
    exit "${AE_GH_READY_EXIT:-0}" ;;
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


def _block(marker: str, md_path: Path) -> str:
    return mse.extract_marked_block(str(md_path), marker)


def _gh_stub_env(tmp_path: Path, **overrides: str) -> tuple[dict, Path]:
    """Prepend a bin dir containing ONLY a stubbed `gh` - real `jq` on PATH
    is left to resolve normally, so any `jq -r '<filter>'` inside the block
    under test executes for real against real JSON."""
    bin_dir = tmp_path / "gh-stub-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log_path = bin_dir / "gh-argv.log"
    log_path.write_text("", encoding="utf-8")
    stub = bin_dir / "gh"
    stub.write_text(_GH_STUB.replace("__LOG__", str(log_path)), encoding="utf-8")
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


def _run(tmp_path: Path, shell: str, script: str, env: dict) -> subprocess.CompletedProcess:
    full = mse.with_completion_marker(script)
    return subprocess.run(
        [shell, "-c", full],
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


def _require_jq() -> None:
    if shutil.which("jq") is None:
        pytest.skip("jq not found on this machine - required to exercise the real filter")


# ---------------------------------------------------------------------------
# (a) timeout + false: zero gh calls, AUTO_MERGE_QUEUED stays false.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_timeout_toggle_false_makes_no_gh_call_and_leaves_queued_false(tmp_path, shell):
    """Mutation this catches: dropping the `if [ "$AUTO_MERGE_ON_CI_GREEN" =
    "true" ]` guard (or inverting it) would call `gh pr ready`/`gh pr merge`
    even with the toggle off - this is the single most dangerous possible
    defect for a feature whose entire safety story is "false means fully
    inert". Scope note: this asserts byte-for-byte output of the MARKED BASH
    BLOCK only (the `AUTO_MERGE_QUEUED` computation and its own two `echo`
    phase lines, which now include the differentiated human-review/queued
    line per round-1 Minor 5) - it does not claim the surrounding prose in
    ds-implement-ticket.md is unchanged, since the concrete human-review
    wording was newly made explicit by this ticket where it was previously
    undescribed prose ("Surface to human and STOP")."""
    shell = _shell_or_skip(shell)
    env, log_path = _gh_stub_env(tmp_path)
    script = mse.with_shell_assignments(
        _block(MARKER_TIMEOUT_QUEUE, CMD_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "false", "PR_NUMBER": "42", "GH_REPO": "acme/widget",
         "TIMEOUT_POLLS": "60"},
    )
    script += '\necho "RESULT_AUTO_MERGE_QUEUED=$AUTO_MERGE_QUEUED"\n'
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    assert _gh_argv(log_path) == [], "toggle=false must make zero gh calls"
    assert "RESULT_AUTO_MERGE_QUEUED=false" in result.stdout, result.stdout
    assert "Open for human review" in result.stdout, result.stdout


# ---------------------------------------------------------------------------
# (b) timeout + true + gh succeeds: un-draft THEN --auto, exactly once each,
#     queued=true, message names the queue.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_timeout_toggle_true_and_merge_succeeds_undrafts_then_queues(tmp_path, shell):
    """Mutation this catches (round-1 Critical): dropping the `gh pr ready`
    call before `gh pr merge --auto`. The PR is still a draft on the timeout
    path (Phase 10b's un-draft is conditional on Phase 10 result: passed,
    which never fires here) and GitHub refuses `--auto` on a draft at the
    GraphQL mutation layer - this repo already measured that refusal
    (.agentic/memory/gh-pr-merge-draft-refusal.md). Also catches: calling
    `gh pr merge` a second time, omitting `--auto`, or reporting the
    human-review line without naming the queue."""
    shell = _shell_or_skip(shell)
    env, log_path = _gh_stub_env(tmp_path, AE_GH_MERGE_EXIT="0", AE_GH_READY_EXIT="0")
    script = mse.with_shell_assignments(
        _block(MARKER_TIMEOUT_QUEUE, CMD_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "PR_NUMBER": "42", "GH_REPO": "acme/widget",
         "TIMEOUT_POLLS": "60"},
    )
    script += '\necho "RESULT_AUTO_MERGE_QUEUED=$AUTO_MERGE_QUEUED"\n'
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    argv = _gh_argv(log_path)
    readies = [c for c in argv if c[:2] == ["pr", "ready"]]
    merges = [c for c in argv if c[:2] == ["pr", "merge"]]
    assert len(readies) == 1, argv
    assert len(merges) == 1, merges
    assert "--auto" in merges[0], merges
    ready_idx = argv.index(readies[0])
    merge_idx = argv.index(merges[0])
    assert ready_idx < merge_idx, (
        f"gh pr ready must run BEFORE gh pr merge --auto, not after: {argv}"
    )
    assert "RESULT_AUTO_MERGE_QUEUED=true" in result.stdout, result.stdout
    assert "auto-merge-queued: true" in result.stdout, result.stdout
    assert "auto-merged" not in result.stdout, (
        f"--auto exiting 0 means QUEUED, never MERGED - the block must not "
        f"claim 'auto-merged': {result.stdout}"
    )
    assert "Queued for auto-merge" in result.stdout, (
        f"the human-facing line must name the queue when queued: {result.stdout}"
    )


# ---------------------------------------------------------------------------
# (c) timeout + true + gh FAILS: still attempts un-draft, falls through to
#     unchanged human-review message, no queued state.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_timeout_toggle_true_and_merge_fails_falls_through_cleanly(tmp_path, shell):
    """Mutation this catches: reporting `auto-merge-queued: true` (or leaving
    AUTO_MERGE_QUEUED set to true) on the failure branch, which would falsely
    persuade the resume-check (tests below) to skip re-polling a PR that was
    never actually queued, and would wrongly print the QUEUED-worded line."""
    shell = _shell_or_skip(shell)
    env, log_path = _gh_stub_env(tmp_path, AE_GH_MERGE_EXIT="1", AE_GH_READY_EXIT="0")
    script = mse.with_shell_assignments(
        _block(MARKER_TIMEOUT_QUEUE, CMD_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "PR_NUMBER": "42", "GH_REPO": "acme/widget",
         "TIMEOUT_POLLS": "60"},
    )
    script += '\necho "RESULT_AUTO_MERGE_QUEUED=$AUTO_MERGE_QUEUED"\n'
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    argv = _gh_argv(log_path)
    assert len([c for c in argv if c[:2] == ["pr", "ready"]]) == 1, argv
    merges = [c for c in argv if c[:2] == ["pr", "merge"]]
    assert len(merges) == 1, merges
    assert "RESULT_AUTO_MERGE_QUEUED=false" in result.stdout, result.stdout
    assert "auto-merge-queued: true" not in result.stdout, result.stdout
    assert "auto-merge-queue-failed" in result.stdout, result.stdout
    assert "Open for human review" in result.stdout, result.stdout
    assert "Queued for auto-merge" not in result.stdout, result.stdout


# ---------------------------------------------------------------------------
# (d) resume with auto_merge_queued=true and PR already MERGED skips to
#     Phase 10b with no second merge call.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_resume_when_already_merged_skips_without_a_second_merge_call(tmp_path, shell):
    """Mutation this catches: calling `gh pr merge` again on resume instead of
    only `gh pr view` - a second merge attempt against an already-merged PR is
    at best a wasted call and at worst a confusing error surfaced to the
    human for no reason."""
    shell = _shell_or_skip(shell)
    env, log_path = _gh_stub_env(tmp_path, AE_GH_PR_STATE="MERGED")
    script = mse.with_shell_assignments(
        _block(MARKER_RESUME_CHECK, CMD_MD),
        {"AUTO_MERGE_QUEUED": "true", "PR_NUMBER": "42", "GH_REPO": "acme/widget"},
    )
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    argv = _gh_argv(log_path)
    assert [c for c in argv if c[:2] == ["pr", "merge"]] == [], (
        f"no gh pr merge call is permitted on the resume-check path: {argv}"
    )
    views = [c for c in argv if c[:2] == ["pr", "view"]]
    assert len(views) == 1, argv
    assert "action: skip-to-phase-10b" in result.stdout, result.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_resume_when_still_open_reenters_poll_without_requeuing(tmp_path, shell):
    """Companion negative control for (d): confirms the MERGED-state assertion
    above is a genuine branch, not a vacuous pass - the still-OPEN case must
    reach the opposite action string and still make no merge call."""
    shell = _shell_or_skip(shell)
    env, log_path = _gh_stub_env(tmp_path, AE_GH_PR_STATE="OPEN")
    script = mse.with_shell_assignments(
        _block(MARKER_RESUME_CHECK, CMD_MD),
        {"AUTO_MERGE_QUEUED": "true", "PR_NUMBER": "42", "GH_REPO": "acme/widget"},
    )
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    argv = _gh_argv(log_path)
    assert [c for c in argv if c[:2] == ["pr", "merge"]] == [], argv
    assert "action: re-enter-poll-no-requeue" in result.stdout, result.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_resume_when_not_queued_takes_the_absent_branch(tmp_path, shell):
    """Mutation this catches: collapsing the three-way branch (queued+merged,
    queued+open, not-queued) into two, which would silently misroute a resume
    on a loop-state file written before auto_merge_queued existed (absent
    field, back-compat case)."""
    shell = _shell_or_skip(shell)
    env, log_path = _gh_stub_env(tmp_path)
    script = mse.with_shell_assignments(
        _block(MARKER_RESUME_CHECK, CMD_MD),
        {"AUTO_MERGE_QUEUED": "false", "PR_NUMBER": "42", "GH_REPO": "acme/widget"},
    )
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    assert _gh_argv(log_path) == [], "not-queued path must not call gh at all"
    assert "action: re-enter-poll]" in result.stdout, result.stdout


# ---------------------------------------------------------------------------
# (e) sibling-PR sweep makes zero gh calls when the toggle is false.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_sibling_sweep_toggle_false_makes_zero_gh_calls(tmp_path, shell):
    """Mutation this catches: any restructuring that hoists the `gh pr list`
    call above (or outside) the `auto_merge_on_ci_green` guard - the sweep's
    entire safety story for an ad-hoc, non-/ds-implement-ticket session is
    that the toggle being false makes it a complete no-op."""
    shell = _shell_or_skip(shell)
    env, log_path = _gh_stub_env(tmp_path)
    script = mse.with_shell_assignments(
        _block(MARKER_SIBLING_SWEEP, CONV_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "false", "GH_REPO": "acme/widget", "BASE_BRANCH": "main"},
    )
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    assert _gh_argv(log_path) == [], "toggle=false must make zero gh calls"


# ---------------------------------------------------------------------------
# Round-1 Major 3: blast radius. A PR that is BEHIND but was never queued
# (autoMergeRequest null) must be untouched, regardless of ownership/BEHIND
# status. This is the exact live scenario the Skeptic reproduced against
# PR #838 on Space-Dinosaurs/DinoStack.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_sibling_sweep_never_newly_queues_an_unqueued_behind_pr(tmp_path, shell):
    """Mutation this catches: dropping `.autoMergeRequest != null` from the
    STUCK_NUMBERS filter (the exact round-1 defect) - re-widens the sweep to
    rebase (and, before this fix, re-queue) ANY BEHIND PR the agent owns,
    unrelated parked work included. Uses the REAL system jq against real
    fixture JSON, not a Python reimplementation (round-1 Major 2) - inverting
    the filter in the doc to drop the autoMergeRequest clause was manually
    confirmed to redden this exact assertion."""
    shell = _shell_or_skip(shell)
    _require_jq()
    pr_list_json = (
        '[{"number":838,"mergeStateStatus":"BEHIND","isDraft":false,"autoMergeRequest":null}]'
    )
    env, log_path = _gh_stub_env(tmp_path, AE_GH_PR_LIST_JSON=pr_list_json)
    script = mse.with_shell_assignments(
        _block(MARKER_SIBLING_SWEEP, CONV_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "GH_REPO": "acme/widget", "BASE_BRANCH": "main"},
    )
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    argv = _gh_argv(log_path)
    assert [c for c in argv if c[:2] == ["pr", "update-branch"]] == [], (
        f"a BEHIND PR with no existing auto-merge queue must never be "
        f"rebased or touched: {argv}"
    )
    assert [c for c in argv if c[:2] == ["pr", "merge"]] == [], argv
    assert "pr=838" not in result.stdout, result.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_sibling_sweep_unsticks_only_an_already_queued_behind_pr(tmp_path, shell):
    """Positive control for the assertion above, and confirms the sweep
    NEVER re-invokes `gh pr merge` (it only rebases to unstick an existing
    queue). Mutation this catches: re-adding a `gh pr merge --auto` call
    after the rebase, which would be a redundant re-queue at best."""
    shell = _shell_or_skip(shell)
    _require_jq()
    pr_list_json = (
        '[{"number":7,"mergeStateStatus":"BEHIND","isDraft":false,'
        '"autoMergeRequest":{"enabledAt":"2026-01-01T00:00:00Z"}}]'
    )
    env, log_path = _gh_stub_env(tmp_path, AE_GH_PR_LIST_JSON=pr_list_json)
    script = mse.with_shell_assignments(
        _block(MARKER_SIBLING_SWEEP, CONV_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "GH_REPO": "acme/widget", "BASE_BRANCH": "main"},
    )
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    argv = _gh_argv(log_path)
    rebases = [c for c in argv if c[:2] == ["pr", "update-branch"]]
    assert [c[2] for c in rebases] == ["7"], argv
    assert [c for c in argv if c[:2] == ["pr", "merge"]] == [], (
        f"the sweep must never call gh pr merge - it only unsticks an "
        f"existing queue: {argv}"
    )
    assert "pr=7" in result.stdout and "rebased-unstuck-queue" in result.stdout, result.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_sibling_sweep_excludes_clean_and_draft_even_when_queued(tmp_path, shell):
    """Real-jq filter correctness (round-1 Major 2): a CLEAN PR with
    autoMergeRequest set needs no unsticking (nothing is stuck), and a draft
    PR is excluded defensively even though GitHub's own draft-vs-auto-merge
    invariant makes that combination not occur in practice."""
    shell = _shell_or_skip(shell)
    _require_jq()
    pr_list_json = (
        '[{"number":9,"mergeStateStatus":"CLEAN","isDraft":false,'
        '"autoMergeRequest":{"x":1}},'
        '{"number":3,"mergeStateStatus":"BEHIND","isDraft":true,'
        '"autoMergeRequest":{"x":1}}]'
    )
    env, log_path = _gh_stub_env(tmp_path, AE_GH_PR_LIST_JSON=pr_list_json)
    script = mse.with_shell_assignments(
        _block(MARKER_SIBLING_SWEEP, CONV_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "GH_REPO": "acme/widget", "BASE_BRANCH": "main"},
    )
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    assert [c for c in _gh_argv(log_path) if c[:2] == ["pr", "update-branch"]] == []
    assert "pr=9" not in result.stdout and "pr=3" not in result.stdout, result.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_sibling_sweep_logs_unknown_mergeability_instead_of_silent_drop(tmp_path, shell):
    """Round-1 Minor: a PR whose mergeStateStatus is UNKNOWN (GitHub computes
    mergeability lazily) must be logged, not silently skipped with no trace.
    Mutation this catches: removing the UNKNOWN_NUMBERS branch entirely."""
    shell = _shell_or_skip(shell)
    _require_jq()
    pr_list_json = '[{"number":21,"mergeStateStatus":"UNKNOWN","isDraft":false,"autoMergeRequest":null}]'
    env, log_path = _gh_stub_env(tmp_path, AE_GH_PR_LIST_JSON=pr_list_json)
    script = mse.with_shell_assignments(
        _block(MARKER_SIBLING_SWEEP, CONV_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "GH_REPO": "acme/widget", "BASE_BRANCH": "main"},
    )
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    argv = _gh_argv(log_path)
    mutations = [c for c in argv if c[:2] in (["pr", "update-branch"], ["pr", "merge"])]
    assert mutations == [], f"an UNKNOWN-only PR must trigger no gh mutation calls: {argv}"
    assert "pr=21" in result.stdout and "skipped-unknown-mergeability" in result.stdout, (
        result.stdout
    )


@pytest.mark.parametrize("shell", SHELLS)
def test_sibling_sweep_uses_limit_100_and_scopes_to_own_prs(tmp_path, shell):
    """Round-1 Minor: `--limit` must be present (default gh page size silently
    truncates at 30). Mutation this catches: removing `--limit 100` or
    `--author "@me"` from the `gh pr list` call."""
    shell = _shell_or_skip(shell)
    _require_jq()
    env, log_path = _gh_stub_env(tmp_path, AE_GH_PR_LIST_JSON="[]")
    script = mse.with_shell_assignments(
        _block(MARKER_SIBLING_SWEEP, CONV_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "GH_REPO": "acme/widget", "BASE_BRANCH": "main"},
    )
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    lists = [c for c in _gh_argv(log_path) if c[:2] == ["pr", "list"]]
    assert len(lists) == 1, lists
    assert "@me" in lists[0], lists[0]
    assert "100" in lists[0], lists[0]


# ---------------------------------------------------------------------------
# Round-1 Major 1: zsh word-splitting. A multi-line PR-number result must
# process EVERY number under zsh, not just the first (zsh does not
# word-split an unquoted `for N in $VAR` the way bash does).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_sibling_sweep_processes_every_pr_in_a_multiline_result_under_both_shells(tmp_path, shell):
    """Mutation this catches: reverting `while IFS= read -r N; do ... done
    <<< "$VAR"` back to `for N in $VAR`. Under bash that mutant still passes
    (bash word-splits unquoted expansion on IFS, including newlines); under
    zsh it silently collapses the whole multi-line result into a single
    malformed argument and rebases at most one (malformed) "PR number" -
    confirmed by manually reverting to the `for` form and re-running this
    exact test under zsh, which reddened with only a garbled single gh call
    instead of three clean ones."""
    shell = _shell_or_skip(shell)
    _require_jq()
    pr_list_json = (
        '[{"number":1,"mergeStateStatus":"BEHIND","isDraft":false,'
        '"autoMergeRequest":{"x":1}},'
        '{"number":2,"mergeStateStatus":"BEHIND","isDraft":false,'
        '"autoMergeRequest":{"x":1}},'
        '{"number":3,"mergeStateStatus":"BEHIND","isDraft":false,'
        '"autoMergeRequest":{"x":1}}]'
    )
    env, log_path = _gh_stub_env(tmp_path, AE_GH_PR_LIST_JSON=pr_list_json)
    script = mse.with_shell_assignments(
        _block(MARKER_SIBLING_SWEEP, CONV_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "GH_REPO": "acme/widget", "BASE_BRANCH": "main"},
    )
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    rebases = [c for c in _gh_argv(log_path) if c[:2] == ["pr", "update-branch"]]
    assert [c[2] for c in rebases] == ["1", "2", "3"], (
        f"all three BEHIND-and-queued PRs must be rebased individually and "
        f"in ascending order under {shell}: {rebases}"
    )


@pytest.mark.parametrize("shell", SHELLS)
def test_sibling_sweep_soft_fails_per_pr_without_blocking_the_rest(tmp_path, shell):
    """Soft-fail contract: one PR's rebase failing must not stop the sweep
    from processing the next PR. Mutation this catches: an `&&`-chained loop
    body (or a bare `set -e`-sensitive construct) that aborts the whole loop
    on the first non-zero exit."""
    shell = _shell_or_skip(shell)
    _require_jq()
    pr_list_json = (
        '[{"number":1,"mergeStateStatus":"BEHIND","isDraft":false,'
        '"autoMergeRequest":{"x":1}},'
        '{"number":2,"mergeStateStatus":"BEHIND","isDraft":false,'
        '"autoMergeRequest":{"x":1}}]'
    )
    env, log_path = _gh_stub_env(
        tmp_path, AE_GH_PR_LIST_JSON=pr_list_json, AE_GH_REBASE_EXIT="1"
    )
    script = mse.with_shell_assignments(
        _block(MARKER_SIBLING_SWEEP, CONV_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "GH_REPO": "acme/widget", "BASE_BRANCH": "main"},
    )
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    rebases = [c for c in _gh_argv(log_path) if c[:2] == ["pr", "update-branch"]]
    assert [c[2] for c in rebases] == ["1", "2"], (
        f"both PRs must be attempted even though the first rebase fails: {rebases}"
    )
    assert result.stdout.count("rebase-failed") == 2, result.stdout


# ---------------------------------------------------------------------------
# Ad-hoc reachability: none of these three blocks are conditioned on a
# /ds-implement-ticket invocation, a loop-state file, or a LOOP_KEY existing.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_timeout_queue_block_has_no_dependency_on_loop_state_or_loop_key(tmp_path, shell):
    """Mutation this catches: introducing a read of `.agentic/loop-state-
    $LOOP_KEY.json` (or any file under `.agentic/`) into the queue decision
    itself - the whole point of the scope correction is that this block must
    fire correctly for an ad-hoc session that never created a loop-state file
    at all. Run with no .agentic/ directory present and LOOP_KEY unset;
    the block must still un-draft and queue on the toggle alone."""
    shell = _shell_or_skip(shell)
    assert not (tmp_path / ".agentic").exists()
    env, log_path = _gh_stub_env(tmp_path, AE_GH_MERGE_EXIT="0", AE_GH_READY_EXIT="0")
    env.pop("LOOP_KEY", None)
    script = mse.with_shell_assignments(
        _block(MARKER_TIMEOUT_QUEUE, CMD_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "PR_NUMBER": "99", "GH_REPO": "acme/widget",
         "TIMEOUT_POLLS": "60"},
    )
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    assert not (tmp_path / ".agentic").exists(), (
        "the queue decision must not have created or required .agentic/"
    )
    argv = _gh_argv(log_path)
    assert len([c for c in argv if c[:2] == ["pr", "ready"]]) == 1, argv
    merges = [c for c in argv if c[:2] == ["pr", "merge"]]
    assert len(merges) == 1 and "--auto" in merges[0], merges


@pytest.mark.parametrize("shell", SHELLS)
def test_sibling_sweep_block_has_no_dependency_on_loop_state_or_loop_key(tmp_path, shell):
    """Same reachability property as above, for the sibling-PR sweep: it must
    run correctly at session start before any ticket loop has ever started in
    this session, with no .agentic/ directory and no LOOP_KEY."""
    shell = _shell_or_skip(shell)
    _require_jq()
    assert not (tmp_path / ".agentic").exists()
    pr_list_json = (
        '[{"number":5,"mergeStateStatus":"BEHIND","isDraft":false,'
        '"autoMergeRequest":{"x":1}}]'
    )
    env, log_path = _gh_stub_env(tmp_path, AE_GH_PR_LIST_JSON=pr_list_json)
    env.pop("LOOP_KEY", None)
    script = mse.with_shell_assignments(
        _block(MARKER_SIBLING_SWEEP, CONV_MD),
        {"AUTO_MERGE_ON_CI_GREEN": "true", "GH_REPO": "acme/widget", "BASE_BRANCH": "main"},
    )
    result = _run(tmp_path, shell, script, env)
    _assert_completed(result)

    assert not (tmp_path / ".agentic").exists()
    rebases = [c for c in _gh_argv(log_path) if c[:2] == ["pr", "update-branch"]]
    assert [c[2] for c in rebases] == ["5"], rebases
