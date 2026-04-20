"""
Purpose: Load and validate component manifests and fixtures from disk,
         computing content and fixture hashes used as TSV keys.

Public API: load_component(name: str) -> ComponentManifest,
            load_fixtures(manifest: ComponentManifest) -> list[Fixture],
            load_fixture(manifest: ComponentManifest, fixture_id: str) -> Fixture,
            list_components() -> list[str],
            compute_component_content_hash(manifest: ComponentManifest) -> str,
            compute_fixture_hash(fixture_path: pathlib.Path) -> str,
            current_protocol_sha(manifest: ComponentManifest) -> str | None,
            ComponentManifest, Fixture dataclasses.

Upstream deps: pyyaml, stdlib hashlib/pathlib/dataclasses, evals.runner.logging.

Downstream consumers: evals.runner.cli, evals.runner.aggregator,
                      evals.runner.invoker, evals.runner.prompt.

Failure modes: raises FileNotFoundError if a manifest or fixture file is missing;
               raises ValueError on schema violations. Hash functions read files
               into memory; fine for text fixtures, not streamed.

Performance: standard; O(total fixture bytes) for hash computation.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_COMPONENTS_DIR = _REPO_ROOT / "evals" / "components"


@dataclass
class ComponentManifest:
    name: str
    tier: int
    content_glob: list[str]
    scoring_module: str
    fixture_dir: str
    n_runs: int
    parallelism: str
    timeout_seconds: int
    invoke: dict
    path: Path

    @property
    def fixture_dir_abs(self) -> Path:
        return _REPO_ROOT / self.fixture_dir


@dataclass
class Fixture:
    id: str
    description: str
    component: str
    protocol_sha: str
    inputs: dict
    expected_findings: dict
    expected_signoff_granted: bool
    clean_allowed: bool
    path: Path
    raw: dict = field(default_factory=dict)

    @property
    def dir(self) -> Path:
        return self.path.parent


def list_components() -> list[str]:
    if not _COMPONENTS_DIR.exists():
        return []
    return sorted(p.stem for p in _COMPONENTS_DIR.glob("*.yaml"))


def load_component(name: str) -> ComponentManifest:
    path = _COMPONENTS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No component manifest at {path}")
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    required = {
        "name",
        "tier",
        "content_glob",
        "scoring_module",
        "fixture_dir",
        "n_runs",
        "parallelism",
        "timeout_seconds",
        "invoke",
    }
    missing = required - set(data)
    if missing:
        raise ValueError(f"Component {name} manifest missing keys: {sorted(missing)}")
    if data["parallelism"] not in ("serial", "parallel"):
        raise ValueError(f"parallelism must be 'serial' or 'parallel', got {data['parallelism']}")
    invoke_section = data.get("invoke") or {}
    if not isinstance(invoke_section, dict):
        raise ValueError(f"Component {name} manifest: invoke must be a mapping")
    mode = invoke_section.get("mode") or "agent"
    if mode not in ("agent", "command"):
        raise ValueError(
            f"Component {name} manifest: invoke.mode must be 'agent' or 'command', got {mode!r}"
        )
    if mode == "agent" and not invoke_section.get("agent_name"):
        raise ValueError(
            f"Component {name} manifest must set invoke.agent_name for invoke.mode='agent' "
            "(the named subagent to spawn). This is required so the runner measures the "
            "actual named agent rather than a raw top-level Claude session."
        )
    if mode == "command" and not invoke_section.get("command_file"):
        raise ValueError(
            f"Component {name} manifest: invoke.mode='command' requires invoke.command_file "
            "(repo-relative path to the command markdown whose body is inlined into the prompt)."
        )
    return ComponentManifest(
        name=data["name"],
        tier=int(data["tier"]),
        content_glob=list(data["content_glob"]),
        scoring_module=data["scoring_module"],
        fixture_dir=data["fixture_dir"],
        n_runs=int(data["n_runs"]),
        parallelism=data["parallelism"],
        timeout_seconds=int(data["timeout_seconds"]),
        invoke=dict(data["invoke"]),
        path=path,
    )


# Per-component fixture validators. A fixture's shape depends on what the
# component's scoring module expects; validation is dispatched by the
# fixture's own `component` field. Skeptic fixtures carry expected_findings
# and diff/worker_output companions; conductor fixtures carry scenario,
# observed_state, and expected_decision inline.

_CONDUCTOR_DECISION_CLASSES = {
    "spawn_agent",
    "re_enter_loop",
    "escalate_cap_reached",
    "escalate_convergence_failure",
    "escalate_blocked",
    "tight_fix_path",
    "proceed_to_next_phase",
    "terminate_clean",
    "trivial_direct_edit",
}

_CONDUCTOR_NEXT_AGENTS = {
    "engineer",
    "skeptic",
    "qa-engineer",
    "architect",
    "investigator",
    "debugger",
    "security-auditor",
    "orchestration-planner",
    "release-orchestrator",
    "dependency-auditor",
    "perf-analyst",
}

_CONDUCTOR_LOOP_ACTIONS = {"re_enter", "exit_clean", "exit_stalled"}
_CONDUCTOR_COST_CLASSES = {"critical", "high", "medium", "low"}


def _validate_skeptic_fixture(data: dict, path: Path) -> None:
    required = {"id", "description", "component", "protocol_sha", "inputs", "expected_findings"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"Fixture at {path} missing keys: {sorted(missing)}")


def _validate_conductor_fixture(data: dict, path: Path) -> None:
    required = {
        "id",
        "component",
        "protocol_sha",
        "scenario",
        "observed_state",
        "inputs",
        "expected_decision",
    }
    missing = required - set(data)
    if missing:
        raise ValueError(f"Conductor fixture at {path} missing keys: {sorted(missing)}")

    observed = data.get("observed_state") or {}
    if not isinstance(observed, dict):
        raise ValueError(f"Conductor fixture at {path}: observed_state must be a mapping")
    obs_required = {"phase", "iteration", "max_iterations"}
    obs_missing = obs_required - set(observed)
    if obs_missing:
        raise ValueError(
            f"Conductor fixture at {path}: observed_state missing keys: {sorted(obs_missing)}"
        )

    expected = data.get("expected_decision") or {}
    if not isinstance(expected, dict):
        raise ValueError(f"Conductor fixture at {path}: expected_decision must be a mapping")
    exp_required = {"decision_class", "cost_class", "rationale_keywords", "must_not_select"}
    exp_missing = exp_required - set(expected)
    if exp_missing:
        raise ValueError(
            f"Conductor fixture at {path}: expected_decision missing keys: {sorted(exp_missing)}"
        )

    dc = expected.get("decision_class")
    if dc not in _CONDUCTOR_DECISION_CLASSES:
        raise ValueError(
            f"Conductor fixture at {path}: decision_class '{dc}' not in "
            f"{sorted(_CONDUCTOR_DECISION_CLASSES)}"
        )
    na = expected.get("next_agent")
    if na is not None and na not in _CONDUCTOR_NEXT_AGENTS:
        raise ValueError(
            f"Conductor fixture at {path}: next_agent '{na}' not in "
            f"{sorted(_CONDUCTOR_NEXT_AGENTS)} (null is also allowed)"
        )
    la = expected.get("loop_action")
    if la is not None and la not in _CONDUCTOR_LOOP_ACTIONS:
        raise ValueError(
            f"Conductor fixture at {path}: loop_action '{la}' not in "
            f"{sorted(_CONDUCTOR_LOOP_ACTIONS)} (null is also allowed)"
        )
    cc = expected.get("cost_class")
    if cc not in _CONDUCTOR_COST_CLASSES:
        raise ValueError(
            f"Conductor fixture at {path}: cost_class '{cc}' not in "
            f"{sorted(_CONDUCTOR_COST_CLASSES)}"
        )
    mns = expected.get("must_not_select")
    if not isinstance(mns, list):
        raise ValueError(f"Conductor fixture at {path}: must_not_select must be a list")
    rk = expected.get("rationale_keywords")
    if not isinstance(rk, list):
        raise ValueError(f"Conductor fixture at {path}: rationale_keywords must be a list")


def _validate_init_project_fixture(data: dict, path: Path) -> None:
    required = {"id", "component", "protocol_sha", "inputs", "expected_outputs"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"init-project fixture at {path} missing keys: {sorted(missing)}")

    inputs = data.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError(f"init-project fixture at {path}: inputs must be a mapping")
    if "repo_dir" not in inputs:
        raise ValueError(
            f"init-project fixture at {path}: inputs.repo_dir is required "
            "(relative path to the seeded repo subtree under the fixture dir)"
        )

    expected = data.get("expected_outputs") or {}
    if not isinstance(expected, dict):
        raise ValueError(f"init-project fixture at {path}: expected_outputs must be a mapping")
    for key in ("must_exist", "must_not_exist", "agents_md_required_sections", "gitignore_required_lines"):
        val = expected.get(key)
        if val is not None and not isinstance(val, list):
            raise ValueError(
                f"init-project fixture at {path}: expected_outputs.{key} must be a list"
            )
    cond = expected.get("must_exist_conditional")
    if cond is not None and not isinstance(cond, dict):
        raise ValueError(
            f"init-project fixture at {path}: expected_outputs.must_exist_conditional must be a mapping"
        )
    signals = expected.get("expected_signals")
    if signals is not None and not isinstance(signals, list):
        raise ValueError(
            f"init-project fixture at {path}: expected_outputs.expected_signals must be a list"
        )
    max_lines = expected.get("agents_md_max_lines")
    if max_lines is not None and not isinstance(max_lines, int):
        raise ValueError(
            f"init-project fixture at {path}: expected_outputs.agents_md_max_lines must be an int"
        )


def _validate_wrap_fixture(data: dict, path: Path) -> None:
    required = {"id", "component", "protocol_sha", "inputs", "expected_outputs"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"wrap fixture at {path} missing keys: {sorted(missing)}")
    inputs = data.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError(f"wrap fixture at {path}: inputs must be a mapping")
    if "repo_dir" not in inputs:
        raise ValueError(f"wrap fixture at {path}: inputs.repo_dir is required")
    expected = data.get("expected_outputs") or {}
    if not isinstance(expected, dict):
        raise ValueError(f"wrap fixture at {path}: expected_outputs must be a mapping")
    route = expected.get("route_expected")
    if route not in ("zero-substance", "light", "standard"):
        raise ValueError(
            f"wrap fixture at {path}: route_expected must be one of "
            "'zero-substance', 'light', 'standard'"
        )


_MEMORY_UPDATE_SHAPES = {"new", "update", "noop"}


def _validate_memory_update_fixture(data: dict, path: Path) -> None:
    required = {"id", "component", "protocol_sha", "inputs", "expected_outputs"}
    missing = required - set(data)
    if missing:
        raise ValueError(
            f"memory-update fixture at {path} missing keys: {sorted(missing)}"
        )
    inputs = data.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError(
            f"memory-update fixture at {path}: inputs must be a mapping"
        )
    if "repo_dir" not in inputs:
        raise ValueError(
            f"memory-update fixture at {path}: inputs.repo_dir is required"
        )
    if not inputs.get("decision_context"):
        raise ValueError(
            f"memory-update fixture at {path}: inputs.decision_context is "
            "required (the $ARGUMENTS payload the command receives)"
        )
    expected = data.get("expected_outputs") or {}
    if not isinstance(expected, dict):
        raise ValueError(
            f"memory-update fixture at {path}: expected_outputs must be a mapping"
        )
    shape = expected.get("expected_entry_shape")
    if shape is not None and shape not in _MEMORY_UPDATE_SHAPES:
        raise ValueError(
            f"memory-update fixture at {path}: expected_entry_shape must be "
            f"one of {sorted(_MEMORY_UPDATE_SHAPES)} or null"
        )
    for key in ("must_exist", "must_not_exist", "required_substrings", "forbidden_substrings"):
        val = expected.get(key)
        if val is not None and not isinstance(val, list):
            raise ValueError(
                f"memory-update fixture at {path}: expected_outputs.{key} must be a list"
            )


def _validate_debugger_fixture(data: dict, path: Path) -> None:
    required = {"id", "component", "protocol_sha", "inputs", "expected_confidence"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"debugger fixture at {path} missing keys: {sorted(missing)}")
    ec = data.get("expected_confidence")
    if ec not in ("High", "Medium", "Low"):
        raise ValueError(
            f"debugger fixture at {path}: expected_confidence must be one of "
            "'High', 'Medium', 'Low'"
        )
    hint = data.get("root_cause_location_hint", "code")
    if hint not in ("code", "config"):
        raise ValueError(
            f"debugger fixture at {path}: root_cause_location_hint must be "
            "'code' or 'config'"
        )
    for key in (
        "diagnosis_keywords",
        "fix_brief_must_mention",
        "root_cause_negative_paths",
    ):
        val = data.get(key)
        if val is not None and not isinstance(val, list):
            raise ValueError(
                f"debugger fixture at {path}: {key} must be a list"
            )
    mh = data.get("min_hypotheses")
    if mh is not None and not isinstance(mh, int):
        raise ValueError(
            f"debugger fixture at {path}: min_hypotheses must be an int"
        )
    inputs = data.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError(f"debugger fixture at {path}: inputs must be a mapping")
    if "bug_report" not in inputs:
        raise ValueError(
            f"debugger fixture at {path}: inputs.bug_report is required "
            "(free-text summary of the failure)"
        )


def _validate_qa_engineer_fixture(data: dict, path: Path) -> None:
    required = {"id", "component", "protocol_sha", "inputs", "expected"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"qa-engineer fixture at {path} missing keys: {sorted(missing)}")
    inputs = data.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError(f"qa-engineer fixture at {path}: inputs must be a mapping")
    acs = inputs.get("acceptance_criteria")
    if not isinstance(acs, list) or not acs:
        raise ValueError(
            f"qa-engineer fixture at {path}: inputs.acceptance_criteria must be a non-empty list"
        )
    for ac in acs:
        if not isinstance(ac, dict) or "id" not in ac or "text" not in ac:
            raise ValueError(
                f"qa-engineer fixture at {path}: each acceptance_criteria entry must have id and text"
            )
    expected = data.get("expected") or {}
    if not isinstance(expected, dict):
        raise ValueError(f"qa-engineer fixture at {path}: expected must be a mapping")
    verdict = expected.get("verdict")
    if verdict not in ("PASS", "FAIL", "PARTIAL", "BLOCKED"):
        raise ValueError(
            f"qa-engineer fixture at {path}: expected.verdict must be one of "
            "'PASS', 'FAIL', 'PARTIAL', 'BLOCKED'"
        )


_ARCHITECT_APPROACH_CLASSES = {
    "in_place_migration",
    "online_backfill",
    "dual_write",
    "middleware_insertion",
    "algorithmic_rewrite",
    "event_sourced_append",
    "additive_endpoint",
}


def _validate_architect_fixture(data: dict, path: Path) -> None:
    required = {"id", "component", "protocol_sha", "inputs", "expected"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"architect fixture at {path} missing keys: {sorted(missing)}")
    inputs = data.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError(f"architect fixture at {path}: inputs must be a mapping")
    for key in ("task_description", "codebase_context"):
        if not inputs.get(key):
            raise ValueError(
                f"architect fixture at {path}: inputs.{key} is required (non-empty)"
            )
    expected = data.get("expected") or {}
    if not isinstance(expected, dict):
        raise ValueError(f"architect fixture at {path}: expected must be a mapping")
    ac = expected.get("approach_class")
    if ac is not None and ac not in _ARCHITECT_APPROACH_CLASSES:
        raise ValueError(
            f"architect fixture at {path}: approach_class '{ac}' not in "
            f"{sorted(_ARCHITECT_APPROACH_CLASSES)} (null is also allowed)"
        )
    for list_key in (
        "required_api_symbols",
        "required_file_paths",
        "forbidden_patterns",
    ):
        val = expected.get(list_key)
        if val is not None and not isinstance(val, list):
            raise ValueError(
                f"architect fixture at {path}: expected.{list_key} must be a list"
            )
    kws = expected.get("required_keywords_by_section")
    if kws is not None and not isinstance(kws, dict):
        raise ValueError(
            f"architect fixture at {path}: expected.required_keywords_by_section must be a mapping"
        )
    oq = expected.get("open_questions_required")
    if oq is not None and oq not in ("none", "required"):
        raise ValueError(
            f"architect fixture at {path}: expected.open_questions_required must be "
            "'none', 'required', or null"
        )


_RELEASE_ORCH_STATUSES = {"SUCCESS", "FAILED", "ROLLED_BACK", "BLOCKED"}
_RELEASE_ORCH_TYPES = {"patch", "minor", "major"}


def _validate_release_orchestrator_fixture(data: dict, path: Path) -> None:
    required = {"id", "component", "protocol_sha", "inputs", "expected_plan"}
    missing = required - set(data)
    if missing:
        raise ValueError(
            f"release-orchestrator fixture at {path} missing keys: {sorted(missing)}"
        )
    inputs = data.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError(
            f"release-orchestrator fixture at {path}: inputs must be a mapping"
        )
    if not inputs.get("plan_only_directive"):
        raise ValueError(
            f"release-orchestrator fixture at {path}: inputs.plan_only_directive "
            "is required (the eval runs in planning-mode only; every fixture "
            "must forbid actual git tag/push and deploy command execution at "
            "the prompt layer)."
        )
    plan = data.get("expected_plan") or {}
    if not isinstance(plan, dict):
        raise ValueError(
            f"release-orchestrator fixture at {path}: expected_plan must be a mapping"
        )
    vd = plan.get("version_decision")
    if vd is not None:
        if not isinstance(vd, dict):
            raise ValueError(
                f"release-orchestrator fixture at {path}: expected_plan.version_decision must be a mapping"
            )
        t = vd.get("type")
        if t is not None and (not isinstance(t, str) or t.lower() not in _RELEASE_ORCH_TYPES):
            raise ValueError(
                f"release-orchestrator fixture at {path}: version_decision.type "
                f"must be one of {sorted(_RELEASE_ORCH_TYPES)} or omitted"
            )
    for key in ("phase_sequence", "gate_enforcement", "rollback", "changelog_tag"):
        val = plan.get(key)
        if val is not None and not isinstance(val, dict):
            raise ValueError(
                f"release-orchestrator fixture at {path}: expected_plan.{key} must be a mapping"
            )
    st = plan.get("expected_status")
    if st is not None and st not in _RELEASE_ORCH_STATUSES:
        raise ValueError(
            f"release-orchestrator fixture at {path}: expected_plan.expected_status "
            f"must be one of {sorted(_RELEASE_ORCH_STATUSES)} or omitted"
        )


def _validate_investigator_fixture(data: dict, path: Path) -> None:
    required = {"id", "component", "protocol_sha", "inputs", "expected_investigation"}
    missing = required - set(data)
    if missing:
        raise ValueError(
            f"investigator fixture at {path} missing keys: {sorted(missing)}"
        )
    inputs = data.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError(f"investigator fixture at {path}: inputs must be a mapping")
    if "question" not in inputs:
        raise ValueError(
            f"investigator fixture at {path}: inputs.question is required"
        )
    if "seed_dir" not in inputs:
        raise ValueError(
            f"investigator fixture at {path}: inputs.seed_dir is required "
            "(relative path to the seeded source subtree under the fixture dir)"
        )
    expected = data.get("expected_investigation") or {}
    if not isinstance(expected, dict):
        raise ValueError(
            f"investigator fixture at {path}: expected_investigation must be a mapping"
        )
    for key in (
        "answer_keywords",
        "expected_citations",
        "blast_radius_paths",
        "acceptable_confidence",
        "vacuous_axes",
    ):
        val = expected.get(key)
        if val is not None and not isinstance(val, list):
            raise ValueError(
                f"investigator fixture at {path}: expected_investigation.{key} must be a list"
            )
    gne = expected.get("gaps_nonempty")
    if gne is not None and not isinstance(gne, bool):
        raise ValueError(
            f"investigator fixture at {path}: expected_investigation.gaps_nonempty must be a bool"
        )


_SECURITY_AUDITOR_SEVERITIES = {"critical", "high", "medium", "informational"}


def _validate_security_auditor_fixture(data: dict, path: Path) -> None:
    required = {"id", "component", "protocol_sha", "inputs", "expected_findings"}
    missing = required - set(data)
    if missing:
        raise ValueError(
            f"security-auditor fixture at {path} missing keys: {sorted(missing)}"
        )
    inputs = data.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError(
            f"security-auditor fixture at {path}: inputs must be a mapping"
        )
    if not inputs.get("code_dir"):
        raise ValueError(
            f"security-auditor fixture at {path}: inputs.code_dir is required "
            "(relative path to the code subtree under the fixture dir)"
        )
    if not inputs.get("security_domain"):
        raise ValueError(
            f"security-auditor fixture at {path}: inputs.security_domain is "
            "required (e.g. 'API endpoint', 'authentication flow')"
        )
    ef = data.get("expected_findings") or {}
    if not isinstance(ef, dict):
        raise ValueError(
            f"security-auditor fixture at {path}: expected_findings must be a mapping"
        )
    for sev, entries in ef.items():
        if sev not in _SECURITY_AUDITOR_SEVERITIES:
            raise ValueError(
                f"security-auditor fixture at {path}: expected_findings key "
                f"'{sev}' not in {sorted(_SECURITY_AUDITOR_SEVERITIES)}"
            )
        if not isinstance(entries, list):
            raise ValueError(
                f"security-auditor fixture at {path}: expected_findings.{sev} must be a list"
            )
        for e in entries:
            if not isinstance(e, dict):
                raise ValueError(
                    f"security-auditor fixture at {path}: expected_findings.{sev} entries must be mappings"
                )
            if not e.get("id"):
                raise ValueError(
                    f"security-auditor fixture at {path}: each expected finding needs an id"
                )
            kws = e.get("keywords")
            if kws is not None and not isinstance(kws, list):
                raise ValueError(
                    f"security-auditor fixture at {path}: keywords must be a list"
                )
    cats = data.get("expected_owasp_categories")
    if cats is not None and not isinstance(cats, list):
        raise ValueError(
            f"security-auditor fixture at {path}: expected_owasp_categories must be a list"
        )


_UPDATE_AE_DECISIONS = {
    "proceed",
    "ff_pull",
    "stop_divergent",
    "stop_dirty",
    "happy_push",
}


def _validate_update_agentic_engineering_fixture(data: dict, path: Path) -> None:
    required = {
        "id",
        "component",
        "protocol_sha",
        "inputs",
        "pre_state",
        "expected_decision",
    }
    missing = required - set(data)
    if missing:
        raise ValueError(
            f"update-agentic-engineering fixture at {path} missing keys: {sorted(missing)}"
        )
    inputs = data.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError(
            f"update-agentic-engineering fixture at {path}: inputs must be a mapping"
        )
    if "repo_dir" not in inputs:
        raise ValueError(
            f"update-agentic-engineering fixture at {path}: inputs.repo_dir is required"
        )
    if "user_request" not in inputs:
        raise ValueError(
            f"update-agentic-engineering fixture at {path}: inputs.user_request is required"
        )
    pre = data.get("pre_state") or {}
    if not isinstance(pre, dict):
        raise ValueError(
            f"update-agentic-engineering fixture at {path}: pre_state must be a mapping"
        )
    for k in ("origin_ahead", "local_ahead"):
        v = pre.get(k, 0)
        if not isinstance(v, int) or v < 0:
            raise ValueError(
                f"update-agentic-engineering fixture at {path}: "
                f"pre_state.{k} must be a non-negative int"
            )
    if not isinstance(pre.get("dirty", False), bool):
        raise ValueError(
            f"update-agentic-engineering fixture at {path}: pre_state.dirty must be a bool"
        )
    dp = pre.get("dirty_paths") or []
    if not isinstance(dp, list):
        raise ValueError(
            f"update-agentic-engineering fixture at {path}: pre_state.dirty_paths must be a list"
        )
    dec = data.get("expected_decision")
    if dec not in _UPDATE_AE_DECISIONS:
        raise ValueError(
            f"update-agentic-engineering fixture at {path}: expected_decision "
            f"'{dec}' not in {sorted(_UPDATE_AE_DECISIONS)}"
        )
    te = data.get("target_edit")
    if te is not None and not isinstance(te, dict):
        raise ValueError(
            f"update-agentic-engineering fixture at {path}: target_edit must be a mapping or null"
        )
    for lk in ("must_commit_paths", "must_not_commit_paths", "forbidden_actions"):
        v = data.get(lk)
        if v is not None and not isinstance(v, list):
            raise ValueError(
                f"update-agentic-engineering fixture at {path}: {lk} must be a list"
            )


def _validate_cleanup_worktrees_fixture(data: dict, path: Path) -> None:
    required = {"id", "component", "protocol_sha", "inputs", "expected"}
    missing = required - set(data)
    if missing:
        raise ValueError(
            f"cleanup-worktrees fixture at {path} missing keys: {sorted(missing)}"
        )
    inputs = data.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError(
            f"cleanup-worktrees fixture at {path}: inputs must be a mapping"
        )
    if "repo_dir" not in inputs:
        raise ValueError(
            f"cleanup-worktrees fixture at {path}: inputs.repo_dir is required"
        )
    expected = data.get("expected") or {}
    if not isinstance(expected, dict):
        raise ValueError(
            f"cleanup-worktrees fixture at {path}: expected must be a mapping"
        )
    for key in (
        "expected_removals",
        "expected_preservations",
        "expected_branch_deletions",
        "expected_branch_preservations",
        "must_contain",
        "must_not_contain",
    ):
        val = expected.get(key)
        if val is not None and not isinstance(val, list):
            raise ValueError(
                f"cleanup-worktrees fixture at {path}: expected.{key} must be a list"
            )


def _validate_prune_harness_fixture(data: dict, path: Path) -> None:
    required = {"id", "component", "protocol_sha", "inputs", "expected"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"prune-harness fixture at {path} missing keys: {sorted(missing)}")
    inputs = data.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError(f"prune-harness fixture at {path}: inputs must be a mapping")
    if "repo_dir" not in inputs:
        raise ValueError(
            f"prune-harness fixture at {path}: inputs.repo_dir is required"
        )
    if "proposal_date" not in inputs:
        raise ValueError(
            f"prune-harness fixture at {path}: inputs.proposal_date is required "
            "(the YYYY-MM-DD string substituted into the proposal filename)"
        )
    expected = data.get("expected") or {}
    if not isinstance(expected, dict):
        raise ValueError(
            f"prune-harness fixture at {path}: expected must be a mapping"
        )
    if not expected.get("proposal_path"):
        raise ValueError(
            f"prune-harness fixture at {path}: expected.proposal_path is required"
        )
    tps = expected.get("expected_true_positives")
    if tps is not None and not isinstance(tps, list):
        raise ValueError(
            f"prune-harness fixture at {path}: expected.expected_true_positives must be a list"
        )
    for i, tp in enumerate(tps or []):
        if not isinstance(tp, dict):
            raise ValueError(
                f"prune-harness fixture at {path}: expected_true_positives[{i}] must be a mapping"
            )
        if not tp.get("file"):
            raise ValueError(
                f"prune-harness fixture at {path}: expected_true_positives[{i}].file is required"
            )
        conf = (tp.get("confidence") or "").upper()
        if conf not in ("HIGH", "MEDIUM", "LOW"):
            raise ValueError(
                f"prune-harness fixture at {path}: expected_true_positives[{i}].confidence "
                f"must be HIGH, MEDIUM, or LOW"
            )
    skips = expected.get("expected_signal_skips")
    if skips is not None and not isinstance(skips, list):
        raise ValueError(
            f"prune-harness fixture at {path}: expected.expected_signal_skips must be a list"
        )
    for s in skips or []:
        if not isinstance(s, int):
            raise ValueError(
                f"prune-harness fixture at {path}: expected_signal_skips entries must be ints"
            )
    seed_hashes = expected.get("seed_content_hashes")
    if seed_hashes is not None and not isinstance(seed_hashes, dict):
        raise ValueError(
            f"prune-harness fixture at {path}: expected.seed_content_hashes must be a mapping"
        )


def _validate_implement_ticket_fixture(data: dict, path: Path) -> None:
    required = {"id", "component", "protocol_sha", "inputs", "expected_outputs"}
    missing = required - set(data)
    if missing:
        raise ValueError(
            f"implement-ticket fixture at {path} missing keys: {sorted(missing)}"
        )
    inputs = data.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError(
            f"implement-ticket fixture at {path}: inputs must be a mapping"
        )
    for key in ("repo_dir", "base_branch", "ticket_description"):
        if not inputs.get(key):
            raise ValueError(
                f"implement-ticket fixture at {path}: inputs.{key} is required"
            )
    acs = inputs.get("acceptance_criteria")
    if acs is not None and not isinstance(acs, list):
        raise ValueError(
            f"implement-ticket fixture at {path}: inputs.acceptance_criteria must be a list"
        )
    expected = data.get("expected_outputs") or {}
    if not isinstance(expected, dict):
        raise ValueError(
            f"implement-ticket fixture at {path}: expected_outputs must be a mapping"
        )
    for list_key in (
        "must_touch_any_of",
        "commit_message_must_contain",
        "must_not_exist",
    ):
        val = expected.get(list_key)
        if val is not None and not isinstance(val, list):
            raise ValueError(
                f"implement-ticket fixture at {path}: expected_outputs.{list_key} must be a list"
            )
    max_loc = expected.get("max_loc")
    if max_loc is not None and not isinstance(max_loc, int):
        raise ValueError(
            f"implement-ticket fixture at {path}: expected_outputs.max_loc must be an int"
        )


_FIXTURE_VALIDATORS = {
    "skeptic": _validate_skeptic_fixture,
    "conductor": _validate_conductor_fixture,
    "init-project": _validate_init_project_fixture,
    "wrap": _validate_wrap_fixture,
    "debugger": _validate_debugger_fixture,
    "qa-engineer": _validate_qa_engineer_fixture,
    "architect": _validate_architect_fixture,
    "release-orchestrator": _validate_release_orchestrator_fixture,
    "investigator": _validate_investigator_fixture,
    "security-auditor": _validate_security_auditor_fixture,
    "memory-update": _validate_memory_update_fixture,
    "implement-ticket": _validate_implement_ticket_fixture,
    "prune-harness": _validate_prune_harness_fixture,
    "cleanup-worktrees": _validate_cleanup_worktrees_fixture,
    "update-agentic-engineering": _validate_update_agentic_engineering_fixture,
}


def _load_fixture_file(path: Path) -> Fixture:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Fixture at {path} is not a YAML mapping")
    component = data.get("component")
    if not component:
        raise ValueError(f"Fixture at {path} missing 'component' field")
    validator = _FIXTURE_VALIDATORS.get(component)
    if validator is None:
        raise ValueError(
            f"Fixture at {path}: no validator registered for component '{component}'. "
            f"Known: {sorted(_FIXTURE_VALIDATORS)}"
        )
    validator(data, path)

    # Components other than Skeptic may not carry expected_findings /
    # expected_signoff_granted; default them to empty so the Fixture shape is
    # uniform. Scoring modules read fixture.raw for component-specific fields.
    expected_findings = dict(data.get("expected_findings") or {})
    return Fixture(
        id=data["id"],
        description=data.get("description", ""),
        component=data["component"],
        protocol_sha=data.get("protocol_sha", ""),
        inputs=dict(data.get("inputs") or {}),
        expected_findings=expected_findings,
        expected_signoff_granted=bool(data.get("expected_signoff_granted", False)),
        clean_allowed=bool(expected_findings.get("clean_allowed", False)),
        path=path,
        raw=data,
    )


def load_fixtures(manifest: ComponentManifest) -> list[Fixture]:
    base = manifest.fixture_dir_abs
    if not base.exists():
        raise FileNotFoundError(f"Fixture dir missing: {base}")
    fixtures: list[Fixture] = []
    for fpath in sorted(base.glob("*/fixture.yaml")):
        fixtures.append(_load_fixture_file(fpath))
    return fixtures


def load_fixture(manifest: ComponentManifest, fixture_id: str) -> Fixture:
    path = manifest.fixture_dir_abs / fixture_id / "fixture.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Fixture {fixture_id} not found at {path}")
    return _load_fixture_file(path)


def _iter_content_files(manifest: ComponentManifest) -> list[Path]:
    files: list[Path] = []
    for pattern in manifest.content_glob:
        # Patterns are repo-root-relative.
        matches = list(_REPO_ROOT.glob(pattern))
        for m in matches:
            if m.is_file():
                files.append(m.resolve())
    # Deterministic order: sort by path string.
    return sorted(set(files), key=lambda p: str(p))


def current_protocol_sha(manifest: ComponentManifest) -> str | None:
    """Return the current git commit SHA that last touched any file in content_glob.

    This is the value that fixture authors record as `protocol_sha` at labeling
    time. Returns None if git is unavailable, if no files match content_glob, or
    if the files are not tracked in git.
    """
    files = _iter_content_files(manifest)
    if not files:
        return None
    rel_paths: list[str] = []
    for fpath in files:
        try:
            rel_paths.append(str(fpath.relative_to(_REPO_ROOT)))
        except ValueError:
            continue
    if not rel_paths:
        return None
    try:
        result = subprocess.run(
            ["git", "log", "-n", "1", "--format=%H", "--"] + rel_paths,
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def compute_component_content_hash(manifest: ComponentManifest) -> str:
    h = hashlib.sha256()
    # Prepend each file's repo-root-relative path (NUL-delimited) before its
    # bytes so that renaming or re-ordering files changes the hash, even if
    # the raw byte concatenation happens to collide.
    for fpath in _iter_content_files(manifest):
        try:
            rel = fpath.relative_to(_REPO_ROOT)
        except ValueError:
            rel = fpath
        h.update(str(rel).encode("utf-8"))
        h.update(b"\0")
        h.update(fpath.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


# Fields that define a fixture's semantic identity for caching / TSV keying.
# Fields like description, protocol_sha, and free-form comments are explicitly
# excluded so they can be reworded without invalidating the fixture cache.
_FIXTURE_HASH_FIELDS = ("id", "inputs", "expected_findings", "expected_signoff_granted")


def compute_fixture_hash(fixture_path: Path) -> str:
    """Hash a fixture by its semantic fields only (canonical JSON).

    This is intentionally NOT a hash of the raw YAML bytes: we want description
    reword churn, protocol_sha bumps, and comment edits to leave fixture_hash
    unchanged so TSV rows remain comparable across those edits. Changes to id,
    inputs, expected_findings, or expected_signoff_granted do alter the hash.
    """
    data: Any = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        # Preserve previous behaviour for malformed fixtures: hash raw bytes.
        return hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    semantic = {k: data.get(k) for k in _FIXTURE_HASH_FIELDS}
    payload = json.dumps(semantic, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
