# Scheduled DinoStack worktree-reap report (macOS launchd)

Runs `ds-cleanup-worktrees --multi-repo --report --json` on a daily schedule against every
repo your `~/.agentic/cleanup-worktrees.json` already names, and pushes a "worst repos by
worktree count" summary (plus a NOTE naming any repo with a `gh` query failure, when present).
**Report/notify only - this job never removes anything.** It exists
to catch machine-wide worktree accumulation between whatever per-session nudges already fire
(see "Retirement condition" below).

**Runs outside `~/Documents` - no Full Disk Access needed.** Same rationale as the
`dinostack-pr-review` package: macOS privacy protection (TCC) blocks `launchd` jobs from
touching `~/Documents`, where this repo lives. `install.sh` copies the files the job needs - `run.sh`
itself plus `bin/ds-cleanup-worktrees` and its `bin/tests/worktree_model.py` import, in their
original relative layout - into `~/.dinostack-worktree-reap/`, and the scheduled job runs only
from there. Unlike the pr-review package, this job never copies any *target* repo's own files (no
`PROJECT_DIR`); it only ever reads target repos through `ds-cleanup-worktrees --report`, which
is structurally read-only.

> **Trade-off:** the copied `run.sh` + `ds-cleanup-worktrees` + `worktree_model.py` are a
> snapshot taken at install time. After you change any of these files in the repo, **re-run
> `install.sh`** so the scheduled report picks up the change.

## Install (one time)

```bash
cd automation/dinostack-worktree-reap
bash install.sh
```

The installer resolves `python3` (and `gh`, if present) for a launchd-safe `PATH`, deploys the
run root to `~/.dinostack-worktree-reap/`, and writes a machine-specific `config.env` there.

**Repo discovery reuses `~/.agentic/cleanup-worktrees.json`** - the same config
`ds-cleanup-worktrees --multi-repo` already reads (`{"roots": [...], "repos": [...]}`). There is
no separate config surface for this package. If that file doesn't exist yet, the installer
offers (interactively, default **no**) to run `ds-cleanup-worktrees --init-config` to scaffold
it. **The installer refuses to install the LaunchAgent** if the config is missing, unreadable,
or has zero `"roots"` and zero `"repos"` entries - there would be nothing for the job to sweep.
Fix the config and re-run `install.sh`.

Default cadence is **once daily at 07:30**. Worktree counts don't meaningfully change hour to
hour, so this is deliberately much lower-frequency than `dinostack-pr-review`'s 90-minute
schedule. To change it, edit `StartCalendarInterval` in
`com.spacedinosaurs.dinostack-worktree-reap.plist.template` in this repo dir (so the new
cadence survives a reinstall), then re-run `install.sh`; or edit the installed plist at
`~/Library/LaunchAgents/com.spacedinosaurs.dinostack-worktree-reap.plist` directly and
`launchctl bootout` + `bootstrap` (or `unload`/`load -w`) to reload it.

## Test immediately

```bash
# Trigger the scheduled job and watch the output:
launchctl kickstart -k "gui/$(id -u)/com.spacedinosaurs.dinostack-worktree-reap"
tail -f ~/.dinostack-worktree-reap/logs/run-*.log

# Or run the deployed runner synchronously:
bash ~/.dinostack-worktree-reap/run.sh && tail -n 40 ~/.dinostack-worktree-reap/logs/run-*.log
```

Confirm the install is healthy any time with `bash verify.sh` (read-only preflight - checks the
plist is loaded, the copied tool is present, the config is non-empty, and the last run isn't
stale; posts nothing, runs no report).

## What the report contains

Each run invokes the DEEP tier: `ds-cleanup-worktrees --multi-repo --report --json` (never
`--count-only` - a scheduled, unattended run is off the interactive fast-first-look path, so it
always pays for the accurate per-entry evaluation). The JSON `rows` are re-sorted worst-first by
`nonroot_worktrees` and the top ~5 repos are summarized as `<count> worktree(s) (<eligible>
eligible to remove)  <repo path>`; if any repo's entries hit a `gh pr list` query failure
(`SKIP_PR_QUERY_ERROR`), a NOTE naming the affected repos (capped at 5) is appended, since
`eligible` is a FLOOR (not an exact count) for those repos, then pushed via:

- **macOS banner** (`osascript`, best-effort - macOS frequently suppresses notifications posted
  by `launchd` background jobs, so don't rely on it as the primary channel).
- **Telegram push** - reliable, reaches your phone.
- A **distinct failure alert** (Telegram, `❌ ... FAILED`) if the `ds-cleanup-worktrees`
  invocation itself fails or produces no parseable JSON - a failed run is never silent, and
  never notifies a stale/absent summary as if it were current.

Logs land in `~/.dinostack-worktree-reap/logs/run-<timestamp>.log` (raw JSON alongside as
`run-<timestamp>.json`), pruned after 30 days.

**DS-196 semantics change (accepted, not pinned):** the deployed `ds-cleanup-worktrees` copy's
`eligible` count now reflects the new origin-reachability evidence source and the 3.0h default
activity-liveness gate - origin-reachable-but-squash-merged worktrees are now counted as
eligible where they previously were not, while a worktree with recent file activity inside the
window is now excluded from `eligible` where it previously was not. This is the intended,
more-accurate behavior for this automation's purpose (a worst-repos-by-eligible-count report)
and is deliberately NOT held back to pre-DS-196 semantics. `run.sh` itself is unaffected and
stays report-only (`--multi-repo --report --json`, no removal-capable flag - see
`bin/tests/test_worktree_reap_report_only.sh`). The deployed copy under `~/.dinostack-worktree-reap/`
is a point-in-time snapshot taken by `install.sh` (see Upstream deps below) - it does NOT pick
up this change automatically; **re-run `automation/dinostack-worktree-reap/install.sh` after
this merge** to refresh it.

**DS-220 query-failure NOTE.** `run.sh`'s summary now also scans every discovered repo (not
just the worst ~5) for a nonzero `pr_query_error_count` and appends a `NOTE:` naming the
affected repos (capped at 5), plus a FLOOR disclosure scoped to the `eligible` figure only -
worktree counts are exact local git enumeration and unaffected by a `gh` failure. Same
snapshot caveat as above: the deployed copy under `~/.dinostack-worktree-reap/` does NOT pick
up this change automatically; **re-run `automation/dinostack-worktree-reap/install.sh` after
this merge** to refresh it.

**Never removal-capable.** `run.sh` invokes `--report` and nothing else - `--report` is
structurally read-only in `ds-cleanup-worktrees` (it never calls `git worktree
remove`/`unlock`/`prune` under any combination of flags, and is incompatible with
`--archive-unproven`). If you want an actual sweep, run `ds-cleanup-worktrees` yourself, or see
`content/commands/ds-cleanup-worktrees.md`.

## Telegram setup

Same bot, same variable names as `dinostack-pr-review`'s `telegram.env`
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) - no need to run `telegram-setup.sh` again. Two
options, copy is the default `install.sh` suggests:

```bash
# Copy (default; a later token rotation on one side won't affect the other)
cp ~/.dinostack-pr-review/telegram.env ~/.dinostack-worktree-reap/telegram.env

# Symlink (keeps both packages permanently in sync with one bot)
ln -sf ~/.dinostack-pr-review/telegram.env ~/.dinostack-worktree-reap/telegram.env
```

If you don't already have `dinostack-pr-review` installed, follow that package's README
"Telegram setup" section first, then copy/symlink the resulting file here. `telegram.env` is
`chmod 600` and lives only in the run root (never in the repo or git); the bot token never
appears in logs.

## Retirement condition

This package's whole justification is closing a gap: worktree accumulation that happens
*between* sessions, when nothing else is watching. If a future measurement shows every
accumulation event this LaunchAgent would have caught was already caught by the SessionStart
machine-wide nudge before the next scheduled run fires, **retire this package** in favor of the
nudge alone - don't keep running a second, redundant scheduled job. Until that measurement
exists, treat this as a belt-and-suspenders check, not a proven-necessary one.

**Report/notify only, always.** This job never removes a worktree, branch, or file in any repo
it inspects, under any configuration.

## Permissions / TCC note

Like `dinostack-pr-review`, this job executes from `~/.dinostack-worktree-reap` - outside any
TCC-protected folder - specifically so it never needs Full Disk Access to run unattended.
`ds-cleanup-worktrees --report` still needs to run `git` (and, unless `--no-gh` is passed
internally by a future revision, `gh`) *against each target repo path* named in
`~/.agentic/cleanup-worktrees.json` - those repo paths themselves may live under `~/Documents`
or another protected location. If you see `git`/`gh` calls against a target repo fail
specifically when triggered by `launchd` (but work fine when you run `run.sh` by hand in a
Terminal), grant Full Disk Access to `/bin/bash` (or your shell) in System Settings → Privacy &
Security → Full Disk Access, exactly as documented in `dinostack-pr-review`'s README for the
equivalent case.

## Platform and notification scope

This package is **macOS-launchd-only** - `install.sh`/`uninstall.sh` call `launchctl`
directly and the plist template targets `com.spacedinosaurs.dinostack-worktree-reap` under
`~/Library/LaunchAgents`. There is no Linux/systemd or Windows equivalent shipped here.
Notifications are Telegram-optional: the macOS banner (`osascript`) is best-effort and macOS
frequently suppresses it, and Telegram push is skipped entirely (log-only) whenever
`telegram.env` is absent or its two variables are unset - the job still runs and logs
normally with zero notification channels configured, which works on any machine `launchd`
runs on.

## Uninstall

```bash
bash uninstall.sh
```

Unloads and removes the LaunchAgent plist. The run root (`~/.dinostack-worktree-reap` - copied
tool, logs, config) is left in place; `rm -rf ~/.dinostack-worktree-reap` to remove it too.
