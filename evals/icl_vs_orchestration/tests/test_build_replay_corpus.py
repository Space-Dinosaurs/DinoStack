"""Tests for evals/icl_vs_orchestration/scripts/build_replay_corpus.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from evals.icl_vs_orchestration.scripts.build_replay_corpus import (
    TICKETS,
    build,
    write_file_from_git,
)


# ---------------------------------------------------------------------------
# Test 1: dry-run prints intended writes without touching disk
# ---------------------------------------------------------------------------

def test_dry_run_prints_without_writing(tmp_path: Path, capsys) -> None:
    """dry-run=True must print DRY: lines and write no files."""
    corpus_root = tmp_path / "corpora" / "replay"
    # Create skeleton dirs so dry-run can report paths
    for slug, spec in TICKETS.items():
        for subdir in ("relevant_files", "workspace_files"):
            (corpus_root / "tickets" / slug / subdir).mkdir(parents=True)

    build(corpus_root, dry_run=True)

    captured = capsys.readouterr()
    # At least one DRY: line per non-empty ticket
    assert "DRY:" in captured.out

    # No actual files written (only dirs we created above)
    written_files = [
        p for p in corpus_root.rglob("*")
        if p.is_file()
    ]
    assert written_files == [], f"dry-run wrote files: {written_files}"


# ---------------------------------------------------------------------------
# Test 2: actual run with mocked subprocess.run
# ---------------------------------------------------------------------------

def test_build_calls_git_show_and_writes_files(tmp_path: Path) -> None:
    """build() writes file content returned by git show into both subdirs."""
    corpus_root = tmp_path / "corpora" / "replay"
    fake_content = "# fake content\n"

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = fake_content

    with patch(
        "evals.icl_vs_orchestration.scripts.build_replay_corpus.subprocess.run",
        return_value=mock_result,
    ) as mock_run:
        build(corpus_root, dry_run=False, ticket_filter="r-trivial-heading-parser")

    spec = TICKETS["r-trivial-heading-parser"]
    expected_calls = len(spec["files"]) * 2  # relevant_files + workspace_files
    assert mock_run.call_count == expected_calls

    # Verify files on disk
    for file_path in spec["files"]:
        for subdir in ("relevant_files", "workspace_files"):
            dest = corpus_root / "tickets" / "r-trivial-heading-parser" / subdir / file_path
            assert dest.exists(), f"Expected file missing: {dest}"
            assert dest.read_text() == fake_content


# ---------------------------------------------------------------------------
# Test 3: idempotency - running twice produces the same result
# ---------------------------------------------------------------------------

def test_build_is_idempotent(tmp_path: Path) -> None:
    """Running build twice overwrites files but does not raise or duplicate."""
    corpus_root = tmp_path / "corpora" / "replay"
    call_count = 0

    def fake_run(cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        m = MagicMock()
        m.returncode = 0
        m.stdout = f"content-v{call_count}\n"
        return m

    with patch(
        "evals.icl_vs_orchestration.scripts.build_replay_corpus.subprocess.run",
        side_effect=fake_run,
    ):
        build(corpus_root, dry_run=False, ticket_filter="r-brief-tier-dimension-signal")
        first_content = (
            corpus_root
            / "tickets"
            / "r-brief-tier-dimension-signal"
            / "relevant_files"
            / "evals/auto/loop.py"
        ).read_text()

        build(corpus_root, dry_run=False, ticket_filter="r-brief-tier-dimension-signal")
        second_content = (
            corpus_root
            / "tickets"
            / "r-brief-tier-dimension-signal"
            / "relevant_files"
            / "evals/auto/loop.py"
        ).read_text()

    # Second run overwrites cleanly
    assert first_content != second_content  # content changed (call_count incremented)
    assert second_content.startswith("content-v")


# ---------------------------------------------------------------------------
# Test 4: git failure raises RuntimeError with helpful message
# ---------------------------------------------------------------------------

def test_git_failure_raises_runtime_error(tmp_path: Path) -> None:
    """write_file_from_git raises RuntimeError when git exits non-zero."""
    bad_result = MagicMock()
    bad_result.returncode = 128
    bad_result.stderr = "fatal: path 'no/such/file' does not exist in 'deadbeef'"

    with patch(
        "evals.icl_vs_orchestration.scripts.build_replay_corpus.subprocess.run",
        return_value=bad_result,
    ):
        dest = tmp_path / "out.py"
        with pytest.raises(RuntimeError, match="git show.*failed"):
            write_file_from_git("deadbeef", "no/such/file", dest)

    # File must not have been created
    assert not dest.exists()
