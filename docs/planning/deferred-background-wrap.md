# Brief: Deferred / Background `/wrap`

*Source: operator-confirmed via /brief (express path from `~/.claude/plans/create-a-plan-for-velvet-sifakis.md`). 2026-06-11.*

**Problem:** Users cannot end a session and immediately start a new one without either waiting for `/wrap`'s full synchronous pipeline (draft → Skeptic → write → compress) or losing the session's enriched context entirely. Because `/wrap` blocks, it gets skipped, and session intent in `context.md`/`MEMORY.md`/`AGENTS.md` is silently lost.

**Success criteria:**
- `/wrap` returns control within a few seconds after staging a resume safety-net, with enrichment finishing in the background; `--sync` preserves today's blocking behavior.
- A session that ends with substantive un-wrapped work leaves a `.agentic/wrap-pending.json` marker; the next session in that project auto-runs enrichment in the background while staying responsive to the user's prompts.
- Background enrichment produces the same `context.md`/`MEMORY.md`/`AGENTS.md` outputs as today's synchronous `/wrap`, with no clobbering of the new session's own `context.md` writes.
- If a session exits before enrichment finishes, the marker survives and a later session completes it idempotently (no duplicate entries); after 3 failed attempts it gives up with a manual-`/wrap` notice.

**Non-goals:**
- Does NOT add interactive prompt-and-block on `/exit`, `/clear`, or `/new` — Claude Code hooks cannot intercept built-in commands; the throttled Stop-hook nudge is the closest achievable.
- Does NOT change what `/wrap` captures or its zero-substance/light/standard routing — only *when* and *where* the work runs.
- Does NOT introduce a detached headless (`claude -p`) enrichment process — background execution stays inside the conductor's session.

**Constraints:**
- No subagent spawns subagents — enrichment is conductor-orchestrated (draft agent → Skeptic → inline writes → compression, all background).
- All shared-doc writers serialize on the existing `.agentic/wrap.lock`; the Stop hook (the one unlocked `context.md` writer today) must become lock-aware.
- Hooks stay fail-open (`exit 0`) and add no perceptible latency — no `gh`/extra `git` in the Stop hook.
- Preserve the Stop hook's existing `*Written by /wrap` detection and the rolling-session-label merge (the compatibility contract).
- All edits under `content/**` + `hooks/**` → route through `/update-agentic-engineering`; regenerate adapters via build scripts; commits DCO-signed (`-s`).

**Verification:**
- `hooks/tests/` unit coverage: lock-present → `context.md` write skipped + spillover written; `/wrap`-authored-today → no marker staged; substantive vs zero-substance staging; atomic marker write; nudge throttled once/session.
- Manual two-session E2E: S1 edits + exit → marker + nudge; S2 SessionStart message + background enrichment spawns + S2 stays responsive + `context.md` merged + marker cleared. Plus: interactive async + `--sync`; kill-mid-enrichment → reclaim after staleness + `attempts ≥ 3` give-up; concurrency (Stop during held lock → spillover drain, no clobber).
- All adapter builds succeed and emit the new `wrap-enrichment` agent + refactored command; methodology lint/build green.

**QA criteria:**
```yaml
qa_skip: pure-backend-library
qa_skip_rationale: >-
  No browser-renderable UI surface. The change is Claude Code hooks (Node/shell)
  plus methodology markdown. Runtime hook behavior is verified by the hooks/tests
  unit suite and the manual two-session E2E protocol named in Verification, neither
  of which the qa-engineer browser/runtime gate can drive.
viewport: [desktop]
scenarios: []
manual_smoke: >-
  Two-session E2E in Verification is the smoke test: stage in S1, confirm
  background enrichment + responsiveness + merged context.md in S2.
```

---

## Reference

Full technical plan (component breakdown, marker state machine, race-free write protocol, spawn choreography, resolved technical defaults): `~/.claude/plans/create-a-plan-for-velvet-sifakis.md`. The architect consumes the Brief above as the authoritative framing; the plan file is supporting design detail.

**Open questions:** none.
