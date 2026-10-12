#!/usr/bin/env python3
"""
Purpose: SessionStart hook that delivers a repo's root MEMORY.md to the main
         session only. A repo opts in by replacing the `@MEMORY.md` import in
         its root CLAUDE.md with the MARKER line: an @-import loads the file
         into every subagent too, while SessionStart additionalContext
         reaches the main session alone, at startup, resume, compact and
         clear.

Catch (failure prevented): the conductor silently losing MEMORY.md once the
       `@MEMORY.md` import is removed from root CLAUDE.md.

Retirement: delete this hook, its .claude/install.sh registration, its
            .claude/uninstall.sh removal, its bin/ds-doctor
            MANAGED_HOOK_BASENAMES entry and its docs rows once Claude Code
            ships a main-session-only import or a per-agent CLAUDE.md
            exclusion.

Public API: python3 hooks/session-start-memory.py
            (reads the SessionStart JSON payload on stdin; prints one JSON
             object on stdout; always exits 0.)
            MARKER - the single source of the opt-in marker literal.
            CAP    - the additionalContext budget, measured as
                     len(json.dumps(ctx, ensure_ascii=True)).
            READ_BUDGET - the largest unshown remainder, in bytes, still
                     directed to be Read in full.

Behavior:
    Phase A: root = `git -C <cwd> rev-parse --show-toplevel`, else cwd.
        Prints `{}` when root CLAUDE.md has no line equal to MARKER after
        strip(), or on any exception.
    Phase B (marker confirmed): prints `{}` when CLAUDE.md,
        .claude/CLAUDE.md or CLAUDE.local.md under root still carries a
        stripped `@MEMORY.md` / `@./MEMORY.md` line (the import already
        delivers it, to subagents too), or when root/MEMORY.md is absent.
        Otherwise emits hookSpecificOutput.additionalContext: a header plus
        the whole file when it fits CAP, else a header, a whole-line
        prefix (lines 1-L), and a directive for the unshown remainder. L is
        the largest line count whose prefix and directive together fit CAP.
        The read-in-full directive is shorter than the grep directive, so a
        longer prefix can fit where a shorter one did not; the scan runs
        until the prefix alone exceeds CAP. A remainder of at most
        READ_BUDGET bytes gets a directive to Read lines L+1 to EOF in full
        before the first decision. A larger one gets a grep-on-demand directive instead: do
        not Read the remainder whole, grep MEMORY.md before any decision
        that may depend on a recorded fact or operator ruling, and Read only
        windows around hits, with a limit sized so that no span of that many
        consecutive lines in the file exceeds READ_BUDGET, unless one line
        alone does: then the limit is 1 and the stated span is over budget.
        The emitted grep command shell-quotes the path. Remainder bytes
        are counted from the raw file. A first line too long to show (L = 0)
        follows the same split on the whole file. Any exception in Phase B
        emits a fallback directive naming the path that never mandates a
        whole-file Read above READ_BUDGET. The output does not depend on
        the payload's `source`.

Upstream deps: Python 3.9+ stdlib only; `git` on PATH (optional - a failure
    falls back to cwd).

Downstream consumers: Claude Code hook runner (SessionStart, matcher "*",
    timeout 5), registered by .claude/install.sh in the guarded
    `test -f ... && python3 ... || exit 0` form. Documented in
    hooks/AGENTS.md. Other harnesses never run it and keep reading
    MEMORY.md through their own pointer or import.

Failure modes: always exits 0 and never writes anything. CAP is 8500 because
    9 KB was measured to arrive inline; the escaped length bounds every
    character or byte unit the harness might count.
    READ_BUDGET is 30000 bytes: the Read tool caps one call at 25,000
    tokens, and a dense MEMORY.md (authentic8, ~275 B/line) was measured at
    ~2 B/token, so one Read holds ~50 KB of it; 30 KB leaves ~40% margin
    for the Read tool's line-number prefixes and denser text. The window
    limit is the largest k in WINDOW_MIN..WINDOW_MAX whose heaviest k-line
    span is at most READ_BUDGET, else WINDOW_MIN, so a single outlier line
    shrinks it for the whole file.

Performance: one `git rev-parse` (2 s timeout) and reads of at most four
    files; well under the 5 s registration timeout.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

MARKER = "<!-- dinostack:memory-main-only -->"
CAP = 8500
READ_BUDGET = 30000
WINDOW_MIN = 1
WINDOW_MAX = 200
IMPORT_LINES = ("@MEMORY.md", "@./MEMORY.md")
IMPORT_FILES = ("CLAUDE.md", os.path.join(".claude", "CLAUDE.md"), "CLAUDE.local.md")


def _esc_len(s):
    return len(json.dumps(s, ensure_ascii=True)) - 2


def _split_lines(text):
    parts = text.split("\n")
    lines = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _has_line(path, wanted):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return any(line.strip() in wanted for line in f)
    except FileNotFoundError:
        return False


def _resolve_root(cwd):
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=2,
        )
        top = r.stdout.strip()
        if r.returncode == 0 and top:
            return top
    except (OSError, subprocess.SubprocessError):
        pass
    return cwd


def _has_marker(root):
    return _has_line(os.path.join(root, "CLAUDE.md"), (MARKER,))


def _has_import(root):
    return any(_has_line(os.path.join(root, name), IMPORT_LINES) for name in IMPORT_FILES)


def _header(path):
    return (
        "Root MEMORY.md (" + path + "), delivered to the main session only by "
        "the DinoStack session-start-memory hook:\n\n"
    )


def _tail_directive(n_bytes, n_lines, last, path):
    return (
        "MEMORY.md is %d bytes, %d lines; only lines 1-%d are shown. Before "
        "your first decision this session, Read %s lines %d-%d in full: one "
        "Read can stop short, so keep reading from the next unread line "
        "(offset/limit; halve limit if a Read is too large) until you have "
        "seen line %d. After a compact or clear, repeat this whenever lines "
        "%d-%d are no longer visible in this conversation."
        % (n_bytes, n_lines, last, path, last + 1, n_lines, n_lines, last + 1, n_lines)
    )


def _line_bytes(raw):
    parts = raw.split(b"\n")
    sizes = [len(p) + 1 for p in parts[:-1]]
    if parts[-1]:
        sizes.append(len(parts[-1]))
    return sizes


def _max_span(sizes, k):
    total = best = sum(sizes[:k])
    for i in range(k, len(sizes)):
        total += sizes[i] - sizes[i - k]
        best = max(best, total)
    return best


def _window_limit(sizes):
    lo, hi = WINDOW_MIN, max(WINDOW_MIN, min(WINDOW_MAX, len(sizes)))
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _max_span(sizes, mid) <= READ_BUDGET:
            lo = mid
        else:
            hi = mid - 1
    return lo, _max_span(sizes, lo)


def _grep_directive(n_bytes, n_lines, last, rest_bytes, path, window):
    shown = ("only lines 1-%d are shown" % last if last
             else "its first line exceeds the cap, so none is shown")
    return (
        "MEMORY.md is %d bytes, %d lines; %s. Do not Read lines %d-%d whole: "
        "those %d bytes are more than one Read returns (the Read tool caps a "
        "call at 25,000 tokens, and dense Markdown runs near 2 bytes per "
        "token). Instead, before any decision that may depend on a recorded "
        "fact or operator ruling, grep for it with `grep -n -i '<topic>' %s` "
        "and Read only a window around each hit: offset a few lines above the "
        "hit, limit at most %d (the heaviest %d-line span in this file is %d "
        "bytes). This holds for the whole session, including after a compact "
        "or clear."
        % (n_bytes, n_lines, shown, last + 1, n_lines, rest_bytes, shlex.quote(path),
           window[0], window[0], window[1])
    )


def _rest_directive(n_bytes, n_lines, last, rest_bytes, path, window):
    if rest_bytes > READ_BUDGET:
        return _grep_directive(n_bytes, n_lines, last, rest_bytes, path, window)
    if last == 0:
        return _none_shown_directive(n_bytes, n_lines, path)
    return _tail_directive(n_bytes, n_lines, last, path)


def _none_shown_directive(n_bytes, n_lines, path):
    return (
        "MEMORY.md is %d bytes, %d lines; its first line exceeds the cap, so "
        "none is shown. Before your first decision, Read %s lines 1-%d in "
        "full, continuing from the next unread line until you have seen "
        "line %d." % (n_bytes, n_lines, path, n_lines, n_lines)
    )


def build_context(path):
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8", errors="replace")
    header = _header(path)
    if 2 + _esc_len(header) + _esc_len(text) <= CAP:
        return header + text

    lines = _split_lines(text)
    sizes = _line_bytes(raw)
    window = _window_limit(sizes)
    used = 2 + _esc_len(header) + _esc_len("\n")
    last = 0
    shown_bytes = 0
    prefix_bytes = 0
    for i, line in enumerate(lines, start=1):
        used += _esc_len(line)
        if used > CAP:
            break
        prefix_bytes += sizes[i - 1]
        rest = len(raw) - prefix_bytes
        if used + _esc_len(_rest_directive(len(raw), len(lines), i, rest, path, window)) <= CAP:
            last = i
            shown_bytes = prefix_bytes
    directive = _rest_directive(len(raw), len(lines), last, len(raw) - shown_bytes, path, window)
    if last == 0:
        return header + directive
    return header + "".join(lines[:last]) + "\n" + directive


def _emit_ctx(ctx):
    print(json.dumps(
        {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}},
        ensure_ascii=True,
    ))


def main():
    try:
        payload = json.loads(sys.stdin.read())
        cwd = os.path.abspath(payload.get("cwd") or os.getcwd())
        root = os.path.abspath(_resolve_root(cwd))
        path = os.path.join(root, "MEMORY.md")
        if not _has_marker(root):
            print("{}")
            return
    except Exception:
        print("{}")
        return

    try:
        if _has_import(root):
            print("{}")
            return
        if not os.path.exists(path):
            print("{}")
            return
        ctx = build_context(path)
    except Exception as exc:
        ctx = (
            "DinoStack memory hook error (%s): MEMORY.md was not delivered. "
            "Before any decision that may depend on a recorded fact or operator "
            "ruling, grep %s for it (`grep -n -i '<topic>' %s`) and Read only "
            "a window around each hit; Read the whole file only if it is at "
            "most %d bytes." % (type(exc).__name__, path, shlex.quote(path), READ_BUDGET)
        )
    _emit_ctx(ctx)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
