#!/usr/bin/env python3
"""
Purpose: Deterministically generate and validate DinoStack's four native Codex skills.

Public API: ``build --repo ROOT [--output DIR]``, ``check --repo ROOT``,
            ``inventory --repo ROOT`` for explicitly refreshing the reviewed
            compatibility occurrence inventory, and ``runtime-guidance
            --repo ROOT`` for translating stdin through the workflow contract.

Upstream deps: canonical content/SKILL.md, content/sections, three canonical
               command bodies, .codex/skill-frontmatter, and the reviewed
               .codex/skill-compatibility.yml inventory. Standard library only.

Downstream consumers: .codex/build.sh, scripts/check-codex-skill-sync.sh, CI,
                      scripts/test/test_codex_skills.py, and the repo-owned
                      .agentic/codex-skill-root-ownership.json registry used
                      by arbitrary-output builds.

Failure modes: refuses symlinked/special generated roots, unmatched source
               occurrences, invalid frontmatter, escaping resources, or drift.
               Check is read-only. A canonical-output build replaces only its
               owned generated tree; an arbitrary-output build also creates or atomically replaces
               .agentic/codex-skill-root-ownership.json.

Performance: linear in canonical source and generated-tree size.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MAGIC = "DINOSTACK_CODEX_SKILL"
SCHEMA = 1
ROOT_MAGIC = "DINOSTACK_CODEX_SKILL_ROOT"
ROOT_MARKER = ".dinostack-generated-root.json"
ROOT_REGISTRY_MAGIC = "DINOSTACK_CODEX_SKILL_ROOT_OWNERSHIP"
ROOT_REGISTRY = Path(".agentic/codex-skill-root-ownership.json")
CODEX_CONTEXT_PATH = "~/.codex/projects/[hash]/context.md"
CONTEXT_WRITER_MIGRATION = "context-writer-migration"
SKILLS = ("agentic-engineering", "brief", "wrap", "implement-ticket")
WORKFLOWS = {
    "brief": "content/commands/ds-brief.md",
    "wrap": "content/commands/ds-wrap.md",
    "implement-ticket": "content/commands/ds-implement-ticket.md",
}
NATIVE_COMMAND_SKILLS = {Path(source).stem: skill for skill, source in WORKFLOWS.items()}
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
2. Resolve `BASE_BRANCH` with
   `$AE_REPO_DIR/bin/ds-codex-dispatch base-branch "$AE_PROJECT_DIR"`. This applies the
   canonical precedence: exactly one dedicated unfenced whole-line `BASE_BRANCH:` declaration in
   project `AGENTS.md` (with an optional Markdown list prefix and optional `Declaration:` prefix),
   then local `develop`, then local `development`. Multiple matching declarations are rejected as
   ambiguous. If none exists, the helper fails closed; ask the operator whether to use `main`
   (recommended, falling back to `master`) or establish a develop-based workflow, exactly as
   required by the base-branch resolution protocol.
3. Choose a unique branch and absolute worktree path beneath `$AE_PROJECT_DIR/.agentic/worktrees/`.
4. Run `git worktree add "$AE_PROJECT_DIR/.agentic/worktrees/<branch>" -b "<branch>" "origin/$BASE_BRANCH"`.
5. Load the named role instructions with
   `$AE_REPO_DIR/bin/ds-codex-dispatch agent <role>`.
6. Call `spawn_agent` with supported inputs (`task_name`, `message`, and `fork_turns`). Begin the
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
    "`$AE_REPO_DIR/bin/ds-codex-dispatch agent <role>`, call `spawn_agent`, then run the "
    "required narrow Skeptic review)"
)
CODEX_BACKGROUND_COMMAND_CONTRACT = (
    "Start the helper with Codex `exec_command`; if `exec_command` yields a session ID, keep the "
    "conductor responsive and poll that session with `write_stdin` until completion; if it returns "
    "a terminal result, branch on that result immediately"
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


def workflow_resolution(name: str) -> tuple[str, str, str]:
    native_skill = NATIVE_COMMAND_SKILLS.get(name)
    if native_skill:
        return f"${native_skill}", "native-skill", native_skill
    if name == "agentic-engineering":
        return f"${name}", "native-skill", name
    if name == "simplify":
        return (
            SIMPLIFY_CONTRACT,
            "cleanup-resource-contract",
            "references/skeptic-protocol.md#section-12",
        )
    return (
        f"manual workflow '{name}' via "
        f"`$AE_REPO_DIR/bin/ds-codex-dispatch command {name}`",
        "manual-command-resource",
        f"content/commands/{name}.md",
    )


def add_workflow_occurrences(
    doc: Document,
    repo: Path,
    found: list[Occurrence],
    occupied: list[tuple[int, int]],
) -> None:
    names = command_names(repo)
    mapped_slashes = tuple(sorted((*names, "simplify"), key=len, reverse=True))
    slash_pattern = r"(?<![\w./-])/((?:" + "|".join(map(re.escape, mapped_slashes)) + r"))\b"
    for match in re.finditer(slash_pattern, doc.text):
        name = match.group(1)
        generated, mode, target = workflow_resolution(name)
        source_start = match.start()
        source_end = match.end()
        source_token = match.group(0)
        if (
            mode == "manual-command-resource"
            and source_start > 0
            and source_end < len(doc.text)
            and doc.text[source_start - 1] == "`"
            and doc.text[source_end] == "`"
        ):
            source_start -= 1
            source_end += 1
            source_token = doc.text[source_start:source_end]
        if any(source_start < right and source_end > left for left, right in occupied):
            found.append(
                Occurrence(
                    doc.source,
                    source_start,
                    source_end,
                    "inventory-only-slash-workflow",
                    source_token,
                    generated,
                    "operational",
                    mode,
                    target,
                    "dinostack-repository",
                    line_fingerprint(
                        doc.text,
                        source_start,
                        source_token,
                        "inventory-only-slash-workflow",
                        doc.source,
                    ),
                )
            )
            continue
        add_occurrence(
            found,
            occupied,
            doc,
            source_start,
            source_end,
            "slash-workflow",
            source_token,
            generated,
            "operational",
            mode,
            target,
            "dinostack-repository",
        )


def rewrite_workflow_references(text: str, repo: Path) -> str:
    names = command_names(repo)
    mapped = tuple(sorted((*names, "simplify"), key=len, reverse=True))
    pattern = r"(?<![\w./-])/((?:" + "|".join(map(re.escape, mapped)) + r"))\b"

    def replacement(match: re.Match[str]) -> str:
        generated, _, _ = workflow_resolution(match.group(1))
        return generated

    for name in mapped:
        generated, mode, _ = workflow_resolution(name)
        if mode == "manual-command-resource":
            text = text.replace(f"`/{name}`", generated)
    return re.sub(pattern, replacement, text)


def add_codex_stop_hook_occurrences(
    doc: Document,
    found: list[Occurrence],
    occupied: list[tuple[int, int]],
) -> None:
    paragraph_rules = (
        (
            r"\*\*Writer scope: the conductor is the primary writer of `\.agentic/events\.jsonl`\.\*\*"
            r".*?(?=\n\n)",
            (
                "**Writer scope: the conductor is the primary writer of "
                "`$AE_PROJECT_DIR/.agentic/events.jsonl`.** The current Codex Stop hook writes "
                f"session continuity only to `{CODEX_CONTEXT_PATH}`. It does not append "
                "`session_total` events or mirror project-local orchestration state. The "
                "project-local writer migration is deferred to "
                f"`{CONTEXT_WRITER_MIGRATION}`. Subagents do not write the events log."
            ),
        ),
        (
            r"\*\*Session context\*\* is auto-written by the Stop hook.*?(?=\n\n)",
            (
                "**Session context.** The current Codex Stop hook writes lightweight session "
                f"continuity to `{CODEX_CONTEXT_PATH}` after each Stop event. Project-local "
                "`$AE_PROJECT_DIR/.agentic/context.md` is richer output written intentionally "
                f"by `$wrap`; automatic project-local writing is deferred to "
                f"`{CONTEXT_WRITER_MIGRATION}`. Update root `MEMORY.md` when stable facts were "
                "learned. Close the session cleanly so the current Codex Stop hook can finish "
                "its hashed global continuity write."
            ),
        ),
        (
            r"\*\*Session context\.\*\* \*\*The read contract is unchanged:.*?(?=\n\n)",
            (
                "**Session context - Codex runtime boundary.** The current Codex Stop hook writes "
                f"lightweight session continuity only to `{CODEX_CONTEXT_PATH}` after each Stop "
                "event. It does not write project-local "
                "`$AE_PROJECT_DIR/.agentic/context.d/<session_id>.md`, does not write "
                "`$AE_PROJECT_DIR/.agentic/context.md`, and does not recompose a project-local "
                f"rollup; that writer migration is deferred to `{CONTEXT_WRITER_MIGRATION}`. "
                "`$wrap` may still write its richer project-local `_wrap.md` handoff, but the "
                "current Codex Stop hook does not consume it."
            ),
        ),
        (
            r"\*\*Per-developer session log:\*\*.*?(?=\n\n)",
            (
                "**Per-developer session log.** Canonical methodology describes a harness Stop "
                "hook that writes `$AE_PROJECT_DIR/.agentic/session-log/<developer_id>.jsonl`. "
                "The current Codex Stop hook does not write that project-local telemetry; it "
                f"writes only `{CODEX_CONTEXT_PATH}`. Codex project-local telemetry migration "
                f"is deferred to `{CONTEXT_WRITER_MIGRATION}`."
            ),
        ),
        (
            r"\*\*Telemetry is BUFFERED, not lost\.\*\*.*?(?=\n\n)",
            (
                "**Telemetry runtime boundary.** The current Codex Stop hook does not write "
                "`~/.agentic/session-log/.pending/<uuid>.json` or project-local session logs; "
                f"it writes only `{CODEX_CONTEXT_PATH}`. Codex telemetry writer migration is "
                f"deferred to `{CONTEXT_WRITER_MIGRATION}`."
            ),
        ),
        (
            r"The Stop hook auto-writes `<cwd>/\.agentic/context\.md`.*?(?=\n\n)",
            (
                f"The current Codex Stop hook writes raw continuity to `{CODEX_CONTEXT_PATH}`. "
                "`$wrap` intentionally writes or merges the richer project-local "
                "`$AE_PROJECT_DIR/.agentic/context.md`; automatic project-local writing is "
                f"deferred to `{CONTEXT_WRITER_MIGRATION}`. It is also the ongoing counterpart "
                "to the project scaffolding workflow and populates AGENTS.md with durable "
                "decisions, conventions, stack details, and gotchas."
            ),
        ),
        (
            r"Use when you want a richer context file than the auto-hook provides "
            r"— e\.g\. before handing off complex in-progress work to a future session\.",
            (
                "Use when you want a richer project-local handoff than the current Codex Stop "
                "continuity file provides - for example, before handing off complex in-progress "
                "work to a future session."
            ),
        ),
        (
            r"The Stop hook writes this session's `<cwd>/\.agentic/context\.d/"
            r"<session_id>\.md`.*?(?=\n\n)",
            (
                f"The current Codex Stop hook writes raw continuity only to "
                f"`{CODEX_CONTEXT_PATH}` after a Stop event. It does not write project-local "
                "`$AE_PROJECT_DIR/.agentic/context.d/<session_id>.md`, does not write "
                "`$AE_PROJECT_DIR/.agentic/context.md`, and does not recompose a project-local "
                f"rollup; migration is deferred to `{CONTEXT_WRITER_MIGRATION}`. `$wrap` "
                "continues to write the richer project-local "
                "`$AE_PROJECT_DIR/.agentic/_wrap.md` handoff and populate AGENTS.md with durable "
                "decisions, conventions, stack details, and gotchas."
            ),
        ),
        (
            r"- Do NOT write `_wrap\.md` \(the Stop hook already writes a raw activity shard "
            r"after every turn, and the rollup already carries it - running /ds-wrap on a "
            r"zero-substance session duplicates that work with a hand-curated version of "
            r"nothing\)",
            (
                f"- Do NOT write `_wrap.md`. The current Codex Stop hook already wrote the "
                f"session's raw continuity to `{CODEX_CONTEXT_PATH}`. A zero-substance `$wrap` "
                "would only create an empty project-local handoff; automatic project-local "
                f"rollup integration remains deferred to `{CONTEXT_WRITER_MIGRATION}`."
            ),
        ),
        (
            r"\*\*Pre-flight lock acquisition\.\*\* /ds-wrap writes to several shared "
            r"project-local files.*?Acquire a project-local lock before proceeding:",
            (
                "**Pre-flight lock acquisition.** `$wrap` writes several shared project-local "
                "files (`_wrap.md`, memory.md, AGENTS.md, compression-state.json, rolling "
                "snapshots). It does not write `$AE_PROJECT_DIR/.agentic/context.md`. The current "
                f"Codex Stop hook writes only `{CODEX_CONTEXT_PATH}`; automatic project-local "
                f"rollup integration is deferred to `{CONTEXT_WRITER_MIGRATION}`. Concurrent "
                "`$wrap` runs in the same project would clobber the files `$wrap` does own. "
                "Acquire a project-local lock before proceeding:"
            ),
        ),
        (
            r"This section is the single source of truth for the on-disk artifacts that drive "
            r"the synchronous `/ds-wrap`.*?(?=\n\n)",
            (
                "This section is the source of truth for the Claude-only deferred-wrap marker "
                "schemas. The Claude Stop hook `$AE_REPO_DIR/hooks/stop-context.js`, the "
                "OpenCode plugin, and the deferred-wrap daemon consume those schemas. The "
                f"current Codex Stop hook writes only `{CODEX_CONTEXT_PATH}` and does not stage "
                f"these project-local markers; migration is deferred to "
                f"`{CONTEXT_WRITER_MIGRATION}`."
            ),
        ),
        (
            r"\*\*2\. `\.agentic/wrap/last-wrap` \(the wrap-recency sentinel\)\.\*\*.*?(?=\n\n)",
            (
                "**2. `$AE_PROJECT_DIR/.agentic/wrap/last-wrap` (the wrap-recency sentinel).** "
                "This project-local sentinel is written only after a successful `$wrap` Part A "
                "write. Claude and OpenCode marker consumers use it for staging suppression. "
                f"The current Codex Stop hook writes only `{CODEX_CONTEXT_PATH}` and does not "
                f"consume this sentinel; migration is deferred to `{CONTEXT_WRITER_MIGRATION}`."
            ),
        ),
        (
            r"\*\*Output path \(context\.md\):\*\* `<cwd>/\.agentic/context\.md`\..*?(?=\n\n)",
            (
                "**Output path (context.md):** `$AE_PROJECT_DIR/.agentic/context.md`. "
                "Project-local and written intentionally by `$wrap`. The current Codex Stop "
                f"hook instead writes `{CODEX_CONTEXT_PATH}`. Automatic project-local writing "
                f"is deferred to `{CONTEXT_WRITER_MIGRATION}`."
            ),
        ),
        (
            r"`<cwd>/\.agentic/context\.md` is now a DERIVED ROLLUP:.*?(?=\n\n)",
            (
                "The project-local derived-rollup contract belongs to harnesses that implement "
                "the project-local context writer. The current Codex Stop hook instead writes "
                f"only `{CODEX_CONTEXT_PATH}` and does not recompose "
                "`$AE_PROJECT_DIR/.agentic/context.md`. `$wrap` writes "
                "`$AE_PROJECT_DIR/.agentic/_wrap.md`; integrating that handoff into an automatic "
                f"Codex project-local rollup is deferred to `{CONTEXT_WRITER_MIGRATION}`."
            ),
        ),
        (
            r"Why: `context\.md` had 13 writer sites.*?(?=\n\n)",
            (
                f"Why: the current Codex Stop hook writes continuity only to "
                f"`{CODEX_CONTEXT_PATH}` and does not read or recompose project-local "
                "`$AE_PROJECT_DIR/.agentic/context.md`. `$wrap` owns its richer project-local "
                "`$AE_PROJECT_DIR/.agentic/_wrap.md` handoff under the wrap lock. Connecting "
                "that handoff to an automatic Codex project-local context writer remains "
                f"deferred to `{CONTEXT_WRITER_MIGRATION}`. Create "
                "`$AE_PROJECT_DIR/.agentic/` if it does not exist."
            ),
        ),
        (
            r"\*\*A conductor-direct session-context write under this exemption targets "
            r"`\.agentic/_wrap\.md`.*?quietly lose the conductor's edit\.",
            (
                "**A conductor-direct session-context write under this exemption targets "
                "`$AE_PROJECT_DIR/.agentic/_wrap.md`, NEVER "
                "`$AE_PROJECT_DIR/.agentic/context.md`.** The current Codex Stop hook writes "
                f"only `{CODEX_CONTEXT_PATH}` and does not consume or recompose either "
                f"project-local file; project-local integration is deferred to "
                f"`{CONTEXT_WRITER_MIGRATION}`."
            ),
        ),
        (
            r"\*\*Final reminder:\*\* After `/ds-wrap` completes, close the session cleanly.*?(?=\n\n|\Z)",
            (
                "**Final reminder:** After `$wrap` completes, close the session cleanly so the "
                f"current Codex Stop hook can finish writing `{CODEX_CONTEXT_PATH}`. The "
                f"project-local migration remains deferred to `{CONTEXT_WRITER_MIGRATION}`."
            ),
        ),
        (
            r"\*\*Contract D — Stop hook mirror\.\*\*\n\nThe Stop hook .*?(?=\n\n)",
            (
                "**Contract D - Codex runtime boundary.**\n\n"
                f"The current Codex Stop hook writes only `{CODEX_CONTEXT_PATH}`. It does not "
                "mark `loop-state.json` interrupted or mirror `batch-state.json`; stale active "
                "state is recovered by the existing age-based resume path. Project-local state "
                f"writer migration is deferred to `{CONTEXT_WRITER_MIGRATION}`."
            ),
        ),
        (
            r"\*\*Telemetry commit:\*\*.*?(?=\n\n)",
            (
                "**Telemetry commit - Codex runtime boundary.** Commit only existing "
                "`$AE_PROJECT_DIR/.agentic/session-log/<developer_id>.jsonl` entries produced "
                "by a supported writer. The current Codex Stop hook does not create those "
                f"entries; it writes only `{CODEX_CONTEXT_PATH}`. Project-local telemetry "
                f"migration is deferred to `{CONTEXT_WRITER_MIGRATION}`."
            ),
        ),
    )
    for pattern, generated in paragraph_rules:
        for match in re.finditer(pattern, doc.text, re.S):
            add_occurrence(
                found,
                occupied,
                doc,
                match.start(),
                match.end(),
                "codex-stop-hook-contract",
                match.group(0),
                generated,
                "operational",
                "codex-stop-hook-runtime",
                CODEX_CONTEXT_PATH,
                "codex-harness",
            )

    token_rules = (
        (
            "- Do NOT write context.md (the Stop hook already writes a raw context file after every "
            "turn - running /ds-wrap on a zero-substance session duplicates that work with a "
            "hand-curated version of nothing)",
            (
                f"- Do NOT write project-local context.md for a zero-substance session. The current "
                f"Codex Stop hook already writes raw continuity to `{CODEX_CONTEXT_PATH}`; "
                f"project-local automatic writing is deferred to `{CONTEXT_WRITER_MIGRATION}`."
            ),
        ),
        ("Preserved by Stop hook.", "Managed only by `$wrap`."),
        (
            '- `interrupt_reason`: enum `unknown | null` — only `unknown` is a writable value '
            "(other values reserved for future writers; the Stop hook cannot distinguish "
            "rate-limit vs crash at hook time).",
            (
                "- `interrupt_reason`: enum `unknown | null`. The current Codex Stop hook does "
                "not write this field; stale active state uses the age-based resume path until "
                f"`{CONTEXT_WRITER_MIGRATION}` ships."
            ),
        ),
        (
            '**If the file exists and `status == "active"` with `last_updated` more than 10 '
            'minutes ago:** treat as implicitly interrupted (the Stop hook may not have fired).',
            (
                '**If the file exists and `status == "active"` with `last_updated` more than 10 '
                "minutes ago:** treat as implicitly interrupted. The current Codex Stop hook "
                "does not write interruption state."
            ),
        ),
        (
            '`"interrupted"` (Stop hook or crash)',
            (
                '`"interrupted"` (a supported harness interruption writer or age-based crash '
                "recovery; not the current Codex Stop hook)"
            ),
        ),
        (
            "> Note: `paused_at` and `pause_reason` are written by Phase 12a on graceful handoff. "
            "`interrupted_at` and `interrupt_reason` are written by the Stop hook on session-exit "
            "crash. These are two distinct paths; `last_summary` is only populated on graceful "
            "pause (the Stop hook cannot synthesize it).",
            (
                "> Note: `paused_at` and `pause_reason` are written by Phase 12a on graceful "
                "handoff. The current Codex Stop hook does not write `interrupted_at`, "
                "`interrupt_reason`, or `last_summary`; age-based recovery handles stale active "
                f"state until `{CONTEXT_WRITER_MIGRATION}` ships."
            ),
        ),
    )
    for token, generated in token_rules:
        for match in re.finditer(re.escape(token), doc.text):
            add_occurrence(
                found,
                occupied,
                doc,
                match.start(),
                match.end(),
                "codex-stop-hook-contract",
                token,
                generated,
                "operational",
                "codex-stop-hook-runtime",
                CODEX_CONTEXT_PATH,
                "codex-harness",
            )


def render_runtime_guidance(text: str, repo: Path) -> str:
    text = re.sub(r"(?<![\w./-])/wrap\b", "$wrap", text)
    doc = Document("generated:.codex/AGENTS.md", text)
    found = inventory_document(doc, repo)
    rendered = transform(text, found, repo)
    remaining = sorted(set(re.findall(r"(?<![\w./-])/ds-[a-z0-9-]+\b", rendered)))
    if remaining:
        raise SkillError(
            "operational bare slash guidance remains in generated .codex/AGENTS.md: "
            + ", ".join(remaining)
        )
    return rendered


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
                        generated = "$AE_REPO_DIR/bin/ds-codex-dispatch legacy-cli claude"
                        mode, target, kind = "shimmed", "bin/ds-codex-dispatch", "operational"
                    elif token.startswith(("agentic-", "ds-")):
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
    if doc.source == "generated:.codex/AGENTS.md":
        binding_preamble = re.search(
            r"(?ms)^## Codex runtime binding preamble\n.*?(?=^\*\*Note:\*\*)",
            doc.text,
        )
        if binding_preamble:
            add_occurrence(
                found,
                occupied,
                doc,
                binding_preamble.start(),
                binding_preamble.end(),
                "codex-binding-preamble",
                binding_preamble.group(0),
                binding_preamble.group(0),
                "operational",
                "codex-binding-preamble",
                "$HOME/.codex/AGENTS.md",
                "codex-harness",
            )
    add_codex_stop_hook_occurrences(doc, found, occupied)

    model_routing_rules = (
        (
            "pass an explicit `model: opus` on the Agent tool call",
            (
                "state explicit Tier 3 intent in the task brief and resolve the reviewer "
                "through role routing before `spawn_agent`"
            ),
        ),
        (
            "The conductor's explicit `model: opus` is the only enforcement.",
            (
                "Explicit Tier 3 task-brief intent plus pre-spawn role routing is the Codex "
                "enforcement."
            ),
        ),
        (
            "omit the model param",
            "use role-default routing and state default Tier intent in the task brief",
        ),
        (
            "model-param mapping",
            "tier-intent and role-routing mapping",
        ),
        (
            "explicit sub-Opus `model` param",
            "explicit below-Tier-3 role routing",
        ),
        (
            "explicit `model` param",
            "explicit role-routing override",
        ),
        (
            "`model: opus`",
            "explicit Tier 3 task-brief intent",
        ),
        (
            "model param",
            "role-routing override",
        ),
    )
    for token, generated in model_routing_rules:
        for match in re.finditer(re.escape(token), doc.text):
            add_occurrence(
                found,
                occupied,
                doc,
                match.start(),
                match.end(),
                "unsupported-spawn-field",
                token,
                generated,
                "operational",
                "codex-role-routing",
                "spawn_agent message",
                "codex-harness",
            )

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
            generated = generated.replace(
                "**Isolation worktrees (`worktree-agent-*`)** are created explicitly",
                "**Isolation worktrees** are created explicitly",
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

    for match in re.finditer(
        r"(?ims)^3\. \*\*On busy:.*?(?=^4\. Liveness)",
        doc.text,
    ):
        if any(match.start() < right and match.end() > left for left, right in occupied):
            continue
        generated, replacements = re.subn(
            r"Run the acquire helper again,\s*this time as a BACKGROUND command\s*"
            r"\(\s*`run_in_background:\s*true`\s*\)",
            CODEX_BACKGROUND_COMMAND_CONTRACT,
            match.group(0),
            count=1,
            flags=re.IGNORECASE,
        )
        if replacements != 1:
            continue
        generated = generated.replace("$CLAUDE_CODE_SESSION_ID", "$AE_SESSION_ID")
        generated = codexify_project_paths(generated, include_claude=True)
        generated = re.sub(r"(?<![\w.])/wrap\b", "$wrap", generated)
        if any(
            forbidden in generated
            for forbidden in (
                "run_in_background",
                "CLAUDE_CODE_SESSION_ID",
                "CLAUDE_SESSION_UUID",
                "AGENTIC_SESSION_ID",
            )
        ):
            raise SkillError(f"incomplete Codex busy-lock paragraph mapping in {doc.source}")
        add_project_path_inventory(found, doc, match.start(), match.group(0))
        add_occurrence(
            found, occupied, doc, match.start(), match.end(), "spawn-semantics",
            match.group(0), generated, "operational", "codex-session-polling",
            "exec_command + conditional session polling + write_stdin", "codex-harness",
        )

    for match in re.finditer(
        r"(?ims)^5\. \*\*`--session-id`.*?(?=^\*\*Self-heal on acquire)",
        doc.text,
    ):
        if any(match.start() < right and match.end() > left for left, right in occupied):
            continue
        generated = match.group(0).replace(
            "$CLAUDE_CODE_SESSION_ID",
            "$AE_SESSION_ID",
        )
        generated, replacements = re.subn(
            r"Use `?CLAUDE_CODE_SESSION_ID`? and only that variable\s*-\s*"
            r"`?AGENTIC_SESSION_ID`? and `?CLAUDE_SESSION_UUID`? are both empty in a live "
            r"session \(`?bin/agentic-migrate`? reads them and is already silently degraded as "
            r"a result\)\.",
            "Use `AE_SESSION_ID` only. It is the Codex session binding derived by passing hook "
            "JSON to `$AE_REPO_DIR/bin/ds-codex-session-id`.",
            generated,
            count=1,
        )
        if replacements != 1:
            continue
        generated = re.sub(
            r"Nothing here is harness-specific beyond the variable name: adapters that do not "
            r"export it simply get the fallback\.",
            "If session-ID derivation yields no identifier, the documented empty-value fallback "
            "applies.",
            generated,
            count=1,
        )
        generated = codexify_project_paths(generated, include_claude=True)
        if any(
            forbidden in generated
            for forbidden in (
                "CLAUDE_CODE_SESSION_ID",
                "CLAUDE_SESSION_UUID",
                "AGENTIC_SESSION_ID",
            )
        ):
            raise SkillError(f"incomplete Codex session-variable paragraph mapping in {doc.source}")
        add_project_path_inventory(found, doc, match.start(), match.group(0))
        add_occurrence(
            found, occupied, doc, match.start(), match.end(), "session-variable",
            match.group(0), generated, "operational", "runtime-helper",
            "bin/ds-codex-session-id", "codex-harness",
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

    for match in re.finditer(r"\bAgent tool call\b", doc.text, re.IGNORECASE):
        if any(match.start() < right and match.end() > left for left, right in occupied):
            continue
        add_occurrence(
            found,
            occupied,
            doc,
            match.start(),
            match.end(),
            "unsupported-spawn-field",
            match.group(0),
            "`spawn_agent` invocation",
            "operational",
            "codex-spawn-contract",
            "spawn_agent",
            "codex-harness",
        )

    literal_rules = [
        (
            r"ds-identity resolve-hook --cwd <cwd>",
            "codex-profile-identity-command",
            'AGENTIC_CONFIG_DIR="$AE_CODEX_CONFIG_DIR" ds-identity '
            'resolve-hook --cwd "$AE_PROJECT_DIR"',
            "validated-config-path",
            "profile-identity-command",
            "AE_CODEX_CONFIG_DIR",
            "codex-config-directory",
        ),
        (
            r"The active profile config dir is the first non-empty qualifying value "
            r"from `AGENTIC_CONFIG_DIR`, `CLAUDE_CONFIG_DIR`, then `CODEX_HOME`; "
            r"expand a leading `~`, normalize lexically, accept only a path under "
            r"`\$HOME`, and reject symlinked components\.",
            "codex-config-binding",
            "For Codex, use only the already-validated `$AE_CODEX_CONFIG_DIR` "
            "runtime binding as the active profile config dir; do not re-resolve "
            "it from `AGENTIC_CONFIG_DIR`, `CLAUDE_CONFIG_DIR`, or `CODEX_HOME`.",
            "validated-config-path",
            "runtime-binding",
            "AE_CODEX_CONFIG_DIR",
            "codex-config-directory",
        ),
        (
            r"it selects the first qualifying profile binding from "
            r"`AGENTIC_CONFIG_DIR`, `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, or "
            r"`PI_CODING_AGENT_DIR`",
            "codex-config-binding",
            "it must use only the already-validated `$AE_CODEX_CONFIG_DIR` "
            "runtime binding",
            "validated-config-path",
            "runtime-binding",
            "AE_CODEX_CONFIG_DIR",
            "codex-config-directory",
        ),
        (
            r"<active-config-dir>/identity\.yml",
            "codex-config-path",
            "$AE_CODEX_CONFIG_DIR/identity.yml",
            "validated-config-path",
            "identity-file",
            "identity.yml",
            "codex-config-directory",
        ),
        (
            r"pass `--profile-dir <dir>` when the active config dir cannot be "
            r"derived from `AGENTIC_CONFIG_DIR`, `CLAUDE_CONFIG_DIR`, "
            r"`CODEX_HOME`, or `PI_CODING_AGENT_DIR`",
            "codex-profile-identity-command",
            "always pass `--profile-dir \"$AE_CODEX_CONFIG_DIR\"` for profile "
            "identity operations",
            "validated-config-path",
            "profile-identity-command",
            "AE_CODEX_CONFIG_DIR",
            "codex-config-directory",
        ),
        (
            r"  Confirm: ds-identity confirm --scope <scope>\n"
            r"  Correct: ds-identity init <handle> --force --scope <scope>",
            "codex-profile-identity-command",
            "  Confirm (global/project): ds-identity confirm --scope "
            "<global|project>\n"
            "  Correct (global/project): ds-identity init <handle> --force "
            "--scope <global|project>\n"
            "  Show (profile): ds-identity show --scope profile --profile-dir "
            "\"$AE_CODEX_CONFIG_DIR\"\n"
            "  Confirm (profile): ds-identity confirm --scope profile "
            "--profile-dir \"$AE_CODEX_CONFIG_DIR\"\n"
            "  Correct (profile): ds-identity init <handle> --force --scope "
            "profile --profile-dir \"$AE_CODEX_CONFIG_DIR\"",
            "validated-config-path",
            "profile-identity-command",
            "AE_CODEX_CONFIG_DIR",
            "codex-config-directory",
        ),
        (
            r"For profile scope, the command uses the active config-dir "
            r"environment automatically; append `--profile-dir <dir>` only when "
            r"no profile env is available\.",
            "codex-profile-identity-command",
            "For profile scope, always pass `--profile-dir "
            "\"$AE_CODEX_CONFIG_DIR\"` to `show`, `confirm`, `init`, and `auto`.",
            "validated-config-path",
            "profile-identity-command",
            "AE_CODEX_CONFIG_DIR",
            "codex-config-directory",
        ),
        (r"~/DinoStack/\.claude/skills/agentic-engineering", "dinostack-home", "$AE_CORE_SKILL_ROOT", "mapped-resource", "skill-root", "agentic-engineering", "dinostack-repository"),
        (r"~/DinoStack", "dinostack-home", "$AE_REPO_DIR", "validated-repository", "repository-root", "content/SKILL.md", "dinostack-repository"),
        (r"~?/??\.claude/skills/agentic-engineering", "claude-path", "$AE_CORE_SKILL_ROOT", "mapped-resource", "skill-root", "agentic-engineering", "dinostack-repository"),
        (r"~/\.claude", "claude-path", "$AE_SHARED_CONFIG_DIR", "shared-config-path", "global-config-root", "$HOME/.claude", "shared-user-config"),
        (r"\.claude/agents", "claude-path", "$AE_REPO_DIR/content/agents", "mapped-resource", "repository-path", "content/agents", "dinostack-repository"),
        (r"\.claude/commands", "claude-path", "$AE_REPO_DIR/content/commands", "mapped-resource", "repository-path", "content/commands", "dinostack-repository"),
        (r"\$CLAUDE_CODE_SESSION_ID", "session-variable", "$AE_SESSION_ID", "runtime-helper", "session-id", "bin/ds-codex-session-id", "codex-harness"),
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

    add_workflow_occurrences(doc, repo, found, occupied)

    all_slashes = re.compile(r"(?<![\w./:-])/([a-z][a-z0-9-]+)\b")
    display_slashes = {
        "attachments", "blob", "browse", "context", "dev", "docs", "empty", "issue", "issues", "jira", "null",
        "operators", "proceed", "pull", "rest", "staleness", "tmp", "unavailable", "view",
        "wrap-internal",
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
        if token in {"Agent", "Task"}:
            add_occurrence(found, occupied, doc, match.start(1), match.end(1), "agent-tool",
                           token, token, "semantic-reference", "canonical-prose",
                           token, "canonical-source")
            continue
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


def transform(
    text: str,
    occurrences: Iterable[Occurrence],
    repo: Path | None = None,
) -> str:
    rendered = text
    for item in sorted(occurrences, key=lambda value: value.start, reverse=True):
        if item.occurrence_class.startswith("inventory-only-"):
            continue
        if rendered[item.start:item.end] != item.source_token:
            raise SkillError(f"transform identity mismatch in {item.source}: {item.source_token!r}")
        rendered = rendered[:item.start] + item.generated_token + rendered[item.end:]
    if repo is not None:
        rendered = rewrite_workflow_references(rendered, repo)
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
`AE_REPO_DIR`. Evaluate
`$AE_REPO_DIR/bin/ds-codex-dispatch runtime-bindings "<absolute-invocation-directory>"`
before any operational step. Require its `AE_REPO_DIR` and `AE_PROJECT_DIR` values to match the
independently validated paths above, then consume the same JSON object to bind
`AE_CODEX_CONFIG_DIR`, `AE_SHARED_CONFIG_DIR`, and `AE_ACTIVATION_CONFIG`; fail closed on any
mismatch. Map canonical filesystem tools to Codex filesystem reads, `rg --files`, `rg`, shell, and
`apply_patch`; ask one bounded direct question only after default derivation.
Derive `AE_SESSION_ID` by passing hook JSON to
`$AE_REPO_DIR/bin/ds-codex-session-id`. Native workflows are invoked with `$` syntax.
Other DinoStack workflows remain manual command resources loaded with
`$AE_REPO_DIR/bin/ds-codex-dispatch command <name>`; do not claim bare slash registration.
Codex `spawn_agent` accepts only `task_name`, `message`, and `fork_turns`. Put Tier and model intent
in the task brief or resolve it through role routing before the spawn; never pass Claude-only spawn
fields. When isolation is required, the conductor creates the worktree manually before spawning.

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
            "templates/.agentic/skill-candidates.md": {
                "path": "templates/.agentic/skill-candidates.md",
                "type": "file",
            },
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


def canonical_root_marker() -> dict[str, object]:
    return {
        "adapter": "codex",
        "binding": {"kind": "repo-relative", "path": ".codex/skills"},
        "magic": ROOT_MAGIC,
        "schema_version": SCHEMA,
        "skills": list(SKILLS),
    }


def arbitrary_root_marker(repo: Path, output: Path, nonce: str) -> dict[str, object]:
    return {
        "adapter": "codex",
        "binding": {
            "kind": "absolute",
            "nonce": nonce,
            "output": str(output),
            "repo": str(repo),
        },
        "magic": ROOT_MAGIC,
        "schema_version": SCHEMA,
        "skills": list(SKILLS),
    }


def canonical_output(repo: Path) -> Path:
    return repo / ".codex/skills"


def is_canonical_output(repo: Path, output: Path) -> bool:
    return output == canonical_output(repo)


def registry_path(repo: Path) -> Path:
    return repo / ROOT_REGISTRY


def validate_registry_ancestors(repo: Path, *, create_parent: bool) -> Path:
    parent = registry_path(repo).parent
    current = repo
    for component in parent.relative_to(repo).parts:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if not create_parent:
                raise SkillError(f"ownership registry parent missing: {current}")
            current.mkdir(mode=0o700)
            info = os.lstat(current)
        except OSError as exc:
            raise SkillError(f"cannot inspect ownership registry ancestor {current}: {exc}") from exc
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise SkillError(f"unsafe ownership registry ancestor: {current}")
    return parent


def load_root_registry(
    repo: Path,
    *,
    required: bool,
    create_parent: bool = False,
) -> dict[str, object]:
    path = registry_path(repo)
    validate_registry_ancestors(repo, create_parent=create_parent)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if required:
            raise SkillError(f"ownership registry missing: {path}")
        return {
            "magic": ROOT_REGISTRY_MAGIC,
            "roots": {},
            "schema_version": SCHEMA,
        }
    except OSError as exc:
        raise SkillError(f"cannot inspect ownership registry {path}: {exc}") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise SkillError(
            f"ownership registry must be an owned mode-0600 single-link regular file: {path}"
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            opened_info = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(opened_info.st_mode)
                or opened_info.st_nlink != 1
                or opened_info.st_uid != os.geteuid()
                or stat.S_IMODE(opened_info.st_mode) != 0o600
                or (opened_info.st_dev, opened_info.st_ino) != (info.st_dev, info.st_ino)
            ):
                raise SkillError(
                    "ownership registry changed or became unsafe while opening: "
                    f"{path}"
                )
            raw_registry = handle.read()
            payload = json.loads(raw_registry.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SkillError(f"invalid ownership registry {path}: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("magic") != ROOT_REGISTRY_MAGIC
        or payload.get("schema_version") != SCHEMA
        or not isinstance(payload.get("roots"), dict)
    ):
        raise SkillError(f"invalid ownership registry schema: {path}")
    if raw_registry != canonical_json(payload):
        raise SkillError(f"ownership registry does not use exact canonical bytes: {path}")
    return payload


def write_root_registry(repo: Path, payload: dict[str, object]) -> None:
    path = registry_path(repo)
    parent = validate_registry_ancestors(repo, create_parent=True)
    if os.path.lexists(path):
        load_root_registry(repo, required=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
        validate_registry_ancestors(repo, create_parent=False)
        if os.path.lexists(path):
            load_root_registry(repo, required=True)
        os.replace(temp_name, path)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.lexists(temp_name):
            os.unlink(temp_name)


def registry_binding(
    repo: Path,
    output: Path,
    *,
    required: bool,
) -> tuple[dict[str, object], dict[str, object] | None]:
    registry = load_root_registry(repo, required=required, create_parent=not required)
    roots = registry["roots"]
    assert isinstance(roots, dict)
    binding = roots.get(str(output))
    if binding is not None and not isinstance(binding, dict):
        raise SkillError(f"invalid ownership registry binding for {output}")
    return registry, binding


def set_registry_binding(repo: Path, output: Path, nonce: str) -> None:
    registry, _ = registry_binding(repo, output, required=False)
    roots = registry["roots"]
    assert isinstance(roots, dict)
    roots[str(output)] = {"nonce": nonce, "repo": str(repo)}
    write_root_registry(repo, registry)


def safe_link(path: Path, target: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, path)


def render_tree(
    repo: Path,
    output: Path,
    staging: Path,
    ownership_marker: dict[str, object],
) -> None:
    compatibility = load_compatibility(repo)
    records, by_source = current_inventory(repo)
    inventory_hash = sha256(canonical_json(compatibility))
    docs = {doc.source: doc.text for doc in documents(repo)}
    (staging / ROOT_MARKER).write_bytes(canonical_json(ownership_marker))
    core = staging / "agentic-engineering"
    core.mkdir(parents=True)
    core_body = transform(docs["content/SKILL.md"], by_source["content/SKILL.md"], repo)
    methodology = transform(
        docs["assembled:METHODOLOGY.md"],
        by_source["assembled:METHODOLOGY.md"],
        repo,
    )
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
        "templates/.agentic/skill-candidates.md": (
            repo / "content/templates/.agentic/skill-candidates.md"
        ),
    }
    for rel, target in target_paths.items():
        final_path = output / "agentic-engineering" / rel
        safe_link(core / rel, os.path.relpath(target, final_path.parent))

    for name, source in WORKFLOWS.items():
        skill = staging / name
        skill.mkdir()
        body = transform(docs[source], by_source[source], repo)
        (skill / "SKILL.md").write_text(frontmatter(repo, name) + preamble(name) + body, encoding="utf-8")
        (skill / "RESOURCE-MAP.json").write_bytes(canonical_json(resource_map(name, inventory_hash)))
        (skill / ".dinostack-skill.json").write_bytes(canonical_json(marker(name)))
        safe_link(skill / "resources", "../agentic-engineering")


def scan_tree(root: Path) -> dict[str, tuple[str, bytes | str]]:
    result: dict[str, tuple[str, bytes | str]] = {}
    if root.is_symlink():
        raise SkillError(f"generated root must be a real directory: {root}")
    if not root.exists():
        return result
    if not root.is_dir():
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
    generated_root = root.resolve(strict=True)
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
            if (
                not resolved.is_relative_to(repository)
                and not resolved.is_relative_to(physical)
                and not resolved.is_relative_to(physical.parent)
                and not resolved.is_relative_to(generated_root)
            ):
                raise SkillError(f"resource escapes validated repository: {name}:{logical}")


def validate_link_mirror(source: Path, destination: Path, relative_prefix: str) -> None:
    if destination.is_symlink() or not destination.is_dir():
        raise SkillError(f"Codex mirror must be a real directory: {destination}")
    expected = {path.name for path in source.glob("*.md")}
    actual = {path.name for path in destination.iterdir()}
    if actual != expected:
        raise SkillError(
            f"Codex mirror drift at {destination}: "
            f"missing={sorted(expected - actual)}, unexpected={sorted(actual - expected)}"
        )
    for name in sorted(expected):
        link = destination / name
        if not link.is_symlink():
            raise SkillError(f"Codex mirror entry must be a symlink: {link}")
        expected_target = f"{relative_prefix}/{name}"
        if os.readlink(link) != expected_target:
            raise SkillError(
                f"Codex mirror target drift at {link}: "
                f"expected={expected_target!r}, actual={os.readlink(link)!r}"
            )


def validate_adapter_mirrors(repo: Path) -> None:
    validate_link_mirror(
        repo / "content/commands", repo / ".codex/commands", "../../content/commands"
    )
    validate_link_mirror(
        repo / "content/references", repo / ".codex/references", "../../content/references"
    )
    hook = repo / ".codex/hooks/skill-auto-load-check.sh"
    if not hook.is_symlink():
        raise SkillError(f"Codex shared hook mirror must be a symlink: {hook}")
    expected_target = "../../hooks/skill-auto-load-check.sh"
    if os.readlink(hook) != expected_target:
        raise SkillError(
            f"Codex shared hook target drift: expected={expected_target!r}, "
            f"actual={os.readlink(hook)!r}"
        )


def validate_generated_root_path(
    output: Path,
    *,
    required: bool,
    expected_marker: dict[str, object] | None = None,
) -> dict[str, object] | None:
    try:
        root_info = os.lstat(output)
    except FileNotFoundError:
        if required:
            raise SkillError(f"generated root missing or unsafe: {output}")
        return None
    except OSError as exc:
        raise SkillError(f"cannot inspect generated root {output}: {exc}") from exc
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise SkillError(f"generated root must be a real directory: {output}")
    if root_info.st_uid != os.geteuid() or root_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise SkillError(f"generated root has unsafe ownership or mode: {output}")

    entries = list(os.scandir(output))
    if not entries:
        if required:
            raise SkillError(f"generated root ownership marker missing: {output / ROOT_MARKER}")
        return None

    marker_path = output / ROOT_MARKER
    try:
        marker_info = os.lstat(marker_path)
    except FileNotFoundError as exc:
        raise SkillError(
            f"unowned generated root is populated and has no ownership marker: {output}"
        ) from exc
    except OSError as exc:
        raise SkillError(f"cannot inspect generated root ownership marker: {exc}") from exc
    if (
        not stat.S_ISREG(marker_info.st_mode)
        or marker_info.st_nlink != 1
        or marker_info.st_uid != os.geteuid()
        or marker_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise SkillError(
            f"generated root ownership marker is not a safe single-link regular file: {marker_path}"
        )
    try:
        marker_bytes = marker_path.read_bytes()
        marker_payload = json.loads(marker_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SkillError(f"cannot read generated root ownership marker: {marker_path}: {exc}") from exc
    if not isinstance(marker_payload, dict) or marker_bytes != canonical_json(marker_payload):
        raise SkillError(f"invalid generated root ownership marker: {marker_path}")
    if expected_marker is not None and marker_payload != expected_marker:
        raise SkillError(f"generated root ownership marker binding mismatch: {marker_path}")
    return marker_payload


def validate_arbitrary_binding(
    repo: Path,
    output: Path,
    marker_payload: dict[str, object],
) -> None:
    binding = marker_payload.get("binding")
    if (
        marker_payload.get("adapter") != "codex"
        or marker_payload.get("magic") != ROOT_MAGIC
        or marker_payload.get("schema_version") != SCHEMA
        or marker_payload.get("skills") != list(SKILLS)
        or not isinstance(binding, dict)
        or binding.get("kind") != "absolute"
        or binding.get("repo") != str(repo)
        or binding.get("output") != str(output)
        or not isinstance(binding.get("nonce"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", binding["nonce"])
    ):
        raise SkillError(f"generated root ownership marker binding mismatch: {output / ROOT_MARKER}")
    _, stored = registry_binding(repo, output, required=True)
    expected = {"nonce": binding["nonce"], "repo": str(repo)}
    if stored != expected:
        raise SkillError(f"ownership registry binding mismatch for generated root: {output}")


def prepare_root_ownership(
    repo: Path,
    output: Path,
    *,
    required: bool,
) -> tuple[dict[str, object], bool]:
    if is_canonical_output(repo, output):
        expected = canonical_root_marker()
        validate_generated_root_path(
            output,
            required=required,
            expected_marker=expected,
        )
        return expected, False

    marker_payload = validate_generated_root_path(output, required=required)
    if marker_payload is not None:
        validate_arbitrary_binding(repo, output, marker_payload)
        return marker_payload, False

    if required:
        raise SkillError(f"generated root missing or unsafe: {output}")

    registry, stored = registry_binding(repo, output, required=False)
    if stored is not None:
        if (
            not isinstance(stored, dict)
            or stored.get("repo") != str(repo)
            or not isinstance(stored.get("nonce"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", stored["nonce"])
        ):
            raise SkillError(f"invalid ownership registry binding for {output}")
        nonce = stored["nonce"]
    else:
        nonce = secrets.token_hex(32)
    return arbitrary_root_marker(repo, output, nonce), stored is None


def sync_tree(
    staging: Path,
    output: Path,
    ownership_marker: dict[str, object],
) -> None:
    validate_generated_root_path(
        output,
        required=False,
        expected_marker=ownership_marker,
    )
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
    ownership_marker, register = prepare_root_ownership(repo, output, required=False)
    output_parent = output.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".codex-skills-render-", dir=output_parent) as temp:
        staging = Path(temp)
        render_tree(repo, output, staging, ownership_marker)
        validate_resources(staging)
        if register:
            binding = ownership_marker["binding"]
            assert isinstance(binding, dict)
            nonce = binding["nonce"]
            assert isinstance(nonce, str)
            set_registry_binding(repo, output, nonce)
        sync_tree(staging, output, ownership_marker)
    check(repo, output)


def check(repo: Path, output: Path) -> None:
    load_compatibility(repo)
    validate_adapter_mirrors(repo)
    ownership_marker, _ = prepare_root_ownership(repo, output, required=True)
    with tempfile.TemporaryDirectory(prefix="codex-skills-check-") as temp:
        expected_root = Path(temp)
        render_tree(repo, output, expected_root, ownership_marker)
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
    for command in ("build", "check", "inventory", "runtime-guidance"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--repo", required=True, type=Path)
        if command in {"build", "check"}:
            sub.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    repo = args.repo.expanduser().resolve(strict=True)
    output = getattr(args, "output", None)
    if output is None:
        output = repo / ".codex/skills"
    elif not output.is_absolute():
        output = Path.cwd() / output
    output = output.expanduser()
    output = output.parent.resolve(strict=False) / output.name
    try:
        if args.command == "inventory":
            sys.stdout.buffer.write(inventory_json(compatibility_payload(repo)))
        elif args.command == "runtime-guidance":
            sys.stdout.write(render_runtime_guidance(sys.stdin.read(), repo))
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
