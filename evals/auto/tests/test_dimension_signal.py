"""Unit tests for _build_dimension_signal in evals.auto.loop."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.auto.loop import _build_dimension_signal, _NO_SIGNAL_LINE


# ---------------------------------------------------------------------------
# TSV helpers
# ---------------------------------------------------------------------------

_TSV_HEADER = [
    "commit", "component_content_hash", "fixture_hash",
    "primary_score_median", "primary_score_stdev", "n_runs",
    "status", "diagnostic_json", "description",
]


def _write_tsv(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(_TSV_HEADER) + "\n")
        for r in rows:
            fh.write("\t".join(str(r.get(c, "")) for c in _TSV_HEADER) + "\n")


def _make_row(per_run: list) -> dict:
    diag = {"n_runs": len(per_run), "per_run": per_run}
    return {
        "commit": "abc123",
        "component_content_hash": "x" * 64,
        "fixture_hash": "y" * 64,
        "primary_score_median": "0.8",
        "primary_score_stdev": "0.1",
        "n_runs": len(per_run),
        "status": "ok",
        "diagnostic_json": json.dumps(diag),
        "description": "test",
    }


def _nested_dim(score: float, vacuous: bool = False) -> dict:
    """Build a nested-dict dimension value (architect-style)."""
    d: dict = {"score": score}
    if vacuous:
        d["vacuous"] = True
    return d


# ---------------------------------------------------------------------------
# Editable file fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal repo tree with an editable file containing known dimension names."""
    results_dir = tmp_path / "evals" / "results"
    results_dir.mkdir(parents=True)
    editable_dir = tmp_path / "content" / "agents"
    editable_dir.mkdir(parents=True)
    agent_md = editable_dir / "mycomp.md"
    agent_md.write_text(
        "# mycomp\nopen_questions section\napproach_commit details\nsection_keywords here\n",
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Test 1: bottom-K extraction from fabricated TSV with known dimensions
# ---------------------------------------------------------------------------

def test_bottom_k_extraction(tmp_repo: Path) -> None:
    """Confirms worst dimensions are returned in ascending order."""
    # Three dimensions: open_questions (worst), approach_commit (mid), section_keywords (best)
    per_run = [
        {
            "diagnostic": {
                "open_questions": _nested_dim(0.1),
                "approach_commit": _nested_dim(0.5),
                "section_keywords": _nested_dim(0.9),
            },
            "primary": 0.8,
            "status": "ok",
        }
    ]
    rows = [_make_row(per_run)] * 3  # 3 fixture rows

    tsv = tmp_repo / "evals" / "results" / "mycomp.tsv"
    _write_tsv(tsv, rows)

    editable = ["content/agents/mycomp.md"]
    result = _build_dimension_signal(tmp_repo, "mycomp", 3, editable)

    assert "open_questions" in result
    assert "approach_commit" in result
    assert "section_keywords" in result
    # open_questions should appear before approach_commit (sorted ascending by avg)
    assert result.index("open_questions") < result.index("approach_commit")
    assert result.index("approach_commit") < result.index("section_keywords")
    # Confirm format
    assert "avg 0.100" in result
    assert "non-vacuous runs" in result


# ---------------------------------------------------------------------------
# Test 2: substring filter excludes dimensions not in editable file
# ---------------------------------------------------------------------------

def test_substring_filter_excludes_unknown_dims(tmp_repo: Path) -> None:
    """Dimensions whose names don't appear in editable files are excluded."""
    per_run = [
        {
            "diagnostic": {
                "open_questions": _nested_dim(0.1),   # in editable file
                "zz_unknown_dim": _nested_dim(0.0),    # NOT in editable file
            },
            "primary": 0.7,
            "status": "ok",
        }
    ]
    rows = [_make_row(per_run)] * 2

    tsv = tmp_repo / "evals" / "results" / "mycomp.tsv"
    _write_tsv(tsv, rows)

    editable = ["content/agents/mycomp.md"]
    result = _build_dimension_signal(tmp_repo, "mycomp", 2, editable)

    assert "open_questions" in result
    assert "zz_unknown_dim" not in result


# ---------------------------------------------------------------------------
# Test 3: vacuous exclusion
# ---------------------------------------------------------------------------

def test_vacuous_runs_excluded(tmp_repo: Path) -> None:
    """Vacuous=True runs are excluded from dimension averages."""
    # open_questions: 2 vacuous runs (score=0.0) + 1 non-vacuous run (score=0.8)
    # Average should be 0.8 (only counting the non-vacuous run).
    per_run = [
        {"diagnostic": {"open_questions": _nested_dim(0.0, vacuous=True)}, "primary": 0.5, "status": "ok"},
        {"diagnostic": {"open_questions": _nested_dim(0.0, vacuous=True)}, "primary": 0.5, "status": "ok"},
        {"diagnostic": {"open_questions": _nested_dim(0.8, vacuous=False)}, "primary": 0.8, "status": "ok"},
    ]
    rows = [_make_row(per_run)]

    tsv = tmp_repo / "evals" / "results" / "mycomp.tsv"
    _write_tsv(tsv, rows)

    editable = ["content/agents/mycomp.md"]
    result = _build_dimension_signal(tmp_repo, "mycomp", 1, editable)

    # avg should reflect only the 1 non-vacuous run with score 0.8
    assert "open_questions" in result
    assert "avg 0.800" in result
    assert "1 non-vacuous runs" in result


# ---------------------------------------------------------------------------
# Test 4: empty/missing TSV returns no-signal line
# ---------------------------------------------------------------------------

def test_missing_tsv_returns_no_signal(tmp_repo: Path) -> None:
    """Missing TSV returns the no-signal fallback line."""
    result = _build_dimension_signal(tmp_repo, "nonexistent_comp", 3, [])
    assert result == _NO_SIGNAL_LINE


def test_empty_tsv_returns_no_signal(tmp_repo: Path) -> None:
    """TSV with no rows returns the no-signal fallback line."""
    tsv = tmp_repo / "evals" / "results" / "mycomp.tsv"
    _write_tsv(tsv, [])  # header only

    result = _build_dimension_signal(tmp_repo, "mycomp", 1, ["content/agents/mycomp.md"])
    assert result == _NO_SIGNAL_LINE


# ---------------------------------------------------------------------------
# Test 5: flat float dimensions (conductor-style)
# ---------------------------------------------------------------------------

def test_flat_float_dimensions(tmp_repo: Path) -> None:
    """Flat float values in [0,1] are treated as dimensions."""
    per_run = [
        {
            "diagnostic": {
                "open_questions": 0.2,   # flat float, in editable file
                "cli_status": "ok",       # string - not a dimension
                "latency_ms": 12345,      # int, not in [0,1] - not a dimension
                "approach_commit": 0.7,   # flat float, in editable file
            },
            "primary": 0.7,
            "status": "ok",
        }
    ]
    rows = [_make_row(per_run)] * 2

    tsv = tmp_repo / "evals" / "results" / "mycomp.tsv"
    _write_tsv(tsv, rows)

    editable = ["content/agents/mycomp.md"]
    result = _build_dimension_signal(tmp_repo, "mycomp", 2, editable)

    assert "open_questions" in result
    assert "approach_commit" in result
    assert "cli_status" not in result
    assert "latency_ms" not in result


# ---------------------------------------------------------------------------
# Test 6: all dimensions are vacuous -> no signal
# ---------------------------------------------------------------------------

def test_all_vacuous_returns_no_signal(tmp_repo: Path) -> None:
    """When every run for every dimension is vacuous, return no-signal."""
    per_run = [
        {"diagnostic": {"open_questions": _nested_dim(0.0, vacuous=True)}, "primary": 0.5, "status": "ok"},
    ]
    rows = [_make_row(per_run)]

    tsv = tmp_repo / "evals" / "results" / "mycomp.tsv"
    _write_tsv(tsv, rows)

    editable = ["content/agents/mycomp.md"]
    result = _build_dimension_signal(tmp_repo, "mycomp", 1, editable)
    assert result == _NO_SIGNAL_LINE


# ---------------------------------------------------------------------------
# Test 7: no matching editable file -> no signal
# ---------------------------------------------------------------------------

def test_no_editable_match_returns_no_signal(tmp_repo: Path) -> None:
    """When no editable file contains any dimension name, return no-signal."""
    per_run = [
        {
            "diagnostic": {
                "zz_unknown_alpha": _nested_dim(0.1),
                "zz_unknown_beta": _nested_dim(0.2),
            },
            "primary": 0.5,
            "status": "ok",
        }
    ]
    rows = [_make_row(per_run)]

    tsv = tmp_repo / "evals" / "results" / "mycomp.tsv"
    _write_tsv(tsv, rows)

    editable = ["content/agents/mycomp.md"]
    result = _build_dimension_signal(tmp_repo, "mycomp", 1, editable)
    assert result == _NO_SIGNAL_LINE
