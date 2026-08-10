#!/usr/bin/env python3
"""
Regression tests for bin/ds-learning-shard (DS-154 Unit A).

Coverage:
  1. append writes a well-formed JSONL line: CLI-owned id/ts present, every
     caller-supplied field preserved verbatim.
  2. description over 500 chars is TRUNCATED, not rejected.
  3. the 5-entry-per-shard cap: the 6th append exits 0, prints to stderr, and
     adds no line.
  4. rollup emits entries then marks them; a second rollup emits [] (idempotency).
  5. rollup against an absent store emits [] and exits 0.
  6. two --repo paths with the SAME directory basename produce DIFFERENT
     repo-keys - the regression guard against the bare-basename slug trap.
  7. symlink invocation through a real os.symlink in a subprocess - the only way
     to exercise the bin/_lib PATH-symlink resolution bug (in-process import
     never hits it).
  8. rollup and list emit a parseable "[]" on the soft-fail path, not empty
     stdout with exit 0 (which crashes any consumer doing json.loads(stdout)).
  9. a linked git worktree and its primary checkout produce the SAME repo-key,
     so an isolation-worktree engineer's appends are visible to a conductor
     rolling up from the primary checkout.
 10. rollup bookkeeping is keyed on the CLI-owned uuid4 entry id, never on a
     count or a position. A positional index into parsed rows loses an
     un-rolled entry the moment an ALREADY-rolled line stops parsing (every
     later row shifts down one), and has a mirror image in the other direction
     as well. The id-set tests cover corruption in both directions, duplicate
     rows, reordered rows, an unknown/legacy count-shaped state record, and
     the bound on the id set itself.

Every subprocess runs under a fake $HOME so the developer's real
~/.agentic/learnings-shards store is never touched.

Run with: python3 -m pytest bin/tests/test_ds_learning_shard.py -x
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_BIN = Path(__file__).resolve().parent.parent
CLI = REPO_BIN / "ds-learning-shard"


def _load_module():
    """Load bin/ds-learning-shard as a module (extension-less executable)."""
    loader = importlib.machinery.SourceFileLoader("ds_learning_shard", str(CLI))
    spec = importlib.util.spec_from_loader("ds_learning_shard", loader)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    loader.exec_module(module)
    return module


def run(home: Path, *args: str, cli: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(cli or CLI), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def append(home: Path, repo: Path, session: str, **over: str) -> subprocess.CompletedProcess:
    fields = {
        "--agent-id": "agent-abc123",
        "--role": "engineer",
        "--event-type": "gotcha",
        "--domain-tag": "git",
        "--description": "worktree branch leaked into the conductor checkout",
        "--resolution": "verify git branch --show-current after every spawn",
    }
    fields.update(over)
    argv: list[str] = ["append", "--repo", str(repo), "--session-key", session]
    for key, value in fields.items():
        argv += [key, value]
    return run(home, *argv)


def store_dir(home: Path) -> Path:
    return home / ".agentic" / "learnings-shards"


def read_entries(home: Path, repo: Path, session: str) -> list[dict]:
    proc = run(home, "list", "--repo", str(repo), "--session-key", session)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture()
def env(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "proj" / "DinoStack"
    repo.mkdir(parents=True)
    return home, repo


# --- 1. well-formed append ------------------------------------------------


def test_append_writes_well_formed_line(env):
    home, repo = env
    proc = append(home, repo, "sess-1")
    assert proc.returncode == 0, proc.stderr

    entries = read_entries(home, repo, "sess-1")
    assert len(entries) == 1
    row = entries[0]

    # CLI-owned fields present and non-empty.
    assert row["id"] and len(row["id"]) == 36
    assert row["ts"].endswith("Z") and row["ts"][4] == "-"

    # Caller-supplied fields preserved verbatim.
    assert row["session_key"] == "sess-1"
    assert row["agent_id"] == "agent-abc123"
    assert row["role"] == "engineer"
    assert row["event_type"] == "gotcha"
    assert row["domain_tag"] == "git"
    assert row["description"] == "worktree branch leaked into the conductor checkout"
    assert row["resolution"] == "verify git branch --show-current after every spawn"

    # Store lives under HOME, outside the repo.
    assert store_dir(home).is_dir()
    assert not (repo / ".agentic").exists()


def test_caller_supplied_id_and_ts_are_ignored():
    """id/ts are CLI-owned; there is no CLI surface to set them."""
    module = _load_module()
    parser = module.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["append", "--repo", ".", "--session-key", "s", "--id", "x"])


def test_resolution_is_optional(env):
    home, repo = env
    argv = [
        "append", "--repo", str(repo), "--session-key", "sess-nores",
        "--agent-id", "a", "--role", "engineer", "--event-type", "decision",
        "--domain-tag", "ci", "--description", "chose squash merge",
    ]
    proc = run(home, *argv)
    assert proc.returncode == 0, proc.stderr
    assert read_entries(home, repo, "sess-nores")[0]["resolution"] is None


# --- 2. description truncation -------------------------------------------


def test_long_description_is_truncated_not_rejected(env):
    home, repo = env
    long_text = "x" * 900
    proc = append(home, repo, "sess-long", **{"--description": long_text})
    assert proc.returncode == 0, proc.stderr

    entries = read_entries(home, repo, "sess-long")
    assert len(entries) == 1, "over-long description must be stored, not rejected"
    assert len(entries[0]["description"]) == 500
    assert entries[0]["description"] == "x" * 500


def test_description_at_limit_is_untouched(env):
    home, repo = env
    exact = "y" * 500
    append(home, repo, "sess-exact", **{"--description": exact})
    assert read_entries(home, repo, "sess-exact")[0]["description"] == exact


# --- 3. per-shard cap -----------------------------------------------------


def test_cap_five_entries_sixth_is_dropped_softly(env):
    home, repo = env
    for i in range(5):
        proc = append(home, repo, "sess-cap", **{"--domain-tag": f"tag{i}"})
        assert proc.returncode == 0, proc.stderr
    assert len(read_entries(home, repo, "sess-cap")) == 5

    sixth = append(home, repo, "sess-cap", **{"--domain-tag": "overflow"})
    assert sixth.returncode == 0, "over-cap append must never block the caller"
    assert "cap reached, entry dropped" in sixth.stderr

    entries = read_entries(home, repo, "sess-cap")
    assert len(entries) == 5, "6th append must not add a line"
    assert all(row["domain_tag"] != "overflow" for row in entries)


def test_cap_is_per_session_not_per_repo(env):
    home, repo = env
    for i in range(5):
        append(home, repo, "sess-a", **{"--domain-tag": f"a{i}"})
    proc = append(home, repo, "sess-b", **{"--domain-tag": "b0"})
    assert proc.returncode == 0
    assert "cap reached" not in proc.stderr
    assert len(read_entries(home, repo, "sess-b")) == 1


# --- 4. rollup + idempotency ---------------------------------------------


def test_rollup_emits_then_marks_and_is_idempotent(env):
    home, repo = env
    append(home, repo, "sess-r1", **{"--domain-tag": "one"})
    append(home, repo, "sess-r2", **{"--domain-tag": "two"})

    first = run(home, "rollup", "--repo", str(repo))
    assert first.returncode == 0, first.stderr
    emitted = json.loads(first.stdout)
    assert len(emitted) == 2
    assert {row["domain_tag"] for row in emitted} == {"one", "two"}
    # Raw entries, verbatim - no classification field added by the CLI.
    assert set(emitted[0]) == {
        "id", "ts", "session_key", "agent_id", "role",
        "event_type", "domain_tag", "description", "resolution",
    }

    second = run(home, "rollup", "--repo", str(repo))
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout) == [], "second rollup must emit []"

    # Entries themselves are not deleted; only the bookkeeping advanced.
    assert len(read_entries(home, repo, "sess-r1")) == 1


def test_rollup_session_scoped(env):
    home, repo = env
    append(home, repo, "sess-x", **{"--domain-tag": "x"})
    append(home, repo, "sess-y", **{"--domain-tag": "y"})

    scoped = run(home, "rollup", "--repo", str(repo), "--session-key", "sess-x")
    emitted = json.loads(scoped.stdout)
    assert [row["domain_tag"] for row in emitted] == ["x"]

    rest = run(home, "rollup", "--repo", str(repo))
    assert [row["domain_tag"] for row in json.loads(rest.stdout)] == ["y"]


def test_rollup_picks_up_entries_appended_after_a_rollup(env):
    home, repo = env
    append(home, repo, "sess-late", **{"--domain-tag": "first"})
    run(home, "rollup", "--repo", str(repo))
    append(home, repo, "sess-late", **{"--domain-tag": "second"})

    proc = run(home, "rollup", "--repo", str(repo))
    emitted = json.loads(proc.stdout)
    assert [row["domain_tag"] for row in emitted] == ["second"]


# --- 5. absent store ------------------------------------------------------


def test_rollup_absent_store_emits_empty_array(env):
    home, repo = env
    assert not store_dir(home).exists()
    proc = run(home, "rollup", "--repo", str(repo))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []
    assert not store_dir(home).exists(), "rollup must not create the store"


def test_list_absent_store_emits_empty_array(env):
    home, repo = env
    proc = run(home, "list", "--repo", str(repo))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []


def test_rollup_absent_session_shard_emits_empty_array(env):
    home, repo = env
    append(home, repo, "sess-present")
    proc = run(home, "rollup", "--repo", str(repo), "--session-key", "sess-missing")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []


# --- 6. repo-key collision resistance ------------------------------------


def test_same_basename_different_paths_get_different_repo_keys(tmp_path: Path):
    """Regression guard: a bare directory basename is NOT an acceptable repo key."""
    module = _load_module()
    a = tmp_path / "alpha" / "DinoStack"
    b = tmp_path / "beta" / "DinoStack"
    a.mkdir(parents=True)
    b.mkdir(parents=True)

    key_a = module.repo_key(str(a))
    key_b = module.repo_key(str(b))

    assert a.name == b.name == "DinoStack"
    assert key_a != key_b, "same-basename repos must not share a shard directory"
    assert key_a == module.repo_key(str(a)), "repo key must be stable across calls"
    # Filesystem-safe.
    assert all(ch.isalnum() or ch in "._-" for ch in key_a)


def test_same_basename_repos_write_to_separate_shard_dirs(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    a = tmp_path / "alpha" / "DinoStack"
    b = tmp_path / "beta" / "DinoStack"
    a.mkdir(parents=True)
    b.mkdir(parents=True)

    append(home, a, "sess-1", **{"--domain-tag": "from-alpha"})
    append(home, b, "sess-1", **{"--domain-tag": "from-beta"})

    dirs = sorted(p.name for p in store_dir(home).iterdir() if p.is_dir())
    assert len(dirs) == 2, f"expected two distinct shard dirs, got {dirs}"
    assert [r["domain_tag"] for r in read_entries(home, a, "sess-1")] == ["from-alpha"]
    assert [r["domain_tag"] for r in read_entries(home, b, "sess-1")] == ["from-beta"]


def test_session_key_with_path_separators_is_filesystem_safe(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "proj"
    repo.mkdir()

    proc = append(home, repo, "../../escape/key")
    assert proc.returncode == 0, proc.stderr
    shards = list(store_dir(home).rglob("*.jsonl"))
    assert len(shards) == 1
    assert shards[0].parent.parent == store_dir(home), "shard must stay inside the store"
    assert read_entries(home, repo, "../../escape/key")[0]["session_key"] == "../../escape/key"


# --- 7. symlink invocation (mandatory _lib resolution guard) --------------


def test_invocation_through_a_path_symlink(tmp_path: Path):
    """install.sh symlinks bin/ds-* into ~/.local/bin but never _lib.py.

    A bare Path(__file__).parent lookup would resolve to the symlink's dir and
    raise FileNotFoundError at import time. Only a real symlink + subprocess
    exercises this; in-process import never does.
    """
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "proj"
    repo.mkdir()

    link_dir = tmp_path / "local-bin"
    link_dir.mkdir()
    link = link_dir / "ds-learning-shard"
    os.symlink(CLI, link)
    assert link.is_symlink()
    assert not (link_dir / "_lib.py").exists()

    helped = run(home, "--help", cli=link)
    assert helped.returncode == 0, helped.stderr
    assert "FileNotFoundError" not in helped.stderr

    argv = [
        "append", "--repo", str(repo), "--session-key", "sess-symlink",
        "--agent-id", "a", "--role", "engineer", "--event-type", "workaround",
        "--domain-tag", "install", "--description", "via symlink",
    ]
    proc = run(home, *argv, cli=link)
    assert proc.returncode == 0, proc.stderr
    assert "FileNotFoundError" not in proc.stderr
    assert read_entries(home, repo, "sess-symlink")[0]["description"] == "via symlink"


# --- 8. soft-fail still emits a parseable JSON array ----------------------


def _break_the_lock(home: Path, repo: Path) -> Path:
    """Force every locked path to raise, without touching the early-exit checks.

    The repo shard dir must still exist (or rollup/list take the documented
    absent-store branch and never reach the soft-fail handler), so the lock FILE
    is replaced by a DIRECTORY: Path.touch(exist_ok=True) is satisfied by utime
    on a directory, and acquire_exclusive_lock's open(..., "r") then raises
    IsADirectoryError inside the try block main() guards.
    """
    module = _load_module()
    # repo_key does not read HOME, so the in-process value matches the CLI's.
    lock = store_dir(home) / module.repo_key(str(repo)) / ".lock"
    assert lock.is_file(), "the append fixture should have created the real lock file"
    lock.unlink()
    lock.mkdir()
    return lock


@pytest.mark.parametrize("subcommand", ["rollup", "list"])
def test_soft_fail_still_emits_empty_json_array(env, subcommand):
    """Contract: rollup/list emit a JSON array to stdout and exit 0 - ALWAYS.

    Empty stdout with exit 0 crashes json.loads(stdout) and the exit code gives
    the consumer no reason to expect it.
    """
    home, repo = env
    append(home, repo, "sess-soft")
    broken = _break_the_lock(home, repo)
    assert broken.is_dir()

    proc = run(home, subcommand, "--repo", str(repo))
    assert proc.returncode == 0, proc.stderr
    assert "soft-fail" in proc.stderr, "the soft-fail path must actually have fired"
    assert json.loads(proc.stdout) == [], f"{subcommand} stdout must stay parseable"


def test_soft_fail_after_a_successful_emit_does_not_append_a_second_array(env):
    """The fallback must not turn one valid array into two, which is unparseable."""
    home, repo = env
    append(home, repo, "sess-two")
    # An unwritable shard dir lets rollup emit, then fail writing .rolled-up.json.
    key_dir = next(p for p in store_dir(home).iterdir() if p.is_dir())
    original = key_dir.stat().st_mode
    os.chmod(key_dir, 0o500)
    try:
        proc = run(home, "rollup", "--repo", str(repo))
    finally:
        os.chmod(key_dir, original)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert len(payload) == 1, "the emitted array must survive the later failure"


# --- 9. worktree / primary checkout key convergence -----------------------


def _require_git() -> str:
    """git is optional locally, MANDATORY in CI.

    A silently-skipped assertion is indistinguishable from a passing one in a
    CI log, so skipping is only allowed off CI.
    """
    found = shutil.which("git")
    if found:
        return found
    if os.environ.get("CI"):
        raise AssertionError("git is required in CI; refusing to skip this assertion")
    pytest.skip("git not installed")


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "user.email=t@example.com",
         "-c", "user.name=Test", *args],
        cwd=str(cwd), capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc


def _make_repo_with_worktree(root: Path) -> tuple[Path, Path]:
    primary = root / "primary" / "DinoStack"
    primary.mkdir(parents=True)
    _git("init", "-q", cwd=primary)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=primary)
    worktree = primary / ".claude" / "worktrees" / "agent-abc"
    _git("worktree", "add", "-q", str(worktree), "-b", "wt-abc", cwd=primary)
    return primary, worktree


def test_worktree_and_primary_checkout_share_one_repo_key(tmp_path: Path):
    """The driving scenario: engineer appends from a worktree, conductor rolls
    up from the primary checkout. Divergent keys silently lose the learning."""
    _require_git()
    module = _load_module()
    primary, worktree = _make_repo_with_worktree(tmp_path)

    assert worktree.is_dir()
    assert primary.resolve() != worktree.resolve()
    assert module.repo_key(str(worktree)) == module.repo_key(str(primary))


def test_subdirectory_of_a_checkout_shares_its_repo_key(tmp_path: Path):
    _require_git()
    module = _load_module()
    primary, _ = _make_repo_with_worktree(tmp_path)
    sub = primary / "bin" / "tests"
    sub.mkdir(parents=True)
    assert module.repo_key(str(sub)) == module.repo_key(str(primary))


def test_two_git_repos_with_the_same_basename_still_differ(tmp_path: Path):
    """Canonicalisation must not regress the same-basename collision guard."""
    _require_git()
    module = _load_module()
    keys = []
    for parent in ("alpha", "beta"):
        repo = tmp_path / parent / "DinoStack"
        repo.mkdir(parents=True)
        _git("init", "-q", cwd=repo)
        _git("commit", "-q", "--allow-empty", "-m", "init", cwd=repo)
        keys.append(module.repo_key(str(repo)))
    assert keys[0] != keys[1]


def test_non_git_path_still_yields_a_stable_key(tmp_path: Path):
    """Documented fallback: hash the caller's own resolved absolute path."""
    module = _load_module()
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert not (plain / ".git").exists()

    key = module.repo_key(str(plain))
    assert key == module.repo_key(str(plain)), "key must be stable across calls"
    assert key.startswith("not-a-repo-")
    assert all(ch.isalnum() or ch in "._-" for ch in key)
    assert module.canonical_repo_path(str(plain)) == str(plain.resolve())


def test_entry_appended_from_a_worktree_is_rolled_up_from_the_primary(tmp_path: Path):
    """End-to-end proof of Major 2: the learning must not vanish."""
    _require_git()
    home = tmp_path / "home"
    home.mkdir()
    primary, worktree = _make_repo_with_worktree(tmp_path)

    proc = append(home, worktree, "sess-wt", **{"--domain-tag": "from-worktree"})
    assert proc.returncode == 0, proc.stderr

    rolled = run(home, "rollup", "--repo", str(primary))
    assert rolled.returncode == 0, rolled.stderr
    emitted = json.loads(rolled.stdout)
    assert [row["domain_tag"] for row in emitted] == ["from-worktree"]

    dirs = [p.name for p in store_dir(home).iterdir() if p.is_dir()]
    assert len(dirs) == 1, f"worktree and primary must share ONE shard dir, got {dirs}"


# --- 10. minor hardening --------------------------------------------------


def test_cap_counts_physical_lines_not_parsed_rows(env):
    """A corrupt line must consume cap budget, or a shard grows without bound."""
    home, repo = env
    append(home, repo, "sess-corrupt")
    shard = next(store_dir(home).rglob("*.jsonl"))
    with open(shard, "a", encoding="utf-8") as handle:
        handle.write("{not json\n" * 4)

    proc = append(home, repo, "sess-corrupt", **{"--domain-tag": "overflow"})
    assert proc.returncode == 0
    assert "cap reached, entry dropped" in proc.stderr
    assert len(shard.read_text(encoding="utf-8").splitlines()) == 5


def test_append_recovers_from_a_newline_less_partial_line(env):
    """A crash mid-append must not make the NEXT append concatenate onto it."""
    home, repo = env
    append(home, repo, "sess-partial")
    shard = next(store_dir(home).rglob("*.jsonl"))
    with open(shard, "a", encoding="utf-8") as handle:
        handle.write('{"partial": tru')  # no trailing newline

    proc = append(home, repo, "sess-partial", **{"--domain-tag": "after-crash"})
    assert proc.returncode == 0, proc.stderr
    lines = shard.read_text(encoding="utf-8").splitlines()
    assert lines[-1].startswith("{"), "the new entry must be its own line"
    assert json.loads(lines[-1])["domain_tag"] == "after-crash"
    assert [r["domain_tag"] for r in read_entries(home, repo, "sess-partial")][-1] == "after-crash"


def test_rollup_self_heals_an_untrustworthy_state_record(env):
    """A shard record in any non-id-keyed shape must re-emit, never strand.

    Re-emission is the safe direction: a duplicate is recoverable
    conductor-side, a lost learning is not.
    """
    home, repo = env
    append(home, repo, "sess-stale", **{"--domain-tag": "only"})
    run(home, "rollup", "--repo", str(repo))

    state_path = next(store_dir(home).rglob(".rolled-up.json"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for name in state["shards"]:
        state["shards"][name] = {"garbage": True}
    state_path.write_text(json.dumps(state), encoding="utf-8")

    proc = run(home, "rollup", "--repo", str(repo))
    assert proc.returncode == 0, proc.stderr
    assert [r["domain_tag"] for r in json.loads(proc.stdout)] == ["only"]


# --- 11. id-keyed rollup bookkeeping (Major: positional index loses entries) --


def _state_path(home: Path) -> Path:
    return next(store_dir(home).rglob(".rolled-up.json"))


def _corrupt_line(shard: Path, index: int) -> None:
    """Make one physical line of a shard unparseable, in place."""
    lines = shard.read_text(encoding="utf-8").splitlines()
    lines[index] = "{not json"
    shard.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_corrupting_an_already_rolled_line_does_not_lose_a_fresh_entry(env):
    """The defect a positional rolled_count cannot survive.

    rolled_count is an index into PARSED rows, and _read_shard skips malformed
    lines by contract. Corrupting an already-rolled line shifts every later row
    down one, so the row at that index is skipped forever. Keyed on ids there
    is no index to shift.
    """
    home, repo = env
    for tag in ("e1", "e2", "e3"):
        append(home, repo, "sess-shift", **{"--domain-tag": tag})

    first = run(home, "rollup", "--repo", str(repo))
    assert [r["domain_tag"] for r in json.loads(first.stdout)] == ["e1", "e2", "e3"]

    for tag in ("e4", "e5"):
        append(home, repo, "sess-shift", **{"--domain-tag": tag})

    shard = next(store_dir(home).rglob("*.jsonl"))
    _corrupt_line(shard, 1)  # already-rolled e2

    second = run(home, "rollup", "--repo", str(repo))
    assert second.returncode == 0, second.stderr
    emitted = [r["domain_tag"] for r in json.loads(second.stdout)]
    assert emitted == ["e4", "e5"], f"e4 must not fall behind an index: {emitted}"


def test_malformed_line_that_was_never_rolled_up_does_not_block_later_entries(env):
    """The mirror direction: a corrupt line among UN-rolled rows."""
    home, repo = env
    append(home, repo, "sess-mal", **{"--domain-tag": "a"})
    append(home, repo, "sess-mal", **{"--domain-tag": "b"})
    append(home, repo, "sess-mal", **{"--domain-tag": "c"})

    shard = next(store_dir(home).rglob("*.jsonl"))
    _corrupt_line(shard, 1)  # never-rolled "b"

    proc = run(home, "rollup", "--repo", str(repo))
    assert proc.returncode == 0, proc.stderr
    assert [r["domain_tag"] for r in json.loads(proc.stdout)] == ["a", "c"]


def test_duplicate_rows_are_emitted_once(env):
    """A duplicated physical line shares one id and must not double-emit."""
    home, repo = env
    append(home, repo, "sess-dup", **{"--domain-tag": "solo"})

    shard = next(store_dir(home).rglob("*.jsonl"))
    line = shard.read_text(encoding="utf-8").splitlines()[0]
    shard.write_text(line + "\n" + line + "\n", encoding="utf-8")

    proc = run(home, "rollup", "--repo", str(repo))
    assert proc.returncode == 0, proc.stderr
    emitted = json.loads(proc.stdout)
    assert [r["domain_tag"] for r in emitted] == ["solo"], "duplicate id emitted twice"

    again = run(home, "rollup", "--repo", str(repo))
    assert json.loads(again.stdout) == []


def test_reordered_rows_are_not_re_emitted(env):
    """Membership has no ordering; a positional index does."""
    home, repo = env
    for tag in ("r1", "r2", "r3"):
        append(home, repo, "sess-reorder", **{"--domain-tag": tag})
    run(home, "rollup", "--repo", str(repo))

    shard = next(store_dir(home).rglob("*.jsonl"))
    lines = shard.read_text(encoding="utf-8").splitlines()
    shard.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")

    proc = run(home, "rollup", "--repo", str(repo))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == [], "reordering must not re-emit"


def test_pre_existing_count_shaped_state_re_emits_rather_than_losing(env):
    """Nothing is in production, so no migration - but never crash, never lose."""
    home, repo = env
    append(home, repo, "sess-legacy", **{"--domain-tag": "kept-1"})
    append(home, repo, "sess-legacy", **{"--domain-tag": "kept-2"})
    run(home, "rollup", "--repo", str(repo))

    state_path = _state_path(home)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    # Exactly the pre-DS-154 shape, id list removed.
    state["shards"] = {
        name: {"rolled_count": 2, "rolled_ts": "2026-01-01T00:00:00Z"}
        for name in state["shards"]
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")

    proc = run(home, "rollup", "--repo", str(repo))
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == "" or "soft-fail" not in proc.stderr, proc.stderr
    emitted = [r["domain_tag"] for r in json.loads(proc.stdout)]
    assert emitted == ["kept-1", "kept-2"], f"count-shaped state must not lose: {emitted}"

    # And the rewritten state is id-keyed again, so idempotency resumes.
    assert json.loads(run(home, "rollup", "--repo", str(repo)).stdout) == []


def test_rollup_state_is_id_keyed_and_bounded_by_the_shard(env):
    """Schema assertion plus the stated bound: never more ids than the shard holds."""
    home, repo = env
    for tag in ("b1", "b2"):
        append(home, repo, "sess-bound", **{"--domain-tag": tag})
    run(home, "rollup", "--repo", str(repo))

    state = json.loads(_state_path(home).read_text(encoding="utf-8"))
    (record,) = state["shards"].values()
    assert "rolled_count" not in record, "positional bookkeeping must be gone"
    assert isinstance(record["rolled_ids"], list)

    shard = next(store_dir(home).rglob("*.jsonl"))
    live_ids = {json.loads(line)["id"] for line in shard.read_text(encoding="utf-8").splitlines()}
    assert set(record["rolled_ids"]) == live_ids
    assert len(record["rolled_ids"]) <= 5, "bounded by ENTRY_CAP_PER_SHARD"

    # Truncating the shard must shrink the id set, not grow it unboundedly.
    shard.write_text("", encoding="utf-8")
    for tag in ("b3",):
        append(home, repo, "sess-bound", **{"--domain-tag": tag})
    run(home, "rollup", "--repo", str(repo))
    state = json.loads(_state_path(home).read_text(encoding="utf-8"))
    (record,) = state["shards"].values()
    assert len(record["rolled_ids"]) == 1


def test_lock_file_is_not_group_or_world_readable(env):
    home, repo = env
    append(home, repo, "sess-lockmode")
    lock = next(store_dir(home).rglob(".lock"))
    assert lock.stat().st_mode & 0o077 == 0


def test_store_root_is_not_world_readable(env):
    home, repo = env
    append(home, repo, "sess-mode")
    assert store_dir(home).stat().st_mode & 0o077 == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
