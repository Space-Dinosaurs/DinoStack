<!--
Purpose: Detailed activation-preflight reference blocks extracted from
         content/sections/01-activation-preflight.md. Contains: Step 5
         (first-activation notice - TTY/QUIET gate, sentinel write contract,
         sentinel body, notice text verbatim), Step 6 (scaffolding-sync
         check - ds-migrate check/apply flow, gitignore patterns,
         AGENTS.md carve-out) and Step 7 (prior-session learning-shard
         rollup - single ds-learning-shard rollup call, conductor-side
         classification, silent empty path).

Public API: Read-only reference document. Cross-referenced from:
            content/sections/01-activation-preflight.md (inline pointers
            replacing the Step 5, Step 6 and Step 7 detail blocks).

Upstream deps: content/sections/01-activation-preflight.md (parent section;
               read Steps 1-4 and Step 8 there for activation decision and
               no-op path); bin/ds-migrate (scaffolding-sync binary
               invoked in Step 6); bin/ds-learning-shard (shard store CLI
               invoked in Step 7); content/references/capture-classification.md
               (classification table applied in Step 7).

Downstream consumers: every adapter that implements the activation preflight
                      (Claude, Codex, Cursor, Hermes, OpenCode, etc.) must
                      implement Steps 5-7 per this spec; CI checks
                      adapter-sync against source.

Failure modes: Sentinel write is create-only (O_EXCL / link() pattern);
               concurrent racers produce exactly one notice. Filesystem
               errors other than EEXIST are silently swallowed - the notice
               may re-print on the next session. ds-migrate and
               ds-learning-shard failures are silently swallowed;
               methodology proceeds.

Performance: Standard (single file write + optional binary shell-out).
-->

> Parent section: `content/sections/01-activation-preflight.md`. Read Steps 1-4 and Step 8 there for the activation decision and no-op path.

## Step 5: First-Activation Notice

5. **First-activation notice (one-time, per-project, TTY-only).** Triggered only when Step 4 resolved to active (any proceed branch). Otherwise skip this step entirely.

   **TTY/QUIET gate.** If `os.environ.get("AGENTIC_QUIET") == "1"` OR `not sys.stdout.isatty()`, skip BOTH the notice print AND the sentinel write. Activation proceeds normally without producing the notice or creating the sentinel. This prevents fixture contamination in eval harness runs and unwanted output in CI/headless contexts.

   **Sentinel write contract (race-safe; create-only).** Two parallel subagent activations on the same fresh project must produce exactly one notice and exactly one sentinel; the loser stays silent. The notice prints if and only if the create-only write succeeded.

   1. Compute path: `<project_root>/.agentic/.activated`.
   2. Ensure `.agentic/` exists (`mkdir -p`); failures silently swallowed - do not crash.
   3. Attempt **create-only** write (must fail if the file already exists):
      - Python: `open(path, 'x')` (raises `FileExistsError` if present).
      - Shell: write to `<path>.tmp.<pid>`, then `ln <tmp> <path>` (atomic, fails on EEXIST), unlink tmp.
      - <!-- Race-safe pattern: O_EXCL / link() guarantees that only one of N concurrent racers wins the create; losers see EEXIST and stay silent. Do NOT replace with `if exists: ... else: write` - that pattern has a TOCTOU race. -->
   4. **Print the notice if and only if the create succeeded.** On EEXIST (sentinel already present), skip the print silently. Losers in a race stay silent.
   5. Filesystem errors other than `EEXIST` (read-only filesystem, permission denied, ENOSPC, etc.) are silently swallowed; the notice may re-print on the next session. Methodology must not crash.

   **Sentinel body (exactly three lines, plain text):**
   ```
   # dinostack: first-activation notice has been shown for this project.
   # Deleting this file re-arms the notice only; it does not change activation state.
   # To opt out, use /ds-disable.
   ```

   **Notice text (verbatim, single line, printed to stdout when create succeeds):**
   ```
   dinostack: active (mode=<mode>, marker=<marker or 'none'>, profile=<profile>). Run /ds-status to inspect, /ds-disable to opt out.
   ```
   Values come from the resolver outputs of Steps 1-3.

## Step 6: Scaffolding-Sync Check

6. **Scaffolding-sync check.** Runs only when Step 4 resolved to active. Silent-fail: any error swallowed; methodology proceeds.

   a. Invoke `ds-migrate check` (resolved from PATH or adapter install bin/). If binary not found: skip silently. The JSON it prints carries a `gitignore_verification` field (`"behavioral"` or `"unavailable"` - see `_compute_negations_defeated` in `bin/ds-migrate`); a `"behavioral"` `status: "ok"` is authoritative for every exact-path manifest negation and, for the four directory-form negations (`!.agentic/session-log/` + its `/**` twin, and `!.agentic/memory-shards/` + its `/**` twin), for any real file already on disk under that directory - see `content/commands/ds-init-project.md` Step 9 for the full scope of what "behavioral" does and does not yet cover (a narrow, self-healing directory-negation probe-guessing limit). A `"unavailable"` `ok` is the pre-round-10 syntactic fallback, not behaviorally verified - Step 6b below still no-ops on it the same as a `"behavioral"` `ok`, unlike `/ds-init-project`'s onboarding check, because this step has no interactive human-reads-the-file fallback to escalate to; the two consumers agree on this fact (an `"unavailable"` `ok` is not authoritative) even though they take different actions on it.
   b. If status is "ok" (project version >= manifest version): no-op, regardless of `gitignore_verification` value (see the note in 6a above on why this differs from `/ds-init-project`'s stricter onboarding check).
   c. If status is "drift": invoke `ds-migrate apply`. The binary acquires `~/.agentic/.scaffolding-apply.lock` (on EWOULDBLOCK: another session is applying - skip silently). It applies additive gitignore patterns (exact-line match, strip trailing whitespace), writes missing `.agentic/` seed files (never overwrites existing), updates `scaffolding_version` in `.agentic/config.json` when all additive rules satisfied, and appends a one-line audit entry to the `.agentic/context.d/scaffolding-notices.md` shard (NOT to `.agentic/context.md`, which is a derived rollup that would discard the entry on the next Stop turn). The `markers:` key in the manifest is IGNORED by this path (operator-owned; surface via `/ds-migrate-project --include-destructive` only).

      `apply` exits 3, prints an actionable stderr message naming the affected paths, and does NOT stamp `scaffolding_version`, when behavioral detection still reports a manifest-negated path ignored by git after every automatic repair has run (a spelling neither the ordering-repair nor the bare-form-repair machinery recognizes). This step's "any error swallowed" discipline (see the step-6 lead sentence above) still applies - the stderr message itself is not read here - but exit 3 is deliberately NOT in the same class as an ordinary swallowed error: `apply` appends a `[scaffolding-sync] FAILED: ...` line naming the affected paths to the SAME `scaffolding-notices.md` shard the success case writes its `[scaffolding-sync] Applied ...` line to, so the failure is visible in the one channel this step's silent-fail discipline does not discard. A prior session's success entry in that shard does not mean a later session's exit-3 failure went unrecorded - each apply invocation appends its own entry.
   d. If status is "self_repo_exempt": no-op. This value is distinct from both "ok" and "drift" and means `project_root` IS the dinostack/agentic-engineering methodology source repo itself, not a scaffolding consumer (see `_is_self_repo` in `bin/ds-migrate`) - the repo's own `.agentic/` gitignore rule is a deliberate, negation-free categorical `.agentic/*` (root AGENTS.md: "DinoStack does not commit its own `.agentic/` runtime files"), and consumer-manifest drift/apply is not a meaningful question against it. `ds-migrate apply` against a self-repo `project_root` is also a no-op (it prints why on stdout rather than writing anything) - never invoke `apply` on a "self_repo_exempt" status, though doing so would be harmless since `apply` re-derives the same exemption independently rather than trusting a caller-supplied status.
   e. AGENTS.md is never modified by this step. Operator-owned scaffolding requires `/ds-migrate-project --include-destructive`.

## Step 7: Prior-Session Learning-Shard Rollup

7. **Prior-session learning-shard rollup.** Runs only when Step 4 resolved to active. This is what drains the per-session learning shards that write-capable subagents append in-flight (`bin/ds-learning-shard append`, per `content/references/learnings-capture-instruction.md`), so capture no longer depends on an operator remembering to run a wrap command at end of session. It fires at the top of the very next session of any kind, on every adapter, because every adapter has an activation-preflight moment by definition. Do not replace it with a daemon, a resume flag, or a harness-specific hook.

   a. Make exactly ONE call: `ds-learning-shard rollup --repo <cwd>` (resolved from PATH or the adapter install `bin/`). Pass no `--session-key`. The CLI prints a JSON array to stdout and exits 0 on every path, soft-fails included.

   b. **Prior sessions only.** An unscoped rollup can only see shards written before this session started, because the current session has appended nothing yet at preflight time. Repeat calls are non-events: `.rolled-up.json` bookkeeping is keyed on the SET of CLI-owned entry ids already emitted, so an entry is emitted exactly once. No extra scoping is needed; passing `--session-key` here would be wrong, since the key of interest belongs to a session that has already ended.

   c. **Empty is the common case and must cost nothing.** On `[]`, stop immediately: print nothing, spawn nothing, write nothing. This step runs at the top of every session, so a chatty or expensive empty path is a step operators will disable.

   d. **Classification is conductor-side; the CLI performs none.** For a non-empty array, apply the guardrail-first precedence chain and table in `content/references/capture-classification.md` to each entry. Forward only the entries whose verdict is `Capture: MUST` to `learnings-agent`, spawning it once for the batch if it is not already running. Entries classified `Capture: SKIP` are dropped silently. Do not invent a parallel classification path.

   e. **Soft-fail absolutely.** Binary not found, non-zero exit, empty output, or output that does not parse as a JSON array: treat as `[]` and proceed. Never print a diagnostic, never retry, never block session start. A dropped rollup is recovered by the next session's preflight, since unemitted entries stay unmarked.
