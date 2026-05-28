# DCO Setup (Maintainer Runbook)

This project uses the [Developer Certificate of Origin](https://developercertificate.org) (DCO) instead of a CLA. Every commit on every pull request must carry a `Signed-off-by:` trailer matching the commit author. Contributor-facing instructions ("what to do as a contributor") live in `CONTRIBUTING.md`; this document is the maintainer runbook for the enforcement mechanism.

## What the workflow does

`.github/workflows/dco.yml` runs on every pull request targeting `main`. The job is named `DCO Signed-off-by check` (job id `dco-check`). It uses two well-maintained community actions:

- `tim-actions/get-pr-commits` — enumerates the commits in the PR.
- `tim-actions/dco` — verifies each commit has a valid `Signed-off-by:` trailer matching the author.

If any commit in the PR is missing a signoff, the check fails. There is no custom regex: the check delegates entirely to the DCO action.

## Requiring the check via branch protection

The workflow alone does not block merges — GitHub branch protection does. To make `DCO Signed-off-by check` a required status check:

1. Open the repo on GitHub → **Settings** → **Branches**.
2. Under **Branch protection rules**, edit (or add) the rule for `main`.
3. Enable **Require status checks to pass before merging**.
4. In the search box, type `DCO Signed-off-by check` and select it. (The check must have run at least once on a PR before GitHub will offer it as a selectable status — open a dummy PR if needed.)
5. Save the rule.

From this point on, no PR can merge into `main` without a green DCO check.

## Alternative: probot/dco GitHub App

GitHub also offers the [DCO GitHub App](https://github.com/apps/dco) (probot/dco) as a hosted alternative.

Tradeoffs vs. the in-repo workflow:

- **In-repo workflow (this repo)** — version-controlled, reviewable in PRs, no install permission needed, travels with the repo.
- **probot/dco App** — needs org/repo admin to install, but surfaces a dedicated per-commit DCO status with an inline "details" link. Reasonable choice when managing many repos centrally.

The two are mutually exclusive in practice — pick one; running both produces duplicate checks. We use the in-repo workflow because it is portable and requires no external install.

## How a contributor fixes a PR missing signoff

If the DCO check fails on a PR, the contributor has three common cases. Maintainers can paste these commands into a PR comment:

- **Last commit only:**
  ```
  git commit --amend --signoff
  git push --force-with-lease
  ```

- **All commits in the branch** (replace `main` with the PR's base branch if different):
  ```
  git rebase --signoff main
  git push --force-with-lease
  ```

- **Going forward**, configure git to sign off automatically for this repo:
  ```
  git config format.signOff true
  ```
  and use `git commit -s` (or rely on the config above) for every commit.

After the force-push, the DCO check re-runs automatically on the PR.

## Post-merge verification

The first end-to-end verification requires a real PR: open a throwaway PR with one signed-off commit and one un-signed commit, confirm the check goes red, amend with `--signoff`, force-push, and confirm the check goes green. Do this once after the workflow merges to main and after the branch protection rule is enabled.
