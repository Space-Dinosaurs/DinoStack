#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that mechanically enforces a grace margin under
         the Follow-up Ticket Creation Discipline's batching rule
         (`content/references/delegation-detail.md` §Follow-up Ticket
         Creation Discipline, item 3: "2 or more discoveries in the same
         session are NEVER separate tickets - batched into exactly ONE").
         That rule was prose-only with zero mechanical enforcement (PR
         #606 shipped it and said outright "a conductor that ignores the
         discipline is not stopped"), and mid-session ticket fan-out was
         measured going 7.7/week -> 25.4/week across one week, with a
         single session minting DS-156 through DS-160 (5 tickets) over
         ~14 hours, each a small bug found while fixing the previous.

         **This hook's threshold is DELIBERATELY a grace margin BELOW the
         prose rule, not a redefinition of it.** The prose rule stays
         "exactly ONE" ticket for 2+ same-session discoveries - do not
         "fix" this file to deny on the 2nd creation to match that text
         more tightly. The 3-creation threshold exists because a real
         session can legitimately contain two independent, unrelated,
         TOP-LEVEL operator-raised asks in one sitting (each spawning its
         own single ticket) - the batching rule's carve-out in item 1
         ("Top-level, operator-raised asks are unaffected") - and a hard
         deny on ticket #2 would block that legitimate case with no
         escape hatch. The measured fan-out case that motivated this hook
         was 5 tickets in one session; a cap of 3 still catches it while
         leaving room for two genuinely independent asks. Counting
         (1st: silent allow, 2nd: allow + advisory, 3rd+: deny) is an
         operator decision, not an architect recommendation - an earlier
         plan draft specified a hard deny on the 2nd creation and was
         explicitly overridden.

         Classifies a tracker-ticket CREATE call three ways:
           1. `mcp__mcp-atlassian__jira_create_issue` - always a creation
              (the tool only creates; verified against
              `content/commands/ds-implement-ticket.md:536`).
           2. `mcp__linear__save_issue` - a creation ONLY when the call
              carries no `id` field (Linear's `save_issue` creates when
              `id` is omitted and updates when it is supplied - verified
              against `content/commands/ds-implement-ticket.md:534`). An
              `id`-bearing call (a status/comment update on an existing
              ticket) is never counted.
           3. `Bash` - a direct API bypass (PR #606 found conductors
              calling Jira REST directly instead of going through the
              documented MCP/Tracker-Create-Helper path). Both sub-cases
              require an explicit HTTP-CLIENT invocation signal - either a
              shell client verb (`curl`/`wget`/`http`/`httpie`, see
              `_HTTP_CLIENT_VERB_RE`) OR a Python HTTP-client reference
              (`urllib.request`, `requests.post`/`.put`/`.request`,
              `httpx.post`/`.put`/`.request`, see `_PYTHON_HTTP_CLIENT_RE`)
              - in addition to their own signal below, so a
              `grep`/`cat`/`echo`/`git show` command that merely CONTAINS
              matching text (the tool/endpoint/mutation name as literal
              search text, not an actual outbound call) never matches.
              The Python-client alternative was added because
              `.agentic/memory/creating-ds-jira-tickets.md` (this
              repo's own operational record) documents that curl/wget are
              hook-blocked here and `python3 -c
              "...urllib.request.Request(..., method='POST')..."` is the
              actual working direct-REST bypass channel - the pre-existing
              shell-verb-only gate covered a channel nobody uses here and
              missed the one everybody does.

              This was added after a Skeptic round found the client-verb
              gate missing entirely: `grep -rn issueCreate hooks/`, `git
              show <sha> | grep issueCreate`, `echo checking issueCreate
              mutation docs`, and `grep -rn 'POST /rest/api/3/issue'
              docs/` were all classified as ticket creations and one of
              them was denied - see the regression tests named
              `test_bash_grep_for_token_never_matches` etc. Widening the
              client-verb gate to Python HTTP clients widens the false-
              positive surface for the same reason, so two additional
              mitigations apply to EVERY Bash classification, not just
              the Python-client path: (i) a command invoking `ds-defer`
              anywhere (`\bds-defer\b`) is never a creation - this is the
              hook's own documented escape hatch, and its example
              `--description` text can legitimately quote the very
              tokens this hook watches for; (ii) a command whose LEADING
              verb (the first whitespace-delimited token, before any
              pipe) is a read/inspection-only command
              (`grep`/`egrep`/`fgrep`/`rg`/`cat`) is never a creation -
              these commands read or print text, they do not issue
              outbound HTTP calls themselves, and a `grep`/`cat`
              command's own search pattern or piped-in body can
              legitimately contain the literal endpoint/verb/mutation
              text as DATA. `gh` was REMOVED from this list (a Skeptic
              round found it wrongly implying `gh` never issues outbound
              HTTP - `gh api` genuinely does). This removal DOES have an
              observable effect: a `gh ... | grep '<text>'` pipe whose
              grep pattern happens to contain a real client-verb literal
              plus a Jira/Linear signal (as DATA, e.g. `grep -c 'curl
              https://api.linear.app/graphql issueCreate mutation'`) is
              no longer exempted purely because `gh` led the first
              segment - it now falls through to the ordinary
              client-verb/endpoint checks, which such literal text can
              satisfy. See
              `test_bash_gh_pipe_no_longer_exempt_after_gh_removal` for
              the pinned before/after behavior and the recommended
              workaround (route such greps through a `cat`/`grep`-only
              pipeline instead).

              BOTH mitigations are CONTAINED to a single, non-compound
              command - a Skeptic round verified `cat p.json | curl -X
              POST .../rest/api/3/issue`, `grep -q x f && curl -X POST
              .../issue`, a grep-leading newline-separated compound, and
              any command merely CONTAINING the literal `ds-defer` token
              anywhere all evaded the matcher entirely, because the
              leading segment's inspection-verb (or the bare presence of
              `ds-defer` text) suppressed the WHOLE command regardless of
              what a later `|`/`&&`/`;`/newline-separated segment
              actually did. The fix: `_bash_is_simple_inspection_command`
              requires EVERY top-level segment of the command (split on
              `|`, `&&`, `;`, and newline - see
              `_bash_command_segments`) to itself lead with an
              inspection-only verb before the inspection-verb mitigation
              applies at all; the `ds-defer` mitigation applies only when
              the command has NO such compound separator anywhere (i.e.
              is a single simple invocation of the escape hatch itself,
              not any command that merely mentions the string). See
              `_bash_is_creation`'s regression tests for both mitigations
              and their containment.
                a. A POST to a Jira `/rest/api/<version>/issue` endpoint
                   NOT followed by `/<key>` (that longer path is a
                   get/update/transition call on an EXISTING issue, not
                   a create) - see `_JIRA_ISSUE_CREATE_PATH_RE`.
                b. Linear's `issueCreate` GraphQL mutation name appearing
                   in a command that also targets the Linear GraphQL API
                   endpoint (`_LINEAR_API_ENDPOINT_RE`) AND carries either
                   an HTTP POST-method signal or the literal `mutation`
                   keyword (`_LINEAR_MUTATION_SIGNAL_RE`) - a real Linear
                   GraphQL curl call almost never passes `-X POST`
                   explicitly (curl implies POST from `-d`/`--data`), so
                   the `mutation` keyword is accepted as an equivalent
                   signal. See `_LINEAR_ISSUE_CREATE_RE`.

         **Triage exemption.** `/ds-feedback-triage` and
         `/ds-ticket-triage` legitimately create multiple tickets in one
         session under an explicit human greenlight per batch (see
         `content/references/delegation-detail.md` item 5: the triage
         creates are gated by a stronger control than this discipline -
         a per-batch human greenlight). Detected by parsing the payload's
         `transcript_path` as JSONL (Claude Code session transcript
         format) and accepting a `<command-name>` or `<command-message>`
         marker for either triage command (`_TRIAGE_MARKER_RE`) ONLY when
         it appears in one of two record shapes that a conductor cannot
         forge via any tool it has access to. **The marker pattern
         requires the leading slash to be OPTIONAL** - a round-2 version
         of this hook hardcoded the no-slash form
         (`<command-name>ds-ticket-triage</command-name>`) as the
         "empirically verified" shape, but every genuine accepted-shape
         record on this machine actually carries the slash
         (`<command-name>/ds-ticket-triage</command-name>`; verified by
         scanning `$CLAUDE_CONFIG_DIR/projects/**/*.jsonl` for real
         `type: "user"` string-content and `type: "system"`/
         `local_command` records). A Skeptic-run independent full-corpus
         measurement (covering BOTH `~/.claude` and `~/.claude-moment8` -
         this machine runs two separate `CLAUDE_CONFIG_DIR` trees, and an
         engineer-run measurement scoped to only one undercounts) found
         **622 top-level transcripts total (481 under `~/.claude` + 141
         under `~/.claude-moment8`) and 3 genuine triage sessions, all 3
         correctly exempted, 0 false positives** against the current
         (slash-optional, `<command-message>`-inclusive) pattern. The
         round-2 no-slash-only pattern matched 0 of those transcripts,
         including every session that genuinely ran a triage command -
         unforgeable, but also permanently dead. Do not re-narrow this
         pattern to a single hardcoded literal without re-running that
         same full-corpus measurement first.

         **Residual Bash false-positive class (verified real, accepted).**
         The `_bash_is_creation` false-positive surface is not zero: a
         command that both (a) invokes a real HTTP client verb or Python
         HTTP-client reference AND (b) carries a Jira issue-create-path
         POST signal or Linear `issueCreate` mutation signal AS LITERAL
         DATA rather than as a real outbound call - and is NOT led by an
         inspection-only verb (see `_bash_is_simple_inspection_command`)
         - still classifies as a creation. Three concrete commands
         verified to still trigger this, all arising only during this
         repo's own hook-development work on this file: `git commit -s
         -m 'feat(hooks): match urllib.request POST to
         /rest/api/3/issue'` (a commit message, not a leading
         grep/cat/rg/egrep/fgrep verb), `echo 'urllib.request POST
         /rest/api/3/issue' > notes.txt` (echo is not on the inspection
         list), and a `python3 - <<EOF` heredoc printing those same
         tokens (the Python-client regex matches the interpreter
         invocation itself, not just an actual HTTP call it makes).
         Accepted as-is: these need 3 such calls in one session to reach
         DENY (the 1st is silent, the 2nd is advisory-only), and they
         only arise while working on THIS hook's own source/tests, not
         in ordinary ticket-creation usage. This is a known, bounded,
         intentionally-unclosed residual - not evidence the matcher is
         clean.
           - a `type: "user"` record whose `message.content` is a plain
             STRING (not a list) - this is how a genuine harness-injected
             slash-command invocation or literal human-typed turn is
             recorded.
           - a `type: "system", subtype: "local_command"` record, whose
             top-level `content` field is a plain string - the harness's
             own local-command marker record.
         Both shapes were verified empirically against real Claude Code
         transcripts on this machine (`$CLAUDE_CONFIG_DIR/projects/.../
         <session-id>.jsonl`, falling back to `~/.claude/projects` only
         when the env var is unset - a hardcoded `~/.claude/projects` path
         has silently globbed an empty directory on this machine before).
         The discriminator that makes this non-forgeable: EVERY tool
         result in a transcript (the only way a conductor's own
         `echo`/`cat`/`git show` output of the marker text could reach the
         transcript) is recorded as `type: "user"` with `message.content`
         being a LIST of `{"type": "tool_result", ...}` blocks, never a
         bare string - confirmed by direct inspection of live transcript
         records. A conductor-authored Bash command that echoes or greps
         the marker string therefore always lands in the excluded
         (list-content) shape, never the accepted (string-content) shape.
         Subagent transcripts are additionally stored in a SEPARATE
         per-session subdirectory (`<transcript-dir>/<session-id>/
         subagents/`), never inlined into the parent's own JSONL file (0
         sidechain records found in the parent transcript across the
         session used for this verification), so a spawned subagent
         cannot inject a marker into the conductor's transcript either.
         This exemption remains SESSION-WIDE and coarse by construction -
         once either marker is found anywhere in the transcript in an
         accepted record shape, every creation call for the rest of the
         session is exempt, even one issued long after the triage
         command's own turn ended. That coarseness is accepted, not
         hidden: closing it would require scoping the exemption to a
         bounded window (e.g. N turns after the command marker), which is
         not implemented here.

         **Residual Bash false-negative class (verified real, accepted).**
         `_bash_is_creation` inspects `tool_input.command` only - it never
         resolves or reads a referenced script file. A create routed
         through a script WRITTEN to disk and then executed
         (`python3 /tmp/scratch/file_tickets.py`) carries none of the
         detection signals in the command string itself (the
         `urllib.request` reference, the `/rest/api/3/issue` path, the
         POST verb all live inside the file, not on the command line), so
         it is invisible to this hook and never advances the counter. This
         is the uncovered sibling of the documented `python3 - <<EOF`
         heredoc case above (there, the body IS in the command string and
         therefore IS visible; here, it never is). Confirmed to have
         happened in this repo's own session history: an agent wrote a
         creation script to a scratchpad directory and ran it, creating
         four Jira tickets, with no `.ticket-batch-*.json` counter file
         written that day. An absent counter file alone does not
         distinguish this false-negative from any of `main()`'s other
         fail-open exits before `_write_state` (see `Failure modes:`
         below for the full list) - directly relevant here, since the
         observed scenario ran from a scratchpad directory and `cwd` had
         no resolvable `.git` ancestor. The counter-file absence is
         consistent with this false-negative class but does not, by
         itself, rule those other paths out. Not attempted: making the hook
         resolve and read an arbitrary referenced script path is
         unbounded (relative paths, `$VAR` expansion, symlinks,
         interpreters other than python, `sh -c`/`env` wrappers) and would
         trade this narrow blind spot for a wide false-positive surface
         plus a filesystem read on every Bash call - a design decision
         out of scope for a mechanical enforcement hook. Known, bounded,
         intentionally-unclosed, same as the false-positive class above.

         **Future hazard - non-forgeability depends on which transcript
         this hook reads.** The "a conductor cannot forge this" claim
         above holds only because this hook reads the MAIN-SESSION
         transcript (`data["transcript_path"]`), which a conductor's own
         Bash output never lands in as string-content. Conductor-authored
         spawn-brief text (e.g. this very finding's own remediation text,
         which quotes the marker literally) DOES land in an
         accepted-shape record inside a SUBAGENT transcript
         (`<session-dir>/subagents/*.jsonl`) - the harness supplies that
         path separately via `agent_transcript_path` (SubagentStop event
         only), and this hook never reads it today. If any future change
         starts passing `agent_transcript_path` into this hook's scan,
         the exemption becomes self-grantable again (a conductor could
         spawn any subagent with a brief that echoes the marker text).
         Do not extend the scan to subagent transcripts without also
         re-deriving the non-forgeability argument from scratch.

         Session state persists at
         `<repo_root>/.agentic/.ticket-batch-<session_id>.json` as
         `{"count": int}` - `session_id` comes from the PreToolUse payload
         (never derived); `repo_root` is resolved from the payload `cwd`
         via `hooks/lib/repo_root.py`'s
         `resolve_agentic_cwd_with_diagnostics()`, never the raw `cwd`
         string. Round-4 rework (coverage-gate finding): this call site
         was missed by every hand-built inventory across four architect
         rounds of the sibling repo-root-anchoring change and originally
         joined the raw payload cwd straight onto the state-file path,
         contradicting the invariant the rest of this branch establishes. Tiered STRICT,
         matching `enforce-skeptic-round-cap.py`'s `_state_path`: this
         counter enforces a session-wide policy invariant (the batching
         cap), and a write at a drifted, unresolved location would not
         merely misplace a log - it would silently reset the counter an
         attacker (or a stray mid-session `cd`) could exploit to bypass
         the cap entirely, which is exactly the "misplaced write actively
         corrupts cross-session-visible state" category
         `hooks/lib/repo_root.py`'s manifest reserves for the strict tier.
         `_state_path` therefore returns `None` when no `.git` ancestor is
         found, and `main()` skips (fails open, same as every other
         unresolvable-payload branch already in this hook) rather than
         writing at the phantom root. `CLAUDE_PROJECT_DIR` would be the
         primary checkout when the payload `cwd` is an isolation
         worktree's - the two are complementary, not interchangeable; this
         hook still only ever consults `cwd` (now via repo-root
         resolution), since ticket creation is a conductor-only action
         that always runs from the primary checkout's `cwd` in practice.

         Decision algorithm (see `_decide()`):
           - next_count = count + 1 on every classified creation call.
           - next_count <= 1 (i.e. this is the 1st creation this
             session): ALLOW silently. Persist count=1. No log_fire call
             (matching every other hook's convention: a silent allow is
             the overwhelming majority case and must not grow the fire
             log).
           - next_count == 2 (the 2nd creation): ALLOW, but emit an
             advisory (`permissionDecision: "allow"` with a non-empty
             `permissionDecisionReason` naming the batching rule) and log
             `"allow_advisory"` via `log_fire()`. Persist count=2.
           - next_count >= 3 (the 3rd and every subsequent creation): a
             valid **operator grant** (see below) is checked first. With
             no valid grant: DENY, citing the batching rule, the concrete
             `bin/ds-defer` escape-hatch command, and the two legitimate
             ways out (`/ds-wrap` to close the session, or routing future
             creates through `/ds-feedback-triage`'s own exemption for a
             greenlit batch - which does not retroactively un-deny THIS
             call). State is NOT persisted on this deny branch (count
             stays at whatever it already was) - a denied call never
             created a ticket, so there is nothing new to count, and this
             keeps every subsequent retry of the same call denied
             identically rather than drifting the counter forward on a
             call that never actually created anything. With a valid
             grant: ALLOW, citing the grant's `reason` back in the
             response and via `log_fire()` (decision `"allow_grant"`),
             persist next_count, and delete the grant file (see below) -
             so a next attempt (with the grant already consumed) falls
             straight back through to the ordinary deny path above.
             Because a grant can now let `next_count` advance past 3, the
             deny/allow-grant message's ordinal is computed from
             `next_count` via `_ordinal()`, not hardcoded to "3rd" as an
             earlier version of this hook did (correct at the time,
             before a grant could ever make this branch fire more than
             once per session at a value other than exactly 3).

         **Operator-granted mid-session exception.** Neither of the two
         "legitimate ways out" cited in the deny message actually lifts
         THIS deny: `/ds-wrap` ends the session rather than continuing it,
         and `/ds-feedback-triage`'s exemption only ever applies to
         creates issued from inside that command's own run (a session
         already mid-triage never reaches this deny branch at all - see
         "Triage exemption" above), so it cannot retroactively unblock a
         call denied outside of it. Before this mechanism existed there
         was genuinely no way for an operator to authorize a 3rd create
         without ending the session - `AE_TICKET_BATCH_GUARD_DISABLE=1` is
         read once by the hook-runner process at its own launch, and a
         conductor `export` in a later Bash tool call never reaches that
         separate process (measured directly: it does not).

         `bin/ds-ticket-grant grant --repo <repo> --session-id <id>
         --reason '<operator's own words>'` (see that file's own module
         docstring for the full CLI contract) writes
         `<repo>/.agentic/.ticket-batch-grant-<safe_session_id>.json` as
         `{"reason": <str>, "granted_at": <UTC ISO8601>}`, where
         `safe_session_id` is byte-for-byte the same sanitization
         `_state_path` below already applies to the batching counter's own
         filename. On the next denied creation this session, `_decide()`
         reads that file via `_load_grant()`: a missing file, unreadable
         file, malformed JSON, non-dict content, or an empty/non-string
         `reason` all resolve to "no grant" (`None`) - every failure mode
         here falls toward the pre-existing deny behavior, never toward a
         phantom allow. A valid grant ALLOWS this one creation, and
         `_consume_grant()` deletes the file immediately (best-effort - a
         delete failure never turns the already-emitted ALLOW decision
         back into a deny, but also never gives a later call a second
         chance to consume the same grant if the delete DID succeed,
         which is the common case) - a stale, un-consumed grant from an
         earlier session or an earlier abandoned request is never
         reusable once a later `grant` invocation for the same session
         overwrites it, and once consumed it cannot allow a 4th (or Nth)
         creation without a fresh `grant` call. This is intentionally
         one-shot rather than a bounded count or a time window - see
         `bin/ds-ticket-grant`'s own module docstring for why a persisting
         exception (count-based or expiry-based) would re-open the exact
         branching-factor hole this whole hook exists to close.
         Attributability is enforced only mechanically (a non-empty
         `reason` string must be present on disk and is echoed back in
         both the hook's `permissionDecisionReason` and its `log_fire()`
         entry) - nothing here verifies an operator actually said the
         quoted words; see `bin/ds-ticket-grant`'s module docstring for
         why that half is left to conductor discipline, not a CLI check.

         Kill switch: `AE_TICKET_BATCH_GUARD_DISABLE=1`, checked FIRST in
         `main()`. Deliberately an environment variable, NOT a
         `.agentic/config.json` key - a config key would add a 22nd
         behavioral toggle and trip the toggle-count-sync obligation
         across 8 prose sites documented in DinoStack's own `MEMORY.md`
         (`README.md`, `content/references/conventions-detail.md`,
         `content/references/risk-config-and-tiers.md`,
         `content/sections/04-risk-classification.md`,
         `docs/components.md`, `docs/configuration-reference.md`), none
         of which this change touches.

Public API: Run as a Claude Code PreToolUse hook (matcher:
            `mcp__mcp-atlassian__jira_create_issue`,
            `mcp__linear__save_issue`, or `Bash`). Reads JSON from stdin,
            writes `hookSpecificOutput` JSON to stdout when denying or
            advising, exits 0 always.

Upstream deps: Python 3 stdlib only (json, os, re, sys, time, pathlib,
               importlib.util for the best-effort `lib/enforcement_log.py`
               and `lib/repo_root.py` imports). No external deps, no
               subprocess.

Downstream consumers: Claude Code hook runner (PreToolUse event, three
                      matcher blocks). Wired via ~/.claude/settings.json
                      by .claude/install.sh using the GUARDED command form
                      (`test -f <path> && python3 <path> || exit 0`) - a
                      bare `python3 {path}` would exit 2 (BLOCKING on
                      PreToolUse) if this file were ever removed while the
                      registration survives, denying every guarded MCP/
                      Bash call in every session. `bin/ds-ticket-grant`
                      is this hook's upstream writer for the operator-
                      grant file (see "Operator-granted mid-session
                      exception" above) - a separate CLI, not imported by
                      this hook; the two are coupled only through the
                      grant file's path/schema, which both sides document
                      and must keep in sync.

Failure modes:
    - Malformed stdin, non-dict tool_input, unclassifiable tool_name/
      command, or a non-creation call (Linear update, Jira GET/search):
      fail-open (exit 0), no state written, no log.
    - `AE_TICKET_BATCH_GUARD_DISABLE=1` in the environment: fail-open
      (exit 0) before any classification, no state written, no log.
    - `cwd` or `session_id` absent/blank/non-string in the payload:
      fail-open (exit 0) - the hook cannot determine where to persist
      state or which session's counter to use.
    - `lib/repo_root.py` fails to import, or the resolved `cwd` has no
      `.git` ancestor within `MAX_DEPTH` (`found_git_ancestor=False`):
      fail-open (exit 0), no state written, no log - matching
      `enforce-skeptic-round-cap.py`'s strict-tier SKIP discipline (see
      module docstring above). A phantom-root write here would silently
      reset the batching counter, so skipping is safer than writing at
      an unresolved location.
    - `transcript_path` absent, unreadable, an individual JSONL line that
      fails to parse, or any other exception while scanning it for the
      triage marker: treated as NOT exempt (`False`) - a malformed line is
      skipped individually (the scan continues), and a triage-exemption
      read failure never silently suppresses enforcement, but also never
      denies solely because the read failed (the call still proceeds
      through the normal count/decide path). The scan reads the
      transcript incrementally (line by line, via `_iter_capped_lines`)
      and stops once `_TRANSCRIPT_READ_CAP_BYTES` of cumulative line
      bytes have been read, so the cap bounds actual I/O and memory, not
      just a post-hoc slice of an already-fully-read string. A SECOND,
      independent cap (`_MAX_LINE_BYTES`) bounds any single physical
      line's own read size - a pathological line with no embedded
      newline is read in `_MAX_LINE_BYTES`-sized chunks and its
      remainder discarded, rather than loaded whole in one `readline()`
      call, so one giant line can never spike memory past that cap
      before the cumulative check even runs.
    - State file present but unparsable JSON: treated as `{"count": 0}` -
      a corrupt state file must never turn into a permanent block.
    - State file write failure (permissions, disk full): the ALLOW/DENY
      decision for THIS call still fires correctly; only the persisted
      count advance may be lost, so a retried call may see a stale
      (lower) count and be permitted again - fail-open, not fail-shut.
    - Any unexpected exception anywhere in the decision path: fail-open
      (exit 0) via an outer try/except in `main()`.
    - Best-effort dynamic import of `lib/enforcement_log.py` for
      `log_fire()`; any import error falls back to a no-op, matching
      every other enforce-*.py hook's fire-logging pattern.
    - Grant file (see "Operator-granted mid-session exception" above)
      missing, unreadable, malformed JSON, non-dict content, or an
      empty/non-string `reason`: treated as no grant - the deny branch's
      pre-existing behavior applies unchanged. This is checked only on
      what would otherwise be a 3rd+-creation DENY; it is never consulted
      on the 1st or 2nd creation, so a grant written before either of
      those has no effect on them (nothing to override - they already
      allow). A grant-file DELETE failure after a successful consuming
      read never turns the already-emitted ALLOW back into a deny for
      THIS call - only a later call could theoretically re-read the
      un-deleted file, and even then only if that later call also reached
      the deny branch with the same (repo, session_id) pair.
    - A creation routed through a script file WRITTEN to disk and then
      executed (`python3 /tmp/scratch/file_tickets.py`) is invisible: this
      hook inspects `tool_input.command` only and never resolves/reads a
      referenced script file, so none of `urllib.request`, the
      `/rest/api/3/issue` path, or the POST verb are visible when they
      live inside the file rather than the command string. Known, bounded,
      intentionally-unclosed - see module docstring "Residual Bash
      false-negative class" above; resolving arbitrary script paths is
      unbounded and out of scope for this hook.

Performance: ~25 ms avg per call, measured directly (20 runs, Python
             interpreter startup only, no state file or transcript I/O
             on the common non-creation path - subprocess dominates; this
             is the whole-process wall time including `python3` startup,
             not the decision logic alone). No subprocess is spawned
             internally; the cost is interpreter startup, not this
             hook's own logic.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

_ADVISORY_AT_COUNT = 2
_DENY_FROM_COUNT = 3

# HTTP method signal required alongside the Jira issue-create path below -
# without this, an ordinary GET/search request against the same endpoint
# family would falsely classify as a creation. Matches "-X POST",
# "--request POST", or a Python-requests-style "method='POST'"/
# 'method="POST"'. Case-insensitive - flag/kwarg forms are unambiguous
# regardless of case.
_HTTP_POST_SIGNAL_RE = re.compile(
    r"(?:-X\s*POST|--request[= ]POST|method\s*=\s*['\"]?POST['\"]?)",
    re.IGNORECASE,
)
# A bare standalone "POST" token (e.g. inside a curl -d/--data command
# where the verb appears unflagged in surrounding prose) - kept as a
# SEPARATE, case-SENSITIVE pattern. Case-insensitive matching here
# false-matched ordinary lowercase English words containing "post" at a
# word boundary (e.g. "post-mortem", a "docs/post/" path segment) since
# "-" and "/" are non-word characters and satisfy \b on both sides. A
# real curl/httpie HTTP-verb token is conventionally uppercase; requiring
# exact-case "POST" keeps the common unflagged-verb case covered while
# eliminating the ordinary-word false-match class.
_HTTP_POST_BARE_WORD_RE = re.compile(r"\bPOST\b")
# Jira REST issue-CREATE path: "/rest/api/<digits>/issue" NOT followed by a
# word char, slash, or hyphen. A trailing "/DS-123" (get/update/transition
# on an EXISTING issue) or a trailing "s" (a different, plural endpoint)
# both fail the negative lookahead and correctly do not match.
_JIRA_ISSUE_CREATE_PATH_RE = re.compile(r"/rest/api/\d+/issue(?![\w/-])")
# Linear's issueCreate GraphQL mutation name, literal word-boundary match.
_LINEAR_ISSUE_CREATE_RE = re.compile(r"\bissueCreate\b")
# Linear's GraphQL API endpoint - required alongside the token above so a
# bare mention of "issueCreate" (e.g. in a grep, docstring, or comment) is
# never sufficient on its own (Critical finding: a Skeptic round found the
# bare-token match denying ordinary read-only Bash calls).
_LINEAR_API_ENDPOINT_RE = re.compile(r"api\.linear\.app/graphql", re.IGNORECASE)
# GraphQL mutation keyword - accepted as an equivalent signal to an
# explicit HTTP POST flag, since a real Linear GraphQL curl call almost
# never passes "-X POST" explicitly (curl already implies POST once
# -d/--data is present).
_LINEAR_MUTATION_SIGNAL_RE = re.compile(r"\bmutation\b", re.IGNORECASE)
# An actual HTTP-client invocation verb - required for BOTH Bash sub-cases
# so a command that merely CONTAINS matching search text (grep/cat/echo/
# git show of the endpoint path or mutation name as literal data, not an
# outbound call) never matches. Word-bounded so "https://..." URLs never
# false-match on the bare "http" alternative ("\bhttp\b" requires a word
# boundary after "http", which "https" fails).
_HTTP_CLIENT_VERB_RE = re.compile(r"\b(curl|wget|http|httpie)\b", re.IGNORECASE)
# A Python HTTP-client reference - an alternative, equally-sufficient
# client-invocation signal to _HTTP_CLIENT_VERB_RE above. curl/wget are
# hook-blocked in this repo (see `.agentic/memory/
# creating-ds-jira-tickets.md`), and `python3 -c
# "...urllib.request.Request(url, method='POST')..."` is the actual
# working direct-REST bypass channel here - the shell-verb-only gate
# covered a channel nobody uses and missed the one everybody does.
_PYTHON_HTTP_CLIENT_RE = re.compile(
    r"\burllib\.request\b|\brequests\.(?:post|put|request)\b|\bhttpx\.(?:post|put|request)\b",
    re.IGNORECASE,
)
# A command invoking the hook's own documented escape hatch is never a
# creation - its `--description`/`--reason` text can legitimately quote
# the very literal tokens this hook watches for (e.g. "curl POST
# /rest/api/3/issue bypass" as a deferred-item description).
_DS_DEFER_RE = re.compile(r"\bds-defer\b")
# Read/inspection-only leading commands - when a command segment's FIRST
# whitespace-delimited token is one of these, that segment reads or
# prints text; it never issues an outbound HTTP call itself, even when
# its own search pattern or a piped-in fetched body contains the
# endpoint/verb/mutation text as literal DATA (e.g. `grep -rn 'curl -X
# POST .../rest/api/3/issue' bin/tests/`). `gh` is deliberately NOT on
# this list - `gh api` genuinely issues outbound HTTP calls, so treating
# it as inspection-only would have been wrong. This has an observable
# effect on a `gh ... | grep '<literal client-verb + Jira/Linear
# signal>'` pipe - see the module docstring point 3 and
# `test_bash_gh_pipe_no_longer_exempt_after_gh_removal`.
_BASH_INSPECTION_LEADING_VERBS = frozenset({"grep", "egrep", "fgrep", "rg", "cat"})

# Top-level command-separator boundaries: pipe, `&&` (also catches a
# bare `&` since it is a substring of `&&`, which is harmless - a lone
# background `&` is not a documented evasion vector here but splitting
# on it too is strictly more conservative, never less), `;`, and
# newline. Used to decide whether the inspection-verb / ds-defer
# suppression below may safely apply to the WHOLE command - see
# `_bash_command_segments` and `_bash_is_simple_inspection_command`.
_COMMAND_SEGMENT_SPLIT_RE = re.compile(r"\||&&|;|\n")


def _bash_leading_verb(command: str) -> str:
    """First whitespace-delimited token of `command`, lowercased. Best-
    effort/naive (no shell-aware parsing) - sufficient for the narrow
    read/inspection-verb suppression this is used for. Callers pass a
    single already-split segment (see `_bash_command_segments`), not a
    raw multi-segment command."""
    parts = command.strip().split(None, 1)
    return parts[0].lower() if parts else ""


def _bash_command_segments(command: str) -> list[str]:
    """Best-effort (no shell-aware parsing) split of `command` into its
    top-level segments across pipe (`|`), `&&`, `;`, and newline
    boundaries - the ways a compound Bash command chains a
    read/inspection command with a DIFFERENT, potentially HTTP-issuing
    command. Empty segments (e.g. from `&&`'s double separator, or a
    trailing separator) are dropped."""
    return [seg for seg in _COMMAND_SEGMENT_SPLIT_RE.split(command) if seg.strip()]


def _bash_is_simple_inspection_command(command: str) -> bool:
    """True only when EVERY top-level segment of `command` (see
    `_bash_command_segments`) leads with a read/inspection-only verb -
    i.e. the command is a single inspection command, or a pipeline/
    compound of ONLY inspection commands, with no non-inspection segment
    chained in by `|`, `&&`, `;`, or newline. Closes a Skeptic-verified
    false-negative class: a prior version keyed suppression off only the
    FIRST segment's leading verb, so `cat p.json | curl -X POST
    .../rest/api/3/issue`, `grep -q x f && curl -X POST .../issue`, and a
    grep-leading newline-separated compound all inherited the leading
    segment's inspection-verb suppression for the WHOLE command,
    silently exempting a real outbound curl/urllib call chained in
    anywhere after the first segment."""
    segments = _bash_command_segments(command)
    if not segments:
        return False
    return all(_bash_leading_verb(seg) in _BASH_INSPECTION_LEADING_VERBS for seg in segments)


def _bash_is_compound(command: str) -> bool:
    """True when `command` contains more than one top-level segment (see
    `_bash_command_segments`) - i.e. a `|`, `&&`, `;`, or newline chains
    in a second command. Used to contain the `ds-defer` escape-hatch
    suppression to a single simple invocation, never a compound where
    `ds-defer` is merely mentioned alongside a different, real call."""
    return len(_bash_command_segments(command)) > 1


# Matches the real harness-recorded `<command-name>` marker for either
# triage command. MEASURED against live Claude Code transcripts on this
# machine ($CLAUDE_CONFIG_DIR/projects/**/*.jsonl): every genuine
# slash-command invocation records the command name WITH its leading
# slash, e.g. `<command-name>/ds-ticket-triage</command-name>` - a prior
# version of this pattern omitted the slash and matched ZERO real
# accepted-shape records (0 of 622 top-level transcripts across
# ~/.claude and ~/.claude-moment8 on this machine - see the module
# docstring "Triage exemption" for the full corpus figures), silently
# making the exemption permanently dead while still reading as
# implemented. The slash is therefore OPTIONAL in the regex
# (`/?`) so this keeps matching even if a future harness version drops
# it - the point is to never again hardcode one exact literal against an
# unverified real shape. Also accepts the sibling `<command-message>`
# tag (present in the same real records, always WITHOUT a leading slash,
# e.g. `<command-message>ds-ticket-triage</command-message>`) as an
# equivalent signal, since both tags are written by the harness itself
# from the same slash-command dispatch and neither is conductor-authored
# text a Bash echo/grep could inject into the excluded (list-content)
# record shape.
_TRIAGE_MARKER_RE = re.compile(
    r"<command-name>/?ds-(?:feedback|ticket)-triage</command-name>"
    r"|<command-message>ds-(?:feedback|ticket)-triage</command-message>"
)

# Bounded read for the transcript scan - a session transcript can grow
# large; this hook only needs to know whether either triage marker
# appears anywhere, so a full-file read (not tailed) is acceptable given
# transcripts are JSONL and typically well under this cap for an
# in-progress session, but the cap still exists as a hard ceiling against
# a pathological file.
_TRANSCRIPT_READ_CAP_BYTES = 20_000_000
# Per-line read cap - bounds a SINGLE pathological line (e.g. one giant
# minified JSON record with no embedded newline), independent of the
# cumulative-bytes cap above. Without this, `for line in fh` reads one
# physical line fully into memory before the cumulative check ever runs,
# so a single oversized line could spike memory well past
# _TRANSCRIPT_READ_CAP_BYTES before the loop gets a chance to stop.
_MAX_LINE_BYTES = 2_000_000


def _load_log_fire():
    """Best-effort dynamic import of the shared fire-logging helper.

    Mirrors the identical lazy, try/except-wrapped import pattern used by
    every sibling enforce-*.py hook (see enforce-skeptic-round-cap.py) - a
    missing or broken sibling module must never crash this hook.
    """
    try:
        import importlib.util as _ilu

        here = Path(__file__).resolve().parent
        mod_path = here / "lib" / "enforcement_log.py"
        spec = _ilu.spec_from_file_location("enforcement_log", str(mod_path))
        mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)
        return mod.log_fire
    except Exception:
        return lambda *a, **k: None


def _bash_is_creation(command: str) -> bool:
    """True when a Bash command is a direct API bypass creating a tracker
    ticket (Jira REST POST to the issue-create endpoint, or Linear's
    issueCreate GraphQL mutation). See module docstring point 3.

    Both sub-cases require an actual HTTP-client invocation signal -
    either a shell client verb (_HTTP_CLIENT_VERB_RE) or a Python
    HTTP-client reference (_PYTHON_HTTP_CLIENT_RE) - so a grep/cat/echo/
    git-show command that merely contains matching text as literal
    search data never matches. Two further mitigations apply before
    either sub-case is even considered, BOTH contained to a single,
    non-compound command so a real outbound call chained in via `|`,
    `&&`, `;`, or newline can never inherit either suppression: a
    `ds-defer` invocation is never a creation when the WHOLE command has
    no compound separator (its own escape-hatch description text can
    legitimately quote the watched tokens - see `_DS_DEFER_RE`), and a
    command every one of whose top-level segments leads with a
    read/inspection-only verb (grep/rg/cat/...) is never a creation (see
    `_bash_is_simple_inspection_command`)."""
    if not command:
        return False
    if not _bash_is_compound(command) and _DS_DEFER_RE.search(command):
        return False
    if _bash_is_simple_inspection_command(command):
        return False
    if not (_HTTP_CLIENT_VERB_RE.search(command) or _PYTHON_HTTP_CLIENT_RE.search(command)):
        return False
    post_signal = _HTTP_POST_SIGNAL_RE.search(command) or _HTTP_POST_BARE_WORD_RE.search(command)
    if _JIRA_ISSUE_CREATE_PATH_RE.search(command) and post_signal:
        return True
    if (
        _LINEAR_API_ENDPOINT_RE.search(command)
        and _LINEAR_ISSUE_CREATE_RE.search(command)
        and (post_signal or _LINEAR_MUTATION_SIGNAL_RE.search(command))
    ):
        return True
    return False


def _is_creation(tool_name: str, tinput: dict) -> bool:
    if tool_name == "mcp__mcp-atlassian__jira_create_issue":
        return True
    if tool_name == "mcp__linear__save_issue":
        # save_issue creates when no `id` is supplied, updates when one is.
        return not tinput.get("id")
    if tool_name == "Bash":
        command = tinput.get("command")
        return _bash_is_creation(command if isinstance(command, str) else "")
    return False


def _record_is_exempt_marker_carrier(rec: dict) -> bool:
    """True when `rec` is one of the two transcript record shapes a
    conductor cannot forge via any tool it has access to - see module
    docstring "Triage exemption" for the empirical verification behind
    this. Does not itself search for the marker text; only decides
    whether the record's shape is eligible to be searched."""
    rec_type = rec.get("type")
    if rec_type == "user":
        msg = rec.get("message")
        return isinstance(msg, dict) and isinstance(msg.get("content"), str)
    if rec_type == "system" and rec.get("subtype") == "local_command":
        return isinstance(rec.get("content"), str)
    return False


def _record_marker_text(rec: dict) -> str:
    """Extract the plain-string text to search for a marker in, for a
    record already confirmed eligible by
    `_record_is_exempt_marker_carrier`."""
    if rec.get("type") == "user":
        return rec["message"]["content"]
    return rec.get("content", "")


def _iter_capped_lines(fh):
    """Yields (line_text, bytes_consumed) pairs, reading each physical
    line via bounded `readline(_MAX_LINE_BYTES)` calls instead of the
    unbounded `for line in fh` - a SINGLE pathological line (no embedded
    newline) is read in `_MAX_LINE_BYTES`-sized chunks rather than loaded
    whole, so the per-line cap bounds actual per-call memory, not just a
    cumulative total measured after the fact. A line that hits the cap
    without reaching a newline is still yielded (as a truncated,
    necessarily-invalid-JSON string) so the caller's existing "skip
    unparsable line, keep scanning" handling applies uniformly - the
    remainder of that same physical line is read and discarded in
    further capped chunks so the next yielded line starts at the next
    real newline boundary."""
    while True:
        chunk = fh.readline(_MAX_LINE_BYTES)
        if not chunk:
            return
        consumed = len(chunk.encode("utf-8", errors="replace"))
        if chunk.endswith("\n") or len(chunk) < _MAX_LINE_BYTES:
            yield chunk, consumed
            continue
        # Oversized line: this chunk hit the cap without reaching a
        # newline. Discard the remainder of the same physical line in
        # further capped chunks, accumulating their bytes too, then
        # yield the first chunk alone (truncated, will fail json.loads).
        while True:
            rest = fh.readline(_MAX_LINE_BYTES)
            if not rest:
                break
            consumed += len(rest.encode("utf-8", errors="replace"))
            if rest.endswith("\n") or len(rest) < _MAX_LINE_BYTES:
                break
        yield chunk, consumed


def _is_triage_exempt(transcript_path) -> bool:
    """Bounded, incremental (line-by-line) scan of the transcript for a
    triage command marker, accepted only in a record shape a conductor
    cannot forge - see module docstring "Triage exemption". Fails to
    False (never exempt) on any read error, missing file, or malformed
    JSONL line - see module docstring "Failure modes"."""
    try:
        if not isinstance(transcript_path, str) or not transcript_path:
            return False
        path = Path(transcript_path)
        if not path.is_file():
            return False
        bytes_read = 0
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line, consumed in _iter_capped_lines(fh):
                bytes_read += consumed
                if bytes_read > _TRANSCRIPT_READ_CAP_BYTES:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                if not _record_is_exempt_marker_carrier(rec):
                    continue
                text = _record_marker_text(rec)
                if _TRIAGE_MARKER_RE.search(text):
                    return True
        return False
    except Exception:
        return False


def _load_repo_root():
    """Best-effort dynamic import of hooks/lib/repo_root.py (mirrors
    _load_log_fire above, and enforce-skeptic-round-cap.py's identical
    loader). Returns None on any load failure - callers must skip the
    .agentic/ read/write rather than fall back to a raw cwd.
    """
    try:
        import importlib.util as _ilu

        here = Path(__file__).resolve().parent
        mod_path = here / "lib" / "repo_root.py"
        spec = _ilu.spec_from_file_location("repo_root", str(mod_path))
        mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


_REPO_ROOT = _load_repo_root()


def _safe_session_id(session_id: str) -> str:
    """Filesystem-safe form of `session_id`, shared by `_state_path` and
    `_grant_path` below so the two families of state file always agree on
    naming - and byte-for-byte identical to `bin/ds-ticket-grant`'s own
    copy of this same function (that CLI has no import path to this
    module, so it is duplicated there rather than shared; keep both in
    sync on any change)."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", session_id.strip()) or "unknown"


def _resolved_agentic_root(cwd: str) -> Path | None:
    """Shared repo-root resolution for both `_state_path` and
    `_grant_path` - returns None when the repo root cannot be resolved.
    Strict tier (see module docstring): a phantom-root read/write here
    would silently reset the batching counter or miss/misplace a grant, so
    this resolves via `resolve_agentic_cwd_with_diagnostics` and refuses
    on `found_git_ancestor=False`, matching
    `enforce-skeptic-round-cap.py`'s `_state_path`.
    """
    if _REPO_ROOT is None:
        return None
    try:
        diag = _REPO_ROOT.resolve_agentic_cwd_with_diagnostics(cwd)
    except Exception:
        return None
    if not diag.get("found_git_ancestor"):
        return None
    return Path(diag["root"]) / ".agentic"


def _state_path(cwd: str, session_id: str) -> Path | None:
    """Returns None when the repo root cannot be resolved - callers must
    skip the read/write on None rather than fall back to a raw cwd."""
    agentic_dir = _resolved_agentic_root(cwd)
    if agentic_dir is None:
        return None
    return agentic_dir / f".ticket-batch-{_safe_session_id(session_id)}.json"


def _grant_path(cwd: str, session_id: str) -> Path | None:
    """Returns None on the same conditions `_state_path` does - a grant
    lookup fails toward "no grant" exactly like the counter fails toward
    "write nothing", never toward a phantom-root read. Filename must stay
    byte-for-byte in sync with `bin/ds-ticket-grant`'s `_grant_path`."""
    agentic_dir = _resolved_agentic_root(cwd)
    if agentic_dir is None:
        return None
    return agentic_dir / f".ticket-batch-grant-{_safe_session_id(session_id)}.json"


def _load_state(path: Path) -> dict:
    try:
        if not path.is_file():
            return {"count": 0}
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"count": 0}
        count = raw.get("count", 0)
        return {"count": count if isinstance(count, int) else 0}
    except Exception:
        return {"count": 0}


def _write_state(path: Path, count: int) -> None:
    """Best-effort atomic write - tmp file + os.replace, pid-suffixed."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "count": count,
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        tmp_path = path.with_suffix(f".tmp.{os.getpid()}")
        tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception:
        # Fail-open: a lost persist means a retried call may see a stale
        # (lower) count and be permitted again - never a false deny.
        pass


def _load_grant(path: Path) -> dict | None:
    """Returns None ("no grant") on a missing file, unreadable file,
    malformed JSON, non-dict content, or an empty/non-string `reason` -
    every failure mode here falls toward the pre-existing deny behavior,
    never toward a phantom allow. See module docstring, "Operator-granted
    mid-session exception"."""
    try:
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return None
        return {"reason": reason.strip()}
    except Exception:
        return None


def _consume_grant(path: Path) -> None:
    """Best-effort one-shot deletion. The ALLOW decision for the call that
    triggered this consumption has already been decided and emitted
    regardless of whether this delete succeeds - a delete failure never
    turns that decision back into a deny; it only (rarely) leaves the file
    behind for a later call to potentially re-read, which is still a
    single, attributable, logged exception, not an unbounded one."""
    try:
        path.unlink()
    except Exception:
        pass


def _ordinal(n: int) -> str:
    """English ordinal suffix for a positive integer ("3rd", "4th", "21st",
    ...). Used for the deny/allow-grant message's ordinal, which is no
    longer always exactly 3 now that a consumed grant can let `next_count`
    advance past `_DENY_FROM_COUNT` (see module docstring, Decision
    algorithm)."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


_ADVISORY_TEMPLATE = (
    "ADVISORY: this is the 2nd tracker-ticket creation this session. Per "
    "content/references/delegation-detail.md §Follow-up Ticket Creation "
    "Discipline, 2+ same-session discoveries are NEVER separate tickets - "
    "they are batched into exactly ONE. A 3rd creation attempt this "
    "session will be DENIED. If this is a genuinely independent, "
    "top-level operator-raised ask (not a mid-session discovery), ignore "
    "this advisory. Otherwise, batch remaining discoveries into this "
    "ticket, or record them with `bin/ds-defer append --repo <repo> "
    "--description '<desc>' --reason failed_promotion_bar` and move on."
)

_DENY_TEMPLATE = (
    "Ticket-batching cap reached: this would be the {ordinal} tracker-"
    "ticket creation this session. Per content/references/"
    "delegation-detail.md §Follow-up Ticket Creation Discipline, 2+ "
    "same-session discoveries are NEVER separate tickets - batch them "
    "into exactly ONE. Do not create this ticket. Instead: record it "
    "with `bin/ds-defer append --repo <repo> --description '<desc>' "
    "--reason failed_promotion_bar` and move on, OR if this genuinely is "
    "a new independent top-level operator-raised ask (not a mid-session "
    "discovery), fold it into the session's existing ticket instead of "
    "creating a new one. If the operator explicitly asks, right now, to "
    "create this ticket anyway: run `bin/ds-ticket-grant grant --repo "
    "<repo> --session-id {session_id} --reason \"<the operator's own "
    "words>\"` then retry this call - this is a one-shot exception, "
    "consumed by this retry, and does not authorize any further create "
    "this session without a fresh grant. Other ways out: run /ds-wrap to "
    "close out this session before starting fresh work; or, for FUTURE "
    "creates only (this does not un-deny the current call), route them "
    "through /ds-feedback-triage, whose own creates are exempt from this "
    "cap under an explicit per-batch human greenlight. "
    "`AE_TICKET_BATCH_GUARD_DISABLE=1` disables this hook outright, but "
    "only if set before this session started - it cannot be set "
    "mid-session."
)

_GRANT_ALLOW_TEMPLATE = (
    "Operator-granted exception consumed for this {ordinal} tracker-"
    "ticket creation this session (grant reason: \"{reason}\"). This "
    "grant was one-shot and has now been deleted - the next creation "
    "this session is evaluated against the ordinary batching cap "
    "(silent 1st, advisory 2nd, denied 3rd+) starting from the count "
    "this call just advanced to, and will need its own fresh grant if "
    "it is also to proceed. Per content/references/delegation-detail.md "
    "§Follow-up Ticket Creation Discipline."
)


def _emit(data: dict, reason: str, decision: str) -> None:
    permission_decision = "deny" if decision == "deny" else "allow"
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": permission_decision,
            "permissionDecisionReason": reason,
        }
    }))
    try:
        _load_log_fire()(data, "enforce-ticket-batching", decision, reason)
    except Exception:
        pass


def main() -> None:
    try:
        if os.environ.get("AE_TICKET_BATCH_GUARD_DISABLE") == "1":
            sys.exit(0)

        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        if not isinstance(data, dict):
            sys.exit(0)

        tool_name = data.get("tool_name")
        raw_tinput = data.get("tool_input")
        tinput = raw_tinput if isinstance(raw_tinput, dict) else {}

        if not _is_creation(tool_name if isinstance(tool_name, str) else "", tinput):
            sys.exit(0)

        cwd = data.get("cwd")
        session_id = data.get("session_id")
        if not isinstance(cwd, str) or not cwd or not isinstance(session_id, str) or not session_id:
            sys.exit(0)

        if _is_triage_exempt(data.get("transcript_path")):
            sys.exit(0)

        path = _state_path(cwd, session_id)
        if path is None:
            # Strict tier: no resolvable repo root under cwd - skip
            # rather than write a phantom-location counter (see module
            # docstring, "Failure modes").
            sys.exit(0)
        state = _load_state(path)
        next_count = state["count"] + 1

        if next_count < _ADVISORY_AT_COUNT:
            _write_state(path, next_count)
            sys.exit(0)

        if next_count == _ADVISORY_AT_COUNT:
            _write_state(path, next_count)
            _emit(data, _ADVISORY_TEMPLATE, "allow_advisory")
            sys.exit(0)

        if next_count >= _DENY_FROM_COUNT:
            # Operator-granted exception check (see module docstring,
            # "Operator-granted mid-session exception"). Only consulted
            # here - never on the 1st/2nd creation, which already allow.
            grant_path = _grant_path(cwd, session_id)
            grant = _load_grant(grant_path) if grant_path is not None else None
            if grant is not None:
                # Grant consumed: this call proceeds, state DOES advance
                # (unlike the plain-deny branch below) because this call
                # is actually about to create a ticket - a future call
                # this session must see the true, advanced count.
                _write_state(path, next_count)
                _consume_grant(grant_path)
                reason = _GRANT_ALLOW_TEMPLATE.format(
                    ordinal=_ordinal(next_count), reason=grant["reason"]
                )
                _emit(data, reason, "allow_grant")
                sys.exit(0)

            # Deny, state unchanged (see module docstring - a denied call
            # never created anything, so there is nothing new to persist).
            # On an all-deny session (no grant ever used) next_count is
            # always exactly 3, since state never advances past
            # _ADVISORY_AT_COUNT (2) on any other branch - but a consumed
            # grant CAN advance it past 3 for a later call in the same
            # session, so the ordinal is derived via `_ordinal()`, not
            # hardcoded, even though "3rd" remains the overwhelmingly
            # common case.
            reason = _DENY_TEMPLATE.format(ordinal=_ordinal(next_count), session_id=session_id)
            _emit(data, reason, "deny")
        sys.exit(0)
    except Exception:
        # Any unexpected error anywhere in the decision path fails open -
        # a hook bug must never block ticket creation outright.
        sys.exit(0)


if __name__ == "__main__":
    main()
