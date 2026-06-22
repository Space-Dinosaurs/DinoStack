#!/usr/bin/env bash
# Purpose: Verify that the body of content/SKILL.md (after stripping the
#          leading HTML-comment manifest block) matches the committed sentinel
#          hash in .codex/skill/.content-skill-sha256. Used as a CI gate to
#          detect unreviewed changes to content/SKILL.md that may require a
#          corresponding update to .codex/skill/SKILL.md.
#
# Public API: bash scripts/check-codex-skill-sync.sh
#             Exits 0 on match, 1 on mismatch or missing sentinel file.
#
# Upstream deps: content/SKILL.md; sha256sum (or shasum -a 256);
#                .codex/skill/.content-skill-sha256.
#
# Downstream consumers: .github/workflows/codex-skill-sync.yml.
#
# Failure modes: missing sentinel file -> exit 1 with regen instructions;
#                hash mismatch -> exit 1 with actionable message and regen
#                command. Read-only; no side effects on the repo.
#
# Performance: O(size of content/SKILL.md); one strip + one hash.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SENTINEL_FILE="$REPO_DIR/.codex/skill/.content-skill-sha256"
SOURCE_FILE="$REPO_DIR/content/SKILL.md"

REGEN_CMD="perl -0pe 's/\\A<!--.*?-->\\n\\n?//s' content/SKILL.md | sha256sum | awk '{print \$1}' > .codex/skill/.content-skill-sha256"

if [ ! -f "$SENTINEL_FILE" ]; then
  echo "check-codex-skill-sync.sh: sentinel file missing: $SENTINEL_FILE" >&2
  echo "  To initialize the sentinel:" >&2
  echo "    $REGEN_CMD" >&2
  exit 1
fi

if [ ! -f "$SOURCE_FILE" ]; then
  echo "check-codex-skill-sync.sh: source file missing: $SOURCE_FILE" >&2
  exit 1
fi

expected="$(cat "$SENTINEL_FILE" | tr -d '[:space:]')"

# Strip the leading HTML comment block exactly as .claude/build.sh does,
# then hash the resulting body.
# Prefer sha256sum (Linux/CI) when available; fall back to shasum -a 256 (macOS).
if command -v sha256sum >/dev/null 2>&1; then
  current="$(perl -0pe 's/\A<!--.*?-->\n\n?//s' "$SOURCE_FILE" | sha256sum | awk '{print $1}')"
else
  current="$(perl -0pe 's/\A<!--.*?-->\n\n?//s' "$SOURCE_FILE" | shasum -a 256 | awk '{print $1}')"
fi

if [ "$current" = "$expected" ]; then
  echo "codex-skill-sync check: OK ($current)"
  exit 0
fi

echo "codex-skill-sync check: MISMATCH" >&2
echo "" >&2
echo "  content/SKILL.md has changed since .codex/skill/SKILL.md was last reviewed." >&2
echo "" >&2
echo "  Review .codex/skill/SKILL.md and update it if needed to reflect the changes" >&2
echo "  in content/SKILL.md, then regenerate the sentinel with:" >&2
echo "" >&2
echo "    $REGEN_CMD" >&2
echo "" >&2
echo "  Include the updated sentinel in the same commit." >&2
echo "" >&2
echo "  expected: $expected" >&2
echo "  current:  $current" >&2
exit 1
