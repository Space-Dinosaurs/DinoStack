"""
Purpose: Protocol and TypedDict definitions shared by all condition runners.
         Both AE-orchestrated and ICL-baseline adapters implement the Condition
         Protocol and populate ConditionResult / ConditionArtifacts.

Public API:
  TicketInput (TypedDict)
  ConditionResult (TypedDict)
  ConditionArtifacts (TypedDict)
  Condition (Protocol)
  extract_rationale_or_plan(source_text: str) -> tuple[str, str]
    Returns (rationale_or_plan, extraction_method) where extraction_method is
    "structured" if a delimited rationale section was found, else "fallback-full-text".

Upstream deps: typing, pathlib.

Downstream consumers: conditions/ae_orchestrated/single_shot.py,
                      conditions/icl_baseline.py, scoring/output_coherence.py,
                      runner.py.

Failure modes: extract_rationale_or_plan never raises; falls back to
               full source text on any parse failure.

Performance: standard; regex on a text blob.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# TypedDicts (defined as plain dicts for Python 3.8+ compat without __required__)
# ---------------------------------------------------------------------------

# TicketInput keys:
#   ticket_id: str
#   ticket_yaml: dict
#   ticket_dir: Path
#   relevant_files_dir: Path
#   architect_plan_path: Path | None
#   brief_path: Path | None


# ConditionArtifacts keys (all optional except rationale_or_plan, diff):
#   rationale_or_plan: str          -- REQUIRED; both AE and ICL adapters
#   diff: str                       -- REQUIRED; mirrors result.diff
#   commit_message: str             -- OPTIONAL; AE only
#   architect_plan_path: Path       -- OPTIONAL; AE only
#   rationale_extraction_method: str -- "structured" | "fallback-full-text"


# ConditionResult keys:
#   ticket_id: str
#   condition_id: str               -- "ae-orchestrated" | "icl-baseline"
#   status: str                     -- "ok" | "timeout" | "error" | "aborted"
#   final_text: str
#   diff: str | None
#   files_touched: list[str]
#   tool_calls: list[dict]
#   tokens: dict
#   cost_usd: float
#   wall_seconds: float
#   raw_trace_path: Path
#   invocation_meta: dict
#   quality_gates: dict
#   artifacts: dict                 -- ConditionArtifacts


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Condition(Protocol):
    """Protocol that every condition adapter must satisfy."""

    condition_id: str

    def prepare(self, ticket: dict, workspace: Path) -> None:
        """Set up the workspace for one ticket run. Called once per ticket."""
        ...

    def run(
        self,
        ticket: dict,
        workspace: Path,
        cost_gate: object,
        timeout_seconds: int,
    ) -> dict:
        """Run the condition for one ticket; return ConditionResult dict."""
        ...


# ---------------------------------------------------------------------------
# Shared rationale extraction rule (v1 default, both adapters)
# ---------------------------------------------------------------------------

# Delimiter patterns that indicate a structured rationale section.
# Order matters: first match wins.
_SECTION_PATTERNS = [
    # Rationale or Reasoning section (highest priority - most specific)
    re.compile(
        r"##\s*(?:Rationale|Reasoning)\s*\n(.*?)(?=\n##\s|\Z)",
        re.IGNORECASE | re.DOTALL,
    ),
    # XML-style delimiter
    re.compile(
        r"<rationale>(.*?)</rationale>",
        re.IGNORECASE | re.DOTALL,
    ),
    # Plan or Architect Plan section (lower priority than Rationale)
    re.compile(
        r"##\s*(?:Plan|Architect Plan)\s*\n(.*?)(?=\n##\s|\Z)",
        re.IGNORECASE | re.DOTALL,
    ),
    # Triple-dashed block with a heading
    re.compile(
        r"---\s*\n(?:rationale|plan):\s*\n(.*?)(?=\n---|\Z)",
        re.IGNORECASE | re.DOTALL,
    ),
]


def extract_rationale_or_plan(source_text: str) -> tuple[str, str]:
    """Extract rationale from source_text using the v1 symmetric rule.

    Rule (binding per architect-plan-eval-harness-v1.md):
    1. Try each _SECTION_PATTERNS in order; if a match is found, return its
       body (stripped) with extraction_method="structured".
    2. If no pattern matches, return the entire source_text with
       extraction_method="fallback-full-text".

    Returns: (rationale_or_plan: str, extraction_method: str)
    """
    for pattern in _SECTION_PATTERNS:
        match = pattern.search(source_text)
        if match:
            body = match.group(1).strip()
            if body:
                return body, "structured"
    # v1 fallback: entire source text
    return source_text, "fallback-full-text"
