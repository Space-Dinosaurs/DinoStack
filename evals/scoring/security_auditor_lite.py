"""
Purpose: Score a single security-auditor run against a labeled fixture by
         parsing the mandated Security Audit output format from
         content/agents/security-auditor.md and matching raised findings to
         expected findings via severity + keyword substrings, with auxiliary
         credit for CWE citations, file:line locations, remediation keywords,
         OWASP coverage, and a tiered sign-off dimension.

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

Failure modes: If the Security Audit header and fewer than 3 of the severity
               sub-sections parse, returns status="invalid_format" and
               primary=0.0 without raising. Never raises; all errors are
               surfaced via status/diagnostic.

Performance: standard; regex-based parse of a short markdown blob.

---

## Scoring formula (v1)

Motivation: the security-auditor's value is adversarial threat-model coverage
with every finding citing a specific location and a named vulnerability
class. Six dimensions capture that value, weighted by how load-bearing each
is for downstream use (engineer writing remediation PRs + architect
review):

    w_correctness    = 0.50   (TP/FN/FP by severity, bounded FP)
    w_cwe_citation   = 0.15   (fraction of TPs naming a CWE-NN identifier)
    w_line_cite      = 0.10   (fraction of TPs citing file:line)
    w_remediation    = 0.10   (fraction of TPs with remediation keywords)
    w_owasp_coverage = 0.10   (fraction of required OWASP categories covered)
    w_signoff        = 0.05   (tiered: no-finding Critical float vs match)

Weights sum to 1.0 exactly; runtime assertion guards future edits.

### Correctness (w_correctness = 0.50)

Severity weights (TP credit):
    Critical: 1.0, High: 0.6, Medium: 0.3, Informational: 0.1

FN penalty weights (miss cost):
    Critical: 1.0, High: 0.5, Medium: 0.2, Informational: 0.05

Bounded FP penalty (same shape as skeptic v2):
    raw_fp      = FP_crit * 0.3 + FP_high * 0.15 + FP_med * 0.05 +
                  FP_info * 0.02
    fp_cap      = max(max_credit, 1.0) * 0.5
    fp_penalty  = min(raw_fp, fp_cap)

    if max_credit > 0:
        base       = (tp_credit - fn_penalty) / max_credit
        correctness = clip(base - fp_penalty / max(max_credit, 1.0), 0, 1)
    else:  # clean fixture
        correctness = clip(1.0 - fp_penalty, 0, 1)

Rationale for bounded FP: per LEARNINGS "Scoring-function floors and
ceilings" - a security-auditor that catches every expected TP must not be
floored to 0 by FP noise alone. The cap guarantees a TP-complete run
cannot score below ~0.5 on correctness regardless of FP count. FNs on
Critical findings still floor the score, which is the correct failure
signal for this component.

### Per-TP axes (vacuous when no TPs)

For each of cwe_citation / line_cite / remediation the per-TP credit is
averaged over the set of matched TPs. If a fixture has no expected
findings, or zero TPs were matched, the axis scores 1.0 (vacuous; no
weight renormalization, per init_project_lite v3 precedent).

- cwe_citation: for each matched TP, credit 1.0 if the raised finding's
  text contains a `CWE-<digits>` token (case-insensitive); else 0.0.
- line_cite: credit 1.0 if the raised finding's text contains a
  `<filename>.<ext>:<digits>` token (or `line <digits>` following the
  file name in the same sentence); else 0.5 if file name alone appears;
  else 0.0.
- remediation: credit 1.0 if the raised finding's text contains any of
  the fixture-declared `remediation_keywords` (case-insensitive
  substring) OR, if the fixture does not declare per-finding keywords,
  any of the generic remediation verbs (parameterize, sanitize, escape,
  allowlist, denylist, validate, encrypt, hash, rotate, authenticate,
  authorize, revoke); else 0.0.

### OWASP coverage (w_owasp_coverage = 0.10)

Fixture declares `expected_owasp_categories` (e.g. ["A01", "A03"]). The
### OWASP Top 10 coverage section must reference each expected category
(case-insensitive substring of the bare code, e.g. "A01" or "A03") -
credit is fraction hit. Vacuous (1.0) if the fixture declares none.

### Sign-off (w_signoff = 0.05, tiered)

The Security Audit output has no literal sign-off line (unlike Skeptic),
but the Critical findings section and Dependency scan section together
act as a go/no-go. This axis checks consistency:

- If fixture.expected_has_critical is True: the Critical findings section
  must NOT be the sentinel "None" (credit 1.0). If "None" is emitted
  against a fixture that expects a Critical, credit 0.0.
- If fixture.expected_has_critical is False: credit 1.0 regardless
  (vacuous on this dimension; clean fixtures do not double-penalize).
- Tiered: if the observed Critical section lists at least one finding
  but no expected Critical TP was matched, credit 0.5 (the auditor
  flagged something Critical-ish that didn't align with the expected
  TP - partial credit because the audit is not silent, but the shape
  is off).

### Version history

v1 (this commit): initial scorer. Six dimensions, bounded FP penalty on
    correctness, vacuous-axis handling on per-TP axes for clean
    fixtures, tiered sign-off. Shape is defensible independent of
    fixture choice.
"""
from __future__ import annotations

import re
from typing import Any

SCORER_VERSION = "v1"

_W_CORRECTNESS = 0.50
_W_CWE_CITATION = 0.15
_W_LINE_CITE = 0.10
_W_REMEDIATION = 0.10
_W_OWASP_COVERAGE = 0.10
_W_SIGNOFF = 0.05

_WEIGHTS_SUM_ASSERTION = abs(
    (
        _W_CORRECTNESS
        + _W_CWE_CITATION
        + _W_LINE_CITE
        + _W_REMEDIATION
        + _W_OWASP_COVERAGE
        + _W_SIGNOFF
    )
    - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "security_auditor_lite weights must sum to 1.0"

# Severity labels emitted by the agent spec. "Informational" maps to the
# "Informational" section. The spec uses Critical/High/Medium/Informational.
_SEVERITIES = ("critical", "high", "medium", "informational")

_TP_WEIGHTS = {"critical": 1.0, "high": 0.6, "medium": 0.3, "informational": 0.1}
_FN_WEIGHTS = {"critical": 1.0, "high": 0.5, "medium": 0.2, "informational": 0.05}
_FP_WEIGHTS = {"critical": 0.3, "high": 0.15, "medium": 0.05, "informational": 0.02}

_GENERIC_REMEDIATION_KEYWORDS = (
    "parameteriz",  # parameterize / parameterized
    "sanitiz",
    "escape",
    "allowlist",
    "denylist",
    "allow-list",
    "deny-list",
    "whitelist",
    "blacklist",
    "validat",
    "encrypt",
    "hash",
    "rotate",
    "authenticate",
    "authoriz",
    "revoke",
    "use prepared",
    "prepared statement",
    "bcrypt",
    "argon2",
    "scrypt",
    "csrf token",
    "content security policy",
    "strict-transport",
    "httponly",
    "samesite",
    "secure cookie",
)

_SECURITY_AUDIT_HEADER_RE = re.compile(r"^##\s*Security Audit\b", re.MULTILINE)
_FINDINGS_SECTION_RE = {
    "critical": re.compile(r"^###\s*Critical findings\s*$", re.MULTILINE | re.IGNORECASE),
    "high": re.compile(r"^###\s*High findings\s*$", re.MULTILINE | re.IGNORECASE),
    "medium": re.compile(r"^###\s*Medium findings\s*$", re.MULTILINE | re.IGNORECASE),
    "informational": re.compile(
        r"^###\s*Informational\s*$", re.MULTILINE | re.IGNORECASE
    ),
}
_OWASP_SECTION_RE = re.compile(
    r"^###\s*OWASP Top 10 coverage\s*$", re.MULTILINE | re.IGNORECASE
)

# Match "file.ext:123", "file.ext line 123", or "file.ext:123-456" tokens.
_FILE_LINE_RE = re.compile(
    r"[A-Za-z0-9_./\-]+\.[A-Za-z0-9]{1,6}(?::\d+(?:-\d+)?|\s+line\s+\d+)",
    re.IGNORECASE,
)
_FILE_ONLY_RE = re.compile(r"[A-Za-z0-9_./\-]+\.[A-Za-z0-9]{1,6}")
_CWE_RE = re.compile(r"\bCWE-\d+\b", re.IGNORECASE)


def _section_body(text: str, header_re: re.Pattern[str]) -> str:
    """Return the body of the matched section header up to the next ### or ##
    heading or EOF. Empty string if the heading is not present."""
    m = header_re.search(text)
    if not m:
        return ""
    start = m.end()
    # find the next ## or ### heading after `start`
    next_m = re.search(r"^##+\s", text[start:], re.MULTILINE)
    if next_m:
        return text[start : start + next_m.start()].strip()
    return text[start:].strip()


def _split_findings(section_body: str) -> list[str]:
    """Split a findings-section body into a list of individual finding
    strings. A finding is typically a bullet beginning with '- ' or '* '; if
    no bullets, the body is either the sentinel "None" or a single finding.
    """
    body = section_body.strip()
    if not body:
        return []
    low = body.lower()
    if low in ("none", "none.", "(none)"):
        return []
    # Bullet-based split
    bullets = re.findall(
        r"^[ \t]*[-*]\s+(.+?)(?=^\s*[-*]\s|\Z)",
        body,
        re.DOTALL | re.MULTILINE,
    )
    if bullets:
        return [b.strip() for b in bullets if b.strip()]
    # Fall back: the whole body is one finding if it isn't empty/None.
    return [body]


def _parse_audit(text: str) -> dict:
    has_header = bool(_SECURITY_AUDIT_HEADER_RE.search(text))
    sections: dict[str, list[str]] = {}
    sections_present: dict[str, bool] = {}
    for sev, rx in _FINDINGS_SECTION_RE.items():
        present = bool(rx.search(text))
        sections_present[sev] = present
        body = _section_body(text, rx)
        sections[sev] = _split_findings(body)
    owasp_body = _section_body(text, _OWASP_SECTION_RE)
    # Format gate: header + at least 3 of the 4 severity sections present.
    severity_section_hits = sum(1 for v in sections_present.values() if v)
    format_valid = has_header and severity_section_hits >= 3
    return {
        "format_valid": format_valid,
        "has_header": has_header,
        "severity_section_hits": severity_section_hits,
        "findings": sections,
        "owasp_body": owasp_body,
    }


def _match_expected(
    raised: list[str], expected: list[dict]
) -> tuple[int, list[tuple[dict, str]], list[int]]:
    """Return (tp, matched_pairs, matched_raised_indices).

    matched_pairs: list of (expected_entry, matched_raised_text) for each TP.
    A raised finding matches an expected entry if every keyword appears
    (case-insensitive substring) in the raised text, OR a CWE id declared
    in the expected entry appears verbatim in the raised text. Each
    expected entry consumes at most one raised.
    """
    matched_raised: set[int] = set()
    tp = 0
    pairs: list[tuple[dict, str]] = []
    for exp in expected:
        kws = [kw.lower() for kw in exp.get("keywords", []) if kw]
        cwe = (exp.get("cwe") or "").lower()
        for i, r in enumerate(raised):
            if i in matched_raised:
                continue
            rl = r.lower()
            kw_hit = bool(kws) and all(kw in rl for kw in kws)
            cwe_hit = bool(cwe) and cwe in rl
            if kw_hit or cwe_hit:
                matched_raised.add(i)
                tp += 1
                pairs.append((exp, r))
                break
    return tp, pairs, sorted(matched_raised)


def _score_per_tp_axis(
    matched_pairs: list[tuple[dict, str]],
    axis: str,
) -> tuple[float, dict]:
    """Generic per-TP axis scorer. `axis` in {'cwe', 'line_cite',
    'remediation'}. If no TPs, the axis is vacuous (1.0)."""
    if not matched_pairs:
        return 1.0, {"vacuous": True, "hits": 0, "total": 0, "per_tp": []}
    hits = 0.0
    per_tp: list[dict] = []
    for exp, raised_text in matched_pairs:
        rl = raised_text
        credit = 0.0
        if axis == "cwe":
            credit = 1.0 if _CWE_RE.search(rl) else 0.0
        elif axis == "line_cite":
            if _FILE_LINE_RE.search(rl):
                credit = 1.0
            elif _FILE_ONLY_RE.search(rl):
                credit = 0.5
            else:
                credit = 0.0
        elif axis == "remediation":
            kws = [kw.lower() for kw in (exp.get("remediation_keywords") or [])]
            low = rl.lower()
            if kws:
                credit = 1.0 if any(k in low for k in kws) else 0.0
            else:
                credit = 1.0 if any(k in low for k in _GENERIC_REMEDIATION_KEYWORDS) else 0.0
        hits += credit
        per_tp.append({"expected_id": exp.get("id"), "credit": credit})
    return hits / len(matched_pairs), {
        "vacuous": False,
        "hits": round(hits, 6),
        "total": len(matched_pairs),
        "per_tp": per_tp,
    }


def _score_owasp(owasp_body: str, expected_categories: list[str]) -> tuple[float, dict]:
    if not expected_categories:
        return 1.0, {"vacuous": True, "hits": 0, "total": 0, "missing": []}
    body = owasp_body or ""
    low = body.lower()
    hits = 0
    missing: list[str] = []
    for cat in expected_categories:
        if cat.lower() in low:
            hits += 1
        else:
            missing.append(cat)
    return hits / len(expected_categories), {
        "vacuous": False,
        "hits": hits,
        "total": len(expected_categories),
        "missing": missing,
    }


def _score_signoff(
    parsed: dict,
    expected_has_critical: bool,
    tp_critical: int,
) -> tuple[float, dict]:
    critical_findings = parsed["findings"]["critical"]
    critical_nonempty = len(critical_findings) > 0
    detail: dict[str, Any] = {
        "expected_has_critical": expected_has_critical,
        "critical_nonempty": critical_nonempty,
        "tp_critical": tp_critical,
    }
    if not expected_has_critical:
        # Clean/below-ceiling fixtures: signoff vacuous on this dimension.
        detail["vacuous"] = True
        return 1.0, detail
    detail["vacuous"] = False
    if critical_nonempty and tp_critical >= 1:
        return 1.0, detail
    if critical_nonempty and tp_critical == 0:
        # Auditor is not silent but the flagged critical doesn't align with
        # the expected TP: tiered partial credit.
        return 0.5, detail
    return 0.0, detail


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
        "security_auditor_lite.score expects a single-run trace; aggregation "
        "across N runs happens in evals.runner.aggregator, not here."
    )

    run = runs[0]
    text = run.get("final_text") or ""
    parsed = _parse_audit(text)

    if not parsed["format_valid"]:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "security_audit_format_not_detected",
                "has_header": parsed["has_header"],
                "severity_section_hits": parsed["severity_section_hits"],
                "final_text_preview": text[:600],
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }

    expected_block = fixture.get("expected_findings") or {}
    if not isinstance(expected_block, dict):
        expected_block = {}

    exp_by_sev: dict[str, list[dict]] = {}
    for sev in _SEVERITIES:
        entries = expected_block.get(sev) or []
        if not isinstance(entries, list):
            entries = []
        exp_by_sev[sev] = [e for e in entries if isinstance(e, dict)]

    raised_by_sev = parsed["findings"]
    tp_counts: dict[str, int] = {}
    fn_counts: dict[str, int] = {}
    fp_counts: dict[str, int] = {}
    all_matched_pairs: list[tuple[dict, str]] = []

    for sev in _SEVERITIES:
        tp, pairs, matched_idx = _match_expected(raised_by_sev[sev], exp_by_sev[sev])
        tp_counts[sev] = tp
        fn_counts[sev] = max(0, len(exp_by_sev[sev]) - tp)
        fp_counts[sev] = max(0, len(raised_by_sev[sev]) - tp)
        all_matched_pairs.extend(pairs)

    tp_credit = sum(tp_counts[s] * _TP_WEIGHTS[s] for s in _SEVERITIES)
    max_credit = sum(len(exp_by_sev[s]) * _TP_WEIGHTS[s] for s in _SEVERITIES)
    fn_penalty = sum(fn_counts[s] * _FN_WEIGHTS[s] for s in _SEVERITIES)
    raw_fp = sum(fp_counts[s] * _FP_WEIGHTS[s] for s in _SEVERITIES)
    fp_cap = max(max_credit, 1.0) * 0.5
    fp_penalty = min(raw_fp, fp_cap)

    clean_case = max_credit == 0.0
    if clean_case:
        correctness = 1.0 - fp_penalty
    else:
        base = (tp_credit - fn_penalty) / max_credit
        correctness = base - fp_penalty / max(max_credit, 1.0)
    correctness = max(0.0, min(1.0, correctness))

    cwe_credit, cwe_detail = _score_per_tp_axis(all_matched_pairs, "cwe")
    line_credit, line_detail = _score_per_tp_axis(all_matched_pairs, "line_cite")
    rem_credit, rem_detail = _score_per_tp_axis(all_matched_pairs, "remediation")

    owasp_expected = list(fixture.get("expected_owasp_categories") or [])
    owasp_credit, owasp_detail = _score_owasp(parsed["owasp_body"], owasp_expected)

    expected_has_critical = bool(fixture.get("expected_has_critical", False))
    signoff_credit, signoff_detail = _score_signoff(
        parsed, expected_has_critical, tp_counts["critical"]
    )

    primary_raw = (
        _W_CORRECTNESS * correctness
        + _W_CWE_CITATION * cwe_credit
        + _W_LINE_CITE * line_credit
        + _W_REMEDIATION * rem_credit
        + _W_OWASP_COVERAGE * owasp_credit
        + _W_SIGNOFF * signoff_credit
    )
    primary = max(0.0, min(1.0, primary_raw))

    diagnostic: dict[str, Any] = {
        "correctness": {
            "credit": round(correctness, 6),
            "tp": tp_counts,
            "fn": fn_counts,
            "fp": fp_counts,
            "raised_counts": {s: len(raised_by_sev[s]) for s in _SEVERITIES},
            "expected_counts": {s: len(exp_by_sev[s]) for s in _SEVERITIES},
            "score_components": {
                "tp_credit": round(tp_credit, 6),
                "max_credit": round(max_credit, 6),
                "fn_penalty": round(fn_penalty, 6),
                "raw_fp": round(raw_fp, 6),
                "fp_cap": round(fp_cap, 6),
                "fp_penalty": round(fp_penalty, 6),
            },
            "clean_case": clean_case,
        },
        "cwe_citation": {"credit": round(cwe_credit, 6), **cwe_detail},
        "line_cite": {"credit": round(line_credit, 6), **line_detail},
        "remediation": {"credit": round(rem_credit, 6), **rem_detail},
        "owasp_coverage": {"credit": round(owasp_credit, 6), **owasp_detail},
        "signoff": {"credit": round(signoff_credit, 6), **signoff_detail},
        "weights": {
            "correctness": _W_CORRECTNESS,
            "cwe_citation": _W_CWE_CITATION,
            "line_cite": _W_LINE_CITE,
            "remediation": _W_REMEDIATION,
            "owasp_coverage": _W_OWASP_COVERAGE,
            "signoff": _W_SIGNOFF,
        },
        "scorer_version": SCORER_VERSION,
    }
    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
