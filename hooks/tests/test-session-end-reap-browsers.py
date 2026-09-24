#!/usr/bin/env python3
"""
Purpose: Regression test for hooks/session-end-reap-browsers.py, the
         SessionEnd hook that reaps orphaned agent-launched Chrome
         browsers. Four things are asserted, in order of what they protect:

         1. THE FIXTURE (plan gate V4). A synthetic process table shaped
            like `ps -Aww -o pid=,ppid=,command=` output, holding every
            process shape the selector must distinguish: an orphaned MCP
            browser, this session's MCP browser, ANOTHER session's MCP
            browser, a live `marp --preview` browser, a live Playwright
            browser, the operator's own Chrome main process, an orphaned
            `agent-browser` browser, a live one, a `--type=` helper, and an
            unrelated process. Exactly three must be selected. The marp and
            Playwright rows are NAMED SAFETY TARGETS: they carry
            `--remote-debugging-pipe` (a puppeteer transport marker shared
            with the MCP, NOT an MCP marker) and a withdrawn earlier draft
            of this unit selected them, which would have SIGKILLed the
            operator's live slide previews at every session end.

            A second table carries the rows whose ABSENCE let a green
            fixture coexist with an unsafe selector: the MCP's OWN
            processes (the `npm exec` wrapper, the stdio server, the
            telemetry watchdog, and the package's bare argv0), plus a
            differently-named launcher whose name merely contains `chrome`
            and two verbatim live non-browser rows (an unrelated Electron
            app's crashpad handler, and `WindowServer`). All of them carry
            `chrome` inside their executable region and would be selected by
            a substring test.

         2. THE MUTATIONS, made to fire (plan gate V4's four named
            mutations, plus three this test adds). The fixture passing is
            not evidence the predicate is safe - the withdrawn draft's
            fixture passed while its predicate was unsafe - so each
            conjunct is rewritten out of the hook's SOURCE in memory, the
            mutated module is loaded, and the mutated selector is asserted
            to produce the WRONG answer against the SAME fixture. A mutation
            that stops reddening (because an anchor moved, or a conjunct
            became unreachable) fails this test rather than silently
            passing.

         3. THE REQUIRED PROPERTIES, each as its own case with a named
            mutation that reddens it: an MCP process shape is never
            selected however its argv is spelled; a real Chrome carrying the
            fingerprint still is; the fingerprint alone never makes a
            non-browser selectable; and unrelated live rows are not
            selected.

         4. THE FAILURE PATHS (plan gate V5b). The hook is run as a real
            subprocess with `ps` missing from PATH, with a malformed
            payload, and with an empty or failing process table; every case
            must exit 0, because a non-zero exit at SessionEnd is the
            blocking code.

         5. THE FIRE RECORD (plan gate V5c). One REAL reap is performed (a
            live child process described by a shimmed `ps` as an orphaned
            MCP browser), and the row it writes must carry the fire-log
            module's canonical schema and name the arm that fired. The
            writer is pinned separately: the same scenario run against a
            copy of the hook with hooks/lib/ absent must write NO row at
            all, which is what distinguishes a row written through
            hooks/lib/enforcement_log.py from a hand-written JSONL line.

         NOT asserted here: this hook's own SessionEnd registration and its
         bin/ds-doctor entry. Those read `.claude/install.sh`'s real output
         and live in bin/tests/test_install_session_end_reap_browsers.sh -
         running the real installer from this file would need node (absent
         from the Python-hook-test CI job) and would rebuild adapters.

Public API: ./hooks/tests/test-session-end-reap-browsers.py
            Exits 0 on all pass, 1 on any failure.

Upstream deps: python3 stdlib only (importlib, json, os, re, shutil,
               subprocess, sys, tempfile, time). No third-party imports,
               no network.

Downstream consumers: the `hooks-python-tests` CI job (the
                      `hooks/tests/test-*.py` glob in
                      .github/workflows/bin-tests.yml), and
                      hooks/tests/test-hooks-pep604-guard.py's runtime
                      smoke loop, which executes this file.

Failure modes: any failed assertion is collected and reported, and the
               process exits 1. Every spawned process is killed and every
               temp directory removed in a finally block.

Performance: a few seconds (a handful of short subprocess runs); no
             network, no sleeps beyond bounded poll loops.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HOOK_PATH = os.path.realpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "session-end-reap-browsers.py")
)
LIB_PATH = os.path.join(os.path.dirname(HOOK_PATH), "lib", "enforcement_log.py")

FIXTURE_HOME = "/home/fixture-user"
FIXTURE_MCP_ROOT = FIXTURE_HOME + "/.cache/chrome-devtools-mcp"

# Real Chrome main-process argv shapes, abbreviated the way `ps` shows them.
# The executable paths deliberately contain SPACES, exactly as the live
# macOS ones do (`.../MacOS/Google Chrome for Testing`) - that is what makes
# the executable-region anchor load-bearing rather than cosmetic.
CHROME_GUI = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
              " --allow-pre-commit-input --enable-automation")
CHROME_TESTING = ("/var/folders/ab/agent-browser/Google Chrome for Testing.app"
                  "/Contents/MacOS/Google Chrome for Testing"
                  " --remote-debugging-port=0 --headless=new")
MCP_BROWSER_ARGS = ("--user-data-dir=%s/chrome-profile"
                    " --remote-debugging-pipe about:blank" % FIXTURE_MCP_ROOT)

# ---------------------------------------------------------------------------
# Table 1: the ten named rows plan gate V4 specifies. Exactly three are
# selected (pids 1001, 1002, 1007).
# ---------------------------------------------------------------------------

ORPHANED_MCP_PID = 1001
OWN_SESSION_MCP_PID = 1002
OTHER_SESSION_MCP_PID = 1003
MARP_PID = 1004          # NAMED SAFETY TARGET
PLAYWRIGHT_PID = 1005    # NAMED SAFETY TARGET
OPERATOR_CHROME_PID = 1006
ORPHANED_AB_PID = 1007
LIVE_AB_PID = 1008
MCP_HELPER_PID = 1009
UNRELATED_PID = 1010

FIXTURE_ROWS = [
    # 1 - orphaned MCP browser: its MCP parent (900) is gone.
    (ORPHANED_MCP_PID, 900, CHROME_GUI + " " + MCP_BROWSER_ARGS),
    # 2 - THIS session's MCP browser: a live MCP ancestor, under our harness.
    (OWN_SESSION_MCP_PID, 901, CHROME_GUI + " " + MCP_BROWSER_ARGS),
    # 3 - ANOTHER session's MCP browser: live ancestor under a foreign
    #     harness that shares the terminal at pid 700.
    (OTHER_SESSION_MCP_PID, 903, CHROME_GUI + " " + MCP_BROWSER_ARGS),
    # 4 - SAFETY TARGET: live `marp --preview` slide deck, pipe flag, live
    #     marp parent. The withdrawn draft selected this.
    (MARP_PID, 905, CHROME_GUI + " --remote-debugging-pipe"
     " --user-data-dir=/var/folders/ab/T/marp-cli-7YGTvrOnyd"),
    # 5 - SAFETY TARGET: live Playwright browser, pipe flag, live driver.
    (PLAYWRIGHT_PID, 906, CHROME_GUI + " --remote-debugging-pipe"
     " --user-data-dir=/var/folders/cd/T/playwright_chromiumdev_profile-9f2c"),
    # 6 - the operator's own Chrome main: no --user-data-dir at all.
    (OPERATOR_CHROME_PID, 1, CHROME_GUI
     + " --origin-trial-disabled-features=CanvasTextNg"),
    # 7 - orphaned agent-browser browser: its daemon (908) is gone.
    (ORPHANED_AB_PID, 908, CHROME_TESTING
     + " --user-data-dir=/var/folders/ef/T/agent-browser-chrome-deadbeef"),
    # 8 - live agent-browser browser: daemon 909 is alive.
    (LIVE_AB_PID, 909, CHROME_TESTING
     + " --user-data-dir=/var/folders/gh/T/agent-browser-chrome-cafebabe"),
    # 9 - a --type= helper of row 1 (the flag is inherited from the main).
    (MCP_HELPER_PID, ORPHANED_MCP_PID, CHROME_GUI + " --type=renderer "
     + MCP_BROWSER_ARGS),
    # 10 - unrelated.
    (UNRELATED_PID, 500, "/usr/bin/unrelated-worker --serve --port 0"),
]

# ---------------------------------------------------------------------------
# Table 2: rows added beyond plan gate V4's named ten, each pinned by a
# mutation or an assertion below. Adding a row here is how a newly measured
# false-positive class gets locked down; none of them may be selected.
# ---------------------------------------------------------------------------

REPARENTED_AB_HELPER_PID = 1011
INCIDENTAL_GREP_PID = 1012

# The MCP's OWN process shapes. These are the rows whose absence let a
# passing fixture coexist with a selector that SIGKILLed them: every one of
# these carries the string `chrome` in its argv0 and, once the installer
# pins a profile root, the fingerprint in its argv too. A substring test on
# the executable region classified all of them as browsers.
MCP_WRAPPER_PID = 1013
MCP_SERVER_PID = 1014
MCP_WATCHDOG_PID = 1015
MCP_BARE_PID = 1018

# Live non-browser shapes measured on the development host. Both are
# classified as Chrome binaries by a substring test and by nothing else.
CHROME_CRASHPAD_PID = 1016
UNRELATED_LIVE_PID = 1017
CHROME_NAMED_LAUNCHER_PID = 1019

PINNED_ROWS = [
    # 11 - a reparented agent-browser HELPER (helpers are reparented to pid 1
    #      while their main lives - measured). Excluded only by the --type=
    #      conjunct; pinned by mutation (b).
    (REPARENTED_AB_HELPER_PID, 1, CHROME_TESTING
     + " --type=renderer"
     " --user-data-dir=/var/folders/ef/T/agent-browser-chrome-deadbeef"),
    # 12 - MEASURED HAZARD, not hypothetical: a process whose own argv embeds
    #      the profile fingerprint because the fingerprint was its ARGUMENT.
    #      Measured live on the development host while writing this hook - a
    #      `ps ... | grep -- '--user-data-dir=<fingerprint>'` pipeline put the
    #      fingerprint into the argv of its own `zsh -c` wrappers and its
    #      `ugrep` process. Such a row satisfies the profile half of Conjunct
    #      A and has no --type=, so it is excluded only by the argv0 half,
    #      which mutation (f) pins.
    (INCIDENTAL_GREP_PID, 9501, "ugrep -G --hidden -I"
     " --user-data-dir=%s/chrome-profile chrome-devtools-mcp/chrome-profile"
     % FIXTURE_MCP_ROOT),
    # 13 - the `npm exec` wrapper that launches the MCP server. Its argv0
    #      contains `chrome`; its argv carries the pinned profile root because
    #      it is the process the installer's flag edit reaches first.
    (MCP_WRAPPER_PID, 902, "npm exec chrome-devtools-mcp@latest --headless"
     " --user-data-dir=%s/chrome-profile" % FIXTURE_MCP_ROOT),
    # 14 - the MCP stdio server itself, at the argv it is SPAWNED with (the
    #      package's bin script, launched by the wrapper above). On macOS its
    #      own row is title-rewritten to `chrome-devtools-mcp` and hides this
    #      argv; it is modelled here because the predicate must not depend on
    #      that rewrite, and any launcher form that does expose it must still
    #      not be selected.
    (MCP_SERVER_PID, MCP_WRAPPER_PID,
     "node /home/fixture-user/.npm/_npx/1a2b/node_modules/chrome-devtools-mcp"
     "/build/src/index.js --headless"
     " --user-data-dir=%s/chrome-profile" % FIXTURE_MCP_ROOT),
    # 15 - the telemetry watchdog the MCP server spawns (measured live on the
    #      development host). Its argv0 contains `chrome` through the package
    #      path; it carries no profile flag, so this row pins the argv0 half
    #      rather than the profile half.
    (MCP_WATCHDOG_PID, MCP_SERVER_PID,
     "node /home/fixture-user/.npm/_npx/1a2b/node_modules/chrome-devtools-mcp"
     "/build/src/telemetry/watchdog/main.js --parent-pid=1014"
     " --app-version=1.10.1 --os-type=2"),
    # 16 - the server's own argv0, with no launcher in front of it and no
    #      absolute path anywhere in its executable region.
    (MCP_BARE_PID, MCP_WRAPPER_PID, "chrome-devtools-mcp --headless"
     " --user-data-dir=%s/chrome-profile" % FIXTURE_MCP_ROOT),
    # 17 - MEASURED (live, verbatim): a crashpad handler belonging to an
    #      unrelated Electron application. Its argv0 contains `chrome` and it
    #      carries no --type=, so a substring test calls it a browser.
    (CHROME_CRASHPAD_PID, 1,
     "/Applications/UA Connect.app/Contents/Frameworks/Electron Framework"
     ".framework/Helpers/chrome_crashpad_handler --no-rate-limit"
     " --monitor-self-annotation=ptype=crashpad-handler"
     " --handshake-fd=17"),
    # 18 - MEASURED (live, verbatim): an unrelated system process with a
    #      space-bearing executable region and a single-dash argument. Neither
    #      a browser nor an MCP server.
    (UNRELATED_LIVE_PID, 1,
     "/System/Library/PrivateFrameworks/SkyLight.framework/Resources"
     "/WindowServer -daemon"),
    # 19 - a DIFFERENTLY-NAMED launcher whose name merely contains `chrome`,
    #      carrying the fingerprint. The mechanism must not be a list of MCP
    #      package names: this row is excluded by argv0 identity, so nothing
    #      has to be added to any list when another such launcher appears.
    (CHROME_NAMED_LAUNCHER_PID, 1, "/usr/local/bin/chrome-launcher"
     " --user-data-dir=%s/chrome-profile" % FIXTURE_MCP_ROOT),
]

# ---------------------------------------------------------------------------
# Table 3: the live parents the ancestry walks need, plus this hook's own
# process chain. An unexpected selection here would be a fixture bug, not a
# selector bug, so they are kept separate from the two tables above.
# ---------------------------------------------------------------------------

SHARED_TERMINAL_PID = 700
OTHER_HARNESS_PID = 904
OWN_MCP_PID = 901
OTHER_MCP_PID = 903
OWN_HOOK_PID = 9500
OWN_WRAPPER_PID = 9501

SUPPORT_ROWS = [
    # The terminal BOTH sessions descend from. Measured live on the
    # development host: two concurrent Claude sessions shared exactly this
    # shape, so an arm (ii) that intersected full ancestor chains (rather
    # than stopping at the harness) would select the other session's
    # browser. Row 3's non-selection is what pins that boundary.
    (SHARED_TERMINAL_PID, 1,
     "/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal"),
    (902, SHARED_TERMINAL_PID,
     "claude --settings /home/fixture-user/.claude/settings.json"),
    (OTHER_HARNESS_PID, SHARED_TERMINAL_PID,
     "claude --settings /home/fixture-user/.claude/settings.json"),
    (OWN_MCP_PID, 902, "chrome-devtools-mcp"),
    (OTHER_MCP_PID, OTHER_HARNESS_PID, "npm exec chrome-devtools-mcp@latest"),
    (905, 1, "node /home/fixture-user/.bun/bin/marp --preview deck.md"),
    (906, 1, "node /home/fixture-user/node_modules/playwright/driver/node"),
    (909, 1, "/home/fixture-user/.hermes/hermes-agent/node_modules/"
     "agent-browser/bin/agent-browser-darwin-arm64"),
    (500, 1, "/usr/bin/launchd-helper --idle"),
    # This hook's own chain: hook -> wrapper shell -> harness. The harness
    # (902) is the boundary; 700 sits above it and is shared.
    (OWN_WRAPPER_PID, 902,
     "zsh -c source /home/fixture-user/.claude/snapshot.sh 2>/dev/null"),
    (OWN_HOOK_PID, OWN_WRAPPER_PID,
     "python3 /repo/hooks/session-end-reap-browsers.py"),
]

ALL_ROWS = FIXTURE_ROWS + PINNED_ROWS + SUPPORT_ROWS

EXPECTED_SELECTION_PIDS = (ORPHANED_MCP_PID, OWN_SESSION_MCP_PID,
                           ORPHANED_AB_PID)


def table_text(rows):
    return "\n".join("%d %d %s" % (pid, ppid, command)
                     for pid, ppid, command in rows) + "\n"


def load_hook(path=HOOK_PATH):
    spec = importlib.util.spec_from_file_location("reap_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_selection(module):
    """(selected dict, verdicts, own_chain) for the fixture table."""
    rows = module.parse_ps_table(table_text(ALL_ROWS))
    ppid_map = module._ppid_map(rows)
    command_map = module._command_map(rows)
    own_chain = module.resolve_own_chain(OWN_HOOK_PID, ppid_map, command_map)
    verdicts = module.classify_rows(rows, FIXTURE_MCP_ROOT, own_chain)
    selected = dict((v.row.pid, v.arm) for v in verdicts if v.arm)
    return selected, verdicts, own_chain


# ---------------------------------------------------------------------------
# 1. The fixture.
# ---------------------------------------------------------------------------

def test_fixture_selects_exactly_the_three_orphans():
    module = load_hook()
    selected, _, own_chain = fixture_selection(module)
    assert own_chain == [OWN_HOOK_PID, OWN_WRAPPER_PID, 902], (
        "resolve_own_chain did not stop at the harness process: %r. The "
        "walk must include the hook, the wrapper shell, and the first "
        "non-shell ancestor, and stop there - continuing upward would "
        "reach the shared terminal both sessions descend from." % (own_chain,)
    )
    assert len(FIXTURE_ROWS) == 10, (
        "plan gate V4 specifies a 10-row named fixture; it now has %d rows"
        % len(FIXTURE_ROWS)
    )
    assert selected == {
        ORPHANED_MCP_PID: module.ARM_ORPHANED_MCP,
        OWN_SESSION_MCP_PID: module.ARM_OWN_SESSION_MCP,
        ORPHANED_AB_PID: module.ARM_ORPHANED_CLI,
    }, "fixture selected %r, expected exactly the three orphans" % (selected,)
    assert set(selected) == set(EXPECTED_SELECTION_PIDS)


def test_fixture_never_selects_the_live_marp_or_playwright_browsers():
    """The two NAMED SAFETY TARGETS, asserted by name, and asserted to be
    rejected by the FINGERPRINT rather than by the ownership test."""
    module = load_hook()
    selected, verdicts, _ = fixture_selection(module)
    assert MARP_PID not in selected, (
        "the live `marp --preview` browser was selected - this is the exact "
        "regression the withdrawn first draft shipped (it carried "
        "--remote-debugging-pipe and no live MCP ancestor)"
    )
    assert PLAYWRIGHT_PID not in selected, (
        "the live Playwright browser was selected - same regression class"
    )
    by_pid = dict((v.row.pid, v) for v in verdicts)
    for pid, label in ((MARP_PID, "marp"), (PLAYWRIGHT_PID, "playwright")):
        assert by_pid[pid].note == "no_agent_browser_fingerprint", (
            "the %s row was rejected for the wrong reason (%r) - it must "
            "fail Conjunct A, the positive MCP profile fingerprint, not the "
            "ancestor test" % (label, by_pid[pid].note)
        )


def test_fixture_never_selects_live_other_session_operator_or_unrelated():
    module = load_hook()
    selected, verdicts, _ = fixture_selection(module)
    by_pid = dict((v.row.pid, v) for v in verdicts)
    for pid, label in (
        (OTHER_SESSION_MCP_PID, "another live session's MCP browser"),
        (OPERATOR_CHROME_PID, "the operator's own Chrome main process"),
        (LIVE_AB_PID, "a live agent-browser browser"),
        (MCP_HELPER_PID, "an MCP browser --type= helper"),
        (REPARENTED_AB_HELPER_PID, "a reparented agent-browser --type= helper"),
        (INCIDENTAL_GREP_PID, "a process carrying the fingerprint as an arg"),
        (UNRELATED_PID, "an unrelated process"),
        (MCP_WRAPPER_PID, "the npm exec wrapper that launches the MCP server"),
        (MCP_SERVER_PID, "the MCP stdio server"),
        (MCP_WATCHDOG_PID, "the MCP telemetry watchdog"),
        (MCP_BARE_PID, "the MCP server's own argv0 with no launcher"),
        (CHROME_CRASHPAD_PID, "a crashpad handler of an unrelated app"),
        (UNRELATED_LIVE_PID, "an unrelated system process"),
        (CHROME_NAMED_LAUNCHER_PID, "a differently-named chrome launcher"),
    ):
        assert pid not in selected, "%s (pid %d) was selected" % (label, pid)
    assert by_pid[OTHER_SESSION_MCP_PID].note == (
        "mcp_browser_not_owned_by_this_session"
    ), ("the other session's browser must be rejected by the ownership "
        "test, not by the fingerprint")
    assert by_pid[REPARENTED_AB_HELPER_PID].note == "browser_helper_process", (
        "the reparented agent-browser helper must be rejected by the --type= "
        "conjunct; got %r" % by_pid[REPARENTED_AB_HELPER_PID].note
    )
    for pid, label in (
        (INCIDENTAL_GREP_PID, "the fingerprint-as-argument row"),
        (MCP_WRAPPER_PID, "the npm exec wrapper"),
        (MCP_SERVER_PID, "the MCP server"),
        (MCP_WATCHDOG_PID, "the MCP watchdog"),
        (MCP_BARE_PID, "the bare MCP argv0"),
        (CHROME_CRASHPAD_PID, "the unrelated app's crashpad handler"),
        (UNRELATED_LIVE_PID, "the unrelated system process"),
        (CHROME_NAMED_LAUNCHER_PID, "the differently-named chrome launcher"),
    ):
        assert by_pid[pid].note == "not_a_chrome_executable", (
            "%s must be rejected by the argv0 half of Conjunct A, not by "
            "the profile half or the ownership test; got %r"
            % (label, by_pid[pid].note)
        )


def test_fingerprint_is_resolved_at_runtime_not_hardcoded():
    """A different HOME must stop rows 1/2/9 from matching at all."""
    module = load_hook()
    rows = module.parse_ps_table(table_text(ALL_ROWS))
    ppid_map = module._ppid_map(rows)
    command_map = module._command_map(rows)
    own_chain = module.resolve_own_chain(OWN_HOOK_PID, ppid_map, command_map)
    selected = dict(module.select_targets(
        rows, "/home/someone-else/.cache/chrome-devtools-mcp", own_chain))
    assert selected == {ORPHANED_AB_PID: module.ARM_ORPHANED_CLI}, (
        "the MCP fingerprint is not HOME-derived - a selector that matched "
        "regardless of HOME would reap another user's browsers. Selected: %r"
        % (selected,)
    )
    assert module.mcp_profile_root(FIXTURE_HOME) == FIXTURE_MCP_ROOT, (
        "mcp_profile_root built %r, expected %r"
        % (module.mcp_profile_root(FIXTURE_HOME), FIXTURE_MCP_ROOT)
    )


# ---------------------------------------------------------------------------
# 2. The mutations - each rewritten out of the hook's own source and made to
#    produce the wrong answer against the SAME fixture.
# ---------------------------------------------------------------------------

MUTATION_ANCHOR_RE = "# MUTATION-ANCHOR: %s\n.*?# END-MUTATION-ANCHOR: %s\n"


def _mutated_source(anchor, replacement_lines):
    with open(HOOK_PATH, "r", encoding="utf-8") as handle:
        source = handle.read()
    pattern = re.compile(
        MUTATION_ANCHOR_RE % (re.escape(anchor), re.escape(anchor)), re.S)
    matches = pattern.findall(source)
    assert len(matches) == 1, (
        "mutation anchor %r matched %d time(s) in %s - the anchor was moved "
        "or duplicated, so the mutation below would have been a no-op and "
        "this gate would have passed vacuously"
        % (anchor, len(matches), HOOK_PATH)
    )
    mutated = pattern.sub(
        "    # MUTATION: %s removed by the regression test\n%s\n"
        % (anchor, "\n".join(replacement_lines)),
        source,
    )
    assert mutated != source, (
        "mutating anchor %r produced a byte-identical source" % anchor
    )
    return mutated


def _load_mutated(anchor, replacement_lines):
    tmpdir = tempfile.mkdtemp(prefix="ae-reap-mutation-")
    try:
        path = os.path.join(tmpdir, "mutated_%s.py" % anchor)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(_mutated_source(anchor, replacement_lines))
        return load_hook(path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_mutation_a_removing_conjunct_a_selects_the_safety_targets():
    """The mutation whose ABSENCE let a passing fixture coexist with an
    unsafe predicate: drop the MCP profile fingerprint and the marp and
    Playwright browsers become selected."""
    module = _load_mutated("conjunct_a", ["    return True"])
    selected, _, _ = fixture_selection(module)
    assert MARP_PID in selected, (
        "mutation (a) did not select the marp browser - the fixture no "
        "longer discriminates on Conjunct A"
    )
    assert PLAYWRIGHT_PID in selected, (
        "mutation (a) did not select the Playwright browser"
    )
    assert len(selected) != 3, (
        "mutation (a) left the selected count at 3 - the fixture cannot "
        "detect the fingerprint being removed"
    )


def test_mutation_b_removing_conjunct_b_selects_browser_helpers():
    module = _load_mutated("conjunct_b", ["    return True"])
    selected, _, _ = fixture_selection(module)
    assert REPARENTED_AB_HELPER_PID in selected, (
        "mutation (b) did not select the reparented --type= helper"
    )
    assert len(selected) != 3, "mutation (b) left the selected count at 3"


def test_mutation_c_removing_the_ancestor_test_selects_another_session():
    module = _load_mutated("ancestor_test", ["    return 'i'"])
    selected, _, _ = fixture_selection(module)
    assert OTHER_SESSION_MCP_PID in selected, (
        "mutation (c) did not select another live session's browser - "
        "the fixture cannot detect the ownership test being removed"
    )
    assert len(selected) == 4, (
        "mutation (c) selected %d rows, expected 4" % len(selected)
    )


def test_mutation_d_dropping_arm_ii_loses_this_sessions_own_browser():
    module = _load_mutated("arm_ii", ["    return False"])
    selected, _, _ = fixture_selection(module)
    assert OWN_SESSION_MCP_PID not in selected, (
        "mutation (d) still selected this session's own browser"
    )
    assert len(selected) == 2, (
        "mutation (d) selected %d rows, expected 2" % len(selected)
    )


def test_mutation_e_widening_own_chain_past_the_harness_crosses_sessions():
    """Not a source mutation: the same selector called with an own-chain
    that continues past the harness into the shared terminal. This is what a
    naive 'descendant of my ancestor chain' arm (ii) computes, and it must
    select the other session's browser - proving the harness boundary in
    resolve_own_chain is load-bearing rather than decorative."""
    module = load_hook()
    rows = module.parse_ps_table(table_text(ALL_ROWS))
    ppid_map = module._ppid_map(rows)
    command_map = module._command_map(rows)
    own_chain = module.resolve_own_chain(OWN_HOOK_PID, ppid_map, command_map)
    assert SHARED_TERMINAL_PID not in own_chain, (
        "resolve_own_chain already includes the shared terminal - the "
        "boundary assertion below would prove nothing"
    )
    widened = own_chain + [SHARED_TERMINAL_PID]
    selected = dict(module.select_targets(rows, FIXTURE_MCP_ROOT, widened))
    assert OTHER_SESSION_MCP_PID in selected, (
        "an own-chain widened past the harness did NOT select the other "
        "session's browser; the fixture no longer models the measured "
        "cross-session terminal shape"
    )


def test_mutation_f_removing_the_chrome_identity_check_selects_non_browsers():
    """The argv0 half of Conjunct A. Two families are pinned here. The first
    is the measured self-match hazard: a process whose argv carries the
    profile fingerprint because the fingerprint was its argument. The second
    is the family the fixture originally had no row for - the MCP's OWN
    processes, whose argv0 contains the string `chrome` and whose argv (once
    the installer pins a profile root) carries the fingerprint, so a
    substring test on the executable region made the server a kill target."""
    module = _load_mutated("chrome_binary", ["    return True"])
    selected, _, _ = fixture_selection(module)
    assert INCIDENTAL_GREP_PID in selected, (
        "mutation (f) did not select the fingerprint-as-argument row - the "
        "measured self-match hazard is no longer pinned by this fixture"
    )
    for pid, label in (
        (MCP_WRAPPER_PID, "the npm exec wrapper"),
        (MCP_SERVER_PID, "the MCP stdio server"),
        (MCP_BARE_PID, "the bare MCP argv0"),
        (CHROME_NAMED_LAUNCHER_PID, "a differently-named chrome launcher"),
    ):
        assert pid in selected, (
            "mutation (f) did not select %s (pid %d) - nothing in the "
            "fixture pins the argv0 conjunct against this shape, which is "
            "exactly how the shipped substring test stayed green"
            % (label, pid)
        )
    assert len(selected) != 3, "mutation (f) left the selected count at 3"


# ---------------------------------------------------------------------------
# 3. The required properties, each with a named mutation that reddens it.
# ---------------------------------------------------------------------------

def test_required_property_mcp_process_shapes_are_never_selected():
    """A process whose executable is `chrome-devtools-mcp` - the node server,
    the `npm exec` wrapper, the telemetry watchdog, or the package's own
    bare argv0 - is not selected, whether or not the profile path appears in
    its argv. The wrapper, server and bare rows carry the fingerprint; the
    watchdog does not, which is why it pins the argv0 half by NOTE rather
    than by the mutation above."""
    module = load_hook()
    selected, verdicts, _ = fixture_selection(module)
    by_pid = dict((v.row.pid, v) for v in verdicts)
    for pid in (MCP_WRAPPER_PID, MCP_SERVER_PID, MCP_WATCHDOG_PID,
                MCP_BARE_PID):
        assert pid not in selected, (
            "an MCP process shape (pid %d) was selected" % pid
        )
        assert module._is_chrome_binary(by_pid[pid].row.command) is False, (
            "pid %d's own executable was classified as a Chrome binary: %r"
            % (pid, by_pid[pid].row.command)
        )
    # The three that carry the fingerprint prove the profile half alone
    # cannot make a non-browser selectable.
    for pid in (MCP_WRAPPER_PID, MCP_SERVER_PID, MCP_BARE_PID):
        assert module._matches_mcp_profile(by_pid[pid].row.command,
                                           FIXTURE_MCP_ROOT) is True, (
            "pid %d was expected to carry the fingerprint, so that its "
            "non-selection demonstrates the profile half is not sufficient "
            "on its own" % pid
        )


def test_required_property_real_chrome_with_the_fingerprint_is_still_selected():
    """The positive control. Mutation (g) - the argv0 half made
    unconditionally false - deselects it, so this assertion is not vacuous."""
    module = load_hook()
    rows = module.parse_ps_table(
        table_text([(1, 0, "launchd"),
                    (2001, 1, CHROME_GUI + " " + MCP_BROWSER_ARGS)]))
    selected = dict(module.select_targets(rows, FIXTURE_MCP_ROOT, [2001]))
    assert selected == {2001: module.ARM_ORPHANED_MCP}, (
        "a real Chrome main carrying the profile fingerprint must still be "
        "selected; got %r" % (selected,)
    )
    mutated = _load_mutated("chrome_binary", ["    return False"])
    rows = mutated.parse_ps_table(
        table_text([(1, 0, "launchd"),
                    (2001, 1, CHROME_GUI + " " + MCP_BROWSER_ARGS)]))
    assert mutated.select_targets(rows, FIXTURE_MCP_ROOT, [2001]) == [], (
        "mutation (g) left the real Chrome selected - this test cannot "
        "detect the argv0 half being removed"
    )


def test_required_property_fingerprint_alone_never_selects_a_non_browser():
    """The profile path is a string any process can name, so a row that is
    not a browser must not become a target by carrying it. Mutation (f)
    selects every row below; the shipped selector selects none. Row 2001's
    executable region carries a space and a single-dash argument, 2004 is a
    measured live crashpad handler of an unrelated Electron app, and 2005 is
    a launcher whose name merely CONTAINS `chrome` - the shape an exclusion
    list would have to be extended for."""
    module = load_hook()
    rows = module.parse_ps_table(table_text([
        (1, 0, "launchd"),
        (2001, 1, "/System/Library/PrivateFrameworks/SkyLight.framework"
         "/Resources/WindowServer -daemon"
         " --user-data-dir=%s/chrome-profile" % FIXTURE_MCP_ROOT),
        (2002, 1, "npm exec chrome-devtools-mcp@latest --headless"
         " --user-data-dir=%s/chrome-profile" % FIXTURE_MCP_ROOT),
        (2003, 1, "chrome-devtools-mcp --headless"
         " --user-data-dir=%s/chrome-profile" % FIXTURE_MCP_ROOT),
        (2004, 1, "/Applications/UA Connect.app/Contents/Frameworks"
         "/Electron Framework.framework/Helpers/chrome_crashpad_handler"
         " --no-rate-limit --user-data-dir=%s/chrome-profile"
         % FIXTURE_MCP_ROOT),
        (2005, 1, "/usr/local/bin/chrome-launcher"
         " --user-data-dir=%s/chrome-profile" % FIXTURE_MCP_ROOT),
    ]))
    shipped = module.select_targets(rows, FIXTURE_MCP_ROOT, [2001])
    assert shipped == [], (
        "a non-browser row was selected on the strength of carrying the "
        "profile path: %r" % (shipped,)
    )
    mutated = _load_mutated("chrome_binary", ["    return True"])
    reddened = dict(mutated.select_targets(rows, FIXTURE_MCP_ROOT, [2001]))
    for pid in (2001, 2002, 2003, 2004, 2005):
        assert pid in reddened, (
            "mutation (f) did not select pid %d - this case is not actually "
            "pinned by the argv0 half" % pid
        )


# ---------------------------------------------------------------------------
# 4. The failure paths (plan gate V5b) - every one must exit 0.
# ---------------------------------------------------------------------------

def _run_hook(stdin_text, env_overrides=None, hook_path=HOOK_PATH, cwd=None):
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, hook_path],
        input=stdin_text,
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd or tempfile.gettempdir(),
        timeout=60,
    )


def _valid_payload(cwd):
    return json.dumps({
        "session_id": "test-session",
        "transcript_path": os.path.join(cwd, "transcript.jsonl"),
        "cwd": cwd,
        "hook_event_name": "SessionEnd",
        "reason": "other",
    })


def _make_shim_ps(directory, script_body):
    """Write a fake `ps` that answers the hook's one fixed query."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "ps")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("#!/bin/sh\n" + script_body + "\n")
    os.chmod(path, 0o755)
    return path


def _shim_env(directory, home):
    return {"PATH": directory + os.pathsep + os.environ.get("PATH", ""),
            "HOME": home}


def _read_fire_rows(path):
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_missing_ps_exits_zero():
    tmpdir = tempfile.mkdtemp(prefix="ae-reap-nops-")
    try:
        empty_bin = os.path.join(tmpdir, "emptybin")
        os.makedirs(empty_bin, exist_ok=True)
        result = _run_hook(_valid_payload(tmpdir),
                           {"PATH": empty_bin, "HOME": FIXTURE_HOME},
                           cwd=tmpdir)
        assert result.returncode == 0, (
            "a missing `ps` must exit 0 (non-zero at SessionEnd is the "
            "blocking code); got rc=%d, stderr=%r"
            % (result.returncode, result.stderr)
        )
        assert "Traceback" not in result.stderr, result.stderr
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_malformed_payload_exits_zero():
    tmpdir = tempfile.mkdtemp(prefix="ae-reap-badpayload-")
    try:
        for payload in ("", "not json at all", "[1, 2, 3]", "null", "{}"):
            result = _run_hook(payload, {"HOME": FIXTURE_HOME}, cwd=tmpdir)
            assert result.returncode == 0, (
                "payload %r exited %d, expected 0" % (payload,
                                                      result.returncode)
            )
            assert "Traceback" not in result.stderr, result.stderr
        log_path = os.path.join(tmpdir, ".agentic",
                                ".enforcement-fires.jsonl")
        assert not os.path.exists(log_path), (
            "an invocation that never reached a verdict (no SessionEnd "
            "payload) wrote a fire row - the empty-stdin smoke-test run "
            "would pollute the real fire log"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_empty_and_failing_process_tables_exit_zero_and_are_logged():
    tmpdir = tempfile.mkdtemp(prefix="ae-reap-emptytable-")
    try:
        payload = _valid_payload(tmpdir)
        cases = (
            ("empty", "exit 0"),
            ("failing", "echo 'ps: type: keyword not found' >&2; exit 1"),
        )
        for label, body in cases:
            shim_dir = os.path.join(tmpdir, "bin-%s" % label)
            _make_shim_ps(shim_dir, body)
            result = _run_hook(payload, _shim_env(shim_dir, FIXTURE_HOME),
                               cwd=tmpdir)
            assert result.returncode == 0, (
                "an %s process table exited %d, expected 0"
                % (label, result.returncode)
            )
            assert "Traceback" not in result.stderr, result.stderr
        log_path = os.path.join(tmpdir, ".agentic",
                                ".enforcement-fires.jsonl")
        assert os.path.exists(log_path), (
            "no fire record at %s - a zero-reap run must still be logged, "
            "or 'the hook never fired' becomes indistinguishable from 'the "
            "hook fired and found nothing'" % log_path
        )
        rows = _read_fire_rows(log_path)
        assert len(rows) == 2, (
            "expected one fire-log row per run, got %d" % len(rows)
        )
        for row in rows:
            assert row["hook"] == "session-end-reap-browsers", row
            assert row["decision"] == "allow", row
            assert row["detail"]["table_rows"] == 0, row
            assert row["detail"]["reaped"] == 0, row
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 5. The fire record and the writer (plan gate V5c).
# ---------------------------------------------------------------------------

def _spawn_sleeper():
    return subprocess.Popen([sys.executable, "-c",
                             "import time; time.sleep(120)"])


def _wait_gone(proc, seconds=5.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.05)
    return proc.poll() is not None


def _orphan_browser_shim(directory, pid, mcp_root):
    """A `ps` shim reporting exactly one row: a browser main with the MCP
    fingerprint, reparented to pid 1 (i.e. an orphan)."""
    _make_shim_ps(directory, "printf '%%s\\n' '%d 1 %s "
                             "--user-data-dir=%s/chrome-profile"
                             " --remote-debugging-pipe about:blank'"
                 % (pid, CHROME_GUI, mcp_root))


def test_one_real_reap_writes_a_fire_row_via_the_shared_log_module():
    tmpdir = tempfile.mkdtemp(prefix="ae-reap-real-")
    sleeper = None
    try:
        home = os.path.join(tmpdir, "home")
        cwd = os.path.join(tmpdir, "project")
        os.makedirs(home)
        os.makedirs(cwd)
        mcp_root = os.path.join(home, ".cache", "chrome-devtools-mcp")
        sleeper = _spawn_sleeper()
        shim_dir = os.path.join(tmpdir, "bin")
        _orphan_browser_shim(shim_dir, sleeper.pid, mcp_root)
        result = _run_hook(_valid_payload(cwd), _shim_env(shim_dir, home),
                           cwd=cwd)
        assert result.returncode == 0, (
            "rc=%d stderr=%r" % (result.returncode, result.stderr))
        assert _wait_gone(sleeper), (
            "the selected orphan (pid %d) was not killed" % sleeper.pid
        )
        log_path = os.path.join(cwd, ".agentic", ".enforcement-fires.jsonl")
        assert os.path.exists(log_path), (
            "no fire record written to %s" % log_path
        )
        rows = _read_fire_rows(log_path)
        assert len(rows) == 1, "expected exactly one fire row, got %r" % rows
        row = rows[0]
        assert row["hook"] == "session-end-reap-browsers", row
        assert row["decision"] == "reap", row
        assert row["detail"]["reaped"] == 1, row
        assert row["detail"]["arm_counts"] == {"i": 1}, (
            "the fire row must name the selector arm that fired; got %r"
            % (row["detail"],)
        )
        # The canonical schema hooks/lib/enforcement_log.py writes.
        assert set(row.keys()) >= {"ts", "hook", "decision", "reason",
                                   "detail"}, row
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$",
                        row["ts"]), row
    finally:
        if sleeper is not None and sleeper.poll() is None:
            sleeper.kill()
            sleeper.wait()
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_the_shared_log_module_is_the_only_writer_of_the_fire_row():
    """Run the same real reap against a COPY of the hook with hooks/lib/
    absent. Nothing may be written: the row asserted above came through
    hooks/lib/enforcement_log.py, not from a hand-written JSONL append."""
    tmpdir = tempfile.mkdtemp(prefix="ae-reap-nowriter-")
    sleeper = None
    try:
        assert os.path.exists(LIB_PATH), (
            "hooks/lib/enforcement_log.py is missing; this assertion cannot "
            "mean anything"
        )
        home = os.path.join(tmpdir, "home")
        cwd = os.path.join(tmpdir, "project")
        copy_dir = os.path.join(tmpdir, "hookedcopy")
        os.makedirs(home)
        os.makedirs(cwd)
        os.makedirs(copy_dir)
        copied_hook = os.path.join(copy_dir, "session-end-reap-browsers.py")
        with open(HOOK_PATH, "r", encoding="utf-8") as src:
            body = src.read()
        with open(copied_hook, "w", encoding="utf-8") as dst:
            dst.write(body)
        assert not os.path.exists(os.path.join(copy_dir, "lib")), (
            "the copy unexpectedly carries a lib/ directory - the writer "
            "discriminator below would be vacuous"
        )

        mcp_root = os.path.join(home, ".cache", "chrome-devtools-mcp")
        sleeper = _spawn_sleeper()
        shim_dir = os.path.join(tmpdir, "bin")
        _orphan_browser_shim(shim_dir, sleeper.pid, mcp_root)
        result = _run_hook(_valid_payload(cwd), _shim_env(shim_dir, home),
                           hook_path=copied_hook, cwd=cwd)
        assert result.returncode == 0, (
            "a hook whose log lib is absent must still exit 0; rc=%d "
            "stderr=%r" % (result.returncode, result.stderr)
        )
        assert _wait_gone(sleeper), (
            "the reap itself must still happen without the log lib"
        )
        log_path = os.path.join(cwd, ".agentic", ".enforcement-fires.jsonl")
        assert not os.path.exists(log_path), (
            "a fire row was written at %s by a hook with no "
            "hooks/lib/enforcement_log.py - something other than the shared "
            "module writes this log" % log_path
        )
    finally:
        if sleeper is not None and sleeper.poll() is None:
            sleeper.kill()
            sleeper.wait()
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    tests = [
        (name, value) for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = []
    for name, test in tests:
        try:
            test()
        except AssertionError as exc:
            failures.append((name, str(exc)))
            print("FAIL: %s\n      %s" % (name, exc))
        except Exception as exc:  # pragma: no cover - surfaced, not hidden
            failures.append((name, "%s: %s" % (type(exc).__name__, exc)))
            print("ERROR: %s\n       %s: %s" % (name, type(exc).__name__, exc))
        else:
            print("PASS: %s" % name)
    print("\n%d passed, %d failed" % (len(tests) - len(failures),
                                      len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
