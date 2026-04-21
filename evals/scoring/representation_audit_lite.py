"""
Purpose: Score a single /representation-audit command-mode run against a
         labeled fixture by inspecting the proposal document written under
         docs/planning/ and verifying structural, vocabulary, candidate-count,
         and content-safety properties.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace (trace["runs"] has one run).
          The run record carries a "filesystem" dict (relative path ->
          sha256) populated by evals.runner.invoker in command mode, and
          "worktree_root" so the scorer can read the proposal markdown
          directly.

Upstream deps: stdlib pathlib, re, fnmatch.

Downstream consumers: evals.runner.cli (dynamic import per manifest's
                      scoring_module).

Failure modes: missing filesystem snapshot => status "invalid_format",
               primary 0.0. Missing worktree_root or proposal file =>
               proposal_presence 0.0 and text-level axes collapse to 0.0
               (candidate_fields, vocabulary, sections) while
               candidate_count and forbidden remain evaluable.

---

## Scoring formula (v1)

Six weighted dimensions summing to 1.0. A perfect run scores exactly 1.0
(runtime assertion). Every axis is vacuous-safe: a fixture that declares
an axis inapplicable (e.g. empty required_sections) scores that axis 1.0.

    w_proposal_presence = 0.20  (proposal file exists at proposal_glob;
                                 binary)
    w_sections          = 0.15  (fraction of required_sections found as
                                 heading prefixes in the proposal;
                                 vacuous if required_sections == [])
    w_candidate_fields  = 0.20  (per-candidate macro-average of the
                                 fraction of required_candidate_fields
                                 present in each candidate block;
                                 vacuous if no candidates parsed)
    w_candidate_count   = 0.15  (tiered: within [min, max] -> 1.0;
                                 off-by-one either side -> 0.5; else 0.0.
                                 If allow_empty_with_rationale is true and
                                 the proposal states an explicit empty-
                                 rationale sentence, 0 candidates counts
                                 as in-range)
    w_vocabulary        = 0.15  (three sub-checks averaged: signal labels
                                 drawn from valid_signals, priority values
                                 drawn from valid_priorities, meaning-
                                 preserved values drawn from
                                 valid_meaning_preserved. Vacuous per
                                 sub-check if no candidates declare the
                                 field)
    w_forbidden         = 0.15  (binary; 1.0 if no content/** file was
                                 written or modified relative to the HEAD
                                 the worktree was initialized from; 0.0
                                 otherwise)

Candidate parsing: the proposal template uses `### ` headings inside a
"## Rewrite candidates" region for each candidate. The scorer locates the
candidates region by splitting on `## ` top-level headings; within it,
each `### ` sub-heading starts a candidate block that runs until the next
`### ` or top-level heading.

Rationale (Overfitting-Rule-passing): the six axes are each independently
defensible against the command's spec. Proposal presence and required-
section coverage check structural template fidelity. Per-candidate
required-field coverage checks that the analyst populated the fixture
rather than dropping a skeleton. Candidate-count tiering mirrors the
command's "3-10 candidates" range as a soft-quality dimension with an
off-by-one grace (analogous to init_project_lite's line-budget tier).
Vocabulary enforcement follows the LEARNINGS rule that enum-like fields
score by exact match against enums declared in the prompt. The forbidden
axis is load-bearing for the command's safety model - the audit
explicitly writes no `content/**` file.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SCORER_VERSION = "v1"

_W_PROPOSAL_PRESENCE = 0.20
_W_SECTIONS = 0.15
_W_CANDIDATE_FIELDS = 0.20
_W_CANDIDATE_COUNT = 0.15
_W_VOCABULARY = 0.15
_W_FORBIDDEN = 0.15

_WEIGHTS_SUM_ASSERTION = abs(
    (
        _W_PROPOSAL_PRESENCE
        + _W_SECTIONS
        + _W_CANDIDATE_FIELDS
        + _W_CANDIDATE_COUNT
        + _W_VOCABULARY
        + _W_FORBIDDEN
    )
    - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "representation_audit_lite weights must sum to 1.0"


# Default canonical fixture enums. Fixtures override via valid_signals /
# valid_priorities / valid_meaning_preserved.
_DEFAULT_VALID_SIGNALS = {"R1", "R2", "R3", "R4", "R5", "R6", "R7"}
_DEFAULT_VALID_PRIORITIES = {"HIGH", "MEDIUM", "LOW"}
_DEFAULT_VALID_MEANING_PRESERVED = {"HIGH", "MEDIUM", "LOW"}


def _read_text(worktree_root: str | None, rel_path: str) -> str:
    if not worktree_root:
        return ""
    p = Path(worktree_root) / rel_path
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _match_proposal(snapshot_keys: set[str], glob: str) -> str | None:
    """Return the first snapshot key matching the glob, or None."""
    import fnmatch

    for k in sorted(snapshot_keys):
        if fnmatch.fnmatch(k, glob):
            return k
    return None


def _parse_candidates(text: str) -> list[dict[str, str]]:
    """Parse candidate blocks from the proposal text.

    Locates the `## Rewrite candidates` region (or any `## ...candidates...`
    heading) and extracts every `### ` sub-heading block until the next
    top-level heading. Each block is returned as a dict with the raw title
    and body text.
    """
    lines = text.splitlines()
    # Find start of a "## ...candidate..." region.
    start = -1
    for i, line in enumerate(lines):
        if line.startswith("## ") and "candidate" in line.lower():
            start = i + 1
            break
    if start == -1:
        return []
    # End at the next `## ` heading.
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    region = lines[start:end]

    candidates: list[dict[str, str]] = []
    cur_title: str | None = None
    cur_body: list[str] = []
    for line in region:
        if line.startswith("### "):
            if cur_title is not None:
                candidates.append({"title": cur_title, "body": "\n".join(cur_body)})
            cur_title = line[4:].strip()
            cur_body = []
        else:
            if cur_title is not None:
                cur_body.append(line)
    if cur_title is not None:
        candidates.append({"title": cur_title, "body": "\n".join(cur_body)})
    return candidates


def _score_candidate_fields(
    candidates: list[dict[str, str]],
    required_fields: list[str],
) -> tuple[float, dict[str, Any]]:
    """Per-candidate macro-average of required-field coverage.

    A field matches if a line in the candidate body starts with either
    `- <field>:` or `<field>:` (case-insensitive) or contains the pattern
    `**<field>:**`. The macro-average is the mean across candidates of
    (hits / total_required).
    """
    if not required_fields:
        return (1.0, {"vacuous": True, "per_candidate": []})
    if not candidates:
        return (
            0.0,
            {
                "vacuous": False,
                "per_candidate": [],
                "reason": "no_candidates_parsed",
            },
        )
    per: list[dict[str, Any]] = []
    total_score = 0.0
    for cand in candidates:
        body = cand.get("body", "")
        body_lower = body.lower()
        hits: list[str] = []
        misses: list[str] = []
        for f in required_fields:
            f_low = f.lower()
            # Accept a field label followed immediately by ':' OR by
            # '(s):' (for plural-tolerant field names like "Signal(s)" as
            # used in the command template). Tolerate a '- ' bullet
            # prefix and `**...**` bold wrapping.
            suffixes = [":", "(s):", "s:"]
            patterns: list[str] = []
            for suf in suffixes:
                patterns.extend([
                    f"- {f_low}{suf}",
                    f"{f_low}{suf}",
                    f"**{f_low}{suf}**",
                    f"- **{f_low}{suf}**",
                ])
            if any(p in body_lower for p in patterns):
                hits.append(f)
            else:
                misses.append(f)
        frac = len(hits) / len(required_fields)
        total_score += frac
        per.append({
            "title": cand["title"],
            "hits": hits,
            "misses": misses,
            "score": round(frac, 4),
        })
    avg = total_score / len(candidates)
    return (avg, {"vacuous": False, "per_candidate": per})


def _count_candidate_credit(
    n: int,
    min_c: int,
    max_c: int,
    allow_empty: bool,
    allow_empty_satisfied: bool,
) -> tuple[float, str]:
    if allow_empty and n == 0 and allow_empty_satisfied:
        return (1.0, "in-range-empty-with-rationale")
    if min_c <= n <= max_c:
        return (1.0, "in-range")
    if n == min_c - 1 or n == max_c + 1:
        return (0.5, "one-off")
    return (0.0, "out-of-range")


def _check_empty_rationale(text: str) -> bool:
    """Heuristic: proposal explicitly states no candidates and gives rationale.

    Passes if the text contains any of several explicit empty-proposal
    markers - a "Total candidates: 0" line, or a phrase indicating the
    audit intentionally returned no proposals.
    """
    t = text.lower()
    markers = [
        "total candidates: 0",
        "total candidates: none",
        "no rewrite candidates",
        "no candidates identified",
        "returned no candidates",
        "no candidates meet",
    ]
    return any(m in t for m in markers)


def _score_vocabulary(
    candidates: list[dict[str, str]],
    valid_signals: set[str],
    valid_priorities: set[str],
    valid_meaning_preserved: set[str],
) -> tuple[float, dict[str, Any]]:
    """Three sub-checks averaged. Each sub-check is vacuous when no
    candidate declares the corresponding field.
    """
    signal_re = re.compile(r"\bR[1-9][0-9]?\b")
    priority_re = re.compile(r"\b(HIGH|MEDIUM|LOW)\b")

    signal_total = 0
    signal_valid = 0
    priority_total = 0
    priority_valid = 0
    meaning_total = 0
    meaning_valid = 0

    diag_signals: list[dict[str, Any]] = []
    diag_priorities: list[dict[str, Any]] = []
    diag_meaning: list[dict[str, Any]] = []

    for cand in candidates:
        body = cand.get("body", "")
        title = cand.get("title", "")
        body_lower = body.lower()

        # Signal labels on a "Signal" or "Signals" field line.
        for ln in body.splitlines():
            ls = ln.strip().lower()
            if ls.startswith("- signal") or ls.startswith("signal") or ls.startswith("- **signal"):
                for tok in signal_re.findall(ln):
                    signal_total += 1
                    ok = tok in valid_signals
                    if ok:
                        signal_valid += 1
                    diag_signals.append({"candidate": title, "label": tok, "ok": ok})

        # Priority: field line explicitly "Priority:" (not Priority rationale).
        for ln in body.splitlines():
            ls = ln.strip()
            ls_low = ls.lower()
            if (
                ls_low.startswith("- priority:")
                or ls_low.startswith("priority:")
                or ls_low.startswith("- **priority:**")
                or ls_low.startswith("**priority:**")
            ):
                for tok in priority_re.findall(ls.upper()):
                    priority_total += 1
                    ok = tok in valid_priorities
                    if ok:
                        priority_valid += 1
                    diag_priorities.append({"candidate": title, "value": tok, "ok": ok})

        # Meaning preserved: similar pattern.
        for ln in body.splitlines():
            ls = ln.strip().lower()
            if (
                ls.startswith("- meaning preserved:")
                or ls.startswith("meaning preserved:")
                or ls.startswith("- **meaning preserved:**")
                or ls.startswith("**meaning preserved:**")
            ):
                for tok in priority_re.findall(ln.upper()):
                    meaning_total += 1
                    ok = tok in valid_meaning_preserved
                    if ok:
                        meaning_valid += 1
                    diag_meaning.append({"candidate": title, "value": tok, "ok": ok})

    sub_scores: list[float] = []
    sub_diag: dict[str, Any] = {}
    if signal_total == 0:
        sub_scores.append(1.0)
        sub_diag["signals"] = {"vacuous": True}
    else:
        s = signal_valid / signal_total
        sub_scores.append(s)
        sub_diag["signals"] = {
            "vacuous": False,
            "valid": signal_valid,
            "total": signal_total,
            "per": diag_signals,
        }
    if priority_total == 0:
        sub_scores.append(1.0)
        sub_diag["priorities"] = {"vacuous": True}
    else:
        s = priority_valid / priority_total
        sub_scores.append(s)
        sub_diag["priorities"] = {
            "vacuous": False,
            "valid": priority_valid,
            "total": priority_total,
            "per": diag_priorities,
        }
    if meaning_total == 0:
        sub_scores.append(1.0)
        sub_diag["meaning_preserved"] = {"vacuous": True}
    else:
        s = meaning_valid / meaning_total
        sub_scores.append(s)
        sub_diag["meaning_preserved"] = {
            "vacuous": False,
            "valid": meaning_valid,
            "total": meaning_total,
            "per": diag_meaning,
        }
    avg = sum(sub_scores) / len(sub_scores)
    return (avg, sub_diag)


def _check_forbidden_content_write(
    snapshot: dict[str, str],
    worktree_root: str | None,
    fixture_repo_dir: str | None,
) -> tuple[float, dict[str, Any]]:
    """Verify no content/** file was mutated, added, or deleted.

    Fixtures seed a `content/` corpus as the audit subject. A well-behaved
    run leaves those files exactly as seeded and writes no new content/
    files. We detect violations by comparing the post-run snapshot under
    content/ against the fixture's seeded shas:

      - a content/ path present post-run but absent from seed => violation
      - a content/ path with a changed sha => violation
      - a content/ path present in seed but absent post-run => violation

    If we cannot locate the seed (no fixture_repo_dir, or path does not
    exist), fall back to the conservative "any content/ path trips" check.
    """
    import hashlib as _h

    snapshot_content = {k: v for k, v in snapshot.items() if k.startswith("content/")}

    if not fixture_repo_dir:
        # Fallback: cannot distinguish seed from write; flag any content/
        # presence as a violation.
        hits = sorted(snapshot_content)
        if hits:
            return (0.0, {"vacuous": False, "violations": hits, "reason": "no_seed_baseline"})
        return (1.0, {"vacuous": False, "violations": []})

    seed_root = Path(fixture_repo_dir)
    seed_content_root = seed_root / "content"
    seed_shas: dict[str, str] = {}
    if seed_content_root.exists():
        for dp, _dns, fns in __import__("os").walk(seed_content_root):
            for n in fns:
                full = Path(dp) / n
                try:
                    data = full.read_bytes()
                except OSError:
                    continue
                rel = "content/" + str(full.relative_to(seed_content_root))
                seed_shas[rel] = _h.sha256(data).hexdigest()

    violations: list[str] = []
    for path, sha in snapshot_content.items():
        if path not in seed_shas:
            violations.append(f"added:{path}")
        elif seed_shas[path] != sha:
            violations.append(f"modified:{path}")
    for path in seed_shas:
        if path not in snapshot_content:
            violations.append(f"deleted:{path}")

    if violations:
        return (
            0.0,
            {
                "vacuous": False,
                "violations": sorted(violations),
                "seed_content_file_count": len(seed_shas),
            },
        )
    return (
        1.0,
        {
            "vacuous": False,
            "violations": [],
            "seed_content_file_count": len(seed_shas),
        },
    )


def score(trace: dict, fixture: dict) -> dict:
    runs = trace.get("runs") or []
    if not runs:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {"reason": "no_runs", "scorer_version": SCORER_VERSION},
            "scorer_version": SCORER_VERSION,
        }
    assert len(runs) == 1
    run = runs[0]
    snapshot = run.get("filesystem")
    if not isinstance(snapshot, dict):
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "no_filesystem_snapshot",
                "cli_status": run.get("status"),
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }
    snapshot_keys = set(snapshot.keys())
    worktree_root = run.get("worktree_root")

    expected = fixture.get("expected_outputs") or {}
    proposal_glob = expected.get("proposal_glob") or "docs/planning/representation-audit-*.md"
    proposal_min = int(expected.get("proposal_min_candidates", 3))
    proposal_max = int(expected.get("proposal_max_candidates", 10))
    required_sections = list(expected.get("required_sections") or [])
    required_candidate_fields = list(expected.get("required_candidate_fields") or [])
    valid_signals = set(expected.get("valid_signals") or _DEFAULT_VALID_SIGNALS)
    valid_priorities = set(expected.get("valid_priorities") or _DEFAULT_VALID_PRIORITIES)
    valid_meaning_preserved = set(
        expected.get("valid_meaning_preserved") or _DEFAULT_VALID_MEANING_PRESERVED
    )
    allow_empty = bool(expected.get("allow_empty_with_rationale", False))
    forbidden_content_write = bool(expected.get("forbidden_content_write", True))

    # --- w_proposal_presence ---
    proposal_path = _match_proposal(snapshot_keys, proposal_glob)
    proposal_present = proposal_path is not None
    presence_credit = 1.0 if proposal_present else 0.0
    presence_detail: dict[str, Any] = {
        "vacuous": False,
        "glob": proposal_glob,
        "matched_path": proposal_path,
    }

    proposal_text = _read_text(worktree_root, proposal_path) if proposal_path else ""

    # --- w_sections ---
    if not required_sections:
        sections_credit = 1.0
        sections_detail: dict[str, Any] = {"vacuous": True, "hits": 0, "total": 0}
    else:
        text_lines = proposal_text.splitlines()
        hits = 0
        missing: list[str] = []
        for req in required_sections:
            if any(line.startswith(req) for line in text_lines):
                hits += 1
            else:
                missing.append(req)
        sections_credit = hits / len(required_sections)
        sections_detail = {
            "vacuous": False,
            "hits": hits,
            "total": len(required_sections),
            "missing": missing,
        }

    # --- w_candidate_count (computed before fields so empty-with-rationale
    #     can mark fields vacuous) ---
    candidates = _parse_candidates(proposal_text) if proposal_text else []
    n_candidates = len(candidates)
    allow_empty_satisfied = _check_empty_rationale(proposal_text) if proposal_text else False
    count_credit, count_tier = _count_candidate_credit(
        n_candidates, proposal_min, proposal_max, allow_empty, allow_empty_satisfied
    )

    # --- w_candidate_fields ---
    # If the fixture legitimately allows an empty proposal and the
    # proposal states the empty rationale, the per-candidate-fields axis
    # is vacuous (there are no candidates to check fields on and the
    # emptiness is expected).
    if allow_empty and n_candidates == 0 and allow_empty_satisfied:
        cand_field_credit = 1.0
        cand_field_detail = {
            "vacuous": True,
            "per_candidate": [],
            "reason": "empty_with_rationale",
        }
    else:
        cand_field_credit, cand_field_detail = _score_candidate_fields(
            candidates, required_candidate_fields
        )
    count_detail: dict[str, Any] = {
        "vacuous": False,
        "observed": n_candidates,
        "min": proposal_min,
        "max": proposal_max,
        "tier": count_tier,
        "allow_empty_with_rationale": allow_empty,
        "empty_rationale_found": allow_empty_satisfied,
    }

    # --- w_vocabulary ---
    vocab_credit, vocab_detail = _score_vocabulary(
        candidates, valid_signals, valid_priorities, valid_meaning_preserved
    )

    # --- w_forbidden ---
    if forbidden_content_write:
        fixture_repo_dir = run.get("fixture_repo_dir")
        forbidden_credit, forbidden_detail = _check_forbidden_content_write(
            snapshot, worktree_root, fixture_repo_dir
        )
    else:
        forbidden_credit = 1.0
        forbidden_detail = {"vacuous": True, "violations": []}

    primary_raw = (
        _W_PROPOSAL_PRESENCE * presence_credit
        + _W_SECTIONS * sections_credit
        + _W_CANDIDATE_FIELDS * cand_field_credit
        + _W_CANDIDATE_COUNT * count_credit
        + _W_VOCABULARY * vocab_credit
        + _W_FORBIDDEN * forbidden_credit
    )
    primary = max(0.0, min(1.0, primary_raw))

    diagnostic: dict[str, Any] = {
        "proposal_presence": presence_detail,
        "sections": sections_detail,
        "candidate_fields": cand_field_detail,
        "candidate_count": count_detail,
        "vocabulary": vocab_detail,
        "forbidden": forbidden_detail,
        "candidates_parsed": len(candidates),
        "snapshot_file_count": len(snapshot_keys),
        "scorer_version": SCORER_VERSION,
    }

    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
