"""
Purpose: Score a single adr-generator run against a labeled fixture by
         locating the ADR (preferring an on-disk file under docs/adr/ if
         written; falling back to parsing final_text emitted by the agent
         under Tier 1 isolation where Write/Edit are dropped) and checking
         six weighted dimensions: YAML front-matter shape, required section
         coverage, per-section substring fidelity, alternatives discipline,
         coded-bullet floors, and filename correctness.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace (trace["runs"] has exactly one
          run record). Aggregation across N runs is the aggregator module's
          job. A multi-run trace is an API-misuse bug and asserts.

Upstream deps: stdlib re, pathlib.

Downstream consumers: evals.runner.cli (dynamic import per the
                      adr-generator manifest's scoring_module field).

Failure modes: If no ADR can be located (neither a file under docs/adr/
               nor a plausibly-ADR-shaped block in final_text), returns
               status="invalid_format" and primary=0.0. Never raises.

Performance: standard; regex + substring passes over a short markdown blob.

---

## Scoring formula (v1)

Six weighted dimensions summing to exactly 1.0. Each is vacuous-safe: a
fixture that does not exercise an axis credits 1.0 rather than 0/0.

    w_frontmatter    = 0.15   # 7 required YAML keys; title format
                               # "ADR-NNNN:" + quoted status + YYYY-MM-DD date
    w_sections       = 0.25   # 8 required sections (Status, Context,
                               # Decision, Consequences, Positive, Negative,
                               # Alternatives Considered, Implementation
                               # Notes, References) - macro hit fraction
    w_substrings     = 0.25   # fixture-declared per-section substring
                               # fidelity; macro-average across sections
    w_alternatives   = 0.15   # >= alternatives_min blocks, each with
                               # an explicit rejection reason
    w_coded_bullets  = 0.10   # POS/NEG/ALT/IMP/REF floor counts;
                               # fraction met
    w_filename       = 0.10   # TIERED: pattern + correct-NNNN -> 1.0,
                               # pattern + wrong NNNN -> 0.5,
                               # malformed -> 0.0

Rationale on tiers: the filename axis is binary-shaped in the agent's
spec, but getting the NNNN wrong (e.g. 0001 when existing ADRs 0001-0002
are seeded and 0003 is expected) is a recoverable mistake a reviewer can
fix in a rename, whereas a malformed filename is a structural defect. A
0.5 for "right pattern, wrong number" keeps the axis from binary-dominating
the score when numbering-discovery is the only defect.

The scorer is file-or-final_text tolerant: Tier 1 isolation drops Write/
Edit from the agent's tool list (invoker._ALLOWED_TOOLS), so under the
eval the agent cannot save the ADR to docs/adr/. The expected path is for
it to emit the ADR text in its final response. The scorer first checks
`docs/adr/` on disk; if empty, it parses the final_text for an ADR block.
The filename axis under the final_text fallback reads the intended
filename from a declared "Filename: adr-NNNN-slug.md" line OR from the
first "# ADR-NNNN: ..." heading, and evaluates shape against that.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SCORER_VERSION = "v1"

_W_FRONTMATTER = 0.15
_W_SECTIONS = 0.25
_W_SUBSTRINGS = 0.25
_W_ALTERNATIVES = 0.15
_W_CODED_BULLETS = 0.10
_W_FILENAME = 0.10

_WEIGHTS_SUM_ASSERTION = abs(
    (_W_FRONTMATTER + _W_SECTIONS + _W_SUBSTRINGS + _W_ALTERNATIVES
     + _W_CODED_BULLETS + _W_FILENAME) - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "adr_generator_lite weights must sum to 1.0"

# The canonical 8 sections the template mandates. The scorer matches on
# normalized headings (case-insensitive, whitespace-collapsed, leading-#
# stripped). "Consequences" is the umbrella heading whose sub-sections
# "Positive" and "Negative" are the load-bearing content targets; we
# require the two sub-headings rather than the umbrella so the score
# discriminates on whether both polarities are documented.
_REQUIRED_SECTIONS = [
    "status",
    "context",
    "decision",
    "positive",
    "negative",
    "alternatives considered",
    "implementation notes",
    "references",
]

# The 7 required YAML front-matter keys.
_REQUIRED_FRONTMATTER_KEYS = [
    "title",
    "status",
    "date",
    "authors",
    "tags",
    "supersedes",
    "superseded_by",
]

_FRONTMATTER_BLOCK_RE = re.compile(
    r"^---\s*\n(?P<body>.*?)\n---\s*$",
    re.DOTALL | re.MULTILINE,
)
_FRONTMATTER_KEY_RE = re.compile(
    r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:",
    re.MULTILINE,
)

_TITLE_SHAPE_RE = re.compile(
    r'^title\s*:\s*"?ADR-(\d{4}):\s*[^"\n]+"?\s*$',
    re.IGNORECASE | re.MULTILINE,
)
_DATE_SHAPE_RE = re.compile(
    r'^date\s*:\s*"?(\d{4}-\d{2}-\d{2})"?\s*$',
    re.IGNORECASE | re.MULTILINE,
)
_STATUS_SHAPE_RE = re.compile(
    r'^status\s*:\s*"?(Proposed|Accepted|Rejected|Superseded|Deprecated)"?\s*$',
    re.IGNORECASE | re.MULTILINE,
)

# A heading line: one or more `#` then text. Capture the level and body.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

# Coded-bullet shape: `**POS-001**`, `**NEG-023**`, etc. Optional leading
# bullet marker. The full regex is liberal on surrounding markdown so we
# count any occurrence of the coded token.
_CODED_TOKEN_RE = re.compile(
    r"\b(POS|NEG|ALT|IMP|REF)-(\d{3})\b",
)

# Filename shape from a "Filename: adr-NNNN-slug.md" declaration line.
_FILENAME_DECL_RE = re.compile(
    r"(?:^|\n)\s*(?:\*\*)?Filename(?:\*\*)?\s*:\s*`?(adr-\d{4}-[a-z0-9\-]+\.md)`?",
    re.IGNORECASE,
)
# H1 adr heading "# ADR-NNNN: Title" - used to derive the intended NNNN
# when no explicit Filename line is provided.
_ADR_H1_RE = re.compile(
    r"^#\s+ADR-(\d{4}):",
    re.MULTILINE | re.IGNORECASE,
)
# Valid filename pattern for disk-written ADRs.
_FILENAME_PATTERN_RE = re.compile(r"^adr-(\d{4})-[a-z0-9\-]+\.md$")


def _normalize_heading(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def _split_headings(text: str) -> list[tuple[int, str, int]]:
    """Return [(level, normalized_name, start_offset)] in source order."""
    out: list[tuple[int, str, int]] = []
    for m in _HEADING_RE.finditer(text):
        level = len(m.group(1))
        name = _normalize_heading(m.group(2))
        out.append((level, name, m.start()))
    return out


def _section_body(text: str, target: str) -> str | None:
    """Return body text of the section whose heading matches `target`.

    Matching is case-insensitive whitespace-normalized. Body extends from
    after the heading line to the next heading at the same or shallower
    level (or EOF).
    """
    headings = _split_headings(text)
    target_n = _normalize_heading(target)
    for idx, (level, name, start) in enumerate(headings):
        if name == target_n:
            # End at the next heading whose level <= this one.
            line_end = text.find("\n", start)
            body_start = line_end + 1 if line_end != -1 else len(text)
            body_end = len(text)
            for j in range(idx + 1, len(headings)):
                lv2, _n2, st2 = headings[j]
                if lv2 <= level:
                    body_end = st2
                    break
            return text[body_start:body_end]
    return None


def _score_frontmatter(text: str) -> tuple[float, dict]:
    m = _FRONTMATTER_BLOCK_RE.search(text)
    if not m:
        return 0.0, {"present": False, "reason": "no_frontmatter_block"}
    body = m.group("body")
    keys_present = {km.group("key").lower() for km in _FRONTMATTER_KEY_RE.finditer(body)}
    key_hits = [k for k in _REQUIRED_FRONTMATTER_KEYS if k in keys_present]
    key_credit = len(key_hits) / len(_REQUIRED_FRONTMATTER_KEYS)

    title_ok = bool(_TITLE_SHAPE_RE.search(body))
    date_ok = bool(_DATE_SHAPE_RE.search(body))
    status_ok = bool(_STATUS_SHAPE_RE.search(body))
    shape_credits = [title_ok, date_ok, status_ok]
    shape_credit = sum(1 for c in shape_credits if c) / len(shape_credits)

    # Weighted split: 0.6 for key coverage, 0.4 for shape checks.
    credit = 0.6 * key_credit + 0.4 * shape_credit
    return credit, {
        "present": True,
        "keys_present": sorted(keys_present),
        "keys_required": _REQUIRED_FRONTMATTER_KEYS,
        "key_hits": key_hits,
        "title_shape_ok": title_ok,
        "date_shape_ok": date_ok,
        "status_shape_ok": status_ok,
        "key_credit": round(key_credit, 6),
        "shape_credit": round(shape_credit, 6),
    }


def _score_sections(text: str) -> tuple[float, dict]:
    headings = _split_headings(text)
    names_seen = {name for _lv, name, _st in headings}
    hits: list[str] = []
    missing: list[str] = []
    for req in _REQUIRED_SECTIONS:
        if req in names_seen:
            hits.append(req)
        else:
            missing.append(req)
    credit = len(hits) / len(_REQUIRED_SECTIONS)
    return credit, {
        "hits": hits,
        "missing": missing,
        "total": len(_REQUIRED_SECTIONS),
    }


def _score_substrings(text: str, per_section: dict) -> tuple[float, dict]:
    """Macro-average per-section required-substring fidelity.

    `per_section` maps section name (e.g. "Context") to a list of required
    substring needles. Matching is case-insensitive. A section not referenced
    in per_section contributes nothing. If no sections are referenced, the
    dimension is vacuous (credit 1.0).
    """
    if not per_section:
        return 1.0, {"vacuous": True}
    per: dict[str, dict] = {}
    creds: list[float] = []
    for sec, needles in per_section.items():
        if not needles:
            continue
        body = _section_body(text, sec) or ""
        lower = body.lower()
        hits = [n for n in needles if n.lower() in lower]
        missing = [n for n in needles if n.lower() not in lower]
        sec_credit = len(hits) / len(needles)
        per[sec] = {"hits": len(hits), "total": len(needles), "missing": missing}
        creds.append(sec_credit)
    if not creds:
        return 1.0, {"vacuous": True, "per_section": per}
    return sum(creds) / len(creds), {
        "vacuous": False,
        "per_section": per,
        "sections": sorted(per.keys()),
    }


def _score_alternatives(text: str, alternatives_min: int) -> tuple[float, dict]:
    """Count distinct alternative blocks under "Alternatives Considered"
    and verify each has an explicit rejection reason.

    A block is either an `####` sub-heading under the section OR a bullet
    item whose body contains an ALT-NNN code. Each block must contain the
    phrase "Rejection Reason" (case-insensitive) or a line beginning with
    a bold "Rejection" label.
    """
    if alternatives_min <= 0:
        return 1.0, {"vacuous": True}
    body = _section_body(text, "alternatives considered")
    if body is None:
        return 0.0, {"reason": "no_alternatives_section"}
    # Sub-heading blocks: `####` under the section.
    sub_headings = re.findall(r"^####\s+.+$", body, re.MULTILINE)
    # ALT codes: treat each distinct ALT-NNN as a candidate block anchor.
    alt_codes = sorted(set(m.group(0) for m in re.finditer(r"\bALT-\d{3}\b", body)))
    # Count blocks as max(subheadings, distinct ALT-NNN / 2) - each
    # alternative typically has at least 2 ALT codes (Description +
    # Rejection Reason), but a single-code alternative still counts.
    block_count = max(len(sub_headings), len(alt_codes) // 2 if alt_codes else 0, 1 if alt_codes else 0)
    # Rejection reason coverage across the section body.
    rejection_hits = len(re.findall(r"rejection\s*reason", body, re.IGNORECASE))
    rejection_ok = rejection_hits >= min(alternatives_min, max(block_count, 1))

    count_credit = min(block_count / alternatives_min, 1.0)
    credit = 0.6 * count_credit + 0.4 * (1.0 if rejection_ok else 0.0)
    return credit, {
        "block_count": block_count,
        "sub_headings": sub_headings,
        "alt_codes": alt_codes,
        "alternatives_min": alternatives_min,
        "rejection_hits": rejection_hits,
        "rejection_ok": rejection_ok,
        "count_credit": round(count_credit, 6),
    }


def _score_coded_bullets(text: str, floors: dict) -> tuple[float, dict]:
    """Fraction of coded-bullet floors met.

    `floors` maps a coded-token prefix (POS/NEG/ALT/IMP/REF) to a minimum
    count. The scorer counts distinct occurrences of each prefix (e.g.
    POS-001, POS-002 -> 2). Credit is (met / total_floors). If no floors
    are declared, the dimension is vacuous.
    """
    if not floors:
        return 1.0, {"vacuous": True}
    counts: dict[str, int] = {"POS": 0, "NEG": 0, "ALT": 0, "IMP": 0, "REF": 0}
    seen: set[tuple[str, str]] = set()
    for m in _CODED_TOKEN_RE.finditer(text):
        prefix, num = m.group(1), m.group(2)
        key = (prefix, num)
        if key in seen:
            continue
        seen.add(key)
        counts[prefix] += 1
    met: list[str] = []
    unmet: list[str] = []
    for prefix, floor in floors.items():
        pfx = prefix.upper()
        if counts.get(pfx, 0) >= int(floor):
            met.append(pfx)
        else:
            unmet.append(pfx)
    total = len(floors)
    credit = len(met) / total if total else 1.0
    return credit, {
        "counts": counts,
        "floors": {k.upper(): int(v) for k, v in floors.items()},
        "met": met,
        "unmet": unmet,
    }


def _score_filename(
    disk_filename: str | None,
    text: str,
    expected_nnnn: str | None,
) -> tuple[float, dict]:
    """Tiered filename credit.

    If the ADR was written to disk under docs/adr/, evaluate the on-disk
    filename. Otherwise, try to derive the intended filename from a
    "Filename: adr-NNNN-slug.md" declaration in the text, or from the
    "# ADR-NNNN:" H1 heading. Tiers:
      - pattern match + correct NNNN -> 1.0
      - pattern match + wrong NNNN   -> 0.5
      - pattern mismatch             -> 0.0

    If no expected_nnnn is declared, any pattern-matching filename credits
    1.0.
    """
    source = "disk" if disk_filename else "text"
    candidate: str | None = disk_filename
    if not candidate:
        m = _FILENAME_DECL_RE.search(text)
        if m:
            candidate = m.group(1)
        else:
            hm = _ADR_H1_RE.search(text)
            if hm:
                # Synthesize minimal candidate: we have NNNN but no slug;
                # treat as "pattern-compatible with NNNN known, slug missing".
                # Tiered credit downgrades to 0.5 when the NNNN is declared
                # via H1 but no filename line exists at all. This surfaces
                # the per-spec defect of not declaring the filename.
                return (
                    0.5 if (expected_nnnn is None or hm.group(1) == expected_nnnn) else 0.0,
                    {
                        "source": "h1_only",
                        "nnnn_from_h1": hm.group(1),
                        "expected_nnnn": expected_nnnn,
                        "reason": "no_filename_declaration_but_h1_present",
                    },
                )
            return 0.0, {"source": "none", "reason": "no_filename_signal_found"}

    pat = _FILENAME_PATTERN_RE.match(candidate)
    if not pat:
        return 0.0, {
            "source": source,
            "candidate": candidate,
            "reason": "pattern_mismatch",
        }
    nnnn = pat.group(1)
    if expected_nnnn is None:
        return 1.0, {
            "source": source,
            "candidate": candidate,
            "nnnn": nnnn,
            "expected_nnnn": None,
        }
    if nnnn == expected_nnnn:
        return 1.0, {
            "source": source,
            "candidate": candidate,
            "nnnn": nnnn,
            "expected_nnnn": expected_nnnn,
        }
    return 0.5, {
        "source": source,
        "candidate": candidate,
        "nnnn": nnnn,
        "expected_nnnn": expected_nnnn,
        "reason": "wrong_nnnn",
    }


def _locate_adr(worktree_root: str | None, final_text: str) -> tuple[str, str | None]:
    """Return (adr_text, disk_filename). Prefer on-disk file under
    docs/adr/; fall back to final_text.
    """
    if worktree_root:
        adr_dir = Path(worktree_root) / "docs" / "adr"
        if adr_dir.is_dir():
            # Prefer the newest `adr-NNNN-*.md` by NNNN desc (highest wins).
            candidates = sorted(
                [p for p in adr_dir.glob("adr-*.md") if p.is_file()],
                key=lambda p: p.name,
                reverse=True,
            )
            # Filter to those not in the seed - a crude heuristic: we can't
            # tell seeded from emitted at this layer, so pick the newest
            # mtime. The fixture's expected_nnnn pins the correct one.
            if candidates:
                newest = max(candidates, key=lambda p: p.stat().st_mtime)
                try:
                    return newest.read_text(encoding="utf-8"), newest.name
                except OSError:
                    pass
    return final_text or "", None


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
        "adr_generator_lite.score expects a single-run trace; aggregation "
        "across N runs happens in evals.runner.aggregator, not here."
    )
    run = runs[0]
    final_text = run.get("final_text") or ""
    worktree_root = run.get("worktree_root")

    adr_text, disk_filename = _locate_adr(worktree_root, final_text)
    if not adr_text.strip():
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "no_adr_located",
                "final_text_preview": final_text[:400],
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }

    expected = fixture.get("expected") or {}
    if not isinstance(expected, dict):
        expected = {}
    per_section_substrings = expected.get("required_substrings_by_section") or {}
    alternatives_min = int(expected.get("alternatives_min", 0))
    coded_floors = expected.get("coded_bullet_floors") or {}
    expected_nnnn = expected.get("expected_nnnn")

    fm_credit, fm_diag = _score_frontmatter(adr_text)
    sec_credit, sec_diag = _score_sections(adr_text)
    sub_credit, sub_diag = _score_substrings(adr_text, per_section_substrings)
    alt_credit, alt_diag = _score_alternatives(adr_text, alternatives_min)
    cb_credit, cb_diag = _score_coded_bullets(adr_text, coded_floors)
    fn_credit, fn_diag = _score_filename(disk_filename, adr_text, expected_nnnn)

    primary_raw = (
        _W_FRONTMATTER * fm_credit
        + _W_SECTIONS * sec_credit
        + _W_SUBSTRINGS * sub_credit
        + _W_ALTERNATIVES * alt_credit
        + _W_CODED_BULLETS * cb_credit
        + _W_FILENAME * fn_credit
    )
    primary = max(0.0, min(1.0, primary_raw))

    # Invalid-format gate: we located SOME ADR text, but if sections credit
    # is zero (no required section headings parsed) the emit is skeletal.
    status = "ok" if sec_credit > 0 else "invalid_format"

    diagnostic: dict[str, Any] = {
        "frontmatter": {"score": round(fm_credit, 6), **fm_diag},
        "sections": {"score": round(sec_credit, 6), **sec_diag},
        "substrings": {"score": round(sub_credit, 6), **sub_diag},
        "alternatives": {"score": round(alt_credit, 6), **alt_diag},
        "coded_bullets": {"score": round(cb_credit, 6), **cb_diag},
        "filename": {"score": round(fn_credit, 6), **fn_diag},
        "source": "disk" if disk_filename else "final_text",
        "disk_filename": disk_filename,
        "weights": {
            "frontmatter": _W_FRONTMATTER,
            "sections": _W_SECTIONS,
            "substrings": _W_SUBSTRINGS,
            "alternatives": _W_ALTERNATIVES,
            "coded_bullets": _W_CODED_BULLETS,
            "filename": _W_FILENAME,
        },
        "scorer_version": SCORER_VERSION,
    }
    return {
        "primary": round(primary, 6),
        "status": status,
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
