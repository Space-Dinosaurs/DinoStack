<!--
Purpose: Full reference for QA gate operational details extracted from
         METHODOLOGY.md §QA Gate. Contains step-by-step gate flows
         (concurrent UI-visible and post-sign-off), per-ticket in-flow rules,
         conductor env preflight, INCONCLUSIVE classification,
         parallel-by-worktree fan-out commands, architect-plan-driven
         scenarios deep prose, and the dev-server boot pattern.

Public API: Read-only reference document. Cross-referenced from:
            content/sections/05-qa-gate.md (pointer),
            content/sections/12-protocol-details.md (QA gate Protocol Details entry).

Upstream deps: content/sections/05-qa-gate.md (parent section; read that
               section first for the QA-fires invariant, skip enums,
               diff-read rule, and re-route limits);
               content/agents/qa-engineer.md (track-scoped qa.md resolution);
               content/references/worktree-lifecycle.md (§Dev-server process
               lifetime ownership, cited by the dev-server boot pattern above).

Downstream consumers: qa-engineer spawns (boot pattern, fan-out commands);
                      conductor orchestration (parallel-by-worktree setup);
                      /ds-implement-ticket Phase 6b (architect-plan-driven scenarios).

Failure modes: Prose; does not execute. The curl-until loop is the canonical
               boot-detection pattern - drift from this reference causes
               qa-engineers to use unreliable fixed-sleep alternatives.

Performance: Standard.
-->

> Parent section: METHODOLOGY.md §QA Gate. Read that section first for the QA-fires invariant, skip enums, diff-read rule, and re-route limits.

# QA Gate - Full Reference

## QA gate flow (UI-visible - concurrent)

**Pre-spawn trigger check:** Before spawning Workers, the conductor inspects the unit's `qa_criteria` (from the Brief or, if no Brief, from the architect plan). If `qa_criteria` is present AND `qa_skip == null` AND `scenarios[]` is non-empty, mark the unit for concurrent QA at review time. The architect's `qa_criteria` is the authoritative trigger - the qa.md trigger patterns are a SUPPLEMENTAL match-set: when both `qa_criteria` and a qa.md trigger match exist, qa-engineer receives both inputs (the scenarios as the test plan, and any matched qa.md project-knowledge entries as supplemental context). qa.md triggers can SUPPLEMENT but CANNOT override `qa_skip != null`. If `qa_criteria` is absent at planning time and the diff is unknown, defer the check to post-Worker (standard flow).

1. Worker returns. Conductor confirms `qa_criteria` indicates QA fires for this unit (`qa_skip == null` and scenarios non-empty).
2. If yes: spawn Skeptic AND `qa-engineer` in a single message (parallel, background). Both receive the diff and the unit's `qa_criteria`. qa-engineer auto-detects qa.md trigger matches at spawn time and pulls supplemental context from any matched entries.
3. Wait for both to return. After qa-engineer returns, run the QA knowledge capture procedure (see §"QA knowledge capture (canonical procedure)" below) before routing on the verdict.
4. If both pass: unit is complete.
5. If Skeptic raises Critical/Major: enter standard Skeptic fix loop. QA re-runs after Skeptic sign-off is achieved.
6. If QA fails (Skeptic already signed off): spawn fix engineer, then re-run QA only. The fix engineer's brief MUST cite `content/references/qa-regression-obligation.md`.

**Phase breadcrumb:** `[phase: qa-review]`

## QA gate flow (non-UI - post-sign-off)

1. Skeptic grants sign-off (minor fixes applied if any)
2. Conductor inspects the unit's `qa_criteria` (from Brief or architect plan).
3. If `qa_criteria` is present AND `qa_skip == null` AND scenarios non-empty: spawn `qa-engineer` with the unit's `qa_criteria` and ticket context. qa-engineer auto-detects qa.md trigger matches at spawn time and pulls supplemental context from any matched entries.
4. QA engineer opens the dev server in a browser (or invokes API/runtime checks per the scenarios' `method`), verifies functionality, returns pass/fail report. Run the QA knowledge capture procedure (see §"QA knowledge capture (canonical procedure)" below) before proceeding to the next step.
5. On PASS: unit is complete.
6. On FAIL: spawn fix engineer for each bug, then re-run QA. The fix engineer's brief MUST cite `content/references/qa-regression-obligation.md`. After Phase 6b clean-exit, if any iteration involved a QA FAIL, the conductor emits the qa-regressions curator to append to `.agentic/qa-regressions.md` (see `/ds-implement-ticket` Phase 6b §"QA regressions curator").

## Per-ticket, in-flow (anti-pattern: end-of-batch QA sweep)

**Phase 6b is a per-ticket, in-flow gate. Conductor MUST NOT aggregate Phase 6b across multiple tickets to run as a final batch step.** Each ticket's QA fires inside that ticket's own loop, before Phase 7. If runtime QA cannot run for ticket N at the moment of its Phase 6b - dev server fails to boot, env file missing, preview deploy is blocked, no working URL - that is a blocker for ticket N specifically, not deferred work to triage at batch end.

When QA cannot run for ticket N, set the unit's QA result to `qa_blocked` and surface the blocker to the operator with the specific cause and the three options:

- **Provide the missing input** (env file, credentials, working preview URL) and re-run Phase 6b.
- **Accept INCONCLUSIVE** with `qa_unverified=true` recorded on the unit (see classification rules below). The PR can still merge, but the ticket carries a known unverified-runtime flag.
- **Abandon the ticket** - close the PR or revert.

Per-ticket QA scales via parallel-by-worktree (see below) - that is the mechanism for "many tickets in flight without a serial QA queue", not batching.

## Conductor preflight before any qa-engineer spawn

Before spawning `qa-engineer` for any unit, the conductor verifies the project env file exists at the path that the dev server will load. The exact path and pull command come from the resolved qa.md (`env_file:` and `env_pull_command:` fields if present) or from project config (e.g. an `env:pull:<app>` script in `package.json`). If the env file is missing, do NOT spawn qa-engineer. Instead surface the verbatim message to the operator:

```
QA env preflight FAILED: <env_file> is missing.
Pull it with: <env_pull_command>
Then re-run Phase 6b for this ticket.
```

Wait for the operator to provide the env file (or accept INCONCLUSIVE per the classification rules below) before proceeding. Spawning qa-engineer just to discover the env is missing wastes a worker turn - the dev server will fail to boot and the qa-engineer will return BLOCKED with no useful signal.

## INCONCLUSIVE classification (no static-only auto-pass)

Static-only QA on an Elevated UI-visible change is approximately zero signal. State hooks, prop-sync bugs, missing render branches, and conditional rendering bugs are invisible to source review. Source verification of an Elevated UI-visible criterion is NOT progress on that criterion.

When the qa-engineer cannot reach a runtime path - preview deploy is blocked AND local-env runtime is unavailable - the unit's QA result is **INCONCLUSIVE** with `qa_unverified=true`, NOT a pass. The conductor surfaces this state to the operator with the same three options as `qa_blocked` above (provide env / accept the unverified state / abandon). The conductor MUST NOT auto-promote INCONCLUSIVE to PASS, and MUST NOT silently proceed to Phase 7 with `qa_unverified=true` set; the operator must explicitly accept that state before merge.

## QA knowledge capture (canonical procedure)

`qa-engineer` has no write access (`disallowedTools: [Edit, Write, Agent]`) and always runs `isolation: "worktree"`, so it cannot append to `.agentic/qa.md` itself - a write from inside an isolation worktree to a `.agentic/`-scoped path lands in that throwaway worktree and is never seen again, because `.agentic/` is gitignored and therefore independent per worktree checkout. Instead, `qa-engineer` returns a `qa-knowledge-json` fenced block in its report text, and the invoker (the conductor, or `/ds-implement-ticket`) is responsible for extracting it and appending the entries to the resolved qa.md in its own checkout. This section is the canonical procedure every call site below points at.

**This is why the report and screenshot-evidence JSON write (`content/agents/qa-engineer.md` §Report structure) targets `/tmp/qa-reports/`, not `.agentic/qa-reports/`.** `/tmp/` is a host-level directory shared across every worktree checkout on the same machine (the same property that already lets `/ds-implement-ticket` Phase 8.5 read `/tmp/qa_*.png` screenshots written from inside the qa-engineer worktree), so a write there survives the worktree's removal and is readable from the conductor's own checkout via the returned `screenshot_evidence_json_path` / `report_path` pointer fields. The `.agentic/qa.md` knowledge-capture case above is different in kind, not merely in path: it is a durable, cross-run project-knowledge file, not a per-run artifact, so it is deliberately never written directly by qa-engineer at all (in any location) - it goes through the `qa-knowledge-json` return payload and an explicit conductor-side append instead. The report/screenshot files are per-run scratch data with a single downstream reader; routing them through `/tmp/` is sufficient and does not need the same indirection.

**Step 1 - extract.** Parse the `qa-knowledge-json` fenced block from the qa-engineer return text (match by info string, either fence character, backticks or tildes). This block still travels inline in the return text - only the screenshot-evidence JSON moved to a file (`screenshot_evidence_json_path` in the pointer return, per `content/agents/qa-engineer.md` §Report structure); `qa-knowledge-json` was not part of that migration. If the block is absent or the JSON fails to parse, treat it as an empty array and continue without error - this is not a failure condition. Filter the parsed array to entries whose `tag` is one of `server`, `timing`, `port`, `auth`, `noise`, `retry`, `tool` and whose `description` is a non-empty string; drop anything else.

**Step 2 - append.** Issue ONE Bash tool call containing the block below, with the filtered array's literal JSON pasted into the heredoc body in place of `[...the extracted array...]`. Do not split this into two tool calls - shell state does not persist across separate Bash invocations, and the temp file this block creates must be written and consumed within the same shell.

**Heredoc-transport invariant.** The pasted text must be standard JSON-array serialization, so no line of it can ever be the bare token `EOF` (JSON scalars are `true`/`false`/`null`, numbers, or quoted strings, and a quoted string cannot contain a raw unescaped newline). Do not hand-edit the pasted array into a non-JSON form.

```bash
# @harness:qa-knowledge-capture
REPO="${REPO:-$(git rev-parse --show-toplevel 2>/dev/null)}"
QA_KNOWLEDGE_TMP=$(mktemp "${TMPDIR:-/tmp}/qa-knowledge-XXXXXX" 2>/dev/null)

if [ -z "$QA_KNOWLEDGE_TMP" ]; then
  echo "WARNING: qa knowledge capture skipped - could not create a temp file (mktemp failed)"
else
cat > "$QA_KNOWLEDGE_TMP" << 'EOF'
[...the extracted array...]
EOF

QA_MD=""
if [ -n "$REPO" ] && [ -f "$REPO/.agentic/qa.md" ]; then
  QA_MD="$REPO/.agentic/qa.md"
elif [ -n "$REPO" ] && [ -f "$REPO/.claude/qa.md" ]; then
  QA_MD="$REPO/.claude/qa.md"
fi

if [ -z "$REPO" ]; then
  echo "WARNING: qa knowledge capture skipped - could not resolve repo root (not inside a git repo?)"
elif [ -z "$QA_MD" ]; then
  echo "WARNING: qa knowledge capture skipped - neither .agentic/qa.md nor .claude/qa.md exists at $REPO"
elif ! command -v python3 >/dev/null 2>&1; then
  echo "WARNING: qa knowledge capture skipped - python3 unavailable"
else
python3 - "$QA_MD" "$QA_KNOWLEDGE_TMP" <<'PY'
import sys, json, re, datetime

qa_md_path, entries_path = sys.argv[1], sys.argv[2]

entries = None
try:
    with open(entries_path, "r", encoding="utf-8") as f:
        raw = f.read()
    entries = json.loads(raw)
except (OSError, ValueError, TypeError) as exc:
    print(f"WARNING: qa knowledge capture skipped - could not parse {entries_path}: {exc}")

if entries is not None and not isinstance(entries, list):
    print(f"WARNING: qa knowledge capture skipped - expected a JSON array, got {type(entries).__name__}")
    entries = None

text = None
if entries is not None:
    try:
        with open(qa_md_path, "r", encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"WARNING: qa knowledge capture skipped - could not read {qa_md_path}: {exc}")

if text is not None:
    text = text.replace("\r\n", "\n")
    if not text.endswith("\n"):
        text += "\n"

    ALLOWED_TAGS = {"server", "timing", "port", "auth", "noise", "retry", "tool"}
    DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    def normalize(s):
        return re.sub(r"\s+", " ", s.strip().lower())

    def strip_bullet_prefix(line):
        s = line.strip()
        s = re.sub(r"^[-*]\s*", "", s)
        s = re.sub(r"^\[\d{4}-\d{2}-\d{2}\]\s*", "", s)
        return s

    sections = list(re.finditer(r"^## Knowledge\n(.*?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE))
    normalized_haystack = set()
    for sec in sections:
        for line in sec.group(1).splitlines():
            if line.strip():
                normalized_haystack.add(normalize(strip_bullet_prefix(line)))

    new_lines = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        tag = e.get("tag", "")
        desc = e.get("description", "")
        if not isinstance(tag, str) or not isinstance(desc, str):
            continue
        if tag not in ALLOWED_TAGS or not desc.strip():
            continue
        needle = normalize(f"{tag}: {desc}")
        if needle in normalized_haystack:
            continue
        date_val = e.get("date")
        date = date_val if isinstance(date_val, str) and DATE_RE.match(date_val) else datetime.date.today().isoformat()
        new_lines.append(f"- [{date}] {tag}: {desc}")
        normalized_haystack.add(needle)

    if not new_lines:
        print("no new knowledge entries")
    elif not sections:
        new_text = text.rstrip("\n") + "\n\n## Knowledge\n" + "\n".join(new_lines) + "\n"
        try:
            with open(qa_md_path, "w", encoding="utf-8") as f:
                f.write(new_text)
            print(f"appended {len(new_lines)} knowledge entry(ies); created ## Knowledge section")
        except OSError as exc:
            print(f"WARNING: qa knowledge capture skipped - could not write {qa_md_path}: {exc}")
    else:
        m = sections[0]
        section_body = m.group(1)
        stripped_body = section_body.rstrip("\n")
        trailing_newlines = section_body[len(stripped_body):] or "\n"
        insertion = stripped_body + ("\n" if stripped_body else "") + "\n".join(new_lines) + trailing_newlines
        new_text = text[: m.start(1)] + insertion + text[m.end(1):]
        try:
            with open(qa_md_path, "w", encoding="utf-8") as f:
                f.write(new_text)
            print(f"appended {len(new_lines)} knowledge entry(ies)")
        except OSError as exc:
            print(f"WARNING: qa knowledge capture skipped - could not write {qa_md_path}: {exc}")
PY
fi

rm -f "$QA_KNOWLEDGE_TMP" 2>/dev/null || true
fi
```

**Structural properties that MUST hold** (all verified by execution - do not "improve" them): column 0 throughout including both `EOF` and `PY` heredoc terminators; the `# @harness:` marker is the first non-blank line inside the fence; zero shell-level `exit` statements (required by `bin/tests/lib/md_shell_extract.py`'s `COMPLETION_MARKER` precondition); `mktemp` uses trailing `X`s with NO suffix (BSD/macOS does not randomize non-trailing `X`s); every skip path prints a `WARNING:` and falls through; `rm -f` fires on every path where a temp file was created.

**Call sites.** This procedure runs after every qa-engineer return, regardless of verdict, at these five points: the concurrent UI-visible QA gate flow (above), the `/ds-implement-ticket` Phase 6b loop's "Receive QA output" step (every iteration), the non-UI post-sign-off QA gate flow (below), the multi-PR fan-out (below, before worktree removal), and `release-orchestrator`'s Phase 8 post-deploy QA - the conductor performs that `qa-engineer` spawn directly (see `content/references/agent-team.md` §"On a `QA_NEEDED` return"; `release-orchestrator` cannot spawn subagents itself), so it is a normal conductor-performed qa-engineer return like the other four and this procedure applies to it the same way. It deliberately does NOT run for fully ad-hoc "run QA" spawns - knowledge from that path continues to be dropped.

## Multi-PR / multi-ticket parallel-by-worktree

When more than one PR (or unit) is awaiting QA, the conductor defaults to parallel verification - one qa-engineer per PR, each in its own worktree, each on a unique port. Single-message fan-out:

```bash
# For each PR awaiting QA at index N (0-based):
git worktree add .agentic/worktrees/qa-<branch> <branch>
# Spawn qa-engineer with isolation: "worktree" and PORT=$((3000 + N)) injected into the brief.
```

All qa-engineers run concurrently (background, single message). After each returns, run the QA knowledge capture procedure (see §"QA knowledge capture (canonical procedure)" above) against that PR's return, then evaluate the worktree for removal.

This worktree is distinct from the harness-created isolation worktree (`.claude/worktrees/agent-<agentId>`) the qa-engineer's own tool calls execute inside; removing this worktree does not affect the isolation worktree's lifecycle.

```bash
if [ -z "$(git -C .agentic/worktrees/qa-<branch> status --porcelain 2>/dev/null)" ]; then
  git worktree remove .agentic/worktrees/qa-<branch>
else
  echo "WARNING: worktree .agentic/worktrees/qa-<branch> has uncommitted changes; skipping cleanup"
fi
```

Serial multi-PR QA is reserved for cases where the parallel path is structurally blocked (e.g. only one preview environment available). Default is parallel.

## Architect-plan-driven scenarios

Phase 6b reads `qa_criteria.scenarios[]` directly from the architect plan or Brief - that block is the authoritative test plan. The architect plan template MUST include the `qa_criteria` YAML block on every Elevated unit (Critical Skeptic finding if absent; see `content/agents/architect.md`). The qa-engineer brief is a thin wrapper supplying the URL, the dev-server boot recipe, the diff, and the `ticket_id`; it does NOT re-author scenarios. Conductor MUST NOT hand-author scenarios at spawn time - that recreates the failure mode where verification drifts from what the architect committed to.

**Scenario method dispatch.** Each scenario's `method` field determines the qa-engineer procedure:
- `browser` - standard browser interaction via agent-browser or Playwright (see `content/agents/qa-engineer.md` §2 Browser verification).
- `api` - curl or Playwright network call against the endpoint under test.
- `runtime-required` - runtime execution required; cannot fall back to source review.
- `visual_conformance` - field-by-field comparison against `expected_visual_claims[]` (see `content/agents/qa-engineer.md` §Visual conformance scenarios).
- `accessibility` - WCAG conformance check via `@axe-core/playwright`; iterates per viewport; reports violations by impact level (see `content/agents/qa-engineer.md` §Accessibility scenarios).
- `perceptual_diff` - pixel-level regression against committed baselines via `page.screenshot()` + pixelmatch comparison; opt-in via `.agentic/config.json` `perceptual_diff_enabled: true` (see `content/agents/qa-engineer.md` §Perceptual diff scenarios).
- `motion` - Runtime verification that animations respect `prefers-reduced-motion: reduce`. qa-engineer uses CDP `Emulation.setEmulatedMedia` and computed-style diffs. See `content/agents/qa-engineer.md` `## Motion scenarios` section.

**Viewport iteration.** When `qa_criteria.viewport` is set (default `[desktop]`), qa-engineer runs each scenario against every viewport in the resolved list. A per-scenario `viewport` field replaces the root list (does not extend it). Report rows are per `(scenario × viewport)` tuple. Canonical sizes: mobile 375x667, tablet 768x1024, desktop 1440x900. Override via qa.md `viewport` knowledge tag. Full procedure in `content/agents/qa-engineer.md` §2 Browser verification (viewport resolution step).

## qa-engineer dev-server boot pattern

When the qa-engineer needs to start a local dev server, it resolves the boot command in this order:

1. Per-track qa.md `command:` field (`.agentic/qa.md` preferred, legacy `.claude/qa.md` fallback; for multi-track repos, the track-scoped qa.md takes priority over the root index per `content/agents/qa-engineer.md`).
2. Fallback to the project's package.json `dev` script (`npm run dev`, `pnpm dev`, etc.) if no qa.md `command:` is set.

After starting the server, the qa-engineer polls for readiness with a curl-until loop bounded by a 90-second timeout - never a fixed `sleep`:

```bash
PORT=<port>
TIMEOUT=90
ELAPSED=0
until curl -s -o /dev/null -w '%{http_code}' "http://localhost:${PORT}/" | grep -qE '^(200|3..)$'; do
  sleep 2
  ELAPSED=$((ELAPSED + 2))
  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    echo "Dev server failed to respond on port ${PORT} within ${TIMEOUT}s"
    exit 1
  fi
done
```

Boot detection by fixed `sleep` is unreliable across machines and network conditions; the curl-until loop is the canonical pattern.

See `content/references/worktree-lifecycle.md` §Dev-server process lifetime ownership: a server booted here is run-scoped only and will not survive the agent's run on this harness - treat it as such rather than as a durably running service.
