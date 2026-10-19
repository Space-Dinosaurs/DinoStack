<!-- Describe the *why* in addition to the *what*. Link related issues. -->

## Summary

<!-- One or two sentences on the motivation and the change. -->

## North Star alignment

<!-- Required when this PR touches a methodology-shaping path. See the canonical trigger
     list in content/agents/skeptic.md step 3.6 - keep this comment in sync with that list.
     A trivial change (typo, formatting, whitespace, comment-only) on a methodology-shaping
     path may satisfy this section with a one-line answer, e.g. "N/A - typo/formatting only,
     no methodology-behavior change." A full pillar/trade-off answer is only expected when the
     diff actually changes behavior. For PRs that touch no methodology-shaping path at all,
     write "N/A". -->

- Pillar(s) advanced (see docs/overview/vision.md):
- Trade-off or pillar this could regress, if any:

## Review rigor

<!-- Required for all PRs. Fill in Brief/Plan path (if any), Skeptic rounds
     completed + tier, and the final findings summary. Trivial-risk changes
     (single Worker, no Skeptic per AE risk classification) may write
     "N/A - Trivial risk, no Skeptic per AE risk classification" instead.
     Keep this comment in sync with .github/workflows/pr-review-rigor.yml. -->

- Brief / Plan path:
- Skeptic rounds (tier):
- Findings summary:

<!-- ds-delivery-record:v1:start -->
## Delivery record (provisional)

Owner: <actual PR owner>. Remote SHA binding follows PR creation.
- Human approval: PENDING — owner must establish actual approval policy/evidence.
- Protocol review: PENDING — owner must collect applicable review evidence/exemptions.
- CI: PENDING — owner/platform must observe current checks.
- QA: PENDING — owner must collect scoped QA evidence/exemptions.
- Human UAT: PENDING — owner must establish request/policy; N/A if neither requires it.

Procedure: content/references/delivery-record.md
<!-- ds-delivery-record:v1:end -->

## Related issues

<!-- e.g. Closes #123, Refs #456 -->

## Checklist

- [ ] DCO sign-off on every commit (`git commit -s`)
- [ ] Affected adapters declared
- [ ] Before/after transcript included for agent-behavior changes
- [ ] `install.sh` re-run locally and behavior verified
- [ ] Tests/lint passing
- [ ] Docs updated if behavior changed

## Affected adapters

<!-- Tick all that apply. -->

- [ ] Claude Code
- [ ] Cursor
- [ ] Codex CLI
- [ ] Gemini CLI
- [ ] Kimi Code
- [ ] OpenCode
- [ ] Pi coding agent
- [ ] Pi oh-my-pi
- [ ] Hermes
- [ ] OpenClaw
- [ ] VS Code Copilot
- [ ] None (methodology / docs only)

## Before/after transcript

<!-- For agent-behavior changes, paste a short before/after transcript. Omit if not applicable. -->
