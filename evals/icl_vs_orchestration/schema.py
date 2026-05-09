"""
Purpose: Validate and parse on-disk manifest/ticket/ae-spec/icl-spec YAML
         files, raising ValueError with a human-readable message on schema
         violations.

Public API:
  validate_corpus_manifest(data: dict) -> None
  validate_ticket(data: dict, ticket_id: str) -> None
  validate_ae_spec(data: dict) -> None
  validate_icl_spec(data: dict) -> None
  REQUIRED_TICKET_FIELDS: frozenset[str]
  REQUIRED_MANIFEST_FIELDS: frozenset[str]

Internal helpers:
  _validate_optional_test_fields(ticket: dict, ticket_id: str) -> None
    (called only from validate_ticket; not part of the public surface)

Upstream deps: stdlib only (re).

Downstream consumers: corpus.py, conditions/ae_orchestrated/single_shot.py,
                      conditions/icl_spec.py.

Failure modes: raises ValueError with a descriptive message on any schema
               violation. Never raises on valid input.

Performance: standard; dict field-presence checks and regex matching only.
"""
from __future__ import annotations

import re

_SHELL_METACHAR_RE = re.compile(r"[|&;<>$`\\!(){}*?~]")
_BRACKET_RE = re.compile(r"[\[\]]")

REQUIRED_MANIFEST_FIELDS = frozenset(
    ["corpus_name", "ticket_classes", "tickets"]
)

REQUIRED_TICKET_FIELDS = frozenset(
    ["ticket_id", "ticket_class", "description"]
)

VALID_TICKET_CLASSES = frozenset(
    ["trivial", "single-elev", "brief-tier", "plan-tier"]
)

VALID_AE_EXECUTION_MODES = frozenset(
    ["single-shot", "sdk-multiturn", "python-conductor-sim"]
)

VALID_CONDITION_IDS = frozenset(["ae-orchestrated", "icl-baseline"])


def _validate_optional_test_fields(ticket: dict, ticket_id: str) -> None:
    """Validate optional test_command / test_pythonpath / test_timeout_seconds fields."""
    if "test_command" in ticket and ticket["test_command"] is not None:
        val = ticket["test_command"]
        if not isinstance(val, str) or not val:
            raise ValueError(
                f"Ticket '{ticket_id}' test_command must be a non-empty string."
            )
        if _SHELL_METACHAR_RE.search(val):
            raise ValueError(
                f"Ticket '{ticket_id}' test_command contains a shell metacharacter "
                f"which is not allowed."
            )
        if _BRACKET_RE.search(val):
            raise ValueError(
                f"Ticket '{ticket_id}' test_command contains '[' or ']' which are "
                f"not supported in v1 (parametrize selectors not supported; use "
                f"file-level pytest paths only, e.g. "
                f"'evals/auto/tests/test_apply.py -x -q')."
            )

    if "test_pythonpath" in ticket and ticket["test_pythonpath"] is not None:
        val = ticket["test_pythonpath"]
        if not isinstance(val, str):
            raise ValueError(
                f"Ticket '{ticket_id}' test_pythonpath must be a string."
            )
        if val.startswith("/"):
            raise ValueError(
                f"Ticket '{ticket_id}' test_pythonpath must not be an absolute path."
            )

    if "test_timeout_seconds" in ticket and ticket["test_timeout_seconds"] is not None:
        val = ticket["test_timeout_seconds"]
        if isinstance(val, bool) or not isinstance(val, int):
            raise ValueError(
                f"Ticket '{ticket_id}' test_timeout_seconds must be an integer."
            )
        if not (5 <= val <= 120):
            raise ValueError(
                f"Ticket '{ticket_id}' test_timeout_seconds must be in range [5, 120]."
            )


def validate_corpus_manifest(data: dict) -> None:
    """Raise ValueError if the corpus manifest is missing required fields."""
    missing = REQUIRED_MANIFEST_FIELDS - set(data.keys())
    if missing:
        raise ValueError(
            f"Corpus manifest missing required fields: {sorted(missing)}"
        )
    if not isinstance(data.get("tickets"), list):
        raise ValueError(
            "Corpus manifest 'tickets' must be a list of ticket_id strings."
        )


def validate_ticket(data: dict, ticket_id: str) -> None:
    """Raise ValueError if a ticket YAML is missing required metadata."""
    missing = REQUIRED_TICKET_FIELDS - set(data.keys())
    if missing:
        raise ValueError(
            f"Ticket '{ticket_id}' missing required fields: {sorted(missing)}"
        )
    cls = data.get("ticket_class", "")
    if cls not in VALID_TICKET_CLASSES:
        raise ValueError(
            f"Ticket '{ticket_id}' has unknown ticket_class '{cls}'. "
            f"Valid values: {sorted(VALID_TICKET_CLASSES)}"
        )
    _validate_optional_test_fields(data, ticket_id)


def validate_ae_spec(data: dict) -> None:
    """Raise ValueError if the AE-orchestrated condition spec is malformed."""
    required = {"spec_version", "content_sha", "execution_mode"}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(
            f"AE-orchestrated spec missing required fields: {sorted(missing)}"
        )
    mode = data.get("execution_mode", "")
    if mode not in VALID_AE_EXECUTION_MODES:
        raise ValueError(
            f"AE spec has unknown execution_mode '{mode}'. "
            f"Valid values: {sorted(VALID_AE_EXECUTION_MODES)}"
        )
    if mode == "sdk-multiturn" and "max_turns" not in data:
        raise ValueError(
            "AE spec with execution_mode='sdk-multiturn' must include max_turns."
        )
    if mode == "python-conductor-sim" and "phase_router_path" not in data:
        raise ValueError(
            "AE spec with execution_mode='python-conductor-sim' must include "
            "phase_router_path."
        )


def validate_icl_spec(data: dict) -> None:
    """Raise ValueError if the ICL-baseline condition spec is malformed."""
    required = {
        "spec_version",
        "file_selection_rule",
        "context_budget_tokens",
        "prompt_template_path",
        "model",
        "max_turns",
        "allowed_tools",
    }
    missing = required - set(data.keys())
    if missing:
        raise ValueError(
            f"ICL baseline spec missing required fields: {sorted(missing)}"
        )
    if not isinstance(data.get("context_budget_tokens"), int):
        raise ValueError(
            "ICL spec 'context_budget_tokens' must be an integer."
        )
    if not isinstance(data.get("allowed_tools"), list):
        raise ValueError("ICL spec 'allowed_tools' must be a list of strings.")
