#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that mechanically enforces a grace margin under
         the Follow-up Ticket Creation Discipline's batching rule
         (`content/references/delegation-detail.md` §Follow-up Ticket
         Creation Discipline, item 3: "2 or more discoveries in the same
         session are NEVER separate tickets - batched into exactly ONE").
         That rule was prose-only with zero mechanical enforcement (PR
         #606 shipped it and said outright "a conductor that ignores the
         discipline is not stopped"), and mid-session ticket fan-out was
         measured going 7.7/week -> 25.4/week across one week, with a
         single session minting DS-156 through DS-160 (5 tickets) over
         ~14 hours, each a small bug found while fixing the previous.

         **This hook's threshold is DELIBERATELY a grace margin BELOW the
         prose rule, not a redefinition of it.** The prose rule stays
         "exactly ONE" ticket for 2+ same-session discoveries - do not
         "fix" this file to deny on the 2nd creation to match that text
         more tightly. The 3-creation threshold exists because a real
         session can legitimately contain two independent, unrelated,
         TOP-LEVEL operator-raised asks in one sitting (each spawning its
         own single ticket) - the batching rule's carve-out in item 1
         ("Top-level, operator-raised asks are unaffected") - and a hard
         deny on ticket #2 would block that legitimate case with no
         escape hatch. The measured fan-out case that motivated this hook
         was 5 tickets in one session; a cap of 3 still catches it while
         leaving room for two genuinely independent asks. Counting
         (1st: silent allow, 2nd: allow + advisory, 3rd+: deny) is an
         operator decision, not an architect recommendation - an earlier
         plan draft specified a hard deny on the 2nd creation and was
         explicitly overridden.

         Classifies a tracker-ticket CREATE call three ways:
           1. `mcp__mcp-atlassian__jira_create_issue` - always a creation
              (the tool only creates; verified against
              `content/commands/ds-implement-ticket.md:536`).
           2. `mcp__linear__save_issue` - a creation ONLY when the call
              carries no `id` field (Linear's `save_issue` creates when
              `id` is omitted and updates when it is supplied - verified
              against `content/commands/ds-implement-ticket.md:534`). An
              `id`-bearing call (a status/comment update on an existing
              ticket) is never counted.
           3. `Bash` - a direct API bypass (PR #606 found conductors
              calling Jira REST directly instead of going through the
              documented MCP/Tracker-Create-Helper path). Two sub-cases,
              both requiring an explicit HTTP-method signal so a GET/
              search call never matches:
                a. A POST to a Jira `/rest/api/<version>/issue` endpoint
                   NOT followed by `/<key>` (that longer path is a
                   get/update/transition call on an EXISTING issue, not
                   a create) - see `_JIRA_ISSUE_CREATE_PATH_RE`.
                b. Linear's `issueCreate` GraphQL mutation name appearing
                   literally in the command text - see
                   `_LINEAR_ISSUE_CREATE_RE`.

         **Triage exemption.** `/ds-feedback-triage` and
         `/ds-ticket-triage` legitimately create multiple tickets in one
         session under an explicit human greenlight per batch (see
         `content/references/delegation-detail.md` item 5: the triage
         creates are gated by a stronger control than this discipline -
         a per-batch human greenlight). Detected by reading the payload's
         `transcript_path` and searching for the literal
         `<command-name>ds-feedback-triage</command-name>` or
         `<command-name>ds-ticket-triage</command-name>` marker (format
         confirmed against `hooks/lib/loop_guard.py`'s
         `_HARNESS_INJECTED_MARKERS` handling of `<command-name>` lines).
         This exemption is SESSION-WIDE and coarse by construction - once
         either marker is found anywhere in the transcript, every
         creation call for the rest of the session is exempt, even one
         issued long after the triage command's own turn ended. This
         limitation is accepted, not hidden: a conductor could in
         principle invoke `/ds-feedback-triage` once merely to silence
         this hook, then create unrelated tickets for the rest of the
         session. Closing that gap would require scoping the exemption to
         a bounded window (e.g. N turns after the command marker), which
         is not implemented here. The exemption is NOT self-grantable by
         the conductor writing a file - it can only be satisfied by an
         actual `<command-name>` marker appearing in the harness-authored
         transcript, which the conductor does not control the format or
         placement of.

         Session state persists at
         `<cwd>/.agentic/.ticket-batch-<session_id>.json` as `{"count":
         int}` - `cwd` and `session_id` both come from the PreToolUse
         payload (never `os.getcwd()` or a derived value); `cwd` is the
         CALLER's root (may be an isolation worktree) while
         `CLAUDE_PROJECT_DIR` would be the primary checkout - the two are
         complementary, not interchangeable, and this hook deliberately
         uses `cwd` alone (matching `enforce-skeptic-round-cap.py`'s
         `_state_path`) since ticket creation is a conductor-only action
         that always runs from the primary checkout's `cwd` in practice.

         Decision algorithm (see `_decide()`):
           - next_count = count + 1 on every classified creation call.
           - next_count <= 1 (i.e. this is the 1st creation this
             session): ALLOW silently. Persist count=1. No log_fire call
             (matching every other hook's convention: a silent allow is
             the overwhelming majority case and must not grow the fire
             log).
           - next_count == 2 (the 2nd creation): ALLOW, but emit an
             advisory (`permissionDecision: "allow"` with a non-empty
             `permissionDecisionReason` naming the batching rule) and log
             `"allow_advisory"` via `log_fire()`. Persist count=2.
           - next_count >= 3 (the 3rd and every subsequent creation):
             DENY, citing the batching rule, the concrete `bin/ds-defer`
             escape-hatch command, and the two legitimate ways out
             (`/ds-wrap` to close the session, or the triage commands for
             a greenlit batch). State is NOT persisted on this branch
             (count stays at whatever it already was) - a denied call
             never created a ticket, so there is nothing new to count,
             and this keeps every subsequent retry of the same call
             denied identically rather than drifting the counter forward
             on a call that never actually created anything.

         Kill switch: `AE_TICKET_BATCH_GUARD_DISABLE=1`, checked FIRST in
         `main()`. Deliberately an environment variable, NOT a
         `.agentic/config.json` key - a config key would add a 22nd
         behavioral toggle and trip the toggle-count-sync obligation
         across 8 prose sites documented in DinoStack's own `MEMORY.md`
         (`README.md`, `content/references/conventions-detail.md`,
         `content/references/risk-config-and-tiers.md`,
         `content/sections/04-risk-classification.md`,
         `docs/components.md`, `docs/configuration-reference.md`), none
         of which this change touches.

Public API: Run as a Claude Code PreToolUse hook (matcher:
            `mcp__mcp-atlassian__jira_create_issue`,
            `mcp__linear__save_issue`, or `Bash`). Reads JSON from stdin,
            writes `hookSpecificOutput` JSON to stdout when denying or
            advising, exits 0 always.

Upstream deps: Python 3 stdlib only (json, os, re, sys, time, pathlib,
               importlib.util for the best-effort `lib/enforcement_log.py`
               import). No external deps, no subprocess.

Downstream consumers: Claude Code hook runner (PreToolUse event, three
                      matcher blocks). Wired via ~/.claude/settings.json
                      by .claude/install.sh using the GUARDED command form
                      (`test -f <path> && python3 <path> || exit 0`) - a
                      bare `python3 {path}` would exit 2 (BLOCKING on
                      PreToolUse) if this file were ever removed while the
                      registration survives, denying every guarded MCP/
                      Bash call in every session.

Failure modes:
    - Malformed stdin, non-dict tool_input, unclassifiable tool_name/
      command, or a non-creation call (Linear update, Jira GET/search):
      fail-open (exit 0), no state written, no log.
    - `AE_TICKET_BATCH_GUARD_DISABLE=1` in the environment: fail-open
      (exit 0) before any classification, no state written, no log.
    - `cwd` or `session_id` absent/blank/non-string in the payload:
      fail-open (exit 0) - the hook cannot determine where to persist
      state or which session's counter to use.
    - `transcript_path` absent, unreadable, or any exception while
      scanning it for the triage marker: treated as NOT exempt (`False`)
      - a triage-exemption read failure never silently suppresses
      enforcement, but also never denies solely because the read failed
      (the call still proceeds through the normal count/decide path).
    - State file present but unparsable JSON: treated as `{"count": 0}` -
      a corrupt state file must never turn into a permanent block.
    - State file write failure (permissions, disk full): the ALLOW/DENY
      decision for THIS call still fires correctly; only the persisted
      count advance may be lost, so a retried call may see a stale
      (lower) count and be permitted again - fail-open, not fail-shut.
    - Any unexpected exception anywhere in the decision path: fail-open
      (exit 0) via an outer try/except in `main()`.
    - Best-effort dynamic import of `lib/enforcement_log.py` for
      `log_fire()`; any import error falls back to a no-op, matching
      every other enforce-*.py hook's fire-logging pattern.

Performance: < 5 ms per call (no subprocess; one small JSON read/write
             under `.agentic/`, one bounded transcript-file read only on
             a classified-creation call).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

_ADVISORY_AT_COUNT = 2
_DENY_FROM_COUNT = 3

# HTTP method signal required alongside the Jira issue-create path below -
# without this, an ordinary GET/search request against the same endpoint
# family would falsely classify as a creation. Matches "-X POST",
# "--request POST", a Python-requests-style "method='POST'"/'method="POST"',
# or a bare standalone "POST" token (e.g. inside a curl -d/--data command
# where the verb appears unflagged in surrounding prose is rare, but a bare
# "POST" word boundary catches common curl/httpie invocations without a
# flag). Case-insensitive.
_HTTP_POST_SIGNAL_RE = re.compile(
    r"(?:-X\s*POST|--request[= ]POST|method\s*=\s*['\"]?POST['\"]?|\bPOST\b)",
    re.IGNORECASE,
)
# Jira REST issue-CREATE path: "/rest/api/<digits>/issue" NOT followed by a
# word char, slash, or hyphen. A trailing "/DS-123" (get/update/transition
# on an EXISTING issue) or a trailing "s" (a different, plural endpoint)
# both fail the negative lookahead and correctly do not match.
_JIRA_ISSUE_CREATE_PATH_RE = re.compile(r"/rest/api/\d+/issue(?![\w/-])")
# Linear's issueCreate GraphQL mutation name, literal word-boundary match.
_LINEAR_ISSUE_CREATE_RE = re.compile(r"\bissueCreate\b")

_TRIAGE_MARKERS = (
    "<command-name>ds-feedback-triage</command-name>",
    "<command-name>ds-ticket-triage</command-name>",
)

# Bounded read for the transcript scan - a session transcript can grow
# large; this hook only needs to know whether either triage marker
# appears anywhere, so a full-file read (not tailed) is acceptable given
# transcripts are JSONL and typically well under this cap for an
# in-progress session, but the cap still exists as a hard ceiling against
# a pathological file.
_TRANSCRIPT_READ_CAP_BYTES = 20_000_000


def _load_log_fire():
    """Best-effort dynamic import of the shared fire-logging helper.

    Mirrors the identical lazy, try/except-wrapped import pattern used by
    every sibling enforce-*.py hook (see enforce-skeptic-round-cap.py) - a
    missing or broken sibling module must never crash this hook.
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


def _bash_is_creation(command: str) -> bool:
    """True when a Bash command is a direct API bypass creating a tracker
    ticket (Jira REST POST to the issue-create endpoint, or Linear's
    issueCreate GraphQL mutation). See module docstring point 3."""
    if not command:
        return False
    if _LINEAR_ISSUE_CREATE_RE.search(command):
        return True
    if _JIRA_ISSUE_CREATE_PATH_RE.search(command) and _HTTP_POST_SIGNAL_RE.search(command):
        return True
    return False


def _is_creation(tool_name: str, tinput: dict) -> bool:
    if tool_name == "mcp__mcp-atlassian__jira_create_issue":
        return True
    if tool_name == "mcp__linear__save_issue":
        # save_issue creates when no `id` is supplied, updates when one is.
        return not tinput.get("id")
    if tool_name == "Bash":
        command = tinput.get("command")
        return _bash_is_creation(command if isinstance(command, str) else "")
    return False


def _is_triage_exempt(transcript_path) -> bool:
    """Best-effort scan of the transcript for a triage command marker.
    Fails to False (never exempt) on any read error - see module
    docstring "Failure modes"."""
    try:
        if not isinstance(transcript_path, str) or not transcript_path:
            return False
        path = Path(transcript_path)
        if not path.is_file():
            return False
        text = path.read_text(encoding="utf-8", errors="replace")[
            :_TRANSCRIPT_READ_CAP_BYTES
        ]
        return any(marker in text for marker in _TRIAGE_MARKERS)
    except Exception:
        return False


def _state_path(cwd: str, session_id: str) -> Path:
    safe_session = re.sub(r"[^A-Za-z0-9._-]", "-", session_id.strip()) or "unknown"
    return Path(cwd) / ".agentic" / f".ticket-batch-{safe_session}.json"


def _load_state(path: Path) -> dict:
    try:
        if not path.is_file():
            return {"count": 0}
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"count": 0}
        count = raw.get("count", 0)
        return {"count": count if isinstance(count, int) else 0}
    except Exception:
        return {"count": 0}


def _write_state(path: Path, count: int) -> None:
    """Best-effort atomic write - tmp file + os.replace, pid-suffixed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "count": count,
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        tmp_path = path.with_suffix(f".tmp.{os.getpid()}")
        tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception:
        # Fail-open: a lost persist means a retried call may see a stale
        # (lower) count and be permitted again - never a false deny.
        pass


_ADVISORY_TEMPLATE = (
    "ADVISORY: this is the 2nd tracker-ticket creation this session. Per "
    "content/references/delegation-detail.md §Follow-up Ticket Creation "
    "Discipline, 2+ same-session discoveries are NEVER separate tickets - "
    "they are batched into exactly ONE. A 3rd creation attempt this "
    "session will be DENIED. If this is a genuinely independent, "
    "top-level operator-raised ask (not a mid-session discovery), ignore "
    "this advisory. Otherwise, batch remaining discoveries into this "
    "ticket, or record them with `bin/ds-defer append --repo <repo> "
    "--description '<desc>' --reason failed_promotion_bar` and move on."
)

_DENY_TEMPLATE = (
    "Ticket-batching cap reached: this would be the {ordinal} tracker-"
    "ticket creation this session. Per content/references/"
    "delegation-detail.md §Follow-up Ticket Creation Discipline, 2+ "
    "same-session discoveries are NEVER separate tickets - batch them "
    "into exactly ONE. Do not create this ticket. Instead: record it "
    "with `bin/ds-defer append --repo <repo> --description '<desc>' "
    "--reason failed_promotion_bar` and move on, OR if this genuinely is "
    "a new independent top-level operator-raised ask (not a mid-session "
    "discovery), fold it into the session's existing ticket instead of "
    "creating a new one. Escape hatches: run /ds-wrap to close out this "
    "session before starting fresh work, or use /ds-feedback-triage / "
    "/ds-ticket-triage for an explicit human-greenlit batch of creates."
)


def _emit(data: dict, reason: str, decision: str) -> None:
    permission_decision = "deny" if decision == "deny" else "allow"
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": permission_decision,
            "permissionDecisionReason": reason,
        }
    }))
    try:
        _load_log_fire()(data, "enforce-ticket-batching", decision, reason)
    except Exception:
        pass


def main() -> None:
    try:
        if os.environ.get("AE_TICKET_BATCH_GUARD_DISABLE") == "1":
            sys.exit(0)

        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        if not isinstance(data, dict):
            sys.exit(0)

        tool_name = data.get("tool_name")
        raw_tinput = data.get("tool_input")
        tinput = raw_tinput if isinstance(raw_tinput, dict) else {}

        if not _is_creation(tool_name if isinstance(tool_name, str) else "", tinput):
            sys.exit(0)

        cwd = data.get("cwd")
        session_id = data.get("session_id")
        if not isinstance(cwd, str) or not cwd or not isinstance(session_id, str) or not session_id:
            sys.exit(0)

        if _is_triage_exempt(data.get("transcript_path")):
            sys.exit(0)

        path = _state_path(cwd, session_id)
        state = _load_state(path)
        next_count = state["count"] + 1

        if next_count < _ADVISORY_AT_COUNT:
            _write_state(path, next_count)
            sys.exit(0)

        if next_count == _ADVISORY_AT_COUNT:
            _write_state(path, next_count)
            _emit(data, _ADVISORY_TEMPLATE, "allow_advisory")
            sys.exit(0)

        if next_count >= _DENY_FROM_COUNT:
            # Deny, state unchanged (see module docstring - a denied call
            # never created anything, so there is nothing new to persist).
            ordinal_map = {3: "3rd"}
            ordinal = ordinal_map.get(next_count, f"{next_count}th")
            reason = _DENY_TEMPLATE.format(ordinal=ordinal)
            _emit(data, reason, "deny")
        sys.exit(0)
    except Exception:
        # Any unexpected error anywhere in the decision path fails open -
        # a hook bug must never block ticket creation outright.
        sys.exit(0)


if __name__ == "__main__":
    main()
