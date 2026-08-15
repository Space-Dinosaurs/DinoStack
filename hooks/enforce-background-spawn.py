#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that enforces three METHODOLOGY rules on Claude Code:
         (1) Background-by-default rule - denies foreground subagent spawns on
         both the legacy `Task` tool name and the current `Agent` tool name,
         with an ASYMMETRIC rule per tool. Live PreToolUse payload capture
         (2026-07-07) confirmed the harness DOES pass run_in_background
         through to the hook for Agent spawns (tool_input keys observed:
         description/prompt/run_in_background/subagent_type, value False) -
         this corrects the earlier assumption that the field was stripped,
         which had left Agent completely unenforced. `Task` (legacy): deny
         unless run_in_background is exactly boolean True - absent, false, or
         non-boolean all deny. `Agent` (current): deny ONLY when
         run_in_background is exactly boolean False; an ABSENT field allows
         (Agent backgrounds by default at the harness level, so omitting the
         field is the documented conductor norm - see METHODOLOGY.md
         §Delegation), and an explicit True also allows.
         (2) Cross-harness team ROUTING enforcement (proactive) - when an
         effective team.yml has `enabled: true` and the spawned subagent_type is
         a dispatchable role (engineer/debugger/qa-engineer/skeptic/
         security-auditor) whose resolved harness (role entry, else
         default_harness) is anything OTHER than "claude", the native Task/Agent
         spawn is denied with an actionable `bin/ds-team dispatch ...`
         instruction. This fixes the chicken-and-egg bug where team.yml was
         silently ignored because the (2)-below sentinel-based suppression only
         ever activates AFTER the first dispatch. Fail-open on any config load
         error; escape hatch AE_TEAM_ROUTING_DISABLE=1 skips this branch
         entirely.
         (3) Cross-harness team sentinel suppression - when a DinoStack cross-
         harness team run is active (sentinel <cwd>/.agentic/teamrun/.active
         exists and is LIVE), denies Task/Agent spawns outright AND denies Skill
         calls whose skill name starts with "oh-my-claudecode:" (OMC-skill
         detection). Tells the conductor to use `bin/ds-team dispatch`.
         The sentinel is treated as EXPIRED (suppression lifted) when the PID it
         names is dead OR its mtime is older than 2 h - so a crashed conductor
         does not permanently suppress native spawns. Sentinel suppression
         applies to BOTH Task and Agent tool names.

         NOTE - Task/Agent rename and run_in_background visibility: Claude Code
         renamed the subagent-spawn tool from "Task" to "Agent". For routing
         enforcement and sentinel suppression, the hook guards on BOTH names -
         this is correct and unchanged. For background-spawn enforcement, BOTH
         names are now checked (DS-70): the harness DOES pass run_in_background
         through for Agent spawns (2026-07-07 live capture), so the earlier
         Agent exemption was based on a false premise. The settings.json
         matcher is wired for both names by install.sh (two PreToolUse blocks:
         one for "Task", one for "Agent") so the hook fires under either name
         and applies routing/sentinel suppression and background enforcement
         correctly. See (1) above for the asymmetric Task-vs-Agent rule.

         Confirmed-supported floor: permissionDecision: "deny" output is stable
         on recent Claude Code builds. The hook fails open on parse error, so
         older builds degrade to no-enforcement rather than breaking.

Public API: Run as a Claude Code PreToolUse hook (matcher: "Task", "Agent", or
            "Skill"). Reads JSON from stdin, writes hookSpecificOutput JSON to
            stdout when denying, exits 0 always.

Upstream deps: Python 3 stdlib (json, os, sys, time, pathlib, importlib) for
               core enforcement. PyYAML is imported opportunistically inside
               try/except for team.yml parsing - never a hard dependency;
               fails open when unavailable. _known_harnesses() also has a
               runtime soft-dependency on bin/_role_spec.py (loaded via
               importlib.machinery.SourceFileLoader to read the canonical
               KNOWN_HARNESSES set) - if that file is missing or fails to
               load, _known_harnesses() falls back to an empty/minimal set
               and the harness is simply treated as unknown, which still
               fails safe (denies with a generic message; never crashes).
               Also a soft-dependency on the sibling hooks/lib/
               enforcement_log.py fire-logging helper (dynamic import, same
               fallback-to-no-op pattern as _known_harnesses()).

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
    - run_in_background absent, false, or non-boolean on Task (legacy tool
      only): deny with reason fed back to model. Only boolean True is
      accepted as the allow signal.
    - run_in_background exactly False on Agent (current tool name): deny with
      reason fed back to model. Absent (key not present) and True both allow
      - Agent backgrounds by default at the harness level, so an absent field
      is the documented conductor norm, not a violation.
    - Foreground-exempt subagent_type (FOREGROUND_EXEMPT): allow regardless of
      run_in_background - these agents have a documented blocking-ordering
      requirement (e.g. the conductor holds .agentic/wrap/lock while
      wrap-ticket runs, so wrap-ticket must complete synchronously before
      Phase 12 cleanup proceeds). Exemption is checked FIRST, before routing
      enforcement and sentinel suppression, so an exempt agent is allowed
      even while a team run is live/configured.
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
    - Agent spawn (no live sentinel, no routing match): allowed unless
      run_in_background is exactly False (see the asymmetric rule above);
      absent or True allows.
    - Resolved harness not in _known_harnesses() (unknown/typo'd harness in
      team.yml, or bin/_role_spec.py failed to load): deny with a generic,
      fully-static message that names the unknown harness but never
      references the `model` field - no code path in the unknown-harness
      branch interpolates untrusted team.yml text.
    - Resolved harness known: deny message names the (allowlist-validated)
      harness and a `bin/ds-team dispatch` command, but the free-text
      `model` value from team.yml is NEVER interpolated into the message -
      not even sanitized/truncated. The suggested dispatch command uses a
      literal `--model <model-from-team.yml>` placeholder so a malicious
      team.yml cannot inject arbitrary text into the LLM-facing deny
      message via the model field.

Performance: < 5 ms per call (in-memory JSON parse + optional YAML parse of two
             small config files + optional stat/proc check, no network I/O).
"""

from __future__ import annotations

import json
import os
import re
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

# Mirrors KNOWN_HARNESSES in bin/_role_spec.py (single source of truth for
# bin/ds-team + bin/ds-configure). _known_harnesses() below tries
# the real module first; this is only the fail-open fallback, kept in sync
# by hand - matches how _DISPATCHABLE_ROLES above is hand-duplicated too.
_KNOWN_HARNESSES_FALLBACK = frozenset({
    "codex", "gemini", "cursor-agent", "kimi", "pi", "omp", "claude",
})


def _load_log_fire():
    """Best-effort dynamic import of the shared fire-logging helper.

    Falls back to a no-op when the sibling module cannot be loaded (missing
    file, syntax error, snapshot copy drift) - fire-logging is additive
    telemetry, never a hard dependency of the enforcement decision itself.

    Called lazily from inside the deny branch (never at module scope) so the
    overwhelming majority of invocations - every silent allow - never read,
    compile, or exec this file at all.
    """
    try:
        import importlib.util as _ilu

        here = Path(__file__).resolve().parent
        mod_path = here / "lib" / "enforcement_log.py"
        spec = _ilu.spec_from_file_location("enforcement_log", str(mod_path))
        mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)
        return mod.log_fire
    except Exception:
        return lambda *a, **k: None


def _known_harnesses() -> frozenset:
    """Load the canonical KNOWN_HARNESSES from bin/_role_spec.py.

    Falls back to the hand-kept mirror on any import error (missing file,
    path layout change, etc.) - team.yml harness validation must never
    crash the hook.
    """
    try:
        import importlib.machinery as _im
        import importlib.util as _ilu

        rs_path = Path(__file__).resolve().parent.parent / "bin" / "_role_spec.py"
        loader = _im.SourceFileLoader("_role_spec", str(rs_path))
        spec = _ilu.spec_from_loader("_role_spec", loader)
        mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        loader.exec_module(mod)
        return mod.KNOWN_HARNESSES
    except Exception:
        return _KNOWN_HARNESSES_FALLBACK


def _safe_display(value, max_len: int = 40) -> str:
    """Strip control chars and truncate untrusted display text.

    *value* originates from a project-level team.yml, which a malicious PR
    can control - it must never carry control characters (e.g. embedded
    newlines) or unbounded length into an LLM-facing deny message.
    """
    if not value:
        return ""
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", str(value))
    return cleaned[:max_len]

_GLOBAL_TEAM_YML_REL = "~/.agentic/team.yml"
_PROJECT_TEAM_YML_REL = ".agentic/team.yml"


def _load_effective_team_config(cwd: str) -> dict:
    """Load and shallow-merge global + project team.yml (project wins).

    Mirrors bin/ds-team's _load_team_config merge semantics: read global
    then project, project overwrites per top-level key. PyYAML is imported
    locally so a hook-context environment without it degrades to an empty
    config (fail-open) rather than crashing. Any error anywhere (missing
    file, unreadable, malformed YAML, import failure) is swallowed and
    contributes nothing to the merged config - never raises.
    """
    try:
        import yaml  # type: ignore
    except Exception:
        print(
            "enforce-background-spawn: PyYAML unavailable, team-routing "
            "enforcement no-op (fail-open)",
            file=sys.stderr,
        )
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
# in /ds-implement-ticket Phase 11b: the conductor holds .agentic/wrap/lock
# for wrap-ticket's duration, and Phase 12 cleanup MUST wait for it to
# complete, so it cannot be forced to background. This is the only
# methodology-sanctioned foreground spawn. Add others here only with an
# equivalent documented blocking-ordering requirement.
FOREGROUND_EXEMPT = {"wrap-ticket"}

# Sentinel path relative to cwd.
#
# DS-175: this path is read off the raw Stop-hook payload cwd with no
# repo-root anchoring - the same unanchored-.agentic/-access class DS-171 U1
# fixed for bin/ds-identity's write-hook/resolve-hook. Deliberately deferred
# out of DS-171 U1's round-4 rework rather than fixed inline, because this
# check is read-only (it only gates whether a spawn nudge fires, never
# writes .agentic/ state) - see DS-175 for the follow-up anchoring fix.
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

def _deny(data: dict, reason: str) -> None:
    # Decision print comes FIRST, unconditionally. Telemetry is loaded and
    # called only after the decision has reached stdout, and is wrapped in
    # its own try/except so a raising log_fire (e.g. a signature mismatch
    # from a half-applied lib snapshot) can never suppress or follow this
    # deny - see hooks/lib/enforcement_log.py manifest "Failure modes".
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    try:
        _load_log_fire()(data, "enforce-background-spawn", "deny", reason)
    except Exception:
        pass
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
        # wrap-ticket runs foreground because the conductor holds            #
        # .agentic/wrap/lock for its duration; Phase 12 cleanup must         #
        # wait for it to complete - the only sanctioned foreground spawn.    #
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
                            if harness not in _known_harnesses():
                                # harness is untrusted (team.yml is project-
                                # controlled, e.g. a malicious PR) - do not
                                # echo it back into an LLM-facing message.
                                _deny(
                                    data,
                                    f"cross-harness team active: role '{role}' is "
                                    "assigned to a non-claude harness in team.yml; "
                                    "dispatch via bin/ds-team."
                                )
                            else:
                                # model is untrusted free text from team.yml
                                # (project-controlled, e.g. a malicious PR) -
                                # never interpolate it into an LLM-facing
                                # message. Reference team.yml generically
                                # instead; harness is allowlist-validated
                                # above so it may stay verbatim.
                                _deny(
                                    data,
                                    f"cross-harness team active: role '{role}' is assigned to "
                                    f"harness '{harness}'. Dispatch with: "
                                    f"bin/ds-team dispatch --harness {harness} --role {role} "
                                    "--brief <file> --workdir <dir> --model <model-from-team.yml> "
                                    "- then poll status/collect."
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
                        data,
                        f"{tool_name} spawn blocked: a DinoStack cross-harness team "
                        "run is active (.agentic/teamrun/.active sentinel present and "
                        "live). Dispatch workers via `bin/ds-team dispatch` "
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
                        data,
                        f"Skill '{skill_name}' blocked: a DinoStack cross-harness "
                        "team run is active (.agentic/teamrun/.active sentinel "
                        "present and live). OMC skills must not be invoked while "
                        "the DinoStack team layer owns dispatch. Use "
                        "`bin/ds-team dispatch` to assign work to workers."
                    )
                # Non-OMC Skill, Skill with absent/unrecognised field -> allow.
                sys.exit(0)
            # Sentinel not live -> fall through to background enforcement.

        # ------------------------------------------------------------------ #
        # Background-spawn enforcement (Task + Agent, asymmetric rule)       #
        # Live PreToolUse payload capture (2026-07-07) confirmed the harness #
        # DOES pass run_in_background through for Agent spawns (tool_input   #
        # keys observed: description/prompt/run_in_background/subagent_type,#
        # value False). The prior assumption that the harness strips the     #
        # field for Agent was false and had left Agent completely            #
        # unenforced. Rule (asymmetric because Agent is background-by-       #
        # default at the harness level and Task is not):                    #
        #   - Task (legacy): deny unless run_in_background is exactly True.  #
        #     Absent/false/non-boolean all deny (unchanged).                 #
        #   - Agent (current): deny ONLY when run_in_background is exactly   #
        #     False. Absent -> allow (harness already backgrounds by         #
        #     default; omitting the field is the documented conductor norm). #
        #     True -> allow.                                                 #
        # Skill already exited above (via sentinel block or passthrough).    #
        # Any other tool_name exits here (Read, Bash, Write, Edit, etc. are  #
        # never Task/Agent, so there are no false positives).                #
        # ------------------------------------------------------------------ #
        if tool_name not in ("Task", "Agent"):
            sys.exit(0)

        # tool_input may be null/missing. Null means no structured params -
        # treat as fail-open since we cannot make an enforcement decision
        # without a dict to inspect. Applies to both Task and Agent: an
        # invisible run_in_background field must never be treated as a deny
        # signal.
        raw_tinput = data.get("tool_input")
        if raw_tinput is None:
            sys.exit(0)
        tinput = raw_tinput if isinstance(raw_tinput, dict) else {}

        # Foreground-exempt agents were already allowed before the sentinel
        # suppression block above. Any spawn that reaches here is non-exempt.

        rib = tinput.get("run_in_background")

        if tool_name == "Agent":
            # Asymmetric rule: only an EXPLICIT False denies. Absent (key not
            # present) and True both allow - Agent backgrounds by default at
            # the harness level, so omitting the field is correct usage, not
            # a violation.
            if rib is False:
                _deny(
                    data,
                    "Agent spawn blocked: run_in_background is explicitly "
                    "false. All delegated subagent spawns MUST run in the "
                    "background (METHODOLOGY.md §Delegation). Omit "
                    "run_in_background entirely (Agent backgrounds by "
                    "default) or set it to true. Direct-action cases (reads, "
                    "memory answers, synthesis) do not spawn an Agent at "
                    "all - use the appropriate dedicated tool instead."
                )
            sys.exit(0)

        # tool_name == "Task" (legacy): only boolean True allows. String
        # "false", 0, None, and other truthy-but-not-true values all deny.
        if rib is True:
            sys.exit(0)

        # Deny foreground Task spawns and feed back a clear, actionable reason
        # so the conductor re-issues with run_in_background: true.
        _deny(
            data,
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
