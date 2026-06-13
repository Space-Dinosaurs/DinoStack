---
marp: true
theme: default
paginate: true
style: |
  @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;600;700;800;900&family=Nunito+Sans:wght@400;600;700&family=JetBrains+Mono:wght@300;400;500&display=swap');
  section {
    font-family: 'Nunito Sans', system-ui, sans-serif;
    background-color: #02050C;
    background-image:
      radial-gradient(800px 480px at 14% -10%, rgba(24,224,255,0.12), transparent 60%),
      radial-gradient(680px 420px at 100% 0%, rgba(176,107,255,0.10), transparent 58%),
      radial-gradient(720px 560px at 70% 115%, rgba(24,224,255,0.05), transparent 60%);
    color: #eaf1fb;
    color-scheme: dark;
  }
  h1, h2, h3, h4, h5, h6 {
    font-family: 'Orbitron', system-ui, sans-serif;
    color: #ffffff;
    letter-spacing: 0.01em;
  }
  h1 { text-shadow: 0 0 30px rgba(24,224,255,0.35); }
  h2 {
    color: #eaf1fb;
    text-shadow: 0 0 18px rgba(24,224,255,0.20);
    border-bottom: 1px solid rgba(255,255,255,0.12);
    padding-bottom: 0.18em;
  }
  strong { color: #ffffff; }
  a { color: #18E0FF; text-decoration: none; }
  section.lead {
    display: flex;
    flex-direction: column;
    justify-content: center;
    text-align: center;
    color: #eaf1fb;
  }
  section.lead h1 {
    font-size: 2.6em;
    margin-bottom: 0.2em;
    color: #ffffff;
    text-shadow: 0 0 38px rgba(24,224,255,0.45);
  }
  section.lead p {
    font-size: 1.2em;
    color: rgba(234,241,251,0.78);
  }
  section.highlight {
    background-color: #02050C;
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
    background: #0A1020;
    border: 1px solid rgba(255,255,255,0.10);
    border-left: 4px solid #18E0FF;
    border-radius: 12px;
    padding: 1.2em;
    box-shadow: 0 2px 14px rgba(0,0,0,0.45), 0 0 22px rgba(24,224,255,0.06);
    color: #eaf1fb;
  }
  .stat {
    font-size: 2.5em;
    font-weight: bold;
    color: #18E0FF;
    font-family: 'Orbitron', system-ui, sans-serif;
  }
  .label {
    font-size: 0.9em;
    color: #9bb0cc;
    margin-top: 0.2em;
  }
  .callout {
    background: rgba(24,224,255,0.06);
    border-left: 4px solid #18E0FF;
    padding: 0.8em 1.2em;
    border-radius: 0 8px 8px 0;
    margin: 0.4em 0 0.8em 0;
    color: #eaf1fb;
  }
  blockquote {
    border-left: 4px solid #18E0FF;
    padding-left: 1em;
    color: rgba(234,241,251,0.78);
    font-style: italic;
  }
  code {
    font-family: 'JetBrains Mono', monospace;
    background: rgba(255,255,255,0.06);
    color: #9be9ff;
    padding: 0.1em 0.35em;
    border-radius: 4px;
  }
  pre {
    background: #04070F;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 8px;
    color: #eaf1fb;
  }
  pre code {
    background: transparent;
    color: #eaf1fb;
    padding: 0;
  }
  table {
    border-collapse: collapse;
    background: transparent;
  }
  table tr {
    background: transparent;
  }
  table tr:nth-child(2n) {
    background: rgba(255,255,255,0.03);
  }
  th, td {
    border: 1px solid rgba(255,255,255,0.12);
    padding: 0.4em 0.8em;
  }
  th {
    background: rgba(255,255,255,0.05);
    color: #ffffff;
    font-family: 'Nunito Sans', system-ui, sans-serif;
  }
  td {
    color: #eaf1fb;
  }
  section::after {
    color: #6a7c97;
  }
  mark {
    background: rgba(233,181,33,0.22);
    color: #ffffff;
  }
  kbd {
    background: rgba(255,255,255,0.08);
    color: #eaf1fb;
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 4px;
  }
  hr {
    background-color: rgba(255,255,255,0.12);
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

- A **DinoStack-provided skill** (installed by the adapters) that creates other skills and agents - not a built-in Anthropic platform feature
- Drives an iterative loop: draft a skill, test it, evaluate the output, improve, repeat
- Uses **subagents** for grading, blind comparison, and analysis - not just vibes
- Outputs a complete skill directory: `SKILL.md`, eval cases, bundled scripts, references
- The same tool that built the DinoStack agents is available to every DinoStack user

<div class="callout">
This is the tool that was used to build the agents in this protocol. It is not a template - it is a development framework with built-in evaluation and iteration. It ships with the DinoStack adapters, not with Claude Code itself.
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

The skill creator is available after DinoStack is installed. To build your own skill or agent:

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

github.com/Space-Dinosaurs/DinoStack
