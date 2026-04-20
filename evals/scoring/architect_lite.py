"""
Purpose: Score a single architect plan against a labeled fixture by parsing
         the mandated 7-section skeleton from content/agents/architect.md,
         then measuring structural coverage, approach commitment, API
         fidelity, section-keyword coverage, alternatives, open questions,
         and anti-pattern avoidance.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace - trace["runs"] has exactly
          one run record with "final_text" holding the architect's emitted
          plan. Aggregation across N runs happens in evals.runner.aggregator.

Upstream deps: stdlib re.

Downstream consumers: evals.runner.cli (dynamic import per the architect
                      manifest's scoring_module field).

Failure modes: returns status="invalid_format" when no required sections
               parse. Never raises; all defects surface via diagnostic.

Performance: standard; a handful of regex passes over a prose blob.

## Scoring formula (v1)

Seven weighted dimensions summing to exactly 1.0. Each is vacuous-safe:
a fixture that does not exercise an axis credits 1.0 rather than 0/0.

    w_structure       = 0.25   # 7 required section headers present
    w_approach_commit = 0.15   # tiered: commits + class match 1.0;
                               # commits but class miss 0.5; hedges 0.0
    w_api_fidelity    = 0.20   # required_api_symbols + required_file_paths
                               # appear in API or Implementation steps
    w_section_keywords= 0.15   # per-section substring coverage
    w_alternatives    = 0.10   # "Alternatives considered" + >=2 bullets
                               # OR "No meaningful alternatives" escape
    w_open_questions  = 0.05   # None or bullets matching expected shape
    w_anti_pattern    = 0.10   # 1.0 - 0.3*Major_hits - 0.1*Minor_hits

The approach_class axis is enum-enforced at the PROMPT layer (see
evals/runner/prompt.py). The scorer does exact substring matching,
underscore-or-space tolerant; no synonym map (LEARNINGS 22-26).
Perfect-run arithmetic: 0.25 + 0.15 + 0.20 + 0.15 + 0.10 + 0.05 + 0.10 = 1.00.
"""
from __future__ import annotations

import re
from typing import Any

SCORER_VERSION = "v1"

_W_STRUCTURE = 0.25
_W_APPROACH_COMMIT = 0.15
_W_API_FIDELITY = 0.20
_W_SECTION_KEYWORDS = 0.15
_W_ALTERNATIVES = 0.10
_W_OPEN_QUESTIONS = 0.05
_W_ANTI_PATTERN = 0.10

_WEIGHTS_SUM_ASSERTION = abs(
    (_W_STRUCTURE + _W_APPROACH_COMMIT + _W_API_FIDELITY + _W_SECTION_KEYWORDS
     + _W_ALTERNATIVES + _W_OPEN_QUESTIONS + _W_ANTI_PATTERN) - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "architect_lite weights must sum to 1.0"

REQUIRED_SECTIONS = [
    "approach",
    "codebase context",
    "data model",
    "api / interface design",
    "implementation steps",
    "trade-offs and constraints",
    "open questions",
]

_SECTION_HEADER_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_HEDGE_PATTERNS = [
    re.compile(r"\boptions? (?:include|are)\b", re.IGNORECASE),
    re.compile(r"\beither\b.+\bor\b", re.IGNORECASE),
    re.compile(r"\b(?:a few|several|multiple) (?:ways|approaches|options)\b", re.IGNORECASE),
    re.compile(r"\bcould (?:be|use|go)\b", re.IGNORECASE),
    re.compile(r"\bwe could\b", re.IGNORECASE),
]
_ALTS_MARKER_RE = re.compile(r"Alternatives considered", re.IGNORECASE)
_ALTS_ESCAPE_RE = re.compile(r"No meaningful alternatives", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*[-*]\s+", re.MULTILINE)


def _split_sections(text: str) -> dict[str, str]:
    matches = list(_SECTION_HEADER_RE.finditer(text))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        name = m.group(1).strip().lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[name] = text[start:end].strip()
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _find_section_body(sections: dict[str, str], canonical_name: str) -> str | None:
    target = _norm(canonical_name)
    for name, body in sections.items():
        if _norm(name) == target:
            return body
    return None


def _contains_normalized(haystack: str, needle: str) -> bool:
    h = haystack.lower().replace("_", " ")
    n = needle.lower().replace("_", " ")
    return n in h


def _score_structure(sections: dict[str, str]) -> tuple[float, list[str]]:
    missing: list[str] = []
    hits = 0
    for req in REQUIRED_SECTIONS:
        if _find_section_body(sections, req) is not None:
            hits += 1
        else:
            missing.append(req)
    return (hits / len(REQUIRED_SECTIONS)), missing


def _score_approach_commit(approach_body: str | None, expected_class: str | None) -> tuple[float, dict]:
    if not approach_body:
        return 0.0, {"commits": False, "class_match": False, "reason": "no_approach_section"}
    bullets = _BULLET_RE.findall(approach_body)
    has_hedge = any(p.search(approach_body) for p in _HEDGE_PATTERNS)
    menu_like = len(bullets) >= 2 and has_hedge
    commits = not has_hedge and not menu_like
    class_match = False
    if expected_class:
        class_match = _contains_normalized(approach_body, expected_class)
    if not commits:
        return 0.0, {"commits": False, "class_match": class_match, "bullets": len(bullets), "hedge": has_hedge}
    if class_match:
        return 1.0, {"commits": True, "class_match": True, "bullets": len(bullets)}
    if not expected_class:
        return 1.0, {"commits": True, "class_match": None, "bullets": len(bullets), "reason": "no_expected_class"}
    return 0.5, {"commits": True, "class_match": False, "bullets": len(bullets)}


def _score_api_fidelity(api_body, impl_body, required_symbols, required_paths):
    total = len(required_symbols) + len(required_paths)
    if total == 0:
        return 1.0, {"vacuous": True, "symbols_hit": 0, "paths_hit": 0, "total": 0}
    combined = "\n".join([api_body or "", impl_body or ""]).lower()
    sym_hits = sum(1 for s in required_symbols if s.lower() in combined)
    path_hits = sum(1 for p in required_paths if p.lower() in combined)
    return (sym_hits + path_hits) / total, {
        "vacuous": False, "symbols_hit": sym_hits, "symbols_total": len(required_symbols),
        "paths_hit": path_hits, "paths_total": len(required_paths),
    }


def _score_section_keywords(sections, required_by_section):
    if not required_by_section:
        return 1.0, {"vacuous": True}
    total = 0
    hits = 0
    per_section: dict[str, dict] = {}
    for sec_name, kws in required_by_section.items():
        body = (_find_section_body(sections, sec_name) or "").lower()
        sec_hits = sum(1 for k in kws if k.lower() in body)
        total += len(kws)
        hits += sec_hits
        per_section[sec_name] = {"hits": sec_hits, "total": len(kws)}
    if total == 0:
        return 1.0, {"vacuous": True, "per_section": per_section}
    return hits / total, {"vacuous": False, "hits": hits, "total": total, "per_section": per_section}


def _score_alternatives(tradeoffs_body, must_list_alternatives):
    if not tradeoffs_body:
        return 0.0, {"reason": "no_tradeoffs_section"}
    has_marker = bool(_ALTS_MARKER_RE.search(tradeoffs_body))
    has_escape = bool(_ALTS_ESCAPE_RE.search(tradeoffs_body))
    if has_escape and not must_list_alternatives:
        return 1.0, {"escape_clause": True}
    if not has_marker:
        if has_escape:
            return 1.0, {"escape_clause": True}
        return 0.0, {"marker": False, "escape_clause": False}
    m = _ALTS_MARKER_RE.search(tradeoffs_body)
    tail = tradeoffs_body[m.end():]
    bullets = _BULLET_RE.findall(tail)
    if len(bullets) >= 2:
        return 1.0, {"marker": True, "bullets": len(bullets)}
    if len(bullets) == 1:
        return 0.5, {"marker": True, "bullets": 1}
    return 0.0, {"marker": True, "bullets": 0}


def _score_open_questions(oq_body, expected):
    if oq_body is None:
        return 0.0, {"reason": "no_open_questions_section"}
    body_stripped = oq_body.strip()
    is_none = bool(re.fullmatch(r"(?i)\s*none\.?\s*", body_stripped))
    bullets = _BULLET_RE.findall(oq_body)
    if expected == "none":
        return (1.0, {"expected": "none", "is_none": True}) if is_none else (0.0, {"expected": "none", "is_none": False})
    if expected == "required":
        return (1.0, {"expected": "required", "bullets": len(bullets)}) if bullets else (0.0, {"expected": "required", "bullets": 0})
    if is_none or bullets:
        return 1.0, {"expected": None, "shape_ok": True}
    return 0.5, {"expected": None, "shape_ok": False}


def _score_anti_pattern(text, forbidden):
    if not forbidden:
        return 1.0, {"forbidden_total": 0, "hits": []}
    credit = 1.0
    hits: list[dict] = []
    for entry in forbidden:
        pattern = entry.get("pattern")
        severity = (entry.get("severity") or "major").lower()
        if not pattern:
            continue
        try:
            rgx = re.compile(pattern, re.IGNORECASE)
        except re.error:
            continue
        m = rgx.search(text)
        if m:
            delta = 0.3 if severity == "major" else 0.1
            credit -= delta
            hits.append({"pattern": pattern, "severity": severity, "match": m.group(0)[:120]})
    return max(0.0, credit), {"forbidden_total": len(forbidden), "hits": hits, "credit": max(0.0, credit)}


def score(trace: dict, fixture: dict) -> dict:
    runs = trace.get("runs") or []
    if not runs:
        return {"primary": 0.0, "status": "invalid_format",
                "diagnostic": {"reason": "no_runs"}, "scorer_version": SCORER_VERSION}
    assert len(runs) == 1, "architect_lite.score expects a single-run trace"
    run = runs[0]
    text = run.get("final_text") or ""
    sections = _split_sections(text)
    expected = fixture.get("expected") or {}

    structure_score, missing_sections = _score_structure(sections)
    approach_body = _find_section_body(sections, "approach")
    codebase_body = _find_section_body(sections, "codebase context")
    data_body = _find_section_body(sections, "data model")
    api_body = _find_section_body(sections, "api / interface design")
    impl_body = _find_section_body(sections, "implementation steps")
    tradeoffs_body = _find_section_body(sections, "trade-offs and constraints")
    oq_body = _find_section_body(sections, "open questions")

    approach_lookup = "\n".join([approach_body or "", codebase_body or ""])
    approach_score, approach_diag = _score_approach_commit(
        approach_lookup if approach_body is not None else None,
        expected.get("approach_class"),
    )
    api_score, api_diag = _score_api_fidelity(
        api_body, impl_body,
        list(expected.get("required_api_symbols") or []),
        list(expected.get("required_file_paths") or []),
    )
    kw_score, kw_diag = _score_section_keywords(
        sections, expected.get("required_keywords_by_section") or {},
    )
    alts_score, alts_diag = _score_alternatives(
        tradeoffs_body, bool(expected.get("must_list_alternatives", True)),
    )
    oq_score, oq_diag = _score_open_questions(oq_body, expected.get("open_questions_required"))
    ap_score, ap_diag = _score_anti_pattern(text, list(expected.get("forbidden_patterns") or []))

    primary = (_W_STRUCTURE * structure_score + _W_APPROACH_COMMIT * approach_score
               + _W_API_FIDELITY * api_score + _W_SECTION_KEYWORDS * kw_score
               + _W_ALTERNATIVES * alts_score + _W_OPEN_QUESTIONS * oq_score
               + _W_ANTI_PATTERN * ap_score)
    primary = max(0.0, min(1.0, primary))

    diagnostic: dict[str, Any] = {
        "structure": {"score": round(structure_score, 6), "missing_sections": missing_sections},
        "approach_commit": {"score": round(approach_score, 6), **approach_diag},
        "api_fidelity": {"score": round(api_score, 6), **api_diag},
        "section_keywords": {"score": round(kw_score, 6), **kw_diag},
        "alternatives": {"score": round(alts_score, 6), **alts_diag},
        "open_questions": {"score": round(oq_score, 6), **oq_diag},
        "anti_pattern": {"score": round(ap_score, 6), **ap_diag},
        "sections_seen": sorted(sections.keys()),
        "data_model_present": data_body is not None,
        "scorer_version": SCORER_VERSION,
    }
    status = "ok" if structure_score > 0 else "invalid_format"
    return {"primary": round(primary, 6), "status": status, "diagnostic": diagnostic, "scorer_version": SCORER_VERSION}
