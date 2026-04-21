"""
Purpose: Score a single dependency-auditor run against a labeled fixture by
         parsing the Dependency Audit Report structure mandated by
         content/agents/dependency-auditor.md (`## Dependency Audit Report`
         header, `### Summary`, `### Findings` with `#### Critical`/`Major`/
         `Minor` subsections, `### Upgrade plan`, `### Open questions`,
         `### Scan gaps`) and combining five weighted dimensions.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace (trace["runs"] has exactly one
          run record). Aggregation across N runs is the aggregator module's
          job. A multi-run trace is an API-misuse bug and asserts.

Upstream deps: stdlib re, json.

Downstream consumers: evals.runner.cli (dynamic import per manifest's
                      scoring_module field).

Failure modes: if the report header or the Findings section is absent,
               returns status="invalid_format" and primary=0.0 without
               raising. Never raises; all errors surface via status/diagnostic.

Performance: standard; regex-based parse of a short text blob plus a
             filesystem read of the fixture's pre-captured audit JSON for
             CVE-from-memory cross-checks.

---

## Scoring formula (v1)

Five weighted dimensions. Weights sum to exactly 1.0 (runtime assertion).

    w_cve_recall          = 0.30  (TP/FN/FP on Critical+Major CVEs;
                                   bounded FP penalty, capped at 0.5 of
                                   max(max_credit, 1.0) - mirrors
                                   skeptic_lite v2 calibration).
    w_license_findings    = 0.20  (TP/FN/FP on license findings;
                                   same bounded-FP shape)
    w_maintenance_findings = 0.15 (TP/FN/FP on maintenance / typosquat /
                                   stale-dep findings; same shape)
    w_scan_coverage       = 0.15  (fraction of expected ecosystems named
                                   in the report's "Ecosystems scanned" or
                                   "Tools run" lines; vacuous -> 1.0)
    w_report_structure    = 0.20  (TIERED: strict (all 5 required
                                   sections present + no CVE-from-memory
                                   hallucination) -> 1.0, partial (4 of 5
                                   present, or one missing but no
                                   hallucination) -> 0.5, malformed -> 0.0;
                                   CVE-from-memory = any CVE-ID emitted
                                   that is NOT present in any of the
                                   fixture's repo/.audit/*.json payloads -
                                   forces this dimension to 0.0.)

Per-axis vacuous handling: for TP/FN/FP axes, a fixture with zero expected
findings of that severity class (e.g. da-003 clean control has no CVEs)
scores `clip(1.0 - fp_penalty, 0, 1)` on that axis - symmetric with
skeptic_lite's clean-case treatment.

### Worked examples

1. da-001 shape: transitive Critical CVE (qs in old express). Expected
   critical CVE finding with keywords ["qs", "CVE-2022-24999"]. Report
   raises the CVE by ID in Critical section, no FP license findings.
   w_cve_recall = 1.0, w_license = 1.0 (vacuous), w_maintenance = 1.0
   (vacuous), w_scan_coverage = 1.0 (npm ecosystem named), w_report_structure
   = 1.0 (strict). primary = 1.0.

2. da-002 shape: GPL dep. Expected license Major. Report flags GPL-3.0
   in Major license section, no CVE noise.
   w_cve_recall = 1.0 (vacuous), w_license = 1.0, w_maintenance = 1.0
   (vacuous), w_scan_coverage = 1.0, w_report_structure = 1.0. primary = 1.0.

3. da-003 shape: clean control. No findings expected.
   All TP/FN/FP axes vacuous -> 1.0 each. If report raises a spurious
   finding with a fabricated CVE-ID (not in .audit/), w_report_structure
   forces 0.0 (hallucination floor).

4. da-005 shape: false-positive trap with a legitimately-named dependency
   that visually resembles a known package but has a real repo and usage
   history. Expected ZERO typosquat findings. Report incorrectly flags
   the legitimate dep as typosquat (FP_m). Clean-case on all other axes,
   w_maintenance hit with fp_penalty = 0.1 -> primary drops from 1.0.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCORER_VERSION = "v1"

_W_CVE = 0.30
_W_LICENSE = 0.20
_W_MAINTENANCE = 0.15
_W_SCAN_COVERAGE = 0.15
_W_REPORT_STRUCTURE = 0.20

_WEIGHTS_SUM_ASSERTION = abs(
    (_W_CVE + _W_LICENSE + _W_MAINTENANCE + _W_SCAN_COVERAGE + _W_REPORT_STRUCTURE)
    - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "dependency_auditor_lite weights must sum to 1.0"

# Report structure regexes. Headers must be matched verbatim (per role doc
# 'Do not paraphrase section headers').
_REPORT_HEADER_RE = re.compile(r"^##\s+Dependency Audit Report\b", re.MULTILINE)
_SUMMARY_RE = re.compile(r"^###\s+Summary\b", re.MULTILINE)
_FINDINGS_RE = re.compile(r"^###\s+Findings\b", re.MULTILINE)
_UPGRADE_PLAN_RE = re.compile(r"^###\s+Upgrade plan\b", re.MULTILINE)
_OPEN_QUESTIONS_RE = re.compile(r"^###\s+Open questions\b", re.MULTILINE)
_SCAN_GAPS_RE = re.compile(r"^###\s+Scan gaps\b", re.MULTILINE)

_SEV_SECTION_RE = re.compile(
    r"^####\s+(Critical|Major|Minor)\s*\n(.*?)(?=^####\s+(?:Critical|Major|Minor)\b|^###\s+|\Z)",
    re.MULTILINE | re.DOTALL,
)

_ECOSYSTEMS_LINE_RE = re.compile(
    r"Ecosystems scanned:\s*([^\n|]+)",
    re.IGNORECASE,
)
_TOOLS_LINE_RE = re.compile(
    r"Tools run:\s*([^\n|]+)",
    re.IGNORECASE,
)

_CVE_ID_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
_GHSA_ID_RE = re.compile(r"\bGHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}\b", re.IGNORECASE)


def _parse_report(text: str) -> dict:
    text = text or ""
    header = bool(_REPORT_HEADER_RE.search(text))
    summary = bool(_SUMMARY_RE.search(text))
    findings = bool(_FINDINGS_RE.search(text))
    upgrade = bool(_UPGRADE_PLAN_RE.search(text))
    openq = bool(_OPEN_QUESTIONS_RE.search(text))
    scan_gaps = bool(_SCAN_GAPS_RE.search(text))

    sections_present = sum(
        [summary, findings, upgrade, openq, scan_gaps]
    )

    # Parse per-severity finding blocks.
    by_sev: dict[str, str] = {"critical": "", "major": "", "minor": ""}
    for m in _SEV_SECTION_RE.finditer(text):
        sev = m.group(1).lower()
        body = (m.group(2) or "").strip()
        by_sev[sev] = body

    # Extract ecosystems and tools (comma-separated list on the header line).
    eco_match = _ECOSYSTEMS_LINE_RE.search(text)
    ecosystems: list[str] = []
    if eco_match:
        ecosystems = [e.strip().lower() for e in eco_match.group(1).split(",") if e.strip()]
    tool_match = _TOOLS_LINE_RE.search(text)
    tools: list[str] = []
    if tool_match:
        tools = [t.strip().lower() for t in tool_match.group(1).split(",") if t.strip()]

    # Harvest all CVE/GHSA ids anywhere in the report (for hallucination check).
    cve_ids = {m.group(0).upper() for m in _CVE_ID_RE.finditer(text)}
    ghsa_ids = {m.group(0).upper() for m in _GHSA_ID_RE.finditer(text)}

    return {
        "header_present": header,
        "summary_present": summary,
        "findings_present": findings,
        "upgrade_plan_present": upgrade,
        "open_questions_present": openq,
        "scan_gaps_present": scan_gaps,
        "sections_present_count": sections_present,
        "findings_by_sev": by_sev,
        "ecosystems": ecosystems,
        "tools": tools,
        "cve_ids": cve_ids,
        "ghsa_ids": ghsa_ids,
        "format_valid": header and findings,
    }


def _match_finding(body: str, expected: dict) -> bool:
    """Case-insensitive keyword-ALL match inside a severity section body."""
    b = body.lower()
    kws = [k.lower() for k in (expected.get("keywords") or []) if k]
    if not kws:
        return False
    return all(kw in b for kw in kws)


def _split_finding_entries(body: str) -> list[str]:
    """Roughly segment a severity-block body into discrete finding entries.

    Accepts either `####` sub-sub-headings, bullet points starting with `-`
    or `*`, or blocks separated by blank lines. Returns a flat list of
    per-entry text slabs for FP counting.
    """
    if not body:
        return []
    body_lower = body.strip().lower()
    if body_lower in {"none", '"none"', "(none)", "- none"}:
        return []
    # Primary split: double newlines or leading bullets.
    entries: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        if line.strip().startswith(("- ", "* ", "#### ")) and current:
            entries.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        entries.append("\n".join(current).strip())
    # Filter placeholders. An entry consisting entirely of one or more
    # "none" lines (possibly with whitespace / bullets) is a placeholder
    # for "no findings in this severity" and MUST NOT count as a raised
    # finding.
    def _is_placeholder(e: str) -> bool:
        lines = [ln.strip().strip("-*").strip().lower() for ln in e.splitlines() if ln.strip()]
        return all(ln in {"", "none", "(none)", '"none"'} for ln in lines)
    return [e for e in entries if e and not _is_placeholder(e)]


def _score_axis(
    raised_body: str,
    expected: list[dict],
) -> tuple[float, dict]:
    """Score a single severity/category axis with TP/FN + bounded FP.

    Mirrors skeptic_lite v2 calibration: max_credit comes from expected
    entries, fp_penalty is bounded at 0.5 * max(max_credit, 1.0), vacuous
    on empty-expected is `clip(1.0 - fp_penalty, 0, 1)`.
    """
    entries = _split_finding_entries(raised_body)
    matched_idx: set[int] = set()
    tp = 0
    for exp in expected:
        for i, entry in enumerate(entries):
            if i in matched_idx:
                continue
            if _match_finding(entry, exp):
                matched_idx.add(i)
                tp += 1
                break
    fn = len(expected) - tp
    fp = max(0, len(entries) - tp)

    max_credit = len(expected) * 1.0  # every expected entry weighted 1.0 on its own axis
    raw_fp = fp * 0.2  # fixed per-FP penalty on non-CVE axes
    fp_cap = max(max_credit, 1.0) * 0.5
    fp_penalty = min(raw_fp, fp_cap)

    if len(expected) == 0:
        # Vacuous-safe: on a clean/irrelevant axis we credit 1.0 unconditionally.
        # Per-category false-positive discipline cannot be enforced without a
        # category classifier (we can't reliably tell a license-typed finding
        # apart from a maintenance-typed one by regex). FP discipline on the
        # axis that DOES expect findings is retained via the bounded-FP
        # penalty; clean-fixture FP discipline is retained via the
        # hallucination gate on w_report_structure.
        primary = 1.0
    else:
        base = (tp - fn * 0.5) / max_credit if max_credit > 0 else 0.0
        primary = max(0.0, min(1.0, base - fp_penalty / max(max_credit, 1.0)))

    return primary, {
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "max_credit": max_credit,
        "raw_fp": round(raw_fp, 6),
        "fp_cap": round(fp_cap, 6),
        "fp_penalty": round(fp_penalty, 6),
        "raised_count": len(entries),
        "expected_count": len(expected),
    }


def _load_audit_catalog(repo_dir: Path | None) -> tuple[set[str], bool]:
    """Collect all CVE/GHSA IDs present in the fixture's pre-captured audit JSON.

    Returns (catalog, audit_dir_present).

    audit_dir_present is True iff the fixture ships any `.audit/*.json`
    pre-captured output (even if that output contains zero CVEs - a
    clean scan is still a scan). The hallucination gate uses this flag
    to decide whether emitting an ID not in the catalog is a defect:
    a clean pip-audit result with zero CVEs MUST refuse every CVE
    emission in the report; a fixture with NO `.audit/` at all cannot
    discriminate hallucinations at all (the agent has no corpus to
    check against), so we skip the gate in that case.
    """
    catalog: set[str] = set()
    if repo_dir is None or not repo_dir.exists():
        return catalog, False
    audit_dir = repo_dir / ".audit"
    if not audit_dir.exists():
        return catalog, False
    audit_files = list(audit_dir.glob("*.json"))
    if not audit_files:
        return catalog, False
    for jf in audit_files:
        try:
            text = jf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Harvest IDs from raw text - handles arbitrary JSON shapes across
        # npm audit / pip-audit / cargo audit / etc.
        for m in _CVE_ID_RE.finditer(text):
            catalog.add(m.group(0).upper())
        for m in _GHSA_ID_RE.finditer(text):
            catalog.add(m.group(0).upper())
    return catalog, True


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
        "dependency_auditor_lite.score expects a single-run trace; aggregation "
        "across N runs happens in evals.runner.aggregator, not here."
    )

    run = runs[0]
    text = run.get("final_text") or ""
    parsed = _parse_report(text)

    if not parsed["format_valid"]:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "dependency_audit_report_header_or_findings_missing",
                "header_present": parsed["header_present"],
                "findings_present": parsed["findings_present"],
                "final_text_preview": text[:600],
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }

    expected = (fixture or {}).get("expected") or {}
    expected_cve = expected.get("cve_findings") or []
    expected_license = expected.get("license_findings") or []
    expected_maint = expected.get("maintenance_findings") or []
    expected_ecosystems = [
        e.lower() for e in (expected.get("expected_ecosystems") or [])
    ]

    # Combine Critical+Major bodies for CVE recall axis; by convention,
    # maintenance/license findings land in Major or Minor.
    cve_body = (
        parsed["findings_by_sev"]["critical"]
        + "\n"
        + parsed["findings_by_sev"]["major"]
    )
    # License / maintenance findings can appear in Major or Minor blocks.
    non_cve_body = (
        parsed["findings_by_sev"]["major"]
        + "\n"
        + parsed["findings_by_sev"]["minor"]
    )

    cve_credit, cve_detail = _score_axis(cve_body, expected_cve)
    license_credit, license_detail = _score_axis(non_cve_body, expected_license)
    maint_credit, maint_detail = _score_axis(non_cve_body, expected_maint)

    # Scan coverage: fraction of expected ecosystems named.
    if not expected_ecosystems:
        scan_coverage = 1.0
        scan_detail: dict[str, Any] = {"vacuous": True}
    else:
        reported = set(parsed["ecosystems"]) | set(parsed["tools"])
        # Soft matching: an expected ecosystem is "covered" if its name
        # appears as a substring in any reported token (npm -> "npm audit" OK).
        hits = 0
        matched: list[str] = []
        for eco in expected_ecosystems:
            for token in reported:
                if eco in token:
                    hits += 1
                    matched.append(eco)
                    break
        scan_coverage = hits / len(expected_ecosystems) if expected_ecosystems else 1.0
        scan_detail = {
            "vacuous": False,
            "expected": expected_ecosystems,
            "reported": sorted(reported),
            "matched": matched,
            "hits": hits,
        }

    # Report structure axis. Strict -> 1.0; partial -> 0.5; malformed -> 0.0.
    # Plus: CVE-from-memory hallucination forces 0.0.
    repo_dir = (fixture or {}).get("_repo_dir")
    audit_catalog, audit_present = _load_audit_catalog(
        Path(repo_dir) if repo_dir else None
    )
    emitted_ids = parsed["cve_ids"] | parsed["ghsa_ids"]
    # Any emitted ID not present in the audit catalog counts as from-memory.
    # Gate fires iff the fixture ships ANY pre-captured audit output (even a
    # clean zero-CVE result). Fixtures with no .audit/ directory at all
    # skip the gate - they have no corpus to cross-check against and the
    # scan_coverage axis will already penalise the missing scan.
    from_memory = sorted(emitted_ids - audit_catalog)
    hallucinated = bool(from_memory) and audit_present

    sections_present = parsed["sections_present_count"]
    if hallucinated:
        structure_credit = 0.0
    elif sections_present == 5:
        structure_credit = 1.0
    elif sections_present == 4:
        structure_credit = 0.5
    else:
        structure_credit = 0.0
    structure_detail = {
        "sections_present_count": sections_present,
        "summary_present": parsed["summary_present"],
        "findings_present": parsed["findings_present"],
        "upgrade_plan_present": parsed["upgrade_plan_present"],
        "open_questions_present": parsed["open_questions_present"],
        "scan_gaps_present": parsed["scan_gaps_present"],
        "emitted_ids": sorted(emitted_ids),
        "audit_catalog_size": len(audit_catalog),
        "from_memory_ids": from_memory,
        "hallucinated": hallucinated,
    }

    # Clean-report FP penalty: a fixture with NO expected findings anywhere
    # (da-003 clean control, da-005 false-positive trap) is meant to test
    # that the agent does not fabricate or over-call findings. For these
    # fixtures we redistribute the penalty across the three vacuous TP/FN/FP
    # axes (each of which otherwise credits 1.0 unconditionally) based on
    # how many actual finding entries appeared in the report. Each spurious
    # finding subtracts 0.2 from the relevant axis down to a floor of 0.0.
    all_axes_vacuous = (
        not expected_cve and not expected_license and not expected_maint
    )
    if all_axes_vacuous:
        total_entries = sum(
            len(_split_finding_entries(parsed["findings_by_sev"][sev]))
            for sev in ("critical", "major", "minor")
        )
        if total_entries > 0:
            fp_clean_penalty = min(1.0, total_entries * 0.2)
            # Spread the penalty equally across the three vacuous axes.
            per_axis = fp_clean_penalty / 3.0
            cve_credit = max(0.0, cve_credit - per_axis)
            license_credit = max(0.0, license_credit - per_axis)
            maint_credit = max(0.0, maint_credit - per_axis)

    primary = (
        _W_CVE * cve_credit
        + _W_LICENSE * license_credit
        + _W_MAINTENANCE * maint_credit
        + _W_SCAN_COVERAGE * scan_coverage
        + _W_REPORT_STRUCTURE * structure_credit
    )
    primary = max(0.0, min(1.0, primary))

    diagnostic: dict[str, Any] = {
        "cve_recall": {"credit": cve_credit, **cve_detail},
        "license_findings": {"credit": license_credit, **license_detail},
        "maintenance_findings": {"credit": maint_credit, **maint_detail},
        "scan_coverage": {"credit": scan_coverage, **scan_detail},
        "report_structure": {"credit": structure_credit, **structure_detail},
        "scorer_version": SCORER_VERSION,
    }

    _ = json  # json import kept for future audit-catalog parsing
    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
