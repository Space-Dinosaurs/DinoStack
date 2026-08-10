#!/usr/bin/env python3
"""
Regression guard for self-contradicting capability claims in agent specs
(DS-154 Unit C, Skeptic round 2 Major 1).

The defect class: an agent spec asserts a BLANKET prohibition on using `Bash`
to mutate state, while the SAME file's own procedure mandates a mutating Bash
command. The claim is false for that agent, and because it sits inside that
agent's own file, the agent can cite it to decline a load-bearing step.

This shipped twice before any gate existed:

  - `content/agents/skeptic.md` carried "your read-only contract forbids using
    it to mutate state" while step 9 mandates `git worktree add <scratch>`,
    `git -C <scratch> checkout <head-sha> -- <test-paths>` and
    `git worktree remove --force <scratch>` to establish the pre-fix-failure
    property. A reviewer executed that exact procedure while finding the
    contradiction.
  - `content/agents/qa-engineer.md` carried the same shape of clause while its
    perceptual_diff procedure calls `fs.writeFileSync(diff_image, ...)`.

Round 1 patched the clause with a general rewrite; round 2 patched one
counterexample with a scoped variant. A third variant would predict a fourth
counterexample, so the clause was deleted outright - each bullet's remaining
reason (the conductor's routing hop reads `learnings_candidate[]` only from
`engineer`, `investigator` and `debugger`) is a fact about the pipeline rather
than a claim about what an agent may do with a tool.

What this guard asserts: no file in content/agents/ contains BOTH a blanket
Bash-mutation prohibition AND an unambiguous mutating command in its own
procedure. It is deliberately narrow on the mutation side - only tokens that
cannot plausibly appear inside a prohibition sentence are matched. `git commit`
and `git stash` are excluded precisely because they DO appear inside
prohibitions ("no writes, no package installs, no git commits" in
content/agents/architect.md:232), which would make this a false-positive
generator rather than a gate.

Verified non-vacuous: run against the pre-fix tree (1716e8c6) this predicate
flags exactly skeptic.md and qa-engineer.md and nothing else; against the fixed
tree it flags nothing.

This module carries a SECOND, independent guard, added in round 4: the
shard-capture membership invariant, which cross-checks the enumerated role list
in content/references/learnings-capture-instruction.md against the agent specs
that actually instruct `ds-learning-shard append`. See the section comment
above `_scan_membership` for why an enumeration needs a gate that a predicate
did not.
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO / "content" / "agents"

# A blanket claim that Bash must never be used to change state.
#
# Deliberately a narrow whitelist of the four wordings that have actually
# shipped here, not a general "prohibition-shaped sentence" pattern. A fifth
# variant would evade it - that is the accepted cost. Any broader pattern (e.g.
# matching "no writes" or a generic never-plus-mutation-verb) fires on
# content/agents/architect.md:232 ("no writes, no package installs, no git
# commits"), which is a legitimate scope statement, not a capability claim;
# turning this gate into a false-positive generator would cost more than the
# evasion it closes. Widen only by adding a literal that has been observed in a
# real spec, and re-run against the pre-fix tree to confirm the gate still
# flags exactly skeptic.md and qa-engineer.md.
PROHIBITION = re.compile(
    r"(never use (it|`Bash`) to (write|modify|mutate)"
    r"|contract forbids using it to mutate"
    r"|off-limits to you"
    r"|never to writing durable)",
    re.IGNORECASE,
)

# Unambiguously state-mutating commands. Kept deliberately small: every token
# here would be bizarre to find inside a prohibition sentence, which is what
# keeps the two-sided match meaningful.
MUTATING_COMMAND = re.compile(
    r"(git worktree add|git worktree remove|writeFileSync|mkdir -p)"
)


def _scan():
    """Fail when one agent file both forbids and mandates Bash mutation.

    Returns the number of agent specs checked. Kept separate from the pytest
    entry point below so the test function itself returns None - a returning
    test raises PytestReturnNotNoneWarning today and is an error in future
    pytest releases.
    """
    agent_files = sorted(AGENTS_DIR.glob("*.md"))
    assert agent_files, f"no agent specs found under {AGENTS_DIR}"

    violations = []
    for path in agent_files:
        text = path.read_text(encoding="utf-8")
        prohibition = PROHIBITION.search(text)
        if not prohibition:
            continue
        mutations = sorted(set(MUTATING_COMMAND.findall(text)))
        if mutations:
            violations.append((path.relative_to(REPO), prohibition.group(0), mutations))

    if violations:
        lines = [
            "Agent spec(s) forbid Bash mutation while mandating it in the same file:",
        ]
        for rel, clause, mutations in violations:
            lines.append(f"  {rel}")
            lines.append(f"    prohibition: {clause!r}")
            lines.append(f"    own procedure uses: {', '.join(mutations)}")
        lines.append(
            "Delete the capability clause rather than narrowing it - a scoped "
            "variant re-asserts the same shape of claim against the same "
            "unverified surface."
        )
        raise AssertionError("\n".join(lines))

    return len(agent_files)


def test_no_self_contradicting_capability_claim():
    _scan()


# ---------------------------------------------------------------------------
# Shard-capture membership invariant (DS-154 Unit C, Skeptic round 4)
# ---------------------------------------------------------------------------
#
# Rounds 1-4 of this unit each fixed the same defect: a PREDICATE deciding
# which capture branch an agent belongs to, falsified by some agent. Round 4
# fixed it correctly, by deleting the predicate and enumerating membership
# instead - `content/references/learnings-capture-instruction.md` now names
# exactly the roles that capture through the shard CLI.
#
# That is the right fix, but it converts a derivable rule into a HAND-MAINTAINED
# TWO-SIDED INVARIANT: the reference's enumeration and the agent files must
# agree, and until this guard nothing checked that. Adding a fifth agent bullet
# instructing `ds-learning-shard append`, or editing the reference's list,
# desynchronizes silently. The class recurred four times precisely because the
# two sides were never cross-checked mechanically.
#
# The reference side is PARSED from the file, never hardcoded here. A hardcoded
# list would make this test a third copy of the invariant - the same defect one
# level up, where someone edits the reference and the test in one pass and the
# agent files silently disagree with both.

REFERENCE = REPO / "content" / "references" / "learnings-capture-instruction.md"

# The enumerated membership sentence, e.g.
#   "Exactly four roles capture through `ds-learning-shard`: `engineer`,
#    `adr-generator`, `product-discovery` and `release-orchestrator`."
# Matched against whitespace-normalized text so the sentence may wrap freely.
MEMBERSHIP_SENTENCE = re.compile(
    r"Exactly\s+(?P<count>[A-Za-z]+|\d+)\s+roles\s+capture\s+through\s+"
    r"`ds-learning-shard`:\s*(?P<roles>[^.]+)\."
)

BACKTICKED = re.compile(r"`([a-z][a-z0-9-]*)`")

# The positive, imperative instruction. `learning-extractor`, `learnings-agent`
# and `wrap-ticket` mention `ds-learning-shard` only to say they cannot run it,
# and none of them carries the `append` subcommand - which is what makes the
# `append` token, rather than the bare CLI name, the discriminator.
SHARD_INVOCATION = "ds-learning-shard append"

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _parse_reference_membership():
    """Return (declared_count, set_of_role_names) from the reference file."""
    text = " ".join(REFERENCE.read_text(encoding="utf-8").split())
    match = MEMBERSHIP_SENTENCE.search(text)
    assert match, (
        f"could not locate the enumerated membership sentence in "
        f"{REFERENCE.relative_to(REPO)}. This guard parses that sentence rather "
        f"than hardcoding the role list; if the wording changed, update "
        f"MEMBERSHIP_SENTENCE here in the same commit - do not replace the parse "
        f"with a literal list, which would make this test a third copy of the "
        f"invariant."
    )
    raw_count = match.group("count").lower()
    declared_count = _NUMBER_WORDS.get(raw_count)
    if declared_count is None:
        declared_count = int(raw_count)
    return declared_count, set(BACKTICKED.findall(match.group("roles")))


def _scan_membership():
    """Fail when the reference's role list and the agent files disagree.

    Asserts SET EQUALITY between the two sides plus the count the sentence
    states. Either half alone is insufficient: a count check passes while the
    sets diverge by a swap, and a one-directional subset check passes while the
    other side has an extra member.
    """
    declared_count, declared_roles = _parse_reference_membership()

    agent_roles = {
        path.stem
        for path in sorted(AGENTS_DIR.glob("*.md"))
        if SHARD_INVOCATION in path.read_text(encoding="utf-8")
    }

    problems = []
    if declared_roles != agent_roles:
        problems.append(
            "reference list and agent files disagree:\n"
            f"    named in reference but no `{SHARD_INVOCATION}` in their spec: "
            f"{sorted(declared_roles - agent_roles) or 'none'}\n"
            f"    instruct `{SHARD_INVOCATION}` but not named in reference:     "
            f"{sorted(agent_roles - declared_roles) or 'none'}"
        )
    if declared_count != len(declared_roles):
        problems.append(
            f"the sentence says {declared_count} roles but backtick-names "
            f"{len(declared_roles)}: {sorted(declared_roles)}"
        )
    if declared_count != len(agent_roles):
        problems.append(
            f"the sentence says {declared_count} roles but "
            f"{len(agent_roles)} agent spec(s) instruct `{SHARD_INVOCATION}`: "
            f"{sorted(agent_roles)}"
        )

    if problems:
        raise AssertionError(
            "shard-capture membership invariant is out of sync between "
            f"{REFERENCE.relative_to(REPO)} and content/agents/:\n  - "
            + "\n  - ".join(problems)
            + "\nBoth sides must be changed together: the enumeration exists "
            "because a capability PREDICATE was falsified four review rounds "
            "running, so do not restore a predicate to paper over the drift."
        )

    return sorted(agent_roles)


def test_shard_capture_membership_matches_agent_specs():
    _scan_membership()


def main():
    checked = _scan()
    print(f"PASS: no self-contradicting capability claim in {checked} agent specs")
    members = _scan_membership()
    print(
        "PASS: shard-capture membership consistent between "
        f"learnings-capture-instruction.md and content/agents/ ({len(members)}): "
        f"{', '.join(members)}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
