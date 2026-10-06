#!/usr/bin/env python3
"""
Purpose: SubagentStop / SessionEnd cleanup hook. Closes the agent-browser
         sessions the ending agent provably opened, then sweeps orphaned
         automation Chrome processes. agent-browser (0.27.0) runs one
         detached daemon per session name, and the daemon plus its full
         Chrome outlive every CLI call and the agent that made it, so a
         session an agent forgets to close holds a browser until something
         else ends it.

Catch: the operator's Mac hard-shut-down from memory exhaustion on
       2026-10-06. 14 of 72 agent-browser session names opened over the
       preceding 4 days were never closed, each holding a full Chrome.

Retirement: delete this hook, its two .claude/install.sh registrations, its
            .claude/uninstall.sh block, its bin/ds-doctor
            MANAGED_HOOK_BASENAMES entry and its docs rows when either holds:
    (a) structural: agent-browser binds a daemon's lifetime to its caller,
        or Claude Code reaps the processes a subagent spawned; or
    (b) measured: across at least 200 logged runs over at least 30 days on
        a host that uses agent-browser, ~/.agentic/browser-reaper.log
        shows zero non-empty `closed=` and zero `orphans_killed=` above 0.

Trigger: SubagentStop and SessionEnd only, never Stop. A Stop fires at the
         end of every main-conversation turn, and a browser the main
         conversation drives across turns must survive between them.
         - SubagentStop reads `agent_transcript_path` (the subagent's own
           transcript) and never falls back to `transcript_path`, which on
           SubagentStop is the PARENT's transcript.
         - SessionEnd reads `transcript_path` plus every
           `<transcript minus .jsonl>/subagents/agent-*.jsonl`, so a
           subagent whose SubagentStop never fired (rate-limit kill,
           interrupt, crash) is still covered when its session ends.
         - Any other event, a missing event, empty stdin, or stdin that is
           not JSON returns without doing anything and writes nothing, so
           a runner that executes every hooks/*.py with empty stdin (as
           hooks/tests/test-hooks-pep604-guard.py does) neither sweeps nor
           adds a line to the operator's log.

Ownership: a session is closed only when (1) a Bash tool_use in a scanned
           transcript ran `agent-browser ... open` for that session name
           in program position (see opened_sessions), and (2) that
           session's live daemon (`~/.agent-browser/<name>.pid`, start
           time = now - ps etime) started inside
           [tool_use time - 2 s, min(tool_result time or now,
           tool_use time + 600 s) + 2 s] of at least one such `open`.
           Condition (2) is what keeps a later session that reuses the
           name, or a daemon the `open` merely attached to, out of reach.
           The 600 s cap is the Bash tool's maximum timeout: an `open` with
           no tool_result (its agent was killed mid-command) cannot claim a
           daemon started after it could have finished. The residual is a
           same-name daemon started within 600 s of such a killed `open`.
           `default` is never closed. If the transcript scan overruns its
           deadline, an `open` with no tool_result seen yet is dropped.

Decisions:
    Background work (SubagentStop): the payload's `background_tasks` and
        `session_crons` say whether work that can wake the agent is still
        in flight. Both are session-wide, not per agent: measured on Claude
        Code 2.1.287, a background subagent's own SubagentStop lists that
        subagent itself (`id` == `agent_id`, type `subagent`), and a
        sibling's or the main session's work appears too. Deferring on any
        non-empty list would therefore keep every background subagent's
        browser until SessionEnd. The close is skipped (logged `deferred`
        with `own_pending=`) only for an entry other than the agent itself
        whose id appears in the agent's own transcript - work that agent
        launched - or an entry with no usable id. Other in-flight work is
        logged as `others_in_flight=` and does not block the close. The
        orphan sweep runs either way.
    Resume after a true stop: a subagent can be resumed after a
        SubagentStop with neither list set (KNW-20260920-006 measured
        repeat stops in 13 of 21 sampled worktree agents). Its browser is
        then gone, and its next command on that session starts a fresh
        browser with no cookies, auth state or navigation position - the
        same state an idle-timeout expiry leaves. Accepted: deferring every
        subagent close to SessionEnd would keep each finished subagent's
        Chrome alive for the whole conductor session, which is the leak
        this hook exists to stop. The cost is bounded to one re-`open` per
        resume and to sessions the resumed agent itself opened.
    SessionEnd `reason`: closes on every reason, `resume` and `clear`
        included, and logs the reason. Any ended session can be resumed
        later (`claude --resume` works after a normal exit too), so
        `resume` carries no more risk here than `prompt_input_exit`;
        session-end-wrap.js excludes `resume` for a different hazard (a
        daemon resuming a still-live session), which closing a browser
        does not have.

Orphan sweep: SIGTERM a Chrome main process only when it has no `--type=`,
    its `--user-data-dir=` contains `agent-browser-chrome-` or
    `playwright_chromiumdev_profile-`, and its parent is pid 1 or absent
    from the process table. The operator's own Chrome (a persistent
    profile) and any Chrome whose daemon is alive never match. Assumes an
    orphan reparents to pid 1; under a Linux subreaper it matches nothing,
    which fails safe.

Log: one line per run on SubagentStop/SessionEnd, whatever the verdict
     (`disabled`, `deferred`, `ran`, `fatal`), to
     ~/.agentic/browser-reaper.log, rotated to `.1` above 1 MiB. A run that
     closed nothing is therefore visible, which is what retirement (b)
     counts.

Kill switch: AE_BROWSER_REAPER_DISABLE=1 (logged as `disabled`).

Wiring: .claude/install.sh registers
        `test -f <hooks>/reap-agent-browsers.py && python3 <...> || exit 0`
        with "timeout": 10 in the "*" block of SubagentStop and SessionEnd.
        Claude Code only; transcript formats differ on other harnesses.

Public API:
    opened_sessions(cmd, inherited=None, depth=0) -> set
    candidates_from_transcript(path, deadline) -> dict
        name -> [(t_lo, t_hi_or_None)]
    owned(cands, daemon_start, now, slack=2.0) -> set
    select_orphans(rows) -> list   rows: pid -> (ppid, etime_s, command)
    own_pending_work(payload, paths, deadline) -> (set, int)
    main() -> None                 never raises past _entry(); exit 0

Upstream deps: Python 3.9+ stdlib only. `/bin/ps -axo pid=,ppid=,etime=,
    command=`. The agent-browser binary from PATH, else
    ~/.local/bin/agent-browser; with neither, nothing is closed and
    `session list` is not run.

Downstream consumers: Claude Code hook runner (SubagentStop, SessionEnd).
    Documented in hooks/AGENTS.md and content/references/
    worktree-lifecycle.md §Agent-spawned process lifetime ownership.

Failure modes: always exits 0. Any exception after a known event is logged
    as `fatal`; before one, nothing is written. Each close runs
    `agent-browser close --session <n>` in its own process group; all
    closes share a 3.5 s deadline, after which stragglers are SIGKILLed.
    Both transcript reads (own_pending_work and the `open` scan) share one
    2 s deadline; an overrun in the first defers the close, and an overrun
    in the second drops every `open` with no tool_result, so a slow read
    never adds a close. A `ps` that exceeds 1.5 s raises, which is logged as
    `fatal` and closes nothing. Misses (bounded only by
    AGENT_BROWSER_IDLE_TIMEOUT_MS): sessions opened from script files or
    unlisted wrappers, `default`, a `run_in_background` open, and a daemon
    that predates its `open`.

Performance: usually well under 1 s. Worst case inside main() is about 8 s
    (1.5 s `ps`, 2 s for both transcript reads, 3.5 s of closes, 1 s
    `session list`), leaving about 2 s of the registered 10 s timeout for
    interpreter startup, reading stdin and the log write (startup measured
    at well under 0.2 s).
"""

import datetime
import glob
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time

LOG_PATH = "~/.agentic/browser-reaper.log"
LOG_ROTATE_BYTES = 1024 * 1024
AB_DIR = "~/.agent-browser"
LOCAL_BIN = "~/.local/bin/agent-browser"
PS_CMD = ["/bin/ps", "-axo", "pid=,ppid=,etime=,command="]

PS_BUDGET_S = 1.5
SCAN_BUDGET_S = 2.0
CLOSE_BUDGET_S = 3.5
LIST_BUDGET_S = 1.0
SLACK_S = 2.0
MAX_OPEN_S = 600.0
MAX_SHELL_DEPTH = 2

SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
REDIR_RE = re.compile(r"^(\d*|&)(>>?|<<?)&?")
SEPARATORS = set(";&|()\n")
# Global flags of agent-browser 0.27.0 (`agent-browser --help`) that take a
# value, so the value is never mistaken for the subcommand.
VALUE_FLAGS = {
    "--profile", "--session-name", "--state", "--headers", "--executable-path",
    "--extension", "--init-script", "--enable", "--args", "--user-agent",
    "--proxy", "--proxy-bypass", "--device", "--screenshot-dir",
    "--screenshot-quality", "--screenshot-format", "--cdp", "--color-scheme",
    "--download-path", "--max-output", "--allowed-domains", "--action-policy",
    "--confirm-actions", "--engine", "--model", "--config", "-p", "--provider",
}
# "Boolean flags accept an optional true/false value" (agent-browser --help).
BOOL_VALUES = ("true", "false")
SHELLS = ("bash", "sh", "zsh", "dash")
SIMPLE_WRAPPERS = ("command", "exec", "nohup")
PROFILE_MARKERS = ("agent-browser-chrome-", "playwright_chromiumdev_profile-")
HANDLED_EVENTS = ("SubagentStop", "SessionEnd")

_state = {"event": None}


# ---------------------------------------------------------------------------
# Command extraction
# ---------------------------------------------------------------------------

def _tokenize(text):
    lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def split_segments(cmd):
    """Shell segments of cmd as token lists. Backslash-newline continuations
    are joined first. A command that does not tokenize as a whole (an
    unbalanced quote) is retried line by line, skipping the bad lines."""
    cmd = cmd.replace("\\\n", " ")
    try:
        chunks = [_tokenize(cmd)]
    except ValueError:
        chunks = []
        for line in cmd.splitlines():
            try:
                chunks.append(_tokenize(line))
            except ValueError:
                continue
    segments = []
    for tokens in chunks:
        segment = []
        join_next = False
        for tok in tokens:
            if join_next:
                segment[-1] += tok
                join_next = False
                continue
            if tok == "&" and segment and segment[-1][-1:] in (">", "<"):
                segment[-1] += tok
                join_next = True
                continue
            if tok and set(tok) <= SEPARATORS:
                if segment:
                    segments.append(segment)
                segment = []
            else:
                segment.append(tok)
        if segment:
            segments.append(segment)
    return segments


def _session_from_assign(tok):
    if tok.startswith("AGENT_BROWSER_SESSION="):
        return tok.split("=", 1)[1]
    return None


def _strip_wrappers(seg, i, env_session):
    """Advance i past leading assignments and allowlisted wrappers. Returns
    (i, env_session)."""
    while i < len(seg):
        tok = seg[i]
        base = os.path.basename(tok)
        if ENV_ASSIGN_RE.match(tok):
            env_session = _session_from_assign(tok) or env_session
            i += 1
        elif base == "env":
            i += 1
            while i < len(seg) and seg[i].startswith("-"):
                i += 2 if seg[i] in ("-u", "--unset", "-C", "--chdir") else 1
        elif base in SIMPLE_WRAPPERS:
            i += 1
        elif base == "time":
            i += 1
            while i < len(seg) and seg[i].startswith("-"):
                i += 1
        elif base == "timeout":
            i += 1
            while i < len(seg) and seg[i].startswith("-"):
                i += 2 if seg[i] in ("-s", "-k", "--signal", "--kill-after") else 1
            i += 1
        elif base in ("npx", "bunx"):
            i += 1
            while i < len(seg) and seg[i].startswith("-"):
                i += 2 if seg[i] in ("-p", "--package") else 1
        elif base == "pnpm" and i + 1 < len(seg) and seg[i + 1] in ("dlx", "exec"):
            i += 2
        else:
            break
    return i, env_session


def _is_agent_browser(tok):
    base = os.path.basename(tok)
    return base == "agent-browser" or base.startswith("agent-browser@")


def _shell_script(seg, i):
    """If seg[i] is a shell run with -c (alone or combined, as in -lc),
    return the script string, else None."""
    if os.path.basename(seg[i]) not in SHELLS:
        return None
    j = i + 1
    while j < len(seg) and seg[j].startswith("-"):
        flag = seg[j]
        if not flag.startswith("--") and "c" in flag[1:]:
            return seg[j + 1] if j + 1 < len(seg) else None
        j += 1
    return None


def _parse_open(args, session):
    """Return the session an `agent-browser <args>` call opens, or None."""
    subcommand = None
    j = 0
    while j < len(args):
        tok = args[j]
        nxt = args[j + 1] if j + 1 < len(args) else None
        if REDIR_RE.match(tok):
            if REDIR_RE.sub("", tok, count=1) == "" and nxt is not None:
                j += 1
        elif tok.startswith("--session="):
            session = tok.split("=", 1)[1]
        elif tok == "--session" and nxt is not None:
            session = nxt
            j += 1
        elif tok in VALUE_FLAGS:
            j += 1
        elif tok.startswith("-"):
            if nxt in BOOL_VALUES:
                j += 1
        elif subcommand is None:
            subcommand = tok
        j += 1
    if subcommand == "open" and session and SESSION_NAME_RE.match(session):
        return session
    return None


def opened_sessions(cmd, inherited=None, depth=0):
    """Session names this command OPENED: a segment whose program (after
    leading VAR=value assignments and allowlisted wrappers) is agent-browser
    and whose subcommand is `open`, naming a session via --session,
    --session=, AGENT_BROWSER_SESSION=, or an earlier `export
    AGENT_BROWSER_SESSION=` / bare assignment segment in the same command.
    A shell -c script is searched too, to depth 2. Mentions inside grep,
    echo, an unknown wrapper, or a non-open call never count."""
    found = set()
    default_session = inherited
    for seg in split_segments(cmd):
        if seg[0] == "export" or all(ENV_ASSIGN_RE.match(t) for t in seg):
            for tok in seg:
                default_session = _session_from_assign(tok) or default_session
            continue
        i, env_session = _strip_wrappers(seg, 0, default_session)
        if i >= len(seg):
            continue
        script = _shell_script(seg, i)
        if script is not None:
            if depth < MAX_SHELL_DEPTH:
                found |= opened_sessions(script, env_session, depth + 1)
            continue
        if not _is_agent_browser(seg[i]):
            continue
        name = _parse_open(seg[i + 1:], env_session)
        if name:
            found.add(name)
    found.discard("default")
    return found


# ---------------------------------------------------------------------------
# Transcript scan
# ---------------------------------------------------------------------------

def _parse_ts(value):
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    m = re.match(r"^(.*T\d\d:\d\d:\d\d)(\.\d+)?([+-]\d\d:\d\d)$", text)
    if not m:
        return None
    frac = (m.group(2) or ".0")[1:7].ljust(6, "0")
    try:
        dt = datetime.datetime.fromisoformat(m.group(1) + "." + frac + m.group(3))
    except ValueError:
        return None
    return dt.timestamp()


def candidates_from_transcript(path, deadline):
    """name -> [(t_lo, t_hi_or_None)] for every `open` in path's Bash
    tool_use entries. t_lo is the tool_use entry's timestamp, t_hi the
    timestamp of the entry carrying its tool_result (None when none was
    seen). On a deadline overrun the scan stops and windows with no
    tool_result are dropped."""
    pending = {}
    windows = {}
    overran = False
    if not path or not os.path.isfile(path):
        return {}
    with open(path, errors="replace") as f:
        for line in f:
            if time.monotonic() > deadline:
                overran = True
                break
            has_open = "agent-browser" in line and "tool_use" in line
            has_result = bool(pending) and "tool_use_id" in line and any(
                tid in line for tid in pending)
            if not has_open and not has_result:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            content = (entry.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            ts = _parse_ts(entry.get("timestamp"))
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "tool_use" and item.get("name") == "Bash":
                    cmd = (item.get("input") or {}).get("command") or ""
                    if "agent-browser" not in cmd or ts is None:
                        continue
                    names = opened_sessions(cmd)
                    if names:
                        tid = item.get("id") or ""
                        window = [ts, None]
                        for name in names:
                            windows.setdefault(name, []).append(window)
                        if tid:
                            pending[tid] = window
                elif item.get("type") == "tool_result":
                    window = pending.pop(item.get("tool_use_id") or "", None)
                    if window is not None and ts is not None:
                        window[1] = ts
    result = {}
    for name, wins in windows.items():
        kept = [(lo, hi) for lo, hi in wins if not (overran and hi is None)]
        if kept:
            result[name] = kept
    return result


def owned(cands, daemon_start, now, slack=SLACK_S):
    """Names whose live daemon started inside one of their open windows."""
    out = set()
    for name, wins in cands.items():
        if name == "default" or name not in daemon_start:
            continue
        start = daemon_start[name]
        for lo, hi in wins:
            upper = min(hi if hi is not None else now, lo + MAX_OPEN_S)
            if lo - slack <= start <= upper + slack:
                out.add(name)
                break
    return out


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------

def parse_etime(text):
    """ps etime `[[dd-]hh:]mm:ss` -> seconds, or None."""
    days = 0
    if "-" in text:
        d, text = text.split("-", 1)
        if not d.isdigit():
            return None
        days = int(d)
    parts = text.split(":")
    if not 2 <= len(parts) <= 3 or not all(p.isdigit() for p in parts):
        return None
    secs = 0
    for p in parts:
        secs = secs * 60 + int(p)
    return days * 86400 + secs


def ps_rows(timeout):
    """pid -> (ppid, etime_s, command) for every process."""
    out = subprocess.run(PS_CMD, capture_output=True, text=True,
                         timeout=timeout).stdout
    rows = {}
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        etime = parse_etime(parts[2])
        if etime is None:
            continue
        rows[int(parts[0])] = (int(parts[1]), etime, parts[3])
    return rows


def send_signal(pid, sig):
    os.kill(pid, sig)


def select_orphans(rows):
    """Orphaned automation Chrome main processes: no --type=, a temp
    automation profile, and a parent that is pid 1 or gone."""
    picked = []
    for pid, (ppid, _etime, cmd) in sorted(rows.items()):
        if "--type=" in cmd:
            continue
        m = re.search(r"--user-data-dir=(\S+)", cmd)
        if not m or not any(mark in m.group(1) for mark in PROFILE_MARKERS):
            continue
        if ppid != 1 and ppid in rows:
            continue
        picked.append(pid)
    return picked


def daemon_states(ab_dir, rows, now):
    """(name -> daemon start epoch for live daemons, has_dead_pid_file)."""
    starts = {}
    dead = False
    for path in glob.glob(os.path.join(ab_dir, "*.pid")):
        name = os.path.basename(path)[:-4]
        try:
            with open(path) as f:
                pid = int(f.read().strip())
        except (OSError, ValueError):
            dead = True
            continue
        row = rows.get(pid)
        if row is None:
            dead = True
            continue
        starts[name] = now - row[1]
    return starts, dead


def find_binary():
    found = shutil.which("agent-browser")
    if found:
        return found
    local = os.path.expanduser(LOCAL_BIN)
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return local
    return None


def run_bounded(argvs, budget):
    """Run each argv in its own process group, all sharing one deadline;
    SIGKILL the group of any still running at the deadline. Returns
    [(argv, rc_or_None)]."""
    deadline = time.monotonic() + budget
    procs = []
    for argv in argvs:
        try:
            procs.append((argv, subprocess.Popen(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)))
        except OSError:
            procs.append((argv, None))
    results = []
    for argv, proc in procs:
        if proc is None:
            results.append((argv, None))
            continue
        try:
            proc.wait(timeout=max(0.0, deadline - time.monotonic()))
            results.append((argv, proc.returncode))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            proc.wait()
            results.append((argv, None))
    return results


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

def write_log(line):
    path = os.path.expanduser(LOG_PATH)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            if os.path.getsize(path) > LOG_ROTATE_BYTES:
                os.replace(path, path + ".1")
        except OSError:
            pass
        with open(path, "a") as f:
            f.write("%s pid=%d %s\n" % (
                datetime.datetime.now(datetime.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"), os.getpid(), line))
    except OSError:
        pass


def _fmt(names):
    return "[" + ",".join(sorted(names)) + "]"


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def _transcripts(payload, event):
    if event == "SubagentStop":
        path = payload.get("agent_transcript_path")
        return [path] if isinstance(path, str) and path else []
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not path:
        return []
    paths = [path]
    if path.endswith(".jsonl"):
        paths += sorted(glob.glob(os.path.join(path[:-6], "subagents", "agent-*.jsonl")))
    return paths


def own_pending_work(payload, paths, deadline):
    """(ids of in-flight work this agent started, count of other in-flight
    work). `background_tasks` and `session_crons` are session-wide and list
    the ending subagent itself, so an entry counts as this agent's own only
    when its id is not the agent's and appears in the agent's own
    transcript (the tool_result that launched it names it). An entry with
    no usable id counts as own, and so does a read that overruns
    `deadline` (`scan-deadline`); both keep the browser."""
    agent_id = payload.get("agent_id")
    entries = []
    for key in ("background_tasks", "session_crons"):
        value = payload.get(key) or []
        entries.extend(value if isinstance(value, list) else [value])
    ids, own = [], set()
    for entry in entries:
        tid = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(tid, str) or not tid:
            own.add("unidentified")
        elif tid != agent_id:
            ids.append(tid)
    if ids:
        chunks = []
        for path in paths:
            try:
                with open(path, errors="replace") as f:
                    while True:
                        if time.monotonic() > deadline:
                            own.add("scan-deadline")
                            return own, 0
                        chunk = f.read(1 << 20)
                        if not chunk:
                            break
                        chunks.append(chunk)
            except OSError:
                continue
        text = "".join(chunks)
        own.update(tid for tid in ids if tid in text)
    return own, len([tid for tid in ids if tid not in own])


def main():
    started = time.monotonic()
    raw = sys.stdin.read()
    if not raw.strip():
        return
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        return
    event = payload.get("hook_event_name")
    if event not in HANDLED_EVENTS:
        return
    _state["event"] = event
    head = "event=%s" % event
    if event == "SubagentStop":
        head += " agent=%s" % payload.get("agent_id", "?")
    else:
        head += " reason=%s" % payload.get("reason", "?")

    if os.environ.get("AE_BROWSER_REAPER_DISABLE") == "1":
        write_log(head + " verdict=disabled")
        return

    scan_deadline = time.monotonic() + SCAN_BUDGET_S
    deferred, waits_note = "", ""
    if event == "SubagentStop":
        own, others = own_pending_work(payload, _transcripts(payload, event), scan_deadline)
        if own:
            deferred = " own_pending=%s" % _fmt(own)
        if others:
            waits_note = " others_in_flight=%d" % others

    rows = ps_rows(timeout=PS_BUDGET_S)
    now = time.time()
    ab_dir = os.path.expanduser(AB_DIR)
    starts, dead_pid_file = daemon_states(ab_dir, rows, now)
    ab = find_binary()

    cands = {}
    closed, skipped, truncated = set(), [], False
    if not deferred:
        for path in _transcripts(payload, event):
            if time.monotonic() > scan_deadline:
                truncated = True
                break
            for name, wins in candidates_from_transcript(path, scan_deadline).items():
                cands.setdefault(name, []).extend(wins)
        mine = owned(cands, starts, now)
        for name in sorted(set(cands) - mine):
            if name not in starts:
                skipped.append("%s:no-live-daemon" % name)
            else:
                skipped.append("%s:daemon-start-outside-window" % name)
        if mine and ab:
            results = run_bounded(
                [[ab, "close", "--session", n] for n in sorted(mine)], CLOSE_BUDGET_S)
            for argv, rc in results:
                if rc == 0:
                    closed.add(argv[3])
                else:
                    skipped.append("%s:close-%s" % (argv[3], "timeout" if rc is None else "rc%d" % rc))
        elif mine:
            skipped.extend("%s:no-binary" % n for n in sorted(mine))

    killed = []
    for pid in select_orphans(rows):
        try:
            send_signal(pid, signal.SIGTERM)
            killed.append(pid)
        except OSError:
            pass

    pruned = False
    if ab and dead_pid_file:
        run_bounded([[ab, "session", "list"]], LIST_BUDGET_S)
        pruned = True

    write_log("%s verdict=%s%s%s candidates=%s closed=%s skipped=%s orphans_killed=%d%s "
              "pruned=%s%s elapsed=%.2fs" % (
                  head, "deferred" if deferred else "ran", deferred, waits_note, _fmt(cands),
                  _fmt(closed), "[" + ",".join(skipped) + "]", len(killed),
                  " orphan_pids=%s" % killed if killed else "", pruned,
                  " scan_truncated=True" if truncated else "",
                  time.monotonic() - started))


def _entry():
    try:
        main()
    except Exception as exc:  # the hook must never fail its caller
        if _state["event"]:
            write_log("event=%s verdict=fatal error=%r" % (_state["event"], exc))
    sys.exit(0)


if __name__ == "__main__":
    _entry()
