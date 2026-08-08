"""
Purpose: Builds hermetic, disposable git repo fixtures that reproduce the
         shapes of consumer/project state the shell blocks embedded in the
         methodology's markdown can run against. Two families live here:
         (a) the six Phase 8 commit-and-telemetry shapes
         (@harness:phase8-commit-and-telemetry in
         content/commands/ds-implement-ticket.md) - the DinoStack repo itself,
         an /ds-init-project-scaffolded consumer repo, a single-engineer
         worktree (WORKTREE_PATH-resolved PR checkout), a fan-out primary
         checkout, an unconfirmed-identity operator, and a confirmed identity
         with no git user.* config; and (b) four knowledge-commit shapes,
         which add a real bare `origin` remote plus seeded MEMORY.md /
         decisions.md / .agentic/learnings.md state so a block that commits
         and pushes knowledge files onto a PR branch can be exercised end to
         end (including a push that is rejected by the remote).

Public API: Fixture (dataclass: repo_dir, worktree_dir, branch_name,
            developer, env, origin_dir)
            GitStub (dataclass: bin_dir, log_path, fail_subcommand,
            fail_exit_code; .argv_lines(), .subcommands(), .was_attempted())
            build_dinostack_shape(tmp_path) -> Fixture
            build_consumer_shape(tmp_path) -> Fixture
            build_worktree_shape(tmp_path) -> Fixture
            build_fanout_shape(tmp_path) -> Fixture
            build_no_identity_shape(tmp_path) -> Fixture
            build_identity_no_gitconfig_shape(tmp_path) -> Fixture
            build_knowledge_consumer_shape(tmp_path, modes=None) -> Fixture
            build_knowledge_dinostack_shape(tmp_path) -> Fixture
            build_knowledge_no_remote_shape(tmp_path, modes=None) -> Fixture
            build_knowledge_push_reject_shape(tmp_path, modes=None) -> Fixture
            add_bare_origin(fixture) -> Path
            seed_knowledge_baseline(fixture, modes) -> None
            apply_knowledge_local(fixture, modes) -> None
            install_push_reject_hook(fixture, message=...) -> Path
            install_git_stub(fixture, fail_subcommand=None,
                             fail_exit_code=1) -> GitStub
            KNOWLEDGE_FILES, KNOWLEDGE_MODES, PUSH_REJECT_MESSAGE
            CONSUMER_GITIGNORE, DINOSTACK_GITIGNORE,
            DINOSTACK_KNOWLEDGE_GITIGNORE

Upstream deps: stdlib only (subprocess, dataclasses, pathlib, shutil).
               Shells out to the system `git` binary. Does not touch the
               developer's real $HOME, ~/.gitconfig, or /etc/gitconfig - every
               fixture pins HOME to a fixture-local temp dir,
               GIT_CONFIG_NOSYSTEM=1, and a fixture-local GIT_CONFIG_GLOBAL so
               no ambient git identity, init.defaultBranch, gpgsign setting,
               or ~/.nvm/nvm.sh (which would otherwise prepend to PATH ahead
               of the ds-identity stub dir) can leak in. The bare
               `origin` added by add_bare_origin() is a sibling directory on
               the same filesystem - still no network access.

Downstream consumers: bin/tests/test_phase8_telemetry_shell.py,
               bin/tests/test_qa_knowledge_capture_shell.py,
               bin/tests/test_knowledge_harness_smoke.py

Failure modes: builders raise via subprocess.CalledProcessError (check=True
               everywhere) if any setup git command fails - a broken fixture
               must not silently produce a misleading test result. No network
               access; every repo is git-init'd locally, never cloned.
               apply_knowledge_local() additionally asserts that each file's
               requested mode is consistent with whether that file is present
               at the branch tip, so a mis-specified fixture fails loudly
               rather than producing a shape the test then mis-describes. It
               also leaves every file it writes STAT-DIRTY on purpose (mtime
               skewed past the index's), so a block under test must
               `git update-index --refresh` before trusting
               `git diff-index --quiet` - see _write_file()'s docstring.
               install_git_stub() refuses a second install on the same
               fixture (it would delegate to the first stub and recurse
               forever), and GitStub.argv_lines() raises on a malformed
               record rather than returning a wrong invocation count.

Performance: standard; each builder does a handful of local git commands
             (~10-50ms) against a pytest tmp_path. The knowledge builders add
             a bare init plus a push/fetch round trip (still local).

Note on BRANCH_NAME: the six Phase 8 builders export BRANCH_NAME into
             Fixture.env because the Phase 8 harness passes it that way. The
             four knowledge builders deliberately do NOT - in production
             $BRANCH_NAME in those blocks is a conductor-substituted shell
             ASSIGNMENT, not an exported variable, so exporting it in a
             fixture would make an `awk ENVIRON["BRANCH_NAME"]` lookup resolve
             in test and empty in production. Inject it with
             md_shell_extract.with_shell_assignments() instead.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DUMMY_NAME = "AE Test Fixture"
DUMMY_EMAIL = "ae-fixture@example.invalid"

# The `.gitignore` block a fresh /ds-init-project-scaffolded consumer repo
# carries (content/commands/ds-init-project.md Step 9): a targeted denylist,
# NOT an umbrella. `.agentic/session-log/` is not ignored by anything in this
# block - it is tracked by default. Trimmed to the entries load-bearing for
# this harness; the full block also lists loop-state/tasks/events/etc, which
# are irrelevant here.
CONSUMER_GITIGNORE = """\
# Agentic engineering runtime artifacts (must not be committed).
.agentic/loop-state.json
.agentic/loop-state-*.json
.agentic/hud/
.agentic/tasks.jsonl
.agentic/events.jsonl
.agentic/context.md
.agentic/context.d/
.agentic/_wrap.md
.agentic/_foreign.md
.agentic/memory/
.agentic/memory.md
.agentic/wrap/
.agentic/preferences.json
.agentic/compression-state.json
.agentic/tracker.yml
.agentic/tracker-states.json
!.agentic/session-log/
!.agentic/learnings.md
!.agentic/qa.md
!.agentic/deploy.md
!.agentic/tracking.md
!.agentic/qa-regressions.md
!.agentic/config.json
"""

# DinoStack's own `.gitignore` (root .gitignore:28-30): a root-anchored
# umbrella that ignores the ENTIRE .agentic/ directory except team.yml -
# `.agentic/session-log/**` is ignored by this, unlike the consumer shape.
DINOSTACK_GITIGNORE = """\
/.agentic/*
!/.agentic/team.yml
"""

# The subset of DinoStack's own root `.gitignore` that governs all THREE
# knowledge files, not just the `.agentic/` umbrella. Verified verbatim
# against the live root .gitignore of this repo (the `/.agentic/*` +
# `!/.agentic/team.yml` pair, the `/decisions.md` rule, and the `/MEMORY.md`
# rule - interleaving comments omitted, rule ORDER preserved because git
# ignore matching is last-match-wins).
#
# Deliberately NOT a reuse of DINOSTACK_GITIGNORE above: that constant covers
# only `.agentic/`, so under it MEMORY.md and decisions.md would be TRACKABLE
# and a "DinoStack shape" fixture built from it would silently exercise the
# consumer path for two of the three knowledge files.
DINOSTACK_KNOWLEDGE_GITIGNORE = """\
/.agentic/*
!/.agentic/team.yml
/decisions.md
/MEMORY.md
"""

# The three knowledge files a knowledge-commit block operates on, in the order
# the methodology consistently names them.
KNOWLEDGE_FILES = ("MEMORY.md", "decisions.md", ".agentic/learnings.md")

# Per-file local-state modes accepted by seed_knowledge_baseline() /
# apply_knowledge_local(). Each is independently selectable per file.
#   "modified"    - tracked at the tip, local copy differs (extra line)
#   "identical"   - tracked at the tip, local copy byte-identical
#   "absent"      - NOT present at the tip at all; exists only locally
#   "fewer_lines" - tracked at the tip, local copy is a strict prefix (so a
#                   revert-guard has real deletions to detect)
KNOWLEDGE_MODES = ("modified", "identical", "absent", "fewer_lines")

# Emitted to stderr by the pre-receive hook installed by
# install_push_reject_hook(). Distinguishable from any real git error so a
# test can prove the push reached the remote and was rejected THERE, rather
# than failing earlier (e.g. an unreachable remote, which would also fail the
# preceding fetch).
PUSH_REJECT_MESSAGE = "AE-FIXTURE-PUSH-REJECTED"

# Framing for the git stub's argv log.
#
# Records are terminated by \x1e (RS) and fields separated by \x1f (US) -
# NEWLINE IS NOT A DELIMITER at either level. That is not a stylistic choice:
# git arguments routinely contain newlines (a `commit-tree -m "$MSG"` whose
# message carries a blank line and a DCO trailer is the canonical case), and
# newline-framed records split one such invocation into three, inflating
# len(argv_lines()) and injecting a phantom entry into subcommands() with
# nothing to detect it.
#
# Each record additionally carries its own argc as field 2, so a record that
# does get split - by an argument containing a literal \x1e, or by any future
# framing regression - fails the field-count check in
# GitStub.argv_lines() LOUDLY instead of being mis-parsed silently.
_ARGV_SEP = "\x1f"
_ARGV_RECORD_SEP = "\x1e"


@dataclass
class Fixture:
    repo_dir: Path
    worktree_dir: Optional[Path]
    branch_name: str
    developer: str
    env: dict[str, str]
    # Populated by add_bare_origin(); None means the fixture has no remote.
    origin_dir: Optional[Path] = None


@dataclass
class GitStub:
    """Handle for the tee-and-delegate `git` stub installed by
    install_git_stub(). The stub records every invocation's full argv then
    exec's the real git, so a long block's other git calls keep working while
    one chosen subcommand can be forced to a chosen exit code."""

    bin_dir: Path
    log_path: Path
    fail_subcommand: Optional[str] = None
    fail_exit_code: int = 1

    def argv_lines(self) -> list[list[str]]:
        """Every recorded invocation as [subcommand, *full_argv].

        Records are \\x1e-terminated and fields \\x1f-separated, so an argument
        containing newlines (a multi-line commit message, say) stays inside
        one record. The per-record argc is validated: a malformed record
        raises rather than silently yielding a wrong invocation count."""
        if not self.log_path.exists():
            return []
        raw = self.log_path.read_text(encoding="utf-8")
        out: list[list[str]] = []
        for record in raw.split(_ARGV_RECORD_SEP):
            if record == "":
                continue
            fields = record.split(_ARGV_SEP)
            if len(fields) < 2:
                raise AssertionError(
                    f"malformed git-stub record (expected at least "
                    f"subcommand + argc, got {fields!r}) in {self.log_path}"
                )
            subcommand, argc_field, args = fields[0], fields[1], fields[2:]
            try:
                argc = int(argc_field)
            except ValueError:
                raise AssertionError(
                    f"malformed git-stub record: argc field {argc_field!r} is "
                    f"not an integer, in record {record!r}"
                ) from None
            if len(args) != argc:
                raise AssertionError(
                    f"malformed git-stub record: argc says {argc} but {len(args)} "
                    f"argument fields are present - the log framing is broken "
                    f"(record: {record!r})"
                )
            out.append([subcommand, *args])
        return out

    def subcommands(self) -> list[str]:
        """The resolved subcommand of every recorded invocation, in order."""
        return [parts[0] for parts in self.argv_lines()]

    def was_attempted(self, subcommand: str) -> bool:
        return subcommand in self.subcommands()


# Every subprocess in this module is bounded and has stdin closed.
#
# timeout: an unbounded git call that stalls (a credential or terminal prompt,
# a hung hook) escalates into a killed CI job with no usable log. Bounded, it
# is one TimeoutExpired at the exact call site. 30s is ~1000x the observed
# runtime of any git command here.
#
# stdin=DEVNULL: a git that decides to prompt gets EOF and fails instead of
# waiting forever. pytest's own fd capture already points fd 0 at devnull, but
# that protection VANISHES under `-s` / `-p no:capture` - which is precisely
# how someone will run this suite while debugging the next stall.
_SUBPROCESS_TIMEOUT_SECONDS = 30


def _run(args: list[str], cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        stdin=subprocess.DEVNULL,
    )


def _base_env(tmp_path: Path, user_name: Optional[str], user_email: Optional[str]) -> dict[str, str]:
    """Every fixture's env: hermetic from the operator's real git identity and
    locale, so behavior does not depend on the machine running the tests."""
    global_gitconfig = tmp_path / ".empty-gitconfig"
    if user_name is not None and user_email is not None:
        global_gitconfig.write_text(
            f"[user]\n\tname = {user_name}\n\temail = {user_email}\n", encoding="utf-8"
        )
    else:
        global_gitconfig.write_text("", encoding="utf-8")

    fixture_home = tmp_path / ".fixture-home"
    fixture_home.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["HOME"] = str(fixture_home)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = str(global_gitconfig)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    # Never let git block on a prompt. GIT_CONFIG_NOSYSTEM=1 plus the
    # fixture-local GIT_CONFIG_GLOBAL already mean no credential or askpass
    # helper is inherited TODAY, but nothing asserted that and nothing would
    # catch a regression - and the failure mode is a subprocess that waits
    # forever, which is the most expensive kind. These four make a prompt
    # impossible rather than merely unreachable: a prompting git now fails
    # fast instead of hanging.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = ""
    env["SSH_ASKPASS"] = ""
    env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"
    # Drop any AUTHOR/COMMITTER identity inherited from the calling process
    # (e.g. this test suite's own CI commit env) unless a fixture opts back
    # in (build_identity_no_gitconfig_shape).
    for key in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "EMAIL",
    ):
        env.pop(key, None)
    return env


def _init_repo(path: Path, branch_name: str, env: dict[str, str]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", "-b", branch_name], cwd=path, env=env)
    (path / "README.md").write_text("fixture repo\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=path, env=env)
    commit_env = dict(env)
    commit_env["GIT_AUTHOR_NAME"] = DUMMY_NAME
    commit_env["GIT_AUTHOR_EMAIL"] = DUMMY_EMAIL
    commit_env["GIT_COMMITTER_NAME"] = DUMMY_NAME
    commit_env["GIT_COMMITTER_EMAIL"] = DUMMY_EMAIL
    _run(["git", "commit", "-q", "-m", "initial commit"], cwd=path, env=commit_env)


def _write_gitignore(path: Path, content: str, env: dict[str, str]) -> None:
    (path / ".gitignore").write_text(content, encoding="utf-8")
    _run(["git", "add", ".gitignore"], cwd=path, env=env)
    commit_env = dict(env)
    commit_env["GIT_AUTHOR_NAME"] = DUMMY_NAME
    commit_env["GIT_AUTHOR_EMAIL"] = DUMMY_EMAIL
    commit_env["GIT_COMMITTER_NAME"] = DUMMY_NAME
    commit_env["GIT_COMMITTER_EMAIL"] = DUMMY_EMAIL
    _run(["git", "commit", "-q", "-m", "add .gitignore"], cwd=path, env=commit_env)


def _seed_session_log(repo_dir: Path, developer: str) -> Path:
    log_dir = repo_dir / ".agentic" / "session-log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{developer}.jsonl"
    log_path.write_text(
        '{"ts":"2026-08-03T00:00:00Z","event":"session_total","tool_calls":1}\n',
        encoding="utf-8",
    )
    return log_path


def _stub_ds_identity(
    bin_dir: Path, env: dict[str, str], developer: Optional[str], provisional: bool = False
) -> None:
    """Install a PATH-shadowing fake `ds-identity` executable so the
    block's `ds-identity show` calls resolve deterministically without
    depending on this machine's real ~/.agentic/identity.yml."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "ds-identity"
    if developer is None:
        body = (
            "#!/bin/sh\n"
            'echo "No identity set. Run: ds-identity init <handle>"\n'
            "exit 0\n"
        )
    elif provisional:
        body = (
            "#!/bin/sh\n"
            f'echo "developer_id:  {developer}"\n'
            'echo "provisional:   true"\n'
            "exit 0\n"
        )
    else:
        body = "#!/bin/sh\n" f'echo "developer_id:  {developer}"\n' "exit 0\n"
    stub.write_text(body, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"


def build_dinostack_shape(tmp_path: Path) -> Fixture:
    """(i) DinoStack itself: `/.agentic/*` umbrella ignores session-log, so
    both the feature-commit `git add` and the telemetry `git add` hit the
    ignored-paths error and no-op. $REPO is on $BRANCH_NAME directly."""
    branch_name = "feature/harness-fixture-i"
    developer = "dev-dinostack"
    repo_dir = tmp_path / "repo"
    env = _base_env(tmp_path, DUMMY_NAME, DUMMY_EMAIL)
    _init_repo(repo_dir, branch_name, env)
    _write_gitignore(repo_dir, DINOSTACK_GITIGNORE, env)
    _seed_session_log(repo_dir, developer)
    _stub_ds_identity(tmp_path / "stub-bin", env, developer)
    env["REPO"] = str(repo_dir)
    env["BRANCH_NAME"] = branch_name
    env["WORKTREE_PATH"] = ""
    return Fixture(repo_dir, None, branch_name, developer, env)


def build_consumer_shape(tmp_path: Path) -> Fixture:
    """(ii) A /ds-init-project-scaffolded consumer repo: session-log is
    tracked (targeted denylist, no umbrella). $REPO stays on a non-target
    default branch; PR_CHECKOUT resolves via WORKTREE_PATH, mirroring the
    common single-engineer path. Correct positive path."""
    branch_name = "feature/harness-fixture-ii"
    developer = "dev-consumer"
    repo_dir = tmp_path / "repo"
    worktree_dir = tmp_path / "worktree"
    env = _base_env(tmp_path, DUMMY_NAME, DUMMY_EMAIL)
    _init_repo(repo_dir, "main", env)
    _write_gitignore(repo_dir, CONSUMER_GITIGNORE, env)
    _seed_session_log(repo_dir, developer)
    _run(["git", "worktree", "add", "-q", str(worktree_dir), "-b", branch_name], cwd=repo_dir, env=env)
    _stub_ds_identity(tmp_path / "stub-bin", env, developer)
    env["REPO"] = str(repo_dir)
    env["BRANCH_NAME"] = branch_name
    env["WORKTREE_PATH"] = str(worktree_dir)
    return Fixture(repo_dir, worktree_dir, branch_name, developer, env)


def build_worktree_shape(tmp_path: Path) -> Fixture:
    """(iii) Dedicated base fixture for the D1/D2 mutation tests. Same shape
    as (ii) (WORKTREE_PATH resolution, PR_CHECKOUT != REPO), except the
    destination session-log file inside worktree_dir MUST be absent before
    the block runs - the D2 mutant relies on `[ -f <dest> ]` being false
    pre-mkdir/cp so its inserted guard actually no-ops the block instead of
    passing through."""
    branch_name = "feature/harness-fixture-iii"
    developer = "dev-worktree"
    repo_dir = tmp_path / "repo"
    worktree_dir = tmp_path / "worktree"
    env = _base_env(tmp_path, DUMMY_NAME, DUMMY_EMAIL)
    _init_repo(repo_dir, "main", env)
    _write_gitignore(repo_dir, CONSUMER_GITIGNORE, env)
    _seed_session_log(repo_dir, developer)
    _run(["git", "worktree", "add", "-q", str(worktree_dir), "-b", branch_name], cwd=repo_dir, env=env)
    dest = worktree_dir / ".agentic" / "session-log" / f"{developer}.jsonl"
    assert not dest.exists(), (
        f"fixture invariant violated: {dest} must not exist before the "
        f"block runs (required for the D2 mutant to be a valid no-op test)"
    )
    _stub_ds_identity(tmp_path / "stub-bin", env, developer)
    env["REPO"] = str(repo_dir)
    env["BRANCH_NAME"] = branch_name
    env["WORKTREE_PATH"] = str(worktree_dir)
    return Fixture(repo_dir, worktree_dir, branch_name, developer, env)


def build_fanout_shape(tmp_path: Path) -> Fixture:
    """(iv) Fan-out primary checkout: $REPO is already checked out on
    $BRANCH_NAME (per the block's own comment: "Fan-out path: $REPO is on
    $FEATURE_BRANCH after the "Merge phase (all-done join)" checkout"), so
    PR_CHECKOUT resolves to $REPO directly with no WORKTREE_PATH involved.
    Correct positive path."""
    branch_name = "feature/harness-fixture-iv"
    developer = "dev-fanout"
    repo_dir = tmp_path / "repo"
    env = _base_env(tmp_path, DUMMY_NAME, DUMMY_EMAIL)
    _init_repo(repo_dir, branch_name, env)
    _write_gitignore(repo_dir, CONSUMER_GITIGNORE, env)
    _seed_session_log(repo_dir, developer)
    _stub_ds_identity(tmp_path / "stub-bin", env, developer)
    env["REPO"] = str(repo_dir)
    env["BRANCH_NAME"] = branch_name
    env["WORKTREE_PATH"] = ""
    return Fixture(repo_dir, None, branch_name, developer, env)


def build_no_identity_shape(tmp_path: Path) -> Fixture:
    """(v) Identity unconfirmed/absent: `ds-identity show` resolves no
    `developer_id:` line, so $DEVELOPER is empty and the
    `[ "$COMMIT_TELEMETRY" = "true" ] && [ -n "$DEVELOPER" ]` guard at :2284
    short-circuits - the telemetry block is never entered."""
    branch_name = "feature/harness-fixture-v"
    repo_dir = tmp_path / "repo"
    env = _base_env(tmp_path, DUMMY_NAME, DUMMY_EMAIL)
    _init_repo(repo_dir, branch_name, env)
    _write_gitignore(repo_dir, CONSUMER_GITIGNORE, env)
    # No session-log seeded - DEVELOPER never resolves, so SESSION_LOG_SRC is
    # never referenced (nothing to seed against).
    _stub_ds_identity(tmp_path / "stub-bin", env, developer=None)
    env["REPO"] = str(repo_dir)
    env["BRANCH_NAME"] = branch_name
    env["WORKTREE_PATH"] = ""
    return Fixture(repo_dir, None, branch_name, "", env)


def build_identity_no_gitconfig_shape(tmp_path: Path) -> Fixture:
    """(vi) D3 base fixture: confirmed developer identity, but NO
    `git config user.name`/`user.email` anywhere (no global, no repo-local).
    `git commit` still succeeds because GIT_AUTHOR_*/GIT_COMMITTER_*/EMAIL
    are set directly in the process env - but `SO_NAME`/`SO_EMAIL` (built
    exclusively from `git config user.name`/`user.email`) resolve empty, so
    the telemetry-commit block's DCO-identity guard fires and skips the
    telemetry commit instead of emitting the malformed `Signed-off-by:  <>`
    trailer (D3, fixed)."""
    branch_name = "feature/harness-fixture-vi"
    developer = "dev-no-gitconfig"
    repo_dir = tmp_path / "repo"
    # user_name/user_email=None -> empty global gitconfig (no [user] section).
    env = _base_env(tmp_path, None, None)
    env["GIT_AUTHOR_NAME"] = DUMMY_NAME
    env["GIT_AUTHOR_EMAIL"] = DUMMY_EMAIL
    env["GIT_COMMITTER_NAME"] = DUMMY_NAME
    env["GIT_COMMITTER_EMAIL"] = DUMMY_EMAIL
    env["EMAIL"] = DUMMY_EMAIL
    _init_repo(repo_dir, branch_name, env)
    _write_gitignore(repo_dir, CONSUMER_GITIGNORE, env)
    _seed_session_log(repo_dir, developer)
    _stub_ds_identity(tmp_path / "stub-bin", env, developer)
    env["REPO"] = str(repo_dir)
    env["BRANCH_NAME"] = branch_name
    env["WORKTREE_PATH"] = ""
    return Fixture(repo_dir, None, branch_name, developer, env)


# ---------------------------------------------------------------------------
# Knowledge-commit fixtures: bare origin, seeded knowledge files, git stub.
#
# These compose. add_bare_origin() / seed_knowledge_baseline() /
# apply_knowledge_local() / install_push_reject_hook() / install_git_stub()
# each take a Fixture and can be layered onto ANY builder above - including
# build_identity_no_gitconfig_shape() - rather than requiring a new builder
# per combination. The four build_knowledge_* builders below are the named
# combinations a knowledge-commit block needs; they are thin compositions of
# these primitives, not independent implementations.
# ---------------------------------------------------------------------------


def _commit_env(env: dict[str, str]) -> dict[str, str]:
    out = dict(env)
    out["GIT_AUTHOR_NAME"] = DUMMY_NAME
    out["GIT_AUTHOR_EMAIL"] = DUMMY_EMAIL
    out["GIT_COMMITTER_NAME"] = DUMMY_NAME
    out["GIT_COMMITTER_EMAIL"] = DUMMY_EMAIL
    return out


def _knowledge_baseline(rel_path: str) -> str:
    """Five-line baseline body. Multi-line so a "fewer lines" local variant is
    a strict prefix with real deletions for a revert-guard to detect."""
    return (
        f"# {rel_path}\n"
        f"baseline line 1 ({rel_path})\n"
        f"baseline line 2 ({rel_path})\n"
        f"baseline line 3 ({rel_path})\n"
        f"baseline line 4 ({rel_path})\n"
    )


def _knowledge_local(rel_path: str, mode: str) -> str:
    base = _knowledge_baseline(rel_path)
    if mode == "identical":
        return base
    if mode == "modified":
        return base + f"local-only edit ({rel_path})\n"
    if mode == "fewer_lines":
        return "".join(base.splitlines(keepends=True)[:2])
    if mode == "absent":
        # Present only locally, never at the tip - distinct content so a test
        # cannot confuse it with a tracked file's baseline.
        return f"# {rel_path}\nuntracked-at-tip local content ({rel_path})\n"
    raise ValueError(f"unknown knowledge mode {mode!r}; expected one of {KNOWLEDGE_MODES}")


def _normalize_modes(modes: Optional[dict[str, str]]) -> dict[str, str]:
    resolved = {rel: "modified" for rel in KNOWLEDGE_FILES}
    for rel, mode in (modes or {}).items():
        if rel not in KNOWLEDGE_FILES:
            raise ValueError(f"unknown knowledge file {rel!r}; expected one of {KNOWLEDGE_FILES}")
        if mode not in KNOWLEDGE_MODES:
            raise ValueError(f"unknown knowledge mode {mode!r}; expected one of {KNOWLEDGE_MODES}")
        resolved[rel] = mode
    return resolved


# Seconds to push a written file's mtime past the index's recorded mtime. Any
# value > 1 works; the point is to leave git's "racily clean" window (an entry
# whose mtime is within the same second as the index write is re-checked by
# CONTENT, outside it git trusts the stat data alone).
_STAT_DIRTY_SKEW_SECONDS = 10


def _write_file(
    repo_dir: Path, rel_path: str, content: str, stat_dirty: bool = False
) -> Path:
    """Write content to repo_dir/rel_path.

    With stat_dirty=True the file's mtime is pushed clearly past the index's,
    which makes `git diff-index --quiet HEAD` report the file as CHANGED even
    when its content is byte-identical - git compares stat data, not content,
    for entries outside the racily-clean window (`git diff-index` docs: with
    --quiet it "may return 1 for a file that has not actually changed"; run
    `git update-index --refresh` first).

    This is deliberately NOT hidden. Without the skew the behavior is a
    genuine RACE - identical-content files were classified "identical" ~70% of
    runs and "modified" ~30% here, purely on whether the write landed in the
    same second as the index write. Forcing the skew makes the harder branch
    the ONLY branch, so a block that omits the index refresh fails every time
    instead of one run in three. Production has the same exposure: a knowledge
    writer that rewrites a file with unchanged content leaves exactly this
    state."""
    path = repo_dir / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if stat_dirty:
        stamp = path.stat().st_mtime + _STAT_DIRTY_SKEW_SECONDS
        os.utime(path, (stamp, stamp))
    return path


def _is_tracked_at_head(repo_dir: Path, rel_path: str, env: dict[str, str]) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "cat-file", "-e", f"HEAD:{rel_path}"],
        env=env,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        stdin=subprocess.DEVNULL,
    )
    return result.returncode == 0


def seed_knowledge_baseline(fixture: Fixture, modes: Optional[dict[str, str]] = None) -> None:
    """Commit the BASELINE version of every knowledge file whose mode is not
    "absent". Must run BEFORE add_bare_origin() so the push carries it - that
    ordering is what makes an "identical to the tip" local file possible."""
    resolved = _normalize_modes(modes)
    staged = False
    for rel_path in KNOWLEDGE_FILES:
        if resolved[rel_path] == "absent":
            continue
        _write_file(fixture.repo_dir, rel_path, _knowledge_baseline(rel_path))
        _run(["git", "add", "--", rel_path], cwd=fixture.repo_dir, env=fixture.env)
        staged = True
    if staged:
        _run(
            ["git", "commit", "-q", "-m", "seed knowledge baseline"],
            cwd=fixture.repo_dir,
            env=_commit_env(fixture.env),
        )


def apply_knowledge_local(fixture: Fixture, modes: Optional[dict[str, str]] = None) -> None:
    """Overwrite each knowledge file on disk with its per-mode LOCAL variant.

    Fails closed: a mode that claims the file is tracked at the tip when it is
    not (or vice versa) raises, so a fixture can never quietly produce a shape
    different from the one the test describes."""
    resolved = _normalize_modes(modes)
    for rel_path in KNOWLEDGE_FILES:
        mode = resolved[rel_path]
        tracked = _is_tracked_at_head(fixture.repo_dir, rel_path, fixture.env)
        if mode == "absent" and tracked:
            raise AssertionError(
                f"fixture invariant violated: {rel_path} is mode 'absent' but IS "
                f"present at the branch tip - pass the same modes dict to "
                f"seed_knowledge_baseline()"
            )
        if mode != "absent" and not tracked:
            raise AssertionError(
                f"fixture invariant violated: {rel_path} is mode {mode!r} but is "
                f"NOT present at the branch tip - call seed_knowledge_baseline() "
                f"with the same modes dict before apply_knowledge_local()"
            )
        _write_file(
            fixture.repo_dir, rel_path, _knowledge_local(rel_path, mode), stat_dirty=True
        )


def add_bare_origin(fixture: Fixture) -> Path:
    """Give the fixture a real remote: a sibling bare repo, `origin` pointing
    at it, the fixture branch pushed with upstream tracking, and a completed
    fetch (so `origin/<branch>` resolves). Returns the bare repo path and
    records it on fixture.origin_dir. Hermeticity is preserved - the bare repo
    is a sibling directory under the same tmp_path and inherits the fixture's
    GIT_CONFIG_NOSYSTEM / GIT_CONFIG_GLOBAL / LC_ALL env; no network."""
    origin_dir = fixture.repo_dir.parent / "origin.git"
    _run(
        ["git", "init", "-q", "--bare", "-b", fixture.branch_name, str(origin_dir)],
        cwd=fixture.repo_dir.parent,
        env=fixture.env,
    )
    _run(["git", "remote", "add", "origin", str(origin_dir)], cwd=fixture.repo_dir, env=fixture.env)
    _run(
        ["git", "push", "-q", "-u", "origin", fixture.branch_name],
        cwd=fixture.repo_dir,
        env=_commit_env(fixture.env),
    )
    _run(["git", "fetch", "-q", "origin"], cwd=fixture.repo_dir, env=fixture.env)
    fixture.origin_dir = origin_dir
    return origin_dir


def install_push_reject_hook(fixture: Fixture, message: str = PUSH_REJECT_MESSAGE) -> Path:
    """Install a `pre-receive` hook on the fixture's bare origin that writes
    `message` to stderr and exits 1.

    This construction is deliberate. A "repoint origin at a broken path"
    variant does NOT work for testing a push-rejection branch: `git fetch`
    against a nonexistent remote fails FIRST, so a block that fetches before
    it pushes never reaches its push. With a pre-receive hook, fetch and
    `rev-parse origin/<branch>` both still succeed and only the push fails -
    which is the shape a real protected-branch / server-hook rejection has.

    CAVEAT (measured, not assumed): the hook only fires when the push actually
    carries a ref update. A no-op push short-circuits client-side with
    "Everything up-to-date" and exit 0, never contacting the hook. So a test
    that wants to observe the rejection must push something new - a fresh
    commit, or a throwaway ref."""
    if fixture.origin_dir is None:
        raise AssertionError("install_push_reject_hook() requires add_bare_origin() first")
    hook = fixture.origin_dir / "hooks" / "pre-receive"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        "#!/bin/sh\n"
        "# Fixture hook: reject every push (bin/tests/lib/git_fixture.py).\n"
        f'echo "{message}" >&2\n'
        "exit 1\n",
        encoding="utf-8",
    )
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return hook


# Body of the tee-and-delegate `git` stub. Kept as a module-level template so
# the shell is readable as shell instead of as escaped Python string
# concatenation. Substituted fields are quoted by install_git_stub().
_GIT_STUB_TEMPLATE = r"""#!/bin/sh
# Tee-and-delegate git stub, installed by bin/tests/lib/git_fixture.py.
# Records this invocation's full argv, then exec's the REAL git binary.
AE_STUB_LOG='__LOG__'
AE_STUB_REAL_GIT='__REAL_GIT__'
AE_STUB_FAIL_SUBCMD='__FAIL_SUBCMD__'
AE_STUB_FAIL_CODE='__FAIL_CODE__'

# Resolve the SUBCOMMAND by skipping git's global options. A naive "$1" would
# report "-C" for every `git -C "$REPO" ...` call, which is how the blocks
# under test invoke git.
sub=''
skip=0
for a in "$@"; do
  if [ "$skip" = 1 ]; then skip=0; continue; fi
  case "$a" in
    -C|-c|--git-dir|--work-tree|--namespace|--exec-path|--super-prefix) skip=1 ;;
    --*=*) ;;
    -*) ;;
    *) sub="$a"; break ;;
  esac
done

# ONE record per invocation, written with ONE append (never a sequence of
# printf calls sharing a redirect, which two concurrent stub processes could
# interleave).
#
# The record is \037-separated and \036-TERMINATED. Newline is deliberately
# NOT a delimiter: git arguments contain newlines (`commit-tree -m "$MSG"`
# with a blank line and a DCO trailer), and newline framing would split one
# invocation into several records that the reader cannot tell apart from
# several invocations. argc ($#) is recorded as field 2 so the reader can
# detect any record that did get split.
AE_STUB_US=$(printf '\037')
AE_STUB_RS=$(printf '\036')
line="$sub$AE_STUB_US$#"
for a in "$@"; do line="$line$AE_STUB_US$a"; done
printf '%s%s' "$line" "$AE_STUB_RS" >> "$AE_STUB_LOG"

if [ -n "$AE_STUB_FAIL_SUBCMD" ] && [ "$sub" = "$AE_STUB_FAIL_SUBCMD" ]; then
  printf 'AE-GIT-STUB: forced failure for subcommand %s (exit %s)\n' \
    "$sub" "$AE_STUB_FAIL_CODE" >&2
  exit "$AE_STUB_FAIL_CODE"
fi
exec "$AE_STUB_REAL_GIT" "$@"
"""


_GIT_STUB_FINGERPRINT = "AE_STUB_REAL_GIT="


def _is_git_stub(path: Path) -> bool:
    """True when path is one of this module's git stubs (not the real git
    binary), detected by a marker in its text. Binary git reads as bytes that
    fail to decode, which is the False case."""
    try:
        return _GIT_STUB_FINGERPRINT in path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False


def install_git_stub(
    fixture: Fixture,
    fail_subcommand: Optional[str] = None,
    fail_exit_code: int = 1,
    bin_dir: Optional[Path] = None,
) -> GitStub:
    """PATH-shadow `git` with a tee-and-delegate stub: it records the full
    argv of every invocation, then `exec`s the REAL git binary (resolved to an
    absolute path at install time, so there is no recursion). Optionally
    forces one chosen subcommand to a chosen exit code while every other git
    call in the block still works - which is what lets a long block be driven
    down one specific failure branch, and what lets a test prove a command was
    never ATTEMPTED (GitStub.was_attempted)."""
    real_git = shutil.which("git", path=fixture.env.get("PATH", os.environ.get("PATH", "")))
    if real_git is None:
        raise AssertionError("no real `git` on PATH for the stub to delegate to")
    real_git = str(Path(real_git).resolve())

    bin_dir = bin_dir or (fixture.repo_dir.parent / "git-stub-bin")
    bin_dir.mkdir(parents=True, exist_ok=True)

    # Fail closed on a SECOND install against the same fixture. The first
    # install prepends its bin_dir to fixture.env["PATH"], so `git` now
    # resolves to the stub - a second install would write
    # AE_STUB_REAL_GIT='<stub>' into the stub and every git call would recurse
    # forever. Observed: a hang until a 15s test timeout, appending to the
    # argv log on every iteration. Checked two ways because a caller-supplied
    # bin_dir defeats the path comparison on its own.
    if Path(real_git).parent == bin_dir or _is_git_stub(Path(real_git)):
        raise AssertionError(
            f"install_git_stub() would delegate to another stub ({real_git}) "
            f"and recurse forever - it has already been installed on this "
            f"fixture. Install it once; pass fail_subcommand on that call, or "
            f"build a second fixture."
        )
    log_path = bin_dir / "argv.log"
    log_path.write_text("", encoding="utf-8")

    for value, label in ((str(log_path), "log path"), (real_git, "git path")):
        if "'" in value:
            raise AssertionError(f"{label} contains a single quote, which would break the stub")
    if fail_subcommand is not None and "'" in fail_subcommand:
        raise AssertionError("fail_subcommand contains a single quote")

    stub = bin_dir / "git"
    stub.write_text(
        _GIT_STUB_TEMPLATE.replace("__LOG__", str(log_path))
        .replace("__REAL_GIT__", real_git)
        .replace("__FAIL_SUBCMD__", fail_subcommand or "")
        .replace("__FAIL_CODE__", str(fail_exit_code)),
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    fixture.env["PATH"] = f"{bin_dir}{os.pathsep}{fixture.env['PATH']}"
    return GitStub(bin_dir, log_path, fail_subcommand, fail_exit_code)


def _knowledge_env(fixture_env: dict[str, str], repo_dir: Path) -> None:
    """Populate the env a knowledge-commit block reads. BRANCH_NAME is
    deliberately ABSENT - see the module manifest's "Note on BRANCH_NAME"."""
    fixture_env["REPO"] = str(repo_dir)
    fixture_env["WORKTREE_PATH"] = ""
    fixture_env.pop("BRANCH_NAME", None)


def _build_knowledge_base(
    tmp_path: Path, branch_name: str, developer: str, gitignore: str
) -> Fixture:
    repo_dir = tmp_path / "repo"
    env = _base_env(tmp_path, DUMMY_NAME, DUMMY_EMAIL)
    _init_repo(repo_dir, branch_name, env)
    _write_gitignore(repo_dir, gitignore, env)
    _stub_ds_identity(tmp_path / "stub-bin", env, developer)
    _knowledge_env(env, repo_dir)
    return Fixture(repo_dir, None, branch_name, developer, env)


def build_knowledge_consumer_shape(
    tmp_path: Path, modes: Optional[dict[str, str]] = None
) -> Fixture:
    """(A) Consumer repo: all three knowledge files are TRACKABLE under the
    /ds-init-project gitignore, a real bare `origin` exists, and each file is
    seeded at the tip then locally varied per `modes` (default: all
    "modified"). The positive path for a knowledge-commit block."""
    resolved = _normalize_modes(modes)
    fixture = _build_knowledge_base(
        tmp_path, "feature/harness-knowledge-a", "dev-knowledge", CONSUMER_GITIGNORE
    )
    seed_knowledge_baseline(fixture, resolved)
    add_bare_origin(fixture)
    apply_knowledge_local(fixture, resolved)
    return fixture


def build_knowledge_dinostack_shape(tmp_path: Path) -> Fixture:
    """(B) DinoStack itself: all three knowledge files exist on disk and ALL
    THREE are gitignored, so nothing is committable. Uses
    DINOSTACK_KNOWLEDGE_GITIGNORE, not DINOSTACK_GITIGNORE - the latter
    ignores only `.agentic/`, which would leave MEMORY.md and decisions.md
    trackable and silently make this the consumer shape for two of three."""
    fixture = _build_knowledge_base(
        tmp_path,
        "feature/harness-knowledge-b",
        "dev-knowledge-dinostack",
        DINOSTACK_KNOWLEDGE_GITIGNORE,
    )
    add_bare_origin(fixture)
    for rel_path in KNOWLEDGE_FILES:
        _write_file(fixture.repo_dir, rel_path, _knowledge_local(rel_path, "absent"))
        result = subprocess.run(
            ["git", "-C", str(fixture.repo_dir), "check-ignore", "-q", "--", rel_path],
            env=fixture.env,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"fixture invariant violated: {rel_path} is NOT ignored under "
                f"DINOSTACK_KNOWLEDGE_GITIGNORE (git check-ignore rc="
                f"{result.returncode}) - this shape requires all three ignored"
            )
    return fixture


def build_knowledge_no_remote_shape(
    tmp_path: Path, modes: Optional[dict[str, str]] = None
) -> Fixture:
    """(C) Consumer gitignore, knowledge files seeded and locally varied, but
    NO remote at all - `git remote get-url origin` fails, so a block's push
    path must never be reached."""
    resolved = _normalize_modes(modes)
    fixture = _build_knowledge_base(
        tmp_path,
        "feature/harness-knowledge-c",
        "dev-knowledge-no-remote",
        CONSUMER_GITIGNORE,
    )
    seed_knowledge_baseline(fixture, resolved)
    apply_knowledge_local(fixture, resolved)
    return fixture


def build_knowledge_push_reject_shape(
    tmp_path: Path, modes: Optional[dict[str, str]] = None
) -> Fixture:
    """(D) Same as (A) plus a `pre-receive` hook on the bare origin that exits
    1 - fetch and `rev-parse origin/<branch>` still succeed, only the push
    fails. See install_push_reject_hook() for why the "broken remote path"
    variant does not work here."""
    resolved = _normalize_modes(modes)
    fixture = _build_knowledge_base(
        tmp_path,
        "feature/harness-knowledge-d",
        "dev-knowledge-reject",
        CONSUMER_GITIGNORE,
    )
    seed_knowledge_baseline(fixture, resolved)
    add_bare_origin(fixture)
    install_push_reject_hook(fixture)
    apply_knowledge_local(fixture, resolved)
    return fixture
