<!--
Purpose: Operator-facing guide to the Graphify integration in AE. Explains
         what graphify does when connected to the methodology, how to enable
         it (presence-gated - no toggle), what changes at risk classification
         and investigation time, and the fail-safe behavior when no graph is
         present.

Public API: Operator-facing prose. Entry point for anyone who wants to
            understand or enable the graph-assisted risk signal.
            The authoritative behavioral spec lives in
            content/references/risk-config-and-tiers.md
            §Graph-derived risk signal and in content/agents/investigator.md
            §Graph-assisted blast radius.

Upstream deps: content/references/risk-config-and-tiers.md
               (graph-derived risk signal, freshness algorithm, autonomous
               refresh, GRAPHIFY_OUT);
               content/sections/02-delegation.md
               (graph-derived escalation rule);
               content/agents/investigator.md
               (graphify affected, read-only lock, staleness fallback).

Downstream consumers: docs site root index.

Failure modes: Stale if the graphify v8 report format changes (heading
               strings for God Nodes / Surprising Connections), or if
               investigator's graphify affected usage changes. Update
               alongside content/references/risk-config-and-tiers.md.

Performance: Standard.
-->

# Graphify integration

When a Graphify knowledge graph is present at the repo root, AE uses it in two
places: risk classification (the conductor) and blast-radius investigation (the
investigator agent). Both paths are presence-gated - no config toggle required.
If no graph exists, behavior is identical to today's non-graph baseline.

## What graphify is

[Graphify](https://github.com/graphifyy/graphifyy) (`pip install graphifyy`)
builds a code knowledge graph from your repository's source files. It writes
two artifacts: `graphify-out/graph.json` (the graph database) and
`GRAPH_REPORT.md` (a human-readable summary at the repo root).

The report's two relevant sections are:
- **God Nodes** - the highest-degree symbols in your codebase: the core
  abstractions that everything else connects to.
- **Surprising Connections** - cross-file couplings that are non-obvious from
  reading any one file.

AE reads those sections to detect when a proposed change touches a symbol that
carries more architectural weight than it appears to.

## How to enable it

Build a graph once from the repo root:

```bash
pip install graphifyy
graphify install          # installs tree-sitter grammars
graphify .                # builds graphify-out/graph.json and GRAPH_REPORT.md
```

That is the entire setup. Once `GRAPH_REPORT.md` exists at the repo root, the
integration activates on its own. There is no config toggle.

**Keep the graph at the repo root.** If you relocate it via `GRAPHIFY_OUT`,
the report is no longer found at the repo root and the signal does not fire.

## What changes

### Risk classification

Before classifying any task's risk, the conductor checks whether a fresh
`GRAPH_REPORT.md` exists at the repo root.

If it does, and the task's target symbol(s) appear in the God Nodes or
Surprising Connections sections of the report, the conductor treats that as an
additional Elevated signal. This mechanizes two existing Elevated signals that
already required human judgment: "Changes to shared utilities (single-file but
high blast radius)" and "Logic with emergent/non-obvious cross-component
interactions."

The signal is escalate-only: it can raise a classification toward Elevated,
never lower one. A change with no other Elevated signals that touches a God
Node gets classified Elevated. A change already classified Elevated stays
Elevated regardless.

### Blast-radius investigation

When the investigator agent runs a shared-utility or per-consumer-impact
analysis, it checks for `graphify-out/graph.json`. If the graph is present, it
runs:

```bash
graphify affected "<symbol-or-label>" --depth 2 [--relation <R>]
```

This is a deterministic graph BFS - read-only, no LLM call. Each result row
carries the affected node label, BFS depth, relation type, and source
location. The investigator treats graph hits as leads, not proof, and confirms
each against the actual file before reporting it as a consumer. When the graph
is absent, the investigator falls back to `grep -rn` exactly as it does today.

The investigator is read-only: it never runs `graphify update .` or any
mutating subcommand.

## Freshness and autonomous refresh

The conductor keeps the graph fresh itself. Before each risk classification
(at most once per session), it checks whether the graph is stale:

- **Primary check**: the `## Graph Freshness` section of `GRAPH_REPORT.md`
  contains `- Built from commit: ` followed by an 8-character SHA. The graph
  is fresh only if that SHA matches the first 8 characters of `git rev-parse
  HEAD` AND the target files have no uncommitted modifications.
- **Fallback** (no freshness section): compare `GRAPH_REPORT.md`'s mtime
  against the newest target-source-file mtime. If any source is newer, treat
  as stale.

When stale, the conductor runs `graphify update .` once from the repo root,
then reads the refreshed report. This runs at most once per session.

The conductor refreshes only an existing graph. It never runs a from-scratch
`graphify .` or any destructive path. If no graph exists, it does nothing and
falls back to non-graph behavior.

If `graphify update .` fails, the conductor proceeds with the existing stale
graph. Because the signal is escalate-only, a stale graph can only under-fire
(miss an escalation), never produce a false downgrade. An update failure never
blocks risk classification.

## Fail-safe summary

| Condition | Behavior |
|---|---|
| No graph at repo root | No change from non-graph baseline |
| Graph present, target symbol not in God Nodes / Surprising Connections | No change |
| Graph present, target symbol matches | Additional Elevated signal |
| Graph stale, update fails | Proceed with stale graph (signal may under-fire) |
| `GRAPHIFY_OUT` relocates the report | Treated as absent; no signal |

## Related references

- `content/references/risk-config-and-tiers.md` §Graph-derived risk signal -
  full freshness algorithm, format coupling, GRAPHIFY_OUT, and symbol-matching
  details
- `content/agents/investigator.md` §Graph-assisted blast radius - `graphify
  affected` usage, staleness fallback, read-only invariant
- `content/sections/02-delegation.md` - graph-derived escalation rule in
  context of the full delegation table
