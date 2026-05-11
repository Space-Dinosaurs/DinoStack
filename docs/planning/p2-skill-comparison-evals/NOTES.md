# Orchestration notes

`orchestration.jsonl` is intentionally empty at Plan-assembly time. The orchestration-planner runs after Plan sign-off and writes one JSONL line per unit (with `unit_slug`, dependencies, `merge_order`, `skeptic_strategy`, risk class) per `content/sections/09-task-decomposition.md`. The architect-plan.md "Per-unit decomposition" section is the input the planner consumes.
