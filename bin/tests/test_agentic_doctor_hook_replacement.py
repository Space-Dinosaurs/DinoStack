"""Unit + caller-level tests for bin/ds-doctor's _hook_replacement() (DS-206).

Covers the accumulator rewrite that converges every stale, DinoStack-shaped
occurrence of every managed hook basename present in a settings.json
`command` string, in one call - fixing the bug where only the FIRST token
matching the FIRST basename found was ever rewritten, leaving a guarded
form's `test -f <NEW> && python3 <OLD> || exit 0` half-fixed.

Run with: python3 -m pytest bin/tests/test_agentic_doctor_hook_replacement.py -x

Test-first ordering (DS-206 spawn brief): this file was written and run
against the UNMODIFIED (pre-fix) _hook_replacement before the fix landed.
Expected red/green table per case, verified by that pre-fix run:

  - test_fully_stale_guarded_form            RED pre-fix / GREEN post-fix
  - test_half_fixed_guarded_form             RED pre-fix / GREEN post-fix
  - test_mixed_stale_path_guarded_form       RED pre-fix / GREEN post-fix
  - test_two_managed_basenames_one_command   RED pre-fix / GREEN post-fix
  - test_three_distinct_stale_occurrences    RED pre-fix / GREEN post-fix
  - test_bare_single_occurrence_stale_form   GREEN both pre-fix and post-fix
                                              (already worked under count=1)
  - test_already_correct_guarded_form        GREEN both pre-fix and post-fix
                                              (returns None both ways)
  - test_non_dinostack_shaped_path_untouched GREEN both pre-fix and post-fix
                                              (negative case; returns None)
  - test_caller_writes_fully_converged_command_to_disk
                                              RED pre-fix / GREEN post-fix
  - test_repair_exits_zero_with_no_fail_line (Amendment 1)
                                              RED pre-fix (would FAIL/exit 2)
                                              / GREEN post-fix
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path

_BIN = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("_ds_doctor_hr", str(_BIN / "ds-doctor"))
_spec = importlib.util.spec_from_loader("_ds_doctor_hr", _loader)
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

Doctor = _mod.Doctor
_hook_replacement = _mod._hook_replacement
check_hook_paths = _mod.check_hook_paths


def _realpath(p: Path) -> Path:
    return Path(os.path.realpath(str(p)))


def _mkrepo(tmp_path: Path) -> Path:
    """A realpath'd fixture repo_dir - never the real checkout.

    Realpathed per the mandatory fixture-construction rule: _load_repo_dir()
    always realpaths, so an un-realpathed fixture makes "already correct"
    assertions pass for the wrong reason on macOS (/tmp -> /private/tmp).
    """
    repo = tmp_path / "DinoStack"
    (repo / ".git").mkdir(parents=True)
    (repo / "hooks").mkdir(parents=True)
    return _realpath(repo)


# ---------------------------------------------------------------------------
# Unit-level cases against _hook_replacement directly
# ---------------------------------------------------------------------------


def test_fully_stale_guarded_form(tmp_path):
    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    old = old_repo / "hooks" / "enforce-turn-shape.py"
    cmd = f"test -f {old} && python3 {old} || exit 0"
    result = _hook_replacement(cmd, repo)
    assert result is not None
    assert str(old) not in result
    assert str(repo / "hooks" / "enforce-turn-shape.py") in result


def test_half_fixed_guarded_form(tmp_path):
    """The bug's own residue: test -f already points at NEW, python3 still OLD."""
    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    new = repo / "hooks" / "enforce-turn-shape.py"
    old = old_repo / "hooks" / "enforce-turn-shape.py"
    cmd = f"test -f {new} && python3 {old} || exit 0"
    result = _hook_replacement(cmd, repo)
    assert result is not None
    assert str(old) not in result
    assert str(new) in result


def test_mixed_stale_path_guarded_form(tmp_path):
    """Two distinct old locations for the same basename in one command."""
    repo = _mkrepo(tmp_path)
    old_repo_a = tmp_path / "old-a-DinoStack"
    old_repo_b = tmp_path / "old-b-DinoStack"
    old_a = old_repo_a / "hooks" / "enforce-turn-shape.py"
    old_b = old_repo_b / "hooks" / "enforce-turn-shape.py"
    cmd = f"test -f {old_a} && python3 {old_b} || exit 0"
    result = _hook_replacement(cmd, repo)
    assert result is not None
    assert str(old_a) not in result
    assert str(old_b) not in result
    assert str(repo / "hooks" / "enforce-turn-shape.py") in result


def test_two_managed_basenames_one_command(tmp_path):
    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    old1 = old_repo / "hooks" / "enforce-background-spawn.py"
    old2 = old_repo / "hooks" / "enforce-orchestrator-singularity.py"
    cmd = f"python3 {old1}; python3 {old2}"
    result = _hook_replacement(cmd, repo)
    assert result is not None
    assert str(old1) not in result
    assert str(old2) not in result
    assert str(repo / "hooks" / "enforce-background-spawn.py") in result
    assert str(repo / "hooks" / "enforce-orchestrator-singularity.py") in result


def test_three_distinct_stale_occurrences(tmp_path):
    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    old1 = old_repo / "hooks" / "enforce-background-spawn.py"
    old2 = old_repo / "hooks" / "enforce-orchestrator-singularity.py"
    old3 = old_repo / "hooks" / "enforce-tier.py"
    cmd = f"python3 {old1}; python3 {old2}; python3 {old3}"
    result = _hook_replacement(cmd, repo)
    assert result is not None
    assert str(old1) not in result
    assert str(old2) not in result
    assert str(old3) not in result


def test_bare_single_occurrence_stale_form(tmp_path):
    """Already worked under the pre-fix count=1 shape - GREEN both ways.

    This assertion form is IDENTICAL pre-fix and post-fix; a passing run
    here is not evidence the fix is applied, only that the bare single-token
    case was never broken. Do not misread it as a red-run failure signal.
    """
    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    old = old_repo / "hooks" / "enforce-tier.py"
    cmd = f"python3 {old}"
    result = _hook_replacement(cmd, repo)
    assert result is not None
    assert str(old) not in result
    assert str(repo / "hooks" / "enforce-tier.py") in result


def test_already_correct_guarded_form(tmp_path):
    """GREEN both ways by design - returns None, nothing to repair."""
    repo = _mkrepo(tmp_path)
    new = repo / "hooks" / "enforce-turn-shape.py"
    cmd = f"test -f {new} && python3 {new} || exit 0"
    result = _hook_replacement(cmd, repo)
    assert result is None


def test_non_dinostack_shaped_path_untouched(tmp_path):
    """Negative case: a non-DinoStack-shaped stale path is left alone.

    The accumulator replaced an early `return None` with full iteration over
    all tokens and all managed basenames, widening the predicate's blast
    radius. Nothing pre-existing pinned this negative case - pin it here.
    """
    repo = _mkrepo(tmp_path)
    foreign = tmp_path / "some-other-project" / "hooks" / "enforce-tier.py"
    cmd = f"python3 {foreign}"
    result = _hook_replacement(cmd, repo)
    assert result is None


# ---------------------------------------------------------------------------
# Caller-level test: check_hook_paths / _atomic_patch_settings writes a
# fully-converged command to disk. MANDATORY isolation: monkeypatch HOME and
# delenv CLAUDE_CONFIG_DIR BEFORE constructing Doctor(...) or calling
# check_hook_paths - without it this test rewrites the developer's real
# ~/.claude/settings.json (reproduced by execution in prior review rounds).
# ---------------------------------------------------------------------------


def test_caller_writes_fully_converged_command_to_disk(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    old1 = old_repo / "hooks" / "enforce-turn-shape.py"
    old2 = old_repo / "hooks" / "enforce-tier.py"

    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    settings_path = claude_dir / "settings.json"
    settings = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"test -f {old1} && python3 {old1} || exit 0",
                            "timeout": 10,
                        }
                    ],
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "Task",
                    "hooks": [
                        {"type": "command", "command": f"python3 {old2}", "timeout": 5}
                    ],
                }
            ],
        }
    }
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    doc = Doctor(repo_dir=repo, fix=True, json_mode=True)
    check_hook_paths(doc)

    written = json.loads(settings_path.read_text(encoding="utf-8"))
    written_text = json.dumps(written)
    assert str(old1) not in written_text
    assert str(old2) not in written_text
    assert str(repo / "hooks" / "enforce-turn-shape.py") in written_text
    assert str(repo / "hooks" / "enforce-tier.py") in written_text


def test_repair_exits_zero_with_no_fail_line(tmp_path, monkeypatch):
    """Amendment 1 regression guard: a successful repair must not also
    report itself as an unfixable FAIL via repoint_symlink's os.symlink
    call against settings.json (a regular file, not a symlink) raising
    FileExistsError.

    Mutation that would redden this: reverting the check_hook_paths fix
    back to `doc.repoint_symlink("hooks", settings_path, old_cmd,
    Path(new_cmd))` (the plan's pre-Amendment-1 caller shape) reproduces
    `FAIL hooks: could not re-point ...: [Errno 17] File exists` and
    doc.fix mode's has_unresolved_findings() returns True.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    old = old_repo / "hooks" / "enforce-tier.py"

    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    settings_path = claude_dir / "settings.json"
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Task",
                    "hooks": [
                        {"type": "command", "command": f"python3 {old}", "timeout": 5}
                    ],
                }
            ]
        }
    }
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    doc = Doctor(repo_dir=repo, fix=True, json_mode=True)
    check_hook_paths(doc)

    assert not any(status == "FAIL" for status, _ in doc.findings), doc.findings
    assert not doc.has_unresolved_findings()
    assert not doc.has_unfixable()
