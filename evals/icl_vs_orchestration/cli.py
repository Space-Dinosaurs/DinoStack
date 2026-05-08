"""
Purpose: CLI entry point for the ICL-vs-orchestration eval harness.
         Exposes 'run' and 'resume' subcommands. Performs preflight checks
         for required binaries (python3, bun). Handles smoke-mode and
         smoke-gate dominance check. Exits with codes:
           0 = success
           1 = usage error
           2 = corpus/spec load error
           3 = budget exceeded (aborted)
           4 = preflight binary missing
           5 = report validation error

Public API: python -m evals.icl_vs_orchestration.cli <subcommand> [options]

Upstream deps: runner.py (RunConfig, run_eval, resume_run), corpus.py,
               schema.py, report.py; stdlib argparse, shutil, sys.

Downstream consumers: run.ts (bun wrapper), CI invocations.

Failure modes: exits with documented codes. All exceptions caught at top level
               and printed to stderr before exit. Never raises uncaught exceptions
               from normal usage.

Performance: startup overhead is negligible; dominated by run_eval().
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def _preflight() -> None:
    """Check required binaries are on PATH; exit 4 with message on miss."""
    missing = [b for b in ["python3", "bun"] if shutil.which(b) is None]
    if missing:
        for b in missing:
            print(
                f"PREFLIGHT ERROR: '{b}' is not on PATH. "
                f"Install it before running the ICL-vs-orchestration eval.",
                file=sys.stderr,
            )
        sys.exit(4)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.icl_vs_orchestration.cli",
        description="ICL-vs-orchestration eval harness",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # --- run subcommand ---
    run_p = sub.add_parser("run", help="Run eval from scratch")
    run_p.add_argument(
        "--corpus", required=True, help="Corpus name (under evals/icl_vs_orchestration/corpora/)"
    )
    run_p.add_argument(
        "--ae-spec", required=True, help="Path to AE condition spec YAML"
    )
    run_p.add_argument(
        "--icl-spec", required=True, help="Path to ICL baseline spec YAML"
    )
    run_p.add_argument("--smoke", action="store_true", help="Smoke mode: 5 tickets/cell")
    run_p.add_argument(
        "--smoke-gate", action="store_true", help="Apply dominance check after smoke"
    )
    run_p.add_argument("--max-tickets", type=int, default=None)
    run_p.add_argument(
        "--cells", nargs="+", default=[], help="Whitelist of cell IDs to run"
    )
    run_p.add_argument("--max-usd", type=float, default=300.0)
    run_p.add_argument("--max-tokens", type=int, default=30_000_000)
    run_p.add_argument("--max-usd-per-cell", type=float, default=None)
    run_p.add_argument("--max-tokens-per-cell", type=int, default=None)
    run_p.add_argument("--timeout", type=int, default=300)
    run_p.add_argument("--weights", type=Path, default=None)
    run_p.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Path to Stage-0 baseline JSON; reads git.agentic_engineering_sha",
    )

    # --- resume subcommand ---
    resume_p = sub.add_parser("resume", help="Resume an interrupted run")
    resume_p.add_argument("run_id", help="Run ID to resume")
    resume_p.add_argument(
        "--corpus", required=True, help="Corpus name (must match original run)"
    )
    resume_p.add_argument("--ae-spec", required=True)
    resume_p.add_argument("--icl-spec", required=True)
    resume_p.add_argument("--max-usd", type=float, default=300.0)
    resume_p.add_argument("--max-tokens", type=int, default=30_000_000)
    resume_p.add_argument("--max-usd-per-cell", type=float, default=None)
    resume_p.add_argument("--max-tokens-per-cell", type=int, default=None)
    resume_p.add_argument("--weights", type=Path, default=None)

    return parser


def main(argv: list[str] | None = None) -> None:
    # Preflight
    _preflight()

    parser = _build_parser()
    args = parser.parse_args(argv)

    _setup_logging()

    corpora_base = Path("evals/icl_vs_orchestration/corpora")

    if args.subcommand == "run":
        corpus_dir = corpora_base / args.corpus
        ae_spec_path = Path(args.ae_spec)
        icl_spec_path = Path(args.icl_spec)

        # Validate paths
        if not corpus_dir.exists():
            print(
                f"ERROR: Corpus directory not found: {corpus_dir}",
                file=sys.stderr,
            )
            sys.exit(2)
        if not ae_spec_path.exists():
            print(
                f"ERROR: AE spec not found: {ae_spec_path}",
                file=sys.stderr,
            )
            sys.exit(2)
        if not icl_spec_path.exists():
            print(
                f"ERROR: ICL spec not found: {icl_spec_path}",
                file=sys.stderr,
            )
            sys.exit(2)

        # Load baseline SHA if provided
        baseline_sha = None
        if args.baseline:
            from .corpus import load_baseline_sha
            try:
                baseline_sha = load_baseline_sha(args.baseline)
                print(f"Pinned AE content_sha from baseline: {baseline_sha}")
            except (FileNotFoundError, ValueError) as e:
                print(f"WARNING: Could not load baseline SHA: {e}", file=sys.stderr)

        from .runner import RunConfig, run_eval

        config = RunConfig(
            corpus_dir=corpus_dir,
            ae_spec_path=ae_spec_path,
            icl_spec_path=icl_spec_path,
            smoke=args.smoke,
            smoke_gate=args.smoke_gate,
            max_tickets=args.max_tickets,
            cells_whitelist=args.cells,
            max_usd_global=args.max_usd,
            max_tokens_global=args.max_tokens,
            max_usd_per_cell=args.max_usd_per_cell,
            max_tokens_per_cell=args.max_tokens_per_cell,
            timeout_seconds=args.timeout,
            weights_path=args.weights,
            baseline_sha=baseline_sha,
        )

        try:
            report = run_eval(config)
        except Exception as e:
            print(f"ERROR: run_eval failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)

        # Validate report schema; exit 5 on validation error.
        from .report import validate_report
        try:
            validate_report(report)
        except ValueError as e:
            print(f"ERROR: Report validation failed: {e}", file=sys.stderr)
            sys.exit(5)

        if report.get("aborted"):
            print(
                f"Run aborted: {report.get('abort_reason', 'budget exceeded')}",
                file=sys.stderr,
            )
            sys.exit(3)

        print(
            f"Run complete. Report: "
            f"evals/icl_vs_orchestration/results/{config.run_id}/results-v1.json"
        )

    elif args.subcommand == "resume":
        run_id = args.run_id
        run_dir = Path(".runtime") / run_id
        if not run_dir.exists():
            print(f"ERROR: Run dir not found: {run_dir}", file=sys.stderr)
            sys.exit(1)

        from .runner import RunConfig, resume_run

        corpus_dir = corpora_base / args.corpus
        config = RunConfig(
            corpus_dir=corpus_dir,
            ae_spec_path=Path(args.ae_spec),
            icl_spec_path=Path(args.icl_spec),
            max_usd_global=args.max_usd,
            max_tokens_global=args.max_tokens,
            max_usd_per_cell=args.max_usd_per_cell,
            max_tokens_per_cell=args.max_tokens_per_cell,
            weights_path=args.weights,
            run_id=run_id,
        )
        try:
            report = resume_run(run_id=run_id, run_dir=run_dir, config=config)
        except Exception as e:
            print(f"ERROR: resume_run failed: {e}", file=sys.stderr)
            sys.exit(1)

        print(
            f"Resume complete. Report: "
            f"evals/icl_vs_orchestration/results/{run_id}/results-v1.json"
        )


def _setup_logging() -> None:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


if __name__ == "__main__":
    main()
