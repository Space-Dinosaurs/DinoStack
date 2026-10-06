"""
Purpose: Pins the prose wiring that routes every MEMORY.md capture writer
         through bin/ds-memory-capture in a compiled two-tier project. The
         helper's behaviour is tested in test_ds_memory_capture.py and the
         Phase 11e ride-along in test_phase11e_knowledge_commit_shell.py; a
         helper nobody calls passes both, so each assertion here is reddened
         by deleting the clause it names.

Public API: none (pytest module).

Upstream deps: content/agents/{wrap-ticket,learnings-agent}.md,
               content/commands/{ds-wrap,ds-memory-update,ds-implement-ticket}.md.

Downstream consumers: .github/workflows/bin-tests.yml (pytest bin/tests/).

Failure modes: n/a (test module).

Performance: standard.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INBOX = ".agentic/memory-capture-inbox.md"


def _text(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


@pytest.mark.parametrize("rel", [
    "content/agents/wrap-ticket.md",
    "content/agents/learnings-agent.md",
    "content/commands/ds-wrap.md",
    "content/commands/ds-memory-update.md",
])
def test_each_writer_has_a_compiled_clause_naming_the_inbox(rel):
    lines = [ln for ln in _text(rel).splitlines() if "**Compiled mode" in ln and INBOX in ln]
    assert lines, f"{rel}: no compiled-mode clause naming {INBOX}"
    assert any("MEMORY.md" in ln and ("never" in ln.lower()) for ln in lines), (
        f"{rel}: the compiled-mode clause must forbid writing MEMORY.md directly"
    )


def test_phase_11b_flushes_before_releasing_the_lock_and_skips_part_e():
    phase = _between(_text("content/commands/ds-implement-ticket.md"),
                     "## Phase 11b:", "## Phase 11d:")
    flush = phase.find('ds-memory-capture flush --dir "$REPO"')
    release = phase.find('ds-wrap-release-lock "$REPO"')
    assert flush != -1, "Phase 11b never runs ds-memory-capture flush"
    assert release != -1 and flush < release, "flush must run before the lock is released"
    assert "- `memory_mode`:" in phase, "wrap-ticket is never told the memory mode"
    assert "**Skip entirely** in compiled mode" in phase, "Part E gate check is not skipped in compiled mode"


def test_ds_wrap_part_b_runs_flush():
    part_b = _between(_text("content/commands/ds-wrap.md"),
                      "Write MEMORY.md**", "Write AGENTS.md updates**")
    assert "run `ds-memory-capture flush`" in part_b


def test_ds_wrap_part_e_excludes_compiled_memory_md():
    part_e = _between(_text("content/commands/ds-wrap.md"), "**Targets:**", "**State file:**")
    memory_line = next(ln for ln in part_e.splitlines() if ln.startswith("- `[cwd]/MEMORY.md`"))
    assert "Not a target in compiled mode" in memory_line


def test_ds_wrap_part_g_ships_new_shards_with_memory_md():
    part_g = _text("content/commands/ds-wrap.md").split("**Part G - Knowledge-file commit.**", 1)[1]
    assert "ds-memory-capture new-shards --ref origin/<BASE_BRANCH>" in part_g
