<!--
Purpose: Procedure for the optional cross-session runbook conductor: after
         /ds-ticket-triage, one session watches the ticket sessions the
         operator opens for the triage lanes, or starts them itself as
         headless lanes via bin/ds-lane, relays operator rulings and
         stoppages between them, and holds risky actions for an operator
         decision. It never implements, reviews, or executes a held action.

Public API: Read-only reference document. Entered only from
            /ds-ticket-triage Output item 8, when the operator replies
            "conduct" or "launch". Defines the state file
            <repo>/.agentic/runbook-<KEY>.json, the kickoff and naming
            format, the launched-lanes procedure (ds-lane start, per-firing
            reap and list, blocked and dead lanes as Operator decisions,
            delivery by send or resume), the watch subscription, the
            stoppage relay branches, and the binding message templates
            (ruling, state, hold, queue).

Upstream deps: Claude Code cross-session tools (ListAgents, SendMessage,
               CronCreate, CronList, CronDelete), loaded via ToolSearch;
               the /ds-ticket-triage artifact (lane fences, KEY stem);
               gh CLI and the configured tracker (live PR, CI and ticket
               state); per-ticket loop-state files written by
               /ds-implement-ticket (read-only here); bin/ds-lane (launch
               mode only).

Downstream consumers: content/commands/ds-ticket-triage.md Output item 8;
                      content/references/conductor-turn-format.md scope
                      filter exception.

Failure modes: Prose reference; does not auto-execute. When the tools are
               absent or fail to load, triage output is unchanged and the
               operator uses the paste-ready kickoff prompts. The state file
               is conductor-only and written tmp+rename before any message
               it records. Rulings, holds and queue sends are recorded, so
               a crash leaves at most an unsent entry for those; `state`
               sends and watch subscriptions are not recorded. PR, CI and
               ticket state are never cached, so nothing in the file can go
               stale against gh or the tracker. `surfaced_status` is
               recorded after its stoppage is surfaced, so a crash risks a
               duplicate stoppage, never a lost one. No executable test can
               exercise this procedure, because it is prose a model runs
               against live cross-session tools; runtime QA of this
               procedure is its check.

Performance: one cron firing per 30 minutes plus one turn per idle notice;
             each firing reads compact --json fields only (M6).
-->

# Runbook conductor

An optional mode for a session that has just run `/ds-ticket-triage`. The operator opens one ticket session per lane, or this session starts each lane headless (§Launched lanes); this session watches them, relays operator rulings, surfaces stoppages as Operator decisions, and holds risky actions until the operator rules. Each ticket session still runs its own full `/ds-implement-ticket` flow. No message ever tells a session to skip its own Skeptic, QA or gates.

## Preconditions and degrade

- Entry is `/ds-ticket-triage` Output item 8. Its print predicate, its load rule and its load-failure line are binding there, not here. Without the tools, the kickoff stays the paste-ready one.
- Load deferred tool schemas with `ToolSearch select:` before first use.
- Cloud sessions are watched through gh and the tracker only.
- Every ticket session must run in this session's permission mode. An idle notice from a session in a different permission class is delivered to the user, not to this session (measured). The Kickoff lane header says so.

## State file

One file, `<repo>/.agentic/runbook-<KEY>.json`, where `KEY` is the triage artifact stem (`triage-YYYYMMDD-4hex`). Only the conductor writes it, write-ahead: atomic tmp+rename, before any SendMessage it records.

Fields: `schema_version`, `runbook_key`, `conductor_session_id`, `repo`, `status` (`active`|`complete`), `updated_at`, `resume_hint`, `waves[]`, `sessions[]` (each `{name, tickets[], adopted_via: issued|operator-confirmed|launched, lane, surfaced_status}`; `lane` is present only for launched sessions), `rulings[]`, `holds[]`, `queue[]`, `cron_id`.

`holds[]` entries are `{ticket, session, summary, decision_verbatim}`. The executor is always the reporting `session`.

PR, CI and ticket state are never stored. Read them live from gh, the tracker and loop-state every time.

## Kickoff and naming

The kickoff is never written into the triage artifact. After "conduct", record each lane's `{name, tickets[]}` in `sessions[]` (with `adopted_via: issued`) and the lanes' tickets as the first entry of `waves[]`, then print for each lane:

- `Lane N - open a new session in the same permission mode as this one and send these as two separate prompts:`
- a fence containing `/rename <the lane's ticket IDs joined by "-">`
- the artifact's lane fence, copied verbatim.

**Adoption.** Match `ListAgents` rows to sessions:

- A row is adopted when its name, minus the ` [hex]` suffix, equals an issued `sessions[].name`.
- Only issued names are adopted automatically. A session the operator explicitly names is added to `sessions[]` with `adopted_via: operator-confirmed`; its `tickets[]` are the tickets the operator names with it.
- A session's tickets always come from `sessions[].tickets`, never from its name.

## Launched lanes

Entered when the operator replies "launch" instead of "conduct". This section replaces §Kickoff and naming's per-lane print: launch prints nothing per lane.

- **Start.** `<state>` below is the directory `ds-lane path` prints (the primary checkout's, even from a linked worktree). For each lane, write `<state>/prompts/<name>.md`, where `<name>` is the lane's ticket IDs joined by "-". Its content is `<state>/prompts/_rules.md` when that file exists, followed by the artifact's lane fence, verbatim. Then run `ds-lane start <name> <that file>` and record `{name, tickets[], adopted_via: launched, lane: <name>}` in `sessions[]`, and the lanes' tickets as the first entry of `waves[]`. Start lanes in artifact order under the cap rule in **Firing**; the rest are queued. The queue is not stored: it is the artifact's lanes, in order, whose tickets are in the current `waves[]` entry and appear in no `sessions[]` entry, so rebuild it from those two fields after a compaction. `ds-lane start` adds the `LANE-DONE`/`LANE-BLOCKED` marker contract itself and runs the lane in this session's permission mode.
- **Not adopted.** Launched sessions get no `ListAgents` adoption, no `notify_when_idle` arming, and no absent-name stoppage.
- **Firing.** The §Watch cron still exists and drives every firing. Each firing runs `ds-lane reap`, then `ds-lane list <the launched lane names>`. A lane newly showing `blocked` or `dead` becomes an Operator decision whose dedupe key, kept in `surfaced_status`, is its `LANE-BLOCKED` line verbatim, or for `dead` (it exited with no marker: crash, API error or `stop`) `dead: ` plus its last `ds-lane tail <name> 1` message verbatim. Its slot stays reserved until its ruling is delivered. A queued lane starts only while `ds-lane count` plus the `blocked` or `dead` lanes with PROC `down` and no delivered ruling is below `DS_LANE_MAX` (default 5).
- **Delivery.** Write each message to `<state>/prompts/<name>.msg.md` and pass that file, never the text inline. A message goes by the lane's `ds-lane list` row: STATE `alive` with PROC `up` (feeder still open) takes `ds-lane send <name> <file>`; PROC `down` with STATE `blocked` or `dead` takes `ds-lane resume <name> <file>`. A lane showing `blocked` with PROC still `up` has no feeder: its ruling stays pending and is retried each firing until PROC is `down`. A lane showing `done` gets no message, and a ruling that names no session goes only to the launched lanes not showing `done`.
- **Reports.** Read a lane's report with `ds-lane tail <name> 1`. A report of a destructive or restoring action goes to §Holds. This reference adds no SendMessage instruction for launched lanes.

## Watch

- Arm each adopted session with `SendMessage{to, notify_when_idle: true, content: ""}`. This is a subscription, not an envelope message. Re-arm it after every idle notice.
- Create one cron, every 30 minutes on an off-minute (for example `7,37 * * * *`), whose prompt names the absolute state-file path and this reference. Record its id in `cron_id`. If `CronList` no longer shows it, re-create it (M4).
- Each firing evaluates the close-out condition. A firing with at least one session not launched by §Launched lanes also runs `ListAgents` and re-arms any such session missing a watch. An issued session name absent from `ListAgents` (a lane whose `/rename` was skipped) is surfaced once as a stoppage: surface it unless that session's `surfaced_status` is already `absent from ListAgents`, then set it to that.
- **Silence.** A firing or notice with no stoppage emits no operator-visible text; the turn is tool calls only.

## Stoppage relay

On an idle notice, read the tracker, gh, and the loop-state of each of the session's tickets. Loop-state is every `<repo>/.agentic/loop-state-*.json` whose `ticket_id` field equals the ticket; there is one file per ticket, so a multi-ticket session has several. Read `status` and `last_phase`. Never re-derive `LOOP_KEY`. If no file matches, leave that fact out.

Then branch on the notice's own harness status line, `Its harness reports: «<status>»`:

- **Done or merged:** silent, or advance the queue.
- **Names a decision, an approval, a confirmation, the operator, or this session:** re-arm. The dedupe key is this status verbatim plus the `last_phase` of the session's tickets' loop-state, as a list in `tickets[]` order when the session has several. If the session's `surfaced_status` equals that key, emit nothing. Otherwise surface the quoted status to the operator as a stoppage ("may await approval in its own window"), then set `surfaced_status` to the key; the session's own question is in its own window. Send the session no `state` message on this branch.
- **Any other status** (for example CI, its own subagent, a push): re-arm only. No message, no operator text.
- **No status line:** re-arm only. Usage-limit resume covers it.

Any notice whose dedupe key (its status verbatim plus that `last_phase` list) differs from the session's `surfaced_status`, on any branch including Done or merged, clears it, and so does a notice with no status line.

Any SendMessage reply from a conducted session that asks a question or reports a stop is relayed verbatim to the operator as an Operator decision.

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
- **hold (decided):** `Operator decided, verbatim: "<text>" [per operator, <date>, verbatim]. You are the executor; execute it once and report the result.` A non-reporting session the ruling names gets the same first sentence plus `Do not act on it yourself.`
- **queue:** `Operator queued for this session, verbatim: "<text>". The operator will start it; no action needed now.`

## Rulings

Store each operator ruling verbatim in `rulings[]` with its date and target sessions, then send `ruling` to the sessions it names, or to all conducted sessions when it names none. A ruling cannot lift the Skeptic round cap: when a session reports a `skeptic-grant-` token, tell the operator to type it in that session (`skeptic-protocol.md` §Round budget item 1).

## Usage-limit resume

On the harness reset prompt ("Your claude.ai usage limit has reset"), send `state` to every conducted session whose ticket is not done or merged. There is no hit-time check, and no message claims that a limit was hit.

## Holds

When a session's status line or reply reports a destructive or restoring action (see §Stoppage relay) for a ticket that has no `holds[]` entry yet:

1. Record `{ticket, session, summary: <the report verbatim>, decision_verbatim: null}`, send `hold (open)` to that session, and present the report verbatim to the operator as an Operator decision. When the report came from an idle notice, set the session's `surfaced_status` to that notice's dedupe key, so the next identical notice is not surfaced again. A reply to `hold (open)` is relayed verbatim to the operator whether or not it asks a question or reports a stop.
2. On the operator's decision, record `decision_verbatim`, then send `hold (decided)` once to the reporting session and to any other session the ruling names.

Known limit: a ticket that already has a `holds[]` entry never gets a second hold, even for a different action; any later report about it, including the executor's result report and repeat idle notices, follows §Stoppage relay's branches without this routing and is surfaced only if those branches surface it.

After these steps, re-arm the session's watch as usual; the clearing of `surfaced_status` above still applies.

The conductor never executes the held action itself.

## Waves

When a wave's tickets are done, re-run `/ds-ticket-triage` over the remaining tickets and present the next wave as an Operator decision. Record it in `waves[]`.

## Session reuse

Launched lanes are never reused. Otherwise only on explicit operator request. Until M1 is measured, print the paste line for the operator and send only `queue`.

## Conductor compaction

After a compaction, the first action is to read the state file. No message is sent before it.

## Ticket-session compaction

- There is no threshold trigger: a session cannot see its own context usage.
- Rulings survive through the footer.
- If the operator asks for a note for a session, send `state`.
- Automatic resume after compaction is a separate sibling unit (a SessionStart(compact) hook), not part of this reference.

## Close-out

Close out when every ticket in every wave of `waves[]` is done or merged and no wave is left to open, or when the operator asks. First surface every `holds[]` entry whose `decision_verbatim` is still null, and close only after the operator acknowledges. Then `CronDelete` the recorded `cron_id` and set `status: complete`.

## Measured unknowns

Each item has the default this procedure works around and the measurement that would settle it.

- **M1, reuse by message.** Default: print the paste line and send only `queue`. Measure: message a finished scratch session "invoke Skill ds-implement-ticket X" and check for a Skill call.
- **M2, cross-permission-mode delivery.** Default: an unacknowledged message becomes a stoppage; cross-class idle notices go to the user. Measure: acceptEdits to default mode, and whether the receiver's transcript shows the empty-content subscription.
- **M3, footer survival after compaction.** Default: every message, including `state`, carries the footer. Measure: send a ruling, `/compact` the receiver, then ask it for the path.
- **M4, cron expiry.** Default: re-create the cron when `CronList` lacks it. Measure: the `CronList` age limit.
- **M5, turn-shape hook on relay turns.** Default: Operator-decision shape; the hook has no cross-session check. Measure: replay a conducted transcript through the installed hook.
- **M6, context per firing.** Default: compact `--json` fields only. Measure: bytes added per silent firing.
- **M7, auto-compaction threshold.** Default: nothing here depends on it. Measure: re-check it against current docs in the sibling compaction-resume unit.
