"""
Purpose: Score a single adr-drift-detector run against a labeled fixture by
         parsing the mandated 7-section Drift Report format from
         content/agents/adr-drift-detector.md, classifying each audited ADR
         (VIOLATED / PARTIAL / UNVERIFIABLE / FOLLOWED / SKIPPED /
         PROPOSED), and comparing per-ADR classifications plus
         violation-evidence paths against fixture expectations.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace (trace["runs"] has exactly one
          run record). Aggregation across N runs happens in
          evals.runner.aggregator. A multi-run trace is an API-misuse bug
          and asserts.

Upstream deps: stdlib re.

Downstream consumers: evals.runner.cli (via dynamic import per manifest's
                      scoring_module field).

Failure modes: If the report's section scaffold is absent or malformed
               (fewer than 4 of the 7 required sections parse), returns
               status="invalid_format" and primary=0.0 without raising.
               Never raises; all errors surface via status/diagnostic.

Performance: standard; regex-based parse of a short markdown blob.

---

## Scoring formula (v1)

Five dimensions summing to 1.0. Vacuous axes score 1.0 without
renormalization (init_project_lite v3 precedent; see evals/LEARNINGS.md).

    w_format         = 0.15   (fraction of the 7 required sections
                               present: Summary, Violations, Partial
                               Compliance, Followed, Unverifiable,
                               Proposed, Skipped)
    w_classification = 0.45   (per-ADR TP/FN/FP against expected
                               classifications; severity-weighted)
    w_evidence       = 0.20   (for each expected VIOLATED ADR, fraction
                               of expected violation-evidence paths
                               that appear in the run's Violations
                               section body)
    w_sections       = 0.10   (header summary "ADRs audited: N |
                               Followed: N | Violated: N | ..."
                               counts match what the body lists)
    w_superseded     = 0.10   (TIERED: full credit when every expected
                               SKIPPED ADR is correctly listed under
                               "## Skipped" AND any named
                               superseded_by target that does not
                               exist is flagged per role-doc rule;
                               half credit if skipped but not flagged;
                               zero if the ADR is not skipped)

The classification axis is the load-bearing one. An ADR's expected
classification is matched against what appears in the report using
severity weights:

    VIOLATED      = 1.0
    PARTIAL       = 0.75
    UNVERIFIABLE  = 0.5
    FOLLOWED      = 0.5

    tp_credit  = sum of weights over correctly classified expected ADRs
    max_credit = sum of weights over all expected ADRs (excluding
                 SKIPPED and PROPOSED which are scored by the
                 superseded / sections axes instead)
    fn_penalty = tp weight for misclassified expected ADRs (weight
                 docked, not recouped)
    raw_fp     = 0.3 per FP-VIOLATED (flagging a FOLLOWED or
                 UNVERIFIABLE ADR as VIOLATED) +
                 0.15 per FP-PARTIAL (flagging as PARTIAL when
                 expected FOLLOWED or UNVERIFIABLE) +
                 0.05 per other misclassification FP
    fp_cap     = max(max_credit, 1.0) * 0.5     # BOUNDED
    fp_penalty = min(raw_fp, fp_cap)

    classification_credit = clip(
        (tp_credit - fn_penalty) / max_credit - fp_penalty / max(max_credit, 1.0),
        0, 1
    )

Rationale: fixtures test the agent's ability to NOT over-report
violations. ad-004 seeds a sqlite3 test-only usage under a "use
PostgreSQL in production" ADR to discriminate a naive grep from a
thoughtful classification. Flagging that ADR as VIOLATED costs more
than flagging it as PARTIAL, which costs more than leaving it as
FOLLOWED (the correct call depends on how the fixture labels it;
ad-004 labels it FOLLOWED and any VIOLATED call is a hard FP).

## Vacuous handling

A fixture may mark any axis vacuous via `vacuous_axes`. Vacuous axes
score 1.0 and do not renormalize. ad-001 is clean (no violations), so
`evidence` and parts of the superseded axis are vacuous on that fixture.
ad-005 exercises the superseded axis primarily.

## Format gate

If fewer than 4 of the 7 required top-level sections (`## Summary`,
`## Violations`, `## Partial Compliance`, `## Followed`, `## Unverifiable`,
`## Proposed`, `## Skipped`) are present, the run is invalid_format
(primary 0.0, short-circuits scoring). Four is the threshold where the
report is too skeletal to be useful regardless of content.

### Version history

v1 (this commit): initial scorer. Five dimensions, bounded FP penalty,
    tiered superseded credit, vacuous-axis handling. Weights sum to 1.0
    and the runtime assertion guards future edits.
"""
from __future__ import annotations

import re
from typing import Any

SCORER_VERSION = "v1"

_W_FORMAT = 0.15
_W_CLASSIFICATION = 0.45
_W_EVIDENCE = 0.20
_W_SECTIONS = 0.10
_W_SUPERSEDED = 0.10

_WEIGHTS_SUM_ASSERTION = abs(
    (_W_FORMAT + _W_CLASSIFICATION + _W_EVIDENCE + _W_SECTIONS + _W_SUPERSEDED) - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "adr_drift_detector_lite weights must sum to 1.0"

_REQUIRED_SECTIONS = [
    "## Summary",
    "## Violations",
    "## Partial Compliance",
    "## Followed",
    "## Unverifiable",
    "## Proposed",
    "## Skipped",
]

_FORMAT_GATE_MIN = 4

_CLASS_WEIGHTS = {
    "VIOLATED": 1.0,
    "PARTIAL": 0.75,
    "UNVERIFIABLE": 0.5,
    "FOLLOWED": 0.5,
}

# Match an ADR number reference. We accept zero-padded (ADR-0001) and
# plain (ADR-1). The capture group normalises the integer.
_ADR_REF_RE = re.compile(r"ADR[-\s]?(\d+)", re.IGNORECASE)

_HEADER_COUNTS_RE = re.compile(
    r"ADRs\s+audited:\s*(\d+)\s*\|\s*Followed:\s*(\d+)\s*\|\s*Violated:\s*(\d+)"
    r"\s*\|\s*Partial:\s*(\d+)\s*\|\s*Unverifiable:\s*(\d+)",
    re.IGNORECASE,
)


def _extract_section(text: str, heading: str) -> str:
    """Return body of `heading` up to the next `## ` heading or EOF."""
    pattern = re.compile(
        rf"^{re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def _present_sections(text: str) -> list[str]:
    present = []
    for s in _REQUIRED_SECTIONS:
        if re.search(rf"^{re.escape(s)}\b", text, re.MULTILINE):
            present.append(s)
    return present


def _adr_ids_in(text: str) -> set[int]:
    """Extract ADR numeric IDs from text (e.g. 'ADR-0003' -> 3)."""
    return {int(m.group(1)) for m in _ADR_REF_RE.finditer(text)}


def _normalise_adr_id(raw: str | int) -> int | None:
    """Accept 'ADR-0003', '0003', or int; return int or None if unparseable."""
    if isinstance(raw, int):
        return raw
    if not isinstance(raw, str):
        return None
    m = _ADR_REF_RE.search(raw)
    if m:
        return int(m.group(1))
    try:
        return int(raw)
    except ValueError:
        return None


def _classify_observed(text: str) -> dict[int, str]:
    """Return {adr_id: classification} for every ADR the report placed
    under one of the outcome sections.

    Outcome sections are mapped to classification labels. If an ADR is
    mentioned in more than one section (it shouldn't be), the first
    non-clean classification wins in this priority order:
    VIOLATED > PARTIAL > UNVERIFIABLE > FOLLOWED > SKIPPED > PROPOSED.
    """
    section_to_class = [
        ("## Violations", "VIOLATED"),
        ("## Partial Compliance", "PARTIAL"),
        ("## Unverifiable", "UNVERIFIABLE"),
        ("## Followed", "FOLLOWED"),
        ("## Skipped", "SKIPPED"),
        ("## Proposed", "PROPOSED"),
    ]
    observed: dict[int, str] = {}
    for heading, cls in section_to_class:
        body = _extract_section(text, heading)
        if not body:
            continue
        for adr_id in _adr_ids_in(body):
            # Priority: don't let a later section downgrade a prior
            # higher-severity placement.
            if adr_id not in observed:
                observed[adr_id] = cls
    return observed


def _score_classification(
    expected: dict[int, str],
    observed: dict[int, str],
) -> tuple[float, dict]:
    """Classification axis. Severity-weighted TP/FN with bounded FP penalty."""
    # Expected excludes SKIPPED and PROPOSED (scored by superseded /
    # sections axes). Those still participate in observed as signal for
    # the superseded axis.
    audit_expected = {
        adr_id: cls for adr_id, cls in expected.items()
        if cls in _CLASS_WEIGHTS
    }
    if not audit_expected:
        return 1.0, {"vacuous": True}

    max_credit = sum(_CLASS_WEIGHTS[c] for c in audit_expected.values())

    tp_credit = 0.0
    fn_penalty = 0.0
    per_adr: list[dict] = []
    misclassified_fps: list[dict] = []
    for adr_id, exp_cls in audit_expected.items():
        obs_cls = observed.get(adr_id)
        w = _CLASS_WEIGHTS[exp_cls]
        if obs_cls == exp_cls:
            tp_credit += w
            per_adr.append({
                "adr_id": adr_id,
                "expected": exp_cls,
                "observed": obs_cls,
                "result": "TP",
                "credit": w,
            })
        else:
            # Wrong classification: docked weight, and the wrong
            # placement (if any) is an FP if it over-flags.
            fn_penalty += w
            per_adr.append({
                "adr_id": adr_id,
                "expected": exp_cls,
                "observed": obs_cls,
                "result": "FN",
                "credit": 0.0,
            })
            if obs_cls is not None and obs_cls != exp_cls:
                misclassified_fps.append({
                    "adr_id": adr_id,
                    "expected": exp_cls,
                    "observed": obs_cls,
                })

    # FP weights: over-flagging (calling FOLLOWED/UNVERIFIABLE "VIOLATED")
    # is worst; the other misclassifications are lighter.
    raw_fp = 0.0
    for m in misclassified_fps:
        obs = m["observed"]
        exp = m["expected"]
        if obs == "VIOLATED" and exp in ("FOLLOWED", "UNVERIFIABLE"):
            raw_fp += 0.3
        elif obs == "PARTIAL" and exp in ("FOLLOWED", "UNVERIFIABLE"):
            raw_fp += 0.15
        else:
            raw_fp += 0.05

    # FPs from ADRs that appear in observed but not in expected at all
    # (invented or hallucinated ADR numbers). These are hard FPs.
    hallucinated = [
        aid for aid in observed
        if aid not in expected and observed[aid] in ("VIOLATED", "PARTIAL")
    ]
    for _ in hallucinated:
        raw_fp += 0.3

    fp_cap = max(max_credit, 1.0) * 0.5
    fp_penalty = min(raw_fp, fp_cap)

    base = (tp_credit - fn_penalty) / max_credit if max_credit > 0 else 0.0
    credit = base - fp_penalty / max(max_credit, 1.0)
    credit = max(0.0, min(1.0, credit))

    return credit, {
        "vacuous": False,
        "per_adr": per_adr,
        "tp_credit": round(tp_credit, 6),
        "max_credit": round(max_credit, 6),
        "fn_penalty": round(fn_penalty, 6),
        "raw_fp": round(raw_fp, 6),
        "fp_cap": round(fp_cap, 6),
        "fp_penalty": round(fp_penalty, 6),
        "hallucinated_ids": hallucinated,
    }


def _score_evidence(
    violations_body: str,
    expected_violations: dict[int, list[str]],
) -> tuple[float, dict]:
    """For each expected VIOLATED ADR, fraction of expected paths that
    appear as substrings anywhere in the Violations section body."""
    if not expected_violations:
        return 1.0, {"vacuous": True}
    per_adr: list[dict] = []
    total_paths = 0
    hits = 0
    body_lower = violations_body.lower()
    for adr_id, paths in expected_violations.items():
        for p in paths:
            total_paths += 1
            if p.lower() in body_lower:
                hits += 1
                per_adr.append({"adr_id": adr_id, "path": p, "found": True})
            else:
                per_adr.append({"adr_id": adr_id, "path": p, "found": False})
    credit = hits / total_paths if total_paths > 0 else 1.0
    return credit, {
        "vacuous": False,
        "hits": hits,
        "total": total_paths,
        "per_adr": per_adr,
    }


def _score_sections(text: str, observed: dict[int, str]) -> tuple[float, dict]:
    """Header counts consistency: the header summary line's counts must
    match what the body sections list."""
    m = _HEADER_COUNTS_RE.search(text)
    if not m:
        return 0.0, {
            "header_found": False,
        }
    audited, followed, violated, partial, unverifiable = (int(m.group(i)) for i in range(1, 6))

    body_counts = {
        "FOLLOWED": sum(1 for c in observed.values() if c == "FOLLOWED"),
        "VIOLATED": sum(1 for c in observed.values() if c == "VIOLATED"),
        "PARTIAL": sum(1 for c in observed.values() if c == "PARTIAL"),
        "UNVERIFIABLE": sum(1 for c in observed.values() if c == "UNVERIFIABLE"),
    }
    body_audited = sum(body_counts.values())

    matches = 0
    total = 5
    if audited == body_audited:
        matches += 1
    if followed == body_counts["FOLLOWED"]:
        matches += 1
    if violated == body_counts["VIOLATED"]:
        matches += 1
    if partial == body_counts["PARTIAL"]:
        matches += 1
    if unverifiable == body_counts["UNVERIFIABLE"]:
        matches += 1
    return matches / total, {
        "header_found": True,
        "header_counts": {
            "audited": audited,
            "followed": followed,
            "violated": violated,
            "partial": partial,
            "unverifiable": unverifiable,
        },
        "body_counts": {
            "audited": body_audited,
            **body_counts,
        },
        "matches": matches,
        "total": total,
    }


def _score_superseded(
    text: str,
    expected: dict[int, str],
    expected_superseded_targets_missing: set[int],
) -> tuple[float, dict]:
    """Tiered credit for Skipped-section coverage.

    - 1.0: every expected SKIPPED ADR appears under '## Skipped' AND
           any ADR whose superseded_by target is missing is explicitly
           flagged with a warning marker (case-insensitive substring
           match for any of: 'not found', 'does not exist', '⚠️',
           'warning').
    - 0.5: skipped ADRs are listed but the missing-target flag is not
           raised on at least one of the ADRs that requires it.
    - 0.0: at least one expected SKIPPED ADR is not listed in the
           '## Skipped' section.

    Vacuous if no ADR is expected SKIPPED.
    """
    expected_skipped = {aid for aid, c in expected.items() if c == "SKIPPED"}
    if not expected_skipped:
        return 1.0, {"vacuous": True}

    skipped_body = _extract_section(text, "## Skipped")
    if not skipped_body:
        return 0.0, {
            "vacuous": False,
            "reason": "no_skipped_section",
            "expected_skipped": sorted(expected_skipped),
        }

    skipped_ids = _adr_ids_in(skipped_body)
    missing = expected_skipped - skipped_ids
    if missing:
        return 0.0, {
            "vacuous": False,
            "reason": "missing_skipped_entries",
            "missing": sorted(missing),
        }

    # All skipped listed. Check warning markers on those whose targets
    # are missing (the fixture tells us which IDs need the flag).
    warn_markers = ("not found", "does not exist", "⚠", "warning")
    body_lower = skipped_body.lower()
    flag_ok = True
    per_adr: list[dict] = []
    for adr_id in expected_superseded_targets_missing:
        # Find the ADR's line in the skipped body.
        line_re = re.compile(
            rf"(^|\n)[^\n]*ADR[-\s]?0*{adr_id}\b[^\n]*",
            re.IGNORECASE,
        )
        m = line_re.search(skipped_body)
        if not m:
            # ADR not listed in Skipped at all (should have been caught
            # above), mark as flag-missing.
            flag_ok = False
            per_adr.append({"adr_id": adr_id, "flagged": False, "reason": "not_in_skipped"})
            continue
        line = m.group(0).lower()
        flagged = any(w in line for w in warn_markers)
        if not flagged:
            flag_ok = False
        per_adr.append({"adr_id": adr_id, "flagged": flagged})

    if flag_ok:
        return 1.0, {
            "vacuous": False,
            "reason": "all_listed_and_flagged",
            "per_adr": per_adr,
        }
    return 0.5, {
        "vacuous": False,
        "reason": "listed_but_flag_missing",
        "per_adr": per_adr,
    }


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
        "adr_drift_detector_lite.score expects a single-run trace; aggregation "
        "across N runs happens in evals.runner.aggregator, not here."
    )

    run = runs[0]
    text = run.get("final_text") or ""

    present = _present_sections(text)
    if len(present) < _FORMAT_GATE_MIN:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "too_few_sections",
                "sections_present": present,
                "required": _REQUIRED_SECTIONS,
                "final_text_preview": text[:600],
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }

    exp_raw = fixture.get("expected_report") or {}
    if not isinstance(exp_raw, dict):
        exp_raw = {}

    # expected_classifications: list of {adr_id, classification}
    expected: dict[int, str] = {}
    for item in exp_raw.get("expected_classifications") or []:
        if not isinstance(item, dict):
            continue
        aid = _normalise_adr_id(item.get("adr_id"))
        cls = (item.get("classification") or "").upper()
        if aid is None:
            continue
        expected[aid] = cls

    # expected_violations: {adr_id: [path, ...]} for ADRs whose
    # classification is VIOLATED.
    expected_violations: dict[int, list[str]] = {}
    for item in exp_raw.get("expected_violation_evidence") or []:
        if not isinstance(item, dict):
            continue
        aid = _normalise_adr_id(item.get("adr_id"))
        paths = list(item.get("paths") or [])
        if aid is not None and paths:
            expected_violations[aid] = paths

    # ADR IDs whose superseded_by target does not exist in the fixture's
    # ADR directory, requiring the warning flag per role doc.
    missing_targets: set[int] = set()
    for item in exp_raw.get("expected_superseded_missing") or []:
        aid = _normalise_adr_id(item)
        if aid is not None:
            missing_targets.add(aid)

    vacuous_axes = set(exp_raw.get("vacuous_axes") or [])
    observed = _classify_observed(text)
    violations_body = _extract_section(text, "## Violations")

    # Structure / format axis: fraction of the 7 sections present.
    format_credit = len(present) / len(_REQUIRED_SECTIONS)
    format_detail = {
        "hits": len(present),
        "total": len(_REQUIRED_SECTIONS),
        "present": present,
        "missing": [s for s in _REQUIRED_SECTIONS if s not in present],
    }

    if "classification" in vacuous_axes:
        classification_credit = 1.0
        classification_detail = {"vacuous": True}
    else:
        classification_credit, classification_detail = _score_classification(expected, observed)

    if "evidence" in vacuous_axes:
        evidence_credit = 1.0
        evidence_detail = {"vacuous": True}
    else:
        evidence_credit, evidence_detail = _score_evidence(violations_body, expected_violations)

    if "sections" in vacuous_axes:
        sections_credit = 1.0
        sections_detail = {"vacuous": True}
    else:
        sections_credit, sections_detail = _score_sections(text, observed)

    if "superseded" in vacuous_axes:
        superseded_credit = 1.0
        superseded_detail = {"vacuous": True}
    else:
        superseded_credit, superseded_detail = _score_superseded(text, expected, missing_targets)

    primary_raw = (
        _W_FORMAT * format_credit
        + _W_CLASSIFICATION * classification_credit
        + _W_EVIDENCE * evidence_credit
        + _W_SECTIONS * sections_credit
        + _W_SUPERSEDED * superseded_credit
    )
    primary = max(0.0, min(1.0, primary_raw))

    diagnostic: dict[str, Any] = {
        "format": format_detail,
        "classification": classification_detail,
        "evidence": evidence_detail,
        "sections": sections_detail,
        "superseded": superseded_detail,
        "observed_classifications": {str(k): v for k, v in observed.items()},
        "expected_classifications": {str(k): v for k, v in expected.items()},
        "weights": {
            "format": _W_FORMAT,
            "classification": _W_CLASSIFICATION,
            "evidence": _W_EVIDENCE,
            "sections": _W_SECTIONS,
            "superseded": _W_SUPERSEDED,
        },
        "vacuous_axes": sorted(vacuous_axes),
        "scorer_version": SCORER_VERSION,
    }
    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
