#!/usr/bin/env python3
"""
Purpose: pytest suite for bin/ds-branch-prune (DS-153). Builds synthetic git
         repositories in tmp_path with real `git merge --squash` and drives
         the CLI end-to-end (subprocess) plus a few direct unit-level checks
         of the diff/patch-id discrimination mechanics, per the plan's Test
         strategy section and Amendments B1/B2/B12.

Public API: none (test module; invoked via `python3 -m pytest`).

Upstream deps: bin/ds-branch-prune (module under test, invoked both as a
               subprocess CLI and, for a couple of direct checks, imported
               by path); real `git` CLI (subprocess); NO REAL `gh`
               invocation anywhere in this file, and no network access.
               Scenarios reach that state one of three ways: injecting
               merged-PR data via `--pr-data <file>`, omitting it via
               `--no-gh`, or - for the cursor-pagination and
               totalCount-reconciliation coverage - stubbing the `gh`
               boundary with `_install_fake_gh`, which monkeypatches the
               module's own `_run` wrapper (serving canned `gh repo view`
               and `gh api graphql` responses while delegating every other
               argv to the real subprocess) plus `shutil.which`, so those
               tests behave identically on a runner with no `gh` installed
               and no auth configured.

Downstream consumers: CI (`python3 -m pytest bin/tests/ -q`, auto-collected
                      per `.github/workflows/bin-tests.yml`); this ticket's
                      QA gate scenarios 1-6.

Failure modes: a missing --pr-data fixture file must error (never silently
               skip) - test_missing_pr_data_file_is_usage_error pins this
               directly. All fixture repos are built under tmp_path and
               torn down by pytest; no real DinoStack checkout, worktree,
               or branch state is ever touched by this file. Every
               `gh`-stubbing test asserts on the returned
               (data, degraded, incomplete_reason) triple rather than on
               log text alone, so a silently-degraded run cannot pass as a
               successful fetch.

Performance: each scenario performs a handful of real `git` subprocess
             calls (init, commit, squash-merge, worktree add) plus one
             `ds-branch-prune` subprocess invocation. Sub-second per test.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "ds-branch-prune"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import importlib.machinery as _ilm  # noqa: E402
import importlib.util as _ilu  # noqa: E402

_loader = _ilm.SourceFileLoader("ds_branch_prune", str(SCRIPT))
_spec = _ilu.spec_from_loader("ds_branch_prune", _loader)
ds_branch_prune = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
_loader.exec_module(ds_branch_prune)


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str, input_text: str = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_text,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"git {args} failed: {proc.stderr}\n{proc.stdout}"
    return proc


def _rev_parse(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", ref).stdout.strip()


def init_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "spec@example.com")
    _git(repo, "config", "user.name", "spec")
    (repo / "README.md").write_text("init\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def write_file(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content)


def squash_merge(repo: Path, branch: str, message: str) -> str:
    """Squash-merges `branch` into the currently checked-out branch (assumed
    main) via real `git merge --squash` + `git commit`, exactly like GitHub's
    squash-merge button. Returns the resulting merge commit's sha."""
    _git(repo, "merge", "--squash", branch)
    _git(repo, "commit", "-q", "-m", message)
    return _rev_parse(repo, "HEAD")


def pr_data_file(tmp_path: Path, prs: list, name: str = "pr-data.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps(prs))
    return str(path)


def run_prune(repo: Path, *, pr_data: str = None, base: str = "main", no_gh: bool = False, dry_run: bool = True, extra=None):
    cmd = [sys.executable, str(SCRIPT), "--repo", str(repo), "--base", base, "--explain"]
    if dry_run:
        cmd.append("--dry-run")
    if pr_data:
        cmd += ["--pr-data", pr_data]
    if no_gh:
        cmd.append("--no-gh")
    if extra:
        cmd += extra
    return subprocess.run(cmd, capture_output=True, text=True)


def outcomes(stdout: str) -> dict:
    result = {}
    in_explain = False
    for line in stdout.splitlines():
        if line.strip() == "-- per-branch --":
            in_explain = True
            continue
        if in_explain and ": " in line:
            branch, rest = line.split(": ", 1)
            result[branch.strip()] = rest.strip()
    return result


# --------------------------------------------------------------------------
# Scenario fixtures (each builds a repo shape from the plan's Test strategy
# table)
# --------------------------------------------------------------------------


def build_clean_squash(tmp_path: Path, name: str = "repo") -> tuple:
    """Scenario: clean squash-merge, main untouched since. Returns
    (repo, pr_data_path, feat_tip_sha, merge_commit_sha)."""
    repo = init_repo(tmp_path, name)
    _git(repo, "checkout", "-q", "-b", "feat")
    write_file(repo, "x.txt", "hello\n")
    _git(repo, "add", "x.txt")
    _git(repo, "commit", "-q", "-m", "add x")
    feat_tip = _rev_parse(repo, "feat")

    _git(repo, "checkout", "-q", "main")
    mc = squash_merge(repo, "feat", "squash feat")

    prs = [{"number": 1, "headRefName": "feat", "headRefOid": feat_tip, "mergeCommit": {"oid": mc}}]
    pr_path = pr_data_file(tmp_path, prs, name=f"{name}-pr-data.json")
    return repo, pr_path, feat_tip, mc


def build_squash_then_main_diverges(tmp_path: Path, name: str = "repo2") -> tuple:
    """Scenario: clean squash-merge, LATER PR modified the same file. L4
    decays (own overlaps on_main); only L2 (patch-id vs the historical
    squash commit) can still prove subsumption."""
    repo, pr_path, feat_tip, mc = build_clean_squash(tmp_path, name)
    # A later commit on main touches the SAME file feat touched.
    write_file(repo, "x.txt", "hello\nmore\n")
    _git(repo, "add", "x.txt")
    _git(repo, "commit", "-q", "-m", "later change to x.txt")
    return repo, pr_path, feat_tip, mc


# --------------------------------------------------------------------------
# 1. clean squash-merge, main untouched since -> DELETE via L2
# --------------------------------------------------------------------------


def test_clean_squash_merge_deletes_via_l2(tmp_path):
    repo, pr_path, _, _ = build_clean_squash(tmp_path)
    proc = run_prune(repo, pr_data=pr_path)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result["feat"] == "DELETE via L2"


# --------------------------------------------------------------------------
# 2. clean squash-merge, later PR modified the same file -> DELETE via L2
#    (proves non-decay: L4 alone would skip)
# --------------------------------------------------------------------------


def test_squash_merge_survives_later_main_divergence_via_l2(tmp_path):
    repo, pr_path, _, _ = build_squash_then_main_diverges(tmp_path)
    proc = run_prune(repo, pr_data=pr_path)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result["feat"] == "DELETE via L2"

    # Companion assertion proving the "L4 alone would skip" claim: with no
    # PR data at all (degraded mode), L4 must fail on THIS repo because main
    # has since diverged on the same file feat touched.
    proc_no_gh = run_prune(repo, no_gh=True)
    assert proc_no_gh.returncode == 0, proc_no_gh.stderr
    result_no_gh = outcomes(proc_no_gh.stdout)
    assert result_no_gh["feat"] == "SKIP_UNPROVEN"


# --------------------------------------------------------------------------
# 3. squash-merged PLUS one extra local commit -> SKIP
#    Vacuity proof 1: built directly on scenario 1's fixture (SAME PR data)
#    - proving PR data actually loads (scenario 1 deletes on this exact
#      fixture shape; this scenario, which differs only by one extra local
#      commit, must SKIP). Asserting both directions on related fixtures is
#      what proves the PR data actually loads rather than everything
#      trivially skipping regardless of input.
# --------------------------------------------------------------------------


def test_squash_merge_plus_extra_local_commit_is_skipped(tmp_path):
    repo, pr_path, _, _ = build_clean_squash(tmp_path)
    _git(repo, "checkout", "-q", "feat")
    write_file(repo, "y.txt", "unmerged extra work\n")
    _git(repo, "add", "y.txt")
    _git(repo, "commit", "-q", "-m", "extra work never merged")
    _git(repo, "checkout", "-q", "main")

    proc = run_prune(repo, pr_data=pr_path)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result["feat"] == "SKIP_UNPROVEN"

    # This is exactly what the old pr_state==MERGED predicate would have
    # deleted (a MERGED PR candidate still matches by branch name) - the
    # terminal SKIP_PR_MERGED_UNPROVEN in worktree_model.py is what stops it.
    assert "DELETE" not in result["feat"]


# --------------------------------------------------------------------------
# 4. tip is an ancestor of the merged head -> DELETE via L3
# --------------------------------------------------------------------------


def test_tip_ancestor_of_merged_head_deletes_via_l3(tmp_path):
    repo = init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feat")
    write_file(repo, "y.txt", "part one\n")
    _git(repo, "add", "y.txt")
    _git(repo, "commit", "-q", "-m", "c1")
    c1 = _rev_parse(repo, "feat")

    write_file(repo, "z.txt", "part two\n")
    _git(repo, "add", "z.txt")
    _git(repo, "commit", "-q", "-m", "c2")
    c2 = _rev_parse(repo, "feat")  # this is H: the full head that got merged

    _git(repo, "checkout", "-q", "main")
    mc = squash_merge(repo, "feat", "squash feat (c1+c2)")

    # Local branch is behind H: reset feat to c1 only.
    _git(repo, "branch", "-f", "feat", c1)

    prs = [{"number": 1, "headRefName": "feat", "headRefOid": c2, "mergeCommit": {"oid": mc}}]
    pr_path = pr_data_file(tmp_path, prs)

    proc = run_prune(repo, pr_data=pr_path)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result["feat"] == "DELETE via L3"


# --------------------------------------------------------------------------
# 5. tip == merged head exactly -> DELETE via L2 or L3
# --------------------------------------------------------------------------


def test_tip_equals_merged_head_deletes(tmp_path):
    repo, pr_path, feat_tip, mc = build_clean_squash(tmp_path)
    proc = run_prune(repo, pr_data=pr_path)
    result = outcomes(proc.stdout)
    assert result["feat"] in ("DELETE via L2", "DELETE via L3")


# --------------------------------------------------------------------------
# 6. branch name reused by an unrelated later PR -> SKIP (patch mismatch)
# --------------------------------------------------------------------------


def test_branch_name_reused_by_unrelated_pr_is_skipped(tmp_path):
    repo = init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feat")
    write_file(repo, "q.txt", "totally unrelated content\n")
    _git(repo, "add", "q.txt")
    _git(repo, "commit", "-q", "-m", "unrelated local work")

    _git(repo, "checkout", "-q", "main")
    # A completely separate squash merge (simulating a DIFFERENT branch's
    # PR that happened to reuse the name "feat" historically).
    _git(repo, "checkout", "-q", "-b", "other")
    write_file(repo, "r.txt", "some other content entirely\n")
    _git(repo, "add", "r.txt")
    _git(repo, "commit", "-q", "-m", "other work")
    _git(repo, "checkout", "-q", "main")
    mc = squash_merge(repo, "other", "squash other, mislabeled as feat's PR")

    prs = [{"number": 2, "headRefName": "feat", "headRefOid": "0" * 40, "mergeCommit": {"oid": mc}}]
    pr_path = pr_data_file(tmp_path, prs)

    proc = run_prune(repo, pr_data=pr_path)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result["feat"] == "SKIP_UNPROVEN"


# --------------------------------------------------------------------------
# 7. local name differs from PR head name, linked by upstream -> DELETE
# --------------------------------------------------------------------------


def test_local_name_differs_linked_by_upstream_deletes(tmp_path):
    repo = init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "local-name")
    write_file(repo, "u.txt", "upstream-linked content\n")
    _git(repo, "add", "u.txt")
    _git(repo, "commit", "-q", "-m", "work")
    tip = _rev_parse(repo, "local-name")

    # Configure upstream tracking directly (rather than --set-upstream-to,
    # which requires the target ref to already exist as a real branch) -
    # `%(upstream:short)` derives purely from this config.
    _git(repo, "config", "branch.local-name.remote", "origin")
    _git(repo, "config", "branch.local-name.merge", "refs/heads/pr-head-name")

    _git(repo, "checkout", "-q", "main")
    mc = squash_merge(repo, "local-name", "squash local-name")

    prs = [{"number": 3, "headRefName": "pr-head-name", "headRefOid": tip, "mergeCommit": {"oid": mc}}]
    pr_path = pr_data_file(tmp_path, prs)

    proc = run_prune(repo, pr_data=pr_path)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result["local-name"].startswith("DELETE")


# --------------------------------------------------------------------------
# 8. local name and upstream both unrelated, tip SHA matches -> DELETE
#    (tip-SHA key)
# --------------------------------------------------------------------------


def test_tip_sha_key_deletes_despite_unrelated_name_and_no_upstream(tmp_path):
    repo = init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "totally-different-local-name")
    write_file(repo, "v.txt", "sha-keyed content\n")
    _git(repo, "add", "v.txt")
    _git(repo, "commit", "-q", "-m", "work")
    tip = _rev_parse(repo, "totally-different-local-name")

    _git(repo, "checkout", "-q", "main")
    mc = squash_merge(repo, "totally-different-local-name", "squash")

    # headRefName is unrelated to the local branch name and no upstream is
    # configured at all - only headRefOid == tip_sha can join this candidate.
    prs = [{"number": 4, "headRefName": "some-pr-branch-name", "headRefOid": tip, "mergeCommit": {"oid": mc}}]
    pr_path = pr_data_file(tmp_path, prs)

    proc = run_prune(repo, pr_data=pr_path)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result["totally-different-local-name"].startswith("DELETE")


# --------------------------------------------------------------------------
# 9. never-merged WIP -> SKIP
# --------------------------------------------------------------------------


def test_never_merged_wip_is_skipped(tmp_path):
    repo = init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "wip")
    write_file(repo, "w.txt", "work in progress\n")
    _git(repo, "add", "w.txt")
    _git(repo, "commit", "-q", "-m", "wip commit")
    _git(repo, "checkout", "-q", "main")

    proc = run_prune(repo, no_gh=True)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result["wip"] == "SKIP_UNPROVEN"


# --------------------------------------------------------------------------
# 10. fast-forward (non-squash) merge -> DELETE via L1
# --------------------------------------------------------------------------


def test_fast_forward_merge_deletes_via_l1(tmp_path):
    repo = init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "ff-feat")
    write_file(repo, "f.txt", "fast forward content\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "ff commit")

    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--ff-only", "ff-feat")

    proc = run_prune(repo, no_gh=True)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result["ff-feat"] == "DELETE via L1"


# --------------------------------------------------------------------------
# 11. branch checked out in a linked worktree -> SKIP_CHECKED_OUT
# --------------------------------------------------------------------------


def test_checked_out_branch_is_skipped(tmp_path):
    repo = init_repo(tmp_path)
    wt_path = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "checked-out-branch", str(wt_path))

    try:
        proc = run_prune(repo, no_gh=True)
        assert proc.returncode == 0, proc.stderr
        result = outcomes(proc.stdout)
        assert result["checked-out-branch"] == "SKIP_CHECKED_OUT"
    finally:
        _git(repo, "worktree", "remove", "--force", str(wt_path))


# --------------------------------------------------------------------------
# 12. main / BASE_BRANCH with fabricated merged-PR data -> SKIP_BASE_BRANCH
# --------------------------------------------------------------------------


def test_base_branch_never_deleted_even_with_fabricated_merged_pr(tmp_path):
    repo = init_repo(tmp_path)
    main_tip = _rev_parse(repo, "main")
    # Fabricate a merged-PR record that "proves" main was merged into itself.
    prs = [{"number": 5, "headRefName": "main", "headRefOid": main_tip, "mergeCommit": {"oid": main_tip}}]
    pr_path = pr_data_file(tmp_path, prs)

    proc = run_prune(repo, pr_data=pr_path)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result["main"] == "SKIP_BASE_BRANCH"


def test_develop_and_development_never_deleted_even_when_not_the_configured_base(tmp_path):
    """M3 fix (Skeptic round 2): G0 must protect `develop`/`development`
    UNCONDITIONALLY, not only the local name of whatever `--base` happens to
    be passed. Reproduces the shipped session-start call site
    (content/references/worktree-lifecycle.md, content/commands/
    ds-cleanup-worktrees.md Step 3), which invokes `ds-branch-prune` with NO
    `--base` at all by design - a repo using a develop-based workflow
    (content/rules/conventions.md Base branch resolution) needs `develop`
    protected even when `--base` resolves to something else entirely. Here
    `--base main` is passed explicitly (matching this suite's other tests,
    which need a local ref to compute merge-base against), with both
    `develop` and `development` fully merged into `main` and a fabricated
    merged-PR record "proving" each - the exact shape the old
    `pr_state == "MERGED"` predicate, and the pre-fix guard set (main,
    master, and only the local name of --base), would have deleted.
    """
    repo = init_repo(tmp_path)
    for name in ("develop", "development"):
        _git(repo, "checkout", "-q", "-b", name, "main")
        write_file(repo, f"{name}.txt", f"{name} content\n")
        _git(repo, "add", f"{name}.txt")
        _git(repo, "commit", "-q", "-m", f"{name} work")
        _git(repo, "checkout", "-q", "main")
        _git(repo, "merge", "-q", "--ff-only", name)

    develop_tip = _rev_parse(repo, "develop")
    development_tip = _rev_parse(repo, "development")
    prs = [
        {"number": 9, "headRefName": "develop", "headRefOid": develop_tip, "mergeCommit": {"oid": develop_tip}},
        {
            "number": 10,
            "headRefName": "development",
            "headRefOid": development_tip,
            "mergeCommit": {"oid": development_tip},
        },
    ]
    pr_path = pr_data_file(tmp_path, prs)

    proc = run_prune(repo, pr_data=pr_path, base="main")
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result["develop"] == "SKIP_BASE_BRANCH"
    assert result["development"] == "SKIP_BASE_BRANCH"


# --------------------------------------------------------------------------
# 13. unrelated root history -> SKIP_NO_MERGE_BASE
# --------------------------------------------------------------------------


def test_unrelated_root_history_is_skipped(tmp_path):
    repo = init_repo(tmp_path)
    _git(repo, "checkout", "-q", "--orphan", "orphan-branch")
    _git(repo, "rm", "-rf", ".")  # remove from index AND working tree
    write_file(repo, "orphan.txt", "no shared history\n")
    _git(repo, "add", "orphan.txt")
    _git(repo, "commit", "-q", "-m", "orphan root")
    _git(repo, "checkout", "-q", "main")

    proc = run_prune(repo, no_gh=True)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result["orphan-branch"] == "SKIP_NO_MERGE_BASE"


# --------------------------------------------------------------------------
# 14. --no-gh on the L2-deletable repo -> SKIP, and the run names the
#     degradation (uses the scenario-2 fixture: the one repo shape where L4
#     alone provably cannot rescue the branch, per the test table's own
#     "L4 alone would skip" note on that scenario)
# --------------------------------------------------------------------------


def test_no_gh_skips_on_l2_only_deletable_repo_and_names_degradation(tmp_path):
    repo, pr_path, _, _ = build_squash_then_main_diverges(tmp_path)

    with_gh = run_prune(repo, pr_data=pr_path)
    assert with_gh.returncode == 0, with_gh.stderr
    assert outcomes(with_gh.stdout)["feat"] == "DELETE via L2"

    without_gh = run_prune(repo, no_gh=True)
    assert without_gh.returncode == 0, without_gh.stderr
    result = outcomes(without_gh.stdout)
    assert result["feat"] == "SKIP_UNPROVEN"
    assert "degraded" in without_gh.stdout.lower()


# --------------------------------------------------------------------------
# Amendment B2 / B12: the whitespace-hole discrimination check
# --------------------------------------------------------------------------


def test_patch_id_whitespace_collision_is_empirically_real():
    # Direct, low-level proof of the amendment's own claim: git patch-id
    # strips whitespace, so a diff changing a line to double-space and one
    # changing it to single-space produce the SAME patch-id.
    diff_double_space = (
        "diff --git a/f.txt b/f.txt\n"
        "index 0000000..1111111 100644\n"
        "--- a/f.txt\n"
        "+++ b/f.txt\n"
        "@@ -1 +1 @@\n"
        "-X\n"
        "+X  Y\n"
    )
    diff_single_space = (
        "diff --git a/f.txt b/f.txt\n"
        "index 0000000..2222222 100644\n"
        "--- a/f.txt\n"
        "+++ b/f.txt\n"
        "@@ -1 +1 @@\n"
        "-X\n"
        "+X Y\n"
    )
    pid_a = ds_branch_prune._patch_id(diff_double_space)
    pid_b = ds_branch_prune._patch_id(diff_single_space)
    assert pid_a is not None and pid_b is not None
    assert pid_a == pid_b, "git patch-id was expected to collide on whitespace-only divergence"

    # The discrimination check must NOT collide - it compares actual content
    # (whitespace included), only stripping the @@ line-number portion.
    sig_a = ds_branch_prune._content_signature(diff_double_space)
    sig_b = ds_branch_prune._content_signature(diff_single_space)
    assert sig_a != sig_b


def test_content_signature_matches_shifted_hunk_and_still_rejects_whitespace(tmp_path):
    """m1 fix (Skeptic round 2): the pre-fix `_content_signature` compared
    the WHOLE diff text (including `diff --git`/`index`/`---`/`+++`
    lines), not just hunk content. `index <old>..<new>` encodes the blob
    hashes of the file's pre/post image, which are a function of the
    surrounding file text at each comparison point - NOT of the delta
    itself. Two diffs applying the byte-identical logical change at a
    shifted hunk position (because the surrounding file differs, e.g. 3
    lines prepended) legitimately patch-id-match (git patch-id already
    ignores this) but previously produced DIFFERENT `_content_signature`
    values purely because of the differing index hashes - a false SKIP
    that defeated L2's stated non-decay property. Reproduces the Skeptic's
    exact scenario: a branch changes line 5 of a 5-line file forked off
    main; before that branch's own squash lands, main gains 3 prepended
    lines to the SAME file, so the squash commit's diff shows the
    identical edit at line 8 instead of line 5.
    """
    repo = init_repo(tmp_path)
    write_file(repo, "f.txt", "l1\nl2\nl3\nl4\nl5\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "add f.txt")
    base_sha = _rev_parse(repo, "main")  # the 5-line state feat forks from

    _git(repo, "checkout", "-q", "-b", "feat", base_sha)
    write_file(repo, "f.txt", "l1\nl2\nl3\nl4\nl5-changed\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "change line 5")
    feat_tip = _rev_parse(repo, "feat")

    # main diverges BEFORE the squash lands: 3 lines prepended to the SAME
    # file feat touched, shifting where the identical edit lands.
    _git(repo, "checkout", "-q", "main")
    write_file(repo, "f.txt", "p1\np2\np3\nl1\nl2\nl3\nl4\nl5\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "prepend 3 lines")

    mc = squash_merge(repo, "feat", "squash feat")

    diff_branch = ds_branch_prune._diff(str(repo), base_sha, feat_tip)
    diff_mc = ds_branch_prune._diff(str(repo), f"{mc}^", mc)

    # Pin the patch-id equality this test relies on BEFORE asserting the
    # fix - if this stops holding, the test below would pass vacuously.
    assert ds_branch_prune._patch_id(diff_branch) == ds_branch_prune._patch_id(diff_mc), (
        "fixture setup error: the shifted-hunk diffs no longer patch-id-match"
    )
    assert ds_branch_prune._content_signature(diff_branch) == ds_branch_prune._content_signature(diff_mc), (
        "m1 regression: a byte-identical logical change applied at a "
        "shifted hunk position must not be rejected by the discrimination "
        "check merely because the surrounding file's blob hashes differ"
    )

    # The genuine whitespace-only case (X  Y vs X Y, same file, same
    # position) must still be rejected - the fix must not over-correct.
    diff_double_space = (
        "diff --git a/f.txt b/f.txt\n"
        "index 0000000..1111111 100644\n"
        "--- a/f.txt\n"
        "+++ b/f.txt\n"
        "@@ -1 +1 @@\n"
        "-X\n"
        "+X  Y\n"
    )
    diff_single_space = (
        "diff --git a/f.txt b/f.txt\n"
        "index 0000000..2222222 100644\n"
        "--- a/f.txt\n"
        "+++ b/f.txt\n"
        "@@ -1 +1 @@\n"
        "-X\n"
        "+X Y\n"
    )
    assert ds_branch_prune._content_signature(diff_double_space) != ds_branch_prune._content_signature(
        diff_single_space
    )

    # End-to-end proof: the shifted-hunk branch must actually DELETE via L2
    # now (it previously resolved SKIP_UNPROVEN despite a real patch-id
    # match, because of this exact discrimination-check bug).
    prs = [{"number": 1, "headRefName": "feat", "headRefOid": feat_tip, "mergeCommit": {"oid": mc}}]
    pr_path = pr_data_file(tmp_path, prs)
    proc = run_prune(repo, pr_data=pr_path)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result["feat"] == "DELETE via L2", (
        "m1 regression: shifted-hunk identical squash content must delete via L2, not SKIP_UNPROVEN"
    )


def test_l2_fabricated_merge_commit_not_on_main_is_skipped(tmp_path):
    # Vacuity proof 2 target (Mandatory verification): a candidate whose
    # mergeCommit is NEVER on the base branch at all (here: the branch's
    # OWN unmerged tip, fabricated as if it were a "mergeCommit") but whose
    # diff trivially self-matches (mc^ == base, mc == O) must still be
    # SKIPPED - only the explicit `merge-base --is-ancestor(mc, base_ref)`
    # guard prevents this. Breaking that guard makes this test's DELETE
    # assertion... wait: this asserts SKIP; the mutation (guard removed)
    # flips it to DELETE, reddening this test.
    repo = init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feat")
    write_file(repo, "x.txt", "hello\n")
    _git(repo, "add", "x.txt")
    _git(repo, "commit", "-q", "-m", "add x")
    feat_tip = _rev_parse(repo, "feat")
    _git(repo, "checkout", "-q", "main")

    # feat is NEVER merged into main at all - main stays at its init commit.
    # The fabricated PR record claims feat's own (unmerged) tip IS the
    # mergeCommit for its own PR - a self-referential diff match that is
    # only rejected by the MC-on-main guard.
    prs = [{"number": 7, "headRefName": "feat", "headRefOid": feat_tip, "mergeCommit": {"oid": feat_tip}}]
    pr_path = pr_data_file(tmp_path, prs)

    proc = run_prune(repo, pr_data=pr_path)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result["feat"] == "SKIP_UNPROVEN", (
        "a mergeCommit that is not itself on the base branch must never "
        "authorize an L2 delete, even if its diff self-matches"
    )


def test_whitespace_only_divergent_branch_is_not_deleted(tmp_path):
    # End-to-end proof (B12's DISCRIMINATION form): a candidate whose
    # patch-id COLLIDES with a real merge commit's patch-id, but whose
    # actual content differs only by whitespace, must NOT be deleted.
    #
    # Both branches must fork from the SAME shared base content ("X\n") for
    # the patch-id collision to be the real one the amendment describes
    # (a line changed to "X  Y" vs the same line changed to "X Y") - a
    # branch forked AFTER the squash would diff "X  Y" -> "X Y" (an
    # unrelated content-shape change, whose patch-id would simply differ
    # for an unrelated reason and never exercise the discrimination check
    # at all). merged-branch and whitespace-divergent are therefore BOTH
    # created directly from `init_sha`, never from each other or from
    # post-squash main.
    repo = init_repo(tmp_path)
    write_file(repo, "f.txt", "X\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "add f.txt")
    init_sha = _rev_parse(repo, "main")

    _git(repo, "checkout", "-q", "-b", "merged-branch", init_sha)
    write_file(repo, "f.txt", "X  Y\n")  # double space
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "double-space change")
    _git(repo, "checkout", "-q", "main")
    mc = squash_merge(repo, "merged-branch", "squash merged-branch")

    _git(repo, "checkout", "-q", "-b", "whitespace-divergent", init_sha)
    write_file(repo, "f.txt", "X Y\n")  # single space - DIFFERENT content
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "single-space change")
    tip = _rev_parse(repo, "whitespace-divergent")
    _git(repo, "checkout", "-q", "main")

    # Direct proof the collision this test relies on is real (not an
    # assumption): compute both diffs exactly as the script would and
    # assert git patch-id genuinely equates them, BEFORE asserting the
    # script's own outcome - if this assertion ever stops holding, the
    # test below would pass VACUOUSLY (for the wrong reason), so it is
    # pinned explicitly.
    diff_a = ds_branch_prune._diff(str(repo), init_sha, tip)
    diff_b = ds_branch_prune._diff(str(repo), f"{mc}^", mc)
    assert ds_branch_prune._patch_id(diff_a) == ds_branch_prune._patch_id(diff_b), (
        "fixture setup error: the two diffs no longer patch-id-collide - "
        "this test would otherwise pass for the wrong reason"
    )
    assert ds_branch_prune._content_signature(diff_a) != ds_branch_prune._content_signature(diff_b)

    # Fabricate a PR record claiming whitespace-divergent's PR merge commit
    # was `mc` (the double-space squash) - patch-id-equal, content-unequal.
    # headRefOid deliberately points at the UNRELATED merged-branch tip
    # (never an ancestor of whitespace-divergent's own tip), not
    # whitespace-divergent's own tip - otherwise L3's "O ancestor of H"
    # check would trivially self-match (O == H) and mask the L2
    # discrimination failure this test exists to prove.
    merged_branch_tip = _rev_parse(repo, "merged-branch")
    prs = [{"number": 6, "headRefName": "whitespace-divergent", "headRefOid": merged_branch_tip, "mergeCommit": {"oid": mc}}]
    pr_path = pr_data_file(tmp_path, prs)

    proc = run_prune(repo, pr_data=pr_path)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    assert result["whitespace-divergent"] == "SKIP_UNPROVEN", (
        "a whitespace-only-divergent branch must never be deleted on a "
        "patch-id collision alone"
    )


# --------------------------------------------------------------------------
# Vacuity proof 4: the aggregate deletes neither 0 nor all branches
# --------------------------------------------------------------------------


def test_aggregate_deletes_neither_zero_nor_all(tmp_path):
    repo, pr_path, _, _ = build_clean_squash(tmp_path)

    _git(repo, "checkout", "-q", "-b", "wip-untouched")
    write_file(repo, "wip.txt", "never merged\n")
    _git(repo, "add", "wip.txt")
    _git(repo, "commit", "-q", "-m", "wip")
    _git(repo, "checkout", "-q", "main")

    proc = run_prune(repo, pr_data=pr_path)
    assert proc.returncode == 0, proc.stderr
    result = outcomes(proc.stdout)
    delete_count = sum(1 for v in result.values() if v.startswith("DELETE"))
    skip_count = sum(1 for v in result.values() if not v.startswith("DELETE"))
    assert delete_count > 0
    assert skip_count > 0


# --------------------------------------------------------------------------
# Vacuity proof 5 / exit-code discipline
# --------------------------------------------------------------------------


def test_exit_zero_when_branches_are_skipped(tmp_path):
    repo = init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "wip")
    write_file(repo, "w.txt", "wip\n")
    _git(repo, "add", "w.txt")
    _git(repo, "commit", "-q", "-m", "wip")
    _git(repo, "checkout", "-q", "main")

    proc = run_prune(repo, no_gh=True)
    assert proc.returncode == 0


def test_bad_repo_path_is_usage_error(tmp_path):
    nonexistent = tmp_path / "does-not-exist"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(nonexistent), "--dry-run"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1


def test_missing_pr_data_file_is_usage_error(tmp_path):
    repo = init_repo(tmp_path)
    missing = tmp_path / "no-such-file.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--dry-run", "--pr-data", str(missing)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "not found" in proc.stderr.lower() or "not found" in proc.stdout.lower()


# --------------------------------------------------------------------------
# B3: deletion ledger (real, non-dry-run delete)
# --------------------------------------------------------------------------


def test_real_delete_writes_ledger_and_deletes_branch(tmp_path):
    repo, pr_path, _, mc = build_clean_squash(tmp_path)

    proc = run_prune(repo, pr_data=pr_path, dry_run=False)
    assert proc.returncode == 0, proc.stderr

    # Branch is actually gone.
    branches = subprocess.run(
        ["git", "-C", str(repo), "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        capture_output=True,
        text=True,
    ).stdout
    assert "feat" not in branches.splitlines()

    ledger = repo / ".agentic" / "branch-prune-ledger.txt"
    assert ledger.exists()
    lines = ledger.read_text().splitlines()
    assert any(line.startswith("feat ") for line in lines)

    # Recovery path the ledger enables: git branch <name> <sha> restores it.
    recorded_sha = next(line.split(" ", 1)[1] for line in lines if line.startswith("feat "))
    _git(repo, "branch", "feat", recorded_sha)
    assert _rev_parse(repo, "feat") == recorded_sha


def test_dry_run_never_writes_ledger_or_deletes(tmp_path):
    repo, pr_path, _, _ = build_clean_squash(tmp_path)

    proc = run_prune(repo, pr_data=pr_path, dry_run=True)
    assert proc.returncode == 0, proc.stderr

    branches = subprocess.run(
        ["git", "-C", str(repo), "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        capture_output=True,
        text=True,
    ).stdout
    assert "feat" in branches.splitlines()
    assert not (repo / ".agentic" / "branch-prune-ledger.txt").exists()


# --------------------------------------------------------------------------
# B11: failed `git branch -D` is reported and the run continues, exit 0
# --------------------------------------------------------------------------


def test_failed_branch_delete_is_reported_and_run_continues(tmp_path, monkeypatch, capsys):
    # Amendment B11: git refusing a `-D` (e.g. a race where the branch
    # becomes checked out or is being rebased elsewhere AFTER this run's own
    # G1 evaluation) must be reported to stderr and the run must still
    # continue and exit 0 - never a hard failure. Simulated by monkeypatching
    # the internal `_run` wrapper to fail ONLY the `branch -D` invocation;
    # every other git call goes through to the real subprocess.
    repo, pr_path, _, _ = build_clean_squash(tmp_path)
    real_run = ds_branch_prune._run

    def fake_run(args, cwd=None, input_text=None):
        if "branch" in args and "-D" in args:
            class FakeProc:
                returncode = 1
                stdout = ""
                stderr = "error: branch 'feat' checked out elsewhere\n"

            return FakeProc()
        return real_run(args, cwd=cwd, input_text=input_text)

    monkeypatch.setattr(ds_branch_prune, "_run", fake_run)
    rc = ds_branch_prune.main(["--repo", str(repo), "--base", "main", "--pr-data", pr_path])
    assert rc == 0

    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "feat" in err

    branches = subprocess.run(
        ["git", "-C", str(repo), "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        capture_output=True,
        text=True,
    ).stdout
    assert "feat" in branches.splitlines()

    # M1 fix (Skeptic round 2): the ledger entry is now written BEFORE the
    # `git branch -D` attempt (write-ahead), not only after a confirmed
    # success - so a failed delete still leaves a ledger entry behind. This
    # is deliberate and harmless: the branch still exists (the delete
    # failed), so the entry simply over-records intent rather than ever
    # under-recording a successful, unrecoverable deletion.
    ledger = repo / ".agentic" / "branch-prune-ledger.txt"
    assert ledger.exists()
    assert any(line.startswith("feat ") for line in ledger.read_text().splitlines())


def test_ledger_write_failure_halts_further_deletions_but_exits_zero(tmp_path, monkeypatch, capsys):
    """M1 fix (Skeptic round 2): a ledger-write failure must be a HARD STOP
    on any further deletion this run - not an uncaught crash (the original
    reproduction: `.agentic/` at mode 500 raised an uncaught PermissionError
    traceback and exited 1 AFTER a branch had already been deleted). This
    test drives two DELETE-eligible branches through one run and simulates
    the ledger write failing on the FIRST one: the run must (a) never
    attempt `git branch -D` for either branch, (b) print the halt reason to
    stderr, and (c) still exit 0 per the script's own documented contract
    ("exit 1 ONLY on an internal/usage error" - a ledger-write failure at
    session start must not look like a hard failure).

    n2 fix (Skeptic round 3): the previous version of this fixture raised
    `_append_ledger` on EVERY call, not just the first. That made `break`
    (halt on first failure) and `continue` (skip the failed branch, keep
    going) produce IDENTICAL observable behavior here - a `continue` mutant
    would ALSO delete nothing, because the second branch's ledger write
    would raise too and its `git branch -D` would never be reached either.
    The two branches sort as "feat" < "ff-branch" (`sorted(branches)`), so
    "feat" fails first; the fake now raises ONLY on that first call and
    delegates to the real `_append_ledger` afterward, so a `continue`
    mutant would let "ff-branch"'s ledger write succeed and its
    `git branch -D` actually run - which the assertion below catches by
    requiring "ff-branch" to still exist. ("ff-branch-again" is the
    currently-checked-out branch at test invocation, so it is
    SKIP_CHECKED_OUT and never a delete candidate under either code path -
    asserting its presence is vacuous and does not discriminate; the real
    discriminators are `call_count["n"] == 1` and "ff-branch" surviving.)
    """
    repo, pr_path, _, _ = build_clean_squash(tmp_path)

    # A second, independently DELETE-eligible branch (L1: trivial ancestor
    # fast-forward merge) so the run has more than one delete_results entry
    # to prove the halt actually stops BOTH, not just the one that failed.
    _git(repo, "checkout", "-q", "-b", "ff-branch")
    write_file(repo, "ff.txt", "ff content\n")
    _git(repo, "add", "ff.txt")
    _git(repo, "commit", "-q", "-m", "ff commit")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "ff-branch")
    _git(repo, "checkout", "-q", "-b", "ff-branch-again", "ff-branch")
    # ff-branch itself is now an ancestor of main (fast-forwarded); use a
    # fresh branch name pointing at the same tip so it, too, resolves DELETE
    # via L1 independently of ff-branch's own fate.

    real_append_ledger = ds_branch_prune._append_ledger
    call_count = {"n": 0}

    def fake_append_ledger(repo_arg, line):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise PermissionError("[Errno 13] Permission denied (simulated)")
        # Only reached if the run did NOT halt after the first failure -
        # i.e. under a `continue` mutant. Delegate to the real
        # implementation so the second branch's deletion actually proceeds,
        # making the mutant's divergence observable in git state below.
        return real_append_ledger(repo_arg, line)

    monkeypatch.setattr(ds_branch_prune, "_append_ledger", fake_append_ledger)

    rc = ds_branch_prune.main(["--repo", str(repo), "--base", "main", "--pr-data", pr_path])
    assert rc == 0

    err = capsys.readouterr().err
    assert "ERROR" in err
    assert "halting further deletions" in err

    branches = subprocess.run(
        ["git", "-C", str(repo), "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    # Neither DELETE-eligible branch was actually deleted - the halt fired
    # before the very first `git branch -D` was attempted. Under a
    # `continue` mutant, "ff-branch" (the second, non-failing DELETE
    # candidate) WOULD be deleted here - this is the assertion that
    # actually distinguishes halt-and-stop from skip-and-proceed.
    # ("ff-branch-again" is the checked-out branch and is never a delete
    # candidate under either code path, so asserting its presence alone
    # would be vacuous.)
    assert "feat" in branches
    assert "ff-branch" in branches
    assert "ff-branch-again" in branches
    assert call_count["n"] == 1
    assert not (repo / ".agentic" / "branch-prune-ledger.txt").exists()


# --------------------------------------------------------------------------
# Mode-label reporting: `degraded` and `--dry-run` are independent axes, and
# the summary line's `mode=` field must reflect both without collapsing them.
# --------------------------------------------------------------------------


def test_dry_run_summary_never_reports_mode_live(tmp_path):
    repo, pr_path, _, _ = build_clean_squash(tmp_path)
    proc = run_prune(repo, pr_data=pr_path, dry_run=True)
    assert proc.returncode == 0, proc.stderr
    assert "mode=live" not in proc.stdout
    assert "mode=dry-run branches=" in proc.stdout


def test_normal_run_summary_reports_mode_live(tmp_path):
    repo, pr_path, _, _ = build_clean_squash(tmp_path)
    proc = run_prune(repo, pr_data=pr_path, dry_run=False)
    assert proc.returncode == 0, proc.stderr
    assert "mode=live branches=" in proc.stdout


def test_degraded_dry_run_summary_surfaces_both_facts(tmp_path):
    repo, pr_path, _, _ = build_squash_then_main_diverges(tmp_path)
    proc = run_prune(repo, no_gh=True, dry_run=True)
    assert proc.returncode == 0, proc.stderr
    assert "degraded" in proc.stdout.lower()
    assert "dry-run" in proc.stdout.lower()
    assert "mode=live" not in proc.stdout
    assert "mode=degraded (gh unavailable), dry-run branches=" in proc.stdout


# --------------------------------------------------------------------------
# Merged-PR window: cursor pagination + totalCount reconciliation.
#
# These cover the fetch that replaced `gh pr list --limit 500`, whose row
# cap sat BELOW this repository's own merged-PR count (500 rows returned
# against 770 merged PRs, measured) and therefore raised the truncation
# flag on every single run. The `gh` boundary is stubbed exactly the way
# this file already stubs it for Amendment B11 - monkeypatching the
# module's own `_run` wrapper and delegating every non-gh argv to the real
# subprocess - so nothing here makes a network call or reads `gh` auth
# state. `shutil.which` is pinned too, so a runner with no `gh` installed
# still exercises the pagination path rather than silently falling through
# to the degraded one.
# --------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _graphql_page(nodes, total_count, has_next, end_cursor="cursor"):
    """One `gh api graphql` response body for the merged-PR connection."""
    return {
        "data": {
            "repository": {
                "pullRequests": {
                    "totalCount": total_count,
                    "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
                    "nodes": nodes,
                }
            }
        }
    }


def _pr_nodes(start, count, prefix="branch"):
    """`count` merged-PR nodes in the exact shape the GraphQL query selects."""
    return [
        {
            "number": n,
            "headRefName": f"{prefix}-{n}",
            "headRefOid": f"{n:040x}",
            "mergeCommit": {"oid": f"{n + 500000:040x}"},
        }
        for n in range(start, start + count)
    ]


def _install_fake_gh(monkeypatch, pages, slug="Space-Dinosaurs/DinoStack", repo_view_rc=0):
    """Serve `pages` to successive `gh api graphql` calls; pass git through.

    Each entry of `pages` is either a dict (encoded as the JSON body of a
    successful call), a `_FakeProc` (returned verbatim, for error and
    malformed-output cases), or an Exception instance (raised, for the "gh
    could not be invoked at all" path).

    Returns the mutable call log so a test can assert HOW MANY requests
    were made - the discriminator between a genuinely paginated fetch and a
    single capped one - which cursor each carried, and the `timeout=` each
    was issued with (an unbounded `gh` call at session start is the failure
    this bound exists to prevent, so it is recorded, not assumed).
    """
    real_run = ds_branch_prune._run
    log = {"graphql": 0, "repo_view": 0, "cursors": [], "timeouts": [], "flags": []}

    def fake_run(args, cwd=None, input_text=None, timeout=None):
        if args[:3] == ["gh", "repo", "view"]:
            log["repo_view"] += 1
            log["timeouts"].append(timeout)
            if repo_view_rc != 0:
                return _FakeProc(repo_view_rc, "")
            return _FakeProc(0, json.dumps({"nameWithOwner": slug}))
        if args[:3] == ["gh", "api", "graphql"]:
            idx = log["graphql"]
            log["graphql"] += 1
            log["timeouts"].append(timeout)
            log["flags"].append(list(args))
            cursor = None
            for token in args:
                if token.startswith("endCursor="):
                    cursor = token.split("=", 1)[1]
            log["cursors"].append(cursor)
            assert idx < len(pages), f"unexpected extra gh api graphql call #{idx + 1}"
            page = pages[idx]
            if isinstance(page, Exception):
                raise page
            if isinstance(page, _FakeProc):
                return page
            return _FakeProc(0, json.dumps(page))
        return real_run(args, cwd=cwd, input_text=input_text, timeout=timeout)

    monkeypatch.setattr(ds_branch_prune.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(ds_branch_prune, "_run", fake_run)
    return log


def test_pagination_retrieves_more_than_the_old_five_hundred_row_cap(tmp_path, monkeypatch):
    """The superseded fetch could never return more than 500 rows. Eight
    pages of 100 reconciling to totalCount=800 must come back COMPLETE.

    Reddening mutation (executed): set `PR_MAX_PAGES = 5` in
    bin/ds-branch-prune. Only 500 nodes are then collected, `saw_last_page`
    stays False, and the call returns the page-cap incomplete reason -
    which is the old 500-row ceiling reappearing under a new name.
    """
    repo = init_repo(tmp_path)
    pages = [
        _graphql_page(
            _pr_nodes(1 + page_index * 100, 100),
            total_count=800,
            has_next=page_index < 7,
            end_cursor=f"cursor-{page_index}",
        )
        for page_index in range(8)
    ]

    log = _install_fake_gh(monkeypatch, pages)
    data, degraded, incomplete_reason = ds_branch_prune._load_merged_prs(str(repo), None, False)

    assert len(data) == 800, len(data)
    assert len(data) > 500, "must exceed the superseded gh pr list --limit ceiling"
    assert degraded is False
    assert incomplete_reason is None, incomplete_reason
    assert log["graphql"] == 8, log
    # The first request must omit $endCursor entirely (`after: ""` is not a
    # valid cursor); every later one carries the PRIOR page's endCursor.
    assert log["cursors"][0] is None, log["cursors"]
    assert log["cursors"][1:] == [f"cursor-{i}" for i in range(7)], log["cursors"]


def test_count_mismatch_is_treated_as_incomplete_not_complete(tmp_path, monkeypatch):
    """THE completeness proof. Retrieving fewer nodes than the connection's
    own totalCount must degrade evidence exactly as truncation used to -
    never be reported as a complete window.

    Reddening mutation (executed): delete the
    `if len(nodes) != total_count:` reconciliation block in
    `_load_merged_prs`. The call then returns `incomplete_reason is None`
    for a demonstrably short window.
    """
    repo = init_repo(tmp_path)
    pages = [
        _graphql_page(_pr_nodes(1, 100), total_count=250, has_next=True, end_cursor="c0"),
        _graphql_page(_pr_nodes(101, 100), total_count=250, has_next=False),
    ]

    _install_fake_gh(monkeypatch, pages)
    data, degraded, incomplete_reason = ds_branch_prune._load_merged_prs(str(repo), None, False)

    assert len(data) == 200
    # Partial data is retained and is NOT degraded (some evidence exists),
    # but the window is explicitly not proven complete.
    assert degraded is False
    assert incomplete_reason is not None
    assert "200" in incomplete_reason and "250" in incomplete_reason, incomplete_reason


def test_absent_total_count_is_treated_as_incomplete(tmp_path, monkeypatch):
    """No totalCount means nothing to reconcile against, so completeness is
    unproven - it must NOT default to complete.

    Reddening mutation (executed): change the
    `if not isinstance(total_count, int) ...` guard to `if False:`. The
    call then returns `incomplete_reason is None` despite having no proof.
    """
    repo = init_repo(tmp_path)
    page = _graphql_page(_pr_nodes(1, 10), total_count=0, has_next=False)
    del page["data"]["repository"]["pullRequests"]["totalCount"]

    _install_fake_gh(monkeypatch, [page])
    data, degraded, incomplete_reason = ds_branch_prune._load_merged_prs(str(repo), None, False)

    assert len(data) == 10
    assert incomplete_reason is not None
    assert "totalCount" in incomplete_reason, incomplete_reason


def test_graphql_errors_array_is_incomplete_even_with_data_present(tmp_path, monkeypatch):
    """A GraphQL partial-data error response (HTTP 200, `data` alongside
    `errors`) must be classified incomplete, not consumed as a short page.

    Reddening mutation (executed): delete the
    `if payload.get("errors"): return None` line from
    `_pull_requests_connection`. The response's 3 nodes are then accepted
    and reconciled against its own totalCount of 3, returning
    `incomplete_reason is None` for an errored response.
    """
    repo = init_repo(tmp_path)
    page = _graphql_page(_pr_nodes(1, 3), total_count=3, has_next=False)
    page["errors"] = [{"message": "Something went wrong"}]

    _install_fake_gh(monkeypatch, [page])
    data, degraded, incomplete_reason = ds_branch_prune._load_merged_prs(str(repo), None, False)

    assert data == []
    assert degraded is True
    assert incomplete_reason is not None


def test_midpagination_failure_keeps_partial_data_and_reports_incomplete(tmp_path, monkeypatch):
    """A page that fails AFTER a good one must retain what was fetched and
    report the window incomplete - fewer deletions, never a false one.

    Reddening mutation (executed): make `_incomplete_window` return
    `(nodes, False, None)`. The short window is then reported complete.
    """
    repo = init_repo(tmp_path)
    pages = [
        _graphql_page(_pr_nodes(1, 100), total_count=200, has_next=True, end_cursor="c0"),
        _FakeProc(1, "", "gh: API rate limit exceeded"),
    ]

    _install_fake_gh(monkeypatch, pages)
    data, degraded, incomplete_reason = ds_branch_prune._load_merged_prs(str(repo), None, False)

    assert len(data) == 100
    assert degraded is False
    assert incomplete_reason is not None
    assert "nonzero" in incomplete_reason, incomplete_reason


def test_first_page_failure_degrades_exactly_like_an_absent_gh(tmp_path, monkeypatch):
    """The pre-change contract for an erroring `gh` was `([], True, ...)`.
    A first-page failure must produce the same state, so a checkout with no
    `gh` auth behaves exactly as it always did.

    Reddening mutation (executed): make `_incomplete_window` return
    `(nodes, False, reason)` unconditionally. `degraded` then comes back
    False on a total fetch failure and main() stops printing the
    degraded-mode NOTE.
    """
    repo = init_repo(tmp_path)

    _install_fake_gh(monkeypatch, [_FakeProc(1, "", "gh: not authenticated")])
    data, degraded, incomplete_reason = ds_branch_prune._load_merged_prs(str(repo), None, False)

    assert data == []
    assert degraded is True
    assert incomplete_reason is not None


def test_unresolvable_repo_slug_degrades_and_never_queries(tmp_path, monkeypatch):
    """`gh api graphql` cannot infer the repository the way `gh pr list`
    did, so slug resolution is a NEW failure surface this change
    introduced. It must degrade quietly, never raise and never query.

    Reddening mutation (executed): replace `_load_merged_prs`'s
    `slug = _gh_repo_slug(repo); if slug is None: return [], True, None`
    with a fallback (`owner, name = slug or ("o", "n")`). The query then
    runs against a fabricated repository slug instead of degrading, and
    both `degraded is True` and `log["graphql"] == 0` fail.
    """
    repo = init_repo(tmp_path)

    log = _install_fake_gh(monkeypatch, [], repo_view_rc=1)
    data, degraded, incomplete_reason = ds_branch_prune._load_merged_prs(str(repo), None, False)

    assert data == []
    assert degraded is True
    assert incomplete_reason is None
    assert log["graphql"] == 0, "must not query without a resolved repository slug"


def test_no_gh_path_makes_no_gh_calls_at_all(tmp_path, monkeypatch):
    """--no-gh must remain a pure short-circuit: the degraded contract is
    unchanged by pagination, and not even the new slug lookup may run.

    Reddening mutation (executed): delete the
    `if no_gh or shutil.which("gh") is None:` early return.
    `log["repo_view"]` becomes 1 and `degraded` flips to False.
    """
    repo = init_repo(tmp_path)

    log = _install_fake_gh(monkeypatch, [])
    data, degraded, incomplete_reason = ds_branch_prune._load_merged_prs(str(repo), None, True)

    assert data == []
    assert degraded is True
    assert incomplete_reason is None
    assert log["repo_view"] == 0, log
    assert log["graphql"] == 0, log


def test_pr_data_contract_is_unchanged_and_makes_no_gh_calls(tmp_path, monkeypatch):
    """--pr-data stays an exact injection seam: data returned verbatim,
    never degraded, never reported incomplete (there is no connection
    totalCount to reconcile injected data against), and no `gh` invoked.

    Reddening mutation (executed): change the --pr-data branch's
    `return data, False, None` to `return data, False, "unreconciled"`. A
    --pr-data run then prints the incomplete NOTE, which is exactly the
    false alarm a manual full-set injection must not trigger.
    """
    repo = init_repo(tmp_path)
    prs = [
        {
            "number": 7,
            "headRefName": "feat",
            "headRefOid": "a" * 40,
            "mergeCommit": {"oid": "b" * 40},
        }
    ]
    pr_path = pr_data_file(tmp_path, prs)

    log = _install_fake_gh(monkeypatch, [])
    data, degraded, incomplete_reason = ds_branch_prune._load_merged_prs(str(repo), pr_path, False)

    assert data == prs
    assert degraded is False
    assert incomplete_reason is None
    assert log["repo_view"] == 0 and log["graphql"] == 0, log


def test_incomplete_window_note_fires_and_is_silent_when_complete(tmp_path, monkeypatch, capsys):
    """Amendment B13's operator-facing contract, end to end through main():
    the NOTE fires when completeness is unproven and is SILENT when proven.
    Before this change the equivalent NOTE fired on every run against this
    repository, so the silent case is the half worth pinning.

    Reddening mutation (executed): change main()'s `if incomplete_reason:`
    to `if False:`. The short-window run then prints no NOTE and the
    operator is never told the evidence was short.
    """
    repo, _, _, _ = build_clean_squash(tmp_path)

    short = [_graphql_page(_pr_nodes(1, 5), total_count=9, has_next=False)]
    _install_fake_gh(monkeypatch, short)
    assert ds_branch_prune.main(["--repo", str(repo), "--base", "main", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "could not be proven complete" in out, out
    assert "never treated as proof" in out, out
    monkeypatch.undo()

    exact = [_graphql_page(_pr_nodes(1, 5), total_count=5, has_next=False)]
    _install_fake_gh(monkeypatch, exact)
    assert ds_branch_prune.main(["--repo", str(repo), "--base", "main", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "could not be proven complete" not in out, out


def test_short_window_can_only_lose_deletions_never_gain_one(tmp_path, monkeypatch, capsys):
    """The fail-safe direction that matters. The SAME repository is driven
    twice: once with the branch's real merged-PR row present (complete
    window) and once with it absent (short window). Losing the row may only
    turn a DELETE into a SKIP - it can never create a deletion.

    The fixture is deliberately `build_squash_then_main_diverges`, NOT
    `build_clean_squash`: on the latter the branch is independently
    deletable via L4, which is local-git-only evidence that no merged-PR
    window can affect, so dropping the PR row leaves the verdict at
    `DELETE via L4` and the test discriminates nothing. (Confirmed by
    running it that way first - it reported `DELETE via L4`.) On this
    fixture a later commit to the same file decays L4, leaving L2 - the
    PR-derived layer - as the only route to a delete.

    Reddening mutation (executed): make `evaluate_branch` return
    `"DELETE via L2"` when its candidate list is empty. The short-window
    run then reports DELETE and this test fails - which is precisely the
    false delete the fail-safe contract forbids.
    """
    repo, pr_path, _, _ = build_squash_then_main_diverges(tmp_path)
    real_prs = json.loads(Path(pr_path).read_text())

    _install_fake_gh(monkeypatch, [_graphql_page(real_prs, len(real_prs), False)])
    assert (
        ds_branch_prune.main(
            ["--repo", str(repo), "--base", "main", "--dry-run", "--explain"]
        )
        == 0
    )
    complete_out = capsys.readouterr().out
    monkeypatch.undo()

    _install_fake_gh(monkeypatch, [_graphql_page([], len(real_prs), False)])
    assert (
        ds_branch_prune.main(
            ["--repo", str(repo), "--base", "main", "--dry-run", "--explain"]
        )
        == 0
    )
    short_out = capsys.readouterr().out

    assert outcomes(complete_out)["feat"] == "DELETE via L2", complete_out
    assert outcomes(short_out)["feat"] == "SKIP_UNPROVEN", short_out
    assert "could not be proven complete" in short_out, short_out


def _capture_pr_state(monkeypatch):
    """Record every `DispositionFacts.pr_state` `evaluate_branch` constructs.

    `evaluate_branch` returns an outcome, not the facts it built, and the
    difference between `"NONE"` and `"not_checked"` is currently INERT in
    the shared model (`_check_pr_state_strict` collapses both to the same
    inconclusive result and `MERGE_EVIDENCE_ORDER` omits the one field
    whose gate would separate them). That inertness is exactly why the
    field has to be asserted directly: an outcome-level assertion would
    pass no matter which value is passed, so it would pin nothing.
    """
    seen = []
    real = ds_branch_prune.disposition_for_orphan_branch

    def spy(branch, facts, base_branches=()):
        seen.append(facts.pr_state)
        return real(branch, facts, base_branches=base_branches)

    monkeypatch.setattr(ds_branch_prune, "disposition_for_orphan_branch", spy)
    return seen


def test_incomplete_window_yields_not_checked_never_an_affirmative_none(tmp_path, monkeypatch):
    """A branch with no candidate PR may only be recorded as `pr_state`
    `"NONE"` - an AFFIRMATIVE "no merged PR exists for this branch" - when
    the merged-PR window was both obtained AND proven complete. On an
    incomplete window the tool has just finished proving it cannot
    enumerate that window, so the only honest value is `"not_checked"`,
    which is the string `DispositionFacts`' own docstring
    (bin/tests/worktree_model.py) requires from a caller that cannot
    determine a fact.

    Both directions are pinned in one test so a fix cannot satisfy it by
    blanket-passing `"not_checked"` and losing the affirmative case.

    Reddening mutation (executed): restore the pre-fix assignment
    `pr_state = "not_checked" if degraded else "NONE"` in
    `evaluate_branch`, i.e. drop the `or incomplete_reason` term.
    """
    repo, _, _, _ = build_clean_squash(tmp_path)

    # Proven-complete window: the affirmative value is still used.
    seen = _capture_pr_state(monkeypatch)
    exact = [_graphql_page(_pr_nodes(1, 5), total_count=5, has_next=False)]
    log = _install_fake_gh(monkeypatch, exact)
    assert ds_branch_prune.main(["--repo", str(repo), "--base", "main", "--dry-run"]) == 0
    complete_states = list(seen)
    assert log["graphql"] == 1, log
    assert "NONE" in complete_states, complete_states
    monkeypatch.undo()

    # Provably INCOMPLETE window (5 nodes retrieved, 9 reported): no
    # affirmative claim may survive anywhere in the run.
    seen = _capture_pr_state(monkeypatch)
    short = [_graphql_page(_pr_nodes(1, 5), total_count=9, has_next=False)]
    _install_fake_gh(monkeypatch, short)
    assert ds_branch_prune.main(["--repo", str(repo), "--base", "main", "--dry-run"]) == 0
    incomplete_states = list(seen)

    assert incomplete_states, "no branch reached disposition_for_orphan_branch"
    assert "NONE" not in incomplete_states, incomplete_states
    assert set(incomplete_states) <= {"MERGED", "not_checked"}, incomplete_states


def test_page_bound_exhaustion_names_the_page_bound_as_its_reason(tmp_path, monkeypatch):
    """`PR_MAX_PAGES` is a safety bound, not a result cap: exhausting it
    with `hasNextPage` still true must report an INCOMPLETE window naming
    that bound, never a complete one. Covered only indirectly before this
    test - the reason string itself was never asserted, so the branch could
    have fallen through to the totalCount reconciliation and produced a
    different (or, on a coincidentally-matching count, NO) reason.

    Reddening mutation (executed): change `if not saw_last_page:` in
    `_load_merged_prs` to `if False:`.
    """
    repo = init_repo(tmp_path)
    monkeypatch.setattr(ds_branch_prune, "PR_MAX_PAGES", 2)

    # Every page reports another after it, so the loop can only ever end by
    # exhausting the bound. totalCount is set to the nodes actually
    # retrieved, so a fall-through to the count check would find them EQUAL
    # and wrongly report the window complete - that is what this pins.
    pages = [
        _graphql_page(_pr_nodes(1, 100), total_count=200, has_next=True, end_cursor="c1"),
        _graphql_page(_pr_nodes(101, 100), total_count=200, has_next=True, end_cursor="c2"),
    ]
    log = _install_fake_gh(monkeypatch, pages)
    data, degraded, incomplete_reason = ds_branch_prune._load_merged_prs(str(repo), None, False)

    assert log["graphql"] == 2, log
    assert len(data) == 200
    assert degraded is False
    assert incomplete_reason is not None
    assert "2-page safety bound" in incomplete_reason, incomplete_reason
    assert "pending" in incomplete_reason, incomplete_reason


def test_null_repository_is_an_unexpected_shape_not_an_empty_window(tmp_path, monkeypatch):
    """GitHub answers a repository the token cannot see (renamed, deleted,
    or not authorized) with HTTP 200, `data.repository: null`, and often no
    nonzero exit. Read naively that is indistinguishable from "this
    repository has no merged PRs", which would be an affirmative claim
    licensing deletions off an empty window. It must be INCOMPLETE.

    Reddening mutation (executed): make `_pull_requests_connection` return
    `{"totalCount": 0, "pageInfo": {"hasNextPage": False}, "nodes": []}`
    instead of `None` when `data.repository` is not a dict.
    """
    repo = init_repo(tmp_path)

    _install_fake_gh(monkeypatch, [{"data": {"repository": None}}])
    data, degraded, incomplete_reason = ds_branch_prune._load_merged_prs(str(repo), None, False)

    assert data == []
    # No nodes were obtained at all, so this is the same state an absent
    # `gh` produces - degraded, and the operator is told why.
    assert degraded is True
    assert incomplete_reason is not None
    assert "unexpected shape" in incomplete_reason, incomplete_reason

    # And the helper itself, directly, on every null hop.
    assert ds_branch_prune._pull_requests_connection({"data": {"repository": None}}) is None
    assert ds_branch_prune._pull_requests_connection({"data": None}) is None
    assert ds_branch_prune._pull_requests_connection({}) is None


def test_every_gh_call_carries_a_bounded_timeout(tmp_path, monkeypatch):
    """This tool runs synchronously at session start and pagination raised
    the worst-case network invocation count from 1 to PR_MAX_PAGES + 1, so
    an unbounded `gh` call is an unbounded session-start stall. Every `gh`
    invocation must carry a positive, finite timeout - `None` is the
    regression this pins.

    Reddening mutation (executed): drop `timeout=GH_CALL_TIMEOUT_SECONDS`
    from the `_run(cmd, cwd=repo, ...)` call in `_load_merged_prs`.
    """
    repo = init_repo(tmp_path)
    pages = [
        _graphql_page(_pr_nodes(1, 100), total_count=150, has_next=True, end_cursor="c1"),
        _graphql_page(_pr_nodes(101, 50), total_count=150, has_next=False),
    ]
    log = _install_fake_gh(monkeypatch, pages)
    _, degraded, incomplete_reason = ds_branch_prune._load_merged_prs(str(repo), None, False)

    assert degraded is False and incomplete_reason is None
    assert log["repo_view"] == 1 and log["graphql"] == 2, log
    assert len(log["timeouts"]) == 3, log["timeouts"]
    assert all(isinstance(t, (int, float)) and t > 0 for t in log["timeouts"]), log["timeouts"]


def test_gh_call_timeout_is_incomplete_never_a_complete_window(tmp_path, monkeypatch):
    """A HUNG `gh` call must be classified exactly like an erroring one -
    partial rows retained, window reported incomplete. The dangerous
    reading is the opposite one: treating the pages fetched before the hang
    as the whole window and certifying it complete.

    Reddening mutation (executed): delete the
    `except subprocess.TimeoutExpired:` arm so the generic
    `except Exception` handles it - the run stays incomplete but names the
    wrong failure mode. Second mutation (executed) for the dangerous
    direction: return `(nodes, False, None)` from that arm.
    """
    repo = init_repo(tmp_path)
    pages = [
        _graphql_page(_pr_nodes(1, 100), total_count=500, has_next=True, end_cursor="c1"),
        subprocess.TimeoutExpired(cmd=["gh", "api", "graphql"], timeout=30.0),
    ]
    _install_fake_gh(monkeypatch, pages)
    data, degraded, incomplete_reason = ds_branch_prune._load_merged_prs(str(repo), None, False)

    assert len(data) == 100
    assert degraded is False
    assert incomplete_reason is not None
    assert "timeout" in incomplete_reason, incomplete_reason


def test_whole_fetch_deadline_bounds_the_loop_and_reports_incomplete(tmp_path, monkeypatch):
    """A per-call timeout alone still admits PR_MAX_PAGES multiples of
    itself, so the pagination loop carries its own wall-clock deadline.
    Crossing it must stop the loop and report INCOMPLETE, retaining what
    was already fetched.

    The clock is faked rather than slept: `time.monotonic` returns 0 while
    the deadline is computed and for the first page's check, then jumps
    past the deadline before the second.

    Reddening mutation (executed): delete the
    `if time.monotonic() >= deadline:` guard at the top of the pagination
    loop.
    """
    repo = init_repo(tmp_path)
    ticks = iter([0.0, 0.0, 10_000.0] + [10_000.0] * 50)
    monkeypatch.setattr(ds_branch_prune.time, "monotonic", lambda: next(ticks))

    pages = [
        _graphql_page(_pr_nodes(1, 100), total_count=150, has_next=True, end_cursor="c1"),
        _graphql_page(_pr_nodes(101, 50), total_count=150, has_next=False),
    ]
    log = _install_fake_gh(monkeypatch, pages)
    data, degraded, incomplete_reason = ds_branch_prune._load_merged_prs(str(repo), None, False)

    assert log["graphql"] == 1, log
    assert len(data) == 100
    assert degraded is False
    assert incomplete_reason is not None
    assert "deadline" in incomplete_reason, incomplete_reason


def test_string_graphql_variables_use_the_raw_field_flag(tmp_path, monkeypatch):
    """`gh api graphql -F` INFERS a type from the literal, so a numeric
    owner or repository name (`2048`, a legal GitHub name) would be sent as
    an Int and rejected by the `$owner:String!` / `$name:String!`
    declarations. `-f` sends a raw string. `pageSize` is genuinely `Int!`
    and genuinely needs `-F`, so this pins BOTH directions - a fix that
    flips every flag to `-f` breaks the query the other way.

    Reddening mutation (executed): change the `owner=`/`name=` flags back
    to `-F`.
    """
    repo = init_repo(tmp_path)
    pages = [
        _graphql_page(_pr_nodes(1, 100), total_count=150, has_next=True, end_cursor="c1"),
        _graphql_page(_pr_nodes(101, 50), total_count=150, has_next=False),
    ]
    log = _install_fake_gh(monkeypatch, pages)
    _, _, incomplete_reason = ds_branch_prune._load_merged_prs(str(repo), None, False)
    assert incomplete_reason is None

    def flag_for(argv, prefix):
        for i, token in enumerate(argv):
            if token.startswith(prefix):
                return argv[i - 1]
        raise AssertionError(f"{prefix} not present in {argv}")

    first, second = log["flags"]
    assert flag_for(first, "owner=") == "-f", first
    assert flag_for(first, "name=") == "-f", first
    assert flag_for(first, "pageSize=") == "-F", first
    # The cursor is `String` too, and only the second page carries one.
    assert flag_for(second, "endCursor=") == "-f", second


def test_superseded_row_cap_constant_is_gone_from_the_script():
    """The 500-row cap must be REMOVED, not merely raised - a stale unused
    ceiling is exactly the misleading artifact this change eliminates.

    Count-claim provenance: this assertion is re-derived from
    bin/ds-branch-prune's bytes at run time, and it lives in a DIFFERENT
    file from the one it greps, so this test's own source text cannot
    satisfy or contaminate it.

    Reddening mutation (executed): re-add `PR_LIST_LIMIT = 500` to
    bin/ds-branch-prune. The assignment assertion fails.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    assert "PR_PAGE_SIZE = 100" in source
    assert "PR_MAX_PAGES = " in source

    # Re-derived against the script's CURRENT bytes, comment lines excluded.
    # The naive `"PR_LIST_LIMIT = " not in source` form was tried first and
    # failed: the script's own comment explaining the removal quotes the
    # dead constant verbatim, so the check matched the prose documenting
    # the fix rather than any surviving code. What must be absent is an
    # executable reference, not the word.
    code_mentions = [
        line
        for line in source.splitlines()
        if "PR_LIST_LIMIT" in line and not line.lstrip().startswith("#")
    ]
    assert code_mentions == [], code_mentions
    assert not any(
        line.startswith("PR_LIST_LIMIT") for line in source.splitlines()
    ), "the superseded row cap was reintroduced as a module-level assignment"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
