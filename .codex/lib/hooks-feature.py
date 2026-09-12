#!/usr/bin/env python3
"""Purpose: Manage the Codex hooks flag without rewriting user TOML.
Public API: python3 hooks-feature.py <config.toml> [--remove-owned]; prints
            enabled, disabled, added, removed, absent, or unsupported. Removal
            requires the caller to verify its ownership marker first.
Upstream deps: Python standard library; existing installer destination guards.
Downstream consumers: .codex/install.sh and .codex/uninstall.sh.
Failure modes: ambiguous/unsupported features definitions remain byte-identical;
               I/O errors exit nonzero, preserving the original until atomic replacement.
               Symlinks and detected concurrent changes are refused; temporary files are cleaned.
               Repeated successful calls are idempotent.
Performance: linear lexical scan of the configuration file.
"""

import json
import os
import re
import sys
import stat
import tempfile
from pathlib import Path


def statements(text):
    """Yield tokens and complete line boundaries outside strings and containers."""
    tokens = []
    depth = 0
    index = 0
    statement_start = 0
    while index < len(text):
        char = text[index]
        if not tokens and char not in " \t\r\n#":
            statement_start = text.rfind("\n", 0, index) + 1
        if char == "#":
            end = text.find("\n", index)
            index = len(text) if end == -1 else end
        elif char in " \t\r":
            index += 1
        elif char == "\n":
            index += 1
            if depth == 0 and tokens:
                yield tokens, statement_start, index
                tokens = []
        elif char in "\"'":
            start = index
            multiline = text.startswith(char * 3, index)
            index += 3 if multiline else 1
            while index < len(text):
                if char == '"' and text[index] == "\\":
                    index += 2
                elif text[index] == char:
                    end = index
                    while end < len(text) and text[end] == char:
                        end += 1
                    if not multiline:
                        index += 1
                        break
                    if end - index >= 3:
                        index = end
                        break
                    index = end
                else:
                    index += 1
            else:
                raise ValueError("unterminated string")
            tokens.append(text[start:index])
        elif char in "[]{}=.,":
            if char in "[{":
                depth += 1
            elif char in "]}":
                depth -= 1
                if depth < 0:
                    raise ValueError("unbalanced container")
            tokens.append(char)
            index += 1
        else:
            start = index
            while index < len(text) and text[index] not in " \t\r\n#\"'[]{}=.,":
                index += 1
            tokens.append(text[start:index])
    if depth:
        raise ValueError("unclosed container")
    if tokens:
        yield tokens, statement_start, len(text)


def key_parts(tokens):
    parts = []
    for index, token in enumerate(tokens):
        if index % 2:
            if token != ".":
                raise ValueError("unsupported key")
        elif token.startswith('"'):
            parts.append(json.loads(token))
        elif token.startswith("'"):
            parts.append(token[1:-1])
        elif re.fullmatch(r"[A-Za-z0-9_-]+", token):
            parts.append(token)
        else:
            raise ValueError("unsupported key")
    if not parts or len(tokens) % 2 == 0:
        raise ValueError("unsupported key")
    return parts


def update_feature(text, remove_owned=False):
    scope = []
    header_end = None
    defined = False
    flag = None
    flag_span = None
    unsupported = False
    for tokens, start, end in statements(text):
        if tokens[0] == "[":
            array = len(tokens) > 1 and tokens[1] == "["
            width = 2 if array else 1
            scope = key_parts(tokens[width:-width])
            if scope[0] == "features":
                defined = True
                if scope[:2] == ["features", "codex_hooks"]:
                    unsupported = True
                if scope == ["features"] and not array:
                    if header_end is not None:
                        unsupported = True
                    header_end = end
                elif array and scope == ["features"]:
                    unsupported = True
        else:
            equals = tokens.index("=")
            key = key_parts(tokens[:equals])
            if not scope and key[0] == "features":
                defined = True
                unsupported = True
            if scope == ["features"] and key[0] == "codex_hooks":
                if len(key) != 1 or flag is not None:
                    unsupported = True
                flag = "enabled" if tokens[equals + 1:] == ["true"] else "disabled"
                flag_span = start, end
    if unsupported or (defined and header_end is None):
        return "unsupported", text
    if remove_owned:
        if flag_span is None:
            return "absent", text
        start, end = flag_span
        return "removed", text[:start] + text[end:]
    if flag is not None:
        return flag, text
    newline = "\r\n" if "\r\n" in text else "\n"
    if header_end is not None:
        prefix = "" if text[:header_end].endswith("\n") else newline
        added = prefix + "codex_hooks = true" + newline
        return "added", text[:header_end] + added + text[header_end:]
    prefix = "" if not text or text.endswith("\n") else newline
    return "added", text + prefix + "[features]" + newline + "codex_hooks = true" + newline


def file_identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def replace_config(path, updated, original_info):
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(updated)
            output.flush()
            os.fchmod(output.fileno(), stat.S_IMODE(original_info.st_mode))
            os.fsync(output.fileno())
        if file_identity(path.lstat()) != file_identity(original_info):
            raise OSError("configuration changed while enabling hooks; retry installation")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main():
    path = Path(sys.argv[1])
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
        original_info = os.fstat(source.fileno())
        if not stat.S_ISREG(original_info.st_mode):
            raise OSError("configuration must be a regular file")
        original = source.read()
    try:
        status, updated = update_feature(original.decode("utf-8"), "--remove-owned" in sys.argv[2:])
    except (ValueError, IndexError):
        status = "unsupported"
    if status in {"added", "removed"}:
        replace_config(path, updated.encode("utf-8"), original_info)
    print(status)


if __name__ == "__main__":
    main()
