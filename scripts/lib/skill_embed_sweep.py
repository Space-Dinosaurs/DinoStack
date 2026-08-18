#!/usr/bin/env python3
"""
Purpose: Byte-exact candidate builder for the skill-embed injection sweep
         harness (DS-45). Given an already-built base SKILL.md, a target
         byte size, and a sweep id, produces a candidate file that pads the
         base content with inert, obviously-synthetic numbered marker lines
         plus a tail block declaring the pad-line count and a sha256 of the
         pad block - so a reader with only the injected content (no
         filesystem access, no diff tool) can tell a genuine tail from a
         truncation boundary that happens to look complete: a truncated
         file either cuts off mid-pad-line (visibly malformed), stops short
         of the declared count (a numbering gap the reader can count), or
         is simply missing the DS-45-SWEEP-END-OF-FILE marker and its hash
         entirely. Padding uses only synthetic HTML-comment marker lines
         (never prose resembling real methodology content), so a padded
         build accidentally left installed cannot be mistaken for real
         guidance.

Public API: build_candidate(base_path: str, target_bytes: int,
                             out_path: str, sweep_id: str | None = None)
                             -> dict (sweep_id, num_pad_lines, actual_bytes)
            paths_refer_to_same_file(path_a: str, path_b: str) -> bool -
                             case-insensitive/symlink/hardlink-aware "same
                             on-disk file" comparison (DS-45 round-2
                             Critical fix - see its own docstring).
            Also runnable as a CLI - see main()/--help, including the
            `check-out-refusal` subcommand
            scripts/skill-embed-sweep-harness.sh's `candidate` subcommand
            shells out to for its real-SKILL.md write guard; nothing else
            in this repo imports this module.

Upstream deps: Python 3 stdlib only (hashlib, os, pathlib, argparse,
               secrets). No third-party packages, no network.

Downstream consumers: scripts/skill-embed-sweep-harness.sh (candidate
                       subcommand); bin/tests/test_skill_embed_sweep_harness.sh.

Failure modes: raises ValueError if target_bytes is smaller than the
               minimum viable candidate size (base content + head marker +
               a zero-pad-line tail block) - there is no way to shrink a
               candidate below its base content, so the caller must pick a
               larger --target-bytes or a smaller --base. Raises
               RuntimeError if the assembled candidate's measured byte
               length does not exactly equal target_bytes (a defensive
               self-check on the padding arithmetic; should never fire).
               Never writes to base_path - read-only. Writes only to
               out_path; callers (the shell entrypoint) are responsible
               for ensuring out_path is never the real, tracked SKILL.md -
               this module has no knowledge of that path and enforces
               nothing about it.

Performance: single pass, O(target_bytes). Target sizes here are on the
             order of ~150 KB, so this runs in well under a second.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sys
from pathlib import Path

SWEEP_ID_LEN = 12  # hex chars; fixes PAD line width across all seq values
PAD_SEQ_WIDTH = 6  # zero-padded decimal digits, e.g. seq=000042
NUM_LINES_WIDTH = 8  # zero-padded decimal digits for declared_total_pad_lines

# Case-folded path tail this shape check refuses regardless of which
# checkout it is found under - see _tail_matches_skill_artifact_shape().
_SKILL_ARTIFACT_TAIL = (".claude", "skills", "dinostack", "skill.md")


def paths_refer_to_same_file(path_a: str, path_b: str) -> bool:
    """True if path_a and path_b resolve to the same on-disk file.

    Robust to: case-insensitive-but-preserving filesystems (macOS/APFS is
    the primary development platform this harness runs on), symlinks (a
    file symlink or a directory-symlink path component), hardlinks, '..'
    segments, and a relative-vs-absolute path mismatch.

    Mechanism: os.path.realpath resolves symlinks and '..' segments for
    both paths, and does so even when the target does not yet exist - it
    resolves as much of the path as exists on disk and appends whatever
    remaining components do not yet exist, unchanged. When BOTH resolved
    paths exist on disk, an (st_dev, st_ino) stat comparison is used and
    is authoritative: that pair *is* what "same file" means at the
    filesystem level, and it is the only thing that also catches a
    hardlink - a hardlink has its own, unrelated path string, so no
    string comparison (case-folded or not) can ever detect one. When
    either resolved path does not yet exist (the common case for --out,
    which is normally about to be created), stat comparison is
    unavailable, so this explicitly falls back to a case-folded string
    comparison of the two resolved paths - conservative (a false refusal
    here is safe; a false negative is not), and it is what closes the
    case-insensitive-filesystem bypass this function was added for
    (DS-45 round-2 Critical: `--out .claude/skills/dinostack/skill.MD`
    resolved to a different os.path.realpath string than the real,
    lowercase-named file and so passed the previous string-equality
    guard outright, on a filesystem where the two paths are the same
    file on disk).
    """
    real_a = os.path.realpath(path_a)
    real_b = os.path.realpath(path_b)
    if os.path.exists(real_a) and os.path.exists(real_b):
        try:
            stat_a = os.stat(real_a)
            stat_b = os.stat(real_b)
            return (stat_a.st_dev, stat_a.st_ino) == (stat_b.st_dev, stat_b.st_ino)
        except OSError:
            pass  # fall through to the string-comparison fallback below
    return real_a.casefold() == real_b.casefold()


def _tail_matches_skill_artifact_shape(resolved_path: str) -> bool:
    """True if resolved_path's final four path components case-fold-match
    .claude/skills/dinostack/SKILL.md, regardless of which checkout it is
    under. Broadens the write guard from "the current repo's real file"
    (paths_refer_to_same_file against this REPO_DIR's REAL_SKILL_FILE) to
    "any checkout's real file" - this machine routinely has many live git
    worktrees, each with its own real SKILL.md at that same relative path,
    and each is an equally live, equally undesirable overwrite target
    (DS-45 round-2 Minor 1). Takes an already-realpath'd string (trailing
    slash and '..' segments already resolved) so this is a pure string
    check with no filesystem access of its own.
    """
    parts = tuple(
        part.casefold() for part in resolved_path.rstrip("/").split("/") if part != ""
    )
    return len(parts) >= 4 and parts[-4:] == _SKILL_ARTIFACT_TAIL


def _pad_line(sweep_id: str, seq: int) -> bytes:
    return (
        f"<!-- DS-45-SWEEP-PAD sweep_id={sweep_id} "
        f"seq={seq:0{PAD_SEQ_WIDTH}d} -->\n"
    ).encode("utf-8")


def _tail_block(sweep_id: str, num_lines: int, target_bytes: int, hash_hex: str) -> bytes:
    return (
        f"<!-- DS-45-SWEEP-TAIL sweep_id={sweep_id}\n"
        f"declared_total_pad_lines={num_lines:0{NUM_LINES_WIDTH}d}\n"
        f"declared_total_bytes={target_bytes}\n"
        f"pad_block_sha256={hash_hex}\n"
        f"DS-45-SWEEP-END-OF-FILE -->\n"
    ).encode("utf-8")


def _head_marker_line(sweep_id: str, target_bytes: int) -> bytes:
    return (
        f"<!-- DS-45-SWEEP-HEAD sweep_id={sweep_id} "
        f"target_bytes={target_bytes} -->"
    ).encode("utf-8")


def _insert_head_marker(base_bytes: bytes, head_marker_line: bytes) -> bytes:
    """Insert head_marker_line as its own line immediately after the
    frontmatter's closing '---' delimiter, if base_bytes opens with a YAML
    frontmatter block (first line exactly '---', a later line also exactly
    '---'). Otherwise prepend it as the first line. Uses split/join on b"\n"
    so the operation is exactly byte-preserving for the untouched portions
    (b"\n".join(base_bytes.split(b"\n")) == base_bytes is an invariant of
    split/join, independent of line contents).
    """
    lines = base_bytes.split(b"\n")
    if lines and lines[0] == b"---":
        for i in range(1, len(lines)):
            if lines[i] == b"---":
                insert_at = i + 1
                new_lines = lines[:insert_at] + [head_marker_line] + lines[insert_at:]
                return b"\n".join(new_lines)
    # No frontmatter delimiter found - prepend as the first line.
    return head_marker_line + b"\n" + base_bytes


def build_candidate(base_path: str, target_bytes: int, out_path: str,
                     sweep_id: str | None = None) -> dict:
    base_bytes = Path(base_path).read_bytes()
    if sweep_id is None:
        sweep_id = secrets.token_hex(SWEEP_ID_LEN // 2)
    if len(sweep_id) != SWEEP_ID_LEN:
        raise ValueError(
            f"sweep_id must be exactly {SWEEP_ID_LEN} hex chars, got "
            f"{len(sweep_id)!r}: {sweep_id!r}"
        )

    head_marker_line = _head_marker_line(sweep_id, target_bytes)
    with_head = _insert_head_marker(base_bytes, head_marker_line)
    head_added_bytes = len(with_head) - len(base_bytes)

    pad_line_len = len(_pad_line(sweep_id, 0))
    # Placeholder hash (64 hex chars, same length as any real sha256 hex
    # digest) so the tail block's byte length is knowable before the real
    # pad-line count/hash exist - measuring the real hash cannot change
    # this length, since hexdigest() is always 64 hex chars.
    placeholder_hash = "0" * 64
    tail_len = len(_tail_block(sweep_id, 0, target_bytes, placeholder_hash))

    available_for_pad = target_bytes - len(with_head) - tail_len
    if available_for_pad < 0:
        minimum = len(with_head) + tail_len
        raise ValueError(
            f"target_bytes={target_bytes} is smaller than the minimum "
            f"viable candidate size ({minimum} B = base+head "
            f"{len(with_head)} B + a zero-pad-line tail block {tail_len} "
            f"B). Pick a larger --target-bytes or a smaller --base."
        )

    num_pad_lines = available_for_pad // pad_line_len
    remainder = available_for_pad - (num_pad_lines * pad_line_len)

    pad_block = b"".join(_pad_line(sweep_id, i) for i in range(1, num_pad_lines + 1))
    hash_hex = hashlib.sha256(pad_block).hexdigest()
    tail_block = _tail_block(sweep_id, num_pad_lines, target_bytes, hash_hex)

    # Byte-exact filler to absorb any remainder below one full pad-line
    # width. Deliberately NOT numbered like the pad block above (a
    # truncation-detection reader should treat this as inert alignment
    # padding, not part of the counted/hashed pad run).
    if remainder == 0:
        filler = b""
    elif remainder == 1:
        filler = b"\n"
    else:
        filler = (b"x" * (remainder - 1)) + b"\n"

    candidate = with_head + pad_block + filler + tail_block

    if len(candidate) != target_bytes:
        raise RuntimeError(
            f"internal error: assembled candidate is {len(candidate)} B, "
            f"expected exactly {target_bytes} B (head_added={head_added_bytes}, "
            f"pad_lines={num_pad_lines} x {pad_line_len} B, "
            f"remainder_filler={len(filler)} B, tail={len(tail_block)} B) - "
            f"this is a defect in skill_embed_sweep.py's padding arithmetic, "
            f"not a caller error. Do not trust this candidate."
        )

    Path(out_path).write_bytes(candidate)

    return {
        "sweep_id": sweep_id,
        "num_pad_lines": num_pad_lines,
        "actual_bytes": len(candidate),
        "pad_block_sha256": hash_hex,
    }


def _cmd_check_out_refusal(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="skill_embed_sweep.py check-out-refusal",
        description="Exit 1 (with a reason on stderr) if --out refers to "
        "the same on-disk file as --real, or matches the "
        ".claude/skills/dinostack/SKILL.md artifact shape under ANY "
        "checkout. Exit 0 silently otherwise. Used by "
        "scripts/skill-embed-sweep-harness.sh's `candidate` write guard "
        "(DS-45 round-2).",
    )
    parser.add_argument("--out", required=True, help="the --out path a caller wants to write to")
    parser.add_argument("--real", required=True, help="this checkout's real, tracked SKILL.md path")
    args = parser.parse_args(argv)

    if paths_refer_to_same_file(args.out, args.real):
        print(
            "skill_embed_sweep.py check-out-refusal: --out resolves to "
            f"the same file as the real, tracked SKILL.md ({args.real}) - "
            "refusing.",
            file=sys.stderr,
        )
        return 1

    out_real = os.path.realpath(args.out)
    if _tail_matches_skill_artifact_shape(out_real):
        print(
            "skill_embed_sweep.py check-out-refusal: --out resolves to "
            f"{out_real!r}, which matches the "
            ".claude/skills/dinostack/SKILL.md artifact shape under a "
            "checkout other than this one - refusing.",
            file=sys.stderr,
        )
        return 1

    return 0


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:]) if argv is None else list(argv)
    if raw_argv and raw_argv[0] == "check-out-refusal":
        return _cmd_check_out_refusal(raw_argv[1:])

    parser = argparse.ArgumentParser(
        description="Build a byte-exact, canary-carrying candidate SKILL.md "
        "for the skill-embed injection sweep (DS-45)."
    )
    parser.add_argument("--base", required=True, help="path to the base SKILL.md (read-only)")
    parser.add_argument("--target-bytes", required=True, type=int, help="exact target byte size")
    parser.add_argument("--out", required=True, help="path to write the candidate to")
    parser.add_argument("--sweep-id", default=None, help="override the auto-generated sweep id")
    args = parser.parse_args(raw_argv)

    try:
        result = build_candidate(args.base, args.target_bytes, args.out, args.sweep_id)
    except (ValueError, RuntimeError) as exc:
        print(f"skill_embed_sweep.py: {exc}", file=sys.stderr)
        return 1

    print(f"sweep_id={result['sweep_id']}")
    print(f"num_pad_lines={result['num_pad_lines']}")
    print(f"actual_bytes={result['actual_bytes']}")
    print(f"pad_block_sha256={result['pad_block_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
