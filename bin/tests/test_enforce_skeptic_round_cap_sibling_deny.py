#!/usr/bin/env python3
"""
Regression tests for the sibling-deny consultation added to
hooks/enforce-skeptic-round-cap.py (fix/round-cap-sibling-deny, extended by
fix/round-cap-all-siblings): a Skeptic spawn round-cap would ALLOW but a
REGISTERED sibling PreToolUse hook on the same "Task"/"Agent" spawn matcher
(enforce-skeptic-neutrality.py / enforce-tier.py / enforce-background-
spawn.py / enforce-orchestrator-singularity.py) independently DENIES must
never advance round_count or consume a recorded ship/escalate decision -
see enforce-skeptic-round-cap.py's "Sibling-deny consultation" docstring
paragraph and content/references/skeptic-protocol.md's "Round budget and
value-per-round gate" item 1.

Every test that invokes hooks/enforce-skeptic-round-cap.py runs it with an
EXPLICIT, scratch `CLAUDE_CONFIG_DIR` (and the other three harness config-dir
env vars cleared) - never the real `~/.claude/settings.json`. A test that
wants the consultation to actually fire must register the sibling's basename
in that scratch config first (`_write_settings`); a test that wants "today's
behavior" (registration unconfirmed) leaves the scratch config dir empty.

Test groups:
  1. test_neutrality_denied_spawn_leaves_no_state_file         - registered sibling; round-cap's own
                                                                 decision would ALLOW round 1, but
                                                                 neutrality denies (untagged field 7) ->
                                                                 no round-state file AND no tuid-index
                                                                 file are ever written.
  2. test_tier_denied_spawn_leaves_no_state_file                - same shape, tier denies (explicit
                                                                 sub-Tier-3 model downgrade on a
                                                                 security-flavored brief).
  2b. test_background_spawn_denied_spawn_leaves_no_state_file   - same shape, enforce-background-
                                                                 spawn.py denies (foreground Task
                                                                 spawn, no run_in_background: true).
  2b'. test_background_spawn_unregistered_leaves_todays_behavior - unregistered background-spawn ->
                                                                 not consulted -> round-cap charges
                                                                 the round exactly as before.
  2c. test_singularity_denied_spawn_leaves_no_state_file        - same shape, enforce-orchestrator-
                                                                 singularity.py denies (non-empty
                                                                 top-level agent_id).
  2c'. test_singularity_unregistered_leaves_todays_behavior     - unregistered singularity -> not
                                                                 consulted -> round-cap charges the
                                                                 round exactly as before.
  3. test_escalate_decision_preserved_when_sibling_denies       - SEVERE case: state at cap with
                                                                 decision:"escalate" recorded; a
                                                                 sibling-denied spawn leaves round_count
                                                                 AND decision byte-unchanged; the NEXT
                                                                 valid spawn is allowed and consumes the
                                                                 escalate; the spawn after THAT is denied
                                                                 at the cap with no decision recorded.
  4. test_clean_spawn_still_advances_normally                   - control: a spawn no sibling denies
                                                                 advances state exactly as before this
                                                                 fix.
  5. test_broken_sibling_module_falls_back_to_original_persist  - a sibling module that fails to import
                                                                 (missing file) never blocks this hook's
                                                                 own persistence.
  6. test_sibling_would_deny_raises_falls_back_to_original_persist - a sibling module whose `would_deny`
                                                                 raises never blocks persistence either.
  7. test_sibling_missing_would_deny_attribute_falls_back        - a sibling module with no `would_deny`
                                                                 attribute at all is simply excluded from
                                                                 consultation, not treated as a failure
                                                                 or a deny.
  8. test_registered_sibling_via_project_settings_is_consulted  - registration confirmed via the UNIT's
                                                                 own project-level `.claude/settings.json`
                                                                 (no CLAUDE_CONFIG_DIR entry needed).
  9. test_unregistered_sibling_leaves_todays_behavior            - Major 1: no settings file anywhere
                                                                 registers the sibling -> NOT consulted ->
                                                                 round-cap persists exactly as it did
                                                                 before this consultation existed, even
                                                                 though the sibling would have denied.
 10. test_malformed_settings_json_leaves_todays_behavior         - same outcome when the only candidate
                                                                 settings file is present but not valid
                                                                 JSON.
 11. test_unreadable_settings_leaves_todays_behavior              - same outcome when the candidate file
                                                                 exists but is unreadable (chmod 000);
                                                                 skipped when the test runner can't drop
                                                                 read permission on itself (e.g. root).
 12. test_drift_guard_every_registered_spawn_hook_is_classified - parses .claude/install.sh's Task/Agent
                                                                 PreToolUse spawn-matcher registrations
                                                                 (tolerant of a one-line upsert_hook() call)
                                                                 and asserts every registered enforce-*.py
                                                                 hook other than round-cap itself is either
                                                                 consulted (_SIBLING_MODULES), tracked as a
                                                                 known unconsulted-but-deny-capable gap
                                                                 (_KNOWN_UNCONSULTED_DENY_CAPABLE, asserted
                                                                 EMPTY as of fix/round-cap-all-siblings),
                                                                 proven never to deny (_NEVER_DENIES), or
                                                                 proven structurally unable to deny a
                                                                 skeptic spawn specifically
                                                                 (_CANNOT_DENY_SKEPTIC) - so a NEW
                                                                 deny-capable hook added to the matcher
                                                                 without classification fails this test.
 13. test_drift_guard_still_catches_a_new_unclassified_hook    - the classification logic still fails a
                                                                 fabricated, genuinely unclassified hook
                                                                 name even with an empty known-unconsulted
                                                                 set - the guard is a real gate, not
                                                                 trivially green because nothing is left
                                                                 to classify.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent.parent
_HOOKS_DIR = _REPO_ROOT / "hooks"
_ROUND_CAP_HOOK = _HOOKS_DIR / "enforce-skeptic-round-cap.py"
_NEUTRALITY_HOOK = _HOOKS_DIR / "enforce-skeptic-neutrality.py"
_TIER_HOOK = _HOOKS_DIR / "enforce-tier.py"
_BACKGROUND_SPAWN_HOOK = _HOOKS_DIR / "enforce-background-spawn.py"
_SINGULARITY_HOOK = _HOOKS_DIR / "enforce-orchestrator-singularity.py"
_INSTALL_SH = _REPO_ROOT / ".claude" / "install.sh"

_CONFIG_DIR_ENV_VARS = ("AGENTIC_CONFIG_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "PI_CODING_AGENT_DIR")


def _load_round_cap_module():
    spec = importlib.util.spec_from_file_location("_round_cap_hook_sibling", _ROUND_CAP_HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ensure_git_marker(cwd: str) -> None:
    Path(cwd, ".git").mkdir(exist_ok=True)


def _prompt(
    diff_key: str,
    what_to_review: str,
    field7: str = "n/a - Trivial direct edit",
) -> str:
    return (
        "## Global-context inputs\n"
        f"6. Diff under review: {diff_key} | git diff origin/main...fix/x\n"
        f"7. Conductor spawn brief: {field7}\n"
        "\n"
        f"**What to review:** {what_to_review}\n"
    )


def _payload(
    cwd: str,
    prompt: str,
    model: str | None = None,
    tool_use_id: str | None = None,
    tool_name: str = "Agent",
    run_in_background: bool | None = None,
    agent_id: str | None = None,
) -> dict:
    tinput = {"subagent_type": "skeptic", "description": "review", "prompt": prompt}
    if model is not None:
        tinput["model"] = model
    if run_in_background is not None:
        tinput["run_in_background"] = run_in_background
    payload = {"tool_name": tool_name, "cwd": cwd, "tool_input": tinput}
    if tool_use_id is not None:
        payload["tool_use_id"] = tool_use_id
    if agent_id is not None:
        payload["agent_id"] = agent_id
    return payload


def _isolated_env(config_dir: Path | None) -> dict:
    """Env for a subprocess hook invocation that NEVER reads the real
    `~/.claude/settings.json` (or any other real harness config). Clears
    all four harness config-dir vars, then sets `CLAUDE_CONFIG_DIR` to
    *config_dir* (a scratch directory) when given - when *config_dir* is
    None, `CLAUDE_CONFIG_DIR` is left unset but still cleared, so
    `_resolve_claude_config_dir()` falls back to its own `~/.claude`
    default; that fallback path is intentionally exercised only by tests
    that assert on "no candidate file exists" (registration unconfirmed),
    never on a test whose real machine happens to have both siblings
    registered there."""
    env = dict(os.environ)
    for var in _CONFIG_DIR_ENV_VARS:
        env.pop(var, None)
    if config_dir is not None:
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    return env


def _write_settings(path: Path, basenames: list[str]) -> None:
    """Write a minimal, real-shaped settings.json registering each of
    *basenames* on BOTH the "Task" and "Agent" PreToolUse matcher, in the
    exact `{"hooks": {"PreToolUse": [{"matcher": ..., "hooks": [{"command":
    ...}]}]}}` shape a live Claude Code settings.json carries (verified
    against this machine's own `~/.claude/settings.json` structure, never
    its content)."""
    entries = [{"type": "command", "command": f"python3 /fake/hooks/{name}", "timeout": 5} for name in basenames]
    payload = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Task", "hooks": entries},
                {"matcher": "Agent", "hooks": entries},
            ]
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _write_settings_single_matcher(path: Path, basenames: list[str], matcher: str) -> None:
    """Same shape as `_write_settings`, but registers *basenames* on ONLY
    *matcher* ("Task" or "Agent") - used to prove registration is scoped
    to the spawn's own `tool_name` (round-2 rework, Minor 2), not "either
    matcher, whichever."""
    entries = [{"type": "command", "command": f"python3 /fake/hooks/{name}", "timeout": 5} for name in basenames]
    payload = {"hooks": {"PreToolUse": [{"matcher": matcher, "hooks": entries}]}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _run_hook(
    hook_path: Path,
    payload: dict,
    run_cwd: str | None = None,
    env: dict | None = None,
) -> tuple[int, dict | None]:
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=run_cwd,
        env=env,
    )
    out = result.stdout.strip()
    parsed = json.loads(out) if out else None
    return result.returncode, parsed


def _is_denied(parsed: dict | None) -> bool:
    if not parsed:
        return False
    return parsed.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def _state_files(cwd: str) -> list[Path]:
    agentic = Path(cwd) / ".agentic"
    if not agentic.is_dir():
        return []
    return sorted(agentic.glob("skeptic-round-*.json"))


def _tuid_index_path(cwd: str) -> Path:
    return Path(cwd) / ".agentic" / "skeptic-tuid-index.json"


@pytest.fixture
def registered_config_dir(tmp_path):
    """A scratch harness config dir whose settings.json registers BOTH
    enforce-skeptic-neutrality.py and enforce-tier.py on Task/Agent -
    isolated per test via pytest's own tmp_path, never the real
    ~/.claude."""
    config_dir = tmp_path / "claude-config"
    _write_settings(
        config_dir / "settings.json",
        ["enforce-skeptic-neutrality.py", "enforce-tier.py"],
    )
    return config_dir


@pytest.fixture
def registered_background_spawn_config_dir(tmp_path):
    """A scratch harness config dir whose settings.json registers ONLY
    enforce-background-spawn.py on Task/Agent."""
    config_dir = tmp_path / "claude-config-bg"
    _write_settings(config_dir / "settings.json", ["enforce-background-spawn.py"])
    return config_dir


@pytest.fixture
def registered_singularity_config_dir(tmp_path):
    """A scratch harness config dir whose settings.json registers ONLY
    enforce-orchestrator-singularity.py on Task/Agent."""
    config_dir = tmp_path / "claude-config-sing"
    _write_settings(config_dir / "settings.json", ["enforce-orchestrator-singularity.py"])
    return config_dir


# --------------------------------------------------------------------------- #
# 1. Neutrality-denied spawn: no state file, no tuid index, ever written
# --------------------------------------------------------------------------- #
def test_neutrality_denied_spawn_leaves_no_state_file(tmp_path, registered_config_dir):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)
    diff_key = "sibling-deny-neutrality-unit"

    prompt = _prompt(
        diff_key,
        what_to_review="Worker fixed the retry logic. Diff attached.",
        field7="The retry logic in retry.py has a race condition.",  # untagged -> neutrality denies
    )
    payload = _payload(cwd, prompt, tool_use_id="tuid-1")

    # Confirm neutrality genuinely denies this exact payload (precondition).
    _, neut_parsed = _run_hook(_NEUTRALITY_HOOK, payload)
    assert _is_denied(neut_parsed), "precondition failed: neutrality did not deny the untagged field-7 payload"

    env = _isolated_env(registered_config_dir)
    rc_code, rc_parsed = _run_hook(_ROUND_CAP_HOOK, payload, env=env)
    assert rc_code == 0
    assert not _is_denied(rc_parsed), "round-cap itself should allow (the sibling's own deny blocks the spawn)"
    assert _state_files(cwd) == [], "round-cap must not persist any round-state file for a sibling-denied spawn"
    assert not _tuid_index_path(cwd).exists(), (
        "round-cap must not create/update skeptic-tuid-index.json for a spawn it never persisted a round for"
    )


# --------------------------------------------------------------------------- #
# 2. Tier-denied spawn: no state file ever written
# --------------------------------------------------------------------------- #
def test_tier_denied_spawn_leaves_no_state_file(tmp_path, registered_config_dir):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)
    diff_key = "sibling-deny-tier-unit"

    prompt = _prompt(
        diff_key,
        what_to_review="Worker patched an authentication bypass in the login flow. Diff attached.",
    )
    # subagent_type "skeptic" + explicit sub-Tier-3 model + a security-flavored
    # brief -> enforce-tier.py denies.
    payload = _payload(cwd, prompt, model="haiku", tool_use_id="tuid-1")

    _, tier_parsed = _run_hook(_TIER_HOOK, payload)
    assert _is_denied(tier_parsed), "precondition failed: tier did not deny the sub-Tier-3 security-brief payload"

    env = _isolated_env(registered_config_dir)
    rc_code, rc_parsed = _run_hook(_ROUND_CAP_HOOK, payload, env=env)
    assert rc_code == 0
    assert not _is_denied(rc_parsed)
    assert _state_files(cwd) == [], "round-cap must not persist any state for a spawn a sibling would deny"
    assert not _tuid_index_path(cwd).exists(), (
        "round-cap must not create/update skeptic-tuid-index.json for a spawn it never persisted a round for"
    )


# --------------------------------------------------------------------------- #
# 2b. background-spawn-denied spawn: no state file ever written (registered)
# --------------------------------------------------------------------------- #
def test_background_spawn_denied_spawn_leaves_no_state_file(tmp_path, registered_background_spawn_config_dir):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)
    diff_key = "sibling-deny-background-spawn-unit"

    prompt = _prompt(diff_key, what_to_review="Worker fixed issue #1, round 1.")
    # tool_name "Task" (legacy) with no run_in_background field -> enforce-
    # background-spawn.py denies (Task requires an explicit True).
    payload = _payload(cwd, prompt, tool_use_id="tuid-1", tool_name="Task")

    _, bg_parsed = _run_hook(_BACKGROUND_SPAWN_HOOK, payload)
    assert _is_denied(bg_parsed), "precondition failed: background-spawn did not deny the foreground Task payload"

    env = _isolated_env(registered_background_spawn_config_dir)
    rc_code, rc_parsed = _run_hook(_ROUND_CAP_HOOK, payload, env=env)
    assert rc_code == 0
    assert not _is_denied(rc_parsed), "round-cap itself should allow (the sibling's own deny blocks the spawn)"
    assert _state_files(cwd) == [], "round-cap must not persist any state for a spawn a sibling would deny"
    assert not _tuid_index_path(cwd).exists(), (
        "round-cap must not create/update skeptic-tuid-index.json for a spawn it never persisted a round for"
    )


def test_background_spawn_unregistered_leaves_todays_behavior(tmp_path):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)
    empty_config_dir = tmp_path / "claude-config-empty"
    empty_config_dir.mkdir()

    diff_key = "sibling-deny-background-spawn-unregistered-unit"
    prompt = _prompt(diff_key, what_to_review="Worker fixed issue #1, round 1.")
    payload = _payload(cwd, prompt, tool_use_id="tuid-1", tool_name="Task")

    _, bg_parsed = _run_hook(_BACKGROUND_SPAWN_HOOK, payload)
    assert _is_denied(bg_parsed), "precondition failed: background-spawn did not deny the foreground Task payload"

    env = _isolated_env(empty_config_dir)
    rc_code, rc_parsed = _run_hook(_ROUND_CAP_HOOK, payload, env=env)
    assert rc_code == 0
    assert not _is_denied(rc_parsed)

    state_files = _state_files(cwd)
    assert len(state_files) == 1, (
        "an UNCONFIRMED enforce-background-spawn.py registration must never be "
        "treated as 'would deny' - round-cap must persist exactly as it did "
        "before this consultation existed"
    )
    state = json.loads(state_files[0].read_text())
    assert state["round_count"] == 1


# --------------------------------------------------------------------------- #
# 2c. orchestrator-singularity-denied spawn: no state file ever written
#     (registered)
# --------------------------------------------------------------------------- #
def test_singularity_denied_spawn_leaves_no_state_file(tmp_path, registered_singularity_config_dir):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)
    diff_key = "sibling-deny-singularity-unit"

    prompt = _prompt(diff_key, what_to_review="Worker fixed issue #1, round 1.")
    # A non-empty top-level agent_id means this spawn was issued from inside
    # a subagent context -> enforce-orchestrator-singularity.py denies.
    payload = _payload(cwd, prompt, tool_use_id="tuid-1", agent_id="agent-xyz")

    _, sing_parsed = _run_hook(_SINGULARITY_HOOK, payload)
    assert _is_denied(sing_parsed), "precondition failed: singularity did not deny the nested-spawn payload"

    env = _isolated_env(registered_singularity_config_dir)
    rc_code, rc_parsed = _run_hook(_ROUND_CAP_HOOK, payload, env=env)
    assert rc_code == 0
    assert not _is_denied(rc_parsed), "round-cap itself should allow (the sibling's own deny blocks the spawn)"
    assert _state_files(cwd) == [], "round-cap must not persist any state for a spawn a sibling would deny"
    assert not _tuid_index_path(cwd).exists(), (
        "round-cap must not create/update skeptic-tuid-index.json for a spawn it never persisted a round for"
    )


def test_singularity_unregistered_leaves_todays_behavior(tmp_path):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)
    empty_config_dir = tmp_path / "claude-config-empty"
    empty_config_dir.mkdir()

    diff_key = "sibling-deny-singularity-unregistered-unit"
    prompt = _prompt(diff_key, what_to_review="Worker fixed issue #1, round 1.")
    payload = _payload(cwd, prompt, tool_use_id="tuid-1", agent_id="agent-xyz")

    _, sing_parsed = _run_hook(_SINGULARITY_HOOK, payload)
    assert _is_denied(sing_parsed), "precondition failed: singularity did not deny the nested-spawn payload"

    env = _isolated_env(empty_config_dir)
    rc_code, rc_parsed = _run_hook(_ROUND_CAP_HOOK, payload, env=env)
    assert rc_code == 0
    assert not _is_denied(rc_parsed)

    state_files = _state_files(cwd)
    assert len(state_files) == 1, (
        "an UNCONFIRMED enforce-orchestrator-singularity.py registration must "
        "never be treated as 'would deny' - round-cap must persist exactly as "
        "it did before this consultation existed"
    )
    state = json.loads(state_files[0].read_text())
    assert state["round_count"] == 1


# --------------------------------------------------------------------------- #
# 3. Severe case: escalate decision preserved, then correctly consumed, then
#    the cap denies again with no decision recorded.
# --------------------------------------------------------------------------- #
def test_escalate_decision_preserved_when_sibling_denies(tmp_path, registered_config_dir):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)
    diff_key = "sibling-deny-escalate-unit"
    env = _isolated_env(registered_config_dir)

    # Rounds 1-2: clean spawns (tagged/n-a field 7), distinct Worker output
    # each round so fingerprint coalescing does not collapse them.
    for i in (1, 2):
        prompt = _prompt(diff_key, what_to_review=f"Worker fixed issue #{i}, round {i}.")
        payload = _payload(cwd, prompt, tool_use_id=f"tuid-{i}")
        code, parsed = _run_hook(_ROUND_CAP_HOOK, payload, env=env)
        assert code == 0
        assert not _is_denied(parsed)

    state_files = _state_files(cwd)
    assert len(state_files) == 1
    state_path = state_files[0]
    state = json.loads(state_path.read_text())
    assert state["round_count"] == 2

    # Conductor records decision: escalate (cap reached, one more round authorized).
    state["decision"] = "escalate"
    state_path.write_text(json.dumps(state))
    before = json.loads(state_path.read_text())

    # Round 3: a NEW fingerprint (new Worker output), but field 7 is untagged
    # -> neutrality denies it.
    prompt3 = _prompt(
        diff_key,
        what_to_review="Worker fixed issue #3, round 3.",
        field7="The retry logic still has a subtle race condition nobody caught.",
    )
    payload3 = _payload(cwd, prompt3, tool_use_id="tuid-3")

    _, neut_parsed = _run_hook(_NEUTRALITY_HOOK, payload3)
    assert _is_denied(neut_parsed), "precondition failed: neutrality did not deny round 3's untagged field-7"

    rc_code, rc_parsed = _run_hook(_ROUND_CAP_HOOK, payload3, env=env)
    assert rc_code == 0
    assert not _is_denied(rc_parsed)

    after = json.loads(state_path.read_text())
    assert after == before, (
        "state must be byte-unchanged after a sibling-denied spawn at cap with "
        f"decision=escalate: before={before!r} after={after!r}"
    )
    assert after["round_count"] == 2
    assert after["decision"] == "escalate"

    # Major 2(a): the NEXT valid (clean, new-fingerprint) spawn must be
    # ALLOWED and must CONSUME the still-live escalate decision.
    prompt4 = _prompt(diff_key, what_to_review="Worker fixed issue #4, round 4 (clean, tagged).")
    payload4 = _payload(cwd, prompt4, tool_use_id="tuid-4")
    rc4_code, rc4_parsed = _run_hook(_ROUND_CAP_HOOK, payload4, env=env)
    assert rc4_code == 0
    assert not _is_denied(rc4_parsed), "the spawn consuming escalate must be allowed"

    consumed = json.loads(state_path.read_text())
    assert consumed["round_count"] == 3, "escalate-consuming spawn must advance round_count"
    assert consumed["decision"] is None, "escalate must be consumed (reset to null) on use"

    # Major 2(a): the spawn AFTER that (cap reached again, no decision
    # recorded) must be DENIED.
    prompt5 = _prompt(diff_key, what_to_review="Worker fixed issue #5, round 5 (clean, tagged).")
    payload5 = _payload(cwd, prompt5, tool_use_id="tuid-5")
    rc5_code, rc5_parsed = _run_hook(_ROUND_CAP_HOOK, payload5, env=env)
    assert rc5_code == 0
    assert _is_denied(rc5_parsed), "cap reached again with no decision recorded must deny"

    final_state = json.loads(state_path.read_text())
    assert final_state["round_count"] == 3, "a DENIED spawn must not advance round_count"
    assert final_state["decision"] is None


# --------------------------------------------------------------------------- #
# 4. Control: a spawn no sibling denies still advances normally
# --------------------------------------------------------------------------- #
def test_clean_spawn_still_advances_normally(tmp_path, registered_config_dir):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)
    diff_key = "sibling-deny-clean-unit"

    prompt = _prompt(diff_key, what_to_review="Worker fixed issue #1, round 1.")
    payload = _payload(cwd, prompt, tool_use_id="tuid-1")

    env = _isolated_env(registered_config_dir)
    code, parsed = _run_hook(_ROUND_CAP_HOOK, payload, env=env)
    assert code == 0
    assert not _is_denied(parsed)

    state_files = _state_files(cwd)
    assert len(state_files) == 1
    state = json.loads(state_files[0].read_text())
    assert state["round_count"] == 1
    assert state["tool_use_ids"] == ["tuid-1"]


# --------------------------------------------------------------------------- #
# 5. Fail direction: a broken/missing sibling module never blocks persistence
# --------------------------------------------------------------------------- #
def _scratch_hooks_dir(tmp_path: Path) -> Path:
    """A scratch hooks/ dir carrying only the round-cap hook and its lib/
    deps - the caller adds/omits/mutates the sibling files it wants to
    test."""
    scratch_hooks = tmp_path / "hooks"
    scratch_hooks.mkdir()
    shutil.copy(_ROUND_CAP_HOOK, scratch_hooks / _ROUND_CAP_HOOK.name)
    shutil.copytree(_HOOKS_DIR / "lib", scratch_hooks / "lib")
    return scratch_hooks


def test_broken_sibling_module_falls_back_to_original_persist_behavior(tmp_path):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)

    scratch_hooks = _scratch_hooks_dir(tmp_path)
    # Deliberately do NOT create enforce-skeptic-neutrality.py or
    # enforce-tier.py in the scratch hooks/ dir - _load_sibling_would_deny_fns
    # hits an import failure for every configured sibling.

    config_dir = tmp_path / "claude-config"
    _write_settings(
        config_dir / "settings.json",
        ["enforce-skeptic-neutrality.py", "enforce-tier.py"],
    )

    diff_key = "sibling-deny-broken-import-unit"
    prompt = _prompt(diff_key, what_to_review="Worker fixed issue #1, round 1.")
    payload = _payload(cwd, prompt, tool_use_id="tuid-1")

    env = _isolated_env(config_dir)
    code, parsed = _run_hook(scratch_hooks / _ROUND_CAP_HOOK.name, payload, env=env)
    assert code == 0
    assert not _is_denied(parsed)

    state_files = _state_files(cwd)
    assert len(state_files) == 1, (
        "a sibling import failure must never suppress persistence - round-cap "
        "should behave exactly as it did before this consultation existed"
    )
    state = json.loads(state_files[0].read_text())
    assert state["round_count"] == 1


# --------------------------------------------------------------------------- #
# 6. Fail direction: a sibling whose would_deny() RAISES never blocks
#    persistence
# --------------------------------------------------------------------------- #
def test_sibling_would_deny_raises_falls_back_to_original_persist_behavior(tmp_path):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)

    scratch_hooks = _scratch_hooks_dir(tmp_path)
    # A sibling module that DOES import successfully and DOES expose a
    # would_deny attribute, but calling it raises.
    (scratch_hooks / "enforce-skeptic-neutrality.py").write_text(
        "def would_deny(data):\n    raise RuntimeError('boom')\n"
    )
    # enforce-tier.py: omitted entirely (an import failure) - the raising
    # sibling alone must already be enough to prove no false deny/no
    # suppressed persistence; not copying the second keeps this test
    # focused on the RAISE path specifically.

    config_dir = tmp_path / "claude-config"
    _write_settings(config_dir / "settings.json", ["enforce-skeptic-neutrality.py"])

    diff_key = "sibling-deny-would-deny-raises-unit"
    # A payload that, if a REAL neutrality hook were consulted, WOULD be
    # denied (untagged field 7) - proving the raise, not a benign payload,
    # is what's being tolerated here.
    prompt = _prompt(
        diff_key,
        what_to_review="Worker fixed issue #1, round 1.",
        field7="This claim has no tag at all.",
    )
    payload = _payload(cwd, prompt, tool_use_id="tuid-1")

    env = _isolated_env(config_dir)
    code, parsed = _run_hook(scratch_hooks / _ROUND_CAP_HOOK.name, payload, env=env)
    assert code == 0
    assert not _is_denied(parsed), "round-cap itself must never deny because a sibling's would_deny raised"

    state_files = _state_files(cwd)
    assert len(state_files) == 1, "a raising would_deny must never suppress persistence"
    state = json.loads(state_files[0].read_text())
    assert state["round_count"] == 1


# --------------------------------------------------------------------------- #
# 7. Fail direction: a sibling module with NO would_deny attribute is simply
#    excluded from consultation
# --------------------------------------------------------------------------- #
def test_sibling_missing_would_deny_attribute_falls_back(tmp_path):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)

    scratch_hooks = _scratch_hooks_dir(tmp_path)
    # Imports fine, but defines no `would_deny` at all.
    (scratch_hooks / "enforce-skeptic-neutrality.py").write_text("SOME_CONSTANT = 1\n")

    config_dir = tmp_path / "claude-config"
    _write_settings(config_dir / "settings.json", ["enforce-skeptic-neutrality.py"])

    diff_key = "sibling-deny-no-would-deny-attr-unit"
    prompt = _prompt(diff_key, what_to_review="Worker fixed issue #1, round 1.")
    payload = _payload(cwd, prompt, tool_use_id="tuid-1")

    env = _isolated_env(config_dir)
    code, parsed = _run_hook(scratch_hooks / _ROUND_CAP_HOOK.name, payload, env=env)
    assert code == 0
    assert not _is_denied(parsed)

    state_files = _state_files(cwd)
    assert len(state_files) == 1
    state = json.loads(state_files[0].read_text())
    assert state["round_count"] == 1


# --------------------------------------------------------------------------- #
# 8. Major 1: registration confirmed via PROJECT-level .claude/settings.json
# --------------------------------------------------------------------------- #
def test_registered_sibling_via_project_settings_is_consulted(tmp_path):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)
    # Project-level settings, registered under the UNIT's own repo root
    # (cwd), no CLAUDE_CONFIG_DIR entry at all.
    _write_settings(Path(cwd) / ".claude" / "settings.json", ["enforce-skeptic-neutrality.py"])

    diff_key = "sibling-deny-project-settings-unit"
    prompt = _prompt(
        diff_key,
        what_to_review="Worker fixed issue #1, round 1.",
        field7="This claim has no tag at all.",
    )
    payload = _payload(cwd, prompt, tool_use_id="tuid-1")

    # Empty, otherwise-unregistered user-level config dir - registration
    # must be found via the PROJECT-level file alone.
    empty_config_dir = tmp_path / "claude-config-empty"
    empty_config_dir.mkdir()
    env = _isolated_env(empty_config_dir)

    rc_code, rc_parsed = _run_hook(_ROUND_CAP_HOOK, payload, env=env)
    assert rc_code == 0
    assert not _is_denied(rc_parsed)
    assert _state_files(cwd) == [], (
        "project-level .claude/settings.json registration must be enough to "
        "confirm the sibling and trigger consultation"
    )


# --------------------------------------------------------------------------- #
# Minor 2 (round-3 rework): registration must be scoped to the spawn's own
# tool_name - a sibling registered on ONLY "Task" must not be treated as
# registered for an "Agent" spawn, and vice versa.
# --------------------------------------------------------------------------- #
def test_registration_scoped_to_spawn_tool_name(tmp_path):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)
    # Registered ONLY on "Task" - the spawn below uses tool_name "Agent".
    config_dir = tmp_path / "claude-config"
    _write_settings_single_matcher(
        config_dir / "settings.json", ["enforce-skeptic-neutrality.py"], matcher="Task"
    )

    diff_key = "sibling-deny-matcher-scope-unit"
    prompt = _prompt(
        diff_key,
        what_to_review="Worker fixed issue #1, round 1.",
        field7="This claim has no tag at all.",  # would deny IF consulted
    )
    payload = _payload(cwd, prompt, tool_use_id="tuid-1", tool_name="Agent")

    env = _isolated_env(config_dir)
    rc_code, rc_parsed = _run_hook(_ROUND_CAP_HOOK, payload, env=env)
    assert rc_code == 0
    assert not _is_denied(rc_parsed)

    state_files = _state_files(cwd)
    assert len(state_files) == 1, (
        "a Task-only registration must not be treated as registered for an "
        "Agent spawn - registration is scoped to the spawn's own tool_name, "
        "not 'either matcher'"
    )
    state = json.loads(state_files[0].read_text())
    assert state["round_count"] == 1

    # Control: the SAME registration (Task-only) genuinely IS consulted for
    # a Task spawn - proves the scoping is about matching, not a blanket
    # "single-matcher registrations never count."
    diff_key2 = "sibling-deny-matcher-scope-unit-2"
    prompt2 = _prompt(
        diff_key2,
        what_to_review="Worker fixed issue #1, round 1.",
        field7="This claim has no tag at all.",
    )
    payload2 = _payload(cwd, prompt2, tool_use_id="tuid-2", tool_name="Task")
    rc2_code, rc2_parsed = _run_hook(_ROUND_CAP_HOOK, payload2, env=env)
    assert rc2_code == 0
    assert not _is_denied(rc2_parsed)
    assert len(_state_files(cwd)) == 1, (
        "a Task-registered sibling must be consulted for a genuine Task "
        "spawn, and consultation must still result in no NEW state file"
    )


# --------------------------------------------------------------------------- #
# 9-11. Major 1: registration UNCONFIRMED -> today's behavior (charge the
#        round) even though the sibling would have denied
# --------------------------------------------------------------------------- #
def test_unregistered_sibling_leaves_todays_behavior(tmp_path):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)
    # No project-level .claude/ dir at all, and an EMPTY user-level config
    # dir (no settings.json anywhere) - registration cannot be confirmed.
    empty_config_dir = tmp_path / "claude-config-empty"
    empty_config_dir.mkdir()

    diff_key = "sibling-deny-unregistered-unit"
    prompt = _prompt(
        diff_key,
        what_to_review="Worker fixed issue #1, round 1.",
        field7="This claim has no tag at all.",  # would deny IF consulted
    )
    payload = _payload(cwd, prompt, tool_use_id="tuid-1")

    _, neut_parsed = _run_hook(_NEUTRALITY_HOOK, payload)
    assert _is_denied(neut_parsed), "precondition failed: neutrality did not deny the untagged field-7 payload"

    env = _isolated_env(empty_config_dir)
    rc_code, rc_parsed = _run_hook(_ROUND_CAP_HOOK, payload, env=env)
    assert rc_code == 0
    assert not _is_denied(rc_parsed)

    state_files = _state_files(cwd)
    assert len(state_files) == 1, (
        "Major 1: an UNCONFIRMED sibling registration must never be treated as "
        "'would deny' - round-cap must persist exactly as it did before the "
        "sibling-deny consultation existed"
    )
    state = json.loads(state_files[0].read_text())
    assert state["round_count"] == 1


def test_malformed_settings_json_leaves_todays_behavior(tmp_path):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)
    config_dir = tmp_path / "claude-config"
    settings_path = config_dir / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text("{not valid json,,,")

    diff_key = "sibling-deny-malformed-settings-unit"
    prompt = _prompt(
        diff_key,
        what_to_review="Worker fixed issue #1, round 1.",
        field7="This claim has no tag at all.",
    )
    payload = _payload(cwd, prompt, tool_use_id="tuid-1")

    env = _isolated_env(config_dir)
    rc_code, rc_parsed = _run_hook(_ROUND_CAP_HOOK, payload, env=env)
    assert rc_code == 0
    assert not _is_denied(rc_parsed)

    state_files = _state_files(cwd)
    assert len(state_files) == 1, "a malformed settings.json must be treated as registration-unconfirmed"
    state = json.loads(state_files[0].read_text())
    assert state["round_count"] == 1


def test_unreadable_settings_leaves_todays_behavior(tmp_path):
    cwd = str(tmp_path / "repo")
    Path(cwd).mkdir()
    _ensure_git_marker(cwd)
    config_dir = tmp_path / "claude-config"
    settings_path = config_dir / "settings.json"
    _write_settings(settings_path, ["enforce-skeptic-neutrality.py"])
    settings_path.chmod(0o000)
    try:
        if os.access(settings_path, os.R_OK):
            pytest.skip("test runner can read a chmod-000 file (likely root) - cannot exercise this path")

        diff_key = "sibling-deny-unreadable-settings-unit"
        prompt = _prompt(
            diff_key,
            what_to_review="Worker fixed issue #1, round 1.",
            field7="This claim has no tag at all.",
        )
        payload = _payload(cwd, prompt, tool_use_id="tuid-1")

        env = _isolated_env(config_dir)
        rc_code, rc_parsed = _run_hook(_ROUND_CAP_HOOK, payload, env=env)
        assert rc_code == 0
        assert not _is_denied(rc_parsed)

        state_files = _state_files(cwd)
        assert len(state_files) == 1, "an unreadable settings.json must be treated as registration-unconfirmed"
        state = json.loads(state_files[0].read_text())
        assert state["round_count"] == 1
    finally:
        settings_path.chmod(0o644)


# --------------------------------------------------------------------------- #
# 12. Drift guard: every registered Task/Agent spawn-matcher hook is
#     classified
# --------------------------------------------------------------------------- #
# Tolerant of BOTH the multi-line and a one-line `upsert_hook(ptu_block[
# "hooks"], "name", ...)` call shape - `\s*` already matches across a
# newline without needing one literally present.
_UPSERT_HOOK_RE = re.compile(r'upsert_hook\(\s*ptu_block\["hooks"\],\s*"([^"]+)"')

# Deny-capability signal, tolerant of JSON key/value spacing variants
# (`"permissionDecision":"deny"`, extra whitespace, ...) and of the
# documented (not currently used by any hook, but explicitly named as the
# fallback path in several hooks' own Failure modes sections) exit-code-2
# deny convention for pre-permissionDecision Claude Code versions.
_DENY_MARKER_RE = re.compile(r'"permissionDecision"\s*:\s*"deny"')
_EXIT_CODE_2_DENY_RE = re.compile(r'sys\.exit\(\s*2\s*\)')


def _is_deny_capable_source(src: str) -> bool:
    return bool(_DENY_MARKER_RE.search(src) or _EXIT_CODE_2_DENY_RE.search(src))


# Never emits a deny decision at all (proven below by asserting the
# deny-capability signal is absent from its source) - genuinely out of
# scope for this hook's sibling-deny consultation, not merely un-consulted.
_NEVER_DENIES = frozenset({
    "enforce-nested-worktree-spawn.py",
    "pre-tool-use-spawn-emit.js",
})

# Deny-capable in general, but structurally UNABLE to deny a
# `subagent_type == "skeptic"` spawn specifically - proven per-entry below
# by regex-extracting the named role-gate set and asserting "skeptic" is
# absent from it, not merely asserted by omission.
_CANNOT_DENY_SKEPTIC = {
    "enforce-worktree-isolation-spawn.py": re.compile(r'MANDATED_ROLES\s*=\s*frozenset\(\{([^}]*)\}\)'),
}


def _registered_task_agent_spawn_hooks() -> list[str]:
    """Parse .claude/install.sh's `for spawn_matcher in ("Task", "Agent"):`
    block and return every `upsert_hook(ptu_block["hooks"], "<name>", ...)`
    basename registered inside it, in source order, deduped."""
    text = _INSTALL_SH.read_text(encoding="utf-8")
    start_marker = 'for spawn_matcher in ("Task", "Agent"):'
    start = text.index(start_marker)
    # The block ends at the next top-level "# ----" section comment after
    # the spawn-emit telemetry hook registration.
    end_marker = '# ---- PreToolUse ticket-batching guard'
    end = text.index(end_marker, start)
    block = text[start:end]
    names = _UPSERT_HOOK_RE.findall(block)
    assert names, "drift-guard parser found zero upsert_hook() registrations - regex is stale, fix it"
    seen = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return seen


def test_drift_guard_every_registered_spawn_hook_is_classified():
    module = _load_round_cap_module()
    registered = _registered_task_agent_spawn_hooks()

    # Sanity: the parser must find hooks known to exist today, or it is
    # silently parsing the wrong block.
    assert "enforce-skeptic-round-cap.py" in registered
    assert "enforce-skeptic-neutrality.py" in registered
    assert "enforce-tier.py" in registered

    consulted = {f"{name}.py" for name in module._SIBLING_MODULES}
    known_gap = set(module._KNOWN_UNCONSULTED_DENY_CAPABLE)

    # fix/round-cap-all-siblings: enforce-background-spawn.py and
    # enforce-orchestrator-singularity.py moved from _KNOWN_UNCONSULTED_
    # DENY_CAPABLE into _SIBLING_MODULES (consulted), leaving no known
    # gap - assert the set is genuinely empty rather than merely small.
    assert known_gap == set(), (
        f"_KNOWN_UNCONSULTED_DENY_CAPABLE should be empty now that both prior "
        f"entries are consulted, found: {known_gap!r}"
    )
    assert "enforce-background-spawn.py" in consulted
    assert "enforce-orchestrator-singularity.py" in consulted

    unclassified = []
    for name in registered:
        if name == "enforce-skeptic-round-cap.py":
            continue
        if name in consulted or name in known_gap or name in _NEVER_DENIES or name in _CANNOT_DENY_SKEPTIC:
            continue
        unclassified.append(name)

    assert unclassified == [], (
        f"registered Task/Agent spawn-matcher hook(s) {unclassified!r} are not "
        "classified in enforce-skeptic-round-cap.py's _SIBLING_MODULES, "
        "_KNOWN_UNCONSULTED_DENY_CAPABLE, or this test's _NEVER_DENIES / "
        "_CANNOT_DENY_SKEPTIC - classify the new hook before this test can pass"
    )

    # enforce-worktree-isolation-spawn.py must not ALSO be in the known-gap
    # set (round-2 rework, Minor 1: a hook is either "deny-capable for
    # skeptic but unconsulted" or "structurally cannot deny a skeptic
    # spawn" - never both).
    assert not (known_gap & set(_CANNOT_DENY_SKEPTIC)), (
        f"{known_gap & set(_CANNOT_DENY_SKEPTIC)!r} appear in both "
        "_KNOWN_UNCONSULTED_DENY_CAPABLE and _CANNOT_DENY_SKEPTIC"
    )

    # _NEVER_DENIES entries must genuinely never emit a deny decision -
    # keeps that allowlist honest rather than a silent escape hatch.
    for name in _NEVER_DENIES:
        if name.endswith(".py"):
            src = (_HOOKS_DIR / name).read_text(encoding="utf-8")
            assert not _is_deny_capable_source(src), (
                f"{name} is listed in _NEVER_DENIES but its source contains a "
                "deny-capability signal - it must be classified as deny-capable instead"
            )

    # known_gap entries must genuinely BE deny-capable - keeps that
    # allowlist honest too (not a dumping ground for anything unclassified).
    for name in known_gap:
        src = (_HOOKS_DIR / name).read_text(encoding="utf-8")
        assert _is_deny_capable_source(src), (
            f"{name} is listed in _KNOWN_UNCONSULTED_DENY_CAPABLE but its "
            "source has no deny-capability signal - it should not be in this list"
        )

    # _CANNOT_DENY_SKEPTIC entries must be structurally proven, not just
    # asserted: the named role-gate set must genuinely exist AND must
    # genuinely not contain "skeptic".
    for name, role_set_re in _CANNOT_DENY_SKEPTIC.items():
        src = (_HOOKS_DIR / name).read_text(encoding="utf-8")
        m = role_set_re.search(src)
        assert m, (
            f"{name} is listed in _CANNOT_DENY_SKEPTIC but the expected role-gate "
            f"pattern {role_set_re.pattern!r} was not found in its source - "
            "the structural proof this classification depends on no longer holds"
        )
        assert '"skeptic"' not in m.group(1), (
            f"{name}'s role-gate set now includes \"skeptic\" - it CAN deny a "
            "skeptic spawn and must move to _KNOWN_UNCONSULTED_DENY_CAPABLE "
            "(or be consulted) instead of _CANNOT_DENY_SKEPTIC"
        )


# --------------------------------------------------------------------------- #
# 13. Drift guard still fails for a new unclassified deny-capable hook, even
#     with an empty _KNOWN_UNCONSULTED_DENY_CAPABLE - proves the drift guard
#     is a genuine gate, not one that trivially passes because there is
#     nothing left to classify.
# --------------------------------------------------------------------------- #
def test_drift_guard_still_catches_a_new_unclassified_hook():
    module = _load_round_cap_module()
    consulted = {f"{name}.py" for name in module._SIBLING_MODULES}
    known_gap = set(module._KNOWN_UNCONSULTED_DENY_CAPABLE)
    assert known_gap == set(), "precondition: known-unconsulted set must be empty for this test to be meaningful"

    # Same classification logic as test_drift_guard_every_registered_spawn_
    # hook_is_classified, applied to a SYNTHETIC registered list carrying one
    # fabricated, genuinely unclassified hook name alongside the real ones.
    synthetic_registered = list(_registered_task_agent_spawn_hooks()) + [
        "enforce-a-brand-new-hook-nobody-classified-yet.py"
    ]
    unclassified = [
        name
        for name in synthetic_registered
        if name != "enforce-skeptic-round-cap.py"
        and name not in consulted
        and name not in known_gap
        and name not in _NEVER_DENIES
        and name not in _CANNOT_DENY_SKEPTIC
    ]
    assert unclassified == ["enforce-a-brand-new-hook-nobody-classified-yet.py"], (
        f"expected exactly the synthetic unclassified hook to surface, got: {unclassified!r}"
    )
