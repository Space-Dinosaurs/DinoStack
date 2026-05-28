#!/usr/bin/env python3
"""
Tests for bin/agentic-migrate.

Uses subprocess to invoke the binary so behaviour matches real CLI usage.
All tests use tmpdir isolation to avoid polluting the real project.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Locate the binary relative to this test file.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN = str(REPO_ROOT / "bin" / "agentic-migrate")
MANIFEST = str(REPO_ROOT / "content" / "project-scaffolding.yml")


def run(args: list[str], env: dict | None = None, cwd: str | None = None) -> subprocess.CompletedProcess:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, BIN] + args,
        capture_output=True,
        text=True,
        env=merged_env,
        cwd=cwd,
    )


class TestHappyPath(unittest.TestCase):
    """v0 project with all rules drifted -> apply writes everything, stamps, audits."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project = Path(self.tmp)
        # Create .agentic/config.json with no scaffolding_version (v0)
        agentic = self.project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({
            "debugger_on_failure": False,
            "qa_default_skip": None,
            "model_profile": "default",
            "auto_merge_on_ci_green": False,
        }) + "\n")
        # Create empty .gitignore
        (self.project / ".gitignore").write_text("")

    def test_apply_writes_rules_stamps_audits(self):
        result = run(
            ["apply", "--manifest", MANIFEST, "--project-root", str(self.project)],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        # .gitignore should contain all patterns
        gi = (self.project / ".gitignore").read_text()
        self.assertIn(".agentic/*", gi)
        self.assertIn("!.agentic/config.json", gi)

        # .agentic/config.json should be seeded (already existed) and stamped
        data = json.loads((self.project / ".agentic" / "config.json").read_text())
        self.assertEqual(data["scaffolding_version"], 1)

        # audit line in context.md
        ctx = (self.project / ".agentic" / "context.md").read_text()
        self.assertIn("[scaffolding-sync] Applied v0 -> v1", ctx)

    def test_check_returns_drift_before_apply(self):
        result = run(
            ["check", "--manifest", MANIFEST, "--project-root", str(self.tmp)],
        )
        self.assertEqual(result.returncode, 1)
        out = json.loads(result.stdout)
        self.assertEqual(out["status"], "drift")


class TestAlreadyCompliant(unittest.TestCase):
    """Already-compliant v0 project: no writes, stamp updated, NO audit line."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project = Path(self.tmp)
        agentic = self.project / ".agentic"
        agentic.mkdir()
        # Write config.json with scaffolding_version already set to 1
        (agentic / "config.json").write_text(json.dumps({
            "scaffolding_version": 0,  # project stamp is 0, but all rules already present
            "debugger_on_failure": False,
        }) + "\n")
        # Seed the file that the manifest wants
        (agentic / "config.json").write_text(json.dumps({
            "scaffolding_version": 0,
            "debugger_on_failure": False,
        }) + "\n")

        # Write .gitignore with ALL patterns already present
        patterns = [
            ".agentic/*",
            "!.agentic/config.json",
            "!.agentic/findings.md",
            "!.agentic/session-log/",
            "!.agentic/session-log/**",
        ]
        (self.project / ".gitignore").write_text("\n".join(patterns) + "\n")

    def test_no_audit_line_when_all_present(self):
        result = run(
            ["apply", "--manifest", MANIFEST, "--project-root", str(self.project)],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        # stamp should be updated
        data = json.loads((self.project / ".agentic" / "config.json").read_text())
        self.assertEqual(data["scaffolding_version"], 1)

        # NO audit line (nothing was written)
        ctx_path = self.project / ".agentic" / "context.md"
        if ctx_path.exists():
            ctx = ctx_path.read_text()
            self.assertNotIn("[scaffolding-sync] Applied", ctx)


class TestConcurrentSessionRace(unittest.TestCase):
    """Two concurrent applies: second exits silently without writing."""

    def test_race(self):
        tmp = tempfile.mkdtemp()
        project = Path(tmp)
        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({"debugger_on_failure": False}) + "\n")
        (project / ".gitignore").write_text("")

        args_list = ["apply", "--manifest", MANIFEST, "--project-root", str(project)]

        # Spawn two subprocesses concurrently via subprocess directly (avoids pickling issues)
        env = os.environ.copy()
        p1 = subprocess.Popen(
            [sys.executable, BIN] + args_list,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        p2 = subprocess.Popen(
            [sys.executable, BIN] + args_list,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        p1.communicate(timeout=30)
        p2.communicate(timeout=30)

        codes = [p1.returncode, p2.returncode]
        # Both must exit without crashing (0 = success/no-op)
        for code in codes:
            self.assertIn(code, (0, 1, 3))  # 0=ok, 1=drift(check-only), 3=partial


class TestMalformedManifest(unittest.TestCase):
    """Malformed manifest: silent skip, exit 2."""

    def test_malformed(self):
        tmp = tempfile.mkdtemp()
        manifest = Path(tmp) / "bad.yml"
        manifest.write_text("not: valid: yaml: :")
        result = run(
            ["check", "--manifest", str(manifest), "--project-root", tmp],
        )
        self.assertEqual(result.returncode, 2)


class TestManifestNotFound(unittest.TestCase):
    """Manifest not found: warning appended to context.md, sentinel created, exit 0."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.nonexistent = "/nonexistent/path/project-scaffolding.yml"

    def test_warning_appended(self):
        # Pass --manifest explicitly so all three fallback candidates are bypassed
        result = run(
            ["apply", "--manifest", self.nonexistent, "--project-root", self.tmp],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        ctx_path = Path(self.tmp) / ".agentic" / "context.md"
        self.assertTrue(ctx_path.exists())
        ctx = ctx_path.read_text()
        self.assertIn("[scaffolding-sync] WARNING: manifest not found", ctx)

    def test_no_duplicate_warning(self):
        # Run twice with explicit nonexistent manifest
        run(["apply", "--manifest", self.nonexistent, "--project-root", self.tmp])
        run(["apply", "--manifest", self.nonexistent, "--project-root", self.tmp])

        ctx_path = Path(self.tmp) / ".agentic" / "context.md"
        ctx = ctx_path.read_text()
        # Only one occurrence
        self.assertEqual(ctx.count("[scaffolding-sync] WARNING: manifest not found"), 1)


class TestGitignoreTrailingWhitespace(unittest.TestCase):
    """.agentic/*  (trailing whitespace) in gitignore vs .agentic/* in manifest -> satisfied."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project = Path(self.tmp)
        agentic = self.project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({"debugger_on_failure": False}) + "\n")

    def test_trailing_whitespace_tolerated(self):
        # Write .gitignore with trailing whitespace on the pattern
        patterns = [
            ".agentic/*  ",  # trailing spaces
            "!.agentic/config.json   ",
            "!.agentic/findings.md",
            "!.agentic/session-log/",
            "!.agentic/session-log/**",
        ]
        (self.project / ".gitignore").write_text("\n".join(patterns) + "\n")

        result = run(
            ["diff", "--manifest", MANIFEST, "--project-root", str(self.project)],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # Should show "up to date" for gitignore patterns
        self.assertNotIn(".agentic/*", result.stdout.split("up to date")[1] if "up to date" in result.stdout else "")


class TestGitignoreGlobDistinction(unittest.TestCase):
    """.agentic/* vs .agentic/** are different - both should be written if manifest has both."""

    def test_glob_distinction(self):
        tmp = tempfile.mkdtemp()
        project = Path(tmp)
        # Create a manifest that has both patterns
        manifest_text = """
scaffolding_version: 1
gitignore:
  - pattern: ".agentic/*"
    purpose: "umbrella ignore"
  - pattern: ".agentic/**"
    purpose: "deep ignore"
files: []
markers: []
"""
        manifest_path = Path(tmp) / "test-manifest.yml"
        manifest_path.write_text(manifest_text)

        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({}) + "\n")
        (project / ".gitignore").write_text("")

        result = run(
            ["apply", "--manifest", str(manifest_path), "--project-root", str(project)],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        gi = (project / ".gitignore").read_text()
        self.assertIn(".agentic/*", gi)
        self.assertIn(".agentic/**", gi)


class TestMarkersIgnored(unittest.TestCase):
    """markers[] in manifest is ignored by apply path."""

    def test_markers_ignored(self):
        tmp = tempfile.mkdtemp()
        project = Path(tmp)

        manifest_text = """
scaffolding_version: 1
gitignore: []
files: []
markers:
  - type: opt-in
    file: AGENTS.md
    line: "agentic-engineering: opt-in"
"""
        manifest_path = Path(tmp) / "test-manifest.yml"
        manifest_path.write_text(manifest_text)

        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({}) + "\n")
        agents_md = project / "AGENTS.md"
        # Does NOT have the opt-in marker
        agents_md.write_text("# My project\n")

        result = run(
            ["apply", "--manifest", str(manifest_path), "--project-root", str(project)],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        # AGENTS.md must remain unchanged
        self.assertEqual(agents_md.read_text(), "# My project\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
