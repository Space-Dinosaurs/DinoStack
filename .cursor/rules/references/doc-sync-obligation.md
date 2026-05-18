# Doc-Sync Obligation for Reality-Asserting Changes

## Overview

Every intent-layer doc that counts, lists, or describes part of the system is a reality assertion. When a change makes that assertion false and the doc is not updated in the same change, the doc becomes **intent debt** - the artifact stops reflecting what the system actually is, and downstream agents and humans read the stale text, trust it, and drift along with it.

This is the doc-level analogue of the regression-test obligation (`content/references/regression-test-obligation.md`) and the module-manifest staleness rule (`content/rules/module-manifest.md`): a reality-asserting change carries an in-PR obligation to keep the asserting artifact true, and the Skeptic verifies it before sign-off.

The default posture is **not to trip**. Most diffs do not change anything a doc asserts. Over-documenting is itself drift - do not add speculative doc edits to changes that do not meet the predicate.

---

## Trigger predicate (when a doc update is obligated)

A doc update is obligated iff the change alters something an intent-layer doc asserts - specifically ANY of:

1. **Enumerable set** - changes a set a doc counts or lists: add/remove/rename a file under `content/agents`, `content/commands`, `content/references`; or add/remove a `content/rules` or `content/sections` file referenced by name in an intent-layer doc.
2. **Public/portable surface** - changes a command, named agent, named reference, or rule presented to users.
3. **Structure/paths** - changes file/dir structure or canonical paths a doc references.
4. **Convention/config/setup** - changes a documented convention, config schema, or install/setup step.
5. **User-facing behavior** - changes user-facing behavior a doc describes.

The Skeptic test to embed: *"Does any sentence, count, or list in README.md, CONTRIBUTING.md, or content/SKILL.md become false or incomplete because of this diff?"* Uncertainty is not an exemption - grep the docs for the changed identifier or count and resolve.

## Exemptions (when it does NOT trip)

The default is NOT to trip. The predicate does not fire for:

- Pure bug fixes with no surface change.
- Internal refactors changing no name, count, path, or behavior a doc asserts.
- Test/eval-only changes.
- Comment, whitespace, or format changes.
- Changes to files no intent-layer doc references.
- Edits to docs themselves.
- Changes already covered by an existing generic statement with no count or list to update.

Over-documenting is itself drift - do not add speculative doc edits to changes that do not meet the predicate.

## Worker obligation

On a predicate-tripping change, in the same change update every invalidated intent-layer doc (scan `README.md`, `CONTRIBUTING.md`, `content/SKILL.md`, affected `content/sections` + `content/references` cross-refs) and attest in the change summary:

`Doc-sync: [predicate clause N triggered] -> updated [doc paths]: [what changed].`

OR if not tripped:

`Doc-sync: predicate not triggered (no reality-asserting change).`

## Skeptic verification

This is a **standing every-round check**, not a fix-round-only check. Apply the trigger predicate to the diff:

- Not tripped -> no finding.
- Tripped + correctly updated -> no finding.
- Tripped + missing/incomplete -> classify (reusing the module-manifest Minor/Major/Critical tier model and intent-debt vocabulary):
  - **Minor** - non-misleading omission: existing text still true but incomplete, no stated count wrong. Does not block sign-off.
  - **Major** - a count/list/path/convention/behavior assertion is now stale or false. Blocks sign-off absent a compelling documented deferral.
  - **Critical** - a stale assertion on a load-bearing public-facing doc that actively misleads on how to use, install, or extend the system (e.g. README install steps, documented command/agent surface, canonical path).

Finding string format:

`[CLASSIFICATION] Doc-sync drift - [doc path]: [assertion] is now false/incomplete because [diff change]. Same-PR doc update required before sign-off.`

## What counts as a sufficient doc update

Analogous to the regression-test-obligation "what counts" bar: the update must make every invalidated assertion true again - correct the count AND the list AND any prose that referenced it - not just the most obvious one. A partial update that fixes the count but leaves a stale enumeration is insufficient, and the Skeptic raises it at the classification its remaining staleness warrants.
