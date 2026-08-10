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


def main():
    checked = _scan()
    print(f"PASS: no self-contradicting capability claim in {checked} agent specs")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
