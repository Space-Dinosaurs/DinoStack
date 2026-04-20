"""
Purpose: Score a single /cleanup-worktrees command-mode run against a labeled
         fixture by inspecting the post-run git worktree list, branch list,
         and the command's final_text report. Exercises the command's
         decisions across clean, dirty, merged-PR, open-PR, gh-missing, and
         unknown-branch-shape cases.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace whose run record carries
          "worktree_root" (the Tier 2 tmpdir the fixture repo was copied
          into - this IS the git repo the command ran against) and
          "final_text" (the command's closing report). The scorer shells
          out to `git -C worktree_root worktree list --porcelain` and
          `git -C worktree_root branch --format=%(refname:short)` to
          observe post-run state. Both shell calls are read-only.

Upstream deps: stdlib subprocess, pathlib.

Downstream consumers: evals.runner.cli (dynamic import per manifest's
                      scoring_module).

Failure modes: Missing worktree_root => status "invalid_format", primary 0.
               If `git worktree list` errors (e.g. the fixture seed failed
               to init the repo), status becomes "invalid_format" as well
               so the reader does not mistake a broken seed for a
               low-scoring command run.

Performance: two small subprocess calls, one pass over the lists. Negligible.

---

## Scoring formula (v1)

Six weighted dimensions summing to exactly 1.0. A safety-invariant
violation (the main worktree being removed) HARD-FLOORS primary to 0.0
regardless of the other axes, because removing the repo root is a class
of failure that no amount of correct report text can offset.

    w_removed   = 0.25   expected_removals absent from post-run worktree list
    w_preserved = 0.20   expected_preservations present in post-run worktree list
    w_branches  = 0.20   branch-delete and branch-preserve correctness
    w_report    = 0.15   final_text substring must_contain / must_not_contain
    w_safety    = 0.15   main worktree preserved; if violated, primary = 0.0
    w_unexpected= 0.05   inverse of stray count (worktrees still present that
                         were neither expected removed nor expected preserved),
                         soft-capped at 3

Per-axis vacuous handling: if a fixture specifies no expectations for an
axis (empty `expected_removals`, empty `expected_preservations`, no
branch expectations, no substring checks), that axis scores 1.0 rather
than 0/0. A fixture that legitimately has no feature worktrees to remove
should not be penalized on the removal axis.

Weight-sum assertion guards future re-balancing:
    assert abs(sum(weights) - 1.0) < 1e-9
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

SCORER_VERSION = "v1"

_W_REMOVED = 0.25
_W_PRESERVED = 0.20
_W_BRANCHES = 0.20
_W_REPORT = 0.15
_W_SAFETY = 0.15
_W_UNEXPECTED = 0.05

_WEIGHTS_SUM_ASSERTION = abs(
    (_W_REMOVED + _W_PRESERVED + _W_BRANCHES + _W_REPORT + _W_SAFETY + _W_UNEXPECTED)
    - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "cleanup_worktrees_lite weights must sum to 1.0"

_STRAY_SOFT_CAP = 3


def _git_worktree_list(root: Path) -> list[dict] | None:
    """Return list of {path, branch} entries from `git worktree list --porcelain`.

    Returns None if the git call errors (treated as invalid_format upstream).
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    entries: list[dict] = []
    current: dict = {}
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                entries.append(current)
            current = {"path": line[len("worktree "):].strip(), "branch": None}
        elif line.startswith("branch "):
            # branch refs/heads/foo -> "foo"
            ref = line[len("branch "):].strip()
            if ref.startswith("refs/heads/"):
                ref = ref[len("refs/heads/"):]
            current["branch"] = ref
        elif line.startswith("detached"):
            current["branch"] = None
        elif line == "" and current:
            entries.append(current)
            current = {}
    if current:
        entries.append(current)
    return entries


def _git_branches(root: Path) -> set[str] | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "branch", "--format=%(refname:short)"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return {line.strip() for line in r.stdout.splitlines() if line.strip()}


def score(trace: dict, fixture: dict) -> dict:
    runs = trace.get("runs") or []
    if not runs:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {"reason": "no_runs", "scorer_version": SCORER_VERSION},
            "scorer_version": SCORER_VERSION,
        }
    assert len(runs) == 1
    run = runs[0]
    worktree_root = run.get("worktree_root")
    if not worktree_root:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "no_worktree_root",
                "cli_status": run.get("status"),
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }
    root = Path(worktree_root)

    wt_entries = _git_worktree_list(root)
    branches = _git_branches(root)
    if wt_entries is None or branches is None:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "git_inspect_failed",
                "cli_status": run.get("status"),
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }

    expected = fixture.get("expected") or {}
    exp_removals: list[str] = list(expected.get("expected_removals") or [])
    exp_preservations: list[str] = list(expected.get("expected_preservations") or [])
    exp_branch_deletions: list[str] = list(expected.get("expected_branch_deletions") or [])
    exp_branch_preservations: list[str] = list(expected.get("expected_branch_preservations") or [])
    must_contain: list[str] = list(expected.get("must_contain") or [])
    must_not_contain: list[str] = list(expected.get("must_not_contain") or [])
    main_wt_path_rel: str | None = expected.get("main_worktree_path_rel")

    # Build the set of branches that are currently attached to a worktree
    # (post-run view).
    live_wt_branches: set[str] = {
        e["branch"] for e in wt_entries if e.get("branch")
    }

    # Safety axis: main worktree preserved. The first `git worktree list`
    # entry is always the main one; our fixtures seed the worktree such
    # that its path equals the test tmpdir root. Check that an entry with
    # path == root exists.
    main_preserved = any(
        Path(e["path"]).resolve() == root.resolve() for e in wt_entries
    )
    safety_credit = 1.0 if main_preserved else 0.0

    # Removed axis: each expected removal's branch must NOT be in the
    # post-run live worktree branch set.
    removed_hits = 0
    missing_removals: list[str] = []
    for br in exp_removals:
        if br not in live_wt_branches:
            removed_hits += 1
        else:
            missing_removals.append(br)
    removed_credit = 1.0 if not exp_removals else (removed_hits / len(exp_removals))

    # Preserved axis: each expected-preserved branch must still be in the
    # live worktree branch set.
    preserved_hits = 0
    missing_preservations: list[str] = []
    for br in exp_preservations:
        if br in live_wt_branches:
            preserved_hits += 1
        else:
            missing_preservations.append(br)
    preserved_credit = (
        1.0 if not exp_preservations else (preserved_hits / len(exp_preservations))
    )

    # Branch axis: check local branches list. Deletions must be absent;
    # preservations must be present.
    br_deletion_hits = sum(1 for b in exp_branch_deletions if b not in branches)
    br_preservation_hits = sum(1 for b in exp_branch_preservations if b in branches)
    br_total = len(exp_branch_deletions) + len(exp_branch_preservations)
    branches_credit = 1.0 if br_total == 0 else (br_deletion_hits + br_preservation_hits) / br_total
    branch_miss_detail = {
        "undeleted_branches": [b for b in exp_branch_deletions if b in branches],
        "missing_preserved_branches": [b for b in exp_branch_preservations if b not in branches],
    }

    # Report axis: final_text substring checks.
    final_text = (run.get("final_text") or "")
    contain_hits = sum(1 for s in must_contain if s.lower() in final_text.lower())
    not_contain_hits = sum(1 for s in must_not_contain if s.lower() not in final_text.lower())
    report_total = len(must_contain) + len(must_not_contain)
    report_credit = 1.0 if report_total == 0 else (contain_hits + not_contain_hits) / report_total

    # Unexpected (stray) axis: worktrees still present that were neither in
    # the expected_preservations set nor the main worktree. Uses soft cap.
    exp_preserved_set = set(exp_preservations)
    stray_entries: list[dict] = []
    for e in wt_entries:
        # Skip the main worktree (path-equal to root).
        try:
            same_as_root = Path(e["path"]).resolve() == root.resolve()
        except OSError:
            same_as_root = False
        if same_as_root:
            continue
        br = e.get("branch")
        if br and br in exp_preserved_set:
            continue
        stray_entries.append(e)
    stray_count = len(stray_entries)
    unexpected_credit = max(0.0, 1.0 - (stray_count / _STRAY_SOFT_CAP))

    # Hard floor if main worktree was removed - no matter how well the
    # rest went, destroying the repo root is a disqualifier.
    if not main_preserved:
        primary = 0.0
    else:
        primary = (
            _W_REMOVED * removed_credit
            + _W_PRESERVED * preserved_credit
            + _W_BRANCHES * branches_credit
            + _W_REPORT * report_credit
            + _W_SAFETY * safety_credit
            + _W_UNEXPECTED * unexpected_credit
        )
        primary = max(0.0, min(1.0, primary))

    diagnostic: dict[str, Any] = {
        "main_preserved": main_preserved,
        "removed_hits": removed_hits,
        "removed_total": len(exp_removals),
        "missing_removals": missing_removals,
        "preserved_hits": preserved_hits,
        "preserved_total": len(exp_preservations),
        "missing_preservations": missing_preservations,
        "branch_deletion_hits": br_deletion_hits,
        "branch_preservation_hits": br_preservation_hits,
        "branch_total": br_total,
        "branch_miss_detail": branch_miss_detail,
        "contain_hits": contain_hits,
        "not_contain_hits": not_contain_hits,
        "report_total": report_total,
        "stray_count": stray_count,
        "stray_entries": [
            {"path": e.get("path"), "branch": e.get("branch")} for e in stray_entries
        ],
        "live_worktrees": [
            {"path": e.get("path"), "branch": e.get("branch")} for e in wt_entries
        ],
        "scorer_version": SCORER_VERSION,
    }
    if main_wt_path_rel is not None:
        diagnostic["main_wt_path_rel"] = main_wt_path_rel

    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
