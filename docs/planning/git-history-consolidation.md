# Git history consolidation — author attribution rewrite

**Status:** Planning. Execution deferred. Gated on inputs and explicit go-ahead listed under "Open inputs at execution time".

## Goal

Consolidate Tyson Hummel's commit attribution across the `agentic-engineering` repo into a single personal GitHub identity, so durable creator recognition survives departure from Space Dinosaurs (formerly Solara6) and is independent of company-controlled email domains.

This is a pre-public-launch hygiene step. The right time to run it is **before** the repo goes public under IR-4 / IR-2, because the rewrite is a destructive history change that becomes much messier once external forks/clones exist.

## Current state (verified 2026-05-27)

Distinct commit author identities in the repo:

| Commits | Identity | Owner | Action |
|---|---|---|---|
| 288 | `fullmetalblanket <admin@fullmetalblanket.com>` | Tyson | rewrite |
| 131 | `Tyson Hummel <tyson@solara6.com>` | Tyson (company) | rewrite |
| 4 | `Tyson Hummel <thummel@crocs.com>` | Tyson (legacy client) | rewrite |
| 1 | `tysonhummel <tyhummel@gmail.com>` | Tyson | rewrite |
| 6 | `Tristan Lee <tristanlee85@gmail.com>` | other contributor | **preserve unchanged** |
| 4 | `Heitor Ramon Ribeiro <heitor.ramon@gmail.com>` | other contributor | **preserve unchanged** |

Tyson is sole arbiter of the repo and has accepted that other collaborators will need to re-clone post-rewrite.

## Approach

Use `git filter-repo --mailmap` to rewrite author and committer fields on Tyson's four identities only, retargeting all to a single new personal identity (handle + noreply email). Force-push the rewritten history pre-public.

### Why rewrite (Option B) rather than re-verify emails (Option A)

Option A — moving each existing email to the new personal GitHub account — is fragile:

- It requires keeping `tyson@solara6.com` attached to a personal GitHub account even after Tyson leaves Solara6. Solara6 owns the domain and can reclaim/disable the address, at which point those 131 commits silently un-attribute.
- Similar concern for `thummel@crocs.com` (defunct client domain).
- GitHub enforces one-email-one-account; the email has to be removable from the existing accounts to add it to the new one.

Option B writes the new personal email directly into commit objects, so attribution survives without dependency on email-ownership mappings or company goodwill.

### Why the noreply email as the target

`<ID>+<handle>@users.noreply.github.com` is bound to the new GitHub account by its numeric ID. It:

- Requires no separate verification.
- Survives a future username change (the ID is stable).
- Hides Tyson's real personal email from the public commit log.

## Procedure

### Pre-execution

1. Collect inputs:
   - New personal GitHub handle.
   - Noreply email — get from the new account's Settings → Emails with "Keep my email private" on. Format: `<id>+<handle>@users.noreply.github.com`.
   - Display name to embed (default: `Tyson Hummel`).
2. Optional courtesy notice to Tristan and Heitor that a history rewrite is coming and they'll need to re-clone.

### Execution (from a fresh clone, NOT the working repo)

```bash
# 1. Tool
brew install git-filter-repo

# 2. Backup branch in the working repo, just in case
git -C /Users/tyson.hummel/Documents/tools/agentic-engineering \
    branch backup/pre-attribution-rewrite-$(date +%Y%m%d)

# 3. Fresh clone for the rewrite (filter-repo refuses non-fresh clones by default)
mkdir -p /tmp/ae-rewrite && cd /tmp/ae-rewrite
git clone --no-local /Users/tyson.hummel/Documents/tools/agentic-engineering source
cd source

# 4. Mailmap — replace NEW_NAME and NEW_EMAIL with confirmed values
cat > /tmp/ae-mailmap.txt <<'EOF'
NEW_NAME <NEW_EMAIL> <admin@fullmetalblanket.com>
NEW_NAME <NEW_EMAIL> <tyson@solara6.com>
NEW_NAME <NEW_EMAIL> <thummel@crocs.com>
NEW_NAME <NEW_EMAIL> <tyhummel@gmail.com>
# Tristan Lee and Heitor Ramon Ribeiro deliberately omitted — preserve unchanged
EOF

# 5. Rewrite
git filter-repo --mailmap /tmp/ae-mailmap.txt

# 6. Verify
git shortlog -sne
# Expected: 4 Tyson lines collapse into 1; Tristan + Heitor unchanged.
```

### Post-rewrite gates (require explicit OK before proceeding)

- Review `git shortlog -sne` output: confirm consolidation; confirm Tristan + Heitor are intact.
- Spot-check `git log --all --format='%an <%ae> %s' | head -50`.

### Force-push (final destructive step, separately gated)

```bash
git remote add origin <origin URL>
git push --force --all origin
git push --force --tags origin
```

### Post-execution

```bash
# Re-clone the working repo from the now-rewritten remote, OR
# reset the existing working repo to the new remote state (advanced — easier to re-clone).

# After successful push and re-clone, configure local git for future commits:
git config --global user.name  "NEW_NAME"
git config --global user.email "NEW_EMAIL"

# Backup branch can be deleted after a few days' confidence:
# git branch -D backup/pre-attribution-rewrite-<date>
```

## Safeguards

- **Backup branch** in the original repo before any rewrite.
- **Fresh clone** for the rewrite — working tree is untouched until force-push.
- **Mailmap explicitly excludes** Tristan and Heitor (only the 4 Tyson identities are listed).
- **Force-push is a separate, explicitly gated step** — the rewrite itself produces a local result that can be reviewed before anything touches the remote.
- **Other contributors' commits remain bit-identical** in their author/committer/message fields (SHAs change because parents change, but the metadata is preserved).

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| SHA changes break open PRs and external clones | Accepted per Tyson's "sole arbiter" call; rewrite is done pre-public to limit blast radius |
| Misattribution of others' commits | Mailmap targets only Tyson's 4 emails; `git shortlog -sne` verification before force-push |
| Signed commits lose signatures | Re-sign going forward if commit signing is in use |
| Backup not taken / unrecoverable mistake | Backup branch + fresh-clone workflow; force-push is the last step |
| New personal email mistyped in mailmap | Pre-rewrite verification by Tyson; `git shortlog -sne` confirms before force-push |

## Side benefit: client-reference scrub

This rewrite also removes `thummel@crocs.com` from commit metadata. Crocs is explicitly on the OSS plan's pre-launch scrub list (§5: client references to remove). The rewrite cleans up one of the spots that scrub would otherwise need to find separately. Track the broader scrub work elsewhere — file contents, prompts, examples, fixtures — not in this plan.

## Open inputs at execution time

- [ ] New personal GitHub handle: ___________________________
- [ ] New personal noreply email: `____+____@users.noreply.github.com`
- [ ] Display name (default `Tyson Hummel`): ___________________________
- [ ] Confirm the 4 identities above are all yours
- [ ] Confirm Tristan + Heitor must be preserved unchanged
- [ ] Explicit go-ahead for force-push (after `git shortlog -sne` review)

## Related work

- **IR-2** — license decision. Independent of this rewrite, but both should be done before public launch.
- **IR-4** — community files (README, CONTRIBUTING, etc.). Independent; runs in parallel.
- **Pre-launch scrub (OSS plan §5)** — broader client-reference removal beyond commit metadata.
