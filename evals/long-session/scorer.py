#!/usr/bin/env python3
"""
Long-session eval scorer.

Reads a fixture YAML and a conductor response (from stdout or a file).
Scores pass/fail based on whether the conductor correctly references
the decision from the specified turn.
"""
import yaml
import sys
import re


def score(fixture_path: str, response: str) -> dict:
    with open(fixture_path) as f:
        fixture = yaml.safe_load(f)

    decision = fixture["decision"]
    response_lower = response.lower()

    # Check expected references
    expected_found = any(ref.lower() in response_lower for ref in decision["expected_references"])

    # Check forbidden references
    forbidden_found = any(ref.lower() in response_lower for ref in decision.get("forbidden_references", []))

    passed = expected_found and not forbidden_found

    return {
        "fixture_id": fixture["id"],
        "passed": passed,
        "expected_found": expected_found,
        "forbidden_found": forbidden_found,
        "details": "Pass" if passed else "Fail: missed expected reference or used forbidden reference"
    }


if __name__ == "__main__":
    fixture = sys.argv[1]
    response = sys.stdin.read()
    result = score(fixture, response)
    print(yaml.dump(result))
    sys.exit(0 if result["passed"] else 1)
