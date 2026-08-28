#!/usr/bin/env python3
"""
Purpose: pytest suite for DS-217's `_pr_state` multi-account `gh` retry in
         bin/ds-cleanup-worktrees. Covers: resolving a query via a SECOND
         configured `gh` login when the default (no-override) call fails;
         positive per-repo env caching (a later branch in the same repo
         reuses the winning env with exactly one more `gh` call, not
         once per account again); negative per-repo caching (a repo where
         every configured account fails makes ZERO further `gh` calls on
         a later entry); the revoked/expired-account filter in
         `_gh_configured_logins`; and the single-account case staying
         call-count-identical to pre-DS-217 behavior.

         Every fake `gh` stub below is a tiny bash script - no real `gh`
         binary, network, or auth state is ever touched by this file.
         `monkeypatch.setenv("PATH", ...)` prepends the stub's directory
         directly onto the REAL process environment (rather than
         patching `subprocess.run`), because `_pr_state`'s retry loop
         builds its `GH_TOKEN`-override env as `{**os.environ,
         "GH_TOKEN": token}` - a patched-argument approach that doesn't
         also mutate real `os.environ` would silently miss that literal
         `os.environ` reference and give the override calls the
         unmodified system PATH. A shared `CALL_LOG` file records one
         line per invocation (subcommand only, never a token) so each
         scenario can assert an exact `gh` call count.

Public API: none (test module; invoked via `python3 -m pytest`).

Upstream deps: bin/ds-cleanup-worktrees (module under test, imported
               directly via SourceFileLoader, mirroring
               bin/tests/test_cleanup_worktrees.py's own
               `_load_module_directly` pattern - `_pr_state`,
               `_gh_configured_logins`, `_PR_STATE_ENV_CACHE`, and
               `_PR_STATE_ALL_FAILED_REPOS` are called/reset directly).

Downstream consumers: CI (`python3 -m pytest bin/tests/ -q`, auto-collected
                      per `.github/workflows/bin-tests.yml`).

Failure modes: no real DinoStack checkout, worktree, branch, or `gh` auth
               state is ever touched by this file. Each scenario gets a
               fresh module object (own `_PR_STATE_ENV_CACHE` /
               `_PR_STATE_ALL_FAILED_REPOS` globals), and `monkeypatch`
               restores `PATH`/`GH_TOKEN` after every test.

Performance: each scenario shells out to the fake `gh` stub a handful of
             times. Sub-second per test.
"""

from __future__ import annotations

import importlib.machinery as _ilm
import importlib.util as _ilu
import os
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "ds-cleanup-worktrees"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _load_module_directly():
    """Fresh module object per call - mirrors
    bin/tests/test_cleanup_worktrees.py's own helper of the same name, so
    each test gets its own `_PR_STATE_ENV_CACHE` / `_PR_STATE_ALL_FAILED_
    REPOS` module globals rather than sharing state with any other test
    file's import of the same script."""
    loader = _ilm.SourceFileLoader("ds_cleanup_worktrees_ds217", str(SCRIPT))
    spec = _ilu.spec_from_loader("ds_cleanup_worktrees_ds217", loader)
    mod = _ilu.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _fake_gh_multi_account(tmp_path: Path, *, accounts, success_tokens, call_log: Path) -> Path:
    """Builds a fake `gh` on its own PATH-prepend dir.

    `accounts`: list of `(login, state, active)` tuples - rendered
    verbatim into a `gh auth status --json hosts` JSON payload (single
    host `github.com`), in the given order (active-first ordering is
    `_gh_configured_logins`'s own job to produce, not this fixture's).

    `success_tokens`: set of `GH_TOKEN` values (as seen by the `pr list`
    invocation) that make `gh pr list` succeed with `[]`. Use `""` to
    mean "GH_TOKEN unset/empty" (the default, no-override attempt).
    ANY other `GH_TOKEN` value fails `pr list` with a nonzero exit and a
    stderr message mirroring GitHub's real generic
    "Could not resolve to a Repository" ambiguity.

    `gh auth token --user <login>` returns `token-<login>` for any login
    present in `accounts` (regardless of its `state` - filtering revoked
    accounts out of the candidate list is `_gh_configured_logins`'s job,
    not this fixture's; a mutation that deletes that filter must still be
    able to obtain a token for the revoked login and observe a real
    query attempt).

    Every invocation appends one line (subcommand words only, never a
    token value) to `call_log`, so tests can assert an exact `gh` call
    count."""
    bin_dir = tmp_path / f"fakebin-{len(list(tmp_path.glob('fakebin-*')))}"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"

    host_accounts = ",".join(
        f'{{"state":"{state}","active":{"true" if active else "false"},'
        f'"host":"github.com","login":"{login}"}}'
        for login, state, active in accounts
    )
    hosts_json = f'{{"hosts":{{"github.com":[{host_accounts}]}}}}'

    token_cases = "\n".join(f'    {login}) echo "token-{login}" ;;' for login, _state, _active in accounts)

    success_case = "|".join(f'"{tok}"' for tok in success_tokens) or '"__never__"'

    gh.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$1 $2 $3" >> "{call_log}"\n'
        'if [ "$1" = "auth" ] && [ "$2" = "status" ] && [ "$3" = "--json" ]; then\n'
        f"  echo '{hosts_json}'\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "auth" ] && [ "$2" = "status" ]; then exit 0; fi\n'
        'if [ "$1" = "auth" ] && [ "$2" = "token" ]; then\n'
        '  case "$4" in\n'
        f"{token_cases}\n"
        '    *) exit 1 ;;\n'
        "  esac\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "pr" ] && [ "$2" = "list" ]; then\n'
        f'  case "${{GH_TOKEN:-}}" in\n'
        f"    {success_case}) echo '[]'; exit 0 ;;\n"
        '    *) echo "gh: could not resolve to a Repository" >&2; exit 1 ;;\n'
        "  esac\n"
        "fi\n"
        "exit 1\n"
    )
    gh.chmod(0o755)
    return bin_dir


def _call_lines(call_log: Path) -> list:
    if not call_log.exists():
        return []
    return [line for line in call_log.read_text().splitlines() if line.strip()]


def _pr_list_call_count(call_log: Path) -> int:
    return sum(1 for line in _call_lines(call_log) if line.startswith("pr list"))


@pytest.fixture(autouse=True)
def _clean_gh_env(monkeypatch):
    """Every scenario in this file assumes the AMBIENT environment carries
    no `GH_TOKEN` - a real one set on the developer/CI machine would make
    the default (no-override) `_pr_state_query` call succeed even under
    the fake `gh` stub, since `env=None` inherits the process environment
    unchanged and the stub reads `${GH_TOKEN:-}` from whatever it
    inherits."""
    monkeypatch.delenv("GH_TOKEN", raising=False)


def _prepend_fake_gh(monkeypatch, gh_dir: Path) -> None:
    """Prepends `gh_dir` onto the REAL `os.environ["PATH"]` via
    `monkeypatch.setenv` (restored automatically after the test) - not a
    `subprocess.run` argument patch. `_pr_state`'s retry loop builds its
    `GH_TOKEN`-override env as `{**os.environ, "GH_TOKEN": token}`, a
    literal reference to the real environment mapping, so only mutating
    `os.environ` itself reaches that code path."""
    monkeypatch.setenv("PATH", f"{gh_dir}{os.pathsep}{os.environ.get('PATH', '')}")


# --------------------------------------------------------------------------
# 1. Multi-account resolution: default call fails, second configured
#    login's token succeeds. Named mutation: revert `_pr_state` to a
#    single unconditional call (no retry loop at all) -> the default
#    attempt's failure becomes the final answer -> reddens to
#    ("not_checked", True) instead of ("NONE", False).
# --------------------------------------------------------------------------


def test_multi_account_resolves_via_second_login(tmp_path, monkeypatch):
    call_log = tmp_path / "calls.log"
    gh_dir = _fake_gh_multi_account(
        tmp_path,
        accounts=[("acct-a", "success", True), ("acct-b", "success", False)],
        success_tokens={"token-acct-b"},
        call_log=call_log,
    )
    _prepend_fake_gh(monkeypatch, gh_dir)
    mod = _load_module_directly()

    state, errored = mod._pr_state(str(tmp_path), "some-branch")
    assert (state, errored) == ("NONE", False), (state, errored, _call_lines(call_log))
    assert _pr_list_call_count(call_log) == 3, _call_lines(call_log)  # default + acct-a + acct-b


# --------------------------------------------------------------------------
# 2. Positive cache: a second `_pr_state` call for a DIFFERENT branch in
#    the same repo reuses the winning env with exactly one more `pr list`
#    call (not once per account again). Named mutation: drop the positive
#    cache (`_PR_STATE_ENV_CACHE` write/read) -> the second call re-runs
#    the whole retry loop -> call count rises to 6, not 4.
# --------------------------------------------------------------------------


def test_positive_cache_reuses_winning_env(tmp_path, monkeypatch):
    call_log = tmp_path / "calls.log"
    gh_dir = _fake_gh_multi_account(
        tmp_path,
        accounts=[("acct-a", "success", True), ("acct-b", "success", False)],
        success_tokens={"token-acct-b"},
        call_log=call_log,
    )
    _prepend_fake_gh(monkeypatch, gh_dir)
    mod = _load_module_directly()

    state1, errored1 = mod._pr_state(str(tmp_path), "branch-one")
    assert (state1, errored1) == ("NONE", False)
    assert _pr_list_call_count(call_log) == 3, _call_lines(call_log)

    state2, errored2 = mod._pr_state(str(tmp_path), "branch-two")
    assert (state2, errored2) == ("NONE", False)
    assert _pr_list_call_count(call_log) == 4, _call_lines(call_log)  # exactly one more


# --------------------------------------------------------------------------
# 3. Negative cache: a repo where every configured account fails makes
#    ZERO further `gh` calls on a second entry. Named mutation: drop the
#    negative cache (`_PR_STATE_ALL_FAILED_REPOS` write/read) -> the
#    second call re-runs the whole retry loop -> call count doubles.
# --------------------------------------------------------------------------


def test_negative_cache_short_circuits_second_entry(tmp_path, monkeypatch):
    call_log = tmp_path / "calls.log"
    gh_dir = _fake_gh_multi_account(
        tmp_path,
        accounts=[("acct-a", "success", True), ("acct-b", "success", False)],
        success_tokens=set(),  # nothing ever succeeds
        call_log=call_log,
    )
    _prepend_fake_gh(monkeypatch, gh_dir)
    mod = _load_module_directly()

    state1, errored1 = mod._pr_state(str(tmp_path), "branch-one")
    assert (state1, errored1) == ("not_checked", True)
    calls_after_first = _pr_list_call_count(call_log)
    assert calls_after_first == 3, _call_lines(call_log)  # default + acct-a + acct-b

    state2, errored2 = mod._pr_state(str(tmp_path), "branch-two")
    assert (state2, errored2) == ("not_checked", True)
    assert _pr_list_call_count(call_log) == calls_after_first, _call_lines(call_log)  # zero more


# --------------------------------------------------------------------------
# 4. Revoked-account filter: an account whose `state` is not `"success"`
#    is never returned by `_gh_configured_logins` (and therefore never
#    probed). Named mutation: drop the `state != "success"` filter ->
#    the revoked login appears in the returned list -> reddens.
# --------------------------------------------------------------------------


def test_revoked_account_excluded_from_configured_logins(tmp_path, monkeypatch):
    call_log = tmp_path / "calls.log"
    gh_dir = _fake_gh_multi_account(
        tmp_path,
        accounts=[
            ("acct-active", "success", True),
            ("acct-revoked", "expired", False),
        ],
        success_tokens=set(),
        call_log=call_log,
    )
    _prepend_fake_gh(monkeypatch, gh_dir)
    mod = _load_module_directly()

    logins = mod._gh_configured_logins()
    assert logins == ["acct-active"], logins


# --------------------------------------------------------------------------
# 5. Single-account case: behavior and `gh` call count match pre-DS-217
#    behavior exactly - the default call succeeds, so the retry loop
#    never runs and `_gh_configured_logins` is never even called. Named
#    mutation: make the retry loop run unconditionally (drop the
#    `if not errored: return` early-out after the default attempt) ->
#    extra `gh auth status --json hosts` / `gh auth token` calls appear
#    even though the first attempt already succeeded -> call count rises
#    above 1.
# --------------------------------------------------------------------------


def test_single_account_call_count_unchanged(tmp_path, monkeypatch):
    call_log = tmp_path / "calls.log"
    gh_dir = _fake_gh_multi_account(
        tmp_path,
        accounts=[("acct-solo", "success", True)],
        success_tokens={""},  # default (no GH_TOKEN override) call succeeds
        call_log=call_log,
    )
    _prepend_fake_gh(monkeypatch, gh_dir)
    mod = _load_module_directly()

    state, errored = mod._pr_state(str(tmp_path), "only-branch")
    assert (state, errored) == ("NONE", False)
    assert len(_call_lines(call_log)) == 1, _call_lines(call_log)  # exactly the one pr-list call
