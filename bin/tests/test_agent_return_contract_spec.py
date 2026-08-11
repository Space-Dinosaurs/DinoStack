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
            verify each checker's logic independent of the real corpus).

Downstream consumers: .github/workflows/bin-tests.yml python-bin-tests job,
            which runs `pytest bin/tests/ -q` - full-directory glob
            discovery, no per-file wiring required for a new test_*.py file.

Failure modes: pure static analysis, no I/O beyond reading .md files under
            this repo.
            NOT_YET_MIGRATED allowlists every real agent file that HAS a
            recognized return-contract shape as of Unit 0 but is not yet
            migrated to its shape's tagging/enum/cap obligation - Unit 1/3/4
            remove a file once it is actually migrated; leaving a migrated
            file in the allowlist silently disables enforcement for it
            (test_allowlist_has_no_stale_entries only catches files that no
            longer exist, not files that were migrated but never removed).
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

Performance: negligible - reads <30 small text files.
"""
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
# content/commands/ds-wrap.md:439,443.) ---

SHAPE_ASSIGNMENTS = {
    # Shape 1 - tagged prose fields.
    "architect.md": 1,
    "debugger.md": 1,
    "dependency-auditor.md": 1,
    "investigator.md": 1,
    "orchestration-planner.md": 1,
    "perf-analyst.md": 1,
    "product-discovery.md": 1,
    "qa-engineer.md": 1,
    "security-auditor.md": 1,
    # Shape 2 - structured schema-object return.
    "engineer.md": 2,
    "learning-extractor.md": 2,
    "learnings-agent.md": 2,
    "wrap-ticket.md": 2,
    "adr-drift-detector.md": 2,
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

# Files with a shape assignment above but not yet migrated to that shape's
# affirmative obligation - genuinely non-compliant today (see
# test_not_yet_migrated_entries_are_actually_unmigrated).
# goal-condition-evaluator.md is deliberately NOT listed here - it is
# already compliant under its shape's checker. engineer.md is DELIBERATELY
# BACK in this set as of round 4 (M1 fix): the
# SHAPE2_PASSTHROUGH_EXEMPT_FIELDS exemption that previously manufactured
# its compliant-now status was deleted (falsified rationale - no downstream
# consumer forwards pr_description_body verbatim; grep confirms the only
# hits are engineer.md's own definition). Unit 0 does not edit agent files,
# so engineer.md's cap is not added this round.
NOT_YET_MIGRATED = {
    # Shape 1
    "architect.md",
    "debugger.md",
    "dependency-auditor.md",
    "investigator.md",
    "orchestration-planner.md",
    "perf-analyst.md",
    "product-discovery.md",
    "qa-engineer.md",
    "security-auditor.md",
    # Shape 2 (target)
    "engineer.md",
    "learning-extractor.md",
    "learnings-agent.md",
    "wrap-ticket.md",
    "adr-drift-detector.md",
    # Shape 3 (narrow - additive cap sentence only, six validated lines untouched)
    "skeptic.md",
    # Shape 4 (narrow - one field's cap addition)
    "release-orchestrator.md",
}


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
ENUM_VALUE_LIST_RE = re.compile(r"\S+\s*\|\s*\S+")
# Round-4 M3/M4 fix: requires an adjacent digit (mirrors Shape 1's
# digit-requiring CAP_RE) so a bare 'max'/'cap' keyword with no numeric
# bound cannot satisfy the obligation - see _shape2_has_cap_with_digit.
# 'truncated (to)' is recognized alongside cap/max/maxLength - the real
# corpus phrases numeric caps this way (engineer.md's raw_output field:
# "truncated to 4000 chars").
SHAPE2_CAP_KEYWORDS_RE = re.compile(
    r"\b(cap(?:ped)?|max(?:imum)?|maxLength|truncated(?:\s+to)?)\b",
    re.IGNORECASE,
)
SHAPE2_ONE_LINE_RE = re.compile(r"<\s*(one|single)[- ]line\b", re.IGNORECASE)
# Round-4 M3 fix: the bare '\.md\b' alternative accepted ANY line
# mentioning a '.md' path as a declared bound (round-4 Major finding) - a
# file's cap declaration must use the explicit 'defined in'/'defined once'
# pointer phrasing, never an incidental filename mention.
SHAPE2_POINTER_RE = re.compile(
    r"\bdefined in\b|\bdefined once\b", re.IGNORECASE
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
    if ENUM_VALUE_LIST_RE.search(rest):
        return True
    for bl in body:
        if bl.strip().startswith("#") and ENUM_VALUE_LIST_RE.search(bl):
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


def _shape2_has_cap_with_digit(text):
    """True only when a cap-shaped keyword AND a digit both appear in
    `text` (round-4 M3/M4 fix - SHAPE2_CAP_KEYWORDS_RE alone requires no
    digit, unlike Shape 1's CAP_RE, so a bare 'max'/'cap' with no numeric
    bound previously satisfied the obligation)."""
    return bool(SHAPE2_CAP_KEYWORDS_RE.search(text)) and bool(re.search(r"\d", text))


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
    named enum-shaped fields like 'lint: pass | fail | not_run')."""
    if ENUM_VALUE_LIST_RE.search(rest):
        return True
    combined = full_line + " " + " ".join(body)
    if _shape2_has_cap_with_digit(combined):
        return True
    if SHAPE2_ONE_LINE_RE.search(combined):
        return True
    if SHAPE2_POINTER_RE.search(combined):
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
        # enum/cap/one-line/pointer obligation (round-4 M3 fix).
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
    if shape == "scalar":
        # A single physical schema line is itself a one-line bound, the
        # same logic '<one-line ...>' states explicitly.
        return True
    return _shape2_text_is_bounded(full_line, rest, body)


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
                "repeated content but declares no cap, one-line marker, or "
                "schema pointer"
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


def _shape3_value_bounded(value):
    v = value.strip()
    if not v:
        return False
    if re.fullmatch(r"true\|false", v, re.IGNORECASE):
        return True
    if ENUM_VALUE_LIST_RE.search(v):
        return True
    if re.fullmatch(r"<?\s*\d+\s*>?", v):
        return True
    if SHAPE2_ONE_LINE_RE.search(v):
        return True
    return False


def check_shape3(text, filename="<fixture>"):
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
    _lang, content = blocks[0]
    lines = [ln for ln in content.split("\n") if ln.strip()]
    if len(lines) > 8:
        return [
            f"{filename}: Shape-3 template has {len(lines)} lines, expected "
            "<= 8 for a fixed literal-line template"
        ]
    violations = []
    for ln in lines:
        m = SHAPE3_LINE_RE.match(ln)
        if not m:
            violations.append(
                f"{filename}: Shape-3 line '{ln}' is not a 'Label: value' line"
            )
            continue
        label, value = m.group(1), m.group(2)
        if not _shape3_value_bounded(value):
            violations.append(
                f"{filename}: Shape-3 line '{label}:' value '{value}' is "
                "neither a closed enum, a bare count, nor bounded to one "
                "line by its own placeholder text"
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
    elif not ENUM_VALUE_LIST_RE.search(status_m.group(1)):
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
            # Round-4 M4 fix: the cap requirement is now unconditional for
            # EVERY placeholder in every subsequent '##' sub-section (per
            # amendment §5), not gated behind a narrative-hint-word
            # heuristic - the deleted SHAPE4_NARRATIVE_HINT_RE heuristic
            # let release-orchestrator.md's placeholder escape detection
            # whenever its wording happened not to contain
            # which/what/why/how/describe/explain/summary/reason.
            # _shape2_has_cap_with_digit also requires an adjacent digit,
            # so a bare 'cap'/'max' keyword with no numeric bound no
            # longer satisfies the requirement.
            if not _shape2_has_cap_with_digit(placeholder):
                violations.append(
                    f"{filename}: '## {title}' placeholder '<{placeholder}>' "
                    "declares no numeric cap (expected a cap/max keyword "
                    "with an adjacent digit)"
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


def test_shape2_engineer_is_not_yet_migrated():
    """engineer.md is NOT compliant now (round-4 M1 fix): the
    SHAPE2_PASSTHROUGH_EXEMPT_FIELDS exemption that previously manufactured
    its compliant-now status is deleted, so pr_description_body's missing
    cap is a real, genuine violation - independently confirmed by name
    below, not merely 'the file has some violations'.

    This also independently VERIFIES (rather than merely asserting, as the
    pre-round-4 docstring did) that raw_output's 'truncated to 4000 chars'
    bound is correctly recognized despite being nested inside the
    quality_gate_results object - the M3 recursion fix walks into that
    container instead of treating it as an unconditionally-bounded
    structural field."""
    path = AGENTS_DIR / "engineer.md"
    violations = check_contract(path.read_text(), "engineer.md")
    assert violations, (
        "engineer.md is listed in NOT_YET_MIGRATED but its Shape-2 checker "
        "found it fully compliant"
    )
    assert any("pr_description_body" in v for v in violations), violations
    assert not any("raw_output" in v for v in violations), (
        "raw_output declares an explicit 'truncated to 4000 chars' bound "
        f"nested inside quality_gate_results - it must not be flagged: {violations}"
    )


# --- Shape 3 fixture tests ---


def test_shape3_compliant_fixture_is_contract_compliant():
    text = _read_fixture("shape3_compliant_agent.md")
    violations = check_contract(text, "shape3_compliant_agent.md", shape=3)
    assert violations == [], violations


def test_shape3_missing_bound_is_flagged():
    text = _read_fixture("shape3_missing_bound_agent.md")
    violations = check_contract(text, "shape3_missing_bound_agent.md", shape=3)
    assert violations, "expected a violation for an unbounded Evidence value"


def test_shape3_goal_condition_evaluator_is_contract_compliant():
    """goal-condition-evaluator.md is claimed COMPLIANT NOW - verified
    independently: GOAL_MET: true|false is a closed enum, and
    Evidence: <one-line ...> is explicitly bounded to one line."""
    path = AGENTS_DIR / "goal-condition-evaluator.md"
    violations = check_contract(path.read_text(), "goal-condition-evaluator.md")
    assert violations == [], violations


def test_shape3_skeptic_is_not_yet_migrated():
    """skeptic.md's six conductor-validated lines are present verbatim, but
    the Calibration section declares no cap on finding-description length
    today - genuinely non-compliant, as NOT_YET_MIGRATED expects."""
    path = AGENTS_DIR / "skeptic.md"
    violations = check_contract(path.read_text(), "skeptic.md")
    assert violations != [], (
        "skeptic.md is listed in NOT_YET_MIGRATED but its Shape-3 checker "
        "found it fully compliant"
    )
    assert any("cap" in v.lower() for v in violations)


# --- Shape 4 fixture tests ---


def test_shape4_compliant_fixture_is_contract_compliant():
    text = _read_fixture("shape4_compliant_agent.md")
    violations = check_contract(text, "shape4_compliant_agent.md", shape=4)
    assert violations == [], violations


def test_shape4_missing_cap_is_flagged():
    text = _read_fixture("shape4_missing_cap_agent.md")
    violations = check_contract(text, "shape4_missing_cap_agent.md", shape=4)
    assert violations, "expected a violation for the uncapped 'Failures and blockers' placeholder"


def test_shape4_release_orchestrator_is_not_yet_migrated():
    path = AGENTS_DIR / "release-orchestrator.md"
    violations = check_contract(path.read_text(), "release-orchestrator.md")
    assert violations != [], (
        "release-orchestrator.md is listed in NOT_YET_MIGRATED but its "
        "Shape-4 checker found it fully compliant"
    )


# --- Real content/agents/*.md enforcement ---


def test_not_yet_migrated_files_are_accounted_for():
    """
    Every discovered content/agents/*.md file is either contract-compliant
    under its own shape, present in NOT_YET_MIGRATED, or present in
    EXEMPT_FILE_ARTIFACT. A file that is in none of those (e.g. a new agent
    file added without a shape assignment, or with an unrecognized heading)
    fails here rather than silently passing unnoticed.
    """
    for path in _real_agent_files():
        if path.name in NOT_YET_MIGRATED or path.name in EXEMPT_FILE_ARTIFACT:
            continue
        violations = check_contract(path.read_text(), path.name)
        assert violations == [], (
            f"{path.name} is not in NOT_YET_MIGRATED or "
            f"EXEMPT_FILE_ARTIFACT and is not contract-compliant: "
            f"{violations}"
        )


def test_not_yet_migrated_entries_are_actually_unmigrated():
    """
    The other half of the migration contract: every file listed in
    NOT_YET_MIGRATED must still be genuinely non-compliant when checked
    directly (independent of the skip in
    test_not_yet_migrated_files_are_accounted_for above). Migrating a
    file's return-contract section makes it contract-compliant; if that
    file is left on NOT_YET_MIGRATED anyway, THIS assertion goes red - a
    migration that forgets to shrink NOT_YET_MIGRATED for a file it just
    migrated is caught here, not silently passed. Shrinking the allowlist
    (removing the now-migrated file) is the only way to make this suite
    green again for that file.
    """
    for name in sorted(NOT_YET_MIGRATED):
        path = AGENTS_DIR / name
        violations = check_contract(path.read_text(), name)
        assert violations != [], (
            f"{name} is listed in NOT_YET_MIGRATED but its return-contract "
            "section is already fully contract-compliant - remove it from "
            "NOT_YET_MIGRATED so test_not_yet_migrated_files_are_accounted_for "
            "starts enforcing it"
        )


def test_allowlist_has_no_stale_entries():
    """NOT_YET_MIGRATED and EXEMPT_FILE_ARTIFACT must only name files that
    currently exist."""
    discovered = {p.name for p in _real_agent_files()}
    stale = (NOT_YET_MIGRATED | EXEMPT_FILE_ARTIFACT) - discovered
    assert stale == set(), (
        "NOT_YET_MIGRATED/EXEMPT_FILE_ARTIFACT name files that no longer "
        f"exist: {sorted(stale)}"
    )


def test_allowlists_are_disjoint():
    """A file must not be classified as both 'has an unmigrated shape' and
    'exempt from all shapes' - the two allowlists are mutually exclusive by
    construction."""
    overlap = NOT_YET_MIGRATED & EXEMPT_FILE_ARTIFACT
    assert overlap == set(), f"files present in both allowlists: {sorted(overlap)}"


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


def test_shape_assignments_and_allowlists_cover_all_real_files():
    """Every real content/agents/*.md file is exactly one of: compliant now
    (no allowlist entry, no exemption), listed in NOT_YET_MIGRATED, or
    listed in EXEMPT_FILE_ARTIFACT. This is the 18-file tally check.

    Round-4 M1 fix: engineer.md moved OUT of the 'compliant now' set (its
    SHAPE2_PASSTHROUGH_EXEMPT_FIELDS exemption was deleted as a spec
    deviation) and back into NOT_YET_MIGRATED - see
    test_shape2_engineer_is_not_yet_migrated."""
    discovered = {p.name for p in _real_agent_files()}
    compliant_now = discovered - NOT_YET_MIGRATED - EXEMPT_FILE_ARTIFACT
    assert compliant_now == {"goal-condition-evaluator.md"}, (
        f"unexpected 'compliant now' set: {sorted(compliant_now)}"
    )


# Note: there is deliberately no `discovered == NOT_YET_MIGRATED |
# EXEMPT_FILE_ARTIFACT` equality test here without the "compliant now"
# carve-out above. That was the shape of the pre-fix bug
# (test_allowlist_covers_all_discovered_agent_files_today): it would go red
# on every successful migration, since a migrated file is correctly REMOVED
# from NOT_YET_MIGRATED without being added anywhere else, legitimately
# shrinking the union over time.
# test_shape_assignments_and_allowlists_cover_all_real_files above pins the
# union PLUS the exact "compliant now" set, which is what actually catches
# an unclassified new agent file without blocking legitimate migrations -
# a migration moves a name out of NOT_YET_MIGRATED and into the
# "compliant now" set, both sides of which this test tracks explicitly.
