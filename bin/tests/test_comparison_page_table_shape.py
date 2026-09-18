"""Module manifest.

Purpose: regression test (DS-240) pinning the structural shape of the three
comparison tables in `docs/agentic-engineering-comparison.html` - every
table's <thead> must declare the same number of `<th scope="col">` columns
(N), every <tbody> row must have exactly N-1 `<td>` cells (the first column
is a `<th scope="row">` label, not a `<td>`), and the standalone `table { }`
CSS rule's `min-width` must equal `240 + 200 * (N - 1)`. Nothing before this
file checked this mechanically; a column addition could ship with the
min-width formula miscounted and only be caught by manual Skeptic review
(the pre-DS-239 state at af733e43^ shipped exactly this stale-comment
defect - see the ticket/plan for detail).

Public API: `extract_table_html`, `col_count`, `body_row_td_counts`,
`table_rule_min_width`, `shape_violations` (pure functions operating on
in-memory HTML text, no fixture files) plus pytest test functions.

Failure modes: `table_rule_min_width`'s CSS-rule regex is anchored to a line
that starts with `table {` (only whitespace before `table`) - it will not
match if the stylesheet is ever reformatted so the `table` selector no
longer opens its own rule at line-start (e.g. reflowed onto one line, or
changed to a `.table-scroll table { ... }` compound selector as the page's
own prose loosely implies elsewhere). That is a known, accepted coupling:
if the CSS selector shape changes, this test's helper must be re-pointed in
the same PR as that CSS change. `col_count` and `body_row_td_counts` raise
neither on a genuinely malformed table: `extract_table_html` raises
AssertionError if a table cannot be located at all, but a missing
`<thead>`/`<tbody>` tag inside an otherwise-located table degrades to a
named violation string via `shape_violations` rather than raising (see
`test_missing_thead_or_tbody_reports_named_violation` below).

Retirement condition: delete this file (not merely skip it) if the three
tables are ever intentionally redesigned to no longer share a uniform
column count across all three - short of that, this is a permanent
enforcement floor on a hand-maintained public HTML artifact with a
demonstrated recurring defect class.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
COMPARISON_HTML_PATH = REPO_ROOT / "docs" / "agentic-engineering-comparison.html"
TABLE_LABELS = ("A", "B", "C")

_TABLE_BLOCK_RE_TEMPLATE = r'<h2 class="section-head">Table {label}\b.*?<table\b[^>]*>(.*?)</table\b[^>]*>'
_THEAD_RE = re.compile(r'<thead\b[^>]*>(.*?)</thead\b[^>]*>', re.DOTALL)
_TBODY_RE = re.compile(r'<tbody\b[^>]*>(.*?)</tbody\b[^>]*>', re.DOTALL)
_COL_TH_RE = re.compile(r'<th\b[^>]*\bscope\s*=\s*"col"')
_TR_RE = re.compile(r'<tr\b[^>]*>(.*?)</tr\b[^>]*>', re.DOTALL)
_TD_RE = re.compile(r'<td\b')
_TABLE_CSS_RULE_RE = re.compile(r'(?m)^[ \t]*table[ \t]*\{([^}]*)\}')
_MIN_WIDTH_RE = re.compile(r'min-width\s*:\s*(\d+)px')


def extract_table_html(full_html: str, label: str) -> str:
    """Returns the substring strictly between that table's <table> and
    </table> tags (the regex's own group(1); the tags themselves are NOT
    included), located via the <h2 class="section-head">Table {label}
    heading. Raises AssertionError (with the label in the message) if not
    found."""
    pattern = re.compile(_TABLE_BLOCK_RE_TEMPLATE.format(label=re.escape(label)), re.DOTALL)
    match = pattern.search(full_html)
    assert match is not None, f"Table {label}: no <table> block found after its section-head heading"
    return match.group(1)


def col_count(table_html: str) -> "int | None":
    """Count of <th ...scope="col"...> inside <thead>, attribute-order
    safe. Returns None (never raises) if no <thead> is found, so callers
    can report a named violation instead of crashing."""
    thead_match = _THEAD_RE.search(table_html)
    if thead_match is None:
        return None
    return len(_COL_TH_RE.findall(thead_match.group(1)))


def body_row_td_counts(table_html: str) -> "list[int] | None":
    """<td> count per <tr> inside <tbody>, in document order. Returns None
    (never raises) if no <tbody> is found."""
    tbody_match = _TBODY_RE.search(table_html)
    if tbody_match is None:
        return None
    tbody_html = tbody_match.group(1)
    return [len(_TD_RE.findall(row)) for row in _TR_RE.findall(tbody_html)]


def table_rule_min_width(full_html: str) -> int:
    """The px value of `min-width` inside the standalone `table { ... }`
    CSS rule (matched by an anchored per-line selector regex, not
    proximity to .table-scroll), as an int. Raises AssertionError if the
    rule or the min-width declaration inside it is absent."""
    rule_match = _TABLE_CSS_RULE_RE.search(full_html)
    assert rule_match is not None, "no standalone `table { ... }` CSS rule found"
    width_match = _MIN_WIDTH_RE.search(rule_match.group(1))
    assert width_match is not None, "`table { ... }` CSS rule has no min-width declaration"
    return int(width_match.group(1))


def shape_violations(full_html: str) -> "list[str]":
    """Pure aggregator: calls the helpers above for A/B/C and the CSS
    rule, returns a list of human-readable violation strings (empty =
    valid). N is pinned as col_count(A) - the reference column count -
    before any comparison runs, and stays pinned even when a later check
    fails, a <thead>/<tbody> is missing, or col_count(A) itself is None."""
    violations: "list[str]" = []

    tables = {}
    for label in TABLE_LABELS:
        try:
            tables[label] = extract_table_html(full_html, label)
        except AssertionError as exc:
            violations.append(f"Table {label}: {exc}")
            tables[label] = None

    col_counts = {}
    for label in TABLE_LABELS:
        if tables[label] is None:
            col_counts[label] = None
            continue
        count = col_count(tables[label])
        if count is None:
            violations.append(f"Table {label}: no <thead> found, cannot determine column count")
        col_counts[label] = count

    reference_n = col_counts.get("A")
    if reference_n is None:
        violations.append("Table A: column count is undetermined (missing <thead>), cannot pin reference N")

    # Check (1): every table's column count matches the pinned reference N.
    for label in TABLE_LABELS:
        count = col_counts[label]
        if count is None:
            continue  # already reported above
        if reference_n is not None and count != reference_n:
            violations.append(
                f"Table {label}: column-count mismatch, has {count} <th scope=\"col\"> "
                f"but reference (Table A) has {reference_n}"
            )

    # Check (2): every body row has reference_n - 1 <td> cells. Missing
    # <tbody> is reported unconditionally (independent of reference_n),
    # since it is a per-table structural defect rather than an N-derived
    # comparison.
    for label in TABLE_LABELS:
        if tables[label] is None:
            continue
        row_counts = body_row_td_counts(tables[label])
        if row_counts is None:
            violations.append(f"Table {label}: no <tbody> found, cannot check row-length invariant")
            continue
        if reference_n is None:
            continue
        expected = reference_n - 1
        for idx, count in enumerate(row_counts):
            if count != expected:
                violations.append(
                    f"Table {label}: row {idx} row-length mismatch, has {count} <td> "
                    f"but expected {expected} (N-1 where N={reference_n})"
                )

    # Check (3): the CSS table rule's min-width matches 240 + 200*(N-1).
    if reference_n is not None:
        try:
            actual_min_width = table_rule_min_width(full_html)
        except AssertionError as exc:
            violations.append(f"min-width: {exc}")
        else:
            expected_min_width = 240 + 200 * (reference_n - 1)
            if actual_min_width != expected_min_width:
                violations.append(
                    f"min-width: table {{ }} rule declares {actual_min_width}px "
                    f"but formula 240 + 200*(N-1) with N={reference_n} expects {expected_min_width}px"
                )

    return violations


@pytest.fixture(scope="module")
def full_html() -> str:
    return COMPARISON_HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def reference_n(full_html: str) -> int:
    table_a = extract_table_html(full_html, "A")
    n = col_count(table_a)
    assert n is not None, "Table A: live page has no <thead>, cannot derive reference N"
    return n


def test_live_page_has_matching_column_counts(full_html: str, reference_n: int) -> None:
    for label in TABLE_LABELS:
        table_html = extract_table_html(full_html, label)
        n = col_count(table_html)
        assert n == reference_n, f"Table {label} has {n} <th scope=\"col\"> columns, expected {reference_n}"


@pytest.mark.parametrize("label", TABLE_LABELS)
def test_live_page_body_rows_match_column_count(full_html: str, reference_n: int, label: str) -> None:
    table_html = extract_table_html(full_html, label)
    row_counts = body_row_td_counts(table_html)
    assert row_counts is not None, f"Table {label}: no <tbody> found"
    expected = reference_n - 1
    for idx, count in enumerate(row_counts):
        assert count == expected, f"Table {label} row {idx} has {count} <td>, expected {expected}"


def test_live_page_min_width_matches_formula(full_html: str, reference_n: int) -> None:
    actual = table_rule_min_width(full_html)
    expected = 240 + 200 * (reference_n - 1)
    assert actual == expected, f"table {{ }} min-width is {actual}px, expected {expected}px for N={reference_n}"


def test_removed_td_reddens_check(full_html: str) -> None:
    table_a = extract_table_html(full_html, "A")
    tbody_match = _TBODY_RE.search(table_a)
    assert tbody_match is not None
    tbody_html = tbody_match.group(1)
    first_row_match = _TR_RE.search(tbody_html)
    assert first_row_match is not None
    row_html = first_row_match.group(0)
    mutated_row_html = re.sub(r'<td\b[^>]*>.*?</td\b[^>]*>', '', row_html, count=1, flags=re.DOTALL)
    assert mutated_row_html != row_html, "mutation matched nothing inside the first tbody row"

    mutated_html = full_html.replace(row_html, mutated_row_html, 1)
    assert mutated_html != full_html, "mutation was a no-op on the full document"

    violations = shape_violations(mutated_html)
    assert violations, "expected shape_violations to report a violation after removing a <td>"
    assert any("Table A" in v and "row-length mismatch" in v for v in violations), violations


def test_extra_thead_th_reddens_check(full_html: str) -> None:
    table_a = extract_table_html(full_html, "A")
    thead_match = _THEAD_RE.search(table_a)
    assert thead_match is not None
    thead_html = thead_match.group(0)
    mutated_thead_html = thead_html.replace(
        "</tr>", '<th scope="col">Mutant</th>\n          </tr>', 1
    )
    assert mutated_thead_html != thead_html, "mutation matched nothing inside Table A's <thead>"

    mutated_html = full_html.replace(thead_html, mutated_thead_html, 1)
    assert mutated_html != full_html, "mutation was a no-op on the full document"

    violations = shape_violations(mutated_html)
    assert violations, "expected shape_violations to report a violation after adding a <th scope=\"col\">"
    assert any("Table A" in v for v in violations), violations


def test_min_width_off_by_200_reddens_check(full_html: str) -> None:
    rule_match = _TABLE_CSS_RULE_RE.search(full_html)
    assert rule_match is not None
    rule_text = rule_match.group(0)
    width_match = _MIN_WIDTH_RE.search(rule_text)
    assert width_match is not None
    live_value = int(width_match.group(1))
    mutated_value = live_value + 200

    mutated_rule_text = rule_text[: width_match.start(1)] + str(mutated_value) + rule_text[width_match.end(1):]
    assert mutated_rule_text != rule_text, "mutation matched nothing inside the table { } CSS rule"

    mutated_html = full_html.replace(rule_text, mutated_rule_text, 1)
    assert mutated_html != full_html, "mutation was a no-op on the full document"

    violations = shape_violations(mutated_html)
    assert violations, "expected shape_violations to report a violation after mutating min-width by 200px"
    assert any("min-width" in v for v in violations), violations


def test_missing_thead_or_tbody_reports_named_violation(full_html: str) -> None:
    """Round-3 Skeptic Minor: a missing <thead> or <tbody> inside an
    otherwise-located table must degrade to a named violation string, not
    raise. Verified directly against the helper functions and against
    shape_violations on a synthetic table missing both."""
    table_a = extract_table_html(full_html, "A")
    assert col_count("<table><tbody><tr><td>x</td></tr></tbody></table>") is None
    assert body_row_td_counts("<table><thead><tr><th scope=\"col\">x</th></tr></thead></table>") is None

    thead_match = _THEAD_RE.search(table_a)
    tbody_match = _TBODY_RE.search(table_a)
    assert thead_match is not None and tbody_match is not None
    stripped_table_a = table_a.replace(thead_match.group(0), "").replace(tbody_match.group(0), "")

    mutated_html = full_html.replace(table_a, stripped_table_a, 1)
    assert mutated_html != full_html, "mutation was a no-op on the full document"

    violations = shape_violations(mutated_html)
    assert any("Table A" in v and "<thead>" in v for v in violations), violations
    assert any("Table A" in v and "<tbody>" in v for v in violations), violations
