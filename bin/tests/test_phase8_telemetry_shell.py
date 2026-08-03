"""
Purpose: Executes the Phase 8 commit-and-telemetry shell block
         (content/commands/ds-implement-ticket.md:2249-2346, marked
         `@harness:phase8-commit-and-telemetry`) against real temp-git
         fixtures under both bash and zsh, so the class of defect that two
         review rounds each missed fails mechanically instead of surviving a
         third: D1 (a hoisted SESSION_LOG_SRC assignment silently drops the
         telemetry commit), D2 (an existence guard placed before the mkdir/cp
         that creates the file no-ops the whole block), and D3 (a missing
         DCO-identity guard on the telemetry commit emits a malformed
         `Signed-off-by:  <>` trailer - live and unfixed on main today).

Public API: none (pytest test module; 9 functions x {bash, zsh} = 18 tests).

Upstream deps: bin/tests/lib/md_shell_extract.py, bin/tests/lib/git_fixture.py,
               content/commands/ds-implement-ticket.md (file under test).

Downstream consumers: .github/workflows/bin-tests.yml (python-bin-tests job),
               which additionally floors the collected-test count at >= 18 -
               see the comment on that step for why.

Failure modes: n/a (test module). Tests #7 and #8 are themselves a self-check
               of the harness: if a mutant fails to be caught, the harness
               regressed to not detecting the defect class it exists for.
               Test #9 is a deliberate characterization test that PASSES
               against current unfixed main - see its docstring.

Performance: standard; each parametrized test does a handful of local git
             operations plus one subprocess shell invocation. Whole suite
             runs in low single-digit seconds.
"""
from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib.git_fixture as git_fixture  # noqa: E402
import lib.md_shell_extract as mse  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MD_PATH = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"
MARKER = "phase8-commit-and-telemetry"

SHELLS = ["bash", "zsh"]

SESSION_LOG_SRC_ANCHOR = 'SESSION_LOG_SRC="$REPO/.agentic/session-log/${DEVELOPER}.jsonl"'
CP_LINE_ANCHOR = (
    'cp "$SESSION_LOG_SRC" "$PR_CHECKOUT/.agentic/session-log/${DEVELOPER}.jsonl" '
    "2>/dev/null || true"
)
MKDIR_LINE_ANCHOR = 'mkdir -p "$PR_CHECKOUT/.agentic/session-log/"'


def _shell_or_skip(shell: str) -> str:
    """Skip locally when a shell is missing; hard-fail in CI so the zsh half
    of the matrix can never be silently dropped (see MEMORY.md's
    'green often means the check did not run' lesson)."""
    if shutil.which(shell) is None:
        if os.environ.get("CI"):
            pytest.fail(f"{shell} not found in CI - the python-bin-tests job must install it")
        pytest.skip(f"{shell} not found on this machine")
    return shell


@functools.lru_cache(maxsize=1)
def _raw_block() -> str:
    return mse.extract_marked_block(str(MD_PATH), MARKER)


def _pr_checkout(fixture: git_fixture.Fixture) -> Path:
    return fixture.worktree_dir if fixture.worktree_dir is not None else fixture.repo_dir


def _make_d1_mutant(block_text: str) -> str:
    """D1: hoist SESSION_LOG_SRC's assignment to immediately AFTER the `cp`
    line that reads it, so `cp ""` runs against an as-yet-unset variable."""
    src_line = mse.line_containing(block_text, SESSION_LOG_SRC_ANCHOR)
    cp_line = mse.line_containing(block_text, CP_LINE_ANCHOR)

    def transform(text: str) -> str:
        without_src = text.replace(src_line + "\n", "", 1)
        return without_src.replace(cp_line, cp_line + "\n" + src_line, 1)

    return mse.apply_transform(block_text, SESSION_LOG_SRC_ANCHOR, transform)


def _make_d2_mutant(block_text: str) -> str:
    """D2: wrap the mkdir+cp pair in a guard checking for the very file they
    create, so on a fixture where the destination is absent, the guard is
    always false and the pair never runs."""
    mkdir_line = mse.line_containing(block_text, MKDIR_LINE_ANCHOR)
    cp_line = mse.line_containing(block_text, CP_LINE_ANCHOR)
    indent = mkdir_line[: len(mkdir_line) - len(mkdir_line.lstrip())]
    pair = mkdir_line + "\n" + cp_line

    def transform(text: str) -> str:
        guarded = (
            f'{indent}if [ -f "$PR_CHECKOUT/.agentic/session-log/${{DEVELOPER}}.jsonl" ]; then\n'
            f"{mkdir_line}\n{cp_line}\n"
            f"{indent}fi"
        )
        return text.replace(pair, guarded, 1)

    return mse.apply_transform(block_text, MKDIR_LINE_ANCHOR, transform)


def _execute(
    rendered_block: str, fixture: git_fixture.Fixture, shell: str
) -> subprocess.CompletedProcess:
    script = mse.with_completion_marker(rendered_block)
    return subprocess.run(
        [shell, "-c", script],
        cwd=str(fixture.repo_dir),
        env=fixture.env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _commit_subjects(path: Path, branch: str, env: dict) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(path), "log", branch, "--format=%s"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


def _telemetry_commit_body(path: Path, branch: str, env: dict) -> str | None:
    """Full commit message body of the first `chore(telemetry):` commit on
    `branch`, or None if no such commit exists."""
    subjects = _commit_subjects(path, branch, env)
    for i, subject in enumerate(subjects):
        if subject.startswith("chore(telemetry):"):
            result = subprocess.run(
                ["git", "-C", str(path), "log", branch, "-1", f"--skip={i}", "--format=%B"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout
    return None


# ---------------------------------------------------------------------------
# 1. Static harness self-check.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_extraction_is_non_vacuous(shell):
    shell = _shell_or_skip(shell)
    block = _raw_block()
    lines = block.splitlines()
    assert len(lines) > 40, f"expected >40 lines, got {len(lines)}"
    for anchor in ("SESSION_LOG_SRC", "Signed-off-by", "PR_CHECKOUT"):
        assert anchor in block, f"expected literal anchor {anchor!r} in extracted block"

    rendered = mse.render(block)
    for key in mse.PLACEHOLDER_WHITELIST:
        assert key not in rendered, f"placeholder {key!r} survived render()"

    d1 = mse.render(_make_d1_mutant(block))
    d1_check = mse.syntax_check(d1, shell)
    assert d1_check.returncode == 0, f"D1 mutant failed to parse under {shell}: {d1_check.stderr}"

    d2 = mse.render(_make_d2_mutant(block))
    d2_check = mse.syntax_check(d2, shell)
    assert d2_check.returncode == 0, f"D2 mutant failed to parse under {shell}: {d2_check.stderr}"


# ---------------------------------------------------------------------------
# 2-4. Correct-block positive paths.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_correct_block_commits_telemetry_on_consumer_shape(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    rendered = mse.render(_raw_block())
    check = mse.syntax_check(rendered, shell)
    assert check.returncode == 0, check.stderr
    result = _execute(rendered, fixture, shell)
    assert mse.COMPLETION_MARKER in result.stdout, result.stderr
    body = _telemetry_commit_body(_pr_checkout(fixture), fixture.branch_name, fixture.env)
    assert body is not None, "expected a chore(telemetry): commit"
    assert f"Signed-off-by: {git_fixture.DUMMY_NAME} <{git_fixture.DUMMY_EMAIL}>" in body


@pytest.mark.parametrize("shell", SHELLS)
def test_correct_block_commits_telemetry_on_worktree_shape(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_worktree_shape(tmp_path)
    rendered = mse.render(_raw_block())
    check = mse.syntax_check(rendered, shell)
    assert check.returncode == 0, check.stderr
    result = _execute(rendered, fixture, shell)
    assert mse.COMPLETION_MARKER in result.stdout, result.stderr
    body = _telemetry_commit_body(_pr_checkout(fixture), fixture.branch_name, fixture.env)
    assert body is not None, "expected a chore(telemetry): commit"
    assert f"Signed-off-by: {git_fixture.DUMMY_NAME} <{git_fixture.DUMMY_EMAIL}>" in body


@pytest.mark.parametrize("shell", SHELLS)
def test_correct_block_commits_telemetry_on_fanout_shape(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_fanout_shape(tmp_path)
    rendered = mse.render(_raw_block())
    check = mse.syntax_check(rendered, shell)
    assert check.returncode == 0, check.stderr
    result = _execute(rendered, fixture, shell)
    assert mse.COMPLETION_MARKER in result.stdout, result.stderr
    body = _telemetry_commit_body(_pr_checkout(fixture), fixture.branch_name, fixture.env)
    assert body is not None, "expected a chore(telemetry): commit"
    assert f"Signed-off-by: {git_fixture.DUMMY_NAME} <{git_fixture.DUMMY_EMAIL}>" in body


# ---------------------------------------------------------------------------
# 5-6. Correct-block negative paths (genuine, non-crash no-ops).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_correct_block_noops_on_dinostack_shape(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_dinostack_shape(tmp_path)
    rendered = mse.render(_raw_block())
    result = _execute(rendered, fixture, shell)
    assert mse.COMPLETION_MARKER in result.stdout, (
        f"block did not run to completion (a genuine no-op is required, not "
        f"a crash): {result.stderr}"
    )
    assert "The following paths are ignored by one of your .gitignore files" in result.stderr
    body = _telemetry_commit_body(_pr_checkout(fixture), fixture.branch_name, fixture.env)
    assert body is None, "expected no chore(telemetry): commit on the dinostack shape"


@pytest.mark.parametrize("shell", SHELLS)
def test_correct_block_skips_telemetry_when_identity_unconfirmed(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_no_identity_shape(tmp_path)
    rendered = mse.render(_raw_block())
    result = _execute(rendered, fixture, shell)
    assert mse.COMPLETION_MARKER in result.stdout, result.stderr
    body = _telemetry_commit_body(_pr_checkout(fixture), fixture.branch_name, fixture.env)
    assert body is None, "expected no chore(telemetry): commit when identity is unconfirmed"


# ---------------------------------------------------------------------------
# 7-8. Mutation tests: D1 and D2 must be caught by this harness.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_defect1_hoisted_cp_silently_drops_telemetry_commit(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_worktree_shape(tmp_path)
    mutant = mse.render(_make_d1_mutant(_raw_block()))
    check = mse.syntax_check(mutant, shell)
    assert check.returncode == 0, f"D1 mutant must parse (same-scope reorder): {check.stderr}"
    result = _execute(mutant, fixture, shell)
    assert mse.COMPLETION_MARKER in result.stdout, result.stderr
    body = _telemetry_commit_body(_pr_checkout(fixture), fixture.branch_name, fixture.env)
    assert body is None, (
        "D1 (hoisted SESSION_LOG_SRC assignment) should silently drop the "
        "telemetry commit - if this fails, the harness is not catching the "
        "defect class it exists to catch"
    )


@pytest.mark.parametrize("shell", SHELLS)
def test_defect2_guard_before_cp_noops_on_single_engineer_path(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_worktree_shape(tmp_path)
    mutant_raw = _make_d2_mutant(_raw_block())
    mutant = mse.render(mutant_raw)
    check = mse.syntax_check(mutant, shell)
    assert check.returncode == 0, (
        f"D2 mutant must parse under {shell} - there is no accepted "
        f"'unparseable' branch for this mutation: {check.stderr}"
    )
    result = _execute(mutant, fixture, shell)
    assert mse.COMPLETION_MARKER in result.stdout, result.stderr
    body = _telemetry_commit_body(_pr_checkout(fixture), fixture.branch_name, fixture.env)
    assert body is None, (
        "D2 (existence guard inserted before the mkdir/cp that creates the "
        "file) should no-op the whole block on a fixture where the "
        "destination is absent"
    )


# ---------------------------------------------------------------------------
# 9. D3 characterization test - documents a LIVE, unfixed defect on main.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_defect3_missing_dco_guard_emits_malformed_trailer(tmp_path, shell):
    """CHARACTERIZATION TEST - passes against current main because it
    documents a live, unfixed defect. Do NOT mark this xfail(strict=True):
    a prior revision did, and it was inverted (the assertions below hold
    today, so the test passes, and strict xfail turns a pass into
    XPASS(strict) -> suite red on merge).

    Defect location: content/commands/ds-implement-ticket.md:2274-2325 - the
    telemetry-commit block builds TELEM_MSG (:2316) from $SO_NAME/$SO_EMAIL
    with NO guard analogous to the one at :2264 that protects the FEATURE
    commit. When git config user.name/user.email are unset (but the commit
    itself still succeeds via GIT_AUTHOR_*/GIT_COMMITTER_* env vars, as a CI
    runner or a fresh clone with no `git config --global user.*` might have),
    the telemetry commit lands with the literal malformed trailer
    `Signed-off-by:  <>` (two spaces, empty angle brackets).

    The follow-up ticket that adds the :2283-2325 guard MUST invert this
    test (assert the malformed trailer no longer occurs) in the SAME PR
    that fixes the defect.
    """
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_identity_no_gitconfig_shape(tmp_path)
    rendered = mse.render(_raw_block())
    result = _execute(rendered, fixture, shell)
    assert mse.COMPLETION_MARKER in result.stdout, result.stderr
    body = _telemetry_commit_body(_pr_checkout(fixture), fixture.branch_name, fixture.env)
    assert body is not None, "expected a chore(telemetry): commit even with no git user.* config"
    assert "Signed-off-by:  <>" in body, (
        f"expected the LIVE malformed trailer 'Signed-off-by:  <>' (D3, "
        f"unfixed on main) in the telemetry commit body, got: {body!r}"
    )
