#!/usr/bin/env python3
"""
Tests for bin/agentic-migrate.

Uses subprocess to invoke the binary so behaviour matches real CLI usage.
All tests use tmpdir isolation to avoid polluting the real project.
"""

import json
import os
import re
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


def _manifest_version() -> int:
    """Read scaffolding_version from the canonical manifest. Mirrors the regex
    used by bin/agentic-migrate._load_manifest so the test always tracks the
    real source of truth without hardcoding a version integer."""
    text = Path(MANIFEST).read_text(encoding="utf-8")
    m = re.search(r'^scaffolding_version:\s*(\d+)', text, re.MULTILINE)
    if not m:
        raise RuntimeError(f"scaffolding_version not found in {MANIFEST}")
    return int(m.group(1))


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
        expected_version = _manifest_version()
        self.assertEqual(data["scaffolding_version"], expected_version)

        # audit line in context.md
        ctx = (self.project / ".agentic" / "context.md").read_text()
        self.assertIn(f"[scaffolding-sync] Applied v0 -> v{expected_version}", ctx)

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

        # Write .gitignore with ALL patterns from the current manifest already present.
        # Read them dynamically so this list stays in sync with future manifest bumps.
        import re as _re
        _manifest_text = Path(MANIFEST).read_text(encoding="utf-8")
        patterns = _re.findall(r'- pattern:\s*"([^"]+)"', _manifest_text)
        (self.project / ".gitignore").write_text("\n".join(patterns) + "\n")

        # Seed all files listed in the manifest so apply finds nothing to write
        # and correctly skips the audit line.
        file_paths = _re.findall(r'- path:\s*"([^"]+)"', _manifest_text)
        for rel_path in file_paths:
            target = self.project / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text("")

    def test_no_audit_line_when_all_present(self):
        result = run(
            ["apply", "--manifest", MANIFEST, "--project-root", str(self.project)],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        # stamp should be updated
        data = json.loads((self.project / ".agentic" / "config.json").read_text())
        self.assertEqual(data["scaffolding_version"], _manifest_version())

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


class TestGitignoreNoTrailingNewline(unittest.TestCase):
    """Regression: .gitignore with no trailing newline must not fuse new pattern onto last line."""

    def test_no_trailing_newline_corruption(self):
        tmp = tempfile.mkdtemp()
        project = Path(tmp)
        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({"debugger_on_failure": False}) + "\n")

        # Write .gitignore WITHOUT a trailing newline - raw bytes to guarantee no \n at end
        gitignore_path = project / ".gitignore"
        gitignore_path.write_bytes(b"node_modules")

        result = run(
            ["apply", "--manifest", MANIFEST, "--project-root", str(project)],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        content = gitignore_path.read_text(encoding="utf-8")

        # Original line must be intact on its own line
        lines = content.splitlines()
        self.assertIn("node_modules", lines, "node_modules line must survive intact")

        # New pattern must appear on its own line (not fused onto node_modules)
        self.assertIn(".agentic/*", lines, ".agentic/* must be on its own line")

        # Sanity: the fused form must NOT exist
        self.assertNotIn("node_modules.agentic", content, "pattern fusion detected")
        self.assertNotIn("node_modules!", content, "pattern fusion detected")

        # File must end with a newline (proper hygiene)
        self.assertTrue(
            gitignore_path.read_bytes().endswith(b"\n"),
            ".gitignore must end with a newline after apply",
        )


class TestMalformedConfigJson(unittest.TestCase):
    """Malformed .agentic/config.json: apply must not crash or clobber the file."""

    def test_malformed_config_json_not_touched(self):
        tmp = tempfile.mkdtemp()
        project = Path(tmp)
        agentic = project / ".agentic"
        agentic.mkdir()

        bad_json = "{ not valid json"
        (agentic / "config.json").write_text(bad_json)
        (project / ".gitignore").write_text("")

        result = run(
            ["apply", "--manifest", MANIFEST, "--project-root", str(project)],
        )
        # Must not crash (exit codes 0 or 3 are both acceptable; 2 would mean manifest error)
        self.assertIn(result.returncode, (0, 3), msg=f"Unexpected exit code: {result.returncode}\n{result.stderr}")

        # The malformed config.json must be left alone (not clobbered with valid JSON)
        actual = (agentic / "config.json").read_text()
        self.assertEqual(actual, bad_json, "Malformed config.json must not be overwritten")


class TestPartialApplyExitCode(unittest.TestCase):
    """Missing seed file -> exit 3 (partial apply); gitignore patterns still applied;
    scaffolding_version NOT stamped."""

    def test_partial_apply_exit_code(self):
        tmp = tempfile.mkdtemp()
        project = Path(tmp)
        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({"debugger_on_failure": False}) + "\n")
        (project / ".gitignore").write_text("")

        # Manifest with a gitignore rule (will succeed) and a file rule pointing
        # to a non-existent seed (will fail).
        manifest_text = """
scaffolding_version: 1
gitignore:
  - pattern: ".agentic/*"
    purpose: "umbrella ignore"
files:
  - path: ".agentic/missing-seed-target.json"
    seed: "templates/does-not-exist.json"
    purpose: "intentionally missing seed"
markers: []
"""
        manifest_path = Path(tmp) / "test-manifest.yml"
        manifest_path.write_text(manifest_text)

        result = run(
            ["apply", "--manifest", str(manifest_path), "--project-root", str(project)],
        )

        # 1. Exit code must be 3 (partial apply)
        self.assertEqual(result.returncode, 3, msg=f"Expected exit 3, got {result.returncode}\n{result.stderr}")

        # 2. The gitignore pattern was still applied
        gi = (project / ".gitignore").read_text()
        self.assertIn(".agentic/*", gi, "Gitignore pattern must be applied even on partial apply")

        # 3. scaffolding_version must NOT be stamped (not all rules satisfied)
        data = json.loads((agentic / "config.json").read_text())
        self.assertNotEqual(
            data.get("scaffolding_version"), 1,
            "scaffolding_version must not be stamped on partial apply",
        )

        # 4. No crash (result.returncode already checked above)


class TestPathTraversalGuard(unittest.TestCase):
    """Manifest entries with traversal paths must not write outside project_root; exit 3."""

    def _make_fixture(self):
        """Return (tmp, project, manifest_dir) with a minimal project scaffold."""
        tmp = tempfile.mkdtemp()
        project = Path(tmp) / "project"
        project.mkdir()
        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({"debugger_on_failure": False}) + "\n")
        (project / ".gitignore").write_text("")
        manifest_dir = Path(tmp)
        (manifest_dir / "innocent.json").write_text("{}\n")
        return tmp, project, manifest_dir

    def test_relative_traversal_blocked(self):
        """../escape.txt must not be written outside project_root."""
        tmp, project, manifest_dir = self._make_fixture()

        manifest_text = """
scaffolding_version: 1
gitignore: []
files:
  - path: "../escape.txt"
    seed: "innocent.json"
    purpose: "relative traversal attempt"
markers: []
"""
        manifest_path = manifest_dir / "traversal-manifest.yml"
        manifest_path.write_text(manifest_text)

        result = run(
            ["apply", "--manifest", str(manifest_path), "--project-root", str(project)],
        )

        self.assertEqual(result.returncode, 3, msg=f"Expected exit 3, got {result.returncode}\n{result.stderr}")
        escaped = project.parent / "escape.txt"
        self.assertFalse(escaped.exists(), "Traversal target must not be written outside project_root")
        self.assertIn("escape.txt", result.stderr, "stderr must mention the offending path")

    def test_absolute_path_blocked(self):
        """An absolute path outside project_root must not be written."""
        tmp, project, manifest_dir = self._make_fixture()

        # Use a predictable temp path that is clearly outside project
        import tempfile as _tf
        target_dir = Path(_tf.mkdtemp())
        absolute_target = str(target_dir / "agentic-escape-test.txt")

        manifest_text = f"""
scaffolding_version: 1
gitignore: []
files:
  - path: "{absolute_target}"
    seed: "innocent.json"
    purpose: "absolute path attack"
markers: []
"""
        manifest_path = manifest_dir / "absolute-manifest.yml"
        manifest_path.write_text(manifest_text)

        result = run(
            ["apply", "--manifest", str(manifest_path), "--project-root", str(project)],
        )

        self.assertEqual(result.returncode, 3, msg=f"Expected exit 3, got {result.returncode}\n{result.stderr}")
        self.assertFalse(
            Path(absolute_target).exists(),
            "Absolute out-of-root target must not be written",
        )
        self.assertIn("agentic-escape-test.txt", result.stderr, "stderr must mention the offending path")


if __name__ == "__main__":
    unittest.main(verbosity=2)
