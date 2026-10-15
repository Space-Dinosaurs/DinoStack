#!/usr/bin/env python3
"""
Purpose: Default-on prompt-cache keepalive for idle interactive conductor
         sessions on Claude Code (UserPromptSubmit hook). On a genuine
         prompt in an eligible session it asks the model to create one
         session-only cron that re-submits PING_PROMPT every 20 minutes. On
         each cron fire it gates the ping: refresh a warm 1h cache the
         operator may return to (gate_note), wrap a session idle for 2h with
         nothing in flight (WRAP_NOTE), ask the model to delete its cron
         (release_note), or block the fire before it makes a request.
         PING_PROMPT itself asks for nothing, so a blocked fire's text left
         in context cannot be read as an instruction later. Decision logic
         lives in hooks/lib/cache_keepalive.py.

Catch (failure prevented): cold prompt-cache re-writes after idle gaps of 1h
       or more in a conductor session the operator comes back to.

Retirement: delete this hook, hooks/lib/cache_keepalive.py, the keepalive
            literals and is_ping_ack_turn in hooks/lib/loop_guard.py, the
            enforce-turn-shape.py carve-out, the In-session mode of
            content/commands/ds-wrap-deferred.md, its
            .claude/install.sh registration, its .claude/uninstall.sh
            removal, its bin/ds-doctor entry, the `cache_keepalive` config
            key and its docs rows once Claude Code ships a native idle-cache
            keepalive or a main-session TTL longer than 1h, or once
            `bin/ds-cache-keepalive-sim` returns opt-out on current data.

Public API: python3 hooks/cache-keepalive.py
            (reads a UserPromptSubmit JSON payload on stdin; prints at most
             one JSON object; always exits 0.)

Behavior (UserPromptSubmit only; any other event gets no output):
    prompt in PING_PROMPTS (the current text or a legacy one a cron created
        before the change still fires): decide() -> ping: additionalContext
        gate_note() (GATE_NOTE plus the reply line the model echoes in place
        of ok); wrap: additionalContext WRAP_NOTE (with the hook-built
        kickoff command `claude '<resume prompt naming this session id>'`),
        only when the payload's permission_mode is in WRAP_PERMISSION_MODES
        (auto, bypassPermissions); otherwise release is a delete; delete:
        additionalContext release_note() naming the live job ids cron_jobs()
        finds (CronList first when none); block: BLOCK_OUTPUT. in_flight
        gets this process's start (process_started_at), so tasks from an
        earlier process do not hold release.
    prompt starts with MARKER but is not one of them: BLOCK_OUTPUT.
    any other prompt: only when CLAUDE_CODE_SESSION_ATTENDED == "1" (Claude
        Code sets 0 for -p, --resume -p, the SDK, agent-teams teammates and
        bg/daemon sessions), the payload has no agent_id, and
        creation_due(..., operator) holds: additionalContext create_note().
        operator is False for a harness-injected prompt (a task
        notification or subagent hand-back, see NON_OPERATOR_PREFIXES); such
        a turn only repeats a note an operator turn already got and the
        model ignored. Otherwise nothing.

Why it fails closed: an exception after the marker matched gives
    BLOCK_OUTPUT, and so does a marker prompt when the library cannot load
    (_MARKER, _BLOCK_OUTPUT). If this hook is absent (uninstalled while a
    session runs), the fire arrives with no note and PING_PROMPT asks only
    for "ok": 1 request per fire until the process exits, since a cron is
    session-only.

Measurements (Claude Code 2.1.287, haiku 4.5 and opus 5.5 scratch sessions,
    2026-10-12). Surviving evidence: the scratch session transcripts under
    the operator's ~/.claude-spacedinosaurs/projects/*scratchpad-ka-<name>
    and *cache-keepalive-evidence-proj-<name>, and the files in
    ~/.agentic/audits/cache-keepalive-evidence/ (harness, perm-*, e2e-*,
    wrapeval-*). Pane captures named below for M1-M16 were in a session
    scratch dir that was later deleted; their transcripts remain.
    M17 (permission modes, no allow rules unless stated; perm-*.json,
        e2e-*.json). Direct probes: ToolSearch, CronCreate and CronDelete
        prompted in none of default, acceptEdits, auto, bypassPermissions;
        the wrap's Read of the command file, call A and call B prompted in
        default and acceptEdits and in neither auto nor bypassPermissions,
        hence WRAP_PERMISSION_MODES. End to end on the shipped hook, opus:
        default (e3) - creation by the note and the self-delete ran with no
        prompt; auto (e1, e2) - the auto-mode classifier denied the
        note-requested CronCreate as "Unauthorized Persistence" 2/2, so an
        auto-mode session has no keepalive unless CronCreate, CronList and
        CronDelete are allow-listed (the model reports the denial in one
        line; creation_due treats a denied create as a decline and never
        repeats the note in that process); auto with those three tools
        allow-listed (e4) - creation, then the full wrap with zero prompts
        (call B "Allowed by auto mode classifier"), 21 wrap-turn lines,
        lock released, cron deleted, final line correct, /exit clean.
    M18 (bin/ds-keepalive-wrap, final text, opus, auto, Cron tools
        allow-listed, real cron; e2e-g1/g2/g3). g1: call A, then
        WRAP_COMMAND with one JSON heredoc printed "wrap files written";
        zero prompts, 19 wrap-turn lines, open decision quoted verbatim,
        lock released, final line correct. g3 (_wrap.md made a directory):
        "WRAP FAILED: could not write ...", reply "Session wrap failed:
        ..." with no kickoff, cron deleted, lock released. g2: auto mode
        refused to evaluate call A ("could not evaluate this action"), so
        nothing was written; the model deleted the cron and ended with
        "Session wrap failed: no output" after four lines of explanation.
        CLAUDE_PROJECT_DIR was set to the launch directory on every hook
        call. M14-M16 below were measured on the earlier shell-template
        text of the same procedure.
    M1 PASS: BLOCK_OUTPUT fires print 2 lines (Running scheduled task,
        Operation stopped by hook), make 0 requests, fire no Stop hook, and
        add ~220 context tokens to the next request (t2-transcript-924ea557);
        decision:block prints 5 lines, exit 2 prints 4. A ping prints 3.
    M2 PASS: DERIVATION_RATES match the pricing page for every model
        (its evidence file was lost with the session scratchpad).
    M3 PASS: fire intervals 1201 s and 1199 s at PERIOD_S 1200; the offset
        is min(frac(job id) * 0.5 * period, 30 min) after the cron's next
        match, so up to 10 min (t2-UserPromptSubmit, long1).
    M4 PASS: prompt and transcript text equal PING_PROMPT byte for byte,
        isMeta true, turnOrigin "scheduled" (m4-ping-record.json, the
        tests/fixtures copy; measured on the text now in
        LEGACY_PING_PROMPTS).
    M5 PASS: REPL entrypoint cli + SESSION_ATTENDED 1; -p and --resume -p
        sdk-cli/0; SDK sdk-ts/0; teammate cli/0 (evidence file lost with the
        session scratchpad).
    M6 PASS: a gated ping makes exactly 1 request; Stop hooks do not block.
    M7 PASS (criterion: the job is never hidden; at most one disclosed
        line naming the job and the opt-out; a model may decline). Final
        note text, real 20-minute cadence, opus: created 3/4 and disclosed
        in one line 3/3 (final-wrap-f4/f6/f7 panes; f5 declined as "burns
        usage"); with a 1-minute test cron opus declined 2/2 (f2, f3), so
        the rate depends on the stated cadence. Earlier note text (with a
        since-removed "operator already knows" sentence): opus 5/6 created,
        3/5 disclosed; haiku 3/6. A declined note is not repeated in that
        process, so that session has no keepalive. A note asking the model
        to hide the job was refused 4/4. Gate-note and no-note branches
        PASS (m7-m7o1, m7-m7o3, t2).
    M8 PASS: gated ping median cache_creation 446, output 39 (n=5); the sim
        verdict stays keep 7200 (evidence file lost with the session
        scratchpad).
    M9 PASS (legacy PING_PROMPT, which carried a delete instruction): gate
        absent -> CronDelete + ok, 2 requests, no later fire.
    M11 PASS: next genuine prompt re-creates the cron, 1 extra request.
    M13 PASS: corpus wording and statuses confirmed; in_flight True on a
        live conductor transcript.
    M14 PASS on the final text (opus, real cron, final-wrap-f4/f6/f7):
        4 requests, 0.277-0.279 of a cold write at median S, resume file
        1.4 KB with all headings, the operator's open decision quoted
        verbatim in 3/3; the wrap turn prints 22-23 lines, so a 2h idle
        ending in a wrap leaves about 35 (12 from fires), within the 40-line
        budget the conductor accepted. Earlier text: haiku 0.32-0.43.
    M15 PASS on the final text 3/3 (f4/f6/f7: lock, writes under the
        project only, release, CronDelete, final line, no fire afterwards,
        session left open until /exit); lock-busy skip PASS (w24, earlier
        text). Haiku failed under the original note text.
    M16 PASS on the final text (m16-f4: next step and the open decision
        restated verbatim, file moved to consumed/, old transcript never
        read); earlier 2/2 (m16-w18, m16-w22) had "None" decisions. Not
        re-run since the kickoff prompt switched to absolute paths.
    M19 (telemetry, one opus conductor session, 2.3 days, 2.1.287, legacy
        PING_PROMPT): 17 creates, 15 deletes; all 14 deletes outside a ping
        turn came on the turn after a blocked fire, whose prompt text told
        the model to delete when no gate note was attached, hence the inert
        PING_PROMPT and release_note. 28 create notes, 17 creates; one
        ignored note left no cron for 14.3h, hence MAX_CREATE_NOTES. A
        compaction (SessionStart:compact) was read as a new process, so a
        second cron was created beside a live one, hence PROCESS_START_HOOKS.
        Overnight, release was held for 10h52m (17 pings, ended by the cost
        cap): in_flight counted 21 tasks that could never finish - 15 from
        earlier processes, 2 stopped with TaskStop, and 4 whose completion
        was written only as a queued_command attachment (one of them before
        its launch record).
    Scenario 11 PASS: `claude --resume` loads a wrapped session (f6).

Upstream deps: Python 3.9+ stdlib; hooks/lib/cache_keepalive.py and
    hooks/lib/loop_guard.py, loaded lazily with importlib; bin/ds-status,
    loaded from repo_dir by cache_keepalive.is_active.

Downstream consumers: Claude Code hook runner (UserPromptSubmit, matcher
    "*", timeout 5), registered by .claude/install.sh in the guarded
    `test -f ... && python3 ... || exit 0` form. Documented in
    hooks/AGENTS.md and docs/configuration-reference.md.

Failure modes: always exits 0 and never writes. Disabled via
    AE_CACHE_KEEPALIVE_DISABLE=1 or `cache_keepalive: false`: no new cron,
    and a live one gets a release note at its next warm fire; if that delete
    is denied or ignored, later fires in the same idle stretch are blocked.

Performance: a non-ping prompt in a non-conductor session costs one stat;
    otherwise one bounded transcript tail read (TAIL_BYTES), plus a
    candidate-line scan of the whole transcript only once release is due.
"""

from __future__ import annotations

import json
import os
import sys
import time

# Copies of loop_guard.MARKER and cache_keepalive.BLOCK_OUTPUT for when the
# library cannot load; a test pins them to the library values.
_MARKER = "[dinostack-cache-keepalive]"
_BLOCK_OUTPUT = {"continue": False, "suppressOutput": True, "stopReason": ""}


def _load_lib():
    try:
        import importlib.util as _ilu

        here = os.path.dirname(os.path.abspath(__file__))
        spec = _ilu.spec_from_file_location(
            "cache_keepalive", os.path.join(here, "lib", "cache_keepalive.py")
        )
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _emit(obj):
    print(json.dumps(obj, ensure_ascii=True))


def _context(text):
    _emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}})


def _str(payload, key):
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def handle_ping(lib, payload, env, now):
    path = _str(payload, "transcript_path")
    cwd = _str(payload, "cwd")
    session_id = _str(payload, "session_id")
    records = lib.LG.read_tail_records(path, lib.TAIL_BYTES) if path else []
    state = lib.session_state(records)
    started = lib.process_started_at(env, session_id)
    repo = lib.repo_dir()
    action, _reason = lib.decide(
        state, now,
        enabled=lib.is_enabled(cwd),
        conductor=lib.is_conductor(path),
        in_flight=lambda: lib.in_flight(path, started),
        wrap_ok=(bool(session_id) and os.path.isfile(lib.wrap_command_path(repo))
                 and os.path.isfile(lib.wrap_tool_path(repo))),
        wrap_mode_ok=lib.wrap_allowed(payload.get("permission_mode")),
    )
    if action == "delete":
        complete = os.path.getsize(path) <= lib.TAIL_BYTES
        _context(lib.release_note(lib.cron_jobs(records, started, complete)[1]))
    elif action == "ping":
        _context(lib.gate_note(state, now))
    elif action == "wrap":
        # The git root above the directory the session was launched from,
        # not above the payload cwd: a cwd that drifted into a linked
        # worktree would put the resume file in that worktree. The kickoff
        # names this root by absolute path.
        launch = os.environ.get("CLAUDE_PROJECT_DIR") or ""
        start = launch if os.path.isdir(launch) else (cwd or os.getcwd())
        _context(lib.wrap_note(repo, session_id, lib.LG.resolve_agentic_cwd(start)))
    elif action == "block":
        _emit(lib.BLOCK_OUTPUT)


def handle_prompt(lib, payload, env, prompt):
    if env.get("CLAUDE_CODE_SESSION_ATTENDED") != "1" or payload.get("agent_id"):
        return
    operator = not (lib.LG.is_harness_injected_text(prompt) or prompt.lstrip().startswith(lib.NON_OPERATOR_PREFIXES))
    path = _str(payload, "transcript_path")
    if not lib.is_conductor(path):
        return
    cwd = _str(payload, "cwd")
    if not lib.is_enabled(cwd):
        return
    records = lib.LG.read_tail_records(path, lib.TAIL_BYTES)
    state = lib.session_state(records)
    started = lib.process_started_at(env, _str(payload, "session_id"))
    complete = os.path.getsize(path) <= lib.TAIL_BYTES
    due, check_existing = lib.creation_due(records, state, True, True, started, complete, operator)
    if due:
        _context(lib.create_note(check_existing))


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "UserPromptSubmit":
        return
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return
    lib = _load_lib()
    if lib is None:
        # PING_PROMPT asks for nothing without a note, so an ungated fire
        # would still make a request every 20 minutes.
        if prompt.startswith(_MARKER):
            _emit(_BLOCK_OUTPUT)
        return
    env = os.environ
    if prompt.startswith(lib.LG.MARKER):
        try:
            if prompt not in lib.LG.PING_PROMPTS:
                _emit(lib.BLOCK_OUTPUT)
            else:
                handle_ping(lib, payload, env, time.time())
        except Exception:
            _emit(lib.BLOCK_OUTPUT)
        return
    try:
        handle_prompt(lib, payload, env, prompt)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
