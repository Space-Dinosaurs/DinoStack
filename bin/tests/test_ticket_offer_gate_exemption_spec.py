#!/usr/bin/env python3
"""
Purpose: Bidirectional set-equality pin between the disk-derived set of
         agent roles (content/agents/*.md basenames + the kernel-only
         "general-purpose" fallback) and the Ticket-Offer Gate's
         EXEMPT/GATED classification in content/references/
         delegation-detail.md §Ticket-Offer Gate - Exemption Set.
Public API: pytest test functions only.
Upstream deps: content/agents/*.md (glob, basenames only); this file's
         own EXEMPT_ROLES / GATED_ROLES constants, which MUST mirror
         content/references/delegation-detail.md §Ticket-Offer Gate -
         Exemption Set verbatim - update both in the same PR.
Downstream consumers: bin-tests.yml python-bin-tests job (pytest
         bin/tests/ -q), full-directory glob discovery, no per-file
         wiring required.
Failure modes: a new content/agents/*.md file with no classification
         reddens the missing-check direction; a removed/renamed file
         with a stale classification entry reddens the phantom-check
         direction. Both are asserted independently (bidirectional set
         equality, not containment).
"""
from __future__ import annotations
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "content" / "agents"

# Mirrors content/references/delegation-detail.md §Ticket-Offer Gate -
# Exemption Set verbatim. Update both in the same PR.
EXEMPT_ROLES = {
    "skeptic", "qa-engineer", "learning-extractor", "learnings-agent",
    "wrap-ticket", "goal-condition-evaluator", "product-discovery",
}
GATED_ROLES = {
    "investigator", "debugger", "architect", "orchestration-planner",
    "engineer", "security-auditor", "dependency-auditor", "perf-analyst",
    "adr-generator", "adr-drift-detector", "general-purpose",
    "release-orchestrator",
}

def _agent_basenames(agents_dir: pathlib.Path) -> set[str]:
    return {p.stem for p in agents_dir.glob("*.md")}

def _disk_roles(agents_dir: pathlib.Path) -> set[str]:
    return _agent_basenames(agents_dir) | {"general-purpose"}

def _classify_delta(agents_dir: pathlib.Path) -> tuple[set[str], set[str]]:
    """The SOLE predicate. Every test below calls this - never re-implement
    the subtraction inline, or a mutation test proves only that its own copy
    of the logic reddens."""
    disk_roles = _disk_roles(agents_dir)
    classified = EXEMPT_ROLES | GATED_ROLES
    return disk_roles - classified, classified - disk_roles

def test_every_role_is_classified_exactly_once():
    missing, phantom = _classify_delta(AGENTS_DIR)
    assert not missing and not phantom, f"missing={missing} phantom={phantom}"

def test_exempt_and_gated_are_disjoint():
    overlap = EXEMPT_ROLES & GATED_ROLES
    assert not overlap, f"role(s) in both sets: {overlap}"

def test_mutation_added_unclassified_agent_file_reddens(tmp_path):
    for f in AGENTS_DIR.glob("*.md"):
        (tmp_path / f.name).write_text("")
    (tmp_path / "totally-new-agent.md").write_text("")
    missing, phantom = _classify_delta(tmp_path)
    assert missing == {"totally-new-agent"}, missing
    assert not phantom, phantom

def test_mutation_removed_agent_file_reddens(tmp_path):
    removed = "wrap-ticket"
    # Precondition: without this, a rename of the target file makes the skip
    # loop match nothing while the phantom assertion still holds - a vacuous pass.
    assert (AGENTS_DIR / f"{removed}.md").exists(), (
        f"fixture target content/agents/{removed}.md no longer exists - "
        "update `removed` to a real agent file"
    )
    for f in AGENTS_DIR.glob("*.md"):
        if f.stem == removed:
            continue
        (tmp_path / f.name).write_text("")
    missing, phantom = _classify_delta(tmp_path)
    assert phantom == {removed}, phantom
    assert not missing, missing
