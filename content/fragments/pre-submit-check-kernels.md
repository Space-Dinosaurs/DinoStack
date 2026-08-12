# Shared pre-submit / Skeptic check kernels

This file is the single hand-edited source for wording shared between
`content/agents/engineer.md`'s "Pre-submit self-check" block and
`content/agents/skeptic.md`'s numbered steps 4.5, 4.6, and 11.5. Both files
state the same mechanical checks in their own voice; this file holds the
identifier lists, trigger phrases, and exemption clauses that must read
identically in both places so they cannot drift word-by-word again.

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
