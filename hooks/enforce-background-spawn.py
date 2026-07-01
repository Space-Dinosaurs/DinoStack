#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that enforces three METHODOLOGY rules on Claude Code:
         (1) Background-by-default rule - denies any `Task` spawn (LEGACY tool
         name) that lacks run_in_background: true. `Agent` spawns are NOT
         background-enforced here: the Claude Code harness strips
         run_in_background from the hook payload for Agent tool calls (verified
         by live PreToolUse payload capture - tool_input keys for an Agent spawn
         are exactly ['description', 'prompt', 'subagent_type']; run_in_background
         is consumed by the harness for its own async routing and never reaches
         the hook). Agent is background-by-default at the harness level, so
         there is nothing to enforce; applying the check would brick every Agent
         spawn. Background enforcement therefore applies to the legacy `Task`
         tool name only.
         (2) Cross-harness team ROUTING enforcement (proactive) - when an
         effective team.yml has `enabled: true` and the spawned subagent_type is
         a dispatchable role (engineer/debugger/qa-engineer/skeptic/
         security-auditor) whose resolved harness (role entry, else
         default_harness) is anything OTHER than "claude", the native Task/Agent
         spawn is denied with an actionable `bin/agentic-team dispatch ...`
         instruction. This fixes the chicken-and-egg bug where team.yml was
         silently ignored because the (2)-below sentinel-based suppression only
         ever activates AFTER the first dispatch. Fail-open on any config load
         error; escape hatch AE_TEAM_ROUTING_DISABLE=1 skips this branch
         entirely.
         (3) Cross-harness team sentinel suppression - when a DinoStack cross-
         harness team run is active (sentinel <cwd>/.agentic/teamrun/.active
         exists and is LIVE), denies Task/Agent spawns outright AND denies Skill
         calls whose skill name starts with "oh-my-claudecode:" (OMC-skill
         detection). Tells the conductor to use `bin/agentic-team dispatch`.
         The sentinel is treated as EXPIRED (suppression lifted) when the PID it
         names is dead OR its mtime is older than 2 h - so a crashed conductor
         does not permanently suppress native spawns. Sentinel suppression
         applies to BOTH Task and Agent tool names.

         NOTE - Task/Agent rename and run_in_background visibility: Claude Code
         renamed the subagent-spawn tool from "Task" to "Agent". For routing
         enforcement and sentinel suppression, the hook guards on BOTH names -
         this is correct and unchanged. For background-spawn enforcement, only
         `Task` is checked: the harness does NOT pass run_in_background to the
         hook for Agent spawns, so enforcing it on Agent would deny every Agent
         call regardless of intent. The settings.json matcher is wired for both
         names by install.sh (two PreToolUse blocks: one for "Task", one for
         "Agent") so the hook fires under either name and applies routing/
         sentinel suppression correctly. Background enforcement applies to the
         legacy `Task` path only for backward compatibility.

         Confirmed-supported floor: permissionDecision: "deny" output is stable
         on recent Claude Code builds. The hook fails open on parse error, so
         older builds degrade to no-enforcement rather than breaking.

Public API: Run as a Claude Code PreToolUse hook (matcher: "Task", "Agent", or
            "Skill"). Reads JSON from stdin, writes hookSpecificOutput JSON to
            stdout when denying, exits 0 always.

Upstream deps: Python 3 stdlib only (json, os, sys, time, pathlib). PyYAML is
               imported opportunistically inside try/except for team.yml
               parsing - never a hard dependency; fails open when unavailable.

Downstream consumers: Claude Code hook runner (PreToolUse event for Task, Agent,
                      and Skill tools). Wired via ~/.claude/settings.json by
                      .claude/install.sh (matcher blocks for "Task", "Agent",
                      and "Skill" - no new wiring needed beyond those matchers).

Failure modes:
    - Malformed stdin: fail-open (exit 0, no deny). A hook bug must never brick
      all spawns - the conductor can still work, just without enforcement.
    - Null or non-dict tool_input: fail-open (exit 0). Same contract - any parse
      or logic error exits 0 so enforcement gaps are never converted to blanket
      blocks.
    - Non-Task/Agent/Skill tool_name: passthrough (exit 0).
    - run_in_background absent, false, or non-boolean on Task (legacy tool only):
      deny with reason fed back to model. Only boolean True is accepted as the
      allow signal. Agent spawns are NOT checked - run_in_background is stripped
      from the hook payload by the harness before the hook fires.
    - Foreground-exempt subagent_type (FOREGROUND_EXEMPT): allow regardless of
      run_in_background - these agents have a documented blocking-ordering
      requirement (e.g. wrap-ticket holds .agentic/wrap.lock). Exemption is
      checked FIRST, before routing enforcement and sentinel suppression, so an
      exempt agent is allowed even while a team run is live/configured.
    - Team routing: missing team.yml (global and project), unreadable file,
      malformed YAML, PyYAML not importable, `enabled` absent/false, role not in
      the dispatchable set, or resolved harness == "claude" -> allow (fall
      through to sentinel suppression / background enforcement). Any exception
      during config load or resolution -> allow (fail-open).
    - AE_TEAM_ROUTING_DISABLE=1 -> team routing branch is skipped entirely,
      unconditionally (env var checked before any file I/O).
    - Sentinel present but PID dead or mtime > 2 h: sentinel treated as expired;
      normal background-spawn enforcement resumes. The sentinel self-expires
      when its conductor PID is dead or its mtime exceeds 2 h; there is no
      manual clear command. Fail-open on sentinel read errors.
    - Agent spawn (no live sentinel, no routing match): always allowed (exits 0
      at the enforcement gate - run_in_background is not present in the real
      harness payload).

Performance: < 5 ms per call (in-memory JSON parse + optional YAML parse of two
             small config files + optional stat/proc check, no network I/O).
"""

import json
import os
import sys
import time
from pathlib import Path

# Dispatchable roles: only these are subject to team-routing enforcement.
# Per content/references/cross-harness-teams.md, conductor, investigator,
# architect, and orchestration-planner always stay native even if team.yml
# maps them elsewhere (their team.yml entries are advisory only).
_DISPATCHABLE_ROLES = frozenset({
    "engineer", "debugger", "qa-engineer", "skeptic", "security-auditor",
})

_GLOBAL_TEAM_YML_REL = "~/.agentic/team.yml"
_PROJECT_TEAM_YML_REL = ".agentic/team.yml"


def _load_effective_team_config(cwd: str) -> dict:
    """Load and shallow-merge global + project team.yml (project wins).

    Mirrors bin/agentic-team's _load_team_config merge semantics: read global
    then project, project overwrites per top-level key. PyYAML is imported
    locally so a hook-context environment without it degrades to an empty
    config (fail-open) rather than crashing. Any error anywhere (missing
    file, unreadable, malformed YAML, import failure) is swallowed and
    contributes nothing to the merged config - never raises.
    """
    try:
        import yaml  # type: ignore
    except Exception:
        return {}

    config: dict = {}
    paths = [
        Path(os.path.expanduser(_GLOBAL_TEAM_YML_REL)),
        Path(cwd) / _PROJECT_TEAM_YML_REL,
    ]
    for path in paths:
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            parsed = yaml.safe_load(text)
            if isinstance(parsed, dict):
                config.update(parsed)
        except Exception:
            # Fail-open per-file: a broken global file must not prevent the
            # project file from loading, and vice versa.
            continue
    return config


def _resolve_role_harness(config: dict, role: str) -> tuple[str | None, str | None]:
    """Resolve the effective harness + model for *role* from *config*.

    Role entry (scalar string or {harness, model} mapping) takes precedence;
    falls back to top-level default_harness (model is None in that case,
    since default_harness carries no model). Returns (None, None) when
    neither a role entry nor a default_harness is present.
    """
    roles = config.get("roles")
    entry = roles.get(role) if isinstance(roles, dict) else None
    if isinstance(entry, str) and entry:
        return entry, None
    if isinstance(entry, dict):
        harness = entry.get("harness")
        model = entry.get("model")
        if harness:
            return harness, model
    default_harness = config.get("default_harness")
    if isinstance(default_harness, str) and default_harness:
        return default_harness, None
    return None, None

# Documented foreground-exempt agents. wrap-ticket runs foreground/blocking
# in /implement-ticket Phase 11b: it holds .agentic/wrap.lock and MUST complete
# before Phase 12 cleanup, so it cannot be forced to background. This is the
# only methodology-sanctioned foreground spawn. Add others here only with
# an equivalent documented blocking-ordering requirement.
FOREGROUND_EXEMPT = {"wrap-ticket"}

# Sentinel path relative to cwd.
_SENTINEL_REL = ".agentic/teamrun/.active"

# Maximum age (seconds) before a sentinel is treated as stale regardless of PID.
_SENTINEL_MAX_AGE_S = 2 * 60 * 60  # 2 hours

def _sentinel_is_live(cwd: str) -> bool:
    """Return True iff the DinoStack team sentinel is present AND live.

    Live = file exists AND PID on first line is alive AND mtime <= 2 h old.
    Any I/O or parse error returns False (fail-open - suppression never sticks
    on a broken sentinel file).
    """
    sentinel = Path(cwd) / _SENTINEL_REL
    try:
        if not sentinel.exists():
            return False

        age = time.time() - sentinel.stat().st_mtime
        if age > _SENTINEL_MAX_AGE_S:
            return False

        first_line = sentinel.read_text(encoding="utf-8").splitlines()[0].strip()
        pid = int(first_line)

        # os.kill(pid, 0) raises OSError when the process does not exist.
        # NOTE: PID reuse - if the original conductor died and the OS recycled
        # its PID to a different process within the 2 h mtime window, this
        # check gives a false-live result. The mtime cap (_SENTINEL_MAX_AGE_S)
        # is the backstop: a sentinel older than 2 h is treated as expired
        # regardless of whether the PID happens to be alive.
        try:
            os.kill(pid, 0)
        except OSError:
            return False

        return True
    except Exception:
        # Any read/parse/stat error -> treat as absent (fail-open).
        return False

def _deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)

def main() -> None:
    try:
        # Fail-open: never block on malformed input - a broken hook must not
        # prevent the conductor from spawning workers at all.
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        tool_name = data.get("tool_name")

        # ------------------------------------------------------------------ #
        # Foreground-exempt check (MUST come before sentinel suppression)    #
        # wrap-ticket holds .agentic/wrap.lock and MUST complete before      #
        # Phase 12 cleanup - it is the only sanctioned foreground spawn.     #
        # Exemption applies regardless of sentinel state, so check first.    #
        # Skill is NOT foreground-exempt - only Task/Agent spawns.           #
        # ------------------------------------------------------------------ #
        if tool_name in ("Task", "Agent"):
            raw_tinput_early = data.get("tool_input")
            tinput_early = raw_tinput_early if isinstance(raw_tinput_early, dict) else {}
            if tinput_early.get("subagent_type") in FOREGROUND_EXEMPT:
                sys.exit(0)

        # ------------------------------------------------------------------ #
        # Cross-harness team ROUTING enforcement (proactive, fixes the core  #
        # bug: team.yml was silently ignored until the FIRST dispatch ever   #
        # created the sentinel). Runs BEFORE sentinel suppression.          #
        # Escape hatch: AE_TEAM_ROUTING_DISABLE=1 skips this branch          #
        # unconditionally, before any file I/O.                              #
        # ------------------------------------------------------------------ #
        if tool_name in ("Task", "Agent") and os.environ.get("AE_TEAM_ROUTING_DISABLE") != "1":
            raw_tinput_route = data.get("tool_input")
            tinput_route = raw_tinput_route if isinstance(raw_tinput_route, dict) else {}
            role = tinput_route.get("subagent_type")
            if isinstance(role, str) and role in _DISPATCHABLE_ROLES:
                cwd_route = data.get("cwd") or os.getcwd()
                try:
                    team_config = _load_effective_team_config(cwd_route)
                    if team_config.get("enabled") is True:
                        harness, model = _resolve_role_harness(team_config, role)
                        if harness and harness != "claude":
                            model_note = f" (model {model})" if model else ""
                            model_flag = f" --model {model}" if model else ""
                            _deny(
                                f"cross-harness team active: role '{role}' is assigned to "
                                f"harness '{harness}'{model_note}. Dispatch with: "
                                f"bin/agentic-team dispatch --harness {harness} --role {role} "
                                f"--brief <file> --workdir <dir>{model_flag} - then poll "
                                "status/collect."
                            )
                except Exception:
                    # Fail-open: any config-load/resolution error allows the
                    # native spawn through unchanged.
                    pass

        # ------------------------------------------------------------------ #
        # Cross-harness sentinel suppression                                 #
        # Applies to non-exempt Task/Agent spawns and oh-my-claudecode:*     #
        # Skills. Exempt agents (wrap-ticket) already exited above.          #
        # ------------------------------------------------------------------ #
        if tool_name in ("Task", "Agent", "Skill"):
            cwd = data.get("cwd") or os.getcwd()
            if _sentinel_is_live(cwd):
                if tool_name in ("Task", "Agent"):
                    _deny(
                        f"{tool_name} spawn blocked: a DinoStack cross-harness team "
                        "run is active (.agentic/teamrun/.active sentinel present and "
                        "live). Dispatch workers via `bin/agentic-team dispatch` "
                        "instead of native spawns. To resume native delegation, wait "
                        "for the team run to complete. The sentinel self-expires when "
                        "its conductor PID is dead or its mtime exceeds 2 h; there is "
                        "no manual clear command."
                    )
                # SKILL-ONLY sub-block: only tool_name == "Skill" reaches here -
                # Task/Agent were _deny()'d outright above and never enter this
                # block. We block oh-my-claudecode:* Skills while a team run owns
                # dispatch.
                # The Claude Code Skill tool passes the skill name in
                # tool_input["skill"] - confirmed by PreToolUse payload
                # inspection and the existing test fixtures in
                # bin/tests/test_enforce_background_spawn.py.
                # We do NOT fall back to a "name" field: an absent or
                # unrecognised field means we cannot determine the skill -
                # fail-open (allow) rather than silently misidentify.
                tinput = data.get("tool_input")
                skill_name = ""
                if isinstance(tinput, dict):
                    raw = tinput.get("skill")
                    if isinstance(raw, str):
                        skill_name = raw
                if skill_name.startswith("oh-my-claudecode:"):
                    _deny(
                        f"Skill '{skill_name}' blocked: a DinoStack cross-harness "
                        "team run is active (.agentic/teamrun/.active sentinel "
                        "present and live). OMC skills must not be invoked while "
                        "the DinoStack team layer owns dispatch. Use "
                        "`bin/agentic-team dispatch` to assign work to workers."
                    )
                # Non-OMC Skill, Skill with absent/unrecognised field -> allow.
                sys.exit(0)
            # Sentinel not live -> fall through to background enforcement.

        # ------------------------------------------------------------------ #
        # Background-spawn enforcement (Task ONLY)                           #
        # Agent spawns are NOT enforced here: run_in_background is stripped  #
        # from the Agent PreToolUse payload by the harness before the hook   #
        # fires (confirmed by live payload capture). Agent is background-by- #
        # default at the harness level, so the check would deny every Agent  #
        # spawn regardless of intent. Only the legacy "Task" tool name        #
        # proceeds to this check; "Agent" (and anything else) exits 0.       #
        # Skill already exited above (via sentinel block or passthrough).    #
        # ------------------------------------------------------------------ #

        # Only enforce on the legacy Task tool name. Agent spawns exit here -
        # run_in_background is not present in the real harness payload for
        # Agent. All direct-action tools (Read, Bash, Write, Edit, etc.) are
        # not Task, so there are no false positives from this scoped deny.
        if tool_name != "Task":
            sys.exit(0)

        # tool_input may be null/missing. Null means no structured params -
        # treat as fail-open since we cannot make an enforcement decision
        # without a dict to inspect.
        raw_tinput = data.get("tool_input")
        if raw_tinput is None:
            sys.exit(0)
        tinput = raw_tinput if isinstance(raw_tinput, dict) else {}

        # Foreground-exempt agents were already allowed before the sentinel
        # suppression block above. Any spawn that reaches here is non-exempt.

        # Allow correctly-formed background spawns. Accept only boolean True -
        # string "false", 0, None, and other truthy-but-not-true values all deny.
        if tinput.get("run_in_background") is True:
            sys.exit(0)

        # Deny foreground Task spawns and feed back a clear, actionable reason
        # so the conductor re-issues with run_in_background: true.
        _deny(
            "Task spawn blocked: run_in_background is missing or false. "
            "All delegated subagent spawns MUST set run_in_background: true "
            "(METHODOLOGY.md §Delegation). Re-issue the Task call with "
            "run_in_background: true. Direct-action cases (reads, memory "
            "answers, synthesis) do not use it at all - use the appropriate "
            "dedicated tool instead."
        )

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open).
        # The fail-open promise must hold for every input shape.
        sys.exit(0)

if __name__ == "__main__":
    main()
