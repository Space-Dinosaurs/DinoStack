#!/usr/bin/env python3
"""
Tests for bin/_steps.py: step ids derived from headings (fences skipped,
content/sections/README.md excluded, collisions qualified by the nearest `##`
ancestor and only the leftovers reported), the one-step-source-per-row rule
(step_outcome, writeback sites, unmapped sites, spawn rows never), the ledger
field map, and, against the live checkout, that every map value and every
helper step literal resolves to a heading.

Run with: python3 -m pytest bin/tests/test_steps.py -q
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_loader = importlib.machinery.SourceFileLoader("steps_under_test", str(REPO_ROOT / "bin" / "_steps.py"))
steps = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(steps)

COMMAND = """# Do Thing

## Phase 1: Start

#### If TRACKER is `none`

```bash
## Phase 99: inside a fence
# a shell comment
```

## Phase 8.5: Later (conditional)

#### If TRACKER is `none`

### Dup
### Dup

~~~
## Not a heading
~~~
"""


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "content" / "commands").mkdir(parents=True)
    (tmp_path / "content" / "sections").mkdir(parents=True)
    (tmp_path / "content" / "commands" / "ds-do-thing.md").write_text(COMMAND)
    (tmp_path / "content" / "sections" / "04-risk.md").write_text("## Risk\n\n### Elevated routes\n")
    (tmp_path / "content" / "sections" / "README.md").write_text("## Readme heading\n")
    return tmp_path


def test_ids_skip_fences_and_readme_and_qualify_collisions(tmp_path):
    got = steps.derive_steps(_repo(tmp_path))
    assert set(got["steps"]) == {
        "do-thing/do-thing", "do-thing/phase-1", "do-thing/phase-8.5",
        "do-thing/phase-1/if-tracker-is-none", "do-thing/phase-8.5/if-tracker-is-none",
        "04-risk/risk", "04-risk/elevated-routes",
    }
    assert got["steps"]["do-thing/phase-8.5"] == {
        "file": "content/commands/ds-do-thing.md", "line": 12, "heading": "Phase 8.5: Later (conditional)"}
    assert got["collisions"] == [
        {"id": "do-thing/phase-8.5/dup", "file": "content/commands/ds-do-thing.md", "lines": [16, 17]}]


def test_one_step_source_per_row():
    assert steps.event_step({"event": "step_outcome", "phase": "ci_loop",
                             "data": {"step": "implement-ticket/phase-10", "outcome": "failed"}}) == (
        "implement-ticket/phase-10", "failed", "step_outcome")
    assert steps.event_step({"event": "tracker_writeback", "data": {"site": "W1", "outcome": "dispatched"}}) == (
        "implement-ticket/tracker-writeback-w1", "dispatched", "tracker_writeback")
    assert steps.event_step({"event": "knowledge_commit", "data": {"site": "phase-11e", "status": "committed"}}) == (
        "implement-ticket/phase-11e", "committed", "knowledge_commit")
    assert steps.event_step({"event": "tracker_writeback", "data": {"site": "W2", "outcome": "dispatched"}}) == (
        "unmapped", "W2", "tracker_writeback")
    for spawn in ("spawn_start", "spawn_complete"):
        assert steps.event_step({"event": spawn, "phase": "skeptic", "data": {"source": "hook"}}) is None


def test_ledger_outcomes():
    lf = steps.LEDGER_FIELD_TO_STEP
    assert steps.ledger_outcomes({"risk_class": "Elevated", "elevated_route": None, "skeptic_rounds": 2,
                                  "qa_status": "skipped:docs-only"}) == [
        (lf["risk_class"], "Elevated", "ledger:risk_class"),
        (lf["elevated_route"], "unknown", "ledger:elevated_route"),
        (lf["skeptic_rounds"], "rounds:2", "ledger:skeptic_rounds"),
        (lf["qa_status"], "skipped:docs-only", "ledger:qa_status"),
    ]
    assert steps.ledger_outcomes({"risk_class": "Low", "elevated_route": "full", "skeptic_rounds": None,
                                  "qa_status": None}) == [(lf["risk_class"], "Low", "ledger:risk_class")]


def test_live_repo_ids():
    got = steps.derive_steps(REPO_ROOT)
    ids = set(got["steps"])
    assert got["collisions"] == []
    text = (REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md").read_text()
    phases = {"implement-ticket/phase-" + m.lower() for m in re.findall(r"^## Phase ([^:\s]+):", text, re.M)}
    assert phases and phases <= ids
    assert {
        "04-risk-classification/elevated-routes",
        "implement-ticket/risk-classification-declaration-unconditional-runs-on-every-ticket",
        "implement-ticket/phase-1/if-tracker-is-none",
        "implement-ticket/phase-11/if-tracker-is-none",
    } <= ids
    assert not any(s.startswith("README/") for s in ids)


def test_every_map_value_and_helper_literal_resolves():
    ids = set(steps.derive_steps(REPO_ROOT)["steps"])
    literals = steps.helper_step_literals(REPO_ROOT)
    assert literals == {"implement-ticket/phase-8", "implement-ticket/phase-10", "implement-ticket/phase-12",
                        "implement-ticket/ticket-rework-ledger-write"}
    instrumented = steps.instrumented_steps(REPO_ROOT)
    assert instrumented == literals | set(steps.SITE_TO_STEP.values()) | set(steps.LEDGER_FIELD_TO_STEP.values())
    assert instrumented - ids == set()
