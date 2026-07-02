<!--
Purpose: Detailed activation-preflight reference blocks extracted from
         content/sections/01-activation-preflight.md. Contains: Step 5
         (first-activation notice - TTY/QUIET gate, sentinel write contract,
         sentinel body, notice text verbatim) and Step 6 (scaffolding-sync
         check - agentic-migrate check/apply flow, gitignore patterns,
         AGENTS.md carve-out).

Public API: Read-only reference document. Cross-referenced from:
            content/sections/01-activation-preflight.md (inline pointers
            replacing the Step 5 and Step 6 detail blocks).

Upstream deps: content/sections/01-activation-preflight.md (parent section;
               read Steps 1-4 and Step 7 there for activation decision and
               no-op path); bin/agentic-migrate (scaffolding-sync binary
               invoked in Step 6).

Downstream consumers: every adapter that implements the activation preflight
                      (Claude, Codex, Cursor, Hermes, OpenCode, etc.) must
                      implement Step 5 and Step 6 per this spec; CI checks
                      adapter-sync against source.

Failure modes: Sentinel write is create-only (O_EXCL / link() pattern);
               concurrent racers produce exactly one notice. Filesystem
               errors other than EEXIST are silently swallowed - the notice
               may re-print on the next session. agentic-migrate failures
               are silently swallowed; methodology proceeds.

Performance: Standard (single file write + optional binary shell-out).
-->

> Parent section: `content/sections/01-activation-preflight.md`. Read Steps 1-4 and Step 7 there for the activation decision and no-op path.

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
   # agentic-engineering: first-activation notice has been shown for this project.
   # Deleting this file re-arms the notice only; it does not change activation state.
   # To opt out, use /agentic-disable.
   ```

   **Notice text (verbatim, single line, printed to stdout when create succeeds):**
   ```
   agentic-engineering: active (mode=<mode>, marker=<marker or 'none'>, profile=<profile>). Run /agentic-status to inspect, /agentic-disable to opt out.
   ```
   Values come from the resolver outputs of Steps 1-3.

## Step 6: Scaffolding-Sync Check

6. **Scaffolding-sync check.** Runs only when Step 4 resolved to active. Silent-fail: any error swallowed; methodology proceeds.

   a. Invoke `agentic-migrate check` (resolved from PATH or adapter install bin/). If binary not found: skip silently.
   b. If status is "ok" (project version >= manifest version): no-op.
   c. If status is "drift": invoke `agentic-migrate apply`. The binary acquires `~/.agentic/.scaffolding-apply.lock` (on EWOULDBLOCK: another session is applying - skip silently). It applies additive gitignore patterns (exact-line match, strip trailing whitespace), writes missing `.agentic/` seed files (never overwrites existing), updates `scaffolding_version` in `.agentic/config.json` when all additive rules satisfied, and appends one-line audit to `.agentic/context.md`. The `markers:` key in the manifest is IGNORED by this path (operator-owned; surface via `/migrate-project --include-destructive` only).
   d. AGENTS.md is never modified by this step. Operator-owned scaffolding requires `/migrate-project --include-destructive`.
