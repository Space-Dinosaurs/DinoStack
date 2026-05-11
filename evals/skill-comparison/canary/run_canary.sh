#!/usr/bin/env bash
# run_canary.sh - Run the skill-comparison canary and save the transcript.
#
# Usage: bash evals/skill-comparison/canary/run_canary.sh
#
# What it does:
#   1. Invokes the skeptic agent via two-level Task spawn (using invoker.run_session
#      mode="agent", agent_name="skeptic") against a minimal canary prompt.
#   2. Saves the raw stream-json transcript to evals/skill-comparison/canary/skeptic.jsonl.
#   3. Runs assert_canary.py on the saved transcript.
#   4. Exits 0 if the canary passes; non-zero otherwise.
#
# Prerequisites:
#   - `claude` CLI is on PATH and authenticated.
#   - Python 3.11+ is available as `python3`.
#   - Run from the repository root (agentic-engineering/).
#
# This script is provided for operator/conductor execution when the engineer
# cannot run the harness directly inside the worker worktree.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
CANARY_DIR="${REPO_ROOT}/evals/skill-comparison/canary"
TRANSCRIPT_PATH="${CANARY_DIR}/skeptic.jsonl"
SCRIPT_DIR="${REPO_ROOT}/evals/skill-comparison"

echo "[canary] Running skill-comparison canary for agent: skeptic"
echo "[canary] Transcript will be saved to: ${TRANSCRIPT_PATH}"

# Use Python to invoke the harness so we get the same path as runner.py.
python3 - <<'PYEOF'
import sys
import os
import tempfile
from pathlib import Path

repo_root = Path(os.environ.get("REPO_ROOT", ".")).resolve()
sys.path.insert(0, str(repo_root))

from evals.runner.invoker import invoke_run, probe_claude_cli

# Verify claude CLI is available.
try:
    version = probe_claude_cli()
    print(f"[canary] Claude CLI version: {version}", file=sys.stderr)
except RuntimeError as exc:
    print(f"[canary] ERROR: {exc}", file=sys.stderr)
    sys.exit(1)

# Canary brief: minimal prompt that exercises the skeptic agent.
# We use a trivial diff so the skeptic has something to review without
# needing the full eval task corpus.
CANARY_BRIEF = """\
You are performing a Skeptic review of the following trivial patch.

Adversarial brief: Check that the implementation does not introduce any
Critical or Major findings.

Worker output:
  Changed: src/utils.py - added a one-line docstring to `parse_input()`.

Global-context inputs:
  - architect plan path: n/a (canary run - no real plan)
  - Brief/Plan artifact path: n/a
  - qa_criteria: n/a
  - per-consumer impact table: n/a
  - related files: n/a
  - diff under review: |
      --- a/src/utils.py
      +++ b/src/utils.py
      @@ -1,3 +1,4 @@
      +\"\"\"Utility helpers for parsing input.\"\"\"
       def parse_input(text):
           return text.strip()

Resolved-issues preflight: No prior rounds.

Provide a structured sign-off response.
"""

transcript_path = Path(
    os.environ.get("TRANSCRIPT_PATH",
                   str(Path(__file__).parent / "skeptic.jsonl"))
)

# Use a temp worktree for the canary run.
with tempfile.TemporaryDirectory(prefix="canary-") as tmp:
    worktree = Path(tmp)
    result = invoke_run(
        prompt=CANARY_BRIEF,
        worktree=worktree,
        timeout_seconds=120,
        agent_name="skeptic",
        mode="agent",
    )
    status = result.get("status", "ok")
    print(f"[canary] Invocation status: {status}", file=sys.stderr)

# The raw stream-json was captured inside invoke_run via subprocess.
# We need to re-run with raw stdout capture to get the JSONL transcript.
# invoke_run returns parsed data; for the raw JSONL we shell out directly.
import subprocess, shutil, time

CLAUDE_BIN = "claude"
from evals.runner.invoker import build_two_level_prompt, _ALLOWED_TOOLS, _MAX_TURNS

outer_prompt = build_two_level_prompt("skeptic", CANARY_BRIEF)
cmd = [
    CLAUDE_BIN, "-p", outer_prompt,
    "--output-format", "stream-json",
    "--verbose",
    "--allowed-tools", _ALLOWED_TOOLS,
    "--permission-mode", "default",
    "--max-turns", _MAX_TURNS,
]

print(f"[canary] Spawning: {' '.join(cmd[:4])} ...", file=sys.stderr)
t0 = time.monotonic()
proc = subprocess.run(
    cmd,
    cwd=str(repo_root),
    capture_output=True,
    text=True,
    timeout=180,
)
elapsed = time.monotonic() - t0
print(f"[canary] Completed in {elapsed:.1f}s, returncode={proc.returncode}", file=sys.stderr)

if proc.returncode != 0:
    print(f"[canary] STDERR:\n{proc.stderr[-2000:]}", file=sys.stderr)
    if not proc.stdout.strip():
        print("[canary] ERROR: No stdout captured - cannot save transcript.", file=sys.stderr)
        sys.exit(1)

# Save the transcript.
transcript_path.write_text(proc.stdout, encoding="utf-8")
print(f"[canary] Transcript saved to {transcript_path} ({len(proc.stdout)} bytes)", file=sys.stderr)
PYEOF

echo "[canary] Running assertion script..."
TRANSCRIPT_PATH="${TRANSCRIPT_PATH}" python3 "${CANARY_DIR}/assert_canary.py" "${TRANSCRIPT_PATH}"
EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 0 ]; then
    echo "[canary] PASS - canary green. Two-level Task spawn of skeptic confirmed."
else
    echo "[canary] FAIL - see diagnostics above. Downstream non-baseline cells are BLOCKED." >&2
fi

exit $EXIT_CODE
