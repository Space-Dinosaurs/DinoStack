"""
Purpose: Assemble per-component invocation prompts and stage fixture companion
         files into the worktree's ./evals-fixture/ dir. Dispatch prompt
         construction by component name via a registry so new components can
         be added without touching the invoker.

Public API: build_prompt(component_name: str, fixture: Fixture) -> str,
            build_skeptic_prompt(fixture: Fixture) -> str,
            build_conductor_prompt(fixture: Fixture) -> str,
            stage_fixture_files(fixture: Fixture, worktree: pathlib.Path) -> pathlib.Path,
            BUILDERS: dict mapping component name -> builder callable.

Upstream deps: stdlib pathlib, shutil; evals.runner.loader.Fixture.

Downstream consumers: evals.runner.invoker, evals.runner.cli.

Failure modes: raises FileNotFoundError if a fixture's companion files
               referenced in inputs are missing from the fixture dir.
               build_prompt raises KeyError if the component name has no
               registered builder - the registry is the source of truth
               for which components the runner can prompt-build for.

Performance: standard.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .loader import Fixture


def stage_fixture_files(fixture: Fixture, worktree: Path) -> Path:
    """Stage known companion files (diff, worker output) into worktree.

    Component-agnostic: only copies files whose keys it recognises in
    fixture.inputs. Components without companion files (e.g. conductor, whose
    fixture data is all inline in observed_state) are a no-op here.
    """
    stage_dir = worktree / "evals-fixture"
    stage_dir.mkdir(parents=True, exist_ok=True)
    for key in ("diff_file", "worker_output_file"):
        rel = fixture.inputs.get(key)
        if not rel:
            continue
        src = fixture.dir / rel
        if not src.exists():
            raise FileNotFoundError(f"Fixture companion file missing: {src}")
        shutil.copy2(src, stage_dir / Path(rel).name)
    return stage_dir


def _read_companion(fixture: Fixture, key: str) -> str:
    rel = fixture.inputs.get(key)
    if not rel:
        return ""
    path = fixture.dir / rel
    if not path.exists():
        raise FileNotFoundError(f"Fixture companion file missing: {path}")
    return path.read_text(encoding="utf-8")


def build_skeptic_prompt(fixture: Fixture) -> str:
    """Build the Skeptic brief.

    Assembles the inner brief (adversarial brief + worker diff/narrative +
    resolved-issues preflight + sign-off instruction) that the invoker passes
    verbatim to the named Skeptic subagent via the Task spawn. The subagent
    already has its role, calibration, and sign-off format loaded from
    content/agents/skeptic.md, so this brief does not repeat the role. The
    expect_subagent / spawn-path handling lives in evals.runner.invoker, not
    here.
    """
    brief = fixture.inputs.get("adversarial_brief", "").rstrip()
    diff_text = _read_companion(fixture, "diff_file")
    worker_text = _read_companion(fixture, "worker_output_file")

    parts = [
        "## Adversarial brief",
        brief,
        "",
        "## Worker output",
        "Diff (also at ./evals-fixture/diff.patch):",
        "```",
        diff_text.rstrip(),
        "```",
        "",
        "Worker narrative (also at ./evals-fixture/worker_output.md):",
        "```",
        worker_text.rstrip(),
        "```",
        "",
        "## Resolved issues preflight",
        "No prior rounds.",
        "",
        "Produce your sign-off using the exact format specified in your role.",
    ]
    return "\n".join(parts) + "\n"


def _format_findings(findings: list[dict]) -> str:
    if not findings:
        return "  (none)"
    lines = []
    for f in findings:
        sev = f.get("severity", "?")
        fid = f.get("id", "?")
        re_raised = f.get("re_raised", False)
        lines.append(f"  - [{sev}] {fid}  (re_raised={'true' if re_raised else 'false'})")
    return "\n".join(lines)


def build_conductor_prompt(fixture: Fixture) -> str:
    """Build the orchestration-planner routing-decision brief.

    The conductor eval presents a mid-flow scenario (goal, observed state,
    open findings, phase) and asks the named orchestration-planner to emit a
    single structured routing decision. The response must end with a fenced
    JSON block under an exact heading so the scorer can parse it
    mechanically.

    The named subagent already has its role loaded from
    content/agents/orchestration-planner.md and the routing rules from
    content/rules/agent-methodology.md - this prompt does not repeat the
    role, it supplies the scenario and the output contract.
    """
    raw = fixture.raw or {}
    scenario = (raw.get("scenario") or "").rstrip()
    observed = raw.get("observed_state") or {}
    invoke_instruction = (fixture.inputs.get("invoke_instruction") or "").rstrip()

    phase = observed.get("phase", "?")
    iteration = observed.get("iteration", 0)
    max_iter = observed.get("max_iterations", 3)
    last_status = observed.get("last_engineer_status", None)
    open_findings = observed.get("open_findings") or []
    risk_signals = observed.get("risk_signals") or []
    qa_triggers = observed.get("qa_triggers_matched", None)
    other_context = (observed.get("other_context") or "").rstrip()

    findings_block = _format_findings(open_findings)
    risk_signals_str = ", ".join(risk_signals) if risk_signals else "(none)"

    # Avoid nested triple-backtick collisions in a triple-quoted Python string
    # by building the example block programmatically.
    fence_open = "```json"
    fence_close = "```"

    parts = [
        "You are being invoked as the orchestration-planner subagent for an "
        "eval run. Follow content/agents/orchestration-planner.md.",
        "",
        "## Scenario",
        scenario,
        "",
        "## Observed state",
        f"phase: {phase}",
        f"iteration: {iteration} / {max_iter}",
        f"last_engineer_status: {last_status}",
        "open_findings:",
        findings_block,
        f"risk_signals: {risk_signals_str}",
        f"qa_triggers_matched: {qa_triggers}",
        "other_context: |",
        "  " + other_context.replace("\n", "\n  ") if other_context else "  (none)",
        "",
        "## Task",
        invoke_instruction or "Given the observed state above, state the single next routing action.",
        "",
        'Your response must end with a fenced json code block under a heading exactly '
        '"## Routing decision (machine-readable)" containing the fields: '
        "decision_class, next_agent, loop_action, rationale. Do not include any "
        "text after the JSON block.",
        "",
        "Example of the required final block:",
        "",
        "## Routing decision (machine-readable)",
        fence_open,
        "{",
        '  "decision_class": "re_enter_loop",',
        '  "next_agent": "engineer",',
        '  "loop_action": "re_enter",',
        '  "rationale": "Major findings remain and iteration < cap."',
        "}",
        fence_close,
    ]
    return "\n".join(parts) + "\n"


# Builder registry. Keyed by component name (matches the manifest `name`
# field). Adding a new component eval means adding its builder here; the
# invoker dispatches through this map and does not know about individual
# components.
BUILDERS = {
    "skeptic": build_skeptic_prompt,
    "conductor": build_conductor_prompt,
}


def build_prompt(component_name: str, fixture: Fixture) -> str:
    """Dispatch to the registered builder for the component."""
    try:
        builder = BUILDERS[component_name]
    except KeyError as e:
        raise KeyError(
            f"No prompt builder registered for component '{component_name}'. "
            f"Known builders: {sorted(BUILDERS)}"
        ) from e
    return builder(fixture)
