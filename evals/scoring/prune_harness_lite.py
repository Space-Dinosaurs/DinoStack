"""
Purpose: Score a single /prune-harness command-mode run against a labeled
         fixture. Measures Step 1 analyst spawn + Step 2 proposal artifact.
         Step 0 git-sync is skipped by the prompt. Step 4 dispatch to
         /update-agentic-engineering is OUT OF SCOPE for this eval.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace (trace["runs"] has one run
          record). The run record carries a "filesystem" dict (relative
          path -> sha256) populated by evals.runner.invoker in command
          mode, and "worktree_root" so the scorer can read the proposal
          markdown directly to inspect structure and candidate content.

Upstream deps: stdlib pathlib, re.

Downstream consumers: evals.runner.cli (dynamic import per manifest's
                      scoring_module).

Failure modes: missing filesystem snapshot => status "invalid_format",
               primary 0.0. Missing proposal file => presence axis 0.0,
               structure/recall/discipline axes cascade vacuous or 0.0.

---

## Scoring formula (v1)

Weighted sum across six dimensions minus a capped extras penalty. Weights
sum to exactly 1.0 (runtime assertion).

    w_proposal_exists   = 0.15   proposal file exists at the expected path
                                 under docs/planning/
    w_structure         = 0.15   four required section headings present in
                                 the proposal (## Signal summary, ## Deletion
                                 candidates, ## Recommended action sequence,
                                 plus the top-level # Harness Pruning
                                 Proposal title)
    w_tp_recall         = 0.25   fraction of expected true-positive
                                 candidates recalled. Confidence tier
                                 contributes half credit when the emitted
                                 tier is adjacent (HIGH vs MEDIUM or MEDIUM
                                 vs LOW) to the expected tier. Exact-tier
                                 match + matching file is full credit.
                                 Vacuous (1.0) when expected_true_positives
                                 is empty.
    w_fp_discipline     = 0.15   tiered: 0 FPs -> 1.0; 1 FP -> 0.5; 2+ -> 0.0.
                                 A FP is any candidate in the proposal that
                                 does not match an expected TP by file-path
                                 and is not explicitly expected as a
                                 near-miss allowance.
    w_signal_discipline = 0.15   the set of signals the analyst declared
                                 skipped must equal expected_signal_skips
                                 exactly (checked by substring match in the
                                 Signal summary section). Vacuous (1.0)
                                 when expected_signal_skips is empty AND
                                 the proposal does not declare any skip.
    w_forbidden_writes  = 0.15   binary; 1.0 if no content/** file was
                                 mutated relative to the fixture seed, 0.0
                                 if any content/** hash changed.

    extras_penalty = 0.1 * N_unexpected_docs_planning_files, capped at 0.15.
                     Files other than the expected proposal written into
                     docs/planning/ count as extras.

Confidence-tier adjacency:
    HIGH <-> MEDIUM (half credit)
    MEDIUM <-> LOW  (half credit)
    HIGH <-> LOW    (zero credit)
    exact match     (full credit)

Vacuous-dimension doctrine (per evals/LEARNINGS.md): every axis that lacks
applicable fixture content scores 1.0, not 0.0. This prevents fixtures
that legitimately have no TPs or no signal skips from being silently
floored.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SCORER_VERSION = "v1"

_W_PROPOSAL_EXISTS = 0.15
_W_STRUCTURE = 0.15
_W_TP_RECALL = 0.25
_W_FP_DISCIPLINE = 0.15
_W_SIGNAL_DISCIPLINE = 0.15
_W_FORBIDDEN_WRITES = 0.15

_WEIGHTS_SUM_ASSERTION = abs(
    (
        _W_PROPOSAL_EXISTS
        + _W_STRUCTURE
        + _W_TP_RECALL
        + _W_FP_DISCIPLINE
        + _W_SIGNAL_DISCIPLINE
        + _W_FORBIDDEN_WRITES
    )
    - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "prune_harness_lite weights must sum to 1.0"

_EXTRAS_CAP = 0.15
_EXTRAS_PER_HIT = 0.1

_REQUIRED_SECTIONS = [
    "# Harness Pruning Proposal",
    "## Signal summary",
    "## Deletion candidates",
    "## Recommended action sequence",
]

_CONFIDENCE_TIERS = ("HIGH", "MEDIUM", "LOW")
_ADJACENCY = {
    ("HIGH", "HIGH"): 1.0,
    ("MEDIUM", "MEDIUM"): 1.0,
    ("LOW", "LOW"): 1.0,
    ("HIGH", "MEDIUM"): 0.5,
    ("MEDIUM", "HIGH"): 0.5,
    ("MEDIUM", "LOW"): 0.5,
    ("LOW", "MEDIUM"): 0.5,
    ("HIGH", "LOW"): 0.0,
    ("LOW", "HIGH"): 0.0,
}


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


def _parse_candidates(proposal_text: str) -> list[dict]:
    """Extract candidate records from the Deletion candidates section.

    A candidate block starts with '### <title>' under '## Deletion
    candidates' and ends at the next '### ' or '## ' heading. The parser
    pulls out the Confidence tier and File path fields by regex.
    """
    candidates: list[dict] = []
    # Slice the section between '## Deletion candidates' and the next '## '
    # heading.
    start_re = re.search(r"^## Deletion candidates\s*$", proposal_text, re.MULTILINE)
    if not start_re:
        return candidates
    rest = proposal_text[start_re.end():]
    end_re = re.search(r"^## ", rest, re.MULTILINE)
    section = rest if not end_re else rest[: end_re.start()]
    # Split on ### headings.
    block_re = re.compile(r"^### (.+?)$", re.MULTILINE)
    matches = list(block_re.finditer(section))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
        body = section[body_start:body_end]
        conf_m = re.search(r"Confidence\s*[:\-]\s*(HIGH|MEDIUM|LOW)", body, re.IGNORECASE)
        file_m = re.search(r"File\s*[:\-]\s*([^\s\n]+)", body)
        confidence = conf_m.group(1).upper() if conf_m else None
        file_path = file_m.group(1).strip().rstrip(",.;") if file_m else None
        candidates.append(
            {
                "title": title,
                "confidence": confidence,
                "file": file_path,
                "body": body.strip(),
            }
        )
    return candidates


def _signal_summary_text(proposal_text: str) -> str:
    start_re = re.search(r"^## Signal summary\s*$", proposal_text, re.MULTILINE)
    if not start_re:
        return ""
    rest = proposal_text[start_re.end():]
    end_re = re.search(r"^## ", rest, re.MULTILINE)
    return rest if not end_re else rest[: end_re.start()]


def _declared_signal_skips(summary_text: str) -> set[int]:
    """Extract the set of signal numbers the analyst declared skipped.

    Looks for text like 'Signal 4 skipped' or 'Signals skipped: 4' in the
    Signal summary block. Returns the set of declared skip numbers.
    """
    skips: set[int] = set()
    for m in re.finditer(r"Signal\s+(\d+)\s+(?:skipped|SKIPPED)", summary_text):
        skips.add(int(m.group(1)))
    # Also accept 'Signals skipped: 4, 7' style.
    list_m = re.search(r"Signals skipped[:\-]\s*([0-9,\s]+)", summary_text, re.IGNORECASE)
    if list_m:
        for tok in re.findall(r"\d+", list_m.group(1)):
            skips.add(int(tok))
    return skips


def _fp_credit(fp_count: int) -> float:
    if fp_count <= 0:
        return 1.0
    if fp_count == 1:
        return 0.5
    return 0.0


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

    # fixture is the raw YAML dict (runner passes fixture.raw to score()).
    expected = fixture.get("expected") or {}
    proposal_path = expected.get("proposal_path") or ""
    expected_tps: list[dict] = list(expected.get("expected_true_positives") or [])
    expected_skips: set[int] = set(int(x) for x in (expected.get("expected_signal_skips") or []))
    seed_content_hashes: dict[str, str] = dict(expected.get("seed_content_hashes") or {})

    # --- w_proposal_exists ---
    proposal_exists = bool(proposal_path) and proposal_path in snapshot_keys
    proposal_credit = 1.0 if proposal_exists else 0.0

    # Load proposal text once.
    proposal_text = _read_text(worktree_root, proposal_path) if proposal_exists else ""

    # --- w_structure ---
    if not proposal_exists:
        structure_credit = 0.0
        structure_detail: dict[str, Any] = {
            "vacuous": False,
            "hits": 0,
            "total": len(_REQUIRED_SECTIONS),
            "missing": list(_REQUIRED_SECTIONS),
        }
    else:
        lines = proposal_text.splitlines()
        hits = 0
        missing: list[str] = []
        for req in _REQUIRED_SECTIONS:
            if any(line.strip() == req or line.startswith(req) for line in lines):
                hits += 1
            else:
                missing.append(req)
        structure_credit = hits / len(_REQUIRED_SECTIONS)
        structure_detail = {
            "vacuous": False,
            "hits": hits,
            "total": len(_REQUIRED_SECTIONS),
            "missing": missing,
        }

    # --- parse candidates (shared by recall + fp) ---
    candidates = _parse_candidates(proposal_text) if proposal_exists else []

    # --- w_tp_recall ---
    if not expected_tps:
        tp_recall_credit = 1.0
        tp_detail: dict[str, Any] = {"vacuous": True, "matched": [], "total": 0}
    else:
        matched = []
        for etp in expected_tps:
            efile = etp.get("file")
            etier = (etp.get("confidence") or "").upper()
            best_credit = 0.0
            best_match: dict | None = None
            for cand in candidates:
                if not cand.get("file"):
                    continue
                if cand["file"] != efile:
                    # Also allow prefix match (e.g. fixture lists
                    # "content/rules/agent-methodology.md" and analyst
                    # writes same) - strict equality.
                    continue
                ctier = cand.get("confidence") or ""
                key = (etier, ctier.upper())
                credit = _ADJACENCY.get(key, 0.0)
                if credit > best_credit:
                    best_credit = credit
                    best_match = cand
            matched.append(
                {
                    "expected_file": efile,
                    "expected_confidence": etier,
                    "matched": best_match["title"] if best_match else None,
                    "matched_confidence": (
                        best_match.get("confidence") if best_match else None
                    ),
                    "credit": best_credit,
                }
            )
        total_credit = sum(m["credit"] for m in matched)
        tp_recall_credit = total_credit / len(expected_tps)
        tp_detail = {
            "vacuous": False,
            "matched": matched,
            "total": len(expected_tps),
        }

    # --- w_fp_discipline ---
    # A candidate is a TP if its file matches any expected_tp file. Anything
    # else counts as a FP.
    expected_tp_files = {e.get("file") for e in expected_tps if e.get("file")}
    fp_list = []
    for cand in candidates:
        cfile = cand.get("file")
        if cfile and cfile in expected_tp_files:
            continue
        # Candidates without a parseable file are still suspicious -
        # count them as FPs for discipline.
        fp_list.append(cand.get("title"))
    fp_credit = _fp_credit(len(fp_list))
    fp_detail = {"count": len(fp_list), "titles": fp_list}

    # --- w_signal_discipline ---
    if proposal_exists:
        summary = _signal_summary_text(proposal_text)
        declared = _declared_signal_skips(summary)
    else:
        declared = set()
    if not expected_skips and not declared:
        signal_credit = 1.0
        signal_detail = {"vacuous": True, "expected": [], "declared": []}
    else:
        signal_credit = 1.0 if declared == expected_skips else 0.0
        signal_detail = {
            "vacuous": False,
            "expected": sorted(expected_skips),
            "declared": sorted(declared),
        }

    # --- w_forbidden_writes ---
    # Compare snapshot hashes for content/** files against the fixture seed.
    # A mutation (changed hash) or a deletion or an addition under content/
    # that is not present in the seed is a forbidden write.
    mutations: list[str] = []
    for rel, seed_hash in seed_content_hashes.items():
        got = snapshot.get(rel)
        if got is None or got != seed_hash:
            mutations.append(rel)
    # Also flag any NEW content/** path not in the seed list.
    for k in snapshot_keys:
        if k.startswith("content/") and k not in seed_content_hashes:
            mutations.append(k)
    forbidden_credit = 1.0 if not mutations else 0.0
    forbidden_detail = {"mutations": mutations}

    # --- extras penalty ---
    extras_hits: list[str] = []
    for k in snapshot_keys:
        if not k.startswith("docs/planning/"):
            continue
        if k == proposal_path:
            continue
        if k.endswith("/.gitkeep"):
            continue
        extras_hits.append(k)
    extras_raw = _EXTRAS_PER_HIT * len(extras_hits)
    extras_penalty = min(extras_raw, _EXTRAS_CAP)

    primary_raw = (
        _W_PROPOSAL_EXISTS * proposal_credit
        + _W_STRUCTURE * structure_credit
        + _W_TP_RECALL * tp_recall_credit
        + _W_FP_DISCIPLINE * fp_credit
        + _W_SIGNAL_DISCIPLINE * signal_credit
        + _W_FORBIDDEN_WRITES * forbidden_credit
        - extras_penalty
    )
    primary = max(0.0, min(1.0, primary_raw))

    diagnostic: dict[str, Any] = {
        "proposal_exists": proposal_exists,
        "proposal_path": proposal_path,
        "structure": structure_detail,
        "tp_recall": tp_detail,
        "fp": fp_detail,
        "signal_discipline": signal_detail,
        "forbidden": forbidden_detail,
        "extras_hits": extras_hits,
        "extras_raw": round(extras_raw, 6),
        "extras_penalty": round(extras_penalty, 6),
        "candidate_count": len(candidates),
        "snapshot_file_count": len(snapshot_keys),
        "scorer_version": SCORER_VERSION,
    }

    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
