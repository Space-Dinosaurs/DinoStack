#!/usr/bin/env python3
"""
Purpose: Deterministically generate and validate DinoStack's four native Codex skills.

Public API: ``build --repo ROOT [--output DIR]``, ``check --repo ROOT``, and
            ``inventory --repo ROOT`` for explicitly refreshing the reviewed
            compatibility occurrence inventory.

Upstream deps: canonical content/SKILL.md, content/sections, three canonical
               command bodies, .codex/skill-frontmatter, and the reviewed
               .codex/skill-compatibility.yml inventory. Standard library only.

Downstream consumers: .codex/build.sh, scripts/check-codex-skill-sync.sh, CI,
                      and scripts/test/test_codex_skills.py.

Failure modes: refuses symlinked/special generated roots, unmatched source
               occurrences, invalid frontmatter, escaping resources, or drift.
               Check is read-only. Build only replaces the owned generated tree.

Performance: linear in canonical source and generated-tree size.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MAGIC = "DINOSTACK_CODEX_SKILL"
SCHEMA = 1
SKILLS = ("agentic-engineering", "brief", "wrap", "implement-ticket")
WORKFLOWS = {
    "brief": "content/commands/brief.md",
    "wrap": "content/commands/wrap.md",
    "implement-ticket": "content/commands/implement-ticket.md",
}
COMMAND_NAMES: tuple[str, ...] = ()
TOOL_MAP = {
    "Agent": "spawn_agent",
    "Task": "spawn_agent",
    "Read": "filesystem read",
    "Glob": "rg --files",
    "Grep": "rg",
    "Bash": "shell",
    "Edit": "apply_patch",
    "Write": "apply_patch",
    "AskUserQuestion": "one bounded direct question after default derivation",
}
CODEX_SPAWN_CONTRACT = """**Codex spawn contract.** Delegate with `spawn_agent` only. Before any spawn that needs an
isolated checkout, run the following from the invoked project root (`$AE_PROJECT_DIR`):

1. `git fetch origin`.
2. Choose a unique branch and absolute worktree path beneath `$AE_PROJECT_DIR/.agentic/worktrees/`.
3. Run `git worktree add "$AE_PROJECT_DIR/.agentic/worktrees/<branch>" -b "<branch>" origin/main`.
4. Load the named role instructions with
   `$AE_REPO_DIR/bin/agentic-codex-dispatch agent <role>`.
5. Call `spawn_agent` with supported inputs (`task_name`, `message`, and `fork_turns`). Begin the
   message with `Work only in the pre-created worktree <absolute-path>` and include the loaded role
   instructions plus the execution contract. The spawned agent must use shell commands in that
   worktree and must not edit the conductor checkout.

Codex spawns are asynchronous. The conductor remains responsive, uses the collaboration status and
wait operations to collect completion, and applies the existing review gates to the returned diff.
Claude hook payload fields and Claude Task behavior do not apply on Codex.
"""
SIMPLIFY_CONTRACT = (
    "the executable cleanup pass in `$AE_CORE_SKILL_ROOT/references/skeptic-protocol.md Section 12` "
    "(load that section, dispatch the named cleanup role with "
    "`$AE_REPO_DIR/bin/agentic-codex-dispatch agent <role>`, call `spawn_agent`, then run the "
    "required narrow Skeptic review)"
)
CODEX_BACKGROUND_COMMAND_CONTRACT = (
    "start the helper with Codex `exec_command`; if it yields a session ID, keep the conductor "
    "responsive and poll it with `write_stdin` until completion"
)
PATH_BINARIES = {
    "awk", "bash", "break", "case", "cat", "cd", "command", "cp", "curl",
    "done", "echo", "elif", "else", "env", "except", "export", "fi", "find",
    "continue", "cut", "do", "false", "for", "gh", "git", "grep", "if",
    "import", "jq", "local", "mkdir", "mv", "node", "npm", "nvm", "perl",
    "pip", "pip3", "print", "printf", "python", "python3", "read", "return",
    "rm", "rmdir", "sed", "sh", "shellcheck", "sleep", "sort", "stat", "tail",
    "then", "touch", "tr", "trap", "true", "try", "until", "wc", "while", ".",
}


class SkillError(RuntimeError):
    """A deterministic build or validation failure."""


@dataclass(frozen=True)
class Document:
    source: str
    text: str


@dataclass(frozen=True)
class Occurrence:
    source: str
    start: int
    end: int
    occurrence_class: str
    source_token: str
    generated_token: str
    kind: str
    resolution_mode: str
    expected_target: str
    scope: str
    occurrence_hash: str

    def record(self) -> dict[str, str]:
        return {
            "expected_target": self.expected_target,
            "generated_token": self.generated_token,
            "kind": self.kind,
            "occurrence_hash": self.occurrence_hash,
            "resolution_mode": self.resolution_mode,
            "scope": self.scope,
            "source": self.source,
            "source_token": self.source_token,
        }


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def inventory_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SkillError(f"cannot read {path}: {exc}") from exc


def command_names(repo: Path) -> tuple[str, ...]:
    return tuple(sorted(path.stem for path in (repo / "content/commands").glob("*.md")))


def assembled_methodology(repo: Path) -> str:
    result = subprocess.run(
        ["bash", str(repo / "scripts/build-methodology.sh")],
        cwd=repo,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode:
        raise SkillError(f"methodology assembly failed: {result.stderr.strip()}")
    return result.stdout


def documents(repo: Path) -> list[Document]:
    docs = [
        Document("content/SKILL.md", read_text(repo / "content/SKILL.md")),
        Document("assembled:METHODOLOGY.md", assembled_methodology(repo)),
    ]
    docs.extend(Document(path, read_text(repo / path)) for path in WORKFLOWS.values())
    return docs


def line_fingerprint(text: str, start: int, token: str, occurrence_class: str, source: str) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end]
    ordinal = text[line_start:start].count(token)
    payload = "\0".join((source, occurrence_class, token, line, str(ordinal))).encode()
    return sha256(payload)


def add_occurrence(
    found: list[Occurrence], occupied: list[tuple[int, int]], doc: Document,
    start: int, end: int, occurrence_class: str, token: str, generated: str,
    kind: str, mode: str, target: str,
    scope: str = "canonical-source",
) -> None:
    if any(start < right and end > left for left, right in occupied):
        return
    occupied.append((start, end))
    found.append(Occurrence(
        doc.source, start, end, occurrence_class, token, generated, kind, mode, target, scope,
        line_fingerprint(doc.text, start, token, occurrence_class, doc.source),
    ))


def add_project_path_inventory(
    found: list[Occurrence], doc: Document, span_start: int, span_text: str,
) -> None:
    """Record project-path scope inside a larger paragraph-level transformation."""
    pattern = re.compile(r"(?<![~\w/])(\.(?:agentic|claude)(?:/[A-Za-z0-9_.*<>\[\]-]+)*/?|\.gitignore)")
    for match in pattern.finditer(span_text):
        token = match.group(1).rstrip(".,;:")
        if token.startswith(".claude") and not doc.source.startswith("content/commands/"):
            continue
        start = span_start + match.start(1)
        found.append(Occurrence(
            doc.source, start, start + len(token), "inventory-only-project-path", token,
            f"$AE_PROJECT_DIR/{token}", "operational", "invoked-project-path", token,
            "invoked-project", line_fingerprint(doc.text, start, token,
                                                  "inventory-only-project-path", doc.source),
        ))


def codexify_project_paths(text: str, include_claude: bool) -> str:
    names = "agentic|claude" if include_claude else "agentic"
    pattern = re.compile(
        rf"(?:<cwd>/|\[cwd\]/)?(\.(?:{names})(?:/[A-Za-z0-9_.*<>\[\]-]+)*/?)"
    )
    rendered = pattern.sub(lambda match: f"$AE_PROJECT_DIR/{match.group(1)}", text)
    return re.sub(r"(?<![/\w])\.gitignore\b", "$AE_PROJECT_DIR/.gitignore", rendered)


def shell_occurrences(doc: Document, found: list[Occurrence], occupied: list[tuple[int, int]], repo: Path) -> None:
    for fence in re.finditer(r"```(?:bash|sh|shell)\s*\n(.*?)```", doc.text, re.I | re.S):
        body = fence.group(1)
        body_start = fence.start(1)
        heredoc: str | None = None
        cursor = 0
        for raw_line in body.splitlines(keepends=True):
            line = raw_line.rstrip("\r\n")
            stripped = line.strip()
            if heredoc is not None:
                if stripped == heredoc:
                    heredoc = None
                cursor += len(raw_line)
                continue
            delimiter = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
            segments = re.finditer(r"(?:^|&&|\|\||[;|])([^;&|]*)", line)
            for segment_match in segments:
                segment = segment_match.group(1)
                match = re.match(
                    r"\s*(?:(?:if|then|elif|while|until|!|do)\s+)?"
                    r"(?:(?:[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\"|\S+))\s+)*"
                    r"([A-Za-z0-9_./$-]+)",
                    segment,
                )
                if match:
                    token = match.group(1)
                    local = segment_match.start(1) + match.start(1)
                    start = body_start + cursor + local
                    if token == "claude":
                        generated = "$AE_REPO_DIR/bin/agentic-codex-dispatch legacy-cli claude"
                        mode, target, kind = "shimmed", "bin/agentic-codex-dispatch", "operational"
                    elif token.startswith("agentic-"):
                        generated = token
                        mode, target, kind = "repository-owned", f"bin/{token}", "operational"
                    elif token in PATH_BINARIES:
                        generated = token
                        mode, target, kind = "PATH-provided", token, "operational"
                    elif token.startswith(("bin/", "hooks/", "scripts/", ".codex/")):
                        generated = f"$AE_REPO_DIR/{token}"
                        mode, target, kind = "repository-owned", token, "operational"
                    else:
                        generated = token
                        mode, target, kind = "display-only", "hashed-source-occurrence", "display-only"
                    add_occurrence(found, occupied, doc, start, start + len(token), "fenced-shell-binary",
                                   token, generated, kind, mode, target)
            if delimiter:
                heredoc = delimiter.group(1)
            cursor += len(raw_line)


def inventory_document(doc: Document, repo: Path) -> list[Occurrence]:
    found: list[Occurrence] = []
    occupied: list[tuple[int, int]] = []

    for match in re.finditer(r"\*\*All delegated tasks run in the background by default\.\*\*.*?(?=\n\n)", doc.text, re.S):
        add_occurrence(
            found, occupied, doc, match.start(), match.end(), "spawn-semantics",
            match.group(0), CODEX_SPAWN_CONTRACT.rstrip(), "operational",
            "codex-spawn-contract", "spawn_agent", "codex-harness",
        )

    worktree_paragraphs = (
        r"\*\*Worktree isolation is MANDATORY\.\*\*.*?(?=\n\n)",
        r"There is no in-place exception\..*?(?=\n\n)",
        r"\*\*Isolation is mandatory for every shippable-edit spawn\.\*\*.*?(?=\n\n)",
        r"\*\*Isolation worktrees \(`worktree-agent-\*`\)\*\*.*?(?=\n\n)",
        r"\*\*Worktree isolation is mandatory on the Elevated path\.\*\*.*?(?=\n\n)",
        r"\*\*Trivial-path solo engineer carve-out\.\*\*.*?(?=\n\n)",
        r"\*\*Step 1\.\*\* Spawn `qa-engineer`.*?(?=\n\n)",
        r"2\. Spawn one `engineer` fix pass scoped to the quality gate failure output.*?(?=\n\n)",
        r"5\. Spawn one `engineer` fix pass with the Debugger's Fix brief appended.*?(?=\n\n)",
    )
    for pattern in worktree_paragraphs:
        for match in re.finditer(pattern, doc.text, re.S):
            generated = match.group(0)
            generated = re.sub(
                r"Every concurrent (`engineer`, `qa-engineer`, and `release-orchestrator`) spawn MUST set "
                r"`isolation: \"worktree\"` on the Agent tool call",
                r"Before every concurrent \1 spawn, execute the Codex spawn contract above",
                generated,
            )
            generated = re.sub(
                r"Every (`engineer`, `qa-engineer`, and `release-orchestrator`) spawn MUST set "
                r"`isolation: \"worktree\"` on the Agent tool call",
                r"Before every \1 spawn, execute the Codex spawn contract above",
                generated,
            )
            generated = generated.replace(
                "The Agent tool call spawning the engineer MUST set `isolation: \"worktree\"`",
                "Before spawning the engineer, execute the Codex spawn contract above",
            )
            generated = generated.replace(
                "The Agent tool call MUST set `isolation: \"worktree\"`",
                "Before calling `spawn_agent`, execute the Codex spawn contract above",
            )
            generated = generated.replace(
                "The Trivial-path solo `engineer` spawn is also `isolation: \"worktree\"`",
                "The Trivial-path solo `engineer` spawn must also execute the Codex spawn contract above",
            )
            generated = generated.replace(
                "the Trivial-path solo `engineer` spawn is also `isolation: \"worktree\"`",
                "the Trivial-path solo `engineer` spawn must also execute the Codex spawn contract above",
            )
            generated = generated.replace(
                "inside its own worktree (`isolation: \"worktree\"`)",
                "inside the pre-created worktree required by the Codex spawn contract above",
            )
            generated = generated.replace(
                "are created by the Agent tool when `isolation: \"worktree\"` is set",
                "are created explicitly by the conductor with `git worktree add` before `spawn_agent`, "
                "as required by the Codex spawn contract above",
            )
            generated = codexify_project_paths(
                generated, include_claude=doc.source.startswith("content/commands/")
            )
            if generated == match.group(0) or "isolation:" in generated:
                raise SkillError(f"incomplete Codex worktree paragraph mapping in {doc.source}")
            add_project_path_inventory(found, doc, match.start(), match.group(0))
            add_occurrence(
                found, occupied, doc, match.start(), match.end(), "spawn-semantics",
                match.group(0), generated, "operational", "codex-spawn-contract",
                "git worktree add + spawn_agent", "codex-harness",
            )

    for match in re.finditer(
        r"\*\*Routing enforcement differs by harness\.\*\*.*?(?=\n\n)", doc.text, re.S
    ):
        generated = (
            "**Routing enforcement differs by harness.** Claude Code's `PreToolUse` hooks enforce "
            "its legacy Agent and Task behavior, but those hooks do not mediate Codex `spawn_agent`. "
            "On Codex, the conductor follows the binding prose contract and, for a role routed to "
            "another harness, executes discover -> dispatch -> status -> collect without silently "
            "falling back to a native spawn. See "
            "`$AE_REPO_DIR/content/references/cross-harness-teams.md` for the full decision rule, "
            "config schema, "
            "self-containment guard, dispatch table, and enforcement-status table."
        )
        add_occurrence(
            found, occupied, doc, match.start(), match.end(), "spawn-semantics",
            match.group(0), generated, "operational", "codex-spawn-contract",
            "cross-harness dispatch contract", "codex-harness",
        )

    for match in re.finditer(r".*?`run_in_background:\s*true`.*?(?=\n)", doc.text):
        if any(match.start() < right and match.end() > left for left, right in occupied):
            continue
        generated = match.group(0).replace(
            "run the acquire helper as a BACKGROUND command (`run_in_background: true`)",
            CODEX_BACKGROUND_COMMAND_CONTRACT,
        )
        if generated == match.group(0):
            continue
        if "run_in_background" in generated:
            raise SkillError(f"incomplete Codex background-command mapping in {doc.source}")
        generated = codexify_project_paths(generated, include_claude=True)
        generated = re.sub(r"(?<![\w.])/wrap\b", "$wrap", generated)
        add_project_path_inventory(found, doc, match.start(), match.group(0))
        add_occurrence(
            found, occupied, doc, match.start(), match.end(), "spawn-semantics",
            match.group(0), generated, "operational", "codex-session-polling",
            "exec_command + write_stdin", "codex-harness",
        )

    literal_rules = [
        (r"~/DinoStack/\.claude/skills/agentic-engineering", "dinostack-home", "$AE_CORE_SKILL_ROOT", "mapped-resource", "skill-root", "agentic-engineering", "dinostack-repository"),
        (r"~/DinoStack", "dinostack-home", "$AE_REPO_DIR", "validated-repository", "repository-root", "content/SKILL.md", "dinostack-repository"),
        (r"~?/??\.claude/skills/agentic-engineering", "claude-path", "$AE_CORE_SKILL_ROOT", "mapped-resource", "skill-root", "agentic-engineering", "dinostack-repository"),
        (r"~/\.claude", "claude-path", "$AE_SHARED_CONFIG_DIR", "shared-config-path", "global-config-root", "$HOME/.claude", "shared-user-config"),
        (r"\.claude/agents", "claude-path", "$AE_REPO_DIR/content/agents", "mapped-resource", "repository-path", "content/agents", "dinostack-repository"),
        (r"\.claude/commands", "claude-path", "$AE_REPO_DIR/content/commands", "mapped-resource", "repository-path", "content/commands", "dinostack-repository"),
        (r"\$CLAUDE_CODE_SESSION_ID", "session-variable", "$AE_SESSION_ID", "runtime-helper", "session-id", "bin/agentic-codex-session-id", "codex-harness"),
    ]
    for pattern, cls, generated, mode, target_kind, target, scope in literal_rules:
        for match in re.finditer(pattern, doc.text):
            add_occurrence(found, occupied, doc, match.start(), match.end(), cls, match.group(0),
                           generated, "operational", mode, target, scope)

    explicit_project = re.compile(
        r"(?:<cwd>|\[cwd\])/(\.(?:claude|agentic)(?:/[A-Za-z0-9_.*<>\[\]-]+)*/?|\.gitignore)"
    )
    for match in explicit_project.finditer(doc.text):
        token = match.group(1).rstrip(".,;:)")
        end = match.start(1) + len(token)
        add_occurrence(found, occupied, doc, match.start(), end, "project-path", match.group(0)[:end-match.start()],
                       f"$AE_PROJECT_DIR/{token}", "operational", "invoked-project-path", token,
                       "invoked-project")

    scoped_path = re.compile(r"(?<![~\w/])(\.(?:claude|agentic)(?:/[A-Za-z0-9_.*<>\[\]-]+)*/?)")
    for match in scoped_path.finditer(doc.text):
        token = match.group(1).rstrip(".,;:)")
        end = match.start(1) + len(token)
        is_project = token.startswith(".agentic") or doc.source.startswith("content/commands/")
        if is_project:
            generated, mode, scope = f"$AE_PROJECT_DIR/{token}", "invoked-project-path", "invoked-project"
        else:
            generated, mode, scope = f"$AE_REPO_DIR/{token}", "validated-repository", "dinostack-repository"
        add_occurrence(found, occupied, doc, match.start(1), end, "scoped-path", token,
                       generated, "operational", mode, token, scope)

    for match in re.finditer(r"(?<![/\w])\.gitignore\b", doc.text):
        add_occurrence(found, occupied, doc, match.start(), match.end(), "project-path", ".gitignore",
                       "$AE_PROJECT_DIR/.gitignore", "operational", "invoked-project-path",
                       ".gitignore", "invoked-project")

    for match in re.finditer(r"isolation:\s*[\"']worktree[\"']", doc.text):
        add_occurrence(found, occupied, doc, match.start(), match.end(), "unsupported-spawn-field",
                       match.group(0), "the explicit Codex worktree bootstrap contract above",
                       "operational", "codex-spawn-contract", "git worktree add", "codex-harness")
    for match in re.finditer(r"run_in_background(?:\s*:\s*(?:true|false))?", doc.text):
        add_occurrence(found, occupied, doc, match.start(), match.end(), "unsupported-spawn-field",
                       match.group(0), "the asynchronous Codex spawn contract above",
                       "operational", "codex-spawn-contract", "spawn_agent", "codex-harness")

    names = command_names(repo)
    mapped_slashes = tuple(sorted((*names, "simplify"), key=len, reverse=True))
    slash_pattern = r"(?<![\w./-])/((?:" + "|".join(map(re.escape, mapped_slashes)) + r"))\b"
    for match in re.finditer(slash_pattern, doc.text):
        name = match.group(1)
        if name in WORKFLOWS or name == "agentic-engineering":
            generated, mode, target = f"${name}", "native-skill", name
        elif name == "simplify":
            generated, mode, target = SIMPLIFY_CONTRACT, "cleanup-resource-contract", "references/skeptic-protocol.md#section-12"
        else:
            generated = f"manual workflow '{name}' via `$AE_REPO_DIR/bin/agentic-codex-dispatch command {name}`"
            mode, target = "manual-command-resource", f"content/commands/{name}.md"
        add_occurrence(found, occupied, doc, match.start(), match.end(), "slash-workflow",
                       match.group(0), generated, "operational", mode, target, "dinostack-repository")

    all_slashes = re.compile(r"(?<![\w./:-])/([a-z][a-z0-9-]+)\b")
    display_slashes = {
        "attachments", "blob", "browse", "dev", "issue", "issues", "jira", "null",
        "operators", "pull", "rest", "staleness", "tmp", "unavailable", "view", "wrap-internal",
    }
    for match in all_slashes.finditer(doc.text):
        if any(match.start() < right and match.end() > left for left, right in occupied):
            continue
        name = match.group(1)
        line_start = doc.text.rfind("\n", 0, match.start()) + 1
        line_end = doc.text.find("\n", match.end())
        if line_end < 0:
            line_end = len(doc.text)
        line = doc.text[line_start:line_end]
        quoted = (match.start() > 0 and doc.text[match.start() - 1] == "`") or (
            match.end() < len(doc.text) and doc.text[match.end()] == "`"
        )
        operational = quoted or bool(re.search(r"\b(?:run|invoke|execute|command|use)\b", line, re.I))
        if name == "exit":
            add_occurrence(found, occupied, doc, match.start(), match.end(), "slash-workflow",
                           match.group(0), match.group(0), "operational", "codex-built-in",
                           "Codex CLI /exit", "codex-harness")
        elif name in display_slashes or not operational:
            add_occurrence(found, occupied, doc, match.start(), match.end(), "slash-token",
                           match.group(0), match.group(0), "display-only", "display-only",
                           "hashed-source-occurrence", "display-only")
        else:
            raise SkillError(
                f"unsupported operational slash workflow {match.group(0)!r} in {doc.source}; "
                "add an explicit native, manual-resource, cleanup-resource, or Codex built-in mapping"
            )

    for match in re.finditer(r"(?<![/\w.-])METHODOLOGY\.md\b", doc.text):
        add_occurrence(found, occupied, doc, match.start(), match.end(), "methodology-reference",
                       match.group(0), "$AE_CORE_SKILL_ROOT/METHODOLOGY.md", "operational",
                       "mapped-resource", "METHODOLOGY.md")

    repo_pattern = r"(?<![\w$./-])((?:content/(?:rules|commands|agents|references|sections)/[A-Za-z0-9_./*-]+)|(?:(?:bin|hooks|scripts|\.codex)/[A-Za-z0-9_./*-]+))"
    for match in re.finditer(repo_pattern, doc.text):
        token = match.group(1).rstrip(".,;:)")
        end = match.start(1) + len(token)
        add_occurrence(found, occupied, doc, match.start(1), end, "repository-path", token,
                       f"$AE_REPO_DIR/{token}", "operational", "validated-repository", token)

    tool_pattern = r"`(Agent|Task|Read|Glob|Grep|Bash|Edit|Write|AskUserQuestion)`"
    for match in re.finditer(tool_pattern, doc.text):
        token = match.group(1)
        line_start = doc.text.rfind("\n", 0, match.start()) + 1
        line_end = doc.text.find("\n", match.end())
        if line_end < 0:
            line_end = len(doc.text)
        line = doc.text[line_start:line_end]
        claude_historical = token in {"Agent", "Task"} and bool(
            re.search(r"Claude Code|PreToolUse|hook|legacy", line, re.I)
        )
        if claude_historical:
            generated = "Claude Agent" if token == "Agent" else "legacy Claude Task"
            mode, target, scope = "claude-harness-reference", token, "claude-harness"
        else:
            generated = TOOL_MAP[token]
            mode, target, scope = "codex-tool", TOOL_MAP[token], "codex-harness"
        add_occurrence(found, occupied, doc, match.start(1), match.end(1), "agent-tool",
                       token, generated, "operational", mode, target, scope)

    semantic_pattern = r"\b(Agent|Task|Read|Glob|Grep|Bash|Edit|Write|AskUserQuestion)\b"
    for match in re.finditer(semantic_pattern, doc.text):
        token = match.group(1)
        if token == "Task" and doc.text[match.end():].startswith(" Decomposition"):
            add_occurrence(found, occupied, doc, match.start(1), match.end(1), "agent-tool",
                           token, token, "semantic-reference", "section-title",
                           "Task Decomposition", "canonical-source")
            continue
        line_start = doc.text.rfind("\n", 0, match.start()) + 1
        line_end = doc.text.find("\n", match.end())
        if line_end < 0:
            line_end = len(doc.text)
        line = doc.text[line_start:line_end]
        if token in {"Agent", "Task"}:
            historical = bool(re.search(r"Claude Code|PreToolUse|hook|legacy", line, re.I))
            generated = ("Claude Agent" if token == "Agent" else "legacy Claude Task") if historical else "spawn_agent"
            mode = "claude-harness-reference" if historical else "codex-spawn-contract"
        else:
            generated, mode = token, "compatibility-preamble"
        add_occurrence(found, occupied, doc, match.start(1), match.end(1), "agent-tool",
                       token, generated, "semantic-reference", mode, TOOL_MAP[token], "codex-harness")

    shell_occurrences(doc, found, occupied, repo)
    return sorted(found, key=lambda item: item.start)


def current_inventory(repo: Path) -> tuple[list[dict[str, str]], dict[str, list[Occurrence]]]:
    by_source: dict[str, list[Occurrence]] = {}
    for doc in documents(repo):
        by_source[doc.source] = inventory_document(doc, repo)
    records = [item.record() for items in by_source.values() for item in items]
    records.sort(key=lambda item: (item["source"], item["occurrence_hash"], item["source_token"]))
    return records, by_source


def compatibility_path(repo: Path) -> Path:
    return repo / ".codex/skill-compatibility.yml"


def compatibility_payload(repo: Path) -> dict[str, object]:
    records, _ = current_inventory(repo)
    return {
        "magic": "DINOSTACK_CODEX_SKILL_COMPATIBILITY",
        "schema_version": 1,
        "sources": [doc.source for doc in documents(repo)],
        "occurrences": records,
    }


def load_compatibility(repo: Path) -> dict[str, object]:
    path = compatibility_path(repo)
    try:
        payload = json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise SkillError(f"{path} must be JSON-compatible YAML: {exc}") from exc
    expected = compatibility_payload(repo)
    if payload != expected:
        old = {item.get("occurrence_hash") for item in payload.get("occurrences", []) if isinstance(item, dict)}
        new = {item["occurrence_hash"] for item in expected["occurrences"]}
        missing, stale = sorted(new - old), sorted(old - new)
        raise SkillError(
            "compatibility inventory drift: "
            f"{len(missing)} unmapped/new and {len(stale)} stale occurrences; "
            "review `python3 scripts/codex-skills.py inventory --repo .`"
        )
    return payload


def transform(text: str, occurrences: Iterable[Occurrence]) -> str:
    rendered = text
    for item in sorted(occurrences, key=lambda value: value.start, reverse=True):
        if item.occurrence_class.startswith("inventory-only-"):
            continue
        if rendered[item.start:item.end] != item.source_token:
            raise SkillError(f"transform identity mismatch in {item.source}: {item.source_token!r}")
        rendered = rendered[:item.start] + item.generated_token + rendered[item.end:]
    return rendered


def frontmatter(repo: Path, name: str) -> str:
    path = repo / ".codex/skill-frontmatter" / f"{name}.yml"
    text = read_text(path)
    match = re.fullmatch(r"---\nname: ([a-z0-9-]+)\ndescription: ([^\n]+)\n---\n", text)
    if not match or match.group(1) != name or not match.group(2).strip():
        raise SkillError(f"invalid Codex skill frontmatter: {path}")
    return text


def preamble(name: str) -> str:
    workflow = name != "agentic-engineering"
    shared = "resources" if workflow else "."
    return f"""
<!-- Generated by scripts/codex-skills.py. Do not edit directly. -->

## Codex resource resolution

Before executing this skill, resolve the physical directory containing this loaded `SKILL.md`
(follow the installed skill-directory symlink) and bind it as `AE_SKILL_ROOT`. Set
`AE_CORE_SKILL_ROOT` to `{shared}` beneath that physical root and validate its
`.dinostack-skill.json` marker has `magic={MAGIC}`, `adapter=codex`,
`name=agentic-engineering`, and `schema_version={SCHEMA}`. Resolve every logical resource through
the adjacent `RESOURCE-MAP.json`; reject missing, escaping, symlink-loop, or wrong-type targets.
Derive `AE_REPO_DIR` from the validated core marker plus its mapped `bin` resource and require the
repository signature (`content/SKILL.md`, `.codex`, and the dispatch helper); never fall back to
the process working directory. Bind `AE_PROJECT_DIR` to the absolute invoked project root before
changing directories (`git rev-parse --show-toplevel` when inside a repository, otherwise the
verified invocation directory). Project `.claude/**`, `.agentic/**`, `.gitignore`, QA, settings,
compression, and migration state resolve only beneath `AE_PROJECT_DIR`, never beneath
`AE_REPO_DIR`. Bind `AE_SHARED_CONFIG_DIR` to the validated `$HOME/.claude` cross-adapter
configuration directory. Map canonical filesystem tools to Codex filesystem reads, `rg --files`,
`rg`, shell, and `apply_patch`; ask one bounded direct question only after default derivation.
Derive `AE_SESSION_ID` by passing hook JSON to
`$AE_REPO_DIR/bin/agentic-codex-session-id`. Native workflows are invoked with `$` syntax.
Other DinoStack workflows remain manual command resources loaded with
`$AE_REPO_DIR/bin/agentic-codex-dispatch command <name>`; do not claim bare slash registration.

{CODEX_SPAWN_CONTRACT}

"""


def resource_map(name: str, inventory_hash: str) -> dict[str, object]:
    if name == "agentic-engineering":
        resources = {
            "METHODOLOGY.md": {"path": "METHODOLOGY.md", "type": "file"},
            "agents": {"path": "agents", "type": "directory"},
            "bin": {"path": "bin", "type": "directory"},
            "commands": {"path": "commands", "type": "directory"},
            "hooks": {"path": "hooks", "type": "directory"},
            "project-scaffolding.yml": {"path": "project-scaffolding.yml", "type": "file"},
            "references": {"path": "references", "type": "directory"},
            "rules": {"path": "rules", "type": "directory"},
            "scripts": {"path": "scripts", "type": "directory"},
            "sections": {"path": "sections", "type": "directory"},
            "templates/.agentic/config.json": {"path": "templates/.agentic/config.json", "type": "file"},
            "templates/.agentic/learnings.md": {"path": "templates/.agentic/learnings.md", "type": "file"},
        }
    else:
        command = WORKFLOWS[name]
        resources = {
            "core": {"path": "resources", "type": "directory"},
            "workflow": {"path": f"resources/{command.removeprefix('content/')}", "type": "file"},
        }
    return {
        "compatibility_inventory_sha256": inventory_hash,
        "resources": resources,
        "schema_version": 1,
        "skill": name,
    }


def marker(name: str) -> dict[str, object]:
    return {"adapter": "codex", "magic": MAGIC, "name": name, "schema_version": SCHEMA}


def safe_link(path: Path, target: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, path)


def render_tree(repo: Path, output: Path, staging: Path) -> None:
    compatibility = load_compatibility(repo)
    records, by_source = current_inventory(repo)
    inventory_hash = sha256(canonical_json(compatibility))
    docs = {doc.source: doc.text for doc in documents(repo)}
    core = staging / "agentic-engineering"
    core.mkdir(parents=True)
    core_body = transform(docs["content/SKILL.md"], by_source["content/SKILL.md"])
    methodology = transform(docs["assembled:METHODOLOGY.md"], by_source["assembled:METHODOLOGY.md"])
    (core / "SKILL.md").write_text(frontmatter(repo, "agentic-engineering") + preamble("agentic-engineering") + core_body, encoding="utf-8")
    (core / "METHODOLOGY.md").write_text(methodology, encoding="utf-8")
    (core / "RESOURCE-MAP.json").write_bytes(canonical_json(resource_map("agentic-engineering", inventory_hash)))
    (core / ".dinostack-skill.json").write_bytes(canonical_json(marker("agentic-engineering")))

    target_paths = {
        "rules": repo / "content/rules", "commands": repo / "content/commands",
        "agents": repo / "content/agents", "references": repo / "content/references",
        "sections": repo / "content/sections", "bin": repo / "bin", "hooks": repo / "hooks",
        "scripts": repo / "scripts", "project-scaffolding.yml": repo / "content/project-scaffolding.yml",
        "templates/.agentic/config.json": repo / "content/templates/.agentic/config.json",
        "templates/.agentic/learnings.md": repo / "content/templates/.agentic/learnings.md",
    }
    for rel, target in target_paths.items():
        final_path = output / "agentic-engineering" / rel
        safe_link(core / rel, os.path.relpath(target, final_path.parent))

    for name, source in WORKFLOWS.items():
        skill = staging / name
        skill.mkdir()
        body = transform(docs[source], by_source[source])
        (skill / "SKILL.md").write_text(frontmatter(repo, name) + preamble(name) + body, encoding="utf-8")
        (skill / "RESOURCE-MAP.json").write_bytes(canonical_json(resource_map(name, inventory_hash)))
        (skill / ".dinostack-skill.json").write_bytes(canonical_json(marker(name)))
        safe_link(skill / "resources", "../agentic-engineering")


def scan_tree(root: Path) -> dict[str, tuple[str, bytes | str]]:
    result: dict[str, tuple[str, bytes | str]] = {}
    if not root.exists():
        return result
    if root.is_symlink() or not root.is_dir():
        raise SkillError(f"generated root must be a real directory: {root}")
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        mode = os.lstat(path).st_mode
        if stat.S_ISLNK(mode):
            result[rel] = ("link", os.readlink(path))
        elif stat.S_ISREG(mode):
            result[rel] = ("file", path.read_bytes())
        elif stat.S_ISDIR(mode):
            result[rel] = ("directory", b"")
        else:
            raise SkillError(f"special file in generated tree: {path}")
    return result


def validate_resources(root: Path) -> None:
    repository = (root / "agentic-engineering/bin").resolve(strict=True).parent
    for name in SKILLS:
        skill = root / name
        if json.loads((skill / ".dinostack-skill.json").read_text()) != marker(name):
            raise SkillError(f"invalid marker for {name}")
        resource_data = json.loads((skill / "RESOURCE-MAP.json").read_text())
        physical = skill.resolve(strict=True)
        for logical, descriptor in resource_data["resources"].items():
            candidate = physical / descriptor["path"]
            resolved = candidate.resolve(strict=True)
            if descriptor["type"] == "file" and not resolved.is_file():
                raise SkillError(f"resource {name}:{logical} is not a file")
            if descriptor["type"] == "directory" and not resolved.is_dir():
                raise SkillError(f"resource {name}:{logical} is not a directory")
            if not resolved.is_relative_to(repository) and not resolved.is_relative_to(physical):
                raise SkillError(f"resource escapes validated repository: {name}:{logical}")


def sync_tree(staging: Path, output: Path) -> None:
    if output.exists() and (output.is_symlink() or not output.is_dir()):
        raise SkillError(f"generated root must be a real directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    expected = scan_tree(staging)
    actual = scan_tree(output)
    for rel, (kind, value) in expected.items():
        destination = output / rel
        if actual.get(rel) == (kind, value):
            continue
        if kind == "directory":
            if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
                raise SkillError(f"cannot replace non-directory generated path: {destination}")
            destination.mkdir(parents=True, exist_ok=True)
        elif kind == "file":
            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(value if isinstance(value, bytes) else value.encode())
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, destination)
            finally:
                if os.path.lexists(temp_name):
                    os.unlink(temp_name)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = destination.parent / f".{destination.name}.link.{os.getpid()}"
            if os.path.lexists(temp):
                os.unlink(temp)
            os.symlink(str(value), temp)
            os.replace(temp, destination)
    stale = sorted(set(actual) - set(expected), key=lambda rel: (rel.count("/"), rel), reverse=True)
    for rel in stale:
        path = output / rel
        mode = os.lstat(path).st_mode
        if stat.S_ISLNK(mode) or stat.S_ISREG(mode):
            path.unlink()
        elif stat.S_ISDIR(mode):
            path.rmdir()
        else:
            raise SkillError(f"refusing to prune special generated path: {path}")


def build(repo: Path, output: Path) -> None:
    output_parent = output.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".codex-skills-render-", dir=output_parent) as temp:
        staging = Path(temp)
        render_tree(repo, output, staging)
        validate_resources(staging)
        sync_tree(staging, output)
    check(repo, output)


def check(repo: Path, output: Path) -> None:
    load_compatibility(repo)
    if not output.exists() or output.is_symlink() or not output.is_dir():
        raise SkillError(f"generated root missing or unsafe: {output}")
    with tempfile.TemporaryDirectory(prefix="codex-skills-check-") as temp:
        expected_root = Path(temp)
        render_tree(repo, output, expected_root)
        expected = scan_tree(expected_root)
        actual = scan_tree(output)
        if expected != actual:
            missing = sorted(set(expected) - set(actual))
            unexpected = sorted(set(actual) - set(expected))
            changed = sorted(rel for rel in set(actual) & set(expected) if actual[rel] != expected[rel])
            raise SkillError(f"generated skill drift: missing={missing}, unexpected={unexpected}, changed={changed}")
    validate_resources(output)
    with tempfile.TemporaryDirectory(prefix="codex-skill-home-") as home, tempfile.TemporaryDirectory(prefix="codex-skill-cwd-") as cwd:
        install = Path(home) / ".agents/skills"
        install.mkdir(parents=True)
        for name in SKILLS:
            os.symlink(output / name, install / name)
        previous = Path.cwd()
        try:
            os.chdir(cwd)
            validate_resources(install)
        finally:
            os.chdir(previous)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "check", "inventory"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--repo", required=True, type=Path)
        if command == "build":
            sub.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    repo = args.repo.expanduser().resolve(strict=True)
    output = getattr(args, "output", None)
    if output is None:
        output = repo / ".codex/skills"
    elif not output.is_absolute():
        output = (Path.cwd() / output).resolve()
    try:
        if args.command == "inventory":
            sys.stdout.buffer.write(inventory_json(compatibility_payload(repo)))
        elif args.command == "build":
            build(repo, output)
            print(f"built exactly {len(SKILLS)} Codex skills in {output}")
        else:
            check(repo, output)
            print(f"Codex skill check: OK ({len(SKILLS)} skills)")
    except SkillError as exc:
        print(f"codex-skills: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
