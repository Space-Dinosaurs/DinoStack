"""
Purpose: Command-line entry point for the evals runner. Subcommands:
         run, list-components, show-results.

Public API: main(argv: list[str] | None = None) -> int; invoked via
            `python -m evals.runner.cli`.

Upstream deps: stdlib argparse, concurrent.futures, importlib, subprocess, sys, json;
               evals.runner.{loader, isolator, invoker, prompt, aggregator,
               tsv_writer, normalizer, logging}.

Downstream consumers: humans running evals; CI (future).

Failure modes: Exits non-zero on missing components, missing fixtures, absent
               Claude CLI, or unhandled runner exceptions. Per-fixture worker
               exceptions are captured as error rows (status="scoring_error")
               so a crashed fixture yields an error row, not a missing row.
               All TSV + runlog writes happen single-threaded after the
               ThreadPoolExecutor joins (no concurrent-append race).

Performance: fixtures run in parallel via a bounded ThreadPoolExecutor
             (default 4 workers, clamped to len(fixtures)). Each fixture
             gets its own isolated wt-<uuid> worktree via isolator.py (tier
             determined per manifest: Tier-1 for agent-mode, Tier-2 for
             command-mode), so workers share no mutable state during
             execution. Writes are single-threaded post-join, sorted by
             fixture_id, so exactly n_fixtures rows land contiguously per
             run-commit.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

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


class _FixtureResult(NamedTuple):
    """Transport type returned by _run_fixture (worker side).

    row: the aggregated TSV row dict (keys match TSV_HEADER; ready for
         tsv.append_row after the executor joins).
    runlog_records: per-run records to be written via write_runlog after join,
                    in run-index order.
    """
    row: dict
    runlog_records: list[dict]


def _run_fixture(
    manifest: ld.ComponentManifest,
    fixture: ld.Fixture,
    n_runs: int,
    commit: str,
    content_hash: str,
    scoring,
    max_turns: int | None = None,
    backend: str = "claude",
    model: str = "sonnet",
) -> _FixtureResult:
    """Execute all n_runs for one fixture; return aggregated row + runlog records.

    Does NOT write to TSV or runlog. All writes happen single-threaded in
    cmd_run after the executor joins, so there is no concurrent-append race
    on the TSV file (tsv_writer is not thread-safe).

    Each invocation uses its own isolator worktree (Tier1Worktree creates a
    unique wt-<uuid12> path per __enter__ call), so parallel calls are safe.
    """
    per_run_scores: list[dict] = []
    invocation_modes: list[str] = []
    runlog_records: list[dict] = []
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
                # Optional per-fixture seed hook: some components (e.g.
                # cleanup-worktrees) need to realize a git-state topology
                # that cannot be captured by a static `repo/` snapshot
                # alone. If the fixture directory contains a `seed.sh`,
                # run it with cwd=worktree and HOME=fake_home BEFORE the
                # CLI is spawned. The seed script is expected to be
                # idempotent-per-fixture and may write files under
                # $HOME/bin/ (e.g. a `gh` stub).
                seed_script = fixture.dir / "seed.sh"
                if seed_script.exists():
                    import os as _os
                    seed_env = _os.environ.copy()
                    seed_env["HOME"] = str(fake_home)
                    seed_env["PATH"] = f"{fake_home}/bin:" + seed_env.get("PATH", "")
                    seed_result = subprocess.run(
                        ["bash", str(seed_script)],
                        cwd=str(worktree),
                        capture_output=True,
                        text=True,
                        env=seed_env,
                        timeout=60,
                    )
                    if seed_result.returncode != 0:
                        _log.error(
                            "Seed hook failed for fixture %s: rc=%d stderr=%s",
                            fixture.id,
                            seed_result.returncode,
                            (seed_result.stderr or "").strip()[-500:],
                        )
                # Per-component worktree preparation hook. Runs AFTER the
                # isolator copies the seeded repo into the tmpdir and
                # BEFORE the Claude CLI is spawned. Used by
                # update-agentic-engineering to perform `git init`, add
                # a sibling bare repo as `origin`, and seed the fixture
                # pre-state (origin-ahead commits, local-ahead commits,
                # dirty-tree WIP) so the command sees a realistic repo
                # on startup.
                preparer = getattr(pr_mod, "WORKTREE_PREPARERS", {}).get(manifest.name)
                if preparer is not None:
                    preparer(fixture, worktree)
                prompt_text = pr_mod.build_prompt(manifest.name, fixture)
                run_record = inv_mod.invoke_run(
                    prompt_text,
                    worktree,
                    manifest.timeout_seconds,
                    mode="command",
                    home=fake_home,
                    max_turns=max_turns,
                    backend=backend,
                    model=model,
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
                    prompt_text, worktree, manifest.timeout_seconds,
                    agent_name=agent_name, max_turns=max_turns,
                    backend=backend,
                    model=model,
                )
            score = _score_run(scoring, run_record, fixture)
        per_run_scores.append(score)
        invocation_modes.append(run_record.get("invocation_mode") or "raw-prompt")
        runlog_records.append({
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
        })

    row = agg_mod.aggregate(per_run_scores, fixture, manifest, commit, content_hash)
    # For agent-mode components, tag any row that fell back to raw-prompt so
    # readers can distinguish real named-subagent measurements from fallbacks.
    # Command-mode rows are always raw-prompt by design and do not get the tag.
    if invoke_mode == "agent" and invocation_modes and any(m != "two-level" for m in invocation_modes):
        row["description"] = f"[raw-prompt] {row['description']}"
    return _FixtureResult(row=row, runlog_records=runlog_records)


def cmd_run(args: argparse.Namespace) -> int:
    inv_mod.probe_cli(args.backend)
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

    # Clamp: at least 1 (guard against --workers 0 or negative), at most
    # len(fixtures) (no point spinning idle threads).
    effective_workers = max(1, min(args.workers, len(fixtures)))

    # Submit all fixtures to the thread pool. Each fixture gets its own
    # isolator worktree (Tier1Worktree creates a unique wt-<uuid12> path per
    # __enter__ call - confirmed via isolator.py), so workers share no
    # mutable state inside _run_fixture.
    futures: dict[concurrent.futures.Future, ld.Fixture] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=effective_workers) as executor:
        for fx in fixtures:
            f = executor.submit(
                _run_fixture,
                manifest, fx, n_runs, commit, content_hash, scoring,
                max_turns=args.max_turns,
                backend=args.backend,
                model=args.model,
            )
            futures[f] = fx

    n_rows = _collect_and_write(futures, manifest, commit, content_hash)
    tsv_file = tsv.tsv_path(manifest.name)
    print(f"Wrote {n_rows} rows to {tsv_file}")
    return 0


def _collect_and_write(
    futures: "dict[concurrent.futures.Future, ld.Fixture]",
    manifest: ld.ComponentManifest,
    commit: str,
    content_hash: str,
) -> int:
    """Collect future results, build error rows for exceptions, sort, and write.

    Separated from cmd_run so tests can drive this logic with a mocked
    _run_fixture without constructing a full argparse.Namespace or loader.

    Returns the number of TSV rows written.

    Invariants:
    - Every fixture in `futures` yields exactly one row (error row on exception).
    - TSV rows are written in fixture_id lexicographic order (deterministic).
    - All writes happen in this function (single-threaded, post-join); callers
      must not write TSV or runlog rows before calling this function.
    """
    # Collect results after executor join. Per-fixture exceptions are captured
    # as error rows (status="scoring_error") so every fixture yields exactly
    # one row - crashed fixture -> error row, not missing row.
    result_pairs: list[tuple[str, _FixtureResult]] = []
    for f, fx in futures.items():
        try:
            fixture_result = f.result()
        except Exception as exc:
            _log.error("Worker exception for fixture %s: %s", fx.id, exc, exc_info=True)
            error_row = agg_mod.aggregate(
                [{"primary": 0.0, "status": "scoring_error", "diagnostic": {"error": str(exc)}}],
                fx,
                manifest,
                commit,
                content_hash,
            )
            fixture_result = _FixtureResult(row=error_row, runlog_records=[])
        result_pairs.append((fx.id, fixture_result))

    # Sort by fixture_id for deterministic write order: rows land contiguously
    # per run-commit in a stable order aggregate_latest can rely on when
    # filtering by expected_commit.
    result_pairs.sort(key=lambda t: t[0])

    # Single-threaded post-join batch write: all TSV rows first, then all
    # runlog records (both in fixture_id order). tsv_writer is not thread-safe;
    # writing here (after executor join) eliminates the race.
    rows: list[dict] = []
    all_runlog_records: list[dict] = []
    for _fx_id, fixture_result in result_pairs:
        rows.append(fixture_result.row)
        all_runlog_records.extend(fixture_result.runlog_records)

    for row in rows:
        tsv.append_row(manifest.name, row)

    for rec in all_runlog_records:
        write_runlog(manifest.name, rec)

    # Per-fixture log summary (preserves original output format).
    for fx_id, fixture_result in result_pairs:
        row = fixture_result.row
        _log.info(
            "  -> fixture=%s median=%.4f stdev=%.4f n=%d status=%s",
            fx_id,
            row["primary_score_median"],
            row["primary_score_stdev"],
            row["n_runs"],
            row["status"],
        )

    return len(rows)


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
    p_run.add_argument(
        "--workers",
        type=int,
        default=4,
        dest="workers",
        help=(
            "Max parallel fixture workers (default: 4). "
            "Clamped to len(fixtures) if fewer fixtures than workers."
        ),
    )
    p_run.add_argument(
        "--max-turns",
        type=int,
        default=None,
        dest="max_turns",
        help=(
            "Override --max-turns passed to the Claude CLI for agent-mode runs "
            f"(default: {inv_mod._MAX_TURNS_DEFAULT}). Raise for SWE-bench fix "
            "tasks that need many tool iterations."
        ),
    )
    p_run.add_argument(
        "--backend",
        choices=["claude", "kimi"],
        default="claude",
        help=(
            "CLI backend to use for eval runs. 'claude' (default) uses Claude Code; "
            "'kimi' uses the Kimi CLI."
        ),
    )
    p_run.add_argument(
        "--model",
        default="sonnet",
        help=(
            "Model alias passed to the CLI backend (default: sonnet). "
            "Passed verbatim as --model to the underlying CLI invocation."
        ),
    )
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
