"""
Purpose: Validate corpus.yaml structural integrity and task directory completeness.
         Run at CI time (and before any eval run) to catch missing files, malformed
         YAML, out-of-range SHAs, duplicate instance IDs, or task directories that
         don't match the corpus entry list.

Public API: main() -> None  (exits non-zero on any failure)
            validate_corpus(corpus_path: Path, tasks_root: Path) -> list[str]

Upstream deps: stdlib pathlib, re, sys; pyyaml for YAML parsing.

Downstream consumers: CI (corpus-validation.yml); runner.py before seeding.

Failure modes: Prints each violation to stderr; returns non-empty list on failure.
               Exits 1 if any violations found. Exit 0 means corpus is structurally
               sound (does not verify SHA reachability - that requires network).

Performance: O(n tasks); <1s for a 15-task corpus.

Validation rules:
  - base_commit must match ^[0-9a-f]{40}$ (40-char lowercase hex).
  - swebench_instance_id must be unique across all tasks.
  - estimated_test_seconds must be < 120 (the >=120 boundary is rejected;
    120 itself and above are out of budget per the brief constraint).
  - fix_commit is intentionally absent from the schema; validator rejects it
    if present to prevent future confusion.
"""
from __future__ import annotations

import re
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
    "held_out_tests",
    "fail_to_pass",
    "estimated_test_seconds",
    "difficulty",
    "known_affected_files",
    "problem_summary",
}

_FORBIDDEN_TASK_FIELDS = {
    "fix_commit",  # removed in r2; test files come from test_patch at base_commit
}

_VALID_DIFFICULTIES = {"single-file", "multi-file", "design-y"}

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

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

    # 4. Count difficulty distribution; track instance_id uniqueness.
    difficulty_counts: dict[str, int] = {}
    seen_instance_ids: dict[str, str] = {}  # instance_id -> slug

    for slug, entry in tasks.items():
        prefix = f"task '{slug}'"

        # Check required fields.
        if not isinstance(entry, dict):
            violations.append(f"{prefix}: entry is not a mapping")
            continue
        for field in _REQUIRED_TASK_FIELDS:
            if field not in entry:
                violations.append(f"{prefix}: missing required field '{field}'")

        # Reject forbidden fields.
        for field in _FORBIDDEN_TASK_FIELDS:
            if field in entry:
                violations.append(
                    f"{prefix}: forbidden field '{field}' present; "
                    f"remove it (test files are extracted from test_patch at base_commit)"
                )

        # Validate base_commit is a 40-char lowercase hex SHA.
        bc = entry.get("base_commit", "")
        if not isinstance(bc, str) or not _SHA_RE.match(bc):
            violations.append(
                f"{prefix}: base_commit '{bc}' is not a 40-char lowercase hex SHA"
            )

        # Validate swebench_instance_id uniqueness.
        iid = entry.get("swebench_instance_id", "")
        if iid:
            if iid in seen_instance_ids:
                violations.append(
                    f"{prefix}: swebench_instance_id '{iid}' already used by "
                    f"task '{seen_instance_ids[iid]}'"
                )
            else:
                seen_instance_ids[iid] = slug

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
        # NOTE: the rejection boundary is >=120 (i.e. 120 itself is out-of-budget).
        est = entry.get("estimated_test_seconds")
        if isinstance(est, (int, float)) and est >= 120:
            violations.append(
                f"{prefix}: estimated_test_seconds={est} exceeds 120 s budget "
                f"(rejection boundary is >=120)"
            )

        # Validate held_out_tests is a non-empty list.
        hot = entry.get("held_out_tests")
        if not isinstance(hot, list) or not hot:
            violations.append(f"{prefix}: 'held_out_tests' must be a non-empty list")

        # Validate fail_to_pass is a non-empty list.
        ftp = entry.get("fail_to_pass")
        if not isinstance(ftp, list) or not ftp:
            violations.append(f"{prefix}: 'fail_to_pass' must be a non-empty list")

        # Check task directory exists.
        task_dir = tasks_root / slug
        if not task_dir.is_dir():
            violations.append(f"{prefix}: task directory '{task_dir}' not found")
            continue

        # Check problem.md exists.
        problem_md = task_dir / "problem.md"
        if not problem_md.is_file():
            violations.append(f"{prefix}: missing problem.md at '{problem_md}'")

        # Check test_patch.diff exists, is non-empty, and looks like a real diff.
        # Staged by seed_corpus.py from the HuggingFace SWE-bench_Lite dataset.
        test_patch = task_dir / "test_patch.diff"
        if not test_patch.is_file():
            violations.append(
                f"{prefix}: missing test_patch.diff at '{test_patch}'. "
                "Run: python evals/skill-comparison/seed_corpus.py"
            )
        elif test_patch.stat().st_size == 0:
            violations.append(
                f"{prefix}: test_patch.diff at '{test_patch}' is empty. "
                "Re-run: python evals/skill-comparison/seed_corpus.py --force"
            )
        else:
            # MINOR-1: detect truncated patches whose first line is not the
            # standard unified diff header. A patch that is non-empty but does
            # not start with 'diff --git' is likely truncated or malformed.
            try:
                first_line = test_patch.read_text(encoding="utf-8", errors="replace").splitlines()[0]
                if not first_line.startswith("diff --git"):
                    violations.append(
                        f"{prefix}: test_patch.diff at '{test_patch}' does not "
                        f"start with 'diff --git' (first line: {first_line[:80]!r}). "
                        "Patch may be truncated; re-run seed_corpus.py --force."
                    )
            except (OSError, IndexError):
                pass  # empty-file case already caught above

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
