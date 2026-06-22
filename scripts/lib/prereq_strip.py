"""
Purpose: Shared utility that strips the agentic-engineering prerequisite
         blockquote from markdown content before it is written to an adapter
         output file. Centralises the single-source regex so all python-using
         adapters (opencode, openclaw, hermes) call one implementation.

Public API: strip_prereq(content: str) -> str
            Removes the FIRST occurrence of the Prerequisite blockquote.

Upstream deps: re (stdlib only).

Downstream consumers: .opencode/build.sh (agents loop, commands loop),
                      .openclaw/build.sh (commands loop, agents loop),
                      .hermes/build.sh (commands loop, agents loop).

Failure modes: Pure function - raises no exceptions; if the pattern is absent
               the input is returned unchanged. Safe to call on any string.

Performance: ~0 ms per call (single regex pass, no I/O).
"""

import re


def strip_prereq(content: str) -> str:
    """Remove the first Prerequisite blockquote from *content* and return the result.

    Matches the exact pattern used across opencode and openclaw build scripts:
      - optional leading newlines
      - a blockquote line starting with '>' followed by optional whitespace,
        '**Prerequisite:**', and any remaining text on that line
      - optional trailing newlines
    Replaces the whole match with a single newline, preserving surrounding spacing.
    count=1 ensures only the first occurrence is removed (per-file contract).
    """
    return re.sub(r'\n*>\s*\*\*Prerequisite:\*\*[^\n]*\n*', '\n', content, count=1)
