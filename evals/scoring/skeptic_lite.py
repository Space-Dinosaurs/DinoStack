"""
Purpose: Score a single Skeptic run against a labeled fixture by parsing the
         mandated sign-off format from content/agents/skeptic.md and matching
         raised findings to expected findings via case-insensitive keyword
         substrings.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v2"}.

Contract: score() expects a single-run trace - i.e. trace["runs"] contains
          exactly one run record. Aggregation across N runs is the
          aggregator module's job (median/stdev over per-run primaries).
          A multi-run trace is an API-misuse bug, not a recoverable state,
          and the function asserts on it.

Upstream deps: stdlib re.

Downstream consumers: evals.runner.cli (via dynamic import per manifest's
                      scoring_module field).

Failure modes: If the Skeptic sign-off format is absent or malformed, returns
               status="invalid_format" and primary=0.0 without raising. Never
               raises; all errors are surfaced via status/diagnostic.

Performance: standard; regex-based parse of a short text blob.

---

## Scoring formula (v2: bounded FP penalty)

Motivation: v1 (commit eae5fb6) normalized `(TP_credit - FN - FP)` by
`max_achievable = sum of TP weights over expected findings`. For single-
finding fixtures `max_achievable` is tiny (0.5 for a one-Major fixture), so
a handful of false-positive Majors at 0.1 each dwarfed the 0.5 TP credit
and floored the score at 0.0 regardless of whether the TP was caught. v1
could not distinguish a Skeptic that caught the defect + raised 5 FPs from
one that missed the defect entirely.

v2 decouples the recall signal from the FP-noise signal:

    tp_credit  = TP_c*1.0 + TP_m*0.5 + TP_mi*0.25
    max_credit = sum of expected-finding weights (same as v1 max_achievable)
    fn_penalty = FN_c*1.0 + FN_m*0.5 + FN_mi*0.1

    raw_fp     = FP_c*0.3 + FP_m*0.1 + FP_mi*0.05
    fp_cap     = max(max_credit, 1.0) * 0.5
    fp_penalty = min(raw_fp, fp_cap)                  # BOUNDED

    if max_credit > 0:                                # defect fixture
        base    = (tp_credit - fn_penalty) / max_credit
        primary = clip(base - fp_penalty / max(max_credit, 1.0), 0, 1)
    else:                                             # clean fixture
        primary = clip(1.0 - fp_penalty, 0, 1)

    # Sign-off mismatch docks 0.3 (unchanged from v1).

Key property: FPs subtract at most 0.5 (half of `max(max_credit, 1.0)`),
so a Skeptic that catches every expected finding cannot fall below ~0.5
from FP noise alone. FNs, in particular Critical FNs, retain the same
weight as v1 and can still floor the score.

### Worked examples

Let `E` denote expected counts, `R` raised counts. Sign-off always matches.

1. sk-001 shape - single Major expected, caught + FP noise.
   E = {C:0, M:1, Mi:0}, R = {C:0, M:6, Mi:0}. TP_m=1, FN=0, FP_m=5.
   max_credit = 0.5, tp_credit = 0.5, fn_penalty = 0.
   raw_fp = 0.5, fp_cap = max(0.5,1.0)*0.5 = 0.5, fp_penalty = 0.5.
   base = 1.0, primary = 1.0 - 0.5/1.0 = 0.5.
   (v1: raw = 0.5 - 0.5 = 0.0, primary = 0.0. Floor removed.)

2. sk-002 shape - single Critical expected, caught + FP noise.
   E = {C:1}, R = {C:2, M:2}. TP_c=1, FN=0, FP_c=1, FP_m=2.
   max_credit = 1.0, tp_credit = 1.0, fn_penalty = 0.
   raw_fp = 0.3 + 0.2 = 0.5, fp_cap = 0.5, fp_penalty = 0.5.
   base = 1.0, primary = 1.0 - 0.5/1.0 = 0.5.
   Heavier FP noise (R={C:4, M:4}): raw_fp = 0.9 + 0.2 = 1.1, clamped
   to 0.5, primary still 0.5.

3. sk-003 shape - clean fixture.
   E = {}, R = {}. max_credit = 0, raw_fp = 0, primary = 1.0.
   If R = {M:2} (spurious): raw_fp = 0.2, fp_cap = 0.5, primary = 0.8.

4. sk-004 shape - Critical + Minor expected, caught with FP noise.
   E = {C:1, Mi:1}, R = {C:4, M:2, Mi:1}. TP_c=1, TP_mi=1, FP_c=3, FP_m=2.
   max_credit = 1.25, tp_credit = 1.25, fn_penalty = 0.
   raw_fp = 0.9 + 0.2 = 1.1, fp_cap = max(1.25,1.0)*0.5 = 0.625,
   fp_penalty = 0.625.
   base = 1.0, primary = 1.0 - 0.625/1.25 = 0.5.
   Missed the Minor (TP_mi=0, FN_mi=1): tp_credit = 1.0, fn_penalty = 0.1,
   base = 0.9/1.25 = 0.72, primary = 0.72 - 0.5 = 0.22.

5. sk-005 shape - single Major expected, caught cleanly.
   E = {M:1}, R = {M:2}. TP_m=1, FP_m=1.
   raw_fp = 0.1, fp_cap = 0.5, fp_penalty = 0.1.
   base = 1.0, primary = 1.0 - 0.1/1.0 = 0.9.
   (v1 was 0.8 here; v2 is slightly kinder to a single-FP case.)

6. Critical miss - still floors.
   E = {C:1}, R = {}. TP_c=0, FN_c=1, FP=0.
   base = -1.0/1.0 = -1.0, primary = clip(-1.0, 0, 1) = 0.0.

7. Perfect run.
   E = {C:1, M:1}, R = {C:1, M:1}. tp_credit = 1.5, fn_penalty = 0,
   fp_penalty = 0, max_credit = 1.5, base = 1.0, primary = 1.0.
"""
from __future__ import annotations

import re
from typing import Any

SCORER_VERSION = "v2"


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
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {"reason": "no_runs"},
            "scorer_version": SCORER_VERSION,
        }
    assert len(runs) == 1, (
        "skeptic_lite.score expects a single-run trace; aggregation across N runs "
        "happens in evals.runner.aggregator, not here."
    )

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
            "scorer_version": SCORER_VERSION,
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
    tp_mi, fn_mi, _ = _match_expected(raised_mi, exp_mi)

    fp_c = max(0, len(raised_c) - tp_c)
    fp_m = max(0, len(raised_m) - tp_m)
    fp_mi = max(0, len(raised_mi) - tp_mi)

    # v2 formula: bounded FP penalty. See module docstring for derivation.
    tp_credit = tp_c * 1.0 + tp_m * 0.5 + tp_mi * 0.25
    max_credit = len(exp_c) * 1.0 + len(exp_m) * 0.5 + len(exp_mi) * 0.25
    fn_penalty = fn_c * 1.0 + fn_m * 0.5 + fn_mi * 0.1

    raw_fp = fp_c * 0.3 + fp_m * 0.1 + fp_mi * 0.05
    fp_cap = max(max_credit, 1.0) * 0.5
    fp_penalty = min(raw_fp, fp_cap)

    clean_case = (len(exp_c) + len(exp_m) + len(exp_mi)) == 0
    expected_signoff = bool(fixture.get("expected_signoff_granted", False))

    if clean_case:
        # Clean fixture: no expected findings. Start at 1.0 and subtract the
        # bounded FP penalty. Any FPs on a clean fixture are the whole story.
        primary = 1.0 - fp_penalty
    else:
        base = (tp_credit - fn_penalty) / max_credit
        primary = base - fp_penalty / max(max_credit, 1.0)

    primary = max(0.0, min(1.0, primary))

    # Sign-off mismatch penalty (docks 0.3 off primary, then clip). Unchanged
    # from v1 - the sign-off decision is a separate axis from finding quality.
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
        "scorer_version": SCORER_VERSION,
        "score_components": {
            "tp_credit": round(tp_credit, 6),
            "max_credit": round(max_credit, 6),
            "fn_penalty": round(fn_penalty, 6),
            "raw_fp": round(raw_fp, 6),
            "fp_cap": round(fp_cap, 6),
            "fp_penalty": round(fp_penalty, 6),
        },
    }
    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
