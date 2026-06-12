# /agentic-cost

Render token and wall-time rollups from `.agentic/events.jsonl`. Optionally
shows dollar columns when `~/.agentic/pricing.yml` is present (opt-in;
absent pricing means token-only output, never invented dollar figures).

Implementation: `bin/agentic-cost` (Python 3 stdlib + optional pyyaml).

## Usage

```
agentic-cost session [<session-uuid>]   # default: current project, all sessions
agentic-cost task <task_id>             # rollup for one task_id
agentic-cost project [--since YYYY-MM-DD]  # rollup across all sessions in this project
agentic-cost team [--json]              # per-developer rollup from .agentic/session-log/
agentic-cost operator [--since YYYY-MM-DD] [--json]
                                        # cross-project rollup from ~/.agentic/session-log/
agentic-cost retro [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--author <handle>] [--json]
                                        # historical rollup from git log + gh pr list
```

The CLI reads `.agentic/events.jsonl` from the current working directory.
Output is a fixed-width table sorted by agent name, with a TOTAL row.
Every output ends with the V1 disclosure footer (see "V1 scope" below).

## Output: pricing absent

```
agent       spawns   in       out      cache_cr  cache_rd  wall(s)
engineer    6        21044    9120     88421     311009    612.4
skeptic     7        4012     1840     21001     94221     401.2
qa-engineer 1        801      244      3001      9100      88.0
TOTAL       14       25857    11204    112423    414330    1101.6

Pricing not configured. Create ~/.agentic/pricing.yml to enable dollar columns.
Note: V1 instruments engineer/skeptic/qa only; architect/investigator/debugger spawns are not counted.
```

## Output: pricing present

When `~/.agentic/pricing.yml` is readable and contains a `models:` map,
dollar columns appear and an "Rates as of YYYY-MM-DD from
~/.agentic/pricing.yml." footer is added. If `pricing.yml.updated` is
older than 90 days, an additional "Rates are >90 days old; verify
before quoting." line follows. Models missing from the rate file render
their dollar columns as `?` and are listed under "Missing rates for: ...".

If `pricing.yml` exists but `pyyaml` is not installed, the CLI falls back
to token-only output and prints "Install pyyaml for pricing support."

## V1 scope

V1 instruments engineer/skeptic/qa only; architect/investigator/debugger spawns are not counted.

This footer is appended to every `agentic-cost session|task|project` output
so users see the disclosure without reading the spec.

## Pricing config (opt-in)

Place at `~/.agentic/pricing.yml`. Rates are USD per 1M tokens. The file is
user-maintained; `/agentic-cost` refuses to print dollar figures when it
is absent.

```
updated: 2026-04-15
models:
  claude-sonnet-4-6:
    input: 3.00
    output: 15.00
    cache_creation: 3.75
    cache_read: 0.30
  claude-opus-4-7:
    input: 15.00
    output: 75.00
    cache_creation: 18.75
    cache_read: 1.50
```

## operator subcommand

`agentic-cost operator` reads the **global** mirror at `~/.agentic/session-log/*.jsonl`
and produces a cross-project rollup aggregated by `developer_id` and `project_slug`.
It is the third dimension in the cost-visibility hierarchy:

| Subcommand | Scope | Source |
|---|---|---|
| `team` | One project, all developers | `.agentic/session-log/*.jsonl` (project-local, local-only) |
| `operator` | All projects, all developers | `~/.agentic/session-log/*.jsonl` (global mirror) |
| `project` | One project, all sessions | `.agentic/events.jsonl` (local telemetry) |

**Per-repo handle attribution:** A developer who uses `agentic-identity init --scope project`
with a handle different from their global handle will appear as two separate rows in both
`team` and `operator` output - one row per distinct `developer_id`. This is expected behavior;
each handle is an independent identity. Manual cross-handle aggregation is required if a
unified view is needed.

The `.pending/` staging directory is never globbed - only fully-attributed
lines from `*.jsonl` files are included. If no global logs exist (directory absent or
all files empty), the command prints "No operator-level session logs found." and exits 0.

**Options:**

- `--since YYYY-MM-DD` - filter to sessions whose `ts` is on or after the given date
- `--json` - emit machine-readable JSON instead of the fixed-width table

**Example output (pricing absent):**

```
Operator rollup (all projects)

developer_id          project_slug          sessions   in       out      wall(s)
fullmetalblanket      agentic-engineering         12   84210    37440   4812.1
fullmetalblanket      helios                       4   21004     9310   1204.3
alice                 helios                       7   31022    14200   2100.0
TOTAL                                             23  136236    60950   8116.4

Note: V1 instruments engineer/skeptic/qa only; architect/investigator/debugger spawns are not counted.
Pricing not configured. Create ~/.agentic/pricing.yml to enable dollar columns.
```

When `~/.agentic/pricing.yml` is present, dollar columns appear following the same
rules as `team` and `project` (rates, 90-day staleness warning, missing-rate `?`
cells).

## retro subcommand

`agentic-cost retro` reconstructs a rough per-author work rollup from external
data sources for projects that pre-date Stage 1 telemetry (or any period where
`.agentic/session-log/` is empty). It is an escape hatch for historical
analysis - not a replacement for true Stage 1 telemetry.

> **WARNING: External-source reconstruction. NOT Stage 1 telemetry.**
> No per-agent attribution. No token counts. Wall-time is PR-merge proxy only.

Data sources (used in order of availability):

1. **`gh pr list`** - if `gh` is installed and authenticated. Provides PR count,
   merged count, files-changed sum, and time-from-open-to-merge as a wall-clock
   proxy. When `gh` is unavailable, a one-line warning is printed and git-only
   mode runs.
2. **`git log`** - always available in a git repo. Provides commit count per
   author, files-touched sum, and ticket-prefix scan (regex `[A-Z]{2,10}-\d+`
   matched against commit subjects).

Example output:

```
Retro rollup for agentic-engineering (2026-04-01 -> 2026-05-28)
WARNING: External-source reconstruction. NOT Stage 1 telemetry.
         No per-agent attribution. No token counts. Wall-time is PR-merge proxy only.

Per-author:
  AUTHOR                COMMITS   PRS  MERGED  AVG_MERGE_TIME  FILES_TOUCHED
  fullmetalblanket           47    12      11            3.2 d           1240
  TOTAL                      47    12      11            3.2 d           1240

Top ticket prefixes (from commit messages):
  DINO            34 commits across  18 tickets
  (no prefix)     13 commits

Stage 1 telemetry: agentic-cost team for accurate per-agent breakdown
                   from sessions starting when Stage 1 was active here.
```

Use `agentic-cost team` for accurate per-agent and per-token breakdowns from
sessions where Stage 1 telemetry was active (`.agentic/session-log/` populated).
Cross-reference with `.agentic/session-log/` to determine when Stage 1 coverage
begins for your project.

## Cross-harness coverage

V1 is Claude Code only. Codex CLI and Gemini CLI sessions produce no
token data because the transcript schema differs; their rows do not
appear in `agentic-cost` output. V2 will add a harness adapter layer.
