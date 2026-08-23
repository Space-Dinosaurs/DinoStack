#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that mechanically enforces the worktree-isolation
         mandate in `content/sections/02-delegation.md:160-162` (restated in
         `content/sections/11-worktree-lifecycle.md`): every `engineer`,
         `qa-engineer`, and `release-orchestrator` spawn MUST set
         `isolation: "worktree"` on the Agent tool call, with NO exception
         (the Trivial-path solo `engineer` spawn is explicitly included).
         Before this hook, the rule had zero mechanical enforcement - a real
         session spawned nine `engineer` agents with no isolation and the
         predicted failure occurred (cross-engineer commit contamination).
         This hook converts that prose mandate into a hard PreToolUse deny.
         Retirement condition (Pillar-8 naming obligation, hooks/AGENTS.md
         §Registering a new enforce-*.py hook): this hook retires when
         EITHER (a) the Claude Code `Agent` tool itself guarantees worktree
         isolation for every spawn regardless of caller-supplied
         `isolation`, making the mandate structurally unbreakable at the
         harness level and this deny permanently unreachable, OR (b)
         `content/sections/02-delegation.md`'s worktree-isolation mandate
         is itself deleted or narrowed to no longer require `isolation:
         "worktree"` unconditionally on the three MANDATED_ROLES.

         Denies when `tool_name == "Agent"` AND `tool_input.subagent_type`
         is one of `{"engineer", "qa-engineer", "release-orchestrator"}`
         (MANDATED_ROLES below) AND `tool_input.isolation` is not exactly
         the string `"worktree"` - including when the `isolation` key is
         entirely ABSENT from the payload. This is now backed by a REAL
         PreToolUse stdin capture (project-scoped capture hook, this
         session, 2026-08-23; raw log gitignored, not shipped, and still
         growing as concurrent sessions append to it - the SHAPES below are
         the load-bearing evidence, not a pinned record count, which would
         go stale the next time anyone reads the live log): a with-isolation
         `Agent` spawn's `tool_input` keys were `['description', 'isolation',
         'prompt', 'subagent_type']` with `isolation == "worktree"`; a
         without-isolation `Agent` spawn's `tool_input` keys were
         `['description', 'prompt', 'subagent_type']` - no `isolation` key
         at all. Top-level payload keys observed on both captured shapes:
         `['cwd', 'effort', 'hook_event_name', 'permission_mode',
         'prompt_id', 'session_id', 'tool_input', 'tool_name',
         'tool_use_id', 'transcript_path']`. There is NO capture for
         `tool_name == "Task"` in this or any prior session's transcript -
         see the Trigger/deny-scope note below for how that gap is handled.
         `hooks/AGENTS.md` §"Spawn payload mechanics" independently lists
         `isolation` as a key in the `Agent` tool's schema (originally
         schema-derived, not a payload capture); that section has since
         been updated to record this same capture as its re-verification,
         scoped to `tool_name == "Agent"` only - see that section directly
         rather than a line number, which drifts on any surrounding edit.

         MANDATED_ROLES is a HARDCODED literal, matching the mandate's own
         wording (`content/sections/02-delegation.md:160`, "Every concurrent
         `engineer`, `qa-engineer`, and `release-orchestrator` spawn") - it
         is not derived from any manifest or role-spec file because no
         single source of truth for "which roles require worktree
         isolation" exists elsewhere in this repo. Compare
         `enforce-background-spawn.py`'s two hand-duplicated literals, which
         are NOT symmetric: `_KNOWN_HARNESSES_FALLBACK` genuinely mirrors a
         real module, `KNOWN_HARNESSES` in `bin/_role_spec.py` (which it
         tries to load first, falling back to the literal only on failure);
         `_DISPATCHABLE_ROLES` mirrors a PROSE list in
         `content/references/cross-harness-teams.md` (the five dispatchable
         roles named at lines 266 and 366), not a `bin/_role_spec.py`
         symbol - `bin/_role_spec.py` defines no dispatchable-roles constant
         at all. MANDATED_ROLES below is the same shape as
         `_DISPATCHABLE_ROLES`: a hand-duplicated mirror of a prose list,
         with no runtime fallback-load attempt.
         SYNC OBLIGATION: if `content/sections/02-delegation.md`'s mandate
         ever adds or removes a role from that list, this literal must be
         updated in the same change, or the hook silently under- or
         over-enforces relative to the prose it backstops.

Trigger: PreToolUse on tool_name in {"Task", "Agent"} (registration is
         shared with the other spawn-guard hooks' matcher loop in
         .claude/install.sh), but the enforcement decision below is
         scoped to `tool_name == "Agent"` ONLY - `tool_name == "Task"`
         always falls through to the fail-open passthrough. There is no
         real-payload capture for `Task` (zero `Task` records exist in
         this session's or any prior local transcript corpus), so denying
         on it would be exactly the unverified-predicate gate
         `hooks/AGENTS.md` §"Fail-open on absent tool_input fields"
         prohibits. If a real `Task`-spawn capture is ever obtained
         showing the same omitted-when-unset shape as `Agent`, this scope
         can be widened in the same change that adds the citation.

Public API: Run as a Claude Code PreToolUse hook (matcher: "Task", "Agent").
            Reads JSON from stdin, writes hookSpecificOutput JSON to stdout
            when denying, exits 0 always.

Upstream deps: Python 3 stdlib only (json, os, sys). Reads the
               AE_WORKTREE_ISOLATION_GUARD_DISABLE env var (kill-switch).
               Soft-dependency on the sibling hooks/lib/enforcement_log.py
               fire-logging helper (dynamic import via a `_load_log_fire()`
               wrapper mirroring every other enforce-*.py hook's pattern,
               fails open to a no-op).

Downstream consumers: Claude Code hook runner (PreToolUse event for Task
                      and Agent). Wired via ~/.claude/settings.json by
                      .claude/install.sh, inside the same
                      `for spawn_matcher in ("Task", "Agent"):` loop that
                      registers hooks/enforce-background-spawn.py and
                      hooks/enforce-nested-worktree-spawn.py. Documented in
                      hooks/AGENTS.md §Entry points.

Failure modes: Fail-open on every uncertain or malformed case - a broken
               hook must never brick every spawn. Round-3 fix pass:
               REINSTATES a kill-switch env var, reversing round-2's
               removal. The governing mandate (`content/sections/
               02-delegation.md`) states "with no exception," but that is a
               statement about the METHODOLOGY rule, not a requirement that
               its ENFORCEMENT MECHANISM be irrecoverable - and two live
               documented states make this hook's mechanism a deadlock
               without one: (1) `content/references/worktree-lifecycle.md`
               §Pre-spawn stash fallback sanctions, in prose, "the rare case
               where isolation is genuinely not possible," which this hook
               makes mechanically impossible for the three mandated roles
               with no operator-side recovery; (2) that same file's
               §Version floor documents a build where an isolated engineer
               self-denies on its own files, and this hook forcing
               isolation on such a build produces a total deadlock,
               recoverable today only by hand-editing
               `~/.claude/settings.json`. `hooks/AGENTS.md` §No gating on
               inferred session capability requires exactly this
               confirmation before any deny: "name the action the agent is
               expected to take instead, and confirm that action is still
               permitted under every other active guard." No config-driven
               exemption list is added alongside the kill-switch (see the
               module docstring's own paragraph on that decision, below) -
               only the two sibling worktree guards' env-var kill-switch
               shape is reinstated, matching their naming exactly.
    - Kill-switch (AE_WORKTREE_ISOLATION_GUARD_DISABLE=1): fail-open
      immediately, before reading stdin - same position and semantics as
      `enforce-worktree-read.py`/`enforce-worktree-write.py`'s kill-
      switches.
    - Malformed/empty stdin, JSON that is not an object: exit 0.
    - tool_name != "Agent" (includes "Task" and every other tool name):
      passthrough (exit 0) - see Trigger note above on why "Task" is
      deliberately fail-open rather than enforced.
    - tool_input null, missing, or not a dict: exit 0 - cannot make an
      enforcement decision without a dict to inspect (same discipline as
      enforce-background-spawn.py's raw_tinput handling).
    - subagent_type absent, not a string, or not one of MANDATED_ROLES:
      allow unconditionally - this hook only ever concerns the three
      mandated roles, regardless of isolation state. There is deliberately
      no `isinstance(role, str)` short-circuit: a non-hashable role (e.g. a
      list) raises inside the membership test, caught by the outer
      `except Exception` and exiting 0 - the same ALLOW a short-circuit
      would produce, measured by mutation test to be indistinguishable in
      every case (see the inline comment at the membership check).
    - subagent_type is a mandated role AND isolation == "worktree" exactly:
      allow.
    - subagent_type is a mandated role AND isolation is absent, None, "",
      or any value other than the exact string "worktree" (e.g. "none",
      True, a typo): deny, with an actionable message naming the exact
      fix and the governing rule - never tells the operator to go read a
      file.
    - Any unexpected exception anywhere: exit 0 (fail-open), matching
      every other enforce-*.py hook's defense-in-depth contract.

Performance: < 5 ms per call (in-memory JSON parse only, no file I/O on the
             allow path, no network I/O).

Exemption-list decision (round-3 fix pass): unlike the two sibling worktree
guards (`enforce-worktree-read.py`/`enforce-worktree-write.py`), this hook
ships ONLY the env-var kill-switch, no `worktree_isolation_guard_exemptions`
config-driven exemption list. The siblings' exemption lists are path
prefixes carving out specific FILES that legitimately need cross-boundary
access for reasons unrelated to the mandate they guard (e.g. a shared config
file); granting one there does not touch the mandate's own scope. There is
no equivalent unit here: this hook's deny key is `subagent_type` (a role),
not a path, and the only imaginable "exemption" shape - a list of role names
or spawn sites permanently excused from `content/sections/02-delegation.md`'s
"with no exception" mandate - would encode a standing carve-out INTO the
mandate itself, which is qualitatively different from a sibling's narrow,
content-addressed path exception and would contradict the rule this hook
backstops far more directly than a session-wide, restart-gated kill-switch
does. The two documented deadlock scenarios above (Pre-spawn stash fallback,
Version floor) are both rare/emergency in nature, not a routine per-role
carve-out, so a full temporary disable-and-restart is the proportionate
recovery mechanism for them - a persistent per-role config exemption is not
warranted.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Kill-switch + recovery (reinstated round-3; see module docstring
# "Exemption-list decision" for why no config exemption list accompanies
# it):
#   To temporarily disable this guard:
#     1. Set AE_WORKTREE_ISOLATION_GUARD_DISABLE=1 in your environment, then
#        restart Claude Code so the hook process inherits the variable.
#     2. Alternatively, remove the "enforce-worktree-isolation-spawn" entry
#        from the Task/Agent PreToolUse block in ~/.claude/settings.json,
#        then restart.
#   To re-enable: unset the variable (or re-run .claude/install.sh).

# Hardcoded, not derived - see module docstring "MANDATED_ROLES is a
# HARDCODED literal" for the sync obligation this creates.
MANDATED_ROLES = frozenset({"engineer", "qa-engineer", "release-orchestrator"})

_REQUIRED_ISOLATION = "worktree"


def _load_log_fire():
    """Best-effort dynamic import of the shared fire-logging helper.

    Falls back to a no-op when the sibling module cannot be loaded (missing
    file, syntax error, snapshot copy drift) - fire-logging is additive
    telemetry, never a hard dependency of the enforcement decision itself.

    Called lazily from inside the deny branch (never at module scope) so
    the overwhelming majority of invocations - every silent allow - never
    read, compile, or exec this file at all.
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


def _deny(data: dict, reason: str) -> None:
    # Decision print comes FIRST, unconditionally. Telemetry is loaded and
    # called only after the decision has reached stdout, and is wrapped in
    # its own try/except so a raising log_fire (e.g. a signature mismatch
    # from a half-applied lib snapshot) can never suppress or follow this
    # deny - convention in every other enforce-*.py hook carrying this same
    # note (see hooks/lib/enforcement_log.py manifest "Failure modes").
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    try:
        _load_log_fire()(data, "enforce-worktree-isolation-spawn", "deny", reason)
    except Exception:
        pass
    sys.exit(0)


def main() -> None:
    # Kill-switch checked before stdin is even read, matching
    # enforce-worktree-read.py/enforce-worktree-write.py's position and
    # semantics exactly.
    if os.environ.get("AE_WORKTREE_ISOLATION_GUARD_DISABLE") == "1":
        sys.exit(0)

    try:
        # No separate inner try/except around json.load: it was measured
        # (mutation test) to be fully redundant with the outer `except
        # Exception` below for every JSON-derived payload - any exception
        # json.load can raise on stdin content is also an Exception the
        # outer handler catches identically, so a second handler here adds
        # no distinct behavior, only an unfalsifiable-by-mutation duplicate.
        data = json.load(sys.stdin)

        if not isinstance(data, dict):
            sys.exit(0)

        # Enforcement is scoped to "Agent" only - there is no real-payload
        # capture proving "Task" omits `isolation` the same way, so denying
        # on "Task" would be an unverified-predicate deny. See the Trigger
        # docstring note above.
        tool_name = data.get("tool_name")
        if tool_name != "Agent":
            sys.exit(0)

        raw_tinput = data.get("tool_input")
        if not isinstance(raw_tinput, dict):
            sys.exit(0)

        # No isinstance(role, str) guard here: measured by mutation test
        # (round-3 fix pass) that adding one is unfalsifiable-by-construction
        # for every input shape reachable from JSON. A non-string, non-
        # hashable role (e.g. a list) raises TypeError inside `in
        # MANDATED_ROLES`, caught by the outer `except Exception` below and
        # exiting 0 (ALLOW) - the exact same externally observable outcome
        # as an explicit isinstance short-circuit would produce. A non-
        # string, hashable role (e.g. an int) is simply never `in` the
        # frozenset of role-name strings, so `role not in MANDATED_ROLES`
        # is True either way. Both paths ALLOW identically with or without
        # the check, so no test can pin it; per this repo's standing
        # preference (deletion over a narrowed rewrite for an unfalsifiable
        # claim), it is omitted rather than kept as decorative.
        role = raw_tinput.get("subagent_type")
        if role not in MANDATED_ROLES:
            sys.exit(0)

        # Denying on an absent `isolation` key here is an instance of
        # hooks/AGENTS.md's "Narrow evidence-gated exception" to §Fail-open
        # on absent tool_input fields: backed by the real per-tool_name
        # capture cited in the module docstring above and in
        # hooks/AGENTS.md §Spawn payload mechanics (captured 2026-08-23),
        # proving `isolation` is present-when-set/omitted-when-unset for
        # `tool_name == "Agent"` specifically. Do not generalize this to
        # "Task" or any other field without an equally real capture.
        # NOT the only deny-on-absent gate in the repo: `enforce-
        # background-spawn.py` also denies a `Task` spawn whose
        # `run_in_background` key is entirely absent, and predates this
        # exception's evidence requirement - it has no per-tool_name
        # capture proving `Task` omits that field only when unset. It is
        # grandfathered debt, not compliant precedent; see hooks/AGENTS.md
        # §Fail-open on absent tool_input fields for the accepted framing.
        isolation = raw_tinput.get("isolation")
        if isolation == _REQUIRED_ISOLATION:
            sys.exit(0)

        _deny(
            data,
            f"{tool_name} spawn of subagent_type '{role}' blocked: worktree "
            "isolation is MANDATORY for every engineer/qa-engineer/"
            "release-orchestrator spawn, with no exception - even a "
            "Trivial-path solo engineer spawn runs isolated "
            "(content/sections/02-delegation.md §Delegation, "
            "content/sections/11-worktree-lifecycle.md §Worktree "
            "Lifecycle). Re-issue this spawn with isolation: \"worktree\" "
            "set on the Agent tool call. A subagent that shares the main "
            "worktree can stage and commit conductor-side untracked files "
            "into its own commit, and two parallel spawns sharing a "
            "working tree produce cross-engineer commit contamination."
        )

    except SystemExit:
        raise
    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open).
        # The fail-open promise must hold for every input shape.
        sys.exit(0)


if __name__ == "__main__":
    main()
