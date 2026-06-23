#!/usr/bin/env python3
"""
Regression tests for agentic-models: scoring, ranking, payload shape.

Test groups:
  1. test_score_substring_match - hint substrings match case-insensitively.
  2. test_score_negative_penalty - "haiku" demotes architect-role picks.
  3. test_score_preview_penalty - preview / experimental models lose tie-breaks.
  4. test_rank_orders_by_score_then_alpha - ranking is deterministic.
  5. test_suggestions_shape - payload has models[], roles{} (9 keys), reviewer_pool[].
  6. test_suggestions_handles_empty_models - empty input yields None primaries.
  7. test_suggestions_distinct_families - reviewer pool pulls from >=2 families.

Run with: python3 -m pytest bin/tests/test_agentic_models.py -x
       or: python3 bin/tests/test_agentic_models.py
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Load agentic-models as a module (no .py extension)
# ---------------------------------------------------------------------------
_BIN_PATH = Path(__file__).parent.parent / "agentic-models"
_loader = importlib.machinery.SourceFileLoader("agentic_models", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("agentic_models", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-models from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

_score = _mod._score
_rank = _mod._rank
_suggestions = _mod._suggestions
ROLES = _mod.ROLES


def test_score_substring_match():
    assert _score("cc/claude-opus-4-5-20251101", {"opus": 5}) == 5
    assert _score("OPUS-4", {"opus": 1}) == 1  # case-insensitive
    assert _score("llama-3.1-8b", {"opus": 5}) == 0


def test_score_negative_penalty():
    assert _score("claude-haiku-4-5", {"opus": 5, "haiku": -3}) == -3
    assert _score("claude-haiku-4-5", {"haiku": 1}) == 1


def test_score_preview_penalty():
    base = _score("claude-opus-4-5", {"opus": 5})
    previewed = _score("claude-opus-4-5-preview", {"opus": 5})
    assert previewed == base - 1


def test_rank_orders_by_score_then_alpha():
    models = ["a-model", "b-model", "c-model"]
    ranked = _rank(models, {"b-model": 1, "a-model": 1})
    # Same score, alpha tiebreak
    assert [m for m, _ in ranked] == ["a-model", "b-model", "c-model"]


def test_suggestions_shape():
    payload = _suggestions(["claude-opus-4-5", "claude-sonnet-4-5", "gpt-5.5"])
    assert "models" in payload
    assert "roles" in payload
    assert "reviewer_pool" in payload
    assert set(payload["roles"].keys()) == set(ROLES)
    for _role, info in payload["roles"].items():
        assert "alternates" in info
        assert len(info["alternates"]) <= 3


def test_suggestions_handles_empty_models():
    payload = _suggestions([])
    assert payload["models"] == []
    assert payload["roles"]["architect"]["primary"] is None
    assert payload["reviewer_pool"] == []


def test_suggestions_distinct_families():
    """Reviewer pool should not be all one family if alternatives exist."""
    models = [
        "cc/claude-opus-4-5",
        "cc/claude-sonnet-4-5",
        "cc/claude-haiku-4-5",
        "cx/gpt-5.5",
        "kimi/kimi-k2.7",
        "glm/glm-5.2",
    ]
    payload = _suggestions(models)
    pool = payload["reviewer_pool"]
    families = {m.split("/", 1)[0] for m in pool}
    # The pool must include at least 2 different families (e.g. cc + cx + kimi).
    assert len(families) >= 2, f"reviewer pool too narrow: {pool}"



def test_cli_help_runs():
    """Issue #1 regression: `main()` must be defined; --help exits 0."""
    r = subprocess.run([sys.executable, str(_BIN_PATH), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "agentic-models" in r.stdout


def test_cli_requires_probe_url():
    """No probe URL -> exit 3 from main(), not NameError (exit 1)."""
    env = dict(os.environ)
    env.pop("AGENTIC_PROBE_URL", None)
    r = subprocess.run([sys.executable, str(_BIN_PATH)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 3
    assert "required" in r.stderr

def main() -> int:
    failures = 0
    tests = [
        test_score_substring_match,
        test_score_negative_penalty,
        test_score_preview_penalty,
        test_rank_orders_by_score_then_alpha,
        test_suggestions_shape,
        test_suggestions_handles_empty_models,
        test_suggestions_distinct_families,
        test_cli_help_runs,
        test_cli_requires_probe_url,
    ]
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as exc:
            print(f"FAIL  {t.__name__}: {exc}")
            failures += 1
    if failures:
        print(f"{failures} test(s) failed")
        return 1
    print(f"All {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
