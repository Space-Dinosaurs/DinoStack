# Risk Register: Auto-Identity V1

| # | Risk | Unit | Likelihood | Impact | Mitigation (designed) |
|---|------|------|-----------|--------|-----------------------|
| R1 | Wrong gh handle attributed to telemetry/PRs | U1,U2 | Med (multi-gh-account machines) | High (permanent mis-attribution) | Provisional gate: no telemetry write / no Developer trailer until confirmed. Pending buffer holds data unattributed; flush stamps confirmed handle only. |
| R2 | Concurrent `confirm` double-appends to global log | U1 | Low | Med (inflated operator totals) | `fcntl.flock` LOCK_EX on `.flush.lock` spans whole flush; dedup by session_uuid. |
| R3 | Malformed `Signed-off-by` fails DCO, blocks PRs | U1 (template) | Med (unset git config) | High (PR blocked) | Guard: `||--global` fallback then loud abort; never emit empty signoff. |
| R4 | Preflight made interactive/slow (invariant break) | U4 | Low | High (every command stalls) | Confirm lives at conductor first-user-turn (meta-divergence pattern), NOT preflight; preflight only reads the field. |
| R5 | Adapter-sync / drift CI fails on merge | U9 | Med | Med (red CI) | U9 runs all 8 builds + baseline regen in same commit, on a branch with all content edits; PR2 bundles content+adapters. |
| R6 | Flush writes into wrong repo (stale repo_root) | U1 | Low | Low | `git -C rev-parse --show-toplevel` + basename==project_slug check; global-only fallback + warn. |
| R7 | `.pending/` leaks unattributed data into rollups | U2,U3 | Low | Med | Pending files are `.json` under `.pending/` subdir; cost glob is top-level `*.jsonl` (non-recursive). |
| R8 | Behavioral PR (U1-U3) merged after content PR breaks conventions ref | sequencing | Low | Med | Merge order enforced: PR1 (behavioral) before PR2 (content references `agentic-identity confirm`). |

No security/auth/payment/PII surface. No data migration (additive schema). All risks have a designed mitigation already in the vetted plan.
