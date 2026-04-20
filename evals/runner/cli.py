"""
Purpose: Command-line entry point for the evals runner. Subcommands:
         run, list-components, show-results.

Public API: main(argv: list[str] | None = None) -> int; invoked via
            `python -m evals.runner.cli`.

Upstream deps: stdlib argparse, importlib, subprocess, sys, json;
               evals.runner.{loader, isolator, invoker, prompt, aggregator,
               tsv_writer, normalizer, logging}.

Downstream consumers: humans running evals; CI (future).

Failure modes: Exits non-zero on missing components, missing fixtures, absent
               Claude CLI, or unhandled runner exceptions. Per-run errors
               within an N-run loop are captured in the runlog and TSV rather
               than raising to the shell.

Performance: dominated by the Claude CLI calls; runner overhead is negligible.
"""
from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from pathlib import Path

from . import aggregator as agg_mod
from . import invoker as inv_mod
from . import isolator as iso_mod
from . import loader as ld
from . import prompt as pr_mod
from . import tsv_writer as tsv
from .logging import get_logger, write_runlog

_log = get_logger("evals.runner")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _git_head_commit() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return r.stdout.strip()
    except Exception:
        return "unknown"


def _load_scoring(module_path: str):
    return importlib.import_module(module_path)


def _score_run(scoring, run_record: dict, fixture: ld.Fixture) -> dict:
    """Wrap a single CLI run record into the trace shape expected by scoring.score."""
    trace = {"runs": [run_record]}
    # Inject the fixture directory so scorers that need the seeded repo
    # (e.g. memory_update_lite comparing seeded MEMORY.md to post-run
    # MEMORY.md) can locate it. fixture.raw is a loaded-from-yaml dict;
    # _fixture_dir is a harness annotation, underscore-prefixed.
    fixture_raw = dict(fixture.raw or {})
    fixture_raw["_fixture_dir"] = str(fixture.dir)
    try:
        out = scoring.score(trace, fixture_raw)
        out.setdefault("status", "ok")
        out.setdefault("primary", 0.0)
        out.setdefault("diagnostic", {})
        # Surface latency/turns in the diagnostic automatically.
        out["diagnostic"].setdefault("latency_ms", run_record.get("latency_ms"))
        out["diagnostic"].setdefault("turns_used", run_record.get("turns_used"))
        out["diagnostic"].setdefault("cli_status", run_record.get("status"))
        return out
    except Exception as e:
        _log.exception("Scoring failed")
        return {
            "primary": 0.0,
            "status": "scoring_error",
            "diagnostic": {"error": str(e), "cli_status": run_record.get("status")},
        }


def _run_fixture(
    manifest: ld.ComponentManifest,
    fixture: ld.Fixture,
    n_runs: int,
    commit: str,
    content_hash: str,
    scoring,
) -> dict:
    per_run_scores: list[dict] = []
    invocation_modes: list[str] = []
    invoke_section = manifest.invoke or {}
    agent_name = invoke_section.get("agent_name")
    invoke_mode = invoke_section.get("mode") or "agent"
    _log.info(
        "Running fixture %s (n=%d, mode=%s, agent=%s)",
        fixture.id, n_runs, invoke_mode, agent_name,
    )
    for i in range(n_runs):
        _log.info("  run %d/%d", i + 1, n_runs)
        if invoke_mode == "command":
            # Tier 2 HOME-redirect path: copy the fixture's seeded repo into
            # a tmpdir worktree and seed a fresh ~/.claude/ inside a fake
            # HOME.
            repo_dir_rel = (fixture.inputs or {}).get("repo_dir")
            fixture_repo_dir = fixture.dir / repo_dir_rel if repo_dir_rel else None
            home_config = (fixture.inputs or {}).get("home_config") or {}
            with iso_mod.make_isolator(
                manifest.tier,
                fixture_repo_dir=fixture_repo_dir,
                home_config=home_config,
            ) as (worktree, fake_home):
                prompt_text = pr_mod.build_prompt(manifest.name, fixture)
                run_record = inv_mod.invoke_run(
                    prompt_text,
                    worktree,
                    manifest.timeout_seconds,
                    mode="command",
                    home=fake_home,
                )
                # Scorer needs the worktree root to read AGENTS.md/.gitignore
                # line-level content. Stuff it into the record before the
                # isolator cleans up.
                run_record["worktree_root"] = str(worktree)
                score = _score_run(scoring, run_record, fixture)
        else:
            with iso_mod.make_isolator(manifest.tier) as worktree:
                pr_mod.stage_fixture_files(fixture, worktree)
                prompt_text = pr_mod.build_prompt(manifest.name, fixture)
                run_record = inv_mod.invoke_run(
                    prompt_text, worktree, manifest.timeout_seconds, agent_name=agent_name
                )
            score = _score_run(scoring, run_record, fixture)
        per_run_scores.append(score)
        invocation_modes.append(run_record.get("invocation_mode") or "raw-prompt")
        write_runlog(
            manifest.name,
            {
                "fixture_id": fixture.id,
                "run_index": i,
                "commit": commit,
                "content_hash": content_hash,
                "cli_status": run_record.get("status"),
                "latency_ms": run_record.get("latency_ms"),
                "turns_used": run_record.get("turns_used"),
                "cost_usd": run_record.get("cost_usd"),
                "invocation_mode": run_record.get("invocation_mode"),
                "primary": score.get("primary"),
                "score_status": score.get("status"),
                "final_text_preview": (run_record.get("final_text") or "")[:1000],
                "parse_warnings": run_record.get("_parse_warnings", []),
            },
        )

    row = agg_mod.aggregate(per_run_scores, fixture, manifest, commit, content_hash)
    # For agent-mode components, tag any row that fell back to raw-prompt so
    # readers can distinguish real named-subagent measurements from fallbacks.
    # Command-mode rows are always raw-prompt by design and do not get the tag.
    if invoke_mode == "agent" and invocation_modes and any(m != "two-level" for m in invocation_modes):
        row["description"] = f"[raw-prompt] {row['description']}"
    tsv.append_row(manifest.name, row)
    return row


def cmd_run(args: argparse.Namespace) -> int:
    inv_mod.probe_claude_cli()
    manifest = ld.load_component(args.component)
    content_hash = ld.compute_component_content_hash(manifest)
    commit = _git_head_commit()
    scoring = _load_scoring(manifest.scoring_module)

    n_runs = args.n if args.n is not None else manifest.n_runs

    if args.fixture:
        fixtures = [ld.load_fixture(manifest, args.fixture)]
    else:
        fixtures = ld.load_fixtures(manifest)
    if not fixtures:
        _log.error("No fixtures found for component %s", manifest.name)
        return 2

    # protocol_sha drift warning: each fixture records the SHA of the content
    # file(s) it was labeled against. If the current SHA differs, fixture
    # labels may be stale. Warn loudly but do not block - re-run fixture-label
    # review is the mitigation (see README).
    current_sha = ld.current_protocol_sha(manifest)
    if current_sha:
        for fx in fixtures:
            if fx.protocol_sha and fx.protocol_sha != current_sha:
                _log.warning(
                    "protocol_sha drift: fixture %s was labeled against %s but "
                    "current content SHA is %s (fixture: %s). Re-run fixture-label "
                    "review before trusting this score.",
                    fx.id,
                    fx.protocol_sha,
                    current_sha,
                    fx.path,
                )

    rows: list[dict] = []
    for fx in fixtures:
        row = _run_fixture(manifest, fx, n_runs, commit, content_hash, scoring)
        rows.append(row)
        _log.info(
            "  -> fixture=%s median=%.4f stdev=%.4f n=%d status=%s",
            fx.id,
            row["primary_score_median"],
            row["primary_score_stdev"],
            row["n_runs"],
            row["status"],
        )

    tsv_file = tsv.tsv_path(manifest.name)
    print(f"Wrote {len(rows)} rows to {tsv_file}")
    return 0


def cmd_list_components(_args: argparse.Namespace) -> int:
    names = ld.list_components()
    if not names:
        print("(no components found under evals/components/)")
        return 0
    for n in names:
        print(n)
    return 0


def cmd_show_results(args: argparse.Namespace) -> int:
    rows = tsv.read_rows(args.component)
    if not rows:
        print(f"(no TSV rows for component {args.component})")
        return 0
    for r in rows:
        print(
            f"{r['commit'][:8]}  fx={r['fixture_hash'][:8]}  "
            f"median={r['primary_score_median']:>6}  stdev={r['primary_score_stdev']:>6}  "
            f"n={r['n_runs']}  status={r['status']}  desc={r['description'][:60]}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.runner.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Run a component eval.")
    p_run.add_argument("component")
    p_run.add_argument("--fixture", default=None, help="Run only this fixture ID.")
    p_run.add_argument("--n", type=int, default=None, help="Override n_runs.")
    p_run.set_defaults(func=cmd_run)

    p_list = sub.add_parser("list-components")
    p_list.set_defaults(func=cmd_list_components)

    p_show = sub.add_parser("show-results")
    p_show.add_argument("component")
    p_show.set_defaults(func=cmd_show_results)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
