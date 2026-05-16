# Brief: GSD-Steal Methodology Improvements

**Problem:** agentic-engineering sessions start cold on product context (no project-level vision/requirements layer), the Debugger is never auto-triggered on quality gate failures (conductor skips diagnosis and re-spawns engineer directly), and operators cannot tune workflow behavior per-project without editing global methodology files.

**Success criteria:**
- `content/agents/architect.md` and `content/agents/investigator.md` both read `docs/overview/vision.md` and `docs/overview/requirements.md` when present, treating them as authoritative product intent
- `/init-project` seeds `docs/overview/vision.md` and `docs/overview/requirements.md` with guided templates and `.agentic/config.json` with defaults
- `content/commands/implement-ticket.md` Phase 7 mandates a Debugger diagnosis step before the next engineer fix pass when `debugger_on_failure: true` is set in `.agentic/config.json` (default: false)
- `.agentic/config.json` schema with three toggles (`debugger_on_failure`, `qa_default_skip`, `model_profile`) is documented in `content/rules/conventions.md` and `content/sections/04-risk-classification.md`

**Non-goals:**
- Replicating GSD's full 5-artifact project model (ROADMAP.md, STATE.md, REQUIREMENTS.md, PROJECT.md, CONTEXT.md) - only `vision.md` and `requirements.md`
- Making `debugger_on_failure: true` the default (it ships as opt-in, default false)
- Adding more than the three named config toggles to `.agentic/config.json`

**Constraints:**
- `docs/overview/` files are operator-owned - agents read, never write
- `.agentic/config.json` is committed (not gitignored), like `qa.md` and `deploy.md`
- Convergence short-circuit in Phase 7 applies to test runners only (stable structured failure IDs); lint/typecheck rely solely on the max-3-cycle cap
- `model_profile: budget` (Tier 1) never applies to security-auditor or other agents with mandatory Tier 3 designation - those require an explicit `Tier: 3` declaration regardless of project model_profile
- `qa_default_skip` canonical definition lives in `content/sections/03-planning-artifacts.md`; architect.md and implement-ticket.md cross-reference only

**Verification:** `bash scripts/build-methodology.sh` exits 0; grep confirms `debugger_on_failure`, `qa_default_skip`, `model_profile`, `docs/overview/vision.md`, `docs/overview/requirements.md` all appear in the assembled `METHODOLOGY.md`.

**QA criteria:**
```yaml
qa_criteria:
  qa_skip: docs-only
  qa_skip_rationale: All changes are edits to methodology prose/spec files (content/agents, content/commands, content/sections, content/rules) and init-project template text; no runtime code, no executable behavior to verify dynamically.
  scenarios: []
  manual_smoke: none
```

**Linked artifacts:** architect-plan: inline (this session); orchestration: TBD after planner runs
