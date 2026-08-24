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
         joined value is EXACTLY ONE sentence matching the shape `n/a -
         <non-empty, bracket-free reason>` (`_field7_is_exempt_na` /
         `_NA_WITH_REASON_RE`) - per skeptic-protocol.md:299/:330, the
         enumerated reason strings this repo's spawn templates most often
         use are canonical PREFERRED WORDING, not an exhaustive whitelist,
         and a truthful non-enumerated reason is equally valid; a bare
         `n/a` is explicitly INVALID per the same protocol section and is
         therefore NOT exempt here, falling through to the per-sentence
         check below (where it is denied as an untagged, non-exempt
         sentence). Two additional bypasses were found by execution and
         are now closed by the same bounding: an `n/a - <reason>` clause
         followed by any FURTHER sentence is no longer exempt (the field's
         value must be that one sentence and nothing else - an appended
         untagged claim now falls through and is denied on its own
         merits), and a reason containing a bracket character is no longer
         exempt (closes a smuggling path where a bracket that narrowly
         missed the exact-literal neutrality-note match below could carry
         an untagged claim inside it while still reading as a compliant
         `n/a - <reason>` prefix).
         Otherwise every individual sentence must carry a
         tag/attribution/self-reference, checked PER SENTENCE via
         `_split_sentences_keep_trailing_tag` so a tag on one sentence
         never exempts a different, untagged sentence - this per-sentence
         scope is field-7-specific and is NOT shared with the brief
         region's exemption, which is PARAGRAPH-scoped
         (`_paragraph_exempt`).

         Field 7's own mandated template line
         (content/commands/ds-skeptic.md) appends a fixed, non-claim-
         bearing "[Neutrality: ... See skeptic-protocol.md Section 7
         'Neutrality requirement'.]" instructional note after the
         conductor's actual value on every spawn. `field7_violation()`
         strips this EXACT boilerplate before evaluating the field
         (`_strip_field7_neutrality_note`) - unstripped, this note's own
         closing bracket denied every template-conforming spawn,
         including a compliant bare `n/a - Trivial direct edit`. The
         strip requires an exact, whitespace-tolerant match of the full
         literal note text (`_NEUTRALITY_NOTE_TEXT`), not merely that
         three required substrings all appear somewhere inside the same
         bracket - a prior looser version of this strip (three
         substrings joined by unbounded filler) was found by execution to
         silently discard a bracket carrying a smuggled untagged claim
         alongside those same three substrings, so any bracket that
         deviates from the exact wording - smuggled content included - is
         now left in place and denies normally; see this hook's test file
         for the executed proof, both for a near-miss bracket and for the
         smuggled-content case.

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

         Retirement condition (Pillar-8 naming obligation, hooks/AGENTS.md
         §Registering a new enforce-*.py hook): the field-7 structural rule
         retires when EITHER (a) every Skeptic-spawn prompt is generated by
         tooling that structurally guarantees a provenance tag on every
         field-7 sentence before the prompt ever reaches this hook (making
         its deny path permanently unreachable), OR (b)
         content/agents/skeptic.md's field-7 provenance mandate is itself
         deleted or narrowed to no longer require every claim to carry one
         of the three canonical tags. The brief-region categories B and C
         retire independently, on a separate condition: when the deferred
         brief-region structural-conformance follow-up ticket (see
         "Categories A, D, E: deleted, with rationale" above) ships and
         supersedes the phrase-deny with a structural check.

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
            `extract_field7`, `extract_field7_ex` (the truncation-aware
            variant `main()` itself calls), and the two brief-region
            category regexes (`_CAT_B`, `_CAT_C`) are also imported
            directly by bin/tests/test_enforce_skeptic_neutrality.py for
            content-equality and violation-content assertions.

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
    - Field 7's 3-line/1-paragraph extraction cap can still truncate a
      long multi-sentence claim. THIS ROUND FIXES the direction of that
      risk: a truncated field 7 no longer denies on an incomplete
      fragment (a FALSE-POSITIVE deny, confirmed live by execution
      against a 6-line hard-wrapped, fully-tagged value whose tag landed
      on line 6 and was cut by the cap) - `_extract_bounded_region_ex`
      now reports whether the cap was hit with more content following,
      and `main()` downgrades to `_ADVISORY_FIELD7_TRUNCATED` rather than
      denying whenever that flag is set. The residual that remains is the
      inverse, weaker-severity direction: a truncated field 7 that
      genuinely IS untagged is no longer caught either (a FALSE-NEGATIVE
      miss, advisory-only) - a hook that cannot see the whole field
      cannot prove it untagged in either direction, and denying was
      judged the more dangerous failure mode of the two. No real-session
      evidence yet shows field-7 values commonly exceeding this window;
      widen the cap if that changes.
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
    - `_SENT_SPLIT_RE`'s abbreviation guard (`e.g.`/`i.e.`/`etc.`/`vs.`/
      `cf.`/`et al.`) is a fixed, non-exhaustive list - an abbreviation
      outside this list that ends mid-sentence in a period can still be
      mis-split, the same class of false positive this round fixed for
      the six listed forms. No real-session evidence yet shows a
      seventh form recurring; extend the list if that changes.
    - EXACTLY ONE disclosed, NOT fixed, false negative remains as of this
      round - re-counted and RE-VERIFIED BY EXECUTION THIS ROUND (see
      the direct `field7_violation()` call against a quoted-tag-syntax
      fixture in bin/tests/test_enforce_skeptic_neutrality.py's
      `test_provenance_re_substring_match_false_negative_residual`), not
      restated from a prior round's claim. A prior round's identical
      "EXACTLY TWO disclosed" attestation was FALSE when written - it
      both mis-stated the count (a third defect, the field-7 truncation
      false-POSITIVE deny below, was live and undisclosed in that
      direction) and mis-stated one residual's direction (the prior
      round's own text called `_BRIEF_START_RE`'s unanchored/first-match
      behavior a "coverage shift", when live execution that round showed
      it producing an outright false-positive DENY on a spawn whose real
      brief was clean). Both the truncation false-positive-deny defect
      and the `_BRIEF_START_RE` false-positive-deny defect are FIXED this
      round (line-anchored + last-occurrence extraction for the marker;
      truncation-flag advisory-downgrade for the cap) and are covered by
      regression tests with confirmed-failing-pre-fix mutations, not
      merely re-labeled as residuals. The one that remains, lower
      severity because it is a false NEGATIVE (a bypass, not a false
      deny) rather than a false positive: `_PROVENANCE_RE` matches the
      literal substring `[verified:` / `[verified-local:` anywhere in a
      sentence, so a sentence that merely quotes tag syntax as an example
      (rather than genuinely carrying a tag of its own) reads as exempt.
      Fixing it requires parsing the wrapping bracket's own
      well-formedness (e.g. confirming the tag is the sentence's own
      trailing annotation, not prose describing tag syntax) - a
      materially larger structural change than this round's scope;
      tracked as a named residual, not silently absorbed.
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
# Line-anchored (mirrors _FIELD7_START_RE's own `(?:^|\n)\s*` prefix) AND
# extracted via `_extract_bounded_region_ex(..., use_last_match=True)`,
# which takes the LAST occurrence, not the first - a prior unanchored,
# first-match version let a pasted block of
# Worker output (or any prose) quoting an earlier, unrelated "Adversarial
# brief:" mention shift the scanned window onto that quoted text instead of
# the conductor's real, current brief for THIS spawn, denying (or falsely
# clearing) a spawn based on content the conductor never composed. See
# test_brief_marker_last_occurrence_not_first for the executed proof and
# its reddening mutation.
_BRIEF_START_RE = re.compile(
    r'(?:^|\n)\s*\*{0,2}Adversarial brief[^:\n]{0,40}:\*{0,2}', re.IGNORECASE
)
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


def _extract_bounded_region_ex(prompt: str, start_re, max_paragraphs: int,
                                max_lines_per_para: int,
                                use_last_match: bool = False) -> tuple[list[str] | None, bool]:
    """Never searches forward for a specific downstream heading; only
    recognizes ANY known structural marker (`_STRUCTURAL_STOP_RE`) as a
    stop condition, so extraction behaves identically regardless of which
    section order a given template puts after the marker.

    `use_last_match` selects the LAST regex match of `start_re` in `prompt`
    instead of the first - used by the brief region (see `_BRIEF_START_RE`'s
    comment) so a quoted, historical mention of the marker ahead of the
    real one never shifts the scanned window.

    Returns `(paragraphs, truncated)`. `truncated` is True when the FIRST
    captured paragraph hit `max_lines_per_para` while further non-blank,
    non-structural-stop content immediately followed it in the prompt -
    i.e. the window closed before the logical unit actually ended, so the
    captured fragment cannot be treated as the complete field value. Field
    7's PRIMARY deny rule (`field7_violation`) downgrades to an advisory
    log rather than a deny when this is True, since a hook that cannot see
    the whole field cannot prove it untagged."""
    if use_last_match:
        matches = list(start_re.finditer(prompt))
        m = matches[-1] if matches else None
    else:
        m = start_re.search(prompt)
    if not m:
        return None, False
    lines = prompt[m.end():].split("\n")
    paragraphs, i, n = [], 0, len(lines)
    truncated = False
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
            if len(para) == max_lines_per_para and i < n:
                nxt = lines[i]
                if nxt.strip() != "" and not _STRUCTURAL_STOP_RE.match(nxt):
                    truncated = True
        if i >= n:
            break
    return (paragraphs if paragraphs else None), truncated


def _extract_bounded_region(prompt: str, start_re, max_paragraphs: int,
                             max_lines_per_para: int) -> list[str] | None:
    """Back-compat shim over `_extract_bounded_region_ex` - drops the
    truncation flag. Kept because bin/tests/test_enforce_skeptic_neutrality.py
    calls this directly (scenario 18's mutation proof) expecting a bare
    list-or-None return."""
    paragraphs, _truncated = _extract_bounded_region_ex(
        prompt, start_re, max_paragraphs, max_lines_per_para
    )
    return paragraphs


def extract_brief(prompt: str) -> list[str] | None:
    paragraphs, _truncated = _extract_bounded_region_ex(
        _strip_preflight_block(prompt), _BRIEF_START_RE,
        _BRIEF_MAX_PARAGRAPHS, _MAX_LINES_PER_PARAGRAPH_BRIEF, use_last_match=True
    )
    return paragraphs


def extract_field7_ex(prompt: str) -> tuple[list[str] | None, bool]:
    """Field-7 counterpart to `extract_brief` that also surfaces the
    truncation flag `main()` needs to decide deny vs. advisory-downgrade."""
    return _extract_bounded_region_ex(
        _strip_preflight_block(prompt), _FIELD7_START_RE,
        _FIELD7_MAX_PARAGRAPHS, _MAX_LINES_PER_PARAGRAPH
    )


def extract_field7(prompt: str) -> list[str] | None:
    paragraphs, _truncated = extract_field7_ex(prompt)
    return paragraphs


# --------------------------------------------------------------------------- #
# Shared exemption markers (provenance tag, attribution, self-ref ticket)
# --------------------------------------------------------------------------- #
_PROVENANCE_RE = re.compile(r'\[verified:|\[verified-local:|\[per\s+\S+.*?,\s*unverified\]',
                             re.IGNORECASE)

# content/agents/skeptic.md:30 states the attribution carve-out is OPEN,
# not a fixed roster: "an Engineer's DONE_WITH_CONCERNS concerns, an
# architect's recommended adversarial brief, or ANY OTHER NAMED AGENT'S
# OWN RETURN passed through as written". A prior round's closed 5-name
# enumeration (Engineer|Architect|Investigator|QA-Engineer|conductor)
# denied 14 of the 18 agents under content/agents/ - e.g. "Per the
# Debugger, ..." or "Per the Skeptic, ..." - even though `skeptic.md`
# explicitly sanctions exactly that shape, and the hook's OWN
# `_brief_deny_reason` prescribes this pass-through as its remedy,
# denying an operator a second time for following it. Fixed to a
# roster derived from the CURRENT `content/agents/*.md` file set
# (`_KNOWN_AGENT_SLUGS` below) rather than a hand-picked subset, kept in
# sync by `bin/tests/test_enforce_skeptic_neutrality.py`'s
# `test_attribution_regex_covers_every_current_agent_file`, which
# re-derives the live directory listing at TEST TIME and fails if this
# hardcoded tuple falls behind it. Deliberately NOT a live directory
# read inside this hook at RUNTIME: the DS-54 hooks-snapshot mechanism
# (scripts/lib/hooks-snapshot.sh's `hooks_source_paths`) copies only
# hooks/, bin/ds-identity, and the four in-scope adapters' hook sources
# into the deployed `~/.agentic/hooks-snapshot/` dir that installed
# hook commands actually execute from - never content/ - so a runtime
# read of content/agents/ would silently find nothing once a session
# runs from the snapshot rather than from the live checkout, a strictly
# worse failure mode than the closed-set gap this fixes.
_KNOWN_AGENT_SLUGS = (
    "adr-drift-detector", "adr-generator", "architect", "debugger",
    "dependency-auditor", "engineer", "goal-condition-evaluator",
    "investigator", "learning-extractor", "learnings-agent",
    "orchestration-planner", "perf-analyst", "product-discovery",
    "qa-engineer", "release-orchestrator", "security-auditor",
    "skeptic", "wrap-ticket",
)


def _slug_to_name_pattern(slug: str) -> str:
    """Converts a hyphenated agent slug (e.g. 'qa-engineer') into a regex
    alternative tolerating however a conductor writes the display name -
    hyphenated, spaced, or any capitalization ('QA-Engineer', 'QA
    Engineer', 'qa engineer') - case-folding is applied by the compiled
    pattern's re.IGNORECASE flag, not here."""
    return r'[-\s]+'.join(re.escape(part) for part in slug.split('-'))


_ATTRIBUTION_RE = re.compile(
    r'\bPer\s+(the\s+)?(?:' +
    '|'.join(_slug_to_name_pattern(_s) for _s in _KNOWN_AGENT_SLUGS) +
    r'|conductor)\b'
    r'|DONE_WITH_CONCERNS',
    re.IGNORECASE,
)
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
# skeptic-protocol.md:299 ("This list is not exhaustive: a situation none of
# them covers may supply its own 'n/a - <reason>' string") and :330 ("A
# truthful, specific rationale that is NOT one of the enumerated strings
# above is valid and must NOT be BLOCKED on that basis alone") both state
# the enumerated set is canonical PREFERRED WORDING for recurring
# situations, never an exhaustive whitelist. A closed-set membership check
# (a prior round's `_CANONICAL_NA_STRINGS`) denied every protocol-valid
# non-enumerated reason - fixed by a SHAPE check instead: any
# `n/a - <non-empty reason>` is exempt, regardless of the reason's exact
# wording (this hook cannot judge truthfulness/specificity - that
# assessment is the Skeptic's own Step 0 job, per the same protocol
# section).
#
# BOUNDED two ways, both closing a real bypass found by execution:
# (1) `[^\[\]\n]+` forbids a bracket character inside the reason, so a
#     bracket that narrowly misses the exact-literal neutrality-note match
#     below (see `_FIELD7_NEUTRALITY_NOTE_RE`) can never smuggle an
#     untagged claim through this exemption merely by trailing a
#     protocol-valid-looking `n/a - <reason>` prefix - e.g. `n/a - Trivial
#     direct edit [Neutrality: <smuggled root-cause claim> - see
#     skeptic-protocol.md Section 7 "Neutrality requirement".]` denies.
# (2) `_field7_is_exempt_na` requires the WHOLE joined field to be
#     EXACTLY ONE sentence per `_split_sentences_keep_trailing_tag` before
#     testing this regex - a prior version had no such bound and matched
#     `re.DOTALL` across the ENTIRE remaining string via a trailing `.*$`,
#     so `n/a - Trivial direct edit. <any untagged claim>.` was exempt in
#     full: the primary deny surface was silently disabled for any field-7
#     value merely PREFIXED with a valid-looking n/a clause. Requiring
#     exactly one sentence means a second, appended sentence instead falls
#     through to the per-sentence loop below, where it is denied on its
#     own merits like any other untagged claim.
_NA_WITH_REASON_RE = re.compile(r'^n/a\s*-\s*[^\[\]\n]+$', re.IGNORECASE)


def _field7_is_exempt_na(text: str) -> bool:
    """Exempt iff the whole joined field is EXACTLY ONE sentence, and that
    sentence is `n/a - <reason>` with a non-empty, bracket-free reason.
    Deliberately does NOT exempt a bare `n/a`: skeptic-protocol.md:299
    states "A bare `n/a` is invalid - every `n/a` value MUST carry a
    specific reason", and :330 requires the Skeptic to BLOCK on a bare
    `n/a`. A bare `n/a` therefore falls through to the per-sentence
    structural check below, where it is denied as an untagged, non-exempt
    sentence - conforming to the protocol rather than inverting it in the
    permissive direction (a prior round's behavior). Likewise, an `n/a -
    <reason>` clause followed by ANY additional sentence, or carrying a
    bracket inside the reason itself, is NOT exempt - both are real
    bypasses found by execution against the prior, unbounded version of
    this check (see `_NA_WITH_REASON_RE`'s comment above)."""
    s = text.strip()
    sentences = _split_sentences_keep_trailing_tag(s)
    if len(sentences) != 1:
        return False
    return bool(_NA_WITH_REASON_RE.match(sentences[0]))


# The template line this hook enforces against (content/commands/ds-skeptic.md
# field 7) appends a fixed, non-claim-bearing instructional note AFTER the
# conductor's actual value on every spawn: '[Neutrality: provenance-tagged
# factual claims only - never a conductor hypothesis or suspicion. See
# skeptic-protocol.md Section 7 "Neutrality requirement".]'. Executed against
# the unmodified hook, this note's OWN closing bracket denied every
# template-conforming spawn, including a bare "n/a - Trivial direct edit"
# plus the note. Stripped here, but ONLY when the bracket is a
# whitespace-normalized match of this EXACT literal wording - a prior
# version instead required only that three substrings ("Neutrality:",
# "skeptic-protocol.md", "Section 7", "Neutrality requirement") all appear
# somewhere inside the same bracket, joined by `[^\]]*?` filler of
# arbitrary content. Executed proof of the bypass that opened: a bracket
# reading '[Neutrality: <smuggled root-cause claim> - see
# skeptic-protocol.md Section 7 "Neutrality requirement".]' still contains
# all three required substrings, so the entire bracket - smuggled claim
# included - was silently discarded before the untagged-sentence check
# ever ran, on a value the conductor's own field-7 text made look like a
# compliant `n/a - <reason>` plus the template's own note. Fixed to an
# exact-literal match (`_NEUTRALITY_NOTE_TEXT` below, whitespace-tolerant
# only) so a bracket carrying ANY additional or substituted content next
# to the three required substrings is left in place, unstripped, and
# denies normally via the per-sentence check (or, for an `n/a`-prefixed
# value, via `_NA_WITH_REASON_RE`'s bracket-free requirement). See
# test_neutrality_note_strip_is_not_a_generic_bracket_escape and
# test_neutrality_note_strip_rejects_smuggled_content_inside_bracket for
# the proof.
# Trailing period on "Neutrality requirement"." is deliberately EXCLUDED
# from this literal and made optional in `_FIELD7_NEUTRALITY_NOTE_RE`
# below (`\.?`), and `_TYPOGRAPHIC_NORMALIZE_TABLE` folds curly quotes/
# em-/en-dashes to their ASCII equivalents before matching - both close a
# punctuation-variance bypass found by execution: a conductor who
# hand-retyped the note (dropping the final period, or via an editor that
# auto-"smart-quotes") produced a bracket that did not match the prior
# exact-literal strip, so the bracket was left in place and its OWN
# closing bracket then denied via `_NA_WITH_REASON_RE`'s bracket-free
# requirement - a false-positive deny on an otherwise-compliant `n/a -
# <reason>` value differing only in incidental punctuation, not content.
# The normalization is 1-char-for-1-char (never changes string length),
# so the matched span's offsets in the NORMALIZED copy apply unchanged to
# the ORIGINAL text when slicing it out in `_strip_field7_neutrality_note`
# - deliberately not a blanket typo-tolerant match: any OTHER deviation
# (a substituted word, added content) still fails to match and denies
# normally, per the smuggling-closure rationale above.
_NEUTRALITY_NOTE_TEXT = (
    'Neutrality: provenance-tagged factual claims only - never a conductor '
    'hypothesis or suspicion. See skeptic-protocol.md Section 7 '
    '"Neutrality requirement"'
)

_TYPOGRAPHIC_NORMALIZE_TABLE = str.maketrans({
    '\u2018': "'", '\u2019': "'",   # curly single quotes -> straight
    '\u201c': '"', '\u201d': '"',   # curly double quotes -> straight
    '\u2013': '-', '\u2014': '-',   # en-dash/em-dash -> hyphen
})


def _literal_to_whitespace_tolerant_pattern(text: str) -> str:
    """Escapes `text` for regex use, then collapses each escaped literal
    space run back into `\\s+` so the match tolerates incidental
    whitespace/line-wrap variance without loosening what content is
    permitted between the required words."""
    escaped = re.escape(text)
    return re.sub(r'(\\ )+', r'\\s+', escaped)


_FIELD7_NEUTRALITY_NOTE_RE = re.compile(
    r'\s*\[\s*' + _literal_to_whitespace_tolerant_pattern(_NEUTRALITY_NOTE_TEXT) + r'\.?\s*\]\s*$',
    re.IGNORECASE,
)


def _strip_field7_neutrality_note(text: str) -> str:
    normalized = text.translate(_TYPOGRAPHIC_NORMALIZE_TABLE)
    m = _FIELD7_NEUTRALITY_NOTE_RE.search(normalized)
    if not m:
        return text
    return (text[:m.start()] + text[m.end():]).rstrip()


# Splits on sentence-ending punctuation NOT immediately followed by a bracket
# tag (so "<claim>. [tag]" stays one unit), AND after a closing "]" followed
# by a capitalized word (so two consecutive tagged claims separate correctly
# instead of merging, which would let sentence 1's tag falsely cover
# sentence 2's untagged claim - a splitter bug found and fixed during this
# design: the original form never split after a closing "]", so two
# consecutive tagged sentences merged into one unit and an untagged second
# sentence went undetected). The four negative lookbehinds guard against a
# SECOND splitter bug (found this round): a period ending a common
# abbreviation ("e.g.", "i.e.", "etc.", "vs.", "cf.", "al." as in "et al.")
# is sentence-ending punctuation by the bare [.?!] test, so a single,
# fully-tagged-or-attributed sentence that merely contains one of these
# abbreviations mid-sentence was incorrectly split into two fragments and
# the tail fragment (with no tag of its own) was falsely denied as
# untagged. Each abbreviation lookbehind is independently fixed-width, so
# they chain legally even though the abbreviations differ in length.
# Each abbreviation lookbehind is SCOPED case-insensitive via the inline
# (?i:...) flag group, not a compile-wide re.IGNORECASE - a compile-wide
# flag would also case-fold the `[A-Z]` lookahead on the second alternative,
# reintroducing the exact splitter-merge bug this regex was fixed for (any
# lowercase word after a closing "]" would then also split, no longer
# distinguishing a genuinely new sentence from mid-value bracket noise).
_SENT_SPLIT_RE = re.compile(
    r'(?<!(?i:e\.g\.))(?<!(?i:i\.e\.))(?<!(?i:etc\.))(?<!(?i:vs\.))(?<!(?i:cf\.))(?<!(?i:al\.))'
    r'(?<=[.?!])\s+(?!\[)'
    r'|(?<=\])\s+(?=[A-Z])'
)


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
    exempt n/a value - the WHOLE joined field is exactly ONE sentence of
    the shape 'n/a - <reason>' with a non-empty, bracket-free reason (a
    bare 'n/a' is explicitly NOT exempt, and neither is an 'n/a -
    <reason>' clause followed by any additional sentence, or one whose
    reason itself contains a bracket - see `_field7_is_exempt_na` and
    `_NA_WITH_REASON_RE` for the two real bypasses this bounding closes),
    or (b) one or more sentences, EACH individually carrying a provenance
    tag, an attribution marker, or a self-referential ticket mention. The
    tag check is PER SENTENCE - a tag on one sentence does not exempt a
    different, untagged sentence. Returns the first untagged sentence, or
    None if clean.

    The field's own fixed trailing "[Neutrality: ...]" template boilerplate
    (see `_strip_field7_neutrality_note`) is stripped before any check, so
    it can never itself read as an untagged claim or falsely close off a
    real one's tag.

    Deliberately NOT applied to the brief region - see this module's
    Purpose docstring and the architect plan's proof that all 10 §8
    templates would deny under this rule despite carrying no violation
    under their own stated purpose."""
    if not field7_paragraphs:
        return None
    joined = _strip_field7_neutrality_note(" ".join(field7_paragraphs))
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
_ADVISORY_FIELD7_TRUNCATED = (
    "Conductor spawn brief (field 7) exceeded the 3-line extraction window "
    "before the value's logical end - the captured fragment cannot be "
    "proven untagged, so the field-7 structural rule was skipped and this "
    "spawn was allowed rather than denied on a possibly-incomplete view. "
    "Coverage reduced for this spawn."
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
        field7_paragraphs, field7_truncated = extract_field7_ex(prompt_text)

        if brief_paragraphs is None:
            _log_advisory(data, _ADVISORY_BRIEF_MISSING)
        if field7_paragraphs is None:
            _log_advisory(data, _ADVISORY_FIELD7_MISSING)

        if field7_paragraphs:
            if field7_truncated:
                # Extraction window closed before the field's logical end -
                # the captured fragment cannot be proven untagged, so this
                # hook downgrades to advisory rather than deny (see
                # `_extract_bounded_region_ex`'s docstring and
                # `_ADVISORY_FIELD7_TRUNCATED`).
                _log_advisory(data, _ADVISORY_FIELD7_TRUNCATED)
            else:
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
