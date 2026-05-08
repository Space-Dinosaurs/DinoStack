"""
Purpose: Regression-test-presence dimension scorer. Checks result.diff for
         newly added test files. Symmetric N/A on tickets without a
         regression-test requirement.

Public API:
  score(result: dict, ticket: dict) -> dict
    Returns DimensionScore-shaped dict.

Upstream deps: stdlib re.

Downstream consumers: scoring/registry.py.

Failure modes: returns not-applicable (via registry symmetric check) on tickets
               where regression tests are not expected. Returns score=0.0 when
               a regression test is expected but none is found in the diff.

Performance: O(diff_size); regex-based.
"""
from __future__ import annotations

import re

SCORER_VERSION = "regression-test-presence-v1"

# Patterns matching test file paths in diffs
_TEST_FILE_PATTERNS = [
    r"\+\+\+ b/.*test.*\.(?:py|ts|js|tsx|jsx)$",
    r"\+\+\+ b/.*spec.*\.(?:py|ts|js|tsx|jsx)$",
    r"\+\+\+ b/tests?/",
    r"\+\+\+ b/__tests__/",
]
_TEST_FILE_RE = re.compile(
    "|".join(_TEST_FILE_PATTERNS), re.MULTILINE | re.IGNORECASE
)

# Patterns suggesting new test code was added (not just modified)
_NEW_TEST_PATTERNS = [
    r"^\+\s*def test_",
    r"^\+\s*it\(",
    r"^\+\s*test\(",
    r"^\+\s*describe\(",
    r"^\+\s*@pytest\.mark\.",
]
_NEW_TEST_RE = re.compile(
    "|".join(_NEW_TEST_PATTERNS), re.MULTILINE | re.IGNORECASE
)


def score(result: dict, ticket: dict) -> dict:
    """Score regression-test presence in the diff."""
    ticket_yaml = ticket.get("ticket_yaml", {})
    expects_regression_test = ticket_yaml.get(
        "expects_regression_test", None
    )

    artifacts = result.get("artifacts", {})
    diff = artifacts.get("diff", result.get("diff") or "")

    # If ticket explicitly says no test expected, N/A
    if expects_regression_test is False:
        return {
            "score": 1.0,
            "diagnostic": {
                "note": "Ticket declares expects_regression_test=False; N/A.",
            },
            "scorer_version": SCORER_VERSION,
            "status": "not-applicable",
        }

    if not diff:
        return {
            "score": 0.0,
            "diagnostic": {
                "note": "No diff available to check for test files.",
                "test_files_found": [],
                "new_test_code": False,
            },
            "scorer_version": SCORER_VERSION,
            "status": "scored",
        }

    test_file_matches = _TEST_FILE_RE.findall(diff)
    new_test_code = bool(_NEW_TEST_RE.search(diff))

    if test_file_matches or new_test_code:
        score_val = 1.0
    else:
        score_val = 0.0

    return {
        "score": score_val,
        "diagnostic": {
            "test_files_found": test_file_matches[:10],
            "new_test_code": new_test_code,
        },
        "scorer_version": SCORER_VERSION,
        "status": "scored",
    }
