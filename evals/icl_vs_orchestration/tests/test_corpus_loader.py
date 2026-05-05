"""Tests for corpus loader - covers QA scenario 5 (missing required metadata)
and baseline SHA reading."""
import json
from pathlib import Path

import pytest
import yaml

from evals.icl_vs_orchestration.corpus import (
    corpus_sha,
    load_baseline_sha,
    load_corpus,
)


def _write_corpus(tmp_path: Path, tickets: list[dict], manifest_extra: dict = None) -> Path:
    """Create a minimal corpus directory structure."""
    corpus_dir = tmp_path / "test_corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    tickets_dir = corpus_dir / "tickets"
    tickets_dir.mkdir()

    manifest = {
        "corpus_name": "test",
        "ticket_classes": ["trivial"],
        "tickets": [t["ticket_id"] for t in tickets],
    }
    if manifest_extra:
        manifest.update(manifest_extra)

    (corpus_dir / "manifest.yaml").write_text(yaml.dump(manifest))

    for ticket in tickets:
        ticket_dir = tickets_dir / ticket["ticket_id"]
        ticket_dir.mkdir()
        (ticket_dir / "ticket.yaml").write_text(yaml.dump(ticket))
        (ticket_dir / "relevant_files").mkdir()

    return corpus_dir


def _valid_ticket(ticket_id: str = "t1") -> dict:
    return {
        "ticket_id": ticket_id,
        "ticket_class": "trivial",
        "description": "A test ticket.",
    }


def test_load_corpus_valid(tmp_path):
    """load_corpus returns manifest and list of ticket dicts."""
    corpus_dir = _write_corpus(tmp_path, [_valid_ticket("t1"), _valid_ticket("t2")])
    manifest, tickets = load_corpus(corpus_dir)
    assert manifest["corpus_name"] == "test"
    assert len(tickets) == 2
    assert tickets[0]["ticket_id"] == "t1"
    assert tickets[1]["ticket_id"] == "t2"


def test_load_corpus_missing_manifest(tmp_path):
    """load_corpus raises FileNotFoundError when manifest is absent."""
    corpus_dir = tmp_path / "no_manifest"
    corpus_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="manifest"):
        load_corpus(corpus_dir)


def test_load_corpus_ticket_missing_required_field(tmp_path):
    """load_corpus raises ValueError when ticket is missing required fields."""
    bad_ticket = {"ticket_id": "t1", "description": "missing ticket_class"}
    corpus_dir = _write_corpus(tmp_path, [bad_ticket])
    with pytest.raises(ValueError, match="ticket_class"):
        load_corpus(corpus_dir)


def test_load_corpus_ticket_invalid_class(tmp_path):
    """load_corpus raises ValueError for unknown ticket_class."""
    bad_ticket = _valid_ticket("t1")
    bad_ticket["ticket_class"] = "unknown-class"
    corpus_dir = _write_corpus(tmp_path, [bad_ticket])
    with pytest.raises(ValueError, match="unknown-class"):
        load_corpus(corpus_dir)


def test_load_corpus_missing_ticket_dir(tmp_path):
    """load_corpus raises FileNotFoundError when a ticket directory is absent."""
    corpus_dir = tmp_path / "c"
    corpus_dir.mkdir()
    (corpus_dir / "manifest.yaml").write_text(yaml.dump({
        "corpus_name": "test",
        "ticket_classes": ["trivial"],
        "tickets": ["t-missing"],
    }))
    (corpus_dir / "tickets").mkdir()
    # No t-missing/ directory
    with pytest.raises(FileNotFoundError, match="t-missing"):
        load_corpus(corpus_dir)


def test_corpus_sha_changes_with_content(tmp_path):
    """corpus_sha changes when manifest content changes."""
    corpus_dir1 = _write_corpus(tmp_path / "c1", [_valid_ticket("t1")])
    corpus_dir2 = _write_corpus(tmp_path / "c2", [_valid_ticket("t2")])
    sha1 = corpus_sha(corpus_dir1)
    sha2 = corpus_sha(corpus_dir2)
    assert sha1 != sha2


def test_corpus_sha_stable(tmp_path):
    """corpus_sha is stable across multiple calls on the same corpus."""
    corpus_dir = _write_corpus(tmp_path, [_valid_ticket("t1")])
    sha1 = corpus_sha(corpus_dir)
    sha2 = corpus_sha(corpus_dir)
    assert sha1 == sha2


def test_load_baseline_sha_reads_correct_field(tmp_path):
    """load_baseline_sha reads git.agentic_engineering_sha from baseline JSON."""
    baseline = {
        "schema_version": 1,
        "git": {
            "agentic_engineering_sha": "abc123def456abc123def456abc123def456abcd",
        },
    }
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline))
    sha = load_baseline_sha(baseline_path)
    assert sha == "abc123def456abc123def456abc123def456abcd"


def test_load_baseline_sha_missing_field_raises(tmp_path):
    """load_baseline_sha raises ValueError when git.agentic_engineering_sha is absent."""
    baseline = {"schema_version": 1, "git": {}}
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline))
    with pytest.raises(ValueError, match="agentic_engineering_sha"):
        load_baseline_sha(baseline_path)


def test_load_baseline_sha_real_stage0_file():
    """load_baseline_sha reads the actual Stage-0 baseline and returns a valid SHA."""
    baseline_path = Path("evals/baselines/2026-05-pre-icl-restructure.json")
    if not baseline_path.exists():
        pytest.skip("Stage-0 baseline not found; run evals-baseline-capture first.")
    sha = load_baseline_sha(baseline_path)
    assert len(sha) == 40, f"Expected 40-char SHA, got: {sha!r}"
    assert sha == "35b34631147fff05fe264f69dc5aa01a08faaa08"
