#!/usr/bin/env python3
"""
Purpose: Regression tests for bin/agentic-tracker - the .agentic/tracker.yml
         overlay merge algorithm, parse boundary, credential guard, and
         write-path git-state guard (DS-74).

Public API: none (test module; not imported by other code).

Test letter set (mirrors the plan's test plan table): A, A2, B, C, D, E, F,
G, H, H2, I, J, K, L, M, O, P, Q, Q2, R, S(a-e). N is permanently vacant.

Upstream deps: bin/agentic-tracker (module under test, loaded via
               SourceFileLoader since it has no .py extension); Python 3
               stdlib only (subprocess, tempfile, unittest-free asserts).
               Every git-touching fixture sets GIT_CONFIG_GLOBAL=/dev/null,
               GIT_CONFIG_SYSTEM=/dev/null, and HOME=<tmpdir> so a
               developer's core.excludesFile cannot make a test pass or
               fail spuriously.

Downstream consumers: none (leaf test module).

Failure modes: each test function raises AssertionError on mismatch;
               the __main__ runner executes all tests sequentially and
               lets the first failure propagate.

Performance: S(a)-(e) and M each shell out to `git` a handful of times in a
             throwaway tmp repo; all other rows are pure in-process calls.

Run with: python3 -m pytest bin/tests/test_agentic_tracker.py -x
       or: python3 bin/tests/test_agentic_tracker.py
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Load agentic-tracker as a module (no .py extension)
# ---------------------------------------------------------------------------
_BIN_PATH = Path(__file__).parent.parent / "agentic-tracker"
_loader = importlib.machinery.SourceFileLoader("agentic_tracker", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("agentic_tracker", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-tracker from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

_read_overlay = _mod._read_overlay
_read_agents_md = _mod._read_agents_md
_defaults_for = _mod._defaults_for
_resolve_tracker = _mod._resolve_tracker
_git_state = _mod._git_state
_check_ignored = _mod._check_ignored
_validate_write_key = _mod._validate_write_key


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git_env(home: Path) -> dict:
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    env["HOME"] = str(home)
    return env


def _init_repo(repo: Path) -> dict:
    repo.mkdir(parents=True, exist_ok=True)
    env = _git_env(repo)
    subprocess.run(["git", "init", "-q"], cwd=str(repo), env=env, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(repo), env=env, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(repo), env=env, check=True)
    return env


def _run_cli(args: list[str], cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_BIN_PATH)] + args,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# A / A2: overlay-independent back-compat sentinels (resolution-level)
# ---------------------------------------------------------------------------

AGENTS_MD_JIRA_FULL = """## Tracker
TRACKER: jira
TICKET_PREFIX: DS
JIRA_BASE_URL: https://solara6.atlassian.net
"""

AGENTS_MD_LINEAR_FULL = """## Linear
- Team: FRM
- Workspace: acme
"""

AGENTS_MD_LINEAR_NO_WORKSPACE = """## Linear
- Team: FRM
"""


def test_A_no_overlay_jira_agents_md_byte_identical():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_JIRA_FULL)
        result = _resolve_tracker(cwd)
        assert result["TRACKER"] == "jira"
        assert result["TICKET_PREFIX"] == "DS"
        assert result["JIRA_BASE_URL"] == "https://solara6.atlassian.net"
        assert result["_source"] == "agents-md"
        assert result["_overridden"] == []
        print("PASS test_A_no_overlay_jira_agents_md_byte_identical")


def test_A2_no_overlay_linear_agents_md():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_LINEAR_FULL)
        result = _resolve_tracker(cwd)
        assert result["TRACKER"] == "linear"
        assert result["LINEAR_WORKSPACE"] == "acme"
        assert result["TRACKER_STATE_QA"] == "Testing"
        assert result["_agents_md_guard"] is None
        print("PASS test_A2_no_overlay_linear_agents_md")


# ---------------------------------------------------------------------------
# B: the DS-74 test - overlay alone, no AGENTS.md
# ---------------------------------------------------------------------------

def test_B_overlay_sole_source_no_agents_md():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(
            cwd / ".agentic" / "tracker.yml",
            "tracker: jira\nprefix: DS\nbase_url: https://solara6.atlassian.net\n",
        )
        result = _resolve_tracker(cwd)
        assert result["TRACKER"] == "jira"
        assert result["TICKET_PREFIX"] == "DS"
        assert result["_source"] == "overlay"
        print("PASS test_B_overlay_sole_source_no_agents_md")


# ---------------------------------------------------------------------------
# C: merge, overlay wins on matching keys, _overridden exact
# ---------------------------------------------------------------------------

def test_C_merge_overlay_wins_overridden_exact():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_JIRA_FULL)
        _write(
            cwd / ".agentic" / "tracker.yml",
            "tracker: jira\nprefix: MYDS\nstate_qa: Testing\n",
        )
        result = _resolve_tracker(cwd)
        assert result["TICKET_PREFIX"] == "MYDS"
        assert result["TRACKER_STATE_QA"] == "Testing"
        assert result["_overridden"] == ["TICKET_PREFIX", "TRACKER_STATE_QA"], result["_overridden"]
        print("PASS test_C_merge_overlay_wins_overridden_exact")


# ---------------------------------------------------------------------------
# D: type switch discards AGENTS.md fields entirely
# ---------------------------------------------------------------------------

def test_D_type_switch_discards_base_fields():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_JIRA_FULL)
        _write(
            cwd / ".agentic" / "tracker.yml",
            "tracker: linear\nprefix: FRM\nworkspace: acme\n",
        )
        result = _resolve_tracker(cwd)
        assert result.get("JIRA_BASE_URL") is None
        assert result["LINEAR_WORKSPACE"] == "acme"
        assert result["_source"] == "overlay"
        print("PASS test_D_type_switch_discards_base_fields")


# ---------------------------------------------------------------------------
# E: credential-shaped key rejects the whole file
# ---------------------------------------------------------------------------

def test_E_credential_key_rejects_whole_file():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_JIRA_FULL)
        overlay = cwd / ".agentic" / "tracker.yml"
        _write(
            overlay,
            "tracker: jira\nprefix: MYDS\nbase_url: https://x.atlassian.net\napi_key: xyz\n",
        )
        fields, status, warnings, reason = _read_overlay(overlay)
        assert status == "unusable"
        assert "credential-shaped key" in reason
        base_result = _resolve_tracker(cwd)
        assert base_result["TICKET_PREFIX"] == "DS"  # AGENTS.md value, not the overlay's
        assert base_result["_source"] == "agents-md"
        print("PASS test_E_credential_key_rejects_whole_file")


# ---------------------------------------------------------------------------
# F: unknown, non-credential key is dropped, not whole-file rejected
# ---------------------------------------------------------------------------

def test_F_unknown_key_dropped_not_whole_file():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        overlay = cwd / ".agentic" / "tracker.yml"
        _write(
            overlay,
            "tracker: jira\nprefix: DS\nbase_url: https://x.atlassian.net\nnickname: bob\n",
        )
        fields, status, warnings, reason = _read_overlay(overlay)
        assert status == "ok"
        assert "nickname" not in fields
        assert any("nickname" in w for w in warnings)
        print("PASS test_F_unknown_key_dropped_not_whole_file")


# ---------------------------------------------------------------------------
# G: invalid UTF-8 bytes - no exception, distinct 'unreadable' path
# ---------------------------------------------------------------------------

def test_G_invalid_utf8_no_exception():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_JIRA_FULL)
        overlay = cwd / ".agentic" / "tracker.yml"
        overlay.parent.mkdir(parents=True, exist_ok=True)
        overlay.write_bytes(b"tracker: jira\n\xff\xfe\x00")
        fields, status, warnings, reason = _read_overlay(overlay)
        assert status == "unusable"
        assert "unreadable" in reason
        result = _resolve_tracker(cwd)
        assert result["_source"] == "agents-md"
        print("PASS test_G_invalid_utf8_no_exception")


# ---------------------------------------------------------------------------
# H / H2: unusable reasons name what IS accepted
# ---------------------------------------------------------------------------

def test_H_missing_tracker_key_reason():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        overlay = cwd / ".agentic" / "tracker.yml"
        _write(overlay, "prefix: DS\n")
        fields, status, warnings, reason = _read_overlay(overlay)
        assert status == "unusable"
        assert "no 'tracker:' key" in reason
        assert "accepted values: jira, linear" in reason
        print("PASS test_H_missing_tracker_key_reason")


def test_H2_unknown_tracker_value_reason():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        overlay = cwd / ".agentic" / "tracker.yml"
        _write(overlay, "tracker: jyra\nprefix: DS\nbase_url: https://x.atlassian.net\n")
        fields, status, warnings, reason = _read_overlay(overlay)
        assert status == "unusable"
        assert "unknown tracker 'jyra'" in reason
        assert "accepted values: jira, linear" in reason
        print("PASS test_H2_unknown_tracker_value_reason")


# ---------------------------------------------------------------------------
# I: empty repo - neither overlay nor AGENTS.md
# ---------------------------------------------------------------------------

def test_I_empty_repo_resolves_none():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        result = _resolve_tracker(cwd)
        assert result["TRACKER"] == "none"
        assert result["_source"] == "none"
        assert result["_overlay_status"] == "absent"
        assert result["_overlay_reason"] is None
        defaults = _defaults_for(None)
        for k in defaults:
            assert result[k] == defaults[k], (k, result[k], defaults[k])
        print("PASS test_I_empty_repo_resolves_none")


# ---------------------------------------------------------------------------
# J: oversized value dropped, then required-field validation fails
# ---------------------------------------------------------------------------

def test_J_oversized_value_dropped_then_unusable():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        overlay = cwd / ".agentic" / "tracker.yml"
        long_prefix = "X" * 300
        _write(overlay, f"tracker: jira\nprefix: {long_prefix}\nbase_url: https://x.atlassian.net\n")
        fields, status, warnings, reason = _read_overlay(overlay)
        assert long_prefix not in str(fields)
        result = _resolve_tracker(cwd)
        assert result["_overlay_status"] == "unusable"
        assert "prefix" in result["_overlay_reason"]
        print("PASS test_J_oversized_value_dropped_then_unusable")


# ---------------------------------------------------------------------------
# K: defaults differ by tracker for TRACKER_STATE_QA
# ---------------------------------------------------------------------------

def test_K_defaults_qa_differ_by_tracker():
    assert _defaults_for("jira")["TRACKER_STATE_QA"] == "QA"
    assert _defaults_for("linear")["TRACKER_STATE_QA"] == "Testing"
    print("PASS test_K_defaults_qa_differ_by_tracker")


# ---------------------------------------------------------------------------
# L: malformed pipeline_order warns and defaults, never raises
# ---------------------------------------------------------------------------

def test_L_malformed_pipeline_order_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        overlay = cwd / ".agentic" / "tracker.yml"
        _write(
            overlay,
            "tracker: jira\nprefix: DS\nbase_url: https://x.atlassian.net\n"
            "pipeline_order: QA, QA, QA\n",
        )
        fields, status, warnings, reason = _read_overlay(overlay)
        assert status == "ok"
        assert "TRACKER_PIPELINE_ORDER" not in fields  # malformed -> dropped, default fills in later
        assert any("pipeline_order" in w for w in warnings)
        result = _resolve_tracker(cwd)
        assert result["TRACKER_PIPELINE_ORDER"] == "IN_PROGRESS, IN_REVIEW, QA"
        print("PASS test_L_malformed_pipeline_order_defaults")


# ---------------------------------------------------------------------------
# M: write-side key validation ordering - exit 4 regardless of ignore state
# ---------------------------------------------------------------------------

def test_M_write_side_key_validation_exit_4():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        env = _init_repo(repo)

        # (ignored repo)
        _write(repo / ".gitignore", ".agentic/tracker.yml\n")
        subprocess.run(["git", "add", ".gitignore"], cwd=str(repo), env=env, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "gitignore"], cwd=str(repo), env=env, check=True)

        r = _run_cli(["set", "api_token", "x"], repo, env)
        assert r.returncode == 4, r.stderr
        assert "credential-shaped key" in r.stderr
        assert not (repo / ".agentic" / "tracker.yml").exists()

        # (unignored repo) - fresh repo, no .gitignore entry
        repo2 = Path(tmp) / "repo2"
        env2 = _init_repo(repo2)
        r2 = _run_cli(["set", "api_token", "x"], repo2, env2)
        assert r2.returncode == 4, r2.stderr
        assert "credential-shaped key" in r2.stderr
        print("PASS test_M_write_side_key_validation_exit_4")


# ---------------------------------------------------------------------------
# O: comment-skip protects a colon-bearing comment line
# ---------------------------------------------------------------------------

def test_O_comment_skip_before_parsing():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        overlay = cwd / ".agentic" / "tracker.yml"
        _write(
            overlay,
            "# api_key: see 1Password\ntracker: jira\nprefix: DS\nbase_url: https://x.atlassian.net\n",
        )
        fields, status, warnings, reason = _read_overlay(overlay)
        assert status == "ok", reason
        result = _resolve_tracker(cwd)
        assert result["_overlay_status"] == "ok"
        print("PASS test_O_comment_skip_before_parsing")


# ---------------------------------------------------------------------------
# P: pure defaults helper for the None branch
# ---------------------------------------------------------------------------

def test_P_defaults_for_none():
    d = _defaults_for(None)
    assert d["TRACKER_STATE_QA"] == "Testing"
    assert d["TRACKER_PIPELINE_ORDER"] == "IN_PROGRESS, IN_REVIEW, QA"
    print("PASS test_P_defaults_for_none")


# ---------------------------------------------------------------------------
# Q / Q2: required-field validation on the resolved set, sole-source only
# ---------------------------------------------------------------------------

def test_Q_missing_required_field_demotes_to_unusable():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        overlay = cwd / ".agentic" / "tracker.yml"
        _write(overlay, "tracker: jira\n")
        result = _resolve_tracker(cwd)
        assert result["_overlay_status"] == "unusable"
        assert "missing required field(s) for tracker 'jira'" in result["_overlay_reason"]
        assert result["TRACKER"] == "none"
        print("PASS test_Q_missing_required_field_demotes_to_unusable")


def test_Q2_empty_value_treated_as_unset():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        overlay = cwd / ".agentic" / "tracker.yml"
        _write(overlay, "tracker: jira\nbase_url: https://x.atlassian.net\nprefix:\n")
        result = _resolve_tracker(cwd)
        assert result["_overlay_status"] == "unusable"
        assert "prefix" in result["_overlay_reason"]
        print("PASS test_Q2_empty_value_treated_as_unset")


# ---------------------------------------------------------------------------
# R: legacy guard is terminal and never suppressed by the overlay
# ---------------------------------------------------------------------------

def test_R_legacy_guard_terminal_json_on_stdout():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_LINEAR_NO_WORKSPACE)
        _write(
            cwd / ".agentic" / "tracker.yml",
            "tracker: jira\nprefix: DS\nbase_url: https://x.atlassian.net\n",
        )
        result = _resolve_tracker(cwd)
        assert result["_agents_md_guard"] is not None

        r = _run_cli(["resolve", "--json"], cwd, dict(os.environ))
        assert r.returncode == 2
        import json as _json
        parsed = _json.loads(r.stdout)
        assert parsed["_agents_md_guard"]
        print("PASS test_R_legacy_guard_terminal_json_on_stdout")


# ---------------------------------------------------------------------------
# S: write-path git-state guard - five cases
# ---------------------------------------------------------------------------

def test_S_write_path_guard_five_cases():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        env = _init_repo(repo)

        # (a) no ignore line -> init exits 3, writes nothing.
        r_a = _run_cli(
            ["init", "--tracker", "jira", "--prefix", "DS", "--base-url", "https://x.atlassian.net"],
            repo,
            env,
        )
        assert r_a.returncode == 3, r_a.stderr
        assert "is NOT gitignored" in r_a.stderr
        assert not (repo / ".agentic" / "tracker.yml").exists()

        # (b) add the ignore line -> init succeeds.
        _write(repo / ".gitignore", ".agentic/tracker.yml\n")
        r_b = _run_cli(
            ["init", "--tracker", "jira", "--prefix", "DS", "--base-url", "https://x.atlassian.net"],
            repo,
            env,
        )
        assert r_b.returncode == 0, r_b.stderr
        assert (repo / ".agentic" / "tracker.yml").is_file()

        # (c) force-track the file, commit, then `set` -> exits 3 with the
        # git rm --cached remedy, NOT the .gitignore remedy.
        subprocess.run(
            ["git", "add", "-f", ".agentic/tracker.yml"], cwd=str(repo), env=env, check=True
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "track overlay"], cwd=str(repo), env=env, check=True
        )
        r_c = _run_cli(["set", "prefix", "Y"], repo, env)
        assert r_c.returncode == 3, r_c.stderr
        assert "already TRACKED" in r_c.stderr
        assert "git rm --cached" in r_c.stderr
        assert "add this line to .gitignore" not in r_c.stderr

        # (e) --force-unignored on a fresh ignored-but-not-yet-existing repo
        # exits 0 with a WARNING; test this against a fresh unignored repo
        # since (a)'s repo now has an ignore line.
        repo_e = Path(tmp) / "repo_e"
        env_e = _init_repo(repo_e)
        r_e = _run_cli(
            [
                "init",
                "--tracker",
                "jira",
                "--prefix",
                "DS",
                "--base-url",
                "https://x.atlassian.net",
                "--force-unignored",
            ],
            repo_e,
            env_e,
        )
        assert r_e.returncode == 0, r_e.stderr
        assert (repo_e / ".agentic" / "tracker.yml").is_file()
        assert "WARNING:" in r_e.stderr

        print("PASS test_S_write_path_guard_five_cases (a, b, c, e)")


def test_S_d_unknown_git_state_fails_closed():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir(parents=True)
        shim_dir = Path(tmp) / "shim"
        shim_dir.mkdir()
        shim = shim_dir / "git"
        shim.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "rev-parse" ]; then echo true; exit 0; fi\n'
            'if [ "$1" = "ls-files" ]; then exit 1; fi\n'
            'if [ "$1" = "check-ignore" ]; then exit 128; fi\n'
            "exit 0\n",
            encoding="utf-8",
        )
        shim.chmod(0o755)
        env = dict(os.environ)
        env["PATH"] = f"{shim_dir}:{env.get('PATH', '')}"

        r = _run_cli(
            ["init", "--tracker", "jira", "--prefix", "DS", "--base-url", "https://x.atlassian.net"],
            repo,
            env,
        )
        assert r.returncode == 3, r.stderr
        assert "cannot determine" in r.stderr
        assert not (repo / ".agentic" / "tracker.yml").exists()
        print("PASS test_S_d_unknown_git_state_fails_closed")


if __name__ == "__main__":
    test_A_no_overlay_jira_agents_md_byte_identical()
    test_A2_no_overlay_linear_agents_md()
    test_B_overlay_sole_source_no_agents_md()
    test_C_merge_overlay_wins_overridden_exact()
    test_D_type_switch_discards_base_fields()
    test_E_credential_key_rejects_whole_file()
    test_F_unknown_key_dropped_not_whole_file()
    test_G_invalid_utf8_no_exception()
    test_H_missing_tracker_key_reason()
    test_H2_unknown_tracker_value_reason()
    test_I_empty_repo_resolves_none()
    test_J_oversized_value_dropped_then_unusable()
    test_K_defaults_qa_differ_by_tracker()
    test_L_malformed_pipeline_order_defaults()
    test_M_write_side_key_validation_exit_4()
    test_O_comment_skip_before_parsing()
    test_P_defaults_for_none()
    test_Q_missing_required_field_demotes_to_unusable()
    test_Q2_empty_value_treated_as_unset()
    test_R_legacy_guard_terminal_json_on_stdout()
    test_S_write_path_guard_five_cases()
    test_S_d_unknown_git_state_fails_closed()
