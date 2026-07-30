#!/usr/bin/env python3
"""
Tests for bin/agentic-migrate.

Uses subprocess to invoke the binary so behaviour matches real CLI usage.
All tests use tmpdir isolation to avoid polluting the real project.
"""

import importlib.machinery
import importlib.util
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


def _load_agentic_migrate_module():
    """Import bin/agentic-migrate (no .py extension) as a module, for tests
    that assert against its pure functions directly rather than round-tripping
    through a subprocess."""
    loader = importlib.machinery.SourceFileLoader("agentic_migrate_under_test", BIN)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


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

        # Audit line lands in the scaffolding-notices SHARD, not in context.md.
        # DS-107: context.md is a derived rollup recomposed from _wrap.md plus
        # .agentic/context.d/*.md on every Stop turn, so the old append-to-
        # context.md target was destroyed by the very next turn.
        ctx = (self.project / ".agentic" / "context.d" / "scaffolding-notices.md").read_text()
        self.assertIn(f"[scaffolding-sync] Applied v0 -> v{expected_version}", ctx)
        # And it must NOT be written to the derived rollup.
        self.assertFalse((self.project / ".agentic" / "context.md").exists())

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
        ctx_path = self.project / ".agentic" / "context.d" / "scaffolding-notices.md"
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
    """Manifest not found: warning appended to the notices shard, sentinel created, exit 0."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.nonexistent = "/nonexistent/path/project-scaffolding.yml"

    def test_warning_appended(self):
        # Pass --manifest explicitly so all three fallback candidates are bypassed
        result = run(
            ["apply", "--manifest", self.nonexistent, "--project-root", self.tmp],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        ctx_path = Path(self.tmp) / ".agentic" / "context.d" / "scaffolding-notices.md"
        self.assertTrue(ctx_path.exists())
        ctx = ctx_path.read_text()
        self.assertIn("[scaffolding-sync] WARNING: manifest not found", ctx)
        # The derived rollup is never appended to directly.
        self.assertFalse((Path(self.tmp) / ".agentic" / "context.md").exists())

    def test_no_duplicate_warning(self):
        # Run twice with explicit nonexistent manifest
        run(["apply", "--manifest", self.nonexistent, "--project-root", self.tmp])
        run(["apply", "--manifest", self.nonexistent, "--project-root", self.tmp])

        ctx_path = Path(self.tmp) / ".agentic" / "context.d" / "scaffolding-notices.md"
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


class TestGitignoreUmbrellaAboveExistingNegation(unittest.TestCase):
    """Regression: git .gitignore matching is last-match-wins - a `!.agentic/...`
    negation only works if it comes AFTER the umbrella pattern it overrides. When
    a project's .gitignore already has negations (seeded by /ds-init-project Step
    9, which predates any umbrella) and `apply` later adds the `.agentic/*`
    umbrella, the umbrella must land ABOVE the existing negations, not at EOF."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project = Path(self.tmp)
        agentic = self.project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({"debugger_on_failure": False}) + "\n")

        # Simulate the pre-umbrella state: Step 9 negations exist, no umbrella yet.
        self.gitignore_path = self.project / ".gitignore"
        self.gitignore_path.write_text(
            "node_modules/\n"
            "!.agentic/session-log/\n"
            "!.agentic/learnings.md\n"
            "!.agentic/qa.md\n"
            "!.agentic/deploy.md\n"
            "!.agentic/tracking.md\n"
            "!.agentic/qa-regressions.md\n"
            "!.agentic/config.json\n"
        )
        subprocess.run(["git", "init", "-q"], cwd=str(self.project), check=True)

    def test_umbrella_lands_above_negation_and_negation_still_wins(self):
        result = run(["apply", "--manifest", MANIFEST, "--project-root", str(self.project)])
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        lines = self.gitignore_path.read_text(encoding="utf-8").splitlines()
        self.assertIn(".agentic/*", lines, "umbrella pattern must have been added")
        umbrella_idx = lines.index(".agentic/*")
        negation_idx = next(i for i, l in enumerate(lines) if l.strip() == "!.agentic/qa.md")
        self.assertLess(
            umbrella_idx, negation_idx,
            "umbrella must be inserted ABOVE the existing negation, not appended at EOF",
        )

        # Behavioral proof: qa.md must NOT be ignored (negation wins because it
        # now follows the umbrella). Real git, not string matching.
        check = subprocess.run(
            ["git", "check-ignore", "-q", ".agentic/qa.md"],
            cwd=str(self.project),
        )
        self.assertNotEqual(
            check.returncode, 0,
            "qa.md must NOT be git-ignored once the umbrella is correctly ordered",
        )

        # Unrelated pre-existing line must be untouched.
        self.assertIn("node_modules/", lines)

    def test_apply_is_idempotent_no_duplicate_umbrella(self):
        r1 = run(["apply", "--manifest", MANIFEST, "--project-root", str(self.project)])
        self.assertEqual(r1.returncode, 0, msg=r1.stderr)
        first_content = self.gitignore_path.read_text(encoding="utf-8")

        r2 = run(["apply", "--manifest", MANIFEST, "--project-root", str(self.project)])
        self.assertEqual(r2.returncode, 0, msg=r2.stderr)
        second_content = self.gitignore_path.read_text(encoding="utf-8")

        lines = second_content.splitlines()
        umbrella_count = sum(1 for l in lines if l.strip() == ".agentic/*")
        self.assertEqual(umbrella_count, 1, "second apply must not duplicate the umbrella pattern")
        self.assertEqual(
            first_content, second_content,
            "a no-op second apply must not change .gitignore content at all",
        )


class TestGitignoreUmbrellaAppendsWhenNoExistingNegation(unittest.TestCase):
    """The no-existing-negation case must behave exactly as before: append at EOF."""

    def test_umbrella_appended_at_eof_when_no_negation_present(self):
        tmp = tempfile.mkdtemp()
        project = Path(tmp)
        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({"debugger_on_failure": False}) + "\n")
        gitignore_path = project / ".gitignore"
        gitignore_path.write_text("node_modules/\n.env\n")

        result = run(["apply", "--manifest", MANIFEST, "--project-root", str(project)])
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        self.assertIn(".agentic/*", lines)
        umbrella_idx = lines.index(".agentic/*")
        # No negation existed, so the umbrella must be appended after the
        # original two lines (their relative order untouched), not inserted
        # somewhere in the middle.
        self.assertEqual(lines[0], "node_modules/")
        self.assertEqual(lines[1], ".env")
        self.assertGreaterEqual(umbrella_idx, 2)


class TestInitProjectStep9NegationBlock(unittest.TestCase):
    """content/commands/ds-init-project.md Step 9's .agentic/ gitignore block must
    emit a `!.agentic/<file>` negation for every tracked config file it claims to
    carve out, and must not duplicate `!.agentic/learnings.md`."""

    STEP9_PATH = REPO_ROOT / "content" / "commands" / "ds-init-project.md"

    def _step9_block(self) -> str:
        text = self.STEP9_PATH.read_text(encoding="utf-8")
        start = text.index("# Agentic engineering runtime artifacts")
        end = text.index("```", start)
        return text[start:end]

    def test_all_expected_negations_present_exactly_once(self):
        block = self._step9_block()
        expected = [
            "!.agentic/session-log/",
            "!.agentic/learnings.md",
            "!.agentic/qa.md",
            "!.agentic/deploy.md",
            "!.agentic/tracking.md",
            "!.agentic/qa-regressions.md",
            "!.agentic/config.json",
        ]
        for negation in expected:
            occurrences = block.count(negation)
            self.assertEqual(
                occurrences, 1,
                f"{negation} must appear exactly once in the Step 9 block, found {occurrences}",
            )

    def test_preferences_json_is_not_negated(self):
        """preferences.json is deliberately ignored (per-developer runtime state)
        and must never be carved out of the umbrella."""
        block = self._step9_block()
        self.assertNotIn("!.agentic/preferences.json", block)
        self.assertIn(".agentic/preferences.json", block)




class TestGitignoreInsertByteBehavior(unittest.TestCase):
    """Major 1 regression: the insert-above-negation branch of
    _append_gitignore must be byte-preserving. Before the fix it read via
    Path.read_text().splitlines() (universal-newline translation strips CR)
    and rewrote the whole file with "\\n".join(...) + "\\n", silently
    converting every CRLF line ending to LF and gratuitously terminating a
    file that previously had no trailing newline.

    Both assertions below use a minimal single-pattern manifest so the insert
    branch fires exactly once and no subsequent append (which is LF-only by
    design, matching pre-existing behavior) can obscure what the insert
    branch itself did.
    """

    def _single_umbrella_manifest(self, tmp):
        manifest_text = """
scaffolding_version: 1
gitignore:
  - pattern: ".agentic/*"
    purpose: "umbrella ignore"
files: []
markers: []
"""
        manifest_path = Path(tmp) / "test-manifest.yml"
        manifest_path.write_text(manifest_text)
        return manifest_path

    def test_cr_byte_count_preserved_through_insert(self):
        tmp = tempfile.mkdtemp()
        project = Path(tmp)
        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({}) + "\n")
        manifest_path = self._single_umbrella_manifest(tmp)

        gitignore_path = project / ".gitignore"
        raw = b"node_modules/\r\n!.agentic/qa.md\r\n"
        gitignore_path.write_bytes(raw)
        original_cr_count = raw.count(b"\r")

        result = run(["apply", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        after = gitignore_path.read_bytes()
        # The two original lines keep their CR; the newly inserted umbrella
        # line reuses the negation line's CRLF terminator, adding exactly one
        # more. No other CR should appear or disappear.
        self.assertEqual(
            after.count(b"\r"), original_cr_count + 1,
            f"CR bytes not preserved: before={original_cr_count} after={after!r}",
        )
        lines = after.split(b"\r\n")
        self.assertIn(b".agentic/*", lines)
        self.assertLess(
            lines.index(b".agentic/*"), lines.index(b"!.agentic/qa.md"),
            "umbrella must land above the negation",
        )

    def test_insert_does_not_add_trailing_newline_to_untouched_last_line(self):
        tmp = tempfile.mkdtemp()
        project = Path(tmp)
        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({}) + "\n")
        manifest_path = self._single_umbrella_manifest(tmp)

        gitignore_path = project / ".gitignore"
        # Negation line first (triggers the insert), then a final line with NO
        # trailing newline. The insert happens above line 0; line 1 (the
        # terminator-less last line) must be left byte-for-byte untouched.
        raw = b"!.agentic/qa.md\nnode_modules"
        gitignore_path.write_bytes(raw)

        result = run(["apply", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        after = gitignore_path.read_bytes()
        self.assertFalse(
            after.endswith(b"\n"),
            f"insert path gratuitously terminated a file with no trailing newline: {after!r}",
        )
        self.assertEqual(after, b".agentic/*\n!.agentic/qa.md\nnode_modules")


class TestUmbrellaRegexTightening(unittest.TestCase):
    """Minor 1: the umbrella regex must recognize `.agentic/**/*` (previously
    missed - would append at EOF and defeat negations) and must NOT treat a
    bare `.agentic/` directory-ignore as a negatable umbrella (git will not
    descend into an excluded directory at all, so no ordering fix can help
    it)."""

    def setUp(self):
        self.mod = _load_agentic_migrate_module()

    def test_deep_glob_recognized_as_umbrella(self):
        self.assertTrue(self.mod._is_agentic_umbrella_pattern(".agentic/**/*"))
        self.assertTrue(self.mod._is_agentic_umbrella_pattern(".agentic/*"))
        self.assertTrue(self.mod._is_agentic_umbrella_pattern(".agentic/**"))
        self.assertTrue(self.mod._is_agentic_umbrella_pattern("**/.agentic/**/*"))

    def test_bare_directory_forms_are_not_umbrella_patterns(self):
        for bare in (".agentic", ".agentic/", "/.agentic", "/.agentic/", "**/.agentic"):
            self.assertFalse(
                self.mod._is_agentic_umbrella_pattern(bare),
                f"{bare!r} must NOT be treated as a negatable umbrella pattern",
            )

    def test_bare_form_rewrite_targets(self):
        self.assertEqual(self.mod._normalize_bare_agentic_pattern(".agentic"), ".agentic/*")
        self.assertEqual(self.mod._normalize_bare_agentic_pattern(".agentic/"), ".agentic/*")
        self.assertEqual(self.mod._normalize_bare_agentic_pattern("/.agentic/"), "/.agentic/*")
        self.assertEqual(self.mod._normalize_bare_agentic_pattern("**/.agentic"), "**/.agentic/*")
        self.assertIsNone(self.mod._normalize_bare_agentic_pattern(".agentic/*"))
        self.assertIsNone(self.mod._normalize_bare_agentic_pattern(".agentic/qa.md"))


class TestBareUmbrellaRewriteEndToEnd(unittest.TestCase):
    """Minor 1, end-to-end: a bare-form manifest pattern must be rewritten
    (with a visible stderr warning) rather than silently inserted verbatim,
    where it would be permanently unnegatable."""

    def test_bare_pattern_rewritten_via_apply(self):
        tmp = tempfile.mkdtemp()
        project = Path(tmp)
        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({}) + "\n")
        (project / ".gitignore").write_text("!.agentic/qa.md\n")

        manifest_text = """
scaffolding_version: 1
gitignore:
  - pattern: ".agentic"
    purpose: "intentionally bare form for regression coverage"
files: []
markers: []
"""
        manifest_path = Path(tmp) / "test-manifest.yml"
        manifest_path.write_text(manifest_text)

        result = run(["apply", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(
            "rewriting bare .agentic/ ignore pattern", result.stderr,
            "bare-form rewrite must emit a visible warning",
        )

        lines = (project / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".agentic/*", lines, "bare pattern must be rewritten to .agentic/*")
        self.assertNotIn(".agentic", lines, "bare form must never be written verbatim")
        self.assertLess(
            lines.index(".agentic/*"), lines.index("!.agentic/qa.md"),
            "rewritten umbrella must still land above the existing negation",
        )



class TestOrderAwareCheckAndRepair(unittest.TestCase):
    """Major 3 regression: `check`/`diff` must detect ordering drift even
    when every individual pattern is textually present (the old presence-only
    logic reported no drift forever once the umbrella existed anywhere in the
    file), and `apply` must repair a misordered file and be idempotent."""

    def _misordered_project(self, tmp):
        project = Path(tmp) / "project"
        project.mkdir()
        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({"scaffolding_version": 1}) + "\n")
        gitignore_path = project / ".gitignore"
        # Umbrella BELOW the negation - the broken ordering that silently
        # defeats the negation (see bin/agentic-migrate _append_gitignore).
        gitignore_path.write_text("!.agentic/qa.md\n.agentic/*\n")
        subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)
        return project, gitignore_path

    def _custom_manifest(self, tmp):
        manifest_text = """
scaffolding_version: 1
gitignore:
  - pattern: ".agentic/*"
    purpose: "umbrella ignore"
  - pattern: "!.agentic/qa.md"
    purpose: "committed"
files: []
markers: []
"""
        manifest_path = Path(tmp) / "test-manifest.yml"
        manifest_path.write_text(manifest_text)
        return manifest_path

    def test_check_reports_drift_on_misordered_file_even_at_current_version(self):
        tmp = tempfile.mkdtemp()
        project, _ = self._misordered_project(tmp)
        manifest_path = self._custom_manifest(tmp)

        result = run(["check", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(result.returncode, 1, msg=result.stdout)
        out = json.loads(result.stdout)
        self.assertEqual(out["status"], "drift")
        self.assertTrue(out["gitignore_misordered"])

    def test_diff_reports_ordering_issue(self):
        tmp = tempfile.mkdtemp()
        project, _ = self._misordered_project(tmp)
        manifest_path = self._custom_manifest(tmp)

        result = run(["diff", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("ordering issue", result.stdout)

    def test_apply_repairs_ordering_and_is_idempotent(self):
        tmp = tempfile.mkdtemp()
        project, gitignore_path = self._misordered_project(tmp)
        manifest_path = self._custom_manifest(tmp)

        r1 = run(["apply", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(r1.returncode, 0, msg=r1.stderr)

        lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            lines, [".agentic/*", "!.agentic/qa.md"],
            "umbrella must be moved above the negation, no other reordering",
        )

        # Real git proof: qa.md must not be ignored now that ordering is fixed.
        check = subprocess.run(["git", "check-ignore", "-q", ".agentic/qa.md"], cwd=str(project))
        self.assertNotEqual(check.returncode, 0, "qa.md must not be git-ignored after repair")

        # check must now report ok (version already current; ordering fixed).
        check_result = run(["check", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(check_result.returncode, 0, msg=check_result.stdout)

        # Idempotent: a second apply makes no further byte-level changes.
        first_content = gitignore_path.read_bytes()
        r2 = run(["apply", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(r2.returncode, 0, msg=r2.stderr)
        second_content = gitignore_path.read_bytes()
        self.assertEqual(first_content, second_content, "second apply must be a true no-op")



if __name__ == "__main__":
    unittest.main(verbosity=2)
