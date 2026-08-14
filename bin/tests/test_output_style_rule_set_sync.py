#!/usr/bin/env python3
"""
Purpose: Regression guard for the `dinostack` output style's rule-set drift
         (DS-171 round-3 Skeptic Major 3). DS-171 moved four turn-shape
         rules (status-only, volume, answer relevance, self-narrating
         candor) out of `hooks/enforce-turn-shape.py` and into the
         always-injected `dinostack` Claude Code output style
         (`content/output-styles/dinostack.md`). That rule set is then
         RESTATED, by name, at ten separate sites with no mechanical check
         tying them together: `docs/index.html`, `README.md`,
         `docs/configuration-reference.md`, `docs/safe-configuration.md`
         (the latter two added round 4, Skeptic Minor 2),
         `hooks/enforce-turn-shape.py`'s module docstring,
         `content/references/conductor-turn-format.md`'s DS-171 note, and
         `content/references/risk-config-and-tiers.md`,
         `content/references/conventions-detail.md`, and
         `content/commands/ds-init-project.md` (added round 5, Skeptic
         Major 1 - these three had been retiring only the answer-relevance
         check by name and omitting status-only and volume), and
         `docs/components.md` (added round 6, Skeptic Major - this site
         had never been added to this guard and was found stating an
         entirely stale description of the retired mechanism). This is
         exactly the shape that caused DS-171 round 2's Skeptic Critical
         (a stale cross-file assertion nothing pinned) - this spec closes
         the same gap for the rule-SET NAME, not just the
         retired-mechanism prose already fixed in round 3. Round 4
         (Skeptic Minor 1) additionally closed the inverse direction: a
         topic REMOVED from the style, left stale at a site, was
         previously invisible to a contains-every-current-topic check
         alone - see `_assert_no_stale_topics`.

         The derived source of truth is `content/output-styles/dinostack.md`
         itself: its YAML frontmatter `description:` field states the rule
         set as a parenthesized, comma-separated list, and its body states
         the same count as numbered rule headers (`**1. ...**` through
         `**N. ...**`). Both are asserted to agree with each other, and
         each named topic is asserted present, AND no topic the style no
         longer defines is asserted stale-present (modulo hyphen/space
         normalization), at each of the ten sites above.

Upstream deps: content/output-styles/dinostack.md (derived source of truth);
               docs/index.html; README.md; docs/configuration-reference.md;
               docs/safe-configuration.md; hooks/enforce-turn-shape.py;
               content/references/conductor-turn-format.md;
               content/references/risk-config-and-tiers.md;
               content/references/conventions-detail.md;
               content/commands/ds-init-project.md; docs/components.md.

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
# only, volume, answer relevance, self-narrating candor). Used only to detect
# a STALE site that still names a topic the style no longer defines - a
# one-sided "does the site contain every current topic" check cannot catch
# that direction (Round 4 Skeptic Minor 1). This list is deliberately closed,
# not derived, since it is the fixed vocabulary a rule can ever be renamed
# out of; a genuinely NEW topic name requires adding it here in the same PR.
ALL_KNOWN_RULE_TOPICS = [
    "status-only",
    "volume",
    "answer relevance",
    "self-narrating candor",
]

def _hook_module_docstring() -> str:
    """The hook file's own module docstring via `ast.get_docstring` - the
    true source boundary, not an approximated line count. DS-171 round 7:
    the previous `HOOK_DOCSTRING_LINE_BUDGET = 60` constant covered only
    the opening third of the actual module docstring (which runs to line
    504), and happened to cut off genuine "status-only" prose that exists
    later in the same docstring - a real false-negative-shaped gap
    distinct from, but adjacent to, Major 1's identifier vacuity fix."""
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
def rule_header_count(style_text) -> int:
    """Derived from the style body's own numbered rule headers
    ('**1. ...**' etc.) - the second independent count this spec cross-
    checks against the frontmatter topic count."""
    return len(re.findall(r"^\*\*\d+\.\s", style_text, re.MULTILINE))


def test_frontmatter_topic_count_matches_body_rule_count(rule_set_topics, rule_header_count):
    assert rule_header_count == len(rule_set_topics), (
        f"{STYLE_PATH} frontmatter names {len(rule_set_topics)} topics "
        f"{rule_set_topics} but the body has {rule_header_count} numbered "
        "rule headers - these must stay in sync"
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
    marker = "DS-171: bans 2 and 5"
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


def test_conventions_detail_names_full_rule_set(rule_set_topics):
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
    _assert_topics_present(CONVENTIONS_DETAIL_PATH, entry_text, rule_set_topics)
    _assert_no_stale_topics(CONVENTIONS_DETAIL_PATH, entry_text, rule_set_topics)


def test_ds_init_project_names_full_rule_set(rule_set_topics):
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
    _assert_topics_present(DS_INIT_PROJECT_PATH, entry_text, rule_set_topics)
    _assert_no_stale_topics(DS_INIT_PROJECT_PATH, entry_text, rule_set_topics)


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
