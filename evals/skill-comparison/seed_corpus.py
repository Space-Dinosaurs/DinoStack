"""
Purpose: Fetch test_patch fields from HuggingFace SWE-bench_Lite dataset and
         write them as committed corpus files at tasks/<slug>/test_patch.diff.
         Run this script once (or when the corpus changes) to stage the patches;
         do NOT run at eval time - use the committed diffs instead.

Public API:
    seed_corpus(corpus_yaml: Path, tasks_root: Path, force: bool = False) -> dict[str, str]
        Returns a mapping of slug -> status ("written" | "exists" | "empty").

    main() -> None  (CLI entry point; exits non-zero on any fetch failure)

Upstream deps: stdlib urllib.request, urllib.error, json, pathlib, sys, time.
               pyyaml for corpus YAML parsing.
               HuggingFace Datasets REST API (public, no auth required).

Downstream consumers: CI seed job; manual corpus maintenance.

Failure modes: HTTP errors (non-200 status) and socket timeouts raise
               urllib.error.URLError / urllib.error.HTTPError. The script
               retries each batch request up to 3 times with exponential
               backoff. Individual task failures are logged to stderr; the
               script continues and exits 1 if any tasks are missing.

Performance: fetches up to 5 batches of 100 rows from HuggingFace REST API
             (max ~0.5 s per request on a good connection). Total runtime is
             typically <5 s for a 12-task corpus.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    print("pyyaml is required: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

_HF_API = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=princeton-nlp%2FSWE-bench_Lite"
    "&config=default"
    "&split=test"
    "&offset={offset}"
    "&length=100"
)

_MAX_RETRIES = 3
_RETRY_BASE_SECONDS = 2.0

_CORPUS_PATH = Path(__file__).parent / "tasks" / "corpus.yaml"
_TASKS_ROOT = Path(__file__).parent / "tasks"


def _fetch_batch(offset: int, timeout: float = 30.0) -> list[dict]:
    """Fetch one 100-row batch from HuggingFace; retry on transient errors."""
    url = _HF_API.format(offset=offset)
    for attempt in range(_MAX_RETRIES):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                data = json.load(resp)
            return data.get("rows", [])
        except (urllib.error.URLError, OSError) as exc:
            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_BASE_SECONDS * (2 ** attempt)
                print(
                    f"  Fetch offset={offset} attempt {attempt + 1} failed: {exc}. "
                    f"Retrying in {delay:.0f}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)
            else:
                raise
    return []  # unreachable


def _load_corpus(corpus_yaml: Path) -> dict[str, str]:
    """Return a mapping of slug -> swebench_instance_id from corpus.yaml."""
    with corpus_yaml.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    tasks = data.get("tasks", {})
    if not isinstance(tasks, dict):
        raise ValueError(f"corpus.yaml at {corpus_yaml} has no 'tasks' mapping")
    result: dict[str, str] = {}
    for slug, meta in tasks.items():
        iid = meta.get("swebench_instance_id", "")
        if iid:
            result[slug] = iid
    return result


def seed_corpus(
    corpus_yaml: Path,
    tasks_root: Path,
    force: bool = False,
) -> dict[str, str]:
    """Fetch test_patch for every task in corpus_yaml and write to tasks_root.

    Args:
        corpus_yaml: path to tasks/corpus.yaml.
        tasks_root: parent directory of per-task subdirectories.
        force: if True, overwrite existing test_patch.diff files.

    Returns:
        Mapping of slug -> status string:
          "written"  - patch fetched and written (or overwritten with force=True).
          "exists"   - patch already present (skipped because force=False).
          "empty"    - HuggingFace returned an empty test_patch for this instance.
    """
    slug_to_iid = _load_corpus(corpus_yaml)
    # Reverse map for lookup during iteration.
    iid_to_slug: dict[str, str] = {v: k for k, v in slug_to_iid.items()}
    target_iids: set[str] = set(iid_to_slug.keys())

    # Check which already have a non-empty test_patch.diff (skip if not force).
    already_done: set[str] = set()
    if not force:
        for slug, iid in slug_to_iid.items():
            patch_path = tasks_root / slug / "test_patch.diff"
            if patch_path.is_file() and patch_path.stat().st_size > 0:
                already_done.add(iid)

    remaining = target_iids - already_done
    patches: dict[str, str] = {}  # iid -> test_patch text

    if remaining:
        print(f"Fetching test_patches for {len(remaining)} tasks from HuggingFace...")
        for offset in range(0, 2000, 100):
            if not remaining:
                break
            print(f"  Fetching rows offset={offset}...", end=" ", flush=True)
            rows = _fetch_batch(offset)
            if not rows:
                print("(no more rows)")
                break
            found_in_batch = 0
            for row_wrapper in rows:
                row = row_wrapper.get("row", {})
                iid = row.get("instance_id", "")
                if iid in remaining:
                    patches[iid] = row.get("test_patch", "")
                    remaining.discard(iid)
                    found_in_batch += 1
            print(f"found {found_in_batch} target rows. {len(remaining)} still needed.")
    else:
        print("All test_patch.diff files already present (use --force to overwrite).")

    if remaining:
        print(
            f"WARNING: {len(remaining)} instance_ids not found in dataset: "
            f"{sorted(remaining)}",
            file=sys.stderr,
        )

    # Write patches and build status map.
    status: dict[str, str] = {}
    for slug, iid in slug_to_iid.items():
        patch_path = tasks_root / slug / "test_patch.diff"

        if iid in already_done:
            status[slug] = "exists"
            continue

        patch_text = patches.get(iid, "")
        if not patch_text:
            print(f"  WARNING: empty test_patch for {slug} ({iid})", file=sys.stderr)
            status[slug] = "empty"
            continue

        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_text(patch_text, encoding="utf-8")
        print(f"  Wrote {slug}/test_patch.diff ({len(patch_text)} chars)")
        status[slug] = "written"

    return status


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Fetch SWE-bench test_patch fields and commit them as corpus fixtures.\n"
            "Run from repo root or evals/skill-comparison/.\n"
            "Output: tasks/<slug>/test_patch.diff for every task in corpus.yaml."
        )
    )
    parser.add_argument(
        "--corpus-yaml",
        type=Path,
        default=_CORPUS_PATH,
        help="Path to tasks/corpus.yaml (default: auto-derived)",
    )
    parser.add_argument(
        "--tasks-root",
        type=Path,
        default=_TASKS_ROOT,
        help="Directory containing per-task subdirectories (default: auto-derived)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing test_patch.diff files",
    )
    args = parser.parse_args()

    try:
        status = seed_corpus(args.corpus_yaml, args.tasks_root, force=args.force)
    except Exception as exc:
        print(f"seed_corpus failed: {exc}", file=sys.stderr)
        sys.exit(1)

    written = sum(1 for s in status.values() if s == "written")
    exists = sum(1 for s in status.values() if s == "exists")
    empty = sum(1 for s in status.values() if s == "empty")
    missing = sum(1 for s in status.values() if s not in ("written", "exists", "empty"))

    print(
        f"\nDone: {written} written, {exists} already existed, "
        f"{empty} empty, {missing} missing from dataset."
    )

    if empty > 0 or missing > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
