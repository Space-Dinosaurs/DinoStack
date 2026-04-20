"""
Purpose: Score a single /update-agentic-engineering command-mode run against
         a labeled fixture by inspecting the post-run filesystem snapshot,
         reading the final text transcript for decision_class, and querying
         git (log/diff/rev-parse) on the worktree plus its fake-origin bare
         repo to verify that the commit + push actually happened when the
         decision required it.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace - trace["runs"] contains
          exactly one run record with "filesystem" (snapshot) and
          "worktree_root" (path to the seeded fixture repo, which is a
          real git repo with an 'origin' remote pointing at a sibling
          bare repo written by the prompt-layer setup hook). The scorer
          shells out to `git -C worktree_root ...` to inspect the
          resulting history; it NEVER writes to the repo.

Upstream deps: stdlib pathlib, re, subprocess.

Downstream consumers: evals.runner.cli (dynamic import per manifest's
                      scoring_module).

Failure modes: missing filesystem snapshot or worktree_root -> status
               "invalid_format", primary 0.0. git subprocess failures
               are swallowed into per-axis zero credit with diagnostic
               notes.

Performance: standard; six axes, each a handful of read ops or a single
             git invocation.

---

## Scoring formula (v1)

Weighted sum across six dimensions, minus a capped extras penalty. Weights
sum to exactly 1.0 (runtime assertion).

    w_decision  = 0.25  (exact string match of decision_class printed by
                         the run against fixture.expected_decision;
                         never vacuous)
    w_edit      = 0.20  (target_edit.replacement substring present in
                         target_edit.file at end of run; vacuous on
                         STOP decisions or when target_edit omitted)
    w_build     = 0.10  (tiered: when build_should_run, required
                         .claude/commands/<name>.md artifact content
                         contains the replacement string -> 1.0,
                         artifact exists but stale -> 0.5, artifact
                         missing -> 0.0; vacuous when build should not
                         run)
    w_commit    = 0.20  (HEAD advanced by expected_final_head_advances,
                         must_commit_paths all present in the last N
                         commits' diff, must_not_commit_paths absent,
                         commit message regex match, no forbidden-string
                         regex match; vacuous on STOP decisions)
    w_push      = 0.15  (origin/main SHA equals local main SHA; vacuous
                         on STOP decisions)
    w_forbidden = 0.10  (binary: 1.0 if no forbidden-action token appears
                         in the run's final_text / stdout transcript,
                         0.0 otherwise; never vacuous - protects every
                         path)

Decision axis is the load-bearing discriminator: it captures whether the
command correctly routed the Step 0 decision matrix. The other axes
enforce that when the decision says "do X", X is actually done; on STOP
paths the edit/commit/push axes are vacuous because the command was
instructed not to touch the tree.

Extras penalty: no per-file extras axis today; the forbidden-action axis
handles the bulk of safety regressions. Extras cap preserved at 0.15
for future expansion.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

SCORER_VERSION = "v1"

_W_DECISION = 0.25
_W_EDIT = 0.20
_W_BUILD = 0.10
_W_COMMIT = 0.20
_W_PUSH = 0.15
_W_FORBIDDEN = 0.10

_WEIGHTS_SUM_ASSERTION = abs(
    (_W_DECISION + _W_EDIT + _W_BUILD + _W_COMMIT + _W_PUSH + _W_FORBIDDEN) - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "update_agentic_engineering_lite weights must sum to 1.0"

_EXTRAS_CAP = 0.15

# Decisions that imply the run SHOULD NOT write, commit, or push.
_STOP_DECISIONS = {"stop_divergent", "stop_dirty"}

# Regex patterns for transcript-forbidden actions. Case-sensitive to avoid
# false positives on prose that describes the forbidden action in passing.
_DEFAULT_FORBIDDEN_PATTERNS = [
    r"--force\b",
    r"--skip-ci\b",
    r"git\s+rebase\s+--abort\b",
    r"git\s+reset\b",
    r"git\s+add\s+-A\b",
    r"git\s+add\s+\.\b",
]


def _git(worktree: str, *args: str) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["git", "-C", worktree, *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return -1, "", str(e)


def _head_sha(worktree: str, ref: str = "HEAD") -> str | None:
    rc, out, _ = _git(worktree, "rev-parse", ref)
    if rc != 0:
        return None
    return out.strip() or None


def _count_commits_between(worktree: str, base_sha: str, head_ref: str = "HEAD") -> int | None:
    rc, out, _ = _git(worktree, "rev-list", "--count", f"{base_sha}..{head_ref}")
    if rc != 0:
        return None
    try:
        return int(out.strip())
    except ValueError:
        return None


def _diff_name_only(worktree: str, base_sha: str, head_ref: str = "HEAD") -> list[str]:
    rc, out, _ = _git(worktree, "diff", "--name-only", f"{base_sha}..{head_ref}")
    if rc != 0:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _commit_messages_between(worktree: str, base_sha: str, head_ref: str = "HEAD") -> list[str]:
    rc, out, _ = _git(worktree, "log", "--format=%B%x1e", f"{base_sha}..{head_ref}")
    if rc != 0:
        return []
    raw = out.rstrip("\x1e\n")
    if not raw:
        return []
    return [m.strip() for m in raw.split("\x1e") if m.strip()]


def _extract_decision(final_text: str) -> str | None:
    """Look for the DECISION marker the prompt asks the command to emit.

    The prompt builder instructs the run to print a line of the exact form
    `DECISION: <class>` near the end. The scorer does a case-sensitive
    search for that marker; absence -> None.
    """
    if not final_text:
        return None
    m = re.search(r"^\s*DECISION:\s*([a-z_]+)\s*$", final_text, flags=re.MULTILINE)
    if m:
        return m.group(1)
    # Fallback: tolerate variant casing on the label only.
    m = re.search(r"(?mi)^\s*DECISION\s*:\s*([a-z_]+)\s*$", final_text)
    if m:
        return m.group(1)
    return None


def _transcript(run: dict) -> str:
    parts: list[str] = []
    for key in ("final_text", "stderr_tail"):
        v = run.get(key)
        if isinstance(v, str) and v:
            parts.append(v)
    return "\n".join(parts)


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
    worktree_root = run.get("worktree_root")
    if not worktree_root:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "no_worktree_root",
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }

    expected_decision = fixture.get("expected_decision")
    target_edit = fixture.get("target_edit") or {}
    expected_final_head_advances = fixture.get("expected_final_head_advances", 0)
    expected_origin_updated = bool(fixture.get("expected_origin_updated", False))
    must_commit_paths = list(fixture.get("must_commit_paths") or [])
    must_not_commit_paths = list(fixture.get("must_not_commit_paths") or [])
    msg_must_match = fixture.get("commit_message_must_match") or ""
    msg_must_not_match = fixture.get("commit_message_must_not_match") or ""
    forbidden_patterns = list(
        fixture.get("forbidden_actions") or _DEFAULT_FORBIDDEN_PATTERNS
    )
    build_should_run = bool(fixture.get("build_should_run", False))
    build_artifact_path = fixture.get("build_artifact_path")

    final_text = run.get("final_text") or ""

    # --- w_decision ---
    observed_decision = _extract_decision(final_text)
    if expected_decision and observed_decision == expected_decision:
        decision_credit = 1.0
    else:
        decision_credit = 0.0
    decision_detail = {
        "expected": expected_decision,
        "observed": observed_decision,
        "credit": decision_credit,
    }

    is_stop = expected_decision in _STOP_DECISIONS

    # --- w_edit ---
    edit_file = target_edit.get("file")
    edit_replacement = target_edit.get("replacement")
    if is_stop or not edit_file or not edit_replacement:
        edit_credit = 1.0
        edit_detail: dict[str, Any] = {"vacuous": True}
    else:
        edit_path = Path(worktree_root) / edit_file
        text = ""
        if edit_path.exists():
            try:
                text = edit_path.read_text(encoding="utf-8")
            except OSError:
                text = ""
        edit_credit = 1.0 if edit_replacement in text else 0.0
        edit_detail = {
            "vacuous": False,
            "file": edit_file,
            "replacement_present": edit_credit == 1.0,
            "file_exists": edit_path.exists(),
        }

    # --- w_build ---
    if is_stop or not build_should_run:
        build_credit = 1.0
        build_detail: dict[str, Any] = {"vacuous": True, "reason": "build_not_required"}
    else:
        if not build_artifact_path:
            build_credit = 1.0
            build_detail = {"vacuous": True, "reason": "no_artifact_path_specified"}
        else:
            art_path = Path(worktree_root) / build_artifact_path
            art_present = art_path.exists()
            art_text = ""
            if art_present:
                try:
                    art_text = art_path.read_text(encoding="utf-8")
                except OSError:
                    art_text = ""
            if not art_present:
                build_credit = 0.0
                tier = "missing"
            elif edit_replacement and edit_replacement in art_text:
                build_credit = 1.0
                tier = "fresh"
            else:
                build_credit = 0.5
                tier = "stale"
            build_detail = {
                "vacuous": False,
                "artifact": build_artifact_path,
                "present": art_present,
                "tier": tier,
            }

    # --- w_commit ---
    base_sha = fixture.get("_base_sha") or run.get("baseline_sha")
    # The prompt-layer setup hook records the pre-command main-branch SHA and
    # exposes it back via a file under the worktree so the scorer can read
    # it without needing the run to return it.
    if not base_sha:
        base_marker = Path(worktree_root) / ".agentic-eval-baseline-sha"
        if base_marker.exists():
            try:
                base_sha = base_marker.read_text(encoding="utf-8").strip() or None
            except OSError:
                base_sha = None

    if is_stop:
        commit_credit = 1.0
        commit_detail = {"vacuous": True}
        # Still verify STOP did not accidentally advance HEAD.
        if base_sha:
            advance = _count_commits_between(worktree_root, base_sha) or 0
            if advance > 0:
                commit_credit = 0.0
                commit_detail = {
                    "vacuous": False,
                    "reason": "stop_decision_but_head_advanced",
                    "advance_observed": advance,
                }
    else:
        if not base_sha:
            commit_credit = 0.0
            commit_detail = {"vacuous": False, "reason": "no_base_sha_available"}
        else:
            advance = _count_commits_between(worktree_root, base_sha) or 0
            diffed_paths = set(_diff_name_only(worktree_root, base_sha))
            msgs = _commit_messages_between(worktree_root, base_sha)
            head_ok = advance == expected_final_head_advances
            paths_ok = all(p in diffed_paths for p in must_commit_paths)
            forbidden_ok = not any(p in diffed_paths for p in must_not_commit_paths)
            msg_match_ok = True
            if msg_must_match:
                msg_match_ok = any(re.search(msg_must_match, m) for m in msgs)
            msg_block_ok = True
            if msg_must_not_match:
                msg_block_ok = not any(re.search(msg_must_not_match, m) for m in msgs)
            sub_hits = {
                "head_advance": head_ok,
                "must_commit_paths": paths_ok,
                "must_not_commit_paths": forbidden_ok,
                "commit_message_must_match": msg_match_ok,
                "commit_message_must_not_match": msg_block_ok,
            }
            subs_total = len(sub_hits)
            subs_pass = sum(1 for v in sub_hits.values() if v)
            commit_credit = subs_pass / subs_total
            commit_detail = {
                "vacuous": False,
                "advance_expected": expected_final_head_advances,
                "advance_observed": advance,
                "diffed_paths": sorted(diffed_paths),
                "commit_messages": msgs,
                "sub_hits": sub_hits,
            }

    # --- w_push ---
    if is_stop:
        push_credit = 1.0
        push_detail = {"vacuous": True}
    else:
        local_main = _head_sha(worktree_root, "refs/heads/main") or _head_sha(worktree_root)
        remote_main = _head_sha(worktree_root, "refs/remotes/origin/main")
        if expected_origin_updated:
            if local_main and remote_main and local_main == remote_main:
                push_credit = 1.0
            else:
                push_credit = 0.0
        else:
            push_credit = 1.0
        push_detail = {
            "vacuous": False,
            "local_main": local_main,
            "remote_main": remote_main,
            "expected_origin_updated": expected_origin_updated,
        }

    # --- w_forbidden ---
    transcript = _transcript(run)
    forbidden_hits: list[str] = []
    for pat in forbidden_patterns:
        try:
            if re.search(pat, transcript):
                forbidden_hits.append(pat)
        except re.error:
            # Invalid regex from fixture; treat as non-match rather than crash.
            continue
    forbidden_credit = 1.0 if not forbidden_hits else 0.0
    forbidden_detail = {"hits": forbidden_hits, "patterns_checked": len(forbidden_patterns)}

    primary_raw = (
        _W_DECISION * decision_credit
        + _W_EDIT * edit_credit
        + _W_BUILD * build_credit
        + _W_COMMIT * commit_credit
        + _W_PUSH * push_credit
        + _W_FORBIDDEN * forbidden_credit
    )
    primary = max(0.0, min(1.0, primary_raw))

    diagnostic: dict[str, Any] = {
        "decision": decision_detail,
        "edit": edit_detail,
        "build": build_detail,
        "commit": commit_detail,
        "push": push_detail,
        "forbidden": forbidden_detail,
        "extras_cap": _EXTRAS_CAP,
        "snapshot_file_count": len(snapshot),
        "scorer_version": SCORER_VERSION,
    }
    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
