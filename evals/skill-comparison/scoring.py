"""
Purpose: Run held-out pytest in isolation and compute pass/fail plus diff-hygiene
         diagnostics for one (task, condition, replicate) cell. Computes the
         engineer's diff from the working directory (git diff against seed_commit)
         as the ground-truth source of changes; falls back to transcript parsing
         only when fix_phase_dir is unavailable (dry-run paths).

Public API:
    score_cell(
        task_slug: str,
        transcript: str,
        task_meta: dict,
        fix_phase_dir: Path,
        held_out_dir: Path,
        tier3_ctx: "Tier3Context | None" = None,
        pytest_timeout: int = 120,
        fail_to_pass: "list[str] | None" = None,
        seed_commit: str = "",
    ) -> ScoringResult

    ScoringResult (dataclass):
        pass_fail: bool          # True iff all held-out tests pass
        score_primary: float     # 1.0 on pass, 0.0 on fail
        lines_touched: int       # total diff lines (additions + deletions)
        files_touched: int       # number of files changed in the diff
        scope_creep_flag: bool   # True if any touched file is outside known_affected_files
        held_out_failures: list[str]  # failing test IDs (empty on pass)
        pytest_returncode: int   # raw pytest exit code
        diff_text: str           # raw diff (from workdir or transcript fallback)
        diagnostics: dict        # bag of supplementary data

    compute_engineer_diff_from_workdir(fix_phase_dir: Path, seed_commit: str) -> str
        Run `git diff <seed_commit>` in fix_phase_dir to get the engineer's changes
        relative to the post-seeding state. Returns "" on any git failure.

    extract_diff_from_transcript(transcript: str) -> str
        Extract the git diff from an engineer's transcript. Returns "" if none found.
        Used as a fallback when fix_phase_dir is unavailable (dry-run paths).

    compute_diff_hygiene(diff_text: str, known_affected_files: list[str]) -> dict
        Parse a unified diff; return lines_touched, files_touched, scope_creep_flag.

    _convert_unittest_id_to_pytest(node_id: str) -> str
        Convert a unittest-style "test_method (module.path.TestClass)" ID to
        pytest node-id format "module/path.py::TestClass::test_method".
        Returns the input unchanged if it does not match the unittest pattern.

Upstream deps: stdlib subprocess, pathlib, re, dataclasses, typing, tempfile, shutil,
               logging.
               evals.runner.isolator.Tier3Docker (optional; used for in-container
               pytest when tier3_ctx is provided).

Downstream consumers: evals/skill-comparison/runner.py.

Failure modes: pytest invocation failure is captured into pytest_returncode and
               held_out_failures; it does not raise. Diff extraction failure
               (workdir unavailable and no diff in transcript) sets diff_text=""
               and lines_touched=0, files_touched=0, scope_creep_flag=False.
               Known-affected-files mismatch (scope_creep_flag) is a diagnostic,
               not an error.

Performance: pytest run is the dominant cost (~<120s per brief constraint).
             Diff parsing is O(diff lines); negligible.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ScoringResult:
    """Result of scoring one (task, condition, replicate) cell."""

    pass_fail: bool
    score_primary: float          # 1.0 = pass, 0.0 = fail
    lines_touched: int
    files_touched: int
    scope_creep_flag: bool
    held_out_failures: list[str] = field(default_factory=list)
    pytest_returncode: int = -1
    diff_text: str = ""
    diagnostics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Diff extraction
# ---------------------------------------------------------------------------

# Patterns that delimit a git diff block in a transcript.
# We look for a "diff --git" header or a triple-backtick "```diff" fenced block.
_DIFF_FENCE_RE = re.compile(
    r"```diff\s*\n(.*?)```",
    re.DOTALL,
)
_GIT_DIFF_RE = re.compile(
    r"(diff --git .+?)(?=\ndiff --git |\Z)",
    re.DOTALL,
)


def extract_diff_from_transcript(transcript: str) -> str:
    """Extract the git diff from an engineer's transcript.

    Tries, in order:
    1. Triple-backtick ```diff ... ``` fenced block.
    2. Raw `diff --git` blocks.

    Returns the first match found, or "" if no diff is present.
    """
    if not transcript:
        return ""

    # 1. Fenced block.
    fenced = _DIFF_FENCE_RE.search(transcript)
    if fenced:
        return fenced.group(1).rstrip()

    # 2. Raw diff blocks.
    raw_diffs = _GIT_DIFF_RE.findall(transcript)
    if raw_diffs:
        return "\n".join(raw_diffs).rstrip()

    return ""


# ---------------------------------------------------------------------------
# Workdir-based diff (ground truth)
# ---------------------------------------------------------------------------


def compute_engineer_diff_from_workdir(fix_phase_dir: Path, seed_commit: str) -> str:
    """Return the engineer's diff relative to seed_commit in fix_phase_dir.

    Runs `git diff <seed_commit>` in fix_phase_dir to capture exactly what the
    engineer changed after seeding. This is the authoritative diff source for
    production scoring - it cannot be confused with tool_use payloads or other
    diff-like text embedded in the CLI transcript.

    Args:
        fix_phase_dir: host-side directory containing the engineer's working tree.
        seed_commit: SHA of the post-seeding commit (from seed_fix_phase return value).
                     When empty, falls back to `git diff HEAD` which compares the
                     working tree (including unstaged changes) against HEAD.

    Returns:
        Raw unified diff text, or "" on any git invocation failure.
    """
    if not fix_phase_dir or not fix_phase_dir.is_dir():
        _LOG.debug(
            "compute_engineer_diff_from_workdir: fix_phase_dir %s unavailable",
            fix_phase_dir,
        )
        return ""

    # When seed_commit is provided, compare the current HEAD (post-engineer commits)
    # against the seed commit. We use HEAD..seed_commit range to capture all commits
    # the engineer may have made, plus any unstaged changes.
    # `git diff <seed_commit>` compares the working tree + index against seed_commit,
    # which captures both committed and uncommitted engineer changes.
    base = seed_commit if seed_commit else "HEAD"
    if not seed_commit:
        _LOG.debug(
            "compute_engineer_diff_from_workdir: no seed_commit; using HEAD (unstaged changes only)"
        )
        cmd = ["git", "diff", "HEAD"]
    else:
        cmd = ["git", "diff", seed_commit]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(fix_phase_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            _LOG.warning(
                "compute_engineer_diff_from_workdir: git diff %s returned %d: %s",
                base, result.returncode, result.stderr[:300],
            )
            return ""
        return result.stdout
    except Exception as exc:
        _LOG.warning(
            "compute_engineer_diff_from_workdir: git diff failed: %s", exc
        )
        return ""


# ---------------------------------------------------------------------------
# Diff hygiene
# ---------------------------------------------------------------------------

_DIFF_FILE_HEADER_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")
_UNIFIED_HUNK_LINE_RE = re.compile(r"^[+\-](?![+\-])")  # +/- but not +++ or ---


def compute_diff_hygiene(
    diff_text: str,
    known_affected_files: list[str],
) -> dict:
    """Parse a unified diff and return diff-hygiene diagnostics.

    Args:
        diff_text: raw unified diff text (may be empty).
        known_affected_files: list of repo-relative file paths the correct
                              patch is expected to touch (from corpus.yaml).

    Returns dict with:
        lines_touched: int   - count of + and - lines (not counting +++ / ---)
        files_touched: int   - number of distinct files in the diff
        scope_creep_flag: bool - True if any changed file is outside known_affected_files
        touched_files: list[str] - the actual list of changed file paths
        outside_files: list[str] - files touched but not in known_affected_files
    """
    if not diff_text:
        return {
            "lines_touched": 0,
            "files_touched": 0,
            "scope_creep_flag": False,
            "touched_files": [],
            "outside_files": [],
        }

    touched_files: list[str] = []
    lines_touched: int = 0

    for line in diff_text.splitlines():
        m = _DIFF_FILE_HEADER_RE.match(line)
        if m:
            # b/ path is the post-patch filename.
            touched_files.append(m.group(2))
            continue
        if _UNIFIED_HUNK_LINE_RE.match(line):
            lines_touched += 1

    # Deduplicate (a file may appear in multiple hunks of a real diff, but
    # the header re fires once per file so this is a belt-and-braces guard).
    seen: set[str] = set()
    unique_files: list[str] = []
    for f in touched_files:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)

    known_set = set(known_affected_files)
    outside_files = [f for f in unique_files if f not in known_set]
    scope_creep_flag = len(outside_files) > 0

    return {
        "lines_touched": lines_touched,
        "files_touched": len(unique_files),
        "scope_creep_flag": scope_creep_flag,
        "touched_files": unique_files,
        "outside_files": outside_files,
    }


# ---------------------------------------------------------------------------
# pytest result parsing
# ---------------------------------------------------------------------------

_PYTEST_FAILED_RE = re.compile(r"^FAILED (.+?)(?:\s+-\s+.+)?$", re.MULTILINE)
_PYTEST_SHORT_SUMMARY_RE = re.compile(
    r"=+ short test summary info =+(.*?)(?:=+ \d+ .+? =+|\Z)",
    re.DOTALL,
)


def _parse_pytest_failures(stdout: str) -> list[str]:
    """Extract failing test IDs from pytest stdout.

    Looks for the short test summary section which lists each FAILED line.
    Falls back to scanning all FAILED lines in the output.
    """
    failures: list[str] = []

    # Prefer the summary section.
    summary_m = _PYTEST_SHORT_SUMMARY_RE.search(stdout)
    search_text = summary_m.group(1) if summary_m else stdout
    for m in _PYTEST_FAILED_RE.finditer(search_text):
        failures.append(m.group(1).strip())

    return failures


# ---------------------------------------------------------------------------
# Unittest-style node-id conversion
# ---------------------------------------------------------------------------

_UNITTEST_ID_RE = re.compile(r"^(\w[\w.]*)\s+\((\S+)\)$")
"""Match unittest-style IDs: "test_method (module.path.TestClass)".

Group 1: method name (e.g. "test_foo")
Group 2: dotted module.TestClass path (e.g. "module.path.TestClass")
"""


def _convert_unittest_id_to_pytest(node_id: str) -> str:
    """Convert a unittest-style test ID to a pytest node-id.

    unittest format: "test_method (module.path.TestClass)"
    pytest format:   "module/path.py::TestClass::test_method"

    The module path component (everything before the last dot-segment, which
    is the class name) is converted from dotted notation to a filesystem path
    with '.py' appended. Dots inside the class name are not converted.

    Example:
        "test_foo (myapp.tests.MyTests)" -> "myapp/tests.py::MyTests::test_foo"
        "test_bar (tests.sub.TheSuite)"  -> "tests/sub.py::TheSuite::test_bar"

    Returns the original string unchanged if it does not match the expected
    unittest format.
    """
    m = _UNITTEST_ID_RE.match(node_id.strip())
    if not m:
        return node_id

    method = m.group(1)
    dotted = m.group(2)  # e.g. "myapp.tests.MyTests"

    parts = dotted.rsplit(".", 1)
    if len(parts) != 2:
        # No dot separator - cannot parse; return unchanged.
        return node_id

    module_path, class_name = parts
    # Convert dotted module path to filesystem path + .py extension.
    file_path = module_path.replace(".", "/") + ".py"
    return f"{file_path}::{class_name}::{method}"


def _normalize_fail_to_pass(
    fail_to_pass: "list[str]",
    context: str,
) -> "list[str]":
    """Normalize a fail_to_pass list, converting unittest-style IDs to pytest format.

    Args:
        fail_to_pass: raw node-id list from corpus.yaml (may contain unittest IDs).
        context: log label for warning messages (e.g. "local" or "tier3").

    Returns a new list with all IDs in pytest node-id format.
    Entries that cannot be parsed log a warning and are dropped (full-tree fallback
    is the caller's responsibility when the returned list is empty).
    """
    result: list[str] = []
    for nid in fail_to_pass:
        # Detect unittest-style: contains "(" and ")" but no "::" or ".py"
        if "(" in nid and ")" in nid and "::" not in nid and ".py" not in nid:
            converted = _convert_unittest_id_to_pytest(nid)
            if converted == nid:
                # Conversion failed (unexpected format).
                _LOG.warning(
                    "_normalize_fail_to_pass [%s]: could not convert unittest-style ID %r; "
                    "dropping it. Full held-out tree will run instead.",
                    context, nid,
                )
                # Signal to caller that we should fall back to full-tree mode.
                return []
            _LOG.debug(
                "_normalize_fail_to_pass [%s]: converted %r -> %r",
                context, nid, converted,
            )
            result.append(converted)
        else:
            # Already pytest-style - pass through unchanged.
            result.append(nid)
    return result


# ---------------------------------------------------------------------------
# In-process pytest runner (no Docker)
# ---------------------------------------------------------------------------

def _run_pytest_local(
    held_out_dir: Path,
    fix_phase_dir: Path,
    timeout: int,
    fail_to_pass: "list[str] | None" = None,
) -> tuple[int, str]:
    """Run pytest on held_out_dir tests against fix_phase_dir worktree.

    Args:
        held_out_dir: directory containing the held-out test files.
        fix_phase_dir: directory containing the engineer's modified repo.
        timeout: pytest wall-clock budget in seconds.
        fail_to_pass: optional list of specific test node-ids to run.
            When provided, pytest is invoked with those node-ids instead of
            the full held_out_dir tree. Relative paths are resolved against
            held_out_dir. When None or empty, all tests under held_out_dir
            are run.

    Returns (returncode, combined_stdout).
    """
    if fail_to_pass:
        # Normalize unittest-style IDs to pytest node-id format before resolving.
        normalized = _normalize_fail_to_pass(fail_to_pass, context="local")
        if not normalized:
            # Conversion failed for at least one ID; fall back to full tree.
            _LOG.warning(
                "_run_pytest_local: falling back to full held_out_dir due to "
                "unparseable node-id(s) in fail_to_pass=%r",
                fail_to_pass,
            )
            test_targets = [str(held_out_dir)]
        else:
            # Run only the specified test node-ids. Paths may be bare node-ids
            # (e.g. "tests/test_foo.py::TestFoo::test_bar") or relative paths;
            # resolve against held_out_dir so pytest can find them.
            test_targets = [
                str(held_out_dir / nid) if not Path(nid).is_absolute() else nid
                for nid in normalized
            ]
    else:
        test_targets = [str(held_out_dir)]

    cmd = [
        sys.executable, "-m", "pytest",
        *test_targets,
        # --noconftest and --rootdir prevent conftest.py / pytest.ini planted
        # by the agent in fix_phase_dir from executing during scoring. These
        # flags are load-bearing isolation guards - do not remove them.
        "--noconftest",
        f"--rootdir={held_out_dir}",
        "--tb=short",
        "-q",
        "--timeout", str(timeout),
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(fix_phase_dir),
            capture_output=True,
            text=True,
            timeout=timeout + 10,
        )
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired as e:
        out = (
            (e.stdout.decode("utf-8", errors="replace") if e.stdout else "")
            + (e.stderr.decode("utf-8", errors="replace") if e.stderr else "")
        )
        return 1, out + "\npytest timed out"


# ---------------------------------------------------------------------------
# In-container pytest runner (Tier 3)
# ---------------------------------------------------------------------------

def _run_pytest_tier3(
    tier3_ctx: object,  # Tier3Context (avoid hard import cycle)
    timeout: int,
    fail_to_pass: "list[str] | None" = None,
    env: "dict[str, str] | None" = None,
    use_timeout: bool = True,
) -> tuple[int, str]:
    """Run pytest inside the Tier 3 container's score phase.

    Delegates to Tier3Docker.run_score_phase. The held-out tests are mounted
    at /scoring/tests inside the container (per the Tier3Context mount layout).
    CWD is /scoring (not /workspace/repo) to prevent conftest.py or pytest.ini
    planted by the agent in /workspace/repo from executing.

    Args:
        tier3_ctx: Tier3Context from Tier3Docker.__enter__.
        timeout: pytest wall-clock budget in seconds.
        fail_to_pass: optional list of specific test node-ids to run.
            When provided, pytest is invoked with those node-ids prefixed by
            /scoring/tests/ (the in-container mount path) instead of the full
            /scoring/tests tree. When None or empty, all tests under
            /scoring/tests are run.

    Returns (returncode, combined_stdout).

    Isolation contract (score phase):
        --confcutdir=/scoring prevents pytest from searching above /scoring
        for conftest.py files, so agent-planted conftest.py at /workspace/repo
        is never loaded. We do NOT use --noconftest because that blanket-disables
        ALL conftest.py loading including legitimate conftest.py files in the
        held-out test tree (/scoring/tests/conftest.py) that SWE-bench tasks
        require for test collection. Similarly, --rootdir is omitted when
        specific node-ids are provided because pytest infers the rootdir from
        the first node-id path, and an explicit --rootdir can cause 0 tests
        collected when node-id paths don't match the declared rootdir.

        The entrypoint's run-tests command (used by Docker-native test runs in
        the test suite) retains --noconftest + --rootdir for the full-tree case
        to preserve backward compatibility with the existing security tests.
    """
    from evals.runner.isolator import Tier3Docker  # local import to avoid hard dep

    # Use the container-resident interpreter, NOT sys.executable.
    # sys.executable is the host Python path (e.g. /Users/.../.pyenv/shims/python3.11)
    # which does not exist inside the Docker image. The python:3.11-slim base image
    # guarantees "python3" on PATH; "python" also exists as a symlink in that image,
    # but "python3" is preferred for explicitness.
    if fail_to_pass:
        # Normalize unittest-style IDs to pytest node-id format before resolving.
        normalized = _normalize_fail_to_pass(fail_to_pass, context="tier3")
        if not normalized:
            # Conversion failed for at least one ID; fall back to full tree.
            _LOG.warning(
                "_run_pytest_tier3: falling back to full /scoring/tests due to "
                "unparseable node-id(s) in fail_to_pass=%r",
                fail_to_pass,
            )
            # Fall through to the full-tree path.
            cmd = [
                "python3", "-m", "pytest",
                "/scoring/tests",
                "--noconftest",
                "--rootdir=/scoring/tests",
                "--confcutdir=/scoring",
                "--import-mode=append",
                "-p", "no:cacheprovider",
                "--tb=short",
                "-q",
            ]
            if use_timeout:
                cmd.append(f"--timeout={timeout}")
            else:
                cmd.extend(["-p", "no:timeout"])
        else:
            # Run only the specified test node-ids. The held_out_dir is mounted at
            # /scoring/tests inside the container, so prepend that path to each
            # relative node-id (e.g. "test_foo.py::TestFoo::test_bar" ->
            # "/scoring/tests/test_foo.py::TestFoo::test_bar").
            # Node-ids that already start with /scoring/tests are passed as-is.
            _CONTAINER_TESTS_ROOT = "/scoring/tests"
            test_targets = [
                nid if nid.startswith(_CONTAINER_TESTS_ROOT)
                else f"{_CONTAINER_TESTS_ROOT}/{nid}"
                for nid in normalized
            ]
            # When specific node-ids are given, omit --rootdir and --noconftest:
            # - --rootdir conflicts with absolute node-id paths when the dir value
            #   doesn't match the path prefix, causing 0 tests collected.
            # - --noconftest blocks legitimate conftest.py in /scoring/tests that
            #   SWE-bench repo tests need for fixtures/collection.
            # --confcutdir=/scoring is retained: it stops conftest discovery at
            # /scoring so agent-planted conftest.py at /workspace/repo is never
            # loaded regardless of CWD.
            cmd = [
                "python3", "-m", "pytest",
                *test_targets,
                "--confcutdir=/scoring",
                "--import-mode=append",
                "-p", "no:cacheprovider",
                "--tb=short",
                "-q",
            ]
            if use_timeout:
                cmd.append(f"--timeout={timeout}")
            else:
                cmd.extend(["-p", "no:timeout"])
    else:
        # Full-tree case: use the original security-hardened flags.
        # --noconftest is safe here because we are running the full tree and
        # do not depend on conftest.py for targeted collection.
        cmd = [
            "python3", "-m", "pytest",
            "/scoring/tests",
            "--noconftest",
            "--rootdir=/scoring/tests",
            "--confcutdir=/scoring",
            "--import-mode=append",
            "-p", "no:cacheprovider",
            "--tb=short",
            "-q",
        ]
        if use_timeout:
            cmd.append(f"--timeout={timeout}")
        else:
            cmd.extend(["-p", "no:timeout"])

    _LOG.info(
        "_run_pytest_tier3: cmd=%s node_ids=%s",
        " ".join(cmd),
        fail_to_pass,
    )
    # Inject PYTHONPATH=/workspace/repo so the repo under test is importable
    # inside the score-phase container without pip install (network is disabled).
    # This resolves ImportError when conftest.py or test modules do
    # `from <repo_package> import ...` (e.g. `from requests.packages import ...`).
    base_env = {"PYTHONPATH": "/workspace/repo:/workspace/repo/src:/workspace/repo/lib", "HOME": "/tmp"}
    if env:
        base_env.update(env)
    result = Tier3Docker.run_score_phase(
        tier3_ctx,
        cmd,
        timeout_seconds=timeout,
        env=base_env,
    )
    return result.returncode, result.stdout + result.stderr


def _run_django_tests_tier3(
    tier3_ctx: object,
    timeout: int,
    fail_to_pass: "list[str] | None" = None,
) -> tuple[int, str]:
    """Run Django tests via tests/runtests.py inside the Tier 3 container."""
    from evals.runner.isolator import Tier3Docker

    labels: list[str] = []
    if fail_to_pass:
        for nid in fail_to_pass:
            if nid.startswith("tests/"):
                nid = nid[6:]
            # Convert filesystem path separators to Python module dots
            nid = nid.replace("/", ".")
            if ".py::" in nid:
                nid = nid.replace(".py::", ".", 1)
            nid = nid.replace("::", ".")
            labels.append(nid)

    if labels:
        cmd = [
            "python3", "tests/tests/runtests.py",
            "--verbosity", "2",
            "--settings", "test_sqlite",
            "--parallel", "1",
            *labels,
        ]
    else:
        cmd = [
            "python3", "tests/tests/runtests.py",
            "--verbosity", "2",
            "--settings", "test_sqlite",
            "--parallel", "1",
        ]

    env = {
        "PYTHONPATH": "/workspace/repo:/workspace/repo/src:/workspace/repo/lib:/workspace/repo/tests",
        "HOME": "/tmp",
    }

    result = Tier3Docker.run_score_phase(
        tier3_ctx,
        cmd,
        timeout_seconds=timeout,
        env=env,
    )
    return result.returncode, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_cell(
    task_slug: str,
    transcript: str,
    task_meta: dict,
    fix_phase_dir: Path,
    held_out_dir: Path,
    tier3_ctx: Optional[object] = None,
    pytest_timeout: int = 120,
    fail_to_pass: "list[str] | None" = None,
    seed_commit: str = "",
) -> ScoringResult:
    """Score one (task, condition, replicate) cell.

    Args:
        task_slug: corpus key (e.g. "django-11039").
        transcript: raw text output from the engineer's run (may be empty).
        task_meta: dict from corpus.yaml tasks[task_slug]; must have
                   "known_affected_files" list and optionally
                   "estimated_test_seconds" (used as a sanity cap).
        fix_phase_dir: host-side directory containing the engineer's
                       modified repo state.
        held_out_dir: host-side directory with the held-out test files.
        tier3_ctx: Tier3Context instance if running inside Docker, else None.
                   When provided, pytest is run via Tier3Docker.run_score_phase
                   (in-container); when None, pytest runs on the host.
        pytest_timeout: per-cell pytest wall-clock budget in seconds (<= 120
                        per the Brief constraint).
        fail_to_pass: optional list of specific test node-ids (relative to
                      held_out_dir / /scoring/tests) to run instead of the
                      full test tree. When None or empty, all tests under
                      held_out_dir are run. Forwarded to both the local and
                      tier3 pytest runners.
        seed_commit: git SHA of the post-seeding commit (returned by
                     seed_fix_phase). When non-empty and fix_phase_dir is a
                     valid git repo, the engineer diff is computed via
                     `git diff <seed_commit>` in fix_phase_dir (ground truth).
                     When empty or unavailable, falls back to transcript
                     parsing (dry-run path).

    Returns:
        ScoringResult with all fields populated.
    """
    known_affected = task_meta.get("known_affected_files", [])

    # 1. Compute diff from workdir (ground truth) when available; fall back
    #    to transcript parsing for dry-run paths where fix_phase_dir is a
    #    temp dir with no git history.
    if seed_commit and fix_phase_dir and (fix_phase_dir / ".git").is_dir():
        diff_text = compute_engineer_diff_from_workdir(fix_phase_dir, seed_commit)
        _LOG.debug(
            "score_cell [%s]: using workdir diff (seed_commit=%s, lines=%d)",
            task_slug, seed_commit[:8], diff_text.count("\n"),
        )
    else:
        diff_text = extract_diff_from_transcript(transcript)
        _LOG.debug(
            "score_cell [%s]: using transcript diff fallback (seed_commit=%r)",
            task_slug, seed_commit or "(empty)",
        )

    # 2. Compute diff hygiene.
    hygiene = compute_diff_hygiene(diff_text, known_affected)

    # 3. Run held-out tests.
    if tier3_ctx is not None:
        if task_slug.startswith("django-"):
            returncode, pytest_out = _run_django_tests_tier3(tier3_ctx, pytest_timeout, fail_to_pass=fail_to_pass)
        else:
            task_env: dict[str, str] | None = None
            use_timeout = task_meta.get("use_pytest_timeout", True)
            returncode, pytest_out = _run_pytest_tier3(tier3_ctx, pytest_timeout, fail_to_pass=fail_to_pass, env=task_env, use_timeout=use_timeout)
    else:
        returncode, pytest_out = _run_pytest_local(held_out_dir, fix_phase_dir, pytest_timeout, fail_to_pass=fail_to_pass)

    pass_fail = returncode == 0
    failures = [] if pass_fail else _parse_pytest_failures(pytest_out)

    return ScoringResult(
        pass_fail=pass_fail,
        score_primary=1.0 if pass_fail else 0.0,
        lines_touched=hygiene["lines_touched"],
        files_touched=hygiene["files_touched"],
        scope_creep_flag=hygiene["scope_creep_flag"],
        held_out_failures=failures,
        pytest_returncode=returncode,
        diff_text=diff_text,
        diagnostics={
            "task_slug": task_slug,
            "touched_files": hygiene["touched_files"],
            "outside_files": hygiene["outside_files"],
            "known_affected_files": known_affected,
            "pytest_output_tail": pytest_out[-1000:] if pytest_out else "",
        },
    )
