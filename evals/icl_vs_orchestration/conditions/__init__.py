"""
Purpose: Condition runner sub-package. Each condition implements the
         Condition Protocol from base.py and produces a ConditionResult.

Public API: see base.py (TicketInput, ConditionResult, ConditionArtifacts,
            Condition Protocol).

Upstream deps: base.py, ae_orchestrated/, icl_baseline.py.

Downstream consumers: runner.py.

Failure modes: each condition captures its own errors into ConditionResult.status
               rather than propagating; caller continues to the next ticket.

Performance: dominated by LLM invocation.
"""
