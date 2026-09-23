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
            if args[:2] == ["git", "rev-parse"]:
                # round-5 finding 2: _resolve_cut verifies the object is a
                # commit before calling git show.
                return subprocess.CompletedProcess(args, 0, stdout="68267374\n", stderr="")
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
        # round-5 finding 2: `git show -s --format=%cI <blob-sha>` exits 0
        # and prints the raw object CONTENTS (not a date) for a non-commit
        # object - a blob SHA must fall through to date parsing (it has no
        # ISO form, so it ultimately fails with a SHORT error message, not
        # one containing the blob's contents), and `git show` must never
        # even be INVOKED on a confirmed non-commit object (the
        # `git rev-parse --verify --quiet <sha>^{commit}` gate runs first).
        # mutation: reverting the gate to trust git show's rc==0 alone
        # (`is_commit = True` unconditionally) reddens the call-count
        # assertion below - git show gets called on the blob when it
        # should not be.
        # ------------------------------------------------------------
        blob_sha = subprocess.run(
            ["git", "rev-parse", f"{sha}:README.md"],
            cwd=git_repo, check=True, capture_output=True, text=True,
        ).stdout.strip()
        try:
            _mod._resolve_cut(blob_sha, str(git_repo))
            assert False, "expected CutResolutionError for a blob SHA"
        except _mod.CutResolutionError as exc:
            assert len(str(exc)) < 200, f"error message too long (blob contents leaked?): {len(str(exc))} chars"

        blob_call_log: list[tuple[str, ...]] = []
        orig_run_blob_gate = _mod._run

        def _tracking_run(args, cwd=None, timeout=None):
            blob_call_log.append(tuple(args[:2]))
            return orig_run_blob_gate(args, cwd=cwd, timeout=timeout)

        _mod._run = _tracking_run
        try:
            try:
                _mod._resolve_cut(blob_sha, str(git_repo))
            except _mod.CutResolutionError:
                pass
        finally:
            _mod._run = orig_run_blob_gate
        assert ("git", "show") not in blob_call_log, (
            f"git show must never be called on a confirmed non-commit object: {blob_call_log}"
        )
        print("_resolve_cut (blob SHA falls through to date parsing, git show never invoked): PASS")

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
        # round-6 finding 2: an oversized --window-days must exit 2 with a
        # usage message, never let cut_dt +/- window_days overflow
        # datetime's range as an uncaught OverflowError (contradicting the
        # manifest's "never a traceback" claim). mutation: raising
        # MAX_WINDOW_DAYS above what cut_dt +/- it can represent (or
        # deleting the check) reddens this - main() would instead crash
        # with an uncaught OverflowError instead of returning 2.
        # ------------------------------------------------------------
        rc_overflow = _mod.main(
            ["--cut", "2026-01-01", "--window-days", "99999999", "--repo", str(git_repo)]
        )
        assert rc_overflow == 2, f"oversized --window-days: expected exit 2, got {rc_overflow}"
        print("CLI exit code (--window-days 99999999 -> exit 2, no OverflowError): PASS")

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
        # Assertion 11b [NEW - round-4 finding 2, comment corrected -
        # round-5 finding 4]: passing the SAME repo twice via --repo
        # (once as-given with a trailing "/.", once plain) must
        # contribute its rows ONCE, not twice - dedup happens in main(),
        # so this drives the CLI layer directly rather than build_delta().
        # mutation: dropping the dict.fromkeys(...) dedup reddens this -
        # sessions would double from 3 to 6. NOTE: dropping the .resolve()
        # call feeding it does NOT redden this specific case - pathlib
        # already normalizes a trailing "/." at Path() construction time
        # (Path("/a/b") == Path("/a/b/.") with no .resolve() involved,
        # verified live) - see the SEPARATE case directly below, which
        # passes literal "." with cwd set to the fixture repo, for the
        # case that actually requires .resolve().
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
        # Assertion 11c [NEW - round-5 finding 4]: the REAL case that
        # requires .resolve() - a literal "." (relative to cwd) and the
        # same repo's absolute path must dedupe to one contributor.
        # mutation: dropping the .resolve() call (keeping dict.fromkeys)
        # reddens this specifically - "." and the absolute path are
        # different, unequal Path objects until resolved, so sessions
        # would double from 3 to 6.
        # ------------------------------------------------------------
        buf_dot = StringIO()
        orig_stdout_dot = sys.stdout
        orig_cwd = os.getcwd()
        sys.stdout = buf_dot
        try:
            os.chdir(dedup_repo)
            rc_dedup_dot = _mod.main([
                "--cut", CUT_ISO,
                "--repo", ".",
                "--repo", str(dedup_repo),
                "--json",
            ])
        finally:
            os.chdir(orig_cwd)
            sys.stdout = orig_stdout_dot
        assert rc_dedup_dot == 0, rc_dedup_dot
        dedup_dot_report = json.loads(buf_dot.getvalue())
        assert dedup_dot_report["metrics"]["sessions"]["before"]["value"] == 3, (
            f"'.' (cwd) and the same repo's absolute path must dedupe: "
            f"{dedup_dot_report['metrics']['sessions']['before']}"
        )
        print("Assertion 11c ('.' with cwd set to the fixture repo dedupes against its absolute path): PASS")

        # ------------------------------------------------------------
        # Assertion 12 [NEW - round-5 finding 1]: multi-repo-union-extent-
        # masks-coverage. Repo A brackets both windows (truth: sessions
        # 2 -> 1). Repo B's telemetry only starts AFTER the cut (as if
        # newly onboarded) but reaches the same after_end coverage
        # anchor as A. A UNION extent would let A's early start mask B's
        # late start, reporting OK/OK with before=2, after=5 (2 from A's
        # own after-window row plus B's 4) - the exact reviewer
        # reproduction. The INTERSECTION extent must instead report
        # INSUFFICIENT_COVERAGE on the before side (B's own extent never
        # reaches before_start) with delta null, and name repo B in the
        # note. mutation: reverting _intersect_repo_extents to a plain
        # min(earliest)/max(latest) union reddens this - before.status
        # goes back to OK and delta becomes a real (masked) number.
        # ------------------------------------------------------------
        union_mask_a = tmp / "union_mask_repo_a"
        union_mask_a_rows = [
            _session_row("2026-08-11T00:00:00+00:00", 1, 100, 10, 5),  # before, brackets before_start
            _session_row("2026-08-24T00:00:00+00:00", 1, 100, 10, 5),  # before
            _session_row("2026-08-26T00:00:00+00:00", 1, 100, 10, 5),  # after
            _session_row("2026-09-08T00:00:00+00:00", 0, 0, 0, 0),     # coverage-only, = after_end
        ]
        _write_jsonl(union_mask_a / ".agentic" / "session-log" / "dev.jsonl", union_mask_a_rows)
        union_mask_b = tmp / "union_mask_repo_b"
        union_mask_b_rows = [
            _session_row("2026-08-27T00:00:00+00:00", 1, 100, 10, 5),  # after - B's OWN earliest, post-cut
            _session_row("2026-08-28T00:00:00+00:00", 1, 100, 10, 5),  # after
            _session_row("2026-08-30T00:00:00+00:00", 1, 100, 10, 5),  # after
            _session_row("2026-09-01T00:00:00+00:00", 1, 100, 10, 5),  # after
            _session_row("2026-09-08T00:00:00+00:00", 0, 0, 0, 0),     # coverage-only, = after_end (matches A)
        ]
        _write_jsonl(union_mask_b / ".agentic" / "session-log" / "dev.jsonl", union_mask_b_rows)
        report_union_mask = _mod.build_delta([union_mask_a, union_mask_b], CUT_DT, 14, now=NOW)
        sessions_union_mask = report_union_mask["metrics"]["sessions"]
        assert sessions_union_mask["before"]["status"] == "INSUFFICIENT_COVERAGE", sessions_union_mask["before"]
        assert sessions_union_mask["before"]["value"] is None, sessions_union_mask["before"]
        assert sessions_union_mask["delta"] is None, sessions_union_mask["delta"]
        assert str(union_mask_b) in (sessions_union_mask["before"]["note"] or ""), sessions_union_mask["before"]["note"]
        print("Assertion 12 (multi-repo intersection extent: late-starting repo B degrades before-side coverage): PASS")

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


# ---------------------------------------------------------------------------
# DS-246: agent_model and per_ticket over telemetry_v 2 hook spawn rows.
# Windows: before [08-11, 08-25), after [08-25, 09-08); v2 extent 08-10..09-09.
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent))
import telemetry_v2_fixtures as fx

_T = fx.tokens


def _legacy_start(ts: str, agent: str, spawn_id: str, task_id: str) -> dict:
    row = fx.v2_start(ts, agent, spawn_id, task_id)
    del row["data"]["telemetry_v"]
    return row


def _ticket_fixture_events() -> list[dict]:
    return [
        # pre-DS-246 rows inside the after window: must never contribute
        _legacy_start("2026-08-28T05:00:00Z", "engineer", "leg1", "AUT-LEG"),
        fx.legacy_complete("2026-08-28T06:00:00Z", "engineer", "leg1", "AUT-LEG",
                           cumulative=_T(input=5)),
        # coverage anchors (no ticket)
        fx.v2_start("2026-08-10T00:00:00Z", "investigator", "anchor-a"),
        fx.v2_start("2026-09-09T00:00:00Z", "investigator", "anchor-b"),
        # before: AUT-580 / AUT-581 share ledger PR 1044
        fx.v2_start("2026-08-12T00:00:00Z", "engineer", "e580", "AUT-580"),
        fx.v2_complete("2026-08-12T01:00:00Z", "engineer", "e580", "AUT-580",
                       cumulative=_T(output=10_000), model="claude-sonnet-5"),
        fx.v2_start("2026-08-12T02:00:00Z", "engineer", "e581", "AUT-581"),
        fx.v2_complete("2026-08-12T03:00:00Z", "engineer", "e581", "AUT-581",
                       cumulative=_T(output=20_000), model="claude-sonnet-5"),
        # before: AUT-500 was opened before v2 coverage began
        fx.v2_start("2026-08-15T00:00:00Z", "engineer", "e500", "AUT-500"),
        # before: an unattributed run
        fx.v2_start("2026-08-15T01:00:00Z", "investigator", "inv1"),
        fx.v2_complete("2026-08-15T02:00:00Z", "investigator", "inv1",
                       cumulative=_T(input=1_000_000), model="claude-haiku-4-5-20251001"),
        # after: AUT-700
        fx.v2_start("2026-08-26T00:00:00Z", "architect", "a700", "AUT-700"),
        fx.v2_complete("2026-08-26T01:00:00Z", "architect", "a700", "AUT-700",
                       cumulative=_T(output=1_000_000), model="claude-opus-5"),
        fx.v2_start("2026-08-27T00:00:00Z", "engineer", "e700", "AUT-700"),
        fx.v2_complete("2026-08-27T02:00:00Z", "engineer", "e700", "AUT-700", wall_seconds=7200.0,
                       cumulative=_T(input=1000, output=2000, cache_read=1_000_000,
                                     cc_5m=100_000, cc_1h=50_000)),
        fx.legacy_complete("2026-08-27T03:00:00Z", "engineer", "e700", "AUT-700",
                           cumulative=_T(input=99_000_000)),
        fx.v2_start("2026-08-28T00:00:00Z", "skeptic", "k700", "AUT-700"),
        fx.v2_complete("2026-08-28T01:00:00Z", "skeptic", "k700", "AUT-700",
                       cumulative=_T(output=100_000), model="claude-sonnet-5",
                       findings_count={"critical": 0, "major": 2, "minor": 1},
                       iteration=1, signed_off=False),
        fx.v2_complete("2026-09-02T01:00:00Z", "skeptic", "k700", "AUT-700", run_index=2,
                       run_start_ts="2026-09-02T00:30:00Z", wall_seconds=1800.0,
                       cumulative=_T(output=150_000), run_tokens=_T(output=50_000),
                       model="claude-sonnet-5", pair_method="resume",
                       findings_count={"critical": 0, "major": 1, "minor": 1},
                       iteration=2, signed_off=True),
        # QA 7b: a FAIL run then a PASS run of one qa-engineer spawn
        fx.v2_start("2026-08-29T00:00:00Z", "qa-engineer", "q700", "AUT-700"),
        fx.v2_complete("2026-08-29T01:00:00Z", "qa-engineer", "q700", "AUT-700",
                       cumulative=_T(input=1_000_000), model="claude-sonnet-5", qa_result="FAIL"),
        fx.v2_complete("2026-08-30T01:00:00Z", "qa-engineer", "q700", "AUT-700", run_index=2,
                       run_start_ts="2026-08-30T00:00:00Z", cumulative=_T(input=1_500_000),
                       run_tokens=_T(input=500_000), model="claude-sonnet-5",
                       pair_method="resume", qa_result="PASS"),
        # after the first merge (09-01): a re-entry whose transcript did not resolve
        fx.v2_start("2026-09-02T12:00:00Z", "engineer", "e700b", "AUT-700"),
        fx.v2_complete("2026-09-02T13:00:00Z", "engineer", "e700b", "AUT-700", wall_seconds=None),
        fx.internal_stop("2026-08-27T02:30:00Z"),
    ]


_TICKET_PRS = [
    {"number": 1044, "title": "Relic features", "headRefName": "feature/AUT-580-581-relic",
     "mergedAt": "2026-08-14T00:00:00Z"},
    {"number": 1050, "title": "[AUT-581]: fix relic", "headRefName": "x",
     "mergedAt": "2026-08-20T00:00:00Z"},
    {"number": 900, "title": "feat(AUT-700): thing", "headRefName": "feature/other",
     "mergedAt": "2026-09-01T00:00:00Z"},
    {"number": 905, "title": "[AUT-700] follow-up", "headRefName": "x",
     "mergedAt": "2026-09-03T00:00:00Z"},
    {"number": 906, "title": "chore: mention AUT-700 in docs", "headRefName": "docs/misc",
     "mergedAt": "2026-09-02T00:00:00Z"},
    {"number": 907, "title": "fix(AUT-7001): other", "headRefName": "feature/AUT-7001-x",
     "mergedAt": "2026-09-02T00:00:00Z"},
]


def _build_ticket_repo(tmp: Path, name: str = "telem") -> Path:
    repo = tmp / name
    fx.write_jsonl(repo / ".agentic" / "events.jsonl", _ticket_fixture_events())
    fx.write_jsonl(repo / ".agentic" / "ticket-ledger.jsonl", [
        {"ticket_id": "AUT-580", "pr_number": 1044, "opened_ts": "2026-08-13T00:00:00Z",
         "branch": "feature/AUT-580-581-relic", "skeptic_rounds": 3},
        {"ticket_id": "AUT-581", "pr_number": 1044, "opened_ts": "2026-08-13T00:00:00Z",
         "branch": "feature/AUT-580-581-relic", "skeptic_rounds": 3},
        {"ticket_id": "AUT-500", "pr_number": 800, "opened_ts": "2026-08-05T00:00:00Z"},
    ])
    (repo / ".agentic" / "loop-state-AUT-700.json").write_text(json.dumps({
        "ticket_id": "AUT-700",
        "loop_state": {"iteration": 2, "findings_log": [
            {"id": "f1", "severity": "Major", "re_raised": True},
            {"id": "f2", "severity": "Major", "re_raised": False},
        ]},
    }), encoding="utf-8")
    (repo / ".agentic" / "loop-state-AUT-580.json").write_text(json.dumps({
        "ticket_id": "AUT-580", "loop_state": {"iteration": 3, "findings_log": [{"id": "g"}]},
    }), encoding="utf-8")
    return repo


def _gh_stub(nodes: list[dict], gh_ok: bool = True):
    def run(args, cwd=None, timeout=None):
        if args[:2] == ["gh", "repo"]:
            if not gh_ok:
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="auth")
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps({"nameWithOwner": "acme/w"}), stderr="")
        if args[:2] == ["gh", "api"]:
            payload = {"data": {"search": {"issueCount": len(nodes),
                                           "pageInfo": {"hasNextPage": False, "endCursor": None},
                                           "nodes": nodes}}}
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
        if args[:2] == ["git", "remote"]:
            return subprocess.CompletedProcess(args, 0, stdout="https://github.com/acme/w.git\n", stderr="")
        raise AssertionError(f"unexpected command: {args}")
    return run


def _ticket_report(repos: list[Path], gh_ok: bool = True, prs: list[dict] | None = None) -> dict:
    orig_run, orig_pricing = _mod._run, _mod._TELEMETRY.PRICING_PATH
    _mod._run = _gh_stub(_TICKET_PRS if prs is None else prs, gh_ok)
    _mod._TELEMETRY.PRICING_PATH = repos[0] / "no-pricing.yml"
    try:
        return _mod.build_delta(repos, CUT_DT, 14, now=NOW)
    finally:
        _mod._run, _mod._TELEMETRY.PRICING_PATH = orig_run, orig_pricing


def _rows_by_ticket(side: dict) -> dict:
    return {r["ticket_id"]: r for r in side["tickets"]}


def test_agent_model_dollars_match_hand_computed_values():
    """QA 5: exact-id and family-priced dollars reported separately; 1h cache at 2x input."""
    with tempfile.TemporaryDirectory() as tmp:
        report = _ticket_report([_build_ticket_repo(Path(tmp))])
    after = report["agent_model"]["after"]
    assert after["status"] == "OK", after
    rows = {(r["agent"], r["model"]): r for r in after["rows"]}
    assert set(rows) == {("architect", "claude-opus-5"), ("engineer", "claude-opus-5-5"),
                         ("engineer", "(unknown)"), ("skeptic", "claude-sonnet-5"),
                         ("qa-engineer", "claude-sonnet-5")}, sorted(rows)
    engineer = rows[("engineer", "claude-opus-5-5")]
    assert abs(engineer["dollars_exact"] - 1.144) < 1e-9, engineer   # legacy 99M-token row ignored
    assert engineer["runs"] == 1 and engineer["dollars_family_estimated"] == 0
    assert rows[("engineer", "(unknown)")]["tokens_null_runs"] == 1
    assert rows[("engineer", "(unknown)")]["wall_null_runs"] == 1
    architect = rows[("architect", "claude-opus-5")]
    assert architect["dollars_family_estimated"] == 20.0 and architect["dollars_exact"] == 0
    assert architect["family_priced_models"] == ["claude-opus-5"]
    assert rows[("skeptic", "claude-sonnet-5")]["dollars_exact"] == 1.5
    assert rows[("qa-engineer", "claude-sonnet-5")]["dollars_exact"] == 3.0
    assert abs(after["dollars_exact"] - 5.644) < 1e-9, after
    assert after["dollars_family_estimated"] == 20.0
    assert after["family_priced_models"] == ["claude-opus-5"]
    assert after["unpriced_models"] == []
    before_rows = {(r["agent"], r["model"]): r for r in report["agent_model"]["before"]["rows"]}
    assert before_rows[("investigator", "claude-haiku-4-5-20251001")]["dollars_exact"] == 1.0
    assert report["agent_model"]["delta"]["dollars_family_estimated"] == 20.0


def test_per_ticket_rows_loops_qa_and_escaped_defects():
    """QA 5 and 7b: per-ticket values from U1-shaped rows, QA FAIL then PASS counted per run."""
    with tempfile.TemporaryDirectory() as tmp:
        report = _ticket_report([_build_ticket_repo(Path(tmp))])
    after = report["per_ticket"]["after"]
    assert after["status"] == "OK", after
    assert set(_rows_by_ticket(after)) == {"AUT-700"}
    t = _rows_by_ticket(after)["AUT-700"]
    assert t["qa_runs"] == 2 and t["qa_fail_backs"] == 1
    assert t["skeptic_reviews"] == 2 and t["skeptic_reviews_source"] == "telemetry"
    assert t["max_iteration"] == 2 and t["max_iteration_source"] == "telemetry"
    assert t["findings"] == {"critical": 0, "major": 3, "minor": 2}
    assert t["re_raised"] == 1
    assert t["pr_status"] == "OK"
    assert t["prs_merged"] == 2 and t["pr_numbers"] == [900, 905]
    assert t["follow_up_prs"] == 1
    assert t["unit_count"] == 1 and t["ledger_skeptic_rounds"] is None
    assert t["loops"] == (2 - 1) + 1 + (2 - 1)
    assert t["final_merge_ts"] == "2026-09-03T00:00:00+00:00"
    assert t["e2e_wall_seconds"] == 8 * 86400
    assert t["reentries_after_merge"] == 1
    assert t["post_merge_findings"] == 1
    assert abs(t["dollars_exact"] - 5.644) < 1e-9 and t["dollars_family_estimated"] == 20.0
    assert after["summary"]["tickets"] == 1 and after["summary"]["loops_mean"] == 3
    assert after["unattributed_runs"] == 0


def test_per_ticket_pr_attribution_ledger_first_then_anchored_prefix():
    """QA 9 / R10: ledger PR 1044 goes to both tickets and is not ambiguous; a ledger
    ticket still collects a fallback follow-up; a PR merely citing T, or naming T0, is not T's."""
    with tempfile.TemporaryDirectory() as tmp:
        report = _ticket_report([_build_ticket_repo(Path(tmp))])
    before = report["per_ticket"]["before"]
    rows = _rows_by_ticket(before)
    assert rows["AUT-580"]["pr_numbers"] == [1044]
    assert rows["AUT-581"]["pr_numbers"] == [1044, 1050]
    assert rows["AUT-581"]["follow_up_prs"] == 1
    assert rows["AUT-580"]["skeptic_reviews"] == 3 and rows["AUT-580"]["skeptic_reviews_source"] == "ledger"
    assert rows["AUT-580"]["max_iteration"] == 3 and rows["AUT-580"]["max_iteration_source"] == "loop_state"
    assert rows["AUT-580"]["re_raised"] is None
    assert rows["AUT-580"]["post_merge_findings"] is None   # no telemetry Skeptic runs to count
    assert rows["AUT-580"]["findings"] is None
    assert before["ambiguous_prs"] == []
    assert before["excluded_pre_v2"] == ["AUT-500"] and "AUT-500" not in rows
    assert before["unattributed_runs"] == 1
    after_numbers = _rows_by_ticket(report["per_ticket"]["after"])["AUT-700"]["pr_numbers"]
    assert 906 not in after_numbers and 907 not in after_numbers


def test_ledger_string_pr_number_is_credited_and_leaves_fallback_pool():
    """Skeptic Major 1: a ledger pr_number stored as "726" is the ledger's PR."""
    nodes = {"r": [{"number": 726, "title": "[AUT-10] other", "headRefName": "x",
                    "mergedAt": "2026-09-01T00:00:00Z"}]}
    credits, ambiguous = _mod._attribute_prs(
        nodes, [("r", {"ticket_id": "AUT-9", "pr_number": "726"})], {"AUT-9", "AUT-10"})
    assert [pr["number"] for pr in credits.get("AUT-9", [])] == [726], credits
    assert "AUT-10" not in credits and ambiguous == []


def _loops_repo(tmp: Path, reviews: int, qa_fails: int, ledger: dict | None) -> Path:
    events = [fx.v2_start("2026-08-10T00:00:00Z", "investigator", "anchor-a"),
              fx.v2_start("2026-09-09T00:00:00Z", "investigator", "anchor-b"),
              fx.v2_start("2026-08-26T00:00:00Z", "engineer", "e", "AUT-800"),
              fx.v2_complete("2026-08-26T01:00:00Z", "engineer", "e", "AUT-800")]
    for i in range(reviews):
        events += [fx.v2_start(f"2026-08-27T0{i}:00:00Z", "skeptic", f"k{i}", "AUT-800"),
                   fx.v2_complete(f"2026-08-27T0{i}:30:00Z", "skeptic", f"k{i}", "AUT-800",
                                  findings_count={"critical": 0, "major": 0, "minor": 0},
                                  iteration=1, signed_off=True)]
    for i in range(qa_fails):
        events += [fx.v2_start(f"2026-08-28T0{i}:00:00Z", "qa-engineer", f"q{i}", "AUT-800"),
                   fx.v2_complete(f"2026-08-28T0{i}:30:00Z", "qa-engineer", f"q{i}", "AUT-800",
                                  qa_result="FAIL")]
    fx.write_jsonl(tmp / ".agentic" / "events.jsonl", events)
    if ledger is not None:
        fx.write_jsonl(tmp / ".agentic" / "ticket-ledger.jsonl",
                       [{"ticket_id": "AUT-800", "opened_ts": "2026-08-26T00:00:00Z", **ledger}])
    return tmp


def _loops_row(reviews: int, qa_fails: int, prs: int, ledger: dict | None) -> dict:
    nodes = [{"number": 1000 + i, "title": f"feat(AUT-800): unit {i}", "headRefName": "x",
              "mergedAt": f"2026-09-0{i + 1}T00:00:00Z"} for i in range(prs)]
    with tempfile.TemporaryDirectory() as tmp:
        report = _ticket_report([_loops_repo(Path(tmp), reviews, qa_fails, ledger)], prs=nodes)
    return _rows_by_ticket(report["per_ticket"]["after"])["AUT-800"]


def test_loops_clean_single_unit_ticket_is_zero():
    """Skeptic Major 2: one review and one PR is no rework."""
    t = _loops_row(reviews=1, qa_fails=0, prs=1, ledger=None)
    assert t["unit_count"] == 1 and t["skeptic_reviews"] == 1 and t["prs_merged"] == 1
    assert t["loops"] == 0, t


def test_loops_clean_two_unit_ticket_is_zero():
    """Skeptic Major 2: one review and one PR per planned unit is no rework."""
    t = _loops_row(reviews=2, qa_fails=0, prs=2, ledger={"unit_count": 2, "skeptic_rounds": 2})
    assert t["unit_count"] == 2 and t["skeptic_reviews"] == 2 and t["prs_merged"] == 2
    assert t["loops"] == 0, t


def test_loops_count_only_rework_beyond_units_and_surface_ledger_rounds():
    """Skeptic Major 2 and Minor 1: extra reviews, QA fail-backs and extra PRs are loops;
    a larger ledger skeptic_rounds is shown beside the telemetry count."""
    t = _loops_row(reviews=4, qa_fails=1, prs=3, ledger={"unit_count": "2", "skeptic_rounds": 5})
    assert t["unit_count"] == 2 and t["skeptic_reviews"] == 4 and t["prs_merged"] == 3
    assert t["skeptic_reviews_source"] == "telemetry" and t["ledger_skeptic_rounds"] == 5
    assert t["loops"] == (4 - 2) + 1 + (3 - 2), t


def test_pr_lookahead_days_out_of_range_exits_2():
    """Skeptic Minor 3: --pr-lookahead-days outside 0..MAX_WINDOW_DAYS exits 2."""
    with tempfile.TemporaryDirectory() as tmp:
        for bad in ("-1", str(_mod.MAX_WINDOW_DAYS + 1)):
            rc = _mod.main(["--cut", "2026-01-01", "--pr-lookahead-days", bad, "--repo", tmp])
            assert rc == 2, (bad, rc)


def test_pr_title_and_branch_matchers():
    for title in ("[AUT-7] x", "[AUT-7]: x", "fix(AUT-7): x", "feat(aut-7)!: x", "AUT-7: x"):
        assert _mod._title_matches("AUT-7", title), title
    for title in ("fix(AUT-70): x", "AUT-70: x", "chore: AUT-7 mentioned", "[AUT-70] x"):
        assert not _mod._title_matches("AUT-7", title), title
    assert _mod._branch_matches("AUT-580", "feature/AUT-580-581-relic")
    assert not _mod._branch_matches("AUT-581", "feature/AUT-580-581-relic")
    assert not _mod._branch_matches("AUT-58", "feature/AUT-580-x")


def test_spawn_sides_gated_by_v2_coverage():
    """QA 6 / R9: partial v2 coverage is INSUFFICIENT_COVERAGE with nulls, no v2 rows is ABSENT,
    and gh unavailable nulls only the PR-derived fields."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        late = tmp / "late"
        fx.write_jsonl(late / ".agentic" / "events.jsonl", [
            fx.v2_start("2026-08-20T00:00:00Z", "engineer", "l1", "AUT-9"),
            fx.v2_complete("2026-08-20T01:00:00Z", "engineer", "l1", "AUT-9", cumulative=_T(output=1)),
            fx.v2_start("2026-09-09T00:00:00Z", "engineer", "l2"),
        ])
        report = _ticket_report([late])
        for key in ("agent_model", "per_ticket"):
            before = report[key]["before"]
            assert before["status"] == "INSUFFICIENT_COVERAGE", before
            assert before["v2_coverage"]["earliest"] == "2026-08-20T00:00:00+00:00"
            assert report[key]["after"]["status"] == "OK"
        assert report["agent_model"]["before"]["rows"] is None
        assert report["per_ticket"]["before"]["tickets"] is None
        assert report["per_ticket"]["delta"] is None

        legacy_only = tmp / "legacy"
        fx.write_jsonl(legacy_only / ".agentic" / "events.jsonl", [
            fx.legacy_complete("2026-08-12T00:00:00Z", "engineer", "x", "AUT-1", cumulative=_T(input=5)),
            fx.legacy_complete("2026-09-09T00:00:00Z", "engineer", "y", "AUT-1", cumulative=_T(input=5)),
        ])
        report = _ticket_report([legacy_only])
        for key in ("agent_model", "per_ticket"):
            for side in ("before", "after"):
                assert report[key][side]["status"] == "ABSENT", report[key][side]
                assert report[key][side]["v2_coverage"]["rows_total"] == 0

        report = _ticket_report([_build_ticket_repo(tmp)], gh_ok=False)
        t = _rows_by_ticket(report["per_ticket"]["after"])["AUT-700"]
        assert t["pr_status"] == "GH_UNAVAILABLE"
        for key in ("prs_merged", "pr_numbers", "final_merge_ts", "e2e_wall_seconds",
                    "follow_up_prs", "reentries_after_merge", "post_merge_findings", "loops"):
            assert t[key] is None, key
        assert t["skeptic_reviews"] == 2 and t["qa_fail_backs"] == 1 and t["re_raised"] == 1


if __name__ == "__main__":
    run_tests()
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and _name != "test_ds_change_delta_regression_suite":
            _fn()
    print("All DS-246 spawn-telemetry tests passed.")
