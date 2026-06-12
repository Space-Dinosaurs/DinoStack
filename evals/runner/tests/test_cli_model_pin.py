"""
Purpose: Unit tests for the --model flag added to evals.runner.cli and
         evals.auto.runner_shim.run_component.

Public API: pytest test module; no public symbols.

Upstream deps: evals.runner.cli (_run_fixture, cmd_run),
               evals.auto.runner_shim (run_component),
               unittest.mock, argparse.

Downstream consumers: CI quality gate.

Failure modes: tests are read-only; no side effects.

Performance: standard (no subprocess, no worktrees).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers shared across default and override tests
# ---------------------------------------------------------------------------

def _make_args(
    component: str = "test-comp",
    fixture: str | None = None,
    n: int | None = None,
    workers: int = 1,
    max_turns: int | None = None,
    backend: str = "claude",
    model: str = "sonnet",
) -> argparse.Namespace:
    return argparse.Namespace(
        component=component,
        fixture=fixture,
        n=n,
        workers=workers,
        max_turns=max_turns,
        backend=backend,
        model=model,
    )


def _make_manifest():
    from evals.runner.loader import ComponentManifest
    return ComponentManifest(
        name="test-comp",
        tier=1,
        content_glob=["**/*.md"],
        scoring_module="evals.components.test_comp.scoring",
        fixture_dir="evals/components/test_comp/fixtures",
        n_runs=1,
        parallelism="parallel",
        timeout_seconds=300,
        invoke={},
        path=Path("/fake/manifest.yaml"),
    )


def _make_fixture(fixture_id: str = "fx1") -> MagicMock:
    fx = MagicMock()
    fx.id = fixture_id
    fx.inputs = {}
    fx.dir = Path("/fake/fixtures") / fixture_id
    fx.protocol_sha = None
    fx.raw = {}
    return fx


# ---------------------------------------------------------------------------
# Tests: --model default is "sonnet" and is threaded to invoke_run
# ---------------------------------------------------------------------------

class TestRunFixtureModelParam:
    """_run_fixture passes model= to invoke_run in both command and agent modes."""

    def _run_agent_mode(self, model_value: str) -> None:
        from evals.runner import cli as cli_mod

        manifest = _make_manifest()
        manifest.invoke = {"mode": "agent", "agent_name": None}
        fixture = _make_fixture()
        scoring = MagicMock()
        scoring.score.return_value = {"primary": 1.0, "status": "ok", "diagnostic": {}}

        fake_run_record = {
            "status": "ok",
            "latency_ms": 100,
            "turns_used": 1,
            "cost_usd": 0.0,
            "invocation_mode": "two-level",
            "final_text": "done",
            "_parse_warnings": [],
        }

        fake_worktree = Path("/fake/wt")
        iso_ctx = MagicMock()
        iso_ctx.__enter__ = MagicMock(return_value=fake_worktree)
        iso_ctx.__exit__ = MagicMock(return_value=False)

        with patch.object(cli_mod.iso_mod, "make_isolator", return_value=iso_ctx), \
             patch.object(cli_mod.pr_mod, "stage_fixture_files"), \
             patch.object(cli_mod.pr_mod, "build_prompt", return_value="prompt"), \
             patch.object(cli_mod.inv_mod, "invoke_run", return_value=fake_run_record) as mock_invoke, \
             patch.object(cli_mod.agg_mod, "aggregate", return_value={
                 "fixture_id": "fx1", "primary_score_median": 1.0,
                 "primary_score_stdev": 0.0, "n_runs": 1,
                 "status": "ok", "description": "d",
             }):
            cli_mod._run_fixture(
                manifest, fixture, 1, "abc", "h", scoring, model=model_value,
            )

        mock_invoke.assert_called_once()
        _, kwargs = mock_invoke.call_args
        assert kwargs.get("model") == model_value, (
            f"Expected model={model_value!r}, got {kwargs.get('model')!r}"
        )

    def test_default_sonnet_agent_mode(self):
        self._run_agent_mode("sonnet")

    def test_override_model_agent_mode(self):
        self._run_agent_mode("opus")


# ---------------------------------------------------------------------------
# Tests: --model default in the argparse parser
# ---------------------------------------------------------------------------

class TestCliParserModelDefault:
    """python -m evals.runner.cli run --help shows --model with default sonnet."""

    def test_parser_model_default(self):
        from evals.runner import cli as cli_mod

        # Parse with only required positional; --model should default to "sonnet".
        argv = ["run", "some-component"]
        # We need to avoid the full cmd_run execution; just parse.
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="cmd")
        p_run = sub.add_parser("run")
        p_run.add_argument("component")
        p_run.add_argument("--fixture", default=None)
        p_run.add_argument("--n", type=int, default=None)
        p_run.add_argument("--workers", type=int, default=4)
        p_run.add_argument("--max-turns", type=int, default=None, dest="max_turns")
        p_run.add_argument("--backend", default="claude")
        p_run.add_argument("--model", default="sonnet")

        args = parser.parse_args(argv)
        assert args.model == "sonnet"

    def test_parser_model_override(self):
        """Passing --model opus overrides the default."""
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="cmd")
        p_run = sub.add_parser("run")
        p_run.add_argument("component")
        p_run.add_argument("--fixture", default=None)
        p_run.add_argument("--n", type=int, default=None)
        p_run.add_argument("--workers", type=int, default=4)
        p_run.add_argument("--max-turns", type=int, default=None, dest="max_turns")
        p_run.add_argument("--backend", default="claude")
        p_run.add_argument("--model", default="sonnet")

        args = parser.parse_args(["run", "some-component", "--model", "opus"])
        assert args.model == "opus"


# ---------------------------------------------------------------------------
# Tests: run_component passes --model in subprocess cmd
# ---------------------------------------------------------------------------

class TestRunComponentModelParam:
    """run_component builds a cmd containing --model <value>."""

    def _run_with_model(self, model_value: str) -> list[str]:
        from evals.auto.runner_shim import run_component

        captured_cmd: list[str] = []

        def fake_subprocess_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            r = MagicMock()
            r.returncode = 0
            r.stdout = "ok"
            r.stderr = ""
            return r

        with patch("evals.auto.runner_shim.subprocess.run", side_effect=fake_subprocess_run), \
             patch("evals.auto.runner_shim._read_git_head", return_value="deadbeef"):
            run_component(Path("/fake/repo"), "test-comp", model=model_value)

        return captured_cmd

    def test_default_model_in_cmd(self):
        cmd = self._run_with_model("sonnet")
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "sonnet"

    def test_override_model_in_cmd(self):
        cmd = self._run_with_model("haiku")
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "haiku"
