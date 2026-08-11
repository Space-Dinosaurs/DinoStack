"""
Purpose: Mutation-testing harness for
         bin/tests/test_agent_return_contract_spec.py's check_contract()
         gate. Four prior rounds of that spec gate each shipped a defect
         where the checker was green because it checked nothing, or
         checked too permissively (round 1: 18/18 structural parse
         failure; round 2: fence-blind silent pass; round 3: a
         `pass`-bodied guard plus three auto-passing heuristics; round 4:
         a shape-level scalar auto-pass, plus three "keyword/phrase
         present ANYWHERE" regexes that claimed adjacency/specificity
         they never enforced) - and every round's own fixtures were
         hand-authored by the same agent, in the same commit, as the
         checker they exercised, so they only ever probed the shape the
         author already had in mind. This file instead mechanically
         DERIVES non-compliant mutants from known-compliant seed texts
         (synthetic seeds built to isolate one nesting depth or one
         validated-line prefix at a time, plus the real skeptic.md
         corpus file for the six-prefix masking bug) and asserts every
         mutant is rejected. A mutant that survives (the checker returns
         [] on genuinely non-compliant text) is a defect in the checker
         under test, never a false report from this harness. Round 5
         adds four regression mutations (shape2_scalar_leaf_unbounded_
         no_auto_pass, shape2_cap_keyword_requires_adjacent_digit,
         shape2_enum_pipe_inside_narrative_placeholder_not_recognized,
         shape2_undeclared_narrative_placeholder_not_recognized - renamed
         in round 7 from shape2_pointer_requires_md_or_schema_reference
         after round 6 deleted the pointer form the old name described)
         encoding the four falsifying probes a reviewing Skeptic used to
         demonstrate the round-4 permissive branches, PLUS a CI floor on
         len(MUTATIONS) (.github/workflows/bin-tests.yml) - round 4's own
         fix removed one operator from this file with the suite still
         reporting `42 passed` and nothing red, because nothing pinned
         the catalog's size. Round 7 adds
         shape3_bare_status_token_regex_permissive_widening, pinning the
         PERMISSIVE direction of SHAPE3_BARE_STATUS_TOKEN_RE (round 6 had
         only pinned its strict direction via the snapshot).

Public API: MUTATIONS (list of (id, run) pairs, each `run()` returning
            (baseline_violations, mutant_violations, caught: bool));
            run_survivors() -> [id, ...] for every mutation where `run()`
            reports caught=False. Also collected as pytest test functions
            (one per mutation id, asserting caught=True) plus
            test_no_survivors, the single aggregate assertion.

Upstream dependencies: test_agent_return_contract_spec.py (imported by
            module name - both files sit in bin/tests/ with no
            __init__.py, so pytest inserts this directory onto sys.path
            at collection time and a bare `import` resolves it);
            content/agents/skeptic.md (the one REAL corpus file mutated
            here, for the six-prefix section-scoping bug - the other
            mutations use synthetic seeds so the harness does not depend
            on the mutability of files outside this shape's own defect
            class).

Downstream consumers: .github/workflows/bin-tests.yml python-bin-tests
            job (`pytest bin/tests/ -q`, full-directory glob discovery).

Failure modes: pure static analysis; no I/O beyond reading skeptic.md and
            the check_contract module. A mutation whose `old` substring is
            not found in its seed raises AssertionError at collection/run
            time (loud, not a silent no-op) - see `_replace_once`.
            Skeptic-mutation correctness requires the SPECIFIC new
            violation to appear (a set difference against the baseline
            violation list), not mere non-emptiness: skeptic.md is
            NOT_YET_MIGRATED and already carries one baseline violation
            (the Calibration cap gap), so a naive `violations != []`
            check would report every skeptic mutation as "caught"
            regardless of whether the mutated line's own defect was
            actually detected - this exact false-positive was measured
            and corrected while building this harness (see the
            comment above `_skeptic_mutation`).

Performance: negligible - reads one real file plus in-memory synthetic
            seed strings.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_agent_return_contract_spec as contract  # noqa: E402


def _replace_once(text, old, new):
    assert old in text, f"mutation anchor text not found in seed: {old!r}"
    mutant = text.replace(old, new, 1)
    assert mutant != text, (
        f"mutation produced no change - old and new are identical: {old!r}"
    )
    return mutant


# --- Shape 1: strip tag / strip cap (compliant_agent.md fixture seed) ---

_SHAPE1_SEED = contract._read_fixture("compliant_agent.md")


def _shape1_mutation(old, new, expect_substr):
    def run():
        baseline = contract.check_contract(_SHAPE1_SEED, "shape1_seed.md")
        mutant_text = _replace_once(_SHAPE1_SEED, old, new)
        mutant = contract.check_contract(mutant_text, "shape1_seed.md")
        caught = any(expect_substr in v for v in mutant)
        return baseline, mutant, caught
    return run


# --- Shape 2: nesting-depth mutations (synthetic seed, guaranteed GREEN
# baseline - covers a top-level scalar/one-line field, an object member,
# an array-of-object item member, and a member nested two levels deep
# inside object-in-object, plus the plan's own Unit-3 array-of-object
# schema shape) ---

_SHAPE2_SEED = """## Output format

```yaml
status: DONE | FAILED | BLOCKED
summary: <one-line summary, cap: 200 chars>
task_ref: <id or null>
metadata:
  owner: <one-line name>
  detail: <one-line note, max 100 chars>
findings:
  - note: <one-line finding, cap: 150 chars>
    tag: <one-line tag>
nested:
  inner:
    deep_note: <one-line deep note, max 50 chars>
```
"""


def _shape2_mutation(old, new, expect_substr):
    def run():
        baseline = contract.check_contract(_SHAPE2_SEED, "shape2_seed.md", shape=2)
        mutant_text = _replace_once(_SHAPE2_SEED, old, new)
        mutant = contract.check_contract(mutant_text, "shape2_seed.md", shape=2)
        caught = any(expect_substr in v for v in mutant)
        return baseline, mutant, caught
    return run


def _shape2_unit3_array_of_object_schema_shape_mutation():
    """The plan's own Unit-3 array-of-object schema shape
    (`"note": "<=150 chars"`) - a compliant seed with the cap declared,
    mutated to remove it. Regression guard for the exact example named in
    the round-4 spawn brief's M3 finding."""
    compliant = (
        '## Output format\n\n```yaml\nstatus: DONE | FAILED\n'
        'items:\n  - note: "<=150 chars"\n```\n'
    )
    unbounded_old = '  - note: "<=150 chars"'
    unbounded_new = '  - note: "unbounded narrative with no declared limit"'

    def run():
        baseline = contract.check_contract(compliant, "shape2_unit3_seed.md", shape=2)
        mutant_text = _replace_once(compliant, unbounded_old, unbounded_new)
        mutant = contract.check_contract(mutant_text, "shape2_unit3_seed.md", shape=2)
        caught = any("note" in v or "items" in v for v in mutant)
        return baseline, mutant, caught
    return run


# --- Shape 3 (skeptic special case): retag/mask one of the six
# conductor-validated line prefixes, against the REAL skeptic.md corpus
# file. skeptic.md was migrated to fully compliant by Unit 1 of the DS
# return-contract migration (2026-08-11) - its baseline is now the empty
# list - but the set-difference-against-baseline machinery below is kept
# unchanged rather than special-cased, so "caught" stays defined as the
# SPECIFIC expected violation appearing in the set difference against the
# baseline, never mere non-emptiness. A naive `violations != []` check
# was measured to report every one of these mutations as "caught"
# regardless of whether the six-prefix guard actually fired - see the
# module docstring. ---

_SKEPTIC_TEXT = (contract.AGENTS_DIR / "skeptic.md").read_text()
_SKEPTIC_BASELINE = contract.check_contract(_SKEPTIC_TEXT, "skeptic.md")


def _skeptic_mutation(old, new, expect_substr):
    def run():
        mutant_text = _replace_once(_SKEPTIC_TEXT, old, new)
        mutant = contract.check_contract(mutant_text, "skeptic.md")
        new_findings = [v for v in mutant if v not in _SKEPTIC_BASELINE]
        caught = any(expect_substr in v for v in new_findings)
        return _SKEPTIC_BASELINE, mutant, caught
    return run


def _skeptic_multi_replace_mutation(replacements, expect_substr):
    """Like _skeptic_mutation, but applies a sequence of (old, new)
    replacements in order - needed because 'Findings:' legitimately
    appears TWICE within the Sign-off format template itself (the
    count-form line and the "write instead: Findings: No findings."
    zero-findings alternate form, per skeptic-protocol.md's own stated
    template) - retagging only ONE of the two leaves the OTHER as a
    genuinely valid, unaltered occurrence of the required prefix, so
    that single-line mutation is not a fair non-compliance test. Both
    occurrences must be corrupted for this to represent real
    label-loss."""
    def run():
        mutant_text = _SKEPTIC_TEXT
        for old, new in replacements:
            mutant_text = _replace_once(mutant_text, old, new)
        mutant = contract.check_contract(mutant_text, "skeptic.md")
        new_findings = [v for v in mutant if v not in _SKEPTIC_BASELINE]
        caught = any(expect_substr in v for v in new_findings)
        return _SKEPTIC_BASELINE, mutant, caught
    return run


# --- Shape 3: bare status token (SHAPE3_BARE_STATUS_TOKEN_RE) permissive-
# direction mutation, synthetic seed - round-7 Major fix. This is the
# unpinned branch a reviewing Skeptic demonstrated: widening
# SHAPE3_BARE_STATUS_TOKEN_RE from r"^[A-Z][A-Z0-9_]*$" to r"^.+$" makes
# every non-'Label: value' line unconditionally compliant, including
# arbitrary unbounded narrative, and every prior test in this suite stayed
# green under that widening because none of them probed a multi-word or
# mixed-case bare line. This seed's baseline compliance depends on the
# genuine narrow regex accepting the bare closed-enum-shaped 'BLOCKED'
# token; the mutation replaces it with a multi-word, mixed-case narrative
# line carrying no colon, which the narrow regex correctly rejects (a
# space and lowercase letters are both outside `[A-Z0-9_]*`) but the
# widened `^.+$` would wrongly accept. ---

_SHAPE3_BARE_TOKEN_SEED = """## Output format

Return exactly this structure and nothing else:

```
GOAL_MET: true|false
BLOCKED
```
"""


def _shape3_bare_token_mutation(old, new, expect_substr):
    def run():
        baseline = contract.check_contract(
            _SHAPE3_BARE_TOKEN_SEED, "shape3_bare_token_seed.md", shape=3
        )
        mutant_text = _replace_once(_SHAPE3_BARE_TOKEN_SEED, old, new)
        mutant = contract.check_contract(
            mutant_text, "shape3_bare_token_seed.md", shape=3
        )
        caught = any(expect_substr in v for v in mutant)
        return baseline, mutant, caught
    return run


# --- Shape 4: unconditional-cap mutations (shape4_compliant_agent.md
# fixture seed) - covers narrative-hint-word present with no digit, and
# narrative-hint-word absent with no cap keyword at all ---

_SHAPE4_SEED = contract._read_fixture("shape4_compliant_agent.md")


def _shape4_mutation(old, new, expect_substr):
    def run():
        baseline = contract.check_contract(_SHAPE4_SEED, "shape4_seed.md", shape=4)
        mutant_text = _replace_once(_SHAPE4_SEED, old, new)
        mutant = contract.check_contract(mutant_text, "shape4_seed.md", shape=4)
        caught = any(expect_substr in v for v in mutant)
        return baseline, mutant, caught
    return run


# --- The mutation catalog ---

MUTATIONS = [
    (
        "shape1_strip_tag",
        _shape1_mutation(
            "### Root cause [MECHANICAL, cap: 500 chars]",
            "### Root cause",
            "no [MECHANICAL] or [ADVISORY] tag",
        ),
    ),
    (
        "shape1_strip_cap",
        _shape1_mutation(
            "### Root cause [MECHANICAL, cap: 500 chars]",
            "### Root cause [MECHANICAL]",
            "declares no numeric cap",
        ),
    ),
    (
        "shape2_object_member_unbounded",
        _shape2_mutation(
            "detail: <one-line note, max 100 chars>",
            "detail: <detailed narrative account of what happened>",
            "'metadata'",
        ),
    ),
    (
        "shape2_array_of_object_member_unbounded",
        _shape2_mutation(
            "note: <one-line finding, cap: 150 chars>",
            "note: <detailed narrative account of the finding>",
            "'findings'",
        ),
    ),
    (
        "shape2_nested_object_in_object_unbounded",
        _shape2_mutation(
            "deep_note: <one-line deep note, max 50 chars>",
            "deep_note: <detailed narrative account, no limit at all>",
            "'nested'",
        ),
    ),
    (
        "shape2_classification_enum_removed",
        _shape2_mutation(
            "status: DONE | FAILED | BLOCKED",
            "status: <one-line result>",
            "declares no closed enum",
        ),
    ),
    (
        "shape2_unit3_array_of_object_schema_shape",
        _shape2_unit3_array_of_object_schema_shape_mutation(),
    ),
    (
        "shape3_skeptic_retag_findings_prefix",
        # 'Findings:' legitimately appears TWICE in the real template
        # (the count-form line and the "write instead: Findings: No
        # findings." zero-findings alternate) - both must be retagged for
        # this to represent genuine label-loss (see
        # _skeptic_multi_replace_mutation). The retag bracket itself must
        # not contain a cap-shaped sentence ('[MECHANICAL, cap: 300
        # chars]' would coincidentally trip the SEPARATE
        # template-smuggling guard instead of the missing-prefix guard
        # this mutation targets - see shape3_skeptic_cap_smuggled_into_
        # template below for that distinct mutation).
        _skeptic_multi_replace_mutation(
            [
                (
                    "Findings: Critical: N, Major: N, Minor: N",
                    "Findings [tagged]: Critical: N, Major: N, Minor: N",
                ),
                (
                    "write instead: Findings: No findings.",
                    "write instead: Findings [tagged]: No findings.",
                ),
            ],
            "'Findings:'",
        ),
    ),
    (
        "shape3_skeptic_cap_smuggled_into_template",
        # The template-smuggling guard's own mutation: insert a
        # cap-shaped sentence referencing 'finding' INTO the fenced
        # Sign-off format template itself, rather than the surrounding
        # Calibration prose - this must be rejected as a violation of
        # "never touch the validated lines", not accepted as satisfying
        # the Calibration cap requirement.
        _skeptic_mutation(
            "Findings: Critical: N, Major: N, Minor: N",
            "Findings [MECHANICAL, cap: 300 chars]: Critical: N, Major: N, Minor: N",
            "must appear in the Calibration section prose",
        ),
    ),
    (
        "shape3_skeptic_retag_signoff_phrase",
        _skeptic_mutation(
            "No unresolved Critical or Major findings. Sign-off granted.",
            "No unresolved severity-1 or severity-2 findings. Sign-off granted.",
            "Sign-off granted",
        ),
    ),
    (
        "shape3_skeptic_delete_manifest_check_line",
        _skeptic_mutation(
            "Manifest check: [pass | N stale (listed above) | N missing "
            "(listed above) | n/a - no non-trivial modules in diff]",
            "",
            "'Manifest check:'",
        ),
    ),
    (
        "shape4_cap_keyword_no_digit_hint_present",
        _shape4_mutation(
            "which gate failed, what the error was, what was\ndone - max 500 chars>",
            "which gate failed, what the error was, what was\ndone - max chars>",
            "declares no closed enum, bounded-by-nature value type, or numeric cap",
        ),
    ),
    (
        "shape4_no_cap_no_hint_word",
        _shape4_mutation(
            "<If status is not SUCCESS: which gate failed, what the error was, "
            "what was\ndone - max 500 chars>",
            "<Details of the blocker text>",
            "declares no closed enum, bounded-by-nature value type, or numeric cap",
        ),
    ),
    (
        "shape2_scalar_leaf_unbounded_no_auto_pass",
        _shape2_mutation(
            "summary: <one-line summary, cap: 200 chars>",
            "summary: <full narrative account with no declared bound at all>",
            "'summary'",
        ),
    ),
    (
        "shape2_cap_keyword_requires_adjacent_digit",
        _shape2_mutation(
            "note: <one-line finding, cap: 150 chars>",
            "note: <detailed account; 3 records were truncated from the source system>",
            "'findings'",
        ),
    ),
    (
        "shape2_enum_pipe_inside_narrative_placeholder_not_recognized",
        _shape2_mutation(
            "owner: <one-line name>",
            "owner: <what happened | why it matters, unbounded>",
            "'metadata'",
        ),
    ),
    (
        "shape2_undeclared_narrative_placeholder_not_recognized",
        # Round-5 name was 'shape2_pointer_requires_md_or_schema_reference',
        # a requirement round 6 deleted outright (the pointer form no
        # longer exists at all - see
        # shape2_pointer_form_deleted_md_reference_no_longer_bounds
        # below). This operator still catches a genuinely unbounded
        # narrative placeholder with no declared cap, enum, or one-line
        # marker, so it is not vacuous - only its old name described a
        # requirement that is now false.
        _shape2_mutation(
            "deep_note: <one-line deep note, max 50 chars>",
            "deep_note: <free-form prose, the term is defined in the glossary>",
            "'nested'",
        ),
    ),
    # --- Round-6 regression mutations, one per Major finding ---
    (
        "shape2_nullable_type_string_word_removed",
        # Round-6 Major-1 falsifying probe: 'string'/'str'/'object'/
        # 'array' no longer satisfy the nullable-type form - a type
        # declaration alone is not a bound. Pre-fix, 'task_id: <string
        # or null>' and 'branch_name: <string, or null>' both passed
        # unconditionally despite carrying no length/shape limit at
        # all (see the real engineer.md regression this mirrors).
        _shape2_mutation(
            "task_ref: <id or null>",
            "task_ref: <string or null>",
            "'task_ref'",
        ),
    ),
    (
        "shape2_pointer_form_deleted_md_reference_no_longer_bounds",
        # Round-6 Major-2 falsifying probe: even with a CONCRETE '.md'
        # reference present (the exact condition the round-5 "fix"
        # required and treated as sufficient), the pointer form is now
        # DELETED outright, not merely narrowed - this text passed
        # under round 5 (SHAPE2_POINTER_RE matched 'defined in
        # our-conventions.md' within its window) and must now be
        # rejected because the form no longer exists to match anything.
        _shape2_mutation(
            "deep_note: <one-line deep note, max 50 chars>",
            "deep_note: <free narrative, see the format defined in "
            "our-conventions.md for tone guidance>",
            "'nested'",
        ),
    ),
    (
        "shape4_one_line_marker_not_recognized",
        # Round-6 Major-3 falsifying probe: check_shape4 does NOT
        # consult the one-line-marker form (form 4) - a placeholder
        # rewritten in that shape is still flagged, proving
        # check_shape4 was never genuinely "the same closed whitelist"
        # as check_shape2 (the false claim this round corrects in the
        # doc and code manifest). This mutation locks the documented
        # per-shape divergence in place: if a future change silently
        # widens check_shape4 to accept this form, this mutation starts
        # failing (an intentional widening must update this mutation
        # explicitly, in the same review as the doc change).
        _shape4_mutation(
            "<If status is not SUCCESS: which gate failed, what the error was, "
            "what was\ndone - max 500 chars>",
            "<one-line summary of what failed>",
            "declares no closed enum, bounded-by-nature value type, or numeric cap",
        ),
    ),
    (
        "shape3_bare_status_token_regex_permissive_widening",
        # Round-7 Major fix: SHAPE3_BARE_STATUS_TOKEN_RE
        # (r"^[A-Z][A-Z0-9_]*$") had no operator pinning its PERMISSIVE
        # direction - a Skeptic demonstrated that widening it to r"^.+$"
        # (unconditionally compliant for any non-'Label: value' line,
        # including arbitrary unbounded narrative) left every prior test
        # in this suite green. This mutation replaces the seed's
        # compliant bare 'BLOCKED' token with a multi-word, mixed-case
        # narrative line - correctly rejected by the narrow regex (a
        # space and lowercase letters both fall outside
        # `[A-Z0-9_]*`) but wrongly accepted by the widened `^.+$` form.
        # If SHAPE3_BARE_STATUS_TOKEN_RE is ever widened to accept
        # arbitrary text, this mutation starts failing.
        _shape3_bare_token_mutation(
            "BLOCKED",
            "Task Blocked Due To Config Error",
            "is not a 'Label: value' line",
        ),
    ),
]


def run_survivors():
    """Return [id, ...] for every mutation in MUTATIONS whose `run()`
    reports caught=False - a mutant the checker failed to reject."""
    survivors = []
    for mutation_id, run in MUTATIONS:
        _baseline, _mutant, caught = run()
        if not caught:
            survivors.append(mutation_id)
    return survivors


# --- Sanity checks: every seed must be a genuinely compliant/known-baseline
# text BEFORE mutation - a seed that is already non-compliant (or already
# raises) makes its mutation assertion vacuous. ---


def test_shape1_seed_is_baseline_compliant():
    assert contract.check_contract(_SHAPE1_SEED, "shape1_seed.md") == []


def test_shape2_seed_is_baseline_compliant():
    assert contract.check_contract(_SHAPE2_SEED, "shape2_seed.md", shape=2) == []


def test_shape4_seed_is_baseline_compliant():
    assert contract.check_contract(_SHAPE4_SEED, "shape4_seed.md", shape=4) == []


def test_skeptic_seed_is_the_real_narrow_not_yet_migrated_baseline():
    """skeptic.md's baseline is expected to be the EMPTY list post-Unit-1
    (2026-08-11) - the file is now fully Shape-3 compliant. If this
    drifts (e.g. skeptic.md gains a new baseline violation elsewhere),
    the skeptic mutations' set-difference logic silently loses precision,
    so pin it here."""
    assert _SKEPTIC_BASELINE == [], _SKEPTIC_BASELINE


# --- One pytest test per mutation, plus the aggregate ---


def test_no_survivors():
    survivors = run_survivors()
    assert survivors == [], (
        f"{len(survivors)} mutant(s) survived (checker returned [] on "
        f"genuinely non-compliant text): {survivors}"
    )


def _make_mutation_test(mutation_id, run):
    def test():
        baseline, mutant, caught = run()
        assert caught, (
            f"mutation '{mutation_id}' survived - checker did not reject "
            f"the mutant. baseline={baseline!r} mutant={mutant!r}"
        )
    test.__name__ = f"test_mutation_{mutation_id}"
    return test


for _mutation_id, _run in MUTATIONS:
    globals()[f"test_mutation_{_mutation_id}"] = _make_mutation_test(
        _mutation_id, _run
    )
del _mutation_id, _run
