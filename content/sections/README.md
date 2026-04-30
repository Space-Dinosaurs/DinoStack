<!--
Purpose: Documents the section-file authoring contract for the agentic-engineering
         methodology. Section files in this directory are the source of truth;
         the assembled METHODOLOGY.md (in adapter directories) is a build artifact.

Public API: This file is documentation, not code. It is consumed by humans
            authoring or refactoring methodology content, and by Skeptic agents
            verifying that section-heading stability is preserved.

Upstream deps: None.

Downstream consumers: scripts/build-methodology.sh, scripts/check-methodology-drift.sh,
                      .claude/build.sh, .codex/build.sh (future), .cursor/build.sh
                      (future), and any agent or human authoring methodology content.

Failure modes: This file does not execute. Drift between this contract and the
               actual section files is a Major Skeptic finding (stale manifest).

Performance: N/A.
-->

# content/sections/

This directory holds the source-of-truth body of the agentic-engineering methodology, split into one file per top-level (`##`) section. The assembled METHODOLOGY.md that ships in each harness adapter is a build artifact - never edit it directly. Edit the section files here, then re-run the relevant adapter's build.sh.

## Naming convention

Section files are named `NN-slug.md` where `NN` is a two-digit ordering prefix and `slug` is a lowercase hyphenated short form of the `##` heading. The numeric prefix governs assembly order; the slug is documentation. Examples:

- `01-activation-preflight.md`
- `02-delegation.md`
- `03-risk-classification.md`

The `NN` prefix is dense (no gaps) at any given commit. To insert a new section between existing ones, renumber subsequent files in the same commit.

## Assembly contract

The assembled METHODOLOGY.md body is the deterministic concatenation of every `*.md` file in this directory in `LC_ALL=C` sorted order, with a single blank line between files. The assembly is performed by `scripts/build-methodology.sh`. Any consumer (build.sh, drift check, etc.) MUST use that script and MUST NOT re-implement the assembly logic.

```bash
# Equivalent shell expression (do not duplicate this in adapters; call the script):
LC_ALL=C ls content/sections/*.md | sort | while read f; do
  cat "$f"
  echo  # blank line separator
done
```

The README.md file (this file) is excluded from assembly because it does not match the `NN-slug.md` numeric-prefix pattern - the build script filters by glob `[0-9][0-9]-*.md`.

## Section heading stability contract

Once a section has been committed, its top-level (`##`) heading text is a durable cross-reference anchor. Other content in this repository - rules, references, agent specs, command files - links to section content using the form `METHODOLOGY.md §<heading>` or `METHODOLOGY.md §<heading> > <sub-heading>`. Renaming a heading after commit is therefore an Elevated change that requires a sweep of every reference in the repo.

Sub-section (`###`) headings are likewise durable anchors when used as cross-reference targets. The `### Elevated signals`, `### Trivial signals`, `### Low signals`, `### Mid-task reclassification`, `### Low risk self-check`, and `### Declaration format` headings inside `03-risk-classification.md` are explicitly relied on by cross-references and MUST NOT be renamed without a sweep.

## Cross-reference format

Use these forms in any rule, reference, agent spec, or command file:

- `METHODOLOGY.md` - link to the assembled methodology as a whole
- `METHODOLOGY.md §<heading>` - link to a top-level (`##`) section (e.g. `METHODOLOGY.md §Risk Classification`)
- `METHODOLOGY.md §<heading> > <sub-heading>` - link to a `###` sub-section (e.g. `METHODOLOGY.md §Risk Classification > Elevated signals`)

Bold-prose paragraph leads (e.g. `**Conductor rule for Trivial:**`) are NOT covered by the stability contract. If you need to reference such content from outside the section file, the content must first be promoted to a real `###` sub-heading in a separate Elevated change.

## Known Wave 1 regressions

The Wave 1 PR that introduced this directory deletes `content/rules/agent-methodology.md`. As of that PR, three sibling adapter scripts still reference the deleted path and will fail until Wave 2 lands:

- `.gemini/build.sh` (line ~55) cats `content/rules/agent-methodology.md`
- `.kimi/build.sh` (line ~32) cats `content/rules/agent-methodology.md`
- `.opencode/install.sh` (line ~322) references the deleted path

If you are on the Wave-1 branch, do NOT run those adapter builds. Wave 2 (Codex/Gemini/Cursor adapter migrations) plus the Kimi and OpenCode catch-ups documented here will close all three.

## Existing-installation upgrade path

If you previously installed the agentic-engineering skill (via `bash .claude/install.sh`), your `~/.claude/CLAUDE.md` contains a managed block with `@skills/agentic-engineering/rules/agent-methodology.md`. After pulling Wave 1, that import points at a deleted file. Re-run `bash .claude/install.sh` once - the script's regex sub rewrites the managed block to import `@skills/agentic-engineering/METHODOLOGY.md` cleanly. The skill directory itself is symlinked from the repo, so its content updates automatically on `git pull`; only the `@`-import line in `CLAUDE.md` is stale until install re-runs.

## Baseline SHA semantics

`scripts/.methodology-baseline.sha256` contains the SHA256 of the assembled output (`bash scripts/build-methodology.sh`) at the moment Wave 1 landed. The architect plan originally specified the baseline as the SHA of the pre-split monolith; that was overridden by the Worker because the Wave 1 commit also promotes 6 bold-prose anchors to `###` sub-headings (an M1 fix), so the assembled output cannot byte-equal the pre-split monolith. Drift-check intent is "no future unintentional drift between sections and assembled output," not "byte-identity to original" - the post-promotion baseline serves that intent.
