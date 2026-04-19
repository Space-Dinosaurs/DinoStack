"""
Purpose: Score a single /wrap command-mode run against a labeled fixture by
         walking the worktree's filesystem snapshot, inspecting text-level
         content of context.md / memory.md / findings.md where present,
         inferring which route the command took, and combining six weighted
         dimensions.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace (trace["runs"] has one run
          record). The run record carries a "filesystem" dict (relative
          path -> sha256) populated by evals.runner.invoker in command
          mode, and "worktree_root" so the scorer can read the text of
          context.md / memory.md / .claude/findings.md directly.

Upstream deps: stdlib pathlib.

Downstream consumers: evals.runner.cli (dynamic import per manifest's
                      scoring_module).

Failure modes: missing filesystem snapshot => status "invalid_format",
               primary 0.0. Missing worktree_root => all text-level
               dimensions treated as failures but existence checks still
               run against snapshot keys.

---

wrap_lite v1 scores six dimensions: file presence, context.md structure,
substring fidelity to the session transcript, routing-path correctness
(tiered), forbidden-file absence, and lock-release hygiene. Tiered routing
credit (exact -> 1.0, adjacent -> 0.5, wrong-direction -> 0.0) reflects
that /wrap's three routes (zero-substance, light, standard) form a
conservativeness gradient rather than discrete classes. A fixture that
should have routed light but went standard has over-captured (recoverable
noise), while one that should have routed standard but went zero-substance
has under-captured (silent gap). The shape is defensible independent of
fixture choice.

## Version history

v1 (550218a): initial. Six dimensions, tiered route credit, binary extras.
v2 (this commit): widens `_ALWAYS_OK_EXTRAS` to include Claude Code runtime
    config (`.claude/settings.json`, `.claude/settings.local.json`) and the
    init-project preflight migration artifact (`.claude/tracking.md`).
    Introduces `_STANDARD_ROUTE_SENTINELS` to prevent double-counting
    `.agentic/memory.md` and `.claude/findings.md` as extras on
    standard-route fixtures where their creation IS the route signal.
    Overfitting-Rule rationale: these paths are either produced by the
    harness (not the command) or are already credited by w_route. v1
    penalized runtime noise, not command fidelity.

## Scoring formula (v2)

Weighted sum across six dimensions, minus a capped extras penalty. Weights
sum to exactly 1.0 (runtime assertion).

    w_files      = 0.25   (must_exist presence; vacuous when must_exist == [])
    w_sections   = 0.15   (context.md required-section prefixes; vacuous if
                           context.md not in must_exist)
    w_substrings = 0.20   (required substrings per file + negative substring
                           checks; each negative hit counts as a miss;
                           vacuous if no substrings specified)
    w_route      = 0.15   (exact -> 1.0, adjacent -> 0.5, wrong-direction
                           -> 0.0; never vacuous)
    w_forbidden  = 0.15   (binary; 1.0 if no forbidden paths present,
                           0.0 otherwise; vacuous when must_not_exist == [])
    w_lock       = 0.10   (1.0 if .agentic/wrap.lock is absent, else 0.0;
                           never vacuous)

Route adjacency: {zero-substance, light} adjacent;
                 {light, standard} adjacent;
                 {zero-substance, standard} wrong-direction.

Route inference (post-run):
  - findings.md OR memory.md newly-written -> standard
  - context.md only newly-written          -> light
  - no new writes to any of the three      -> zero-substance

Extras penalty: for each file under .agentic/ or .claude/ that is NOT in
must_exist and NOT in the always-ok set, add 0.1; cap at 0.15.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

SCORER_VERSION = "v2"

_W_FILES = 0.25
_W_SECTIONS = 0.15
_W_SUBSTRINGS = 0.20
_W_ROUTE = 0.15
_W_FORBIDDEN = 0.15
_W_LOCK = 0.10

_WEIGHTS_SUM_ASSERTION = abs(
    (_W_FILES + _W_SECTIONS + _W_SUBSTRINGS + _W_ROUTE + _W_FORBIDDEN + _W_LOCK) - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "wrap_lite weights must sum to 1.0"

_EXTRAS_CAP = 0.15
_EXTRAS_PER_HIT = 0.1

_ROUTES = {"zero-substance", "light", "standard"}
# Adjacency map. Keys are the expected route; values are the credit for
# observing a given actual route.
_ROUTE_CREDIT = {
    "zero-substance": {"zero-substance": 1.0, "light": 0.5, "standard": 0.0},
    "light": {"zero-substance": 0.5, "light": 1.0, "standard": 0.5},
    "standard": {"zero-substance": 0.0, "light": 0.5, "standard": 1.0},
}

_LOCK_PATH = ".agentic/wrap.lock"
_CONTEXT_PATH = ".agentic/context.md"
_MEMORY_PATH = ".agentic/memory.md"
_FINDINGS_PATH = ".agentic/findings.md"

# Fixture authors use bare filenames as keys in expected_substrings
# (e.g. "context.md", "memory.md", "findings.md"). Resolve those to the
# canonical on-disk paths written by /wrap. A key that already contains
# "/" is treated as literal.
_SHORTNAME_MAP = {
    "context.md": _CONTEXT_PATH,
    "memory.md": _MEMORY_PATH,
    "findings.md": _FINDINGS_PATH,
}


def _resolve_path(key: str) -> str:
    if "/" in key:
        return key
    return _SHORTNAME_MAP.get(key, key)

# Paths that are expected infrastructure in a /wrap-run worktree and should
# NOT count as "extras" even if not listed in must_exist.
#
# Rationale per Phase 5 baseline (v1 first-run finding): wr-002 and wr-004
# scored 0.85 entirely on the extras axis because the /wrap run produced
# Claude Code runtime config files and a preflight-migration-scaffolded
# tracking.md that no fixture's must_exist listed. These are not /wrap
# outputs and penalizing them measures runtime noise, not command fidelity.
_ALWAYS_OK_EXTRAS = {
    ".agentic/session-transcript.md",  # fixture seed, not a /wrap output
    ".claude/settings.json",           # Claude Code runtime config
    ".claude/settings.local.json",     # Claude Code runtime config
    ".agentic/tracking.md",            # init-project preflight migration artifact (post-migration path)
    ".claude/tracking.md",             # legacy init-project preflight migration artifact (back-compat window)
}

# Files that /wrap's standard route legitimately produces as the route's
# own signal. When route_expected == "standard", these files appearing is
# evidence of correct behavior (already credited by w_route) and must not
# double-count as extras. On light or zero-substance fixtures, their
# appearance remains a real over-capture signal and does count.
_STANDARD_ROUTE_SENTINELS = {
    ".agentic/memory.md",
    ".agentic/findings.md",
}


def _infer_route(snapshot_keys: set[str], seed_keys: set[str]) -> str:
    """Infer which route /wrap took from post-run filesystem state.

    A file counts as "newly written" if it is present in the post-run
    snapshot and was NOT in the seed. /wrap may rewrite a seeded
    findings.md (wr-002, wr-004) - in that case the file was already in
    seed_keys and is not classified as a new write by this inference. That
    is acceptable: route inference is a behavioural signal, and seeded
    findings.md that /wrap touches still trips the route-standard signal
    through memory.md or additional writes.
    """
    def newly(path: str) -> bool:
        return path in snapshot_keys and path not in seed_keys

    newly_memory = newly(_MEMORY_PATH)
    newly_findings = newly(_FINDINGS_PATH)
    newly_context = newly(_CONTEXT_PATH)
    if newly_memory or newly_findings:
        return "standard"
    if newly_context:
        return "light"
    return "zero-substance"


def _read_text(worktree_root: str | None, rel_path: str) -> str:
    if not worktree_root:
        return ""
    p = Path(worktree_root) / rel_path
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _collect_seed_keys(fixture: dict) -> set[str]:
    """Best-effort reconstruction of which files were in the fixture seed.

    Used only for route inference. Reads from the fixture's declared
    repo_dir if still available on disk (fixture.raw carries the path at
    labeling time). We do not fail if missing - an empty seed set just
    means every post-run file counts as "newly written", which is the
    zero-substance-friendly default.
    """
    # The caller passes us fixture.raw; the fixture's repo_dir is relative
    # to the fixture.yaml directory, which we cannot recover from raw
    # alone. So we conservatively treat the seed as containing the three
    # /wrap-written paths if the fixture listed them in must_exist. That
    # yields correct inference for wr-001 (only context.md expected), wr-
    # 002/wr-004 (findings.md seeded, will still be seen as seeded), and
    # wr-005 (none expected).
    #
    # Trade-off acknowledged: this is a heuristic that can in principle
    # misclassify a run where /wrap rewrites a seeded file. In practice,
    # wr-002 / wr-004 expect findings.md in must_exist AND have it in the
    # seed; since the file IS present in the post-run snapshot either way,
    # route inference falls through to checking memory.md and context.md,
    # which are the stronger standard-path signals.
    expected = fixture.get("expected_outputs") or {}
    must_exist = set(expected.get("must_exist") or [])
    # Heuristic seed: the fixture's repo-seed state is whatever is marked
    # must_exist MINUS the three files /wrap can write. We include the
    # seeded findings.md as a seed key so it doesn't spuriously count as
    # "newly written" when /wrap merely merges into it.
    seeded_wrap_outputs: set[str] = set()
    # wr-002 / wr-004 seed findings.md:
    if _FINDINGS_PATH in must_exist:
        # Heuristic: assume seeded iff context.md not in must_exist (i.e.
        # not a single-file-wrap). wr-002 and wr-004 both have context.md
        # AND findings.md in must_exist, so this would be wrong. Instead,
        # treat findings.md as seeded for any fixture where route_expected
        # is "standard" AND findings.md is in must_exist - the standard
        # path is the only one where an existing findings.md makes sense
        # as context.
        if expected.get("route_expected") == "standard":
            seeded_wrap_outputs.add(_FINDINGS_PATH)
    return seeded_wrap_outputs


def _score_substrings(
    expected_substrings: dict[str, list[str]],
    forbidden_per_file: dict[str, list[str]],
    context_forbidden: list[str],
    worktree_root: str | None,
) -> tuple[float, dict[str, Any]]:
    """Score required + negative substring checks across files.

    Each required substring that IS present -> 1 hit. Each required
    substring that is NOT present -> 1 miss. Each negative substring that
    IS present -> 1 miss (same weight as a missed required substring).
    Each negative that is NOT present -> 1 hit.

    If there are no substring checks at all (neither required nor negative
    nor forbidden_per_file), the dimension is vacuously satisfied.
    """
    hits = 0
    misses = 0
    detail: dict[str, Any] = {"required": {}, "negative": []}
    for rel, needles in (expected_substrings or {}).items():
        resolved = _resolve_path(rel)
        text = _read_text(worktree_root, resolved)
        file_detail = {"present": [], "missing": [], "resolved_path": resolved}
        for n in needles or []:
            if n in text:
                hits += 1
                file_detail["present"].append(n)
            else:
                misses += 1
                file_detail["missing"].append(n)
        detail["required"][rel] = file_detail
    for rel, needles in (forbidden_per_file or {}).items():
        resolved = _resolve_path(rel)
        text = _read_text(worktree_root, resolved)
        for n in needles or []:
            if n in text:
                misses += 1
                detail["negative"].append({"file": rel, "needle": n, "hit": True})
            else:
                hits += 1
                detail["negative"].append({"file": rel, "needle": n, "hit": False})
    context_text = _read_text(worktree_root, _CONTEXT_PATH)
    # context_md_forbidden_substrings applies to the Recent Focus section
    # specifically. If context.md does not yet have a Recent Focus marker
    # we apply the check to the whole file - a file that never wrote the
    # section cannot hide a forbidden substring in it.
    haystack = context_text
    if "## Recent Focus" in context_text:
        start = context_text.index("## Recent Focus")
        # Slice to the next ## heading if any.
        rest = context_text[start + len("## Recent Focus"):]
        next_h = rest.find("\n## ")
        haystack = rest if next_h == -1 else rest[:next_h]
    for n in context_forbidden or []:
        if n.lower() in haystack.lower():
            misses += 1
            detail["negative"].append(
                {"file": _CONTEXT_PATH + "#RecentFocus", "needle": n, "hit": True}
            )
        else:
            hits += 1
            detail["negative"].append(
                {"file": _CONTEXT_PATH + "#RecentFocus", "needle": n, "hit": False}
            )
    total = hits + misses
    if total == 0:
        return (1.0, {"vacuous": True, "hits": 0, "misses": 0, **detail})
    return (hits / total, {"vacuous": False, "hits": hits, "misses": misses, **detail})


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
    snapshot_keys = set(snapshot.keys())
    worktree_root = run.get("worktree_root")

    expected = fixture.get("expected_outputs") or {}
    must_exist = list(expected.get("must_exist") or [])
    must_not_exist = list(expected.get("must_not_exist") or [])
    required_sections = list(expected.get("context_md_required_sections") or [])
    expected_substrings = expected.get("expected_substrings") or {}
    forbidden_substrings_per_file = expected.get("forbidden_substrings") or {}
    context_forbidden = list(expected.get("context_md_forbidden_substrings") or [])
    route_expected = expected.get("route_expected")

    # --- w_files ---
    if not must_exist:
        files_credit = 1.0
        files_detail: dict[str, Any] = {"vacuous": True, "present": 0, "total": 0, "missing": []}
    else:
        present = 0
        missing: list[str] = []
        for p in must_exist:
            if p in snapshot_keys:
                present += 1
            else:
                missing.append(p)
        files_credit = present / len(must_exist)
        files_detail = {
            "vacuous": False,
            "present": present,
            "total": len(must_exist),
            "missing": missing,
        }

    # --- w_sections ---
    if _CONTEXT_PATH not in must_exist:
        sections_credit = 1.0
        sections_detail: dict[str, Any] = {"vacuous": True, "hits": 0, "total": 0}
    else:
        context_text = _read_text(worktree_root, _CONTEXT_PATH)
        context_lines = context_text.splitlines()
        hits = 0
        for req in required_sections:
            if any(line.startswith(req) for line in context_lines):
                hits += 1
        total = max(len(required_sections), 1)
        sections_credit = hits / total if required_sections else 1.0
        sections_detail = {
            "vacuous": False,
            "hits": hits,
            "total": len(required_sections),
        }

    # --- w_substrings ---
    substrings_credit, substrings_detail = _score_substrings(
        expected_substrings,
        forbidden_substrings_per_file,
        context_forbidden,
        worktree_root,
    )

    # --- w_route ---
    seed_keys = _collect_seed_keys(fixture)
    observed_route = _infer_route(snapshot_keys, seed_keys)
    if route_expected in _ROUTE_CREDIT:
        route_credit = _ROUTE_CREDIT[route_expected].get(observed_route, 0.0)
    else:
        route_credit = 0.0
    route_detail = {
        "expected": route_expected,
        "observed": observed_route,
        "credit": route_credit,
    }

    # --- w_forbidden ---
    if not must_not_exist:
        forbidden_credit = 1.0
        forbidden_detail: dict[str, Any] = {"vacuous": True, "hits": []}
    else:
        hits_list = [p for p in must_not_exist if p in snapshot_keys]
        forbidden_credit = 1.0 if not hits_list else 0.0
        forbidden_detail = {"vacuous": False, "hits": hits_list}

    # --- w_lock ---
    # Lock detection: a lock dir is present if any path starts with
    # ".agentic/wrap.lock/" OR the bare path ".agentic/wrap.lock" is in
    # the snapshot. /wrap.lock is a directory in production; the snapshot
    # only records files inside it.
    lock_present = _LOCK_PATH in snapshot_keys or any(
        k.startswith(_LOCK_PATH + "/") for k in snapshot_keys
    )
    lock_credit = 0.0 if lock_present else 1.0
    lock_detail = {"lock_present": lock_present}

    # --- extras penalty ---
    accounted: set[str] = set(must_exist) | set(_ALWAYS_OK_EXTRAS)
    if route_expected == "standard":
        accounted |= _STANDARD_ROUTE_SENTINELS
    extras_hits: list[str] = []
    for k in snapshot_keys:
        if not (k.startswith(".agentic/") or k.startswith(".claude/")):
            continue
        if k in accounted:
            continue
        if k.startswith(_LOCK_PATH):
            # Lock presence is penalized by w_lock, not by extras.
            continue
        extras_hits.append(k)
    extras_raw = _EXTRAS_PER_HIT * len(extras_hits)
    extras_penalty = min(extras_raw, _EXTRAS_CAP)

    primary_raw = (
        _W_FILES * files_credit
        + _W_SECTIONS * sections_credit
        + _W_SUBSTRINGS * substrings_credit
        + _W_ROUTE * route_credit
        + _W_FORBIDDEN * forbidden_credit
        + _W_LOCK * lock_credit
        - extras_penalty
    )
    primary = max(0.0, min(1.0, primary_raw))

    diagnostic: dict[str, Any] = {
        "files": files_detail,
        "sections": sections_detail,
        "substrings": substrings_detail,
        "route": route_detail,
        "forbidden": forbidden_detail,
        "lock": lock_detail,
        "extras_hits": extras_hits,
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
