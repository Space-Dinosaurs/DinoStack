# Run with: python3 hooks/tests/test-doc-sync-abdication-guard.py
"""
Regression guard: the `abdication_guard_enabled` documentation must not
regress to the false claims DS-115 fix pass 1 (commit 61a802df) corrected
across three files.

Why this exists: `abdication_guard_enabled` has no code-level default - an
absent key leaves the guard inert (see hooks/enforce-no-abdication.py:864,
`config.get("abdication_guard_enabled") is not True`). Two of the three
corrected files (hooks/enforce-no-abdication.py's own inline comment and
docs/components.md's config entry) directly asserted the opposite - that
the guard "defaults to true" / is "Default on" - despite the guard code
itself never having behaved that way. The third (hooks/AGENTS.md) made a
narrower but related error: it described the guard as blocking only one
shape (a permission-seeking interrogative), silently dropping the second
shape (a stalled surface-and-proceed commitment) the guard has also blocked
since the surface-and-proceed fix landed. All three were corrected in the
same pass with no accompanying regression test, and the false-default claim
specifically has now recurred four times across this one file/feature (see
MEMORY.md "PR review cycles vs skeptic adherence" and
content/references/regression-test-obligation.md for the general obligation
this test satisfies). Nothing upstream of this test asserted on any of the
three claims, so they survived multiple review rounds un-caught; a plain
grep plus two scoped structural checks are enough to catch a recurrence of
any of them, and that is the entire job of this file. Do not delete this
test as noise - it is the only mechanical check standing between an edit
here and a repeat of any of the three misses.

Every statement above was verified true against the repo as of commit
61a802df (fix pass 1), by re-introducing each of the three original claims
one at a time in a scratch copy and confirming this suite fails on each
(see the commit message / PR description for the observed exit codes), and
by the confirming repo-wide grep for the two literal phrasings returning
zero hits at the time this test was written.
"""
import os
import re
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Phrasings that must never reappear, regardless of exact surrounding prose.
# Matched case-insensitively; deliberately loose (not proximity-scoped to
# "abdication_guard_enabled") because both phrasings are narrow enough on
# their own not to false-positive elsewhere in these three files - confirmed
# by a repo-wide grep across content/ docs/ README.md CONTRIBUTING.md
# .github/ hooks/ bin/ returning zero hits for either phrase as of this
# writing. "default `true`" is deliberately NOT included here even though
# it was the pre-fix phrasing in docs/components.md, because that literal
# string is legitimately used by several OTHER config toggles in the same
# file (e.g. commit_telemetry, skill_candidate_detection) - a bare global
# match on it would false-positive on unrelated, correct entries. The
# abdication_guard_enabled-specific case is covered by
# test_components_md_states_absent_semantics() below, which scopes to that
# entry's own text span.
FORBIDDEN_PHRASES = [
    "defaults to true",
    "default on",
]

# The three files DS-115 fix pass 1 corrected. Paths are relative to repo root.
TARGET_FILES = [
    "hooks/enforce-no-abdication.py",
    "docs/components.md",
    "hooks/AGENTS.md",
]


def read_file(rel_path: str) -> str:
    with open(os.path.join(REPO_ROOT, rel_path), "r") as f:
        return f.read()


def normalized_for_phrase_search(text: str) -> str:
    """Collapse newlines, leading '#' comment markers, and repeated
    whitespace to single spaces so a forbidden phrase wrapped across a
    line break (e.g. a Python comment split mid-sentence) is still
    detected. Without this, "defaults to\\n        # true" would not
    match the contiguous phrase "defaults to true" even though it is the
    same false claim - exactly the shape the old enforce-no-abdication.py
    comment used."""
    collapsed = re.sub(r"\n\s*#?\s*", " ", text)
    return re.sub(r"\s+", " ", collapsed)


def test_forbidden_phrases_absent() -> int:
    """Assertions 1-9 (3 files x 3 phrases): none of the three corrected
    files may contain any of the forbidden default-true phrasings."""
    print("\n  [MUST NOT REGRESS: false 'default true' claim]")
    failed = 0
    n = 0
    for rel_path in TARGET_FILES:
        text = normalized_for_phrase_search(read_file(rel_path)).lower()
        for phrase in FORBIDDEN_PHRASES:
            n += 1
            present = phrase in text
            print(f"  [{'FAIL' if present else 'PASS'}] {n}. '{phrase}' absent from {rel_path}")
            if present:
                failed += 1
    return failed


def test_enforce_no_abdication_comment_corrected() -> int:
    """Assertion 10: the specific inline comment directly preceding the
    `config.get("abdication_guard_enabled")` read in enforce-no-abdication.py
    states the corrected absent-key-is-inert semantics. Scoped to the
    comment block immediately above that line (not the whole file) so a
    reworded but still-correct comment elsewhere can't mask a regression at
    this specific site."""
    print("\n  [MUST STATE: corrected absent-key semantics at the config-read site]")
    failed = 0
    text = read_file("hooks/enforce-no-abdication.py")
    lines = text.splitlines()
    site_idx = next(
        (i for i, line in enumerate(lines) if 'config.get("abdication_guard_enabled")' in line),
        None,
    )
    if site_idx is None:
        print("  [FAIL] 10. config.get(\"abdication_guard_enabled\") read site not found")
        return 1
    # Look at the two comment lines directly above the config_path assignment
    # (the comment block precedes config_path, which precedes the try/read).
    window_start = max(0, site_idx - 8)
    window = "\n".join(lines[window_start:site_idx]).lower()
    corrected_present = "absent" in window and "exactly" in window
    print(f"  [{'PASS' if corrected_present else 'FAIL'}] 10. Comment above config-read states 'absent'/'exactly' semantics")
    if not corrected_present:
        failed += 1
    return failed


def test_components_md_states_absent_semantics() -> int:
    """Assertion 11: docs/components.md's abdication_guard_enabled entry
    states 'absent' guard-inert semantics rather than a bare boolean
    default."""
    print("\n  [MUST STATE: absent -> guard inert in docs/components.md]")
    failed = 0
    text = read_file("docs/components.md")
    match = re.search(r"`abdication_guard_enabled`[^)]*\)", text)
    entry = match.group(0) if match else ""
    entry_lower = entry.lower()
    absent_present = "absent" in entry_lower
    print(f"  [{'PASS' if absent_present else 'FAIL'}] 11. docs/components.md abdication_guard_enabled entry states 'absent' semantics")
    if not absent_present:
        failed += 1

    default_true_present = "default `true`" in entry_lower
    print(f"  [{'FAIL' if default_true_present else 'PASS'}] 12. docs/components.md abdication_guard_enabled entry does not claim 'default `true`'")
    if default_true_present:
        failed += 1
    return failed


def test_hooks_agents_md_states_both_shapes() -> int:
    """Assertion 13: hooks/AGENTS.md's enforce-no-abdication.py table row
    describes BOTH shapes the guard blocks - a permission-seeking
    interrogative AND a stalled surface-and-proceed commitment - not just
    the interrogative shape. The pre-fix row named only the interrogative
    shape ("Block turns that end with permission-seeking interrogatives;
    inject a 'proceed' directive.") which is not a "default true" phrasing
    at all, so the FORBIDDEN_PHRASES check above cannot catch its
    regression - this assertion exists specifically to cover that gap."""
    print("\n  [MUST STATE: both guard shapes in hooks/AGENTS.md]")
    failed = 0
    text = read_file("hooks/AGENTS.md")
    match = re.search(r"\| `enforce-no-abdication\.py` \|.*\|\n", text)
    row = match.group(0) if match else ""
    row_lower = row.lower()
    if not row:
        print("  [FAIL] 13. enforce-no-abdication.py row not found in hooks/AGENTS.md")
        return 1
    interrogative_present = "interrogative" in row_lower
    stall_present = "stall" in row_lower or "surface-and-proceed" in row_lower
    both_present = interrogative_present and stall_present
    print(f"  [{'PASS' if both_present else 'FAIL'}] 13. hooks/AGENTS.md row describes both the interrogative and stall/surface-and-proceed shapes")
    if not both_present:
        failed += 1
    return failed


def main() -> None:
    total_failed = 0
    total_failed += test_forbidden_phrases_absent()
    total_failed += test_enforce_no_abdication_comment_corrected()
    total_failed += test_components_md_states_absent_semantics()
    total_failed += test_hooks_agents_md_states_both_shapes()

    print()
    if total_failed == 0:
        print("All doc-sync abdication-guard tests passed.")
        sys.exit(0)
    else:
        print(f"{total_failed} test assertion(s) FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    main()
