#!/usr/bin/env python3
"""
Regression spec for bin/ds-learnings-retrieval-rate.

The DS-223 plan's normative classification case table is transcribed into
CASE_TABLE below and driven against the shipped predicate by a single
parametrized test. The table is the oracle: adding a row here is how
predicate coverage is added, and no per-case test is hand-written alongside
it. Every other test in this module covers a contract the table cannot
express - role resolution, the no-data envelope, config-dir resolution, the
total row identity, the derived `wiring` column, and the pooled arithmetic.

Fixtures are synthetic transcript stores built in a tmpdir with
CLAUDE_CONFIG_DIR pointed at them. The operator's real transcripts are
never read by a test.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent.parent
CLI_PATH = REPO_DIR / "bin" / "ds-learnings-retrieval-rate"
ALIAS_PATH = REPO_DIR / "bin" / "agentic-learnings-retrieval-rate"

_loader = SourceFileLoader("ds_learnings_retrieval_rate", str(CLI_PATH))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
lrr = importlib.util.module_from_spec(_spec)
sys.modules[_loader.name] = lrr
_loader.exec_module(lrr)


FIRED = True
NOT_FIRED = False

# ---------------------------------------------------------------------------
# The DS-223 normative case table. `reason` is the one clause that decides
# the row and is asserted on nothing - it is here so a failing row explains
# itself. C1-C18 are the round-3 plan's rows; C19-C23 close the five Majors
# the plan reached its review cap with (pattern-position discrimination,
# the WRITE_TOOLS exclusion, the redirect skip, and the shell-string
# carrier rule in both directions). C27-C41 close the DS-223 iteration-2
# findings: the `<` input-redirect asymmetry (J1), the `if` idiom (Minor 1),
# a disclosed command-substitution false negative (Minor 2), and a per-member
# row for every previously unpinned member of PATTERN_SUPPRESS_FLAGS,
# FILE_VALUE_FLAGS, WRITE_TOOLS and FIELD_ALLOWLIST (J2). The remaining
# constants are closed sets pinned behaviourally by TestCommandSets below.
# ---------------------------------------------------------------------------
CASE_TABLE = [
    (
        "C1", "Bash",
        {"command": "grep -i -E 'kw' .agentic/learnings.md"},
        FIRED,
        "read command, file is a bare argument",
    ),
    (
        "C2", "Read",
        {"file_path": ".agentic/learnings.md"},
        FIRED,
        "allowlisted read field holds the path",
    ),
    (
        "C3", "Bash",
        {"command": 'grep -n "MEMORY.md\\|learnings.md" docs/index.html'},
        NOT_FIRED,
        "path appears only inside the search pattern; the file read is docs/index.html",
    ),
    (
        "C4", "Bash",
        {
            "command": "cat > plan.md <<'EOF'\n"
                       "notes\n"
                       "grep -i -E 'x' .agentic/learnings.md\n"
                       "EOF"
        },
        NOT_FIRED,
        "the match is inside a heredoc body - data being written, not a command being run",
    ),
    (
        "C5", "Grep",
        {"pattern": ".agentic/learnings.md", "path": "content/"},
        NOT_FIRED,
        "pattern is not an allowlisted field; this is a search FOR references",
    ),
    (
        "C6", "Glob",
        {"pattern": "**/learnings.md"},
        NOT_FIRED,
        "Glob is not in FIELD_ALLOWLIST; listing names is not reading contents",
    ),
    (
        "C7", "Edit",
        {"file_path": ".agentic/learnings.md", "old_string": "a", "new_string": "b"},
        NOT_FIRED,
        "write tool",
    ),
    (
        "C8", "Bash",
        {"command": "git check-ignore -v .agentic/learnings.md"},
        NOT_FIRED,
        "git is not a read command; this is a metadata probe",
    ),
    (
        "C9", "Bash",
        {
            "command": "git commit -s -m \"$(cat <<'EOF'\n"
                       "fix: note .agentic/learnings.md in the body\n"
                       "EOF\n"
                       ")\""
        },
        NOT_FIRED,
        "commit-message heredoc body; the only read command present has no path operand "
        "once the body is removed",
    ),
    (
        "C10", "Grep",
        {"pattern": "kw", "path": ".", "glob": "learnings.md"},
        NOT_FIRED,
        "path is '.', and glob is not allowlisted - a knowing false negative",
    ),
    (
        "C11", "Bash",
        {"command": "grep -rn 'kw' content/ .agentic/learnings.md"},
        FIRED,
        "multi-target read command; the file is one of its read operands",
    ),
    (
        "C12", "Bash",
        {"command": "git ls-files .agentic/learnings.md"},
        NOT_FIRED,
        "metadata probe, same as C8",
    ),
    (
        "C13", "Bash",
        {"command": "cat ~/DinoStack/.agentic/learnings.md | head -50"},
        FIRED,
        "absolute/expanded path form; pipeline segments are classified independently",
    ),
    (
        "C14", "Bash",
        {"command": "echo hi > .agentic/learnings.md"},
        NOT_FIRED,
        "echo is not a read command, and the path follows a redirect operator",
    ),
    (
        "C15", "Bash",
        {"command": "cd /x && grep -i -E 'a|b' .agentic/learnings.md"},
        FIRED,
        "the | inside a quoted regex must not split the command",
    ),
    (
        "C16", "Bash",
        {"command": "grep -c '' .agentic/learnings.md 2>/dev/null"},
        FIRED,
        "a trailing redirect does not suppress an earlier read operand",
    ),
    (
        "C17", "Write",
        {"file_path": ".agentic/learnings.md", "content": "x"},
        NOT_FIRED,
        "write tool",
    ),
    (
        "C18", "Bash",
        {"command": "tee -a .agentic/learnings.md <<'EOF'\nentry\nEOF"},
        NOT_FIRED,
        "tee is not in READ_CMDS; this is the append-write shape",
    ),
    (
        "C19", "Bash",
        {"command": "grep -rn '.agentic/learnings.md' docs/"},
        NOT_FIRED,
        "the token is a perfect PATH_TOKEN but occupies grep's pattern slot, not an "
        "operand slot; the file read is docs/. This is the row that pins "
        "operand-vs-pattern discrimination inside a shell string",
    ),
    (
        "C20", "Edit",
        {
            "file_path": "content/agents/engineer.md",
            "old_string": "x",
            "new_string": "grep -i -E 'kw' .agentic/learnings.md",
        },
        NOT_FIRED,
        "WRITE_TOOLS is applied BEFORE the unlisted-tool carrier scan, so a read "
        "command in text being WRITTEN never fires. This is the row that makes "
        "WRITE_TOOLS reachable: without it, Edit falls through to the carrier scan "
        "and the new_string classifies as a read",
    ),
    (
        "C21", "Bash",
        {"command": "grep -c x docs/index.html > .agentic/learnings.md"},
        NOT_FIRED,
        "a read command whose only mention of the file is its redirect TARGET; both "
        "the redirect token and the token after it are skipped",
    ),
    (
        "C22", "ctx_batch_execute",
        {
            "commands": [
                {"label": "learnings", "command": "grep -i -E 'kw' .agentic/learnings.md"}
            ]
        },
        FIRED,
        "a tool outside FIELD_ALLOWLIST is scanned as a carrier of shell command "
        "strings, and the carried string is classified by the same shell rules",
    ),
    (
        "C23", "SomeMcpReadTool",
        {"file_path": ".agentic/learnings.md"},
        NOT_FIRED,
        "the carrier rule is the ONLY branch applied to an unlisted tool; no bare-path "
        "field of an unlisted tool ever fires",
    ),
    (
        "C24", "Grep",
        {"pattern": "kw", "path": ".agentic/learnings.md"},
        FIRED,
        "the retrieval shape done through the harness's own Grep tool with the file "
        "as its search TARGET. Grep.path is in FIELD_ALLOWLIST and C5/C10 are both "
        "NOT_FIRED rows, so without this row removing Grep.path from the allowlist "
        "flips nothing and the field is unpinned",
    ),
    (
        "C25", "Bash",
        {"command": "cd /repo; grep -n 'kw' .agentic/learnings.md | head -20"},
        FIRED,
        "the `;` is glued to the preceding word, so a whitespace-only lexer yields "
        "one segment whose command word is `cd` and never classifies the grep. Two "
        "real corpus reads were missed this way before punctuation_chars=True",
    ),
    (
        "C26", "Bash",
        {"command": "for k in A B; do grep -n -A4 \"$k\" .agentic/learnings.md; done"},
        FIRED,
        "a single-command loop body puts the shell keyword `do` in the command-word "
        "slot of the same segment as the grep; without COMMAND_WORD_SKIP the command "
        "word reads as `do` and the file is never seen. This is the row that makes "
        "COMMAND_WORD_SKIP reachable - a multi-command body would be split by the "
        "`;` instead and would pin nothing",
    ),
    (
        "C27", "Bash",
        {"command": "cat < .agentic/learnings.md"},
        FIRED,
        "an INPUT redirect's target is READ. Before DS-223 J1 the `<` target was "
        "skipped exactly as a `>` target is, so the single most common shell way "
        "of reading a file classified NOT_FIRED",
    ),
    (
        "C28", "Bash",
        {"command": "grep -i kw < .agentic/learnings.md"},
        FIRED,
        "input redirect on a pattern-taking command: the pattern slot is filled by "
        "`kw`, and the redirect target is still an operand",
    ),
    (
        "C29", "Bash",
        {"command": "grep -c x docs/index.html &> .agentic/learnings.md"},
        NOT_FIRED,
        "`&>` is an output redirect, so its target is written. This is the row that "
        "makes the `&` member of REDIRECT_PUNCT reachable - `&` alone is an "
        "OPERATOR_TOKEN and splits before it can reach the operand scan",
    ),
    (
        "C30", "Bash",
        {"command": "cat <<< .agentic/learnings.md"},
        NOT_FIRED,
        "a herestring's operand is a literal word fed on stdin, not a filename to "
        "open. This is what keeps INPUT_REDIRECT_RE narrow to exactly one `<`",
    ),
    (
        "C31", "Bash",
        {"command": "if grep -q kw .agentic/learnings.md; then echo y; fi"},
        FIRED,
        "`if` occupies the command-word slot of the same segment as the grep, so "
        "without `if` in COMMAND_WORD_SKIP the command word reads as `if` and one "
        "of the most common shell idioms there is classifies NOT_FIRED",
    ),
    (
        "C32", "Bash",
        {"command": "grep -e kw -e .agentic/learnings.md docs/"},
        NOT_FIRED,
        "two out-of-band patterns, the second of which is the literal path. `-e` "
        "must consume its value, or that value falls through as an operand and the "
        "row becomes a false positive. This is the row that pins `-e` in "
        "PATTERN_SUPPRESS_FLAGS",
    ),
    (
        "C33", "Bash",
        {"command": "grep --regexp=kw .agentic/learnings.md"},
        FIRED,
        "the `=` spelling of an out-of-band pattern: the path is an operand, not the "
        "pattern slot. Pins `--regexp`, and pins the `=`-form branch of the "
        "suppress rule",
    ),
    (
        "C34", "Bash",
        {"command": "sed --expression='s|a|b|' .agentic/learnings.md"},
        FIRED,
        "same shape for sed's script flag. Pins `--expression`; without it the "
        "script is skipped as a plain option and the path is eaten by the pattern "
        "slot",
    ),
    (
        "C35", "Bash",
        {"command": "grep -f .agentic/learnings.md docs/"},
        FIRED,
        "the file is grep's PATTERN FILE - genuinely opened and read, even though "
        "the search target is docs/. Pins `-f` in FILE_VALUE_FLAGS (drop it and the "
        "value is skipped unread) and in PATTERN_SUPPRESS_FLAGS (drop it there and "
        "the value is eaten by the pattern slot)",
    ),
    (
        "C36", "Bash",
        {"command": "grep --file=.agentic/learnings.md docs/"},
        FIRED,
        "the `=` spelling of the same carve-out; pins `--file` in both sets",
    ),
    (
        "C37", "Write",
        {"file_path": "probe.sh", "content": "grep -i kw .agentic/learnings.md\n"},
        NOT_FIRED,
        "authoring a script that WOULD read the file is not reading it. This is the "
        "row that makes the `Write` member of WRITE_TOOLS reachable: C17's bare "
        "file_path cannot fire through the carrier scan, so removing `Write` from "
        "WRITE_TOOLS flips nothing there",
    ),
    (
        "C38", "MultiEdit",
        {
            "file_path": "content/agents/engineer.md",
            "edits": [{"old_string": "a", "new_string": "cat .agentic/learnings.md"}],
        },
        NOT_FIRED,
        "same, for MultiEdit's nested edit payload; pins the `MultiEdit` member",
    ),
    (
        "C39", "NotebookEdit",
        {"notebook_path": "nb.ipynb", "new_source": "cat .agentic/learnings.md"},
        NOT_FIRED,
        "same, for a notebook cell body; pins the `NotebookEdit` member",
    ),
    (
        "C40", "Bash",
        {"command": "ls -la", "description": "cat .agentic/learnings.md for priors"},
        NOT_FIRED,
        "a Bash call whose DESCRIPTION paraphrases a read that the command does not "
        "perform. This is the row that makes Bash's FIELD_ALLOWLIST entry "
        "load-bearing: without it Bash falls to the carrier scan, which reads every "
        "string field including this one",
    ),
    (
        "C41", "Bash",
        {"command": "cat $(ls .agentic/learnings.md)"},
        NOT_FIRED,
        "a knowing false negative, disclosed in the footer: the path is inside a "
        "command substitution, so the outer `cat`'s operand list never contains a "
        "literal path token",
    ),
]


class TestClassificationCaseTable(unittest.TestCase):
    def test_classification_matches_case_table(self):
        for case_id, tool, tool_input, required, reason in CASE_TABLE:
            with self.subTest(case=case_id, tool=tool):
                self.assertEqual(
                    lrr.call_is_fired(tool, tool_input),
                    required,
                    f"{case_id} ({tool}) must be "
                    f"{'FIRED' if required else 'NOT_FIRED'}: {reason}",
                )

    def test_case_table_ids_are_unique_and_complete(self):
        ids = [row[0] for row in CASE_TABLE]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [f"C{n}" for n in range(1, len(ids) + 1)])


class TestPathToken(unittest.TestCase):
    """PATH_TOKEN is a precise definition, not an English gesture at 'no shell
    metacharacters' - `~` is a metacharacter and C13 depends on it passing."""

    def test_tilde_prefixed_path_is_a_path_token(self):
        self.assertTrue(lrr.is_path_token("~/DinoStack/.agentic/learnings.md"))

    def test_boundary_is_a_slash(self):
        self.assertTrue(lrr.is_path_token(".agentic/learnings.md"))
        self.assertFalse(lrr.is_path_token("xx.agentic/learnings.md"))

    def test_glob_and_option_tokens_are_not_path_tokens(self):
        self.assertFalse(lrr.is_path_token("*/.agentic/learnings.md"))
        self.assertFalse(lrr.is_path_token("--file=.agentic/learnings.md"))


# Test-OWNED expected membership for the four closed sets. These literals
# are the second operand that makes the loops below falsifiable: iterating
# `lrr.READ_CMDS` directly cannot detect a deletion, because the deleted
# member takes its own subtest away with it and the suite stays green with a
# silently smaller subtest count. (Measured: the first cut of these tests
# survived 24 of 29 per-member deletions for exactly that reason.) Keep each
# literal in sync with the CLI deliberately - a diff here is the point.
EXPECTED_READ_CMDS = frozenset({
    "grep", "rg", "egrep", "fgrep", "cat", "head", "tail", "sed",
    "awk", "less", "wc", "sort", "uniq", "nl", "cut",
})
EXPECTED_PATTERN_ARG_CMDS = frozenset({"grep", "rg", "egrep", "fgrep", "sed", "awk"})
EXPECTED_OPERATOR_TOKENS = frozenset({
    ";", ";;", "&&", "||", "|", "&", "(", ")", "{", "}",
})
EXPECTED_COMMAND_WORD_SKIP = frozenset({
    "do", "then", "else", "elif", "if", "while", "until", "!", "time",
    "sudo", "env", "command", "nohup", "exec", "builtin",
})


class TestCommandSets(unittest.TestCase):
    """Pins for the four closed sets whose members are too numerous for one
    case-table row each (DS-223 J2).

    Two layers, because either alone is defeatable. The membership layer
    asserts the CLI's set equals a test-owned literal, bidirectionally, so
    adding OR deleting a member reddens. The behaviour layer then iterates
    the LITERAL and asserts what membership MEANS for each named member, so
    the equality assertion is not a bare golden hash - every member has an
    executed consequence. The paired non-member assertions pin the
    exclusion boundary, which a membership-only loop leaves open.
    """

    TARGET = ".agentic/learnings.md"

    # Deliberately NOT read commands: metadata probes, writers, and
    # interpreters. The footer names the interpreter case as a known false
    # negative, so this is the boundary that keeps it honest.
    NON_READ_CMDS = ("git", "tee", "echo", "python3", "ls", "touch", "cp", "tar")

    NON_TRANSPARENT_WORDS = ("cd", "xargs", "echo", "python3")

    def test_command_sets_match_expected_membership(self):
        self.assertEqual(lrr.READ_CMDS, EXPECTED_READ_CMDS)
        self.assertEqual(lrr.PATTERN_ARG_CMDS, EXPECTED_PATTERN_ARG_CMDS)
        self.assertEqual(lrr.OPERATOR_TOKENS, EXPECTED_OPERATOR_TOKENS)
        self.assertEqual(lrr.COMMAND_WORD_SKIP, EXPECTED_COMMAND_WORD_SKIP)
        # PATTERN_ARG_CMDS is meaningless for a command whose operands are
        # never read, so the containment is part of the contract.
        self.assertTrue(EXPECTED_PATTERN_ARG_CMDS <= EXPECTED_READ_CMDS)

    def test_every_read_cmd_reads_its_operands(self):
        for cmd in sorted(EXPECTED_READ_CMDS):
            with self.subTest(cmd=cmd):
                # With the pattern slot explicitly filled, every read
                # command's trailing operand is read.
                self.assertTrue(
                    lrr.command_string_reads_target(f"{cmd} kw {self.TARGET}"),
                    f"{cmd} is in READ_CMDS, so its file operand must be read",
                )
                # And the bare form fires iff the command does NOT consume
                # its first argument as a pattern. Both operands here are
                # test-owned, so this pins PATTERN_ARG_CMDS member-by-member.
                self.assertEqual(
                    lrr.command_string_reads_target(f"{cmd} {self.TARGET}"),
                    cmd not in EXPECTED_PATTERN_ARG_CMDS,
                    f"bare `{cmd} <path>` must fire iff {cmd} takes no pattern arg",
                )

    def test_non_read_commands_never_fire(self):
        for cmd in self.NON_READ_CMDS:
            with self.subTest(cmd=cmd):
                self.assertNotIn(cmd, lrr.READ_CMDS)
                self.assertFalse(
                    lrr.command_string_reads_target(f"{cmd} kw {self.TARGET}")
                )
                self.assertFalse(
                    lrr.command_string_reads_target(f"{cmd} {self.TARGET}")
                )

    def test_every_operator_token_splits_a_segment(self):
        for op in sorted(EXPECTED_OPERATOR_TOKENS):
            with self.subTest(op=op):
                # `echo` is not a read command, so the target is only seen
                # if the operator actually ended echo's segment.
                self.assertTrue(
                    lrr.command_string_reads_target(
                        f"echo x {op} grep kw {self.TARGET}"
                    ),
                    f"`{op}` must end the preceding command's segment",
                )

    def test_every_skipped_command_word_is_transparent(self):
        for word in sorted(EXPECTED_COMMAND_WORD_SKIP):
            with self.subTest(word=word):
                self.assertTrue(
                    lrr.command_string_reads_target(
                        f"{word} grep kw {self.TARGET}"
                    ),
                    f"`{word}` must not occupy the command-word slot",
                )

    def test_non_transparent_command_words_are_opaque(self):
        for word in self.NON_TRANSPARENT_WORDS:
            with self.subTest(word=word):
                self.assertNotIn(word, lrr.COMMAND_WORD_SKIP)
                self.assertFalse(
                    lrr.command_string_reads_target(
                        f"{word} grep kw {self.TARGET}"
                    ),
                    f"`{word}` is the command; the rest is its argv, not a command",
                )

    def test_span_marker_matches_the_stamper(self):
        """The CLI's SPAN_MARKER is a second site that knows the shared-
        fragment marker syntax (DS-223 Minor 5). Assert it against the
        stamper's own regex rather than against a hand-typed copy, so a
        marker-syntax change in scripts/lib/ reddens here instead of
        silently degrading every role to unwired-control."""
        loader = SourceFileLoader(
            "stamp_agent_fragments",
            str(REPO_DIR / "scripts" / "lib" / "stamp_agent_fragments.py"),
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        stamper = importlib.util.module_from_spec(spec)
        loader.exec_module(stamper)
        span = f"{lrr.SPAN_MARKER}body<!-- /shared -->"
        match = stamper.SHARED_RE.fullmatch(span)
        self.assertIsNotNone(
            match, "the CLI's SPAN_MARKER must open a span the stamper recognizes"
        )
        self.assertEqual(match.group("id"), lrr.FRAGMENT_ID)


def _write_transcript(store: Path, session: str, agent_id: str, role, calls):
    directory = store / "projects" / "hash1" / session / "subagents"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"agent-{agent_id}.jsonl"
    lines = []
    for tool_name, tool_input in calls:
        lines.append(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": tool_name, "input": tool_input}
                        ]
                    },
                }
            )
        )
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    if role is not None:
        (directory / f"agent-{agent_id}.meta.json").write_text(
            json.dumps({"agentType": role, "spawnDepth": 1}), encoding="utf-8"
        )
    return path


def _run_cli(store: Path, executable: Path = CLI_PATH, json_flag: bool = True):
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(store)
    env.pop("AGENTIC_CONFIG_DIR", None)
    argv = [sys.executable, str(executable)]
    if json_flag:
        argv.append("--json")
    result = subprocess.run(argv, capture_output=True, text=True, env=env)
    return result


class TestRender(unittest.TestCase):
    """The default (non---json) path is the one an operator actually reads,
    and it is where both pooled human lines compute their own denominator.
    Before DS-223 J4 every end-to-end test passed --json, so none of this
    was executed at all.
    """

    def test_format_rate_renders_percent_and_na(self):
        self.assertEqual(lrr.format_rate(None), "n/a")
        self.assertEqual(lrr.format_rate(0.0), "0.0%")
        self.assertEqual(lrr.format_rate(1.0), "100.0%")
        self.assertEqual(lrr.format_rate(0.076), "7.6%")

    def test_table_path_renders_rows_total_pooled_and_footer(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            _write_transcript(
                store, "s1", "aaa", "architect",
                [("Bash", {"command": "grep -i -E 'kw' .agentic/learnings.md"})],
            )
            _write_transcript(store, "s1", "bbb", "skeptic", [("Read", {"file_path": "x"})])
            result = _run_cli(store, json_flag=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            out = result.stdout
            self.assertNotIn("Traceback", result.stderr)
            # The table is a table, not JSON.
            self.assertNotIn("{", out)
            for token in ("role", "wiring", "runs", "fired", "not_fired",
                          "unreadable", "rate"):
                self.assertIn(token, out)
            self.assertIn("architect", out)
            self.assertIn("wired", out)
            self.assertIn("skeptic", out)
            self.assertIn("unwired-control", out)
            self.assertIn("100.0%", out)
            self.assertIn("TOTAL", out)
            self.assertIn("skipped_oversize: 0", out)
            self.assertIn("Notes:", out)
            # Wired roles sort ahead of controls, which is what makes the
            # pooled control line readable as a floor for the rows above it.
            self.assertLess(out.index("architect"), out.index("skeptic"))

    def test_pooled_human_lines_exclude_unreadable_from_the_denominator(self):
        """`runs - unreadable` is computed ONLY in the render layer, so this
        invariant is unasserted on the operator's path without this test."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            _write_transcript(
                store, "s1", "aaa", "architect",
                [("Bash", {"command": "grep -i -E 'kw' .agentic/learnings.md"})],
            )
            _write_transcript(store, "s1", "bbb", "architect", [])  # zero records
            out = _run_cli(store, json_flag=False).stdout
            self.assertIn("pooled wired: 1/1 = 100.0%", out)
            self.assertNotIn("pooled wired: 1/2", out)
            self.assertIn("pooled unwired-control: 0/0 = n/a", out)

    def test_no_transcripts_human_branch_says_why_and_prints_no_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_cli(Path(tmp), json_flag=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            out = result.stdout
            self.assertIn("No subagent transcripts found.", out)
            self.assertIn("subagents/agent-*.jsonl", out)
            self.assertIn("error: no_transcripts", out)
            # The early return must skip the table AND the footer entirely -
            # a header of empty columns over no data is worse than nothing.
            self.assertNotIn("not_fired", out)
            self.assertNotIn("Notes:", out)
            self.assertNotIn("pooled wired", out)

    def test_missing_agents_dir_renders_a_warning(self):
        payload = {
            "harness": "claude-code",
            "config_dir": "/x",
            "transcripts_scanned": 1,
            "by_role": {
                "architect": {
                    "wiring": "n/a", "runs": 1, "fired": 0,
                    "not_fired": 1, "unreadable": 0, "rate": 0.0,
                }
            },
            "pooled": {
                "wired": {"runs": 0, "fired": 0, "unreadable": 0, "rate": None},
                "unwired_control": {"runs": 0, "fired": 0, "unreadable": 0, "rate": None},
            },
            "skipped_oversize": 0,
            "error": None,
        }
        self.assertIn("WARNING", lrr.render(payload, agents_dir_present=False))
        self.assertNotIn("WARNING", lrr.render(payload, agents_dir_present=True))

    def test_footer_discloses_both_retroactivity_directions_and_substitution(self):
        """DS-223 Minors 2 and 3: an undisclosed false-negative class and a
        one-directional caveat are both defects in a tool whose entire
        output is a number someone will act on."""
        footer = "\n".join(lrr.FOOTER)
        self.assertIn("command substitution", footer)
        self.assertIn("INFLATES", footer)
        self.assertIn("REMOVED", footer)


class TestEndToEnd(unittest.TestCase):
    def test_role_comes_from_meta_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            _write_transcript(store, "s1", "aaa", "debugger", [("Read", {"file_path": "x"})])
            result = _run_cli(store)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertIn("debugger", payload["by_role"])
            self.assertNotIn("unknown", payload["by_role"])

    def test_missing_sidecar_yields_unknown_role_with_na_wiring(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            _write_transcript(store, "s1", "aaa", None, [("Read", {"file_path": "x"})])
            payload = json.loads(_run_cli(store).stdout)
            self.assertIn("unknown", payload["by_role"])
            self.assertEqual(payload["by_role"]["unknown"]["wiring"], "n/a")

    def test_no_transcripts_exits_zero_with_error_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_cli(Path(tmp))
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["error"], "no_transcripts")
            self.assertEqual(payload["transcripts_scanned"], 0)
            self.assertNotIn("Traceback", result.stderr)

    def test_config_dir_is_resolved_not_hardcoded(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            _write_transcript(store, "s1", "aaa", "architect", [("Read", {"file_path": "x"})])
            payload = json.loads(_run_cli(store).stdout)
            self.assertEqual(payload["config_dir"], str(store))
            self.assertEqual(payload["transcripts_scanned"], 1)

    def test_alias_behaves_identically(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            _write_transcript(
                store, "s1", "aaa", "architect",
                [("Bash", {"command": "grep -i -E 'kw' .agentic/learnings.md"})],
            )
            self.assertEqual(_run_cli(store).stdout, _run_cli(store, ALIAS_PATH).stdout)

    def test_row_identity_is_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            _write_transcript(
                store, "s1", "aaa", "architect",
                [("Bash", {"command": "grep -i -E 'kw' .agentic/learnings.md"})],
            )
            _write_transcript(store, "s1", "bbb", "architect", [])
            oversize = _write_transcript(
                store, "s1", "ccc", "architect", [("Read", {"file_path": "x"})]
            )
            with oversize.open("r+b") as handle:
                handle.truncate(lrr.MAX_TRANSCRIPT_BYTES + 1)

            payload = json.loads(_run_cli(store).stdout)
            row = payload["by_role"]["architect"]
            self.assertEqual(payload["transcripts_scanned"], 3)
            self.assertEqual(
                payload["transcripts_scanned"],
                sum(r["runs"] for r in payload["by_role"].values()),
            )
            self.assertEqual(row["runs"], row["fired"] + row["not_fired"] + row["unreadable"])
            self.assertEqual(row["runs"], 3)
            self.assertEqual(row["fired"], 1)
            self.assertEqual(row["not_fired"], 0)
            self.assertEqual(row["unreadable"], 2)
            self.assertEqual(payload["skipped_oversize"], 1)
            # rate excludes unreadable from BOTH numerator and denominator.
            self.assertEqual(row["rate"], 1.0)

    def test_pooled_carries_unreadable_and_excludes_it_from_the_rate(self):
        """The pooled object must expose `unreadable` so its rate denominator
        is defined, and defined the same way a row's is."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            _write_transcript(
                store, "s1", "aaa", "architect",
                [("Bash", {"command": "grep -i -E 'kw' .agentic/learnings.md"})],
            )
            _write_transcript(store, "s1", "bbb", "architect", [])
            _write_transcript(store, "s1", "ccc", "skeptic", [("Read", {"file_path": "x"})])

            payload = json.loads(_run_cli(store).stdout)
            for arm in ("wired", "unwired_control"):
                pooled = payload["pooled"][arm]
                self.assertIn("unreadable", pooled)
            wired = payload["pooled"]["wired"]
            self.assertEqual(wired["runs"], 2)
            self.assertEqual(wired["unreadable"], 1)
            self.assertEqual(wired["fired"], 1)
            self.assertEqual(wired["rate"], 1.0)
            control = payload["pooled"]["unwired_control"]
            self.assertEqual((control["runs"], control["unreadable"], control["fired"]), (1, 0, 0))
            self.assertEqual(control["rate"], 0.0)

    def test_rate_is_null_when_every_run_is_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            _write_transcript(store, "s1", "aaa", "architect", [])
            payload = json.loads(_run_cli(store).stdout)
            self.assertIsNone(payload["by_role"]["architect"]["rate"])
            self.assertIsNone(payload["pooled"]["wired"]["rate"])


class TestWiringIsDerived(unittest.TestCase):
    """`wiring` is load-bearing for both pooled arms, so it must be derived
    from the live agent files rather than hardcoded - stamping the fragment
    into a fourth agent file moves that role without an edit to the CLI."""

    def _agents_dir(self, tmp, wired_roles, unwired_roles):
        agents = Path(tmp) / "agents"
        agents.mkdir()
        for role in wired_roles:
            (agents / f"{role}.md").write_text(
                f"lead-in {lrr.SPAN_MARKER}body<!-- /shared -->\n", encoding="utf-8"
            )
        for role in unwired_roles:
            (agents / f"{role}.md").write_text("no span here\n", encoding="utf-8")
        return agents

    def test_span_presence_decides_wired_vs_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = self._agents_dir(tmp, ["engineer"], ["skeptic"])
            self.assertEqual(lrr.wiring_for("engineer", agents), "wired")
            self.assertEqual(lrr.wiring_for("skeptic", agents), "unwired-control")

    def test_role_without_an_agent_file_is_na(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = self._agents_dir(tmp, [], ["skeptic"])
            self.assertEqual(lrr.wiring_for("general-purpose", agents), "n/a")
            self.assertEqual(lrr.wiring_for("unknown", agents), "n/a")

    def test_intrinsic_learnings_roles_are_na_even_with_a_span(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents = self._agents_dir(tmp, ["learnings-agent"], ["wrap-ticket"])
            for role in sorted(lrr.INTRINSIC_LEARNINGS_ROLES):
                self.assertEqual(lrr.wiring_for(role, agents), "n/a")

    def test_engineer_is_wired_in_the_live_tree(self):
        """The Unit 2 half of this ticket stamps the span into engineer.md;
        this asserts the derivation actually sees it, so the two units cannot
        land half-applied with the measurement silently misreporting."""
        self.assertEqual(lrr.wiring_for("engineer", lrr.AGENTS_DIR), "wired")
        for role in ("architect", "debugger", "investigator"):
            self.assertEqual(lrr.wiring_for(role, lrr.AGENTS_DIR), "wired")
        self.assertEqual(lrr.wiring_for("skeptic", lrr.AGENTS_DIR), "unwired-control")

    def test_missing_agents_dir_degrades_to_na(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(lrr.wiring_for("engineer", Path(tmp) / "nope"), "n/a")


if __name__ == "__main__":
    unittest.main()
