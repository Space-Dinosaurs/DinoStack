"""
Conftest for evals/skill-comparison/tests/.

The parent directory is named `skill-comparison` which contains a hyphen and
is therefore not a valid Python identifier. This conftest inserts the
`skill-comparison/` directory into sys.path so test modules can import
`ae_rules_payload` directly without a dotted-path reference to the
hyphen-named package.
"""
import sys
from pathlib import Path

_SKILL_COMPARISON_DIR = Path(__file__).parent.parent  # evals/skill-comparison/
if str(_SKILL_COMPARISON_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_COMPARISON_DIR))
