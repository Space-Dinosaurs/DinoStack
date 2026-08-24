#!/usr/bin/env python3
"""
Purpose: pytest suite for bin/tests/worktree_model.py (DS-118). Property/
         regression tests for parse_porcelain's real-fixture and bare-repo
         handling, classify_entry's path-and-host-only classification
         (including the defect-1 collision fixtures and the cross-repo /
         evals/.worktrees non-collision cases), disposition_for's fail-
         closed gate, disposition_for_orphan_branch's WorktreeClass-free
         reduction, and the MERGE_EVIDENCE_ORDER mutation switch.

         DS-196 additions: `_check_origin_reachable`'s pr_state-precondition
         gate, the structural proof that the STRICT/branch-deletion path is
         unreachable by origin-reachability evidence (both a dict-membership
         AND an order-tuple-membership not-in assertion, plus a monkeypatch
         mutation adding it to BOTH simultaneously that must then flip
         disposition_for_orphan_branch to an incorrect ELIGIBLE, proving the
         structural assertions are load-bearing), and the order-tuple/
         checks-dict key-set consistency assertion (plan step 17).

Public API: none (test module; invoked via `python3 -m pytest`).

Upstream deps: worktree_model.py (module under test).

Downstream consumers: CI (`python3 -m pytest bin/tests/test_worktree_model.py -q`);
                      qa_criteria scenarios 1-7 (this ticket's QA gate).

Failure modes: none of these tests perform real filesystem or git I/O
               beyond the module-under-test's own pure functions - all
               fixture data is inline string/dataclass literals.

Performance: sub-second; no I/O.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import worktree_model  # noqa: E402
from worktree_model import (  # noqa: E402
    DEFAULT_BASE_BRANCHES,
    MERGE_EVIDENCE_ORDER,
    WORKTREE_REMOVAL_EVIDENCE_ORDER,
    Disposition,
    DispositionFacts,
    WorktreeClass,
    WorktreeEntry,
    _assert_evidence_order_key_consistency,
    _check_origin_reachable,
    classify_entry,
    disposition_for,
    disposition_for_orphan_branch,
    parse_porcelain,
    relative_path,
)

REPO_ROOT = "/Users/tyson/Documents/Development/ai-tools/DinoStack"

# --------------------------------------------------------------------------
# Real captured fixture - `git worktree list --porcelain`, this repo,
# 2026-08-02, from a live `.claude/worktrees/agent-*` isolation worktree.
# Per the plan's Known limitations: this fixture WILL drift from the live
# machine's state over time - that is expected and does not need updating
# for this fixture's own tests to remain meaningful, since it is a frozen
# regression snapshot, not a live assertion about current `main`.
# --------------------------------------------------------------------------
FIXTURE_PORCELAIN_REAL = """\
worktree /Users/tyson/Documents/Development/ai-tools/DinoStack
HEAD 3498b05cd2c26613d13df67ab7ca70c6feb2f1ab
branch refs/heads/fix/frontmatter-yaml-validity

worktree /Users/tyson/Documents/Development/ai-tools/DinoStack/.agentic/worktrees/context-safe-io-core-v2
HEAD 9cfe17748022d0865cd6be16b95297f43011934c
branch refs/heads/feature/context-safe-io-core-v2

worktree /Users/tyson/Documents/Development/ai-tools/DinoStack/.claude/worktrees/agent-a1a5afef2f39362a6
HEAD 51a598c81e8f4c19920cb6aa571fea70ff5d2eb4
branch refs/heads/feature/ds108-tasks-jsonl-cross-session

worktree /Users/tyson/Documents/Development/ai-tools/DinoStack/.claude/worktrees/agent-a162cb0ddd4a04c6c
HEAD 5ca5ac4541b7a454f16ed34c00d17c45b35be06b
detached

worktree /Users/tyson/Documents/Development/ai-tools/DinoStack/.claude/worktrees/agent-a8441028669f85a9b
HEAD 90e1af7e725fc48f54a7a271f794c0b618265f82
branch refs/heads/fix/ds-118-worktree-model
locked claude agent agent-a8441028669f85a9b (pid 88867 start Thu Jul 30 23:10:13 2026)

worktree /Users/tyson/Documents/Development/ai-tools/DinoStack/evals/.worktrees/wt-6343844a930f
HEAD fb2f39a15cb78283eed7fd4a21c363340675755f
detached
"""

FIXTURE_PORCELAIN_BARE = "worktree /tmp/scratch/bare.git\nbare\n"


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------


class TestParserRealFixture:
    def test_parser_real_fixture_order_and_count(self):
        entries = parse_porcelain(FIXTURE_PORCELAIN_REAL)
        assert len(entries) == 6
        # Order preservation: git always emits the main worktree first, and
        # `parse_porcelain` must preserve input order exactly - `is_main`
        # derivation elsewhere depends on entries[0] being the main entry.
        assert entries[0].path == REPO_ROOT
        assert entries[1].path.endswith("context-safe-io-core-v2")
        assert entries[-1].path.endswith("wt-6343844a930f")

    def test_parser_real_fixture_branch_and_detached_fields(self):
        entries = parse_porcelain(FIXTURE_PORCELAIN_REAL)
        by_path = {e.path: e for e in entries}
        main = by_path[REPO_ROOT]
        assert main.branch == "fix/frontmatter-yaml-validity"
        assert main.is_detached is False
        assert main.is_bare is False

        detached_entry = by_path[
            f"{REPO_ROOT}/.claude/worktrees/agent-a162cb0ddd4a04c6c"
        ]
        assert detached_entry.branch is None
        assert detached_entry.is_detached is True

    def test_parser_real_fixture_locked_reason_captured_with_spaces(self):
        entries = parse_porcelain(FIXTURE_PORCELAIN_REAL)
        locked_entry = next(e for e in entries if e.locked)
        assert locked_entry.locked_reason == "claude agent agent-a8441028669f85a9b (pid 88867 start Thu Jul 30 23:10:13 2026)"


class TestParserBareRepo:
    def test_parser_bare_repo_shape(self):
        entries = parse_porcelain(FIXTURE_PORCELAIN_BARE)
        assert len(entries) == 1
        e = entries[0]
        assert e.is_bare is True
        assert e.head is None
        assert e.branch is None
        assert e.is_detached is False
        assert e.path == "/tmp/scratch/bare.git"

    def test_parser_bare_repo_does_not_raise(self):
        # No HEAD, no branch, no detached line at all - none of that is
        # validated for a bare block; this must not raise.
        parse_porcelain(FIXTURE_PORCELAIN_BARE)

    def test_parser_non_bare_missing_head_still_raises(self):
        # Companion to the bare exemption: proves the exemption is scoped
        # to bare entries only, not a general loosening of validation. A
        # non-bare block (no `bare` key) missing HEAD is still malformed.
        malformed = "worktree /tmp/x\nbranch refs/heads/main\n"
        with pytest.raises(ValueError):
            parse_porcelain(malformed)

    def test_parser_missing_worktree_key_always_raises(self):
        malformed = "HEAD deadbeef\nbranch refs/heads/main\n"
        with pytest.raises(ValueError):
            parse_porcelain(malformed)

    def test_parser_both_branch_and_detached_raises(self):
        malformed = "worktree /tmp/x\nHEAD deadbeef\nbranch refs/heads/main\ndetached\n"
        with pytest.raises(ValueError):
            parse_porcelain(malformed)

    def test_parser_neither_branch_nor_detached_raises(self):
        malformed = "worktree /tmp/x\nHEAD deadbeef\n"
        with pytest.raises(ValueError):
            parse_porcelain(malformed)


# --------------------------------------------------------------------------
# classify (defect-1 collision fixtures + real-fixture round trip)
# --------------------------------------------------------------------------


class TestClassifyEntry:
    def test_classify_main_entry(self):
        entries = parse_porcelain(FIXTURE_PORCELAIN_REAL)
        wc = classify_entry(entries[0], host=REPO_ROOT, repo_root=REPO_ROOT, is_main=True)
        assert wc is WorktreeClass.MAIN

    def test_classify_isolation_by_path_even_with_feature_branch_name(self):
        # DS-118 defect 1, reproduced: an isolation-created worktree
        # (`.claude/worktrees/agent-*`) whose branch was renamed to the
        # `feature/*` convention post-creation - the live, observed
        # collision. Path wins; branch name is never consulted.
        entry = WorktreeEntry(
            path=f"{REPO_ROOT}/.claude/worktrees/agent-a1a5afef2f39362a6",
            head="51a598c81e8f4c19920cb6aa571fea70ff5d2eb4",
            branch="feature/ds108-tasks-jsonl-cross-session",
            is_detached=False,
        )
        wc = classify_entry(entry, host=REPO_ROOT, repo_root=REPO_ROOT, is_main=False)
        assert wc is WorktreeClass.ISOLATION

    def test_classify_conductor_created_by_path_even_with_fix_branch_name(self):
        entry = WorktreeEntry(
            path=f"{REPO_ROOT}/.agentic/worktrees/context-safe-io-core-v2",
            head="9cfe17748022d0865cd6be16b95297f43011934c",
            branch="feature/context-safe-io-core-v2",
            is_detached=False,
        )
        wc = classify_entry(entry, host=REPO_ROOT, repo_root=REPO_ROOT, is_main=False)
        assert wc is WorktreeClass.CONDUCTOR_CREATED

    def test_classify_detached_isolation_entry_still_classified_by_path(self):
        entry = WorktreeEntry(
            path=f"{REPO_ROOT}/.claude/worktrees/agent-a162cb0ddd4a04c6c",
            head="5ca5ac4541b7a454f16ed34c00d17c45b35be06b",
            branch=None,
            is_detached=True,
        )
        wc = classify_entry(entry, host=REPO_ROOT, repo_root=REPO_ROOT, is_main=False)
        assert wc is WorktreeClass.ISOLATION

    def test_classify_bare_entry_is_unmanaged(self):
        entries = parse_porcelain(FIXTURE_PORCELAIN_BARE)
        wc = classify_entry(entries[0], host="/tmp/scratch", repo_root="/tmp/scratch", is_main=False)
        assert wc is WorktreeClass.UNMANAGED

    def test_classify_unrecognized_in_repo_path_is_unmanaged(self):
        entry = WorktreeEntry(
            path=f"{REPO_ROOT}/some/random/place",
            head="deadbeef",
            branch="whatever",
            is_detached=False,
        )
        wc = classify_entry(entry, host=REPO_ROOT, repo_root=REPO_ROOT, is_main=False)
        assert wc is WorktreeClass.UNMANAGED

    def test_classify_pre_fix_failure_mode_naive_substring_match(self):
        # Companion test: demonstrates why classify_entry uses
        # relative_path's normalized PREFIX check rather than a naive
        # substring test. A path that merely CONTAINS the isolation marker
        # string, without actually being rooted under it, must not
        # false-positive as ISOLATION.
        path = f"{REPO_ROOT}/backup-of-.claude/worktrees/agent-lookalike"
        naive_match = ".claude/worktrees/" in path  # the pre-fix heuristic
        assert naive_match is True  # the naive check WOULD false-positive

        entry = WorktreeEntry(path=path, head="deadbeef", branch="whatever", is_detached=False)
        wc = classify_entry(entry, host=REPO_ROOT, repo_root=REPO_ROOT, is_main=False)
        # The prefix-anchored, relative_path-based check correctly refuses
        # to match: "backup-of-.claude/worktrees/..." does not START with
        # ".claude/worktrees/" once relativized.
        assert wc is WorktreeClass.UNMANAGED


class TestClassifyCrossRepo:
    def test_cross_repo_worktree_never_classified_isolation(self):
        # A worktree that belongs to a DIFFERENT repository entirely, whose
        # path happens to sit under a `.claude/worktrees/`-shaped subpath of
        # ITS OWN (foreign) root - must resolve UNMANAGED, never ISOLATION,
        # when classified against THIS repo's host/repo_root.
        foreign_entry = WorktreeEntry(
            path="/Users/tyson/Documents/Development/other-repo/.claude/worktrees/agent-foreign",
            head="cafebabe",
            branch="feature/unrelated",
            is_detached=False,
        )
        wc = classify_entry(foreign_entry, host=REPO_ROOT, repo_root=REPO_ROOT, is_main=False)
        assert wc is WorktreeClass.UNMANAGED

    def test_cross_repo_worktree_named_worktree_agent_still_unmanaged(self):
        # Even a branch NAMED with the isolation convention does not matter
        # here - classify_entry never reads entry.branch at all (outcome
        # rubric line 1).
        foreign_entry = WorktreeEntry(
            path="/some/other/host/repo/.claude/worktrees/agent-x",
            head="cafebabe",
            branch="worktree-agent-x",
            is_detached=False,
        )
        wc = classify_entry(foreign_entry, host=REPO_ROOT, repo_root=REPO_ROOT, is_main=False)
        assert wc is WorktreeClass.UNMANAGED

    def test_host_not_equal_repo_root_foreign_path_stays_unmanaged(self):
        # DS-118's MANDATORY cross-repo non-collision guarantee, exercised
        # with `host != repo_root` for the first time (all other tests in
        # this suite pass them equal, which is why a mutation deleting the
        # `under_host` guard (":316-317") previously survived all 33 tests -
        # `relative_path` alone happened to fail closed by coincidence in
        # every host==repo_root fixture). Here `host` is THIS repo's root
        # but the caller passes a DIFFERENT (foreign) `repo_root` - the
        # scenario the guard exists to catch: without it, `relative_path`
        # would relativize the foreign entry against the foreign
        # `repo_root` and produce a matching `.claude/worktrees/` prefix,
        # misclassifying it ISOLATION.
        foreign_root = "/some/other/host/repo"
        foreign_entry = WorktreeEntry(
            path=f"{foreign_root}/.claude/worktrees/agent-x",
            head="cafebabe",
            branch="feature/unrelated",
            is_detached=False,
        )
        wc = classify_entry(foreign_entry, host=REPO_ROOT, repo_root=foreign_root, is_main=False)
        assert wc is WorktreeClass.UNMANAGED


class TestClassifyBareEntryUnderAdminPath:
    def test_bare_entry_under_isolation_path_still_unmanaged(self):
        # Companion to test_classify_bare_entry_is_unmanaged: that test's
        # bare fixture path ("/tmp/scratch/bare.git") is NOT under either
        # admin prefix, so it resolves UNMANAGED via the fall-through branch
        # even with the `is_bare` guard (":308-311") deleted - which is why
        # a mutation removing that guard also survived all 33 tests. Here
        # the bare entry's path IS under `.claude/worktrees/`, so only the
        # explicit `is_bare` guard - not the fall-through - can produce the
        # correct UNMANAGED result; without it this would misclassify
        # ISOLATION.
        entry = WorktreeEntry(
            path=f"{REPO_ROOT}/.claude/worktrees/bare-like",
            head=None,
            branch=None,
            is_detached=False,
            is_bare=True,
        )
        wc = classify_entry(entry, host=REPO_ROOT, repo_root=REPO_ROOT, is_main=False)
        assert wc is WorktreeClass.UNMANAGED


class TestClassifyEvals:
    def test_evals_worktrees_resolve_unmanaged(self):
        # evals/.worktrees/wt-* entries are pinned worktrees of a nested,
        # separately-managed repo - they must resolve UNMANAGED even though
        # their path IS a real descendant of this repo's own host/repo_root
        # (unlike the cross-repo case above), because they do not sit under
        # either recognized admin subdirectory.
        entries = parse_porcelain(FIXTURE_PORCELAIN_REAL)
        entry = next(e for e in entries if e.path.endswith("wt-6343844a930f"))
        wc = classify_entry(entry, host=REPO_ROOT, repo_root=REPO_ROOT, is_main=False)
        assert wc is WorktreeClass.UNMANAGED


def test_classify_entry_is_branch_invariant_sweep():
    # Outcome rubric line 1's invariant ("classify_entry never reads
    # entry.branch"), swept mechanically across 4 representative paths x 9
    # branch values rather than asserted from a single fixture per class -
    # closes this ticket's Minor 1 (the invariant held empirically but was
    # previously untested as a sweep). Any branch value must yield the same
    # WorktreeClass for a fixed path.
    paths = [
        REPO_ROOT,  # is_main True case handled separately below
        f"{REPO_ROOT}/.claude/worktrees/agent-x",
        f"{REPO_ROOT}/.agentic/worktrees/some-unit",
        f"{REPO_ROOT}/some/random/place",
    ]
    branch_values = [
        None,
        "main",
        "master",
        "develop",
        "feature/x",
        "fix/y",
        "chore/z",
        "worktree-agent-x",
        "weird/../branch",
    ]
    for path in paths:
        results = set()
        for branch in branch_values:
            entry = WorktreeEntry(
                path=path,
                head="deadbeef",
                branch=branch,
                is_detached=(branch is None),
            )
            wc = classify_entry(entry, host=REPO_ROOT, repo_root=REPO_ROOT, is_main=(path == REPO_ROOT))
            results.add(wc)
        assert len(results) == 1, f"path {path!r} classified differently across branch values: {results}"


def test_relative_path_pure_normalization():
    assert relative_path(f"{REPO_ROOT}/.claude/worktrees/agent-x", REPO_ROOT) == ".claude/worktrees/agent-x"
    assert relative_path(REPO_ROOT, REPO_ROOT) == "."
    assert relative_path("/somewhere/else", REPO_ROOT) == "/somewhere/else"


# --------------------------------------------------------------------------
# fail_closed (DispositionFacts + disposition_for gate)
# --------------------------------------------------------------------------


def _clean_branched_entry(*, locked=False):
    return WorktreeEntry(
        path=f"{REPO_ROOT}/.claude/worktrees/agent-x",
        head="deadbeef",
        branch="fix/something",
        is_detached=False,
        locked=locked,
    )


class TestDispositionFailClosed:
    def test_fail_closed_field_omission_raises_typeerror(self):
        with pytest.raises(TypeError):
            DispositionFacts(  # missing pr_state AND origin_reachable
                dirty_status="clean",
                head_reachable="reachable",
                ls_remote_status="pushed",
                merge_evidence="merged",
                content_subsumption="not_checked",
            )

    def test_fail_closed_origin_reachable_omission_alone_raises_typeerror(self):
        # DS-196 (R3-Minor fold): pins origin_reachable's own no-default
        # status independently of pr_state's - every OTHER field is
        # present here, isolating the omission to origin_reachable alone,
        # so a later `origin_reachable: str = "not_checked"` default could
        # not silently retire this invariant without reddening this test.
        with pytest.raises(TypeError):
            DispositionFacts(  # missing origin_reachable only
                dirty_status="clean",
                head_reachable="reachable",
                ls_remote_status="pushed",
                merge_evidence="merged",
                content_subsumption="not_checked",
                pr_state="MERGED",
            )

    def test_fail_closed_dirty_not_checked_skips(self):
        facts = DispositionFacts(
            dirty_status="not_checked",
            head_reachable="reachable",
            ls_remote_status="pushed",
            merge_evidence="merged",
            content_subsumption="not_checked",
            pr_state="MERGED",
            origin_reachable="not_checked",  # DS-196
        )
        result = disposition_for(_clean_branched_entry(), WorktreeClass.ISOLATION, facts)
        assert result is Disposition.SKIP_DIRTY

    def test_fail_closed_all_evidence_not_checked_never_defaults_eligible(self):
        facts = DispositionFacts(
            dirty_status="clean",
            head_reachable="not_checked",
            ls_remote_status="not_checked",
            merge_evidence="not_checked",
            content_subsumption="not_checked",
            pr_state="not_checked",
            origin_reachable="not_checked",  # DS-196
        )
        result = disposition_for(_clean_branched_entry(), WorktreeClass.ISOLATION, facts)
        assert result is not Disposition.ELIGIBLE
        assert result is Disposition.SKIP_AMBIGUOUS_NO_PR

    def test_fail_closed_detached_head_not_checked_skips(self):
        entry = WorktreeEntry(
            path=f"{REPO_ROOT}/.claude/worktrees/agent-x",
            head="deadbeef",
            branch=None,
            is_detached=True,
        )
        facts = DispositionFacts(
            dirty_status="clean",
            head_reachable="not_checked",
            ls_remote_status="not_checked",
            merge_evidence="not_checked",
            content_subsumption="not_checked",
            pr_state="not_checked",
            origin_reachable="not_checked",  # DS-196
        )
        result = disposition_for(entry, WorktreeClass.ISOLATION, facts)
        assert result is Disposition.SKIP_UNREFERENCED_COMMIT

    def test_disposition_for_locked_skips_before_anything_else(self):
        facts = DispositionFacts(
            dirty_status="clean",
            head_reachable="reachable",
            ls_remote_status="pushed",
            merge_evidence="merged",
            content_subsumption="not_checked",
            pr_state="MERGED",
            origin_reachable="not_checked",  # DS-196
        )
        result = disposition_for(_clean_branched_entry(locked=True), WorktreeClass.ISOLATION, facts)
        assert result is Disposition.SKIP_LOCKED

    def test_disposition_for_main_and_unmanaged_never_eligible(self):
        facts = DispositionFacts(
            dirty_status="clean",
            head_reachable="reachable",
            ls_remote_status="pushed",
            merge_evidence="merged",
            content_subsumption="not_checked",
            pr_state="MERGED",
            origin_reachable="not_checked",  # DS-196
        )
        entry = _clean_branched_entry()
        assert disposition_for(entry, WorktreeClass.MAIN, facts) is Disposition.SKIP_MAIN
        assert disposition_for(entry, WorktreeClass.UNMANAGED, facts) is Disposition.SKIP_UNMANAGED

    def test_disposition_for_eligible_on_merged_evidence(self):
        facts = DispositionFacts(
            dirty_status="clean",
            head_reachable="reachable",
            ls_remote_status="not_checked",
            merge_evidence="merged",
            content_subsumption="not_checked",
            pr_state="not_checked",
            origin_reachable="not_checked",  # DS-196
        )
        result = disposition_for(_clean_branched_entry(), WorktreeClass.ISOLATION, facts)
        assert result is Disposition.ELIGIBLE

    def test_disposition_for_squash_merged_live_worktree_stays_reclaimable(self):
        # DS-153 Amendment B1 - the decisive regression this split exists to
        # prevent: a LIVE worktree (`disposition_for`, `git worktree
        # remove`) whose only evidence is a bare `pr_state == "MERGED"` -
        # `merge_evidence` inconclusive (squash merge breaks ancestry) and
        # `content_subsumption` never computed for a worktree (G1 in
        # ds-branch-prune skips worktree-checked-out branches; nothing
        # computes the subsumption predicate for a live worktree). Under
        # the pre-B1 shared-checker design this would have hit the new
        # terminal skip and stranded every squash-merged live worktree
        # permanently. `disposition_for` must remain ELIGIBLE.
        facts = DispositionFacts(
            dirty_status="clean",
            head_reachable="reachable",
            ls_remote_status="pushed",
            merge_evidence="not_checked",
            content_subsumption="not_checked",
            pr_state="MERGED",
            origin_reachable="not_checked",  # DS-196
        )
        result = disposition_for(_clean_branched_entry(), WorktreeClass.ISOLATION, facts)
        assert result is Disposition.ELIGIBLE


# --------------------------------------------------------------------------
# orphan_branch
# --------------------------------------------------------------------------


class TestDispositionForOrphanBranch:
    def test_orphan_branch_eligible_on_merged_evidence(self):
        facts = DispositionFacts(
            dirty_status="not_checked",  # irrelevant - no worktree, no working tree
            head_reachable="not_checked",  # irrelevant - no worktree
            ls_remote_status="not_checked",
            merge_evidence="merged",
            content_subsumption="not_checked",
            pr_state="not_checked",
            origin_reachable="not_checked",  # DS-196
        )
        assert disposition_for_orphan_branch("some-branch", facts) is Disposition.ELIGIBLE

    def test_orphan_branch_pr_open_skips(self):
        facts = DispositionFacts(
            dirty_status="not_checked",
            head_reachable="not_checked",
            ls_remote_status="pushed",
            merge_evidence="not_checked",
            content_subsumption="not_checked",
            pr_state="OPEN",
            origin_reachable="not_checked",  # DS-196
        )
        assert disposition_for_orphan_branch("some-branch", facts) is Disposition.SKIP_PR_OPEN

    def test_orphan_branch_no_evidence_at_all_skips_ambiguous(self):
        facts = DispositionFacts(
            dirty_status="not_checked",
            head_reachable="not_checked",
            ls_remote_status="not_checked",
            merge_evidence="not_checked",
            content_subsumption="not_checked",
            pr_state="not_checked",
            origin_reachable="not_checked",  # DS-196
        )
        assert disposition_for_orphan_branch("some-branch", facts) is Disposition.SKIP_AMBIGUOUS_NO_PR

    def test_orphan_branch_main_and_master_never_eligible_even_with_merged_evidence(self):
        # Major 5: main/master previously resolved ELIGIBLE when
        # merge_evidence="merged" - trivially true for a base branch
        # against itself. The base-branch guard must win over every
        # evidence source, including the strongest one.
        facts = DispositionFacts(
            dirty_status="not_checked",
            head_reachable="not_checked",
            ls_remote_status="not_checked",
            merge_evidence="merged",
            content_subsumption="not_checked",
            pr_state="MERGED",
            origin_reachable="not_checked",  # DS-196
        )
        assert disposition_for_orphan_branch("main", facts) is Disposition.SKIP_BASE_BRANCH
        assert disposition_for_orphan_branch("master", facts) is Disposition.SKIP_BASE_BRANCH
        assert DEFAULT_BASE_BRANCHES == ("main", "master")

    def test_orphan_branch_base_branches_is_explicit_not_inferred(self):
        # A caller with a differently-named base branch (e.g. "develop")
        # must pass its own base_branches - the function never infers one,
        # and the default set does not silently protect an unlisted branch.
        facts = DispositionFacts(
            dirty_status="not_checked",
            head_reachable="not_checked",
            ls_remote_status="not_checked",
            merge_evidence="merged",
            content_subsumption="not_checked",
            pr_state="not_checked",
            origin_reachable="not_checked",  # DS-196
        )
        assert disposition_for_orphan_branch("develop", facts) is Disposition.ELIGIBLE
        assert (
            disposition_for_orphan_branch("develop", facts, base_branches=("develop",))
            is Disposition.SKIP_BASE_BRANCH
        )

    def test_orphan_branch_pr_merged_alone_is_terminal_skip(self):
        # DS-153 B1: the single most important line in the change. A bare
        # MERGED PR is affirmatively insufficient for BRANCH DELETION
        # (`git branch -D`) - it proves a PR merged, not that this local
        # tip's content is on the base branch. Both merge_evidence and
        # content_subsumption are inconclusive here, so reaching pr_state
        # must produce SKIP_PR_MERGED_UNPROVEN, never ELIGIBLE.
        facts = DispositionFacts(
            dirty_status="not_checked",
            head_reachable="not_checked",
            ls_remote_status="pushed",
            merge_evidence="not_checked",
            content_subsumption="not_checked",
            pr_state="MERGED",
            origin_reachable="not_checked",  # DS-196
        )
        result = disposition_for_orphan_branch("some-branch", facts)
        assert result is Disposition.SKIP_PR_MERGED_UNPROVEN
        assert result is not Disposition.ELIGIBLE

    def test_orphan_branch_content_subsumed_is_eligible_despite_bare_merged_pr(self):
        # DS-153 B1: content_subsumption == "subsumed" (the plan's
        # four-layer predicate having proven the tip's content is on the
        # base branch) rescues an otherwise-terminal bare MERGED PR -
        # content_subsumption is checked BEFORE pr_state in
        # MERGE_EVIDENCE_ORDER, so ELIGIBLE is reached without ever
        # consulting the (still bare) MERGED pr_state.
        facts = DispositionFacts(
            dirty_status="not_checked",
            head_reachable="not_checked",
            ls_remote_status="pushed",
            merge_evidence="not_checked",
            content_subsumption="subsumed",
            pr_state="MERGED",
            origin_reachable="not_checked",  # DS-196
        )
        result = disposition_for_orphan_branch("some-branch", facts)
        assert result is Disposition.ELIGIBLE

    def test_orphan_branch_content_not_checked_fails_closed_to_terminal_skip(self):
        # Companion to the two tests above: "not_checked" (the caller could
        # not compute the predicate at all - e.g. degraded mode with no gh
        # candidate data) is inconclusive, not a green light, and falls
        # through to the same terminal pr_state check as "not_subsumed".
        facts = DispositionFacts(
            dirty_status="not_checked",
            head_reachable="not_checked",
            ls_remote_status="pushed",
            merge_evidence="not_checked",
            content_subsumption="not_checked",
            pr_state="MERGED",
            origin_reachable="not_checked",  # DS-196
        )
        result = disposition_for_orphan_branch("some-branch", facts)
        assert result is Disposition.SKIP_PR_MERGED_UNPROVEN

    def test_orphan_branch_squash_merged_live_worktree_evidence_is_skipped(self):
        # DS-153 B1, the direct counterpart of
        # test_disposition_for_squash_merged_live_worktree_stays_reclaimable:
        # feeding the IDENTICAL evidence shape (bare MERGED PR, no ancestry,
        # no subsumption computed) through the BRANCH-DELETION function
        # must yield the opposite verdict, proving the split is real and
        # testable rather than accidental.
        facts = DispositionFacts(
            dirty_status="not_checked",
            head_reachable="not_checked",
            ls_remote_status="pushed",
            merge_evidence="not_checked",
            content_subsumption="not_checked",
            pr_state="MERGED",
            origin_reachable="not_checked",  # DS-196
        )
        result = disposition_for_orphan_branch("some-branch", facts)
        assert result is Disposition.SKIP_PR_MERGED_UNPROVEN

    def test_orphan_branch_never_produces_worktree_only_dispositions(self):
        # Source-level guarantee: disposition_for_orphan_branch has no
        # WorktreeClass parameter at all, so it structurally cannot return
        # SKIP_MAIN, SKIP_UNMANAGED, SKIP_LOCKED, SKIP_DIRTY, or
        # SKIP_UNREFERENCED_COMMIT - verified here by exhausting every
        # facts combination against the reachable disposition set.
        unreachable = {
            Disposition.SKIP_MAIN,
            Disposition.SKIP_UNMANAGED,
            Disposition.SKIP_LOCKED,
            Disposition.SKIP_DIRTY,
            Disposition.SKIP_UNREFERENCED_COMMIT,
        }
        dirty_values = ["clean", "dirty", "not_checked"]
        reach_values = ["reachable", "unreachable", "not_checked"]
        ls_values = ["pushed", "not_pushed", "error", "not_checked"]
        merge_values = ["merged", "unmerged", "not_checked"]
        subsumption_values = ["subsumed", "not_subsumed", "not_checked"]
        pr_values = ["OPEN", "MERGED", "CLOSED", "NONE", "not_checked"]
        # DS-196 (R3-MAJOR-3 fold): origin_reachable is a full 3-value
        # dimension here rather than held fixed at "not_checked" - proving
        # disposition_for_orphan_branch never produces a worktree-only
        # disposition regardless of what this new field carries, since
        # _EVIDENCE_CHECKS_STRICT has no "origin_reachable" key at all.
        origin_reachable_values = ["reachable", "unreachable", "not_checked"]
        seen = set()
        for d in dirty_values:
            for r in reach_values:
                for ls in ls_values:
                    for m in merge_values:
                        for cs in subsumption_values:
                            for pr in pr_values:
                                for orig in origin_reachable_values:
                                    facts = DispositionFacts(
                                        dirty_status=d,
                                        head_reachable=r,
                                        ls_remote_status=ls,
                                        merge_evidence=m,
                                        content_subsumption=cs,
                                        pr_state=pr,
                                        origin_reachable=orig,
                                    )
                                    seen.add(disposition_for_orphan_branch("b", facts))
        assert seen.isdisjoint(unreachable)


# --------------------------------------------------------------------------
# ordering (MERGE_EVIDENCE_ORDER mutation switch)
# --------------------------------------------------------------------------


class TestMergeEvidenceOrdering:
    def test_ordering_default_precedence_is_merge_evidence_first(self):
        assert MERGE_EVIDENCE_ORDER == (
            "merge_evidence",
            "content_subsumption",
            "pr_state",
            "ls_remote_status",
        )

    def test_ordering_mutation_switch_proves_order_load_bearing(self):
        # A branch whose PR is OPEN (a hard safety signal) but whose local
        # push status is stale/not-pushed. Under the NORMATIVE order
        # (merge_evidence, pr_state, ls_remote_status), merge_evidence is
        # inconclusive and pr_state="OPEN" wins -> SKIP_PR_OPEN. Under a
        # REVERSED order, ls_remote_status is checked first and
        # "not_pushed" wins instead -> SKIP_NOT_PUSHED. Different results
        # from the same facts prove the order is load-bearing, not
        # decorative - the reversed order silently loses the PR-open
        # safety signal.
        facts = DispositionFacts(
            dirty_status="clean",
            head_reachable="not_checked",
            ls_remote_status="not_pushed",
            merge_evidence="not_checked",
            content_subsumption="not_checked",
            pr_state="OPEN",
            origin_reachable="not_checked",  # DS-196
        )
        normative = disposition_for_orphan_branch("b", facts, merge_evidence_order=MERGE_EVIDENCE_ORDER)
        reversed_order = tuple(reversed(MERGE_EVIDENCE_ORDER))
        mutated = disposition_for_orphan_branch("b", facts, merge_evidence_order=reversed_order)

        assert normative is Disposition.SKIP_PR_OPEN
        assert mutated is Disposition.SKIP_NOT_PUSHED
        assert normative is not mutated


# --------------------------------------------------------------------------
# DS-196: origin_reachable evidence (LENIENT-only, worktree removal)
# --------------------------------------------------------------------------


def _clean_branched_facts(*, pr_state: str, origin_reachable: str) -> DispositionFacts:
    return DispositionFacts(
        dirty_status="clean",
        head_reachable="not_checked",
        ls_remote_status="not_checked",
        merge_evidence="not_checked",
        content_subsumption="not_checked",
        pr_state=pr_state,
        origin_reachable=origin_reachable,
    )


class TestCheckOriginReachable:
    def test_eligible_when_reachable_and_pr_state_resolved(self):
        facts = _clean_branched_facts(pr_state="NONE", origin_reachable="reachable")
        assert _check_origin_reachable(facts) is Disposition.ELIGIBLE

    def test_none_when_unreachable(self):
        facts = _clean_branched_facts(pr_state="NONE", origin_reachable="unreachable")
        assert _check_origin_reachable(facts) is None

    def test_none_when_pr_state_not_checked_even_if_reachable(self):
        # DS-196 --no-gh safety property (QA scenario 8): pr_state must
        # be AFFIRMATIVELY resolved before origin_reachable is trusted -
        # otherwise a worktree behind a live OPEN PR the query simply
        # could not see would be indistinguishable from a safely-reapable
        # one.
        facts = _clean_branched_facts(pr_state="not_checked", origin_reachable="reachable")
        assert _check_origin_reachable(facts) is None

    def test_pr_state_precondition_mutation_reddens_to_eligible(self):
        # Named mutation: removing the pr_state precondition entirely
        # makes an origin-reachable-but-pr-state-unresolved entry resolve
        # ELIGIBLE, which is exactly the unsafe behavior the precondition
        # exists to prevent.
        def _unsafe_check(facts: DispositionFacts):
            if facts.origin_reachable == "reachable":
                return Disposition.ELIGIBLE
            return None

        facts = _clean_branched_facts(pr_state="not_checked", origin_reachable="reachable")
        assert _check_origin_reachable(facts) is None
        assert _unsafe_check(facts) is Disposition.ELIGIBLE

    def test_full_disposition_for_reaches_eligible_via_origin_reachable(self):
        # QA scenario 1 (worktree_model half): a squash-merged (ancestry
        # inconclusive), origin-reachable, resolved-non-open-PR entry
        # reaches ELIGIBLE via WORKTREE_REMOVAL_EVIDENCE_ORDER's new slot.
        facts = _clean_branched_facts(pr_state="NONE", origin_reachable="reachable")
        result = disposition_for(_clean_branched_entry(), WorktreeClass.ISOLATION, facts)
        assert result is Disposition.ELIGIBLE

    def test_full_disposition_for_stays_ambiguous_when_unreachable(self):
        facts = _clean_branched_facts(pr_state="NONE", origin_reachable="unreachable")
        result = disposition_for(_clean_branched_entry(), WorktreeClass.ISOLATION, facts)
        assert result is Disposition.SKIP_AMBIGUOUS_NO_PR

    def test_open_pr_wins_over_origin_reachable(self):
        # QA scenario 7 / Critical-fix regression: pr_state precedes
        # origin_reachable in WORKTREE_REMOVAL_EVIDENCE_ORDER, so an OPEN
        # PR's veto can never be shadowed.
        facts = _clean_branched_facts(pr_state="OPEN", origin_reachable="reachable")
        result = disposition_for(_clean_branched_entry(), WorktreeClass.ISOLATION, facts)
        assert result is Disposition.SKIP_PR_OPEN

    def test_reordering_before_pr_state_reddens_open_pr_to_remove(self):
        # Named mutation for the above: reordering origin_reachable BEFORE
        # pr_state in the evidence-order tuple passed explicitly flips the
        # OPEN-PR-protected entry to ELIGIBLE - proving the shipped order
        # (pr_state before origin_reachable) is load-bearing.
        facts = _clean_branched_facts(pr_state="OPEN", origin_reachable="reachable")
        mutated_order = (
            "merge_evidence",
            "content_subsumption",
            "origin_reachable",
            "pr_state",
            "ls_remote_status",
        )
        result = disposition_for(
            _clean_branched_entry(), WorktreeClass.ISOLATION, facts, merge_evidence_order=mutated_order
        )
        assert result is Disposition.ELIGIBLE

    def test_no_origin_reachable_evidence_rollback_reproduces_pre_ds196(self):
        # QA scenario 6: passing MERGE_EVIDENCE_ORDER explicitly (the
        # --no-origin-reachable-evidence rollback lever's call-site shape)
        # reproduces pre-DS-196 behavior exactly - no origin-reachable
        # REMOVE with it set.
        facts = _clean_branched_facts(pr_state="NONE", origin_reachable="reachable")
        result = disposition_for(
            _clean_branched_entry(), WorktreeClass.ISOLATION, facts, merge_evidence_order=MERGE_EVIDENCE_ORDER
        )
        assert result is Disposition.SKIP_AMBIGUOUS_NO_PR


class TestOriginReachableStrictPathIsolation:
    """QA scenario 2 (redesigned per R3-MAJOR-3): the STRICT/branch-deletion
    path must be structurally unreachable by origin-reachability evidence.
    """

    def test_origin_reachable_absent_from_strict_checks_dict(self):
        assert "origin_reachable" not in worktree_model._EVIDENCE_CHECKS_STRICT

    def test_origin_reachable_absent_from_module_level_merge_evidence_order(self):
        assert "origin_reachable" not in MERGE_EVIDENCE_ORDER

    def test_both_conditions_required_monkeypatch_mutation_proves_load_bearing(self, monkeypatch):
        # R3-MAJOR-3 (binding): the mutation MUST pass
        # merge_evidence_order=MERGE_EVIDENCE_ORDER + ("origin_reachable",)
        # EXPLICITLY to disposition_for_orphan_branch alongside
        # monkeypatch.setitem on _EVIDENCE_CHECKS_STRICT - NEVER a setattr
        # on the module-level MERGE_EVIDENCE_ORDER tuple, since
        # disposition_for_orphan_branch's default is a DEF-TIME binding
        # (a setattr-based mutation is inert and would fail loudly instead
        # of proving anything).
        monkeypatch.setitem(
            worktree_model._EVIDENCE_CHECKS_STRICT, "origin_reachable", worktree_model._check_origin_reachable
        )
        mutated_order = MERGE_EVIDENCE_ORDER + ("origin_reachable",)

        facts = DispositionFacts(
            dirty_status="not_checked",
            head_reachable="not_checked",
            ls_remote_status="pushed",
            merge_evidence="not_checked",
            content_subsumption="not_checked",
            pr_state="NONE",
            origin_reachable="reachable",
        )
        # Baseline: with the real (unmutated) default order, this same
        # facts object never reaches ELIGIBLE via origin_reachable.
        baseline = disposition_for_orphan_branch("some-branch", facts)
        assert baseline is not Disposition.ELIGIBLE

        mutated = disposition_for_orphan_branch(
            "some-branch", facts, merge_evidence_order=mutated_order
        )
        assert mutated is Disposition.ELIGIBLE


class TestEvidenceOrderKeyConsistency:
    """Plan step 17 / QA scenario 11: order-tuple/checks-dict key-set
    consistency across every valid (order, strict) pairing this module's
    public functions can actually produce."""

    def test_assertion_passes_on_live_module_state(self):
        # Should not raise - already called once at import time; calling
        # it again here is itself part of the regression coverage (a
        # future edit that breaks the live pairings breaks this test too,
        # not just module import).
        _assert_evidence_order_key_consistency()

    def test_mutation_order_entry_with_no_dict_key_reddens(self, monkeypatch):
        mutated_order = WORKTREE_REMOVAL_EVIDENCE_ORDER + ("nonexistent_evidence_key",)
        monkeypatch.setattr(
            worktree_model,
            "_VALID_EVIDENCE_ORDER_CHECKS_PAIRINGS",
            ((mutated_order, worktree_model._EVIDENCE_CHECKS_LENIENT),),
        )
        with pytest.raises(AssertionError):
            worktree_model._assert_evidence_order_key_consistency()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
