# template-rules

Rules with embedded Execution Contract templates and tabular structure. These must NOT trip R-signals - templates and tables are load-bearing structural formats, not prose.

## Execution Contract template (do NOT rewrite)

Every Worker spawn includes the following 5-field contract:

- outputs: what artifact the run produces
- budget: advisory tool-call ceiling
- tool_scope: tool categories expected for this task
- completion_conditions: acceptance criteria
- output_paths: specific paths the run writes to

## Routing decisions (table - do NOT rewrite)

| Signal                                 | Route                  | Next agent       |
|----------------------------------------|------------------------|------------------|
| Major finding open                     | re_enter_loop          | engineer         |
| All findings resolved                  | proceed_to_next_phase  | null             |
| Iteration cap reached                  | escalate_cap_reached   | null             |
| Convergence failure                    | escalate_convergence   | null             |

## Rule - one real qualifier chain worth rewriting (R1 candidate)

The conductor must not spawn a new Worker to address a Major finding if the iteration count has already reached the cap AND a Skeptic re-review has not yet been run since the last fix pass AND the finding was not raised in the previous round AND the finding is not a regression of an already-resolved finding, in which case the conductor escalates instead of spawning.

## Rule - one every-task qualifier repetition (R6 candidate)

The "no commits before sign-off" rule applies to every Worker. The "no commits before sign-off" rule also applies to every Debugger. The "no commits before sign-off" rule applies to every Architect. Each agent observes the same commit gate; the repetition is cross-document in the real corpus but here is within-document - R6 candidate.
