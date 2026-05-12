"""
Purpose: Build the AE-rules-injected system-prompt payload by concatenating
         content/ files in the canonical glob order for the skill-comparison
         eval's `ae-rules-injected` condition.

Public API: build_payload(content_root: Path) -> str
            content_glob(content_root: Path) -> list[Path]

            build_payload is a pure function: identical content/ trees produce
            byte-identical output. content_glob exposes the ordered file list
            used for cache-key derivation in spec YAMLs.

Upstream deps: stdlib pathlib, glob.

Downstream consumers: evals/skill-comparison/runner.py (injects payload as
                       the outer conductor's system prompt for the
                       ae-rules-injected condition).

Failure modes: raises FileNotFoundError if content_root does not exist or
               if SKILL.md is absent. Individual section/rule/reference/
               command files that cannot be read are skipped with a warning
               comment inserted in the payload so missing files surface
               at review time rather than silently dropping content.

               Note: references/ scope is *.md ONLY (not *.yml). The Brief
               scopes the AE-rules payload to *.md files across all groups.
               The .yml reference examples (spawn-presets-example.yml,
               tier-map-example.yml) are excluded to stay within Brief scope.

Performance: O(total file bytes); dominated by I/O. Typically < 600 KB;
             runs once per matrix cell setup, not per-run.
"""
from __future__ import annotations

import glob
import os
from pathlib import Path


# Stable separator used between each file section in the payload.
# Including the relative path makes the payload self-documenting and
# allows assert_canary.py to verify content provenance.
_SEPARATOR_TEMPLATE = "\n\n# === {rel_path} ===\n\n"


def content_glob(content_root: Path) -> list[Path]:
    """Return the ordered list of content/ files that compose the payload.

    Order is load-bearing (matches Brief Measurement Equivalence rationale):
      1. SKILL.md          - skill manifest / entry point
      2. sections/*.md     - methodology core
      3. rules/*.md        - code standards, conventions, module manifests
      4. references/*.md   - on-demand protocol text
      5. commands/*.md     - slash-command bodies

    Within each glob, files are sorted lexicographically by filename for
    determinism across filesystems and Python versions.

    This is the canonical cache-key source: any spec YAML's content_glob
    field MUST list these five glob patterns in this order.
    """
    root = Path(content_root)

    def _sorted_glob(pattern: str) -> list[Path]:
        matches = [Path(p) for p in glob.glob(str(root / pattern))]
        return sorted(matches, key=lambda p: p.name)

    ordered: list[Path] = []

    # 1. SKILL.md - single file, must exist.
    skill_md = root / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(
            f"SKILL.md not found in content_root: {root}. "
            f"The AE-rules payload requires SKILL.md as its entry point."
        )
    ordered.append(skill_md)

    # 2. sections/*.md
    ordered.extend(_sorted_glob("sections/*.md"))

    # 3. rules/*.md
    ordered.extend(_sorted_glob("rules/*.md"))

    # 4. references/*.md (*.md only - Brief scopes payload to *.md files).
    # .yml reference examples are excluded to stay within Brief scope.
    ordered.extend(_sorted_glob("references/*.md"))

    # 5. commands/*.md
    ordered.extend(_sorted_glob("commands/*.md"))

    return ordered


def build_payload(content_root: Path) -> str:
    """Concatenate content/ files into the AE-rules system-prompt payload.

    Returns a single string with each file separated by a stable header line
    containing the file's path relative to content_root. The output is
    deterministic given the same content/ tree.

    Args:
        content_root: Path to the content/ directory (e.g. repo_root / "content").

    Returns:
        Concatenated payload string suitable for injection as a system prompt.

    Raises:
        FileNotFoundError: if content_root does not exist.
    """
    root = Path(content_root)
    if not root.exists():
        raise FileNotFoundError(f"content_root does not exist: {root}")

    files = content_glob(root)
    parts: list[str] = []

    for path in files:
        rel = path.relative_to(root)
        separator = _SEPARATOR_TEMPLATE.format(rel_path=str(rel))
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            # Surface missing/unreadable files in the payload rather than
            # silently dropping content.
            text = f"[ERROR: could not read {rel}: {exc}]"
        parts.append(separator + text)

    return "".join(parts)
