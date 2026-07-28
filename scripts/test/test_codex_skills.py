#!/usr/bin/env python3
"""
Purpose: Exercise deterministic Codex native-skill generation, validation, and lifecycle behavior.

Public API: ``python3 scripts/test/test_codex_skills.py [--clean-clone]``.

Upstream deps: scripts/codex-skills.py, Codex adapter build/install sources, Git,
               and the canonical/generated skill trees copied into isolated fixtures.

Downstream consumers: Codex skill-sync CI, pre-commit regression coverage, and release verification.

Failure modes: exits non-zero on generation drift, unsafe path handling, lifecycle
               ownership violations, hook trigger gaps, or compatibility regressions.

Performance: integration-heavy; copies the repository per test and optionally clones it.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import typing
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
GENERATOR = Path("scripts/codex-skills.py")
SKILL_NAMES = {"agentic-engineering", "brief", "wrap", "implement-ticket"}
ROOT_MARKER = ".dinostack-generated-root.json"


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


def execute(
    arguments: list[str],
    *,
    cwd: Path,
    expected: int = 0,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        arguments,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != expected:
        raise AssertionError(
            f"expected exit {expected}, got {result.returncode}\n"
            f"command: {arguments}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
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


def identity_fingerprint(root: Path) -> dict[str, tuple[object, ...]]:
    records: dict[str, tuple[object, ...]] = {}
    paths = [root, *sorted(root.rglob("*"))]
    for path in paths:
        rel = "." if path == root else path.relative_to(root).as_posix()
        info = os.lstat(path)
        identity = (
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_nlink,
            info.st_uid,
            info.st_gid,
            info.st_size,
            info.st_mtime_ns,
        )
        if stat.S_ISLNK(info.st_mode):
            records[rel] = ("link", *identity, os.readlink(path))
        elif stat.S_ISREG(info.st_mode):
            records[rel] = (
                "file",
                *identity,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        elif stat.S_ISDIR(info.st_mode):
            records[rel] = ("directory", *identity)
        else:
            records[rel] = ("special", *identity)
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

    def build_at_output(
        self,
        output: Path,
        *,
        expected: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        return run(
            self.repo,
            "build",
            "--repo",
            str(self.repo),
            "--output",
            str(output),
            expected=expected,
        )

    def check_at_output(
        self,
        output: Path,
        *,
        expected: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        return run(
            self.repo,
            "check",
            "--repo",
            str(self.repo),
            "--output",
            str(output),
            expected=expected,
        )

    def public_build(self) -> subprocess.CompletedProcess[str]:
        return execute(["bash", str(self.repo / ".codex/build.sh")], cwd=self.repo)

    def test_exact_four_valid_skills_and_unrelated_cwd(self) -> None:
        skills = self.repo / ".codex/skills"
        self.assertEqual(
            SKILL_NAMES | {ROOT_MARKER},
            {entry.name for entry in skills.iterdir()},
        )
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
        (self.repo / "content/commands/ds-brief.md").unlink()
        self.check(expected=1)

    def test_every_generated_output_class_is_mutation_checked(self) -> None:
        mutations = (
            ("skill body", ".codex/skills/brief/SKILL.md", "file"),
            ("marker", ".codex/skills/wrap/.dinostack-skill.json", "file"),
            ("resource map", ".codex/skills/implement-ticket/RESOURCE-MAP.json", "file"),
            ("core resource link", ".codex/skills/agentic-engineering/rules", "link"),
            ("workflow resource link", ".codex/skills/brief/resources", "link"),
        )
        for label, relative, kind in mutations:
            with self.subTest(output_class=label):
                path = self.repo / relative
                if kind == "file":
                    path.write_bytes(path.read_bytes() + b"\nmutation\n")
                else:
                    path.unlink()
                    path.symlink_to("../../../../outside")
                self.check(expected=1)
                self.build()
                self.check()

    def test_frontmatter_and_link_mutations_fail(self) -> None:
        frontmatter = self.repo / ".codex/skill-frontmatter/brief.yml"
        frontmatter.write_text("---\nname: wrong\ndescription: broken\n---\n", encoding="utf-8")
        self.check(expected=1)
        shutil.copy2(REPO / ".codex/skill-frontmatter/brief.yml", frontmatter)
        link = self.repo / ".codex/skills/brief/resources"
        link.unlink()
        link.symlink_to("../../../../outside")
        self.check(expected=1)

    def test_command_reference_and_hook_mirror_mutations_fail_and_repair(self) -> None:
        links = (
            ".codex/commands/ds-brief.md",
            ".codex/references/skeptic-protocol.md",
            ".codex/hooks/skill-auto-load-check.sh",
        )
        for relative in links:
            with self.subTest(mirror=relative):
                link = self.repo / relative
                link.unlink()
                link.symlink_to("../../../../outside")
                self.check(expected=1)
                self.public_build()
                self.check()

    def test_public_build_rejects_external_symlink_mirror_roots_without_mutation(self) -> None:
        mirrors = (
            (".codex/commands", "brief.md"),
            (".codex/references", "skeptic-protocol.md"),
            (".codex/hooks", "skill-auto-load-check.sh"),
        )
        for relative, collision_name in mirrors:
            with self.subTest(mirror_root=relative):
                fixture = Path(self.temporary.name) / relative.replace("/", "-").lstrip(".")
                fixture.mkdir()
                repo = copy_repo(fixture)
                outside = fixture / "outside"
                outside.mkdir()
                sentinel = outside / "sentinel.bin"
                collision = outside / collision_name
                unrelated = outside / "unrelated" / "preserve.txt"
                sentinel.write_bytes(b"\x00external-sentinel\xff")
                collision.write_bytes(b"external-collision-must-survive\n")
                unrelated.parent.mkdir()
                unrelated.write_bytes(b"unrelated-external-content\n")

                destination = repo / relative
                shutil.rmtree(destination)
                destination.symlink_to(outside, target_is_directory=True)
                before = fingerprint(outside)
                repo_before = fingerprint(repo)
                before_entries = {
                    path.relative_to(outside).as_posix()
                    for path in outside.rglob("*")
                }

                result = execute(
                    ["bash", str(repo / ".codex/build.sh")],
                    cwd=repo,
                    expected=1,
                )

                self.assertEqual(before, fingerprint(outside))
                self.assertEqual(repo_before, fingerprint(repo))
                self.assertEqual(
                    before_entries,
                    {
                        path.relative_to(outside).as_posix()
                        for path in outside.rglob("*")
                    },
                )
                self.assertEqual(b"\x00external-sentinel\xff", sentinel.read_bytes())
                self.assertEqual(
                    b"external-collision-must-survive\n",
                    collision.read_bytes(),
                )
                self.assertEqual(
                    b"unrelated-external-content\n",
                    unrelated.read_bytes(),
                )
                self.assertIn("unsafe Codex mirror root", result.stderr)

    def test_public_build_rejects_non_directory_mirror_roots_before_mutation(self) -> None:
        for relative in (".codex/commands", ".codex/references", ".codex/hooks"):
            with self.subTest(mirror_root=relative):
                fixture = (
                    Path(self.temporary.name)
                    / f"non-directory-{relative.replace('/', '-').lstrip('.')}"
                )
                fixture.mkdir()
                repo = copy_repo(fixture)
                destination = repo / relative
                shutil.rmtree(destination)
                destination.write_bytes(b"non-directory-root-must-survive\n")
                before = fingerprint(repo)

                result = execute(
                    ["bash", str(repo / ".codex/build.sh")],
                    cwd=repo,
                    expected=1,
                )

                self.assertEqual(before, fingerprint(repo))
                self.assertEqual(
                    b"non-directory-root-must-survive\n",
                    destination.read_bytes(),
                )
                self.assertIn("unsafe Codex mirror root", result.stderr)

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
            "slash-workflow": "Run /ds-brief now.",
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
        self.assertNotIn('origin/main"', generated)
        self.assertIn('origin/$BASE_BRANCH"', generated)
        self.assertIn('agentic-codex-dispatch base-branch "$AE_PROJECT_DIR"', generated)
        self.assertIn("then local", generated)
        self.assertIn("`develop`, then local", generated)
        self.assertIn("`development`", generated)
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

    def test_wrap_busy_lock_uses_codex_command_polling_and_session_binding(self) -> None:
        wrap = (self.repo / ".codex/skills/wrap/SKILL.md").read_text(encoding="utf-8")
        busy = re.search(
            r"(?ms)^3\. \*\*On busy:.*?(?=^4\. Liveness)",
            wrap,
        )
        self.assertIsNotNone(busy)
        paragraph = busy.group(0)
        self.assertIn("exec_command", paragraph)
        self.assertIn("session ID", paragraph)
        self.assertIn("write_stdin", paragraph)
        self.assertIn("$AE_SESSION_ID", paragraph)
        self.assertNotIn("asynchronous Codex spawn contract", paragraph)
        for forbidden in (
            "CLAUDE_CODE_SESSION_ID",
            "CLAUDE_SESSION_UUID",
            "AGENTIC_SESSION_ID",
        ):
            self.assertNotIn(forbidden, paragraph)

        directive = re.search(
            r"(?ms)^5\. \*\*`--session-id`.*?(?=^\*\*Self-heal on acquire)",
            wrap,
        )
        self.assertIsNotNone(directive)
        directive_text = directive.group(0)
        self.assertIn("$AE_SESSION_ID", directive_text)
        self.assertIn("agentic-codex-session-id", directive_text)
        for forbidden in (
            "CLAUDE_CODE_SESSION_ID",
            "CLAUDE_SESSION_UUID",
            "AGENTIC_SESSION_ID",
        ):
            self.assertNotIn(forbidden, directive_text)

    def test_global_agents_defines_runtime_bindings_before_operational_use(self) -> None:
        def assert_binding_order(text: str) -> None:
            heading = "## Codex runtime binding preamble"
            self.assertIn(heading, text)
            preamble_start = text.index(heading)
            activation_start = text.index("## Activation preflight")
            self.assertLess(preamble_start, activation_start)
            preamble = text[preamble_start:activation_start]
            for binding in (
                "AE_REPO_DIR",
                "AE_PROJECT_DIR",
                "AE_CODEX_CONFIG_DIR",
                "AE_SHARED_CONFIG_DIR",
                "AE_ACTIVATION_CONFIG",
            ):
                self.assertIn(f"bind `{binding}`", preamble)
                reference = f"${binding}"
                if reference in text:
                    self.assertLess(
                        text.index(f"bind `{binding}`"),
                        text.index(reference),
                    )
            self.assertIn("AGENTIC_CONFIG_DIR", preamble)
            self.assertIn("CODEX_HOME", preamble)
            self.assertNotIn("$HOME/.codex/AGENTS.md", preamble)
            self.assertIn("content/SKILL.md", preamble)
            self.assertIn("agentic-codex-dispatch", preamble)
            self.assertIn("fail closed", preamble)

        generated = (self.repo / ".codex/AGENTS.md").read_text(encoding="utf-8")
        assert_binding_order(generated)

        fixture = Path(self.temporary.name) / "global-agents-install"
        home = fixture / "home"
        invoked = fixture / "invoked-project"
        home.mkdir(parents=True)
        invoked.mkdir()
        execute(["git", "init", "-q", str(invoked)], cwd=fixture)
        env = os.environ.copy()
        env["HOME"] = str(home)
        env.pop("AGENTIC_CONFIG_DIR", None)
        execute(
            [
                "bash",
                str(self.repo / ".codex/install.sh"),
                "--mode=opt-out",
                "--profile=default",
                "--no-identity",
            ],
            cwd=invoked,
            env=env,
        )
        installed = (home / ".codex/AGENTS.md").read_text(encoding="utf-8")
        assert_binding_order(installed)

    def test_runtime_bindings_follow_redirected_and_default_installs(self) -> None:
        dispatcher = self.repo / "bin/agentic-codex-dispatch"
        fixture = Path(self.temporary.name) / "runtime-bindings"
        home = fixture / "home"
        invoked = fixture / "invoked-project"
        redirected = fixture / "profiles/codex-tenant"
        mismatch = fixture / "profiles/mismatch"
        home.mkdir(parents=True)
        invoked.mkdir()
        redirected.parent.mkdir()
        mismatch.mkdir()
        execute(["git", "init", "-q", str(invoked)], cwd=fixture)

        redirected_env = os.environ.copy()
        redirected_env["HOME"] = str(home)
        redirected_env["AGENTIC_CONFIG_DIR"] = str(redirected)
        redirected_env["CODEX_HOME"] = str(fixture / "ignored-codex-home")
        self.assertFalse((home / ".claude").exists())
        execute(
            [
                "bash",
                str(self.repo / ".codex/install.sh"),
                f"--config-dir={redirected}",
                "--mode=opt-in",
                "--profile=strict",
                "--no-identity",
            ],
            cwd=invoked,
            env=redirected_env,
        )
        self.assertFalse((home / ".claude").exists())
        redirected_result = execute(
            [
                sys.executable,
                str(dispatcher),
                "runtime-bindings",
                str(invoked.resolve()),
            ],
            cwd=fixture,
            env=redirected_env,
        )
        redirected_bindings = json.loads(redirected_result.stdout)
        self.assertEqual(str(self.repo.resolve()), redirected_bindings["AE_REPO_DIR"])
        self.assertEqual(str(invoked.resolve()), redirected_bindings["AE_PROJECT_DIR"])
        self.assertEqual(
            str(redirected.resolve()),
            redirected_bindings["AE_CODEX_CONFIG_DIR"],
        )
        self.assertEqual(
            str(redirected.resolve()),
            redirected_bindings["AE_SHARED_CONFIG_DIR"],
        )
        self.assertEqual(
            str((redirected / "agentic-engineering.json").resolve()),
            redirected_bindings["AE_ACTIVATION_CONFIG"],
        )
        redirected_activation = json.loads(
            (redirected / "agentic-engineering.json").read_text(encoding="utf-8")
        )
        self.assertEqual("opt-in", redirected_activation["mode"])
        self.assertEqual("strict", redirected_activation["profile"])
        self.assertTrue((redirected / "AGENTS.md").is_symlink())

        codex_home = fixture / "profiles/codex-home"
        codex_home_env = os.environ.copy()
        codex_home_env["HOME"] = str(home)
        codex_home_env.pop("AGENTIC_CONFIG_DIR", None)
        codex_home_env["CODEX_HOME"] = str(codex_home)
        execute(
            [
                "bash",
                str(self.repo / ".codex/install.sh"),
                "--mode=opt-out",
                "--profile=default",
                "--no-identity",
            ],
            cwd=invoked,
            env=codex_home_env,
        )
        self.assertFalse((home / ".claude").exists())
        codex_home_result = execute(
            [
                sys.executable,
                str(dispatcher),
                "runtime-bindings",
                str(invoked.resolve()),
            ],
            cwd=fixture,
            env=codex_home_env,
        )
        codex_home_bindings = json.loads(codex_home_result.stdout)
        self.assertEqual(
            str(codex_home.resolve()),
            codex_home_bindings["AE_CODEX_CONFIG_DIR"],
        )
        self.assertEqual(
            str(codex_home.resolve()),
            codex_home_bindings["AE_SHARED_CONFIG_DIR"],
        )
        self.assertEqual(
            str((codex_home / "agentic-engineering.json").resolve()),
            codex_home_bindings["AE_ACTIVATION_CONFIG"],
        )
        codex_home_activation = json.loads(
            (codex_home / "agentic-engineering.json").read_text(encoding="utf-8")
        )
        self.assertEqual("opt-out", codex_home_activation["mode"])
        self.assertEqual("default", codex_home_activation["profile"])

        default_home = fixture / "default-home"
        default_home.mkdir()
        default_env = os.environ.copy()
        default_env["HOME"] = str(default_home)
        default_env.pop("AGENTIC_CONFIG_DIR", None)
        default_env.pop("CODEX_HOME", None)
        execute(
            [
                "bash",
                str(self.repo / ".codex/install.sh"),
                "--mode=opt-out",
                "--profile=default",
                "--no-identity",
            ],
            cwd=invoked,
            env=default_env,
        )
        default_result = execute(
            [
                sys.executable,
                str(dispatcher),
                "runtime-bindings",
                str(invoked.resolve()),
            ],
            cwd=fixture,
            env=default_env,
        )
        default_bindings = json.loads(default_result.stdout)
        self.assertTrue((default_home / ".claude").is_dir())
        self.assertEqual(
            str((default_home / ".codex").resolve()),
            default_bindings["AE_CODEX_CONFIG_DIR"],
        )
        self.assertEqual(
            str((default_home / ".claude").resolve()),
            default_bindings["AE_SHARED_CONFIG_DIR"],
        )
        self.assertEqual(
            str((default_home / ".claude/agentic-engineering.json").resolve()),
            default_bindings["AE_ACTIVATION_CONFIG"],
        )
        default_activation = json.loads(
            (
                default_home / ".claude/agentic-engineering.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual("opt-out", default_activation["mode"])
        self.assertEqual("default", default_activation["profile"])

        mismatch_env = redirected_env.copy()
        mismatch_env["AGENTIC_CONFIG_DIR"] = str(mismatch)
        rejected = execute(
            [
                sys.executable,
                str(dispatcher),
                "runtime-bindings",
                str(invoked.resolve()),
            ],
            cwd=fixture,
            env=mismatch_env,
            expected=2,
        )
        self.assertEqual("", rejected.stdout)
        self.assertIn("configured AGENTS.md", rejected.stderr)

        redirected_alias = fixture / "profiles/redirected-alias"
        redirected_alias.symlink_to(redirected, target_is_directory=True)
        symlink_env = redirected_env.copy()
        symlink_env["AGENTIC_CONFIG_DIR"] = str(redirected_alias)
        symlink_rejected = execute(
            [
                sys.executable,
                str(dispatcher),
                "runtime-bindings",
                str(invoked.resolve()),
            ],
            cwd=fixture,
            env=symlink_env,
            expected=2,
        )
        self.assertEqual("", symlink_rejected.stdout)
        self.assertIn("must not be a symlink", symlink_rejected.stderr)

    def test_generated_base_branch_guidance_matches_dispatcher_grammar(self) -> None:
        paths = [self.repo / ".codex/AGENTS.md"]
        paths.extend(
            self.repo / f".codex/skills/{skill}/SKILL.md"
            for skill in sorted(SKILL_NAMES)
        )
        for path in paths:
            with self.subTest(path=path.relative_to(self.repo)):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn(
                    "the first `BASE_BRANCH:` declaration",
                    text,
                )
                self.assertIn("exactly one dedicated unfenced whole-line", text)
                self.assertIn("optional Markdown list prefix", text)
                self.assertIn("optional `Declaration:` prefix", text)
                self.assertIn("Multiple matching declarations are rejected", text)

    def test_all_skill_preambles_consume_validated_runtime_bindings(self) -> None:
        for skill in sorted(SKILL_NAMES):
            with self.subTest(skill=skill):
                text = (self.repo / f".codex/skills/{skill}/SKILL.md").read_text(
                    encoding="utf-8"
                )
                preamble = text.split("**Codex spawn contract.**", 1)[0]
                self.assertIn("runtime-bindings", preamble)
                for binding in (
                    "AE_CODEX_CONFIG_DIR",
                    "AE_SHARED_CONFIG_DIR",
                    "AE_ACTIVATION_CONFIG",
                    "AE_REPO_DIR",
                    "AE_PROJECT_DIR",
                ):
                    self.assertIn(binding, preamble)
                self.assertNotIn("$HOME/.claude", preamble)

    def test_generated_stop_lifecycle_matches_actual_codex_hook(self) -> None:
        agents = (self.repo / ".codex/AGENTS.md").read_text(encoding="utf-8")
        wrap = (self.repo / ".codex/skills/wrap/SKILL.md").read_text(encoding="utf-8")
        for label, text in (("AGENTS", agents), ("wrap", wrap)):
            with self.subTest(surface=label):
                self.assertIn("~/.codex/projects/[hash]/context.md", text)
                self.assertIn("context-writer-migration", text)
                self.assertNotIn(
                    "Stop hook writes this session's "
                    "`$AE_PROJECT_DIR/.agentic/context.d/<session_id>.md`",
                    text,
                )
                self.assertNotIn(
                    "Stop hook writes `$AE_PROJECT_DIR/.agentic/context.md`",
                    text,
                )
                self.assertNotIn("recomposed on every Stop turn", text)
                self.assertNotIn("the next Stop turn", text)

        introduction = wrap[
            wrap.index("# $wrap"):wrap.index("**Relationship to `wrap-ticket`.**")
        ]
        self.assertIn("~/.codex/projects/[hash]/context.md", introduction)
        self.assertIn("context-writer-migration", introduction)
        self.assertNotIn("richer context file than the auto-hook provides", introduction)
        for residual in (
            "raw activity shard after every turn",
            "rollup already carries it",
            "It does NOT write `context.md` - that file is a derived rollup",
            "Making the shared file DERIVED",
            "lost update self-heals on the next turn",
            "rollup write be lock-free",
        ):
            self.assertNotIn(residual, wrap)
        for line in wrap.splitlines():
            if re.search(r"\bderived[- ]rollup\b", line, re.IGNORECASE):
                self.assertTrue(
                    "project-local" in line
                    or "~/.codex/projects/[hash]/context.md" in line
                    or "harnesses that implement" in line,
                    f"unqualified Codex derived-rollup claim: {line}",
                )
        hook = (self.repo / ".codex/hooks/stop-context-codex.js").read_text(
            encoding="utf-8"
        )
        self.assertIn(".codex", hook)
        self.assertIn("projects", hook)
        self.assertIn("context.md", hook)
        self.assertNotIn(".agentic/context", hook)

    def test_public_docs_describe_codex_activation_path_precedence(self) -> None:
        surfaces = (
            "README.md",
            ".codex/README.md",
            "ADAPTERS.md",
            "docs/index.html",
        )
        for relative in surfaces:
            with self.subTest(surface=relative):
                text = (self.repo / relative).read_text(encoding="utf-8")
                visible = re.sub(r"<[^>]+>", " ", text)
                visible = re.sub(r"\s+", " ", visible)
                self.assertIn("$HOME/.claude/agentic-engineering.json", visible)
                self.assertIn("AGENTIC_CONFIG_DIR", visible)
                self.assertIn("CODEX_HOME", visible)
                self.assertRegex(
                    visible,
                    re.compile(
                        r"AGENTIC_CONFIG_DIR.{0,120}CODEX_HOME.{0,120}default",
                        re.IGNORECASE,
                    ),
                )
                self.assertIn(
                    "redirected Codex config directory",
                    visible,
                )

    def test_ordinary_capitalized_task_nouns_are_not_rewritten(self) -> None:
        module_name = f"codex_skills_fixture_{id(self)}"
        spec = importlib.util.spec_from_file_location(module_name, self.repo / GENERATOR)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        self.addCleanup(sys.modules.pop, module_name, None)
        spec.loader.exec_module(module)
        fixture = module.Document(
            "fixture.md",
            "\n".join(
                (
                    'issue_type mapped from TICKET_TYPE: "Story", "Bug", or "Task".',
                    "### Task-state initialization",
                    "## Current Task / Next Steps",
                    "## Task entries (machine-readable)",
                    "Use the `Task` tool for an actual delegated call.",
                )
            ),
        )
        occurrences = module.inventory_document(fixture, self.repo)
        rendered = module.transform(fixture.text, occurrences)
        self.assertIn('"Story", "Bug", or "Task"', rendered)
        self.assertIn("### Task-state initialization", rendered)
        self.assertIn("## Current Task / Next Steps", rendered)
        self.assertIn("## Task entries (machine-readable)", rendered)
        self.assertIn("Use the `spawn_agent` tool", rendered)

    def test_generated_skills_preserve_task_nouns(self) -> None:
        ticket = (self.repo / ".codex/skills/implement-ticket/SKILL.md").read_text(encoding="utf-8")
        wrap = (self.repo / ".codex/skills/wrap/SKILL.md").read_text(encoding="utf-8")
        methodology = (
            self.repo / ".codex/skills/agentic-engineering/METHODOLOGY.md"
        ).read_text(encoding="utf-8")
        self.assertIn('task -> "Task"; omit to accept project default', ticket)
        self.assertIn("### Task-state initialization", ticket)
        self.assertIn("## Task entries (machine-readable)", ticket)
        self.assertIn("## Current Task / Next Steps", wrap)
        self.assertIn("## Task-state file", methodology)
        self.assertNotIn("spawn_agent-state", ticket + methodology)

    def test_base_branch_resolver_explicit_develop_development_and_absence(self) -> None:
        project = Path(self.temporary.name) / "base-branch-project"
        project.mkdir()
        execute(["git", "init", "-q", str(project)], cwd=Path(self.temporary.name))
        execute(["git", "config", "user.email", "test@example.com"], cwd=project)
        execute(["git", "config", "user.name", "Test"], cwd=project)
        execute(["git", "commit", "--allow-empty", "-qm", "base"], cwd=project)
        (project / "AGENTS.md").write_text("BASE_BRANCH: release/integration\n", encoding="utf-8")
        dispatcher = self.repo / "bin/agentic-codex-dispatch"
        explicit = execute(
            [sys.executable, str(dispatcher), "base-branch", str(project.resolve())],
            cwd=self.repo,
        )
        self.assertEqual("release/integration", explicit.stdout.strip())
        (project / "AGENTS.md").unlink()
        execute(["git", "branch", "develop"], cwd=project)
        fallback = execute(
            [sys.executable, str(dispatcher), "base-branch", str(project.resolve())],
            cwd=self.repo,
        )
        self.assertEqual("develop", fallback.stdout.strip())
        execute(["git", "branch", "-D", "develop"], cwd=project)
        execute(["git", "branch", "development"], cwd=project)
        secondary_fallback = execute(
            [sys.executable, str(dispatcher), "base-branch", str(project.resolve())],
            cwd=self.repo,
        )
        self.assertEqual("development", secondary_fallback.stdout.strip())
        execute(["git", "branch", "-D", "development"], cwd=project)
        absent = execute(
            [sys.executable, str(dispatcher), "base-branch", str(project.resolve())],
            cwd=self.repo,
            expected=2,
        )
        self.assertIn("no BASE_BRANCH declaration", absent.stderr)
        self.assertIn("ask whether to use main", absent.stderr)

    def test_base_branch_resolver_uses_only_dedicated_unfenced_declarations(self) -> None:
        project = Path(self.temporary.name) / "base-branch-grammar-project"
        project.mkdir()
        execute(["git", "init", "-q", str(project)], cwd=Path(self.temporary.name))
        execute(["git", "config", "user.email", "test@example.com"], cwd=project)
        execute(["git", "config", "user.name", "Test"], cwd=project)
        execute(["git", "commit", "--allow-empty", "-qm", "base"], cwd=project)
        dispatcher = self.repo / "bin/agentic-codex-dispatch"

        for label, content in (
            ("negative-line", "No BASE_BRANCH: line exists.\n"),
            ("negative-declaration", "A no BASE_BRANCH: declaration means ask.\n"),
            ("fenced", "```text\nBASE_BRANCH: fenced-example\n```\n"),
            (
                "trailing-text-does-not-close",
                "```text\n```still-fenced\nBASE_BRANCH: still-fenced\n```\n",
            ),
        ):
            with self.subTest(ignored=label):
                (project / "AGENTS.md").write_text(content, encoding="utf-8")
                result = execute(
                    [sys.executable, str(dispatcher), "base-branch", str(project.resolve())],
                    cwd=self.repo,
                    expected=2,
                )
                self.assertIn("no BASE_BRANCH declaration", result.stderr)

        for label, content, expected in (
            ("exact", "BASE_BRANCH: main\n", "main"),
            ("list", "- BASE_BRANCH: release/integration\n", "release/integration"),
            ("declaration", "Declaration: BASE_BRANCH: current\n", "current"),
            (
                "four-space-fence-is-code-not-opening-fence",
                "    ```text\nBASE_BRANCH: visible\n    ```\n",
                "visible",
            ),
        ):
            with self.subTest(accepted=label):
                (project / "AGENTS.md").write_text(content, encoding="utf-8")
                result = execute(
                    [sys.executable, str(dispatcher), "base-branch", str(project.resolve())],
                    cwd=self.repo,
                )
                self.assertEqual(expected, result.stdout.strip())

        (project / "AGENTS.md").write_text(
            "BASE_BRANCH: main\n- BASE_BRANCH: develop\n",
            encoding="utf-8",
        )
        ambiguous = execute(
            [sys.executable, str(dispatcher), "base-branch", str(project.resolve())],
            cwd=self.repo,
            expected=2,
        )
        self.assertIn("multiple BASE_BRANCH declarations", ambiguous.stderr)

    def test_dispatch_rejects_escaping_and_wrong_type_descriptors(self) -> None:
        dispatcher = self.repo / "bin/agentic-codex-dispatch"
        map_path = self.repo / ".codex/skills/agentic-engineering/RESOURCE-MAP.json"
        original = map_path.read_bytes()
        hostile = self.repo / ".codex/skills/agentic-engineering/dispatch-fifo"
        cases = (
            ("absolute", {"path": str((Path(self.temporary.name) / "outside").resolve()), "type": "file"}),
            ("traversal", {"path": "../../../../outside", "type": "file"}),
            ("directory as file", {"path": "references", "type": "file"}),
            ("file as directory", {"path": "METHODOLOGY.md", "type": "directory"}),
            ("invalid type", {"path": "METHODOLOGY.md", "type": "socket"}),
        )
        try:
            for label, descriptor in cases:
                with self.subTest(descriptor=label):
                    payload = json.loads(original)
                    payload["resources"]["hostile"] = descriptor
                    map_path.write_text(json.dumps(payload), encoding="utf-8")
                    execute(
                        [sys.executable, str(dispatcher), "path", "hostile"],
                        cwd=self.repo,
                        expected=2,
                    )
            if hasattr(os, "mkfifo"):
                os.mkfifo(hostile)
                payload = json.loads(original)
                payload["resources"]["hostile"] = {"path": "dispatch-fifo", "type": "file"}
                map_path.write_text(json.dumps(payload), encoding="utf-8")
                execute(
                    [sys.executable, str(dispatcher), "path", "hostile"],
                    cwd=self.repo,
                    expected=2,
                )
        finally:
            map_path.write_bytes(original)
            if hostile.exists():
                hostile.unlink()

    def test_absolute_output_resolves_logical_physical_alias(self) -> None:
        physical = Path(self.temporary.name) / "physical-output"
        physical.mkdir()
        logical = Path(self.temporary.name) / "logical-output"
        logical.symlink_to(physical, target_is_directory=True)
        requested = logical / "skills"
        result = run(
            self.repo,
            "build",
            "--repo",
            str(self.repo),
            "--output",
            str(requested),
        )
        self.assertIn(str((physical / "skills").resolve()), result.stdout)
        self.assertTrue((physical / "skills/agentic-engineering/SKILL.md").is_file())

    def test_default_and_explicit_symlinked_output_roots_are_rejected_without_target_mutation(
        self,
    ) -> None:
        for label, output in (
            ("default", self.repo / ".codex/skills"),
            ("explicit", Path(self.temporary.name) / "explicit-skills"),
        ):
            with self.subTest(output_root=label):
                target = Path(self.temporary.name) / f"{label}-target"
                target.mkdir()
                sentinel = target / "unrelated.txt"
                sentinel.write_text("preserve me\n", encoding="utf-8")
                before = fingerprint(target)
                if output.exists() and not output.is_symlink():
                    shutil.rmtree(output)
                output.symlink_to(target, target_is_directory=True)

                if label == "default":
                    result = run(
                        self.repo,
                        "build",
                        "--repo",
                        str(self.repo),
                        expected=1,
                    )
                else:
                    result = self.build_at_output(output, expected=1)

                self.assertIn("generated root must be a real directory", result.stderr)
                self.assertTrue(output.is_symlink())
                self.assertEqual(before, fingerprint(target))
                self.assertEqual("preserve me\n", sentinel.read_text(encoding="utf-8"))

    def test_populated_unowned_output_root_is_rejected_without_identity_or_byte_mutation(
        self,
    ) -> None:
        output = Path(self.temporary.name) / "populated-unowned"
        nested = output / "nested"
        nested.mkdir(parents=True)
        sentinel = nested / "sentinel.bin"
        sentinel.write_bytes(b"\x00unowned-output\xff")
        outside = Path(self.temporary.name) / "outside-target"
        outside.mkdir()
        outside_sentinel = outside / "preserve.txt"
        outside_sentinel.write_text("external target remains untouched\n", encoding="utf-8")
        link = nested / "external-link"
        link.symlink_to(outside, target_is_directory=True)
        before = identity_fingerprint(output)
        outside_before = identity_fingerprint(outside)

        result = self.build_at_output(output, expected=1)

        self.assertIn("unowned generated root", result.stderr)
        self.assertEqual(before, identity_fingerprint(output))
        self.assertEqual(outside_before, identity_fingerprint(outside))
        self.assertEqual(b"\x00unowned-output\xff", sentinel.read_bytes())
        self.assertEqual(
            "external target remains untouched\n",
            outside_sentinel.read_text(encoding="utf-8"),
        )

    def test_generated_root_marker_tamper_spoof_and_hardlink_fail_closed(self) -> None:
        canonical_marker = (
            self.repo / ".codex/skills" / ROOT_MARKER
        ).read_bytes()
        cases: list[tuple[str, bytes, bool]] = [
            ("tampered", canonical_marker + b"tamper\n", False),
            (
                "spoofed",
                json.dumps(
                    {
                        "adapter": "codex",
                        "magic": "DINOSTACK_CODEX_SKILL_ROOT",
                        "schema_version": 999,
                        "skills": sorted(SKILL_NAMES),
                    },
                    sort_keys=True,
                ).encode("utf-8"),
                False,
            ),
            ("hardlinked", canonical_marker, True),
        ]
        for label, marker_bytes, hardlink in cases:
            with self.subTest(marker=label):
                fixture = Path(self.temporary.name) / f"root-marker-{label}"
                output = fixture / "skills"
                output.mkdir(parents=True)
                sentinel = output / "sentinel.txt"
                sentinel.write_text("preserve\n", encoding="utf-8")
                marker_path = output / ROOT_MARKER
                if hardlink:
                    external_marker = fixture / "external-marker"
                    external_marker.write_bytes(marker_bytes)
                    os.link(external_marker, marker_path)
                else:
                    marker_path.write_bytes(marker_bytes)
                before = identity_fingerprint(output)

                result = self.build_at_output(output, expected=1)

                self.assertIn("ownership marker", result.stderr)
                self.assertEqual(before, identity_fingerprint(output))
                self.assertEqual("preserve\n", sentinel.read_text(encoding="utf-8"))

    def test_copied_canonical_marker_cannot_adopt_populated_arbitrary_root(self) -> None:
        output = Path(self.temporary.name) / "copied-canonical-marker"
        output.mkdir()
        sentinel = output / "sentinel.bin"
        sentinel.write_bytes(b"\x00copied-canonical-marker\xff")
        shutil.copy2(
            self.repo / ".codex/skills" / ROOT_MARKER,
            output / ROOT_MARKER,
        )
        before = identity_fingerprint(output)

        result = self.build_at_output(output, expected=1)

        self.assertIn("binding", result.stderr)
        self.assertEqual(before, identity_fingerprint(output))
        self.assertEqual(b"\x00copied-canonical-marker\xff", sentinel.read_bytes())

    def test_arbitrary_root_binding_registry_and_read_only_check(self) -> None:
        source = Path(self.temporary.name) / "owned-arbitrary-source"
        source.mkdir()
        self.build_at_output(source)
        registry = self.repo / ".agentic/codex-skill-root-ownership.json"
        self.assertTrue(registry.is_file())
        self.assertEqual(0o600, stat.S_IMODE(os.lstat(registry).st_mode))

        copied = Path(self.temporary.name) / "copied-arbitrary-root"
        shutil.copytree(source, copied, symlinks=True)
        copied_before = identity_fingerprint(copied)
        result = self.build_at_output(copied, expected=1)
        self.assertIn("binding", result.stderr)
        self.assertEqual(copied_before, identity_fingerprint(copied))

        output_before = identity_fingerprint(source)
        registry_before = identity_fingerprint(registry.parent)
        self.check_at_output(source)
        self.assertEqual(output_before, identity_fingerprint(source))
        self.assertEqual(registry_before, identity_fingerprint(registry.parent))

    def test_arbitrary_root_registry_absent_tampered_symlink_and_hardlink_refuse(
        self,
    ) -> None:
        output = Path(self.temporary.name) / "registry-protected-output"
        output.mkdir()
        self.build_at_output(output)
        registry = self.repo / ".agentic/codex-skill-root-ownership.json"
        original = registry.read_bytes()
        external = Path(self.temporary.name) / "registry-external"
        external.write_bytes(original)
        output_before = identity_fingerprint(output)

        for label in ("absent", "tampered", "symlink", "hardlink"):
            with self.subTest(registry=label):
                if os.path.lexists(registry):
                    registry.unlink()
                if label == "tampered":
                    registry.write_bytes(b'{"tampered":true}\n')
                    registry.chmod(0o600)
                elif label == "symlink":
                    registry.symlink_to(external)
                elif label == "hardlink":
                    os.link(external, registry)

                result = self.build_at_output(output, expected=1)

                self.assertIn("ownership registry", result.stderr)
                self.assertEqual(output_before, identity_fingerprint(output))
                if os.path.lexists(registry):
                    registry.unlink()
                registry.write_bytes(original)
                registry.chmod(0o600)

    def test_arbitrary_root_registry_requires_exact_canonical_bytes(self) -> None:
        output = Path(self.temporary.name) / "registry-canonical-output"
        output.mkdir()
        self.build_at_output(output)
        registry = self.repo / ".agentic/codex-skill-root-ownership.json"
        payload = json.loads(registry.read_text(encoding="utf-8"))
        registry.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        output_before = identity_fingerprint(output)
        registry_before = identity_fingerprint(registry.parent)

        for operation in ("check", "build"):
            with self.subTest(operation=operation):
                if operation == "check":
                    result = self.check_at_output(output, expected=1)
                else:
                    result = self.build_at_output(output, expected=1)
                self.assertIn("canonical bytes", result.stderr)
                self.assertEqual(output_before, identity_fingerprint(output))
                self.assertEqual(registry_before, identity_fingerprint(registry.parent))

    def test_empty_output_root_bootstraps_then_updates_and_prunes_deterministically(
        self,
    ) -> None:
        output = Path(self.temporary.name) / "owned-output"
        output.mkdir()
        self.build_at_output(output)
        first = fingerprint(output)
        self.assertTrue((output / ROOT_MARKER).is_file())

        stale = output / "stale.txt"
        stale.write_text("generated-root stale content\n", encoding="utf-8")
        generated = output / "brief/SKILL.md"
        generated.write_text("drift\n", encoding="utf-8")
        self.build_at_output(output)

        self.assertFalse(stale.exists())
        repaired = fingerprint(output)
        self.build_at_output(output)
        self.assertEqual(repaired, fingerprint(output))
        def logical(records: dict[str, tuple[object, ...]]) -> dict[str, tuple[object, ...]]:
            return {
                key: (value[0],) if value[0] == "directory" else value[:2]
                for key, value in records.items()
            }
        self.assertEqual(
            logical(first),
            logical(repaired),
        )

    def test_installer_rejects_config_and_skill_root_symlink_ancestry_before_mutation(
        self,
    ) -> None:
        cases = (
            ("config-final", "config-final"),
            ("config-ancestor", "config-ancestor"),
            ("skills-final", "skills-final"),
            ("skills-ancestor", "skills-ancestor"),
        )
        for label, mode in cases:
            with self.subTest(path_case=label):
                fixture = Path(self.temporary.name) / f"installer-{label}"
                home = fixture / "home"
                outside = fixture / "outside"
                home.mkdir(parents=True)
                outside.mkdir()
                outside_sentinel = outside / "sentinel.bin"
                outside_sentinel.write_bytes(b"\x00external-install-root\xff")
                arguments = [
                    "bash",
                    str(self.repo / ".codex/install.sh"),
                    "--mode=opt-out",
                    "--profile=default",
                    "--no-identity",
                ]
                if mode == "config-final":
                    (home / ".codex").symlink_to(outside, target_is_directory=True)
                elif mode == "config-ancestor":
                    (home / "profiles").symlink_to(outside, target_is_directory=True)
                    arguments.append(f"--config-dir={home / 'profiles/codex'}")
                elif mode == "skills-final":
                    (home / ".agents").mkdir()
                    (home / ".agents/skills").symlink_to(
                        outside,
                        target_is_directory=True,
                    )
                else:
                    (home / ".agents").symlink_to(outside, target_is_directory=True)
                env = os.environ.copy()
                env["HOME"] = str(home)
                env.pop("AGENTIC_CONFIG_DIR", None)
                home_before = identity_fingerprint(home)
                outside_before = identity_fingerprint(outside)

                result = execute(
                    arguments,
                    cwd=self.repo,
                    env=env,
                    expected=1,
                )

                self.assertIn("unsafe install path", result.stderr)
                self.assertEqual(home_before, identity_fingerprint(home))
                self.assertEqual(outside_before, identity_fingerprint(outside))
                self.assertEqual(b"\x00external-install-root\xff", outside_sentinel.read_bytes())

    def test_installer_preflights_every_final_mutable_destination_before_mutation(
        self,
    ) -> None:
        bin_name = next(
            path.name for path in sorted((self.repo / "bin").glob("agentic-*"))
            if path.is_file()
        )
        final_cases = [
            ("activation", ".claude/agentic-engineering.json", "symlink"),
            ("config", ".codex/config.toml", "symlink"),
            ("marker", ".codex/.agentic-eng-added-codex-hooks-flag", "symlink"),
            ("agents", ".codex/agents", "symlink"),
            ("agents-file", ".codex/AGENTS.md", "symlink"),
            ("hooks", ".codex/hooks.json", "symlink"),
            ("bin", f".local/bin/{bin_name}", "symlink"),
            ("config-hardlink", ".codex/config.toml", "hardlink"),
        ]
        final_cases.extend(
            (f"skill-{name}", f".agents/skills/{name}", "symlink")
            for name in sorted(SKILL_NAMES)
        )
        snapshot_key = (
            f"{self.repo.resolve().name}-"
            f"{hashlib.sha256(str(self.repo.resolve()).encode()).hexdigest()[:12]}"
        )
        final_cases.extend(
            (
                ("snapshot-root", f".agentic/hooks-snapshot/{snapshot_key}", "symlink"),
                (
                    "snapshot-meta",
                    f".agentic/hooks-snapshot/{snapshot_key}/.snapshot-meta.json",
                    "symlink",
                ),
            )
        )

        for label, relative, attack in final_cases:
            with self.subTest(destination=label):
                fixture = Path(self.temporary.name) / f"final-path-{label}"
                home = fixture / "home"
                outside = fixture / "outside"
                home.mkdir(parents=True)
                outside.mkdir()
                victim = outside / "victim"
                victim.write_bytes(b"\x00final-path-victim\xff")
                destination = home / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if label in {"agents", "snapshot-root"}:
                    target_dir = outside / f"{label}-dir"
                    target_dir.mkdir()
                    destination.symlink_to(target_dir, target_is_directory=True)
                elif attack == "hardlink":
                    os.link(victim, destination)
                else:
                    destination.symlink_to(victim)
                env = os.environ.copy()
                env["HOME"] = str(home)
                env.pop("AGENTIC_CONFIG_DIR", None)
                home_before = identity_fingerprint(home)
                outside_before = identity_fingerprint(outside)

                result = execute(
                    [
                        "bash",
                        str(self.repo / ".codex/install.sh"),
                        "--mode=opt-out",
                        "--profile=default",
                        "--no-identity",
                    ],
                    cwd=self.repo,
                    env=env,
                    expected=1,
                )

                self.assertIn("unsafe install destination", result.stderr)
                self.assertEqual(home_before, identity_fingerprint(home))
                self.assertEqual(outside_before, identity_fingerprint(outside))

    def test_installer_build_refusal_precedes_all_user_state_mutation(self) -> None:
        fixture = Path(self.temporary.name) / "installer-build-refusal"
        home = fixture / "home"
        temp_root = fixture / "staging"
        home.mkdir(parents=True)
        temp_root.mkdir()
        (home / ".claude").mkdir()
        activation = home / ".claude/agentic-engineering.json"
        activation.write_bytes(b'{"mode":"opt-in","profile":"strict","sentinel":"keep"}\n')
        build = self.repo / ".codex/build.sh"
        build.write_text("#!/usr/bin/env bash\nexit 73\n", encoding="utf-8")
        build.chmod(0o755)
        home_before = identity_fingerprint(home)
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["TMPDIR"] = str(temp_root)
        env.pop("AGENTIC_CONFIG_DIR", None)

        result = execute(
            [
                "bash",
                str(self.repo / ".codex/install.sh"),
                "--mode=opt-out",
                "--profile=default",
                "--no-identity",
            ],
            cwd=self.repo,
            env=env,
            expected=73,
        )

        self.assertEqual("", result.stdout)
        self.assertEqual(home_before, identity_fingerprint(home))
        self.assertEqual([], list(temp_root.iterdir()))

    def test_isolated_install_update_and_uninstall_owns_exactly_four_skills(self) -> None:
        home = Path(self.temporary.name) / "home"
        temp_root = Path(self.temporary.name) / "install-staging"
        home.mkdir()
        temp_root.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["TMPDIR"] = str(temp_root)
        env.pop("AGENTIC_CONFIG_DIR", None)
        install = [
            "bash", str(self.repo / ".codex/install.sh"),
            "--mode=opt-out", "--profile=default", "--no-identity",
        ]
        execute(install, cwd=self.repo, env=env)
        self.assertEqual([], list(temp_root.iterdir()))
        execute(install, cwd=self.repo, env=env)
        self.assertEqual([], list(temp_root.iterdir()))
        skill_home = home / ".agents/skills"
        self.assertEqual(SKILL_NAMES, {entry.name for entry in skill_home.iterdir()})
        for name in SKILL_NAMES:
            link = skill_home / name
            self.assertTrue(link.is_symlink())
            self.assertEqual(str(self.repo / ".codex/skills" / name), os.readlink(link))
            self.assertTrue((link / "SKILL.md").is_file())
        execute(["bash", str(self.repo / ".codex/uninstall.sh")], cwd=self.repo, env=env)
        self.assertEqual(set(), {entry.name for entry in skill_home.iterdir()})

    def test_ci_precommit_and_public_docs_cover_native_skill_surface(self) -> None:
        workflow = (self.repo / ".github/workflows/codex-skill-sync.yml").read_text(encoding="utf-8")
        self.assertIn("python3 scripts/test/test_codex_skills.py --clean-clone", workflow)
        self.assertIn("bash .codex/build.sh", workflow)
        self.assertIn("git diff --exit-code", workflow)
        precommit = (self.repo / "hooks/pre-commit").read_text(encoding="utf-8")
        self.assertIn('scripts/check-codex-skill-sync.sh"', precommit)
        self.assertIn('"$REPO_DIR/.codex/skills"', precommit)
        self.assertIn('"$REPO_DIR/.codex/skill-compatibility.yml"', precommit)
        self.assertIn('"$REPO_DIR/.codex/hooks/skill-auto-load-check.sh"', precommit)

        stale = re.compile(r"\.codex/skill(?:/|\*\*)")
        checked = [
            self.repo / "AGENTS.md",
            self.repo / ".codex/README.md",
            self.repo / ".codex/install.sh",
            self.repo / ".codex/uninstall.sh",
        ]
        checked.extend((self.repo / "content").rglob("*.md"))
        checked.extend((self.repo / ".codex/skills").rglob("*.md"))
        offenders = [
            str(path.relative_to(self.repo))
            for path in checked
            if stale.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual([], offenders)
        readme = (self.repo / ".codex/README.md").read_text(encoding="utf-8")
        self.assertIn("exactly four native Codex skills", readme)
        self.assertIn("~/.agents/skills/agentic-engineering", readme)
        self.assertIn("~/.agents/skills/brief", readme)
        self.assertIn("~/.agents/skills/wrap", readme)
        self.assertIn("~/.agents/skills/implement-ticket", readme)
        self.assertIn("relative resource symlinks", readme)
        self.assertIn("bash scripts/check-codex-skill-sync.sh", readme)

    def test_public_codex_guidance_describes_four_native_dollar_workflows(self) -> None:
        surfaces = (
            "ADAPTERS.md",
            "README.md",
            "docs/components.md",
            "docs/index.html",
        )
        inventory = (
            "exactly four native Codex skills: agentic-engineering, brief, wrap, "
            "and implement-ticket."
        )
        forbidden = (
            "hardlinks, no transform",
            "Commands are hardlinks from",
            "and a SKILL.md for on-demand loading",
            "must be pasted or referenced manually",
            "Reference the command files manually or paste their contents",
            "Codex CLI adapter (AGENTS.md, skill, commands, install/uninstall)",
        )

        for relative in surfaces:
            with self.subTest(surface=relative):
                content = (self.repo / relative).read_text(encoding="utf-8")
                visible = re.sub(r"<[^>]+>", " ", content).replace("`", "")
                visible = re.sub(r"\s+", " ", visible)
                visible = re.sub(r"\s+([,.;:])", r"\1", visible)
                self.assertIn(inventory, visible)
                for invocation in ("$brief", "$wrap", "$implement-ticket"):
                    self.assertIn(invocation, content)
                for stale_claim in forbidden:
                    self.assertNotIn(stale_claim.lower(), content.lower())

    def test_installed_runtime_guidance_uses_generator_workflow_contract(self) -> None:
        module_name = f"codex_skills_runtime_guidance_{id(self)}"
        spec = importlib.util.spec_from_file_location(module_name, self.repo / GENERATOR)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        self.addCleanup(sys.modules.pop, module_name, None)
        spec.loader.exec_module(module)

        compatibility = json.loads(
            (self.repo / ".codex/skill-compatibility.yml").read_text(encoding="utf-8")
        )
        native_tokens = {
            item["generated_token"]
            for item in compatibility["occurrences"]
            if item["resolution_mode"] == "native-skill"
            and item["expected_target"] in module.WORKFLOWS
        }
        self.assertEqual({"$brief", "$wrap", "$implement-ticket"}, native_tokens)
        skeptic_tokens = {
            item["generated_token"]
            for item in compatibility["occurrences"]
            if item["resolution_mode"] == "manual-command-resource"
            and item["expected_target"] == "content/commands/ds-skeptic.md"
        }
        self.assertEqual(
            {
                "manual workflow 'ds-skeptic' via "
                "`$AE_REPO_DIR/bin/agentic-codex-dispatch command ds-skeptic`"
            },
            skeptic_tokens,
        )

        self.public_build()
        home = Path(self.temporary.name) / "runtime-guidance-home"
        home.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(home)
        env.pop("AGENTIC_CONFIG_DIR", None)
        execute(
            [
                "bash",
                str(self.repo / ".codex/install.sh"),
                "--mode=opt-out",
                "--profile=default",
                "--no-identity",
            ],
            cwd=self.repo,
            env=env,
        )

        installed_agents = (home / ".codex/AGENTS.md").read_text(encoding="utf-8")
        for token in sorted(native_tokens):
            self.assertIn(token, installed_agents)
        for token in sorted(skeptic_tokens):
            self.assertIn(token, installed_agents)
        self.assertNotIn("$skeptic", installed_agents)
        self.assertNotRegex(installed_agents, r"(?<![\w./-])/ds-[a-z0-9-]+\b")

        project = Path(self.temporary.name) / "runtime-guidance-project"
        project.mkdir()
        node = shutil.which("node")
        self.assertIsNotNone(node, "node is required for the Codex Stop-hook regression")
        hook_result = subprocess.run(
            [node, str(self.repo / ".codex/hooks/stop-context-codex.js")],
            cwd=self.repo,
            env=env,
            input=json.dumps(
                {
                    "cwd": str(project),
                    "session_id": "runtime-guidance-session",
                    "last_assistant_message": "runtime guidance",
                    "model": "gpt-test",
                }
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(0, hook_result.returncode, hook_result.stderr)
        context_path = (
            home
            / ".codex/projects"
            / str(project).replace("/", "-")
            / "context.md"
        )
        emitted_context = context_path.read_text(encoding="utf-8")
        self.assertIn("$wrap", emitted_context)
        self.assertNotRegex(emitted_context, r"(?<![\w./-])/ds-[a-z0-9-]+\b")

    def test_codex_stop_hook_documentation_matches_runtime_path(self) -> None:
        hook = (
            self.repo / ".codex/hooks/stop-context-codex.js"
        ).read_text(encoding="utf-8")
        project_dir = re.search(
            r"const projectDir = path\.join\(os\.homedir\(\), "
            r"'([^']+)', '([^']+)', hash\);",
            hook,
        )
        output_name = re.search(
            r"const outputPath = path\.join\(projectDir, '([^']+)'\);",
            hook,
        )
        self.assertIsNotNone(project_dir, "production hook project path is discoverable")
        self.assertIsNotNone(output_name, "production hook context filename is discoverable")
        runtime_path = (
            f"~/{project_dir.group(1)}/{project_dir.group(2)}/[hash]/"
            f"{output_name.group(1)}"
        )

        installer = (self.repo / ".codex/install.sh").read_text(encoding="utf-8")
        installer_path = re.search(
            r"Session context saved to ([^ ]+) on Stop\.",
            installer,
        )
        self.assertIsNotNone(installer_path, "installer context path is discoverable")
        self.assertEqual(runtime_path, installer_path.group(1))

        runtime_test = (
            self.repo / "hooks/tests/test-stop-context-codex-stdin-guard.js"
        ).read_text(encoding="utf-8")
        tested_path = re.search(
            r"const contextPath = path\.join\(fakeHome, "
            r"'([^']+)', '([^']+)', hash, '([^']+)'\);",
            runtime_test,
        )
        self.assertIsNotNone(tested_path, "runtime-test context path is discoverable")
        runtime_test_path = (
            f"~/{tested_path.group(1)}/{tested_path.group(2)}/[hash]/"
            f"{tested_path.group(3)}"
        )
        self.assertEqual(runtime_path, runtime_test_path)

        readme = (self.repo / ".codex/README.md").read_text(encoding="utf-8")
        readme_path = re.search(
            r"Codex's current Stop hook writes\s+session continuity to `([^`]+)`",
            readme,
        )
        self.assertIsNotNone(readme_path, "README context path is discoverable")
        self.assertEqual(runtime_path, readme_path.group(1))
        self.assertIn("context-writer-migration", readme)
        self.assertIn("has not shipped", readme)

        docs = (self.repo / "docs/index.html").read_text(encoding="utf-8")
        docs_path = re.search(
            r"stop-context-codex\.js</code> writes continuity to "
            r"<code>([^<]+)</code>",
            docs,
        )
        self.assertIsNotNone(docs_path, "docs-site context path is discoverable")
        self.assertEqual(runtime_path, docs_path.group(1))
        self.assertIn("context-writer-migration", docs)
        self.assertIn("not part of this generator unit", docs)

        generated_surfaces = {
            ".codex/AGENTS.md": (
                self.repo / ".codex/AGENTS.md"
            ).read_text(encoding="utf-8"),
        }
        generated_surfaces.update(
            {
                path.relative_to(self.repo).as_posix(): path.read_text(encoding="utf-8")
                for path in sorted((self.repo / ".codex/skills").rglob("*.md"))
            }
        )
        false_project_local_claims = (
            re.compile(
                r"Stop hook\s+(?:auto-)?writes(?:\s+to)?\s+`?"
                r"(?:<cwd>/|\$AE_PROJECT_DIR/)?\.agentic/context\.md",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:<cwd>|\$AE_PROJECT_DIR)?/?\.agentic/context\.md"
                r"[^\n]{0,160}(?:is\s+)?(?:auto-)?written by (?:the )?Stop hook",
                re.IGNORECASE,
            ),
            re.compile(r"The Stop hook writes to the same path", re.IGNORECASE),
        )
        offenders: list[str] = []
        for relative, text in generated_surfaces.items():
            for pattern in false_project_local_claims:
                if pattern.search(text):
                    offenders.append(f"{relative}: {pattern.pattern}")
        self.assertEqual([], offenders)

        for relative in (
            ".codex/AGENTS.md",
            ".codex/skills/wrap/SKILL.md",
            ".codex/skills/implement-ticket/SKILL.md",
        ):
            with self.subTest(runtime_guidance=relative):
                text = generated_surfaces[relative]
                self.assertIn(runtime_path, text)
                self.assertIn("context-writer-migration", text)
        wrap = generated_surfaces[".codex/skills/wrap/SKILL.md"]
        self.assertIn(
            "The current Codex Stop hook writes raw continuity only to "
            f"`{runtime_path}`",
            wrap,
        )
        self.assertIn(
            "It does not write project-local "
            "`$AE_PROJECT_DIR/.agentic/context.d/<session_id>.md`",
            wrap,
        )
        self.assertIn(
            "`$wrap` continues to write the richer project-local "
            "`$AE_PROJECT_DIR/.agentic/_wrap.md` handoff",
            wrap,
        )
        self.assertNotIn("Neither writes `context.md` directly.", wrap)
        self.assertIn("$wrap", wrap)

    def test_generated_markdown_has_no_operational_bare_ds_workflow_invocations(self) -> None:
        markdown = [self.repo / ".codex/AGENTS.md"]
        markdown.extend(sorted((self.repo / ".codex/skills").rglob("*.md")))
        pattern = re.compile(r"(?<![\w./-])/ds-[a-z0-9-]+\b")
        offenders: list[str] = []
        for path in markdown:
            text = path.read_text(encoding="utf-8")
            for match in pattern.finditer(text):
                if (
                    path.is_symlink()
                    and path.relative_to(self.repo).as_posix()
                    == (
                        ".codex/skills/agentic-engineering/templates/.agentic/"
                        "skill-candidates.md"
                    )
                ):
                    continue
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(
                    f"{path.relative_to(self.repo).as_posix()}:{line}:{match.group(0)}"
                )
        self.assertEqual([], offenders)

    def test_generated_operational_spawn_guidance_uses_only_codex_supported_fields(
        self,
    ) -> None:
        markdown = [self.repo / ".codex/AGENTS.md"]
        markdown.extend(
            path
            for path in sorted((self.repo / ".codex/skills").rglob("*.md"))
            if not path.is_symlink()
        )
        forbidden = (
            re.compile(r"`?isolation\s*:\s*[\"']?worktree", re.IGNORECASE),
            re.compile(r"\brun_in_background\b"),
            re.compile(r"\bsubagent_type\b"),
            re.compile(r"\bAgent tool call\b", re.IGNORECASE),
            re.compile(r"\bmodel\s+param(?:eter)?\b", re.IGNORECASE),
            re.compile(r"`model\s*:\s*[^`]+`", re.IGNORECASE),
            re.compile(
                r"\bAgent\b[^\n]{0,120}\bcreates?[^\n]{0,80}\bworktree",
                re.IGNORECASE,
            ),
        )
        offenders: list[str] = []
        for path in markdown:
            text = path.read_text(encoding="utf-8")
            for pattern in forbidden:
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    offenders.append(
                        f"{path.relative_to(self.repo).as_posix()}:{line}:{match.group(0)}"
                    )
        self.assertEqual([], offenders)
        preamble = (
            self.repo / ".codex/skills/agentic-engineering/SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "supported inputs (`task_name`, `message`, and `fork_turns`)",
            preamble,
        )

    def test_codex_stop_hook_manifest_describes_direct_non_atomic_write(self) -> None:
        leading = "\n".join(
            (self.repo / ".codex/hooks/stop-context-codex.js")
            .read_text(encoding="utf-8")
            .splitlines()[:35]
        )
        self.assertIn("one bounded direct non-atomic local file write", leading)
        self.assertIn(
            "interruption can leave context.md truncated or torn",
            leading,
        )

    def test_codex_session_id_has_bounded_timeout_aware_stdin_contract(self) -> None:
        command = [sys.executable, str(self.repo / "bin/agentic-codex-session-id")]
        cap = 1024 * 1024

        ordinary = subprocess.run(
            command,
            input=b'{"session_id":"ordinary"}',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(0, ordinary.returncode)
        self.assertEqual(b"ordinary\n", ordinary.stdout)
        self.assertEqual(b"", ordinary.stderr)

        prefix = b'{"session_id":"at-limit"}'
        exact = prefix + (b" " * (cap - len(prefix)))
        at_limit = subprocess.run(
            command,
            input=exact,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(0, at_limit.returncode)
        self.assertEqual(b"at-limit\n", at_limit.stdout)
        self.assertEqual(b"", at_limit.stderr)

        over_limit = subprocess.run(
            command,
            input=exact + b" ",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(2, over_limit.returncode)
        self.assertEqual(b"", over_limit.stdout)
        self.assertIn(b"exceeds 1048576 bytes", over_limit.stderr)

        for label, raw, expected_code, expected_stdout in (
            ("regular-ordinary", b'{"session_id":"regular"}', 0, b"regular\n"),
            ("regular-exact", exact, 0, b"at-limit\n"),
            ("regular-over", exact + b" ", 2, b""),
        ):
            with self.subTest(regular_file=label):
                with tempfile.NamedTemporaryFile() as source:
                    source.write(raw)
                    source.flush()
                    source.seek(0)
                    result = subprocess.run(
                        command,
                        stdin=source,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                self.assertEqual(expected_code, result.returncode)
                self.assertEqual(expected_stdout, result.stdout)
                if expected_code == 0:
                    self.assertEqual(b"", result.stderr)
                else:
                    self.assertIn(b"exceeds 1048576 bytes", result.stderr)

        for label, raw in (
            ("eof", b""),
            ("malformed", b'{"session_id":'),
            ("non-object", b"[]"),
        ):
            with self.subTest(input=label):
                result = subprocess.run(
                    command,
                    input=raw,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(2, result.returncode)
                self.assertEqual(b"", result.stdout)

        stalled = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIsNotNone(stalled.stdin)
        started = time.monotonic()
        stalled.stdin.write(b'{"session_id":"stalled"')
        stalled.stdin.flush()
        self.assertEqual(2, stalled.wait(timeout=3))
        elapsed = time.monotonic() - started
        stalled.stdin.close()
        self.assertLess(elapsed, 2.5)
        self.assertEqual(b"", stalled.stdout.read())
        self.assertIn(b"stdin stalled", stalled.stderr.read())
        stalled.stdout.close()
        stalled.stderr.close()

        manifest = "\n".join(
            (self.repo / "bin/agentic-codex-session-id")
            .read_text(encoding="utf-8")
            .splitlines()[:35]
        )
        self.assertIn("1 MiB", manifest)
        self.assertIn("timeout", manifest)
        self.assertNotIn("Performance: constant time", manifest)

    def test_codex_session_id_selector_setup_failure_is_input_error(self) -> None:
        module_name = f"codex_session_id_{id(self)}"
        path = self.repo / "bin/agentic-codex-session-id"
        loader = importlib.machinery.SourceFileLoader(module_name, str(path))
        spec = importlib.util.spec_from_loader(module_name, loader)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        self.addCleanup(sys.modules.pop, module_name, None)
        loader.exec_module(module)

        read_descriptor, write_descriptor = os.pipe()
        self.addCleanup(os.close, read_descriptor)
        self.addCleanup(os.close, write_descriptor)
        stdin = mock.Mock()
        stdin.isatty.return_value = False
        stdin.buffer.fileno.return_value = read_descriptor
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(module.sys, "stdin", stdin),
            mock.patch.object(module.sys, "argv", [str(path)]),
            mock.patch.object(
                module.selectors,
                "DefaultSelector",
                side_effect=OSError("selector unavailable"),
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = module.main()

        self.assertEqual(2, result)
        self.assertEqual("", stdout.getvalue())
        self.assertIn("cannot monitor stdin: selector unavailable", stderr.getvalue())

    def test_codex_dispatch_runtime_annotations_resolve(self) -> None:
        path = self.repo / "bin/agentic-codex-dispatch"
        prefix = path.read_text(encoding="utf-8").split("\ndef repo_root", 1)[0]
        namespace: dict[str, object] = {}
        exec(compile(prefix, str(path), "exec"), namespace)
        fail = namespace["fail"]
        self.assertIs(typing.NoReturn, typing.get_type_hints(fail)["return"])

    def test_generator_manifest_discloses_arbitrary_root_registry_side_effect(self) -> None:
        leading = "\n".join(
            (self.repo / GENERATOR).read_text(encoding="utf-8").splitlines()[:35]
        )
        self.assertIn(".agentic/codex-skill-root-ownership.json", leading)
        self.assertIn("arbitrary-output build", leading)
        self.assertIn("creates or atomically replaces", leading)

    def test_project_scaffolding_seed_resources_are_closed_and_exact_symlinks(self) -> None:
        module_name = f"codex_skills_resources_{id(self)}"
        spec = importlib.util.spec_from_file_location(module_name, self.repo / GENERATOR)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        self.addCleanup(sys.modules.pop, module_name, None)
        spec.loader.exec_module(module)

        resource_map = module.resource_map("agentic-engineering", "inventory-hash")
        resources = resource_map["resources"]
        manifest_descriptor = resources["project-scaffolding.yml"]
        skill_root = self.repo / ".codex/skills/agentic-engineering"
        manifest = skill_root / manifest_descriptor["path"]
        self.assertTrue(manifest.is_file())
        seeds = re.findall(
            r'^\s*seed:\s*"([^"]+)"\s*$',
            manifest.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
        self.assertTrue(seeds)
        for seed in seeds:
            with self.subTest(seed=seed):
                self.assertIn(seed, resources)
                descriptor = resources[seed]
                mapped = skill_root / descriptor["path"]
                self.assertTrue(mapped.is_symlink())
                source = self.repo / "content" / seed
                expected_target = os.path.relpath(source, mapped.parent)
                self.assertEqual(expected_target, os.readlink(mapped))
                self.assertEqual(source.resolve(), mapped.resolve(strict=True))

    def test_codex_adapter_describes_exact_relative_symlink_mirrors(self) -> None:
        build = (self.repo / ".codex/build.sh").read_text(encoding="utf-8")
        install = (self.repo / ".codex/install.sh").read_text(encoding="utf-8")
        generated_agents = (self.repo / ".codex/AGENTS.md").read_text(encoding="utf-8")

        reference_claim = (
            ".codex/references/` (tracked relative symlinks to "
            "`../../content/references/*.md`)"
        )
        with self.subTest(surface="reference mirrors"):
            self.assertNotIn(".codex/references/` (local copies)", build)
            self.assertNotIn(".codex/references/` (local copies)", generated_agents)
            self.assertEqual(2, build.count(reference_claim))
            self.assertEqual(2, generated_agents.count(reference_claim))

        command_claim = (
            ".codex/commands/       - Source command templates "
            "(tracked relative symlinks to ../../content/commands/*.md)"
        )
        installer_reference_claim = (
            ".codex/references/     - Reference docs "
            "(tracked relative symlinks to ../../content/references/*.md)"
        )
        with self.subTest(surface="installer command mirrors"):
            self.assertNotIn(
                "Source command templates (hardlinks from content/commands/)",
                install,
            )
            self.assertNotIn("Local copies of reference docs", install)
            self.assertIn(command_claim, install)
            self.assertIn(installer_reference_claim, install)

        hook_claim = (
            "Create a tracked relative symlink at"
            "\n# .codex/hooks/skill-auto-load-check.sh targeting"
            "\n# ../../hooks/skill-auto-load-check.sh"
        )
        with self.subTest(surface="shared hook mirror"):
            self.assertNotIn(
                "hardlink it into .codex/hooks/",
                build,
            )
            self.assertIn(hook_claim, build)

    def test_touched_nontrivial_modules_have_current_leading_manifests(self) -> None:
        required_fields = (
            "Purpose:",
            "Public API:",
            "Upstream deps:",
            "Downstream consumers:",
            "Failure modes:",
            "Performance:",
        )
        for relative in (
            "scripts/test/test_codex_skills.py",
            ".codex/build.sh",
            ".codex/hooks/stop-context-codex.js",
            "hooks/pre-commit",
        ):
            with self.subTest(module=relative):
                leading = "\n".join(
                    (self.repo / relative).read_text(encoding="utf-8").splitlines()[:35]
                )
                for field in required_fields:
                    self.assertIn(field, leading)

        methodology_manifest = "\n".join(
            (self.repo / "scripts/build-methodology.sh")
            .read_text(encoding="utf-8")
            .splitlines()[:35]
        )
        self.assertIn("find", methodology_manifest)
        self.assertIn(".codex/build.sh", methodology_manifest)
        self.assertNotIn("future .codex/build.sh", methodology_manifest)
        self.assertNotIn("sort+ls", methodology_manifest)

    def test_manual_workflow_references_have_balanced_inline_code(self) -> None:
        generated = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((self.repo / ".codex/skills").rglob("*.md"))
        )
        self.assertNotRegex(generated, r"manual workflow '[^']+'.*?``")
        self.assertIn(
            "added by manual workflow 'ds-init-project' via "
            "`$AE_REPO_DIR/bin/agentic-codex-dispatch command ds-init-project`) "
            "for architectural decisions",
            generated,
        )

    def test_vision_alignment_workflow_executes_canonical_codex_paths(self) -> None:
        workflow = (
            self.repo / ".github/workflows/vision-alignment-check.yml"
        ).read_text(encoding="utf-8")
        match = re.search(
            r'case "\$f" in\s*\n\s*([^\n]+)\)\s*\n\s*TRIGGERED=true',
            workflow,
        )
        self.assertIsNotNone(match, "vision workflow case pattern is discoverable")
        pattern = match.group(1).strip() if match else ""
        matcher = f'case "$1" in {pattern}) exit 0 ;; *) exit 1 ;; esac'

        triggered = (
            "content/sections/02-delegation.md",
            "hooks/pre-commit",
            ".codex/hooks/stop-context-codex.js",
            ".codex/skill-frontmatter/brief.yml",
            ".codex/skill-compatibility.yml",
            ".codex/skills/brief/SKILL.md",
            "scripts/codex-skills.py",
            ".codex/config/hooks.json",
            ".gemini/hooks/stop-context-gemini.js",
            ".kimi/hooks/session-start.sh",
            ".claude/build.sh",
            ".codex/build.sh",
            ".cursor/build.sh",
            "bin/agentic-codex-dispatch",
            ".codex/install.sh",
            "scripts/install-profiles.sh",
            "docs/overview/vision.md",
            "docs/overview/requirements.md",
        )
        not_triggered = (
            ".codex/skill/SKILL.md",
            ".codex/skill-frontmatter-old/brief.yml",
            ".codex/skills-old/brief/SKILL.md",
            "scripts/codex-skills.py.bak",
            "docs/codex-permissions.md",
            "README.md",
        )
        for path in triggered:
            with self.subTest(triggered=path):
                result = subprocess.run(
                    ["bash", "-c", matcher, "vision-trigger", path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
        for path in not_triggered:
            with self.subTest(not_triggered=path):
                result = subprocess.run(
                    ["bash", "-c", matcher, "vision-trigger", path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                self.assertEqual(1, result.returncode, result.stderr)

    def test_precommit_behavior_uses_staged_codex_skill_paths(self) -> None:
        precommit_source = (self.repo / "hooks/pre-commit").read_text(encoding="utf-8")
        match = re.search(
            r'case "\$staged_path" in\s*\n(.*?)\)\s*\n'
            r'\s*CODEX_SKILL_SYNC_REQUIRED=true',
            precommit_source,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "pre-commit Codex path matcher is discoverable")
        pattern = re.sub(r"\\\s*\n\s*", "", match.group(1)).strip() if match else ""
        matcher = f'case "$1" in {pattern}) exit 0 ;; *) exit 1 ;; esac'
        relevant_paths = (
            "content/SKILL.md",
            "content/sections/02-delegation.md",
            "content/commands/ds-brief.md",
            "scripts/build-methodology.sh",
            "scripts/codex-skills.py",
            "scripts/check-codex-skill-sync.sh",
            "scripts/test/test_codex_skills.py",
            ".codex/build.sh",
            ".codex/skill-frontmatter/brief.yml",
            ".codex/skill-compatibility.yml",
            ".codex/skills/brief/SKILL.md",
            ".codex/commands/ds-brief.md",
            ".codex/references/skeptic-protocol.md",
            ".codex/hooks/skill-auto-load-check.sh",
            "hooks/skill-auto-load-check.sh",
            "hooks/pre-commit",
            ".github/workflows/codex-skill-sync.yml",
            ".github/workflows/vision-alignment-check.yml",
        )
        for path in relevant_paths:
            with self.subTest(relevant_path=path):
                result = subprocess.run(
                    ["bash", "-c", matcher, "precommit-trigger", path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
        for path in ("README.md", ".codex/README.md", "docs/codex-permissions.md"):
            with self.subTest(unrelated_path=path):
                result = subprocess.run(
                    ["bash", "-c", matcher, "precommit-trigger", path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                self.assertEqual(1, result.returncode, result.stderr)

        execute(["git", "init", "-q"], cwd=self.repo)
        execute(["git", "config", "user.email", "test@example.com"], cwd=self.repo)
        execute(["git", "config", "user.name", "Test"], cwd=self.repo)
        execute(["git", "add", "-A"], cwd=self.repo)
        execute(["git", "commit", "-qm", "fixture"], cwd=self.repo)
        precommit = ["bash", str(self.repo / "hooks/pre-commit")]

        generated = self.repo / ".codex/skills/brief/SKILL.md"
        original_generated = generated.read_bytes()
        generated.write_text(
            generated.read_text(encoding="utf-8") + "\nstaged corruption\n",
            encoding="utf-8",
        )
        execute(["git", "add", str(generated.relative_to(self.repo))], cwd=self.repo)
        generated.write_bytes(original_generated)
        corruption = execute(precommit, cwd=self.repo, expected=1)
        self.assertIn("Checking staged Codex native skill sync", corruption.stdout)
        self.assertIn("generated skill drift", corruption.stderr)

        execute(["git", "reset", "--hard", "HEAD"], cwd=self.repo)
        generator = self.repo / "scripts/codex-skills.py"
        generator.write_text(
            generator.read_text(encoding="utf-8") + "\n# staged generator regression\n",
            encoding="utf-8",
        )
        execute(["git", "add", str(generator.relative_to(self.repo))], cwd=self.repo)
        generator_result = execute(precommit, cwd=self.repo)
        self.assertIn("Checking staged Codex native skill sync", generator_result.stdout)
        self.assertIn("Codex skill check: OK (4 skills)", generator_result.stdout)

        execute(["git", "reset", "--hard", "HEAD"], cwd=self.repo)
        canonical = self.repo / "content/commands/ds-brief.md"
        canonical.unlink()
        execute(["git", "add", "-u", str(canonical.relative_to(self.repo))], cwd=self.repo)
        canonical_deletion = execute(precommit, cwd=self.repo, expected=1)
        self.assertIn("Checking staged Codex native skill sync", canonical_deletion.stdout)

        execute(["git", "reset", "--hard", "HEAD"], cwd=self.repo)
        generated.unlink()
        execute(["git", "add", "-u", str(generated.relative_to(self.repo))], cwd=self.repo)
        generated_deletion = execute(precommit, cwd=self.repo, expected=1)
        self.assertIn("Checking staged Codex native skill sync", generated_deletion.stdout)
        self.assertIn("generated skill drift", generated_deletion.stderr)
        self.assertIn("brief/SKILL.md", generated_deletion.stderr)

        execute(["git", "reset", "--hard", "HEAD"], cwd=self.repo)
        unrelated = self.repo / "README.md"
        unrelated.write_text(
            unrelated.read_text(encoding="utf-8") + "\nunrelated staged path\n",
            encoding="utf-8",
        )
        execute(["git", "add", str(unrelated.relative_to(self.repo))], cwd=self.repo)
        unrelated_result = execute(precommit, cwd=self.repo)
        self.assertNotIn("Checking staged Codex native skill sync", unrelated_result.stdout)

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
        execute(["bash", str(clone / ".codex/build.sh")], cwd=clone)
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
