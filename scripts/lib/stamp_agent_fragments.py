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
#             undefined fragment id, if the kernels file is missing, or if a
#             file's shared-marker openers/closers are unbalanced or nested.
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
OPENER_RE = re.compile(r"<!-- shared:(?P<id>[a-zA-Z0-9_-]+) -->")
CLOSER_RE = re.compile(r"<!-- /shared -->")


def parse_fragments(text: str) -> dict:
    """Parse `<!-- FRAGMENT:<id> -->...<!-- /FRAGMENT -->` blocks out of the
    kernels file text.

    Rejects a fragment body containing a marker-like string
    (`<!-- shared:` or `<!-- /shared -->`). Without this, stamping is
    non-convergent: SHARED_RE.sub() would inject the marker-like substring
    into every `<!-- shared:<id> -->` span it fills, growing the file (and
    the false "no changes" trigger point) a little more on every re-run,
    each run reporting exit 0.
    """
    fragments = {}
    for match in FRAGMENT_RE.finditer(text):
        frag_id = match.group("id")
        body = match.group("body").strip()
        if OPENER_RE.search(body) or CLOSER_RE.search(body):
            print(
                f"stamp-agent-fragments: fragment '{frag_id}' in "
                f"{KERNELS_FILE.relative_to(REPO_DIR)} contains a marker-like "
                "string ('<!-- shared: -->' or '<!-- /shared -->') in its "
                "body - this makes stamping non-convergent. Remove it from "
                "the fragment text.",
                file=sys.stderr,
            )
            sys.exit(1)
        fragments[frag_id] = body
    return fragments


def load_fragments() -> dict:
    if not KERNELS_FILE.is_file():
        print(f"stamp-agent-fragments: kernels file not found: {KERNELS_FILE}", file=sys.stderr)
        sys.exit(1)
    text = KERNELS_FILE.read_text(encoding="utf-8")
    return parse_fragments(text)


def check_marker_balance(path: Path, text: str) -> None:
    """Guard against an unbalanced or nested `<!-- shared: -->` marker pair.

    SHARED_RE's non-greedy `.*?` will happily match from one opener to the
    NEXT closer in the file if a span is missing its own closer - silently
    swallowing everything in between. Both a missing closer and a missing
    opener (or all closers removed) leave the tree in a stamp-stable state
    that a byte-diff-only check can never catch, so this must fail loud
    before any substitution happens.
    """
    opener_count = len(OPENER_RE.findall(text))
    closer_count = len(CLOSER_RE.findall(text))
    if opener_count != closer_count:
        print(
            f"stamp-agent-fragments: {path.relative_to(REPO_DIR)} has "
            f"{opener_count} '<!-- shared:<id> -->' opener(s) but "
            f"{closer_count} '<!-- /shared -->' closer(s) - a marker is "
            "missing or unbalanced. Fix the markup before stamping.",
            file=sys.stderr,
        )
        sys.exit(1)

    for match in SHARED_RE.finditer(text):
        if OPENER_RE.search(match.group(0), 1):
            print(
                f"stamp-agent-fragments: {path.relative_to(REPO_DIR)} has a "
                f"'<!-- shared:{match.group('id')} -->' span whose body "
                "contains a nested '<!-- shared: -->' opener - markers "
                "cannot nest. Fix the markup before stamping.",
                file=sys.stderr,
            )
            sys.exit(1)


def stamp_file(path: Path, fragments: dict) -> bool:
    original = path.read_text(encoding="utf-8")
    check_marker_balance(path, original)
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
