#!/usr/bin/env python3
"""
Purpose: Shared fire-logging helper for AE's Python enforce-*.py
         PreToolUse/Stop hooks. Appends one line to
         [cwd]/.agentic/.enforcement-fires.jsonl whenever a hook takes a
         non-passthrough action (deny, or an allow-with-advisory-reason).
         A silent allow (the overwhelming majority of invocations) never
         calls this - only actions are logged, so the file stays small
         and cheap to read. This exists because eight of the nine
         enforce-*.py hooks currently leave no trace of whether they have
         ever fired, making an inert rule indistinguishable from a
         load-bearing one (see MEMORY.md / session notes on the
         abdication-guard fire-count precedent, the one hook that already
         tracked this before this module existed).

Public API (module-level function, no class):
    log_fire(data, hook_name, decision, reason) -> None
        data: the parsed stdin payload dict for this hook invocation (or
              any object - non-dict is tolerated and treated as {}). cwd
              is read from data["cwd"] when data is a dict and that key is
              a non-empty string; falls back to os.getcwd() otherwise.
        hook_name: short hook identifier, e.g. "enforce-tier". Any type is
              accepted and coerced with str() - callers pass a literal.
        decision: the action taken, e.g. "deny" or "allow_advisory". Free-
              form by design (see Failure modes) - this module does not
              validate against an enum so a future action shape (e.g. a
              new "ask" decision) never needs a lib change to be logged.
        reason: short human-readable reason string - callers already have
              one on hand (the same text fed back to the model via
              permissionDecisionReason). Truncated to 800 chars here so a
              pathological reason string cannot grow the log unbounded.

Upstream deps: Python 3 stdlib only (json, os, datetime). Imports the
               sibling hooks/lib/repo_root.py module via an isolated
               importlib.util.spec_from_file_location load (_load_repo_root
               - round-2 rework: was a `sys.path.insert(0, ...)` + `from
               repo_root import ...` pair, a global process-wide side
               effect for every caller that dynamically loads this file)
               - anchors the write below to the repo root instead of the
               raw payload cwd (or the os.getcwd() fallback when cwd is
               absent from the payload). Writes ONLY
               [resolved root]/.agentic/.enforcement-fires.jsonl (creates
               that .agentic/ dir with os.makedirs(exist_ok=True) if
               absent). Never reads any file.

Downstream consumers: the eleven enforce-*.py PreToolUse/Stop hooks that
                       call log_fire() at their action-emission point:
                       enforce-askuserquestion-default.py,
                       enforce-background-spawn.py,
                       enforce-orchestrator-singularity.py,
                       enforce-planning-artifact-spawn.py,
                       enforce-shippable-edit.py,
                       enforce-skeptic-round-cap.py,
                       enforce-ticket-batching.py, enforce-tier.py,
                       enforce-turn-shape.py, enforce-worktree-read.py,
                       and enforce-worktree-write.py.
                       enforce-turn-shape.py is the first Stop-event
                       consumer; the other ten are PreToolUse.
                       enforce-no-abdication.py is deliberately NOT a
                       consumer - it keeps its own pre-existing counter
                       file (.abdication-guard-fire-count) with different
                       semantics (a cumulative count + loop-guard state,
                       not a fire log) completely unchanged; this module
                       is purely additive telemetry for the other ten
                       and must never be repurposed to touch that file.

Failure modes: Fully fail-open and silent, matching every enforce-*.py
               hook's own contract - a telemetry helper must never be the
               reason a legitimate hook decision fails to reach the model.
    - Any exception anywhere in log_fire() (missing/unwritable .agentic/,
      a full disk, a non-string-coercible argument, cwd resolution
      failure) is swallowed inside a single try/except - log_fire() NEVER
      raises and NEVER writes to stdout or stderr, so it can never
      interfere with the calling hook's own hookSpecificOutput print.
    - data not a dict, or data["cwd"] absent/blank/non-string: falls back
      to os.getcwd() - never fails the call.
    - Concurrent hook invocations appending simultaneously: each append is
      a single os.write() to an os.O_APPEND-opened file descriptor. The
      atomicity guarantee here is POSIX's O_APPEND semantics (the kernel
      atomically seeks to end-of-file and performs the write as one
      operation, so two concurrent appenders' bytes cannot interleave) -
      NOT PIPE_BUF, which governs atomic writes to pipes and FIFOs and has
      no bearing on a regular file. This guarantee holds on local POSIX
      filesystems but is NOT guaranteed over NFS, where O_APPEND is well
      documented to be non-atomic under concurrent writers from different
      clients. This module's writes are always to a project-local
      `.agentic/` directory, so the NFS caveat is noted but not currently a
      practical concern. This is why a full read-existing + tmp-write +
      os.replace cycle (the pattern used elsewhere in this codebase for
      whole-file replace writes) is NOT used here: that pattern exists to
      make a REPLACE atomic, but a pure single-line APPEND has a cheaper
      native atomicity guarantee on local filesystems and paying the
      read-modify-tmp-rename cost on every enforcement action would be
      wasteful.

Performance: < 1 ms per call (one os.makedirs check, one os.open with
             O_APPEND, one os.write, one os.close - no read-before-write).
             Every caller loads this module lazily via a `_load_log_fire()`
             call placed INSIDE its action branch (deny, or allow-with-
             advisory), never at module scope - so the overwhelming
             majority of hook invocations (every silent allow, and every
             kill-switched invocation that exits before reaching the
             action branch) never read, compile, or exec this file at all.
"""

from __future__ import annotations

import datetime
import json
import os


def _load_repo_root():
    """Best-effort dynamic import of the sibling hooks/lib/repo_root.py
    module. Round-2 rework (Minor): replaces a `sys.path.insert(0, ...)` +
    `from repo_root import ...` pair - a GLOBAL process-wide side effect
    that shadowed any other `repo_root`/`git_worktree`/`loop_guard`/
    `enforcement_log`-named module for the rest of the process, for every
    caller that dynamically loads this file via importlib.util (10
    enforce-*.py hooks at last audit). Uses the same isolated
    importlib.util.spec_from_file_location loader every other Python
    .agentic/ consumer in this repo uses (bin/ds-status, bin/ds-cost,
    bin/ds-memory, hooks/enforce-skeptic-round-cap.py) instead."""
    try:
        import importlib.util as _ilu

        here = os.path.dirname(os.path.abspath(__file__))
        mod_path = os.path.join(here, "repo_root.py")
        spec = _ilu.spec_from_file_location("repo_root", mod_path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_REPO_ROOT = _load_repo_root()


def resolve_agentic_cwd(cwd: str) -> str:
    """Thin wrapper preserving this module's pre-existing call shape
    (`resolve_agentic_cwd(cwd)`) for its own callers below. Falls back to
    cwd unchanged if the resolver failed to load - fire-logging is
    additive telemetry, never a hard dependency."""
    if _REPO_ROOT is None:
        return cwd
    try:
        return _REPO_ROOT.resolve_agentic_cwd(cwd)
    except Exception:
        return cwd


_LOG_BASENAME = ".enforcement-fires.jsonl"
# 800, not 400: enforce-planning-artifact-spawn's advisory reason embeds a
# full repo-relative target path and was measured at 391 chars against the
# prior 400-char cap - 9 chars from silent clipping on a slightly longer
# path. Doubled for headroom rather than tuned to the single longest known
# caller.
_REASON_MAX_LEN = 800


def _now_iso() -> str:
    """ISO8601 UTC with millisecond precision, matching the events.jsonl
    convention used by the JS hooks (new Date().toISOString())."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(
        now.microsecond // 1000
    )


def log_fire(data, hook_name, decision, reason) -> None:
    """Append one fire-log line. Fail-open: never raises, never prints."""
    try:
        cwd = None
        if isinstance(data, dict):
            raw_cwd = data.get("cwd")
            if isinstance(raw_cwd, str) and raw_cwd.strip():
                cwd = raw_cwd.strip()
        if not cwd:
            cwd = os.getcwd()

        # resolve_agentic_cwd walks up from cwd (whether it came from the
        # payload or the os.getcwd() fallback above) to the nearest .git
        # ancestor, so a drifted process cwd never determines the write
        # location on its own.
        agentic_dir = os.path.join(resolve_agentic_cwd(cwd), ".agentic")
        os.makedirs(agentic_dir, exist_ok=True)
        log_path = os.path.join(agentic_dir, _LOG_BASENAME)

        entry = {
            "ts": _now_iso(),
            "hook": str(hook_name),
            "decision": str(decision),
            "reason": str(reason)[:_REASON_MAX_LEN],
        }
        line = json.dumps(entry) + "\n"

        # Single os.write() to an O_APPEND fd: POSIX guarantees this append
        # is atomic for a write under PIPE_BUF, so two concurrent hook
        # invocations never interleave or clobber each other's line - no
        # tmp-file/rename dance needed for a pure append (see Failure modes).
        fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:
        # Fail-open: a logging failure must never propagate or affect the
        # caller's own hook decision, and must never write to stdout/stderr
        # (which could corrupt the caller's own hookSpecificOutput print).
        pass
