#!/usr/bin/env python3
"""
Purpose: Claude Code SessionEnd hook that reaps agent-launched Chrome
         browsers still running after the session that launched them ends.
         Two browser paths are covered, both by process OWNERSHIP rather
         than by name matching:

           (MCP path) a browser launched by the `chrome-devtools-mcp`
             server, which tears its browser down only when the server
             exits cleanly - a SIGKILLed server, or the 5s
             `process.exit(0)` backstop in chrome-devtools-mcp-main.js
             that skips teardown, leaves a headed window on the desktop
             forever.
           (CLI path) a `Google Chrome for Testing` browser whose
             `agent-browser` daemon is already gone.

         THE SELECTOR, AND WHY IT IS SHAPED THIS WAY. An earlier draft of
         this unit keyed on `--remote-debugging-pipe` plus "no live
         chrome-devtools-mcp ancestor" - i.e. it tested
         NOT-owned-by-the-MCP, a complement with no positive ownership
         evidence in it. `--remote-debugging-pipe` is a puppeteer
         transport marker, not an MCP marker: measured live on the
         development host, four pipe-flag browser mains coexisted, each
         with a live parent - two `marp --preview` (this repo's own slide
         tooling), one `playwright/driver/node`, and one
         `chrome-devtools-mcp`. With the MCP dead, no row remains to test
         against, so that selector would have SIGKILLed the operator's
         live slide previews at every session end.

         The corrected selector requires a POSITIVE fingerprint the
         browser carries in its OWN argv, which therefore survives its
         server's death:

           Conjunct A - the row's OWN argv0 is a Chrome binary, matched
             by exact basename against a known Chrome executable name,
             AND argv contains
             `--user-data-dir=<HOME>/.cache/chrome-devtools-mcp/`
             This is the MCP's own profile root (BrowserManager.js's
             non-isolated default, and pinned explicitly by the
             installer). `marp` uses a `marp-cli-*` temp dir, Playwright
             its own `playwright_*` temp dir, and `agent-browser` an
             `agent-browser-chrome-*` temp dir, so none of them can
             match. The operator's own Chrome main process carries NO
             `--user-data-dir` at all (measured), so no separate
             operator-profile guard is needed - A excludes it
             structurally.
             The argv0 half is not decoration, and the match must be an
             EXACT basename rather than a substring. This is the half
             that carries the safety property: the profile path is a
             string any process can name, so a row's non-browser identity
             has to be established by its own executed image, never by
             what its arguments happen to contain. Measured on the
             development host: the `chrome-devtools-mcp` server's own
             argv0 CONTAINS `chrome`, so a substring test made every MCP
             server process on the machine - and every `npm exec`
             wrapper carrying its name - a kill target the moment its
             argv also carried a profile path. Also measured while
             developing this hook: a
             `ps ... | grep -- '--user-data-dir=<the fingerprint>'`
             pipeline put the fingerprint string into the argv of its own
             `zsh -c` wrappers and its `ugrep` process. Both families
             carry the fingerprint, and both are excluded by argv0 alone.
             The executable path is read as everything before the first
             ` --` (which is how the spaces inside
             `.../Google Chrome for Testing` survive); `_executable_name`
             then resolves argv0 out of that region.
           Conjunct B - argv does NOT contain `--type=`. Chrome passes
             launch flags down to helpers/renderers, so without this the
             selector would match the whole browser rather than its root.
             The ratio is not a fixed figure: measured on the same live
             MCP browser it ran 1 main to 17 helpers (six consecutive
             snapshots, 2026-09-23) and 1 main to 18 earlier the same
             session, tracking how many renderers Chrome currently has.
             What is stable is that every helper carries the flags and
             only the root does not.
           Arm (i)  - A and B hold, and the browser has NO live
             `chrome-devtools-mcp` ancestor: a genuine orphan.
           Arm (ii) - A and B hold, and the live MCP ancestor is inside
             THIS session's own process tree, bounded at this session's
             harness process. Covers the case where the MCP process is
             still alive (or its `npm exec` wrapper is) while the browser
             is being abandoned: at SessionEnd, this session's own
             browsers die regardless.
           Arm (iii) - an `agent-browser` Chrome main (argv carries a
             `--user-data-dir=` whose path contains
             `agent-browser-chrome-`, no `--type=`) whose owning
             `agent-browser` daemon is already gone. NO `agent-browser`
             CLI command is ever run from here: the CLI's sessions are
             machine-global and `close --all` closes every active session
             on the machine, so any CLI-driven close is a cross-run
             hazard. Only a browser whose daemon is provably dead is
             selected.

         R4 SAFETY ARGUMENT (a browser belonging to ANOTHER live session
         must never be selected). Arm (i) cannot reach one: a live
         session's browser always has a live MCP ancestor. Arm (iii)
         cannot reach one: a live agent-browser browser always has a live
         daemon parent. Arm (ii) is the one that needs an argument, and
         the naive form of it is WRONG: measured live on this host, two
         concurrent Claude sessions had the shapes (each chain read from
         the process itself upward)

             this session:  hook -> "zsh -c ..." -> claude(48684) ->
                            "-zsh" -> "login ..." -> Terminal(640)
             other session: chrome-devtools-mcp -> "npm exec ..." ->
                            claude(76072) -> "-zsh" -> "login ..." ->
                            Terminal(640)

         so intersecting their two full ancestor chains matches on
         Terminal(640) - a shared ancestor ABOVE both harnesses. An
         arm (ii) built on that intersection would have reaped the other
         session's live browser. This module therefore bounds the walk at
         THIS session's harness: `_resolve_own_chain()` walks up from the
         hook's own pid only through wrapper SHELLS and stops at the
         first non-shell ancestor (the harness), never continuing into
         the terminal/launchd region both sessions share. Verified
         against the live table: the other session's MCP browser is not
         selected.

Public API: none (CLI hook). Invoked by the Claude Code SessionEnd hook
            with the hook JSON payload on stdin (fd 0):
            { session_id, transcript_path, cwd, hook_event_name:
              "SessionEnd", reason }. Not imported by any module; the
            pure functions below (`parse_ps_table`, `select_targets`,
            `classify_rows`) are imported by this hook's own regression
            test via importlib.

Upstream deps: Python 3 stdlib only (json, os, select, signal,
               subprocess, sys) plus one local module loaded lazily by
               path: hooks/lib/enforcement_log.py (the repo's sole
               fire-log writer, and the only code that knows the
               worktree-local-to-primary-checkout redirection rule - a
               hand-written JSONL line would land in a discarded
               worktree-local copy). Exactly one external command:
               `ps -Aww -o pid=,ppid=,command=`, run ONCE per
               invocation with a timeout. Never a `type=` ps keyword:
               measured on macOS, `ps: type: keyword not found` and the
               command still prints a table MISSING that column, so a
               parser reads shifted fields.

Downstream consumers: Claude Code SessionEnd hook (the second entry in
                      the `SessionEnd` matcher-"*" block wired by
                      .claude/install.sh; the first is
                      session-end-wrap.js). No code imports this file.
                      Registered with the guarded command form
                      (`test -f ... && python3 ... || exit 0`) because a
                      bare `python3 <missing path>` exits 2, which is the
                      BLOCKING code on SessionEnd. The fire record is
                      every-verdict: one line per run, including a run
                      that reaped nothing, so the retirement question
                      ("zero reaps across N sessions in which the hook
                      provably ran") is answerable by measurement rather
                      than by silence.

Failure modes: Fully fail-closed, exit 0 on EVERY path. A non-zero exit
               at SessionEnd is the blocking code, so a cleanup hook must
               never be able to turn a session's end into a failure. Every
               degradation - an unparseable or absent payload, a `ps` that
               is missing/errors/times out, a process table that is empty
               (including one whose every line failed to parse), an
               unresolvable own-process chain, a failed kill, an
               unexpected exception anywhere in run() - results in NO kill
               and exit 0. The hook reads no config file and holds no kill
               switch: it is a once-per-session cleanup, not a policy
               guard, and a kill switch would add a second silence that
               the fire record exists to remove. It also never runs an
               `agent-browser` command of any kind.

               Known residuals, stated rather than hidden. First, the
               selector takes ONE snapshot and never re-reads it, so a pid
               reused between the snapshot and the kill could in principle
               be killed. The window is the lifetime of one `ps` call on a
               box that is not recycling pids at that rate, and one
               snapshot is a hard requirement (no polling, no retry)
               because a reaper that re-runs `ps` in a loop at session
               shutdown is a bigger risk than the one it closes. Second, a
               NON-EMPTY but incomplete table is accepted and treated as
               the whole process list: `ps` either answers completely or
               exits non-zero, so the window is narrow, but the hook
               cannot detect a truncated table from inside - on one, an
               MCP ancestor whose row is missing reads as a dead owner,
               and an `agent-browser` daemon whose row is missing reads as
               `ARM_ORPHANED_CLI`. Nothing is selected unless the row
               already carries a positive browser fingerprint of its own,
               so what such a table can cost is a browser-shaped process,
               never an arbitrary one.

Performance: one `ps` (~10 ms) plus one bounded stdin read (<= 0.5 s
             worst case when the harness never closes stdin). No polling,
             no sleeps, no retries. The fire-log module is loaded only on
             a SessionEnd invocation that reached a verdict.
"""

from __future__ import annotations

import json
import os
import re
import select
import signal
import subprocess
import sys
import time


HOOK_NAME = "session-end-reap-browsers"

# The single, mandated process-table command. `-Aww` keeps the full argv
# (a truncated command line would drop the `--user-data-dir` fingerprint),
# and the `=`-suffixed field list suppresses the header so every line is
# data. Never add `type=` to this list - see the docstring.
PS_COMMAND = ["ps", "-Aww", "-o", "pid=,ppid=,command="]
PS_TIMEOUT_SECONDS = 3
STDIN_TIMEOUT_SECONDS = 0.5
STDIN_MAX_BYTES = 262144
MAX_ANCESTOR_HOPS = 64

# pid 0 is the kernel/swapper and pid 1 is launchd/init. Neither is ever an
# ownership signal: every reparented process ends up at pid 1, so treating
# it as a live ancestor would make every orphan look "owned".
INIT_PIDS = frozenset((0, 1))

# Wrapper shells only - deliberately NOT interpreters. The walk in
# `_resolve_own_chain()` climbs past these to reach the harness process and
# stops at the first non-member. An interpreter is excluded from this set on
# purpose: a Node/Python-based harness process is itself the boundary, and
# skipping past it would walk into the terminal region two sessions share.
SHELL_BASENAMES = frozenset((
    "sh", "bash", "zsh", "dash", "ash", "ksh", "csh", "tcsh", "fish",
))

# The basenames a real Chrome-family browser's OWN argv0 resolves to. Positive
# identity, never a substring: `chrome-devtools-mcp` contains `chrome` and is
# the MCP server's argv0, so a substring test cannot tell a browser from the
# server that spawned it. Covers the measured macOS shapes (`Google Chrome`,
# `Google Chrome for Testing`), the Linux ones (`/opt/google/chrome/chrome`,
# `/usr/bin/google-chrome`), Playwright's `Chromium` and `headless_shell`, and
# `chrome-headless-shell`. Helpers are deliberately absent: `Google Chrome
# Helper (Renderer)`, `chrome_crashpad_handler` and the other per-process
# children are not browsers, and Chrome already marks them with `--type=`.
CHROME_BINARY_NAMES = frozenset((
    "Google Chrome",
    "Google Chrome Beta",
    "Google Chrome Canary",
    "Google Chrome Dev",
    "Google Chrome for Testing",
    "Chromium",
    "chrome",
    "chrome-headless-shell",
    "chromium",
    "chromium-browser",
    "chromium-headless-shell",
    "google-chrome",
    "google-chrome-stable",
    "headless_shell",
))

MCP_SERVER_MARKER = "chrome-devtools-mcp"
MCP_PROFILE_RELATIVE = os.path.join(".cache", "chrome-devtools-mcp")
AGENT_BROWSER_PROFILE_MARKER = "agent-browser-chrome-"
USER_DATA_DIR_FLAG = "--user-data-dir="
BROWSER_TYPE_FLAG = "--type="

ARM_ORPHANED_MCP = "i"
ARM_OWN_SESSION_MCP = "ii"
ARM_ORPHANED_CLI = "iii"


class Row(object):
    """One parsed `ps` line: pid, ppid, and the full command string."""

    __slots__ = ("pid", "ppid", "command")

    def __init__(self, pid, ppid, command):
        self.pid = pid
        self.ppid = ppid
        self.command = command

    def __repr__(self):  # pragma: no cover - diagnostics only
        return "Row(pid=%d, ppid=%d)" % (self.pid, self.ppid)


class Verdict(object):
    """One row's classification. `arm` is "" when the row is not selected."""

    __slots__ = ("row", "arm", "note")

    def __init__(self, row, arm, note):
        self.row = row
        self.arm = arm
        self.note = note

    def __repr__(self):  # pragma: no cover - diagnostics only
        return "Verdict(pid=%d, arm=%r)" % (self.row.pid, self.arm)


# ---------------------------------------------------------------------------
# Process table
# ---------------------------------------------------------------------------

def parse_ps_table(text):
    """Parse `ps -Aww -o pid=,ppid=,command=` output into Row objects.

    Never raises: an empty, truncated, or malformed line is skipped rather
    than aborting the parse, so a degraded table yields fewer rows instead
    of a traceback. Returns [] for empty/None input.
    """
    rows = []
    if not text:
        return rows
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except (TypeError, ValueError):
            continue
        rows.append(Row(pid, ppid, parts[2]))
    return rows


def snapshot_process_table():
    """Take the hook's single `ps` snapshot.

    Returns (rows, note). `rows` is [] and `note` is a short fixed-vocabulary
    label on any failure, so the caller can log WHY it did nothing without
    ever raising.
    """
    try:
        proc = subprocess.run(
            PS_COMMAND,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return [], "ps_timeout"
    except Exception as exc:
        return [], "ps_unavailable_%s" % type(exc).__name__
    if proc.returncode != 0:
        # A non-zero ps can still print a degraded table (that is exactly
        # what an unsupported `type=` keyword does on macOS). Refuse the
        # whole snapshot rather than trusting shifted fields.
        return [], "ps_exit_%d" % proc.returncode
    try:
        text = proc.stdout.decode("utf-8", "replace")
    except Exception:
        return [], "ps_undecodable"
    rows = parse_ps_table(text)
    if not rows:
        return [], "ps_empty_table"
    return rows, ""


def _command_map(rows):
    return dict((row.pid, row.command) for row in rows)


def _ppid_map(rows):
    return dict((row.pid, row.ppid) for row in rows)


def ancestor_pids(pid, ppid_map, max_hops=MAX_ANCESTOR_HOPS):
    """STRICT ancestors of *pid* (its parent first), excluding *pid* itself.

    Excluding the starting pid is load-bearing: an MCP browser's own argv
    contains the MCP profile path, which itself contains the string
    `chrome-devtools-mcp`, so a chain that included the browser would let it
    match itself as its own MCP ancestor. Walks stop at pid 0/1, at a
    repeated pid (a cycle), and at max_hops.
    """
    chain = []
    seen = set((pid,))
    current = ppid_map.get(pid)
    hops = 0
    while (current is not None and current not in INIT_PIDS
           and current not in seen and hops < max_hops):
        chain.append(current)
        seen.add(current)
        current = ppid_map.get(current)
        hops += 1
    return chain


def _chain_including(pid, ppid_map):
    """*pid* followed by its strict ancestors."""
    return [pid] + ancestor_pids(pid, ppid_map)


def _basename(command):
    """argv0's basename, with any leading '-' stripped (login shells)."""
    tokens = command.strip().split()
    if not tokens:
        return ""
    token = tokens[0]
    slash = token.rfind("/")
    if slash != -1:
        token = token[slash + 1:]
    return token.lstrip("-")


def _is_shell_wrapper(command):
    """True for a shell process (with or without an explicit path)."""
    return _basename(command) in SHELL_BASENAMES


def resolve_own_chain(self_pid, ppid_map, command_map):
    """The pids that identify THIS session, bounded at its harness process.

    Starts at *self_pid* and walks up through wrapper shells, stopping at -
    and INCLUDING - the first ancestor that is not a shell. That ancestor is
    the harness process, and stopping there is what keeps a shared terminal
    (an ancestor of two concurrent sessions) out of the set. Returns just
    [self_pid] when nothing above it resolves, which makes arm (ii)
    unreachable rather than over-broad.
    """
    chain = [self_pid]
    current = ppid_map.get(self_pid)
    hops = 0
    while (current is not None and current not in INIT_PIDS
           and hops < MAX_ANCESTOR_HOPS):
        chain.append(current)
        if not _is_shell_wrapper(command_map.get(current, "")):
            break
        current = ppid_map.get(current)
        hops += 1
    return chain


# ---------------------------------------------------------------------------
# The selector. Each conjunct lives in its own small function, and each is
# bracketed by MUTATION-ANCHOR comments: hooks/tests/test-session-end-reap-
# browsers.py rewrites one anchored block at a time in memory and asserts the
# fixture reddens. Removing a conjunct must never be a silent edit.
# ---------------------------------------------------------------------------

def _executable_region(command):
    """Everything before the command's first ` --` flag.

    Anchored on the first flag rather than on whitespace because a Chrome
    executable path contains spaces (`.../MacOS/Google Chrome for Testing`),
    and a plain `split()[0]` truncates it to the `Google` segment.
    """
    return re.split(r"\s--", command, maxsplit=1)[0]


def _executable_name(command):
    """argv0's basename, or "" for a command with no executable token.

    argv0 cannot be taken as the region's first whitespace-separated token,
    because a Chrome executable path carries spaces. It is resolved by where
    the region's ABSOLUTE paths start instead: exactly one, at the region's
    own start, means the whole region is argv0 (the space-bearing Chrome
    path); anything else means argv0 is only the first token, because that
    first token is a launcher (`node <script>`, `npm exec <package>`,
    `sh -c "<...>"`) or an absolute launcher path that names a Chrome path
    as its own ARGUMENT.

    Reading only the region keeps the arguments out of argv0 entirely, so a
    process whose arguments merely mention a Chrome path is never mistaken
    for one.
    """
    region = _executable_region(command).strip()
    if not region:
        return ""
    tokens = region.split()
    path_starts = [i for i, token in enumerate(tokens) if token.startswith("/")]
    if len(path_starts) == 1 and path_starts[0] == 0:
        return region.rsplit("/", 1)[-1]
    if not path_starts:
        # No absolute path anywhere: the region is either a bare Chrome name
        # that carries spaces, or a bare launcher name.
        return region if region in CHROME_BINARY_NAMES else tokens[0]
    return tokens[0]


def _is_chrome_binary(command):
    """Conjunct A, part 1: the row's OWN executed image is a Chrome browser.

    An exact basename match against CHROME_BINARY_NAMES, never a substring -
    see the module docstring for the `chrome-devtools-mcp` argv0 that a
    substring test cannot distinguish from a browser.
    """
    # MUTATION-ANCHOR: chrome_binary
    return _executable_name(command) in CHROME_BINARY_NAMES
    # END-MUTATION-ANCHOR: chrome_binary


def _matches_mcp_profile(command, mcp_profile_root):
    """Conjunct A, part 2: the positive MCP fingerprint, in the BROWSER's
    own argv (so it survives the server's death).

    A path-prefix test, and safe to keep as one: it is only ever reached for
    a row that already passed part 1, so the fingerprint selects WHICH Chrome
    is reaped, never WHETHER a row is a browser. A process that names this
    profile path without being a Chrome binary - the MCP server itself, an
    `npm exec` wrapper, a `grep` whose pattern is the path - is rejected by
    part 1 and never consulted here.
    """
    # MUTATION-ANCHOR: conjunct_a
    return (USER_DATA_DIR_FLAG + mcp_profile_root + "/") in command
    # END-MUTATION-ANCHOR: conjunct_a


def _is_browser_main(command):
    """Conjunct B: a browser MAIN process, not one of its helpers."""
    # MUTATION-ANCHOR: conjunct_b
    return BROWSER_TYPE_FLAG not in command
    # END-MUTATION-ANCHOR: conjunct_b


def _matches_agent_browser_profile(command):
    """Arm (iii)'s fingerprint: an agent-browser temporary profile."""
    return (USER_DATA_DIR_FLAG in command
            and AGENT_BROWSER_PROFILE_MARKER in command)


def _own_chain_matches(pid, ppid_map, own_chain):
    """True when *pid* or any of its ancestors is in this session's chain."""
    own = set(own_chain)
    for candidate in _chain_including(pid, ppid_map):
        if candidate in own:
            return True
    return False


def _arm_ii(pid, ppid_map, own_chain):
    """Arm (ii): the owner is inside THIS session's own process tree."""
    # MUTATION-ANCHOR: arm_ii
    return _own_chain_matches(pid, ppid_map, own_chain)
    # END-MUTATION-ANCHOR: arm_ii


def _mcp_arm(pid, command_map, ppid_map, own_chain):
    """Return arm "i", arm "ii", or "" for an MCP-fingerprint browser main."""
    # MUTATION-ANCHOR: ancestor_test
    live_owners = [
        candidate for candidate in ancestor_pids(pid, ppid_map)
        if MCP_SERVER_MARKER in command_map.get(candidate, "")
    ]
    if not live_owners:
        return ARM_ORPHANED_MCP
    for owner in live_owners:
        if _arm_ii(owner, ppid_map, own_chain):
            return ARM_OWN_SESSION_MCP
    return ""
    # END-MUTATION-ANCHOR: ancestor_test


def _agent_browser_arm(pid, ppid, command_map):
    """Return arm "iii" for an agent-browser browser whose daemon is gone.

    "Gone" means exactly one of: the parent is pid 0/1 (reparented to
    launchd), or the parent pid no longer resolves in the snapshot. A parent
    that resolves to a live process is treated as NOT provably gone, with no
    exception - and in particular there is no "unless the parent is
    recognisably an agent-browser daemon" branch, because a parent that is
    recognisably an agent-browser daemon IS the live daemon, and selecting
    its browser would kill a browser that is still in use. The ambiguous
    case (a reused pid, or an unexpected launcher) fails closed rather than
    killing a live browser. This hook never invokes the agent-browser CLI.
    """
    if ppid in INIT_PIDS:
        return ARM_ORPHANED_CLI
    owner_command = command_map.get(ppid)
    if owner_command is None:
        return ARM_ORPHANED_CLI
    return ""


def classify_rows(rows, mcp_profile_root, own_chain):
    """Classify every row. Returns a list of Verdict, selected or not."""
    command_map = _command_map(rows)
    ppid_map = _ppid_map(rows)
    verdicts = []
    for row in rows:
        arm = ""
        note = ""
        if not _is_browser_main(row.command):
            note = "browser_helper_process"
        elif not _is_chrome_binary(row.command):
            note = "not_a_chrome_executable"
        elif _matches_mcp_profile(row.command, mcp_profile_root):
            arm = _mcp_arm(row.pid, command_map, ppid_map, own_chain)
            note = "mcp_browser" if arm else "mcp_browser_not_owned_by_this_session"
        elif _matches_agent_browser_profile(row.command):
            arm = _agent_browser_arm(row.pid, row.ppid, command_map)
            note = "agent_browser_orphan" if arm else "agent_browser_owner_alive_or_unproven"
        else:
            note = "no_agent_browser_fingerprint"
        verdicts.append(Verdict(row, arm, note))
    return verdicts


def select_targets(rows, mcp_profile_root, own_chain):
    """The pids this run would reap, as [(pid, arm), ...]."""
    return [
        (verdict.row.pid, verdict.arm)
        for verdict in classify_rows(rows, mcp_profile_root, own_chain)
        if verdict.arm
    ]


def mcp_profile_root(home=None):
    """`<HOME>/.cache/chrome-devtools-mcp`, forward-slashed.

    Resolved at runtime, never hardcoded. Chrome argv uses forward slashes
    on every platform this hook runs on, so the separator is normalised -
    the trailing "/" added by Conjunct A is what keeps a lookalike sibling
    directory (`.cache/chrome-devtools-mcp-evil`) from matching.
    """
    if home is None:
        home = os.path.expanduser("~")
    return os.path.join(home, MCP_PROFILE_RELATIVE).replace(os.sep, "/")


# ---------------------------------------------------------------------------
# stdin / logging / reaping
# ---------------------------------------------------------------------------

def _read_stdin(timeout_seconds=STDIN_TIMEOUT_SECONDS,
                max_bytes=STDIN_MAX_BYTES):
    """Bounded stdin read. Never blocks past *timeout_seconds*.

    `select()` bounds the wait and each read is a SINGLE `os.read()` syscall
    - never a buffered `read(n)`/`readline()`, which loops internally and can
    block past the select result. Reads stop at EOF, at the byte cap, or at
    the deadline. Returns "" for every failure mode.
    """
    try:
        fd = sys.stdin.fileno()
    except Exception:
        return ""
    chunks = []
    total = 0
    deadline = time.time() + timeout_seconds
    while total < max_bytes:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            ready = select.select([fd], [], [], remaining)[0]
        except Exception:
            break
        if not ready:
            break
        try:
            chunk = os.read(fd, min(65536, max_bytes - total))
        except Exception:
            break
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    try:
        return b"".join(chunks).decode("utf-8", "replace")
    except Exception:
        return ""


def read_payload(text=None):
    """Parse the hook payload. Returns {} unless it is a JSON object."""
    if text is None:
        text = _read_stdin()
    try:
        data = json.loads(text)
    except Exception:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _load_log_fire():
    """Load hooks/lib/enforcement_log.py::log_fire by path, lazily.

    Loaded inside the logging branch (never at module scope) so the common
    no-verdict exit path never compiles it. The lib is the repo's sole
    fire-log writer and is the only code that redirects a worktree-local
    write to the primary checkout; a hand-written JSONL line here would land
    somewhere no consumer reads.
    """
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    module_path = os.path.join(here, "lib", "enforcement_log.py")
    spec = importlib.util.spec_from_file_location("enforcement_log", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.log_fire


def _reap(pid):
    """SIGKILL one selected pid. Returns True only if the signal was sent."""
    try:
        os.kill(pid, signal.SIGKILL)
        return True
    except Exception:
        return False


def run(payload):
    """Evaluate the process table. Returns (decision, reason, detail).

    Never raises and never kills anything outside the selector's output.
    `detail` carries only small integers and fixed-vocabulary labels, per
    enforcement_log's contract for structured discriminators.
    """
    rows, note = snapshot_process_table()
    if not rows:
        return (
            "allow",
            "no process table (%s) - nothing evaluated" % (note or "empty"),
            {"table_rows": 0, "selected": 0, "reaped": 0, "ps_note": note or "empty"},
        )

    own_chain = resolve_own_chain(os.getpid(), _ppid_map(rows), _command_map(rows))
    targets = select_targets(rows, mcp_profile_root(), own_chain)

    reaped_arms = {}
    failed = 0
    for pid, arm in targets:
        if _reap(pid):
            reaped_arms[arm] = reaped_arms.get(arm, 0) + 1
        else:
            failed += 1

    detail = {
        "table_rows": len(rows),
        "selected": len(targets),
        "reaped": sum(reaped_arms.values()),
        "arms": sorted(reaped_arms.keys()),
        "arm_counts": reaped_arms,
        "kill_failures": failed,
    }
    if reaped_arms:
        return (
            "reap",
            "reaped %d orphaned agent browser(s): arms=%s"
            % (sum(reaped_arms.values()), ",".join(sorted(reaped_arms.keys()))),
            detail,
        )
    if targets:
        return (
            "allow",
            "selected %d browser(s) but no kill succeeded" % len(targets),
            detail,
        )
    return (
        "allow",
        "no orphaned agent browser in a %d-row process table" % len(rows),
        detail,
    )


def main(argv=None):
    """CLI entry point. Returns 0 on every path - never any other code."""
    payload = {}
    try:
        payload = read_payload()
    except Exception:
        payload = {}

    # Only a genuine SessionEnd invocation is evaluated or logged. A
    # non-SessionEnd or unparseable payload (including the empty stdin a
    # smoke-test harness passes) exits silently: logging it would write real
    # fire-log rows for invocations the guard never evaluated.
    if payload.get("hook_event_name") != "SessionEnd":
        return 0

    try:
        decision, reason, detail = run(payload)
    except Exception as exc:
        decision = "allow"
        reason = "internal error (%s) - nothing reaped" % type(exc).__name__
        detail = {"error": type(exc).__name__}

    try:
        log_fire = _load_log_fire()
        log_fire(payload, HOOK_NAME, decision, reason, detail=detail)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
