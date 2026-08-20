#!/usr/bin/env python3
"""
Purpose: Regression guard for the `dinostack` output style's rule-set drift.
         The `dinostack` Claude Code output style
         (`content/output-styles/dinostack.md`) carries five turn-shape
         rule topics - status-only, volume, answer relevance,
         self-narrating candor, editorial addenda - and that set is
         RESTATED, by name, at ten other sites with no mechanical check
         tying them together (see `Upstream deps` below). A stale
         cross-file assertion nothing pins is the defect class this spec
         exists to close.

         The derived source of truth is the style file itself: its YAML
         frontmatter `description:` field states the rule set as a
         parenthesized, comma-separated list, and its body states those
         topics under numbered rule headers (`**1. ...**` through
         `**N. ...**`). There is deliberately no 1:1 equality between
         header count and topic count - that equality encoded an
         enumerated one-rule-per-topic structure DS-PILLAR1 deleted, since
         one governing warrant rule now names four topics as instances
         beside a single surviving volume rule. Both drift directions are
         instead covered per-topic and per-rule: every declared topic must
         be named in the body
         (`test_body_covers_every_frontmatter_topic`) and every numbered
         rule must itself name a declared topic
         (`test_every_numbered_rule_maps_to_a_declared_topic`; a count
         bound cannot do this - it leaves undetected growth wherever slack
         remains). At each of the ten sites, every current topic is
         asserted present AND no retired topic is asserted stale-present
         (`_assert_no_stale_topics`), modulo hyphen/space normalization.

         A second, orthogonal axis pins the ban's DESCRIPTION, not just
         its NAME: name-only checks let six sites keep a pre-widening,
         package-scoped definition of the editorial-addenda ban while
         staying green. See
         `test_no_site_scopes_editorial_addenda_to_a_labelled_package`
         (conditional - fires only where a site describes the ban in
         package or positional terms; its residual gaps are enumerated
         above `_NARROW_SCOPE_RE`) and
         `test_widening_is_stated_at_both_normative_sources` (pins the
         rule at its two origins so a re-narrowing there cannot propagate
         outward as a newly-consistent narrow definition).

Upstream deps: content/output-styles/dinostack.md (derived source of truth);
               docs/index.html; README.md; docs/configuration-reference.md;
               docs/safe-configuration.md; hooks/enforce-turn-shape.py;
               content/references/conductor-turn-format.md;
               content/references/risk-config-and-tiers.md;
               content/references/conventions-detail.md;
               content/commands/ds-init-project.md; docs/components.md.

Canonical-plus-pointer (operator decision 2026-08-20): PUBLIC-doc sites
(docs/index.html, README.md, docs/configuration-reference.md,
docs/safe-configuration.md, docs/components.md) still restate the full
rule-set text verbatim - the doc-sync obligation mandates restatement
there, and this spec continues to pin it exactly as before. Two CONTENT
sites (`content/references/conventions-detail.md`,
`content/commands/ds-init-project.md`) were confirmed verbatim duplicates
of the canonical CONTENT site (`content/references/risk-config-and-tiers.md`
- already the "Full semantics:" target every sibling toggle bullet in
those two files points at) and were deduped to a short summary plus a
`content/references/risk-config-and-tiers.md` pointer, per PR #780's
established toggle-dedup pattern. Their tests now accept EITHER the full
topic-bearing text OR the canonical pointer string
(`test_canonical_or_pointer`, used by
`test_conventions_detail_names_full_rule_set_or_pointer` and
`test_ds_init_project_names_full_rule_set_or_pointer`) - the canonical site
itself (`test_risk_config_and_tiers_names_full_rule_set`) is UNCHANGED and
still requires the full text, so deleting it there still fails loudly.
`hooks/enforce-turn-shape.py` and `content/references/conductor-turn-format.md`
were NOT deduped (out of scope for this pass) and keep their original
full-text-only assertions.

Downstream consumers: CI (bin-tests / pytest bin/tests/); a human reviewer
                       of any PR that renames, adds, or removes a
                       turn-shape rule from the `dinostack` output style.

Failure modes: a site missing a current topic, or still naming a topic the
               style no longer defines, fails loudly with the specific
               topic(s) and file named - it never silently passes. A
               genuinely new rule topic requires adding it to
               `ALL_KNOWN_RULE_TOPICS` in the same PR, or this guard cannot
               detect its later removal either.

Run with: python3 -m pytest bin/tests/test_output_style_rule_set_sync.py -q
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STYLE_PATH = REPO_ROOT / "content" / "output-styles" / "dinostack.md"
INDEX_PATH = REPO_ROOT / "docs" / "index.html"
README_PATH = REPO_ROOT / "README.md"
HOOK_PATH = REPO_ROOT / "hooks" / "enforce-turn-shape.py"
CTF_PATH = REPO_ROOT / "content" / "references" / "conductor-turn-format.md"
CONFIG_REF_PATH = REPO_ROOT / "docs" / "configuration-reference.md"
SAFE_CONFIG_PATH = REPO_ROOT / "docs" / "safe-configuration.md"
RISK_CONFIG_PATH = REPO_ROOT / "content" / "references" / "risk-config-and-tiers.md"
CONVENTIONS_DETAIL_PATH = REPO_ROOT / "content" / "references" / "conventions-detail.md"
DS_INIT_PROJECT_PATH = REPO_ROOT / "content" / "commands" / "ds-init-project.md"
COMPONENTS_PATH = REPO_ROOT / "docs" / "components.md"

# The closed universe of topics this rule set has ever named (DS-171: status-
# only, volume, answer relevance, self-narrating candor, editorial addenda).
# Used only to detect a STALE site that still names a topic the style no
# longer defines - a one-sided "does the site contain every current topic"
# check cannot catch that direction. Deliberately closed, not derived: it is
# the fixed vocabulary a rule can ever be renamed out of, so a genuinely NEW
# topic name requires adding it here in the same PR. Keep the prose above in
# step with the literal below; an enumeration shorter than the list is a
# stale count-sync site of exactly the kind this file exists to catch.
ALL_KNOWN_RULE_TOPICS = [
    "status-only",
    "volume",
    "answer relevance",
    "self-narrating candor",
    "editorial addenda",
]

def _hook_module_docstring() -> str:
    """The hook file's own module docstring via `ast.get_docstring` - the
    true source boundary. An approximated line budget was tried first and
    covered only the opening third of the real docstring, cutting off
    genuine topic prose further down: a false-negative-shaped gap."""
    tree = ast.parse(HOOK_PATH.read_text(encoding="utf-8"))
    doc = ast.get_docstring(tree)
    assert doc, f"{HOOK_PATH} must have a module docstring"
    return doc


# DS-171 round 7 Skeptic Major 1 fixed the guard's false-pass-via-identifier
# bug (see `_normalize`/`_topic_pattern` below), but `hooks/enforce-turn-
# shape.py` is explicitly frozen this round (untouched since round 4) and
# its module docstring - verified by a direct search of the WHOLE file, not
# just the docstring - never states the literal two-word phrase "answer
# relevance" as prose anywhere: only via the retired `_answer_relevance_
# flag` identifier and the paraphrase "the relevance rule". This is a
# genuine, narrow, explicitly tracked gap (see this change's "Accepted
# debt" PR note), not a reopening of the identifier vacuity - every OTHER
# topic at this site, and every topic at every OTHER site, is still
# checked at full strictness via `_assert_topics_present`.
HOOK_KNOWN_GAP_TOPICS = ["answer relevance"]


def _normalize(text: str) -> str:
    """Lowercase, and fold hyphens (only) to spaces so "status-only" and
    "status only" compare equal. Underscores are deliberately NOT folded
    (DS-171 round 7 Skeptic Major 1): folding `_` to a space used to let a
    retired function identifier - `_status_only_flag`, `_volume_flag`,
    `_answer_relevance_flag` - normalize into a literal "status only" /
    "volume" / "answer relevance" run of words on the identifier's name
    alone, satisfying a topic-presence check even at a site whose prose
    never states the topic. Leaving underscores intact means an
    identifier like `_status_only_flag` stays one unbroken token with no
    internal spaces, so it can no longer masquerade as the multi-word
    phrase. See `_topic_pattern` for the remaining single-word case
    (`_volume_flag` still literally CONTAINS "volume" as a substring)."""
    text = text.lower()
    text = re.sub(r"-", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _topic_pattern(topic: str) -> re.Pattern[str]:
    """Word-boundary regex for a normalized topic phrase (DS-171 round 7
    Skeptic Major 1). A plain substring `in` check still lets a
    single-word topic like "volume" match inside a retired identifier
    such as `_volume_flag` even after `_normalize` stops folding
    underscores, since "volume" is literally a substring of that token.
    `\\b` closes this: `_` is a regex word character, so there is no word
    boundary between the leading "_" and "v" in `_volume_flag` - the
    pattern cannot match there, while it matches normally in genuine
    prose like "the turn-charge volume check", where "volume" is
    surrounded by spaces."""
    words = [re.escape(w) for w in _normalize(topic).split(" ") if w]
    return re.compile(r"\b" + r"\s+".join(words) + r"\b")


@pytest.fixture(scope="module")
def style_text() -> str:
    return STYLE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rule_set_topics(style_text) -> list[str]:
    """Derived from the style's own YAML frontmatter description, e.g.
    'DinoStack conductor turn-shape discipline (status-only, volume,
    answer relevance, self-narrating candor)' -> the 4 parenthesized
    topics. Never hardcoded - this is the thing every other site must
    agree with."""
    match = re.search(r"^description:.*\(([^)]*)\)", style_text, re.MULTILINE)
    assert match, (
        f"{STYLE_PATH} frontmatter 'description:' must state the rule set "
        "as a parenthesized, comma-separated list"
    )
    topics = [t.strip() for t in match.group(1).split(",")]
    assert all(topics), f"{STYLE_PATH} frontmatter rule-set list has an empty entry: {topics}"
    return topics


@pytest.fixture(scope="module")
def style_body(style_text) -> str:
    """The style's BODY, with the YAML frontmatter stripped.

    This exists because of a vacuity bug caught by mutation-testing the
    first draft of `test_body_covers_every_frontmatter_topic`: that check
    originally scanned the whole file, which CONTAINS the `description:`
    line the topics are derived from. Every topic therefore matched
    itself, and deleting a topic from the body entirely left the test
    green. Operands must not share a source - see the repo's
    "same-source operands are unfalsifiable" lesson. Splitting on the
    closing `---` fence is asserted, not assumed, so a frontmatter shape
    change fails loudly instead of silently restoring the vacuity."""
    match = re.match(r"^---\n.*?\n---\n(.*)$", style_text, re.DOTALL)
    assert match, (
        f"{STYLE_PATH} must open with a YAML frontmatter block delimited by "
        "'---' lines - this spec strips it so the body cannot satisfy a "
        "topic-coverage check using the frontmatter's own description line"
    )
    body = match.group(1)
    assert "description:" not in body, (
        f"{STYLE_PATH}: frontmatter strip left a 'description:' line in the "
        "body - the topic-coverage check would compare the description "
        "against itself and pass vacuously"
    )
    return body


_RULE_HEADER_RE = re.compile(r"^\*\*(\d+)\.\s", re.MULTILINE)


@pytest.fixture(scope="module")
def rule_blocks(style_body) -> list[tuple[str, str]]:
    """Each numbered rule as `(number, block_text)`, where the block runs
    from its own `**N.**` header to the next header (or end of body).

    Derived from `style_body`, never `style_text`, for the same
    same-source-operands reason - see that fixture's docstring."""
    starts = [m.start() for m in _RULE_HEADER_RE.finditer(style_body)]
    numbers = [m.group(1) for m in _RULE_HEADER_RE.finditer(style_body)]
    bounds = starts + [len(style_body)]
    return [(numbers[i], style_body[bounds[i]:bounds[i + 1]]) for i in range(len(starts))]


def test_body_covers_every_frontmatter_topic(rule_set_topics, style_body):
    """Drift direction 1: a declared topic dropped from the body. See the
    module manifest for why this replaced a header/topic count equality."""
    normalized_body = _normalize(style_body)
    missing = [t for t in rule_set_topics if not _topic_pattern(t).search(normalized_body)]
    assert not missing, (
        f"{STYLE_PATH} frontmatter declares topic(s) {missing} that the body "
        "never names. Either the body dropped a rule the description still "
        "advertises (and the ten restatement sites are now stale), or the "
        "description names a topic that was never written - fix whichever "
        "it is; do not delete the topic from the description without also "
        "updating the ten sites this spec checks."
    )


def test_every_numbered_rule_maps_to_a_declared_topic(rule_set_topics, rule_blocks):
    """Drift direction 2: a numbered rule added to the body with no
    declared topic, which would never reach the ten restatement sites.
    Headers may still be FEWER than topics (one governing rule may name
    several); only the converse is closed. See the module manifest.

    KNOWN EVASIONS - this maps a rule to a topic by mere mention, so a
    block that names a topic incidentally maps to it regardless of the
    rule's actual subject. Constructed cases that pass:
      1. Incidental mention - "not to be confused with the volume rule
         above", "not an instance of answer relevance".
      2. Mention inside a fenced code block - not stripped before matching.
      3. Negated mention - a rule whose subject is swapped while it
         retains "This is not a volume rule".
    A rule split across two headers where only the first names a topic
    IS caught. These are accepted limits, not oversights: the tripwire
    targets an invented rule stated in good faith, and the count bound it
    replaced passed all three cases too."""
    assert rule_blocks, (
        f"{STYLE_PATH} body has no numbered `**N.**` rule headers at all - "
        "refusing to certify a style with no stated rules as compliant"
    )
    unmapped = []
    for number, block in rule_blocks:
        normalized = _normalize(block)
        if not any(_topic_pattern(t).search(normalized) for t in rule_set_topics):
            header = block.splitlines()[0].strip()
            unmapped.append(f"**{number}.** ({header[:80]})")
    assert not unmapped, (
        f"{STYLE_PATH} body has numbered rule(s) {unmapped} whose text names "
        f"none of the frontmatter's declared topics {rule_set_topics}. A rule "
        "the description does not name cannot be synced to the ten "
        "restatement sites, so it grows the rule set invisibly - the exact "
        "re-enumeration DS-PILLAR1 removed. Either state the rule as an "
        "instance of a topic already declared, or add its topic to the "
        "description (and to ALL_KNOWN_RULE_TOPICS) in the same change."
    )


def test_rule_set_is_plausible(rule_set_topics):
    # Sanity floor: catches an accidentally-emptied description field.
    assert len(rule_set_topics) >= 2, (
        f"{STYLE_PATH} frontmatter rule-set list is implausibly short: {rule_set_topics}"
    )


def _assert_topics_present(site_path: Path, site_text: str, topics: list[str]) -> None:
    normalized_site = _normalize(site_text)
    missing = [t for t in topics if not _topic_pattern(t).search(normalized_site)]
    assert not missing, (
        f"{site_path} is missing rule-set topic(s) {missing} from "
        f"{STYLE_PATH}'s frontmatter rule set {topics} - update it to match "
        "or correct the drift"
    )


def _assert_no_stale_topics(site_path: Path, site_text: str, topics: list[str]) -> None:
    """Guards the OTHER direction from `_assert_topics_present` (DS-171
    round 4, Skeptic Minor 1): a topic removed from the style's own rule
    set, but left behind in a site's prose, is invisible to a
    contains-every-current-topic check alone - that check only ever grows
    stricter as topics are ADDED, never catches one being silently dropped
    everywhere except the style. This walks the closed `ALL_KNOWN_RULE_TOPICS`
    vocabulary and asserts the site names exactly the topics the style
    currently defines, no more."""
    normalized_site = _normalize(site_text)
    stale = [
        t
        for t in ALL_KNOWN_RULE_TOPICS
        if _topic_pattern(t).search(normalized_site) and t not in topics
    ]
    assert not stale, (
        f"{site_path} still names rule-set topic(s) {stale} that "
        f"{STYLE_PATH}'s frontmatter no longer defines ({topics}) - the "
        "style dropped a topic and this site was not updated to match"
    )


# Canonical-plus-pointer target for the two deduped CONTENT sites. Path
# string only (not a heading anchor) - the pointer sentence at both sites
# reads "Full semantics: `content/references/risk-config-and-tiers.md`
# §Project config."
CANONICAL_CONTENT_POINTER = "content/references/risk-config-and-tiers.md"


def _assert_full_text_or_canonical_pointer(
    site_path: Path, site_text: str, topics: list[str]
) -> None:
    """A deduped CONTENT site must carry EITHER the full topic-bearing text
    (in which case it is also held to the no-stale-topics invariant, same as
    a canonical site) OR an explicit pointer to the canonical CONTENT site.
    Neither present means the site was gutted without leaving a trail to the
    real definition - fails loudly rather than silently passing on an absent
    paragraph."""
    normalized_site = _normalize(site_text)
    missing = [t for t in topics if not _topic_pattern(t).search(normalized_site)]
    if not missing:
        _assert_no_stale_topics(site_path, site_text, topics)
        return
    assert CANONICAL_CONTENT_POINTER in site_text, (
        f"{site_path} carries neither the full rule-set text (missing topic(s) "
        f"{missing}) nor a pointer to the canonical site ({CANONICAL_CONTENT_POINTER!r}) "
        "- a deduped site must always resolve to one or the other"
    )


def test_index_html_names_full_rule_set(rule_set_topics):
    text = INDEX_PATH.read_text(encoding="utf-8")
    marker = "Claude Code turn-shape output style"
    assert marker in text, (
        f"{INDEX_PATH} must contain the '{marker}' card describing the "
        "dinostack output style"
    )
    card_text = text[text.index(marker):]
    # Scope to this one card, not the whole rest of the file - without an
    # end delimiter this passes vacuously the moment any topic word
    # recurs anywhere later in index.html (DS-171 round 5, Skeptic Minor 4).
    next_card = card_text.find("</div>", 1)
    if next_card != -1:
        card_text = card_text[: next_card + len("</div>")]
    _assert_topics_present(INDEX_PATH, card_text, rule_set_topics)
    _assert_no_stale_topics(INDEX_PATH, card_text, rule_set_topics)


def test_readme_names_full_rule_set(rule_set_topics):
    text = README_PATH.read_text(encoding="utf-8")
    marker = "turn_shape_guard_enabled"
    assert marker in text, (
        f"{README_PATH} must contain the '{marker}' config entry describing "
        "what moved to the dinostack output style"
    )
    entry_text = text[text.index(marker):]
    # Scope to this one bullet, not the whole rest of the file.
    next_bullet = entry_text.find("\n- `", 1)
    if next_bullet != -1:
        entry_text = entry_text[:next_bullet]
    _assert_topics_present(README_PATH, entry_text, rule_set_topics)
    _assert_no_stale_topics(README_PATH, entry_text, rule_set_topics)


def test_hook_docstring_names_full_rule_set(rule_set_topics):
    docstring_text = _hook_module_docstring()
    checked_topics = [t for t in rule_set_topics if t not in HOOK_KNOWN_GAP_TOPICS]
    _assert_topics_present(HOOK_PATH, docstring_text, checked_topics)
    _assert_no_stale_topics(HOOK_PATH, docstring_text, rule_set_topics)


def test_configuration_reference_names_full_rule_set(rule_set_topics):
    text = CONFIG_REF_PATH.read_text(encoding="utf-8")
    marker = "turn_shape_guard_enabled"
    assert marker in text, (
        f"{CONFIG_REF_PATH} must contain the '{marker}' config entry "
        "describing what moved to the dinostack output style"
    )
    entry_text = text[text.index(marker):]
    # Scope to this one table row, not the whole rest of the file.
    next_row = entry_text.find("\n|", 1)
    if next_row != -1:
        entry_text = entry_text[:next_row]
    _assert_topics_present(CONFIG_REF_PATH, entry_text, rule_set_topics)
    _assert_no_stale_topics(CONFIG_REF_PATH, entry_text, rule_set_topics)


def test_safe_configuration_names_full_rule_set(rule_set_topics):
    text = SAFE_CONFIG_PATH.read_text(encoding="utf-8")
    marker = "[`enforce-turn-shape.py`]"
    assert marker in text, (
        f"{SAFE_CONFIG_PATH} must contain the '{marker}' hook entry "
        "describing what moved to the dinostack output style"
    )
    entry_text = text[text.index(marker):]
    # Scope to this one list item, not the whole rest of the file.
    next_item = entry_text.find("\n- [", 1)
    if next_item != -1:
        entry_text = entry_text[:next_item]
    _assert_topics_present(SAFE_CONFIG_PATH, entry_text, rule_set_topics)
    _assert_no_stale_topics(SAFE_CONFIG_PATH, entry_text, rule_set_topics)


def test_conductor_turn_format_names_full_rule_set(rule_set_topics):
    text = CTF_PATH.read_text(encoding="utf-8")
    # Marker was "DS-171: bans 2 and 5". DS-PILLAR1 collapsed the numbered
    # ban list into one governing warrant rule plus named instances, so a
    # marker keyed to ban NUMBERS no longer resolves. This one is keyed to
    # the note's subject instead, which is stable across renumbering - the
    # defect the numbered marker kept re-encoding.
    marker = "Mechanization status (DS-171)"
    assert marker in text, (
        f"{CTF_PATH} must contain the DS-171 note describing what moved to "
        "the dinostack output style"
    )
    note_text = text[text.index(marker):]
    # Scope to this one paragraph (it already covers the self-narrating-
    # candor addendum inline, not a separate following paragraph -
    # `note_text.find("\n\n", 1)` stops at the end of THIS paragraph, it
    # does not additionally include a second one), not the whole rest of
    # the file.
    next_para = note_text.find("\n\n", 1)
    if next_para != -1:
        note_text = note_text[:next_para]
    _assert_topics_present(CTF_PATH, note_text, rule_set_topics)
    _assert_no_stale_topics(CTF_PATH, note_text, rule_set_topics)


def test_risk_config_and_tiers_names_full_rule_set(rule_set_topics):
    text = RISK_CONFIG_PATH.read_text(encoding="utf-8")
    marker = "`turn_shape_guard_enabled`"
    assert marker in text, (
        f"{RISK_CONFIG_PATH} must contain the '{marker}' config entry "
        "describing what moved to the dinostack output style"
    )
    entry_text = text[text.index(marker):]
    # Scope to this one bullet, not the whole rest of the file.
    next_bullet = entry_text.find("\n- `", 1)
    if next_bullet != -1:
        entry_text = entry_text[:next_bullet]
    _assert_topics_present(RISK_CONFIG_PATH, entry_text, rule_set_topics)
    _assert_no_stale_topics(RISK_CONFIG_PATH, entry_text, rule_set_topics)


def test_conventions_detail_names_full_rule_set_or_pointer(rule_set_topics):
    text = CONVENTIONS_DETAIL_PATH.read_text(encoding="utf-8")
    marker = "`turn_shape_guard_enabled`"
    assert marker in text, (
        f"{CONVENTIONS_DETAIL_PATH} must contain the '{marker}' config entry "
        "describing what moved to the dinostack output style"
    )
    entry_text = text[text.index(marker):]
    # Scope to this one bullet, not the whole rest of the file.
    next_bullet = entry_text.find("\n- `", 1)
    if next_bullet != -1:
        entry_text = entry_text[:next_bullet]
    _assert_full_text_or_canonical_pointer(CONVENTIONS_DETAIL_PATH, entry_text, rule_set_topics)


def test_ds_init_project_names_full_rule_set_or_pointer(rule_set_topics):
    text = DS_INIT_PROJECT_PATH.read_text(encoding="utf-8")
    marker = "`turn_shape_guard_enabled`"
    assert marker in text, (
        f"{DS_INIT_PROJECT_PATH} must contain the '{marker}' config entry "
        "describing what moved to the dinostack output style"
    )
    entry_text = text[text.index(marker):]
    # Scope to this one bullet, not the whole rest of the file.
    next_bullet = entry_text.find("\n- `", 1)
    if next_bullet != -1:
        entry_text = entry_text[:next_bullet]
    _assert_full_text_or_canonical_pointer(DS_INIT_PROJECT_PATH, entry_text, rule_set_topics)


# --- Description invariant ------------------------------------------------
# The topic-NAME checks above assert each site NAMES `editorial addenda`,
# never that the site's DESCRIPTION of that ban matches the rule - the
# "prose-invariant tests pin promise not mechanism" shape. This invariant is
# deliberately CONDITIONAL rather than a wording pin: it fires only where a
# site describes the ban narrowly at all, and then requires the widening in
# the same paragraph. A site that never does (docs/index.html today) stays
# out of scope - the check targets the defect shape, not a house style.
#
# The trigger covers two axes, because a single literal (`labell?ed\s+
# package`) is defeated by any synonym:
#
#   * PACKAGE shape - a narrowing modifier (labelled, bundled, grouped,
#     packaged, ...) in front of a container noun (package, bundle, group,
#     cluster, batch, set, section, block), allowing up to two intervening
#     words so "trailing bundled group" and "labelled trailing section" match.
#   * POSITIONAL scoping - trailing / closing / opening / appended /
#     "at the end of", which the **Editorial addenda.** rule names as
#     explicitly NOT part of the shape.
#
# `_BAN_SUBJECT_RE` gates both. Without it, a widened vocabulary would fire on
# any paragraph anywhere in these eleven files that happens to say "closing
# section" about something else entirely; with it, the check stays aimed at
# paragraphs that are actually describing this ban, which is what lets the
# narrowing vocabulary be broad.
#
# RESIDUAL GAP - what this does NOT catch, stated rather than papered over:
# a regex cannot close a natural-language evasion, and pretending otherwise
# would be worse than a named limit. Specifically:
#   1. A re-narrowing that uses none of the container nouns or positional
#      tokens above ("the ban on a run-on paragraph of observations", "the ban
#      on an attention roundup") passes silently.
#   2. A re-narrowing whose paragraph names none of the subject markers in
#      `_BAN_SUBJECT_RE` - e.g. a gloss written purely as "the ban on
#      'Two things stand out'-style trailers" - is out of scope by gate.
#   3. A narrow gloss that also happens to contain a `_WIDENING_RE` phrase
#      about some OTHER clause in the same paragraph satisfies the check
#      without the widening applying to the gloss; the paragraph scope makes
#      this less likely than a char window would, not impossible.
#   4. Semantic re-narrowing with no lexical marker at all ("the ban applies
#      when the conductor groups them together") is entirely invisible.
# The invariant is a tripwire for the realistic near-miss, not a proof. The
# normative statement of the ban is the **Editorial addenda.** rule in
# `content/references/conductor-turn-format.md`, and human review of any edit
# to a gloss remains load-bearing.
_NARROWING_MODIFIERS = (
    r"labell?ed|bundled|grouped|packaged|batched|clustered|"
    r"trailing|closing|opening|appended|final|concluding"
)
# Nouns the ban's own vocabulary uses for the thing being banned. Deliberately
# excludes generic nouns a neighbouring clause might carry ("recap",
# "statement", "rule"): "Ban 5 (closing recap)" and ban 8's "A closing
# statement naming follow-on work" both sit in paragraphs that name this ban,
# and neither is a gloss OF it - a modifier alone is not evidence.
_BAN_NOUNS = (
    r"package|bundle|group|cluster|batch|set|section|block|roundup|"
    r"item|items|observation|observations|addendum|addenda|trailer|trailers"
)
# A positional scoping claim stated without a container noun. Anchored on the
# turn itself so it cannot match an unrelated "at the end of the file".
_POSITIONAL_PHRASE = (
    r"(?:at\s+the\s+(?:end|close|start)\s+of|(?:at\s+the\s+)?(?:very\s+)?"
    r"(?:end|close|start)\s+of)\s+(?:the\s+|a\s+|any\s+)?turn"
)

_NARROW_SCOPE_RE = re.compile(
    r"(?:\b(?:" + _NARROWING_MODIFIERS + r")\b(?:\s+\S+){0,2}?\s+\b(?:" + _BAN_NOUNS + r")\b)"
    r"|(?:" + _POSITIONAL_PHRASE + r")",
    re.IGNORECASE,
)

# Gate for the widened vocabulary above: the paragraph must actually be
# talking about the editorial-addenda ban before a narrowing token in it
# means anything.
_BAN_SUBJECT_RE = re.compile(
    r"editorial\s+addend(?:um|a)|conductor[- ]selected|"
    r"worth\s+your\s+attention|ban\s+7",
    re.IGNORECASE,
)

# Any of these phrasings is sufficient evidence the definition is NOT
# narrowly scoped. All are in live use: the config-entry sites say "whether
# or not it is bundled ... the canonical form, not the boundary"; the
# **Editorial addenda.** rule and the style's editorial-addenda instance both
# say "not its boundary". The POSITIONAL widenings are listed because the
# trigger covers the positional axis too, and a site may legitimately state
# the widening on that axis alone - "Position is not part of the shape" and
# "in any position in the turn" are correct text a package-only widening list
# would have flagged as offenders.
_WIDENING_RE = re.compile(
    r"whether or not it is bundled|not the boundary|not its boundary|"
    r"position is not part of the shape|position[- ]independent|"
    r"in any position",
    re.IGNORECASE,
)

# Scope is the PARAGRAPH, not a character window. A definition and the
# qualifier that bounds it live in the same block of prose at every live
# site; a fixed char window instead splits the **Editorial addenda.** rule
# (whose widening sits at the top of a very long paragraph while a legitimate
# non-definitional mention - "belongs in the sentence where it is relevant,
# not in a labelled package" - sits at the bottom) and produces a false
# positive on correct text.
# Whitespace inside a block is normalized first, because a hard-wrapped
# docstring breaks "whether or not it is bundled" across a newline plus
# indent.
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")

# Every file this spec already treats as a restatement site, plus the style
# itself. `docs/index.html` is included deliberately even though it carries
# no match today - if a future edit adds a package-scoped gloss there, this
# check must see it.
#
# THIS FILE IS DELIBERATELY EXCLUDED. It is not a restatement SITE; it is the
# guard, and it necessarily QUOTES the narrow forms it catches. Adding this
# path would make the invariant fire on its own documentation, and the only
# ways out would be to stop quoting the defect or to sprinkle widening
# phrases into comments describing narrow historical text (making them
# false). Accepted cost: a re-narrowing of THIS file's own gloss is not
# caught mechanically. It is bounded - the gloss documents a guard rather
# than stating the rule, and the two normative sources are pinned by
# `test_widening_is_stated_at_both_normative_sources`.
_DESCRIPTION_INVARIANT_PATHS = [
    STYLE_PATH,
    INDEX_PATH,
    README_PATH,
    HOOK_PATH,
    CTF_PATH,
    CONFIG_REF_PATH,
    SAFE_CONFIG_PATH,
    RISK_CONFIG_PATH,
    CONVENTIONS_DETAIL_PATH,
    DS_INIT_PROJECT_PATH,
    COMPONENTS_PATH,
]


@pytest.mark.parametrize("site_path", _DESCRIPTION_INVARIANT_PATHS, ids=lambda p: p.name)
def test_no_site_scopes_editorial_addenda_to_a_labelled_package(site_path):
    """Conditional description invariant. See the block comment above
    `_NARROW_SCOPE_RE` for the widened trigger vocabulary (round 9) and,
    importantly, for the four residual gaps it does NOT close - a regex
    cannot fully close a natural-language evasion and this one does not
    claim to."""
    text = site_path.read_text(encoding="utf-8")
    offenders = []
    cursor = 0
    for block in _PARAGRAPH_SPLIT_RE.split(text):
        block_start = text.index(block, cursor) if block else cursor
        cursor = block_start + len(block)
        flat = re.sub(r"\s+", " ", block)
        if not _BAN_SUBJECT_RE.search(flat):
            continue
        if not _NARROW_SCOPE_RE.search(flat):
            continue
        if not _WIDENING_RE.search(flat):
            offenders.append(text.count("\n", 0, block_start) + 1)
    assert not offenders, (
        f"{site_path} describes the editorial-addenda ban in package or "
        f"positional terms in the paragraph(s) starting at line(s) "
        f"{offenders} without stating that the "
        "package is the canonical form and not the boundary. The "
        f"**Editorial addenda.** rule in {CTF_PATH} covers any "
        "conductor-selected item carrying none of "
        "the four turn warrants, bundled or not, IN ANY POSITION in the "
        "turn - a package-scoped or trailing-scoped gloss understates it. "
        "Match the wording already used at the other sites."
    )


# --- Disposition non-restatement invariant --------------------------------
# The **Editorial addenda.** rule's **Disposition.** paragraph routes a
# process observation to the PR body and defers ADMISSION into
# `## Operator decisions` wholly to the kernel gate in
# `content/sections/02-delegation.md`. It must not paraphrase that gate's
# conditions, in full or in summary. This defect relocated twice rather than
# recurring verbatim, on two DIFFERENT axes, so the guard pins both:
#
#   * a weaker SUFFICIENT condition ("it IS a `## Operator decisions` item")
#     carries none of the gate's condition tokens, so a token check alone
#     cannot see it; what it drops is the DENIAL, pinned as present below.
#   * a stricter but INCOMPLETE necessary condition (naming the six-source
#     derivation and a `no derivable default` result while dropping the
#     hard-stop disjunct, thereby licensing unilateral action on an
#     irreversible change) is caught by the condition tokens being ABSENT.
#
# The deferral clause's presence is the third leg.
_DISPOSITION_MARKER = "**Disposition.**"

# Tokens that appear in the kernel gate's admission conditions
# (`content/sections/02-delegation.md`, "Operator decisions go last in the
# turn"). Any of them inside the Disposition paragraph means the gate is
# being restated here, which is the second place for it to drift. Compared
# after `_flatten_for_tokens` folds markdown emphasis and hyphens away, so
# "**no derivable default**" and "no derivable-default" both match.
_GATE_CONDITION_TOKENS = [
    "six source",
    "no derivable default",
    "hard stop",
    "surface and proceed",
    "admits an item",
    "only after",
    "only when",
    "only if",
    "sufficient condition",
    "necessary condition",
    "necessary, never sufficient",
]

# The denial that does the work without asserting a condition, and the
# explicit statement of deferral. Both must survive verbatim (modulo
# whitespace and emphasis) - dropping either is how round 1 and round 3's
# fix respectively would be undone.
_DISPOSITION_REQUIRED_PHRASES = [
    "is not thereby a `## operator decisions` item",
    "deliberately does not restate them",
]


def _flatten_for_tokens(text: str) -> str:
    """Lowercase, drop markdown emphasis, fold hyphens and whitespace runs to
    single spaces. Keeps backticks (the required phrases quote a literal
    markdown heading) and commas (one required token is comma-bearing)."""
    flat = text.lower()
    flat = flat.replace("*", "").replace("_", " ")
    flat = re.sub(r"-", " ", flat)
    flat = re.sub(r"\s+", " ", flat)
    return flat.strip()


def _disposition_paragraph() -> str:
    """Locate the editorial-addenda rule's Disposition paragraph, failing
    LOUDLY if it cannot be
    found or looks truncated.

    The vacuity guard is the point of this helper. Every check below is an
    assertion ABOUT a paragraph; if the paragraph is renamed, reflowed into
    a different block structure, or emptied, a naive `for block in ...: if
    marker in block` loop would simply iterate zero times and the whole
    invariant would pass having examined nothing - the exact false-pass
    class this repo keeps rediscovering. So: exactly one block must carry
    the marker, and it must still be substantial prose."""
    text = CTF_PATH.read_text(encoding="utf-8")
    blocks = [b for b in _PARAGRAPH_SPLIT_RE.split(text) if _DISPOSITION_MARKER in b]
    assert len(blocks) == 1, (
        f"{CTF_PATH}: expected exactly ONE paragraph containing "
        f"{_DISPOSITION_MARKER!r} (the editorial-addenda rule's "
        f"Disposition), found {len(blocks)}. "
        "This guard asserts properties OF that paragraph and cannot run "
        "without it - if the Disposition was renamed, split, or duplicated, "
        "update this locator in the same change rather than letting the "
        "invariant pass vacuously."
    )
    block = blocks[0]
    assert len(block) > 500, (
        f"{CTF_PATH}: the Disposition paragraph is only {len(block)} chars - "
        "implausibly short for a block that must carry both the routing "
        "disposition and the deferral to the kernel gate. Refusing to "
        "certify a stub as compliant."
    )
    return block


def test_disposition_locator_is_not_vacuous():
    """Exercises the vacuity guard itself so a broken locator surfaces as its
    own named failure rather than as silent green in the checks below."""
    assert _DISPOSITION_MARKER in _disposition_paragraph()


def test_disposition_states_the_denial_and_the_deferral():
    """Closes the sufficient-condition axis: an affirmative "it IS a
    `## Operator decisions` item" carries none of the gate's condition
    tokens and is invisible to the token check below."""
    flat = _flatten_for_tokens(_disposition_paragraph())
    missing = [p for p in _DISPOSITION_REQUIRED_PHRASES if p not in flat]
    assert not missing, (
        f"{CTF_PATH}: the editorial-addenda Disposition paragraph no "
        "longer states "
        f"{missing}. The first phrase is the DENIAL that lets the paragraph "
        "say something useful without asserting an admission condition "
        "(dropping it is how round 1's sufficient-condition relocation "
        "read); the second is the explicit deferral to the kernel gate in "
        "content/sections/02-delegation.md. Both must stay."
    )


def test_disposition_does_not_restate_the_kernel_admission_gate():
    """Closes the necessary-condition axis: a paraphrase of the gate is a
    second place for it to drift, and an INCOMPLETE paraphrase is actively
    wrong. See the block comment above `_DISPOSITION_MARKER`."""
    flat = _flatten_for_tokens(_disposition_paragraph())
    found = [t for t in _GATE_CONDITION_TOKENS if t in flat]
    assert not found, (
        f"{CTF_PATH}: the editorial-addenda Disposition paragraph restates "
        "the kernel "
        f"admission gate - it contains condition token(s) {found}. That "
        "paragraph states, in its own words, that "
        "content/sections/02-delegation.md is the single normative "
        "statement of the admission conditions and that this file "
        "'deliberately does not restate them, in full or in summary'. A "
        "paraphrase here is a second place for the gate to drift, and an "
        "INCOMPLETE paraphrase (round 2 dropped the hard-stop disjunct) is "
        "actively wrong. Route the reader to the gate instead."
    )


def test_widening_is_stated_at_both_normative_sources(style_body):
    """The conditional check above can only compare a site against the rule
    if the rule itself still states the widening. Pin it at BOTH normative
    sources so a silent re-narrowing at the origin goes red here rather
    than propagating outward as a newly-consistent narrow definition."""
    # STYLE_PATH is checked against `style_body`, never the whole file: its
    # frontmatter `description:` line names "editorial addenda" verbatim, so
    # a whole-file anchor would be satisfied by the description alone no
    # matter what the body says - the same-source-operands vacuity
    # `style_body` exists to prevent. The anchor is the italic body marker,
    # which the frontmatter cannot supply.
    sources = (
        (CTF_PATH, "editorial addendum", CTF_PATH.read_text(encoding="utf-8")),
        (STYLE_PATH, "*Editorial addenda.*", style_body),
    )
    for path, anchor, text in sources:
        assert anchor.lower() in text.lower(), f"{path} must state the editorial-addenda rule"
        assert _NARROW_SCOPE_RE.search(text), (
            f"{path} must name the labelled-package form of the ban so the "
            "conditional description invariant has something to check"
        )
        assert _WIDENING_RE.search(text), (
            f"{path} no longer states that the labelled package is the "
            "canonical form and NOT the boundary of the editorial-addenda "
            "ban - the rule has been re-narrowed at a normative source"
        )


def test_components_names_full_rule_set(rule_set_topics):
    text = COMPONENTS_PATH.read_text(encoding="utf-8")
    marker = "`turn_shape_guard_enabled`"
    assert marker in text, (
        f"{COMPONENTS_PATH} must contain the '{marker}' config entry "
        "describing what moved to the dinostack output style"
    )
    entry_text = text[text.index(marker):]
    # docs/components.md packs every toggle into one inline comma-separated
    # paragraph (no leading "\n- `" bullet marker like the other sites) -
    # scope to this one parenthetical by finding the ")," that closes it
    # and precedes the next backtick-quoted config key. DS-171 round 7
    # Skeptic Minor 1: this terminator is position-dependent - it assumes
    # `turn_shape_guard_enabled` is not the LAST toggle in the paragraph.
    # If it ever becomes the last one, `find` returns -1 and a silent
    # `if next_entry != -1` fallback would widen the scope to the rest of
    # the file, letting later unrelated prose vacuously satisfy or mask
    # this check. Fail loudly instead so a future reordering is caught and
    # this terminator logic is revisited, rather than silently trusting an
    # unscoped match.
    next_entry = entry_text.find("), `", 1)
    assert next_entry != -1, (
        f"{COMPONENTS_PATH}: could not find the '), `' terminator after "
        f"'{marker}' - either `turn_shape_guard_enabled` has become the "
        "last toggle in the inline paragraph (update this terminator to "
        "match the new closing punctuation) or the paragraph's shape "
        "otherwise changed; do not fall back to scanning the rest of the "
        "file"
    )
    entry_text = entry_text[: next_entry + 1]
    _assert_topics_present(COMPONENTS_PATH, entry_text, rule_set_topics)
    _assert_no_stale_topics(COMPONENTS_PATH, entry_text, rule_set_topics)
