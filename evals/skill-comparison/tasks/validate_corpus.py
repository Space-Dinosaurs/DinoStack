"""
Purpose: Validate corpus.yaml structural integrity and task directory completeness.
         Run at CI time (and before any eval run) to catch missing files, malformed
         YAML, or task directories that don't match the corpus entry list.

Public API: main() -> None  (exits non-zero on any failure)
            validate_corpus(corpus_path: Path, tasks_root: Path) -> list[str]

Upstream deps: stdlib pathlib, sys; pyyaml for YAML parsing.

Downstream consumers: CI / pre-run check; called by runner.py before seeding.

Failure modes: Prints each violation to stderr; returns non-empty list on failure.
               Exits 1 if any violations found. Exit 0 means corpus is structurally
               sound (does not verify SHA correctness - that requires network).

Performance: O(n tasks); <1s for a 15-task corpus.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("pyyaml is required: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

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

_CORPUS_PATH = Path(__file__).parent / "corpus.yaml"
_TASKS_ROOT = Path(__file__).parent


def validate_corpus(corpus_path: Path, tasks_root: Path) -> list[str]:
    """Return a list of violation strings; empty means corpus is valid."""
    violations: list[str] = []

    # 1. Parse YAML.
    try:
        with corpus_path.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return [f"corpus.yaml YAML parse error: {e}"]
    except OSError as e:
        return [f"corpus.yaml not readable: {e}"]

    if not isinstance(data, dict):
        return ["corpus.yaml top-level must be a mapping"]

    # 2. Check freeze_metadata block.
    fm = data.get("freeze_metadata")
    if not isinstance(fm, dict):
        violations.append("corpus.yaml: missing or malformed 'freeze_metadata' block")
    else:
        for required in ("freeze_date", "swebench_dataset", "dataset_split",
                          "dataset_commit_hash", "selected_count"):
            if required not in fm:
                violations.append(f"corpus.yaml freeze_metadata: missing '{required}'")

    # 3. Check tasks block.
    tasks = data.get("tasks")
    if not isinstance(tasks, dict) or not tasks:
        violations.append("corpus.yaml: 'tasks' block is missing or empty")
        return violations

    # 4. Count difficulty distribution.
    difficulty_counts: dict[str, int] = {}

    for slug, entry in tasks.items():
        prefix = f"task '{slug}'"

        # Check required fields.
        if not isinstance(entry, dict):
            violations.append(f"{prefix}: entry is not a mapping")
            continue
        for field in _REQUIRED_TASK_FIELDS:
            if field not in entry:
                violations.append(f"{prefix}: missing required field '{field}'")

        # Validate difficulty.
        diff = entry.get("difficulty")
        if diff not in _VALID_DIFFICULTIES:
            violations.append(
                f"{prefix}: invalid difficulty '{diff}'; "
                f"must be one of {sorted(_VALID_DIFFICULTIES)}"
            )
        else:
            difficulty_counts[diff] = difficulty_counts.get(diff, 0) + 1

        # Validate estimated_test_seconds < 120.
        est = entry.get("estimated_test_seconds")
        if isinstance(est, (int, float)) and est >= 120:
            violations.append(
                f"{prefix}: estimated_test_seconds={est} exceeds 120 s budget"
            )

        # Validate held_out_tests is a non-empty list.
        hot = entry.get("held_out_tests")
        if not isinstance(hot, list) or not hot:
            violations.append(f"{prefix}: 'held_out_tests' must be a non-empty list")

        # Check task directory exists.
        task_dir = tasks_root / slug
        if not task_dir.is_dir():
            violations.append(f"{prefix}: task directory '{task_dir}' not found")
            continue

        # Check problem.md exists.
        problem_md = task_dir / "problem.md"
        if not problem_md.is_file():
            violations.append(f"{prefix}: missing problem.md at '{problem_md}'")

        # Check held_out_tests directory exists.
        hot_dir = task_dir / "held_out_tests"
        if not hot_dir.is_dir():
            violations.append(
                f"{prefix}: missing held_out_tests/ directory at '{hot_dir}'"
            )

    # 5. Check overall count.
    total = len(tasks)
    if not (10 <= total <= 15):
        violations.append(
            f"corpus.yaml: {total} tasks found; expected 10-15 per brief constraint"
        )

    # 6. Check difficulty mix (loose; just warn if far off).
    sf = difficulty_counts.get("single-file", 0)
    mf = difficulty_counts.get("multi-file", 0)
    dy = difficulty_counts.get("design-y", 0)
    if sf / max(total, 1) < 0.5:
        violations.append(
            f"corpus.yaml: single-file difficulty ratio {sf}/{total} is below "
            f"50% (brief target: ~60%)"
        )
    if mf / max(total, 1) < 0.2:
        violations.append(
            f"corpus.yaml: multi-file difficulty ratio {mf}/{total} is below "
            f"20% (brief target: ~30%)"
        )
    if dy < 1:
        violations.append(
            "corpus.yaml: no design-y tasks found (brief target: >=1)"
        )

    return violations


def main() -> None:
    violations = validate_corpus(_CORPUS_PATH, _TASKS_ROOT)
    if violations:
        print("corpus validation FAILED:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        sys.exit(1)
    print(f"corpus.yaml OK ({_CORPUS_PATH})")


if __name__ == "__main__":
    main()
