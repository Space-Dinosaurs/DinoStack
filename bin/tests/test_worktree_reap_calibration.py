#!/usr/bin/env python3
"""
Purpose: Regression suite for the worktree-reap calibration change - the
         three surfaces it added or corrected, each of which had no
         coverage before:
           U1  bin/ds-branch-prune no longer hardcodes `--base origin/main`;
               it resolves through the SHARED `resolve_base_branch` now
               living in bin/_lib.py, and fails SAFE (deletes nothing,
               writes no ledger entry, exits 0) when resolution fails.
           U3  `_dirty_composition` - REPORT-ONLY itemization of what a
               dirty worktree holds, bucketed PER LINE of
               `git status --porcelain`, never per status letter.
           U4  `_unregistered_worktree_dirs` - REPORT-ONLY listing of
               directories under this repo's worktree prefixes that git
               does not know about, with a depth-agnostic descent that must
               never name an ancestor of a registered worktree and must
               never print a removal command.
         Round-2 review additions, all on the same three surfaces:
           - the `--explain` raw-porcelain dump is BOUNDED per entry and
             states its omitted count (Major 1), with a negative control
             proving the truncation line is not printed unconditionally;
           - `ds-branch-prune`'s unresolvable-base summary line composes
             `mode=` from every axis that held and carries `skips=`, so a
             --dry-run run is distinguishable from a live one (Minor 5);
           - the orphan NOTE's `--explain` hint is conditional (Minor 6).

Public API: pytest test functions only; no importable helpers are intended
            for reuse outside this file.

Upstream deps: Python 3 stdlib (subprocess, sys, pathlib), pytest, the
               `git` CLI, and the two binaries under test
               (bin/ds-branch-prune, bin/ds-cleanup-worktrees), loaded both
               as subprocesses (end-to-end CLI behavior) and as directly-
               imported modules (unit-level access to the two report-only
               helpers). bin/_lib.py is imported directly for the resolver
               default-`prog` assertion.

Downstream consumers: CI only - auto-collected by
                      `python3 -m pytest bin/tests/`, which is what both
                      `.github/workflows/bin-tests.yml` and
                      `scripts/check-local.sh` run. No production code
                      imports this file.

Failure modes: every fixture builds a throwaway repo (plus a bare origin
               where a remote is needed) under pytest's `tmp_path`; nothing
               here touches the real checkout, the user's `$HOME`, or any
               network. Each `git` helper asserts on a nonzero exit rather
               than continuing against an unbuilt fixture, so a broken
               fixture fails loudly instead of vacuously passing.

Performance: a handful of local `git` invocations per test; no network, no
             `gh`, and every subprocess run of ds-branch-prune passes
             `--no-gh` so no test can block on an external call.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BIN_DIR = Path(__file__).resolve().parent.parent
PRUNE = BIN_DIR / "ds-branch-prune"
CLEANUP = BIN_DIR / "ds-cleanup-worktrees"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(BIN_DIR))

import importlib.machinery as _ilm  # noqa: E402
import importlib.util as _ilu  # noqa: E402

import _lib  # noqa: E402


def _load(path: Path, name: str):
    loader = _ilm.SourceFileLoader(name, str(path))
    spec = _ilu.spec_from_loader(name, loader)
    mod = _ilu.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


ds_cleanup = _load(CLEANUP, "ds_cleanup_worktrees_calibration")


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert proc.returncode == 0, f"git {args} failed: {proc.stderr}\n{proc.stdout}"
    return proc


def _repo_with_origin(tmp_path: Path, name: str = "repo") -> Path:
    """A repo on `main` with a real bare origin, one commit pushed."""
    origin = tmp_path / f"{name}-origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "spec@example.com")
    _git(repo, "config", "user.name", "spec")
    _git(repo, "remote", "add", "origin", str(origin))
    (repo / "README.md").write_text("init\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo


def _prune(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PRUNE), "--repo", str(repo), "--no-gh", *extra],
        capture_output=True,
        text=True,
    )


# --------------------------------------------------------------------------
# U1 - base resolution in ds-branch-prune
# --------------------------------------------------------------------------


def test_branch_prune_resolves_declared_base_from_agents_md(tmp_path):
    """R1 (deterministic). With no --base, a repo declaring
    `BASE_BRANCH: develop` in AGENTS.md must prove against
    `origin/develop`.

    Reddening mutation: revert `p.add_argument("--base", default=None)` to
    `default="origin/main"`. The summary line reverts to
    `base=origin/main` and this fails.
    """
    repo = _repo_with_origin(tmp_path)
    _git(repo, "checkout", "-q", "-b", "develop")
    _git(repo, "push", "-q", "-u", "origin", "develop")
    _git(repo, "checkout", "-q", "main")
    (repo / "AGENTS.md").write_text("BASE_BRANCH: develop\n")
    _git(repo, "add", "AGENTS.md")
    _git(repo, "commit", "-q", "-m", "declare base")

    proc = _prune(repo, "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert "base=origin/develop" in proc.stdout, proc.stdout
    assert "base=origin/main" not in proc.stdout, proc.stdout
    assert "via agents-md" in proc.stdout, proc.stdout


def test_branch_prune_unresolvable_base_deletes_nothing_and_exits_zero(tmp_path):
    """R2 (deterministic). An AGENTS.md declaration naming a branch that
    does not exist on origin is AUTHORITATIVE and must not fall through:
    zero deletions, no ledger entry, exit 0, and every candidate named on
    stderr.

    Reddening mutation: delete the `if resolved_base is None:` early
    return in main(). The run then proceeds with `resolved_base = None`,
    which either crashes or evaluates branches against a bogus base -
    either way `stale/work` stops surviving and/or the exit code moves.
    """
    repo = _repo_with_origin(tmp_path)
    _git(repo, "branch", "stale/work")
    (repo / "AGENTS.md").write_text("BASE_BRANCH: no-such-branch\n")
    _git(repo, "add", "AGENTS.md")
    _git(repo, "commit", "-q", "-m", "declare bad base")

    proc = _prune(repo)
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    assert (
        "base=unresolved mode=skipped, degraded (gh unavailable) "
        "branches=0 deletions=0 skips=0" in proc.stdout
    ), proc.stdout
    # nothing destroyed, nothing recorded
    branches = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/").stdout.split()
    assert "stale/work" in branches, branches
    assert not (repo / ".agentic" / "branch-prune-ledger.txt").exists()
    assert "origin/no-such-branch" in proc.stderr, proc.stderr


def test_branch_prune_diagnostics_use_its_own_program_prefix(tmp_path):
    """R3, first half (deterministic). The shared resolver's diagnostics
    must name the tool that actually emitted them.

    Reddening mutation: drop `prog="ds-branch-prune"` from the
    `resolve_base_branch` call in main(). Every diagnostic then reverts to
    the `ds-cleanup-worktrees:` default and both assertions fail.
    """
    repo = _repo_with_origin(tmp_path)
    (repo / "AGENTS.md").write_text("BASE_BRANCH: no-such-branch\n")
    _git(repo, "add", "AGENTS.md")
    _git(repo, "commit", "-q", "-m", "declare bad base")

    proc = _prune(repo)
    diag = [ln for ln in proc.stderr.splitlines() if "declared base candidate" in ln]
    assert diag, proc.stderr
    assert all(ln.startswith("ds-branch-prune: ") for ln in diag), diag
    assert "ds-cleanup-worktrees:" not in proc.stderr, proc.stderr


def test_resolver_default_prog_keeps_cleanup_worktrees_output_byte_identical(tmp_path):
    """R3, second half (deterministic). `prog` defaults to
    "ds-cleanup-worktrees", so every pre-existing diagnostic string is
    unchanged for that tool.

    Reddening mutation: change the `prog` default in `_lib`'s
    `resolve_base_branch` signature to anything else (or make it required).
    The prefix assertion fails immediately, and the 11 pre-existing
    resolver tests in test_cleanup_worktrees.py fail alongside it.
    """
    repo = _repo_with_origin(tmp_path)
    (repo / "AGENTS.md").write_text("BASE_BRANCH: no-such-branch\n")

    ref, source, diagnostics = _lib.resolve_base_branch(str(repo), None)
    assert ref is None and source == "unresolved"
    assert diagnostics and all(d.startswith("ds-cleanup-worktrees: ") for d in diagnostics), diagnostics
    # the module-level re-export in ds-cleanup-worktrees resolves to the
    # very same object, so its own callers cannot drift from _lib's
    assert ds_cleanup.resolve_base_branch is _lib.resolve_base_branch


def test_branch_prune_explicit_base_is_used_verbatim_without_validation(tmp_path):
    """R4 (deterministic). An explicit --base bypasses resolution entirely
    and is never second-guessed, even when it names a ref that does not
    exist and even when AGENTS.md declares something else.

    Reddening mutation: add any validation of `explicit_base` in
    `resolve_base_branch` (e.g. returning `(None, "unresolved", ...)` when
    `_ref_exists` is False). The summary line then reads
    `base=unresolved` and this fails.
    """
    repo = _repo_with_origin(tmp_path)
    (repo / "AGENTS.md").write_text("BASE_BRANCH: develop\n")

    proc = _prune(repo, "--dry-run", "--base", "origin/totally-made-up")
    assert proc.returncode == 0, proc.stderr
    assert "base=origin/totally-made-up" in proc.stdout, proc.stdout
    # "explicit" is not announced as an auto-resolution
    assert "auto-resolved" not in proc.stdout, proc.stdout


def test_branch_prune_guards_develop_even_when_base_resolves_elsewhere(tmp_path):
    """R2-adjacent safety invariant (deterministic): `develop` and
    `development` stay in G0's guard set UNCONDITIONALLY, independent of
    what resolution picked - the stray-`develop` hazard disclosed in the
    manifest is bounded by exactly this.

    Reddening mutation: change `base_branches` in main() to
    `set(DEFAULT_BASE_BRANCHES) | {base_local}`, dropping the
    unconditional pair. `develop` then stops reporting SKIP_BASE_BRANCH.
    """
    repo = _repo_with_origin(tmp_path)
    _git(repo, "branch", "develop")
    _git(repo, "branch", "development")

    proc = _prune(repo, "--dry-run", "--explain")
    assert proc.returncode == 0, proc.stderr
    assert "develop: SKIP_BASE_BRANCH" in proc.stdout, proc.stdout
    assert "development: SKIP_BASE_BRANCH" in proc.stdout, proc.stdout


def test_branch_prune_bad_pr_data_is_still_exit_one_on_unresolvable_base(tmp_path):
    """A usage error must never be downgraded to the exit-0 base skip.
    This pins the deliberate ordering (pr-data validation BEFORE base
    resolution) that closed the regression the first draft introduced.

    Reddening mutation: move the `_load_merged_prs` call back below the
    base-resolution block in main(). On this fixture (unresolvable base
    AND a missing --pr-data file) the run then exits 0 instead of 1.
    """
    repo = _repo_with_origin(tmp_path)
    (repo / "AGENTS.md").write_text("BASE_BRANCH: no-such-branch\n")
    _git(repo, "add", "AGENTS.md")
    _git(repo, "commit", "-q", "-m", "declare bad base")

    proc = subprocess.run(
        [
            sys.executable,
            str(PRUNE),
            "--repo",
            str(repo),
            "--dry-run",
            "--pr-data",
            str(tmp_path / "does-not-exist.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    assert "--pr-data file not found" in proc.stderr, proc.stderr


def test_branch_prune_defines_its_own_run_and_does_not_import_the_shared_one():
    """R11 (deterministic). Exactly one `_run` name in ds-branch-prune, and
    it is this file's own - NOT `_lib`'s - and `_lib`'s is not imported
    alongside it under some OTHER name either.

    Reddening mutation 1: replace ds-branch-prune's own `_run` with
    `from _lib import _run`. The identity assertion fires.

    Reddening mutation 2: ADD `from _lib import _run as _shared_run` to
    ds-branch-prune, leaving its own `_run` in place. Every runtime
    identity assertion below stays green (the alias binds a different
    name), so the import scan is what fires. This is the shape the
    bin/_lib.py manifest claims is excluded, and it needs its own pin.
    """
    prune_mod = _load(PRUNE, "ds_branch_prune_calibration")
    assert prune_mod._run is not _lib._run
    # signature discrimination: this file's own takes `input_text`
    import inspect

    assert "input_text" in inspect.signature(prune_mod._run).parameters
    assert "input_text" not in inspect.signature(_lib._run).parameters
    # bin/ds-cleanup-worktrees, by contrast, re-exports _lib's verbatim
    assert ds_cleanup._run is _lib._run

    # Source-text pin for the "under an alias or otherwise" half of the
    # claim, which no runtime assertion above can reach. Parsed rather than
    # grepped so that the prose in this file's own import-block comment -
    # which names `_run` and `_lib` repeatedly, on purpose - cannot satisfy
    # or defeat the check. Two routes are rejected: a direct `from _lib`
    # import of `_run` under ANY binding, and importing the `_lib` module
    # itself, which would make `_lib._run` reachable by attribute access.
    # `from _lib import *` needs no arm: `_lib` defines no `__all__` and
    # `_run` is underscore-prefixed, so a star import provably cannot bind
    # it.
    import ast

    tree = ast.parse(PRUNE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "_lib":
            bindings = [a.asname or a.name for a in node.names]
            assert "_run" not in {a.name for a in node.names}, (
                f"ds-branch-prune:{node.lineno} imports _lib's `_run` "
                f"(bound as {bindings}); it must keep ONLY its own "
                "different-signature `_run`"
            )
        if isinstance(node, ast.Import):
            assert all(a.name != "_lib" for a in node.names), (
                f"ds-branch-prune:{node.lineno} imports the `_lib` module "
                "itself, which reaches `_lib._run` by attribute access"
            )


def test_unresolved_base_summary_composes_mode_and_keeps_the_skips_field(tmp_path):
    """Round-2 Minor 5 (deterministic). The unresolvable-base summary line
    hardcoded `mode=skipped` and omitted the `skips=` field the normal
    summary carries, so a --dry-run invocation was indistinguishable from a
    live one on exactly the path where that distinction matters most - this
    tool deletes branches, and this repo already shipped that defect shape
    once (`mode = "degraded" if degraded else "live"`, never consulting
    args.dry_run).

    Every assertion anchors on the composed `mode=` field TOGETHER with an
    adjacent field on the same line, never a bare substring, so a match
    cannot be satisfied by an unrelated NOTE line elsewhere in the output.

    Reddening mutation (EXECUTED): revert the call to a hardcoded
    `mode=skipped` string. Both stanzas' assertions fail (the live one
    loses its `degraded (gh unavailable)` axis, the dry-run one loses that
    axis AND `dry-run`), and the two runs' summary lines become
    byte-identical, failing the final inequality.
    """
    repo = _repo_with_origin(tmp_path)
    (repo / "AGENTS.md").write_text("BASE_BRANCH: no-such-branch\n")
    _git(repo, "add", "AGENTS.md")
    _git(repo, "commit", "-q", "-m", "declare bad base")

    def _summary(proc):
        lines = [ln for ln in proc.stdout.splitlines() if "base=unresolved" in ln]
        assert len(lines) == 1, proc.stdout
        return lines[0]

    # `_prune` always passes --no-gh, so the degraded axis holds on both
    # runs and only `dry-run` distinguishes them - which is exactly the
    # composition property under test: a third axis must not displace it.
    live = _prune(repo)
    assert live.returncode == 0, live.stderr
    live_line = _summary(live)
    assert (
        "base=unresolved mode=skipped, degraded (gh unavailable) "
        "branches=0 deletions=0 skips=0" in live_line
    ), live_line

    dry = _prune(repo, "--dry-run")
    assert dry.returncode == 0, dry.stderr
    dry_line = _summary(dry)
    assert (
        "base=unresolved mode=skipped, degraded (gh unavailable), dry-run "
        "branches=0 deletions=0 skips=0" in dry_line
    ), dry_line

    # the whole point: the two runs are distinguishable on this line
    assert live_line != dry_line, (live_line, dry_line)

    # fail-safe semantics unchanged by the reporting fix
    assert not (repo / ".agentic" / "branch-prune-ledger.txt").exists()


def test_compose_mode_treats_every_axis_as_independent():
    """Round-2 Minor 5, unit arm (deterministic). `_compose_mode` is the
    SINGLE composer for both summary lines, and each axis contributes
    independently - "live" is emitted only when no axis is set.

    Reddening mutation (EXECUTED): rewrite the body as an either/or chain
    (`return "skipped" if skipped else ("dry-run" if dry_run else "live")`).
    The three multi-axis assertions fail.
    """
    prune_mod = _load(PRUNE, "ds_branch_prune_compose_mode")
    c = prune_mod._compose_mode
    assert c(False, False) == "live"
    assert c(False, True) == "dry-run"
    assert c(True, False) == "degraded (gh unavailable)"
    assert c(True, True) == "degraded (gh unavailable), dry-run"
    assert c(False, False, skipped=True) == "skipped"
    assert c(False, True, skipped=True) == "skipped, dry-run"
    assert c(True, True, skipped=True) == "skipped, degraded (gh unavailable), dry-run"


# --------------------------------------------------------------------------
# U3 - dirty composition (report only)
# --------------------------------------------------------------------------


def _dirty_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "dirty"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "spec@example.com")
    _git(repo, "config", "user.name", "spec")
    (repo / "seed").write_text("seed\n")
    _git(repo, "add", "seed")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def test_dirty_composition_buckets_per_line_not_per_letter(tmp_path):
    """R13 (deterministic). Porcelain v1 emits ONE line per entry with a
    TWO-character status field. This fixture adds a NEW file to the index
    and then modifies it in the working tree, which porcelain reports as
    the single line `AM f1` - one line, two letters (measured; it is NOT
    `MM f1`, which would require the file to have been tracked in HEAD
    first). Bucketing is per LINE, so it must total 1, landing in `added`
    via the FIRST NON-SPACE character `A`.

    The assertions below are deliberately on the TOTAL rather than on the
    bucket name: the property under test is "one line yields one bucket
    increment", which holds whichever bucket wins, and a total-based
    assertion cannot be satisfied by a per-letter implementation.

    Reddening mutation: bucket by iterating the characters of `XY`
    (`for ch in xy: ...`). `AM f1` then yields added=1 AND modified=1, so
    the total is 2 and both total assertions fail.
    """
    repo = _dirty_repo(tmp_path)
    (repo / "f1").write_text("a\n")
    _git(repo, "add", "f1")
    (repo / "f1").write_text("b\n")  # staged add + unstaged modify

    raw: list = []
    comp = ds_cleanup._dirty_composition(str(repo), _raw_out=raw)
    assert comp is not None
    assert raw and "f1" in raw[0]
    assert sum(comp.values()) == len([ln for ln in raw[0].splitlines() if ln.strip()])
    assert sum(comp.values()) == 1, comp
    assert list(comp.values()) == [1], comp


def test_dirty_composition_named_buckets_and_nothing_dropped(tmp_path):
    """R14 (deterministic). An untracked file, a deletion, and a staged
    add each land in their own named bucket, and the bucket total equals
    the porcelain line count - nothing is silently dropped.

    Reddening mutation: `return None` (or `continue`) for any status
    character missing from `_DIRTY_STATUS_BUCKETS` instead of falling
    through to `other`. The sum-equals-line-count assertion fails.
    """
    repo = _dirty_repo(tmp_path)
    (repo / "untracked").write_text("u\n")
    (repo / "seed").unlink()
    (repo / "added").write_text("a\n")
    _git(repo, "add", "added")

    raw: list = []
    comp = ds_cleanup._dirty_composition(str(repo), _raw_out=raw)
    assert comp is not None, raw
    assert comp.get("untracked") == 1, comp
    assert comp.get("deleted") == 1, comp
    assert comp.get("added") == 1, comp
    line_count = len([ln for ln in raw[0].splitlines() if ln.strip()])
    assert sum(comp.values()) == line_count, (comp, raw[0])


def test_dirty_composition_unmapped_letter_lands_in_other(tmp_path, monkeypatch):
    """R14, the `other` arm (deterministic). An unmapped status letter is
    counted, never dropped - and the raw porcelain text is surfaced
    alongside so an `other` line stays attributable.

    Reddening mutation: drop the `"other"` default from the
    `_DIRTY_STATUS_BUCKETS.get(first, "other")` lookup (making it
    `[first]`) - the run raises KeyError instead of reporting. Or skip the
    line entirely - the sum assertion fails.
    """

    class _FakeProc:
        returncode = 0
        stdout = "?? new\nT  typed\nUU conflicted\nZZ weird\n"
        stderr = ""

    monkeypatch.setattr(ds_cleanup, "_run", lambda *a, **k: _FakeProc())
    raw: list = []
    comp = ds_cleanup._dirty_composition("/nonexistent", _raw_out=raw)
    assert comp == {"untracked": 1, "typechange": 1, "unmerged": 1, "other": 1}, comp
    assert sum(comp.values()) == 4
    assert raw[0] == _FakeProc.stdout


def test_dirty_composition_returns_none_on_nonzero_git_exit(tmp_path, monkeypatch):
    """R15 (deterministic). A failed measurement must be None - reported
    as `composition: unavailable` - never an empty or zeroed mapping.

    Reddening mutation: change `if proc.returncode != 0: return None` to
    `return {}`. The `is None` assertion fails, and the tool would then
    report "measured nothing" for a measurement that never happened.
    """

    class _FailProc:
        returncode = 128
        stdout = ""
        stderr = "fatal: not a git repository"

    monkeypatch.setattr(ds_cleanup, "_run", lambda *a, **k: _FailProc())
    assert ds_cleanup._dirty_composition("/nonexistent") is None


def test_dirty_composition_returns_none_on_unparseable_line(monkeypatch):
    """R15, second arm (deterministic). A line too short to carry a
    porcelain v1 status field is unparseable, not zero.

    Reddening mutation: drop the `if len(line) < 3: return None` guard.
    The function then returns a bucket mapping built from a guess.
    """

    class _ShortProc:
        returncode = 0
        stdout = "M\n"
        stderr = ""

    monkeypatch.setattr(ds_cleanup, "_run", lambda *a, **k: _ShortProc())
    assert ds_cleanup._dirty_composition("/nonexistent") is None


def test_no_flag_removes_a_dirty_worktree(tmp_path):
    """R16 (deterministic). `--force-dirty` was designed, reviewed across
    two rounds, and DROPPED. Nothing in the shipped CLI may override the
    dirty refusal.

    Reddening mutation: add a `--force-dirty` argument (or any other
    dirty-override flag) to parse_args. The membership assertion fires.
    """
    proc = subprocess.run(
        [sys.executable, str(CLEANUP), "--help"], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    for banned in ("--force-dirty", "--ignore-dirty", "--allow-dirty", "--force-remove"):
        assert banned not in proc.stdout, (banned, proc.stdout)


def _dirty_registered_worktree(tmp_path: Path, file_count: int) -> Path:
    """A repo with ONE registered worktree under `.agentic/worktrees/`
    holding `file_count` untracked files, so the entry resolves SKIP_DIRTY
    and `--explain` prints its composition plus raw dump.
    """
    repo = _repo_with_origin(tmp_path)
    wt = repo / ".agentic" / "worktrees" / "feature" / "dirty"
    _git(repo, "worktree", "add", "-q", "-b", "feature/dirty", str(wt))
    for i in range(file_count):
        (wt / f"f{i:04d}.txt").write_text("x\n")
    return repo


def _explain(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(CLEANUP),
            "--repo",
            str(repo),
            "--dry-run",
            "--explain",
            "--no-gh",
            "--min-age-hours",
            "0",
            "--activity-window-hours",
            "0",
        ],
        capture_output=True,
        text=True,
    )


def test_explain_raw_dirty_dump_is_capped_and_names_the_omitted_count(tmp_path):
    """Round-2 Major 1 (deterministic). `--explain` is the documented
    triage invocation, and a real abandoned worktree can hold thousands of
    untracked files - the reviewer measured 3007 stdout lines from a
    3000-file fixture before the cap. The raw dump must be BOUNDED per
    entry, and the omitted count must be stated rather than silently lost.

    The bound asserted here is on the OUTPUT SIZE, not on any one string:
    the number of `    | ` raw lines is pinned to exactly the cap even
    though the worktree holds far more, and total stdout is asserted to be
    a small multiple of the cap rather than a function of the file count.

    Reddening mutation (EXECUTED): delete the `[:_EXPLAIN_RAW_DIRTY_LINE_CAP]`
    slice in _run_repo's --explain block (restoring the uncapped
    `for raw_line in raw_lines:`). All 120 raw lines then print, the
    raw-line-count assertion fails at 120 != 20, and the stdout-size bound
    fails alongside it.
    """
    cap = ds_cleanup._EXPLAIN_RAW_DIRTY_LINE_CAP
    file_count = cap * 6
    repo = _dirty_registered_worktree(tmp_path, file_count)

    proc = _explain(repo)
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    out = proc.stdout
    assert "SKIP_DIRTY" in out, out

    raw_lines = [ln for ln in out.splitlines() if ln.startswith("    | ")]
    # exactly the cap: not fewer (the dump still happens) and not more
    # (it is bounded), independent of how much the worktree holds.
    truncation = [ln for ln in raw_lines if "more line(s) omitted" in ln]
    assert len(truncation) == 1, out
    assert len(raw_lines) == cap + 1, (len(raw_lines), file_count, out)

    # the count is capped, never lost
    assert f"{file_count - cap} more line(s) omitted" in truncation[0], truncation
    assert f"cover all {file_count}" in truncation[0], truncation

    # the one-line composition summary is unaffected by the cap and still
    # accounts for every line
    assert f"composition: untracked={file_count}" in out, out

    # output size is a function of the cap, not of the worktree's contents
    assert len(out.splitlines()) < cap * 3, (len(out.splitlines()), out)


def test_explain_raw_dirty_dump_prints_no_truncation_line_under_the_cap(tmp_path):
    """Round-2 Major 1, negative control (deterministic). Below the cap the
    dump is complete and NO truncation line appears - proving the
    truncation line is produced by real overflow rather than printed
    unconditionally, and that the cap does not silently clip a small
    worktree.

    Reddening mutation (EXECUTED): drop the `if omitted > 0:` guard so the
    truncation line prints unconditionally. This fixture then emits
    `... -17 more line(s) omitted` and the absence assertion fires.
    (`>= 0` is NOT a reddening mutation here and was rejected after being
    run: `omitted` is -17 on an under-cap fixture, so the branch stays
    dead either way - the guard's real failure mode is unconditionality,
    not its boundary.) A second, independent reddening mutation: lower
    `_EXPLAIN_RAW_DIRTY_LINE_CAP` below `file_count`, which fires the
    complete-dump assertion instead.
    """
    cap = ds_cleanup._EXPLAIN_RAW_DIRTY_LINE_CAP
    file_count = 3
    assert file_count < cap
    repo = _dirty_registered_worktree(tmp_path, file_count)

    proc = _explain(repo)
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    out = proc.stdout
    raw_lines = [ln for ln in out.splitlines() if ln.startswith("    | ")]
    assert len(raw_lines) == file_count, (raw_lines, out)
    assert "more line(s) omitted" not in out, out


def test_orphan_note_hint_is_conditional_on_explain(tmp_path):
    """Round-2 Minor 6 (deterministic). The NOTE must not tell an operator
    to "re-run with --explain" on a run that already passed --explain and
    is printing the paths a few lines below.

    Reddening mutation (EXECUTED): make `hint` unconditional (drop the
    `if args.explain` branch, always using the re-run wording). The
    --explain assertion fires on the first stanza below.
    """
    repo = _repo_with_origin(tmp_path)
    (repo / ".claude" / "worktrees" / "agent-orphan").mkdir(parents=True)

    base = [sys.executable, str(CLEANUP), "--repo", str(repo), "--dry-run", "--no-gh"]

    with_explain = subprocess.run(base + ["--explain"], capture_output=True, text=True)
    assert with_explain.returncode == 0, with_explain.stderr
    assert "are NOT registered with git" in with_explain.stdout, with_explain.stdout
    assert "Re-run with --explain" not in with_explain.stdout, with_explain.stdout
    assert "The paths are listed below." in with_explain.stdout, with_explain.stdout

    without = subprocess.run(base, capture_output=True, text=True)
    assert without.returncode == 0, without.stderr
    assert "are NOT registered with git" in without.stdout, without.stdout
    assert "Re-run with --explain to see the paths." in without.stdout, without.stdout
    assert "The paths are listed below." not in without.stdout, without.stdout


# --------------------------------------------------------------------------
# U4 - unregistered worktree directories (report only)
# --------------------------------------------------------------------------


def test_unregistered_worktree_dirs_never_names_an_ancestor_of_a_registered_one(tmp_path):
    """R17 (deterministic). This repo's convention nests feature worktrees
    one level deeper (`.agentic/worktrees/fix/<name>`), so a single-level
    glob would report `.agentic/worktrees/fix` - the PARENT of a live
    worktree - as an orphan.

    Reddening mutation: replace the recursive `_walk` with a single-level
    listdir (drop the `_has_registered_descendant` descend branch).
    `.agentic/worktrees/fix` is then reported and the assertion fires.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    registered = repo / ".agentic" / "worktrees" / "fix" / "live"
    registered.mkdir(parents=True)
    orphan_deep = repo / ".agentic" / "worktrees" / "fix" / "dead"
    orphan_deep.mkdir()
    orphan_shallow = repo / ".claude" / "worktrees" / "agent-abc"
    orphan_shallow.mkdir(parents=True)

    found = ds_cleanup._unregistered_worktree_dirs(str(repo), {str(registered)})

    assert ".agentic/worktrees/fix" not in found, found
    assert ".agentic/worktrees/fix/live" not in found, found
    assert ".agentic/worktrees/fix/dead" in found, found
    assert ".claude/worktrees/agent-abc" in found, found
    assert found == sorted(found)


def test_unregistered_worktree_dirs_does_not_descend_into_a_reported_orphan(tmp_path):
    """R17, second arm (deterministic). A reported orphan is reported
    ONCE - its children are not walked, so an operator gets one decision
    per orphan rather than a flood of nested paths.

    Reddening mutation: descend unconditionally instead of only when a
    registered descendant exists. `.claude/worktrees/agent-abc/src` then
    appears and the assertion fires.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    orphan = repo / ".claude" / "worktrees" / "agent-abc"
    (orphan / "src").mkdir(parents=True)

    found = ds_cleanup._unregistered_worktree_dirs(str(repo), set())
    assert found == [".claude/worktrees/agent-abc"], found


def test_unregistered_worktree_dirs_ignores_paths_outside_the_two_prefixes(tmp_path):
    """Deterministic. `evals/` needs no special case: it is outside both
    prefixes and is already SKIP_UNMANAGED's subject.

    Reddening mutation: add a third entry to `_WORKTREE_DIR_PREFIXES`, or
    walk `repo` itself. `evals/.worktrees/wt-1` then appears.
    """
    repo = tmp_path / "repo"
    (repo / "evals" / ".worktrees" / "wt-1").mkdir(parents=True)
    (repo / "node_modules" / "pkg").mkdir(parents=True)
    assert ds_cleanup._unregistered_worktree_dirs(str(repo), set()) == []


def test_orphan_report_prints_no_removal_command(tmp_path):
    """R18 (deterministic). The entire orphan report - the NOTE line and
    the --explain list - must contain no `rm`, no `rmdir`, and no
    `git worktree remove`, not even as a suggestion. That is the whole
    safety argument for shipping a report-only surface whose descent
    predicate could still be wrong.

    Reddening mutation: append any removal hint (e.g. `rm -rf <path>`) to
    the NOTE text. The token scan fires.
    """
    repo = _repo_with_origin(tmp_path)
    (repo / ".claude" / "worktrees" / "agent-orphan").mkdir(parents=True)
    (repo / ".agentic" / "worktrees" / "chore").mkdir(parents=True)

    proc = subprocess.run(
        [
            sys.executable,
            str(CLEANUP),
            "--repo",
            str(repo),
            "--dry-run",
            "--explain",
            "--no-gh",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    combined = proc.stdout + proc.stderr
    assert "are NOT registered with git" in combined, combined
    assert ".claude/worktrees/agent-orphan" in combined, combined
    assert ".agentic/worktrees/chore" in combined, combined

    report = combined[combined.index("are NOT registered with git"):]
    for banned in ("rm -rf", "rmdir", "worktree remove", "rm "):
        assert banned not in report, (banned, report)


def test_orphan_report_is_absent_when_there_are_no_orphans(tmp_path):
    """Deterministic negative control - proves the NOTE above is produced
    by real state, not printed unconditionally.

    Reddening mutation: emit the NOTE outside the `if unregistered_dirs:`
    guard. This fails.
    """
    repo = _repo_with_origin(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(CLEANUP), "--repo", str(repo), "--dry-run", "--explain", "--no-gh"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "are NOT registered with git" not in proc.stdout + proc.stderr


# --------------------------------------------------------------------------
# out-of-scope invariants this change must not disturb
# --------------------------------------------------------------------------


def test_worktree_model_performs_no_io():
    """R8 (deterministic). bin/tests/worktree_model.py asserts "No I/O." in
    its own manifest and is deliberately NOT the destination for the moved
    resolver. It must not gain a subprocess or a filesystem dependency.

    Reddening mutation: add `import subprocess` (or `resolve_base_branch`)
    to worktree_model.py. The import scan fires.
    """
    text = (BIN_DIR / "tests" / "worktree_model.py").read_text()
    for banned in ("import subprocess", "import shutil", "resolve_base_branch", "_run("):
        assert banned not in text, banned


def test_codex_dispatch_keeps_its_own_unrelated_resolver():
    """R12 (deterministic). bin/ds-codex-dispatch defines an INDEPENDENT
    `resolve_base_branch(project: Path) -> str` with different semantics.
    It is out of scope and must not be swept into the shared one by a
    grep-driven edit.

    Reddening mutation: replace that definition with
    `from _lib import resolve_base_branch`. The signature scan fires.
    """
    text = (BIN_DIR / "ds-codex-dispatch").read_text()
    assert "def resolve_base_branch(project: Path) -> str:" in text
    assert "from _lib import resolve_base_branch" not in text


@pytest.mark.parametrize(
    "binary", [PRUNE, CLEANUP], ids=["ds-branch-prune", "ds-cleanup-worktrees"]
)
def test_binary_imports_lib_by_absolute_path_with_empty_pythonpath(binary, tmp_path):
    """R9 (deterministic). Both binaries must find `_lib` from their own
    RESOLVED location, not from an inherited PYTHONPATH and not from
    Python's implicit `sys.path[0]`.

    Invoked through a SYMLINK deliberately - that is the only shape where
    the explicit insert is load-bearing, and it is the shape every adapter
    installs (`~/.local/bin/ds-branch-prune -> <repo>/bin/ds-branch-prune`).
    Python sets `sys.path[0]` to the directory of the script AS NAMED, not
    to its realpath, so under a symlink the repo's `bin/` is not on the
    path at all unless the binary puts it there itself. Running the file
    directly would pass either way and would be a decorative test.

    Reddening mutation: remove `sys.path.insert(0, str(_BIN_DIR /
    "tests"))` from either binary - it then dies with
    `ModuleNotFoundError: worktree_model` under this invocation. Verified
    reddening for both binaries.

    MEASURED AND DISCLOSED: removing the SIBLING insert of `_BIN_DIR`
    itself does NOT redden this test on CPython 3.14, because CPython
    resolves `sys.path[0]` THROUGH the symlink to the target's real
    directory, which is `bin/` - so `_lib` is importable either way there.
    That line is kept as defense in depth (an older interpreter, or a
    copied rather than symlinked PATH shim), not because this test proves
    it load-bearing. Stating that plainly rather than claiming a
    reddening mutation this suite does not actually have.
    """
    link_dir = tmp_path / "fake-path-bin"
    link_dir.mkdir()
    link = link_dir / binary.name
    link.symlink_to(binary)
    proc = subprocess.run(
        [sys.executable, str(link), "--help"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "", "HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    assert "ModuleNotFoundError" not in proc.stderr, proc.stderr
