#!/usr/bin/env python3
"""
Internal shared helpers for dinostack bin/ CLIs.
NOT a public CLI - do not invoke directly.

Purpose: Provide the shared helpers reused by multiple CLIs:
  1. acquire_exclusive_lock - fcntl.LOCK_EX context manager with sleep-retry
     until timeout; used for multi-process coordination (e.g. flush lock).
  2. atomic_write - write content to a pid-suffixed <path>.tmp.<pid> sibling
     then rename; cleans up OUR OWN pid-suffixed .tmp on failure; optional
     chmod mode. Atomic for a single writer only - the pid suffix exists to
     stop two concurrent writers from colliding on one staging path.
  3. resolve_claude_config_dir - the harness config-dir env-var precedence
     lookup (read-only, no filesystem writes).
  4. resolve_base_branch (plus its private helpers and the shared `_run`
     subprocess wrapper) - the ONE base-branch resolver both
     bin/ds-cleanup-worktrees and bin/ds-branch-prune use. It lived in
     bin/ds-cleanup-worktrees until the worktree-reap calibration work;
     bin/ds-branch-prune hardcoded `origin/main` instead, so on any repo
     whose integration branch is not `main` it evaluated every branch
     against the wrong base and proved nothing. Unlike helpers 1-3, this
     one is NOT pure in-process work: it shells out.

Public API:
  acquire_exclusive_lock(lock_path, timeout=30.0)
    Context manager. Opens lock_path as a Python file object (buffered), acquires
    fcntl.LOCK_EX | LOCK_NB via a 0.1s sleep-retry loop until timeout, yields the
    file object, releases (LOCK_UN) and closes on exit. Raises RuntimeError on
    timeout so callers can distinguish "another holder" from a filesystem error.
    Caller is responsible for ensuring lock_path and its parent exist before entry.

  atomic_write(path, content, mode=0o600)
    Writes str content to a pid-suffixed <path>.tmp.<pid> sibling then renames
    into place. When mode is not None, applies os.chmod to the tmp file before
    rename. On any exception, unlinks OUR OWN pid-suffixed tmp file
    (missing_ok) and re-raises - never a shared/fixed name another concurrent
    caller could own. path must be a pathlib.Path.

  resolve_claude_config_dir()
    Returns the active harness config dir as an absolute pathlib.Path,
    honoring the same env-var precedence as bin/ds-identity's
    PROFILE_CONFIG_DIR_ENV: AGENTIC_CONFIG_DIR > CLAUDE_CONFIG_DIR >
    CODEX_HOME > PI_CODING_AGENT_DIR, first non-empty wins. Falls back to
    ~/.claude when none is set. A `~`-prefixed value is expanded, and the
    result is absolutized via os.path.abspath() (round-2 fix: kept in sync
    with the Node sibling, hooks/lib/config-dir.js's
    resolveClaudeConfigDir(), which now applies the same two steps). This
    is a READ-ONLY lookup (transcript discovery), not a write target -
    unlike ds-identity's _profile_config_dir(), it deliberately does NOT
    apply a $HOME-containment check or symlink-component check; those
    guards exist there to stop an identity WRITE from escaping the user
    tree, which does not apply to a read-only glob/stat lookup here.

  resolve_base_branch(repo, explicit_base, multi_repo=False,
                      prog="ds-cleanup-worktrees")
    Returns (resolved_ref, source_tier, diagnostics). See the function's own
    docstring and the tier-order comment block directly above it for the
    full, normative resolution order and its three deliberate deviations
    from content/rules/conventions.md base-branch resolution. `prog`
    prefixes every diagnostic line; it defaults to "ds-cleanup-worktrees"
    so output is byte-identical to what this code produced before the move,
    and bin/ds-branch-prune passes its own name.

  _run(args, cwd=None, timeout=None, env=None)
    Private-by-convention subprocess wrapper shared with the resolver
    helpers (see its own docstring for the `env=` REPLACEMENT semantics and
    the synthetic rc=124 timeout result). Exported because
    bin/ds-cleanup-worktrees routes every one of its own subprocess calls
    through it. bin/ds-branch-prune does NOT import this function at all,
    under an alias or otherwise: it keeps its own same-named,
    different-signature `_run` (an `input_text` parameter, no timeout
    support) that every call site there depends on, the two are
    deliberately NOT unified, and nothing on that side would call this one,
    so an alias import would be dead code reading as a live dependency.
    That file's import block says the same, and
    `test_branch_prune_defines_its_own_run_and_does_not_import_the_shared_one`
    pins it.

Upstream deps: Python 3 stdlib only (contextlib, fcntl, os, re, subprocess,
               time, pathlib, typing), plus the `git` CLI for
               resolve_base_branch and its helpers ONLY - every other
               function here is pure in-process work with no external
               process dependency.

Downstream consumers: bin/ds-config (atomic_write), bin/ds-defer (both
                      helpers), bin/ds-feedback (both helpers),
                      bin/ds-learning-shard (both helpers),
                      bin/ds-migrate (atomic_write), bin/ds-tracker
                      (atomic_write), bin/ds-parse-subagent-usage
                      (resolve_claude_config_dir),
                      bin/ds-cleanup-worktrees (resolve_base_branch, _run,
                      and every private resolver helper - re-exported at its
                      own module level so its test suites' `mod.<name>`
                      attribute access keeps working), bin/ds-branch-prune
                      (resolve_base_branch ONLY - it imports no other
                      symbol from this module, and specifically not `_run`;
                      see that function's Public API entry above).
                      bin/ds-identity does NOT
                      use this module - it ships its own
                      _atomic_write_identity, its own lock contextmanager,
                      and its own (containment-checked) _profile_config_dir.

Failure modes:
  acquire_exclusive_lock: raises RuntimeError("lock timeout") after timeout seconds
    with no lock held; the underlying fd is always closed before raising.
    OS errors opening the lock file propagate to the caller unchanged (the file
    must exist before calling; existence is the caller's responsibility).
  atomic_write: on any write/chmod/rename failure, removes OUR OWN pid-suffixed
    .tmp.<pid> file (missing_ok semantics) and re-raises the original exception.
    The destination file is never partially written. The .tmp.<pid> suffix is
    appended to the full filename (e.g. identity.yml -> identity.yml.tmp.12345)
    to stay in the same directory and on the same filesystem as the
    destination, AND to guarantee two concurrent callers never share one
    staging path (single-writer atomicity only - see rename semantics; the
    pid suffix prevents cross-process tmp collision/cleanup, not a
    last-write-wins race on the final destination itself).
  resolve_claude_config_dir: an unset/blank/whitespace-only env var is
    treated as absent; the first non-blank value wins even if the resulting
    path does not exist on disk - callers must handle a nonexistent config
    dir themselves (e.g. by falling through to a glob). `~` expansion and
    abspath absolutization happen unconditionally on the winning value.
    os.path.expanduser never raises (an unresolvable `~user` form is
    returned unchanged, per CPython's own KeyError-swallowing behavior) but
    os.path.abspath is NOT purely a string operation: for a RELATIVE input
    (e.g. a config-dir env var set to a relative path) it calls
    os.getcwd(), which DOES touch the filesystem and CAN raise (e.g.
    FileNotFoundError when the current working directory has been deleted
    out from under the process). This is a narrow, unlikely-in-practice
    edge case - not observed in this repo - but the function is not
    unconditionally raise-free.
  resolve_base_branch: never raises and never exits - an unresolvable base
    is returned as (None, "unresolved", diagnostics), and failing SAFE on
    that is the CALLER's responsibility (both callers print the diagnostics
    and then do nothing destructive that run). An AGENTS.md `BASE_BRANCH:`
    declaration that does not validate fails resolution outright rather
    than falling through to a lower tier - see the tier-order comment.
    Every subprocess call routes through `_run`, which converts a timeout
    into a nonzero-rc CompletedProcess rather than propagating an
    exception, so a failed call always reads as "could not determine",
    never as proof of anything.

Performance: Standard. acquire_exclusive_lock sleeps 0.1s per retry (~300 retries
  over 30s); atomic_write is a single write + fsync-less rename (same filesystem).
  resolve_claude_config_dir is a handful of os.environ.get() calls - negligible.
  resolve_base_branch is the sole exception to this module's otherwise
  no-subprocess profile: it performs up to ~6 short, local, NON-network
  subprocess calls plus one AGENTS.md read - milliseconds in practice, but
  not free. Called once per repo per run, never in an inner loop.
"""

from __future__ import annotations

import fcntl
import os
import re
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Generator, List, Optional, Tuple


@contextmanager
def acquire_exclusive_lock(
    lock_path: Path,
    timeout: float = 30.0,
) -> Generator[object, None, None]:
    """Context manager: acquire fcntl.LOCK_EX on lock_path.

    Opens lock_path as a Python file object ('r' mode - the file must already
    exist), retries with 0.1s sleep until timeout, yields the file object,
    then releases LOCK_UN and closes on exit.

    Raises RuntimeError on timeout (lock not acquired; fd is closed before
    raising). OS errors on open propagate unchanged.

    Usage:
        with acquire_exclusive_lock(lock_path) as fd:
            # critical section
            ...
    """
    fd = open(lock_path, "r")  # noqa: SIM115 - intentional: file stays open for flock
    try:
        deadline = time.monotonic() + timeout
        acquired = False
        while time.monotonic() < deadline:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                time.sleep(0.1)

        if not acquired:
            fd.close()
            raise RuntimeError(f"acquire_exclusive_lock: timeout after {timeout}s on {lock_path}")

        try:
            yield fd
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()

    except RuntimeError:
        raise
    except BaseException:
        # Covers exceptions from open() after fd is assigned but before acquired.
        # If fd was opened but flock not yet attempted (shouldn't happen in normal
        # flow but guard anyway), close it.
        try:
            fd.close()
        except Exception:
            pass
        raise


# Harness-standard config-dir env vars, in detection precedence order. Kept
# in sync with bin/ds-identity's PROFILE_CONFIG_DIR_ENV (same precedence,
# same four vars) - see that file's comment for why each one is listed.
CONFIG_DIR_ENV: tuple[str, ...] = (
    "AGENTIC_CONFIG_DIR",
    "CLAUDE_CONFIG_DIR",
    "CODEX_HOME",
    "PI_CODING_AGENT_DIR",
)


def resolve_claude_config_dir() -> Path:
    """Return the active harness config dir, or ~/.claude when none is set.

    Read-only lookup: no $HOME-containment or symlink check (contrast with
    bin/ds-identity's _profile_config_dir(), which guards a WRITE target).
    Round-2 fix: applies os.path.abspath() in addition to expanduser() so
    a relative env-var value absolutizes the same way the Node sibling
    (hooks/lib/config-dir.js's resolveClaudeConfigDir()) now does.
    """
    for var in CONFIG_DIR_ENV:
        raw = os.environ.get(var, "").strip()
        if raw:
            return Path(os.path.abspath(os.path.expanduser(raw)))
    return Path(os.path.expanduser("~/.claude"))


def atomic_write(path: Path, content: str, mode: int | None = 0o600) -> None:
    """Write content to path atomically via a .tmp sibling.

    Steps:
      1. Write content to <path>.tmp.<pid> (text, utf-8).
      2. If mode is not None, chmod <path>.tmp.<pid> to mode.
      3. Rename <path>.tmp.<pid> -> path.

    On any failure, unlinks OUR OWN pid-suffixed <path>.tmp.<pid> (missing_ok)
    and re-raises. The destination file is never partially overwritten.
    Atomic for a single writer only: the pid suffix guarantees two concurrent
    callers never share one staging path, but it does not add cross-process
    locking around the final rename - a last-write-wins race on the
    destination itself is still possible if two writers target the same path.

    The tmp filename is suffixed with the current pid so two concurrent
    callers (e.g. two ds-identity invocations) never share one staging
    path - a fixed tmp name would let one process's crash-cleanup unlink
    another process's still-in-flight write, or let two writers collide on
    the same tmp file.

    path.parent must already exist (no mkdir here - callers handle that).
    """
    tmp = path.parent / (path.name + f".tmp.{os.getpid()}")
    try:
        tmp.write_text(content, encoding="utf-8")
        if mode is not None:
            os.chmod(tmp, mode)
        tmp.rename(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _run(
    args: List[str],
    cwd: Optional[str] = None,
    timeout: Optional[float] = None,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    """`env=None` (the default) inherits the current process environment,
    identical to every pre-existing call site - this parameter is
    additive-only. `env={...}` REPLACES the subprocess environment
    entirely (Python's own `subprocess.run` semantics), so a caller that
    wants to add/override on top of the inherited environment (e.g.
    `_pr_state`'s `GH_TOKEN` retry) must build the dict as
    `{**os.environ, "GH_TOKEN": token}` itself - `_run` performs no
    merging.
    """
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        # Synthetic failure result - callers treat any nonzero returncode as
        # "could not determine", never as proof of anything. rc=124 mirrors
        # the shell convention for a timed-out command.
        return subprocess.CompletedProcess(args, returncode=124, stdout="", stderr=f"timeout after {timeout}s")




# --------------------------------------------------------------------------
# Base-branch resolution (round-4 rework, DS-cleanup-worktrees; moved here
# from bin/ds-cleanup-worktrees so bin/ds-branch-prune shares ONE resolver
# rather than hardcoding `origin/main` - see this module's Downstream
# consumers). Replaces
# content/commands/ds-cleanup-worktrees.md's former Step 2 hand-rolled
# grep/awk/sed text-extraction pipeline, which produced a fresh defect in
# three consecutive review rounds (matched prose, mishandled quotes,
# doubled origin/ prefix, a fenced-example `head -1` win; trailing
# whitespace surviving normalization; a fence-stripper that missed indented
# and ~~~ fences; unstripped single quotes; end-of-line anchoring that
# rejected a trailing comment) - each fix was an input-variant patch on the
# last, so this round moves resolution into tested Python instead.
#
# Resolution order, first candidate that resolves AND validates wins:
#   a. explicit --base CLI argument, if the operator passed one - used
#      VERBATIM, no validation/fallthrough (preserves this tool's
#      pre-existing precedence for an operator override; a bad explicit
#      value is not silently second-guessed).
#   b. a `BASE_BRANCH:` declaration in the repo's AGENTS.md - AUTHORITATIVE,
#      not merely first-ranked: if declared but its `origin/<name>` ref does
#      not validate, resolution fails outright (source "unresolved") rather
#      than falling through to tier c or below. conventions.md's canonical
#      order says the declaration "wins. Highest priority," and a silent
#      substitution of a different (possibly perfectly valid) base is a
#      more dangerous failure than a skipped run - the substituted base
#      being valid is exactly what would let a wrongful reap slip through
#      undetected. Only tiers c-f below have a same-tier-to-next-tier
#      fallthrough on validation failure.
#   c. `git symbolic-ref refs/remotes/origin/HEAD`.
#   d. a local `develop` branch.
#   e. a local `development` branch.
#   f. `main`, then `master`.
# Tiers b-f each resolve to an `origin/<name>` ref (mirroring the shell
# pipeline this replaces, which always compared against the REMOTE branch)
# and are each validated with `git rev-parse --verify` before use. Among
# tiers c-f, a resolved-but-nonexistent candidate is reported via a
# diagnostic and the next candidate is tried, never a hard failure on the
# first miss (tier b is the sole exception - see above). Only when every
# candidate fails does resolution fail, naming every candidate tried.
#
# This order deliberately differs from content/rules/conventions.md's
# canonical §Base branch resolution in three ways, all because this tool
# runs non-interactively with no operator to prompt:
#   1. it inserts an extra tier (c, origin/HEAD) between the AGENTS.md
#      declaration and the local develop/development tiers - the
#      strongest automatic signal of a repo's actual configured default
#      branch when AGENTS.md declares nothing, ahead of a local
#      develop/development branch that could be an unrelated leftover
#      branch a contributor happened to create locally;
#   2. conventions.md's final step is an interactive prompt (offering
#      main, falling back to master, with an explicit decline path) - this
#      tool has no operator to prompt, so it resolves main (falling back
#      to master) directly instead of stopping to ask;
#   3. a declared-but-unresolvable AGENTS.md base fails resolution outright
#      instead of falling through to a lower tier - conventions.md's prose
#      does not itself specify fallthrough-on-declared-but-unresolvable
#      behavior, since its resolution is interactive; this tool makes the
#      choice explicit rather than picking silent substitution by default.
# --------------------------------------------------------------------------

#: Matches a `BASE_BRANCH:` declaration line, tolerating an optional
#: leading backtick before the label (a whole-phrase inline-code span, a
#: common markdown convention), an optional matching quote/backtick pair
#: wrapping just the value, and an optional `refs/heads/`/`origin/`
#: prefix. The `trailer` group captures everything after the value so
#: `_ALLOWED_DECL_TRAILER_RE` below can distinguish a genuine declaration
#: from a prose sentence that merely MENTIONS `BASE_BRANCH:` (e.g.
#: "BASE_BRANCH: resolution rules.", the round-2 false-match defect).
_BASE_BRANCH_DECL_RE = re.compile(
    r"`?BASE_BRANCH:\s*"
    r"(?P<quote>[`\"']?)"
    r"(?P<value>(?:refs/heads/|origin/)?[A-Za-z0-9][A-Za-z0-9_./-]*)"
    r"(?P=quote)"
    r"`?"  # closes an optional whole-phrase-wrapping leading backtick above
    r"(?P<trailer>.*)$"
)

#: A declaration's trailer is allowed to be empty, a bare closing period,
#: and/or a `#`- or `//`-prefixed trailing comment - anything else (extra
#: prose words) means the whole line was a mention, not a declaration.
_ALLOWED_DECL_TRAILER_RE = re.compile(r"^\s*(\.\s*)?(#.*|//.*)?\s*$")


def _strip_fenced_and_indented_lines(text: str) -> List[str]:
    """Blank out fenced (``` / ~~~) and 4-space/tab-indented code regions
    so a `BASE_BRANCH:` mention inside an illustrative example can never
    match - only a genuine declaration in prose can. Line COUNT and ORDER
    are preserved (fenced/indented lines become empty strings, never
    removed), so a real declaration appearing AFTER a fenced example in
    the same file is still reachable on its own line."""
    lines = text.splitlines()
    out: List[str] = []
    in_fence = False
    for line in lines:
        stripped = line.lstrip(" \t")
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append("")
            continue
        if in_fence:
            out.append("")
            continue
        if line[:4] == "    " or line[:1] == "\t":
            out.append("")
            continue
        out.append(line)
    return out


def _parse_base_branch_declaration(agents_md_text: str) -> Optional[str]:
    """Extract a `BASE_BRANCH:` declaration's value from AGENTS.md prose.
    Returns None when no genuine declaration is found (no matching line,
    every match is inside a fenced/indented example, or every match is a
    prose mention that fails the trailer check)."""
    for line in _strip_fenced_and_indented_lines(agents_md_text):
        m = _BASE_BRANCH_DECL_RE.search(line)
        if not m:
            continue
        if not _ALLOWED_DECL_TRAILER_RE.match(m.group("trailer")):
            continue
        value = m.group("value")
        if value.startswith("refs/heads/"):
            value = value[len("refs/heads/"):]
        elif value.startswith("origin/"):
            value = value[len("origin/"):]
        # Branch names never legitimately end in "." (git rejects them,
        # git-check-ref-format(1)) - the value char class allows "." mid-
        # token (e.g. "release-1.2") so a trailing sentence period gets
        # greedily consumed into the value at true end-of-line; strip
        # exactly one.
        if len(value) > 1 and value.endswith("."):
            value = value[:-1]
        return value
    return None


def _read_agents_md(repo: str) -> Optional[str]:
    try:
        return (Path(repo) / "AGENTS.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _local_branch_exists(repo: str, name: str) -> bool:
    proc = _run(["git", "-C", repo, "show-ref", "--verify", "--quiet", f"refs/heads/{name}"])
    return proc.returncode == 0


def _origin_head_branch(repo: str) -> Optional[str]:
    proc = _run(["git", "-C", repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"])
    if proc.returncode != 0:
        return None
    ref = proc.stdout.strip()
    prefix = "refs/remotes/origin/"
    if ref.startswith(prefix) and len(ref) > len(prefix):
        return ref[len(prefix):]
    return None


def _ref_exists(repo: str, ref: str) -> bool:
    # Checks the LOCAL remote-tracking ref (e.g. `origin/main`), not the
    # remote itself - no network call is made here. A branch that genuinely
    # exists on origin but whose local remote-tracking ref is stale or was
    # never fetched will report as missing; `git fetch origin` is the fix.
    proc = _run(["git", "-C", repo, "rev-parse", "--verify", "--quiet", ref])
    return proc.returncode == 0


def _has_any_remote(repo: str) -> bool:
    """True when `repo` has at least one git remote configured (`git
    remote`, no network call). Round-N Major 1 fix: every automatic base
    candidate is an `origin/<name>` ref, so a repo with zero remotes can
    never resolve one regardless of which branch name is tried - this is
    the ACTUAL cause of every live `resolve_base_branch` failure measured
    under `--multi-repo --report --count-only` (11 of 11 `skipped-base-
    unresolved` repos, verified: zero non-root worktrees on 10 of the 11,
    none an AGENTS.md `BASE_BRANCH:` failure). Distinguishing this case
    lets `resolve_base_branch` give advice that is actually actionable for
    it, instead of the generic "declare BASE_BRANCH or pass --base" text,
    which is a dead end here: declaring BASE_BRANCH still resolves against
    `origin/<name>` and cannot help, and `--base` is a hard usage error
    under `--multi-repo` (see `_validate_args`)."""
    proc = _run(["git", "-C", repo, "remote"])
    if proc.returncode != 0:
        return False
    return bool(proc.stdout.strip())


def resolve_base_branch(
    repo: str,
    explicit_base: Optional[str],
    multi_repo: bool = False,
    prog: str = "ds-cleanup-worktrees",
) -> Tuple[Optional[str], str, List[str]]:
    """Resolve the --base ref per the tier order documented in the module
    comment above. Returns (resolved_ref, source_tier, diagnostics):
    `resolved_ref` is None either when an AGENTS.md `BASE_BRANCH:`
    declaration is present but its ref fails validation (declaration is
    authoritative, never falls through to a lower tier - see module
    comment), or when every tier-c-through-f automatic candidate failed
    validation (`explicit_base` given always resolves, tier "explicit");
    `source_tier` is one of "explicit", "agents-md", "origin-head",
    "local-develop", "local-development", "main-fallback",
    "master-fallback", or "unresolved" when resolved_ref is None;
    `diagnostics` is zero or more human-readable lines - one per candidate
    that resolved to a value but failed `git rev-parse --verify` against
    the LOCAL remote-tracking ref (e.g. `origin/main`), not the remote
    itself - a ref that is stale or was never fetched reads as missing even
    when the branch genuinely exists on origin (`git fetch origin` fixes
    this) - plus (only when every candidate failed) a final line naming
    every candidate tried. `multi_repo` (round-N Major 1) is used ONLY to
    keep the final "every candidate failed" diagnostic's remediation
    advice mode-aware: suggesting `--base` is useless (a hard usage error,
    exit 2) when this resolution is happening under `--multi-repo`, so
    that branch of the message is omitted there. `prog` (DS-worktree-reap
    calibration) is the program name every diagnostic line is prefixed
    with; it defaults to "ds-cleanup-worktrees" so this function's output
    is byte-identical to what it produced before the move into
    `bin/_lib.py`, and `bin/ds-branch-prune` passes its own name so an
    operator can tell which tool emitted a given line.
    """
    diagnostics: List[str] = []

    if explicit_base is not None:
        return explicit_base, "explicit", diagnostics

    # A `BASE_BRANCH:` declaration in AGENTS.md is authoritative, not just a
    # ranked candidate - conventions.md's canonical resolution order says
    # the declaration "wins. Highest priority." A declared-but-unresolvable
    # value must never silently fall through to origin/HEAD, a local
    # develop/development branch, or main/master: those could easily be
    # VALID branches that resolve cleanly, so a fallthrough would reap
    # against a base the operator never declared, with no error surfaced -
    # the dangerous case is exactly the one where the substituted base is
    # itself valid. Fail the whole resolution here (never a hard crash;
    # `resolved_ref is None` already fails safe at the caller, which skips
    # the reap for this run without exiting nonzero).
    agents_md_text = _read_agents_md(repo)
    if agents_md_text is not None:
        declared = _parse_base_branch_declaration(agents_md_text)
        if declared:
            ref = f"origin/{declared}"
            if _ref_exists(repo, ref):
                return ref, "agents-md", diagnostics
            diagnostics.append(
                f"{prog}: declared base candidate '{ref}' (source: agents-md) "
                "does not exist as a local remote-tracking ref - AGENTS.md's BASE_BRANCH "
                "declaration is authoritative and is never silently overridden by a "
                "different base; resolution fails rather than falling through. If the "
                "branch genuinely exists on origin, this ref may simply be stale or "
                "unfetched - try `git fetch origin` first. Otherwise, fix the branch name "
                "in AGENTS.md's BASE_BRANCH declaration, or pass --base explicitly to "
                "override the declaration for this run."
            )
            return None, "unresolved", diagnostics

    candidates: List[Tuple[str, str]] = []

    origin_head = _origin_head_branch(repo)
    if origin_head:
        candidates.append((f"origin/{origin_head}", "origin-head"))

    if _local_branch_exists(repo, "develop"):
        candidates.append(("origin/develop", "local-develop"))
    if _local_branch_exists(repo, "development"):
        candidates.append(("origin/development", "local-development"))

    candidates.append(("origin/main", "main-fallback"))
    candidates.append(("origin/master", "master-fallback"))

    for ref, source in candidates:
        if _ref_exists(repo, ref):
            return ref, source, diagnostics
        diagnostics.append(
            f"{prog}: base candidate '{ref}' (source: {source}) does not exist "
            "on origin - trying the next candidate."
        )

    tried = ", ".join(f"{ref} ({source})" for ref, source in candidates)

    # Round-N Major 1 fix: every candidate above is an `origin/<name>` ref,
    # so a repo with zero git remotes can never resolve ANY of them - this
    # is the actual, measured cause of every live failure (see
    # `_has_any_remote`'s docstring). Name that cause specifically and give
    # mode-aware advice, instead of the generic "declare BASE_BRANCH or
    # pass --base" text, which is a dead end here: a BASE_BRANCH
    # declaration still resolves against `origin/<name>` and cannot help,
    # and suggesting `--base` under `--multi-repo` would recommend a flag
    # that is a hard usage error there (see `_validate_args`).
    if not _has_any_remote(repo):
        remediation = (
            "This repo has no git remotes configured (`git remote` returned nothing), so no "
            "`origin/<branch>` ref can ever resolve here regardless of which branch name is "
            "tried - declaring BASE_BRANCH in AGENTS.md will not help either, since it also "
            "resolves against `origin/<name>`. Add a remote (`git remote add origin <url>`) "
            "and fetch, or skip this repo."
        )
        if not multi_repo:
            remediation += (
                " Alternatively, pass --base <ref> explicitly - it bypasses remote resolution "
                "entirely and is accepted verbatim."
            )
        diagnostics.append(
            f"{prog}: could not resolve a base branch - no git remotes configured. "
            f"Tried: {tried}. {remediation}"
        )
    else:
        advice = "Declare BASE_BRANCH in AGENTS.md"
        advice += ", or pass --base explicitly." if not multi_repo else " for this repo."
        diagnostics.append(
            f"{prog}: could not resolve a base branch - every candidate failed. "
            f"Tried: {tried}. {advice}"
        )
    return None, "unresolved", diagnostics
