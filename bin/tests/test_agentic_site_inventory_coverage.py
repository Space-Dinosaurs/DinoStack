"""
Purpose: Coverage-diff gate for DS-171's repo-root anchoring fix. Re-derives
    a deliberately OVERINCLUSIVE candidate list of ".agentic" path-
    construction lines across hooks/, hooks/lib/, and bin/ (RECURSIVELY -
    round-2 rework fixed a Major finding where a non-recursive walk made any
    future hooks/<subdir>/* file invisible to this gate), then asserts every
    candidate line appears in the fixed inventory
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

    ROUND-2 REWORK (adversarial review found the line-number-keyed
    inventory laundered regressions - inserting one harmless comment line
    reddened BOTH tests below and the rational fix, bulk regeneration,
    would silently absorb a genuinely new un-anchored site added in the
    same edit): the inventory key is now `path::normalized-snippet[#N]`,
    NOT `path:line`. A key is stable under any line-number shift elsewhere
    in the file; it only changes when the site's OWN line content changes.
    The `#N` disambiguator (N = 1-based occurrence index within the file)
    only appears for the 2nd and later occurrence of an identical
    normalized snippet in the same file, so two genuinely different lines
    that happen to normalize identically still get distinct keys.

Public API: pytest discovers test_candidates_are_all_inventoried() and
    test_inventory_has_no_dangling_entries() automatically.

Upstream deps: Python 3 stdlib only (re, os, pathlib). Scans the live
    hooks/, hooks/lib/, and bin/ trees at test-run time - no fixtures for
    the CANDIDATE side (the inventory file at
    hooks/tests/fixtures/agentic-write-sites.txt is the only fixture, and
    it is the thing being checked against, not a candidate source).

Downstream consumers: pytest bin/tests/ (CI, .github/workflows/bin-tests.yml).

Failure modes: a candidate line not present in the inventory fails with an
    assertion message naming every offending file:line (not just the
    first). A stale inventory entry whose key no longer matches any live
    candidate is reported by test_inventory_has_no_dangling_entries() as a
    separate, non-blocking-in-spirit informational failure (kept as a real
    pytest failure so staleness cannot silently accumulate either).

Performance: O(files scanned); a few hundred files, single grep-equivalent
    regex pass each. Sub-second.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INVENTORY_PATH = REPO_ROOT / "hooks" / "tests" / "fixtures" / "agentic-write-sites.txt"

# Root directories scanned for candidate .agentic path-construction lines.
# Scanned RECURSIVELY (round-2 rework; was non-recursive, which made any
# future hooks/<subdir>/* file invisible to this gate). "hooks/lib" is
# DELIBERATELY NOT listed separately here even though it holds real
# candidate sites: "hooks" is walked recursively and already covers it -
# listing both would rglob() every hooks/lib/* file twice (once directly,
# once as a descendant of "hooks"), duplicating every candidate in that
# directory. bin/ has no subdirectories today but is walked recursively
# too for the same forward-looking reason "hooks" is.
SCAN_DIRS = ["hooks", "bin"]

# File extensions considered ("" covers extension-less bin/ CLIs).
CANDIDATE_EXTENSIONS = {".js", ".py", ".sh", ""}

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
    # Round-2 rework: the scanner-widening pass (Major 3) surfaced these two
    # additional operator-invoked CLIs' bare relative `Path(".agentic/...")`
    # constants (bin/ds-config's project config writer, bin/ds-team's
    # PROJECT_TEAM_YML). Verified zero hooks/*.js call sites shell out to
    # either binary - both are exclusively human/CLI-invoked, same
    # rationale as bin/ds-doctor/ds-migrate/ds-update above.
    "bin/ds-config",
    "bin/ds-team",
}

# Test/fixture paths (at any depth) are never scanned as candidates.
EXCLUDED_DIR_PREFIXES = (
    "hooks/tests/",
    "bin/tests/",
)

# Individual regex primitives for ".agentic" path construction, deliberately
# overinclusive - a resolver-wrapped site (e.g. `path.join(resolveAgenticCwd
# (cwd), '.agentic', ...)`) still matches and must still be inventoried,
# which is exactly the point: the inventory is a complete site list, not
# just a list of un-fixed sites. Round-2 rework widened this list after
# adversarial review proved several shapes slipped past the original single
# regex: `path.resolve(cwd, '.agentic')`, string concatenation
# (`cwd + '/.agentic/...'`), Python f-strings (`f"{cwd}/.agentic/..."`),
# `Path(os.getcwd()) / ".agentic"` (nested-call parens), `.joinpath(...)`,
# and `"$(pwd)/.agentic"`.
_PRIMITIVE_PATTERNS = [
    # JS/Python join calls: path.join(...) / os.path.join(...) anywhere on
    # the line (paired with the outer ".agentic in line" prefilter).
    r"\bpath\.join\(",
    r"\bos\.path\.join\(",
    # pathlib slash-join: Path(<balanced-one-level-nesting>) / ... - handles
    # one level of nested call parens, e.g. Path(os.getcwd()) / ".agentic".
    r"Path\((?:[^()]|\([^()]*\))*\)\s*/",
    # .resolve(...) / .joinpath(...) method calls (path.resolve, os.path.
    # resolve, a pathlib Path's .resolve()/.joinpath()).
    r"\.resolve\(",
    r"\.joinpath\(",
    # A call result (any function, not just Path(...)) divided by a
    # ".agentic"-bearing string literal - covers bin/ds-status's/ds-cost's
    # `_agentic_root() / ".agentic" / ...` module-level constants, which P3
    # above (Path(...)-specific) does not reach.
    r"\)\s*/\s*[\"']\.agentic",
    # Any call whose (first) argument is a ".agentic"-bearing string
    # literal - covers bin/ds-memory's `_LazyAgenticPath(".agentic", ...)`
    # constructor calls (a path-construction primitive local to that
    # file's own lazy-proxy wrapper, not path.join/Path()/.resolve()).
    r"\(\s*[\"']\.agentic",
    # Shell/JS-template variable interpolation immediately before /.agentic:
    # $var/.agentic, ${var}/.agentic, `${cwd}/.agentic`.
    r"\$\{?\w+\}?/\.agentic",
    # Shell command substitution: "$(pwd)/.agentic".
    r"\$\(pwd\)",
    # Python f-string interpolation: f"{cwd}/.agentic/...".
    r"f[\"'][^\"']*\{[^}]*\}[^\"']*\.agentic",
    # String concatenation with a .agentic-bearing literal on either side:
    # cwd + '/.agentic/...'  or  '/.agentic/...' + cwd
    r"\+\s*[\"'][^\"']*\.agentic",
    r"[\"'][^\"']*\.agentic[^\"']*[\"']\s*\+",
]
PRIMITIVE_RE = re.compile("|".join(f"(?:{p})" for p in _PRIMITIVE_PATTERNS))

# Deliberately HOME-scoped sites (os.homedir(), $HOME, ~/.agentic, etc.) are
# a DIFFERENT, permanently-correct pattern - never anchored to a project's
# repo root by design (e.g. stop-context.js's ~/.agentic/.identity-nudged
# sentinel). Round-2 rework: tightened from a bare `"HOME" in line`
# substring check (which silently dropped any line merely CONTAINING the
# substring "HOME" - e.g. a trailing `# HOMEBREW note` comment - from
# candidate scanning) to explicit HOME-variable-reference patterns.
_HOME_PATTERNS = [
    r"homedir\(",
    r"~/\.agentic",
    r"\$HOME\b",
    r"\$\{HOME\}",
    r"os\.environ(?:\.get)?\(\s*[\"']HOME[\"']",
    r"process\.env\.HOME\b",
    r"getenv\(\s*[\"']HOME[\"']",
]
HOME_RE = re.compile("|".join(f"(?:{p})" for p in _HOME_PATTERNS))


def _iter_candidate_files():
    for d in SCAN_DIRS:
        base = REPO_ROOT / d
        if not base.is_dir():
            continue
        # Recursive walk (round-2 rework; was base.iterdir(), single-level
        # only). Sorted for deterministic scan order.
        for entry in sorted(base.rglob("*")):
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


def _normalize_snippet(line: str) -> str:
    """Collapse whitespace so a key is stable across re-indentation and
    unrelated line-number shifts elsewhere in the file."""
    return re.sub(r"\s+", " ", line.strip())


def _find_candidates() -> list[str]:
    """Return a sorted list of content-keyed candidate strings, one per
    matching line: "path::normalized-snippet" (or "path::snippet#N" for the
    Nth+ occurrence of an identical normalized snippet within one file)."""
    candidates = []
    for rel, entry in _iter_candidate_files():
        try:
            text = entry.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        seen_counts: dict[str, int] = {}
        for line in text.splitlines():
            if ".agentic" not in line:
                continue
            if HOME_RE.search(line):
                continue
            if not PRIMITIVE_RE.search(line):
                continue
            snippet = _normalize_snippet(line)
            seen_counts[snippet] = seen_counts.get(snippet, 0) + 1
            idx = seen_counts[snippet]
            key = f"{rel}::{snippet}" if idx == 1 else f"{rel}::{snippet}#{idx}"
            candidates.append(key)
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
    """An inventory entry whose key no longer matches any live candidate is
    stale - either the site's line content changed (inventory needs
    updating) or the site was removed/rewritten. Keeps the inventory honest
    as the only mechanically-checked evidence of coverage."""
    candidates = set(_find_candidates())
    inventory = _load_inventory()
    dangling = sorted(inventory - candidates)
    assert not dangling, (
        f"The following inventory entries in {INVENTORY_PATH.relative_to(REPO_ROOT)} "
        "no longer match any live .agentic path-construction candidate line - "
        "the site's content changed, was rewritten, or was removed; update the inventory:\n  "
        + "\n  ".join(dangling)
    )
