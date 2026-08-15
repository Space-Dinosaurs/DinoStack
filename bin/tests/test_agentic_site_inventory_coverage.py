"""
Purpose: Coverage-diff gate for DS-171's repo-root anchoring fix. Re-derives
    a deliberately OVERINCLUSIVE candidate list of ".agentic" path-
    construction lines across hooks/, hooks/lib/, and bin/, then asserts
    every candidate line appears in the fixed inventory
    hooks/tests/fixtures/agentic-write-sites.txt. A new .agentic-
    constructing line that is not yet inventoried fails this test, naming
    the offending file:line - closing the gap where a future hook could
    silently reintroduce a cwd-relative (non-repo-root-anchored) .agentic/
    write with no gate ever noticing.

    NAMING NOTE: the originating spec named this file with hyphens
    (bin/tests/test-agentic-site-inventory-coverage.py). bin/tests/ is
    discovered by `pytest bin/tests/ -q` (see .github/workflows/
    bin-tests.yml), which uses pytest's default `test_*.py` discovery glob
    - a hyphenated name in this directory would never be collected. Named
    with underscores here to actually run; hooks/tests/test-repo-root.{js,py}
    correctly keep the hyphenated convention required by that directory's
    own bash-loop discovery mechanism (a DIFFERENT mechanism, not the
    inconsistency it might look like).

Public API: pytest discovers test_candidates_are_all_inventoried() and
    test_inventory_has_no_dangling_entries() automatically.

Upstream deps: Python 3 stdlib only (re, pathlib). Scans the live
    hooks/, hooks/lib/, and bin/ trees at test-run time - no fixtures for
    the CANDIDATE side (the inventory file at
    hooks/tests/fixtures/agentic-write-sites.txt is the only fixture, and
    it is the thing being checked against, not a candidate source).

Downstream consumers: pytest bin/tests/ (CI, .github/workflows/bin-tests.yml).

Failure modes: a candidate line not present in the inventory fails with an
    assertion message naming every offending file:line (not just the
    first). A stale inventory entry whose file:line no longer matches any
    live candidate is reported by test_inventory_has_no_dangling_entries()
    as a separate, non-blocking-in-spirit informational failure (kept as a
    real pytest failure so staleness cannot silently accumulate either).

Performance: O(files scanned); a few hundred files, single grep-equivalent
    regex pass each. Sub-second.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INVENTORY_PATH = REPO_ROOT / "hooks" / "tests" / "fixtures" / "agentic-write-sites.txt"

# Directories scanned for candidate .agentic path-construction lines.
SCAN_DIRS = ["hooks", "hooks/lib", "bin"]

# File extensions considered (no recursion into hooks/tests/, hooks/lib is
# flat so no recursion needed there either; bin/ is flat).
CANDIDATE_EXTENSIONS = {".js", ".py", ".sh", ""}  # "" covers extension-less bin/ CLIs

# The resolver modules themselves are what DOES the resolving, not a site
# to be resolved - excluded from candidate scanning. Also excluded: files
# using a DIFFERENT, already-correct root-resolution mechanism unrelated to
# this ticket's payload-cwd-drift bug class (CLAUDE_PROJECT_DIR-based
# enforce-worktree-{read,write}.py; HOME-scoped, not cwd-scoped,
# version-check-core.sh and repo-dir-fallback.sh - both target
# $HOME/.agentic, never a project's .agentic/).
EXCLUDED_FILES = {
    "hooks/lib/repo-root.js",
    "hooks/lib/repo_root.py",
    "hooks/lib/repo-root.sh",
    "hooks/enforce-worktree-read.py",
    "hooks/enforce-worktree-write.py",
    "hooks/lib/version-check-core.sh",
    "hooks/lib/repo-dir-fallback.sh",
    # Operator-invoked CLIs whose Path.cwd()/os.getcwd() reflects wherever
    # the human ran them from - correct behavior for a manually-invoked
    # tool, not the harness-payload-cwd-drift-across-Bash-calls bug class
    # this ticket fixes. bin/ds-reap-worktrees additionally falls under the
    # brief's explicit "reaped-telemetry consumer wiring" out-of-scope
    # carve-out (its .agentic sites take an explicit --repo/worktree_path
    # argument, not a bare cwd, anyway).
    "bin/ds-doctor",
    "bin/ds-reap-worktrees",
    "bin/ds-update",
}

# Test/fixture paths are never scanned as candidates.
EXCLUDED_DIR_PREFIXES = (
    "hooks/tests/",
    "bin/tests/",
)

# A candidate line must mention ".agentic" AND one of these path-
# construction primitives. Deliberately overinclusive - a resolver-wrapped
# site (e.g. `path.join(resolveAgenticCwd(cwd), '.agentic', ...)`) still
# matches and must still be inventoried, which is exactly the point: the
# inventory is a complete site list, not just a list of un-fixed sites.
PRIMITIVE_RE = re.compile(
    r"\.agentic.*(?:path\.join|os\.path\.join|Path\([^)]*\)\s*/)"
    r"|(?:path\.join|os\.path\.join|Path\([^)]*\)\s*/).*\.agentic"
    r"|\$\{?\w+\}?/\.agentic"  # $var/.agentic or ${var}/.agentic (bash)
)


def _iter_candidate_files():
    for d in SCAN_DIRS:
        base = REPO_ROOT / d
        if not base.is_dir():
            continue
        # Non-recursive: each of hooks/, hooks/lib/, bin/ is scanned at its
        # own single level only (matches the brief's explicit dir list;
        # hooks/tests/ and bin/tests/ are separately excluded above anyway).
        for entry in sorted(base.iterdir()):
            # Skip symlinks (e.g. bin/agentic-* -> bin/ds-*): scanning both
            # the symlink and its target would double-report every site in
            # the target file under two different names.
            if entry.is_symlink():
                continue
            if not entry.is_file():
                continue
            rel = str(entry.relative_to(REPO_ROOT))
            if rel in EXCLUDED_FILES:
                continue
            if any(rel.startswith(p) for p in EXCLUDED_DIR_PREFIXES):
                continue
            if entry.suffix not in CANDIDATE_EXTENSIONS:
                continue
            yield rel, entry


def _find_candidates() -> list[str]:
    """Return a sorted list of "path:line" candidate strings."""
    candidates = []
    for rel, entry in _iter_candidate_files():
        try:
            text = entry.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ".agentic" not in line:
                continue
            # Deliberately HOME-scoped sites (os.homedir(), $HOME, ~/.agentic)
            # are a DIFFERENT, permanently-correct pattern - never anchored
            # to a project's repo root by design (e.g. stop-context.js's
            # ~/.agentic/.identity-nudged sentinel). Excluded by content,
            # not by file, since a file can legitimately mix both patterns.
            if "homedir(" in line or "HOME" in line or "~/.agentic" in line:
                continue
            if PRIMITIVE_RE.search(line):
                candidates.append(f"{rel}:{lineno}")
    return sorted(candidates)


def _load_inventory() -> set[str]:
    entries = set()
    for raw in INVENTORY_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entries.add(line)
    return entries


def test_candidates_are_all_inventoried():
    candidates = _find_candidates()
    inventory = _load_inventory()
    missing = [c for c in candidates if c not in inventory]
    assert not missing, (
        "The following .agentic path-construction site(s) are NOT listed in "
        f"{INVENTORY_PATH.relative_to(REPO_ROOT)} - add each to the inventory "
        "(after confirming it is anchored via resolveAgenticCwd/"
        "resolve_agentic_cwd/resolve_agentic_root, not a raw cwd join):\n  "
        + "\n  ".join(missing)
    )


def test_inventory_has_no_dangling_entries():
    """An inventory entry whose file:line no longer matches any live
    candidate is stale - either the line moved (inventory needs updating)
    or the site was removed/rewritten. Keeps the inventory honest as the
    only mechanically-checked evidence of coverage."""
    candidates = set(_find_candidates())
    inventory = _load_inventory()
    dangling = sorted(inventory - candidates)
    assert not dangling, (
        f"The following inventory entries in {INVENTORY_PATH.relative_to(REPO_ROOT)} "
        "no longer match any live .agentic path-construction candidate line - "
        "the site moved, was rewritten, or was removed; update the inventory:\n  "
        + "\n  ".join(dangling)
    )
