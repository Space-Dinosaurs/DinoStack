# Brief: Daemon-Driven Deferred `/wrap`

*Source: operator-confirmed via /brief. 2026-06-12. Supersedes the deferral mechanism in PR #184 (evolves the same branch; #184's marker/lock/spillover are retained and repurposed, its in-session async enrichment is removed).*

**Problem:** Users skip or forget `/wrap` because it is slow and blocks switching sessions, so session intent in `context.md`/`MEMORY.md`/`AGENTS.md` is silently lost. PR #184 deferred the work into the *next* session's conductor, but that taxes the next session's context and keeps enrichment coupled to an interactive session. This externalizes deferral entirely: an out-of-session, per-project daemon finishes forgotten wraps automatically with zero burden on any live session, while manual `/wrap` stays an explicit synchronous "do it now."

**Success criteria:**
- Manual `/wrap` runs the full **synchronous** pipeline in-session and blocks to completion; it stages a marker first and clears it on success, so an interrupted manual run is finished by the daemon.
- A session ending with substantive un-wrapped work - clean `SessionEnd`, or killed and detected via marker staleness - is wrapped **automatically** by a per-project background daemon, with no user action and no in-session enrichment.
- The daemon resumes the ended session **headlessly** (`claude --resume <id> "/wrap"`, non-`--bare`, plain resume, using the **existing authed `claude` session - no token/API key**) in a **dedicated worktree** built from the session's recorded commit; produces the same `context.md`/`MEMORY.md`/`AGENTS.md` outputs as a synchronous wrap; **copies gitignored outputs** (`context.md`, `memory.md`) back into the canonical project `.agentic/`; and **merges committed outputs** (`AGENTS.md`, committed docs) onto the session's branch.
- The daemon processes ended sessions **FIFO, one at a time**, serialized on `wrap.lock`; is a per-project **singleton**; is launched **detached** from `SessionEnd` (opportunistic) and `SessionStart` (backlog drain + notice); and **self-terminates after ~15 min idle**.
- The daemon path is **opt-in** via `.agentic/config.json` `deferred_wrap_daemon` (default `false`); when off, behavior is unchanged and no headless process spawns.
- `/wrap`'s core pipeline behaves **identically on every adapter**. All daemon/hook/marker machinery is additive, **Claude Code-only**, and gated behind the opt-in toggle; on a non-Claude adapter or with the toggle off, `/wrap` runs exactly as today (synchronous, no marker, no daemon).
- #184's in-session async enrichment (the in-session `wrap-enrichment` role and `SessionStart` auto-enrichment) is **removed**; the daemon is the sole deferral mechanism. #184's marker, Stop-hook lock-awareness, and spillover are **retained and repurposed**.

**Non-goals:**
- No interactive prompt-and-block on `/exit`, `/clear`, `/new` - hooks cannot intercept built-in commands.
- Does NOT change what `/wrap` captures or its zero-substance/light/standard routing.
- **Committed-only** - does not snapshot or replay uncommitted working-tree edits.
- **No compaction guard** - a compacted long session is wrapped on its compacted transcript (documented limitation; manual `/wrap` is the high-fidelity path).
- No `--bare` mode; no separate long-lived token / API key (relies on the existing authed `claude` session).
- One daemon does not run wraps concurrently or across projects (per-project singleton, FIFO).
- **Claude Code-only for v1.** Other adapters (Codex, Cursor, Gemini, OpenCode) get no daemon; not all support hooks/session-resume equivalently. Cross-adapter expansion is explicitly future work, out of scope here.

**Constraints:**
- Route all `content/**` + `hooks/**` edits through `/update-agentic-engineering`; DCO-signed commits (`-s`); regenerate all adapters.
- Hooks stay fail-open (`exit 0`) with no added Stop-hook latency (no `gh`/extra `git`); detached launch uses the `session-start-version-check.sh` fire-and-forget pattern.
- Daemon serializes on the existing `.agentic/wrap.lock` and reuses #184's marker schema, Stop-hook lock-awareness, spillover drain, and the `*Written by /wrap` detection + rolling-session-label merge.
- Daemon resumes only finalized/ended markers, with a best-effort active-session check before resume (plain `--resume` interleave mitigation); runs `/wrap` non-`--bare`; uses the existing authed `claude` session.
- Per-project singleton via a PID lock; ~15 min idle self-exit (configurable); 30-min staleness/reclaim recovers a dead daemon or a session killed without `SessionEnd`.
- Node, sharing marker/lock/path utilities with `hooks/stop-context.js`; unit-tested via `hooks/tests/`.
- Marker records what is needed to replay: `session_id`, project root, branch, HEAD commit SHA, summary pointers, status (`pending`/`ready`/`in_progress`/`done`), claim fields, attempts.
- `content/commands/wrap.md`'s added marker-staging must be guarded so non-Claude adapters and the toggle-off path retain today's exact behavior (the command's core pipeline is untouched).
- A new `SessionEnd` hook + the daemon entrypoint must be wired in `.claude/install.sh` and settings.

**Verification:**
- `hooks/tests/`: marker finalize-on-`SessionEnd`; staleness backstop; Stop-hook refresh + `/wrap` suppression (reuse #184); daemon singleton (second launch no-ops); idle self-exit; FIFO ordering; lock contention wait+retry; opt-in gate off -> no launch; non-Claude/toggle-off -> `/wrap` unchanged (no marker staged).
- **Empirical auth check (MUST verify in a real run):** a detached, no-TTY `claude -p "/wrap" --resume <id>` launched from a hook inherits the interactive authed session credentials (keychain / `~/.claude`) without prompting; on failure, the daemon surfaces a one-time notice rather than failing silently.
- Manual E2E: S1 edit + exit -> marker finalized -> daemon wraps headlessly in a worktree -> outputs copied back + `AGENTS.md` merged to branch + marker cleared; S2 stays fully responsive; killed-session (no `SessionEnd`) recovered via staleness at next `SessionStart`; manual `/wrap` blocks to completion; opt-in off -> nothing spawns.
- All adapter builds succeed; methodology lint/build green.

**QA criteria:**
```yaml
qa_skip: pure-backend-library
qa_skip_rationale: >-
  No browser-renderable UI surface. The change is a Node daemon plus Claude Code
  hooks (Node/shell) plus methodology markdown. Runtime behavior is verified by the
  hooks/tests unit suite, an empirical headless-auth check, and the manual two-session
  + daemon E2E protocol named in Verification, none of which the qa-engineer
  browser/runtime gate can drive.
viewport: [desktop]
scenarios: []
manual_smoke: >-
  Two-session + daemon E2E in Verification is the smoke test: stage in S1, exit,
  confirm the daemon wraps headlessly and copies outputs back, S2 stays responsive.
```

---

## Amendments (operator-accepted 2026-06-12, post-architect+Skeptic)

Two success-criteria narrowings, both forced by findings (not preferences), accepted by the operator before implementation:

1. **Fidelity (forced by the headless empirical test):** the deferred wrap is a **non-interactive single-pass enrichment** (`/wrap-deferred`), NOT the full interactive `/wrap`. It writes context.md / `.agentic/memory.md` / AGENTS.md directly with no draft-Worker, no Skeptic review of its own draft, and no compression pass. The interactive `/wrap` provably HANGS headlessly on its human-decision points (a stale-lock prompt), so the full-fidelity pipeline cannot run unattended. Manual `/wrap` remains the full-fidelity path. This narrows "produces the same outputs as a synchronous wrap" -> "produces a good-faith single-pass enrichment of the same three targets."
2. **Coverage (forced by the live-resume Critical):** only a **cleanly-ended** session (a genuine `SessionEnd` with a terminal reason) is auto-wrapped. A session killed without `SessionEnd`, or ended via `reason:resume`, is NOT auto-wrapped - manual `/wrap` recovers it. The only safe "this session has ended" signal is a real `SessionEnd`; a heartbeat-staleness sweep cannot distinguish an idle-but-open live session from a killed one, so auto-wrapping the abnormal-termination case would risk resuming a LIVE session and corrupting its transcript. This narrows "killed and detected via marker staleness -> wrapped automatically" -> "cleanly-ended sessions auto-wrap; abnormally-terminated sessions need manual `/wrap`." (Marker staleness/reclaim now recovers only a dead *daemon*'s abandoned `in_progress` marker, never a killed live session's `pending` marker.)

Authoritative design: `docs/planning/daemon-driven-deferred-wrap/architect-plan.md` (v4, Skeptic-signed-off: 0 Critical / 0 Major across 3 review rounds). Empirical basis: `docs/planning/daemon-driven-deferred-wrap/headless-test-findings.md`.

## Reference

Evolves PR #184 (`feature/deferred-background-wrap`). Feasibility of headless resume verified via claude-code-guide (2026-06-12): `claude -p "/wrap" --resume <id>` is supported non-`--bare`; resume reloads the transcript; non-`--bare` uses stored credentials automatically; the one empirical unknown is detached/no-TTY keychain access (covered in Verification). Operator decisions captured in `.agentic/brief-session.json` (`decisions` block, d1-d9).

**Open questions:** none.
