"""Purpose: Run /ds-implement-ticket's post-implementation scripts end to end
against a temp origin and a git-backed fake GitHub: ds-ticket-commit pushes
the engineer's commit and retires its worktree, ds-ticket-ci waits out a
lazily registering suite, the Phase 10b ready fence (run from
ds-implement-ticket.md) marks the PR ready, ds-ticket-finish merge
publishes the delivery record, merges, base-syncs and retires the QA
carrier. A red check stops at ds-ticket-ci with nothing marked ready or
merged.
Public API: pytest-discovered test cases.
Upstream deps: pytest, git, jq, python3; Phase 10b of
content/commands/ds-implement-ticket.md; bin/ds-ticket-commit,
bin/ds-ticket-ci, bin/ds-ticket-finish, bin/ds-pr-delivery-record,
bin/ds-base-sync, bin/ds-retire-carrier; record() from
test_pr_delivery_record.py.
Downstream consumers: bin-tests CI and local pytest runs.
Failure modes: assertion failures or subprocess timeouts; all state lives
under pytest's tmp_path.
Performance: a few seconds per case (local git only, --interval 0).
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pr_delivery_record import record

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "bin"
BRANCH = "feature/e2e"
COMMAND = ROOT / "content/commands/ds-implement-ticket.md"

# The fake gh keeps PR state in FAKE_GH_STATE and reads the branch head
# and performs the squash merge in the bare origin, so merge and base sync
# are observable as real refs.
GH = r"""#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
p = Path(os.environ["FAKE_GH_STATE"]); s = json.loads(p.read_text()); args = sys.argv[1:]
s["calls"].append(args)
origin = s["origin"]
def git(*a):
    return subprocess.run(["git", "--git-dir", origin, *a], check=True, capture_output=True, text=True).stdout.strip()
def head():
    return git("rev-parse", "refs/heads/" + s["branch"])
def done(out=None, code=0, err=None):
    p.write_text(json.dumps(s))
    if out is not None: print(out if isinstance(out, str) else json.dumps(out))
    if err: print(err, file=sys.stderr)
    sys.exit(code)
def opt(name):
    return args[args.index(name) + 1] if name in args else None
if args[:2] == ["pr", "view"]:
    fields = {
        "baseRefName": s["base"], "isDraft": s["draft"], "state": s["state"], "number": 7,
        "mergeable": "MERGEABLE", "reviewDecision": "", "autoMergeRequest": None,
        "body": s["body"], "url": "https://github.com/test/repo/pull/7",
    }
    q = opt("-q")
    if q == ".commits[-1].messageHeadline": done(git("log", "-1", "--format=%s", "refs/heads/" + s["branch"]))
    if "headRefOid" in opt("--json"): fields["headRefOid"] = head()
    if q: done(json.dumps(fields[q.lstrip(".")]).strip('"') if not isinstance(fields[q.lstrip(".")], str) else fields[q.lstrip(".")])
    done({k: fields[k] for k in opt("--json").split(",")})
if args[:2] == ["pr", "checks"]:
    if any(f in opt("--json") for f in ("status", "conclusion")): done(code=1, err='Unknown JSON field: "status"')
    polls = s["check_polls"]
    current = polls.pop(0) if len(polls) > 1 else polls[0]
    done(current, code=8 if any(c["bucket"] == "pending" for c in current) else 0)
if args[:2] == ["pr", "ready"]:
    s["draft"] = False; done()
if args[:2] == ["pr", "edit"]:
    s["body"] = Path(opt("--body-file")).read_text(); done()
if args[:2] == ["pr", "merge"]:
    sha = opt("--match-head-commit")
    if s["draft"] or s["state"] != "OPEN" or sha != head(): done(code=1, err="not mergeable")
    tree = git("rev-parse", sha + "^{tree}")
    squash = subprocess.run(
        ["git", "--git-dir", origin, "commit-tree", tree, "-p", git("rev-parse", "refs/heads/" + s["base"]), "-m", "squash (#7)"],
        check=True, capture_output=True, text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "gh", "GIT_AUTHOR_EMAIL": "gh@example.com",
             "GIT_COMMITTER_NAME": "gh", "GIT_COMMITTER_EMAIL": "gh@example.com"},
    ).stdout.strip()
    git("update-ref", "refs/heads/" + s["base"], squash)
    if "--delete-branch" in args: git("update-ref", "-d", "refs/heads/" + s["branch"])
    s["state"] = "MERGED"; done()
if args[:2] == ["api", "--paginate"] and args[2].endswith("/rules/branches/" + s["base"]):
    done([{"type": "required_status_checks",
           "parameters": {"required_status_checks": [{"context": c} for c in s["required"]]}}])
done(code=1, err="fake gh: unhandled " + " ".join(args))
"""


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def check(name, bucket):
    return {"name": name, "state": bucket.upper(), "bucket": bucket}


@pytest.fixture
def pipeline(tmp_path):
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    git("init", "-q", "--bare", "-b", "main", str(origin))
    git("clone", "-q", str(origin), str(repo))
    for key, value in (("user.email", "spec@example.com"), ("user.name", "spec")):
        git("config", key, value, cwd=repo)
    (repo / "README.md").write_text("init\n")
    (repo / ".gitignore").write_text("/.agentic/*\n")
    git("add", "README.md", ".gitignore", cwd=repo)
    git("commit", "-q", "-m", "init", cwd=repo)
    git("push", "-q", "-u", "origin", "main", cwd=repo)

    # The engineer's isolation worktree, already committed (Phase 8 calls
    # ds-ticket-commit without files on this path).
    engineer = repo / ".agentic/worktrees/engineer"
    git("worktree", "add", "-q", "-b", BRANCH, str(engineer), cwd=repo)
    (engineer / "feature.txt").write_text("feature\n")
    git("add", "feature.txt", cwd=engineer)
    git("commit", "-q", "-m", "feat: e2e", cwd=engineer)
    # The QA carrier ds-ticket-finish merge retires.
    qa = repo / ".agentic/worktrees" / ("qa-" + BRANCH)
    git("worktree", "add", "-q", "-b", "qa-e2e", str(qa), cwd=repo)
    git("push", "-q", "origin", "qa-e2e", cwd=repo)

    stub = tmp_path / "stub-bin"
    stub.mkdir()
    (stub / "gh").write_text(GH)
    (stub / "gh").chmod(0o755)
    (stub / "ds-pr-delivery-record").symlink_to(BIN / "ds-pr-delivery-record")
    tools = {str(Path(shutil.which(t)).parent) for t in ("git", "jq", "python3", "bash")}
    state = tmp_path / "gh.json"
    state.write_text(json.dumps({
        "origin": str(origin), "branch": BRANCH, "base": "main", "draft": True, "state": "OPEN",
        "body": "User prose\n## Review rigor\n- pending\n## North Star alignment\nPillar 2\n",
        "required": ["lint", "test", "build"], "check_polls": [], "calls": [],
    }))
    env = {k: v for k, v in os.environ.items() if k not in ("REPO_DIR", "AE_SESSION_ID", "CLAUDE_CODE_SESSION_ID")}
    env.update({
        "PATH": os.pathsep.join([str(stub), *sorted(tools), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]),
        "FAKE_GH_STATE": str(state), "HOME": str(tmp_path / "home"),
    })
    (tmp_path / "home").mkdir()
    return {"tmp": tmp_path, "origin": origin, "repo": repo, "engineer": engineer, "qa": qa, "state": state, "env": env}


def gh_state(p):
    return json.loads(p["state"].read_text())


def set_polls(p, polls):
    s = gh_state(p)
    s["check_polls"] = polls
    p["state"].write_text(json.dumps(s))


def run(p, *argv):
    return subprocess.run([str(a) for a in argv], env=p["env"], capture_output=True, text=True, timeout=50)


def commit_and_wait(p):
    commit = run(p, BIN / "ds-ticket-commit", "--repo", p["repo"], "--branch", BRANCH, "--worktree-path", p["engineer"])
    ci = run(p, BIN / "ds-ticket-ci", "--pr", "7", "--gh-repo", "test/repo", "--polls", "10", "--interval", "0")
    return commit, ci


def phase10b_ready_fence():
    text = COMMAND.read_text(encoding="utf-8")
    section = text[text.index("## Phase 10b:"):text.index("## Phase 11:")]
    after = section[section.index("**Mark ready-for-review:**"):]
    assert section.index("**Thread rule:**") < section.index("**Mark ready-for-review:**")
    return re.search(r"```bash\n(.*?)```", after, re.S).group(1)


def test_commit_ci_finish_delivers_and_cleans_up(pipeline):
    p = pipeline
    engineer_sha = git("rev-parse", BRANCH, cwd=p["repo"])
    # Two stable all-green polls of 1 check (the PR #839 shape) must not
    # pass against 3 required checks.
    set_polls(p, [
        [check("lint", "pass")],
        [check("lint", "pass")],
        [check("lint", "pass"), check("test", "pass"), check("build", "pass")],
    ])
    commit, ci = commit_and_wait(p)

    assert commit.returncode == 0, commit.stdout + commit.stderr
    assert git("--git-dir", str(p["origin"]), "rev-parse", "refs/heads/" + BRANCH) == engineer_sha
    assert not p["engineer"].exists(), commit.stdout + commit.stderr

    assert ci.returncode == 0, ci.stdout + ci.stderr
    s = gh_state(p)
    checks_calls = [c for c in s["calls"] if c[:2] == ["pr", "checks"]]
    assert len(checks_calls) == 4, "the 1-of-3 green polls did not pass; two all-green polls at the floor did"
    assert s["draft"] is True, "ds-ticket-ci leaves the ready step to Phase 10b"
    assert not any(c[:2] == ["pr", "merge"] for c in s["calls"]), "ds-ticket-ci never merges"

    ready = subprocess.run(["bash", "-c", phase10b_ready_fence()], capture_output=True, text=True, timeout=30,
                           env={**p["env"], "PR_NUMBER": "7", "GH_REPO": "test/repo"})
    assert ready.returncode == 0, ready.stdout + ready.stderr
    assert gh_state(p)["draft"] is False, "the Phase 10b fence marked the PR ready"

    assessment = p["tmp"] / "assessment.json"
    assessment.write_text(json.dumps(record(engineer_sha)))
    finish = run(p, BIN / "ds-ticket-finish", "merge", "--repo", p["repo"], "--branch", BRANCH, "--ticket", "T-1",
                 "--gh-repo", "test/repo", "--pr", "7", "--delivery-record-input", assessment,
                 "--auto-merge", "true", "--base-branch", "main")
    out = finish.stdout + finish.stderr
    assert finish.returncode == 0, out
    assert "[phase: auto-merged | pr=7]" in out
    merges = [c for c in gh_state(p)["calls"] if c[:2] == ["pr", "merge"]]
    assert len(merges) == 1 and merges[0][merges[0].index("--match-head-commit") + 1] == engineer_sha
    origin_main = git("--git-dir", str(p["origin"]), "rev-parse", "refs/heads/main")
    assert git("--git-dir", str(p["origin"]), "rev-parse", "refs/heads/main^{tree}") == git("rev-parse", engineer_sha + "^{tree}", cwd=p["repo"])
    assert git("rev-parse", "main", cwd=p["repo"]) == origin_main, "base sync fast-forwarded local main"
    assert not p["qa"].exists(), "QA carrier retired"


def test_red_check_stops_before_ready_and_merge(pipeline):
    p = pipeline
    main_before = git("--git-dir", str(p["origin"]), "rev-parse", "refs/heads/main")
    set_polls(p, [[check("lint", "pass"), check("test", "fail"), check("build", "pass")]])
    commit, ci = commit_and_wait(p)

    assert commit.returncode == 0, commit.stdout + commit.stderr
    assert ci.returncode == 1, ci.stdout + ci.stderr
    assert "failing-checks: test" in ci.stdout
    s = gh_state(p)
    assert s["draft"] is True
    assert not any(c[:2] in (["pr", "merge"], ["pr", "ready"]) for c in s["calls"])
    assert git("--git-dir", str(p["origin"]), "rev-parse", "refs/heads/main") == main_before
