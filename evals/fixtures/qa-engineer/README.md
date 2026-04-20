# qa-engineer fixtures

This directory holds the qa-engineer component eval corpus. Five fixtures
covering the verdict space (PASS, FAIL x2, PARTIAL, BLOCKED) and the main
discrimination axes the scorer grades.

## What this measures vs. what it does NOT

The production qa-engineer interacts with a real browser (agent-browser
or Playwright), a live dev server, a test runner, and an auth system.
The eval environment has NONE of these. Each fixture ships a synthetic
**observability.md** bundle that stands in for what a browser session
plus console capture plus network log plus test-run output would have
produced. The eval prompt tells the agent to treat that file as its
authoritative capture - source-fallback mode.

**This DOES measure:**
- QA Verification Report structural fidelity (## Result header, numbered
  ### N. criterion blocks with Result/Method/Evidence/Expected/Actual/
  Location fields).
- Verdict accuracy against the observed state described in the bundle.
- Per-criterion Result token accuracy.
- Evidence specificity - concrete DOM content, file paths, element refs,
  class tokens, or hand-waving.
- Runtime-fallback discipline - runtime_required ACs correctly marked
  SKIPPED/SKIPPED-BLOCKED when the observability bundle shows they
  cannot be verified, rather than silently source-verified.
- Blocking-issue content - does the report surface the right root-cause
  keywords in the Blocking Issues section?

**This does NOT measure:**
- Real browser interaction, snapshot reading, or screenshot capture.
- Real dev server start/health checks.
- Real test runner execution.
- Real auth handling (cookie minting, OAuth, dev bypass).
- Real qa.md knowledge-entry appending.

A maintainer edit to browser-specific workflow language in
`content/agents/qa-engineer.md` that does not change the report shape
or the PASS/FAIL/PARTIAL/BLOCKED decision rules may not move fixture
scores. That is a property of the proxy, not a scorer bug - the same
category as the conductor eval's session-level-routing proxy and the
/wrap eval's session-transcript proxy (see `evals/LEARNINGS.md`).

## Fixtures

| ID     | Verdict | Discrimination axis                               |
|--------|---------|---------------------------------------------------|
| qa-001 | PASS    | Clean dashboard change, all ACs verifiable. Ceiling. |
| qa-002 | FAIL    | Diff claims 5 nav items, only 4 added. Blocking-issue discrimination. |
| qa-003 | PARTIAL | Admin route auth-walled, one static AC verifiable, two runtime ACs blocked. |
| qa-004 | FAIL    | Form renders cleanly but submit returns 500 - passing-for-wrong-reason trap. |
| qa-005 | BLOCKED | Runtime-only payment flow, no auth, no qa.md, no bypass documented. |

## Caveats

1. observability.md bundles are synthetic, not recorded from real runs.
2. qa-003 deliberately has AC 1 as STATIC (class tokens, source) and
   ACs 2-3 as RUNTIME. Expected PARTIAL relies on the agent correctly
   labeling AC 1 source-verified while marking 2-3 SKIPPED-BLOCKED.
3. qa-004 is the passing-for-wrong-reason trap: form renders (2 ACs
   trivially pass by DOM) but submit path 500s in the network log.
4. qa-005 is the honest-BLOCKED case. Padding PARTIAL with trivial
   login-page-renders checks violates the hard rule in
   `content/agents/qa-engineer.md` "Auth handling".
