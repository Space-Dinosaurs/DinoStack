# Architect Plan: Path C - Real pytest execution (v3, signed off with one baked engineer constraint)

## Approach

Replace prose-based correctness approximation with real subprocess pytest invocation against the agent-edited workspace. Adds optional fields to `ticket.yaml`, a new `test_executor.py` module, a tolerant preflight viability check, and wires `test_execution` results through `runner.py` into `correctness.py` as a first-path check inside the existing dimension. The keyword fallback survives unchanged when `test_command` is null. Symmetric-dimset invariant preserved (no new dimension).

## File-by-file changes

### 1. `evals/icl_vs_orchestration/schema.py`
- Add `import re`.
- Add private `_validate_optional_test_fields(ticket, ticket_id)` covering `test_command` (non-empty str, no chars matching `[|&;<>$\`\\!(){}*?~]`, no `[` or `]` with parametrize-limitation error message), `test_pythonpath` (str, no leading `/`), `test_timeout_seconds` (int, range [5, 120]). Each violation raises `ValueError` with `ticket_id` in the message.
- Call `_validate_optional_test_fields(data, ticket_id)` at end of existing `validate_ticket()`.
- Update module manifest.

### 2. `evals/icl_vs_orchestration/test_executor.py` (NEW)
```python
def run_tests(test_command, workspace, pythonpath=".", timeout_seconds=30) -> dict:
    args = shlex.split(test_command)
    env = os.environ.copy()
    abs_pypath = str((workspace / pythonpath).resolve())
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{abs_pypath}:{existing}" if existing else abs_pypath
    t0 = time.monotonic()
    try:
        proc = subprocess.run(args, cwd=workspace, env=env, capture_output=True, text=True, timeout=timeout_seconds)
        duration = time.monotonic() - t0
        stdout_tail = (proc.stdout + proc.stderr)[-500:]
        outcome = "pass" if proc.returncode == 0 else "fail"
        return {"outcome": outcome, "returncode": proc.returncode, "stdout_tail": stdout_tail, "duration_seconds": duration, "error": None}
    except subprocess.TimeoutExpired:
        return {"outcome": "error", "returncode": None, "stdout_tail": "", "duration_seconds": float(timeout_seconds), "error": f"timed out after {timeout_seconds}s"}
    except OSError as e:
        return {"outcome": "error", "returncode": None, "stdout_tail": "", "duration_seconds": 0.0, "error": str(e)}
```
Module manifest header required (six fields per `module-manifest.md`).

### 3. `evals/icl_vs_orchestration/corpus.py`
Add `preflight_test_commands(tickets, workspace_root, log)`. For each ticket with non-null `test_command`: run `pytest --collect-only -q <test_command>` with `cwd=workspace_root`, `capture_output=True`, `text=True`, `timeout=30`.

**HARD CONSTRAINT (Skeptic r3, baked into engineer brief):** capture COMBINED stdout+stderr. Pytest emits collection-time `ImportError`/`ModuleNotFoundError` to **stdout**, not stderr. Use `combined = (proc.stdout or "") + (proc.stderr or "")` and search the combined string. Searching `stderr` alone defeats the tolerant-preflight design.

Three-branch classification:
- exit 0: pass (continue)
- exit != 0 AND `re.search(r"ImportError|ModuleNotFoundError", combined, re.IGNORECASE)`: `log.warning("preflight deferred: ticket %s test import not resolvable against baseline workspace; will validate at runtime", ticket_id)` and continue
- exit != 0 AND no import pattern in combined: `raise RuntimeError(f"preflight failed for ticket {ticket_id}: pytest --collect-only exited {returncode}; output: {combined[:500]}")`

Update module manifest.

### 4. `evals/icl_vs_orchestration/runner.py`
(a) After `condition.run()` returns and before `registry.score_result(result, ticket)` in `_run_tickets()`:
```python
test_cmd = ticket.get("test_command")
if test_cmd:
    from .test_executor import run_tests
    result["test_execution"] = run_tests(
        test_command=test_cmd,
        workspace=workspace,
        pythonpath=ticket.get("test_pythonpath", "."),
        timeout_seconds=ticket.get("test_timeout_seconds", 30),
    )
```
(b) Replace hardcoded `"correctness_method": "ac-keyword"` in `_build_report()` with detection over scored dimensions: produce `"test-execution"` if all use method `"test-pass-real"`, `"ac-keyword"` if all use that, `"mixed"` otherwise.
(c) Call `corpus.preflight_test_commands(tickets, workspace_root, log)` from `run_eval()` after `load_corpus()` and before condition construction.
(d) Update module manifest to add `test_executor` upstream dep.

### 5. `evals/icl_vs_orchestration/scoring/correctness.py`
Add at top of `score()`:
```python
test_exec = result.get("test_execution")
if test_exec is not None:
    outcome = test_exec.get("outcome")
    score_val = 1.0 if outcome == "pass" else 0.0
    return {
        "score": score_val,
        "diagnostic": {
            "method": "test-pass-real",
            "outcome": outcome,
            "returncode": test_exec.get("returncode"),
            "stdout_tail": test_exec.get("stdout_tail", "")[-200:],
            "duration_seconds": test_exec.get("duration_seconds"),
        },
        "scorer_version": SCORER_VERSION,
        "status": "scored",
    }
```
Existing keyword path unchanged as fallback. (Verified: existing returns at lines 71/86 use `"status": "scored"`.)

### 6. `corpora/replay/tickets/r-brief-tier-whole-file/ticket.yaml`
Add `test_command: "pytest evals/auto/tests/test_apply.py -x -q"`.

### 7. `corpora/replay/tickets/r-trivial-heading-parser/ticket.yaml`
Add `test_command: null` (explicit null documents intentional v1 absence).

### 8. `evals/icl_vs_orchestration/AGENTS.md`
Append to "Known limitations" section:
- v1 `test_command` validation rejects pytest parametrize node IDs (paths containing `[` or `]`). Use file-level paths only. Parametrize selectors not supported until v2.
- Resume from disk reuses stored `test_execution` without re-running preflight. V1 known limitation.
- v1 has only one viable ticket (`r-brief-tier-whole-file`) carrying `test_command`. `r-trivial-heading-parser` ships the same `test_apply.py` test file and uses keyword fallback to avoid correlated signal. Follow-up: synthesize a ticket-specific test file for `r-trivial-heading-parser` in a subsequent corpus iteration.

### 9. Tests
Per orchestration.jsonl unit `test-suite`. New: `test_test_executor.py`, `test_corpus_preflight.py`. Extend: `test_schema.py`, `test_correctness.py`, `test_runner.py`.

## QA criteria
```yaml
qa_criteria:
  qa_skip: pure-backend-library
  qa_skip_rationale: Eval harness is a python library invoked via CLI; no UI surface, no running service.
```

## Open questions
None. All round-3 findings closed; HARD CONSTRAINT for preflight stream capture baked into engineer execution contract.
