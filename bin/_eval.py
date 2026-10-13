"""
Purpose: Evaluation engine for the ds-eval telemetry program. Answers "what
         is working well and what is not" for one or more repos over one
         window: per-agent cost and value, Skeptic yield per round, work
         items (ticket-keyed spawns with PR outcome and rework), hook deny
         quality with operator labels, cost reconciled against the
         harness's own cost-state, and a ranked list of proposals (D1a-D3)
         plus the telemetry gaps that block the rest (D4).
         Catches: decisions made from a figure that silently treats missing
         telemetry as zero (every metric carries OK/ABSENT/PARTIAL with
         coverage), visible-token spend reported as total spend (cost is
         reconciled to cost-state, tolerance 0), and spawn cost that cannot
         be tied to a ticket or PR. Also hosts the ticket/PR/pricing helpers
         bin/ds-change-delta imports (moved here so both tools share one
         copy).
         Retire when /ds-evaluate and ds-change-delta stop calling it; until
         then it is the only reader that joins transcripts, hook spawn rows,
         fire rows and git history.

Public API:
    evaluate(repos, start, end, *, base=None, ticket_re=None, use_gh=True,
             stores=None, rates=None, include_sessions=False,
             use_feedback=True) -> dict
        Keys: meta, agents, skeptic_rounds, work_items, hooks, cost, mix,
        keepalive, decisions, gaps, plus `session_rows` (one session_summary() per
        in-window session) when include_sessions is True, so ds-change-delta
        can split a window by entrypoint without a second transcript pass.
        use_feedback=False skips the `ds-feedback list` read (labels are
        then absent, as when ds-feedback is unavailable), for a caller that
        reads no label-derived figure.
        With several repos the sections are computed over the union of their
        inputs (`hooks` pools each hook's rows across
        repos); decisions and gaps are computed per repo and carry a `repo`
        key, and each D2 decision carries that repo's own `hook_figures`
        (deny, joinable_deny, repeat_share, labelled, labelled_fp_rate) and
        `label_sample`, so a labelling step never reads pooled figures.
        Labels match a deny by (fire_label.hook, fire_key): one tool_use_id
        can carry denies from several hooks. `base=None` resolves each repo's base via
        _lib.resolve_base_branch. `stores` defaults to _transcripts.stores();
        `rates` defaults to _telemetry.load_rates(include_defaults=True).
        `stores` is a _transcripts.StoreSet (default resolve_stores()) or a
        list of store paths. meta.stores has one entry per store
        (_transcripts.store_entry: path, status scanned|partial, sessions)
        plus one per unreadable or missing requested store, whose `sessions`
        is None (ABSENT), never 0.
    metric(status, value, coverage=None, missing=()) -> dict
        The envelope every metric uses: {status: OK|ABSENT|PARTIAL, value,
        coverage, missing}. ABSENT means no input (value is None, never 0);
        PARTIAL means a named source or sample is incomplete; OK means the
        metric's input set is non-empty and every source it reads was
        available (coverage < 1 then says the input set is a subset, and
        `missing` names what it excludes).
    keepalive: {repo: section}, one per repo (never pooled). A section is
        pings {fired, passed, dropped, deleted, wrapped, unclassified}
        (_transcripts.Turn.outcome, ping turns timestamped in the window);
        passed_ping_usage {input, output, cache_read, cache_creation, usd};
        returns {"20-60"|"60-120"|"120-240"|"over 240": {with_ping,
        no_ping}}, each {returns, cold, avg_cache_read,
        avg_cache_creation}: a return is a human turn in the window more
        than 20 min after the previous non-ping main-chain request (any
        turn's request, a task notification's included), with_ping when a
        passed ping fell in that gap, cold when its first request created
        more than it read; and estimated_net_usd {usd,
        avoided_creation_tokens, avoided_creation_usd, passed_ping_usd},
        basis "estimate": each warm with-ping return's cache_read x the
        same bucket's no-ping cold rate, priced at (1h write - read), minus
        passed-ping dollars. Never a measured saving. A bucket with
        1-9 returns is PARTIAL "n < 10", with none ABSENT; with no ping
        turn in the window every figure is ABSENT, never 0.
    Ping usage: agents.conductor (usd and by_entrypoint) excludes keepalive
        ping turns; it included them before keepalive was split out, so a
        window with passed pings now reads lower by their usage. cost, mix
        and is_empty_session still count it, as visible spend the
        cost-state also records. ds-change-delta inherits only this; a
        keepalive cut should be the first real ping fire, not the merge.
    Additive figures (none feeds a decision rule):
        Empty session (is_empty_session, the one definition, also used by
        bin/ds-change-delta through session_rows[].empty): no usage record,
        conductor or subagent, and no cost-state spend (the cost-state
        record is absent or $0). cost.reconciled.empty_sessions and
        cost.no_cost_state.empty_sessions (each with empty_session_ids)
        count them inside the group they already belong to, so each
        session is in one group; both are left out of
        cost.window_total.coverage (numerator and denominator; the total is
        coverage_excludes_empty_sessions), and the reconciled ones out of
        cost.attributed_share.coverage's denominator. They add $0.
        skeptic_rounds.by_iteration.iteration_tagged_share (equal to its
        `coverage`) and findings_carrying_share (returns carrying
        signed_off or findings_count), with their counts in `returns`.
        work_items.items rows carry `tiers` (the key tiers of the item's
        spawns), `wall_spawns` (spawns with a wall time; wall_seconds is
        their sum and None when there is none) and `pr_history` (False
        when the repo has no readable merged-PR history), and three
        fields that say where an item with no `first_merged_pr` landed
        (none feeds first_merged_pr, pr_numbers, rework or D3):
        `own_prs_merged_in_window`: its key PR or its spawns' own PR
        numbers that are in the window's merge set ([start, end + 7d))
        but are not in pr_numbers (the PR carries no ticket id);
        `merged_outside_window`: the PR commits it names (those
        numbers, or a PR commit carrying its ticket id) that
        git_pr_merges finds on the base ref and that are not in the
        window's merge set, as [{number, merged_at, when
        "before"|"in"|"after"}]. `when` is "in" only for a
        `Merge pull request #N from ...` commit dated inside the
        window, a subject form the window's own merge set does not
        parse. A commit whose subject starts `Revert "` is never
        counted here;
        `ticket_mention_commits`: how many other first-parent commits
        on the base ref, at any date, carry its ticket id in subject or
        body (a count only: a mention is not a landing).
        The last two are [] and 0 when the search found none, and None
        when the item has a first_merged_pr (not searched) or the base
        ref could not be read. work_items.summary is {items, usd_median,
        wall_seconds_median}, the two medians as metric envelopes.
    session_summary(session, repo) -> dict
        {session_id, repo, first_ts (ISO), entrypoint, model, version,
        cost_usd, empty}. `empty` is is_empty_session(session).
        entrypoint/model/version are the (model, entrypoint,
        version) Usage key with the most conductor messages (subagent usage
        when the conductor has none; ties break on the sorted key); each is
        None when the session recorded no usage. cost_usd is
        Session.cost_usd (None unless cost-state covers the session).
    fire_key(row) -> str | None
        tool_use_id, else f"{session_id}@{ts}", else None.
    git_merged_prs(repo, base, start, end) -> list[dict] | None
        First-parent commits on `base` whose subject ends "(#N)", committed
        in [start, end): {number, sha, merged_at, subject, body, ids, reverts,
        revert_subject}. None when git cannot read the ref.
    git_pr_merges(repo, base, numbers, tickets, pattern) -> list[dict] | None
        One `git log --first-parent --grep` over the whole of `base`:
        commits whose subject ends "(#N)" or reads
        `Merge pull request #N from ...` for an N in `numbers`, or whose
        subject or body carries one of `tickets`: {number, subject,
        merged_at, ids}. `number` is None for any other subject. None
        when git cannot read the ref.
    order_decisions(decisions) -> list
        Sorted by (rank_usd is None, -(rank_usd or 0), -evidence.count, rule,
        subject).
    ROUTES: rule -> route (D1a/D1b/D1c update-agentic-engineering,
        D2 prune-harness, D3 tracker-ticket). Gaps have no route.
    Moved from bin/ds-change-delta (which imports them): _parse_ts,
        _as_int, _v2_coverage, _price_runs, _run_model, _ticket_index,
        _title_matches, _branch_matches, _attribute_prs, _ticket_row,
        _ticket_summary, _per_ticket_side, REENTRY_AFTER_MERGE,
        QA_FAIL_RESULTS, _TELEMETRY.

Work-item key (tiers, first match wins): 1 exactly one ticket id in the
    spawn's meta description; 2 one unambiguous ticket id among the hook
    task_ids joined to the spawn by agent_id or tool_use_id; 3 the spawn's
    own single pr_created; 4 the first PR created in the same session at or
    after the spawn ends. A PR ref's repo must equal the evaluated repo's
    owner/name; a ref with repo None matches only a merged PR number of that
    repo and is marked repo_inferred. A tier-3/4 PR resolves to the single
    ticket id its subject (else body) carries, else to `pr:<owner/name>#N`
    (the repo path when no origin slug resolves). Ticket
    prefixes are learned from the ticket_id values in .agentic/tasks.jsonl
    and .agentic/ticket-ledger.jsonl and from hook task_ids, with fallback
    [A-Z][A-Z0-9]+-N. Tier 4 is disabled for a run when its tier agreement
    has compared >= 20 and agree/compared < 0.8.

Upstream deps: Python 3 stdlib; bin/_lib.py (resolve_base_branch, _run),
    bin/_telemetry.py (pricing, hook spawn folding) and bin/_transcripts.py
    (sessions across every config-dir store), each loaded by resolved path.
    Reads <repo>/.agentic/events.jsonl (hook spawn rows),
    <repo>/.agentic/.enforcement-fires.jsonl (primary copy only),
    <repo>/.agentic/tasks.jsonl and ticket-ledger.jsonl (ticket prefixes),
    `git log --first-parent <base>` (the window, and one undated --grep
    pass for the items with no in-window merge), `git remote get-url origin`, and,
    `ds-feedback list --status triaged --repo <repo>` (operator fire labels,
    read unless use_feedback is False; a pure read that creates nothing),
    and, unless use_gh is False, `gh pr list` (open/closed
    state of engineer PRs not shown merged on the base ref).

Downstream consumers: bin/ds-eval (CLI); bin/ds-evaluate (/ds-evaluate's
    signal collection, via bin/ds-eval); bin/ds-change-delta (moved
    helpers, and its `eval` side: evaluate(use_gh=False,
    use_feedback=False, include_sessions=True) per window); bin/tests/test_ds_eval.py.

Failure modes: never raises on a missing store, file, ref, gh or pricing;
    each degrades to an ABSENT or PARTIAL metric whose `missing` names the
    reason. Read-only: no file, ref or tracker is written.

Performance: one _transcripts.sessions() pass per repo (dominant cost,
    about 1 min for 280 sessions), one read of events.jsonl and the fire log
    per repo, at most two `git log` per repo, at most one `gh pr list` and one
    `ds-feedback list` per repo.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BIN = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    loader = importlib.machinery.SourceFileLoader(name, str(_BIN / filename))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    loader.exec_module(mod)
    return mod


_LIB = _load("_eval_lib", "_lib.py")
_TELEMETRY = _load("_telemetry", "_telemetry.py")
_TRANSCRIPTS = _load("_eval_transcripts", "_transcripts.py")

REENTRY_AFTER_MERGE = timedelta(hours=1)
QA_FAIL_RESULTS = ("FAIL", "PARTIAL")

OK, ABSENT, PARTIAL = "OK", "ABSENT", "PARTIAL"
FALLBACK_TICKET_PREFIX = r"[A-Z][A-Z0-9]+"
LOOKAHEAD = timedelta(days=7)
REPEAT_WINDOW = timedelta(minutes=15)
TIER4_MIN_COMPARED = 20
TIER4_MIN_AGREEMENT = 0.8
LABEL_SAMPLE_SIZE = 5
GH_TIMEOUT_SECONDS = 60.0
ROUND_CAP_HOOK = "enforce-skeptic-round-cap"
OWN_VALUE_TYPES = ("skeptic", "qa-engineer", "engineer")
ROUTES = {
    "D1a": "update-agentic-engineering",
    "D1b": "update-agentic-engineering",
    "D1c": "update-agentic-engineering",
    "D2": "prune-harness",
    "D3": "tracker-ticket",
}
SECTIONS = ("agents", "skeptic_rounds", "work_items", "hooks", "cost", "mix", "keepalive", "decisions", "gaps")
IDLE_RETURN = timedelta(minutes=20)
RETURN_BUCKETS = (("20-60", 60), ("60-120", 120), ("120-240", 240), ("over 240", None))
MIN_BUCKET_N = 10
PING_OUTCOMES = ("passed", "dropped", "deleted", "wrapped", "unclassified")

_PR_SUBJECT_RE = re.compile(r"\(#(\d+)\)\s*$")
_REVERT_SUBJECT_RE = re.compile(r'^Revert "(.*)"\s*$')
_MERGE_COMMIT_SUBJECT_RE = re.compile(r"^Merge pull request #(\d+) from ")
_REVERTS_BODY_RE = re.compile(r"This reverts commit ([0-9a-f]{7,40})")
_SLUG_RE = re.compile(r"github\.com[:/]+([^/\s]+/[^/\s]+?)(?:\.git)?/?$")
_PREFIX_RE = re.compile(r"^([A-Z][A-Z0-9]+)-\d+")
_CONTEXT_TAG_RE = re.compile(r"\[[^\]]*\]$")


# ---------------------------------------------------------------------------
# Helpers moved from bin/ds-change-delta, which imports them.
# ---------------------------------------------------------------------------


def _parse_ts(value) -> datetime | None:
    """Parse an ISO8601 UTC timestamp, tolerating a trailing 'Z'. Mirrors
    bin/ds-hook-fire-report's _parse_ts (duplicated, not imported)."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        return int(value)
    return None


def _v2_coverage(spawn_data: dict) -> dict:
    return {
        "earliest": spawn_data["earliest_ts"].isoformat() if spawn_data["earliest_ts"] else None,
        "latest": spawn_data["latest_ts"].isoformat() if spawn_data["latest_ts"] else None,
        "rows_total": spawn_data["rows_total"],
    }


def _price_runs(items: list[tuple[str, dict]], rates: dict) -> dict:
    """Price (model, run) pairs on each run's own run_tokens. Exact-id and
    family-priced dollars are kept apart; a run without run_tokens is
    counted, never priced as zero."""
    by_model: dict[str, dict[str, int]] = {}
    tokens_null_runs = 0
    for model, run in items:
        if run["run_tokens"] is None:
            tokens_null_runs += 1
            continue
        bands = by_model.setdefault(model, dict.fromkeys(_TELEMETRY.BANDS, 0))
        for band, count in _TELEMETRY.token_bands(run["run_tokens"]).items():
            bands[band] += count
    tokens = dict.fromkeys(_TELEMETRY.BANDS, 0)
    exact = family = 0.0
    family_models: set[str] = set()
    unpriced: set[str] = set()
    for model, bands in by_model.items():
        for band, count in bands.items():
            tokens[band] += count
        priced = _TELEMETRY.price_tokens(model, bands, rates)
        if priced is None or priced["total"] is None:
            unpriced.add(model)
        elif priced["match"] == "exact":
            exact += priced["total"]
        else:
            family += priced["total"]
            family_models.add(model)
    return {
        "tokens": tokens,
        "tokens_null_runs": tokens_null_runs,
        "dollars_exact": round(exact, 6),
        "dollars_family_estimated": round(family, 6),
        "family_priced_models": sorted(family_models),
        "unpriced_models": sorted(unpriced),
    }


def _run_model(rec, run: dict) -> str:
    return run["model"] or rec.model or "(unknown)"


def _ticket_index(spawn_data: dict) -> dict[str, dict]:
    """Every ticket named by a v2 spawn's task_id or a ledger row, with the
    ts that places it in a window: its first v2 spawn, else its earliest
    ledger opened_ts."""
    index: dict[str, dict] = {}

    def entry(ticket: str) -> dict:
        return index.setdefault(ticket, {"recs": [], "repos": set(), "ledger": [],
                                         "first_spawn_ts": None, "ledger_opened_ts": None})

    for repo, rec in spawn_data["spawns"]:
        if not rec.task_id:
            continue
        e = entry(str(rec.task_id))
        e["recs"].append(rec)
        e["repos"].add(repo)
        first = _parse_ts(rec.start_ts) or _parse_ts(rec.runs[0]["end_ts"] if rec.runs else None)
        if first is not None and (e["first_spawn_ts"] is None or first < e["first_spawn_ts"]):
            e["first_spawn_ts"] = first
    for repo, row in spawn_data["ledger"]:
        ticket = row.get("ticket_id")
        if not ticket:
            continue
        e = entry(str(ticket))
        e["ledger"].append(row)
        e["repos"].add(repo)
        opened = _parse_ts(row.get("opened_ts"))
        if opened is not None and (e["ledger_opened_ts"] is None or opened < e["ledger_opened_ts"]):
            e["ledger_opened_ts"] = opened
    return index


def _title_matches(ticket: str, title: str) -> bool:
    t = re.escape(ticket)
    return re.match(rf"^\s*(?:\[{t}\]:?|{t}\s*:|[a-z]+\({t}\)!?:)", title, re.IGNORECASE) is not None


def _branch_matches(ticket: str, head_ref: str) -> bool:
    segment = head_ref.rsplit("/", 1)[-1]
    return re.match(rf"^{re.escape(ticket)}(?![0-9])", segment, re.IGNORECASE) is not None


def _attribute_prs(pr_nodes: dict[str, list[dict]], ledger: list[tuple[str, dict]],
                   tickets: set[str]) -> tuple[dict[str, list[dict]], list[dict]]:
    """A PR number a repo's ledger records is credited to every ledger
    ticket recording it and leaves that repo's fallback pool. Any other PR
    is credited by an anchored title prefix, else by the final
    `/`-separated segment of headRefName; a fallback PR matching more than
    one ticket is ambiguous and credited to none."""
    credits: dict[str, list[dict]] = {}
    ambiguous: list[dict] = []
    for repo, nodes in pr_nodes.items():
        ledger_map: dict[int, set[str]] = {}
        for ledger_repo, row in ledger:
            number = _as_int(row.get("pr_number"))
            if ledger_repo == repo and number is not None and row.get("ticket_id"):
                ledger_map.setdefault(number, set()).add(str(row["ticket_id"]))
        for node in nodes:
            number = _as_int(node.get("number"))
            pr = {"repo": repo, "number": number, "merged_at": _parse_ts(node.get("mergedAt"))}
            if number in ledger_map:
                for ticket in ledger_map[number]:
                    credits.setdefault(ticket, []).append(pr)
                continue
            title = node.get("title") or ""
            hits = [t for t in tickets if _title_matches(t, title)]
            if not hits:
                head_ref = node.get("headRefName") or ""
                hits = [t for t in tickets if _branch_matches(t, head_ref)]
            if len(hits) == 1:
                credits.setdefault(hits[0], []).append(pr)
            elif hits:
                ambiguous.append({"repo": repo, "number": number, "tickets": sorted(hits)})
    return credits, ambiguous


def _ticket_row(ticket: str, entry: dict, loop_states: list[dict], credited: list[dict],
                pr_status: str, pr_cutoff: datetime, rates: dict) -> dict:
    runs = [(rec, run) for rec in entry["recs"] for run in rec.runs]
    skeptic_runs = [run for rec, run in runs if rec.agent == "skeptic"]
    reviewed = [run for run in skeptic_runs if run["findings_count"] is not None]

    ledger_rounds = [n for n in (_as_int(r.get("skeptic_rounds")) for r in entry["ledger"]) if n is not None]
    ledger_skeptic_rounds = max(ledger_rounds) if ledger_rounds else None
    skeptic_reviews, reviews_source = len(skeptic_runs), "telemetry"
    if not skeptic_runs and ledger_skeptic_rounds is not None:
        skeptic_reviews, reviews_source = ledger_skeptic_rounds, "ledger"
    unit_counts = [n for n in (_as_int(r.get("unit_count")) for r in entry["ledger"]) if n is not None]
    unit_count = max(max(unit_counts) if unit_counts else 1, 1)
    findings = None
    if reviewed:
        findings = {
            sev: sum(_as_int(run["findings_count"].get(sev)) or 0 for run in reviewed)
            for sev in ("critical", "major", "minor")
        }

    iterations = [n for n in (_as_int(run["iteration"]) for run in skeptic_runs) if n is not None]
    max_iteration, iteration_source = (max(iterations), "telemetry") if iterations else (None, None)
    if max_iteration is None:
        state_iters = [n for n in (_as_int((s.get("loop_state") or {}).get("iteration")) for s in loop_states)
                       if n is not None]
        if state_iters:
            max_iteration, iteration_source = max(state_iters), "loop_state"

    findings_log = [
        f for s in loop_states for f in ((s.get("loop_state") or {}).get("findings_log") or [])
        if isinstance(f, dict)
    ]
    keyed = [f for f in findings_log if "re_raised" in f]
    re_raised = sum(1 for f in keyed if f["re_raised"] is True) if keyed else None

    qa_runs = [run for rec, run in runs if rec.agent == "qa-engineer"]
    qa_fail_backs = sum(1 for run in qa_runs if run["qa_result"] in QA_FAIL_RESULTS)

    row = {
        "ticket_id": ticket,
        "first_spawn_ts": entry["first_spawn_ts"].isoformat() if entry["first_spawn_ts"] else None,
        "skeptic_reviews": skeptic_reviews,
        "skeptic_reviews_source": reviews_source,
        "skeptic_reviews_with_findings": len(reviewed),
        "ledger_skeptic_rounds": ledger_skeptic_rounds,
        "unit_count": unit_count,
        "max_iteration": max_iteration,
        "max_iteration_source": iteration_source,
        "findings": findings,
        "re_raised": re_raised,
        "qa_runs": len(qa_runs),
        "qa_fail_backs": qa_fail_backs,
        "pr_status": pr_status,
        "prs_merged": None,
        "pr_numbers": None,
        "final_merge_ts": None,
        "e2e_wall_seconds": None,
        "follow_up_prs": None,
        "reentries_after_merge": None,
        "post_merge_findings": None,
        "loops": None,
        **_price_runs([(_run_model(rec, run), run) for rec, run in runs], rates),
    }
    if pr_status != "OK":
        return row

    merged = sorted(
        (pr for pr in credited if pr["merged_at"] is not None and pr["merged_at"] < pr_cutoff),
        key=lambda pr: pr["merged_at"],
    )
    row["prs_merged"] = len(merged)
    row["pr_numbers"] = [pr["number"] for pr in merged]
    row["loops"] = (max(skeptic_reviews - unit_count, 0) + qa_fail_backs
                    + max(len(merged) - unit_count, 0))
    if not merged:
        return row
    first_merge = merged[0]["merged_at"]
    final_merge = merged[-1]["merged_at"]
    row["final_merge_ts"] = final_merge.isoformat()
    if entry["first_spawn_ts"] is not None:
        row["e2e_wall_seconds"] = (final_merge - entry["first_spawn_ts"]).total_seconds()
    row["follow_up_prs"] = sum(1 for pr in merged if pr["merged_at"] > first_merge)
    row["reentries_after_merge"] = sum(
        1 for rec in entry["recs"]
        if (start_ts := _parse_ts(rec.start_ts)) is not None
        and start_ts > first_merge + REENTRY_AFTER_MERGE
    )
    post_merge = [run for run in skeptic_runs
                  if (end_ts := _parse_ts(run["end_ts"])) is not None and first_merge < end_ts < pr_cutoff]
    if reviews_source == "telemetry" and all(run["findings_count"] is not None for run in post_merge):
        row["post_merge_findings"] = sum(
            (_as_int(run["findings_count"].get("critical")) or 0)
            + (_as_int(run["findings_count"].get("major")) or 0)
            for run in post_merge
        )
    return row


def _ticket_summary(rows: list[dict]) -> dict:
    def present(key):
        return [r[key] for r in rows if r[key] is not None]

    loops = present("loops")
    e2e = present("e2e_wall_seconds")
    return {
        "tickets": len(rows),
        "loops_total": sum(loops) if loops else None,
        "loops_mean": statistics.mean(loops) if loops else None,
        "skeptic_reviews_total": sum(present("skeptic_reviews")),
        "qa_fail_backs_total": sum(present("qa_fail_backs")),
        "e2e_wall_seconds_median": statistics.median(e2e) if e2e else None,
        "dollars_exact_total": round(sum(present("dollars_exact")), 6),
        "dollars_family_estimated_total": round(sum(present("dollars_family_estimated")), 6),
    }


def _per_ticket_side(spawn_data: dict, index: dict[str, dict], start: datetime, end: datetime,
                     status: str, note: str | None, credits: dict[str, list[dict]],
                     ambiguous: list[dict], repo_pr_status: dict[str, str],
                     pr_cutoff: datetime, rates: dict) -> dict:
    """Tickets whose first v2 spawn (else earliest ledger opened_ts) falls
    in [start, end). A ticket whose ledger opened_ts predates the v2
    extent is listed in excluded_pre_v2, not reported; one with no ledger
    row cannot be detected as pre-v2 and is anchored at its first v2
    spawn. Every value is null unless status is OK."""
    side: dict = {"status": status, "note": note, "v2_coverage": _v2_coverage(spawn_data)}
    if status != "OK":
        side.update(tickets=None, summary=None, excluded_pre_v2=None,
                    ambiguous_prs=None, unattributed_runs=None)
        return side
    v2_start = spawn_data["earliest_ts"]
    rows, excluded = [], []
    for ticket in sorted(index):
        entry = index[ticket]
        anchor = entry["first_spawn_ts"] or entry["ledger_opened_ts"]
        if anchor is None or not (start <= anchor < end):
            continue
        if entry["ledger_opened_ts"] is not None and entry["ledger_opened_ts"] < v2_start:
            excluded.append(ticket)
            continue
        statuses = [repo_pr_status.get(repo, "NOT_FETCHED") for repo in sorted(entry["repos"])]
        pr_status = next((s for s in statuses if s != "OK"), "OK")
        rows.append(_ticket_row(ticket, entry, spawn_data["loop_states"].get(ticket, []),
                                credits.get(ticket, []), pr_status, pr_cutoff, rates))
    reported = {r["ticket_id"] for r in rows}
    unattributed_runs = sum(
        1 for _repo, rec in spawn_data["spawns"] if not rec.task_id
        for run in rec.runs
        if (ts := _parse_ts(run["end_ts"])) is not None and start <= ts < end
    )
    side.update(
        tickets=rows,
        summary=_ticket_summary(rows),
        excluded_pre_v2=excluded,
        ambiguous_prs=[a for a in ambiguous if reported & set(a["tickets"])],
        unattributed_runs=unattributed_runs,
    )
    return side


# ---------------------------------------------------------------------------
# Envelope and small helpers
# ---------------------------------------------------------------------------


def metric(status: str, value, coverage=None, missing=()) -> dict:
    return {"status": status, "value": value if status != ABSENT else None,
            "coverage": coverage, "missing": list(missing)}


def _absent(reason: str, coverage=None) -> dict:
    return metric(ABSENT, None, coverage, [reason])


def _ratio(num, den):
    return round(num / den, 4) if den else None


def _ordered_sum(values) -> float:
    """Left-to-right float sum. Python's sum() compensates rounding, so it
    can differ in the last bit from a plain running total (jq's `add`), which
    the cost reconciliation is checked against at tolerance 0."""
    total = 0.0
    for v in values:
        total += v
    return total


def _model_base(model) -> str:
    """Model id without a trailing context-window tag: cost-state keys read
    `claude-opus-5-5[1m]` where transcripts record `claude-opus-5-5`."""
    return _CONTEXT_TAG_RE.sub("", str(model))


def _usd(value):
    return round(value, 6) if value is not None else None


def session_summary(session, repo) -> dict:
    counts: dict = {}
    for key, tokens in session.conductor.items():
        counts[key] = counts.get(key, 0) + tokens.get("messages", 0)
    if not counts:
        for sub in session.subagents:
            for key, tokens in sub.usage.items():
                counts[key] = counts.get(key, 0) + tokens.get("messages", 0)
    top = min(counts, key=lambda k: (-counts[k], tuple(str(x) for x in k))) if counts else (None, None, None)
    return {
        "session_id": session.session_id, "repo": str(repo),
        "first_ts": session.first_ts.isoformat() if session.first_ts else None,
        "model": top[0], "entrypoint": top[1], "version": top[2], "cost_usd": session.cost_usd,
        "empty": is_empty_session(session),
    }


def is_empty_session(session) -> bool:
    """No usage record, conductor or subagent, and no cost-state spend (the
    record is absent or $0): the session never reached the model."""
    return (not session.conductor and not session.keepalive and not any(sub.usage for sub in session.subagents)
            and not session.cost_state_usd)


def fire_key(row: dict) -> str | None:
    if not isinstance(row, dict):
        return None
    tool_use_id = row.get("tool_use_id")
    if isinstance(tool_use_id, str) and tool_use_id:
        return tool_use_id
    session_id, ts = row.get("session_id"), row.get("ts")
    if isinstance(session_id, str) and session_id and isinstance(ts, str) and ts:
        return f"{session_id}@{ts}"
    return None


def _read_jsonl(path: Path) -> list[dict] | None:
    """Parsed dict rows, or None when the file is absent or unreadable."""
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return None
    rows = []
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                rows.append(rec)
    return rows


def _in(ts, start, end) -> bool:
    return ts is not None and start <= ts < end


# ---------------------------------------------------------------------------
# Git and gh
# ---------------------------------------------------------------------------


def git_merged_prs(repo, base: str, start: datetime, end: datetime) -> list[dict] | None:
    proc = _LIB._run(
        ["git", "log", "--first-parent", f"--since={start.isoformat()}", f"--until={end.isoformat()}",
         "--format=%H%x1f%cI%x1f%s%x1f%b%x1e", base],
        cwd=str(repo), timeout=60.0,
    )
    if proc.returncode != 0:
        return None
    out = []
    for chunk in proc.stdout.split("\x1e"):
        parts = chunk.strip("\n").split("\x1f")
        if len(parts) < 4:
            continue
        sha, committed, subject, body = parts[0].strip(), parts[1], parts[2], parts[3]
        m = _PR_SUBJECT_RE.search(subject)
        merged_at = _parse_ts(committed)
        if not m or merged_at is None or not (start <= merged_at < end):
            continue
        rev = _REVERT_SUBJECT_RE.match(_PR_SUBJECT_RE.sub("", subject).strip())
        out.append({
            "number": int(m.group(1)), "sha": sha, "merged_at": merged_at,
            "subject": subject, "body": body,
            "reverts": _REVERTS_BODY_RE.findall(body),
            "revert_subject": rev.group(1) if rev else None,
        })
    out.sort(key=lambda pr: pr["merged_at"])
    return out


def git_pr_merges(repo, base: str, numbers, tickets, pattern: re.Pattern) -> list[dict] | None:
    args = ["git", "log", "--first-parent", "-F", "--format=%cI%x1f%s%x1f%b%x1e"]
    for n in sorted(numbers):
        args += [f"--grep=(#{n})", f"--grep=Merge pull request #{n} from "]
    args += [f"--grep={t}" for t in sorted(tickets)]
    proc = _LIB._run(args + [base], cwd=str(repo), timeout=60.0)
    if proc.returncode != 0:
        return None
    out = []
    for chunk in proc.stdout.split("\x1e"):
        parts = chunk.strip("\n").split("\x1f")
        if len(parts) < 3:
            continue
        subject = parts[1]
        m = _PR_SUBJECT_RE.search(subject) or _MERGE_COMMIT_SUBJECT_RE.match(subject)
        merged_at = _parse_ts(parts[0])
        if merged_at is None:
            continue
        number = int(m.group(1)) if m else None
        ids = [t for t in _ids(pattern, subject) + _ids(pattern, parts[2]) if t in tickets]
        if number in numbers or ids:
            out.append({"number": number, "subject": subject, "merged_at": merged_at, "ids": ids})
    out.sort(key=lambda c: (c["merged_at"], c["subject"]))
    return out


def _reverted(pr: dict, prs: list[dict]) -> bool:
    """A later merged PR within LOOKAHEAD reverts `pr`: its subject is
    `Revert "<pr subject>"` or its body says `This reverts commit <sha>`."""
    horizon = pr["merged_at"] + LOOKAHEAD
    title = _PR_SUBJECT_RE.sub("", pr["subject"]).strip()
    for other in prs:
        if not (pr["merged_at"] < other["merged_at"] <= horizon):
            continue
        if any(pr["sha"].startswith(s) for s in other["reverts"]) or other["revert_subject"] == title:
            return True
    return False


def _follow_ups(first: dict, ticket: str | None, linked: list[dict], prs: list[dict],
                pattern: re.Pattern) -> list[int]:
    """Merged PRs within LOOKAHEAD after `first` that belong to the same work
    item: linked to it, or carrying its ticket id in subject or body."""
    horizon = first["merged_at"] + LOOKAHEAD
    out = []
    linked_numbers = {pr["number"] for pr in linked}
    for pr in prs:
        if not (first["merged_at"] < pr["merged_at"] <= horizon):
            continue
        subject_ids, body_ids = _pr_ids(pattern, pr)
        if pr["number"] in linked_numbers or (ticket and ticket in subject_ids + body_ids):
            out.append(pr["number"])
    return out


def _repo_slug(repo) -> str | None:
    proc = _LIB._run(["git", "remote", "get-url", "origin"], cwd=str(repo), timeout=30.0)
    if proc.returncode != 0:
        return None
    m = _SLUG_RE.search(proc.stdout.strip())
    return m.group(1) if m else None


def _gh_pr_states(slug: str) -> dict[int, str] | None:
    """State of the repo's 1000 most recent PRs. Not `--search`: the search
    API answers an inaccessible repo with an empty list and exit 0, which
    would read as "no PRs" instead of "gh unavailable"."""
    proc = _LIB._run(
        ["gh", "pr", "list", "--repo", slug, "--state", "all", "--limit", "1000", "--json", "number,state"],
        timeout=GH_TIMEOUT_SECONDS,
    )
    if proc.returncode != 0:
        return None
    try:
        rows = json.loads(proc.stdout)
    except ValueError:
        return None
    return {r["number"]: str(r.get("state", "")).lower() for r in rows
            if isinstance(r, dict) and isinstance(r.get("number"), int)}


def _feedback_items(repo: str) -> list[dict] | None:
    """Triaged ds-feedback items for this repo, or None when the CLI fails."""
    proc = _LIB._run([sys.executable, str(_BIN / "ds-feedback"), "list", "--status", "triaged",
                      "--repo", repo], timeout=60.0)
    if proc.returncode != 0:
        return None
    try:
        rows = json.loads(proc.stdout)
    except ValueError:
        return None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else None


# ---------------------------------------------------------------------------
# Ticket ids
# ---------------------------------------------------------------------------


def _ticket_pattern(prefixes) -> re.Pattern:
    body = "|".join(sorted(map(re.escape, prefixes))) if prefixes else FALLBACK_TICKET_PREFIX
    return re.compile(rf"(?<![A-Za-z0-9])(?:{body})-\d+(?![0-9])")


def _ids(pattern: re.Pattern, text) -> list[str]:
    if not isinstance(text, str) or not text:
        return []
    return list(dict.fromkeys(m.group(0) for m in pattern.finditer(text)))


def _pr_ids(pattern: re.Pattern, pr: dict) -> tuple[list[str], list[str]]:
    return _ids(pattern, pr["subject"]), _ids(pattern, pr["body"])


# ---------------------------------------------------------------------------
# Per-repo inputs
# ---------------------------------------------------------------------------


def _sub_path(session, sub) -> Path:
    return session.path.parent / session.session_id / "subagents" / f"agent-{sub.agent_id}.jsonl"


def _file_last_ts(path: Path) -> datetime | None:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 262144))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    best = None
    for line in tail.splitlines():
        ts = _TRANSCRIPTS._line_ts(line)
        if ts is not None and (best is None or ts > best):
            best = ts
    return best


def _hook_rows(events: list[dict]) -> list[dict]:
    out = []
    for ev in events:
        data = ev.get("data")
        if (ev.get("event") in ("spawn_start", "spawn_complete") and isinstance(data, dict)
                and data.get("source") == "hook"):
            out.append(ev)
    return out


def _load_repo(repo: Path, start: datetime, end: datetime, base, ticket_re, use_gh, stores,
               use_feedback=True) -> dict:
    agentic = repo / ".agentic"
    events = _read_jsonl(agentic / "events.jsonl")
    hook_rows = _hook_rows(events or [])
    fires = _read_jsonl(agentic / ".enforcement-fires.jsonl")
    prefixes = set()
    for name in ("tasks.jsonl", "ticket-ledger.jsonl"):
        for row in _read_jsonl(agentic / name) or []:
            m = _PREFIX_RE.match(str(row.get("ticket_id") or ""))
            if m:
                prefixes.add(m.group(1))
    for ev in hook_rows:
        m = _PREFIX_RE.match(str(ev.get("task_id") or ""))
        if m:
            prefixes.add(m.group(1))
    pattern = re.compile(ticket_re) if ticket_re else _ticket_pattern(prefixes)

    base_ref, base_source, base_diag = (base, "explicit", []) if base else _LIB.resolve_base_branch(
        str(repo), None, prog="ds-eval")
    prs = git_merged_prs(repo, base_ref, start, end + LOOKAHEAD) if base_ref else None
    for pr in prs or []:
        pr["in_window"] = pr["merged_at"] < end
    slug = _repo_slug(repo)
    gh_states, gh_status = None, "disabled (--no-gh)"
    if use_gh:
        if slug is None:
            gh_status = "unavailable: no github origin remote"
        else:
            gh_states = _gh_pr_states(slug)
            gh_status = "ok" if gh_states is not None else "unavailable: gh pr list failed"
    labels = _feedback_items(str(repo)) if use_feedback else None
    sessions = _TRANSCRIPTS.sessions(repo, start, end, stores)
    return {
        "repo": str(repo), "sessions": sessions, "hook_rows": hook_rows,
        "events_present": events is not None, "fires": fires, "pattern": pattern,
        "prefixes": sorted(prefixes), "base": base_ref, "base_source": base_source,
        "base_diagnostics": base_diag, "prs": prs, "slug": slug,
        "gh_states": gh_states, "gh_status": gh_status, "labels": labels,
    }


# ---------------------------------------------------------------------------
# Pricing of visible usage
# ---------------------------------------------------------------------------


def _price_usage(usage, rates: dict) -> tuple[float | None, list[str]]:
    """Priced dollars of a _transcripts Usage (exact + family), and the models
    no rate covers. None when there is no usage or nothing could be priced."""
    if not usage:
        return None, []
    items = [(model, {"run_tokens": tokens}) for (model, _ep, _ver), tokens in usage.items()]
    priced = _price_runs(items, rates)
    if len(priced["unpriced_models"]) == len({m for m, _ in items}):
        return None, priced["unpriced_models"]
    return priced["dollars_exact"] + priced["dollars_family_estimated"], priced["unpriced_models"]


def _by_entrypoint(usage, rates: dict) -> dict[str, float | None]:
    groups: dict = {}
    for key, tokens in usage.items():
        groups.setdefault(key[1] or "(none)", {})[key] = tokens
    return {ep: _usd(_price_usage(group, rates)[0]) for ep, group in sorted(groups.items())}


def _usd_metric(usds: list, unpriced: set, label: str) -> dict:
    known = [u for u in usds if u is not None]
    if not known:
        return _absent(f"no priced {label} usage" + (f" (unpriced: {', '.join(sorted(unpriced))})"
                                                     if unpriced else ""))
    missing = []
    if unpriced:
        missing.append("unpriced models: " + ", ".join(sorted(unpriced)))
    if len(known) < len(usds):
        missing.append(f"{len(usds) - len(known)} of {len(usds)} with no priced usage")
    status = PARTIAL if missing else OK
    m = metric(status, _usd(sum(known)), _ratio(len(known), len(usds)), missing)
    m["basis"] = "priced"
    return m


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _spawn_index(inputs: list[dict], rates: dict) -> list[dict]:
    """One entry per Sub of every in-window session, with its priced dollars
    and its hook rows (joined by agent_id or tool_use_id)."""
    spawns = []
    for inp in inputs:
        by_agent: dict = {}
        by_tool: dict = {}
        for ev in inp["hook_rows"]:
            data = ev["data"]
            if data.get("agent_id"):
                by_agent.setdefault(data["agent_id"], []).append(ev)
            if data.get("tool_use_id"):
                by_tool.setdefault(data["tool_use_id"], []).append(ev)
        for session in inp["sessions"]:
            for sub in session.subagents:
                rows = list(by_agent.get(sub.agent_id, []))
                for ev in by_tool.get(sub.tool_use_id, []) if sub.tool_use_id else []:
                    if ev not in rows:
                        rows.append(ev)
                usd, unpriced = _price_usage(sub.usage, rates)
                spawns.append({
                    "inp": inp, "session": session, "sub": sub,
                    "type": sub.agent_type or "(unknown)", "usd": usd, "unpriced": unpriced,
                    "hook_rows": rows, "end": None,
                })
    return spawns


def _skeptic_returns(inputs: list[dict], start: datetime, end: datetime) -> list[dict]:
    out = []
    for inp in inputs:
        for ev in inp["hook_rows"]:
            if ev.get("event") != "spawn_complete" or ev.get("agent") != "skeptic":
                continue
            ts = _parse_ts(ev.get("ts"))
            if not _in(ts, start, end):
                continue
            data = ev["data"]
            fc = data.get("findings_count") if isinstance(data.get("findings_count"), dict) else None
            out.append({
                "repo": inp["repo"], "ts": ts, "agent_id": data.get("agent_id"),
                "iteration": _as_int(data.get("iteration")),
                "signed_off": data.get("signed_off") if isinstance(data.get("signed_off"), bool) else None,
                "findings": None if fc is None else {
                    sev: _as_int(fc.get(sev)) or 0 for sev in ("critical", "major", "minor")},
            })
    return out


def _skeptic_section(returns: list[dict]) -> dict:
    if not returns:
        none = _absent("no Skeptic spawn_complete hook rows in the window")
        return {"by_iteration": none, "late_withheld_share": none, "late_fix_verification_share": none}
    by_iter: dict = {}
    for r in returns:
        key = str(r["iteration"]) if r["iteration"] is not None else "unknown"
        b = by_iter.setdefault(key, {"returns": 0, "signed_off": 0, "withheld": 0, "signed_off_missing": 0,
                                     "with_findings": 0, "findings": {"critical": 0, "major": 0, "minor": 0}})
        b["returns"] += 1
        if r["signed_off"] is None:
            b["signed_off_missing"] += 1
        elif r["signed_off"]:
            b["signed_off"] += 1
        else:
            b["withheld"] += 1
        if r["findings"] is not None:
            b["with_findings"] += 1
            for sev, n in r["findings"].items():
                b["findings"][sev] += n
    with_iter = sum(1 for r in returns if r["iteration"] is not None)
    missing = [f"{len(returns) - with_iter} returns carry no iteration"] if with_iter < len(returns) else []
    by_iteration = metric(OK, dict(sorted(by_iter.items(), key=lambda kv: (kv[0] == "unknown", kv[0].zfill(4)))),
                          _ratio(with_iter, len(returns)), missing)
    with_verdict = sum(1 for r in returns if r["signed_off"] is not None or r["findings"] is not None)
    by_iteration["returns"] = {"total": len(returns), "iteration_tagged": with_iter,
                               "findings_carrying": with_verdict}
    by_iteration["iteration_tagged_share"] = _ratio(with_iter, len(returns))
    by_iteration["findings_carrying_share"] = _ratio(with_verdict, len(returns))

    late = [r for r in returns if r["iteration"] is not None and r["iteration"] >= 2]
    so = [r for r in late if r["signed_off"] is not None]
    fc = [r for r in late if r["findings"] is not None]
    if so:
        withheld = sum(1 for r in so if r["signed_off"] is False)
        late_withheld = metric(OK, {"share": _ratio(withheld, len(so)), "withheld": withheld, "n": len(so)},
                               _ratio(len(so), len(late)),
                               [f"{len(late) - len(so)} late returns carry no signed_off"]
                               if len(so) < len(late) else [])
    else:
        late_withheld = _absent("no Skeptic return with iteration >= 2 carries signed_off",
                                0.0 if late else None)
    if fc:
        clean = sum(1 for r in fc if r["findings"]["critical"] == 0 and r["findings"]["major"] == 0)
        late_fix = metric(OK, {"share": _ratio(clean, len(fc)), "critical_major_free": clean, "n": len(fc)},
                          _ratio(len(fc), len(late)),
                          [f"{len(late) - len(fc)} late returns carry no findings_count"]
                          if len(fc) < len(late) else [])
    else:
        late_fix = _absent("no Skeptic return with iteration >= 2 carries findings_count",
                           0.0 if late else None)
    return {"by_iteration": by_iteration, "late_withheld_share": late_withheld,
            "late_fix_verification_share": late_fix}


def _matching_ref(ref, inp: dict, merged_numbers: set) -> tuple[int, bool] | None:
    repo, number, _ts = ref
    if repo is None:
        return (number, True) if number in merged_numbers else None
    if inp["slug"] is not None and repo.lower() == inp["slug"].lower():
        return number, False
    return None


def _key_spawns(spawns: list[dict], inputs: list[dict]) -> dict:
    """Assign each spawn a work-item key by tiers 1-4 and compute tier
    agreement. Mutates each spawn with `tier`, `key`, `ticket`, `pr`,
    `repo_inferred`."""
    pr_maps = {inp["repo"]: {pr["number"]: pr for pr in (inp["prs"] or [])} for inp in inputs}
    session_prs: dict = {}
    for sp in spawns:
        inp, session = sp["inp"], sp["session"]
        sid = (inp["repo"], session.session_id)
        if sid not in session_prs:
            refs = list(session.pr_created)
            for sub in session.subagents:
                refs.extend(sub.pr_created)
            matched = []
            for ref in refs:
                hit = _matching_ref(ref, inp, set(pr_maps[inp["repo"]]))
                if hit is not None and ref[2] is not None:
                    matched.append((ref[2], hit[0], hit[1]))
            session_prs[sid] = sorted(matched)

    def resolve_pr(inp, number):
        pr = pr_maps[inp["repo"]].get(number)
        if pr is not None:
            subject_ids, body_ids = _pr_ids(inp["pattern"], pr)
            for ids in (subject_ids, body_ids):
                if len(ids) == 1:
                    return ids[0], pr
        return None, pr

    candidates: list[dict] = []
    for sp in spawns:
        inp, sub, pattern = sp["inp"], sp["sub"], sp["inp"]["pattern"]
        c: dict = {}
        ids = _ids(pattern, sub.description)
        if len(ids) == 1:
            c[1] = {"ticket": ids[0]}
        task_ids = set()
        for ev in sp["hook_rows"]:
            task_ids.update(_ids(pattern, ev.get("task_id")))
        if len(task_ids) == 1:
            c[2] = {"ticket": next(iter(task_ids))}
        own = []
        for ref in sub.pr_created:
            hit = _matching_ref(ref, inp, set(pr_maps[inp["repo"]]))
            if hit is not None:
                own.append(hit)
        own = list(dict.fromkeys(own))
        if len(own) == 1:
            ticket, pr = resolve_pr(inp, own[0][0])
            c[3] = {"ticket": ticket, "number": own[0][0], "pr": pr, "repo_inferred": own[0][1]}
        sp["end"] = _file_last_ts(_sub_path(sp["session"], sub))
        if sp["end"] is not None:
            nxt = next((m for m in session_prs[(inp["repo"], sp["session"].session_id)] if m[0] >= sp["end"]),
                       None)
            if nxt is not None:
                ticket, pr = resolve_pr(inp, nxt[1])
                c[4] = {"ticket": ticket, "number": nxt[1], "pr": pr, "repo_inferred": nxt[2]}
        candidates.append(c)

    agreement = {t: {"agree": 0, "compared": 0} for t in (2, 3, 4)}
    for sp, c in zip(spawns, candidates):
        if 1 not in c:
            continue
        tid = c[1]["ticket"]
        if 2 in c:
            agreement[2]["compared"] += 1
            agreement[2]["agree"] += c[2]["ticket"] == tid
        for t in (3, 4):
            if t in c and c[t]["pr"] is not None:
                subject_ids, body_ids = _pr_ids(sp["inp"]["pattern"], c[t]["pr"])
                agreement[t]["compared"] += 1
                agreement[t]["agree"] += tid in subject_ids or tid in body_ids
    a4 = agreement[4]
    tier4_disabled = a4["compared"] >= TIER4_MIN_COMPARED and a4["agree"] / a4["compared"] < TIER4_MIN_AGREEMENT

    for sp, c in zip(spawns, candidates):
        sp.update(tier=None, key=None, ticket=None, pr=None, repo_inferred=False)
        for t in (1, 2, 3, 4):
            if t not in c or (t == 4 and tier4_disabled):
                continue
            hit = c[t]
            sp["tier"] = t
            sp["ticket"] = hit.get("ticket")
            sp["pr"] = hit.get("number")
            sp["repo_inferred"] = bool(hit.get("repo_inferred"))
            sp["key"] = sp["ticket"] or f"pr:{sp['inp']['slug'] or sp['inp']['repo']}#{hit['number']}"
            break
    return {"agreement": {str(t): v for t, v in agreement.items()}, "tier4_disabled": tier4_disabled}


def _landing_evidence(rows: list[dict], inputs: list[dict], start: datetime, end: datetime) -> None:
    """Where each row with no first_merged_pr landed, so its absence from the
    ticket-id match never reads as "not merged": its own PRs in the window's
    merge set, then one git_pr_merges call per repo for PR commits outside
    that set and a count of other commits mentioning its ticket id."""
    for inp in inputs:
        mine = [r for r in rows if r["repo"] == inp["repo"] and r["pr_history"] and r["first_merged_pr"] is None]
        if not mine:
            continue
        in_window = {pr["number"] for pr in inp["prs"] or []}
        for r in mine:
            r["own_prs_merged_in_window"] = sorted(r["_pr_candidates"] & in_window)
        numbers = {n for r in mine for n in r["_pr_candidates"]}
        tickets = {r["ticket"] for r in mine if r["ticket"]}
        found = git_pr_merges(inp["repo"], inp["base"], numbers, tickets, inp["pattern"]) if inp["base"] else None
        if found is None:
            continue

        def when(ts):
            return "before" if ts < start else "in" if ts < end + LOOKAHEAD else "after"

        for r in mine:
            hits = [c for c in found if c["number"] in r["_pr_candidates"] or r["ticket"] in c["ids"]]
            merges = [c for c in hits if c["number"] is not None and c["number"] not in in_window
                      and not c["subject"].startswith('Revert "')]
            r["merged_outside_window"] = [
                {"number": c["number"], "merged_at": c["merged_at"].isoformat(), "when": when(c["merged_at"])}
                for c in merges]
            r["ticket_mention_commits"] = sum(1 for c in hits if r["ticket"] in c["ids"] and c not in merges)


def _work_items(spawns: list[dict], inputs: list[dict], returns: list[dict], keying: dict,
                start: datetime, end: datetime) -> dict:
    total = len(spawns)
    tiers = {str(t): sum(1 for sp in spawns if sp["tier"] == t) for t in (1, 2, 3, 4)}
    tiers["unkeyed"] = sum(1 for sp in spawns if sp["tier"] is None)
    missing = []
    if keying["tier4_disabled"]:
        a4 = keying["agreement"]["4"]
        missing.append(f"tier 4 disabled: agreement {a4['agree']}/{a4['compared']} < {TIER4_MIN_AGREEMENT}")
    if tiers["unkeyed"]:
        missing.append(f"{tiers['unkeyed']} spawns unkeyed")
    if total == 0:
        coverage = _absent("no subagent spawns in the window's sessions")
    else:
        coverage = metric(OK, tiers, _ratio(total - tiers["unkeyed"], total), missing)

    no_git = [inp["repo"] for inp in inputs if inp["prs"] is None]
    iter_by_agent: dict = {}
    for r in returns:
        if r["agent_id"] and r["iteration"] is not None:
            key = (r["repo"], r["agent_id"])
            iter_by_agent[key] = max(iter_by_agent.get(key, 0), r["iteration"])

    items: dict = {}
    for sp in spawns:
        if sp["key"] is None:
            continue
        inp = sp["inp"]
        it = items.setdefault((inp["repo"], sp["key"]), {
            "repo": inp["repo"], "key": sp["key"], "ticket": sp["ticket"], "spawns": 0, "usd_list": [],
            "walls": [], "tiers": set(), "max_iteration": None, "types": set(), "prs": set(),
            "repo_inferred": False, "own_prs": set(),
        })
        it["own_prs"].update(n for ref_repo, n, _ts in sp["sub"].pr_created
                             if ref_repo and inp["slug"] and ref_repo.lower() == inp["slug"].lower())
        it["spawns"] += 1
        it["usd_list"].append(sp["usd"])
        if sp["sub"].wall_seconds is not None:
            it["walls"].append(sp["sub"].wall_seconds)
        it["tiers"].add(sp["tier"])
        it["types"].add(sp["type"])
        it["repo_inferred"] |= sp["repo_inferred"]
        if sp["pr"] is not None:
            it["prs"].add(sp["pr"])
        n = iter_by_agent.get((inp["repo"], sp["sub"].agent_id))
        if n is not None:
            it["max_iteration"] = max(it["max_iteration"] or 0, n)

    rows = []
    for (repo, _key), it in sorted(items.items()):
        inp = next(i for i in inputs if i["repo"] == repo)
        prs = inp["prs"] or []
        by_number = {pr["number"]: pr for pr in prs}
        linked = {n for n in it["prs"] if n in by_number}
        if it["ticket"]:
            linked |= {pr["number"] for pr in prs
                       if it["ticket"] in _pr_ids(inp["pattern"], pr)[0] + _pr_ids(inp["pattern"], pr)[1]}
        merged = sorted((by_number[n] for n in linked), key=lambda pr: pr["merged_at"])
        first = merged[0] if merged else None
        follow_ups, reverted = [], False
        if first is not None:
            follow_ups = _follow_ups(first, it["ticket"], merged, prs, inp["pattern"])
            reverted = _reverted(first, prs)
        known = [u for u in it["usd_list"] if u is not None]
        flagged = bool(first is not None and (it["max_iteration"] or 0) >= 3 and (follow_ups or reverted))
        rows.append({
            "repo": repo, "key": it["key"], "ticket": it["ticket"], "spawns": it["spawns"],
            "usd": _usd(sum(known)) if known else None, "usd_basis": "priced",
            "wall_seconds": round(sum(it["walls"]), 3) if it["walls"] else None,
            "wall_spawns": len(it["walls"]), "tiers": sorted(it["tiers"]),
            "pr_history": inp["prs"] is not None, "max_iteration": it["max_iteration"],
            "types": sorted(it["types"]), "pr_numbers": [pr["number"] for pr in merged],
            "first_merged_pr": first["number"] if first else None,
            "follow_up_prs": follow_ups, "reverted": reverted,
            "repo_inferred": it["repo_inferred"], "flagged_d3": flagged,
            "own_prs_merged_in_window": [], "merged_outside_window": None, "ticket_mention_commits": None,
            "_pr_candidates": it["prs"] | it["own_prs"],
        })
    _landing_evidence(rows, inputs, start, end)
    for row in rows:
        del row["_pr_candidates"]

    if not rows:
        items_metric = _absent("no keyed work items")
    else:
        items_metric = metric(PARTIAL if no_git else OK, rows, None,
                              [f"no merged-PR history (git) for {r}" for r in no_git])
    merged_rows = [r for r in rows if r["first_merged_pr"] is not None]
    if no_git and len(no_git) == len(inputs):
        rework = _absent("no merged-PR history: base ref unresolved or unreadable")
        outcome = _absent("no merged-PR history: base ref unresolved or unreadable")
    elif not rows:
        rework = _absent("no keyed work items")
        outcome = _absent("no keyed work items")
    else:
        status = PARTIAL if no_git else OK
        miss = [f"no merged-PR history (git) for {r}" for r in no_git]
        rework = metric(status, {
            "items_merged": len(merged_rows),
            "follow_up_items": sum(1 for r in merged_rows if r["follow_up_prs"]),
            "reverted_items": sum(1 for r in merged_rows if r["reverted"]),
            "follow_up_prs": sum(len(r["follow_up_prs"]) for r in merged_rows),
            "loops": sum(max((r["max_iteration"] or 1) - 1, 0) for r in rows),
            "rework_share": _ratio(sum(1 for r in merged_rows if r["follow_up_prs"] or r["reverted"]),
                                   len(merged_rows)),
        }, _ratio(len(merged_rows), len(rows)), miss)
        outcome = metric(status, {
            "items": len(rows), "items_merged": len(merged_rows),
            "merged_prs_in_window": sum(1 for i in inputs for pr in i["prs"] or [] if pr["in_window"]),
        }, _ratio(len(merged_rows), len(rows)), miss)
    return {"coverage": coverage, "tier_agreement": keying["agreement"], "tier4_disabled": keying["tier4_disabled"],
            "items": items_metric, "summary": _items_summary(rows), "pr_outcome": outcome, "rework": rework}


def _items_summary(rows: list[dict]) -> dict:
    """Keyed-item count with the median priced dollars and median summed
    spawn wall, each over the items that carry the figure."""
    def median(key, what):
        known = [r[key] for r in rows if r[key] is not None]
        if not known:
            return _absent(f"no keyed work item with {what}" if rows else "no keyed work items")
        return metric(OK if len(known) == len(rows) else PARTIAL, round(statistics.median(known), 6),
                      _ratio(len(known), len(rows)),
                      [f"{len(rows) - len(known)} of {len(rows)} items without {what}"]
                      if len(known) < len(rows) else [])

    return {"items": len(rows), "usd_median": median("usd", "priced usage"),
            "wall_seconds_median": median("wall_seconds", "a spawn wall time")}


def _engineer_value(spawns: list[dict], inputs: list[dict]) -> dict:
    outcomes = {"prs": 0, "merged": 0, "reverted": 0, "followed_up": 0, "open": 0, "closed": 0,
                "merged_off_window": 0, "unknown": 0}
    missing = []
    for sp in spawns:
        if sp["type"] != "engineer":
            continue
        inp = sp["inp"]
        prs = inp["prs"] or []
        merged = {pr["number"]: pr for pr in prs}
        own = list(dict.fromkeys(h for h in (_matching_ref(ref, inp, set(merged)) for ref in sp["sub"].pr_created)
                                 if h is not None))
        if len(own) != 1:
            continue
        number = own[0][0]
        outcomes["prs"] += 1
        if number in merged:
            pr = merged[number]
            subject_ids, body_ids = _pr_ids(inp["pattern"], pr)
            ticket = (subject_ids or body_ids or [None])[0]
            outcomes["merged"] += 1
            outcomes["reverted"] += _reverted(pr, prs)
            outcomes["followed_up"] += bool(_follow_ups(pr, ticket, [pr], prs, inp["pattern"]))
        elif inp["gh_states"] is not None and inp["gh_states"].get(number) in ("open", "closed", "merged"):
            state = inp["gh_states"][number]
            outcomes["merged_off_window" if state == "merged" else state] += 1
        else:
            outcomes["unknown"] += 1
    if outcomes["prs"] == 0:
        return _absent("no engineer spawn created exactly one PR of this repo")
    if outcomes["unknown"]:
        missing.append(f"{outcomes['unknown']} unmerged PRs with unknown state (gh: "
                       + "; ".join(sorted({i['gh_status'] for i in inputs})) + ")")
    return metric(PARTIAL if missing else OK, outcomes,
                  _ratio(outcomes["prs"] - outcomes["unknown"], outcomes["prs"]), missing)


def _qa_value(spawns_rows: list[dict]) -> dict:
    if not spawns_rows:
        return _absent("no qa-engineer spawn_complete hook rows in the window")
    parsed = [r for r in spawns_rows if isinstance(r["data"].get("qa_result"), str)]
    if not parsed:
        return _absent(f"0/{len(spawns_rows)} qa-engineer completions parse a result", 0.0)
    fails = sum(1 for r in parsed if r["data"]["qa_result"] in QA_FAIL_RESULTS)
    return metric(OK, {"runs": len(parsed), "fail_or_partial": fails, "pass": len(parsed) - fails},
                  _ratio(len(parsed), len(spawns_rows)),
                  [f"{len(spawns_rows) - len(parsed)} completions carry no qa_result"]
                  if len(parsed) < len(spawns_rows) else [])


def _correlational(agent_type: str, work_rows: list[dict]) -> dict:
    merged_rows = [r for r in work_rows if r["first_merged_pr"] is not None]
    if not work_rows:
        return _absent("no keyed work items")

    def side(rows, merged):
        reworked = sum(1 for r in merged if r["follow_up_prs"] or r["reverted"])
        return {"n": len(rows), "merged_share": _ratio(len(merged), len(rows)),
                "rework_share": _ratio(reworked, len(merged)), "merged_n": len(merged)}

    with_t = [r for r in work_rows if agent_type in r["types"]]
    without = [r for r in work_rows if agent_type not in r["types"]]
    m = metric(OK, {"with": side(with_t, [r for r in merged_rows if agent_type in r["types"]]),
                    "without": side(without, [r for r in merged_rows if agent_type not in r["types"]])})
    m["basis"] = "correlational"
    return m


def _agents_section(inputs, spawns, rates, skeptic, work, start, end) -> dict:
    agents: dict = {}
    conductor_usd, conductor_unpriced, by_ep = [], set(), {}
    for inp in inputs:
        for session in inp["sessions"]:
            usd, unpriced = _price_usage(session.conductor, rates)
            conductor_usd.append(usd)
            conductor_unpriced.update(unpriced)
            for ep, v in _by_entrypoint(session.conductor, rates).items():
                if v is not None:
                    by_ep[ep] = by_ep.get(ep, 0.0) + v
    if conductor_usd:
        agents["conductor"] = {"sessions": len(conductor_usd),
                               "usd": _usd_metric(conductor_usd, conductor_unpriced, "conductor"),
                               "by_entrypoint": {k: _usd(v) for k, v in sorted(by_ep.items())}}
    work_rows = work["items"]["value"] or []
    qa_rows = [ev for inp in inputs for ev in inp["hook_rows"]
               if ev.get("event") == "spawn_complete" and ev.get("agent") == "qa-engineer"
               and _in(_parse_ts(ev.get("ts")), start, end)]
    for agent_type in sorted({sp["type"] for sp in spawns}):
        mine = [sp for sp in spawns if sp["type"] == agent_type]
        unpriced = {m for sp in mine for m in sp["unpriced"]}
        eps: dict = {}
        for sp in mine:
            for ep, v in _by_entrypoint(sp["sub"].usage, rates).items():
                if v is not None:
                    eps[ep] = eps.get(ep, 0.0) + v
        walls = [sp["sub"].wall_seconds for sp in mine if sp["sub"].wall_seconds is not None]
        if agent_type == "skeptic":
            value = {"own": skeptic["by_iteration"]}
        elif agent_type == "qa-engineer":
            value = {"own": _qa_value(qa_rows)}
        elif agent_type == "engineer":
            value = {"own": _engineer_value(spawns, inputs)}
        else:
            value = {"own": _absent("no causal value signal for this type (needs a counterfactual); "
                                    "see value.work_items and ds-change-delta --cut"),
                     "work_items": _correlational(agent_type, work_rows)}
        agents[agent_type] = {
            "spawns": len(mine), "usd": _usd_metric([sp["usd"] for sp in mine], unpriced, agent_type),
            "by_entrypoint": {k: _usd(v) for k, v in sorted(eps.items())},
            "wall_seconds": round(sum(walls), 3) if walls else None, "value": value,
        }
    return agents


def _visible_usages(s) -> list:
    """Every usage a session's transcripts record: conductor, keepalive pings
    and subagents. Ping usage is real spend, so it stays in reconciliation."""
    return [s.conductor, s.keepalive] + [sub.usage for sub in s.subagents]


def _sum_usage(usages) -> dict:
    total: dict = {}
    for usage in usages:
        for key, tokens in usage.items():
            bucket = total.setdefault(key, dict.fromkeys(tokens, 0))
            for name, value in tokens.items():
                bucket[name] = None if bucket[name] is None or value is None else bucket[name] + value
    return total


def _returns(session) -> list[dict]:
    """Human turns more than IDLE_RETURN after the previous non-ping
    main-chain request. Any turn (task notification, agent hand-back) that
    made a request moves that point; a passed ping does not, and is recorded
    as preceding the return instead."""
    out, prev, pinged = [], None, False
    for turn in session.turns:
        if (turn.kind == "human" and turn.first is not None and prev is not None
                and turn.ts is not None and turn.ts - prev > IDLE_RETURN):
            out.append({"ts": turn.ts, "gap": turn.ts - prev, "with_ping": pinged, **turn.first})
        if turn.kind == "ping":
            pinged = pinged or turn.outcome == "passed"
        elif turn.last_ts is not None:
            prev, pinged = turn.last_ts, False
    return out


def _bucket(gap: timedelta) -> str:
    minutes = gap.total_seconds() / 60
    return next(name for name, upper in RETURN_BUCKETS if upper is None or minutes < upper)


def _return_metric(rows: list[dict]) -> dict:
    if not rows:
        return _absent("no returns")
    n = len(rows)
    value = {"returns": n, "cold": sum(1 for r in rows if r["cache_creation"] > r["cache_read"]),
             "avg_cache_read": round(sum(r["cache_read"] for r in rows) / n),
             "avg_cache_creation": round(sum(r["cache_creation"] for r in rows) / n)}
    return metric(PARTIAL, value, None, ["n < 10"]) if n < MIN_BUCKET_N else metric(OK, value)


def _avoided_usd(model, tokens: float, rates: dict) -> float | None:
    """Price of `tokens` at (1h cache write - cache read) for `model`."""
    write = _TELEMETRY.price_tokens(model, {"cache_creation": tokens, "cache_creation_1h": tokens}, rates)
    read = _TELEMETRY.price_tokens(model, {"cache_read": tokens}, rates)
    if write is None or read is None or write["total"] is None or read["total"] is None:
        return None
    return write["by_kind"]["cache_creation_1h"] - read["by_kind"]["cache_read"]


def _keepalive_section(inputs, rates, start, end) -> dict:
    """Keepalive pings in the window, what the passed ones cost, how warm
    the operator's returns after idle were, and an estimated net."""
    sessions = [s for inp in inputs for s in inp["sessions"]]
    pings = [t for s in sessions for t in s.turns if t.kind == "ping" and _in(t.ts, start, end)]
    if not pings:
        none = _absent("no keepalive ping in window")
        return {"pings": none, "passed_ping_usage": none,
                "returns": {name: {"with_ping": none, "no_ping": none} for name, _ in RETURN_BUCKETS},
                "estimated_net_usd": none}
    counts = {"fired": len(pings), **{o: sum(1 for t in pings if t.outcome == o) for o in PING_OUTCOMES}}
    passed = _sum_usage(t.usage for t in pings if t.outcome == "passed")
    passed_usd, unpriced = _price_usage(passed, rates) if passed else (0.0, [])
    tokens = {k: sum(t[k] for t in passed.values()) for k in ("input", "output", "cache_read", "cache_creation")}
    usage_m = (metric(PARTIAL, {**tokens, "usd": None}, None, ["unpriced models: " + ", ".join(unpriced)])
               if passed_usd is None else metric(OK, {**tokens, "usd": _usd(passed_usd)}))

    rows = [r for s in sessions for r in _returns(s) if _in(r["ts"], start, end)]
    returns, missing, avoided_tokens, avoided_usd = {}, [], 0.0, 0.0
    for name, _ in RETURN_BUCKETS:
        mine = [r for r in rows if _bucket(r["gap"]) == name]
        with_ping = [r for r in mine if r["with_ping"]]
        no_ping = [r for r in mine if not r["with_ping"]]
        returns[name] = {"with_ping": _return_metric(with_ping), "no_ping": _return_metric(no_ping)}
        warm = [r for r in with_ping if r["cache_creation"] <= r["cache_read"]]
        if not warm:
            continue
        if not no_ping:
            missing.append(f"{name}: no no-ping returns (no counterfactual)")
            continue
        if len(with_ping) < MIN_BUCKET_N or len(no_ping) < MIN_BUCKET_N:
            missing.append(f"{name}: n < 10")
        cold_rate = sum(1 for r in no_ping if r["cache_creation"] > r["cache_read"]) / len(no_ping)
        for r in warm:
            usd = _avoided_usd(r["model"], r["cache_read"] * cold_rate, rates)
            if usd is None:
                missing.append(f"{name}: unpriced model {r['model']}")
                continue
            avoided_tokens += r["cache_read"] * cold_rate
            avoided_usd += usd
    if passed_usd is None:
        net = _absent("passed pings unpriced")
    else:
        if not rows:
            missing.append("no returns after idle")
        net = metric(PARTIAL if missing else OK,
                     {"usd": _usd(avoided_usd - passed_usd), "avoided_creation_tokens": round(avoided_tokens),
                      "avoided_creation_usd": _usd(avoided_usd), "passed_ping_usd": _usd(passed_usd)},
                     None, sorted(set(missing)))
    net["basis"] = ("estimate, not a measured saving: warm returns after a passed ping x the no-ping "
                    "cold rate of the same bucket x cache_read, priced at (1h write - read), minus passed pings")
    return {"pings": metric(OK, counts), "passed_ping_usage": usage_m, "returns": returns,
            "estimated_net_usd": net}


def _cost_section(inputs, rates, start, end) -> dict:
    sessions = [s for inp in inputs for s in inp["sessions"]]
    reconciled = sorted((s for s in sessions if s.cost_covers_session and s.cost_usd is not None),
                        key=lambda s: s.session_id)
    empty = [s for s in reconciled if is_empty_session(s)]
    partial = [s for s in sessions if s.cost_state_usd is not None and not s.cost_covers_session]
    no_state = [s for s in sessions if s.cost_state_usd is None]
    empty_no_state = [s for s in no_state if is_empty_session(s)]
    all_empty = len(empty) + len(empty_no_state)

    def visible(s):
        usds, unpriced = [], set()
        for usage in _visible_usages(s):
            usd, up = _price_usage(usage, rates)
            usds.append(usd)
            unpriced.update(up)
        known = [u for u in usds if u is not None]
        return (sum(known) if known else None), unpriced

    rec_usd = _ordered_sum(s.cost_usd for s in reconciled)
    cost: dict = {
        "reconciled": {"status": OK if reconciled else ABSENT, "usd": rec_usd if reconciled else None,
                       "sessions": len(reconciled), "session_ids": sorted(s.session_id for s in reconciled),
                       "empty_sessions": len(empty),
                       "empty_session_ids": sorted(s.session_id for s in empty)},
        "partial_process": {"status": PARTIAL if partial else OK, "sessions": len(partial),
                            "last_process_usd_lower_bound":
                                _ordered_sum(s.cost_state_usd for s in sorted(partial, key=lambda s: s.session_id))
                                if partial else None,
                            "session_ids": sorted(s.session_id for s in partial)},
    }
    nv = [visible(s)[0] for s in no_state]
    nv_known = [u for u in nv if u is not None]
    cost["no_cost_state"] = {"status": ABSENT if no_state else OK, "value": None, "sessions": len(no_state),
                             "priced_visible_usd": _usd(sum(nv_known)) if nv_known else None,
                             "basis": "priced", "session_ids": sorted(s.session_id for s in no_state),
                             "empty_sessions": len(empty_no_state),
                             "empty_session_ids": sorted(s.session_id for s in empty_no_state)}
    if not sessions:
        cost["window_total"] = _absent("no in-window sessions in any store")
    else:
        gaps = len(partial) + len(no_state)
        cost["window_total"] = metric(
            PARTIAL if gaps else OK, rec_usd if reconciled else None,
            _ratio(len(reconciled) - len(empty), len(sessions) - all_empty),
            [f"partial_process: {len(partial)}", f"no_cost_state: {len(no_state)}"] if gaps else [])
        cost["window_total"]["coverage_excludes_empty_sessions"] = all_empty
        if not reconciled:
            cost["window_total"]["value"] = None
    cost["straddling_sessions"] = sum(1 for s in sessions if s.first_ts < start or s.last_ts > end)

    attributed, absent_models, exceed = [], {}, []
    unpriced_all: set = set()
    for s in reconciled:
        usd, unpriced = visible(s)
        attributed.append(usd)
        unpriced_all |= unpriced
        seen = {_model_base(key[0]) for usage in _visible_usages(s) for key in usage}
        state_tokens = 0
        for model, mu in (s.model_usage or {}).items():
            if not isinstance(mu, dict):
                continue
            state_tokens += sum(_as_int(mu.get(k)) or 0 for k in
                                ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens"))
            if _model_base(model) not in seen and isinstance(mu.get("costUSD"), (int, float)):
                absent_models[model] = absent_models.get(model, 0.0) + float(mu["costUSD"])
        vis_tokens = sum(t["input"] + t["output"] + t["cache_read"] + t["cache_creation"]
                         for usage in _visible_usages(s) for t in usage.values())
        if s.model_usage is not None and vis_tokens > state_tokens:
            exceed.append(s.session_id)
    known = [u for u in attributed if u is not None]
    if not reconciled or not known or rec_usd <= 0:
        cost["attributed_share"] = _absent("no reconciled sessions with priced visible usage")
    else:
        miss = ["unpriced models: " + ", ".join(sorted(unpriced_all))] if unpriced_all else []
        cost["attributed_share"] = metric(PARTIAL if miss else OK,
                                          {"share": _ratio(sum(known), rec_usd), "priced_visible_usd": _usd(sum(known)),
                                           "reconciled_usd": rec_usd},
                                          _ratio(len(known), len(reconciled) - len(empty)), miss)
        cost["attributed_share"]["basis"] = "priced / cost-state"
    cost["models_absent_from_transcripts"] = {m: _usd(v) for m, v in sorted(absent_models.items())}
    cost["visible_exceeds_cost_state"] = {"sessions": len(exceed), "session_ids": sorted(exceed)}
    return cost


def _mix_section(inputs, rates) -> dict:
    by_ep: dict = {}
    by_model: dict = {}
    unpriced: set = set()
    for inp in inputs:
        for s in inp["sessions"]:
            for usage in _visible_usages(s):
                for key, tokens in usage.items():
                    usd, up = _price_usage({key: tokens}, rates)
                    unpriced.update(up)
                    if usd is None:
                        continue
                    by_ep[key[1] or "(none)"] = by_ep.get(key[1] or "(none)", 0.0) + usd
                    by_model[key[0]] = by_model.get(key[0], 0.0) + usd
    total = sum(by_ep.values())
    if not total:
        none = _absent("no priced visible usage")
        return {"by_entrypoint": none, "by_model": none}
    miss = ["unpriced models: " + ", ".join(sorted(unpriced))] if unpriced else []

    def shares(d):
        m = metric(PARTIAL if miss else OK,
                   {k: {"usd": _usd(v), "share": _ratio(v, total)} for k, v in sorted(d.items())}, None, miss)
        m["basis"] = "priced"
        return m

    return {"by_entrypoint": shares(by_ep), "by_model": shares(by_model)}


def _hooks_section(inputs, start, end) -> tuple[dict, dict]:
    """Per-hook deny metrics with labels. Returns (hooks, round_cap) where
    round_cap carries D1b's current and previous-window counts."""
    length = end - start
    prev_start = start - length
    present = [inp for inp in inputs if inp["fires"] is not None]
    if not present:
        reason = "no .agentic/.enforcement-fires.jsonl"
        return {}, {"deny": _absent(reason), "fire_log": _absent(reason)}
    earliest = None
    denies: dict = {}
    prev_cap = 0
    for inp in present:
        for row in inp["fires"]:
            ts = _parse_ts(row.get("ts"))
            if ts is None:
                continue
            if earliest is None or ts < earliest:
                earliest = ts
            if row.get("decision") != "deny":
                continue
            hook = str(row.get("hook") or "(unknown)")
            if _in(ts, start, end):
                denies.setdefault(hook, []).append((ts, row, inp["repo"]))
            elif hook == ROUND_CAP_HOOK and prev_start <= ts < start:
                prev_cap += 1

    labels: dict = {}
    label_status = []
    for inp in inputs:
        if inp["labels"] is None:
            label_status.append(f"ds-feedback list failed for {inp['repo']}")
            continue
        for i, item in enumerate(inp["labels"]):
            fl = item.get("fire_label")
            if not isinstance(fl, dict) or fl.get("verdict") not in ("true_positive", "false_positive"):
                continue
            if not isinstance(fl.get("fire_key"), str) or not isinstance(fl.get("hook"), str):
                continue
            key = (fl["hook"], fl["fire_key"])
            rank = (str(item.get("ts") or ""), i)
            if key not in labels or rank >= labels[key][0]:
                labels[key] = (rank, fl["verdict"])

    hooks: dict = {}
    for hook, rows in sorted(denies.items()):
        rows.sort(key=lambda r: r[0])
        joinable = [(ts, row) for ts, row, _repo in rows if fire_key(row) is not None]
        repeats = 0
        last_by_session: dict = {}
        for ts, row in joinable:
            sid = row.get("session_id")
            if isinstance(sid, str) and sid:
                prev = last_by_session.get(sid)
                if prev is not None and ts - prev <= REPEAT_WINDOW:
                    repeats += 1
                last_by_session[sid] = ts
        labelled = {"n": 0, "fp": 0, "tp": 0}
        unlabelled = []
        for ts, row in joinable:
            hit = labels.get((hook, fire_key(row)))
            if hit is None:
                unlabelled.append((ts, row))
                continue
            labelled["n"] += 1
            labelled["fp" if hit[1] == "false_positive" else "tp"] += 1
        n = labelled["n"]
        cov = _ratio(n, len(joinable)) if joinable else None
        if n == 0:
            fp_rate = _absent("no operator labels match a deny in the window"
                              + (f" ({'; '.join(label_status)})" if label_status else ""), cov)
        else:
            fp_rate = metric(OK if n >= 5 else PARTIAL, _ratio(labelled["fp"], n), cov,
                             [] if n >= 5 else [f"only {n} labels (OK at 5)"])
        repeat = (_absent("no joinable denies (rows carry no tool_use_id or session_id)", 0.0)
                  if not joinable else
                  metric(OK, _ratio(repeats, len(joinable)), _ratio(len(joinable), len(rows)),
                         [f"{len(rows) - len(joinable)} denies not joinable"] if len(joinable) < len(rows) else []))
        hooks[hook] = {
            "deny": metric(OK, len(rows)), "joinable_deny": len(joinable), "repeat_share": repeat,
            "labelled": labelled, "labelled_fp_rate": fp_rate, "_unlabelled": unlabelled,
        }
    cap_missing = []
    cap_status = OK
    if earliest is None or earliest > prev_start:
        cap_status = PARTIAL
        cap_missing.append("fire log does not cover the preceding window")
    cap = {"deny": metric(cap_status, {"current": len(denies.get(ROUND_CAP_HOOK, [])), "previous": prev_cap},
                          None, cap_missing),
           "fire_log": metric(OK, len(present), _ratio(len(present), len(inputs)))}
    if ROUND_CAP_HOOK in hooks:
        hooks[ROUND_CAP_HOOK]["deny_previous_window"] = metric(cap_status, prev_cap, None, cap_missing)
    return hooks, cap


# ---------------------------------------------------------------------------
# Decision rules and gaps
# ---------------------------------------------------------------------------


def order_decisions(decisions: list[dict]) -> list[dict]:
    return sorted(decisions, key=lambda d: (d["rank_usd"] is None, -(d["rank_usd"] or 0),
                                            -d["evidence"]["count"], d["rule"], d["subject"]))


def _decision(rule, subject, figure, value, count, rank_usd, repo) -> dict:
    return {"rule": rule, "subject": subject, "evidence": {"figure": figure, "value": value, "count": count},
            "rank_usd": _usd(rank_usd), "route": ROUTES[rule], "repo": repo}


def _gap(input_name, m, blocks, repo) -> dict:
    return {"input": input_name, "status": m["status"], "coverage": m.get("coverage"), "blocks": blocks,
            "repo": repo}


def _decide(repo, sections, spawns, returns, pricing_ok) -> tuple[list, list]:
    decisions, gaps = [], []
    sk = sections["skeptic_rounds"]
    late_agents = {r["agent_id"] for r in returns if r["iteration"] is not None and r["iteration"] >= 2}
    late_subs = [sp for sp in spawns if sp["type"] == "skeptic" and sp["sub"].agent_id in late_agents]
    late_usd = [sp["usd"] for sp in late_subs if sp["usd"] is not None]
    d1_rank = sum(late_usd) if (pricing_ok and late_usd) else None

    m = sk["late_withheld_share"]
    if m["status"] != OK:
        gaps.append(_gap("skeptic_rounds.late_withheld_share", m, ["D1a"], repo))
    elif m["value"]["n"] >= 5 and m["value"]["share"] >= 0.5:
        decisions.append(_decision("D1a", "skeptic round-2+ withheld sign-off", "skeptic_rounds.late_withheld_share",
                                   m["value"]["share"], m["value"]["n"], d1_rank, repo))

    cap = sections["_round_cap"]["deny"]
    if cap["status"] != OK:
        gaps.append(_gap(f"hooks.{ROUND_CAP_HOOK}.deny", cap, ["D1b"], repo))
    else:
        c, p = cap["value"]["current"], cap["value"]["previous"]
        if c >= 5 and c >= 1.5 * max(p, 1):
            decisions.append(_decision("D1b", "skeptic round-cap hits rising", f"hooks.{ROUND_CAP_HOOK}.deny",
                                       {"current": c, "previous": p}, c, d1_rank, repo))

    m = sk["late_fix_verification_share"]
    if m["status"] != OK:
        gaps.append(_gap("skeptic_rounds.late_fix_verification_share", m, ["D1c"], repo))
    elif m["value"]["n"] >= 10 and m["value"]["share"] >= 0.8:
        decisions.append(_decision("D1c", "skeptic late rounds mostly re-verify fixes",
                                   "skeptic_rounds.late_fix_verification_share",
                                   m["value"]["share"], m["value"]["n"], d1_rank, repo))

    fire_log = sections["_round_cap"]["fire_log"]
    if fire_log["status"] != OK:
        gaps.append(_gap("hooks.fire_log", fire_log, ["D2"], repo))
    for hook, h in sections["hooks"].items():
        fired = None
        if h["repeat_share"]["status"] == OK and h["joinable_deny"] >= 10 and h["repeat_share"]["value"] >= 0.5:
            fired = ("repeat_share", h["repeat_share"]["value"])
        elif (h["labelled_fp_rate"]["status"] == OK and h["labelled"]["n"] >= 5
              and h["labelled_fp_rate"]["value"] >= 0.5):
            fired = ("labelled_fp_rate", h["labelled_fp_rate"]["value"])
        if fired:
            h["label_sample"] = [{"fire_key": fire_key(row), "ts": row.get("ts"), "reason": row.get("reason")}
                                 for _ts, row in sorted(h["_unlabelled"], key=lambda x: x[0], reverse=True)
                                 [:LABEL_SAMPLE_SIZE]]
            d = _decision("D2", hook, f"hooks[{hook}].{fired[0]}", fired[1], h["joinable_deny"], None, repo)
            d["hook_figures"] = {k: h[k] for k in ("deny", "joinable_deny", "repeat_share", "labelled",
                                                   "labelled_fp_rate")}
            d["label_sample"] = h["label_sample"]
            decisions.append(d)
        if h["repeat_share"]["status"] != OK:
            gaps.append(_gap(f"hooks[{hook}].repeat_share", h["repeat_share"], ["D2"], repo))
        if h["labelled_fp_rate"]["status"] != OK and h["joinable_deny"] > 0:
            gaps.append(_gap(f"hooks[{hook}].labelled_fp_rate", h["labelled_fp_rate"], ["D2"], repo))

    rework = sections["work_items"]["rework"]
    if rework["status"] != OK:
        gaps.append(_gap("work_items.rework", rework, ["D3"], repo))
    else:
        flagged = [r for r in sections["work_items"]["items"]["value"] or [] if r["flagged_d3"]]
        if flagged:
            keys = {(r["repo"], r["key"]) for r in flagged}
            usd = [sp["usd"] for sp in spawns if (sp["inp"]["repo"], sp["key"]) in keys and sp["usd"] is not None]
            decisions.append(_decision("D3", ", ".join(sorted(r["key"] for r in flagged)),
                                       "work_items.rework", [r["key"] for r in flagged], len(flagged),
                                       sum(usd) if (pricing_ok and usd) else None, repo))

    if sections["cost"]["window_total"]["status"] == PARTIAL:
        gaps.append(_gap("cost.window_total", sections["cost"]["window_total"], [], repo))
    return decisions, gaps


# ---------------------------------------------------------------------------
# evaluate()
# ---------------------------------------------------------------------------


def _sections(inputs, rates, start, end) -> tuple[dict, list, list]:
    spawns = _spawn_index(inputs, rates)
    keying = _key_spawns(spawns, inputs)
    returns = _skeptic_returns(inputs, start, end)
    skeptic = _skeptic_section(returns)
    work = _work_items(spawns, inputs, returns, keying, start, end)
    hooks, round_cap = _hooks_section(inputs, start, end)
    sections = {
        "agents": _agents_section(inputs, spawns, rates, skeptic, work, start, end),
        "skeptic_rounds": skeptic,
        "work_items": work,
        "hooks": hooks,
        "cost": _cost_section(inputs, rates, start, end),
        "mix": _mix_section(inputs, rates),
        "_round_cap": round_cap,
    }
    return sections, spawns, returns


def _public(sections: dict) -> dict:
    out = {k: v for k, v in sections.items() if not k.startswith("_")}
    for h in out["hooks"].values():
        h.pop("_unlabelled", None)
    return out


def evaluate(repos, start: datetime, end: datetime, *, base=None, ticket_re=None, use_gh=True,
             stores=None, rates=None, include_sessions=False, use_feedback=True) -> dict:
    start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
    end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
    if stores is None:
        stores = _TRANSCRIPTS.resolve_stores()
    elif not hasattr(stores, "readable"):
        stores = _TRANSCRIPTS.StoreSet([Path(s) for s in stores], [], [])
    store_set, stores = stores, list(stores.readable)
    pricing_source = "caller-supplied"
    if rates is None:
        rates, pricing_source = _TELEMETRY.load_rates(include_defaults=True)
    pricing_ok = bool(rates)
    repos = [Path(os.path.abspath(str(r))) for r in repos]
    inputs = [_load_repo(r, start, end, base, ticket_re, use_gh, stores, use_feedback) for r in repos]

    decisions, gaps, per_repo, keepalive = [], [], [], {}
    for inp in inputs:
        keepalive[inp["repo"]] = _keepalive_section([inp], rates, start, end)
        sections, spawns, returns = _sections([inp], rates, start, end)
        d, g = _decide(inp["repo"], sections, spawns, returns, pricing_ok)
        decisions.extend(d)
        gaps.extend(g)
        per_repo.append(sections)
    combined = per_repo[0] if len(inputs) == 1 else _sections(inputs, rates, start, end)[0]

    sessions = [s for inp in inputs for s in inp["sessions"]]
    by_store: dict = {str(s): 0 for s in stores}
    for s in sessions:
        by_store[str(s.store)] = by_store.get(str(s.store), 0) + 1
    store_entries = []
    for store in stores:
        unreadable_dirs = [u for r in repos for u in _TRANSCRIPTS.project_dirs_checked(r, store)[1]]
        store_entries.append(_TRANSCRIPTS.store_entry(store, by_store.get(str(store), 0), unreadable_dirs))
    store_entries += store_set.problem_entries()
    meta = {
        "repos": [inp["repo"] for inp in inputs],
        "start": start.isoformat(), "end": end.isoformat(),
        "stores": store_entries, "sessions": len(sessions),
        "base": {inp["repo"]: {"ref": inp["base"], "source": inp["base_source"],
                               "diagnostics": inp["base_diagnostics"]} for inp in inputs},
        "repo_slug": {inp["repo"]: inp["slug"] for inp in inputs},
        "ticket_pattern": {inp["repo"]: inp["pattern"].pattern for inp in inputs},
        "gh": {inp["repo"]: inp["gh_status"] for inp in inputs},
        "pricing_source": pricing_source if pricing_ok else None,
        "inputs": {inp["repo"]: {"events": inp["events_present"], "fires": inp["fires"] is not None,
                                 "sessions": len(inp["sessions"]),
                                 "merged_prs": None if inp["prs"] is None else len(inp["prs"]),
                                 "labels": None if inp["labels"] is None else len(inp["labels"])}
                   for inp in inputs},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    report = {"meta": meta, **_public(combined), "keepalive": keepalive,
              "decisions": order_decisions(decisions), "gaps": gaps}
    if include_sessions:
        report["session_rows"] = [session_summary(s, inp["repo"]) for inp in inputs for s in inp["sessions"]]
    return report
