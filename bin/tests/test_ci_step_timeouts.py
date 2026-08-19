#!/usr/bin/env python3
"""
Purpose: Regression guard for .github/workflows/bin-tests.yml's TIMEOUT
         POLICY comment (top of that file): every `run:` step in every job
         must carry its own `timeout-minutes`, except `actions/checkout` and
         `actions/setup-python` (cache-backed GitHub-hosted actions,
         deliberately exempted by that same policy comment - no stall on
         either has been observed there). Parses the YAML and enumerates
         steps mechanically; never a hand-typed count of how many steps
         exist (same discipline this repo uses for every other count-sync
         site - see AGENTS.md's count-sync entries).

Test groups:
  1. test_every_run_step_has_timeout_minutes - the real assertion: every
     `run:`-shaped step in every job of bin-tests.yml carries
     `timeout-minutes`.
  2. test_uses_steps_are_exempted_by_name - sanity check that the exemption
     set actually matches `actions/checkout*` / `actions/setup-python*`
     `uses:` steps and nothing else, so the exemption cannot silently widen
     to cover a `run:` step that happens to share a job with an exempted
     action.
  3. test_mutation_missing_timeout_is_caught - deletes `timeout-minutes`
     from one real `run:` step (bin-sh-tests' "install gitleaks CLI" step,
     a copy of the parsed YAML, not the file on disk) and asserts the
     checker function reports it as a violation, proving the checker
     function does something more than the parse succeeding.

Run with: python3 bin/tests/test_ci_step_timeouts.py
       or: python3 -m pytest bin/tests/test_ci_step_timeouts.py
"""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".github"
    / "workflows"
    / "bin-tests.yml"
)

EXEMPT_ACTION_PREFIXES = ("actions/checkout", "actions/setup-python")


def find_timeout_violations(workflow: dict) -> list[str]:
    """Return a list of "<job>/<step name>" strings for every `run:` step
    missing `timeout-minutes`. Steps whose `uses:` starts with one of
    EXEMPT_ACTION_PREFIXES are skipped entirely (they have no `run:` key to
    check in the first place, but the explicit skip keeps intent legible).
    """
    violations = []
    jobs = workflow.get("jobs", {})
    for job_name, job in jobs.items():
        for step in job.get("steps", []):
            uses = step.get("uses")
            if uses is not None:
                if any(uses.startswith(p) for p in EXEMPT_ACTION_PREFIXES):
                    continue
                # A `uses:` step that is NOT one of the exempted actions is
                # outside this test's stated scope (the policy comment only
                # discusses `run:` steps and the two named exemptions) -
                # skip it without asserting either way.
                continue
            if "run" not in step:
                continue
            step_label = step.get("name", "<unnamed step>")
            if "timeout-minutes" not in step:
                violations.append(f"{job_name}/{step_label}")
    return violations


class TestCiStepTimeouts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(WORKFLOW_PATH, "r") as f:
            cls.workflow = yaml.safe_load(f)

    def test_every_run_step_has_timeout_minutes(self):
        violations = find_timeout_violations(self.workflow)
        self.assertEqual(
            violations,
            [],
            "The following run: steps in bin-tests.yml are missing "
            "timeout-minutes (policy comment at the top of that file "
            "requires one on every run: step except actions/checkout and "
            "actions/setup-python): " + ", ".join(violations),
        )

    def test_uses_steps_are_exempted_by_name(self):
        jobs = self.workflow.get("jobs", {})
        seen_uses = set()
        for job in jobs.values():
            for step in job.get("steps", []):
                uses = step.get("uses")
                if uses is not None:
                    seen_uses.add(uses.split("@")[0])
        # Every `uses:` step actually present in the file must be one of the
        # two exempted actions - if a third action type is ever added to
        # this workflow, this test forces a conscious decision about
        # whether it needs a timeout-minutes-equivalent treatment rather
        # than silently inheriting the exemption.
        for uses in seen_uses:
            self.assertIn(
                uses,
                EXEMPT_ACTION_PREFIXES,
                f"uses: '{uses}' is not one of the two documented "
                "timeout-exempt actions (actions/checkout, "
                "actions/setup-python) - decide explicitly whether it "
                "needs a duration bound.",
            )

    def test_mutation_missing_timeout_is_caught(self):
        mutated = copy.deepcopy(self.workflow)
        target_job = mutated["jobs"]["bin-sh-tests"]
        found = False
        for step in target_job["steps"]:
            if step.get("name", "").startswith("install gitleaks CLI"):
                self.assertIn(
                    "timeout-minutes",
                    step,
                    "fixture step must start with timeout-minutes present, "
                    "or this mutation test proves nothing",
                )
                del step["timeout-minutes"]
                found = True
                break
        self.assertTrue(found, "could not locate the gitleaks install step to mutate")
        violations = find_timeout_violations(mutated)
        self.assertIn("bin-sh-tests/install gitleaks CLI (required by test_gitleaks_allowlist_scope.sh)", violations)


if __name__ == "__main__":
    unittest.main()
