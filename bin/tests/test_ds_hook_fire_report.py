#!/usr/bin/env python3
"""
Tests for bin/ds-hook-fire-report (DS-179 /ds-prune-harness Signal 8 input).

Covers the binding status-enum contract from the module's own manifest and
content/commands/ds-prune-harness.md Signal 8: UNMEASURED is never conflated
with a real zero (ZERO_INVOCATIONS / ZERO_ACTION_IN_WINDOW), the two zero
statuses stay distinct per posture, a present-but-unparseable log is never
read as a real zero-fire measurement, and confidence-bearing coverage is
measured off the log's own timestamps, never the requested --days window.
Each test below names the mutation that would redden it, per DS-179's own
mutation-testing obligation.

Run with: python3 -m pytest bin/tests/test_ds_hook_fire_report.py -q
"""

from __future__ import annotations

import json
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


def _run_json(repo: Path, *extra: str) -> dict:
    proc = _run(repo, "--json", *extra)
    assert proc.returncode == 0, f"exit {proc.returncode}: {proc.stderr}"
    return json.loads(proc.stdout)


def _row_for(report: dict, hook: str) -> dict:
    rows = report["hooks"]
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
    report = _run_json(repo)
    assert report["meta"]["log_present"] is True
    row = _row_for(report, "enforce-fake-action.py")
    assert row["posture"] == "ACTION_ONLY"
    assert row["fire_count_window"] == 0
    assert row["status"] == "ZERO_ACTION_IN_WINDOW"


def test_action_only_zero_window_flips_to_unmeasured_when_log_absent(tmp_path):
    """Mutation for the above: delete the fixture log file entirely. The
    status for the same hook must flip to UNMEASURED - proving
    ZERO_ACTION_IN_WINDOW and UNMEASURED are structurally distinct code
    paths, not one path wearing two labels."""
    repo = _make_repo(tmp_path)
    # No .agentic/.enforcement-fires.jsonl written at all.
    report = _run_json(repo)
    assert report["meta"]["log_present"] is False
    row = _row_for(report, "enforce-fake-action.py")
    assert row["posture"] == "ACTION_ONLY"
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
    report = _run_json(repo)
    row = _row_for(report, "enforce-fake-abdication.py")
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
    report = _run_json(repo)
    row = _row_for(report, "enforce-fake-abdication.py")
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

    report = _run_json(real_root)
    reported_hooks = sorted(r["hook"] for r in report["hooks"])
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

    baseline_report = _run_json(tmp_repo)
    baseline_count = len(baseline_report["hooks"])

    victims = sorted((tmp_repo / "hooks").glob("enforce-*.py"))
    assert victims, "no copied hook files to mutate - setup is broken"
    victim = victims[0]
    victim.rename(tmp_repo / "hooks" / ("renamed-" + victim.name))

    mutated_report = _run_json(tmp_repo)
    assert len(mutated_report["hooks"]) == baseline_count - 1, (
        f"expected count to drop by exactly 1 after renaming "
        f"{victim.name} out of the enforce-*.py glob, got "
        f"{baseline_count} -> {len(mutated_report['hooks'])}"
    )


# ---------------------------------------------------------------------------
# (d) --repo names which tree to MEASURE, not where this tool's OWN code
#     (scripts/lib/enforcer_facts.py) lives. A --repo target that has
#     hooks/ but no scripts/lib/enforcer_facts.py of its own must still
#     succeed, because the tool loads its dependency from its own
#     resolved install dir, never from --repo.
#     Mutation: revert _load_enforcer_facts() to resolve
#     scripts/lib/enforcer_facts.py against repo_root (the --repo target)
#     instead of the tool's own install dir -> this test must fail with
#     an uncaught FileNotFoundError (a nonzero/crashed subprocess), since
#     the fixture repo below deliberately has no scripts/lib/ directory
#     at all.
# ---------------------------------------------------------------------------


def test_repo_without_its_own_enforcer_facts_still_succeeds(tmp_path):
    """--repo points at a tree with hooks/ but deliberately WITHOUT
    scripts/lib/enforcer_facts.py - simulating a partial or non-DinoStack
    checkout. The tool must still load its dependency from its own
    install dir and produce a report, not crash."""
    repo = tmp_path / "bare-repo"
    (repo / "hooks").mkdir(parents=True, exist_ok=True)
    _write(repo / "hooks" / "enforce-fake-action.py", _ACTION_ONLY_HOOK_SRC)
    # Deliberately no scripts/lib/ at all under this --repo target.
    assert not (repo / "scripts").exists()

    report = _run_json(repo)
    row = _row_for(report, "enforce-fake-action.py")
    assert row["posture"] == "ACTION_ONLY"
    assert row["status"] == "UNMEASURED"


# ---------------------------------------------------------------------------
# (e) A present-but-unparseable log must never read as a real zero-fire
#     measurement (the PR #723 accumulate-then-return-zero class).
#     Mutation: revert log_effectively_empty's use in the status branch
#     (i.e. gate status only on `not log_present`) -> both tests below
#     must flip from UNMEASURED to ZERO_INVOCATIONS / ZERO_ACTION_IN_WINDOW.
# ---------------------------------------------------------------------------


def test_wholly_malformed_log_reports_unmeasured_not_zero(tmp_path):
    """A present log file containing 2 lines of garbage (no valid JSON at
    all) must report UNMEASURED for every hook, not a real zero - a file
    nothing could be read out of is not evidence of zero invocations."""
    repo = _make_repo(tmp_path)
    _write(
        repo / ".agentic" / ".enforcement-fires.jsonl",
        "not json at all\n{also not json\n",
    )
    report = _run_json(repo)
    assert report["meta"]["log_present"] is True
    assert report["meta"]["log_parsed_lines"] == 0
    assert report["meta"]["log_total_lines"] == 2
    assert report["meta"]["log_malformed_lines"] == 2
    assert report["meta"]["log_effectively_empty"] is True
    action_row = _row_for(report, "enforce-fake-action.py")
    every_verdict_row = _row_for(report, "enforce-fake-abdication.py")
    assert action_row["status"] == "UNMEASURED"
    assert every_verdict_row["status"] == "UNMEASURED"


def test_empty_present_log_reports_unmeasured(tmp_path):
    """A present but wholly empty (0-byte) log file must also report
    UNMEASURED - indistinguishable from the malformed case in terms of
    "no usable data", by the same rule."""
    repo = _make_repo(tmp_path)
    _write(repo / ".agentic" / ".enforcement-fires.jsonl", "")
    report = _run_json(repo)
    assert report["meta"]["log_present"] is True
    assert report["meta"]["log_parsed_lines"] == 0
    assert report["meta"]["log_effectively_empty"] is True
    row = _row_for(report, "enforce-fake-abdication.py")
    assert row["status"] == "UNMEASURED"


def test_partially_malformed_log_is_a_real_measurement(tmp_path):
    """A log with SOME valid lines and SOME garbage lines is a real
    measurement over the lines that parsed - it must NOT collapse to
    UNMEASURED, and meta must report the malformed-line count so the
    caller can see the log was not perfectly clean.
    Mutation: change the effectively-empty predicate from
    `log_parsed_lines == 0` to `log_malformed_lines > 0` -> this test
    would flip from ZERO_INVOCATIONS to UNMEASURED even though one line
    genuinely parsed."""
    repo = _make_repo(tmp_path)
    _write(
        repo / ".agentic" / ".enforcement-fires.jsonl",
        "garbage line, not json\n"
        + json.dumps(
            {
                "ts": _RECENT_TS,
                "hook": "enforce-some-other-hook",
                "decision": "deny",
                "reason": "real record",
            }
        )
        + "\n",
    )
    report = _run_json(repo)
    assert report["meta"]["log_present"] is True
    assert report["meta"]["log_total_lines"] == 2
    assert report["meta"]["log_parsed_lines"] == 1
    assert report["meta"]["log_malformed_lines"] == 1
    assert report["meta"]["log_effectively_empty"] is False
    row = _row_for(report, "enforce-fake-abdication.py")
    assert row["status"] == "ZERO_INVOCATIONS"


# ---------------------------------------------------------------------------
# (f) Confidence-bearing coverage must be MEASURED off the log's own
#     timestamps (meta.log_coverage_days), never the requested --days
#     window (meta.requested_window_days echoes the caller's input
#     verbatim and must not be usable as a coverage claim).
#     Mutation: compute log_coverage_days as `days` (the requested window)
#     instead of the measured span -> the assertion below (coverage far
#     less than the requested 90) would flip to false (coverage == 90).
# ---------------------------------------------------------------------------


def test_log_coverage_days_is_measured_not_the_requested_window(tmp_path):
    repo = _make_repo(tmp_path)
    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat().replace(
        "+00:00", "Z"
    )
    _write(
        repo / ".agentic" / ".enforcement-fires.jsonl",
        json.dumps(
            {
                "ts": three_days_ago,
                "hook": "enforce-fake-abdication",
                "decision": "allow",
                "reason": "only 3 days of real history",
            }
        )
        + "\n",
    )
    # Request a 90-day window - far more than the log's real 3-day span.
    report = _run_json(repo, "--days", "90")
    assert report["meta"]["requested_window_days"] == 90
    coverage = report["meta"]["log_coverage_days"]
    assert coverage is not None
    assert coverage < 5, (
        f"log_coverage_days={coverage} should reflect the log's real ~3-day "
        "span, not the requested 90-day window"
    )


def test_log_coverage_days_is_none_when_log_absent(tmp_path):
    repo = _make_repo(tmp_path)
    report = _run_json(repo)
    assert report["meta"]["log_coverage_days"] is None


# ---------------------------------------------------------------------------
# (f.1) DS-179 round 3 Major 1 - log_coverage_days (span) alone is not data
#     adequacy. Reproduces the Skeptic's own two executed fixtures: a
#     sparse-but-old log can cross the old bare `log_coverage_days >= 30`
#     gate while containing almost no real data.
#     Mutation: delete the `log_parsed_lines >= MIN_PARSED_LINES_FOR_CONFIDENCE`
#     conjunct from log_confidence_eligible's computation -> both tests
#     below flip from False to True, since log_coverage_days alone (595.0
#     and 121.0 respectively) already clears the >= 30 span gate.
# ---------------------------------------------------------------------------


def test_sparse_old_log_crosses_span_gate_but_not_confidence_eligible(tmp_path):
    """Skeptic fixture 1: 2 records, one dated 2025-01-01 -> log_coverage_days
    far exceeds 30 (measured: 595.0), but only 2 parsed records exist -
    nowhere near enough to trust the span as a real measurement."""
    repo = _make_repo(tmp_path)
    old_ts = "2025-01-01T00:00:00Z"
    _write(
        repo / ".agentic" / ".enforcement-fires.jsonl",
        "\n".join(
            [
                json.dumps(
                    {
                        "ts": old_ts,
                        "hook": "enforce-fake-abdication",
                        "decision": "allow",
                        "reason": "ancient",
                    }
                ),
                json.dumps(
                    {
                        "ts": _RECENT_TS,
                        "hook": "enforce-fake-abdication",
                        "decision": "allow",
                        "reason": "recent",
                    }
                ),
            ]
        )
        + "\n",
    )
    report = _run_json(repo, "--days", "90")
    coverage = report["meta"]["log_coverage_days"]
    assert coverage is not None and coverage >= 30, (
        f"expected the span gate to be crossed (>= 30), got {coverage}"
    )
    assert report["meta"]["log_parsed_lines"] == 2
    assert report["meta"]["log_confidence_eligible"] is False, (
        "a 2-record log spanning months must not be confidence-eligible "
        "even though its span alone clears the 30-day gate"
    )


def test_three_records_spanning_121_days_not_confidence_eligible(tmp_path):
    """Skeptic fixture 2: 3 records spanning 121 days -> log_coverage_days
    measured well above 30, still not enough parsed records to trust."""
    repo = _make_repo(tmp_path)
    now = datetime.now(timezone.utc)
    timestamps = [
        (now - timedelta(days=121)).isoformat().replace("+00:00", "Z"),
        (now - timedelta(days=60)).isoformat().replace("+00:00", "Z"),
        (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    ]
    _write(
        repo / ".agentic" / ".enforcement-fires.jsonl",
        "\n".join(
            json.dumps(
                {
                    "ts": ts,
                    "hook": "enforce-fake-abdication",
                    "decision": "allow",
                    "reason": "sparse",
                }
            )
            for ts in timestamps
        )
        + "\n",
    )
    report = _run_json(repo, "--days", "90")
    coverage = report["meta"]["log_coverage_days"]
    assert coverage is not None and coverage >= 30
    assert report["meta"]["log_parsed_lines"] == 3
    assert report["meta"]["log_confidence_eligible"] is False


def test_dense_recent_log_is_confidence_eligible(tmp_path):
    """Positive control for the density floor: a log with
    MIN_PARSED_LINES_FOR_CONFIDENCE (30) records spanning >= 30 real days
    IS confidence-eligible - proving the floor is reachable, not just a
    one-way gate.
    Mutation: raise MIN_PARSED_LINES_FOR_CONFIDENCE above 30 -> this test
    flips from True to False."""
    repo = _make_repo(tmp_path)
    now = datetime.now(timezone.utc)
    lines = []
    for i in range(30):
        ts = (now - timedelta(days=i)).isoformat().replace("+00:00", "Z")
        lines.append(
            json.dumps(
                {
                    "ts": ts,
                    "hook": "enforce-fake-abdication",
                    "decision": "allow",
                    "reason": f"day {i}",
                }
            )
        )
    _write(repo / ".agentic" / ".enforcement-fires.jsonl", "\n".join(lines) + "\n")
    report = _run_json(repo, "--days", "90")
    assert report["meta"]["log_parsed_lines"] == 30
    coverage = report["meta"]["log_coverage_days"]
    assert coverage is not None and coverage >= 29
    assert report["meta"]["log_confidence_eligible"] is True


# ---------------------------------------------------------------------------
# (f.2) DS-179 round 3 Major 2 - a majority-malformed log must not be
#     treated as a clean measurement even though log_effectively_empty is
#     False and a real hook status is reported.
#     Mutation: delete the `log_malformed_ratio <= MAX_MALFORMED_RATIO_FOR_CONFIDENCE`
#     conjunct from log_confidence_eligible's computation -> the assertion
#     below flips from False to True.
# ---------------------------------------------------------------------------


def test_majority_malformed_log_reported_and_realistic(tmp_path):
    """Skeptic's own executed reproduction, verbatim: 99 garbage lines + 1
    valid record. Pins the exact measured meta values from the round-3
    finding and confirms status logic is unaffected by (low) confidence
    eligibility - the hook still reports a real status derived from the one
    parsed line. Deliberately does NOT assert log_confidence_eligible here:
    with only 1 parsed line this fixture is already disqualified by the
    density conjunct alone and would not isolate the corruption conjunct -
    see test_high_malformed_ratio_disqualifies_a_dense_log below for that."""
    repo = _make_repo(tmp_path)
    lines = ["not json at all " + str(i) for i in range(99)]
    lines.append(
        json.dumps(
            {
                "ts": _RECENT_TS,
                "hook": "enforce-fake-abdication",
                "decision": "allow",
                "reason": "the one real line",
            }
        )
    )
    _write(repo / ".agentic" / ".enforcement-fires.jsonl", "\n".join(lines) + "\n")
    report = _run_json(repo)
    assert report["meta"]["log_effectively_empty"] is False
    assert report["meta"]["log_parsed_lines"] == 1
    assert report["meta"]["log_malformed_lines"] == 99
    assert report["meta"]["log_malformed_ratio"] == 0.99
    assert report["meta"]["log_confidence_eligible"] is False
    row = _row_for(report, "enforce-fake-abdication.py")
    assert row["status"] == "ACTIVE"


def test_high_malformed_ratio_disqualifies_a_dense_log(tmp_path):
    """Isolates the corruption conjunct from the density conjunct: a log
    with 40 malformed lines and 35 valid, dense, sufficiently-old parsed
    records (well past the 30-record density floor, well past 30 days of
    span) is STILL not confidence-eligible once malformed_ratio (40/75 ~
    0.53) exceeds MAX_MALFORMED_RATIO_FOR_CONFIDENCE (0.5) - proving the
    corruption check bites even when density and span both pass.
    Mutation: delete the `log_malformed_ratio <= MAX_MALFORMED_RATIO_FOR_CONFIDENCE`
    conjunct from log_confidence_eligible's computation -> this test flips
    from False to True (density and span alone would otherwise pass it)."""
    repo = _make_repo(tmp_path)
    now = datetime.now(timezone.utc)
    lines = ["garbage line " + str(i) for i in range(40)]
    for i in range(35):
        ts = (now - timedelta(days=i)).isoformat().replace("+00:00", "Z")
        lines.append(
            json.dumps(
                {
                    "ts": ts,
                    "hook": "enforce-fake-abdication",
                    "decision": "allow",
                    "reason": f"day {i}",
                }
            )
        )
    _write(repo / ".agentic" / ".enforcement-fires.jsonl", "\n".join(lines) + "\n")
    report = _run_json(repo, "--days", "90")
    assert report["meta"]["log_parsed_lines"] == 35
    assert report["meta"]["log_malformed_lines"] == 40
    assert report["meta"]["log_malformed_ratio"] > 0.5
    coverage = report["meta"]["log_coverage_days"]
    assert coverage is not None and coverage >= 30
    assert report["meta"]["log_confidence_eligible"] is False


def test_low_malformed_ratio_does_not_disqualify_confidence(tmp_path):
    """Positive control for the corruption ceiling: a log with a small
    minority of malformed lines (well under 50%) alongside enough dense,
    old-enough parsed records is confidence-eligible.
    Mutation: lower MAX_MALFORMED_RATIO_FOR_CONFIDENCE below the ratio used
    here -> this test flips from True to False."""
    repo = _make_repo(tmp_path)
    now = datetime.now(timezone.utc)
    lines = ["garbage"]
    for i in range(30):
        ts = (now - timedelta(days=i)).isoformat().replace("+00:00", "Z")
        lines.append(
            json.dumps(
                {
                    "ts": ts,
                    "hook": "enforce-fake-abdication",
                    "decision": "allow",
                    "reason": f"day {i}",
                }
            )
        )
    _write(repo / ".agentic" / ".enforcement-fires.jsonl", "\n".join(lines) + "\n")
    report = _run_json(repo, "--days", "90")
    assert report["meta"]["log_parsed_lines"] == 30
    assert report["meta"]["log_malformed_lines"] == 1
    assert report["meta"]["log_confidence_eligible"] is True


# ---------------------------------------------------------------------------
# (g) A record with an absent/unparseable ts counts toward
#     fire_count_all_time but never fire_count_window, and that gap is
#     now visible via fire_count_unparsed_ts rather than silent.
#     Mutation: stop incrementing fire_count_unparsed_ts (hardcode 0) ->
#     this test's assertion would fail.
# ---------------------------------------------------------------------------


def test_unparsed_ts_record_visible_via_unparsed_ts_count(tmp_path):
    repo = _make_repo(tmp_path)
    _write(
        repo / ".agentic" / ".enforcement-fires.jsonl",
        json.dumps(
            {
                "ts": "not-a-real-timestamp",
                "hook": "enforce-fake-abdication",
                "decision": "allow",
                "reason": "bad ts",
            }
        )
        + "\n",
    )
    report = _run_json(repo)
    row = _row_for(report, "enforce-fake-abdication.py")
    assert row["fire_count_all_time"] == 1
    assert row["fire_count_window"] == 0
    assert row["fire_count_unparsed_ts"] == 1


# ---------------------------------------------------------------------------
# Legend surfaces in both output modes.
# ---------------------------------------------------------------------------


def test_legend_present_in_json_and_table(tmp_path):
    repo = _make_repo(tmp_path)
    report = _run_json(repo)
    assert set(report["meta"]["legend"]) == {
        "UNMEASURED",
        "ZERO_INVOCATIONS",
        "ZERO_ACTION_IN_WINDOW",
        "ACTIVE",
    }
    assert "NOT proof" in report["meta"]["legend"]["ZERO_ACTION_IN_WINDOW"]

    table_proc = _run(repo)
    assert "Legend:" in table_proc.stdout
    assert "ZERO_ACTION_IN_WINDOW" in table_proc.stdout


# ---------------------------------------------------------------------------
# CLI surface sanity
# ---------------------------------------------------------------------------


def test_table_output_is_default_and_json_flag_switches_format(tmp_path):
    repo = _make_repo(tmp_path)
    table_proc = _run(repo)
    assert table_proc.returncode == 0
    assert "posture" in table_proc.stdout  # table header, not JSON
    report = _run_json(repo)
    assert isinstance(report, dict)
    assert isinstance(report["hooks"], list)


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
    report = _run_json(repo, "--days", "14")
    row = _row_for(report, "enforce-fake-abdication.py")
    assert row["fire_count_window"] == 0
    assert row["fire_count_all_time"] == 1
    assert row["status"] == "ZERO_INVOCATIONS"
