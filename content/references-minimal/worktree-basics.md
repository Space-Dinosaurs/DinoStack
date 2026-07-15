# Worktree Isolation (minimal)

Every shippable-edit spawn sets `isolation: worktree`. Conductor removes worktree after PR opens.

## Branch

Engineer branches from `origin/main`:
```
git fetch origin && git worktree add .agentic/worktrees/<branch> -b <branch> origin/main
```

`origin/main`, NOT local `main` (may have unmerged sibling work).

## Commit + PR

- `$QUALITY_CMD` passes with zero errors before commit.
- `git commit -s` if repo enforces DCO.
- `gh pr create` after commit. No AI/Claude attribution in body.

## Cleanup

Conductor removes worktree + branch after merge:
```
git worktree remove .agentic/worktrees/<branch>
git branch -d <branch>
```

## Forbidden

- `git push --force`
- `rm -rf`
- editing `.agentic/`, `docs/planning/`, `.claude/skills/agentic-engineering/` from worker