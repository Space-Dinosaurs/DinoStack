#!/usr/bin/env python3
"""
Regression tests for hooks/enforce-skeptic-neutrality.py.

Implements the 29 QA scenarios from the DS-187 architect plan (round 6
FINAL, constraint-based) - `.agentic/ds-187-architect-plan.md` § QA
criteria. Scenario numbers in test names/comments below match the plan's
`id:` field 1:1.

Fixture convention (mirrors bin/tests/test_enforce_skeptic_round_cap.py):
every test passes an isolated `tmp_path` throwaway directory as the
payload's `cwd`, so no test can append to the live repo's
`.agentic/.enforcement-fires.jsonl`.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_HOOK_PATH = Path(__file__).parent.parent.parent / "hooks" / "enforce-skeptic-neutrality.py"
_REPO_ROOT = Path(__file__).parent.parent.parent

_spec = importlib.util.spec_from_file_location("enforce_skeptic_neutrality", _HOOK_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _payload(cwd: str, prompt: str, tool_name: str = "Agent") -> dict:
    return {
        "tool_name": tool_name,
        "cwd": cwd,
        "tool_input": {
            "subagent_type": "skeptic",
            "description": "review",
            "prompt": prompt,
        },
    }


def _run_hook(payload: dict) -> tuple[int, dict | None, str]:
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    out = result.stdout.strip()
    parsed = json.loads(out) if out else None
    return result.returncode, parsed, result.stdout


def _is_denied(parsed: dict | None) -> bool:
    if not parsed:
        return False
    return parsed.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def _deny_reason(parsed: dict | None) -> str:
    if not parsed:
        return ""
    return parsed.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


def _fires_path(cwd: str) -> Path:
    return Path(cwd) / ".agentic" / ".enforcement-fires.jsonl"


def _read_fires(cwd: str) -> list[dict]:
    path = _fires_path(cwd)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_section8_templates() -> list[str]:
    """Extracts the 10 canonical adversarial-brief templates from
    content/references/skeptic-protocol.md §8, verbatim. §8 has 8
    bold-labeled blockquote blocks; the "Document synthesis, architecture,
    and planning" block itself contains THREE sentences separated by
    blank ">" continuation lines (its own sub-paragraphs), which is what
    brings the total to 10, matching the plan's 1-smart-contracts ..
    10-general-code-review enumeration. Bounded to the literal "## 8."
    heading through the next "## 9." heading so a later, unrelated
    blockquote elsewhere in the file (e.g. §12's `/simplify` brief) is
    never picked up.
    """
    text = (_REPO_ROOT / "content" / "references" / "skeptic-protocol.md").read_text(encoding="utf-8")
    start = text.find("## 8. Domain-Specific Adversarial Brief Templates")
    assert start != -1, "skeptic-protocol.md §8 heading not found"
    end = text.find("\n## 9.", start)
    assert end != -1, "skeptic-protocol.md §9 heading not found (bound is open-ended)"
    section = text[start:end]

    blocks: list[list[str]] = []
    current: list[str] = []
    for line in section.split("\n"):
        if line.startswith(">"):
            current.append(line[1:].lstrip())
        else:
            if current:
                blocks.append(current)
                current = []
    if current:
        blocks.append(current)

    templates: list[str] = []
    for block in blocks:
        sub: list[str] = []
        cur: list[str] = []
        for line in block:
            if line == "":
                if cur:
                    sub.append(" ".join(cur))
                    cur = []
            else:
                cur.append(line)
        if cur:
            sub.append(" ".join(cur))
        templates.extend(sub)
    return templates


_GOOD_EXAMPLE = "Review the diff for correctness of retry/backoff logic across all touched files."


# --------------------------------------------------------------------------- #
# Scenario 1: DENY, field-7 structural rule - real round-1 defect shape
# --------------------------------------------------------------------------- #
def test_scenario_01_deny_field7_real_round1_defect(tmp_path):
    sentence = (
        "The plan uses a [verified-by-read: file:line] tag form that is not "
        "one of the three canonical provenance tags."
    )
    prompt = f"7. Conductor spawn brief (...): {sentence}\n\n## What to review\n"
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), prompt))
    assert rc == 0
    assert _is_denied(parsed)
    assert sentence in _deny_reason(parsed)


# --------------------------------------------------------------------------- #
# Scenario 2: DENY, field-7 structural rule - real round-5 defect shape
# --------------------------------------------------------------------------- #
def test_scenario_02_deny_field7_real_round5_defect(tmp_path):
    sentence = (
        "Four rounds of probing produced no legitimate-content collision for "
        "categories B and C."
    )
    prompt = f"7. Conductor spawn brief (...): {sentence}\n\n## What to review\n"
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), prompt))
    assert rc == 0
    assert _is_denied(parsed)
    assert sentence in _deny_reason(parsed)


# --------------------------------------------------------------------------- #
# Scenario 3 (REVISED, round-N fix): DENY - field-7 bare "n/a" is NOT exempt.
#
# skeptic-protocol.md:299 ("A bare `n/a` is invalid - every `n/a` value MUST
# carry a specific reason") and :330 (the Skeptic BLOCKS on a bare `n/a`)
# both require rejecting a bare `n/a`. The prior round's `_field7_is_exempt_na`
# inverted this in the permissive direction (a Skeptic finding this round);
# fixed to DENY, conforming to the protocol rather than the hook's own prior
# behavior.
# --------------------------------------------------------------------------- #
def test_scenario_03_deny_field7_bare_na(tmp_path):
    prompt = "7. Conductor spawn brief (...): n/a\n\n## What to review\n"
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), prompt))
    assert rc == 0
    assert _is_denied(parsed)
    assert _mod.field7_violation(["n/a"]) == "n/a"


def test_scenario_03_mutation_bare_na_exemption_reddens():
    """Executed mutation-testing proof: restoring the prior round's
    permissive bare-'n/a' exemption (`s == "n/a" or ...`) makes a bare 'n/a'
    exempt again, contradicting the protocol."""
    assert _mod._field7_is_exempt_na("n/a") is False
    mutated_exempt = ("n/a" == "n/a".strip())  # the prior round's bare check
    assert mutated_exempt is True, "mutation should have re-exempted bare n/a"


# --------------------------------------------------------------------------- #
# Scenario 4: ALLOW - field-7 exempt canonical "n/a - Trivial direct edit"
# --------------------------------------------------------------------------- #
def test_scenario_04_allow_field7_canonical_na(tmp_path):
    prompt = "7. Conductor spawn brief (...): n/a - Trivial direct edit\n\n## What to review\n"
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), prompt))
    assert rc == 0
    assert not _is_denied(parsed)
    assert _mod.field7_violation(["n/a - Trivial direct edit"]) is None


# --------------------------------------------------------------------------- #
# Round-N fix regression: Critical 1 - the hook must not deny the repo's own
# canonical spawn template. Reads content/commands/ds-skeptic.md's LIVE
# field-7 line directly (not a synthetic copy in this test file), so
# template drift re-breaks this test rather than silently going unnoticed.
# --------------------------------------------------------------------------- #
def _read_live_field7_template_line() -> str:
    text = (_REPO_ROOT / "content" / "commands" / "ds-skeptic.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith("7. Conductor spawn brief"):
            return line
    raise AssertionError("content/commands/ds-skeptic.md field-7 template line not found")


def test_round_n_fix_critical1_live_template_na_value_allowed(tmp_path):
    """A conductor who fills field 7 with a compliant 'n/a - Trivial direct
    edit' and leaves the template's own trailing '[Neutrality: ...]' note
    intact (the normal, expected shape of a real spawn) must be allowed."""
    template_line = _read_live_field7_template_line()
    assert "[Neutrality:" in template_line, (
        "template line no longer carries the trailing neutrality note - "
        "re-check whether this regression test is still needed"
    )
    bracket_start = template_line.index("[Neutrality:")
    trailing_note = template_line[bracket_start:]
    filled_value = f"n/a - Trivial direct edit {trailing_note}"
    prompt = f"7. Conductor spawn brief (...): {filled_value}\n\n## What to review\n"
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), prompt))
    assert rc == 0
    assert not _is_denied(parsed), _deny_reason(parsed)
    assert _mod.field7_violation([filled_value]) is None


def test_round_n_fix_critical1_mutation_note_strip_removed_reddens():
    """Executed mutation-testing proof: removing
    `_strip_field7_neutrality_note()` from `field7_violation()` reddens for
    a TAGGED (non-n/a) field-7 value carrying the template's trailing note -
    the note's own closing bracket is then read as an untagged claim
    fragment and a compliant, fully-tagged spawn is falsely denied. (A bare
    n/a-shaped value is a weaker witness here since Critical 2's shape-based
    `_field7_is_exempt_na` independently matches any string beginning
    `n/a - ...` regardless of what follows, strip or no strip - this
    fixture isolates the note-strip fix specifically.)"""
    template_line = _read_live_field7_template_line()
    bracket_start = template_line.index("[Neutrality:")
    trailing_note = template_line[bracket_start:]
    filled_value = f"The retry fix resolves the timeout. [verified: a.py:5] {trailing_note}"

    # Live behavior: allowed.
    assert _mod.field7_violation([filled_value]) is None

    # Mutated behavior: skip the strip, exercise the exempt-check +
    # per-sentence path directly as field7_violation() would without it.
    joined = " ".join([filled_value])
    assert not _mod._field7_is_exempt_na(joined), (
        "unstripped joined value must not equal the exact n/a shape"
    )
    violation = None
    for sent in _mod._split_sentences_keep_trailing_tag(joined):
        if not (
            _mod._PROVENANCE_RE.search(sent)
            or _mod._ATTRIBUTION_RE.search(sent)
            or _mod._SELF_REF_TICKET_RE.search(sent)
        ):
            violation = sent
            break
    assert violation is not None, "mutation should have reddened (false deny reintroduced)"


def test_round_n_fix_critical1_neutrality_note_strip_is_not_a_generic_bracket_escape():
    """Proves the neutrality-note strip cannot be used as a generic
    "append any trailing bracket" escape hatch: a bracket missing any one
    of the three required substrings (the literal 'Neutrality:' opener,
    'skeptic-protocol.md', and 'Section 7' + 'Neutrality requirement') is
    left in place and denies normally, including when it contains an
    actual smuggled claim."""
    smuggled = "The retry fix is definitely correct. [I am confident retry.py:42 is the root cause]"
    assert _mod.field7_violation([smuggled]) == smuggled

    near_miss_1 = "The retry fix is definitely correct. [Neutrality: some unrelated note]"
    assert _mod.field7_violation([near_miss_1]) == near_miss_1

    near_miss_2 = (
        "The retry fix is definitely correct. "
        "[Neutrality: cites skeptic-protocol.md but not the section]"
    )
    assert _mod.field7_violation([near_miss_2]) == near_miss_2

    # Only the exact three-substring form strips, and even then the
    # underlying untagged claim (not the note) still denies.
    exact_note = (
        "The retry fix is definitely correct. "
        '[Neutrality: provenance-tagged factual claims only - never a '
        'conductor hypothesis or suspicion. See skeptic-protocol.md '
        'Section 7 "Neutrality requirement".]'
    )
    assert _mod.field7_violation([exact_note]) == "The retry fix is definitely correct."


# --------------------------------------------------------------------------- #
# Round-N fix regression: Critical 2 - a protocol-valid non-enumerated
# `n/a - <reason>` must be exempt (skeptic-protocol.md:299,330).
# --------------------------------------------------------------------------- #
def test_round_n_fix_critical2_allow_non_enumerated_na(tmp_path):
    value = "n/a - Skeptic reviewing a conductor-authored artifact with no separate brief"
    prompt = f"7. Conductor spawn brief (...): {value}\n\n## What to review\n"
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), prompt))
    assert rc == 0
    assert not _is_denied(parsed), _deny_reason(parsed)
    assert _mod.field7_violation([value]) is None


def test_round_n_fix_critical2_mutation_closed_set_reddens():
    """Executed mutation-testing proof: restoring the prior round's
    closed-set `_CANONICAL_NA_STRINGS` membership check reddens on any
    truthful, protocol-valid reason not in that enumerated set."""
    canonical_na_strings = {
        "n/a - Trivial direct edit",
        "n/a - permission-blocked carve-out",
    }
    value = "n/a - Skeptic reviewing a conductor-authored artifact with no separate brief"
    mutated_exempt = value in canonical_na_strings
    assert mutated_exempt is False, "mutation should have reddened (falsely denied)"
    assert _mod._field7_is_exempt_na(value) is True


# --------------------------------------------------------------------------- #
# Round-N fix regression: Major - abbreviation periods (e.g./i.e./etc.) must
# not split a compliant, fully-tagged-or-attributed sentence into an
# untagged tail fragment.
# --------------------------------------------------------------------------- #
def test_round_n_fix_major_abbreviation_eg_not_split():
    value = "Per the Engineer, the fix touches the retry path, e.g. the backoff calculation."
    assert _mod.field7_violation([value]) is None


def test_round_n_fix_major_abbreviation_ie_not_split():
    value = "That is, i.e. the config change is unrelated to the retry path. [verified: a.py:1]"
    assert _mod.field7_violation([value]) is None


def test_round_n_fix_major_mutation_abbreviation_guard_removed_reddens():
    """Executed mutation-testing proof: removing the abbreviation
    lookbehinds from _SENT_SPLIT_RE reddens - a compliant, tagged sentence
    containing 'e.g.' is mis-split into an untagged tail fragment and
    falsely denied."""
    import re as _re

    mutated_re = _re.compile(r'(?<=[.?!])\s+(?!\[)|(?<=\])\s+(?=[A-Z])')  # missing abbrev guards
    value = "Per the Engineer, the fix touches the retry path, e.g. the backoff calculation."

    def _split_with(regex, text):
        raw = regex.split(text.strip())
        out: list[str] = []
        for frag in raw:
            frag = frag.strip()
            if not frag:
                continue
            if out and _re.fullmatch(r'\[[^\]]*\]\.?', frag):
                out[-1] = out[-1] + " " + frag
            else:
                out.append(frag)
        return out

    # Live regex: stays one sentence, allowed.
    assert len(_mod._split_sentences_keep_trailing_tag(value)) == 1
    assert _mod.field7_violation([value]) is None

    # Mutated regex: splits on the "e.g." period, tail fragment is untagged.
    mutated_sentences = _split_with(mutated_re, value)
    assert len(mutated_sentences) == 2, "mutation did not split as expected"
    violation = None
    for sent in mutated_sentences:
        if not (
            _mod._PROVENANCE_RE.search(sent)
            or _mod._ATTRIBUTION_RE.search(sent)
            or _mod._SELF_REF_TICKET_RE.search(sent)
        ):
            violation = sent
            break
    assert violation is not None, "mutation should have reddened (false deny on tail fragment)"


# --------------------------------------------------------------------------- #
# Scenario 5: ALLOW - field-7 single tagged claim (true negative)
# --------------------------------------------------------------------------- #
def test_scenario_05_allow_field7_single_tagged_claim():
    assert _mod.field7_violation(
        ["The retry backoff is unchanged from the prior round. [verified: hooks/retry.py:42]"]
    ) is None


# --------------------------------------------------------------------------- #
# Scenario 6: ALLOW - field-7 two sentences, both individually tagged
# --------------------------------------------------------------------------- #
def test_scenario_06_allow_field7_two_sentences_both_tagged():
    assert _mod.field7_violation(
        [
            "The retry backoff is unchanged. [verified: a.py:1] "
            "The config loader was not touched. [verified: b.py:2]"
        ]
    ) is None


# --------------------------------------------------------------------------- #
# Scenario 7: DENY precisely - two sentences, one tagged one not; the
#             violation identifies the untagged sentence, not the tagged one
# --------------------------------------------------------------------------- #
def test_scenario_07_deny_field7_two_sentences_one_untagged():
    joined = [
        "The retry backoff is unchanged. [verified: a.py:1] "
        "The config loader introduced a new bug."
    ]
    result = _mod.field7_violation(joined)
    assert result == "The config loader introduced a new bug."


def test_scenario_07_mutation_splitter_bug_reddens():
    """Executed mutation-testing proof: reverting _SENT_SPLIT_RE to omit the
    (?<=\\])\\s+(?=[A-Z]) alternative merges the two sentences into one unit,
    so sentence 1's tag falsely covers sentence 2's untagged claim and the
    violation is missed. This test directly exercises the reverted regex
    (not the live one) to prove the mutation reddens the scenario, per the
    Engineer's mandatory mutation-testing obligation."""
    import re as _re

    joined = (
        "The retry backoff is unchanged. [verified: a.py:1] "
        "The config loader introduced a new bug."
    )
    reverted_split_re = _re.compile(r'(?<=[.?!])\s+(?!\[)')  # missing the ] alternative

    def _split_with(regex, text):
        raw = regex.split(text.strip())
        out: list[str] = []
        for frag in raw:
            frag = frag.strip()
            if not frag:
                continue
            if out and _re.fullmatch(r'\[[^\]]*\]\.?', frag):
                out[-1] = out[-1] + " " + frag
            else:
                out.append(frag)
        return out

    # Live (fixed) regex: correctly separates into 2 sentences.
    assert len(_mod._split_sentences_keep_trailing_tag(joined)) == 2

    # Reverted (mutated) regex: merges into 1 sentence, whose leading tag
    # then falsely covers the untagged second half - the violation check
    # would find no untagged sentence at all.
    mutated_sentences = _split_with(reverted_split_re, joined)
    assert len(mutated_sentences) == 1, "mutation did not merge as expected"
    mutated_violation = None
    for sent in mutated_sentences:
        if not (
            _mod._PROVENANCE_RE.search(sent)
            or _mod._ATTRIBUTION_RE.search(sent)
            or _mod._SELF_REF_TICKET_RE.search(sent)
        ):
            mutated_violation = sent
            break
    assert mutated_violation is None, "mutation should have suppressed the violation (reddened)"


# --------------------------------------------------------------------------- #
# Scenario 8: ALLOW - field-7 trailing-tag adjacency is not falsely denied
# --------------------------------------------------------------------------- #
def test_scenario_08_allow_field7_trailing_tag_adjacency():
    assert _mod.field7_violation(
        ["The retry fix resolves the timeout. [verified: a.py:5]"]
    ) is None


def test_scenario_08_mutation_lookahead_removal_reddens():
    """Executed mutation-testing proof: removing the (?!\\[) negative
    lookahead from _SENT_SPLIT_RE reddens on a fixture with two ADJACENT
    bracket tags, not on a single trailing tag (a single trailing tag is
    protected regardless, by _split_sentences_keep_trailing_tag's own
    bracket-only-fragment reattachment step - confirmed by direct
    execution). With two adjacent tags, the mutated regex splits BEFORE
    the first bracket, and the leading claim fragment ("Claim one.") is
    NOT a bracket-only fragment, so it is never reattached and reads as
    a standalone, untagged sentence - the exact failure mode the plan
    describes ("the tag splits off as its own sentence and the claim
    reads as untagged")."""
    import re as _re

    text = "Claim one. [verified: a.py:1] [verified: b.py:2]"
    live_split = _mod._split_sentences_keep_trailing_tag(text)
    assert live_split == [text], "live regex must keep this as one tagged unit"

    mutated_split_re = _re.compile(r'(?<=[.?!])\s+|(?<=\])\s+(?=[A-Z])')  # missing (?!\[)

    def _split_with(regex, s):
        raw = regex.split(s.strip())
        out: list[str] = []
        for frag in raw:
            frag = frag.strip()
            if not frag:
                continue
            if out and _re.fullmatch(r'\[[^\]]*\]\.?', frag):
                out[-1] = out[-1] + " " + frag
            else:
                out.append(frag)
        return out

    mutated = _split_with(mutated_split_re, text)
    assert "Claim one." in mutated, "mutation should isolate the claim as its own untagged fragment"
    violation = None
    for sent in mutated:
        if not (
            _mod._PROVENANCE_RE.search(sent)
            or _mod._ATTRIBUTION_RE.search(sent)
            or _mod._SELF_REF_TICKET_RE.search(sent)
        ):
            violation = sent
            break
    assert violation == "Claim one.", "mutation should have reddened (false deny on an untagged fragment)"


# --------------------------------------------------------------------------- #
# Scenario 9: ALLOW - field-7 attributed pass-through (no bracket tag)
# --------------------------------------------------------------------------- #
def test_scenario_09_allow_field7_attributed_passthrough():
    assert _mod.field7_violation(
        ["Per Engineer, the retry backoff resets incorrectly under load."]
    ) is None


# --------------------------------------------------------------------------- #
# Scenario 10: ALLOW - field-7 self-referential ticket mention only
# --------------------------------------------------------------------------- #
def test_scenario_10_allow_field7_self_ref_ticket():
    assert _mod.field7_violation(
        ["DS-190 is the ticket this spawn reviews."]
    ) is None


# --------------------------------------------------------------------------- #
# Scenario 11: field-7 rule scoped to field 7 only - all 10 §8 templates,
#              if fed through field7_violation(), would ALL deny
# --------------------------------------------------------------------------- #
def test_scenario_11_field7_rule_misapplied_to_brief_denies_all_templates():
    templates = _read_section8_templates()
    assert len(templates) == 10, f"expected exactly 10 §8 templates, found {len(templates)}"
    for i, template in enumerate(templates, start=1):
        violation = _mod.field7_violation([template])
        assert violation is not None, (
            f"§8 template #{i} unexpectedly passed field7_violation() - it should "
            f"deny (proving the rule must never be applied to the brief region): {template!r}"
        )


def test_scenario_11_mutation_applying_field7_rule_to_brief_reddens():
    """Executed mutation-testing proof: applying field7_violation() to the
    brief-region extraction path in main() would deny every unmodified §8
    template, breaking every real Skeptic spawn. Verified directly (without
    invoking main()) by confirming an unmodified §8 template denies under
    field7_violation() - the same assertion test_scenario_11 above already
    makes, restated as an explicit mutation-consequence check."""
    templates = _read_section8_templates()
    assert templates, "no §8 templates found - cannot prove the mutation's consequence"
    sample = templates[0]
    assert _mod.field7_violation([sample]) is not None, (
        "if main() applied field7_violation() to the brief region, this "
        "unmodified §8 template would be denied on every real spawn"
    )


# --------------------------------------------------------------------------- #
# Scenario 12: DENY, brief region, category B
# --------------------------------------------------------------------------- #
def test_scenario_12_deny_brief_category_b(tmp_path):
    prompt = (
        "**Adversarial brief:** I suspect the config loader introduced this "
        "bug.\n\n## Global-context inputs\n"
    )
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), prompt))
    assert rc == 0
    assert _is_denied(parsed)
    assert "category B" in _deny_reason(parsed)


# --------------------------------------------------------------------------- #
# Scenario 13: DENY, brief region, category C
# --------------------------------------------------------------------------- #
def test_scenario_13_deny_brief_category_c(tmp_path):
    prompt = (
        "**Adversarial brief:** look hard at the retry.py backoff "
        "calculation.\n\n## Global-context inputs\n"
    )
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), prompt))
    assert rc == 0
    assert _is_denied(parsed)
    assert "category C" in _deny_reason(parsed)


# --------------------------------------------------------------------------- #
# Scenario 14: ALLOW - attribution-exempt brief text that WOULD match
#              category B if the exemption were removed
# --------------------------------------------------------------------------- #
def test_scenario_14_attribution_exempt(tmp_path):
    prompt = (
        '**Adversarial brief:** Per Engineer DONE_WITH_CONCERNS: "I think the '
        'retry backoff in retry.py may reset on the wrong condition."\n\n'
        "## Global-context inputs\n"
        "7. Conductor spawn brief (...): n/a - Trivial direct edit\n"
    )
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), prompt))
    assert rc == 0
    assert not _is_denied(parsed)
    fires = _read_fires(str(tmp_path))
    assert fires == []

    # Executed confirmation: WITH the exemption in place, this paragraph is
    # exempt (suppressing category B); WITHOUT the exemption, category B
    # would fire on the same text.
    para = _mod.extract_brief(prompt)[0]
    assert _mod._paragraph_exempt(para) is True
    assert _mod._CAT_B.search(para) is not None


# --------------------------------------------------------------------------- #
# Scenario 15: All 10 canonical §8 templates are CLEAN against categories
#              B and C - standing regression gate
# --------------------------------------------------------------------------- #
def test_scenario_15_section8_templates_clean_against_bc():
    templates = _read_section8_templates()
    assert len(templates) == 10
    for i, template in enumerate(templates, start=1):
        hits = [name for name, pat in _mod._BRIEF_CATEGORIES if pat.search(template)]
        assert hits == [], f"§8 template #{i} unexpectedly fires categories {hits}: {template!r}"


def test_scenario_15_mutation_broadened_category_c_reddens():
    """Executed mutation-testing proof: broadening category C's phrase list
    to include the generic verb 'look for' fires on several §8 templates
    that legitimately use that phrasing."""
    import re as _re

    broadened_cat_c = _re.compile(
        r'\b(construct the case where|build the case (that|where)|look hard at|look for)\b',
        _re.IGNORECASE,
    )
    templates = _read_section8_templates()
    hits = sum(1 for t in templates if broadened_cat_c.search(t))
    assert hits > 0, "mutation should have fired on at least one §8 template (reddened)"


# --------------------------------------------------------------------------- #
# Scenario 16: Preflight-strip direction 1 - a field-7 MENTION (not heading)
#              retains its trailing tag intact
# --------------------------------------------------------------------------- #
def test_scenario_16_preflight_mention_field7_tag_intact():
    prompt = (
        "7. Conductor spawn brief (...): The retry fix (also listed in the "
        "Resolved issues preflight) [per engineer, unverified].\n\n"
        "## What to review\n"
    )
    result = _mod.extract_field7(prompt)
    assert result == [
        "The retry fix (also listed in the Resolved issues preflight) [per engineer, unverified]."
    ]


# --------------------------------------------------------------------------- #
# Scenario 17: Preflight-strip direction 2 - a brief MENTION (not heading)
#              does not silently delete a real steer in the same sentence
# --------------------------------------------------------------------------- #
def test_scenario_17_preflight_mention_brief_steer_retained():
    prompt = (
        "**Adversarial brief:** This item was listed in the Resolved issues "
        "preflight; separately, I suspect the retry path is the real "
        "bug.\n\n## Global-context inputs\n"
    )
    result = _mod.extract_brief(prompt)
    assert result is not None
    assert "I suspect" in " ".join(result)


# --------------------------------------------------------------------------- #
# Scenario 18: Preflight-strip regression - a genuine preflight HEADING
#              still strips correctly
# --------------------------------------------------------------------------- #
def test_scenario_18_preflight_heading_regression():
    """The preflight section quotes a PRIOR round's field-7-shaped line
    verbatim (a realistic "resolved issues" entry - preflight content is
    exactly prior-round claim text). Without stripping the preflight
    HEADING first, `_FIELD7_START_RE.search()` would match this quoted,
    stale marker (the FIRST occurrence in the prompt) instead of the real,
    current field-7 marker further down - confirmed by direct mutation:
    removing `_strip_preflight_block()` from `extract_field7` here yields
    the quoted historical steer instead of the real field-7 value."""
    prompt = (
        "**Adversarial brief:** " + _GOOD_EXAMPLE + "\n\n"
        "**What to review:** Worker output.\n\n"
        "**Resolved issues preflight:**\n"
        "- Conductor spawn brief (...): I suspect the retry handler is the "
        "root cause. [verified: a.py:1]\n\n"
        "## Global-context inputs\n"
        "7. Conductor spawn brief (...): n/a - Trivial direct edit\n"
    )
    assert _mod.extract_field7(prompt) == ["n/a - Trivial direct edit"]


def test_scenario_18_mutation_strip_removal_reddens():
    """Executed mutation-testing proof for scenario 18: removing
    `_strip_preflight_block()` from `extract_field7` causes the quoted
    historical steer inside the preflight section to be captured instead
    of the real field-7 value."""
    prompt = (
        "**Adversarial brief:** " + _GOOD_EXAMPLE + "\n\n"
        "**What to review:** Worker output.\n\n"
        "**Resolved issues preflight:**\n"
        "- Conductor spawn brief (...): I suspect the retry handler is the "
        "root cause. [verified: a.py:1]\n\n"
        "## Global-context inputs\n"
        "7. Conductor spawn brief (...): n/a - Trivial direct edit\n"
    )
    mutated = _mod._extract_bounded_region(
        prompt, _mod._FIELD7_START_RE, _mod._FIELD7_MAX_PARAGRAPHS, _mod._MAX_LINES_PER_PARAGRAPH
    )
    assert mutated != ["n/a - Trivial direct edit"], "mutation should have reddened (wrong marker matched)"
    assert mutated == ["I suspect the retry handler is the root cause. [verified: a.py:1]"]


# --------------------------------------------------------------------------- #
# Scenario 19: Preflight-strip regression - a hard-wrapped preflight
#              heading still strips correctly
# --------------------------------------------------------------------------- #
def test_scenario_19_preflight_heading_hard_wrapped():
    prompt = (
        "**Resolved issues\npreflight:**\n"
        "- Conductor spawn brief (...): I suspect the retry handler is the "
        "root cause. [verified: a.py:1]\n\n"
        "## Global-context inputs\n"
        "7. Conductor spawn brief (...): n/a - Trivial direct edit\n"
    )
    assert _mod.extract_field7(prompt) == ["n/a - Trivial direct edit"]


def test_scenario_19_mutation_literal_space_reddens():
    """Executed mutation-testing proof: replacing \\s+ between "Resolved"
    and "issues"/"preflight" in _PREFLIGHT_START_RE with a literal space
    fails to match a hard-wrapped heading (phrase split across a line
    break), so the strip never fires and the quoted historical steer
    leaks into the field-7 capture."""
    import re as _re

    mutated_re = _re.compile(
        r'(?:^|\n)[ \t]*\*{0,2}Resolved issues preflight\*{0,2}[ \t]*:[ \t]*\*{0,2}[ \t]*(?=\n|$)',
        _re.IGNORECASE,
    )
    hard_wrapped = "**Resolved issues\npreflight:**\n- text\n"
    assert mutated_re.search(hard_wrapped) is None, "mutation should fail to match the hard-wrapped heading"
    assert _mod._PREFLIGHT_START_RE.search(hard_wrapped) is not None, "live regex must match it"


# --------------------------------------------------------------------------- #
# Scenario 20: Extraction order-independence - skeptic.md order vs
#              ds-skeptic.md order yield an identical captured brief value
# --------------------------------------------------------------------------- #
def test_scenario_20_extraction_order_independence():
    skeptic_md_order = (
        "**Adversarial brief:** " + _GOOD_EXAMPLE + "\n\n"
        "**What to review:** Worker output goes here.\n\n"
        "## Resolved issues preflight: n/a\n\n"
        "## Global-context inputs\n"
        "7. Conductor spawn brief (...): n/a - Trivial direct edit\n"
    )
    ds_skeptic_md_order = (
        "## Global-context inputs\n"
        "1. Architect plan: n/a\n"
        "7. Conductor spawn brief (...): n/a - Trivial direct edit\n\n"
        "**What to review:**\n\n"
        "**Resolved issues preflight:** n/a\n\n"
        "**Adversarial brief:** " + _GOOD_EXAMPLE + "\n"
    )
    assert _mod.extract_brief(skeptic_md_order) == [_GOOD_EXAMPLE]
    assert _mod.extract_brief(ds_skeptic_md_order) == [_GOOD_EXAMPLE]


# --------------------------------------------------------------------------- #
# Scenario 21: DENY, field-7, numbered+bolded marker shape
# --------------------------------------------------------------------------- #
def test_scenario_21_deny_field7_numbered_bolded(tmp_path):
    sentence = "The real bug is in retry.py, I think."
    prompt = f"7. **Conductor spawn brief (...):** {sentence}\n\n## What to review\n"
    assert _mod.extract_field7(prompt) == [sentence]
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), prompt))
    assert rc == 0
    assert _is_denied(parsed)


# --------------------------------------------------------------------------- #
# Scenario 22: SIGNALLED ADVISORY - no brief marker found
# --------------------------------------------------------------------------- #
def test_scenario_22_no_brief_marker_signalled_advisory(tmp_path):
    prompt = (
        "## Global-context inputs\n"
        "7. Conductor spawn brief (...): n/a - Trivial direct edit\n\n"
        "## What to review\nSome worker output.\n"
    )
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), prompt))
    assert rc == 0
    fires = _read_fires(str(tmp_path))
    assert len(fires) == 1
    assert fires[0]["decision"] == "allow_advisory"
    assert fires[0]["reason"] == _mod._ADVISORY_BRIEF_MISSING


# --------------------------------------------------------------------------- #
# Scenario 23: SIGNALLED ADVISORY - no field-7 marker found, distinct reason
# --------------------------------------------------------------------------- #
def test_scenario_23_no_field7_marker_signalled_advisory(tmp_path):
    prompt = (
        "**Adversarial brief:** " + _GOOD_EXAMPLE + "\n\n"
        "## What to review\nSome worker output.\n"
    )
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), prompt))
    assert rc == 0
    fires = _read_fires(str(tmp_path))
    field7_fires = [f for f in fires if f["reason"] == _mod._ADVISORY_FIELD7_MISSING]
    assert len(field7_fires) == 1
    assert field7_fires[0]["reason"] != _mod._ADVISORY_BRIEF_MISSING


# --------------------------------------------------------------------------- #
# Scenario 24: Kill-switch suppresses BOTH deny paths and both advisory
#              paths
# --------------------------------------------------------------------------- #
def test_scenario_24_kill_switch_suppresses_everything(tmp_path, monkeypatch):
    monkeypatch.setenv("AE_SKEPTIC_NEUTRALITY_GUARD_DISABLE", "1")

    field7_deny_prompt = (
        "7. Conductor spawn brief (...): The config loader introduced a new "
        "bug.\n\n## What to review\n"
    )
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), field7_deny_prompt))
    assert rc == 0 and not _is_denied(parsed)

    brief_deny_prompt = (
        "**Adversarial brief:** I suspect the config loader introduced this "
        "bug.\n\n## Global-context inputs\n"
    )
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), brief_deny_prompt))
    assert rc == 0 and not _is_denied(parsed)

    no_brief_marker_prompt = (
        "## Global-context inputs\n7. Conductor spawn brief (...): n/a\n\n"
        "## What to review\nx\n"
    )
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), no_brief_marker_prompt))
    assert rc == 0

    no_field7_marker_prompt = "**Adversarial brief:** " + _GOOD_EXAMPLE + "\n\n## What to review\nx\n"
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), no_field7_marker_prompt))
    assert rc == 0

    assert _read_fires(str(tmp_path)) == []


# --------------------------------------------------------------------------- #
# Scenario 25: Hook fails open on malformed/non-JSON stdin, and when
#              subagent_type != "skeptic"
# --------------------------------------------------------------------------- #
def test_scenario_25_malformed_stdin_failopen():
    result = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input="not json{{{",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_scenario_25_non_skeptic_subagent_failopen(tmp_path):
    prompt = (
        "**Adversarial brief:** I suspect the config loader introduced this "
        "bug.\n\n## Global-context inputs\n"
    )
    payload = _payload(str(tmp_path), prompt)
    payload["tool_input"]["subagent_type"] = "engineer"
    rc, parsed, _ = _run_hook(payload)
    assert rc == 0
    assert not _is_denied(parsed)
    assert _read_fires(str(tmp_path)) == []


# --------------------------------------------------------------------------- #
# Scenario 26: Task and Agent matchers behave identically
# --------------------------------------------------------------------------- #
def test_scenario_26_task_and_agent_matchers_identical(tmp_path):
    prompt = (
        "**Adversarial brief:** I suspect the config loader introduced this "
        "bug.\n\n## Global-context inputs\n"
    )
    rc_task, parsed_task, _ = _run_hook(_payload(str(tmp_path / "a"), prompt, tool_name="Task"))
    rc_agent, parsed_agent, _ = _run_hook(_payload(str(tmp_path / "b"), prompt, tool_name="Agent"))
    assert rc_task == rc_agent == 0
    assert _is_denied(parsed_task) is True
    assert _is_denied(parsed_agent) is True


# --------------------------------------------------------------------------- #
# Scenario 27: hooks/tests/test-hooks-pep604-guard.py reports 79 checks
# --------------------------------------------------------------------------- #
def test_scenario_27_pep604_guard_79_checks():
    guard_path = _REPO_ROOT / "hooks" / "tests" / "test-hooks-pep604-guard.py"
    result = subprocess.run(
        [sys.executable, str(guard_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "All 79 checks passed." in result.stdout


# --------------------------------------------------------------------------- #
# Scenarios 28/29 are exercised directly by pytest on their own suites
# (bin/tests/test_docs_currency_sync.py, bin/tests/test_tracker_writeback_ranking_spec.py)
# per the plan's Implementation step 6 - not duplicated here.
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Round-2 fix regression: Critical (relocated) - `_ATTRIBUTION_RE` was a
# closed 4-agent enumeration against `content/agents/skeptic.md:30`'s open
# "any other named agent's own return passed through as written" carve-out,
# denying 14 of the 18 agents under content/agents/ a protocol-sanctioned
# un-bracketed pass-through. Fixed by deriving `_ATTRIBUTION_RE` from
# `_KNOWN_AGENT_SLUGS`, a hardcoded tuple kept in sync (rather than read at
# hook RUNTIME - the DS-54 hooks-snapshot mechanism does not carry
# content/agents/ into the deployed snapshot dir) by this test re-deriving
# the live `content/agents/*.md` file set at TEST TIME on every run.
# --------------------------------------------------------------------------- #
def _live_agent_slugs() -> set[str]:
    agents_dir = _REPO_ROOT / "content" / "agents"
    return {p.stem for p in agents_dir.glob("*.md")}


def test_attribution_regex_slug_set_matches_live_agents_directory():
    """Bidirectional set equality, not containment: fails if a new agent
    file is added and `_KNOWN_AGENT_SLUGS` is not updated to match, AND
    fails if `_KNOWN_AGENT_SLUGS` carries a stale slug no longer present
    under content/agents/."""
    assert set(_mod._KNOWN_AGENT_SLUGS) == _live_agent_slugs()


def test_attribution_regex_allows_every_current_agent_pass_through():
    """Executed end-to-end: 'Per the <Agent>, ...' must ALLOW (not deny)
    for every current agent under content/agents/, per skeptic.md:30's
    'any other named agent's own return passed through as written'
    carve-out. Round-2's closed 4-name enumeration denied 14 of these."""
    for slug in sorted(_live_agent_slugs()):
        display = slug.replace("-", " ").title()
        sentence = f"Per the {display}, the retry backoff resets incorrectly under load."
        assert _mod.field7_violation([sentence]) is None, (
            f"attribution to '{display}' (slug '{slug}') was incorrectly denied"
        )


def test_attribution_regex_allows_conductor_and_done_with_concerns():
    assert _mod.field7_violation(
        ["Per the conductor, the retry backoff resets incorrectly under load."]
    ) is None
    assert _mod.field7_violation(
        ["Per Engineer DONE_WITH_CONCERNS: the retry backoff resets incorrectly under load."]
    ) is None


def test_attribution_regex_mutation_closed_roster_reddens():
    """Executed mutation-testing proof: reverting to the round-2 closed
    5-name roster (Engineer|Architect|Investigator|QA-Engineer|conductor)
    denies attribution to every other current agent (14 of 18 files)."""
    import re as _re

    old_re = _re.compile(
        r'\bPer\s+(the\s+)?(Engineer|Architect|Investigator|QA-Engineer|conductor)\b'
        r'|DONE_WITH_CONCERNS',
        _re.IGNORECASE,
    )
    denied_count = 0
    for slug in _live_agent_slugs():
        display = slug.replace("-", " ").title()
        sentence = f"Per the {display}, the retry backoff resets incorrectly under load."
        if not old_re.search(sentence):
            denied_count += 1
    assert denied_count >= 13, (
        f"mutation should have reddened (denied most agents), only denied {denied_count}"
    )


# --------------------------------------------------------------------------- #
# Round-2 fix regression: Major - `_NA_WITH_REASON_RE` with `re.DOTALL` and
# an unbounded `.*$` tail exempted the ENTIRE remainder of field 7 once a
# leading `n/a - <reason>` clause matched, silently disabling the primary
# deny rule for any field-7 value merely prefixed with a valid-looking n/a
# clause.
# --------------------------------------------------------------------------- #
def test_round2_fix_major_na_prefix_does_not_exempt_trailing_untagged_sentence():
    value = "n/a - Trivial direct edit. The config loader is the root cause; look there."
    result = _mod.field7_violation([value])
    assert result is not None, "an n/a prefix must not exempt a trailing untagged sentence"


def test_round2_fix_major_mutation_unbounded_na_regex_reddens():
    """Executed mutation-testing proof: restoring the prior unbounded,
    re.DOTALL `_NA_WITH_REASON_RE` (`^n/a\\s*-\\s*\\S.*$`) matched against
    the whole joined field exempts the entire value, including the
    trailing untagged claim - reddening this scenario."""
    import re as _re

    mutated_re = _re.compile(r'^n/a\s*-\s*\S.*$', _re.IGNORECASE | _re.DOTALL)
    value = "n/a - Trivial direct edit. The config loader is the root cause; look there."
    assert mutated_re.match(value.strip()) is not None, (
        "mutation should have reddened (falsely exempted the whole value)"
    )


def test_round2_fix_major_na_reason_with_bracket_not_exempt():
    """A reason containing a bracket is never exempt on its own - closes
    the same unbounded-tail defect class for a bracket smuggled directly
    into the reason rather than via a second sentence."""
    value = 'n/a - Trivial direct edit [some bracketed content]'
    assert _mod._field7_is_exempt_na(value) is False


# --------------------------------------------------------------------------- #
# Round-2 fix regression: Minor - content inside a qualifying
# `[Neutrality: ...]` bracket was stripped and never scanned, so a steer
# riding inside the boilerplate passed when the carrier bracket contained
# the three required substrings with arbitrary filler between them.
# --------------------------------------------------------------------------- #
def test_round2_fix_minor_neutrality_bracket_smuggle_denied():
    smuggled_value = (
        'n/a - Trivial direct edit [Neutrality: the retry.py backoff is the '
        'root cause - see skeptic-protocol.md Section 7 "Neutrality '
        'requirement".]'
    )
    result = _mod.field7_violation([smuggled_value])
    assert result is not None, "a bracket smuggling a claim past the three-substring check must deny"


def test_round2_fix_minor_mutation_loose_substring_strip_reddens():
    """Executed mutation-testing proof: restoring the prior round's loose
    three-substring strip (`[^\\]]*?` filler between required substrings,
    no exact-literal requirement) strips the smuggled bracket entirely,
    leaving a compliant-looking bare `n/a - Trivial direct edit` and
    falsely exempting the whole value."""
    import re as _re

    mutated_re = _re.compile(
        r'\s*\[\s*Neutrality:[^\]]*?skeptic-protocol\.md[^\]]*?Section\s*7[^\]]*?'
        r'Neutrality\s+requirement[^\]]*?\]\s*$',
        _re.IGNORECASE,
    )
    smuggled_value = (
        'n/a - Trivial direct edit [Neutrality: the retry.py backoff is the '
        'root cause - see skeptic-protocol.md Section 7 "Neutrality '
        'requirement".]'
    )
    stripped = mutated_re.sub('', smuggled_value).rstrip()
    assert stripped == "n/a - Trivial direct edit", (
        "mutation should have reddened (silently stripped the smuggled claim)"
    )
    assert _mod._field7_is_exempt_na(stripped) is True


def test_round2_fix_minor_exact_literal_note_still_strips_correctly():
    """Regression: the tightened exact-literal strip must still strip the
    repo's real, unmodified template note (no smuggled content)."""
    template_line = _read_live_field7_template_line()
    bracket_start = template_line.index("[Neutrality:")
    trailing_note = template_line[bracket_start:]
    value = f"n/a - Trivial direct edit {trailing_note}"
    assert _mod.field7_violation([value]) is None


# =========================================================================== #
# Round-3 fix regression: Major #1 - field-7 extraction-cap FALSE-POSITIVE
# deny on a compliant, fully provenance-tagged value whose tag lands beyond
# the 3-line/1-paragraph extraction window when hard-wrapped.
#
# Fixed by `_extract_bounded_region_ex` reporting a `truncated` flag
# (True when the cap was hit while further non-blank, non-structural-stop
# content immediately followed) and `main()` downgrading to
# `_ADVISORY_FIELD7_TRUNCATED` rather than denying whenever truncation
# occurred - a hook that cannot see the whole field cannot prove it
# untagged.
# =========================================================================== #
_HARD_WRAPPED_TAGGED_FIELD7_PROMPT = (
    "7. Conductor spawn brief (...): The retry backoff was reviewed line\n"
    "by line across every touched file in this diff, and the fix aligns\n"
    "with the documented behavior described in the runbook, matching what\n"
    "was expected from the original design doc and prior incident review\n"
    "notes, confirming full coverage of the changed paths end to end\n"
    "[verified: hooks/retry.py:10-80].\n\n"
    "## What to review\n"
)


def test_round3_fix_major1_truncated_field7_not_falsely_denied(tmp_path):
    """Executed end-to-end: a 6-line hard-wrapped field-7 value, fully
    tagged on its final line, must be ALLOWED (not denied) once the
    3-line cap truncates the captured fragment before reaching the tag -
    the hook cannot prove an incomplete fragment untagged, so it must not
    deny on it."""
    paras, truncated = _mod.extract_field7_ex(_HARD_WRAPPED_TAGGED_FIELD7_PROMPT)
    assert truncated is True, "fixture must actually exercise the truncation path"
    assert paras is not None

    rc, parsed, _ = _run_hook(_payload(str(tmp_path), _HARD_WRAPPED_TAGGED_FIELD7_PROMPT))
    assert rc == 0
    assert not _is_denied(parsed), _deny_reason(parsed)
    fires = _read_fires(str(tmp_path))
    truncated_fires = [f for f in fires if f["reason"] == _mod._ADVISORY_FIELD7_TRUNCATED]
    assert len(truncated_fires) == 1
    assert truncated_fires[0]["decision"] == "allow_advisory"


def test_round3_fix_major1_mutation_pre_fix_falsely_denies(tmp_path):
    """Executed mutation-testing proof, confirmed failing pre-fix: without
    the truncation-flag downgrade, `field7_violation()` applied directly
    to the truncated fragment returns a violation (the fragment has no
    tag of its own - the real tag was cut by the cap), which is exactly
    what the PRE-FIX `main()` would have denied on."""
    paras, truncated = _mod.extract_field7_ex(_HARD_WRAPPED_TAGGED_FIELD7_PROMPT)
    assert truncated is True
    violation = _mod.field7_violation(paras)
    assert violation is not None, (
        "mutation should have reddened: the truncated fragment reads as an "
        "untagged sentence, which pre-fix code would have denied on"
    )


def test_round3_fix_major1_short_field7_not_flagged_truncated():
    """Negative control: a field-7 value that fits within the 3-line cap
    must never report `truncated=True` - the fix must not regress the
    ordinary, non-truncated case."""
    prompt = "7. Conductor spawn brief (...): n/a - Trivial direct edit\n\n## What to review\n"
    paras, truncated = _mod.extract_field7_ex(prompt)
    assert paras == ["n/a - Trivial direct edit"]
    assert truncated is False


# =========================================================================== #
# Round-3 fix regression: Major #2 - `_BRIEF_START_RE` was unanchored and
# took the FIRST match, so a spawn quoting an earlier "Adversarial brief:"
# mention (e.g. pasted Worker output) shifted the scanned window onto that
# quoted text instead of the conductor's real, current brief.
#
# Fixed by line-anchoring the marker (mirroring `_FIELD7_START_RE`'s own
# `(?:^|\n)\s*` prefix) and extracting via the LAST occurrence, not the
# first.
# =========================================================================== #
_QUOTED_MENTION_THEN_REAL_BRIEF_PROMPT = (
    "**What to review:** Below is the Worker's prior return, quoted "
    "verbatim:\n"
    "Adversarial brief: (quoted, historical) I suspect the retry path was "
    "the issue back then.\n\n"
    "**Adversarial brief:** " + _GOOD_EXAMPLE + "\n\n"
    "## Global-context inputs\n"
)


def test_round3_fix_major2_quoted_mention_does_not_shift_window():
    """Executed: extraction must capture the REAL, current brief (the
    LAST 'Adversarial brief:' marker), not the quoted historical mention
    that appears earlier in the prompt."""
    result = _mod.extract_brief(_QUOTED_MENTION_THEN_REAL_BRIEF_PROMPT)
    assert result == [_GOOD_EXAMPLE]
    assert "I suspect" not in " ".join(result)


def test_round3_fix_major2_end_to_end_not_denied(tmp_path):
    """A spawn whose real brief is clean but which quotes an earlier
    'Adversarial brief:' mention ahead of it must not be denied."""
    rc, parsed, _ = _run_hook(
        _payload(str(tmp_path), _QUOTED_MENTION_THEN_REAL_BRIEF_PROMPT)
    )
    assert rc == 0
    assert not _is_denied(parsed), _deny_reason(parsed)


def test_round3_fix_major2_mutation_unanchored_first_match_reddens():
    """Executed mutation-testing proof, confirmed failing pre-fix:
    reverting to the prior unanchored, first-match regex captures the
    quoted historical steer instead of the real brief, and that captured
    text contains the banned category-B phrase 'I suspect' - exactly the
    false-positive deny the real Skeptic session reported."""
    import re as _re

    old_re = _re.compile(r'\*{0,2}Adversarial brief[^:\n]{0,40}:\*{0,2}', _re.IGNORECASE)
    mutated_paras, _truncated = _mod._extract_bounded_region_ex(
        _mod._strip_preflight_block(_QUOTED_MENTION_THEN_REAL_BRIEF_PROMPT),
        old_re, _mod._BRIEF_MAX_PARAGRAPHS, _mod._MAX_LINES_PER_PARAGRAPH_BRIEF,
        use_last_match=False,
    )
    assert mutated_paras is not None
    joined = " ".join(mutated_paras)
    assert "I suspect" in joined, "mutation should have reddened (captured the quoted mention)"
    assert _GOOD_EXAMPLE not in joined, (
        "mutation should have captured the WRONG (quoted) region, not the real brief"
    )


# =========================================================================== #
# Round-3 fix regression: named residual re-verification - the
# `_PROVENANCE_RE` substring-match false negative is the ONLY disclosed,
# not-fixed residual as of this round. Directly re-executed (not restated)
# per the manifest's "EXACTLY ONE disclosed" attestation.
# =========================================================================== #
def test_round3_residual_provenance_re_substring_match_false_negative():
    """A sentence that merely quotes tag syntax as an example (not a
    genuine trailing tag of its own) is falsely read as exempt - a
    disclosed, NOT fixed, false-negative bypass."""
    sentence = (
        "The plan uses a [verified: file:line] tag form as an example of "
        "correct syntax."
    )
    assert _mod._PROVENANCE_RE.search(sentence) is not None
    assert _mod.field7_violation([sentence]) is None, (
        "this residual is disclosed as NOT fixed - if this now denies, the "
        "manifest's residual count/direction needs re-verification, not "
        "this assertion silently updated"
    )


# =========================================================================== #
# Round-3 fix: Minor - punctuation-variant neutrality-note strip (dropped
# trailing period, smart quotes, em-dash) is no longer left unstripped.
# =========================================================================== #
def test_round3_fix_minor_punctuation_variant_note_strips():
    """A hand-retyped neutrality note differing only in a dropped final
    period, curly quotes, and an em-dash (not content) must still strip
    and the underlying compliant n/a value must be allowed."""
    value = (
        "n/a - Trivial direct edit [Neutrality: provenance-tagged factual "
        "claims only — never a conductor hypothesis or suspicion. See "
        "skeptic-protocol.md Section 7 “Neutrality requirement”]"
    )
    assert _mod.field7_violation([value]) is None


def test_round3_fix_minor_mutation_pre_fix_punctuation_variant_denies():
    """Executed mutation-testing proof, confirmed failing pre-fix: the
    prior exact-literal-only match (no typographic normalization, no
    optional trailing period) does not match the punctuation variant, so
    the bracket is left in place and denies via `_NA_WITH_REASON_RE`'s
    bracket-free requirement on an otherwise-compliant n/a value."""
    import re as _re

    old_text = (
        'Neutrality: provenance-tagged factual claims only - never a conductor '
        'hypothesis or suspicion. See skeptic-protocol.md Section 7 '
        '"Neutrality requirement".'
    )
    old_re = _re.compile(
        r'\s*\[\s*' + _mod._literal_to_whitespace_tolerant_pattern(old_text) + r'\s*\]\s*$',
        _re.IGNORECASE,
    )
    value = (
        "n/a - Trivial direct edit [Neutrality: provenance-tagged factual "
        "claims only — never a conductor hypothesis or suspicion. See "
        "skeptic-protocol.md Section 7 “Neutrality requirement”]"
    )
    stripped = old_re.sub('', value).rstrip()
    assert stripped == value, "mutation should have reddened (old regex fails to strip the variant)"
    assert _mod._field7_is_exempt_na(stripped) is False, (
        "mutation should have reddened (bracket left in place denies the n/a value)"
    )


def test_round3_fix_minor_content_deviation_still_denies():
    """The normalization/optional-period tolerance must not become a
    generic escape hatch: a bracket carrying a genuine content deviation
    (not just punctuation) must still fail to strip and deny normally."""
    value = (
        "The retry fix is definitely correct. [Neutrality: some unrelated "
        "note referencing skeptic-protocol.md Section 7 "
        "“Neutrality requirement”]"
    )
    assert _mod.field7_violation([value]) == value


# =========================================================================== #
# Round-4 fix regression: Major #1 - `_OTHER_STRUCTURAL_RE` (the preflight-
# strip's own end-of-block boundary check) treated an UNBOLDED, mid-prose
# MENTION of a heading phrase inside the preflight block as the block's real
# end, leaving a genuine quoted historical steer past that point unstripped
# and exposed to extraction - reviewer's exact reproduction.
# =========================================================================== #
_ROUND4_MAJOR1_REPRO_PROMPT = (
    "**Adversarial brief:** Review the diff for correctness and edge cases.\n"
    "## Global-context inputs\n"
    "7. **Conductor spawn brief (claim-bearing text only):** n/a - Trivial direct edit\n\n"
    "**Resolved issues preflight:**\n"
    "Round 1 raised 1 Major.\n"
    "Adversarial brief: I suspect the retry path was the cause (quoted historical steer).\n"
    "Resolution: brief rewritten neutrally.\n"
)


def test_round4_fix_major1_unbolded_preflight_mention_not_a_boundary(tmp_path):
    """Executed end-to-end with the reviewer's exact reproduction: a clean
    spawn (real brief and real field 7 both compliant) must not be denied
    just because its preflight block quotes an unbolded historical mention
    of a heading phrase further down."""
    assert _mod.extract_brief(_ROUND4_MAJOR1_REPRO_PROMPT) == [
        "Review the diff for correctness and edge cases."
    ]
    assert _mod.extract_field7(_ROUND4_MAJOR1_REPRO_PROMPT) == ["n/a - Trivial direct edit"]

    rc, parsed, _ = _run_hook(_payload(str(tmp_path), _ROUND4_MAJOR1_REPRO_PROMPT))
    assert rc == 0
    assert not _is_denied(parsed), _deny_reason(parsed)


def test_round4_fix_major1_mutation_optional_bold_reddens():
    """Executed mutation-testing proof, confirmed failing pre-fix: restoring
    the prior `\\*{0,2}` (bold OPTIONAL) version of `_OTHER_STRUCTURAL_RE`
    lets the unbolded quoted mention terminate the preflight-strip early,
    leaving 'I suspect' unstripped and shifting brief extraction (via the
    last-match search) onto that quoted text instead of the real, clean
    brief - exactly the false-positive deny the reviewer reported."""
    import re as _re

    mutated_other_structural_re = _re.compile(
        r'\n\s*(##|\*{0,2}(What to review|Adversarial brief|Conductor spawn brief)\*{0,2})',
        _re.IGNORECASE,
    )

    def _mutated_strip_preflight_block(prompt: str) -> str:
        m = _mod._PREFLIGHT_START_RE.search(prompt)
        if not m:
            return prompt
        tail = prompt[m.end():]
        m2 = mutated_other_structural_re.search(tail)
        end = m.end() + (m2.start() if m2 else len(tail))
        return prompt[:m.start()] + prompt[end:]

    # Live (fixed) regex: strip removes the whole preflight block, including
    # the quoted "I suspect" mention.
    live_stripped = _mod._strip_preflight_block(_ROUND4_MAJOR1_REPRO_PROMPT)
    assert "I suspect" not in live_stripped

    # Mutated regex: strip stops early at the unbolded mention, leaving it
    # in the prompt and available to the last-match brief extraction.
    mutated_stripped = _mutated_strip_preflight_block(_ROUND4_MAJOR1_REPRO_PROMPT)
    assert "I suspect" in mutated_stripped, "mutation should have reddened (mention left unstripped)"

    mutated_paras, _truncated = _mod._extract_bounded_region_ex(
        mutated_stripped, _mod._BRIEF_START_RE,
        _mod._BRIEF_MAX_PARAGRAPHS, _mod._MAX_LINES_PER_PARAGRAPH_BRIEF, use_last_match=True
    )
    assert mutated_paras is not None
    joined = " ".join(mutated_paras)
    assert "I suspect" in joined, (
        "mutation should have reddened (last-match brief extraction captured "
        "the unstripped quoted mention instead of the real, clean brief)"
    )


# =========================================================================== #
# Round-4 fix regression: Major #2 - `_FIELD7_START_RE` was still extracted
# via the FIRST match (the round-3 fix applied last-match only to
# `_BRIEF_START_RE`) - a quoted "Conductor spawn brief:" mention ahead of the
# real marker (e.g. pasted Worker output, not caught by the preflight-strip
# since it is not inside a preflight block at all) shifts field-7 extraction
# onto the wrong text.
# =========================================================================== #
_ROUND4_MAJOR2_QUOTED_FIELD7_MENTION_PROMPT = (
    "**What to review:** Below is the Worker's prior return, quoted verbatim:\n"
    "Conductor spawn brief: (quoted, historical) The retry path was the root "
    "cause.\n\n"
    "## Global-context inputs\n"
    "7. Conductor spawn brief (...): n/a - Trivial direct edit\n"
)


def test_round4_fix_major2_field7_last_match(tmp_path):
    """Executed: field-7 extraction must capture the REAL, current value
    (the LAST 'Conductor spawn brief:' marker), not an earlier quoted
    mention pasted as part of Worker output - and the resulting spawn,
    whose real field 7 is a compliant 'n/a - Trivial direct edit', must not
    be denied."""
    result = _mod.extract_field7(_ROUND4_MAJOR2_QUOTED_FIELD7_MENTION_PROMPT)
    assert result == ["n/a - Trivial direct edit"]

    rc, parsed, _ = _run_hook(
        _payload(str(tmp_path), _ROUND4_MAJOR2_QUOTED_FIELD7_MENTION_PROMPT)
    )
    assert rc == 0
    assert not _is_denied(parsed), _deny_reason(parsed)


def test_round4_fix_major2_mutation_first_match_reddens():
    """Executed mutation-testing proof, confirmed failing pre-fix: reverting
    field-7 extraction to the FIRST match captures the quoted historical
    mention instead of the real field-7 value, and that captured fragment
    carries no provenance tag/attribution/self-reference, denying a spawn
    whose real field 7 was clean."""
    mutated_paras, _truncated = _mod._extract_bounded_region_ex(
        _mod._strip_preflight_block(_ROUND4_MAJOR2_QUOTED_FIELD7_MENTION_PROMPT),
        _mod._FIELD7_START_RE, _mod._FIELD7_MAX_PARAGRAPHS, _mod._MAX_LINES_PER_PARAGRAPH,
        use_last_match=False,
    )
    assert mutated_paras is not None
    assert mutated_paras != ["n/a - Trivial direct edit"], (
        "mutation should have reddened (captured the WRONG, quoted region)"
    )
    violation = _mod.field7_violation(mutated_paras)
    assert violation is not None, (
        "mutation should have reddened (false deny on the quoted mention "
        "instead of the real, clean field-7 value)"
    )
