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

Every subprocess runs under a fake $HOME so the developer's real
~/.agentic/learnings-shards store is never touched.

Run with: python3 -m pytest bin/tests/test_ds_learning_shard.py -x
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
