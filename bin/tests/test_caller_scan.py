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
    one. A census of the swept trees found 624 bare fences against 119
    `bash` ones, overwhelmingly output samples and JSON, so that reading
    manufactured callers - and the empty info string also inverted the fence
    state machine (see the next test). If this residual is ever closed, it
    must be closed WITHOUT reintroducing either effect.
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
# --------------------------------------------------------------------------

def test_tool_itself_is_excluded_by_exact_path_not_prefix():
    assert "bin/ds-cleanup-worktrees" in caller_scan.EXCLUDED_EXACT
    # A future sibling sharing the prefix must NOT be silently excluded.
    sibling = "bin/ds-cleanup-worktrees-all"
    assert sibling not in caller_scan.EXCLUDED_EXACT
    assert not sibling.startswith(caller_scan.EXCLUDED_DIRS)


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
