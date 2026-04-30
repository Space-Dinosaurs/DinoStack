## Task Decomposition

**One agent, one task, one prompt.** The conductor breaks work into atomic units before spawning Workers. A focused agent is a correct agent - Workers should not do epics alone.

**Decompose implementation, not review.** Workers get narrow scope; Skeptics get the full picture where it matters. The orchestration-planner identifies unit boundaries and dependencies; the conductor applies the following rules to the planner's output:
- **Independent elevated units (planner-identified):** each gets its own Skeptic (small diff, high signal)
- **Interdependent elevated units (planner-identified):** separate focused Workers, but one Skeptic reviewing the combined diff - the integration Skeptic replaces per-unit Skeptics, not layers on top
- **Low-risk units:** direct action with self-check (no Skeptic) - e.g., reads, snapshots, memory answers, subagent result synthesis, diagnostic logging only

**Before spawning workers: run the orchestration-planner.** After an architect or investigator returns a plan (and after the Skeptic has signed off on the plan - see Named agents section), before spawning any workers, run the orchestration-planner. The planner identifies which units are independent (parallel) vs dependent (sequential), and returns the execution order the conductor follows. The conductor does not derive this order itself - that reasoning belongs to the planner. Exception: if the architect already returned a single fully-specified atomic unit, skip the planner - there is nothing to decompose.
