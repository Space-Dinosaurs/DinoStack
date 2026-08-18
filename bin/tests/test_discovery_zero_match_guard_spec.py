#!/usr/bin/env python3
"""
Purpose: Regression guard for DS-176 (the vacuous-pass check class): every
         discovery-based check in this repo whose guard carries the literal
         phrase "discovery is broken, not clean" must hard-fail on zero
         discovered items in one of three detectable forms (see
         content/references/code-standards-detail.md
         §Discovery-Based Check Discipline). This test discovers those
         guard sites BY CONTENT (never a hand-typed file list) and
         bidirectionally pins the resulting set against a small, content-
         derived classification table, so an accidental deletion or a
         weakening edit (e.g. dropping the `exit 1`, or turning the guard
         into a bare log statement) reddens this suite.
Public API: pytest test functions only. `_ast_derived_helper_call_set`,
         `_conforms_to_mandated_form`, `_discover_live_sites`,
         `_is_docstring_hit`, `_manifest_public_api_names`,
         `_normalized_scan`, `_site_label`, and `_site_label_python` are
         internal helpers exercised directly by test functions below (the
         two helpers backing the pin test itself are self-covering - the
         same AST walk that pins this field also scans the pin test's own
         body). This list is no longer hand-reconciled: it is PINNED by
         `test_manifest_public_api_matches_ast_derived_call_set` below,
         which walks every `test_*` function's AST call sites against this
         module's own `_`-prefixed defs and asserts bidirectional set
         equality against this sentence's own backtick-quoted names - a
         hand-edit that omits or phantom-adds a name reddens that test
         (DS-177 Fix 5, re-pinned rework4 after a helper name was added to
         a test without a matching manifest update and went undetected by
         hand-reconciliation alone).
Upstream deps: `git ls-files` (repo-relative, tracked-only discovery -
         this checkout's `.claude/worktrees/agent-*` count fluctuates
         session-to-session as isolation worktrees are created and reaped,
         each a full copy of every guard site; an unfiltered `rglob()`
         from the repo root would
         multiply every LIVE_GUARD_SITES entry by (1 + worktree count) and
         either mask the problem under bare-basename keys or redden this
         gate locally while CI, a clean checkout, stays green - see the
         `_tracked_relative_paths()` function in
         bin/tests/test_ticket_offer_gate_trigger_wording_spec.py (grep
         for that function name - a raw line-number citation here has
         already drifted twice) for the identical precedent this reuses).
         `LIVE_GUARD_SITES` keys
         are `(repo_relative_path, derived_label)` pairs; the label is
         content-derived (AST scope resolution for .py, nearest enclosing
         `jobs:` job name for .yml), never hand-typed, so a 3-guards-to-2
         deletion cannot silently pass under a stale hand-typed cardinal.
Downstream consumers: bin-tests.yml python-bin-tests job
         (`pytest bin/tests/ -q`), full-directory glob discovery under
         `bin/tests/`, no per-file wiring required.
Failure modes: (a) a live guard site is deleted or weakened to a fourth,
         undetectable idiom (log-only, no `exit 1` / `sys.exit(1)` /
         assert) - caught by `test_each_live_guard_conforms_to_mandated_form`
         and the mutation tests below; (b) `LIVE_GUARD_SITES` drifts from the
         live tree (a site added or removed without updating the pin) -
         caught by the bidirectional set-equality test, in BOTH directions
         (a phantom entry naming something nonexistent is caught by
         `LIVE_GUARD_SITES - disk_live`, not just an omission); (c) phrase
         discovery itself finds nothing (this file's own vacuous-pass
         guard, `test_discovery_finds_phrase_occurrences`).
False-positive reasoning: prose references to the guard phrase exist
         purely as documentation - bin/tests/test_ticket_offer_gate_trigger_
         wording_spec.py:36 (module docstring, explaining this file's own
         discipline by citation) and :164-165 (a FUNCTION docstring
         explaining a *different*, non-phrase-carrying guard's rationale).
         The exact count (currently 2) is asserted with `==`, never
         hand-typed here, by `test_docstring_reference_not_flagged_as_violation`
         - re-derive fresh at PR time, never trust a cited cardinal. Both
         are classified DOCUMENTATION by AST (first-statement string
         constant of a Module/FunctionDef), out of scope, not a violation.
AC-5 scope justification (re-derive fresh at PR time, never trust a cited
         cardinal): as of this file's introduction, 29-of-77 files matched
         by the flat (non-recursive) `bin/tests/*.py` glob use a discovery
         pattern (`.glob(`, `.rglob(`, `os.walk(`, or `git ls-files`),
         against 7 live guards (this file's own vacuous-pass guard - the
         last entry in `LIVE_GUARD_SITES` below - plus the pre-existing
         entries above it) carrying the mandated-form phrase, across 4
         files. (The recursive `bin/tests/**/*.py` glob yields 80, not 77
         - a different method with a different denominator; this
         justification cites the flat glob because that is the method
         that was actually run.) A universal meta-linter over all 29 is
         out of this ticket's two-item scope and requires the same
         DOCUMENTATION-vs-CODE judgment the AST approach makes tractable
         for these 4 files but not yet repo-wide - a deliberate,
         documented limitation, not a silent gap.
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

GUARD_PHRASE = "discovery is broken, not clean"

SEARCH_SUFFIXES = {".py", ".yml", ".yaml"}

# Single source of truth for the module docstring's "False-positive
# reasoning" cardinal (DS-177 rework3 Minor fix). The docstring's prose
# ("currently 2") and test_docstring_reference_not_flagged_as_violation's
# assertion both read this constant instead of carrying independent
# hand-typed copies; test_module_docstring_cites_current_reference_count
# below proves the coupling by asserting the docstring text itself embeds
# this constant's live value, so a divergence (constant changed, prose
# not) reddens rather than passing silently.
DOCSTRING_REFERENCE_COUNT = 2

# Content-derived, never hand-typed (DS-176 Round-2 Critical fix). All but
# the last entry below pre-date this file; the last entry is this file's
# own vacuous-pass guard, added because this file's own discovery guard
# carries the same literal phrase and is therefore itself discoverable by
# the mechanism it tests.
LIVE_GUARD_SITES = frozenset(
    {
        (".github/workflows/bin-tests.yml", "hooks-python-tests"),
        (".github/workflows/bin-tests.yml", "bin-sh-tests"),
        (".github/workflows/hooks-tests.yml", "hooks-js-tests"),
        (".github/workflows/hooks-tests.yml", "hooks-sh-tests"),
        ("hooks/tests/test-hooks-pep604-guard.py", "hook_files"),
        ("hooks/tests/test-hooks-pep604-guard.py", "test_files"),
        (
            "bin/tests/test_discovery_zero_match_guard_spec.py",
            "test_discovery_finds_phrase_occurrences",
        ),
    }
)


def _tracked_relative_paths() -> list[pathlib.Path]:
    """Git-tracked paths with a SEARCH_SUFFIXES extension, resolved
    relative to REPO_ROOT. Scoping via `git ls-files` (rather than an
    unfiltered directory walk) matters because this checkout carries a
    fluctuating number of `.claude/worktrees/agent-*` copies of the whole
    tree - created and reaped session-to-session as isolation worktrees
    spin up and down (fluctuating count, see the module docstring's
    Upstream deps note) - none of which are part of
    the primary worktree's git index. DS-177 Fix 4: no cardinal is
    asserted here, since one would go stale independently of this
    function's own behavior."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    paths: list[pathlib.Path] = []
    for rel in result.stdout.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        p = pathlib.Path(rel)
        if p.suffix in SEARCH_SUFFIXES:
            paths.append(p)
    return paths


def _normalized_scan_positions(text: str) -> list[tuple[int, int]]:
    """Whitespace-normalize (collapse runs of whitespace to a single ' ')
    before matching GUARD_PHRASE, then back-map each match to an
    original-text (orig_start, orig_end) 0-indexed, inclusive CHARACTER
    offset pair - not a line range. Form C needs this column-level
    precision (a one-line assert's condition and message share the same
    line number, so line comparison alone cannot distinguish them);
    `_normalized_scan` below derives its line ranges from this."""
    orig_indices: list[int] = []
    normalized_chars: list[str] = []
    prev_was_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not prev_was_space:
                normalized_chars.append(" ")
                orig_indices.append(i)
            prev_was_space = True
        else:
            normalized_chars.append(ch)
            orig_indices.append(i)
            prev_was_space = False
    normalized = "".join(normalized_chars)

    positions: list[tuple[int, int]] = []
    search_from = 0
    phrase_len = len(GUARD_PHRASE)
    while True:
        idx = normalized.find(GUARD_PHRASE, search_from)
        if idx == -1:
            break
        end_idx = idx + phrase_len - 1
        orig_start = orig_indices[idx]
        orig_end = orig_indices[end_idx]
        positions.append((orig_start, orig_end))
        search_from = idx + 1
    return positions


def _line_start_offsets(text: str) -> list[int]:
    """`starts[i]` is the absolute character offset of the start of
    (1-indexed) line `i + 1`. Used to convert an AST node's
    `lineno`/`col_offset` into an absolute character offset comparable
    against `_normalized_scan_positions`' output. Splits ONLY on `\\n` -
    deliberately NOT `str.splitlines()`'s broader break set (`\\x0b`,
    `\\x0c`, U+2028, U+2029, U+0085, ...), none of which CPython's
    tokenizer (and therefore AST `lineno`) treats as a line boundary; a
    `str.splitlines()` split diverges from AST line numbering the moment
    one of those characters appears earlier in the file, misaligning every
    subsequent offset (DS-177 rework Minor 1 fix; `_check_form_c`'s
    `text_lines` has the matching fix - see
    `test_form_c_form_feed_does_not_misalign_offsets`). This is NOT a
    claim that `\\n`-only splitting is exactly equivalent to tokenizer line
    boundaries in general: a lone `\\r` (old Mac line ending) IS also a
    tokenizer/AST line boundary that `\\n`-only splitting would miss,
    causing the same class of misalignment. That residual case is
    unreachable via this file's real discovery path (never via an
    in-memory mutation-test fixture, which controls its own bytes)
    because every real file is read with `pathlib.Path.read_text()`,
    which applies universal-newline translation - `\\r` and `\\r\\n` are
    already collapsed to `\\n` before the text ever reaches this function
    (verified: a CRLF fixture read via `read_text()` contains no `\\r` and
    classifies (True, 'C'))."""
    starts = [0]
    offset = 0
    for ch in text:
        offset += 1
        if ch == "\n":
            starts.append(offset)
    return starts


def _normalized_scan(text: str) -> list[tuple[int, int]]:
    """Back-map each `_normalized_scan_positions` character-offset match
    to an original-text (start_line, end_line) 1-indexed, inclusive line
    range. Catches a wrapped/reformatted occurrence a single-line scan
    misses (DS-176 Round-2 Major 2) - see
    test_wrap_tolerant_scan_finds_split_occurrence."""
    matches: list[tuple[int, int]] = []
    for orig_start, orig_end in _normalized_scan_positions(text):
        start_line = text.count("\n", 0, orig_start) + 1
        end_line = text.count("\n", 0, orig_end) + 1
        matches.append((start_line, end_line))
    return matches


def _docstring_line_ranges(text: str) -> list[tuple[int, int]]:
    """Every Module/FunctionDef/AsyncFunctionDef/ClassDef docstring's
    (start_line, end_line) range, via AST - not a text-based heuristic."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    ranges: list[tuple[int, int]] = []

    def _check_body(body: list) -> None:
        if not body:
            return
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            end = getattr(first, "end_lineno", first.lineno)
            ranges.append((first.lineno, end))

    _check_body(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _check_body(node.body)
    return ranges


def _is_docstring_hit(text: str, line_range: tuple[int, int]) -> bool:
    for start, end in _docstring_line_ranges(text):
        if start <= line_range[0] <= end or start <= line_range[1] <= end:
            return True
    return False


_JOB_NAME_RE = re.compile(r"^  ([\w-]+):$")
_MODULE_GUARD_RE = re.compile(r"^\s*if not ([\w.]+)\s*:")


def _site_label_yaml(lines: list[str], line_range: tuple[int, int]) -> str | None:
    """Scan upward from the hit for the nearest `^  ([\\w-]+):$` job-name
    line under `jobs:`."""
    for i in range(line_range[0] - 1, -1, -1):
        m = _JOB_NAME_RE.match(lines[i])
        if m:
            return m.group(1)
    return None


def _site_label_python(text: str, line_range: tuple[int, int]) -> str | None:
    """AST SCOPE RESOLUTION, not a nearest-`def` line scan (DS-176 Round-3
    Critical fix). Walk the parsed module and find the innermost
    FunctionDef/AsyncFunctionDef whose line span CONTAINS the hit; a
    preceding sibling def is not an enclosing scope and must not match. If
    no enclosing function contains the hit (module-level code), fall back
    to the identifier in the nearest preceding `if not <ident>:` guard
    line - this is the shape both test-hooks-pep604-guard.py guards use."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    hit_line = line_range[0]
    candidates: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", node.lineno)
            if start <= hit_line <= end:
                candidates.append((end - start, node.name))
    if candidates:
        candidates.sort(key=lambda t: t[0])
        return candidates[0][1]

    # Split ONLY on "\n" - see `_line_start_offsets`' docstring (DS-177
    # rework2 Major fix). `line_range` is derived from `_normalized_scan`,
    # which counts `\n` only; `str.splitlines()` here would misalign
    # `lines[i]` against that line number the moment a non-`\n` line-break
    # character (form feed, U+2028, ...) appears earlier in the file.
    lines = text.split("\n")
    lower_bound = max(-1, hit_line - 16)
    for i in range(hit_line - 1, lower_bound, -1):
        m = _MODULE_GUARD_RE.match(lines[i])
        if m:
            return m.group(1)
    return None


def _site_label(
    suffix: str, text: str, line_range: tuple[int, int]
) -> str | None:
    if suffix in (".yml", ".yaml"):
        # Split ONLY on "\n" - see `_line_start_offsets`' docstring
        # (DS-177 rework2 Major fix). `line_range` is `\n`-counted by
        # `_normalized_scan`; `str.splitlines()` here would misalign the
        # indexed line the moment a non-`\n` line-break character appears
        # earlier in the file.
        return _site_label_yaml(text.split("\n"), line_range)
    if suffix == ".py":
        return _site_label_python(text, line_range)
    return None


def _check_form_a(lines: list[str], line_range: tuple[int, int]) -> bool:
    window_line = "\n".join(lines[line_range[0] - 1 : line_range[1]])
    if ">&2" not in window_line:
        return False
    after = lines[line_range[0] - 1 : min(len(lines), line_range[1] + 6)]
    return bool(re.search(r"exit\s+1\b", "\n".join(after)))


def _check_form_b(lines: list[str], line_range: tuple[int, int]) -> bool:
    nearby = lines[max(0, line_range[0] - 5) : min(len(lines), line_range[1] + 6)]
    joined_nearby = "\n".join(nearby)
    if "file=sys.stderr" not in joined_nearby and "sys.stderr.write" not in joined_nearby:
        return False
    after = lines[line_range[0] - 1 : min(len(lines), line_range[1] + 6)]
    joined_after = "\n".join(after)
    return "sys.exit(1)" in joined_after or "raise SystemExit" in joined_after


def _byte_col_to_char_col(line: str, byte_col: int) -> int:
    """`ast` node `col_offset`/`end_col_offset` values are UTF-8 BYTE
    offsets into their line (the `ast` module's documented contract),
    while `_line_start_offsets` and `_normalized_scan_positions` both
    count CHARACTERS. Comparing the two directly without this conversion
    shifts the comparison by one position per multi-byte character
    preceding the offset on that line (DS-177 Fix 2 - measured: 20
    multi-byte characters earlier on the line made a conforming Form C
    guard misclassify as NONE). Converts by encoding `line` to UTF-8,
    slicing the first `byte_col` bytes, decoding back to str, and taking
    the resulting character length - AST byte offsets always land on a
    UTF-8 boundary (token boundaries in valid source), so this slice never
    splits a multi-byte sequence."""
    return len(line.encode("utf-8")[:byte_col].decode("utf-8"))


def _check_form_c(text: str, line_range: tuple[int, int]) -> bool:
    """AST-based, at CHARACTER-OFFSET precision, not proximity regex or
    line-span containment (DS-176 rework-2 Major fix, then re-fixed to
    column granularity in the same round; DS-177 fixed three further
    defects in this same comparison - see Fix 1/2/3 notes below). Line-
    range containment on `node.msg` alone is still not sufficient: a
    one-liner assert's CONDITION and MESSAGE share the same physical line
    number (`assert "<phrase>" not in out, "unexpected"` - phrase in the
    condition, "unexpected" the message, both on line N), so line-level
    comparison cannot tell them apart. This re-locates every phrase hit
    whose (start_line, end_line) equals `line_range` (DS-177 Fix 1: ALL
    such hits, not just the first found - a one-liner where the phrase
    appears in both the condition AND the message, e.g. `assert "<p>" in
    out, "bad - <p>"`, has two same-line-range hits, and testing only the
    leftmost one rejected a genuinely conforming guard) at exact
    character-offset precision (via `_normalized_scan_positions`, DS-177
    Fix 2: `node.msg`'s AST col_offset/end_col_offset are UTF-8 BYTE
    offsets and must be converted to character offsets via
    `_byte_col_to_char_col` before comparison against the character-offset
    hit spans, or a multi-byte character earlier on the line shifts every
    downstream comparison) and requires the hit span to fall FULLY INSIDE
    `node.msg`'s own character-offset span (DS-177 Fix 3: containment, not
    overlap - a straddling hit like `assert discovery is broken, not
    clean` (phrase spanning the test/msg comma boundary) overlaps
    `node.msg`'s span without being contained in it and must NOT conform)
    - never the whole assert statement, and never `node.test`. Also still
    catches the earlier same-line `print("...phrase"); assert True` shape:
    `assert True` has no `msg` at all, so it is skipped outright."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False

    hit_offsets: list[tuple[int, int]] = []
    for orig_start, orig_end in _normalized_scan_positions(text):
        start_line = text.count("\n", 0, orig_start) + 1
        end_line = text.count("\n", 0, orig_end) + 1
        if (start_line, end_line) == line_range:
            hit_offsets.append((orig_start, orig_end))
    if not hit_offsets:
        return False

    line_starts = _line_start_offsets(text)
    # Split ONLY on "\n" - see `_line_start_offsets`' docstring (DS-177
    # rework Minor 1 fix). `str.splitlines()` here would misalign
    # `text_lines[msg.lineno - 1]` against AST `lineno` the moment a
    # non-`\n` line-break character (form feed, U+2028, ...) appears
    # earlier in the file.
    text_lines = text.split("\n")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        msg = node.msg
        if msg is None:
            continue
        msg_start_line_text = text_lines[msg.lineno - 1]
        msg_start_char_col = _byte_col_to_char_col(msg_start_line_text, msg.col_offset)
        msg_start_offset = line_starts[msg.lineno - 1] + msg_start_char_col
        msg_end_lineno = getattr(msg, "end_lineno", msg.lineno)
        msg_end_col = getattr(msg, "end_col_offset", msg.col_offset)
        msg_end_line_text = text_lines[msg_end_lineno - 1]
        msg_end_char_col = _byte_col_to_char_col(msg_end_line_text, msg_end_col)
        msg_end_offset = line_starts[msg_end_lineno - 1] + msg_end_char_col - 1
        for hit_start_offset, hit_end_offset in hit_offsets:
            if msg_start_offset <= hit_start_offset and hit_end_offset <= msg_end_offset:
                return True
    return False


def _conforms_to_mandated_form(
    suffix: str, text: str, line_range: tuple[int, int]
) -> tuple[bool, str]:
    """Form A (shell): phrase line has `>&2`; `exit 1` (or equivalent)
    within a few lines after. Form B (python): phrase inside
    `print(..., file=sys.stderr)` or `sys.stderr.write(...)`; `sys.exit(1)`
    or `raise SystemExit` within a few lines after. Form C (pytest-assert -
    the dominant repo form): a single `assert <expr>, "<msg>"` statement,
    where the assert's MESSAGE (`node.msg`, not the whole statement and not
    `node.test`) IS the phrase-carrier and the assert IS the failure
    mechanism - AST-verified (the phrase hit must fall inside `node.msg`'s
    own source span), not a `\\bassert\\b` proximity regex and not
    whole-statement line-span containment. For .py files, a phrase
    occurring inside a docstring is classified DOCUMENTATION - out of
    scope, not a violation, not a guard."""
    # Split ONLY on "\n" - see `_line_start_offsets`' docstring (DS-177
    # rework2 Major fix). `line_range` is `\n`-counted by
    # `_normalized_scan`; `str.splitlines()` here would misalign
    # `lines[i]` against that line number the moment a non-`\n` line-break
    # character (form feed, U+2028, ...) appears earlier in the file -
    # this is the exact sibling-site defect `_line_start_offsets` and
    # `_check_form_c`'s `text_lines` were already fixed for in the DS-177
    # rework, and that fix's reviewer measured this site as unfixed.
    lines = text.split("\n")
    if suffix in (".yml", ".yaml"):
        ok = _check_form_a(lines, line_range)
        return (ok, "A" if ok else "NONE")
    if suffix == ".py":
        if _is_docstring_hit(text, line_range):
            return (True, "DOCUMENTATION")
        if _check_form_b(lines, line_range):
            return (True, "B")
        if _check_form_c(text, line_range):
            return (True, "C")
        return (False, "NONE")
    return (False, "NONE")


def _discover_live_sites(
    root: pathlib.Path = REPO_ROOT,
    rel_paths: list[pathlib.Path] | None = None,
) -> set[tuple[str, str]]:
    """`root`/`rel_paths` default to the real repo tree (`REPO_ROOT` /
    `_tracked_relative_paths()`) - every non-mutation call site relies on
    those defaults and is unaffected by this signature. The parameters
    exist so `test_mutation_guard_entirely_removed_reddens` can exercise
    THIS function against a real, disposable fixture file (DS-176 rework
    Critical fix: the prior version of that test asserted on two local set
    literals and never called this function at all)."""
    sites: set[tuple[str, str]] = set()
    paths = rel_paths if rel_paths is not None else _tracked_relative_paths()
    for rel in paths:
        abs_path = root / rel
        try:
            text = abs_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        matches = _normalized_scan(text)
        if not matches:
            continue
        for line_range in matches:
            if rel.suffix == ".py" and _is_docstring_hit(text, line_range):
                continue
            label = _site_label(rel.suffix, text, line_range)
            if label is not None:
                sites.add((str(rel), label))
    return sites


def test_discovery_finds_phrase_occurrences() -> None:
    """Vacuous-pass guard: if discovery finds nothing, every assertion
    below would pass trivially against an empty set."""
    sites = _discover_live_sites()
    assert sites, "phrase discovery found ZERO occurrences - discovery is broken, not clean"


def test_wrap_tolerant_scan_finds_split_occurrence() -> None:
    """DS-176 Round-2 Major 2: a single-line scan misses a wrapped
    occurrence. In-memory fixture with the phrase deliberately split
    across two lines, mirroring
    test_ticket_offer_gate_trigger_wording_spec.py:164-165's real shape."""
    fixture = (
        "def guard():\n"
        '    """Fail loudly instead - discovery is broken,\n'
        '    not clean."""\n'
        "    pass\n"
    )
    matches = _normalized_scan(fixture)
    assert matches, "wrap-tolerant scan failed to find a phrase split across two lines"
    start_line, end_line = matches[0]
    assert start_line == 2 and end_line == 3, (
        f"expected the split occurrence to span lines 2-3, got {(start_line, end_line)}"
    )


def test_live_guard_sites_bidirectional_set_equality() -> None:
    """Bidirectional set equality, not one-directional containment - a
    phantom pinned entry naming something nonexistent must also fail, not
    just an omitted real site."""
    disk_live = _discover_live_sites()
    only_on_disk = disk_live - LIVE_GUARD_SITES
    only_pinned = LIVE_GUARD_SITES - disk_live
    assert not only_on_disk, (
        f"live guard site(s) found on disk but not pinned in LIVE_GUARD_SITES: {sorted(only_on_disk)}"
    )
    assert not only_pinned, (
        "LIVE_GUARD_SITES pin(s) not found on disk (phantom entry, deleted "
        "guard, or - most likely for this file's own vacuous-pass-guard "
        "entry - this test file itself is not yet `git add`ed and so "
        "invisible to the "
        f"`git ls-files`-scoped discovery in an uncommitted checkout): {sorted(only_pinned)}"
    )


def test_bidirectional_comparison_reddens_on_phantom_pin(monkeypatch) -> None:
    """Minor 3 (DS-176 rework-2): on the real, synced tree there is no
    phantom pin, so the `only_pinned = LIVE_GUARD_SITES - disk_live` line
    inside test_live_guard_sites_bidirectional_set_equality above
    and a neutered `only_pinned = frozenset()` both report zero difference
    - nothing in the suite would catch that line being neutered. This
    injects a genuine phantom entry into LIVE_GUARD_SITES via monkeypatch,
    then calls the real production test function - which executes the
    actual subtraction against a live-computed `disk_live` - and asserts
    it raises. If that comparison is ever neutered to a constant, this
    test's own `pytest.fail` below fires instead of the expected
    AssertionError, reddening the suite."""
    phantom = ("bin/tests/this-file-does-not-exist.py", "nonexistent_guard")
    monkeypatch.setattr(
        sys.modules[__name__], "LIVE_GUARD_SITES", LIVE_GUARD_SITES | {phantom}
    )
    try:
        test_live_guard_sites_bidirectional_set_equality()
    except AssertionError:
        pass
    else:
        pytest.fail(
            "expected test_live_guard_sites_bidirectional_set_equality to "
            "raise AssertionError on a phantom LIVE_GUARD_SITES entry, but "
            "it passed - the only_pinned comparison is not discriminating"
        )


def test_bidirectional_comparison_reddens_on_unpinned_disk_site(monkeypatch) -> None:
    """DS-177 rework Minor 2 regression test - mirror direction of
    test_bidirectional_comparison_reddens_on_phantom_pin above. `only_on_disk
    = disk_live - LIVE_GUARD_SITES` catches an unpinned real site; a
    neutered `only_on_disk = frozenset()` would report zero difference no
    matter what disk contains, and nothing else in the suite would catch
    it. This injects a genuine extra site into the LIVE result via
    monkeypatching `_discover_live_sites` (never a hardcoded stub), then
    calls the real production test function - which executes the actual
    `disk_live - LIVE_GUARD_SITES` subtraction against that live-computed
    set - and asserts it raises."""
    extra_site = ("bin/tests/this-file-does-not-exist.py", "phantom_disk_guard")
    real_discover_live_sites = _discover_live_sites

    def _discover_with_extra_site(*args, **kwargs):
        return real_discover_live_sites(*args, **kwargs) | {extra_site}

    monkeypatch.setattr(
        sys.modules[__name__], "_discover_live_sites", _discover_with_extra_site
    )
    try:
        test_live_guard_sites_bidirectional_set_equality()
    except AssertionError:
        pass
    else:
        pytest.fail(
            "expected test_live_guard_sites_bidirectional_set_equality to "
            "raise AssertionError on an unpinned disk-only site, but it "
            "passed - the only_on_disk comparison is not discriminating "
            "(e.g. neutered to a hardcoded `frozenset()`)"
        )


def test_each_live_guard_conforms_to_mandated_form() -> None:
    failures = []
    for rel_str, label in sorted(LIVE_GUARD_SITES):
        rel = pathlib.Path(rel_str)
        abs_path = REPO_ROOT / rel
        text = abs_path.read_text(encoding="utf-8")
        matches = _normalized_scan(text)
        site_matches = [
            m
            for m in matches
            if _site_label(rel.suffix, text, m) == label
            and not (rel.suffix == ".py" and _is_docstring_hit(text, m))
        ]
        assert site_matches, f"could not re-locate site {rel_str}/{label} for form check"
        ok, form = _conforms_to_mandated_form(rel.suffix, text, site_matches[0])
        if not ok:
            failures.append(f"{rel_str}/{label}: does not conform to a mandated form ({form})")
    assert not failures, "\n".join(failures)


def test_own_vacuous_pass_guard_conforms_to_form_c() -> None:
    """Proves this file's own guard (test_discovery_finds_phrase_occurrences)
    conforms to Form C."""
    this_file = pathlib.Path(__file__).resolve()
    rel = this_file.relative_to(REPO_ROOT)
    text = this_file.read_text(encoding="utf-8")
    matches = [
        m
        for m in _normalized_scan(text)
        if _site_label(rel.suffix, text, m) == "test_discovery_finds_phrase_occurrences"
        and not _is_docstring_hit(text, m)
    ]
    assert matches, "could not locate this file's own guard site"
    ok, form = _conforms_to_mandated_form(rel.suffix, text, matches[0])
    assert ok and form == "C", f"expected this file's own guard to conform to Form C, got ({ok}, {form})"


def test_form_c_rejects_log_only_guard_with_unrelated_adjacent_assert() -> None:
    """DS-176 rework Major fix regression test. Proven live on
    hooks/tests/test-hooks-pep604-guard.py: replacing its `hook_files`
    guard with a bare `print(...)` (no stderr, no exit) left an unrelated
    `assert True` two lines away, and the old `\\bassert\\b` proximity
    regex classified it as conforming Form C anyway. The assert must
    CARRY the phrase and BE the failure mechanism, not merely sit nearby."""
    fixture = (
        "def check_files(hook_files):\n"
        f'    print("ERROR: zero matched - {GUARD_PHRASE}")\n'
        "    assert True\n"
    )
    matches = _normalized_scan(fixture)
    assert matches
    ok, form = _conforms_to_mandated_form(".py", fixture, matches[0])
    assert not ok, (
        f"log-only guard with an unrelated adjacent assert should NOT conform, got ({ok}, {form})"
    )


def test_form_c_rejects_same_line_print_and_unrelated_assert() -> None:
    """DS-176 rework-2 Major fix regression test. `_check_form_c` used to
    be interval-OVERLAP on the whole assert statement's line span - a
    ONE-LINER `print("...phrase"); assert True` puts the phrase hit and
    the unrelated assert on the SAME line, which line-granular overlap
    admits regardless. Must NOT conform: `assert True` carries no message
    at all, let alone the phrase."""
    fixture = (
        "def check_files(hook_files):\n"
        f'    print("ERROR: zero matched - {GUARD_PHRASE}"); assert True\n'
    )
    matches = _normalized_scan(fixture)
    assert matches
    ok, form = _conforms_to_mandated_form(".py", fixture, matches[0])
    assert not ok, (
        f"same-line print+unrelated-assert should NOT conform, got ({ok}, {form})"
    )


def test_form_c_rejects_phrase_in_assert_condition_not_message() -> None:
    """DS-176 rework-2 Major fix regression test. A phrase living in the
    assert's CONDITION rather than its MESSAGE is not a zero-discovery
    guard at all - `assert "<phrase>" not in out, "unexpected"` fails with
    the message "unexpected", which says nothing about discovery being
    broken. Must NOT conform."""
    fixture = (
        "def check_output(out):\n"
        f'    assert "{GUARD_PHRASE}" not in out, "unexpected"\n'
    )
    matches = _normalized_scan(fixture)
    assert matches
    ok, form = _conforms_to_mandated_form(".py", fixture, matches[0])
    assert not ok, (
        f"phrase-in-condition (not message) should NOT conform, got ({ok}, {form})"
    )


def test_form_c_accepts_assert_that_itself_carries_the_phrase() -> None:
    """Positive companion to the test above: a real
    `assert <expr>, "<msg with phrase>"` statement, where the assert IS
    the failure mechanism, must still classify as Form C."""
    fixture = (
        "def check_files(hook_files):\n"
        f'    assert hook_files, "zero matched - {GUARD_PHRASE}"\n'
    )
    matches = _normalized_scan(fixture)
    assert matches
    ok, form = _conforms_to_mandated_form(".py", fixture, matches[0])
    assert ok and form == "C", f"expected Form C, got ({ok}, {form})"


def test_form_c_accepts_phrase_in_both_condition_and_message() -> None:
    """DS-177 Fix 1 regression test. `_check_form_c` used to re-locate the
    phrase hit's character-offset span by BREAKing on the first
    `line_range` match it found. When the phrase appears in BOTH the
    assert's CONDITION and its MESSAGE on one line
    (`assert "<phrase>" in out, "bad - <phrase>"`), both occurrences share
    the same (start_line, end_line), and the leftmost (condition) offset
    won the break - so a genuinely conforming guard (the message DOES
    carry the phrase) was rejected. Must conform: at least one of the two
    same-line-range hits (the message one) falls inside `node.msg`'s
    span."""
    fixture = (
        "def check_output(out):\n"
        f'    assert "{GUARD_PHRASE}" in out, "bad - {GUARD_PHRASE}"\n'
    )
    matches = _normalized_scan(fixture)
    assert len(matches) == 2, f"expected 2 same-line-range hits, got {matches}"
    ok, form = _conforms_to_mandated_form(".py", fixture, matches[0])
    assert ok and form == "C", (
        f"phrase present in the message (as well as the condition) should "
        f"still conform via the message occurrence, got ({ok}, {form})"
    )


def test_form_c_multibyte_characters_before_message_do_not_misalign() -> None:
    """DS-177 Fix 2 regression test. `ast` node `col_offset`/
    `end_col_offset` are UTF-8 BYTE offsets, while `_line_start_offsets`
    and `_normalized_scan_positions` both count CHARACTERS; comparing them
    directly shifted the comparison by one position per multi-byte
    character preceding the assert's message on the same line. 20 CJK
    characters (3 bytes each in UTF-8, so +2 bytes per character over a
    naive 1-byte-per-char assumption = 40 bytes of drift) in the
    condition, immediately before a message that IS just the phrase, push
    the mis-derived message-start offset past the phrase's true end
    offset - reddening a genuinely conforming guard. (A non-em-dash
    multi-byte character is used deliberately; this repo bans authored
    em dashes and the point under test is multi-byte width, not the exact
    character.)"""
    multibyte_padding = "日" * 20  # CJK "day/sun" character, 3 UTF-8 bytes
    fixture = (
        "def check_files(hook_files):\n"
        f'    assert hook_files == "{multibyte_padding}", "{GUARD_PHRASE}"\n'
    )
    matches = _normalized_scan(fixture)
    assert matches
    ok, form = _conforms_to_mandated_form(".py", fixture, matches[0])
    assert ok and form == "C", (
        f"multi-byte padding earlier on the line should not affect Form C "
        f"classification, got ({ok}, {form})"
    )


def test_form_c_rejects_hit_straddling_condition_message_boundary() -> None:
    """DS-177 Fix 3 regression test. `_check_form_c` used to test interval
    OVERLAP between the phrase hit and `node.msg`'s span, not containment,
    despite its own docstring promising containment ("fall inside"). A
    phrase hit that STRADDLES the test/msg comma boundary -
    `assert discovery is broken, not clean` has `node.test` = `discovery
    is broken` and `node.msg` = `not clean`, and the phrase spans both -
    overlapped `node.msg`'s span without being contained in it, and the
    old overlap check wrongly accepted it. Must NOT conform: the assert's
    message here is `not clean`, which says nothing about discovery being
    broken."""
    fixture = (
        "def check():\n"
        f"    assert {GUARD_PHRASE}\n"
    )
    matches = _normalized_scan(fixture)
    assert matches
    ok, form = _conforms_to_mandated_form(".py", fixture, matches[0])
    assert not ok, (
        f"a phrase hit straddling the assert's test/msg boundary should "
        f"NOT conform (the message alone does not carry the phrase), got "
        f"({ok}, {form})"
    )


def test_form_c_form_feed_does_not_misalign_offsets() -> None:
    """DS-177 rework Minor 1 regression test. `_line_start_offsets` and
    `_check_form_c`'s `text_lines` used to split on `str.splitlines()`'s
    broader break set (form feed `\\x0c` among them), which CPython's
    tokenizer - and therefore AST `lineno` - does NOT treat as a line
    boundary. A form feed appearing on an earlier physical line inserts an
    extra phantom "line" into the `splitlines()`-derived list/offset
    array, so `text_lines[msg.lineno - 1]` (indexed by the true, `\\n`-only
    AST line number) grabs the WRONG line's content and the resulting
    character-offset comparison misses - misclassifying a genuinely
    conforming guard as non-conforming. Fixture: a form feed sits inside a
    string literal on the line BEFORE the assert, so `str.splitlines()`
    over-splits by one entry ahead of the assert's own (`\\n`-only) AST
    line number. Confirmed failing pre-fix against the parent commit's
    module (returned `(False, 'NONE')`); this fixture must classify Form
    C."""
    fixture = (
        "def check_files(hook_files):\n"
        '    marker = "a\x0cb"\n'
        f'    assert hook_files, "{GUARD_PHRASE}"\n'
    )
    matches = _normalized_scan(fixture)
    assert matches
    ok, form = _conforms_to_mandated_form(".py", fixture, matches[0])
    assert ok and form == "C", (
        f"a form feed on an earlier line should not misalign line "
        f"numbering and cause a conforming guard to misclassify, got "
        f"({ok}, {form})"
    )


def test_form_a_form_feed_does_not_misalign_offsets() -> None:
    """DS-177 rework2 Major regression test, mirroring
    test_form_c_form_feed_does_not_misalign_offsets above. The declined
    sibling site: `_conforms_to_mandated_form` used to split on
    `str.splitlines()`'s broader break set (form feed among them) before
    handing `lines` to `_check_form_a`, so a form feed on an earlier
    physical line inserted a phantom extra "line" into the list -
    misaligning the `>&2`/`exit 1` window against the `\\n`-only
    `line_range` `_normalized_scan` produces, and misclassifying a
    genuinely conforming Form A guard as non-conforming. Confirmed failing
    pre-fix against the parent commit's module (returned `(False,
    'NONE')`); this fixture must classify Form A."""
    fixture = (
        'echo "a\x0cb"\n'
        f'echo "ERROR: zero matched - {GUARD_PHRASE}" >&2\n'
        "exit 1\n"
    )
    matches = _normalized_scan(fixture)
    assert matches
    ok, form = _conforms_to_mandated_form(".yml", fixture, matches[0])
    assert ok and form == "A", (
        f"a form feed on an earlier line should not misalign line "
        f"numbering and cause a conforming Form A guard to misclassify, "
        f"got ({ok}, {form})"
    )


def test_site_label_python_form_feed_does_not_misalign() -> None:
    """DS-177 rework3 Major regression test. `_site_label_python`'s
    module-level fallback branch (`if not <ident>:` guard scan) used to
    split on `str.splitlines()`'s broader break set before this rework's
    `text.split("\\n")` fix (:305) - the same sibling-site defect class
    `_line_start_offsets`, `_check_form_c`'s `text_lines`, and
    `_conforms_to_mandated_form`'s `lines` were already fixed for. Fixture:
    two form feeds earlier in the file insert two phantom
    `splitlines()`-only entries, misaligning the reverse index scan so it
    lands on `DECOY1`'s guard line instead of the nearer, correct
    `RIGHT_IDENT` guard - both `if not <ident>:` lines exist so a reverted
    site returns a WRONG label, not merely a missing one. Confirmed RED
    against a reverted (`splitlines()`) site during this rework: returned
    'DECOY1' instead of 'RIGHT_IDENT'."""
    fixture = (
        "x = 1\x0c\n"
        "y = 2\x0c\n"
        "if not DECOY1:\n"
        "    pass\n"
        "if not RIGHT_IDENT:\n"
        f'    print("ERROR - {GUARD_PHRASE}")\n'
    )
    matches = _normalized_scan(fixture)
    assert matches
    label = _site_label_python(fixture, matches[0])
    assert label == "RIGHT_IDENT", (
        f"a form feed earlier in the file should not misalign the reverse "
        f"`if not <ident>:` scan and cause it to return the wrong guard's "
        f"identifier, got {label!r}"
    )


def test_site_label_yaml_form_feed_does_not_misalign() -> None:
    """DS-177 rework3 Major regression test, mirroring
    test_site_label_python_form_feed_does_not_misalign above. `_site_label`'s
    yaml branch (:323) used to split on `str.splitlines()`'s broader break
    set before this rework's `text.split("\\n")` fix - the same
    sibling-site defect class. Fixture: two form feeds packed into one
    line earlier in the file insert two phantom `splitlines()`-only
    entries, misaligning the reverse upward job-name scan so it lands on
    the decoy job `decoy1` instead of the nearer, correct job `right-job` -
    both job-name lines exist so a reverted site returns a WRONG label,
    not merely a missing one. Confirmed RED against a reverted
    (`splitlines()`) site during this rework: returned 'decoy1' instead of
    'right-job'."""
    fixture = (
        "jobs:\n"
        "  filler-job:\n"
        "    steps:\n"
        "      - run: ff\x0c\x0cend\n"
        "    more: stuff\n"
        "  decoy1:\n"
        "  right-job:\n"
        f'      - run: echo "ERROR - {GUARD_PHRASE}" >&2; exit 1\n'
    )
    matches = _normalized_scan(fixture)
    assert matches
    label = _site_label(".yml", fixture, matches[0])
    assert label == "right-job", (
        f"a form feed earlier in the file should not misalign the reverse "
        f"job-name scan and cause it to return the wrong job's name, got "
        f"{label!r}"
    )


def test_form_a_rejects_stdout_only_with_exit() -> None:
    """DS-177 rework Minor 2 regression test. `_check_form_a`'s `>&2`
    check can be silently deleted, leaving only the `exit 1` search, and
    nothing in the suite would catch it. A guard that logs to STDOUT
    (no `>&2`) and then exits is not the mandated Form A shape - the
    message must be stderr-directed - and must NOT conform."""
    fixture = f'echo "ERROR: zero matched - {GUARD_PHRASE}"\nexit 1\n'
    matches = _normalized_scan(fixture)
    assert matches
    ok, form = _conforms_to_mandated_form(".yml", fixture, matches[0])
    assert not ok, (
        f"stdout-only (no >&2) message followed by exit 1 should NOT "
        f"conform, got ({ok}, {form})"
    )


def test_form_b_rejects_stderr_write_without_exit() -> None:
    """DS-177 rework Minor 2 regression test. `_check_form_b`'s
    `sys.exit(1)`/`raise SystemExit` check can be silently neutered to
    `return True`, and nothing in the suite would catch it. A Form B
    guard that writes to stderr but never exits is the classic
    'log but don't fail' vacuous-pass shape and must NOT conform."""
    fixture = (
        "def check_files(hook_files):\n"
        f'    print("ERROR: zero matched - {GUARD_PHRASE}", file=sys.stderr)\n'
        "    pass\n"
    )
    matches = _normalized_scan(fixture)
    assert matches
    ok, form = _conforms_to_mandated_form(".py", fixture, matches[0])
    assert not ok, (
        f"stderr write without sys.exit(1)/raise SystemExit should NOT "
        f"conform, got ({ok}, {form})"
    )


def test_form_b_rejects_stdout_only_with_exit() -> None:
    """DS-177 rework2 Minor 1 regression test, mirroring
    test_form_a_rejects_stdout_only_with_exit above. `_check_form_b`'s
    stderr-direction check (`"file=sys.stderr" not in joined_nearby and
    "sys.stderr.write" not in joined_nearby`) can be silently deleted,
    leaving only the `sys.exit(1)`/`raise SystemExit` search - and, unlike
    Form A (which already had both halves guarded), nothing in the suite
    caught it: all pre-existing tests still passed with that check
    removed. A guard that logs to STDOUT (no stderr direction) and then
    exits is not the mandated Form B shape - the message must be
    stderr-directed - and must NOT conform."""
    fixture = (
        "def check_files(hook_files):\n"
        f'    print("ERROR: zero matched - {GUARD_PHRASE}")\n'
        "    sys.exit(1)\n"
    )
    matches = _normalized_scan(fixture)
    assert matches
    ok, form = _conforms_to_mandated_form(".py", fixture, matches[0])
    assert not ok, (
        f"stdout-only (no stderr direction) message followed by "
        f"sys.exit(1) should NOT conform, got ({ok}, {form})"
    )


def test_mutation_weakened_to_log_only_reddens() -> None:
    """AC-4 variant 1: delete only the failure statement (exit 1), leaving
    the log line - the classic 'we log but don't fail' vacuous-pass shape.
    In-memory fixture only."""
    fixture = (
        f'echo "ERROR: glob matched zero runnable files - {GUARD_PHRASE}" >&2\n'
        "echo done\n"
    )
    matches = _normalized_scan(fixture)
    assert matches
    ok, form = _conforms_to_mandated_form(".yml", fixture, matches[0])
    assert not ok, f"weakened (no exit 1) guard should NOT conform, got ({ok}, {form})"


def test_mutation_guard_entirely_removed_reddens(tmp_path: pathlib.Path) -> None:
    """AC-4 variant 2: delete the whole guard block - the phrase (and thus
    the site) simply vanishes from disk. DS-176 rework Critical fix: the
    prior version of this test built `phantom_pin - fixture_sites` from
    two LOCAL LITERALS - pure set arithmetic that referenced no module
    symbol and exercised no code path (proven vacuous by gutting
    `_discover_live_sites()` to `return set()`: four other tests failed
    and this one still passed). This version writes a REAL fixture file to
    a disposable `tmp_path`, calls the ACTUAL `_discover_live_sites()`
    against it before and after the guard block is deleted, and asserts
    the real discovery+comparison path reports the phantom - exactly the
    logic `test_live_guard_sites_bidirectional_set_equality` runs against
    the tracked tree."""
    fixture_rel = pathlib.Path("fixture-guard.yml")
    fixture_path = tmp_path / fixture_rel
    fixture_path.write_text(
        "jobs:\n"
        "  some-job:\n"
        "    steps:\n"
        f'      - run: echo "ERROR: zero matched - {GUARD_PHRASE}" >&2; exit 1\n'
    )

    before = _discover_live_sites(root=tmp_path, rel_paths=[fixture_rel])
    assert ("fixture-guard.yml", "some-job") in before, (
        "setup sanity check failed: the real _discover_live_sites() did "
        f"not discover the fixture guard before removal, got {sorted(before)}"
    )

    # Mutate on disk: delete the whole guard block, mirroring a real
    # accidental deletion - the phrase (and thus the site) vanishes.
    fixture_path.write_text(
        "jobs:\n"
        "  some-job:\n"
        "    steps:\n"
        "      - run: echo done\n"
    )

    after = _discover_live_sites(root=tmp_path, rel_paths=[fixture_rel])
    phantom_pin = frozenset({("fixture-guard.yml", "some-job")})
    only_pinned = phantom_pin - after
    assert only_pinned, (
        "guard removal not detected: the real _discover_live_sites() "
        f"still reports the removed site as present, got {sorted(after)}"
    )


def test_docstring_reference_not_flagged_as_violation() -> None:
    """test_ticket_offer_gate_trigger_wording_spec.py:36 (module docstring)
    and :164-165 (function docstring) both classify as DOCUMENTATION
    (AST-confirmed), not NON-CONFORMING. DS-177 rework2 Minor 2 fix:
    exact equality, not a `>= 2` lower bound - a lower bound stays green
    if a third occurrence appears on disk, silently going stale exactly
    like the word-form-cardinal class this fix closes in the module
    docstring above. DS-177 rework3 Minor fix: compares against
    DOCSTRING_REFERENCE_COUNT, the same module constant this file's own
    docstring prose is pinned against by
    test_module_docstring_cites_current_reference_count below - not an
    independent hand-typed `2` literal."""
    target = REPO_ROOT / "bin" / "tests" / "test_ticket_offer_gate_trigger_wording_spec.py"
    text = target.read_text(encoding="utf-8")
    matches = _normalized_scan(text)
    assert len(matches) == DOCSTRING_REFERENCE_COUNT, (
        f"expected exactly {DOCSTRING_REFERENCE_COUNT} phrase occurrences in "
        f"{target}, found {len(matches)} - re-derive the module docstring's "
        "False-positive reasoning citation if this count has changed"
    )
    for line_range in matches:
        assert _is_docstring_hit(text, line_range), (
            f"{target}:{line_range} expected to classify as a docstring hit "
            "(prose reference), but AST did not confirm it"
        )
        ok, form = _conforms_to_mandated_form(".py", text, line_range)
        assert ok and form == "DOCUMENTATION", (
            f"{target}:{line_range} expected DOCUMENTATION classification, got ({ok}, {form})"
        )


def test_module_docstring_cites_current_reference_count() -> None:
    """DS-177 rework3 Minor regression test. Proves the coupling between
    DOCSTRING_REFERENCE_COUNT and this module's own docstring prose
    ("The exact count (currently 2) is asserted with `==`..."): asserts
    the docstring literally embeds the constant's live value. If the
    constant is ever changed without updating the prose (or vice versa),
    this test reddens instead of the two hand-typed copies silently
    diverging - the exact class Minor 3 (DS-176 rework-2) and the word-
    form-cardinal class closed above (test_docstring_reference_not_
    flagged_as_violation's own docstring, three paragraphs up) already
    describe for other counts in this file."""
    assert __doc__ is not None
    needle = f"currently {DOCSTRING_REFERENCE_COUNT}"
    assert needle in __doc__, (
        f"module docstring does not contain {needle!r} - DOCSTRING_REFERENCE_COUNT "
        f"is {DOCSTRING_REFERENCE_COUNT} but the docstring prose was not updated "
        "to match (or the constant was changed without updating the prose)"
    )


_FIELD_HEADER_RE = re.compile(r"^([A-Z][\w \-]*):", re.MULTILINE)

# Matches ONLY the contiguous, comma/and-joined run of backtick-quoted
# `_`-prefixed names that sits immediately before the "are internal
# helpers" clause - i.e. the enumerated list itself, not the surrounding
# rationale prose in the same field. DS-177 rework5 Minor 1 fix: the prior
# version slurped the whole `Public API:` field with a bare
# `` `(_name)` `` findall, so a name mentioned only in passing in the
# rationale (e.g. "as discussed for `_site_label_python` above") counted
# as declared even if it had been removed from the actual list - a false
# negative demonstrated by deleting a name from the list while adding one
# rationale mention of it in the same field, which left the pin GREEN.
# Anchoring on "are\b" is what makes this narrower than the field slice:
# the enumeration is always immediately followed by "are internal
# helpers" in this module's docstring convention (see the sentence this
# regex targets), so nothing after that word can be mistaken for a list
# member no matter how many more `_name` backticks appear later in the
# same field's rationale.
_PUBLIC_API_LIST_RE = re.compile(
    r"((?:(?:and\s+)?`_[A-Za-z0-9_]+`,\s*)*(?:and\s+)?`_[A-Za-z0-9_]+`)\s+are\b"
)


def _manifest_public_api_names() -> frozenset[str]:
    """Parse THIS module's own docstring's `Public API:` field and return
    every backtick-quoted `_`-prefixed name in its enumerated LIST -
    specifically the comma/and-joined run of names that sits directly
    before "are internal helpers", located by `_PUBLIC_API_LIST_RE` - not
    every backtick-quoted name anywhere in the field's text. A name
    mentioned only in the field's rationale prose (outside that list) does
    NOT count as declared. Field boundaries are located structurally (the
    next unindented `Header:` line, matching the module docstring's own
    field layout - see the raw-line audit in this ticket's rework), not by
    a hand-typed line range, so a later field reorder or insertion does
    not silently widen or narrow the slice fed to the list regex."""
    assert __doc__ is not None
    headers = list(_FIELD_HEADER_RE.finditer(__doc__))
    start = next(m for m in headers if m.group(1) == "Public API")
    later = [m for m in headers if m.start() > start.start()]
    end = later[0].start() if later else len(__doc__)
    field_text = __doc__[start.start():end]
    list_match = _PUBLIC_API_LIST_RE.search(field_text)
    assert list_match is not None, (
        "could not locate the enumerated name list (the backtick-name run "
        "immediately preceding 'are internal helpers') inside this "
        "module's docstring 'Public API:' field - the field's prose no "
        "longer matches the expected list-then-'are' shape; fix the "
        "docstring or `_PUBLIC_API_LIST_RE` before trusting this pin"
    )
    return frozenset(re.findall(r"`(_[A-Za-z0-9_]+)`", list_match.group(1)))


def _ast_derived_helper_call_set() -> frozenset[str]:
    """Walk THIS module's own source (read from disk, not `__doc__` or an
    in-memory copy) and collect every `_`-prefixed module-level function
    that is called DIRECTLY (by bare name, not via an attribute or an
    indirect reference) from inside a `test_*` function body. This is the
    exact method the module docstring's `Public API:` field claims to be
    pinned against."""
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    helper_defs = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_")
    }
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id in helper_defs
                ):
                    called.add(sub.func.id)
    return frozenset(called)


def test_manifest_public_api_matches_ast_derived_call_set() -> None:
    """DS-177 rework4 Major regression test. The module docstring's
    `Public API:` list has now been hand-reconciled twice (DS-177 Fix 5;
    then again to add `_is_docstring_hit`) and regressed once
    (`_site_label_python` was added to
    `test_site_label_python_form_feed_does_not_misalign` in rework3
    without a matching manifest update, and nothing caught it - AC-5
    passed at the prior commit and silently failed at this one). A third
    hand-reconciliation is not a fix, so this test derives BOTH sides from
    source - the manifest sentence itself (`_manifest_public_api_names`,
    parsed from `__doc__`, not a duplicate hand-typed constant) and the
    real AST call graph (`_ast_derived_helper_call_set`) - and asserts
    BIDIRECTIONAL set equality, not containment: an omission (a helper
    called by a test but missing from the manifest) and a phantom entry
    (a manifest name no test actually calls, e.g. pointing at a renamed
    or deleted helper) are both defects, and containment-only would catch
    only the first."""
    manifest = _manifest_public_api_names()
    derived = _ast_derived_helper_call_set()
    missing_from_manifest = derived - manifest
    phantom_in_manifest = manifest - derived
    assert not missing_from_manifest and not phantom_in_manifest, (
        "module docstring 'Public API:' list is out of sync with the "
        "AST-derived set of `_`-prefixed helpers called directly from "
        f"test_* functions - missing from manifest: {sorted(missing_from_manifest)}; "
        f"phantom in manifest (no test calls this name): {sorted(phantom_in_manifest)}"
    )


def test_nested_local_helper_does_not_pressure_manifest_pin() -> None:
    """DS-177 rework5 Minor 2 regression test. Defines and calls a purely
    local, NESTED `_`-prefixed helper (not module-level) to prove
    `_ast_derived_helper_call_set`'s `helper_defs` set is built from
    `tree.body` (module-level defs only), not `ast.walk(tree)` (which
    would also pick up nested defs). Before this fix, `ast.walk` pulled
    `_helper` into `helper_defs`, and this test's own call to it made it
    show up as "missing from manifest" in
    `test_manifest_public_api_matches_ast_derived_call_set` - pressuring
    an author to add a non-API local name to the docstring `Public API:`
    field to silence a false positive, which would have made that field
    false. Confirmed failing pre-fix by temporarily reverting the
    `tree.body` change back to `ast.walk(tree)`."""

    def _helper() -> int:
        return 1

    assert _helper() == 1
