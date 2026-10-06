#!/usr/bin/env python3
"""
Purpose: Contract stand-in for a two-tier project's own memory compiler
         (the shape authentic8's scripts/regenerate-memory.mjs exposes), so
         bin/tests/test_ds_memory_capture.py can exercise
         bin/ds-memory-capture against real compiler semantics without
         depending on any one project. It reproduces only the contract the
         helper relies on: a shard with no `index` compiles verbatim, an
         indexed shard compiles to `- <text> [<id>]` lines (nothing for
         `index: none`), `ingest` accepts only gap blocks of one dated line
         plus blank lines at the head or tail, head blocks take
         min-1000 (tail max+1000), a duplicate `sequence` throws, a stray
         or edited line refuses, and the post-ingest compile must reproduce
         MEMORY.md byte-for-byte before any shard is written.

Public API: run with cwd = project root -
  python3 compiler.py ingest | status | regenerate --check

Upstream deps: Python 3 stdlib only. Reads `.agentic/memory-shards/` and
  `MEMORY.md` under the current working directory.

Downstream consumers: bin/tests/test_ds_memory_capture.py and
  bin/tests/test_phase11e_knowledge_commit_shell.py (copied into each
  fixture repo as a git-tracked `scripts/compiler.py`).

Failure modes: every refusal prints `<cmd>: REFUSING - <reason>` to stderr,
  exits 1 and writes nothing. Middle-gap ingest (new lines between two
  existing blocks) is refused rather than modelled.

Performance: standard (fixture-sized corpora only).
"""
import hashlib
import json
import os
import re
import sys

SHARD_DIR = os.path.join(".agentic", "memory-shards")
PREAMBLE = "_preamble.md"
GAP = 1000
DATED = re.compile(r"^- \*\*20\d\d-\d\d-\d\d")
FM = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)


class Refuse(Exception):
    pass


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _write(p, text):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, p)


def _index(fm):
    lines = fm.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("index:"):
            rest = line[len("index:"):].strip()
            if rest == "none":
                return "none"
            items = []
            for item in lines[i + 1:]:
                if not item.startswith("  - "):
                    break
                items.append(json.loads(item[4:]))
            return items
    return None


def records():
    out = []
    for name in sorted(os.listdir(SHARD_DIR)):
        if name == PREAMBLE or name.startswith(".") or not name.endswith(".md"):
            continue
        m = FM.match(_read(os.path.join(SHARD_DIR, name)))
        if not m:
            raise Refuse("%s has no frontmatter" % name)
        seq = re.search(r"^sequence:\s*(-?\d+)\s*$", m.group(1), re.M)
        if not seq:
            raise Refuse("%s has no sequence" % name)
        out.append({"file": name, "sequence": int(seq.group(1)), "body": m.group(2),
                    "index": _index(m.group(1))})
    seen = {}
    for r in out:
        if r["sequence"] in seen:
            raise Refuse("duplicate sequence %d (files %s and %s)"
                         % (r["sequence"], seen[r["sequence"]], r["file"]))
        seen[r["sequence"]] = r["file"]
    return sorted(out, key=lambda r: r["sequence"])


def block(r):
    if r["index"] is None:
        return r["body"]
    if r["index"] == "none":
        return ""
    return "".join("- %s [%s]\n" % (t, r["file"][:-3]) for t in r["index"])


def compile_all(recs):
    return _read(os.path.join(SHARD_DIR, PREAMBLE)) + "".join(block(r) for r in recs)


def split_gap(gap):
    blocks = []
    for line in gap.split("\n")[:-1] if gap.endswith("\n") else gap.split("\n"):
        if DATED.match(line):
            blocks.append(line + "\n")
        elif line == "" and blocks:
            blocks[-1] += "\n"
        elif line != "":
            raise Refuse("stray line %r" % line[:120])
    return blocks


def ingest():
    recs = records()
    pre = _read(os.path.join(SHARD_DIR, PREAMBLE))
    text = _read("MEMORY.md")
    if not text.startswith(pre):
        raise Refuse("MEMORY.md does not start with _preamble.md")
    pos, gaps, emitted = len(pre), [], 0
    for r in recs:
        b = block(r)
        if not b:
            continue
        at = text.find(b, pos)
        if at < 0:
            raise Refuse("compiled block for %s is not present, unchanged and in order" % r["file"])
        if at > pos:
            gaps.append((text[pos:at], "head" if emitted == 0 else "middle"))
        pos, emitted = at + len(b), emitted + 1
    if pos < len(text):
        gaps.append((text[pos:], "head" if emitted == 0 and not recs else "tail"))
    bodies = {r["body"] for r in recs}
    added = []
    for gap, where in gaps:
        blocks = split_gap(gap)
        if blocks and where == "middle":
            raise Refuse("middle-gap ingest is not modelled by this fixture")
        for k, body in enumerate(blocks):
            if body in bodies:
                raise Refuse("a new block duplicates an existing shard body")
            bodies.add(body)
            if where == "head" and recs:
                seq = recs[0]["sequence"] - (len(blocks) - k) * GAP
            else:
                seq = (recs[-1]["sequence"] if recs else 0) + (k + 1) * GAP
            date = body[4:14]
            name = "%s-session-%s.md" % (date, hashlib.sha256(body.encode()).hexdigest()[:8])
            if os.path.exists(os.path.join(SHARD_DIR, name)):
                raise Refuse("new shard filename %s already exists" % name)
            added.append({"file": name, "sequence": seq, "body": body, "index": None})
    if not added:
        print("ingest: nothing to ingest")
        return
    if compile_all(sorted(recs + added, key=lambda r: r["sequence"])) != text:
        raise Refuse("ingested shard set would not reproduce MEMORY.md byte-for-byte")
    for a in added:
        _write(os.path.join(SHARD_DIR, a["file"]),
               "---\nname: %s\ndescription: \"fixture\"\nmetadata:\n  type: project\n"
               "sequence: %d\nsupersedes: []\nsuperseded_by: null\n---\n%s"
               % (a["file"][:-3], a["sequence"], a["body"]))
    print("ingest: added %d shard(s) with no index field" % len(added))


def status():
    recs = records()
    verbatim = [r for r in recs if r["index"] is None]
    print("status: %d verbatim %d bytes; %d indexed"
          % (len(verbatim), sum(len(r["body"].encode()) for r in verbatim),
             len(recs) - len(verbatim)))


def regenerate_check():
    if compile_all(records()) != _read("MEMORY.md"):
        raise Refuse("MEMORY.md differs from the compile")
    print("regenerate --check: ok")


def main(argv):
    cmd = argv[0] if argv else ""
    try:
        if cmd == "ingest":
            ingest()
        elif cmd == "status":
            status()
        elif cmd == "regenerate" and argv[1:] == ["--check"]:
            regenerate_check()
        else:
            print("usage: compiler.py ingest | status | regenerate --check", file=sys.stderr)
            return 2
    except Refuse as err:
        print("%s: REFUSING - %s" % (cmd, err), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
