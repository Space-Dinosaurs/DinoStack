"""
Purpose: Executes the Phase 8 commit-and-telemetry shell block
         (content/commands/ds-implement-ticket.md, marked
         `@harness:phase8-commit-and-telemetry`) against real temp-git
         fixtures under both bash and zsh, so the class of defect that two
         review rounds each missed fails mechanically instead of surviving a
         third: D1 (a hoisted SESSION_LOG_SRC assignment silently drops the
         telemetry commit), D2 (an existence guard placed before the mkdir/cp
         that creates the file no-ops the whole block), and D3 (a missing
         DCO-identity guard on the telemetry commit would emit a malformed
         `Signed-off-by:  <>` trailer - fixed; the guard now skips the
         telemetry commit instead of emitting the malformed trailer).

Public API: none (pytest test module; 10 functions x {bash, zsh} = 20 tests).

Upstream deps: bin/tests/lib/md_shell_extract.py, bin/tests/lib/git_fixture.py,
               content/commands/ds-implement-ticket.md (file under test).

Downstream consumers: .github/workflows/bin-tests.yml (python-bin-tests job),
               which additionally floors the collected-test count at >= 20 -
               see the comment on that step for why.

Failure modes: n/a (test module). Tests #7 and #8 are themselves a self-check
               of the harness: if a mutant fails to be caught, the harness
               regressed to not detecting the defect class it exists for.
               Test #9 now guards the D3 fix: it asserts the telemetry commit
               is skipped (not the malformed trailer) when git user.name/
               user.email are unset - see its docstring.

Performance: standard; each parametrized test does a handful of local git
             operations plus one subprocess shell invocation. Whole suite
             runs in low single-digit seconds.

Known scope limitation: the feature-commit `git add [specific files]` line
             (rendered to `.agentic/session-log/${DEVELOPER}.jsonl` via
             md_shell_extract.PLACEHOLDER_WHITELIST) runs before $DEVELOPER
             is assigned later in the block, so it is a guaranteed pathspec
             mismatch under every fixture here and no test exercises the
             feature-commit path - only the telemetry-commit path (which
             resolves $DEVELOPER first) is covered. See
             bin/tests/lib/md_shell_extract.py's manifest for detail.
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


@pytest.mark.parametrize("shell", SHELLS)
def test_correct_block_aborts_loudly_on_defeated_negation(tmp_path, shell):
    """Point-of-use defeated-negation check (round 12). The consumer shape
    has a WORKING `!.agentic/session-log/` negation and would otherwise
    commit telemetry (see test_correct_block_commits_telemetry_on_consumer_
    shape) - here a PATH-shadowed stub `ds-migrate` reports the exact
    developer's session-log path as a DEFEATED negation, and the block must
    print a visible ERROR and skip the commit, instead of silently no-oping
    the way a bare `git add` on an ignored path would."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    defeated_path = f".agentic/session-log/{fixture.developer}.jsonl"
    git_fixture.install_ds_migrate_stub(tmp_path, fixture.env, defeated_path)
    rendered = mse.render(_raw_block())
    result = _execute(rendered, fixture, shell)
    assert mse.COMPLETION_MARKER in result.stdout, result.stderr
    assert "ERROR" in result.stdout, f"expected a visible ERROR line:\n{result.stdout}"
    assert "DEFEATED NEGATION" in result.stdout
    assert defeated_path in result.stdout
    body = _telemetry_commit_body(_pr_checkout(fixture), fixture.branch_name, fixture.env)
    assert body is None, "expected no chore(telemetry): commit when the negation is defeated"


# ---------------------------------------------------------------------------
# 7-8. Mutation tests: D1 and D2 must be caught by this harness.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_defect1_hoisted_cp_silently_drops_telemetry_commit(tmp_path, shell):
    """Both-directions check (M3): the unmutated block MUST produce a
    telemetry commit on this exact fixture shape before we assert the mutant
    suppresses it - otherwise a broken fixture (e.g. a wrong session-log
    filename that makes a commit impossible under any block) would make this
    test pass vacuously regardless of whether the mutant is actually caught."""
    shell = _shell_or_skip(shell)

    unmutated_dir = tmp_path / "unmutated"
    unmutated_dir.mkdir()
    unmutated_fixture = git_fixture.build_worktree_shape(unmutated_dir)
    unmutated_rendered = mse.render(_raw_block())
    unmutated_result = _execute(unmutated_rendered, unmutated_fixture, shell)
    assert mse.COMPLETION_MARKER in unmutated_result.stdout, unmutated_result.stderr
    unmutated_body = _telemetry_commit_body(
        _pr_checkout(unmutated_fixture), unmutated_fixture.branch_name, unmutated_fixture.env
    )
    assert unmutated_body is not None, (
        "harness self-check failed: the UNMUTATED block produced no "
        "telemetry commit on this fixture shape - the fixture (not the "
        "defect) is broken, so a mutant assertion of body is None below "
        "would be vacuous"
    )

    mutant_dir = tmp_path / "mutant"
    mutant_dir.mkdir()
    fixture = git_fixture.build_worktree_shape(mutant_dir)
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
    """Both-directions check (M3): see test_defect1's docstring - the
    unmutated block must be shown to produce a telemetry commit on this
    fixture shape before the mutant's suppression of it is meaningful."""
    shell = _shell_or_skip(shell)

    unmutated_dir = tmp_path / "unmutated"
    unmutated_dir.mkdir()
    unmutated_fixture = git_fixture.build_worktree_shape(unmutated_dir)
    unmutated_rendered = mse.render(_raw_block())
    unmutated_result = _execute(unmutated_rendered, unmutated_fixture, shell)
    assert mse.COMPLETION_MARKER in unmutated_result.stdout, unmutated_result.stderr
    unmutated_body = _telemetry_commit_body(
        _pr_checkout(unmutated_fixture), unmutated_fixture.branch_name, unmutated_fixture.env
    )
    assert unmutated_body is not None, (
        "harness self-check failed: the UNMUTATED block produced no "
        "telemetry commit on this fixture shape - the fixture (not the "
        "defect) is broken, so a mutant assertion of body is None below "
        "would be vacuous"
    )

    mutant_dir = tmp_path / "mutant"
    mutant_dir.mkdir()
    fixture = git_fixture.build_worktree_shape(mutant_dir)
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
# 9. D3 regression test - guards the DCO-identity guard fix.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_dco_guard_skips_telemetry_commit_when_gitconfig_missing(tmp_path, shell):
    """Guards the fix for D3: the telemetry-commit block now mirrors the
    feature commit's DCO-identity guard - if `git config user.name` /
    `user.email` are both unset, the telemetry commit is skipped (with a
    visible WARNING and the staged file unstaged) rather than emitting the
    malformed `Signed-off-by:  <>` trailer (two spaces, empty angle
    brackets).

    Fixture (vi) (build_identity_no_gitconfig_shape) has a confirmed
    developer identity but no `git config user.*` anywhere - `git commit`
    would still succeed via GIT_AUTHOR_*/GIT_COMMITTER_* env vars, but
    $SO_NAME/$SO_EMAIL (built exclusively from `git config user.name`/
    `user.email`) resolve empty, so this fixture exercises the guard's skip
    path.

    Prior to the fix, this test (then named
    test_defect3_missing_dco_guard_emits_malformed_trailer) was a
    CHARACTERIZATION test asserting the malformed trailer WAS present - see
    git history for that version if the pre-fix behavior needs to be
    reproduced.
    """
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_identity_no_gitconfig_shape(tmp_path)
    rendered = mse.render(_raw_block())
    result = _execute(rendered, fixture, shell)
    assert mse.COMPLETION_MARKER in result.stdout, (
        "expected the block to run to completion (a genuine skip is "
        f"required, not a crash): {result.stderr}"
    )
    body = _telemetry_commit_body(_pr_checkout(fixture), fixture.branch_name, fixture.env)
    assert body is None, (
        f"expected NO chore(telemetry): commit when git user.name/user.email "
        f"are unset (DCO-identity guard should skip it), got: {body!r}"
    )
    assert (
        "WARNING: git user.name or user.email not set; skipping telemetry "
        "commit to avoid malformed DCO trailer." in result.stdout
    ), f"expected the DCO-identity-guard WARNING in stdout, got: {result.stdout!r}"
