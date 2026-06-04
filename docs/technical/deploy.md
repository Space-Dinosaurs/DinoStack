# Deploying the docs site

The docs site (hub page at `docs/agentic-engineering.html` plus slide decks under `docs/slides/`) is a static Vercel deploy of the `docs/` directory. There is no Vercel build step - whatever is in `docs/` at deploy time is what ships. This file is the canonical procedure. Follow it exactly.

## Project facts

- Vercel account: `thummelbiz`
- Team scope: `tysons-projects-3e917e3c`
- Project name: `agentic-engineering-tyhummel`
- Project ID: `prj_8xV8CAdosPuAwPmz3GTcMwxcGTOQ`
- Org ID: `team_WtGhZ3kSxiYdIFHJQdEx9riE`
- Production URL: https://agentic-engineering-deploy.vercel.app
- Dashboard: https://vercel.com/tysons-projects-3e917e3c/agentic-engineering-tyhummel

## Prerequisites

- Vercel CLI installed (`vercel --version`)
- Marp CLI installed (`marp --version`, expects v4.x)
- `vercel.json` at repo root sets `outputDirectory: "docs"` and rewrites `/` to `/agentic-engineering.html`

## Procedure

### 1. Confirm the right Vercel account

```bash
vercel whoami
```

Must print `thummelbiz`. If it prints anything else (for example `thummel-6350`), run `vercel logout` then `vercel login` and pick the email tied to `thummelbiz`. Deploying from the wrong account will silently create an orphan project (see Footgun below).

### 2. Rebuild slides ONLY if .md content changed

Marp regenerates non-deterministic `data-marpit-scope-XXXX` CSS hash tokens on every build. A no-op rebuild produces a ~62-line diff across all 11 slide HTML files with zero content change. Do NOT rebuild unless you actually edited a slide `.md` source.

If a slide source changed:

```bash
marp -I docs/slides/ --html --output docs/slides/
git diff docs/slides/
git add docs/slides/
git commit -m "docs: rebuild slides"
```

The `-I` flag (input directory) is required by marp v4 when batching a directory. The `--html` flag is required because some sources use raw HTML blocks.

To discard a no-op rebuild diff: `git checkout -- docs/slides/`.

### Partial rebuild (one or two decks changed)

When only specific decks changed, rebuild per-file rather than batch to avoid the ~62-line no-op CSS-hash diff across untouched decks:

```bash
marp docs/slides/<changed-deck>.md --html --output docs/slides/<changed-deck>.html
```

Verify the output with `git status docs/slides/` before committing - only the changed deck's html should be dirty. The batch `-I` command remains the correct path for full rebuilds (e.g., after a Marp CLI upgrade or theme change).

### 3. Link to the existing project

```bash
vercel link --yes --project agentic-engineering-tyhummel --scope tysons-projects-3e917e3c
```

### 4. Verify the link points to the correct project (critical)

```bash
cat .vercel/project.json
```

The `projectId` field MUST equal `prj_8xV8CAdosPuAwPmz3GTcMwxcGTOQ`. If it shows any other ID, STOP. You are linked to a wrongly-auto-created orphan on the wrong Vercel account. Recover with:

```bash
vercel project rm agentic-engineering-tyhummel
rm -rf .vercel
vercel logout
vercel login   # pick the thummelbiz email
```

then restart from step 1.

### 5. Deploy

```bash
vercel --prod --yes
```

Upload + alias takes 30-90 seconds. Do not interrupt.

### 6. Smoke test

```bash
curl -sSI https://agentic-engineering-deploy.vercel.app/
curl -sS https://agentic-engineering-deploy.vercel.app/ | head -c 300
```

Expect HTTP 200 and a body containing `<title>Agentic Engineering</title>`. The custom alias may take 10-30 seconds to flip after the deploy returns.

## Footgun: silent auto-create on the wrong account

`vercel link --yes --project NAME --scope SCOPE` does NOT error if the scope is invisible to the current account or the named project does not exist. It silently creates a NEW project under whatever scope the current account uses. Always run step 4 to verify the project ID before deploying. A previous incident on 2026-04-12 deployed an orphan project to a separate `thummel-6350` Vercel account because that account cannot see the `tysons-projects-3e917e3c` scope; the orphan had to be deleted with `vercel project rm` before recovery.

## Notes

- `.vercel/project.json` is gitignored by default (the Vercel CLI added `.vercel` to `.gitignore`). Each fresh checkout must re-link. To skip linking, either commit `.vercel/project.json` (un-ignore it) or set env vars `VERCEL_ORG_ID=team_WtGhZ3kSxiYdIFHJQdEx9riE` and `VERCEL_PROJECT_ID=prj_8xV8CAdosPuAwPmz3GTcMwxcGTOQ`.
- The repo has two git remotes (`origin` to fullmetalblanket, `upstream` to Solara6). On first link the CLI may interactively prompt to pick a remote. The prompt fires AFTER `.vercel/project.json` is written, so the link itself succeeds either way.
- `.claude/build.sh` and `.cursor/build.sh` are unrelated to docs. They build the skill adapters for Claude Code and Cursor.
