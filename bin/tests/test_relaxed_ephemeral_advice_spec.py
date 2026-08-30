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
Performance: static reads of ten tracked text files plus three machinery trees.
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
        "Decide or adopt architecture",
        "Write an ADR, plan, or spec",
        "Unfamiliar multi-read advisory work",
        "An implementation request",
        "The `default` and `strict` profiles are unchanged by this override",
        "Chat becomes binding only when promoted to a ticket, Brief, Plan, ADR, requirements or decision artifact, acceptance criteria, or implementation request",
    ):
        assert expected in compact, f"canonical decision corpus missing {expected!r}"


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
