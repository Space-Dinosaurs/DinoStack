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


class TestInitProjectStep9SingleSourced(unittest.TestCase):
    """Round 3 rework (Major B): `/ds-init-project` Step 9 no longer hand-copies
    a second `.gitignore` denylist. It literally delegates the `.agentic/`
    portion of a fresh project's `.gitignore` to `ds-migrate apply` against
    THIS repo's canonical manifest (`content/project-scaffolding.yml`), so
    the init route and the migrate route read from one source and cannot
    diverge by construction - a divergence class like `phase0-classifiers.yml`
    (tracked on init, ignored on migrate) or `.activated` is now structurally
    impossible for any path the manifest already knows about. This class
    replaces the prior round's outcome-COMPARISON gate (which compared two
    independently-maintained lists and was blind to any path outside both)
    with (a) a prose-invariant check that Step 9 actually delegates rather
    than silently reintroducing a duplicate block, and (b) a single-route
    outcome gate against the SAME expanded path set the round-3 Skeptic named
    as previously undecided (Major A) - `TRACKED_KNOWLEDGE_PATHS` and
    `IGNORED_KNOWLEDGE_PATHS` below are each reviewed, rationale-backed
    per-path decisions, not a re-derivation of the manifest's own negation
    list (that would be circular)."""

    STEP9_PATH = REPO_ROOT / "content" / "commands" / "ds-init-project.md"

    def _step9_section(self) -> str:
        text = self.STEP9_PATH.read_text(encoding="utf-8")
        start = text.index("### 9. Create `.gitignore`")
        end = text.index("\n### 10.", start)
        return text[start:end]

    def test_step9_delegates_to_ds_migrate_apply(self):
        """Step 9 must invoke the real binary against the real manifest, not
        hand-copy a second gitignore block. This is the structural fix that
        makes route divergence impossible for any manifest-covered path.

        MAJOR 1 (round 4): anchored on the FENCED EXECUTABLE BLOCK itself,
        not the section's prose as a whole. The round-3 version of this test
        asserted `"ds-migrate apply" in section`, which stayed GREEN when the
        Skeptic replaced the executable block's content with
        `echo 'nothing to do'` - the substring survived in three incidental
        prose mentions elsewhere in the same section (the "This is the SAME
        command..." paragraph, the "`ds-migrate apply` is:" bullet intro, and
        the "seeds `.agentic/config.json`..." bullet). Finding exactly one
        fenced block whose own content is the literal invocation closes that
        gap - see the mutation proof in the round-4 rework return."""
        section = self._step9_section()
        fences = re.findall(r"```\n(.*?)```", section, re.DOTALL)
        executable_fences = [f for f in fences if f.strip().startswith("ds-migrate apply")]
        self.assertEqual(
            len(executable_fences), 1,
            "Step 9 must contain exactly one fenced block whose content IS "
            "the literal `ds-migrate apply` invocation (not merely a prose "
            f"mention elsewhere in the section); found {len(executable_fences)}.",
        )
        self.assertIn("--project-root", executable_fences[0])
        self.assertIn("content/project-scaffolding.yml", section)

    def test_step9_no_longer_hand_lists_agentic_ignore_patterns(self):
        """Round-1/round-2 regression guard: Step 9 must not regain a literal,
        hand-copied `.agentic/<file>` ignore-pattern list - that is exactly
        the second hand-maintained copy this rework eliminates. A handful of
        prose mentions of specific paths (in the "deliberately excluded"
        rationale paragraph) is fine; a fenced code block enumerating many
        bare `.agentic/<path>` ignore lines is not."""
        section = self._step9_section()
        # The old block had 40+ literal ignore-pattern lines inside a single
        # fenced code block. Assert no fenced block in the Step 9 section
        # contains more than a handful of ".agentic/" line-starts - a loose
        # but effective guard against the block's reintroduction.
        for fence_match in re.finditer(r"```\n(.*?)```", section, re.DOTALL):
            body = fence_match.group(1)
            agentic_lines = [
                ln for ln in body.splitlines()
                if ln.strip().startswith(".agentic/") or ln.strip().startswith("!.agentic/")
            ]
            self.assertLess(
                len(agentic_lines), 5,
                f"Step 9 contains a fenced block with {len(agentic_lines)} literal "
                ".agentic/ ignore-pattern lines - this looks like the hand-copied "
                "denylist block being reintroduced instead of delegating to "
                "`ds-migrate apply`.",
            )

    # Reviewed per-path decisions for the 8 paths the round-2 Skeptic found
    # committed-by-default on the (then denylist-shaped) init route with no
    # documented rationale either way (Major A). Under the default-deny
    # umbrella every one of these is IGNORED unless explicitly negated in
    # content/project-scaffolding.yml - so "ignored" here requires no
    # negation, and "tracked" requires one. See content/project-scaffolding.yml
    # v7 and content/commands/ds-init-project.md Step 9's "Deliberately
    # excluded" paragraph for the full rationale text.
    TRACKED_KNOWLEDGE_PATHS = (
        ".agentic/qa.md",
        ".agentic/deploy.md",
        ".agentic/tracking.md",
        ".agentic/qa-regressions.md",
        ".agentic/learnings.md",
        ".agentic/config.json",
        ".agentic/team.yml",
        ".agentic/skill-candidates.md",
        ".agentic/session-log/example-dev.jsonl",
        ".agentic/phase0-classifiers.yml",
        ".agentic/deferred-work.jsonl",
        # Major A: schema (agent/tier/brief_prefix) carries no model handles
        # or other private data - shared team config, tracked like config.json.
        ".agentic/presets.yml",
    )

    # Major A: reviewed and confirmed IGNORED (no negation) - each carries a
    # documented reason distinct from "nobody thought of it yet":
    #   - learnings-agent.session: per-session background-capture tracking
    #     state (content/references/conductor-operating-rules.md).
    #   - findings.md: curated Skeptic-finding patterns, already documented
    #     machine-local (content/references/conventions-detail.md).
    #   - tier-map.yml: maps roles to concrete MODEL NAMES for Codex/Gemini -
    #     same private-model-handle rationale as role-models.yml.
    #   - codex-skill-root-ownership.json: a DinoStack-repo-internal build
    #     safety registry (scripts/codex-skills.py), not project scaffolding.
    #   - tasks.jsonl.<ts>.bak / loop-state-<key>.json.tmp /
    #     knowledge-commit-state.json.tmp: backup/tmp siblings of already-
    #     ignored runtime state - ephemeral by the same logic as the file
    #     they shadow.
    IGNORED_KNOWLEDGE_PATHS = (
        ".agentic/context.md",
        ".agentic/.capability-cache.json",
        ".agentic/.activated",
        ".agentic/learnings-agent.session",
        ".agentic/findings.md",
        ".agentic/tier-map.yml",
        ".agentic/codex-skill-root-ownership.json",
        ".agentic/tasks.jsonl.20260101-000000.bak",
        ".agentic/loop-state-DS-1.json.tmp",
        ".agentic/knowledge-commit-state.json.tmp",
    )

    def _tracked_outcome(self, project: Path) -> dict:
        """git add -A + git status --porcelain, per the Verification section's
        explicit instruction: git check-ignore exit codes are unreliable for
        a negation-only match under an umbrella model (measured, not the
        round-1 commit message's inverted claim) - status after a real `git
        add -A` is the only outcome that actually matches what gets
        committed."""
        all_paths = self.TRACKED_KNOWLEDGE_PATHS + self.IGNORED_KNOWLEDGE_PATHS
        for rel in all_paths:
            target = project / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("placeholder\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(project), check=True)
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(project), check=True, capture_output=True, text=True,
        ).stdout
        staged = set()
        for line in status.splitlines():
            # Porcelain format: "XY <path>"; a newly-added tracked file is "A ".
            staged.add(line[3:])
        outcome = {}
        for rel in all_paths:
            outcome[rel] = "tracked" if rel in staged else "ignored"
        return outcome

    def test_manifest_outcome_matches_reviewed_classification(self):
        """Apply the real manifest via the real binary (exactly what Step 9
        now runs) against a fresh project and confirm every reviewed path
        lands where Major A decided it should. Since Step 9 now delegates to
        this same call, this single-route check covers both adoption paths -
        see test_step9_delegates_to_ds_migrate_apply for the structural half
        of that claim."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".agentic").mkdir()
            (project / ".agentic" / "config.json").write_text(json.dumps({}) + "\n")
            (project / ".gitignore").write_text("")
            subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)
            result = run(["apply", "--manifest", MANIFEST, "--project-root", str(project)])
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            outcome = self._tracked_outcome(project)

        for rel in self.TRACKED_KNOWLEDGE_PATHS:
            self.assertEqual(outcome[rel], "tracked", f"{rel} must be tracked")
        for rel in self.IGNORED_KNOWLEDGE_PATHS:
            self.assertEqual(outcome[rel], "ignored", f"{rel} must be ignored")

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


class TestPreexistingBareAgenticDirectiveRealGit(unittest.TestCase):
    """MAJOR 3 (round 4): a repo that already has a bare `.agentic/`
    directory-ignore line in its `.gitignore` BEFORE dinostack is adopted -
    an entirely natural thing to have hand-written - defeats every
    `!.agentic/<file>` negation `apply` writes, regardless of ordering,
    because git will not descend into an excluded directory at all. Before
    this fix, `apply` returned rc=0, `check` reported `{"status": "ok", ...}`,
    and a real `git add -A` staged ONLY `.gitignore` - every knowledge file
    (qa.md, config.json, learnings.md, team.yml, session-log/) silently never
    got committed. Uses `git add -A` + `git status --porcelain` as the
    oracle, per the Verification section's explicit instruction that
    `git check-ignore` exit codes are unreliable here (measured, not
    trusted)."""

    def _seed_project(self, tmp: str, bare_pattern: str) -> Path:
        project = Path(tmp)
        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({}) + "\n")
        # The hand-written bare form a real pre-existing .gitignore would
        # carry - written BEFORE dinostack ever touches this file.
        (project / ".gitignore").write_text(f"{bare_pattern}\n")
        subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)
        return project

    def test_apply_rewrites_preexisting_bare_form_and_tracks_knowledge_files(self):
        for bare_pattern in (".agentic", ".agentic/", "/.agentic/"):
            with self.subTest(bare_pattern=bare_pattern):
                with tempfile.TemporaryDirectory() as tmp:
                    project = self._seed_project(tmp, bare_pattern)

                    result = run(["apply", "--manifest", MANIFEST, "--project-root", str(project)])
                    self.assertEqual(result.returncode, 0, msg=result.stderr)

                    gi_lines = (project / ".gitignore").read_text(encoding="utf-8").splitlines()
                    self.assertNotIn(bare_pattern, gi_lines, "bare form must be rewritten, not left in place")
                    self.assertIn(".agentic/*", gi_lines, "bare form must be rewritten to the *-suffixed umbrella")

                    # Real oracle: git add -A + git status --porcelain, not
                    # git check-ignore (measured unreliable under
                    # umbrella+negation for a path `git add` accepts).
                    for rel in (".agentic/qa.md", ".agentic/config.json", ".agentic/team.yml"):
                        target = project / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text("placeholder\n", encoding="utf-8")
                    subprocess.run(["git", "add", "-A"], cwd=str(project), check=True)
                    status = subprocess.run(
                        ["git", "status", "--porcelain"],
                        cwd=str(project), check=True, capture_output=True, text=True,
                    ).stdout
                    staged = {line[3:] for line in status.splitlines()}
                    for rel in (".agentic/qa.md", ".agentic/config.json", ".agentic/team.yml"):
                        self.assertIn(
                            rel, staged,
                            f"{rel} must be tracked after apply repairs the bare-form "
                            f"defeater (bare_pattern={bare_pattern!r}); a bare form left "
                            "unrepaired makes every knowledge file silently never commit.",
                        )

    def test_check_reports_drift_not_ok_when_bare_form_present_at_current_version(self):
        """A project already stamped at the manifest's current version, whose
        `.gitignore` nonetheless carries a bare-form defeater (e.g.
        hand-edited after a prior apply, or the pre-adoption .gitignore case
        above at a project that happens to already be stamped), must report
        `status: drift`, never `status: ok` - version currency alone is not
        the postcondition."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            agentic = project / ".agentic"
            agentic.mkdir()
            manifest_version = _manifest_version()
            (agentic / "config.json").write_text(json.dumps({"scaffolding_version": manifest_version}) + "\n")
            (project / ".gitignore").write_text(".agentic/*\n!.agentic/config.json\n.agentic/\n")
            subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)

            result = run(["check", "--manifest", MANIFEST, "--project-root", str(project)])
            out = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1, msg=result.stdout)
            self.assertEqual(out["status"], "drift")
            self.assertTrue(out["gitignore_bare_defeater"])


class TestSessionLogRecursiveNegationNotSilentlyDropped(unittest.TestCase):
    """MAJOR 5 (round 4): the `!.agentic/session-log/**` negation is
    redundant (measured: a plain `!.agentic/session-log/` directory negation
    already recurses into nested files under `.agentic/*` on its own - see
    the corrected prose in content/commands/ds-init-project.md Step 9), but
    "redundant" is not "untested" - before this test, nothing in the suite
    would go red if the manifest's `!.agentic/session-log/**` line were
    silently dropped, because the outcome-parity test in
    TestInitProjectStep9SingleSourced only asserts a top-level
    `.agentic/session-log/example-dev.jsonl` file lands tracked, which the
    single `!.agentic/session-log/` negation already guarantees on its own.
    This test pins the manifest's own second negation line directly, so a
    silent drop is caught here even though the functional outcome for a
    top-level file would not change."""

    def test_manifest_declares_recursive_session_log_negation(self):
        manifest_text = Path(MANIFEST).read_text(encoding="utf-8")
        self.assertIn(
            '- pattern: "!.agentic/session-log/**"',
            manifest_text,
            "content/project-scaffolding.yml must keep the explicit "
            "!.agentic/session-log/** negation even though it is redundant "
            "with !.agentic/session-log/ - it documents nested-file coverage "
            "explicitly. Dropping it silently is a manifest content "
            "regression, not a behavior change to make freely.",
        )


class TestManifestCarveOutsRealGit(unittest.TestCase):
    """Major 2 regression: every tool-agnostic config file the canonical
    manifest declares committed must actually NOT be git-ignored once applied
    - verified against real `git check-ignore`, not string inspection.
    qa.md, deploy.md, and tracking.md were missing their negation entirely."""

    def test_carved_out_files_not_ignored(self):
        tmp = tempfile.mkdtemp()
        project = Path(tmp)
        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({}) + "\n")
        (project / ".gitignore").write_text("")
        subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)

        result = run(["apply", "--manifest", MANIFEST, "--project-root", str(project)])
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        # Derive the expected negation set from the manifest itself (rather
        # than a hardcoded list) so this test cannot go stale the next time a
        # negation is added - Minor 3 regression.
        manifest_text = Path(MANIFEST).read_text(encoding="utf-8")
        negation_patterns = re.findall(r'- pattern:\s*"(!\.agentic/[^"]+)"', manifest_text)
        self.assertTrue(negation_patterns, "manifest must declare at least one negation")

        for pattern in negation_patterns:
            rel = pattern[1:]  # drop leading "!"
            if rel.endswith("/**"):
                # Recursive-glob negation: prove it covers a nested file,
                # since check-ignore cannot be pointed at a glob directly.
                target = rel[: -len("/**")] + "/example-file.txt"
                (project / rel[: -len("/**")]).mkdir(parents=True, exist_ok=True)
            elif rel.endswith("/"):
                # A trailing-slash pattern only matches a real directory -
                # git will not treat a nonexistent path as directory-typed.
                target = rel.rstrip("/")
                (project / target).mkdir(parents=True, exist_ok=True)
            else:
                target = rel
            check = subprocess.run(["git", "check-ignore", "-q", target], cwd=str(project))
            self.assertNotEqual(
                check.returncode, 0,
                f"{target} (from manifest pattern {pattern!r}) must NOT be "
                "git-ignored (manifest negation missing or broken)",
            )

        # Sanity check the negative: an artifact with no negation IS ignored,
        # proving the umbrella itself is doing something (not a vacuous pass).
        check = subprocess.run(["git", "check-ignore", "-q", ".agentic/context.md"], cwd=str(project))
        self.assertEqual(check.returncode, 0, "context.md (no negation) must still be git-ignored")


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


class TestOrderRepairTerminatorlessLastLine(unittest.TestCase):
    """Major A regression: a misordered .agentic/ umbrella that is the
    file's terminator-less LAST line must not fuse with the line it is
    moved above when _repair_gitignore_order relocates it - fusion
    destroys whichever negation shared that line. Also asserts the file's
    original trailing-newline convention (present or absent) is preserved
    rather than silently changed by relocating the terminator-less line."""

    def _manifest(self, tmp):
        manifest_text = """
scaffolding_version: 1
gitignore:
  - pattern: ".agentic/*"
    purpose: "umbrella ignore"
  - pattern: "!.agentic/my-project-notes.md"
    purpose: "project-specific negation"
  - pattern: "!.agentic/config.json"
    purpose: "committed"
files: []
markers: []
"""
        manifest_path = Path(tmp) / "test-manifest.yml"
        manifest_path.write_text(manifest_text)
        return manifest_path

    def test_terminatorless_last_line_umbrella_does_not_fuse(self):
        tmp = tempfile.mkdtemp()
        project = Path(tmp)
        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({"scaffolding_version": 1}) + "\n")
        subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)

        gitignore_path = project / ".gitignore"
        # Umbrella is the file's LAST line, with NO trailing newline - the
        # exact fixture that previously fused it with the negation line it
        # was moved above, destroying the "!.agentic/my-project-notes.md"
        # negation (a user-authored one, not manifest-declared, so the
        # later append loop cannot mask the damage by re-adding it).
        raw = (
            b".agentic/loop-state.json\n"
            b"!.agentic/my-project-notes.md\n"
            b"!.agentic/config.json\n"
            b".agentic/*"
        )
        gitignore_path.write_bytes(raw)

        manifest_path = self._manifest(tmp)
        result = run(["apply", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        after = gitignore_path.read_bytes()

        # The fusion bug produced exactly this garbage line - assert absence.
        self.assertNotIn(b".agentic/*!.agentic/my-project-notes.md", after)

        lines = after.split(b"\n")
        self.assertIn(b".agentic/loop-state.json", lines)
        self.assertIn(b".agentic/*", lines)
        self.assertIn(b"!.agentic/my-project-notes.md", lines)
        self.assertIn(b"!.agentic/config.json", lines)

        # The umbrella must land above BOTH negations.
        umbrella_idx = lines.index(b".agentic/*")
        self.assertLess(umbrella_idx, lines.index(b"!.agentic/my-project-notes.md"))
        self.assertLess(umbrella_idx, lines.index(b"!.agentic/config.json"))

        # Original file had no trailing newline - that convention must be
        # preserved, not silently changed by relocating the terminator-less
        # line elsewhere in the file.
        self.assertFalse(
            after.endswith(b"\n"), f"trailing-newline convention not preserved: {after!r}"
        )

        # Real git proof: the user-authored negation must actually work now,
        # not merely look intact as a string.
        check = subprocess.run(
            ["git", "check-ignore", "-q", ".agentic/my-project-notes.md"], cwd=str(project)
        )
        self.assertNotEqual(
            check.returncode, 0,
            "!.agentic/my-project-notes.md negation must not be destroyed by the repair",
        )
        check = subprocess.run(["git", "check-ignore", "-q", ".agentic/config.json"], cwd=str(project))
        self.assertNotEqual(check.returncode, 0, "!.agentic/config.json negation must survive too")

        # Idempotent: a second apply is a true byte-level no-op.
        second = run(["apply", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(
            gitignore_path.read_bytes(), after, "second apply must not change bytes"
        )


class TestOrderRepairCommentAttachedLineMovedWithComment(unittest.TestCase):
    """Round-7 CRITICAL regression: round 6 excluded a comment-attached
    misordered candidate from `_find_misordered_umbrella` itself, which is
    also the DETECTION function `_compute_diff` calls to set
    `gitignore_misordered` - so `check`/`diff` reported `ok` (no drift) while
    the negations below a comment-attached umbrella line stayed defeated.
    Detection must be unconditional (regardless of any preceding comment);
    only the REPAIRER may special-case a comment-attached line, and it must
    never do so by silently reporting no drift. The repairer's chosen
    handling: move the comment together with its pattern line, as a single
    unit, to just above the negation - the comment is never orphaned (it
    stays directly above what it describes) and the negation is always
    repaired (never left defeated to avoid disturbing a comment)."""

    def test_detection_is_unconditional_on_comment_attached_duplicate(self):
        mod = _load_agentic_migrate_module()
        lines = [
            ".agentic/*",
            "!.agentic/config.json",
            "# intentional re-ignore",
            ".agentic/*",
        ]
        self.assertEqual(
            mod._find_misordered_umbrella(lines), 3,
            "a comment-attached candidate must still be detected as misordered",
        )

    def test_detection_is_unconditional_on_comment_attached_move_case(self):
        """The pure-move case (a distinct pattern, no dedup involved at
        all) must also be detected - this is not limited to duplicates."""
        mod = _load_agentic_migrate_module()
        lines = [
            ".agentic/*",
            "!.agentic/config.json",
            "# runtime scratch, do not commit",
            ".agentic/**",
        ]
        self.assertEqual(mod._find_misordered_umbrella(lines), 3)

    def test_comment_attached_duplicate_is_moved_with_its_comment(self):
        mod = _load_agentic_migrate_module()
        tmp = tempfile.mkdtemp()
        gitignore_path = Path(tmp) / ".gitignore"
        gitignore_path.write_text(
            ".agentic/*\n"
            "!.agentic/config.json\n"
            "# intentional re-ignore\n"
            ".agentic/*\n"
        )

        changed = mod._repair_gitignore_order(gitignore_path)

        self.assertTrue(
            changed, "a comment-attached duplicate must be repaired, not left in place"
        )
        self.assertEqual(
            gitignore_path.read_text(),
            (
                ".agentic/*\n"
                "# intentional re-ignore\n"
                ".agentic/*\n"
                "!.agentic/config.json\n"
            ),
            "the comment and its pattern line move together, in original order, "
            "above the negation - never dropped, never left below it",
        )

    def test_comment_attached_move_case_no_duplicate(self):
        """The pure-move shape (comment-preceded `.agentic/**`, no duplicate
        anywhere else in the file) was silently broken by round 6 with no
        coverage at all - this closes that gap."""
        mod = _load_agentic_migrate_module()
        tmp = tempfile.mkdtemp()
        gitignore_path = Path(tmp) / ".gitignore"
        gitignore_path.write_text(
            ".agentic/*\n"
            "!.agentic/config.json\n"
            "# runtime scratch, do not commit\n"
            ".agentic/**\n"
        )

        changed = mod._repair_gitignore_order(gitignore_path)

        self.assertTrue(changed)
        self.assertEqual(
            gitignore_path.read_text(),
            (
                ".agentic/*\n"
                "# runtime scratch, do not commit\n"
                ".agentic/**\n"
                "!.agentic/config.json\n"
            ),
        )

    def test_non_comment_duplicate_still_deduplicated(self):
        """Regression guard for the opposite direction: a misordered duplicate
        with NO preceding comment must still be dropped as before - the
        comment-attached handling must not silently disable dedup entirely."""
        mod = _load_agentic_migrate_module()
        tmp = tempfile.mkdtemp()
        gitignore_path = Path(tmp) / ".gitignore"
        gitignore_path.write_text(
            ".agentic/*\n"
            "!.agentic/config.json\n"
            ".agentic/*\n"
        )

        changed = mod._repair_gitignore_order(gitignore_path)

        self.assertTrue(changed)
        self.assertEqual(
            gitignore_path.read_text(),
            ".agentic/*\n!.agentic/config.json\n",
            "a non-comment-attached duplicate must still be deduplicated away",
        )


class TestCheckDetectsCommentAttachedMisorderedUmbrella(unittest.TestCase):
    """Integration-level companion to the CRITICAL regression above: proves
    the fix through the actual `check`/`apply` CLI surface (not just the
    pure `_find_misordered_umbrella`/`_repair_gitignore_order` functions),
    covering both the comment-attached duplicate and the comment-attached
    pure-move shapes."""

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

    def _project_with_tail(self, tmp, tail):
        project = Path(tmp) / "project"
        project.mkdir()
        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({"scaffolding_version": 1}) + "\n")
        (agentic / "qa.md").write_text("x\n")
        gitignore_path = project / ".gitignore"
        gitignore_path.write_text(".agentic/*\n!.agentic/qa.md\n" + tail)
        subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)
        return project, gitignore_path

    def test_check_reports_drift_on_comment_attached_duplicate(self):
        tmp = tempfile.mkdtemp()
        project, _ = self._project_with_tail(
            tmp, "# intentional re-ignore\n.agentic/*\n"
        )
        manifest_path = self._custom_manifest(tmp)

        result = run(["check", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(result.returncode, 1, msg=result.stdout)
        out = json.loads(result.stdout)
        self.assertEqual(out["status"], "drift")
        self.assertTrue(out["gitignore_misordered"])

    def test_check_reports_drift_on_comment_attached_move_case(self):
        tmp = tempfile.mkdtemp()
        project, _ = self._project_with_tail(
            tmp, "# runtime scratch, do not commit\n.agentic/**\n"
        )
        manifest_path = self._custom_manifest(tmp)

        result = run(["check", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(result.returncode, 1, msg=result.stdout)
        out = json.loads(result.stdout)
        self.assertEqual(out["status"], "drift")
        self.assertTrue(out["gitignore_misordered"])

    def test_apply_repairs_comment_attached_duplicate_and_negation_works(self):
        tmp = tempfile.mkdtemp()
        project, gitignore_path = self._project_with_tail(
            tmp, "# intentional re-ignore\n.agentic/*\n"
        )
        manifest_path = self._custom_manifest(tmp)

        result = run(["apply", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        check_result = run(["check", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(check_result.returncode, 0, msg=check_result.stdout)

        # Real git proof, not just a string check.
        check = subprocess.run(["git", "check-ignore", "-q", ".agentic/qa.md"], cwd=str(project))
        self.assertNotEqual(check.returncode, 0, "qa.md must not be git-ignored after repair")

        first_content = gitignore_path.read_bytes()
        r2 = run(["apply", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(r2.returncode, 0, msg=r2.stderr)
        self.assertEqual(gitignore_path.read_bytes(), first_content, "second apply must be a true no-op")


class TestRootAnchoredNegationRecognized(unittest.TestCase):
    """Round 8 MAJOR 1 regression: a root-anchored `!/.agentic/<file>`
    negation line must be recognized by every negation-lookup site
    (_find_misordered_umbrella, _repair_gitignore_order, _append_gitignore),
    symmetric with _is_agentic_umbrella_pattern's own acceptance of the
    `/`-prefixed umbrella form. Before the fix, `line.strip().startswith(
    "!.agentic/")` missed this spelling entirely: _find_misordered_umbrella
    found no negation line at all, so `check` reported `ok` while a
    root-anchored-negation project's umbrella sat misordered below the
    negations, silently defeating every one of them - permanently, since
    _compute_diff's `gitignore_misordered` flag never went True to trigger
    `apply`."""

    def _misordered_root_anchored_project(self, tmp):
        project = Path(tmp) / "project"
        project.mkdir()
        agentic = project / ".agentic"
        agentic.mkdir()
        (agentic / "config.json").write_text(json.dumps({"scaffolding_version": 1}) + "\n")
        (agentic / "qa.md").write_text("# qa\n")
        gitignore_path = project / ".gitignore"
        # Root-anchored negation, with the umbrella misordered BELOW it -
        # the exact shape the pre-fix bare-form-only lookup missed.
        gitignore_path.write_text("!/.agentic/qa.md\n.agentic/*\n")
        subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)
        return project, gitignore_path

    def _custom_manifest(self, tmp):
        # Root-anchored patterns, matching the fixture's own spelling exactly
        # (_pattern_present is an exact-line match) - this isolates the
        # ordering-repair mutation being tested. A manifest using the bare
        # spelling would make `apply` treat "!.agentic/qa.md" as a separate
        # missing pattern and append it at EOF (below the umbrella but
        # working on its own), which would mask a broken negation-lookup
        # mutation behind that unrelated append path.
        manifest_text = """
scaffolding_version: 1
gitignore:
  - pattern: "/.agentic/*"
    purpose: "umbrella ignore"
  - pattern: "!/.agentic/qa.md"
    purpose: "committed"
files: []
markers: []
"""
        manifest_path = Path(tmp) / "test-manifest.yml"
        manifest_path.write_text(manifest_text)
        return manifest_path

    def test_find_misordered_umbrella_recognizes_root_anchored_negation(self):
        mod = _load_agentic_migrate_module()
        lines = ["!/.agentic/qa.md", ".agentic/*"]
        self.assertEqual(
            mod._find_misordered_umbrella(lines), 1,
            "root-anchored !/.agentic/ negation must be found so the "
            "umbrella below it is detected as misordered",
        )

    def test_is_agentic_negation_line_matrix(self):
        mod = _load_agentic_migrate_module()
        positive = [
            "!.agentic/x", "!/.agentic/x", "!**/.agentic/x",
            "  !.agentic/x  ", "\t!/.agentic/x\t", "!.agentic/x\n",
        ]
        for line in positive:
            self.assertTrue(
                mod._is_agentic_negation_line(line),
                f"expected {line!r} to be recognized as an .agentic/ negation line",
            )
        negative = [
            "!other/path", "!.agentic-other/x", ".agentic/*",
            "!agentic/x", "# !.agentic/x",
        ]
        for line in negative:
            self.assertFalse(
                mod._is_agentic_negation_line(line),
                f"expected {line!r} to NOT be recognized as an .agentic/ negation line",
            )

    def test_check_reports_drift_on_root_anchored_misordered_file(self):
        tmp = tempfile.mkdtemp()
        project, _ = self._misordered_root_anchored_project(tmp)
        manifest_path = self._custom_manifest(tmp)

        result = run(["check", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(result.returncode, 1, msg=result.stdout)
        out = json.loads(result.stdout)
        self.assertEqual(out["status"], "drift")
        self.assertTrue(
            out["gitignore_misordered"],
            "check must report misordering for a root-anchored negation, "
            "not silently report ok - this is the exact MAJOR 1 defect",
        )

    def test_apply_repairs_root_anchored_ordering_and_negation_works(self):
        tmp = tempfile.mkdtemp()
        project, gitignore_path = self._misordered_root_anchored_project(tmp)
        manifest_path = self._custom_manifest(tmp)

        r1 = run(["apply", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(r1.returncode, 0, msg=r1.stderr)

        # check must now report ok (ordering fixed).
        check_result = run(["check", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(check_result.returncode, 0, msg=check_result.stdout)

        # Real git proof (never git check-ignore's exit code alone as the
        # sole oracle - stage via a fresh index, per this branch's
        # established verification convention).
        add = subprocess.run(["git", "add", "-A"], cwd=str(project))
        self.assertEqual(add.returncode, 0)
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(project),
            capture_output=True, text=True, check=True,
        )
        self.assertIn(
            ".agentic/qa.md", status.stdout,
            "qa.md must be stageable (not git-ignored) after root-anchored "
            f"ordering repair; git status --porcelain was:\n{status.stdout}",
        )

        # Idempotent: a second apply makes no further byte-level changes.
        first_content = gitignore_path.read_bytes()
        r2 = run(["apply", "--manifest", str(manifest_path), "--project-root", str(project)])
        self.assertEqual(r2.returncode, 0, msg=r2.stderr)
        self.assertEqual(gitignore_path.read_bytes(), first_content, "second apply must be a true no-op")

    def test_double_star_prefixed_negation_recognized(self):
        mod = _load_agentic_migrate_module()
        lines = ["!**/.agentic/qa.md", ".agentic/*"]
        self.assertEqual(
            mod._find_misordered_umbrella(lines), 1,
            "**/-prefixed !**/.agentic/ negation must also be recognized",
        )

    def test_non_negation_bang_line_not_misread_as_negation(self):
        mod = _load_agentic_migrate_module()
        # A line that starts with `!` but is unrelated to .agentic/ must
        # never be mistaken for the negation anchor - it should not cause
        # _find_misordered_umbrella to falsely treat an umbrella below it
        # as ordering-violating relative to a negation that doesn't exist
        # for .agentic/ at all in this fixture.
        lines = ["!other/path", ".agentic/*"]
        self.assertIsNone(
            mod._find_misordered_umbrella(lines),
            "an unrelated !-prefixed line must not be treated as an "
            ".agentic/ negation anchor",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
