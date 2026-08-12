"""
Purpose: Spec gate enforcing the return-contract compliance shapes defined in
         content/references/subagent-return-contract.md on every
         content/agents/*.md file: each of the four recognized shapes
         (tagged prose fields, structured schema-object return, fixed
         literal-line template, fixed markdown-sectioned flat report) has
         its own affirmative obligation, checked mechanically per shape.
         A file's deliverable being a file it writes (not a conductor-parsed
         return) is the sole exemption category.

Public API: check_contract(text, filename, shape=None) -> list[str]
            (violations; empty list means compliant) - dispatches to the
            per-shape checker (check_shape1/2/3/3_skeptic/4) below based on
            SHAPE_ASSIGNMENTS[filename], or an explicit `shape` override for
            fixture-based tests. Also collected as pytest test functions.

Upstream dependencies: content/agents/*.md (real agent files, dispatched via
            SHAPE_ASSIGNMENTS/EXEMPT_FILE_ARTIFACT below);
            bin/tests/fixtures/agent_return_contract/*.md (fixtures used to
            verify each checker's logic independent of the real corpus);
            bin/tests/fixtures/agent_return_contract/
            expected_violations_snapshot.json (round-5: the exact per-file
            violation-string snapshot loaded into EXPECTED_VIOLATIONS -
            see generate_agent_return_contract_snapshot.py for how this
            file is regenerated);
            content/references/subagent-return-contract.md (read directly
            at test time via CONTRACT_REF_PATH, round-6 addition).

Downstream consumers: .github/workflows/bin-tests.yml python-bin-tests job,
            which runs `pytest bin/tests/ -q` - full-directory glob
            discovery, no per-file wiring required for a new test_*.py file.
            The same job also floors test_agent_return_contract_mutation.py's
            collected test count (round-5 structural change 3).

Failure modes: pure static analysis, no I/O beyond reading .md files under
            this repo.
            SHAPE_ASSIGNMENTS dispatches every real agent file that HAS a
            recognized return-contract shape to its shape's checker.
            EXPECTED_VIOLATIONS (round-5, replaces the NOT_YET_MIGRATED
            boolean allowlist retired this round) pins the EXACT violation
            set per file - test_expected_violations_snapshot_matches_reality
            fails loudly, by name, on either a violation silently
            disappearing (laxness) or a new one silently appearing
            (over-strictness); a boolean allowlist could only ever detect
            "flagged vs not flagged", not which specific violations fired.
            EXEMPT_FILE_ARTIFACT separately tracks files whose deliverable is
            a file they write to disk, not a conductor-parsed return - never
            expected to gain a shape at all.
            Round-2 Major fix (both silent-pass vectors relocated from a
            round-1 Critical, not merely worded differently):
            (a) the section-START scan is now fence-aware on the same basis
                as the section-END scan - a fenced illustrative example
                containing a recognized heading earlier in the file no
                longer wins the match.
            (b) _fenced_spans no longer assumes fences are balanced - an odd
                fence-marker count is DETECTED and reported as a loud
                violation (never silently mis-paired, which previously
                truncated a section before reaching a genuinely
                non-compliant field - see
                fixtures/unbalanced_fence_truncates_section_agent.md).
            Round-2 Minor fix: CAP_RE is now anchored to the tag bracket's
            own extra text (`tag_extra`, the content between
            `[MECHANICAL,` and `]`), never the field's full header_text -
            a cap-shaped phrase in the field's TITLE (e.g. "Coverage of max
            10 items") or in a parenthetical pointing elsewhere (e.g.
            "(see cap: 300 chars in Rules)") no longer false-positives as a
            declared cap - see fixtures/cap_false_positive_agent.md.
            Round-4 fixes (four Majors + Minors, all reproduced by a
            mutation harness in test_agent_return_contract_mutation.py
            BEFORE being fixed - see that file for the pre-fix survivor
            list):
            (M1) SHAPE2_PASSTHROUGH_EXEMPT_FIELDS deleted outright - it
                manufactured engineer.md's compliant-now status via an
                exemption with a falsified rationale (no downstream
                consumer forwards pr_description_body verbatim).
                engineer.md is back in NOT_YET_MIGRATED.
            (M2) check_shape3_skeptic's six-prefix presence check is now
                scoped to the '## Sign-off format' section text only, not
                the whole file - the old whole-file search let a prose
                mention of a validated line's label elsewhere (e.g. the
                Reading-your-spawn-prompt guard at line 50 that literally
                quotes "Findings:") mask a retagged/altered template line.
                The template-smuggling guard (previously a dead `pass`
                loop) now actually raises a violation when the cap
                sentence is found inside the Sign-off format template
                itself instead of the Calibration section.
            (M3) _shape2_is_bounded now recurses into 'object' and
                'array_of_object' top-level fields instead of returning
                True unconditionally - every nested 'key: value' leaf line
                (object member, array-of-object item member, or a member
                nested two levels deep) now carries its own enum/cap/
                one-line/pointer obligation. SHAPE2_CAP_KEYWORDS_RE now
                requires an adjacent digit (mirrors Shape 1's CAP_RE
                discipline - a bare 'max'/'cap' keyword no longer
                satisfies the obligation) and recognizes 'truncated (to)'
                as a cap keyword (engineer.md's raw_output field). A leaf
                whose value is itself a '|'-delimited list (e.g.
                'lint: pass | fail | not_run') is recognized as bounded
                regardless of field name, not only for CLASSIFICATION_FIELD
                _NAME_RE matches. SHAPE2_POINTER_RE no longer accepts a
                bare '.md' substring as a declared bound (too loose - any
                incidental file-path mention satisfied it); only the
                explicit 'defined in'/'defined once' pointer phrasing
                counts.
            (M4) check_shape4's cap requirement is now unconditional for
                every placeholder in every subsequent '##' sub-section -
                the SHAPE4_NARRATIVE_HINT_RE heuristic (which/what/why/...)
                is deleted. A cap keyword with no adjacent digit no longer
                satisfies the requirement (same digit discipline as M3).
            (Minor) FENCE_RE now recognizes '~~~' fences and fences
                indented under a list item (both live in the real corpus:
                qa-engineer.md's '~~~qa-knowledge-json' block,
                investigator.md's indented ' ```bash ' blocks under
                numbered steps) in addition to column-0 backtick fences.
            (Minor) test_shape2_engineer_is_contract_compliant renamed and
                repurposed: engineer.md is no longer contract-compliant
                (M1), and the prior docstring's raw_output-cap claim is now
                independently VERIFIED (via M3's recursion) rather than
                merely asserted alongside a since-corrected compliant-now
                verdict.
            CORRECTION (round-5): the M3 paragraph above claimed
                "SHAPE2_CAP_KEYWORDS_RE now requires an adjacent digit" -
                this was FALSE. The round-4 code required a cap keyword
                AND a digit to both appear ANYWHERE in the same combined
                line+body text, with no adjacency check at all; the
                violation message made the same false claim. Round 5
                fixes this for real - see below.
            Round-5 fixes (structural rewrite, not another permissive
            branch - see the four falsifying probes below, each
            independently confirmed RED post-fix, plus four new
            regression mutations added to MUTATIONS in
            test_agent_return_contract_mutation.py):
            (1) Every leaf-boundedness check (Shape 2's schema leaves,
                Shape 3's literal-line values, Shape 4's report
                placeholders) now goes through the SAME closed set of
                seven explicitly named forms (see the block above
                CLASSIFICATION_FIELD_NAME_RE): enum list, true-adjacent
                numeric cap, fixed-length spec ('40-char'), one-line
                marker, schema/doc pointer, bounded-by-nature value
                literal, nullable-type placeholder. Anything matching
                none of these fails by default - there is no remaining
                shape-level auto-pass. Specifically: `_shape2_is_bounded`
                no longer returns True unconditionally for the 'scalar'
                shape (probe: 'note: <full narrative account with no
                declared bound at all>' now correctly flagged, where it
                previously passed unconditionally).
            (2) SHAPE_NUMERIC_CAP_RE requires the digit+unit to appear
                TRUE-adjacent to the cap keyword (immediately following
                it), not merely present anywhere in the combined text
                (probe: 'x: <full narrative; note that 3 records were
                truncated from the source system>' now correctly
                rejected).
            (3) _is_enum_list() replaces the bare '\\S+\\s*\\|\\s*\\S+'
                search: an enum is recognized only as (a) the value
                standing ALONE as a bare '|'-delimited token list, never
                inside a '<...>' narrative placeholder bracket, or (b) an
                explicit 'enum:' label preceding a pipe list (probe:
                'summary: <what happened | why it matters, unbounded>'
                now correctly rejected - it satisfies neither form).
            (4) SHAPE2_POINTER_RE now requires 'defined in'/'defined
                once' to be followed, within a short window, by a
                concrete '.md' path or the word 'schema' - not accepted
                bare anywhere (probe: 'x: <free-form prose, the term is
                defined in the glossary>' now correctly rejected).
            (5) check_shape4's placeholder loop now applies the same
                closed-whitelist check instead of an unconditional
                numeric-cap-only requirement - implementing the doc's
                actual Shape-4 scope ("every OTHER section WITH
                OPEN-ENDED FREE TEXT"), not "every placeholder
                unconditionally" (which round 4 had regressed to after
                deleting the gameable narrative-hint-word heuristic).
            (6) check_shape3 now inspects EVERY fenced block in the
                section, not just blocks[0] - goal-condition-evaluator.md
                has three templates, and the second's Evidence value
                ('"evaluator-error: <reason>"') was never checked before
                this fix. goal-condition-evaluator.md is RECLASSIFIED
                from compliant-now to genuinely non-compliant as a
                result (it was never actually fully compliant, only
                under-checked).
            (7) NOT_YET_MIGRATED (a boolean membership set) is RETIRED,
                replaced by an exact per-file expected-violations
                SNAPSHOT (bin/tests/fixtures/agent_return_contract/
                expected_violations_snapshot.json) - a boolean allowlist
                cannot detect a checker becoming more permissive (a
                violation silently disappearing) or more strict (a
                violation silently appearing) for a file that stays
                flagged either way, which is exactly the failure mode
                that shipped in rounds 1-4. See
                bin/tests/generate_agent_return_contract_snapshot.py for
                the deliberate, reviewed snapshot-update procedure.
            (8) The mutation catalog's size is now floored in CI
                (.github/workflows/bin-tests.yml, "floor collected
                test_agent_return_contract_mutation.py count") - removing
                an operator from MUTATIONS without shrinking the floor is
                caught, closing the gap where the suite went green with
                one operator deleted and `len(MUTATIONS) == 12` unchecked
                anywhere.
            CORRECTION (round-6): item (1) above claimed every
                leaf-boundedness check goes through "the SAME closed set
                of seven explicitly named forms." This was FALSE for two
                separate reasons, both now fixed (round-6 Major-3):
                `check_shape4` never consulted forms 4 (one-line marker)
                or 5-then/7-now (nullable-type) at all - only forms
                1/2/3/6(then) - so a form-4/7 placeholder in a Shape-4
                report was flagged even though the doc's "same whitelist"
                claim said it would pass; and `_shape3_value_bounded`
                consulted a THIRD, undocumented list that accepted none
                of forms 2/3/5(then)/6(then)/7(then) and added an EIGHTH,
                unnamed form of its own (any value containing no '<' is a
                "fully realized literal" - bounded by construction, no
                open narrative slot). Round-6 does not unify the three
                checkers' form sets (a genuinely bigger, riskier change
                for a narrow-tightening round) - it instead makes the
                per-shape divergence an explicit, named, and doc-matched
                fact: see the "Per-shape form usage" comment blocks above
                `check_shape2`, `check_shape3`/`check_shape3_skeptic`, and
                `check_shape4` below, and the identical per-shape lists in
                content/references/subagent-return-contract.md's
                "Compliance shapes" section - the two are meant to be
                diffed side by side, not merely both present.
            Round-6 fixes (three Majors + five Minors, each reproduced by
            a one-line Skeptic probe BEFORE being fixed - see the three
            new regression mutations added to MUTATIONS in
            test_agent_return_contract_mutation.py):
            (M1) `_SHAPE_TYPE_WORDS` (form 6, was form 7) no longer
                includes 'string'/'str'/'object'/'array' - a bare type
                declaration is not itself a bound (probe:
                'task_id: <string or null>' and 'branch_name: <string,
                or null>' both previously passed unconditionally via this
                form despite carrying no length/shape limit at all; now
                correctly flagged - see
                test_shape2_engineer_is_not_yet_migrated).
            (M2) The prior "form 5" (SHAPE2_POINTER_RE, an explicit
                schema/doc pointer) is DELETED OUTRIGHT, not narrowed - a
                fullmatch rewrite (the fix pattern used for form 6/"form
                6 was form 7") was considered and rejected: real corpus
                pointer phrasing is a full sentence embedded in
                narrative, with no clean fullmatch shape to anchor a
                whole-body match on without reintroducing the same
                proximity-window bypass (probe: 'x: <free narrative, see
                the format defined in our-conventions.md for tone
                guidance>' and 'x: <unbounded prose; tone is defined in
                the schema we use internally>' both previously passed;
                now correctly rejected - the form no longer exists to
                match either text). engineer.md's `learnings_candidate`
                was the sole load-bearing field for this form and is now
                correctly flagged.
            (M3) See the CORRECTION block immediately above - the
                "same closed whitelist everywhere" claim is fixed by
                accurate per-shape documentation (code manifest AND
                content/references/subagent-return-contract.md), not by
                forcing every shape through an identical form set.
            (Minor) `SHAPE_BOUNDED_VALUE_LITERALS` (form 5, was form 6)
                no longer includes 'message'/'commit message' - a commit
                message is not bounded by nature, unlike a SHA/URL/
                timestamp/tag (probe: release-orchestrator.md's
                '<sha> <message>' commit-listing lines now correctly flag
                the `<message>` half; the `<sha>` half stays bounded).
            (Minor) `check_shape3` now recognizes a bare closed-enum-
                shaped status token (all-caps identifier, no colon) as a
                valid, bounded Shape-3 line, via
                SHAPE3_BARE_STATUS_TOKEN_RE - not a "not a 'Label: value'
                line" violation. goal-condition-evaluator.md's escape-hatch
                `BLOCKED` line (content/agents/goal-condition-evaluator.md)
                is a standalone status literal by the template's own
                design, and flagging it was gate over-strictness, not a
                real gap; content/references/subagent-return-contract.md's
                Shape-3 definition is corrected in the same change to
                state this explicitly.
            (Minor) The falsified "of the 18 files, only 3 ... carry any
                'never omit any section' instruction" sentence in
                content/references/subagent-return-contract.md is DELETED
                (not narrowed-and-left-alongside-its-own-correction) -
                the accurate per-file enumeration is folded directly into
                the sentence it replaces (no numeral restated here, since
                this manifest comment is itself a fourth unpinned copy of
                that count and drifted stale once already), and the
                separate "Correction (2026-08-11, round 5)" paragraph
                correcting a sentence that no longer exists is removed
                with it.
            (Minor) content/references/subagent-return-contract.md's
                form-6-then/form-7-now vocabulary list is enumerated in
                full (no trailing '...') and now matches
                `_SHAPE_TYPE_WORDS` exactly post-M1 - both lists are the
                13 surviving words, same order.
            (Minor) Degenerate caps ('cap: 0 chars', 'max 1 item') are
                left passing, deliberately - a 0-char or 1-item cap is a
                syntactically valid, if unusual, declared bound; treating
                it as a violation would require guessing the author's
                intent rather than checking a structural property. Not
                observed anywhere in the real corpus as of round 6.

Performance: negligible - reads <30 small text files.
"""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_DIR = REPO_ROOT / "content" / "agents"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "agent_return_contract"

# Heading synonyms verified against the live content/agents/*.md corpus
# (not trusted from any prior description). Each of these headings was
# individually confirmed to introduce the agent's OWN return-contract
# section, not an unrelated section that merely shares vocabulary:
#   - "Output format"    - the majority case (debugger, architect, ...)
#   - "Sign-off format"  - skeptic.md:118, explicitly the agent's own
#                            structured return ("The conductor validates
#                            this format exactly.")
#   - "Report structure" - dependency-auditor.md, perf-analyst.md,
#                            release-orchestrator.md, each an explicit
#                            "output this exact report" instruction
#   - "Output templates" - product-discovery.md:157, the agent's own
#                            proposal-file templates
HEADING_SYNONYMS = (
    "Output format",
    "Sign-off format",
    "Report structure",
    "Output templates",
)
SECTION_START_RE = re.compile(
    r"^##\s+(?:" + "|".join(re.escape(h) for h in HEADING_SYNONYMS) + r")\s*$",
    re.MULTILINE,
)
# "### N. Return" workflow sub-steps (learning-extractor.md, learnings-agent.md,
# wrap-ticket.md) are a second recognized Shape-2 section anchor - the return
# is not a top-level "## Output format"-shaped section at all, but a numbered
# Workflow sub-step.
RETURN_SUBSTEP_RE = re.compile(r"^###\s+\d+\.\s+Return\s*$", re.MULTILINE)
SECTION_END_RE = re.compile(r"^##\s+\S", re.MULTILINE)
SUBSTEP_END_RE = re.compile(r"^##\s+\S|^###\s+\S", re.MULTILINE)
# Round-4 Minor fix: recognize '~~~' fences (live at
# qa-engineer.md:317,321,438,453,458,475,478,492) and fences indented under
# a list item (live at investigator.md:56,58,64,70,
# orchestration-planner.md:80), not only column-0 backtick fences - an
# unrecognized fence type is invisible to _fenced_spans, which can silently
# mis-pair every fence marker after it.
FENCE_RE = re.compile(r"^[ \t]*(?:```|~~~).*$", re.MULTILINE)
HEADER_RE = re.compile(r"^###\s+(.+)$", re.MULTILINE)
TAG_RE = re.compile(r"\[(MECHANICAL|ADVISORY)([^\]]*)\]")
CAP_RE = re.compile(
    r"\b(?:cap(?:ped)?\s*(?:at)?\s*[:\-]?\s*|<=\s*|max(?:imum)?\s*(?:of)?\s*)(\d+)\s*"
    r"(chars?|characters?|items?|steps?|entries|words)\b",
    re.IGNORECASE,
)

# --- Shape assignment (per amendment section 2 - verified against the live
# tree 2026-08-11, not trusted from the amendment's word alone: engineer.md
# and goal-condition-evaluator.md were independently re-read and confirmed
# compliant under their shape's checker; learning-extractor.md,
# learnings-agent.md, wrap-ticket.md, adr-drift-detector.md were
# independently re-read and confirmed to carry a real structured return
# under a "### N. Return" sub-step or "## Phase 6: Produce the Drift
# Report" heading - not "no such section under any name"; skeptic.md's
# six conductor-validated Sign-off format lines were confirmed verbatim
# against content/commands/ds-skeptic.md:68 and
# content/commands/ds-wrap.md:439,443.
# Unit 4 (return-contract migration) moved dependency-auditor.md and
# perf-analyst.md from Shape 1 to Shape 2: both retired their free-prose
# "## Report structure" narrative for the pointer JSON schema (report
# written to .agentic/audit-reports/ via Bash heredoc - neither agent has
# a Write/Edit grant - plus a small structured return), matching
# adr-drift-detector.md's own Shape 2 shape unchanged by this move. ---

SHAPE_ASSIGNMENTS = {
    # Shape 1 - tagged prose fields.
    "architect.md": 1,
    "debugger.md": 1,
    "investigator.md": 1,
    "orchestration-planner.md": 1,
    "product-discovery.md": 1,
    "security-auditor.md": 1,
    # Shape 2 - structured schema-object return.
    "engineer.md": 2,
    "learning-extractor.md": 2,
    "learnings-agent.md": 2,
    "wrap-ticket.md": 2,
    "adr-drift-detector.md": 2,
    "dependency-auditor.md": 2,
    "perf-analyst.md": 2,
    "qa-engineer.md": 2,
    # Shape 3 - fixed literal-line template.
    "goal-condition-evaluator.md": 3,
    "skeptic.md": 3,
    # Shape 4 - fixed markdown-sectioned flat report.
    "release-orchestrator.md": 4,
}

# Files whose deliverable is a file they write to disk (via Write/Edit), not
# a payload the conductor parses or gates on - and no downstream command
# file parses a conductor-facing return from them. adr-generator.md's
# output is the generated ADR document itself; confirmed (2026-08-11) via
# `grep -n "Output\|Return\|Report" content/agents/adr-generator.md`
# returning nothing - no return-to-conductor section under any name.
EXEMPT_FILE_ARTIFACT = {
    "adr-generator.md",
}

# --- Round-5 structural change 2: NOT_YET_MIGRATED (a boolean membership
# set) is RETIRED. A boolean allowlist can only ever say "this file is
# still non-compliant" - it cannot detect a checker becoming MORE
# permissive (violations silently disappearing) or MORE strict
# (violations silently appearing) for a file that stays on the list
# either way. Four consecutive rounds of THIS spec gate shipped exactly
# that failure mode: a permissive branch added to make the real corpus
# green, invisible to any test that only asks "is this file still
# flagged at all". The replacement is an exact per-file
# expected-violations SNAPSHOT (every violation string, not just a
# boolean) in
# bin/tests/fixtures/agent_return_contract/expected_violations_snapshot.json,
# loaded below and compared to the live checker output for every
# SHAPE_ASSIGNMENTS file in test_expected_violations_snapshot_matches_
# reality. ANY drift - a violation disappearing (widening/laxness) or a
# new one appearing (narrowing/over-strictness) - fails that test loudly
# and by name, and must be reviewed and re-approved deliberately via
# bin/tests/generate_agent_return_contract_snapshot.py (see that
# script's module docstring for the exact update procedure - it is
# deliberately NOT a silent one-command refresh). The mutation harness
# in test_agent_return_contract_mutation.py is kept alongside this,
# unchanged in purpose: the two are complementary, not redundant - the
# snapshot catches drift in the REAL corpus; the mutation harness proves
# the checker can still fire on synthetic non-compliant text the real
# corpus may never happen to contain.
EXPECTED_VIOLATIONS = json.loads(
    (FIXTURES_DIR / "expected_violations_snapshot.json").read_text()
)


class UnbalancedFenceError(ValueError):
    """Raised when a text span contains an odd number of ``` fence markers -
    the span cannot be reliably paired into open/close spans, so callers
    must surface this as a loud violation rather than guess a pairing."""


def _fenced_spans(text):
    """Return a list of (start, end) character spans covered by fenced
    ``` code blocks, pairing consecutive fence markers as open/close.

    Fences are REQUIRED to be balanced (an even marker count) - an odd
    count raises UnbalancedFenceError rather than silently pairing
    positionally, which previously mis-paired everything after the
    unbalanced marker and could truncate a section before reaching a
    genuinely non-compliant field (round-2 Major finding, vector b)."""
    marks = list(FENCE_RE.finditer(text))
    if len(marks) % 2 != 0:
        raise UnbalancedFenceError(
            f"odd number of fence markers ({len(marks)}) in this span - "
            "fences must be balanced to reliably determine section "
            "boundaries; refusing to guess a pairing"
        )
    return [
        (marks[i].start(), marks[i + 1].end())
        for i in range(0, len(marks), 2)
    ]


def _find_unfenced_match(pattern, text, fenced_spans):
    """Return the first match of `pattern` in `text` that does not fall
    inside any span in `fenced_spans`, or None."""
    for m in pattern.finditer(text):
        pos = m.start()
        if any(s <= pos < e for s, e in fenced_spans):
            continue
        return m
    return None


def extract_output_format_section(text):
    """Return the text of the agent's own return-contract section (matched
    via HEADING_SYNONYMS), or None if no recognized heading is present.

    Both the section START and the section END are fence-aware: a fenced
    illustrative example earlier in the file that happens to contain a
    recognized heading (e.g. inside a "do not do this" template) must not
    win the start match (round-2 Major finding, vector a) - the real
    corpus also embeds example '##'-level lines inside the very fence that
    documents the field template (e.g. debugger.md's
    '## Diagnosis: [...]'), which the END scan must correctly walk past.

    Raises UnbalancedFenceError if the whole-document fence count, or the
    post-heading remainder's fence count, is odd - callers must treat this
    as a loud violation.
    """
    fenced_whole = _fenced_spans(text)
    start_m = _find_unfenced_match(SECTION_START_RE, text, fenced_whole)
    if not start_m:
        return None
    rest = text[start_m.end():]
    fenced_rest = _fenced_spans(rest)
    end_m = _find_unfenced_match(SECTION_END_RE, rest, fenced_rest)
    if end_m is None:
        return rest
    return rest[:end_m.start()]


def extract_return_substep_section(text):
    """Return the text of a '### N. Return' Workflow sub-step (Shape 2's
    second recognized anchor for learning-extractor.md, learnings-agent.md,
    wrap-ticket.md), or None if no such sub-step heading is present.
    Fence-aware on the same basis as extract_output_format_section."""
    fenced_whole = _fenced_spans(text)
    start_m = _find_unfenced_match(RETURN_SUBSTEP_RE, text, fenced_whole)
    if not start_m:
        return None
    rest = text[start_m.end():]
    fenced_rest = _fenced_spans(rest)
    end_m = _find_unfenced_match(SUBSTEP_END_RE, rest, fenced_rest)
    if end_m is None:
        return rest
    return rest[:end_m.start()]


def extract_report_phase_section(text, heading_text):
    """Return the text under a literal '## <heading_text>' heading that is
    NOT one of HEADING_SYNONYMS (adr-drift-detector.md's
    '## Phase 6: Produce the Drift Report'), or None."""
    pattern = re.compile(
        r"^##\s+" + re.escape(heading_text) + r"\s*$", re.MULTILINE
    )
    fenced_whole = _fenced_spans(text)
    start_m = _find_unfenced_match(pattern, text, fenced_whole)
    if not start_m:
        return None
    rest = text[start_m.end():]
    fenced_rest = _fenced_spans(rest)
    end_m = _find_unfenced_match(SECTION_END_RE, rest, fenced_rest)
    if end_m is None:
        return rest
    return rest[:end_m.start()]


def extract_fields(section_text):
    """Return [(header_text, body_text), ...] for each '###' field in the section."""
    headers = list(HEADER_RE.finditer(section_text))
    fields = []
    for i, hm in enumerate(headers):
        header_text = hm.group(1).strip()
        body_start = hm.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(section_text)
        fields.append((header_text, section_text[body_start:body_end]))
    return fields


# --- Shape 1: tagged prose fields ---


def check_shape1(text, filename="<fixture>"):
    """Return a list of human-readable violation strings; [] means compliant."""
    try:
        section = extract_output_format_section(text)
    except UnbalancedFenceError as e:
        return [f"{filename}: {e}"]
    if section is None:
        return [
            f"{filename}: no recognized return-contract heading found "
            f"(tried: {', '.join(HEADING_SYNONYMS)})"
        ]
    fields = extract_fields(section)
    if not fields:
        return [f"{filename}: no '###' fields found in the Output format section"]

    violations = []
    for header_text, _body_text in fields:
        tag_m = TAG_RE.search(header_text)
        if not tag_m:
            violations.append(
                f"{filename}: field '{header_text}' has no [MECHANICAL] or "
                "[ADVISORY] tag"
            )
            continue

        tag, tag_extra = tag_m.group(1), tag_m.group(2)
        if tag == "ADVISORY":
            if "notes" not in header_text.lower():
                violations.append(
                    f"{filename}: field '{header_text}' is tagged [ADVISORY] but "
                    "is not folded under a 'Notes' header"
                )
            continue

        # MECHANICAL: enum fields are exempt from the numeric-cap requirement
        # (the enum's own closed value set is the bound).
        if "enum" in tag_extra.lower():
            continue

        # The cap must be anchored to the tag BRACKET's own extra text
        # (tag_extra, i.e. the content between "[MECHANICAL," and "]"),
        # never the field's full header_text. Anchoring to header_text lets
        # a cap-shaped phrase in the field's TITLE (e.g. "Coverage of max
        # 10 items [MECHANICAL]") or in a parenthetical pointing elsewhere
        # (e.g. "Findings [MECHANICAL] (see cap: 300 chars in Rules)")
        # false-positive as a declared cap when the tag bracket itself
        # declares none (round-2 Minor finding).
        if not CAP_RE.search(tag_extra):
            violations.append(
                f"{filename}: MECHANICAL field '{header_text}' declares no "
                "numeric cap inside its own [MECHANICAL, ...] tag bracket "
                "(expected e.g. '[MECHANICAL, cap: 500 chars]') and is not "
                "tagged 'enum'"
            )
    return violations


# --- Shape 2: structured schema-object return ---

CLASSIFICATION_FIELD_NAME_RE = re.compile(
    r"(?:^|_)(status|verdict|result|outcome[_-]?type|skipped[_-]?reason|decision)(?:_|$)",
    re.IGNORECASE,
)

# --- Round-5 rewrite: closed whitelist of recognized bound forms. ---
#
# Every leaf-boundedness check in this module (Shape 2's schema leaves,
# Shape 3's literal-line values, Shape 4's report placeholders) now goes
# through this same small set of explicitly named, independently
# falsifiable forms. A leaf is bounded ONLY when it matches one of these
# forms; anything unrecognized FAILS by default - there is no
# shape-level auto-pass left anywhere in this file (the round-4
# `_shape2_is_bounded` `return True` for the 'scalar' shape is removed;
# see `_shape2_is_bounded` below). A new bound syntax is added
# deliberately, by naming a new form here AND in the matching
# "Compliance shapes" list in
# content/references/subagent-return-contract.md - never by widening an
# existing pattern to silence a false positive.
#
# Form 1 - closed enum list, `_is_enum_list()`. Recognizes exactly two
# shapes: (a) the field's own value STANDS ALONE as a bare
# '|'-delimited list of simple tokens (no embedded spaces/commas per
# token) - e.g. 'DONE | FAILED | BLOCKED', 'pass | fail | not_run' - and
# never when the whole value is wrapped in a '<...>' narrative
# placeholder bracket; or (b) an explicit 'enum:' label (inline or on a
# '#'-prefixed comment line) precedes a '|'-delimited list, regardless
# of quoting - e.g. '# enum: null | "zero-substance" | "no-consumer"'.
# Round-5 fix: the prior ENUM_VALUE_LIST_RE (`\S+\s*\|\s*\S+`) matched a
# bare pipe ANYWHERE in the combined text, so
# 'summary: <what happened | why it matters, unbounded>' satisfied both
# the bound obligation and the closed-enum obligation purely because it
# contained ' | ' - neither form above accepts that text: it has no
# 'enum:' label, and the whole value is bracket-wrapped narrative, not a
# bare token list.
def _is_enum_list(text):
    t = text.strip()
    enum_label_m = re.search(r"\benum\s*:\s*(.+)$", t, re.IGNORECASE | re.MULTILINE)
    if enum_label_m and "|" in enum_label_m.group(1):
        return True
    if t.startswith("<") and t.endswith(">"):
        return False
    if "|" not in t:
        return False
    value_part = t.split("#", 1)[0].strip()
    if not value_part or "|" not in value_part:
        return False
    parts = value_part.split("|")
    if len(parts) < 2:
        return False
    for p in parts:
        p = p.strip()
        if not p or not re.fullmatch(r'"?[A-Za-z0-9_.\-]+"?', p):
            return False
    return True


# Form 2 - numeric cap with a keyword TRUE-adjacent to its digit.
# Round-5 fix: the prior SHAPE2_CAP_KEYWORDS_RE was a bare keyword
# search (cap/max/maxLength/truncated) combined with a SEPARATE
# `\d` search anywhere in the same combined line+body text
# (`_shape2_has_cap_with_digit`) - the code comment and the emitted
# violation string both claimed "adjacent digit", but nothing enforced
# adjacency: 'x: <full narrative; note that 3 records were truncated
# from the source system>' satisfied it (keyword 'truncated' and digit
# '3' both present, nowhere near each other). This pattern requires the
# digit and its unit to appear immediately after the keyword (mirrors
# Shape 1's CAP_RE discipline, which was always anchored this way).
SHAPE_NUMERIC_CAP_RE = re.compile(
    r"\b(?:cap(?:ped)?\s*(?:at)?\s*[:\-]?\s*|max(?:imum)?\s*(?:of)?\s*[:\-]?\s*|"
    r"maxLength\s*[:=]?\s*|truncated\s+to\s*[:\-]?\s*)"
    r"(\d+)\s*(chars?|characters?|items?|steps?|entries|words)\b",
    re.IGNORECASE,
)

# Form 3 - a fixed-length spec written as "<N>-char[acter][s]" (e.g.
# engineer.md's "full 40-char SHA") - a digit directly modifying "char"
# is itself an explicit, self-describing bound, distinct from the
# keyword-led cap form above.
SHAPE_FIXED_LENGTH_RE = re.compile(r"\b\d+-char(?:acter)?s?\b", re.IGNORECASE)

# Form 4 - a `<one-line ...>` / `<single-line ...>` placeholder marker -
# unchanged from prior rounds.
SHAPE2_ONE_LINE_RE = re.compile(r"<\s*(one|single)[- ]line\b", re.IGNORECASE)

# Round-6 Major-2 fix: the prior "form 5" (SHAPE2_POINTER_RE, an
# explicit schema/doc pointer: 'defined in'/'defined once' followed,
# within a short window, by a '.md' path or the word 'schema') is
# DELETED OUTRIGHT, not narrowed. It was a bypassable proximity
# heuristic even after the round-5 tightening: 'x: <free narrative, see
# the format defined in our-conventions.md for tone guidance>' and
# 'x: <unbounded prose; tone is defined in the schema we use
# internally>' both satisfied it, because the check never required the
# pointer phrasing to constitute the WHOLE placeholder body (unlike
# form 6/now-5 below, which is a strict fullmatch on the entire '<...>'
# content). A fullmatch-based rewrite was considered and rejected: real
# corpus pointer phrasing is a full sentence embedded in narrative
# prose (e.g. "entry shape, enum and cap are defined in
# references/learnings-capture-instruction.md"), not a value that
# stands alone as a placeholder body the way form 6 values do - there
# is no clean fullmatch shape to anchor on without reintroducing a
# proximity window. One fewer heuristic is worth more than the single
# snapshot entry (engineer.md's `learnings_candidate`) this was
# load-bearing for; that field is now correctly flagged unbounded and
# must take an explicit cap or one-line marker like any other field.
#
# Form 5 (was "form 6") - bounded-by-nature value-type placeholders: a
# '<...>' placeholder whose ENTIRE body (nothing more) names one of
# these well-known, syntactically-constrained value types is bounded by
# construction - it cannot carry open-ended narrative regardless of
# length, so no numeric cap is required. This is a closed enumeration
# of value TYPES (fullmatch, not substring), never a keyword-anywhere
# search - "<full narrative; note the sha format>" does NOT match,
# because the placeholder body as a whole is not one of these literal
# phrases. Extending this list is a deliberate, visible edit here plus
# a matching update to subagent-return-contract.md.
#
# Round-6 Minor fix: 'message' and 'commit message' are REMOVED. A
# commit message is not bounded by nature - it can be arbitrarily long
# narrative prose, unlike a SHA/URL/timestamp/tag, which each have an
# inherent syntactic ceiling. Real corpus impact:
# release-orchestrator.md's '<sha> <message>' commit-listing lines now
# correctly flag the `<message>` half as unbounded (the `<sha>` half
# stays bounded via 'sha' below).
SHAPE_BOUNDED_VALUE_LITERALS = frozenset({
    "sha", "from-sha", "to-sha", "commit sha",
    "url",
    "timestamp",
    "tag",
    "path", "repo-relative path", "file path",
    "environment name", "remote name",
    "exact command run", "exact rollback command",
    "count",
    "version",
})


def _strip_inline_comment(text):
    """Return the portion of `text` before any '#'-led inline comment,
    trimmed - a value's own placeholder must be matched against its
    real content, not a comment trailing it on the same physical line
    (e.g. engineer.md's 'task_id: <string or null>            # echoed
    from execution contract; null on single-unit')."""
    return text.split("#", 1)[0].strip()


def _is_bounded_value_literal(text):
    t = _strip_inline_comment(text)
    if t.startswith("<") and t.endswith(">"):
        t = t[1:-1].strip()
    return t.lower() in SHAPE_BOUNDED_VALUE_LITERALS


# Form 6 (was "form 7") - a nullable-type declaration `<TYPE or null>` (optionally
# `<TYPE, or null>`), where TYPE is 1-2 words drawn from a closed
# vocabulary of BOUNDED type names. This is a type annotation, not
# open-ended narrative - e.g. engineer.md's 'commit_sha: <full 40-char
# SHA, or null if no commit was made>' pattern generalized to a bare
# type word. TYPE is restricted to known type words specifically so
# this form cannot be gamed by appending " or null" to an otherwise-
# narrative placeholder ("<full narrative or null>" does NOT match -
# "full"/"narrative" are not type words).
#
# Round-6 Major-1 fix: 'string', 'str', 'object', and 'array' are
# REMOVED from this vocabulary. A type declaration is not itself a
# bound - 'string' and 'str' impose no length limit at all, and
# 'object'/'array' impose no shape/size limit either, so
# '<string or null>' and '<object or null>' are open-ended narrative
# wearing a type label, not a bounded form. This was a real gap, not
# hypothetical: engineer.md's 'task_id: <string or null>' and
# 'branch_name: <string, or null>' both matched this form pre-fix
# despite carrying no bound whatsoever - see
# test_shape2_engineer_is_not_yet_migrated's updated assertions. The
# surviving words below are all themselves syntactically bounded
# (a number/boolean/date/timestamp has an inherent format ceiling; the
# remaining string-shaped words - sha/url/path/tag/id/name - are
# narrow, well-known identifier shapes, not open narrative).
_SHAPE_TYPE_WORDS = frozenset({
    "number", "int", "integer", "boolean", "bool",
    "date", "timestamp", "sha", "url", "path", "tag", "id", "name",
})
_SHAPE_NULLABLE_TYPE_RE = re.compile(
    r"^<\s*([\w\s]{1,30}?),?\s+or\s+null\s*>$", re.IGNORECASE
)


def _is_nullable_type_placeholder(text):
    m = _SHAPE_NULLABLE_TYPE_RE.match(_strip_inline_comment(text))
    if not m:
        return False
    words = m.group(1).lower().split()
    return 1 <= len(words) <= 2 and all(w in _SHAPE_TYPE_WORDS for w in words)


def _shape2_has_cap_with_digit(text):
    """True when a cap-shaped keyword is TRUE-adjacent to its digit+unit
    (SHAPE_NUMERIC_CAP_RE), or the text carries an explicit fixed-length
    spec (SHAPE_FIXED_LENGTH_RE, e.g. '40-char'). See the round-5
    docstrings on those two patterns above for what changed and why."""
    return bool(SHAPE_NUMERIC_CAP_RE.search(text)) or bool(
        SHAPE_FIXED_LENGTH_RE.search(text)
    )


TOP_LEVEL_YAML_KEY_RE = re.compile(r"^(\w+):(.*)$")
TOP_LEVEL_JSON_KEY_RE = re.compile(r'^  "(\w+)":(.*?),?$')
# Round-4 M3 fix: matches a 'key: value' line at ANY indentation depth
# (object member, array-of-object item member via a leading '- ', or a
# member nested two levels deep) - used to recurse into 'object' and
# 'array_of_object' top-level fields, which previously returned True
# unconditionally without inspecting their contents at all.
SHAPE2_NESTED_KEY_RE = re.compile(r'^(\s*)-?\s*"?(\w+)"?\s*:\s*(.*)$')


def _extract_fenced_blocks(section_text):
    """Return [(lang, content), ...] for every fenced ```lang block in
    section_text, in document order."""
    fenced_whole = _fenced_spans(section_text)
    blocks = []
    for s, e in fenced_whole:
        raw = section_text[s:e]
        m = re.match(r"^```(\w*)\n(.*)\n```$", raw, re.DOTALL)
        if m:
            blocks.append((m.group(1).lower(), m.group(2)))
    return blocks


def _parse_top_level_entries(block_text):
    """Return [(name, full_line, rest, body_lines), ...] for each top-level
    key in a fenced yaml/json return block. Handles both bare YAML keys
    (column 0) and 2-space-indented JSON-quoted keys."""
    lines = block_text.split("\n")
    is_json = block_text.lstrip().startswith("{")
    key_re = TOP_LEVEL_JSON_KEY_RE if is_json else TOP_LEVEL_YAML_KEY_RE
    entries = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = key_re.match(line)
        if m:
            name = m.group(1)
            rest = m.group(2)
            body = []
            j = i + 1
            indent = len(line) - len(line.lstrip())
            while j < n:
                nxt = lines[j]
                if nxt.strip() == "":
                    body.append(nxt)
                    j += 1
                    continue
                nxt_indent = len(nxt) - len(nxt.lstrip())
                if nxt_indent > indent:
                    body.append(nxt)
                    j += 1
                    continue
                break
            entries.append((name, line, rest, body))
            i = j
        else:
            i += 1
    return entries


def _shape2_has_enum(name, rest, body, schema_text):
    if _is_enum_list(rest):
        return True
    for bl in body:
        if bl.strip().startswith("#") and _is_enum_list(bl):
            return True
    if schema_text:
        m = re.search(
            r'"' + re.escape(name) + r'"\s*:\s*\{[^{}]*"enum"\s*:',
            schema_text,
            re.DOTALL,
        )
        if m:
            return True
    return False


def _shape2_field_shape(rest, body):
    """Classify a top-level field's shape as one of:
    'block_scalar', 'array_of_object', 'array_of_plain', 'object', 'scalar'.
    """
    stripped = rest.strip()
    if stripped in ("|", ">") or stripped.startswith("|") or stripped.startswith(">"):
        return "block_scalar"
    if stripped.startswith("[{"):
        return "array_of_object"
    if stripped.startswith("["):
        return "array_of_plain"
    if body:
        first = body[0].strip()
        if first.startswith("-") and ":" in first:
            return "array_of_object"
        if first.startswith("-"):
            return "array_of_plain"
        if re.match(r'^"?\w+"?\s*:', first):
            return "object"
    return "scalar"



def _shape2_text_is_bounded(full_line, rest, body):
    """Shared leaf-boundedness check, used both for a top-level scalar/
    array-of-plain/block-scalar field's own text and for every nested leaf
    a container field recurses into (round-4 M3 fix).

    The enum-list check is deliberately scoped to `rest` alone (the
    key's own value text), never the full_line+body combined text: a
    block-scalar opener ('key: |' or 'key: >') followed by unrelated body
    prose on the next physical line can spuriously look like an 'X | Y'
    pipe-delimited list once joined into one combined string (e.g.
    'pr_description_body: |   <markdown body suitable for the PR; ...>'
    matches '\\S+\\s*\\|\\s*\\S+' purely by adjacency, with no real enum
    intent) - this was caught by the mutation harness's own baseline
    sanity check against engineer.md, not hypothesized in advance.
    A '|'-delimited value list in `rest` is itself a closed, bounded set -
    recognized here regardless of field name, not only via
    CLASSIFICATION_FIELD_NAME_RE (needed for nested non-classification-
    named enum-shaped fields like 'lint: pass | fail | not_run').

    Round-5: every check below is one of the explicitly named, closed
    forms defined above `_shape2_has_cap_with_digit` - there is no
    remaining shape-level auto-pass anywhere in this function. Round-6:
    the schema/doc-pointer form is deleted outright (Major-2 fix - see
    the comment above SHAPE_BOUNDED_VALUE_LITERALS); a leaf that matches
    none of the six SURVIVING recognized forms is unbounded."""
    if _is_enum_list(rest):
        return True
    combined = full_line + " " + " ".join(body)
    if _shape2_has_cap_with_digit(combined):
        return True
    if SHAPE2_ONE_LINE_RE.search(combined):
        return True
    if _is_bounded_value_literal(rest):
        return True
    if _is_nullable_type_placeholder(rest):
        return True
    return False


def _shape2_collect_leaf_entries(body_lines):
    """Return [(name, full_line, rest, sub_body), ...] for every 'key:
    value' line found at ANY indentation depth within body_lines whose
    value portion is non-empty on the same physical line - this walks
    object members AND array-of-object item members uniformly without
    building a full YAML tree (round-4 M3 fix: the checker previously
    returned True unconditionally for 'object'/'array_of_object' shapes,
    never inspecting their contents)."""
    entries = []
    n = len(body_lines)
    i = 0
    while i < n:
        line = body_lines[i]
        m = SHAPE2_NESTED_KEY_RE.match(line)
        if m and m.group(3).strip():
            indent = len(line) - len(line.lstrip())
            sub = []
            j = i + 1
            while j < n:
                nxt = body_lines[j]
                if not nxt.strip():
                    sub.append(nxt)
                    j += 1
                    continue
                nxt_indent = len(nxt) - len(nxt.lstrip())
                if nxt_indent > indent and not SHAPE2_NESTED_KEY_RE.match(nxt):
                    sub.append(nxt)
                    j += 1
                    continue
                break
            entries.append((m.group(2), line, m.group(3), sub))
            i = j
        else:
            i += 1
    return entries


def _shape2_is_bounded(name, full_line, rest, body, schema_text):
    shape = _shape2_field_shape(rest, body)
    if shape in ("array_of_object", "object"):
        # Recurse: every 'key: value' leaf line nested inside this
        # container - at any depth, including an array-of-object item
        # member or a member nested two levels deep - carries its own
        # enum/cap/one-line/bounded-literal/nullable-type obligation
        # (round-4 M3 fix; round-6 Major-2 deleted the pointer form this
        # comment used to name here).
        nested = _shape2_collect_leaf_entries(body)
        if not nested:
            # No leaf key:value lines found inside - nothing to recurse
            # into; treat conservatively as unbounded rather than
            # silently passing an unparseable or empty container.
            return False
        for n_name, n_line, n_rest, n_body in nested:
            if CLASSIFICATION_FIELD_NAME_RE.search(n_name):
                if not _shape2_has_enum(n_name, n_rest, n_body, schema_text):
                    return False
                continue
            if not _shape2_text_is_bounded(n_line, n_rest, n_body):
                return False
        return True
    # Round-5 structural fix: the 'scalar' shape previously auto-passed
    # unconditionally here ("a single physical schema line is itself a
    # one-line bound") - that auto-pass is deleted. A scalar field's
    # text is now run through the SAME closed-whitelist check
    # (_shape2_text_is_bounded) as every other shape; a scalar value
    # that is not itself an enum/cap/one-line/bounded-literal/
    # nullable-type form is unbounded, exactly like a nested leaf.
    return _shape2_text_is_bounded(full_line, rest, body)


# Per-shape form usage (round-6 Major-3): check_shape2 is the ONLY
# checker that consults the FULL closed whitelist (all six surviving
# forms, via _shape2_is_bounded/_shape2_text_is_bounded) - it is the
# canonical/authoritative list. check_shape3 and check_shape4 each
# consult a DIFFERENT, narrower subset (see the comment blocks above
# their own leaf-boundedness logic below) - this is a deliberate,
# now-documented divergence, not an accidental gap. The identical
# per-shape lists live in content/references/subagent-return-
# contract.md's "Compliance shapes" section; the two must be kept
# literally diffable against each other.
def check_shape2(text, filename="<fixture>"):
    try:
        section = extract_output_format_section(text)
        if section is None:
            section = extract_return_substep_section(text)
        if section is None:
            section = extract_report_phase_section(
                text, "Phase 6: Produce the Drift Report"
            )
    except UnbalancedFenceError as e:
        return [f"{filename}: {e}"]
    if section is None:
        return [
            f"{filename}: no recognized Shape-2 return anchor found "
            f"(tried: {', '.join(HEADING_SYNONYMS)}; '### N. Return'; "
            "'## Phase 6: Produce the Drift Report')"
        ]

    try:
        blocks = _extract_fenced_blocks(section)
    except UnbalancedFenceError as e:
        return [f"{filename}: {e}"]
    yaml_json_blocks = [
        (lang, content) for lang, content in blocks if lang in ("yaml", "json")
    ]
    if not yaml_json_blocks:
        return [
            f"{filename}: no fenced ```yaml or ```json return block found in "
            "the Shape-2 return section"
        ]

    primary_lang, primary_content = yaml_json_blocks[0]
    schema_text = None
    for lang, content in yaml_json_blocks[1:]:
        if lang == "json":
            schema_text = content
            break

    entries = _parse_top_level_entries(primary_content)
    if not entries:
        return [f"{filename}: no top-level fields found in the Shape-2 return block"]

    violations = []
    for name, full_line, rest, body in entries:
        is_classification = bool(CLASSIFICATION_FIELD_NAME_RE.search(name))
        if is_classification:
            if not _shape2_has_enum(name, rest, body, schema_text):
                violations.append(
                    f"{filename}: classification field '{name}' declares no "
                    "closed enum (expected an inline 'X | Y | Z' value list "
                    "or an adjacent JSON-Schema 'enum:')"
                )
            continue
        if not _shape2_is_bounded(name, full_line, rest, body, schema_text):
            violations.append(
                f"{filename}: field '{name}' is capable of open-ended or "
                "repeated content but declares no cap or one-line marker"
            )
    return violations


# --- Shape 3: fixed literal-line template ---

SKEPTIC_REQUIRED_LINE_PREFIXES = (
    "Reviewed:",
    "Findings:",
    "Active search:",
    "No unresolved Critical or Major findings. Sign-off granted.",
    "Manifest check:",
    "Test-CI-wiring check:",
)
SHAPE3_LINE_RE = re.compile(r"^(\S[^:]*):\s*(.*)$")
# Round-6 Minor fix: a bare closed-enum-shaped status token standing
# ALONE on its own line, with no colon at all (e.g.
# goal-condition-evaluator.md's escape-hatch 'BLOCKED' line), is a
# legitimate Shape-3 line - the value IS the token itself, a fixed
# literal from a small, implied vocabulary, no different in kind from
# 'GOAL_MET: true|false' collapsed into a single word. Flagging it as
# "not a 'Label: value' line" was gate over-strictness: the Shape-3
# doc definition never required every line to carry a colon, only that
# every VALUE be bounded. Deliberately narrow (fullmatch, all-caps
# identifier only) so this cannot be gamed by an arbitrary lowercase or
# mixed-case narrative line slipping through uncaptured.
SHAPE3_BARE_STATUS_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Per-shape form usage (round-6 Major-3): _shape3_value_bounded does
# NOT consult the Shape-2 whitelist at all - it is a SEPARATE, smaller,
# named form set specific to Shape-3's single-physical-line values:
#   - closed enum: a bare 'true'/'false' literal, the literal string
#     'true|false', or _is_enum_list() (the same enum-list check Shape
#     2 uses, form 1 above).
#   - bare count: a bare '<N>' or 'N' integer placeholder - a
#     Shape-3-only form with no Shape-2 equivalent (Shape 2 has no
#     "bare count" form; it requires a keyword-led numeric cap
#     instead).
#   - one-line marker (form 4 above) - reused as-is.
#   - fully-realized literal (Shape-3-only, NEWLY NAMED round-6): a
#     value containing no '<...>' placeholder at all has no open
#     narrative slot to overflow, so it is bounded by construction
#     (e.g. a hardcoded escape-hatch message). This was previously an
#     unnamed, undocumented eighth check; it is now a named form,
#     specific to this shape - it does not generalize to Shape 2, whose
#     '<...>'-free scalar values (e.g. a bare integer with no bracket)
#     are still routed through the full whitelist above, not this
#     shortcut.
# Shape 3 does NOT use: true-adjacent numeric cap (form 2), fixed-length
# spec (form 3), bounded-by-nature value literal (form 5) - none of
# these apply to a single physical 'Label: value' line the way they do
# to a multi-line YAML/JSON schema leaf or a report placeholder.
def _shape3_value_bounded(value):
    v = value.strip()
    if not v:
        return False
    if v.lower() in ("true", "false"):
        return True
    if re.fullmatch(r"true\|false", v, re.IGNORECASE):
        return True
    if _is_enum_list(v):
        return True
    if re.fullmatch(r"<?\s*\d+\s*>?", v):
        return True
    if SHAPE2_ONE_LINE_RE.search(v):
        return True
    # A value with no '<...>' placeholder at all is a fully realized
    # literal (fixed boilerplate text, e.g. a hardcoded escape-hatch
    # message) - there is no open narrative slot to overflow, so it is
    # bounded by construction. A value containing '<' still has an open
    # placeholder slot and must satisfy one of the forms above.
    if "<" not in v:
        return True
    return False


def check_shape3(text, filename="<fixture>"):
    """Round-5 Minor fix: every fenced block in the section is now
    checked, not just blocks[0] - goal-condition-evaluator.md has three
    fenced return templates and the second ('Evidence: "evaluator-error:
    <reason>"') carries an unbounded placeholder that was never
    inspected under the pre-fix blocks[0]-only check.

    Round-6 Minor fix: a bare closed-enum-shaped status token line (no
    colon) is now recognized as compliant via
    SHAPE3_BARE_STATUS_TOKEN_RE - see the comment above that pattern."""
    try:
        section = extract_output_format_section(text)
    except UnbalancedFenceError as e:
        return [f"{filename}: {e}"]
    if section is None:
        return [
            f"{filename}: no recognized return-contract heading found "
            f"(tried: {', '.join(HEADING_SYNONYMS)})"
        ]
    try:
        blocks = _extract_fenced_blocks(section)
    except UnbalancedFenceError as e:
        return [f"{filename}: {e}"]
    if not blocks:
        return [f"{filename}: no fenced literal-line template found"]

    violations = []
    for block_idx, (_lang, content) in enumerate(blocks, start=1):
        lines = [ln for ln in content.split("\n") if ln.strip()]
        if len(lines) > 8:
            violations.append(
                f"{filename}: Shape-3 template (block {block_idx}) has "
                f"{len(lines)} lines, expected <= 8 for a fixed "
                "literal-line template"
            )
            continue
        for ln in lines:
            m = SHAPE3_LINE_RE.match(ln)
            if not m:
                if SHAPE3_BARE_STATUS_TOKEN_RE.match(ln.strip()):
                    continue
                violations.append(
                    f"{filename}: Shape-3 line '{ln}' (block {block_idx}) "
                    "is not a 'Label: value' line"
                )
                continue
            label, value = m.group(1), m.group(2)
            if not _shape3_value_bounded(value):
                violations.append(
                    f"{filename}: Shape-3 line '{label}:' (block "
                    f"{block_idx}) value '{value}' is neither a closed "
                    "enum, a bare count, nor bounded to one line by its "
                    "own placeholder text"
                )
    return violations


def check_shape3_skeptic(text, filename="skeptic.md"):
    """skeptic.md's narrow special case: the six conductor-validated lines
    from skeptic-protocol.md Section 11 must be present verbatim (and never
    retagged) WITHIN THE '## Sign-off format' SECTION ITSELF, and a
    cap-keyword sentence referencing 'finding' with a numeric bound must
    appear in the Calibration section (never inside the Sign-off format
    template itself - a match inside the template would violate the
    'never touch the validated lines' constraint, not satisfy it).

    Round-4 M2 fix: the six-prefix presence check used to search the
    WHOLE FILE, not the Sign-off format section - a prose mention of a
    validated line's label elsewhere in the file (e.g. the
    Reading-your-spawn-prompt guard that literally quotes "Findings:")
    masked a retagged or altered template line, since the retagged text no
    longer contains the exact prefix but the unrelated prose mention still
    does. Scoping the search to the Sign-off format section closes this.
    The template-smuggling guard below was previously a dead `pass` loop
    that computed `blocks` and never actually flagged anything; it now
    raises a real violation when the cap sentence is found inside the
    Sign-off format template instead of the surrounding Calibration prose.
    """
    violations = []

    signoff_m = re.search(r"^##\s+Sign-off format\s*$", text, re.MULTILINE)
    if not signoff_m:
        violations.append(f"{filename}: no '## Sign-off format' section found")
        signoff_section_text = ""
    else:
        signoff_rest = text[signoff_m.end():]
        signoff_end = SECTION_END_RE.search(signoff_rest)
        signoff_section_text = (
            signoff_rest[:signoff_end.start()] if signoff_end else signoff_rest
        )

    for prefix in SKEPTIC_REQUIRED_LINE_PREFIXES:
        if prefix not in signoff_section_text:
            violations.append(
                f"{filename}: required Sign-off format line prefix "
                f"'{prefix}' not found verbatim in the '## Sign-off format' "
                "section"
            )

    calib_m = re.search(r"^##\s+Calibration\s*$", text, re.MULTILINE)
    if not calib_m:
        violations.append(f"{filename}: no '## Calibration' section found")
        return violations
    rest = text[calib_m.end():]
    end_m = SECTION_END_RE.search(rest)
    calibration_text = rest[:end_m.start()] if end_m else rest

    cap_sentence_re = re.compile(
        r"finding[^.\n]*\b(cap(?:ped)?|max(?:imum)?)\b[^.\n]*\d+", re.IGNORECASE
    )
    if not cap_sentence_re.search(calibration_text):
        violations.append(
            f"{filename}: Calibration section declares no explicit numeric "
            "cap on finding-description length"
        )

    # Guard against the cap sentence being smuggled INTO the validated
    # template instead of the surrounding Calibration prose - that would
    # violate the "never alter/retag/restructure" constraint even though it
    # might satisfy a naive text search.
    if signoff_section_text:
        try:
            blocks = _extract_fenced_blocks(signoff_section_text)
        except UnbalancedFenceError:
            blocks = []
        for _lang, content in blocks:
            if cap_sentence_re.search(content):
                violations.append(
                    f"{filename}: the finding-description cap sentence must "
                    "appear in the Calibration section prose, not inside "
                    "the Sign-off format fenced template itself"
                )
    return violations


# --- Shape 4: fixed markdown-sectioned flat report ---

SHAPE4_STATUS_LINE_RE = re.compile(r"^##\s+Status:\s*(.+)$", re.MULTILINE)
SHAPE4_SUBSECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)

# Per-shape form usage (round-6 Major-3): check_shape4's placeholder loop
# below consults exactly FOUR of the six Shape-2 forms - closed enum
# (form 1, via _is_enum_list), true-adjacent numeric cap (form 2) and
# fixed-length spec (form 3, both via _shape2_has_cap_with_digit), and
# bounded-by-nature value literal (form 5, via
# _is_bounded_value_literal). It does NOT consult one-line marker
# (form 4) or nullable-type placeholder (form 6) - a report-template
# placeholder bracket (e.g. '<exact command run>') is never written in
# either of those two shapes in the real corpus, so there was nothing to
# match; this is a documented absence, not a silent gap.


def check_shape4(text, filename="<fixture>"):
    try:
        section = extract_output_format_section(text)
    except UnbalancedFenceError as e:
        return [f"{filename}: {e}"]
    if section is None:
        return [
            f"{filename}: no recognized return-contract heading found "
            f"(tried: {', '.join(HEADING_SYNONYMS)})"
        ]
    try:
        blocks = _extract_fenced_blocks(section)
    except UnbalancedFenceError as e:
        return [f"{filename}: {e}"]
    if not blocks:
        return [f"{filename}: no fenced flat-report template found"]
    _lang, content = blocks[0]
    if HEADER_RE.search(content):
        return [
            f"{filename}: Shape-4 template contains '###' fields - this is "
            "a Shape-1 file, not Shape-4"
        ]
    status_m = SHAPE4_STATUS_LINE_RE.search(content)
    violations = []
    if not status_m:
        violations.append(
            f"{filename}: no '## Status: ...' line found in the report template"
        )
    elif not _is_enum_list(status_m.group(1)):
        violations.append(
            f"{filename}: '## Status:' line declares no closed enum "
            f"('{status_m.group(1)}')"
        )

    subsection_matches = list(SHAPE4_SUBSECTION_RE.finditer(content))
    for i, sm in enumerate(subsection_matches):
        title = sm.group(1)
        if title.startswith("Status:"):
            continue
        body_start = sm.end()
        body_end = (
            subsection_matches[i + 1].start()
            if i + 1 < len(subsection_matches)
            else len(content)
        )
        body = content[body_start:body_end]
        for placeholder_m in re.finditer(r"<([^<>]+)>", body):
            placeholder = placeholder_m.group(1)
            # Round-5 fix: the requirement is now the closed whitelist of
            # recognized bound forms (bounded-by-nature value literal,
            # closed enum, or a true-adjacent numeric/fixed-length cap) -
            # replacing round-4's unconditional numeric-cap-only
            # requirement, which forced a cap onto every placeholder
            # regardless of whether its value type is already bounded by
            # nature (a SHA, a URL, a timestamp, a tag, an exact command,
            # ...). This is the scope the doc's Shape-4 obligation always
            # stated ("every OTHER section with open-ended free text"),
            # not "every placeholder unconditionally".
            if _is_bounded_value_literal(placeholder):
                continue
            if _is_enum_list(placeholder):
                continue
            if _shape2_has_cap_with_digit(placeholder):
                continue
            violations.append(
                f"{filename}: '## {title}' placeholder '<{placeholder}>' "
                "is open-ended free text and declares no closed enum, "
                "bounded-by-nature value type, or numeric cap"
            )
    return violations


# --- Dispatch ---


def check_contract(text, filename="<fixture>", shape=None):
    """Return a list of human-readable violation strings; [] means
    compliant. Dispatches to the checker for SHAPE_ASSIGNMENTS[filename],
    or the explicit `shape` override (1/2/3/4) for fixture-based tests that
    have no real filename to look up. Files with no assignment and no
    override default to Shape 1 (the original, and still most common,
    shape)."""
    resolved = shape if shape is not None else SHAPE_ASSIGNMENTS.get(filename, 1)
    if resolved == 1:
        return check_shape1(text, filename)
    if resolved == 2:
        return check_shape2(text, filename)
    if resolved == 3:
        if filename == "skeptic.md":
            return check_shape3_skeptic(text, filename)
        return check_shape3(text, filename)
    if resolved == 4:
        return check_shape4(text, filename)
    raise ValueError(f"unrecognized shape: {resolved!r}")


def _read_fixture(name):
    return (FIXTURES_DIR / name).read_text()


def _real_agent_files():
    return sorted(AGENTS_DIR.glob("*.md"))


# --- Fixture-based checker correctness tests (independent of the allowlist) ---


def test_compliant_fixture_is_contract_compliant():
    text = _read_fixture("compliant_agent.md")
    assert check_contract(text, "compliant_agent.md") == []


def test_fixture_missing_tag_is_flagged():
    text = _read_fixture("missing_tag_agent.md")
    violations = check_contract(text, "missing_tag_agent.md")
    assert violations, "expected a violation for an untagged field"
    assert any("no [MECHANICAL] or [ADVISORY] tag" in v for v in violations)


def test_fixture_missing_cap_is_flagged():
    text = _read_fixture("missing_cap_agent.md")
    violations = check_contract(text, "missing_cap_agent.md")
    assert violations, "expected a violation for a MECHANICAL field with no cap"
    assert any("declares no numeric cap" in v for v in violations)


def test_fenced_template_fixture_is_contract_compliant():
    """
    Reproduces the REAL content/agents/*.md corpus shape (verified against
    debugger.md et al.): the field template lives inside a fenced code
    block that itself contains a '##'-level example line
    ('## Diagnosis: [...]'). Before the fence-aware fix, SECTION_END_RE
    matched that in-fence '##' line and truncated the section to ~30-140
    chars before it ever reached a '###' field - this fixture proves the
    extractor now correctly walks past it to the real end of section
    ('## Rules').
    """
    text = _read_fixture("compliant_fenced_template_agent.md")
    violations = check_contract(text, "compliant_fenced_template_agent.md")
    assert violations == [], violations


def test_cap_requirement_ignores_unrelated_body_prose():
    """
    A MECHANICAL field with no cap declared in its own header must still be
    flagged even when its body contains unrelated cap-shaped prose (e.g.
    'at max 3 items of supporting evidence') that has nothing to do with
    this field's own cap. Proves CAP_RE is anchored to the tag bracket
    only, not searched across the whole field body.
    """
    text = _read_fixture("missing_cap_unrelated_body_prose_agent.md")
    violations = check_contract(text, "missing_cap_unrelated_body_prose_agent.md")
    assert violations, (
        "expected a cap violation even though unrelated body prose contains "
        "a cap-shaped phrase"
    )
    assert any("declares no numeric cap" in v for v in violations)


def test_cap_false_positive_in_title_and_parenthetical_is_flagged():
    """
    Round-2 MINOR fix regression guard: a cap-shaped phrase in a field's
    own TITLE ("Coverage of max 10 items") or in a parenthetical pointing
    elsewhere ("(see cap: 300 chars in Rules)") must not satisfy the cap
    requirement when the [MECHANICAL] tag bracket itself declares no cap.
    Verified against the pre-fix checker: it returned [] (falsely
    compliant) for this exact fixture.
    """
    text = _read_fixture("cap_false_positive_agent.md")
    violations = check_contract(text, "cap_false_positive_agent.md")
    assert len(violations) == 2, violations
    assert all("declares no numeric cap" in v for v in violations)


def test_fence_protected_heading_before_real_section_is_flagged():
    """
    Round-2 Major fix regression guard, vector (a): SECTION_START_RE.search
    was not fence-aware, so a fenced illustrative example containing a
    recognized heading earlier in the file won the match and the real
    section (with its genuinely untagged field) was never inspected.
    Verified against the pre-fix checker: it returned [] for this exact
    fixture.
    """
    text = _read_fixture("fence_protected_heading_before_real_section_agent.md")
    violations = check_contract(
        text, "fence_protected_heading_before_real_section_agent.md"
    )
    assert violations, (
        "expected a violation for the real section's untagged 'Answer' "
        "field - the fenced example's heading must not win the start match"
    )
    assert any("Answer" in v for v in violations)


def test_unbalanced_fence_is_flagged_loudly_not_silently_truncated():
    """
    Round-2 Major fix regression guard, vector (b): _fenced_spans assumed
    fences are balanced and paired markers positionally. An odd
    fence-marker count inside the section mis-paired everything after it,
    making an in-fence '##'-level example line look un-fenced and
    truncating the section before it ever reached the real untagged field.
    Verified against the pre-fix checker: it returned [] for this exact
    fixture. The fix must detect the imbalance and fail loudly (a non-empty
    violation naming the fence problem), never silently guess a pairing.
    """
    text = _read_fixture("unbalanced_fence_truncates_section_agent.md")
    violations = check_contract(text, "unbalanced_fence_truncates_section_agent.md")
    assert violations, "expected a loud violation for the unbalanced fence"
    assert any("fence" in v.lower() for v in violations)


def test_unrecognized_heading_fails_loudly_not_silently():
    """
    Round-2 regression re-check: a new agent file whose return-contract
    section uses a heading with no recognized synonym, and which is not in
    SHAPE_ASSIGNMENTS or EXEMPT_FILE_ARTIFACT, must fail loudly (a
    non-empty violation) rather than being silently skipped.
    """
    text = _read_fixture("unrecognized_heading_agent.md")
    violations = check_contract(text, "unrecognized_heading_agent.md")
    assert violations, "expected a loud violation for an unrecognized heading"


# --- Shape 2 fixture tests ---


def test_shape2_compliant_fixture_is_contract_compliant():
    text = _read_fixture("shape2_compliant_agent.md")
    violations = check_contract(text, "shape2_compliant_agent.md", shape=2)
    assert violations == [], violations


def test_shape2_missing_enum_and_cap_is_flagged():
    text = _read_fixture("shape2_missing_enum_and_cap_agent.md")
    violations = check_contract(text, "shape2_missing_enum_and_cap_agent.md", shape=2)
    assert violations, "expected violations for missing enum and missing cap"
    assert any("closed enum" in v for v in violations)
    assert any("declares no cap" in v for v in violations)


def test_shape2_engineer_is_now_compliant():
    """Final unit of the DS return-contract migration (2026-08-11) closes
    engineer.md's last four violations: `task_id` and `branch_name` now use
    the nullable-type placeholder form (`<id, or null>` / `<name, or null>`
    - both TYPE words drawn from `_SHAPE_TYPE_WORDS`, not the deleted
    'string' entry); `pr_description_body` carries an explicit
    'capped at 2000 chars' true-adjacent numeric cap (the architect plan's
    assigned bound - decision-relevant PR body content needs headroom but
    not a changelog); `learnings_candidate` carries an explicit
    'capped at 5 items' true-adjacent numeric cap (matching the canonical
    5-entry cap in learnings-capture-instruction.md) rather than relying on
    the now-deleted schema/doc-pointer form.

    This also continues to VERIFY that raw_output's 'truncated to 4000
    chars' bound is correctly recognized despite being nested inside the
    quality_gate_results object, and that files_modified.path
    (`<repo-relative path>`) is correctly recognized as a bounded-by-nature
    value literal - neither regressed by this round's edits."""
    path = AGENTS_DIR / "engineer.md"
    violations = check_contract(path.read_text(), "engineer.md")
    assert violations == [], violations


# --- Shape 3 fixture tests ---


def test_shape3_compliant_fixture_is_contract_compliant():
    text = _read_fixture("shape3_compliant_agent.md")
    violations = check_contract(text, "shape3_compliant_agent.md", shape=3)
    assert violations == [], violations


def test_shape3_missing_bound_is_flagged():
    text = _read_fixture("shape3_missing_bound_agent.md")
    violations = check_contract(text, "shape3_missing_bound_agent.md", shape=3)
    assert violations, "expected a violation for an unbounded Evidence value"


def test_shape3_goal_condition_evaluator_is_now_compliant():
    """Round-5 Minor fix: check_shape3 previously inspected only
    blocks[0] - goal-condition-evaluator.md has THREE fenced return
    templates (the two-line success/failure form, the evaluator-error
    escape hatch, and the no-confirmed-sign-off escape hatch), and the
    second's Evidence value ('"evaluator-error: <reason>"') carried an
    unbounded placeholder that was never inspected before that fix.

    Round-6 Minor fix: the third block's bare 'BLOCKED' line (no colon)
    is NOT flagged - it is a legitimate bare closed-enum-shaped
    status token (SHAPE3_BARE_STATUS_TOKEN_RE).

    Final unit of the DS return-contract migration (2026-08-11) closes the
    remaining genuine gap: the second block's Evidence value is now
    '"evaluator-error: <one-line reason>"' - the one-line marker form
    (SHAPE2_ONE_LINE_RE, reused as-is by Shape 3) - so
    goal-condition-evaluator.md is now fully Shape-3 compliant."""
    path = AGENTS_DIR / "goal-condition-evaluator.md"
    violations = check_contract(path.read_text(), "goal-condition-evaluator.md")
    assert violations == [], violations


def test_shape3_skeptic_is_now_compliant():
    """Unit 1 (DS return-contract migration) added the additive
    finding-description cap sentence to skeptic.md's Calibration section
    without touching any of its six conductor-validated Sign-off format
    lines - skeptic.md is now fully Shape-3 compliant."""
    path = AGENTS_DIR / "skeptic.md"
    violations = check_contract(path.read_text(), "skeptic.md")
    assert violations == [], violations


# --- Shape 4 fixture tests ---


def test_shape4_compliant_fixture_is_contract_compliant():
    text = _read_fixture("shape4_compliant_agent.md")
    violations = check_contract(text, "shape4_compliant_agent.md", shape=4)
    assert violations == [], violations


def test_shape4_missing_cap_is_flagged():
    text = _read_fixture("shape4_missing_cap_agent.md")
    violations = check_contract(text, "shape4_missing_cap_agent.md", shape=4)
    assert violations, "expected a violation for the uncapped 'Failures and blockers' placeholder"


def test_shape4_release_orchestrator_is_now_compliant():
    """Unit 4 (return-contract migration) added an explicit cap to each of
    release-orchestrator.md's three genuinely open-ended Shape-4
    placeholders (the '<message>' half of its two commit-listing lines,
    the QA report summary placeholder, and the Failures-and-blockers
    placeholder) without touching any bounded-by-nature placeholder
    (sha/url/timestamp/tag/environment name/remote name/exact command/
    exact rollback command) or the '## Status:' closed-enum line -
    release-orchestrator.md is now fully Shape-4 compliant."""
    path = AGENTS_DIR / "release-orchestrator.md"
    violations = check_contract(path.read_text(), "release-orchestrator.md")
    assert violations == [], violations


def test_shape2_dependency_auditor_is_now_compliant():
    """Unit 4 (return-contract migration) retired dependency-auditor.md's
    free-prose '## Report structure' (Summary/Findings/Upgrade plan/Open
    questions/Scan gaps, none tagged) for the pointer-JSON Shape 2 return:
    the full report is written to .agentic/audit-reports/ via a Bash
    heredoc (this agent has no Write/Edit grant), and the small returned
    object declares an enum or bound on every field (scan_completeness/
    maintenance_signal/verdict as closed enums, critical_count/major_count/
    minor_count/report_path as bounded-by-nature '<count>'/'<path>'
    literals, notes as a capped, omit-when-empty field)."""
    path = AGENTS_DIR / "dependency-auditor.md"
    violations = check_contract(path.read_text(), "dependency-auditor.md")
    assert violations == [], violations


def test_critical_findings_cap_never_suppresses_a_critical():
    """Round 3 (Skeptic Major 1) - a Critical finding must never be
    suppressed by a bounded findings-list cap. security-auditor.md's
    '### Critical findings' section and dependency-auditor.md's
    critical_findings pointer field both carry a hard item cap (10 and
    5 respectively); each must also carry an unconditional "report all
    of them anyway" clause, with grouping offered only as a compression
    means, that takes precedence over the cap. Without this clause, an
    auditor with more Criticals than the cap has no compliant path
    except dropping the overflow."""
    for filename in ("security-auditor.md", "dependency-auditor.md"):
        text = (AGENTS_DIR / filename).read_text()
        assert "must never be suppressed" in text, (
            f"{filename} is missing the anti-suppression clause for its "
            "capped Critical findings list"
        )
        assert "report all of them anyway" in text, (
            f"{filename}'s anti-suppression clause must instruct reporting "
            "all Criticals, not just acknowledge the cap"
        )
        assert "takes precedence over it" in text, (
            f"{filename}'s anti-suppression clause must explicitly take "
            "precedence over the cap, not merely coexist with it"
        )


def test_shape2_perf_analyst_is_now_compliant():
    """Unit 4 (return-contract migration) retired perf-analyst.md's
    free-prose '## Report structure' (Summary/Methodology/Measurements/
    Perf budget verdict/Hotspot/Root cause/Evidence/Fix brief for
    engineer/Confidence, none tagged) for the pointer-JSON Shape 2 return:
    the full report is written to .agentic/audit-reports/ via a Bash
    heredoc (this agent has no Write/Edit grant), and the small returned
    object declares an enum or bound on every field (verdict/confidence as
    closed enums, hotspot/root_cause/fix_brief as explicitly capped
    strings matching debugger's Root cause/Fix brief precedent, report_path
    as a bounded-by-nature '<path>' literal, notes as a capped,
    omit-when-empty field)."""
    path = AGENTS_DIR / "perf-analyst.md"
    violations = check_contract(path.read_text(), "perf-analyst.md")
    assert violations == [], violations


def test_shape2_adr_drift_detector_is_now_compliant():
    """Unit 4 (return-contract migration) retired adr-drift-detector.md's
    free-prose 'Phase 6: Produce the Drift Report' narrative (which
    previously had no fenced yaml/json return block at all - the
    NO_STRUCTURED_RETURN_SECTION defect the Unit-0 amendment corrected to
    NOT_YET_MIGRATED) for the pointer-JSON Shape 2 return: the full report
    is written to .agentic/audit-reports/ via a Bash heredoc (this agent
    has no Write/Edit grant), and the small returned object declares an
    enum or bound on every field (verdict as a closed enum,
    adrs_scanned/violations_count/partial_count/unverifiable_count/
    report_path as bounded-by-nature '<count>'/'<path>' literals, notes
    as a capped, omit-when-empty field)."""
    path = AGENTS_DIR / "adr-drift-detector.md"
    violations = check_contract(path.read_text(), "adr-drift-detector.md")
    assert violations == [], violations


# --- "Don't omit" instruction count pin (round-2 rework of Unit 4) ---

DONT_OMIT_PATTERN = re.compile(
    r"never omit|do not omit|don't omit|do not skip sections?", re.IGNORECASE
)


def test_dont_omit_instruction_count_matches_prose():
    """subagent-return-contract.md's 'Why this file exists' section states
    an exact count and file set of content/agents/*.md files still
    carrying some form of a "don't omit" instruction. That count has been
    wrong or arguably-wrong across three consecutive PRs (undercounting
    debugger.md's distinct field-scoped 'Never omit the location' line and
    missing adr-generator.md's 'Do not skip sections' entirely). This
    grep-based pin catches drift mechanically instead of relying on manual
    re-verification: update both this test's `expected` set and the prose
    paragraph together whenever either changes."""
    hits = {
        path.name
        for path in AGENTS_DIR.glob("*.md")
        if DONT_OMIT_PATTERN.search(path.read_text())
    }
    expected = {"architect.md", "skeptic.md", "debugger.md", "adr-generator.md"}
    assert hits == expected, (
        f"missing: {sorted(expected - hits)}; unexpected: {sorted(hits - expected)}"
    )


CONTRACT_REF_PATH = REPO_ROOT / "content" / "references" / "subagent-return-contract.md"

DONT_OMIT_PROSE_COUNT_PATTERN = re.compile(
    r"(\d+)\s+carry some\s*\nform of a \"don't omit\" instruction",
)


def test_dont_omit_instruction_count_matches_prose_number():
    """Round 3 (Skeptic Minor 2) - the prior count pin
    (test_dont_omit_instruction_count_matches_prose, above) only pins the
    live tree against a hardcoded `expected` set; it does not verify that
    `expected`'s cardinality matches the number subagent-return-contract.md
    itself states in prose ("of the 18 files ..., 4 carry some form of a
    ...instruction"). Editing that paragraph's "4" alone - without touching
    this test file - left the prior test green. This test parses the
    numeral out of the prose file and asserts it against the same
    mechanically-measured hit set, so a prose-only edit reddens here."""
    prose_text = CONTRACT_REF_PATH.read_text()
    match = DONT_OMIT_PROSE_COUNT_PATTERN.search(prose_text)
    assert match, (
        "could not find the '<N> carry some form of a \"don't omit\" "
        f"instruction' sentence in {CONTRACT_REF_PATH}"
    )
    prose_count = int(match.group(1))

    hits = {
        path.name
        for path in AGENTS_DIR.glob("*.md")
        if DONT_OMIT_PATTERN.search(path.read_text())
    }
    assert prose_count == len(hits), (
        f"subagent-return-contract.md claims {prose_count} files carry a "
        f"'don't omit' instruction, but the live tree has {len(hits)}: "
        f"{sorted(hits)}"
    )


# --- Real content/agents/*.md enforcement (round-5 snapshot model) ---


def test_shape_assignments_and_exemption_cover_all_real_files():
    """Every discovered content/agents/*.md file is either in
    SHAPE_ASSIGNMENTS (has a recognized shape, checked below against the
    snapshot) or in EXEMPT_FILE_ARTIFACT. A file in neither (e.g. a new
    agent file added without a shape assignment, or with an unrecognized
    heading) fails here rather than silently passing unnoticed. This is
    the 18-file tally check."""
    discovered = {p.name for p in _real_agent_files()}
    classified = set(SHAPE_ASSIGNMENTS) | EXEMPT_FILE_ARTIFACT
    assert discovered == classified, (
        f"unclassified files: {sorted(discovered - classified)}; "
        f"stale allowlist entries: {sorted(classified - discovered)}"
    )


def test_expected_violations_snapshot_matches_reality():
    """The core round-5 regression guard: for every SHAPE_ASSIGNMENTS
    file, the LIVE checker output must equal the committed snapshot
    EXACTLY - not 'both empty' or 'both non-empty', the same set of
    violation strings. Any drift is reported by name and by exact
    string-level diff:
      - a violation DISAPPEARING (the checker got more permissive, or
        the file was genuinely migrated - the snapshot must be updated
        deliberately via generate_agent_return_contract_snapshot.py,
        reviewed, in the SAME PR as whatever caused the change);
      - a violation APPEARING (the checker got more strict, or a
        regression was introduced into the agent file - same review
        obligation).
    This is what a boolean NOT_YET_MIGRATED set could never do: four
    consecutive prior rounds shipped a permissive branch that a boolean
    "is this file still flagged at all" test cannot see, because the
    file stayed flagged (just for fewer, or different, reasons)."""
    mismatches = []
    for name in sorted(SHAPE_ASSIGNMENTS):
        path = AGENTS_DIR / name
        live = check_contract(path.read_text(), name)
        expected = EXPECTED_VIOLATIONS.get(name)
        if expected is None:
            mismatches.append(f"{name}: no snapshot entry at all")
            continue
        if live != expected:
            missing = [v for v in expected if v not in live]
            extra = [v for v in live if v not in expected]
            detail = []
            if missing:
                detail.append(f"disappeared (now unflagged): {missing}")
            if extra:
                detail.append(f"appeared (newly flagged): {extra}")
            mismatches.append(f"{name}: " + "; ".join(detail))
    assert mismatches == [], (
        "expected_violations_snapshot.json drifted from the live checker "
        "output - review each entry below, and if the change is "
        "intentional, regenerate via "
        "bin/tests/generate_agent_return_contract_snapshot.py --write "
        "after reviewing its diff:\n" + "\n".join(mismatches)
    )


def test_snapshot_has_no_stale_or_missing_entries():
    """expected_violations_snapshot.json's key set must equal
    SHAPE_ASSIGNMENTS exactly - a stale entry for a renamed/deleted file,
    or a missing entry for a newly shape-assigned file, is caught here
    rather than silently ignored by the per-file loop above."""
    snapshot_keys = set(EXPECTED_VIOLATIONS)
    assigned = set(SHAPE_ASSIGNMENTS)
    assert snapshot_keys == assigned, (
        f"snapshot has entries with no shape assignment: "
        f"{sorted(snapshot_keys - assigned)}; shape-assigned files with "
        f"no snapshot entry: {sorted(assigned - snapshot_keys)}"
    )


def test_shape_assignments_and_exempt_are_disjoint():
    """A file must not be classified as both 'has a recognized shape' and
    'exempt from all shapes' - the two sets are mutually exclusive by
    construction."""
    overlap = set(SHAPE_ASSIGNMENTS) & EXEMPT_FILE_ARTIFACT
    assert overlap == set(), f"files present in both sets: {sorted(overlap)}"


def test_exempt_file_artifact_set_is_adr_generator_only():
    """adr-generator.md is the sole remaining exemption (its deliverable is
    the ADR document it writes, not a conductor-parsed return) - verified
    independently: grep for an Output/Return/Report heading in the file
    finds nothing."""
    assert EXEMPT_FILE_ARTIFACT == {"adr-generator.md"}
    path = AGENTS_DIR / "adr-generator.md"
    text = path.read_text()
    assert not re.search(r"Output|Return|Report", text), (
        "adr-generator.md now contains an Output/Return/Report heading - "
        "its file-artifact exemption needs re-verification"
    )


def test_fully_compliant_files_are_exactly_the_snapshot_empty_set():
    """Cross-check against the snapshot from the other direction: the set
    of files with an empty violations list in the snapshot is the
    project's actual 'compliant now' set. As of round 5 this was the
    EMPTY set - goal-condition-evaluator.md, the only remaining
    candidate, was reclassified to genuinely non-compliant by the
    check_shape3 all-blocks fix. Unit 1 of the DS return-contract
    migration (2026-08-11) grew this set by six: architect.md, debugger.md,
    investigator.md, orchestration-planner.md, security-auditor.md,
    skeptic.md - each migrated to its shape's tagging/enum/cap obligation
    with the boilerplate "never omit any section" rule deleted from its own
    Rules section (where present) and folded ADVISORY content moved into a
    single `Notes` block. Unit 4 (same migration) grew it by four more:
    dependency-auditor.md, perf-analyst.md, and adr-drift-detector.md each
    retired a free-prose report shape for the pointer-JSON Shape 2 return
    (report written to .agentic/audit-reports/ via Bash heredoc - none of
    the three has a Write/Edit grant); release-orchestrator.md added an
    explicit cap to its three previously-unbounded Shape-4 placeholders.
    Unit 3 (same migration) grew it by one more: qa-engineer.md moved from
    Shape 1 to Shape 2. The final unit of the migration (2026-08-11) closes
    the remaining six files: engineer.md, goal-condition-evaluator.md,
    learning-extractor.md, learnings-agent.md, product-discovery.md, and
    wrap-ticket.md each cleared their last cap/enum/tag gaps. The
    'compliant now' set is therefore now every SHAPE_ASSIGNMENTS file - the
    migration is complete, and this test now asserts that directly against
    SHAPE_ASSIGNMENTS rather than a hand-enumerated growing list, so a
    future new agent file lands in this set automatically as soon as it is
    both shape-assigned and genuinely compliant, with no list to remember
    to extend."""
    compliant_now = {name for name, v in EXPECTED_VIOLATIONS.items() if v == []}
    assert compliant_now == set(SHAPE_ASSIGNMENTS), (
        f"unexpected 'compliant now' set: {sorted(compliant_now)} vs "
        f"SHAPE_ASSIGNMENTS: {sorted(SHAPE_ASSIGNMENTS)}"
    )


# --- Final unit, Part B: two regression pins, accepted debt on the merged
# Unit 3 PR. See content/references/subagent-return-contract.md's Unit 3
# summary (qa-engineer.md) for the background this pins. ---

# Generalized, not hardcoded to qa-engineer.md - matches any agent file
# whose OWN prose asserts it always runs isolation: "worktree" (the exact
# phrasing qa-engineer.md uses twice, both independently confirmed by
# _find above). A future worktree-isolated writer is covered automatically
# as soon as its own file states this, with no list to remember to extend.
WORKTREE_MANDATORY_MARKER_RE = re.compile(
    r'always runs\s*`?isolation:\s*"worktree"`?', re.IGNORECASE
)
# A Bash heredoc write target assigned to a repo-relative '.agentic/...'
# path - either a shell variable assignment ('X_PATH=".agentic/foo"') or a
# bare 'mkdir -p .agentic/foo' - inside a mandated-isolation agent's own
# Bash block. Absolute paths ('/tmp/...') never match this pattern.
REPO_RELATIVE_AGENTIC_WRITE_RE = re.compile(
    r'(?:="|mkdir -p )(\.agentic/\S*)'
)


def test_worktree_mandatory_agents_write_artifacts_to_absolute_paths():
    """Regression pin (final unit, Part B, pin 1) - accepted debt on the
    merged Unit 3 PR: reverting every '/tmp/qa-reports' back to
    '.agentic/qa-reports' in qa-engineer.md currently left all ~1251
    bin/tests green, because nothing asserted that a mandatorily
    worktree-isolated agent must write its machine-consumed artifacts to
    an ABSOLUTE path rather than a repo-relative one - '.agentic/' is
    gitignored and independent per worktree checkout, so a write there is
    sealed inside the throwaway worktree and never seen again once it is
    removed (qa-engineer.md's own rationale, content/agents/qa-engineer.md
    §Report structure). This test discovers the mandated set from each
    file's OWN prose (WORKTREE_MANDATORY_MARKER_RE) rather than a
    hand-maintained list, so it generalizes to any future agent that gains
    a mandatory isolation: "worktree" requirement, not only qa-engineer.md.

    Mutation-proven: reverting qa-engineer.md's two '/tmp/qa-reports'
    occurrences back to '.agentic/qa-reports' (the exact regression this
    pin targets) turns this test RED; restoring them turns it GREEN. See
    the four-observation report in the PR description for the live
    RED/GREEN transcript."""
    mandated_files = [
        p for p in sorted(AGENTS_DIR.glob("*.md"))
        if WORKTREE_MANDATORY_MARKER_RE.search(p.read_text())
    ]
    assert mandated_files, (
        "expected at least one agent file whose own prose asserts "
        "mandatory isolation: \"worktree\" (qa-engineer.md as of this "
        "writing) - zero found; WORKTREE_MANDATORY_MARKER_RE may have "
        "drifted from the live prose it is meant to match"
    )
    violations = []
    for p in mandated_files:
        text = p.read_text()
        for block in _extract_fenced_blocks(text):
            _lang, content = block
            for m in REPO_RELATIVE_AGENTIC_WRITE_RE.finditer(content):
                violations.append(
                    f"{p.name}: writes machine-consumed artifact to "
                    f"repo-relative '{m.group(1)}' despite this file's own "
                    "prose asserting mandatory isolation: \"worktree\" - "
                    "use an absolute path (e.g. /tmp/...) instead"
                )
    assert violations == [], violations


def test_screenshot_evidence_json_path_producer_consumer_coupling():
    """Regression pin (final unit, Part B, pin 2) - accepted debt on the
    merged Unit 3 PR: nothing ties qa-engineer.md's emitted
    `screenshot_evidence_json_path` field name to
    content/commands/ds-implement-ticket.md Phase 8.5's reader of that
    same field; a rename on either side yields dead evidence links with
    nothing red. This pin asserts the exact field-name literal is present
    in both the producer (qa-engineer.md's pointer-return schema) and the
    consumer (ds-implement-ticket.md's Phase 8.5 QA screenshot evidence
    capture step) - a rename on either side, without the matching rename
    on the other, turns this test RED.

    Mutation-proven: renaming the field in qa-engineer.md's schema line
    (`screenshot_evidence_json_path: <path>`) alone, or renaming it in
    ds-implement-ticket.md's Phase 8.5 read alone, each independently
    turns this test RED; restoring either turns it GREEN. See the
    four-observation report in the PR description for the live
    RED/GREEN transcript."""
    field_name = "screenshot_evidence_json_path"
    producer_text = (AGENTS_DIR / "qa-engineer.md").read_text()
    consumer_path = (
        REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"
    )
    consumer_text = consumer_path.read_text()
    assert f"{field_name}: <path>" in producer_text, (
        f"qa-engineer.md no longer declares the '{field_name}' field in "
        "its pointer-return schema - the producer side of this coupling "
        "is broken"
    )
    assert field_name in consumer_text, (
        f"ds-implement-ticket.md no longer references '{field_name}' - "
        "the consumer side of this coupling is broken (Phase 8.5's QA "
        "screenshot evidence read)"
    )
    assert "Phase 8.5" in consumer_text, (
        "ds-implement-ticket.md's Phase 8.5 heading is gone or renamed - "
        "re-anchor this pin's consumer-side check to wherever the "
        "screenshot-evidence read step now lives"
    )
