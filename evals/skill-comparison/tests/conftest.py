"""
Conftest for evals/skill-comparison/tests/.

The parent directory is named `skill-comparison` which contains a hyphen and
is therefore not a valid Python identifier. This conftest inserts the
`skill-comparison/` directory and the `skill-comparison/canary/` subdirectory
into sys.path so test modules can import `ae_rules_payload` and
`assert_canary` directly without dotted-path references.

Test modules must NOT re-insert sys.path entries already managed here (m4 fix:
avoid duplicate sys.path manipulation across conftest and test modules).
"""
import sys
from pathlib import Path

_SKILL_COMPARISON_DIR = Path(__file__).parent.parent  # evals/skill-comparison/
_CANARY_DIR = _SKILL_COMPARISON_DIR / "canary"        # evals/skill-comparison/canary/

for _dir in (_SKILL_COMPARISON_DIR, _CANARY_DIR):
    _dir_str = str(_dir)
    if _dir_str not in sys.path:
        sys.path.insert(0, _dir_str)
