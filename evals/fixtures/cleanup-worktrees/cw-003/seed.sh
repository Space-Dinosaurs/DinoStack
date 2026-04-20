#!/usr/bin/env bash
# cw-003 seed: gh CLI broken (below-ceiling graceful-degradation path).
set -euo pipefail

git init -q -b main
git config user.email "test@example.com"
git config user.name "Test"
git add -A
git commit -q -m "seed: baseline"

WTS="$HOME/wts"
mkdir -p "$WTS"

git branch feature/needs-review
git worktree add -q "$WTS/wt-feat-review" feature/needs-review

# Do NOT create a gh stub. Also neutralize any real gh by placing a stub
# on $HOME/bin (first on PATH) that always errors - simulating an
# install that is present but non-functional (exit 127, "not available"
# message to stderr). A reasonable maintainer branches to the
# "gh not available" path when invocation fails.
mkdir -p "$HOME/bin"
cat > "$HOME/bin/gh" <<'GH'
#!/usr/bin/env bash
echo "gh: command not found (eval-stubbed as unavailable)" >&2
exit 127
GH
chmod +x "$HOME/bin/gh"
