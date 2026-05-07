"""Tests for workspace_files/ copy logic in both condition adapters.

Covers:
  - AEOrchestratedSingleShot.prepare()
  - ICLBaseline.prepare()

Both adapters must copy workspace_files/ into the workspace root, skip
.gitkeep files, preserve subtree structure, and silently no-op when the
workspace_files/ directory is absent.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ae_adapter(tmp_path: Path):
    """Return an AEOrchestratedSingleShot instance with a minimal ae_spec."""
    spec_path = tmp_path / "ae_spec.yaml"
    spec_path.write_text(
        yaml.dump(
            {
                "spec_version": "1",
                "content_sha": "abc123",
                "execution_mode": "single-shot",
                "model": "claude-sonnet",
            }
        )
    )
    from evals.icl_vs_orchestration.conditions.ae_orchestrated.single_shot import (
        AEOrchestratedSingleShot,
    )
    return AEOrchestratedSingleShot(spec_path)


@pytest.fixture()
def icl_adapter(tmp_path: Path):
    """Return an ICLBaseline instance with a minimal icl_spec."""
    spec_path = tmp_path / "icl_spec.yaml"
    spec_path.write_text(
        yaml.dump(
            {
                "spec_version": "1",
                "file_selection_rule": "all",
                "context_budget_tokens": 8000,
                "prompt_template_path": "prompts/icl.md",
                "model": "claude-sonnet",
                "max_turns": 1,
                "allowed_tools": [],
            }
        )
    )
    from evals.icl_vs_orchestration.conditions.icl_baseline import ICLBaseline
    return ICLBaseline(spec_path)


def _make_ticket(ticket_dir: Path | None, ticket_yaml: dict | None = None) -> dict:
    """Build a minimal ticket dict."""
    return {
        "ticket_id": "test-ticket",
        "ticket_dir": str(ticket_dir) if ticket_dir else None,
        "ticket_yaml": ticket_yaml or {"ticket_id": "test-ticket", "ticket_class": "trivial", "description": "test"},
    }


# ---------------------------------------------------------------------------
# AEOrchestratedSingleShot tests
# ---------------------------------------------------------------------------

class TestAEAdapterPrepareWorkspaceFiles:

    def test_workspace_files_copied_to_workspace(self, ae_adapter, tmp_path: Path) -> None:
        """Files in workspace_files/ are copied into the workspace root."""
        ticket_dir = tmp_path / "ticket"
        ws_files = ticket_dir / "workspace_files"
        ws_files.mkdir(parents=True)
        (ws_files / "src" / "foo.py").parent.mkdir(parents=True)
        (ws_files / "src" / "foo.py").write_text("# foo\n")

        workspace = tmp_path / "workspace"
        ae_adapter.prepare(_make_ticket(ticket_dir), workspace)

        dest = workspace / "src" / "foo.py"
        assert dest.exists(), "File not copied to workspace"
        assert dest.read_text() == "# foo\n"

    def test_workspace_files_absent_is_noop(self, ae_adapter, tmp_path: Path) -> None:
        """Missing workspace_files/ dir does not raise."""
        ticket_dir = tmp_path / "ticket"
        ticket_dir.mkdir()  # no workspace_files/ subdir

        workspace = tmp_path / "workspace"
        ae_adapter.prepare(_make_ticket(ticket_dir), workspace)  # must not raise

        assert workspace.exists()

    def test_gitkeep_files_skipped(self, ae_adapter, tmp_path: Path) -> None:
        """.gitkeep files in workspace_files/ are not copied."""
        ticket_dir = tmp_path / "ticket"
        ws_files = ticket_dir / "workspace_files"
        ws_files.mkdir(parents=True)
        (ws_files / ".gitkeep").write_text("")
        (ws_files / "real.py").write_text("# real\n")

        workspace = tmp_path / "workspace"
        ae_adapter.prepare(_make_ticket(ticket_dir), workspace)

        assert not (workspace / ".gitkeep").exists(), ".gitkeep must not be copied"
        assert (workspace / "real.py").exists(), "real.py must be copied"

    def test_subtree_structure_preserved(self, ae_adapter, tmp_path: Path) -> None:
        """Nested subdirectory structure under workspace_files/ is mirrored."""
        ticket_dir = tmp_path / "ticket"
        ws_files = ticket_dir / "workspace_files"
        (ws_files / "a" / "b" / "c").mkdir(parents=True)
        (ws_files / "a" / "b" / "c" / "deep.txt").write_text("deep\n")

        workspace = tmp_path / "workspace"
        ae_adapter.prepare(_make_ticket(ticket_dir), workspace)

        assert (workspace / "a" / "b" / "c" / "deep.txt").read_text() == "deep\n"


# ---------------------------------------------------------------------------
# ICLBaseline tests
# ---------------------------------------------------------------------------

class TestICLAdapterPrepareWorkspaceFiles:

    def test_workspace_files_copied_to_workspace(self, icl_adapter, tmp_path: Path) -> None:
        """ICL adapter: files in workspace_files/ are copied into workspace."""
        ticket_dir = tmp_path / "ticket"
        ws_files = ticket_dir / "workspace_files"
        ws_files.mkdir(parents=True)
        (ws_files / "module.py").write_text("# module\n")

        workspace = tmp_path / "workspace"
        icl_adapter.prepare(_make_ticket(ticket_dir), workspace)

        assert (workspace / "module.py").read_text() == "# module\n"

    def test_workspace_files_absent_is_noop(self, icl_adapter, tmp_path: Path) -> None:
        """ICL adapter: missing workspace_files/ dir does not raise."""
        ticket_dir = tmp_path / "ticket"
        ticket_dir.mkdir()

        workspace = tmp_path / "workspace"
        icl_adapter.prepare(_make_ticket(ticket_dir), workspace)

        assert workspace.exists()
