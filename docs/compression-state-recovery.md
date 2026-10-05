# Recover historical compression baselines

`ds-compression-state-recover` repairs reviewed state entries that claim compression
was deferred, no rewrite occurred, and a baseline or threshold was reset. These
are historical note claims, not proof that a memory file remained unchanged.
Recovery deletes complete candidate entries without changing any memory file or
recording successful compression. Fresh eligibility does not itself curate memory
or reduce resident bytes.

Inspect without creating directories, locks or files inside the project:

```bash
ds-compression-state-recover inspect --dir /absolute/project > /tmp/compression-review.json
```

Independently review the complete entries, reasons, target snapshots and proposed
state hash. Recognition is deliberately conservative: case-insensitive patterns
require `compression [was] deferred`, `no rewrite occurred`, and `baseline` or
`threshold` followed within 100 characters on the same sentence/line by `reset`.
Existing backups, snapshots, nonzero counters, unknown fields, invalid sizes/dates
and explicit success claims prevent recovery. Success or completion wording in
either order within 100 characters of rewrite, compression or curation in the
same sentence/line counts as contradictory evidence. Unmatched entries remain ambiguous;
unknown target paths remain untouched. Only project-root `MEMORY.md`, root
`CLAUDE.md`, and `.agentic/memory.md` are eligible. A missing target is reported
explicitly and still requires review.

Apply the exact report after review:

```bash
ds-compression-state-recover apply --dir /absolute/project --plan /tmp/compression-review.json
```

Apply recomputes and compares the full report under the existing wrap lock, then
checks it again before atomic publication. State or target changes invalidate the
review, including changes with identical size and restored modification time.
Subdirectories resolve to their repository root; linked worktrees stay in their
own checkout. Non-repository inputs are refused. Symlinks in state/target/lock
paths or parent directories are refused. Malformed UTF-8 in state or reviewed
reports is refused before a backup or state rewrite. JSON numbers that cannot round-trip
through the runtime without changing their value, including overflow, underflow,
precision loss and negative zero, are refused before a backup or state rewrite.

The output names changed targets, the exact original-state backup and SHA256, and
the resulting state hash. Verify the backup hash against the inspection's
`state_sha256`, inspect the new state, and compare memory hashes with the reviewed
snapshots. Retain the backup manually. A fresh inspection and apply are a no-op
when no candidates remain. File permissions on state are preserved; backup mode
is 0600.

Exit codes: 0 success/no-op, 1 refusal or I/O failure, 2 invalid usage, 5 busy lock.
On a failure, stdout may identify a valid retained backup. If ownership is lost
after publication, `published: true` reports the completed change and the
replacement lock is preserved; investigate that lock before retrying. Cooperative
locking and observed replacement checks do not protect against a malicious writer
racing the synchronous ownership-check/release interval.

For rollback, independently verify the backup's SHA256 against the original
inspection. Acquire the existing wrap lock in-process using `acquireWrapLock`
with role `commit`, current PID and a fresh token; do not wait or steal a lock.
Read the backup with no-follow access. Write its exact bytes to an exclusive
same-directory temporary file, preserve the state permissions, and fsync it.
Before atomically renaming it over state, recheck the state snapshot and lock
directory identity, plus the guarded JSON descriptor's token, PID and role.
Release only that same owned lock with `releaseWrapLock(root, token)` immediately
after the ownership check. Preserve replacement locks and refuse unsafe paths.
Confirm the restored state bytes and SHA256 exactly equal the backup. The
subprocess regression suite exercises a round-trip restore under this lock.

Recovery is a one-time migration, with no automatic hook or backup pruning.
