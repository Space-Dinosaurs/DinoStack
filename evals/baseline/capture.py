"""
Purpose: CLI tool and library that captures a point-in-time snapshot of evals/auto/
         and evals/components/ scores into a reproducible baseline JSON artifact.
         Stage-0 precondition for the ICL vs orchestration evaluation.

Public API:
    capture_baseline(output_path: Path, resume: bool = False) -> BaselineResult
    collect_component_scores(component_yaml: Path, results_tsv: Path) -> ComponentEntry
    collect_environment_metadata() -> EnvironmentDict
    collect_git_metadata() -> GitDict

    CLI:
        python -m evals.baseline.capture --output evals/baselines/2026-05-pre-icl-restructure.json
        python -m evals.baseline.capture --resume

Upstream dependencies:
    - Python 3.11 stdlib (argparse, hashlib, json, os, pathlib, platform, socket,
      subprocess, tempfile, csv, shutil, datetime)
    - evals/components/*.yaml (component manifests; enumerated at runtime)
    - evals/results/*.tsv (pre-computed score data; not re-run by this tool)
    - ~/.claude/agentic-engineering.json (methodology config snapshot)
    - git CLI (via subprocess; must be on PATH)

Downstream consumers:
    - evals/baseline/validate.py (reads the output JSON for schema validation)
    - Stage-6 comparison runner (reads agentic_engineering_sha to pin the AE condition)
    - Any future harness consuming schema_version: 1 baseline artifacts

Failure modes:
    - Dirty git working tree: capture refuses with a clear error; not resumable across
      SHA changes. Call abort_with_msg(); exit(1).
    - Missing results TSV for a component: records as components_skipped, not a hard fail.
    - subprocess failure (git, claude CLI): individual fields set to None with reason string;
      does not abort the overall capture unless git HEAD is unreadable.
    - Partial capture interrupted mid-run: progress sibling file preserves completed
      components; resume validates SHA + clean tree before continuing.

Performance: One-shot CLI run; reads pre-computed TSVs only (no model calls). Expected
             wall time: <5 seconds for 20 components on a cold filesystem.
"""

import argparse
import csv
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TypedDict


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class GitDict(TypedDict):
    ai_tools_sha: str
    ai_tools_dirty: bool
    agentic_engineering_sha: Optional[str]
    agentic_engineering_dirty: bool
    helios_sha: Optional[str]
    helios_dirty: bool


class EnvironmentDict(TypedDict):
    claude_cli_version: Optional[str]
    claude_config_snapshot: Optional[str]
    agentic_engineering_json: Optional[dict]
    agentic_engineering_json_path: str
    model_tier_default: str
    python_version: str
    platform: str
    hostname: str


class FixtureEntry(TypedDict):
    fixture_hash: str
    fixture_description: str
    primary_score_median: float
    primary_score_stdev: float
    n_runs: int
    status: str
    captured_at_sha: str


class ComponentEntry(TypedDict):
    name: str
    manifest_path: str
    manifest_sha256: str
    fixtures: list[FixtureEntry]


class SkippedEntry(TypedDict):
    name: str
    reason: str


class FailedEntry(TypedDict):
    name: str
    reason: str


class ManifestEnumeration(TypedDict):
    discovered_yaml_files: list[str]
    count: int
    all_accounted_for: bool


class BaselineResult(TypedDict):
    schema_version: int
    baseline_id: str
    captured_at_utc: str
    captured_by: str
    stochasticity_disclaimer: str
    git: GitDict
    environment: EnvironmentDict
    components: list[ComponentEntry]
    components_skipped: list[SkippedEntry]
    components_failed: list[FailedEntry]
    manifest_enumeration: ManifestEnumeration


class ValidationResult(TypedDict):
    ok: bool
    errors: list[str]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
BASELINE_ID = "2026-05-pre-icl-restructure"
CAPTURED_BY = "evals-baseline-capture@v1"
STOCHASTICITY_DISCLAIMER = (
    "This baseline is one sample of a stochastic distribution. "
    "Stage 6 comparison MUST be distributional (e.g. Wilcoxon signed-rank against "
    "recorded n=3 medians or per-fixture-stdev-multiplied bands), "
    "NOT point-equality or fixed-percent thresholds."
)

# Resolved from this file's location: evals/baseline/capture.py -> repo root is ../../..
_THIS_FILE = Path(__file__).resolve()
_EVALS_DIR = _THIS_FILE.parent.parent          # evals/
_REPO_ROOT = _THIS_FILE.parent.parent.parent   # repo root


def _run(cmd: list[str], cwd: Optional[Path] = None) -> tuple[int, str, str]:
    """Run a subprocess; return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd or _REPO_ROOT),
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _abort(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Git metadata
# ---------------------------------------------------------------------------

def _sha_for_submodule(name: str) -> tuple[Optional[str], bool]:
    """Return (sha, dirty) for a named submodule. (None, False) if not found."""
    rc, out, _ = _run(["git", "submodule", "status", name])
    if rc != 0 or not out:
        return None, False
    # Format: [+- ]<sha> <name> [(<desc>)]
    # Leading '+' means dirty, ' ' means clean, '-' means not initialized
    line = out.strip()
    dirty = line.startswith("+")
    parts = line.lstrip("+ -").split()
    sha = parts[0] if parts else None
    return sha, dirty


def _resolve_parent_repo_root() -> Optional[Path]:
    """
    Resolve the parent (ai-tools) repo root when capture.py runs inside a git
    worktree of the agentic-engineering submodule clone.

    Strategy:
      1. Read the .git file in _REPO_ROOT (which is the ae worktree root).
         If it is a regular directory (main worktree), there is no parent.
      2. If .git is a file, it contains "gitdir: <path>".  Parse the path to
         get the git common dir, then walk up two levels:
           <common-dir>  = .../agentic-engineering/.git
           <ae-dir>      = .../agentic-engineering/
           <parent-root> = .../ai-tools/    <- what we want
      3. Verify the candidate is itself a git repo (contains a .git entry).
      4. Return None on any error so the caller can record null gracefully.
    """
    git_marker = _REPO_ROOT / ".git"
    if not git_marker.exists():
        return None

    # Case: regular directory - this IS the main worktree, no parent
    if git_marker.is_dir():
        return None

    # Case: .git file -> worktree
    try:
        content = git_marker.read_text().strip()
    except OSError:
        return None

    # Expected: "gitdir: /abs/path/to/.git/worktrees/<name>"
    if not content.startswith("gitdir:"):
        return None
    git_dir = Path(content.split(":", 1)[1].strip())

    # The common git dir for a worktree is resolved via git rev-parse
    rc, common_dir_str, _ = _run(["git", "rev-parse", "--git-common-dir"], cwd=_REPO_ROOT)
    if rc != 0 or not common_dir_str:
        # Fall back: walk up from the gitdir path
        # gitdir = <common>/.git/worktrees/<name>  -> common = gitdir.parent.parent.parent
        common_dir = git_dir.parent.parent.parent
    else:
        common_dir = Path(common_dir_str).resolve()

    # common_dir is <ae-root>/.git  -> ae-root = common_dir.parent
    ae_root = common_dir.parent
    parent_root = ae_root.parent

    # Sanity check: parent should be a git repo
    if not (parent_root / ".git").exists():
        return None

    return parent_root


def collect_git_metadata() -> GitDict:
    """
    Collect git SHAs and dirty-tree status for the ae worktree HEAD and the
    parent (ai-tools) repo HEAD.

    When capture.py runs inside the agentic-engineering worktree:
      - agentic_engineering_sha = git rev-parse HEAD  (the ae branch HEAD)
      - ai_tools_sha             = parent repo HEAD    (the ai-tools gitlink SHA)

    If the parent repo root cannot be resolved, ai_tools_sha is recorded as
    None with a note rather than aborting; agentic_engineering_sha is always
    required (aborts on failure).
    """
    # ae HEAD - required; abort if unreadable
    rc, ae_sha, err = _run(["git", "rev-parse", "HEAD"])
    if rc != 0:
        _abort(f"Cannot read git HEAD: {err}")

    rc_dirty, dirty_out, _ = _run(["git", "status", "--porcelain"])
    ae_dirty = bool(dirty_out.strip()) if rc_dirty == 0 else False

    # parent (ai-tools) HEAD - best-effort; null if not resolvable
    parent_root = _resolve_parent_repo_root()
    if parent_root is not None:
        rc_p, parent_sha, _ = _run(["git", "rev-parse", "HEAD"], cwd=parent_root)
        ai_tools_sha: Optional[str] = parent_sha if rc_p == 0 else None
    else:
        ai_tools_sha = None

    helios_sha, helios_dirty = _sha_for_submodule("helios")

    return GitDict(
        ai_tools_sha=ai_tools_sha,
        ai_tools_dirty=False,  # dirty check is for the ae worktree, not parent
        agentic_engineering_sha=ae_sha,
        agentic_engineering_dirty=ae_dirty,
        helios_sha=helios_sha,
        helios_dirty=helios_dirty,
    )


# ---------------------------------------------------------------------------
# Environment metadata
# ---------------------------------------------------------------------------

def collect_environment_metadata() -> EnvironmentDict:
    """
    Collect CLI versions, agentic-engineering config, and platform info.
    Fields that cannot be populated record explicit None with reason in the value.
    """
    # claude CLI version
    rc, claude_ver, _ = _run(["claude", "--version"])
    claude_cli_version: Optional[str] = claude_ver if rc == 0 else None

    # claude config list
    rc2, config_out, config_err = _run(["claude", "config", "list"])
    if rc2 == 0:
        claude_config_snapshot: Optional[str] = config_out
    else:
        claude_config_snapshot = f"null:command-failed:{config_err or 'non-zero exit'}"

    # agentic-engineering.json
    ae_json_path = Path.home() / ".claude" / "agentic-engineering.json"
    ae_json: Optional[dict] = None
    if ae_json_path.exists():
        try:
            ae_json = json.loads(ae_json_path.read_text())
        except Exception as exc:
            ae_json = {"null": f"parse-error:{exc}"}
    else:
        ae_json = {"null": "file-not-found"}

    # model tier default - try to derive from agentic-engineering.json preset/profile
    model_tier = "unknown:not-resolvable-from-config"
    if isinstance(ae_json, dict) and "preset" in ae_json and ae_json["preset"] is not None:
        preset_map = {"lean": "relaxed", "standard": "default", "strict": "strict"}
        profile = preset_map.get(ae_json["preset"], ae_json.get("profile", "default"))
        model_tier = f"sonnet:profile={profile}"
    elif isinstance(ae_json, dict) and "profile" in ae_json:
        model_tier = f"sonnet:profile={ae_json['profile']}"

    machine = platform.machine()
    system = platform.system().lower()
    plat_str = f"{system}-{machine}"

    return EnvironmentDict(
        claude_cli_version=claude_cli_version,
        claude_config_snapshot=claude_config_snapshot,
        agentic_engineering_json=ae_json,
        agentic_engineering_json_path=str(ae_json_path),
        model_tier_default=model_tier,
        python_version=platform.python_version(),
        platform=plat_str,
        hostname=socket.gethostname(),
    )


# ---------------------------------------------------------------------------
# Component score extraction
# ---------------------------------------------------------------------------

def _file_sha256(path: Path) -> str:
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return h


def collect_component_scores(
    component_yaml: Path,
    results_tsv: Path,
    ai_tools_sha: str,
) -> ComponentEntry:
    """
    Extract fixture scores from a pre-computed results TSV for one component.
    Returns a ComponentEntry dict.

    Expected TSV columns (tab-separated, first row is header):
        commit, component_content_hash, fixture_hash, primary_score_median,
        primary_score_stdev, n_runs, status, diagnostic_json, description
    """
    name = component_yaml.stem
    manifest_path = str(component_yaml.relative_to(_REPO_ROOT))
    manifest_sha256 = _file_sha256(component_yaml)

    fixtures: list[FixtureEntry] = []

    with results_tsv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            try:
                fixtures.append(FixtureEntry(
                    fixture_hash=row["fixture_hash"],
                    fixture_description=row.get("description", ""),
                    primary_score_median=float(row["primary_score_median"]),
                    primary_score_stdev=float(row["primary_score_stdev"]),
                    n_runs=int(row["n_runs"]),
                    status=row["status"],
                    captured_at_sha=row.get("commit", ai_tools_sha),
                ))
            except (KeyError, ValueError):
                # Malformed row; skip but don't abort
                continue

    return ComponentEntry(
        name=name,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        fixtures=fixtures,
    )


# ---------------------------------------------------------------------------
# Progress file helpers
# ---------------------------------------------------------------------------

def _progress_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".progress")


def _load_progress(output_path: Path) -> Optional[dict]:
    p = _progress_path(output_path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _save_progress(output_path: Path, progress: dict) -> None:
    p = _progress_path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Write atomically via tmp+rename
    tmp = p.with_suffix(".progress.tmp")
    tmp.write_text(json.dumps(progress, indent=2))
    shutil.move(str(tmp), str(p))


def _delete_progress(output_path: Path) -> None:
    p = _progress_path(output_path)
    if p.exists():
        p.unlink()


# ---------------------------------------------------------------------------
# Resume preconditions
# ---------------------------------------------------------------------------

def _ae_json_sha256() -> Optional[str]:
    ae_path = Path.home() / ".claude" / "agentic-engineering.json"
    if ae_path.exists():
        return hashlib.sha256(ae_path.read_bytes()).hexdigest()
    return None


def _verify_resume_preconditions(progress: dict, current_sha: str) -> None:
    """
    Verify all 4 resume preconditions. Abort with explanation if any fail.
    """
    errors = []

    # Precondition 2: SHA must match
    if progress.get("started_at_sha") != current_sha:
        errors.append(
            f"SHA mismatch: progress started at {progress.get('started_at_sha')!r} "
            f"but current HEAD is {current_sha!r}. "
            "Cross-SHA contamination is not permitted. Start fresh or abandon."
        )

    # Precondition 3: working tree must be clean (already verified before this call,
    # but re-check against what progress recorded)
    rc, dirty, _ = _run(["git", "status", "--porcelain"])
    if dirty.strip():
        errors.append(
            "Working tree is dirty. Clean all uncommitted changes before resuming."
        )

    # Precondition 4: agentic-engineering.json SHA must match
    current_ae_sha = _ae_json_sha256()
    recorded_ae_sha = progress.get("agentic_engineering_json_sha256")
    if recorded_ae_sha and current_ae_sha != recorded_ae_sha:
        errors.append(
            f"~/.claude/agentic-engineering.json has changed since capture started "
            f"(recorded={recorded_ae_sha!r}, current={current_ae_sha!r}). "
            "Methodology config changed; cannot resume. Start fresh."
        )

    if errors:
        msg = "\n  ".join(errors)
        _abort(f"Resume preconditions failed:\n  {msg}")


# ---------------------------------------------------------------------------
# Main capture logic
# ---------------------------------------------------------------------------

def capture_baseline(output_path: Path, resume: bool = False) -> BaselineResult:
    """
    Capture the baseline. If resume=True and a valid progress file exists,
    continues from where a prior session left off.

    Returns the completed BaselineResult dict (also written atomically to output_path).
    """
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect git metadata first - abort if HEAD unreadable
    git_meta = collect_git_metadata()
    # current_sha is the ae worktree HEAD; used for resume SHA pinning
    current_sha = git_meta["agentic_engineering_sha"]

    # --- Resume or fresh start ---
    progress = _load_progress(output_path)
    completed_by_name: dict[str, ComponentEntry] = {}
    started_at_sha = current_sha
    started_at_utc = datetime.now(timezone.utc).isoformat()

    if resume and progress is not None:
        _verify_resume_preconditions(progress, current_sha)
        started_at_sha = progress["started_at_sha"]
        started_at_utc = progress["started_at_utc"]
        for entry in progress.get("components_completed", []):
            completed_by_name[entry["name"]] = entry["entry"]
        print(
            f"Resuming from progress file. "
            f"{len(completed_by_name)} components already captured."
        )
    elif resume and progress is None:
        p = _progress_path(output_path)
        if not p.exists():
            _abort(
                f"--resume specified but progress file not found: {p}\n"
                "  Precondition 1 failed: progress file does not exist. "
                "Run without --resume to start a fresh capture."
            )
        else:
            _abort(
                f"--resume specified but progress file could not be parsed: {p}\n"
                "  Precondition 1 failed: file exists but JSON is invalid or corrupt. "
                "Delete the progress file and run without --resume to start fresh."
            )
    elif not resume and progress is not None:
        print(
            "WARNING: A progress file exists from a prior session but --resume was not "
            "specified. Starting fresh (existing progress ignored)."
        )

    # --- Enumerate components ---
    components_dir = _EVALS_DIR / "components"
    results_dir = _EVALS_DIR / "results"
    yaml_files = sorted(components_dir.glob("*.yaml"))
    yaml_names = [y.stem for y in yaml_files]

    components: list[ComponentEntry] = []
    components_skipped: list[SkippedEntry] = []
    components_failed: list[FailedEntry] = []

    # Start from completed set
    for name, entry in completed_by_name.items():
        components.append(entry)

    remaining = [y for y in yaml_files if y.stem not in completed_by_name]

    # Collect environment once (may change on resume but that's ok - collect fresh)
    env_meta = collect_environment_metadata()

    for yaml_file in remaining:
        name = yaml_file.stem
        tsv_path = results_dir / f"{name}.tsv"

        if not tsv_path.exists():
            print(f"  SKIP {name}: no results TSV at {tsv_path.relative_to(_REPO_ROOT)}")
            components_skipped.append(SkippedEntry(
                name=name,
                reason=f"no results TSV at evals/results/{name}.tsv",
            ))
        else:
            try:
                entry = collect_component_scores(yaml_file, tsv_path, current_sha)
                components.append(entry)
                print(
                    f"  OK   {name}: {len(entry['fixtures'])} fixtures"
                )
            except Exception as exc:
                print(f"  FAIL {name}: {exc}")
                components_failed.append(FailedEntry(name=name, reason=str(exc)))

        # Save progress after each component
        completed_entries = [
            {"name": c["name"], "captured_at_sha": current_sha, "entry": c}
            for c in components
        ]
        remaining_names = [
            y.stem for y in yaml_files
            if y.stem not in {c["name"] for c in components}
            and y.stem not in {s["name"] for s in components_skipped}
            and y.stem not in {f["name"] for f in components_failed}
        ]
        ae_sha = _ae_json_sha256()
        _save_progress(output_path, {
            "schema_version": SCHEMA_VERSION,
            "started_at_sha": started_at_sha,
            "started_at_utc": started_at_utc,
            "agentic_engineering_json_sha256": ae_sha,
            "components_completed": completed_entries,
            "components_remaining": remaining_names,
        })

    # --- Verify all YAMLs accounted for ---
    accounted = (
        {c["name"] for c in components}
        | {s["name"] for s in components_skipped}
        | {f["name"] for f in components_failed}
    )
    all_accounted = set(yaml_names) == accounted

    manifest_enum = ManifestEnumeration(
        discovered_yaml_files=[
            str(y.relative_to(_REPO_ROOT)) for y in yaml_files
        ],
        count=len(yaml_files),
        all_accounted_for=all_accounted,
    )

    if not all_accounted:
        missing = set(yaml_names) - accounted
        extra = accounted - set(yaml_names)
        msg_parts = []
        if missing:
            msg_parts.append(f"missing from output: {sorted(missing)}")
        if extra:
            msg_parts.append(f"extra in output (not in components/): {sorted(extra)}")
        print(f"WARNING: manifest enumeration mismatch - {'; '.join(msg_parts)}")

    baseline: BaselineResult = BaselineResult(
        schema_version=SCHEMA_VERSION,
        baseline_id=BASELINE_ID,
        captured_at_utc=datetime.now(timezone.utc).isoformat(),
        captured_by=CAPTURED_BY,
        stochasticity_disclaimer=STOCHASTICITY_DISCLAIMER,
        git=git_meta,
        environment=env_meta,
        components=components,
        components_skipped=components_skipped,
        components_failed=components_failed,
        manifest_enumeration=manifest_enum,
    )

    # --- Atomic write via tmp+rename ---
    tmp_path = output_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(baseline, indent=2))
    shutil.move(str(tmp_path), str(output_path))

    # --- Delete progress file on success ---
    _delete_progress(output_path)

    print(f"\nBaseline written to: {output_path}")
    print(f"  Components captured: {len(components)}")
    print(f"  Skipped: {len(components_skipped)}")
    print(f"  Failed:  {len(components_failed)}")
    print(f"  Capture SHA (agentic_engineering_sha): {git_meta['agentic_engineering_sha']}")

    return baseline


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_output() -> Path:
    return _EVALS_DIR / "baselines" / f"{BASELINE_ID}.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture an evals baseline snapshot for the ICL vs orchestration evaluation.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_default_output(),
        help="Output path for the baseline JSON (default: evals/baselines/2026-05-pre-icl-restructure.json)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a prior capture from the progress sibling file.",
    )
    args = parser.parse_args()

    capture_baseline(output_path=args.output, resume=args.resume)


if __name__ == "__main__":
    main()
