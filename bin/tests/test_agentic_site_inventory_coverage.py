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

    DS-176 REWORK (adapter-hooks-agentic-root): SCAN_DIRS now also covers
    the hand-authored, non-build-generated adapter hook/plugin/extension
    surfaces - ".cursor/hooks", ".copilot/hooks", ".github/hooks",
    ".gemini/hooks", ".kimi/hooks", ".opencode/plugins", ".codex/hooks",
    ".pi/extensions/dinostack" - which close the phantom-.agentic-tree bug
    class this gate exists to catch (the original DS-171 pass covered
    hooks/**, bin/**, and the Claude Code Bash hook, but explicitly NOT the
    adapter dirs, because build.sh does not regenerate them and
    check-adapter-sync cannot see them). Deliberately scoped to each
    adapter's hand-authored hook/plugin/extension SUBDIRECTORY, never the
    adapter's full top-level tree: every adapter directory also holds a
    build-generated, verbatim copy of content/** (references/, commands/,
    agents/, skills/, templates/ - including, for .cursor and .gemini, a
    templates/.agentic/ SCAFFOLD directory whose files are literal
    `/ds-init-project` templates, not executable code) - scanning those
    would flood candidates with prose matches on the literal string
    ".agentic" inside markdown, none of which are path-construction sites.

    DS-176 ROUND-2 REWORK (Major 1: the six-entry list above was confirm-only -
    each dir was individually verified to hold hooks and nothing else, but
    the set itself was never independently derived, so it silently omitted
    ".codex/hooks" (3 files: risk-reminder.sh, stop-context-codex.js, and a
    symlinked skill-auto-load-check.sh -> ../../hooks/skill-auto-load-
    check.sh that the scanner's is_symlink() skip already handles) and
    ".pi/extensions/dinostack" (index.ts) entirely): the eight SCAN_DIRS
    adapter entries above were derived by enumerating the FULL set of
    adapter roots this repo builds (the 11-entry pathspec asserted by
    ".github/workflows/adapter-sync.yml"'s "Verify adapter-sync pathspec
    entries exist" step: .claude .codex .cursor .gemini .kimi .opencode
    .omp .pi .hermes .openclaw .copilot, plus the .github/* subpaths),
    then running `find <each-root> -maxdepth 2 -type d` over all 11 and
    keeping every directory name matching hook/plugin/extension/script.
    That surfaced exactly eight hits: .copilot/hooks, .github/hooks,
    .kimi/hooks, .opencode/plugins, .pi/extensions (containing the single
    dinostack/ subdir, scanned directly rather than its parent so the scan
    stays scoped to hand-authored code, not a future sibling extension
    directory of unknown shape), .codex/hooks, .cursor/hooks, .gemini/hooks
    - .claude, .omp, .hermes, and .openclaw have no such directory at this
    depth (Claude Code's hooks are wired via settings.json, not a
    hooks/-shaped directory in the adapter tree). Each of the eight
    SCAN_DIRS adapter entries was then individually verified (as before) to
    hold only hook/plugin/extension code, zero generated markdown - but
    that per-entry confirmation is no longer the sole method establishing
    the set is complete.

    The same `find`-derived sweep also surfaced ".codex/lib/prompt-
    wrappers.py", which builds two ".agentic"-shaped paths (RUNTIME_REL at
    module scope, and `paths.repo / ".agentic"`) but sits under ".codex/lib"
    (not ".codex/hooks"), i.e. it is not, and never was, inside SCAN_DIRS -
    it is out of scope by directory selection, not by an EXCLUDED_FILES
    entry. Decision: it stays out of scope, deliberately not added to
    SCAN_DIRS or EXCLUDED_FILES. Every `.agentic` site in that module
    derives from `paths.repo`, which comes from its parser's `--repo`
    argument (argparse `required=True`, no cwd default,
    ".codex/lib/prompt-wrappers.py:3052,3056") - the same explicit-required-
    argument exemption rationale already applied to bin/ds-doctor,
    bin/ds-evaluate, bin/ds-migrate, and bin/ds-team above, not the bare-
    cwd-fallback drift-prone class this gate exists to catch. It is a
    build-time prompt-generation tool invoked by ".codex/build.sh" and by a
    human operator, never by a live hooks/*.js or hooks/*.py call site
    reading a harness-payload cwd.

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

    ROUND-3 REWORK (adversarial review Minor 3, left as documented rather
    than mechanically closed): this gate asserts only that a candidate
    line is LISTED in the inventory, never that the site it names is
    actually ANCHORED via resolveAgenticCwd/resolve_agentic_cwd/
    resolve_agentic_root. A new un-anchored `.agentic` write, dutifully
    copy-pasted into the inventory by whoever added it, passes this test
    exactly as cleanly as a genuinely anchored one - the "after confirming
    it is anchored" instruction in the assertion message below is a
    human-review prompt, not something this test verifies. No cheap
    mechanical check closes this: "anchored" means "the value flowing into
    this join traces back to a resolveAgenticCwd/resolve_agentic_cwd/
    resolve_agentic_root call or an equally-safe explicit CLI argument",
    which requires dataflow analysis this line-pattern scanner does not
    and cannot do. Left as a known, named gap rather than a false
    assurance.

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
#
# DS-176: the eight adapter hook/plugin/extension subdirectories below are
# scanned in addition - see the DS-176 REWORK and DS-176 ROUND-2 REWORK
# paragraphs in this file's module docstring for how the set was derived
# (enumerated from all 11 adapter roots, not confirmed against a
# pre-picked list) and why each is scoped to its adapter's hand-authored
# hooks/plugins/extension subdirectory, never the adapter's full top-level
# tree.
SCAN_DIRS = [
    "hooks",
    "bin",
    ".cursor/hooks",
    ".copilot/hooks",
    ".github/hooks",
    ".gemini/hooks",
    ".kimi/hooks",
    ".opencode/plugins",
    ".codex/hooks",
    ".pi/extensions/dinostack",
]

# File extensions considered ("" covers extension-less bin/ CLIs; ".ts" is
# DS-176's addition, needed for .opencode/plugins/session-context.ts and
# .pi/extensions/dinostack/index.ts).
CANDIDATE_EXTENSIONS = {".js", ".py", ".sh", ".ts", ""}

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
    # either binary - both take an explicit --repo/--workdir-style argument
    # rather than a bare cwd, same rationale as bin/ds-doctor/ds-migrate/
    # ds-update above.
    "bin/ds-config",
    # Round-3 rework (Major 4): the round-2 comment above claimed bin/ds-team
    # is "exclusively human/CLI-invoked" - FALSE. hooks/enforce-background-
    # spawn.py:398,411,433,463 instructs the CONDUCTOR to run
    # `bin/ds-team dispatch --harness ... --workdir <dir>` via Bash as part
    # of its normal deny-message-driven remediation flow. The exemption
    # itself is still correct, but for a DIFFERENT, narrower reason: every
    # `.agentic`-writing call in bin/ds-team (the `dispatch` subcommand's
    # run_dir/active_sentinel writes) is anchored to an EXPLICIT, REQUIRED
    # `--workdir` argument (argparse `required=True`, no cwd default) -
    # matching the explicit-argument pattern that already exempts
    # bin/ds-evaluate (--repo) and bin/ds-migrate (--project-root) below,
    # not a bare Path.cwd()/os.getcwd() fallback of the drift-prone class
    # this ticket fixes.
    #
    # This does NOT cover the separate reader-side bug also found in
    # round-3 review: hooks/enforce-background-spawn.py's own
    # `_sentinel_is_live(cwd)` (lines 288-300) reads
    # `Path(cwd) / ".agentic/teamrun/.active"` against the raw, UNANCHORED
    # harness-payload cwd (`data.get("cwd") or os.getcwd()`) - the exact
    # writer/reader split this ticket exists to close, and it is invisible
    # to THIS scanner because the join line (`Path(cwd) / _SENTINEL_REL`)
    # contains no `.agentic` string literal at all (the literal lives on a
    # separate line, `_SENTINEL_REL = ".agentic/teamrun/.active"`, which
    # itself matches no join-primitive shape). Deliberately DEFERRED, not
    # fixed, in this rework - anchoring hooks/enforce-background-spawn.py's
    # sentinel read is separable from correcting this exclusion rationale,
    # and widening the scanner to catch bare-constant-then-later-joined
    # `.agentic` strings is a separate, riskier regex change. Tracked as an
    # open gap, not silently dropped.
    "bin/ds-team",
    # Round-3 rework (Major 3 audit): bin/ds-evaluate is a slash-command-
    # driven signal collector (`/ds-evaluate`, `content/commands/
    # ds-evaluate.md`), never shelled out to from any hooks/*.js or
    # hooks/*.py call site. Its `.agentic`-reading sites (session-log,
    # events.jsonl, enforcement-fires.jsonl) all derive from `repo`, which
    # comes from an explicit `--repo` argument (default "." - the
    # conductor's OWN cwd, not a harness-payload cwd handed across a
    # Bash-tool boundary) - same explicit-argument exemption rationale as
    # bin/ds-doctor/bin/ds-update above.
    "bin/ds-evaluate",
    # Round-3 rework (Major 3 audit): bin/ds-migrate is a project-
    # scaffolding/migration CLI invoked from `/ds-init-project`,
    # `/ds-migrate-project`, and `/ds-wrap`'s scaffolding step, never from
    # a hooks/*.js or hooks/*.py call site. Its `.agentic`-writing sites
    # all derive from `project_root`, which comes from an explicit
    # `--project-root` argument (default `Path.cwd()` - the conductor's
    # own invoking cwd, not a drifted harness-payload cwd) - same
    # explicit-argument exemption rationale as bin/ds-doctor/bin/ds-update
    # above. (The round-2 comment two entries up already referenced
    # "bin/ds-doctor/ds-migrate/ds-update" as sharing this rationale, but
    # bin/ds-migrate itself was never actually added to this set until
    # now - a stale cross-reference this rework corrects.)
    "bin/ds-migrate",
    # DS-agentic-repair (phantom .agentic/ tree cleanup, post-PR-#745):
    # bin/ds-agentic-repair is an operator-invoked CLI whose sole cwd-
    # sensitive input is an explicit `--repo` argument (default ".",
    # resolved once via resolve_agentic_cwd before any .agentic path is
    # constructed) - same explicit-argument exemption rationale as
    # bin/ds-doctor/bin/ds-evaluate/bin/ds-migrate above, matching
    # bin/ds-reap-worktrees's own precedent for this exact carve-out
    # (:111-115 in this file). Not shelled out to by any hooks/*.js or
    # hooks/*.py call site.
    "bin/ds-agentic-repair",
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
    # Round-3 rework (Major 3): a BARE identifier/attribute (no preceding
    # `)`, no Path(...) wrapper) divided by a ".agentic"-bearing string
    # literal - e.g. `some_root / ".agentic" / "probe.json"` or
    # `self.root / ".agentic"`. The `)`-anchored primitive above and the
    # Path(...)-slash primitive both required something in front of the
    # `/` that this shape lacks; mutation-proved (a variable-then-slash
    # line reddened this gate only after adding this pattern; it slipped
    # past silently before).
    r"\b\w+(?:\.\w+)*\s*/\s*[\"']\.agentic",
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
