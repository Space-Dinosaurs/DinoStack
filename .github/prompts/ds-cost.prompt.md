---
description: "Render token and wall-time rollups from `.agentic/events.jsonl`. Optionally"
---
# /ds-cost

Render token and wall-time rollups from `.agentic/events.jsonl`. Optionally
shows dollar columns when `~/.agentic/pricing.yml` is present (opt-in;
absent pricing means token-only output, never invented dollar figures).

Implementation: `bin/ds-cost` (Python 3 stdlib + optional pyyaml).

## Usage

```
ds-cost session [<session-uuid>]   # default: current project, all sessions
ds-cost task <task_id>             # rollup for one task_id
ds-cost project [--since YYYY-MM-DD]  # rollup across all sessions in this project
ds-cost team [--json]              # per-developer rollup from .agentic/session-log/
ds-cost operator [--since YYYY-MM-DD] [--json]
                                        # cross-project rollup from ~/.agentic/session-log/
ds-cost retro [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--author <handle>] [--json]
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
Note: all agent types are counted (hook-emitted spawn_start for ad-hoc sessions; conductor spawn_complete for /ds-implement-ticket sessions). Hook-spawn tokens render as n/a in the unpriced table (zeros in the priced table) UNLESS a paired hook-emitted spawn_complete resolved a real subagent transcript (post-DS-160 token resolution), in which case the real summed tokens are shown. Hook-spawn wall-time renders as n/a (unpriced table) or 0.0 (priced table) UNLESS a paired hook-emitted spawn_complete (DS-160) supplied a real wall_seconds figure for that spawn, in which case the real duration is shown.
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

V1 counts all agent types (hook-emitted `spawn_start` for ad-hoc sessions;
conductor-emitted `spawn_complete` for `/ds-implement-ticket` sessions) - no
role is excluded. Hook-emitted spawns render token columns as `n/a` (or `0`
in the priced table) unless a paired hook-emitted `spawn_complete` resolved
a real subagent transcript (post-DS-160 token resolution), in which case the
real summed tokens are shown. Hook-emitted spawns render wall-time as `n/a`
(unpriced table) or `0.0` (priced table) unless a paired hook-emitted
`spawn_complete` (DS-160) supplied a real `wall_seconds` figure for that
spawn - which does not require transcript resolution - in which case the
real duration is shown.

This footer is appended to every `ds-cost session|task|project` output
so users see the disclosure without reading the spec.

## Pricing config (opt-in)

Place at `~/.agentic/pricing.yml`. Rates are USD per 1M tokens. The file is
user-maintained; `/ds-cost` refuses to print dollar figures when it
is absent.

THIS SHAPE IS AN ILLUSTRATIVE EXAMPLE ONLY - the model ids below are
placeholders, not real provider ids.
Substitute your own current model ids and rates; `/ds-cost` looks up each
event's recorded model string as a literal key into `models:`, so any id you
use here works as long as it matches.

```
updated: 2026-04-15
models:
  <model-id-1>:      # e.g. a fast/cheap tier model id
    input: 3.00
    output: 15.00
    cache_creation: 3.75
    cache_read: 0.30
  <model-id-2>:      # e.g. a max-capability tier model id
    input: 15.00
    output: 75.00
    cache_creation: 18.75
    cache_read: 1.50
```

## operator subcommand

`ds-cost operator` reads the **global** mirror at `~/.agentic/session-log/*.jsonl`
and produces a cross-project rollup aggregated by `developer_id` and `project_slug`.
It is the third dimension in the cost-visibility hierarchy:

| Subcommand | Scope | Source |
|---|---|---|
| `team` | One project, all developers | `.agentic/session-log/*.jsonl` (committed via Phase 8 telemetry commits; cross-machine after pull) |
| `operator` | All projects, all developers | `~/.agentic/session-log/*.jsonl` (global mirror) |
| `project` | One project, all sessions | `.agentic/events.jsonl` (local telemetry) |

**Multi-scope handle attribution:** A developer who uses project, profile, and
global handles can appear as separate rows in both `team` and `operator`
output - one row per distinct `developer_id`. This is expected behavior; each
handle is an independent identity. Manual cross-handle aggregation is required
if a unified view is needed.

The `.pending/` staging directory is never globbed - only fully-attributed
lines from `*.jsonl` files are included. If no global logs exist (directory absent or
all files empty), the command prints "No operator session data. Run sessions
with a confirmed identity to populate." and exits 0.

**Options:**

- `--since YYYY-MM-DD` - filter to sessions whose `ts` is on or after the given date
- `--json` - emit machine-readable JSON instead of the fixed-width table

**Example output:**

```
Operator rollup (all projects)
developer/project        sessions    in_tok   out_tok  cache_cr  cache_rd   wall(s)
-----------------------------------------------------------------------------------
alice/my-project                1     84210     37440      9200     41000    4812.1
bob/my-project                  1     31022     14200      3900     16100    2100.0
alice/side-project              1     21004      9310      2100      8800    1204.3
```

Rows are sorted by total tokens descending, keyed by a single
`developer/project` label column; there is no TOTAL row. `ds-cost operator`
does not implement pricing - it never prints dollar columns, and
`~/.agentic/pricing.yml` has no effect on this subcommand's output.

## retro subcommand

`ds-cost retro` reconstructs a rough per-author work rollup from external
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
Retro rollup for dinostack (2026-04-01 -> 2026-05-28)
WARNING: External-source reconstruction. NOT Stage 1 telemetry.
         No per-agent attribution. No token counts. Wall-time is PR-merge proxy only.

Per-author:
  AUTHOR                COMMITS   PRS  MERGED  AVG_MERGE_TIME  FILES_TOUCHED
  alice                      47    12      11            3.2 d           1240
  TOTAL                      47    12      11            3.2 d           1240

Top ticket prefixes (from commit messages):
  DINO            34 commits across  18 tickets
  (no prefix)     13 commits

Stage 1 telemetry: ds-cost team for accurate per-agent breakdown
                   from sessions starting when Stage 1 was active here.
```

Use `ds-cost team` for accurate per-agent and per-token breakdowns from
sessions where Stage 1 telemetry was active (`.agentic/session-log/` populated).
Cross-reference with `.agentic/session-log/` to determine when Stage 1 coverage
begins for your project.

## Cross-harness coverage

V1 is Claude Code only. Codex CLI and Gemini CLI sessions produce no
token data because the transcript schema differs; their rows do not
appear in `ds-cost` output. V2 will add a harness adapter layer.
