#!/usr/bin/env python3
"""
Purpose: PreToolUse Bash hook (DS-261) that denies an `rm` command whose
         operand expands an unguarded shell variable, such as
         `rm $B/$s/x`. Claude Code stops the operator with a "Dangerous rm
         operation on possibly-empty variable path" approval dialog for
         that shape, even under bypassPermissions (measured on Claude Code
         2.1.280, DS-261 Unit 0). A deny preempts the dialog in both the
         main session and a subagent (same measurement), and the deny
         reason names the `${VAR:?}` rewrite so the agent fixes the
         command itself. This hook is a dial serving operator attention,
         not an enforcement floor: it prevents no data loss the dialog
         would not, it only keeps the dialog from reaching the operator.

Catch: AUT-1046, authentic8, 2026-09-26. A subagent capture loop ran
       `rm $B/$s/$t.raw.json` and the operator was prompted on every batch.

Retirement: delete this hook, its install.sh block, its bin/ds-doctor
            MANAGED_HOOK_BASENAMES entry, and its count-sync edits when
            either holds:
    (a) a no-hook interactive pty probe, run under bypassPermissions (the
        mode Unit 0 found the dialog in), on a newer Claude Code release
        shows no dialog for `rm $A/$B/x`; or
    (b) zero deny rows in the last 90 days across every fire-log copy on
        the operator's machine, including worktree copies:
        `find <operator dev root> -name .enforcement-fires.jsonl` piped
        through
        `jq -c --arg since "<ISO date 90 days ago>" 'select(.hook=="enforce-guarded-rm" and .decision=="deny" and .ts >= $since)'`.

Trigger: PreToolUse, matcher "Bash". Applies to the main session and to
         subagents alike; `permission_mode` is not read, because nothing in
         the payload separates an interactive session (where the dialog
         costs the operator) from a headless one.

Wiring: registered by .claude/install.sh under the "Bash" matcher with the
        guarded command form
        `test -f <path> && python3 <path> || exit 0`, never a bare
        `python3 <path>`: a missing script exits 2, which is BLOCKING on
        PreToolUse. Claude Code only; no other adapter has this dialog.

Public API:
    find_unguarded_rm(command: str) -> Optional[Tuple[str, List[str]]]
        Pure. Returns (operand_raw, [var_names]) for the first `rm` operand
        that expands an unguarded variable, else None. Never raises: any
        parse failure returns None (allow).
    main() -> None
        Hook entry point. Reads the PreToolUse JSON payload on stdin. On a
        hit it prints a hookSpecificOutput deny first, then logs one fire
        row with detail {"agent_self_corrects": true}, which /ds-wrap D.5
        signal 3(b) excludes from its guardrail-fire tally.

Classification:
    - Counted as variables: $NAME, $1-$9, ${...}.
    - Guarded (allow): ${#...}, ${NAME:?...}, and ${NAME:-w} / ${NAME:=w}
      where w is non-empty and contains no `$` or backtick.
    - Ignored: $@ $* $# $? $$ $! $- $0 and $((...)).
    - Unguarded (deny): every other variable form, including ${X}, ${X?}
      and an operand that is only a variable (`rm "$f"`).
    - Only expansions outside single quotes and not backslash-escaped count.
    - $(...), backticks, <(...) and >(...) bodies are analysed as separate
      commands; their substituted value is not treated as a variable.
    - `rm` is a command-position word whose literal basename is `rm`
      (`rm`, `/bin/rm`), after skipping leading NAME=v assignments.
      Command position: first word, after an operator, or after one of
      do then else elif if while until ! { time.
    - Operands run to the next operator. Words with a literal leading `-`
      are options until `--`. Redirection targets are not operands.

Residuals (allowed, not analysed): a wrapped rm (sudo, env, nice, xargs,
    command, exec), `git rm`, `find -delete` and `-exec rm`, rmdir, unlink,
    shred, command strings passed to bash -c / eval / ssh, heredoc bodies,
    and case arms.

Upstream deps: Python 3 stdlib only (json, os, re, sys, importlib.util,
               pathlib). Soft dependency on hooks/lib/enforcement_log.py,
               loaded lazily in the deny branch; falls back to a no-op.

Downstream consumers: Claude Code hook runner (PreToolUse, "Bash").
                      content/commands/ds-wrap.md D.5 signal 3(b) reads
                      the fire rows. Documented in hooks/AGENTS.md
                      §Entry points.

Failure modes: fail-open everywhere except the deny itself.
    - Kill-switch AE_RM_GUARD_DISABLE=1 in the hook process environment:
      exit 0 before reading stdin. It must be set before the session
      starts; writing it inline in the command does not disable the hook.
    - Malformed stdin, a non-dict payload, tool_name other than "Bash", or
      a missing / empty / non-str command: exit 0, no output.
    - Unbalanced quotes or parentheses (including a `case ... in a)`
      pattern), an unquoted `<<` / `<<-` heredoc, input over 100,000
      characters, or nesting deeper than 5: allow.
    - The deny is printed before log_fire runs, and log_fire runs inside
      its own try/except, so a raising telemetry helper cannot turn the
      deny into an allow.
    - Any other exception: exit 0.

Performance: one linear pass over the command string per nesting level;
             python3 startup dominates (about 30 ms per Bash call).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

HOOK_NAME = "enforce-guarded-rm"
KILL_SWITCH = "AE_RM_GUARD_DISABLE"

MAX_INPUT_LEN = 100000
MAX_DEPTH = 5
OPERAND_DISPLAY_MAX = 200

REASON_TEMPLATE = (
    "Blocked (enforce-guarded-rm, DS-261): rm operand {op} expands unguarded "
    "variable(s) {vars}. An empty or unset value collapses the path "
    "(e.g. $B/x -> /x), and an interactive Claude Code session may stop to "
    "ask the operator. Rewrite each as ${{VAR:?}} "
    '(e.g. rm "${{B:?}}"/"${{s:?}}"/file), or write the files under a literal '
    "scratchpad path and rm that literal path."
)

_RESERVED = frozenset(
    ("do", "then", "else", "elif", "if", "while", "until", "!", "{", "time")
)
_SPECIAL_PARAMS = "@*#?$!-"
_NAME_START = re.compile(r"[A-Za-z_]")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_BRACE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+|[@*#?$!-]")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")


class _FailOpen(Exception):
    pass


class _Found(Exception):
    def __init__(self, operand: str, names: List[str]) -> None:
        super().__init__(operand)
        self.operand = operand
        self.names = names


class _Word:
    __slots__ = ("start", "end", "lit", "unguarded", "has_exp", "quoted",
                 "first_literal", "nested")

    def __init__(self, start: int) -> None:
        self.start = start
        self.end = start
        self.lit: List[str] = []
        self.unguarded: List[str] = []
        self.has_exp = False
        self.quoted = False
        self.first_literal: Optional[str] = None
        self.nested: List[str] = []

    def add_lit(self, text: str) -> None:
        if self.first_literal is None and not self.has_exp and not self.lit:
            self.first_literal = text[:1] if text else None
        self.lit.append(text)

    def add_exp(self, unguarded_name: Optional[str]) -> None:
        if not self.lit and not self.has_exp:
            self.first_literal = ""
        self.has_exp = True
        if unguarded_name is not None:
            self.unguarded.append(unguarded_name)

    def literal(self) -> str:
        return "".join(self.lit)


def _skip_squote(s: str, i: int) -> int:
    j = s.find("'", i)
    if j < 0:
        raise _FailOpen()
    return j + 1


def _match_backtick(s: str, i: int) -> int:
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "`":
            return i
        i += 1
    raise _FailOpen()


def _skip_dquote(s: str, i: int) -> int:
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
        elif c == '"':
            return i + 1
        elif c == "$" and s.startswith("$(", i):
            i = _match_paren(s, i + 2) + 1
        elif c == "$" and s.startswith("${", i):
            i = _match_brace(s, i + 2) + 1
        elif c == "`":
            i = _match_backtick(s, i + 1) + 1
        else:
            i += 1
    raise _FailOpen()


def _match_paren(s: str, i: int) -> int:
    """Index of the `)` closing a `(` whose body starts at i."""
    n = len(s)
    depth = 1
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
        elif c == "'":
            i = _skip_squote(s, i + 1)
        elif c == '"':
            i = _skip_dquote(s, i + 1)
        elif c == "`":
            i = _match_backtick(s, i + 1) + 1
        elif c == "(":
            depth += 1
            i += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
            i += 1
        else:
            i += 1
    raise _FailOpen()


def _match_brace(s: str, i: int) -> int:
    """Index of the `}` closing a `${` whose body starts at i."""
    n = len(s)
    depth = 1
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
        elif c == "'":
            i = _skip_squote(s, i + 1)
        elif c == '"':
            i = _skip_dquote(s, i + 1)
        elif c == "`":
            i = _match_backtick(s, i + 1) + 1
        elif s.startswith("$(", i):
            i = _match_paren(s, i + 2) + 1
        elif s.startswith("${", i):
            depth += 1
            i += 2
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
            i += 1
        else:
            i += 1
    raise _FailOpen()


def _classify_brace(inner: str) -> Optional[str]:
    """Return the variable name if ${inner} is an unguarded variable, else
    None (guarded or ignored)."""
    if inner.startswith("#") and len(inner) > 1:
        return None
    m = _BRACE_NAME.match(inner)
    if not m:
        return inner or "?"
    name = m.group(0)
    rest = inner[m.end():]
    if name in _SPECIAL_PARAMS:
        if name == "!" and rest:
            return rest
        return None
    if name == "0" and not rest:
        return None
    if rest.startswith(":?"):
        return None
    if rest[:2] in (":-", ":="):
        word = rest[2:]
        if word and "$" not in word and "`" not in word:
            return None
    return name


def _unescape_backtick(body: str) -> str:
    return re.sub(r"\\([`$\\])", r"\1", body)


class _Lexer:
    def __init__(self, s: str) -> None:
        self.s = s
        self.n = len(s)
        self.tokens: List[Tuple[str, object]] = []
        self.word: Optional[_Word] = None
        self.paren = 0

    def ensure(self, i: int) -> _Word:
        if self.word is None:
            self.word = _Word(i)
        return self.word

    def finish(self, i: int) -> None:
        if self.word is not None:
            self.word.end = i
            self.tokens.append(("word", self.word))
            self.word = None

    def dollar(self, i: int, w: _Word, in_dq: bool) -> int:
        s = self.s
        nxt = s[i + 1] if i + 1 < self.n else ""
        if s.startswith("$((", i):
            j = _match_paren(s, i + 2)
            w.add_exp(None)
            return j + 1
        if nxt == "(":
            j = _match_paren(s, i + 2)
            w.nested.append(s[i + 2:j])
            w.add_exp(None)
            return j + 1
        if nxt == "{":
            j = _match_brace(s, i + 2)
            w.add_exp(_classify_brace(s[i + 2:j]))
            return j + 1
        if nxt and _NAME_START.match(nxt):
            m = _NAME.match(s, i + 1)
            w.add_exp(m.group(0))
            return m.end()
        if nxt.isdigit() and nxt.isascii():
            w.add_exp(None if nxt == "0" else nxt)
            return i + 2
        if nxt and nxt in _SPECIAL_PARAMS:
            w.add_exp(None)
            return i + 2
        if nxt == "'" and not in_dq:
            k = i + 2
            while k < self.n:
                if s[k] == "\\":
                    k += 2
                    continue
                if s[k] == "'":
                    w.add_lit(s[i + 2:k])
                    w.quoted = True
                    return k + 1
                k += 1
            raise _FailOpen()
        if nxt == '"' and not in_dq:
            return i + 1
        w.add_lit("$")
        return i + 1

    def dquote(self, i: int, w: _Word) -> int:
        s = self.s
        w.quoted = True
        while i < self.n:
            c = s[i]
            if c == "\\":
                nxt = s[i + 1] if i + 1 < self.n else ""
                if nxt == "\n":
                    i += 2
                elif nxt in ('$', '`', '"', '\\'):
                    w.add_lit(nxt)
                    i += 2
                else:
                    w.add_lit("\\")
                    i += 1
            elif c == '"':
                return i + 1
            elif c == "$":
                i = self.dollar(i, w, True)
            elif c == "`":
                j = _match_backtick(s, i + 1)
                w.nested.append(_unescape_backtick(s[i + 1:j]))
                w.add_exp(None)
                i = j + 1
            else:
                w.add_lit(c)
                i += 1
        raise _FailOpen()

    def redirection_len(self, i: int) -> int:
        s = self.s
        for op in ("<<<", "&>>", ">>", ">&", ">|", "<>", "<&", "&>"):
            if s.startswith(op, i):
                return len(op)
        if s.startswith("<<", i):
            raise _FailOpen()
        return 1

    def run(self) -> List[Tuple[str, object]]:
        s = self.s
        i = 0
        while i < self.n:
            c = s[i]
            if c == "\\":
                if i + 1 < self.n and s[i + 1] == "\n":
                    i += 2
                    continue
                w = self.ensure(i)
                w.add_lit(s[i + 1] if i + 1 < self.n else "\\")
                w.quoted = True
                i += 2
                continue
            if c in " \t\r":
                self.finish(i)
                i += 1
                continue
            if c == "\n":
                self.finish(i)
                self.tokens.append(("op", "\n"))
                i += 1
                continue
            if c == "#" and self.word is None:
                j = s.find("\n", i)
                i = self.n if j < 0 else j
                continue
            if c == "'":
                w = self.ensure(i)
                j = _skip_squote(s, i + 1)
                w.add_lit(s[i + 1:j - 1])
                w.quoted = True
                i = j
                continue
            if c == '"':
                w = self.ensure(i)
                i = self.dquote(i + 1, w)
                continue
            if c == "`":
                w = self.ensure(i)
                j = _match_backtick(s, i + 1)
                w.nested.append(_unescape_backtick(s[i + 1:j]))
                w.add_exp(None)
                i = j + 1
                continue
            if c == "$":
                w = self.ensure(i)
                i = self.dollar(i, w, False)
                continue
            if c in "<>" and s.startswith("(", i + 1):
                w = self.ensure(i)
                j = _match_paren(s, i + 2)
                w.nested.append(s[i + 2:j])
                w.add_exp(None)
                i = j + 1
                continue
            if c in "<>" or s.startswith("&>", i):
                w = self.word
                if (w is not None and not w.quoted and not w.has_exp
                        and w.literal().isdigit()):
                    self.word = None
                else:
                    self.finish(i)
                length = self.redirection_len(i)
                self.tokens.append(("redir", s[i:i + length]))
                i += length
                continue
            if c in ";&|()":
                self.finish(i)
                two = s[i:i + 2]
                if two in ("&&", "||", "|&", ";;"):
                    op = two
                else:
                    op = c
                if op == "(":
                    self.paren += 1
                elif op == ")":
                    self.paren -= 1
                    if self.paren < 0:
                        raise _FailOpen()
                self.tokens.append(("op", op))
                i += len(op)
                continue
            w = self.ensure(i)
            w.add_lit(c)
            i += 1
        self.finish(self.n)
        if self.paren != 0:
            raise _FailOpen()
        return self.tokens


def _dedupe(names: List[str]) -> List[str]:
    seen: List[str] = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return seen


def _analyze(command: str, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise _FailOpen()
    tokens = _Lexer(command).run()
    cmd_pos = True
    in_rm = False
    after_dd = False
    skip_target = False
    for kind, val in tokens:
        if kind == "op":
            cmd_pos = True
            in_rm = False
            skip_target = False
            continue
        if kind == "redir":
            skip_target = True
            continue
        w = val  # type: _Word
        for body in w.nested:
            _analyze(body, depth + 1)
        if skip_target:
            skip_target = False
            continue
        raw = command[w.start:w.end]
        if in_rm:
            if not after_dd and not w.has_exp and w.literal() == "--":
                after_dd = True
                continue
            if not after_dd and w.first_literal == "-":
                continue
            if w.unguarded:
                raise _Found(raw, _dedupe(w.unguarded))
            continue
        if not cmd_pos:
            continue
        if _ASSIGNMENT.match(raw):
            continue
        lit = w.literal()
        if not w.has_exp and lit in _RESERVED:
            continue
        cmd_pos = False
        if not w.has_exp and lit.rsplit("/", 1)[-1] == "rm":
            in_rm = True
            after_dd = False


def find_unguarded_rm(command: str) -> Optional[Tuple[str, List[str]]]:
    try:
        if not isinstance(command, str) or len(command) > MAX_INPUT_LEN:
            return None
        _analyze(command, 0)
        return None
    except _Found as hit:
        return hit.operand, hit.names
    except Exception:
        return None


def _load_log_fire():
    try:
        import importlib.util as _ilu

        here = Path(__file__).resolve().parent
        mod_path = here / "lib" / "enforcement_log.py"
        spec = _ilu.spec_from_file_location("enforcement_log", str(mod_path))
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.log_fire
    except Exception:
        return lambda *a, **k: None


def build_reason(operand: str, names: List[str]) -> str:
    op = operand[:OPERAND_DISPLAY_MAX]
    return REASON_TEMPLATE.format(
        op=op, vars=", ".join("$" + n for n in names)
    )


def main() -> None:
    if os.environ.get(KILL_SWITCH) == "1":
        sys.exit(0)
    try:
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)
        if not isinstance(data, dict) or data.get("tool_name") != "Bash":
            sys.exit(0)
        tool_input = data.get("tool_input")
        if not isinstance(tool_input, dict):
            sys.exit(0)
        command = tool_input.get("command")
        if not isinstance(command, str) or not command:
            sys.exit(0)
        hit = find_unguarded_rm(command)
        if hit is None:
            sys.exit(0)
        reason = build_reason(hit[0], hit[1])
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))
        sys.stdout.flush()
        try:
            _load_log_fire()(
                data, HOOK_NAME, "deny", reason,
                detail={"agent_self_corrects": True},
            )
        except Exception:
            pass
        sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
