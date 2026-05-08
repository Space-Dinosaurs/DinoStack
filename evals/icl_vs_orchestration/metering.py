"""
Purpose: Extract token counts and estimated USD cost from a Claude CLI
         stream-json run record, reusing the normalizer output shape from
         evals.runner.normalizer.

Public API:
  extract_tokens(run_record: dict) -> dict
    Returns {input: int, output: int, cache_creation: int, cache_read: int}.
  estimate_cost_usd(tokens: dict, model: str) -> float
    Returns estimated USD cost using known per-token rates for common models.
    Returns 0.0 for unknown models (logged as a diagnostic, not an error).

Upstream deps: evals.runner.normalizer (parse_stream_json output shape);
               stdlib only.

Downstream consumers: conditions/ae_orchestrated/single_shot.py,
                      conditions/icl_baseline.py, cost_gate.py.

Failure modes: returns 0 counts and 0.0 cost on malformed/absent token fields
               rather than raising; cost estimation for unknown models logs
               a diagnostic warning and returns 0.0.

Performance: standard; O(1) dict lookups.
"""
from __future__ import annotations

import logging

_LOG = logging.getLogger(__name__)

# Per-million-token rates (USD) for known model families.
# Source: Anthropic pricing as of 2026-05.
# Cache rates are per-million-tokens too.
_MODEL_RATES: dict[str, dict[str, float]] = {
    "claude-sonnet": {
        "input": 3.0,
        "output": 15.0,
        "cache_creation": 3.75,
        "cache_read": 0.30,
    },
    "claude-haiku": {
        "input": 0.25,
        "output": 1.25,
        "cache_creation": 0.30,
        "cache_read": 0.03,
    },
    "claude-opus": {
        "input": 15.0,
        "output": 75.0,
        "cache_creation": 18.75,
        "cache_read": 1.50,
    },
    # GLM family (Z.AI, Helios-routine)
    "glm": {
        "input": 0.10,
        "output": 0.10,
        "cache_creation": 0.0,
        "cache_read": 0.0,
    },
    # Kimi K2 (Moonshot AI) - approximate public pricing as of 2026-05.
    # Input: $0.60/M, Output: $2.50/M. Moonshot does not publish a distinct
    # cache-creation rate; using input rate as a conservative estimate.
    # Cache-read at ~10% of input per Moonshot documentation. Refresh if
    # Moonshot updates public pricing at https://platform.moonshot.cn/docs/pricing.
    "claude-kimi-k2": {
        "input": 0.60,
        "output": 2.50,
        "cache_creation": 0.60,
        "cache_read": 0.06,
    },
}


def _resolve_rates(model: str) -> dict[str, float] | None:
    """Return rate dict for `model` by prefix matching; None if unknown."""
    model_lower = model.lower()
    for prefix, rates in _MODEL_RATES.items():
        if prefix in model_lower:
            return rates
    return None


def extract_tokens(run_record: dict) -> dict:
    """Extract token counts from a normalizer run record.

    Looks for token fields directly on the run_record dict (as set by
    parse_stream_json) or under a 'usage' sub-key.
    Returns: {input: int, output: int, cache_creation: int, cache_read: int}.
    """
    # parse_stream_json may surface usage on top-level or nested
    usage = run_record.get("usage") or {}
    if not usage:
        # try flat keys from older normalizer versions
        usage = run_record

    return {
        "input": int(usage.get("input_tokens", 0)),
        "output": int(usage.get("output_tokens", 0)),
        "cache_creation": int(usage.get("cache_creation_input_tokens", 0)),
        "cache_read": int(usage.get("cache_read_input_tokens", 0)),
    }


def estimate_cost_usd(tokens: dict, model: str) -> float:
    """Return estimated USD cost for a set of token counts and a model name.

    Uses prefix matching against _MODEL_RATES. Returns 0.0 and logs a
    warning for unknown models - caller can still record tokens accurately.
    """
    rates = _resolve_rates(model)
    if rates is None:
        _LOG.warning(
            "Unknown model '%s' for cost estimation; recording $0.00. "
            "Add this model's rates to metering._MODEL_RATES.",
            model,
        )
        return 0.0

    per_million = 1_000_000.0
    cost = (
        tokens.get("input", 0) * rates["input"] / per_million
        + tokens.get("output", 0) * rates["output"] / per_million
        + tokens.get("cache_creation", 0) * rates["cache_creation"] / per_million
        + tokens.get("cache_read", 0) * rates["cache_read"] / per_million
    )
    return round(cost, 8)
