#!/usr/bin/env python3
"""
Regression spec for bin/ds-skill-load-rate (DS-227).

Fixtures are synthetic transcript stores built in a tmpdir with
CLAUDE_CONFIG_DIR pointed at them. The operator's real transcripts are
never read by a test. For every assertion, a mutation that would redden it
is named in the docstring or an inline comment, per the ticket's AC5.
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
CLI_PATH = REPO_DIR / "bin" / "ds-skill-load-rate"
ALIAS_PATH = REPO_DIR / "bin" / "agentic-skill-load-rate"

_loader = SourceFileLoader("ds_skill_load_rate", str(CLI_PATH))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
slr = importlib.util.module_from_spec(_spec)
sys.modules[_loader.name] = slr
_loader.exec_module(slr)


# ---------------------------------------------------------------------------
# Fixture record builders - each mirrors a shape verified against a live
# transcript, cited in the ticket and re-verified during implementation.
# ---------------------------------------------------------------------------


def slash_record(ts="2026-09-01T00:00:00.000Z"):
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": "<command-message>dinostack</command-message>\n<command-name>/dinostack</command-name>",
        },
        "timestamp": ts,
    }


def injected_body_record(ts="2026-09-01T00:00:01.000Z"):
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": "Base directory for this skill: /x/dinostack"}],
        },
        "timestamp": ts,
    }


def model_load_record(with_caller=True, tool_id="toolu_01AAA", ts="2026-09-01T00:00:00.000Z",
                       skill="dinostack"):
    tool_use = {"type": "tool_use", "id": tool_id, "name": "Skill", "input": {"skill": skill}}
    if with_caller:
        tool_use["caller"] = {"type": "direct"}
    return {
        "type": "assistant",
        "message": {"content": [tool_use]},
        "timestamp": ts,
    }


def other_skill_load_record(skill="ds-wrap", ts="2026-09-01T00:00:00.000Z"):
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "id": "toolu_01ZZZ", "name": "Skill",
                 "input": {"skill": skill}, "caller": {"type": "direct"}}
            ]
        },
        "timestamp": ts,
    }


def nudge_record(ts="2026-09-01T00:00:00.000Z"):
    return {
        "type": "attachment",
        "attachment": {
            "type": "hook_success",
            "hookName": "UserPromptSubmit",
            "content": "SKILL CHECK [dinostack]: skill_auto_load=true.\nBefore responding...",
            "command": "AE_ADAPTER=claude bash .../hooks/skill-auto-load-check.sh",
        },
        "timestamp": ts,
    }


def plain_record(ts="2026-09-01T00:00:00.000Z"):
    return {"type": "user", "message": {"role": "user", "content": "hello"}, "timestamp": ts}


def list_shaped_user_record_with_slash_text(ts="2026-09-01T00:00:00.000Z"):
    """A type:"user" record whose message.content is LIST-shaped (a
    tool_result payload) but happens to contain the slash-marker text
    inside a nested string - mirrors a live shape found in this session's
    own transcript (lines 227, 273, 320): a tool_result echoing a prior
    <command-name>/dinostack</command-name> invocation back into context.
    Must NOT be classified as an operator-typed load; only a bare-string
    message.content is the real trigger shape."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "content": [
                        {
                            "type": "text",
                            "text": "Earlier in this session: <command-name>/dinostack</command-name>",
                        }
                    ],
                }
            ],
        },
        "timestamp": ts,
    }


def nudge_wrong_hook_name_record(ts="2026-09-01T00:00:00.000Z"):
    """Same attachment.type and marker text as nudge_record, but a
    DIFFERENT hookName - must not be classified as the auto-load nudge."""
    return {
        "type": "attachment",
        "attachment": {
            "type": "hook_success",
            "hookName": "SomeOtherHook",
            "content": "SKILL CHECK [dinostack]: skill_auto_load=true.\nBefore responding...",
        },
        "timestamp": ts,
    }


def nudge_wrong_attachment_type_record(ts="2026-09-01T00:00:00.000Z"):
    """Same hookName and marker text as nudge_record, but a DIFFERENT
    attachment.type - must not be classified as the auto-load nudge."""
    return {
        "type": "attachment",
        "attachment": {
            "type": "hook_failure",
            "hookName": "UserPromptSubmit",
            "content": "SKILL CHECK [dinostack]: skill_auto_load=true.\nBefore responding...",
        },
        "timestamp": ts,
    }


def write_transcript(store: Path, project_dir_name: str, session_id: str, records: list) -> Path:
    project_dir = store / "projects" / project_dir_name
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / f"{session_id}.jsonl"
    lines = [json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


# Every real Claude-Code-form project directory name begins with "-" (an
# absolute path with each "/" replaced by "-"). Round-1's fixture had no
# leading dash, so all 13 invocations using it exercised a shape that
# cannot occur in production and could not have caught the Major 2
# leading-dash argparse defect - this name deliberately reproduces the
# real shape.
PROJECT = "-Users-tyson-fixture-repo"


def _run_cli(store: Path, extra_args=None, executable: Path = CLI_PATH, cwd: Path = None):
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(store)
    env.pop("AGENTIC_CONFIG_DIR", None)
    argv = [sys.executable, str(executable), "--json"]
    if extra_args:
        argv.extend(extra_args)
    result = subprocess.run(argv, capture_output=True, text=True, env=env, cwd=str(cwd) if cwd else None)
    return result


def _collect_json(store: Path, extra_args=None, executable: Path = CLI_PATH, cwd: Path = None) -> dict:
    result = _run_cli(store, extra_args, executable=executable, cwd=cwd)
    assert result.returncode == 0, result.stderr
    assert not result.stderr, result.stderr
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# classify_transcript: the core predicate
# ---------------------------------------------------------------------------


class TestClassifyTranscript(unittest.TestCase):
    def test_model_only_load_classifies_model(self):
        # Mutation: swap MODE_MODEL/MODE_OPERATOR in the mode-assignment
        # branch and this reddens.
        with tempfile.TemporaryDirectory() as tmp:
            path = write_transcript(Path(tmp), PROJECT, "s1", [model_load_record()])
            result = slr.classify_transcript(path)
            self.assertEqual(result["mode"], slr.MODE_MODEL)

    def test_operator_only_load_classifies_operator(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_transcript(
                Path(tmp), PROJECT, "s1", [slash_record(), injected_body_record()]
            )
            result = slr.classify_transcript(path)
            self.assertEqual(result["mode"], slr.MODE_OPERATOR)

    def test_no_load_classifies_none(self):
        # Mutation: delete the `if first_operator_line is None and
        # first_model_line is None: mode = None` branch and this reddens
        # (mode would come back as MODE_OPERATOR via the elif chain).
        with tempfile.TemporaryDirectory() as tmp:
            path = write_transcript(Path(tmp), PROJECT, "s1", [plain_record()])
            result = slr.classify_transcript(path)
            self.assertIsNone(result["mode"])

    def test_operator_first_wins_when_both_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = [
                slash_record(ts="2026-09-01T00:00:00.000Z"),
                model_load_record(ts="2026-09-01T00:00:05.000Z"),
            ]
            path = write_transcript(Path(tmp), PROJECT, "s1", records)
            result = slr.classify_transcript(path)
            self.assertEqual(result["mode"], slr.MODE_OPERATOR)

    def test_model_first_wins_when_both_present(self):
        # Mutation: flip the `<` to `>` in the tie-break comparison and this
        # reddens (would report MODE_OPERATOR instead).
        with tempfile.TemporaryDirectory() as tmp:
            records = [
                model_load_record(ts="2026-09-01T00:00:00.000Z"),
                slash_record(ts="2026-09-01T00:00:05.000Z"),
            ]
            path = write_transcript(Path(tmp), PROJECT, "s1", records)
            result = slr.classify_transcript(path)
            self.assertEqual(result["mode"], slr.MODE_MODEL)

    def test_caller_absent_skill_call_still_counts_as_model(self):
        """3 of 39 observed Skill tool_use records in the corpus this tool
        was built against omit `caller` entirely. Mutation: change
        _is_skill_load_call to require `"caller" in tool_input` and this
        reddens."""
        with tempfile.TemporaryDirectory() as tmp:
            path = write_transcript(
                Path(tmp), PROJECT, "s1",
                [model_load_record(with_caller=False, tool_id="call_00_xyz")],
            )
            result = slr.classify_transcript(path)
            self.assertEqual(result["mode"], slr.MODE_MODEL)

    def test_skill_load_for_a_different_skill_does_not_count(self):
        # Mutation: delete the TARGET_SKILL_NAMES membership check in
        # _is_skill_load_call and this reddens (mode would be MODE_MODEL).
        with tempfile.TemporaryDirectory() as tmp:
            path = write_transcript(Path(tmp), PROJECT, "s1", [other_skill_load_record()])
            result = slr.classify_transcript(path)
            self.assertIsNone(result["mode"])

    def test_pre_rename_agentic_engineering_skill_name_still_counts_as_model(self):
        """DS-227 round 3 Major 1: TARGET_SKILL_NAMES must include the
        pre-rename skill name "agentic-engineering" (commit 1e777841,
        2026-08-09 renamed .claude/skills/agentic-engineering to
        .claude/skills/dinostack - same skill, not a different one). A
        window straddling that date must count both names or it silently
        undercounts pre-rename model-initiated loads.
        Mutation: rewrite TARGET_SKILL_NAMES to frozenset({"dinostack"})
        and this reddens."""
        with tempfile.TemporaryDirectory() as tmp:
            path = write_transcript(
                Path(tmp), PROJECT, "s1",
                [model_load_record(skill="agentic-engineering")],
            )
            result = slr.classify_transcript(path)
            self.assertEqual(result["mode"], slr.MODE_MODEL)

    def test_nudge_fired_no_load_is_distinguished_from_no_nudge(self):
        """Proves the nudge-fired-but-no-load case actually distinguishes:
        a session with the nudge and a load must NOT be flagged, and a
        session with neither must not be flagged either."""
        with tempfile.TemporaryDirectory() as tmp:
            nudge_only = write_transcript(Path(tmp), PROJECT, "s1", [nudge_record()])
            nudge_and_load = write_transcript(
                Path(tmp), PROJECT, "s2", [nudge_record(), model_load_record()]
            )
            neither = write_transcript(Path(tmp), PROJECT, "s3", [plain_record()])

            r1 = slr.classify_transcript(nudge_only)
            r2 = slr.classify_transcript(nudge_and_load)
            r3 = slr.classify_transcript(neither)

            self.assertTrue(r1["nudge_fired"])
            self.assertIsNone(r1["mode"])

            self.assertTrue(r2["nudge_fired"])
            self.assertEqual(r2["mode"], slr.MODE_MODEL)

            self.assertFalse(r3["nudge_fired"])
            self.assertIsNone(r3["mode"])

    def test_list_shaped_user_content_with_slash_text_is_not_a_slash_load(self):
        """Major 5 (round 2): _slash_load_fired must require message.content
        to be a bare STRING, not merely contain the marker substring
        anywhere. Mutation: `isinstance(content, str) and SLASH_MARKER in
        content` -> `SLASH_MARKER in str(content)` and this reddens - a
        real transcript shape (a tool_result echoing a prior slash command
        back into context) would then be misclassified as MODE_OPERATOR."""
        with tempfile.TemporaryDirectory() as tmp:
            path = write_transcript(
                Path(tmp), PROJECT, "s1", [list_shaped_user_record_with_slash_text()]
            )
            result = slr.classify_transcript(path)
            self.assertIsNone(result["mode"])

    def test_nudge_requires_hook_success_attachment_type(self):
        """Major 5 (round 2): deleting the `attachment.get("type") !=
        "hook_success"` guard in _nudge_fired reddens this - a
        hook_failure-typed attachment carrying the marker text would then
        be misclassified as a fired nudge."""
        with tempfile.TemporaryDirectory() as tmp:
            path = write_transcript(
                Path(tmp), PROJECT, "s1", [nudge_wrong_attachment_type_record()]
            )
            result = slr.classify_transcript(path)
            self.assertFalse(result["nudge_fired"])

    def test_nudge_requires_user_prompt_submit_hook_name(self):
        """Major 5 (round 2): deleting the `attachment.get("hookName") !=
        "UserPromptSubmit"` guard in _nudge_fired reddens this - an
        attachment from a different hook carrying the marker text would
        then be misclassified as a fired nudge."""
        with tempfile.TemporaryDirectory() as tmp:
            path = write_transcript(
                Path(tmp), PROJECT, "s1", [nudge_wrong_hook_name_record()]
            )
            result = slr.classify_transcript(path)
            self.assertFalse(result["nudge_fired"])

    def test_zero_parsed_records_is_unreadable(self):
        # Mutation: delete the `if parsed == 0: return {"status":
        # STATUS_UNREADABLE}` check and this reddens (mode key would be
        # missing entirely, raising KeyError in the caller).
        with tempfile.TemporaryDirectory() as tmp:
            path = write_transcript(Path(tmp), PROJECT, "s1", [])
            result = slr.classify_transcript(path)
            self.assertEqual(result["status"], slr.STATUS_UNREADABLE)

    def test_oversize_file_is_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_transcript(Path(tmp), PROJECT, "s1", [plain_record()])
            original = slr.MAX_TRANSCRIPT_BYTES
            slr.MAX_TRANSCRIPT_BYTES = 1
            try:
                result = slr.classify_transcript(path)
            finally:
                slr.MAX_TRANSCRIPT_BYTES = original
            self.assertEqual(result["status"], slr.STATUS_UNREADABLE)

    def test_malformed_line_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / PROJECT
            project_dir.mkdir(parents=True, exist_ok=True)
            real_path = project_dir / "s1.jsonl"
            real_path.write_text(
                "not json\n" + json.dumps(model_load_record()) + "\n", encoding="utf-8"
            )
            result = slr.classify_transcript(real_path)
            self.assertEqual(result["mode"], slr.MODE_MODEL)

    def test_window_timestamps_track_min_and_max(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = [
                model_load_record(ts="2026-09-01T00:00:00.000Z"),
                plain_record(ts="2026-08-01T00:00:00.000Z"),
                plain_record(ts="2026-09-15T00:00:00.000Z"),
            ]
            path = write_transcript(Path(tmp), PROJECT, "s1", records)
            result = slr.classify_transcript(path)
            self.assertEqual(result["min_ts"], "2026-08-01T00:00:00.000Z")
            self.assertEqual(result["max_ts"], "2026-09-15T00:00:00.000Z")


# ---------------------------------------------------------------------------
# Scope resolution
# ---------------------------------------------------------------------------


class TestScopeResolution(unittest.TestCase):
    def test_project_dir_name_for_replaces_slash_only(self):
        # Mutation: change the transform to also replace "." and this
        # reddens against the real corpus naming (dot-bearing project dirs
        # like -Users-tyson-.claude-commands exist and must not shift).
        self.assertEqual(
            slr.project_dir_name_for("/Users/tyson/Documents/Development/ai-tools/DinoStack"),
            "-Users-tyson-Documents-Development-ai-tools-DinoStack",
        )
        self.assertEqual(
            slr.project_dir_name_for("/Users/tyson/.claude/commands"),
            "-Users-tyson-.claude-commands",
        )

    def test_explicit_repo_path_scope_is_repo_path_mode(self):
        """Named (round 2) to match what it actually exercises: an
        EXPLICIT --repo-path flag, not the no-flag default. See
        test_default_scope_with_no_flags_derives_from_cwd below for the
        actual default-scope (no scope flag at all) coverage."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "config"
            write_transcript(store, PROJECT, "s1", [model_load_record()])
            repo_like = Path(tmp) / "fixture-repo"
            repo_like.mkdir()
            # Rename the project dir to match what this repo_like path would
            # derive to, so the cwd-default path actually finds it.
            derived = slr.project_dir_name_for(str(repo_like))
            (store / "projects" / derived).mkdir(parents=True, exist_ok=True)
            for f in (store / "projects" / PROJECT).glob("*.jsonl"):
                (store / "projects" / derived / f.name).write_text(f.read_text())

            payload = _collect_json(store, extra_args=["--repo-path", str(repo_like)])
            self.assertEqual(payload["scope"]["mode"], "repo-path")
            self.assertEqual(payload["sessions_scanned"], 1)
            self.assertEqual(payload["sessions_model"], 1)

    def test_default_scope_with_no_flags_derives_from_cwd(self):
        """The tool's primary use case: no scope flag at all. Mutation
        (Major 4, verified in round 2): replace
        `args.repo_path or os.getcwd()` with `args.repo_path or
        "/nonexistent-mutant"` AND `"cwd-default"` with `"MUTANT"` in
        resolve_scope - both reddened this test (KeyError/wrong-mode
        assertion failure), where the misnamed round-1 test
        (test_explicit_repo_path_scope_is_repo_path_mode, which always
        passes --repo-path explicitly) did not move at all."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "config"
            repo_like = Path(tmp) / "fixture-repo"
            repo_like.mkdir()
            # os.getcwd() inside the subprocess reports the OS's own view of
            # the cwd, which can differ from our own un-resolved tmp path on
            # a host where /tmp (or /var) is itself a symlink (e.g. macOS's
            # /var -> /private/var) - derive the expected name from the
            # subprocess's own getcwd(), not from repo_like's literal string.
            actual_cwd = subprocess.run(
                [sys.executable, "-c", "import os; print(os.getcwd())"],
                capture_output=True, text=True, cwd=str(repo_like),
            ).stdout.strip()
            derived = slr.project_dir_name_for(actual_cwd)
            write_transcript(store, derived, "s1", [model_load_record()])

            payload = _collect_json(store, extra_args=[], cwd=repo_like)
            self.assertEqual(payload["scope"]["mode"], "cwd-default")
            self.assertEqual(payload["scope"]["derived_project_dir"], derived)
            self.assertEqual(payload["sessions_scanned"], 1)
            self.assertEqual(payload["sessions_model"], 1)

    def test_explicit_project_dir_scopes_to_exactly_that_directory(self):
        # Mutation: have resolve_scope ignore args.project_dir and fall
        # through to cwd-default, and this reddens (would find 0 sessions).
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            write_transcript(store, "proj-a", "s1", [model_load_record()])
            write_transcript(store, "proj-b", "s1", [slash_record()])
            payload = _collect_json(store, extra_args=["--project-dir", "proj-a"])
            self.assertEqual(payload["scope"]["project_dirs"], ["proj-a"])
            self.assertEqual(payload["sessions_scanned"], 1)
            self.assertEqual(payload["sessions_model"], 1)
            self.assertEqual(payload["sessions_operator"], 0)

    def test_scope_never_leaks_an_unrelated_project(self):
        """AC scoping constraint: an unscoped run must not fold in a
        sibling project's sessions. Mutation: have resolve_scope glob
        `projects/*` unconditionally and this reddens (sessions_scanned
        would be 2, not 1)."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            write_transcript(store, "proj-a", "s1", [model_load_record()])
            write_transcript(store, "proj-other-repo", "s1", [model_load_record()])
            payload = _collect_json(store, extra_args=["--project-dir", "proj-a"])
            self.assertEqual(payload["sessions_scanned"], 1)

    def test_all_projects_scans_every_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            write_transcript(store, "proj-a", "s1", [model_load_record()])
            write_transcript(store, "proj-b", "s1", [slash_record()])
            payload = _collect_json(store, extra_args=["--all-projects"])
            self.assertEqual(payload["sessions_scanned"], 2)
            self.assertEqual(set(payload["scope"]["project_dirs"]), {"proj-a", "proj-b"})

    def test_project_dir_and_repo_path_and_all_projects_are_mutually_exclusive(self):
        result = _run_cli(
            Path(tempfile.mkdtemp()),
            extra_args=["--project-dir", "x", "--all-projects"],
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not allowed with argument", result.stderr)

    def test_project_dir_space_separated_before_another_scope_flag_stays_mutex(self):
        """DS-227 round 3 Major 2: _normalize_argv must NOT rewrite
        `--project-dir --all-projects` into
        `--project-dir=--all-projects` - that swallowed a real scope flag
        as a bogus value and exited 0 with a silent no-data report,
        indistinguishable from a real no-data result. The correct behavior
        is argparse's own "expected one argument" usage error, exit != 0.
        Mutation: drop the `not argv[i + 1].startswith("--")` guard in
        _normalize_argv and this reddens (rc becomes 0)."""
        result = _run_cli(
            Path(tempfile.mkdtemp()),
            extra_args=["--project-dir", "--all-projects"],
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected one argument", result.stderr)

    def test_repo_path_space_separated_before_another_scope_flag_stays_mutex(self):
        """Same defect, --repo-path form. Measured pre-fix: `--repo-path
        --all-projects` printed `repo_path: <cwd>/--all-projects` and
        exited 0."""
        result = _run_cli(
            Path(tempfile.mkdtemp()),
            extra_args=["--repo-path", "--all-projects"],
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected one argument", result.stderr)


# ---------------------------------------------------------------------------
# Honest reporting: no fabricated zero, scope on every figure, ABSENT literal
# ---------------------------------------------------------------------------


class TestHonestReporting(unittest.TestCase):
    def test_no_transcripts_reports_error_envelope_never_a_bare_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = _collect_json(Path(tmp), extra_args=["--project-dir", "nope"])
            self.assertEqual(payload["error"], "no_transcripts")
            self.assertEqual(payload["sessions_scanned"], 0)

    def test_json_headline_fields_present_and_null_absent_pair_on_no_data(self):
        """DS-227 round 3 Minor 1: the manifest promises `unprompted_load_rate`
        (JSON null on no-data) and `unprompted_load_rate_display` (the
        literal string "ABSENT" on no-data) in --json output. Mutation:
        delete the `_finalize_rate_fields(payload)` call on the
        no_transcripts early-return path and this reddens (KeyError)."""
        with tempfile.TemporaryDirectory() as tmp:
            payload = _collect_json(Path(tmp), extra_args=["--project-dir", "nope"])
            self.assertIn("unprompted_load_rate", payload)
            self.assertIn("unprompted_load_rate_display", payload)
            self.assertIsNone(payload["unprompted_load_rate"])
            self.assertEqual(payload["unprompted_load_rate_display"], "ABSENT")

    def test_json_headline_fields_present_and_typed_on_real_data(self):
        """Same two fields on a real (non-no-data) scan: the numeric field
        is a float in [0, 1] and the display field is the "NN.N%" string
        format_rate() produces for it - not just present, but internally
        consistent with each other. Mutation: replace `_finalize_rate_fields`
        body with `pass` and this reddens (KeyError on missing keys)."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            write_transcript(store, PROJECT, "s1", [model_load_record()])
            write_transcript(store, PROJECT, "s2", [slash_record()])
            payload = _collect_json(store, extra_args=["--project-dir", PROJECT])
            self.assertIsInstance(payload["unprompted_load_rate"], float)
            self.assertEqual(payload["unprompted_load_rate"], 0.5)
            self.assertEqual(payload["unprompted_load_rate_display"], "50.0%")

    def test_no_transcripts_human_render_says_absent_not_zero(self):
        # Mutation: render "0.0%" instead of ABSENT on the no-data path and
        # this reddens - the whole point of AC3 is distinguishing "no data"
        # from "measured zero".
        with tempfile.TemporaryDirectory() as tmp:
            argv = [sys.executable, str(CLI_PATH), "--project-dir", "nope"]
            env = dict(os.environ)
            env["CLAUDE_CONFIG_DIR"] = str(tmp)
            out = subprocess.run(argv, capture_output=True, text=True, env=env).stdout
            self.assertIn("ABSENT", out)
            self.assertNotIn("0.0%", out)

    def test_format_rate_none_is_absent_literal(self):
        self.assertEqual(slr.format_rate(None), slr.ABSENT)
        self.assertEqual(slr.ABSENT, "ABSENT")

    def test_format_rate_zero_is_a_real_zero_not_absent(self):
        """A genuine zero measurement (data was readable, nothing fired)
        must render as 0.0%, distinct from the no-data ABSENT case.
        Mutation: collapse format_rate(0.0) to ABSENT and this reddens."""
        self.assertEqual(slr.format_rate(0.0), "0.0%")

    def test_all_unreadable_render_shows_absent_denominator_not_zero(self):
        """DS-227 round 3 Minor 2: a scan whose transcripts all parse to
        zero records (all unreadable, denominator 0) must render the
        readable-transcript-count and headline denominator as the literal
        string ABSENT, never the fabricated integer 0 - the same
        never-zero-fill discipline PR #723 established. Mutation: change
        `denom if denom > 0 else ABSENT` to bare `denom` at either of its
        two call sites in render() and this reddens."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            write_transcript(store, PROJECT, "s1", [])
            write_transcript(store, PROJECT, "s2", [])
            payload = _collect_json(store, extra_args=["--project-dir", PROJECT])
            self.assertEqual(payload["sessions_scanned"], 2)
            self.assertEqual(payload["sessions_unreadable"], 2)
            self.assertIsNone(payload["unprompted_load_rate"])

            argv = [sys.executable, str(CLI_PATH), "--project-dir", PROJECT]
            env = dict(os.environ)
            env["CLAUDE_CONFIG_DIR"] = str(store)
            out = subprocess.run(argv, capture_output=True, text=True, env=env).stdout
            self.assertIn("sessions with a readable transcript: ABSENT", out)
            self.assertIn("(0/ABSENT readable sessions in scope)", out)
            self.assertNotIn("readable transcript: 0", out)

    def test_unprompted_rate_denominator_excludes_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            write_transcript(store, PROJECT, "s1", [model_load_record()])
            write_transcript(store, PROJECT, "s2", [])  # zero records -> unreadable
            payload = _collect_json(store, extra_args=["--project-dir", PROJECT])
            self.assertEqual(payload["sessions_scanned"], 2)
            self.assertEqual(payload["sessions_unreadable"], 1)
            rate = slr.unprompted_rate(payload)
            self.assertEqual(rate, 1.0)

    def test_totals_invariant_holds(self):
        """sessions_scanned == unreadable + operator + model + no_load in
        every run. Mutation: increment sessions_scanned without updating
        one of the four buckets and this reddens."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            write_transcript(store, PROJECT, "s1", [model_load_record()])
            write_transcript(store, PROJECT, "s2", [slash_record()])
            write_transcript(store, PROJECT, "s3", [plain_record()])
            write_transcript(store, PROJECT, "s4", [])
            write_transcript(store, PROJECT, "s5", [nudge_record()])
            payload = _collect_json(store, extra_args=["--project-dir", PROJECT])
            total = (
                payload["sessions_unreadable"]
                + payload["sessions_operator"]
                + payload["sessions_model"]
                + payload["sessions_no_load"]
            )
            self.assertEqual(payload["sessions_scanned"], total)
            self.assertEqual(payload["sessions_scanned"], 5)

    def test_scope_is_present_on_every_report(self):
        """AC2: a rate without its scope is not a verified claim - assert
        the human render always states the scope mode and project dirs."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            write_transcript(store, PROJECT, "s1", [model_load_record()])
            argv = [sys.executable, str(CLI_PATH), "--project-dir", PROJECT]
            env = dict(os.environ)
            env["CLAUDE_CONFIG_DIR"] = str(store)
            out = subprocess.run(argv, capture_output=True, text=True, env=env).stdout
            self.assertIn("scope mode:", out)
            self.assertIn("project directories scanned", out)
            self.assertIn("window (date range):", out)

    def test_human_render_headline_matches_json_figures(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            write_transcript(store, PROJECT, "s1", [model_load_record()])
            write_transcript(store, PROJECT, "s2", [slash_record()])
            payload = _collect_json(store, extra_args=["--project-dir", PROJECT])
            argv = [sys.executable, str(CLI_PATH), "--project-dir", PROJECT]
            env = dict(os.environ)
            env["CLAUDE_CONFIG_DIR"] = str(store)
            out = subprocess.run(argv, capture_output=True, text=True, env=env).stdout
            self.assertIn(f"{slr.format_rate(slr.unprompted_rate(payload))}", out)
            self.assertIn("(1/2 readable sessions in scope)", out)


# ---------------------------------------------------------------------------
# Read-only guarantee
# ---------------------------------------------------------------------------


class TestReadOnly(unittest.TestCase):
    def test_running_the_tool_never_mutates_the_transcript_store(self):
        """Mutation: add any os.remove/Path.write_text/open(...,'w') call
        anywhere in collect()/classify_transcript() and this reddens, since
        it would change either the file set or a file's bytes."""
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            path = write_transcript(store, PROJECT, "s1", [model_load_record(), nudge_record()])
            before_bytes = path.read_bytes()
            before_listing = sorted(p.name for p in (store / "projects" / PROJECT).iterdir())

            for extra in (["--project-dir", PROJECT], ["--project-dir", PROJECT, "--json"],
                          ["--all-projects"]):
                _run_cli(store, extra_args=extra)

            after_bytes = path.read_bytes()
            after_listing = sorted(p.name for p in (store / "projects" / PROJECT).iterdir())
            self.assertEqual(before_bytes, after_bytes)
            self.assertEqual(before_listing, after_listing)


# ---------------------------------------------------------------------------
# Compat symlink
# ---------------------------------------------------------------------------


class TestCompatSymlink(unittest.TestCase):
    def test_agentic_alias_exists_and_resolves_to_ds_name(self):
        self.assertTrue(ALIAS_PATH.is_symlink())
        self.assertEqual(os.readlink(ALIAS_PATH), "ds-skill-load-rate")

    def test_agentic_alias_behaves_identically(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            write_transcript(store, PROJECT, "s1", [model_load_record()])
            via_ds = _collect_json(store, extra_args=["--project-dir", PROJECT])
            via_alias = _collect_json(
                store, extra_args=["--project-dir", PROJECT], executable=ALIAS_PATH
            )
            self.assertEqual(via_ds["sessions_model"], via_alias["sessions_model"])


if __name__ == "__main__":
    unittest.main()
