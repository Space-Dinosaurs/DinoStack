#!/usr/bin/env python3
"""
Tests for bin/ds-change-delta (DS-241). Loaded via
importlib.machinery.SourceFileLoader exactly like
bin/tests/test_agentic_cost_subcommands.py.

Run with: python3 bin/tests/test_ds_change_delta.py
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

_MOD_PATH = Path(__file__).parent.parent / "ds-change-delta"
_loader = importlib.machinery.SourceFileLoader("ds_change_delta", str(_MOD_PATH))
_spec = importlib.util.spec_from_loader("ds_change_delta", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for ds-change-delta from {_MOD_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

CUT_ISO = "2026-08-25T00:00:00+00:00"
CUT_DT = datetime.fromisoformat(CUT_ISO)
NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _session_row(ts: str, spawn: int, wall: int, tok_in: int, tok_out: int) -> dict:
    return {
        "ts": ts,
        "event": "session_total",
        "data": {
            "spawn_count": spawn,
            "wall_seconds": wall,
            "tokens": {
                "input": tok_in,
                "output": tok_out,
                "cache_creation": 0,
                "cache_read": 0,
            },
        },
    }


def _fire_row(ts: str, decision: str = "deny") -> dict:
    return {"hook": "h1", "ts": ts, "decision": decision}


def _build_primary_fixture(tmp: Path) -> Path:
    """Primary fixture per the plan: 3 before rows, 5 after rows (4 +
    boundary), a coverage-only row at after_end, and fires log with
    2 before / 6 after primary deny rows, a stranded copy with one
    exact duplicate and one genuinely new after-window deny row."""
    repo = tmp / "primary"
    session_rows = [
        _session_row("2026-08-11T00:00:00+00:00", 2, 100, 10, 5),   # before, = before_start
        _session_row("2026-08-18T00:00:00+00:00", 3, 200, 10, 5),   # before
        _session_row("2026-08-24T00:00:00+00:00", 4, 300, 10, 5),   # before
        _session_row(CUT_ISO, 3, 150, 8, 4),                          # boundary -> after
        _session_row("2026-08-26T00:00:00+00:00", 4, 200, 10, 5),   # after
        _session_row("2026-08-29T00:00:00+00:00", 5, 250, 12, 6),   # after
        _session_row("2026-09-01T00:00:00+00:00", 4, 200, 10, 5),   # after
        _session_row("2026-09-05T00:00:00+00:00", 4, 200, 10, 10),  # after
        _session_row("2026-09-08T00:00:00+00:00", 0, 0, 0, 0),      # coverage-only, = after_end
    ]
    _write_jsonl(repo / ".agentic" / "session-log" / "dev.jsonl", session_rows)

    primary_fires = [
        _fire_row("2026-08-11T00:00:00+00:00"),  # before, deny (1)
        _fire_row("2026-08-15T00:00:00+00:00", decision="allow_advisory"),  # before, NON-deny - must not count
        _fire_row("2026-08-20T00:00:00+00:00"),  # before, deny (2)
        _fire_row("2026-08-26T00:00:00+00:00"),  # after, deny (1)
        _fire_row("2026-08-27T00:00:00+00:00"),  # after, deny (2)
        _fire_row("2026-08-27T12:00:00+00:00", decision="allow"),  # after, NON-deny - must not count
        _fire_row("2026-08-28T00:00:00+00:00"),  # after, deny (3)
        _fire_row("2026-08-29T00:00:00+00:00"),  # after, deny (4)
        _fire_row("2026-08-30T00:00:00+00:00"),  # after, deny (5)
        _fire_row("2026-09-07T23:00:00+00:00"),  # after, deny (6)
        _fire_row("2026-09-08T00:00:00+00:00"),  # coverage-only, = after_end
    ]
    _write_jsonl(repo / ".agentic" / ".enforcement-fires.jsonl", primary_fires)

    # Stranded copy: line 0 is an EXACT duplicate of one primary after-window
    # deny line (must dedupe); line 1 is a genuinely new after-window deny
    # row (must count once); line 2 is a NON-deny row (must not count -
    # removing the stranded-loop deny filter must redden this).
    dup_line = json.dumps(_fire_row("2026-08-26T00:00:00+00:00"))
    new_line = json.dumps(_fire_row("2026-08-31T00:00:00+00:00"))
    stranded_non_deny_line = json.dumps(
        _fire_row("2026-08-27T06:00:00+00:00", decision="allow")
    )
    stranded_path = repo / ".claude" / "worktrees" / "agent-x" / ".agentic" / ".enforcement-fires.jsonl"
    stranded_path.parent.mkdir(parents=True, exist_ok=True)
    stranded_path.write_text(
        dup_line + "\n" + new_line + "\n" + stranded_non_deny_line + "\n", encoding="utf-8"
    )

    return repo


def _init_git_repo(repo: Path) -> str:
    """git init + one commit dated exactly CUT_ISO (author AND committer -
    GIT_COMMITTER_DATE must be set separately from --date, which sets only
    the author date). Returns the commit SHA."""
    env = dict(os.environ)
    env["GIT_AUTHOR_NAME"] = "Test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "Test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_DATE"] = CUT_ISO
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, env=env)
    subprocess.run(
        ["git", "commit", "-q", f"--date={CUT_ISO}", "-m", "fixture commit"],
        cwd=repo, check=True, env=env,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    return sha


def run_tests() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # ------------------------------------------------------------
        # Fixture-sanity: git committer date resolves exactly to CUT_ISO
        # ------------------------------------------------------------
        git_repo = tmp / "gitrepo"
        git_repo.mkdir()
        sha = _init_git_repo(git_repo)
        proc = subprocess.run(
            ["git", "-C", str(git_repo), "show", "-s", "--format=%cI", sha],
            capture_output=True, text=True, check=True,
        )
        parsed_committer_date = _mod._parse_ts(proc.stdout.strip())
        assert parsed_committer_date == CUT_DT, (
            f"Fixture sanity: git show returned {proc.stdout.strip()!r} "
            f"(parsed {parsed_committer_date}), expected {CUT_DT!r}"
        )
        print("Fixture sanity (git committer date == CUT_ISO): PASS")

        # ------------------------------------------------------------
        # _resolve_cut: SHA and date paths
        # ------------------------------------------------------------
        resolved_dt, resolved_src = _mod._resolve_cut(sha, str(git_repo))
        assert resolved_dt == CUT_DT, f"_resolve_cut(sha): got {resolved_dt}, want {CUT_DT}"
        assert resolved_src == f"sha:{sha}", f"_resolve_cut(sha) source: {resolved_src}"
        resolved_dt2, resolved_src2 = _mod._resolve_cut("2026-08-25", str(git_repo))
        assert resolved_src2 == "date:2026-08-25"
        try:
            _mod._resolve_cut("not-a-sha-or-date!!", str(git_repo))
            assert False, "expected CutResolutionError for malformed --cut"
        except _mod.CutResolutionError:
            pass
        # round-4 finding 1: a value that is SHA-shaped (7-40 hex chars)
        # but has no such commit, and is ALSO a valid compact ISO date,
        # must fall through to date parsing rather than being rejected -
        # git show is attempted first regardless of digit/letter shape,
        # and only a git-show FAILURE triggers the date-parsing fallback.
        # mutation: reintroducing the round-3 `(?!\d+$)` lookahead in
        # _SHA_RE, or swapping the try-git-then-date order, reddens this.
        resolved_dt3, resolved_src3 = _mod._resolve_cut("20260825", str(git_repo))
        assert resolved_src3 == "date:20260825", resolved_src3
        assert resolved_dt3 == CUT_DT.replace(hour=0, minute=0, second=0), resolved_dt3
        # round-4 finding 1: a REAL all-digit SHA (git show succeeds) must
        # resolve as `sha:`, never be diverted to date parsing just
        # because it is all-digit - 28 of 1163 commits on this repo's own
        # history have all-digit 8-char abbreviations. mutation: gating
        # the git-show attempt on "contains a non-digit character"
        # reddens this (the round-3 lookahead did exactly that).
        orig_run_sha_order = _mod._run

        def _mock_run_all_digit_sha(args, cwd=None, timeout=None):
            if args[:2] == ["git", "show"]:
                return subprocess.CompletedProcess(args, 0, stdout=CUT_ISO, stderr="")
            raise AssertionError(f"unexpected command: {args}")

        _mod._run = _mock_run_all_digit_sha
        try:
            resolved_dt4, resolved_src4 = _mod._resolve_cut("68267374", str(git_repo))
        finally:
            _mod._run = orig_run_sha_order
        assert resolved_src4 == "sha:68267374", resolved_src4
        assert resolved_dt4 == CUT_DT, resolved_dt4
        print("_resolve_cut (SHA / date / malformed / compact-digit-date / real-all-digit-sha): PASS")

        # ------------------------------------------------------------
        # CLI exit-code pin (finding 4, round 2): a --cut matching neither
        # shape is a CutResolutionError like any other unresolvable
        # --cut, and exits 1 - never a distinct exit 2 (exit 2 is
        # reserved for argparse's own usage errors, which never reach
        # main()'s body). No dedicated reddening mutation: this exercises
        # the same CutResolutionError path already mutation-tested above
        # via _resolve_cut directly, one layer up through main()'s
        # exception-to-exit-code mapping.
        # ------------------------------------------------------------
        rc_malformed = _mod.main(
            ["--cut", "not-a-sha-or-date!!", "--repo", str(git_repo)]
        )
        assert rc_malformed == 1, f"malformed --cut: expected exit 1, got {rc_malformed}"
        print("CLI exit code (malformed --cut -> exit 1): PASS")

        # ------------------------------------------------------------
        # --cut-repo default (finding 6, round 2): with no --cut-repo, the
        # SHA must be resolved against the first VALID --repo, not the
        # first positional --repo argument - a nonexistent first --repo
        # must not make cut resolution fail. mutation M: reverting
        # `cut_repo = args.cut_repo or str(valid_repos[0])` back to
        # `str(repo_paths[0])` reddens this (exit 1 instead of 0).
        # ------------------------------------------------------------
        rc_default_cut_repo = _mod.main(
            ["--cut", sha, "--repo", str(tmp / "does-not-exist"), "--repo", str(git_repo), "--json"]
        )
        assert rc_default_cut_repo == 0, (
            f"--cut-repo default should resolve against the first VALID --repo "
            f"(skipping a nonexistent one), got exit {rc_default_cut_repo}"
        )
        print("--cut-repo default (skips a nonexistent first --repo): PASS")

        # ------------------------------------------------------------
        # Primary fixture + assertions 1, 2, 3, 4a, 4b
        # ------------------------------------------------------------
        primary = _build_primary_fixture(tmp)
        report = _mod.build_delta([primary], CUT_DT, 14, now=NOW)
        m = report["metrics"]

        # Assertion 1: sessions
        assert m["sessions"]["before"]["status"] == "OK"
        assert m["sessions"]["before"]["value"] == 3, m["sessions"]["before"]
        assert m["sessions"]["after"]["status"] == "OK"
        assert m["sessions"]["after"]["value"] == 5, m["sessions"]["after"]
        assert m["sessions"]["delta"] == 2
        print("Assertion 1 (sessions before=3 after=5 delta=2): PASS")

        # Assertion 2: spawns_per_session
        sp = m["spawns_per_session"]
        assert sp["before"]["value"] == 3.0, sp["before"]
        assert sp["after"]["value"] == 4.0, sp["after"]
        assert sp["delta"] == 1.0, sp["delta"]
        print("Assertion 2 (spawns_per_session before=3.0 after=4.0 delta=1.0): PASS")

        # Assertion 3: hook_denies_per_session exact deny counts
        hd = m["hook_denies_per_session"]
        assert hd["before"]["status"] == "OK", hd["before"]
        assert hd["after"]["status"] == "OK", hd["after"]
        assert hd["before"]["note"] is None
        assert hd["after"]["note"] is None
        # before deny count == 2 -> value = 2/3
        assert abs(hd["before"]["value"] - (2 / 3)) < 1e-9, hd["before"]
        # after deny count == 7 (6 primary + 1 new stranded, dup dropped) -> value = 7/5
        assert abs(hd["after"]["value"] - (7 / 5)) < 1e-9, hd["after"]
        # rows_consumed is split per store (finding 5) - both the fires
        # numerator and the session-log denominator must be visible.
        assert hd["before"]["rows_consumed"] == {"fires": 2, "sessions": 3}, hd["before"]
        assert hd["after"]["rows_consumed"] == {"fires": 7, "sessions": 5}, hd["after"]
        print("Assertion 3 (hook_denies_per_session before-deny=2 after-deny=7, OK/OK, note=None): PASS")

        # Assertion 4a: wall_seconds_per_session
        ws = m["wall_seconds_per_session"]
        assert ws["before"]["value"] == 200.0, ws["before"]
        assert ws["after"]["value"] == 200.0, ws["after"]
        assert ws["delta"] == 0.0, ws["delta"]
        assert ws["data_quality"] is None, ws["data_quality"]
        print("Assertion 4a (wall_seconds_per_session real zero delta 200.0/200.0): PASS")

        # Assertion 4b: tokens_per_session
        tp = m["tokens_per_session"]
        assert tp["before"]["value"] == 15.0, tp["before"]  # 45/3
        assert tp["after"]["value"] == 16.0, tp["after"]    # 80/5
        assert tp["delta"] == 1.0, tp["delta"]
        assert tp["data_quality"] is None, tp["data_quality"]
        print("Assertion 4b (tokens_per_session nonzero unequal 15.0/16.0, data_quality=None): PASS")

        # ------------------------------------------------------------
        # Assertion 3b: fires log present, session-log absent for one repo
        # ------------------------------------------------------------
        degraded_repo = tmp / "degraded"
        _write_jsonl(
            degraded_repo / ".agentic" / ".enforcement-fires.jsonl",
            [_fire_row("2026-08-12T00:00:00+00:00"), _fire_row("2026-08-26T00:00:00+00:00")],
        )
        report_3b = _mod.build_delta([degraded_repo], CUT_DT, 14, now=NOW)
        hd_3b = report_3b["metrics"]["hook_denies_per_session"]
        assert hd_3b["after"]["status"] == "ABSENT", hd_3b["after"]
        assert "session-log" in (hd_3b["after"]["note"] or ""), hd_3b["after"]["note"]
        print("Assertion 3b (hook_denies_per_session degrades to ABSENT, session-log named): PASS")

        # ------------------------------------------------------------
        # Assertion 3c [NEW - finding 1]: fires log genuinely covers both
        # windows (earliest/latest span before_start..after_end) but has
        # ZERO deny rows in the after window (only a non-deny row there).
        # Coverage must be judged on the WHOLE store, not the deny-only
        # subset - after.status must be OK with value 0.0, never
        # INSUFFICIENT_COVERAGE/ABSENT just because no denies landed
        # after the cut.
        # ------------------------------------------------------------
        zero_deny_repo = tmp / "zero_post_cut_deny"
        zero_deny_sessions = [
            _session_row("2026-08-11T00:00:00+00:00", 2, 100, 10, 5),
            _session_row(CUT_ISO, 3, 100, 10, 5),
            _session_row("2026-09-08T00:00:00+00:00", 0, 0, 0, 0),  # coverage-only
        ]
        _write_jsonl(zero_deny_repo / ".agentic" / "session-log" / "dev.jsonl", zero_deny_sessions)
        zero_deny_fires = [
            _fire_row("2026-08-11T00:00:00+00:00"),  # before, deny - anchors earliest
            _fire_row("2026-08-26T00:00:00+00:00", decision="allow"),  # after, NON-deny
            _fire_row("2026-09-08T00:00:00+00:00", decision="allow"),  # coverage-only, anchors latest
        ]
        _write_jsonl(zero_deny_repo / ".agentic" / ".enforcement-fires.jsonl", zero_deny_fires)
        report_3c = _mod.build_delta([zero_deny_repo], CUT_DT, 14, now=NOW)
        hd_3c = report_3c["metrics"]["hook_denies_per_session"]
        assert hd_3c["after"]["status"] == "OK", hd_3c["after"]
        assert hd_3c["after"]["value"] == 0.0, hd_3c["after"]
        print("Assertion 3c (fires log covers both windows, zero post-cut denies -> after.status=OK, value=0.0): PASS")

        # ------------------------------------------------------------
        # Assertion 5: both-sided zero-filled
        # ------------------------------------------------------------
        zf_repo = tmp / "zerofilled"
        zf_rows = [
            _session_row("2026-08-11T00:00:00+00:00", 2, 0, 0, 0),
            _session_row("2026-08-20T00:00:00+00:00", 3, 0, 0, 0),
            _session_row("2026-08-26T00:00:00+00:00", 4, 0, 0, 0),
            _session_row("2026-09-08T00:00:00+00:00", 0, 0, 0, 0),  # coverage
        ]
        _write_jsonl(zf_repo / ".agentic" / "session-log" / "dev.jsonl", zf_rows)
        report_zf = _mod.build_delta([zf_repo], CUT_DT, 14, now=NOW)
        for key in ("wall_seconds_per_session", "tokens_per_session"):
            entry = report_zf["metrics"][key]
            assert entry["data_quality"] == "zero-filled", (key, entry)
            assert entry["delta"] is None, (key, entry)
        print("Assertion 5 (both-sided zero-filled -> data_quality='zero-filled', delta=None): PASS")

        # ------------------------------------------------------------
        # Assertion 6: before-side INSUFFICIENT_COVERAGE, after-side OK
        # ------------------------------------------------------------
        cov_repo = tmp / "coverage"
        cov_rows = [
            _session_row("2026-08-26T00:00:00+00:00", 3, 100, 10, 5),  # inside after window
            _session_row("2026-09-08T00:00:00+00:00", 2, 100, 10, 5),  # at/after after_window_end
        ]
        _write_jsonl(cov_repo / ".agentic" / "session-log" / "dev.jsonl", cov_rows)
        report_cov = _mod.build_delta([cov_repo], CUT_DT, 14, now=NOW)
        sessions_cov = report_cov["metrics"]["sessions"]
        assert sessions_cov["before"]["status"] == "INSUFFICIENT_COVERAGE", sessions_cov["before"]
        assert sessions_cov["before"]["value"] is None, (
            "sessions.before.value must be null under INSUFFICIENT_COVERAGE, "
            f"not a bare numeric count: {sessions_cov['before']}"
        )
        assert sessions_cov["after"]["status"] == "OK", sessions_cov["after"]
        print("Assertion 6 (before INSUFFICIENT_COVERAGE -> value=None, after OK): PASS")

        # ------------------------------------------------------------
        # Assertion 6b [NEW]: after-side INSUFFICIENT_COVERAGE (finding 7) -
        # the after side's latest row sits STRICTLY INSIDE the after window
        # (never at/after after_window_end), so the after side's own
        # coverage check must independently fail. Every other fixture's
        # latest row sits exactly at after_end, which never exercises this
        # branch - flipping `latest_ts < window_end` to `>` would survive
        # the suite without this fixture.
        # ------------------------------------------------------------
        after_cov_repo = tmp / "after_coverage"
        after_cov_rows = [
            _session_row("2026-08-11T00:00:00+00:00", 2, 100, 10, 5),  # before, covers before_start
            _session_row("2026-08-26T00:00:00+00:00", 3, 100, 10, 5),  # after, strictly inside - latest row
        ]
        _write_jsonl(after_cov_repo / ".agentic" / "session-log" / "dev.jsonl", after_cov_rows)
        report_after_cov = _mod.build_delta([after_cov_repo], CUT_DT, 14, now=NOW)
        sessions_after_cov = report_after_cov["metrics"]["sessions"]
        assert sessions_after_cov["after"]["status"] == "INSUFFICIENT_COVERAGE", sessions_after_cov["after"]
        assert sessions_after_cov["after"]["value"] is None, sessions_after_cov["after"]
        print("Assertion 6b (after-side INSUFFICIENT_COVERAGE when latest row is strictly inside the window): PASS")

        # ------------------------------------------------------------
        # Assertion 7: cut = today -> NOT_YET_ELAPSED
        # ------------------------------------------------------------
        today_repo = tmp / "today"
        today_cut = NOW
        today_rows = [
            _session_row((today_cut - _mod.timedelta(days=1)).isoformat(), 3, 100, 10, 5),
            _session_row((today_cut - _mod.timedelta(days=13)).isoformat(), 2, 100, 10, 5),
        ]
        _write_jsonl(today_repo / ".agentic" / "session-log" / "dev.jsonl", today_rows)
        report_today = _mod.build_delta([today_repo], today_cut, 14, now=NOW)
        for key in ("sessions", "spawns_per_session", "tokens_per_session", "wall_seconds_per_session"):
            entry = report_today["metrics"][key]
            assert entry["after"]["status"] == "NOT_YET_ELAPSED", (key, entry["after"])
            assert entry["delta"] is None, (key, entry["delta"])
            # Deliberate deviation from the plan's "still reports an
            # informational value" text (finding 6, not editing the
            # plan file): the shipped code nulls the value on every
            # non-OK status including NOT_YET_ELAPSED, for consistency
            # with how the ratio metrics already treat every other
            # non-OK status - see content/commands/ds-change-delta.md.
            assert entry["after"]["value"] is None, (key, entry["after"])
        print("Assertion 7 (cut=today -> after.status=NOT_YET_ELAPSED, delta=None, value=None): PASS")

        # ------------------------------------------------------------
        # Assertion 8: coverage spans both windows, zero session_total in after
        # ------------------------------------------------------------
        zs_repo = tmp / "zerosessions"
        zs_rows = [
            _session_row("2026-08-11T00:00:00+00:00", 2, 100, 10, 5),
            _session_row("2026-08-20T00:00:00+00:00", 3, 100, 10, 5),
            _session_row("2026-09-08T00:00:00+00:00", 2, 100, 10, 5),  # coverage only
        ]
        _write_jsonl(zs_repo / ".agentic" / "session-log" / "dev.jsonl", zs_rows)
        report_zs = _mod.build_delta([zs_repo], CUT_DT, 14, now=NOW)
        sessions_zs = report_zs["metrics"]["spawns_per_session"]
        assert sessions_zs["after"]["status"] == "ZERO_SESSIONS", sessions_zs["after"]
        assert sessions_zs["after"]["value"] is None
        assert sessions_zs["delta"] is None
        print("Assertion 8 (after.status=ZERO_SESSIONS, value=None, delta=None): PASS")

        # ------------------------------------------------------------
        # Assertion 10: after-window all-zero wall_seconds while before real
        # ------------------------------------------------------------
        zfa_repo = tmp / "zerofilledafter"
        zfa_rows = [
            _session_row("2026-08-11T00:00:00+00:00", 2, 100, 10, 5),
            _session_row("2026-08-20T00:00:00+00:00", 3, 200, 10, 5),
            _session_row("2026-08-26T00:00:00+00:00", 4, 0, 10, 5),
            _session_row("2026-09-08T00:00:00+00:00", 2, 0, 10, 5),  # coverage
        ]
        _write_jsonl(zfa_repo / ".agentic" / "session-log" / "dev.jsonl", zfa_rows)
        report_zfa = _mod.build_delta([zfa_repo], CUT_DT, 14, now=NOW)
        wsa = report_zfa["metrics"]["wall_seconds_per_session"]
        assert wsa["data_quality"] == "zero-filled-after", wsa
        assert wsa["delta"] is None, wsa
        print("Assertion 10 (after-only zero-filled -> data_quality='zero-filled-after', delta=None): PASS")

        # ------------------------------------------------------------
        # Assertion 11: multi-repo merge, one repo has no session-log dir
        # ------------------------------------------------------------
        mr_covering = tmp / "mr_covering"
        mr_rows = [
            _session_row("2026-08-11T00:00:00+00:00", 2, 100, 10, 5),
            _session_row("2026-08-26T00:00:00+00:00", 3, 100, 10, 5),
            _session_row("2026-09-08T00:00:00+00:00", 2, 100, 10, 5),
        ]
        _write_jsonl(mr_covering / ".agentic" / "session-log" / "dev.jsonl", mr_rows)
        mr_empty = tmp / "mr_empty"
        (mr_empty / ".agentic").mkdir(parents=True)  # no session-log/ subdir at all
        report_mr = _mod.build_delta([mr_covering, mr_empty], CUT_DT, 14, now=NOW)
        sessions_mr = report_mr["metrics"]["sessions"]
        assert sessions_mr["before"]["status"] == "OK", sessions_mr["before"]
        expected_source = [str(mr_covering / ".agentic" / "session-log" / "dev.jsonl")]
        assert sessions_mr["before"]["source"] == expected_source, sessions_mr["before"]["source"]
        assert sessions_mr["before"]["rows_consumed"] == 1, sessions_mr["before"]
        print("Assertion 11 (multi-repo merge: source omits non-contributing repo, status OK): PASS")

        # ------------------------------------------------------------
        # Assertion 11b [NEW - round-4 finding 2]: passing the SAME repo
        # twice via --repo (once as-given, once as its resolved absolute
        # form) must contribute its rows ONCE, not twice - dedup happens
        # in main(), so this drives the CLI layer directly rather than
        # build_delta(). mutation: dropping the dict.fromkeys(...) dedup
        # (or the .resolve() call feeding it) reddens this - sessions
        # would double from 3 to 6.
        # ------------------------------------------------------------
        dedup_repo = tmp / "dedup_repo"
        dedup_rows = [
            _session_row("2026-08-11T00:00:00+00:00", 2, 100, 10, 5),
            _session_row("2026-08-18T00:00:00+00:00", 3, 100, 10, 5),
            _session_row("2026-08-24T00:00:00+00:00", 4, 100, 10, 5),
        ]
        _write_jsonl(dedup_repo / ".agentic" / "session-log" / "dev.jsonl", dedup_rows)
        buf = StringIO()
        orig_stdout = sys.stdout
        sys.stdout = buf
        try:
            rc_dedup = _mod.main([
                "--cut", CUT_ISO,
                "--repo", str(dedup_repo),
                "--repo", str(dedup_repo) + os.sep + ".",
                "--json",
            ])
        finally:
            sys.stdout = orig_stdout
        assert rc_dedup == 0, rc_dedup
        dedup_report = json.loads(buf.getvalue())
        assert dedup_report["metrics"]["sessions"]["before"]["value"] == 3, (
            f"same repo passed twice must not double-count sessions: "
            f"{dedup_report['metrics']['sessions']['before']}"
        )
        print("Assertion 11b (same --repo passed twice is deduped, not double-counted): PASS")

        # ------------------------------------------------------------
        # Assertion 9: PR history via mocked gh
        # ------------------------------------------------------------
        orig_run = _mod._run

        def _page(nodes, has_next, cursor, issue_count):
            return {
                "data": {
                    "search": {
                        "issueCount": issue_count,
                        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                        "nodes": nodes,
                    }
                }
            }

        call_log: list[list[str]] = []

        def _mock_run_two_page(args, cwd=None, timeout=None):
            call_log.append(args)
            if args[:2] == ["gh", "repo"]:
                return subprocess.CompletedProcess(
                    args, 0, stdout=json.dumps({"nameWithOwner": "acme/widgets"}), stderr=""
                )
            if args[:2] == ["gh", "api"]:
                # Determine which page via presence of endCursor
                has_cursor = any(a.startswith("endCursor=") for a in args)
                if not has_cursor:
                    payload = _page(
                        [{"number": 1, "mergedAt": "x", "commits": {"totalCount": 3}}],
                        True, "CURSOR1", 2,
                    )
                else:
                    payload = _page(
                        [{"number": 2, "mergedAt": "x", "commits": {"totalCount": 5}}],
                        False, None, 2,
                    )
                return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
            raise AssertionError(f"unexpected command: {args}")

        _mod._run = _mock_run_two_page
        try:
            before_pr = _mod._fetch_pr_window(
                str(tmp), "acme", "widgets",
                CUT_DT - _mod.timedelta(days=14), CUT_DT, NOW,
            )
        finally:
            _mod._run = orig_run
        assert before_pr["status"] == "OK", before_pr
        assert before_pr["merged_prs"] == 2, before_pr
        assert before_pr["commits"] == 8, before_pr
        assert before_pr["commits_per_pr"] == 4.0, before_pr
        print("Assertion 9a (PR history two-page fetch: merged_prs=2 commits=8 commits_per_pr=4.0): PASS")

        def _mock_run_dropped_page(args, cwd=None, timeout=None):
            if args[:2] == ["gh", "repo"]:
                return subprocess.CompletedProcess(
                    args, 0, stdout=json.dumps({"nameWithOwner": "acme/widgets"}), stderr=""
                )
            if args[:2] == ["gh", "api"]:
                payload = _page(
                    [{"number": 1, "mergedAt": "x", "commits": {"totalCount": 3}}],
                    False, None, 5,  # issueCount=5 but only 1 node retrieved
                )
                return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
            raise AssertionError(f"unexpected command: {args}")

        _mod._run = _mock_run_dropped_page
        try:
            dropped = _mod._fetch_pr_window(
                str(tmp), "acme", "widgets",
                CUT_DT - _mod.timedelta(days=14), CUT_DT, NOW,
            )
        finally:
            _mod._run = orig_run
        assert dropped["status"] == "INCOMPLETE_WINDOW", dropped
        print("Assertion 9b (PR history dropped-page: status=INCOMPLETE_WINDOW): PASS")

        # ------------------------------------------------------------
        # Assertion 9c [NEW - finding 2]: half-open PR windows - a PR merged
        # exactly at the cut instant must be reachable by the after
        # window's query and NOT by the before window's query. GitHub's
        # `merged:A..B` range is inclusive on both ends, so the two
        # queries' boundary instants must differ by one second, never
        # share the literal cut instant.
        # ------------------------------------------------------------
        captured_queries: list[str] = []

        def _mock_run_capture_query(args, cwd=None, timeout=None):
            if args[:2] == ["gh", "repo"]:
                return subprocess.CompletedProcess(
                    args, 0, stdout=json.dumps({"nameWithOwner": "acme/widgets"}), stderr=""
                )
            if args[:2] == ["gh", "api"]:
                # The search-string arg is "q=...", distinct from the
                # GraphQL query-text arg "query=..." (which contains no
                # "merged:" literal at all - matching on "query=" here
                # would silently find nothing).
                q_arg = next((a for a in args if a.startswith("q=")), "")
                q_match = re.search(r"merged:(\S+)\.\.(\S+)", q_arg)
                captured_queries.append(
                    (q_match.group(1), q_match.group(2)) if q_match else (None, None)
                )
                payload = _page([], False, None, 0)
                return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
            raise AssertionError(f"unexpected command: {args}")

        _mod._run = _mock_run_capture_query
        try:
            _mod._pr_history_for_repo(
                str(tmp), CUT_DT - _mod.timedelta(days=14), CUT_DT,
                CUT_DT, CUT_DT + _mod.timedelta(days=14), NOW,
            )
        finally:
            _mod._run = orig_run
        assert len(captured_queries) == 2, captured_queries
        before_start_q, before_end_q = captured_queries[0]
        after_start_q, after_end_q = captured_queries[1]
        cut_str = _mod._gh_search_datetime(CUT_DT)
        assert before_end_q != cut_str, (
            f"before window's end must NOT be the literal cut instant "
            f"(that double-counts a PR merged exactly at the cut): {before_end_q}"
        )
        assert after_start_q == cut_str, (
            f"after window's start must be the literal cut instant: {after_start_q}"
        )
        before_end_dt = datetime.strptime(before_end_q, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        assert before_end_dt == CUT_DT - _mod.timedelta(seconds=1), (
            f"before window's end must be exactly one second before the cut: {before_end_q}"
        )
        print("Assertion 9c (half-open PR windows: before-end = cut-1s, after-start = cut): PASS")

        # ------------------------------------------------------------
        # Assertion 9d [NEW - finding 2]: GH_UNAVAILABLE (a real repo with
        # an origin remote that gh cannot resolve) vs NOT_A_GIT_REPO (no
        # origin remote at all) must be distinguished, never collapsed.
        # ------------------------------------------------------------
        has_origin_repo = tmp / "has_origin"
        has_origin_repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=has_origin_repo, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/example/unreachable.git"],
            cwd=has_origin_repo, check=True,
        )
        no_origin_repo = tmp / "no_origin"
        no_origin_repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=no_origin_repo, check=True)

        def _mock_run_gh_erroring(args, cwd=None, timeout=None):
            if args[:2] == ["git", "remote"]:
                # Let the real git command run - it reflects the real
                # per-fixture remote configuration set up above.
                return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
            if args[:2] == ["gh", "repo"]:
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="gh: authentication error")
            raise AssertionError(f"unexpected command: {args}")

        _mod._run = _mock_run_gh_erroring
        try:
            result_has_origin = _mod._pr_history_for_repo(
                str(has_origin_repo), CUT_DT - _mod.timedelta(days=14), CUT_DT,
                CUT_DT, CUT_DT + _mod.timedelta(days=14), NOW,
            )
            result_no_origin = _mod._pr_history_for_repo(
                str(no_origin_repo), CUT_DT - _mod.timedelta(days=14), CUT_DT,
                CUT_DT, CUT_DT + _mod.timedelta(days=14), NOW,
            )
        finally:
            _mod._run = orig_run
        assert result_has_origin["before"]["status"] == "GH_UNAVAILABLE", result_has_origin["before"]
        assert result_no_origin["before"]["status"] == "NOT_A_GIT_REPO", result_no_origin["before"]
        print("Assertion 9d (origin-remote-but-gh-erroring -> GH_UNAVAILABLE; no-origin -> NOT_A_GIT_REPO): PASS")

        # ------------------------------------------------------------
        # R5: read-only guarantee - argv allowlist + HEAD/status byte-identity
        # ------------------------------------------------------------
        readonly_repo = tmp / "readonly"
        readonly_repo.mkdir()
        ro_sha = _init_git_repo(readonly_repo)
        _write_jsonl(
            readonly_repo / ".agentic" / "session-log" / "dev.jsonl",
            [_session_row("2026-08-11T00:00:00+00:00", 2, 100, 10, 5)],
        )

        head_before = subprocess.run(
            ["git", "-C", str(readonly_repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout
        status_before = subprocess.run(
            ["git", "-C", str(readonly_repo), "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout

        recorded_argv: list[tuple[str, str]] = []
        real_run = _mod._run

        def _recording_run(args, cwd=None, timeout=None):
            recorded_argv.append(tuple(args[:2]))
            return real_run(args, cwd=cwd, timeout=timeout)

        _mod._run = _recording_run
        try:
            rc = _mod.main(["--cut", ro_sha, "--cut-repo", str(readonly_repo),
                             "--repo", str(readonly_repo), "--json"])
        finally:
            _mod._run = real_run
        assert rc == 0, rc

        allowlist = {("git", "show"), ("git", "rev-parse"), ("git", "remote"),
                     ("gh", "repo"), ("gh", "api")}
        for argv in recorded_argv:
            assert argv in allowlist, f"non-allowlisted subprocess call: {argv}"
        assert recorded_argv, "expected at least one recorded subprocess call"

        head_after = subprocess.run(
            ["git", "-C", str(readonly_repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout
        status_after = subprocess.run(
            ["git", "-C", str(readonly_repo), "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout
        assert head_before == head_after, "HEAD changed across a ds-change-delta run"
        assert status_before == status_after, "working tree status changed across a ds-change-delta run"
        print("R5 (read-only guarantee: argv allowlist + HEAD/status byte-identity): PASS")

        print("\nAll ds-change-delta tests passed.")


def test_ds_change_delta_regression_suite() -> None:
    """pytest collection entrypoint - runs the full assertion suite above."""
    run_tests()


if __name__ == "__main__":
    run_tests()
