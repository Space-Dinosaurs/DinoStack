"""
Purpose: Builds hermetic, disposable git repo fixtures that reproduce the six
         shapes of consumer/project state the Phase 8 commit-and-telemetry
         shell block (content/commands/ds-implement-ticket.md:2249-2346) can
         run against: the DinoStack repo itself, an /ds-init-project-scaffolded
         consumer repo, a fan-out engineer worktree, a fan-out primary
         checkout, an unconfirmed-identity operator, and a confirmed identity
         with no git user.* config. Built for
         bin/tests/test_phase8_telemetry_shell.py.

Public API: Fixture (dataclass: repo_dir, worktree_dir, branch_name,
            developer, env)
            build_dinostack_shape(tmp_path) -> Fixture
            build_consumer_shape(tmp_path) -> Fixture
            build_worktree_shape(tmp_path) -> Fixture
            build_fanout_shape(tmp_path) -> Fixture
            build_no_identity_shape(tmp_path) -> Fixture
            build_identity_no_gitconfig_shape(tmp_path) -> Fixture

Upstream deps: stdlib only (subprocess, dataclasses, pathlib). Shells out to
               the system `git` binary. Does not touch the developer's real
               $HOME, ~/.gitconfig, or /etc/gitconfig - every fixture pins
               GIT_CONFIG_NOSYSTEM=1 and a fixture-local GIT_CONFIG_GLOBAL so
               no ambient git identity, init.defaultBranch, or gpgsign setting
               can leak in.

Downstream consumers: bin/tests/test_phase8_telemetry_shell.py

Failure modes: builders raise via subprocess.CalledProcessError (check=True
               everywhere) if any setup git command fails - a broken fixture
               must not silently produce a misleading test result. No network
               access; every repo is git-init'd locally, never cloned.

Performance: standard; each builder does a handful of local git commands
             (~10-50ms) against a pytest tmp_path.
"""
from __future__ import annotations

import os
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


@dataclass
class Fixture:
    repo_dir: Path
    worktree_dir: Optional[Path]
    branch_name: str
    developer: str
    env: dict[str, str]


def _run(args: list[str], cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(args, cwd=str(cwd), env=env, check=True, capture_output=True, text=True)


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

    env = dict(os.environ)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = str(global_gitconfig)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
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


def _stub_agentic_identity(
    bin_dir: Path, env: dict[str, str], developer: Optional[str], provisional: bool = False
) -> None:
    """Install a PATH-shadowing fake `agentic-identity` executable so the
    block's `agentic-identity show` calls resolve deterministically without
    depending on this machine's real ~/.agentic/identity.yml."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "agentic-identity"
    if developer is None:
        body = (
            "#!/bin/sh\n"
            'echo "No identity set. Run: agentic-identity init <handle>"\n'
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
    _stub_agentic_identity(tmp_path / "stub-bin", env, developer)
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
    _stub_agentic_identity(tmp_path / "stub-bin", env, developer)
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
    _stub_agentic_identity(tmp_path / "stub-bin", env, developer)
    env["REPO"] = str(repo_dir)
    env["BRANCH_NAME"] = branch_name
    env["WORKTREE_PATH"] = str(worktree_dir)
    return Fixture(repo_dir, worktree_dir, branch_name, developer, env)


def build_fanout_shape(tmp_path: Path) -> Fixture:
    """(iv) Fan-out primary checkout: $REPO is already checked out on
    $BRANCH_NAME (per the block's own comment: "Fan-out path: $REPO is on
    $FEATURE_BRANCH after the line-977 checkout"), so PR_CHECKOUT resolves
    to $REPO directly with no WORKTREE_PATH involved. Correct positive path."""
    branch_name = "feature/harness-fixture-iv"
    developer = "dev-fanout"
    repo_dir = tmp_path / "repo"
    env = _base_env(tmp_path, DUMMY_NAME, DUMMY_EMAIL)
    _init_repo(repo_dir, branch_name, env)
    _write_gitignore(repo_dir, CONSUMER_GITIGNORE, env)
    _seed_session_log(repo_dir, developer)
    _stub_agentic_identity(tmp_path / "stub-bin", env, developer)
    env["REPO"] = str(repo_dir)
    env["BRANCH_NAME"] = branch_name
    env["WORKTREE_PATH"] = ""
    return Fixture(repo_dir, None, branch_name, developer, env)


def build_no_identity_shape(tmp_path: Path) -> Fixture:
    """(v) Identity unconfirmed/absent: `agentic-identity show` resolves no
    `developer_id:` line, so $DEVELOPER is empty and the
    `[ "$COMMIT_TELEMETRY" = "true" ] && [ -n "$DEVELOPER" ]` guard at :2283
    short-circuits - the telemetry block is never entered."""
    branch_name = "feature/harness-fixture-v"
    repo_dir = tmp_path / "repo"
    env = _base_env(tmp_path, DUMMY_NAME, DUMMY_EMAIL)
    _init_repo(repo_dir, branch_name, env)
    _write_gitignore(repo_dir, CONSUMER_GITIGNORE, env)
    # No session-log seeded - DEVELOPER never resolves, so SESSION_LOG_SRC is
    # never referenced (nothing to seed against).
    _stub_agentic_identity(tmp_path / "stub-bin", env, developer=None)
    env["REPO"] = str(repo_dir)
    env["BRANCH_NAME"] = branch_name
    env["WORKTREE_PATH"] = ""
    return Fixture(repo_dir, None, branch_name, "", env)


def build_identity_no_gitconfig_shape(tmp_path: Path) -> Fixture:
    """(vi) D3 base fixture: confirmed developer identity, but NO
    `git config user.name`/`user.email` anywhere (no global, no repo-local).
    `git commit` still succeeds because GIT_AUTHOR_*/GIT_COMMITTER_*/EMAIL
    are set directly in the process env - but `SO_NAME`/`SO_EMAIL` (built
    exclusively from `git config user.name`/`user.email`, :2261-2262) resolve
    empty, so the telemetry trailer lands as the malformed
    `Signed-off-by:  <>` (D3, live on main today)."""
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
    _stub_agentic_identity(tmp_path / "stub-bin", env, developer)
    env["REPO"] = str(repo_dir)
    env["BRANCH_NAME"] = branch_name
    env["WORKTREE_PATH"] = ""
    return Fixture(repo_dir, None, branch_name, developer, env)
