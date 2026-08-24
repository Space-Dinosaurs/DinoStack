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
# Scenario 3: ALLOW - field-7 exempt bare "n/a"
# --------------------------------------------------------------------------- #
def test_scenario_03_allow_field7_bare_na(tmp_path):
    prompt = "7. Conductor spawn brief (...): n/a\n\n## What to review\n"
    rc, parsed, _ = _run_hook(_payload(str(tmp_path), prompt))
    assert rc == 0
    assert not _is_denied(parsed)
    assert _mod.field7_violation(["n/a"]) is None


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
