# Verification Gate: Daemon-Driven Deferred `/wrap`

*Plan-tier artifact. Every gate has a named owner and an explicit pass condition - no "cannot specify" entries. Automated gates run in CI/hooks-tests; operator gates are the two real-runs an agent cannot drive.*

## Automated gates (engineer/Skeptic-verified before merge)

| Gate | Pass condition | Unit | Owner |
|---|---|---|---|
| **Unit tests (21 cases)** | `hooks/tests/` suite green; the 21 named cases in architect-plan §Verification gates all pass | U7 | engineer + U7 Skeptic |
| **G-NOSWEEP** (CRITICAL-A) | `hooks/wrap-stale-sweep.js` does not exist; SessionStart makes no sweep call; no `pending` marker reaches `ready` without a terminal SessionEnd; no built copy in any of 7 adapters | U2, U4, U9 | integration Skeptic + U9 |
| **G-SELFHEAL** (MAJOR-B) | Existing install w/ no install.sh re-run + no pre-existing sentinel -> first Claude SessionStart creates `.claude-host`; off-Claude does NOT create it | U4 | U4/integration Skeptic; case 20 |
| **MAJOR-3 no-regress** | A late Stop after `finalizeReady` does NOT regress `ready`->`pending` | U1 | integration Skeptic; case 5 |
| **MAJOR-C reclaim** | `reclaimAbandonedInProgress` resets only daemon-claimed dead-PID stale markers; never touches session-claimed/live-PID/fresh/`pending`; `gave_up` at attempts>=3 | U3 | integration Skeptic; case 19 |
| **MINOR-E golden** | Interactive `/wrap` Part A context.md output byte-identical pre/post the format extraction (5-label fixture) | U-WDEF, U7 | U-WDEF Skeptic; case 21 |
| **Loop-guard** | `AGENTIC_WRAP_DAEMON=1` no-ops all entry points (Stop stagePending, SessionEnd finalize+launch, SessionStart launch, Step-0a staging) | U1-U4 | integration Skeptic; case 13 |
| **Off-Claude/toggle-off byte-identity** | `/wrap` runs byte-identical with no sentinel / toggle off / under guard; no marker staged | U5 | U5 Skeptic; cases 11,12 |
| **Security (daemon)** | No subprocess arg injection; bypassPermissions blast radius bounded by `--allowedTools`; no lock/PID TOCTOU; stale-lock `rm -rf` no path traversal; PID-reuse fail-safe | U3 | security-auditor (multi-dimensional) |
| **Perf (daemon)** | No added Stop-hook latency (heartbeat is a single local fs touch); idle self-exit fires; FIFO scan cost bounded | U3 | perf-analyst (multi-dimensional) |
| **Doc-sync (MAJOR-4)** | Toggle count consistent across conventions.md / 04-risk-classification.md / METHODOLOGY; built adapter copies match | U8, U9 | per-unit Skeptics |
| **Build/lint** | All 7 adapter builds green; methodology lint green; 3 tracked wrap-enrichment copies deleted; no orphaned async sections; OpenCode stages no marker (MINOR-D) | U9 | U9 Skeptic |
| **Manifests** | New source files (wrap-marker.js, session-end-wrap.js, wrap-daemon.js, session-start-wrap.sh) carry manifest headers; stop-context.js + conductor-operating-rules.md manifests updated | U1,U2,U3,U4,U6 | per-unit/integration Skeptics |

## Operator gates (real-runs - cannot be agent-driven)

| Gate | Pass condition | When |
|---|---|---|
| **G-AUTH** | A detached, no-TTY `claude --resume <id> -p "/wrap-deferred"` launched from the daemon inherits the authed session credentials without prompting (or the auth pre-flight fails loud, not silent). | After merge, before relying on the daemon in anger. |
| **G-E2E** | S1 substantive edit + clean exit -> SessionEnd finalizes a per-session `ready` marker -> daemon resumes S1 headlessly in the MAIN dir + runs non-interactive `/wrap-deferred` (auto-clears a stale `wrap.lock` in code, no prompt) -> context.md/memory.md/AGENTS.md written in place -> marker cleared; S2 stays responsive; daemon killed mid-wrap -> next startup reclaims the `in_progress` marker and re-wraps (MAJOR-C); existing install self-heals `.claude-host` on first SessionStart (MAJOR-B); kill-without-SessionEnd / `reason:resume` is NOT auto-wrapped (manual `/wrap` recovers - CRITICAL-A limitation); manual `/wrap` blocks to completion; toggle-off + non-Claude -> no marker. | After all units merge, before enabling for real use. |

## Gate ordering
Per-unit automated gates clear inside each unit's wave. The integration + multi-dimensional gates clear in Wave 5 (over the combined U1+U2+U3+U4 diff). U7 (tests) and U9 (build/lint) clear in Waves 6-7. The two operator gates are the final acceptance, surfaced to the operator after merge - the feature ships toggle-off and is enabled only after they pass.
