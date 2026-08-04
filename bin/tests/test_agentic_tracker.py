#!/usr/bin/env python3
"""
Purpose: Regression tests for bin/agentic-tracker - the .agentic/tracker.yml
         overlay merge algorithm, parse boundary, credential guard, and
         write-path git-state guard (DS-74).

Public API: none (test module; not imported by other code).

Test letter set (mirrors the plan's test plan table): A, A2, B, C, D, E, F,
G, H, H2, I, J, K, L, L2, L3, L4, L5, M, O, P, Q, Q2, R, S(a-e), T, U, V, V2,
W, X, Y, Z. N is permanently vacant. L2-Z cover DS-117 (dev-complete
splits from terminal Done).

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
_base_result = _mod._base_result
_apply_dev_complete_default = _mod._apply_dev_complete_default
TRACKED_READ_WARNING = _mod.TRACKED_READ_WARNING


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

AGENTS_MD_JIRA_FULL_WITH_QA = """## Tracker
TRACKER: jira
TICKET_PREFIX: DS
JIRA_BASE_URL: https://solara6.atlassian.net
JIRA_STATE_QA: QA
"""

AGENTS_MD_LINEAR_FULL = """## Linear
- Team: FRM
- Workspace: acme
"""

AGENTS_MD_LINEAR_NO_WORKSPACE = """## Linear
- Team: FRM
"""

# DS-117: dev-complete fixtures.
AGENTS_MD_JIRA_DEV_COMPLETE_AND_DONE = """## Tracker
TRACKER: jira
TICKET_PREFIX: DS
JIRA_BASE_URL: https://solara6.atlassian.net
JIRA_STATE_DEV_COMPLETE: Ready for QA
JIRA_STATE_DONE: Shipped
"""

AGENTS_MD_LINEAR_DEV_COMPLETE_AND_DONE = """## Linear
- Team: FRM
- Workspace: acme
- State Dev Complete: Merged
- State Done: Shipped
"""

AGENTS_MD_JIRA_DONE_OVERRIDE_ONLY = """## Tracker
TRACKER: jira
TICKET_PREFIX: DS
JIRA_BASE_URL: https://solara6.atlassian.net
JIRA_STATE_DONE: Ready for QA
"""

AGENTS_MD_LINEAR_DONE_OVERRIDE_ONLY = """## Linear
- Team: FRM
- Workspace: acme
- State Done: Ready for QA
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
    # AGENTS_MD_JIRA_FULL_WITH_QA declares BOTH TICKET_PREFIX and
    # TRACKER_STATE_QA, so the overlay setting different values for both is
    # a genuine overwrite, not merely an add - distinguishing "overridden"
    # from "added" (a field the overlay sets that AGENTS.md never declared
    # must NOT appear in _overridden).
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_JIRA_FULL_WITH_QA)
        _write(
            cwd / ".agentic" / "tracker.yml",
            "tracker: jira\nprefix: MYDS\nstate_qa: Testing\n",
        )
        result = _resolve_tracker(cwd)
        assert result["TICKET_PREFIX"] == "MYDS"
        assert result["TRACKER_STATE_QA"] == "Testing"
        assert result["_overridden"] == ["TICKET_PREFIX", "TRACKER_STATE_QA"], result["_overridden"]
        print("PASS test_C_merge_overlay_wins_overridden_exact")


def test_C2_merge_add_not_override():
    # A field the overlay ADDS (absent from AGENTS.md) must not be counted
    # as an override - only a genuinely overwritten (present-in-base,
    # different value) field belongs in _overridden.
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_JIRA_FULL)  # no qa_assignee declared
        _write(
            cwd / ".agentic" / "tracker.yml",
            "tracker: jira\nqa_assignee: abc123\n",
        )
        result = _resolve_tracker(cwd)
        assert result["JIRA_QA_ASSIGNEE_ACCOUNT_ID"] == "abc123"
        assert result["_overridden"] == [], result["_overridden"]
        print("PASS test_C2_merge_add_not_override")


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
    # DS-117: dev-complete defaults identically on BOTH trackers (unlike QA)
    # because it inherits the resolved TRACKER_STATE_DONE, which does not
    # vary by tracker.
    assert (
        _defaults_for("jira")["TRACKER_STATE_DEV_COMPLETE"]
        == _defaults_for("linear")["TRACKER_STATE_DEV_COMPLETE"]
        == "Done"
    )
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
        assert any(
            "ordering of IN_PROGRESS/IN_REVIEW/QA with optional DEV_COMPLETE" in w
            for w in warnings
        ), warnings
        result = _resolve_tracker(cwd)
        assert result["TRACKER_PIPELINE_ORDER"] == "IN_PROGRESS, IN_REVIEW, QA"
        print("PASS test_L_malformed_pipeline_order_defaults")


# ---------------------------------------------------------------------------
# L2-L5: DEV_COMPLETE as an optional 4th pipeline_order token (Decision 1)
# ---------------------------------------------------------------------------

def test_L2_pipeline_order_accepts_optional_dev_complete():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        overlay = cwd / ".agentic" / "tracker.yml"
        _write(
            overlay,
            "tracker: jira\nprefix: DS\nbase_url: https://x.atlassian.net\n"
            "pipeline_order: IN_PROGRESS, IN_REVIEW, DEV_COMPLETE, QA\n",
        )
        fields, status, warnings, reason = _read_overlay(overlay)
        assert status == "ok", reason
        assert fields["TRACKER_PIPELINE_ORDER"] == "IN_PROGRESS, IN_REVIEW, DEV_COMPLETE, QA"
        assert not any("pipeline_order" in w for w in warnings)
        print("PASS test_L2_pipeline_order_accepts_optional_dev_complete")


def test_L3_pipeline_order_rejects_missing_required_token():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        overlay = cwd / ".agentic" / "tracker.yml"
        _write(
            overlay,
            "tracker: jira\nprefix: DS\nbase_url: https://x.atlassian.net\n"
            "pipeline_order: IN_PROGRESS, DEV_COMPLETE, QA\n",
        )
        fields, status, warnings, reason = _read_overlay(overlay)
        assert status == "ok", reason
        assert "TRACKER_PIPELINE_ORDER" not in fields
        assert any("pipeline_order" in w for w in warnings)
        print("PASS test_L3_pipeline_order_rejects_missing_required_token")


def test_L4_pipeline_order_rejects_five_tokens_and_unknown_token():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        overlay = cwd / ".agentic" / "tracker.yml"
        _write(
            overlay,
            "tracker: jira\nprefix: DS\nbase_url: https://x.atlassian.net\n"
            "pipeline_order: IN_PROGRESS, IN_REVIEW, QA, DEV_COMPLETE, BOGUS\n",
        )
        fields, status, warnings, reason = _read_overlay(overlay)
        assert status == "ok", reason
        assert "TRACKER_PIPELINE_ORDER" not in fields
        assert any("pipeline_order" in w for w in warnings)
        print("PASS test_L4_pipeline_order_rejects_five_tokens_and_unknown_token")


def test_L5_pipeline_order_three_token_form_still_valid():
    # SC2/R6 regression: a 3-token declaration stays valid with no warning.
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        overlay = cwd / ".agentic" / "tracker.yml"
        _write(
            overlay,
            "tracker: jira\nprefix: DS\nbase_url: https://x.atlassian.net\n"
            "pipeline_order: IN_REVIEW, IN_PROGRESS, QA\n",
        )
        fields, status, warnings, reason = _read_overlay(overlay)
        assert status == "ok", reason
        assert fields["TRACKER_PIPELINE_ORDER"] == "IN_REVIEW, IN_PROGRESS, QA"
        assert not any("pipeline_order" in w for w in warnings)
        print("PASS test_L5_pipeline_order_three_token_form_still_valid")


# ---------------------------------------------------------------------------
# T: overlay accepts state_dev_complete as a key
# ---------------------------------------------------------------------------

def test_T_overlay_state_dev_complete_key_accepted():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        overlay = cwd / ".agentic" / "tracker.yml"
        _write(
            overlay,
            "tracker: jira\nprefix: DS\nbase_url: https://x.atlassian.net\n"
            "state_dev_complete: Ready for QA\n",
        )
        fields, status, warnings, reason = _read_overlay(overlay)
        assert status == "ok", reason
        assert fields["TRACKER_STATE_DEV_COMPLETE"] == "Ready for QA"

        result = _resolve_tracker(cwd)
        assert result["TRACKER_STATE_DEV_COMPLETE"] == "Ready for QA"
        assert result["TRACKER_DEV_COMPLETE_DECLARED"] == "true"
        print("PASS test_T_overlay_state_dev_complete_key_accepted")


# ---------------------------------------------------------------------------
# U: JIRA_STATE_DEV_COMPLETE / State Dev Complete: never shadow Done, in
# either direction (label-shadowing guard, both trackers)
# ---------------------------------------------------------------------------

def test_U_agents_md_dev_complete_field_both_trackers():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_JIRA_DEV_COMPLETE_AND_DONE)
        result = _resolve_tracker(cwd)
        assert result["TRACKER_STATE_DEV_COMPLETE"] == "Ready for QA"
        assert result["TRACKER_STATE_DONE"] == "Shipped"
        assert result["TRACKER_DEV_COMPLETE_DECLARED"] == "true"

    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_LINEAR_DEV_COMPLETE_AND_DONE)
        result = _resolve_tracker(cwd)
        assert result["TRACKER_STATE_DEV_COMPLETE"] == "Merged"
        assert result["TRACKER_STATE_DONE"] == "Shipped"
        assert result["TRACKER_DEV_COMPLETE_DECLARED"] == "true"
    print("PASS test_U_agents_md_dev_complete_field_both_trackers")


# ---------------------------------------------------------------------------
# V: the round-1 Critical pin - dev-complete inherits the RESOLVED Done
# value, never the literal "Done".
# ---------------------------------------------------------------------------

def test_V_dev_complete_inherits_resolved_done_not_literal():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_JIRA_DONE_OVERRIDE_ONLY)
        result = _resolve_tracker(cwd)
        assert result["TRACKER_STATE_DEV_COMPLETE"] == "Ready for QA"
        assert result["TRACKER_STATE_DEV_COMPLETE"] != "Done"
        assert result["TRACKER_DEV_COMPLETE_DECLARED"] == "false"

    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_LINEAR_DONE_OVERRIDE_ONLY)
        result = _resolve_tracker(cwd)
        assert result["TRACKER_STATE_DEV_COMPLETE"] == "Ready for QA"
        assert result["TRACKER_STATE_DEV_COMPLETE"] != "Done"
        assert result["TRACKER_DEV_COMPLETE_DECLARED"] == "false"
    print("PASS test_V_dev_complete_inherits_resolved_done_not_literal")


# ---------------------------------------------------------------------------
# W: inheritance also flows through an overlay-declared state_done, when
# AGENTS.md declares no Done field.
# ---------------------------------------------------------------------------

def test_W_dev_complete_inheritance_via_overlay_done():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        # Fixture requirement: the overlay must also carry tracker: plus
        # that tracker's REQUIRED_KEYS (prefix + base_url for jira).
        # Without them the sole-source branch hits the missing-required
        # check and falls back to _base_result(base), yielding "Done" for a
        # fixture reason unrelated to what this test pins.
        _write(
            cwd / ".agentic" / "tracker.yml",
            "tracker: jira\nprefix: DS\nbase_url: https://x.atlassian.net\n"
            "state_done: Shipped\n",
        )
        result = _resolve_tracker(cwd)
        assert result["TRACKER_STATE_DONE"] == "Shipped"
        assert result["TRACKER_STATE_DEV_COMPLETE"] == "Shipped"
        assert result["TRACKER_DEV_COMPLETE_DECLARED"] == "false"
        print("PASS test_W_dev_complete_inheritance_via_overlay_done")


# ---------------------------------------------------------------------------
# V2: the round-2 Major pin, part 1 - TRACKER_DEV_COMPLETE_DECLARED is the
# string "true"/"false", never a JSON boolean.
# ---------------------------------------------------------------------------

def test_V2_declared_dev_complete_sets_the_declared_flag():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_JIRA_DEV_COMPLETE_AND_DONE)
        result = _resolve_tracker(cwd)
        v = result["TRACKER_DEV_COMPLETE_DECLARED"]
        assert v == "true"
        assert isinstance(v, str)

    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_JIRA_DONE_OVERRIDE_ONLY)
        result = _resolve_tracker(cwd)
        v2 = result["TRACKER_DEV_COMPLETE_DECLARED"]
        assert v2 == "false"
        assert isinstance(v2, str)
    print("PASS test_V2_declared_dev_complete_sets_the_declared_flag")


# ---------------------------------------------------------------------------
# X: a declared dev-complete wins over the inherited default.
# ---------------------------------------------------------------------------

def test_X_declared_dev_complete_wins_over_inheritance():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_JIRA_DEV_COMPLETE_AND_DONE)
        result = _resolve_tracker(cwd)
        assert result["TRACKER_STATE_DEV_COMPLETE"] == "Ready for QA"
        assert result["TRACKER_STATE_DEV_COMPLETE"] != result["TRACKER_STATE_DONE"]
        print("PASS test_X_declared_dev_complete_wins_over_inheritance")


# ---------------------------------------------------------------------------
# Y: an inherited dev-complete must never be reported as an operator
# override, even on the merge path.
# ---------------------------------------------------------------------------

def test_Y_inherited_dev_complete_is_not_reported_as_override():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        _write(cwd / "AGENTS.md", AGENTS_MD_JIRA_FULL)  # tracker: jira, no dev-complete field
        _write(
            cwd / ".agentic" / "tracker.yml",
            "tracker: jira\nprefix: MYDS\n",
        )
        result = _resolve_tracker(cwd)
        assert result["_source"] == "merged"
        assert "TRACKER_STATE_DEV_COMPLETE" not in result["_overridden"]
        assert "TRACKER_DEV_COMPLETE_DECLARED" not in result["_overridden"]
        assert result["TRACKER_DEV_COMPLETE_DECLARED"] == "false"
        print("PASS test_Y_inherited_dev_complete_is_not_reported_as_override")


# ---------------------------------------------------------------------------
# Z: TRACKER=none still reports _source == "none" after inheritance -
# guards the copy-not-mutate obligation on _base_result's caller-owned dict.
# ---------------------------------------------------------------------------

def test_Z_base_result_source_unaffected_by_inheritance():
    base: dict = {}
    result = _base_result(base)
    assert result["_source"] == "none"
    assert base == {}, base  # caller's dict must not be mutated in place
    assert "TRACKER_STATE_DEV_COMPLETE" not in base

    result2 = _base_result(None)
    assert result2["_source"] == "none"
    print("PASS test_Z_base_result_source_unaffected_by_inheritance")


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


def test_M2_set_unreadable_existing_overlay_degrades_no_traceback():
    # cmd_set reads-then-rewrites an existing overlay; an unreadable file at
    # that point (permission change between _check_ignored and the read, or
    # any other OSError) must degrade to a clear operator-facing message and
    # exit 1, never a raw traceback. Outside the plan's fail-safe invariant
    # (which binds _resolve_tracker only) but a real rough edge on the same
    # file class - see qa-regression note in the fix commit.
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        env = _init_repo(repo)
        _write(repo / ".gitignore", ".agentic/tracker.yml\n")
        r_init = _run_cli(
            ["init", "--tracker", "jira", "--prefix", "DS", "--base-url", "https://x.atlassian.net"],
            repo,
            env,
        )
        assert r_init.returncode == 0, r_init.stderr

        overlay_path = repo / ".agentic" / "tracker.yml"
        os.chmod(overlay_path, 0o000)
        try:
            r = _run_cli(["set", "prefix", "Y"], repo, env)
            assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
            assert "Traceback" not in r.stderr
            assert "cannot read existing" in r.stderr
        finally:
            os.chmod(overlay_path, 0o600)
        print("PASS test_M2_set_unreadable_existing_overlay_degrades_no_traceback")


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
    # DS-117: dev-complete defaults to the resolved Done value, pinning the
    # relationship (not just the literal), plus the declared flag default.
    assert d["TRACKER_STATE_DEV_COMPLETE"] == "Done"
    assert d["TRACKER_STATE_DEV_COMPLETE"] == d["TRACKER_STATE_DONE"]
    assert d["TRACKER_DEV_COMPLETE_DECLARED"] == "false"
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

        r = _run_cli(["resolve", "--json"], cwd, _git_env(cwd))
        assert r.returncode == 2
        import json as _json
        parsed = _json.loads(r.stdout)
        assert parsed["_agents_md_guard"]
        print("PASS test_R_legacy_guard_terminal_json_on_stdout")


# ---------------------------------------------------------------------------
# Critical regression: an unreadable AGENTS.md must degrade, never raise.
# Fail-safe invariant: _resolve_tracker never raises and never exits/signals
# non-zero for any file-state reason - the only non-zero exit is 2 (legacy
# guard). An unreadable AGENTS.md (e.g. chmod 000) is a file-state reason.
# ---------------------------------------------------------------------------

def test_unreadable_agents_md_never_raises():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        agents_path = cwd / "AGENTS.md"
        _write(agents_path, AGENTS_MD_JIRA_FULL)
        _write(
            cwd / ".agentic" / "tracker.yml",
            "tracker: jira\nprefix: DS\nbase_url: https://x.atlassian.net\n",
        )
        os.chmod(agents_path, 0o000)
        try:
            result = _resolve_tracker(cwd)  # must not raise
            assert result["_source"] == "overlay", result["_source"]
            assert result["TICKET_PREFIX"] == "DS"

            env = _git_env(cwd)
            r = _run_cli(["resolve", "--json"], cwd, env)
            assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
            assert "Traceback" not in r.stderr
        finally:
            # Restore permissions so tempfile cleanup can remove the file.
            os.chmod(agents_path, 0o644)
        print("PASS test_unreadable_agents_md_never_raises")


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
        env = _git_env(repo)
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


# ---------------------------------------------------------------------------
# no-repo state: outside any git work tree, the write-path guard allows and
# warns rather than refuses.
# ---------------------------------------------------------------------------

def test_no_repo_state_allows_and_warns():
    with tempfile.TemporaryDirectory() as tmp:
        # A plain directory with no .git anywhere in its ancestry. Guard
        # against accidentally running this INSIDE the DinoStack repo's own
        # tree (which would make cwd.parent resolve to a real git work
        # tree and defeat the fixture) by asserting the state up front.
        cwd = Path(tmp) / "no-git-here"
        cwd.mkdir()
        overlay_path = cwd / ".agentic" / "tracker.yml"
        overlay_path.parent.mkdir(parents=True)
        state = _git_state(overlay_path)
        assert state == "no-repo", f"fixture precondition failed: git state was {state!r}, not no-repo"

        may_write, returned_state, msg = _check_ignored(overlay_path)
        assert may_write is True
        assert returned_state == "no-repo"
        assert msg, "no-repo must still emit a warning message"
        print("PASS test_no_repo_state_allows_and_warns")


# ---------------------------------------------------------------------------
# Read-side tracked-file warning (plan r2 mitigation for Known limitation 2).
# ---------------------------------------------------------------------------

def test_tracked_overlay_emits_read_side_warning():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        env = _init_repo(repo)
        _write(repo / ".gitignore", ".agentic/tracker.yml\n")
        r_init = _run_cli(
            ["init", "--tracker", "jira", "--prefix", "DS", "--base-url", "https://x.atlassian.net"],
            repo,
            env,
        )
        assert r_init.returncode == 0, r_init.stderr

        subprocess.run(
            ["git", "add", "-f", ".agentic/tracker.yml"], cwd=str(repo), env=env, check=True
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "track overlay"], cwd=str(repo), env=env, check=True
        )

        result = _resolve_tracker(repo)
        assert result["_git_state"] == "tracked"
        assert TRACKED_READ_WARNING in result["_warnings"], result["_warnings"]

        r_resolve = _run_cli(["resolve", "--json"], repo, env)
        assert r_resolve.returncode == 0, r_resolve.stderr
        assert TRACKED_READ_WARNING in r_resolve.stderr
        print("PASS test_tracked_overlay_emits_read_side_warning")


if __name__ == "__main__":
    test_A_no_overlay_jira_agents_md_byte_identical()
    test_A2_no_overlay_linear_agents_md()
    test_B_overlay_sole_source_no_agents_md()
    test_C_merge_overlay_wins_overridden_exact()
    test_C2_merge_add_not_override()
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
    test_L2_pipeline_order_accepts_optional_dev_complete()
    test_L3_pipeline_order_rejects_missing_required_token()
    test_L4_pipeline_order_rejects_five_tokens_and_unknown_token()
    test_L5_pipeline_order_three_token_form_still_valid()
    test_T_overlay_state_dev_complete_key_accepted()
    test_U_agents_md_dev_complete_field_both_trackers()
    test_V_dev_complete_inherits_resolved_done_not_literal()
    test_W_dev_complete_inheritance_via_overlay_done()
    test_V2_declared_dev_complete_sets_the_declared_flag()
    test_X_declared_dev_complete_wins_over_inheritance()
    test_Y_inherited_dev_complete_is_not_reported_as_override()
    test_Z_base_result_source_unaffected_by_inheritance()
    test_M_write_side_key_validation_exit_4()
    test_M2_set_unreadable_existing_overlay_degrades_no_traceback()
    test_O_comment_skip_before_parsing()
    test_P_defaults_for_none()
    test_Q_missing_required_field_demotes_to_unusable()
    test_Q2_empty_value_treated_as_unset()
    test_R_legacy_guard_terminal_json_on_stdout()
    test_unreadable_agents_md_never_raises()
    test_S_write_path_guard_five_cases()
    test_S_d_unknown_git_state_fails_closed()
    test_no_repo_state_allows_and_warns()
    test_tracked_overlay_emits_read_side_warning()
