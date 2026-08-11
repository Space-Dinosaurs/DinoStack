"""
Purpose: Mutation-testing harness for
         bin/tests/test_agent_return_contract_spec.py's check_contract()
         gate. Three prior rounds of that spec gate each shipped a
         defect where the checker was green because it checked nothing
         (round 1: 18/18 structural parse failure; round 2: fence-blind
         silent pass; round 3: a `pass`-bodied guard plus three
         auto-passing heuristics) - and every round's own fixtures were
         hand-authored by the same agent, in the same commit, as the
         checker they exercised, so they only ever probed the shape the
         author already had in mind. This file instead mechanically
         DERIVES non-compliant mutants from known-compliant seed texts
         (synthetic seeds built to isolate one nesting depth or one
         validated-line prefix at a time, plus the real skeptic.md
         corpus file for the six-prefix masking bug) and asserts every
         mutant is rejected. A mutant that survives (the checker returns
         [] on genuinely non-compliant text) is a defect in the checker
         under test, never a false report from this harness.

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
    return text.replace(old, new, 1)


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
# file. skeptic.md is NOT_YET_MIGRATED and already carries one baseline
# violation (the Calibration-section cap gap) - so "caught" is defined as
# the SPECIFIC expected violation appearing in the set difference against
# the baseline, never mere non-emptiness. A naive `violations != []` check
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
            "declares no numeric cap",
        ),
    ),
    (
        "shape4_no_cap_no_hint_word",
        _shape4_mutation(
            "<If status is not SUCCESS: which gate failed, what the error was, "
            "what was\ndone - max 500 chars>",
            "<Details of the blocker text>",
            "declares no numeric cap",
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
    """skeptic.md's baseline is expected to carry EXACTLY the one known
    Calibration-cap violation - if this drifts (e.g. skeptic.md gains a
    new baseline violation elsewhere), the skeptic mutations' set-difference
    logic silently loses precision, so pin it here."""
    assert _SKEPTIC_BASELINE == [
        "skeptic.md: Calibration section declares no explicit numeric cap "
        "on finding-description length"
    ], _SKEPTIC_BASELINE


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
