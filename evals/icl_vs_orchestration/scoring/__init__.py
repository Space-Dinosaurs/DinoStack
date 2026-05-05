"""
Purpose: Scorer sub-package for the ICL-vs-orchestration eval harness.
         Provides per-dimension scorers implementing the 6-dimension Brief Q4
         rubric and the scorer registry that aggregates them.

Public API: see registry.py (load_registry, DimensionScore, TicketScore).

Upstream deps: stdlib; conditions/base.py (for artifact shapes).

Downstream consumers: runner.py, report.py.

Failure modes: individual scorer errors are caught by registry.py and
               returned as status="floored" with score=0.0 rather than
               propagating to the runner.

Performance: all scorers are purely computational (no I/O except diff parsing).
"""
