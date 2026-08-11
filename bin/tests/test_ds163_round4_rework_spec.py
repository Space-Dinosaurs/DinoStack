#!/usr/bin/env python3
"""
Spec tests for DS-163 round-4 rework: the two Skeptic findings from round 4
get their own mechanism-pinned regression guard here, per the per-finding
regression obligation.

Covers:
  - Major: content/references/events-log.md's `session_uuid` paragraph must
    not claim "four" active conductor-emitted event types carry
    `data.session_uuid` when there are now five active conductor-emitted
    event types (the diff added `tracker_writeback`, which explicitly does
    NOT carry `session_uuid`). The corrected clause must name the count of
    five and explicitly exclude `tracker_writeback`.
  - Minor: the two W1 `tracker_writeback` emit fences in
    content/commands/ds-implement-ticket.md are mutually exclusive by
    construction - the skip-emit fence is guarded by
    `if [ -n "$W1_REASON" ]`, and the dispatch-emit fence must be guarded by
    `if [ -z "$W1_REASON" ]`. Before the round-4 fix, the dispatch fence had
    no guard at all, so a literal run of both fences on a skipped ticket
    (the common `TRACKER=none` path) emitted a second, affirmatively false
    `dispatch_failed` event. This test extracts both fences verbatim and
    executes them under a stubbed `ds-emit`, proving exactly one emit call
    fires per branch.

Run with: python3 -m pytest bin/tests/test_ds163_round4_rework_spec.py -q
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

EVENTS_LOG_PATH = REPO_ROOT / "content" / "references" / "events-log.md"
IMPLEMENT_TICKET_PATH = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"

BASH_FENCE_RE = re.compile(r"```bash\n(.*?)\n```", re.S)


# ---------------------------------------------------------------------------
# Major: the session_uuid count clause.
# ---------------------------------------------------------------------------

STALE_COUNT_PHRASE = "The four active conductor-emitted event types above"

CORRECTED_COUNT_PHRASE = (
    "Four of the five active conductor-emitted event types above"
)


def test_events_log_session_uuid_clause_does_not_claim_stale_four_of_four():
    text = EVENTS_LOG_PATH.read_text(encoding="utf-8")
    assert STALE_COUNT_PHRASE not in text, (
        f"{EVENTS_LOG_PATH} still claims 'the four active conductor-emitted "
        f"event types' carry session_uuid, but this diff added a fifth "
        f"active conductor-emitted type (tracker_writeback) that explicitly "
        f"does NOT carry session_uuid - the definite-article 'the four' "
        f"count is false now that there are five"
    )


def test_events_log_session_uuid_clause_states_corrected_four_of_five():
    text = EVENTS_LOG_PATH.read_text(encoding="utf-8")
    assert CORRECTED_COUNT_PHRASE in text, (
        f"{EVENTS_LOG_PATH} must state the corrected count clause "
        f"({CORRECTED_COUNT_PHRASE!r}) - four of the five active "
        f"conductor-emitted event types carry session_uuid; tracker_writeback "
        f"is the fifth and explicitly does not"
    )
    # And it must name the exception explicitly, not just fix the number.
    idx = text.index(CORRECTED_COUNT_PHRASE)
    window = text[idx : idx + 400]
    assert "tracker_writeback" in window and "does not" in window, (
        "the corrected count clause must explicitly name tracker_writeback "
        "as the exception that does not carry session_uuid, not merely "
        "change '4' to '4 of 5'"
    )


# ---------------------------------------------------------------------------
# Minor: dispatch-emit fence guard symmetry.
# ---------------------------------------------------------------------------


def _extract_fence_containing(marker: str) -> str:
    text = IMPLEMENT_TICKET_PATH.read_text(encoding="utf-8")
    for fence in BASH_FENCE_RE.findall(text):
        if marker in fence:
            return fence
    raise AssertionError(f"no ```bash fence found containing {marker!r}")


def _run_fence_sequence_and_count_emits(w1_reason: str) -> int:
    """Run both W1 emit fences back-to-back with W1_REASON pre-seeded to
    `w1_reason`, using a stubbed `ds-emit` that appends one line per
    invocation to a log file. Returns the number of ds-emit invocations
    observed - the mutual-exclusion guarantee under test is that this is
    always exactly 1, never 2, regardless of which branch W1_REASON
    selects."""
    skip_fence = _extract_fence_containing('\\"outcome\\":\\"skipped\\"')
    dispatch_fence = _extract_fence_containing('if [ -z "$W1_REASON" ]')

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        stub_bin = tmp / "bin"
        stub_bin.mkdir()
        log_path = tmp / "emit.log"
        stub = stub_bin / "ds-emit"
        stub.write_text(
            "#!/bin/sh\necho \"$@\" >> \"$DS_EMIT_LOG\"\nexit 0\n"
        )
        stub.chmod(0o755)

        script = (
            "set -euo pipefail\n"
            f'W1_REASON="{w1_reason}"\n'
            'TICKET_ID="DS-999"\n'
            'TRACKER_STATE_IN_PROGRESS="in_progress"\n'
            'W1_DISPATCH_OUTCOME="dispatched"\n'
            "LOOP_KEY=\"\"\n"
            + skip_fence
            + "\n"
            + dispatch_fence
            + "\n"
        )
        script_path = tmp / "run.sh"
        script_path.write_text(script)

        env = {
            "PATH": f"{stub_bin}:/usr/bin:/bin",
            "DS_EMIT_LOG": str(log_path),
        }
        result = subprocess.run(
            ["bash", str(script_path)],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, (
            f"fence sequence exited nonzero (W1_REASON={w1_reason!r}): "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        if log_path.exists():
            lines = [l for l in log_path.read_text().splitlines() if l.strip()]
            return len(lines)
        return 0


def test_skip_and_dispatch_emit_fences_are_mutually_exclusive_when_skipped():
    # The common TRACKER=none path: W1_REASON is non-empty. Exactly one
    # emit (the skip emit) must fire.
    count = _run_fence_sequence_and_count_emits("tracker_none")
    assert count == 1, (
        f"expected exactly 1 ds-emit call when W1_REASON is set "
        f"(skip path), got {count} - before the round-4 fix the dispatch "
        f"fence had no guard and fired unconditionally, producing a second, "
        f"affirmatively false dispatch_failed event on every skipped ticket"
    )


def test_skip_and_dispatch_emit_fences_are_mutually_exclusive_when_dispatched():
    # W1_REASON empty: the gate holds. Exactly one emit (the dispatch emit)
    # must fire.
    count = _run_fence_sequence_and_count_emits("")
    assert count == 1, (
        f"expected exactly 1 ds-emit call when W1_REASON is empty "
        f"(dispatch path), got {count}"
    )
