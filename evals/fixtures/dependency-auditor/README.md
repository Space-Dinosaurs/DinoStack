# dependency-auditor fixtures

This directory holds the dependency-auditor component eval corpus. Five
fixtures covering the main axes the scorer grades (CVE recall, license
findings, maintenance / typosquat findings, scan coverage, report
structure + CVE-from-memory hallucination detection).

## What this measures vs. what it does NOT

The production dependency-auditor agent has `Bash` access and runs
`npm audit --json`, `pip-audit --format=json`, `cargo audit --json`,
`npx license-checker`, `npm view <pkg>`, etc. live. The eval environment
is Tier 1 read-only: NO `Bash`, NO network, NO live registry. Every
fixture ships a `repo/` subtree with real `package.json` / lockfiles /
pyproject.toml / Cargo.toml plus pre-captured tool JSON under
`repo/.audit/*.json`. The eval prompt inlines those manifests and every
audit payload, and tells the agent to treat the staged JSON as its
authoritative tool output - source-fallback mode.

**This DOES measure:**
- Dependency Audit Report structural fidelity (`## Dependency Audit
  Report` title, `### Summary` / `### Findings` / `### Upgrade plan` /
  `### Open questions` / `### Scan gaps` sections, `#### Critical` /
  `#### Major` / `#### Minor` severity sub-blocks).
- CVE recall: does the agent surface every CVE present in the staged
  `.audit/*.json` under the correct severity, with a correct
  remediation hint?
- License compliance: does the agent flag blocked licenses (GPL-family
  in a proprietary project) when `known_constraints` specifies the
  policy?
- Maintenance / typosquat discipline: does the agent AVOID calling a
  legitimate dependency a typosquat on a false-positive-trap fixture?
- Scan coverage: does the agent correctly name the ecosystems scanned
  and the tools run, including flagging a missing scanner in `### Scan
  gaps`?
- **CVE-from-memory hallucination:** the scorer cross-checks every CVE
  / GHSA ID the agent emits against the union of IDs present in the
  fixture's `repo/.audit/*.json`. An ID the agent emits that is NOT in
  the staged audit corpus forces the report-structure axis to 0.0.
  This is the load-bearing honesty check the role doc mandates
  ("Never state a CVE from memory").

**This does NOT measure:**
- Live `npm audit` / `pip-audit` / `cargo audit` / `govulncheck`
  execution or their registry round-trips.
- Live `npm view <pkg>` calls for maintenance signals (last release
  date, deprecated flag, weekly download counts). The role doc
  references these explicitly; the eval can approximate them only via
  pre-captured `.audit/npm-view-*.json` payloads, and no fixture here
  tries to exercise the full maintenance-signal axis against a live
  registry.
- The ecosystem-detection phase in wall-clock terms (Phase 1 of the
  role doc). The prompt states the detected ecosystem for the agent up
  front because the fixture author knows what's seeded; this removes a
  detection-failure noise source but also means edits to the
  detection table in the role doc may not move fixture scores.

**Bash-denied proxy caveat:** maintainer edits to
`content/agents/dependency-auditor.md` that change Bash-command
specifics (exact flag names, output-parsing invariants) may not move
any fixture score because the agent never runs those commands. The
eval discriminates on report structure, CVE recall against staged
JSON, license reasoning, and hallucination discipline. This is the
same category of proxy as the qa-engineer eval (source-fallback mode
for a browser-dependent agent) and the debugger eval (static evidence
bundle for a repo-dependent agent). See `evals/LEARNINGS.md` for the
broader pattern.

## Fixtures

| ID     | Scope         | Discrimination axis                                           |
|--------|---------------|---------------------------------------------------------------|
| da-001 | full_audit    | Transitive Critical/High CVE (qs < 6.9.7 via express 4.17.1). CVE recall. |
| da-002 | full_audit    | GPL-3.0 license in proprietary project (readline-sync). License axis. BELOW-CEILING. |
| da-003 | full_audit    | Clean control: up-to-date Python project, no advisories. Ceiling / FP discipline. |
| da-004 | full_audit    | Scan gap: Cargo.lock present, no cargo-audit staged. Scan_coverage + gap-reporting. BELOW-CEILING. |
| da-005 | upgrade_diff  | False-positive trap: adds `lodash-es` (legitimate ES-module lodash). Typosquat-FP discipline. BELOW-CEILING if overcalled. |

## Caveats

1. All `.audit/*.json` payloads are hand-authored to mirror the real
   shape of each tool's JSON output. Advisory IDs and CVSS scores in
   da-001 match the real `qs` prototype-pollution advisory
   (GHSA-hrpp-h998-j3pp / CVE-2022-24999) so the agent's cross-
   reference against the staged corpus succeeds on the real ID.
2. npm classifies the `qs` advisory as `high`, not `critical`. The
   scorer's CVE recall axis combines Critical+Major sections, so the
   agent may file the finding under either severity and still score on
   recall. The role doc's severity classification is a judgment call
   the agent makes; the eval does not force one interpretation.
3. da-002's `known_constraints` field is the ONLY signal that a GPL
   finding is blocking in this project. Without that field the agent
   would be within its rights to log GPL as informational (Minor).
   Per the role doc: "Apply any license constraints from the spawn
   prompt. If no constraints were given, flag Blocked and Unknown
   licenses as findings."
4. da-004 deliberately has no `.audit/cargo-audit.json`. The agent
   must detect the gap from the manifest/lockfile mismatch (Cargo.lock
   present, no staged cargo-audit output) and record it in
   `### Scan gaps`. The scan_coverage axis credits ecosystems that
   appear in the report's `Ecosystems scanned:` or `Tools run:` header
   line; a report that includes cargo in `Scan gaps` but omits it
   from the header line still gets structural credit but not
   scan_coverage credit - this is intentional discrimination.
5. da-005 ships `.audit/npm-view-lodash-es.json` with real-shaped
   metadata (published 2015, 10M+ weekly downloads, linked github
   repo under `lodash/lodash`). Per the role doc, a package with a
   repository link, established publish date, and high download
   counts is NOT a typosquat candidate even if the name resembles
   `lodash`. Flagging it Major is a false positive the scorer
   penalizes on the maintenance axis.

## Proxy limitations (documented, not bugs)

- The agent has no live network, so Phase 4 (maintenance signals via
  `npm view <pkg> time.modified` / `deprecated` / downloads) is only
  exercised when a fixture pre-captures the relevant payload (da-005
  does; da-001..da-004 do not). A regression that weakens Phase 4
  language in the role doc may not move any fixture's score in the
  current corpus.
- The agent has no access to real-world typosquat registries or
  security advisory databases beyond the staged `.audit/*.json`. The
  hallucination floor in the scorer is an indirect proxy for the
  "do not state a CVE from memory" rule: it penalizes IDs that are
  not in the staged corpus, but it cannot verify that a cited CVE is
  semantically accurate given its advisory text.
