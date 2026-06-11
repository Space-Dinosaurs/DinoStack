# Risk Register: Deferred / Background `/wrap`

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R1 | Duplicate enrichment of one marker across two sessions | Low | Low | Idempotency is the correctness guarantee (context.md merge dedups via the new Recent-Focus dedup-on-marker rule; `.agentic/memory.md`/`AGENTS.md` single-writer; root `MEMORY.md`/`learnings.md` append-dedup). `claimed_at` + staleness window reduce frequency only. Wasteful, never corrupting. |
| R2 | Pinned-header prefix drift across the 3 emitters/2 matchers | Low | High | One byte-exact prefix `# Session Context\n*Written by /wrap` is the single contract; integration Skeptic verifies it across `wrap.md`, `stop-context.js:788`, `session-context.ts:449`. |
| R3 | Lock-aware hook regression breaks normal context.md write | Low | Med | Hooks fail-open (`fs.existsSync` wrapped in try/catch → false). When `wrap.lock` absent (the common case — only `/wrap` creates it), behavior is byte-identical to today. `hooks/tests/` covers lock-present and lock-absent paths. |
| R4 | `.last-wrap` written too early suppresses the recovery marker | Low | High | Fixed in plan: Step 0a stages the *marker*; `.last-wrap` written only after a successful Part A context.md write. Integration Skeptic checks the write timing. |
| R5 | OpenCode plugin `finalize()` fires per-turn finalization writes | Low | High | Plan scopes the shared `finalize()` to the context.md branch only; the 3 finalization writes stay `command.executed`-exclusive. Integration Skeptic checks plugin:710-712. |
| R6 | Drain temp file `.stop-deferred-activity.jsonl.draining.<pid>` leaks on crash | Low | Low | SessionStart sweep `rm -f ...draining.*` (fail-open) in U5. Spilled records re-derivable. |
| R7 | Adapter divergence (OpenCode hand-port drifts from Node hook) | Med | Low | Reciprocal `// keep in sync` comments in both files; OpenCode is a known hand-maintained parallel port (MEMORY.md 2026-05-03). |
| R8 | Spillover record lost if the Part-A drain reads-then-appends instead of cutting first | Low | Low | Atomic three-step rename-first drain (`rename → fold → unlink`); a post-rename hook append lands in a fresh file for the next drain. Verified by Verification Gate Row 6 (Stop-during-held-lock → no clobber). |

No High-likelihood risks. All High-impact risks are Low-likelihood and gated by the integration Skeptic.
