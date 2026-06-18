#!/usr/bin/env python3
"""
Purpose: UserPromptSubmit hook variant of the role-models bootstrap. Pi and
         oh-my-pi do not expose a UserPromptSubmit hook surface, so the
         canonical entry point is Step 6.5 of the activation preflight
         (content/sections/01-activation-preflight.md). This hook exists for
         harnesses that DO have a UserPromptSubmit surface and want the
         bootstrap to fire on every prompt rather than only on first activation
         of a fresh machine. It is optional and not registered by any current
         adapter install script.

         When the user has not yet configured `~/.agentic/role-models.yml`,
         this hook runs `bin/agentic-configure --non-interactive` to seed
         defaults from the live harness probe before the prompt reaches the
         model. After the first successful run, a sentinel file
         (`.agentic/.role-models-bootstrap`) prevents re-runs.

Public API: role-models-bootstrap.py
            Reads the hook payload from stdin (harness contract) and either:
              - exits 0 with no output (already bootstrapped, missing
                env / wrong harness, headless session, no probe URL), or
              - runs the configurator with --non-interactive and exits 0.
            Never blocks the prompt. Never deletes an existing
            role-models.yml. Never writes outside ~/.agentic/.

Upstream deps: bin/agentic-configure (the configurator);
               bin/agentic-models (probes the harness, called by the
               configurator).

Downstream consumers: harnesses that expose a UserPromptSubmit hook
                      surface. The activation preflight (Step 6.5) is the
                      canonical Pi/oh-my-pi entry point and does not depend
                      on this hook.

Failure modes: Probe failure -> configurator falls back to scalar defaults
               and still writes the file. Subsequent prompts find the
               file and skip the bootstrap. No retry loop. No error
               surfaced to the user unless they ask.

Performance: One HTTP probe on the very first prompt; subsequent prompts
             are a single stat() check. Sub-second on a warm probe.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from pathlib import Path

GLOBAL_CONFIG = Path(os.path.expanduser("~/.agentic/role-models.yml"))
SENTINEL = Path(os.path.expanduser("~/.agentic/.role-models-bootstrap"))
CONFIGURE_BIN = Path(__file__).parent.parent / "bin" / "agentic-configure"


def _is_pi_omp_harness() -> bool:
    """Best-effort runtime gate. Mirrors bin/agentic-status."""
    for key in ("PI_HARNESS", "OMP_HARNESS", "OH_MY_PI_HARNESS", "AGENTIC_HARNESS"):
        val = os.environ.get(key, "").lower()
        if val in ("pi", "omp", "oh-my-pi", "oh_my_pi"):
            return True
    return False


def _already_bootstrapped() -> bool:
    return SENTINEL.exists() or GLOBAL_CONFIG.exists()


def main() -> int:
    # Drain stdin -- the hook contract passes a JSON payload we do not need.
    with contextlib.suppress(OSError):
        sys.stdin.read()

    if not _is_pi_omp_harness():
        return 0
    if not CONFIGURE_BIN.is_file():
        return 0
    if _already_bootstrapped():
        return 0
    if not os.environ.get("NINEROUTER_URL"):
        # No probe URL means we cannot suggest models; skip silently. The
        # user can run `agentic-configure` later when they have a probe.
        return 0

    with contextlib.suppress(subprocess.SubprocessError, OSError):
        subprocess.run(
            [str(CONFIGURE_BIN), "--non-interactive"],
            timeout=30,
            check=False,
            capture_output=True,
        )
    SENTINEL.parent.mkdir(parents=True, exist_ok=True)
    SENTINEL.write_text(
        "# agentic-engineering: role-models bootstrap ran.\n"
        "# Delete this file to re-run the bootstrap on the next prompt.\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
