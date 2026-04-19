"""
Purpose: Parse the editor-agent's Overfitting Rule verdict line and flag the
         failure mode where an edit explicitly references a fixture ID
         (e.g. "sk-001", "ip-003", "wr-002", "co-005"). An edit that names a
         specific fixture in its rationale is overfitting by definition -
         scores inform, they do not justify.

Public API: parse_verdict(text: str) -> dict with keys {verdict: "pass"|"fail",
            reason: str, raw_line: str, fixture_ids: list[str]}.
            Returns verdict="fail" if the verdict line is missing or malformed,
            or if the rationale or the diff references any fixture ID pattern.

Upstream deps: stdlib re.

Downstream consumers: evals.auto.loop.

Failure modes: None raised; malformed input returns verdict="fail" with a reason.

Performance: regex-only over short text; negligible.
"""
from __future__ import annotations

import re
from typing import Dict, List

# Fixture-ID patterns seen in this repo's components: sk-NNN, ip-NNN,
# wr-NNN, co-NNN. Match case-insensitively with a word boundary.
_FIXTURE_ID_RE = re.compile(r"\b(sk|ip|wr|co)-\d{3}\b", re.IGNORECASE)

_VERDICT_RE = re.compile(
    r"^\s*Overfitting Rule verdict:\s*(yes|no|pass|fail)\b\s*(?:because\s*(.*))?$",
    re.IGNORECASE | re.MULTILINE,
)


def _normalize_verdict(token: str) -> str:
    tok = token.strip().lower()
    # The spawn brief asks for "yes|no" (yes = rule satisfied -> pass).
    # Accept pass/fail as synonyms to be robust to minor drift in the
    # editor-agent's phrasing.
    if tok in ("yes", "pass"):
        return "pass"
    if tok in ("no", "fail"):
        return "fail"
    return "fail"


def parse_verdict(text: str, diff: str = "") -> Dict[str, object]:
    """Extract and validate the Overfitting Rule verdict from editor-agent output.

    text: the full editor-agent response (the line must be present on its own
          line for the regex to anchor).
    diff: optional - the proposed diff. If supplied, fixture-ID references in
          the diff itself are treated as failures even if the verdict line
          claims "yes".
    """
    m = _VERDICT_RE.search(text or "")
    if not m:
        return {
            "verdict": "fail",
            "reason": "verdict_line_missing",
            "raw_line": "",
            "fixture_ids": [],
        }
    raw_line = m.group(0).strip()
    verdict = _normalize_verdict(m.group(1))
    reason = (m.group(2) or "").strip()

    # Scan BOTH the rationale and the diff for fixture IDs. An edit whose
    # rationale or payload names a specific fixture is overfitting.
    ids_in_reason: List[str] = [x.lower() for x in _FIXTURE_ID_RE.findall(reason)]
    ids_in_diff: List[str] = [x.lower() for x in _FIXTURE_ID_RE.findall(diff or "")]
    # findall() with groups returns the group text only; re-scan for the full match.
    reason_full = [m.group(0).lower() for m in _FIXTURE_ID_RE.finditer(reason)]
    diff_full = [m.group(0).lower() for m in _FIXTURE_ID_RE.finditer(diff or "")]
    all_ids = sorted(set(reason_full + diff_full))

    if all_ids:
        return {
            "verdict": "fail",
            "reason": f"fixture_id_referenced: {','.join(all_ids)}",
            "raw_line": raw_line,
            "fixture_ids": all_ids,
        }

    return {
        "verdict": verdict,
        "reason": reason or ("" if verdict == "pass" else "no_reason_given"),
        "raw_line": raw_line,
        "fixture_ids": [],
    }
