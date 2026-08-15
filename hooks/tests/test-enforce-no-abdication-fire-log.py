# Run with: python3 hooks/tests/test-enforce-no-abdication-fire-log.py
"""
Purpose: regression guard for enforce-no-abdication.py's fire-log wiring.

         This hook was the ONLY enforce-*.py hook not wired to
         hooks/lib/enforcement_log.py. It contributed zero rows to
         .agentic/.enforcement-fires.jsonl across 2026-08-03..2026-08-14
         while the other hooks contributed 1059, and its only other state
         (.agentic/.abdication-guard-fire-count) is reset to 0 on every
         clean turn, so it retained no history. Its effect was therefore
         unmeasurable in either direction and every claim about whether it
         fires - including "it never fires" - was unfalsifiable.

         These tests exist so that stays fixed. Each ALLOW/DENY assertion
         below fails if the corresponding _fire_log() call is deleted from
         the hook: the assertions read the actual JSONL rows off disk and
         require a row with the expected decision AND the expected
         discriminating `detail` fields. A test written from the fix's
         SHAPE (e.g. "the string _fire_log appears in the source") would
         pass while the exact reverted line ships - see
         hooks/AGENTS.md and the repo's regression-test discipline.

         Verified RED by deletion during authoring: removing the deny-path
         _fire_log() call fails cases 1/2/9; removing the clean-turn
         _fire_log() call fails cases 3/4/10.

Public API: run as a standalone script (the hooks/tests/test-*.py CI glob
            in .github/workflows/bin-tests.yml hooks-python-tests runs it
            via `python3 <file>`). Exits 0 on success, 1 on any failure.

Upstream deps: Python 3 stdlib only (json, os, subprocess, sys, tempfile,
               shutil, stat) plus the sibling _fire_log_test_helper.py
               (raising-log_fire soft-fail harness).

Downstream consumers: CI only.

Failure modes: each case runs the real hook as a subprocess against an
               isolated temp cwd, so cases cannot contaminate one another's
               counter file or fire log.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fire_log_test_helper import run_hook_with_raising_log_fire  # noqa: E402

HOOK_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "enforce-no-abdication.py"
)
FIRE_LOG_RELPATH = os.path.join(".agentic", ".enforcement-fires.jsonl")

# A message that trips classifier 3 (_is_prose_ballot): 2 items, neither
# carrying a recommendation marker.
BALLOT_MSG = "## Operator decisions\n\n- Ship option A?\n- Ship option B?\n"
# A message no classifier fires on.
CLEAN_MSG = "Fixed the bug and added a regression test. All quality gates pass."
# A classic permission-seeking interrogative (classifier 1).
ABDICATION_MSG = "The branch is ready. Want me to go ahead?"

_failures = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print("  [PASS] " + label)
    else:
        print("  [FAIL] " + label + ((" :: " + extra) if extra else ""))
        _failures.append(label)


def make_cwd(enabled: bool = True) -> str:
    cwd = tempfile.mkdtemp(prefix="test-abdication-firelog-")
    agentic = os.path.join(cwd, ".agentic")
    os.makedirs(agentic, exist_ok=True)
    with open(os.path.join(agentic, "config.json"), "w") as f:
        json.dump({"abdication_guard_enabled": enabled}, f)
    return cwd


def make_payload(cwd: str, message: str, **overrides) -> str:
    payload = {
        "hook_event_name": "Stop",
        "session_id": "test-abdication-firelog",
        "cwd": cwd,
        "stop_hook_active": False,
        "permission_mode": "default",
        "last_assistant_message": message,
    }
    payload.update(overrides)
    return json.dumps(payload)


def run_hook(cwd: str, payload: str, extra_env: dict | None = None):
    env = os.environ.copy()
    env.pop("AE_ABDICATION_GUARD_DISABLE", None)
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )
    return result.returncode, result.stdout, result.stderr


def read_rows(cwd: str) -> list:
    path = os.path.join(cwd, FIRE_LOG_RELPATH)
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                rows.append({"_unparseable": line})
    return rows


# ---------------------------------------------------------------------------
# 1-2, 9: DENY path logs
# ---------------------------------------------------------------------------


def test_deny_path_logs() -> None:
    print("\nDeny path (prose ballot -> block):")
    cwd = make_cwd()
    rc, stdout, _ = run_hook(cwd, make_payload(cwd, BALLOT_MSG))

    verdict = json.loads(stdout) if stdout.strip() else None
    check(
        "1. hook still BLOCKS (verdict unchanged by the added logging)",
        verdict is not None and verdict.get("decision") == "block",
        "stdout=%r" % stdout[:120],
    )

    rows = read_rows(cwd)
    deny_rows = [r for r in rows if r.get("decision") == "deny"]
    check(
        "2. exactly one 'deny' row written to .enforcement-fires.jsonl",
        len(deny_rows) == 1,
        "rows=%r" % rows,
    )
    if not deny_rows:
        return
    row = deny_rows[0]
    check(
        "9. deny row carries hook name, ts, reason and a detail object",
        row.get("hook") == "enforce-no-abdication"
        and isinstance(row.get("ts"), str)
        and row["ts"].endswith("Z")
        and isinstance(row.get("reason"), str)
        and row["reason"]
        and isinstance(row.get("detail"), dict),
        "row=%r" % row,
    )
    detail = row.get("detail", {})
    check(
        "9b. deny detail identifies WHICH classifier fired (c3_ballot)",
        detail.get("c3_ballot") is True
        and detail.get("fired") == "ballot"
        and detail.get("c1_abdication") is False
        and detail.get("c2_stall") is False,
        "detail=%r" % detail,
    )
    check(
        "9c. deny detail records the ballot shape that produced the verdict",
        detail.get("decisions_heading") is True
        and detail.get("decision_items") == 2
        and detail.get("unrecommended_items") == 2,
        "detail=%r" % detail,
    )


# ---------------------------------------------------------------------------
# 3-4, 10: ALLOW path logs (the datum a deny-only log cannot provide)
# ---------------------------------------------------------------------------


def test_allow_path_logs() -> None:
    print("\nAllow path (clean turn -> no block):")
    cwd = make_cwd()
    rc, stdout, _ = run_hook(cwd, make_payload(cwd, CLEAN_MSG))

    check(
        "3. hook still ALLOWS with empty stdout (verdict unchanged)",
        rc == 0 and stdout.strip() == "",
        "rc=%d stdout=%r" % (rc, stdout[:120]),
    )

    rows = read_rows(cwd)
    allow_rows = [r for r in rows if r.get("decision") == "allow"]
    check(
        "4. exactly one 'allow' row written on a clean turn",
        len(allow_rows) == 1,
        "rows=%r" % rows,
    )
    if not allow_rows:
        return
    detail = allow_rows[0].get("detail", {})
    check(
        "10. allow row records the classified path with all three "
        "classifier verdicts False",
        detail.get("path") == "classified"
        and detail.get("c1_abdication") is False
        and detail.get("c2_stall") is False
        and detail.get("c3_ballot") is False,
        "detail=%r" % detail,
    )
    check(
        "10b. allow row distinguishes 'no decisions block present' from "
        "'a compliant one was present'",
        detail.get("decisions_heading") is False
        and detail.get("decision_items") == 0,
        "detail=%r" % detail,
    )


def test_compliant_ballot_allow_is_distinguishable() -> None:
    """The central question this whole change exists to answer: does the
    canonical decisions-block shape reach a classifier at all? A compliant
    block must produce an ALLOW row that PROVES the block was seen."""
    print("\nAllow path (compliant Operator decisions block):")
    cwd = make_cwd()
    msg = (
        "## Operator decisions\n\n"
        "- Ship option A. Recommendation: yes, it matches the existing pattern.\n"
        "- Ship option B (Recommended)\n"
    )
    rc, stdout, _ = run_hook(cwd, make_payload(cwd, msg))
    check(
        "5. compliant ballot still ALLOWS (verdict unchanged)",
        rc == 0 and stdout.strip() == "",
        "stdout=%r" % stdout[:120],
    )
    rows = [r for r in read_rows(cwd) if r.get("decision") == "allow"]
    detail = rows[0].get("detail", {}) if rows else {}
    check(
        "5b. the allow row PROVES the heading reached classifier 3 "
        "(heading seen, 2 items, 0 unrecommended)",
        detail.get("decisions_heading") is True
        and detail.get("decision_items") == 2
        and detail.get("unrecommended_items") == 0
        and detail.get("c3_ballot") is False,
        "detail=%r" % detail,
    )


# ---------------------------------------------------------------------------
# 6: negative-gate suppression is recorded, WITH the suppressing token
# ---------------------------------------------------------------------------


def test_negative_gate_token_recorded() -> None:
    print("\nNegative-gate suppression recording:")
    cwd = make_cwd()
    msg = "This is irreversible and cannot be undone. Want me to go ahead?"
    rc, stdout, _ = run_hook(cwd, make_payload(cwd, msg))
    check(
        "6. hard-gated interrogative still ALLOWS (verdict unchanged)",
        rc == 0 and stdout.strip() == "",
        "stdout=%r" % stdout[:120],
    )
    rows = [r for r in read_rows(cwd) if r.get("decision") == "allow"]
    detail = rows[0].get("detail", {}) if rows else {}
    check(
        "6b. allow row records hard_gate=True, the permission phrase that "
        "was present, and WHICH token suppressed it",
        detail.get("hard_gate") is True
        and detail.get("permission_phrase") is True
        and detail.get("c1_abdication") is False
        and isinstance(detail.get("gate_token"), str)
        and detail["gate_token"] in ("irreversible", "cannot be undone"),
        "detail=%r" % detail,
    )


def test_gate_token_never_leaks_pii() -> None:
    """The two co-occurrence gates match a bare email regex and a dollar
    amount. gate_token must report a category label for those, never the
    matched text - this file has no redaction layer."""
    print("\nPII boundary on gate_token:")
    for msg, label, leak in (
        (
            "Sending the summary to alice@example.com now. Want me to continue?",
            "<external-message co-occurrence>",
            "alice@example.com",
        ),
        (
            "Approving this will spend $4200 of credits. Should I proceed?",
            "<spend co-occurrence>",
            "$4200",
        ),
    ):
        cwd = make_cwd()
        run_hook(cwd, make_payload(cwd, msg))
        rows = [r for r in read_rows(cwd) if r.get("decision") == "allow"]
        detail = rows[0].get("detail", {}) if rows else {}
        blob = json.dumps(rows)
        check(
            "7. gate_token is the category label %r, not the matched text" % label,
            detail.get("gate_token") == label,
            "detail=%r" % detail,
        )
        check(
            "7b. the literal %r never appears anywhere in the log row" % leak,
            leak not in blob,
            "blob=%r" % blob[:200],
        )


# ---------------------------------------------------------------------------
# 8: an inert guard must write NOTHING
# ---------------------------------------------------------------------------


def test_no_rows_when_guard_inert() -> None:
    print("\nInert-guard paths write no rows:")
    # (a) config present but abdication_guard_enabled: false
    cwd = make_cwd(enabled=False)
    run_hook(cwd, make_payload(cwd, BALLOT_MSG))
    check(
        "8. guard disabled in config -> zero fire-log rows",
        read_rows(cwd) == [],
        "rows=%r" % read_rows(cwd),
    )

    # (b) kill switch
    cwd = make_cwd()
    run_hook(cwd, make_payload(cwd, BALLOT_MSG), {"AE_ABDICATION_GUARD_DISABLE": "1"})
    check(
        "8b. kill switch set -> zero fire-log rows",
        read_rows(cwd) == [],
        "rows=%r" % read_rows(cwd),
    )

    # (c) stop_hook_active re-entrancy guard
    cwd = make_cwd()
    run_hook(cwd, make_payload(cwd, BALLOT_MSG, stop_hook_active=True))
    check(
        "8c. stop_hook_active -> zero fire-log rows",
        read_rows(cwd) == [],
        "rows=%r" % read_rows(cwd),
    )

    # (d) no config file at all
    cwd = tempfile.mkdtemp(prefix="test-abdication-firelog-noconfig-")
    run_hook(cwd, make_payload(cwd, BALLOT_MSG))
    check(
        "8d. no .agentic/config.json -> zero fire-log rows",
        read_rows(cwd) == [],
        "rows=%r" % read_rows(cwd),
    )


# ---------------------------------------------------------------------------
# 11-13: SOFT-FAIL - a broken log path must never change the verdict
# ---------------------------------------------------------------------------


def test_raising_log_fire_does_not_suppress_verdict() -> None:
    print("\nSoft-fail: log_fire raises unconditionally:")
    cwd = make_cwd()
    rc, stdout, stderr = run_hook_with_raising_log_fire(
        "enforce-no-abdication.py",
        make_payload(cwd, BALLOT_MSG),
        cwd=cwd,
        extra_env={"AE_ABDICATION_GUARD_DISABLE": ""},
    )
    verdict = json.loads(stdout) if stdout.strip() else None
    check(
        "11. a raising log_fire still emits the BLOCK verdict unchanged",
        rc == 0 and verdict is not None and verdict.get("decision") == "block",
        "rc=%d stdout=%r stderr=%r" % (rc, stdout[:160], stderr[:160]),
    )

    cwd2 = make_cwd()
    rc2, stdout2, stderr2 = run_hook_with_raising_log_fire(
        "enforce-no-abdication.py",
        make_payload(cwd2, CLEAN_MSG),
        cwd=cwd2,
        extra_env={"AE_ABDICATION_GUARD_DISABLE": ""},
    )
    check(
        "11b. a raising log_fire still emits the ALLOW verdict unchanged",
        rc2 == 0 and stdout2.strip() == "",
        "rc=%d stdout=%r stderr=%r" % (rc2, stdout2[:160], stderr2[:160]),
    )


def test_unwritable_log_dir_does_not_change_verdict() -> None:
    """Deliberately break the log path itself (read-only .agentic/) and
    confirm the hook still returns its normal verdict."""
    print("\nSoft-fail: .agentic/ made read-only after config write:")
    for msg, expect_block, label in (
        (BALLOT_MSG, True, "BLOCK"),
        (CLEAN_MSG, False, "ALLOW"),
    ):
        cwd = make_cwd()
        agentic = os.path.join(cwd, ".agentic")
        original_mode = stat.S_IMODE(os.stat(agentic).st_mode)
        os.chmod(agentic, 0o500)  # r-x: readable (config) but not writable
        try:
            rc, stdout, stderr = run_hook(cwd, make_payload(cwd, msg))
        finally:
            os.chmod(agentic, original_mode)

        if expect_block:
            # The counter write also fails here, and the hook's documented
            # pre-existing behavior is to ALLOW when the loop bound cannot
            # be persisted. The point under test is that it does not crash,
            # does not emit garbage, and exits 0 either way.
            ok = rc == 0 and (stdout.strip() == "" or json.loads(stdout).get("decision") == "block")
        else:
            ok = rc == 0 and stdout.strip() == ""
        check(
            "12. unwritable .agentic/ -> exit 0 and no garbage stdout (%s case)"
            % label,
            ok,
            "rc=%d stdout=%r stderr=%r" % (rc, stdout[:160], stderr[:160]),
        )


def test_bad_detail_still_writes_canonical_row() -> None:
    """enforcement_log.log_fire must degrade a non-serializable `detail`
    to the canonical 4-field line rather than losing the row."""
    print("\nlog_fire detail degradation:")
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")
    )
    import importlib.util

    lib_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "lib", "enforcement_log.py"
    )
    spec = importlib.util.spec_from_file_location("enforcement_log_t", lib_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    cwd = tempfile.mkdtemp(prefix="test-abdication-firelog-detail-")
    mod.log_fire({"cwd": cwd}, "test-hook", "allow", "r", detail={"bad": object()})
    rows = read_rows(cwd)
    check(
        "13. non-serializable detail -> canonical 4-field row still written",
        len(rows) == 1
        and set(rows[0].keys()) == {"ts", "hook", "decision", "reason"},
        "rows=%r" % rows,
    )

    cwd2 = tempfile.mkdtemp(prefix="test-abdication-firelog-detail2-")
    mod.log_fire({"cwd": cwd2}, "test-hook", "allow", "r")
    rows2 = read_rows(cwd2)
    check(
        "13b. omitted detail -> line byte-identical to the pre-change "
        "4-field schema",
        len(rows2) == 1 and set(rows2[0].keys()) == {"ts", "hook", "decision", "reason"},
        "rows=%r" % rows2,
    )


# ---------------------------------------------------------------------------
# 14: the cap and no-message allow paths log too
# ---------------------------------------------------------------------------


def test_cap_reached_path_logs() -> None:
    print("\nCap-reached allow path:")
    cwd = make_cwd()
    # Drive the counter to the cap by blocking twice on the same user turn.
    for _ in range(2):
        run_hook(cwd, make_payload(cwd, BALLOT_MSG))
    rows_before = len(read_rows(cwd))
    rc, stdout, _ = run_hook(cwd, make_payload(cwd, BALLOT_MSG))
    rows = read_rows(cwd)
    check(
        "14. third consecutive block is capped -> ALLOW (behavior unchanged)",
        rc == 0 and stdout.strip() == "",
        "stdout=%r" % stdout[:120],
    )
    capped = [
        r
        for r in rows[rows_before:]
        if r.get("decision") == "allow"
        and r.get("detail", {}).get("path") == "cap_reached"
    ]
    check(
        "14b. the capped turn is logged as allow/path=cap_reached",
        len(capped) == 1,
        "new rows=%r" % rows[rows_before:],
    )


def main() -> None:
    print("Fire-log wiring regression tests for enforce-no-abdication.py")
    test_deny_path_logs()
    test_allow_path_logs()
    test_compliant_ballot_allow_is_distinguishable()
    test_negative_gate_token_recorded()
    test_gate_token_never_leaks_pii()
    test_no_rows_when_guard_inert()
    test_raising_log_fire_does_not_suppress_verdict()
    test_unwritable_log_dir_does_not_change_verdict()
    test_bad_detail_still_writes_canonical_row()
    test_cap_reached_path_logs()

    print()
    if _failures:
        print("%d assertion(s) FAILED:" % len(_failures))
        for f in _failures:
            print("  - " + f)
        sys.exit(1)
    print("All fire-log wiring tests passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
