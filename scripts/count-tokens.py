#!/usr/bin/env python3
"""
Purpose: Report byte and token counts for a set of files, used to measure the
         built methodology resident-set size before/after compression work
         (DS-68). Token counting calls the Anthropic count_tokens API when
         credentials are available; otherwise falls back to a bytes/4
         heuristic so the script never hard-fails in an unauthenticated
         environment.

Public API: CLI - `python3 scripts/count-tokens.py --files <path> [<path> ...]`
            Prints a per-file table (bytes, tokens, method) plus a totals row
            to stdout. Exits 0 on success, 1 if any listed file is missing.
            Importable helpers: count_bytes(path), count_tokens_for_text(text)
            -> (count: int, method: str).

Upstream deps: Python 3 stdlib only (argparse, pathlib, sys, os, urllib for the
               REST fallback). Optional: the `anthropic` pip package, if
               importable, is preferred over raw REST. Reads ANTHROPIC_API_KEY
               from the environment when a live token count is requested.

Downstream consumers: DS-68 baseline capture (scripts/count-tokens.py invoked
                      directly from the ticket workflow); no other script
                      imports this module as of authoring.

Failure modes: Never raises on missing API auth - falls back to the bytes/4
               estimate and prefixes the method column with
               "[ESTIMATE: no API auth, using bytes/4 heuristic]". Missing
               input files are reported per-file and cause a non-zero exit
               after all files are processed (best-effort - does not abort
               early). Network errors talking to the Anthropic API are caught
               per-file and also fall back to the byte/4 estimate for that
               file only.

Performance: One API call per file when live token counting is available
             (network-bound, typically <1s per call); the bytes/4 fallback is
             O(file size), effectively instant.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Tuple

ESTIMATE_PREFIX = "[ESTIMATE: no API auth, using bytes/4 heuristic]"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages/count_tokens"
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"


def count_bytes(path: Path) -> int:
    """Return the size of *path* in bytes."""
    return path.stat().st_size


def _count_tokens_via_sdk(text: str, api_key: str) -> int:
    """Count tokens using the `anthropic` pip package. Raises on any failure."""
    import anthropic  # type: ignore[import-not-found]

    client = anthropic.Anthropic(api_key=api_key)
    result = client.messages.count_tokens(
        model=DEFAULT_MODEL,
        messages=[{"role": "user", "content": text}],
    )
    return int(result.input_tokens)


def _count_tokens_via_rest(text: str, api_key: str) -> int:
    """Count tokens using a direct REST call. Raises on any failure."""
    payload = json.dumps(
        {
            "model": DEFAULT_MODEL,
            "messages": [{"role": "user", "content": text}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=payload,
        method="POST",
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return int(body["input_tokens"])


def count_tokens_for_text(text: str) -> Tuple[int, str]:
    """Return (token_count, method) for *text*.

    method is one of: "anthropic-sdk", "anthropic-rest", or the ESTIMATE_PREFIX
    string when no API auth is available or the live call failed.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    byte_estimate = len(text.encode("utf-8")) // 4

    if not api_key:
        return byte_estimate, ESTIMATE_PREFIX

    try:
        return _count_tokens_via_sdk(text, api_key), "anthropic-sdk"
    except ImportError:
        pass
    except Exception:
        return byte_estimate, ESTIMATE_PREFIX

    try:
        return _count_tokens_via_rest(text, api_key), "anthropic-rest"
    except Exception:
        return byte_estimate, ESTIMATE_PREFIX


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(
        description="Report byte and token counts for a set of files."
    )
    parser.add_argument(
        "--files",
        nargs="+",
        required=True,
        metavar="PATH",
        help="One or more file paths to measure.",
    )
    args = parser.parse_args(argv)

    rows = []
    missing = []
    total_bytes = 0
    total_tokens = 0

    for raw_path in args.files:
        path = Path(raw_path)
        if not path.is_file():
            missing.append(raw_path)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        nbytes = count_bytes(path)
        ntokens, method = count_tokens_for_text(text)
        total_bytes += nbytes
        total_tokens += ntokens
        rows.append((raw_path, nbytes, ntokens, method))

    name_width = max([len("FILE")] + [len(r[0]) for r in rows], default=len("FILE"))
    header = f"{'FILE':<{name_width}}  {'BYTES':>10}  {'TOKENS':>10}  METHOD"
    print(header)
    print("-" * len(header))
    for raw_path, nbytes, ntokens, method in rows:
        print(f"{raw_path:<{name_width}}  {nbytes:>10}  {ntokens:>10}  {method}")
    print("-" * len(header))
    print(f"{'TOTAL':<{name_width}}  {total_bytes:>10}  {total_tokens:>10}")

    if missing:
        print("\nMissing files (skipped):", file=sys.stderr)
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
