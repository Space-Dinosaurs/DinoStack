"""
Purpose: Load, validate, and consume the ICL-baseline condition spec
         (specs/icl-baseline.yaml), providing the file-selection rule,
         context-budget, prompt template, and model configuration.

Public API:
  load_spec(path: Path) -> dict
  validate_spec(spec: dict) -> None  (delegates to schema.validate_icl_spec)
  assemble_icl_prompt(spec: dict, ticket: dict) -> str
    Builds the full ICL prompt by assembling ticket context files up to
    spec.context_budget_tokens. Uses the v1 fallback (file-selection heuristic)
    when spec.prompt_template_path is absent or a stub.

Upstream deps: schema.py (validate_icl_spec); pyyaml; stdlib pathlib.

Downstream consumers: conditions/icl_baseline.py.

Failure modes: raises FileNotFoundError if the spec path or template path
               is missing. Raises ValueError (via validate_icl_spec) on
               malformed spec. Never raises on prompt assembly; truncates
               context to budget and logs a warning.

Performance: standard; text assembly O(relevant_files_count).
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ..schema import validate_icl_spec

_LOG = logging.getLogger(__name__)

# Rough token estimator: 1 token ~= 4 chars (conservative).
_CHARS_PER_TOKEN = 4


def load_spec(path: Path) -> dict:
    """Load and return the ICL spec dict from YAML."""
    with path.open() as f:
        spec = yaml.safe_load(f)
    validate_spec(spec)
    return spec


def validate_spec(spec: dict) -> None:
    """Delegate to schema.validate_icl_spec."""
    validate_icl_spec(spec)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def assemble_icl_prompt(spec: dict, ticket: dict) -> str:
    """Build the full ICL prompt for one ticket.

    Assembly order:
    1. System/role preamble (from prompt template if present, else built-in v1 stub)
    2. Ticket description (from ticket.yaml)
    3. Relevant files (selected by file_selection_rule; budget-capped)
    4. Task instruction

    v1 fallback: when the prompt template is a stub (path is 'stub' or file
    doesn't exist), uses a built-in template. When icl-baseline-spec lands
    with a concrete template, the harness upgrades automatically without
    code change - only the YAML path changes.
    """
    budget_tokens = spec.get("context_budget_tokens", 200_000)
    budget_chars = budget_tokens * _CHARS_PER_TOKEN

    # Load prompt template
    template_path_str = spec.get("prompt_template_path", "stub")
    template_path = Path(template_path_str)
    if template_path_str == "stub" or not template_path.exists():
        _LOG.debug(
            "ICL prompt template '%s' is a stub or absent; using v1 built-in template.",
            template_path_str,
        )
        template = _BUILTIN_V1_TEMPLATE
    else:
        template = template_path.read_text()

    # Ticket description
    ticket_yaml = ticket.get("ticket_yaml", {})
    description = ticket_yaml.get("description", "(no description)")
    ticket_id = ticket.get("ticket_id", "unknown")

    # Assemble context budget
    relevant_files_dir = ticket.get("relevant_files_dir")
    file_selection_rule = spec.get("file_selection_rule", "all")
    context_files = _select_files(relevant_files_dir, file_selection_rule)

    # Budget-cap context files
    header = template.format(ticket_id=ticket_id, description=description)
    used_chars = len(header)
    included_files: list[tuple[str, str]] = []
    for fpath, content in context_files:
        if used_chars + len(content) > budget_chars:
            _LOG.warning(
                "Context budget hit for ticket '%s'; truncating at %d chars.",
                ticket_id,
                budget_chars,
            )
            break
        included_files.append((fpath, content))
        used_chars += len(content)

    # Build final prompt
    parts = [header, ""]
    if included_files:
        parts.append("## Relevant Files\n")
        for fpath, content in included_files:
            parts.append(f"### {fpath}\n```\n{content}\n```\n")

    parts += [
        "## Task",
        "Implement the changes described in this ticket.",
        "Provide a complete response including:",
        "1. Your rationale and plan (## Rationale)",
        "2. The complete diff of all changes (## Diff)",
        "",
    ]
    return "\n".join(parts)


def _select_files(
    relevant_files_dir: object, rule: str
) -> list[tuple[str, str]]:
    """Return [(filename, content), ...] based on the file_selection_rule."""
    if relevant_files_dir is None:
        return []
    d = Path(relevant_files_dir)
    if not d.exists():
        return []
    files = sorted(d.iterdir())
    if rule == "all":
        pass  # include all
    elif rule == "top_k":
        files = files[:10]  # default k=10; v1 stub
    # else: unknown rule treated as "all"
    result = []
    for f in files:
        if f.is_file():
            try:
                content = f.read_text()
                result.append((f.name, content))
            except OSError:
                pass
    return result


_BUILTIN_V1_TEMPLATE = """\
# ICL Baseline - Single Prompt Implementation

You are an expert software engineer. Implement the following ticket in one response.

## Ticket: {ticket_id}

{description}
"""
