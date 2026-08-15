#!/usr/bin/env python3
"""
Purpose: pytest suite for bin/ds-agentic-repair - the phantom `.agentic/`
    tree finder/repairer (post-PR-#745 cwd-drift cleanup, DS-agentic-
    repair). Exercises the three-layer classification predicate
    (`classify()`) directly against hermetic fixture trees (no real `git`
    subprocess needed - `hooks/lib/repo_root.py`'s repo-root check is a
    pure `.git`-EXISTENCE check, so a fixture only needs to create a
    `.git` FILE or directory at the right path, never a working repo), and
    the end-to-end CLI (report-only default, `--fix` repair, idempotency,
    dedup) via `main()` invoked in-process against a tmp_path tree.

    Every fixture lives entirely under pytest's own `tmp_path` - never
    against this repo's real `.agentic/` and never against `~/.agentic`
    (the global store), per the ticket brief.

Public API: none (test module; `python3 -m pytest bin/tests/
    test_ds_agentic_repair.py -q`).

Upstream deps: bin/ds-agentic-repair (module under test, loaded via
    importlib.util.spec_from_file_location since it has no `.py`
    extension - the same loading mechanism pytest's own bin/tests/
    conftest-less collection already relies on for sibling `bin/ds-*`
    modules, e.g. bin/tests/test_reap_worktrees.py's subprocess
    invocation; this file additionally imports IN-PROCESS via importlib
    to call `classify()`/`scan()`/`repair_one()` directly for the unit-
    level assertions, then separately drives `main()` for the CLI-level
    assertions).

Downstream consumers: CI (`python3 -m pytest bin/tests/ -q`, auto-collected
    per `.github/workflows/bin-tests.yml`).

Failure modes: each test builds its own isolated tmp_path tree; no shared
    fixture state, no real DinoStack checkout, worktree, or branch state
    is ever touched by this file.

Performance: pure filesystem operations against tmp_path; no network, no
    subprocess. Sub-second for the whole suite.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parent.parent / "ds-agentic-repair"


def _load_module():
    # `spec_from_file_location` cannot infer a loader for an extension-less
    # file (bin/ds-agentic-repair has none - it is invoked directly, not
    # imported, in production) - an explicit SourceFileLoader is required.
    import importlib.machinery

    loader = importlib.machinery.SourceFileLoader("ds_agentic_repair", str(_MODULE_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    # dataclasses.dataclass() looks its defining module up in sys.modules
    # by name during class creation - it must be registered BEFORE
    # exec_module() runs the module body, or module-level @dataclass
    # decorators raise AttributeError on a None lookup.
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


repair = _load_module()


def _make_git_marker(path: Path, as_file: bool = False) -> None:
    """Creates a `.git` entry at `path/.git` - a FILE when `as_file=True`
    (reproducing a linked worktree's own `.git`, which is a file, never a
    directory), a directory otherwise (an ordinary repo root). The repo-
    root check in hooks/lib/repo_root.py is a pure `os.path.exists()`
    probe with no content requirement, so this is sufficient to fake a
    repo root without ever shelling out to real `git`.
    """
    path.mkdir(parents=True, exist_ok=True)
    git_marker = path / ".git"
    if as_file:
        git_marker.write_text("gitdir: /somewhere/else\n", encoding="utf-8")
    else:
        git_marker.mkdir()


def _make_runtime_agentic(path: Path, events_lines=None) -> None:
    """Populates `path` (a `.agentic`-named directory) with the shape a
    real hook-written tree accumulates - at least one Layer-3 runtime-
    state marker, so `classify()` will call it a stray whenever Layers 1/2
    do not already exempt it.
    """
    path.mkdir(parents=True, exist_ok=True)
    if events_lines is not None:
        (path / "events.jsonl").write_text(
            "\n".join(events_lines) + ("\n" if events_lines else ""), encoding="utf-8"
        )
    (path / "context.md").write_text("# stray context\n", encoding="utf-8")
    (path / "wrap").mkdir(exist_ok=True)
    (path / "wrap" / "lock").write_text("stale\n", encoding="utf-8")


def _make_template_agentic(path: Path) -> None:
    """Populates `path` with the shape a SHIPPED SCAFFOLDING TEMPLATE
    carries - seed files only, zero Layer-3 runtime-state markers."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text('{"mode": "opt-out"}\n', encoding="utf-8")
    (path / "learnings.md").write_text("# Learnings\n", encoding="utf-8")


def _snapshot(root: Path) -> dict:
    """rel-path -> content (or None for a directory) for every entry under
    `root`, used to assert byte-identical before/after a run."""
    out = {}
    for p in root.rglob("*"):
        rel = p.relative_to(root).as_posix()
        out[rel] = None if p.is_dir() else p.read_bytes()
    return out


# ---------------------------------------------------------------------------
# Layer classification - unit level.
# ---------------------------------------------------------------------------


def test_stray_at_arbitrary_subdirectory_depth(tmp_path):
    """Positive: a stray at an arbitrary depth (`<repo>/src/foo/.agentic`),
    matching the consumer-repo damage shape - not the nested-inside-
    `.agentic` shape this repo happens to exhibit.

    Mutation that reddens: hardcoding Layer 2's check to
    `path.parent.name == ".agentic"` (i.e. only ever recognizing the
    nested-inside-`.agentic` shape) instead of the general repo-root test
    would misclassify this fixture as legitimate.
    """
    repo = tmp_path / "consumer-repo"
    _make_git_marker(repo)
    stray = repo / "src" / "foo" / ".agentic"
    _make_runtime_agentic(stray, events_lines=["{\"a\":1}"])

    result = repair.classify(stray, repo)
    assert result.verdict == "stray"
    assert result.reason == "not-repo-root+runtime-markers"


def test_stray_admin_style_depth(tmp_path):
    """Positive: `<repo>/admin/.agentic`, a second arbitrary-depth shape.

    Mutation that reddens: inverting Layer 3 (treating ABSENCE of runtime
    markers as the stray signal instead of presence) would flip this to
    "legitimate" since the fixture DOES carry markers.
    """
    repo = tmp_path / "consumer-repo"
    _make_git_marker(repo)
    stray = repo / "admin" / ".agentic"
    _make_runtime_agentic(stray)

    result = repair.classify(stray, repo)
    assert result.verdict == "stray"


def test_stray_dot_agentic_nested_shape(tmp_path):
    """Positive: the real shape observed in this repo, `.agentic/.agentic`.

    Mutation that reddens: `_is_repo_root_dir` treating a `.agentic`
    directory's own presence of a `.git`-shaped file (there is none here,
    but a broken implementation that special-cased "already inside
    .agentic" as automatically a repo root) would misclassify this.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    stray = repo / ".agentic" / ".agentic"
    _make_runtime_agentic(stray)

    result = repair.classify(stray, repo)
    assert result.verdict == "stray"


def test_stray_dot_agentic_memory_nested_shape(tmp_path):
    """Positive: the second real shape observed in this repo,
    `.agentic/memory/.agentic`.

    Mutation that reddens: same as above - any shortcut that treats
    directories two-or-more levels under `.agentic/` as automatically
    legitimate would misclassify this.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    stray = repo / ".agentic" / "memory" / ".agentic"
    _make_runtime_agentic(stray)

    result = repair.classify(stray, repo)
    assert result.verdict == "stray"


def test_negative_shipped_template(tmp_path):
    """Negative control: a shipped-template fixture (content/templates/
    .agentic shape - seed files only, zero runtime markers, and ALSO
    on the Layer-1 exact-exclusion list - both layers independently
    protect it, verified separately below).

    Mutation that reddens: disabling `_is_excluded` (Layer 1) changes the
    verdict's REASON from "excluded" to "no-runtime-markers" - Layer 3
    still saves the verdict itself (this fixture carries zero runtime
    markers), but the reason-string assertion below catches the loss of
    Layer 1 protection directly. Separately, deleting the Layer-3 content
    guard entirely (making Layer 2's repo-root test the only
    discriminator, with Layer 1 ALSO disabled) would misclassify this as
    a stray outright, since content/templates is not itself a repo root -
    the false-positive class the ticket brief warns breaks
    `/ds-init-project` scaffolding.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    tmpl = repo / "content" / "templates" / ".agentic"
    _make_template_agentic(tmpl)

    before = _snapshot(repo)
    result = repair.classify(tmpl, repo)
    assert result.verdict == "legitimate"
    assert result.reason == "excluded"

    # --fix must be a true no-op against this fixture.
    rc = repair.main(["--repo", str(repo), "--fix"])
    assert rc == 0
    after = _snapshot(repo)
    assert before == after


def test_negative_worktree_root(tmp_path):
    """Negative control: a worktree-root fixture with `.git` as a FILE
    (a linked git worktree's own `.git`), carrying a stray-shaped
    `.agentic` with real runtime markers underneath it.

    Mutation that reddens: using `os.path.isdir(".git")` instead of
    `os.path.exists(".git")` anywhere in the repo-root check would fail
    to recognize this fixture as a repo root (a linked worktree's `.git`
    is a file, never a directory) and misclassify its `.agentic` as a
    stray - corrupting live isolation-worktree state, per the ticket
    brief's central warning.

    Note: `.agentic` directly under `repo` now hits the flat
    `rel_posix == ".agentic"` invariant (checked before Layer 2, see
    round-2 rework), so the reason string is "repo-root-agentic" rather
    than "parent-is-repo-root" - the verdict (legitimate) is what this
    test guards, not which of the two independent mechanisms produced it.
    """
    repo = tmp_path / "worktree-agent-xyz"
    _make_git_marker(repo, as_file=True)
    wt_agentic = repo / ".agentic"
    _make_runtime_agentic(wt_agentic, events_lines=["{\"b\":2}"])

    before = _snapshot(repo)
    result = repair.classify(wt_agentic, repo)
    assert result.verdict == "legitimate"
    assert result.reason == "repo-root-agentic"

    rc = repair.main(["--repo", str(repo), "--fix"])
    assert rc == 0
    after = _snapshot(repo)
    assert before == after


def test_negative_nested_worktree_root(tmp_path):
    """Negative control: a linked git worktree whose root sits INSIDE the
    scanned repo (e.g. `repo/.claude/worktrees/agent-xyz`, the real shape
    every isolation-worktree spawn produces), carrying its own
    `.agentic` directly under its own root.

    Round-3 rework: `test_negative_worktree_root` above was reworked in
    round 2 to give the worktree root ITSELF as `repo` (`.agentic` sits
    directly under the scanned root), so `rel_posix == ".agentic"` and the
    flat invariant at the top of `classify()` short-circuits before Layer
    2 (`_is_repo_root_dir`) ever runs - that test now exercises the flat
    invariant, not Layer 2, and lost coverage for Layer 2's `.git`-as-FILE
    handling. This fixture nests the worktree root one level inside the
    scanned repo instead, so `rel_posix` is
    `.claude/worktrees/agent-xyz/.agentic` (never the bare string
    `.agentic`), the flat invariant does not fire, and only Layer 2
    (`.agentic`'s PARENT, the worktree root, is itself a repo root via a
    `.git` FILE) can save it from Layer 3's runtime-marker match.

    Mutation that reddens: replacing `_is_repo_root_dir`'s body with
    `return (path / ".git").is_dir()` treats a linked worktree's `.git`
    FILE as "not a repo root" (`is_dir()` is False for a file), so the
    worktree root fails Layer 2, this `.agentic` falls through to Layer 3
    (which finds real runtime markers), and it misclassifies as a stray -
    exactly the live corruption hazard this layer exists to prevent for
    isolation-worktree state. Confirmed: this mutation leaves all tests in
    this suite green if this test is absent (verified against the
    pre-fix, round-2 state of this file), and reddens with this test
    present.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    wt_root = repo / ".claude" / "worktrees" / "agent-xyz"
    _make_git_marker(wt_root, as_file=True)
    wt_agentic = wt_root / ".agentic"
    _make_runtime_agentic(wt_agentic, events_lines=["{\"b\":2}"])

    before = _snapshot(repo)
    result = repair.classify(wt_agentic, repo)
    assert result.verdict == "legitimate"
    assert result.reason == "parent-is-repo-root"

    rc = repair.main(["--repo", str(repo), "--fix"])
    assert rc == 0
    after = _snapshot(repo)
    assert before == after


def test_negative_evals_style_fixture(tmp_path):
    """Negative control: an `evals/`-style fixture - git-untracked test
    content (repo decision #203) carrying runtime-shaped markers that
    cannot be safely inspected by content alone.

    Mutation that reddens: removing the `evals/` prefix from
    `_EXCLUDED_PATH_PREFIXES` would let Layer 2 (parent not a repo root)
    and Layer 3 (runtime markers present) both agree this is a stray -
    exactly the untracked-content risk the exclusion list exists to
    cover independently of content inspection.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    fixture = repo / "evals" / "icl_vs_orchestration" / ".agentic"
    _make_runtime_agentic(fixture, events_lines=["{\"c\":3}"])

    before = _snapshot(repo)
    result = repair.classify(fixture, repo)
    assert result.verdict == "legitimate"
    assert result.reason == "excluded"

    rc = repair.main(["--repo", str(repo), "--fix"])
    assert rc == 0
    after = _snapshot(repo)
    assert before == after


def test_negative_archive_dir_itself(tmp_path):
    """Negative control: after a real `--fix` run creates the tool's own
    archive directory, a second scan must never treat any path under
    `.agentic/stray-agentic-archive/` as a fresh stray, and the archive's
    own content must be byte-identical before and after that second run.

    Mutation that reddens: removing `.agentic/stray-agentic-archive/`
    from `_EXCLUDED_PATH_PREFIXES` reproduces the earlier-design bug
    named in the module docstring ("Archive placement") - a stray whose
    remainder gets archived, then re-discovered and re-archived under a
    fresh timestamp on the very next scan, unbounded.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    stray = repo / "src" / "foo" / ".agentic"
    _make_runtime_agentic(stray, events_lines=["{\"d\":4}"])

    rc = repair.main(["--repo", str(repo), "--fix"])
    assert rc == 0
    archive_root = repo / ".agentic" / "stray-agentic-archive"
    assert archive_root.is_dir()
    # The archived remainder must not itself contain a directory literally
    # named ".agentic" anywhere (the flattening guarantee).
    assert not any(p.name == ".agentic" for p in archive_root.rglob("*"))

    before = _snapshot(archive_root)
    results = repair.scan(repo)
    archived_entries = [r for r in results if r.rel_posix.startswith(".agentic/stray-agentic-archive/")]
    assert archived_entries == []

    rc2 = repair.main(["--repo", str(repo), "--fix"])
    assert rc2 == 0
    after = _snapshot(archive_root)
    assert before == after


# ---------------------------------------------------------------------------
# CLI-level: idempotency, dedup, report-only default.
# ---------------------------------------------------------------------------


def test_idempotency_second_fix_is_byte_identical(tmp_path):
    """Two `--fix` runs; the canonical events.jsonl must be byte-identical
    after the second (there is nothing left to find - every stray tree
    was already removed by the first run).

    Mutation that reddens: a merge that appends lines unconditionally
    instead of deduping against `canonical_path`'s EXISTING content (not
    just against lines seen earlier in the same run) would duplicate
    every line on hypothetical repeated exposure; more directly here, a
    bug that fails to actually REMOVE the stray directory after a
    successful merge/archive would cause the second run to re-merge the
    same events, breaking idempotency outright.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    stray = repo / "src" / ".agentic"
    _make_runtime_agentic(stray, events_lines=['{"x":1}', '{"x":2}'])

    rc1 = repair.main(["--repo", str(repo), "--fix"])
    assert rc1 == 0
    canonical = repo / ".agentic" / "events.jsonl"
    first_bytes = canonical.read_bytes()
    assert not stray.exists()

    rc2 = repair.main(["--repo", str(repo), "--fix"])
    assert rc2 == 0
    second_bytes = canonical.read_bytes()
    assert first_bytes == second_bytes


def test_dedup_overlapping_records_merge_without_duplication(tmp_path):
    """Overlapping records (present both in the canonical file already and
    in the stray) merge without duplication, preserving order: existing
    canonical lines first (unchanged order), then the stray's own new
    lines in the stray's original order.

    Mutation that reddens: dropping the `seen` set (or building it only
    from canonical content and never updating it as new lines are
    appended) would either duplicate an overlapping line, or - if two
    strays share a line - duplicate it a second time across strays in the
    same run.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    canonical = repo / ".agentic" / "events.jsonl"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text('{"e":1}\n{"e":2}\n', encoding="utf-8")

    stray = repo / "src" / ".agentic"
    # "{"e":2}" overlaps with the canonical file; "{"e":3}" is new.
    _make_runtime_agentic(stray, events_lines=['{"e":2}', '{"e":3}'])

    rc = repair.main(["--repo", str(repo), "--fix"])
    assert rc == 0
    lines = canonical.read_text(encoding="utf-8").splitlines()
    assert lines == ['{"e":1}', '{"e":2}', '{"e":3}']
    assert lines.count('{"e":2}') == 1


def test_report_only_default_deletes_nothing(tmp_path):
    """No flags at all (the default) must behave IDENTICALLY to
    `--dry-run`: report-only, zero filesystem writes.

    Mutation that reddens: defaulting `do_fix` to True instead of gating
    strictly on `args.fix` would delete the stray tree even with no flags
    passed at all - the single most dangerous possible default for a
    destructive tool.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    stray = repo / "src" / ".agentic"
    _make_runtime_agentic(stray, events_lines=['{"y":1}'])

    before = _snapshot(repo)
    rc = repair.main(["--repo", str(repo)])
    assert rc == 0
    after = _snapshot(repo)
    assert before == after
    assert stray.is_dir()

    # --dry-run must be identical.
    rc2 = repair.main(["--repo", str(repo), "--dry-run"])
    assert rc2 == 0
    after2 = _snapshot(repo)
    assert before == after2
    assert stray.is_dir()


def test_cli_subprocess_json_report_lists_stray(tmp_path):
    """End-to-end subprocess invocation (not in-process) sanity check: the
    tool is genuinely executable as a CLI, and --json reports the stray.

    Mutation that reddens: any bug making the CLI unparseable/non-
    executable as a standalone script (e.g. a bad shebang, or a module-
    level exception before argparse runs) would fail this before any
    assertion even executes.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    stray = repo / "src" / ".agentic"
    _make_runtime_agentic(stray, events_lines=['{"z":1}'])

    proc = subprocess.run(
        [sys.executable, str(_MODULE_PATH), "--repo", str(repo), "--json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    report = json.loads(proc.stdout)
    assert report["mode"] == "report-only"
    assert report["strays_found"] == 1
    assert report["strays"][0]["path"] == "src/.agentic"
    # Report-only subprocess run must not have touched the fixture.
    assert stray.is_dir()


def test_repo_not_a_git_repository_errors(tmp_path):
    """Usage error: --repo has no `.git` ancestor anywhere up the tree.

    Mutation that reddens: dropping the `found_git_ancestor` guard in
    `_resolve_repo` would silently accept a non-repo directory and scan
    it as if it were a real project root.
    """
    not_a_repo = tmp_path / "just-a-directory"
    not_a_repo.mkdir()
    rc = repair.main(["--repo", str(not_a_repo)])
    assert rc == 1


# ---------------------------------------------------------------------------
# Round-2 rework regression tests (Critical + Major 1-3 + Minor). Each was
# confirmed failing against the pre-fix code before its fix landed - see
# the engineer return summary for the pre-fix output captured for each.
# ---------------------------------------------------------------------------


def test_critical_degraded_resolver_refuses_entire_run(tmp_path, monkeypatch):
    """CRITICAL: when the repo-root resolver fails to load (`_REPO_ROOT is
    None`), the tool must refuse to run AT ALL - not merely refuse --fix -
    and must NOT delete the repo's own live top-level `.agentic/`.

    Pre-fix behavior (reproduced): `_is_repo_root_dir` returned False
    unconditionally on a None resolver, collapsing "could not determine"
    into "not a repo root"; the repo's own `.agentic/` (which always
    carries runtime markers) then cleared Layer 2 as a false negative and
    was classified `stray`, and `--fix` destroyed it with `rc == 0`.

    Mutation that reddens: removing the `if _REPO_ROOT is None: return 1`
    guard at the top of `main()` restores exactly that path.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    live_agentic = repo / ".agentic"
    _make_runtime_agentic(live_agentic, events_lines=['{"live":1}'])

    monkeypatch.setattr(repair, "_REPO_ROOT", None)

    before = _snapshot(repo)
    rc = repair.main(["--repo", str(repo), "--fix"])
    assert rc == 1
    after = _snapshot(repo)
    assert before == after
    assert live_agentic.is_dir()


def test_critical_own_agentic_never_stray_even_if_layer2_fails(tmp_path, monkeypatch):
    """CRITICAL: the flat `rel_posix == ".agentic"` invariant in
    `classify()` protects the repo's own top-level `.agentic/` even when
    Layer 2 (`_is_repo_root_dir`) itself is broken/returns False - it must
    not be the sole thing standing between this directory and destruction.

    Pre-fix behavior (reproduced): with no flat invariant, forcing
    `_is_repo_root_dir` to return False for ANY input reproduces the exact
    degraded-resolver collapse from the Critical finding and `classify()`
    returns "stray".

    Mutation that reddens: removing the `if rel_posix == ".agentic":
    return ... "legitimate" ...` short-circuit at the top of `classify()`.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    live_agentic = repo / ".agentic"
    _make_runtime_agentic(live_agentic, events_lines=['{"live":1}'])

    monkeypatch.setattr(repair, "_is_repo_root_dir", lambda path: False)

    result = repair.classify(live_agentic, repo)
    assert result.verdict == "legitimate"
    assert result.reason == "repo-root-agentic"


def test_critical_archive_dir_refused_when_descendant_of_stray_dir(tmp_path):
    """CRITICAL: `repair_one()` must refuse to proceed if the computed
    `archive_dir` is ever a descendant of the `stray_dir` it is about to
    `shutil.rmtree`, independent of whether `classify()` should have
    prevented this shape from ever reaching `repair_one()` in the first
    place. Constructed directly (bypassing `classify()`/`scan()`, which
    already exclude this shape via the flat invariant) to prove the guard
    inside `repair_one()` itself, not merely its callers' good behavior.

    Pre-fix behavior (reproduced): `archive_dir` is computed as
    `repo_root/.agentic/stray-agentic-archive/<leaf>` with no check that
    it is outside `stray_dir` - when `stray_dir` IS `repo_root/.agentic`,
    the archive is written inside the very tree `shutil.rmtree(stray_dir)`
    then destroys, permanently losing the archived remainder in the same
    operation that was supposed to preserve it.

    Mutation that reddens: removing the `is_descendant` check (and its
    early `return RepairResult(..., ok=False, ...)`) in `repair_one()`.

    Round-3 note: this fixture's `stray_dir` (`repo/.agentic`, forced via
    a hand-built `ClassifiedDir`) now trips the unconditional
    canonical-tree guard added at the TOP of `repair_one()` (round-3
    Major 3 fix) before the archive-destination check below it is ever
    reached - both guards independently refuse this shape, so the detail
    message assertion below accepts either guard's wording. The narrower
    `test_critical_repair_one_refuses_canonical_agentic_with_only_events`
    test below isolates the specific shape (only `events.jsonl`, no
    remainder) where the archive-destination check alone used to be
    unreachable.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    live_agentic = repo / ".agentic"
    _make_runtime_agentic(live_agentic, events_lines=['{"live":1}'])
    # A remainder file besides events.jsonl, so an archive_dir actually
    # gets computed and this guard has something to refuse.
    (live_agentic / "extra-remainder.txt").write_text("do not lose me\n", encoding="utf-8")

    entry = repair.ClassifiedDir(live_agentic, ".agentic", "stray", "forced-for-test")
    result = repair.repair_one(repo, entry)

    assert result.ok is False
    assert result.archived is False
    assert result.removed is False
    assert "archive_dir" in result.detail or "descendant" in result.detail or "canonical" in result.detail
    # The directory and its contents must survive completely untouched.
    assert live_agentic.is_dir()
    assert (live_agentic / "extra-remainder.txt").read_text(encoding="utf-8") == "do not lose me\n"
    assert (live_agentic / "context.md").is_file()


def test_critical_repair_one_refuses_canonical_agentic_with_only_events(tmp_path):
    """Round-3 MAJOR 3 regression: `repair_one()` called directly with a
    `ClassifiedDir` for the canonical `.agentic` tree, holding ONLY
    `events.jsonl` (no other remainder), must refuse rather than delete
    the live canonical tree.

    Pre-fix behavior (reproduced by the reviewer): with `remainder_names`
    empty, the `if remainder_names:` block - which contained the ONLY
    guard against `stray_dir` being the canonical tree - never ran at
    all, so `shutil.rmtree(stray_dir)` proceeded unguarded and deleted
    `repo/.agentic` (events.jsonl included), returning
    `ok=True removed=True detail=ok` with no archive and `merged_lines=0`
    even though canonical and stray were the SAME directory (the
    round-1 Critical shape, still reachable through this specific
    remainder-less entry point despite both upstream guards).

    Mutation that reddens: deleting the unconditional
    `if stray_dir == canonical_agentic:` guard at the top of
    `repair_one()` (added in round 3, narrowed to equality-only in
    round 4, before the `remainder_names` branch) restores exactly this
    behavior - confirmed by removing it and re-running this test, which
    fails with `result.removed is True` and the canonical tree gone.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    live_agentic = repo / ".agentic"
    _make_runtime_agentic(live_agentic, events_lines=['{"live":1}'])
    # Deliberately NO extra remainder file - only events.jsonl, the exact
    # shape that left the old archive-destination check unreached.
    assert sorted(p.name for p in live_agentic.iterdir()) == ["context.md", "events.jsonl", "wrap"]
    # (context.md/wrap are runtime markers from _make_runtime_agentic;
    # remove them so the fixture is EXACTLY the reviewer's repro shape -
    # events.jsonl and nothing else.)
    (live_agentic / "context.md").unlink()
    import shutil as _shutil

    _shutil.rmtree(live_agentic / "wrap")
    assert [p.name for p in live_agentic.iterdir()] == ["events.jsonl"]

    entry = repair.ClassifiedDir(live_agentic, ".agentic", "stray", "forced-for-test")
    result = repair.repair_one(repo, entry)

    assert result.ok is False
    assert result.removed is False
    assert result.archived is False
    assert "canonical" in result.detail
    # The canonical tree, events.jsonl included, must survive completely
    # untouched.
    assert live_agentic.is_dir()
    assert (live_agentic / "events.jsonl").read_text(encoding="utf-8") == '{"live":1}\n'


def test_major_round4_repair_one_repairs_nested_stray_inside_canonical(tmp_path):
    """ROUND 4 MAJOR 1 regression: `repair_one()` must actually REPAIR a
    stray nested INSIDE the canonical `.agentic/` tree - the primary shape
    `_iter_agentic_dirs`'s own docstring calls "the exact shape this
    repo's live tree exhibits" (e.g. `.agentic/.agentic`,
    `.agentic/memory/.agentic`) and the tool's primary use case. This is
    the OPPOSITE direction from the round-3 canonical-tree guard (which
    protects `stray_dir` from BEING or CONTAINING canonical) - here
    `stray_dir` is CONTAINED BY canonical, and must still be removed.

    Pre-fix behavior (the over-broad round-3 guard, reproduced by the
    round-4 reviewer against the primary checkout): the guard read
    `if stray_dir == canonical_agentic or canonical_agentic in
    stray_dir.parents:` - the second disjunct fires whenever `stray_dir`
    is nested under canonical, refusing every phantom of this shape with
    `ok=False removed=False archived=False`, even though this is exactly
    the shape the tool exists to clean up.

    Mutation that reddens: restoring the `or canonical_agentic in
    stray_dir.parents` disjunct to the guard in `repair_one()` turns this
    test red (`result.ok` becomes `False`, `result.removed` becomes
    `False`, and the nested stray survives).
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    canonical = repo / ".agentic"
    canonical.mkdir(parents=True)
    (canonical / "events.jsonl").write_text('{"canonical":1}\n', encoding="utf-8")

    nested_stray = canonical / ".agentic"
    _make_runtime_agentic(nested_stray, events_lines=['{"nested":1}'])
    (nested_stray / "extra-remainder.txt").write_text("archive me\n", encoding="utf-8")

    entry = repair.ClassifiedDir(nested_stray, ".agentic/.agentic", "stray", "forced-for-test")
    result = repair.repair_one(repo, entry)

    assert result.ok is True
    assert result.removed is True
    assert result.archived is True
    assert result.merged_lines == 1
    # The nested stray is gone, the canonical tree (a sibling ancestor of
    # the stray, not the stray itself) survives untouched, and the
    # canonical events.jsonl now carries both lines.
    assert not nested_stray.exists()
    assert canonical.is_dir()
    merged = (canonical / "events.jsonl").read_text(encoding="utf-8")
    assert '{"canonical":1}' in merged
    assert '{"nested":1}' in merged


def test_major1_dry_run_and_fix_together_rejected(tmp_path):
    """MAJOR 1: `--dry-run --fix` together must be rejected, not silently
    resolved by letting `--fix` win. For a tool whose only irreversible
    mode is `--fix`, the defensive-habit invocation must never be the
    destructive one.

    Pre-fix behavior (reproduced): `do_fix = bool(args.fix)` ignored
    `--dry-run` entirely; `main(["--repo", R, "--dry-run", "--fix"])`
    printed `mode=fix` and removed the stray tree, with `rc == 0`.

    Mutation that reddens: removing the `if args.dry_run and args.fix:
    ... return 1` check at the top of `main()`.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    stray = repo / "src" / ".agentic"
    _make_runtime_agentic(stray, events_lines=['{"combo":1}'])

    before = _snapshot(repo)
    rc = repair.main(["--repo", str(repo), "--dry-run", "--fix"])
    assert rc == 1
    after = _snapshot(repo)
    assert before == after
    assert stray.is_dir()


def test_major2_merge_without_trailing_newline_does_not_corrupt(tmp_path):
    """MAJOR 2: merging into a canonical events.jsonl that does NOT end in
    a trailing newline (a truncated/interrupted write, or a foreign
    writer) must not concatenate the first new line onto the end of the
    last existing line.

    Pre-fix behavior (reproduced): canonical `{"canon":1}` (no trailing
    newline) plus stray `{"stray":1}` produced the single unparseable line
    `{"canon":1}{"stray":1}\\n` - BOTH records lost.

    Mutation that reddens: removing the `needs_leading_newline` check (and
    its `fh.write("\\n")`) in `_merge_events()`.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)
    canonical = repo / ".agentic" / "events.jsonl"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text('{"canon":1}', encoding="utf-8")  # deliberately no trailing \n
    assert not canonical.read_bytes().endswith(b"\n")

    stray = repo / "src" / ".agentic"
    _make_runtime_agentic(stray, events_lines=['{"stray":1}'])

    rc = repair.main(["--repo", str(repo), "--fix"])
    assert rc == 0

    lines = canonical.read_text(encoding="utf-8").splitlines()
    assert lines == ['{"canon":1}', '{"stray":1}']


def test_major3_undecodable_stray_isolated_does_not_abort_run(tmp_path):
    """MAJOR 3: an undecodable stray events.jsonl (raising
    UnicodeDecodeError, a ValueError subclass - NOT an OSError) must be
    isolated to that one entry's per-entry failure and must NOT abort
    processing of other strays in the same run.

    Pre-fix behavior (reproduced): `repair_one` caught only `OSError`;
    `UNCAUGHT EXCEPTION: UnicodeDecodeError` propagated out of the
    per-entry loop in `main()`, and every stray after the failing one was
    silently never processed.

    Mutation that reddens: narrowing the `except (OSError,
    UnicodeDecodeError, ValueError)` clause in `repair_one()` back to
    `except OSError`.

    `rc == 1` (not 0) is asserted below: `bad_stray`'s repair genuinely
    fails (`ok=False`), and `main()` now returns nonzero whenever any
    repair fails (round-3 Minor fix) - this test's whole point is that
    the OTHER stray still gets processed despite that failure, not that
    the run reports success.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)

    bad_stray = repo / "aaa-bad" / ".agentic"
    _make_runtime_agentic(bad_stray)
    (bad_stray / "events.jsonl").write_bytes(b"\xff\xfe not valid utf-8\n")

    good_stray = repo / "zzz-good" / ".agentic"
    _make_runtime_agentic(good_stray, events_lines=['{"good":1}'])

    rc = repair.main(["--repo", str(repo), "--fix"])
    assert rc == 1

    # The undecodable stray's data is preserved in place, unmerged - never
    # removed, per the per-entry-failure discipline.
    assert bad_stray.is_dir()

    # The good stray, sorted AFTER the bad one alphabetically, must still
    # have been processed and removed - proving the run did not abort.
    assert not good_stray.exists()
    canonical = repo / ".agentic" / "events.jsonl"
    assert '{"good":1}' in canonical.read_text(encoding="utf-8").splitlines()


def test_minor_nested_evals_directory_protected(tmp_path):
    """MINOR: `evals/` protection must apply wherever `evals` appears as a
    path COMPONENT, not only as a root-anchored prefix - a nested
    `sub/evals/case/.agentic` must be excluded exactly like a root-level
    `evals/case/.agentic`. `my-evals/` (a similarly-named but DISTINCT
    directory) must NOT be excluded by this rule.

    Pre-fix behavior (reproduced): `rel_posix.startswith("evals/")` is
    False for `"sub/evals/case/.agentic"` (it starts with `"sub/"`), so
    the fixture fell through Layer 1 to Layers 2/3 and classified `stray`.

    Mutation that reddens: reverting `_is_excluded()` to the
    root-anchored `rel_posix.startswith("evals/")` form.
    """
    repo = tmp_path / "dinostack"
    _make_git_marker(repo)

    nested_evals = repo / "sub" / "evals" / "case" / ".agentic"
    _make_runtime_agentic(nested_evals, events_lines=['{"nested-evals":1}'])

    result = repair.classify(nested_evals, repo)
    assert result.verdict == "legitimate"
    assert result.reason == "excluded"

    my_evals = repo / "my-evals" / "case" / ".agentic"
    _make_runtime_agentic(my_evals, events_lines=['{"my-evals":1}'])
    my_result = repair.classify(my_evals, repo)
    assert my_result.verdict == "stray"

    # --fix over the whole tree: nested_evals survives, my_evals is
    # correctly repaired away (not a false-positive exclusion).
    rc = repair.main(["--repo", str(repo), "--fix"])
    assert rc == 0
    assert nested_evals.is_dir()
    assert not my_evals.exists()
