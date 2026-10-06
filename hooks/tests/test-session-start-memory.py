# Run with: python3 hooks/tests/test-session-start-memory.py
"""
Tests for hooks/session-start-memory.py.

Every case runs the hook as a subprocess against a scratch git repo, the
way the Claude Code hook runner does. After the T1-T11 pass against the
real hook, each named mutation (a)-(f) is applied to a copy of the hook and
the test it targets is run against that copy; the suite fails if the
mutation does not redden it.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

REAL_HOOK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "session-start-memory.py",
)
HOOK = REAL_HOOK
CAP = 8500
MARKER = "<!-- dinostack:memory-main-only -->"
SCRATCH = tempfile.mkdtemp(prefix="ssm-test-")
DIRECTIVE = (
    "MEMORY.md is %d bytes; only lines 1-%d are shown. Before your first decision this session, "
    "Read %s from line %d to EOF in full (offset/limit; halve limit if a Read is too large). "
    "After a compact or clear, repeat this whenever lines %d to EOF are no longer visible in this conversation."
)


def make_repo(name, claude_md=None, memory=None, extra=None):
    root = tempfile.mkdtemp(prefix=name + "-", dir=SCRATCH)
    subprocess.run(["git", "init", "-q", root], check=True)
    if claude_md is not None:
        with open(os.path.join(root, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write(claude_md)
    if memory is not None:
        with open(os.path.join(root, "MEMORY.md"), "w", encoding="utf-8") as f:
            f.write(memory)
    for rel, body in (extra or {}).items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
    return os.path.realpath(root)


def run_hook(stdin_text):
    r = subprocess.run(
        [sys.executable, HOOK], input=stdin_text.encode("utf-8"),
        capture_output=True, timeout=30,
    )
    assert r.returncode == 0, ("exit", r.returncode, r.stderr)
    return r.stdout


def run_payload(cwd, source="startup"):
    return run_hook(json.dumps({
        "session_id": "s", "transcript_path": "/dev/null", "cwd": cwd,
        "hook_event_name": "SessionStart", "source": source,
    }))


def ctx_of(stdout):
    out = json.loads(stdout)
    assert set(out) == {"hookSpecificOutput"}, out
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart", hso
    return hso["additionalContext"]


def migrated(*extra_lines):
    return "@AGENTS.md\n" + MARKER + "\n" + "".join(l + "\n" for l in extra_lines)


def big_memory(target_bytes, filler):
    lines = ["# Memory CANARY_HEAD\n"]
    i = 0
    size = len(lines[0].encode("utf-8"))
    while size < target_bytes:
        line = "- entry %05d %s\n" % (i, filler)
        lines.append(line)
        size += len(line.encode("utf-8"))
        i += 1
    return "".join(lines)


def split_lines(text):
    parts = text.split("\n")
    out = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        out.append(parts[-1])
    return out


def check_head_cut(root, memory):
    """Shared T2/T11 assertions; returns the CTX."""
    stdout = run_payload(root)
    ctx = ctx_of(stdout)
    assert len(json.dumps(ctx, ensure_ascii=True)) <= CAP, len(json.dumps(ctx, ensure_ascii=True))
    path = os.path.join(root, "MEMORY.md")
    n = len(memory.encode("utf-8"))
    marker = "MEMORY.md is %d bytes; only lines 1-" % n
    assert marker in ctx, ctx[-600:]
    last = int(ctx.split(marker, 1)[1].split(" ", 1)[0])
    assert last >= 1, last
    lines = split_lines(memory)
    head = "".join(lines[:last])
    assert head in ctx, "shown text is not exactly lines 1-%d" % last
    after_head = ctx.split(head, 1)[1]
    assert after_head.startswith("\nMEMORY.md is "), repr(after_head[:80])
    assert after_head[1:] == DIRECTIVE % (n, last, path, last + 1, last + 1), after_head[-600:]
    assert os.path.isabs(path)
    grown = ctx.split(head, 1)[0] + head + lines[last] + "\n" + DIRECTIVE % (n, last + 1, path, last + 2, last + 2)
    assert len(json.dumps(grown, ensure_ascii=True)) > CAP, "L is not the longest prefix that fits"
    return stdout


# ---------------------------------------------------------------------------


def t1_small_file_full():
    memory = "# Memory\nCANARY_SMALL_0001\n" + ("filler line\n" * 50) + "CANARY_SMALL_END\n"
    root = make_repo("t1", migrated(), memory)
    ctx = ctx_of(run_payload(root))
    assert ctx.endswith(memory), ctx[-200:]
    assert "CANARY_SMALL_0001" in ctx and "CANARY_SMALL_END" in ctx
    assert "only lines" not in ctx


def t2_large_file_head():
    memory = big_memory(300 * 1024, "x" * 60)
    root = make_repo("t2", migrated(), memory)
    check_head_cut(root, memory)


def t3_import_line_suppresses():
    memory = "CANARY\n"
    cases = [
        ("t3a", migrated("@MEMORY.md"), {}),
        ("t3b", migrated("  @./MEMORY.md  "), {}),
        ("t3c", migrated(), {os.path.join(".claude", "CLAUDE.md"): "@MEMORY.md\n"}),
        ("t3d", migrated(), {"CLAUDE.local.md": "x\n@./MEMORY.md\n"}),
    ]
    for name, cm, extra in cases:
        root = make_repo(name, cm, memory, extra)
        out = run_payload(root).strip()
        assert out == b"{}", (name, out)


def t4_no_marker():
    for name, cm in (("t4", "@AGENTS.md\nsome text\n"), ("t4b", None)):
        out = run_payload(make_repo(name, cm, "CANARY\n")).strip()
        assert out == b"{}", (name, out[:120])


def t5_no_memory():
    out = run_payload(make_repo("t5", migrated(), None)).strip()
    assert out == b"{}", out[:120]


def t6_garbage_stdin():
    for junk in ("", "not json", "[1,2]", "{\"cwd\": 5}"):
        assert run_hook(junk).strip() == b"{}", junk


def t7_source_invariant():
    memory = big_memory(60 * 1024, "y" * 60)
    root = make_repo("t7", migrated(), memory)
    outs = {s: run_payload(root, s) for s in ("startup", "resume", "compact", "clear")}
    assert len(set(outs.values())) == 1, {k: len(v) for k, v in outs.items()}
    ctx_of(outs["startup"])


def t8_subdirectory_cwd():
    memory = "CANARY_T8\n"
    root = make_repo("t8", migrated(), memory, {os.path.join("src", "deep", "a.py"): "x = 1\n"})
    ctx = ctx_of(run_payload(os.path.join(root, "src", "deep")))
    assert "CANARY_T8" in ctx
    assert "(" + os.path.join(root, "MEMORY.md") + ")" in ctx, ctx[:200]


def t9_first_line_too_long():
    memory = ("z" * (10 * 1024)) + "\nsecond line\n"
    root = make_repo("t9", migrated(), memory)
    ctx = ctx_of(run_payload(root))
    path = os.path.join(root, "MEMORY.md")
    want = ("MEMORY.md is %d bytes; its first line exceeds the cap, so none is shown. "
            "Read %s in full from line 1 before your first decision." % (len(memory), path))
    assert want in ctx, ctx[-400:]
    assert "zzzz" not in ctx and "second line" not in ctx


def t10_unreadable_memory():
    root = make_repo("t10", migrated(), "CANARY_T10\n")
    path = os.path.join(root, "MEMORY.md")
    os.chmod(path, 0)
    try:
        if os.access(path, os.R_OK):
            if os.environ.get("CI"):
                raise AssertionError("T10 cannot make MEMORY.md unreadable (running as root?)")
            print("  SKIP T10: mode 000 is still readable to this user")
            return
        ctx = ctx_of(run_payload(root))
        assert ctx.startswith("DinoStack memory hook error ("), ctx
        assert ("): MEMORY.md was not delivered. Read %s in full before your first decision." % path) in ctx, ctx
        assert "CANARY_T10" not in ctx
    finally:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def t11_multibyte_filler():
    memory = big_memory(120 * 1024, "é漢" * 20)
    root = make_repo("t11", migrated(), memory)
    stdout = check_head_cut(root, memory)
    stdout.decode("ascii")


TESTS = [
    ("T1", t1_small_file_full), ("T2", t2_large_file_head),
    ("T3", t3_import_line_suppresses), ("T4", t4_no_marker),
    ("T5", t5_no_memory), ("T6", t6_garbage_stdin),
    ("T7", t7_source_invariant), ("T8", t8_subdirectory_cwd),
    ("T9", t9_first_line_too_long), ("T10", t10_unreadable_memory),
    ("T11", t11_multibyte_filler),
]

# (tag, old, new, test that must redden)
MUTATIONS = [
    ("(a) drop the import check", "        if _has_import(root):\n", "        if False:\n", "T3"),
    ("(b) CAP set to 20000", "\nCAP = 8500\n", "\nCAP = 20000\n", "T2"),
    ("(c) drop the marker check", "        if not _has_marker(root):\n", "        if False:\n", "T4"),
    ("(d) mid-line cut", "    lines = _split_lines(text)\n",
     "    lines = [text[i:i + 40] for i in range(0, len(text), 40)]\n", "T2"),
    ("(e) emit systemMessage",
     '{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}}',
     '{"systemMessage": ctx}', "T1"),
    ("(f) UTF-8 bytes instead of escaped length",
     "    return len(json.dumps(s, ensure_ascii=True)) - 2\n",
     '    return len(s.encode("utf-8"))\n', "T11"),
]


def run_tests(selected=None):
    failed = []
    for name, fn in TESTS:
        if selected and name != selected:
            continue
        try:
            fn()
            if not selected:
                print("PASS: %s %s" % (name, fn.__name__))
        except AssertionError as exc:
            failed.append(name)
            reason = str(exc)[:160].replace("\n", " ")
            print(("    (!) %s -> %s" if selected else "FAIL: %s %s") % (name, reason))
    return failed


def run_mutations():
    global HOOK
    failed = 0
    with open(REAL_HOOK, encoding="utf-8") as f:
        src = f.read()
    for i, (tag, old, new, target) in enumerate(MUTATIONS):
        if src.count(old) != 1:
            print("FAIL: mutation %s anchor matched %d times" % (tag, src.count(old)))
            failed += 1
            continue
        mutant = os.path.join(SCRATCH, "mutant-%d.py" % i)
        with open(mutant, "w", encoding="utf-8") as f:
            f.write(src.replace(old, new))
        HOOK = mutant
        try:
            reddened = run_tests(target)
        finally:
            HOOK = REAL_HOOK
        if reddened:
            print("PASS: mutation %s reddens %s" % (tag, target))
        else:
            print("FAIL: mutation %s left %s green" % (tag, target))
            failed += 1
    return failed


def main():
    try:
        failed = len(run_tests())
        failed += run_mutations()
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)
    print("\nResults: %d failed." % failed)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
