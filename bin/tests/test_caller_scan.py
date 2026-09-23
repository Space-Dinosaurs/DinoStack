"""Purpose: pin `caller_scan`'s invocation predicate and fence scan against
         the shapes three review rounds found it getting wrong. DS-245's
         rubric R3 rests entirely on `check_unattended_callers_carry_floor`,
         and that check rests entirely on this predicate; until this file
         existed, nothing committed exercised it and every defect in it was
         found by a reviewer hand-injecting a shape.

         The three defects this file would have caught, each now a case
         below: a bare `"$DS_CLEANUP_BIN"` skipped because no flag followed
         it (round 1, CM1); an invocation in a fence the scan would not read
         (round 1, CM1); and a non-shell fence's CLOSING ``` read as OPENING
         an executable region, which cost 836 executable lines in one file
         while inventing 2040 phantom ones (round 2, CM2-1).

Public API: none (pytest module).

Upstream deps: bin/tests/caller_scan.py, imported via the repo-root-relative
               path this file sits in. pytest.

Downstream consumers: CI - `python3 -m pytest bin/tests/` auto-collects it,
                      which is the `bin-tests` workflow job and
                      `scripts/check-local.sh`'s pytest gate.

Failure modes: a case fails when the predicate accepts a line that is not a
               mutating invocation, rejects one that is, or when the fence
               scan disagrees with hand-marked expectations.

Performance: pure string work, no I/O, no git; milliseconds.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import caller_scan  # noqa: E402


# --------------------------------------------------------------------------
# is_invocation: shapes that ARE a command-position invocation.
#
# Every one of these, written without a --dry-run/--count-only/--report
# flag, removes worktrees. `bare_bin_no_flags` and `path_form` are the two
# the flag-requiring predicate of round 0/1 skipped.
# --------------------------------------------------------------------------
INVOCATIONS = [
    ("bare_bin_no_flags", '  "$DS_CLEANUP_BIN"'),
    ("bare_bin_flagged", '  "$DS_CLEANUP_BIN" --explain --measure-size'),
    ("unbraced_var", '  $DS_CLEANUP_BIN --explain'),
    ("braced_var", '  "${DS_CLEANUP_BIN}" --explain'),
    ("bare_name", '        ds-cleanup-worktrees --repo "$REPO_ROOT" \\'),
    ("path_form", '  python3 "$REPO_DIR/bin/ds-cleanup-worktrees" --explain'),
    ("var_assignment_prefix", '  FOO=1 ds-cleanup-worktrees --explain'),
    ("interpreter_prefix", '  python3 "$DS_CLEANUP_BIN" --explain'),
    ("wrapper_chain", 'out=$("$TIMEOUT_BIN" 5 python3 "$DS_CLEANUP_BIN" --explain)'),
    ("command_substitution", 'x="$(ds-cleanup-worktrees --explain)"'),
    ("subshell_at_line_start", '( ds-cleanup-worktrees --repo /tmp/x )'),
    ("after_and_and", 'cmd1 && ds-cleanup-worktrees --explain'),
    ("after_semicolon", 'cmd1 ; ds-cleanup-worktrees --explain'),
    ("after_pipe", 'cmd1 | ds-cleanup-worktrees --explain'),
    ("then_branch", 'if x; then ds-cleanup-worktrees --explain; fi'),
]

# --------------------------------------------------------------------------
# is_invocation: shapes that are NOT an invocation. A false positive here is
# as damaging as a false negative - it reddens the gate on a doc edit and
# trains a maintainer to widen the allowlist to make it quiet.
# --------------------------------------------------------------------------
NON_INVOCATIONS = [
    ("command_v_probe", '  elif command -v ds-cleanup-worktrees >/dev/null 2>&1; then'),
    ("assignment_to_var", '  DS_CLEANUP_BIN="$REPO_DIR/bin/ds-cleanup-worktrees"'),
    ("assignment_bare", '_ds_cleanup_worktrees="$SCRIPT_DIR/ds-cleanup-worktrees"'),
    ("var_guard_test", '  if [[ -n "${DS_CLEANUP_BIN:-}" ]]; then'),
    ("echo_prose", '  echo "WARNING: ds-cleanup-worktrees not found on PATH"'),
    ("docstring_crossref", '    bin/ds-cleanup-worktrees) so it needs no new `.gitignore` carve-out'),
    ("docstring_crossref_possessive", "     bin/ds-cleanup-worktrees's telemetry-salvage guard"),
    ("docstring_crossref_conjunction", '     bin/ds-cleanup-worktrees and bin/ds-branch-prune use'),
    ("slash_command_in_help", '  /ds-cleanup-worktrees           Remove stale subagent worktrees.'),
    ("prose_backtick", 'Run `ds-cleanup-worktrees` when worktrees accumulate.'),
    ("sibling_binary", '  ds-cleanup-worktrees-all --explain'),
]


@pytest.mark.parametrize("label,line", INVOCATIONS, ids=[c[0] for c in INVOCATIONS])
def test_is_invocation_accepts(label, line):
    assert caller_scan.is_invocation(line), (label, line)


@pytest.mark.parametrize("label,line", NON_INVOCATIONS, ids=[c[0] for c in NON_INVOCATIONS])
def test_is_invocation_rejects(label, line):
    assert not caller_scan.is_invocation(line), (label, line)


# --------------------------------------------------------------------------
# Fence scan.
# --------------------------------------------------------------------------

def test_shell_fence_body_is_executable():
    lines = ["prose", "```bash", "IN_FENCE=1", "```", "more prose"]
    assert caller_scan.executable_lines(lines, True) == {3}


def test_non_shell_fence_body_is_not_executable():
    lines = ["prose", "```json", '{"a": 1}', "```", "more prose"]
    assert caller_scan.executable_lines(lines, True) == set()


def test_bare_fence_body_is_not_executable():
    """Accepted residual, pinned so it is a decision rather than a drift.

    Round 1 treated a bare fence as shell to catch an invocation written in
    one. Bare fences are overwhelmingly output samples and JSON, so that
    reading manufactured callers - and the empty info string also inverted
    the fence state machine (see the next test). If this residual is ever
    closed, it must be closed WITHOUT reintroducing either effect.

    The census supporting the first half lives beside the constant it
    justifies, in `caller_scan.SHELL_INFO`'s comment, together with the
    command that re-derives it. It is deliberately not restated here: the
    figure this docstring carried in 571f632b (624/119) was wrong - it
    counted fence DELIMITER lines, so every closing fence was tallied as a
    bare one - and two copies of a number is how one of them goes stale
    (DS-245 review round 3, finding 1).
    """
    lines = ["prose", "```", "ds-cleanup-worktrees --explain", "```"]
    assert caller_scan.executable_lines(lines, True) == set()


def test_shell_fence_after_non_shell_fence_stays_executable():
    """DS-245 round 2, CM2-1 - the exact regression, at minimum size.

    A one-variable state machine that also treats the empty info string as
    shell reads the ```json block's CLOSING fence as OPENING a bare
    executable fence. Everything after it inverts: the real ```bash body
    becomes prose and the surrounding prose becomes executable. Measured on
    content/commands/ds-implement-ticket.md, that cost all 836 genuinely
    executable lines and invented 2040 phantom ones.
    """
    lines = [
        "prose",          # 1
        "```json",        # 2
        '{"a": 1}',       # 3  not executable
        "```",            # 4  closes the json fence - must NOT open one
        "between",        # 5  not executable
        "```bash",        # 6
        "REAL=1",         # 7  executable
        "```",            # 8
        "after",          # 9  not executable
    ]
    assert caller_scan.executable_lines(lines, True) == {7}


def test_comment_lines_inside_a_shell_fence_are_skipped():
    lines = ["```bash", "# a comment", "REAL=1", "```"]
    assert caller_scan.executable_lines(lines, True) == {3}


def test_non_markdown_is_every_non_comment_line():
    lines = ["#!/bin/sh", "# comment", "real=1", "", "also=2"]
    assert caller_scan.executable_lines(lines, False) == {3, 4, 5}


def test_shell_info_excludes_the_empty_string():
    """A direct pin on the constant, so restoring "" is a loud change.

    `test_shell_fence_after_non_shell_fence_stays_executable` already fails
    if "" returns, because the two-variable machine plus "" still treats the
    json body as executable. This asserts the decision itself.
    """
    assert "" not in caller_scan.SHELL_INFO
    assert "bash" in caller_scan.SHELL_INFO


# --------------------------------------------------------------------------
# Exclusions (round 1, cm3).
#
# The version of this section shipped in 571f632b asserted only on the
# CONSTANTS - that the tool's path is in EXCLUDED_EXACT and a sibling is not.
# That is true under either comparison, so it certified a hazard it could not
# detect: changing `find_mutating`'s `path in EXCLUDED_EXACT` to
# `path.startswith(EXCLUDED_EXACT)` - the exact silent swallow the constant's
# own comment warns about - passed all 35 cases (DS-245 review round 3,
# finding 2). The test below drives `find_mutating` against a scratch repo
# that actually contains such a sibling, so the comparison itself is what is
# under test.
# --------------------------------------------------------------------------

def test_excluded_exact_names_the_tool_and_not_its_siblings():
    """Constants only - retained as documentation of intent.

    This cannot catch a prefix-vs-exact regression on its own; that is
    `test_sibling_binary_sharing_the_tools_path_prefix_is_still_scanned`'s
    job. Kept so the intent is stated next to the constant it describes.
    """
    assert "bin/ds-cleanup-worktrees" in caller_scan.EXCLUDED_EXACT
    sibling = "bin/ds-cleanup-worktrees-all"
    assert sibling not in caller_scan.EXCLUDED_EXACT
    assert not sibling.startswith(caller_scan.EXCLUDED_DIRS)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo)] + list(args), check=True,
                   capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_sibling_binary_sharing_the_tools_path_prefix_is_still_scanned(tmp_path):
    """DS-245 review round 3, finding 2 - drives the comparison, not the constants.

    Reddening mutation (EXECUTED): in `caller_scan.find_mutating`, change
        if path in EXCLUDED_EXACT or path.startswith(EXCLUDED_DIRS):
    to
        if path.startswith(EXCLUDED_EXACT) or path.startswith(EXCLUDED_DIRS):
    `bin/ds-cleanup-worktrees-all` then falls inside the exclusion and its
    mutating invocation disappears from the scan, so the assertion below that
    it IS found fails. Before this test existed that mutation was silent.
    """
    repo = tmp_path / "scratch"
    # All four swept paths must exist: a pathspec naming a directory that is
    # not in the index makes `git grep` fail rather than return no matches.
    for name in caller_scan.SWEPT_PATHS:
        (repo / name).mkdir(parents=True)
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))
    _git(repo, "config", "user.email", "scan@example.com")
    _git(repo, "config", "user.name", "scan")

    # The tool itself: mentions its own name, and MUST be excluded.
    (repo / "bin" / "ds-cleanup-worktrees").write_text(
        '#!/usr/bin/env python3\n'
        'print("ds-cleanup-worktrees: mode=dry-run")\n'
    )
    # A sibling whose path shares the tool's path as a PREFIX, carrying a
    # real mutating invocation. It is a caller and must be scanned.
    (repo / "bin" / "ds-cleanup-worktrees-all").write_text(
        '#!/bin/bash\n'
        'ds-cleanup-worktrees --repo "$1" --explain\n'
    )
    # Keep the other swept dirs non-empty so git tracks them.
    for name in ("content", "hooks", "scripts"):
        (repo / name / "placeholder.md").write_text("no invocation here\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")

    found = {path for path, _lineno, _raw in caller_scan.find_mutating(str(repo))}

    assert "bin/ds-cleanup-worktrees-all" in found, (
        "a sibling binary sharing the tool's path prefix was dropped from the "
        "scan - EXCLUDED_EXACT must be compared with == , never startswith"
    )
    assert "bin/ds-cleanup-worktrees" not in found, (
        "the tool's own file must stay excluded; it is not one of its callers"
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_test_directories_are_excluded_by_prefix(tmp_path):
    """The other half of the split: EXCLUDED_DIRS IS a prefix comparison.

    Reddening mutation (EXECUTED): change `path.startswith(EXCLUDED_DIRS)` to
    `path in EXCLUDED_DIRS`; the fixture invocation under `bin/tests/` is then
    scanned and this assertion fails.
    """
    repo = tmp_path / "scratch"
    for name in caller_scan.SWEPT_PATHS:
        (repo / name).mkdir(parents=True)
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))
    _git(repo, "config", "user.email", "scan@example.com")
    _git(repo, "config", "user.name", "scan")

    (repo / "bin" / "tests").mkdir()
    (repo / "bin" / "tests" / "test_fixture.sh").write_text(
        '#!/bin/bash\n'
        'ds-cleanup-worktrees --repo "$1" --explain\n'
    )
    for name in ("content", "hooks", "scripts"):
        (repo / name / "placeholder.md").write_text("no invocation here\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")

    found = {path for path, _lineno, _raw in caller_scan.find_mutating(str(repo))}
    assert "bin/tests/test_fixture.sh" not in found, (
        "a scratch-fixture invocation under bin/tests/ is not an operational "
        "caller and must stay excluded"
    )


# --------------------------------------------------------------------------
# Feeder robustness (qa-engineer against 571f632b, non-blocking).
#
# `git grep` reports a matching BINARY file as `Binary file <path> matches` -
# a line with no `:<lineno>:` fields. Parsing it raised a bare ValueError,
# outside `find_mutating`'s documented fail-loud contract. QA hit it only
# because its scratch snapshot tracked a `__pycache__` this repo gitignores,
# so it was unreachable on the real tree - but that unreachability rests on
# .gitignore content, which is not this module's invariant.
# --------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_tracked_binary_matching_the_feeder_is_skipped_not_fatal(tmp_path):
    """A matching binary must be skipped, leaving real callers found.

    Reddening mutation (EXECUTED): drop `-I` from the `git grep` argv in
    `caller_scan._grep_hits`. `git grep` then emits `Binary file
    bin/blob.pyc matches`, which this scan cannot parse, and find_mutating
    raises instead of returning - so the assertion below fails.
    """
    repo = tmp_path / "scratch"
    for name in caller_scan.SWEPT_PATHS:
        (repo / name).mkdir(parents=True)
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))
    _git(repo, "config", "user.email", "scan@example.com")
    _git(repo, "config", "user.name", "scan")

    (repo / "bin" / "caller.sh").write_text(
        '#!/bin/bash\n'
        'ds-cleanup-worktrees --repo "$1" --explain\n'
    )
    # A tracked binary whose BYTES contain the token - exactly the shape a
    # committed __pycache__ produced for QA.
    (repo / "bin" / "blob.pyc").write_bytes(
        b"\x00\x01\x02ds-cleanup-worktrees --explain\x00\xff\xfe"
    )
    for name in ("content", "hooks", "scripts"):
        (repo / name / "placeholder.md").write_text("no invocation here\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")

    found = {path for path, _lineno, _raw in caller_scan.find_mutating(str(repo))}
    assert found == {"bin/caller.sh"}, (
        "a tracked binary matching the feeder must be skipped, not crash the "
        "scan and not be reported as a caller"
    )


def test_unparseable_feeder_line_raises_the_documented_runtime_error(monkeypatch):
    """Any non-`<path>:<lineno>:<text>` line takes the fail-loud path.

    Reddening mutation (EXECUTED): delete the `len(parts) != 3 or not
    parts[1].isdigit()` guard in `_grep_hits`. The bare `line.split(":", 2)`
    then raises ValueError, which is not RuntimeError, so pytest.raises
    below does not catch it and the test errors.
    """
    import subprocess as _sp

    class _Fake:
        returncode = 0
        stdout = "Binary file bin/blob.pyc matches\n"
        stderr = ""

    monkeypatch.setattr(caller_scan.subprocess, "run", lambda *a, **k: _Fake())
    with pytest.raises(RuntimeError) as excinfo:
        caller_scan.find_mutating("/nonexistent-root")
    assert "Binary file" in str(excinfo.value)
    assert "<path>:<lineno>:<text>" in str(excinfo.value)
    assert _sp is not None  # keeps the import meaningful to linters


# --------------------------------------------------------------------------
# Which guard actually rejects which shape (DS-245 review round 3, finding 3).
#
# `PROBE_RE` and the bare-name lookbehind are both DEFENSE IN DEPTH, not the
# mechanism: deleting either leaves every case above green, which the
# reviewer executed. The two tests below pin the attribution itself, so the
# comments in `caller_scan.py` cannot drift back to claiming those guards do
# work they do not do.
# --------------------------------------------------------------------------

def test_command_v_probe_is_rejected_by_cmd_prefix_too():
    """`CMD_PREFIX_RE`, not `PROBE_RE`, is sufficient on its own here.

    `command` is deliberately absent from `_WRAPPER`, so a prefix ending in
    `command -v ` cannot be consumed and the position is not command
    position. Reddening mutation: add `command` to `_WRAPPER` - the prefix
    then matches and `PROBE_RE` becomes the only remaining guard, which is
    exactly the trigger `caller_scan.PROBE_RE`'s comment names.
    """
    before = "  elif command -v "
    assert not caller_scan.CMD_PREFIX_RE.search(before)
    assert caller_scan.PROBE_RE.search(before)
    assert "command" not in caller_scan._WRAPPER


def test_slash_command_is_rejected_by_cmd_prefix_too():
    """The lookbehind rejects it first; `CMD_PREFIX_RE` would anyway.

    A prefix ending in `/` can never match, because the prefix must end
    exactly at the token and no alternative consumes a trailing slash.
    Reddening mutation: give `CMD_PREFIX_RE` an alternative that consumes a
    bare path segment - the lookbehind then becomes load-bearing alone.
    """
    for before in ("  /", "x=$(/", "; /", "  bin/"):
        assert not caller_scan.CMD_PREFIX_RE.search(before), before
    # And with the lookbehind in place the token does not even match.
    line = "  /ds-cleanup-worktrees           Remove stale subagent worktrees."
    assert not list(caller_scan.TOKEN_RE.finditer(line))


# --------------------------------------------------------------------------
# The feeder pattern must see a path-form invocation at all (round 1, CM1).
# --------------------------------------------------------------------------

def test_feeder_pattern_matches_a_path_form_line():
    import re

    line = 'python3 "$REPO_DIR/bin/ds-cleanup-worktrees" --explain'
    assert re.search(caller_scan.PATTERN, line), (
        "the feeder pattern cannot see a path-form invocation, so any "
        "equality asserted downstream is vacuous for that shape"
    )
