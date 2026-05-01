> Note: References to "agent-methodology.md" in this historical doc refer to what is now METHODOLOGY.md (assembled from content/sections/). See content/sections/README.md.

<!--
Purpose: Handoff document for Path 1 adapter-restructure project. Captures
         architectural rationale, post-Wave-1 state, known regressions on main,
         and concrete unit specs for Wave 1.5 + Wave 2 so a fresh session can
         pick up the work without re-deriving the rev3 architect plan.

Public API: This is a planning artifact, not code. The "API" is the unit list
            in §Wave 1.5 and §Wave 2 - those are binding work contracts for
            the next architect/engineer spawns.

Upstream deps: content/sections/README.md (binding layout contract),
               scripts/build-methodology.sh, scripts/check-methodology-drift.sh,
               PR #23 (Wave 1 merge), docs/planning/p0-gemini-adapter.md.

Downstream consumers: Future conductor sessions resuming Path 1; architects
                      spawned to plan Wave 1.5 / Wave 2; engineers executing
                      the unit list.

Failure modes: Document drift. If Wave 1.5 or Wave 2 ships and this file is not
               updated, subsequent readers will execute against a stale plan.
               Update or delete this file the moment Wave 2 merges.

Performance: N/A (static planning artifact).
-->

# Path 1 Adapter Restructure - Handoff Doc

**Status:** Wave 1 merged 2026-04-30 (PR [#23](https://github.com/Solara6/agentic-engineering/pull/23)). Wave 1.5 and Wave 2 deferred. This document is the resume point.

**Audience:** A fresh session picking up Path 1 with no prior context. Read this first, then `content/sections/README.md`, then choose Wave 1.5 or Wave 2.

---

## 1. Status as of Wave 1 merge

**Shipped in PR #23 (`feat!: split agent-methodology.md into composable sections (Wave 1)`):**

- `content/sections/` — 10 numbered section files (`01-activation-preflight.md` through `10-protocol-details.md`) plus `README.md` (the binding layout contract).
- `scripts/build-methodology.sh` — assembles `content/sections/*.md` into a single `METHODOLOGY.md` artifact for adapters that cannot use `@`-includes.
- `scripts/check-methodology-drift.sh` — CI gate; exits non-zero if the assembled output drifts from the committed canonical file.
- The legacy `content/rules/agent-methodology.md` was DELETED in PR #23. Adapters that still cat it (see §3) are broken on `main`.
- `.claude/` adapter has been migrated: it now uses `@`-includes against `content/sections/` directly. This is the only adapter that supports `@`-includes.

**On `main` right now:**

- `content/sections/` is the canonical source.
- `.claude/` is the only fully migrated adapter.
- 7 other adapters (`.codex`, `.cursor`, `.gemini`, `.kimi`, `.opencode`, plus any others) still expect a flattened body. They use `cat`-flatten via their own `build.sh`. Three of them are broken; see §3.

**Tooling that exists:**

- `scripts/build-methodology.sh` — call this from any non-Claude adapter's `build.sh` to produce the flattened body.
- `scripts/check-methodology-drift.sh` — wired into CI.
- `content/sections/README.md` — the layout contract. Section ordering, anchor scheme, and add-section protocol live here. Treat it as binding.

---

## 2. Path 1 architectural rationale

**Why Path 1 (collapse adapter accretion onto a `content/`-canonical source) and not the alternatives:**

We considered four paths: (a) cleanup-in-place (keep the giant `agent-methodology.md`, just trim), (b) MCP-served methodology (move the body behind an MCP server), (c) drop multi-harness support (Claude-only), (d) Path 1 (split into composable sections, assemble per-adapter at build time). We picked Path 1 because it is the only option that simultaneously preserves multi-harness support, eliminates hand-maintained body assembly, and gives us a CI gate against drift.

**Critical facts a fresh session must internalize:**

- **`@`-include support is Claude-only.** The other 7 adapters do not have a working include directive. Cat-flatten via `build-methodology.sh` is the assembly mechanism for them and stays.
- **Honest reduction is ~25-30%, NOT the rev1 fantasy 78%.** An earlier rev1 plan claimed 78% LOC reduction. That number was wrong - it counted savings only on Claude and ignored the cat-flattened bodies of the other adapters. The real headline number is ~25-30% across the whole repo. Plan against that, not the inflated number.
- **Real wins** (the things that justify the work):
  - Composable per-section authoring (edit one of the 10 sections without touching the others).
  - Drift CI gate (`check-methodology-drift.sh`) catches divergence between assembled output and canonical source.
  - SKILL.md dedup target (Wave 2 Unit 2-9): per-adapter SKILL.md bodies become hardlinks to a single `content/SKILL.md`.
  - §-anchor cross-refs replace fragile line-number citations.
  - Eliminated hand-maintained body assembly: every adapter's `build.sh` calls one shared script.
- **TOML converter extraction is OUT of scope.** `.codex/build.sh` contains TOML conversion logic; that stays in this restructure. Extracting it is a separate refactor and must not be bundled into Wave 2.

---

## 3. Known Wave 1 regressions on main

The Skeptic for PR #23 confirmed three adapter scripts on `main` reference the deleted `content/rules/agent-methodology.md`. They are broken until Wave 2 lands. **Do not run their build scripts** until the corresponding Wave 2 unit ships.

| File | Approx line | Symptom |
|---|---|---|
| `.gemini/build.sh` | ~55 | `cat content/rules/agent-methodology.md` against deleted path |
| `.kimi/build.sh` | ~32 | Same `cat` against deleted path |
| `.opencode/install.sh` | ~322 | References deleted path during install |

Wave 2 Units 2-2, 2-7, and 2-8 fix these respectively. Until they merge, the only adapter buildable from `main` is `.claude`.

---

## 4. Wave 1.5 spec — rename cascade

**Shape:** single atomic PR, single Engineer, mechanical rewrite. No architectural decisions.

**Scope:** Rename `agent-methodology` → `METHODOLOGY` across approximately 130 occurrences in 8 paths:

- `content/`
- `.claude/commands/`
- `.codex/commands/`
- `.cursor/commands/`
- `README.md`
- `ADAPTERS.md`
- `update.sh`
- Historical-doc footnote-only treatment for `docs/research/` and `docs/planning/p*-*.md` (do NOT do a wholesale rename in these; add a footnote at the top of any file that references the old name explaining the rename).

**Reference format rewrite rules** (apply mechanically, in this order):

1. `agent-methodology.md` (whole-file reference, no anchor) → `METHODOLOGY.md`
2. `agent-methodology.md#<anchor>` (anchor reference) → `METHODOLOGY.md §<heading>` — convert URL-anchor to section-anchor citation. Heading text comes from the section title in `content/sections/`.
3. Path references: `~/.claude/skills/agentic-engineering/rules/agent-methodology.md` → `~/.claude/skills/agentic-engineering/METHODOLOGY.md`. **Drop the `rules/` segment** — the assembled `METHODOLOGY.md` lives at the skill root, not under `rules/`.

**Special case — `content/commands/representation-audit.md` calibration specimens.** Lines 43, 49, 55, 57, 63, 69, 75, 81, 93 in the old file cite `agent-methodology.md line N` or `lines N-M`. These line-number citations are now stale (the file is gone). Rewrite each to a §-anchor citation per the canonical scheme in `content/sections/README.md`. A practical recipe for the engineer:

```bash
grep -n 'agent-methodology.md line' content/commands/representation-audit.md
grep -n 'lines [0-9]' content/commands/representation-audit.md
```

For each match, locate the corresponding section in `content/sections/` and rewrite the citation as `METHODOLOGY.md §<section-heading>`. The concrete per-line rewrites from the rev3 architect plan are inlined below (verify against the actual current line in `representation-audit.md` before editing - line numbers may have shifted slightly):

| Old (line N in `representation-audit.md`) | Rewrite |
|---|---|
| Line ~43: `agent-methodology.md line 106, the Low signals block` | `METHODOLOGY.md §Risk Classification > Low signals` |
| Line ~49: `agent-methodology.md line 106` ... `lines 19-49` | `METHODOLOGY.md §Risk Classification > Low signals` and `METHODOLOGY.md §Delegation > spawn-threshold table` |
| Line ~55: `skeptic-protocol.md Section 2 Step-by-step (lines ~93-140)` | `skeptic-protocol.md §Section 2 (Step-by-step)` (in protocol file, not methodology - included for §-format consistency) |
| Line ~57: `agent-methodology.md` ... `lines ~79-83` | `METHODOLOGY.md §Delegation > Worker preamble` (Execution Contract template lives there) |
| Line ~63: `agent-methodology/subagent-protocol.md` | unchanged - this references a directory name that does not change. Verify against the current line; if the citation does reference the old `agent-methodology` directory name, it stays. |
| Line ~69: `skeptic-protocol.md lines 27-35, the Low risk definition` | `skeptic-protocol.md §Risk Classification (Skeptic) > Low risk` |
| Line ~75: `agent-methodology.md lines 27-29 and 106` | `METHODOLOGY.md §Delegation > spawn-threshold table` and `METHODOLOGY.md §Risk Classification > Low signals` |
| Line ~81: `agent-methodology.md line 29` | `METHODOLOGY.md §Delegation > spawn-threshold table > file-renaming row` |
| Line ~93: `agent-methodology.md` ... `around lines 79-83` | `METHODOLOGY.md §Delegation > Worker preamble (Execution Contract template)` |

The Skeptic for Wave 1.5 must verify each rewritten citation actually points at content that exists at the cited section in `METHODOLOGY.md` (which is the assembled output of `content/sections/`). The `representation-audit` calibration is load-bearing - a citation that points at non-existent content silently degrades R1-R7 signal definitions.

**Validation gate** (the engineer must run this before opening the PR):

```bash
grep -rn 'agent-methodology' \
  content/ .claude/commands/ .codex/commands/ .cursor/commands/ \
  README.md ADAPTERS.md update.sh
```

Expected: zero matches. Historical docs (`docs/research/`, `docs/planning/p*-*.md`) are excluded from the gate; they retain their original references with a footnote noting the rename.

**Why Wave 1.5 first:** Wave 2 will surface adapter-side references that Wave 1.5 catches. Doing rename second forces Wave 2 to re-scope mid-flight.

---

## 5. Wave 2 spec — adapter migrations

**Shape:** single atomic PR, 9 units total. 8 parallel + 1 sequential composition step. Each parallel unit gets its own Engineer + per-unit Skeptic. The composition unit runs after all parallel units land.

**Per-unit Skeptic strategy:** `per-unit` for the 8 parallel units (each has small scope, high signal). Composition unit (2-10) gets one integration Skeptic on the merged diff.

### Parallel units (run concurrently)

| Unit | File | Action | Target |
|---|---|---|---|
| 2-1 | `.codex/build.sh` | Replace AGENTS.md assembly block with call to `scripts/build-methodology.sh` | ~290 LOC honest target (TOML converter stays) |
| 2-2 | `.gemini/build.sh` | Migrate off deleted path. **First read `docs/planning/p0-gemini-adapter.md`** — Gemini adapter may be partially staging, in which case this is new-file creation rather than migration. | TBD per p0-gemini-adapter.md |
| 2-3 | `.cursor/build.sh` | Add section-assembly step | ~60 LOC |
| 2-4 | `.codex/install.sh` | Apply symlink rewrite contract (§6) for `rules`→`sections` migration | — |
| 2-5 | `.cursor/install.sh` | Same as 2-4 | — |
| 2-6 | `.gemini/install.sh` | Same as 2-4 (or new-file creation if Gemini is staging) | — |
| 2-7 | `.kimi/build.sh` | **NEW from prior Skeptic catch.** Migrate to use `scripts/build-methodology.sh` instead of `cat content/rules/agent-methodology.md` | — |
| 2-8 | `.opencode/install.sh` | **NEW from prior Skeptic catch.** Migrate off the deleted path | — |

### Sequential units (run after parallel land)

| Unit | Action |
|---|---|
| 2-9 | SKILL.md dedup. Move common body to `content/SKILL.md`; replace per-adapter SKILL.md files with hardlinks. **Confirm before splitting** whether each adapter still needs adapter-specific frontmatter. Per rev3: body is dedup target; frontmatter is small and per-adapter. |
| 2-10 | Shared-file composition. Edit `update.sh`, `README.md`, `ADAPTERS.md` to reflect new layout. **The 8 parallel workers are explicitly forbidden from editing these 3 files.** They are the integration-Skeptic surface. |

### Wave 2 acceptance criteria

- All build scripts produce **byte-identical methodology output** to the Wave-1 baseline.
- CI line-count gates pass (`check-methodology-drift.sh` exits 0 for every adapter).
- Merge gated on every per-unit Skeptic signing off, plus the composition Skeptic on the integrated diff.

---

## 6. Symlink rewrite contract for `update.sh`

This is the binding 5-case spec from the rev3 architect plan. It applies to Unit 2-4 and any other `install.sh` that does the `rules`→`sections` symlink rewrite.

| Case | Pre-state | Action |
|---|---|---|
| 1 | `sections` exists, `rules` absent | Already migrated. No action. |
| 2 | `rules` is a symlink, `sections` absent | `unlink rules`; create new `sections` symlink. |
| 3 | `rules` is a real directory (legacy install) | Backup to `rules.bak.<timestamp>`; create new `sections` symlink. |
| 4 | Both `rules` and `sections` exist | **ABORT non-zero** with a manual-intervention message. Do not auto-resolve. |
| 5 | Neither exists | Clean install. Create new `sections` symlink only. |

Engineers implementing 2-4/2-5/2-6 must implement all five cases. Skeptic must confirm all five branches are covered before sign-off.

---

## 7. Open decisions

**None blocking.** Two confirm-before-execute items:

1. **Unit 2-2 (Gemini adapter):** Read `docs/planning/p0-gemini-adapter.md` before assuming the adapter shape. Gemini may still be staging; if there is conflict between this handoff and the p0 plan, escalate to the human rather than picking one.
2. **Unit 2-9 (SKILL.md dedup):** Confirm whether each adapter still needs adapter-specific frontmatter (Claude vs Codex vs Cursor differ in frontmatter conventions). Per rev3, body is dedup target; frontmatter stays per-adapter. Confirm with a quick read of each existing SKILL.md before splitting.

---

## 8. Cross-references

- **PR #23 (Wave 1 merge):** https://github.com/Solara6/agentic-engineering/pull/23
- **Layout contract (binding):** `content/sections/README.md`
- **Assembly script:** `scripts/build-methodology.sh`
- **CI drift gate:** `scripts/check-methodology-drift.sh`
- **Gemini adapter context:** `docs/planning/p0-gemini-adapter.md`

---

## 9. What a fresh session should do first

5-step entry recipe:

1. **Open** at `/Users/tyson/Documents/Development/ai-tools/agentic-engineering/`.
2. **Read** this handoff doc + `content/sections/README.md`. Do not skim - the layout contract is binding for both waves.
3. **Verify Wave 1 baseline holds:** `bash scripts/check-methodology-drift.sh` must exit 0. If it does not, stop and investigate before doing any new work.
4. **Pick Wave 1.5 OR Wave 2.** Recommend Wave 1.5 first - Wave 2 will likely surface refs that Wave 1.5 didn't catch and force a mid-flight re-scope. Wave 1.5 is mechanical and short; doing it first de-risks Wave 2.
5. **Spawn** an architect-or-engineer per the spec in §4 or §5. The design is locked; the implementation is mechanical. For Wave 1.5: single Engineer is sufficient (rename cascade, validation grep gate). For Wave 2: orchestration-planner first, then 8 parallel Engineers + composition Engineer, with per-unit Skeptics and one integration Skeptic.

---

## Appendix - quick fact sheet

- Path 1, not Path 0/2/3.
- Honest reduction ~25-30%. Not 78%.
- `@`-includes are Claude-only.
- TOML converter stays in `.codex/build.sh`.
- 3 files broken on main: `.gemini/build.sh`, `.kimi/build.sh`, `.opencode/install.sh`.
- 9 Wave 2 units (8 parallel + 1 composition).
- Symlink rewrite has 5 cases; case 4 aborts.
- Don't edit `update.sh` / `README.md` / `ADAPTERS.md` from a parallel unit - those are composition-unit territory.
