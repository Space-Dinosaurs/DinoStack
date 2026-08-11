"""
Purpose: Proves the knowledge-commit test harness works before any
         knowledge-commit block exists to test. Executes a throwaway
         second `@harness:`-marked block
         (bin/tests/fixtures/knowledge_harness_smoke.md, marker
         `knowledge-smoke`) end to end against the four new
         build_knowledge_* fixtures under both bash and zsh, and pins the
         answers to the four harness questions that blocked the
         knowledge-commit test plan: (1) md_shell_extract.render() is
         Phase-8-only and RAISES on a zero-placeholder block, so new
         consumers must bypass it; (2) a value can be injected as a
         non-exported shell assignment (awk -v sees it, awk ENVIRON[] does
         not - which is the production shape); (3) a tee-and-delegate `git`
         stub can force one subcommand to fail while a dozen other git calls
         in the same block still work, and can prove a command was never
         attempted; (4) `awk '{s += $2} END {print s+0}'` on an empty file
         emits "0", not nothing.

Public API: none (pytest test module; 13 parametrized functions x {bash, zsh}
            = 26 collected IDs, plus 4 static shell-independent assertions =
            30 - see the collected-count floor in
            .github/workflows/bin-tests.yml).

Upstream deps: bin/tests/lib/md_shell_extract.py, bin/tests/lib/git_fixture.py,
               bin/tests/fixtures/knowledge_harness_smoke.md.

Downstream consumers: .github/workflows/bin-tests.yml (python-bin-tests job).

Failure modes: n/a (test module). Every fixture claim is asserted against
               ACTUAL git state (check-ignore / cat-file / rev-parse / a real
               push against the bare origin), never against the builder's own
               return value - a builder that lies about the shape it produced
               is exactly the failure this module exists to exclude.

Performance: standard; each test builds one or two temp git repos with a bare
             origin and runs one subprocess shell invocation.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib.git_fixture as git_fixture  # noqa: E402
import lib.md_shell_extract as mse  # noqa: E402

MD_PATH = Path(__file__).resolve().parent / "fixtures" / "knowledge_harness_smoke.md"
MARKER = "knowledge-smoke"

SHELLS = ["bash", "zsh"]

MEMORY = "MEMORY.md"
DECISIONS = "decisions.md"
LEARNINGS = ".agentic/learnings.md"

# Every subprocess in this module is bounded and stdin-closed. A per-call
# timeout LARGER than the CI step budget can never fire usefully - two 120s
# calls alone exceeded the old 5-minute job limit, so the job died before any
# timeout produced a diagnostic. These are sized to fail inside the step and
# under pytest-timeout's own 60s per-test limit, leaving a stack trace at the
# exact call. stdin=DEVNULL keeps a prompting git from blocking under
# `-s` / `-p no:capture`, where pytest's fd-0 capture is absent.
BLOCK_TIMEOUT_SECONDS = 30
GIT_TIMEOUT_SECONDS = 30


def _shell_or_skip(shell: str) -> str:
    """Skip locally when a shell is missing; hard-fail in CI so the zsh half
    of the matrix can never be silently dropped (see the same guard in
    test_phase8_telemetry_shell.py)."""
    if shutil.which(shell) is None:
        if os.environ.get("CI"):
            pytest.fail(f"{shell} not found in CI - the python-bin-tests job must install it")
        pytest.skip(f"{shell} not found on this machine")
    return shell


def _raw_block() -> str:
    return mse.extract_marked_block(str(MD_PATH), MARKER)


def _run_block(fixture: git_fixture.Fixture, shell: str) -> subprocess.CompletedProcess:
    """Execute the smoke block with BRANCH_NAME injected as a NON-exported
    shell assignment, and assert it is absent from the subprocess env - if it
    leaked into the env, the ENVIRON[] half of the Q2 assertion would pass
    for the wrong reason."""
    assert "BRANCH_NAME" not in fixture.env, (
        "BRANCH_NAME must not be in the fixture env - it is injected as a "
        "non-exported shell assignment so the block reproduces production"
    )
    script = mse.with_shell_assignments(
        mse.with_completion_marker(_raw_block()),
        {"BRANCH_NAME": fixture.branch_name},
    )
    return subprocess.run(
        [shell, "-c", script],
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


def _field(stdout: str, key: str) -> str:
    """Value of the single `KEY=[value]`-shaped probe line."""
    prefix = f"{key}=["
    hits = [ln for ln in stdout.splitlines() if ln.startswith(prefix)]
    assert len(hits) == 1, f"expected exactly 1 {key} line, got {hits!r}"
    return hits[0][len(prefix) : -1]


def _plain_field(stdout: str, key: str) -> str:
    """Value of the single `KEY=value`-shaped probe line (no brackets)."""
    prefix = f"{key}="
    hits = [ln for ln in stdout.splitlines() if ln.startswith(prefix)]
    assert len(hits) == 1, f"expected exactly 1 {key} line, got {hits!r}"
    return hits[0][len(prefix) :]


def _file_state(stdout: str, rel_path: str) -> str:
    prefix = f"SMOKE_FILE {rel_path}="
    hits = [ln for ln in stdout.splitlines() if ln.startswith(prefix)]
    assert len(hits) == 1, f"expected exactly 1 SMOKE_FILE line for {rel_path}, got {hits!r}"
    return hits[0][len(prefix) :]


def _git(fixture: git_fixture.Fixture, *args: str, cwd: Path | None = None):
    return subprocess.run(
        ["git", "-C", str(cwd or fixture.repo_dir), *args],
        env=fixture.env,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        stdin=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# Q1 (static). render() is Phase-8-only: it raises on a zero-placeholder
# block, so a new consumer must bypass it. Pinned mechanically so a future
# change to render()'s contract cannot silently invalidate the manifest note.
# ---------------------------------------------------------------------------


def test_render_raises_on_this_block_so_consumers_must_bypass_it():
    block = _raw_block()
    for key in mse.PLACEHOLDER_WHITELIST:
        assert key not in block, (
            f"this fixture block must contain NO Phase 8 placeholder; found {key!r}"
        )
    with pytest.raises(mse.HarnessExtractionError) as excinfo:
        mse.render(block)
    message = str(excinfo.value)
    assert "occurs 0 times" in message
    # The raise must send a new consumer to the BYPASS, not to editing the
    # global whitelist - adding keys there would break Phase 8's render call
    # sites, and this is precisely the raise a new consumer hits first.
    assert "bypass render()" in message, message
    assert "do NOT add keys to the whitelist" in message, message


def test_extraction_is_non_vacuous():
    block = _raw_block()
    lines = block.splitlines()
    assert len(lines) > 40, f"expected >40 lines, got {len(lines)}"
    for anchor in ("SMOKE_AWK_ENVIRON", "diff-index", "push -q origin", "check-ignore"):
        assert anchor in block, f"expected literal anchor {anchor!r} in extracted block"


# ---------------------------------------------------------------------------
# git_fixture.DINOSTACK_GITIGNORE / DINOSTACK_KNOWLEDGE_GITIGNORE are
# hard-copies of this repo's own root .gitignore, not a derivation from it -
# nothing re-checks the copy against reality automatically (see the note on
# each constant in lib/git_fixture.py). A prior round removed the dead
# `!/.agentic/team.yml` negation from the live .gitignore (c9bf29b9) and left
# both fixture constants asserting the old shape for four more commits before
# this test existed. Assert the copies against the live file directly so a
# future divergence fails loudly instead of silently.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_dinostack_gitignore_constants_match_live_root_gitignore():
    live_lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    # Only checks the two root-ANCHORED forms (`/.agentic...` and
    # `!/.agentic...`) - the current live shape. A future non-anchored form
    # (e.g. `.agentic/*` or `!.agentic/team.yml`, with no leading `/`) would
    # not be matched by this filter and would drift undetected; if the live
    # file's .agentic/ shape ever moves to a non-anchored form, widen this
    # filter in the same change.
    live_agentic_lines = [
        line
        for line in live_lines
        if line.strip() and (line.startswith("/.agentic") or line.startswith("!/.agentic"))
    ]
    assert live_agentic_lines == ["/.agentic/*"], (
        "live root .gitignore's root-anchored .agentic/-related lines "
        f"changed shape; got {live_agentic_lines!r} - update "
        "git_fixture.DINOSTACK_GITIGNORE and DINOSTACK_KNOWLEDGE_GITIGNORE "
        "(and their comments) to match, then update this assertion's "
        "expected value"
    )
    assert git_fixture.DINOSTACK_GITIGNORE == "/.agentic/*\n", (
        "git_fixture.DINOSTACK_GITIGNORE has drifted from the live root "
        ".gitignore's .agentic/-related lines"
    )
    assert git_fixture.DINOSTACK_KNOWLEDGE_GITIGNORE == (
        "/.agentic/*\n/decisions.md\n/MEMORY.md\n"
    ), (
        "git_fixture.DINOSTACK_KNOWLEDGE_GITIGNORE has drifted from the live "
        "root .gitignore's .agentic/, decisions.md, and MEMORY.md lines"
    )
    assert "/decisions.md" in live_lines, "live root .gitignore no longer ignores decisions.md"
    assert "/MEMORY.md" in live_lines, "live root .gitignore no longer ignores MEMORY.md"


# ---------------------------------------------------------------------------
# A second @harness: marker extracts, parses, and executes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_second_marker_extracts_parses_and_executes(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    check = mse.syntax_check(_raw_block(), shell)
    assert check.returncode == 0, check.stderr
    result = _run_block(fixture, shell)
    _assert_completed(result)
    assert _plain_field(result.stdout, "SMOKE_COMMIT") == "ok", result.stdout
    assert _plain_field(result.stdout, "SMOKE_PUSH") == "ok", result.stderr


# ---------------------------------------------------------------------------
# Q2. BRANCH_NAME injected as a non-exported shell assignment.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_branch_name_is_assigned_not_exported(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    result = _run_block(fixture, shell)
    _assert_completed(result)
    assert _field(result.stdout, "SMOKE_BRANCH_ASSIGNED") == fixture.branch_name
    assert _field(result.stdout, "SMOKE_AWK_V") == fixture.branch_name, (
        "awk -v must see the assigned value"
    )
    assert _field(result.stdout, "SMOKE_AWK_ENVIRON") == "", (
        "awk ENVIRON[\"BRANCH_NAME\"] must be EMPTY - a non-empty value means "
        "the variable was exported, so the test would pass over a production "
        "path where it is only assigned"
    )


@pytest.mark.parametrize("shell", SHELLS)
def test_exported_branch_name_would_populate_environ(tmp_path, shell):
    """Both-directions control for the assertion above: with BRANCH_NAME in
    the subprocess ENV instead, ENVIRON["BRANCH_NAME"] DOES resolve. Without
    this, an ENVIRON lookup that is empty for some unrelated reason (a
    stripped env, an awk that does not implement ENVIRON) would make the
    assertion above pass vacuously."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    env = dict(fixture.env)
    env["BRANCH_NAME"] = fixture.branch_name
    script = mse.with_shell_assignments(
        mse.with_completion_marker(_raw_block()), {"BRANCH_NAME": fixture.branch_name}
    )
    result = subprocess.run(
        [shell, "-c", script],
        cwd=str(fixture.repo_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=BLOCK_TIMEOUT_SECONDS,
        stdin=subprocess.DEVNULL,
    )
    _assert_completed(result)
    assert _field(result.stdout, "SMOKE_AWK_ENVIRON") == fixture.branch_name


# ---------------------------------------------------------------------------
# Q4. awk sum over an EMPTY file.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_awk_sum_on_empty_file_emits_zero_not_nothing(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    result = _run_block(fixture, shell)
    _assert_completed(result)
    assert _field(result.stdout, "SMOKE_AWK_EMPTY_FILE") == "0", (
        "an empty-vs-zero guard would have an UNREACHABLE empty arm for a "
        "present-but-empty file: `s+0` forces numeric context and prints 0"
    )


# ---------------------------------------------------------------------------
# Builder shape assertions - against actual git state, not the return value.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_consumer_shape_supports_independent_per_file_modes(tmp_path, shell):
    shell = _shell_or_skip(shell)
    modes = {MEMORY: "identical", DECISIONS: "absent", LEARNINGS: "fewer_lines"}
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path, modes)

    # Actual git state, independent of the block.
    assert _git(fixture, "cat-file", "-e", f"HEAD:{MEMORY}").returncode == 0
    assert _git(fixture, "cat-file", "-e", f"HEAD:{DECISIONS}").returncode != 0, (
        "'absent' must mean absent from the branch tip, not merely modified"
    )
    assert _git(fixture, "cat-file", "-e", f"HEAD:{LEARNINGS}").returncode == 0
    # Compare CONTENT, not `diff-index --quiet`: the fixture deliberately
    # leaves an identical file stat-dirty, and diff-index --quiet reports a
    # stat-dirty entry as changed without inspecting its content (see
    # test_identical_file_survives_a_stat_dirty_mtime).
    assert (fixture.repo_dir / MEMORY).read_text(encoding="utf-8") == _git(
        fixture, "show", f"HEAD:{MEMORY}"
    ).stdout, "'identical' must be byte-identical to the tip"
    tip_lines = len(_git(fixture, "show", f"HEAD:{LEARNINGS}").stdout.splitlines())
    local_lines = len((fixture.repo_dir / LEARNINGS).read_text(encoding="utf-8").splitlines())
    assert local_lines < tip_lines, (
        f"'fewer_lines' must have fewer lines than the tip ({local_lines} vs {tip_lines})"
    )

    result = _run_block(fixture, shell)
    _assert_completed(result)
    assert _file_state(result.stdout, MEMORY) == "identical"
    assert _file_state(result.stdout, DECISIONS) == "untracked"
    assert _file_state(result.stdout, LEARNINGS).startswith("modified +0 -"), result.stdout
    deleted = int(_file_state(result.stdout, LEARNINGS).rsplit("-", 1)[1])
    assert deleted == tip_lines - local_lines


@pytest.mark.parametrize("shell", SHELLS)
def test_identical_file_survives_a_stat_dirty_mtime(tmp_path, shell):
    """Regression guard for a real flake this harness produced before the
    fixture forced the condition: a file rewritten with IDENTICAL content has
    an mtime newer than the index's, and `git diff-index --quiet HEAD` trusts
    stat data over content outside git's racily-clean window - so it reports
    the file as changed. Left racy, "identical" was reported ~70% of runs and
    "modified +0 -0" ~30%. The fixture now forces the stat-dirty state and the
    block must `git update-index --refresh` before diff-index; drop that
    refresh and this test fails every run rather than one in three."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path, {MEMORY: "identical"})

    # The fixture really is stat-dirty: content matches the tip byte for byte,
    # but the working file's mtime is ahead of the index's.
    assert _git(fixture, "show", f"HEAD:{MEMORY}").stdout == (
        fixture.repo_dir / MEMORY
    ).read_text(encoding="utf-8")
    # `git ls-files --debug` prints "  mtime: <secs>:<nanos>".
    index_mtime = float(
        _git(fixture, "ls-files", "--debug", "--", MEMORY)
        .stdout.split("mtime:")[1]
        .split()[0]
        .split(":")[0]
    )
    assert (fixture.repo_dir / MEMORY).stat().st_mtime > index_mtime + 1, (
        "fixture invariant: the identical file's mtime must be clearly ahead "
        "of the index's, or this test is not exercising the stat-dirty branch"
    )

    result = _run_block(fixture, shell)
    _assert_completed(result)
    assert _file_state(result.stdout, MEMORY) == "identical", (
        "an unchanged file must not be classified as changed just because it "
        "was rewritten - the block must refresh the index before diff-index"
    )


@pytest.mark.parametrize("shell", SHELLS)
def test_dinostack_shape_ignores_all_three_knowledge_files(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_dinostack_shape(tmp_path)

    for rel_path in git_fixture.KNOWLEDGE_FILES:
        assert (fixture.repo_dir / rel_path).exists(), f"{rel_path} must exist on disk"
        assert _git(fixture, "check-ignore", "-q", "--", rel_path).returncode == 0, (
            f"{rel_path} must be ignored under DINOSTACK_KNOWLEDGE_GITIGNORE"
        )

    before = _git(fixture, "rev-parse", "HEAD").stdout.strip()
    result = _run_block(fixture, shell)
    _assert_completed(result)
    for rel_path in git_fixture.KNOWLEDGE_FILES:
        assert _file_state(result.stdout, rel_path) == "ignored"
    assert _plain_field(result.stdout, "SMOKE_STAGED") == "0"
    assert _git(fixture, "rev-parse", "HEAD").stdout.strip() == before, (
        "nothing is committable on the DinoStack shape"
    )


@pytest.mark.parametrize("shell", SHELLS)
def test_no_remote_shape_has_no_remote_and_never_pushes(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_no_remote_shape(tmp_path)
    assert fixture.origin_dir is None
    assert _git(fixture, "remote").stdout.strip() == "", "this shape must have NO remote"

    stub = git_fixture.install_git_stub(fixture)
    result = _run_block(fixture, shell)
    _assert_completed(result)
    assert _plain_field(result.stdout, "SMOKE_HAS_REMOTE") == "0"
    assert _plain_field(result.stdout, "SMOKE_PUSH") == "skipped-no-remote"
    assert not stub.was_attempted("push"), (
        f"push must never be attempted without a remote; log: {stub.subcommands()}"
    )
    assert stub.was_attempted("add"), (
        "control: the stub DID record other subcommands, so the absence of "
        "'push' above is a real absence and not an empty log"
    )


@pytest.mark.parametrize("shell", SHELLS)
def test_push_reject_shape_fails_only_at_push(tmp_path, shell):
    """The load-bearing claim about this fixture's construction: with a
    pre-receive hook, `fetch` and `rev-parse origin/<branch>` BOTH succeed and
    only `push` fails. A "repoint origin at a broken path" variant would fail
    at fetch, so the block would never reach its push."""
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_push_reject_shape(tmp_path)

    fetch = _git(fixture, "fetch", "origin")
    assert fetch.returncode == 0, f"fetch must succeed: {fetch.stderr}"
    revparse = _git(fixture, "rev-parse", "--verify", f"refs/remotes/origin/{fixture.branch_name}")
    assert revparse.returncode == 0, f"rev-parse must succeed: {revparse.stderr}"
    # Probe onto a THROWAWAY ref, not the fixture branch: at this point local
    # HEAD equals the remote tip, and a no-op push short-circuits with
    # "Everything up-to-date" and exit 0 WITHOUT ever invoking the remote's
    # pre-receive hook. A throwaway ref is a genuine ref update, so the hook
    # runs; the push is rejected, so the remote is left unchanged.
    push = _git(fixture, "push", "origin", "HEAD:refs/heads/ae-fixture-probe")
    assert push.returncode != 0, "push must be rejected by the pre-receive hook"
    assert git_fixture.PUSH_REJECT_MESSAGE in push.stderr, push.stderr
    assert (
        _git(
            fixture, "rev-parse", "--verify", "ae-fixture-probe", cwd=fixture.origin_dir
        ).returncode
        != 0
    ), "a rejected push must leave the remote unchanged"

    result = _run_block(fixture, shell)
    _assert_completed(result)
    assert _plain_field(result.stdout, "SMOKE_FETCH") == "ok"
    assert _plain_field(result.stdout, "SMOKE_REVPARSE") == "ok"
    assert _plain_field(result.stdout, "SMOKE_COMMIT") == "ok"
    assert _plain_field(result.stdout, "SMOKE_PUSH") == "fail"
    assert git_fixture.PUSH_REJECT_MESSAGE in result.stderr, result.stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_consumer_shape_push_actually_lands_on_origin(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    assert fixture.origin_dir is not None
    before = _git(fixture, "rev-parse", fixture.branch_name, cwd=fixture.origin_dir).stdout.strip()

    result = _run_block(fixture, shell)
    _assert_completed(result)
    assert _plain_field(result.stdout, "SMOKE_PUSH") == "ok", result.stderr

    after = _git(fixture, "rev-parse", fixture.branch_name, cwd=fixture.origin_dir).stdout.strip()
    assert after != before, "the bare origin's branch tip must have advanced"
    local = _git(fixture, "rev-parse", "HEAD").stdout.strip()
    assert after == local
    subject = _git(
        fixture, "log", "-1", "--format=%s", fixture.branch_name, cwd=fixture.origin_dir
    ).stdout.strip()
    assert subject == f"chore(knowledge): smoke {fixture.branch_name}"


# ---------------------------------------------------------------------------
# Q3. Tee-and-delegate git stub.
# ---------------------------------------------------------------------------


def test_git_stub_log_keeps_a_multiline_argument_in_one_record(tmp_path):
    """Regression guard: a git argument containing newlines must not split
    one invocation into several log records.

    `commit-tree -m "$MSG"` with a blank line and a DCO trailer is the exact
    shape a knowledge-commit block builds. Under newline-framed records this
    produced THREE entries for ONE invocation, a phantom
    'Signed-off-by: ...' entry in subcommands(), and an inflated
    len(argv_lines()) - with nothing to detect it. Records are now
    \\x1e-terminated and carry their own argc.

    Shell-independent: this exercises the stub itself, not a shell block."""
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    stub = git_fixture.install_git_stub(fixture)
    msg = "chore(knowledge): capture MEMORY.md\n\nSigned-off-by: A B <a@b.c>\n"

    tree = subprocess.run(
        ["git", "-C", str(fixture.repo_dir), "write-tree"],
        env=fixture.env,
        capture_output=True,
        text=True,
        check=True,
        timeout=GIT_TIMEOUT_SECONDS,
        stdin=subprocess.DEVNULL,
    ).stdout.strip()
    proc = subprocess.run(
        ["git", "-C", str(fixture.repo_dir), "commit-tree", tree, "-p", "HEAD", "-m", msg],
        env=fixture.env,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0, proc.stderr

    lines = stub.argv_lines()
    assert len(lines) == 2, f"expected exactly 2 recorded invocations, got {lines!r}"
    assert stub.subcommands() == ["write-tree", "commit-tree"], (
        f"no phantom entries permitted: {stub.subcommands()!r}"
    )
    commit_tree = lines[1]
    assert commit_tree[-1] == msg, (
        "the multi-line -m argument must round-trip byte-exact inside its "
        f"record, got {commit_tree[-1]!r}"
    )
    assert commit_tree == [
        "commit-tree",
        "-C",
        str(fixture.repo_dir),
        "commit-tree",
        tree,
        "-p",
        "HEAD",
        "-m",
        msg,
    ]


def test_git_stub_cannot_be_installed_twice(tmp_path):
    """A second install would resolve `git` to the first stub and recurse
    forever (observed: a hang until a 15s timeout, growing the argv log every
    iteration). It must raise instead - a fixture that hangs would burn the
    whole python-bin-tests job with no diagnostic."""
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    git_fixture.install_git_stub(fixture)
    with pytest.raises(AssertionError, match="recurse forever"):
        git_fixture.install_git_stub(fixture)
    # Also caught when the caller supplies a different bin_dir, where the
    # parent-directory comparison alone would not fire.
    with pytest.raises(AssertionError, match="recurse forever"):
        git_fixture.install_git_stub(fixture, bin_dir=tmp_path / "second-stub-bin")


@pytest.mark.parametrize("shell", SHELLS)
def test_git_stub_records_argv_and_delegates_to_real_git(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    stub = git_fixture.install_git_stub(fixture)

    result = _run_block(fixture, shell)
    _assert_completed(result)
    # Delegation actually happened: the block's commit and push both worked.
    assert _plain_field(result.stdout, "SMOKE_COMMIT") == "ok"
    assert _plain_field(result.stdout, "SMOKE_PUSH") == "ok", result.stderr

    lines = stub.argv_lines()
    assert len(lines) >= 12, f"expected >= 12 recorded git calls, got {len(lines)}"
    subs = set(stub.subcommands())
    for expected in ("remote", "fetch", "rev-parse", "check-ignore", "cat-file",
                     "diff-index", "add", "commit", "push"):
        assert expected in subs, f"{expected!r} missing from recorded subcommands {sorted(subs)}"
    # Full argv is recorded, not just the subcommand.
    push_line = [parts for parts in lines if parts[0] == "push"][0]
    assert push_line[1] == "-C" and push_line[2] == str(fixture.repo_dir), push_line
    assert f"HEAD:refs/heads/{fixture.branch_name}" in push_line


@pytest.mark.parametrize("shell", SHELLS)
def test_git_stub_forces_one_subcommand_while_others_still_work(tmp_path, shell):
    """Both directions: the SAME fixture shape reports MEMORY.md as
    'identical' with an unforced stub, and as 'modified' once `diff-index`
    alone is forced to exit 1 - while `commit` and `push` in the same block
    still succeed through the real git."""
    shell = _shell_or_skip(shell)
    # MEMORY.md identical, the other two genuinely modified - so the block has
    # real work to commit and push in BOTH arms, and the only difference
    # between them is diff-index's verdict on MEMORY.md.
    modes = {MEMORY: "identical", DECISIONS: "modified", LEARNINGS: "modified"}

    control_dir = tmp_path / "control"
    control_dir.mkdir()
    control = git_fixture.build_knowledge_consumer_shape(control_dir, modes)
    git_fixture.install_git_stub(control)
    control_result = _run_block(control, shell)
    _assert_completed(control_result)
    assert _file_state(control_result.stdout, MEMORY) == "identical"
    assert _plain_field(control_result.stdout, "SMOKE_STAGED") == "2"
    assert _plain_field(control_result.stdout, "SMOKE_PUSH") == "ok", control_result.stderr

    forced_dir = tmp_path / "forced"
    forced_dir.mkdir()
    forced = git_fixture.build_knowledge_consumer_shape(forced_dir, modes)
    stub = git_fixture.install_git_stub(forced, fail_subcommand="diff-index", fail_exit_code=1)
    forced_result = _run_block(forced, shell)
    _assert_completed(forced_result)
    assert _file_state(forced_result.stdout, MEMORY) == "modified +0 -0", forced_result.stdout
    assert _plain_field(forced_result.stdout, "SMOKE_STAGED") == "3"
    assert _plain_field(forced_result.stdout, "SMOKE_COMMIT") == "ok", (
        "commit must still reach the real git - only diff-index is forced"
    )
    assert _plain_field(forced_result.stdout, "SMOKE_PUSH") == "ok", forced_result.stderr
    assert stub.was_attempted("diff-index")
    assert "AE-GIT-STUB: forced failure for subcommand diff-index" in forced_result.stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_git_stub_can_force_push_to_a_chosen_exit_code(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_knowledge_consumer_shape(tmp_path)
    stub = git_fixture.install_git_stub(fixture, fail_subcommand="push", fail_exit_code=7)

    before = _git(fixture, "rev-parse", fixture.branch_name, cwd=fixture.origin_dir).stdout.strip()
    result = _run_block(fixture, shell)
    _assert_completed(result)
    assert _plain_field(result.stdout, "SMOKE_FETCH") == "ok", "fetch is untouched by the force"
    assert _plain_field(result.stdout, "SMOKE_COMMIT") == "ok"
    assert _plain_field(result.stdout, "SMOKE_PUSH") == "fail"
    assert stub.was_attempted("push")
    after = _git(fixture, "rev-parse", fixture.branch_name, cwd=fixture.origin_dir).stdout.strip()
    assert after == before, "the forced push must not have reached the real git"
