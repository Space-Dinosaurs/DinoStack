# it-002-report

agentic-engineering: opt-in

## Stack
- Python 3.11
- pytest

## Conventions
- Branch naming: fix/<slug> for bug fixes, feat/<slug> for new features
- Conventional-commit prefixes (feat, fix, refactor, test, docs)

## Project config
- BASE_BRANCH: main
- QUALITY_CMD: python -m pytest -q && python -c "import report"
