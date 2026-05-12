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
