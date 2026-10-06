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

Behavior:
    Phase A: root = `git -C <cwd> rev-parse --show-toplevel`, else cwd.
        Prints `{}` when root CLAUDE.md has no line equal to MARKER after
        strip(), or on any exception.
    Phase B (marker confirmed): prints `{}` when CLAUDE.md,
        .claude/CLAUDE.md or CLAUDE.local.md under root still carries a
        stripped `@MEMORY.md` / `@./MEMORY.md` line (the import already
        delivers it, to subagents too), or when root/MEMORY.md is absent.
        Otherwise emits hookSpecificOutput.additionalContext: a header plus
        the whole file when it fits CAP, else a header, the longest
        whole-line prefix (lines 1-L) that fits, and a directive to Read
        lines L+1 to EOF before the first decision. Any exception in Phase B
        emits a fallback directive naming the path instead of silence.
        The output does not depend on the payload's `source`.

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

Performance: one `git rev-parse` (2 s timeout) and reads of at most four
    files; well under the 5 s registration timeout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

MARKER = "<!-- dinostack:memory-main-only -->"
CAP = 8500
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


def _tail_directive(n_bytes, last, path):
    return (
        "MEMORY.md is %d bytes; only lines 1-%d are shown. Before your first "
        "decision this session, Read %s from line %d to EOF in full "
        "(offset/limit; halve limit if a Read is too large). After a compact "
        "or clear, repeat this whenever lines %d to EOF are no longer visible "
        "in this conversation." % (n_bytes, last, path, last + 1, last + 1)
    )


def _none_shown_directive(n_bytes, path):
    return (
        "MEMORY.md is %d bytes; its first line exceeds the cap, so none is "
        "shown. Read %s in full from line 1 before your first decision."
        % (n_bytes, path)
    )


def build_context(path):
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8", errors="replace")
    header = _header(path)
    if 2 + _esc_len(header) + _esc_len(text) <= CAP:
        return header + text

    lines = _split_lines(text)
    used = 2 + _esc_len(header) + _esc_len("\n")
    last = 0
    for i, line in enumerate(lines, start=1):
        used += _esc_len(line)
        if used + _esc_len(_tail_directive(len(raw), i, path)) > CAP:
            break
        last = i
    if last == 0:
        return header + _none_shown_directive(len(raw), path)
    return header + "".join(lines[:last]) + "\n" + _tail_directive(len(raw), last, path)


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
            "Read %s in full before your first decision." % (type(exc).__name__, path)
        )
    _emit_ctx(ctx)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
