# Run with: python3 hooks/tests/test-session-start-memory.py
"""
Tests for hooks/session-start-memory.py.

Every case runs the hook as a subprocess against a scratch git repo, the
way the Claude Code hook runner does. After the T1-T17 pass against the
real hook, each named mutation (a)-(r) is applied to a copy of the hook and
the test it targets is run against that copy; the suite fails if the
mutation does not redden it.
"""

import json
import os
import shlex
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
READ_BUDGET = 30000
WINDOW_MIN = 1
WINDOW_MAX = 200
MARKER = "<!-- dinostack:memory-main-only -->"
SCRATCH = tempfile.mkdtemp(prefix="ssm-test-")
DIRECTIVE = (
    "MEMORY.md is %d bytes, %d lines; only lines 1-%d are shown. Before your first decision this session, "
    "Read %s lines %d-%d in full: one Read can stop short, so keep reading from the next unread line "
    "(offset/limit; halve limit if a Read is too large) until you have seen line %d. "
    "After a compact or clear, repeat this whenever lines %d-%d are no longer visible in this conversation."
)


GREP_DIRECTIVE = (
    "MEMORY.md is %d bytes, %d lines; %s. Do not Read lines %d-%d whole: those %d bytes are more than "
    "one Read returns (the Read tool caps a call at 25,000 tokens, and dense Markdown runs near 2 bytes "
    "per token). Instead, before any decision that may depend on a recorded fact or operator ruling, grep "
    "for it with `grep -n -i '<topic>' %s` and Read only a window around each hit: offset a few lines "
    "above the hit, limit at most %d (the heaviest %d-line span in this file is %d bytes). This holds "
    "for the whole session, including after a compact or clear."
)


def spans(memory, k):
    """Byte size of every k-line window of memory, by brute force."""
    sizes = [len(l.encode("utf-8")) for l in split_lines(memory)]
    return [sum(sizes[i:i + k]) for i in range(max(1, len(sizes) - k + 1))]


def window_limit(memory):
    n_lines = len(split_lines(memory))
    fits = [k for k in range(WINDOW_MIN, min(WINDOW_MAX, n_lines) + 1)
            if max(spans(memory, k)) <= READ_BUDGET]
    k = max(fits) if fits else WINDOW_MIN
    return k, max(spans(memory, k))


def directive(n, n_lines, last, path, rest=0, memory=None):
    if rest > READ_BUDGET:
        shown = "only lines 1-%d are shown" % last if last else "its first line exceeds the cap, so none is shown"
        k, span = window_limit(memory)
        return GREP_DIRECTIVE % (n, n_lines, shown, last + 1, n_lines, rest, shlex.quote(path), k, k, span)
    return DIRECTIVE % (n, n_lines, last, path, last + 1, n_lines, n_lines, last + 1, n_lines)


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
    """Shared T2/T11/T12/T13 assertions; returns (stdout, last, rest bytes)."""
    stdout = run_payload(root)
    ctx = ctx_of(stdout)
    assert len(json.dumps(ctx, ensure_ascii=True)) <= CAP, len(json.dumps(ctx, ensure_ascii=True))
    path = os.path.join(root, "MEMORY.md")
    n = len(memory.encode("utf-8"))
    lines = split_lines(memory)
    marker = "MEMORY.md is %d bytes, %d lines; only lines 1-" % (n, len(lines))
    assert marker in ctx, ctx[-600:]
    last = int(ctx.split(marker, 1)[1].split(" ", 1)[0])
    assert last >= 1, last
    head = "".join(lines[:last])
    rest = n - len(head.encode("utf-8"))
    assert head in ctx, "shown text is not exactly lines 1-%d" % last
    after_head = ctx.split(head, 1)[1]
    assert after_head.startswith("\nMEMORY.md is "), repr(after_head[:80])
    assert after_head[1:] == directive(n, len(lines), last, path, rest, memory), after_head[-600:]
    assert os.path.isabs(path)
    prefix = ctx.split(head, 1)[0] + head
    grown_rest = rest
    for longer in range(last + 1, len(lines)):
        prefix += lines[longer - 1]
        if len(json.dumps(prefix + "\n", ensure_ascii=True)) > CAP:
            break
        grown_rest -= len(lines[longer - 1].encode("utf-8"))
        grown = prefix + "\n" + directive(n, len(lines), longer, path, grown_rest, memory)
        assert len(json.dumps(grown, ensure_ascii=True)) > CAP, "L=%d fits but %d was shown" % (longer, last)
    return stdout, last, rest


# ---------------------------------------------------------------------------


def t1_small_file_full():
    memory = "# Memory\nCANARY_SMALL_0001\n" + ("filler line\n" * 50) + "CANARY_SMALL_END\n"
    root = make_repo("t1", migrated(), memory)
    ctx = ctx_of(run_payload(root))
    assert ctx.endswith(memory), ctx[-200:]
    assert "CANARY_SMALL_0001" in ctx and "CANARY_SMALL_END" in ctx
    assert "only lines" not in ctx


def t2_large_file_head():
    # Shaped like the measured authentic8 MEMORY.md: ~309 KB, ~1,126 lines, ~275 B/line.
    memory = big_memory(309 * 1024, "x" * 260)
    root = make_repo("t2 it's", migrated(), memory)
    _, _, rest = check_head_cut(root, memory)
    assert rest > READ_BUDGET, rest
    tail = ctx_of(run_payload(root)).rsplit("\nMEMORY.md is ", 1)[1]
    assert "in full" not in tail, tail
    path = os.path.join(root, "MEMORY.md")
    assert " " in path and "'" in path
    assert "grep -n -i '<topic>' " + shlex.quote(path) + "`" in tail, tail
    limit = int(tail.split("limit at most ", 1)[1].split(" ", 1)[0])
    assert WINDOW_MIN < limit < WINDOW_MAX, limit
    assert max(spans(memory, limit)) <= READ_BUDGET, limit
    assert max(spans(memory, limit + 1)) > READ_BUDGET, "limit is not the largest that fits"


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
    want = ("MEMORY.md is %d bytes, 2 lines; its first line exceeds the cap, so none is shown. "
            "Before your first decision, Read %s lines 1-2 in full, continuing from the next "
            "unread line until you have seen line 2." % (len(memory), path))
    assert want in ctx, ctx[-400:]
    assert "zzzz" not in ctx and "second line" not in ctx


def t10_unreadable_memory():
    root = make_repo("t10 x", migrated(), "CANARY_T10\n")
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
        want = ("): MEMORY.md was not delivered. Before any decision that may depend on a recorded fact "
                "or operator ruling, grep %s for it (`grep -n -i '<topic>' %s`) and Read only a window "
                "around each hit; Read the whole file only if it is at most %d bytes."
                % (path, shlex.quote(path), READ_BUDGET))
        assert want in ctx, ctx
        assert "in full" not in ctx, ctx
        assert "CANARY_T10" not in ctx
    finally:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def t11_multibyte_filler():
    memory = big_memory(120 * 1024, "é漢" * 20)
    root = make_repo("t11", migrated(), memory)
    stdout, _, _ = check_head_cut(root, memory)
    stdout.decode("ascii")


def t12_small_remainder_reads_in_full():
    memory = big_memory(24 * 1024, "w" * 60)
    root = make_repo("t12", migrated(), memory)
    _, last, rest = check_head_cut(root, memory)
    assert 0 < rest <= READ_BUDGET, rest
    want = directive(len(memory.encode("utf-8")), len(split_lines(memory)), last,
                     os.path.join(root, "MEMORY.md"))
    assert ctx_of(run_payload(root)).endswith(want)


def boundary_memory(target_rest, name):
    """A MEMORY.md whose head fits CAP and whose one unshown line is exactly target_rest bytes."""
    head = big_memory(5 * 1024, "b" * 60)
    memory = head + "- tail " + "p" * (target_rest - len("- tail \n")) + "\n"
    root = make_repo(name, migrated(), memory)
    _, last, rest = check_head_cut(root, memory)
    assert last == len(split_lines(head)) and rest == target_rest, (last, rest, target_rest)
    return root


def t13_threshold_boundary():
    root = boundary_memory(READ_BUDGET, "t13a")
    ctx = ctx_of(run_payload(root))
    assert ctx.rsplit("\nMEMORY.md is ", 1)[1].count(" in full") == 1, ctx[-400:]
    root = boundary_memory(READ_BUDGET + 1, "t13b")
    ctx = ctx_of(run_payload(root))
    tail = ctx.rsplit("\nMEMORY.md is ", 1)[1]
    assert "in full" not in tail and "Do not Read lines" in tail, tail


def t14_first_line_too_long_large_file():
    memory = ("z" * (10 * 1024)) + "\n" + "- line %s\n" % ("q" * 100) * 300
    root = make_repo("t14", migrated(), memory)
    ctx = ctx_of(run_payload(root))
    n = len(memory.encode("utf-8"))
    want = directive(n, len(split_lines(memory)), 0, os.path.join(root, "MEMORY.md"), n, memory)
    assert ctx.endswith(want), ctx[-600:]
    assert "in full" not in ctx and "zzzz" not in ctx


def t15_long_line_cluster():
    # Short lines plus one contiguous run of ~5 KB lines: the average-based
    # limit would let a window over the run exceed READ_BUDGET.
    memory = big_memory(200 * 1024, "s" * 60)
    lines = split_lines(memory)
    cluster = ["- long %02d %s\n" % (i, "L" * 5000) for i in range(8)]
    memory = "".join(lines[:600] + cluster + lines[600:])
    root = make_repo("t15", migrated(), memory)
    check_head_cut(root, memory)
    tail = ctx_of(run_payload(root)).rsplit("\nMEMORY.md is ", 1)[1]
    limit = int(tail.split("limit at most ", 1)[1].split(" ", 1)[0])
    assert max(spans(memory, limit)) <= READ_BUDGET, (limit, max(spans(memory, limit)))
    avg_limit = int(READ_BUDGET // (len(memory.encode("utf-8")) / len(split_lines(memory))))
    assert limit < avg_limit, (limit, avg_limit)


def t16_invalid_utf8_counts_raw_bytes():
    # 200 invalid bytes in the shown head decode to U+FFFD (3 bytes each when
    # re-encoded); counting that way would shrink a 30001-byte remainder under
    # READ_BUDGET and pick the read-in-full branch.
    head = big_memory(5 * 1024, "b" * 60).encode("utf-8") + b"- bad " + b"\xff" * 200 + b"\n"
    tail = b"- tail " + b"p" * (READ_BUDGET + 1 - len(b"- tail \n")) + b"\n"
    root = make_repo("t16", migrated())
    with open(os.path.join(root, "MEMORY.md"), "wb") as f:
        f.write(head + tail)
    ctx = ctx_of(run_payload(root))
    rest = ctx.rsplit("\nMEMORY.md is ", 1)[1]
    n_head = head.count(b"\n")
    assert rest.startswith("%d bytes, %d lines; only lines 1-%d are shown. Do not Read lines %d-%d whole: "
                           "those %d bytes" % (len(head + tail), n_head + 1, n_head, n_head + 1,
                                               n_head + 1, READ_BUDGET + 1)), rest[:300]
    assert "in full" not in rest, rest[:300]


def t17_longer_prefix_fits_with_shorter_directive():
    # Line A leaves a remainder just over READ_BUDGET (grep directive) and does
    # not fit; line B after it drops the remainder to READ_BUDGET, and the
    # shorter read-in-full directive lets lines 1-B fit.
    root = make_repo("t17", migrated())
    path = os.path.join(root, "MEMORY.md")
    head = big_memory(4 * 1024, "h" * 60)
    line_b = "- b\n"
    line_t = "- tail " + "t" * (READ_BUDGET - len("- tail \n")) + "\n"
    header = ("Root MEMORY.md (" + path + "), delivered to the main session only by "
              "the DinoStack session-start-memory hook:\n\n")
    n_head = len(split_lines(head))

    def sized(a_len, n_shown):
        line_a = "- a " + "a" * (a_len - len("- a \n")) + "\n"
        memory = head + line_a + line_b + line_t
        lines = split_lines(memory)
        rest = len(memory.encode("utf-8")) - len("".join(lines[:n_shown]).encode("utf-8"))
        ctx = header + "".join(lines[:n_shown]) + "\n" + directive(
            len(memory.encode("utf-8")), len(lines), n_shown, path, rest, memory)
        return memory, len(json.dumps(ctx, ensure_ascii=True))

    a_len = 100
    while sized(a_len + 1, n_head + 2)[1] <= CAP:
        a_len += 1
    memory, with_b = sized(a_len, n_head + 2)
    assert with_b <= CAP, "construction: lines 1-B do not fit"
    assert sized(a_len, n_head + 1)[1] > CAP, "construction: lines 1-A fit, so the early-break case is not exercised"
    with open(path, "w", encoding="utf-8") as f:
        f.write(memory)
    _, last, rest = check_head_cut(root, memory)
    assert (last, rest) == (n_head + 2, READ_BUDGET), (last, n_head + 2, rest)


TESTS = [
    ("T1", t1_small_file_full), ("T2", t2_large_file_head),
    ("T3", t3_import_line_suppresses), ("T4", t4_no_marker),
    ("T5", t5_no_memory), ("T6", t6_garbage_stdin),
    ("T7", t7_source_invariant), ("T8", t8_subdirectory_cwd),
    ("T9", t9_first_line_too_long), ("T10", t10_unreadable_memory),
    ("T11", t11_multibyte_filler), ("T12", t12_small_remainder_reads_in_full),
    ("T13", t13_threshold_boundary), ("T14", t14_first_line_too_long_large_file),
    ("T15", t15_long_line_cluster), ("T16", t16_invalid_utf8_counts_raw_bytes),
    ("T17", t17_longer_prefix_fits_with_shorter_directive),
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
    ("(g) EOF line number dropped from the directive",
     "    return _tail_directive(n_bytes, n_lines, last, path)\n",
     "    return _tail_directive(n_bytes, last + 1, last, path)\n", "T12"),
    ("(h) threshold compared with >=", "    if rest_bytes > READ_BUDGET:\n",
     "    if rest_bytes >= READ_BUDGET:\n", "T13"),
    ("(i) grep branch never taken", "\nREAD_BUDGET = 30000\n", "\nREAD_BUDGET = 10 ** 9\n", "T2"),
    ("(p) grep command path unquoted", "rest_bytes, shlex.quote(path),\n", "rest_bytes, path,\n", "T2"),
    ("(q) fallback grep command path unquoted", "path, shlex.quote(path), READ_BUDGET)", "path, path, READ_BUDGET)",
     "T10"),
    ("(j) window limit hardcoded", "    return lo, _max_span(sizes, lo)\n",
     "    return WINDOW_MAX, _max_span(sizes, WINDOW_MAX)\n", "T2"),
    ("(k) none-shown keeps the read-in-full text for a large file",
     "    if rest_bytes > READ_BUDGET:\n", "    if rest_bytes > READ_BUDGET and last:\n", "T14"),
    ("(l) fallback mandates a full Read",
     '"Before any decision that may depend on a recorded fact or operator "\n',
     '"Read it in full. Before any decision that may depend on a recorded fact or operator "\n',
     "T10"),
    ("(m) remainder measured as the whole file",
     '    directive = _rest_directive(len(raw), len(lines), last, len(raw) - shown_bytes, path, window)\n',
     '    directive = _rest_directive(len(raw), len(lines), last, len(raw), path, window)\n', "T13"),
    ("(n) window limit from the average line length",
     "    window = _window_limit(sizes)\n",
     "    window = (max(WINDOW_MIN, min(WINDOW_MAX, READ_BUDGET * len(sizes) // len(raw))), 0)\n", "T15"),
    ("(o) remainder counted from re-encoded text",
     "    sizes = _line_bytes(raw)\n",
     '    sizes = [len(l.encode("utf-8")) for l in lines]\n', "T16"),
    ("(r) prefix scan stops at the first line that does not fit",
     "        if used + _esc_len(_rest_directive(len(raw), len(lines), i, rest, path, window)) <= CAP:\n",
     "        if used + _esc_len(_rest_directive(len(raw), len(lines), i, rest, path, window)) > CAP:\n"
     "            break\n        if True:\n", "T17"),
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
