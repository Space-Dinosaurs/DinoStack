#!/usr/bin/env bash
# cw-004 seed: orphaned worktree-agent-* branches with no worktree attached.
# Built by creating worktrees, removing the directories, and then running
# `git worktree prune` so metadata is already clean but the branches
# remain. Step 5 of the command should delete them.
set -euo pipefail

git init -q -b main
git config user.email "test@example.com"
git config user.name "Test"
git add -A
git commit -q -m "seed: baseline"

WTS="$HOME/wts"
mkdir -p "$WTS"

for name in orphan-a orphan-b; do
  git branch "worktree-agent-$name"
  git worktree add -q "$WTS/wt-$name" "worktree-agent-$name"
done

# Now detach: remove the worktree directories AND the gitdir metadata so
# the branches are truly orphaned with no entry in `git worktree list`.
# We call `git worktree remove --force` which deletes the dir AND
# administrative metadata, then manually restore the branches (remove
# deletes them too).
for name in orphan-a orphan-b; do
  git worktree remove -f "$WTS/wt-$name" 2>/dev/null || true
  # Re-create the branch pointing at HEAD so the orphan-branch case is
  # realized.
  git branch "worktree-agent-$name" 2>/dev/null || true
done
git worktree prune

# gh stub: no feature branches in this fixture so stub returns empty.
mkdir -p "$HOME/bin"
cat > "$HOME/bin/gh" <<'GH'
#!/usr/bin/env bash
echo '[]'
GH
chmod +x "$HOME/bin/gh"
