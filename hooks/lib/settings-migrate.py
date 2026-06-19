"""
Purpose: Single-sourced prune-then-add migration for ~/.claude/settings.json
         hook registrations. Used by both install.sh and uninstall.sh to ensure
         idempotent, complete management of all agentic-engineering hook entries
         across all 5 Claude Code events (UserPromptSubmit, Stop, SessionStart,
         SessionEnd, PreToolUse). Importable by tests AND runnable as a CLI.

Public API:
    is_agentic_owned(command: str) -> bool
    prune(settings: dict) -> dict
    derive_pretooluse_matchers(hooks_dir: str) -> list[str]
    add_dispatchers(settings: dict, repo_dir: str,
                   pretooluse_matchers: list[str]) -> dict
    migrate(settings_path: str, repo_dir: str, mode: str) -> None

    CLI: python3 hooks/lib/settings-migrate.py <install|uninstall> <repo_dir>
                 [<settings_path>]
         Default settings_path: ~/.claude/settings.json

Upstream deps: Python 3 stdlib only (json, os, re, sys, time, pathlib).

Downstream consumers:
    .claude/install.sh   (install mode)
    .claude/uninstall.sh (uninstall mode)
    hooks/tests/test-settings-migrate.js (U8 test suite, via subprocess CLI)

Failure modes: Raises on unreadable or malformed settings.json (caller must
               handle). The backup written on install is best-effort
               (fail-open: warns to stderr but does not abort). CLI exits 1 on
               usage error; exits 0 on success.

Performance: Sub-millisecond; pure in-process JSON transform with one file
             read, one file write, and one optional backup write.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Ownership predicate
# ---------------------------------------------------------------------------

# Any future hook basename MUST be added here in the same commit (prevents
# orphan-registration accumulation).
_LEGACY_BASENAMES = {
    "session-start-wrap.sh",
    "session-start-version-check.sh",
    "session-end-wrap.js",
    "stop-context.js",
    "skill-auto-load-check.sh",
    "enforce-background-spawn.py",
    "enforce-askuserquestion-default.py",
}

_PATH_SUBSTRING = "agentic-engineering/hooks/"
_RISK_ECHO_SIGNATURE = "BEFORE ANY ACTION: classify risk first"
_DISPATCHER_SUBSTRING = "dino-dispatch.py"


def is_agentic_owned(command: str) -> bool:
    """Return True iff the command string is an agentic-engineering hook entry.

    Matches on:
    - The path substring 'agentic-engineering/hooks/'
    - Any legacy hook basename from the known set
    - The risk-echo signature substring
    - The dispatcher path substring 'dino-dispatch.py'

    Does NOT match '*-mika.py' commands or plugin commands (they contain none
    of the above substrings).
    """
    if _PATH_SUBSTRING in command:
        return True
    if _RISK_ECHO_SIGNATURE in command:
        return True
    if _DISPATCHER_SUBSTRING in command:
        return True
    # Check legacy basenames - match as substring to handle full absolute paths
    for basename in _LEGACY_BASENAMES:
        if basename in command:
            return True
    return False


# ---------------------------------------------------------------------------
# Prune
# ---------------------------------------------------------------------------

def prune(settings: dict) -> dict:
    """Remove all agentic-owned entries from settings["hooks"].

    Walk every event in settings["hooks"]; within each event's list of
    matcher-blocks, remove any entry in a block's "hooks" array whose
    "command" is agentic-owned; drop any matcher-block left with an empty
    "hooks" array; drop any event key left with an empty list.

    Never inspects or removes non-agentic entries. Returns the mutated
    settings dict (same object, mutated in place for convenience).
    """
    hooks = settings.get("hooks", {})
    events_to_delete = []

    for event_name, blocks in hooks.items():
        if not isinstance(blocks, list):
            continue

        new_blocks = []
        for block in blocks:
            if not isinstance(block, dict):
                new_blocks.append(block)
                continue
            hook_entries = block.get("hooks", [])
            filtered = [
                e for e in hook_entries
                if not (isinstance(e, dict) and is_agentic_owned(e.get("command", "")))
            ]
            if filtered:
                block = dict(block)
                block["hooks"] = filtered
                new_blocks.append(block)
            # else: block's hooks are now empty - drop the block entirely

        if new_blocks:
            hooks[event_name] = new_blocks
        else:
            events_to_delete.append(event_name)

    for event_name in events_to_delete:
        del hooks[event_name]

    if hooks:
        settings["hooks"] = hooks
    elif "hooks" in settings:
        del settings["hooks"]

    return settings


# ---------------------------------------------------------------------------
# Derive PreToolUse matchers from leaf headers
# ---------------------------------------------------------------------------

_MATCHER_RE = re.compile(r"^#\s*dino-matcher:\s*(.+)$")


def derive_pretooluse_matchers(hooks_dir: str) -> list:
    """Scan hooks/pretooluse.d/* leaf files for '# dino-matcher: <pattern>'
    headers (checked in the first 20 lines of each file). Return the sorted
    list of distinct patterns found.

    Today's result: ["AskUserQuestion", "Task"]
    """
    pretooluse_dir = Path(hooks_dir) / "pretooluse.d"
    if not pretooluse_dir.is_dir():
        return []

    patterns: set = set()
    for leaf in sorted(pretooluse_dir.iterdir()):
        if not leaf.is_file():
            continue
        try:
            with open(leaf, "r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if i >= 20:
                        break
                    m = _MATCHER_RE.match(line.rstrip("\n"))
                    if m:
                        patterns.add(m.group(1).strip())
        except OSError:
            continue

    return sorted(patterns)


# ---------------------------------------------------------------------------
# Add dispatchers
# ---------------------------------------------------------------------------

def _dispatcher_cmd(repo_dir: str, event: str) -> str:
    return f"python3 {repo_dir}/hooks/dino-dispatch.py {event}"


def _ensure_dedicated_block(event_blocks: list, matcher: str, command: str, timeout: int) -> list:
    """Ensure exactly one dedicated agentic dispatcher block exists for
    (event, matcher). A block is 'dedicated' when ALL its hook entries are
    agentic-owned - we never merge into a user/plugin block.

    Algorithm:
    1. Collect all blocks matching this matcher.
    2. Among those, find any that are fully agentic-owned (all entries owned).
    3. If a fully-owned block already has the dispatcher entry -> no-op.
    4. If a fully-owned block exists but lacks the entry -> add to first one.
    5. If no fully-owned block -> append a fresh one.
    Returns the (possibly mutated) event_blocks list.
    """
    entry = {"type": "command", "command": command, "timeout": timeout}

    owned_blocks = [
        (i, b) for i, b in enumerate(event_blocks)
        if isinstance(b, dict)
        and b.get("matcher") == matcher
        and all(is_agentic_owned(e.get("command", "")) for e in b.get("hooks", []))
    ]

    if owned_blocks:
        idx, block = owned_blocks[0]
        existing_cmds = [e.get("command", "") for e in block.get("hooks", [])]
        if command not in existing_cmds:
            new_block = dict(block)
            new_block["hooks"] = list(block.get("hooks", [])) + [entry]
            event_blocks[idx] = new_block
    else:
        event_blocks.append({"matcher": matcher, "hooks": [entry]})

    return event_blocks


def add_dispatchers(settings: dict, repo_dir: str, pretooluse_matchers: list) -> dict:
    """Add dispatcher entries for all 5 events.

    Each dispatcher entry goes into its OWN dedicated agentic-owned matcher
    block - never merged into an existing user/plugin block. The function is
    idempotent: calling it twice on already-added settings is a no-op.

    Events registered:
      UserPromptSubmit  matcher "*"       -> dino-dispatch.py UserPromptSubmit
      Stop              matcher "*"       -> dino-dispatch.py Stop
      SessionStart      matcher "*"       -> dino-dispatch.py SessionStart
      SessionEnd        matcher "*"       -> dino-dispatch.py SessionEnd
      PreToolUse        one block per pretooluse_matcher -> dino-dispatch.py PreToolUse
    """
    hooks = settings.setdefault("hooks", {})

    # Star-matcher events
    for event in ("UserPromptSubmit", "Stop", "SessionStart", "SessionEnd"):
        blocks = hooks.setdefault(event, [])
        hooks[event] = _ensure_dedicated_block(
            blocks, "*", _dispatcher_cmd(repo_dir, event), 15
        )

    # PreToolUse: one block per derived matcher
    ptu_blocks = hooks.setdefault("PreToolUse", [])
    for matcher in pretooluse_matchers:
        ptu_blocks = _ensure_dedicated_block(
            ptu_blocks, matcher, _dispatcher_cmd(repo_dir, "PreToolUse"), 15
        )
    hooks["PreToolUse"] = ptu_blocks

    settings["hooks"] = hooks
    return settings


# ---------------------------------------------------------------------------
# Top-level migrate flow
# ---------------------------------------------------------------------------

def migrate(settings_path: str, repo_dir: str, mode: str) -> None:
    """Run the full install or uninstall migration against settings_path.

    install:
      1. Read settings.json (or {} if absent).
      2. Back up to {settings_path}.bak-{timestamp}.
      3. prune() all agentic-owned entries.
      4. add_dispatchers() with matchers derived from hooks/pretooluse.d/.
      5. Write back (indent=2, trailing newline).

    uninstall:
      1. Read settings.json (skip if absent).
      2. prune() all agentic-owned entries.
      3. Write back (indent=2, trailing newline).

    Both modes are idempotent.
    """
    if mode not in ("install", "uninstall"):
        raise ValueError(f"mode must be 'install' or 'uninstall', got '{mode}'")

    hooks_dir = os.path.join(repo_dir, "hooks")

    # Read
    if os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8") as fh:
            settings = json.load(fh)
    else:
        if mode == "uninstall":
            print(f"  settings.json not found at {settings_path} - nothing to update.")
            return
        settings = {}

    if mode == "install":
        # Back up before mutating
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        backup_path = f"{settings_path}.bak-{timestamp}"
        try:
            with open(backup_path, "w", encoding="utf-8") as fh:
                json.dump(settings, fh, indent=2)
                fh.write("\n")
            print(f"  + backup written to {backup_path}")
        except OSError as exc:
            print(f"  ! backup failed ({exc}) - continuing", file=sys.stderr)

    # Prune
    settings = prune(settings)

    if mode == "install":
        # Add dispatchers
        matchers = derive_pretooluse_matchers(hooks_dir)
        settings = add_dispatchers(settings, repo_dir, matchers)
        print(f"  + dispatcher entries registered for events: "
              f"UserPromptSubmit, Stop, SessionStart, SessionEnd, "
              f"PreToolUse({', '.join(matchers)})")

    # Write back
    with open(settings_path, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
        fh.write("\n")
    print("  settings.json written.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _main() -> None:
    if len(sys.argv) < 3:
        print(
            "Usage: python3 hooks/lib/settings-migrate.py "
            "<install|uninstall> <repo_dir> [<settings_path>]",
            file=sys.stderr,
        )
        sys.exit(1)

    mode = sys.argv[1]
    repo_dir = sys.argv[2]
    settings_path = (
        sys.argv[3] if len(sys.argv) >= 4
        else os.path.expanduser("~/.claude/settings.json")
    )

    migrate(settings_path, repo_dir, mode)


if __name__ == "__main__":
    _main()
