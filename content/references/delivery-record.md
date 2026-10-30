<!--
Purpose: Canonical SHA-bound PR evidence and publication procedure.
Public API: version 1 input to bin/ds-pr-delivery-record; DELIVERY_RECORD_INPUT
            names the assessment JSON in executable calling examples.
Upstream deps: actual project/GitHub policy, review findings, CI, QA and human evidence.
Downstream consumers: ticket Phases 9/11d/11e/12, universal PR workflow,
                      timeout queue, sibling sweep, PR template.
Failure modes: missing evidence stays pending; failed publication blocks agent
               merge/new queue. GitHub has no body CAS; no background watcher.
Performance: one bounded publication per creation/head change/merge request.
-->

# PR delivery records

Every team PR carries separate human approval, protocol review, CI, QA and human
UAT declarations at the live remote `headRefOid`. The record is declared evidence,
not independent proof of execution. This procedure catches a late push or rebase
being merged under evidence from an earlier head. It remains a permanent
publication floor; it introduces no GitHub required check or approval policy.

## Collect and assess

At PR creation include the provisional section below, then immediately collect
and publish a SHA-bound provisional record after obtaining the PR number. For
ticket flows use that ticket's keyed loop state, final findings log and QA
artifacts. Preserve the three `## Review rigor` labels: `Brief / Plan path`,
`Skeptic rounds (tier)`, `Findings summary`. Refresh their actual values when
collecting final evidence. Missing logs mean unknown/pending, never zero findings.
Valid Trivial/Low review and QA exemptions, and the single-review route's non-UI
QA exemption, remain valid with concrete reasons.
Keep the populated Review rigor section separate from the managed block.
The advisory `pr-review-rigor.yml` check validates text presence only; its success
does not prove execution, SHA coverage or evidence quality.

Collect the five checks at the current remote SHA, not local HEAD. Each scope
names actual checks/scenarios, their limitations and required follow-up. A local
artifact needs a substantive summary in the public body; label its locator local
and unavailable remotely. Screenshots substantiate only what they actually show.
Review evidence includes round/tier, findings and unresolved exceptions. Preserve
existing non-Critical cap and Minor-fix exceptions with their actual authority;
Critical findings cannot be waived. Pending work always names who acts next and
what they must do. Browser/agent testing is QA. UAT PASS identifies the actual
human who accepted named scenarios. If UAT was neither requested nor required,
use N/A with that applicability reason; otherwise leave it pending its human owner.

Discover actual platform approval requirements and project protocol separately.
`policy.source` cites where authority was established. Failed discovery means an
explicit unknown explanation, never “no approval required.” A human approval PASS
identifies the actual human, actual reviewed SHA and evidence; an agent's Skeptic
sign-off does not fulfil GitHub APPROVED. The publisher independently observes
GitHub's aggregate `reviewDecision` (empty => NONE, retrieval failure => UNKNOWN).
That observation neither grants approval nor proves the declared human checked
the current head. Honour configured requirements. An existing explicit project
admin authorization may permit autonomous merge; record its actual authority and
whether override is intended or already exercised in `policy.override.reason`.
Refresh after an observed bypass when possible. Never invent authority for
another project or impose a new human prerequisite on an already authorized path.
This record does not change live settings, required CI or the existing review/QA
floors and INCONCLUSIVE acceptance rules.

## Version 1 input

Run `ds-pr-delivery-record --repo OWNER/REPO --pr NUMBER --input FILE`.
Its permanent compatibility symlink invokes the same helper. The JSON object
contains `version: 1`, full lowercase 40-character `head_sha`, `record_owner`,
`risk` (Trivial, Low, Elevated), `policy`, and `checks`.

`policy` always contains nonempty `source`, `github_requirement`,
`protocol_requirement` (actual requirements or explicit unknown explanations),
`github_review_decision` (APPROVED, CHANGES_REQUESTED, REVIEW_REQUIRED, NONE,
UNKNOWN; overwritten with the live observation), and `override` (null or the
waiver object below).

`checks` has exactly `human_approval`, `protocol_review`, `ci`, `qa`, `uat`.
Each contains all these fields:

| Field | Meaning |
|---|---|
| result | PASS, FAIL, PENDING, INCONCLUSIVE, N/A, WAIVED |
| scope | Nonempty actual scope/scenarios; WAIVED scope names the declared head |
| coverage | EXACT, DELTA_ASSESSED, STALE, UNKNOWN |
| evidence_sha | Actual execution/review SHA, or null when not executed/unknown |
| evidence | Array of `{locator, visibility, summary}`; visibility public or local |
| reason | Concrete applicability, uncertainty, waiver or next-action reason; otherwise null |
| pending_owner | Actual unfinished-work owner; otherwise null |
| waiver | Null except WAIVED; object `{authorized_by, authority, evidence, reason}` |

`performed_by` is optional except PASS requires an actual actor. Human approval
and UAT identify humans, not the recording agent. `performed_at` is optional;
never invent a timestamp. Evidence summaries must substantiate the claimed scope.
Waiver and override evidence arrays must be nonempty and cite existing authority;
recording authority grants none.

PASS requires nonempty evidence, actual actor, scope and execution SHA. FAIL needs
evidence, reason and pending owner; use the execution SHA if known. PENDING and
INCONCLUSIVE need reason and pending owner; include attempted evidence if
available, and leave SHA null if never executed. N/A requires an applicability
reason, null execution SHA, owner and waiver, and EXACT applicability assessment
at this head. WAIVED requires reason and complete waiver, and may have null
execution SHA. Non-WAIVED checks always have null waiver.

Coverage is independent of historical result. After a head change retain PASS
and its original evidence SHA but mark STALE until rerun or explicitly assessed.
STALE/UNKNOWN always have reason/next action and owner; they are effectively
pending coverage and cannot satisfy an applicable required merge/queue check.
EXACT evidence uses the current head. DELTA_ASSESSED requires a nonempty
`coverage_transitions` array (otherwise optional, default `[]`): each entry has
`from_sha`, `to_sha`, `assessed_by`, nonempty evidence array and reason. The
continuous chain starts at evidence_sha and ends at head_sha. Do not relabel old
evidence with a new execution SHA.

For metadata-only deltas, compare both exact SHAs and document why each affected
check remains applicable. Behavioral deltas follow existing review/QA rules;
rebases include base-context and conflict assessment. Unknown comparisons stay
pending. An evidence SHA is not proof that the intervening changes were assessed.

Example pending check (repeat for all five checks with their actual scopes):

```json
{"result":"PENDING","scope":"required CI at remote head","coverage":"UNKNOWN",
 "evidence_sha":null,"evidence":[],"reason":"wait for platform checks",
 "pending_owner":"PR owner and GitHub CI","waiver":null}
```

Bad: “QA PASS at new SHA” copied from an earlier browser run.
Good: “QA PASS at original SHA, STALE; PR owner must assess the rebase before queue.”

## Publish and consume

The managed block uses `<!-- ds-delivery-record:v1:start -->` and
`<!-- ds-delivery-record:v1:end -->`. Only that span is replaced. User prose,
North Star, QA Evidence and Review rigor remain outside it. Malformed or duplicate
markers fail visibly. The publisher fetches the remote head/body, observes review
decision, rereads before editing and permits one fresh-body rebuild if the body
changed, then fails if contention continues. It uses `gh pr edit --body-file`
and reads back both head and body. No GitHub compare-and-swap exists: an
unobserved simultaneous edit can still be lost. A racing record remains
attributable to the SHA printed inside it; no future-head guarantee is made.

Exit 0 means successful publication/readback at requested remote SHA. Exit 1 is
validation/API/publication/readback failure; 2 is observed head movement. JSON
stdout always includes `published_sha`: full requested SHA on success, null on
failure, plus status, PR URL and observed SHA. Work can continue after failure,
but agent merge/new queue must wait for resolved assessment and successful
publication. Use the exit status AND validated published_sha, never a fresh query,
observed_sha or local HEAD as a substitute. Prepare `DELIVERY_RECORD_INPUT` anew
from current evidence immediately before this source block:

```bash
# @harness:delivery-record-publish
DELIVERY_PUBLISHED_SHA=""
if DELIVERY_PUBLICATION=$(ds-pr-delivery-record --repo "$GH_REPO" --pr "$PR_NUMBER" --input "$DELIVERY_RECORD_INPUT"); then
  DELIVERY_PUBLISHED_SHA=$(printf '%s' "$DELIVERY_PUBLICATION" | jq -er '.published_sha | select(type == "string" and length == 40 and test("^[0-9a-f]{40}$"))') || DELIVERY_PUBLISHED_SHA=""
fi
```

Every immediate merge or new auto-merge/queue request, including authorized
`--admin` paths and sibling requeue, must use that successful publication cycle's
SHA as `gh pr merge --match-head-commit "$DELIVERY_PUBLISHED_SHA"` along with
existing authorized flags. No request if the SHA is empty. If publication/request
fails or the head mismatches, reassess affected evidence/policy, republish and
retry with the newly published SHA. Never retry with only a fresh queried SHA or
omit the guard. This binds acceptance of the request, not later external pushes
to an already accepted queue. CI may be PENDING in the normal GitHub queue with
owner/platform dependency; required checks remain authoritative. Resolve other
applicable required checks under existing authority before requesting merge.

Universal/ad-hoc and sibling owning flows use the same publication block above,
then this request block. Set `DELIVERY_MERGE_MODE` to immediate, auto, or admin
only under the existing project authorization; admin means an immediate authorized
bypass and must have its intended override recorded in policy first.

```bash
# @harness:delivery-record-merge
if [ -n "$DELIVERY_PUBLISHED_SHA" ]; then
  case "$DELIVERY_MERGE_MODE" in
    immediate) gh pr merge "$PR_NUMBER" --repo "$GH_REPO" --match-head-commit "$DELIVERY_PUBLISHED_SHA" --squash --delete-branch ;;
    auto) gh pr merge "$PR_NUMBER" --repo "$GH_REPO" --match-head-commit "$DELIVERY_PUBLISHED_SHA" --squash --delete-branch --auto ;;
    admin) gh pr merge "$PR_NUMBER" --repo "$GH_REPO" --match-head-commit "$DELIVERY_PUBLISHED_SHA" --squash --delete-branch --admin ;;
  esac
fi
```

## Head changes and queued work

Refresh after every owner push/rebase, after ticket Phase 11e and immediately
before merge/queue with current CI. Before advancing an already queued head,
observe `autoMergeRequest` and successfully disable auto-merge via
`gh pr merge --disable-auto`; if observation or disable fails, do not advance.
Then push/rebase, collect a new record with uncovered checks pending (preserving
original evidence SHAs), assess affected review/QA and only then requeue under
existing authority using published_sha. The sibling sweep suspends before
rebase and leaves the queue off, reports pending coverage and continues other
PRs. Its owning flow must collect/publish/resolve before requeue. An external
push stales the record; there is no watcher. Queue observations are at a named
SHA/time, not promises of future applicability.

Initial provisional PR body, before a remote binding exists:

```markdown
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
```

After creation replace the provisional section with the managed publication;
never carry a stale provisional section alongside a final record.
