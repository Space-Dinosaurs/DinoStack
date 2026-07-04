#!/usr/bin/env python3
"""
Purpose: Zero-dropped-rules verifier for the DS-68 methodology compression
         effort. Snapshots a "rule inventory" of methodology prose (bolded
         lead phrases, list items, imperative/modal paragraph leads, table
         rows, and fenced-block first lines) from a set of directories
         before an edit, then checks a post-edit snapshot of the same trees
         against it so that no rule silently vanishes during a relocation
         or compression pass. Also does a whole-line set diff as a second,
         coarser-grained mechanism so any dropped line - not just ones that
         match an anchor pattern - is caught. Both mechanisms are
         multiplicity-aware (collections.Counter, not a set): deleting one
         of N verbatim copies of a line/anchor decreases its count and must
         be covered by a mapping entry, even though the text still exists
         elsewhere in the scanned trees. Anchors shorter than
         ANCHOR_MIN_LEN (13 chars, post-normalization) are excluded from
         the anchor-presence test - they are near-zero-signal accidental
         substrings and the whole-line mechanism already covers the lines
         they came from.

Public API: extract-rule-inventory.py snapshot --scan <dir>... --out <file>
            extract-rule-inventory.py check --before <snapshot.json>
                                             --scan <dir>... [--mapping <file>]
            extract-rule-inventory.py --self-test
            Importable helpers: extract_anchors(text), extract_lines(text),
            build_snapshot(dirs), check_snapshot(before, dirs, mapping).

Upstream deps: Python 3 stdlib only (argparse, json, re, subprocess,
               pathlib, datetime, sys). `git rev-parse HEAD` (best-effort;
               falls back to null on failure or outside a git repo).

Downstream consumers: DS-68 compression workflow (unit 0 baseline snapshot,
                      unit 10 final check); no other module imports this.

Failure modes: `snapshot` writes a JSON file; missing --out parent dir is
               created. `check` never mutates input files; a mapping file
               that does not parse as JSON, or is malformed, is treated as
               a hard error (`raise SystemExit(2)` - exit code 2) rather
               than silently ignored, since a broken mapping would
               otherwise mask real drops. `check` exits 0 only when zero
               anchors/lines DECREASED in occurrence count without mapping
               coverage; otherwise exit 1 and the full UNMAPPED/
               UNACCOUNTED list is printed (a distinct code from the
               mapping-parse-error exit 2, so the two failure classes never
               collide). A single mapping entry accounting for more than
               BLANKET_ENTRY_WARN_THRESHOLD (20) vanished/decreased lines
               prints a WARNING line (does not fail the gate by itself -
               it is a visibility flag for reviewers). `--self-test` never
               touches the real filesystem outside a temp directory it
               creates and cleans up itself.

Performance: O(total bytes across scanned .md files); single pass per
             directory tree; suitable for interactive use on a docs tree
             of a few hundred files.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Optional

MAX_ANCHOR_LEN = 80

# MINOR-1: anchors shorter than this floor (post-normalization) survive as
# accidental substrings almost anywhere and carry near-zero presence signal;
# the whole-line mechanism (Mechanism B) still covers the lines they came
# from, so they are excluded from the anchor-presence test entirely (not
# just filtered at report time - dropped at extraction so before/after
# multiplicity accounting never has to reason about them).
ANCHOR_MIN_LEN = 13

# MINOR-2: a single mapping entry accounting for more vanished/decreased
# lines than this is flagged with a WARNING (not a FAIL) so a reviewer can
# eyeball whether an over-broad blanket entry is masking real drops.
BLANKET_ENTRY_WARN_THRESHOLD = 20

BOLD_LEAD_RE = re.compile(r"^\*\*(.+?)\*\*")
LIST_PREFIX_RE = re.compile(r"^(?:>\s*)?(?:[-*]\s+|\d+\.\s+)?")
LIST_ITEM_RE = re.compile(r"^(?:[-*]\s+|\d+\.\s+)(.*)$")
TABLE_ROW_RE = re.compile(r"^\|.*\|$")
FENCE_RE = re.compile(r"^```")

IMPERATIVE_PREFIXES = (
    "MUST",
    "Never",
    "Always",
    "Do not",
    "The conductor",
    "Workers",
)
IMPERATIVE_LOWER_PREFIXES = (
    "never ",
    "always ",
    "do not ",
)


def normalize_ws(s: str) -> str:
    """Whitespace-normalize: collapse all runs of whitespace to a single space, strip ends."""
    return re.sub(r"\s+", " ", s).strip()


def truncate(s: str, n: int = MAX_ANCHOR_LEN) -> str:
    return s[:n]


def strip_list_prefix(line: str) -> str:
    """Strip an optional blockquote/list prefix before checking for a bold lead."""
    return LIST_PREFIX_RE.sub("", line, count=1)


def extract_anchors(text: str) -> list[str]:
    """Extract Mechanism A anchors from a single markdown file's text.

    Returns a list of anchor strings (whitespace-normalized, truncated to
    MAX_ANCHOR_LEN, and floored at ANCHOR_MIN_LEN - see MINOR-1). Order is
    not significant to callers - a snapshot stores the sorted, de-duplicated
    set.
    """
    anchors: list[str] = []
    lines = text.splitlines()

    # 1. Bolded lead phrases (per-line).
    for raw_line in lines:
        candidate = strip_list_prefix(raw_line)
        m = BOLD_LEAD_RE.match(candidate)
        if m:
            anchors.append(truncate(normalize_ws(m.group(1))))

    # 2. List items (first 80 chars of the item body).
    for raw_line in lines:
        m = LIST_ITEM_RE.match(raw_line.lstrip())
        if m:
            anchors.append(truncate(normalize_ws(m.group(1))))

    # 3. Imperative/modal paragraph leads. A paragraph is a run of
    #    non-blank lines; only the first line of the paragraph is checked.
    paragraphs = _split_paragraphs(lines)
    for para_first_line in paragraphs:
        stripped = strip_list_prefix(para_first_line).lstrip()
        # Strip a leading bold marker so "**MUST** do X" still matches.
        bold_stripped = BOLD_LEAD_RE.sub(lambda mm: mm.group(1), stripped, count=1)
        if bold_stripped.startswith(IMPERATIVE_PREFIXES):
            anchors.append(truncate(normalize_ws(bold_stripped)))
            continue
        if bold_stripped.startswith(IMPERATIVE_LOWER_PREFIXES):
            anchors.append(truncate(normalize_ws(bold_stripped)))

    # 4. Table rows and fenced-block first lines.
    in_fence = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if FENCE_RE.match(stripped):
            if not in_fence:
                in_fence = True
                # The fence marker line itself is the "first line" of the block.
                anchors.append(truncate(normalize_ws(stripped)))
            else:
                in_fence = False
            continue
        if TABLE_ROW_RE.match(stripped):
            anchors.append(truncate(normalize_ws(stripped)))

    # De-duplicate while preserving determinism; empty anchors are noise,
    # and anchors shorter than ANCHOR_MIN_LEN are excluded (MINOR-1) - they
    # survive as accidental substrings almost anywhere and the whole-line
    # mechanism already covers the lines they came from.
    return sorted({a for a in anchors if a and len(a) >= ANCHOR_MIN_LEN})


def _split_paragraphs(lines: list[str]) -> list[str]:
    """Return the first line of every paragraph (run of non-blank lines)."""
    firsts: list[str] = []
    in_para = False
    for line in lines:
        if line.strip() == "":
            in_para = False
            continue
        if not in_para:
            firsts.append(line)
            in_para = True
    return firsts


def extract_lines(text: str) -> list[str]:
    """Mechanism B: whole-line set. Non-blank, whitespace-normalized lines."""
    out = []
    for raw_line in text.splitlines():
        norm = normalize_ws(raw_line)
        if norm:
            out.append(norm)
    return out


def iter_md_files(dirs: list[str]) -> list[Path]:
    files: list[Path] = []
    for d in dirs:
        p = Path(d)
        if not p.exists():
            continue
        if p.is_file():
            if p.suffix == ".md":
                files.append(p)
            continue
        files.extend(sorted(p.rglob("*.md")))
    return sorted(set(files))


def git_head() -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def build_snapshot(dirs: list[str]) -> dict:
    """Build a rule-inventory snapshot, multiplicity-aware (MAJOR-1).

    `anchor_counts` / `line_counts` record, per anchor/line, how many
    scanned files contain it (extract_anchors/extract_lines are called
    per-file, so a repeat within one file counts once per anchor but every
    literal line occurrence for lines - see extract_lines). Deleting one of
    N verbatim copies of a line/anchor decreases its count even though the
    text is still present (as a set member) elsewhere in the trees - this
    is exactly the multiplicity-blindness fix: `check_snapshot` compares
    counts, not mere presence. `anchors` / `lines` remain as sorted
    de-duplicated lists for stats/reporting convenience; they are derived
    from the same Counters (their keys), not an independent computation.
    """
    anchor_counts: Counter[str] = Counter()
    line_counts: Counter[str] = Counter()
    per_dir_stats: dict[str, dict[str, int]] = {}

    for d in dirs:
        files = iter_md_files([d])
        dir_anchors: set[str] = set()
        dir_lines: set[str] = set()
        for f in files:
            text = f.read_text(encoding="utf-8", errors="replace")
            file_anchors = extract_anchors(text)
            file_lines = extract_lines(text)
            anchor_counts.update(file_anchors)
            line_counts.update(file_lines)
            dir_anchors.update(file_anchors)
            dir_lines.update(file_lines)
        per_dir_stats[d] = {
            "files": len(files),
            "anchors": len(dir_anchors),
            "lines": len(dir_lines),
        }

    return {
        "anchors": sorted(anchor_counts),
        "lines": sorted(line_counts),
        "anchor_counts": dict(sorted(anchor_counts.items())),
        "line_counts": dict(sorted(line_counts.items())),
        "meta": {
            "git_head": git_head(),
            "timestamp": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
            "dirs": dirs,
            "per_dir_stats": per_dir_stats,
        },
    }


def load_mapping(path: Optional[str]) -> list[dict]:
    """Load and validate a mapping file.

    MINOR-3a: a malformed mapping (unparseable JSON, or a JSON value that
    is neither a list nor {"entries": [...]}) is a hard error distinct from
    a gate FAIL (exit 1) - it exits 2, since a broken mapping would
    otherwise silently mask real drops rather than fail loudly. Passing a
    string to SystemExit (the prior behavior) actually yields exit code 1,
    colliding with gate-FAIL; printing to stderr and raising
    SystemExit(2) explicitly avoids that collision.
    """
    if not path:
        return []
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FATAL: mapping file {path!r} failed to parse: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if isinstance(data, dict):
        data = data.get("entries", [])
    if not isinstance(data, list):
        print(f"FATAL: mapping file {path!r} must be a JSON list or {{'entries': [...]}}", file=sys.stderr)
        raise SystemExit(2)
    return data


def check_snapshot(before: dict, dirs: list[str], mapping: list[dict]) -> tuple[bool, str]:
    """Compare a BEFORE snapshot against the current state of `dirs`.

    MAJOR-1 (multiplicity-aware): the prior implementation compared
    presence in a SET, so deleting one of N verbatim copies of a line or
    anchor passed silently as long as at least one copy survived anywhere
    in the scanned trees - exactly the DS-68 in-tree-dedup use case
    (pointer-replacing a duplicated copy). This version compares BEFORE
    vs AFTER occurrence *counts* (collections.Counter) per anchor/line: a
    decrease in count is flagged unless a mapping entry (Compressed or
    Pointer-replaced) accounts for it. A pure relocation (count unchanged,
    position moved) still passes with no mapping entry required.

    Returns (ok, report_text).
    """
    after = build_snapshot(dirs)
    after_anchor_counts: Counter[str] = Counter(after.get("anchor_counts", {}))
    after_line_counts: Counter[str] = Counter(after.get("line_counts", {}))

    # Back-compat: a BEFORE snapshot predating this fix carries only the
    # deduplicated `anchors`/`lines` lists (no counts) - treat each as
    # count 1 rather than hard-failing on a missing key.
    before_anchor_counts: Counter[str] = Counter(before.get("anchor_counts") or {})
    if not before_anchor_counts and before.get("anchors"):
        before_anchor_counts = Counter({a: 1 for a in before["anchors"]})
    before_line_counts: Counter[str] = Counter(before.get("line_counts") or {})
    if not before_line_counts and before.get("lines"):
        before_line_counts = Counter({line: 1 for line in before["lines"]})

    # Mapped text: any BEFORE line/anchor covered by a mapping entry tagged
    # Compressed or Pointer-replaced is considered accounted for. An entry's
    # `before` text may span a whole paragraph (multiple original lines
    # joined), so containment - not exact equality - is the correct test:
    # a vanished single line is "mapped" if it appears verbatim inside the
    # entry's recorded before-text. Entries are kept indexed (not flattened)
    # so MINOR-2 can attribute accounted-line counts back to their entry.
    mapping_entries: list[tuple[int, list[str]]] = []
    for idx, entry in enumerate(mapping):
        if not isinstance(entry, dict):
            continue
        tag = entry.get("status") or entry.get("tag")
        if tag not in ("Compressed", "Pointer-replaced"):
            continue
        texts = []
        before_text = entry.get("before") or entry.get("before_line")
        if before_text:
            texts.append(normalize_ws(before_text))
        # Support a batch form: {"status": "Compressed", "before_lines": [...]}
        for bl in entry.get("before_lines", []) or []:
            texts.append(normalize_ws(bl))
        if texts:
            mapping_entries.append((idx, texts))
    mapped_texts = [t for _, texts in mapping_entries for t in texts]

    def _is_mapped(item: str) -> bool:
        return any(item in text for text in mapped_texts)

    # Anchors: only ANCHOR_MIN_LEN-and-above anchors reach here at all
    # (extract_anchors already floors them - MINOR-1).
    unmapped_anchors = []  # (anchor, before_count, after_count)
    for anchor, before_count in before_anchor_counts.items():
        after_count = after_anchor_counts.get(anchor, 0)
        if after_count < before_count and not _is_mapped(anchor):
            unmapped_anchors.append((anchor, before_count, after_count))

    decreased_lines = []  # every line whose count went down, mapped or not
    unaccounted_lines = []  # (line, before_count, after_count) - not mapped
    for line, before_count in before_line_counts.items():
        after_count = after_line_counts.get(line, 0)
        if after_count < before_count:
            decreased_lines.append(line)
            if not _is_mapped(line):
                unaccounted_lines.append((line, before_count, after_count))

    # MINOR-2: flag any single mapping entry that accounts for an
    # over-broad number of decreased lines - a visibility warning, not a
    # gate failure by itself.
    entry_accounted_counts: list[tuple[int, str, int]] = []  # (idx, tag/label, accounted)
    blanket_warnings: list[tuple[int, str, int]] = []
    for idx, texts in mapping_entries:
        accounted = sum(1 for line in decreased_lines if any(line in t for t in texts))
        entry = mapping[idx]
        tag = entry.get("status") or entry.get("tag") or "?"
        label = truncate(normalize_ws(entry.get("before") or entry.get("before_line") or f"(entry #{idx})"))
        entry_accounted_counts.append((idx, f"{tag}: {label}", accounted))
        if accounted > BLANKET_ENTRY_WARN_THRESHOLD:
            blanket_warnings.append((idx, f"{tag}: {label}", accounted))

    lines_report = []
    lines_report.append("=== Rule Inventory Check ===")
    lines_report.append(
        f"BEFORE anchors: {len(before_anchor_counts)}  BEFORE lines: {len(before_line_counts)}"
    )
    lines_report.append(
        f"AFTER  anchors: {len(after_anchor_counts)}  AFTER  lines: {len(after_line_counts)}"
    )
    lines_report.append(f"Mapping entries loaded: {len(mapping)} (Compressed/Pointer-replaced: {len(mapping_entries)})")
    lines_report.append("")
    lines_report.append(
        f"UNMAPPED anchors (count decreased BEFORE->AFTER, no mapping): {len(unmapped_anchors)}"
    )
    for a, bc, ac in unmapped_anchors:
        lines_report.append(f"  UNMAPPED ANCHOR: {a} (before={bc} after={ac})")
    lines_report.append("")
    lines_report.append(
        f"Decreased whole-lines: {len(decreased_lines)} "
        f"(unaccounted: {len(unaccounted_lines)})"
    )
    for line, bc, ac in unaccounted_lines:
        lines_report.append(f"  UNACCOUNTED LINE: {line} (before={bc} after={ac})")
    lines_report.append("")
    lines_report.append("Per-entry accounted-line counts (Compressed/Pointer-replaced entries):")
    if entry_accounted_counts:
        for idx, label, accounted in entry_accounted_counts:
            lines_report.append(f"  entry #{idx} [{label}]: accounts for {accounted} decreased line(s)")
    else:
        lines_report.append("  (none)")
    for idx, label, accounted in blanket_warnings:
        lines_report.append(
            f"  WARNING: entry #{idx} [{label}] accounts for {accounted} decreased lines "
            f"(> {BLANKET_ENTRY_WARN_THRESHOLD} threshold) - verify this entry is not "
            f"masking an unrelated drop"
        )

    ok = len(unmapped_anchors) == 0 and len(unaccounted_lines) == 0
    lines_report.append("")
    lines_report.append("RESULT: PASS" if ok else "RESULT: FAIL")
    return ok, "\n".join(lines_report)


def cmd_snapshot(args: argparse.Namespace) -> int:
    snap = build_snapshot(args.scan)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote snapshot: {out_path}")
    print(f"  anchors: {len(snap['anchors'])}  lines: {len(snap['lines'])}")
    for d, stats in snap["meta"]["per_dir_stats"].items():
        print(f"  {d}: files={stats['files']} anchors={stats['anchors']} lines={stats['lines']}")
    print(f"  git_head: {snap['meta']['git_head']}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    before_path = Path(args.before)
    try:
        before = json.loads(before_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FATAL: could not read/parse --before snapshot {args.before!r}: {exc}", file=sys.stderr)
        return 2
    mapping = load_mapping(args.mapping)
    ok, report = check_snapshot(before, args.scan, mapping)
    print(report)
    return 0 if ok else 1


# --------------------------------------------------------------------------
# Self-test: embedded fixture proving relocation passes, compression-with-
# mapping passes, a deliberate drop is caught, a duplicated-copy drop is
# caught (MAJOR-1 regression - this case must FAIL against the old
# set-semantics logic), the same duplicated-copy drop passes when mapped,
# and an over-broad blanket mapping entry emits a WARNING (MINOR-2).
# --------------------------------------------------------------------------

_FIXTURE_BEFORE = {
    "a.md": (
        "**Relocated Rule** applies to all workers and must not be skipped.\n\n"
        "- keep this list item across the edit\n\n"
        "MUST validate every input before use.\n\n"
        "This line will be dropped without any mapping entry at all.\n"
    ),
    "b.md": (
        "This paragraph is long and repetitive in the before-tree and will be\n"
        "compressed down to a single shorter sentence in the after-tree, but\n"
        "it is recorded in the mapping file as Compressed so the check passes.\n"
    ),
}

_FIXTURE_AFTER_PASS = {
    # a.md's content relocated verbatim into c.md (new filename, same
    # content - simulating a section move to a different file); b.md's
    # paragraph is compressed with a mapping entry covering the drop.
    "c.md": (
        "**Relocated Rule** applies to all workers and must not be skipped.\n\n"
        "- keep this list item across the edit\n\n"
        "MUST validate every input before use.\n\n"
        "This line will be dropped without any mapping entry at all.\n"
    ),
    "b.md": (
        "This paragraph is compressed now.\n"
    ),
}

_FIXTURE_AFTER_DROP = {
    "c.md": (
        "**Relocated Rule** applies to all workers and must not be skipped.\n\n"
        "- keep this list item across the edit\n\n"
        "MUST validate every input before use.\n\n"
        # the drop-line is gone here, with no mapping entry - must be caught
    ),
    "b.md": (
        "This paragraph is compressed now.\n"
    ),
}

_FIXTURE_MAPPING = [
    {
        "status": "Compressed",
        "before": (
            "This paragraph is long and repetitive in the before-tree and will be "
            "compressed down to a single shorter sentence in the after-tree, but "
            "it is recorded in the mapping file as Compressed so the check passes."
        ),
    }
]

# Case 4/5: duplicated-copy drop - the SAME bold-lead anchor + whole line
# appears verbatim in two files (count=2). Dropping it from one file with
# no mapping entry must FAIL (this is the MAJOR-1 regression test - the
# old set-semantics logic would PASS here because the text still exists in
# x.md). Dropping it WITH a Pointer-replaced mapping entry must PASS.
_DUP_LINE = "**Duplicated Rule Anchor** must appear in two files at once and be tracked by count."

_FIXTURE_DUP_BEFORE = {
    "x.md": _DUP_LINE + "\n",
    "y.md": _DUP_LINE + "\n",
}

_FIXTURE_DUP_AFTER = {
    # x.md keeps its copy; y.md's copy is replaced by unrelated content -
    # the duplicated anchor/line's occurrence count drops from 2 to 1.
    "x.md": _DUP_LINE + "\n",
    "y.md": "This file now says something completely different and unrelated.\n",
}

_FIXTURE_DUP_MAPPING = [
    {
        "status": "Pointer-replaced",
        "before": _DUP_LINE,
    }
]

# Case 6: a single over-broad "Compressed" mapping entry whose before-text
# is a 25-line blanket paragraph - every one of those 25 lines vanishes,
# all accounted for by the ONE entry, which must trip the MINOR-2
# BLANKET_ENTRY_WARN_THRESHOLD (20) WARNING.
_BLANKET_LINES = [
    f"This is unique disposable line number {i} in the blanket paragraph." for i in range(1, 26)
]
_FIXTURE_BLANKET_BEFORE = {"blanket.md": "\n".join(_BLANKET_LINES) + "\n"}
_FIXTURE_BLANKET_AFTER = {"blanket.md": "This paragraph has been fully compressed into one summary sentence.\n"}
_FIXTURE_BLANKET_MAPPING = [
    {
        "status": "Compressed",
        "before": "\n".join(_BLANKET_LINES),
    }
]


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")


def run_self_test() -> int:
    all_pass = True

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        before_dir = tmp_path / "before"
        after_pass_dir = tmp_path / "after_pass"
        after_drop_dir = tmp_path / "after_drop"
        dup_before_dir = tmp_path / "dup_before"
        dup_after_dir = tmp_path / "dup_after"
        blanket_before_dir = tmp_path / "blanket_before"
        blanket_after_dir = tmp_path / "blanket_after"
        for d in (
            before_dir,
            after_pass_dir,
            after_drop_dir,
            dup_before_dir,
            dup_after_dir,
            blanket_before_dir,
            blanket_after_dir,
        ):
            d.mkdir()
        _write_tree(before_dir, _FIXTURE_BEFORE)
        _write_tree(after_pass_dir, _FIXTURE_AFTER_PASS)
        _write_tree(after_drop_dir, _FIXTURE_AFTER_DROP)
        _write_tree(dup_before_dir, _FIXTURE_DUP_BEFORE)
        _write_tree(dup_after_dir, _FIXTURE_DUP_AFTER)
        _write_tree(blanket_before_dir, _FIXTURE_BLANKET_BEFORE)
        _write_tree(blanket_after_dir, _FIXTURE_BLANKET_AFTER)

        before_snap = build_snapshot([str(before_dir)])

        # Case 1: relocation - anchors/lines moved verbatim into a new file
        # name/dir; the relocated bold-lead anchor must survive the check
        # with zero UNMAPPED entries for it.
        ok_pass, report_pass = check_snapshot(before_snap, [str(after_pass_dir)], _FIXTURE_MAPPING)
        case1_relocated_anchor_ok = "UNMAPPED ANCHOR: Relocated Rule" not in report_pass
        print("=== Case 1: relocation (anchor survives verbatim in new file/location) ===")
        print("PASS" if case1_relocated_anchor_ok else "FAIL")
        all_pass = all_pass and case1_relocated_anchor_ok

        print("\n=== Case 2: compression with mapping entry (dropped line, mapped) ===")
        case2_ok = ok_pass  # full after_pass tree: relocation + compression + drop-line preserved verbatim
        print("PASS" if case2_ok else "FAIL")
        print(report_pass)
        all_pass = all_pass and case2_ok

        print("\n=== Case 3: deliberate drop is caught (no mapping entry, exit 1) ===")
        ok_drop, report_drop = check_snapshot(before_snap, [str(after_drop_dir)], _FIXTURE_MAPPING)
        case3_ok = (not ok_drop) and ("This line will be dropped without any mapping entry at all." in report_drop)
        print("PASS" if case3_ok else "FAIL")
        print(report_drop)
        all_pass = all_pass and case3_ok

        # Case 4 (MAJOR-1 regression): duplicated-copy drop, no mapping.
        # Must FAIL - this is the exact scenario old set-semantics logic
        # let through (text still exists verbatim in x.md).
        print("\n=== Case 4: duplicated-copy drop, no mapping (MAJOR-1 regression) ===")
        dup_before_snap = build_snapshot([str(dup_before_dir)])
        ok_dup_nomap, report_dup_nomap = check_snapshot(dup_before_snap, [str(dup_after_dir)], [])
        case4_ok = (
            not ok_dup_nomap
            and "UNMAPPED ANCHOR: Duplicated Rule Anchor" in report_dup_nomap
            and f"UNACCOUNTED LINE: {_DUP_LINE}" in report_dup_nomap
        )
        print("PASS" if case4_ok else "FAIL")
        print(report_dup_nomap)
        all_pass = all_pass and case4_ok

        # Case 5: same duplicated-copy drop, but WITH a Pointer-replaced
        # mapping entry covering it - must PASS.
        print("\n=== Case 5: duplicated-copy drop, WITH Pointer-replaced mapping entry ===")
        ok_dup_mapped, report_dup_mapped = check_snapshot(
            dup_before_snap, [str(dup_after_dir)], _FIXTURE_DUP_MAPPING
        )
        case5_ok = ok_dup_mapped
        print("PASS" if case5_ok else "FAIL")
        print(report_dup_mapped)
        all_pass = all_pass and case5_ok

        # Case 6 (MINOR-2): a single blanket "Compressed" entry accounting
        # for 25 (> BLANKET_ENTRY_WARN_THRESHOLD) decreased lines must
        # trip the WARNING - the gate still PASSes (the drop is mapped),
        # but the WARNING line must be present for reviewer visibility.
        print("\n=== Case 6: over-broad blanket mapping entry emits WARNING (MINOR-2) ===")
        blanket_before_snap = build_snapshot([str(blanket_before_dir)])
        ok_blanket, report_blanket = check_snapshot(
            blanket_before_snap, [str(blanket_after_dir)], _FIXTURE_BLANKET_MAPPING
        )
        case6_ok = ok_blanket and "WARNING: entry #0" in report_blanket and "accounts for 25 decreased lines" in report_blanket
        print("PASS" if case6_ok else "FAIL")
        print(report_blanket)
        all_pass = all_pass and case6_ok

    print("\n=== Self-test summary ===")
    print("ALL CASES PASS" if all_pass else "SOME CASES FAILED")
    return 0 if all_pass else 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="extract-rule-inventory.py",
        description="Zero-dropped-rules verifier for methodology compression edits.",
    )
    parser.add_argument("--self-test", action="store_true", help="run the embedded fixture self-test and exit")
    sub = parser.add_subparsers(dest="command")

    p_snap = sub.add_parser("snapshot", help="build and write a rule-inventory snapshot")
    p_snap.add_argument("--scan", nargs="+", required=True, help="directories (or .md files) to scan")
    p_snap.add_argument("--out", required=True, help="output JSON snapshot path")
    p_snap.set_defaults(func=cmd_snapshot)

    p_check = sub.add_parser("check", help="check a BEFORE snapshot against the current tree")
    p_check.add_argument("--before", required=True, help="path to a BEFORE snapshot JSON file")
    p_check.add_argument("--scan", nargs="+", required=True, help="directories (or .md files) to scan as AFTER")
    p_check.add_argument("--mapping", default=None, help="optional mapping JSON file (Compressed / Pointer-replaced entries)")
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)

    if args.__dict__.get("self_test"):
        return run_self_test()

    if not getattr(args, "command", None):
        parser.print_help()
        return 2

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
