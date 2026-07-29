#!/usr/bin/env bash
# Purpose: Mechanically enforce, on every future commit rather than once at
#          review time, that the DS-108 tasks.jsonl cross-session fix stays
#          complete: no sole-writer vocabulary survives on a tasks.jsonl
#          referent, the task-state fold is defined AND cited at every reader
#          file, every counting reader (shell and prose) dedupes by task_id,
#          the retired concept name is gone, the status-sync enum
#          misattribution is corrected, and the row-7 ownership warning is
#          present.
#
# Public API: executable shell gate. Exit 0 = all gates pass; exit 1 = at least
#             one gate failed; exit 2 = repo root could not be resolved (never
#             a silent vacuous pass). Honors GATE_REPO to override the root.
#
# Upstream deps: content/commands/ds-implement-ticket.md,
#                content/commands/ds-ticket-status-sync.md,
#                content/commands/ds-wrap.md,
#                content/references/task-state-file.md,
#                content/references/ticket-rework.md,
#                content/sections/08-task-state-file.md; `git grep` (BRE/ERE
#                only - see PATTERN HAZARD below).
#
# Downstream consumers: .github/workflows/bin-tests.yml (glob-discovered by
#                       `files=(bin/tests/test_*.sh)`, run as `bash "$f"`).
#
# Failure modes: run from an unresolvable root -> exit 2 (guard below), NOT a
#                vacuous pass. Under zsh, an unquoted multi-path variable does
#                NOT word-split; every pathspec here is passed as separate
#                quoted arguments for that reason. mktemp -d scratch is removed
#                by an EXIT trap.
#
# Performance: Standard (about fifteen `git grep` passes over content/; no network).
#
# BANNED LITERAL - the phrase `no lock protocol is needed` is banned outright in
#   content/references/task-state-file.md and content/sections/08-task-state-file.md,
#   not merely banned-with-a-false-premise. SW below matches it as a literal, so a
#   semantically correct rewrite that KEEPS the phrase and corrects only its
#   premise still FAILS G1a. Sanctioned replacement wording:
#   "No lock is needed because no writer ever rewrites the file."
#   Same rule for `sole writer` / `sole-writer` in those two files: G1a admits no
#   qualifier there (G1b's `across agents` carve-out is deliberately NOT extended
#   to the canonical spec - see AC2).
#
# THRESHOLD DESIGN - READ BEFORE TOUCHING ONE.
#   Floors sit only on quantities this change does NOT reduce: L_REF (stable),
#   FOLD (per-file, grows 0->N), G4's positive floor (0->1), G4b's positive
#   floor (stable at 2). The sole-writer count is what the change SHRINKS and is
#   deliberately NOT floored.
#   The FOLD floor is PER FILE, not a global sum. A global sum over a 13-site
#   rename is satisfiable by concentrating every mention in one file: a tree with
#   zero per-reader citations in ds-implement-ticket.md, ticket-rework.md and
#   ds-wrap.md measured FOLD=9 and scored 10/0 against a global `>= 6` floor.
#   Do NOT collapse these back into one sum, and do NOT lower a per-file entry:
#   each entry equals the number of R-sites in that file that the plan requires
#   to cite the fold by name.
#   There is NO CAP here. A prior revision capped `across agents` at 14 - a cap
#   on a quantity the change GROWS, the mirror of the floor hazard. It could
#   only false-FAIL a thorough correct implementation. Do not reintroduce it.
#   Blanket-marking is stopped by FOLD/G1a/G2/G4/G4b/G5/G6, all orthogonal to marking.
# PATTERN HAZARD: `git grep -E` does NOT support `\b`. No pattern here uses it.
# BARE-GREP HAZARD: every grep writes to a file whose emptiness is tested.
# SHELL HAZARD: this file is run as `bash "$f"` by CI, but is also run by hand
#   under zsh. zsh does not word-split unquoted parameter expansions, so a
#   `-- $CANON` pathspec would collapse to ONE nonexistent path, git would exit
#   1, and `|| true` would swallow it - a silently vacuous gate. Pass each path
#   as its own quoted argument. Do NOT use `mapfile`: bash 3.2 lacks it. The
#   per-file FOLD loop is fed by a HEREDOC, never a pipe: a piped `while read`
#   runs in a subshell under bash and the PASS/FAIL counters would be discarded.
set -uo pipefail
REPO_DIR="${GATE_REPO:-$(cd "$(dirname "$0")/../.." 2>/dev/null && pwd)}"
cd "$REPO_DIR" 2>/dev/null || { echo "FATAL: cannot cd to '$REPO_DIR'" >&2; exit 2; }
# ROOT GUARD: without this, a bad GATE_REPO or an invocation from outside
# bin/tests/ yields L_REF=0/S1=0 and vacuously PASSES G1a/G1b/G2/G4/G5. The
# floors would catch it, but only after reporting a misleading diagnostic.
if ! git rev-parse --show-toplevel >/dev/null 2>&1 \
   || [ ! -f content/references/task-state-file.md ] \
   || [ ! -f content/commands/ds-implement-ticket.md ]; then
  echo "FATAL: '$REPO_DIR' is not a DinoStack repo root (expected content/references/task-state-file.md and content/commands/ds-implement-ticket.md). Set GATE_REPO." >&2
  exit 2
fi
PASS=0; FAIL=0
_pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
_fail() { echo "FAIL: $1" >&2; FAIL=$((FAIL + 1)); }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
SW='sole.writer|sole writer|no lock protocol is needed'
CANON1=content/references/task-state-file.md
CANON2=content/sections/08-task-state-file.md
DIT=content/commands/ds-implement-ticket.md
SS=content/commands/ds-ticket-status-sync.md
TRW=content/references/ticket-rework.md
WRAP=content/commands/ds-wrap.md

L_REF="$(git grep -ciE 'tasks\.jsonl' -- content 2>/dev/null | awk -F: '{s+=$2} END{print s+0}')"
if [ "${L_REF:-0}" -ge 55 ]; then _pass "L_REF floor: $L_REF (>= 55)"
else _fail "FLOOR FAIL: L_REF=$L_REF (<55) - referent lens vacuous. Do NOT lower."; fi

# FOLD: PER-FILE floors, one entry per reader file, each equal to the number of
# R-sites in that file the plan requires to cite the fold by name. NOT a global sum.
FOLDSUM=0; FOLDBAD=""
while IFS=: read -r ff nn; do
  [ -n "$ff" ] || continue
  c="$(git grep -ciE 'task-state fold' -- "$ff" 2>/dev/null | awk -F: '{s+=$2} END{print s+0}')"
  FOLDSUM=$((FOLDSUM + c))
  if [ "$c" -lt "$nn" ]; then FOLDBAD="$FOLDBAD $ff($c/$nn)"; fi
done <<'FOLDSPEC'
content/commands/ds-implement-ticket.md:7
content/references/task-state-file.md:3
content/commands/ds-ticket-status-sync.md:2
content/references/ticket-rework.md:1
content/commands/ds-wrap.md:1
FOLDSPEC
if [ -z "$FOLDBAD" ]; then _pass "FOLD per-file floors: all 5 reader files at or above their R-site counts (sum=$FOLDSUM)"
else _fail "FLOOR FAIL: 'task-state fold' citations below the per-file R-site floor:$FOLDBAD - a global sum would have passed this. Do NOT lower, do NOT collapse into a sum."; fi

# G1a: FILE-scoped - catches the :32-33 phrase split a line grep misses.
git grep -niE "$SW" -- "$CANON1" "$CANON2" > "$TMP/g1a" 2>/dev/null || true
if [ -s "$TMP/g1a" ]; then _fail "G1a FAIL - sole-writer vocabulary survives in canonical task-state spec (see BANNED LITERAL in the header):"; cat "$TMP/g1a" >&2
else _pass "G1a: canonical task-state spec is free of sole-writer vocabulary"; fi

git grep -niE 'tasks\.jsonl|task-state file|task file' -- content 2>/dev/null > "$TMP/s1" || true
S1="$(grep -c . "$TMP/s1" 2>/dev/null || true)"; [ -n "$S1" ] || S1=0
if [ "$S1" -ge 40 ]; then _pass "G1b stage floor: $S1 tasks-scoped lines (>= 40)"
else _fail "FLOOR FAIL: G1b stage-1 matched $S1 (<40) - pattern vacuous."; fi
grep -Ei "$SW" "$TMP/s1" 2>/dev/null | grep -vi 'across agents' \
  | grep -vE '^content/references/task-state-file\.md:|^content/sections/08-task-state-file\.md:' > "$TMP/g1b" || true
if [ -s "$TMP/g1b" ]; then _fail "G1b FAIL - unqualified sole-writer claim(s) on tasks.jsonl:"; cat "$TMP/g1b" >&2
else _pass "G1b: every remaining tasks-scoped sole-writer claim is qualified 'across agents'"; fi

# G2: the CONCEPT NAME, not just the parenthetical. Lens 3 is file-scoped
# because task-state-file.md:16-17 splits the phrase across the line break.
git grep -niE 'P1 design' -- content > "$TMP/g2a" 2>/dev/null || true
git grep -niE 'field-level merge algorithm' -- content > "$TMP/g2b" 2>/dev/null || true
git grep -niE 'merge algorithm' -- "$CANON1" "$CANON2" > "$TMP/g2c" 2>/dev/null || true
cat "$TMP/g2a" "$TMP/g2b" "$TMP/g2c" 2>/dev/null | sort -u > "$TMP/g2" || true
if [ -s "$TMP/g2" ]; then _fail "G2 FAIL - the retired merge-algorithm name survives (dangling after rename):"; cat "$TMP/g2" >&2
else _pass "G2: no surviving 'P1 design' / 'field-level merge algorithm' reference"; fi

# G4 POSITIVE floor (0->1): if a reflow separates the path literal from the
# dedupe, THIS fails loudly rather than the emptiness gate going silently vacuous.
G4DEDUP="$(git grep -nE 'tasks\.jsonl' -- "$DIT" 2>/dev/null | grep -c 'sort -u' || true)"; [ -n "$G4DEDUP" ] || G4DEDUP=0
if [ "$G4DEDUP" -ge 1 ]; then _pass "G4 positive floor: $G4DEDUP tasks.jsonl line(s) carry 'sort -u' (>= 1)"
else _fail "FLOOR FAIL: no tasks.jsonl line carries 'sort -u' - the dedupe is absent, or a reflow split it from the path literal. Do NOT lower."; fi
git grep -nE 'tasks\.jsonl' -- "$DIT" 2>/dev/null | grep -E 'grep -c' | grep -v 'sort -u' > "$TMP/g4" || true
if [ -s "$TMP/g4" ]; then _fail "G4 FAIL - counting reader of tasks.jsonl without 'sort -u' task_id dedupe:"; cat "$TMP/g4" >&2
else _pass "G4: every counting reader of tasks.jsonl dedupes by task_id"; fi

# G4b: the PROSE counting readers (R8 ds-implement-ticket.md, R9 ticket-rework.md).
# G4 only sees lines carrying both `tasks.jsonl` and `grep -c`, and is $DIT-scoped,
# so both prose sites sat outside every gate before r4.
git grep -niE 'tasks\.jsonl' -- "$DIT" "$TRW" 2>/dev/null | grep -Ei 'count of|counts of|number of' > "$TMP/g4ball" || true
G4BALL="$(grep -c . "$TMP/g4ball" 2>/dev/null || true)"; [ -n "$G4BALL" ] || G4BALL=0
if [ "$G4BALL" -ge 2 ]; then _pass "G4b positive floor: $G4BALL prose counting-reader line(s) (>= 2)"
else _fail "FLOOR FAIL: G4b matched $G4BALL prose counting-reader line(s) (<2) - R8/R9 were reworded past the lens. Re-anchor the pattern; do NOT lower."; fi
grep -vi 'distinct' "$TMP/g4ball" > "$TMP/g4b" || true
if [ -s "$TMP/g4b" ]; then _fail "G4b FAIL - prose counting reader of tasks.jsonl that does not say 'distinct':"; cat "$TMP/g4b" >&2
else _pass "G4b: R8/R9 prose counting readers count DISTINCT task_ids"; fi

# G5 (OQ1): scoped to status-sync ONLY. The identical enum at
# ds-implement-ticket.md:218/900 is batch-state.json's tickets[] and is CORRECT.
git grep -niE 'skipped_already_merged|\| complete \|' -- "$SS" > "$TMP/g5" 2>/dev/null || true
if [ -s "$TMP/g5" ]; then _fail "G5 FAIL - the batch-state tickets[] enum is still pasted onto the tasks.jsonl lookup (OQ1):"; cat "$TMP/g5" >&2
else _pass "G5: status-sync reads the tasks.jsonl writer enum, not the batch-state one"; fi

# G6: row 7's warning is specified verbatim in 3.3, so it IS gateable.
G6="$(git grep -cE 'is in_progress under another session' -- "$DIT" 2>/dev/null | cut -d: -f2)"; [ -n "$G6" ] || G6=0
if [ "$G6" -ge 1 ]; then _pass "G6: row-7 foreign-ownership warning present ($G6)"
else _fail "G6 FAIL: row-7 foreign-ownership warning absent - the ownership gate has no operator-visible output."; fi

echo; echo "Results: $PASS passed, $FAIL failed (L_REF=$L_REF FOLDsum=$FOLDSUM S1=$S1 G4dedup=$G4DEDUP G4b=$G4BALL)"
[ "$FAIL" -gt 0 ] && exit 1; exit 0
