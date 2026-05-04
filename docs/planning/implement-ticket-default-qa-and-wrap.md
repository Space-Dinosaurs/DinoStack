# Brief: /implement-ticket default-on QA + per-ticket wrap learnings

**Problem:** Two related gaps in `/implement-ticket`. (1) Phase 6b QA gate fires only when a project has `.agentic/qa.md` with trigger patterns matching the diff; greenfield projects (no qa.md yet) skip QA entirely — exactly when meaningful verification is most valuable. The skill is project-level ticket implementation; observable behavior is the norm, not the exception. (2) Each ticket produces durable learnings (architecture decisions, project quirks, gotchas) but those learnings are not captured per-PR — they accumulate only in conversation context and dissipate at session end, so the next ticket's planning starts from poorer context than it should.

**Success criteria:**
- Every Elevated unit runs QA against planning-derived `qa_criteria` unless explicitly skipped via one of 5 valid `qa_skip` enum values.
- qa-engineer reads `qa_criteria` as authoritative test plan; qa.md context is supplemental, never gating.
- Each PR opens triggers a `wrap-ticket` agent that appends durable learnings to `MEMORY.md`, `decisions.md`, and `.agentic/context.md` (append-only; deduped).
- Trivial-path single-ticket invocations remain bit-for-bit identical: no qa_criteria required, no Phase 11b execution.
- Phase 11b never blocks Phase 12 cleanup or PR completion; soft-fails on any error.

**Non-goals:**
- AGENTS.md auto-edits from wrap-ticket. AGENTS.md remains under operator + /wrap control.
- MEMORY.md rotation/aging. Unbounded growth is documented limitation; rotation is future work.
- Replacing existing `/wrap` skill. /wrap remains the on-demand richer session-level summarization tool with Skeptic review; wrap-ticket is a constrained per-PR subset.
- Auto-derived qa_criteria for tickets that lack it. Architect MUST emit it for Elevated; absence is a Critical Skeptic finding on the architect plan.

**Constraints:**
- Conductor remains sole writer of `.agentic/{tasks.jsonl, loop-state.json, batch-state.json}`. Stop hook is sanctioned exception for interrupted-status writes.
- Phase 11b wrap-ticket is the **automated writer in Phase 11b** for `MEMORY.md`, `decisions.md`, and `.agentic/context.md` (append-only). Operators retain manual write rights; Stop hook retains context.md auto-write; /wrap retains its own write paths. wrap-ticket and /wrap MUST NOT run concurrently — share `.agentic/wrap.lock`.
- Phase 11b reads `findings_log` from `loop-state.json` BEFORE Phase 12 cleanup. findings-curator (Phase 6 exit) does NOT clear findings_log; Phase 12 cleanup is the only clearer.
- qa.md triggers SUPPLEMENT qa-engineer context but CANNOT override `qa_skip != null`. Architect's commitment is authoritative.
- Edits restricted to: `content/sections/03-planning-artifacts.md`, `content/sections/02-delegation.md`, `content/sections/05-qa-gate.md`, `content/agents/architect.md`, `content/agents/qa-engineer.md`, `content/agents/wrap-ticket.md` (NEW), `content/commands/implement-ticket.md`, `content/commands/wrap.md`. Build artifacts under adapter directories not edited directly.

**Verification:**

Grep checks against the post-edit repo:
- `grep -rn "qa_criteria" content/` → present in `architect.md`, `qa-engineer.md`, `implement-ticket.md`, `03-planning-artifacts.md`, `05-qa-gate.md`
- `grep -rn "qa_skip" content/` → 5 enum values listed in `architect.md` and `03-planning-artifacts.md`: `pure-backend-library`, `config-only`, `type-only-refactor`, `dep-bump-no-runtime-change`, `docs-only`
- `grep -n "Phase 11b" content/commands/implement-ticket.md` → section heading + cross-references
- `grep -n "wrap-ticket" content/sections/02-delegation.md` → automated-writer carve-out paragraph
- `ls content/agents/wrap-ticket.md` → new file exists with manifest header
- Phase 6b trigger paragraph no longer contains the legacy phrase. Run `grep -n 'qa.md exists at either resolver path' content/commands/implement-ticket.md content/sections/05-qa-gate.md` and confirm zero matches; the canonical pre-edit phrasing was: `"qa.md exists at either resolver path (.agentic/qa.md preferred, legacy .claude/qa.md fallback) AND has a ## QA triggers section AND the diff matches at least one trigger pattern."`

Schema validation walkthrough:
- `qa_criteria` schema: `qa_skip` (enum or null), `qa_skip_rationale` (required iff qa_skip != null, max 200 chars), `scenarios[]` with `id` (monotonic int), `description` (one observable sentence), `method` (`browser | api | runtime-required` — `source-verified-acceptable` REMOVED), `evidence` (string), `manual_smoke` (paragraph or "none"). When `qa_skip == null`, `scenarios` MUST have ≥1 entry. Invalid `qa_skip` enum is normalized to null + Phase 6b emits Major operator warning at gate entry: `"WARNING: qa_skip value '<X>' is not a valid enum (one of: pure-backend-library, config-only, type-only-refactor, dep-bump-no-runtime-change, docs-only). Treating as null; QA will fire."`

Decision-rule tests (must pass for all combinations):
- Elevated + qa_criteria present + qa_skip=null + scenarios non-empty → QA fires
- Elevated + qa_criteria present + qa_skip in 5-enum set → QA skipped, rationale logged
- Elevated + qa_criteria present + qa_skip invalid string → normalized null + warning + QA fires
- Elevated + qa_criteria absent (architect plan missing the block) → Skeptic-on-architect-plan raises Critical
- Trivial path → Phase 6b never fires; Phase 11b unconditionally skipped with `skipped_reason: "trivial-no-brief"`
- Resume of in-flight ticket whose Brief lacks qa_criteria → Phase 0b detects, attempts retroactive backfill from architect plan; if architect plan also lacks it, surfaces operator prompt (one-time bypass option for transition tickets); new invocations hard-fail

Phase 11b behavioral tests:
- PR opened on Elevated unit → wrap-ticket spawns with full inputs, applies append-discipline, returns JSON, conductor prints operator_summary
- PR opened on Trivial unit → Phase 11b skips with `skipped_reason: "trivial-no-brief"`, no spawn
- wrap-ticket fails or times out (>60s) → conductor warns and Phase 12 proceeds; PR is unaffected
- /wrap holds `.agentic/wrap.lock` in another session → Phase 11b skips with operator note
- Dedup: wrap-ticket finds candidate fact already in MEMORY.md (case-insensitive whitespace-collapsed substring match) → skips that append; logs in `writer_actions[]`

qa.md snapshot mechanism (resolves gitignored-file diff problem):
- Snapshot is gated on Elevated classification — fires only after risk classification has set risk to Elevated. Trivial invocations skip snapshotting entirely (preserving bit-for-bit-identical guarantee).
- At the first Elevated phase boundary post-classification (typically end of Phase 1 / beginning of Phase 2), conductor copies `.agentic/qa.md` (if present) to `.agentic/qa.md.snapshot-<ticket_id>`. Atomic write.
- On resume of an Elevated ticket from a paused/interrupted state, snapshot is re-acquired only if absent (preserve original snapshot if present).
- wrap-ticket reads working-tree `.agentic/qa.md` and diffs against `.agentic/qa.md.snapshot-<ticket_id>` to surface qa.md additions made during this ticket.
- Phase 12 cleanup removes the snapshot file.
- Snapshot path is gitignored under `.agentic/` umbrella.
- Verification: a Trivial single-ticket invocation produces NO `.agentic/qa.md.snapshot-*` file; an Elevated invocation produces exactly one snapshot named for the ticket_id and removes it at Phase 12.

Stop-hook ordering preserved:
- writeLoopState first (per existing convention)
- writeBatchState second (per recent batch-handoff work)
- No wrap-ticket interaction with Stop hook.

**Open Questions:** none.

**Linked artifacts:**

architect-plan: produced inline by an architect spawn during this conductor session — no external file path. The plan covered 12 implementation steps; this Brief incorporates the plan's intent with the following amendments resolving Skeptic v1 findings:

- **C1 (findings_log race):** Explicit ordering — findings-curator at Phase 6 exit reads `findings_log` but does NOT clear it. Phase 11b's wrap-ticket reads `findings_log` before Phase 12 cleanup. Phase 12 is the only clearer.
- **C2 (qa_skip invalid enum):** Single normalization rule — invalid value treated as null + Major operator warning at Phase 6b entry. No silent fall-through. Skeptic-on-Brief still flags as Major upstream as a defense-in-depth.
- **M3 (Trivial-path Phase 11b):** Unconditionally skipped with `skipped_reason: "trivial-no-brief"`. No input substitutions; the spawn never fires for Trivial.
- **M4 (in-flight Brief migration):** Phase 0b on resume detects missing qa_criteria. Resolution order: (a) check architect plan for qa_criteria block — if present, conductor authors retroactive Brief amendment appending the block; (b) if absent, surface operator prompt with one-time bypass option for transition tickets only. New invocations after rollout hard-fail per architect plan.
- **M5 (qa.md snapshot):** Phase 0b snapshots qa.md to `.agentic/qa.md.snapshot-<ticket_id>`; wrap-ticket diffs working tree against snapshot; Phase 12 removes. Specified in Verification.
- **M6 (qa.md triggers vs qa_skip):** qa.md triggers can SUPPLEMENT qa-engineer context (additional matched patterns passed alongside qa_criteria scenarios) but CANNOT override `qa_skip != null`. The architect's `qa_skip` decision is authoritative and bypasses the trigger check entirely.
- **M7 (sole-writer wording):** Reframed as "automated writer in Phase 11b". Operators retain manual write rights for MEMORY.md, decisions.md, context.md. Stop hook retains context.md auto-write. /wrap retains its own write paths (uses .agentic/wrap.lock to serialize with wrap-ticket).
- **M8 (regression tests):** Verification field above lists the decision-rule tests, Phase 11b behavioral tests, and qa.md snapshot mechanism that constitute the regression coverage. These are inspectable post-edit.
- **m9 (method enum):** `source-verified-acceptable` REMOVED. Enum reduced to `browser | api | runtime-required`. The whole point of QA is dynamic verification; the escape-hatch enum value is dropped.
- **m10 (MEMORY.md growth):** Documented non-handling for v1. Per-ticket cap of 3 appends + dedup limits noise; rotation/aging is future work. Soft tripwire: when `MEMORY.md` exceeds 50 KB, wrap-ticket emits a one-line operator advisory in its `operator_summary` ("MEMORY.md exceeds 50 KB; consider /wrap-driven consolidation"). No automatic rotation in v1.
- **m11 (decisions.md resolver):** Probe order, FIRST MATCH WINS: (a) `AGENTS.md` decision-log convention if specified; (b) `decisions.md` at cwd; (c) `docs/decisions.md`; (d) `docs/adr/` directory if exists (creates `docs/adr/NNN-<title>.md` per ADR convention); (e) create `decisions.md` at cwd. When multiple sources exist concurrently (e.g., both `decisions.md` at cwd and `docs/adr/`), the first match wins; subsequent paths are not consulted.
- **m12 (supplemental_qa_md_match flag):** REMOVED. qa-engineer auto-detects qa.md trigger matches at spawn time; no architect flag.

orchestration: 4 atomic units, sequential — (a) `content/agents/wrap-ticket.md` new agent spec with manifest header; (b) `content/agents/architect.md` + `content/agents/qa-engineer.md` + `content/sections/03-planning-artifacts.md` + `content/sections/05-qa-gate.md` + `content/sections/02-delegation.md` (qa_criteria contract surface and writer carve-outs); (c) `content/commands/implement-ticket.md` (Phase 6b trigger rewrite, Phase 0b qa.md snapshot + Brief-on-resume detection, Phase 11b insertion, Phase 12 snapshot cleanup); (d) `content/commands/wrap.md` relationship-clarification paragraph. Single engineer can apply all four in one pass; sequential because they share schema definitions.
