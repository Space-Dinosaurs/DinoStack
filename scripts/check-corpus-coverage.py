#!/usr/bin/env python3
"""
Purpose: CI guard (DS-204) ensuring every content/sections/[0-9][0-9]-*.md
         methodology file has declared a corpus posture - either a line-1
         file-level `<!-- corpora: ... -->` marker, or at least one
         `corpus:begin` block - and that every corpus:begin block whose list
         is not exactly "minimal medium full" carries the mandatory trigger
         clause. Catches a new/edited section file silently shipping with no
         posture at all, which would make its corpus membership ambiguous.

Public API: CLI - `python3 scripts/check-corpus-coverage.py [sections_dir]`
            (sections_dir defaults to content/sections relative to the repo
            root this script lives in). Exits 0 when every file passes, 1
            naming the offending file(s) on stderr.

Upstream deps: scripts/lib/corpus-filter.py (imports CORPORA_FILE_RE,
               CORPUS_BEGIN_RE, CORPUS_END_RE - never re-derives marker
               syntax) and its filter_text()/CorpusFilterError for the
               trigger-mandatory validation, which filter_text() already
               enforces as a side effect of a full-corpus parse.

Downstream consumers: .github/workflows/methodology-drift.yml (check-drift
                       job, after the drift-check step); developers running
                       locally before committing a content/sections/ change.

Failure modes: exits 1 and lists every offending file if any file has
               neither a file-level corpora: marker nor any corpus:begin
               block, or if any corpus:begin block's trigger clause is
               missing when required (surfaced by re-raising
               CorpusFilterError from the upstream parser, prefixed with the
               file name). Exits 1 if sections_dir does not exist or has no
               matching files (an empty section set is itself a defect, not
               a vacuous pass). Read-only; never mutates content/sections/.

Performance: O(total size of section files); one full-corpus parse per file.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_DIR = Path(__file__).parent.parent
_FILTER_MODULE_PATH = _REPO_DIR / "scripts" / "lib" / "corpus-filter.py"

_spec = importlib.util.spec_from_file_location("corpus_filter", _FILTER_MODULE_PATH)
assert _spec is not None and _spec.loader is not None
cf = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("corpus_filter", cf)
_spec.loader.exec_module(cf)


def file_has_posture(text: str) -> bool:
    """A file declares a posture if it carries a file-level corpora: marker
    on any line, or contains any corpus:begin/corpus:end marker line -
    including a lone, unbalanced corpus:end, which is not a valid posture on
    its own but IS evidence of an attempted (malformed) partition. Detecting
    it here routes the file to the real parser below instead of a generic
    "no posture declared" message that would mask the actual malformation
    (DS-204 round-1 Skeptic finding coverage-diagnostic-masked, Minor)."""
    for line in text.splitlines():
        if (
            cf.CORPORA_FILE_RE.match(line)
            or cf.CORPUS_BEGIN_RE.match(line)
            or cf.CORPUS_END_RE.match(line)
        ):
            return True
    return False


def check_file(path: Path) -> list[str]:
    """Returns a list of problem strings for `path` (empty = clean)."""
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []

    if not file_has_posture(text):
        problems.append(
            f"{path.name}: no corpus posture declared - add a line-1 "
            "'<!-- corpora: minimal medium full -->' marker, or partition "
            "the file with one or more corpus:begin/corpus:end blocks"
        )
        return problems

    # Re-use the real parser (full corpus) so the mandatory-trigger rule,
    # nesting rule, and balance rule are enforced identically to the build.
    try:
        cf.filter_text(text, "full", path.name, file_label=path.name)
    except cf.CorpusFilterError as exc:
        problems.append(f"{path.name}: {exc}")

    return problems


def main(argv: list[str]) -> int:
    sections_dir = Path(argv[0]) if argv else (_REPO_DIR / "content" / "sections")

    if not sections_dir.is_dir():
        print(f"check-corpus-coverage.py: not a directory: {sections_dir}", file=sys.stderr)
        return 1

    section_files = sorted(sections_dir.glob("[0-9][0-9]-*.md"))
    if not section_files:
        print(
            f"check-corpus-coverage.py: no [0-9][0-9]-*.md files found in {sections_dir}",
            file=sys.stderr,
        )
        return 1

    all_problems: list[str] = []
    for path in section_files:
        all_problems.extend(check_file(path))

    if all_problems:
        for problem in all_problems:
            print(f"check-corpus-coverage.py: {problem}", file=sys.stderr)
        return 1

    print(f"check-corpus-coverage.py: OK ({len(section_files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
