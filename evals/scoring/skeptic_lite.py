"""
Purpose: Score a single Skeptic run against a labeled fixture by parsing the
         mandated sign-off format from content/agents/skeptic.md and matching
         raised findings to expected findings via case-insensitive keyword
         substrings.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format"}.

Upstream deps: stdlib re.

Downstream consumers: evals.runner.cli (via dynamic import per manifest's
                      scoring_module field).

Failure modes: If the Skeptic sign-off format is absent or malformed, returns
               status="invalid_format" and primary=0.0 without raising. Never
               raises; all errors are surfaced via status/diagnostic.

Performance: standard; regex-based parse of a short text blob.
"""
from __future__ import annotations

import re
from typing import Any


_SIGNOFF_GRANTED_RE = re.compile(
    r"No unresolved Critical or Major findings\.\s*Sign-off granted\.",
    re.IGNORECASE,
)
_SIGNOFF_WITHHELD_RE = re.compile(r"Sign-off withheld\.", re.IGNORECASE)
_ACTIVE_SEARCH_RE = re.compile(r"Active search:", re.IGNORECASE)
_FINDINGS_HEADER_RE = re.compile(
    r"Findings:\s*Critical:\s*(\d+)\s*,\s*Major:\s*(\d+)\s*,\s*Minor:\s*(\d+)",
    re.IGNORECASE,
)
_NO_FINDINGS_RE = re.compile(
    r'Findings:\s*(?:"?No findings\.?"?)',
    re.IGNORECASE,
)

# A finding line looks like e.g.
#   "Major - Missing module manifest header on src/x.py (lines 1-80)"
#   "CRITICAL: path traversal in handle_upload()"
_FINDING_LINE_RE = re.compile(
    r"^\s*[-*]?\s*(Critical|Major|Minor)\b\s*[:\-\u2013\u2014]\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)


def _parse_signoff(text: str) -> dict:
    has_active = bool(_ACTIVE_SEARCH_RE.search(text))
    granted = bool(_SIGNOFF_GRANTED_RE.search(text))
    withheld = bool(_SIGNOFF_WITHHELD_RE.search(text))
    header = _FINDINGS_HEADER_RE.search(text)
    no_findings = bool(_NO_FINDINGS_RE.search(text))

    format_valid = has_active and (granted or withheld) and (bool(header) or no_findings)

    counts = {"critical": 0, "major": 0, "minor": 0}
    if header:
        counts = {
            "critical": int(header.group(1)),
            "major": int(header.group(2)),
            "minor": int(header.group(3)),
        }

    findings_by_sev: dict[str, list[str]] = {"critical": [], "major": [], "minor": []}
    for m in _FINDING_LINE_RE.finditer(text):
        sev = m.group(1).lower()
        desc = m.group(2).strip()
        # Skip the "Findings: Critical: N, Major: N, Minor: N" summary line.
        if desc[:1].isdigit() and "," in desc[:20]:
            continue
        findings_by_sev[sev].append(desc)

    return {
        "format_valid": format_valid,
        "has_active_search": has_active,
        "signoff_granted": granted and not withheld,
        "signoff_withheld": withheld,
        "counts": counts,
        "findings": findings_by_sev,
    }


def _match_expected(raised: list[str], expected: list[dict]) -> tuple[int, int, list[str]]:
    """Return (true_positives, false_negatives, matched_raised_descs).

    A raised finding matches an expected entry if, for that expected entry, every
    keyword appears (case-insensitive substring) in the raised description, OR any
    category-name token appears. Each expected entry consumes at most one raised.
    """
    matched_raised: set[int] = set()
    tp = 0
    matched_descs: list[str] = []
    for exp in expected:
        kws = [kw.lower() for kw in exp.get("keywords", []) if kw]
        category = (exp.get("category") or "").lower()
        for i, r in enumerate(raised):
            if i in matched_raised:
                continue
            rl = r.lower()
            kw_hit = kws and all(kw in rl for kw in kws)
            cat_hit = category and category in rl
            if kw_hit or cat_hit:
                matched_raised.add(i)
                tp += 1
                matched_descs.append(r)
                break
    fn = len(expected) - tp
    return tp, fn, matched_descs


def score(trace: dict, fixture: dict) -> dict:
    runs = trace.get("runs") or []
    if not runs:
        return {"primary": 0.0, "status": "invalid_format", "diagnostic": {"reason": "no_runs"}}

    run = runs[0]
    text = run.get("final_text") or ""
    parsed = _parse_signoff(text)

    if not parsed["format_valid"]:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "signoff_format_not_detected",
                "has_active_search": parsed["has_active_search"],
                "signoff_granted": parsed["signoff_granted"],
                "signoff_withheld": parsed["signoff_withheld"],
                "final_text_preview": text[:600],
            },
        }

    expected = fixture.get("expected_findings", {}) or {}
    exp_c = expected.get("critical") or []
    exp_m = expected.get("major") or []
    exp_mi = expected.get("minor") or []

    raised_c = parsed["findings"]["critical"]
    raised_m = parsed["findings"]["major"]
    raised_mi = parsed["findings"]["minor"]

    tp_c, fn_c, _ = _match_expected(raised_c, exp_c)
    tp_m, fn_m, _ = _match_expected(raised_m, exp_m)
    tp_mi, fn_mi, matched_mi = _match_expected(raised_mi, exp_mi)

    fp_c = max(0, len(raised_c) - tp_c)
    fp_m = max(0, len(raised_m) - tp_m)
    fp_mi = max(0, len(raised_mi) - tp_mi)

    raw = (
        tp_c * 1.0 + tp_m * 0.5 + tp_mi * 0.25
        - fn_c * 1.0 - fn_m * 0.5 - fn_mi * 0.1
        - fp_c * 0.3 - fp_m * 0.1 - fp_mi * 0.05
    )
    max_achievable = len(exp_c) * 1.0 + len(exp_m) * 0.5 + len(exp_mi) * 0.25

    clean_case = (len(exp_c) + len(exp_m) + len(exp_mi)) == 0
    expected_signoff = bool(fixture.get("expected_signoff_granted", False))

    if clean_case:
        # Clean fixture: no expected findings. Primary starts at 1.0 and is
        # docked by false positives, clipped to [0, 1].
        primary = 1.0 - (fp_c * 0.3 + fp_m * 0.1 + fp_mi * 0.05)
        primary = max(0.0, min(1.0, primary))
    else:
        if max_achievable > 0:
            primary = raw / max_achievable
        else:
            primary = 0.0
        primary = max(0.0, min(1.0, primary))

    # Sign-off mismatch penalty (docks 0.3 off primary, then clip).
    signoff_match = parsed["signoff_granted"] == expected_signoff
    if not signoff_match:
        primary = max(0.0, primary - 0.3)

    diagnostic: dict[str, Any] = {
        "tp": {"critical": tp_c, "major": tp_m, "minor": tp_mi},
        "fn": {"critical": fn_c, "major": fn_m, "minor": fn_mi},
        "fp": {"critical": fp_c, "major": fp_m, "minor": fp_mi},
        "raised_counts": {
            "critical": len(raised_c),
            "major": len(raised_m),
            "minor": len(raised_mi),
        },
        "expected_counts": {
            "critical": len(exp_c),
            "major": len(exp_m),
            "minor": len(exp_mi),
        },
        "signoff_granted": parsed["signoff_granted"],
        "signoff_expected": expected_signoff,
        "signoff_match": signoff_match,
        "format_valid": parsed["format_valid"],
        "clean_case": clean_case,
    }
    return {"primary": round(primary, 6), "status": "ok", "diagnostic": diagnostic}
