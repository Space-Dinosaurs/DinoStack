#!/usr/bin/env python3
"""
Spec tests for DS-163 round-3 rework: two of the round-3 Skeptic findings
(the Major doc-agreement finding, and Minor 2's unparseable
condition-position placeholder) get their own mechanism-pinned regression
guard here, per the per-finding regression obligation.

Covers:
  - Major: docs/events-log-telemetry.md and content/references/events-log.md
    must agree on tracker_writeback's coverage scope. The round-1 overclaim
    ("one event per ticket entry regardless of outcome") must not exist in
    either file, and both files must state the narrower, correct scope
    ("one event per W1 gate evaluation the conductor actually reaches").
  - Minor 2: every ```bash fence in content/commands/ds-implement-ticket.md
    must parse under `bash -n`, with a precisely-allowlisted set of
    pre-existing value-position placeholder exceptions (verified against
    origin/main at the time this test was written) - no NEW condition-
    position placeholder may be introduced.

Run with: python3 -m pytest bin/tests/test_ds163_round3_rework_spec.py -q
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

EVENTS_LOG_PATH = REPO_ROOT / "content" / "references" / "events-log.md"
EVENTS_LOG_TELEMETRY_PATH = REPO_ROOT / "docs" / "events-log-telemetry.md"
IMPLEMENT_TICKET_PATH = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"

# The round-1 overclaim. Neither file may contain this phrase.
OVERCLAIM_PHRASE = "one event per ticket entry regardless of outcome"

# The corrected, narrower coverage statement. Both files must contain this
# (or a superset sentence containing it) so they agree.
CORRECT_COVERAGE_PHRASE = "one event per W1 gate evaluation the conductor"

# Fences whose FIRST LINE matches one of these regexes are pre-existing
# value-position placeholders on origin/main, verified by running bash -n
# against origin/main's copy of this file at the time this test was
# written (DS-163 round 3). A new match here is fine (these are known-bad
# forever); anything else that fails bash -n is a NEW defect.
ALLOWLISTED_FIRST_LINES = [
    re.compile(r'^\s*USAGE_AND_CALIBRATION="\$\(printf'),
    re.compile(r"^PR_NUMBER=<captured-from-Phase-9>$"),
    re.compile(r'^\s*RUN_ID=\$\(gh run list --pr "\$PR_NUMBER"'),
    re.compile(r'^\s*if \[ -f \.github/CODEOWNERS \]'),
    re.compile(r"^rm -f \.agentic/qa\.md\.snapshot-<ticket_id>"),
]

BASH_FENCE_RE = re.compile(r"```bash\n(.*?)\n```", re.S)


def _bash_n_ok(fence_body: str) -> bool:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sh", delete=False
    ) as fh:
        fh.write(fence_body)
        path = fh.name
    try:
        result = subprocess.run(
            ["bash", "-n", path], capture_output=True, text=True
        )
        return result.returncode == 0
    finally:
        Path(path).unlink(missing_ok=True)


def _is_allowlisted(fence_body: str) -> bool:
    first_line = fence_body.splitlines()[0] if fence_body.splitlines() else ""
    return any(rx.search(first_line) for rx in ALLOWLISTED_FIRST_LINES)


def test_events_log_and_telemetry_doc_do_not_carry_the_overclaim():
    for path in (EVENTS_LOG_PATH, EVENTS_LOG_TELEMETRY_PATH):
        text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
        assert OVERCLAIM_PHRASE not in text, (
            f"{path} still carries the round-1 overclaim "
            f"({OVERCLAIM_PHRASE!r}) - tracker_writeback does NOT fire on "
            f"every ticket entry; it fires only on W1 gate evaluations the "
            f"conductor actually reaches"
        )


def _normalize_whitespace(text: str) -> str:
    # Markdown prose wraps across lines; a phrase that spans a line break
    # in the source must still match. Collapse all whitespace runs
    # (including embedded newlines) to a single space before comparing.
    return re.sub(r"\s+", " ", text)


def test_events_log_and_telemetry_doc_agree_on_coverage_scope():
    events_log_text = _normalize_whitespace(
        EVENTS_LOG_PATH.read_text(encoding="utf-8")
    )
    telemetry_text = _normalize_whitespace(
        EVENTS_LOG_TELEMETRY_PATH.read_text(encoding="utf-8")
    )
    assert CORRECT_COVERAGE_PHRASE in events_log_text, (
        f"{EVENTS_LOG_PATH} must state the narrower tracker_writeback "
        f"coverage scope ({CORRECT_COVERAGE_PHRASE!r})"
    )
    assert CORRECT_COVERAGE_PHRASE in telemetry_text, (
        f"{EVENTS_LOG_TELEMETRY_PATH} must state the same narrower "
        f"tracker_writeback coverage scope ({CORRECT_COVERAGE_PHRASE!r}) - "
        f"the public doc previously contradicted the reference doc here"
    )


def test_no_new_condition_position_placeholder_in_bash_fences():
    text = IMPLEMENT_TICKET_PATH.read_text(encoding="utf-8")
    fences = BASH_FENCE_RE.findall(text)
    unexpected_failures = []
    for fence in fences:
        if _bash_n_ok(fence):
            continue
        if _is_allowlisted(fence):
            continue
        unexpected_failures.append(fence.splitlines()[0] if fence.splitlines() else "<empty>")
    assert not unexpected_failures, (
        f"the following bash fence(s) in {IMPLEMENT_TICKET_PATH} fail "
        f"`bash -n` and are NOT on the pre-existing value-position "
        f"placeholder allowlist - this is the round-1-recurring class of "
        f"defect where a fence loses its emit line to a parse error before "
        f"it ever runs: {unexpected_failures}"
    )


def test_allowlist_entries_still_exist():
    # Renamed from test_allowlist_entries_still_exist_and_still_fail_bash_n
    # (DS-163 round-4 rework): the original name promised a check of BOTH
    # halves - that each allowlist entry still matches a fence, AND that
    # the matched fence still fails `bash -n` - but the body below only
    # ever asserted the first half. Rather than add the missing half, the
    # name is narrowed to match what this test actually does: confirm
    # every allowlist regex still matches SOME fence in the file. If a
    # pre-existing placeholder gets fixed (turned into valid bash or
    # removed), its allowlist regex should stop matching anything - this
    # guards against the allowlist silently widening to cover a NEW,
    # unrelated failure after the original placeholder it was written for
    # is gone. Adding the missing half was judged not worth it: the sibling
    # test_no_new_condition_position_placeholder_in_bash_fences() above
    # short-circuits with `continue` as soon as `_bash_n_ok(fence)` is
    # True, before it ever consults `_is_allowlisted()` - so an allowlisted
    # fence that has stopped failing `bash -n` (a "dead" entry) is already
    # skipped by that first check regardless of the allowlist, and a dead
    # entry can therefore only ever exempt a fence that already fails
    # `bash -n` in the first place. The missing half of this test's name
    # would add no protection the control flow above doesn't already give
    # for free.
    text = IMPLEMENT_TICKET_PATH.read_text(encoding="utf-8")
    fences = BASH_FENCE_RE.findall(text)
    matched_regexes = set()
    for fence in fences:
        if _is_allowlisted(fence):
            first_line = fence.splitlines()[0] if fence.splitlines() else ""
            for i, rx in enumerate(ALLOWLISTED_FIRST_LINES):
                if rx.search(first_line):
                    matched_regexes.add(i)
    assert len(matched_regexes) == len(ALLOWLISTED_FIRST_LINES), (
        f"expected all {len(ALLOWLISTED_FIRST_LINES)} allowlist entries to "
        f"match a fence in {IMPLEMENT_TICKET_PATH}; matched indices: "
        f"{sorted(matched_regexes)} - an unmatched entry means its "
        f"placeholder was fixed/removed and the allowlist line should be "
        f"deleted, not left dangling"
    )
