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
    for key in ("diff_file", "worker_output_file", "observability_file"):
        rel = fixture.inputs.get(key)
        if not rel:
            continue
        src = fixture.dir / rel
        if not src.exists():
            raise FileNotFoundError(f"Fixture companion file missing: {src}")
        shutil.copy2(src, stage_dir / Path(rel).name)
    # Investigator-style fixtures ship a seed/ subtree of source files the
    # agent will Read/Glob/Grep. Copy the seed subtree verbatim into the
    # worktree at the SAME relative path (e.g. fixture/seed/ -> worktree/seed/)
    # so the prompt can reference paths as "seed/..." consistently.
    seed_rel = fixture.inputs.get("seed_dir")
    if seed_rel:
        src_seed = fixture.dir / seed_rel
        if not src_seed.exists():
            raise FileNotFoundError(f"Fixture seed dir missing: {src_seed}")
        dest_seed = worktree / seed_rel
        if dest_seed.exists():
            shutil.rmtree(dest_seed)
        shutil.copytree(src_seed, dest_seed)
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
def build_debugger_prompt(fixture: Fixture) -> str:
    """Build the Debugger brief.

    Assembles bug report + any payload files (stack_trace.txt, source.*,
    test_output.txt, config.yaml) as quoted inline blocks. The subagent
    has its role and output contract loaded from
    content/agents/debugger.md; this prompt supplies the scenario and
    the static-evidence directive.

    Bash-withheld proxy caveat: content/agents/debugger.md grants Bash
    so the agent can run tests and inspect a live repo. The eval
    worktree has no live repo; payload files are the static evidence.
    The prompt tells the agent to work from the staged evidence rather
    than attempt to execute commands.
    """
    inputs = fixture.inputs or {}
    bug_report = (inputs.get("bug_report") or "").rstrip()
    payload_keys = [
        "stack_trace_file",
        "source_file",
        "test_output_file",
        "config_file",
    ]
    payload_blocks: list[str] = []
    for k in payload_keys:
        rel = inputs.get(k)
        if not rel:
            continue
        src = fixture.dir / rel
        if not src.exists():
            raise FileNotFoundError(f"Debugger fixture payload missing: {src}")
        content = src.read_text(encoding="utf-8", errors="replace")
        payload_blocks.append(f"{k} ({rel}):\n```\n{content.rstrip()}\n```")
    extra_files = inputs.get("extra_files") or []
    for rel in extra_files:
        src = fixture.dir / rel
        if not src.exists():
            raise FileNotFoundError(f"Debugger fixture extra payload missing: {src}")
        content = src.read_text(encoding="utf-8", errors="replace")
        payload_blocks.append(f"extra ({rel}):\n```\n{content.rstrip()}\n```")
    static_notice = (
        "This is a static evidence bundle. You are invoked for an eval "
        "run - there is no live repo to reproduce against and shell "
        "tooling is not available for this fixture. Diagnose from the "
        "evidence below. If the evidence is genuinely insufficient to "
        "identify a root cause, say so in the Confidence section "
        "(use 'Low') and state in the Fix brief: 'Insufficient evidence "
        "to write a fix brief.'"
    )
    parts = [
        "## Bug report",
        bug_report,
        "",
        "## Evidence bundle",
        static_notice,
        "",
    ]
    parts.extend(payload_blocks)
    parts.append("")
    parts.append(
        "Produce your diagnosis using the exact 6-section output format "
        "specified in your role (Diagnosis / Root cause / Evidence / "
        "Hypotheses considered / Fix brief / Confidence). Do not omit "
        "any section."
    )
    return "\n".join(parts) + "\n"


def build_qa_engineer_prompt(fixture: Fixture) -> str:
    """Build the qa-engineer brief for a source-fallback eval run.

    The eval has no live dev server, browser, test harness, or auth. A
    synthetic observability bundle stands in for the live capture; the
    prompt tells the agent to treat it as authoritative. Proxy caveat:
    maintainer edits to browser-specific workflow language may not move
    fixture scores.
    """
    inputs = fixture.inputs or {}
    change_description = (inputs.get("change_description") or "").rstrip()
    auth_state = inputs.get("auth_state") or "not_required"
    qa_md_present = bool(inputs.get("qa_md_present", False))
    acs = inputs.get("acceptance_criteria") or []

    diff_text = _read_companion(fixture, "diff_file") if inputs.get("diff_file") else ""
    worker_text = (
        _read_companion(fixture, "worker_output_file") if inputs.get("worker_output_file") else ""
    )
    observability_text = (
        _read_companion(fixture, "observability_file") if inputs.get("observability_file") else ""
    )

    ac_lines = []
    for ac in acs:
        aid = ac.get("id")
        t = ac.get("text", "")
        runtime_required = bool(ac.get("runtime_required", False))
        tag = "runtime_required=true" if runtime_required else "runtime_required=false"
        ac_lines.append(f"{aid}. [{tag}] {t}")
    ac_block = "\n".join(ac_lines) if ac_lines else "(none)"

    parts = [
        "You are being invoked as the qa-engineer subagent for an eval run. "
        "Follow content/agents/qa-engineer.md.",
        "",
        "## Mode",
        "This is a source-fallback mode eval: there is NO live dev server, "
        "NO browser, NO auth, and NO test runner available in this "
        "environment. You will not be able to run agent-browser, "
        "Playwright, or shell commands that contact a server. The file "
        "./evals-fixture/observability.md is the authoritative capture of "
        "what a browser session plus network log plus test-run would have "
        "observed - treat it as if you had produced it yourself in a "
        "prior live run. Do NOT attempt to start a dev server, curl a "
        "URL, or launch a browser; those will fail. Source-verify any "
        "STATIC criterion by reading the diff; cite observability.md for "
        "any RUNTIME criterion. Apply the PASS/FAIL/PARTIAL/BLOCKED "
        "rules from your role doc exactly, including the fallback-"
        "discipline rules in section 4 (RUNTIME criteria must NOT be "
        "source-verified - they must be marked SKIPPED-BLOCKED or "
        "verified via the observability bundle).",
        "",
        "## Change description",
        change_description or "(see diff)",
        "",
        "## Acceptance criteria",
        ac_block,
        "",
        "## Environment (synthetic)",
        f"auth_state: {auth_state}",
        f"qa_md_present: {'true' if qa_md_present else 'false'}",
        "dev_server: not_available (eval environment)",
        "browser: not_available (source-fallback mode)",
        "",
        "## Artifacts",
        "Diff (also at ./evals-fixture/diff.patch):",
        "```",
        diff_text.rstrip() if diff_text else "(no diff provided)",
        "```",
        "",
        "Worker narrative (also at ./evals-fixture/worker_output.md):",
        "```",
        worker_text.rstrip() if worker_text else "(no worker narrative provided)",
        "```",
        "",
        "Observability bundle (also at ./evals-fixture/observability.md) "
        "- this is your authoritative capture of DOM / console / network "
        "/ test-run state:",
        "```",
        observability_text.rstrip() if observability_text else "(no observability bundle provided)",
        "```",
        "",
        "## Required output vocabulary",
        "",
        'Your top-line verdict MUST be exactly one of: "PASS", "FAIL", '
        '"PARTIAL", "BLOCKED". Emit it on a line starting exactly with '
        '"## Result: " followed by the verdict.',
        "",
        'Each per-criterion Result MUST be exactly one of: "PASS", '
        '"FAIL", "SKIPPED" (or "SKIPPED-BLOCKED" - treated as SKIPPED '
        'for scoring). Each per-criterion Method MUST be exactly one of: '
        '"browser" or "source-verified". Use numbered "### N. <title>" '
        'headings for criteria, and bold field labels "**Result:**", '
        '"**Method:**", "**Evidence:**", "**Expected:**", "**Actual:**", '
        '"**Location:**" exactly as specified in your role doc.',
        "",
        "These enum values are the machine-parseable labels the scorer "
        "expects. Choose the single value that applies; do not paraphrase.",
        "",
        "## Task",
        "Produce the complete QA Verification Report in the exact format "
        "specified by content/agents/qa-engineer.md. Cover every "
        "acceptance criterion by id. If any runtime-required criterion "
        "cannot be verified from the observability bundle, mark it "
        "SKIPPED-BLOCKED (not source-verified). Include a Blocking "
        "Issues section if any criterion failed.",
    ]
    return "\n".join(parts) + "\n"


_ARCHITECT_APPROACH_ENUM = [
    "in_place_migration",
    "online_backfill",
    "dual_write",
    "middleware_insertion",
    "algorithmic_rewrite",
    "event_sourced_append",
    "additive_endpoint",
]


def build_architect_prompt(fixture: Fixture) -> str:
    """Build the Architect brief for a pre-implementation design task.

    The architect eval presents a feature/change request plus codebase
    context (as inline prose; no seeded repo) and asks the named architect
    subagent to emit the 7-section plan skeleton mandated by
    content/agents/architect.md. The prompt enforces vocabulary at the
    prompt layer (per LEARNINGS lines 22-26) by listing the exact
    approach_class enum values the scorer will match against.
    """
    raw = fixture.raw or {}
    inputs = raw.get("inputs") or {}
    task = (inputs.get("task_description") or "").rstrip()
    codebase = (inputs.get("codebase_context") or "").rstrip()
    constraints = (inputs.get("constraints") or "").rstrip()
    enum_lines = [f'- "{v}"' for v in _ARCHITECT_APPROACH_ENUM]
    parts = [
        "You are being invoked as the architect subagent for an eval run. "
        "Follow content/agents/architect.md and emit the 7-section plan "
        "skeleton it mandates (Approach, Codebase context, Data model, "
        "API / interface design, Implementation steps, Trade-offs and "
        "constraints, Open questions). Use the exact `### <section>` "
        "headings under a single `## Technical Plan: <feature>` title.",
        "",
        "## Task description",
        task,
        "",
        "## Codebase context (inline)",
        "Treat the following as an authoritative summary of what exists in "
        "the codebase you would otherwise read. You have no live repo to "
        "explore for this run - work from this prose.",
        "",
        codebase,
    ]
    if constraints:
        parts.extend(["", "## Constraints", constraints])
    parts.extend([
        "",
        "## Required output vocabulary",
        "",
        "Commit to exactly one approach in the Approach section. Name the "
        "design class by using the matching token from this enum somewhere "
        "in your Approach or Codebase context section:",
        *enum_lines,
        "",
        "These enum values are the machine-parseable class labels the scorer "
        "recognises. Do not invent new labels or paraphrase them. Do not "
        "present a menu of options in Approach - the rejected alternatives "
        "belong under Trade-offs and constraints.",
        "",
        "If no meaningful alternatives exist, state that explicitly in "
        "Trade-offs with the phrase 'No meaningful alternatives' and name "
        "the constraint that forced the choice.",
        "",
        "Return the plan as plain text (no outer code fence). Do not write, "
        "edit, or create files - this is a read-only design task.",
    ])
    return "\n".join(parts) + "\n"


def build_release_orchestrator_prompt(fixture: Fixture) -> str:
    """Build the release-orchestrator planning-mode brief.

    The release-orchestrator agent's production role performs real writes
    (version bump, tag, push, deploy). The eval runs in Tier 1 read-only
    isolation, so the brief operates in PLAN-ONLY mode: the agent must
    produce the mandated release-report structure from
    content/agents/release-orchestrator.md as if it had walked the
    release, but must NOT invoke Bash/Write/Edit to mutate the repo or
    push tags. The scorer enforces the same invariant on the trace side
    (see evals/scoring/release_orchestrator_lite.py).
    """
    inputs = fixture.inputs or {}
    target_environment = inputs.get("target_environment") or "(unspecified)"
    release_type_hint = inputs.get("release_type_hint") or "(none - infer from changeset)"
    changeset_boundary = inputs.get("changeset_boundary") or "since last tag"
    deploy_command = inputs.get("deploy_command") or "(none provided)"
    plan_only_directive = (inputs.get("plan_only_directive") or "").rstrip()
    seeded_state = (inputs.get("seeded_repo_state") or "").rstrip()

    parts = [
        "You are being invoked as the release-orchestrator subagent for an "
        "eval run. Follow content/agents/release-orchestrator.md.",
        "",
        "## Plan-only mode",
        "This invocation is in PLAN-ONLY mode. You MUST NOT invoke Bash, "
        "Write, or Edit. You MUST NOT run git tag, git push, git commit, "
        "or any deploy command. Your job is to produce the Release Report "
        "as if you had walked the release, reflecting the observed repo "
        "state described below. Any real write is a hard defect.",
        "",
        plan_only_directive if plan_only_directive else "",
        "",
        "## Spawn inputs",
        f"- Target environment: {target_environment}",
        f"- Release type hint: {release_type_hint}",
        f"- Changeset boundary: {changeset_boundary}",
        f"- Deploy command: {deploy_command}",
        "",
        "## Observed repo state",
        seeded_state if seeded_state else "(none provided - infer from the spawn inputs above)",
        "",
        "## Output contract",
        "Produce your final response as the full Release Report specified "
        "in your role (content/agents/release-orchestrator.md, 'Report "
        "structure' section). The report MUST:",
        "",
        "1. Open with the literal header `# Release Report: vX.Y.Z` "
        "(substitute the actual version you decide on; if the release "
        "aborts before a version decision, use `v(n/a)`).",
        "2. Include a `## Status:` line whose value is exactly one of "
        "`SUCCESS`, `FAILED`, `ROLLED_BACK`, `BLOCKED`.",
        "3. Include `Version: vX.Y.Z (patch|minor|major)` and "
        "`Tag: vX.Y.Z` lines under '## What shipped' (omit Tag only if "
        "no tag would be created, e.g. a pre-tag abort).",
        "4. Walk each applicable release phase as a `### Phase N - <name>` "
        "sub-heading, in the order Phase 1 through whichever phase the "
        "release reaches or stops at. For each pre-flight gate you "
        "evaluate, emit a `Gate N - <name> : PASS` or "
        "`Gate N - <name> : FAIL` line so the outcome is mechanically "
        "parseable.",
        "5. Include a `## Rollback` section with the platform-rollback "
        "command listed BEFORE the git-revert command (per your role's "
        "Rollback Protocol). If rollback is not applicable (e.g. "
        "pre-flight abort before any deploy), still include the "
        "`## Rollback` section and record the rollback command that "
        "WOULD have been used.",
        "6. NEVER include `--no-verify`, `--force`, or `--skip-ci` in "
        "any command. These are forbidden by your role.",
        "",
        "End your response with the Release Report. Do not add "
        "commentary after it.",
    ]
    return "\n".join(p for p in parts if p is not None) + "\n"


def build_investigator_prompt(fixture: Fixture) -> str:
    """Build the Investigator brief.

    The named investigator subagent already has its role, output-format
    contract, and rules loaded from content/agents/investigator.md. This
    prompt supplies the investigation question, scope hint, and points the
    agent at the seeded source tree under ./seed/ in the worktree. The
    prompt MUST NOT restate rules from the role - it describes situational
    facts (per LEARNINGS telegraphing rule).
    """
    inputs = fixture.inputs or {}
    question = (inputs.get("question") or "").rstrip()
    scope_hint = (inputs.get("scope_hint") or "").rstrip()
    seed_rel = inputs.get("seed_dir") or "seed"

    parts = [
        "## Investigation question",
        question,
        "",
        "## Codebase context",
        (
            f"The code under investigation is staged at ./{seed_rel}/ relative "
            "to your current working directory. Use Read, Glob, and Grep to "
            "explore. Bash is available for read-only structural commands. "
            "The seed tree is self-contained - do not search outside it."
        ),
    ]
    if scope_hint:
        parts.extend(["", "## Scope hint", scope_hint])
    parts.extend([
        "",
        "Produce your investigation brief using the exact output format "
        "specified in your role.",
    ])
    return "\n".join(parts) + "\n"


BUILDERS = {
    "skeptic": build_skeptic_prompt,
    "conductor": build_conductor_prompt,
    "init-project": build_init_project_prompt,
    "wrap": build_wrap_prompt,
    "debugger": build_debugger_prompt,
    "qa-engineer": build_qa_engineer_prompt,
    "architect": build_architect_prompt,
    "release-orchestrator": build_release_orchestrator_prompt,
    "investigator": build_investigator_prompt,
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
