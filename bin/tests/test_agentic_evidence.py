#!/usr/bin/env python3
"""
Tests for agentic-evidence: the evidence spill/sketch/rehydrate CLI.

Subcommands: spill [FILE] [--label] [--tool] [--status] [--evidence-dir]
             sketch [--evidence-dir]
             get <node-id> [--evidence-dir]
             prune (--all | --older-than HOURS) [--evidence-dir]

Run with: python3 -m pytest bin/tests/test_agentic_evidence.py -x
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

_BIN_PATH = Path(__file__).parent.parent / "agentic-evidence"
_loader = importlib.machinery.SourceFileLoader("agentic_evidence", str(_BIN_PATH))
_spec = importlib.util.spec_from_loader("agentic_evidence", _loader)
if _spec is None:
    raise RuntimeError(f"Cannot build spec for agentic-evidence from {_BIN_PATH}")
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)


def _capture(fn, args_ns, cwd, stdin_bytes=None) -> tuple[int, str, str]:
    """Run fn(args_ns) with cwd chdir'd; capture stdout/stderr (and stdin)."""
    old_cwd = os.getcwd()
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    old_stdin = sys.stdin
    out_cap = StringIO()
    err_cap = StringIO()
    sys.stdout = out_cap
    sys.stderr = err_cap
    if stdin_bytes is not None:
        sys.stdin = io.TextIOWrapper(io.BytesIO(stdin_bytes))
    try:
        os.chdir(cwd)
        rc = fn(args_ns)
    finally:
        os.chdir(old_cwd)
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        sys.stdin = old_stdin
    return rc, out_cap.getvalue(), err_cap.getvalue()


def _spill_args(
    file=None, label="unlabeled", tool="unknown", status="ok", evidence_dir=None
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        file=file, label=label, tool=tool, status=status, evidence_dir=evidence_dir
    )


def _sketch_args(evidence_dir=None) -> types.SimpleNamespace:
    return types.SimpleNamespace(evidence_dir=evidence_dir)


def _get_args(node_id: str, evidence_dir=None) -> types.SimpleNamespace:
    return types.SimpleNamespace(node_id=node_id, evidence_dir=evidence_dir)


def _prune_args(all_=False, older_than=None, evidence_dir=None) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        all=all_, older_than=older_than, evidence_dir=evidence_dir
    )


def _write_node(root, seq, label, tool, chars, ts, status, raw: bytes) -> None:
    """Write a node file in the exact binding format (hand-crafted)."""
    root.mkdir(parents=True, exist_ok=True)
    header = (
        f"<!-- ae-node: n{seq} | label: {label} | tool: {tool} | "
        f"chars: {chars} | ts: {ts} | status: {status} -->"
    )
    (root / f"n{seq}.md").write_bytes(header.encode("utf-8") + b"\n--- raw ---\n" + raw)


def _assert_sketch_line_shape(line: str) -> re.Match:
    m = re.match(
        r"^- n(\d+) \| label: (.*) \| tool: (.*) \| chars: (\d+) \| "
        r"ts: (.*) \| status: (.*)$",
        line,
    )
    assert m, f"sketch line does not match shared binding contract: {line!r}"
    return m


def test_spill_from_file():
    """spill FILE -> node written with header + verbatim raw; sketch line printed."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        evidence = root / "evidence"
        raw = "line one\nline two\n"
        src = root / "input.txt"
        src.write_text(raw)
        args = _spill_args(
            file=str(src), label="my label", tool="bash", status="ok",
            evidence_dir=str(evidence),
        )
        rc, out, err = _capture(_mod.cmd_spill, args, root)
        assert rc == 0, f"rc={rc} err={err!r}"
        node = evidence / "n1.md"
        assert node.is_file()
        text = node.read_text()
        assert "<!-- ae-node: n1 | label: my label | tool: bash |" in text
        assert "--- raw ---" in text
        assert text.endswith(raw)
        m = _assert_sketch_line_shape(out.strip())
        assert m.group(1) == "1"
        assert m.group(2) == "my label"
        assert m.group(3) == "bash"
        assert m.group(4) == str(len(raw))
        assert m.group(6) == "ok"
    print("PASS test_spill_from_file")


def test_spill_from_stdin():
    """spill with no FILE reads stdin and writes a node."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        evidence = root / "evidence"
        args = _spill_args(
            file=None, label="stdin-node", tool="bash", status="ok",
            evidence_dir=str(evidence),
        )
        rc, out, err = _capture(_mod.cmd_spill, args, root, stdin_bytes=b"from stdin\n")
        assert rc == 0, f"rc={rc} err={err!r}"
        node = evidence / "n1.md"
        assert node.is_file()
        assert node.read_text().endswith("from stdin\n")
        assert "- n1 | label: stdin-node" in out
    print("PASS test_spill_from_stdin")


def test_spill_seq_monotonicity():
    """seq = max existing seq + 1 (fresh dir -> n1,n2; pre-seeded n1,n3 -> n4)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        evidence = root / "evidence"
        for i, label in enumerate(["a", "b"], 1):
            args = _spill_args(
                file=None, label=label, tool="bash", status="ok",
                evidence_dir=str(evidence),
            )
            rc, out, err = _capture(_mod.cmd_spill, args, root, stdin_bytes=b"x\n")
            assert rc == 0, err
            assert out.startswith(f"- n{i} |")
        assert (evidence / "n1.md").is_file()
        assert (evidence / "n2.md").is_file()

        seed = root / "seed"
        _write_node(seed, 1, "a", "bash", "3", "2026-08-05T12:00:00Z", "ok", b"abc")
        _write_node(seed, 3, "b", "bash", "3", "2026-08-05T12:00:00Z", "ok", b"def")
        args = _spill_args(
            file=None, label="c", tool="bash", status="ok", evidence_dir=str(seed)
        )
        rc, out, err = _capture(_mod.cmd_spill, args, root, stdin_bytes=b"ghi")
        assert rc == 0, err
        assert out.startswith("- n4 |")
        assert (seed / "n4.md").is_file()
    print("PASS test_spill_seq_monotonicity")


def test_get_exact_bytes_round_trip():
    """get prints the spilled raw byte-for-byte."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        evidence = root / "evidence"
        raw = "first line\nsecond line\nthird line\n"
        args = _spill_args(
            file=None, label="rt", tool="bash", status="ok", evidence_dir=str(evidence)
        )
        rc, _, err = _capture(_mod.cmd_spill, args, root, stdin_bytes=raw.encode())
        assert rc == 0, err
        rc, out, err = _capture(_mod.cmd_get, _get_args("n1", str(evidence)), root)
        assert rc == 0, err
        assert out == raw, f"round-trip mismatch: {out!r} != {raw!r}"
    print("PASS test_get_exact_bytes_round_trip")


def test_sketch_numeric_order_and_metadata():
    """sketch orders nodes by numeric seq and emits correct metadata."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        evidence = root / "evidence"
        _write_node(evidence, 2, "second", "curl", "5", "2026-08-05T12:02:00Z", "ok", b"xxxxx")
        _write_node(evidence, 10, "tenth", "bash", "4", "2026-08-05T12:03:00Z", "err", b"xxxx")
        _write_node(evidence, 1, "first", "rg", "3", "2026-08-05T12:01:00Z", "ok", b"xxx")
        rc, out, err = _capture(_mod.cmd_sketch, _sketch_args(str(evidence)), root)
        assert rc == 0, err
        lines = out.splitlines()
        assert lines[0] == "## Evidence sketch (3 nodes, ~12 chars spilled)"
        assert lines[1] == "- n1 | label: first | tool: rg | chars: 3 | ts: 2026-08-05T12:01:00Z | status: ok"
        assert lines[2] == "- n2 | label: second | tool: curl | chars: 5 | ts: 2026-08-05T12:02:00Z | status: ok"
        assert lines[3] == "- n10 | label: tenth | tool: bash | chars: 4 | ts: 2026-08-05T12:03:00Z | status: err"
    print("PASS test_sketch_numeric_order_and_metadata")


def test_prune_all():
    """prune --all removes every node and reports the count."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        evidence = root / "evidence"
        _write_node(evidence, 1, "a", "bash", "3", "2026-08-05T12:00:00Z", "ok", b"abc")
        _write_node(evidence, 2, "b", "bash", "3", "2026-08-05T12:00:00Z", "ok", b"def")
        rc, out, err = _capture(
            _mod.cmd_prune, _prune_args(all_=True, older_than=None, evidence_dir=str(evidence)), root
        )
        assert rc == 0, err
        assert out.strip() == "removed 2 node(s)"
        assert not list(evidence.iterdir())
    print("PASS test_prune_all")


def test_prune_older_than():
    """prune --older-than removes only nodes older than the cutoff."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        evidence = root / "evidence"
        now = datetime.now(timezone.utc)
        old_ts = (now - timedelta(hours=96)).strftime("%Y-%m-%dT%H:%M:%SZ")
        recent_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_node(evidence, 1, "old", "bash", "3", old_ts, "ok", b"abc")
        _write_node(evidence, 2, "new", "bash", "3", recent_ts, "ok", b"def")
        rc, out, err = _capture(
            _mod.cmd_prune, _prune_args(all_=False, older_than=48, evidence_dir=str(evidence)), root
        )
        assert rc == 0, err
        assert out.strip() == "removed 1 node(s)"
        assert not (evidence / "n1.md").exists()
        assert (evidence / "n2.md").exists()
    print("PASS test_prune_older_than")


def test_get_missing_node_exit_2():
    """get on a missing node -> stderr error + exit 2."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        evidence = root / "evidence"
        evidence.mkdir(parents=True)
        rc, out, err = _capture(_mod.cmd_get, _get_args("n99", str(evidence)), root)
        assert rc == 2
        assert "Error" in err and "n99" in err
    print("PASS test_get_missing_node_exit_2")


def test_sketch_empty_dir_exit_0():
    """sketch on a missing/empty dir -> '0 nodes', exit 0."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        missing = root / "does-not-exist"
        rc, out, err = _capture(_mod.cmd_sketch, _sketch_args(str(missing)), root)
        assert rc == 0, err
        assert "0 nodes" in out
    print("PASS test_sketch_empty_dir_exit_0")


def test_evidence_dir_override():
    """--evidence-dir is honored even when CWD has no .git ancestor."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        custom = root / "custom" / "evidence"
        rc, out, err = _capture(
            _mod.cmd_spill,
            _spill_args(file=None, label="o", tool="bash", status="ok", evidence_dir=str(custom)),
            root,
            stdin_bytes=b"data\n",
        )
        assert rc == 0, err
        assert (custom / "n1.md").is_file()
        rc, out, err = _capture(_mod.cmd_sketch, _sketch_args(str(custom)), root)
        assert rc == 0
        assert "1 nodes" in out
    print("PASS test_evidence_dir_override")


def test_git_directory_anchoring():
    """nearest .git DIRECTORY ancestor anchors the evidence root."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".git").mkdir()
        sub = root / "sub"
        sub.mkdir()
        rc, out, err = _capture(
            _mod.cmd_spill,
            _spill_args(file=None, label="anchor", tool="bash", status="ok", evidence_dir=None),
            sub,
            stdin_bytes=b"data\n",
        )
        assert rc == 0, err
        node = root / ".agentic" / "evidence" / "n1.md"
        assert node.is_file(), f"node not anchored under .git dir: {err!r}"
    print("PASS test_git_directory_anchoring")


def test_git_file_anchoring():
    """.git FILE whose first line starts 'gitdir:' anchors (isolation worktree)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".git").write_text(
            "gitdir: /fake/main-worktree/.git/worktrees/evidence-wt\n"
        )
        sub = root / "sub"
        sub.mkdir()
        rc, out, err = _capture(
            _mod.cmd_spill,
            _spill_args(file=None, label="wt", tool="bash", status="ok", evidence_dir=None),
            sub,
            stdin_bytes=b"data\n",
        )
        assert rc == 0, err
        node = root / ".agentic" / "evidence" / "n1.md"
        assert node.is_file(), f"node not anchored under gitdir: file: {err!r}"
    print("PASS test_git_file_anchoring")


def test_separator_collision():
    """A literal '--- raw ---' inside the raw body must round-trip byte-exact."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        evidence = root / "evidence"
        raw = "line one\n--- raw ---\nline two\n"
        rc, _, err = _capture(
            _mod.cmd_spill,
            _spill_args(file=None, label="collision", tool="bash", status="ok", evidence_dir=str(evidence)),
            root,
            stdin_bytes=raw.encode(),
        )
        assert rc == 0, err
        rc, out, err = _capture(_mod.cmd_get, _get_args("n1", str(evidence)), root)
        assert rc == 0, err
        assert out == raw, f"separator collision broke round-trip: {out!r} != {raw!r}"
    print("PASS test_separator_collision")


def test_symlink_invocation():
    """Real os.symlink + subprocess (DS-66 regression guard: self-contained)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_bin = tmp_path / "local-bin"
        fake_bin.mkdir()
        symlink_path = fake_bin / "agentic-evidence"
        os.symlink(_BIN_PATH.resolve(), symlink_path)

        result = subprocess.run(
            [str(symlink_path), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"--help through symlink rc={result.returncode}: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "_lib.py" not in result.stderr
        assert "Traceback" not in result.stderr

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        src = tmp_path / "src.txt"
        src.write_text("symlink spill\n")
        result = subprocess.run(
            [str(symlink_path), "spill", str(src), "--label", "sym",
             "--tool", "bash", "--status", "ok"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"spill through symlink failed: {result.stderr!r}"
        assert (repo / ".agentic" / "evidence" / "n1.md").is_file()
    print("PASS test_symlink_invocation")


def test_sketch_shared_contract_format():
    """The per-node sketch line matches the shared binding contract byte-for-byte."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        evidence = root / "evidence"
        _write_node(evidence, 1, "rg TODO scan", "bash", "4120", "2026-08-05T12:00:00Z", "ERR", b"x" * 4120)
        _write_node(evidence, 2, "second", "curl", "77", "2026-08-05T12:01:00Z", "ok", b"y" * 77)
        rc, out, err = _capture(_mod.cmd_sketch, _sketch_args(str(evidence)), root)
        assert rc == 0, err
        lines = out.splitlines()
        assert lines[0] == "## Evidence sketch (2 nodes, ~4197 chars spilled)"
        assert lines[1] == (
            "- n1 | label: rg TODO scan | tool: bash | chars: 4120 | "
            "ts: 2026-08-05T12:00:00Z | status: ERR"
        )
        assert lines[2] == (
            "- n2 | label: second | tool: curl | chars: 77 | "
            "ts: 2026-08-05T12:01:00Z | status: ok"
        )
    print("PASS test_sketch_shared_contract_format")


def test_sketch_degrade_unparseable_header():
    """Nodes with unparseable headers degrade to label: unlabeled."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        evidence = root / "evidence"
        evidence.mkdir(parents=True)
        (evidence / "n1.md").write_text("not a valid header\n--- raw ---\nbody\n")
        _write_node(evidence, 2, "good", "bash", "4", "2026-08-05T12:00:00Z", "ok", b"body")
        rc, out, err = _capture(_mod.cmd_sketch, _sketch_args(str(evidence)), root)
        assert rc == 0
        lines = out.splitlines()
        assert "label: unlabeled" in lines[1]
        assert "label: good" in lines[2]
    print("PASS test_sketch_degrade_unparseable_header")


def test_sketch_warns_over_40():
    """sketch emits a non-blocking stderr warning when N > 40."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        evidence = root / "evidence"
        for i in range(1, 42):
            _write_node(evidence, i, f"label{i}", "bash", "5", "2026-08-05T12:00:00Z", "ok", b"x" * 5)
        rc, out, err = _capture(_mod.cmd_sketch, _sketch_args(str(evidence)), root)
        assert rc == 0
        assert "41 nodes" in out
        assert "Warning" in err
    print("PASS test_sketch_warns_over_40")


def test_spill_missing_file_exit_2():
    """spill on a missing FILE -> stderr error + exit 2."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rc, out, err = _capture(
            _mod.cmd_spill,
            _spill_args(file=str(root / "missing.txt"), label="x", tool="bash", status="ok", evidence_dir=str(root / "ev")),
            root,
        )
        assert rc == 2
        assert "Error" in err
    print("PASS test_spill_missing_file_exit_2")


def test_spill_empty_stdin_exit_2():
    """spill on empty stdin -> stderr error + exit 2."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rc, out, err = _capture(
            _mod.cmd_spill,
            _spill_args(file=None, label="x", tool="bash", status="ok", evidence_dir=str(root / "ev")),
            root,
            stdin_bytes=b"",
        )
        assert rc == 2
        assert "Error" in err
    print("PASS test_spill_empty_stdin_exit_2")


def test_prune_missing_dir_exit_0():
    """prune on a missing dir -> 'removed 0 node(s)', exit 0."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        missing = root / "no-such-evidence"
        rc, out, err = _capture(
            _mod.cmd_prune,
            _prune_args(all_=True, older_than=None, evidence_dir=str(missing)),
            root,
        )
        assert rc == 0, err
        assert out.strip() == "removed 0 node(s)"
    print("PASS test_prune_missing_dir_exit_0")


def test_version_and_help():
    """--version and --help both work."""
    result = subprocess.run(
        [sys.executable, str(_BIN_PATH), "--version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"rc={result.returncode}: {result.stderr!r}"
    assert "agentic-evidence 0.1.0" in result.stdout

    result = subprocess.run(
        [sys.executable, str(_BIN_PATH), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "spill" in result.stdout
    assert "sketch" in result.stdout
    assert "prune" in result.stdout
    print("PASS test_version_and_help")


def test_get_invalid_node_id_exit_2():
    """get on a non-n<seq> node id -> stderr error + exit 2."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rc, out, err = _capture(
            _mod.cmd_get, _get_args("bogus", str(root / "ev")), root
        )
        assert rc == 2
        assert "Error" in err
    print("PASS test_get_invalid_node_id_exit_2")


if __name__ == "__main__":
    _tests = [
        test_spill_from_file,
        test_spill_from_stdin,
        test_spill_seq_monotonicity,
        test_get_exact_bytes_round_trip,
        test_sketch_numeric_order_and_metadata,
        test_prune_all,
        test_prune_older_than,
        test_get_missing_node_exit_2,
        test_sketch_empty_dir_exit_0,
        test_evidence_dir_override,
        test_git_directory_anchoring,
        test_git_file_anchoring,
        test_separator_collision,
        test_symlink_invocation,
        test_sketch_shared_contract_format,
        test_sketch_degrade_unparseable_header,
        test_sketch_warns_over_40,
        test_spill_missing_file_exit_2,
        test_spill_empty_stdin_exit_2,
        test_prune_missing_dir_exit_0,
        test_version_and_help,
        test_get_invalid_node_id_exit_2,
    ]
    failures = 0
    for t in _tests:
        try:
            t()
        except Exception as exc:
            failures += 1
            print(f"FAIL {t.__name__}: {exc}")
    if failures:
        raise SystemExit(1)
    print("All agentic-evidence tests passed.")
