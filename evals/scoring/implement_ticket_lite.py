"""
Purpose: Score a single /implement-ticket command-mode run against a labeled
         fixture by inspecting the local artifacts produced by Phases 2-8 and
         Phase 12 of the command (branch created, source edited, loop-state
         written, commit made with required substrings, quality gate exit,
         scope envelope held, forbidden paths absent).

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace - trace["runs"] contains exactly
          one run record with a "filesystem" dict (populated by
          evals.runner.invoker for mode="command") and a "worktree_root" path
          under which the scorer shells out to git to read HEAD branch,
          HEAD commit message, diff stats, and loop-state JSON. Aggregation
          across N runs happens in evals.runner.aggregator.

Upstream deps: stdlib json, pathlib, subprocess, re.

Downstream consumers: evals.runner.cli (dynamic import per manifest's
                      scoring_module).

Failure modes: Missing filesystem snapshot or missing worktree_root =>
               status "invalid_format", primary 0.0. Missing `git` binary
               or non-git worktree => defensive zero on branch/commit
               axes. Any axis whose expected-spec field is absent from the
               fixture is treated as vacuously satisfied (credit 1.0).

Performance: standard; a handful of `git` shell-outs per run and a single
             JSON parse of .agentic/loop-state.json.

---

## Scoring formula (v1)

Seven weighted dimensions summing to exactly 1.0, minus a capped extras
penalty. A runtime assertion guards the weight sum (per evals/LEARNINGS.md
rule "scorer weights must sum to 1.0").

    w_branch     = 0.10  (HEAD branch name starts with expected prefix,
                          and is not the fixture's base branch)
    w_edit       = 0.20  (diff from base touched >= one path in
                          must_touch_any_of; vacuous if unset)
    w_loop_state = 0.20  (TIERED: 1.0 full well-formed schema with
                          required fields and enum-valid values;
                          0.5 file exists but wrong shape (missing a
                          required field, or enum value not in spec);
                          0.0 file missing)
    w_commit     = 0.15  (HEAD commit message contains every substring
                          in commit_message_must_contain; vacuous if unset)
    w_quality    = 0.15  (TIERED quality-gate proxy: 1.0 pass artifact
                          present OR a second-pass fix narrative; 0.5
                          fail-acceptable (command acknowledged and
                          attempted one fix pass per Phase 7); 0.0
                          vacuous zero if no gate artifact found and
                          the fixture required one)
    w_scope      = 0.10  (TIERED LOC envelope: 1.0 diff added+removed
                          <= max_loc; 0.5 <= max_loc + grace; 0.0 over)
    w_forbidden  = 0.10  (no forbidden paths created in the diff)

    extras_raw   = 0.10 * any_forbidden_path_present
                 + 0.05 * any_unexpected_tracker_ref
    extras_cap   = 0.15

    primary = clip(sum(w_i * credit_i) - extras_penalty, 0.0, 1.0)

Vacuous-per-axis handling mirrors init_project_lite v3: a fixture that
declares no constraint on, e.g., `must_touch_any_of` credits that axis
1.0 rather than dividing by zero. This prevents unfair zero-outs on
fixtures whose archetype does not exercise a given axis.

Tiered credit shapes (loop_state, quality, scope) follow init_project_lite
v4's "soft quality dimension" pattern: a scaffold near the edge of the
envelope is meaningfully different from one far over, and the scorer
should reflect that rather than floor.

Version history:
  v1: initial seven-dim scorer. Weights sum to 1.0 (runtime assertion).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

SCORER_VERSION = "v1"

_W_BRANCH = 0.10
_W_EDIT = 0.20
_W_LOOP_STATE = 0.20
_W_COMMIT = 0.15
_W_QUALITY = 0.15
_W_SCOPE = 0.10
_W_FORBIDDEN = 0.10

_WEIGHTS_SUM_ASSERTION = abs(
    (_W_BRANCH + _W_EDIT + _W_LOOP_STATE + _W_COMMIT + _W_QUALITY + _W_SCOPE + _W_FORBIDDEN)
    - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "implement_ticket_lite weights must sum to 1.0"

_EXTRAS_CAP = 0.15
_EXTRAS_FORBIDDEN = 0.10
_EXTRAS_TRACKER_REF = 0.05

_SCOPE_GRACE = 20  # LOC grace window above max_loc tier

# Valid enum values the /implement-ticket vocabulary declares. A loop-state
# file with status or termination_reason outside these sets is "exists-wrong".
_LOOP_STATUS_ENUM = {"active", "interrupted", "complete", "stalled"}
_LOOP_TERMINATION_ENUM = {"clean", "cap_reached", "convergence_failure", "blocked", None}
_LOOP_PHASE_ENUM = {"skeptic", "qa"}


def _git(worktree: Path, *args: str) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["git", "-C", str(worktree), *args],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)


def _head_branch(worktree: Path) -> str | None:
    rc, out, _ = _git(worktree, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return None
    name = out.strip()
    if not name or name == "HEAD":
        return None
    return name


def _head_commit_message(worktree: Path) -> str:
    rc, out, _ = _git(worktree, "log", "-1", "--format=%B", "HEAD")
    if rc != 0:
        return ""
    return out


def _diff_name_only(worktree: Path, base_ref: str) -> list[str]:
    # Compare HEAD against the base ref (best-effort; base_ref may be the
    # seed commit created by the prompt's pre-setup). Fall back to HEAD~1
    # if the base ref is unresolvable.
    for ref in (base_ref, "HEAD~1"):
        rc, out, _ = _git(worktree, "diff", "--name-only", f"{ref}..HEAD")
        if rc == 0:
            return [p for p in out.splitlines() if p.strip()]
    return []


def _diff_loc(worktree: Path, base_ref: str) -> int:
    for ref in (base_ref, "HEAD~1"):
        rc, out, _ = _git(worktree, "diff", "--shortstat", f"{ref}..HEAD")
        if rc != 0:
            continue
        m = re.search(r"(\d+)\s+insertion", out)
        ins = int(m.group(1)) if m else 0
        m = re.search(r"(\d+)\s+deletion", out)
        dels = int(m.group(1)) if m else 0
        return ins + dels
    return 0


def _loop_state_credit(worktree_root: Path) -> tuple[float, str, dict]:
    """TIERED credit for .agentic/loop-state.json well-formedness.

    1.0 file exists, valid JSON, required fields present, enum values
        within declared vocabulary.
    0.5 file exists but wrong shape (invalid JSON, missing a required
        field, or enum value outside declared set).
    0.0 file missing entirely.
    """
    path = worktree_root / ".agentic" / "loop-state.json"
    if not path.exists():
        return 0.0, "missing", {"path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return 0.5, "exists-wrong-parse", {"error": str(e)}
    if not isinstance(data, dict):
        return 0.5, "exists-wrong-shape", {"reason": "not a mapping"}
    required_top = {"status", "loop_state"}
    missing_top = required_top - set(data)
    if missing_top:
        return 0.5, "exists-wrong-missing-fields", {"missing": sorted(missing_top)}
    status = data.get("status")
    if status not in _LOOP_STATUS_ENUM:
        return 0.5, "exists-wrong-status-enum", {"status": status}
    ls = data.get("loop_state") or {}
    if not isinstance(ls, dict):
        return 0.5, "exists-wrong-loop-state-shape", {}
    phase = ls.get("phase")
    if phase is not None and phase not in _LOOP_PHASE_ENUM:
        return 0.5, "exists-wrong-phase-enum", {"phase": phase}
    term = ls.get("termination_reason")
    if term not in _LOOP_TERMINATION_ENUM:
        return 0.5, "exists-wrong-termination-enum", {"termination_reason": term}
    return 1.0, "full", {"status": status, "phase": phase, "termination_reason": term}


def _scope_credit(loc: int, max_loc: int) -> tuple[float, str]:
    if loc <= max_loc:
        return 1.0, "under"
    if loc <= max_loc + _SCOPE_GRACE:
        return 0.5, "grace"
    return 0.0, "over"


def _quality_credit(worktree_root: Path, snapshot_keys: set[str], commit_message: str) -> tuple[float, str]:
    """TIERED quality-gate proxy.

    The eval does not run the archetype-specific QUALITY_CMD itself; it
    inspects indirect artifacts the command's Phase 7 produces:

    - If the HEAD commit message mentions "quality" or "lint" or "typecheck"
      or "tests pass" => credit 1.0 (the command acknowledged and documented
      the gate).
    - Else if a .agentic/loop-state.json exists and its termination_reason
      is 'clean' => credit 1.0 (clean exit implies the gate passed).
    - Else if a quality-fix commit exists (two commits since base) with any
      keyword => 0.5 (fail-acceptable: second-pass fix path).
    - Else vacuous zero 0.0.
    """
    msg_l = (commit_message or "").lower()
    if any(k in msg_l for k in ("quality", "lint", "typecheck", "tests pass", "test pass")):
        return 1.0, "pass-artifact-in-commit"
    ls_path = worktree_root / ".agentic" / "loop-state.json"
    if ls_path.exists():
        try:
            data = json.loads(ls_path.read_text(encoding="utf-8"))
            term = (data.get("loop_state") or {}).get("termination_reason")
            if term == "clean":
                return 1.0, "clean-termination"
        except (OSError, json.JSONDecodeError):
            pass
    # Count commits since the seed - > 1 suggests a fix pass happened.
    rc, out, _ = _git(worktree_root, "rev-list", "--count", "HEAD")
    if rc == 0:
        try:
            n = int(out.strip())
        except ValueError:
            n = 0
        if n >= 3:  # seed + impl + fix
            return 0.5, "fail-acceptable-fix-pass"
    return 0.0, "vacuous"


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
        "implement_ticket_lite.score expects a single-run trace; aggregation "
        "across N runs happens in evals.runner.aggregator."
    )
    run = runs[0]
    snapshot = run.get("filesystem")
    if not isinstance(snapshot, dict):
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
    worktree_root_s = run.get("worktree_root")
    if not worktree_root_s:
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
    worktree_root = Path(worktree_root_s)

    expected = fixture.get("expected_outputs") or {}
    base_branch = (fixture.get("inputs") or {}).get("base_branch") or "main"
    branch_prefix = expected.get("branch_prefix") or ""
    must_touch = list(expected.get("must_touch_any_of") or [])
    commit_must_contain = list(expected.get("commit_message_must_contain") or [])
    max_loc = expected.get("max_loc")
    must_not_exist = list(expected.get("must_not_exist") or [])
    loop_state_required = bool(expected.get("loop_state_required", True))
    quality_required = bool(expected.get("quality_required", True))

    # --- Branch axis ---
    head_branch = _head_branch(worktree_root)
    if branch_prefix:
        branch_ok = bool(
            head_branch
            and head_branch != base_branch
            and head_branch.startswith(branch_prefix)
        )
        branch_credit = 1.0 if branch_ok else 0.0
    else:
        # Vacuous - no prefix declared.
        branch_ok = head_branch is not None and head_branch != base_branch
        branch_credit = 1.0 if branch_ok else 0.0

    # --- Edit axis ---
    diff_files = _diff_name_only(worktree_root, base_branch)
    if must_touch:
        edit_hit = any(
            any(f == p or f.startswith(p.rstrip("/") + "/") for p in must_touch)
            for f in diff_files
        )
        edit_credit = 1.0 if edit_hit else 0.0
    else:
        # Vacuous - at least require some change from base.
        edit_credit = 1.0 if diff_files else 0.0

    # --- Loop-state axis ---
    if loop_state_required:
        loop_state_credit_val, loop_state_tier, loop_state_diag = _loop_state_credit(worktree_root)
    else:
        loop_state_credit_val, loop_state_tier, loop_state_diag = 1.0, "vacuous", {}

    # --- Commit axis ---
    head_msg = _head_commit_message(worktree_root)
    if commit_must_contain:
        hits = [s for s in commit_must_contain if s in head_msg]
        commit_credit = len(hits) / max(len(commit_must_contain), 1)
    else:
        commit_credit = 1.0 if head_msg.strip() else 0.0

    # --- Quality axis ---
    if quality_required:
        quality_credit_val, quality_tier = _quality_credit(
            worktree_root, snapshot_keys, head_msg
        )
    else:
        quality_credit_val, quality_tier = 1.0, "vacuous"

    # --- Scope axis ---
    diff_loc = _diff_loc(worktree_root, base_branch)
    if isinstance(max_loc, int) and max_loc > 0:
        scope_credit_val, scope_tier = _scope_credit(diff_loc, max_loc)
    else:
        scope_credit_val, scope_tier = 1.0, "vacuous"

    # --- Forbidden axis ---
    forbidden_hits = [p for p in must_not_exist if p in snapshot_keys]
    forbidden_credit = 0.0 if forbidden_hits else 1.0

    # --- Extras (unexpected tracker references) ---
    tracker_refs_hits = 0
    # Fixture sets TRACKER=none; any "Closes LINEAR-", "Closes JIRA-", or
    # "linear.app" in the commit message is an unexpected reference.
    for pat in (r"\bCloses\s+[A-Z]+-\d+", r"linear\.app", r"atlassian\.net"):
        if re.search(pat, head_msg):
            tracker_refs_hits += 1
            break  # count once
    extras_raw = (
        _EXTRAS_FORBIDDEN * (1 if forbidden_hits else 0)
        + _EXTRAS_TRACKER_REF * tracker_refs_hits
    )
    extras_penalty = min(extras_raw, _EXTRAS_CAP)

    weighted = (
        _W_BRANCH * branch_credit
        + _W_EDIT * edit_credit
        + _W_LOOP_STATE * loop_state_credit_val
        + _W_COMMIT * commit_credit
        + _W_QUALITY * quality_credit_val
        + _W_SCOPE * scope_credit_val
        + _W_FORBIDDEN * forbidden_credit
    )
    primary = max(0.0, min(1.0, weighted - extras_penalty))

    diagnostic: dict[str, Any] = {
        "head_branch": head_branch,
        "branch_credit": branch_credit,
        "diff_files": diff_files,
        "edit_credit": edit_credit,
        "loop_state_credit": loop_state_credit_val,
        "loop_state_tier": loop_state_tier,
        "loop_state_detail": loop_state_diag,
        "commit_msg_preview": head_msg[:200],
        "commit_credit": round(commit_credit, 6),
        "commit_hits": [s for s in commit_must_contain if s in head_msg] if commit_must_contain else [],
        "quality_credit": quality_credit_val,
        "quality_tier": quality_tier,
        "diff_loc": diff_loc,
        "scope_credit": scope_credit_val,
        "scope_tier": scope_tier,
        "forbidden_hits": forbidden_hits,
        "forbidden_credit": forbidden_credit,
        "tracker_refs_hits": tracker_refs_hits,
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
