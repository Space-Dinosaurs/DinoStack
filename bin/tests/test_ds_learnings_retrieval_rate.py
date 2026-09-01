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
# carrier rule in both directions).
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


def _run_cli(store: Path, executable: Path = CLI_PATH):
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(store)
    env.pop("AGENTIC_CONFIG_DIR", None)
    result = subprocess.run(
        [sys.executable, str(executable), "--json"],
        capture_output=True,
        text=True,
        env=env,
    )
    return result


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
