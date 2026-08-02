#!/usr/bin/env python3
"""
Purpose: pytest suite for bin/tests/worktree_model.py (DS-118). Property/
         regression tests for parse_porcelain's real-fixture and bare-repo
         handling, classify_entry's path-and-host-only classification
         (including the defect-1 collision fixtures and the cross-repo /
         evals/.worktrees non-collision cases), disposition_for's fail-
         closed gate, disposition_for_orphan_branch's WorktreeClass-free
         reduction, and the MERGE_EVIDENCE_ORDER mutation switch.

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

from worktree_model import (  # noqa: E402
    MERGE_EVIDENCE_ORDER,
    Disposition,
    DispositionFacts,
    WorktreeClass,
    WorktreeEntry,
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
            DispositionFacts(  # missing pr_state
                dirty_status="clean",
                head_reachable="reachable",
                ls_remote_status="pushed",
                merge_evidence="merged",
            )

    def test_fail_closed_dirty_not_checked_skips(self):
        facts = DispositionFacts(
            dirty_status="not_checked",
            head_reachable="reachable",
            ls_remote_status="pushed",
            merge_evidence="merged",
            pr_state="MERGED",
        )
        result = disposition_for(_clean_branched_entry(), WorktreeClass.ISOLATION, facts)
        assert result is Disposition.SKIP_DIRTY

    def test_fail_closed_all_evidence_not_checked_never_defaults_eligible(self):
        facts = DispositionFacts(
            dirty_status="clean",
            head_reachable="not_checked",
            ls_remote_status="not_checked",
            merge_evidence="not_checked",
            pr_state="not_checked",
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
            pr_state="not_checked",
        )
        result = disposition_for(entry, WorktreeClass.ISOLATION, facts)
        assert result is Disposition.SKIP_UNREFERENCED_COMMIT

    def test_disposition_for_locked_skips_before_anything_else(self):
        facts = DispositionFacts(
            dirty_status="clean",
            head_reachable="reachable",
            ls_remote_status="pushed",
            merge_evidence="merged",
            pr_state="MERGED",
        )
        result = disposition_for(_clean_branched_entry(locked=True), WorktreeClass.ISOLATION, facts)
        assert result is Disposition.SKIP_LOCKED

    def test_disposition_for_main_and_unmanaged_never_eligible(self):
        facts = DispositionFacts(
            dirty_status="clean",
            head_reachable="reachable",
            ls_remote_status="pushed",
            merge_evidence="merged",
            pr_state="MERGED",
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
            pr_state="not_checked",
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
            pr_state="not_checked",
        )
        assert disposition_for_orphan_branch("some-branch", facts) is Disposition.ELIGIBLE

    def test_orphan_branch_pr_open_skips(self):
        facts = DispositionFacts(
            dirty_status="not_checked",
            head_reachable="not_checked",
            ls_remote_status="pushed",
            merge_evidence="not_checked",
            pr_state="OPEN",
        )
        assert disposition_for_orphan_branch("some-branch", facts) is Disposition.SKIP_PR_OPEN

    def test_orphan_branch_no_evidence_at_all_skips_ambiguous(self):
        facts = DispositionFacts(
            dirty_status="not_checked",
            head_reachable="not_checked",
            ls_remote_status="not_checked",
            merge_evidence="not_checked",
            pr_state="not_checked",
        )
        assert disposition_for_orphan_branch("some-branch", facts) is Disposition.SKIP_AMBIGUOUS_NO_PR

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
        pr_values = ["OPEN", "MERGED", "CLOSED", "NONE", "not_checked"]
        seen = set()
        for d in dirty_values:
            for r in reach_values:
                for ls in ls_values:
                    for m in merge_values:
                        for pr in pr_values:
                            facts = DispositionFacts(
                                dirty_status=d,
                                head_reachable=r,
                                ls_remote_status=ls,
                                merge_evidence=m,
                                pr_state=pr,
                            )
                            seen.add(disposition_for_orphan_branch("b", facts))
        assert seen.isdisjoint(unreachable)


# --------------------------------------------------------------------------
# ordering (MERGE_EVIDENCE_ORDER mutation switch)
# --------------------------------------------------------------------------


class TestMergeEvidenceOrdering:
    def test_ordering_default_precedence_is_merge_evidence_first(self):
        assert MERGE_EVIDENCE_ORDER == ("merge_evidence", "pr_state", "ls_remote_status")

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
            pr_state="OPEN",
        )
        normative = disposition_for_orphan_branch("b", facts, merge_evidence_order=MERGE_EVIDENCE_ORDER)
        reversed_order = tuple(reversed(MERGE_EVIDENCE_ORDER))
        mutated = disposition_for_orphan_branch("b", facts, merge_evidence_order=reversed_order)

        assert normative is Disposition.SKIP_PR_OPEN
        assert mutated is Disposition.SKIP_NOT_PUSHED
        assert normative is not mutated


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
