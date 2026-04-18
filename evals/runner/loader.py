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
    if not isinstance(invoke_section, dict) or not invoke_section.get("agent_name"):
        raise ValueError(
            f"Component {name} manifest must set invoke.agent_name (the named subagent "
            "to spawn). This is required so the runner measures the actual named agent "
            "rather than a raw top-level Claude session."
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


def _load_fixture_file(path: Path) -> Fixture:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    required = {"id", "description", "component", "protocol_sha", "inputs", "expected_findings"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"Fixture at {path} missing keys: {sorted(missing)}")
    return Fixture(
        id=data["id"],
        description=data["description"],
        component=data["component"],
        protocol_sha=data["protocol_sha"],
        inputs=dict(data["inputs"]),
        expected_findings=dict(data["expected_findings"]),
        expected_signoff_granted=bool(data.get("expected_signoff_granted", False)),
        clean_allowed=bool(data["expected_findings"].get("clean_allowed", False)),
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
