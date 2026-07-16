#!/usr/bin/env python3
"""Regression tests for deterministic Codex native-skill generation and checking."""

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
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
GENERATOR = Path("scripts/codex-skills.py")
SKILL_NAMES = {"agentic-engineering", "brief", "wrap", "implement-ticket"}


def run(repo: Path, *arguments: str, expected: int = 0, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(repo / GENERATOR), *arguments],
        cwd=cwd or repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != expected:
        raise AssertionError(
            f"expected exit {expected}, got {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def copy_repo(destination: Path) -> Path:
    root = destination / "repo"
    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {name for name in names if name == "__pycache__" or name.endswith(".pyc")}
        if Path(directory).resolve() == REPO.resolve():
            ignored.update(name for name in names if name in {".git", ".agentic"})
        return ignored

    shutil.copytree(
        REPO,
        root,
        symlinks=True,
        ignore=ignore,
    )
    return root


def fingerprint(root: Path) -> dict[str, tuple[object, ...]]:
    records: dict[str, tuple[object, ...]] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            records[rel] = ("link", os.readlink(path), info.st_mtime_ns)
        elif stat.S_ISREG(info.st_mode):
            records[rel] = ("file", hashlib.sha256(path.read_bytes()).hexdigest(), info.st_mtime_ns)
        elif stat.S_ISDIR(info.st_mode):
            records[rel] = ("directory", info.st_mtime_ns)
        else:
            records[rel] = ("special", stat.S_IFMT(info.st_mode), info.st_mtime_ns)
    return records


class CodexSkillGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-skills-test-")
        self.addCleanup(self.temporary.cleanup)
        self.repo = copy_repo(Path(self.temporary.name))

    def check(self, expected: int = 0, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return run(self.repo, "check", "--repo", str(self.repo), expected=expected, cwd=cwd)

    def build(self) -> subprocess.CompletedProcess[str]:
        return run(self.repo, "build", "--repo", str(self.repo))

    def test_exact_four_valid_skills_and_unrelated_cwd(self) -> None:
        skills = self.repo / ".codex/skills"
        self.assertEqual(SKILL_NAMES, {entry.name for entry in skills.iterdir()})
        unrelated = Path(self.temporary.name) / "unrelated" / "nested"
        unrelated.mkdir(parents=True)
        result = self.check(cwd=unrelated)
        self.assertIn("OK (4 skills)", result.stdout)
        for name in SKILL_NAMES:
            skill = skills / name
            text = (skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertRegex(text, rf"\A---\nname: {re.escape(name)}\ndescription: .+\n---\n")
            marker = json.loads((skill / ".dinostack-skill.json").read_text())
            self.assertEqual("DINOSTACK_CODEX_SKILL", marker["magic"])

    def test_check_is_read_only(self) -> None:
        before = fingerprint(self.repo)
        self.check()
        self.assertEqual(before, fingerprint(self.repo))

    def test_generated_byte_and_missing_resource_mutations_fail(self) -> None:
        skill = self.repo / ".codex/skills/brief/SKILL.md"
        skill.write_text(skill.read_text() + "corruption\n", encoding="utf-8")
        self.check(expected=1)
        self.build()
        (self.repo / "content/commands/brief.md").unlink()
        self.check(expected=1)

    def test_frontmatter_and_link_mutations_fail(self) -> None:
        frontmatter = self.repo / ".codex/skill-frontmatter/brief.yml"
        frontmatter.write_text("---\nname: wrong\ndescription: broken\n---\n", encoding="utf-8")
        self.check(expected=1)
        shutil.copy2(REPO / ".codex/skill-frontmatter/brief.yml", frontmatter)
        link = self.repo / ".codex/skills/brief/resources"
        link.unlink()
        link.symlink_to("../../../../outside")
        self.check(expected=1)

    def test_unexpected_paths_fail_then_build_prunes_and_repairs(self) -> None:
        stale_file = self.repo / ".codex/skills/stale.txt"
        stale_directory = self.repo / ".codex/skills/agentic-engineering/stale"
        stale_file.write_text("stale", encoding="utf-8")
        stale_directory.mkdir()
        (stale_directory / "old.txt").write_text("old", encoding="utf-8")
        generated = self.repo / ".codex/skills/wrap/SKILL.md"
        generated.write_text("drift", encoding="utf-8")
        self.check(expected=1)
        self.build()
        self.assertFalse(stale_file.exists())
        self.assertFalse(stale_directory.exists())
        self.check()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unavailable")
    def test_special_generated_path_is_rejected(self) -> None:
        fifo = self.repo / ".codex/skills/hostile-fifo"
        os.mkfifo(fifo)
        self.check(expected=1)
        self.build_result = run(self.repo, "build", "--repo", str(self.repo), expected=1)
        self.assertIn("special file", self.build_result.stderr)

    def test_every_compatibility_class_fails_closed_on_new_occurrence(self) -> None:
        payload = json.loads((self.repo / ".codex/skill-compatibility.yml").read_text())
        classes = {item["kind"] + ":" + item["resolution_mode"] for item in payload["occurrences"]}
        self.assertTrue(classes)
        additions = {
            "claude-path": "Path: .claude/agents/new-role.md",
            "dinostack-home": "Path: ~/DinoStack/new-resource",
            "session-variable": "Value: $CLAUDE_CODE_SESSION_ID",
            "methodology-reference": "Read METHODOLOGY.md now.",
            "slash-workflow": "Run /brief now.",
            "agent-tool": "Use `Read` now.",
            "repository-path": "Read content/rules/new-rule.md.",
            "fenced-shell-binary": "```bash\nnew-unmapped-binary --flag\n```",
        }
        actual_classes = {item.get("resolution_mode") for item in payload["occurrences"]}
        self.assertIn("native-skill", actual_classes)
        for label, addition in additions.items():
            with self.subTest(compatibility_class=label):
                source = self.repo / "content/SKILL.md"
                original = source.read_text(encoding="utf-8")
                source.write_text(original + f"\n{addition}\n", encoding="utf-8")
                result = self.check(expected=1)
                self.assertIn("compatibility inventory drift", result.stderr)
                source.write_text(original, encoding="utf-8")
        self.check()

    def test_inventory_and_build_are_deterministic(self) -> None:
        inventory_before = (self.repo / ".codex/skill-compatibility.yml").read_bytes()
        tree_before = fingerprint(self.repo / ".codex/skills")
        generated = subprocess.check_output(
            [sys.executable, str(self.repo / GENERATOR), "inventory", "--repo", str(self.repo)],
            cwd=self.repo,
        )
        self.assertEqual(inventory_before, generated)
        self.build()
        self.assertEqual(tree_before, fingerprint(self.repo / ".codex/skills"))

    def test_project_local_paths_keep_invoked_project_scope(self) -> None:
        wrap = (self.repo / ".codex/skills/wrap/SKILL.md").read_text(encoding="utf-8")
        ticket = (self.repo / ".codex/skills/implement-ticket/SKILL.md").read_text(encoding="utf-8")
        core = (self.repo / ".codex/skills/agentic-engineering/SKILL.md").read_text(encoding="utf-8")
        for path in (
            ".claude/settings.json",
            ".claude/settings.local.json",
            ".claude/compression-state.json",
            ".agentic/compression-state.json",
            ".gitignore",
        ):
            self.assertIn(f"$AE_PROJECT_DIR/{path}", wrap)
            self.assertNotIn(f"$AE_REPO_DIR/{path}", wrap)
        for path in (".agentic/qa.md", ".claude/qa.md"):
            self.assertIn(f"$AE_PROJECT_DIR/{path}", ticket)
            self.assertNotIn(f"$AE_REPO_DIR/{path}", ticket)
        self.assertIn("$AE_REPO_DIR/.claude/build.sh", core)

        payload = json.loads((self.repo / ".codex/skill-compatibility.yml").read_text())
        project_records = [
            item for item in payload["occurrences"]
            if item["source_token"] in {
                ".claude/settings.json", ".claude/settings.local.json",
                ".claude/compression-state.json", ".agentic/compression-state.json",
                ".agentic/qa.md", ".claude/qa.md", ".gitignore",
            }
        ]
        self.assertTrue(project_records)
        self.assertTrue(all(item.get("scope") == "invoked-project" for item in project_records))
        repository_records = [
            item for item in payload["occurrences"]
            if item["source_token"] == ".claude/build.sh"
        ]
        self.assertTrue(repository_records)
        self.assertTrue(all(item.get("scope") == "dinostack-repository" for item in repository_records))

    def test_generated_spawn_contract_is_executable_codex_semantics(self) -> None:
        generated = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((self.repo / ".codex/skills").rglob("*.md"))
        )
        self.assertNotRegex(generated, r"\bisolation\s*:")
        self.assertNotIn("run_in_background", generated)
        self.assertNotIn("on BOTH `spawn_agent` and `spawn_agent`", generated)
        self.assertNotIn("legacy `legacy Claude Task`", generated)
        self.assertNotIn("set `the explicit Codex", generated)
        self.assertNotIn("legacy Claude Task Decomposition", generated)
        self.assertNotIn(".agentic$wrap", generated)
        self.assertIn("git worktree add", generated)
        self.assertIn("origin/main", generated)
        self.assertIn("Work only in the pre-created worktree", generated)
        self.assertIn("$AE_REPO_DIR/bin/agentic-codex-dispatch agent <role>", generated)
        self.assertIn("spawn_agent", generated)

        payload = json.loads((self.repo / ".codex/skill-compatibility.yml").read_text())
        unsupported = [
            item for item in payload["occurrences"]
            if "isolation:" in item["source_token"] or "run_in_background" in item["source_token"]
        ]
        self.assertTrue(unsupported)
        self.assertTrue(all(
            item["resolution_mode"] in {"codex-spawn-contract", "codex-session-polling"}
            for item in unsupported
        ))

    def test_simplify_uses_explicit_cleanup_resource_contract(self) -> None:
        generated = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((self.repo / ".codex/skills").rglob("*.md"))
        )
        self.assertNotIn("/simplify", generated)
        self.assertIn("skeptic-protocol.md Section 12", generated)
        self.assertIn("spawn_agent", generated)
        payload = json.loads((self.repo / ".codex/skill-compatibility.yml").read_text())
        simplify = [item for item in payload["occurrences"] if item["source_token"] == "/simplify"]
        self.assertEqual(3, len(simplify))
        self.assertTrue(all(item["resolution_mode"] == "cleanup-resource-contract" for item in simplify))

    def test_proceed_tokens_remain_display_only(self) -> None:
        generated = (self.repo / ".codex/skills/implement-ticket/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`yes`/proceed override", generated)
        payload = json.loads((self.repo / ".codex/skill-compatibility.yml").read_text())
        proceed = [item for item in payload["occurrences"] if item["source_token"] == "/proceed"]
        self.assertEqual(1, len(proceed))
        self.assertTrue(all(item["kind"] == "display-only" for item in proceed))
        self.assertTrue(all(item["resolution_mode"] == "display-only" for item in proceed))

    def test_unsupported_spawn_fields_and_operational_slash_fail_closed(self) -> None:
        source = self.repo / "content/SKILL.md"
        original = source.read_text(encoding="utf-8")
        additions = (
            "Spawn with `isolation: \"worktree\"`.",
            "Set `run_in_background: true`.",
            "Run `/unsupported-codex-workflow` now.",
        )
        for addition in additions:
            with self.subTest(addition=addition):
                source.write_text(original + f"\n{addition}\n", encoding="utf-8")
                result = self.check(expected=1)
                self.assertTrue(
                    "compatibility inventory drift" in result.stderr
                    or "unsupported operational slash workflow" in result.stderr,
                    result.stderr,
                )
        source.write_text(original, encoding="utf-8")
        self.check()


def clean_clone_test() -> None:
    with tempfile.TemporaryDirectory(prefix="codex-skills-clean-clone-") as temporary:
        clone = Path(temporary) / "clone"
        subprocess.run(["git", "clone", "--no-hardlinks", str(REPO), str(clone)], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        run(clone, "check", "--repo", str(clone))
        run(clone, "build", "--repo", str(clone))
        run(clone, "check", "--repo", str(clone))
        diff = subprocess.run(["git", "diff", "--exit-code"], cwd=clone, check=False,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if diff.returncode:
            raise AssertionError(f"clean-clone build drifted:\n{diff.stdout}\n{diff.stderr}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--clean-clone", action="store_true")
    known, remaining = parser.parse_known_args()
    if known.clean_clone:
        clean_clone_test()
        print("clean clone Codex skill build: OK")
    else:
        unittest.main(argv=[sys.argv[0], *remaining])
