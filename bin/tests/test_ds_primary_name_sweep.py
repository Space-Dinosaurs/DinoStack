#!/usr/bin/env python3
"""
Purpose: Regression coverage for the bin/agentic-* -> bin/ds-* PRIMARY-NAME
         sweep (distinct from test_ds_rename_regression.py, which covers
         symlink/alias structural correctness). This asserts no ds-* tool
         self-identifies with its OLD agentic-* name, and that
         scripts/codex-skills.py never ships an old tool name into a
         generated Codex artifact through a codex-authored REPLACEMENT
         string. This is the class of bug a Skeptic review caught as a
         MAJOR finding on Unit 2 of the ds-rename program:
         scripts/codex-skills.py's `literal_rules` REPLACEMENT text (index
         2 of each tuple) still said "agentic-identity" instead of
         "ds-identity", so it shipped into four generated Codex artifacts
         (.codex/AGENTS.md, .codex/skills/dinostack/
         METHODOLOGY.md, .codex/skill-compatibility.yml) even though every
         other MAJOR/MINOR finding in the same review round had been fixed.
         No prior test asserted this - that absence is precisely why the
         bug shipped and survived one full review cycle.

         Three checks, in increasing specificity:

         (1) `test_bin_scripts_do_not_self_identify_with_old_names` - scans
             every non-symlink, non-test file directly under `bin/` (the
             25 real `bin/ds-*` tools plus `bin/_lib.py`, `bin/_role_spec.py`)
             for any of the 25 old `agentic-*` tool names appearing as
             literal text. `bin/tests/` is excluded because it legitimately
             references old names as literal test fixtures (see
             test_ds_rename_regression.py) - that is test data, not a tool
             self-identifying. `bin/AGENTS.md` is excluded because its job
             is to document the old-name -> new-name compat mapping (it
             says "bin/agentic-cost -> bin/ds-cost" by design); every other
             bin/ file is asserted clean.

         (2) `test_codex_literal_rules_replacements_never_contain_old_names`
             - the PRIMARY, general-purpose check. This statically parses
             `scripts/codex-skills.py` (via `ast`, no import/execution) to
             extract the `literal_rules` list and asserts that no tuple's
             REPLACEMENT string (index 2) contains any of the 25 old tool
             names. This is deliberately a check on the SOURCE that
             PRODUCES the generated tree, not the rendered output itself,
             for a precise reason established by manual audit of all 14
             current tuples: a `literal_rules` tuple's PATTERN (index 0) is
             legitimately ALLOWED to contain an old name, because its job
             is to MATCH un-renamed `content/**` text, not to assert that
             none exists. As of the completion of Units 1-5 (bin/, content/
             sections/, content/rules/, content/commands/, content/agents/,
             and content/references/), an AST parse of the current 14
             tuples finds ZERO PATTERNs that still retain an old tool
             name - every tuple that once matched pre-rename prose was
             updated in lockstep when its target file was renamed. The
             general invariant this program maintains: a `literal_rules`
             PATTERN may legitimately retain an old name ONLY for as long
             as some file under `content/**` that the pattern is meant to
             match still contains un-renamed prose - the moment the last
             such file in a given tree is renamed, any PATTERN still
             citing the old name becomes dead weight (not a bug, but a
             signal the pattern's target text tree is now fully migrated).
             `content/project-scaffolding.yml` is copied verbatim as an
             operator-facing resource, so nothing it contains feeds any
             `literal_rules` PATTERN and is outside this test's concern
             regardless of whether its own prose has been renamed - as of
             the fix for MINOR 3 in the same review round that added this
             test (DS-90 Unit 5 review), it has been: its manifest header
             now says `bin/ds-migrate` throughout, not `bin/agentic-migrate`.
             This paragraph is written to name the invariant, not a
             specific file's rename status, so it stays true regardless of
             future renames - `test_content_residue_set_pinned_to_known_exceptions`
             below is what actually enforces the exact residue set (which
             file, which token), so this paragraph never has to.
             `content/project-scaffolding.yml` not feeding `literal_rules`
             was never an exceptional property of that one file - stated
             precisely, `scripts/codex-skills.py`'s `documents()` function
             (codex-skills.py:608-614) pattern-matches only THREE things:
             `content/SKILL.md`, the assembled METHODOLOGY from
             `content/sections/**`, and the 3 `WORKFLOWS` command files.
             Everything else under `content/**` - including all of
             `content/references/**`, `content/rules/**`,
             `content/agents/**`, and every non-WORKFLOWS file in
             `content/commands/**`, not just `project-scaffolding.yml` - is
             equally outside pattern-match scope; `safe_link()` (not
             `transform()`) is what routes `project-scaffolding.yml`
             specifically, but the same non-pattern-matched outcome holds
             for the rest of the tree via other routing. But the
             REPLACEMENT is entirely
             codex-authored: it is hand-written prose/command text that
             ships into the generated Codex harness, and none of the 14
             current tuples' replacements has any legitimate reason to
             reproduce an old tool name (verified by reading every tuple: 8
             of 14 map to `$AE_*` runtime bindings or the protected
             `dinostack` skill noun, and the other 6 either match
             nothing in current content or are literal command text that
             should always use the new `ds-*` form). This closes the
             MAJOR-1 gap directly at its source and generalizes to any
             future `literal_rules` entry without needing per-entry
             maintenance.

             This is NOT the same class of rule as the OTHER old-name-
             preserving transformation in codex-skills.py
             (`codexify_project_paths`, which does prefix-only path
             substitution and legitimately preserves a trailing literal
             segment such as `bin/agentic-migrate` because content/** still
             writes that bare relative path) - that function builds its
             replacement DYNAMICALLY by splicing the unmatched suffix of
             the matched text, so it can never "forget" to rename a
             hardcoded string. `literal_rules`' fully-hardcoded replacement
             strings are one place this can go stale, and are the shape of
             the MAJOR 1 finding, but they are not the only place: several
             other codex-authored hardcoded strings in this file (e.g. the
             `CODEX_SPAWN_CONTRACT`/`SIMPLIFY_CONTRACT` blocks and other
             inline `bin/ds-*` command text) carry the same risk if a tool
             is ever renamed again - this test does not scan those.

         (3) `test_codex_generated_identity_commands_use_ds_identity` -
             defense-in-depth directly against the two rendered artifacts
             MAJOR 1 named (`.codex/AGENTS.md` and
             `.codex/skills/dinostack/METHODOLOGY.md`): asserts
             the specific renamed operational strings that `literal_rules`
             tuples 0 and 5 (the identity resolve-hook and confirm/correct
             block) are supposed to produce are present verbatim, and that
             their old-name predecessors are absent. This is intentionally
             narrow and tied to the exact bug instance (not a generic
             sweep of the rendered tree - see the module docstring
             discussion of why a generic content-derivation boundary on
             rendered output is fragile: an unrenamed file under
             `content/**` could legitimately still say an old tool name
             verbatim (as of the MINOR 3 fix in the same review round,
             none currently do - `content/project-scaffolding.yml` was
             the last one and is now renamed - but the pattern-matching
             boundary this test avoids still has to hold generally, not
             just for today's zero-file case; see check (2)'s discussion
             above) - and a window/diff-based exclusion boundary against
             that prose produces false
             positives whenever codex-skills.py's own (legitimate)
             path-qualification logic inserts a nearby `$AE_*` token -
             check (2) above is the robust, general mechanism; this check
             (3) is a targeted sensor confirming the actual shipped bytes
             match what (2) implies).

         The protected skill noun "dinostack", the protected
         config filenames/markers (~/.claude/agentic-engineering.json,
         agentic-engineering-config.json, "agentic-engineering: opt-in" /
         "opt-out" / "-profile:" / "-preset:"), and any bare "agentic-"
         prefix (e.g. `BIN_TOOL_PREFIXES = ("agentic-", "ds-")`,
         "agentic-* -> ds-* rename") are never matched by check (1): it
         scans for the 25 SPECIFIC full old tool-name strings
         ("agentic-config", "agentic-identity", ...), and none of those 25
         strings is a substring of any protected marker (verified: "config"
         never immediately follows "agentic-" in
         "agentic-engineering-config.json" - "engineering-" sits between
         them). Check (2) inspects only the REPLACEMENT half of each
         tuple, so a PATTERN that legitimately needs to match
         "dinostack" or any other protected/un-renamed
         content/** string never triggers it.

Public API: python3 -m pytest bin/tests/test_ds_primary_name_sweep.py -q
            Also directly executable: python3 bin/tests/test_ds_primary_name_sweep.py
            Exits 0 on all pass, 1 on any failure (direct-execution mode).

Upstream deps: Python 3 stdlib only (ast, json, os, pathlib, subprocess).
               Check (2) parses scripts/codex-skills.py source without
               executing it. Check (3) requires `.codex/AGENTS.md` and
               `.codex/skills/dinostack/METHODOLOGY.md` to exist
               (built by `.codex/build.sh`); if absent, that check fails
               loudly rather than skipping, since a repo that ships
               `.codex/**` without these files is itself a defect.
               `test_no_sibling_product_brand_name_in_tracked_tree` shells
               out to `git ls-files -z` (the one subprocess call in this
               module) to enumerate the tracked tree; see that function's
               own docstring and the preceding section comment for why
               tracked-files-based scanning was chosen over a filesystem
               walk.

Downstream consumers: bin-tests CI job (pytest bin/tests/ -q picks up every
                      test_*.py file automatically).

Failure modes: any assertion failure prints/raises and is counted; the
               direct-execution __main__ path exits 1 if any check fails.

Performance: < 2 s wall time (pure filesystem/AST reads plus one
             `git ls-files` subprocess call).
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"
CONTENT_DIR = REPO_ROOT / "content"
CODEX_SKILLS_PY = REPO_ROOT / "scripts" / "codex-skills.py"
CODEX_AGENTS_MD = REPO_ROOT / ".codex" / "AGENTS.md"
CODEX_METHODOLOGY_MD = REPO_ROOT / ".codex" / "skills" / "dinostack" / "METHODOLOGY.md"

# The 25 renamed tools (suffix only) - independently re-derived against
# `ls bin/agentic-*` at review time, same list as
# test_ds_rename_regression.py's SUFFIXES (kept in sync manually; a
# count-driven cross-check lives in test_every_ds_star_file_on_disk_has_a_
# working_agentic_alias in that file).
OLD_SUFFIXES = [
    "base-sync", "calibrate", "codex-dispatch", "codex-session-id", "config",
    "configure", "cost", "disable", "doctor", "emit", "evidence", "feedback",
    "help", "identity", "memory", "migrate", "models",
    "parse-subagent-usage", "resolve-worktree", "status", "team", "tracker",
    "update", "wrap-acquire-lock", "wrap-release-lock",
]
OLD_NAMES = [f"agentic-{s}" for s in OLD_SUFFIXES]

# bin/AGENTS.md's job is to document the old-name -> new-name compat
# mapping ("bin/agentic-cost -> bin/ds-cost") - it is expected to mention
# old names by design and is excluded from the self-identification scan.
EXCLUDED_BIN_FILES = {"AGENTS.md"}


def _bin_files_to_scan() -> list[Path]:
    """Every non-symlink, non-directory file directly under bin/, excluding
    bin/tests/ (test fixtures legitimately reference old names as literal
    data) and EXCLUDED_BIN_FILES (documented exceptions)."""
    out = []
    for entry in sorted(BIN_DIR.iterdir()):
        if entry.is_dir():
            continue
        if entry.is_symlink():
            continue
        if entry.name in EXCLUDED_BIN_FILES:
            continue
        out.append(entry)
    return out


def test_bin_scripts_do_not_self_identify_with_old_names() -> None:
    files = _bin_files_to_scan()
    assert files, "no bin/ files found to scan - unexpected"

    failures = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:  # pragma: no cover - defensive
            failures.append(f"{path.name}: could not read ({exc})")
            continue
        hit_names = [name for name in OLD_NAMES if name in text]
        if hit_names:
            failures.append(f"{path.name}: contains old tool name(s) {hit_names}")

    assert not failures, "old tool names found in bin/ (excluding tests/ and documented exceptions):\n" + "\n".join(
        failures
    )


def _extract_literal_rules_tuples() -> list[tuple]:
    """Statically parse scripts/codex-skills.py and return every tuple in
    the `literal_rules = [...]` assignment as a list of Python tuples
    (via ast.literal_eval - no code execution)."""
    assert CODEX_SKILLS_PY.is_file(), f"{CODEX_SKILLS_PY} is missing"
    src = CODEX_SKILLS_PY.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(CODEX_SKILLS_PY))

    assign_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "literal_rules":
                    assign_node = node
                    break
        if assign_node is not None:
            break

    assert assign_node is not None, "could not find `literal_rules = [...]` in scripts/codex-skills.py"
    assert isinstance(assign_node.value, ast.List), "literal_rules is not a list literal"

    tuples = []
    for elt in assign_node.value.elts:
        assert isinstance(elt, ast.Tuple), f"literal_rules entry is not a tuple: {ast.dump(elt)[:120]}"
        tuples.append(tuple(ast.literal_eval(e) for e in elt.elts))
    return tuples


def test_codex_literal_rules_replacements_never_contain_old_names() -> None:
    tuples = _extract_literal_rules_tuples()
    assert len(tuples) >= 14, f"expected at least 14 literal_rules tuples, found {len(tuples)}"

    failures = []
    for i, tup in enumerate(tuples):
        assert len(tup) >= 3, f"literal_rules[{i}] has fewer than 3 elements: {tup}"
        replacement = tup[2]
        assert isinstance(replacement, str), f"literal_rules[{i}][2] is not a string: {replacement!r}"
        hit_names = [name for name in OLD_NAMES if name in replacement]
        if hit_names:
            failures.append(
                f"literal_rules[{i}] REPLACEMENT contains old tool name(s) {hit_names}: {replacement!r}"
            )

    assert not failures, (
        "scripts/codex-skills.py literal_rules REPLACEMENT strings must never contain an old "
        "agentic-* tool name (the PATTERN half may - it exists to match un-renamed content/** "
        "text - but the REPLACEMENT is entirely codex-authored):\n" + "\n".join(failures)
    )


def test_codex_generated_identity_commands_use_ds_identity() -> None:
    for path in (CODEX_AGENTS_MD, CODEX_METHODOLOGY_MD):
        assert path.is_file(), f"{path} is missing - run `.codex/build.sh` before this test"
        text = path.read_text(encoding="utf-8")

        # literal_rules[0]: the identity resolve-hook operational command.
        assert 'ds-identity resolve-hook --cwd "$AE_PROJECT_DIR"' in text, (
            f"{path}: expected renamed resolve-hook command not found"
        )
        assert 'agentic-identity resolve-hook --cwd "$AE_PROJECT_DIR"' not in text, (
            f"{path}: old-name resolve-hook command leaked into generated output"
        )

    # literal_rules[5]: the confirm/correct block only renders into
    # .codex/AGENTS.md in the current build (it is not tracked by the
    # skill-compatibility.yml inventory at all - its occurring span is
    # claimed by an earlier pass when assembling METHODOLOGY.md - so this
    # assertion is scoped to AGENTS.md only, not both files).
    agents_text = CODEX_AGENTS_MD.read_text(encoding="utf-8")
    assert "Confirm (global/project): ds-identity confirm --scope" in agents_text, (
        f"{CODEX_AGENTS_MD}: expected renamed confirm/correct block not found"
    )
    assert "Confirm (global/project): agentic-identity confirm --scope" not in agents_text, (
        f"{CODEX_AGENTS_MD}: old-name confirm/correct block leaked into generated output"
    )


# The pinned residue set the module docstring's "known exception" claim
# depends on: (file, token) pairs for any `agentic-<word>` string under
# content/** that is NOT the protected "dinostack" skill noun or
# one of its protected marker extensions (agentic-engineering-config,
# dinostack-profile, dinostack-preset). Independently
# re-derived, not copied from OLD_NAMES above.
#
# `content/project-scaffolding.yml`'s `bin/agentic-migrate` occurrences
# (all 5, across its Purpose/Public API/Downstream/Failure modes manifest
# fields) were renamed to `bin/ds-migrate` as part of the MINOR 3 fix in
# the same review round that added this test (DS-90 Unit 5 review) - its
# applied content (gitignore patterns, seed files below the header) never
# referenced the old name, so nothing was deferred there. That file
# therefore no longer appears in this residue set.
#
RESIDUE_TOKEN_PATTERN = re.compile(r"agentic-[a-zA-Z][a-zA-Z0-9-]*")
# Exact protected token set - NOT a prefix check. A prefix check
# (`token.startswith("dinostack")`) silently drops any token
# that merely BEGINS with the protected noun, e.g. a hypothetical
# `dinostack-doctor` would be masked even though it is not one
# of the actually-protected markers. Verified empirically: injecting
# `dinostack-doctor` into content/ left the old prefix-based
# check GREEN.
PROTECTED_TOKENS = {
    "dinostack",
    "dinostack-profile",
    "dinostack-preset",
    "agentic-engineering-config",
    # As of the skill-namespace rename (agentic-engineering -> dinostack),
    # "agentic-engineering" itself is a second, deliberately-preserved noun:
    # the config filename stem (agentic-engineering.json,
    # agentic-engineering-config.json) and the activation marker strings
    # (agentic-engineering: opt-in/opt-out, -profile:, -preset:) are
    # explicitly out of scope for that rename - those markers live in
    # consumer repos we do not control, so renaming them would silently
    # change activation state in projects we never touch. The
    # /ds-update-agentic-engineering command name is likewise unaffected.
    "agentic-engineering",
    "agentic-engineering-profile",
    "agentic-engineering-preset",
}
EXPECTED_RESIDUE_SET: set[tuple[str, str]] = {
    # DS-agentic-repair (phantom .agentic/ tree cleanup, post-PR-#745):
    # the brief-mandated CLI name `bin/ds-agentic-repair` intrinsically
    # contains the substring "agentic-repair", which the token pattern
    # below matches regardless of the "ds-" prefix immediately preceding
    # it (the pattern has no left-boundary anchor on "ds-"). This is NOT
    # a stale pre-rename `agentic-*` tool name surviving in content/ - the
    # tool was born with its "ds-" prefix and never had an old
    # `agentic-agentic-repair`-style identity to rename FROM (its
    # `bin/agentic-agentic-repair` compat symlink is the alias TARGET
    # convention every ds-* tool gets, per test_ds_rename_regression.py,
    # not a leftover primary name). content/references/events-log.md and
    # content/sections/09-events-log.md are its two content/** mentions -
    # the reference doc's Downstream/Append-discipline entries and the
    # section's Writer-scope sentence respectively (round-2 rework of
    # DS-agentic-repair added it there as the sixth writer).
    ("content/references/events-log.md", "agentic-repair"),
    ("content/sections/09-events-log.md", "agentic-repair"),
}


def test_content_residue_set_pinned_to_known_exceptions() -> None:
    """Scans every file under content/** for `agentic-<word>` tokens,
    excludes the protected `dinostack` skill noun and its marker
    extensions, and asserts the remaining (file, token) set is exactly
    EXPECTED_RESIDUE_SET - no more, no fewer. The set held exactly one
    prior exception (`content/references/planning-artifacts.md`,
    `agentic-factory`, a worked-example track name that named an
    operator's private repo and was neutralized to a generic name,
    dropping the set back to empty) before the `("content/references/
    events-log.md", "agentic-repair")` entry above was added - see that
    entry's own comment for why it is a substring artifact of a NEW,
    brief-mandated `ds-*` tool name, not a stale pre-rename residue. Any
    OTHER stray old name anywhere under content/** turns this RED; adding
    a new exception requires updating this set to match, which is the
    point: the residue set can no longer silently drift out of sync with
    what the docstring claims."""
    assert CONTENT_DIR.is_dir(), f"{CONTENT_DIR} is missing"

    found: set[tuple[str, str]] = set()
    for path in CONTENT_DIR.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # pragma: no cover - defensive
            continue
        rel = str(path.relative_to(REPO_ROOT))
        for match in RESIDUE_TOKEN_PATTERN.finditer(text):
            token = match.group(0)
            if token in PROTECTED_TOKENS:
                continue
            found.add((rel, token))

    assert found == EXPECTED_RESIDUE_SET, (
        "content/** residue set of unprotected agentic-* tokens has drifted from the "
        f"pinned expectation.\nExpected: {sorted(EXPECTED_RESIDUE_SET)}\n"
        f"Found:    {sorted(found)}\n"
        f"Added:    {sorted(found - EXPECTED_RESIDUE_SET)}\n"
        f"Missing:  {sorted(EXPECTED_RESIDUE_SET - found)}"
    )


# --- Sibling-product brand-name guard (round-2 review, Finding 1) --------
#
# A prior commit scrubbed a sibling product's brand name out of this public
# repo (docs/, content/, and every adapter dir). Nothing pinned that the
# name stays out, and the residue sweep above is deliberately scoped to
# content/ only - it would not catch a reintroduction under docs/ (which is
# hand-authored, not generated from content/) or under an adapter dir such
# as .hermes/SKILL.md (which aggregates every command and is a documented
# silent-revert vector - see AGENTS.md "Aggregate generated files revert
# across PRs"). This closes that gap with a whole-tracked-tree scan.


def _tracked_repo_files() -> list[Path]:
    """Every git-tracked file in the repo, via `git ls-files -z` (NUL
    separated, so filenames containing spaces or newlines are handled
    correctly). Deliberately git-tracked-files-based rather than a
    filesystem walk: `git ls-files` gives the exclusions this guard needs
    for free, because none of them are ever tracked - `.git/` itself, the
    gitignored `.agentic/**` runtime tree (except the one carved-out
    `team.yml`, which cannot contain a brand-name residue), and gitignored
    `node_modules/` (which is exactly where an unrelated vendored file
    happens to share the brand name in its filename - see the module-level
    docstring on that collision). A filesystem walk would instead scan
    whatever untracked local junk happens to be sitting in the worktree
    (editor scratch files, an accidentally-materialized node_modules/
    tree) and would have to hand-exclude all of the above, which is
    exactly the kind of hand-maintained exclusion list that goes stale.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout
    return [REPO_ROOT / p for p in out.decode("utf-8", errors="ignore").split("\0") if p]


# The forbidden brand string is built from character codes rather than
# written as a string literal on purpose: this test file is itself part of
# the tracked tree the scan below walks, so a literal occurrence of the
# brand name in this source file would make the guard trip over its OWN
# source and fail unconditionally the moment it was added. Do NOT "clean
# this up" into a plain string literal - that reintroduces exactly the
# self-triggering bug this comment exists to prevent.
_FORBIDDEN_BRAND_TOKEN = "".join(chr(c) for c in (72, 101, 108, 105, 111, 115))


# Floor on the number of files `git ls-files -z` must enumerate before this
# guard's scan is trusted. The tree currently has ~1163 tracked files; this
# is set well below that (not a maintenance tripwire) purely to catch the
# `git ls-files` call itself failing or returning empty - a scan over zero
# files passes vacuously having checked nothing, per this repo's "green
# often means the check did not run" lesson.
MIN_EXPECTED_TRACKED_FILE_COUNT = 500


def test_no_sibling_product_brand_name_in_tracked_tree() -> None:
    """Scans every git-tracked file in the repo (not just content/, and not
    just adapter dirs) for the sibling-product brand name, matched
    case-insensitively (mirrors the case-insensitive `git grep -a -i`
    verification this program is expected to satisfy). This repo is public;
    the sibling product is unreleased and non-open-source and must never be
    named here."""
    token_lower = _FORBIDDEN_BRAND_TOKEN.lower()
    tracked_files = _tracked_repo_files()
    assert len(tracked_files) >= MIN_EXPECTED_TRACKED_FILE_COUNT, (
        f"`git ls-files -z` enumeration itself failed or returned suspiciously few files "
        f"({len(tracked_files)} < {MIN_EXPECTED_TRACKED_FILE_COUNT}) - this guard would "
        "otherwise pass vacuously having scanned nothing"
    )

    failures = []
    for path in tracked_files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except IsADirectoryError:
            # Expected: a small number of tracked entries are symlinks to
            # directories (their real contents are tracked and scanned
            # separately via their own paths).
            continue
        if token_lower in text.lower():
            failures.append(str(path.relative_to(REPO_ROOT)))

    assert not failures, (
        "sibling-product brand name found in tracked file(s) - this repo is public "
        "and must never reference the unreleased sibling product by name:\n"
        + "\n".join(sorted(failures))
    )


EXTRA_TESTS = [
    test_bin_scripts_do_not_self_identify_with_old_names,
    test_codex_literal_rules_replacements_never_contain_old_names,
    test_codex_generated_identity_commands_use_ds_identity,
    test_content_residue_set_pinned_to_known_exceptions,
    test_no_sibling_product_brand_name_in_tracked_tree,
]


if __name__ == "__main__":
    failures = 0
    for t in EXTRA_TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {t.__name__}: {exc}")
    if failures:
        sys.exit(1)
    print("All tests passed.")
