"""
Tests for corpus.yaml structural integrity.

These tests run against the committed corpus.yaml and task directory
tree without requiring network access.  They verify:
  - YAML parses cleanly.
  - All required fields are present on every task entry.
  - Task slug directories exist with problem.md and held_out_tests/.
  - Difficulty distribution satisfies the brief (60/30/10 target).
  - Per-task estimated_test_seconds is within the <120 s budget.
  - Task count is 10-15.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_TASKS_ROOT = Path(__file__).parent.parent / "tasks"
_CORPUS_PATH = _TASKS_ROOT / "corpus.yaml"

_REQUIRED_TASK_FIELDS = {
    "swebench_instance_id",
    "repo_url",
    "base_commit",
    "fix_commit",
    "held_out_tests",
    "estimated_test_seconds",
    "difficulty",
    "known_affected_files",
    "problem_summary",
}

_VALID_DIFFICULTIES = {"single-file", "multi-file", "design-y"}


@pytest.fixture(scope="module")
def corpus() -> dict:
    with _CORPUS_PATH.open() as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def tasks(corpus) -> dict:
    return corpus["tasks"]


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


def test_corpus_yaml_parses(corpus):
    assert isinstance(corpus, dict), "corpus.yaml top-level must be a mapping"


def test_freeze_metadata_present(corpus):
    fm = corpus.get("freeze_metadata")
    assert isinstance(fm, dict), "freeze_metadata block missing or not a mapping"
    for field in ("freeze_date", "swebench_dataset", "dataset_split",
                  "dataset_commit_hash", "selected_count"):
        assert field in fm, f"freeze_metadata missing '{field}'"


def test_tasks_block_present(corpus):
    assert "tasks" in corpus, "corpus.yaml missing 'tasks' block"
    assert isinstance(corpus["tasks"], dict), "'tasks' must be a mapping"
    assert len(corpus["tasks"]) > 0, "'tasks' is empty"


def test_task_count_in_range(tasks):
    n = len(tasks)
    assert 10 <= n <= 15, f"Expected 10-15 tasks, got {n}"


@pytest.mark.parametrize("slug", list(yaml.safe_load(
    _CORPUS_PATH.read_text())["tasks"].keys()))
def test_task_required_fields(slug, tasks):
    entry = tasks[slug]
    for field in _REQUIRED_TASK_FIELDS:
        assert field in entry, f"Task '{slug}' missing field '{field}'"


@pytest.mark.parametrize("slug", list(yaml.safe_load(
    _CORPUS_PATH.read_text())["tasks"].keys()))
def test_task_difficulty_valid(slug, tasks):
    diff = tasks[slug].get("difficulty")
    assert diff in _VALID_DIFFICULTIES, (
        f"Task '{slug}' has invalid difficulty '{diff}'"
    )


@pytest.mark.parametrize("slug", list(yaml.safe_load(
    _CORPUS_PATH.read_text())["tasks"].keys()))
def test_task_time_budget(slug, tasks):
    est = tasks[slug].get("estimated_test_seconds", 999)
    assert est < 120, (
        f"Task '{slug}' estimated_test_seconds={est} exceeds 120 s budget"
    )


@pytest.mark.parametrize("slug", list(yaml.safe_load(
    _CORPUS_PATH.read_text())["tasks"].keys()))
def test_task_held_out_tests_nonempty(slug, tasks):
    hot = tasks[slug].get("held_out_tests", [])
    assert isinstance(hot, list) and len(hot) > 0, (
        f"Task '{slug}' held_out_tests must be a non-empty list"
    )


# ---------------------------------------------------------------------------
# Directory / file presence tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slug", list(yaml.safe_load(
    _CORPUS_PATH.read_text())["tasks"].keys()))
def test_task_directory_exists(slug):
    task_dir = _TASKS_ROOT / slug
    assert task_dir.is_dir(), f"Task directory not found: {task_dir}"


@pytest.mark.parametrize("slug", list(yaml.safe_load(
    _CORPUS_PATH.read_text())["tasks"].keys()))
def test_task_problem_md_exists(slug):
    problem_md = _TASKS_ROOT / slug / "problem.md"
    assert problem_md.is_file(), f"Missing problem.md: {problem_md}"


@pytest.mark.parametrize("slug", list(yaml.safe_load(
    _CORPUS_PATH.read_text())["tasks"].keys()))
def test_task_held_out_tests_dir_exists(slug):
    hot_dir = _TASKS_ROOT / slug / "held_out_tests"
    assert hot_dir.is_dir(), f"Missing held_out_tests/ dir: {hot_dir}"


# ---------------------------------------------------------------------------
# Difficulty distribution tests
# ---------------------------------------------------------------------------


def test_difficulty_distribution(tasks):
    counts: dict[str, int] = {}
    for entry in tasks.values():
        d = entry.get("difficulty", "unknown")
        counts[d] = counts.get(d, 0) + 1
    total = len(tasks)
    sf = counts.get("single-file", 0)
    mf = counts.get("multi-file", 0)
    dy = counts.get("design-y", 0)
    # Brief: 60% single-file, 30% multi-file, 10% design-y (loose check)
    assert sf / total >= 0.5, (
        f"single-file ratio {sf}/{total}={sf/total:.0%} is below 50% target"
    )
    assert mf / total >= 0.2, (
        f"multi-file ratio {mf}/{total}={mf/total:.0%} is below 20% target"
    )
    assert dy >= 1, "No design-y tasks found; at least 1 required"
