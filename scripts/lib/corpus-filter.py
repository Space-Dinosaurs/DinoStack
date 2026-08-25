#!/usr/bin/env python3
"""
Purpose: Line-filter methodology section files by "corpus" marker so that
         build-methodology.sh can assemble a smaller (minimal/medium) or full
         methodology body from the same content/sections/*.md sources,
         deferring low-frequency-trigger content behind a generated pointer
         block instead of loading it every session.

Public API: filter_text(text, corpus, source_name, full_text_name="METHODOLOGY.md",
            file_label="<stdin>") -> str
            CORPORA_FILE_RE, CORPUS_BEGIN_RE, CORPUS_END_RE (module-level
            compiled regexes - the single source of truth for marker syntax;
            other consumers, notably check-corpus-coverage.py, import these
            rather than re-deriving them).
            CorpusFilterError(Exception) - raised on malformed markers; str(e)
            names the offending file:line.
            CLI: `python3 scripts/lib/corpus-filter.py --corpus <minimal|
            medium|full> --source-name <basename> [--full-text-name
            <basename>]` reads the full source text from stdin and writes the
            filtered text to stdout. This is the file interface
            build-methodology.sh's assemble() uses: one subprocess invocation
            per section file, piping that file's bytes in and capturing
            filtered bytes out - there is no separate file-path mode.

Marker syntax (all stripped from output at every corpus - see "Why marker
lines are always stripped" below):
  <!-- corpora: minimal medium full -->
      File-level posture declaration. Informational only for the filter
      (it does not gate anything by itself); its purpose is to satisfy
      check-corpus-coverage.py's coverage requirement for a file that is not
      internally partitioned. Recognized on any line, not only line 1, but
      intended to appear once, as line 1.
  <!-- corpus:begin <space-separated corpus list> | trigger: <text> -->
  ... content ...
  <!-- corpus:end -->
      Wraps a block that is included in the output only when the active
      corpus is a member of <corpus list>. `trigger: <text>` is MANDATORY
      unless the list is exactly the three tokens "minimal medium full" (in
      which case the block is never excluded and a trigger would be
      meaningless). Nesting a corpus:begin inside another corpus:begin is a
      hard error - the filter has no concept of a compound/inherited posture.

Why marker lines are always stripped: the marker lines themselves are HTML
comments, invisible to a rendered doc but not byte-identical to a build that
predates the markers. The `--corpus full` build is required to be
byte-for-byte identical to the pre-marker build (every corpus list a caller
in this repo actually writes includes "full"), so the filter strips every
marker line unconditionally and passes all *content* lines through at `full`.

Upstream deps: none beyond the Python 3 standard library (re, sys, argparse).

Downstream consumers: scripts/build-methodology.sh (assemble(), one
subprocess call per section file); scripts/check-corpus-coverage.py (imports
the three regexes to validate content/sections/*.md without re-deriving
marker syntax).

Failure modes: raises CorpusFilterError (CLI: prints to stderr, exits 1) on
  - an corpus:end with no open corpus:begin ("unbalanced end")
  - EOF reached with an open corpus:begin ("unbalanced begin")
  - a corpus:begin nested inside another corpus:begin ("nested begin")
  - a corpus:begin whose list contains a token outside {minimal, medium,
    full}, or an empty list, or a duplicate token
  - a corpus:begin whose list is not exactly "minimal medium full" and that
    omits the trigger clause ("missing mandatory trigger")
  Every error names the 1-indexed source line. filter_text() is pure (no I/O,
  no retries needed - re-run on the same input for the same result).

Performance: O(number of lines); single pass, no backtracking beyond the
  three fixed regexes.
"""

from __future__ import annotations

import argparse
import re
import sys

VALID_CORPORA = ("minimal", "medium", "full")
_ALL_CORPORA_TOKENS = frozenset(VALID_CORPORA)

CORPORA_FILE_RE = re.compile(r"^\s*<!--\s*corpora:\s*([\w\s]+?)\s*-->\s*$")
CORPUS_BEGIN_RE = re.compile(
    r"^\s*<!--\s*corpus:begin\s+([\w\s]+?)\s*(?:\|\s*trigger:\s*(.+?)\s*)?-->\s*$"
)
CORPUS_END_RE = re.compile(r"^\s*<!--\s*corpus:end\s*-->\s*$")


class CorpusFilterError(Exception):
    """Raised on malformed corpus markers. str(e) names file:line."""


def _parse_corpus_tokens(raw: str, file_label: str, line_no: int) -> list[str]:
    tokens = raw.split()
    if not tokens:
        raise CorpusFilterError(f"{file_label}:{line_no}: empty corpus list")
    seen: set[str] = set()
    for token in tokens:
        if token not in _ALL_CORPORA_TOKENS:
            raise CorpusFilterError(
                f"{file_label}:{line_no}: unknown corpus token '{token}' "
                f"(expected one of {', '.join(VALID_CORPORA)})"
            )
        if token in seen:
            raise CorpusFilterError(
                f"{file_label}:{line_no}: duplicate corpus token '{token}'"
            )
        seen.add(token)
    return tokens


def filter_text(
    text: str,
    corpus: str,
    source_name: str,
    full_text_name: str = "METHODOLOGY.md",
    file_label: str = "<stdin>",
) -> str:
    """Filter `text` (a content/sections/*.md source) to the given corpus.

    Returns the filtered text, marker lines always stripped, with a generated
    "Deferred at this corpus" pointer block appended when one or more
    corpus:begin blocks were excluded at this corpus. Raises
    CorpusFilterError on malformed markers (see module docstring).
    """
    if corpus not in _ALL_CORPORA_TOKENS:
        raise CorpusFilterError(
            f"{file_label}: unknown active corpus '{corpus}' "
            f"(expected one of {', '.join(VALID_CORPORA)})"
        )

    lines = text.splitlines()
    out: list[str] = []
    triggers: list[str] = []
    seen_triggers: set[str] = set()

    # Stack depth is 0 or 1 (nesting is a hard error); modeled as a stack for
    # clarity at the unbalanced-begin/end error sites.
    stack: list[tuple[int, list[str], str | None]] = []  # (line_no, corpus_list, trigger)

    for idx, line in enumerate(lines, start=1):
        begin_match = CORPUS_BEGIN_RE.match(line)
        end_match = CORPUS_END_RE.match(line) if begin_match is None else None
        corpora_match = (
            CORPORA_FILE_RE.match(line) if begin_match is None and end_match is None else None
        )

        if begin_match is not None:
            if stack:
                raise CorpusFilterError(
                    f"{file_label}:{idx}: nested corpus:begin "
                    f"(already inside a block opened at line {stack[-1][0]})"
                )
            corpus_list = _parse_corpus_tokens(begin_match.group(1), file_label, idx)
            trigger = begin_match.group(2)
            trigger = trigger.strip() if trigger else None
            is_universal = sorted(corpus_list) == sorted(VALID_CORPORA)
            if trigger is None and not is_universal:
                raise CorpusFilterError(
                    f"{file_label}:{idx}: corpus:begin with a partial corpus "
                    f"list ({' '.join(corpus_list)}) is missing the mandatory "
                    "'| trigger: <text>' clause"
                )
            stack.append((idx, corpus_list, trigger))
            continue  # marker line stripped from output

        if end_match is not None:
            if not stack:
                raise CorpusFilterError(
                    f"{file_label}:{idx}: corpus:end with no matching corpus:begin"
                )
            stack.pop()
            continue  # marker line stripped from output

        if corpora_match is not None:
            # File-level posture declaration: informational, always stripped.
            _parse_corpus_tokens(corpora_match.group(1), file_label, idx)
            continue

        if stack:
            _begin_line, corpus_list, trigger = stack[-1]
            if corpus in corpus_list:
                out.append(line)
            elif trigger is not None and trigger not in seen_triggers:
                seen_triggers.add(trigger)
                triggers.append(trigger)
        else:
            out.append(line)

    if stack:
        begin_line, _corpus_list, _trigger = stack[0]
        raise CorpusFilterError(
            f"{file_label}:{begin_line}: unbalanced corpus:begin (no matching corpus:end before EOF)"
        )

    result = "\n".join(out)
    if text.endswith("\n"):
        result += "\n"

    if triggers:
        if result and not result.endswith("\n"):
            result += "\n"
        pointer_lines = [
            "",
            "**Deferred at this corpus.** These rules are in force; their text is not loaded here. Read",
            f"`{full_text_name}` in this skill's own directory (same folder as this file) for the full text -",
            f'search for the section covering "{source_name}".',
        ]
        pointer_lines.extend(f"- {t}" for t in triggers)
        result += "\n".join(pointer_lines) + "\n"

    return result


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Filter a methodology section file to an active corpus."
    )
    parser.add_argument("--corpus", required=True, choices=VALID_CORPORA)
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--full-text-name", default="METHODOLOGY.md")
    return parser


def main(argv: list[str]) -> int:
    args = _build_arg_parser().parse_args(argv)
    text = sys.stdin.read()
    try:
        filtered = filter_text(
            text,
            corpus=args.corpus,
            source_name=args.source_name,
            full_text_name=args.full_text_name,
            file_label=args.source_name,
        )
    except CorpusFilterError as exc:
        print(f"corpus-filter.py: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(filtered)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
