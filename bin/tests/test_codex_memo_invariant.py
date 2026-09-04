#!/usr/bin/env python3
"""
Purpose: Statically enforce the process-scoped invariant that makes
         scripts/codex-skills.py's assembled_methodology() and
         current_inventory() memos safe. Those memos are correct only
         because every build/check/inventory runs in a NEW process with an
         empty memo, so scripts/test/test_codex_skills.py's ~110 mutation
         gates always read a mutated tree fresh. The moment any test in
         that file loads the generator IN-PROCESS and reaches a memoized
         function twice, a mutation applied between the two calls is
         silently masked - the second call returns the stale pre-mutation
         result, no SkillError is raised, and the gate passes while
         asserting nothing. This guard fails CI on that shape.

Public API: pytest/unittest entry points only. The reusable core is
            scan(test_source, generator_source) -> ScanResult and
            memo_assignments(generator_source) -> set[str]. Both take
            source TEXT (not paths) so the self-tests can drive them with
            synthetic fixtures and observe them go RED.

Upstream deps: standard library only (ast, textwrap, unittest, pathlib).
               Reads scripts/codex-skills.py and
               scripts/test/test_codex_skills.py as text; never imports or
               executes either - the same no-execution discipline as the
               sibling precedent bin/tests/test_ds_primary_name_sweep.py,
               which AST-parses the same generator.

Downstream consumers: the `python-bin-tests` CI job, which runs
                      `python3 -m pytest bin/tests/ -q --timeout=60`
                      and collects this file automatically via pytest's
                      default `test_*.py` glob. No other module imports it.

Failure modes: fails (never errors) when a generator-loading test in
               scripts/test/test_codex_skills.py touches a symbol that
               transitively reaches a memoized function, naming the test,
               the symbol, the call path, and the remedy.

               Fails CLOSED in three ways, because a guard that can only
               pass is worthless: a loader site whose module variable
               cannot be resolved is a failure; a bare (non-attribute) use
               of a resolved module variable - rebinding it to another
               name, passing it to a helper, handing it to getattr - is a
               failure; and a scan finding fewer than
               EXPECTED_MINIMUM_LOADER_SITES sites is a failure, so a
               renamed loader idiom reddens rather than blinding the guard.

               KNOWN DETECTION BOUNDARY, deliberately not closed. Two
               shapes still pass GREEN and would need a real dataflow
               analysis rather than this local AST pass:
                 (1) a loader at MODULE level, outside any function -
                     scan() only walks function bodies;
                 (2) dictionary-style symbol access that never forms an
                     attribute node against a generator symbol, i.e.
                     module.__dict__["current_inventory"](repo) - the only
                     attribute label here is __dict__, which is not a
                     generator symbol.
               Both are far from the file's established idiom, unlike the
               sys.modules[...] alias (one line from the idiom used at all
               five real sites), which IS closed. Revisit if either
               appears.

               Pure read-only static analysis; no side effects, safe to
               re-run.

Performance: two ast.parse calls plus a BFS over the generator's symbol
             graph; well under a second, far inside the 60 s CI per-test
             timeout. Figures are deliberately not pinned here - they
             re-stale on every edit to either file.

Pillar 8 (named catch): the concrete failure this would have caught is the
             one a Skeptic demonstrated live on this branch - loading the
             branch module in-process, calling current_inventory(),
             applying the exact anchor mutation that
             test_unmatched_paragraph_rule_anchor_fails_loudly exists to
             catch, and calling again: no SkillError, identical stale
             result, where a fresh process catches it. The natural next
             optimization - converting the ~110 subprocess invocations in
             scripts/test/test_codex_skills.py to in-process calls for
             speed - would disarm every mutation gate on a REQUIRED check
             while every test stayed green.

Pillar 8 (retirement condition): this guard retires when the memos are
             removed from scripts/codex-skills.py. It is not a permanent
             floor - it exists solely to protect those two caches.
             test_memos_still_exist_or_this_guard_retires fails on their
             removal precisely so the deletion of the memos and the
             deletion of this file happen in the same change. That pin is
             an AST check for a real module-level assignment, not
             substring containment: deleting the assignment while leaving
             the name in a neighbouring comment must NOT keep it green.
"""

from __future__ import annotations

import ast
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GENERATOR_PATH = REPO_ROOT / "scripts" / "codex-skills.py"
GENERATOR_TESTS_PATH = REPO_ROOT / "scripts" / "test" / "test_codex_skills.py"

# The two process-scoped memoized functions whose staleness the mutation
# gates cannot survive. Keep in lockstep with codex-skills.py.
MEMOIZED_FUNCTIONS = ("current_inventory", "assembled_methodology")

# The module-level dicts backing those memos. Their presence is this
# guard's retirement condition.
MEMO_NAMES = ("_ASSEMBLED_METHODOLOGY_MEMO", "_CURRENT_INVENTORY_MEMO")

# Module-level constant in scripts/test/test_codex_skills.py naming the
# generator. A loader call is a *generator* loader only when this name
# appears in its arguments - that is what distinguishes the five real sites
# from the sibling loaders for PROMPT_GENERATOR and bin/agentic-codex-session-id,
# which load different files and are correctly out of scope.
GENERATOR_CONSTANT = "GENERATOR"

LOADER_FUNCTIONS = ("spec_from_file_location", "spec_from_loader", "SourceFileLoader")
MODULE_FACTORY = "module_from_spec"

# Bare (non-attribute) uses of the module variable that are structurally
# incapable of reaching a generator symbol, and are the file's own idiom at
# all five real sites. Everything else bare fails closed.
#   spec.loader.exec_module(module)      -> executes the module body
#   sys.modules[module_name] = module    -> alias registration, itself tracked
EXEC_MODULE = "exec_module"

# The real file currently has five in-process generator loader sites. The
# guard asserts it found at least this many so that a refactor which moves
# or renames the loader idiom turns the guard red rather than silently
# reducing it to a no-op. Lower this only alongside a real site removal.
EXPECTED_MINIMUM_LOADER_SITES = 5

REMEDY = (
    "Call the generator in a subprocess instead."
)
UNVERIFIABLE_REMEDY = (
    "Assign the module to a plain local from module_from_spec(), or call the "
    "generator in a subprocess."
)


class ScanResult:
    """violations: human-readable failures. sites: generator loader sites seen."""

    def __init__(self, violations: list[str], sites: list[str]) -> None:
        self.violations = violations
        self.sites = sites


def _call_label(call: ast.Call) -> str:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return ""


def _enclosing_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _referenced_names(node: ast.AST) -> set[str]:
    """Every bare name and attribute label appearing anywhere under `node`.

    Deliberately over-broad: an edge that does not correspond to a real call
    only makes the guard more conservative, and a false "reaches a memo"
    is a loud, fixable failure, whereas a missed edge is a silent hole.
    """
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def memo_assignments(generator_source: str) -> set[str]:
    """Memo names bound by a real module-level assignment.

    An AST check, not substring containment: a memo name surviving only in a
    comment or docstring must not satisfy the retirement pin.
    """
    tree = ast.parse(generator_source, filename="codex-skills.py")
    bound: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bound.add(node.target.id)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.add(target.id)
    return bound


def build_call_graph(generator_source: str) -> dict[str, set[str]]:
    """Map every generator symbol to the generator symbols it can reach directly.

    Nodes are module-level function names, class names, and `Class.method`.
    A class node inherits the union of its methods' edges, so accessing
    `module.SomeClass` is treated as reaching whatever its methods reach.
    """
    tree = ast.parse(generator_source, filename="codex-skills.py")
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.add(f"{node.name}.{sub.name}")
                        symbols.add(sub.name)

    graph: dict[str, set[str]] = {name: set() for name in symbols}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            graph[node.name] |= _referenced_names(node) & symbols
            graph[node.name].discard(node.name)
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    edges = _referenced_names(sub) & symbols
                    edges.discard(sub.name)
                    graph[f"{node.name}.{sub.name}"] |= edges
                    graph[sub.name] |= edges
                    graph[node.name] |= edges
    return graph


def reaches(graph: dict[str, set[str]], start: str, targets: tuple[str, ...]) -> list[str] | None:
    """Shortest symbol path from `start` to any target, or None."""
    if start in targets:
        return [start]
    seen = {start}
    queue: list[list[str]] = [[start]]
    while queue:
        path = queue.pop(0)
        for nxt in sorted(graph.get(path[-1], set())):
            if nxt in seen:
                continue
            seen.add(nxt)
            extended = path + [nxt]
            if nxt in targets:
                return extended
            queue.append(extended)
    return None


def _generator_loader_names(func: ast.AST) -> tuple[set[str], set[str]]:
    """(spec variables, module_name variables) for GENERATOR loader calls."""
    specs: set[str] = set()
    name_vars: set[str] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if _call_label(call) not in LOADER_FUNCTIONS:
            continue
        if not any(
            isinstance(n, ast.Name) and n.id == GENERATOR_CONSTANT
            for arg in call.args
            for n in ast.walk(arg)
        ):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                specs.add(target.id)
        for arg in call.args:
            if isinstance(arg, ast.Name):
                name_vars.add(arg.id)
    return specs, name_vars


def _module_variables(func: ast.AST) -> set[str]:
    """Names assigned from importlib.util.module_from_spec(...)."""
    variables: set[str] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if _call_label(node.value) != MODULE_FACTORY:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                variables.add(target.id)
    return variables


def _is_sys_modules_alias(node: ast.AST, name_vars: set[str]) -> bool:
    """`sys.modules[<the loader's module_name var>]` - an alias of the module.

    This is one line from the idiom used at all five real sites
    (`sys.modules[module_name] = module`), so it is closed rather than
    left to the documented boundary.
    """
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "modules"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "sys"
        and isinstance(node.slice, ast.Name)
        and node.slice.id in name_vars
    )


def _symbols_touched(func: ast.AST, module_variables: set[str], name_vars: set[str]) -> set[str]:
    """Attribute labels read off any in-process module handle or its alias."""
    touched: set[str] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Attribute):
            continue
        base = node.value
        if isinstance(base, ast.Name) and base.id in module_variables:
            touched.add(node.attr)
        elif _is_sys_modules_alias(base, name_vars):
            touched.add(node.attr)
    return touched


def _exempt_bare_uses(func: ast.AST, module_variables: set[str], name_vars: set[str]) -> set[int]:
    """id()s of bare module-variable uses that cannot reach a generator symbol.

    Exactly two shapes, both the file's own idiom at all five real sites:
    `spec.loader.exec_module(module)` and `sys.modules[module_name] = module`
    (whose alias this guard already tracks).
    """
    exempt: set[int] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and _call_label(node) == EXEC_MODULE:
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id in module_variables:
                    exempt.add(id(arg))
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) \
                and node.value.id in module_variables:
            if any(_is_sys_modules_alias(t, name_vars) for t in node.targets):
                exempt.add(id(node.value))
    return exempt


def _bare_uses(func: ast.AST, module_variables: set[str], name_vars: set[str]) -> list[int]:
    """Line numbers where a module variable is used other than as `module.attr`.

    Rebinding to another name, passing it to a helper, or handing it to
    getattr all defeat the attribute-based reachability scan, so they fail
    closed rather than pass silently.
    """
    attribute_bases = {
        id(node.value)
        for node in ast.walk(func)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        and node.value.id in module_variables
    }
    exempt = _exempt_bare_uses(func, module_variables, name_vars)
    lines: list[int] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and node.id in module_variables \
                and isinstance(node.ctx, ast.Load) \
                and id(node) not in attribute_bases and id(node) not in exempt:
            lines.append(node.lineno)
    return sorted(lines)


def scan(test_source: str, generator_source: str) -> ScanResult:
    """Report every in-process generator load that can reach a memoized function.

    Takes source text rather than paths so the self-tests can drive it with
    synthetic fixtures and observe it go RED.
    """
    graph = build_call_graph(generator_source)
    tree = ast.parse(test_source, filename="test_codex_skills.py")
    violations: list[str] = []
    sites: list[str] = []

    for func in _enclosing_functions(tree):
        specs, name_vars = _generator_loader_names(func)
        if not specs:
            continue
        site = f"{func.name} (line {func.lineno})"
        sites.append(site)

        module_variables = _module_variables(func)
        if not module_variables:
            violations.append(
                f"{site} in scripts/test/test_codex_skills.py loads "
                f"scripts/codex-skills.py in-process but no module variable could be "
                f"resolved, so this guard cannot verify it stays clear of "
                f"{' / '.join(MEMOIZED_FUNCTIONS)}. Failing closed. "
                f"{UNVERIFIABLE_REMEDY}"
            )
            continue

        for line in _bare_uses(func, module_variables, name_vars):
            violations.append(
                f"{site} in scripts/test/test_codex_skills.py uses the in-process "
                f"generator module as a bare value at line {line} (rebinding it, "
                f"passing it to a helper, or reaching it via getattr) rather than as "
                f"a direct attribute access, so this guard cannot follow it to "
                f"{' / '.join(MEMOIZED_FUNCTIONS)}. Failing closed. "
                f"{UNVERIFIABLE_REMEDY}"
            )

        for symbol in sorted(_symbols_touched(func, module_variables, name_vars)):
            path = reaches(graph, symbol, MEMOIZED_FUNCTIONS)
            if path is None:
                continue
            violations.append(
                f"{site} in scripts/test/test_codex_skills.py reaches memoized "
                f"{path[-1]}() in scripts/codex-skills.py in-process via "
                f"{' -> '.join(path)}. The memos are process-scoped: a second "
                f"in-process call after a content/ mutation returns the STALE "
                f"pre-mutation result and silently disarms the mutation gate. "
                f"{REMEDY}"
            )

    return ScanResult(violations, sites)


# --------------------------------------------------------------------------
# Fixtures for the self-tests. A guard never observed failing is
# indistinguishable from one that cannot fail, so each RED case below makes
# a specific arm of scan()/memo_assignments() fire on purpose.
# --------------------------------------------------------------------------

FIXTURE_GENERATOR = textwrap.dedent(
    '''
    _ASSEMBLED_METHODOLOGY_MEMO: dict = {}
    _CURRENT_INVENTORY_MEMO: dict = {}

    def assembled_methodology(repo):
        return ""

    def documents(repo):
        return [assembled_methodology(repo)]

    def inventory_document(doc, repo):
        return []

    def current_inventory(repo):
        return [inventory_document(d, repo) for d in documents(repo)]

    def render_tree(repo, output):
        return current_inventory(repo)

    def transform(text, occurrences):
        return text

    def build(repo, output):
        render_tree(repo, output)
    '''
)

# Mirrors the real idiom at all five sites, including the sys.modules alias
# registration and exec_module call that must NOT be flagged as bare uses.
_LOADER_PREAMBLE = '''
GENERATOR = Path("scripts/codex-skills.py")

class Fixture:
    def test_example(self):
        module_name = "fixture"
        spec = importlib.util.spec_from_file_location(module_name, self.repo / GENERATOR)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
'''


def _fixture_test(body: str) -> str:
    return textwrap.dedent(_LOADER_PREAMBLE) + textwrap.indent(textwrap.dedent(body), " " * 8)


class CodexMemoInvariantGuardTests(unittest.TestCase):
    """Self-tests: prove the guard fires before trusting it to stay green."""

    def test_guard_goes_red_on_direct_in_process_memo_call(self) -> None:
        """The exact shape the Skeptic demonstrated: call, mutate, call again."""
        fixture = _fixture_test(
            """
            first = module.current_inventory(self.repo)
            target.write_text(text.replace(anchor, "reworded"))
            second = module.current_inventory(self.repo)
            assert first == second
            """
        )
        result = scan(fixture, FIXTURE_GENERATOR)
        self.assertTrue(result.sites, "fixture must register a loader site")
        self.assertEqual(1, len(result.violations), result.violations)
        self.assertIn("test_example", result.violations[0])
        self.assertIn("current_inventory", result.violations[0])
        self.assertIn("scripts/test/test_codex_skills.py", result.violations[0])
        self.assertIn("scripts/codex-skills.py", result.violations[0])

    def test_guard_goes_red_on_transitive_in_process_memo_call(self) -> None:
        """build -> render_tree -> current_inventory must be caught too."""
        result = scan(_fixture_test("module.build(self.repo, self.out)"), FIXTURE_GENERATOR)
        self.assertEqual(1, len(result.violations), result.violations)
        self.assertIn("build -> render_tree -> current_inventory", result.violations[0])

    def test_guard_goes_red_on_transitive_assembled_methodology(self) -> None:
        result = scan(_fixture_test("module.documents(self.repo)"), FIXTURE_GENERATOR)
        self.assertEqual(1, len(result.violations), result.violations)
        self.assertIn("documents -> assembled_methodology", result.violations[0])

    def test_guard_goes_red_on_sys_modules_alias(self) -> None:
        """sys.modules[module_name].build(...) is one line from the real idiom."""
        result = scan(
            _fixture_test("sys.modules[module_name].build(self.repo, self.out)"),
            FIXTURE_GENERATOR,
        )
        self.assertEqual(1, len(result.violations), result.violations)
        self.assertIn("build -> render_tree -> current_inventory", result.violations[0])

    def test_guard_goes_red_on_bare_alias_rebinding(self) -> None:
        """`m = module; m.build(...)` must fail closed, not slip through."""
        result = scan(_fixture_test("m = module\nm.build(self.repo, self.out)"), FIXTURE_GENERATOR)
        self.assertEqual(1, len(result.violations), result.violations)
        self.assertIn("bare value", result.violations[0])
        self.assertIn("Assign the module to a plain local", result.violations[0])

    def test_guard_goes_red_on_getattr_access(self) -> None:
        """getattr(module, "current_inventory") is a bare use, so it fails closed."""
        result = scan(
            _fixture_test('getattr(module, "current_inventory")(self.repo)'),
            FIXTURE_GENERATOR,
        )
        self.assertEqual(1, len(result.violations), result.violations)
        self.assertIn("bare value", result.violations[0])

    def test_guard_fails_closed_when_module_variable_is_unresolvable(self) -> None:
        """A loader site it cannot interpret is a failure, never a silent pass."""
        fixture = textwrap.dedent(
            '''
            GENERATOR = Path("scripts/codex-skills.py")

            class Fixture:
                def test_example(self):
                    spec = importlib.util.spec_from_file_location(name, self.repo / GENERATOR)
                    exec_somehow(spec)
            '''
        )
        result = scan(fixture, FIXTURE_GENERATOR)
        self.assertEqual(1, len(result.violations), result.violations)
        self.assertIn("cannot verify", result.violations[0])
        self.assertIn("Assign the module to a plain local", result.violations[0])

    def test_guard_goes_red_when_the_loader_idiom_is_renamed(self) -> None:
        """Threshold self-test: a wrapper the guard cannot see must not read green."""
        fixture = textwrap.dedent(
            '''
            GENERATOR = Path("scripts/codex-skills.py")

            class Fixture:
                def test_example(self):
                    module = load_generator_module(self.repo / GENERATOR)
                    module.build(self.repo, self.out)
            '''
        )
        result = scan(fixture, FIXTURE_GENERATOR)
        self.assertEqual([], result.sites, "renamed loader must be invisible to scan()")
        self.assertLess(
            len(result.sites),
            EXPECTED_MINIMUM_LOADER_SITES,
            "a source whose loader idiom the guard cannot see must trip the "
            "site-count threshold rather than report success",
        )

    def test_guard_stays_green_on_symbols_that_cannot_reach_a_memo(self) -> None:
        """It must not fire on the real, legitimate in-process usages."""
        fixture = _fixture_test(
            """
            occurrences = module.inventory_document(doc, self.repo)
            module.transform(doc.text, occurrences)
            """
        )
        self.assertEqual([], scan(fixture, FIXTURE_GENERATOR).violations)

    def test_guard_ignores_loaders_for_other_files(self) -> None:
        """PROMPT_GENERATOR / bin tool loaders are out of scope by construction."""
        fixture = textwrap.dedent(
            '''
            PROMPT_GENERATOR = Path(".codex/lib/prompt-wrappers.py")

            class Fixture:
                def test_example(self):
                    spec = importlib.util.spec_from_file_location(
                        name, self.repo / PROMPT_GENERATOR)
                    module = importlib.util.module_from_spec(spec)
                    module.current_inventory(self.repo)
            '''
        )
        result = scan(fixture, FIXTURE_GENERATOR)
        self.assertEqual([], result.sites)
        self.assertEqual([], result.violations)


class MemoRetirementPinTests(unittest.TestCase):
    """The retirement pin must key on a real assignment, not a surviving name."""

    def test_pin_sees_real_module_level_assignments(self) -> None:
        self.assertEqual(set(MEMO_NAMES), set(MEMO_NAMES) & memo_assignments(FIXTURE_GENERATOR))

    def test_pin_goes_red_when_assignment_is_deleted_but_comment_remains(self) -> None:
        """Substring containment would stay green here. An AST check must not."""
        stripped = FIXTURE_GENERATOR.replace(
            "_ASSEMBLED_METHODOLOGY_MEMO: dict = {}",
            "# _ASSEMBLED_METHODOLOGY_MEMO was removed; see the memo comment above",
        )
        self.assertIn("_ASSEMBLED_METHODOLOGY_MEMO", stripped, "name must survive in a comment")
        self.assertNotIn("_ASSEMBLED_METHODOLOGY_MEMO", memo_assignments(stripped))
        self.assertIn("_CURRENT_INVENTORY_MEMO", memo_assignments(stripped))


class CodexMemoInvariantTests(unittest.TestCase):
    """The live assertions against the real repository files."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.generator_source = GENERATOR_PATH.read_text(encoding="utf-8")
        cls.test_source = GENERATOR_TESTS_PATH.read_text(encoding="utf-8")
        cls.result = scan(cls.test_source, cls.generator_source)

    def test_no_in_process_generator_load_reaches_a_memoized_function(self) -> None:
        self.assertEqual(
            [],
            self.result.violations,
            "process-scoped memo invariant violated:\n  "
            + "\n  ".join(self.result.violations),
        )

    def test_guard_actually_observed_the_real_loader_sites(self) -> None:
        """Non-vacuity: a guard that scanned nothing must not report success."""
        self.assertGreaterEqual(
            len(self.result.sites),
            EXPECTED_MINIMUM_LOADER_SITES,
            "expected at least "
            f"{EXPECTED_MINIMUM_LOADER_SITES} in-process generator loader sites in "
            "scripts/test/test_codex_skills.py, found "
            f"{len(self.result.sites)}: {self.result.sites}. If a site was genuinely "
            "removed, lower EXPECTED_MINIMUM_LOADER_SITES in the same change; "
            "otherwise the loader idiom moved and this guard has gone blind.",
        )

    def test_call_graph_resolves_the_real_memoized_functions(self) -> None:
        """Guards the graph builder itself against silently resolving nothing."""
        graph = build_call_graph(self.generator_source)
        for name in MEMOIZED_FUNCTIONS:
            self.assertIn(name, graph, f"{name}() not found in scripts/codex-skills.py")
        self.assertIsNotNone(
            reaches(graph, "build", MEMOIZED_FUNCTIONS),
            "build() must reach a memoized function; if it no longer does, the "
            "call graph builder is broken, not the generator",
        )

    def test_memos_still_exist_or_this_guard_retires(self) -> None:
        """Retirement condition, enforced: memos gone -> delete this file."""
        bound = memo_assignments(self.generator_source)
        for memo in MEMO_NAMES:
            self.assertIn(
                memo,
                bound,
                f"{memo} is no longer assigned at module level in "
                "scripts/codex-skills.py. This guard exists only to protect the "
                "process-scoped memos; delete "
                "bin/tests/test_codex_memo_invariant.py in the same change.",
            )


if __name__ == "__main__":
    unittest.main()
