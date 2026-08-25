"""
Purpose: Regression guard for the `docs/overview/_proposed/` carve-out in the
         repo's root `.gitignore` (DS-200 U3). The carve-out must let
         `_proposed/*.md` be tracked WITHOUT re-enabling tracking of secrets
         and OS junk underneath it. An earlier round of DS-200 shipped the
         two-line form

             !docs/overview/_proposed/
             !docs/overview/_proposed/**

         which was measured, independently and twice, to make `.env` and
         `.DS_Store` under `_proposed/` TRACKABLE: gitignore matching is
         last-match-wins, and that broad `**` negation sits LATER in the file
         than the repo-wide `.env` / `.env.local` / `.env*.local` / `.DS_Store`
         rules, so it overrode them. The shipped three-line form re-excludes
         the directory's contents (`docs/overview/_proposed/*`) before
         negating only `*.md`, so no rule that matches a dotfile secret is
         ever overridden.

         Nothing else in the repo guards this, so a revert or a re-broadening
         of the negation would land silently. That is what this file exists to
         redden.

Public API: pytest test functions only; no importable helpers are intended for
            reuse outside this module.

Upstream deps: stdlib (subprocess, os, pathlib) plus `pytest`, the module's
            only non-stdlib dependency (parametrization and fixtures). Shells
            out to the system `git` binary against a disposable pytest
            `tmp_path` repo. Reads the LIVE root `.gitignore` of this
            checkout (never a hand-typed copy - a fixture built from
            remembered rules validates the fixture, not the repo). No network,
            no writes anywhere outside `tmp_path`.

Downstream consumers: none (leaf test module). Collected by
            `python3 -m pytest bin/tests/ -q`, which is the `python-bin-tests`
            job in `.github/workflows/bin-tests.yml`.

Failure modes: every git subprocess that establishes or reads fixture state
            (`init`, `add -A`, `ls-files -z`) runs with `check=True` and a
            bounded timeout, so a broken fixture raises loudly rather than
            yielding a misleading pass. The one exception is the diagnostic-
            only `check-ignore -v` call in `_check_ignore_detail`, which runs
            with `check=False` since a nonzero exit there is not itself a
            fixture failure. `_trackable_set()` asserts the probe files it
            wrote are actually on disk before consulting git, so an empty
            result can never be mistaken for "everything is ignored".

Performance: standard; one `git init` plus three git commands per
             parametrized case (`add -A`, `ls-files -z`, `check-ignore -v`),
             all local (~50ms each).

Oracle note (deliberate, see DS-200 U3 brief item 4): this module does NOT use
`git check-ignore` exit status as its oracle. Measured: `check-ignore -v`
exits 0 when a NEGATION matches an untracked path, so exit status alone is
ambiguous in both directions for exactly the rules under test here. Instead
the oracle is real staging semantics - write every probe file, run `git add
-A` (which silently skips ignored paths and stages everything else), then read
`git ls-files`. That set IS the answer to "what can be committed", which is
the property the carve-out exists to control, and it has no ambiguous case.
`git check-ignore -v` output is still collected, but only as diagnostic detail
in assertion messages.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

# bin/tests/<this file> -> bin/tests -> bin -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_GITIGNORE = REPO_ROOT / ".gitignore"

_SUBPROCESS_TIMEOUT_SECONDS = 30

# The shipped three-line carve-out, as it appears in the live root .gitignore.
# Used only as the search target for building the mutant below - the tests
# themselves always run against the live file's real bytes.
CORRECT_FORM = (
    "!docs/overview/_proposed/\n"
    "docs/overview/_proposed/*\n"
    "!docs/overview/_proposed/*.md\n"
)

# The defective form an earlier DS-200 round shipped. Reinstating it is the
# mutation this suite must redden.
BROAD_NEGATION_FORM = (
    "!docs/overview/_proposed/\n"
    "!docs/overview/_proposed/**\n"
)

# Probe paths. Every one is created on disk in the fixture repo.
PROPOSED = "docs/overview/_proposed"

# Must stay IGNORED under _proposed/ - these are the paths the broad-negation
# form leaked. `secret.env.local` matches NONE of the repo-wide .env rules
# (they all anchor on a leading `.env`), so it is ignored solely by the middle
# `docs/overview/_proposed/*` re-exclusion line - it is the probe that proves
# that line is load-bearing on its own.
SECRETS_UNDER_PROPOSED = (
    f"{PROPOSED}/.env",
    f"{PROPOSED}/.env.local",
    f"{PROPOSED}/secret.env.local",
    f"{PROPOSED}/.DS_Store",
)

# Must be TRACKABLE - the whole point of the carve-out.
TRACKABLE_UNDER_PROPOSED = f"{PROPOSED}/vision.md"

# Must stay IGNORED - the earlier rules the broad negation was overriding, plus
# the `docs/overview/*` umbrella the carve-out is punched through.
UNREGRESSED_IGNORED = (
    ".env",
    ".DS_Store",
    "docs/overview/junk-probe.md",
)

# Pre-existing carve-out that must survive untouched.
PREEXISTING_TRACKABLE = "docs/overview/vision.md"

ALL_PROBES = (
    *SECRETS_UNDER_PROPOSED,
    TRACKABLE_UNDER_PROPOSED,
    *UNREGRESSED_IGNORED,
    PREEXISTING_TRACKABLE,
)


def _hermetic_env(tmp_path: Path) -> dict[str, str]:
    """Env that isolates git from the operator's real config - in particular
    from any global `core.excludesFile`, which would otherwise silently add
    ignore rules this suite is not testing."""
    global_config = tmp_path / "empty-gitconfig"
    global_config.write_text("", encoding="utf-8")
    home = tmp_path / "fixture-home"
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = str(global_config)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(args: list[str], cwd: Path, env: dict[str, str], check: bool = True):
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        check=check,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        stdin=subprocess.DEVNULL,
    )


def _check_ignore_detail(repo: Path, env: dict[str, str]) -> str:
    """Diagnostic only, never the oracle: which rule git says matched each
    probe. Included in assertion messages so a failure names the offending
    .gitignore line instead of just the path."""
    result = _git(
        ["check-ignore", "-v", "--no-index", "--", *ALL_PROBES],
        cwd=repo,
        env=env,
        check=False,
    )
    return result.stdout or "(no rule matched any probe)"


def _trackable_set(tmp_path: Path, gitignore_text: str) -> tuple[set[str], str]:
    """Build a scratch repo carrying `gitignore_text`, materialize every probe
    path, then return (set of paths git will actually stage, diagnostic).

    `git add -A` silently skips ignored paths and stages everything else, so
    the resulting `git ls-files` IS the trackable set - real staging
    semantics, not an exit-status inference."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    env = _hermetic_env(tmp_path)
    _git(["init", "-q", "-b", "main"], cwd=repo, env=env)
    (repo / ".gitignore").write_text(gitignore_text, encoding="utf-8")

    for rel in ALL_PROBES:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"probe content for {rel}\n", encoding="utf-8")
        assert path.is_file(), f"fixture invariant violated: failed to write probe {rel}"

    _git(["add", "-A"], cwd=repo, env=env)
    listed = _git(["ls-files", "-z"], cwd=repo, env=env).stdout
    tracked = {entry for entry in listed.split("\0") if entry}
    # `.gitignore` itself is always staged; drop it so callers compare probes.
    tracked.discard(".gitignore")
    return tracked, _check_ignore_detail(repo, env)


def _live_gitignore_text() -> str:
    return LIVE_GITIGNORE.read_text(encoding="utf-8")


def test_live_gitignore_contains_the_three_line_carveout():
    """Fails loudly if the carve-out is reverted or reshaped, so the behavior
    tests below can never pass vacuously against a file that no longer has the
    construct they describe."""
    text = _live_gitignore_text()
    assert CORRECT_FORM in text, (
        "the three-line docs/overview/_proposed/ carve-out is missing from "
        f"{LIVE_GITIGNORE}. Expected to find, contiguously:\n{CORRECT_FORM}"
    )
    assert "!docs/overview/_proposed/**" not in text, (
        "the root .gitignore contains the broad `!docs/overview/_proposed/**` "
        "negation. Under last-match-wins that overrides the repo-wide .env / "
        ".DS_Store rules above it and makes secrets under _proposed/ "
        "trackable - the exact defect this carve-out replaced."
    )


@pytest.mark.parametrize("rel", SECRETS_UNDER_PROPOSED)
def test_secrets_under_proposed_are_ignored(tmp_path: Path, rel: str):
    tracked, detail = _trackable_set(tmp_path, _live_gitignore_text())
    assert rel not in tracked, (
        f"{rel} is TRACKABLE under the live root .gitignore - a secret or OS "
        f"junk file under docs/overview/_proposed/ must never be committable.\n"
        f"check-ignore -v detail:\n{detail}"
    )


def test_proposed_markdown_is_trackable(tmp_path: Path):
    tracked, detail = _trackable_set(tmp_path, _live_gitignore_text())
    assert TRACKABLE_UNDER_PROPOSED in tracked, (
        f"{TRACKABLE_UNDER_PROPOSED} is NOT trackable under the live root "
        f".gitignore - the carve-out exists precisely to allow it.\n"
        f"check-ignore -v detail:\n{detail}"
    )


@pytest.mark.parametrize("rel", UNREGRESSED_IGNORED)
def test_earlier_rules_are_unregressed(tmp_path: Path, rel: str):
    tracked, detail = _trackable_set(tmp_path, _live_gitignore_text())
    assert rel not in tracked, (
        f"{rel} became TRACKABLE - the _proposed/ carve-out has regressed a "
        f"rule that sits earlier in the file.\ncheck-ignore -v detail:\n{detail}"
    )


def test_preexisting_overview_vision_carveout_survives(tmp_path: Path):
    tracked, detail = _trackable_set(tmp_path, _live_gitignore_text())
    assert PREEXISTING_TRACKABLE in tracked, (
        f"{PREEXISTING_TRACKABLE} is no longer trackable - the pre-existing "
        f"`!docs/overview/vision.md` carve-out has been broken.\n"
        f"check-ignore -v detail:\n{detail}"
    )


def test_broad_negation_mutant_leaks_secrets(tmp_path: Path):
    """The reddening mutation, codified.

    Swapping the shipped three-line form for the two-line broad-negation form
    that an earlier DS-200 round shipped must make `.env` and `.DS_Store`
    under `_proposed/` trackable. If this test ever stops observing the leak,
    the oracle above has gone blind and every assertion in this module is
    decorative - so the leak is asserted POSITIVELY here rather than being
    left as a one-off manual check."""
    live = _live_gitignore_text()
    assert CORRECT_FORM in live, "cannot build the mutant: shipped form not found"
    mutant = live.replace(CORRECT_FORM, BROAD_NEGATION_FORM)
    assert mutant != live, "mutation was a no-op"

    tracked, detail = _trackable_set(tmp_path, mutant)
    leaked = [rel for rel in SECRETS_UNDER_PROPOSED if rel in tracked]
    assert set(leaked) == set(SECRETS_UNDER_PROPOSED), (
        "the broad-negation mutant did NOT leak every secret probe, so the "
        "oracle cannot distinguish the defect from the fix. Leaked: "
        f"{sorted(leaked)}; expected all of {sorted(SECRETS_UNDER_PROPOSED)}.\n"
        f"check-ignore -v detail:\n{detail}"
    )
    assert TRACKABLE_UNDER_PROPOSED in tracked, (
        "sanity check failed: the mutant should still make vision.md "
        "trackable, so the leak above is the ONLY behavioral difference."
    )
