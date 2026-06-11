# Verification Gate: Deferred / Background `/wrap`

Non-skippable. The PR does not merge until every row passes.

| # | Check | Owner | Gate |
|---|-------|-------|------|
| 1 | `hooks/tests/` coverage GREEN: lock-present → context.md skipped + spillover record written; lock-absent → context.md written as today (no regression); `.last-wrap` session-id match → no marker staged; substantive vs zero-substance staging; atomic marker write (valid JSON, tmp+rename) | `stop-hook` engineer + integration Skeptic | automated, blocking |
| 2 | Pinned-header prefix `# Session Context\n*Written by /wrap` byte-identical across `wrap.md` emitters, `stop-context.js:788`, `session-context.ts:449` | integration Skeptic | review, blocking |
| 3 | `.last-wrap` written ONLY after the Part A context.md write (never in Step 0a); the 3 OpenCode finalization writes stay `command.executed`-only | integration Skeptic | review, blocking |
| 4 | Recent-Focus merge is idempotent on a duplicate claim of the same marker (no double-appended session label) | integration Skeptic + `hooks/tests` idempotency case | review + automated, blocking |
| 5 | All four adapter builds (`.claude/.codex/.cursor/.opencode build.sh`) succeed; methodology lint/build green | `adapter-regen` engineer | automated, blocking |
| 6 | **Manual two-session E2E** (HUMAN-DRIVEN — agents cannot run real Claude Code sessions): S1 edits + exits → `wrap-pending.json` + nudge present; S2 SessionStart surfaces the marker, background enrichment spawns, S2 stays responsive to prompts, context.md merges (spillover drained), marker clears, `.last-wrap` = S2 session_id. Plus: `/wrap --sync` still blocks; kill-mid-enrichment → next session reclaims after staleness, `attempts ≥ 3` gives up | **Operator** | manual, blocking |

Row 6 is the runtime gate the qa-engineer browser/runtime path cannot drive (`qa_skip: pure-backend-library`). It requires the operator to drive two real sessions. No "cannot specify" entries.
