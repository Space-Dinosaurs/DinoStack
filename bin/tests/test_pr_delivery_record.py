"""Purpose: Exercise the publisher and calling Markdown against a persistent fake GitHub.
Public API: pytest-discovered test cases and the github fixture.
Upstream deps: pytest, Python stdlib, lib.md_shell_extract, publisher CLI and calling Markdown.
Downstream consumers: bin-tests CI and local pytest runs.
Failure modes: assertion failures or subprocess timeouts; GitHub state stays in temporary files.
Performance: subprocess-backed cases; no network calls.
"""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.md_shell_extract import extract_marked_block

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "bin/ds-pr-delivery-record"
REFERENCE = ROOT / "content/references/delivery-record.md"
TICKET = ROOT / "content/commands/ds-implement-ticket.md"
CONVENTIONS = ROOT / "content/references/conventions-detail.md"
A, B, C = "a" * 40, "b" * 40, "c" * 40
START = "<!-- ds-delivery-record:v1:start -->"
END = "<!-- ds-delivery-record:v1:end -->"

GH = r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p=Path(os.environ['FAKE_GH_STATE']); s=json.loads(p.read_text()); args=sys.argv[1:]
s['calls'].append(args)
def done(output=None, code=0):
    p.write_text(json.dumps(s))
    if output is not None: print(json.dumps(output))
    sys.exit(code)
if args[:2] == ['pr','view']:
    fields=args[args.index('--json')+1]
    if fields == 'headRefOid,body,url':
        s['views']=s.get('views',0)+1
        n=str(s['views'])
        if n in s.get('move_at',{}): s['head']=s['move_at'][n]
        if n in s.get('body_at',{}): s['body']+=s['body_at'][n]
        done({'headRefOid':s['head'],'body':s['body'],'url':'https://github.com/test/repo/pull/7'})
    if fields == 'reviewDecision':
        if s.get('review_failure'): done(code=1)
        done({'reviewDecision':s.get('decision','')})
    if fields == 'autoMergeRequest':
        if s.get('queue_failure'): done(code=1)
        done({'autoMergeRequest':s.get('queue')})
    if fields == 'isDraft,mergeable,reviewDecision':
        done({'isDraft':False,'mergeable':'MERGEABLE','reviewDecision':'NONE'})
    if fields == 'commits':
        p.write_text(json.dumps(s)); print(s.get('headline','feat: test')); sys.exit(0)
    if fields == 'isDraft':
        p.write_text(json.dumps(s)); print('false'); sys.exit(0)
    if fields == 'state':
        p.write_text(json.dumps(s)); print('OPEN'); sys.exit(0)
if args[:2] == ['pr','edit']:
    if s.get('edit_failure'): done(code=1)
    s['body']=Path(args[args.index('--body-file')+1]).read_text()
    if s.get('corrupt_readback'): s['body']+='concurrent edit'
    s['edits']=s.get('edits',0)+1
    done()
if args[:2] == ['pr','list']:
    done(s.get('siblings',[]))
if args[:2] == ['pr','update-branch']:
    s['head']='b'*40; done()
if args[:2] == ['pr','ready']: done()
if args[:2] == ['pr','merge']:
    if '--disable-auto' in args:
        if s.get('disable_failure'): done(code=1)
        s['queue']=None; done()
    if s.get('race_merge'): s['head']=s.pop('race_merge')
    if '--match-head-commit' not in args: s['unguarded']=True; done(code=1)
    requested=args[args.index('--match-head-commit')+1]
    if requested != s['head']: s['rejected']=True; done(code=1)
    s['accepted']=s.get('accepted',[])+[requested]; done()
done(code=1)
"""


def record(head=A):
    check = {
        "result": "PENDING",
        "scope": "required evidence at remote head",
        "coverage": "UNKNOWN",
        "evidence_sha": None,
        "evidence": [],
        "reason": "owner must collect applicable evidence",
        "pending_owner": "PR owner",
        "waiver": None,
    }
    return {
        "version": 1,
        "head_sha": head,
        "record_owner": "PR owner",
        "risk": "Elevated",
        "policy": {
            "source": "project policy; GitHub discovery pending",
            "github_requirement": "unknown: owner must inspect rules",
            "github_review_decision": "UNKNOWN",
            "protocol_requirement": "Skeptic and QA",
            "override": None,
        },
        "checks": {k: copy.deepcopy(check) for k in ("human_approval", "protocol_review", "ci", "qa", "uat")},
    }


def passed(head=A):
    return {
        "result": "PASS",
        "scope": "publisher CLI fixtures; no human UAT",
        "coverage": "EXACT",
        "evidence_sha": head,
        "performed_by": "QA agent",
        "evidence": [
            {
                "locator": "/tmp/tests.log",
                "visibility": "local",
                "summary": "CLI fixture tests passed, only mocked GitHub calls exercised",
            }
        ],
        "reason": None,
        "pending_owner": None,
        "waiver": None,
    }


@pytest.fixture
def github(tmp_path):
    state = tmp_path / "github.json"
    state.write_text(
        json.dumps(
            {
                "head": A,
                "body": "User prose\n## Review rigor\n- Findings summary: pending\n## North Star alignment\nPillar 2\n## QA Evidence\nScoped tests",
                "calls": [],
            }
        )
    )
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(GH)
    gh.chmod(0o755)
    (bindir / "ds-pr-delivery-record").symlink_to(CLI)
    env = {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ["PATH"], "FAKE_GH_STATE": str(state)}
    return tmp_path, state, env


def state_get(github):
    return json.loads(github[1].read_text())


def alter(github, **updates):
    state = state_get(github)
    state.update(updates)
    github[1].write_text(json.dumps(state))


def publish(github, data=None):
    path = github[0] / "assessment.json"
    path.write_text(json.dumps(data if data is not None else record()))
    proc = subprocess.run(
        [str(CLI), "--repo", "test/repo", "--pr", "7", "--input", str(path)],
        env=github[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc, json.loads(proc.stdout)


def test_publish_refresh_preserves_body_and_local_scope(github):
    original = state_get(github)["body"]
    data = record()
    data["checks"]["qa"] = passed()
    proc, result = publish(github, data)
    assert proc.returncode == 0, proc.stderr
    assert result["published_sha"] == A
    body = state_get(github)["body"]
    assert body.startswith(original)
    assert "unavailable remotely" in body and "/tmp/tests.log" in body
    assert "github_review_decision: NONE" in body
    proc, _ = publish(github, data)
    assert proc.returncode == 0
    assert state_get(github)["body"].count(START) == 1
    assert state_get(github)["body"].count(END) == 1


@pytest.mark.parametrize("result", ["FAIL", "INCONCLUSIVE"])
def test_attempted_check_with_unknown_sha_rendering(github, result):
    data = record()
    check = passed()
    check.update(
        result=result,
        coverage="UNKNOWN",
        evidence_sha=None,
        reason="Execution attempted; checked SHA unavailable",
        pending_owner="PR owner",
    )
    data["checks"]["qa"] = check
    proc, publication = publish(github, data)
    assert proc.returncode == 0, proc.stderr
    assert publication["published_sha"] == A
    body = state_get(github)["body"]
    qa_row = next(line for line in body.splitlines() if line.startswith("| qa |"))
    assert f"| qa | {result} / UNKNOWN (pending coverage)" in qa_row
    assert "none (not executed or SHA unknown)" in qa_row
    assert "none (no execution claimed)" not in body


@pytest.mark.parametrize(
    "mutation", ["owner", "reason", "na", "waiver", "actor", "sha", "exact", "delta", "checks", "visibility"]
)
def test_validation_rejects_incomplete_claims_without_edit(github, mutation):
    data = record()
    c = data["checks"]["qa"]
    if mutation == "owner":
        c["pending_owner"] = None
    if mutation == "reason":
        c["reason"] = ""
    if mutation == "na":
        c.update(result="N/A", coverage="EXACT", pending_owner=None, reason="")
    if mutation == "waiver":
        c.update(
            result="WAIVED",
            coverage="EXACT",
            waiver={"authorized_by": "agent", "reason": "wanted to merge", "evidence": []},
        )
    if mutation == "actor":
        data["checks"]["qa"] = passed()
        del data["checks"]["qa"]["performed_by"]
    if mutation == "sha":
        data["head_sha"] = "local HEAD"
    if mutation == "exact":
        data["checks"]["qa"] = passed(B)
    if mutation == "delta":
        data["checks"]["qa"] = passed(B)
        data["checks"]["qa"]["coverage"] = "DELTA_ASSESSED"
    if mutation == "checks":
        del data["checks"]["uat"]
    if mutation == "visibility":
        data["checks"]["qa"] = passed()
        data["checks"]["qa"]["evidence"][0]["visibility"] = "private"
    proc, result = publish(github, data)
    assert proc.returncode == 1 and result["published_sha"] is None
    assert not state_get(github).get("edits")


@pytest.mark.parametrize(
    "body", [START, END, END + START, START + END + START + END, "<!-- ds-delivery-record:v1:start"]
)
def test_malformed_markers_fail_without_edit(github, body):
    alter(github, body=body)
    proc, result = publish(github)
    assert proc.returncode == 1 and result["published_sha"] is None
    assert not state_get(github).get("edits")


@pytest.mark.parametrize("at", ["1", "2", "3"])
def test_head_races_never_report_success(github, at):
    alter(github, move_at={at: B})
    proc, result = publish(github)
    assert proc.returncode == 2 and result["published_sha"] is None and result["observed_sha"] == B
    if at != "3":
        assert not state_get(github).get("edits")


@pytest.mark.parametrize("fault", ["edit_failure", "corrupt_readback"])
def test_api_readback_failure_is_visible(github, fault):
    alter(github, **{fault: True})
    proc, result = publish(github)
    assert proc.returncode == 1 and result["published_sha"] is None and proc.stderr


def test_review_discovery_failure_is_unknown_not_none(github):
    alter(github, review_failure=True)
    assert publish(github)[0].returncode == 0
    assert "github_review_decision: UNKNOWN" in state_get(github)["body"]


def test_one_concurrent_body_rebuild_preserves_new_prose(github):
    alter(github, body_at={"2": "\nAdded during collection"})
    assert publish(github)[0].returncode == 0
    assert "Added during collection" in state_get(github)["body"]


def test_repeated_body_contention_fails_before_write(github):
    alter(github, body_at={"2": " first edit", "3": " second edit"})
    proc, result = publish(github)
    assert proc.returncode == 1 and result["published_sha"] is None
    assert not state_get(github).get("edits")


def test_delta_chain_preserves_execution_sha(github):
    alter(github, head=C)
    data = record(C)
    c = passed()
    c["coverage"] = "DELTA_ASSESSED"
    c["coverage_transitions"] = [
        {
            "from_sha": A,
            "to_sha": B,
            "assessed_by": "reviewer",
            "reason": "compared metadata-only change",
            "evidence": c["evidence"],
        },
        {
            "from_sha": B,
            "to_sha": C,
            "assessed_by": "reviewer",
            "reason": "compared new base and conflicts",
            "evidence": c["evidence"],
        },
    ]
    data["checks"]["qa"] = c
    assert publish(github, data)[0].returncode == 0
    assert A in state_get(github)["body"] and "DELTA_ASSESSED" in state_get(github)["body"]
    c["coverage_transitions"][1]["from_sha"] = A
    assert publish(github, data)[0].returncode == 1


def source(path, marker):
    return extract_marked_block(str(path), marker)


def run_source(github, script, **assignments):
    import shlex

    pre = "\n".join(
        f"{k}={shlex.quote(v)}"
        for k, v in {
            "GH_REPO": "test/repo",
            "PR_NUMBER": "7",
            "AUTO_MERGE_ON_CI_GREEN": "true",
            "DELIVERY_RECORD_INPUT": str(github[0] / "assessment.json"),
            **assignments,
        }.items()
    )
    return subprocess.run(
        ["bash", "-c", pre + "\n" + script], env=github[2], cwd=github[0], capture_output=True, text=True, timeout=30
    )


@pytest.mark.parametrize(
    "consumer", ["universal", "sibling-owner", "admin", "ticket-immediate", "ticket-auto", "timeout"]
)
def test_publish_to_request_race_requires_fresh_assessment(github, consumer):
    publish(github)
    alter(github, race_merge=B)
    if consumer in ("ticket-immediate", "ticket-auto"):
        if consumer == "ticket-auto":
            alter(github, headline="chore(knowledge): tests")
        script = source(TICKET, "phase12-auto-merge")
        assignments = {}
    elif consumer == "timeout":
        script = source(CONVENTIONS, "phase10-timeout-auto-merge-queue")
        assignments = {"TIMEOUT_POLLS": "2"}
    else:
        script = source(REFERENCE, "delivery-record-publish") + "\n" + source(REFERENCE, "delivery-record-merge")
        assignments = {
            "DELIVERY_MERGE_MODE": "admin"
            if consumer == "admin"
            else "auto"
            if consumer == "sibling-owner"
            else "immediate"
        }
    run_source(github, script, **assignments)
    state = state_get(github)
    assert state.get("rejected") and not state.get("accepted") and not state.get("unguarded")
    calls = [x for x in state["calls"] if x[:2] == ["pr", "merge"] and "--disable-auto" not in x]
    assert len(calls) == 1 and calls[0][calls[0].index("--match-head-commit") + 1] == A
    # A fresh publication alone cannot move the old evidence onto B.
    assert publish(github)[0].returncode == 2
    data = record(B)
    data["checks"]["qa"] = passed()
    data["checks"]["qa"].update(coverage="STALE", reason="owner must compare new head", pending_owner="PR owner")
    assert publish(github, data)[0].returncode == 0
    data["checks"]["qa"] = passed(B)
    assert publish(github, data)[0].returncode == 0
    run_source(github, script, **assignments)
    assert state_get(github)["accepted"] == [B]


@pytest.mark.parametrize("bad", ["{}", '{"published_sha":null}', '{"published_sha":"HEAD"}', "not json"])
@pytest.mark.parametrize("consumer", ["universal", "ticket", "timeout"])
def test_bad_success_output_never_merges(github, bad, consumer):
    import shlex

    stub = github[0] / "bin/ds-pr-delivery-record"
    stub.unlink()
    stub.write_text("#!/bin/sh\nprintf '%s\\n' " + shlex.quote(bad) + "\n")
    stub.chmod(0o755)
    script = (
        source(REFERENCE, "delivery-record-publish") + "\n" + source(REFERENCE, "delivery-record-merge")
        if consumer == "universal"
        else source(TICKET, "phase12-auto-merge")
        if consumer == "ticket"
        else source(CONVENTIONS, "phase10-timeout-auto-merge-queue")
    )
    run_source(github, script, DELIVERY_MERGE_MODE="immediate", TIMEOUT_POLLS="2")
    assert not [c for c in state_get(github)["calls"] if c[:2] == ["pr", "merge"]]


@pytest.mark.parametrize("disable_failure", [True, False])
def test_sibling_suspends_before_rebase_and_never_requeues(github, disable_failure):
    alter(
        github,
        queue={"enabled": True},
        disable_failure=disable_failure,
        siblings=[{"number": 7, "mergeStateStatus": "BEHIND", "isDraft": False, "autoMergeRequest": {"enabled": True}}],
    )
    result = run_source(github, source(CONVENTIONS, "sibling-pr-sweep"), BASE_BRANCH="main")
    calls = state_get(github)["calls"]
    disables = [c for c in calls if "--disable-auto" in c]
    rebases = [c for c in calls if c[:2] == ["pr", "update-branch"]]
    assert len(disables) == 1
    assert len(rebases) == (0 if disable_failure else 1)
    assert not state_get(github).get("accepted")
    if rebases:
        assert calls.index(disables[0]) < calls.index(rebases[0])
        assert "pending-coverage-queue-off" in result.stdout
        data = record(B)
        data["checks"]["qa"] = passed()
        data["checks"]["qa"].update(coverage="STALE", reason="assess rebase/base context", pending_owner="owning flow")
        assert publish(github, data)[0].returncode == 0
        assert "| qa | PASS / STALE (pending coverage)" in state_get(github)["body"]


@pytest.mark.parametrize("queued,disable_failure", [(True, False), (True, True), (False, False)])
def test_remote_knowledge_push_and_delivery_refresh(github, queued, disable_failure):
    import test_phase11e_knowledge_commit_shell as knowledge

    knowledge_dir = github[0] / "knowledge"
    knowledge_dir.mkdir()
    fixture = knowledge.git_fixture.build_knowledge_consumer_shape(knowledge_dir)
    local = knowledge._git(fixture, "rev-parse", "HEAD").stdout.strip()
    alter(github, head=local, queue={"enabled": True} if queued else None, disable_failure=disable_failure)
    import shutil

    wrapper = github[0] / "bin/git"
    wrapper.write_text(
        "#!/usr/bin/env python3\nimport json,os,subprocess,sys\nfrom pathlib import Path\np=Path(os.environ['FAKE_GH_STATE'])\na=sys.argv[1:]\nif 'push' in a:\n s=json.loads(p.read_text()); s['calls'].append(['git','push']); s['push_when_queued']=s.get('queue') is not None; p.write_text(json.dumps(s))\nr=subprocess.run(["
        + repr(shutil.which("git"))
        + "]+a)\nif 'push' in a and r.returncode == 0:\n s=json.loads(p.read_text()); s['head']=a[-1].split(':')[0]; p.write_text(json.dumps(s))\nsys.exit(r.returncode)\n"
    )
    wrapper.chmod(0o755)
    fixture.env["PATH"] = github[2]["PATH"]
    fixture.env["FAKE_GH_STATE"] = github[2]["FAKE_GH_STATE"]
    result = subprocess.run(
        ["bash", "-c", knowledge._script(fixture)],
        cwd=fixture.repo_dir,
        env=fixture.env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    knowledge._assert_completed(result)
    remote = knowledge._git(fixture, "rev-parse", fixture.branch_name, cwd=fixture.origin_dir).stdout.strip()
    assert knowledge._git(fixture, "rev-parse", "HEAD").stdout.strip() == local
    if disable_failure:
        assert remote == local and "head unchanged" in result.stdout
        return
    assert remote != local
    assert state_get(github)["push_when_queued"] is False
    data = record(remote)
    data["checks"]["qa"] = passed(local)
    data["checks"]["qa"].update(coverage="STALE", reason="assess new remote knowledge commit", pending_owner="PR owner")
    alter(github, head=remote)
    proc, output = publish(github, data)
    assert proc.returncode == 0 and output["published_sha"] == remote
    body = state_get(github)["body"]
    assert remote in body and local in body and "PASS / STALE (pending coverage)" in body
    calls = state_get(github)["calls"]
    if queued:
        disable = [c for c in calls if "--disable-auto" in c][0]
        assert calls.index(disable) < calls.index(["git", "push"])
        assert state_get(github)["queue"] is None


@pytest.mark.parametrize("consumer", ["universal", "ticket", "timeout"])
def test_sha_with_trailing_newline_is_not_a_published_sha(github, consumer):
    test_bad_success_output_never_merges(github, json.dumps({"published_sha": A + "\n"}), consumer)


def test_valid_applicability_and_authorized_waiver_are_distinct(github):
    data = record()
    data["checks"]["uat"].update(
        result="N/A",
        coverage="EXACT",
        reason="No human UAT requested or required by project policy",
        pending_owner=None,
    )
    data["checks"]["protocol_review"].update(
        result="WAIVED",
        coverage="EXACT",
        reason="Existing non-Critical iteration-cap exception at declared head",
        waiver={
            "authorized_by": "project maintainer",
            "authority": "existing project iteration-cap policy",
            "reason": "non-Critical cap accepted at this head",
            "evidence": [
                {
                    "locator": "https://example.test/policy",
                    "visibility": "public",
                    "summary": "Maintainer authorized the existing non-Critical cap exception; no Critical waiver",
                }
            ],
        },
    )
    data["checks"]["human_approval"] = passed()
    data["checks"]["human_approval"].update(
        performed_by="human reviewer Alice",
        scope="Actual human review of publisher changes",
        evidence=[
            {
                "locator": "https://example.test/review",
                "visibility": "public",
                "summary": "Alice reviewed the publisher at this exact SHA",
            }
        ],
    )
    proc, _ = publish(github, data)
    assert proc.returncode == 0
    body = state_get(github)["body"]
    assert "human reviewer Alice" in body and "WAIVED / EXACT" in body and "N/A / EXACT" in body
