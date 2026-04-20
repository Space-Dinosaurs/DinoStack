"""
Purpose: Score a single qa-engineer run against a labeled fixture by parsing
         the structured QA Verification Report format mandated by
         content/agents/qa-engineer.md (## Result: PASS|FAIL|PARTIAL|BLOCKED
         header, numbered ### N. Criterion blocks with Result/Method/Evidence/
         Expected/Actual/Location fields), and combining five weighted
         dimensions.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace (trace["runs"] has one run
          record). Aggregation across N runs is the aggregator module's
          job. A multi-run trace is API misuse and asserts.

Upstream deps: stdlib re.

Downstream consumers: evals.runner.cli (dynamic import per manifest's
                      scoring_module field).

Failure modes: if the structured report cannot be parsed at all (no
               ## Result header or no numbered ### N. blocks), returns
               status="invalid_format", primary=0.0. Never raises.

Performance: standard; regex-based parse of a short text blob.

---

## Scoring formula (v1)

Five weighted dimensions. Weights sum to exactly 1.0 (runtime assertion).

    w_verdict       = 0.30  (exact verdict match -> 1.0;
                             PARTIAL <-> PASS -> 0.4;
                             BLOCKED when non-BLOCKED expected -> 0.2;
                             polar mismatch FAIL <-> PASS -> 0.0;
                             other pairings follow same table)
    w_per_criterion = 0.25  (fraction of expected AC results matching
                             the raised per-AC Result token; vacuous ->
                             1.0 if no expected per-criterion labels)
    w_evidence      = 0.20  (TIERED per AC: keyword or file:line or @eN
                             element-ref or class-token match -> 1.0;
                             non-empty Evidence field that does not match
                             any specific marker -> 0.5; empty -> 0.0;
                             averaged across ACs that appeared in the
                             report; vacuous -> 1.0 if no ACs parsed)
    w_fallback      = 0.15  (for each AC flagged runtime_required in the
                             fixture, credit 1.0 unless it was both
                             marked source-verified AND not
                             SKIPPED / SKIPPED-BLOCKED; vacuous -> 1.0
                             if no runtime_required ACs)
    w_blocking      = 0.10  (fraction of expected blocking-issue keyword
                             hits in the "## Blocking Issues" section;
                             vacuous -> 1.0 if none expected)

Verdict match matrix (raised x expected):

             PASS    FAIL    PARTIAL  BLOCKED
    PASS     1.0     0.0     0.4      0.2
    FAIL     0.0     1.0     0.4      0.2
    PARTIAL  0.4     0.4     1.0      0.2
    BLOCKED  0.2     0.2     0.2      1.0
"""
from __future__ import annotations

import re
from typing import Any

SCORER_VERSION = "v1"

_W_VERDICT = 0.30
_W_PER_CRITERION = 0.25
_W_EVIDENCE = 0.20
_W_FALLBACK = 0.15
_W_BLOCKING = 0.10

assert abs((_W_VERDICT + _W_PER_CRITERION + _W_EVIDENCE + _W_FALLBACK + _W_BLOCKING) - 1.0) < 1e-9, (
    "qa_engineer_lite weights must sum to 1.0"
)

_VERDICT_MATRIX: dict[str, dict[str, float]] = {
    "PASS":    {"PASS": 1.0, "FAIL": 0.0, "PARTIAL": 0.4, "BLOCKED": 0.2},
    "FAIL":    {"PASS": 0.0, "FAIL": 1.0, "PARTIAL": 0.4, "BLOCKED": 0.2},
    "PARTIAL": {"PASS": 0.4, "FAIL": 0.4, "PARTIAL": 1.0, "BLOCKED": 0.2},
    "BLOCKED": {"PASS": 0.2, "FAIL": 0.2, "PARTIAL": 0.2, "BLOCKED": 1.0},
}

_RESULT_HEADER_RE = re.compile(
    r"^##\s*Result:\s*(PASS|FAIL|PARTIAL|BLOCKED)\b",
    re.IGNORECASE | re.MULTILINE,
)

_AC_BLOCK_RE = re.compile(
    r"^###\s+(\d+)\.\s*(.+?)\n(.*?)(?=^###\s+\d+\.|^##\s+|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)

_AC_FIELD_RE = {
    "result": re.compile(
        r"\*\*Result:\*\*\s*(PASS|FAIL|SKIPPED(?:-BLOCKED)?)\b",
        re.IGNORECASE,
    ),
    "method": re.compile(
        r"\*\*Method:\*\*\s*([^\n]+)",
        re.IGNORECASE,
    ),
    "evidence": re.compile(
        r"\*\*Evidence:\*\*\s*([^\n]+(?:\n(?!\s*\*\*)[^\n]+)*)",
        re.IGNORECASE,
    ),
}

_BLOCKING_SECTION_RE = re.compile(
    r"##\s*Blocking Issues\s*\n(.*?)(?=^##\s+|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)

_FILE_LINE_RE = re.compile(r"\b[\w./-]+\.\w+:\d+")
_ELEMENT_REF_RE = re.compile(r"@e\d+")
_CLASS_TOKEN_RE = re.compile(r"\b(?:bg|text|border|ring|from|to)-[a-z]+-\d+\b")
_SCREENSHOT_RE = re.compile(r"(?:/tmp/qa_[\w.-]+\.png|\.png\b)", re.IGNORECASE)


def _parse_report(text: str) -> dict:
    m = _RESULT_HEADER_RE.search(text or "")
    verdict = m.group(1).upper() if m else None

    acs: list[dict] = []
    for block in _AC_BLOCK_RE.finditer(text or ""):
        num = int(block.group(1))
        title = block.group(2).strip()
        body = block.group(3) or ""
        fields: dict[str, str] = {}
        for key, rex in _AC_FIELD_RE.items():
            fm = rex.search(body)
            if fm:
                fields[key] = fm.group(1).strip()
        acs.append(
            {
                "id": num,
                "title": title,
                "body": body,
                "result": fields.get("result", "").upper() or None,
                "method": (fields.get("method") or "").lower() or None,
                "evidence": fields.get("evidence", "").strip(),
            }
        )

    bm = _BLOCKING_SECTION_RE.search(text or "")
    blocking_text = bm.group(1) if bm else ""

    return {
        "verdict": verdict,
        "acs": acs,
        "blocking_text": blocking_text,
        "format_valid": bool(verdict) and bool(acs),
    }


def _is_specific_evidence(evidence: str, keywords: list[str]) -> bool:
    if not evidence:
        return False
    e_lower = evidence.lower()
    for kw in keywords or []:
        if kw and kw.lower() in e_lower:
            return True
    if _FILE_LINE_RE.search(evidence):
        return True
    if _ELEMENT_REF_RE.search(evidence):
        return True
    if _CLASS_TOKEN_RE.search(evidence):
        return True
    if _SCREENSHOT_RE.search(evidence):
        return True
    return False


def _is_source_verified(method: str | None) -> bool:
    if not method:
        return False
    m = method.lower()
    return "source-verified" in m or "source-fallback" in m or "source verified" in m


def _is_skipped(result: str | None) -> bool:
    if not result:
        return False
    return result.upper().startswith("SKIPPED")


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
        "qa_engineer_lite.score expects a single-run trace; aggregation across "
        "N runs happens in evals.runner.aggregator, not here."
    )

    run = runs[0]
    text = run.get("final_text") or ""
    parsed = _parse_report(text)

    if not parsed["format_valid"]:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "qa_report_format_not_detected",
                "verdict_found": parsed["verdict"],
                "ac_count": len(parsed["acs"]),
                "final_text_preview": text[:600],
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }

    expected = (fixture or {}).get("expected") or {}
    expected_verdict = (expected.get("verdict") or "").upper() or None
    expected_per_criterion = expected.get("per_criterion") or []
    evidence_keywords_by_ac = {
        int(e.get("id")): list(e.get("keywords") or [])
        for e in (expected.get("evidence_keywords") or [])
    }
    expected_blocking_kws = list(expected.get("expected_blocking_issues") or [])

    inputs = (fixture or {}).get("inputs") or {}
    acs_input = inputs.get("acceptance_criteria") or []
    runtime_required_ids = {
        int(a.get("id")) for a in acs_input if a.get("runtime_required")
    }

    raised_v = parsed["verdict"]
    if expected_verdict is None:
        verdict_credit = 1.0
        verdict_detail = {"vacuous": True, "raised": raised_v}
    else:
        row = _VERDICT_MATRIX.get(raised_v or "", {})
        verdict_credit = row.get(expected_verdict, 0.0)
        verdict_detail = {
            "vacuous": False,
            "raised": raised_v,
            "expected": expected_verdict,
            "credit": verdict_credit,
        }

    raised_by_id = {ac["id"]: ac for ac in parsed["acs"]}
    if not expected_per_criterion:
        per_crit_credit = 1.0
        per_crit_detail = {"vacuous": True}
    else:
        hits = 0
        total = 0
        per_crit_rows: list[dict] = []
        for exp in expected_per_criterion:
            try:
                aid = int(exp.get("id"))
            except (TypeError, ValueError):
                continue
            expected_result = (exp.get("result") or "").upper()
            raised = raised_by_id.get(aid)
            raised_result = (raised or {}).get("result") or ""
            rr_norm = "SKIPPED" if raised_result.startswith("SKIPPED") else raised_result
            er_norm = "SKIPPED" if expected_result.startswith("SKIPPED") else expected_result
            match = rr_norm == er_norm and rr_norm != ""
            if match:
                hits += 1
            total += 1
            per_crit_rows.append(
                {"id": aid, "expected": expected_result, "raised": raised_result, "match": match}
            )
        per_crit_credit = hits / total if total else 1.0
        per_crit_detail = {
            "vacuous": False,
            "hits": hits,
            "total": total,
            "rows": per_crit_rows,
        }

    if not parsed["acs"]:
        evidence_credit = 1.0
        evidence_detail = {"vacuous": True}
    else:
        tiers: list[float] = []
        evidence_rows: list[dict] = []
        for ac in parsed["acs"]:
            kws = evidence_keywords_by_ac.get(ac["id"], [])
            ev = ac.get("evidence") or ""
            if not ev.strip():
                tier = 0.0
            elif _is_specific_evidence(ev, kws):
                tier = 1.0
            else:
                tier = 0.5
            tiers.append(tier)
            evidence_rows.append(
                {"id": ac["id"], "tier": tier, "preview": ev[:120]}
            )
        evidence_credit = sum(tiers) / len(tiers)
        evidence_detail = {"vacuous": False, "mean": evidence_credit, "rows": evidence_rows}

    if not runtime_required_ids:
        fallback_credit = 1.0
        fallback_detail = {"vacuous": True}
    else:
        per_ac_credits: list[float] = []
        fallback_rows: list[dict] = []
        for aid in sorted(runtime_required_ids):
            raised = raised_by_id.get(aid)
            if raised is None:
                per_ac_credits.append(0.0)
                fallback_rows.append({"id": aid, "credit": 0.0, "reason": "ac_missing_from_report"})
                continue
            method = raised.get("method")
            result = raised.get("result")
            src_verified = _is_source_verified(method)
            skipped = _is_skipped(result)
            if src_verified and not skipped:
                per_ac_credits.append(0.0)
                fallback_rows.append(
                    {"id": aid, "credit": 0.0, "reason": "source_verified_without_skipped"}
                )
            else:
                per_ac_credits.append(1.0)
                fallback_rows.append(
                    {
                        "id": aid,
                        "credit": 1.0,
                        "method": method,
                        "result": result,
                    }
                )
        fallback_credit = sum(per_ac_credits) / len(per_ac_credits)
        fallback_detail = {
            "vacuous": False,
            "mean": fallback_credit,
            "rows": fallback_rows,
        }

    if not expected_blocking_kws:
        blocking_credit = 1.0
        blocking_detail = {"vacuous": True}
    else:
        blocking_lower = (parsed["blocking_text"] or "").lower()
        hits = [kw for kw in expected_blocking_kws if kw and kw.lower() in blocking_lower]
        blocking_credit = len(hits) / len(expected_blocking_kws)
        blocking_detail = {
            "vacuous": False,
            "hits": hits,
            "expected": expected_blocking_kws,
        }

    primary = (
        _W_VERDICT * verdict_credit
        + _W_PER_CRITERION * per_crit_credit
        + _W_EVIDENCE * evidence_credit
        + _W_FALLBACK * fallback_credit
        + _W_BLOCKING * blocking_credit
    )
    primary = max(0.0, min(1.0, primary))

    diagnostic: dict[str, Any] = {
        "verdict": verdict_detail,
        "per_criterion": per_crit_detail,
        "evidence": evidence_detail,
        "fallback": fallback_detail,
        "blocking": blocking_detail,
        "parsed_ac_count": len(parsed["acs"]),
        "scorer_version": SCORER_VERSION,
    }

    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
