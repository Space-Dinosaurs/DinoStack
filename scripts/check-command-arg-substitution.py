#!/usr/bin/env python3
"""
Purpose: Fails CI when a bare $0-$9 or $ARGUMENTS token reappears inside
         an executable (bare/```bash/```sh) fence anywhere under a
         target directory (default content/commands) - the exact class
         of harness textual-substitution corruption DS-192 fixed at 12
         sites.

Public API: main(argv) -> int (exit code); run as
            `python3 scripts/check-command-arg-substitution.py [target_dir]`.

Upstream deps: python3 standard library only (re, glob, sys).

Downstream consumers: .github/workflows/command-arg-substitution.yml
                       (non-required CI gate);
                       bin/tests/test_check_command_arg_substitution.sh.

Failure modes: never mutates any file - read-only scan, stdout/stderr
               only. Exit 1 on a bare-token violation or an empty
               file-discovery set. Exit 2 on an unrecognized
               (unclassifiable) fence line or an unterminated fence
               block, so the parser fails loudly rather than silently
               desynchronizing open/closed state.
"""

import glob
import re
import sys

FENCE_RE = re.compile(r'^(?:> )?[ \t]*```([A-Za-z0-9_+-]*)[ \t]*$')
PARTIAL_FENCE_RE = re.compile(r'^(?:> )?[ \t]*`{3,}')
TOKEN_RE = re.compile(r'\$(?:[0-9]|ARGUMENTS\b)')
SCAN_LANGS = {"", "bash", "sh"}


def scan_file(path):
    """Return (violations, error) for one file.

    violations is a list of (lineno, line_text) tuples.
    error is None, or a string describing a fatal parse failure.
    """
    violations = []
    state = "CLOSED"

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()

    for lineno, line in enumerate(lines, start=1):
        fence_match = FENCE_RE.match(line)
        if fence_match:
            if state == "CLOSED":
                lang = fence_match.group(1)
                state = "SCAN" if lang in SCAN_LANGS else "SKIP"
            else:
                state = "CLOSED"
            continue

        if PARTIAL_FENCE_RE.match(line) and not fence_match:
            return violations, (
                f"{path}:{lineno}: unrecognized fence line, "
                f"cannot classify: {line}"
            )

        if state == "SCAN" and TOKEN_RE.search(line):
            violations.append((lineno, line))

    if state != "CLOSED":
        return violations, f"{path}: unterminated fence block (opened, never closed)"

    return violations, None


def main(argv):
    target_dir = argv[1] if len(argv) > 1 else "content/commands"
    files = sorted(glob.glob(target_dir + "/**/*.md", recursive=True))

    if not files:
        print(f"ERROR: discovery set is empty (dir={target_dir})", file=sys.stderr)
        return 1

    all_violations = []
    for path in files:
        violations, error = scan_file(path)
        if error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        for lineno, line in violations:
            all_violations.append((path, lineno, line))

    if all_violations:
        for path, lineno, line in all_violations:
            print(f"{path}:{lineno}: {line}")
        return 1

    print(f"OK: {len(files)} file(s) scanned, zero violations")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
