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


_FIXTURE_VALIDATORS = {
    "skeptic": _validate_skeptic_fixture,
    "conductor": _validate_conductor_fixture,
    "init-project": _validate_init_project_fixture,
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
