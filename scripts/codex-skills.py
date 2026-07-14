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
    occurrence_hash: str

    def record(self) -> dict[str, str]:
        return {
            "expected_target": self.expected_target,
            "generated_token": self.generated_token,
            "kind": self.kind,
            "occurrence_hash": self.occurrence_hash,
            "resolution_mode": self.resolution_mode,
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
) -> None:
    if any(start < right and end > left for left, right in occupied):
        return
    occupied.append((start, end))
    found.append(Occurrence(
        doc.source, start, end, occurrence_class, token, generated, kind, mode, target,
        line_fingerprint(doc.text, start, token, occurrence_class, doc.source),
    ))


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
    literal_rules = [
        (r"~/DinoStack/\.claude/skills/agentic-engineering", "dinostack-home", "$AE_CORE_SKILL_ROOT", "mapped-resource", "skill-root", "agentic-engineering"),
        (r"~/DinoStack", "dinostack-home", "$AE_REPO_DIR", "validated-repository", "repository-root", "content/SKILL.md"),
        (r"~?/??\.claude/skills/agentic-engineering", "claude-path", "$AE_CORE_SKILL_ROOT", "mapped-resource", "skill-root", "agentic-engineering"),
        (r"~/\.claude", "claude-path", "$AE_SHARED_CONFIG_DIR", "shared-config-path", "global-config-root", "$HOME/.claude"),
        (r"\.claude/agents", "claude-path", "$AE_REPO_DIR/content/agents", "mapped-resource", "repository-path", "content/agents"),
        (r"\.claude/commands", "claude-path", "$AE_REPO_DIR/content/commands", "mapped-resource", "repository-path", "content/commands"),
        (r"(?<![~\w/])\.claude", "claude-path", "$AE_REPO_DIR/.claude", "validated-repository", "repository-path", ".claude"),
        (r"\$CLAUDE_CODE_SESSION_ID", "session-variable", "$AE_SESSION_ID", "runtime-helper", "session-id", "bin/agentic-codex-session-id"),
    ]
    for pattern, cls, generated, mode, target_kind, target in literal_rules:
        for match in re.finditer(pattern, doc.text):
            add_occurrence(found, occupied, doc, match.start(), match.end(), cls, match.group(0),
                           generated, "operational", mode, target)

    names = command_names(repo)
    slash_pattern = r"(?<![\w./-])/((?:" + "|".join(map(re.escape, names)) + r"))\b"
    for match in re.finditer(slash_pattern, doc.text):
        name = match.group(1)
        if name in WORKFLOWS or name == "agentic-engineering":
            generated, mode, target = f"${name}", "native-skill", name
        else:
            generated = f"manual workflow '{name}' via `$AE_REPO_DIR/bin/agentic-codex-dispatch command {name}`"
            mode, target = "manual-command-resource", f"content/commands/{name}.md"
        add_occurrence(found, occupied, doc, match.start(), match.end(), "slash-workflow",
                       match.group(0), generated, "operational", mode, target)

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
        add_occurrence(found, occupied, doc, match.start(1), match.end(1), "agent-tool",
                       token, TOOL_MAP[token], "operational", "codex-tool", TOOL_MAP[token])

    semantic_pattern = r"\b(Agent|Task|Read|Glob|Grep|Bash|Edit|Write|AskUserQuestion)\b"
    for match in re.finditer(semantic_pattern, doc.text):
        token = match.group(1)
        add_occurrence(found, occupied, doc, match.start(1), match.end(1), "agent-tool",
                       token, token, "semantic-reference", "compatibility-preamble", TOOL_MAP[token])

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
the process working directory. Bind `AE_SHARED_CONFIG_DIR` to the validated `$HOME/.claude`
cross-adapter configuration directory. Interpret canonical Claude `Agent` and `Task` operations as
Codex `spawn_agent`: load the named role from the mapped `agents` resource and create an explicit
repository git worktree before any spawn that requires isolation. Map canonical filesystem tools
to Codex filesystem reads, `rg --files`, `rg`, shell, and `apply_patch`; ask one bounded direct
question only after default derivation. Derive `AE_SESSION_ID` by passing hook JSON to
`$AE_REPO_DIR/bin/agentic-codex-session-id`. Native workflows are invoked with `$` syntax.
Other DinoStack workflows remain manual command resources loaded with
`$AE_REPO_DIR/bin/agentic-codex-dispatch command <name>`; do not claim bare slash registration.

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
