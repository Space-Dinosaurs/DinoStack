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


def build_security_auditor_prompt(fixture: Fixture) -> str:
    """Build the security-auditor brief for a Tier 1 eval run.

    The agent's production role grants Read, Glob, Grep, Bash. Tier 1
    isolation does not provide Bash, so the subagent runs effectively
    read-only (the brief acknowledges this explicitly). Code files are
    inlined into the prompt so the auditor can cite file:line even
    without tooling access; the files are also staged under
    ./evals-fixture/code/ for any in-environment Read access the
    subagent does retain.

    Vocabulary enforcement: the prompt lists the exact severity section
    headings the scorer matches against (Critical findings / High
    findings / Medium findings / Informational / OWASP Top 10 coverage)
    - scorer hits these by regex, so paraphrasing ("Critical issues"
    instead of "Critical findings") is a format-gate failure.
    """
    inputs = fixture.inputs or {}
    code_dir_rel = inputs.get("code_dir")
    if not code_dir_rel:
        raise ValueError(
            f"security-auditor fixture {fixture.id} missing inputs.code_dir"
        )
    code_dir = fixture.dir / code_dir_rel
    if not code_dir.exists() or not code_dir.is_dir():
        raise FileNotFoundError(
            f"security-auditor fixture {fixture.id}: code_dir missing at {code_dir}"
        )
    files: list[Path] = []
    for p in sorted(code_dir.rglob("*")):
        if p.is_file():
            files.append(p)
    if not files:
        raise ValueError(
            f"security-auditor fixture {fixture.id}: code_dir {code_dir} contains no files"
        )

    code_blocks: list[str] = []
    for fp in files:
        rel = fp.relative_to(fixture.dir)
        try:
            content = fp.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = fp.read_text(encoding="utf-8", errors="replace")
        numbered = "\n".join(
            f"{i + 1:4d}  {line}" for i, line in enumerate(content.splitlines())
        )
        code_blocks.append(f"### {rel}\n```\n{numbered}\n```")

    security_domain = inputs.get("security_domain") or "(unspecified)"
    prior_mitigations = (inputs.get("prior_mitigations") or "").rstrip()

    static_notice = (
        "This is an eval run. Bash tooling is not available in this "
        "environment - work from the file contents inlined below. Each "
        "file is shown with line numbers in the left column so you can "
        "cite `file:line` accurately without running grep. Do not "
        "attempt to execute shell commands; they will fail."
    )

    parts = [
        "You are being invoked as the security-auditor subagent for an "
        "eval run. Follow content/agents/security-auditor.md.",
        "",
        "## Security domain",
        security_domain,
        "",
        "## Prior mitigations",
        prior_mitigations or "(none declared - assume nothing)",
        "",
        "## Evaluation mode",
        static_notice,
        "",
        "## Code to audit",
    ]
    parts.extend(code_blocks)
    parts.extend([
        "",
        "## Required output format",
        "",
        "Produce the audit using the exact section structure mandated by "
        "your role. The scorer parses these section headings by regex "
        "and will treat paraphrased headings as a format-gate failure. "
        "Use these EXACT headings (case matters on the words, level 2 "
        "for the title, level 3 for the sub-sections):",
        "",
        "- `## Security Audit: <component/feature>`",
        "- `### Threat model`",
        "- `### Critical findings`",
        "- `### High findings`",
        "- `### Medium findings`",
        "- `### Informational`",
        "- `### Positive controls noted`",
        "- `### OWASP Top 10 coverage`",
        "- `### Dependency scan`",
        "",
        "For each finding in a severity section, emit a bullet that "
        "includes: the vulnerability name, a CWE-NN identifier where "
        "one applies, a `file.ext:line` citation, the impact, and a "
        "remediation. A severity section with no findings must contain "
        "the literal line `None`.",
        "",
        "In the `### OWASP Top 10 coverage` section, list each applicable "
        "OWASP category by its short code (e.g. `A01`, `A03`, `A07`) "
        "with a one-line status - the scorer matches these short codes "
        "directly.",
        "",
        "Do not write, edit, or create files. This is read-only.",
    ])
    return "\n".join(parts) + "\n"


def build_memory_update_prompt(fixture: Fixture) -> str:
    """Build the command-mode prompt for a /memory-update eval run.

    /memory-update in production is a thin main-agent dispatcher that
    spawns a background `general-purpose` Worker to verify and write a
    single date-stamped bullet to `.agentic/memory/MEMORY.md`. The eval
    cannot reproduce the background-spawn channel under a redirected
    HOME, so this prompt collapses the main-agent dispatcher and the
    Worker body into a single inline session. The scorer measures the
    one side-effect: the resulting MEMORY.md file. This proxy is
    documented in the component README.

    Fail-fast: raises if the seeded AGENTS.md lacks the
    'agentic-engineering: opt-in' marker (Activation preflight would
    no-op and the run would silently score 0) or if the fixture does
    not supply inputs.decision_context (the $ARGUMENTS payload).
    """
    inputs = fixture.inputs or {}
    expected = (fixture.raw or {}).get("expected_outputs") or {}

    repo_dir_rel = inputs.get("repo_dir")
    if not repo_dir_rel:
        raise ValueError(f"memory-update fixture {fixture.id} missing inputs.repo_dir")
    agents_md_path = fixture.dir / repo_dir_rel / "AGENTS.md"
    if not agents_md_path.exists():
        raise FileNotFoundError(
            f"memory-update fixture {fixture.id}: seeded AGENTS.md missing at {agents_md_path}"
        )
    agents_md_text = agents_md_path.read_text(encoding="utf-8")
    if "agentic-engineering: opt-in" not in agents_md_text:
        raise ValueError(
            f"memory-update fixture {fixture.id}: seeded AGENTS.md at "
            f"{agents_md_path} does not contain 'agentic-engineering: opt-in'. "
            "The Activation preflight will no-op without that marker; "
            "refusing to run to prevent silent zero-scoring."
        )

    decision_context = (inputs.get("decision_context") or "").rstrip()
    if not decision_context:
        raise ValueError(
            f"memory-update fixture {fixture.id}: inputs.decision_context is "
            "required (the $ARGUMENTS payload the command receives)."
        )

    command_path = _REPO_ROOT_P / "content" / "commands" / "memory-update.md"
    if not command_path.exists():
        raise FileNotFoundError(f"memory-update command body missing: {command_path}")
    command_body = command_path.read_text(encoding="utf-8")

    auto_memory_banner = (
        "This is a persistent auto memory directory at ./.agentic/memory/. "
        "You can use it for notes that persist across sessions."
    )

    fixture_context = (
        "You are running the /memory-update command against the repository "
        "rooted at the current working directory. Your $HOME is redirected "
        "for this session; a project-level config lives at "
        "$HOME/.claude/agentic-engineering.json and may already be seeded."
    )

    non_interactivity = (
        "Do not prompt the user. The command body below is nominally a main-"
        "agent dispatcher that spawns a background general-purpose Worker. "
        "Under this eval, execute the Worker brief INLINE in the current "
        "session instead of spawning a subagent: run Part 1 (relevance "
        "filter), Part 2 (verify claims against the seeded repo files "
        "using Read / Grep as needed), Part 3 (draft), and Part 4 (write "
        "to disk via the Write or Edit tool directly). Do not call the "
        "Task tool. Do not run `git` or attempt to commit. The canonical "
        "MEMORY.md path for this session is "
        "`.agentic/memory/MEMORY.md` relative to the current working "
        "directory; create the parent directory if it does not exist."
    )

    must_exist = list(expected.get("must_exist") or [])
    must_not_exist = list(expected.get("must_not_exist") or [])

    required_outputs_lines: list[str] = []
    if must_exist:
        required_outputs_lines.append("The following files must exist after you finish:")
        for p in must_exist:
            required_outputs_lines.append(f"- {p}")
        required_outputs_lines.append("")
    if must_not_exist:
        required_outputs_lines.append(
            "The following files MUST NOT be present when you finish:"
        )
        for p in must_not_exist:
            required_outputs_lines.append(f"- {p}")
        required_outputs_lines.append("")
    if not required_outputs_lines:
        required_outputs_lines.append(
            "No explicit required-output paths for this scenario - follow "
            "the relevance filter in the command body and write only what "
            "it prescribes."
        )
    required_outputs_block = "\n".join(required_outputs_lines).rstrip()

    parts = [
        f"<SYNTHETIC_AUTO_MEMORY_BANNER>\n{auto_memory_banner}",
        "",
        "<FIXTURE_CONTEXT>",
        fixture_context,
        "",
        "<DECISION_CONTEXT>",
        "The decision context below is the $ARGUMENTS payload the command "
        "receives. Substitute it wherever the command body references "
        "$ARGUMENTS.",
        "",
        decision_context,
        "",
        "<NON_INTERACTIVITY_DIRECTIVE>",
        non_interactivity,
        "",
        "<REQUIRED_OUTPUTS>",
        required_outputs_block,
        "",
        "<COMMAND_BODY>",
        "The verbatim body of content/commands/memory-update.md follows. "
        "Execute it against this repository under the inline-execution "
        "directive above:",
        "",
        command_body.rstrip(),
        "",
        "<COMPLETION_MARKER>",
        "When finished, print a final line exactly: MEMORY_UPDATE_DONE",
    ]
    return "\n".join(parts) + "\n"


def build_prune_harness_prompt(fixture: Fixture) -> str:
    """Build the command-mode prompt for a /prune-harness eval run.

    The eval measures Step 1 (analyst spawn) + Step 2 (proposal artifact).
    Step 0 git-sync is explicitly skipped (the isolated worktree has no
    remote and a divergence check would block). Step 4 dispatch to
    /update-agentic-engineering is OUT OF SCOPE.

    Because the command body spawns a Worker subagent in production, this
    eval instructs the top-level session NOT to spawn a Task subagent.
    Instead it writes the proposal inline. This is an intentional proxy
    (documented in the component README): we measure the signal-checklist
    walk + the proposal artifact, not the subagent-spawn plumbing.

    Fail-fast: the fixture's seeded AGENTS.md must carry the literal
    "agentic-engineering: opt-in" line. Without it, the /prune-harness
    Activation preflight no-ops and the run produces nothing.
    """
    inputs = fixture.inputs or {}
    expected = (fixture.raw or {}).get("expected") or {}

    repo_dir_rel = inputs.get("repo_dir")
    if not repo_dir_rel:
        raise ValueError(f"prune-harness fixture {fixture.id} missing inputs.repo_dir")
    agents_md_path = fixture.dir / repo_dir_rel / "AGENTS.md"
    if not agents_md_path.exists():
        raise FileNotFoundError(
            f"prune-harness fixture {fixture.id}: seeded AGENTS.md missing at {agents_md_path}"
        )
    agents_md_text = agents_md_path.read_text(encoding="utf-8")
    if "agentic-engineering: opt-in" not in agents_md_text:
        raise ValueError(
            f"prune-harness fixture {fixture.id}: seeded AGENTS.md at {agents_md_path} "
            "does not contain the literal line 'agentic-engineering: opt-in'. "
            "The /prune-harness Activation preflight will no-op without that "
            "marker; refusing to run to prevent silent zero-scoring."
        )

    proposal_date = inputs.get("proposal_date")
    if not proposal_date:
        raise ValueError(
            f"prune-harness fixture {fixture.id} missing inputs.proposal_date"
        )
    proposal_path = expected.get("proposal_path") or (
        f"docs/planning/harness-pruning-{proposal_date}.md"
    )

    command_path = _REPO_ROOT_P / "content" / "commands" / "prune-harness.md"
    if not command_path.exists():
        raise FileNotFoundError(f"prune-harness command body missing: {command_path}")
    command_body = command_path.read_text(encoding="utf-8")

    auto_memory_banner = (
        "This is a persistent auto memory directory at ./.agentic/memory/. "
        "You can use it for notes that persist across sessions."
    )

    fixture_context = (
        "You are running the /prune-harness command against the synthetic "
        "methodology corpus at the current working directory. The "
        "content/ tree below is deliberately small for eval reproducibility; "
        "treat it as the full corpus to analyze. Your $HOME is redirected "
        "for this session. Step 0 (git-sync) of the command body is "
        "SKIPPED for this run."
    )

    non_interactivity = (
        "Do not prompt the user at any point. Skip Step 0 (git-sync "
        "preflight) entirely - there is no remote to fetch. Do NOT spawn "
        "a Task subagent for Step 1; instead, apply the Signal Checklist "
        "yourself and write the proposal document inline. Stop immediately "
        "after writing the proposal. Step 2 (user approval) and Step 4 "
        "(dispatch to /update-agentic-engineering) are OUT OF SCOPE for "
        "this eval - do not present, do not approve, do not dispatch."
    )

    required_outputs_lines = [
        f"Write the proposal document to exactly this path: {proposal_path}",
        "",
        "The proposal MUST contain these four section headings verbatim:",
        "- `# Harness Pruning Proposal - YYYY-MM-DD` (top-level title; "
        f"substitute {proposal_date})",
        "- `## Signal summary`",
        "- `## Deletion candidates`",
        "- `## Recommended action sequence`",
        "",
        "For each candidate under `## Deletion candidates`, emit a `### "
        "<candidate title>` sub-heading followed by these fields (each on "
        "its own line), in this order:",
        "- `Confidence: HIGH | MEDIUM | LOW`  (emit exactly one of these "
        "three tokens; HIGH for Signal 1 firings, MEDIUM for Signals 2/3/5/7 "
        "when evidence is unambiguous, LOW for Signal 6 complexity concerns)",
        "- `File: <content-relative path>`  (e.g. "
        "`File: content/rules/agent-methodology.md`)",
        "- `Signal(s): <which numbered signals fired>`",
        "- `Rationale: <one-paragraph evidence>`",
        "- `Risk if wrong: <what breaks if this deletion is incorrect>`",
        "- `Suggested action: delete | consolidate into X | simplify`",
        "",
        "If a signal is skipped (e.g. Signal 4 when no findings.md exists "
        "at either `.agentic/findings.md` or `.claude/findings.md`), state "
        "the skip in `## Signal summary` using the phrase `Signal N "
        "skipped:` followed by the rationale. The scorer extracts skip "
        "numbers from that exact phrasing.",
        "",
        "If no candidates are found after applying all applicable signals, "
        "the proposal still writes and states this explicitly with "
        "rationale under `## Deletion candidates` - an empty proposal is "
        "a valid output, but silently returning nothing is not.",
        "",
        "Do NOT modify any file under `content/`. The command is analysis "
        "only. Any write outside the single proposal path is a forbidden "
        "write and is scored as such.",
    ]
    required_outputs_block = "\n".join(required_outputs_lines)

    parts = [
        f"<SYNTHETIC_AUTO_MEMORY_BANNER>\n{auto_memory_banner}",
        "",
        "<FIXTURE_CONTEXT>",
        fixture_context,
        "",
        "<NON_INTERACTIVITY_DIRECTIVE>",
        non_interactivity,
        "",
        "<REQUIRED_OUTPUTS>",
        required_outputs_block,
        "",
        "<COMMAND_BODY>",
        "The verbatim body of content/commands/prune-harness.md follows. "
        "Execute it against this repository, subject to the Step 0 skip "
        "and no-Task-spawn directives above:",
        "",
        command_body.rstrip(),
        "",
        "<COMPLETION_MARKER>",
        "When finished, print a final line exactly: PRUNE_HARNESS_DONE",
    ]
    return "\n".join(parts) + "\n"


def build_implement_ticket_prompt(fixture: Fixture) -> str:
    """Build the command-mode prompt for an /implement-ticket eval run.

    `/implement-ticket` is a slash command and is not discoverable under a
    redirected HOME (see evals/LEARNINGS.md "Slash commands are not
    discoverable under redirected HOME"). We inline the verbatim body of
    content/commands/implement-ticket.md into the prompt, wrapped by:

      - a synthetic auto-memory banner (the command's Phase 2 reads it)
      - a FIXTURE_CONTEXT preface declaring plan-only mode, TRACKER=none,
        and no gh auth
      - a SYNTHETIC_TICKET block standing in for Phase 1's tracker fetch
      - a NON_INTERACTIVITY_DIRECTIVE enumerating Phases 4/5/6/7/8/12 to
        execute, Phases 9/10/11 to skip, and a git pre-setup sequence to
        bootstrap the seeded repo
      - a PHASE_SCOPE block restating which phases are in-scope
      - a VOCABULARY block enumerating loop-state enum values (status,
        termination_reason, phase) so the scorer can match exact strings
      - a REQUIRED_OUTPUTS block enumerating the artifacts the scorer
        will inspect
      - the verbatim COMMAND_BODY
      - a COMPLETION_MARKER "IMPLEMENT_TICKET_DONE"

    Fail-fast: raise if the seeded AGENTS.md does not carry the opt-in
    marker (activation preflight will no-op). Raise if the seeded
    AGENTS.md contains a `## Tracker` or `## Linear` section - the eval
    only supports TRACKER=none and a seeded tracker would make Phase 1
    attempt an MCP call that cannot succeed in the isolated environment.
    """
    inputs = fixture.inputs or {}
    expected = (fixture.raw or {}).get("expected_outputs") or {}

    repo_dir_rel = inputs.get("repo_dir")
    if not repo_dir_rel:
        raise ValueError(
            f"implement-ticket fixture {fixture.id} missing inputs.repo_dir"
        )
    agents_md_path = fixture.dir / repo_dir_rel / "AGENTS.md"
    if not agents_md_path.exists():
        raise FileNotFoundError(
            f"implement-ticket fixture {fixture.id}: seeded AGENTS.md missing "
            f"at {agents_md_path}"
        )
    agents_md_text = agents_md_path.read_text(encoding="utf-8")
    if "agentic-engineering: opt-in" not in agents_md_text:
        raise ValueError(
            f"implement-ticket fixture {fixture.id}: seeded AGENTS.md does not "
            "contain the literal line 'agentic-engineering: opt-in'. The "
            "command's Activation preflight will no-op without that marker."
        )
    for banned_section in ("\n## Tracker", "\n## Linear"):
        if banned_section in agents_md_text:
            raise ValueError(
                f"implement-ticket fixture {fixture.id}: seeded AGENTS.md "
                f"contains a '{banned_section.strip()}' section. This eval only "
                "supports TRACKER=none. Remove the section from the fixture or "
                "promote this fixture to a tracker-aware eval variant."
            )

    command_path = _REPO_ROOT_P / "content" / "commands" / "implement-ticket.md"
    if not command_path.exists():
        raise FileNotFoundError(
            f"implement-ticket command body missing: {command_path}"
        )
    command_body = command_path.read_text(encoding="utf-8")

    auto_memory_banner = (
        "This is a persistent auto memory directory at ./.agentic/memory/. "
        "You can use it for notes that persist across sessions."
    )

    base_branch = inputs.get("base_branch") or "main"
    ticket_description = (inputs.get("ticket_description") or "").rstrip()
    acs = inputs.get("acceptance_criteria") or []
    ac_lines = "\n".join(f"- {ac}" for ac in acs) if acs else "- (none stated)"

    fixture_context = (
        "You are running the /implement-ticket command against the "
        "repository rooted at the current working directory. Your $HOME is "
        "redirected for this session and there is no live Linear/Jira "
        "MCP, no GitHub CLI authentication, and no remote configured. "
        "TRACKER is 'none'. Operate in local-artifact mode only - no "
        "network calls, no PR creation, no tracker updates."
    )

    synthetic_ticket = (
        "## Ticket description\n"
        f"{ticket_description}\n"
        "\n"
        "## Acceptance criteria\n"
        f"{ac_lines}"
    )

    non_interactivity = (
        "Do not prompt the user at any point. Where the command body "
        "instructs you to confirm or ask (Phase 1 TRACKER=none 'describe "
        "what you want to implement' prompt, BASE_BRANCH resolution "
        "prompts, resume prompts, etc.), proceed with the auto-discovered "
        "defaults. Use the SYNTHETIC_TICKET above as the Phase 1 ticket "
        "content. Use BASE_BRANCH=" + base_branch + ". Never block waiting "
        "for input.\n\n"
        "PRE-SETUP (run before any Phase): the seeded repo is not yet a "
        "git repo. Run these commands once at the start:\n"
        "  git init -q\n"
        "  git add -A\n"
        "  git -c user.email=eval@local -c user.name=eval commit -q -m 'fixture seed'\n"
        "  git branch -M " + base_branch + "\n"
        "\n"
        "PHASE EXECUTION:\n"
        "- Execute Phase 2 (read the codebase; abbreviated is fine - no "
        "  live investigator spawn needed).\n"
        "- Execute Phase 3 (architecture plan); the architect can be "
        "  inlined as a planning pass rather than a separate Task spawn.\n"
        "- Execute Phase 4 (create branch from " + base_branch + ").\n"
        "- Execute Phase 5 (implement the ticket as a single unit; no "
        "  fan-out; no worktrees).\n"
        "- Execute Phase 6 (Skeptic loop); inline Skeptic review is "
        "  acceptable. Write .agentic/loop-state.json at loop init and at "
        "  each state transition per the VOCABULARY below.\n"
        "- Execute Phase 7 (quality gate); run the AGENTS.md QUALITY_CMD "
        "  if present. On failure, the one-engineer-pass rule applies.\n"
        "- Execute Phase 8 (commit only; DO NOT run `git push`). Stage "
        "  specific files (no `git add -A` / `git add .`). The commit "
        "  message must include the substrings listed under "
        "  REQUIRED_OUTPUTS so the scorer can confirm the change narrative.\n"
        "- SKIP Phase 9 (gh pr create). There is no remote and no gh "
        "  authentication; attempting this will fail and waste turns.\n"
        "- SKIP Phase 10 (CI Test URL polling). No CI is configured.\n"
        "- SKIP Phase 11 (tracker post). TRACKER=none.\n"
        "- Execute Phase 12 (loop-state cleanup): set status to "
        "  'complete' on .agentic/loop-state.json (atomic write) as the "
        "  final act."
    )

    phase_scope = (
        "In-scope phases (execute): 2, 3, 4, 5, 6, 7, 8 (commit only), 12.\n"
        "Out-of-scope phases (skip entirely): 9, 10, 11."
    )

    vocabulary = (
        ".agentic/loop-state.json must be a JSON object with these fields:\n"
        "- `status`: exactly one of `\"active\"`, `\"interrupted\"`, "
        "`\"complete\"`, `\"stalled\"`.\n"
        "- `loop_state.phase`: exactly one of `\"skeptic\"` or `\"qa\"`.\n"
        "- `loop_state.termination_reason`: exactly one of `\"clean\"`, "
        "`\"cap_reached\"`, `\"convergence_failure\"`, `\"blocked\"`, or "
        "`null`.\n"
        "These are the machine-parseable labels the scorer matches. Do "
        "not paraphrase them or invent new values."
    )

    branch_prefix = expected.get("branch_prefix") or ""
    must_touch = list(expected.get("must_touch_any_of") or [])
    commit_must_contain = list(expected.get("commit_message_must_contain") or [])
    max_loc = expected.get("max_loc")
    must_not_exist = list(expected.get("must_not_exist") or [])

    req_lines: list[str] = []
    if branch_prefix:
        req_lines.append(
            f"- The working branch name must start with `{branch_prefix}` "
            f"and must not equal the base branch `{base_branch}`."
        )
    if must_touch:
        req_lines.append("- The diff from the base must touch at least one of:")
        for p in must_touch:
            req_lines.append(f"    - `{p}`")
    if commit_must_contain:
        req_lines.append(
            "- The HEAD commit message (Phase 8) must contain each of these substrings:"
        )
        for s in commit_must_contain:
            req_lines.append(f"    - `{s}`")
    if max_loc:
        req_lines.append(
            f"- The total diff (additions + deletions) should stay <= {max_loc} "
            "lines of code. Avoid refactoring out-of-scope modules."
        )
    if must_not_exist:
        req_lines.append("- The following files MUST NOT be created:")
        for p in must_not_exist:
            req_lines.append(f"    - `{p}`")
    req_lines.append(
        "- `.agentic/loop-state.json` must be well-formed per VOCABULARY above."
    )
    required_outputs_block = "\n".join(req_lines).rstrip()

    parts = [
        f"<SYNTHETIC_AUTO_MEMORY_BANNER>\n{auto_memory_banner}",
        "",
        "<FIXTURE_CONTEXT>",
        fixture_context,
        "",
        "<SYNTHETIC_TICKET>",
        synthetic_ticket,
        "",
        "<NON_INTERACTIVITY_DIRECTIVE>",
        non_interactivity,
        "",
        "<PHASE_SCOPE>",
        phase_scope,
        "",
        "<VOCABULARY>",
        vocabulary,
        "",
        "<REQUIRED_OUTPUTS>",
        required_outputs_block,
        "",
        "<COMMAND_BODY>",
        "The verbatim body of content/commands/implement-ticket.md follows. "
        "Execute the in-scope phases against this repository:",
        "",
        command_body.rstrip(),
        "",
        "<COMPLETION_MARKER>",
        "When finished, print a final line exactly: IMPLEMENT_TICKET_DONE",
    ]
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
    "security-auditor": build_security_auditor_prompt,
    "memory-update": build_memory_update_prompt,
    "implement-ticket": build_implement_ticket_prompt,
    "prune-harness": build_prune_harness_prompt,
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
