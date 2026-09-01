# Shared wording kernels for content/agents/

This file is the single hand-edited source for any wording that must read
identically in more than one `content/agents/*.md` file. Each agent states
the surrounding instruction in its own voice; this file holds the identifier
lists, trigger phrases, exemption clauses, and whole instruction bodies that
must not drift word-by-word between them.

Two id families live here today. The five pre-submit / Skeptic check kernels
are shared between `content/agents/engineer.md`'s "Pre-submit self-check"
block and `content/agents/skeptic.md`'s numbered steps 4.5, 4.6, and 11.5.
The `learnings-retrieval` id is the whole prior-learnings retrieval
instruction, shared by `architect.md`, `debugger.md`, `engineer.md`, and
`investigator.md` - deliberately not `skeptic.md`, whose independence from
prior conclusions is the point of the role. The file keeps its historical
name; the name is a mild misnomer now, and renaming it would move
`KERNELS_FILE`, `CONTRIBUTING.md`, and the test module for no behavioral
gain.

Edit fragment text here, then run `bash scripts/stamp-agent-fragments.sh`
(or `bash scripts/build-all.sh`, which runs it first) to propagate the
change into every `<!-- shared:<id> -->...<!-- /shared -->` span in
`content/agents/*.md`. Do not hand-edit the interior of a `shared:` span
directly - the next stamp run will overwrite it.

`skeptic.md`'s wording is canonical wherever the two files historically
disagreed (see the "that" fix below).

<!-- FRAGMENT:test-file-glob-list -->
(matches `*/tests/*`, `test_*.py`, `*.test.*`, `*.spec.*`, or a file added to an existing test-only directory), grep `.github/workflows/*.yml` and `.github/workflows/*.yaml` for a reference to that file, its containing glob, or an auto-discovering runner covering its directory (e.g. a `pytest <dir>` invocation)
<!-- /FRAGMENT -->

<!-- FRAGMENT:identifier-rename-trigger -->
renames, removes, or reshapes an identifier that other parts of the repository could reference by name
<!-- /FRAGMENT -->

<!-- FRAGMENT:identifier-type-list -->
a config key, environment variable, exported symbol, database column, API field, or route name
<!-- /FRAGMENT -->

<!-- FRAGMENT:rename-exemption-clause -->
purely local variable or parameter renames that nothing outside the function can reference
<!-- /FRAGMENT -->

<!-- FRAGMENT:async-primitive-list -->
an async function, Promise, goroutine, or background task without the caller awaiting or otherwise observing its outcome
<!-- /FRAGMENT -->

<!-- FRAGMENT:learnings-retrieval -->
Grep `.agentic/learnings.md` for entries matching this task's domain keywords (e.g. `grep -i -E '<kw1>|<kw2>' .agentic/learnings.md`). Cite an entry ID (`LRN-*` / `KNW-*`) only when that entry's own text actually matches the keywords - never cite a spurious or tangential ID to pad confidence. Two cases are both silent no-ops with zero confidence impact and no reported gap: the file is absent, or the file exists but no entry matches. Only a genuine match changes downstream output.
<!-- /FRAGMENT -->
