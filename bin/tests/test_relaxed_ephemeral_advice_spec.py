#!/usr/bin/env python3
"""
Regression spec for the relaxed ephemeral chat-advice routing contract.

Purpose: Pin the ordered four-predicate override, its five canonical carrier
    rows, subordinate routing mirrors, remaining-signal backstop, decision
    corpus, profile isolation, and scope-rule salience without introducing new
    runtime machinery.
Public API: pytest test functions (no importable production symbols).
Upstream deps: canonical methodology, agent, reference, and public-doc prose.
Downstream consumers: bin-tests CI (`pytest bin/tests/`).
Failure modes: missing or reordered binding prose fails with the affected path
    and contract fragment in the assertion message.
Performance: static reads of tracked text files and machinery trees.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent

RISK = REPO_ROOT / "content/sections/04-risk-classification.md"
DELEGATION = REPO_ROOT / "content/sections/02-delegation.md"
SUBAGENT = REPO_ROOT / "content/references/subagent-protocol.md"
DETAIL = REPO_ROOT / "content/references/delegation-detail.md"
DESIGN = REPO_ROOT / "content/references/design-goals.md"
ENGINEER = REPO_ROOT / "content/agents/engineer.md"
SKEPTIC = REPO_ROOT / "content/agents/skeptic.md"
DOCS = REPO_ROOT / "docs/index.html"
RISK_SLIDES = REPO_ROOT / "docs/slides/risk-classification-slides.md"
PROFILE_SLIDES = REPO_ROOT / "docs/slides/profiles-slides.md"
CANONICAL_SKILL = REPO_ROOT / "content/SKILL.md"
CODEX_SKILL = REPO_ROOT / ".codex/skills/dinostack/SKILL.md"
CODEX_METHODOLOGY = REPO_ROOT / ".codex/skills/dinostack/METHODOLOGY.md"

PREDICATES = (
    "output is chat text only",
    "zero filesystem or external-state writes",
    "the user did not ask to decide, adopt, standardize, document, or implement",
    "the response is not acceptance criteria or governing downstream input",
)

CARRIERS = (
    "Answer a question from context in memory",
    "Synthesize already-returned subagent results",
    "Architecture decision constraining future choices",
    "Document synthesis / architecture / planning",
    "Research that produces an artifact (doc, plan, recommendation)",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing contract file: {path.relative_to(REPO_ROOT)}"
    text = path.read_text(encoding="utf-8")
    assert text, f"empty contract file: {path.relative_to(REPO_ROOT)}"
    return text


def _assert_in_order(text: str, fragments: tuple[str, ...], label: str) -> None:
    haystack = " ".join(text.split()).lower()
    needles = tuple(" ".join(fragment.split()).lower() for fragment in fragments)
    positions = [haystack.find(fragment) for fragment in needles]
    missing = [fragment for fragment, position in zip(fragments, positions) if position < 0]
    assert not missing, f"{label} missing ordered fragments: {missing}"
    assert positions == sorted(positions), (
        f"{label} fragments are out of order: "
        + ", ".join(f"{fragment!r}@{position}" for fragment, position in zip(fragments, positions))
    )


def test_canonical_override_orders_predicates_carriers_and_backstop() -> None:
    text = _read(RISK)
    heading = "#### Relaxed ephemeral chat-advice override"
    start = text.find(heading)
    assert start >= 0, f"{RISK.relative_to(REPO_ROOT)} missing {heading!r}"
    end = text.find("**`relaxed` (additional Low overrides):**", start)
    assert end > start, "ephemeral-advice contract must precede the remaining relaxed overrides"
    block = text[start:end]

    _assert_in_order(block, PREDICATES, "canonical predicate gate")
    _assert_in_order(block, CARRIERS, "canonical carrier scan")
    compact_block = " ".join(block.split()).lower()
    assert compact_block.find(PREDICATES[-1].lower()) < compact_block.find(CARRIERS[0].lower()), (
        "all four predicates must pass before the five carrier rows are considered"
    )
    backstop = "scan the complete remaining Elevated signal list"
    assert backstop in block, "canonical override is missing the remaining-signal backstop"
    assert compact_block.find(CARRIERS[-1].lower()) < compact_block.find(backstop.lower()), (
        "the complete remaining Elevated scan must run after the five carrier rows"
    )
    for retained_signal in (
        "Multi-read investigation",
        "unfamiliar-area exploration",
        "protocol or infrastructure edits",
        "state changes",
        "security-sensitive work",
        "shared utilities",
        "high-stakes work",
        "emergent interactions",
    ):
        assert retained_signal.lower() in compact_block, (
            f"remaining-signal backstop omits {retained_signal!r}"
        )


def test_canonical_override_pins_decision_corpus_and_profile_isolation() -> None:
    text = _read(RISK)
    compact = " ".join(text.split())
    for expected in (
        "How would you recommend changing DinoStack?",
        "Low and direct in `relaxed` only when chat-only and non-exploratory",
        "Breadth alone does not make it exploratory",
        "Decide or adopt architecture",
        "Write an ADR, plan, or spec",
        "explicitly requests unfamiliar, repository-specific, multi-file or multi-read evidence",
        "An implementation request",
        "The `default` and `strict` profiles are unchanged by this override",
        "Chat becomes binding only when promoted to a ticket, Brief, Plan, ADR, requirements or decision artifact, acceptance criteria, or implementation request",
    ):
        assert expected in compact, f"canonical decision corpus missing {expected!r}"


def test_relaxed_advice_is_classified_before_the_first_project_read() -> None:
    canonical = " ".join(_read(RISK).split())
    for expected in (
        "no-investigation fast path",
        "Mandatory activation and skill-loading reads do not disqualify it",
        "answer immediately from context already held or classify Elevated before the first project-content read or tool call",
        "must not start project exploration as Low and promise to promote later",
        "explicit unfamiliar or multi-read investigation request is Elevated before any project-content read",
    ):
        assert expected in canonical, f"canonical timing boundary missing {expected!r}"

    for path in (DELEGATION, SUBAGENT):
        mirror = " ".join(_read(path).split())
        assert "no-investigation fast path" in mirror
        assert "before the first project-content read or tool call" in mirror
        assert "Never start project exploration as Low and promise to promote later" in mirror
        assert "explicit unfamiliar or multi-read investigation request is Elevated" in mirror
        assert "content/sections/04-risk-classification.md" in mirror


def test_skill_surfaces_relaxed_pre_read_gate_before_general_guidance() -> None:
    required = (
        "Early relaxed-advice routing gate",
        "apply risk classification before the first project-content read",
        "Relaxed ephemeral chat advice remains direct only when the answer can be produced from context already held",
        "otherwise classify Elevated before reading",
        "explicit user request for unfamiliar, repository-specific, multi-file or multi-read evidence is Elevated and delegated before any project-content read",
    )
    for path in (CANONICAL_SKILL, CODEX_SKILL):
        text = _read(path)
        compact = " ".join(text.split())
        for expected in required:
            assert expected in compact, (
                f"{path.relative_to(REPO_ROOT)} missing early routing gate fragment {expected!r}"
            )
        gate = text.find("**Early relaxed-advice routing gate.**")
        assert gate < text.find("**Conductor default: act, don't ask.**")
        assert gate < text.find("## Rules (read these files)")

    methodology = _read(CODEX_METHODOLOGY)
    _assert_in_order(methodology, PREDICATES, "generated Codex predicate scope")
    _assert_in_order(methodology, CARRIERS, "generated Codex carrier scope")


def test_broad_relaxed_prompt_does_not_imply_investigation() -> None:
    required = (
        "Within that relaxed-only override, breadth alone is not an investigation request",
        "How would you recommend changing DinoStack?",
        "bounded high-level advice from the methodology and context loaded during mandatory skill activation",
        "state specificity or evidence limitations when useful",
        "do not explore the project merely to improve specificity",
        "An explicit user request for unfamiliar, repository-specific, multi-file or multi-read evidence is Elevated and delegated before any project-content read",
    )
    for path in (RISK, CANONICAL_SKILL, CODEX_SKILL):
        compact = " ".join(_read(path).split())
        for expected in required:
            assert expected in compact, (
                f"{path.relative_to(REPO_ROOT)} missing broad-prompt distinction {expected!r}"
            )


def test_explicit_investigation_rule_preserves_the_remaining_signal_safety_floor() -> None:
    required = (
        "narrows only whether advisory wording constitutes an investigation request",
        "every other canonical Elevated signal still wins",
        "security-sensitive",
        "high-stakes",
        "state-changing",
        "protocol or infrastructure",
    )
    for path in (RISK, CANONICAL_SKILL, CODEX_SKILL):
        compact = " ".join(_read(path).split())
        for expected in required:
            assert expected in compact, (
                f"{path.relative_to(REPO_ROOT)} missing remaining-signal safety floor "
                f"{expected!r}"
            )


def test_delegation_failure_never_falls_back_to_direct_project_investigation() -> None:
    required = (
        "If the required named-agent route cannot start",
        "report the blocker",
        "bounded context-only advice",
        "does not perform the requested investigation",
        "never fall back to conductor multi-file or project exploration",
    )
    for path in (RISK, CANONICAL_SKILL, CODEX_SKILL):
        compact = " ".join(_read(path).split())
        for expected in required:
            assert expected in compact, (
                f"{path.relative_to(REPO_ROOT)} missing fail-closed delegation rule "
                f"{expected!r}"
            )


def test_relaxed_implementation_routes_before_existing_branch_inspection() -> None:
    canonical_required = (
        "Implement the recommended DinoStack changes.",
        "outside the relaxed chat-advice exception",
        "state-changing Elevated",
        "named Engineer/Worker route",
        "before the first non-mandatory project-content read",
        "Existing candidate commits or an already-populated feature branch",
        "do not authorize conductor-side inspection, verification, or implementation",
        "fail closed",
        "git diff, tests, or source reads",
    )
    canonical = " ".join(_read(RISK).split())
    for expected in canonical_required:
        assert expected in canonical, f"canonical implementation routing missing {expected!r}"

    complete_binding_signature = (
        "Existing candidate commits or an already-populated feature branch do not authorize "
        "conductor-side inspection, verification, or implementation"
    )
    source_sites = (RISK, CANONICAL_SKILL, DELEGATION, SUBAGENT, DETAIL)
    binding_sites = [
        path.relative_to(REPO_ROOT)
        for path in source_sites
        if complete_binding_signature in " ".join(_read(path).split())
    ]
    assert binding_sites == [RISK.relative_to(REPO_ROOT)], (
        "complete implementation-routing binding must exist only at the canonical risk site; "
        f"found copies in {binding_sites}"
    )

    pointer_requirements = {
        DELEGATION: ("Implementation requests are state-changing Elevated", "exclusively governs"),
        SUBAGENT: ("Implementation requests are state-changing Elevated", "canonical pre-read"),
        DETAIL: ("Implementation requests are state-changing Elevated", "defined only in"),
    }
    for path, fragments in pointer_requirements.items():
        compact = " ".join(_read(path).split())
        assert "content/sections/04-risk-classification.md" in compact
        for expected in fragments:
            assert expected in compact, (
                f"{path.relative_to(REPO_ROOT)} missing narrow routing pointer {expected!r}"
            )

    skill = " ".join(_read(CANONICAL_SKILL).split())
    for expected in (
        "State-changing implementation requests (implement, change, fix, or build)",
        "named Engineer/Worker route before any non-mandatory project read or command",
        "Until that route starts, do not inspect or verify candidate work; a failed route ends in a blocker",
        "Canonical candidate-branch and fail-closed details",
        "content/sections/04-risk-classification.md",
    ):
        assert expected in skill, f"early skill routing signal missing {expected!r}"


def test_early_gate_is_scoped_to_relaxed_after_all_predicates() -> None:
    for path in (CANONICAL_SKILL, CODEX_SKILL):
        compact = " ".join(_read(path).split())
        guard = "only after activation resolves `profile=relaxed` and all four canonical predicates pass"
        exclusion = "If profile is `default` or `strict`, this gate does not apply"
        baseline = "the motivating advisory retains its existing Elevated routing"
        prompt = "How would you recommend changing DinoStack?"
        for expected in (guard, exclusion, baseline, prompt):
            assert expected in compact, (
                f"{path.relative_to(REPO_ROOT)} missing cross-profile guard {expected!r}"
            )
        assert compact.find(guard) < compact.find(prompt)
        assert compact.find(exclusion) < compact.find(prompt)

    risk = " ".join(_read(RISK).split())
    relaxed_gate = "In the `relaxed` profile only, advice may remain **Low** when all four predicates pass"
    breadth = "Within that relaxed-only override, breadth alone is not an investigation request"
    assert relaxed_gate in risk
    assert risk.find(relaxed_gate) < risk.find(breadth), (
        "canonical breadth guidance must sit after the explicit relaxed predicate gate"
    )
    assert risk.find(PREDICATES[-1]) < risk.find(breadth), (
        "all four predicates must precede the broad-prompt exception"
    )


def test_five_carriers_and_order_are_mirrored_at_routing_sites() -> None:
    for path in (DELEGATION, SUBAGENT):
        text = _read(path)
        _assert_in_order(text, CARRIERS, str(path.relative_to(REPO_ROOT)))
        assert "relaxed ephemeral chat-advice override" in text, (
            f"{path.relative_to(REPO_ROOT)} lacks the canonical override pointer"
        )
        assert "all four predicates" in text and "remaining Elevated signal" in text, (
            f"{path.relative_to(REPO_ROOT)} lacks predicate/backstop routing"
        )

    detail = _read(DETAIL)
    _assert_in_order(detail, PREDICATES, "delegation-detail predicate mirror")
    compact_detail = " ".join(detail.split())
    assert "five carrier rows" in compact_detail
    assert "remaining Elevated signal list" in compact_detail


def test_common_rationalization_preserves_relaxed_chat_advice_exception() -> None:
    detail = _read(DETAIL)
    prefix = '- "I have subagent output in hand, so writing from it is just synthesizing results"'
    paragraph = next(
        (line for line in detail.splitlines() if line.startswith(prefix)),
        "",
    )
    assert paragraph, "delegation-detail is missing the subagent-synthesis rationalization"
    compact = paragraph.lower()
    assert "qualifying relaxed ephemeral chat advice" in compact
    assert "content/sections/04-risk-classification.md" in paragraph
    assert "Relaxed ephemeral chat-advice override" in paragraph
    assert "durable artifacts and non-qualifying recommendations remain elevated" in compact
    stale_blanket = (
        "not authoring a new document, specification, plan, or recommendation. "
        "The moment the output is a new artifact"
    )
    assert stale_blanket not in paragraph, (
        "the rationalization must not classify every new recommendation as Elevated"
    )


def test_scope_rule_precedes_autonomy_and_engineer_duplication_is_consolidated() -> None:
    delegation = _read(DELEGATION)
    scope = "**Scope discipline.** Do only the requested scope"
    autonomy = "**Proactive autonomy.**"
    assert scope in delegation, "delegation kernel is missing the salient scope rule"
    assert delegation.find(scope) < delegation.find(autonomy), (
        "scope discipline must appear before proactive autonomy"
    )

    engineer = _read(ENGINEER)
    assert engineer.count("**Stay in scope.**") == 1, (
        "Engineer must carry one consolidated scope rule, not repeated scope prose"
    )
    assert "reclassify rather than silently expand" in " ".join(engineer.split())
    assert engineer.find("**Stay in scope.**") < engineer.find("## Reading your spawn prompt")

    skeptic = _read(SKEPTIC)
    assert "scope" in skeptic.lower(), "existing Skeptic scope review must remain present"


def test_design_and_public_docs_explain_the_relaxed_dial() -> None:
    for path in (DESIGN, DOCS, RISK_SLIDES, PROFILE_SLIDES):
        text = _read(path)
        assert "ephemeral" in text.lower() and "chat" in text.lower(), (
            f"{path.relative_to(REPO_ROOT)} lacks the relaxed ephemeral-chat explanation"
        )
        assert "default" in text and "strict" in text, (
            f"{path.relative_to(REPO_ROOT)} does not preserve profile boundaries"
        )


def test_no_new_runtime_machinery_is_keyed_to_the_override() -> None:
    forbidden_roots = (
        REPO_ROOT / "hooks",
        REPO_ROOT / "scripts",
        REPO_ROOT / ".github/workflows",
    )
    markers = ("ephemeral chat advice", "ephemeral chat-advice", "ephemeral_advice", "relaxed advice")
    matches = []
    for root in forbidden_roots:
        assert root.is_dir(), f"missing machinery root: {root.relative_to(REPO_ROOT)}"
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            lower_text = text.lower()
            for marker in markers:
                if marker.lower() in lower_text:
                    matches.append(f"{path.relative_to(REPO_ROOT)}: {marker}")
    assert not matches, (
        "relaxed advice must remain prose-routed, without new hook, script, "
        f"workflow, telemetry, delivery, or worktree machinery: {matches}"
    )
