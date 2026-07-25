#!/usr/bin/env bash
# Purpose: Read-only verification of generated Codex native skills, reviewed
#          compatibility occurrences, resource closure, and committed bytes.
#
# Public API: bash scripts/check-codex-skill-sync.sh
#
# Upstream deps: scripts/codex-skills.py and its canonical/generated inputs.
#
# Downstream consumers: .github/workflows/codex-skill-sync.yml and pre-commit.
#
# Failure modes: propagates any inventory, frontmatter, link, resource, marker,
#                arbitrary-cwd, unexpected-path, or generated-byte failure.
#
# Performance: one private render and bounded four-skill validation.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$REPO_DIR/scripts/codex-skills.py" check --repo "$REPO_DIR"
