"""
Purpose: Shared extraction helpers for pinning a resident-tier rule
         paragraph in content/rules/conventions.md against its full detail
         section in content/references/conventions-detail.md. Extracted in
         round 7 (DS-auto-merge-followthrough) from byte-identical inline
         logic duplicated between bin/tests/test_merge_time_writeback_spec.py
         and bin/tests/test_auto_merge_followthrough_resident_spec.py -
         those two modules differed only in which label/heading constant
         they closed over, not in the extraction logic itself.

Public API: resident_rule(path, label) -> str
            detail_section(path, heading) -> str

Upstream deps: stdlib only (pathlib).

Downstream consumers: bin/tests/test_merge_time_writeback_spec.py,
               bin/tests/test_auto_merge_followthrough_resident_spec.py.

Failure modes: raises ValueError (via str.index) if `label`/`heading` is not
               found in the file, or if the expected terminator (a blank
               line for resident_rule, the next "## " heading for
               detail_section) is not found after it - fail-loud by design,
               matching the extraction discipline `md_shell_extract.py` uses
               for its own marker lookups.

Performance: One file read plus pure string slicing per call.
"""
from __future__ import annotations

import pathlib


def resident_rule(path: pathlib.Path, label: str) -> str:
    """Return the resident-tier paragraph in `path` that begins with `label`,
    up to (not including) the next blank line."""
    text = path.read_text(encoding="utf-8")
    idx = text.index(label)
    return text[idx : text.index("\n\n", idx)]


def detail_section(path: pathlib.Path, heading: str) -> str:
    """Return the full detail section in `path` that begins with `heading`,
    up to (not including) the next level-2 (`## `) heading."""
    text = path.read_text(encoding="utf-8")
    start = text.index(heading)
    end = text.index("\n## ", start + len(heading))
    return text[start:end]
