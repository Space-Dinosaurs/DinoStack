#!/usr/bin/env python3
"""
Purpose: Decision logic for the prompt-cache keepalive gate
         (hooks/cache-keepalive.py). From a transcript it decides, for each
         keepalive cron fire, whether to ping (refresh a warm 1h cache the
         operator is likely to come back to), wrap the idle session, ask
         the model to delete its cron (release_note), or block the fire
         before it makes a request; and, on a prompt, whether to ask the
         model to create the cron.

Public API:
    Constants: CRON_EXPR, PERIOD_S, TTL_S, COLD_AFTER_S, EFFECTIVE_INTERVAL_S,
        ACTIVE_WINDOW_S, RELEASE_AFTER_S, MIN_PREFIX_TOKENS, TAIL_BYTES,
        DERIVATION_RATES, PING_CC_TOKENS, PING_OUT_TOKENS, CREATE_NOTE_MARKER,
        MAX_CREATE_NOTES, RELEASE_MARKER, PROCESS_START_HOOKS,
        BLOCK_OUTPUT, WRAP_MARKER, WRAP_PERMISSION_MODES,
        NON_OPERATOR_PREFIXES, TERMINAL_STATUSES, IN_FLIGHT_MAX_BYTES,
        RESUME_DIR, RESUME_MAX_BYTES, RESUME_RETENTION_DAYS, KILL_SWITCH_ENV,
        CONFIG_KEY.
    ping_cost(S) / max_pings(S): cost of one ping at prefix S in input-token
        units, and the per-idle-period cap floor((W - R) * S / ping_cost(S)),
        so pinging never costs more than the cold re-write it avoids.
    is_active(cwd, repo=None) -> bool: the activation preflight's step 4
        via bin/ds-status (loaded from repo_dir); False for a no-op project
        and when the resolver cannot load.
    is_enabled(cwd) -> bool: False iff AE_CACHE_KEEPALIVE_DISABLE=1, the
        project is not active (is_active), or the first config carrying
        `cache_keepalive` sets a literal false. Lookup:
        <resolve_agentic_cwd(cwd)>/.agentic/config.json, then
        ~/.claude/agentic-engineering.json, then the default true.
    is_conductor(transcript_path) -> bool: <transcript minus .jsonl>/subagents
        is a directory, i.e. the session has spawned a subagent.
    session_state(records) -> dict: ttl ("1h" | "5m" | None),
        last_request_start, idle_since, prefix_tokens, ping_rate_limited,
        pings_since_idle, wrapped_since_idle (a ping turn after the newest
        real request carried WRAP_MARKER), fires_since_wrap (ping records
        after the last such turn), deletes_since_idle (ping turns after the
        newest real request that made a request without a GATE_NOTE or
        WRAP_MARKER note, i.e. release fires).
    in_flight(transcript_path, started_at=None) -> bool: an async agent or
        background Bash task launched in this process has no terminal
        notification (a user record or a queued_command attachment, in
        either order relative to the launch) and no TaskStop result yet.
        Launches before started_at or before a PROCESS_START_HOOKS
        SessionStart attachment are dropped: they died with their process.
        True on any doubt.
    wrap_allowed(permission_mode) -> bool: permission_mode is in
        WRAP_PERMISSION_MODES.
    decide(state, now, enabled, conductor, in_flight, wrap_ok, wrap_mode_ok)
        -> (action, reason); action is ping | wrap | delete | block.
    cron_jobs(records, started_at=None, complete=False) -> (status, ids):
        status "live" | "absent" | "unknown" for this process's keepalive
        crons (current or legacy prompt), replayed from CronCreate,
        CronDelete and CronList results; a record is this process's when it
        follows the last record before started_at or the last
        PROCESS_START_HOOKS attachment, or is stamped at or after started_at.
        ids: the live job ids. cron_status(...) -> the status alone.
    creation_due(records, state, enabled, conductor, started_at=None,
        complete=False, operator=True) -> (due, check_existing): not live,
        no denied create since the last delete or process start, fewer than
        MAX_CREATE_NOTES notes since then, and, when operator is False, at
        least one such note already (a repeat, never a first ask).
    create_note(check_existing) -> str: the CREATE_NOTE_MARKER instruction.
    release_note(job_ids) -> str: the RELEASE_MARKER instruction to
        CronDelete the named jobs (CronList first when none), then "ok".
    gate_note(state, now) -> str: GATE_NOTE plus the one reply line the
        model echoes, e.g. "keepalive: cache warmed (idle 40m, next check
        4:28pm)": idle is now - idle_since (omitted when unknown), the
        check is now + PERIOD_S in local time.
    repo_dir() -> str; wrap_command_path(repo) -> str.
    wrap_tool_path(repo) -> str: <repo>/bin/ds-keepalive-wrap.
    wrap_command(repo, session_id, root) -> str: the shell-quoted
        ds-keepalive-wrap invocation the wrap note carries.
    kickoff_command(session_id, root) -> str: `claude <quoted
        KICKOFF_PROMPT>`, naming <root>/.agentic by absolute path.
    wrap_note(repo, session_id, root) -> str: WRAP_MARKER note naming the
        procedure file, the project root, the wrap command and the kickoff.
    process_started_at(env, session_id) -> float | None.

Definitions (main chain only; sidechain records are ignored):
    A request is one non-synthetic assistant message id; its start is the
    timestamp of the nearest user-type record before it (send time). A turn
    starts at a non-tool_result user record that carries turnOrigin or is
    not isMeta; it is a ping turn iff that record passes
    loop_guard.is_ping_record. L = now - last_request_start. idle_since is
    the start of the newest request outside a ping turn, so pings never
    move the release clock, and requests triggered by task notifications
    (every subagent completion) do. pings_since_idle counts ping turns
    after idle_since that made at least one request; a blocked fire makes
    none and writes only isMeta records after the newest request, so it
    moves none of these values.

decide order (first that holds wins; every delete is carried out by the
release_note the hook attaches, since PING_PROMPT itself asks for nothing):
    disabled, ttl-not-1h, small-prefix, not-conductor -> delete if
        L < COLD_AFTER_S (the release turn costs 2 warm requests),
        else block (a cold release would pay a full re-write).
    rate-limited -> block.  cache-presumed-cold (L >= COLD_AFTER_S) -> block.
    already-wrapped (wrapped since idle_since: the wrap turn's CronDelete
        was skipped or failed) -> delete on the first fire after the wrap,
        block on every later one; a session never wraps twice per idle.
    release-wrap (now - idle_since >= RELEASE_AFTER_S, nothing in flight)
        -> wrap; delete when the session's permission_mode is not in
        WRAP_PERMISSION_MODES (release-no-wrap-mode: the wrap's Bash calls
        would wait at a prompt) or the wrap command file or
        bin/ds-keepalive-wrap is missing.
    cost-capped (pings_since_idle >= max_pings(prefix)) -> delete.
    recently-active (L < ACTIVE_WINDOW_S) -> block.  Otherwise pass -> ping.
    Then delete-ignored: any delete becomes block when deletes_since_idle
        > 0 (a release already ran this idle stretch and the cron still
        fires), so a denied or ignored CronDelete costs one request, not one
        per fire.

Derivation (bin/ds-cache-keepalive-sim reproduces every figure):
    Timing: fires every PERIOD_S; a fire pings when L is in
    [ACTIVE_WINDOW_S, COLD_AFTER_S), a window exactly one period wide, so
    exactly one fire per idle stretch lands in it and idle pings are
    EFFECTIVE_INTERVAL_S apart. COLD_AFTER_S = TTL_S - 120 s of margin for
    the request's own latency.
    Data: 30 days of main-session transcripts across all 4 local config
    stores, conductor sessions only (non-conductor sessions: EV <= +0.8M at
    every setting, so they get no cron). 568 conductor returns after >= 35
    min idle; gaps across a process restart excluded; 332 terminal
    sessions. Ping cost read*S + write_1h*cc + output*out with cc=854,
    out=193 (medians of 22 scheduled fires). M8 measured gated pings at a
    median cc=446, out=39, but on n=5 scratch sessions with small prefixes;
    PING_CC_TOKENS/PING_OUT_TOKENS keep the larger corpus figures, which
    understate EV and lower max_pings, so the error runs conservative.
    Keepalive EV at P=20 min, 2h release (base-input-token equivalents,
    by abandoned-open fraction f): median 15.6 / 39.0 / 50.2 / 57.6 / 62.3M
    at f = 1 / 0.5 / 0.26 / 0.1 / 0; p90 cost 8.2 / 45.4 (f=0.26) / 58.5M.
    Positive at every f.
    Wrap: 201 returns past release, 332 terminal sessions. At 4 requests
    per wrap the cost is 49.7M on returns and 75.0M on terminals (all
    open); starting fresh after the wrap saves 169.0M, for a net +181.6M at
    f=0 and +59.9M at f=1. Resuming the wrapped session cold instead nets
    +12.6M / -109.1M, so the docs tell the operator to start fresh.
    Cost cap: bounds pinging while a subagent hangs past release.
    DERIVATION_RATES are input-token multipliers pinned by a test against
    bin/_telemetry.py DEFAULT_RATES.

Upstream deps: Python 3 stdlib; sibling loop_guard.py (ping literals,
    read_tail_records, resolve_agentic_cwd), loaded with importlib at import
    time; a load failure raises to the importer. bin/ds-status
    (_load_config, _resolve_agents_md, _scan_agents_md, _resolve), loaded
    from repo_dir() by is_active, since the hooks snapshot does not carry
    it; ~/.agentic/agentic-engineering-config.json (repo_dir).

Downstream consumers: hooks/cache-keepalive.py; bin/ds-cache-keepalive-sim
    imports the constants; bin/ds-keepalive-wrap imports RESUME_DIR,
    RESUME_MAX_BYTES and RESUME_RETENTION_DAYS and is the command
    wrap_command() names; bin/_transcripts.py imports LG, WRAP_MARKER
    and (through LG) GATE_NOTE to tag ping turns for ds-eval;
    hooks/tests/test-cache-keepalive.py.

Failure modes: never writes. is_active, and so is_enabled, is False when
    bin/ds-status cannot be loaded or raises; with the project active, an
    unreadable or keyless config falls through to the default True.
    session_state skips unparseable records; a tail with no usage gives
    ttl None (ttl-not-1h). A missing request start counts as cold; a
    missing idle_since as released. in_flight is True on read errors, an
    unparseable candidate line, or a file over IN_FLIGHT_MAX_BYTES.

Performance: one bounded tail read (TAIL_BYTES) per decision; in_flight
    streams the whole file but parses only candidate lines, and only once
    release is reached.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shlex
import time


def _load_loop_guard():
    import importlib.util as _ilu

    here = os.path.dirname(os.path.abspath(__file__))
    spec = _ilu.spec_from_file_location("loop_guard", os.path.join(here, "loop_guard.py"))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LG = _load_loop_guard()

CRON_EXPR = "7,27,47 * * * *"
PERIOD_S = 1200
TTL_S = 3600
COLD_AFTER_S = 3480
EFFECTIVE_INTERVAL_S = (COLD_AFTER_S // PERIOD_S) * PERIOD_S
ACTIVE_WINDOW_S = COLD_AFTER_S - PERIOD_S
RELEASE_AFTER_S = 7200
MIN_PREFIX_TOKENS = 50000
TAIL_BYTES = LG.TAIL_BYTES
DERIVATION_RATES = {"write_1h": 2.0, "read_max": 0.1, "output": 5.0}
PING_CC_TOKENS = 854
PING_OUT_TOKENS = 193

CREATE_NOTE_MARKER = "[dinostack-cache-keepalive:create]"
MAX_CREATE_NOTES = 3
RELEASE_MARKER = LG.RELEASE_MARKER
# Permission modes in which every in-session wrap tool call ran without a
# prompt in a project with no allow rules (measured on 2.1.287: Read of the
# command file, call A, call B). In default and acceptEdits both Bash calls
# prompted, so an unattended wrap would wait at a prompt; there, release
# deletes the cron instead. CronCreate/CronDelete prompted in none of the
# four measured modes (default, acceptEdits, auto, bypassPermissions); plan
# and dontAsk were not measured and get the same self-delete.
WRAP_PERMISSION_MODES = frozenset(("auto", "bypassPermissions"))
# Prompts the harness submits on a subagent's behalf (measured: a subagent
# hand-back arrives as a UserPromptSubmit starting "<agent-message from=").
NON_OPERATOR_PREFIXES = ("<agent-message", "<task-notification>")
BLOCK_OUTPUT = {"continue": False, "suppressOutput": True, "stopReason": ""}
WRAP_MARKER = LG.WRAP_MARKER
TERMINAL_STATUSES = frozenset(("completed", "failed", "killed", "stopped"))
IN_FLIGHT_MAX_BYTES = 256 * 1024 * 1024
RESUME_DIR = ".agentic/resume"
RESUME_MAX_BYTES = 8192
RESUME_RETENTION_DAYS = 14

KILL_SWITCH_ENV = "AE_CACHE_KEEPALIVE_DISABLE"
CONFIG_KEY = "cache_keepalive"
GLOBAL_CONFIG = os.path.expanduser("~/.claude/agentic-engineering.json")
AE_CONFIG = os.path.expanduser("~/.agentic/agentic-engineering-config.json")
WRAP_COMMAND_REL = os.path.join("content", "commands", "ds-wrap-deferred.md")

# {agentic} is the absolute <root>/.agentic the wrap wrote to: the root is
# the git-root ancestor of the launch directory, so a session launched from
# a subdirectory must not look for .agentic/ relative to its own cwd.
KICKOFF_PROMPT = (
    "Resume wrapped session {sid}: read {agentic}/context.md first, then "
    "{agentic}/resume/{sid}.md. Restate its Next step and Pending operator "
    "decisions verbatim, move the file to {agentic}/resume/consumed/, then "
    "continue from the Next step."
)
FALLBACK_PROMPT = (
    "Resume my last wrapped session: read .agentic/context.md first, then "
    "the newest file in .agentic/resume/ (not consumed/). Restate its Next "
    "step and Pending operator decisions verbatim, move it to "
    ".agentic/resume/consumed/, then continue from the Next step."
)


def ping_cost(S):
    r = DERIVATION_RATES
    return r["read_max"] * S + r["write_1h"] * PING_CC_TOKENS + r["output"] * PING_OUT_TOKENS


def max_pings(S):
    r = DERIVATION_RATES
    return int((r["write_1h"] - r["read_max"]) * S // ping_cost(S))


def _config_value(path):
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        return None
    if isinstance(data, dict) and CONFIG_KEY in data:
        return data[CONFIG_KEY]
    return None


def _load_status_resolver(repo):
    """bin/ds-status from the DinoStack checkout: the canonical activation
    resolver (global mode + AGENTS.md marker). The hooks snapshot does not
    carry bin/ds-status, so it is loaded from repo_dir."""
    import importlib.machinery
    import importlib.util as _ilu

    path = os.path.join(repo, "bin", "ds-status")
    loader = importlib.machinery.SourceFileLoader("ds_status_for_keepalive", path)
    spec = _ilu.spec_from_loader("ds_status_for_keepalive", loader)
    mod = _ilu.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def is_active(cwd: str, repo=None) -> bool:
    """content/sections/01-activation-preflight.md step 4, via bin/ds-status:
    False when the project resolves to no-op (mode opt-out + marker opt-out,
    or mode opt-in without an opt-in marker). False when the resolver cannot
    be loaded or raises, since a ping or wrap in a no-op project writes into
    its .agentic/."""
    try:
        status = _load_status_resolver(repo or repo_dir())
        config, config_status = status._load_config()
        prev = os.getcwd()
        try:
            os.chdir(LG.resolve_agentic_cwd(cwd) if cwd else prev)
            scan = status._scan_agents_md(status._resolve_agents_md())
        finally:
            os.chdir(prev)
        return bool(status._resolve(config, scan, config_status).get("active"))
    except Exception:
        return False


def is_enabled(cwd: str) -> bool:
    if os.environ.get(KILL_SWITCH_ENV) == "1":
        return False
    if not is_active(cwd):
        return False
    paths = []
    if cwd:
        paths.append(os.path.join(LG.resolve_agentic_cwd(cwd), ".agentic", "config.json"))
    paths.append(GLOBAL_CONFIG)
    for path in paths:
        value = _config_value(path)
        if value is not None:
            return value is not False
    return True


def is_conductor(transcript_path) -> bool:
    if not isinstance(transcript_path, str) or not transcript_path:
        return False
    return os.path.isdir(os.path.join(os.path.splitext(transcript_path)[0], "subagents"))


def _ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def session_state(records) -> dict:
    requests = []
    seen_ids = set()
    rate_limited_starts = []
    last_user_ts = None
    in_ping_turn = False
    turn = 0
    wrap_turns = []
    ping_turns = []
    gated_turns = set()
    for rec in records:
        if not isinstance(rec, dict) or rec.get("isSidechain"):
            continue
        kind = rec.get("type")
        ts = _ts(rec.get("timestamp"))
        if kind == "attachment":
            att = rec.get("attachment") or {}
            if in_ping_turn and att.get("hookEvent") == "UserPromptSubmit":
                blob = json.dumps(att)
                if WRAP_MARKER in blob:
                    wrap_turns.append(turn)
                if WRAP_MARKER in blob or LG.GATE_NOTE in blob:
                    gated_turns.add(turn)
            continue
        if kind == "user":
            if ts is not None:
                last_user_ts = ts
            if LG.starts_turn(rec):
                in_ping_turn = LG.is_ping_record(rec)
                turn += 1
                if in_ping_turn:
                    ping_turns.append(turn)
            continue
        if kind != "assistant":
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        if msg.get("model") == "<synthetic>":
            if rec.get("error") == "rate_limit" and in_ping_turn:
                rate_limited_starts.append(last_user_ts if last_user_ts is not None else ts)
            continue
        mid = msg.get("id")
        usage = msg.get("usage")
        if not mid or not isinstance(usage, dict) or mid in seen_ids:
            continue
        seen_ids.add(mid)
        creation = usage.get("cache_creation") or {}
        requests.append({
            "start": last_user_ts if last_user_ts is not None else ts,
            "ping": in_ping_turn,
            "turn": turn,
            "c1h": creation.get("ephemeral_1h_input_tokens", 0) or 0,
            "c5m": creation.get("ephemeral_5m_input_tokens", 0) or 0,
            "prefix": (usage.get("input_tokens", 0) or 0)
            + (usage.get("cache_read_input_tokens", 0) or 0)
            + (usage.get("cache_creation_input_tokens", 0) or 0),
        })

    ttl = None
    for req in reversed(requests):
        if req["c1h"] > 0:
            ttl = "1h"
            break
        if req["c5m"] > 0:
            ttl = "5m"
            break
    real = [r for r in requests if not r["ping"]]
    idle_since = real[-1]["start"] if real else None
    last_real_turn = real[-1]["turn"] if real else 0
    wraps = [t for t in wrap_turns if t > last_real_turn]
    return {
        "wrapped_since_idle": bool(wraps),
        "fires_since_wrap": len([t for t in ping_turns if wraps and t > wraps[-1]]),
        "ttl": ttl,
        "last_request_start": requests[-1]["start"] if requests else None,
        "idle_since": idle_since,
        "prefix_tokens": requests[-1]["prefix"] if requests else 0,
        "ping_rate_limited": any(
            t is not None and (idle_since is None or t > idle_since) for t in rate_limited_starts
        ),
        "pings_since_idle": len({r["turn"] for r in requests if r["ping"] and r["turn"] > last_real_turn}),
        "deletes_since_idle": len({r["turn"] for r in requests
                                   if r["ping"] and r["turn"] > last_real_turn and r["turn"] not in gated_turns}),
    }


_LAUNCH_RE = re.compile(r"Async agent launched successfully.*?agentId: ([A-Za-z0-9_-]+)", re.S)
_BG_RE = re.compile(r"running in background with ID: ([A-Za-z0-9_-]+)")
_STOPPED_RE = re.compile(r"Successfully stopped task: ([A-Za-z0-9_-]+)")
_TASK_ID_RE = re.compile(r"<task-id>([^<]+)</task-id>")
_STATUS_RE = re.compile(r"<status>([^<]+)</status>")
_CANDIDATES = ("launched successfully", "running in background with ID", "<task-notification>", '"SendMessage"',
               "Successfully stopped task", "SessionStart:startup", "SessionStart:resume")
# SessionStart hook names that mark a new process. A compaction also fires
# SessionStart ("SessionStart:compact") but keeps the process, its crons and
# its background tasks.
PROCESS_START_HOOKS = ("SessionStart:startup", "SessionStart:resume")


def _is_process_start(rec) -> bool:
    att = rec.get("attachment") if rec.get("type") == "attachment" else None
    return isinstance(att, dict) and att.get("hookEvent") == "SessionStart" and att.get("hookName") in PROCESS_START_HOOKS


def _record_texts(rec):
    msg = rec.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return [content]
    out = []
    if isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and isinstance(b.get("text"), str):
                out.append(b["text"])
            elif b.get("type") == "tool_result":
                c = b.get("content")
                if isinstance(c, str):
                    out.append(c)
                elif isinstance(c, list):
                    out.extend(x.get("text", "") for x in c if isinstance(x, dict) and isinstance(x.get("text"), str))
    return out


def in_flight(transcript_path, started_at=None) -> bool:
    try:
        if os.path.getsize(transcript_path) > IN_FLIGHT_MAX_BYTES:
            return True
        launched = set()
        active = set()
        finished = set()
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not any(c in line for c in _CANDIDATES):
                    continue
                rec = json.loads(line)
                if not isinstance(rec, dict) or rec.get("isSidechain"):
                    continue
                if _is_process_start(rec):
                    # Agents and background shells die with their process
                    # and never send a terminal notification.
                    launched.clear()
                    active.clear()
                    finished.clear()
                    continue
                kind = rec.get("type")
                if kind == "assistant":
                    msg = rec.get("message")
                    for b in (msg.get("content") if isinstance(msg, dict) else None) or []:
                        if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "SendMessage":
                            to = (b.get("input") or {}).get("to")
                            if to in launched:
                                active.add(to)
                                finished.discard(to)
                    continue
                if kind == "user":
                    texts = _record_texts(rec)
                elif kind == "attachment" and isinstance((rec.get("attachment") or {}).get("prompt"), str):
                    # A notification that arrives while the model is busy is
                    # written only as a queued_command attachment.
                    texts = [rec["attachment"]["prompt"]]
                else:
                    continue
                ts = _ts(rec.get("timestamp"))
                earlier_process = started_at is not None and ts is not None and ts < started_at
                for text in texts:
                    for m in list(_LAUNCH_RE.finditer(text)) + list(_BG_RE.finditer(text)):
                        if earlier_process:
                            continue
                        launched.add(m.group(1))
                        # A fast task's notification can be written before
                        # the tool_result that announces its launch.
                        if m.group(1) not in finished:
                            active.add(m.group(1))
                    for m in _STOPPED_RE.finditer(text):
                        finished.add(m.group(1))
                        active.discard(m.group(1))
                    if "<task-notification>" in text:
                        for block in text.split("<task-notification>")[1:]:
                            tid = _TASK_ID_RE.search(block)
                            st = _STATUS_RE.search(block)
                            if not tid:
                                continue
                            if st and st.group(1).strip() in TERMINAL_STATUSES:
                                finished.add(tid.group(1))
                                active.discard(tid.group(1))
                            elif tid.group(1) in launched:
                                active.add(tid.group(1))
        return bool(active)
    except Exception:
        return True


def wrap_allowed(permission_mode) -> bool:
    return permission_mode in WRAP_PERMISSION_MODES


def decide(state, now, enabled=True, conductor=True, in_flight=lambda: True, wrap_ok=True, wrap_mode_ok=True):
    action, reason = _decide(state, now, enabled, conductor, in_flight, wrap_ok, wrap_mode_ok)
    if action == "delete" and state.get("deletes_since_idle"):
        # A self-delete already ran this idle stretch and the cron still
        # fires (CronDelete denied or ignored): every further delete fire
        # would be another warm request, and no later check bounds it.
        return ("block", "delete-ignored")
    return (action, reason)


def _decide(state, now, enabled, conductor, in_flight, wrap_ok, wrap_mode_ok):
    last = state.get("last_request_start")
    L = float("inf") if last is None else now - last
    warm = L < COLD_AFTER_S

    def ineligible(reason):
        return ("delete" if warm else "block", reason)

    if not enabled:
        return ineligible("disabled")
    if state.get("ttl") != "1h":
        return ineligible("ttl-not-1h")
    if (state.get("prefix_tokens") or 0) < MIN_PREFIX_TOKENS:
        return ineligible("small-prefix")
    if not conductor:
        return ineligible("not-conductor")
    if state.get("ping_rate_limited"):
        return ("block", "rate-limited")
    if not warm:
        return ("block", "cache-presumed-cold")
    if state.get("wrapped_since_idle"):
        # Only the model's CronDelete ends the cron; if the wrap turn skipped
        # or failed it, release still holds, so without this every later
        # fire would wrap again. One more self-delete, then block.
        return ("block" if state.get("fires_since_wrap") else "delete", "already-wrapped")
    idle_since = state.get("idle_since")
    if (idle_since is None or now - idle_since >= RELEASE_AFTER_S) and not in_flight():
        if not wrap_mode_ok:
            return ("delete", "release-no-wrap-mode")
        return ("wrap", "release-wrap") if wrap_ok else ("delete", "release-wrap-unavailable")
    if (state.get("pings_since_idle") or 0) >= max_pings(state.get("prefix_tokens") or 0):
        return ("delete", "cost-capped")
    if L < ACTIVE_WINDOW_S:
        return ("block", "recently-active")
    return ("ping", "pass")


def _tool_results_by_id(records):
    out = {}
    for rec in records:
        if rec.get("type") != "user":
            continue
        msg = rec.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                c = b.get("content")
                if isinstance(c, list):
                    c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                out[b.get("tool_use_id")] = c if isinstance(c, str) else ""
    return out


_JOB_ID_RE = re.compile(r"job ([0-9a-f]{8})")
# One CronList line per job (measured, 2.1.287):
# "c02e1ce7 \u2014 7,27,47 * * * * (recurring) [session-only]: <prompt, truncated>"
_LISTED_JOB_RE = re.compile(r"^([0-9a-f]{8}) .*?: " + re.escape(LG.MARKER) + " ", re.M)


def process_started_at(env, session_id):
    """startedAt (epoch s) of this session's live process from
    <config dir>/sessions/<CLAUDE_PID>.json, or None. A SessionStart
    attachment is written only when a SessionStart hook prints something,
    so it cannot mark every process start on its own."""
    try:
        pid = env.get("CLAUDE_PID")
        config_dir = env.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
        with open(os.path.join(config_dir, "sessions", str(int(pid)) + ".json"), "r") as f:
            entry = json.load(f)
        if entry.get("sessionId") != session_id:
            return None
        return float(entry["startedAt"]) / 1000.0
    except Exception:
        return None


def _scan_crons(records, started_at=None, complete=False):
    """Index of the last record from an earlier process (None if unknown;
    -1 when `complete` - the records are the whole transcript - and none
    predates started_at); our cron events in order as (index, kind, value,
    current): create (job id or None, result_seen), delete (job id) and
    list (the job ids a CronList showed), current when the record is known
    to come from this process; and create-note injection indexes."""
    results = _tool_results_by_id(records)
    process_start = -1 if (complete and started_at is not None) else None
    events = []
    injections = []
    stamps = {}
    for i, rec in enumerate(records):
        if rec.get("isSidechain"):
            continue
        ts = _ts(rec.get("timestamp"))
        stamps[i] = ts
        if started_at is not None and ts is not None and ts < started_at:
            process_start = i
        if rec.get("type") == "attachment":
            att = rec.get("attachment") or {}
            if _is_process_start(rec):
                process_start = i
            if att.get("hookEvent") == "UserPromptSubmit" and CREATE_NOTE_MARKER in json.dumps(att):
                injections.append(i)
            continue
        if rec.get("type") == "user":
            for text in _record_texts(rec):
                for m in re.finditer(r"Cancelled job ([0-9a-f]{8})", text):
                    events.append((i, "delete", m.group(1)))
            continue
        if rec.get("type") != "assistant":
            continue
        msg = rec.get("message")
        for b in (msg.get("content") if isinstance(msg, dict) else None) or []:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            inp = b.get("input") or {}
            res = results.get(b.get("id"))
            if b.get("name") == "CronCreate" and inp.get("prompt") in LG.PING_PROMPTS:
                m = _JOB_ID_RE.search(res) if isinstance(res, str) else None
                events.append((i, "create", (m.group(1) if m else None, res is not None)))
            elif b.get("name") == "CronDelete":
                events.append((i, "delete", inp.get("id")))
            elif b.get("name") == "CronList" and isinstance(res, str):
                events.append((i, "list", _LISTED_JOB_RE.findall(res)))
    ours = set()
    for _, kind, value in events:
        if kind == "create" and value[0]:
            ours.add(value[0])
        elif kind == "list":
            ours.update(value)

    def current(i):
        if process_start is not None and i > process_start:
            return True
        return started_at is not None and stamps.get(i) is not None and stamps[i] >= started_at

    events = [(i, kind, value, current(i)) for i, kind, value in events if kind != "delete" or value in ours]
    return process_start, events, injections


def cron_jobs(records, started_at=None, complete=False):
    """(status, job ids): status is "live" when this process has at least
    one keepalive cron, "absent" when it provably has none, else "unknown";
    the ids are the live keepalive jobs this transcript names, oldest first."""
    process_start, events, _ = _scan_crons(records, started_at, complete)
    live = []
    known = process_start is not None
    last_create = None
    for _, kind, value, current in events:
        if not current:
            continue
        if kind == "create":
            last_create = value
            if value[0]:
                known = True
                live = [j for j in live if j != value[0]] + [value[0]]
        elif kind == "delete":
            live = [j for j in live if j != value]
        else:
            known = True
            live = list(value)
    if live:
        return ("live", live)
    if known or (last_create is not None and last_create[1]):
        return ("absent", [])
    return ("unknown", [])


def cron_status(records, started_at=None, complete=False) -> str:
    return cron_jobs(records, started_at, complete)[0]


def creation_due(records, state, enabled, conductor, started_at=None, complete=False, operator=True):
    if not (enabled and conductor):
        return (False, False)
    if state.get("ttl") != "1h" or (state.get("prefix_tokens") or 0) < MIN_PREFIX_TOKENS:
        return (False, False)
    status, _ = cron_jobs(records, started_at, complete)
    if status == "live":
        return (False, False)
    process_start, events, injections = _scan_crons(records, started_at, complete)
    anchors = [i for i, kind, _, _ in events if kind == "delete"] + ([process_start] if process_start is not None else [])
    anchor = max(anchors) if anchors else -1
    # A create denied by a permission rule or the auto-mode classifier
    # (measured: "Unauthorized Persistence") is a decline, not a retry cue.
    if any(i > anchor and kind == "create" and not value[0] and value[1] for i, kind, value, _ in events):
        return (False, False)
    notes = [i for i in injections if i > anchor]
    # An ignored note is repeated on later turns, up to MAX_CREATE_NOTES
    # (measured: 28 notes, 17 creates; one ignored note left the session
    # without a cron for 14.3h). A turn the operator did not type only
    # repeats a note the operator's own turn already received, so a release
    # is not undone by a task notification arriving while the operator is away.
    if len(notes) >= MAX_CREATE_NOTES or (not operator and not notes):
        return (False, False)
    return (True, status == "unknown")


def _every(seconds):
    minutes = max(1, int(seconds) // 60)
    return "minute" if minutes == 1 else "%d minutes" % minutes


def create_note(check_existing: bool) -> str:
    # States provenance, purpose and the off switch. Measured on haiku: a note
    # telling the model to hide the job from the user was refused and
    # reported to the user in 4 of 4 sessions.
    tools = "CronCreate, CronList and CronDelete"
    check = (", call CronList and stop if a job with the prompt below already exists"
             if check_existing else "")
    return (
        CREATE_NOTE_MARKER + " DinoStack cache keepalive, a DinoStack default the operator "
        "can turn off (config key " + CONFIG_KEY + "; off with `" + CONFIG_KEY
        + ": false` or " + KILL_SWITCH_ENV + "=1). It keeps this session's 1h "
        "prompt cache warm while the operator is away by re-submitting a short "
        "prompt every " + _every(PERIOD_S) + "; a DinoStack hook drops every fire that would "
        "not help, and the job deletes itself once the session is idle for good. "
        "As part of this turn, load " + tools + " with one ToolSearch (query "
        "\"select:CronCreate,CronList,CronDelete\")" + check + ", then call "
        "CronCreate with cron " + json.dumps(CRON_EXPR) + ", recurring true, "
        "durable false, prompt exactly " + json.dumps(LG.PING_PROMPT) + ". If "
        "you mention it, use one line naming the job and the opt-out; if asked, "
        "explain it plainly."
    )


def release_note(job_ids) -> str:
    if job_ids:
        target = "call CronDelete for job " + " and job ".join(job_ids)
    else:
        target = ("call CronList, then CronDelete every job whose prompt starts with "
                  + LG.MARKER)
    return (
        RELEASE_MARKER + " DinoStack keepalive release: this session's keepalive "
        "cron is no longer needed. In this turn, " + target + ", then reply with "
        "exactly: ok. Do nothing else."
    )


def _duration(seconds):
    minutes = int(seconds) // 60
    return "%dm" % minutes if minutes < 60 else "%dh%02dm" % divmod(minutes, 60)


def gate_note(state, now) -> str:
    # The next fire is one PERIOD_S after this one (measured, M3); it is a
    # check, not a promised ping, since the gate decides again then.
    idle_since = state.get("idle_since")
    idle = "idle %s, " % _duration(now - idle_since) if idle_since is not None else ""
    t = time.localtime(now + PERIOD_S)
    when = "%d:%02d%s" % (t.tm_hour % 12 or 12, t.tm_min, "am" if t.tm_hour < 12 else "pm")
    return LG.GATE_NOTE + LG.GATE_REPLY_LEAD + "keepalive: cache warmed (" + idle + "next check " + when + ")"


def repo_dir() -> str:
    try:
        with open(AE_CONFIG, "r") as f:
            value = json.load(f).get("repo_dir")
        if isinstance(value, str) and value and os.path.isdir(value):
            return value
    except Exception:
        pass
    return os.path.expanduser("~/DinoStack")


def wrap_command_path(repo: str) -> str:
    return os.path.join(repo, WRAP_COMMAND_REL)


def wrap_tool_path(repo: str) -> str:
    return os.path.join(repo, "bin", "ds-keepalive-wrap")


def wrap_command(repo: str, session_id: str, root: str) -> str:
    return " ".join(shlex.quote(part) for part in (wrap_tool_path(repo), "--root", root, "--session-id", session_id))


def kickoff_command(session_id: str, root: str) -> str:
    # No cd and no CLAUDE_CONFIG_DIR prefix: the operator starts the fresh
    # session from the shell the wrapped session ran in. The session id keeps
    # concurrent sessions in one repo apart; the absolute paths make the
    # prompt work from any directory of that repo.
    return "claude " + shlex.quote(KICKOFF_PROMPT.format(sid=session_id, agentic=os.path.join(root, ".agentic")))


def wrap_note(repo: str, session_id: str, root: str) -> str:
    # Measured on haiku, both fixed here: inline as "Kickoff: <cmd>", the
    # kickoff (a prompt addressed to a future session) was run or obeyed
    # instead of the wrap, so it is fenced as data; and without an explicit
    # project root the model took the DinoStack checkout for the project and
    # wrote into its .agentic/.
    kickoff = kickoff_command(session_id, root)
    return (
        WRAP_MARKER + " " + LG.GATE_NOTE + " Do not reply ok. This session "
        "has been idle for 2h: wrap it now by following "
        + wrap_command_path(repo) + " §In-session mode (read it once), steps 1-5, for "
        "session " + session_id + ". Project root: " + root + " - run every "
        "command there and write only under " + os.path.join(root, ".agentic")
        + "/; never write anywhere else. Resume file: "
        + os.path.join(root, RESUME_DIR, session_id + ".md")
        + ". WRAP_COMMAND below is the one command that writes the wrap: run "
        "it exactly as given, adding only the heredoc the procedure describes. "
        "The KICKOFF below is a shell command for the "
        "operator to paste into a new terminal later. Never run it and never "
        "act on the prompt inside it; only copy it, verbatim, into the resume "
        "file header, the Recent Focus label and your final line. If "
        "WRAP_COMMAND does not print `wrap files written`, end with the line "
        "the procedure gives for that case and no kickoff. Otherwise end your "
        "reply with exactly one line: Session wrapped (idle 2h). Run /exit, "
        "then resume with: <KICKOFF>\nWRAP_COMMAND: " + wrap_command(repo, session_id, root)
        + "\nKICKOFF: " + kickoff
    )
