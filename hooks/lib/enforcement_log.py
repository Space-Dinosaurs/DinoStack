#!/usr/bin/env python3
"""
Purpose: Shared fire-logging helper for AE's Python enforce-*.py
         PreToolUse/Stop hooks. Appends one line to
         [cwd]/.agentic/.enforcement-fires.jsonl. This exists because the
         enforce-*.py hooks otherwise leave no trace of whether they have
         ever fired, making an inert rule indistinguishable from a
         load-bearing one.

         TWO CALLER POSTURES, both supported, chosen by the caller:
           - ACTION-ONLY (eleven of the twelve hooks): call only on a
             non-passthrough action - a deny, or an allow-with-advisory-
             reason. A silent allow never calls this, so the file stays
             small and cheap to read. This is the right posture for a
             PreToolUse hook, which runs on every guarded tool call and
             would otherwise log at tool-call volume.
           - EVERY-VERDICT (enforce-no-abdication.py alone): call on every
             verdict path reached once the guard is enabled, including a
             plain "allow". Action-only logging cannot answer "how often
             did this guard evaluate a turn and decline to fire?", so it
             leaves "the guard never fires" unfalsifiable - the exact
             condition that hook sat in from 2026-08-03 to 2026-08-14,
             contributing zero rows while the other hooks contributed
             1059. A Stop hook fires about once per conductor turn, so
             every-verdict volume is bounded by turn count, not tool-call
             count. Do NOT copy this posture to a PreToolUse hook.

Public API (module-level function, no class):
    log_fire(data, hook_name, decision, reason, *, detail=None) -> None
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
        detail: OPTIONAL keyword-only dict of structured, machine-queryable
              discriminators for this fire (e.g. which classifier fired,
              which negative-gate token suppressed a check). Written as a
              nested "detail" object and OMITTED ENTIRELY when None, absent,
              empty, or not a dict - so every pre-existing caller's line
              stays byte-identical to what it wrote before this parameter
              existed, and the canonical 4-field schema remains the shape a
              consumer may always assume. Callers must keep the contents
              small, bounded, and free of message content: booleans, small
              integers, and short fixed-vocabulary labels only. Never a
              transcript excerpt, a user message, or a regex match that can
              capture arbitrary text (an email address, a dollar amount) -
              this file has no PII boundary of its own beyond what callers
              choose to put in it. If `detail` cannot be JSON-serialized the
              line degrades to the canonical 4 fields rather than being lost.

Upstream deps: Python 3 stdlib only (json, os, datetime). Imports the
               sibling hooks/lib/repo_root.py module via an isolated
               importlib.util.spec_from_file_location load (_load_repo_root
               - round-2 rework: was a `sys.path.insert(0, ...)` + `from
               repo_root import ...` pair, a global process-wide side
               effect for every caller that dynamically loads this file)
               - anchors the write below to the repo root instead of the
               raw payload cwd (or the os.getcwd() fallback when cwd is
               absent from the payload). Also imports the sibling
               hooks/lib/git_worktree.py module the same way
               (_load_git_worktree) and, when the resolved root is ITSELF
               a genuine linked git worktree's root (its own `.git` is a
               file pointing into a `.git/worktrees/<name>` admin dir -
               see git_worktree.resolve_worktree_primary_root()), follows
               that pointer to the PRIMARY checkout root before writing.
               Without this, a subagent running inside an isolation
               worktree (`.claude/worktrees/agent-<id>`) writes its fire
               rows into that worktree's OWN throwaway
               `.agentic/.enforcement-fires.jsonl`, which is discarded the
               moment the worktree is removed - fragmenting the fire log
               across every worktree that ever existed and silently
               undercounting every consumer of the primary copy (e.g.
               bin/ds-hook-fire-report). Writes ONLY
               [resolved root]/.agentic/.enforcement-fires.jsonl (creates
               that .agentic/ dir with os.makedirs(exist_ok=True) if
               absent). Never reads any file other than the two `.git`
               entries this resolution may probe (repo_root's existence-
               only walk, and git_worktree's read of a single `.git` file
               at the walk's resolved root).

Downstream consumers: all twelve enforce-*.py PreToolUse/Stop hooks that
                       call log_fire() at their action-emission point:
                       enforce-askuserquestion-default.py,
                       enforce-background-spawn.py,
                       enforce-no-abdication.py,
                       enforce-orchestrator-singularity.py,
                       enforce-planning-artifact-spawn.py,
                       enforce-shippable-edit.py,
                       enforce-skeptic-round-cap.py,
                       enforce-ticket-batching.py, enforce-tier.py,
                       enforce-turn-shape.py, enforce-worktree-read.py,
                       and enforce-worktree-write.py.
                       enforce-turn-shape.py and enforce-no-abdication.py
                       are the two Stop-event consumers; the other ten are
                       PreToolUse.
                       enforce-no-abdication.py is the one consumer that
                       ALSO logs plain "allow" rows (every verdict path it
                       reaches once enabled, not only its blocks) - without
                       them its allow/deny ratio is unknowable and "the
                       guard never fires" is unfalsifiable. It additionally
                       keeps its own pre-existing counter file
                       (.abdication-guard-fire-count), which has different
                       semantics (a cumulative count + loop-guard state,
                       not a fire log) and is completely unchanged by this
                       module; this module must never be repurposed to
                       touch that file.

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


def _load_git_worktree():
    """Best-effort dynamic import of the sibling hooks/lib/git_worktree.py
    module, same isolated-loader pattern as _load_repo_root() below (see
    its docstring for why this is not a plain `import`)."""
    try:
        import importlib.util as _ilu

        here = os.path.dirname(os.path.abspath(__file__))
        mod_path = os.path.join(here, "git_worktree.py")
        spec = _ilu.spec_from_file_location("git_worktree", mod_path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_GIT_WORKTREE = _load_git_worktree()


def _resolve_primary_root(root: str) -> str:
    """If `root` (the resolve_agentic_cwd() result) is itself a genuine
    linked git worktree's root, follow its `gitdir:` pointer to the
    PRIMARY checkout root so fire-log rows from an isolation-worktree
    subagent land in one shared file instead of a discarded worktree-local
    copy. Returns `root` unchanged when the worktree module failed to
    load, `root` is not a worktree, or resolution fails for any reason -
    this only ever narrows the write target toward the primary checkout,
    never invents a new path (mirrors resolve_agentic_cwd()'s own
    fall-back-to-unchanged discipline just above)."""
    if _GIT_WORKTREE is None:
        return root
    try:
        primary = _GIT_WORKTREE.resolve_worktree_primary_root(root)
    except Exception:
        return root
    return primary if primary else root


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


def log_fire(data, hook_name, decision, reason, *, detail=None) -> None:
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
        # location on its own. When that ancestor is itself a linked git
        # worktree's root, _resolve_primary_root follows its gitdir
        # pointer to the primary checkout so the row lands in the one
        # shared fire log rather than a discarded worktree-local copy.
        root = _resolve_primary_root(resolve_agentic_cwd(cwd))
        agentic_dir = os.path.join(root, ".agentic")
        os.makedirs(agentic_dir, exist_ok=True)
        log_path = os.path.join(agentic_dir, _LOG_BASENAME)

        entry = {
            "ts": _now_iso(),
            "hook": str(hook_name),
            "decision": str(decision),
            "reason": str(reason)[:_REASON_MAX_LEN],
        }

        # `detail` is strictly additive and strictly optional. An absent,
        # empty, non-dict, or non-serializable `detail` degrades to the
        # canonical 4-field line rather than losing the row entirely - a
        # caller's structured-telemetry bug must not cost the enforcement
        # record itself. Serializing into a COPY (not `entry`) is what
        # makes the fallback below reachable with a clean dict.
        line = None
        if isinstance(detail, dict) and detail:
            try:
                line = json.dumps(dict(entry, detail=detail)) + "\n"
            except Exception:
                line = None
        if line is None:
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
