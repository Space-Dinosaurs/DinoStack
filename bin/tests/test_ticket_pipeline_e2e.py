"""Purpose: Run /ds-implement-ticket's post-implementation steps end to end
against a temp origin and the git-backed fake GitHub from
test_pr_delivery_record.py: ds-ticket-commit pushes the engineer's commit and
retires its worktree, the Phase 9 `gh pr create` fence (run from
ds-implement-ticket.md) opens a draft PR, ds-ticket-finish ledger records it,
ds-ticket-ci waits out a lazily registering suite, the Phase 10b ready fence
marks the PR ready, and ds-ticket-finish merge publishes the delivery
record, merges, base-syncs and retires the QA carrier. A red check stops at
ds-ticket-ci with nothing marked ready or merged.
Public API: pytest-discovered test cases.
Upstream deps: pytest, git, jq, python3; Phases 9 and 10b of
content/commands/ds-implement-ticket.md; bin/ds-ticket-commit,
bin/ds-ticket-ci, bin/ds-ticket-finish, bin/ds-pr-delivery-record,
bin/ds-base-sync, bin/ds-retire-carrier; GH and record() from
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
from test_pr_delivery_record import GH, record

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "bin"
COMMAND = ROOT / "content/commands/ds-implement-ticket.md"
BRANCH = "feature/e2e"


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def check(name, bucket):
    return {"name": name, "state": bucket.upper(), "bucket": bucket}


def section(start, end):
    text = COMMAND.read_text(encoding="utf-8")
    return text[text.index(start):text.index(end)]


def phase9_create_fence():
    fences = [f for f in re.findall(r"```bash\n(.*?)```", section("## Phase 9:", "## Phase 10:"), re.S) if "gh pr create" in f]
    assert len(fences) == 1
    fence = fences[0]
    for placeholder, value in (("[GH_REPO]", "test/repo"), ("[BASE_BRANCH]", "main"), ("[BRANCH_NAME]", BRANCH),
                               ("[TICKET_PREFIX]-NNN", "T-1"), ("[ticket title]", "e2e")):
        assert placeholder in fence
        fence = fence.replace(placeholder, value)
    return fence


def phase10b_ready_fence():
    text = section("## Phase 10b:", "## Phase 11:")
    assert text.index("**Thread rule:**") < text.index("**Mark ready-for-review:**")
    after = text[text.index("**Mark ready-for-review:**"):]
    return re.search(r"```bash\n(.*?)```", after, re.S).group(1)


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
        "origin": str(origin), "branch": BRANCH, "base": "main", "state": "OPEN", "body": "",
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


def run(p, *argv, extra_env=None):
    return subprocess.run([str(a) for a in argv], env={**p["env"], **(extra_env or {})},
                          capture_output=True, text=True, timeout=50)


def commit_create_ledger_wait(p):
    commit = run(p, BIN / "ds-ticket-commit", "--repo", p["repo"], "--branch", BRANCH, "--worktree-path", p["engineer"])
    create = run(p, "bash", "-c", phase9_create_fence(), extra_env={
        "UNIT_IS_BEHAVIOR_VISIBLE": "false", "DELIVERY_RECORD_OWNER": "spec", "DEVELOPER": "", "ENGINEER_MODEL": ""})
    ledger = run(p, BIN / "ds-ticket-finish", "ledger", "--repo", p["repo"], "--ticket", "T-1", "--branch", BRANCH,
                 "--gh-repo", "test/repo", "--loop-key", "t-1", "--rework-detection", "true",
                 "--risk-class", "Elevated", "--skeptic-rounds", "2", "--qa-status", "PASS")
    ci = run(p, BIN / "ds-ticket-ci", "--pr", "7", "--gh-repo", "test/repo", "--polls", "10", "--interval", "0")
    return commit, create, ledger, ci


def test_commit_through_merge_delivers_and_cleans_up(pipeline):
    p = pipeline
    engineer_sha = git("rev-parse", BRANCH, cwd=p["repo"])
    # Two stable all-green polls missing two required checks (the PR #839
    # shape) must not pass.
    set_polls(p, [
        [check("lint", "pass")],
        [check("lint", "pass")],
        [check("lint", "pass"), check("test", "pass"), check("build", "pass")],
    ])
    commit, create, ledger, ci = commit_create_ledger_wait(p)

    assert commit.returncode == 0, commit.stdout + commit.stderr
    assert git("--git-dir", str(p["origin"]), "rev-parse", "refs/heads/" + BRANCH) == engineer_sha
    assert not p["engineer"].exists(), commit.stdout + commit.stderr

    assert create.returncode == 0, create.stdout + create.stderr
    s = gh_state(p)
    creates = [c for c in s["calls"] if c[:2] == ["pr", "create"]]
    assert len(creates) == 1
    assert creates[0][creates[0].index("--head") + 1] == BRANCH and creates[0][creates[0].index("--base") + 1] == "main"
    assert s["draft"] is True, "Phase 9 opens a draft PR"
    assert "<!-- ds-delivery-record:v1:start -->" in s["body"] and "## North Star alignment" in s["body"]

    assert ledger.returncode == 0, ledger.stdout + ledger.stderr
    rows = [json.loads(line) for line in (p["repo"] / ".agentic/ticket-ledger.jsonl").read_text().splitlines()]
    assert [(r["ticket_id"], r["pr_number"], r["branch"], r["skeptic_rounds"]) for r in rows] == [("T-1", 7, BRANCH, 2)]

    assert ci.returncode == 0, ci.stdout + ci.stderr
    s = gh_state(p)
    checks_calls = [c for c in s["calls"] if c[:2] == ["pr", "checks"]]
    assert len(checks_calls) == 4, "polls missing required checks did not pass; two all-green polls with all required did"
    assert s["draft"] is True, "ds-ticket-ci leaves the ready step to Phase 10b"
    assert not any(c[:2] == ["pr", "merge"] for c in s["calls"]), "ds-ticket-ci never merges"

    ready = run(p, "bash", "-c", phase10b_ready_fence(), extra_env={"PR_NUMBER": "7", "GH_REPO": "test/repo"})
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
    commit, create, ledger, ci = commit_create_ledger_wait(p)

    assert commit.returncode == 0 and create.returncode == 0 and ledger.returncode == 0
    assert ci.returncode == 1, ci.stdout + ci.stderr
    assert "failing-checks: test" in ci.stdout
    s = gh_state(p)
    assert s["draft"] is True
    assert not any(c[:2] in (["pr", "merge"], ["pr", "ready"]) for c in s["calls"])

    # Phase 10 sends a red result to 10a; only a pass reaches 10b's ready.
    routing = section("**Outcome routing (exit code):**", "## Phase 10a:")
    assert "- **1** failed:" in routing and "Enter Phase 10a." in routing.split("- **1** failed:")[1].split("\n")[0]
    assert [line for line in routing.splitlines() if "Phase 10b" in line] == [
        line for line in routing.splitlines() if line.startswith("- **0** passed:")]
    # Merge is unreachable while the PR is a draft: a conductor that ran
    # ds-ticket-finish merge on this red result merges nothing.
    assessment = p["tmp"] / "assessment.json"
    assessment.write_text(json.dumps(record(git("--git-dir", str(p["origin"]), "rev-parse", "refs/heads/" + BRANCH))))
    finish = run(p, BIN / "ds-ticket-finish", "merge", "--repo", p["repo"], "--branch", BRANCH, "--ticket", "T-1",
                 "--gh-repo", "test/repo", "--pr", "7", "--delivery-record-input", assessment,
                 "--auto-merge", "true", "--base-branch", "main")
    assert "[phase: auto-merge-skipped | isDraft=true" in finish.stdout + finish.stderr
    assert not any(c[:2] == ["pr", "merge"] for c in gh_state(p)["calls"])
    assert git("--git-dir", str(p["origin"]), "rev-parse", "refs/heads/main") == main_before
