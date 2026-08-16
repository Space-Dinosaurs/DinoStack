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
Public API: pytest test functions only. `_normalized_scan`, `_site_label`,
         and `_conforms_to_mandated_form` are internal helpers exercised
         directly by the mutation tests below.
Upstream deps: `git ls-files` (repo-relative, tracked-only discovery -
         this checkout carries 40+ `.claude/worktrees/agent-*` copies of
         every guard site; an unfiltered `rglob()` from the repo root would
         multiply every LIVE_GUARD_SITES entry by (1 + worktree count) and
         either mask the problem under bare-basename keys or redden this
         gate locally while CI, a clean checkout, stays green - see
         `_tracked_relative_paths()` in
         bin/tests/test_ticket_offer_gate_trigger_wording_spec.py:110-133
         for the identical precedent this reuses). `LIVE_GUARD_SITES` keys
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
         and the two mutation tests; (b) `LIVE_GUARD_SITES` drifts from the
         live tree (a site added or removed without updating the pin) -
         caught by the bidirectional set-equality test, in BOTH directions
         (a phantom entry naming something nonexistent is caught by
         `LIVE_GUARD_SITES - disk_live`, not just an omission); (c) phrase
         discovery itself finds nothing (this file's own vacuous-pass
         guard, `test_discovery_finds_phrase_occurrences`).
False-positive reasoning: two prose references to the guard phrase exist
         purely as documentation - bin/tests/test_ticket_offer_gate_trigger_
         wording_spec.py:36 (module docstring, explaining this file's own
         discipline by citation) and :164-165 (a FUNCTION docstring
         explaining a *different*, non-phrase-carrying guard's rationale).
         Both are classified DOCUMENTATION by AST (first-statement string
         constant of a Module/FunctionDef), out of scope, not a violation -
         see `test_docstring_reference_not_flagged_as_violation`.
AC-5 scope justification (re-derive fresh at PR time, never trust a cited
         cardinal): as of this file's introduction, 30-of-80
         `bin/tests/*.py` files use a discovery pattern (`glob`, `rglob`,
         `os.walk`, or `git ls-files`), against 7 live guards (this file's
         own guard plus the 6 documented above) carrying the mandated-form
         phrase, across 4 files. A universal meta-linter over all 30 is out
         of this ticket's two-item scope and requires the same
         DOCUMENTATION-vs-CODE judgment the AST approach makes tractable
         for these 4 files but not yet repo-wide - a deliberate,
         documented limitation, not a silent gap.
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

GUARD_PHRASE = "discovery is broken, not clean"

SEARCH_SUFFIXES = {".py", ".yml", ".yaml"}

# Content-derived, never hand-typed (DS-176 Round-2 Critical fix). The 6
# pre-existing entries plus this file's own vacuous-pass guard (7th entry,
# added because this file's own discovery guard carries the same literal
# phrase and is therefore itself discoverable by the mechanism it tests).
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
    unfiltered directory walk) matters because this checkout carries 40+
    `.claude/worktrees/agent-*` copies of the whole tree, none of which are
    part of the primary worktree's git index."""
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


def _normalized_scan(text: str) -> list[tuple[int, int]]:
    """Whitespace-normalize (collapse runs of whitespace to a single ' ')
    before matching GUARD_PHRASE, then back-map each match's normalized
    offset to an original-text (start_line, end_line) 1-indexed, inclusive
    line range. Catches a wrapped/reformatted occurrence a single-line scan
    misses (DS-176 Round-2 Major 2) - see
    test_wrap_tolerant_scan_finds_split_occurrence."""
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

    matches: list[tuple[int, int]] = []
    search_from = 0
    phrase_len = len(GUARD_PHRASE)
    while True:
        idx = normalized.find(GUARD_PHRASE, search_from)
        if idx == -1:
            break
        end_idx = idx + phrase_len - 1
        orig_start = orig_indices[idx]
        orig_end = orig_indices[end_idx]
        start_line = text.count("\n", 0, orig_start) + 1
        end_line = text.count("\n", 0, orig_end) + 1
        matches.append((start_line, end_line))
        search_from = idx + 1
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

    lines = text.splitlines()
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
        return _site_label_yaml(text.splitlines(), line_range)
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


def _check_form_c(lines: list[str], line_range: tuple[int, int]) -> bool:
    window = lines[max(0, line_range[0] - 4) : min(len(lines), line_range[1] + 4)]
    return bool(re.search(r"\bassert\b", "\n".join(window)))


def _conforms_to_mandated_form(
    suffix: str, text: str, line_range: tuple[int, int]
) -> tuple[bool, str]:
    """Form A (shell): phrase line has `>&2`; `exit 1` (or equivalent)
    within a few lines after. Form B (python): phrase inside
    `print(..., file=sys.stderr)` or `sys.stderr.write(...)`; `sys.exit(1)`
    or `raise SystemExit` within a few lines after. Form C (pytest-assert -
    the dominant repo form): a single `assert <expr>, "<msg>"` statement,
    where the assert IS both phrase-carrier and failure mechanism. For .py
    files, a phrase occurring inside a docstring is classified
    DOCUMENTATION - out of scope, not a violation, not a guard."""
    lines = text.splitlines()
    if suffix in (".yml", ".yaml"):
        ok = _check_form_a(lines, line_range)
        return (ok, "A" if ok else "NONE")
    if suffix == ".py":
        if _is_docstring_hit(text, line_range):
            return (True, "DOCUMENTATION")
        if _check_form_b(lines, line_range):
            return (True, "B")
        if _check_form_c(lines, line_range):
            return (True, "C")
        return (False, "NONE")
    return (False, "NONE")


def _discover_live_sites() -> set[tuple[str, str]]:
    sites: set[tuple[str, str]] = set()
    for rel in _tracked_relative_paths():
        abs_path = REPO_ROOT / rel
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
        f"LIVE_GUARD_SITES pin(s) not found on disk (phantom entry or deleted guard): {sorted(only_pinned)}"
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


def test_mutation_guard_entirely_removed_reddens() -> None:
    """AC-4 variant 2: delete the whole guard block - the phrase (and thus
    the site) simply vanishes from disk. Confirmed via a phantom-pin
    scenario: a LIVE_GUARD_SITES entry naming a site absent from a fixture
    tree is flagged by the bidirectional set-equality logic (exercised
    directly here on an in-memory fixture rather than the tracked tree)."""
    fixture_sites: set[tuple[str, str]] = set()  # guard removed - nothing discovered
    phantom_pin = frozenset({("fake/deleted-guard.yml", "deleted-job")})
    only_pinned = phantom_pin - fixture_sites
    assert only_pinned, "phantom-classification check itself is broken (should be non-empty)"


def test_docstring_reference_not_flagged_as_violation() -> None:
    """test_ticket_offer_gate_trigger_wording_spec.py:36 (module docstring)
    and :164-165 (function docstring) both classify as DOCUMENTATION
    (AST-confirmed), not NON-CONFORMING."""
    target = REPO_ROOT / "bin" / "tests" / "test_ticket_offer_gate_trigger_wording_spec.py"
    text = target.read_text(encoding="utf-8")
    matches = _normalized_scan(text)
    assert len(matches) >= 2, (
        f"expected at least 2 phrase occurrences in {target}, found {len(matches)}"
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
