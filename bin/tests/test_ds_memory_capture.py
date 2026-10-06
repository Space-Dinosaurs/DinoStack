"""
Purpose: Executes bin/ds-memory-capture against real git fixture repos whose
         compiler is bin/tests/fixtures/two_tier/compiler.py, covering mode
         detection, the inbox-to-shard flush for each capture writer's live
         entry format, rollback, standard-mode no-ops, the merge-collision
         repair, and the claim-by-rename inbox. Every case asserts distinct
         exit codes and names its reddening mutation in its docstring.

Public API: none (pytest module).

Upstream deps: bin/ds-memory-capture, bin/tests/fixtures/two_tier/compiler.py,
               and the writer format sources under content/ (read live).

Downstream consumers: .github/workflows/bin-tests.yml (pytest bin/tests/).

Failure modes: n/a (test module).

Performance: standard; each case builds one temp repo.
"""
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TOOL = REPO_ROOT / "bin" / "ds-memory-capture"
COMPILER = REPO_ROOT / "bin" / "tests" / "fixtures" / "two_tier" / "compiler.py"
SHARDS = Path(".agentic") / "memory-shards"
INBOX = Path(".agentic") / "memory-capture-inbox.md"
PREAMBLE_TEXT = "Header line. New entries are captured by `python3 scripts/compiler.py ingest`.\n\n"
DATE = "2026-10-05"

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
}


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-C", str(repo), *args], env=GIT_ENV, capture_output=True,
                       text=True, stdin=subprocess.DEVNULL, timeout=30)
    if check:
        assert r.returncode == 0, r.stderr
    return r


def _shard(seq: int, body: str, index: str | None = None) -> str:
    fm = ["---", "name: x", 'description: "x"', "metadata:", "  type: project",
          "sequence: %d" % seq, "supersedes: []", "superseded_by: null"]
    if index is not None:
        fm.append(index)
    return "\n".join(fm) + "\n---\n" + body


INDEXED = _shard(1000, "- **2026-01-01:** long fact A\n", 'index:\n  - "Rule A"')
VERBATIM = _shard(2000, "- **2026-01-02:** old fact B\n")
NONE = _shard(3000, "- **2026-01-03:** history C\n", "index: none")


def make_repo(tmp: Path, *, indexed: bool = True, preamble: str = PREAMBLE_TEXT,
              track_compiler: bool = True) -> Path:
    repo = tmp / "repo"
    (repo / SHARDS).mkdir(parents=True)
    (repo / "scripts").mkdir()
    shutil.copy(COMPILER, repo / "scripts" / "compiler.py")
    (repo / ".gitignore").write_text(".agentic/*\n!.agentic/memory-shards/\n")
    (repo / SHARDS / "_preamble.md").write_text(preamble)
    (repo / SHARDS / "2026-01-01-a.md").write_text(INDEXED if indexed else _shard(1000, "- **2026-01-01:** long fact A\n"))
    (repo / SHARDS / "2026-01-02-b.md").write_text(VERBATIM)
    if indexed:
        (repo / SHARDS / "2026-01-03-c.md").write_text(NONE)
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))
    (repo / "MEMORY.md").write_text(_compile(repo))
    _git(repo, "add", "-A")
    if not track_compiler:
        _git(repo, "rm", "-q", "--cached", "scripts/compiler.py")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _compile(repo: Path) -> str:
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'scripts'); import compiler; "
         "sys.stdout.write(compiler.compile_all(compiler.records()))"],
        cwd=repo, capture_output=True, text=True, check=True)
    return out.stdout


def compiler(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "scripts/compiler.py", *args], cwd=repo,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)


def tool(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), "--dir", str(repo), *args], cwd=repo,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)


def detect(repo: Path) -> dict:
    r = tool(repo, "detect")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def write_inbox(repo: Path, *lines: str) -> None:
    with open(repo / INBOX, "a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def inbox_text(repo: Path) -> str:
    p = repo / INBOX
    return p.read_text(encoding="utf-8") if p.exists() else ""


def shard_files(repo: Path) -> set[str]:
    return {p.name for p in (repo / SHARDS).glob("*.md") if p.name != "_preamble.md"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Writer formats, read live from the content files that define them.
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"^([ \t]*)```[^\n]*\n(.*?)^\1```", re.S | re.M)


def _fenced_templates(rel: str) -> list[str]:
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    out = []
    for m in _FENCE.finditer(text):
        body = "\n".join(line[len(m.group(1)):] for line in m.group(2).rstrip("\n").split("\n"))
        if body.startswith("- **YYYY-MM-DD:**"):
            out.append(body)
    return out


def _ds_wrap_template() -> list[str]:
    text = (REPO_ROOT / "content/commands/ds-wrap.md").read_text(encoding="utf-8")
    return re.findall(r"^`(- \*\*YYYY-MM-DD:\*\* \[what was decided[^`]*)`$", text, re.M)


WRITER_FORMATS = {
    "wrap-ticket": ("content/agents/wrap-ticket.md", 2),
    "learnings-agent": ("content/agents/learnings-agent.md", 2),
    "ds-memory-update": ("content/commands/ds-memory-update.md", 1),
}


def _format_cases() -> list[tuple[str, str]]:
    cases = []
    for writer, (rel, count) in WRITER_FORMATS.items():
        found = _fenced_templates(rel)
        assert len(found) == count, f"{rel}: expected {count} MEMORY.md entry fences, found {len(found)}"
        cases += [(f"{writer}-{i}", t) for i, t in enumerate(found)]
    inline = _ds_wrap_template()
    assert len(inline) == 1, f"ds-wrap.md Output 2 entry span: expected 1, found {len(inline)}"
    cases.append(("ds-wrap-part-b", inline[0]))
    return cases


FORMAT_CASES = _format_cases()


# ---------------------------------------------------------------------------
# (a)-(d) detect
# ---------------------------------------------------------------------------


def test_a_no_shard_dir_is_standard(tmp_path):
    """Mutation: default the mode to two-tier."""
    repo = tmp_path / "plain"
    repo.mkdir()
    _git(tmp_path, "init", "-q", str(repo))
    info = detect(repo)
    assert info["mode"] == "standard"
    assert info["batch_due"] is False


def test_b_verbatim_only_shards_are_standard(tmp_path):
    """T4. Mutation: any shard means two-tier."""
    repo = make_repo(tmp_path, indexed=False)
    info = detect(repo)
    assert info["mode"] == "standard"
    assert info["verbatim_shards"] == 2 and info["indexed_shards"] == 0


def test_c_index_shard_is_two_tier(tmp_path):
    """Mutation: corrupt the `^index:` regex."""
    repo = make_repo(tmp_path)
    info = detect(repo)
    assert info["mode"] == "two-tier"
    assert info["compiler"] == ["python3", "scripts/compiler.py"]
    assert (info["indexed_shards"], info["verbatim_shards"]) == (2, 1)
    assert info["verbatim_bytes"] == len("- **2026-01-02:** old fact B\n")


@pytest.mark.parametrize("preamble,track", [
    ("Run `python3 scripts/compiler.py ingest` or `node scripts/compiler.py ingest`.\n\n", True),
    ("Run `ruby scripts/compiler.py ingest`.\n\n", True),
    ("Run `python3 ../outside.py ingest`.\n\n", True),
    (PREAMBLE_TEXT, False),
], ids=["two-spans", "disallowed-interpreter", "outside-dir", "untracked-compiler"])
def test_d_unresolved_preamble(tmp_path, preamble, track):
    """Mutation: take the first span, or drop the interpreter allowlist."""
    repo = make_repo(tmp_path, preamble=preamble, track_compiler=track)
    info = detect(repo)
    assert info["mode"] == "two-tier-unresolved", info
    assert info["compiler"] is None and info["reason"]


# ---------------------------------------------------------------------------
# (e) each writer's live format, written to the inbox and flushed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", FORMAT_CASES, ids=[c[0] for c in FORMAT_CASES])
def test_e_writer_format_flushes_to_a_verbatim_shard(tmp_path, case):
    """T1/T2/T3/T5. Mutations: skip `ingest` after insertion; drop the trigger
    from the `captured:` line; make a writer's format two lines."""
    _, template = case
    entry = template.replace("YYYY-MM-DD", DATE, 1)
    repo = make_repo(tmp_path)
    before_shards = shard_files(repo)
    indexed = {n: sha(repo / SHARDS / n) for n in ("2026-01-01-a.md", "2026-01-03-c.md")}
    before = detect(repo)
    write_inbox(repo, entry)

    r = tool(repo, "flush")

    assert r.returncode == 0, r.stdout + r.stderr
    new = shard_files(repo) - before_shards
    assert len(new) == 1, (new, r.stdout)
    assert "index:" not in (repo / SHARDS / new.pop()).read_text()
    assert compiler(repo, "regenerate", "--check").returncode == 0
    assert (repo / "MEMORY.md").read_text().startswith(PREAMBLE_TEXT + entry + "\n")
    assert {n: sha(repo / SHARDS / n) for n in indexed} == indexed
    after = detect(repo)
    assert after["verbatim_bytes"] - before["verbatim_bytes"] == len((entry + "\n").encode())
    assert "deferred-verbatim; batch trigger: verbatim_bytes > 40000, now %d" % after["verbatim_bytes"] in r.stdout
    assert inbox_text(repo) == ""


# ---------------------------------------------------------------------------
# (f)-(h) refusal paths
# ---------------------------------------------------------------------------


def test_f_ingest_refusal_rolls_back_only_our_bytes(tmp_path):
    """A shard file already holding the name ingest will derive makes the
    post-insertion ingest refuse. Mutation: skip the rollback."""
    repo = make_repo(tmp_path)
    entry = "- **%s:** colliding fact" % DATE
    name = "%s-session-%s.md" % (DATE, hashlib.sha256((entry + "\n").encode()).hexdigest()[:8])
    (repo / SHARDS / name).write_text(_shard(4000, "- **2026-01-04:** other\n", "index: none"))
    snapshot = (repo / "MEMORY.md").read_bytes()
    write_inbox(repo, entry)

    r = tool(repo, "flush")

    assert r.returncode == 1, r.stdout
    assert (repo / "MEMORY.md").read_bytes() == snapshot
    assert inbox_text(repo) == entry + "\n"
    assert "requeued (ingest refused)" in r.stdout


def test_g_pre_existing_wedge_leaves_file_untouched(tmp_path):
    """A hand edit of a compiled line wedges ingest before we start; the
    file must never be rewritten. Mutation: skip the pre-ingest."""
    repo = make_repo(tmp_path)
    mem = repo / "MEMORY.md"
    mem.write_text(mem.read_text().replace("- Rule A [2026-01-01-a]", "- Rule A edited [2026-01-01-a]"))
    st = mem.stat()
    write_inbox(repo, "- **%s:** fact during wedge" % DATE)

    r = tool(repo, "flush")

    assert r.returncode == 1, r.stdout
    after = mem.stat()
    assert (after.st_ino, after.st_mtime_ns) == (st.st_ino, st.st_mtime_ns)
    assert "pre-ingest refused" in r.stdout
    assert "fact during wedge" in inbox_text(repo)


def test_h_standard_mode_exits_2_and_changes_nothing(tmp_path):
    """T4. Mutation: proceed with the flush anyway."""
    repo = make_repo(tmp_path, indexed=False)
    write_inbox(repo, "- **%s:** standard fact" % DATE)
    mem, inbox = sha(repo / "MEMORY.md"), inbox_text(repo)
    shards = shard_files(repo)

    r = tool(repo, "flush")

    assert r.returncode == 2, r.stdout
    assert sha(repo / "MEMORY.md") == mem and inbox_text(repo) == inbox
    assert shard_files(repo) == shards
    assert not (repo / ".agentic" / "memory-capture.lock").exists()


# ---------------------------------------------------------------------------
# (i)-(j) new-shards and repair
# ---------------------------------------------------------------------------


def test_i_new_shards_lists_exactly_paths_absent_from_ref(tmp_path):
    """Mutation: list every shard."""
    repo = make_repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / SHARDS / "2026-02-01-committed.md").write_text(_shard(5000, "- **2026-02-01:** c\n"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c")
    (repo / SHARDS / "2026-02-02-untracked.md").write_text(_shard(6000, "- **2026-02-02:** u\n"))
    (repo / SHARDS / "2026-01-02-b.md").write_text(_shard(2000, "- **2026-01-02:** changed\n"))
    (repo / ".agentic" / "ignored.md").write_text("x\n")

    r = tool(repo, "new-shards", "--ref", base)

    assert r.returncode == 0
    assert r.stdout.splitlines() == [
        ".agentic/memory-shards/2026-02-01-committed.md",
        ".agentic/memory-shards/2026-02-02-untracked.md",
    ]
    assert tool(repo, "new-shards", "--ref", "no-such-ref").stdout == ""


def test_i_new_shards_handles_non_ascii_names(tmp_path):
    """git quotes non-ASCII paths unless -z is used, so a quoted name never
    matches a file on disk and drops out. Mutation: drop -z."""
    repo = make_repo(tmp_path)
    (repo / SHARDS / "2026-02-06-über.md").write_text(_shard(5000, "- **2026-02-06:** u\n"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "u")
    (repo / SHARDS / "2026-02-04-café.md").write_text(_shard(6000, "- **2026-02-04:** c\n"))

    r = tool(repo, "new-shards", "--ref", "HEAD")

    assert r.returncode == 0
    assert r.stdout.splitlines() == [".agentic/memory-shards/2026-02-04-café.md"], r.stdout


def test_i_new_shards_prints_nothing_in_standard_mode(tmp_path):
    repo = make_repo(tmp_path, indexed=False)
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / SHARDS / "2026-02-02-untracked.md").write_text(_shard(6000, "- **2026-02-02:** u\n"))
    r = tool(repo, "new-shards", "--ref", base)
    assert (r.returncode, r.stdout) == (0, "")


def test_j_merge_collision_is_repaired_from_committed_state(tmp_path):
    """Two branches flush from one base; a both-sides resolution commits two
    shards on one sequence and the compile throws. Mutation: define the
    new-shards set by git status instead of tree absence."""
    repo = make_repo(tmp_path)
    for branch, text in (("a", "fact from branch a"), ("b", "fact from branch b")):
        _git(repo, "checkout", "-q", "-b", branch, "main")
        write_inbox(repo, "- **%s:** %s" % (DATE, text))
        assert tool(repo, "flush").returncode == 0
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", branch)
    merge = _git(repo, "merge", "-q", "a", check=False)
    assert merge.returncode != 0 and "MEMORY.md" in merge.stdout + merge.stderr
    mem = (repo / "MEMORY.md").read_text()
    resolved = re.sub(r"<<<<<<< [^\n]*\n(.*?)=======\n(.*?)>>>>>>> [^\n]*\n", r"\1\2", mem, flags=re.S)
    (repo / "MEMORY.md").write_text(resolved)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-edit")
    failed = compiler(repo, "regenerate", "--check")
    assert failed.returncode == 1 and "duplicate sequence" in failed.stderr
    assert compiler(repo, "ingest").returncode == 0, "fixture must mirror a real ingest that misses the wedge"

    snapshot = {n: sha(repo / SHARDS / n) for n in shard_files(repo)}
    mem = sha(repo / "MEMORY.md")
    empty = tool(repo, "flush")
    assert empty.returncode == 1 and "ds-memory-capture repair --ref" in empty.stdout, empty.stdout
    write_inbox(repo, "- **%s:** queued after the merge" % DATE)
    hinted = tool(repo, "flush")
    assert hinted.returncode == 1 and "ds-memory-capture repair --ref" in hinted.stdout
    assert "queued after the merge" in inbox_text(repo) and sha(repo / "MEMORY.md") == mem

    at_merge = tool(repo, "repair", "--ref", "HEAD")
    assert at_merge.returncode == 1 and "colliding shards exist at HEAD" in at_merge.stdout, at_merge.stdout
    assert {n: sha(repo / SHARDS / n) for n in shard_files(repo)} == snapshot

    r = tool(repo, "repair", "--ref", "main")

    assert r.returncode == 0, r.stdout
    assert "repair: commit these shard changes:" in r.stdout
    assert compiler(repo, "regenerate", "--check").returncode == 0
    seqs = [re.search(r"^sequence: (-?\d+)$", (repo / SHARDS / n).read_text(), re.M).group(1)
            for n in shard_files(repo)]
    assert len(seqs) == len(set(seqs)) == 5


def test_j_repair_restores_a_shard_whose_line_is_missing(tmp_path):
    """The only copy of a fact must survive a `repair` that cannot re-capture
    it. Mutation: drop the re-capture check."""
    repo = make_repo(tmp_path)
    committed = (repo / "MEMORY.md").read_text()
    write_inbox(repo, "- **%s:** sole-copy fact" % DATE)
    assert tool(repo, "flush").returncode == 0
    new = shard_files(repo) - {"2026-01-01-a.md", "2026-01-02-b.md", "2026-01-03-c.md"}
    (name,) = new
    before = (repo / SHARDS / name).read_bytes()
    (repo / "MEMORY.md").write_text(committed)

    r = tool(repo, "repair", "--ref", "HEAD")

    assert r.returncode == 1, r.stdout
    assert "not re-captured" in r.stdout
    assert (repo / SHARDS / name).read_bytes() == before


def test_j_repair_failure_removes_shards_its_ingest_created(tmp_path):
    """On a failed repair, ingest may already have captured some other line
    (here a hand-added one); that shard must go too, or a rollback leaves a
    shard nobody committed to. Mutation: skip the cleanup of new shards."""
    repo = make_repo(tmp_path)
    committed = (repo / "MEMORY.md").read_text()
    write_inbox(repo, "- **%s:** sole-copy fact" % DATE)
    assert tool(repo, "flush").returncode == 0
    before = {n: sha(repo / SHARDS / n) for n in shard_files(repo)}
    (repo / "MEMORY.md").write_text(
        PREAMBLE_TEXT + "- **%s:** hand-added line\n" % DATE + committed[len(PREAMBLE_TEXT):])

    r = tool(repo, "repair", "--ref", "HEAD")

    assert r.returncode == 1 and "not re-captured" in r.stdout, r.stdout
    assert {n: sha(repo / SHARDS / n) for n in shard_files(repo)} == before


def test_j_repair_keeps_indexed_shards_absent_at_ref(tmp_path):
    """Only no-`index` shards are re-ingestable. Mutation: drop the index:
    filter, so the indexed shard is deleted too."""
    repo = make_repo(tmp_path)
    (repo / SHARDS / "2026-02-01-indexed.md").write_text(
        _shard(5000, "- **2026-02-01:** long fact D\n", 'index:\n  - "Rule D"'))
    (repo / "MEMORY.md").write_text(_compile(repo))

    r = tool(repo, "repair", "--ref", "HEAD")

    assert r.returncode == 0, r.stdout
    assert (repo / SHARDS / "2026-02-01-indexed.md").exists()
    assert compiler(repo, "regenerate", "--check").returncode == 0


def test_e_pre_existing_dated_line_is_reported_as_captured(tmp_path):
    """A dated line already in MEMORY.md is captured by the first ingest; it
    must get its own `captured:` record. Mutation: snapshot the shard set
    after the first ingest instead of before it."""
    repo = make_repo(tmp_path)
    mem = repo / "MEMORY.md"
    mem.write_text(PREAMBLE_TEXT + "- **%s:** hand-added line\n" % DATE + mem.read_text()[len(PREAMBLE_TEXT):])
    write_inbox(repo, "- **%s:** queued line" % DATE)

    r = tool(repo, "flush")

    assert r.returncode == 0, r.stdout
    assert r.stdout.count("captured: %s-session-" % DATE) == 2, r.stdout
    assert "flush: captured 2," in r.stdout


# ---------------------------------------------------------------------------
# (k), (l), (n)
# ---------------------------------------------------------------------------


def test_k_unresolved_mode_exits_1_and_keeps_entry(tmp_path):
    """Mutation: exit 2 (the standard-mode code) for unresolved mode."""
    repo = make_repo(tmp_path, preamble="No ingest command named here.\n\n")
    entry = "- **%s:** unresolved fact" % DATE
    write_inbox(repo, entry)
    mem = sha(repo / "MEMORY.md")

    r = tool(repo, "flush")

    assert r.returncode == 1, r.stdout
    assert inbox_text(repo) == entry + "\n"
    assert sha(repo / "MEMORY.md") == mem
    assert "two-tier-unresolved" in r.stdout


def test_k_usage_error_exits_3(tmp_path):
    repo = make_repo(tmp_path)
    assert tool(repo, "repair").returncode == 3
    assert tool(repo).returncode == 3


def test_l_exact_duplicate_is_dropped_not_requeued(tmp_path):
    """An inbox line byte-identical to an existing shard body (a re-read
    claimed file, or a re-run writer). Mutation: re-queue it."""
    repo = make_repo(tmp_path)
    write_inbox(repo, "- **2026-01-02:** old fact B")
    mem = sha(repo / "MEMORY.md")

    r = tool(repo, "flush")

    assert r.returncode == 0, r.stdout
    assert "skipped (duplicate): 2026-01-02-b" in r.stdout
    assert inbox_text(repo) == "" and sha(repo / "MEMORY.md") == mem


def test_l_multi_line_entry_is_requeued_with_reason(tmp_path):
    repo = make_repo(tmp_path)
    write_inbox(repo, "- **%s:** first line" % DATE, "  continuation")
    r = tool(repo, "flush")
    assert r.returncode == 1
    assert "first line\n  continuation\n" in inbox_text(repo)
    assert "requeued (not one line" in r.stdout


def _load_tool():
    loader = importlib.machinery.SourceFileLoader("ds_memory_capture", str(TOOL))
    spec = importlib.util.spec_from_loader("ds_memory_capture", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_n_line_written_after_claim_survives_to_next_flush(tmp_path, capsys):
    """A writer appending while a flush is in progress must not be lost.
    Mutation: truncate the inbox instead of renaming it at claim time."""
    repo = make_repo(tmp_path)
    write_inbox(repo, "- **%s:** first fact" % DATE)
    late = "- **%s:** written mid-flush" % DATE
    mod = _load_tool()
    real_claim = mod._claim_inbox

    def claim_then_write(d):
        claimed = real_claim(d)
        write_inbox(repo, late)
        return claimed

    mod._claim_inbox = claim_then_write
    assert mod.main(["--dir", str(repo), "flush"]) == 0
    assert inbox_text(repo) == late + "\n"
    assert not list((repo / ".agentic").glob("memory-capture-inbox.md.claimed-*"))

    r = tool(repo, "flush")
    assert r.returncode == 0 and inbox_text(repo) == ""
    assert "written mid-flush" in (repo / "MEMORY.md").read_text()
