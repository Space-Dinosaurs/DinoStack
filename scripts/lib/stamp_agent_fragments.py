# Purpose: Python implementation for scripts/stamp-agent-fragments.sh - see
#          that file's manifest header for the full contract (Public API,
#          Upstream deps, Downstream consumers, Failure modes). Split out so
#          the bash entrypoint stays a thin, portable wrapper (no bash
#          heredoc/regex gymnastics for multiline HTML-comment span
#          replacement).
#
# Public API: python3 scripts/lib/stamp_agent_fragments.py
#             Exits 0 on success (including the idempotent no-op case),
#             non-zero if any `<!-- shared:<id> -->` span references an
#             undefined fragment id, or if the kernels file is missing.
#
# Upstream deps: content/fragments/pre-submit-check-kernels.md;
#                content/agents/*.md; python3 stdlib only (re, pathlib, sys).
#
# Downstream consumers: scripts/stamp-agent-fragments.sh (sole caller).

import re
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent.parent
KERNELS_FILE = REPO_DIR / "content" / "fragments" / "pre-submit-check-kernels.md"
AGENTS_DIR = REPO_DIR / "content" / "agents"

FRAGMENT_RE = re.compile(
    r"<!-- FRAGMENT:(?P<id>[a-zA-Z0-9_-]+) -->\n(?P<body>.*?)\n<!-- /FRAGMENT -->",
    re.DOTALL,
)
SHARED_RE = re.compile(
    r"<!-- shared:(?P<id>[a-zA-Z0-9_-]+) -->.*?<!-- /shared -->",
    re.DOTALL,
)


def load_fragments() -> dict:
    if not KERNELS_FILE.is_file():
        print(f"stamp-agent-fragments: kernels file not found: {KERNELS_FILE}", file=sys.stderr)
        sys.exit(1)
    text = KERNELS_FILE.read_text(encoding="utf-8")
    fragments = {}
    for match in FRAGMENT_RE.finditer(text):
        fragments[match.group("id")] = match.group("body").strip()
    return fragments


def stamp_file(path: Path, fragments: dict) -> bool:
    original = path.read_text(encoding="utf-8")
    missing_ids = []

    def replace(match: "re.Match") -> str:
        frag_id = match.group("id")
        if frag_id not in fragments:
            missing_ids.append(frag_id)
            return match.group(0)
        return f"<!-- shared:{frag_id} -->{fragments[frag_id]}<!-- /shared -->"

    updated = SHARED_RE.sub(replace, original)

    if missing_ids:
        unique = sorted(set(missing_ids))
        print(
            f"stamp-agent-fragments: {path.relative_to(REPO_DIR)} references "
            f"undefined fragment id(s): {', '.join(unique)}",
            file=sys.stderr,
        )
        sys.exit(1)

    if updated != original:
        path.write_text(updated, encoding="utf-8")
        print(f"stamp-agent-fragments: stamped {path.relative_to(REPO_DIR)}")
        return True
    return False


def main() -> None:
    fragments = load_fragments()
    changed = False
    for path in sorted(AGENTS_DIR.glob("*.md")):
        if stamp_file(path, fragments):
            changed = True
    if not changed:
        print("stamp-agent-fragments: no changes (tree already stamped)")


if __name__ == "__main__":
    main()
