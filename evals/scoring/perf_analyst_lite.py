"""
Purpose: Score a single perf-analyst run against a labeled fixture by parsing
         the structured Perf Analysis report mandated by
         content/agents/perf-analyst.md (## Perf Analysis: title + 9 sub-
         sections: Summary, Methodology, Measurements, Perf budget verdict,
         Hotspot, Root cause, Evidence, Fix brief for engineer, Confidence)
         and combining seven weighted dimensions.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace (trace["runs"] has one run
          record). Aggregation across N runs is the aggregator module's
          job. A multi-run trace is an API-misuse bug and the function
          asserts on it.

Upstream deps: stdlib re.

Downstream consumers: evals.runner.cli (dynamic import per manifest's
                      scoring_module field).

Failure modes: if fewer than 8 of the 10 required section headers are
               present, returns status="invalid_format" and primary=0.0.
               Never raises; errors surface via status/diagnostic.

Performance: standard; regex parse of a short text blob.

---

## Scoring formula (v1)

Seven weighted dimensions; weights sum to exactly 1.0 (runtime assertion).

    w_format         = 0.15
    w_hotspot_loc    = 0.20
    w_pattern        = 0.20
    w_evidence       = 0.15
    w_budget         = 0.10
    w_fix_brief      = 0.10
    w_confidence     = 0.10

### Dimension definitions

- **format**: tiered credit for required-section presence. The report
  must carry a "## Perf Analysis:" title plus nine "### <section>"
  headings (Summary, Methodology, Measurements, Perf budget verdict,
  Hotspot, Root cause, Evidence, Fix brief for engineer, Confidence).
  Scoring:
    - 10 of 10 headers present                -> 1.0
    - 8 or 9 of 10 present                    -> 0.5
    - <= 7 of 10 present                      -> run is invalid_format
      (primary=0.0, short-circuits the rest of scoring).

- **hotspot_loc**: fraction of fixture.hotspot_keywords that appear
  (case-insensitive substring) in the Hotspot section body. Vacuous if
  fixture declares no hotspot_keywords.

- **pattern**: the Hotspot section's "Pattern:" line must carry a token
  matching the fixture's expected_pattern (case-insensitive substring
  match on the enum literal). Credit is 1.0 on exact enum match, 0.0
  otherwise. If the raised pattern token matches any fixture
  forbidden_patterns, this axis is forced to 0.0 regardless of any other
  match (the forbidden-pattern trap). Vacuous if expected_pattern is
  null AND forbidden_patterns is empty.

- **evidence**: fraction of fixture.evidence_tokens (case-insensitive
  substrings) found in the combined Evidence + Measurements sections.
  These are the numeric citations the scorer expects: percentages,
  query counts, byte totals, timer values quoted from the staged
  artifacts. Vacuous if fixture declares no evidence_tokens.

- **budget**: matches the "### Perf budget verdict" section's literal
  verdict token against fixture.expected_budget_verdict (one of PASS,
  FAIL, N/A; case-insensitive). Credit 1.0 on exact match, 0.0
  otherwise. Vacuous if fixture declares no expected_budget_verdict.

- **fix_brief**: the Fix brief for engineer section must name a
  concrete location (at least one fixture.hotspot_keywords substring
  appears in the Fix brief body) AND carry a concrete action verb. The
  verb set is a fixed lexicon: {"replace", "remove", "cache",
  "memoize", "batch", "async", "stream", "index", "preload", "reuse",
  "avoid", "move", "hoist", "eliminate", "rewrite", "defer",
  "prefetch", "bulk", "join", "eager"}. Credit is 1.0 only if BOTH
  conditions hold; 0.5 if one holds; 0.0 if neither. Vacuous if
  fixture.hotspot_keywords is empty (no anchor to check location
  against).

- **confidence**: matches the parsed Confidence enum token against
  fixture.expected_confidence (one of High, Medium, Low). Tiered:
    - exact match                                       -> 1.0
    - adjacent (High<->Medium or Medium<->Low)          -> 0.5
    - polar (High<->Low)                                -> 0.0
  Overclaim guard: if expected_confidence is "Medium" or "Low" and the
  parsed confidence is "High", credit is clamped to 0.5 max - an
  overclaiming brief on an intentionally below-ceiling fixture must not
  receive full credit even if the "adjacent" tier would allow it. This
  is the confidence trap (pa-001 N+1-but-no-second-measurement,
  pa-003 CPU-pattern-overclaim).

### Vacuous handling

Vacuous axes score 1.0; weights are NOT renormalized (init_project_lite
v3 / investigator_lite v1 precedent). Over-vacuous fixtures would
saturate the scorer; keep at most two axes vacuous per fixture.

### Invalid-format floor

If the Perf Analysis title is missing OR fewer than 8 of the 10
required section headers are present, primary=0.0 with
status="invalid_format". A perf-analyst that does not follow the
report contract has not produced a scorable analysis.
"""
from __future__ import annotations

import re
from typing import Any

SCORER_VERSION = "v1"

_W_FORMAT = 0.15
_W_HOTSPOT_LOC = 0.20
_W_PATTERN = 0.20
_W_EVIDENCE = 0.15
_W_BUDGET = 0.10
_W_FIX_BRIEF = 0.10
_W_CONFIDENCE = 0.10

_WEIGHTS_SUM_OK = abs(
    (
        _W_FORMAT
        + _W_HOTSPOT_LOC
        + _W_PATTERN
        + _W_EVIDENCE
        + _W_BUDGET
        + _W_FIX_BRIEF
        + _W_CONFIDENCE
    )
    - 1.0
) < 1e-9
assert _WEIGHTS_SUM_OK, "perf_analyst_lite weights must sum to 1.0"


# Ten required headers. The first is the "## Perf Analysis:" title; the
# remaining nine are "### <section>" sub-headings mandated by the role doc.
_TITLE_RE = re.compile(r"^##\s+Perf\s+Analysis\s*:", re.MULTILINE | re.IGNORECASE)

_SUBSECTION_HEADERS = [
    ("summary", re.compile(r"^###\s+Summary\b", re.MULTILINE | re.IGNORECASE)),
    ("methodology", re.compile(r"^###\s+Methodology\b", re.MULTILINE | re.IGNORECASE)),
    ("measurements", re.compile(r"^###\s+Measurements\b", re.MULTILINE | re.IGNORECASE)),
    (
        "perf_budget_verdict",
        re.compile(r"^###\s+Perf\s+budget\s+verdict\b", re.MULTILINE | re.IGNORECASE),
    ),
    ("hotspot", re.compile(r"^###\s+Hotspot\b", re.MULTILINE | re.IGNORECASE)),
    ("root_cause", re.compile(r"^###\s+Root\s+cause\b", re.MULTILINE | re.IGNORECASE)),
    ("evidence", re.compile(r"^###\s+Evidence\b", re.MULTILINE | re.IGNORECASE)),
    (
        "fix_brief",
        re.compile(r"^###\s+Fix\s+brief(?:\s+for\s+engineer)?\b", re.MULTILINE | re.IGNORECASE),
    ),
    ("confidence", re.compile(r"^###\s+Confidence\b", re.MULTILINE | re.IGNORECASE)),
]

_CONFIDENCE_VALUE_RE = re.compile(r"\b(High|Medium|Low)\b", re.IGNORECASE)

_BUDGET_VERDICT_RE = re.compile(r"\b(PASS|FAIL|N\s*/\s*A)\b", re.IGNORECASE)

_PATTERN_LINE_RE = re.compile(
    r"(?i)\bPattern\b\s*[:\*]*\s*([^\n]+)",
)

_FIX_BRIEF_VERBS = {
    "replace",
    "remove",
    "cache",
    "memoize",
    "batch",
    "async",
    "stream",
    "index",
    "preload",
    "reuse",
    "avoid",
    "move",
    "hoist",
    "eliminate",
    "rewrite",
    "defer",
    "prefetch",
    "bulk",
    "join",
    "eager",
}


def _split_sections(text: str) -> dict[str, str]:
    """Return {section_key: section_body} for each matched sub-section."""
    hits: list[tuple[int, int, str]] = []
    for key, pat in _SUBSECTION_HEADERS:
        for m in pat.finditer(text):
            line_end = text.find("\n", m.end())
            if line_end == -1:
                line_end = len(text)
            hits.append((m.start(), line_end, key))
    all_headers = [m.start() for m in re.finditer(r"^#{1,6}\s+\S", text, re.MULTILINE)]
    hits.sort()
    out: dict[str, str] = {}
    for i, (_, hdr_end, key) in enumerate(hits):
        next_boundary = len(text)
        if i + 1 < len(hits):
            next_boundary = min(next_boundary, hits[i + 1][0])
        for h in all_headers:
            if h > hdr_end and h < next_boundary:
                next_boundary = h
                break
        out.setdefault(key, text[hdr_end:next_boundary].strip())
    return out


def _score_format(text: str) -> tuple[float, dict, bool]:
    """Returns (credit, detail, valid_format)."""
    title_present = bool(_TITLE_RE.search(text or ""))
    present: list[str] = []
    missing: list[str] = []
    for key, pat in _SUBSECTION_HEADERS:
        if pat.search(text or ""):
            present.append(key)
        else:
            missing.append(key)
    n_present = (1 if title_present else 0) + len(present)
    if n_present >= 10:
        return (1.0, {"present": n_present, "title": title_present, "missing": missing}, True)
    if n_present >= 8:
        return (0.5, {"present": n_present, "title": title_present, "missing": missing}, True)
    return (0.0, {"present": n_present, "title": title_present, "missing": missing}, False)


def _score_hotspot_loc(body: str, fixture: dict) -> tuple[float, dict]:
    kws = list(fixture.get("hotspot_keywords") or [])
    if not kws:
        return (1.0, {"vacuous": True})
    b_low = (body or "").lower()
    hits = [kw for kw in kws if kw and kw.lower() in b_low]
    return (
        len(hits) / len(kws),
        {"vacuous": False, "hits": hits, "misses": [k for k in kws if k not in hits]},
    )


def _score_pattern(hotspot_body: str, fixture: dict) -> tuple[float, dict]:
    expected = (fixture.get("expected_pattern") or "").strip()
    forbidden = list(fixture.get("forbidden_patterns") or [])
    if not expected and not forbidden:
        return (1.0, {"vacuous": True})
    m = _PATTERN_LINE_RE.search(hotspot_body or "")
    raised_line = m.group(1).strip() if m else ""
    raised_low = raised_line.lower()
    for fp in forbidden:
        if fp and fp.lower() in raised_low:
            return (
                0.0,
                {
                    "vacuous": False,
                    "raised": raised_line,
                    "expected": expected,
                    "hit_forbidden": fp,
                },
            )
    if expected and expected.lower() in raised_low:
        return (
            1.0,
            {"vacuous": False, "raised": raised_line, "expected": expected, "match": True},
        )
    return (
        0.0,
        {"vacuous": False, "raised": raised_line, "expected": expected, "match": False},
    )


def _score_evidence(
    evidence_body: str, measurements_body: str, fixture: dict
) -> tuple[float, dict]:
    tokens = list(fixture.get("evidence_tokens") or [])
    if not tokens:
        return (1.0, {"vacuous": True})
    blob = ((evidence_body or "") + "\n" + (measurements_body or "")).lower()
    hits = [t for t in tokens if t and t.lower() in blob]
    return (
        len(hits) / len(tokens),
        {"vacuous": False, "hits": hits, "misses": [t for t in tokens if t not in hits]},
    )


def _score_budget(body: str, fixture: dict) -> tuple[float, dict]:
    expected = (fixture.get("expected_budget_verdict") or "").strip()
    if not expected:
        return (1.0, {"vacuous": True})
    m = _BUDGET_VERDICT_RE.search(body or "")
    raised = None
    if m:
        raised = m.group(1).upper().replace(" ", "")
    exp_norm = expected.upper().replace(" ", "")
    if raised == exp_norm:
        return (1.0, {"vacuous": False, "raised": raised, "expected": exp_norm, "match": True})
    return (0.0, {"vacuous": False, "raised": raised, "expected": exp_norm, "match": False})


def _score_fix_brief(body: str, fixture: dict) -> tuple[float, dict]:
    kws = list(fixture.get("hotspot_keywords") or [])
    if not kws:
        return (1.0, {"vacuous": True})
    b_low = (body or "").lower()
    has_location = any(kw and kw.lower() in b_low for kw in kws)
    verb_hits = [v for v in _FIX_BRIEF_VERBS if re.search(r"\b" + v + r"\b", b_low)]
    has_verb = bool(verb_hits)
    if has_location and has_verb:
        credit = 1.0
    elif has_location or has_verb:
        credit = 0.5
    else:
        credit = 0.0
    return (
        credit,
        {
            "vacuous": False,
            "has_location": has_location,
            "has_verb": has_verb,
            "verb_hits": verb_hits[:5],
        },
    )


def _parse_confidence(body: str) -> str | None:
    m = _CONFIDENCE_VALUE_RE.search(body or "")
    if not m:
        return None
    return m.group(1).capitalize()


def _score_confidence(parsed: str | None, expected: str | None) -> tuple[float, dict]:
    if not parsed or not expected:
        return (0.0, {"parsed": parsed, "expected": expected, "match": "no_enum"})
    p = parsed.capitalize()
    e = expected.capitalize()
    if p == e:
        return (1.0, {"parsed": p, "expected": e, "match": "exact"})
    pair = {p, e}
    if pair == {"High", "Low"}:
        credit = 0.0
        match_type = "polar"
    else:
        credit = 0.5
        match_type = "adjacent"
    # Overclaim guard: expected Medium/Low but parsed High clamps at 0.5 max.
    if e in ("Medium", "Low") and p == "High":
        credit = min(credit, 0.5)
        match_type = "overclaim"
    return (credit, {"parsed": p, "expected": e, "match": match_type})


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
        "perf_analyst_lite.score expects a single-run trace; aggregation across "
        "N runs happens in evals.runner.aggregator, not here."
    )
    run = runs[0]
    text = run.get("final_text") or ""

    format_credit, format_detail, valid_format = _score_format(text)
    if not valid_format:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "perf_analysis_report_format_not_detected",
                "format": format_detail,
                "final_text_preview": text[:600],
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }

    sections = _split_sections(text)
    hotspot_body = sections.get("hotspot", "")
    evidence_body = sections.get("evidence", "")
    measurements_body = sections.get("measurements", "")
    budget_body = sections.get("perf_budget_verdict", "")
    fix_brief_body = sections.get("fix_brief", "")
    confidence_body = sections.get("confidence", "")

    hotspot_credit, hotspot_detail = _score_hotspot_loc(hotspot_body, fixture)
    pattern_credit, pattern_detail = _score_pattern(hotspot_body, fixture)
    evidence_credit, evidence_detail = _score_evidence(
        evidence_body, measurements_body, fixture
    )
    budget_credit, budget_detail = _score_budget(budget_body, fixture)
    fix_credit, fix_detail = _score_fix_brief(fix_brief_body, fixture)
    parsed_confidence = _parse_confidence(confidence_body)
    confidence_credit, confidence_detail = _score_confidence(
        parsed_confidence, fixture.get("expected_confidence")
    )

    primary = (
        _W_FORMAT * format_credit
        + _W_HOTSPOT_LOC * hotspot_credit
        + _W_PATTERN * pattern_credit
        + _W_EVIDENCE * evidence_credit
        + _W_BUDGET * budget_credit
        + _W_FIX_BRIEF * fix_credit
        + _W_CONFIDENCE * confidence_credit
    )
    primary = max(0.0, min(1.0, primary))

    diagnostic: dict[str, Any] = {
        "format": {"credit": format_credit, **format_detail},
        "hotspot_loc": {"credit": hotspot_credit, **hotspot_detail},
        "pattern": {"credit": pattern_credit, **pattern_detail},
        "evidence": {"credit": evidence_credit, **evidence_detail},
        "budget": {"credit": budget_credit, **budget_detail},
        "fix_brief": {"credit": fix_credit, **fix_detail},
        "confidence": {"credit": confidence_credit, **confidence_detail},
        "parsed_confidence": parsed_confidence,
        "scorer_version": SCORER_VERSION,
    }
    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
