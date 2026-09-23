#!/usr/bin/env python3
"""
Purpose: Pin the Role-default tier table in
         content/references/risk-config-and-tiers.md to each agent's
         frontmatter `model:` in content/agents/*.md. The table header says
         "frontmatter `model:` MUST agree with this table"; that promise was
         broken silently before (DS-137), so this test enforces it (DS-247).

Public API: pytest test functions `test_table_matches_frontmatter` and
            `test_tier_model_mapping`.
            Run with: python3 -m pytest bin/tests/test_role_default_tier_sync.py -q

Upstream deps: content/references/risk-config-and-tiers.md (table found by its
               `| Agent | Default tier |` header row); content/agents/*.md
               (frontmatter block between the first two `---` lines).

Downstream consumers: .github/workflows/bin-tests.yml (auto-discovered by
                      `pytest bin/tests/`).

Failure modes: Fails with the offending agent named when the table's agent set
               differs from content/agents/*.md, when a row's model differs
               from the frontmatter, or when a row's tier and model disagree
               under 1=haiku, 2=sonnet, 3=opus. Fails loudly if the table
               header or a frontmatter `model:` key cannot be found.
               Retirement condition: delete when the table is generated from
               frontmatter.

Performance: Reads 19 small files; well under 100 ms.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TABLE_DOC = REPO_ROOT / "content" / "references" / "risk-config-and-tiers.md"
AGENTS_DIR = REPO_ROOT / "content" / "agents"
TIER_TO_MODEL = {"1": "haiku", "2": "sonnet", "3": "opus"}


def _frontmatter_model(path):
    lines = path.read_text().splitlines()
    assert lines and lines[0].strip() == "---", f"{path.name}: no frontmatter block"
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep and key.strip() == "model":
            return value.strip()
    raise AssertionError(f"{path.name}: frontmatter has no model: key")


def _table_rows():
    lines = TABLE_DOC.read_text().splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("| Agent | Default tier |")),
        None,
    )
    assert start is not None, "Role-default tier table header not found"
    rows = {}
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows[cells[0]] = (cells[1], cells[2])
    assert rows, "Role-default tier table has no rows"
    return rows


def test_table_matches_frontmatter():
    rows = _table_rows()
    agents = {p.stem: p for p in AGENTS_DIR.glob("*.md")}
    assert set(rows) == set(agents), (
        f"table-only: {sorted(set(rows) - set(agents))}; "
        f"frontmatter-only: {sorted(set(agents) - set(rows))}"
    )
    for name, (_, model) in rows.items():
        actual = _frontmatter_model(agents[name])
        assert model == actual, f"{name}: table says {model}, frontmatter says {actual}"


def test_tier_model_mapping():
    for name, (tier, model) in _table_rows().items():
        assert TIER_TO_MODEL.get(tier) == model, f"{name}: tier {tier} does not map to {model}"
