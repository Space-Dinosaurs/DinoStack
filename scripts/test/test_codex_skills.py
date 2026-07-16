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
import hashlib
import importlib.util
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

    def public_build(self) -> subprocess.CompletedProcess[str]:
        return execute(["bash", str(self.repo / ".codex/build.sh")], cwd=self.repo)

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
            ".codex/commands/brief.md",
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

    def test_isolated_install_update_and_uninstall_owns_exactly_four_skills(self) -> None:
        home = Path(self.temporary.name) / "home"
        home.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(home)
        env.pop("AGENTIC_CONFIG_DIR", None)
        install = [
            "bash", str(self.repo / ".codex/install.sh"),
            "--mode=opt-out", "--profile=default", "--no-identity",
        ]
        execute(install, cwd=self.repo, env=env)
        execute(install, cwd=self.repo, env=env)
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
            "added by manual workflow 'init-project' via "
            "`$AE_REPO_DIR/bin/agentic-codex-dispatch command init-project`) "
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
            "content/commands/brief.md",
            "scripts/build-methodology.sh",
            "scripts/codex-skills.py",
            "scripts/check-codex-skill-sync.sh",
            "scripts/test/test_codex_skills.py",
            ".codex/build.sh",
            ".codex/skill-frontmatter/brief.yml",
            ".codex/skill-compatibility.yml",
            ".codex/skills/brief/SKILL.md",
            ".codex/commands/brief.md",
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
        canonical = self.repo / "content/commands/brief.md"
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
