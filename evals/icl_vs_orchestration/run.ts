/**
 * Bun wrapper for the ICL-vs-orchestration eval harness.
 *
 * Usage:
 *   bun evals/icl_vs_orchestration/run.ts [args...]
 *   bun evals/icl_vs_orchestration/run.ts --smoke --corpus smoke \
 *       --ae-spec evals/icl_vs_orchestration/specs/ae-orchestrated.yaml \
 *       --icl-spec evals/icl_vs_orchestration/specs/icl-baseline.yaml
 *
 * Preflight: checks that python3 is on PATH before delegating.
 * Exits 4 with a message naming the missing binary if not found.
 * All other args are forwarded verbatim to:
 *   python -m evals.icl_vs_orchestration.cli run [args...]
 *
 * Default subcommand is 'run'. Pass 'resume <run_id>' as first args for resume.
 */

import { $ } from "bun";

// Preflight: verify python3 is available
const python3 = Bun.which("python3");
if (!python3) {
  console.error(
    "PREFLIGHT ERROR: 'python3' is not on PATH. " +
      "Install Python 3.11+ before running the ICL-vs-orchestration eval."
  );
  process.exit(4);
}

// Determine subcommand from args
const args = process.argv.slice(2);
let subcommand = "run";
let forwardArgs = args;

if (args[0] === "resume") {
  subcommand = "resume";
  forwardArgs = args;
} else if (args[0] === "run") {
  subcommand = "run";
  forwardArgs = args.slice(1);
}

// Delegate to Python CLI
const result = await $`${python3} -m evals.icl_vs_orchestration.cli ${subcommand} ${forwardArgs}`.nothrow();

process.exit(result.exitCode ?? 0);
