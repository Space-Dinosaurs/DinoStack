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
         match an anchor pattern - is caught.

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
               that does not parse as JSON is treated as a hard error
               (exit 2) rather than silently ignored, since a broken
               mapping would otherwise mask real drops. `check` exits 0
               only when zero anchors are UNMAPPED and zero lines vanished
               unaccounted for; otherwise exit 1 and the full UNMAPPED
               list is printed. `--self-test` never touches the real
               filesystem outside a temp directory it creates and cleans
               up itself.

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
from pathlib import Path
from typing import Optional

MAX_ANCHOR_LEN = 80

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
    MAX_ANCHOR_LEN). Order is not significant to callers - a snapshot stores
    the sorted, de-duplicated set.
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

    # De-duplicate while preserving determinism; empty anchors are noise.
    return sorted({a for a in anchors if a})


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
    all_anchors: set[str] = set()
    all_lines: set[str] = set()
    per_dir_stats: dict[str, dict[str, int]] = {}

    for d in dirs:
        files = iter_md_files([d])
        dir_anchors: set[str] = set()
        dir_lines: set[str] = set()
        for f in files:
            text = f.read_text(encoding="utf-8", errors="replace")
            dir_anchors.update(extract_anchors(text))
            dir_lines.update(extract_lines(text))
        all_anchors.update(dir_anchors)
        all_lines.update(dir_lines)
        per_dir_stats[d] = {
            "files": len(files),
            "anchors": len(dir_anchors),
            "lines": len(dir_lines),
        }

    return {
        "anchors": sorted(all_anchors),
        "lines": sorted(all_lines),
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
    if not path:
        return []
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FATAL: mapping file {path!r} failed to parse: {exc}") from exc
    if isinstance(data, dict):
        data = data.get("entries", [])
    if not isinstance(data, list):
        raise SystemExit(f"FATAL: mapping file {path!r} must be a JSON list or {{'entries': [...]}}")
    return data


def check_snapshot(before: dict, dirs: list[str], mapping: list[dict]) -> tuple[bool, str]:
    """Compare a BEFORE snapshot against the current state of `dirs`.

    Returns (ok, report_text).
    """
    after = build_snapshot(dirs)
    after_anchor_set = set(after["anchors"])
    after_line_set = set(after["lines"])
    # The after-corpus for substring matching includes both anchors and
    # whole lines, per the spec ("appear ... somewhere in the scanned
    # trees" against "anchors+lines").
    after_corpus = list(after_anchor_set) + list(after_line_set)

    before_anchors = before.get("anchors", [])
    before_lines = before.get("lines", [])

    unmapped_anchors = []
    for anchor in before_anchors:
        if not any(anchor in hay for hay in after_corpus):
            unmapped_anchors.append(anchor)

    # Mapped text: any BEFORE line covered by a mapping entry tagged
    # Compressed or Pointer-replaced is considered accounted for. An entry's
    # `before` text may span a whole paragraph (multiple original lines
    # joined), so containment - not exact equality - is the correct test:
    # a vanished single line is "mapped" if it appears verbatim inside the
    # entry's recorded before-text.
    mapped_texts = []
    for entry in mapping:
        if not isinstance(entry, dict):
            continue
        tag = entry.get("status") or entry.get("tag")
        if tag in ("Compressed", "Pointer-replaced"):
            before_text = entry.get("before") or entry.get("before_line")
            if before_text:
                mapped_texts.append(normalize_ws(before_text))
            # Support a batch form: {"status": "Compressed", "before_lines": [...]}
            for bl in entry.get("before_lines", []) or []:
                mapped_texts.append(normalize_ws(bl))

    vanished_lines = [line for line in before_lines if line not in after_line_set]
    unaccounted_lines = [
        line for line in vanished_lines if not any(line in text for text in mapped_texts)
    ]

    lines_report = []
    lines_report.append("=== Rule Inventory Check ===")
    lines_report.append(f"BEFORE anchors: {len(before_anchors)}  BEFORE lines: {len(before_lines)}")
    lines_report.append(f"AFTER  anchors: {len(after['anchors'])}  AFTER  lines: {len(after['lines'])}")
    lines_report.append(f"Mapping entries loaded: {len(mapping)}")
    lines_report.append("")
    lines_report.append(f"UNMAPPED anchors (present BEFORE, absent AFTER, no mapping): {len(unmapped_anchors)}")
    for a in unmapped_anchors:
        lines_report.append(f"  UNMAPPED ANCHOR: {a}")
    lines_report.append("")
    lines_report.append(
        f"Vanished whole-lines: {len(vanished_lines)} "
        f"(unaccounted: {len(unaccounted_lines)})"
    )
    for line in unaccounted_lines:
        lines_report.append(f"  UNACCOUNTED LINE: {line}")

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
# mapping passes, and a deliberate drop is caught.
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
        for d in (before_dir, after_pass_dir, after_drop_dir):
            d.mkdir()
        _write_tree(before_dir, _FIXTURE_BEFORE)
        _write_tree(after_pass_dir, _FIXTURE_AFTER_PASS)
        _write_tree(after_drop_dir, _FIXTURE_AFTER_DROP)

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
