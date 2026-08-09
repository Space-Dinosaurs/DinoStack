#!/usr/bin/env python3
"""
Purpose: Mechanically enumerate every consumer that would break if a set of
         line ranges were moved out of a target markdown file (e.g. splitting
         content/commands/ds-implement-ticket.md into content/references/*
         behind trigger-pointers). Exists because four prose-only review
         rounds on that exact split each fixed the named defects and left or
         reintroduced structurally identical ones - prose review can only
         falsify a claim someone wrote down, never one nobody made.

Public API: CLI. `python3 scripts/prose-move-impact.py --target <path>
            --range START:END:DEST [--range ...] | --config <json>`. Prints a
            human-readable report to stdout. Exit 0 only when every consumer
            was fully resolved, every resolved assertion still holds after
            the proposed move, AND no consumer's scanned set is left behind
            by the move (see `Report.ok`); exit 1 when any assertion breaks,
            anything could not be resolved (see UNRESOLVED below - this is
            deliberate: an unresolved assertion is treated as a potential
            break, not a pass), or a consumer's hardcoded single-file scan
            would silently stop covering the moved content post-move (see
            SCANNED SET below - a consumer whose only finding is
            `leaves_scanned_set=True` must not exit 0 either). Importable:
            `analyze(repo_root, target_rel, ranges) -> Report` for callers
            that want the structured result (used by
            bin/tests/test_prose_move_impact.py).

Upstream deps: `git grep` (consumer discovery), Python stdlib only
               (re, ast, bisect, dataclasses, json, argparse). No PyPI deps.

Downstream consumers: bin/tests/test_prose_move_impact.py (spec + known-
                      answer fixtures + regression tests + mutation test +
                      a differential test that simulates the post-move
                      tree in a scratch git repo and runs the real shell
                      gates against it). Intended to be run ad hoc by a
                      human/architect before authoring a split plan, not
                      wired into CI as a required gate - its inputs
                      (proposed move ranges) do not exist yet on main and
                      there is nothing for a CI job to check against.

Failure modes: any consumer file this tool cannot parse into at least one
               resolved assertion, or any assertion whose target-line
               resolution is ambiguous, is emitted verbatim in the
               UNRESOLVED section and forces a non-zero exit. This is
               intentional per the tool's own design constraint ("fail
               loud, never silently skip") - a tool that quietly drops
               what it does not understand reproduces the exact failure
               mode it exists to prevent. A regex-metachar pattern (from a
               `_present`/`grep -qiE` shell call site) is resolved via an
               ERE fallback, not just a literal substring match - see
               `_resolve_literal_in_target`. A consumer that hardcodes a
               single-file scan of the target with no `content/**`-wide
               fallback (see `infer_scanned_set`) forces a non-zero exit
               too, even when nothing else in the report resolved to a
               break - `Report.ok` treats `leaves_scanned_set=True` as a
               failure in its own right, not just an informational row, so
               a run whose only finding is a left-behind scanned set cannot
               silently print `Verdict: OK`. Read-only; no side effects.

Performance: single pass over `git grep` output plus one parse per
             discovered consumer file (typically a few dozen files, low
             hundreds of KB total) - well under a second on this repo.
"""

from __future__ import annotations

import argparse
import ast
import bisect
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TARGET = "content/commands/ds-implement-ticket.md"
SEARCH_DIRS = ["bin/tests", "hooks/tests", "content", "scripts", ".github"]

# Consumers whose entire job is talking ABOUT this tool/its fixtures, or
# generated/build artifacts that mention the target path only incidentally.
# Kept short and explicit rather than clever, per the "fail loud" mandate -
# an entry here is a deliberate, reviewable exemption, not a silent guess.
SELF_EXEMPT_SUFFIXES = ("prose-move-impact.py", "test_prose_move_impact.py")

# Mechanical-assertion extraction (literal/regex/heading-block/count-floor)
# is scoped to actual executable gates - test suites and check-*.sh scripts.
# Everything else discovery turns up (content/**, .github/prompts, .github/
# agents, README-style docs) is PROSE that mentions or duplicates the target,
# not a runnable assertion against it: it can contain any short English word
# that also happens to appear in the target ("default", "status", "worktree")
# with zero semantic connection. Treating those as load-bearing produced
# hundreds of false "BREAKING" rows on generic short strings. Those files
# are still discovered and reported (doc-sync is a real, separate concern -
# see AGENTS.md's docs-currency-pass rule) but only via a lightweight
# heading-citation check, never via arbitrary literal matching.


def _is_checked_consumer(rel: str) -> bool:
    if rel.startswith("bin/tests/") or rel.startswith("hooks/tests/"):
        return True
    name = Path(rel).name
    if rel.startswith("scripts/") and name.startswith("check-") and name.endswith(".sh"):
        return True
    return False


# ---------------------------------------------------------------------------
# Fence-aware heading index
# ---------------------------------------------------------------------------


@dataclass
class Heading:
    line: int  # 1-indexed line of the "## " (or "### ") heading
    end_line: int  # 1-indexed last line belonging to this heading's block
    level: int  # number of leading '#' characters
    text: str  # full heading line, stripped of trailing whitespace


def fence_aware_headings(lines: list[str]) -> list[Heading]:
    """Scan `lines` (no trailing newlines required) tracking ``` fence state
    and record only '#'-prefixed heading lines OUTSIDE a fence. A block's
    end_line is the line before the next heading of level <= its own level,
    or EOF - this mirrors _extract_block()-style consumers that stop at the
    next top-level heading, not the next heading of any depth."""
    fenced = False
    starts: list[tuple[int, int, str]] = []  # (line_no, level, text)
    fence_re = re.compile(r"^```")
    heading_re = re.compile(r"^(#{1,6})\s")
    for i, raw in enumerate(lines, start=1):
        s = raw.rstrip("\n")
        if fence_re.match(s):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = heading_re.match(s)
        if m:
            starts.append((i, len(m.group(1)), s))
    headings: list[Heading] = []
    for idx, (ln, level, text) in enumerate(starts):
        end = len(lines)
        for j in range(idx + 1, len(starts)):
            nxt_ln, nxt_level, _ = starts[j]
            if nxt_level <= level:
                end = nxt_ln - 1
                break
        headings.append(Heading(line=ln, end_line=end, level=level, text=text))
    return headings


def build_line_starts(text: str) -> list[int]:
    starts = [0]
    for m in re.finditer("\n", text):
        starts.append(m.end())
    return starts


def offset_to_line(line_starts: list[int], offset: int) -> int:
    return bisect.bisect_right(line_starts, offset)


# ---------------------------------------------------------------------------
# Move ranges
# ---------------------------------------------------------------------------


@dataclass
class MoveRange:
    start: int
    end: int
    dest: str

    def contains(self, line: int) -> bool:
        return self.start <= line <= self.end

    def overlaps(self, start: int, end: int) -> bool:
        return not (end < self.start or start > self.end)


def range_for_line(ranges: list[MoveRange], line: int) -> MoveRange | None:
    for r in ranges:
        if r.contains(line):
            return r
    return None


def any_range_overlaps(ranges: list[MoveRange], start: int, end: int) -> MoveRange | None:
    for r in ranges:
        if r.overlaps(start, end):
            return r
    return None


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


@dataclass
class Assertion:
    consumer: str
    kind: str  # literal_presence | literal_absent | literal_count | comment_reference
    #             | heading_block | regex_pattern | line_range | grep_count_floor
    detail: str
    resolved: bool
    breaks: bool  # True if the move would break this assertion
    lines: list[int] = field(default_factory=list)
    note: str = ""


@dataclass
class Unresolved:
    consumer: str
    detail: str
    line: int | None = None


@dataclass
class ScannedSetFinding:
    consumer: str
    scope: str  # "single-file" | "multi-file-content" | "unknown"
    detail: str
    leaves_scanned_set: bool = False


@dataclass
class DocCitation:
    consumer: str
    heading: str
    dest: str


@dataclass
class Report:
    target: str
    ranges: list[MoveRange]
    consumers: list[str]
    assertions: list[Assertion] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)
    scanned_sets: list[ScannedSetFinding] = field(default_factory=list)
    doc_consumers: list[str] = field(default_factory=list)
    doc_citations: list[DocCitation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        if self.unresolved:
            return False
        if any(a.breaks for a in self.assertions):
            return False
        if any(s.leaves_scanned_set for s in self.scanned_sets):
            return False
        return True


# ---------------------------------------------------------------------------
# Consumer discovery
# ---------------------------------------------------------------------------


def discover_consumers(repo_root: Path, target_rel: str) -> list[str]:
    basename = Path(target_rel).name
    pattern = "|".join(re.escape(p) for p in {target_rel, basename})
    cmd = ["git", "grep", "-l", "-E", pattern, "--"] + SEARCH_DIRS
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"git grep discovery failed: {proc.stderr.strip()}")
    files = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line == target_rel:
            continue
        if any(line.endswith(sfx) for sfx in SELF_EXEMPT_SUFFIXES):
            continue
        files.add(line)
    return sorted(files)


# ---------------------------------------------------------------------------
# Shell-continuation join (backslash line continuation -> one logical line)
# ---------------------------------------------------------------------------


def join_shell_continuations(text: str) -> list[tuple[int, str]]:
    """Return (starting_line_no, logical_line) pairs, joining any line
    ending in a bare trailing backslash with the following physical line(s)
    so a multi-line `_absent "$SPEC" "label" \\n  'pattern'` call is visible
    to a single-line regex scan."""
    raw_lines = text.split("\n")
    out: list[tuple[int, str]] = []
    i = 0
    n = len(raw_lines)
    while i < n:
        start = i + 1
        buf = raw_lines[i]
        while buf.endswith("\\") and i + 1 < n:
            buf = buf[:-1] + " " + raw_lines[i + 1]
            i += 1
        out.append((start, buf))
        i += 1
    return out


# ---------------------------------------------------------------------------
# Literal-string assertion extraction (generic, language-agnostic)
# ---------------------------------------------------------------------------

# The double-quote branch is deliberately restricted to never START a match
# at a position followed by `$(` (shell command substitution). Without that
# guard, a line like `G6="$(git grep -cE 'pattern' -- "$DIT" ...)"` lets the
# double-quote alternative greedily match from the assignment's opening `"`
# all the way to the NEXT `"` it meets - which here is the opening quote of
# the nested `"$DIT"`, not the assignment's real closing quote - swallowing
# the single-quoted grep pattern living in between as unmatched filler and
# denying the single-quote alternative any chance to see it (finditer never
# backtracks into a span a prior alternative already consumed). Shell/code
# syntax like `$(...)` is not itself a content literal we want to extract,
# so refusing to start a double-quote match there is safe.
#
# The single-quote branch deliberately does NOT exclude a backslash from
# its content class (unlike the double-quote branch): bash single quotes
# have no escape mechanism at all - `\` is a literal character inside
# `'...'`, and the closing `'` is always the next single-quote character,
# full stop. A `grep -qiE '<pattern>'` call site's pattern routinely
# contains backslash-escaped ERE metacharacters (`\(`, `\)`, `\+`, `\.`) -
# excluding `\` from the class silently made `_literals_in_line` never
# extract those patterns AT ALL (not merely fail to resolve them against
# the target), which is a distinct and more severe drop than the
# resolution-time literal-vs-ERE gap this module fixes elsewhere.
_STR_RE = re.compile(r'"((?:(?!\$\()[^"\\]){6,300})"|\'([^\']{6,300})\'')


_SHELL_NOISE_RE = re.compile(r"^\s*\$?\(?\s*(echo|cat|grep|awk|sed|printf|true|false)\b")


def _is_meaningful_literal(lit: str) -> bool:
    """A single snake_case/camelCase token (e.g. `task_id`, `created_at`)
    coincidentally reappears in a 3600-line prose file constantly and is
    almost never itself the thing under test - the surrounding code (a
    dict-key check, a JSON schema field) is testing something about the
    *consumer's own data model*, not this specific target file's prose. A
    real content assertion against the target is either a multi-word
    phrase, or a short token wrapped in punctuation that marks it as a
    deliberately quoted fragment (a backtick-quoted identifier, a path, a
    key: value pair, an env-var style `$NAME`, or a rendered literal like
    `NAME=value`). Common inline shell boilerplate that both the target's
    fenced code examples and a consumer's own script logic incidentally
    share (`2>/dev/null || true`, `$(echo ...`) is excluded explicitly -
    it is shell noise, not a content assertion against the target's prose."""
    if _SHELL_NOISE_RE.match(lit) or "2>/dev/null" in lit or lit.strip() in ("", "true", "false"):
        return False
    if len([w for w in lit.split() if w]) >= 2:
        # A real multi-word phrase - the dominant shape of the fixtures'
        # own load-bearing assertions ("## Tracker Writeback Helper",
        # "State Dev Complete:", "Pipeline order"). A single word padded
        # with whitespace (' want ') does not count as multi-word.
        return True
    if len(lit) >= 12 and re.search(r"[`:/=$]", lit) and not re.search(r"[()]", lit):
        return True
    return False


def _literals_in_line(line: str) -> list[str]:
    out = []
    for m in _STR_RE.finditer(line):
        lit = m.group(1) if m.group(1) is not None else m.group(2)
        out.append(lit)
    return out


def _classify_line(logical_line: str) -> str:
    l = logical_line
    stripped = l.strip()
    if stripped.startswith("#"):
        return "comment_reference"
    # Bash-style helper calls (`_absent "$SPEC" "label" 'pattern'`) have no
    # parens - shell function invocation syntax never does - so the
    # `"_absent("`/`"_present("` substring checks below only catch a
    # Python-style call. Detect the bash form explicitly, or every such
    # call (the dominant shape across bin/tests/*.sh's `_present`/`_absent`
    # helpers) silently falls through to the generic "literal_reference"
    # catch-all below and never gets treated as a load-bearing assertion.
    is_absent_call = (
        "_absent(" in l
        or stripped.startswith("_absent ")
        or re.search(r"\bnot in\b", l)
    )
    if is_absent_call or (".count(" in l and "== 0" in l):
        if ".count(" in l and "== 0" in l:
            return "literal_count"
        return "literal_absent"
    if "_present(" in l or stripped.startswith("_present "):
        return "literal_presence"
    if ".count(" in l:
        return "literal_count"
    if re.search(r"\bin\s+text\b|\bin\s+block\b|\bin\s+canonical_block\b|\bin\s+implement_ticket_text\b", l):
        return "literal_presence"
    if "assert" in l and " in " in l:
        return "literal_presence"
    return "literal_reference"


def _is_shell_call_line(logical_line: str) -> bool:
    """True only for the bash `_absent`/`_present` test-helper calling
    convention (`_absent(` / `_present(` as a Python-adjacent form, or the
    space-separated shell-invocation form `_absent "..." ...`). This
    convention has a FIXED, verified argument order (`<file>? <label>
    <pattern>`) with the actual grep pattern always last - a distinct
    literal-ordering contract from the Python `"phrase" in text` /
    `assert "phrase" in text, f"error message"` idiom, where the FIRST
    literal is the search phrase and any LATER literal is part of an
    error message, not a second pattern to resolve. Conflating the two
    orderings (treating "last literal" as universally special) mis-selects
    the error-message string as the assertion payload for every Python
    consumer and floods the report with spurious UNRESOLVED rows for
    ordinary human-readable failure text."""
    l = logical_line
    stripped = l.strip()
    return "_absent(" in l or "_present(" in l or stripped.startswith(("_absent ", "_present "))


# Matches the 3-arg shell calling convention `_present "$VAR" <label>
# <pattern>` / `_absent "$VAR" <label> <pattern>` and captures the file
# variable name (`VAR`) actually passed at THIS call site - see
# `extract_literal_assertions`'s per-call-site scoping.
_SHELL_CALL_FILE_ARG_RE = re.compile(r'^\s*_(?:absent|present)\s+"\$(\w+)"')


def _target_occurrences(target_text: str, line_starts: list[int], literal: str) -> list[int]:
    """Exact substring occurrences of `literal` in the live target text."""
    lines = []
    idx = target_text.find(literal)
    while idx != -1:
        lines.append(offset_to_line(line_starts, idx))
        idx = target_text.find(literal, idx + 1)
    return lines


def _target_regex_occurrences(target_lines: list[str], pattern: str) -> list[int] | None:
    """Match `pattern` as a case-insensitive ERE against each target line -
    mirroring `grep -qiE`'s own semantics, exactly like
    `_count_pattern_in_target` already does correctly for shell floor
    patterns below. Returns None when `pattern` fails to compile; the
    caller must treat that as unresolved, never as "no matches"."""
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None
    return [i for i, line in enumerate(target_lines, start=1) if compiled.search(line)]


def _resolve_literal_in_target(
    target_text: str, target_lines: list[str], line_starts: list[int], literal: str
) -> tuple[list[int], str | None]:
    """Resolve `literal` against the live target text. Tries an exact
    substring match first (the common case: a plain quoted phrase); if
    that finds nothing, `literal` may be an ERE pattern lifted verbatim
    from a `grep -qiE '<pattern>'` call site - a quoted regex and a quoted
    plain-text literal are syntactically indistinguishable at extraction
    time (both are just a quoted string in source), so both get extracted
    the same way and are only told apart HERE, by which resolution
    strategy actually finds the content. A naive literal-substring-only
    match silently drops any pattern containing a regex metacharacter
    (`.`, `\\+`, `|`, ...) that has zero literal occurrences even though
    the live gate (`grep -qiE`) matches it fine. Returns
    (occurrence_lines, method) where method is "literal", "regex", or None
    (could not resolve either way - the caller must emit UNRESOLVED, never
    silently drop, per this tool's entire reason to exist)."""
    occ = _target_occurrences(target_text, line_starts, literal)
    if occ:
        return occ, "literal"
    regex_occ = _target_regex_occurrences(target_lines, literal)
    if regex_occ:
        return regex_occ, "regex"
    return [], None


# Kinds whose target-directed literal is a genuine mechanical assertion
# (matched against the target's content by a live gate) rather than
# incidental descriptive text.
_PATTERN_CHECK_KINDS = {"literal_absent", "literal_presence", "literal_count"}


def extract_literal_assertions(
    consumer_rel: str,
    consumer_text: str,
    target_text: str,
    target_lines: list[str],
    line_starts: list[int],
    ranges: list[MoveRange],
    target_rel: str,
) -> tuple[list[Assertion], list[Unresolved]]:
    out: list[Assertion] = []
    unresolved: list[Unresolved] = []
    # A consumer's `_present`/`_absent` calls are only actually checking
    # THIS target when they read from a shell variable whose assignment
    # resolves to `target_rel` (e.g. `SPEC="$REPO_DIR/.../
    # ds-implement-ticket.md"`) - some `bin/tests/*.sh` files that are
    # discovered as consumers (they mention the target file's path
    # somewhere, e.g. in a comment) run their entire `_present`/`_absent`
    # suite against a DIFFERENT spec file (verified: test_ticket_rework_
    # triage_badge.sh and test_ticket_triage_inflight.sh both point `$SPEC`
    # at content/commands/ds-ticket-triage.md, not this target; and
    # test_batch_state_timestamp_field.sh itself has TWO spec variables -
    # `$SPEC` -> this target, `$SPEC2` -> a different reference doc).
    # `path_vars` resolves the file-scoped default (used by the 2-arg
    # `_absent <label> <pattern>` form, whose target file is baked into
    # the helper's own body, not passed per call); `_SHELL_CALL_FILE_ARG_RE`
    # additionally resolves the 3-arg `_present "$VAR" <label> <pattern>`
    # form PER CALL SITE, since a file with two spec variables can mix
    # target-directed and non-target-directed calls in the same file.
    path_vars = _build_shell_path_vars(consumer_text, target_rel)
    for _lineno, logical in join_shell_continuations(consumer_text):
        literals = _literals_in_line(logical)
        if not literals:
            continue
        kind = _classify_line(logical)
        last_idx = len(literals) - 1
        call_arg_m = _SHELL_CALL_FILE_ARG_RE.match(logical)
        if call_arg_m:
            # Explicit 3-arg form: trust the actual variable this call
            # site passed, even if some OTHER variable in the file also
            # resolves to the target.
            is_call_target_scoped = path_vars.get(call_arg_m.group(1)) == target_rel
        else:
            # 2-arg form (or unrecognized shape): fall back to "does this
            # file have a variable resolving to the target at all".
            is_call_target_scoped = bool(path_vars)
        is_shell_call = _is_shell_call_line(logical) and is_call_target_scoped
        for idx, lit in enumerate(literals):
            # Only the LAST quoted literal on a pattern-check line (the
            # `<pattern>` slot of `_present <file> <label> <pattern>` /
            # `_absent <label> <pattern>` / `x.count("...")`) is the actual
            # payload a live gate matches against the target - a preceding
            # LABEL argument is documentation, never itself required to
            # appear verbatim in the target's prose. Only that slot gets
            # the ERE-fallback + fail-loud treatment; escalating every
            # quoted string on the line flooded the report with false
            # UNRESOLVED rows for ordinary label/message text that was
            # never meant to match the target (confirmed: matching a
            # single-file test consumer against this file's OWN internal
            # string literals produced dozens of spurious rows before this
            # narrowing).
            #
            # This MUST be computed before the `_is_meaningful_literal`
            # filter below, and the filter must be skipped for a pattern
            # slot: `_is_meaningful_literal` exists to drop incidental
            # short-token noise, but a pattern slot is by construction a
            # deliberate assertion payload (e.g. `'mark-blocked-and-
            # continue'`, `'fail-open'`, `'<ISO8601>'`) regardless of shape.
            # Filtering it first silently dropped these with no UNRESOLVED
            # row - the identical silent-drop class the ERE-fallback fix
            # above exists to prevent, one filter earlier in this function.
            is_pattern_slot = kind in _PATTERN_CHECK_KINDS and idx == last_idx and is_shell_call
            if not is_pattern_slot and not _is_meaningful_literal(lit):
                continue
            # Skip pure noise: path literals that merely re-cite the target
            # path itself carry no content assertion.
            if lit in (DEFAULT_TARGET, Path(DEFAULT_TARGET).name):
                continue
            if is_pattern_slot:
                occ, method = _resolve_literal_in_target(target_text, target_lines, line_starts, lit)
            else:
                occ = _target_occurrences(target_text, line_starts, lit)
                method = "literal" if occ else None
            if kind == "literal_absent":
                if not occ:
                    # Genuinely resolved: neither a literal substring nor
                    # an ERE match is present in the target, so there is
                    # nothing for a move to break - a legitimate "absent"
                    # answer, not an unresolved one.
                    continue
                out.append(
                    Assertion(
                        consumer=consumer_rel,
                        kind=kind,
                        detail=f"asserts {lit!r} is ABSENT from target"
                        + (
                            " (currently matches via ERE, independent of this move)"
                            if method == "regex"
                            else ""
                        ),
                        resolved=True,
                        breaks=False,
                        lines=occ,
                        note="absence assertions cannot be broken by a move away from the target",
                    )
                )
                continue
            if not occ:
                if is_pattern_slot:
                    # Fail loud: neither literal-substring nor ERE
                    # resolution found this pattern in the target. Never
                    # silently drop - a dropped assertion inside a
                    # consumer that yielded some OTHER resolved assertion
                    # is invisible to every other section of the report.
                    unresolved.append(
                        Unresolved(
                            consumer=consumer_rel,
                            detail=f"{kind}: {lit!r} not found in target as a literal substring or "
                            "as a case-insensitive ERE match - could not mechanically resolve",
                        )
                    )
                continue
            moved = [ln for ln in occ if range_for_line(ranges, ln) is not None]
            method_note = " (resolved via ERE match, not literal substring)" if method == "regex" else ""
            if kind == "comment_reference":
                out.append(
                    Assertion(
                        consumer=consumer_rel,
                        kind=kind,
                        detail=f"comment cites {lit!r}{method_note}",
                        resolved=True,
                        breaks=False,
                        lines=occ,
                        note="informational only; goes stale but does not break a gate",
                    )
                )
            elif kind == "literal_count":
                out.append(
                    Assertion(
                        consumer=consumer_rel,
                        kind=kind,
                        detail=(
                            f"counts occurrences of {lit!r} in target ({len(occ)} total, "
                            f"{len(moved)} in a move range){method_note}"
                        ),
                        resolved=True,
                        breaks=bool(moved),
                        lines=occ,
                        note="moving any occurrence changes the count this assertion pins" if moved else "",
                    )
                )
            else:  # literal_presence / literal_reference (treated as load-bearing)
                out.append(
                    Assertion(
                        consumer=consumer_rel,
                        kind="literal_presence",
                        detail=f"asserts {lit!r} is present in target{method_note}",
                        resolved=True,
                        breaks=bool(moved),
                        lines=occ,
                        note=f"moves to {range_for_line(ranges, moved[0]).dest}" if moved else "",
                    )
                )
    return out, unresolved


# ---------------------------------------------------------------------------
# Heading-block assertions (HEADING = "..." + _extract_block()-style readers)
# ---------------------------------------------------------------------------

_HEADING_VAR_RE = re.compile(r'^\s*(?:HEADING|SECTION_HEADING)\s*=\s*["\'](#{1,6}\s[^"\']+)["\']')


def extract_heading_block_assertions(
    consumer_rel: str,
    consumer_text: str,
    headings: list[Heading],
    ranges: list[MoveRange],
) -> list[Assertion]:
    out: list[Assertion] = []
    if "_extract_block" not in consumer_text and "HEADING" not in consumer_text:
        return out
    for line in consumer_text.split("\n"):
        m = _HEADING_VAR_RE.match(line)
        if not m:
            continue
        heading_text = m.group(1)
        match = next((h for h in headings if h.text == heading_text), None)
        if match is None:
            out.append(
                Assertion(
                    consumer=consumer_rel,
                    kind="heading_block",
                    detail=f"HEADING={heading_text!r} does not match any live heading",
                    resolved=False,
                    breaks=True,
                    note="heading not found in target - already broken independent of this move",
                )
            )
            continue
        overlap = any_range_overlaps(ranges, match.line, match.end_line)
        out.append(
            Assertion(
                consumer=consumer_rel,
                kind="heading_block",
                detail=(
                    f"_extract_block-style reader anchors on {heading_text!r} "
                    f"spanning target lines {match.line}-{match.end_line}"
                ),
                resolved=True,
                breaks=overlap is not None,
                lines=[match.line, match.end_line],
                note=(
                    f"heading block overlaps proposed move to {overlap.dest} "
                    f"({overlap.start}-{overlap.end}) - block extraction would "
                    "no longer find this content contiguous in the target file"
                    if overlap
                    else ""
                ),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Python regex-pattern assertions (re.compile(...) constant-folded via ast)
# ---------------------------------------------------------------------------


def _eval_str_expr(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _eval_str_expr(node.left)
        right = _eval_str_expr(node.right)
        if left is not None and right is not None:
            return left + right
    return None


# `re.compile`'s own flag constants (the module-level names, plus their
# single-letter aliases) - resolved from an `ast.Attribute` like
# `re.IGNORECASE` at a `re.compile(pattern, <flags-expr>)` call site.
# Combinations via `|` (`re.IGNORECASE | re.DOTALL`) are resolved
# recursively through the `ast.BinOp`/`ast.BitOr` branch below.
_RE_FLAG_NAMES = {
    "IGNORECASE": re.IGNORECASE,
    "I": re.IGNORECASE,
    "MULTILINE": re.MULTILINE,
    "M": re.MULTILINE,
    "DOTALL": re.DOTALL,
    "S": re.DOTALL,
    "VERBOSE": re.VERBOSE,
    "X": re.VERBOSE,
    "ASCII": re.ASCII,
    "A": re.ASCII,
    "UNICODE": re.UNICODE,
    "U": re.UNICODE,
    "LOCALE": re.LOCALE,
    "L": re.LOCALE,
}


def _eval_flags_expr(node) -> int | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "re":
        return _RE_FLAG_NAMES.get(node.attr)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _eval_flags_expr(node.left)
        right = _eval_flags_expr(node.right)
        if left is not None and right is not None:
            return left | right
    return None


def extract_python_regex_patterns(consumer_text: str) -> dict[str, tuple[str, int]]:
    """Returns {name: (pattern, flags)}. `flags` reads the actual second
    positional arg or `flags=` keyword of the `re.compile(...)` call site -
    a naive re-compile with no flags silently discards `re.IGNORECASE`/
    `re.DOTALL`/`re.MULTILINE` the consumer actually used, which can make a
    pattern that genuinely matches the live target (case-insensitively, or
    across a newline) read as a false non-match here."""
    try:
        tree = ast.parse(consumer_text)
    except SyntaxError:
        return {}
    out: dict[str, tuple[str, int]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        is_compile = (
            isinstance(func, ast.Attribute)
            and func.attr == "compile"
            and isinstance(func.value, ast.Name)
            and func.value.id == "re"
        )
        if not is_compile or not call.args:
            continue
        pat = _eval_str_expr(call.args[0])
        if pat is None:
            continue
        flags = 0
        if len(call.args) >= 2:
            f = _eval_flags_expr(call.args[1])
            if f is not None:
                flags = f
        for kw in call.keywords:
            if kw.arg == "flags":
                f = _eval_flags_expr(kw.value)
                if f is not None:
                    flags = f
        for t in node.targets:
            if isinstance(t, ast.Name):
                out[t.id] = (pat, flags)
    return out


def extract_regex_assertions(
    consumer_rel: str,
    consumer_text: str,
    target_text: str,
    line_starts: list[int],
    ranges: list[MoveRange],
) -> tuple[list[Assertion], list[Unresolved]]:
    assertions: list[Assertion] = []
    unresolved: list[Unresolved] = []
    if not consumer_rel.endswith(".py"):
        return assertions, unresolved
    patterns = extract_python_regex_patterns(consumer_text)
    for name, (pat, flags) in patterns.items():
        # Only meaningful if the compiled name is actually referenced again
        # (search/finditer/match) - a defined-but-unused pattern is noise.
        if not re.search(rf"\b{re.escape(name)}\s*\.\s*(search|finditer|match)\b", consumer_text):
            continue
        try:
            compiled = re.compile(pat, flags)
        except re.error as e:
            unresolved.append(
                Unresolved(consumer=consumer_rel, detail=f"{name}: pattern failed to compile: {e}")
            )
            continue
        # Match against the WHOLE target text, not per-line: a consumer
        # searches its own whole-text string (this is exactly what the
        # consumer's own `.search()`/`.finditer()` call does), and a
        # per-line scan misses any pattern that can span a newline (e.g.
        # `[^.]{0,80}` matches `\n`) - a deletion seam created by the move
        # can create a NEW cross-line match post-move that a per-line scan
        # would never see either way, silently converting a real break
        # into a false "zero matches, cannot break" resolution below.
        matches = sorted({offset_to_line(line_starts, m.start()) for m in compiled.finditer(target_text)})
        moved = [ln for ln in matches if range_for_line(ranges, ln) is not None]
        if not matches:
            # Zero occurrences in the PRE-move target, under either
            # polarity, is mechanically resolvable as non-breaking: the
            # move only relocates existing target lines verbatim into a
            # destination file, it cannot conjure a match into existence
            # on content that already matches nothing. A must-match
            # assertion with zero matches is already failing independent
            # of any move (a pre-existing defect out of this tool's
            # scope); a must-NOT-match assertion with zero matches is
            # correctly satisfied and stays that way post-move either
            # way. Report it resolved, not UNRESOLVED - polarity still
            # can't be confirmed mechanically, but it provably doesn't
            # change what this move does to the assertion's outcome.
            assertions.append(
                Assertion(
                    consumer=consumer_rel,
                    kind="regex_pattern",
                    detail=(
                        f"regex assertion {name!r} (pattern={pat!r}) matches ZERO "
                        "lines in the pre-move target"
                    ),
                    resolved=True,
                    breaks=False,
                    lines=[],
                    note=(
                        "polarity (must-match vs must-NOT-match) not mechanically "
                        "confirmed, but zero pre-move matches means this move "
                        "cannot change the assertion's outcome either way"
                    ),
                )
            )
            continue
        # Polarity (should-match vs should-not-match) is not mechanically
        # derivable from the compiled pattern alone - report as UNRESOLVED
        # per the "fail loud" design constraint rather than guessing.
        unresolved.append(
            Unresolved(
                consumer=consumer_rel,
                detail=(
                    f"regex assertion {name!r} (pattern={pat!r}) currently matches "
                    f"target lines {matches}"
                    + (
                        f"; {len(moved)} of those line(s) fall inside a proposed "
                        f"move range {moved} - polarity (must-match vs must-NOT-"
                        "match) could not be determined mechanically, verify by hand"
                        if moved
                        else " (none inside a proposed move range - low risk, but "
                        "polarity still not mechanically confirmed)"
                    )
                ),
            )
        )
    return assertions, unresolved


# ---------------------------------------------------------------------------
# Shell grep -c floor assertions: single "-ge N" style and heredoc tables
# ---------------------------------------------------------------------------

# Deliberately NOT `$`-anchored: `VAR="$(git grep -c ...)"` is frequently
# followed by a trailing statement on the same physical line (e.g.
# `G6="$(...)"; [ -n "$G6" ] || G6=0` in test_tasks_jsonl_fold.sh) rather
# than ending the line. `(.*?)` is non-greedy so it stops at the FIRST `)`
# it meets, which is the assignment's own closing paren for every floor
# pattern in this repo (none of the `git grep -c` patterns extracted here
# contain a literal `)` themselves) - a greedy `.*` would instead run to
# the LAST `)` on the line, which can land past the assignment entirely
# once a trailing statement is present.
_VAR_ASSIGN_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)="?\$\((.*?)\)"?')
_GREP_C_RE = re.compile(r"git grep -c([iE]*)\s+['\"]([^'\"]+)['\"].*?--\s+(\S+)")
_FLOOR_RE = re.compile(r'\[\s*"\$(\w+)"\s*-(ge|gt|le|lt|eq)\s+"?(\d+)"?\s*\]')
_PATH_VAR_RE = re.compile(
    r'^\s*([A-Za-z_][A-Za-z0-9_]*)=\$?\{?"?\$?(?:REPO_DIR|REPO_ROOT)?/?["\']?([\w./-]*content/commands/[\w.-]+\.md)'
)
_PY_PATH_VAR_RE = re.compile(
    r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*REPO_ROOT\s*/\s*"([\w.-]+)"\s*/\s*"([\w.-]+)"\s*/\s*"([\w.-]+)"'
)


def _build_shell_path_vars(consumer_text: str, target_rel: str) -> dict[str, str]:
    varmap: dict[str, str] = {}
    for line in consumer_text.split("\n"):
        m = _PATH_VAR_RE.match(line)
        if m and m.group(2).endswith(Path(target_rel).name):
            varmap[m.group(1)] = target_rel
        m2 = _PY_PATH_VAR_RE.match(line)
        if m2:
            candidate = "/".join([m2.group(2), m2.group(3), m2.group(4)])
            if candidate == target_rel:
                varmap[m2.group(1)] = target_rel
    return varmap


def _count_pattern_in_target(
    target_text: str, line_starts: list[int], pattern: str, ci: bool, ranges: list[MoveRange]
) -> tuple[int, int]:
    """Count *matching lines* of `pattern` (an ERE, from `git grep -c[iE]`)
    in the live target text using an actual regex compile - NOT a naive
    literal substring match, which silently miscounts any pattern
    containing a backslash-escaped metacharacter (e.g. `tasks\\.jsonl`
    would find zero literal '\\.' sequences in prose that only ever
    contains a plain '.'). `git grep -c` counts MATCHING LINES, not raw
    occurrences (verified: one target line here contains the pinned phrase
    twice, and `git grep -ci` still counts it once) - this counts lines to
    stay faithful to that semantic, not `finditer()` occurrences. Returns
    (count_before, count_moved)."""
    try:
        flags = re.IGNORECASE if ci else 0
        compiled = re.compile(pattern, flags)
    except re.error:
        compiled = None
    count_before = 0
    moved = 0
    for i, line in enumerate(target_text.split("\n"), start=1):
        hit = compiled.search(line) if compiled else ((pattern.lower() in line.lower()) if ci else (pattern in line))
        if not hit:
            continue
        count_before += 1
        if range_for_line(ranges, i) is not None:
            moved += 1
    return count_before, moved


def extract_shell_floor_assertions(
    consumer_rel: str,
    consumer_text: str,
    target_text: str,
    target_lines: list[str],
    ranges: list[MoveRange],
    target_rel: str,
) -> list[Assertion]:
    if not consumer_rel.endswith(".sh"):
        return []
    out: list[Assertion] = []
    varmap = _build_shell_path_vars(consumer_text, target_rel)
    lines = consumer_text.split("\n")

    # (a) simple VAR="$(git grep -c ... -- <path-or-var>)" .. [ "$VAR" -geN N ]
    for i, line in enumerate(lines):
        vm = _VAR_ASSIGN_RE.match(line)
        if not vm:
            continue
        var, inner = vm.group(1), vm.group(2)
        gm = _GREP_C_RE.search(inner)
        if not gm:
            continue
        flags, pattern, file_tok = gm.group(1), gm.group(2), gm.group(3)
        # Strip the quoting AND the `$`/`${...}` variable-reference syntax
        # (e.g. `"$DIT"` -> `DIT`) - `varmap`'s keys are the bare variable
        # names `_build_shell_path_vars` extracted from each assignment
        # (`DIT=content/commands/...`), never dollar-prefixed. Without
        # this, `varmap.get("$DIT")` always misses even when `DIT` is
        # correctly resolved to the target, silently discarding the floor.
        file_tok = file_tok.strip('"').strip("'").lstrip("$").strip("{}")
        resolved_path = varmap.get(file_tok, file_tok if file_tok == target_rel else None)
        if resolved_path != target_rel:
            continue
        # find a floor referencing $var within the next few lines
        floor = None
        for j in range(i, min(i + 6, len(lines))):
            fm = _FLOOR_RE.search(lines[j])
            if fm and fm.group(1) == var:
                floor = (fm.group(2), int(fm.group(3)))
                break
        if floor is None:
            continue
        op, n = floor
        ci = "i" in flags
        line_starts = build_line_starts(target_text)
        count_before, moved_count = _count_pattern_in_target(target_text, line_starts, pattern, ci, ranges)
        count_after = count_before - moved_count
        clears = {
            "ge": count_after >= n,
            "gt": count_after > n,
            "le": count_after <= n,
            "lt": count_after < n,
            "eq": count_after == n,
        }[op]
        out.append(
            Assertion(
                consumer=consumer_rel,
                kind="grep_count_floor",
                detail=(
                    f"`{var}` = git grep -c{flags} '{pattern}' -- {file_tok}: "
                    f"before={count_before}, moved={moved_count}, after={count_after}, "
                    f"floor `-{op} {n}`"
                ),
                resolved=True,
                breaks=not clears,
                note="floor no longer clears after move" if not clears else "floor still clears (verify it also stays inside any relevant SCANNED SET)",
            )
        )

    # (b) heredoc per-file floor table, e.g. FOLDSPEC in test_tasks_jsonl_fold.sh
    heredoc_re = re.compile(r"<<'(\w+)'\n(.*?)\n\1", re.DOTALL)
    for hm in heredoc_re.finditer(consumer_text):
        tag, body = hm.group(1), hm.group(2)
        # locate the grep -c pattern used inside the loop feeding this heredoc
        # (search the ~15 lines preceding the heredoc opener)
        window_start = max(0, hm.start() - 1500)
        window = consumer_text[window_start:hm.start()]
        # Take the LAST grep -c call before the heredoc opener, not the
        # first: the window can span an earlier, unrelated grep -c call
        # (e.g. a preceding stage's floor) that has nothing to do with the
        # loop that actually feeds this heredoc.
        gm_all = list(re.finditer(r"git grep -c([iE]*)\s+['\"]([^'\"]+)['\"]", window))
        if not gm_all:
            continue
        gm = gm_all[-1]
        flags, pattern = gm.group(1), gm.group(2)
        ci = "i" in flags
        line_starts = build_line_starts(target_text)
        for row in body.split("\n"):
            row = row.strip()
            if not row or ":" not in row:
                continue
            path, _, floor_s = row.rpartition(":")
            if path != target_rel or not floor_s.isdigit():
                continue
            n = int(floor_s)
            count_before, moved_count = _count_pattern_in_target(target_text, line_starts, pattern, ci, ranges)
            count_after = count_before - moved_count
            clears = count_after >= n
            out.append(
                Assertion(
                    consumer=consumer_rel,
                    kind="grep_count_floor",
                    detail=(
                        f"heredoc `{tag}` per-file floor: pattern '{pattern}' in {path}: "
                        f"before={count_before}, moved={moved_count}, after={count_after}, floor >= {n}"
                    ),
                    resolved=True,
                    breaks=not clears,
                    note="floor no longer clears after move" if not clears else "",
                )
            )
    return out


# ---------------------------------------------------------------------------
# Scanned-set inference (single-file hardcoded FILE= vs multi-file content/**)
# ---------------------------------------------------------------------------

_FILE_LITERAL_ASSIGN_RE = re.compile(
    r'^\s*(?:FILE|SPEC|DIT|MD_PATH|CANONICAL_PATH|TARGET)\w*\s*=\s*["\']?content/commands/[\w.-]+\.md'
)


def infer_scanned_set(
    consumer_rel: str, consumer_text: str, target_rel: str, ranges: list[MoveRange]
) -> ScannedSetFinding | None:
    has_single_file_var = any(
        _FILE_LITERAL_ASSIGN_RE.match(line) for line in consumer_text.split("\n")
    )
    has_content_dirscope = bool(
        re.search(r"--\s+content\b", consumer_text)
        or re.search(r'\(REPO_ROOT\s*/\s*"content"\)\.rglob', consumer_text)
        or re.search(r'\.glob\("content/', consumer_text)
    )
    dest_dirs = sorted({Path(r.dest).parent.as_posix() for r in ranges})
    if has_content_dirscope and not has_single_file_var:
        return ScannedSetFinding(
            consumer=consumer_rel,
            scope="multi-file-content",
            detail=f"scans all of content/** (git grep or rglob over content/) - "
            f"destinations {dest_dirs} remain inside this scanned set",
            leaves_scanned_set=False,
        )
    if has_single_file_var:
        return ScannedSetFinding(
            consumer=consumer_rel,
            scope="single-file",
            detail=(
                f"hardcodes a single-file scan of {target_rel} with no "
                f"content/**-wide fallback - moved content lands in "
                f"{dest_dirs}, which this consumer never reads"
            ),
            leaves_scanned_set=True,
        )
    return None


# ---------------------------------------------------------------------------
# Analysis driver
# ---------------------------------------------------------------------------


def analyze(repo_root: Path, target_rel: str, ranges: list[MoveRange]) -> Report:
    target_path = repo_root / target_rel
    if not target_path.is_file():
        raise FileNotFoundError(f"target file not found: {target_path}")
    target_text = target_path.read_text(encoding="utf-8")
    target_lines_raw = target_text.split("\n")
    line_starts = build_line_starts(target_text)
    headings = fence_aware_headings(target_lines_raw)

    consumers = discover_consumers(repo_root, target_rel)
    report = Report(target=target_rel, ranges=ranges, consumers=consumers)

    if not consumers:
        # Non-vacuity guard: a target file this tool is ever pointed at is
        # never actually consumer-free in this repo. Zero discovered
        # consumers means the discovery step itself broke (bad pathspec,
        # git not on PATH, wrong cwd) - report it loudly rather than
        # silently returning an empty-therefore-"OK" report, which is
        # exactly the failure class this tool exists to prevent.
        report.unresolved.append(
            Unresolved(
                consumer="<discovery>",
                detail="git grep discovery found ZERO consumers referencing the "
                "target file - this is almost certainly a broken discovery step "
                "(bad git invocation, wrong cwd, missing git on PATH), not a "
                "target file nobody reads. Refusing to report OK.",
            )
        )
        return report

    if not any(_is_checked_consumer(c) for c in consumers):
        # Second non-vacuity guard, one level down from the one above: the
        # first guard only fires when discovery finds literally nothing.
        # It does NOT fire when discovery finds plenty of doc/prose
        # consumers but zero *checked* (executable-gate) consumers - every
        # non-checked file `continue`s past the `found_any` machinery
        # below without ever touching it, so a `bin/tests/` rename, a gate
        # moving under `scripts/verify-*.sh`, or any other drift in
        # `_is_checked_consumer`/`SEARCH_DIRS` silently produces a report
        # with zero BREAKING rows and zero UNRESOLVED entries - `Verdict:
        # OK`, having asserted nothing. Report it loudly instead.
        report.unresolved.append(
            Unresolved(
                consumer="<discovery>",
                detail=(
                    f"discovery found {len(consumers)} consumer(s) referencing the "
                    "target file, but ZERO of them match the checked-consumer "
                    "patterns (bin/tests/**, hooks/tests/**, scripts/check-*.sh) - "
                    "this is almost certainly _is_checked_consumer()/SEARCH_DIRS "
                    "drifting out from under a renamed or relocated executable "
                    "gate, not a target file with no runnable consumers left. "
                    "Refusing to report OK."
                ),
            )
        )

    for rel in consumers:
        path = repo_root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            report.unresolved.append(Unresolved(consumer=rel, detail=f"could not read file: {e}"))
            continue

        if not _is_checked_consumer(rel):
            # Doc/prose consumer: not a runnable gate. Only load-bearing check
            # is "does it cite one of the moving headings by name" (a real,
            # if lightweight, doc-sync signal) - never arbitrary literal
            # matching, which produced hundreds of false positives on plain
            # English words shared with the target's content.
            report.doc_consumers.append(rel)
            for h in headings:
                r = any_range_overlaps(ranges, h.line, h.end_line)
                if r is None:
                    continue
                heading_title = h.text.lstrip("#").strip()
                if heading_title and heading_title in text:
                    report.doc_citations.append(
                        DocCitation(consumer=rel, heading=h.text, dest=r.dest)
                    )
            continue

        found_any = False

        lit_assertions, lit_unresolved = extract_literal_assertions(
            rel, text, target_text, target_lines_raw, line_starts, ranges, target_rel
        )
        report.assertions.extend(lit_assertions)
        report.unresolved.extend(lit_unresolved)
        found_any = found_any or bool(lit_assertions) or bool(lit_unresolved)

        hb_assertions = extract_heading_block_assertions(rel, text, headings, ranges)
        report.assertions.extend(hb_assertions)
        found_any = found_any or bool(hb_assertions)

        regex_assertions, regex_unresolved = extract_regex_assertions(rel, text, target_text, line_starts, ranges)
        report.assertions.extend(regex_assertions)
        report.unresolved.extend(regex_unresolved)
        found_any = found_any or bool(regex_assertions) or bool(regex_unresolved)

        floor_assertions = extract_shell_floor_assertions(
            rel, text, target_text, target_lines_raw, ranges, target_rel
        )
        report.assertions.extend(floor_assertions)
        found_any = found_any or bool(floor_assertions)

        scanned = infer_scanned_set(rel, text, target_rel, ranges)
        if scanned is not None:
            report.scanned_sets.append(scanned)

        if not found_any:
            report.unresolved.append(
                Unresolved(
                    consumer=rel,
                    detail="references the target file but no assertion against its "
                    "content could be extracted - manual review required before this "
                    "consumer can be certified safe (checked-consumer set: bin/tests/**, "
                    "hooks/tests/**, scripts/check-*.sh)",
                )
            )

    return report


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_report(report: Report) -> str:
    out = []
    out.append(f"# Prose move impact report: {report.target}")
    out.append("")
    out.append("## Proposed move ranges")
    for r in report.ranges:
        out.append(f"  {r.start:>5}-{r.end:<5} -> {r.dest}")
    out.append("")
    out.append(f"## Consumers discovered ({len(report.consumers)})")
    for c in report.consumers:
        out.append(f"  - {c}")
    out.append("")

    breaking = [a for a in report.assertions if a.breaks]
    passing = [a for a in report.assertions if a.resolved and not a.breaks]

    out.append(f"## BREAKING assertions ({len(breaking)})")
    for a in breaking:
        out.append(f"  [{a.kind}] {a.consumer}: {a.detail}")
        if a.note:
            out.append(f"      note: {a.note}")
    out.append("")

    out.append(f"## Passing assertions ({len(passing)})")
    for a in passing:
        out.append(f"  [{a.kind}] {a.consumer}: {a.detail}")
    out.append("")

    out.append(f"## Scanned-set findings ({len(report.scanned_sets)})")
    for s in report.scanned_sets:
        flag = "LEAVES SCANNED SET" if s.leaves_scanned_set else "stays in scanned set"
        out.append(f"  [{s.scope}] {s.consumer}: {s.detail} -- {flag}")
    out.append("")

    out.append(
        f"## Doc/prose consumers ({len(report.doc_consumers)}) - not mechanically "
        "gated; docs-currency review only"
    )
    for c in report.doc_consumers:
        out.append(f"  - {c}")
    out.append("")

    out.append(
        f"## Doc citations of a moving heading ({len(report.doc_citations)}) - "
        "these docs name a section that is moving; update the cross-reference"
    )
    for dc in report.doc_citations:
        out.append(f"  {dc.consumer}: cites {dc.heading!r} -> moving to {dc.dest}")
    out.append("")

    out.append(f"## UNRESOLVED ({len(report.unresolved)})")
    for u in report.unresolved:
        loc = f":{u.line}" if u.line else ""
        out.append(f"  {u.consumer}{loc}: {u.detail}")
    out.append("")

    out.append(f"## Verdict: {'OK' if report.ok else 'FAIL'}")
    if not report.ok:
        out.append(
            "One or more assertions break, or one or more consumers/assertions "
            "could not be resolved. Nothing here is a silent pass."
        )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_range_flag(s: str) -> MoveRange:
    parts = s.split(":", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(f"--range must be START:END:DEST, got {s!r}")
    start_s, end_s, dest = parts
    return MoveRange(start=int(start_s), end=int(end_s), dest=dest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--range", action="append", dest="ranges", type=parse_range_flag, default=[])
    parser.add_argument("--config", help="JSON file: {\"target\": str, \"ranges\": [{\"start\",\"end\",\"dest\"}]}")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of the text report")
    args = parser.parse_args(argv)

    target = args.target
    ranges = list(args.ranges)
    if args.config:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        target = cfg.get("target", target)
        for r in cfg.get("ranges", []):
            ranges.append(MoveRange(start=int(r["start"]), end=int(r["end"]), dest=r["dest"]))

    if not ranges:
        parser.error("at least one --range or a --config with ranges is required")

    repo_root = Path(args.repo_root).resolve()
    report = analyze(repo_root, target, ranges)

    if args.json:
        print(
            json.dumps(
                {
                    "target": report.target,
                    "ok": report.ok,
                    "consumers": report.consumers,
                    "assertions": [
                        {
                            "consumer": a.consumer,
                            "kind": a.kind,
                            "detail": a.detail,
                            "resolved": a.resolved,
                            "breaks": a.breaks,
                            "lines": a.lines,
                            "note": a.note,
                        }
                        for a in report.assertions
                    ],
                    "scanned_sets": [
                        {
                            "consumer": s.consumer,
                            "scope": s.scope,
                            "detail": s.detail,
                            "leaves_scanned_set": s.leaves_scanned_set,
                        }
                        for s in report.scanned_sets
                    ],
                    "unresolved": [
                        {"consumer": u.consumer, "detail": u.detail, "line": u.line}
                        for u in report.unresolved
                    ],
                    "doc_consumers": report.doc_consumers,
                    "doc_citations": [
                        {"consumer": dc.consumer, "heading": dc.heading, "dest": dc.dest}
                        for dc in report.doc_citations
                    ],
                },
                indent=2,
            )
        )
    else:
        print(render_report(report))

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
