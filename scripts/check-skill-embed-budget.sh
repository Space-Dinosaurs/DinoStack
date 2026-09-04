#!/usr/bin/env bash
# Purpose: Two-sided guard on the generated .claude/skills/dinostack/
#          SKILL.md - the artifact Claude Code injects verbatim into context
#          when the /dinostack skill is invoked, post-DS-143
#          (trigger-loaded methodology). Three failure classes:
#            - EMBED INCOMPLETE: a whole content/sections/*.md or
#              content/rules/*.md source file silently dropped from
#              assembly (a bad exclusion pattern, a broken loop, etc.). This
#              can land well inside the FLOOR..CEILING byte band undetected
#              by size alone - verified live: excluding
#              content/rules/code-standards.md from the embed loop rebuilds
#              a SKILL.md that still measures inside the band and exits 0
#              without this check. Also covers an outright add/remove of a
#              source file via pinned EXPECTED_SECTION_COUNT/
#              EXPECTED_RULES_COUNT constants (see their own comment below
#              for why a pinned count, not a re-derived one, is required).
#            - FLOOR: catches a regression to a pointer-only skill body (the
#              embed step in .claude/build.sh silently breaking and no
#              longer inlining METHODOLOGY.md/conventions.md/code-standards.md
#              into SKILL.md). Would otherwise be invisible - a pointer-only
#              skill still builds, still passes adapter-sync, and only fails
#              at runtime when an agent needs content that never loaded.
#            - CEILING: intended as a safety boundary, not a tidiness
#              budget. Its arithmetic origin was never anchored to a swept
#              injection measurement (DS-45 finding - see the CEILING
#              constant's own comment below for the full provenance), but
#              the value itself, 145,000 B, IS now confirmed to load intact
#              via a real swept measurement on 2026-09-03 (DS-45 sweep,
#              see below) - do not treat a future CEILING bump as routine
#              housekeeping regardless: raising it without a new swept
#              injection measurement re-opens the exact risk this gate
#              exists to close.
#
# Public API: bash scripts/check-skill-embed-budget.sh
#             Exits 0 when the embed-completeness check passes AND
#             FLOOR <= size <= CEILING. Exits 1 otherwise, or when a
#             required input is missing. DS-182 added an informational
#             "burn" line (git-based, vs the resolved base ref) to the
#             THREE FLOOR/CEILING exit paths (OK, BELOW FLOOR, and ABOVE
#             CEILING alike) - it is computed once, after the
#             embed-completeness check, so the six earlier "embed
#             incomplete" exit 1 paths do NOT print it (see Failure modes
#             below for the full list). Purely descriptive, it never
#             affects the exit code and
#             renders a "burn: SKIPPED (...)" line (never a blank line,
#             never a failure) when git or a base ref is unavailable. No
#             delta axis here, deliberately: unlike
#             content/commands/ds-implement-ticket.md (hand-authored - see
#             scripts/check-command-file-budget.sh), SKILL.md is a
#             GENERATED artifact whose size on any given branch reflects
#             upstream churn on `content/**` as much as this PR's own
#             diff, so a hard per-PR delta limit here would fail PRs for
#             bytes they did not write - the exact failure mode DS-182
#             exists to close (KNW-20260818-001).
#
# Upstream deps: .claude/skills/dinostack/SKILL.md (built by
#                .claude/build.sh; this script does not rebuild it - it
#                measures whatever is currently on disk, matching how
#                check-adapter-sync and the runtime skill loader both treat
#                the file as the artifact of record); content/sections/
#                [0-9][0-9]-*.md and content/rules/*.md (excluding
#                module-manifest.md) for the embed-completeness check;
#                scripts/lib/budget-gate.sh (shared repo-dir resolution and
#                byte measurement; budget_burn_line for the informational
#                line printed on every exit path below. The OK-path report
#                is hand-rolled directly in this file, NOT routed through
#                budget_eval - bin/ds-evaluate's _collect_budget_gates
#                stores lines[-1] of stdout as this gate's summary, and
#                that consumer depends on the exact pre-DS-182 wording
#                ("ceiling:"/"headroom to ceiling:"), which budget_eval's
#                shared "threshold:"/"headroom:" labels cannot express).
#                The burn line additionally depends on `git` being on PATH
#                and a resolvable base ref (origin/main or main); it
#                renders a distinct SKIPPED line (never fails, never
#                blank) when either is missing.
#
# Downstream consumers: .github/workflows/resident-budget.yml (the
#                        check-skill-embed-budget job's checkout needs
#                        `fetch-depth: 0` so the burn line can resolve
#                        `origin/main` - a default shallow checkout would
#                        leave that ref unreachable and the line would
#                        render its SKIPPED variant on every CI run; the
#                        sibling check-resident-budget job's checkout is
#                        deliberately left alone, since that gate gained no
#                        git axis); bin/ds-evaluate's _collect_budget_gates
#                        (reads lines[-1] of stdout as this gate's summary
#                        - see the Upstream deps note above on why the
#                        OK-path tail is hand-rolled rather than routed
#                        through budget_eval).
#
# Failure modes: embed incomplete (a source file dropped from assembly, or
#                a file count mismatch against EXPECTED_SECTION_COUNT/
#                EXPECTED_RULES_COUNT) -> exit 1 with a distinct "embed
#                incomplete" message, checked before the FLOOR/CEILING bound
#                check below. Below FLOOR -> exit 1, message explicitly
#                frames this as an embed regression, not a healthy shrink -
#                a passing skill body should never get anywhere near
#                100,000 B smaller by accident. Above CEILING -> exit 1,
#                message reiterates the single-data-point caveat and warns
#                against a routine bump. Missing input file -> exit 1. The
#                burn line is computed once, before any of the three exit
#                paths, and printed on all three - unresolvable git/base
#                (no git, not a work tree, no base ref, path absent at
#                base, or base commit date unreadable) renders a "burn:
#                SKIPPED (...)" line rather than omitting the line
#                entirely; never a failure, never blocks the FLOOR/CEILING
#                result. Read-only; no side effects on the repo.
#
# Detection boundary: the heading-completeness check below proves each
# source file's own top-level heading is PRESENT somewhere in the built
# output - it is a presence check, not a completeness digest, so partial
# corruption or truncation of a section's BODY (heading intact, content
# gutted or duplicated) is only caught if it pushes total bytes outside
# FLOOR..CEILING.
#
# Compatible with both bash and zsh invocation of the containing shell; CI
# always invokes it as `bash scripts/check-skill-embed-budget.sh`, but a
# contributor, reviewer, or this file's own regression test may invoke it
# as `zsh scripts/check-skill-embed-budget.sh` and it must behave
# identically. Avoid the variable names `status` and `path` anywhere in
# this file - both are special/read-only in zsh.

set -euo pipefail

# BASH_SOURCE is unset under zsh - fall back to $0 so SCRIPT_DIR resolves
# correctly under both interpreters instead of collapsing to "//".
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=lib/budget-gate.sh
source "$SCRIPT_DIR/lib/budget-gate.sh"
REPO_DIR="$(budget_repo_dir "$SCRIPT_DIR")"

SKILL_FILE="$REPO_DIR/.claude/skills/dinostack/SKILL.md"

# Floor: catches a regression to a pointer-only skill (the embed step
# silently breaking and SKILL.md no longer inlining the methodology body).
# 100,000 B is far below any realistic embedded size and far above what a
# pointer-only skill would ever measure.
FLOOR=100000

# Ceiling: 145,000 B as of 2026-08-19 (raised from 139,160 B - see the
# "2026-08-19 raise" paragraph at the end of this comment for what that
# raise does and does not establish). The paragraphs immediately below
# describe the now-superseded 139,160 B value's own provenance and are
# kept as the historical arithmetic record; read "CEILING" in them as
# that prior value, not the current one.
#
# What 139,160 B actually was: 126,509 B, a local build measurement of
# .claude/skills/agentic-engineering/SKILL.md (the skill directory's
# pre-rename name; it became dinostack later) taken on the DS-143 branch
# on 2026-08-07 (commit baf0b011bd61f055e6ec685663a1f6e24b8834ce), times
# 1.1 for headroom. 126,509 x 1.1 = 139,159.9, which was written up as
# "rounded down" to 139,160 in the original comment - that description
# was itself wrong; 139,160 is the nearest-integer rounding, not a
# round-down, and the true round-down would be 139,159. Immaterial by one
# byte, but stated accurately here since the previous text asserted the
# wrong operation.
#
# What that value was NOT: it was not derived from, or swept relative to,
# the separate 127,107-byte figure - the harness's empirically-confirmed
# verbatim-injection point. That figure's provenance is not traceable
# through git history to a
# measurement commit naming which build, which session, or which harness
# version produced it (checked via `git log --all -S`) - this is a
# statement about what git history contains, not a claim that no record
# exists anywhere (a gitignored planning doc is, by construction, outside
# what any git-log search could ever find either way). The two figures
# were plainly related in the authoring commit's own framing - c1d7c90c's
# message states CEILING as "~1.1x the measured build at authoring time"
# in one paragraph, and separately, in the next paragraph, that "the
# harness was empirically verified to inject the full SKILL.md body
# verbatim at ~127 KB" - but the arithmetic that actually produced
# 139,160 traces only to the 126,509 B build-size snapshot, never to
# 127,107. So the old CEILING was 1.1x that build-size snapshot (126,509
# B, itself only 598 B below the injection-confirmed figure) - not 1.1x,
# or any swept multiple of, the injection-verified figure itself. It
# ended up roughly 12,053 B above the injection-confirmed point (127,107
# B), and 9,145 B above the largest recorded intact injection on file
# (130,015 B - see below).
#
# What is actually on record, checked 2026-08-18: the largest recorded
# intact injection is 130,015 B (DS-146: canaries present at head and
# tail, no truncation, no performance warning - see
# .agentic/learnings.md KNW-20260811-004 and
# docs/skill-embed-injection-sweep.md). The live payload on main measured
# 138,990 B before DS-204. DS-204 (unit B) flips this adapter's SKILL.md
# embed from the full corpus to the minimal corpus (a generated "Deferred
# at this corpus" pointer block replaces deferred content, with the full
# text still reachable at the unfiltered METHODOLOGY.md sibling) - the new
# measured default is 127,753 B. This is NOT a new injection-verified
# figure - no sweep has been run against it - but it is materially
# favorable versus the prior state: 127,753 B is the first live default on
# record that sits BELOW the 130,015 B largest-recorded-intact-injection
# figure above, rather than above it (138,990 B was 8,975 B over that
# figure; 127,753 B is 2,262 B under it). At the time this paragraph was
# first written, that did not make 127,753 B a verified-safe size on its
# own - only a fresh sweep does that. That sweep has now been run (see the
# 2026-09-03 paragraph below), and confirms CEILING (145,000 B) itself as
# an intact injection point - the largest confirmed point on record is now
# 160,000 B (the sweep's highest tested target), superseding the 130,015 B
# figure above.
#
# 2026-08-19 raise: CEILING moved from 139,160 B to 145,000 B by explicit
# operator decision, to unblock work. At the time, this was not done on
# the basis of a new swept injection measurement - none had been run
# since the 130,015 B figure above - so the raise did not make the gate
# more verified than it was: the prior value was itself unswept and
# arbitrary (1.1x a build-size snapshot, never anchored to an injection
# measurement), so raising it moved an arbitrary number rather than
# spending verified evidence. That gap is closed by the 2026-09-03 sweep
# below, which measured CEILING's own value directly.
#
# 2026-09-03 sweep (DS-45, RUN for the first time): headless `claude -p`
# probe sessions, `--allowedTools "Skill"`, explicit `/dinostack`
# invocation, answer-from-context-only prompts (no file-read tools
# permitted in the probe), each verified by both a tail-canary marker AND
# a sha256 cross-check of the literal pad_block_sha256 value the tail
# block declares (the hash match is the load-bearing evidence over a bare
# marker claim - it is a high-entropy string a model could not plausibly
# guess, so reproducing it correctly evidences the tail block genuinely
# reached context; this is narrower than a full read-and-recompute check
# against the actual file bytes, since the probe model only reports what
# it sees rather than independently counting the pad-line run or
# recomputing the hash itself - see
# docs/skill-embed-injection-sweep.md's Step 3 for the full distinction
# from the canary scheme's stronger, reader-side guarantee). Measured
# intact - tail canary found,
# declared_total_bytes correct, DS-45-SWEEP-END-OF-FILE present, exact
# pad_block_sha256 match - at 140,000 B, 145,000 B, 150,000 B, and
# 160,000 B. Every install was cmp-verified and every probe followed by a
# verified restore; final state confirmed clean (real SKILL.md at
# 138,320 B, zero canaries, clean git status). This confirms CEILING
# (145,000 B) as a genuinely verified-safe injection point - the first
# real measurement this gate has ever had. It does NOT establish that no
# truncation point exists above 160,000 B; do not read this result as
# unlimited headroom, and do not treat it as license to raise CEILING to
# any value. This sweep says nothing about whether raising CEILING is
# warranted. Do not raise CEILING as routine housekeeping when content
# grows: raising it remains a separate operator decision requiring its
# own new swept confirmation that the larger body still loads untruncated
# in the live harness, and say so explicitly in the PR that raises it.
# The reusable procedure for producing that swept confirmation is
# documented at docs/skill-embed-injection-sweep.md (DS-45) - use it
# rather than reconstructing an ad hoc measurement.
CEILING=145000

# EXPECTED_SECTION_COUNT / EXPECTED_RULES_COUNT: pinned counts, ratcheted the
# same way FLOOR/CEILING/THRESHOLD are elsewhere in this repo (see
# scripts/check-resident-budget.sh). Update the same commit that adds,
# removes, or renumbers a content/sections/[0-9][0-9]-*.md file, or
# adds/removes a content/rules/*.md file other than module-manifest.md
# (excluded from the embed by .claude/build.sh, and from this count).
#
# Deliberately a fixed constant, NOT derived from the working tree at check
# time (e.g. re-running the same find/glob build-methodology.sh or
# .claude/build.sh themselves use): deriving the expected count from the
# working tree makes the expected side and the actual side move together,
# so an outright file deletion removes it from both what is expected AND
# what is checked - the loss becomes invisible. A pinned constant closes
# that tautology.
EXPECTED_SECTION_COUNT=12
EXPECTED_RULES_COUNT=2

if [ ! -f "$SKILL_FILE" ]; then
  echo "check-skill-embed-budget.sh: missing file: $SKILL_FILE" >&2
  echo "  Run .claude/build.sh to regenerate it, then re-run this check." >&2
  exit 1
fi

# Embed-completeness check (distinct from the FLOOR/CEILING bound check
# below): a whole embedded source file can go missing from assembly and
# still land inside the FLOOR..CEILING byte band, where the two-sided bound
# check alone cannot see it. A single arbitrary head/tail phrase pair cannot
# detect a dropped file in the middle of either set, so this checks a
# phrase from EVERY file in both sets - each file's own first top-level
# heading, derived dynamically so a renamed file is covered automatically
# without maintaining a hardcoded phrase list here. Shared between the two
# sets (content/sections/[0-9][0-9]-*.md and content/rules/*.md, excluding
# module-manifest.md) via scripts/lib/budget-gate.sh's
# budget_check_embedded_set (DS-183 round 2 (M6) extraction - previously a
# local `_check_embedded_set` function defined here; check-codex-skill-
# budget.sh's own near-verbatim reimplementation of the section-heading half
# now calls this same shared function instead). Output wording is
# UNCHANGED: this file's own "check-skill-embed-budget.sh" caller_label
# reproduces every message this file already printed before the extraction.
ALL_HEADINGS=""
budget_check_embedded_set "check-skill-embed-budget.sh" "$REPO_DIR/content/sections" '[0-9][0-9]-*.md' '' "$EXPECTED_SECTION_COUNT" 'section' 'EXPECTED_SECTION_COUNT' "$SKILL_FILE" ALL_HEADINGS 'SKILL.md' 'FLOOR/CEILING'
budget_check_embedded_set "check-skill-embed-budget.sh" "$REPO_DIR/content/rules" '*.md' 'module-manifest.md' "$EXPECTED_RULES_COUNT" 'rules' 'EXPECTED_RULES_COUNT' "$SKILL_FILE" ALL_HEADINGS 'SKILL.md' 'FLOOR/CEILING'

# Duplicate-heading guard: `grep -qxF "$heading" "$SKILL_FILE"` above matches
# presence ANYWHERE in the built output, not per-file. If two source files
# happened to share the same first top-level heading, dropping ONE of them
# would still find the OTHER's copy of that heading in the output and pass
# - the presence check alone cannot tell which file it matched. Asserting
# uniqueness up front closes this cheaply instead of relying on it staying
# true by chance.
duplicate_headings="$(printf '%s' "$ALL_HEADINGS" | LC_ALL=C sort | LC_ALL=C uniq -d)"
if [ -n "$duplicate_headings" ]; then
  echo "check-skill-embed-budget.sh: embed incomplete" >&2
  echo "  duplicate top-level heading(s) shared across source files - the" >&2
  echo "  presence check above cannot distinguish per-file completeness when" >&2
  echo "  a heading repeats, so it can silently pass with one copy dropped:" >&2
  printf '%s\n' "$duplicate_headings" | while IFS= read -r dup; do
    [ -n "$dup" ] && echo "    $dup" >&2
  done
  echo "  give the affected file(s) a distinct top-level heading." >&2
  exit 1
fi

skill_bytes="$(budget_file_bytes "$SKILL_FILE")"

# Informational burn line (git-based, vs the resolved base ref) - never
# affects the exit code, always renders a line (a "burn: SKIPPED (...)"
# line, never silently omitted, when git or a base ref is unavailable).
# Computed once here, before any of the three exit paths below, so all
# three print it - see scripts/lib/budget-gate.sh's budget_burn_line for
# the full contract, and the header comment above for why this is a burn
# line rather than a hard per-PR delta limit on this generated artifact.
burn_line="$(budget_burn_line "$REPO_DIR" "$SKILL_FILE" "$CEILING" "$skill_bytes")"

if [ "$skill_bytes" -lt "$FLOOR" ]; then
  echo "check-skill-embed-budget.sh: BELOW FLOOR - embed regression, not a" >&2
  echo "  healthy shrink." >&2
  echo "  $SKILL_FILE measured only $skill_bytes B," >&2
  echo "  below the $FLOOR B floor." >&2
  echo "  This almost certainly means the embed step in .claude/build.sh" >&2
  echo "  broke and SKILL.md regressed to a pointer-only body that no" >&2
  echo "  longer inlines the methodology content. Investigate the build" >&2
  echo "  step directly; do not lower FLOOR to make this pass." >&2
  echo "  $burn_line" >&2
  exit 1
fi

if [ "$skill_bytes" -gt "$CEILING" ]; then
  overage=$(( skill_bytes - CEILING ))
  echo "check-skill-embed-budget.sh: ABOVE CEILING." >&2
  echo "  $SKILL_FILE measured $skill_bytes B," >&2
  echo "  above the $CEILING B ceiling ($overage B over)." >&2
  echo "" >&2
  echo "  CEILING is intended as a safety boundary, not a tidiness budget." >&2
  echo "  A 2026-09-03 swept measurement (DS-45) confirmed CEILING itself" >&2
  echo "  (145,000 B) as an intact injection point, up to and including" >&2
  echo "  160,000 B - but that does NOT establish no truncation point" >&2
  echo "  exists above that figure. See the CEILING constant's own" >&2
  echo "  comment above for the full DS-45 provenance and sweep result." >&2
  echo "  Do not raise CEILING as routine housekeeping - only" >&2
  echo "  raise it alongside a new swept confirmation that the larger" >&2
  echo "  body still loads untruncated in the live harness (procedure:" >&2
  echo "  docs/skill-embed-injection-sweep.md), and say so" >&2
  echo "  explicitly in the PR that raises it. Otherwise, trim content." >&2
  echo "  $burn_line" >&2
  exit 1
fi

# OK path deliberately does not route through budget_eval's generic
# "threshold:"/"headroom:" labels: bin/ds-evaluate's _collect_budget_gates
# stores lines[-1] of stdout as this gate's summary, and that consumer
# expects the exact pre-DS-182 wording ("ceiling:"/"headroom to ceiling:")
# - budget_eval's shared labels cannot express that without changing the
# stored summary text for every gate that already depends on it.
echo "skill embed budget check: OK"
echo "  SKILL.md: $skill_bytes B"
echo "  floor:    $FLOOR B"
echo "  ceiling:  $CEILING B"
echo "  $burn_line"
echo "  headroom to ceiling: $(( CEILING - skill_bytes )) B"
exit 0
