"""
Purpose: Score a single Investigator run against a labeled fixture by parsing
         the mandated investigation-brief output format from
         content/agents/investigator.md and checking structure, answer
         keywords, file:line citations, blast-radius path coverage, and
         confidence calibration.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace (trace["runs"] has exactly one
          run record). Aggregation across N runs is the aggregator module's
          job. A multi-run trace is an API-misuse bug and asserts.

Upstream deps: stdlib re.

Downstream consumers: evals.runner.cli (dynamic import per manifest's
                      scoring_module).

Failure modes: If fewer than 4 of the 7 required sub-sections parse, returns
               status="invalid_format" and primary=0.0 without raising. Never
               raises; all errors are surfaced via status/diagnostic.

Performance: standard; regex-based parse of a short markdown blob.

---

## Scoring formula (v1)

Motivation: the Investigator's value is a structured, evidence-backed brief
the conductor can hand to architect/engineer. Five dimensions capture the
shape of that value, weighted by how load-bearing each is for downstream use:

    w_structure   = 0.15   (7 required sub-sections present)
    w_answer      = 0.20   (substring fraction of fixture.answer_keywords
                            in the ### Answer section)
    w_citation    = 0.30   (tiered credit per expected citation: path+line
                            = 1.0, path-only = 0.5, absent = 0.0)
    w_blast       = 0.25   (fraction of fixture.blast_radius_paths named
                            in the ### Component map section)
    w_calibration = 0.10   (confidence enum valid AND, if gaps_nonempty
                            required, ### Gaps and unknowns contains
                            more than a "no gaps" sentinel)

Weights sum to 1.0 exactly; runtime assertion guards future edits.

Vacuous handling: a fixture may mark an axis vacuous by setting the
corresponding `vacuous_axes` entry. Vacuous axes score 1.0; weights are
NOT renormalized (per init_project_lite v3 precedent). This lets the
clean/scoped control fixture (in-005) skip citation + blast scoring without
collapsing the remaining dimensions' dynamic range.

Format gate: if fewer than 4 of the 7 required sub-sections are present in
the output, the run is invalid_format (primary 0.0, short-circuits scoring).
Four is the threshold where the brief is too skeletal to be useful regardless
of what it contains.

Citation tiering: architect's investigator brief explicitly prefers file:line
over vague paths ("Risks and gotchas" rule: "file:line references over vague
descriptions"). A brief that names the right file but drops the line number
is half-credit - the architect still has to grep for the relevant hunk.

Confidence calibration: the fixture declares which confidence level is
plausible ("acceptable_confidence" is a list, e.g. ["High"] for in-001 where
end-to-end tracing is feasible, ["Medium", "Low"] for in-004 where the
evidence is genuinely ambiguous). If the Investigator emits a confidence
outside that list, calibration is 0. If the fixture further sets
gaps_nonempty=True, the "### Gaps and unknowns" section must not be the
sentinel phrases "none", "coverage was complete", or equivalent - otherwise
calibration is also 0 even if confidence is in-set.

### Version history

v1 (this commit): initial scorer. Five dimensions, tiered citation credit,
    vacuous-axis handling on blast + citation for the scoped-summary control
    fixture, format gate at <4 sub-sections. Shape is defensible
    independent of fixture choice: the dimensions map to the four things
    an investigation brief is FOR (structure, direct answer, evidence
    backing, coverage) plus one axis (calibration) that guards against
    over-confidence on ambiguous evidence.
"""
from __future__ import annotations

import re
from typing import Any

SCORER_VERSION = "v1"

_W_STRUCTURE = 0.15
_W_ANSWER = 0.20
_W_CITATION = 0.30
_W_BLAST = 0.25
_W_CALIBRATION = 0.10

_WEIGHTS_SUM_ASSERTION = abs(
    (_W_STRUCTURE + _W_ANSWER + _W_CITATION + _W_BLAST + _W_CALIBRATION) - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "investigator_lite weights must sum to 1.0"

# The seven required sub-section headings, in the order the agent spec
# prescribes. The top-level "## Investigation:" title is not counted - it
# is a label, not a content section.
_REQUIRED_SECTIONS = [
    "### Answer",
    "### Key findings",
    "### Component map",
    "### Risks and gotchas",
    "### Gaps and unknowns",
    "### Recommended next steps",
    "### Confidence",
]

_FORMAT_GATE_MIN = 4

# Match `path/to/file.ext:lineno` or `path/to/file.ext:start-end`. The path
# must contain a dotted extension to avoid matching bare words.
_PATH_LINE_RE = re.compile(
    r"(?P<path>[A-Za-z0-9_./\-]+\.[A-Za-z0-9]{1,6})(?::(?P<line>\d+(?:-\d+)?))?"
)

_CONFIDENCE_RE = re.compile(
    r"###\s*Confidence\s*\n+\s*(?:\*\*)?(High|Medium|Low)(?:\*\*)?",
    re.IGNORECASE,
)

# Sentinels meaning "nothing to report" in a Gaps section. If the fixture
# requires gaps_nonempty and the section matches one of these, calibration
# fails even if confidence is in-set.
_GAPS_SENTINELS = (
    "none",
    "no gaps",
    "coverage was complete",
    "fully explored",
    "no unknowns",
    "nothing to report",
)


def _extract_section(text: str, heading: str) -> str:
    """Return the body of `heading` up to the next ### heading or EOF.

    Heading matching is line-anchored and case-sensitive. Returns "" if the
    heading is not present.
    """
    pattern = re.compile(
        rf"^{re.escape(heading)}\s*\n(.*?)(?=^###\s|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def _section_present(text: str, heading: str) -> bool:
    return re.search(
        rf"^{re.escape(heading)}\b", text, re.MULTILINE
    ) is not None


def _present_sections(text: str) -> list[str]:
    return [s for s in _REQUIRED_SECTIONS if _section_present(text, s)]


def _score_answer(answer_text: str, keywords: list[str]) -> tuple[float, dict]:
    if not keywords:
        return 1.0, {"vacuous": True, "hits": 0, "total": 0, "missing": []}
    lower = answer_text.lower()
    hits = 0
    missing: list[str] = []
    for kw in keywords:
        if kw.lower() in lower:
            hits += 1
        else:
            missing.append(kw)
    return hits / len(keywords), {
        "vacuous": False,
        "hits": hits,
        "total": len(keywords),
        "missing": missing,
    }


def _score_citations(text: str, expected: list[str]) -> tuple[float, dict]:
    """Tiered citation scoring.

    `expected` is a list of path strings (e.g. "seed/api/fee.py"). For each
    expected path, the best-found citation in the brief is classified:
      - path+line present (e.g. "seed/api/fee.py:42")       -> 1.0
      - path present without a line number                  -> 0.5
      - path absent                                         -> 0.0
    Result is the mean of per-path credits.
    """
    if not expected:
        return 1.0, {"vacuous": True, "credits": [], "total": 0}
    matches = list(_PATH_LINE_RE.finditer(text))
    matched_paths: dict[str, bool] = {}  # path -> has_line (True if any hit has a line)
    for m in matches:
        p = m.group("path")
        has_line = m.group("line") is not None
        prev = matched_paths.get(p)
        matched_paths[p] = prev or has_line

    per_path: list[dict] = []
    total = 0.0
    for exp in expected:
        best = 0.0
        best_found: str | None = None
        for found, has_line in matched_paths.items():
            if exp == found or exp.endswith("/" + found) or found.endswith("/" + exp):
                credit = 1.0 if has_line else 0.5
                if credit > best:
                    best = credit
                    best_found = found
        per_path.append({"expected": exp, "found": best_found, "credit": best})
        total += best
    return total / len(expected), {
        "vacuous": False,
        "credits": per_path,
        "total": len(expected),
    }


def _score_blast(component_map_text: str, paths: list[str]) -> tuple[float, dict]:
    if not paths:
        return 1.0, {"vacuous": True, "hits": 0, "total": 0, "missing": []}
    lower = component_map_text.lower()
    hits = 0
    missing: list[str] = []
    for p in paths:
        if p.lower() in lower:
            hits += 1
        else:
            missing.append(p)
    return hits / len(paths), {
        "vacuous": False,
        "hits": hits,
        "total": len(paths),
        "missing": missing,
    }


def _score_calibration(
    full_text: str,
    gaps_text: str,
    acceptable_confidence: list[str],
    gaps_nonempty_required: bool,
) -> tuple[float, dict]:
    m = _CONFIDENCE_RE.search(full_text)
    observed = m.group(1).capitalize() if m else None
    accepted = [c.capitalize() for c in acceptable_confidence] if acceptable_confidence else []
    if not accepted:
        confidence_ok = observed in {"High", "Medium", "Low"}
    else:
        confidence_ok = observed in accepted

    gaps_lower = gaps_text.strip().lower()
    gaps_is_sentinel = any(s in gaps_lower for s in _GAPS_SENTINELS) or not gaps_lower
    if gaps_nonempty_required:
        gaps_ok = not gaps_is_sentinel and len(gaps_lower) > 0
    else:
        gaps_ok = True

    credit = 1.0 if (confidence_ok and gaps_ok) else 0.0
    return credit, {
        "vacuous": False,
        "observed_confidence": observed,
        "acceptable_confidence": accepted or ["High", "Medium", "Low"],
        "confidence_ok": confidence_ok,
        "gaps_nonempty_required": gaps_nonempty_required,
        "gaps_ok": gaps_ok,
        "gaps_preview": gaps_text[:200],
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
        "investigator_lite.score expects a single-run trace; aggregation "
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

    expected = fixture.get("expected_investigation") or {}
    if not isinstance(expected, dict):
        expected = {}
    answer_keywords = list(expected.get("answer_keywords") or [])
    expected_citations = list(expected.get("expected_citations") or [])
    blast_paths = list(expected.get("blast_radius_paths") or [])
    acceptable_confidence = list(expected.get("acceptable_confidence") or [])
    gaps_nonempty = bool(expected.get("gaps_nonempty", False))
    vacuous_axes = set(expected.get("vacuous_axes") or [])

    answer_body = _extract_section(text, "### Answer")
    component_body = _extract_section(text, "### Component map")
    gaps_body = _extract_section(text, "### Gaps and unknowns")

    # Structure: fraction of the 7 required sections present. Always live -
    # the whole point of the output format is load-bearing.
    structure_credit = len(present) / len(_REQUIRED_SECTIONS)
    structure_detail = {
        "hits": len(present),
        "total": len(_REQUIRED_SECTIONS),
        "present": present,
        "missing": [s for s in _REQUIRED_SECTIONS if s not in present],
    }

    if "answer" in vacuous_axes:
        answer_credit = 1.0
        answer_detail = {"vacuous": True, "hits": 0, "total": 0, "missing": []}
    else:
        answer_credit, answer_detail = _score_answer(answer_body, answer_keywords)

    if "citation" in vacuous_axes:
        citation_credit = 1.0
        citation_detail = {"vacuous": True, "credits": [], "total": 0}
    else:
        citation_credit, citation_detail = _score_citations(text, expected_citations)

    if "blast" in vacuous_axes:
        blast_credit = 1.0
        blast_detail = {"vacuous": True, "hits": 0, "total": 0, "missing": []}
    else:
        blast_credit, blast_detail = _score_blast(component_body, blast_paths)

    if "calibration" in vacuous_axes:
        calibration_credit = 1.0
        calibration_detail = {"vacuous": True}
    else:
        calibration_credit, calibration_detail = _score_calibration(
            text, gaps_body, acceptable_confidence, gaps_nonempty
        )

    primary_raw = (
        _W_STRUCTURE * structure_credit
        + _W_ANSWER * answer_credit
        + _W_CITATION * citation_credit
        + _W_BLAST * blast_credit
        + _W_CALIBRATION * calibration_credit
    )
    primary = max(0.0, min(1.0, primary_raw))

    diagnostic: dict[str, Any] = {
        "structure": structure_detail,
        "answer": answer_detail,
        "citation": citation_detail,
        "blast": blast_detail,
        "calibration": calibration_detail,
        "weights": {
            "structure": _W_STRUCTURE,
            "answer": _W_ANSWER,
            "citation": _W_CITATION,
            "blast": _W_BLAST,
            "calibration": _W_CALIBRATION,
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
