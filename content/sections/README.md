<!--
Purpose: Documents the section-file authoring contract for the dinostack
         methodology. Section files in this directory are the source of truth;
         the assembled METHODOLOGY.md (in adapter directories) is a build artifact.

Public API: This file is documentation, not code. It is consumed by humans
            authoring or refactoring methodology content, and by Skeptic agents
            verifying that section-heading stability is preserved.

Upstream deps: None.

Downstream consumers: scripts/build-methodology.sh, scripts/check-methodology-drift.sh
                      (via its --list-files mode), .claude/build.sh, .codex/build.sh
                      (future), .cursor/build.sh (future), and any agent or human
                      authoring methodology content.

Failure modes: This file does not execute. Drift between this contract and the
               actual section files is a Major Skeptic finding (stale manifest).

Performance: N/A.
-->

# content/sections/

This directory holds the source-of-truth body of the dinostack methodology, split into one file per top-level (`##`) section. The assembled METHODOLOGY.md that ships in each harness adapter is a build artifact - never edit it directly. Edit the section files here, then re-run the relevant adapter's build.sh.

## Naming convention

Section files are named `NN-slug.md` where `NN` is a two-digit ordering prefix and `slug` is a lowercase hyphenated short form of the `##` heading. The numeric prefix governs assembly order; the slug is documentation. Examples:

- `01-activation-preflight.md`
- `02-delegation.md`
- `03-planning-artifacts.md`
- `04-risk-classification.md`

The `NN` prefix is dense (no gaps) at any given commit. To insert a new section between existing ones, renumber subsequent files in the same commit.

## Assembly contract

The assembled METHODOLOGY.md body is the deterministic concatenation of every `*.md` file in this directory in `LC_ALL=C` sorted order, with a single blank line between files, each file passed through `scripts/lib/corpus-filter.py` for the active `--corpus` tier (see "Corpus markers (DS-204)" below; `--corpus full`, the default, is byte-identical to the pre-DS-204 concatenation). The assembly is performed by `scripts/build-methodology.sh`. The drift check (`scripts/check-methodology-drift.sh`) derives its file set from `bash scripts/build-methodology.sh --list-files` - the same `LC_ALL=C find|sort` glob, corpus-agnostic - and hashes each section file directly; it never re-implements concatenation.

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

Sub-section (`###`) headings are likewise durable anchors when used as cross-reference targets. The `### Elevated signals`, `### Trivial signals`, `### Low signals`, `### Mid-task reclassification`, `### Low risk self-check`, and `### Declaration format` headings inside `04-risk-classification.md` are explicitly relied on by cross-references and MUST NOT be renamed without a sweep.

## Cross-reference format

Use these forms in any rule, reference, agent spec, or command file:

- `METHODOLOGY.md` - link to the assembled methodology as a whole
- `METHODOLOGY.md §<heading>` - link to a top-level (`##`) section (e.g. `METHODOLOGY.md §Risk Classification`)
- `METHODOLOGY.md §<heading> > <sub-heading>` - link to a `###` sub-section (e.g. `METHODOLOGY.md §Risk Classification > Elevated signals`)

Bold-prose paragraph leads (e.g. `**Conductor rule for Trivial:**`) are NOT covered by the stability contract. If you need to reference such content from outside the section file, the content must first be promoted to a real `###` sub-heading in a separate Elevated change.

## Known Wave 1 regressions

The Wave 1 PR that introduced this directory deletes the now-renamed `content/rules/METHODOLOGY.md`. As of that PR, three sibling adapter scripts still reference the deleted path and will fail until Wave 2 lands:

- `.gemini/build.sh` (line ~55) cats `content/rules/METHODOLOGY.md` (deleted path)
- `.kimi/build.sh` (line ~32) cats `content/rules/METHODOLOGY.md` (deleted path)
- `.opencode/install.sh` (line ~322) references the deleted path

If you are on the Wave-1 branch, do NOT run those adapter builds. Wave 2 (Codex/Gemini/Cursor adapter migrations) plus the Kimi and OpenCode catch-ups documented here will close all three.

## Existing-installation upgrade path

If you previously installed the dinostack skill (via `bash .claude/install.sh`), your `~/.claude/CLAUDE.md` contains a managed block with `@skills/dinostack/METHODOLOGY.md`. After pulling Wave 1, that import points at a deleted file. Re-run `bash .claude/install.sh` once - the script's regex sub rewrites the managed block to import `@skills/dinostack/METHODOLOGY.md` cleanly. The skill directory itself is symlinked from the repo, so its content updates automatically on `git pull`; only the `@`-import line in `CLAUDE.md` is stale until install re-runs.

## Baseline SHA semantics

`scripts/.methodology-baseline.sha256` is a per-file manifest: one `<basename> <sha256>` line per `content/sections/[0-9][0-9]-*.md` file, headed by a fixed comment line, written atomically and verbatim by `bash scripts/check-methodology-drift.sh --regenerate`. It is equivalent in intent to the single assembled-output hash it replaced: both pin the section files so that unintentional drift fails the `methodology-drift` CI gate. The per-file form keeps the gate meaningful across assembly-logic changes - a change to the concatenation in `scripts/build-methodology.sh` that leaves every section file untouched would trip a whole-output baseline but is covered instead by the `adapter-sync` gate, which rebuilds every adapter from the same script and fails on any drift.

Section content is kernel content, loaded at every corpus tier by default (see "Corpus markers (DS-204)" below for the one exception). Detail passing the three-question partition test (see `content/references/design-goals.md` Goal 4) belongs in `content/references/**`, reached by a read-on-trigger pointer in `12-protocol-details.md`.

## Corpus markers (DS-204)

A section file may declare a corpus posture via one of two mechanisms, defined in `scripts/lib/corpus-filter.py` (the single source of truth for marker syntax - never re-derive it):

- A line-1 file-level `<!-- corpora: minimal medium full -->` marker: the whole file loads at every corpus (the common case; most section files carry this).
- One or more `<!-- corpus:begin <space-separated corpus list> | trigger: <text> --> ... <!-- corpus:end -->` blocks: the wrapped content loads only when the active corpus is in `<corpus list>`. At a non-matching corpus, the block is replaced by a generated "Deferred at this corpus" pointer block naming each excluded block's `trigger:` text - a concrete, recognizable event, not a topic. The `trigger:` clause is mandatory unless the list is exactly `minimal medium full` (in which case the block is never excluded).

Every section file MUST declare a posture one way or the other - `scripts/check-corpus-coverage.py` (wired into `.github/workflows/methodology-drift.yml`) fails CI on a file with neither. A partitioned file's own first top-level (`##`) heading must never sit inside a `corpus:begin` block - it must always be reachable, at every corpus. Marker lines themselves are always stripped from assembled output, at every corpus, so `--corpus full` output is byte-identical to the pre-DS-204 assembly.

`.claude/`, `.kimi/`, `.gemini/`, and `.copilot/` (`.github/skills/`) each build a MINIMAL-corpus embed for their trigger-loaded skill body, alongside an unfiltered FULL-corpus sibling file the pointer blocks name. `.codex/` and the remaining adapters are unaffected - they still assemble the full corpus.
