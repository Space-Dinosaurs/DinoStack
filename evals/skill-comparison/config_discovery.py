"""
Purpose: Discover condition configs from evals/skill-comparison/specs/*.yaml and
         return structured metadata suitable for driving the 8-condition matrix
         runner. Mirrors the aggregate_benchmark dynamic-discovery pattern from
         evals/skill-comparison's reference implementation.

Public API:
    discover_configs(specs_dir: Path | None = None) -> list[ConditionConfig]

    ConditionConfig (dataclass):
        name: str           # condition name (e.g. "baseline", "ae-rules-injected")
        spec_path: Path     # absolute path to the YAML spec file
        raw: dict           # parsed YAML contents (full spec, unvalidated)
        content_glob: list[str]   # from spec's content_glob field (empty list if absent)
        description: str    # from spec's description field (empty string if absent)

Upstream deps: stdlib pathlib, importlib.util; pyyaml (project-standard dep).

Downstream consumers: evals/skill-comparison/runner.py.

Failure modes: returns empty list if specs_dir does not exist or contains no
               *.yaml files (caller decides whether to abort or warn). Per-file
               parse errors are logged as warnings and that file is skipped so
               one bad spec does not block the rest. yaml.YAMLError is caught
               per-file; other OSError bubbles up from open() as it indicates
               a filesystem issue broader than a single spec.

Performance: O(number of spec files); dominated by YAML parse. Negligible for
             the expected 8-10 spec files.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# yaml is project-standard (pyyaml in requirements.txt).
try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "pyyaml is required for config_discovery; install it with: pip install pyyaml"
    ) from exc

_LOG = logging.getLogger(__name__)

# Default specs dir: same directory as this file, under "specs/".
_DEFAULT_SPECS_DIR = Path(__file__).parent / "specs"

# Canonical 8-condition list. Discovery returns conditions in this order when
# possible; unknown conditions are appended after in filesystem order.
CANONICAL_CONDITIONS: list[str] = [
    "baseline",
    "ae-rules-injected",
    "engineer-direct",
    "architect-direct",
    "investigator-direct",
    "debugger-direct",
    "skeptic-direct",
    "qa-engineer-direct",
]


@dataclass
class ConditionConfig:
    """Parsed metadata for one condition spec YAML."""

    name: str
    spec_path: Path
    raw: dict = field(default_factory=dict, repr=False)
    content_glob: list[str] = field(default_factory=list)
    description: str = ""


def discover_configs(specs_dir: Path | None = None) -> list[ConditionConfig]:
    """Discover and parse condition configs from specs_dir/*.yaml.

    Args:
        specs_dir: directory to scan for *.yaml files. Defaults to
                   evals/skill-comparison/specs/ (relative to this file).

    Returns:
        List of ConditionConfig, sorted in CANONICAL_CONDITIONS order first,
        then any remaining specs in lexicographic order.
    """
    target_dir = Path(specs_dir) if specs_dir is not None else _DEFAULT_SPECS_DIR

    if not target_dir.exists():
        _LOG.warning(
            "config_discovery: specs_dir %s does not exist; returning empty list.",
            target_dir,
        )
        return []

    yaml_files = sorted(target_dir.glob("*.yaml"))
    if not yaml_files:
        _LOG.warning(
            "config_discovery: no *.yaml files found in %s; returning empty list.",
            target_dir,
        )
        return []

    raw_configs: list[ConditionConfig] = []
    for spec_path in yaml_files:
        try:
            with open(spec_path, encoding="utf-8") as fh:
                raw: Any = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            _LOG.warning(
                "config_discovery: skipping %s - YAML parse error: %s",
                spec_path.name,
                exc,
            )
            continue

        if not isinstance(raw, dict):
            _LOG.warning(
                "config_discovery: skipping %s - top-level YAML must be a mapping.",
                spec_path.name,
            )
            continue

        # Derive condition name from the YAML's "condition" key, falling back
        # to the stem of the filename (e.g. "baseline.yaml" -> "baseline").
        condition_name: str = raw.get("condition") or spec_path.stem

        content_glob_raw = raw.get("content_glob", [])
        if isinstance(content_glob_raw, str):
            content_glob_raw = [content_glob_raw]
        content_glob: list[str] = list(content_glob_raw) if content_glob_raw else []

        description: str = raw.get("description", "") or ""

        raw_configs.append(
            ConditionConfig(
                name=condition_name,
                spec_path=spec_path.resolve(),
                raw=raw,
                content_glob=content_glob,
                description=description,
            )
        )

    # Sort: canonical order first, then lexicographic for unknowns.
    canonical_index: dict[str, int] = {c: i for i, c in enumerate(CANONICAL_CONDITIONS)}
    n_canonical = len(CANONICAL_CONDITIONS)

    def _sort_key(cfg: ConditionConfig) -> tuple[int, str]:
        return canonical_index.get(cfg.name, n_canonical), cfg.name

    return sorted(raw_configs, key=_sort_key)
