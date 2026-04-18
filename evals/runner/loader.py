"""
Purpose: Load and validate component manifests and fixtures from disk,
         computing content and fixture hashes used as TSV keys.

Public API: load_component(name: str) -> ComponentManifest,
            load_fixtures(manifest: ComponentManifest) -> list[Fixture],
            load_fixture(manifest: ComponentManifest, fixture_id: str) -> Fixture,
            list_components() -> list[str],
            compute_component_content_hash(manifest: ComponentManifest) -> str,
            compute_fixture_hash(fixture_path: pathlib.Path) -> str,
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


def compute_component_content_hash(manifest: ComponentManifest) -> str:
    h = hashlib.sha256()
    for fpath in _iter_content_files(manifest):
        h.update(fpath.read_bytes())
    return h.hexdigest()


def compute_fixture_hash(fixture_path: Path) -> str:
    return hashlib.sha256(fixture_path.read_bytes()).hexdigest()
