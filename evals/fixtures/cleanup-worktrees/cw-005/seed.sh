#!/usr/bin/env bash
# cw-005 seed: unknown-shape branch that should be preserved.
set -euo pipefail

git init -q -b main
git config user.email "test@example.com"
git config user.name "Test"
git add -A
git commit -q -m "seed: baseline"

WTS="$HOME/wts"
mkdir -p "$WTS"

git branch experiment/spike-xyz
git worktree add -q "$WTS/wt-spike" experiment/spike-xyz

mkdir -p "$HOME/bin"
cat > "$HOME/bin/gh" <<'GH'
#!/usr/bin/env bash
echo '[]'
GH
chmod +x "$HOME/bin/gh"
