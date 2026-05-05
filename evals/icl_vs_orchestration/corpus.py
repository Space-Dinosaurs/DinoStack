"""
Purpose: Load and validate an icl-vs-orchestration corpus directory,
         producing TicketInput records and a corpus_sha for report pinning.

Public API:
  load_corpus(corpus_dir: Path) -> tuple[dict, list[TicketInput]]
    Returns (manifest, tickets) where tickets is a list of TicketInput dicts.
  corpus_sha(manifest_path: Path) -> str
    Returns sha256 hex of the corpus manifest for report pinning.

Upstream deps: schema.py (validate_corpus_manifest, validate_ticket);
               pyyaml; stdlib hashlib/pathlib.

Downstream consumers: runner.py, cli.py.

Failure modes: raises FileNotFoundError when corpus_dir or required
               subdirectories are absent. Raises ValueError (via schema.py)
               on malformed manifest or ticket YAML.

Performance: standard; O(tickets * file-reads).
"""
from __future__ import annotations

import hashlib
import json
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
