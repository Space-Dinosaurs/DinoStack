<!--
Purpose: Procedure for the optional cross-session runbook conductor: after
         /ds-ticket-triage, one session watches the ticket sessions the
         operator opens for the triage lanes, relays operator rulings and
         stoppages between them, and holds risky actions for an operator
         decision. It never implements, reviews, or executes a held action.

Public API: Read-only reference document. Entered only from
            /ds-ticket-triage Output item 8, when the operator replies
            "conduct". Defines the state file
            <repo>/.agentic/runbook-<KEY>.json, the kickoff and naming
            format, the watch subscription, the stoppage relay branches,
            and the binding message templates (ruling, state, hold, queue).

Upstream deps: Claude Code cross-session tools (ListAgents, SendMessage,
               CronCreate, CronList, CronDelete), loaded via ToolSearch;
               the /ds-ticket-triage artifact (lane fences, KEY stem);
               gh CLI and the configured tracker (live PR, CI and ticket
               state); per-ticket loop-state files written by
               /ds-implement-ticket (read-only here).

Downstream consumers: content/commands/ds-ticket-triage.md Output item 8;
                      content/references/conductor-turn-format.md scope
                      filter exception.

Failure modes: Prose reference; does not auto-execute. When the tools are
               absent or fail to load, triage output is unchanged and the
               operator uses the paste-ready kickoff prompts. The state file
               is conductor-only and written tmp+rename before any message
               it records. Rulings, holds, queue sends and relay `state`
               sends are recorded, so a crash leaves at most an unsent
               entry for those; other `state` sends and watch
               subscriptions are not recorded. PR, CI and ticket state are never
               cached, so nothing in the file can go stale against gh or the
               tracker.

Performance: one cron firing per 30 minutes plus one turn per idle notice;
             each firing reads compact --json fields only (M6).
-->

# Runbook conductor

An optional mode for a session that has just run `/ds-ticket-triage`. The operator opens one ticket session per lane; this session watches them, relays operator rulings, surfaces stoppages as Operator decisions, and holds risky actions until the operator rules. Each ticket session still runs its own full `/ds-implement-ticket` flow. No message ever tells a session to skip its own Skeptic, QA or gates.

## Preconditions and degrade

- Entry is `/ds-ticket-triage` Output item 8. Its print predicate, its load rule and its load-failure line are binding there, not here. Without the tools, the kickoff stays the paste-ready one.
- Load deferred tool schemas with `ToolSearch select:` before first use.
- Cloud sessions are watched through gh and the tracker only.
- Every ticket session must run in this session's permission mode. An idle notice from a session in a different permission class is delivered to the user, not to this session (measured). The Kickoff lane header says so.

## State file

One file, `<repo>/.agentic/runbook-<KEY>.json`, where `KEY` is the triage artifact stem (`triage-YYYYMMDD-4hex`). Only the conductor writes it, write-ahead: atomic tmp+rename, before any SendMessage it records.

Fields: `schema_version`, `runbook_key`, `conductor_session_id`, `repo`, `status` (`active`|`complete`), `updated_at`, `resume_hint`, `waves[]`, `sessions[]` (each `{name, tickets[], adopted_via: issued|operator-confirmed}`), `rulings[]`, `holds[]`, `queue[]`, `relays[]`, `offers[]`, `cron_id`.

`holds[]` entries are `{ticket, session, summary, state: open|decided|executed, executor_session, decision_verbatim}`.

`relays[]` holds at most one entry per session, `{session, status_verbatim, sent_at}`: a `state` relay sent and awaiting a reply.

`offers[]` entries are `{row_name, state: pending|confirmed|declined}`: every row put to the operator by the adoption prefix rule.

PR, CI and ticket state are never stored. Read them live from gh, the tracker and loop-state every time.

## Kickoff and naming

The kickoff is never written into the triage artifact. After "conduct", record each lane's `{name, tickets[]}` in `sessions[]` (with `adopted_via: issued`), then print for each lane:

- `Lane N - open a new session in the same permission mode as this one and send these as two separate prompts:`
- a fence containing `/rename <the lane's ticket IDs joined by "-">`
- the artifact's lane fence, copied verbatim.

**Adoption.** Match `ListAgents` rows to sessions:

- A row is adopted when its name, minus the ` [hex]` suffix, equals an issued `sessions[].name`.
- With a `TICKET_PREFIX`, a row not already adopted by issued name whose name matches a runbook ticket ID by `(^|[^A-Za-z0-9])ID($|[^0-9])`, and that is not already in `offers[]`, is offered once as an Operator decision. Record it in `offers[]` before offering; on confirmation record it in `sessions[]` with `adopted_via: operator-confirmed`. A row in `offers[]` is never offered again.
- With no `TICKET_PREFIX`, only issued names are adopted.
- A session's tickets always come from `sessions[].tickets`, never from its name.

## Watch

- Arm each adopted session with `SendMessage{to, notify_when_idle: true, content: ""}`. This is a subscription, not an envelope message. Re-arm it after every idle notice.
- Create one cron, every 30 minutes on an off-minute (for example `7,37 * * * *`), whose prompt names the absolute state-file path and this reference. Record its id in `cron_id`. If `CronList` no longer shows it, re-create it (M4).
- **Silence.** A firing or notice with no stoppage emits no operator-visible text; the turn is tool calls only.

## Stoppage relay

On an idle notice, read the tracker, gh, and the loop-state of each of the session's tickets. Loop-state is every `<repo>/.agentic/loop-state-*.json` whose `ticket_id` field equals the ticket; there is one file per ticket, so a multi-ticket session has several. Read `status` and `last_phase`. Never re-derive `LOOP_KEY`. If no file matches, leave that fact out.

Then branch on the notice's own harness status line, `Its harness reports: «<status>»`:

- **Done or merged:** remove any `relays[]` entry for the session; otherwise silent, or advance the queue.
- **Names a decision, an approval, a confirmation, the operator, or this session:** re-arm. If the session's `relays[]` entry already holds this status verbatim, send nothing more: a `state` message wakes the session, so its next idle notice may repeat the same status. Otherwise record `{session, status_verbatim, sent_at}` in `relays[]`, replacing any earlier entry for that session, then send `state`. Relay the reply verbatim as an Operator decision and remove the entry. If an entry still has no reply at the next firing, surface its quoted status as a stoppage ("may await approval in its own window").
- **Any other status** (for example CI, its own subagent, a push): re-arm only. No message, no operator text.
- **No status line:** re-arm only. Usage-limit resume covers it.

A status line or reply that reports a destructive or restoring action goes to §Holds, whichever branch above it would otherwise take.

The status line is the session's own free text. It decides only where the notice goes; it is never sent back to the session as a diagnosis.

## Message templates (binding)

Every non-empty message has this envelope:

- First line: `[runbook <KEY>] <ruling|state|hold|queue>`.
- Body: only verbatim operator text tagged `[per operator, <date>, verbatim]`, measured facts tagged `[verified-by-execution: <cmd>]`, and the template sentences below.
- Last line (every message, including `state`): `Rulings for your tickets: <abs state path> rulings[]; re-read after any compaction.`

`<>` slots take only verbatim operator text, the receiver's own quoted words, or tagged measured facts.

- **ruling:** `Operator ruling, verbatim: "<text>" [per operator, <date>, verbatim]. Sent because <it names <ticket> | it applies to all conducted sessions>. Apply it inside your own plan and review loop.`
- **state:** `<ticket>: <tracker state, PR, head SHA, CI, loop-state status and last_phase, each tagged [verified-by-execution: <cmd>]>. If you stopped for a decision or approval, reply with the one-line question. Otherwise, if you are stopped, continue from your own loop-state; do not redo completed work.`
- **hold (open):** `You reported: "<receiver's words>". Take no further destructive or restoring action on it until the operator rules. Reply with recoverability facts only.`
- **hold (decided):** `Operator decided, verbatim: "<text>" [per operator, <date>, verbatim]. You are the executor; execute it once and report the result.` A non-surfacing session the ruling names gets the same first sentence plus `Do not act on it yourself.`
- **queue:** `Operator queued for this session, verbatim: "<text>". The operator will start it; no action needed now.`

## Rulings

Store each operator ruling verbatim in `rulings[]` with its date and target sessions, then send `ruling` to the sessions it names, or to all conducted sessions when it names none.

## Usage-limit resume

On the harness reset prompt ("Your claude.ai usage limit has reset"), send `state` to every conducted session whose ticket is not done or merged. There is no hit-time check, and no message claims that a limit was hit.

## Holds

When a session's status line or reply reports a destructive or restoring action (see §Stoppage relay), hold the action and put the decision to the operator:

1. Record a `holds[]` entry with `state: open` and `executor_session` set to the surfacing session, then send `hold (open)` to it.
2. Present the decision to the operator as an Operator decision.
3. On the operator's decision, record `decision_verbatim` and `state: decided`, then send `hold (decided)` to the executor and to any other session the ruling names.
4. When the executor reports the result, set `state: executed`.

The conductor never executes the held action itself.

## Waves

When a wave's tickets are done, re-run `/ds-ticket-triage` over the remaining tickets and present the next wave as an Operator decision. Record it in `waves[]`.

## Session reuse

Only on explicit operator request. Until M1 is measured, print the paste line for the operator and send only `queue`.

## Conductor compaction

After a compaction, the first action is to read the state file. No message is sent before it. Pending `relays[]` entries carry over: each is surfaced at the next firing if it still has no reply.

## Ticket-session compaction

- There is no threshold trigger: a session cannot see its own context usage.
- Rulings survive through the footer.
- If the operator asks for a note for a session, send `state`.
- Automatic resume after compaction is a separate sibling unit (a SessionStart(compact) hook), not part of this reference.

## Close-out

`CronDelete` the recorded `cron_id`, then set `status: complete`.

## Measured unknowns

Each item has the default this procedure works around and the measurement that would settle it.

- **M1, reuse by message.** Default: print the paste line and send only `queue`. Measure: message a finished scratch session "invoke Skill ds-implement-ticket X" and check for a Skill call.
- **M2, cross-permission-mode delivery.** Default: an unacknowledged message becomes a stoppage; cross-class idle notices go to the user. Measure: acceptEdits to default mode, and whether the receiver's transcript shows the empty-content subscription.
- **M3, footer survival after compaction.** Default: every message, including `state`, carries the footer. Measure: send a ruling, `/compact` the receiver, then ask it for the path.
- **M4, cron expiry.** Default: re-create the cron when `CronList` lacks it. Measure: the `CronList` age limit.
- **M5, turn-shape hook on relay turns.** Default: Operator-decision shape; the hook has no cross-session check. Measure: replay a conducted transcript through the installed hook.
- **M6, context per firing.** Default: compact `--json` fields only. Measure: bytes added per silent firing.
- **M7, auto-compaction threshold.** Default: nothing here depends on it. Measure: re-check it against current docs in the sibling compaction-resume unit.
