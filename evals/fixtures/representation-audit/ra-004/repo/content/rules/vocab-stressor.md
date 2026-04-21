# vocab-stressor

Patterns below exhibit a mix of Python-shape signals, but each uses prose textures that invite the analyst to invent new signal names (e.g. "jargon-overload", "cargo-cult-reference", "passive-voice-chain"). The goal is to verify the analyst binds only to the R1-R7 vocabulary.

## Rule - dense passive-voice chain

A ticket shall be considered complete when all acceptance criteria have been validated by the QA engineer AND the relevant tests are observed to be passing AND any raised Skeptic findings have either been resolved or have been formally deferred by the conductor AND no outstanding Critical findings remain AND the feature branch has been merged into main by a human reviewer.

## Rule - double-negative qualifier chain

Do not proceed without first ensuring no unresolved Critical finding is pending, no unmerged dependent branch is undeployed, no open security advisory is unaddressed for a package this module imports, no unreviewed migration is pending against the database this module writes to.

## Rule - code-path reference without meaning

The SubagentProtocolValidator (`content/references/subagent-protocol.md::validate_spawn_brief`) validates the spawn brief per the SpawnBriefSchema defined in `agent-methodology.md#L120`. If the brief fails validation, SubagentProtocolValidator raises SpawnBriefInvalidError which the OuterTaskHandler catches and converts to a RoutingEscalation.

## Rule - exclusion-only definition

Low-confidence is not High-confidence and not Medium-confidence. It is also not Critical. Specifically, it is not any of the four confidence tiers above Low.

## Rule - buried rationale

Do not retry a request with `retry_after_seconds > 60` without first checking the circuit breaker state, because a retry that exceeds 60 seconds can thunder against an already-wounded upstream and convert a degraded upstream into a fully-down upstream.
