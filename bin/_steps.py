"""
Purpose: Step ids for the methodology's own steps (phases, route branches,
         gates, writeback sites), so a step can be counted and changed on its
         own. The ids are derived at read time from the headings that
         already exist; nothing here is a hand-kept list of steps. This
         header is the single canonical home for the id rule and both maps.
         Catches: a step whose fire count and outcomes cannot be read
         because nothing names it. Retire when /ds-evaluate stops reporting
         [steps].

Id rule:
    Sources: content/commands/*.md and content/sections/[0-9][0-9]-*.md.
    Lines inside fenced blocks (``` or ~~~) are not headings.
    Id: <stem>/<anchor>. The stem is the file name without `.md` and without
    a leading `ds-` (ds-implement-ticket.md -> implement-ticket).
    Anchor: `phase-<tok>` for a heading `Phase <tok>: ...` (tok lowercased,
    e.g. phase-8.5, phase-0a-open-goal); otherwise a GitHub-style slug:
    lowercased, characters other than letters, digits, `_`, `-` and space
    dropped, spaces to `-`, runs of `-` collapsed, ends trimmed.
    Collisions: headings with the same anchor in one file are qualified by
    their nearest `##` ancestor's anchor
    (implement-ticket/phase-1/if-tracker-is-none). Only ids still shared
    after that are reported in `collisions`, and none of them is a step.

Maps:
    SITE_TO_STEP: `data.site` of tracker_writeback and knowledge_commit rows
    -> step id. Outcome: data.outcome (tracker_writeback), data.status
    (knowledge_commit). Any other site is reported as unmapped.
    LEDGER_FIELD_TO_STEP: .agentic/ticket-ledger.jsonl field -> step id.
    One record feeds each step at most once (ledger_outcomes):
      risk_class      non-null; outcome = the value.
      elevated_route  records whose risk_class is Elevated; outcome = the
                      value, null counted as `unknown`.
      skeptic_rounds  non-null; outcome = `rounds:<n>`.
      qa_status       non-null; outcome = the value (skipped:* included).
    step_outcome rows (bin/ds-emit, written by the bin/ds-ticket-* helpers)
    carry their own `data.step` and `data.outcome`; each helper's manifest
    header defines its outcome enum. Their step literals are the standalone
    `<stem>/<anchor>` words on a `ds_step_outcome` line in bin/ds-ticket-*.

One step source per row: step_outcome -> data.step; tracker_writeback and
    knowledge_commit -> data.site; ledger records -> LEDGER_FIELD_TO_STEP.
    Spawn rows and the top-level `phase` field are never read.

Real 0 vs ABSENT: each instrumented step has one source (step_sources):
    `helper:<script>` (the bin/ds-ticket-* file its literal is in),
    `site:<site>`, or `ledger`. A step with 0 fires is a real 0 only when
    its source wrote at least one row in the window (row_source; ledger
    records count by opened_ts); otherwise its count is ABSENT. A site step
    is its own only source, so its 0 is always ABSENT.

Public API:
    derive_steps(repo) -> {"steps": {id: {file, line, heading}},
                           "collisions": [{id, file, lines}]}
    event_step(row) -> (step, outcome, source) | ("unmapped", site, source)
                       | None
    ledger_outcomes(record) -> [(step, outcome, source)]
    helper_step_literals(repo) -> set[str]
    step_sources(repo) -> {step: source}
    row_source(row) -> source | None
    instrumented_steps(repo) -> set[str]

Upstream deps: Python 3 stdlib.

Downstream consumers: bin/_eval.py (the `steps` section of evaluate());
    content/references/events-log.md (Step ids pointer);
    bin/tests/test_steps.py.

Failure modes: an unreadable source file is skipped; never raises.

Performance: one read of each command and section file.
"""
from __future__ import annotations

import re
from pathlib import Path

SITE_TO_STEP = {
    "W1": "implement-ticket/tracker-writeback-w1",
    "phase-11e": "implement-ticket/phase-11e",
}

LEDGER_FIELD_TO_STEP = {
    "risk_class": "implement-ticket/risk-classification-declaration-unconditional-runs-on-every-ticket",
    "elevated_route": "04-risk-classification/elevated-routes",
    "skeptic_rounds": "implement-ticket/phase-6",
    "qa_status": "implement-ticket/phase-6b",
}

_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_PHASE_RE = re.compile(r"^Phase\s+([0-9][0-9A-Za-z.\-]*)\s*:")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_LITERAL_RE = re.compile(r"(?:^|\s)([a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9./-]*)(?=\s|$)")


def _anchor(text: str) -> str:
    m = _PHASE_RE.match(text)
    if m:
        return "phase-" + m.group(1).lower()
    slug = re.sub(r"[^\w\- ]", "", text.lower())
    slug = re.sub(r"-+", "-", slug.replace(" ", "-"))
    return slug.strip("-")


def _sources(repo: Path) -> list[Path]:
    content = Path(repo) / "content"
    return sorted((content / "commands").glob("*.md")) + sorted((content / "sections").glob("[0-9][0-9]-*.md"))


def _headings(path: Path) -> list[tuple[int, int, str, str]]:
    """(line, level, text, nearest ## anchor) for each heading outside fences."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out, fence, h2 = [], None, ""
    for n, line in enumerate(lines, 1):
        f = _FENCE_RE.match(line)
        if f:
            mark = f.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence) and not f.group(2).strip():
                fence = None
            continue
        if fence is not None:
            continue
        h = _HEADING_RE.match(line)
        if not h:
            continue
        level, text = len(h.group(1)), h.group(2)
        anchor = _anchor(text)
        if level == 2:
            h2 = anchor
        out.append((n, level, text, h2 if level > 2 else ""))
    return out


def derive_steps(repo) -> dict:
    steps: dict[str, dict] = {}
    collisions: list[dict] = []
    root = Path(repo)
    for path in _sources(root):
        stem = path.stem[3:] if path.stem.startswith("ds-") else path.stem
        rel = str(path.relative_to(root))
        heads = _headings(path)
        counts: dict[str, int] = {}
        for _, _, text, _ in heads:
            counts[_anchor(text)] = counts.get(_anchor(text), 0) + 1
        ids: dict[str, list[tuple[int, str]]] = {}
        for n, _, text, h2 in heads:
            anchor = _anchor(text)
            if counts[anchor] > 1 and h2:
                anchor = f"{h2}/{anchor}"
            ids.setdefault(f"{stem}/{anchor}", []).append((n, text))
        for sid, hits in ids.items():
            if len(hits) > 1:
                collisions.append({"id": sid, "file": rel, "lines": [n for n, _ in hits]})
            else:
                steps[sid] = {"file": rel, "line": hits[0][0], "heading": hits[0][1]}
    return {"steps": steps, "collisions": collisions}


def event_step(row: dict):
    data = row.get("data") if isinstance(row, dict) else None
    if not isinstance(data, dict):
        return None
    event = row.get("event")
    if event == "step_outcome":
        step = data.get("step")
        if not isinstance(step, str) or not step:
            return None
        return step, str(data.get("outcome")), "step_outcome"
    if event in ("tracker_writeback", "knowledge_commit"):
        site = data.get("site")
        outcome = data.get("outcome") if event == "tracker_writeback" else data.get("status")
        if site in SITE_TO_STEP:
            return SITE_TO_STEP[site], str(outcome), event
        return "unmapped", str(site), event
    return None


def ledger_outcomes(record: dict) -> list[tuple[str, str, str]]:
    out = []
    risk = record.get("risk_class")
    if risk is not None:
        out.append((LEDGER_FIELD_TO_STEP["risk_class"], str(risk), "ledger:risk_class"))
    if risk == "Elevated":
        route = record.get("elevated_route")
        out.append((LEDGER_FIELD_TO_STEP["elevated_route"], "unknown" if route is None else str(route),
                    "ledger:elevated_route"))
    rounds = record.get("skeptic_rounds")
    if rounds is not None:
        out.append((LEDGER_FIELD_TO_STEP["skeptic_rounds"], f"rounds:{rounds}", "ledger:skeptic_rounds"))
    qa = record.get("qa_status")
    if qa is not None:
        out.append((LEDGER_FIELD_TO_STEP["qa_status"], str(qa), "ledger:qa_status"))
    return out


def _helper_steps(repo) -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted((Path(repo) / "bin").glob("ds-ticket-*")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if "ds_step_outcome " in line and not line.lstrip().startswith("#"):
                found.update({step: path.name for step in _LITERAL_RE.findall(line)})
    return found


def helper_step_literals(repo) -> set[str]:
    return set(_helper_steps(repo))


def step_sources(repo) -> dict[str, str]:
    out = {step: f"site:{site}" for site, step in SITE_TO_STEP.items()}
    out.update({step: "ledger" for step in LEDGER_FIELD_TO_STEP.values()})
    out.update({step: f"helper:{name}" for step, name in _helper_steps(repo).items()})
    return out


def row_source(row: dict) -> str | None:
    data = row.get("data") if isinstance(row, dict) else None
    if not isinstance(data, dict):
        return None
    if row.get("event") == "step_outcome":
        return f"helper:{data.get('helper')}"
    if row.get("event") in ("tracker_writeback", "knowledge_commit"):
        return f"site:{data.get('site')}"
    return None


def instrumented_steps(repo) -> set[str]:
    return set(step_sources(repo))
