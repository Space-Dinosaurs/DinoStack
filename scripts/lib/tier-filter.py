#!/usr/bin/env python3
# Purpose: Filter a single source `content/sections/NN-*.md` file to emit only
#          content for the requested tier. Three marker forms are recognized:
#             1. File-level `<!-- tiers: t1 t2 ... -->` on the first line -
#                restricts file inclusion to listed tiers. Absent = all tiers.
#             2. Inline block `<!-- tier:begin t1 t2 ... --> ... <!-- tier:end -->`
#                - emits body only if requested tier is in the list. Markers
#                are themselves stripped (each whole-line + its trailing '\n').
#                No nesting is allowed; tier lists are space-separated tier names.
#
# Public API:
#   python3 scripts/lib/tier-filter.py <tier> < input.md
#   tier in {minimal,medium,full}
#
# Upstream deps: python3 (stdlib only).
#
# Downstream consumers: scripts/build-methodology.sh (one invocation per
#                       section file, via stdin/stdout).
#
# Failure modes: invalid tier name -> exit 2. Unknown tier in marker -> exit 3
#                with `<stdin>:N:` prefix on stderr. Unbalanced begin/end,
#                stray end, nested begin -> exit 3 with line number.
#
# Performance: O(line count); one pass.

import re
import sys

VALID_TIERS = {"minimal", "medium", "full"}

TIERS_FILE_RE = re.compile(r"^\s*<!--\s*tiers:\s*([\w\s]+?)\s*-->\s*$")
TIER_BEGIN_RE = re.compile(r"^\s*<!--\s*tier:begin\s+([\w\s]+?)\s*-->\s*$")
TIER_END_RE = re.compile(r"^\s*<!--\s*tier:end\s*-->\s*$")


def parse_tier_list(raw: str, lineno: int | None = None) -> list[str]:
    parts = [t for t in raw.strip().split() if t]
    for t in parts:
        if t not in VALID_TIERS:
            die(f"unknown tier name '{t}'", lineno=lineno)
    return parts


def die(msg: str, lineno: int | None = None) -> None:
    where = f"<stdin>:{lineno}" if lineno is not None else "<stdin>"
    sys.stderr.write(f"tier-filter.py: {where}: {msg}\n")
    sys.exit(3)


def main() -> None:
    if len(sys.argv) != 2:
        sys.stderr.write("tier-filter.py: usage: tier-filter.py <tier>\n")
        sys.exit(2)
    tier = sys.argv[1]
    if tier not in VALID_TIERS:
        sys.stderr.write(f"tier-filter.py: invalid tier '{tier}'\n")
        sys.exit(2)

    raw = sys.stdin.read()
    if not raw:
        return

    # Track whether input ended with a trailing newline so we can restore it
    # verbatim (byte-identical round-trip for FULL output is a hard requirement).
    had_trailing_newline = raw.endswith("\n")
    # We strip a single trailing newline so split() doesn't yield an empty
    # pseudo-line; we re-add it at the end.
    body = raw[:-1] if had_trailing_newline else raw
    lines = body.split("\n")

    # File-level inclusion: only the very first line (line 0) is eligible.
    start_index = 0
    if lines and lines[0].strip():
        m = TIERS_FILE_RE.match(lines[0])
        if m:
            incl_tiers = parse_tier_list(m.group(1), lineno=1)
            if tier not in incl_tiers:
                # File entirely excluded for this tier; emit nothing.
                return
            start_index = 1  # Marker line is dropped from output below.
        # else: first line is content, not a marker - proceed normally.

    out: list[str] = []
    in_block_tiers: list[str] | None = None  # None = outside any block

    for lineno0, line in enumerate(lines):
        lineno = lineno0 + 1  # 1-indexed for error messages
        if lineno0 < start_index:
            continue  # skip file-level marker line

        if in_block_tiers is None:
            m = TIER_BEGIN_RE.match(line)
            if m:
                in_block_tiers = parse_tier_list(m.group(1), lineno=lineno)
                continue
            if TIER_END_RE.match(line):
                die("stray `<!-- tier:end -->` with no matching begin", lineno=lineno)
            # Plain content line - always emit when outside a block.
            out.append(line)
        else:
            if TIER_END_RE.match(line):
                in_block_tiers = None
                continue
            if TIER_BEGIN_RE.match(line):
                die(
                    "nested `<!-- tier:begin -->` not allowed (close the current block with `<!-- tier:end -->` first)",
                    lineno=lineno,
                )
            if tier in in_block_tiers:
                out.append(line)
            # else: drop line (excluded tier)

    if in_block_tiers is not None:
        die("unclosed `<!-- tier:begin -->` block at end of input", lineno=len(lines))

    payload = "\n".join(out)
    if had_trailing_newline:
        payload += "\n"
    sys.stdout.write(payload)


if __name__ == "__main__":
    main()
