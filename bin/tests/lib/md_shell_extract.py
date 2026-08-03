"""
Purpose: Extracts and mutates fenced ```bash blocks out of a markdown command
         file (specifically content/commands/ds-implement-ticket.md) so their
         shell can be executed against real git fixtures in a pytest suite,
         instead of only ever being read as prose. Built for
         bin/tests/test_phase8_telemetry_shell.py, which exercises the Phase 8
         commit-and-telemetry block.

Public API: extract_marked_block(md_path, marker) -> str
            render(block_text) -> str
            apply_transform(block_text, anchor, transform_fn) -> str
            with_completion_marker(rendered_script) -> str
            syntax_check(rendered_script, shell) -> subprocess.CompletedProcess
            line_containing(text, substr) -> str
            PLACEHOLDER_WHITELIST: dict[str, str]
            COMPLETION_MARKER: str
            HarnessExtractionError, HarnessTransformError

Upstream deps: stdlib only (re, subprocess, tempfile, os).

Downstream consumers: bin/tests/test_phase8_telemetry_shell.py

Failure modes: every extraction/render/transform step is fail-closed - 0 or
               >1 matches raises rather than silently picking one. This
               mirrors the defect class the harness exists to catch (an
               anchor that stops being unique after a prose edit must break
               the test suite loudly, not degrade into extracting the wrong
               block). No side effects other than syntax_check(), which
               shells out to `<shell> -n` against a temp file it creates and
               deletes; safe to call repeatedly.

Performance: standard; extraction/render/transform are pure string ops over
             a <5KB block. syntax_check() forks a subprocess per call.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from typing import Callable


class HarnessExtractionError(Exception):
    """Raised when a fenced ```bash block cannot be uniquely located, or a
    placeholder in PLACEHOLDER_WHITELIST does not appear exactly once."""


class HarnessTransformError(Exception):
    """Raised when an anchor substring used for a mutation (or a
    line_containing() lookup) does not match exactly once inside the
    extracted block."""


# Placeholders that appear in the Phase 8 commit-and-telemetry block as
# human-facing template text (e.g. `git -C $REPO add [specific files]`) that
# must be substituted with a concrete value before the block is executable.
#
# Deliberately NOT a generic bracket regex: the block also has 8+ legitimate
# `[ ... ]` shell test expressions (e.g. `[ -n "$PR_CHECKOUT" ]`), so a naive
# `\[[^]]*\]` pattern is permanently red, and `\[[A-Z_]+\]` is blind to the
# lowercase, space-containing "[specific files]" placeholder.
PLACEHOLDER_WHITELIST: dict[str, str] = {
    "[specific files]": ".agentic/session-log/${DEVELOPER}.jsonl",
    "[BRANCH_NAME]": "$BRANCH_NAME",
    "[TICKET_PREFIX]": "DS-000",
}

# Appended as the final line of a rendered script to prove the block ran to
# completion rather than crashing partway through.
#
# PRECONDITION: marker-absence in stdout proves non-completion ONLY if the
# block contains no `exit` of its own (an early `exit 0` would still leave
# the marker unprinted while the block "succeeded"). Verified 0 occurrences
# of `exit` in the current Phase 8 block (grep -cw exit == 0); re-verify this
# precondition if this helper is ever reused against a different block.
COMPLETION_MARKER = "HARNESS_BLOCK_COMPLETED"

_BASH_FENCE_RE = re.compile(r"```bash\n(.*?)```", re.DOTALL)


def _marker_line(marker: str) -> str:
    return f"# @harness:{marker}"


def extract_marked_block(md_path: str, marker: str) -> str:
    """Return the body (marker line stripped) of the single fenced ```bash
    block in md_path whose first non-blank inner line is exactly
    `# @harness:<marker>`. Raises HarnessExtractionError on 0 or >1 matches.
    """
    with open(md_path, "r", encoding="utf-8") as fh:
        text = fh.read()

    target = _marker_line(marker)
    matches: list[str] = []
    for block in _BASH_FENCE_RE.findall(text):
        lines = block.split("\n")
        first_non_blank_idx = None
        for i, line in enumerate(lines):
            if line.strip() != "":
                first_non_blank_idx = i
                break
        if first_non_blank_idx is None:
            continue
        if lines[first_non_blank_idx].strip() == target:
            remainder = "\n".join(lines[first_non_blank_idx + 1 :])
            matches.append(remainder.lstrip("\n"))

    if len(matches) == 0:
        raise HarnessExtractionError(
            f"marker '{target}' not found in any ```bash block in {md_path} "
            f"(expected exactly 1 match, got 0). Remedy: update the anchor in "
            f"bin/tests/lib/md_shell_extract.py to match the new prose; this "
            f"harness tests Phase 8's telemetry-commit shell, see "
            f"bin/tests/test_phase8_telemetry_shell.py."
        )
    if len(matches) > 1:
        raise HarnessExtractionError(
            f"marker '{target}' matched {len(matches)} ```bash blocks in "
            f"{md_path} (expected exactly 1). Remedy: update the anchor in "
            f"bin/tests/lib/md_shell_extract.py to match the new prose; this "
            f"harness tests Phase 8's telemetry-commit shell, see "
            f"bin/tests/test_phase8_telemetry_shell.py."
        )
    return matches[0]


def render(block_text: str) -> str:
    """Substitute every PLACEHOLDER_WHITELIST key for its value.

    Fails closed in both directions:
      (a) PRE-RENDER: every key must appear exactly once in block_text, or
          this raises - catches "prose renamed the placeholder so render()
          would otherwise silently substitute nothing".
      (b) POST-RENDER: no key may survive substitution.
    """
    for key in PLACEHOLDER_WHITELIST:
        count = block_text.count(key)
        if count != 1:
            raise HarnessExtractionError(
                f"placeholder '{key}' occurs {count} times in the extracted "
                f"block (expected exactly 1). Remedy: update "
                f"PLACEHOLDER_WHITELIST in bin/tests/lib/md_shell_extract.py "
                f"to match content/commands/ds-implement-ticket.md; this "
                f"harness tests Phase 8's telemetry-commit shell, see "
                f"bin/tests/test_phase8_telemetry_shell.py."
            )

    rendered = block_text
    for key, value in PLACEHOLDER_WHITELIST.items():
        rendered = rendered.replace(key, value)

    for key in PLACEHOLDER_WHITELIST:
        if key in rendered:
            raise HarnessExtractionError(
                f"placeholder '{key}' still present after render() "
                f"substitution - substitution did not take effect."
            )
    return rendered


def line_containing(text: str, substr: str) -> str:
    """Return the single full line (no trailing newline) in text that
    contains substr exactly once across the whole text. Raises
    HarnessTransformError on 0 or >1 matching lines, or if substr itself
    occurs more than once total (ambiguous anchor)."""
    total = text.count(substr)
    if total != 1:
        raise HarnessTransformError(
            f"anchor '{substr}' occurs {total} times in the block (expected "
            f"exactly 1). Remedy: update the anchor in "
            f"bin/tests/test_phase8_telemetry_shell.py to match "
            f"content/commands/ds-implement-ticket.md; this harness tests "
            f"Phase 8's telemetry-commit shell."
        )
    for line in text.split("\n"):
        if substr in line:
            return line
    raise HarnessTransformError(
        f"anchor '{substr}' found via count() but not via line scan - "
        f"internal inconsistency in line_containing()."
    )


def apply_transform(
    block_text: str, anchor: str, transform_fn: Callable[[str], str]
) -> str:
    """Validate anchor occurs exactly once in block_text, then apply
    transform_fn(block_text) -> mutated_text. Raises HarnessTransformError on
    0 or >1 anchor occurrences, or if transform_fn returns the input
    unchanged (a no-op transform is a harness bug, not a valid mutant)."""
    count = block_text.count(anchor)
    if count != 1:
        raise HarnessTransformError(
            f"anchor '{anchor}' occurs {count} times in the block (expected "
            f"exactly 1). Remedy: update the anchor in "
            f"bin/tests/test_phase8_telemetry_shell.py to match "
            f"content/commands/ds-implement-ticket.md; this harness tests "
            f"Phase 8's telemetry-commit shell, see "
            f"bin/tests/test_phase8_telemetry_shell.py."
        )
    mutated = transform_fn(block_text)
    if mutated == block_text:
        raise HarnessTransformError(
            f"transform_fn anchored on '{anchor}' produced no change - "
            f"the mutant is identical to the original block."
        )
    return mutated


def with_completion_marker(rendered_script: str) -> str:
    """Append `echo "HARNESS_BLOCK_COMPLETED"` as the final line.

    PRECONDITION (see COMPLETION_MARKER docstring above): marker-absence
    proves non-completion only if the block contains no `exit` of its own.
    """
    script = rendered_script
    if not script.endswith("\n"):
        script += "\n"
    return script + f'echo "{COMPLETION_MARKER}"\n'


def syntax_check(rendered_script: str, shell: str) -> subprocess.CompletedProcess:
    """Run `<shell> -n` against rendered_script via a temp file. Returns the
    CompletedProcess (caller inspects .returncode / .stderr)."""
    fd, path = tempfile.mkstemp(prefix="phase8-syntax-", suffix=".sh")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(rendered_script)
        return subprocess.run(
            [shell, "-n", path],
            capture_output=True,
            text=True,
        )
    finally:
        os.remove(path)
