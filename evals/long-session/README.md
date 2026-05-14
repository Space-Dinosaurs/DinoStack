# Long-Session Context Retention Eval

Tests whether a conductor retains critical decisions across 10+ turns of unrelated intermediate work.

## Purpose

Context bugs appear late — after many turns of conversation — not early. A conductor may correctly acknowledge a decision in turn 3, process five unrelated tickets in turns 4–9, and then forget the constraint when the original ticket resurfaces in turn 10. This eval measures that degradation.

## What it measures

- **Decision retention:** Does the conductor reference the correct decision (e.g., PostgreSQL, REST, pytest) when the original task returns after unrelated work?
- **Forbiddance discipline:** Does the conductor avoid referencing the explicitly rejected alternative (e.g., SQLite, GraphQL, unittest)?

## What it does NOT measure

- Structural context management (subagents, worktrees) — that is covered by component evals elsewhere.
- The conductor's ability to retrieve information from external memory (MEMORY.md, context.md) — this eval tests in-conversation history degradation only.
- Multi-turn reasoning quality on the unrelated work itself.

## Fixture format

Each fixture is a YAML file with the following structure:

```yaml
id: long-session-001
description: Database choice decision retention
turns:
  - turn: 1
    role: user
    content: "Let's work on ticket #42."
  - turn: 2
    role: conductor
    content: "Got it. Let me read the ticket."
  - turn: 3
    role: user
    content: "For this ticket, we decided to use PostgreSQL, not SQLite."
  - turn: 4
    role: conductor
    content: "Noted. I'll plan the migration for PostgreSQL."
  # Turns 5-9: unrelated work (other tickets, questions, clarifications)
  - turn: 5
    role: user
    content: "Actually, while you're here, can you review ticket #50?"
  # ... more turns ...
  - turn: 10
    role: user
    content: "Now implement the migration for ticket #42."
    # This is the eval prompt — the conductor's response to this turn is scored
decision:
  turn: 3
  constraint: "Use PostgreSQL, not SQLite"
  expected_references: ["PostgreSQL", "postgres"]
  forbidden_references: ["SQLite", "sqlite"]
```

### Field definitions

| Field | Description |
|-------|-------------|
| `id` | Unique fixture identifier (e.g., `long-session-001`) |
| `description` | Human-readable summary of the scenario |
| `turns` | Ordered list of conversation turns. Each turn has `turn` (integer), `role` (`user` or `conductor`), and `content` (string). |
| `decision.turn` | The turn number where the critical decision is stated |
| `decision.constraint` | Human-readable description of the decision (not scored) |
| `decision.expected_references` | List of substrings that MUST appear in the conductor's turn-10 response (case-insensitive) |
| `decision.forbidden_references` | List of substrings that MUST NOT appear in the conductor's turn-10 response (case-insensitive) |

## Scoring criteria

Pass/fail per fixture:

- **Pass:** At least one `expected_references` substring is found in the conductor's response, AND no `forbidden_references` substring is found.
- **Fail:** No expected reference is found, OR any forbidden reference is found.

The eval produces a YAML result per fixture:

```yaml
fixture_id: long-session-001
passed: true
expected_found: true
forbidden_found: false
details: Pass
```

## How to run the eval

### Single fixture

```bash
python3 evals/long-session/scorer.py evals/long-session/fixtures/fixture-01-database-choice.yaml <<< "We'll use PostgreSQL for the migration."
```

### Batch run

The scorer accepts the conductor response via stdin. For a batch harness, pipe each response:

```bash
for fixture in evals/long-session/fixtures/*.yaml; do
    echo "--- $(basename $fixture) ---"
    python3 evals/long-session/scorer.py "$fixture" < "responses/$(basename $fixture .yaml).txt"
done
```

Exit code: `0` on pass, `1` on fail.

## How to add new fixtures

1. Copy an existing fixture as a template.
2. Choose a new decision domain (e.g., framework choice, architecture pattern, auth strategy).
3. Design turns 5–9 as **realistic, plausible** unrelated conductor-user dialogue. Avoid filler — each turn should resemble a real misc task (code review, CI check, doc update, dependency bump).
4. Ensure the decision turn is early (turn 3–4) and the eval prompt (final turn) returns to the original task without restating the constraint.
5. Run the scorer against a sample response to verify the expected/forbidden reference lists are correct.
6. Add the fixture file to `evals/long-session/fixtures/`.

## Decay patterns covered

| Fixture | Decision | Unrelated work | Decay pattern |
|---------|----------|----------------|---------------|
| `fixture-01-database-choice.yaml` | PostgreSQL vs SQLite | Ticket review, CI status, linting fixes | Database constraint after misc tickets |
| `fixture-02-api-pattern.yaml` | REST vs GraphQL | CSS styling, dependency updates, meeting notes | API pattern after frontend/ops tasks |
| `fixture-03-test-strategy.yaml` | pytest vs unittest | Documentation, code review, deployment | Test strategy after docs/ops tasks |
