"""
Purpose: Score a single Debugger run against a labeled fixture by parsing
         the 6-section output format mandated by content/agents/debugger.md
         (Diagnosis / Root cause / Evidence / Hypotheses considered / Fix
         brief / Confidence) and combining six weighted dimensions.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace (trace["runs"] has one run
          record). Aggregation across N runs is the aggregator module's
          job. A multi-run trace is an API-misuse bug and the function
          asserts on it.

Upstream deps: stdlib re.

Downstream consumers: evals.runner.cli (dynamic import via manifest's
                      scoring_module field).

Failure modes: if the 6-section structure is missing or Confidence enum is
               absent / invalid, returns status="invalid_format" and
               primary=0.0. Never raises; all errors surface via
               status/diagnostic.

Performance: standard; regex parse of a short text blob.

---

## Scoring formula (v1)

Six weighted dimensions; weights sum to exactly 1.0 (runtime assertion).

    w_structure              = 0.15
    w_root_cause_locality    = 0.30
    w_diagnosis_keywords     = 0.20
    w_hypothesis_discipline  = 0.10
    w_fix_brief_specificity  = 0.15
    w_confidence_calibration = 0.10

### Dimension definitions

- **structure**: 1.0 if all six required section headers are present AND
  the Confidence line contains exactly one of {High, Medium, Low}. If any
  of the six headers is missing OR the Confidence enum is absent/invalid,
  the run is classified invalid_format and primary=0.0 (floor).

- **root_cause_locality**: tiered credit for how precisely the Root cause
  section pins the defect. Scanned against the Root cause block text.
    - file:line pattern ("path/file.ext:123")  -> 1.0
    - file + symbol pattern ("file.ext" and a `backticked_symbol()` or
      function/method mention in the same block) -> 0.6
    - file-only pattern (a path/file reference without line or symbol) -> 0.3
    - no file reference at all -> 0.0
  If the fixture declares `root_cause_location_hint` as "config" (the
  defect is not in code - e.g. db-005 where the location is a config
  file, not source.py), the scorer requires the config file path to be
  the primary (first-appearing) file reference in the Root cause block.
  A secondary code-file reference as explanatory context does NOT zero
  the credit; a code-file appearing BEFORE the config-file (debugger
  named code as the primary location) zeros the axis.

- **diagnosis_keywords**: fraction of `diagnosis_keywords` (fixture-
  declared substrings, case-insensitive) found in the combined Diagnosis
  + Root cause text. If the fixture declares no keywords, the dimension
  is vacuously 1.0.

- **hypothesis_discipline**: counts bullet lines under Hypotheses
  considered. A bullet is "disciplined" if it contains a verdict word
  ("eliminate" or "confirm" or a close morphological variant:
  "eliminated", "ruled out", "confirmed", "rejected"). Let `n` be the
  number of bullets and `d` the number of disciplined bullets.
    - If `n < min_hypotheses` (fixture-declared, default 2): score is
      d / min_hypotheses (penalizes under-counting).
    - Else: score is d / n (straight discipline fraction).
  Hypotheses dimension is NEVER vacuous: every diagnosis should show
  at least some hypothesis elimination reasoning. A fixture declaring
  `min_hypotheses: 0` is the explicit opt-out.

- **fix_brief_specificity**: fraction of `fix_brief_must_mention` fixture
  substrings present in the Fix brief block (case-insensitive). Special
  rule when `expected_confidence == "Low"`: the Fix brief MUST contain
  the literal substring "insufficient evidence" (case-insensitive). If
  Low-confidence fixture and the phrase is present, fix_brief dimension
  is 1.0 regardless of other substrings (a Low-confidence diagnosis is
  not supposed to write a concrete fix brief). If Low-confidence and
  the phrase is absent, the dimension is 0.0 - the debugger guessed
  despite low confidence, which the rule explicitly forbids.
  If the fixture declares no substrings (and is not Low-confidence),
  the dimension is vacuously 1.0.

- **confidence_calibration**: matches the parsed confidence enum against
  the fixture's `expected_confidence`.
    - exact match                        -> 1.0
    - adjacent (High<->Medium or Medium<->Low) -> 0.5
    - polar (High<->Low)                 -> 0.0

### Vacuous handling summary

| Dimension                | Vacuous when                                    |
|--------------------------|-------------------------------------------------|
| structure                | never                                           |
| root_cause_locality      | never                                           |
| diagnosis_keywords       | fixture.diagnosis_keywords == []                |
| hypothesis_discipline    | fixture.min_hypotheses == 0                     |
| fix_brief_specificity    | fix_brief_must_mention == [] AND expected != Low |
| confidence_calibration   | never                                           |

### Invalid-format floor

If any of the six section headers is missing OR the Confidence value is
not one of {High, Medium, Low}, primary=0.0 with status="invalid_format".
This is a hard floor - a debugger that does not follow the output
contract has not produced a scorable diagnosis.
"""
from __future__ import annotations

import re
from typing import Any

SCORER_VERSION = "v1"

_W_STRUCTURE = 0.15
_W_ROOT_CAUSE_LOCALITY = 0.30
_W_DIAGNOSIS_KEYWORDS = 0.20
_W_HYPOTHESIS_DISCIPLINE = 0.10
_W_FIX_BRIEF_SPECIFICITY = 0.15
_W_CONFIDENCE_CALIBRATION = 0.10

_WEIGHTS_SUM_OK = abs(
    (
        _W_STRUCTURE
        + _W_ROOT_CAUSE_LOCALITY
        + _W_DIAGNOSIS_KEYWORDS
        + _W_HYPOTHESIS_DISCIPLINE
        + _W_FIX_BRIEF_SPECIFICITY
        + _W_CONFIDENCE_CALIBRATION
    )
    - 1.0
) < 1e-9
assert _WEIGHTS_SUM_OK, "debugger_lite weights must sum to 1.0"


_SECTION_HEADERS = [
    ("diagnosis", re.compile(r"^##\s+Diagnosis\b", re.MULTILINE)),
    ("root_cause", re.compile(r"^###\s+Root cause\b", re.MULTILINE | re.IGNORECASE)),
    ("evidence", re.compile(r"^###\s+Evidence\b", re.MULTILINE | re.IGNORECASE)),
    (
        "hypotheses",
        re.compile(r"^###\s+Hypotheses considered\b", re.MULTILINE | re.IGNORECASE),
    ),
    ("fix_brief", re.compile(r"^###\s+Fix brief\b", re.MULTILINE | re.IGNORECASE)),
    ("confidence", re.compile(r"^###\s+Confidence\b", re.MULTILINE | re.IGNORECASE)),
]

_CONFIDENCE_VALUE_RE = re.compile(r"\b(High|Medium|Low)\b", re.IGNORECASE)

# file:line pattern: path with slash or dot-extension, followed by :NNN
_FILE_LINE_RE = re.compile(
    r"([\w\-./]+\.[A-Za-z0-9]{1,6}):(\d+)",
)
# file-only pattern: a filename with extension appearing in the text.
_FILE_RE = re.compile(r"([\w\-./]+\.[A-Za-z0-9]{1,6})\b")
# symbol pattern: a backticked identifier followed by ( or method-like form
_SYMBOL_RE = re.compile(r"`[A-Za-z_][\w.]*(?:\(\))?`")

_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)(?=^\s*[-*]\s+|\Z)", re.MULTILINE | re.DOTALL)

_DISCIPLINE_WORDS = (
    "eliminate",
    "eliminated",
    "eliminating",
    "confirm",
    "confirmed",
    "confirming",
    "ruled out",
    "rejected",
    "rejected:",
)


def _split_sections(text: str) -> dict[str, str]:
    """Return {section_key: section_body} for each matched header.

    A section body runs from the header line's end to the start of the
    next recognized header (any section at any level) or end of text.
    Sections whose headers are not found are omitted.
    """
    # Find every header occurrence across all section patterns.
    hits: list[tuple[int, int, str]] = []  # (start, end_of_header_line, key)
    for key, pat in _SECTION_HEADERS:
        for m in pat.finditer(text):
            # end of the header line
            line_end = text.find("\n", m.end())
            if line_end == -1:
                line_end = len(text)
            hits.append((m.start(), line_end, key))
    # Sort by start. Also collect ANY "##" or "###" header positions to
    # use as body boundaries even if they are not among our six (so a
    # stray section doesn't bleed into our parse).
    all_headers = [m.start() for m in re.finditer(r"^#{1,6}\s+\S", text, re.MULTILINE)]
    hits.sort()
    out: dict[str, str] = {}
    for i, (start, hdr_end, key) in enumerate(hits):
        # Body boundary: earliest of (next hit's start) or (next generic
        # header after hdr_end) or end-of-text.
        next_boundary = len(text)
        # Next of our known hits
        if i + 1 < len(hits):
            next_boundary = min(next_boundary, hits[i + 1][0])
        # Next generic header after hdr_end
        for h in all_headers:
            if h > hdr_end and h < next_boundary:
                next_boundary = h
                break
        out.setdefault(key, text[hdr_end:next_boundary].strip())
    return out


def _parse_confidence(body: str) -> str | None:
    m = _CONFIDENCE_VALUE_RE.search(body or "")
    if not m:
        return None
    return m.group(1).capitalize()


def _score_root_cause_locality(body: str, fixture: dict) -> tuple[float, dict]:
    hint = (fixture.get("root_cause_location_hint") or "code").lower()
    detail: dict[str, Any] = {"hint": hint, "tier": None, "match": None}

    if hint == "config":
        # Config-path fixture: credit a mention of the expected config
        # file. Full credit requires config_path to be the primary
        # (first-appearing) file reference in the Root cause block; a
        # secondary code-file reference as explanatory context does not
        # zero the credit. A code-file appearing BEFORE the config
        # file, though, is the "debugger blamed code" failure mode.
        config_path = fixture.get("root_cause_expected_path") or ""
        negative_paths = fixture.get("root_cause_negative_paths") or []
        m_line = _FILE_LINE_RE.search(body)
        if m_line and config_path and config_path in m_line.group(1):
            detail["tier"] = "file_line"
            detail["match"] = m_line.group(0)
            return (1.0, detail)
        cfg_idx = body.find(config_path) if config_path else -1
        neg_first_idx = -1
        neg_first_path = None
        for neg in negative_paths:
            idx = body.find(neg)
            if idx != -1 and (neg_first_idx == -1 or idx < neg_first_idx):
                neg_first_idx = idx
                neg_first_path = neg
        if cfg_idx != -1 and (neg_first_idx == -1 or cfg_idx < neg_first_idx):
            detail["tier"] = "config_file_primary"
            detail["match"] = config_path
            return (1.0, detail)
        if cfg_idx != -1 and neg_first_idx != -1 and cfg_idx >= neg_first_idx:
            detail["tier"] = "code_primary_config_secondary"
            detail["match"] = {"code": neg_first_path, "config": config_path}
            return (0.0, detail)
        if neg_first_idx != -1 and cfg_idx == -1:
            detail["tier"] = "blamed_code_only"
            detail["match"] = neg_first_path
            return (0.0, detail)
        detail["tier"] = "no_file_ref"
        return (0.0, detail)

    # Code-path fixture.
    m_line = _FILE_LINE_RE.search(body)
    if m_line:
        detail["tier"] = "file_line"
        detail["match"] = m_line.group(0)
        return (1.0, detail)
    file_hits = _FILE_RE.findall(body)
    symbol_hits = _SYMBOL_RE.findall(body)
    if file_hits and symbol_hits:
        detail["tier"] = "file_and_symbol"
        detail["match"] = {"file": file_hits[0], "symbol": symbol_hits[0]}
        return (0.6, detail)
    if file_hits:
        detail["tier"] = "file_only"
        detail["match"] = file_hits[0]
        return (0.3, detail)
    detail["tier"] = "none"
    return (0.0, detail)


def _score_diagnosis_keywords(
    diagnosis_body: str, root_cause_body: str, fixture: dict
) -> tuple[float, dict]:
    kws = list(fixture.get("diagnosis_keywords") or [])
    if not kws:
        return (1.0, {"vacuous": True, "hits": [], "misses": []})
    blob = (diagnosis_body + "\n" + root_cause_body).lower()
    hits: list[str] = []
    misses: list[str] = []
    for kw in kws:
        if kw.lower() in blob:
            hits.append(kw)
        else:
            misses.append(kw)
    return (len(hits) / len(kws), {"vacuous": False, "hits": hits, "misses": misses})


def _score_hypothesis_discipline(body: str, fixture: dict) -> tuple[float, dict]:
    min_hypotheses = int(fixture.get("min_hypotheses", 2))
    if min_hypotheses == 0:
        return (1.0, {"vacuous": True, "bullets": 0, "disciplined": 0})
    bullets = [b.strip() for b in _BULLET_RE.findall(body or "")]
    disciplined = 0
    for b in bullets:
        low = b.lower()
        if any(w in low for w in _DISCIPLINE_WORDS):
            disciplined += 1
    n = len(bullets)
    if n < min_hypotheses:
        # Under-count penalty: divide by min, not n.
        credit = disciplined / max(min_hypotheses, 1)
    else:
        credit = disciplined / n
    credit = max(0.0, min(1.0, credit))
    return (
        credit,
        {
            "vacuous": False,
            "bullets": n,
            "disciplined": disciplined,
            "min_required": min_hypotheses,
        },
    )


def _score_fix_brief_specificity(
    body: str, fixture: dict, parsed_confidence: str | None
) -> tuple[float, dict]:
    expected_conf = (fixture.get("expected_confidence") or "").capitalize()
    must_mention = list(fixture.get("fix_brief_must_mention") or [])
    body_low = (body or "").lower()
    if expected_conf == "Low":
        present = "insufficient evidence" in body_low
        return (
            1.0 if present else 0.0,
            {
                "low_confidence_rule": True,
                "insufficient_evidence_present": present,
            },
        )
    if not must_mention:
        return (1.0, {"vacuous": True, "hits": [], "misses": []})
    hits: list[str] = []
    misses: list[str] = []
    for n in must_mention:
        if n.lower() in body_low:
            hits.append(n)
        else:
            misses.append(n)
    return (
        len(hits) / len(must_mention),
        {"vacuous": False, "hits": hits, "misses": misses},
    )


def _score_confidence_calibration(
    parsed: str | None, expected: str | None
) -> tuple[float, dict]:
    if not parsed or not expected:
        return (0.0, {"parsed": parsed, "expected": expected})
    parsed_c = parsed.capitalize()
    expected_c = expected.capitalize()
    if parsed_c == expected_c:
        return (1.0, {"parsed": parsed_c, "expected": expected_c, "match": "exact"})
    pair = {parsed_c, expected_c}
    if pair == {"High", "Low"}:
        return (0.0, {"parsed": parsed_c, "expected": expected_c, "match": "polar"})
    return (0.5, {"parsed": parsed_c, "expected": expected_c, "match": "adjacent"})


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
        "debugger_lite.score expects a single-run trace; aggregation across N "
        "runs happens in evals.runner.aggregator, not here."
    )
    run = runs[0]
    text = run.get("final_text") or ""

    sections = _split_sections(text)
    required_keys = {"diagnosis", "root_cause", "evidence", "hypotheses", "fix_brief", "confidence"}
    missing = sorted(required_keys - set(sections))
    confidence_val = _parse_confidence(sections.get("confidence", ""))

    if missing or not confidence_val:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "missing_sections_or_confidence",
                "missing_sections": missing,
                "parsed_confidence": confidence_val,
                "final_text_preview": text[:600],
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }

    structure_credit = 1.0

    rc_body = sections.get("root_cause", "")
    locality_credit, locality_detail = _score_root_cause_locality(rc_body, fixture)

    kw_credit, kw_detail = _score_diagnosis_keywords(
        sections.get("diagnosis", ""), rc_body, fixture
    )

    hyp_credit, hyp_detail = _score_hypothesis_discipline(
        sections.get("hypotheses", ""), fixture
    )

    fix_credit, fix_detail = _score_fix_brief_specificity(
        sections.get("fix_brief", ""), fixture, confidence_val
    )

    conf_credit, conf_detail = _score_confidence_calibration(
        confidence_val, fixture.get("expected_confidence")
    )

    primary = (
        _W_STRUCTURE * structure_credit
        + _W_ROOT_CAUSE_LOCALITY * locality_credit
        + _W_DIAGNOSIS_KEYWORDS * kw_credit
        + _W_HYPOTHESIS_DISCIPLINE * hyp_credit
        + _W_FIX_BRIEF_SPECIFICITY * fix_credit
        + _W_CONFIDENCE_CALIBRATION * conf_credit
    )
    primary = max(0.0, min(1.0, primary))

    diagnostic: dict[str, Any] = {
        "structure": {"credit": structure_credit, "missing_sections": []},
        "root_cause_locality": {"credit": locality_credit, **locality_detail},
        "diagnosis_keywords": {"credit": kw_credit, **kw_detail},
        "hypothesis_discipline": {"credit": hyp_credit, **hyp_detail},
        "fix_brief_specificity": {"credit": fix_credit, **fix_detail},
        "confidence_calibration": {"credit": conf_credit, **conf_detail},
        "parsed_confidence": confidence_val,
        "scorer_version": SCORER_VERSION,
    }
    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
