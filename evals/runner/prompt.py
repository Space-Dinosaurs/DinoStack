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
        "## Required output vocabulary",
        "",
        'Your "decision_class" MUST be exactly one of these string values:',
        '- "escalate_cap_reached"',
        '- "escalate_convergence_failure"',
        '- "escalate_blocked"',
        '- "tight_fix_path"',
        '- "re_enter_loop"',
        '- "proceed_to_next_phase"',
        '- "terminate_clean"',
        '- "trivial_direct_edit"',
        '- "spawn_agent"',
        "",
        'Your "loop_action" MUST be exactly one of: "re_enter", "exit_clean", '
        '"exit_stalled", or null (use null when no loop action applies).',
        "",
        'Your "next_agent" MUST be null or one of the named agent slugs: '
        '"adr-drift-detector", "adr-generator", "architect", "debugger", '
        '"dependency-auditor", "engineer", "investigator", '
        '"orchestration-planner", "perf-analyst", "qa-engineer", '
        '"release-orchestrator", "security-auditor", "skeptic".',
        "",
        "These enum values are the machine-parseable labels the scorer expects. "
        "Choose the single value that best describes the routing decision you "
        "would make; do not invent new labels or paraphrase these.",
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


_REPO_ROOT_P = Path(__file__).resolve().parent.parent.parent


def build_init_project_prompt(fixture: Fixture) -> str:
    """Build the command-mode prompt for a /init-project eval run.

    The runner cannot invoke `/init-project` as a slash command under a
    redirected HOME (the command body is not installed into the fake
    ~/.claude/). Instead, we inline the verbatim body of
    content/commands/init-project.md into the prompt alongside a synthetic
    auto-memory banner (which the command looks for to derive the memory
    dir), a fixture-context preface, a non-interactivity directive, and an
    explicit "Required outputs" block that enumerates the paths the scorer
    will check (vocabulary enforcement at the prompt layer, per
    evals/LEARNINGS.md).
    """
    inputs = fixture.inputs or {}
    expected = (fixture.raw or {}).get("expected_outputs") or {}
    signals = set(expected.get("expected_signals") or [])

    must_exist = list(expected.get("must_exist") or [])
    cond = expected.get("must_exist_conditional") or {}
    for sig in signals:
        for p in cond.get(sig, []):
            if p not in must_exist:
                must_exist.append(p)

    command_path = _REPO_ROOT_P / "content" / "commands" / "init-project.md"
    if not command_path.exists():
        raise FileNotFoundError(f"init-project command body missing: {command_path}")
    command_body = command_path.read_text(encoding="utf-8")

    # The synthetic auto-memory banner mirrors what Claude Code injects at
    # session start when autoMemoryDirectory is pinned. /init-project Step 8
    # looks for this exact phrasing to derive the memory dir path.
    auto_memory_banner = (
        "This is a persistent auto memory directory at ./.agentic/memory/. "
        "You can use it for notes that persist across sessions."
    )

    non_interactivity = (
        "Do not prompt the user at any point. Where the command body below "
        "instructs you to confirm or ask (including but not limited to: "
        "tracker-selection prompts, Linear-migration prompts, 'Proceed?' "
        "confirmations, and Step 2a [y/N] prompts), proceed with the "
        "auto-discovered defaults. If a required field cannot be "
        "auto-discovered, write the file with the template's TODO "
        "placeholder so it remains auditable. Never block waiting for input."
    )

    required_outputs_lines = ["The following files must exist after you finish:"]
    for p in must_exist:
        required_outputs_lines.append(f"- {p}")
    required_outputs_lines.append("")
    mne = expected.get("must_not_exist") or []
    if mne:
        required_outputs_lines.append("The following files MUST NOT be created:")
        for p in mne:
            required_outputs_lines.append(f"- {p}")
        required_outputs_lines.append("")
    sections = expected.get("agents_md_required_sections") or []
    if sections:
        required_outputs_lines.append(
            "AGENTS.md must contain these sections (as verbatim line prefixes):"
        )
        for s in sections:
            required_outputs_lines.append(f"- {s!r}")
        max_lines = expected.get("agents_md_max_lines")
        if max_lines:
            required_outputs_lines.append(
                f"AGENTS.md must be at most {max_lines} lines."
            )
        required_outputs_lines.append("")
    gi_lines = expected.get("gitignore_required_lines") or []
    if gi_lines:
        required_outputs_lines.append(
            ".gitignore must contain each of these substrings:"
        )
        for s in gi_lines:
            required_outputs_lines.append(f"- `{s}`")
        required_outputs_lines.append("")

    required_outputs_block = "\n".join(required_outputs_lines).rstrip()

    parts = [
        f"<SYNTHETIC_AUTO_MEMORY_BANNER>\n{auto_memory_banner}",
        "",
        "<FIXTURE_CONTEXT>",
        (
            "You are running the /init-project command against the repository "
            "rooted at the current working directory. Your $HOME is redirected "
            "for this session; a project-level config lives at "
            "$HOME/.claude/agentic-engineering.json and may already be seeded."
        ),
        "",
        "<NON_INTERACTIVITY_DIRECTIVE>",
        non_interactivity,
        "",
        "<REQUIRED_OUTPUTS>",
        required_outputs_block,
        "",
        "<COMMAND_BODY>",
        "The verbatim body of content/commands/init-project.md follows. "
        "Execute it against this repository:",
        "",
        command_body.rstrip(),
        "",
        "<COMPLETION_MARKER>",
        "When finished, print a final line exactly: INIT_PROJECT_DONE",
    ]
    _ = inputs  # inputs currently unused here; home_config is applied by isolator.
    return "\n".join(parts) + "\n"


def build_wrap_prompt(fixture: Fixture) -> str:
    """Build the command-mode prompt for a /wrap eval run.

    The runner cannot invoke `/wrap` as a slash command under a redirected
    HOME (same caveat as /init-project; see LEARNINGS). We inline the
    verbatim body of content/commands/wrap.md into the prompt alongside:

      - a synthetic auto-memory banner
      - a fixture-context preface that hands the seeded session transcript
        to the command as its authoritative session memory
      - a non-interactivity directive that includes a seed-commit step and
        any fixture-specific `pre_wrap_git_setup` shell commands
      - a required-outputs block enumerating the paths the scorer will
        check
      - a completion marker "WRAP_DONE"

    Fail-fast: if the fixture's seeded AGENTS.md does not carry the
    literal "agentic-engineering: opt-in" line, the /wrap Activation
    preflight will no-op and the run will produce nothing. We raise here
    before the CLI is spawned so the failure mode is visible in the
    runner output rather than silently scoring zero.
    """
    inputs = fixture.inputs or {}
    expected = (fixture.raw or {}).get("expected_outputs") or {}

    repo_dir_rel = inputs.get("repo_dir")
    if not repo_dir_rel:
        raise ValueError(f"wrap fixture {fixture.id} missing inputs.repo_dir")
    agents_md_path = fixture.dir / repo_dir_rel / "AGENTS.md"
    if not agents_md_path.exists():
        raise FileNotFoundError(
            f"wrap fixture {fixture.id}: seeded AGENTS.md missing at {agents_md_path}"
        )
    agents_md_text = agents_md_path.read_text(encoding="utf-8")
    if "agentic-engineering: opt-in" not in agents_md_text:
        raise ValueError(
            f"wrap fixture {fixture.id}: seeded AGENTS.md at {agents_md_path} "
            "does not contain the literal line 'agentic-engineering: opt-in'. "
            "The /wrap Activation preflight will no-op without that marker; "
            "refusing to run to prevent silent zero-scoring."
        )

    transcript_path = fixture.dir / repo_dir_rel / ".agentic" / "session-transcript.md"
    if not transcript_path.exists():
        raise FileNotFoundError(
            f"wrap fixture {fixture.id}: session transcript missing at {transcript_path}"
        )
    transcript_text = transcript_path.read_text(encoding="utf-8")

    command_path = _REPO_ROOT_P / "content" / "commands" / "wrap.md"
    if not command_path.exists():
        raise FileNotFoundError(f"wrap command body missing: {command_path}")
    command_body = command_path.read_text(encoding="utf-8")

    auto_memory_banner = (
        "This is a persistent auto memory directory at ./.agentic/memory/. "
        "You can use it for notes that persist across sessions."
    )

    fixture_context = (
        "You are finalizing a coding session with /wrap. The session "
        "transcript below is the authoritative record of what happened "
        "this session. Treat it as your session memory for Step 0 "
        "compilation."
    )

    pre_setup = inputs.get("pre_wrap_git_setup") or []
    pre_setup_block_lines = [
        "Before running any git command inside the worktree, first run "
        "`git init -q && git add -A && git commit -q -m 'fixture seed' "
        "--allow-empty` to establish a baseline commit so HEAD exists."
    ]
    if pre_setup:
        pre_setup_block_lines.append(
            "Then, before invoking the /wrap body below, run these shell "
            "commands in order to reproduce the state the transcript "
            "describes:"
        )
        for cmd in pre_setup:
            pre_setup_block_lines.append(f"- `{cmd}`")

    non_interactivity = (
        "Do not prompt the user at any point. Where the command body "
        "instructs you to confirm or ask (including user-abort paths), "
        "proceed with the auto-discovered defaults. If a required field "
        "cannot be auto-discovered, write the template's placeholder so "
        "it remains auditable. Never block waiting for input. "
        + " ".join(pre_setup_block_lines)
    )

    must_exist = list(expected.get("must_exist") or [])
    must_not_exist = list(expected.get("must_not_exist") or [])
    required_sections = list(expected.get("context_md_required_sections") or [])

    required_outputs_lines: list[str] = []
    if must_exist:
        required_outputs_lines.append("The following files must exist after you finish:")
        for p in must_exist:
            required_outputs_lines.append(f"- {p}")
        required_outputs_lines.append("")
    if must_not_exist:
        required_outputs_lines.append("The following files MUST NOT be present when you finish:")
        for p in must_not_exist:
            required_outputs_lines.append(f"- {p}")
        required_outputs_lines.append("")
    if required_sections:
        required_outputs_lines.append(
            ".agentic/context.md must contain these sections (verbatim line prefixes):"
        )
        for s in required_sections:
            required_outputs_lines.append(f"- {s!r}")
        required_outputs_lines.append("")
    if not required_outputs_lines:
        required_outputs_lines.append(
            "No explicit required-output paths for this scenario - "
            "follow the routing logic in the command body and write only "
            "what the route prescribes."
        )
    required_outputs_block = "\n".join(required_outputs_lines).rstrip()

    parts = [
        f"<SYNTHETIC_AUTO_MEMORY_BANNER>\n{auto_memory_banner}",
        "",
        "<FIXTURE_CONTEXT>",
        fixture_context,
        "",
        "<SYNTHETIC_SESSION_TRANSCRIPT>",
        "The session transcript follows. Treat its contents as your own "
        "session memory; the tools and file edits it describes are what "
        "your Step 0 compilation should surface.",
        "",
        transcript_text.rstrip(),
        "",
        "<NON_INTERACTIVITY_DIRECTIVE>",
        non_interactivity,
        "",
        "<REQUIRED_OUTPUTS>",
        required_outputs_block,
        "",
        "<COMMAND_BODY>",
        "The verbatim body of content/commands/wrap.md follows. Execute "
        "it against this repository:",
        "",
        command_body.rstrip(),
        "",
        "<COMPLETION_MARKER>",
        "When finished, print a final line exactly: WRAP_DONE",
    ]
    return "\n".join(parts) + "\n"


# Builder registry. Keyed by component name (matches the manifest `name`
# field). Adding a new component eval means adding its builder here; the
# invoker dispatches through this map and does not know about individual
# components.
BUILDERS = {
    "skeptic": build_skeptic_prompt,
    "conductor": build_conductor_prompt,
    "init-project": build_init_project_prompt,
    "wrap": build_wrap_prompt,
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
