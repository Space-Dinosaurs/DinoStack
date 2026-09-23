"""Purpose: find every MUTATING invocation of `bin/ds-cleanup-worktrees` under
         a repo's `content/`, `hooks/`, `bin/` and `scripts/` trees, so
         `test_worktree_lifecycle_spec.sh`'s
         `check_unattended_callers_carry_floor` can assert that set equals a
         pinned allowlist (DS-245 rubric R3: no unattended caller's refusal
         set may widen).

         This lives in its own module rather than inside that shell script's
         heredoc for one reason: the predicate has been WRONG in three
         consecutive review rounds (a flag was required, so a bare
         `"$DS_CLEANUP_BIN"` - which removes - was skipped; only
         shell-tagged fences were read; then an empty-string fence tag
         inverted the fence state machine and silently cost 836 executable
         lines in one file). Each was found by a reviewer hand-injecting a
         shape, because nothing committed exercised the predicate. Importing
         it makes `bin/tests/test_caller_scan.py` possible, which is the
         first coverage this logic has ever had.

Public API: SHELL_INFO, EXCLUDED_EXACT, EXCLUDED_DIRS, NON_MUTATING_FLAGS,
            PATTERN, SWEPT_PATHS
            is_invocation(line) -> bool
            executable_lines(lines, is_markdown) -> set[int] (1-based)
            find_mutating(repo_root) -> list[(path, lineno, raw_line)]

Upstream deps: Python 3 stdlib only (re, subprocess). `git grep` at the
               caller-supplied repo root. No writes of any kind.

Downstream consumers: bin/tests/test_worktree_lifecycle_spec.sh
                      (check_unattended_callers_carry_floor); its own
                      regression suite bin/tests/test_caller_scan.py,
                      auto-collected by `python3 -m pytest bin/tests/`.

Failure modes: `find_mutating` raises RuntimeError when the feeder `git
               grep` cannot run or matches nothing at all - an empty result
               there means the pattern or the swept paths have drifted, and
               reporting it as "no mutating callers" would be a vacuous
               pass. `is_invocation` and `executable_lines` are pure and
               total over any input.

Performance: one `git grep` over four trees plus a line scan of each hit
             file; sub-second on this repo.
"""

from __future__ import annotations

import re
import subprocess
from typing import Dict, List, Sequence, Set, Tuple

#: The step-9a enumeration pattern, DELIBERATELY WIDENED (DS-245 review
#: round 1, CM1). Step 9a's own pattern excludes `/` from the class preceding
#: the token, so it cannot match a path-form invocation such as
#: `python3 "$REPO_DIR/bin/ds-cleanup-worktrees" --explain` at all - measured
#: 0 hits for that line under 9a's pattern, 1 under this one. A feeder that
#: cannot see a shape makes any equality asserted downstream vacuous for it.
#: Dropping `/` does not loosen the TRAILING boundary, so a sibling binary
#: like `ds-cleanup-worktrees-all` is still not matched (its trailing `-` is
#: inside the excluded class); that sibling is handled deliberately by
#: EXCLUDED_EXACT, not by accident.
PATTERN = (
    r'(^|[^A-Za-z0-9_.-])(ds-cleanup-worktrees|DS_CLEANUP_BIN)'
    r'([^A-Za-z0-9_.-]|$)'
)

SWEPT_PATHS = ("content", "hooks", "bin", "scripts")

#: Two kinds, kept apart deliberately (DS-245 review round 1, cm3): EXACT
#: paths compared with ==, and DIRECTORY prefixes compared with startswith.
#: `bin/ds-cleanup-worktrees` is an exact path, never a prefix - as a prefix
#: it would silently swallow a future sibling such as
#: `bin/ds-cleanup-worktrees-all`, which WOULD be a caller and must be
#: classified rather than excluded by an accident of naming.
EXCLUDED_EXACT = ("bin/ds-cleanup-worktrees",)
#: `bin/tests/` covers this module and the spec shell, whose own literals
#: would otherwise self-trigger; both hold scratch-fixture invocations
#: rather than operational callers.
EXCLUDED_DIRS = ("bin/tests/", "hooks/tests/")

#: Fence info strings whose bodies are executable shell.
#:
#: The empty string is DELIBERATELY ABSENT (DS-245 review round 2, CM2-1).
#: Round 1 added it to catch an invocation written in a bare ``` fence, and
#: that was a net loss, measured two ways. A census of the swept paths finds
#: 624 bare fences against 119 `bash` ones, and the bare ones are
#: overwhelmingly output samples, JSON and diagrams - treating them as shell
#: manufactures false callers. `console` and `shell-session`, added in the
#: same round, match ZERO fences anywhere in the tree. Accepted residual,
#: stated rather than papered over: a mutating invocation written inside a
#: bare fence is not seen by this scan.
SHELL_INFO = ("bash", "sh", "shell", "zsh")

#: A run carrying any of these removes nothing.
NON_MUTATING_FLAGS = ("--count-only", "--report", "--dry-run")

#: The tool spelled as a COMMAND WORD. Three forms: a `$DS_CLEANUP_BIN`
#: expansion, a PATH ending in the tool name (at least one segment before
#: the slash, so the `/ds-cleanup-worktrees` SLASH COMMAND in `bin/ds-help`'s
#: listing is not mistaken for a filesystem path), or the bare name resolved
#: through PATH.
TOKEN_RE = re.compile(
    r'(?:'
    r'"?\$\{?DS_CLEANUP_BIN\}?"?'
    r'|"?[^\s;&|()"\x27]+/ds-cleanup-worktrees"?'
    r'|(?<![A-Za-z0-9_./-])ds-cleanup-worktrees'
    r')(?![A-Za-z0-9_.-])'
)

#: Words that may precede a command without displacing it from command
#: position: interpreters, and wrappers that go on to exec their argument.
#: The `"$VAR"` alternative covers the live `"$TIMEOUT_BIN" 5 python3 ...`
#: shape in hooks/session-start-wrap.sh.
_WRAPPER = (
    r'(?:python3?|exec|env|nohup|setsid|time|timeout|sudo|bash|sh|xargs'
    r'|"?\$\{?[A-Za-z_][A-Za-z0-9_]*\}?"?)'
)

#: Command position, matched against the text BEFORE the token on its line.
#: Deliberately narrow on `(`: a bare `(` counts only at line start (a
#: subshell, the shape the session-start reap uses), never mid-line, because
#: a `(` inside a prose string is common and would fabricate invocations.
CMD_PREFIX_RE = re.compile(
    r'(?:'
    r'^\s*'
    r'|^\s*\(\s*'
    r'|\$\(\s*'
    r'|[;&|]\s*'
    r'|\b(?:then|else|elif|do|if|while|until)\s+'
    r')'
    r'(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*'
    r'(?:' + _WRAPPER + r'\s+(?:[-\w./]+\s+)*)*'
    r'$'
)

#: `command -v <tool>` is a probe, not an invocation (step 9a says so).
PROBE_RE = re.compile(r'command\s+-v\s*$|(?<![A-Za-z0-9_-])-v\s*$')


def is_invocation(raw: str) -> bool:
    """True iff the tool stands in command position anywhere on this line.

    For the `$DS_CLEANUP_BIN` and bare-name forms, carrying a flag is NOT
    required: `"$DS_CLEANUP_BIN"` with no arguments at all runs the tool in
    its default mode, which REMOVES.

    The PATH form is the one exception, and the asymmetry is measured, not
    stylistic. Widening the feeder to see path forms also makes it return
    every `bin/ds-cleanup-worktrees` CROSS-REFERENCE in a Python docstring,
    and a docstring continuation line beginning with that path is in command
    position by every structural test there is - `bin/_lib.py`,
    `bin/ds-agentic-repair` and `bin/ds-branch-prune` were all flagged that
    way. Requiring a following flag separates naming a path from running it.
    Residual, stated at its true width (DS-245 review round 2, cm2-3): any
    path-form invocation whose first argument is not a flag is missed - a
    positional root under `--multi-repo`, or no arguments at all.
    """
    for m in TOKEN_RE.finditer(raw):
        before = raw[:m.start()]
        if PROBE_RE.search(before):
            continue
        if not CMD_PREFIX_RE.search(before):
            continue
        if "/" in m.group(0) and not re.match(r'\s+-', raw[m.end():]):
            continue
        return True
    return False


def executable_lines(lines: Sequence[str], is_markdown: bool) -> Set[int]:
    """1-based line numbers whose content is executable shell.

    For markdown that is the inside of a fence whose info string is in
    SHELL_INFO; for any other file it is every non-comment line.

    Fence nesting and fence EXECUTABILITY are tracked as two separate facts
    on purpose (DS-245 review round 2, CM2-1). Collapsing them into one flag
    is what let a non-shell fence's CLOSING ``` be read as OPENING an
    executable region: with the empty info string treated as shell, every
    line after a ```json block became "executable" and every line inside a
    real ```bash block after it became prose. Two variables cost two lines
    and make that class unrepresentable rather than merely absent today.
    """
    ok: Set[int] = set()
    if not is_markdown:
        for i, raw in enumerate(lines, 1):
            if not raw.strip().startswith("#"):
                ok.add(i)
        return ok

    in_fence = False
    fence_is_shell = False
    for i, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if stripped.startswith("```"):
            if in_fence:
                in_fence = False
                fence_is_shell = False
            else:
                info = stripped[3:].strip().split()
                in_fence = True
                fence_is_shell = bool(info) and info[0] in SHELL_INFO
            continue
        if in_fence and fence_is_shell and not stripped.startswith("#"):
            ok.add(i)
    return ok


def _grep_hits(repo_root: str) -> Dict[str, Set[int]]:
    proc = subprocess.run(
        ["git", "-C", repo_root, "grep", "-n", "-E", PATTERN, "--"] + list(SWEPT_PATHS),
        capture_output=True,
        text=True,
    )
    # `git grep` exits 1 on zero matches - which here means the enumeration
    # itself broke, never a clean result. Fail loudly rather than reporting
    # an empty mutating set as agreement with an empty allowlist.
    if proc.returncode not in (0, 1):
        raise RuntimeError(
            "the step-9a git grep failed (rc=%d): %s" % (proc.returncode, proc.stderr.strip())
        )
    if not proc.stdout.strip():
        raise RuntimeError(
            "the step-9a git grep matched NOTHING - the pattern or the swept "
            "paths have drifted, so this scan would otherwise report no "
            "callers having looked at nothing"
        )
    hits: Dict[str, Set[int]] = {}
    for line in proc.stdout.splitlines():
        path, lineno, _rest = line.split(":", 2)
        hits.setdefault(path, set()).add(int(lineno))
    return hits


def find_mutating(repo_root: str) -> List[Tuple[str, int, str]]:
    """Every mutating invocation under the swept paths, as (path, lineno, line)."""
    found: List[Tuple[str, int, str]] = []
    hits = _grep_hits(repo_root)
    for path in sorted(hits):
        if path in EXCLUDED_EXACT or path.startswith(EXCLUDED_DIRS):
            continue
        with open("%s/%s" % (repo_root, path), encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        ok = executable_lines(lines, path.endswith(".md"))
        for lineno in sorted(hits[path]):
            if lineno not in ok or lineno > len(lines):
                continue
            raw = lines[lineno - 1]
            if not is_invocation(raw):
                continue
            if any(flag in raw for flag in NON_MUTATING_FLAGS):
                continue
            found.append((path, lineno, raw))
    return found
