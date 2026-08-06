#!/usr/bin/env bash
# Purpose: Read-only verification of generated Codex native skills and legacy
#          prompt wrappers, reviewed compatibility occurrences, resource
#          closure, and committed bytes.
#
# Public API: bash scripts/check-codex-skill-sync.sh
#
# Upstream deps: scripts/codex-skills.py, .codex/lib/prompt-wrappers.py, and
#                their canonical/generated inputs.
#
# Downstream consumers: .github/workflows/codex-skill-sync.yml and pre-commit.
#
# Failure modes: propagates any inventory, frontmatter, link, resource, marker,
#                ownership, recovery-state, unexpected-path, or generated-byte
#                failure.
#
# Performance: one private render, bounded four-skill validation, and one
#              direct prompt-wrapper inventory validation.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$REPO_DIR/scripts/codex-skills.py" check --repo "$REPO_DIR"
python3 "$REPO_DIR/.codex/lib/prompt-wrappers.py" check --repo "$REPO_DIR"
