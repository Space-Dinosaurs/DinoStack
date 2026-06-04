# Verification Gate: Auto-Identity V1

Every unit has a concrete verification path (no "cannot specify" entries).

| Unit | Verification |
|------|-------------|
| U1 `bin/agentic-identity` | Run `agentic-identity auto` (gh authed) -> identity.yml has `provisional: true`/`derived_from: gh`; `auto` w/o gh -> exit 1; `auto` over confirmed w/o --force -> exit 2; `show` prints `provisional: true`; `confirm` strips flags + flushes pending (line lands in both logs w/ confirmed dev_id + original ts); two parallel `confirm` -> no double-append (flock); stale repo_root -> global-only + warn. Integration Skeptic verifies flock/dedup/repo_root logic. |
| U2 `hooks/stop-context.js` | Provisional/null session -> `.pending/<uuid>.json` written (no dev_id), no session-log write; confirmed session -> appends both per-project + global; cap-100 drops oldest + stderr notice; `writeSessionLogGlobal` silent-fail independent. Integration Skeptic verifies gate + atomicity. |
| U3 `bin/agentic-cost` | `agentic-cost operator` aggregates `~/.agentic/session-log/*.jsonl` by dev+project; `.pending/` excluded; `--json` valid; `team` output unchanged. Integration Skeptic. |
| U4 protocol docs | sections/01 Step 1 read-only (no shell-out/prompt - preserves preflight invariant); conventions.md + METHODOLOGY.md first-turn confirm matches U1 `confirm`; TEAM noted enabled-not-auto-distributed. Content Skeptic. |
| U5 `agentic-cost.md` | `operator` documented (glob path, .pending exclusion, table, --json). Self-evident review (Trivial). |
| U6 `agentic-identity.md` (new) | All 4 subcommands w/ correct flags; pending-buffer + cap; schema + back-compat; manifest header. Content Skeptic. |
| U8 `sections/09` note | One paragraph: pending buffer is pre-attribution staging, not an events.jsonl event. Self-evident review (Trivial). |
| U9 adapters + baseline | All 8 adapters rebuilt (no stale); `scripts/.methodology-baseline.sha256` regenerated; **adapter-sync + methodology-drift CI gates green**; no U7 artifacts present. Adapter Skeptic + CI. |

Feature-level gate: architect plan QA `manual_smoke` cases 1-13 pass. DCO CI green on both PRs (commits Signed-off-by, author tyhummel@gmail.com).
