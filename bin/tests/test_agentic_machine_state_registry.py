#!/usr/bin/env python3
"""
Purpose: DS-259 drift gate for `bin/ds-cleanup-worktrees`' `.agentic/`
    disposable set. Inside `.agentic/` an unknown name stays protected
    (fail-closed), so every machine-written state name must be declared
    positively in the tool. This test scans writer source for `.agentic/`
    state names and fails on any name that is neither covered by the tool's
    deletable constants nor recorded in `REVIEWED_NOT_DISPOSABLE` below, so a
    new hook's output cannot silently start blocking worktree reap again.

    Scan scope: `test_agentic_site_inventory_coverage._iter_candidate_files`
    over its SCAN_DIRS plus `scripts`, with EXCLUDED_FILES NOT applied (it
    lists cwd-anchoring exemptions, several of which are `.agentic` writers),
    minus `scripts/test/`, minus files git does not track (so a local run
    sees exactly what CI sees), and minus `bin/ds-cleanup-worktrees` itself:
    its pattern literals would otherwise certify their own coverage.

    Extractors: (a) names anchored on `.agentic` (`'.agentic/NAME'`,
    `'.agentic', 'NAME'`, `".agentic" / "NAME"`); (b) string literals shaped
    like state files (dot-prefixed hyphenated names, `*.json`, `*.jsonl`,
    `*.lock` basenames); (c) in files containing `.agentic`, the literal on
    the right of an ALL_CAPS assignment whose name ends in NAME, FILENAME,
    FILE, BASENAME, REL or MARKER. `{...}`/`${...}` normalize to `*` and a
    trailing `-` to `-*`.

    Classification: a token is classified by the exact rule (it fnmatches a
    deletable constant with every `*` replaced by `x`), the prefix rule (a
    token ending in `-*` with no other `*` whose stem starts with the
    letter-bearing literal head of a basename or top-level pattern), or the
    ledger rule. The prefix rule lives in this test only: no deletable
    constant may be widened, and no entry added, to make this test pass. A
    prefix token classified that way does not prove the full runtime name is
    deletable; if the suffix does not match, the file stays protected
    (fail-closed).

    Recall gaps (R3's "fails when a writer's output is not classified" holds
    only within these bounds): (1) names built at runtime with no literal
    stem, and prefix tokens whose suffix is unknown; (2) literals that fit
    none of (a), (b), (c); (3) state that agents write because `content/`
    prose tells them to; (4) writers outside the scan scope, e.g.
    `.codex/lib/prompt-wrappers.py` (its only state is under
    `codex-prompt-generation/`, already a disposable dir name). Retirement:
    when every `.agentic/` state writer resolves its path through one shared
    machine-state subdirectory, delete this test.

Public API: pytest discovers the test_* functions; `extract_state_names`
    is the extractor, returning token -> set of source paths.

Upstream deps: bin/ds-cleanup-worktrees (deletable constants and
    `_is_protected_ignored_path`, loaded via SourceFileLoader);
    bin/tests/test_agentic_site_inventory_coverage.py (SCAN_DIRS and the
    candidate-file walker); bin/ds-agentic-repair (`_RUNTIME_STATE_MARKERS`);
    `git ls-files` (subprocess, check=True).

Downstream consumers: pytest bin/tests/ (CI, .github/workflows/bin-tests.yml).

Failure modes: an unclassified token fails naming the token, its source
    files, and the two places to classify it. A ledger key no longer
    extracted fails as stale. A git failure fails the test, never skips it.

Performance: one walk of a few hundred files plus one `git ls-files`; well
    under a second.
"""

from __future__ import annotations

import fnmatch
import importlib.machinery as _ilm
import importlib.util as _ilu
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, Set

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TOOL_REL = "bin/ds-cleanup-worktrees"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_agentic_site_inventory_coverage as inv  # noqa: E402


def _load(name: str, rel: str):
    loader = _ilm.SourceFileLoader(name, str(REPO_ROOT / rel))
    spec = _ilu.spec_from_loader(name, loader)
    mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = mod  # dataclasses in the loaded module resolve it here
    loader.exec_module(mod)
    return mod


tool = _load("ds_cleanup_worktrees_registry", TOOL_REL)

DELETABLE_PATTERNS = (
    tuple(tool._AGENTIC_DISPOSABLE_DIR_NAMES)
    + tuple(tool._AGENTIC_DISPOSABLE_BASENAME_PATTERNS)
    + tuple(tool._AGENTIC_DISPOSABLE_TOPLEVEL_PATTERNS)
)
PREFIX_SOURCE_PATTERNS = tuple(tool._AGENTIC_DISPOSABLE_BASENAME_PATTERNS) + tuple(
    tool._AGENTIC_DISPOSABLE_TOPLEVEL_PATTERNS
)

#: Names the scan extracts that are deliberately NOT disposable. Each value
#: starts with `protected:` (authored or operator-owned project state),
#: `not-project:` (never lives in a project `.agentic/`), or `unverified:`
#: (no code writer traced; stays protected, fail-closed). This set does not
#: affect deletion behavior.
REVIEWED_NOT_DISPOSABLE: Dict[str, str] = {
    "_wrap.md": "protected: curated wrap summary, source of the context.md rollup",
    "config.json": "protected: per-project behavioral toggles",
    "qa.md": "protected: authored QA runbook",
    "tracker.yml": "protected: operator tracker overlay",
    "identity.yml": "protected: operator identity override",
    "team.yml": "protected: operator team config",
    "learnings.md": "protected: curated learnings",
    "memory.md": "protected: legacy fact store",
    "memory": "protected: auto-memory directory",
    "skill-candidates.md": "protected: curated skill-candidate backlog",
    "loop-state*": "protected: live review-loop state read across a ticket",
    "batch-state.json": "protected: live batch-run state",
    "memory-shards": "protected: memory shard store",
    "worktrees": "protected: conductor-created worktree directory",
    "worktree-archive": "protected: archive bundles, sole copy of some branches",
    "reaped-telemetry": "protected: telemetry salvaged from reaped worktrees",
    "stray-agentic-archive": "protected: archived stray .agentic trees",
    "teamrun": "protected: team run directories",
    "evidence": "protected: QA evidence",
    ".activated": "protected: activation sentinel read by bin/ds-status",
    "codex-skill-root-ownership.json": "protected: build-tool safety registry",
    "branch-prune-ledger.txt": "protected: record of branch deletions",
    "phase0-classifiers.yml": "protected: project classifier config",
    "role-models.yml": "protected: operator role-to-model map",
    "ds-153-plan.md": "protected: authored plan, cited in a comment",
    "wrap.lock": "protected: legacy directory-shaped wrap lock (hooks/lib/wrap-marker.js)",
    "owner.json": "protected: never top-level; lives under wrap/lock/, already disposable via wrap/",
    "pending-<session_id>.json": "protected: never top-level; lives under wrap/, already disposable via wrap/",
    ".agentic": "protected: a nested .agentic tree is a stray, handled by bin/ds-agentic-repair",
    "dotagentic": "not-project: bin/ds-agentic-repair archive-name mangling, not a file",
    "learnings-agent.session": (
        "unverified: session marker the conductor writes per content/ prose; "
        "hooks/stop-context.js only removes it, no code writer"
    ),
    "settings.json": "not-project: harness settings under ~/.claude",
    "settings*.json": "not-project: harness settings glob under ~/.claude",
    "hooks.json": "not-project: harness hook config",
    "installed_plugins.json": "not-project: harness plugin registry",
    "version-check-cache.json": "not-project: ~/.agentic update cache",
    "update-shared.json": "not-project: ~/.agentic update state",
    "agentic-engineering-config.json": "not-project: ~/.agentic install config",
    "agentic-engineering.json": "not-project: harness-level DinoStack config",
    ".identity-nudged": "not-project: ~/.agentic sentinel",
    "hooks-snapshot": "not-project: ~/.agentic hooks snapshot directory",
    ".snapshot-meta.json": "not-project: hooks snapshot metadata",
    ".rolled-up.json": "not-project: ~/.agentic/learnings-shards bookkeeping",
    ".lock": "not-project: ~/.agentic/learnings-shards lock name",
    ".processing.*.*.json": "not-project: ~/.agentic/session-log/.pending claim name",
    "ds-identity-write-hook-*-*.json": "not-project: os.tmpdir() status file",
    ".meta.json": "not-project: subagent transcript sidecar under the harness projects dir",
    "agent-*.meta.json": "not-project: subagent transcript sidecar under the harness projects dir",
    ".settings-tmp-*": "not-project: tempfile prefix in ~/.claude",
    ".version-cache-tmp-*": "not-project: tempfile prefix in ~/.agentic",
    ".codex-skills-render-*": "not-project: tempfile prefix in the codex skills output dir",
    ".dinostack-generated-root.json": "not-project: codex generated-skill root marker",
    ".dinostack-skill.json": "not-project: codex generated-skill marker",
    "RESOURCE-MAP.json": "not-project: codex generated-skill resource map",
    ".chrome-for-testing-cache": "not-project: slide overflow checker browser cache",
    "slide-overflow-baseline.json": "not-project: scripts/ baseline file",
    "Agent": "not-project: tool name, not a file",
    "enforce-no-abdication": "not-project: hook name, not a file",
    "DS-45-SWEEP-HEAD": "not-project: sweep canary text, not a file",
}

INCIDENT_NAMES = (
    ".ticket-scan-*.json",
    ".nested-worktree-spawn-*.json",
    ".telemetry-health.json",
    ".turn-shape-guard-fire-count",
    "context.md",
    "context.d",
    "session-log",
    "skeptic-round-*.json",
    "skeptic-tuid-index.json",
)

_BRACE = re.compile(r"\$?\{[^{}\n]*\}")
_ANCHOR_SLASH = re.compile(r"""["'`]\.agentic/([A-Za-z0-9_.*{}$<>\-]+)""")
_ANCHOR_ARG = re.compile(r"""["']\.agentic["']\s*(?:,|/)\s*f?["']([^"'\n]+)["']""")
_LITERAL = re.compile(r"""(["'`])([^"'`\n\\]{1,160})\1""")
_DOT_HYPHEN = re.compile(r"^\.[A-Za-z0-9_*]+(?:-[A-Za-z0-9_*.]*)+$")
_STATE_EXT = re.compile(r"^[^/\s]+\.(?:json|jsonl|lock)$")
_CONST_ASSIGN = re.compile(
    r"""^\s*(?:export\s+)?(?:const\s+|let\s+|var\s+)?_?[A-Z][A-Z0-9_]*(?:NAME|FILENAME|FILE|BASENAME|REL|MARKER)"""
    r"""\s*(?::\s*\w+\s*)?=\s*f?(["'])([^"'\n]+)\1""",
    re.M,
)


def _normalize(raw: str):
    tok = _BRACE.sub("*", raw)
    if tok.endswith("-"):
        tok += "*"
    if not re.match(r"[A-Za-z0-9_.]", tok):
        return None
    if not re.search(r"[A-Za-z0-9]", tok):
        return None
    return tok


def _extract_text(text: str) -> Set[str]:
    raw: Set[str] = set()
    for m in _ANCHOR_SLASH.finditer(text):
        raw.add(m.group(1).split("/")[0].rstrip("."))
    for m in _ANCHOR_ARG.finditer(text):
        raw.add(m.group(1).split("/")[0])
    for m in _LITERAL.finditer(text):
        lit = m.group(2)
        flat = _BRACE.sub("*", lit)
        if "/" in flat or " " in flat:
            continue
        if _DOT_HYPHEN.match(flat) or _STATE_EXT.match(flat):
            raw.add(lit)
    if ".agentic" in text:
        for m in _CONST_ASSIGN.finditer(text):
            if "/" not in m.group(2):
                raw.add(m.group(2))
    return {tok for tok in (_normalize(r) for r in raw) if tok}


def extract_state_names(paths: Iterable[Path]) -> Dict[str, Set[str]]:
    found: Dict[str, Set[str]] = {}
    for path in paths:
        try:
            source = str(path.relative_to(REPO_ROOT))
        except ValueError:
            source = str(path)
        for tok in _extract_text(path.read_text(encoding="utf-8", errors="replace")):
            found.setdefault(tok, set()).add(source)
    return found


def _scan_paths():
    scan_dirs = [*inv.SCAN_DIRS, "scripts"]
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--", *scan_dirs],
        capture_output=True,
        check=True,
    )
    tracked = {p.decode("utf-8") for p in proc.stdout.split(b"\0") if p}
    for rel, entry in inv._iter_candidate_files(scan_dirs=scan_dirs, excluded_files=frozenset()):
        if rel.startswith("scripts/test/") or rel == TOOL_REL or rel not in tracked:
            continue
        yield entry


def _scan() -> Dict[str, Set[str]]:
    return extract_state_names(_scan_paths())


def _is_prefix_token(tok: str) -> bool:
    return tok.endswith("-*") and tok.count("*") == 1


def _exact_rule(tok: str) -> bool:
    probe = tok.replace("*", "x")
    return any(fnmatch.fnmatch(probe, p) for p in DELETABLE_PATTERNS)


def _prefix_rule(tok: str) -> bool:
    if not _is_prefix_token(tok):
        return False
    stem = tok[:-1]
    for pattern in PREFIX_SOURCE_PATTERNS:
        if "*" not in pattern:
            continue
        head = pattern.split("*", 1)[0]
        if re.search(r"[A-Za-z]", head) and stem.startswith(head):
            return True
    return False


def _ledger_rule(tok: str, ledger: Dict[str, str]) -> bool:
    probe = tok.replace("*", "x")
    return any(fnmatch.fnmatch(probe, key) for key in ledger)


def _unclassified(found: Dict[str, Set[str]], ledger: Dict[str, str]) -> Dict[str, Set[str]]:
    return {
        tok: srcs
        for tok, srcs in found.items()
        if not (_exact_rule(tok) or _prefix_rule(tok) or _ledger_rule(tok, ledger))
    }


def test_every_extracted_state_name_is_classified():
    bad = _unclassified(_scan(), REVIEWED_NOT_DISPOSABLE)
    msg = "\n".join(
        f"  {tok!r} (from {', '.join(sorted(srcs))})" for tok, srcs in sorted(bad.items())
    )
    assert not bad, (
        "Unclassified .agentic/ state names. For each, either add a pattern citing its "
        f"writer to the deletable constants in {TOOL_REL} (machine-written state), or add "
        "it to REVIEWED_NOT_DISPOSABLE in this file with a protected:/not-project:/"
        "unverified: reason:\n" + msg
    )


def _covers(tok: str, name: str) -> bool:
    return tok == name or (_is_prefix_token(tok) and name.startswith(tok[:-1]))


def test_incident_names_are_extracted_and_disposable():
    found = _scan()
    for name in INCIDENT_NAMES:
        assert tool._is_protected_ignored_path(".agentic/" + name.replace("*", "x")) is False, name
        assert any(_covers(tok, name) for tok in found), f"no scanned writer token covers {name!r}"


def test_ledger_has_no_stale_entries():
    found = _scan()
    stale = [
        key for key in REVIEWED_NOT_DISPOSABLE if not any(fnmatch.fnmatch(t.replace("*", "x"), key) for t in found)
    ]
    assert not stale, f"REVIEWED_NOT_DISPOSABLE keys no longer extracted by the scan: {stale}"


def test_synthetic_new_writers_are_reported_unclassified(tmp_path):
    js = tmp_path / "new-hook.js"
    js.write_text("const p = path.join(dir, '.brand-new-hook-state.json');\n")
    py = tmp_path / "new_hook.py"
    py.write_text(
        'COUNTER_FILENAME = "brand-new-count"\n'
        "PREFIX = '.brand-new-prefix-'\n"
        'agentic_dir = root / ".agentic"\n'
    )
    found = extract_state_names([js, py])
    bad = _unclassified(found, REVIEWED_NOT_DISPOSABLE)
    for tok in (".brand-new-hook-state.json", "brand-new-count", ".brand-new-prefix-*"):
        assert tok in found, f"extractor missed {tok!r}"
        assert tok in bad, f"{tok!r} was classified but must be reported unclassified"


def test_scan_scope_reaches_adapters_and_excluded_files():
    found = _scan()
    assert ".opencode/plugins/session-context.ts" in found.get("events.jsonl", set())
    assert "bin/ds-migrate" in found.get(".manifest-not-found-warned", set())


def test_repair_runtime_markers_are_disposable():
    repair = _load("ds_agentic_repair_registry", "bin/ds-agentic-repair")
    for marker in repair._RUNTIME_STATE_MARKERS:
        assert tool._is_protected_ignored_path(f".agentic/{marker}") is False, marker
