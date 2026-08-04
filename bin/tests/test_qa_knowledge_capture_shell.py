"""
Purpose: Executes the QA knowledge capture shell block
         (content/references/qa-gate.md, marked `@harness:qa-knowledge-capture`)
         against real temp-git fixtures under bash, zsh, and sh, so the
         extraction/dedup/append behavior that replaces qa-engineer's former
         (broken, isolation-worktree-scoped) direct write is verified against
         real filesystem state instead of only ever being read as prose.
         Covers 14 required cases: happy-path append, dedup (case/whitespace,
         legacy no-date bullet, `*`-bulleted line, cross-section false
         positive), malformed input, absent qa.md (both locations), legacy
         `.claude/qa.md` fallback, CRLF / no-trailing-newline heading
         placement, invalid-date fallback + idempotent re-run, special
         characters round-tripping through the heredoc/JSON layer, multiple
         `## Knowledge` headings, the reproduced BSD-mktemp-suffix squat
         defect, non-UTF-8 input, and an unwritable qa.md.

Public API: none (pytest test module; 14 cases x {bash, zsh, sh} = 42 tests).

Upstream deps: bin/tests/lib/md_shell_extract.py, bin/tests/lib/git_fixture.py,
               content/references/qa-gate.md (file under test).

Downstream consumers: .github/workflows/bin-tests.yml (python-bin-tests job).

Failure modes: n/a (test module). Deliberately does NOT call
               lib.md_shell_extract.render() - that helper's
               PLACEHOLDER_WHITELIST is hardcoded to Phase 8 keys and raises
               on any other block; this harness does its own single-token
               substitution of `[...the extracted array...]` instead.

Performance: standard; each parametrized test does a handful of local git
             operations plus one subprocess shell invocation.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib.git_fixture as git_fixture  # noqa: E402
import lib.md_shell_extract as mse  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MD_PATH = REPO_ROOT / "content" / "references" / "qa-gate.md"
MARKER = "qa-knowledge-capture"
PLACEHOLDER = "[...the extracted array...]"

SHELLS = ["bash", "zsh", "sh"]


def _shell_or_skip(shell: str) -> str:
    """Skip locally when a shell is missing; hard-fail in CI so no shell in
    the matrix can be silently dropped (see MEMORY.md's 'green often means
    the check did not run' lesson)."""
    if shutil.which(shell) is None:
        if os.environ.get("CI"):
            pytest.fail(f"{shell} not found in CI - the python-bin-tests job must install it")
        pytest.skip(f"{shell} not found on this machine")
    return shell


def _raw_block() -> str:
    return mse.extract_marked_block(str(MD_PATH), MARKER)


def _script(entries_text: str) -> str:
    """Substitute the single `[...the extracted array...]` placeholder for
    entries_text. Deliberately NOT lib.md_shell_extract.render() - that
    helper's PLACEHOLDER_WHITELIST is Phase-8-specific and raises on any
    block that doesn't contain its keys."""
    block = _raw_block()
    count = block.count(PLACEHOLDER)
    assert count == 1, f"expected placeholder {PLACEHOLDER!r} exactly once, found {count}"
    return block.replace(PLACEHOLDER, entries_text)


def _entries_json(entries: list[dict]) -> str:
    return json.dumps(entries, indent=2)


def _make_env(fixture: git_fixture.Fixture, tmp_path: Path) -> dict[str, str]:
    """Fixture env, with TMPDIR pinned to a fixture-local dir so the block's
    mktemp calls never touch the real host /tmp and so "no temp file left
    behind" assertions can enumerate a known-clean directory."""
    env = dict(fixture.env)
    tmpdir = tmp_path / "qa-tmpdir"
    tmpdir.mkdir(parents=True, exist_ok=True)
    env["TMPDIR"] = str(tmpdir)
    return env


def _run(entries_text: str, fixture: git_fixture.Fixture, env: dict, shell: str, timeout: int = 60):
    script = mse.with_completion_marker(_script(entries_text))
    return subprocess.run(
        [shell, "-c", script],
        cwd=str(fixture.repo_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _assert_completed(result: subprocess.CompletedProcess) -> None:
    assert mse.COMPLETION_MARKER in result.stdout, (
        f"block did not reach completion.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def _leftover_temp_files(env: dict) -> list[Path]:
    tmpdir = Path(env["TMPDIR"])
    return sorted(tmpdir.glob("qa-knowledge-*"))


def _write_qa_md(repo_dir: Path, content: str, legacy: bool = False, crlf: bool = False) -> Path:
    rel = ".claude/qa.md" if legacy else ".agentic/qa.md"
    path = repo_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if crlf:
        content = content.replace("\n", "\r\n")
    path.write_bytes(content.encode("utf-8"))
    return path


def _qa_md_path(repo_dir: Path, legacy: bool = False) -> Path:
    return repo_dir / (".claude/qa.md" if legacy else ".agentic/qa.md")


# ---------------------------------------------------------------------------
# Harness self-check.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_extraction_is_non_vacuous(shell):
    shell = _shell_or_skip(shell)
    block = _raw_block()
    assert block.count(PLACEHOLDER) == 1
    for anchor in ("QA_KNOWLEDGE_TMP", "QA_MD", "rm -f"):
        assert anchor in block, f"expected literal anchor {anchor!r} in extracted block"
    rendered = _script(_entries_json([]))
    check = mse.syntax_check(rendered, shell)
    assert check.returncode == 0, check.stderr


# ---------------------------------------------------------------------------
# Case 1. Well-formed 2-entry payload appends both, creates ## Knowledge.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_case1_two_entries_creates_knowledge_section(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    _write_qa_md(fixture.repo_dir, "# QA Config\n## Dev server\ncommand: npm run dev\n")
    env = _make_env(fixture, tmp_path)
    entries = [
        {"tag": "timing", "description": "Wait 2s after nav to /dashboard", "date": "2026-08-01"},
        {"tag": "auth", "description": "Use demo@example.com / password", "date": "2026-08-01"},
    ]
    result = _run(_entries_json(entries), fixture, env, shell)
    _assert_completed(result)
    text = _qa_md_path(fixture.repo_dir).read_text(encoding="utf-8")
    assert "## Knowledge" in text
    assert "- [2026-08-01] timing: Wait 2s after nav to /dashboard" in text
    assert "- [2026-08-01] auth: Use demo@example.com / password" in text
    assert not _leftover_temp_files(env), _leftover_temp_files(env)


# ---------------------------------------------------------------------------
# Case 2. Duplicate (tag, description), case/whitespace-varied, is skipped.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_case2_duplicate_case_whitespace_varied_skipped(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    _write_qa_md(
        fixture.repo_dir,
        "# QA Config\n\n## Knowledge\n- [2026-01-01] timing:   Wait   2s  after nav\n",
    )
    env = _make_env(fixture, tmp_path)
    entries = [{"tag": "TIMING".lower(), "description": "wait 2s   AFTER nav", "date": "2026-08-01"}]
    result = _run(_entries_json(entries), fixture, env, shell)
    _assert_completed(result)
    assert "no new knowledge entries" in result.stdout
    text = _qa_md_path(fixture.repo_dir).read_text(encoding="utf-8")
    assert text.count("## Knowledge") == 1
    assert "2026-08-01" not in text


# ---------------------------------------------------------------------------
# Case 3. Coincidental match under a different section is NOT skipped.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_case3_match_under_different_section_not_deduped(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    _write_qa_md(
        fixture.repo_dir,
        "# QA Config\n\n## QA triggers\n- timing: Wait 2s after nav\n\n## Knowledge\n",
    )
    env = _make_env(fixture, tmp_path)
    entries = [{"tag": "timing", "description": "Wait 2s after nav", "date": "2026-08-01"}]
    result = _run(_entries_json(entries), fixture, env, shell)
    _assert_completed(result)
    assert "appended 1 knowledge entry" in result.stdout
    text = _qa_md_path(fixture.repo_dir).read_text(encoding="utf-8")
    assert "- [2026-08-01] timing: Wait 2s after nav" in text


# ---------------------------------------------------------------------------
# Case 4. Malformed JSON -> WARNING, no write, temp file removed, exit 0.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_case4_malformed_json_skips_cleanly(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    _write_qa_md(fixture.repo_dir, "# QA Config\n")
    env = _make_env(fixture, tmp_path)
    result = _run("{not valid json[", fixture, env, shell)
    _assert_completed(result)
    assert result.returncode == 0
    assert "WARNING" in result.stdout
    text = _qa_md_path(fixture.repo_dir).read_text(encoding="utf-8")
    assert text == "# QA Config\n"
    assert not _leftover_temp_files(env), _leftover_temp_files(env)


# ---------------------------------------------------------------------------
# Case 5. Neither qa.md exists -> WARNING, exit 0, completion marker present.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_case5_neither_qa_md_exists(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    env = _make_env(fixture, tmp_path)
    entries = [{"tag": "timing", "description": "irrelevant", "date": "2026-08-01"}]
    result = _run(_entries_json(entries), fixture, env, shell)
    _assert_completed(result)
    assert result.returncode == 0
    assert "WARNING" in result.stdout
    assert not _qa_md_path(fixture.repo_dir).exists()
    assert not _qa_md_path(fixture.repo_dir, legacy=True).exists()
    assert not _leftover_temp_files(env), _leftover_temp_files(env)


# ---------------------------------------------------------------------------
# Case 6. Only legacy .claude/qa.md exists -> entries land there.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_case6_legacy_qa_md_only(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    _write_qa_md(fixture.repo_dir, "# QA Config (legacy)\n", legacy=True)
    env = _make_env(fixture, tmp_path)
    entries = [{"tag": "port", "description": "Use port 4000 not 3000", "date": "2026-08-01"}]
    result = _run(_entries_json(entries), fixture, env, shell)
    _assert_completed(result)
    text = _qa_md_path(fixture.repo_dir, legacy=True).read_text(encoding="utf-8")
    assert "- [2026-08-01] port: Use port 4000 not 3000" in text
    assert not _qa_md_path(fixture.repo_dir).exists()


# ---------------------------------------------------------------------------
# Case 7. Legacy no-date bullet AND *-bulleted line both dedupe.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_case7_legacy_bullet_styles_dedupe(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    _write_qa_md(
        fixture.repo_dir,
        "# QA Config\n\n## Knowledge\n"
        "- timing: legacy no date entry\n"
        "* auth: star bulleted entry\n",
    )
    env = _make_env(fixture, tmp_path)
    entries = [
        {"tag": "timing", "description": "legacy no date entry", "date": "2026-08-01"},
        {"tag": "auth", "description": "star bulleted entry", "date": "2026-08-01"},
    ]
    result = _run(_entries_json(entries), fixture, env, shell)
    _assert_completed(result)
    assert "no new knowledge entries" in result.stdout
    text = _qa_md_path(fixture.repo_dir).read_text(encoding="utf-8")
    assert "2026-08-01" not in text


# ---------------------------------------------------------------------------
# Case 8. CRLF file, and "## Knowledge" as last line with no trailing
# newline - neither produces a duplicate heading.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_case8a_crlf_no_duplicate_heading(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    _write_qa_md(
        fixture.repo_dir,
        "# QA Config\n\n## Knowledge\n- [2026-01-01] timing: existing entry\n",
        crlf=True,
    )
    env = _make_env(fixture, tmp_path)
    entries = [{"tag": "auth", "description": "new distinct entry", "date": "2026-08-01"}]
    result = _run(_entries_json(entries), fixture, env, shell)
    _assert_completed(result)
    text = _qa_md_path(fixture.repo_dir).read_text(encoding="utf-8")
    assert text.count("## Knowledge") == 1
    assert "new distinct entry" in text


@pytest.mark.parametrize("shell", SHELLS)
def test_case8b_knowledge_as_last_line_no_trailing_newline(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    path = _qa_md_path(fixture.repo_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"# QA Config\n\n## Knowledge")
    env = _make_env(fixture, tmp_path)
    entries = [{"tag": "noise", "description": "ignore this warning", "date": "2026-08-01"}]
    result = _run(_entries_json(entries), fixture, env, shell)
    _assert_completed(result)
    text = path.read_text(encoding="utf-8")
    assert text.count("## Knowledge") == 1
    assert "ignore this warning" in text


# ---------------------------------------------------------------------------
# Case 9. Non-zero-padded date falls back to today; running twice produces
# exactly ONE line.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_case9_invalid_date_falls_back_and_idempotent(tmp_path, shell):
    import datetime

    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    _write_qa_md(fixture.repo_dir, "# QA Config\n")
    env = _make_env(fixture, tmp_path)
    entries = [{"tag": "retry", "description": "retry search endpoint once", "date": "2026-8-3"}]
    result1 = _run(_entries_json(entries), fixture, env, shell)
    _assert_completed(result1)
    today = datetime.date.today().isoformat()
    text = _qa_md_path(fixture.repo_dir).read_text(encoding="utf-8")
    assert f"- [{today}] retry: retry search endpoint once" in text
    assert "2026-8-3" not in text

    result2 = _run(_entries_json(entries), fixture, env, shell)
    _assert_completed(result2)
    text2 = _qa_md_path(fixture.repo_dir).read_text(encoding="utf-8")
    assert text2.count("retry search endpoint once") == 1


# ---------------------------------------------------------------------------
# Case 10. Apostrophe, double quote, and $VAR-shaped substring round-trip.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_case10_special_characters_round_trip(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    _write_qa_md(fixture.repo_dir, "# QA Config\n")
    env = _make_env(fixture, tmp_path)
    desc = "It's a \"quoted\" $HOME reference, not expanded"
    entries = [{"tag": "tool", "description": desc, "date": "2026-08-01"}]
    result = _run(_entries_json(entries), fixture, env, shell)
    _assert_completed(result)
    text = _qa_md_path(fixture.repo_dir).read_text(encoding="utf-8")
    assert f"- [2026-08-01] tool: {desc}" in text


# ---------------------------------------------------------------------------
# Case 11. Two ## Knowledge headings, entry under the second -> not
# re-appended into the first.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_case11_dedup_across_multiple_knowledge_headings(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    _write_qa_md(
        fixture.repo_dir,
        "# QA Config\n\n"
        "## Knowledge\n- [2026-01-01] timing: first section entry\n\n"
        "## Other\nsome content\n\n"
        "## Knowledge\n- [2026-01-02] auth: second section entry\n",
    )
    env = _make_env(fixture, tmp_path)
    entries = [{"tag": "auth", "description": "second section entry", "date": "2026-08-01"}]
    result = _run(_entries_json(entries), fixture, env, shell)
    _assert_completed(result)
    assert "no new knowledge entries" in result.stdout
    text = _qa_md_path(fixture.repo_dir).read_text(encoding="utf-8")
    # First section must not have gained the (duplicate) entry.
    first_section = text.split("## Other")[0]
    assert "second section entry" not in first_section
    assert "2026-08-01" not in text


# ---------------------------------------------------------------------------
# Case 12. Squat test - a literal pre-existing "qa-knowledge-XXXXXX" file
# must survive untouched, and mktemp must still produce a fresh randomized
# path (BSD/macOS non-trailing-X non-randomization regression guard).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_case12_squat_pre_created_literal_mktemp_name(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    _write_qa_md(fixture.repo_dir, "# QA Config\n")
    env = _make_env(fixture, tmp_path)

    squat_path = Path(env["TMPDIR"]) / "qa-knowledge-XXXXXX"
    squat_content = b"do-not-touch-this-literal-file\n"
    squat_path.write_bytes(squat_content)

    entries = [{"tag": "server", "description": "extra --no-sandbox flag needed", "date": "2026-08-01"}]
    result = _run(_entries_json(entries), fixture, env, shell)
    _assert_completed(result)
    assert "WARNING: qa knowledge capture skipped - could not create a temp file" not in result.stdout

    # The literal squat file must be untouched.
    assert squat_path.read_bytes() == squat_content

    # No OTHER temp file should remain (the real run's mktemp file was
    # consumed and removed).
    leftovers = [p for p in _leftover_temp_files(env) if p != squat_path]
    assert not leftovers, leftovers

    text = _qa_md_path(fixture.repo_dir).read_text(encoding="utf-8")
    assert "extra --no-sandbox flag needed" in text


# ---------------------------------------------------------------------------
# Case 13. Non-UTF-8 qa.md -> WARNING naming the read failure, no write,
# exit 0, no traceback on stderr.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_case13_non_utf8_qa_md_warns_cleanly(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    path = _qa_md_path(fixture.repo_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    original = b"# QA Config\n\xff\xfe not valid utf-8 \xff\n"
    path.write_bytes(original)
    env = _make_env(fixture, tmp_path)
    entries = [{"tag": "timing", "description": "irrelevant", "date": "2026-08-01"}]
    result = _run(_entries_json(entries), fixture, env, shell)
    _assert_completed(result)
    assert result.returncode == 0
    assert "WARNING" in result.stdout
    assert "Traceback" not in result.stderr
    assert path.read_bytes() == original
    assert not _leftover_temp_files(env), _leftover_temp_files(env)


# ---------------------------------------------------------------------------
# Case 14. Unwritable qa.md -> WARNING naming the write failure, exit 0, no
# traceback. Skipped gracefully when permission bits are unenforceable
# (e.g. running as root in a container).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shell", SHELLS)
def test_case14_unwritable_qa_md_warns_cleanly(tmp_path, shell):
    shell = _shell_or_skip(shell)
    fixture = git_fixture.build_consumer_shape(tmp_path)
    path = _qa_md_path(fixture.repo_dir)
    original = b"# QA Config\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(original)
    path.chmod(0o444)
    try:
        # Permission bits are unenforceable for the root user (e.g. inside
        # an unprivileged-by-default CI container running as root) - skip
        # the assertion gracefully in that case rather than false-failing.
        if os.access(path, os.W_OK):
            pytest.skip(
                "permission bits unenforceable for the current user "
                "(likely running as root) - cannot exercise the unwritable-file path"
            )
        env = _make_env(fixture, tmp_path)
        entries = [{"tag": "timing", "description": "irrelevant", "date": "2026-08-01"}]
        result = _run(_entries_json(entries), fixture, env, shell)
        _assert_completed(result)
        assert result.returncode == 0
        assert "WARNING" in result.stdout
        assert "Traceback" not in result.stderr
        assert path.read_bytes() == original
        assert not _leftover_temp_files(env), _leftover_temp_files(env)
    finally:
        path.chmod(0o644)
