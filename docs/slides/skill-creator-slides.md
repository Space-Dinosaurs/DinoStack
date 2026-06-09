---
marp: true
theme: default
paginate: true
style: |
  section {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    background: #faf8f3;
  }
  section.lead {
    display: flex;
    flex-direction: column;
    justify-content: center;
    text-align: center;
    background: #faf8f3;
    color: #1a1a1f;
  }
  section.lead h1 {
    font-size: 2.5em;
    margin-bottom: 0.2em;
    color: #224466;
  }
  section.lead p {
    font-size: 1.2em;
    opacity: 0.85;
  }
  section.highlight {
    background: #faf8f3;
  }
  .columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5em;
    margin-bottom: 0.8em;
  }
  .columns-3 {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 1em;
    margin-bottom: 0.8em;
  }
  .card {
    background: white;
    border-radius: 12px;
    padding: 1.2em;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    border-left: 4px solid #b5451f;
  }
  .stat {
    font-size: 2.5em;
    font-weight: bold;
    color: #b5451f;
  }
  .label {
    font-size: 0.9em;
    color: #666;
    margin-top: 0.2em;
  }
  .callout {
    background: #faf0e8;
    border-left: 4px solid #b5451f;
    padding: 0.8em 1.2em;
    border-radius: 0 8px 8px 0;
    margin: 0.4em 0 0.8em 0;
  }
  blockquote {
    border-left: 4px solid #b5451f;
    padding-left: 1em;
    color: #555;
    font-style: italic;
  }
---

<!-- _class: lead -->

# The Skill Creator

How DinoStack's agents and skills were built - and how you can build your own

---

## What is the skill creator?

<style scoped>
  ul { font-size: 0.92em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.88em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

- A **built-in Anthropic skill** for Claude Code that creates other skills and agents
- Drives an iterative loop: draft a skill, test it, evaluate the output, improve, repeat
- Uses **subagents** for grading, blind comparison, and analysis - not just vibes
- Outputs a complete skill directory: `SKILL.md`, eval cases, bundled scripts, references
- The same tool that built the DinoStack agents is available to everyone

<div class="callout">
This is the tool that was used to build the agents in this protocol. It is not a template - it is a development framework with built-in evaluation and iteration.
</div>

---

<!-- _class: highlight -->

## The improvement loop

<style scoped>
  .columns { gap: 0.8em; margin-bottom: 0.8em; }
  .columns .card { padding: 0.5em 0.8em; font-size: 0.75em; line-height: 1.3; }
  .columns .card strong { display: block; margin-bottom: 0.15em; font-size: 1.05em; }
  .callout { font-size: 0.8em; padding: 0.4em 1em; margin-top: 0.4em; }
  h2 { margin-bottom: 0.4em; }
</style>

<div class="columns">
<div class="card">
<strong>1. Capture intent</strong>
What should the skill do? When should it trigger? What does good output look like?
</div>
<div class="card">
<strong>2. Write draft</strong>
SKILL.md with instructions, examples, edge cases. Scripts and references as needed.
</div>
<div class="card">
<strong>3. Create test cases</strong>
2-3 realistic user scenarios saved to evals.json. No assertions yet - just prompts.
</div>
<div class="card">
<strong>4. Run evals</strong>
Spawn with-skill and baseline runs in parallel. Capture timing, tokens, and output.
</div>
<div class="card">
<strong>5. Evaluate</strong>
Grader agent scores assertions. The operator can review or let the agent evaluate autonomously.
</div>
<div class="card">
<strong>6. Improve and repeat</strong>
Analyze patterns across runs, refine instructions, rerun. Usually 2-3 iterations.
</div>
</div>

<div class="callout">
Each iteration produces a measurable delta: pass rate, token cost, execution time. You know if the skill got better, not just different.
</div>

---

## Three evaluation agents - not just vibes

<style scoped>
  .columns-3 .card { padding: 0.7em 0.9em; font-size: 0.78em; line-height: 1.35; }
  .columns-3 .card strong { font-size: 1.05em; }
  .callout { font-size: 0.85em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

<div class="columns-3">
<div class="card">
<strong>Grader</strong><br/>
Evaluates assertions against outputs. Requires evidence, not surface compliance. Flags trivially-satisfied assertions and suggests missing coverage.
</div>
<div class="card">
<strong>Comparator</strong><br/>
Blind A/B comparison. Scores two outputs without knowing which skill produced them. Generates a task-specific rubric, picks a winner with reasoning.
</div>
<div class="card">
<strong>Analyzer</strong><br/>
Post-hoc analysis. Compares transcripts against instructions. Scores instruction-following 1-10. Identifies why the winner won and what to fix.
</div>
</div>

<div class="callout">
The grader catches regressions. The comparator catches bias. The analyzer tells you what to change. Together they close the loop without guessing.
</div>

---

## How DinoStack used it

<style scoped>
  ul { font-size: 0.9em; }
  ul li { margin: 0.25em 0; }
  .callout { font-size: 0.88em; padding: 0.5em 1em; margin-top: 0.5em; }
</style>

- Each named agent (investigator, architect, engineer, skeptic, etc.) was **drafted, tested, and refined** through the skill creator's eval loop
- Test cases exercised realistic scenarios - not toy examples
- The grader verified that agents returned structured output in the right format
- The comparator confirmed new versions were actually better than previous ones
- Description optimization tuned auto-triggering so the right agent fires for the right task

<div class="callout">
The agents didn't ship because they "seemed good." They shipped because they passed quantitative benchmarks and blind comparisons across multiple iterations.
</div>

---

## You can do this too

<style scoped>
  p { font-size: 0.85em; margin: 0.3em 0; }
  ol { font-size: 0.82em; }
  ol li { margin: 0.15em 0; }
  .callout { font-size: 0.82em; padding: 0.4em 1em; margin-top: 0.4em; }
</style>

The skill creator is available to every Claude Code user. To build your own skill or agent:

1. Start Claude Code and say **"create a skill that does X"** - the skill creator activates
2. Describe what you want - the skill creator drafts `SKILL.md` and test cases
3. **Review the evals** or let the agent evaluate autonomously
4. The skill creator **iterates** - rewriting instructions, rerunning evals, benchmarking
5. After 2-3 rounds, you have a tested, benchmarked skill with a tuned trigger description

Agents can also invoke the skill creator to build new agents and skills on demand - the same evaluation rigor applies whether a human or an agent initiated the build.

<div class="callout">
The bar is not "it works once." The bar is: it passes assertions, wins blind comparisons, and generalizes beyond the test cases.
</div>

---

<!-- _class: lead -->

# Build skills that pass, not skills that seem fine

Structured evaluation. Blind comparison. Measurable improvement.

github.com/Space-Dinosaurs/agentic-engineering
