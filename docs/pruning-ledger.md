# Pruning Ledger

## Scope

This ledger is fed by exactly two commands: **`/ds-prune-harness`** and **`/ds-representation-audit`**. Both write candidate proposals to `docs/planning/` (gitignored, ephemeral) and, once the user approves or rejects a candidate, record a standing entry here.

`/ds-evaluate` and `/ds-failure-audit` are deliberately **not** in scope. They produce whole-report scorecards, not standing per-item candidates, and their `docs/planning/` output stays ephemeral - a later reader must not assume either of those commands feeds this ledger.

## Path resolution

This file's path is resolved per-repo, not hardcoded: prefer a tracked `.agentic/pruning-ledger.md` when the consuming repo tracks `.agentic/`, else `docs/pruning-ledger.md`. Determined mechanically via `git check-ignore -q <path>` (exit 1 means tracked-capable, exit 0 means ignored, exit 128 is a git failure and neither - see `/ds-prune-harness` Step 0.5 for the full three-way handling), never assumed. In this repo, `.agentic/` is categorically gitignored (see `AGENTS.md`'s "DinoStack does not commit its own `.agentic/` runtime files" decision block - DinoStack is the methodology's source, not a consumer of it, so its own `.agentic/` scratch stays untracked - and the `.agentic/*` umbrella in `.gitignore`), so the resolver lands on `docs/pruning-ledger.md` - this file is the expected outcome here, not a special case.

## Lifecycle

- **RAISED** - a candidate the user approved for action, or explicitly deferred (not rejected), pending a deletion/rewrite PR via `/ds-update-agentic-engineering`.
- **ACTIONED** - the candidate's deletion/rewrite PR merged. `Disposition` carries the PR URL. This transition happens **in the same PR diff as the deletion/rewrite itself** - the Skeptic reviewing that deletion necessarily reviews the ledger update, so a `RAISED` entry can only reach `ACTIONED` via a PR a Skeptic already gated. This is what closes the write-only-graveyard risk: nothing here can be marked done without independent review of the same change.
- **REJECTED** - the user declined the candidate at proposal-review time. `Disposition` carries the user's stated reason and the date.

**Carry-over:** every `RAISED` entry left un-actioned resurfaces at the top of the next `/ds-prune-harness` (or `/ds-representation-audit`) run's proposal, rather than sitting silently. A candidate neither approved-and-actioned nor explicitly rejected stays `RAISED` indefinitely if the audit command is never run again - this is a real residual gap inherent to "the process only runs when invoked," not one this ledger's mechanics can force closed on their own.

## Entry schema

```
## PL-YYYYMMDD-N
- Status: RAISED | ACTIONED | REJECTED
- Source: ds-prune-harness run YYYY-MM-DD (docs/planning/harness-pruning-YYYY-MM-DD.md)
- File(s): content/path/to/file.md (lines N-M)
- Signal(s): [...]
- Confidence: HIGH | MEDIUM | LOW
- Rationale: [one paragraph]
- Disposition: [filled on ACTIONED/REJECTED - PR link or rejection reason + date]
```

`Source` names either `ds-prune-harness` or `ds-representation-audit` and the date of the run that produced the candidate, plus the proposal file's path under `docs/planning/` at the time it was written (that file is gitignored and will not exist by the time a later reader opens this ledger - the path is provenance, not a live link).

---

No entries yet. The first `/ds-prune-harness` or `/ds-representation-audit` run whose candidates the user approves, defers, or rejects appends below this line.
