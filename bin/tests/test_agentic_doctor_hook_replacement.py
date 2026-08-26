"""Unit + caller-level tests for bin/ds-doctor's _hook_replacement() (DS-206).

Covers the accumulator rewrite that converges every stale, DinoStack-shaped
occurrence of every managed hook basename present in a settings.json
`command` string, in one call - fixing the bug where only the FIRST token
matching the FIRST basename found was ever rewritten, leaving a guarded
form's `test -f <NEW> && python3 <OLD> || exit 0` half-fixed.

Run with: python3 -m pytest bin/tests/test_agentic_doctor_hook_replacement.py -x

Test-first ordering (DS-206): this file was written and run against the
UNMODIFIED (pre-fix) _hook_replacement before the fix landed, and against
the live (post-fix) function after. Each test's own docstring states its
expected pre-fix/post-fix status (RED pre-fix / GREEN post-fix, or GREEN
both ways for a characterization test) and, where the case is a
characterization test rather than a plain regression case, its verified
reddening mutation - deliberately not duplicated here, since a second copy
of that information drifts independently of the code and the tests
themselves (this file has already gone through three review rounds where
a hand-maintained summary of this kind went stale on the round it was
supposed to describe).
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path

_BIN = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("_ds_doctor_hr", str(_BIN / "ds-doctor"))
_spec = importlib.util.spec_from_loader("_ds_doctor_hr", _loader)
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

Doctor = _mod.Doctor
_hook_replacement = _mod._hook_replacement
check_hook_paths = _mod.check_hook_paths


def _realpath(p: Path) -> Path:
    return Path(os.path.realpath(str(p)))


def _mkrepo(tmp_path: Path) -> Path:
    """A realpath'd fixture repo_dir - never the real checkout.

    Realpathed per the mandatory fixture-construction rule: _load_repo_dir()
    always realpaths, so an un-realpathed fixture makes "already correct"
    assertions pass for the wrong reason on macOS (/tmp -> /private/tmp).
    """
    repo = tmp_path / "DinoStack"
    (repo / ".git").mkdir(parents=True)
    (repo / "hooks").mkdir(parents=True)
    return _realpath(repo)


# ---------------------------------------------------------------------------
# Unit-level cases against _hook_replacement directly
# ---------------------------------------------------------------------------


def test_fully_stale_guarded_form(tmp_path):
    """RED pre-fix / GREEN post-fix: both the `test -f` and `python3`
    clauses of a guarded form point at the same stale basename occurrence
    (the simplest fully-unconverted case)."""
    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    old = old_repo / "hooks" / "enforce-turn-shape.py"
    cmd = f"test -f {old} && python3 {old} || exit 0"
    result = _hook_replacement(cmd, repo)
    assert result is not None
    assert str(old) not in result
    assert str(repo / "hooks" / "enforce-turn-shape.py") in result


def test_half_fixed_guarded_form(tmp_path):
    """RED pre-fix / GREEN post-fix. The bug's own residue: test -f already
    points at NEW, python3 still OLD."""
    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    new = repo / "hooks" / "enforce-turn-shape.py"
    old = old_repo / "hooks" / "enforce-turn-shape.py"
    cmd = f"test -f {new} && python3 {old} || exit 0"
    result = _hook_replacement(cmd, repo)
    assert result is not None
    assert str(old) not in result
    assert str(new) in result


def test_mixed_stale_path_guarded_form(tmp_path):
    """RED pre-fix / GREEN post-fix. Two distinct old locations for the
    same basename in one command."""
    repo = _mkrepo(tmp_path)
    old_repo_a = tmp_path / "old-a-DinoStack"
    old_repo_b = tmp_path / "old-b-DinoStack"
    old_a = old_repo_a / "hooks" / "enforce-turn-shape.py"
    old_b = old_repo_b / "hooks" / "enforce-turn-shape.py"
    cmd = f"test -f {old_a} && python3 {old_b} || exit 0"
    result = _hook_replacement(cmd, repo)
    assert result is not None
    assert str(old_a) not in result
    assert str(old_b) not in result
    assert str(repo / "hooks" / "enforce-turn-shape.py") in result


def test_two_managed_basenames_one_command(tmp_path):
    """RED pre-fix / GREEN post-fix. Space-delimited, `&&`-joined shape -
    what .claude/install.sh's own guarded multi-hook registrations
    actually look like. NOT semicolon-joined: a `;`-adjacent stale token
    is a distinct, disclosed corruption path (see
    test_adjacent_punctuation_token_loses_punctuation below) and must not
    be conflated with ordinary multi-basename convergence.
    """
    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    old1 = old_repo / "hooks" / "enforce-background-spawn.py"
    old2 = old_repo / "hooks" / "enforce-orchestrator-singularity.py"
    new1 = repo / "hooks" / "enforce-background-spawn.py"
    new2 = repo / "hooks" / "enforce-orchestrator-singularity.py"
    cmd = f"python3 {old1} && python3 {old2}"
    result = _hook_replacement(cmd, repo)
    assert result is not None
    assert str(old1) not in result
    assert str(old2) not in result
    # Exact-string assertion, not mere substring containment: pins that the
    # `&&` joiner and spacing are preserved, not merely that the stale paths
    # are gone (a corrupting repair that also removed the joiner would still
    # pass the weaker substring-only form used pre-fix-round-2).
    assert result == f"python3 {new1} && python3 {new2}"


def test_three_distinct_stale_occurrences(tmp_path):
    """RED pre-fix / GREEN post-fix. Space-delimited, `&&`-joined shape
    (see test_two_managed_basenames_one_command's docstring for why `;`
    is deliberately not used here)."""
    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    old1 = old_repo / "hooks" / "enforce-background-spawn.py"
    old2 = old_repo / "hooks" / "enforce-orchestrator-singularity.py"
    old3 = old_repo / "hooks" / "enforce-tier.py"
    new1 = repo / "hooks" / "enforce-background-spawn.py"
    new2 = repo / "hooks" / "enforce-orchestrator-singularity.py"
    new3 = repo / "hooks" / "enforce-tier.py"
    cmd = f"python3 {old1} && python3 {old2} && python3 {old3}"
    result = _hook_replacement(cmd, repo)
    assert result is not None
    assert str(old1) not in result
    assert str(old2) not in result
    assert str(old3) not in result
    assert result == f"python3 {new1} && python3 {new2} && python3 {new3}"


def test_adjacent_punctuation_token_loses_punctuation(tmp_path):
    """GREEN both pre-fix and post-fix. CHARACTERIZATION TEST, not a
    supported-behavior guard: pins the
    disclosed, accepted corruption in _hook_replacement's Known limitations
    #2 - a stale token immediately followed by punctuation (here, a `;`
    with no separating space) is replaced via `str(Path(token))`, which
    silently drops the trailing punctuation from the token's own string
    form. `.claude/install.sh` never emits this shape (its registrations
    are always space-delimited, no adjacent punctuation), so this input is
    unreachable from any current producer - this test exists ONLY to make
    the accepted-but-real corruption path explicit and machine-checked, so
    a reader cannot mistake test_two_managed_basenames_one_command or
    test_three_distinct_stale_occurrences (both now `&&`-joined) as
    covering this shape. If this assertion ever starts failing because the
    punctuation is preserved, that is an IMPROVEMENT to document, not a
    regression to chase.
    """
    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    old = old_repo / "hooks" / "enforce-tier.py"
    new = repo / "hooks" / "enforce-tier.py"
    cmd = f"python3 {old}; echo done"
    result = _hook_replacement(cmd, repo)
    assert result is not None
    assert str(old) not in result
    # The trailing semicolon (adjacent to the stale token, no separating
    # space) is silently dropped - this is the disclosed corruption, not a
    # well-formed repair.
    assert result == f"python3 {new} echo done"


def test_bare_single_occurrence_stale_form(tmp_path):
    """Already worked under the pre-fix count=1 shape - GREEN both ways.

    This assertion form is IDENTICAL pre-fix and post-fix; a passing run
    here is not evidence the fix is applied, only that the bare single-token
    case was never broken. Do not misread it as a red-run failure signal.
    """
    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    old = old_repo / "hooks" / "enforce-tier.py"
    cmd = f"python3 {old}"
    result = _hook_replacement(cmd, repo)
    assert result is not None
    assert str(old) not in result
    assert str(repo / "hooks" / "enforce-tier.py") in result


def test_already_correct_guarded_form(tmp_path):
    """GREEN both ways by design - returns None, nothing to repair."""
    repo = _mkrepo(tmp_path)
    new = repo / "hooks" / "enforce-turn-shape.py"
    cmd = f"test -f {new} && python3 {new} || exit 0"
    result = _hook_replacement(cmd, repo)
    assert result is None


def test_lone_token_normalization_mismatch_reports_false_healthy(tmp_path):
    """RED pre-fix / GREEN post-fix. CHARACTERIZATION TEST for the Major-1
    fix-round-2 disclosure, not a supported-behavior guard: pins the
    MEASURED pre-fix vs post-fix difference for a lone (single-occurrence)
    token whose string form has a normalization difference from
    repo_dir/hooks/<basename> (here, a doubled path separator).

    Pre-fix (verified against origin/main at commit 91b2d7d6's parent):
    the old body returned `cmd.replace(...)` unconditionally once the
    DinoStack-shape test passed, so this lone mismatched token was
    returned UNCHANGED (non-None) - a visible but no-op `FIX hooks` line,
    read-only exit 1.

    Post-fix (this test, against the live function): `changed` stays
    False because `new_result != result` never holds (str.replace found
    nothing to replace), so the function returns None - `check_hook_paths`
    then reports "OK hooks: ... all managed hook paths reference
    repo_dir", exit 0. This is a silent, positive false-healthy verdict
    for an unreachable-from-any-current-producer input; accepted per
    Pillar 8, not fixed, but must not be characterized as unchanged
    behavior - it is a real, disclosed regression in this one dimension
    for this specific unreachable input.
    """
    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    # Doubled separator - Path()/str() round-tripping does not normalize
    # this away, so str.replace(str(token_path), ...) never matches.
    mismatched = f"{old_repo}//hooks/enforce-tier.py"
    cmd = f"python3 {mismatched}"
    result = _hook_replacement(cmd, repo)
    assert result is None, (
        "post-fix, a lone normalization-mismatched token must report None "
        "(silent false-healthy) per the disclosed Known limitation #1 - "
        "if this changes, update both this test and the docstring together"
    )


def test_multi_occurrence_partial_repair_leaves_mismatch_stale(tmp_path):
    """GREEN both pre-fix and post-fix. CHARACTERIZATION TEST, not a
    supported-behavior guard: pins the MEASURED pre-fix/post-fix
    EQUIVALENCE (not a difference) for the multi-occurrence,
    same-basename, guarded-form shape.

    Measured identically against both origin/main's pre-fix
    _hook_replacement and this file's live (post-fix) function: a guarded
    command with one normalization-mismatched occurrence of a basename and
    one cleanly-stale occurrence of the SAME basename returns a non-None,
    partially-repaired string in which the mismatched occurrence is still
    present verbatim. Pre-fix's `cmd.replace(..., count=1)` already
    rewrote the clean occurrence and returned a non-None string with the
    mismatched one untouched; post-fix's accumulator does the same. This
    shape did NOT change between rounds - see Known limitation #1 in
    _hook_replacement's own docstring, which now describes only this
    present-tense behavior with no pre-fix/post-fix provenance claim.

    Reddening mutation (VERIFIED by execution, not merely named): revert
    _hook_replacement to its pre-fix body - confirmed to produce the SAME
    non-None/mismatch-still-present result for this exact input, so this
    test does NOT redden on that specific revert (that is the point: it
    pins an equivalence, not a difference). It DOES redden on changing the
    replace target from the Path-normalized `str(token_path)` to the raw
    `token` substring - i.e. `result.replace(token, str(expected))`
    instead of `result.replace(str(token_path), str(expected))` - because
    the raw token string (still containing the doubled separator) exists
    verbatim in `result`/`cmd`, so that mutation makes the mismatched
    occurrence get silently rewritten too, failing this test's "still
    present" assertion. Confirmed against a mutated copy of ds-doctor
    before this test was finalized.
    """
    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    # Doubled separator - never matched by str.replace (Known limitation #1).
    mismatched = f"{old_repo}//hooks/enforce-tier.py"
    clean_stale = old_repo / "hooks" / "enforce-tier.py"
    cmd = f"test -f {mismatched} && python3 {clean_stale} || exit 0"
    result = _hook_replacement(cmd, repo)
    assert result is not None, (
        "the clean occurrence alone should make changed True even though "
        "the mismatched occurrence cannot be rewritten"
    )
    assert mismatched in result, (
        "the normalization-mismatched occurrence must remain verbatim in "
        "the returned command - if it is gone, str.replace started "
        "matching it, which is a real behavior change requiring a "
        "docstring update"
    )
    assert str(clean_stale) not in result


def test_non_dinostack_shaped_path_untouched(tmp_path):
    """GREEN both pre-fix and post-fix. Negative case: a non-DinoStack-
    shaped stale path is left alone.

    The accumulator replaced an early `return None` with full iteration over
    all tokens and all managed basenames, widening the predicate's blast
    radius. Nothing pre-existing pinned this negative case - pin it here.
    """
    repo = _mkrepo(tmp_path)
    foreign = tmp_path / "some-other-project" / "hooks" / "enforce-tier.py"
    cmd = f"python3 {foreign}"
    result = _hook_replacement(cmd, repo)
    assert result is None


# ---------------------------------------------------------------------------
# Caller-level test: check_hook_paths / _atomic_patch_settings writes a
# fully-converged command to disk. MANDATORY isolation: monkeypatch HOME and
# delenv CLAUDE_CONFIG_DIR BEFORE constructing Doctor(...) or calling
# check_hook_paths - without it this test rewrites the developer's real
# ~/.claude/settings.json (reproduced by execution in prior review rounds).
# ---------------------------------------------------------------------------


def test_caller_writes_fully_converged_command_to_disk(tmp_path, monkeypatch):
    """RED pre-fix / GREEN post-fix. Verifies AC1's actual caller contract:
    check_hook_paths/_atomic_patch_settings write a fully-converged command
    to disk (a guarded Stop-hook entry plus a separate PreToolUse entry,
    two different basenames), not merely that the unit function returns
    one."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    old1 = old_repo / "hooks" / "enforce-turn-shape.py"
    old2 = old_repo / "hooks" / "enforce-tier.py"

    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    settings_path = claude_dir / "settings.json"
    settings = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"test -f {old1} && python3 {old1} || exit 0",
                            "timeout": 10,
                        }
                    ],
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "Task",
                    "hooks": [
                        {"type": "command", "command": f"python3 {old2}", "timeout": 5}
                    ],
                }
            ],
        }
    }
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    doc = Doctor(repo_dir=repo, fix=True, json_mode=True)
    check_hook_paths(doc)

    written = json.loads(settings_path.read_text(encoding="utf-8"))
    written_text = json.dumps(written)
    assert str(old1) not in written_text
    assert str(old2) not in written_text
    assert str(repo / "hooks" / "enforce-turn-shape.py") in written_text
    assert str(repo / "hooks" / "enforce-tier.py") in written_text


def test_repair_exits_zero_with_no_fail_line(tmp_path, monkeypatch):
    """RED pre-fix (Amendment 1's own defect, introduced by the accumulator
    widening drift's reach, fixed in the same commit) / GREEN post-fix.
    Amendment 1 regression guard: a successful repair must not also
    report itself as an unfixable FAIL via repoint_symlink's os.symlink
    call against settings.json (a regular file, not a symlink) raising
    FileExistsError.

    Mutation that would redden this: reverting the check_hook_paths fix
    back to `doc.repoint_symlink("hooks", settings_path, old_cmd,
    Path(new_cmd))` (the plan's pre-Amendment-1 caller shape) reproduces
    `FAIL hooks: could not re-point ...: [Errno 17] File exists` and
    doc.fix mode's has_unresolved_findings() returns True.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    repo = _mkrepo(tmp_path)
    old_repo = tmp_path / "old-DinoStack"
    old = old_repo / "hooks" / "enforce-tier.py"

    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    settings_path = claude_dir / "settings.json"
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Task",
                    "hooks": [
                        {"type": "command", "command": f"python3 {old}", "timeout": 5}
                    ],
                }
            ]
        }
    }
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    doc = Doctor(repo_dir=repo, fix=True, json_mode=True)
    check_hook_paths(doc)

    assert not any(status == "FAIL" for status, _ in doc.findings), doc.findings
    assert not doc.has_unresolved_findings()
    assert not doc.has_unfixable()
