#!/usr/bin/env bash
# cw-002 seed: single feature worktree with an OPEN PR.
set -euo pipefail

git init -q -b main
git config user.email "test@example.com"
git config user.name "Test"
git add -A
git commit -q -m "seed: baseline"

WTS="$HOME/wts"
mkdir -p "$WTS"

git branch feature/open-pr
git worktree add -q "$WTS/wt-feat-open" feature/open-pr

mkdir -p "$HOME/bin"
cat > "$HOME/bin/gh" <<'GH'
#!/usr/bin/env bash
args="$*"
branch=""
if [[ "$args" =~ --head[[:space:]]+([^[:space:]]+) ]]; then
  branch="${BASH_REMATCH[1]}"
fi
case "$branch" in
  feature/open-pr)
    echo '[{"number":202,"state":"OPEN","title":"open pr under review"}]'
    ;;
  *)
    echo '[]'
    ;;
esac
GH
chmod +x "$HOME/bin/gh"
