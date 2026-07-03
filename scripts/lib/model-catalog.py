#!/usr/bin/env python3
"""
Purpose: Read scripts/lib/model-catalog.json (the curated install-TUI
         suggestion pool) and emit provider/model rows for the install
         wizard, and parse an OpenAI-compatible /v1/models response (read
         from stdin) into the same row shape for the custom-provider flow.
         This is the single reader/parser so bash never parses JSON. Pure
         offline code: it reads one local JSON file and/or stdin and prints
         rows. Network I/O (curl) lives in install-tui.sh, not here.

Public API:
  model-catalog.py providers
      -> "key<TAB>label" per provider (for a provider picker).
  model-catalog.py pairs [--provider P ...]
      -> "id<TAB>label" per model. With no --provider, every provider's
         models in catalog order. Repeat --provider to restrict.
  model-catalog.py ids [--provider P ...]
      -> one model id per line (ranking input for bin/agentic-models).
  model-catalog.py parse-models [--name NAME]
      -> read an OpenAI-compatible /v1/models JSON body from STDIN and emit
         "id<TAB>label" rows, one per model. Tolerates both the canonical
         {"data": [{"id": ...}]} shape and a bare top-level list. The label
         is prefixed with "<name>: " so the picker shows provenance. Exit 2
         on unparseable/empty input (bash then falls back to curated-only).

Exit code: 0 on success; 2 on bad arguments, an unreadable/malformed
           catalog, or (parse-models) unparseable/empty stdin. Never writes
           to disk, never makes network calls.

Upstream deps: Python 3 stdlib (argparse, json, os, sys).
Downstream consumers: scripts/install-tui.sh (curated picker + custom
                      provider merge via curl | parse-models).
Failure modes: missing/malformed model-catalog.json -> stderr + exit 2;
               parse-models with non-JSON/empty stdin -> stderr + exit 2.
Performance: one JSON parse; <10 ms.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

# Invisible/direction-control code points rejected in model ids: zero-width
# (ZWSP/ZWNJ/ZWJ/word-joiner), bidi controls (LRM/RLM/LRE/RLE/PDF/LRO/RLO,
# isolates LRI/RLI/FSI/PDI), and BOM/ZWNBSP. Selected ids persist to disk
# (CUSTOM_IDS / team config), so a spoofed-direction or invisibly-padded id
# would survive into config files and later shell pipelines.
_INVISIBLE_CODEPOINTS = frozenset({
    0x200B, 0x200C, 0x200D, 0x200E, 0x200F,
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
    0x2060, 0x2066, 0x2067, 0x2068, 0x2069,
    0xFEFF,
})


def _load() -> dict[str, Any]:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "model-catalog.json")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _parse_models_stdin(name: str) -> int:
    # Read + decode inside the try: non-UTF-8 bytes on stdin (UnicodeDecodeError)
    # and pathological nesting (RecursionError) must honor the exit-2 contract
    # (bash falls back to curated-only), never a traceback.
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError, RecursionError) as exc:
        print(f"model-catalog: parse-models: invalid JSON: {exc}", file=sys.stderr)
        return 2
    if isinstance(payload, dict):
        data = payload.get("data")
    else:
        data = payload
    if not isinstance(data, list):
        print("model-catalog: parse-models: expected {data:[...]} or a list",
              file=sys.stderr)
        return 2
    count = 0
    for entry in data:
        if isinstance(entry, dict):
            # OpenAI spec: the routable model identifier is the `id` field.
            # We deliberately do NOT fall back to `name`/`model` (those are
            # display metadata) - a missing id would otherwise write a
            # non-routable label into team config. Skip id-less entries.
            mid = entry.get("id")
        elif isinstance(entry, str):
            mid = entry
        else:
            mid = None
        if not isinstance(mid, str) or not mid.strip():
            continue
        mid = mid.strip()
        # Reject C0 control chars (tab/newline/etc) that would break the
        # id<TAB>label row contract downstream (bash reads this line-by-line),
        # plus DEL (0x7F) and C1 controls (0x80-0x9F) which are equally
        # non-printable and terminal-escape-adjacent, plus bidi/zero-width/BOM
        # code points (ids persist into CUSTOM_IDS/team config on disk; see
        # _INVISIBLE_CODEPOINTS). Ordinary non-ASCII letters (e.g. é, CJK)
        # remain allowed.
        if any(ord(c) < 32 or 0x7F <= ord(c) <= 0x9F
               or ord(c) in _INVISIBLE_CODEPOINTS for c in mid):
            continue
        print(f"{mid}\t{name}: {mid}")
        count += 1
    if count == 0:
        print("model-catalog: parse-models: no models in response", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="model-catalog.py",
        description="Emit rows from the curated install-TUI model suggestion pool.",
    )
    ap.add_argument("cmd", choices=["providers", "pairs", "ids", "parse-models"],
                    help="providers | pairs | ids | parse-models")
    ap.add_argument("--provider", action="append", default=[],
                    help="restrict pairs/ids to this provider key (repeatable)")
    ap.add_argument("--name", default="custom",
                    help="parse-models: provider display name for the label prefix")
    args = ap.parse_args(argv)

    if args.cmd == "parse-models":
        return _parse_models_stdin(args.name)

    try:
        catalog = _load()
    except (OSError, json.JSONDecodeError) as exc:
        print(f"model-catalog: cannot read catalog: {exc}", file=sys.stderr)
        return 2

    providers: dict[str, Any] = catalog.get("providers", {}) or {}
    if not isinstance(providers, dict):
        print("model-catalog: 'providers' must be an object", file=sys.stderr)
        return 2

    if args.cmd == "providers":
        for key, info in providers.items():
            label = info.get("label", key) if isinstance(info, dict) else key
            print(f"{key}\t{label}")
        return 0

    selected = args.provider or list(providers.keys())
    for key in selected:
        info = providers.get(key)
        if not isinstance(info, dict):
            continue
        for model in info.get("models", []) or []:
            if not isinstance(model, dict):
                continue
            mid = model.get("id", "")
            label = model.get("label", mid)
            if not mid:
                continue
            if args.cmd == "pairs":
                print(f"{mid}\t{label}")
            else:  # ids
                print(mid)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
