"""Behavioral matrix for bin/ds-retire-carrier (cases a-s, one per gate or
ledger rule). Every case builds disposable repos with a bare origin under
pytest's tmp_path and never touches a live checkout. Every subprocess run of
the tool goes through a git argv shim that logs each git invocation; the
shim log is checked after every run for force, unlock, branch deletion,
prune and push (case m)."""

from __future__ import annotations

import importlib.machinery as _ilm
import importlib.util as _ilu
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TOOL = REPO_ROOT / "bin" / "ds-retire-carrier"
CODEX_SKILLS = REPO_ROOT / "scripts" / "codex-skills.py"
REAL_GIT = shutil.which("git")
GITIGNORE = "/.agentic/*\n/.claude/worktrees/\nnode_modules/\n*.log\n*.out\n"


def _load(name: str, path: Path):
    loader = _ilm.SourceFileLoader(name, str(path))
    module = _ilu.module_from_spec(_ilu.spec_from_loader(name, loader))
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run([REAL_GIT, "-C", str(cwd), *args], capture_output=True, text=True)
    if check:
        assert proc.returncode == 0, f"git {args} failed: {proc.stderr}{proc.stdout}"
    return proc


def commit(cwd: Path, name: str, content: str = "x\n") -> str:
    (cwd / name).write_text(content)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", f"add {name}")
    return git(cwd, "rev-parse", "HEAD").stdout.strip()


class Fixture:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.origin = tmp / "origin.git"
        self.repo = tmp / "repo"
        subprocess.run([REAL_GIT, "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run([REAL_GIT, "clone", "-q", str(self.origin), str(self.repo)], check=True,
                       capture_output=True)
        git(self.repo, "config", "user.email", "spec@example.com")
        git(self.repo, "config", "user.name", "spec")
        (self.repo / ".gitignore").write_text(GITIGNORE)
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-q", "-m", "init")
        git(self.repo, "push", "-q", "-u", "origin", "main")
        self.shim_dir = tmp / "shim"
        self.shim_dir.mkdir()
        self.shim_log = tmp / "git-argv.jsonl"
        shim = self.shim_dir / "git"
        shim.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            f"with open({str(self.shim_log)!r}, 'a') as h:\n"
            "    h.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            f"os.execv({REAL_GIT!r}, [{REAL_GIT!r}] + sys.argv[1:])\n"
        )
        shim.chmod(0o755)

    @property
    def ledger(self) -> Path:
        return self.repo / ".agentic" / "worktree-cleanup-skips.jsonl"

    def records(self) -> list:
        if not self.ledger.exists():
            return []
        return [json.loads(line) for line in self.ledger.read_text().splitlines() if line.strip()]

    def add(self, name: str, branch: str | None = None, start: str = "main") -> Path:
        path = self.repo / ".agentic" / "worktrees" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if branch:
            git(self.repo, "worktree", "add", "-q", str(path), "-b", branch, start)
        else:
            git(self.repo, "worktree", "add", "-q", "--detach", str(path), start)
        git(path, "config", "user.email", "spec@example.com")
        git(path, "config", "user.name", "spec")
        return path

    def env(self) -> dict:
        env = dict(os.environ)
        env["PATH"] = f"{self.shim_dir}{os.pathsep}{env.get('PATH', '')}"
        env.pop("AE_SESSION_ID", None)
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        return env

    def run(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        proc = subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                              cwd=str(cwd or self.tmp), env=self.env())
        assert_no_forbidden_git(self.shim_log)
        return proc

    def run_shell(self, command: str, extra_env: dict) -> subprocess.CompletedProcess:
        env = self.env()
        env.update(extra_env)
        proc = subprocess.run(["bash", "-c", command], capture_output=True, text=True,
                              cwd=str(self.repo), env=env)
        assert_no_forbidden_git(self.shim_log)
        return proc

    def registered(self) -> list:
        out = git(self.repo, "worktree", "list", "--porcelain").stdout
        return [line.split(" ", 1)[1] for line in out.splitlines() if line.startswith("worktree ")]


def assert_no_forbidden_git(log: Path) -> None:
    if not log.exists():
        return
    for line in log.read_text().splitlines():
        argv = json.loads(line)
        assert "--force" not in argv and "-f" not in argv, argv
        assert "push" not in argv, argv
        if "worktree" in argv:
            sub = argv[argv.index("worktree") + 1]
            assert sub not in ("unlock", "prune"), argv
        if "branch" in argv:
            assert not {"-d", "-D", "--delete"} & set(argv), argv
        if "update-ref" in argv:
            assert not {"-d", "--delete"} & set(argv), argv
            ref = argv[argv.index("update-ref") + 1]
            assert ref.startswith("refs/heads/carrier-pin/"), argv
        if "fetch" in argv:
            assert not {"--prune", "-p", "--prune-tags"} & set(argv), argv


@pytest.fixture
def fx(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path)


def last(fx: Fixture) -> dict:
    return fx.records()[-1]


# a. Codex carrier completion, driven from the generated contract's own text.
def test_a_codex_carrier_completion_from_contract(fx: Fixture) -> None:
    contract = _load("codex_skills_for_test", CODEX_SKILLS).CODEX_SPAWN_CONTRACT
    add_cmd = re.search(r"`(git worktree add [^`]+)`", contract).group(1)
    paragraph = re.search(r"\*\*Retire or hold each checkout at completion\.\*\*.*?(?=\n\n)", contract, re.S)
    assert paragraph, "retirement paragraph missing from CODEX_SPAWN_CONTRACT"
    retire_cmd = re.search(r"`(\$AE_REPO_DIR/[^`]+<absolute-path>)`", paragraph.group(0)).group(1)
    branch = "codex/reviewer-1"
    wt = fx.repo / ".agentic" / "worktrees" / branch
    env = {"AE_PROJECT_DIR": str(fx.repo), "AE_REPO_DIR": str(REPO_ROOT), "BASE_BRANCH": "main"}
    git(fx.repo, "fetch", "-q", "origin")
    proc = fx.run_shell(add_cmd.replace("<branch>", branch), env)
    assert proc.returncode == 0, proc.stderr
    git(wt, "config", "user.email", "spec@example.com")
    git(wt, "config", "user.name", "spec")
    sha = commit(wt, "review.txt")
    proc = fx.run_shell(retire_cmd.replace("<absolute-path>", str(wt)), env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not wt.exists()
    assert git(fx.repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0
    assert git(fx.repo, "cat-file", "-e", sha, check=False).returncode == 0
    rec = last(fx)
    assert rec["kind"] == "retired" and rec["registered_before"] == 2 and rec["registered_after"] == 1, rec


# b. Detached unpushed commit: held; --pin retires and keeps it reachable.
def test_b_detached_unpushed_held_then_pin(fx: Fixture) -> None:
    wt = fx.add("det-b")
    sha = commit(wt, "b.txt")
    proc = fx.run(str(wt))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "privately pins 1 commit(s)" in proc.stderr
    assert wt.exists() and last(fx)["kind"] == "hold"
    proc = fx.run("--pin", str(wt))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    pins = git(fx.repo, "for-each-ref", "--format=%(refname)", "refs/heads/carrier-pin/").stdout.split()
    assert pins == [f"refs/heads/carrier-pin/det-b-{sha[:8]}"], pins
    assert git(fx.repo, "merge-base", "--is-ancestor", sha, pins[0], check=False).returncode == 0
    assert last(fx)["kind"] == "retired" and last(fx)["pinned"] == pins
    assert "det-b" not in fx.run("--repo", str(fx.repo), "--list-holds").stdout


# c. A commit only the detached HEAD reflog still names: held.
def test_c_detached_reflog_only_commit_held(fx: Fixture) -> None:
    wt = fx.add("det-c")
    commit(wt, "c.txt")
    git(wt, "checkout", "-q", "--detach", "main")
    proc = fx.run(str(wt))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "unpinned commit" in last(fx)["reason"]
    assert wt.exists()


# c2. Branched carrier after an amend: the pre-amend commit survives in the branch reflog.
def test_c2_branched_after_amend_retired(fx: Fixture) -> None:
    wt = fx.add("br-c2", branch="feature/c2")
    commit(wt, "c2.txt")
    (wt / "c2.txt").write_text("amended\n")
    git(wt, "commit", "-q", "-a", "--amend", "-m", "amended")
    git(fx.repo, "remote", "set-url", "origin", str(fx.tmp / "nowhere.git"))
    proc = fx.run(str(wt))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not wt.exists()


# d. A stale local remote-tracking ref is not a pin: the live origin no longer has it.
def test_d_stale_origin_ref_held(fx: Fixture) -> None:
    wt = fx.add("det-d")
    commit(wt, "d.txt")
    git(wt, "push", "-q", "origin", "HEAD:refs/heads/topic-d")
    git(fx.repo, "fetch", "-q", "origin")
    git(fx.origin, "branch", "-D", "topic-d")
    assert git(fx.repo, "show-ref", "--verify", "--quiet", "refs/remotes/origin/topic-d", check=False).returncode == 0
    proc = fx.run(str(wt))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert wt.exists()


# e. Ignored authored .agentic/plan.md: held, file intact.
def test_e_ignored_plan_held(fx: Fixture) -> None:
    wt = fx.add("br-e", branch="feature/e")
    (wt / ".agentic").mkdir()
    (wt / ".agentic" / "plan.md").write_text("plan\n")
    proc = fx.run(str(wt))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "holds protected ignored content (1 paths: .agentic/plan.md)" in proc.stderr
    assert (wt / ".agentic" / "plan.md").read_text() == "plan\n"
    assert last(fx)["reason"].startswith("protected ignored content")


# f. Disposable ignored content: retired, telemetry salvaged into the primary.
def test_f_disposable_content_retired_and_salvaged(fx: Fixture) -> None:
    wt = fx.add("br-f", branch="feature/f")
    (wt / "node_modules").mkdir()
    (wt / "node_modules" / "dep.js").write_text("x\n")
    (wt / ".agentic").mkdir()
    (wt / ".agentic" / "events.jsonl").write_text('{"e":1}\n')
    proc = fx.run(str(wt))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    salvaged = list((fx.repo / ".agentic" / "reaped-telemetry").glob("*.jsonl"))
    assert len(salvaged) == 1 and salvaged[0].read_text() == '{"e":1}\n'


# f1. Evidence has no exception: held until it is deleted.
def test_f1_evidence_held_until_deleted(fx: Fixture) -> None:
    wt = fx.add("br-f1", branch="feature/f1")
    (wt / "node_modules").mkdir()
    (wt / "node_modules" / "dep.js").write_text("x\n")
    (wt / ".agentic" / "evidence").mkdir(parents=True)
    (wt / ".agentic" / "events.jsonl").write_text('{"e":1}\n')
    (wt / ".agentic" / "evidence" / "n1.md").write_text("node\n")
    assert fx.run(str(wt)).returncode == 3
    assert (wt / ".agentic" / "evidence" / "n1.md").exists()
    shutil.rmtree(wt / ".agentic" / "evidence")
    proc = fx.run(str(wt))
    assert proc.returncode == 0, proc.stdout + proc.stderr


# f2. Strict polarity for detached carriers. `*.log` is on the strict
# allowlist, so an ignored file outside it (`x.out`) is what separates them.
def test_f2_detached_strict_branched_default(fx: Fixture) -> None:
    det = fx.add("det-f2")
    (det / "x.out").write_text("o\n")
    proc = fx.run(str(det))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "x.out" in last(fx)["reason"]
    br = fx.add("br-f2", branch="feature/f2")
    (br / "x.out").write_text("o\n")
    proc = fx.run(str(br))
    assert proc.returncode == 0, proc.stdout + proc.stderr


# g. In-progress markers are a denylist; unknown files such as CLAUDE_BASE pass.
def test_g_bisect_held_claude_base_passes(fx: Fixture) -> None:
    wt = fx.add("br-g", branch="feature/g")
    git(wt, "bisect", "start")
    proc = fx.run(str(wt))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "has a git operation in progress (BISECT_" in proc.stderr
    ctl = fx.add("br-g2", branch="feature/g2")
    gitdir = Path(git(ctl, "rev-parse", "--absolute-git-dir").stdout.strip())
    (gitdir / "CLAUDE_BASE").write_text("main\n")
    proc = fx.run(str(ctl))
    assert proc.returncode == 0, proc.stdout + proc.stderr


# h. --hold requires --revisit and writes nothing without it.
def test_h_hold_requires_revisit(fx: Fixture) -> None:
    wt = fx.add("br-h", branch="feature/h")
    proc = fx.run("--hold", "--reason", "server running", str(wt))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert not fx.ledger.exists()


# i. Fold: latest record wins; legacy records list as holds.
def test_i_fold_latest_record_and_legacy(fx: Fixture) -> None:
    wt = fx.add("br-i", branch="feature/i")
    (wt / "dirty.txt").write_text("d\n")
    assert fx.run(str(wt)).returncode == 3
    (wt / "dirty.txt").unlink()
    assert fx.run(str(wt)).returncode == 0
    listing = fx.run("--repo", str(fx.repo), "--list-holds").stdout
    assert "br-i" not in listing

    live = fx.add("br-i2", branch="feature/i2")
    base = {"ts": "2026-01-01T00:00:00Z", "path": str(live), "branch": "feature/i2", "head": None,
            "owner": "o", "registered_before": 3}
    with fx.ledger.open("a") as handle:
        handle.write(json.dumps({**base, "kind": "hold", "explicit": False, "reason": "r", "revisit": "e"}) + "\n")
        handle.write(json.dumps({**base, "kind": "retired", "registered_after": 2}) + "\n")
    assert "br-i2" not in fx.run("--repo", str(fx.repo), "--list-holds").stdout

    legacy = fx.add("br-i3", branch="feature/i3")
    with fx.ledger.open("a") as handle:
        handle.write(json.dumps({"ts": "t", "branch": "feature/i3", "path": str(legacy), "stderr": "boom"}) + "\n")
    holds = json.loads(fx.run("--repo", str(fx.repo), "--list-holds", "--json").stdout)
    entry = [h for h in holds if h["path"] == str(legacy)]
    assert entry and entry[0]["owner"] == "unknown" and entry[0]["reason"] == "legacy remove refusal: boom"
    assert entry[0]["revisit"] == "re-run ds-retire-carrier" and entry[0]["explicit"] is False


# j. Locked: held, still locked, lock reason recorded in stderr.
def test_j_locked_held(fx: Fixture) -> None:
    wt = fx.add("br-j", branch="feature/j")
    git(fx.repo, "worktree", "lock", "--reason", "agent busy", str(wt))
    proc = fx.run(str(wt))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "is locked; skipping cleanup (branch=feature/j)" in proc.stderr
    assert last(fx)["stderr"] == "worktree is locked: agent busy"
    assert "locked agent busy" in git(fx.repo, "worktree", "list", "--porcelain").stdout
    assert wt.exists()


# k. --repo may name a linked worktree; the ledger still lands in the primary.
def test_k_repo_linked_worktree_and_mismatch(fx: Fixture) -> None:
    other = fx.add("br-k-other", branch="feature/k-other")
    wt = fx.add("br-k", branch="feature/k")
    (wt / "dirty.txt").write_text("d\n")
    assert fx.run("--repo", str(other), str(wt)).returncode == 3
    assert fx.ledger.exists()
    assert not (other / ".agentic" / "worktree-cleanup-skips.jsonl").exists()
    assert not (wt / ".agentic" / "worktree-cleanup-skips.jsonl").exists()
    foreign = Fixture(fx.tmp / "foreign")
    count = len(fx.records())
    proc = fx.run("--repo", str(foreign.repo), str(wt))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert len(fx.records()) == count


# l. Broken origin: a branched carrier needs no network; a detached one holds.
def test_l_broken_origin(fx: Fixture) -> None:
    det = fx.add("det-l")
    commit(det, "l.txt")
    br = fx.add("br-l", branch="feature/l")
    commit(br, "l-branched.txt")
    git(fx.repo, "remote", "set-url", "origin", str(fx.tmp / "missing.git"))
    proc = fx.run(str(det))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "git fetch origin failed" in last(fx)["reason"] and last(fx)["stderr"]
    proc = fx.run(str(br))
    assert proc.returncode == 0, proc.stdout + proc.stderr


# n. Post-merge release: a held branched carrier retires once clean, with no origin branch.
def test_n_post_merge_release(fx: Fixture) -> None:
    wt = fx.add("br-n", branch="feature/n")
    commit(wt, "n.txt")
    git(wt, "push", "-q", "origin", "feature/n")
    (wt / "dirty.txt").write_text("d\n")
    assert fx.run(str(wt)).returncode == 3
    (wt / "dirty.txt").unlink()
    git(fx.origin, "branch", "-D", "feature/n")
    proc = fx.run(str(wt))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert git(fx.repo, "show-ref", "--verify", "--quiet", "refs/heads/feature/n", check=False).returncode == 0


# o. Self: a caller inside the carrier never removes it.
def test_o_self_held(fx: Fixture) -> None:
    wt = fx.add("br-o", branch="feature/o")
    proc = fx.run(str(wt), cwd=wt)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert wt.exists() and last(fx)["revisit"] == "re-run from outside the carrier"


# p. --dry-run returns the verdict and writes nothing, fetching nothing.
def test_p_dry_run_writes_nothing(fx: Fixture) -> None:
    clean = fx.add("br-p", branch="feature/p")
    det = fx.add("det-p")
    commit(det, "p.txt")
    fetch_head = fx.repo / ".git" / "FETCH_HEAD"
    before = fetch_head.read_bytes() if fetch_head.exists() else None
    proc = fx.run("--dry-run", str(clean))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = fx.run("--dry-run", str(det))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert not fx.ledger.exists()
    assert clean.exists() and det.exists()
    after = fetch_head.read_bytes() if fetch_head.exists() else None
    assert before == after
    assert not git(fx.repo, "for-each-ref", "refs/heads/carrier-pin/").stdout


# q. An explicit hold survives a plain re-run and yields only to --release.
def test_q_explicit_hold_until_release(fx: Fixture) -> None:
    wt = fx.add("br-q", branch="feature/q")
    proc = fx.run("--hold", "--reason", "dev server live", "--revisit", "QA returns", str(wt))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    count = len(fx.records())
    proc = fx.run(str(wt))
    assert proc.returncode == 3 and "explicit=yes" in proc.stdout, proc.stdout + proc.stderr
    assert len(fx.records()) == count and wt.exists()
    proc = fx.run("--release", str(wt))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not wt.exists()


def _in_process(fx: Fixture, stub, *argv: str):
    return _in_process_patched(fx, {"_salvage_and_remove": stub}, *argv)


def _in_process_patched(fx: Fixture, patches: dict, *argv: str):
    tool = _load("ds_retire_carrier_for_test", TOOL)
    for name, value in patches.items():
        setattr(tool, name, value)
    cwd = os.getcwd()
    os.chdir(fx.tmp)
    try:
        return tool, tool.main(list(argv))
    finally:
        os.chdir(cwd)


# r. Salvage failure is a hold, never a removal.
def test_r_salvage_failed_held(fx: Fixture) -> None:
    wt = fx.add("br-r", branch="feature/r")

    def stub(repo, path, branch):
        return {"salvage_failed": True, "salvaged": False, "removed": False,
                "already_unregistered": False, "detail": "copy failed: disk full"}

    _tool, rc = _in_process(fx, stub, str(wt))
    assert rc == 3
    rec = last(fx)
    assert rec["reason"] == "telemetry salvage failed" and rec["stderr"] == "copy failed: disk full"
    assert wt.exists()


# s. Unregistered with content left on disk: held and listed while the directory exists.
def test_s_already_unregistered_listed(fx: Fixture) -> None:
    wt = fx.add("br-s", branch="feature/s")
    admin = Path(git(wt, "rev-parse", "--absolute-git-dir").stdout.strip())

    def stub(repo, path, branch):
        shutil.rmtree(admin)
        return {"salvage_failed": False, "salvaged": False, "removed": False,
                "already_unregistered": True, "detail": "rmtree retry failed"}

    _tool, rc = _in_process(fx, stub, str(wt))
    assert rc == 3
    assert last(fx)["reason"] == "unregistered with content left on disk"
    assert str(wt) not in "\n".join(fx.registered())
    listing = fx.run("--repo", str(fx.repo), "--list-holds").stdout
    assert f"HELD {wt}" in listing


def _nested(fx: Fixture, carrier: Path, name: str) -> Path:
    path = carrier / ".claude" / "worktrees" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    git(fx.repo, "worktree", "add", "-q", "--detach", str(path), "main")
    git(path, "config", "user.email", "spec@example.com")
    git(path, "config", "user.name", "spec")
    return path


# t. A registered worktree nested inside the carrier (unlocked, detached, dirty,
# with an unpushed commit) holds the carrier; removal would delete it.
def test_t_nested_dirty_detached_worktree_held(fx: Fixture) -> None:
    carrier = fx.add("br-t", branch="feature/t")
    inner = _nested(fx, carrier, "inner-t")
    sha = commit(inner, "inner.txt")
    (inner / "dirty.txt").write_text("d\n")
    proc = fx.run(str(carrier))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    rec = last(fx)
    assert str(inner) in rec["reason"] and str(inner) in rec["revisit"], rec
    assert "contains 1 registered worktree(s)" in proc.stderr
    assert (inner / "dirty.txt").exists() and carrier.exists()
    assert str(inner) in fx.registered()
    assert git(fx.repo, "cat-file", "-e", sha, check=False).returncode == 0


# t2. A locked, dirty nested worktree holds the carrier and stays locked.
def test_t2_nested_locked_worktree_held(fx: Fixture) -> None:
    carrier = fx.add("br-t2", branch="feature/t2")
    inner = _nested(fx, carrier, "inner-t2")
    (inner / "dirty.txt").write_text("d\n")
    git(fx.repo, "worktree", "lock", "--reason", "agent busy", str(inner))
    proc = fx.run(str(carrier))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert str(inner) in last(fx)["reason"]
    assert (inner / "dirty.txt").exists()
    assert "locked agent busy" in git(fx.repo, "worktree", "list", "--porcelain").stdout


# u. A commit named only by ORIG_HEAD is a candidate.
def test_u_orig_head_only_commit_held(fx: Fixture) -> None:
    wt = fx.add("det-u")
    sha = commit(wt, "u.txt")
    git(wt, "checkout", "-q", "--detach", "main")
    gitdir = Path(git(wt, "rev-parse", "--absolute-git-dir").stdout.strip())
    (gitdir / "ORIG_HEAD").write_text(sha + "\n")
    (gitdir / "logs" / "HEAD").unlink()
    proc = fx.run(str(wt))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert sha[:8] in last(fx)["reason"]
    assert wt.exists()


# v. Gate 3: a .git file naming another carrier's admin dir, or an admin dir
# outside <common>/worktrees/, is indeterminate.
def test_v_private_gitdir_validation(fx: Fixture) -> None:
    wt = fx.add("br-v", branch="feature/v")
    other = fx.add("br-v-other", branch="feature/v-other")
    other_admin = git(other, "rev-parse", "--absolute-git-dir").stdout.strip()
    (wt / ".git").write_text(f"gitdir: {other_admin}\n")
    proc = fx.run(str(wt))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "private gitdir indeterminate" in proc.stderr and "points at" in last(fx)["reason"]
    assert wt.exists()

    wt2 = fx.add("br-v2", branch="feature/v2")
    admin2 = Path(git(wt2, "rev-parse", "--absolute-git-dir").stdout.strip())
    outside = fx.tmp / "outside-admin"
    shutil.copytree(admin2, outside)
    (outside / "commondir").write_text(str(admin2.parent.parent) + "\n")
    (wt2 / ".git").write_text(f"gitdir: {outside}\n")
    proc = fx.run(str(wt2))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "is not under" in last(fx)["reason"]
    assert wt2.exists()


# w. --pin re-verifies: pins that do not cover every unpinned commit still hold.
def test_w_pin_reverification_holds(fx: Fixture) -> None:
    wt = fx.add("det-w")
    commit(wt, "w.txt")
    _tool, rc = _in_process_patched(fx, {"_maximal": lambda cwd, commits: []}, "--pin", str(wt))
    assert rc == 3
    assert last(fx)["reason"] == "--pin re-verification found commits still unpinned"
    assert wt.exists()


# x. A reftable repository holds before any reflog file is trusted.
def test_x_reftable_holds(fx: Fixture) -> None:
    wt = fx.add("br-x", branch="feature/x")
    tool = _load("ds_retire_carrier_reftable", TOOL)
    real = tool._git

    def fake(args, cwd, timeout=None):
        if args == ["config", "--get", "extensions.refStorage"]:
            return subprocess.CompletedProcess(args, 0, "reftable\n", "")
        return real(args, cwd, timeout)

    _tool, rc = _in_process_patched(fx, {"_git": fake}, str(wt))
    assert rc == 3
    assert "reftable" in last(fx)["reason"]
    assert wt.exists()


# y. Detached carriers re-filter .agentic/ offenders: disposable telemetry does not hold.
def test_y_detached_agentic_refilter(fx: Fixture) -> None:
    wt = fx.add("det-y")
    (wt / ".agentic").mkdir()
    (wt / ".agentic" / "events.jsonl").write_text('{"e":1}\n')
    proc = fx.run(str(wt))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert list((fx.repo / ".agentic" / "reaped-telemetry").glob("*.jsonl"))


# z. Inspection never rewrites the carrier's index (GIT_OPTIONAL_LOCKS=0).
def test_z_dry_run_leaves_index_untouched(fx: Fixture) -> None:
    wt = fx.add("br-z", branch="feature/z")
    index = Path(git(wt, "rev-parse", "--absolute-git-dir").stdout.strip()) / "index"
    os.utime(wt / ".gitignore", (1_000_000_000, 1_000_000_000))
    before = index.read_bytes()
    proc = fx.run("--dry-run", str(wt))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert index.read_bytes() == before


# aa. An explicit hold is keyed to its carrier: a new carrier at the same path is not held by it.
def test_aa_explicit_hold_not_inherited_by_new_carrier(fx: Fixture) -> None:
    wt = fx.add("br-aa", branch="feature/aa")
    assert fx.run("--hold", "--reason", "server", "--revisit", "QA returns", str(wt)).returncode == 3
    git(fx.repo, "worktree", "remove", str(wt))
    commit(fx.repo, "aa-main.txt")
    fx.add("br-aa", branch="feature/aa2")
    proc = fx.run(str(wt))
    assert proc.returncode == 0, proc.stdout + proc.stderr
