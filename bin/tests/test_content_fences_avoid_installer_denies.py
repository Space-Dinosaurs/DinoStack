"""
Purpose: Fails when an executable fence anywhere under content/**/*.md runs a
         command that .claude/install.sh's own recommended_deny list denies
         (for example `rm -rf`), so shipped methodology never instructs an
         agent to run a command the shipped installer blocks.

Public API: pytest test functions only; no importable helpers are consumed
         elsewhere.

Upstream dependencies: .claude/install.sh (the `recommended_deny = [...]`
         block, read as text; only its "Bash(<prefix>*)" entries are used);
         content/**/*.md.

Downstream consumers: .github/workflows/bin-tests.yml python-bin-tests job,
         which runs `pytest bin/tests/ -q` with directory-glob discovery.

Failure modes: pure static analysis of tracked text files. Matching is
         prefix-based at command-start positions (line start, after
         ; & | { ( or then/do/else) inside bare, bash, sh, shell and zsh
         fences; comment text is ignored. A denied command reached any other
         way (a subcommand such as `git -C x rm -rf .`, a variable, eval) is
         not detected. If no Bash deny prefix parses, the prefix test fails
         loudly rather than letting the scan pass vacuously. That failure is
         this test's retirement condition: when .claude/install.sh ships no
         Bash deny prefixes, delete this test rather than repair the parse.

Performance: negligible - one regex pass over content/**/*.md.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INSTALL_SH = REPO_ROOT / ".claude" / "install.sh"
CONTENT_DIR = REPO_ROOT / "content"

_DENY_BLOCK_RE = re.compile(r"recommended_deny\s*=\s*\[(.*?)\]", re.S)
_BASH_ENTRY_RE = re.compile(r'"Bash\(([^)]*)\)"')
_FENCE_RE = re.compile(r"^(?:> )?[ \t]*```([A-Za-z0-9_+-]*)[ \t]*$")
_EXEC_LANGS = {"", "bash", "sh", "shell", "zsh"}
_COMMAND_START = r"(?:^|[;&|{(]|\bthen\b|\bdo\b|\belse\b)\s*"
_TRAILING_COMMENT_RE = re.compile(r"(?:^|\s)#.*$")


def _deny_prefixes() -> list[str]:
    match = _DENY_BLOCK_RE.search(INSTALL_SH.read_text())
    if not match:
        return []
    return [p.rstrip("*").strip() for p in _BASH_ENTRY_RE.findall(match.group(1))]


def _scan(text: str, prefixes: list[str]) -> list[tuple[int, str, str]]:
    patterns = [(p, re.compile(_COMMAND_START + re.escape(p))) for p in prefixes]
    hits = []
    inside = False
    lang = None
    for lineno, line in enumerate(text.split("\n"), 1):
        fence = _FENCE_RE.match(line)
        if fence:
            if not inside:
                inside, lang = True, fence.group(1)
            else:
                inside = False
            continue
        if not inside or lang not in _EXEC_LANGS:
            continue
        code = _TRAILING_COMMENT_RE.sub("", line)
        for prefix, pattern in patterns:
            if pattern.search(code):
                hits.append((lineno, prefix, line.strip()))
    return hits


def test_install_sh_ships_bash_deny_prefixes():
    assert _deny_prefixes(), (
        f"no \"Bash(<prefix>*)\" entries parsed from recommended_deny in {INSTALL_SH}"
    )


@pytest.mark.parametrize("lang", ["", "bash", "sh", "shell", "zsh"])
def test_scanner_detects_a_denied_command(lang):
    sample = f"```{lang}\nmkdir -p x\n[ -d x ] && rm -rf x\n```\n"
    assert _scan(sample, ["rm -rf"]) == [(3, "rm -rf", "[ -d x ] && rm -rf x")]


def test_content_fences_avoid_installer_denies():
    prefixes = _deny_prefixes()
    violations = []
    for path in sorted(CONTENT_DIR.rglob("*.md")):
        for lineno, prefix, line in _scan(path.read_text(), prefixes):
            violations.append(
                f"{path.relative_to(REPO_ROOT)}:{lineno}: `{prefix}` in: {line}"
            )
    assert not violations, (
        ".claude/install.sh denies these commands, so an agent following the "
        "fence is refused:\n" + "\n".join(violations)
    )
