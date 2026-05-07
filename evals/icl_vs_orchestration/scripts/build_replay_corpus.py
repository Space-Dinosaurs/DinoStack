#!/usr/bin/env python3
"""
Purpose: CLI tool that populates the replay corpus by extracting historical
         file snapshots from git at the pre-merge SHA for each ticket. Writes
         both relevant_files/ (read-only context) and workspace_files/ (editable
         starting state) under corpora/replay/tickets/<slug>/.

Public API:
  build(corpus_root: Path, dry_run: bool, ticket_filter: str | None) -> None
  write_file_from_git(sha: str, path: str, dest: Path) -> None
  main() -> int

Upstream deps: subprocess (git show), pathlib, argparse; stdlib only.

Downstream consumers: invoked directly via
  python3 -m evals.icl_vs_orchestration.scripts.build_replay_corpus
  No direct code consumers. This is a one-shot build tool; its OUTPUT
  (corpora/replay/tickets/<slug>/relevant_files/ and workspace_files/) is
  consumed at eval-runtime by the corpus loader (corpus.py), not by importing
  this module.

Failure modes: raises RuntimeError when git show fails (bad SHA or path).
               Caller sees the error message and the offending git command.
               Dry-run mode makes zero filesystem writes; safe to call anywhere.

Performance: one git-show subprocess per (file x subdir) pair. Typically
             <1 s per file on local repos; bounded by git object resolution.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Corpus definition
# ---------------------------------------------------------------------------

TICKETS: dict[str, dict] = {
    "r-trivial-heading-parser": {
        "pre_merge_sha": "7eec21ab84a4eba381b7a28a6e51f8dfb064eb46",
        "files": [
            "evals/auto/apply.py",
            "evals/auto/loop.py",
            "evals/auto/tests/test_apply.py",
        ],
    },
    "r-single-elev-isolator-auth": {
        "pre_merge_sha": "61eb71591e098faba88166dc8bc5df5268b00004",
        "files": [
            "evals/runner/isolator.py",
        ],
    },
    "r-brief-tier-whole-file": {
        "pre_merge_sha": "156d62af75df72fb0f037ba95cbedbd722573998",
        "files": [
            "evals/auto/apply.py",
            "evals/auto/loop.py",
            "evals/auto/program.md",
            "evals/auto/components.yaml",
            "evals/auto/tests/test_apply.py",
        ],
    },
    "r-brief-tier-dimension-signal": {
        "pre_merge_sha": "2d4c4053562789e0ee5dbfc7147574229322e46b",
        "files": [
            "evals/auto/loop.py",
        ],
    },
    "r-plan-tier-agentic-disable": {
        "pre_merge_sha": "4412c4ffeaf54295e8e9de689a1f975de253f98b",
        "files": [],  # all new files in this ticket; nothing to seed
    },
}

# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def write_file_from_git(sha: str, path: str, dest: Path) -> None:
    """Extract a single file at <sha> from git and write it to <dest>.

    Args:
        sha: The git commit SHA to read from.
        path: Repo-relative path to the file.
        dest: Destination on disk; parent directories are created automatically.

    Raises:
        RuntimeError: When git show exits non-zero (missing file or bad SHA).
    """
    result = subprocess.run(
        ["git", "show", f"{sha}:{path}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git show {sha}:{path} failed: {result.stderr.strip()}"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(result.stdout)


def build(
    corpus_root: Path,
    dry_run: bool = False,
    ticket_filter: str | None = None,
) -> None:
    """Populate relevant_files/ and workspace_files/ for all tickets.

    Args:
        corpus_root: Path to corpora/replay/.
        dry_run: When True, print intended writes but make no filesystem changes.
        ticket_filter: When set, restrict to the named ticket slug only.
    """
    for slug, spec in TICKETS.items():
        if ticket_filter and slug != ticket_filter:
            continue

        sha = spec["pre_merge_sha"]
        files: list[str] = spec["files"]

        if not files:
            if dry_run:
                print(f"DRY: {slug} - no files to seed (new-file-only ticket)")
            else:
                print(f"{slug}: no files to seed (new-file-only ticket)")
            continue

        for file_path in files:
            for subdir in ("relevant_files", "workspace_files"):
                dest = corpus_root / "tickets" / slug / subdir / file_path
                if dry_run:
                    print(f"DRY: would write {dest}")
                else:
                    write_file_from_git(sha, file_path, dest)
                    print(f"wrote {dest}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Parse args and run build. Returns exit code."""
    parser = argparse.ArgumentParser(
        description=(
            "Populate the replay corpus by extracting file snapshots from git. "
            "Run from the repo root: "
            "python3 -m evals.icl_vs_orchestration.scripts.build_replay_corpus"
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without making changes.",
    )
    parser.add_argument(
        "--ticket",
        type=str,
        default=None,
        metavar="SLUG",
        help="Restrict build to a single ticket slug.",
    )
    args = parser.parse_args()

    corpus_root = Path(__file__).resolve().parents[1] / "corpora" / "replay"
    build(corpus_root, dry_run=args.dry_run, ticket_filter=args.ticket)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
