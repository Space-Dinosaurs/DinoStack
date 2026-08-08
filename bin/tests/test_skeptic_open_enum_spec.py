#!/usr/bin/env python3
"""
Spec tests for the "Skeptic `n/a` enum stays open-world" axis (DS-113):
Section 4.5's enumerated `n/a` rationale set is canonical *preferred wording*
for recurring situations, not an exhaustive whitelist, and Step 0 check 2
must keep assessing rationales on the merits rather than reverting to a
closed string-membership test.

Motivating history (DS-98): the enumerated set was certified complete four
separate times in two days, each certification made while fixing the one
before it, because every certification was a membership test against the
list's own current contents - a membership test can only confirm what is
already in the list, never surface a legitimate value missing from it. DS-98
converted the check from closed membership to an open merits assessment
(`content/references/skeptic-protocol.md` §4.5 Step 0 check 2), but nothing
mechanically stopped a future maintainer from re-closing it by re-introducing
a "must be one of the following" construction, deleting the "not exhaustive"
framing, or reverting the sanctioning phrase Step 0 check 2 depends on. This
suite is that mechanical stop.

Pattern precedent (DS-97, `test_learnings_agent_capture_model_spec.py`): a
prose obligation ("learnings-agent capture is mandatory-trigger, not
discretionary") was declared closed five times before a guard shaped like
this one - presence-anchored assertion of the sanctioning phrase as the
primary check, a narrow residual-pattern catcher as backstop, and an explicit
exemption table for framing that legitimately mentions the banned vocabulary
without asserting it - actually held. This file follows that same shape and
its file layout/naming conventions directly.

Independent precedent for converting a prose obligation into a per-site
gate: `.agentic/learnings.md` entry KNW-20260725-020 (session-local,
gitignored in this repo; cited here as the general pattern, not a file this
suite reads).

Why the mechanism is shaped the way it is: a bare-token scan cannot separate
"a sentence that re-closes the list" from "a sentence that narrates the
closed-world past or forbids re-closing it". The worst possible false
positive is the open-world rationale itself - the sentence at
`content/references/skeptic-protocol.md` §4.5 that explains why the list is
open carries several of the exact tokens (`exhaustive`, `whitelist`,
`string-membership`) a naive scanner would ban. A guard that fails on the
sentence it exists to protect creates pressure to delete that sentence,
which is the opposite of the intended effect. So this suite makes
presence-anchored assertion of the sanctioning phrases the PRIMARY guard
(test 2) and treats a pattern-based scan for closed-world constructions as a
narrow, pattern-scoped-exempted residual catcher (test 3), never the other
way around.

Sanctioned scan sites (`SCAN_FILES`, tests 3/3b only):
  - content/references/skeptic-protocol.md - canonical Section 4.5 source;
    carries the enumerated set, the "not exhaustive" framing, and Step 0
    check 2's sanctioning phrase.
  - content/agents/skeptic.md - the Skeptic's own operating instructions
    (.claude/agents is a symlink blob pointing at ../content/agents, so
    .claude/agents/skeptic.md resolves to the same file - editing one edits
    both; this suite reads the content/ path only, per repo convention).
  No other file is scanned by tests 3/3b: the closed-world-construction
  residual catcher exists to police the two files that define and enforce
  Step 0, not the entire tree - a wider scope would produce false positives
  on unrelated prose (e.g. the pagination-completeness claim about event
  scanning at skeptic-protocol.md's "is exhaustive for new events", which
  this suite treats as a SANCTIONED_FRAMING exemption rather than widening
  or narrowing the pattern to dodge it).

File enumeration for test 4 (the only test that needs a repo-wide scan) is
derived from `git ls-files -z`, not `Path.rglob`/`os.walk`/`glob`. This is
binding, not a style preference: this ticket's own planning artifact
contains the merged-disjunction string this suite hunts for, and stale
copies of every file this suite scans live under `.agentic/worktrees/**` and
`.claude/worktrees/**` from prior sessions. All of those are untracked or
gitignored. A walk-based scan would pick them up and could pass or fail for
reasons that have nothing to do with the live tree a reviewer actually
checks out; `git ls-files` excludes them by construction because it only
ever lists what git tracks.

Run with: python3 -m pytest bin/tests/test_skeptic_open_enum_spec.py -q
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SKEPTIC_PROTOCOL = REPO_ROOT / "content" / "references" / "skeptic-protocol.md"
SKEPTIC_AGENT = REPO_ROOT / "content" / "agents" / "skeptic.md"

# Scope for tests 3 and 3b - exactly these two files, nothing else.
SCAN_FILES = [SKEPTIC_PROTOCOL, SKEPTIC_AGENT]

OPEN_WORLD_PHRASE = "not an exhaustive whitelist"
MUST_NOT_BLOCK_PHRASE = "must not be blocked on that basis alone"

SANCTION_ANCHORS = [
    (
        "This list is not exhaustive",
        "the enum preamble's own open-world declaration - if this disappears, the "
        "enumerated `n/a` set silently reads as closed again",
    ),
    (
        "not an exhaustive whitelist",
        "Step 0 check 2's sanctioning phrase - the specific sentence that keeps the "
        "Skeptic from BLOCKing a truthful rationale that is not one of the enumerated "
        "strings",
    ),
    (
        "Do not re-close this list by reverting to string-membership checking",
        "the explicit prohibition against reverting Step 0 check 2 to a closed "
        "membership test - the exact regression DS-98 fixed and this suite exists to "
        "keep fixed",
    ),
]

# (regex, description) - each asserts closure of the enumerated set rather
# than merely naming or describing it.
PRESCRIPTIVE_PATTERNS = [
    re.compile(r"\bis exhaustive\b", re.IGNORECASE),
    re.compile(r"\bare exhaustive\b", re.IGNORECASE),
    re.compile(r"\ban exhaustive (list|set|whitelist|enumeration|vocabulary)\b", re.IGNORECASE),
    re.compile(r"\bmust be one of\b", re.IGNORECASE),
    re.compile(r"\bonly the enumerated\b", re.IGNORECASE),
    re.compile(r"\bclosed vocabulary\b", re.IGNORECASE),
    re.compile(r"\bstring-membership\b", re.IGNORECASE),
    re.compile(r"\bwhitelist\b", re.IGNORECASE),
]

# Pattern-scoped stripping: for each (file, substring), remove ONLY that
# exact substring from a matching line before running PRESCRIPTIVE_PATTERNS
# against what remains. Never exclude the whole line - a second, unrelated
# closed-world construction co-located on the same line must still be
# caught. This is a measured, complete set: a full scan of SCAN_FILES against
# PRESCRIPTIVE_PATTERNS with this table applied yields exactly zero residual
# hits (test 3). If a future edit produces a new hit, the fix is to add a
# reasoned exemption here, never to narrow a PRESCRIPTIVE_PATTERNS regex to
# make the hit vanish - narrowing the regex is the DS-97 failure mode
# (case-sensitive/token-scoped checks silently missing semantic variants)
# this suite's design exists to prevent.
SANCTIONED_FRAMING: list[tuple[Path, str, str]] = [
    (
        SKEPTIC_PROTOCOL,
        "This list is not exhaustive",
        "the enum preamble's own open-world declaration",
    ),
    (
        SKEPTIC_PROTOCOL,
        "not an exhaustive whitelist",
        "Step 0 check 2's sanctioning phrase",
    ),
    (
        SKEPTIC_PROTOCOL,
        "previously treated as exhaustive",
        "narrates the closed-world past, does not assert it for the present",
    ),
    (
        SKEPTIC_PROTOCOL,
        "a closed vocabulary guarantees",
        "argues against closure (a closed vocabulary guarantees a missed case), not for it",
    ),
    (
        SKEPTIC_PROTOCOL,
        "reverting to string-membership checking",
        "the prohibition itself - names the banned construction to forbid it",
    ),
    (
        SKEPTIC_PROTOCOL,
        "is exhaustive for new events",
        "a pagination-completeness claim about event scanning, semantically unrelated "
        "to the `n/a` enum",
    ),
]


def _git_ls_files(prefix: str) -> list[Path]:
    """Enumerate tracked files under `prefix`, resolved from REPO_ROOT via
    `git ls-files -z`. Never Path.rglob/os.walk/glob - see module docstring
    "File enumeration" for why: worktree artifacts and untracked planning
    docs under this same tree can carry the exact strings this suite hunts
    for, and a walk-based scan would pick them up while `git ls-files`
    excludes anything git does not track by construction."""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z", "--", prefix],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"git ls-files unavailable or failed: {exc}")
        return []
    raw = proc.stdout.decode("utf-8", errors="replace")
    names = [n for n in raw.split("\0") if n]
    if not names:
        pytest.skip(f"git ls-files -z -- {prefix} returned empty - repo state unreadable")
    return [REPO_ROOT / n for n in names]


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, FileNotFoundError):
        return []


# ---------------------------------------------------------------------------
# Test 1 - open-world sanctioning phrase present in both copies (anti-rubber-
# stamp half: the sanctioned sites must actually carry their sanction).
# ---------------------------------------------------------------------------

def test_open_world_sanctioning_phrase_present_in_both_copies():
    protocol_text = SKEPTIC_PROTOCOL.read_text(encoding="utf-8")
    assert OPEN_WORLD_PHRASE.lower() in protocol_text.lower(), (
        f"{_rel(SKEPTIC_PROTOCOL)} no longer contains {OPEN_WORLD_PHRASE!r} - this is "
        "Step 0 check 2's sanctioning phrase; without it, a truthful rationale that is "
        "not one of the enumerated strings has no textual basis to avoid a BLOCKED verdict."
    )

    for path in (SKEPTIC_PROTOCOL, SKEPTIC_AGENT):
        text = path.read_text(encoding="utf-8")
        assert MUST_NOT_BLOCK_PHRASE in text.lower(), (
            f"{_rel(path)} no longer contains a case-insensitive match for "
            f"{MUST_NOT_BLOCK_PHRASE!r} - both the protocol and the agent's own operating "
            "instructions must state that a truthful, specific, non-enumerated rationale "
            "must not be BLOCKED on that basis alone."
        )


# ---------------------------------------------------------------------------
# Test 2 - open-world sanction anchors present (primary guard).
# ---------------------------------------------------------------------------

def test_open_world_sanction_anchors_present():
    text = SKEPTIC_PROTOCOL.read_text(encoding="utf-8")
    for anchor, forbids in SANCTION_ANCHORS:
        assert anchor in text, (
            f"{_rel(SKEPTIC_PROTOCOL)} is missing the sanction anchor {anchor!r}. "
            f"This sentence {forbids}. Its deletion would silently re-close the "
            "enumerated `n/a` rationale set - restore it verbatim; see DS-98 in the "
            "module docstring for the motivating history."
        )


# ---------------------------------------------------------------------------
# Test 3 - residual catcher: zero closed-world constructions after
# pattern-scoped stripping of the sanctioned framing.
# ---------------------------------------------------------------------------

def _residual_violations() -> list[tuple[Path, int, str, str]]:
    violations: list[tuple[Path, int, str, str]] = []
    for path in SCAN_FILES:
        for lineno, line in enumerate(_read_lines(path), start=1):
            remainder = line
            for sfile, sub, _reason in SANCTIONED_FRAMING:
                if sfile == path and sub in remainder:
                    remainder = remainder.replace(sub, "")
            for pattern in PRESCRIPTIVE_PATTERNS:
                if pattern.search(remainder):
                    violations.append((path, lineno, line, pattern.pattern))
    return violations


def test_no_prescriptive_closed_world_construction_in_enforcement_files():
    violations = _residual_violations()
    assert not violations, (
        "Found a closed-world construction (asserts the enumerated `n/a` set IS "
        "exhaustive, rather than merely naming or narrating it) outside the sanctioned "
        "framing table. This re-closes the list Step 0 check 2 depends on staying open. "
        "If this hit is legitimate framing (narrates the closed-world past, argues "
        "against closure, or is semantically unrelated to the `n/a` enum), add a "
        "reasoned SANCTIONED_FRAMING entry - do NOT narrow a PRESCRIPTIVE_PATTERNS regex "
        "to make it vanish (the DS-97 failure mode this suite's design exists to "
        "prevent). Offending site(s): "
        + "; ".join(
            f"{_rel(p)}:{ln} (matched /{pat}/): {line.strip()!r}"
            for p, ln, line, pat in violations
        )
    )


def test_sanctioned_framing_substrings_still_present():
    # Vacuity guard: if a SANCTIONED_FRAMING substring silently disappears
    # from the file it's scoped to (rewording, deletion), the exemption
    # becomes dead weight and test_no_prescriptive_closed_world_construction
    # stops meaningfully exercising the exclusion path for it.
    missing = []
    for path, sub, _reason in SANCTIONED_FRAMING:
        text = path.read_text(encoding="utf-8")
        if sub not in text:
            missing.append(f"{_rel(path)} no longer contains {sub!r}")
    assert not missing, (
        "SANCTIONED_FRAMING entries not found in their scoped file (exemption is dead "
        "weight if this happens - the residual-catcher test above is untested for these "
        "exclusions): " + "; ".join(missing)
    )


# ---------------------------------------------------------------------------
# Test 4 - architect-skip enum split into two values.
# ---------------------------------------------------------------------------

MERGED_DISJUNCTION = "judgment-based skip for a well-understood, self-contained change"
JUDGMENT_PREFIX = "n/a - architect skipped (judgment-based:"
MECHANICAL_PREFIX = "n/a - architect skipped (mechanical:"


def test_architect_skip_enum_is_split_into_two_values():
    text = SKEPTIC_PROTOCOL.read_text(encoding="utf-8")
    assert JUDGMENT_PREFIX in text, (
        f"{_rel(SKEPTIC_PROTOCOL)} is missing the split judgment-based enum value "
        f"{JUDGMENT_PREFIX!r} - DS-113 splits the merged architect-skip disjunction into "
        "two independently falsifiable values so a Skeptic can test each rationale's "
        "truthfulness."
    )
    assert MECHANICAL_PREFIX in text, (
        f"{_rel(SKEPTIC_PROTOCOL)} is missing the split mechanical enum value "
        f"{MECHANICAL_PREFIX!r} - see JUDGMENT_PREFIX assertion above for why the split "
        "is required."
    )

    offenders = []
    for path in _git_ls_files("content/"):
        for lineno, line in enumerate(_read_lines(path), start=1):
            if MERGED_DISJUNCTION in line:
                offenders.append(f"{_rel(path)}:{lineno}: {line.strip()!r}")
    assert not offenders, (
        f"The merged disjunction {MERGED_DISJUNCTION!r} is still present in a tracked "
        "file under content/ - it must be fully replaced by the two split enum values "
        f"({JUDGMENT_PREFIX!r} and {MECHANICAL_PREFIX!r}). Offending site(s): "
        + "; ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Test 5 - branch-copy rule covers Step 0 checks (not just the enum).
# ---------------------------------------------------------------------------

def test_branch_copy_rule_covers_step_0_checks():
    protocol_text = SKEPTIC_PROTOCOL.read_text(encoding="utf-8")
    assert "the Step 0 checks, or any other Section 4.5 validation rule" in protocol_text, (
        f"{_rel(SKEPTIC_PROTOCOL)} no longer broadens the branch-copy rule to cover the "
        "Step 0 checks and other Section 4.5 validation rules, not just the enumerated "
        "`n/a` set - a PR that rewrites a Step 0 check without touching the enum would "
        "again be validated against a stale installed copy."
    )

    agent_text = SKEPTIC_AGENT.read_text(encoding="utf-8")
    assert "Step 0" in agent_text and "branch" in agent_text.lower() and (
        "validate every field against the branch's copy" in agent_text
        or "branch's own copy" in agent_text
    ), (
        f"{_rel(SKEPTIC_AGENT)} is missing a branch-copy sentence naming Step 0 - the "
        "agent's own operating instructions must tell it to validate against the "
        "branch's copy of Section 4.5 when the diff under review amends Step 0 itself."
    )


# ---------------------------------------------------------------------------
# Test 6 - post-Step-0 falsity disposition present in both copies.
# ---------------------------------------------------------------------------

def test_post_step0_falsity_disposition_present_in_both_copies():
    protocol_text = SKEPTIC_PROTOCOL.read_text(encoding="utf-8")
    assert "Falsity discovered after Step 0" in protocol_text, (
        f"{_rel(SKEPTIC_PROTOCOL)} is missing the 'Falsity discovered after Step 0' "
        "subsection - without it, a Skeptic that discovers a rationale was false after "
        "Step 0 has no documented disposition and may incorrectly return a retroactive "
        "BLOCKED, discarding review work already completed."
    )
    assert "finding, never a retroactive BLOCKED" in protocol_text, (
        f"{_rel(SKEPTIC_PROTOCOL)} is missing the explicit 'finding, never a retroactive "
        "BLOCKED' disposition rule."
    )

    agent_text = SKEPTIC_AGENT.read_text(encoding="utf-8")
    assert re.search(r"do not return blocked", agent_text, re.IGNORECASE), (
        f"{_rel(SKEPTIC_AGENT)}'s Step 0 region is missing a case-insensitive 'do NOT "
        "return BLOCKED' instruction for the post-Step-0 falsity-discovery case."
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
