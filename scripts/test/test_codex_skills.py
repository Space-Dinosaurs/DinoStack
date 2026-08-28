#!/usr/bin/env python3
"""
Purpose: Exercise deterministic Codex native-skill and prompt-wrapper generation,
         validation, recovery, and lifecycle behavior.

Public API: ``python3 scripts/test/test_codex_skills.py [--clean-clone]``.

Upstream deps: scripts/codex-skills.py, .codex/lib/prompt-wrappers.py, Codex
               adapter build sources, Git, and canonical/generated trees copied
               into isolated fixtures.

Downstream consumers: Codex skill-sync CI, pre-commit regression coverage, and release verification.

Failure modes: exits non-zero on generation drift, unsafe path handling,
               transaction recovery failure, ownership violations, hook trigger
               gaps, or compatibility regressions.

Performance: integration-heavy; copies the repository per test and optionally clones it.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
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
import threading
import time
import typing
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
GENERATOR = Path("scripts/codex-skills.py")
PROMPT_GENERATOR = Path(".codex/lib/prompt-wrappers.py")
SKILL_NAMES = {"dinostack", "brief", "wrap", "implement-ticket"}
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


def run_prompts(
    repo: Path,
    command: str,
    *,
    expected: int = 0,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    output: Path | None = None,
    state: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    arguments = [
        sys.executable,
        str(repo / PROMPT_GENERATOR),
        command,
        "--repo",
        str(repo),
    ]
    if output is not None or state is not None:
        if output is not None:
            arguments.extend(["--output", str(output)])
        if state is not None:
            arguments.extend(["--state-dir", str(state)])
    return execute(arguments, cwd=cwd or repo, expected=expected, env=env)


def load_prompt_generator(repo: Path) -> typing.Any:
    module_name = f"prompt_wrappers_{hashlib.sha256(str(repo).encode()).hexdigest()}"
    spec = importlib.util.spec_from_file_location(module_name, repo / PROMPT_GENERATOR)
    if spec is None or spec.loader is None:
        raise AssertionError("failed to load prompt-wrapper generator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


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
            ("core resource link", ".codex/skills/dinostack/rules", "link"),
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

    def test_unmatched_paragraph_rule_anchor_fails_loudly(self) -> None:
        """Regression for the round-7 CRITICAL: a PARAGRAPH_RULES anchor in
        scripts/codex-skills.py that stops matching its canonical prose target
        (because the target was reworded) must fail the build loudly instead of
        silently reverting the Codex-specific override to unqualified canonical
        text. Mutates the canonical opener the "Writer scope" rule anchors on -
        the exact class of drift that caused the round-7 CRITICAL - and asserts
        both `check` and `inventory` fail with a message naming the unmatched
        rule."""
        target = self.repo / "content/sections/09-events-log.md"
        text = target.read_text(encoding="utf-8")
        # Derive the anchor from PARAGRAPH_RULES itself (rather than a fourth
        # hand-typed copy of the writer count) so this test can never drift
        # from the generator's own anchor the way it did across two prior
        # writer-count bumps. The first rule's pattern is a fully-escaped
        # regex literal up to its trailing ".*?(?=\n\n)" wildcard suffix;
        # unescape it back to the literal prose it targets.
        module_name = f"codex_skills_fixture_{id(self)}"
        spec = importlib.util.spec_from_file_location(module_name, self.repo / GENERATOR)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        self.addCleanup(sys.modules.pop, module_name, None)
        spec.loader.exec_module(module)
        raw_pattern = module.PARAGRAPH_RULES[0][0]
        literal_pattern = raw_pattern.removesuffix(r".*?(?=\n\n)")
        anchor = re.sub(r"\\(.)", r"\1", literal_pattern)
        self.assertIn(anchor, text, "fixture repo's canonical opener must match the live anchor")
        target.write_text(text.replace(anchor, "**Writer scope: something else entirely**"), encoding="utf-8")

        result = self.check(expected=1)
        self.assertIn("PARAGRAPH_RULES", result.stderr)
        self.assertIn("matched ZERO times", result.stderr)

        inventory = run(self.repo, "inventory", "--repo", str(self.repo), expected=1)
        self.assertIn("PARAGRAPH_RULES", inventory.stderr)

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
        stale_directory = self.repo / ".codex/skills/dinostack/stale"
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
        core = (self.repo / ".codex/skills/dinostack/SKILL.md").read_text(encoding="utf-8")
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
        self.assertIn('ds-codex-dispatch base-branch "$AE_PROJECT_DIR"', generated)
        self.assertIn("then local", generated)
        self.assertIn("`develop`, then local", generated)
        self.assertIn("`development`", generated)
        self.assertIn("Work only in the pre-created worktree", generated)
        self.assertIn("$AE_REPO_DIR/bin/ds-codex-dispatch agent <role>", generated)
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

    def test_referenced_content_reachable_from_codex_skills_has_no_new_unguarded_spawn_literal(self) -> None:
        """Regression guard for the Unit 5 (DS-143 split) codex-spawn-contract
        regression: scripts/codex-skills.py's ``documents()`` only transforms
        content/commands/*.md, content/SKILL.md, and assembled METHODOLOGY.md -
        it never sees content/references/**, even though every Codex skill's
        ``resources/references`` entry is a symlink straight into that
        directory (verbatim, untransformed). A raw `isolation: "worktree"` /
        `run_in_background` literal that lands in a content/references/**
        file a Codex skill can reach is therefore inexecutable on Codex and
        invisible to test_generated_spawn_contract_is_executable_codex_semantics
        above, because ``Path.rglob`` does not descend into symlinked
        directories - it only ever sees the skills' own non-symlinked *.md.

        This test walks the same `.codex/skills` tree WITH symlinks followed
        (`os.walk(..., followlinks=True)`), so it does reach content/references/**.
        A small, explicit allowlist of files already known to carry raw
        Claude-only spawn/session literals as inert reference-doc prose
        (pre-existing accepted state) is exempt. Any OTHER reachable file
        containing the pattern fails the build - which is exactly what would
        have caught the Unit 5 regression (a NEW reference file introducing
        an unguarded, unlisted spawn/session literal with no kernel-side
        executable counterpart). Unit 5 itself was abandoned as an
        extraction (content/references/qa-loop-state.md does not exist on
        this branch), so that allowlist entry is deliberately NOT present
        here.
        """
        allowlisted_reference_files = {
            "delegation-detail.md",
            "qa-gate.md",
            "agent-team.md",
            "subagent-protocol.md",
            # DS-return-contract Unit 3 (dc5233e4): both files gained the
            # identical descriptive clause "since this agent always runs
            # isolation: \"worktree\"" explaining WHY qa-engineer's report
            # writes go to /tmp instead of .agentic/ - a fact citation about
            # existing qa-engineer behavior, not an executable instruction
            # telling an agent how to construct a spawn call. Inert
            # reference-doc prose; no kernel-side executable counterpart to
            # restore it to.
            "subagent-return-contract.md",
            "conductor-operating-rules.md",
        }
        pattern = re.compile(r"\bisolation\s*:|run_in_background")
        offenders: list[str] = []
        skills_root = self.repo / ".codex/skills"
        repo_real = self.repo.resolve()
        references_real = (self.repo / "content/references").resolve()
        seen_real_paths: set[Path] = set()
        for dirpath, _dirnames, filenames in os.walk(skills_root, followlinks=True):
            for filename in filenames:
                if not filename.endswith(".md"):
                    continue
                candidate = Path(dirpath) / filename
                real = candidate.resolve()
                if real in seen_real_paths:
                    continue
                seen_real_paths.add(real)
                # Only content/references/** is in scope: it is the one canonical
                # source tree that is reachable from every Codex skill's resources
                # symlink AND is never a documents() transform input (unlike
                # content/sections/**, which feeds assembled_methodology(), or
                # content/commands/**, which is a direct WORKFLOWS document).
                if references_real not in real.parents:
                    continue
                if real.name in allowlisted_reference_files:
                    continue
                text = real.read_text(encoding="utf-8")
                if pattern.search(text):
                    offenders.append(str(real.relative_to(repo_real)))
        self.assertFalse(
            offenders,
            "found unguarded isolation:/run_in_background literal(s) reachable from a "
            "Codex skill's resources tree, outside the accepted allowlist: "
            f"{sorted(offenders)} - either restore the executable spawn-contract "
            "paragraph to the owning content/commands/*.md kernel file (so "
            "scripts/codex-skills.py's documents() can transform it) with an adjacent "
            "pointer from the reference file, or add the file to "
            "allowlisted_reference_files with a stated reason if it is genuinely inert "
            "reference-doc prose citing the kernel paragraph.",
        )

    def test_unit1_unit6_codex_restorations_pinned_in_kernel(self) -> None:
        """Regression guard for the two live Codex-transform regressions
        salvaged from the abandoned PR #624 (DS-143 Unit 5 QA-loop-state
        extraction). Unit 5 itself is NOT ported (no content/references/
        qa-loop-state.md on this branch) - Phase 6b and Phase 8.5 stay
        inline in the kernel, unmoved. What this test pins is the two
        genuine repairs that DID land:

        - Unit 1 (#620, merged) had dropped 10 codexified occurrences from
          `content/commands/ds-implement-ticket.md`'s Tracker Writeback
          Helper section. 9 of the 10 are restored as a "Caller
          enumeration" bullet list (the 10th was a legitimate relocation to
          content/references/tracker-writeback.md's own citation of
          ds-wrap.md and stays where it is).
        - Unit 6 (#621, merged) had dropped 4 occurrences from Phase 12a.
          All 4 are restored as the "Resume banners" and "Interrupt vs.
          pause path note" paragraphs.

        A future tidy-up that silently deletes either restoration would
        reintroduce the exact codex-skill-compatibility gap Unit 1/6
        shipped, invisibly - scripts/codex-skills.py's `documents()`
        transform only sees these tokens while they live in the kernel
        command file, not in the symlinked content/references/** tree they
        point back to.

        Confirmed red pre-fix (mutation test performed manually, not part
        of the automated suite): deleting the "Caller enumeration" bullet
        list, or deleting the "Resume banners"/"Interrupt vs. pause path
        note" paragraphs, from content/commands/ds-implement-ticket.md each
        independently turns this test red.
        """
        kernel_path = self.repo / "content/commands/ds-implement-ticket.md"
        kernel = kernel_path.read_text(encoding="utf-8")

        # --- Unit 1: Tracker Writeback Helper "Caller enumeration" ---
        twh_start = kernel.index("## Tracker Writeback Helper")
        twh_end = kernel.index("## Tracker Create Helper", twh_start)
        twh = kernel[twh_start:twh_end]
        self.assertIn("**Caller enumeration", twh)
        self.assertEqual(twh.count("/ds-wrap"), 5, (
            "expected 5 '/ds-wrap' occurrences in the Tracker Writeback Helper "
            "section (1 pre-existing in the intro paragraph + 4 restored by "
            "the Caller enumeration block) - got a different count, which "
            "means the restoration was partially or fully reverted"
        ))
        self.assertEqual(twh.count("`/ds-ticket-status-sync`"), 5, (
            "expected 5 '`/ds-ticket-status-sync`' occurrences in the Tracker "
            "Writeback Helper section (1 pre-existing + 4 restored) - got a "
            "different count"
        ))
        self.assertIn(".agentic/tracker-states.json", twh)

        # --- Unit 6: Phase 12a "Resume banners" / "Interrupt vs. pause path note" ---
        phase12a_start = kernel.index(
            "## Phase 12a: Handoff evaluation (batch, open-goal, and single-ticket-capped)"
        )
        phase12a_end = kernel.index("## Phase 12b: Operator Runbook", phase12a_start)
        phase12a = kernel[phase12a_start:phase12a_end]
        self.assertIn("**Resume banners", phase12a)
        self.assertIn("Resume: /ds-implement-ticket from this directory", phase12a)
        self.assertIn(
            "Resume: /ds-implement-ticket ... goal_mode=open_goal ...", phase12a
        )
        self.assertIn("**Interrupt vs. pause path note", phase12a)
        self.assertIn("hooks/session-end-wrap.js", phase12a)
        self.assertIn(".agentic/loop-state-", phase12a)

        # The generated Codex skill must carry the transformed (native
        # /ds-implement-ticket and ds-codex-dispatch-aware) forms of these
        # tokens - not merely leave them absent because the kernel
        # restoration itself never landed in the built artifact.
        generated_ticket = (
            self.repo / ".codex/skills/implement-ticket/SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Caller enumeration", generated_ticket)
        self.assertIn("Resume banners", generated_ticket)
        self.assertIn("$AE_PROJECT_DIR/.agentic/tracker-states.json", generated_ticket)
        self.assertIn("$AE_PROJECT_DIR/.agentic/loop-state-", generated_ticket)

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
        self.assertIn("ds-codex-session-id", directive_text)
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
            self.assertIn("ds-codex-dispatch", preamble)
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

    def test_degrade_path_companion_survives_git_clean_and_round_trips(self) -> None:
        # DS-183 round 5 (M1/M2 fix). The degrade-path companion previously
        # lived inside this checkout at .codex/AGENTS.degraded.md, gitignored
        # - deleted by a routine `git clean -xfd` or absent in a fresh
        # worktree, leaving the installed AGENTS.md symlink dangling with
        # nothing behind it. This test forces the degrade path (a real,
        # non-symlink directory pre-placed at the dinostack skill's load
        # path, exactly as the reviewer reproduced it), then simulates a
        # `git clean` of the checkout and asserts the companion is untouched
        # because it never lived there. It also covers the two behaviours a
        # Critical (C1) and a Major (M1) were filed against: install writes
        # the companion and symlinks AGENTS_DST at it, and
        # runtime_bindings() accepts that target; plus uninstall removing
        # the companion and auto-heal switching back when the skill link
        # becomes healthy again.
        dispatcher = self.repo / "bin/agentic-codex-dispatch"
        fixture = Path(self.temporary.name) / "degrade-path"
        home = fixture / "home"
        invoked = fixture / "invoked-project"
        home.mkdir(parents=True)
        invoked.mkdir()
        execute(["git", "init", "-q", str(invoked)], cwd=fixture)

        env = os.environ.copy()
        env["HOME"] = str(home)
        env.pop("AGENTIC_CONFIG_DIR", None)
        env.pop("CODEX_HOME", None)

        # Force the degrade path: a real (non-symlink) directory sitting
        # where install.sh would otherwise place the dinostack skill
        # symlink makes the skill unreachable at its load path.
        skill_dst = home / ".agents/skills/dinostack"
        skill_dst.mkdir(parents=True)

        install = [
            "bash", str(self.repo / ".codex/install.sh"),
            "--mode=opt-out", "--profile=default", "--no-identity",
        ]
        result = execute(install, cwd=invoked, env=env)
        self.assertIn("degrade path", result.stdout)

        agents_dst = home / ".codex/AGENTS.md"
        agents_degraded = home / ".codex/AGENTS.degraded.md"
        # Behaviour 1: companion written, installed symlink points at it -
        # and it lives under the Codex config dir, never inside self.repo.
        self.assertTrue(agents_dst.is_symlink())
        self.assertEqual(str(agents_degraded), os.readlink(agents_dst))
        self.assertTrue(agents_degraded.is_file())
        self.assertFalse(agents_degraded.is_relative_to(self.repo))
        self.assertIn("Embedded methodology", agents_degraded.read_text(encoding="utf-8"))

        # Behaviour 2: runtime_bindings() accepts the degraded target.
        bindings_result = execute(
            [sys.executable, str(dispatcher), "runtime-bindings", str(invoked.resolve())],
            cwd=fixture,
            env=env,
        )
        bindings = json.loads(bindings_result.stdout)
        self.assertEqual(str((home / ".codex").resolve()), bindings["AE_CODEX_CONFIG_DIR"])

        # M1's actual reproduction: `git clean -xfd` on this checkout (or a
        # fresh worktree) cannot touch the companion, because it never
        # lived inside self.repo - asserted directly below via
        # is_relative_to(self.repo) rather than by actually invoking
        # `git clean` against the fixture. Confirm the companion and a
        # working runtime both survive a would-be clean.
        self.assertTrue(agents_degraded.exists())
        post_clean_bindings = execute(
            [sys.executable, str(dispatcher), "runtime-bindings", str(invoked.resolve())],
            cwd=fixture,
            env=env,
        )
        self.assertEqual(bindings_result.stdout, post_clean_bindings.stdout)

        # Behaviour 3: runtime_bindings() still rejects a third, arbitrary
        # physical target - the identity check is not simply disabled.
        rogue = home / ".codex/rogue-AGENTS.md"
        rogue.write_text("not dinostack\n", encoding="utf-8")
        agents_dst.unlink()
        agents_dst.symlink_to(rogue)
        rejected = execute(
            [sys.executable, str(dispatcher), "runtime-bindings", str(invoked.resolve())],
            cwd=fixture,
            env=env,
            expected=2,
        )
        self.assertIn("configured AGENTS.md resolves to", rejected.stderr)
        # Restore the degrade-path link for the remaining assertions below.
        agents_dst.unlink()
        agents_dst.symlink_to(agents_degraded)

        # Behaviour 4: auto-heal switches AGENTS_DST back to the stub and
        # removes the now-orphaned companion once the skill link is
        # healthy again.
        shutil.rmtree(skill_dst)
        heal_result = execute(install, cwd=invoked, env=env)
        self.assertIn("skill link healthy again", heal_result.stdout)
        self.assertTrue(agents_dst.is_symlink())
        self.assertEqual(str(self.repo / ".codex/AGENTS.md"), os.readlink(agents_dst))
        self.assertFalse(agents_degraded.exists())

        # Behaviour 5: force the degrade path again, then uninstall - the
        # companion must be removed.
        if skill_dst.is_symlink():
            skill_dst.unlink()
        else:
            shutil.rmtree(skill_dst)
        skill_dst.mkdir(parents=True)
        execute(install, cwd=invoked, env=env)
        self.assertTrue(agents_degraded.exists())
        execute(["bash", str(self.repo / ".codex/uninstall.sh")], cwd=invoked, env=env)
        self.assertFalse(agents_degraded.exists())
        self.assertFalse(agents_dst.exists())

    def test_degrade_path_companion_never_destroys_unmarked_user_data(self) -> None:
        # DS-183 round 6 (M1 fix). $AGENTS_DEGRADED moved to a user-owned
        # config path in round 5 - fixing the checkout-fragility problem
        # (see the test above) but introducing a data-loss one: nothing
        # distinguished a pre-existing real user file at that exact path
        # from install.sh/uninstall.sh's own generated artifact, so
        # uninstall.sh deleted it outright with no backup. This test
        # reproduces that against a genuine, unmarked pre-existing file and
        # asserts every step of the marker-based fix: install backs it up
        # rather than clobbering it; a second install (now marker-owned)
        # overwrites in place with no new backup; and uninstall restores
        # the ORIGINAL user backup rather than just deleting the companion.
        dispatcher = self.repo / "bin/agentic-codex-dispatch"
        fixture = Path(self.temporary.name) / "degrade-path-user-data"
        home = fixture / "home"
        invoked = fixture / "invoked-project"
        home.mkdir(parents=True)
        invoked.mkdir()
        execute(["git", "init", "-q", str(invoked)], cwd=fixture)

        env = os.environ.copy()
        env["HOME"] = str(home)
        env.pop("AGENTIC_CONFIG_DIR", None)
        env.pop("CODEX_HOME", None)

        # Force the degrade path, same technique as the test above.
        skill_dst = home / ".agents/skills/dinostack"
        skill_dst.mkdir(parents=True)

        codex_dir = home / ".codex"
        codex_dir.mkdir(parents=True)
        agents_degraded = codex_dir / "AGENTS.degraded.md"
        user_content = "MY OWN IMPORTANT NOTES - do not delete\n"
        agents_degraded.write_text(user_content, encoding="utf-8")

        install = [
            "bash", str(self.repo / ".codex/install.sh"),
            "--mode=opt-out", "--profile=default", "--no-identity",
        ]
        execute(install, cwd=invoked, env=env)

        # The pre-existing unmarked file must be preserved via backup, not
        # overwritten in place.
        backups = sorted(codex_dir.glob("AGENTS.degraded.md.backup-*"))
        self.assertEqual(1, len(backups), f"expected exactly one backup, found {backups}")
        self.assertEqual(user_content, backups[0].read_text(encoding="utf-8"))
        self.assertIn(
            "dinostack:codex-degrade-generated",
            agents_degraded.read_text(encoding="utf-8").splitlines()[0],
        )

        dispatcher_check = execute(
            [sys.executable, str(dispatcher), "runtime-bindings", str(invoked.resolve())],
            cwd=fixture,
            env=env,
        )
        self.assertTrue(json.loads(dispatcher_check.stdout)["AE_CODEX_CONFIG_DIR"])

        # A second install run (now marker-owned) overwrites the companion
        # in place with no additional backup.
        execute(install, cwd=invoked, env=env)
        backups_after_second_install = sorted(codex_dir.glob("AGENTS.degraded.md.backup-*"))
        self.assertEqual(1, len(backups_after_second_install))
        self.assertEqual(backups[0], backups_after_second_install[0])

        # Uninstall removes the marker-owned companion and restores the
        # ORIGINAL user backup, rather than just deleting the companion and
        # leaving the user's own data stranded in a .backup-* file only.
        execute(["bash", str(self.repo / ".codex/uninstall.sh")], cwd=invoked, env=env)
        self.assertTrue(agents_degraded.exists())
        self.assertEqual(user_content, agents_degraded.read_text(encoding="utf-8"))
        self.assertEqual([], sorted(codex_dir.glob("AGENTS.degraded.md.backup-*")))

    def test_degrade_path_write_failure_reports_actionable_error(self) -> None:
        # DS-183 round 6 (Minor fix). A non-writable Codex config directory
        # previously aborted the degrade-path write with a raw shell
        # "Permission denied" and no remediation. The straightforward-looking
        # `if ! { ...; } > "$TMP"; then` guard does NOT reliably propagate a
        # redirection failure through bash's `!` negation on a brace-group
        # command - measured directly: it silently takes the success branch
        # even though the write failed - so the actual fix disables -e
        # around the write and checks $? explicitly instead. This test
        # covers the fixed behaviour: a clear, actionable error and a clean
        # exit 1, never a raw abort with no guidance.
        fixture = Path(self.temporary.name) / "degrade-path-write-failure"
        home = fixture / "home"
        invoked = fixture / "invoked-project"
        home.mkdir(parents=True)
        invoked.mkdir()
        execute(["git", "init", "-q", str(invoked)], cwd=fixture)

        env = os.environ.copy()
        env["HOME"] = str(home)
        env.pop("AGENTIC_CONFIG_DIR", None)
        env.pop("CODEX_HOME", None)

        # Force the degrade path.
        skill_dst = home / ".agents/skills/dinostack"
        skill_dst.mkdir(parents=True)

        codex_dir = home / ".codex"
        codex_dir.mkdir(parents=True)
        codex_dir.chmod(0o555)
        self.addCleanup(lambda: codex_dir.chmod(0o755))

        install = [
            "bash", str(self.repo / ".codex/install.sh"),
            "--mode=opt-out", "--profile=default", "--no-identity",
        ]
        result = execute(install, cwd=invoked, env=env, expected=1)
        self.assertIn("could not write", result.stderr)
        self.assertIn("check write permissions on", result.stderr)
        codex_dir.chmod(0o755)
        self.assertEqual([], list(codex_dir.glob("AGENTS.degraded.md.tmp-*")))

    def test_generated_base_branch_guidance_matches_dispatcher_grammar(self) -> None:
        # DS-183 moved this guidance out of the always-loaded `.codex/AGENTS.md`
        # stub into the trigger-loaded skill bodies, so `.codex/AGENTS.md` is
        # deliberately excluded here - it no longer carries this text. Each
        # skill's own SKILL.md still must.
        paths = [
            self.repo / f".codex/skills/{skill}/SKILL.md"
            for skill in sorted(SKILL_NAMES)
        ]
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
        # DS-183 moved this guidance out of the always-loaded `.codex/AGENTS.md`
        # stub into the trigger-loaded wrap skill body, so `.codex/AGENTS.md`
        # is deliberately excluded here - it no longer carries this text.
        wrap = (self.repo / ".codex/skills/wrap/SKILL.md").read_text(encoding="utf-8")
        for label, text in (("wrap", wrap),):
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
            self.repo / ".codex/skills/dinostack/METHODOLOGY.md"
        ).read_text(encoding="utf-8")
        self.assertIn('task -> "Task"; omit to accept project default', ticket)
        self.assertIn("### Task-state initialization", ticket)
        self.assertIn("## Task entries (machine-readable)", ticket)
        self.assertIn("## Current Task / Next Steps", wrap)
        self.assertIn("## Task-state file", methodology)
        self.assertNotIn("spawn_agent-state", ticket + methodology)

    def test_shell_occurrences_classifies_ds_prefixed_bin_tokens(self) -> None:
        """Regression for the DS-rename classifier gap (scripts/codex-skills.py
        shell_occurrences): after bin/agentic-* -> bin/ds-* renamed the real
        content files onto a ds- prefix, a fenced-shell token like `ds-cost`
        fell through the `token.startswith("agentic-")` elif into the final
        else branch (kind="display-only", target="hashed-source-occurrence")
        instead of being recognized as a repository-owned operational bin/
        tool. Confirmed failing pre-fix: with the elif reverted to
        `token.startswith("agentic-")` only, this test's kind/resolution_mode/
        expected_target assertions redden (see fix commit for revert+rerun).
        """
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
                    "Run it:",
                    "```bash",
                    "ds-cost team",
                    "```",
                )
            ),
        )
        occurrences = module.inventory_document(fixture, self.repo)
        matches = [o for o in occurrences if o.source_token == "ds-cost"]
        self.assertEqual(
            len(matches), 1,
            f"expected exactly one ds-cost occurrence, got {matches!r} in {occurrences!r}",
        )
        occ = matches[0]
        self.assertEqual(occ.kind, "operational")
        self.assertEqual(occ.resolution_mode, "repository-owned")
        self.assertEqual(occ.expected_target, "bin/ds-cost")
        self.assertNotEqual(occ.kind, "display-only")
        self.assertNotEqual(occ.expected_target, "hashed-source-occurrence")

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
        map_path = self.repo / ".codex/skills/dinostack/RESOURCE-MAP.json"
        original = map_path.read_bytes()
        hostile = self.repo / ".codex/skills/dinostack/dispatch-fifo"
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
        self.assertTrue((physical / "skills/dinostack/SKILL.md").is_file())

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
        # Strip comment lines FIRST, before any assertion runs, so every
        # assertion below that is meant to describe LIVE configuration reads
        # `code_text` rather than the raw `workflow` text - a commented-out
        # or illustrative line (e.g. "# runs-on: ubuntu-latest (was)") must
        # never satisfy a check that a live key is actually set.
        code_lines = [
            line for line in workflow.splitlines() if not line.strip().startswith("#")
        ]
        code_text = "\n".join(code_lines)
        self.assertIn(
            "run: python3 scripts/test/test_codex_skills.py\n",
            code_text,
        )
        self.assertIn("python3 scripts/test/test_codex_skills.py --clean-clone", code_text)
        self.assertIn("\n  check-codex-skill-sync:\n", code_text)
        self.assertIn("runs-on: ubuntu-latest", code_text)
        # No secondary-platform matrix leg: GitHub Actions appends
        # " (<matrix value>)" to the reported check name for ANY job with a
        # strategy.matrix key, even a single-value one - a matrix here would
        # make the required context "check-codex-skill-sync" unsatisfiable.
        self.assertNotIn("strategy:", code_text)
        self.assertNotIn("matrix:", code_text)
        self.assertIn("bash .codex/build.sh", code_text)
        self.assertIn("git diff --exit-code", code_text)
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
        self.assertIn("~/.agents/skills/dinostack", readme)
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
            "exactly four native Codex skills: dinostack, brief, wrap, "
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
                "`$AE_REPO_DIR/bin/ds-codex-dispatch command ds-skeptic`"
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
        # DS-183 moved this workflow-token guidance out of the always-loaded
        # `.codex/AGENTS.md` stub into the trigger-loaded dinostack skill's
        # METHODOLOGY.md, symlinked (not copied) into ~/.agents/skills/ by
        # install.sh - so the workflow-token assertions below are retargeted
        # at that installed symlink target rather than installed AGENTS.md.
        installed_methodology = (
            home / ".agents/skills/dinostack/METHODOLOGY.md"
        ).read_text(encoding="utf-8")
        for token in sorted(native_tokens):
            self.assertIn(token, installed_methodology)
        for token in sorted(skeptic_tokens):
            self.assertIn(token, installed_methodology)
        self.assertNotIn("$skeptic", installed_agents)
        self.assertNotRegex(installed_agents, r"(?<![\w./-])/ds-[a-z0-9-]+\b")

        generated_guidance = {
            ".codex/AGENTS.md": (self.repo / ".codex/AGENTS.md").read_text(
                encoding="utf-8"
            ),
        }
        generated_guidance.update(
            {
                str(path.relative_to(self.repo)): path.read_text(encoding="utf-8")
                for path in sorted((self.repo / ".codex/skills").rglob("*.md"))
            }
        )
        generic_profile_guidance = (
            r"(?:profile|identity)[^\n]{0,240}"
            r"(?:--profile-dir <dir>|active config-dir environment|"
            r"cannot be derived from `AGENTIC_CONFIG_DIR`|--scope <scope>)"
        )
        for generated_path, content in generated_guidance.items():
            self.assertNotRegex(
                content,
                generic_profile_guidance,
                f"generic profile identity guidance survived in {generated_path}",
            )
            for command in re.findall(
                r"ds-identity (?:show|confirm)[^\n`]*--scope profile[^\n`]*",
                content,
            ):
                self.assertIn(
                    '--profile-dir "$AE_CODEX_CONFIG_DIR"',
                    command,
                    f"unpinned Codex profile identity command in {generated_path}",
                )
        self.assertIn(
            'ds-identity show --scope profile --profile-dir "$AE_CODEX_CONFIG_DIR"',
            installed_agents,
        )
        self.assertIn(
            'ds-identity confirm --scope profile --profile-dir "$AE_CODEX_CONFIG_DIR"',
            installed_agents,
        )
        self.assertIn("$AE_CODEX_CONFIG_DIR/identity.yml", installed_agents)
        self.assertNotIn("<active-config-dir>/identity.yml", installed_agents)
        self.assertIn(
            "use only the already-validated `$AE_CODEX_CONFIG_DIR` runtime binding",
            installed_agents,
        )
        self.assertNotIn(
            "active profile config dir is the first non-empty qualifying value",
            installed_agents,
        )
        self.assertIn(
            "$AE_REPO_DIR/bin/ds-codex-dispatch runtime-bindings",
            installed_agents,
        )

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

        # DS-183 moved this guidance out of the always-loaded `.codex/AGENTS.md`
        # stub into the trigger-loaded skill bodies, so `.codex/AGENTS.md` is
        # deliberately excluded from this positive check (it is still covered
        # by the false_project_local_claims negative check above via
        # generated_surfaces).
        for relative in (
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
                        ".codex/skills/dinostack/templates/.agentic/"
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
            self.repo / ".codex/skills/dinostack/SKILL.md"
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

        resource_map = module.resource_map("dinostack")
        resources = resource_map["resources"]
        manifest_descriptor = resources["project-scaffolding.yml"]
        skill_root = self.repo / ".codex/skills/dinostack"
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
            "`$AE_REPO_DIR/bin/ds-codex-dispatch command ds-init-project`) "
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
            ".codex/lib/prompt-wrappers.py",
            "scripts/check-codex-skill-sync.sh",
            "scripts/test/test_codex_skills.py",
            ".codex/build.sh",
            ".codex/skill-frontmatter/brief.yml",
            ".codex/skill-compatibility.yml",
            ".codex/skills/brief/SKILL.md",
            ".codex/prompts/ds-brief.md",
            ".codex/prompt-generation-state/manifest.json",
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


class CodexPromptWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-prompts-test-")
        self.addCleanup(self.temporary.cleanup)
        self.repo = copy_repo(Path(self.temporary.name))

    def prompt(self, command: str, *, expected: int = 0, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return run_prompts(self.repo, command, expected=expected, env=env)

    def test_inventory_wrapper_bytes_and_closed_manifest(self) -> None:
        inventory = json.loads(self.prompt("inventory").stdout)
        self.assertEqual(26, len(inventory))
        self.assertEqual(sorted(inventory), inventory)
        self.assertNotIn("ds-wrap-deferred", inventory)
        self.assertEqual(
            {"dinostack", "brief", "wrap", "implement-ticket", ROOT_MARKER},
            {entry.name for entry in (self.repo / ".codex/skills").iterdir()},
        )
        prompts = self.repo / ".codex/prompts"
        self.assertEqual(
            {".dinostack-generated-root.json", *(f"{name}.md" for name in inventory)},
            {entry.name for entry in prompts.iterdir()},
        )
        for name in inventory:
            text = (prompts / f"{name}.md").read_text(encoding="utf-8")
            expected = (
                "---\n"
                f"description: Run DinoStack workflow {name}\n"
                'argument-hint: "[arguments]"\n'
                "---\n"
                "Use the `$dinostack` skill. From that loaded skill's physical root, "
                f"read and execute the canonical `commands/{name}.md` workflow with these arguments:\n\n"
                "$ARGUMENTS\n"
            )
            self.assertEqual(expected, text)
            self.assertEqual(1, text.count("$ARGUMENTS"))
            self.assertEqual(1, text.count(f"commands/{name}.md"))
            neutral = text.replace(f"commands/{name}.md", "commands/NEUTRAL.md")
            self.assertNotRegex(neutral, r"/ds-[a-z0-9-]+|/prompts?:")
            self.assertNotIn(f"/{name.removeprefix('ds-')}", neutral)
        raw_manifest = (self.repo / ".codex/prompt-generation-state/manifest.json").read_bytes()
        manifest = json.loads(raw_manifest)
        self.assertEqual(
            raw_manifest,
            (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        )
        self.assertEqual(
            {"binding", "entries", "magic", "schema_version"},
            set(manifest),
        )
        self.assertEqual(
            {
                "commands_root": ".codex/commands",
                "kind": "canonical",
                "prompts_root": ".codex/prompts",
                "state_root": ".codex/prompt-generation-state",
            },
            manifest["binding"],
        )
        self.assertEqual(
            sorted(
                (
                    (name, f"{name}.md", f"{name}.md")
                    for name in inventory
                ),
                key=lambda entry: entry[1],
            ),
            [
                (entry["basename"], entry["output"], entry["source"])
                for entry in manifest["entries"]
            ],
        )

    def test_read_only_modes_and_clean_noop_preserve_identity(self) -> None:
        before_repo = identity_fingerprint(self.repo)
        unrelated = Path(self.temporary.name) / "cwd with spaces"
        unrelated.mkdir()
        run_prompts(self.repo, "inventory", cwd=unrelated)
        missing_runtime = run_prompts(
            self.repo, "check", cwd=unrelated, expected=1
        )
        self.assertIn("prompt runtime root", missing_runtime.stderr)
        self.assertEqual(before_repo, identity_fingerprint(self.repo))
        tracked_before = {
            "prompts": identity_fingerprint(self.repo / ".codex/prompts"),
            "state": identity_fingerprint(self.repo / ".codex/prompt-generation-state"),
            "skills": identity_fingerprint(self.repo / ".codex/skills"),
        }
        self.prompt("build")
        run_prompts(self.repo, "check", cwd=unrelated)
        self.prompt("build")
        self.assertEqual(tracked_before["prompts"], identity_fingerprint(self.repo / ".codex/prompts"))
        self.assertEqual(tracked_before["state"], identity_fingerprint(self.repo / ".codex/prompt-generation-state"))
        self.assertEqual(tracked_before["skills"], identity_fingerprint(self.repo / ".codex/skills"))

    def test_paths_precedence_is_read_only_and_validated(self) -> None:
        config_flag = Path(self.temporary.name) / "flag"
        config_agentic = Path(self.temporary.name) / "agentic"
        config_codex = Path(self.temporary.name) / "codex"
        home = Path(self.temporary.name) / "home"
        for path in (config_flag, config_agentic, config_codex, home / ".codex"):
            path.mkdir(parents=True, mode=0o700)
            path.chmod(0o700)
        before = fingerprint(Path(self.temporary.name))
        env = os.environ.copy()
        env.update(
            {
                "AGENTIC_CONFIG_DIR": str(config_agentic),
                "CODEX_HOME": str(config_codex),
                "HOME": str(home),
            }
        )
        command = [sys.executable, str(self.repo / PROMPT_GENERATOR), "paths"]
        agentic = execute(command, cwd=self.repo, env=env)
        self.assertEqual(str(config_agentic.resolve()), json.loads(agentic.stdout)["config_dir"])
        env.pop("AGENTIC_CONFIG_DIR")
        codex = execute(command, cwd=self.repo, env=env)
        self.assertEqual(str(config_codex.resolve()), json.loads(codex.stdout)["config_dir"])
        env.pop("CODEX_HOME")
        default = execute(command, cwd=self.repo, env=env)
        self.assertEqual(str((home / ".codex").resolve()), json.loads(default.stdout)["config_dir"])
        flagged = execute(command + ["--config-dir", str(config_flag)], cwd=self.repo, env=env)
        self.assertEqual(str(config_flag.resolve()), json.loads(flagged.stdout)["config_dir"])
        self.assertEqual(before, fingerprint(Path(self.temporary.name)))
        env["HOME"] = "relative"
        execute(command, cwd=self.repo, env=env, expected=1)

    def test_paths_invalid_config_dir_is_deterministic_without_traceback(self) -> None:
        command = [
            sys.executable,
            str(self.repo / PROMPT_GENERATOR),
            "paths",
            "--config-dir",
        ]
        missing = Path(self.temporary.name) / "missing-config"
        invalid_file = Path(self.temporary.name) / "config-file"
        invalid_file.write_text("not a directory\n", encoding="utf-8")
        for candidate in (missing, invalid_file):
            with self.subTest(candidate=candidate):
                first = execute(
                    command + [str(candidate)],
                    cwd=self.repo,
                    expected=1,
                )
                second = execute(
                    command + [str(candidate)],
                    cwd=self.repo,
                    expected=1,
                )
                self.assertEqual(first.stderr, second.stderr)
                self.assertTrue(first.stderr.startswith("ERROR: "))
                self.assertNotIn("Traceback", first.stderr)

    def test_unexpandable_tilde_paths_fail_with_closed_cli_errors_without_mutation(self) -> None:
        missing_user = "~definitely-no-such-dinostack-user/path"
        generator = str(self.repo / PROMPT_GENERATOR)
        valid_output = str(self.repo / ".codex/prompts")
        valid_state = str(self.repo / ".codex/prompt-generation-state")
        cases = (
            (["paths", "--config-dir", missing_user], "Codex config directory"),
            (["inventory", "--repo", missing_user], "repository root"),
            (["build", "--repo", missing_user], "repository root"),
            (["check", "--repo", missing_user], "repository root"),
            (
                [
                    "build", "--repo", str(self.repo), "--output", missing_user,
                    "--state-dir", valid_state,
                ],
                "prompt output root",
            ),
            (
                [
                    "check", "--repo", str(self.repo), "--output", missing_user,
                    "--state-dir", valid_state,
                ],
                "prompt output root",
            ),
            (
                [
                    "build", "--repo", str(self.repo), "--output", valid_output,
                    "--state-dir", missing_user,
                ],
                "prompt state root",
            ),
            (
                [
                    "check", "--repo", str(self.repo), "--output", valid_output,
                    "--state-dir", missing_user,
                ],
                "prompt state root",
            ),
        )
        before = fingerprint(Path(self.temporary.name))
        for arguments, label in cases:
            with self.subTest(arguments=arguments):
                result = execute(
                    [sys.executable, generator, *arguments],
                    cwd=self.repo,
                    expected=1,
                )
                self.assertEqual("", result.stdout)
                self.assertEqual(f"ERROR: cannot expand {label}\n", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(before, fingerprint(Path(self.temporary.name)))

    def test_hostile_directory_enumeration_stops_at_cap_plus_one(self) -> None:
        module = load_prompt_generator(self.repo)
        repo_info = os.lstat(self.repo)

        class FakeEntry:
            def __init__(self, index: int) -> None:
                self.name = f"entry-{index}"

            def stat(self, *, follow_symlinks: bool) -> os.stat_result:
                del follow_symlinks
                stats.append(self.name)
                return repo_info

        class FakeScandir:
            def __init__(self) -> None:
                self.index = 0

            def __enter__(self) -> FakeScandir:
                return self

            def __exit__(self, *arguments: object) -> None:
                del arguments

            def __iter__(self) -> FakeScandir:
                return self

            def __next__(self) -> FakeEntry:
                consumed.append(self.index)
                entry = FakeEntry(self.index)
                self.index += 1
                return entry

        consumed: list[int] = []
        stats: list[str] = []
        with mock.patch.object(module.os, "scandir", return_value=FakeScandir()):
            with self.assertRaisesRegex(module.PromptError, "entry ceiling"):
                module._direct_entries(
                    -1,
                    "hostile test root",
                    limit=2,
                )
        self.assertEqual([0, 1, 2], consumed)
        self.assertEqual(["entry-0", "entry-1"], stats)

        commands = self.repo / ".codex/commands"
        sources = self.repo / "content/commands"
        additions = module.MAX_INVENTORY + 1 - len(tuple(commands.iterdir()))
        for index in range(additions):
            name = f"ds-cap-{index:04d}.md"
            (sources / name).write_text("# cap\n", encoding="utf-8")
            (commands / name).symlink_to(f"../../content/commands/{name}")
        result = self.prompt("inventory", expected=1)
        self.assertIn("inventory exceeds its entry ceiling", result.stderr)

    def test_runtime_binding_enumeration_stops_at_cap_plus_one(self) -> None:
        self.prompt("build")
        runtime_base = self.repo / ".agentic/codex-prompt-generation"
        existing = len(tuple(runtime_base.iterdir()))
        module = load_prompt_generator(self.repo)
        for index in range(module.MAX_RUNTIME_BINDINGS + 1 - existing):
            (runtime_base / f"{index + 1:064x}").mkdir(mode=0o700)
        result = self.prompt("build", expected=1)
        self.assertIn("runtime binding root exceeds its entry ceiling", result.stderr)

    def test_output_enumeration_stops_at_cap_plus_one(self) -> None:
        module = load_prompt_generator(self.repo)
        self.prompt("build")
        output = self.repo / ".codex/prompts"
        additions = module.MAX_OUTPUT_ENTRIES + 1 - len(tuple(output.iterdir()))
        for index in range(additions):
            (output / f".hostile-{index:04d}").write_bytes(b"hostile\n")
        result = self.prompt("check", expected=1)
        self.assertIn("prompt output root exceeds its entry ceiling", result.stderr)

    def test_transaction_and_evidence_enumeration_stop_at_cap_plus_one(self) -> None:
        for surface in ("transaction", "evidence"):
            with self.subTest(surface=surface):
                fixture = copy_repo(
                    Path(self.temporary.name) / f"{surface}-entry-cap"
                )
                source = fixture / "content/commands/ds-entry-cap.md"
                mirror = fixture / ".codex/commands/ds-entry-cap.md"
                source.write_text("# entry cap\n", encoding="utf-8")
                mirror.symlink_to("../../content/commands/ds-entry-cap.md")
                env = os.environ.copy()
                env["DINOSTACK_PROMPT_FAULT"] = "after-journal"
                run_prompts(fixture, "build", expected=1, env=env)
                transaction = next(
                    (fixture / ".agentic/codex-prompt-generation").glob(
                        "*/transactions/*"
                    )
                )
                if surface == "transaction":
                    (transaction / "cap-plus-one").write_bytes(b"hostile\n")
                    expected_error = (
                        "prompt transaction exceeds its entry ceiling"
                    )
                else:
                    journal = json.loads(
                        (transaction / "journal.json").read_bytes()
                    )
                    allowed = {
                        str(value)
                        for operation in journal["operations"]
                        for key in ("old_evidence", "placeholder_evidence")
                        if (value := operation["artifacts"][key]) is not None
                    }
                    old_manifest = journal["manifest_artifacts"]["old_evidence"]
                    if old_manifest is not None:
                        allowed.add(str(old_manifest))
                    evidence = transaction / "evidence"
                    additions = len(allowed) + 1 - len(tuple(evidence.iterdir()))
                    for index in range(additions):
                        path = evidence / f"hostile-{index:04d}"
                        path.write_bytes(b"hostile\n")
                        path.chmod(0o600)
                    expected_error = (
                        "prompt transaction evidence exceeds its entry ceiling"
                    )
                result = run_prompts(fixture, "build", expected=1)
                self.assertIn(expected_error, result.stderr)

    def test_inventory_rejects_hostile_direct_entries_and_targets(self) -> None:
        commands = self.repo / ".codex/commands"
        cases: list[tuple[str, typing.Callable[[Path], object]]] = [
            ("hidden", lambda path: path.write_text("hidden", encoding="utf-8")),
            ("regular", lambda path: path.write_text("regular", encoding="utf-8")),
            ("directory", lambda path: path.mkdir()),
            ("wrong-target", lambda path: path.symlink_to("../../content/commands/ds-help.md")),
            ("case", lambda path: path.symlink_to("../../content/commands/DS-Bad.md")),
            ("unicode", lambda path: path.symlink_to("../../content/commands/ds-\N{GREEK SMALL LETTER ALPHA}.md")),
            ("overlong", lambda path: path.symlink_to("../../content/commands/" + "ds-" + "a" * 130 + ".md")),
        ]
        names = {
            "hidden": ".hidden.md",
            "regular": "ds-hostile.md",
            "directory": "ds-nested.md",
            "wrong-target": "ds-wrong.md",
            "case": "DS-Bad.md",
            "unicode": "ds-\N{GREEK SMALL LETTER ALPHA}.md",
            "overlong": "ds-" + "a" * 130 + ".md",
        }
        for label, mutate in cases:
            with self.subTest(case=label):
                path = commands / names[label]
                mutate(path)
                before = identity_fingerprint(commands)
                result = self.prompt("inventory", expected=1)
                self.assertIn("ERROR:", result.stderr)
                self.assertEqual(before, identity_fingerprint(commands))
                if path.is_dir() and not path.is_symlink():
                    path.rmdir()
                else:
                    path.unlink()
        if hasattr(os, "mkfifo"):
            fifo = commands / "ds-fifo.md"
            os.mkfifo(fifo)
            self.prompt("inventory", expected=1)
            fifo.unlink()

    def test_dynamic_add_remove_and_only_deferred_exclusion(self) -> None:
        source = self.repo / "content/commands/ds-new-workflow.md"
        mirror = self.repo / ".codex/commands/ds-new-workflow.md"
        source.write_text("# New workflow\n", encoding="utf-8")
        mirror.symlink_to("../../content/commands/ds-new-workflow.md")
        self.prompt("build")
        self.assertTrue((self.repo / ".codex/prompts/ds-new-workflow.md").is_file())
        self.assertEqual(27, len(json.loads(self.prompt("inventory").stdout)))
        mirror.unlink()
        source.unlink()
        self.prompt("build")
        self.assertFalse((self.repo / ".codex/prompts/ds-new-workflow.md").exists())
        self.assertFalse((self.repo / ".codex/prompts/ds-wrap-deferred.md").exists())
        self.prompt("check")

    def test_hostile_generated_bytes_topology_and_manifest_fail_closed(self) -> None:
        prompt = self.repo / ".codex/prompts/ds-brief.md"
        manifest = self.repo / ".codex/prompt-generation-state/manifest.json"
        outside = Path(self.temporary.name) / "outside.bin"
        outside.write_bytes(b"external sentinel")
        original = prompt.read_bytes()
        prompt.write_bytes(original + b"drift")
        self.prompt("check", expected=1)
        self.prompt("build", expected=1)
        self.assertEqual(b"external sentinel", outside.read_bytes())
        prompt.write_bytes(original)
        manifest_value = json.loads(manifest.read_bytes())
        manifest_value["unexpected"] = True
        manifest.write_bytes(
            (json.dumps(manifest_value, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
        self.prompt("check", expected=1)
        shutil.copy2(REPO / ".codex/prompt-generation-state/manifest.json", manifest)
        extra = self.repo / ".codex/prompts/unmanifested.md"
        extra.write_text("collision", encoding="utf-8")
        self.prompt("build", expected=1)
        self.assertEqual("collision", extra.read_text(encoding="utf-8"))
        extra.unlink()
        prompt.unlink()
        os.link(outside, prompt)
        self.prompt("check", expected=1)
        self.prompt("build", expected=1)
        self.assertEqual(b"external sentinel", outside.read_bytes())

    def test_marker_manifest_path_sha_mode_and_special_cases_fail_closed(self) -> None:
        prompt_marker = self.repo / ".codex/prompts/.dinostack-generated-root.json"
        state_marker = self.repo / ".codex/prompt-generation-state/.dinostack-generated-state.json"
        manifest_path = self.repo / ".codex/prompt-generation-state/manifest.json"
        wrapper = self.repo / ".codex/prompts/ds-help.md"
        originals = {
            prompt_marker: prompt_marker.read_bytes(),
            state_marker: state_marker.read_bytes(),
            manifest_path: manifest_path.read_bytes(),
            wrapper: wrapper.read_bytes(),
        }
        for marker in (prompt_marker, state_marker):
            with self.subTest(marker=marker.name):
                value = json.loads(marker.read_bytes())
                value["extra"] = "rejected"
                marker.write_bytes(
                    (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
                )
                before = identity_fingerprint(self.repo / ".codex")
                self.prompt("check", expected=1)
                self.prompt("build", expected=1)
                self.assertEqual(before, identity_fingerprint(self.repo / ".codex"))
                marker.write_bytes(originals[marker])
        mutations = (
            lambda value: value["entries"][0].update({"sha256": "0" * 64}),
            lambda value: value["entries"][0].update({"output": "../escape.md"}),
            lambda value: value["entries"][0].update({"source": "/absolute.md"}),
            lambda value: value["entries"][0].update({"extra": True}),
            lambda value: value.update({"extra": True}),
        )
        for mutate in mutations:
            with self.subTest(manifest_mutation=repr(mutate)):
                value = json.loads(originals[manifest_path])
                mutate(value)
                manifest_path.write_bytes(
                    (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
                )
                self.prompt("check", expected=1)
                self.prompt("build", expected=1)
                manifest_path.write_bytes(originals[manifest_path])
        wrapper.chmod(0o600)
        self.prompt("check", expected=1)
        self.prompt("build", expected=1)
        wrapper.chmod(0o644)
        if hasattr(os, "mkfifo"):
            wrapper.unlink()
            os.mkfifo(wrapper)
            self.prompt("check", expected=1)
            self.prompt("build", expected=1)
            wrapper.unlink()
            wrapper.write_bytes(originals[wrapper])
            wrapper.chmod(0o644)
        outside = Path(self.temporary.name) / "manifest-hardlink"
        outside.write_bytes(originals[manifest_path])
        manifest_path.unlink()
        os.link(outside, manifest_path)
        self.prompt("check", expected=1)
        self.prompt("build", expected=1)
        self.assertEqual(originals[manifest_path], outside.read_bytes())

    def test_root_symlink_and_special_substitution_never_mutates_external_sentinel(self) -> None:
        outside = Path(self.temporary.name) / "external"
        outside.mkdir()
        sentinel = outside / "sentinel"
        sentinel.write_bytes(b"keep")
        prompts = self.repo / ".codex/prompts"
        shutil.rmtree(prompts)
        prompts.symlink_to(outside, target_is_directory=True)
        before = identity_fingerprint(outside)
        self.prompt("check", expected=1)
        self.prompt("build", expected=1)
        self.assertEqual(before, identity_fingerprint(outside))
        prompts.unlink()
        shutil.copytree(REPO / ".codex/prompts", prompts)
        runtime_base = self.repo / ".agentic/codex-prompt-generation"
        if runtime_base.exists():
            shutil.rmtree(runtime_base)
        runtime_base.parent.mkdir(exist_ok=True, mode=0o700)
        runtime_base.symlink_to(outside, target_is_directory=True)
        self.prompt("build", expected=1)
        self.assertEqual(before, identity_fingerprint(outside))

    def test_private_arbitrary_roots_require_nonce_and_confine_runtime(self) -> None:
        container = Path(self.temporary.name) / "private"
        container.mkdir(mode=0o700)
        output = container / "prompts"
        state = container / "state"
        result = run_prompts(
            self.repo, "build", output=output, state=state, expected=1
        )
        self.assertIn("nonce", result.stderr)
        marker = container / ".dinostack-prompt-private-root.json"
        marker.write_bytes(
            (
                json.dumps(
                    {
                        "magic": "DINOSTACK_CODEX_PROMPT_PRIVATE_ROOT",
                        "nonce": "a" * 64,
                        "schema_version": 1,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode()
        )
        marker.chmod(0o600)
        run_prompts(self.repo, "build", output=output, state=state)
        run_prompts(self.repo, "check", output=output, state=state)
        owner_path = container / "runtime/owner.json"
        self.assertTrue(owner_path.is_file())
        self.assertFalse((self.repo / ".agentic/codex-prompt-generation").exists())
        renamed = self.repo.with_name("private-root-renamed-repo")
        self.repo.rename(renamed)
        self.repo = renamed
        run_prompts(self.repo, "build", output=output, state=state)
        run_prompts(self.repo, "check", output=output, state=state)
        run_prompts(self.repo, "build", output=output, state=state)
        run_prompts(self.repo, "check", output=output, state=state)
        retained_entries = tuple((container / "runtime/evidence").iterdir())
        self.assertEqual(1, len(retained_entries))

        current_owner = json.loads(owner_path.read_bytes())
        for replacement in (
            str(container / "nested/prompts"),
            str(container / "alias/../prompts"),
            str(container / "runtime"),
        ):
            with self.subTest(forged_private_path=replacement):
                forged = dict(current_owner)
                forged["prompts_root"] = replacement
                payload = (
                    json.dumps(forged, sort_keys=True, separators=(",", ":"))
                    + "\n"
                ).encode()
                path = (
                    container
                    / "runtime/evidence"
                    / f"owner-{hashlib.sha256(payload).hexdigest()}"
                )
                path.write_bytes(payload)
                path.chmod(0o600)
                before = identity_fingerprint(container / "runtime")
                for command in ("check", "build"):
                    rejected = run_prompts(
                        self.repo,
                        command,
                        output=output,
                        state=state,
                        expected=1,
                    )
                    self.assertIn("owner evidence", rejected.stderr)
                    self.assertEqual(
                        before,
                        identity_fingerprint(container / "runtime"),
                    )
                path.unlink()
        canonical_shaped = dict(current_owner)
        recorded_repo = Path(str(current_owner["repo_realpath"]))
        canonical_shaped["prompts_root"] = str(recorded_repo / ".codex/prompts")
        canonical_shaped["state_root"] = str(
            recorded_repo / ".codex/prompt-generation-state"
        )
        canonical_payload = (
            json.dumps(canonical_shaped, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode()
        canonical_path = (
            container
            / "runtime/evidence"
            / f"owner-{hashlib.sha256(canonical_payload).hexdigest()}"
        )
        canonical_path.write_bytes(canonical_payload)
        canonical_path.chmod(0o600)
        before = identity_fingerprint(container / "runtime")
        for command in ("check", "build"):
            rejected = run_prompts(
                self.repo,
                command,
                output=output,
                state=state,
                expected=1,
            )
            self.assertIn("owner evidence", rejected.stderr)
            self.assertEqual(before, identity_fingerprint(container / "runtime"))
        canonical_path.unlink()
        foreign = dict(current_owner)
        foreign["repo_ino"] = int(foreign["repo_ino"]) + 1
        foreign["binding"] = hashlib.sha256(
            f'{foreign["repo_dev"]}:{foreign["repo_ino"]}'.encode()
        ).hexdigest()
        foreign_payload = (
            json.dumps(foreign, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        foreign_path = (
            container
            / "runtime/evidence"
            / f"owner-{hashlib.sha256(foreign_payload).hexdigest()}"
        )
        foreign_path.write_bytes(foreign_payload)
        foreign_path.chmod(0o600)
        before = identity_fingerprint(container / "runtime")
        for command in ("check", "build"):
            rejected = run_prompts(
                self.repo,
                command,
                output=output,
                state=state,
                expected=1,
            )
            self.assertIn("owner evidence", rejected.stderr)
            self.assertEqual(before, identity_fingerprint(container / "runtime"))
        foreign_path.unlink()
        marker.chmod(0o644)
        run_prompts(self.repo, "check", output=output, state=state, expected=1)

    def test_fault_journal_recovery_create_prune_replace_manifest_and_cleanup(self) -> None:
        source = self.repo / "content/commands/ds-recovery.md"
        mirror = self.repo / ".codex/commands/ds-recovery.md"
        source.write_text("# recovery\n", encoding="utf-8")
        mirror.symlink_to("../../content/commands/ds-recovery.md")
        for fault in ("after-journal", "after-operation-0", "before-manifest", "after-manifest", "before-cleanup"):
            with self.subTest(fault=fault):
                env = os.environ.copy()
                env["DINOSTACK_PROMPT_FAULT"] = fault
                self.prompt("build", expected=1, env=env)
                self.prompt("check", expected=1)
                self.prompt("build")
                self.prompt("check")
                self.assertEqual(
                    [],
                    list((self.repo / ".agentic/codex-prompt-generation").glob("*/transactions/*")),
                )
                mirror.unlink()
                source.unlink()
                self.prompt("build")
                source.write_text("# recovery\n", encoding="utf-8")
                mirror.symlink_to("../../content/commands/ds-recovery.md")
        mirror.unlink()
        source.unlink()
        self.prompt("build")
        # Manufacture a valid older manifested wrapper to force the replace path.
        wrapper = self.repo / ".codex/prompts/ds-brief.md"
        older = wrapper.read_bytes().replace(b"Run DinoStack workflow", b"Run DinoStack workflow")
        older = older.replace(b"with these arguments:", b"with these arguments: ")
        wrapper.write_bytes(older)
        manifest_path = self.repo / ".codex/prompt-generation-state/manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        for entry in manifest["entries"]:
            if entry["output"] == "ds-brief.md":
                entry["sha256"] = hashlib.sha256(older).hexdigest()
        manifest_path.write_bytes(
            (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
        env = os.environ.copy()
        env["DINOSTACK_PROMPT_FAULT"] = "after-journal"
        self.prompt("build", expected=1, env=env)
        self.prompt("build")
        self.prompt("check")

    def test_pending_journal_schema_blob_closure_and_multiple_transactions_fail_closed(self) -> None:
        source = self.repo / "content/commands/ds-journal.md"
        mirror = self.repo / ".codex/commands/ds-journal.md"
        source.write_text("# journal\n", encoding="utf-8")
        mirror.symlink_to("../../content/commands/ds-journal.md")
        env = os.environ.copy()
        env["DINOSTACK_PROMPT_FAULT"] = "after-journal"
        self.prompt("build", expected=1, env=env)
        transaction = next(
            (self.repo / ".agentic/codex-prompt-generation").glob("*/transactions/*")
        )
        journal = transaction / "journal.json"
        original_journal = journal.read_bytes()
        value = json.loads(original_journal)
        value["extra"] = True
        journal.write_bytes(
            (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
        journal.chmod(0o600)
        self.prompt("check", expected=1)
        self.prompt("build", expected=1)
        journal.write_bytes(original_journal)
        journal.chmod(0o644)
        self.prompt("build", expected=1)
        journal.chmod(0o600)
        extra = transaction / "new/extra.md"
        extra.write_bytes(b"extra")
        extra.chmod(0o600)
        self.prompt("build", expected=1)
        extra.unlink()
        blob = transaction / "new/ds-journal.md"
        original_blob = blob.read_bytes()
        blob.write_bytes(original_blob + b"tamper")
        self.prompt("build", expected=1)
        blob.write_bytes(original_blob)
        blob.chmod(0o600)
        duplicate = transaction.with_name("f" * 64)
        shutil.copytree(transaction, duplicate)
        self.prompt("check", expected=1)
        self.prompt("build", expected=1)
        shutil.rmtree(duplicate)
        self.prompt("build")
        self.prompt("check")

    def test_foreign_pending_binding_conflicts_and_same_filesystem_rename_refreshes_owner(self) -> None:
        self.prompt("build")
        runtime_base = self.repo / ".agentic/codex-prompt-generation"
        active = next(runtime_base.iterdir())
        foreign = runtime_base / ("f" * 64)
        (foreign / "transactions" / ("e" * 64)).mkdir(parents=True, mode=0o700)
        foreign.chmod(0o700)
        (foreign / "transactions").chmod(0o700)
        (foreign / "transactions" / ("e" * 64)).chmod(0o700)
        self.prompt("build", expected=1)
        shutil.rmtree(foreign)
        old_repo = self.repo
        renamed = old_repo.with_name("repo renamed")
        old_repo.rename(renamed)
        self.repo = renamed
        run_prompts(self.repo, "build")
        run_prompts(self.repo, "check")
        owner = json.loads((next((self.repo / ".agentic/codex-prompt-generation").iterdir()) / "owner.json").read_bytes())
        self.assertEqual(str(self.repo.resolve()), owner["repo_realpath"])
        self.assertEqual(str(self.repo.resolve() / ".codex/prompts"), owner["prompts_root"])
        self.assertEqual(active.name, next((self.repo / ".agentic/codex-prompt-generation").iterdir()).name)

    def test_repeated_repository_rename_cycles_converge_with_bounded_owner_evidence(self) -> None:
        self.prompt("build")
        original = self.repo
        alternate = original.with_name("repo alternate")
        generated_before = {
            "prompts": identity_fingerprint(original / ".codex/prompts"),
            "state": identity_fingerprint(original / ".codex/prompt-generation-state"),
        }
        runtime_binding = next(
            (original / ".agentic/codex-prompt-generation").iterdir()
        ).name

        for destination in (alternate, original, alternate, original) * 3:
            self.repo.rename(destination)
            self.repo = destination
            run_prompts(self.repo, "build")
            run_prompts(self.repo, "check")
            runtime = self.repo / ".agentic/codex-prompt-generation" / runtime_binding
            owner = json.loads((runtime / "owner.json").read_bytes())
            self.assertEqual(str(self.repo.resolve()), owner["repo_realpath"])
            self.assertEqual(
                str(self.repo.resolve() / ".codex/prompts"),
                owner["prompts_root"],
            )
            self.assertEqual(
                str(self.repo.resolve() / ".codex/prompt-generation-state"),
                owner["state_root"],
            )
            evidence = tuple((runtime / "evidence").iterdir())
            self.assertLessEqual(len(evidence), 64)
            for entry in evidence:
                self.assertRegex(entry.name, r"^owner-[0-9a-f]{64}(?:-[0-9a-f]{32})?$")
                payload = entry.read_bytes()
                self.assertTrue(entry.name.startswith(f"owner-{hashlib.sha256(payload).hexdigest()}"))
                self.assertEqual(
                    {
                        "binding", "magic", "prompts_root", "repo_dev", "repo_ino",
                        "repo_realpath", "schema_version", "state_root",
                    },
                    set(json.loads(payload)),
                )

        self.assertEqual(
            generated_before["prompts"],
            identity_fingerprint(self.repo / ".codex/prompts"),
        )
        self.assertEqual(
            generated_before["state"],
            identity_fingerprint(self.repo / ".codex/prompt-generation-state"),
        )

    def test_owner_refresh_failpoints_restart_and_repeat_rename_cycles(self) -> None:
        faults = (
            "owner-after-stage",
            "owner-after-exchange",
            "owner-before-quarantine",
            "owner-after-quarantine-rename",
        )
        for fault in faults:
            with self.subTest(fault=fault):
                fixture = copy_repo(Path(self.temporary.name) / fault)
                run_prompts(fixture, "build")
                original = fixture
                alternate = original.with_name(f"{original.name}-alternate")
                original.rename(alternate)
                fixture = alternate
                env = os.environ.copy()
                env["DINOSTACK_PROMPT_FAULT"] = fault
                run_prompts(fixture, "build", expected=1, env=env)
                run_prompts(fixture, "build")
                for destination in (original, alternate, original, alternate):
                    fixture.rename(destination)
                    fixture = destination
                    run_prompts(fixture, "build")
                    run_prompts(fixture, "check")
                    runtime = next(
                        (fixture / ".agentic/codex-prompt-generation").iterdir()
                    )
                    expected_owner = json.loads(
                        (runtime / "owner.json").read_bytes()
                    )
                    self.assertEqual(str(fixture.resolve()), expected_owner["repo_realpath"])
                    self.assertEqual(
                        str(fixture.resolve() / ".codex/prompts"),
                        expected_owner["prompts_root"],
                    )
                    self.assertEqual([], list(runtime.glob(".owner-*.stage")))
                    evidence = tuple((runtime / "evidence").iterdir())
                    self.assertLessEqual(len(evidence), 64)
                    for entry in evidence:
                        payload = entry.read_bytes()
                        self.assertRegex(
                            entry.name,
                            r"^owner-[0-9a-f]{64}(?:-[0-9a-f]{32})?$",
                        )
                        self.assertTrue(
                            entry.name.startswith(
                                f"owner-{hashlib.sha256(payload).hexdigest()}"
                            )
                        )

    def test_cold_owner_partial_publication_and_absence_adoption_converge(self) -> None:
        module = load_prompt_generator(self.repo)
        paths = module.resolve_paths(module._repo(str(self.repo)), None, None)
        expected = module.canonical_json(module._runtime_owner(paths))
        for iteration in range(8):
            with self.subTest(iteration=iteration):
                shutil.rmtree(self.repo / ".agentic", ignore_errors=True)
                env = os.environ.copy()
                env["DINOSTACK_PROMPT_FAULT"] = "initial-owner-after-write"
                failed = self.prompt("build", expected=1, env=env)
                self.assertIn("initial-owner-after-write", failed.stderr)
                runtime = paths.runtime
                stage = runtime / module.INITIAL_OWNER_STAGE
                self.assertTrue(stage.is_file())
                self.assertLess(stage.stat().st_size, len(expected))
                self.assertEqual(expected[:stage.stat().st_size], stage.read_bytes())
                self.prompt("build")
                self.prompt("build")
                self.prompt("check")
                self.assertEqual(expected, (runtime / "owner.json").read_bytes())
                self.assertFalse(stage.exists())
                self.assertEqual(
                    {"build.lock", "completed", "evidence", "owner.json", "transactions"},
                    {entry.name for entry in runtime.iterdir()},
                )

        shutil.rmtree(self.repo / ".agentic", ignore_errors=True)
        env = os.environ.copy()
        env["DINOSTACK_PROMPT_FAULT"] = "initial-owner-after-write"
        self.prompt("build", expected=1, env=env)
        stage = paths.runtime / module.INITIAL_OWNER_STAGE
        legacy_owner = paths.runtime / "owner.json"
        stage.rename(legacy_owner)
        partial = legacy_owner.read_bytes()
        self.assertEqual(expected[:len(partial)], partial)
        self.prompt("build")
        self.assertEqual(expected, legacy_owner.read_bytes())

        shutil.rmtree(self.repo / ".agentic", ignore_errors=True)
        self.prompt("build", expected=1, env=env)
        stage = paths.runtime / module.INITIAL_OWNER_STAGE
        stage.rename(paths.runtime / "owner.json")
        (paths.runtime / "owner.json").write_bytes(b"arbitrary-corruption")
        before = identity_fingerprint(paths.runtime)
        failed = self.prompt("build", expected=1)
        self.assertIn("ERROR:", failed.stderr)
        self.assertEqual(before, identity_fingerprint(paths.runtime))

    def test_legacy_partial_owner_is_resumed_but_arbitrary_bytes_are_not(self) -> None:
        module = load_prompt_generator(self.repo)
        paths = module.resolve_paths(module._repo(str(self.repo)), None, None)
        expected = module.canonical_json(module._runtime_owner(paths))
        paths.runtime.mkdir(parents=True, mode=0o700)
        (self.repo / ".agentic").chmod(0o700)
        paths.runtime.parent.chmod(0o700)
        paths.runtime.chmod(0o700)
        (paths.runtime / "build.lock").write_bytes(b"")
        (paths.runtime / "build.lock").chmod(0o600)
        prefix = expected[:max(1, len(expected) // 3)]
        (paths.runtime / "owner.json").write_bytes(prefix)
        (paths.runtime / "owner.json").chmod(0o600)
        self.prompt("build")
        self.prompt("check")
        self.assertEqual(expected, (paths.runtime / "owner.json").read_bytes())

        shutil.rmtree(self.repo / ".agentic")
        paths.runtime.mkdir(parents=True, mode=0o700)
        (self.repo / ".agentic").chmod(0o700)
        paths.runtime.parent.chmod(0o700)
        paths.runtime.chmod(0o700)
        (paths.runtime / "build.lock").write_bytes(b"")
        (paths.runtime / "build.lock").chmod(0o600)
        (paths.runtime / "owner.json").write_bytes(b"arbitrary-corruption")
        (paths.runtime / "owner.json").chmod(0o600)
        before = identity_fingerprint(paths.runtime)
        result = self.prompt("build", expected=1)
        self.assertIn("ERROR:", result.stderr)
        self.assertEqual(before, identity_fingerprint(paths.runtime))

    def test_completed_inventory_digest_accepts_only_derived_legacy_forms(self) -> None:
        source = self.repo / "content/commands/ds-digest-compat.md"
        mirror = self.repo / ".codex/commands/ds-digest-compat.md"
        source.write_text("# digest compatibility\n", encoding="utf-8")
        mirror.symlink_to("../../content/commands/ds-digest-compat.md")
        self.prompt("build")
        self.prompt("check")
        completed = next(
            (self.repo / ".agentic/codex-prompt-generation").glob(
                "*/completed/*"
            )
        )
        journal_path = completed / "journal.json"
        journal = json.loads(journal_path.read_bytes())
        manifest = json.loads((completed / "new/manifest.json").read_bytes())
        names = [entry["basename"] for entry in manifest["entries"]]
        ordered_digest = hashlib.sha256(
            (json.dumps(names, sort_keys=True, separators=(",", ":")) + "\n").encode()
        ).hexdigest()
        sorted_digest = hashlib.sha256(
            (
                json.dumps(sorted(names), sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode()
        ).hexdigest()
        self.assertNotEqual(ordered_digest, sorted_digest)
        self.assertEqual(ordered_digest, journal["source_inventory_sha256"])

        journal["source_inventory_sha256"] = sorted_digest
        journal_path.write_bytes(
            (json.dumps(journal, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
        self.prompt("check")

        journal["source_inventory_sha256"] = "f" * 64
        journal_path.write_bytes(
            (json.dumps(journal, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
        result = self.prompt("check", expected=1)
        self.assertIn("inventory digest", result.stderr)

    def test_owner_evidence_semantic_inconsistency_fails_without_mutation(self) -> None:
        self.prompt("build")
        runtime = next(
            (self.repo / ".agentic/codex-prompt-generation").iterdir()
        )
        owner = json.loads((runtime / "owner.json").read_bytes())
        evidence = runtime / "evidence"

        def assert_rejected(mutator: typing.Callable[[dict[str, object]], None]) -> None:
            value = dict(owner)
            mutator(value)
            payload = (
                json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode()
            path = evidence / f"owner-{hashlib.sha256(payload).hexdigest()}"
            path.write_bytes(payload)
            path.chmod(0o600)
            before = identity_fingerprint(runtime)
            for command in ("check", "build"):
                result = self.prompt(command, expected=1)
                self.assertIn("owner evidence", result.stderr)
                self.assertEqual(before, identity_fingerprint(runtime))
            path.unlink()

        cases: tuple[typing.Callable[[dict[str, object]], None], ...] = (
            lambda value: value.update({"binding": "f" * 64}),
            lambda value: value.update(
                {
                    "repo_dev": int(value["repo_dev"]) + 1,
                    "binding": hashlib.sha256(
                        f'{int(value["repo_dev"]) + 1}:{value["repo_ino"]}'.encode()
                    ).hexdigest(),
                }
            ),
            lambda value: value.update({"prompts_root": str(self.repo / "other")}),
            lambda value: value.update({"state_root": str(self.repo / "other")}),
            lambda value: value.update(
                {
                    "prompts_root": str(runtime.parent / "private-output"),
                    "state_root": str(runtime.parent / "private-state"),
                }
            ),
            lambda value: value.update(
                {"repo_realpath": str(self.repo.parent / "alias" / ".." / self.repo.name)}
            ),
            lambda value: value.update({"repo_realpath": "relative/repo"}),
            lambda value: value.update({"repo_realpath": str(self.repo) + "/."}),
        )
        for mutate in cases:
            with self.subTest(mutate=repr(mutate)):
                assert_rejected(mutate)

    def test_check_rejects_poisoned_runtime_without_mutation(self) -> None:
        self.prompt("build")
        runtime = next(
            (self.repo / ".agentic/codex-prompt-generation").iterdir()
        )
        moved = self.repo.with_name("runtime-check-moved")
        self.repo.rename(moved)
        self.repo = moved
        self.prompt("check")
        poison_index = 0

        def assert_rejected(mutator: typing.Callable[[Path], None]) -> None:
            nonlocal poison_index
            poison_index += 1
            fixture = copy_repo(Path(self.temporary.name) / f"runtime-poison-{poison_index}")
            run_prompts(fixture, "build")
            fixture_runtime = next(
                (fixture / ".agentic/codex-prompt-generation").iterdir()
            )
            mutator(fixture_runtime)
            before = identity_fingerprint(fixture_runtime)
            result = run_prompts(fixture, "check", expected=1)
            self.assertIn("ERROR:", result.stderr)
            self.assertEqual(before, identity_fingerprint(fixture_runtime))
            sync = execute(
                ["bash", str(fixture / "scripts/check-codex-skill-sync.sh")],
                cwd=fixture,
                expected=1,
            )
            self.assertIn("ERROR:", sync.stderr + sync.stdout)
            self.assertEqual(before, identity_fingerprint(fixture_runtime))

        def hardlink_lock(root: Path) -> None:
            source = root.parent / "hardlink-source"
            source.write_bytes(b"")
            source.chmod(0o600)
            (root / "build.lock").unlink()
            os.link(source, root / "build.lock")

        def symlink_lock(root: Path) -> None:
            (root / "build.lock").unlink()
            (root / "build.lock").symlink_to("owner.json")

        def fifo_lock(root: Path) -> None:
            (root / "build.lock").unlink()
            os.mkfifo(root / "build.lock", 0o600)

        def wrong_mode_lock(root: Path) -> None:
            (root / "build.lock").chmod(0o644)

        mutations: list[typing.Callable[[Path], None]] = [
            lambda root: (root / "owner.json").write_bytes(b"{\"bad\":true}\n"),
            lambda root: (root / "build.lock").write_bytes(b"poison"),
            hardlink_lock,
            symlink_lock,
            wrong_mode_lock,
            lambda root: (root / "unexpected").write_bytes(b"poison"),
            lambda root: (root / "completed" / ("f" * 64)).mkdir(mode=0o700),
            lambda root: (root / "evidence" / ("owner-" + "f" * 64)).write_bytes(b"bad"),
            lambda root: (root / "transactions" / ("e" * 64)).mkdir(mode=0o700),
        ]
        if hasattr(os, "mkfifo"):
            mutations.append(fifo_lock)
        for mutator in mutations:
            with self.subTest(mutator=repr(mutator)):
                assert_rejected(mutator)

        clean = copy_repo(Path(self.temporary.name) / "clean-check")
        before = identity_fingerprint(clean)
        result = run_prompts(clean, "check", expected=1)
        self.assertIn("ERROR:", result.stderr)
        self.assertEqual(before, identity_fingerprint(clean))

    def test_noreplace_unsupported_fallback_refuses_before_mutation(self) -> None:
        module = load_prompt_generator(self.repo)
        root = Path(self.temporary.name) / "noreplace-fallback"
        root.mkdir(mode=0o700)
        source = root / "source"
        source.write_bytes(b"owned")
        source.chmod(0o600)
        before = identity_fingerprint(root)
        dir_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            with mock.patch.object(module.ctypes, "CDLL", return_value=object()):
                with self.assertRaisesRegex(
                    module.PromptError,
                    "atomic no-replace rename is unavailable",
                ):
                    module._rename_noreplace(dir_fd, "source", "destination")
        finally:
            os.close(dir_fd)
        self.assertEqual(before, identity_fingerprint(root))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires FIFO support")
    def test_fifo_journal_stage_and_read_substitutions_fail_promptly(self) -> None:
        source = self.repo / "content/commands/ds-fifo-stage.md"
        mirror = self.repo / ".codex/commands/ds-fifo-stage.md"
        source.write_text("# fifo stage\n", encoding="utf-8")
        mirror.symlink_to("../../content/commands/ds-fifo-stage.md")
        env = os.environ.copy()
        env["DINOSTACK_PROMPT_FAULT"] = "after-journal"
        self.prompt("build", expected=1, env=env)
        transaction = next(
            (self.repo / ".agentic/codex-prompt-generation").glob(
                "*/transactions/*"
            )
        )
        journal = json.loads((transaction / "journal.json").read_bytes())
        operation = next(item for item in journal["operations"] if item["action"] == "create")
        stage = self.repo / ".codex/prompts" / operation["artifacts"]["stage"]
        os.mkfifo(stage, 0o600)
        command = [
            sys.executable,
            str(self.repo / PROMPT_GENERATOR),
            "build",
            "--repo",
            str(self.repo),
        ]
        result = subprocess.run(
            command,
            cwd=self.repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
            check=False,
        )
        self.assertEqual(1, result.returncode, result)
        self.assertRegex(result.stderr, r"safe regular file|safely open")
        self.assertTrue(stat.S_ISFIFO(os.lstat(stage).st_mode))

        script = r'''
import importlib.util, os, pathlib, sys
repo = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("fifo_probe", repo / ".codex/lib/prompt-wrappers.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
mode = sys.argv[2]
root_path = repo / (".fifo-probe-" + mode)
root_path.mkdir(mode=0o700)
leaf = root_path / "leaf"
leaf.write_bytes(b"safe")
leaf.chmod(0o600)
root = module._root_identity(root_path, "fifo probe", exact_mode=0o700)
if mode == "optional":
    leaf.unlink()
    os.mkfifo(leaf, 0o600)
    module._read_optional_pinned(root, "leaf", "fifo optional", mode=0o600, max_bytes=16)
else:
    dir_fd = module._open_root(root, "fifo probe")
    real_open = module.os.open
    swapped = False
    def substitute(name, flags, *args, **kwargs):
        global swapped
        if name == "leaf" and not swapped:
            swapped = True
            leaf.unlink()
            os.mkfifo(leaf, 0o600)
        return real_open(name, flags, *args, **kwargs)
    module.os.open = substitute
    try:
        module._read_child(dir_fd, "leaf", "fifo child", exact_mode=0o600, max_bytes=16)
    finally:
        os.close(dir_fd)
'''
        for mode in ("optional", "child"):
            with self.subTest(helper=mode):
                probe = subprocess.run(
                    [sys.executable, "-c", script, str(self.repo), mode],
                    cwd=self.repo,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=3,
                    check=False,
                )
                self.assertNotEqual(0, probe.returncode)
                self.assertIn("PromptError", probe.stderr)

    def test_before_journal_fault_cleans_transaction_and_preserves_old_state(self) -> None:
        tracked_before = identity_fingerprint(self.repo / ".codex/prompts")
        state_before = identity_fingerprint(self.repo / ".codex/prompt-generation-state")
        source = self.repo / "content/commands/ds-before-journal.md"
        mirror = self.repo / ".codex/commands/ds-before-journal.md"
        source.write_text("# before\n", encoding="utf-8")
        mirror.symlink_to("../../content/commands/ds-before-journal.md")
        env = os.environ.copy()
        env["DINOSTACK_PROMPT_FAULT"] = "after-blobs"
        self.prompt("build", expected=1, env=env)
        self.assertEqual(tracked_before, identity_fingerprint(self.repo / ".codex/prompts"))
        self.assertEqual(state_before, identity_fingerprint(self.repo / ".codex/prompt-generation-state"))
        self.assertEqual(
            [],
            list((self.repo / ".agentic/codex-prompt-generation").glob("*/transactions/*")),
        )

    def test_manifest_schema_ceiling_and_canonical_corruption_fail_closed(self) -> None:
        manifest = self.repo / ".codex/prompt-generation-state/manifest.json"
        original = manifest.read_bytes()
        over_limit_entries = [
            {
                "basename": f"ds-limit-{index:04d}",
                "output": f"ds-limit-{index:04d}.md",
                "sha256": "0" * 64,
                "source": f"ds-limit-{index:04d}.md",
            }
            for index in range(513)
        ]
        mutations: list[tuple[str, bytes]] = []
        for label, mutate in (
            ("binding-extra", lambda item: item["binding"].update({"extra": True})),
            ("entries-type", lambda item: item.update({"entries": {}})),
            (
                "basename-over-limit",
                lambda item: item["entries"][0].update(
                    {
                        "basename": "ds-" + "a" * 126,
                        "output": "ds-" + "a" * 126 + ".md",
                        "source": "ds-" + "a" * 126 + ".md",
                    }
                ),
            ),
            (
                "uppercase-digest",
                lambda item: item["entries"][0].update({"sha256": "A" * 64}),
            ),
            (
                "source-mismatch",
                lambda item: item["entries"][0].update({"source": "ds-other.md"}),
            ),
            (
                "entry-ceiling",
                lambda item: item.update({"entries": over_limit_entries}),
            ),
        ):
            changed = json.loads(original)
            mutate(changed)
            mutations.append(
                (
                    label,
                    (
                        json.dumps(changed, sort_keys=True, separators=(",", ":"))
                        + "\n"
                    ).encode(),
                )
            )
        mutations.extend(
            (
                (
                    "duplicate-json-key",
                    original.replace(
                        b'{"binding":',
                        b'{"magic":"duplicate","binding":',
                        1,
                    ),
                ),
                ("trailing-bytes", original + b"\n"),
                ("byte-ceiling", b" " * (1024 * 1024 + 1)),
            )
        )
        for label, changed in mutations:
            with self.subTest(corruption=label):
                manifest.write_bytes(changed)
                before = identity_fingerprint(self.repo / ".codex")
                self.prompt("check", expected=1)
                self.prompt("build", expected=1)
                self.assertEqual(before, identity_fingerprint(self.repo / ".codex"))
                manifest.write_bytes(original)
        self.prompt("check")

    def test_boolean_schema_versions_fail_closed_in_every_control_schema(self) -> None:
        def encode(value: object) -> bytes:
            return (
                json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode()

        module = load_prompt_generator(self.repo)
        repo = module._repo(str(self.repo))
        paths = module.resolve_paths(repo, None, None)
        manifest_path = self.repo / ".codex/prompt-generation-state/manifest.json"
        manifest_original = manifest_path.read_bytes()
        self.prompt("build")
        owner_path = next(
            (self.repo / ".agentic/codex-prompt-generation").glob("*/owner.json")
        )
        owner_original = owner_path.read_bytes()

        container = Path(self.temporary.name) / "boolean-private"
        output = container / "prompts"
        state = container / "state"
        container.mkdir(mode=0o700)
        private_path = container / ".dinostack-prompt-private-root.json"
        private_original = encode(
            {
                "magic": "DINOSTACK_CODEX_PROMPT_PRIVATE_ROOT",
                "nonce": "a" * 64,
                "schema_version": 1,
            }
        )
        private_path.write_bytes(private_original)
        private_path.chmod(0o600)
        run_prompts(self.repo, "build", output=output, state=state)

        cases = (
            ("private-container", private_path, private_original, True),
            ("private-container", private_path, private_original, False),
            ("manifest", manifest_path, manifest_original, True),
            ("manifest", manifest_path, manifest_original, False),
            ("runtime-owner", owner_path, owner_original, True),
            ("runtime-owner", owner_path, owner_original, False),
        )
        for label, path, original, hostile in cases:
            with self.subTest(schema=label, value=hostile):
                value = json.loads(original)
                value["schema_version"] = hostile
                path.write_bytes(encode(value))
                with self.assertRaises(module.PromptError):
                    if label == "private-container":
                        module._private_container(output, state)
                    elif label == "manifest":
                        module._parse_manifest(path.read_bytes())
                    else:
                        module._prepare_runtime(paths)
                path.write_bytes(original)

        source = self.repo / "content/commands/ds-boolean-schema.md"
        mirror = self.repo / ".codex/commands/ds-boolean-schema.md"
        source.write_text("# boolean schema\n", encoding="utf-8")
        mirror.symlink_to("../../content/commands/ds-boolean-schema.md")
        env = os.environ.copy()
        env["DINOSTACK_PROMPT_FAULT"] = "after-journal"
        self.prompt("build", expected=1, env=env)
        journal_path = next(
            (self.repo / ".agentic/codex-prompt-generation").glob(
                "*/transactions/*/journal.json"
            )
        )
        journal_original = journal_path.read_bytes()
        for hostile in (True, False):
            with self.subTest(schema="journal", value=hostile):
                value = json.loads(journal_original)
                value["schema_version"] = hostile
                journal_path.write_bytes(encode(value))
                with self.assertRaises(module.PromptError):
                    module._journal(journal_path.parent)
                journal_path.write_bytes(journal_original)

    def test_transaction_closed_schema_semantics_and_forged_blobs_fail_closed(self) -> None:
        source = self.repo / "content/commands/ds-transaction-schema.md"
        mirror = self.repo / ".codex/commands/ds-transaction-schema.md"
        source.write_text("# transaction schema\n", encoding="utf-8")
        mirror.symlink_to("../../content/commands/ds-transaction-schema.md")
        env = os.environ.copy()
        env["DINOSTACK_PROMPT_FAULT"] = "after-journal"
        self.prompt("build", expected=1, env=env)
        transaction = next(
            (self.repo / ".agentic/codex-prompt-generation").glob("*/transactions/*")
        )
        backup = Path(self.temporary.name) / "transaction-backup"
        shutil.copytree(transaction, backup)

        def restore() -> None:
            shutil.rmtree(transaction)
            shutil.copytree(backup, transaction)

        def mutate_journal(
            callback: typing.Callable[[dict[str, typing.Any]], None],
        ) -> None:
            journal_path = transaction / "journal.json"
            journal = json.loads(journal_path.read_bytes())
            callback(journal)
            journal_path.write_bytes(
                (
                    json.dumps(journal, sort_keys=True, separators=(",", ":"))
                    + "\n"
                ).encode()
            )

        def forge_wrapper() -> None:
            journal_path = transaction / "journal.json"
            manifest_path = transaction / "new/manifest.json"
            wrapper_path = transaction / "new/ds-transaction-schema.md"
            forged = b"forged wrapper body\n"
            wrapper_path.write_bytes(forged)
            wrapper_hash = hashlib.sha256(forged).hexdigest()
            manifest_value = json.loads(manifest_path.read_bytes())
            next(
                entry
                for entry in manifest_value["entries"]
                if entry["basename"] == "ds-transaction-schema"
            )["sha256"] = wrapper_hash
            manifest_bytes = (
                json.dumps(
                    manifest_value,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode()
            manifest_path.write_bytes(manifest_bytes)
            journal = json.loads(journal_path.read_bytes())
            next(
                operation
                for operation in journal["operations"]
                if operation["path"] == "ds-transaction-schema.md"
            )["new_sha256"] = wrapper_hash
            journal["new_manifest_sha256"] = hashlib.sha256(
                manifest_bytes
            ).hexdigest()
            journal_path.write_bytes(
                (
                    json.dumps(journal, sort_keys=True, separators=(",", ":"))
                    + "\n"
                ).encode()
            )

        cases: list[tuple[str, typing.Callable[[], object]]] = [
            (
                "transaction-root-extra",
                lambda: (transaction / "extra").write_text("extra", encoding="utf-8"),
            ),
            (
                "journal-extra-key",
                lambda: mutate_journal(lambda journal: journal.update({"extra": True})),
            ),
            (
                "inventory-digest",
                lambda: mutate_journal(
                    lambda journal: journal.update(
                        {"source_inventory_sha256": "0" * 64}
                    )
                ),
            ),
            (
                "operation-omission",
                lambda: mutate_journal(
                    lambda journal: journal.update(
                        {"operations": journal["operations"][1:]}
                    )
                ),
            ),
            (
                "operation-correlation",
                lambda: mutate_journal(
                    lambda journal: journal["operations"][0].update(
                        {"action": "replace", "old_sha256": "0" * 64}
                    )
                ),
            ),
            ("forged-wrapper", forge_wrapper),
            (
                "journal-mode",
                lambda: (transaction / "journal.json").chmod(0o644),
            ),
            (
                "transaction-mode",
                lambda: transaction.chmod(0o755),
            ),
        ]
        for label, mutate in cases:
            with self.subTest(corruption=label):
                mutate()
                generated_before = {
                    "prompts": identity_fingerprint(self.repo / ".codex/prompts"),
                    "state": identity_fingerprint(
                        self.repo / ".codex/prompt-generation-state"
                    ),
                }
                self.prompt("check", expected=1)
                self.prompt("build", expected=1)
                self.assertEqual(
                    generated_before["prompts"],
                    identity_fingerprint(self.repo / ".codex/prompts"),
                )
                self.assertEqual(
                    generated_before["state"],
                    identity_fingerprint(
                        self.repo / ".codex/prompt-generation-state"
                    ),
                )
                restore()
        self.prompt("build")
        self.prompt("check")

    def test_manifest_is_published_last_and_recovery_validates_outputs_first(self) -> None:
        manifest = self.repo / ".codex/prompt-generation-state/manifest.json"
        old_manifest = manifest.read_bytes()
        source = self.repo / "content/commands/ds-manifest-last.md"
        mirror = self.repo / ".codex/commands/ds-manifest-last.md"
        source.write_text("# manifest last\n", encoding="utf-8")
        mirror.symlink_to("../../content/commands/ds-manifest-last.md")
        env = os.environ.copy()
        env["DINOSTACK_PROMPT_FAULT"] = "before-manifest"
        self.prompt("build", expected=1, env=env)
        self.assertEqual(old_manifest, manifest.read_bytes())
        self.assertTrue((self.repo / ".codex/prompts/ds-manifest-last.md").is_file())
        self.prompt("check", expected=1)
        self.prompt("build")
        self.assertNotEqual(old_manifest, manifest.read_bytes())
        self.prompt("check")

    def test_descriptor_pinned_root_replace_and_prune_substitution_races(self) -> None:
        self.prompt("build")
        module = load_prompt_generator(self.repo)
        repo = module._repo(str(self.repo))
        paths = module.resolve_paths(repo, None, None)
        root = module._root_identity(paths.output, "prompt output root")
        outside = Path(self.temporary.name) / "descriptor-race-outside"
        outside.mkdir()
        sentinel = outside / "sentinel"
        sentinel.write_bytes(b"external sentinel")
        outside_before = identity_fingerprint(outside)

        saved_root = paths.output.with_name("prompts-pinned-saved")
        real_open = module.os.open
        swapped = False

        def substitute_root(path: typing.Any, flags: int, *args: typing.Any, **kwargs: typing.Any) -> int:
            nonlocal swapped
            if not swapped and Path(path) == paths.output and flags & getattr(os, "O_DIRECTORY", 0):
                paths.output.rename(saved_root)
                paths.output.symlink_to(outside, target_is_directory=True)
                swapped = True
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(module.os, "open", side_effect=substitute_root):
            with self.assertRaises(module.PromptError):
                module._atomic_bytes(root, "ds-race.md", b"race\n", 0o644, expected=None)
        paths.output.unlink()
        saved_root.rename(paths.output)
        self.assertEqual(outside_before, identity_fingerprint(outside))

        target = paths.output / "ds-brief.md"
        original = target.read_bytes()
        held = paths.output / ".race-held"
        evidence = Path(self.temporary.name) / "descriptor-evidence"
        evidence.mkdir(mode=0o700)
        evidence_root = module._root_identity(
            evidence,
            "test evidence root",
            exact_mode=0o700,
        )
        replace_plan = module.MutationPlan(
            stage=".descriptor-replace.stage",
            old_evidence="descriptor-replace-old",
            placeholder_evidence=None,
            evidence_root=evidence_root,
            fault_prefix="replace",
        )
        real_exchange = module._rename_exchange
        exchanged = False

        def substitute_replace(dir_fd: int, left: str, right: str) -> None:
            nonlocal exchanged
            if not exchanged:
                target.rename(held)
                target.symlink_to(sentinel)
                exchanged = True
            real_exchange(dir_fd, left, right)

        with mock.patch.object(module, "_rename_exchange", side_effect=substitute_replace):
            with self.assertRaises(module.PromptError):
                module._atomic_bytes(
                    root,
                    target.name,
                    original + b"new",
                    0o644,
                    expected=original,
                    plan=replace_plan,
                )
        self.assertTrue(target.is_symlink())
        self.assertEqual(original, held.read_bytes())
        self.assertEqual(outside_before, identity_fingerprint(outside))
        target.unlink()
        held.rename(target)
        module._quarantine_leaf(
            root,
            replace_plan.stage,
            evidence_root,
            "descriptor-failed-stage",
            original + b"new",
            0o644,
            max_bytes=module.MAX_WRAPPER_BYTES,
            fault_prefix="test",
        )

        exchanged = False
        attacker = b"substituted direct child"
        attacker_inode = -1

        def substitute_prune(dir_fd: int, left: str, right: str) -> None:
            nonlocal exchanged, attacker_inode
            if not exchanged:
                target.rename(held)
                target.write_bytes(attacker)
                attacker_inode = target.stat().st_ino
                exchanged = True
            real_exchange(dir_fd, left, right)

        prune_plan = module.MutationPlan(
            stage=".descriptor-prune.hold",
            old_evidence="descriptor-prune-old",
            placeholder_evidence="descriptor-prune-placeholder",
            evidence_root=evidence_root,
            fault_prefix="prune",
        )
        with mock.patch.object(module, "_rename_exchange", side_effect=substitute_prune):
            with self.assertRaises(module.PromptError):
                module._unlink_owned(
                    root,
                    target.name,
                    original,
                    plan=prune_plan,
                )
        self.assertTrue(target.is_file())
        self.assertEqual(attacker, target.read_bytes())
        self.assertEqual(attacker_inode, target.stat().st_ino)
        self.assertEqual(original, held.read_bytes())
        self.assertEqual(outside_before, identity_fingerprint(outside))
        target.unlink()
        held.rename(target)
        self.prompt("check")

    def test_atomic_create_and_replace_reject_staged_temp_substitution(self) -> None:
        self.prompt("build")
        module = load_prompt_generator(self.repo)
        repo = module._repo(str(self.repo))
        paths = module.resolve_paths(repo, None, None)
        root = module._root_identity(paths.output, "prompt output root")
        evidence = Path(self.temporary.name) / "atomic-evidence"
        evidence.mkdir(mode=0o700)
        evidence_root = module._root_identity(
            evidence,
            "test evidence root",
            exact_mode=0o700,
        )

        create_name = "ds-temp-create.md"
        create_destination = paths.output / create_name
        create_stage = paths.output / ".create-stage-held"
        create_attacker = b"attacker create bytes\n"
        create_temp: Path | None = None
        create_inode = -1
        real_noreplace = module._rename_noreplace
        substituted = False

        def substitute_create(dir_fd: int, source: str, destination: str) -> None:
            nonlocal create_temp, create_inode, substituted
            if not substituted and destination == create_name:
                create_temp = paths.output / source
                create_temp.rename(create_stage)
                create_temp.write_bytes(create_attacker)
                create_temp.chmod(0o644)
                create_inode = create_temp.stat().st_ino
                substituted = True
            real_noreplace(dir_fd, source, destination)

        with mock.patch.object(
            module,
            "_rename_noreplace",
            side_effect=substitute_create,
        ):
            with self.assertRaises(module.PromptError):
                module._atomic_bytes(
                    root,
                    create_name,
                    b"trusted create bytes\n",
                    0o644,
                    expected=None,
                    plan=module.MutationPlan(
                        stage=".atomic-create.stage",
                        old_evidence=None,
                        placeholder_evidence=None,
                        evidence_root=evidence_root,
                        fault_prefix="create",
                    ),
                )
        self.assertFalse(create_destination.exists())
        self.assertIsNotNone(create_temp)
        assert create_temp is not None
        self.assertTrue(create_temp.is_file())
        self.assertEqual(create_attacker, create_temp.read_bytes())
        self.assertEqual(create_inode, create_temp.stat().st_ino)
        create_temp.unlink()
        create_stage.unlink()

        target = paths.output / "ds-brief.md"
        original = target.read_bytes()
        replace_stage = paths.output / ".replace-stage-held"
        replace_attacker = b"attacker replace bytes\n"
        replace_temp: Path | None = None
        replace_inode = -1
        real_exchange = module._rename_exchange
        substituted = False

        def substitute_replace_temp(dir_fd: int, left: str, right: str) -> None:
            nonlocal replace_temp, replace_inode, substituted
            if not substituted and right == target.name:
                replace_temp = paths.output / left
                replace_temp.rename(replace_stage)
                replace_temp.write_bytes(replace_attacker)
                replace_temp.chmod(0o644)
                replace_inode = replace_temp.stat().st_ino
                substituted = True
            real_exchange(dir_fd, left, right)

        with mock.patch.object(
            module,
            "_rename_exchange",
            side_effect=substitute_replace_temp,
        ):
            with self.assertRaises(module.PromptError):
                module._atomic_bytes(
                    root,
                    target.name,
                    original + b"trusted replacement\n",
                    0o644,
                    expected=original,
                    plan=module.MutationPlan(
                        stage=".atomic-replace.stage",
                        old_evidence="atomic-replace-old",
                        placeholder_evidence=None,
                        evidence_root=evidence_root,
                        fault_prefix="replace",
                    ),
                )
        self.assertEqual(original, target.read_bytes())
        self.assertIsNotNone(replace_temp)
        assert replace_temp is not None
        self.assertTrue(replace_temp.is_file())
        self.assertEqual(replace_attacker, replace_temp.read_bytes())
        self.assertEqual(replace_inode, replace_temp.stat().st_ino)
        replace_temp.unlink()
        replace_stage.unlink()
        self.prompt("check")

    def test_post_validation_cleanup_never_deletes_substituted_external_leaf(self) -> None:
        module = load_prompt_generator(self.repo)
        repo = module._repo(str(self.repo))
        paths = module.resolve_paths(repo, None, None)
        root = module._root_identity(paths.output, "prompt output root")
        target = paths.output / "ds-brief.md"
        original = target.read_bytes()
        evidence = Path(self.temporary.name) / "cleanup-evidence"
        evidence.mkdir(mode=0o700)
        evidence_root = module._root_identity(
            evidence,
            "test evidence root",
            exact_mode=0o700,
        )
        plan = module.MutationPlan(
            stage=".cleanup-replace.stage",
            old_evidence="cleanup-replace-old",
            placeholder_evidence=None,
            evidence_root=evidence_root,
            fault_prefix="replace",
        )
        external = Path(self.temporary.name) / "cleanup-external"
        external.write_bytes(b"external cleanup sentinel\n")
        external.chmod(0o640)
        os.utime(external, ns=(1_700_000_000_000_000_000,) * 2)
        def external_signature(path: Path) -> tuple[object, ...]:
            info = os.lstat(path)
            return (
                info.st_dev,
                info.st_ino,
                info.st_mode,
                info.st_mtime_ns,
                path.read_bytes(),
            )

        external_before = external_signature(external)
        displaced = paths.output / ".cleanup-displaced"
        real_move = module._rename_noreplace_between
        substituted = False

        def substitute_temp(
            source_fd: int,
            source: str,
            destination_fd: int,
            destination: str,
        ) -> None:
            nonlocal substituted
            if not substituted and source == plan.stage:
                (paths.output / source).rename(displaced)
                os.link(external, paths.output / source)
                substituted = True
            real_move(source_fd, source, destination_fd, destination)

        with mock.patch.object(
            module,
            "_rename_noreplace_between",
            side_effect=substitute_temp,
        ):
            with self.assertRaises(module.PromptError):
                module._atomic_bytes(
                    root,
                    target.name,
                    original + b"replacement\n",
                    0o644,
                    expected=original,
                    plan=plan,
                )
        self.assertTrue(substituted)
        self.assertEqual(external_before, external_signature(external))

    def test_prune_and_transaction_cleanup_never_delete_substituted_leaves(self) -> None:
        for boundary in ("name", "hold", "transaction-child", "transaction-root"):
            with self.subTest(boundary=boundary):
                fixture = copy_repo(Path(self.temporary.name) / boundary)
                module = load_prompt_generator(fixture)
                repo = module._repo(str(fixture))
                paths = module.resolve_paths(repo, None, None)
                external = Path(self.temporary.name) / f"{boundary}-external"
                substituted = False

                if boundary in {"transaction-child", "transaction-root"}:
                    source = fixture / "content/commands/ds-cleanup-race.md"
                    mirror = fixture / ".codex/commands/ds-cleanup-race.md"
                    source.write_text("# cleanup race\n", encoding="utf-8")
                    mirror.symlink_to("../../content/commands/ds-cleanup-race.md")
                    env = os.environ.copy()
                    env["DINOSTACK_PROMPT_FAULT"] = "after-journal"
                    run_prompts(fixture, "build", expected=1, env=env)
                    transaction = next(
                        (fixture / ".agentic/codex-prompt-generation").glob(
                            "*/transactions/*"
                        )
                    )
                    if boundary == "transaction-child":
                        external.write_bytes(b"transaction child sentinel\n")
                        external.chmod(0o600)
                        os.utime(
                            external,
                            ns=(1_700_000_000_000_000_000,) * 2,
                        )

                        def child_signature(path: Path) -> tuple[object, ...]:
                            info = os.lstat(path)
                            return (
                                info.st_dev,
                                info.st_ino,
                                info.st_mode,
                                info.st_mtime_ns,
                                path.read_bytes(),
                            )

                        external_before = child_signature(external)
                        blob = next((transaction / "new").iterdir())
                        displaced = Path(self.temporary.name) / "transaction-child-displaced"
                        blob.rename(displaced)
                        os.link(external, blob)
                        substituted = True
                        module._remove_transaction(transaction)
                    else:
                        external.mkdir()
                        (external / "sentinel").write_bytes(b"transaction sentinel\n")
                        external_before = identity_fingerprint(external)
                        displaced = Path(self.temporary.name) / "transaction-root-displaced"
                        real_move = module._rename_noreplace_between

                        def substitute_transaction(
                            source_fd: int,
                            source_name: str,
                            destination_fd: int,
                            destination_name: str,
                        ) -> None:
                            nonlocal substituted
                            if not substituted and source_name == transaction.name:
                                transaction.rename(displaced)
                                transaction.symlink_to(
                                    external,
                                    target_is_directory=True,
                                )
                                substituted = True
                            real_move(
                                source_fd,
                                source_name,
                                destination_fd,
                                destination_name,
                            )

                        with mock.patch.object(
                            module,
                            "_rename_noreplace_between",
                            side_effect=substitute_transaction,
                        ):
                            with self.assertRaises(module.PromptError):
                                module._remove_transaction(transaction)
                else:
                    external.write_bytes(f"{boundary} sentinel\n".encode())
                    external.chmod(0o640)
                    os.utime(external, ns=(1_700_000_000_000_000_000,) * 2)

                    def external_signature(path: Path) -> tuple[object, ...]:
                        info = os.lstat(path)
                        return (
                            info.st_dev,
                            info.st_ino,
                            info.st_mode,
                            info.st_mtime_ns,
                            path.read_bytes(),
                        )

                    external_before = external_signature(external)
                    root = module._root_identity(paths.output, "prompt output root")
                    target = paths.output / "ds-brief.md"
                    original = target.read_bytes()
                    displaced = paths.output / f".{boundary}-displaced"
                    evidence = Path(self.temporary.name) / f"{boundary}-evidence"
                    evidence.mkdir(mode=0o700)
                    plan = module.MutationPlan(
                        stage=f".{boundary}-prune.hold",
                        old_evidence=f"{boundary}-old",
                        placeholder_evidence=f"{boundary}-placeholder",
                        evidence_root=module._root_identity(
                            evidence,
                            "test evidence root",
                            exact_mode=0o700,
                        ),
                        fault_prefix="prune",
                    )
                    real_move = module._rename_noreplace_between

                    def substitute_prune_cleanup(
                        source_fd: int,
                        source_name: str,
                        destination_fd: int,
                        destination_name: str,
                    ) -> None:
                        nonlocal substituted
                        selected = (
                            boundary == "name" and source_name == target.name
                        ) or (
                            boundary == "hold" and source_name == plan.stage
                        )
                        if not substituted and selected:
                            (paths.output / source_name).rename(displaced)
                            os.link(external, paths.output / source_name)
                            substituted = True
                        real_move(
                            source_fd,
                            source_name,
                            destination_fd,
                            destination_name,
                        )

                    with mock.patch.object(
                        module,
                        "_rename_noreplace_between",
                        side_effect=substitute_prune_cleanup,
                    ):
                        with self.assertRaises(module.PromptError):
                            module._unlink_owned(
                                root,
                                target.name,
                                original,
                                plan=plan,
                            )
                self.assertTrue(substituted)
                if boundary == "transaction-child":
                    self.assertEqual(external_before, child_signature(external))
                elif boundary == "transaction-root":
                    self.assertEqual(
                        external_before,
                        identity_fingerprint(external),
                    )
                else:
                    self.assertEqual(external_before, external_signature(external))

    def test_internal_mutation_failpoints_restart_to_exact_state(self) -> None:
        cases = (
            ("replace-after-stage", "replace"),
            ("replace-after-exchange", "replace"),
            ("replace-before-quarantine", "replace"),
            ("replace-after-quarantine-rename", "replace"),
            ("prune-after-placeholder", "prune"),
            ("prune-after-exchange", "prune"),
            ("prune-after-quarantine-rename", "prune"),
            ("prune-after-tombstone", "prune"),
            ("manifest-after-stage", "manifest"),
            ("manifest-after-exchange", "manifest"),
            ("manifest-before-quarantine", "manifest"),
            ("manifest-after-quarantine-rename", "manifest"),
            ("transaction-after-archive", "manifest"),
        )
        for fault, action in cases:
            with self.subTest(fault=fault):
                fixture = copy_repo(Path(self.temporary.name) / fault)
                if action == "replace":
                    wrapper = fixture / ".codex/prompts/ds-brief.md"
                    wrapper.write_bytes(wrapper.read_bytes() + b"old\n")
                    manifest = fixture / ".codex/prompt-generation-state/manifest.json"
                    value = json.loads(manifest.read_bytes())
                    next(
                        entry
                        for entry in value["entries"]
                        if entry["basename"] == "ds-brief"
                    )["sha256"] = hashlib.sha256(wrapper.read_bytes()).hexdigest()
                    manifest.write_bytes(
                        (
                            json.dumps(value, sort_keys=True, separators=(",", ":"))
                            + "\n"
                        ).encode()
                    )
                elif action == "prune":
                    source = fixture / "content/commands/ds-help.md"
                    mirror = fixture / ".codex/commands/ds-help.md"
                    mirror.unlink()
                    source.unlink()
                else:
                    source = fixture / "content/commands/ds-internal-fault.md"
                    mirror = fixture / ".codex/commands/ds-internal-fault.md"
                    source.write_text("# internal fault\n", encoding="utf-8")
                    mirror.symlink_to("../../content/commands/ds-internal-fault.md")
                env = os.environ.copy()
                env["DINOSTACK_PROMPT_FAULT"] = fault
                run_prompts(fixture, "build", expected=1, env=env)
                if fault.endswith("after-stage") or fault.endswith(
                    "after-placeholder"
                ):
                    transaction = next(
                        (fixture / ".agentic/codex-prompt-generation").glob(
                            "*/transactions/*"
                        )
                    )
                    journal = json.loads(
                        (transaction / "journal.json").read_bytes()
                    )
                    if action == "manifest":
                        artifacts = journal["manifest_artifacts"]
                        mutation_root = (
                            fixture / ".codex/prompt-generation-state"
                        )
                    else:
                        operation = next(
                            item
                            for item in journal["operations"]
                            if item["action"] == action
                        )
                        artifacts = operation["artifacts"]
                        mutation_root = fixture / ".codex/prompts"
                    self.assertTrue(
                        (mutation_root / artifacts["stage"]).exists(),
                        "journal exists and names the durable pre-mutation stage",
                    )
                run_prompts(fixture, "build")
                run_prompts(fixture, "check")

    def test_post_exchange_read_failures_restore_original_inode_and_bytes(self) -> None:
        for action in ("replace", "prune"):
            with self.subTest(action=action):
                fixture = copy_repo(Path(self.temporary.name) / action)
                module = load_prompt_generator(fixture)
                repo = module._repo(str(fixture))
                paths = module.resolve_paths(repo, None, None)
                root = module._root_identity(paths.output, "prompt output root")
                target = paths.output / "ds-brief.md"
                original = target.read_bytes()
                evidence = Path(self.temporary.name) / f"{action}-rollback-evidence"
                evidence.mkdir(mode=0o700)
                sentinel = Path(self.temporary.name) / f"{action}-external"
                sentinel.write_bytes(b"external sentinel\n")
                sentinel.chmod(0o640)
                os.utime(
                    sentinel,
                    ns=(1_700_000_000_000_000_000,) * 2,
                )

                def signature(path: Path) -> tuple[object, ...]:
                    info = os.lstat(path)
                    return (
                        info.st_dev,
                        info.st_ino,
                        info.st_mode,
                        info.st_mtime_ns,
                        path.read_bytes(),
                    )

                target_before = signature(target)
                sentinel_before = signature(sentinel)
                plan = module.MutationPlan(
                    stage=f".{action}-read-failure.stage",
                    old_evidence=f"{action}-old",
                    placeholder_evidence=(
                        f"{action}-placeholder" if action == "prune" else None
                    ),
                    evidence_root=module._root_identity(
                        evidence,
                        "test rollback evidence",
                        exact_mode=0o700,
                    ),
                    fault_prefix=action,
                )
                real_read_child = module._read_child

                def fail_after_exchange(
                    dir_fd: int,
                    name: str,
                    label: str,
                    *,
                    exact_mode: int,
                    max_bytes: int = module.MAX_CONTROL_BYTES,
                ) -> tuple[bytes, os.stat_result]:
                    if (
                        action == "replace"
                        and label.startswith("published output")
                    ) or (
                        action == "prune"
                        and label.startswith("prune hold")
                    ):
                        raise module.PromptError(
                            "injected post-exchange read failure"
                        )
                    return real_read_child(
                        dir_fd,
                        name,
                        label,
                        exact_mode=exact_mode,
                        max_bytes=max_bytes,
                    )

                with mock.patch.object(
                    module,
                    "_read_child",
                    side_effect=fail_after_exchange,
                ):
                    with self.assertRaisesRegex(
                        module.PromptError,
                        "injected post-exchange read failure",
                    ):
                        if action == "replace":
                            module._atomic_bytes(
                                root,
                                target.name,
                                original + b"replacement\n",
                                0o644,
                                expected=original,
                                plan=plan,
                            )
                        else:
                            module._unlink_owned(
                                root,
                                target.name,
                                original,
                                plan=plan,
                            )
                self.assertEqual(target_before, signature(target))
                self.assertEqual(sentinel_before, signature(sentinel))

    def test_two_fresh_builders_converge_without_runtime_warmup(self) -> None:
        for iteration in range(8):
            with self.subTest(iteration=iteration):
                fixture = copy_repo(
                    Path(self.temporary.name) / f"fresh-build-{iteration}"
                )
                runtime_base = fixture / ".agentic/codex-prompt-generation"
                self.assertFalse(runtime_base.exists())
                command = [
                    sys.executable,
                    str(fixture / ".codex/lib/prompt-wrappers.py"),
                    "build",
                    "--repo",
                    str(fixture),
                ]
                first = subprocess.Popen(
                    command,
                    cwd=fixture,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                second = subprocess.Popen(
                    command,
                    cwd=fixture,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                first_output = first.communicate(timeout=30)
                second_output = second.communicate(timeout=30)
                self.assertEqual(
                    (0, 0),
                    (first.returncode, second.returncode),
                    (first_output, second_output),
                )
                run_prompts(fixture, "check")
                locks = tuple(runtime_base.glob("*/build.lock"))
                owners = tuple(runtime_base.glob("*/owner.json"))
                self.assertEqual((1, 1), (len(locks), len(owners)))
                self.assertEqual(b"", locks[0].read_bytes())

    def test_build_lock_rotation_is_rejected_and_two_builders_converge(self) -> None:
        module = load_prompt_generator(self.repo)
        runtime_lock: Path | None = None
        held_lock: Path | None = None
        real_flock = module.fcntl.flock
        rotated = False

        def rotate_before_lock(fd: int, operation: int) -> None:
            nonlocal runtime_lock, held_lock, rotated
            if not rotated and operation == module.fcntl.LOCK_EX:
                runtime_lock = next(
                    (
                        self.repo / ".agentic/codex-prompt-generation"
                    ).glob("*/build.lock")
                )
                held_lock = runtime_lock.with_name("build.lock.rotated")
                runtime_lock.rename(held_lock)
                runtime_lock.write_bytes(b"")
                runtime_lock.chmod(0o600)
                rotated = True
            real_flock(fd, operation)

        with mock.patch.object(module.fcntl, "flock", side_effect=rotate_before_lock):
            with self.assertRaises(module.PromptError):
                module.build(module.resolve_paths(module._repo(str(self.repo)), None, None))

        assert runtime_lock is not None and held_lock is not None
        runtime_lock.unlink()
        held_lock.rename(runtime_lock)
        source = self.repo / "content/commands/ds-two-builders.md"
        mirror = self.repo / ".codex/commands/ds-two-builders.md"
        source.write_text("# two builders\n", encoding="utf-8")
        mirror.symlink_to("../../content/commands/ds-two-builders.md")
        command = [
            sys.executable,
            str(self.repo / ".codex/lib/prompt-wrappers.py"),
            "build",
            "--repo",
            str(self.repo),
        ]
        first = subprocess.Popen(command, cwd=self.repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        second = subprocess.Popen(command, cwd=self.repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        first_output = first.communicate(timeout=30)
        second_output = second.communicate(timeout=30)
        self.assertEqual((0, 0), (first.returncode, second.returncode), (first_output, second_output))
        self.prompt("check")

    def test_cleanup_has_no_pathname_deletes_and_evidence_cap_fails_closed(self) -> None:
        source = (
            self.repo / ".codex/lib/prompt-wrappers.py"
        ).read_text(encoding="utf-8")
        self.assertNotRegex(source, r"os\.(?:unlink|rmdir)\(")
        self.prompt("build")
        completed = next(
            (self.repo / ".agentic/codex-prompt-generation").glob("*/completed")
        )
        for index in range(65):
            (completed / f"{index:064x}").mkdir(mode=0o700)
        result = self.prompt("build", expected=1)
        self.assertIn("bounded cap", result.stderr)

    def test_atomic_publication_rejects_cross_filesystem_results(self) -> None:
        module = load_prompt_generator(self.repo)

        class CrossFilesystemLibc:
            def renameatx_np(self, *arguments: object) -> int:
                return -1

            def renameat2(self, *arguments: object) -> int:
                return -1

        root = self.repo / ".codex/prompts"
        dir_fd = os.open(
            root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            with (
                mock.patch.object(
                    module.ctypes,
                    "CDLL",
                    return_value=CrossFilesystemLibc(),
                ),
                mock.patch.object(
                    module.ctypes,
                    "get_errno",
                    return_value=errno.EXDEV,
                ),
            ):
                with self.assertRaisesRegex(
                    module.PromptError,
                    "crossed a filesystem boundary",
                ):
                    module._rename_noreplace(dir_fd, "left", "right")
                with self.assertRaisesRegex(
                    module.PromptError,
                    "crossed a filesystem boundary",
                ):
                    module._rename_exchange(dir_fd, "left", "right")
        finally:
            os.close(dir_fd)

    def test_pending_transaction_conflicts_after_cross_checkout_copy(self) -> None:
        source = self.repo / "content/commands/ds-cross-checkout.md"
        mirror = self.repo / ".codex/commands/ds-cross-checkout.md"
        source.write_text("# cross checkout\n", encoding="utf-8")
        mirror.symlink_to("../../content/commands/ds-cross-checkout.md")
        env = os.environ.copy()
        env["DINOSTACK_PROMPT_FAULT"] = "after-journal"
        self.prompt("build", expected=1, env=env)
        copied = Path(self.temporary.name) / "copied-checkout"
        shutil.copytree(self.repo, copied, symlinks=True)
        before = {
            "prompts": identity_fingerprint(copied / ".codex/prompts"),
            "state": identity_fingerprint(copied / ".codex/prompt-generation-state"),
        }
        result = run_prompts(copied, "build", expected=1)
        self.assertRegex(result.stderr, r"cross-filesystem|foreign pending")
        self.assertEqual(
            before["prompts"],
            identity_fingerprint(copied / ".codex/prompts"),
        )
        self.assertEqual(
            before["state"],
            identity_fingerprint(copied / ".codex/prompt-generation-state"),
        )

    def test_runtime_is_ignored_and_markers_have_no_absolute_paths(self) -> None:
        execute(["git", "init", "-q"], cwd=self.repo)
        result = execute(
            ["git", "check-ignore", "-v", ".agentic/codex-prompt-generation/probe/owner.json"],
            cwd=self.repo,
        )
        self.assertIn("/.agentic/*", result.stdout)
        for path in (
            self.repo / ".codex/prompts/.dinostack-generated-root.json",
            self.repo / ".codex/prompt-generation-state/.dinostack-generated-state.json",
            self.repo / ".codex/prompt-generation-state/manifest.json",
        ):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(str(self.repo), text)
            self.assertNotIn(str(Path.home()), text)


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
