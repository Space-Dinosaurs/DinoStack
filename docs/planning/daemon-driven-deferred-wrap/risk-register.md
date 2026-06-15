# Risk Register: Daemon-Driven Deferred `/wrap`

*Plan-tier artifact. Derived from architect-plan.md v4 §Risk + rollback seeds and the orchestration plan. 10 Elevated units; the marker state machine is the cross-cutting correctness invariant.*

## Cross-cutting risks

| ID | Risk | Blast radius | Mitigation | Owner gate |
|---|---|---|---|---|
| X1 | **Live-resume corruption** - the daemon resumes a still-live session and interleaves its transcript. | Catastrophic (user data) | Sole `pending->ready` transition is SessionEnd terminal-reason `finalizeReady`; no stale-sweep; daemon claims ONLY `ready`; `reclaimAbandonedInProgress` never touches `pending`. (CRITICAL-A resolution.) | Integration Skeptic (U1+U2+U3+U4) |
| X2 | **Infinite re-wrap loop** - the daemon's headless `/wrap-deferred` fires Stop/SessionEnd, staging a new marker. | High (runaway cost) | `AGENTIC_WRAP_DAEMON=1` exported to the child; every marker/launch entry point no-ops under guard; `.last-wrap` secondary backstop. | Integration Skeptic; test case 13 |
| X3 | **Marker state regression** - a late Stop downgrades `ready`->`pending`, losing the finalize. | Medium | `stagePending` suppresses on ready/pending/in_progress; `finalizeReady` no-downgrade. (MAJOR-3.) | Integration Skeptic; test case 5 |
| X4 | **Silent feature no-op** - existing installs lack `.claude-host` -> Step 0a never stages. | Medium (UX) | Self-healing sentinel: SessionStart writes it create-if-absent every start; install.sh drop kept as belt. (MAJOR-B.) | U4 Skeptic; G-SELFHEAL; test case 20 |
| X5 | **Off-Claude / toggle-off behavior change** - `/wrap` not byte-identical when feature inactive. | Medium (cross-adapter) | Step 0a gated on `.claude-host` + toggle + non-guard; off-Claude has no sentinel. | U5 Skeptic; test cases 11,12 |
| X6 | **Doc/intent drift** - toggle counts, manifests, carve-outs left stale. | Low | U8 bumps counts in conventions.md + 04-risk-classification.md + METHODOLOGY; U1/U6 update manifests; U6 rewrites carve-out. | Per-unit Skeptics; MAJOR-4 cross-check |

## Per-unit risks (high-blast-radius units)

**U1 marker-lib (highest structural - runs on every Stop turn):** a regression silently degrades context.md writes every turn. Mitigation: fail-open throughout (transitions return falsy, never throw to the hook); guard early-returns are pure no-ops; extend the #184 test suite before merge. Rollback: revert U1 (self-contained, one commit); schema v1->v3 is forward-harmless.

**U3 daemon (highest behavioral - subprocess + lock/PID + session resume):** hung headless `claude` wedges the daemon; auth failure silently drops wraps; stale-lock `rm -rf` mis-fires; PID-reuse false-liveness; bypassPermissions blast radius. Mitigation: timeout-and-kill bounds every child; `claude auth status` pre-flight + fail-loud notice; `acquireWrapLock` only clears locks >30min stale; `process.kill(pid,0)` ESRCH=dead / EPERM=alive (fail-safe toward NOT reclaiming); `--allowedTools` allowlist is the real constraint, bypassPermissions only suppresses prompts; janitor is delete-only. Review: **multi-dimensional** (security-auditor + perf-analyst + integration Skeptic). Rollback: opt-in (`deferred_wrap_daemon: false`) - disabling the toggle stops all spawns; revert U3+U4 removes the daemon path with zero effect on synchronous `/wrap`.

**U5 wrap.md (protocol - `/wrap` on every adapter):** malformed Step 0a guard stages off-Claude or skips on-Claude. Mitigation: positive install-verified self-healing sentinel; explicit off-Claude/toggle-off byte-identity test. Rollback: revert restores async-default `/wrap`; the intended FEATURE rollback is the toggle, not a source revert.

## Residual / accepted

- **G-AUTH** (detached no-TTY keychain inheritance): empirical, covered defensively (pre-flight + fail-loud + timeout-kill); operator `-p` test corroborates. Confirmed once at G-AUTH real-run.
- **Brief amendments (operator-accepted 2026-06-12):** single-pass fidelity; cleanly-ended-only auto-wrap (killed/resume -> manual `/wrap`). See Brief §Amendments.
- **MINOR-1 pending-marker clutter:** bounded delete-only janitor (`deferred_wrap_pending_ttl_days`, default 7) in U3; delete-only so it cannot reintroduce X1.
