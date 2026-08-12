<!--
Purpose: Canonical authoring guidance for command files, skill definitions, and
         agent/global definitions in the methodology. Teaches two principles:
         trigger-keyword descriptions (a description is always injected into
         context even when the artifact is unused, so it must enumerate when to
         fire rather than summarize behavior) and bad/good example-pair seeding
         (concrete pairs encode taste via few-shot transfer more reliably than
         abstract rules). Also states the module-manifest requirement for new
         command files.

Public API: Read on trigger when authoring or editing a command file
            (content/commands/*.md), a skill definition (e.g. a
            SKILL.frontmatter.yaml), or an agent/global definition
            (content/agents/*.md). Referenced from content/SKILL.md (Reference
            Docs section) and content/commands/ds-update-agentic-engineering.md
            (command-authoring note for the methodology-edit flow).

Upstream deps: content/rules/module-manifest.md (manifest requirement for new
               command files).

Downstream consumers: authors of new commands, skills, and agent definitions;
                      Skeptic (may cite these sections when reviewing an
                      authoring change).

Failure modes: Prose reference; does not auto-execute. The cited examples go
               stale if the artifacts they quote change (the qa-engineer.md
               pair, the "Apply when" frontmatter) - re-verify the cited lines
               when editing this doc.

Performance: N/A - methodology document consumed by LLMs at spawn time.
-->

# Command, Skill & Definition Authoring

Guidance for authoring the descriptions and example content of command files,
skill definitions, and agent/global definitions. The goal of an authored
definition is to fire at the right moment and to encode the taste an agent needs
to produce output shaped the way a reviewer expects. Two principles carry most
of the weight, both from Theo (t3.gg) "I Fixed Claude Without Touching Any
Code".

## 1. Trigger-keyword descriptions

### The always-injected rationale

A skill or command's description is injected into the agent's context on every
session where that skill or command is available - even when the skill or
command is never invoked. The cost of carrying the description is paid whether
or not the artifact fires. A behavior summary spends that always-paid context on
text that is useful only after the firing decision is already made, and at that
point the full body of the skill or command is available anyway.

### The rule

Write descriptions as trigger keywords: enumerate the conditions under which
the skill or command should fire, so the description answers "when do I use
this?" rather than "what does this do?". The moment the description actually
matters is the instant an agent is deciding whether to invoke the artifact, and
a list of trigger conditions is what decides at that instant.

### Canonical example: the dinostack skill itself

The skill's frontmatter description is written as a trigger, not a summary
(`SKILL.frontmatter.yaml`):

```
Apply when the user mentions any software development work: implementing
features, fixing bugs, reviewing or refactoring code, debugging, testing,
deploying, working with agents or subagents, making architecture decisions,
setting up projects, managing dependencies, writing scripts, or any task
that involves reading, writing, or reasoning about code and systems.
```

### Command files use the same trigger principle

Where a command file needs a trigger, express it as a "When to use" field. Every
command file should answer "use when X, Y, or Z holds" before it explains what
the command does. Reference example (`content/commands/ds-update-agentic-engineering.md`):

```
**When to use - use whenever ANY of these hold:**
- (a) The user asks to edit, add, or remove a rule, convention, agent
      definition, command, reference, or protocol doc under your dinostack
      install.
- (b) The user says "update the methodology", ...
```

### Anti-pattern

A description that leads with behavior instead of the trigger forces the agent
to infer the trigger from what the command does:

```
Bad:  "Compiles the project, runs the test suite, and reports failures."
Good: "Use when you need to verify the project builds and tests pass before
       merging a change."
```

## 2. Bad/good example pairs

### The rationale

Agents are demonstrably good at few-shot transfer from concrete example pairs.
A single bad/good pair encodes the boundary of what acceptable output looks like
more reliably than a paragraph of abstract rules, because it shows both the
wrong shape and the right shape side by side. Seed skills, commands, and agent
definitions with these pairs to encode taste at the point where the output is
produced.

### Canonical example

`content/agents/qa-engineer.md` (QA knowledge entries):

```
Good: `- [2026-03-30] timing: Wait 2s after navigation to /dashboard - React Query refetch completes async`
Bad:  `- [2026-03-30] timing: Page needs time to load`
```

The pair teaches three things at once: name the concrete cause (the async
refetch), name the concrete remediation (wait 2s after navigation), and never
hand-wave ("Page needs time to load").

### When to add a pair

Add a bad/good pair when an agent's output is consistently off in a specific
way - a failure mode you keep correcting in review. The pair replaces the
correction: it moves the taste boundary from "the reviewer says no" to "the spec
says no", so the agent can self-correct on the first pass. If the output is only
occasionally off, a single good example plus an abstract rule is enough; the
pair earns its space only when the miss is recurring.

## 3. Module-manifest requirement for new command files

New command files, and any other non-trivial file, must carry the
module-manifest header block. See `content/rules/module-manifest.md` for the
required fields (Purpose, Public API, Upstream dependencies, Downstream
consumers, Failure modes, Performance).
`content/commands/ds-failure-audit.md` is the reference example of a command
file with a complete manifest.

A new command is not done when its file is written. It must also be wired in:
registered in `bin/ds-help` (the full command inventory), and covered by the
docs update check in `content/commands/ds-update-agentic-engineering.md`
Step 3.5. `content/SKILL.md`'s Commands section is a curated subset - only a few
commands warrant prominent placement there, so add a command to it only when
that is the case. The two principles above apply to the command's description
during that wiring.
