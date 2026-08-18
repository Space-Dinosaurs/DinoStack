#!/usr/bin/env python3
"""
Tests for bin/ds-hook-fire-report (DS-179 /ds-prune-harness Signal 8 input).

Covers the binding status-enum contract from the module's own manifest and
content/commands/ds-prune-harness.md Signal 8: UNMEASURED is never conflated
with a real zero (ZERO_INVOCATIONS / ZERO_ACTION_IN_WINDOW), and the two
zero statuses stay distinct per posture. Each test below names the mutation
that would redden it, per DS-179's own mutation-testing obligation.

Run with: python3 -m pytest bin/tests/test_ds_hook_fire_report.py -q
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BIN = Path(__file__).parent.parent / "ds-hook-fire-report"
LIB_SRC = Path(__file__).parent.parent.parent / "scripts" / "lib" / "enforcer_facts.py"
PY = sys.executable

# Recent-timestamp helper - always inside any real --days window, computed
# relative to "now" rather than a hardcoded literal date, so this suite
# never goes stale the way a fixed calendar date would.
_RECENT_TS = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace(
    "+00:00", "Z"
)

# A hook stub whose only fire-log call logs "deny" - a real ACTION_ONLY
# posture (never logs a plain "allow", so it should classify the same way
# a real hooks/enforce-*.py PreToolUse hook does).
_ACTION_ONLY_HOOK_SRC = '''
def check(data):
    log_fire(data, "enforce-fake-action", "deny", "blocked")
'''

# A hook stub shaped like enforce-no-abdication.py: it logs a plain "allow"
# on its non-firing path, which is exactly what makes a posture
# EVERY_VERDICT rather than ACTION_ONLY.
_EVERY_VERDICT_HOOK_SRC = '''
def check(data):
    log_fire(data, "enforce-fake-abdication", "allow", "ok")
'''


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_repo(tmp_path: Path) -> Path:
    """Synthetic DinoStack-shaped repo: hooks/ with two fixture enforce-*.py
    files (one ACTION_ONLY, one EVERY_VERDICT) plus a real copy of
    scripts/lib/enforcer_facts.py (the module under test's own dependency -
    copied rather than imported so this test exercises the shipped file,
    not a path into the real checkout)."""
    repo = tmp_path / "repo"
    (repo / "hooks").mkdir(parents=True, exist_ok=True)
    _write(repo / "hooks" / "enforce-fake-action.py", _ACTION_ONLY_HOOK_SRC)
    _write(repo / "hooks" / "enforce-fake-abdication.py", _EVERY_VERDICT_HOOK_SRC)
    (repo / "scripts" / "lib").mkdir(parents=True, exist_ok=True)
    shutil.copy(LIB_SRC, repo / "scripts" / "lib" / "enforcer_facts.py")
    return repo


def _run(repo: Path, *extra: str):
    return subprocess.run(
        [PY, str(BIN), "--repo", str(repo), *extra],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _run_json(repo: Path, *extra: str) -> list[dict]:
    proc = _run(repo, "--json", *extra)
    assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr}"
    return json.loads(proc.stdout)


def _row_for(rows: list[dict], hook: str) -> dict:
    matches = [r for r in rows if r["hook"] == hook]
    assert matches, f"no row for {hook!r} in {[r['hook'] for r in rows]}"
    return matches[0]


# ---------------------------------------------------------------------------
# (a) ACTION_ONLY hook, 0 window entries -> ZERO_ACTION_IN_WINDOW, never
#     UNMEASURED, when the log is present.
#     Mutation: delete the fixture log entirely -> must flip to UNMEASURED.
# ---------------------------------------------------------------------------


def test_action_only_zero_window_is_zero_action_not_unmeasured(tmp_path):
    repo = _make_repo(tmp_path)
    # Log present (non-empty), but carries no entries for our fixture hook -
    # a real "this hook fired zero times in the window" case, not an
    # absent-log case.
    _write(
        repo / ".agentic" / ".enforcement-fires.jsonl",
        json.dumps(
            {
                "ts": _RECENT_TS,
                "hook": "enforce-some-other-hook",
                "decision": "deny",
                "reason": "unrelated",
            }
        )
        + "\n",
    )
    rows = _run_json(repo)
    row = _row_for(rows, "enforce-fake-action.py")
    assert row["posture"] == "ACTION_ONLY"
    assert row["log_present"] is True
    assert row["fire_count_window"] == 0
    assert row["status"] == "ZERO_ACTION_IN_WINDOW"


def test_action_only_zero_window_flips_to_unmeasured_when_log_absent(tmp_path):
    """Mutation for the above: delete the fixture log file entirely. The
    status for the same hook must flip to UNMEASURED - proving
    ZERO_ACTION_IN_WINDOW and UNMEASURED are structurally distinct code
    paths, not one path wearing two labels."""
    repo = _make_repo(tmp_path)
    # No .agentic/.enforcement-fires.jsonl written at all.
    rows = _run_json(repo)
    row = _row_for(rows, "enforce-fake-action.py")
    assert row["posture"] == "ACTION_ONLY"
    assert row["log_present"] is False
    assert row["status"] == "UNMEASURED"


# ---------------------------------------------------------------------------
# (b) EVERY_VERDICT hook, 0 entries -> ZERO_INVOCATIONS.
#     Mutation: add one "allow" line for that hook -> must flip to ACTIVE.
# ---------------------------------------------------------------------------


def test_every_verdict_zero_entries_is_zero_invocations(tmp_path):
    repo = _make_repo(tmp_path)
    _write(
        repo / ".agentic" / ".enforcement-fires.jsonl",
        json.dumps(
            {
                "ts": _RECENT_TS,
                "hook": "enforce-some-other-hook",
                "decision": "deny",
                "reason": "unrelated",
            }
        )
        + "\n",
    )
    rows = _run_json(repo)
    row = _row_for(rows, "enforce-fake-abdication.py")
    assert row["posture"] == "EVERY_VERDICT"
    assert row["fire_count_window"] == 0
    assert row["status"] == "ZERO_INVOCATIONS"


def test_every_verdict_one_allow_row_flips_to_active(tmp_path):
    """Mutation for the above: add one 'allow' fire-log row for the
    EVERY_VERDICT fixture hook. Status must flip to ACTIVE."""
    repo = _make_repo(tmp_path)
    _write(
        repo / ".agentic" / ".enforcement-fires.jsonl",
        json.dumps(
            {
                "ts": _RECENT_TS,
                "hook": "enforce-fake-abdication",
                "decision": "allow",
                "reason": "no-op verdict",
            }
        )
        + "\n",
    )
    rows = _run_json(repo)
    row = _row_for(rows, "enforce-fake-abdication.py")
    assert row["posture"] == "EVERY_VERDICT"
    assert row["fire_count_window"] == 1
    assert row["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# (c) Every real hooks/enforce-*.py file appears in a real (non-fixture)
#     run's output set, and the count is derived from disk, never a
#     hand-typed cardinal.
#     Mutation: rename one hook file in a tmp copy of the real repo; the
#     count must drop by 1.
# ---------------------------------------------------------------------------


def _real_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def test_real_repo_hook_set_matches_disk(tmp_path):
    real_root = _real_repo_root()
    real_hooks = sorted(p.name for p in (real_root / "hooks").glob("enforce-*.py"))
    assert len(real_hooks) >= 5, (
        f"only found {len(real_hooks)} real hooks/enforce-*.py files - the "
        "glob is probably broken, which would make this assertion vacuous"
    )

    rows = _run_json(real_root)
    reported_hooks = sorted(r["hook"] for r in rows)
    assert reported_hooks == real_hooks, (
        f"ds-hook-fire-report reported {reported_hooks}, expected exactly "
        f"the real hooks/enforce-*.py set {real_hooks}"
    )


def test_hook_count_drops_by_one_when_a_hook_file_is_renamed(tmp_path):
    """Mutation for the above: copy the real repo's hooks/ + scripts/lib/
    into a tmp dir and rename one hooks/enforce-*.py file so it no longer
    matches the glob. The reported count must drop by exactly 1, proving
    the derivation is live off disk rather than a cached/hand-typed set."""
    real_root = _real_repo_root()
    tmp_repo = tmp_path / "mutated-repo"
    (tmp_repo / "hooks").mkdir(parents=True, exist_ok=True)
    (tmp_repo / "scripts" / "lib").mkdir(parents=True, exist_ok=True)
    for p in (real_root / "hooks").glob("enforce-*.py"):
        shutil.copy(p, tmp_repo / "hooks" / p.name)
    shutil.copy(LIB_SRC, tmp_repo / "scripts" / "lib" / "enforcer_facts.py")

    baseline_rows = _run_json(tmp_repo)
    baseline_count = len(baseline_rows)

    victims = sorted((tmp_repo / "hooks").glob("enforce-*.py"))
    assert victims, "no copied hook files to mutate - setup is broken"
    victim = victims[0]
    victim.rename(tmp_repo / "hooks" / ("renamed-" + victim.name))

    mutated_rows = _run_json(tmp_repo)
    assert len(mutated_rows) == baseline_count - 1, (
        f"expected count to drop by exactly 1 after renaming "
        f"{victim.name} out of the enforce-*.py glob, got "
        f"{baseline_count} -> {len(mutated_rows)}"
    )


# ---------------------------------------------------------------------------
# CLI surface sanity
# ---------------------------------------------------------------------------


def test_table_output_is_default_and_json_flag_switches_format(tmp_path):
    repo = _make_repo(tmp_path)
    table_proc = _run(repo)
    assert table_proc.returncode == 0
    assert "posture" in table_proc.stdout  # table header, not JSON
    with_json = _run_json(repo)
    assert isinstance(with_json, list)


def test_days_window_is_respected(tmp_path):
    repo = _make_repo(tmp_path)
    _write(
        repo / ".agentic" / ".enforcement-fires.jsonl",
        json.dumps(
            {
                "ts": "2020-01-01T00:00:00Z",  # far outside any real window
                "hook": "enforce-fake-abdication",
                "decision": "allow",
                "reason": "ancient",
            }
        )
        + "\n",
    )
    rows = _run_json(repo, "--days", "14")
    row = _row_for(rows, "enforce-fake-abdication.py")
    assert row["fire_count_window"] == 0
    assert row["fire_count_all_time"] == 1
    assert row["status"] == "ZERO_INVOCATIONS"
