"""
Purpose: Score a single /init-project command-mode run against a labeled
         fixture by walking the worktree's filesystem snapshot and checking
         required path existence, forbidden path absence, AGENTS.md
         structure (required sections, line budget), and .gitignore
         content.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v4"}.

Contract: score() expects a single-run trace - trace["runs"] contains
          exactly one run record with a "filesystem" dict mapping repo-
          relative paths to sha256 hashes (populated by
          evals.runner.invoker when mode=="command") AND access to the
          worktree for AGENTS.md / .gitignore line-level inspection. The
          scorer reads those two files directly from disk via a
          worktree_root path passed in the run record.

Upstream deps: stdlib re, pathlib, fnmatch.

Downstream consumers: evals.runner.cli (dynamic import per manifest's
                      scoring_module).

Failure modes: Missing or empty filesystem snapshot => status
               "invalid_format", primary 0.0. Missing worktree_root =>
               AGENTS.md / .gitignore checks treated as failures but the
               existence checks still run on the snapshot keys.

Performance: standard; one pass over the snapshot keys, one read of each
             of two small text files.

---

## Scoring formula (v4)

Weighted sum across five dimensions, minus a capped extras penalty. Weights
are normalized so a perfect run scores exactly 1.0. The v1 weights summed to
0.95, so a flawless scaffold scored 0.95 with no dimension missed - confusing
for fixture authors. v2 scales every v1 weight by 1/0.95 (factor ~1.05263).

v3 adds vacuous-dimension handling: if a fixture has no applicable
conditionals (conditional_total == 0) the conditional-files dimension is
treated as vacuously satisfied and credited at 1.0, rather than 0/1 = 0.
The command did nothing wrong on an axis that did not apply. The same
vacuously-satisfied semantics are applied to the gitignore dimension when
gitignore_total == 0 (previously 0 / max(0, 1) == 0.0 incorrectly
penalized the run). Sections always have required values per fixture
schema, so no vacuous case exists there.

v4 replaces the binary line-budget flag with a tiered credit:
  - line_count <= max_lines                  -> 1.0 ("under")
  - max_lines < line_count <= max_lines + 10 -> 0.5 ("grace")
  - line_count > max_lines + 10              -> 0.0 ("over")
Weights themselves are unchanged from v3; only the line-budget term's
credit function changes. The weights-sum assertion still holds.

Justification (Overfitting-Rule-passing rationale):

Tiered line-budget credit (under -> 1.0, grace+10 -> 0.5, over -> 0.0)
reflects that AGENTS.md length is a soft quality dimension, not a hard
pass/fail. A scaffold 2 lines over budget is meaningfully different from
one 20 lines over, and the v3 binary flag collapsed that distinction.
This shape is defensible independent of any single fixture: the command
prescribes a 45-line budget, not a hard limit, and downstream reviewers
treat small overruns as warnings rather than defects.

Version history:
  v1: weights sum to 0.95 (perfect run caps at 0.95).
  v2: renormalize weights to sum to 1.0.
  v3: vacuous-dimension handling for conditional + gitignore when
      their totals are 0.
  v4: tiered line-budget credit (under/grace/over); weights unchanged.

    v1_sum  = 0.50 + 0.15 + 0.15 + 0.10 + 0.05 = 0.95
    scale   = 1 / 0.95

    w_req    = 0.50 * scale = 0.526316   (required file presence)
    w_cond   = 0.15 * scale = 0.157895   (conditional files keyed on signals)
    w_sect   = 0.15 * scale = 0.157895   (AGENTS.md section coverage)
    w_gi     = 0.10 * scale = 0.105263   (.gitignore substring coverage)
    w_budget = 0.05 * scale = 0.052632   (AGENTS.md line-budget tier credit)

    Assertion: w_req + w_cond + w_sect + w_gi + w_budget == 1.0 (see
    _WEIGHTS_SUM_ASSERTION below).

    extras_raw     = 0.3 * forbidden_present + 0.05 * unexpected_claude_md
    extras_penalty = min(extras_raw, 0.15)

    primary = clip(w_req * required_present / required_total
                   + w_cond * (1.0 if conditional_total == 0
                               else conditional_present / conditional_total)
                   + w_sect * section_hits / section_total
                   + w_gi   * (1.0 if gitignore_total == 0
                               else gitignore_hits / gitignore_total)
                   + w_budget * line_budget_credit
                   - extras_penalty, 0.0, 1.0)

Perfect-run arithmetic check:
    1.0 * 0.526316 + 1.0 * 0.157895 + 1.0 * 0.157895
  + 1.0 * 0.105263 + 1.0 * 0.052632 - 0.0
  = 1.000001 (rounds to 1.000000 after round(_, 6) + clip)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

SCORER_VERSION = "v4"

# v1 weights renormalized so a perfect run scores 1.0 instead of 0.95.
_SCALE = 1.0 / 0.95
_W_REQ = 0.50 * _SCALE
_W_COND = 0.15 * _SCALE
_W_SECT = 0.15 * _SCALE
_W_GI = 0.10 * _SCALE
_W_BUDGET = 0.05 * _SCALE

# Sanity: weights sum to 1.0 within floating-point epsilon. A perfect run
# (all ratios == 1.0, no extras penalty) MUST score exactly 1.0 after the
# final clip; fixture authors should never see 0.95 and wonder which
# dimension was missed.
_WEIGHTS_SUM_ASSERTION = abs(
    (_W_REQ + _W_COND + _W_SECT + _W_GI + _W_BUDGET) - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "init_project_lite weights must sum to 1.0"

_EXTRAS_CAP = 0.15
_EXTRAS_FORBIDDEN = 0.3
_EXTRAS_UNEXPECTED = 0.05

# v4: grace window above max_lines that still earns partial credit.
_LINE_BUDGET_GRACE = 10


def _line_budget_credit(line_count: int, max_lines: int) -> tuple[float, str]:
    if line_count <= max_lines:
        return (1.0, "under")
    if line_count <= max_lines + _LINE_BUDGET_GRACE:
        return (0.5, "grace")
    return (0.0, "over")


def _count_present(snapshot_keys: set[str], paths: list[str]) -> tuple[int, list[str]]:
    present = 0
    missing: list[str] = []
    for p in paths:
        if p in snapshot_keys:
            present += 1
        else:
            missing.append(p)
    return present, missing


def _unexpected_claude_md_count(
    snapshot_keys: set[str],
    active_conditional_paths: set[str],
    must_exist_set: set[str],
) -> int:
    always_ok = {".claude/findings.md"}
    count = 0
    for k in snapshot_keys:
        if not k.startswith(".claude/") or not k.endswith(".md"):
            continue
        if k in must_exist_set or k in active_conditional_paths or k in always_ok:
            continue
        count += 1
    return count


def score(trace: dict, fixture: dict) -> dict:
    runs = trace.get("runs") or []
    if not runs:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {"reason": "no_runs", "scorer_version": SCORER_VERSION},
            "scorer_version": SCORER_VERSION,
        }
    assert len(runs) == 1, (
        "init_project_lite.score expects a single-run trace; aggregation "
        "across N runs happens in evals.runner.aggregator."
    )
    run = runs[0]
    snapshot = run.get("filesystem")
    if not isinstance(snapshot, dict) or not snapshot:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "no_filesystem_snapshot",
                "cli_status": run.get("status"),
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }
    snapshot_keys = set(snapshot.keys())

    expected = fixture.get("expected_outputs") or {}
    must_exist = list(expected.get("must_exist") or [])
    must_not_exist = list(expected.get("must_not_exist") or [])
    cond_map = expected.get("must_exist_conditional") or {}
    expected_signals = set(expected.get("expected_signals") or [])
    required_sections = list(expected.get("agents_md_required_sections") or [])
    max_lines = int(expected.get("agents_md_max_lines") or 45)
    gi_required = list(expected.get("gitignore_required_lines") or [])

    # Required files
    required_present, missing_required = _count_present(snapshot_keys, must_exist)
    required_total = max(len(must_exist), 1)

    # Conditional files: active when their signal key is in expected_signals
    conditional_paths: list[str] = []
    for sig, paths in cond_map.items():
        if sig in expected_signals:
            conditional_paths.extend(paths)
    conditional_present, missing_conditional = _count_present(snapshot_keys, conditional_paths)
    conditional_total = len(conditional_paths)

    # Forbidden files
    forbidden_present_list = [p for p in must_not_exist if p in snapshot_keys]
    forbidden_present = len(forbidden_present_list)

    # AGENTS.md structure
    worktree_root = run.get("worktree_root")
    agents_md_path: Path | None = None
    if worktree_root and "AGENTS.md" in snapshot_keys:
        agents_md_path = Path(worktree_root) / "AGENTS.md"
    agents_md_text = ""
    if agents_md_path is not None and agents_md_path.exists():
        try:
            agents_md_text = agents_md_path.read_text(encoding="utf-8")
        except OSError:
            agents_md_text = ""

    if agents_md_text:
        agents_lines = agents_md_text.splitlines()
        line_count_agents_md = len(agents_lines)
        line_budget_ok = line_count_agents_md <= max_lines
        line_budget_credit, line_budget_tier = _line_budget_credit(
            line_count_agents_md, max_lines
        )
        section_hits = 0
        for req in required_sections:
            if any(line.startswith(req) for line in agents_lines):
                section_hits += 1
    else:
        agents_lines = []
        line_count_agents_md = 0
        line_budget_ok = False
        line_budget_credit = 0.0
        line_budget_tier = "over"
        section_hits = 0
    section_total = max(len(required_sections), 1)

    # .gitignore content
    gitignore_text = ""
    if worktree_root and ".gitignore" in snapshot_keys:
        gi_path = Path(worktree_root) / ".gitignore"
        if gi_path.exists():
            try:
                gitignore_text = gi_path.read_text(encoding="utf-8")
            except OSError:
                gitignore_text = ""
    gitignore_hits = sum(1 for s in gi_required if s in gitignore_text)
    gitignore_total = len(gi_required)

    # Extras
    active_conditional_set = set(conditional_paths)
    must_exist_set = set(must_exist)
    unexpected_claude_md = _unexpected_claude_md_count(
        snapshot_keys, active_conditional_set, must_exist_set
    )
    extras_raw = _EXTRAS_FORBIDDEN * forbidden_present + _EXTRAS_UNEXPECTED * unexpected_claude_md
    extras_penalty = min(extras_raw, _EXTRAS_CAP)

    score_primary = (
        _W_REQ * (required_present / required_total)
        + _W_COND * (1.0 if conditional_total == 0 else conditional_present / conditional_total)
        + _W_SECT * (section_hits / section_total)
        + _W_GI * (1.0 if gitignore_total == 0 else gitignore_hits / gitignore_total)
        + _W_BUDGET * line_budget_credit
        - extras_penalty
    )
    primary = max(0.0, min(1.0, score_primary))

    diagnostic: dict[str, Any] = {
        "required_present": required_present,
        "required_total": len(must_exist),
        "missing_required": missing_required,
        "conditional_present": conditional_present,
        "conditional_total": conditional_total,
        "missing_conditional": missing_conditional,
        "forbidden_present": forbidden_present,
        "forbidden_paths": forbidden_present_list,
        "section_hits": section_hits,
        "section_total": len(required_sections),
        "line_count_agents_md": line_count_agents_md,
        "line_budget_ok": line_budget_ok,
        "line_budget_credit": line_budget_credit,
        "line_budget_tier": line_budget_tier,
        "line_budget_grace_max": max_lines + _LINE_BUDGET_GRACE,
        "gitignore_hits": gitignore_hits,
        "gitignore_total": gitignore_total,
        "unexpected_claude_md": unexpected_claude_md,
        "extras_raw": round(extras_raw, 6),
        "extras_penalty": round(extras_penalty, 6),
        "snapshot_file_count": len(snapshot_keys),
        "scorer_version": SCORER_VERSION,
    }

    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
