"""
Purpose: Executes the two shell blocks Phase 11e added to
         content/commands/ds-implement-ticket.md - the knowledge-commit block
         (`@harness:phase11e-knowledge-commit`) and the amended Phase 12
         auto-merge block (`@harness:phase12-auto-merge`) - against real git
         fixtures under both bash and zsh, instead of only ever reading them as
         prose. Every test is written from the shape of a DEFECT the block must
         not have (zsh word-splitting, staging against the real index, a
         suppressed gitignore diagnostic, a malformed DCO trailer, an empty
         commit per invocation, a missing index refresh, a revert guard that
         fails open, `files_committed` populated on a failure path), and each
         was confirmed to go RED under a mutation of the implementation.

Public API: none (pytest test module; 23 parametrized functions x {bash, zsh}
            = 46 collected IDs, plus 3 static shell-independent assertions =
            49 - see the collected-count floor in
            .github/workflows/bin-tests.yml).

Upstream deps: bin/tests/lib/md_shell_extract.py (extraction + non-exported
               shell assignment injection + completion marker),
               bin/tests/lib/git_fixture.py (the four build_knowledge_*
               shapes, install_git_stub, install_push_reject_hook),
               content/commands/ds-implement-ticket.md (the blocks under test).

               md_shell_extract.render() is deliberately NOT used and MUST NOT
               be: PLACEHOLDER_WHITELIST is global and fail-closed pre-render,
               so it raises on any block that does not carry all three Phase 8
               placeholders - which these blocks do not. test_static_*
               below pins that fact mechanically.

Downstream consumers: .github/workflows/bin-tests.yml (python-bin-tests job).

Failure modes: n/a (test module). Commit counts are read from the BARE ORIGIN's
               branch ref, never from the block's own stdout - the block pushes
               a commit-tree SHA straight to refs/heads/<branch> and never moves
               local HEAD, so local HEAD is not evidence either way. Absence
               assertions are always paired with a positive control (a
               "Signed-off-by is not malformed" assertion is worthless without
               first proving a well-formed one is produced on the happy path).

Performance: standard; each test builds one or two temp git repos with a bare
             origin and runs one or two subprocess shell invocations.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib.git_fixture as git_fixture  # noqa: E402
import lib.md_shell_extract as mse  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MD_PATH = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"
MARKER = "phase11e-knowledge-commit"
MARKER_PHASE12 = "phase12-auto-merge"

SHELLS = ["bash", "zsh"]

MEMORY = "MEMORY.md"
DECISIONS = "decisions.md"
LEARNINGS = ".agentic/learnings.md"

STATE_FILE = ".agentic/knowledge-commit-state.json"

# Bounded and stdin-closed for the same reason as every subprocess in
# bin/tests/lib/git_fixture.py: an unbounded stall becomes a killed CI job with
# no log, and pytest's fd-0 capture disappears under `-s`.
BLOCK_TIMEOUT_SECONDS = 60
GIT_TIMEOUT_SECONDS = 30


def _shell_or_skip(shell: str) -> str:
    """Skip locally when a shell is missing; hard-fail in CI so the zsh half of
    the matrix can never be silently dropped (same guard as
    test_knowledge_harness_smoke.py)."""
    if shutil.which(shell) is None:
        if os.environ.get("CI"):
            pytest.fail(f"{shell} not found in CI - the python-bin-tests job must install it")
        pytest.skip(f"{shell} not found on this machine")
    return shell


# ---------------------------------------------------------------------------
# Extraction. NEVER mse.render() - see the module manifest.
# ---------------------------------------------------------------------------


def _block(marker: str = MARKER) -> str:
    return mse.extract_marked_block(str(MD_PATH), marker)


def _script(fixture: git_fixture.Fixture, block: str | None = None) -> str:
    """The extraction contract for every test in this module: extract, do our
    OWN single-token $REPO substitution, inject BRANCH_NAME as a NON-exported
    shell assignment (production shape - see with_shell_assignments), then
    append the completion marker."""
    assert "BRANCH_NAME" not in fixture.env, (
        "BRANCH_NAME must be absent from the fixture env - it is injected as a "
        "non-exported shell assignment so the block reproduces production"
    )
    script = _block() if block is None else block
    script = script.replace("$REPO", str(fixture.repo_dir))
    script = mse.with_shell_assignments(script, {"BRANCH_NAME": fixture.branch_name})
    return mse.with_completion_marker(script)


def _run(fixture: git_fixture.Fixture, shell: str, block: str | None = None):
    return subprocess.run(
        [shell, "-c", _script(fixture, block)],
        cwd=str(fixture.repo_dir),
        env=fixture.env,
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


def _git(fixture: git_fixture.Fixture, *args: str, cwd: Path | None = None):
    return subprocess.run(
        ["git", "-C", str(cwd or fixture.repo_dir), *args],
        env=fixture.env,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        stdin=subprocess.DEVNULL,
    )


def _origin_count(fixture: git_fixture.Fixture) -> int:
    """Commits on the BARE ORIGIN's branch ref. The block pushes a commit-tree
    SHA directly to refs/heads/<branch> and never moves local HEAD, so the
    origin ref is the only place a produced commit is observable."""
    if fixture.origin_dir is None:
        return 0
    result = _git(fixture, "rev-list", "--count", fixture.branch_name, cwd=fixture.origin_dir)
    assert result.returncode == 0, result.stderr
    return int(result.stdout.strip())


def _origin_tip_files(fixture: git_fixture.Fixture) -> list[str]:
    result = _git(
        fixture, "log", "-1", "--name-only", "--format=", fixture.branch_name,
        cwd=fixture.origin_dir,
    )
    assert result.returncode == 0, result.stderr
    return sorted(ln for ln in result.stdout.splitlines() if ln.strip())


def _origin_tip_body(fixture: git_fixture.Fixture) -> str:
    result = _git(
        fixture, "log", "-1", "--format=%B", fixture.branch_name, cwd=fixture.origin_dir
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _write_config(fixture: git_fixture.Fixture, payload: dict) -> None:
    config = fixture.repo_dir / ".agentic" / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(payload), encoding="utf-8")


def _install_emit_stub(fixture: git_fixture.Fixture) -> Path:
    """PATH-shadow `ds-emit` with a stub that captures its 4th argument
    (the JSON data payload) so a test can read `status` / `files_staged` /
    `files_committed` literally instead of inferring them from stdout."""
    bin_dir = fixture.repo_dir.parent / "emit-stub-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log_path = bin_dir / "emit.json"
    stub = bin_dir / "ds-emit"
    stub.write_text(
        "#!/bin/sh\n"
        f"printf '%s' \"$4\" > '{log_path}'\n"
        "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    fixture.env["PATH"] = f"{bin_dir}{os.pathsep}{fixture.env['PATH']}"
    return log_path


def _emit_payload(log_path: Path) -> dict:
    assert log_path.exists(), "ds-emit was never invoked - no event payload to inspect"
    return json.loads(log_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Mutations. Each is a real mutant of the shipped block, used either by the
# harness self-check below or (documented in the PR) run by hand to confirm the
# corresponding test goes red.
# ---------------------------------------------------------------------------

_ADD_LINE = (
    'KC_ADD_ERR=$(GIT_INDEX_FILE="$KC_IDX" git -C "$REPO" add -- "$KC_F" 2>&1 >/dev/null)'
)
_LOOP_HEADER = "for KC_F in MEMORY.md decisions.md .agentic/learnings.md; do"


def _mutate_empty_survivor_loop(block: str) -> str:
    """Force the staging loop to iterate over nothing, so no file is ever
    staged and no commit can be produced."""
    return mse.apply_transform(
        block, _LOOP_HEADER, lambda text: text.replace(_LOOP_HEADER, 'for KC_F in ""; do')
    )


def _mutate_post_loop_unquoted_add(block: str) -> str:
    """The zsh word-splitting defect: accumulate survivors into one variable
    and stage them after the loop with an UNQUOTED expansion. Under bash the
    variable word-splits into three pathspecs and this works; under zsh it does
    not split, so git receives one pathspec containing spaces."""
    mutated = mse.apply_transform(
        block,
        _ADD_LINE,
        lambda text: text.replace(_ADD_LINE, 'KC_SURVIVORS="$KC_SURVIVORS $KC_F"; KC_ADD_ERR=""'),
    )
    return mse.apply_transform(
        mutated,
        "\n      done\n",
        lambda text: text.replace(
            "\n      done\n",
            '\n      done\n      GIT_INDEX_FILE="$KC_IDX" git -C "$REPO" add -- $KC_SURVIVORS\n',
        ),
    )


# ---------------------------------------------------------------------------
# 1. zsh word-splitting.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_all_three_files_stage_without_word_splitting(tmp_path, shell):
    """A post-loop `git add -- $KC_SURVIVORS` is the defect: zsh does not
    word-split unquoted expansions, so git receives one pathspec containing
    spaces and fails. The shipped block stages inside the loop with a quoted
    "$KC_F", which is shell-independent."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    before = _origin_count(fixture)

    result = _run(fixture, shell)
    _assert_completed(result)

    assert _origin_count(fixture) == before + 1, (
        f"expected exactly one new commit on origin/{fixture.branch_name}.\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert _origin_tip_files(fixture) == sorted([MEMORY, DECISIONS, LEARNINGS]), (
        f"all three knowledge files must be in the commit: {result.stdout}"
    )
    assert "fatal: pathspec" not in result.stderr, result.stderr


# ---------------------------------------------------------------------------
# 2. Return-driven survivor list + a categorical `.agentic/*` floor.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_learnings_alone_commits_with_no_agentic_path_floor(tmp_path, shell):
    """Two defects at once. A categorical `.agentic/*` refusal - the defect
    that made this phase's deleted predecessor ship zero commits over its whole
    lifetime - would produce NO commit here. A survivor list driven by an agent
    return value rather than by disk would not see the learnings write at
    all."""
    shell = _shell_or_skip(shell)
    modes = {MEMORY: "identical", DECISIONS: "identical", LEARNINGS: "modified"}
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path, modes)
    before = _origin_count(fixture)

    result = _run(fixture, shell)
    _assert_completed(result)

    assert _origin_count(fixture) == before + 1, (
        f"expected exactly one new commit.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert _origin_tip_files(fixture) == [LEARNINGS], (
        "only the changed file may be committed, and .agentic/learnings.md is "
        f"a first-class candidate: {result.stdout}"
    )


# ---------------------------------------------------------------------------
# 3. Staging or refreshing against the REAL index.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_real_index_is_never_read_or_written(tmp_path, shell):
    """Dropping GIT_INDEX_FILE="$KC_IDX" from ANY of read-tree / update-index /
    add / write-tree / diff-index makes the block operate on the conductor's
    real index. `update-index` alone is enough: it rewrites whichever index it
    targets, so that single omission reds the sha256 assertion below even
    though it stages nothing."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    index_path = fixture.repo_dir / ".git" / "index"

    # Order matters: `git status` REFRESHES (and rewrites) the real index, so
    # the "before" snapshot is taken AFTER the pre-run status, and the "after"
    # status is taken AFTER the post-run snapshot.
    status_before = _git(fixture, "status", "--porcelain").stdout
    sha_before = hashlib.sha256(index_path.read_bytes()).hexdigest()

    result = _run(fixture, shell)
    _assert_completed(result)

    sha_after = hashlib.sha256(index_path.read_bytes()).hexdigest()
    status_after = _git(fixture, "status", "--porcelain").stdout

    assert sha_after == sha_before, (
        "$REPO/.git/index was modified - some index operation is missing its "
        "GIT_INDEX_FILE assignment"
    )
    # The block writes .agentic/knowledge-commit-state.json on push success;
    # that new untracked path is the ONE expected porcelain difference and is
    # not an index mutation.
    def _strip_state(text: str) -> list[str]:
        return [ln for ln in text.splitlines() if "knowledge-commit-state.json" not in ln]

    assert _strip_state(status_after) == _strip_state(status_before), (
        f"working-tree/index state changed:\n{status_before!r}\n->\n{status_after!r}"
    )
    assert _git(fixture, "diff", "--cached", "--quiet").returncode == 0, (
        "the real index has staged content after the run"
    )
    leftovers = sorted(
        p.name for p in (fixture.repo_dir / ".git").glob("knowledge-commit-index-*")
    )
    assert leftovers == [], f"temporary index files were not cleaned up: {leftovers}"


# ---------------------------------------------------------------------------
# 4. Suppressed gitignore diagnostic.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_gitignored_files_are_skipped_audibly(tmp_path, shell):
    """Both halves matter. Suppressing `check-ignore -v` with `>/dev/null` (its
    matched-rule output is on STDOUT, so `2>/dev/null` is a NO-OP here and is
    not the mutation to test with) or deleting the echo leaves the skip silent,
    which is the exact silent-strand failure this diagnostic exists to prevent.
    Both of those real mutations red the assertions below. This is also the
    DinoStack shape: all three candidates ignored, so Phase 11e is a deliberate
    no-op here - but an AUDIBLE one."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_dinostack_shape(tmp_path)
    before = _origin_count(fixture)

    result = _run(fixture, shell)
    _assert_completed(result)

    assert _origin_count(fixture) == before, "nothing is committable on the DinoStack shape"
    diagnostics = [ln for ln in result.stdout.splitlines() if "is gitignored (rule:" in ln]
    assert len(diagnostics) == 3, (
        f"expected one visible gitignore diagnostic per candidate, got "
        f"{diagnostics!r}\nSTDOUT:\n{result.stdout}"
    )
    for rel_path in git_fixture.KNOWLEDGE_FILES:
        named = [ln for ln in diagnostics if ln.split(" is gitignored")[0].endswith(rel_path)]
        assert len(named) == 1, f"no diagnostic names {rel_path}: {diagnostics!r}"
        # The MATCHED RULE must actually be quoted. Suppressing `check-ignore
        # -v` with `>/dev/null` leaves the line printing "(rule: )" - visible
        # but useless - so counting lines alone does not catch that
        # suppression. (`2>/dev/null` would be a no-op: the matched rule is on
        # STDOUT.)
        rule = named[0].split("(rule:", 1)[1].rsplit(")", 1)[0].strip()
        assert ".gitignore:" in rule, (
            f"the diagnostic for {rel_path} must quote the matched rule from "
            f"`check-ignore -v`, got {rule!r}"
        )


# ---------------------------------------------------------------------------
# 4b. Point-of-use defeated-negation check (round 12).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_defeated_negation_is_skipped_loudly_others_still_commit(tmp_path, shell):
    """The consumer shape has WORKING negations for all three candidates and
    would otherwise commit all three (see the positive-path tests) - here a
    PATH-shadowed stub `ds-migrate` reports `.agentic/learnings.md`
    specifically as a DEFEATED negation. That file must be skipped with a
    visible ERROR naming it, while MEMORY.md and decisions.md - unaffected
    by the stub - still commit normally: per-file gating, not a whole-sweep
    abort."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    git_fixture.install_ds_migrate_stub(tmp_path, fixture.env, LEARNINGS)
    before = _origin_count(fixture)

    result = _run(fixture, shell)
    _assert_completed(result)

    assert "ERROR" in result.stdout, f"expected a visible ERROR line:\n{result.stdout}"
    assert "DEFEATED NEGATION" in result.stdout
    assert LEARNINGS in result.stdout

    assert _origin_count(fixture) == before + 1, "expected exactly one commit"
    tip_files = _origin_tip_files(fixture)
    assert LEARNINGS not in tip_files, f"defeated-negation file must not be committed: {tip_files}"
    assert MEMORY in tip_files, f"unaffected files must still commit: {tip_files}"
    assert DECISIONS in tip_files, f"unaffected files must still commit: {tip_files}"


# ---------------------------------------------------------------------------
# 5. Malformed DCO trailer.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_dco_trailer_is_wellformed_or_the_commit_is_skipped(tmp_path, shell):
    """Positive control FIRST: with an identity configured, a well-formed
    trailer really is produced. Without it, the absence assertion below would
    pass vacuously on a block that produces no commit at all for some unrelated
    reason."""
    shell = _shell_or_skip(shell)

    control_dir = tmp_path / "control"
    control_dir.mkdir()
    control = git_fixture.build_knowledge_consumer_shape(control_dir)
    control_before = _origin_count(control)
    control_result = _run(control, shell)
    _assert_completed(control_result)
    assert _origin_count(control) == control_before + 1, control_result.stderr
    assert re.search(r"^Signed-off-by: .+ <.+@.+>$", _origin_tip_body(control), re.M), (
        f"positive control: a well-formed DCO trailer must be produced.\n"
        f"{_origin_tip_body(control)!r}"
    )

    unset_dir = tmp_path / "unset"
    unset_dir.mkdir()
    fixture = git_fixture.build_knowledge_consumer_shape(unset_dir)
    # Blank the fixture-local global gitconfig AFTER the build, so the fixture's
    # own seed commits still work but `git config user.name` now resolves empty.
    Path(fixture.env["GIT_CONFIG_GLOBAL"]).write_text("", encoding="utf-8")
    assert _git(fixture, "config", "user.name").stdout.strip() == ""
    before = _origin_count(fixture)

    result = _run(fixture, shell)
    _assert_completed(result)

    assert _origin_count(fixture) == before, (
        f"no commit may be produced without a resolvable identity.\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert not re.search(r"Signed-off-by:\s*<>", _origin_tip_body(fixture)), (
        "a malformed empty DCO trailer was committed"
    )


# ---------------------------------------------------------------------------
# 6. One empty commit per invocation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_second_run_over_unchanged_state_adds_no_commit(tmp_path, shell):
    """Two independent guards keep a re-run from producing an empty commit: the
    `KC_N -eq 0` staging guard, and the tree-identity short-circuit behind it.
    Deleting BOTH lets run 2 commit a tree identical to the branch tip."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    before = _origin_count(fixture)

    first = _run(fixture, shell)
    _assert_completed(first)
    after_first = _origin_count(fixture)
    assert after_first == before + 1, (
        f"run 1 must produce exactly one commit.\nSTDOUT:\n{first.stdout}\n"
        f"STDERR:\n{first.stderr}"
    )

    second = _run(fixture, shell)
    _assert_completed(second)
    assert _origin_count(fixture) == after_first, (
        f"run 2 over unchanged state must produce NO commit.\n"
        f"STDOUT:\n{second.stdout}\nSTDERR:\n{second.stderr}"
    )


# ---------------------------------------------------------------------------
# 7. Ref-absent path.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_absent_branch_ref_is_reported_separately_from_fetch_failure(tmp_path, shell):
    """A transient fetch failure and an absent branch ref are SEPARATE
    conditions: collapsing them would report "branch not found" for a network
    blip on a branch that exists locally and would have pushed fine."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_no_remote_shape(tmp_path)
    assert fixture.origin_dir is None
    log_path = _install_emit_stub(fixture)
    head_before = _git(fixture, "rev-parse", "HEAD").stdout.strip()

    result = _run(fixture, shell)
    _assert_completed(result)

    # The WARNING below goes to stdout, which is not durable. Only the event
    # payload survives, so "no PR branch" must be a DISTINCT status there - left
    # at the "no-changes" initializer it would be indistinguishable from
    # "nothing changed", which is how this phase's deleted predecessor shipped
    # zero commits for its entire lifetime without anyone noticing.
    assert _emit_payload(log_path)["status"] == "no-branch", _emit_payload(log_path)

    assert result.returncode == 0, result.stderr
    assert _git(fixture, "rev-parse", "HEAD").stdout.strip() == head_before
    assert _git(fixture, "rev-list", "--count", "HEAD").stdout.strip() == _git(
        fixture, "rev-list", "--count", fixture.branch_name
    ).stdout.strip()
    resolve_lines = [ln for ln in result.stdout.splitlines() if "does not resolve" in ln]
    assert len(resolve_lines) == 1, (
        f"expected the ref-absence warning, got:\n{result.stdout}"
    )
    assert "fetch" not in resolve_lines[0], (
        f"the ref-absence warning must not be phrased as a fetch failure: "
        f"{resolve_lines[0]!r}"
    )
    assert _no_bare_exit(_block()), "the block must contain no bare `exit`"


# ---------------------------------------------------------------------------
# 8. Push failure.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_rejected_push_leaves_no_marker_and_reports_the_remote_error(tmp_path, shell):
    """The default all-"modified" modes are load-bearing here: they force a
    real ref update. A no-op push short-circuits client-side with "Everything
    up-to-date" and exit 0, never reaching the remote's pre-receive hook, which
    would make this test pass vacuously."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_push_reject_shape(tmp_path)
    before = _origin_count(fixture)

    result = _run(fixture, shell)
    _assert_completed(result)

    rejected = [ln for ln in result.stdout.splitlines() if "rejected:" in ln]
    assert len(rejected) == 1, (
        f"the push-failed branch must be reached and reported.\nSTDOUT:\n{result.stdout}"
    )
    assert _origin_count(fixture) == before, "a rejected push must leave the remote unchanged"
    assert not (fixture.repo_dir / STATE_FILE).exists(), (
        "the dedup marker must NOT be written when the push failed - Part G "
        "would then skip content that was never shipped"
    )
    assert git_fixture.PUSH_REJECT_MESSAGE in rejected[0], (
        f"the remote's own stderr must be surfaced: {rejected[0]!r}"
    )


# ---------------------------------------------------------------------------
# 9. Revert guard: warn, skip under auto-merge, and FAIL CLOSED.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_deleted_lines_warn_and_name_the_real_branch(tmp_path, shell):
    """The branch name must reach awk via `-v`. An `ENVIRON["BRANCH_NAME"]`
    lookup resolves EMPTY under both shells (the variable is assigned, not
    exported - the production shape), which would print `origin/ -` and red
    this assertion."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path, {MEMORY: "fewer_lines"})
    before = _origin_count(fixture)

    result = _run(fixture, shell)
    _assert_completed(result)

    assert _origin_count(fixture) == before + 1, (
        "with auto-merge off the commit still proceeds; the warning is the "
        f"whole defense.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    pattern = r"has [0-9]+ deleted line\(s\) vs origin/" + re.escape(fixture.branch_name)
    assert re.search(pattern, result.stdout), (
        f"expected a deleted-line warning naming origin/{fixture.branch_name}.\n"
        f"STDOUT:\n{result.stdout}"
    )


@pytest.mark.parametrize("shell", SHELLS)
def test_revert_risk_is_skipped_under_auto_merge(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path, {MEMORY: "fewer_lines"})
    _write_config(fixture, {"auto_merge_on_ci_green": True})
    log_path = _install_emit_stub(fixture)
    before = _origin_count(fixture)

    result = _run(fixture, shell)
    _assert_completed(result)

    assert _origin_count(fixture) == before, (
        "under auto-merge nobody reads the PR diff, so a revert-risk commit "
        f"must not be pushed.\nSTDOUT:\n{result.stdout}"
    )
    assert _emit_payload(log_path)["status"] == "revert-risk-skipped"


@pytest.mark.parametrize("shell", SHELLS)
def test_revert_guard_fails_closed_when_it_cannot_be_evaluated(tmp_path, shell):
    """An unevaluable guard counts as RISK PRESENT, never as risk absent."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    _write_config(fixture, {"auto_merge_on_ci_green": True})
    log_path = _install_emit_stub(fixture)
    git_fixture.install_git_stub(fixture, fail_subcommand="diff-index")
    before = _origin_count(fixture)

    result = _run(fixture, shell)
    _assert_completed(result)

    assert _origin_count(fixture) == before, result.stdout
    payload = _emit_payload(log_path)
    assert payload["status"] == "revert-risk-skipped"
    assert payload["deleted_lines"] == -1, payload
    failed = [ln for ln in result.stdout.splitlines() if "diff-index failed" in ln]
    assert len(failed) == 1 and "AE-GIT-STUB" in failed[0], (
        f"the guard failure must name the underlying error: {result.stdout}"
    )


# ---------------------------------------------------------------------------
# 10. Phase 12 auto-merge.
# ---------------------------------------------------------------------------

_GH_STUB = r"""#!/bin/sh
AE_GH_LOG='__LOG__'
line=""
for a in "$@"; do line="$line$a$(printf '\037')"; done
printf '%s\n' "$line" >> "$AE_GH_LOG"

case "$1 $2" in
  "pr view")
    case "$*" in
      *"--json isDraft"*)
        [ "$AE_GH_FAIL_PRSTATE" = "1" ] && exit 1
        printf '{"isDraft":false,"mergeable":"MERGEABLE","reviewDecision":"NONE"}\n'
        exit 0 ;;
      *"--json commits"*)
        [ "$AE_GH_FAIL_COMMITS" = "1" ] && exit 1
        printf '%s\n' "$AE_GH_TIP_HEADLINE"
        exit 0 ;;
      *"--json state"*)
        printf '%s\n' "${AE_GH_STATE:-OPEN}"
        exit 0 ;;
    esac
    exit 1 ;;
  "pr merge")
    exit "${AE_GH_MERGE_EXIT:-0}" ;;
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


def _phase12_env(tmp_path: Path, **overrides: str) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "gh-stub-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log_path = bin_dir / "gh-argv.log"
    log_path.write_text("", encoding="utf-8")
    for name, body in (("gh", _GH_STUB.replace("__LOG__", str(log_path))), ("jq", _JQ_STUB)):
        stub = bin_dir / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["AE_GH_TIP_HEADLINE"] = "feat: something else"
    env["AE_GH_FAIL_COMMITS"] = "0"
    env["AE_GH_FAIL_PRSTATE"] = "0"
    env.update(overrides)
    return env, log_path


def _run_phase12(tmp_path: Path, shell: str, env: dict[str, str]):
    script = mse.with_completion_marker(
        mse.with_shell_assignments(
            _block(MARKER_PHASE12),
            {"AUTO_MERGE_ON_CI_GREEN": "true", "PR_NUMBER": "42", "GH_REPO": "acme/widget"},
        )
    )
    return subprocess.run(
        [shell, "-c", script],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=BLOCK_TIMEOUT_SECONDS,
        stdin=subprocess.DEVNULL,
    )


def _gh_argv(log_path: Path) -> list[list[str]]:
    raw = log_path.read_text(encoding="utf-8")
    return [
        [f for f in line.split("\x1f") if f != ""] for line in raw.splitlines() if line.strip()
    ]


@pytest.mark.parametrize("shell", SHELLS)
def test_phase12_queues_auto_merge_when_the_tip_is_a_knowledge_commit(tmp_path, shell):
    """`--auto` exiting 0 means QUEUED, not MERGED - the block must not claim
    `auto-merged` on that branch, or W7 would fire against an unmerged PR."""
    shell = _shell_or_skip(shell)
    env, log_path = _phase12_env(
        tmp_path, AE_GH_TIP_HEADLINE="chore(knowledge): capture MEMORY.md from ticket session"
    )
    result = _run_phase12(tmp_path, shell, env)
    _assert_completed(result)

    argv = _gh_argv(log_path)
    merges = [call for call in argv if call[:2] == ["pr", "merge"]]
    assert len(merges) == 1 and "--auto" in merges[0], argv
    assert "auto-merge-queued" in result.stdout, result.stdout
    assert "auto-merged" not in result.stdout, result.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_phase12_merges_immediately_when_the_tip_is_not_a_knowledge_commit(tmp_path, shell):
    shell = _shell_or_skip(shell)
    env, log_path = _phase12_env(tmp_path)
    result = _run_phase12(tmp_path, shell, env)
    _assert_completed(result)

    merges = [call for call in _gh_argv(log_path) if call[:2] == ["pr", "merge"]]
    assert len(merges) == 1 and "--auto" not in merges[0], merges
    assert "auto-merged" in result.stdout, result.stdout
    assert "auto-merge-queued" not in result.stdout, result.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_phase12_falls_back_to_the_pre_11e_path_when_the_tip_lookup_fails(tmp_path, shell):
    """Only the `--json commits` call fails; the isDraft/mergeable lookup still
    succeeds. The block must degrade to exactly its pre-Phase-11e behavior."""
    shell = _shell_or_skip(shell)
    env, log_path = _phase12_env(tmp_path, AE_GH_FAIL_COMMITS="1")
    result = _run_phase12(tmp_path, shell, env)
    _assert_completed(result)

    merges = [call for call in _gh_argv(log_path) if call[:2] == ["pr", "merge"]]
    assert len(merges) == 1 and "--auto" not in merges[0], merges
    assert "auto-merged" in result.stdout, result.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_phase12_skips_without_merging_when_the_pr_state_lookup_fails(tmp_path, shell):
    """Pre-existing behavior, pinned so Phase 11e's edit cannot change it: an
    empty PR_STATE fails the IS_DRAFT gate and `gh pr merge` is never called."""
    shell = _shell_or_skip(shell)
    env, log_path = _phase12_env(tmp_path, AE_GH_FAIL_PRSTATE="1")
    result = _run_phase12(tmp_path, shell, env)
    _assert_completed(result)

    assert "auto-merge-skipped" in result.stdout, result.stdout
    merges = [call for call in _gh_argv(log_path) if call[:2] == ["pr", "merge"]]
    assert merges == [], f"gh pr merge must never be invoked on this path: {merges}"


# ---------------------------------------------------------------------------
# 11. The knowledge_commit_on_pr toggle.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_toggle_false_attempts_no_git_at_all(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    _write_config(fixture, {"knowledge_commit_on_pr": False})
    stub = git_fixture.install_git_stub(fixture)
    before = _origin_count(fixture)

    result = _run(fixture, shell)
    _assert_completed(result)

    assert _origin_count(fixture) == before
    assert "status=disabled" in result.stdout, result.stdout
    assert not stub.was_attempted("fetch"), stub.subcommands()
    assert not stub.was_attempted("push"), stub.subcommands()


@pytest.mark.parametrize("shell", SHELLS)
def test_toggle_absent_defaults_to_enabled(tmp_path, shell):
    """The control for the assertion above: with the key absent the SAME
    fixture commits and the stub records fetch and push, so their absence there
    is a real absence and not an empty log."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    _write_config(fixture, {"some_other_key": True})
    stub = git_fixture.install_git_stub(fixture)
    before = _origin_count(fixture)

    result = _run(fixture, shell)
    _assert_completed(result)

    assert _origin_count(fixture) == before + 1, result.stdout
    assert stub.was_attempted("fetch") and stub.was_attempted("push"), stub.subcommands()


# ---------------------------------------------------------------------------
# 12. The missing index refresh.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_stat_dirty_identical_file_is_not_misclassified_as_changed(tmp_path, shell):
    """`git diff-index --quiet` trusts stat data over content outside git's
    racily-clean window, so a byte-identical file rewritten with a newer mtime
    reads as CHANGED. The fixture forces that state, so deleting the
    `update-index -q --refresh` line misclassifies MEMORY.md on EVERY run
    rather than one in three."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path, {MEMORY: "identical"})
    log_path = _install_emit_stub(fixture)
    before = _origin_count(fixture)

    result = _run(fixture, shell)
    _assert_completed(result)

    assert _origin_count(fixture) == before + 1, result.stdout
    payload = _emit_payload(log_path)
    assert MEMORY not in payload["files_staged"], payload
    assert MEMORY not in _origin_tip_files(fixture), _origin_tip_files(fixture)
    assert _origin_tip_files(fixture) == sorted([DECISIONS, LEARNINGS]), (
        "the genuinely-changed files must still be committed"
    )


# ---------------------------------------------------------------------------
# 13. files_committed on failure paths.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_files_committed_is_empty_on_a_failed_push(tmp_path, shell):
    """`files_committed` means files ACTUALLY committed. Populating it at
    staging time would make a failed push indistinguishable from a success in
    events.jsonl - the log would assert content shipped that never left the
    machine."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_push_reject_shape(tmp_path)
    log_path = _install_emit_stub(fixture)

    result = _run(fixture, shell)
    _assert_completed(result)

    payload = _emit_payload(log_path)
    assert payload["status"] == "push-failed", payload
    assert payload["files_committed"] == [], payload
    assert payload["files_staged"] != [], (
        "files_staged must be non-empty, or the emptiness of files_committed "
        "above proves nothing"
    )
    assert isinstance(payload["deleted_lines"], int), payload


@pytest.mark.parametrize("shell", SHELLS)
def test_files_committed_equals_files_staged_on_success(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    log_path = _install_emit_stub(fixture)

    result = _run(fixture, shell)
    _assert_completed(result)

    payload = _emit_payload(log_path)
    assert payload["status"] == "committed", payload
    assert payload["files_committed"] == payload["files_staged"] != [], payload
    assert isinstance(payload["deleted_lines"], int), payload
    assert (fixture.repo_dir / STATE_FILE).exists(), "the dedup marker must be written"


# ---------------------------------------------------------------------------
# 14. Harness self-check.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_an_empty_survivor_loop_breaks_the_commit_producing_tests(tmp_path, shell):
    """Self-check: tests 1, 2, 6 and 12 above all depend on the block actually
    producing a commit. Force the survivor loop empty and that shared
    precondition must be violated - if it is not, those four tests are passing
    for a reason unrelated to what they claim to measure."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    before = _origin_count(fixture)

    result = _run(fixture, shell, block=_mutate_empty_survivor_loop(_block()))
    _assert_completed(result)

    assert _origin_count(fixture) == before, (
        "the mutant still produced a commit - the commit-producing assertions "
        "in this module are not measuring the staging loop"
    )


@pytest.mark.parametrize("shell", SHELLS)
def test_the_word_splitting_mutant_is_shell_dependent(tmp_path, shell):
    """The other half of the self-check: the post-loop unquoted-add mutant must
    behave DIFFERENTLY under bash and zsh. If it worked under both, test 1
    would be pinning nothing about word-splitting."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    before = _origin_count(fixture)

    result = _run(fixture, shell, block=_mutate_post_loop_unquoted_add(_block()))
    _assert_completed(result)

    if shell == "bash":
        assert _origin_count(fixture) == before + 1, (
            f"under bash the unquoted expansion word-splits and still works.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    else:
        assert "fatal: pathspec" in result.stderr, (
            "under zsh the unquoted expansion does NOT word-split, so git must "
            f"reject the single space-containing pathspec.\nSTDERR:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# 15. Static, shell-independent.
# ---------------------------------------------------------------------------

_COMMENT_RE = re.compile(r"#.*$")
_BARE_EXIT_RE = re.compile(r"(?:^|[;&|]\s*)exit\b")


def _no_bare_exit(block: str) -> bool:
    """True when no line of block runs `exit` as a COMMAND. Comments are
    stripped first: both blocks legitimately discuss exit codes in prose."""
    for line in block.splitlines():
        if _BARE_EXIT_RE.search(_COMMENT_RE.sub("", line)):
            return False
    return True


def test_static_neither_block_contains_a_bare_exit():
    """with_completion_marker's precondition: marker-absence proves
    non-completion ONLY if the block cannot exit early on its own. Phase 11e
    additionally contracts for zero `exit` statements as its soft-fail
    guarantee."""
    for marker in (MARKER, MARKER_PHASE12):
        assert _no_bare_exit(_block(marker)), f"`exit` found in the {marker} block"


def test_static_render_raises_on_both_blocks():
    """render() is Phase-8-only: PLACEHOLDER_WHITELIST is global and fail-closed
    pre-render, so it raises on any block without all three Phase 8
    placeholders. Pinned mechanically so this module's bypass can never quietly
    become unnecessary (or quietly become wrong)."""
    for marker in (MARKER, MARKER_PHASE12):
        block = _block(marker)
        for key in mse.PLACEHOLDER_WHITELIST:
            assert key not in block, f"{marker} must contain no Phase 8 placeholder ({key!r})"
        with pytest.raises(mse.HarnessExtractionError):
            mse.render(block)


def test_static_extraction_is_non_vacuous():
    block = _block()
    assert len(block.splitlines()) > 100, "the Phase 11e block should be substantial"
    for anchor in (
        "GIT_INDEX_FILE",
        "update-index -q --refresh",
        "check-ignore -v",
        "commit-tree",
        "knowledge_commit_on_pr",
        "revert-risk-skipped",
    ):
        assert anchor in block, f"expected literal anchor {anchor!r} in the extracted block"
    phase12 = _block(MARKER_PHASE12)
    for anchor in ("KC_KNOWLEDGE_PUSHED", "--auto", "auto-merge-deferred"):
        assert anchor in phase12, f"expected literal anchor {anchor!r} in the Phase 12 block"
