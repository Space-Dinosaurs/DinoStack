# security-auditor component eval

Measures whether `content/agents/security-auditor.md` produces a
threat-model-driven audit with correct severity-keyed findings, CWE
citations, file:line locations, remediation guidance, and OWASP
coverage.

## What this measures

- Does the auditor emit the mandated 7-sub-section format (Threat model,
  Critical/High/Medium/Informational findings, Positive controls, OWASP
  Top 10 coverage, Dependency scan)?
- Does it catch the expected vulnerabilities at the expected severity,
  without over-flagging (FP discipline)?
- Does each true-positive finding carry a CWE-NN identifier and a
  `file.ext:line` citation?
- Does each TP finding carry remediation keywords tied to the
  vulnerability class (parameterize, sanitize, allowlist, etc.)?
- Does the OWASP coverage section name the expected categories
  (A01/A03/etc.) by short code?
- Is the Critical findings section coherent - populated when a Critical
  is expected, silent when none is expected?

## What this does NOT measure

- Prose quality of the threat-model section. The scorer checks
  structural presence of the header only; it does not judge the two
  sentences inside.
- Depth of the Dependency scan. Fixtures do not seed package manifests;
  any dependency finding is out of scope for current corpus.
- Positive-controls accuracy. The section is required to be present by
  the format gate but is not scored on content.

## Invocation path

Tier 1 two-level Task spawn: an outer `claude -p` session invokes
`subagent_type="security-auditor"` with the prompt built by
`build_security_auditor_prompt`. The subagent inherits its role from
`content/agents/security-auditor.md`.

## Bash-in-Tier-1 soft claim

`content/agents/security-auditor.md` declares
`tools: Read, Glob, Grep, Bash` in its frontmatter. Bash is granted in
production so the agent can grep the codebase aggressively for
vulnerability patterns. Tier 1 isolation does NOT grant Bash to
subagents - the outer session's `allowed_tools` scopes what any spawned
subagent can actually invoke, and Tier 1 is read-only (Read, Grep,
Glob, Task).

Implication: what this eval measures is a security-auditor with the
Bash tool **soft-withdrawn**. The prompt builder acknowledges this
explicitly and inlines every code file with line numbers so the
auditor can cite `file:line` accurately without running grep. A
maintainer change to the agent's Bash usage patterns (e.g. new
recommended grep invocations) will not move fixture scores because the
tool is absent. This is the same proxy class as debugger's
Bash-withheld caveat.

## Isolation

Tier 1: read-only worktree, no Bash, no Write, no Edit,
`default` permission mode. The subagent cannot modify files or
exfiltrate network.

## OVERFITTING-RULE pointer

See `evals/OVERFITTING-RULE.md`. Common temptations on this component:

- Adding a synonym map so "Cross-Site Scripting" counts without
  "XSS". Don't. Enforce vocabulary at the fixture keyword layer; the
  keyword list on each expected finding is where flexibility lives.
- Editing `security-auditor.md` to mention one specific vulnerability
  class because a single fixture misses it. Don't - if the change is
  worth making, it would survive the fixture being deleted.
- Lowering the Critical-FN penalty so sa-001 scores non-zero when the
  SQL injection is missed. Don't - a Critical miss is the defining
  failure mode this eval guards against.
