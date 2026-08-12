"""
Purpose: Deliberate, reviewable regeneration tool for
         bin/tests/fixtures/agent_return_contract/expected_violations_snapshot.json
         - the per-file exact-violations snapshot that
         test_agent_return_contract_spec.py's
         test_expected_violations_snapshot_matches_reality asserts against.
         This script exists so a snapshot update is never a silent
         one-command refresh: by DEFAULT it only prints a diff between the
         live checker's output and the committed snapshot and exits
         non-zero if they differ - it never writes the file unless given
         --write, and --write still prints the full diff first so the
         change is visible in the PR that carries it.

Public API: main() (CLI entry point: `python3
            bin/tests/generate_agent_return_contract_snapshot.py [--write]`).

Upstream dependencies: test_agent_return_contract_spec.py (SHAPE_ASSIGNMENTS,
            EXEMPT_FILE_ARTIFACT, check_contract - the same dispatch the spec
            gate itself uses, so this script can never drift from what the
            gate actually checks); content/agents/*.md (the real corpus).

Downstream consumers: a human operator, run manually when a deliberate
            agent-file migration or checker fix is expected to change the
            violation set for one or more files.
            HOW TO UPDATE THE SNAPSHOT (deliberate, reviewed procedure):
              1. Make the intended change (migrate an agent file's return
                 section, or fix a checker defect).
              2. Run `python3 bin/tests/generate_agent_return_contract_snapshot.py`
                 with NO flags - this prints a per-file diff of what changed
                 and exits 1 if there is any difference. Read the diff:
                 confirm every file that shows a change is one you intended
                 to change, and confirm the new violation text for each
                 file is what you expect (a file's violations disappearing
                 entirely is a MIGRATION being reflected; new violations
                 appearing on a file you didn't touch is a checker
                 regression, not a snapshot update).
              3. Only after reviewing that diff, re-run with `--write` to
                 regenerate the JSON file, then include the diff in the
                 PR description so a reviewer can see exactly what
                 widened/narrowed and why, in the same review as the code
                 change that caused it.
            This script is intentionally NOT wired into any CI job or
            pre-commit hook - the snapshot only ever changes via an
            explicit, reviewed human invocation of this exact procedure.

Failure modes: exits 1 (no write) when run without --write and the live
            checker output differs from the committed snapshot - this is
            the expected/desired behavior for the CI-facing check
            (test_expected_violations_snapshot_matches_reality calls the
            same computation in-process, not this script, but this script
            gives a human the same view proactively). Exits 0 after a
            successful --write.

Performance: negligible - reads <30 small text files.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_agent_return_contract_spec as contract  # noqa: E402

SNAPSHOT_PATH = (
    contract.FIXTURES_DIR / "expected_violations_snapshot.json"
)


def compute_live_violations():
    """Return {filename: [violation, ...]} for every file in
    SHAPE_ASSIGNMENTS (EXEMPT_FILE_ARTIFACT files carry no shape and are
    not snapshotted - their exemption is asserted by a separate test)."""
    result = {}
    for name in sorted(contract.SHAPE_ASSIGNMENTS):
        path = contract.AGENTS_DIR / name
        result[name] = contract.check_contract(path.read_text(), name)
    return result


def load_committed_snapshot():
    if not SNAPSHOT_PATH.exists():
        return {}
    return json.loads(SNAPSHOT_PATH.read_text())


def diff_snapshots(committed, live):
    """Return a human-readable diff report string, or '' if identical."""
    lines = []
    all_names = sorted(set(committed) | set(live))
    for name in all_names:
        old = committed.get(name)
        new = live.get(name)
        if old == new:
            continue
        lines.append(f"=== {name} ===")
        if old is None:
            lines.append("  (new entry - file not previously snapshotted)")
        else:
            for v in old:
                if v not in (new or []):
                    lines.append(f"  - {v}")
        if new is None:
            lines.append("  (entry removed - file no longer shape-assigned)")
        else:
            for v in new:
                if v not in (old or []):
                    lines.append(f"  + {v}")
    return "\n".join(lines)


def main():
    write = "--write" in sys.argv
    live = compute_live_violations()
    committed = load_committed_snapshot()
    diff = diff_snapshots(committed, live)
    if not diff:
        print("expected_violations_snapshot.json matches the live checker "
              "output - no changes.")
        return 0
    print("The live checker output differs from the committed snapshot:")
    print(diff)
    print()
    if not write:
        print(
            "Not written (no --write flag). Review the diff above: every "
            "changed file must be one you intended to change, and the new "
            "violation text for each must be what you expect. Re-run with "
            "--write only after that review, and include this diff in the "
            "PR description."
        )
        return 1
    SNAPSHOT_PATH.write_text(
        json.dumps(live, indent=2, sort_keys=True) + "\n"
    )
    print(f"Written: {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
