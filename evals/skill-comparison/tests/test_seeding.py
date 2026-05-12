"""
Tests for evals/skill-comparison/seeding.py and seed_corpus.py.

Coverage:
- seed_fix_phase: clones the right repo at the right commit (subprocess mocked).
- seed_fix_phase: patch failure produces SeedError with step="patch_failed".
- seed_fix_phase: cache hit copies instead of re-cloning.
- seed_fix_phase: missing test_patch.diff raises FileNotFoundError.
- seed_fix_phase: missing task_meta fields raises ValueError.
- seed_corpus: writes test_patch.diff files from mocked HuggingFace responses.
- seed_corpus: skips already-present patches when force=False.
- seed_corpus: overwrites when force=True.
- runner integration: seed_fix_phase is called in non-dry-run path.
- runner integration: seed_error recorded in TSV and cell skipped on SeedError.

Network test (live, opt-in):
- LIVE_SEED_TEST=1 env var enables a real clone of psf/requests at
  36453b95b13079296776d11b09cab2567ea3e703 and verifies test_patch applies.
"""
from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

# conftest.py inserts skill-comparison/ into sys.path.
from seeding import DEFAULT_CACHE_DIR, SeedError, seed_fix_phase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_subprocess_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Return a fake CompletedProcess for subprocess.run mocks."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def _write_patch(task_dir: Path, content: str = "--- a/f\n+++ b/f\n@@ -1 +1 @@\n-old\n+new\n") -> Path:
    """Write a minimal test_patch.diff to task_dir."""
    task_dir.mkdir(parents=True, exist_ok=True)
    p = task_dir / "test_patch.diff"
    p.write_text(content, encoding="utf-8")
    return p


_TASK_META = {
    "repo_url": "https://github.com/psf/requests",
    "base_commit": "36453b95b13079296776d11b09cab2567ea3e703",
}

_TASK_SLUG = "requests-3362"


# ---------------------------------------------------------------------------
# SeedError
# ---------------------------------------------------------------------------


class TestSeedError:
    def test_step_attribute(self):
        err = SeedError(step="clone_failed", stderr="some output")
        assert err.step == "clone_failed"
        assert "clone_failed" in str(err)

    def test_stderr_truncated_in_message(self):
        err = SeedError(step="patch_failed", stderr="x" * 1000)
        # message should not be huge
        assert len(str(err)) < 700


# ---------------------------------------------------------------------------
# seed_fix_phase: subprocess mocked
# ---------------------------------------------------------------------------


class TestSeedFixPhase:
    """All subprocess calls are mocked so no network is required."""

    def _all_ok(self, *args, **kwargs) -> MagicMock:
        return _make_subprocess_result(returncode=0)

    def test_cache_miss_clones_then_fetches_then_copies(self, tmp_path: Path):
        """On cache miss: shallow clone + fetch + checkout + local clone + apply."""
        tasks_root = tmp_path / "tasks"
        task_dir = tasks_root / _TASK_SLUG
        _write_patch(task_dir)

        cache_dir = tmp_path / "cache"
        fix_dir = tmp_path / "fix"

        # Fake the cache as valid after the clone step.
        def fake_run(cmd, cwd, capture_output, text, timeout):
            # After the first clone call, create the .git marker so _is_cache_valid passes.
            key = f"{_TASK_SLUG}-{_TASK_META['base_commit'][:8]}"
            (cache_dir / key / ".git").mkdir(parents=True, exist_ok=True)
            return _make_subprocess_result(returncode=0)

        with patch("subprocess.run", side_effect=fake_run) as mock_run:
            seed_fix_phase(
                task_slug=_TASK_SLUG,
                task_meta=_TASK_META,
                fix_dir=fix_dir,
                tasks_root=tasks_root,
                cache_dir=cache_dir,
            )

        # Verify the sequence of commands.
        cmds = [c[0][0] for c in mock_run.call_args_list]  # first positional arg (cmd list)
        git_subcmds = [c[1] for c in cmds]  # "clone", "fetch", "checkout", etc.

        # Should have: clone (cache), fetch, checkout, clone --local, checkout, apply.
        assert "clone" in git_subcmds
        assert "fetch" in git_subcmds
        assert "apply" in git_subcmds

    def test_cache_hit_skips_clone(self, tmp_path: Path):
        """On cache hit: skip initial clone; only do local-clone + checkout + apply."""
        tasks_root = tmp_path / "tasks"
        task_dir = tasks_root / _TASK_SLUG
        _write_patch(task_dir)

        cache_dir = tmp_path / "cache"
        # Pre-seed the cache so _is_cache_valid returns True.
        key = f"{_TASK_SLUG}-{_TASK_META['base_commit'][:8]}"
        (cache_dir / key / ".git").mkdir(parents=True, exist_ok=True)

        fix_dir = tmp_path / "fix"

        with patch("subprocess.run", side_effect=self._all_ok) as mock_run:
            seed_fix_phase(
                task_slug=_TASK_SLUG,
                task_meta=_TASK_META,
                fix_dir=fix_dir,
                tasks_root=tasks_root,
                cache_dir=cache_dir,
            )

        cmds = [c[0][0] for c in mock_run.call_args_list]
        git_subcmds = [c[1] for c in cmds]

        # The very first git call must be "clone" for local copy, not the remote clone.
        first_clone = next(
            (c for c in mock_run.call_args_list if c[0][0][1] == "clone"), None
        )
        assert first_clone is not None
        # The --local flag must be present (not a remote clone).
        assert "--local" in first_clone[0][0], (
            "Cache hit path must use git clone --local, not a fresh remote clone"
        )

    def test_patch_failure_raises_seed_error(self, tmp_path: Path):
        """When git apply fails, SeedError(step='patch_failed') is raised."""
        tasks_root = tmp_path / "tasks"
        task_dir = tasks_root / _TASK_SLUG
        _write_patch(task_dir)

        cache_dir = tmp_path / "cache"
        key = f"{_TASK_SLUG}-{_TASK_META['base_commit'][:8]}"
        (cache_dir / key / ".git").mkdir(parents=True, exist_ok=True)

        fix_dir = tmp_path / "fix"

        call_count = {"n": 0}

        def fail_on_apply(cmd, **kwargs):
            call_count["n"] += 1
            if cmd[1] == "apply":
                return _make_subprocess_result(returncode=1, stderr="patch conflict")
            return _make_subprocess_result(returncode=0)

        with patch("subprocess.run", side_effect=fail_on_apply):
            with pytest.raises(SeedError) as exc_info:
                seed_fix_phase(
                    task_slug=_TASK_SLUG,
                    task_meta=_TASK_META,
                    fix_dir=fix_dir,
                    tasks_root=tasks_root,
                    cache_dir=cache_dir,
                )

        assert exc_info.value.step == "patch_failed"
        assert "patch" in exc_info.value.stderr.lower() or "conflict" in exc_info.value.stderr

    def test_clone_failure_raises_seed_error(self, tmp_path: Path):
        """When the remote clone fails, SeedError(step='clone_failed') is raised."""
        tasks_root = tmp_path / "tasks"
        _write_patch(tasks_root / _TASK_SLUG)

        cache_dir = tmp_path / "cache"
        # No .git in cache - cache miss path.
        fix_dir = tmp_path / "fix"

        with patch("subprocess.run", return_value=_make_subprocess_result(returncode=128, stderr="not a repo")):
            with pytest.raises(SeedError) as exc_info:
                seed_fix_phase(
                    task_slug=_TASK_SLUG,
                    task_meta=_TASK_META,
                    fix_dir=fix_dir,
                    tasks_root=tasks_root,
                    cache_dir=cache_dir,
                )

        assert exc_info.value.step == "clone_failed"

    def test_missing_patch_raises_file_not_found(self, tmp_path: Path):
        """When test_patch.diff is absent, FileNotFoundError is raised before any git call."""
        tasks_root = tmp_path / "tasks"
        # No test_patch.diff written.
        (tasks_root / _TASK_SLUG).mkdir(parents=True, exist_ok=True)

        with patch("subprocess.run") as mock_run:
            with pytest.raises(FileNotFoundError):
                seed_fix_phase(
                    task_slug=_TASK_SLUG,
                    task_meta=_TASK_META,
                    fix_dir=tmp_path / "fix",
                    tasks_root=tasks_root,
                )

        mock_run.assert_not_called()

    def test_missing_repo_url_raises_value_error(self, tmp_path: Path):
        tasks_root = tmp_path / "tasks"
        _write_patch(tasks_root / _TASK_SLUG)
        bad_meta = {"base_commit": "abc123"}

        with pytest.raises(ValueError, match="repo_url"):
            seed_fix_phase(
                task_slug=_TASK_SLUG,
                task_meta=bad_meta,
                fix_dir=tmp_path / "fix",
                tasks_root=tasks_root,
            )

    def test_missing_base_commit_raises_value_error(self, tmp_path: Path):
        tasks_root = tmp_path / "tasks"
        _write_patch(tasks_root / _TASK_SLUG)
        bad_meta = {"repo_url": "https://github.com/psf/requests"}

        with pytest.raises(ValueError, match="base_commit"):
            seed_fix_phase(
                task_slug=_TASK_SLUG,
                task_meta=bad_meta,
                fix_dir=tmp_path / "fix",
                tasks_root=tasks_root,
            )

    def test_returns_seed_commit_sha(self, tmp_path: Path):
        """seed_fix_phase returns a dict with non-empty 'seed_commit' SHA.

        Regression for smoke-v6 diff-source bug: seed_fix_phase now commits the
        post-seeding state so scoring can run `git diff <seed_commit>` to get
        the engineer's changes without parsing the (unreliable) transcript.
        """
        tasks_root = tmp_path / "tasks"
        _write_patch(tasks_root / _TASK_SLUG)

        cache_dir = tmp_path / "cache"
        key = f"{_TASK_SLUG}-{_TASK_META['base_commit'][:8]}"
        (cache_dir / key / ".git").mkdir(parents=True, exist_ok=True)

        fix_dir = tmp_path / "fix"

        _FAKE_SHA = "abc123def456abc123def456abc123def456abc1"

        def fake_run(cmd, **kwargs):
            # rev-parse HEAD returns the fake SHA.
            if "rev-parse" in cmd:
                result = _make_subprocess_result(returncode=0, stdout=_FAKE_SHA + "\n")
                return result
            return _make_subprocess_result(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            result = seed_fix_phase(
                task_slug=_TASK_SLUG,
                task_meta=_TASK_META,
                fix_dir=fix_dir,
                tasks_root=tasks_root,
                cache_dir=cache_dir,
            )

        assert isinstance(result, dict), (
            f"seed_fix_phase must return a dict, got {type(result)}"
        )
        assert "seed_commit" in result, (
            "Return dict must have 'seed_commit' key for engineer diff base"
        )
        assert result["seed_commit"] == _FAKE_SHA, (
            f"seed_commit must equal the HEAD SHA; got {result['seed_commit']!r}"
        )

    def test_seed_commit_in_returned_dict_after_git_add_commit(self, tmp_path: Path):
        """seed_fix_phase issues git add -A and git commit after applying the patch.

        Verifies the commit step is present by checking that 'commit' appears in
        the sequence of git subcommands issued after 'apply'.
        """
        tasks_root = tmp_path / "tasks"
        _write_patch(tasks_root / _TASK_SLUG)

        cache_dir = tmp_path / "cache"
        key = f"{_TASK_SLUG}-{_TASK_META['base_commit'][:8]}"
        (cache_dir / key / ".git").mkdir(parents=True, exist_ok=True)

        fix_dir = tmp_path / "fix"

        issued_cmds: list[list[str]] = []

        def recording_run(cmd, **kwargs):
            issued_cmds.append(list(cmd))
            if "rev-parse" in cmd:
                return _make_subprocess_result(returncode=0, stdout="deadbeef" * 5 + "\n")
            return _make_subprocess_result(returncode=0)

        with patch("subprocess.run", side_effect=recording_run):
            seed_fix_phase(
                task_slug=_TASK_SLUG,
                task_meta=_TASK_META,
                fix_dir=fix_dir,
                tasks_root=tasks_root,
                cache_dir=cache_dir,
            )

        # Extract git subcommands: handle both `git <subcmd>` and `git -c k=v <subcmd>`.
        # `-c key=value` option tokens don't start with "-" but ARE option arguments.
        # Strategy: skip tokens that start with "-" OR are values for "-c" (contain "=").
        def _git_subcmd(cmd: list) -> str:
            """Return the git subcommand from a git invocation list.

            Handles: git <subcmd>, git -c k=v <subcmd>, git --flag <subcmd>.
            The subcommand is the first token after 'git' that is not a flag
            and not a -c value (which contains '=').
            """
            if not cmd or cmd[0] != "git":
                return ""
            skip_next = False
            for token in cmd[1:]:
                if skip_next:
                    skip_next = False
                    continue
                if token == "-c":
                    skip_next = True
                    continue
                if token.startswith("-"):
                    continue
                # A -c value looks like "user.email=seed@local" - contains "=".
                # But valid subcommands never contain "=".
                if "=" in token:
                    continue
                return token
            return ""

        git_subcmds = [_git_subcmd(c) for c in issued_cmds if c and c[0] == "git"]
        assert "apply" in git_subcmds, "git apply must be called"
        apply_idx = git_subcmds.index("apply")
        post_apply = git_subcmds[apply_idx + 1:]
        assert "add" in post_apply, (
            "git add must be issued after git apply to stage the patch"
        )
        assert "commit" in post_apply, (
            "git commit must be issued after git apply to record the seed state; "
            "this commit SHA is needed for engineer diff computation in scoring"
        )


# ---------------------------------------------------------------------------
# seed_corpus tests
# ---------------------------------------------------------------------------


class TestSeedCorpus:
    """Tests for seed_corpus.py's seed_corpus() function.

    HuggingFace HTTP calls are mocked via urllib.request.urlopen.
    """

    _MINIMAL_CORPUS = """\
freeze_metadata:
  freeze_date: "2026-05-12"
  swebench_dataset: "princeton-nlp/SWE-bench_Lite"
  dataset_split: "test"
  dataset_commit_hash: "princeton-nlp/SWE-bench_Lite@main"
  selected_count: 1
tasks:
  requests-3362:
    swebench_instance_id: "psf__requests-3362"
    repo_url: "https://github.com/psf/requests"
    base_commit: "36453b95b13079296776d11b09cab2567ea3e703"
    held_out_tests:
      - "tests/test_requests.py"
    fail_to_pass:
      - "tests/test_requests.py::TestRequests::test_response_decode_unicode"
    estimated_test_seconds: 15
    difficulty: single-file
    known_affected_files:
      - "requests/utils.py"
    problem_summary: test task
"""

    def _make_hf_response(self, instance_id: str, test_patch: str) -> bytes:
        """Build a minimal HuggingFace API JSON response."""
        import json
        return json.dumps({
            "rows": [
                {"row": {"instance_id": instance_id, "test_patch": test_patch}}
            ]
        }).encode()

    def test_writes_patch_when_absent(self, tmp_path: Path):
        """seed_corpus writes test_patch.diff when it does not exist."""
        from seed_corpus import seed_corpus

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(self._MINIMAL_CORPUS, encoding="utf-8")
        tasks_root = tmp_path / "tasks"
        (tasks_root / "requests-3362").mkdir(parents=True)

        fake_patch = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1 +1 @@\n-x\n+y\n"
        hf_bytes = self._make_hf_response("psf__requests-3362", fake_patch)

        class FakeHTTPResponse:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return hf_bytes
            def __iter__(self):
                import io, json as _json
                yield from io.BytesIO(hf_bytes)
            # urlopen uses .read() via json.load which needs read()
            def readable(self): return True

        import io, json as _json

        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self, *a): return hf_bytes

        import urllib.request as _urlreq

        def fake_urlopen(url, timeout=None):
            import io, json as _j
            class _R:
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def read(self): return hf_bytes
                # json.load calls read() via a file-like wrapper
            return _R()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            # json.load needs a file-like with read()
            with patch("json.load", return_value=_json.loads(hf_bytes)):
                status = seed_corpus(corpus_yaml, tasks_root)

        patch_file = tasks_root / "requests-3362" / "test_patch.diff"
        assert patch_file.is_file()
        assert status.get("requests-3362") == "written"
        assert patch_file.read_text(encoding="utf-8") == fake_patch

    def test_skips_when_exists_and_no_force(self, tmp_path: Path):
        """seed_corpus returns 'exists' without fetching when patch already present."""
        from seed_corpus import seed_corpus

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(self._MINIMAL_CORPUS, encoding="utf-8")
        tasks_root = tmp_path / "tasks"
        patch_path = tasks_root / "requests-3362" / "test_patch.diff"
        patch_path.parent.mkdir(parents=True)
        patch_path.write_text("existing patch content", encoding="utf-8")

        with patch("urllib.request.urlopen") as mock_urlopen:
            status = seed_corpus(corpus_yaml, tasks_root, force=False)

        mock_urlopen.assert_not_called()
        assert status.get("requests-3362") == "exists"

    def test_force_overwrites_existing(self, tmp_path: Path):
        """seed_corpus overwrites test_patch.diff when force=True."""
        from seed_corpus import seed_corpus
        import json as _json

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(self._MINIMAL_CORPUS, encoding="utf-8")
        tasks_root = tmp_path / "tasks"
        patch_path = tasks_root / "requests-3362" / "test_patch.diff"
        patch_path.parent.mkdir(parents=True)
        patch_path.write_text("old content", encoding="utf-8")

        new_patch = "new patch content after force"
        hf_bytes = self._make_hf_response("psf__requests-3362", new_patch)
        hf_data = _json.loads(hf_bytes)

        with patch("json.load", return_value=hf_data):
            with patch("urllib.request.urlopen"):
                status = seed_corpus(corpus_yaml, tasks_root, force=True)

        assert status.get("requests-3362") == "written"
        assert patch_path.read_text(encoding="utf-8") == new_patch


# ---------------------------------------------------------------------------
# runner integration: seed_fix_phase called in non-dry-run
# ---------------------------------------------------------------------------


class TestRunnerSeedingIntegration:
    """Verify runner.run_matrix calls seed_fix_phase in the non-dry-run path."""

    _MINIMAL_CORPUS_YAML = """\
freeze_metadata:
  freeze_date: "2026-05-12"
tasks:
  requests-3362:
    swebench_instance_id: "psf__requests-3362"
    repo_url: "https://github.com/psf/requests"
    base_commit: "36453b95b13079296776d11b09cab2567ea3e703"
    held_out_tests:
      - "tests/test_requests.py"
    fail_to_pass:
      - "tests/test_requests.py::TestRequests::test_response_decode_unicode"
    estimated_test_seconds: 15
    difficulty: single-file
    known_affected_files:
      - "requests/utils.py"
    problem_summary: test task
"""

    def test_seed_fix_phase_called_in_production_path(self, tmp_path: Path):
        """run_matrix calls seed_fix_phase for each cell in non-dry-run mode."""
        from runner import run_matrix
        from scoring import ScoringResult

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(self._MINIMAL_CORPUS_YAML, encoding="utf-8")
        results_tsv = tmp_path / "results.tsv"

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )
        canned_result = {
            "final_text": "Fixed.",
            "status": "ok",
            "cost_usd": 0.0,
            "usage": {},
            "latency_ms": 0,
            "invocation_mode": "agent",
            "tool_calls": [],
            "turns_used": 1,
            "_parse_warnings": [],
        }

        seed_calls: list[dict] = []

        def fake_seed(task_slug, task_meta, fix_dir, tasks_root, cache_dir=None):
            seed_calls.append({"task_slug": task_slug, "fix_dir": fix_dir})
            return {"seed_commit": "fake-sha-for-test"}

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner._run_cell", return_value=canned_result),
            patch("runner.seed_fix_phase", side_effect=fake_seed),
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="off",  # no docker
            )

        assert len(seed_calls) == 1, (
            f"seed_fix_phase must be called once per cell in non-dry-run mode; "
            f"got {len(seed_calls)} calls"
        )
        assert seed_calls[0]["task_slug"] == "requests-3362"

    def test_seed_fix_phase_not_called_in_dry_run(self, tmp_path: Path):
        """run_matrix skips seed_fix_phase when dry_run=True."""
        from runner import run_matrix
        from scoring import ScoringResult

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(self._MINIMAL_CORPUS_YAML, encoding="utf-8")
        results_tsv = tmp_path / "results.tsv"

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner.seed_fix_phase") as mock_seed,
        ):
            run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=True,
                conditions=["baseline"],
            )

        mock_seed.assert_not_called()

    def test_seed_error_records_row_and_skips_engineer(self, tmp_path: Path):
        """When seed_fix_phase raises SeedError, TSV row has status='seed_error'."""
        from runner import run_matrix
        from scoring import ScoringResult

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(self._MINIMAL_CORPUS_YAML, encoding="utf-8")
        results_tsv = tmp_path / "results.tsv"

        canned_score = ScoringResult(
            pass_fail=True, score_primary=1.0,
            lines_touched=1, files_touched=1, scope_creep_flag=False,
        )

        def raise_seed_error(**kwargs):
            raise SeedError(step="clone_failed", stderr="git error")

        run_cell_calls: list = []

        def fake_run_cell(**kwargs):
            run_cell_calls.append(kwargs)
            return {"final_text": "", "status": "ok", "cost_usd": 0.0, "usage": {}, "latency_ms": 0, "invocation_mode": "agent", "tool_calls": [], "turns_used": 1, "_parse_warnings": []}

        with (
            patch("runner.score_cell", return_value=canned_score),
            patch("runner._run_cell", side_effect=fake_run_cell),
            patch("runner.seed_fix_phase", side_effect=raise_seed_error),
        ):
            report = run_matrix(
                tasks_yaml=corpus_yaml,
                results_tsv=results_tsv,
                n_replicates=1,
                n_replicates_methodology=1,
                dry_run=False,
                conditions=["baseline"],
                tier3_mode="off",
            )

        assert report.rows_written == 1

        # Read back TSV and check status.
        import csv
        with results_tsv.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        assert len(rows) == 1
        assert rows[0]["status"] == "seed_error", (
            f"Expected status='seed_error' when seeding fails; got {rows[0]['status']!r}"
        )

        # Engineer must NOT have been called.
        assert not run_cell_calls, (
            "run_cell must not be called when seeding fails"
        )


# ---------------------------------------------------------------------------
# MAJOR-1 regression: cache corruption detection
# ---------------------------------------------------------------------------


class TestCacheCorruptionDetection:
    """Regression suite for MAJOR-1.

    An interrupted git clone creates a .git directory but leaves HEAD
    unresolvable. _is_cache_valid must detect this and remove the corrupt
    directory so the next call does a fresh clone.

    Mock strategy: we pre-create a cache_path/.git/ directory (simulating an
    interrupted clone), and patch subprocess.run so that the git rev-parse
    call returns non-zero (simulating a corrupt HEAD). We then call
    _is_cache_valid and assert it returns False AND that the corrupt directory
    was removed.

    We do NOT mock at the _is_cache_valid function level - that would hide the
    regression path entirely.
    """

    def test_corrupt_cache_detected_and_removed(self, tmp_path: Path):
        """_is_cache_valid returns False AND removes the dir when HEAD is unresolvable.

        Regression test for MAJOR-1: previously _is_cache_valid only checked
        for the existence of .git, not whether the repo was actually usable.
        An interrupted clone would create .git but leave HEAD unresolvable,
        causing all subsequent cells to fail with seed_error.
        """
        from seeding import _is_cache_valid

        # Simulate an interrupted clone: .git exists but HEAD is unresolvable.
        cache_path = tmp_path / "corrupt-cache"
        (cache_path / ".git").mkdir(parents=True)

        def fake_run(cmd, **kwargs):
            # Simulate git rev-parse --verify HEAD failing (corrupt repo).
            if "rev-parse" in cmd:
                result = MagicMock()
                result.returncode = 128
                result.stdout = ""
                result.stderr = "fatal: not a git repository"
                return result
            result = MagicMock()
            result.returncode = 0
            result.stdout = "deadbeef" * 5
            result.stderr = ""
            return result

        with patch("subprocess.run", side_effect=fake_run):
            is_valid = _is_cache_valid(cache_path)

        assert is_valid is False, (
            "_is_cache_valid must return False for a corrupt cache (git rev-parse fails). "
            "MAJOR-1 regression: previously True was returned for any dir with .git present."
        )
        assert not cache_path.exists(), (
            "_is_cache_valid must remove the corrupt cache directory so the next "
            "call triggers a fresh clone. The dir should be gone."
        )

    def test_valid_cache_not_removed(self, tmp_path: Path):
        """_is_cache_valid returns True and does NOT remove a valid repo."""
        from seeding import _is_cache_valid

        cache_path = tmp_path / "valid-cache"
        (cache_path / ".git").mkdir(parents=True)

        def fake_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = "d5276398046ce4a102776a1e67dcac2884d80dfe\n"
            result.stderr = ""
            return result

        with patch("subprocess.run", side_effect=fake_run):
            is_valid = _is_cache_valid(cache_path)

        assert is_valid is True, "_is_cache_valid must return True for a valid repo"
        assert cache_path.exists(), "Valid cache directory must NOT be removed"

    def test_missing_git_dir_returns_false(self, tmp_path: Path):
        """_is_cache_valid returns False (without subprocess call) when .git is absent."""
        from seeding import _is_cache_valid

        cache_path = tmp_path / "no-git"
        cache_path.mkdir()  # dir exists but no .git

        with patch("subprocess.run") as mock_run:
            is_valid = _is_cache_valid(cache_path)

        assert is_valid is False
        mock_run.assert_not_called(), (
            "subprocess.run must NOT be called when .git is absent"
        )


# ---------------------------------------------------------------------------
# MINOR-1 regression: validate_corpus checks first line of test_patch.diff
# ---------------------------------------------------------------------------


class TestValidateCorpusPatchFirstLine:
    """Regression suite for MINOR-1.

    validate_corpus.py must report a violation when test_patch.diff exists and
    is non-empty but its first line does not start with 'diff --git'.
    """

    _MINIMAL_CORPUS_YAML = """\
freeze_metadata:
  freeze_date: "2026-05-12"
  swebench_dataset: "princeton-nlp/SWE-bench_Lite"
  dataset_split: "test"
  dataset_commit_hash: "abc"
  selected_count: 1
tasks:
  django-11039:
    swebench_instance_id: "django__django-11039"
    repo_url: "https://github.com/django/django"
    base_commit: "d5276398046ce4a102776a1e67dcac2884d80dfe"
    held_out_tests:
      - "tests/migrations/test_commands.py"
    fail_to_pass:
      - "test_sqlmigrate"
    estimated_test_seconds: 30
    difficulty: single-file
    known_affected_files:
      - "django/core/management/commands/sqlmigrate.py"
    problem_summary: sqlmigrate wraps output in BEGIN/COMMIT.
"""

    def _write_task_dir(self, tasks_root: Path, patch_content: str) -> None:
        task_dir = tasks_root / "django-11039"
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "problem.md").write_text("problem", encoding="utf-8")
        (task_dir / "held_out_tests").mkdir(exist_ok=True)
        (task_dir / "test_patch.diff").write_text(patch_content, encoding="utf-8")

    def test_truncated_patch_reported_as_violation(self, tmp_path: Path):
        """validate_corpus reports a violation when patch first line is not 'diff --git'.

        Regression test for MINOR-1: previously only size=0 was checked; a
        truncated non-empty patch would pass validation silently.
        """
        import sys
        sys.path.insert(0, str(tmp_path.parent))

        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(self._MINIMAL_CORPUS_YAML, encoding="utf-8")
        tasks_root = tmp_path

        # Truncated patch: non-empty but first line is not 'diff --git'.
        self._write_task_dir(tasks_root, "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x\n+y\n")

        from tasks.validate_corpus import validate_corpus
        violations = validate_corpus(corpus_yaml, tasks_root)

        diff_git_violations = [v for v in violations if "diff --git" in v]
        assert diff_git_violations, (
            "validate_corpus must report a violation when test_patch.diff first "
            "line does not start with 'diff --git'. MINOR-1 regression: truncated "
            "patches were silently accepted."
        )

    def test_valid_patch_no_first_line_violation(self, tmp_path: Path):
        """No violation when test_patch.diff starts with 'diff --git'."""
        corpus_yaml = tmp_path / "corpus.yaml"
        corpus_yaml.write_text(self._MINIMAL_CORPUS_YAML, encoding="utf-8")
        tasks_root = tmp_path

        self._write_task_dir(
            tasks_root,
            "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x\n+y\n",
        )

        from tasks.validate_corpus import validate_corpus
        violations = validate_corpus(corpus_yaml, tasks_root)

        diff_git_violations = [v for v in violations if "diff --git" in v and "does not start" in v]
        assert not diff_git_violations, (
            f"No 'diff --git' first-line violation expected for a valid patch; "
            f"got: {diff_git_violations}"
        )


# ---------------------------------------------------------------------------
# Live network test (opt-in)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("LIVE_SEED_TEST") != "1",
    reason="Skipped by default - set LIVE_SEED_TEST=1 to run (requires network + ~5 min)",
)
class TestLiveSeed:
    """Real clone + patch for requests-3362. Requires network access."""

    def test_requests_3362_seeds_and_patch_applies(self, tmp_path: Path):
        """Clone requests at the known commit and apply the committed test_patch.diff.

        Verifies:
        - Clone succeeds.
        - Checkout of base_commit succeeds.
        - test_patch.diff applies without error.
        - The held-out test file is present in fix_dir after seeding.
        """
        tasks_root = (
            Path(__file__).parent.parent / "tasks"
        )
        patch_file = tasks_root / "requests-3362" / "test_patch.diff"
        if not patch_file.is_file():
            pytest.skip(f"test_patch.diff not found at {patch_file}; run seed_corpus.py first")

        fix_dir = tmp_path / "fix"
        cache_dir = tmp_path / "cache"

        # This is a real git clone - it will take a few seconds.
        seed_fix_phase(
            task_slug="requests-3362",
            task_meta={
                "repo_url": "https://github.com/psf/requests",
                "base_commit": "36453b95b13079296776d11b09cab2567ea3e703",
            },
            fix_dir=fix_dir,
            tasks_root=tasks_root,
            cache_dir=cache_dir,
        )

        # The test_patch adds/modifies tests/test_requests.py.
        test_file = fix_dir / "tests" / "test_requests.py"
        assert test_file.is_file(), (
            f"After seeding, tests/test_requests.py must exist in fix_dir; "
            f"fix_dir contents: {list(fix_dir.iterdir())}"
        )

        # The cache was populated.
        key = f"requests-3362-{_TASK_META['base_commit'][:8]}"
        assert (cache_dir / key / ".git").is_dir(), "Cache must be populated after first seed"

        # Second call uses cache (local clone).
        fix_dir2 = tmp_path / "fix2"
        seed_fix_phase(
            task_slug="requests-3362",
            task_meta=_TASK_META,
            fix_dir=fix_dir2,
            tasks_root=tasks_root,
            cache_dir=cache_dir,
        )
        assert (fix_dir2 / "tests" / "test_requests.py").is_file(), (
            "Cache-hit path must also produce a seeded fix_dir"
        )
