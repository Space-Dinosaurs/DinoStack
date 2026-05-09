"""
Purpose: Load and validate an icl-vs-orchestration corpus directory,
         producing TicketInput records and a corpus_sha for report pinning.
         Also provides tolerant preflight validation of ticket test commands.

Public API:
  load_corpus(corpus_dir: Path) -> tuple[dict, list[TicketInput]]
    Returns (manifest, tickets) where tickets is a list of TicketInput dicts.
  corpus_sha(manifest_path: Path) -> str
    Returns sha256 hex of the corpus manifest for report pinning.
  preflight_test_commands(tickets, workspace_root, log) -> None
    Validates each ticket's test_command via pytest --collect-only.
    Defers tickets with unresolvable imports (warning); raises RuntimeError
    for other collection failures.

Upstream deps: schema.py (validate_corpus_manifest, validate_ticket);
               pyyaml; stdlib hashlib/pathlib/re/shlex/subprocess/logging.

Downstream consumers: runner.py, cli.py.

Failure modes: raises FileNotFoundError when corpus_dir or required
               subdirectories are absent. Raises ValueError (via schema.py)
               on malformed manifest or ticket YAML. preflight_test_commands
               raises RuntimeError when pytest --collect-only fails for a
               reason other than an unresolvable import (e.g. typo in path,
               missing file); in that case the message includes ticket_id and
               the first 500 chars of combined stdout+stderr.

Performance: standard; O(tickets * file-reads). preflight_test_commands adds
             one subprocess call per ticket that has a test_command (30s
             timeout each).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from .schema import validate_corpus_manifest, validate_ticket

if TYPE_CHECKING:
    pass


def load_corpus(corpus_dir: Path) -> tuple[dict, list[dict]]:
    """Load a corpus directory and return (manifest, [TicketInput, ...]).

    Each TicketInput dict has keys matching the ConditionResult TypedDict:
      ticket_id, ticket_yaml, ticket_dir, relevant_files_dir,
      architect_plan_path (Path|None), brief_path (Path|None).
    """
    corpus_dir = corpus_dir.resolve()
    manifest_path = corpus_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Corpus manifest not found: {manifest_path}"
        )
    with manifest_path.open() as f:
        manifest = yaml.safe_load(f)
    validate_corpus_manifest(manifest)

    tickets_dir = corpus_dir / "tickets"
    if not tickets_dir.exists():
        raise FileNotFoundError(
            f"Corpus tickets directory not found: {tickets_dir}"
        )

    ticket_inputs = []
    for ticket_id in manifest["tickets"]:
        ticket_dir = tickets_dir / ticket_id
        if not ticket_dir.exists():
            raise FileNotFoundError(
                f"Ticket directory not found: {ticket_dir}"
            )
        ticket_yaml_path = ticket_dir / "ticket.yaml"
        if not ticket_yaml_path.exists():
            raise FileNotFoundError(
                f"ticket.yaml not found for ticket '{ticket_id}': "
                f"{ticket_yaml_path}"
            )
        with ticket_yaml_path.open() as f:
            ticket_data = yaml.safe_load(f)
        validate_ticket(ticket_data, ticket_id)

        architect_plan_path = ticket_dir / "architect_plan.md"
        if not architect_plan_path.exists():
            architect_plan_path = None

        brief_path = ticket_dir / "brief.md"
        if not brief_path.exists():
            brief_path = None

        relevant_files_dir = ticket_dir / "relevant_files"
        if not relevant_files_dir.exists():
            relevant_files_dir.mkdir(parents=True)

        ticket_inputs.append(
            {
                "ticket_id": ticket_id,
                "ticket_yaml": ticket_data,
                "ticket_dir": ticket_dir,
                "relevant_files_dir": relevant_files_dir,
                "architect_plan_path": architect_plan_path,
                "brief_path": brief_path,
            }
        )

    return manifest, ticket_inputs


def corpus_sha(corpus_dir: Path) -> str:
    """Return sha256 hex of the corpus manifest YAML for report pinning."""
    manifest_path = corpus_dir / "manifest.yaml"
    data = manifest_path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def preflight_test_commands(
    tickets: list[dict],
    workspace_root: Path,
    log: logging.Logger,
) -> None:
    """Validate each ticket's test_command via pytest --collect-only.

    For each ticket with a truthy test_command:
    - returncode 0: pass, continue silently.
    - returncode != 0 AND output contains ImportError/ModuleNotFoundError:
        emit log.warning and continue (deferred; will validate at runtime).
    - returncode != 0 AND no import-error pattern: raise RuntimeError.

    Tickets without test_command (or test_command: null) are silently skipped.
    """
    for ticket in tickets:
        ticket_yaml = ticket.get("ticket_yaml") or {}
        test_command = ticket_yaml.get("test_command")
        if not test_command:
            continue

        ticket_id = ticket.get("ticket_id", "<unknown>")
        # Strip leading "pytest" token if present to avoid "pytest pytest ..."
        # duplication when test_command is a full invocation like
        # "pytest evals/auto/tests/test_apply.py -x -q".
        parts = shlex.split(test_command)
        if parts and parts[0] == "pytest":
            parts = parts[1:]
        args = [sys.executable, "-m", "pytest", "--collect-only", "-q"] + parts
        proc = subprocess.run(
            args,
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        combined = (proc.stdout or "") + (proc.stderr or "")

        if proc.returncode == 0:
            continue

        if re.search(r"ImportError|ModuleNotFoundError", combined, re.IGNORECASE):
            log.warning(
                "preflight deferred: ticket %s test import not resolvable "
                "against baseline workspace; will validate at runtime",
                ticket_id,
            )
            continue

        raise RuntimeError(
            f"preflight failed for ticket {ticket_id}: pytest --collect-only "
            f"exited {proc.returncode}; output: {combined[:500]}"
        )


def load_baseline_sha(baseline_path: Path) -> str:
    """Read and return git.agentic_engineering_sha from the Stage-0 artifact.

    This is the content_sha pinned into the AE-orchestrated condition spec
    so Stage 3 and Stage 6 run against a recorded protocol SHA.
    """
    with baseline_path.open() as f:
        data = json.load(f)
    sha = data.get("git", {}).get("agentic_engineering_sha")
    if not sha:
        raise ValueError(
            f"Stage-0 baseline at {baseline_path} is missing "
            "'git.agentic_engineering_sha'. Re-run evals-baseline-capture."
        )
    return sha
