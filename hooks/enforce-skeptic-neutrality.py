#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that mechanically enforces the Skeptic-brief
         neutrality requirement (content/references/skeptic-protocol.md §7
         "Neutrality requirement") AT SPAWN TIME, not after the review
         returns. Before this hook, a conductor-composed steer baked into a
         Skeptic spawn's Global-context field 7 ("Conductor spawn brief")
         or adversarial brief could poison the review by naming a specific
         suspected root cause, file, or conclusion as the conductor's own
         belief - the reviewer then confirms the steer rather than
         independently finding it.

         **PRIMARY deny surface: field 7 is a structural conformance
         check, not a phrase scan.** Field 7's own mandated label
         (content/agents/skeptic.md) is "claim-bearing text only," and
         content/sections/04-risk-classification.md's provenance test
         already requires every claim to carry one of three canonical
         tags. `field7_violation()` enforces that contract directly: any
         non-exempt sentence in field 7 that carries no provenance tag, no
         attribution marker, and no self-referential ticket mention is
         denied, regardless of its wording. This closes a defect class no
         phrase-category scan can express by construction - two real
         Skeptic spawns issued during this ticket's own DS-187 session
         were independently flagged for exactly this shape (an untagged
         factual claim in field 7), and both scored ZERO against every
         phrase category tried across six prior rounds of this hook's
         design (see the DS-187 architect plan's "New evidence driving
         the reframe" section for the executed proof).

         Field 7 is exempt from the structural rule only when its whole
         joined value is exactly `n/a` or one of the canonical enumerated
         `n/a - <reason>` strings this repo's spawn templates use
         (`_CANONICAL_NA_STRINGS`) - otherwise every individual sentence
         must carry a tag/attribution/self-reference, checked PER
         SENTENCE via `_split_sentences_keep_trailing_tag` so a tag on one
         sentence never exempts a different, untagged sentence.

         **The structural rule does NOT apply to the brief region.**
         Proven, not assumed: feeding all 10 canonical §8 adversarial-
         brief templates (content/references/skeptic-protocol.md §8)
         through `field7_violation()` denies every one of them, since none
         carry provenance tags - correctly so, per their own stated
         purpose as verbatim (or adapted, per §8's own "Adapt them"
         instruction) domain threat-model prose, not claim-bearing text.
         The brief region instead keeps a narrow phrase-deny - categories
         B and C only - proven zero-collision against all 10 templates
         and across six rounds of adversarial testing. Categories A, D,
         and E from earlier rounds are deleted: A and E are fully
         subsumed by the field-7 structural rule (any untagged assertion,
         regardless of phrasing, is already denied there), and D was
         never confirmed against a real spawn (advisory-only, invented to
         match a synthetic fixture). See the architect plan's "Categories
         A, D, E: deleted, with rationale" for the full justification.

         A genuine "Resolved issues preflight" HEADING (line-anchored,
         mandatory colon) is stripped from the prompt before extraction
         (`_strip_preflight_block`), because that section legitimately
         quotes historical steers verbatim for context and must never be
         scanned as if it were the conductor's own current claim. This is
         intentionally NOT a free-floating phrase match: an earlier
         version of this strip matched any MENTION of the phrase, not
         just the heading, and either truncated a legitimate tagged claim
         or silently deleted a genuine steer positioned after the
         mention, depending on which side of the match it fell on.

Public API: Run as a Claude Code PreToolUse hook (matcher: "Task" or
            "Agent"), fires only when `tool_input.subagent_type ==
            "skeptic"`. Reads JSON from stdin, writes hookSpecificOutput
            JSON to stdout only on deny, exits 0 always (fail-open on any
            malformed input). `field7_violation`, `extract_brief`,
            `extract_field7`, and the two brief-region category regexes
            (`_CAT_B`, `_CAT_C`) are also imported directly by
            bin/tests/test_enforce_skeptic_neutrality.py for content-
            equality and violation-content assertions.

Upstream deps: Python 3 stdlib only (json, os, re, sys, importlib.util for
               the best-effort `lib/enforcement_log.py` import). No
               subprocess, no network, no third-party packages.

Downstream consumers: Claude Code hook runner (PreToolUse event for Task
                      and Agent tools, matching enforce-tier.py's dual-
                      matcher wiring). Wired via ~/.claude/settings.json by
                      .claude/install.sh using the GUARDED command form
                      (`test -f <path> && python3 <path> || exit 0`) - a
                      bare `python3 {path}` would exit 2 (BLOCKING on
                      PreToolUse) if this file were ever removed while the
                      registration survives, denying every guarded Skeptic
                      spawn. `.agentic/.enforcement-fires.jsonl` (via
                      `lib/enforcement_log.py`) records every deny and
                      every allow_advisory row for calibration.

Failure modes:
    - Malformed stdin, non-dict tool_input, non-Task/Agent tool_name, or
      subagent_type != "skeptic": fail-open (exit 0), no scanning.
    - Kill switch (`AE_SKEPTIC_NEUTRALITY_GUARD_DISABLE=1`) set: fail-open
      (exit 0) BEFORE any extraction or log_fire call, checked strictly
      first - a check placed after violation detection but before
      dispatch would be inert (no log_fire happens during detection,
      only at dispatch); placed after dispatch it would leave fire-log
      rows appearing despite the kill switch being set.
    - Adversarial-brief marker not found: only the field-7 region is
      scanned; an advisory row is logged naming the reduced coverage
      (`_ADVISORY_BRIEF_MISSING`). Never denies on a missing marker alone.
    - Field-7 marker not found: only the brief region is scanned, with a
      distinct advisory (`_ADVISORY_FIELD7_MISSING`).
    - Neither marker found: two advisory rows logged (one per missing
      marker), zero rules applied, exit 0.
    - Field 7's 3-line/1-paragraph extraction cap can truncate a long
      multi-sentence claim, leaving its tail unscanned - a disclosed,
      real false-negative risk under this DENY-primary design (more
      consequential than under the prior advisory-only design). No
      real-session evidence yet shows field-7 values commonly exceeding
      this window; widen if that changes.
    - A tag anywhere in a brief-region paragraph exempts every claim in
      that SAME paragraph (bounded to <=5 lines) from categories B and
      C - a disclosed, bounded residual matching prior rounds' scope
      decision.
    - The brief region retains only a phrase-based residual (categories
      B, C), not structural conformance - §8's own "Adapt them"
      instruction makes a verbatim/whitespace-normalized brief-template
      match infeasible for real use (would deny the majority of
      legitimate spawns). A controlled-vocabulary composed-extension
      system is a named, deferred follow-up, not implemented here.
    - Best-effort dynamic import of `lib/enforcement_log.py` for
      `log_fire()`; any import error falls back to a no-op, matching
      every other enforce-*.py hook's fire-logging pattern. A lost
      telemetry row never affects the allow/deny decision.
    - Any other unexpected exception during processing: fail-open (exit
      0), matching every sibling enforce-*.py hook's outer try/except
      convention.

Performance: < 5 ms per call (no subprocess, a handful of bounded regex
             scans over a small extracted window, one small JSON append
             under `.agentic/` on deny/advisory only).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

KILL_SWITCH_ENV = "AE_SKEPTIC_NEUTRALITY_GUARD_DISABLE"

# --------------------------------------------------------------------------- #
# Extraction regexes (order-independent by construction)
# --------------------------------------------------------------------------- #
_BRIEF_START_RE = re.compile(r'\*{0,2}Adversarial brief[^:\n]{0,40}:\*{0,2}', re.IGNORECASE)
_FIELD7_START_RE = re.compile(
    r'(?:^|\n)\s*(?:(?:7\.|[-*])\s*)?\*{0,2}\s*Conductor spawn brief[^:\n]{0,80}:\*{0,2}',
    re.IGNORECASE,
)
_STRUCTURAL_STOP_RE = re.compile(
    r'^\s*(##|\*{0,2}(What to review|Resolved issues preflight|Adversarial brief|'
    r'Conductor spawn brief)|[1-7]\.\s)',
    re.IGNORECASE,
)

# --------------------------------------------------------------------------- #
# Preflight-strip (line-anchored heading, not a free-floating phrase match)
# --------------------------------------------------------------------------- #
_PREFLIGHT_START_RE = re.compile(
    r'(?:^|\n)[ \t]*\*{0,2}Resolved\s+issues\s+preflight\*{0,2}[ \t]*:[ \t]*\*{0,2}[ \t]*(?=\n|$)',
    re.IGNORECASE,
)
_OTHER_STRUCTURAL_RE = re.compile(
    r'\n\s*(##|\*{0,2}(What to review|Adversarial brief|Conductor spawn brief)\*{0,2})',
    re.IGNORECASE,
)


def _strip_preflight_block(prompt: str) -> str:
    """Strips ONLY a genuine preflight SECTION HEADING occupying its own
    line (mandatory colon; \\s+ between words tolerates a hard-wrap
    splitting the phrase across a line break), never a mid-sentence
    MENTION of the phrase - an earlier free-floating phrase match with no
    line-anchor and no mandatory colon either truncated legitimate tagged
    content or silently deleted a genuine steer, depending on which side
    of the match it fell on."""
    m = _PREFLIGHT_START_RE.search(prompt)
    if not m:
        return prompt
    tail = prompt[m.end():]
    m2 = _OTHER_STRUCTURAL_RE.search(tail)
    end = m.end() + (m2.start() if m2 else len(tail))
    return prompt[:m.start()] + prompt[end:]


# --------------------------------------------------------------------------- #
# Bounded region extraction
# --------------------------------------------------------------------------- #
_MAX_LINES_PER_PARAGRAPH = 3          # field 7
_MAX_LINES_PER_PARAGRAPH_BRIEF = 5    # brief region
_BRIEF_MAX_PARAGRAPHS = 2             # tolerates a "type: <label>**" tail then a separate paragraph
_FIELD7_MAX_PARAGRAPHS = 1            # field 7 is a single inline bracketed value per the template


def _extract_bounded_region(prompt: str, start_re, max_paragraphs: int,
                             max_lines_per_para: int) -> list[str] | None:
    """Never searches forward for a specific downstream heading; only
    recognizes ANY known structural marker (`_STRUCTURAL_STOP_RE`) as a
    stop condition, so extraction behaves identically regardless of which
    section order a given template puts after the marker."""
    m = start_re.search(prompt)
    if not m:
        return None
    lines = prompt[m.end():].split("\n")
    paragraphs, i, n = [], 0, len(lines)
    for _ in range(max_paragraphs):
        if i < n and lines[i].strip() == "":
            i += 1
        para = []
        while i < n and len(para) < max_lines_per_para:
            line = lines[i]
            if line.strip() == "":
                break
            if _STRUCTURAL_STOP_RE.match(line):
                i = n
                break
            para.append(line)
            i += 1
        if para:
            paragraphs.append(" ".join(l.strip() for l in para))
        if i >= n:
            break
    return paragraphs if paragraphs else None


def extract_brief(prompt: str) -> list[str] | None:
    return _extract_bounded_region(_strip_preflight_block(prompt), _BRIEF_START_RE,
                                    _BRIEF_MAX_PARAGRAPHS, _MAX_LINES_PER_PARAGRAPH_BRIEF)


def extract_field7(prompt: str) -> list[str] | None:
    return _extract_bounded_region(_strip_preflight_block(prompt), _FIELD7_START_RE,
                                    _FIELD7_MAX_PARAGRAPHS, _MAX_LINES_PER_PARAGRAPH)


# --------------------------------------------------------------------------- #
# Shared exemption markers (provenance tag, attribution, self-ref ticket)
# --------------------------------------------------------------------------- #
_PROVENANCE_RE = re.compile(r'\[verified:|\[verified-local:|\[per\s+\S+.*?,\s*unverified\]',
                             re.IGNORECASE)
_ATTRIBUTION_RE = re.compile(r'\bPer\s+(the\s+)?(Engineer|Architect|Investigator|QA-Engineer|conductor)\b'
                              r'|DONE_WITH_CONCERNS', re.IGNORECASE)
_SELF_REF_TICKET_RE = re.compile(r'\bDS-\d+\s+is\s+(the\s+)?(ticket|PR|unit|issue)\b', re.IGNORECASE)


def _paragraph_exempt(paragraph: str) -> bool:
    """Brief-region exemption, PARAGRAPH scope - a tag anywhere in the
    captured paragraph exempts every claim within that same paragraph
    (bounded to <=5 lines), not just the one it annotates. Used only by
    the brief-region category B/C check."""
    return bool(_PROVENANCE_RE.search(paragraph) or _ATTRIBUTION_RE.search(paragraph)
                or _SELF_REF_TICKET_RE.search(paragraph))


# --------------------------------------------------------------------------- #
# Field 7: PRIMARY structural conformance rule
# --------------------------------------------------------------------------- #
_CANONICAL_NA_STRINGS = {
    "n/a - Trivial direct edit",
    "n/a - permission-blocked carve-out",
    "n/a - Brief tier (per-consumer lives in architect plan path above)",
    "n/a - non-shared-utility surface (importer count below 5 threshold)",
    "n/a - architect plan deferred to Plan-tier second pass",
    "n/a - Skeptic-on-Brief (Brief is the artifact under review)",
    "n/a - Skeptic-on-plan (Brief authoring gated on this sign-off)",
    "n/a - single Elevated unit (no Brief required by the promotion gate)",
    "n/a - architect skipped (judgment-based: well-understood, self-contained change)",
    "n/a - architect skipped (mechanical: simple/targeted-unit metric)",
    "n/a - assembled Plan review (per-unit plans listed inline)",
    "n/a - Worker was self-directed with no conductor-composed brief text beyond a ticket ID reference",
    "n/a - internal scaffolding artifact (no conductor claim-bearing brief text distinct from the artifact itself)",
}


def _field7_is_exempt_na(text: str) -> bool:
    s = text.strip()
    return s == "n/a" or s in _CANONICAL_NA_STRINGS


# Splits on sentence-ending punctuation NOT immediately followed by a bracket
# tag (so "<claim>. [tag]" stays one unit), AND after a closing "]" followed
# by a capitalized word (so two consecutive tagged claims separate correctly
# instead of merging, which would let sentence 1's tag falsely cover
# sentence 2's untagged claim - a splitter bug found and fixed during this
# design: the original form never split after a closing "]", so two
# consecutive tagged sentences merged into one unit and an untagged second
# sentence went undetected).
_SENT_SPLIT_RE = re.compile(r'(?<=[.?!])\s+(?!\[)|(?<=\])\s+(?=[A-Z])')


def _split_sentences_keep_trailing_tag(text: str) -> list[str]:
    raw = _SENT_SPLIT_RE.split(text.strip())
    out: list[str] = []
    for frag in raw:
        frag = frag.strip()
        if not frag:
            continue
        if out and re.fullmatch(r'\[[^\]]*\]\.?', frag):
            out[-1] = out[-1] + " " + frag
        else:
            out.append(frag)
    return out


def field7_violation(field7_paragraphs: list[str] | None) -> str | None:
    """PRIMARY DENY RULE. Permitted field-7 content is EXACTLY: (a) an
    exempt n/a value (bare 'n/a' or one of the canonical enumerated
    strings, checked over the WHOLE joined field), or (b) one or more
    sentences, EACH individually carrying a provenance tag, an
    attribution marker, or a self-referential ticket mention. The tag
    check is PER SENTENCE - a tag on one sentence does not exempt a
    different, untagged sentence. Returns the first untagged sentence, or
    None if clean.

    Deliberately NOT applied to the brief region - see this module's
    Purpose docstring and the architect plan's proof that all 10 §8
    templates would deny under this rule despite carrying no violation
    under their own stated purpose."""
    if not field7_paragraphs:
        return None
    joined = " ".join(field7_paragraphs)
    if _field7_is_exempt_na(joined):
        return None
    for sent in _split_sentences_keep_trailing_tag(joined):
        if not (_PROVENANCE_RE.search(sent) or _ATTRIBUTION_RE.search(sent)
                or _SELF_REF_TICKET_RE.search(sent)):
            return sent
    return None


# --------------------------------------------------------------------------- #
# Brief region: narrow phrase-deny, categories B and C only
# --------------------------------------------------------------------------- #
_CAT_B = re.compile(r'\bI\s+(think|believe|suspect|bet|am confident)\b', re.IGNORECASE)
_CAT_C = re.compile(r'\b(construct the case where|build the case (that|where)|look hard at)\b',
                     re.IGNORECASE)

_BRIEF_CATEGORIES = (("B", _CAT_B), ("C", _CAT_C))


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #
def _field7_deny_reason(sentence: str) -> str:
    return (
        f"Agent/Task spawn blocked: field 7 (Conductor spawn brief) contains an "
        f"untagged sentence: {sentence!r}. Field 7's own mandated label is "
        "'claim-bearing text only' - per content/sections/04-risk-classification.md's "
        "provenance test, every claim in it must carry one of the three canonical "
        "tags ([verified: file:line] / [per <agent>, unverified] / "
        "[verified-local: <path> - reason]) or be attributed to a named subagent "
        "('Per <Agent>' / DONE_WITH_CONCERNS). Fix: add the appropriate tag, or "
        "replace the field with 'n/a - <reason>' if there is nothing claim-bearing "
        "to disclose. To disable this guard for this session: set "
        f"{KILL_SWITCH_ENV}=1 and restart."
    )


def _brief_deny_reason(category: str, matched: str) -> str:
    return (
        f"Agent/Task spawn blocked: adversarial brief text matches a banned "
        f"conductor-composed steer shape (category {category}): {matched!r}. "
        "Per content/references/skeptic-protocol.md §7 'Neutrality requirement', "
        "the brief must not name a specific suspected root cause or construction "
        "as the conductor's own belief. Fix: delete the sentence and use one of "
        "the 10 canonical templates in §8, or restate it as an attributed "
        "subagent claim ('Per <Agent>: ...'). To disable this guard for this "
        f"session: set {KILL_SWITCH_ENV}=1 and restart."
    )


_ADVISORY_BRIEF_MISSING = (
    "Adversarial brief marker not found - brief region not scanned. "
    "Coverage reduced for this spawn."
)
_ADVISORY_FIELD7_MISSING = (
    "Conductor spawn brief (field 7) marker not found - field-7 region "
    "not scanned. Coverage reduced for this spawn."
)


def _load_log_fire():
    """Best-effort dynamic import of the shared fire-logging helper.

    Mirrors the identical lazy, try/except-wrapped import pattern used by
    every sibling enforce-*.py hook (see enforce-tier.py, enforce-skeptic-
    round-cap.py) - a missing or broken sibling module must never crash
    this hook."""
    try:
        import importlib.util as _ilu

        here = Path(__file__).resolve().parent
        mod_path = here / "lib" / "enforcement_log.py"
        spec = _ilu.spec_from_file_location("enforcement_log", str(mod_path))
        mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)
        return mod.log_fire
    except Exception:
        return lambda *a, **k: None


def _deny(data: dict, reason: str) -> None:
    # Decision print comes FIRST, unconditionally. Telemetry is loaded and
    # called only after the decision has reached stdout, and is wrapped in
    # its own try/except so a raising log_fire can never suppress or
    # follow this deny - matches every sibling enforce-*.py hook.
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    try:
        _load_log_fire()(data, "enforce-skeptic-neutrality", "deny", reason)
    except Exception:
        pass
    sys.exit(0)


def _log_advisory(data: dict, reason: str) -> None:
    try:
        _load_log_fire()(data, "enforce-skeptic-neutrality", "allow_advisory", reason)
    except Exception:
        pass


def main() -> None:
    # Kill-switch checked FIRST, before any extraction or log_fire call, so
    # it suppresses BOTH deny paths and every allow_advisory logging path.
    if os.environ.get(KILL_SWITCH_ENV) == "1":
        sys.exit(0)

    try:
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        if not isinstance(data, dict):
            sys.exit(0)

        tool_name = data.get("tool_name")
        if tool_name not in ("Task", "Agent"):
            sys.exit(0)

        raw_tinput = data.get("tool_input")
        if not isinstance(raw_tinput, dict):
            sys.exit(0)
        tinput = raw_tinput

        if tinput.get("subagent_type") != "skeptic":
            sys.exit(0)

        prompt = tinput.get("prompt")
        prompt_text = prompt if isinstance(prompt, str) else ""

        brief_paragraphs = extract_brief(prompt_text)
        field7_paragraphs = extract_field7(prompt_text)

        if brief_paragraphs is None:
            _log_advisory(data, _ADVISORY_BRIEF_MISSING)
        if field7_paragraphs is None:
            _log_advisory(data, _ADVISORY_FIELD7_MISSING)

        if field7_paragraphs:
            violation = field7_violation(field7_paragraphs)
            if violation:
                _deny(data, _field7_deny_reason(violation))  # exits

        if brief_paragraphs:
            for para in brief_paragraphs:
                if _paragraph_exempt(para):
                    continue
                for name, pat in _BRIEF_CATEGORIES:
                    m = pat.search(para)
                    if m:
                        _deny(data, _brief_deny_reason(name, m.group(0)))  # exits

        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open).
        sys.exit(0)


if __name__ == "__main__":
    main()
