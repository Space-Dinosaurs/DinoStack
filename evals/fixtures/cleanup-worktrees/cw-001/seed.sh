#!/usr/bin/env bash
# cw-001 seed: clean isolation + dirty isolation + merged-PR feature.
# Run with cwd = worktree (the copied repo/ tree); HOME = fake home.
set -euo pipefail

git init -q -b main
git config user.email "test@example.com"
git config user.name "Test"
git add -A
git commit -q -m "seed: baseline"

# Worktree sibling location (all worktrees live under $HOME/wts so isolator
# cleanup removes them when the run finishes).
WTS="$HOME/wts"
mkdir -p "$WTS"

# Branches.
git branch worktree-agent-clean
git branch worktree-agent-dirty
git branch feature/merged-pr

# Attach worktrees.
git worktree add -q "$WTS/wt-clean" worktree-agent-clean
git worktree add -q "$WTS/wt-dirty" worktree-agent-dirty
git worktree add -q "$WTS/wt-feat"  feature/merged-pr

# Make wt-dirty actually dirty by writing an uncommitted file.
echo "uncommitted work in progress" > "$WTS/wt-dirty/scratch.txt"

# gh stub: feature/merged-pr is MERGED. All other branches have no PR.
mkdir -p "$HOME/bin"
cat > "$HOME/bin/gh" <<'GH'
#!/usr/bin/env bash
# Deterministic gh stub. Supports `gh pr list --state all --head <branch> --json ...`.
# Prints JSON arrays; empty for branches not known to be on a PR.
args="$*"
branch=""
if [[ "$args" =~ --head[[:space:]]+([^[:space:]]+) ]]; then
  branch="${BASH_REMATCH[1]}"
fi
case "$branch" in
  feature/merged-pr)
    echo '[{"number":101,"state":"MERGED","title":"merged pr"}]'
    ;;
  *)
    echo '[]'
    ;;
esac
GH
chmod +x "$HOME/bin/gh"
