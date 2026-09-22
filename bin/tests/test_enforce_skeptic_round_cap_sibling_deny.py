#!/usr/bin/env python3
"""
Regression tests for the sibling-deny consultation added to
hooks/enforce-skeptic-round-cap.py (fix/round-cap-sibling-deny): a Skeptic
spawn round-cap would ALLOW but a sibling PreToolUse hook on the same
"Task"/"Agent" spawn matcher (enforce-skeptic-neutrality.py /
enforce-tier.py) independently DENIES must never advance round_count or
consume a recorded ship/escalate decision - see enforce-skeptic-round-cap.py's
"Sibling-deny consultation" docstring paragraph and content/references/
skeptic-protocol.md ~:431.

Test groups:
  1. test_neutrality_denied_spawn_leaves_no_state_file         - round-cap's own decision would ALLOW
                                                                 round 1, but neutrality denies (untagged
                                                                 field 7) -> no state file is ever written.
  2. test_tier_denied_spawn_leaves_no_state_file                - same shape, tier denies (explicit
                                                                 sub-Tier-3 model downgrade on a
                                                                 security-flavored brief).
  3. test_escalate_decision_preserved_when_sibling_denies       - SEVERE case: state at cap with
                                                                 decision:"escalate" recorded; a spawn
                                                                 with a new fingerprint that neutrality
                                                                 denies must leave round_count AND
                                                                 decision byte-unchanged - the operator's
                                                                 escalate authorization is not spent on a
                                                                 review that never ran.
  4. test_clean_spawn_still_advances_normally                   - control: a spawn no sibling denies
                                                                 advances state exactly as before this
                                                                 fix.
  5. test_broken_sibling_module_falls_back_to_original_persist  - a sibling module that fails to import
                                                                 (missing file) never blocks this hook's
                                                                 own persistence - fail direction: import
                                                                 failure means "persist as today," never
                                                                 "treat as denied."
  6. test_drift_guard_every_registered_spawn_hook_is_classified - parses .claude/install.sh's Task/Agent
                                                                 PreToolUse spawn-matcher registrations
                                                                 and asserts every registered enforce-*.py
                                                                 hook other than round-cap itself is
                                                                 either consulted (_SIBLING_MODULES),
                                                                 tracked as a known gap
                                                                 (_KNOWN_UNCONSULTED_DENY_CAPABLE), or
                                                                 explicitly proven never to deny
                                                                 (_NEVER_DENIES) - so a NEW deny-capable
                                                                 hook added to the matcher without
                                                                 classification fails this test.
"""

from __future__ import annotations

import importlib.util
import json
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
_INSTALL_SH = _REPO_ROOT / ".claude" / "install.sh"


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


def _payload(cwd: str, prompt: str, model: str | None = None, tool_use_id: str | None = None) -> dict:
    tinput = {"subagent_type": "skeptic", "description": "review", "prompt": prompt}
    if model is not None:
        tinput["model"] = model
    payload = {"tool_name": "Agent", "cwd": cwd, "tool_input": tinput}
    if tool_use_id is not None:
        payload["tool_use_id"] = tool_use_id
    return payload


def _run_hook(hook_path: Path, payload: dict, run_cwd: str | None = None) -> tuple[int, dict | None]:
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=run_cwd,
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


# --------------------------------------------------------------------------- #
# 1. Neutrality-denied spawn: no state file ever written
# --------------------------------------------------------------------------- #
def test_neutrality_denied_spawn_leaves_no_state_file(tmp_path):
    cwd = str(tmp_path)
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

    rc_code, rc_parsed = _run_hook(_ROUND_CAP_HOOK, payload)
    assert rc_code == 0
    assert not _is_denied(rc_parsed), "round-cap itself should allow (the sibling's own deny blocks the spawn)"
    assert _state_files(cwd) == [], "round-cap must not persist any state for a spawn a sibling would deny"


# --------------------------------------------------------------------------- #
# 2. Tier-denied spawn: no state file ever written
# --------------------------------------------------------------------------- #
def test_tier_denied_spawn_leaves_no_state_file(tmp_path):
    cwd = str(tmp_path)
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

    rc_code, rc_parsed = _run_hook(_ROUND_CAP_HOOK, payload)
    assert rc_code == 0
    assert not _is_denied(rc_parsed)
    assert _state_files(cwd) == [], "round-cap must not persist any state for a spawn a sibling would deny"


# --------------------------------------------------------------------------- #
# 3. Severe case: escalate decision preserved, not consumed
# --------------------------------------------------------------------------- #
def test_escalate_decision_preserved_when_sibling_denies(tmp_path):
    cwd = str(tmp_path)
    _ensure_git_marker(cwd)
    diff_key = "sibling-deny-escalate-unit"

    # Rounds 1-2: clean spawns (tagged/n-a field 7), distinct Worker output
    # each round so fingerprint coalescing does not collapse them.
    for i in (1, 2):
        prompt = _prompt(diff_key, what_to_review=f"Worker fixed issue #{i}, round {i}.")
        payload = _payload(cwd, prompt, tool_use_id=f"tuid-{i}")
        code, parsed = _run_hook(_ROUND_CAP_HOOK, payload)
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

    rc_code, rc_parsed = _run_hook(_ROUND_CAP_HOOK, payload3)
    assert rc_code == 0
    assert not _is_denied(rc_parsed)

    after = json.loads(state_path.read_text())
    assert after == before, (
        "state must be byte-unchanged after a sibling-denied spawn at cap with "
        f"decision=escalate: before={before!r} after={after!r}"
    )
    assert after["round_count"] == 2
    assert after["decision"] == "escalate"


# --------------------------------------------------------------------------- #
# 4. Control: a spawn no sibling denies still advances normally
# --------------------------------------------------------------------------- #
def test_clean_spawn_still_advances_normally(tmp_path):
    cwd = str(tmp_path)
    _ensure_git_marker(cwd)
    diff_key = "sibling-deny-clean-unit"

    prompt = _prompt(diff_key, what_to_review="Worker fixed issue #1, round 1.")
    payload = _payload(cwd, prompt, tool_use_id="tuid-1")

    code, parsed = _run_hook(_ROUND_CAP_HOOK, payload)
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
def test_broken_sibling_module_falls_back_to_original_persist_behavior(tmp_path):
    cwd = str(tmp_path / "repo")
    cwd_path = Path(cwd)
    cwd_path.mkdir()
    _ensure_git_marker(cwd)

    # Copy just the round-cap hook (and its lib/ deps) into a scratch hooks/
    # dir with the sibling modules DELETED, so `_load_sibling_would_deny_fns`
    # hits an import failure for every configured sibling.
    scratch_hooks = tmp_path / "hooks"
    scratch_hooks.mkdir()
    shutil.copy(_ROUND_CAP_HOOK, scratch_hooks / _ROUND_CAP_HOOK.name)
    shutil.copytree(_HOOKS_DIR / "lib", scratch_hooks / "lib")
    # Deliberately do NOT copy enforce-skeptic-neutrality.py or enforce-tier.py.

    diff_key = "sibling-deny-broken-import-unit"
    prompt = _prompt(diff_key, what_to_review="Worker fixed issue #1, round 1.")
    payload = _payload(cwd, prompt, tool_use_id="tuid-1")

    code, parsed = _run_hook(scratch_hooks / _ROUND_CAP_HOOK.name, payload)
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
# 6. Drift guard: every registered Task/Agent spawn-matcher hook is classified
# --------------------------------------------------------------------------- #
_UPSERT_HOOK_RE = re.compile(r'upsert_hook\(\s*\n\s*ptu_block\["hooks"\],\s*\n\s*"([^"]+)"')

# Never emits a deny decision at all (proven below by asserting the literal
# deny-JSON marker is absent from its source) - genuinely out of scope for
# this hook's sibling-deny consultation, not merely un-consulted.
_NEVER_DENIES = frozenset({
    "enforce-nested-worktree-spawn.py",
    "pre-tool-use-spawn-emit.js",
})


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

    unclassified = []
    for name in registered:
        if name == "enforce-skeptic-round-cap.py":
            continue
        if name in consulted or name in known_gap or name in _NEVER_DENIES:
            continue
        unclassified.append(name)

    assert unclassified == [], (
        f"registered Task/Agent spawn-matcher hook(s) {unclassified!r} are not "
        "classified in enforce-skeptic-round-cap.py's _SIBLING_MODULES, "
        "_KNOWN_UNCONSULTED_DENY_CAPABLE, or this test's _NEVER_DENIES - add "
        "the new hook to one of the three (consult it, name it as a known "
        "gap, or prove it never denies) before this test can pass"
    )

    # _NEVER_DENIES entries must genuinely never emit a deny decision -
    # keeps that allowlist honest rather than a silent escape hatch.
    for name in _NEVER_DENIES:
        if name.endswith(".py"):
            src = (_HOOKS_DIR / name).read_text(encoding="utf-8")
            assert '"permissionDecision": "deny"' not in src, (
                f"{name} is listed in _NEVER_DENIES but its source contains a "
                "deny-JSON marker - it must be classified as deny-capable instead"
            )

    # known_gap entries must genuinely BE deny-capable - keeps that
    # allowlist honest too (not a dumping ground for anything unclassified).
    for name in known_gap:
        src = (_HOOKS_DIR / name).read_text(encoding="utf-8")
        assert '"permissionDecision": "deny"' in src, (
            f"{name} is listed in _KNOWN_UNCONSULTED_DENY_CAPABLE but its "
            "source has no deny-JSON marker - it should not be in this list"
        )
