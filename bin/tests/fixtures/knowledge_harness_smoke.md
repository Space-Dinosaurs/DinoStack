# Knowledge-harness smoke block (test fixture, not methodology prose)

This file exists solely so `bin/tests/test_knowledge_harness_smoke.py` can
prove that a **second** `@harness:`-marked block can be extracted and executed
by `bin/tests/lib/md_shell_extract.py` against the knowledge fixtures in
`bin/tests/lib/git_fixture.py`. It is deliberately NOT under `content/`: it is
throwaway test input, carries no methodology obligation, and must never be
built into an adapter.

The block below is a stand-in shaped like a knowledge-commit block (probe the
remote, classify each knowledge file, stage, commit, push) so the fixtures are
exercised through the same git surface a real block would use. It is not the
real block and nothing depends on its behavior beyond this test module.

```bash
# @harness:knowledge-smoke
set -u

# Q2 probe: $BRANCH_NAME must arrive as a shell ASSIGNMENT, so awk -v sees it
# and awk ENVIRON[] does not.
echo "SMOKE_BRANCH_ASSIGNED=[$BRANCH_NAME]"
echo "SMOKE_AWK_V=[$(awk -v x="$BRANCH_NAME" 'BEGIN{print x}')]"
echo "SMOKE_AWK_ENVIRON=[$(awk 'BEGIN{print ENVIRON["BRANCH_NAME"]}')]"

# Q4 probe: does `s+0` on an EMPTY (but present) file emit "0" or nothing?
EMPTY_PROBE="$REPO/.smoke-empty-probe"
: > "$EMPTY_PROBE"
echo "SMOKE_AWK_EMPTY_FILE=[$(awk '{s += $2} END {print s+0}' "$EMPTY_PROBE")]"

if git -C "$REPO" remote get-url origin >/dev/null 2>&1; then
  echo "SMOKE_HAS_REMOTE=1"
  if git -C "$REPO" fetch -q origin; then
    echo "SMOKE_FETCH=ok"
  else
    echo "SMOKE_FETCH=fail"
  fi
  if git -C "$REPO" rev-parse --verify -q "refs/remotes/origin/$BRANCH_NAME" >/dev/null; then
    echo "SMOKE_REVPARSE=ok"
  else
    echo "SMOKE_REVPARSE=fail"
  fi
else
  echo "SMOKE_HAS_REMOTE=0"
fi

STAGED=0
for f in MEMORY.md decisions.md .agentic/learnings.md; do
  if [ ! -f "$REPO/$f" ]; then
    echo "SMOKE_FILE $f=missing"
    continue
  fi
  if git -C "$REPO" check-ignore -q -- "$f"; then
    echo "SMOKE_FILE $f=ignored"
    continue
  fi
  if git -C "$REPO" cat-file -e "HEAD:$f" 2>/dev/null; then
    # MANDATORY before diff-index: a file rewritten with identical content has
    # a newer mtime than the index records, and `diff-index --quiet` trusts
    # stat data over content outside git's racily-clean window - so it reports
    # an UNCHANGED file as changed. Exits non-zero when entries needed
    # updating, which is not an error here.
    git -C "$REPO" update-index -q --refresh >/dev/null 2>&1 || true
    if git -C "$REPO" diff-index --quiet HEAD -- "$f"; then
      echo "SMOKE_FILE $f=identical"
      continue
    fi
    NUMSTAT=$(git -C "$REPO" diff --numstat HEAD -- "$f")
    ADDED=$(echo "$NUMSTAT" | awk '{print $1+0}')
    DELETED=$(echo "$NUMSTAT" | awk '{print $2+0}')
    echo "SMOKE_FILE $f=modified +$ADDED -$DELETED"
  else
    echo "SMOKE_FILE $f=untracked"
  fi
  git -C "$REPO" add -- "$f"
  STAGED=$((STAGED + 1))
done
echo "SMOKE_STAGED=$STAGED"

if [ "$STAGED" -gt 0 ]; then
  if git -C "$REPO" commit -q -s -m "chore(knowledge): smoke $BRANCH_NAME"; then
    echo "SMOKE_COMMIT=ok"
  else
    echo "SMOKE_COMMIT=fail"
  fi
  if git -C "$REPO" remote get-url origin >/dev/null 2>&1; then
    if git -C "$REPO" push -q origin "HEAD:refs/heads/$BRANCH_NAME"; then
      echo "SMOKE_PUSH=ok"
    else
      echo "SMOKE_PUSH=fail"
    fi
  else
    echo "SMOKE_PUSH=skipped-no-remote"
  fi
fi
```
