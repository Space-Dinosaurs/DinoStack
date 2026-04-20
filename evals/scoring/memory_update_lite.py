"""
Purpose: Score a single /memory-update command-mode run against a labeled
         fixture by walking the worktree's filesystem snapshot, inspecting
         the text-level content of `.agentic/memory/MEMORY.md` where
         present, classifying the shape of the write (new / update / noop)
         against the fixture's expectation, and combining six weighted
         dimensions.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], status: "ok" | "invalid_format",
             diagnostic: dict, scorer_version: "v1"}.

Contract: score() expects a single-run trace (trace["runs"] has one run
          record). The run record carries a "filesystem" dict (relative
          path -> sha256) populated by evals.runner.invoker in command
          mode, and "worktree_root" so the scorer can read the text of
          MEMORY.md directly.

Upstream deps: stdlib pathlib.

Downstream consumers: evals.runner.cli (dynamic import per manifest's
                      scoring_module).

Failure modes: missing filesystem snapshot => status "invalid_format",
               primary 0.0. Missing worktree_root => text-level
               dimensions degrade gracefully (absent MEMORY.md treated
               as empty string).

---

memory_update_lite v1 scores the single side-effect of /memory-update:
the contents (and existence) of `.agentic/memory/MEMORY.md`. The command
body collapses a main-agent + background Worker spawn into one inline
session under this eval (documented in the component README as a proxy),
so the scorer cannot measure the background-spawn discipline - only the
resulting file.

## Scoring formula (v1)

Weighted sum across six dimensions. Weights sum to exactly 1.0 (runtime
assertion).

    w_file     = 0.20  (MEMORY.md existence matches must_exist /
                        must_not_exist; vacuous when neither side of the
                        expectation applies, which does not occur on
                        the current corpus).
    w_shape    = 0.25  (bullet-count delta vs seeded MEMORY.md matches
                        expected_entry_shape. Tiered: the three shapes
                        {new, update, noop} form an adjacency gradient
                        similar to wrap_lite's route credit. Exact -> 1.0,
                        adjacent -> 0.5, wrong-direction -> 0.0. Vacuous
                        when expected_entry_shape is null - i.e. when
                        the fixture expects the file to not exist).
    w_required = 0.25  (fraction of required_substrings present in
                        MEMORY.md; vacuous when list empty).
    w_forbidden= 0.15  (fraction of forbidden_substrings absent from
                        MEMORY.md; vacuous when list empty).
    w_header   = 0.10  (file starts with `# Memory` AND contains no
                        invented H2 beyond that single header; vacuous
                        when MEMORY.md is not expected to exist).
    w_mustnot  = 0.05  (no path from must_not_exist is present in the
                        snapshot; vacuous when list empty).

Shape adjacency:
    {new, update} adjacent  (both are real writes; routing between them
                             is a judgement call on whether a prior
                             entry exists and is related).
    {update, noop} adjacent (both touch-or-preserve an existing entry;
                             a worker that conservatively no-ops when a
                             fuzzy duplicate exists is a softer failure
                             than one that writes a fresh duplicate).
    {new, noop} wrong       (a genuinely new decision silently dropped,
                             or a noop-fixture getting a fresh write,
                             are the two wrong-direction failure modes).

Shape inference:
    seed_bullets     = count of lines starting with "- **" in the
                       seeded MEMORY.md (0 if file not seeded).
    observed_bullets = count of lines starting with "- **" in the
                       post-run MEMORY.md (0 if absent).
    delta = observed_bullets - seed_bullets.
    - delta >= 1                 -> "new"
    - delta == 0 and seed > 0    -> "update" if the seeded bullet text
                                    appears to have changed (simple sha
                                    of the bullet block differs) else
                                    "noop"
    - delta == 0 and seed == 0   -> "noop"
    - delta < 0                  -> "new" (worker deleted content; we
                                    treat this as a wrong shape via the
                                    adjacency map - a fixture expecting
                                    noop will score 0, a fixture expecting
                                    new will score 1.0 for shape but will
                                    fail required_substrings).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

SCORER_VERSION = "v1"

_W_FILE = 0.20
_W_SHAPE = 0.25
_W_REQUIRED = 0.25
_W_FORBIDDEN = 0.15
_W_HEADER = 0.10
_W_MUSTNOT = 0.05

_WEIGHTS_SUM_ASSERTION = abs(
    (_W_FILE + _W_SHAPE + _W_REQUIRED + _W_FORBIDDEN + _W_HEADER + _W_MUSTNOT) - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "memory_update_lite weights must sum to 1.0"

_MEMORY_PATH = ".agentic/memory/MEMORY.md"

_SHAPES = {"new", "update", "noop"}
_SHAPE_CREDIT = {
    "new":    {"new": 1.0, "update": 0.5, "noop": 0.0},
    "update": {"new": 0.5, "update": 1.0, "noop": 0.5},
    "noop":   {"new": 0.0, "update": 0.5, "noop": 1.0},
}


def _read_text(worktree_root: str | None, rel_path: str) -> str:
    if not worktree_root:
        return ""
    p = Path(worktree_root) / rel_path
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_seed_text(fixture: dict) -> str:
    """Read the seeded MEMORY.md from the fixture dir (if any).

    fixture["_fixture_dir"] is injected by the runner when the fixture is
    loaded; fall back to walking from `fixture_path` if present. The seed
    lives at <fixture_dir>/repo/.agentic/memory/MEMORY.md. Missing file
    -> empty string.
    """
    fd = fixture.get("_fixture_dir")
    if not fd:
        return ""
    p = Path(fd) / "repo" / ".agentic" / "memory" / "MEMORY.md"
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _count_bullets(text: str) -> int:
    return sum(1 for ln in text.splitlines() if ln.lstrip().startswith("- **"))


def _bullet_block_hash(text: str) -> str:
    bullets = "\n".join(
        ln for ln in text.splitlines() if ln.lstrip().startswith("- **")
    )
    return hashlib.sha256(bullets.encode("utf-8")).hexdigest()


def _infer_shape(seed_text: str, observed_text: str) -> str:
    seed_bullets = _count_bullets(seed_text)
    observed_bullets = _count_bullets(observed_text)
    delta = observed_bullets - seed_bullets
    if delta >= 1:
        return "new"
    if delta < 0:
        # Worker deleted content. Classify as "new" so wrong-direction
        # adjacency logic applies consistently.
        return "new"
    # delta == 0
    if seed_bullets == 0:
        return "noop"
    if _bullet_block_hash(seed_text) != _bullet_block_hash(observed_text):
        return "update"
    return "noop"


def _score_required(text: str, needles: list[str]) -> tuple[float, dict[str, Any]]:
    if not needles:
        return 1.0, {"vacuous": True, "hits": 0, "total": 0, "missing": []}
    hits = 0
    missing: list[str] = []
    for n in needles:
        if n in text:
            hits += 1
        else:
            missing.append(n)
    return hits / len(needles), {
        "vacuous": False,
        "hits": hits,
        "total": len(needles),
        "missing": missing,
    }


def _score_forbidden(text: str, needles: list[str]) -> tuple[float, dict[str, Any]]:
    if not needles:
        return 1.0, {"vacuous": True, "hits": 0, "total": 0, "present": []}
    present: list[str] = []
    for n in needles:
        if n in text:
            present.append(n)
    absent = len(needles) - len(present)
    return absent / len(needles), {
        "vacuous": False,
        "absent": absent,
        "total": len(needles),
        "present": present,
    }


def _score_header(text: str, must_exist_expected: bool) -> tuple[float, dict[str, Any]]:
    if not must_exist_expected:
        return 1.0, {"vacuous": True}
    if not text:
        return 0.0, {"vacuous": False, "reason": "file_absent"}
    lines = text.splitlines()
    # Ignore leading blank lines.
    first_nonblank = next((ln for ln in lines if ln.strip()), "")
    header_ok = first_nonblank.strip() == "# Memory"
    # Count H2 lines (lines starting with "## "). Worker spec forbids
    # invented H2 beyond the file header; zero H2 is correct.
    invented_h2 = [ln for ln in lines if ln.startswith("## ")]
    if header_ok and not invented_h2:
        return 1.0, {"vacuous": False, "header_ok": True, "invented_h2": []}
    # Half credit for one defect, zero for both.
    if header_ok or not invented_h2:
        return 0.5, {
            "vacuous": False,
            "header_ok": header_ok,
            "invented_h2": invented_h2,
        }
    return 0.0, {
        "vacuous": False,
        "header_ok": False,
        "invented_h2": invented_h2,
    }


def score(trace: dict, fixture: dict) -> dict:
    runs = trace.get("runs") or []
    if not runs:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {"reason": "no_runs", "scorer_version": SCORER_VERSION},
            "scorer_version": SCORER_VERSION,
        }
    assert len(runs) == 1
    run = runs[0]
    snapshot = run.get("filesystem")
    if not isinstance(snapshot, dict):
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "no_filesystem_snapshot",
                "cli_status": run.get("status"),
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }
    snapshot_keys = set(snapshot.keys())
    worktree_root = run.get("worktree_root")

    expected = fixture.get("expected_outputs") or {}
    must_exist = list(expected.get("must_exist") or [])
    must_not_exist = list(expected.get("must_not_exist") or [])
    required_substrings = list(expected.get("required_substrings") or [])
    forbidden_substrings = list(expected.get("forbidden_substrings") or [])
    expected_shape = expected.get("expected_entry_shape")

    memory_expected = _MEMORY_PATH in must_exist
    memory_must_not = _MEMORY_PATH in must_not_exist
    memory_present = _MEMORY_PATH in snapshot_keys
    observed_text = _read_text(worktree_root, _MEMORY_PATH) if memory_present else ""
    seed_text = _read_seed_text(fixture)

    # --- w_file ---
    if memory_expected and not memory_must_not:
        file_credit = 1.0 if memory_present else 0.0
        file_detail: dict[str, Any] = {
            "vacuous": False,
            "expected_present": True,
            "observed_present": memory_present,
        }
    elif memory_must_not and not memory_expected:
        file_credit = 0.0 if memory_present else 1.0
        file_detail = {
            "vacuous": False,
            "expected_present": False,
            "observed_present": memory_present,
        }
    else:
        # Neither side declared - vacuous.
        file_credit = 1.0
        file_detail = {"vacuous": True, "observed_present": memory_present}

    # --- w_shape ---
    if expected_shape is None:
        shape_credit = 1.0
        shape_detail: dict[str, Any] = {"vacuous": True}
    else:
        if expected_shape not in _SHAPES:
            shape_credit = 0.0
            shape_detail = {
                "vacuous": False,
                "reason": f"unknown_expected_shape:{expected_shape}",
            }
        else:
            observed_shape = _infer_shape(seed_text, observed_text)
            shape_credit = _SHAPE_CREDIT[expected_shape].get(observed_shape, 0.0)
            shape_detail = {
                "vacuous": False,
                "expected": expected_shape,
                "observed": observed_shape,
                "seed_bullets": _count_bullets(seed_text),
                "observed_bullets": _count_bullets(observed_text),
                "credit": shape_credit,
            }

    # --- w_required ---
    required_credit, required_detail = _score_required(observed_text, required_substrings)

    # --- w_forbidden ---
    forbidden_credit, forbidden_detail = _score_forbidden(observed_text, forbidden_substrings)

    # --- w_header ---
    header_credit, header_detail = _score_header(observed_text, memory_expected)

    # --- w_mustnot ---
    if not must_not_exist:
        mustnot_credit = 1.0
        mustnot_detail: dict[str, Any] = {"vacuous": True, "hits": []}
    else:
        hits_list = [p for p in must_not_exist if p in snapshot_keys]
        mustnot_credit = 1.0 if not hits_list else 0.0
        mustnot_detail = {"vacuous": False, "hits": hits_list}

    primary_raw = (
        _W_FILE * file_credit
        + _W_SHAPE * shape_credit
        + _W_REQUIRED * required_credit
        + _W_FORBIDDEN * forbidden_credit
        + _W_HEADER * header_credit
        + _W_MUSTNOT * mustnot_credit
    )
    primary = max(0.0, min(1.0, primary_raw))

    diagnostic: dict[str, Any] = {
        "file": file_detail,
        "shape": shape_detail,
        "required": required_detail,
        "forbidden": forbidden_detail,
        "header": header_detail,
        "mustnot": mustnot_detail,
        "snapshot_file_count": len(snapshot_keys),
        "memory_present": memory_present,
        "scorer_version": SCORER_VERSION,
    }

    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
