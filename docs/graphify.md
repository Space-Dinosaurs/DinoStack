<!--
Purpose: Operator-facing guide to the Graphify integration in AE. Explains
         its single use (the investigator's optional blast-radius lookup),
         how to build the graph, who keeps it fresh, and the fail-safe
         behavior when no usable graph is present.

Public API: Operator-facing prose. Entry point for anyone who wants to
            understand or enable graph-assisted blast-radius investigation.
            The authoritative behavioral spec lives in
            content/agents/investigator.md §Graph-assisted blast radius.

Upstream deps: content/agents/investigator.md
               (graphify affected, read-only lock, staleness fallback).

Downstream consumers: docs site root index.

Failure modes: Stale if the investigator's graphify affected usage or the
               graphify CLI flags it relies on change. Update alongside
               content/agents/investigator.md.

Performance: Standard.
-->

# Graphify integration

AE uses a Graphify knowledge graph in one place: the investigator agent's
blast-radius lookup. It is presence-gated - no config toggle. When no graph is
present, the investigator falls back to `grep -rn`.

## What graphify is

[Graphify](https://github.com/graphifyy/graphifyy) (`pip install graphifyy`)
builds a code knowledge graph from your repository's source files and writes
it to `graphify-out/graph.json`.

## How to enable it

Build a graph once from the repo root:

```bash
pip install graphifyy
graphify install          # graphify setup step
graphify .                # builds graphify-out/graph.json
```

The graph lands in `graphify-out/graph.json`, or under the directory named by
`GRAPHIFY_OUT` when that is set. There is no config toggle.

## Blast-radius investigation

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

## Freshness

Keeping the graph fresh is the operator's job. Either install graphify's git
hooks with `graphify hook install` (post-commit and post-checkout), or run
`graphify update .` manually after changes. Hooks installed to `.git/hooks`
do not fire when `core.hooksPath` is overridden.

The investigator compares the graph's mtime against the relevant source files.
When the graph is stale, it falls back to `grep -rn` and notes the staleness
in its return.

## Worktrees

When `graphify-out/` is untracked and repo-relative, the graph exists only in
the checkout where it was built, so an agent running in an isolation worktree
finds no graph there and uses `grep -rn`. A graph committed to the repo, or
one located through an absolute `GRAPHIFY_OUT`, is visible from worktrees too.

## Fail-safe summary

| Condition | Behavior |
|---|---|
| No graph | `grep -rn` |
| `graphify` binary missing | `grep -rn` |
| Graph stale | `grep -rn`, with a staleness note |

## History

An earlier conductor-side risk-escalation use of the graph was removed
(DS-255) because nothing executed it.

## Related references

- `content/agents/investigator.md` §Graph-assisted blast radius - `graphify
  affected` usage, staleness fallback, read-only invariant
