#!/usr/bin/env python3
"""
Tests for bin/_eval.py and bin/ds-eval: metric envelopes, the four cost
groups, work-item tiers and tier agreement, fire_key and labelled FP rate,
decision-rule thresholds, ordering, routes and gaps.

Run with: python3 -m pytest bin/tests/test_ds_eval.py
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_BIN = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("_eval_under_test", str(_BIN / "_eval.py"))
ev = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(ev)
_cli_loader = importlib.machinery.SourceFileLoader("ds_eval_under_test", str(_BIN / "ds-eval"))
cli = importlib.util.module_from_spec(importlib.util.spec_from_loader(_cli_loader.name, _cli_loader))
_cli_loader.exec_module(cli)
tr = ev._TRANSCRIPTS

START = datetime(2026, 10, 1, tzinfo=timezone.utc)
END = datetime(2026, 10, 8, tzinfo=timezone.utc)
RATES = {"claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.2}}
PATTERN = ev._ticket_pattern({"AUT"})


def T(day, hour=0, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def usage(output=1_000_000, model="claude-opus-5-5", ep="cli"):
    u = tr.Usage()
    u[(model, ep, "2.1.287")] = {"input": 0, "output": output, "cache_read": 0, "cache_creation": 0,
                                 "cache_creation_5m": 0, "cache_creation_1h": 0, "messages": 1}
    return u


def sub(agent_id, agent_type="engineer", description=None, prs=(), output=1_000_000, tool_use_id=None):
    return tr.Sub(agent_id, agent_type, description, tool_use_id, usage(output), 60.0, list(prs))


def session(tmp_path, sid, subs=(), prs=(), cost=None, covers=True, first=T(2), last=T(3), sub_ends=None):
    path = tmp_path / f"{sid}.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    for s in subs:
        end = (sub_ends or {}).get(s.agent_id, last)
        sp = tmp_path / sid / "subagents" / f"agent-{s.agent_id}.jsonl"
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({"type": "user", "timestamp": iso(end)}, separators=(",", ":")) + "\n",
                      encoding="utf-8")
    return tr.Session(session_id=sid, store=tmp_path, path=path, cost_usd=cost if covers else None,
                      cost_state_usd=cost, cost_covers_session=covers and cost is not None,
                      cost_start_ts=first, model_usage=None, conductor=usage(500_000),
                      subagents=list(subs), first_ts=first, last_ts=last, pr_created=list(prs))


def pr(number, merged_at, subject=None, body="", sha=None):
    subject = subject or f"feat: change ({'#'}{number})"
    rev = ev._REVERT_SUBJECT_RE.match(ev._PR_SUBJECT_RE.sub("", subject).strip())
    return {"number": number, "sha": sha or f"{number:040x}", "merged_at": merged_at, "subject": subject,
            "body": body, "reverts": ev._REVERTS_BODY_RE.findall(body),
            "revert_subject": rev.group(1) if rev else None, "in_window": merged_at < END}


def skeptic_row(ts, agent_id, iteration=None, signed_off=None, findings=None, task_id=None):
    data = {"source": "hook", "telemetry_v": 2, "agent_id": agent_id, "tool_use_id": f"tu-{agent_id}"}
    if iteration is not None:
        data["iteration"] = iteration
    if signed_off is not None:
        data["signed_off"] = signed_off
    if findings is not None:
        data["findings_count"] = findings
    return {"ts": iso(ts), "event": "spawn_complete", "agent": "skeptic", "task_id": task_id, "data": data}


def inp(sessions=(), hook_rows=(), fires=(), prs=(), labels=(), slug="acme/w", gh_states=None,
        gh_status="disabled (--no-gh)", repo="/r"):
    return {"repo": repo, "sessions": list(sessions), "hook_rows": list(hook_rows), "events_present": True,
            "fires": None if fires is None else list(fires), "pattern": PATTERN, "prefixes": ["AUT"],
            "base": "main", "base_source": "explicit", "base_diagnostics": [],
            "prs": None if prs is None else list(prs), "slug": slug, "gh_states": gh_states,
            "gh_status": gh_status, "labels": None if labels is None else list(labels)}


def run(inputs, rates=RATES):
    sections, spawns, returns = ev._sections(inputs, rates, START, END)
    decisions, gaps = ev._decide(inputs[0]["repo"], sections, spawns, returns, bool(rates))
    return sections, spawns, decisions, gaps


def rules(decisions):
    return [d["rule"] for d in decisions]


# ---------------------------------------------------------------------------
# Envelope, fire_key
# ---------------------------------------------------------------------------


def test_absent_metric_value_is_none_never_zero():
    assert ev.metric("ABSENT", 0, 0.0, ["x"])["value"] is None
    assert ev._absent("why")["missing"] == ["why"]
    assert ev.metric("OK", 0)["value"] == 0


def test_fire_key_prefers_tool_use_id_then_session_at_ts():
    assert ev.fire_key({"tool_use_id": "toolu_1", "session_id": "s", "ts": "t"}) == "toolu_1"
    assert ev.fire_key({"session_id": "s", "ts": "2026-10-01T00:00:00Z"}) == "s@2026-10-01T00:00:00Z"
    assert ev.fire_key({"session_id": "s"}) is None
    assert ev.fire_key({"ts": "t"}) is None
    assert ev.fire_key({"tool_use_id": "", "session_id": "", "ts": "t"}) is None


# ---------------------------------------------------------------------------
# Cost reconciliation (P-R2)
# ---------------------------------------------------------------------------


def test_four_cost_groups_and_window_total(tmp_path):
    sessions = [
        session(tmp_path, "a", cost=10.25),
        session(tmp_path, "b", cost=5.5),
        session(tmp_path, "c", cost=99.0, covers=False),
        session(tmp_path, "d", cost=None),
        session(tmp_path, "e", cost=1.0, first=T(1) - timedelta(days=2)),
    ]
    sections, *_ = run([inp(sessions)])
    cost = sections["cost"]
    rec = cost["reconciled"]
    assert rec["status"] == "OK" and rec["sessions"] == 3
    assert rec["usd"] == 10.25 + 5.5 + 1.0
    assert rec["session_ids"] == ["a", "b", "e"]
    pp = cost["partial_process"]
    assert (pp["status"], pp["sessions"], pp["last_process_usd_lower_bound"]) == ("PARTIAL", 1, 99.0)
    nc = cost["no_cost_state"]
    assert (nc["status"], nc["value"], nc["sessions"], nc["basis"]) == ("ABSENT", None, 1, "priced")
    assert nc["priced_visible_usd"] == 10.0
    wt = cost["window_total"]
    assert wt["status"] == "PARTIAL" and wt["value"] == rec["usd"]
    assert wt["coverage"] == 0.6
    assert wt["missing"] == ["partial_process: 1", "no_cost_state: 1"]
    assert cost["straddling_sessions"] == 1
    share = cost["attributed_share"]
    assert share["status"] == "OK" and share["value"]["priced_visible_usd"] == 30.0


def test_window_total_ok_only_when_every_session_reconciles(tmp_path):
    sections, *_ = run([inp([session(tmp_path, "a", cost=2.0)])])
    wt = sections["cost"]["window_total"]
    assert (wt["status"], wt["value"], wt["coverage"], wt["missing"]) == ("OK", 2.0, 1.0, [])
    pp, nc = sections["cost"]["partial_process"], sections["cost"]["no_cost_state"]
    assert pp["last_process_usd_lower_bound"] is None and nc["priced_visible_usd"] is None


def test_no_sessions_is_absent_not_zero():
    sections, *_ = run([inp([])])
    cost = sections["cost"]
    assert cost["reconciled"]["status"] == "ABSENT" and cost["reconciled"]["usd"] is None
    assert cost["window_total"]["status"] == "ABSENT" and cost["window_total"]["value"] is None
    assert cost["window_total"]["missing"]
    assert cost["attributed_share"]["status"] == "ABSENT"
    assert sections["mix"]["by_entrypoint"]["status"] == "ABSENT"


def test_no_pricing_is_absent_with_reason(tmp_path):
    sections, *_ = run([inp([session(tmp_path, "a", cost=2.0, subs=[sub("e1")])])], rates={})
    usd = sections["agents"]["engineer"]["usd"]
    assert usd["status"] == "ABSENT" and usd["value"] is None and "claude-opus-5-5" in usd["missing"][0]
    assert sections["cost"]["reconciled"]["usd"] == 2.0


def test_agent_dollars_are_priced_and_split_by_entrypoint(tmp_path):
    s = session(tmp_path, "a", cost=2.0, subs=[sub("e1"), sub("e2", output=500_000)])
    sections, *_ = run([inp([s])])
    eng = sections["agents"]["engineer"]
    assert eng["spawns"] == 2 and eng["usd"]["value"] == 30.0 and eng["usd"]["basis"] == "priced"
    assert eng["by_entrypoint"] == {"cli": 30.0}
    assert sections["agents"]["conductor"]["usd"]["value"] == 10.0
    assert sections["mix"]["by_entrypoint"]["value"]["cli"]["share"] == 1.0


# ---------------------------------------------------------------------------
# Work-item tiers and agreement
# ---------------------------------------------------------------------------


def test_tiers_one_to_four_first_match_wins(tmp_path):
    subs = [
        sub("t1", description="AUT-1 implement"),
        sub("t2", description="no id here", tool_use_id="tu-t2"),
        sub("t3", description="two AUT-3 and AUT-30", prs=[("acme/w", 30, T(2, 5))]),
        sub("t4", description=None),
        sub("t5", description=None, prs=[("other/repo", 31, T(2, 5))]),
    ]
    s = session(tmp_path, "s", subs=subs, prs=[("acme/w", 40, T(2, 7)), (None, 41, T(2, 9))],
                sub_ends={"t1": T(2, 1), "t2": T(2, 1), "t3": T(2, 6), "t4": T(2, 6), "t5": T(2, 8)})
    hook_rows = [{"ts": iso(T(2)), "event": "spawn_start", "agent": "engineer", "task_id": "AUT-2-unit",
                  "data": {"source": "hook", "tool_use_id": "tu-t2"}}]
    prs = [pr(30, T(3), "feat(AUT-3): x (#30)"), pr(40, T(3), "feat(AUT-4): y (#40)"),
           pr(41, T(3, 2), "chore: z (#41)")]
    _sections, spawns, *_ = run([inp([s], hook_rows=hook_rows, prs=prs)])
    by = {sp["sub"].agent_id: sp for sp in spawns}
    assert (by["t1"]["tier"], by["t1"]["key"]) == (1, "AUT-1")
    assert (by["t2"]["tier"], by["t2"]["key"]) == (2, "AUT-2")
    assert (by["t3"]["tier"], by["t3"]["key"], by["t3"]["pr"]) == (3, "AUT-3", 30)
    assert (by["t4"]["tier"], by["t4"]["key"], by["t4"]["pr"]) == (4, "AUT-4", 40)
    assert (by["t5"]["tier"], by["t5"]["pr"], by["t5"]["repo_inferred"]) == (4, 41, True)
    assert by["t5"]["key"] == "pr:acme/w#41"


def test_own_pr_tier_keys_a_pr_creating_engineer_to_its_own_pr(tmp_path):
    eng = sub("e", description=None, prs=[("acme/w", 10, T(2, 1))])
    s = session(tmp_path, "s", subs=[eng], prs=[("acme/w", 11, T(2, 5))], sub_ends={"e": T(2, 2)})
    prs = [pr(10, T(3), "feat(AUT-10): mine (#10)"), pr(11, T(3), "feat(AUT-11): next (#11)")]
    sections, spawns, *_ = run([inp([s], prs=prs)])
    (sp,) = spawns
    assert (sp["tier"], sp["pr"], sp["key"]) == (3, 10, "AUT-10")


def test_repo_none_ref_matches_only_a_merged_pr_of_the_repo(tmp_path):
    eng = sub("e", prs=[(None, 77, T(2, 1))])
    s = session(tmp_path, "s", subs=[eng], sub_ends={"e": T(2, 2)})
    _s, spawns, *_ = run([inp([s], prs=[pr(78, T(3))])])
    assert spawns[0]["tier"] is None
    _s, spawns, *_ = run([inp([s], prs=[pr(77, T(3))])])
    assert spawns[0]["tier"] == 3 and spawns[0]["repo_inferred"] is True


def _agreement_fixture(tmp_path, compared, agree):
    subs, prs, refs, ends = [], [], [], {}
    for i in range(compared):
        subs.append(sub(f"a{i}", description=f"AUT-{100 + i} work"))
        ticket = 100 + i if i < agree else 900 + i
        prs.append(pr(500 + i, T(3), f"feat(AUT-{ticket}): x (#{500 + i})"))
        refs.append(("acme/w", 500 + i, T(2, 1, i)))
        ends[f"a{i}"] = T(2, 1, i)
    subs.append(sub("only4", description=None))
    ends["only4"] = T(2, 0, 30)
    s = session(tmp_path, "s", subs=subs, prs=refs, sub_ends=ends)
    return run([inp([s], prs=prs)])


@pytest.mark.parametrize("compared,agree,disabled", [(20, 15, True), (20, 16, False), (19, 0, False)])
def test_tier4_disable_rule(tmp_path, compared, agree, disabled):
    sections, spawns, *_ = _agreement_fixture(tmp_path, compared, agree)
    work = sections["work_items"]
    assert work["tier_agreement"]["4"] == {"agree": agree, "compared": compared}
    assert work["tier4_disabled"] is disabled
    only4 = next(sp for sp in spawns if sp["sub"].agent_id == "only4")
    assert only4["tier"] == (None if disabled else 4)
    assert any("tier 4 disabled" in m for m in work["coverage"]["missing"]) is disabled


def test_tier_agreement_for_tiers_two_and_three(tmp_path):
    subs = [sub("x", description="AUT-5 a", tool_use_id="tu-x", prs=[("acme/w", 9, T(2, 1))]),
            sub("y", description="AUT-6 b", tool_use_id="tu-y")]
    hook_rows = [{"ts": iso(T(2)), "event": "spawn_start", "agent": "engineer", "task_id": "AUT-5",
                  "data": {"source": "hook", "tool_use_id": "tu-x"}},
                 {"ts": iso(T(2)), "event": "spawn_start", "agent": "engineer", "task_id": "AUT-7",
                  "data": {"source": "hook", "tool_use_id": "tu-y"}}]
    s = session(tmp_path, "s", subs=subs)
    sections, *_ = run([inp([s], hook_rows=hook_rows, prs=[pr(9, T(3), "x (#9)", body="Closes AUT-5")])])
    agr = sections["work_items"]["tier_agreement"]
    assert agr["2"] == {"agree": 1, "compared": 2}
    assert agr["3"] == {"agree": 1, "compared": 1}


# ---------------------------------------------------------------------------
# Skeptic rules D1a / D1c and D1b
# ---------------------------------------------------------------------------


def _late(n, withheld=0, clean=0, iteration=2):
    rows = []
    for i in range(n):
        major = 0 if i < clean else 1
        rows.append(skeptic_row(T(2, 1, i), f"k{i}", iteration=iteration, signed_off=i >= withheld,
                                findings={"critical": 0, "major": major, "minor": 1}))
    return rows


@pytest.mark.parametrize("n,withheld,fires", [(5, 3, True), (4, 3, False), (6, 3, True), (5, 2, False)])
def test_d1a_threshold(n, withheld, fires):
    _s, _sp, decisions, gaps = run([inp(hook_rows=_late(n, withheld=withheld), fires=[])])
    assert ("D1a" in rules(decisions)) is fires


@pytest.mark.parametrize("n,clean,fires", [(10, 8, True), (9, 9, False), (10, 7, False)])
def test_d1c_threshold(n, clean, fires):
    _s, _sp, decisions, _g = run([inp(hook_rows=_late(n, clean=clean), fires=[])])
    assert ("D1c" in rules(decisions)) is fires


def test_skeptic_shares_absent_without_fields_and_report_coverage():
    rows = [skeptic_row(T(2), "a", iteration=2), skeptic_row(T(2), "b", iteration=1)]
    sections, _sp, decisions, gaps = run([inp(hook_rows=rows, fires=[])])
    m = sections["skeptic_rounds"]["late_withheld_share"]
    assert m["status"] == "ABSENT" and m["value"] is None and m["coverage"] == 0.0
    assert {g["input"] for g in gaps} >= {"skeptic_rounds.late_withheld_share",
                                          "skeptic_rounds.late_fix_verification_share"}
    rows += _late(5, withheld=5)
    sections, *_ = run([inp(hook_rows=rows, fires=[])])
    m = sections["skeptic_rounds"]["late_withheld_share"]
    assert m["status"] == "OK" and m["value"]["n"] == 5 and m["coverage"] == round(5 / 6, 4)
    assert m["missing"] == ["1 late returns carry no signed_off"]
    by_iter = sections["skeptic_rounds"]["by_iteration"]["value"]
    assert by_iter["2"]["withheld"] == 5 and by_iter["2"]["signed_off_missing"] == 1


def _cap_rows(current, previous):
    rows = [{"ts": iso(T(1) - timedelta(days=8)), "hook": "other", "decision": "allow"}]
    rows += [{"ts": iso(T(2, 0, i)), "hook": ev.ROUND_CAP_HOOK, "decision": "deny"} for i in range(current)]
    rows += [{"ts": iso(T(1) - timedelta(days=3, minutes=i)), "hook": ev.ROUND_CAP_HOOK, "decision": "deny"}
             for i in range(previous)]
    return rows


@pytest.mark.parametrize("c,p,fires", [(5, 3, True), (5, 0, True), (4, 0, False), (6, 4, True), (5, 4, False)])
def test_d1b_threshold(c, p, fires):
    sections, _sp, decisions, _g = run([inp(fires=_cap_rows(c, p))])
    assert ("D1b" in rules(decisions)) is fires
    if fires:
        d = next(d for d in decisions if d["rule"] == "D1b")
        assert d["evidence"] == {"figure": f"hooks.{ev.ROUND_CAP_HOOK}.deny",
                                 "value": {"current": c, "previous": p}, "count": c}


def test_d1b_is_a_gap_when_the_fire_log_is_missing_or_short():
    _s, _sp, decisions, gaps = run([inp(fires=None)])
    assert "D1b" not in rules(decisions)
    assert any(g["input"] == f"hooks.{ev.ROUND_CAP_HOOK}.deny" and g["status"] == "ABSENT" for g in gaps)
    short = [r for r in _cap_rows(9, 0) if r["decision"] == "deny"]
    _s, _sp, decisions, gaps = run([inp(fires=short)])
    assert "D1b" not in rules(decisions)
    assert any(g["blocks"] == ["D1b"] and g["status"] == "PARTIAL" for g in gaps)


def test_d1_rank_is_priced_late_skeptic_subs_or_none(tmp_path):
    subs = [sub(f"k{i}", agent_type="skeptic", output=100_000) for i in range(5)] + [
        sub("early", agent_type="skeptic")]
    s = session(tmp_path, "s", subs=subs)
    rows = _late(5, withheld=5) + [skeptic_row(T(2), "early", iteration=1, signed_off=True)]
    _s, _sp, decisions, _g = run([inp([s], hook_rows=rows, fires=[])])
    assert next(d for d in decisions if d["rule"] == "D1a")["rank_usd"] == 10.0
    _s, _sp, decisions, _g = run([inp([s], hook_rows=rows, fires=[])], rates={})
    assert next(d for d in decisions if d["rule"] == "D1a")["rank_usd"] is None


# ---------------------------------------------------------------------------
# D2 and labels
# ---------------------------------------------------------------------------


def _denies(n, hook="enforce-x", spacing=20, sessions=1, base=T(2)):
    return [{"ts": iso(base + timedelta(minutes=i * spacing)), "hook": hook, "decision": "deny",
             "session_id": f"s{i % sessions}", "tool_use_id": f"tu{i}", "reason": f"r{i}"} for i in range(n)]


@pytest.mark.parametrize("n,spacing,fires", [(10, 10, True), (9, 10, False), (10, 20, False)])
def test_d2_repeat_threshold(n, spacing, fires):
    rows = _denies(n, spacing=spacing)
    sections, _sp, decisions, _g = run([inp(fires=rows)])
    h = sections["hooks"]["enforce-x"]
    assert h["joinable_deny"] == n
    assert ("D2" in rules(decisions)) is fires
    if fires:
        d = next(d for d in decisions if d["rule"] == "D2")
        assert d["rank_usd"] is None and d["evidence"]["count"] == n and d["subject"] == "enforce-x"
        assert [x["fire_key"] for x in h["label_sample"]] == [f"tu{i}" for i in range(n - 1, n - 6, -1)]
    else:
        assert "label_sample" not in h


def _paired_denies(repeats, n=10):
    """n denies in one session: `repeats` of them 5 minutes after the previous
    deny, the rest an hour after it."""
    ts, rows = T(2), []
    for i in range(n):
        ts += timedelta(minutes=5 if 0 < i <= repeats else 60)
        rows.append({"ts": iso(ts), "hook": "enforce-x", "decision": "deny", "session_id": "s",
                     "tool_use_id": f"tu{i}"})
    return rows


@pytest.mark.parametrize("repeats,fires", [(5, True), (4, False)])
def test_d2_repeat_share_at_and_below_half(repeats, fires):
    sections, _sp, decisions, _g = run([inp(fires=_paired_denies(repeats))])
    assert sections["hooks"]["enforce-x"]["repeat_share"]["value"] == repeats / 10
    assert ("D2" in rules(decisions)) is fires


def test_d2_repeat_arm_needs_ten_joinable_denies():
    rows = _paired_denies(5, n=9)
    sections, _sp, decisions, _g = run([inp(fires=rows)])
    assert sections["hooks"]["enforce-x"]["repeat_share"]["value"] == round(5 / 9, 4)
    assert "D2" not in rules(decisions)


@pytest.mark.parametrize("gap,repeat", [(timedelta(minutes=15), True),
                                        (timedelta(minutes=15, seconds=1), False)])
def test_repeat_window_is_inclusive_at_fifteen_minutes(gap, repeat):
    rows = [{"ts": iso(T(2) + gap * i), "hook": "enforce-x", "decision": "deny", "session_id": "s",
             "tool_use_id": f"tu{i}"} for i in range(2)]
    sections, *_ = run([inp(fires=rows)])
    assert sections["hooks"]["enforce-x"]["repeat_share"]["value"] == (0.5 if repeat else 0.0)


def test_labels_are_keyed_by_hook_and_fire_key():
    rows = []
    for i in range(6):
        for hook in ("hA", "hB"):
            rows.append({"ts": iso(T(2, i)), "hook": hook, "decision": "deny", "session_id": "s",
                         "tool_use_id": f"tu{i}"})
    labels = [_label(f"tu{i}", "false_positive", hook="hA") for i in range(5)]
    sections, _sp, decisions, _g = run([inp(fires=rows, labels=labels)])
    assert sections["hooks"]["hA"]["labelled"] == {"n": 5, "fp": 5, "tp": 0}
    assert sections["hooks"]["hB"]["labelled"] == {"n": 0, "fp": 0, "tp": 0}
    assert [d["subject"] for d in decisions if d["rule"] == "D2"] == ["hA"]


def test_missing_fire_log_is_a_gap_blocking_d2_and_d1b():
    _s, _sp, decisions, gaps = run([inp(fires=None)])
    by_input = {g["input"]: g for g in gaps}
    assert by_input["hooks.fire_log"]["status"] == "ABSENT" and by_input["hooks.fire_log"]["blocks"] == ["D2"]
    assert by_input[f"hooks.{ev.ROUND_CAP_HOOK}.deny"]["blocks"] == ["D1b"]
    _s, _sp, _d, gaps = run([inp(fires=[])])
    assert "hooks.fire_log" not in {g["input"] for g in gaps}


def test_multi_repo_d2_carries_its_own_repo_figures_and_sample(monkeypatch):
    def denies(prefix, spacing):
        return [{"ts": iso(T(2) + timedelta(minutes=spacing * i)), "hook": "enforce-x", "decision": "deny",
                 "session_id": f"{prefix}s", "tool_use_id": f"{prefix}{i}"} for i in range(10)]

    inputs = {"/r1": inp(repo="/r1", fires=denies("a", 5), prs=None),
              "/r2": inp(repo="/r2", fires=denies("b", 60), prs=None)}
    monkeypatch.setattr(ev, "_load_repo", lambda r, *a: inputs[str(r)])
    report = ev.evaluate(["/r1", "/r2"], START, END, use_gh=False, stores=[], rates=RATES)
    (d2,) = [d for d in report["decisions"] if d["rule"] == "D2"]
    assert d2["repo"] == "/r1"
    assert d2["hook_figures"]["joinable_deny"] == 10 and d2["hook_figures"]["repeat_share"]["value"] == 0.9
    assert [x["fire_key"] for x in d2["label_sample"]] == ["a9", "a8", "a7", "a6", "a5"]
    assert report["hooks"]["enforce-x"]["joinable_deny"] == 20
    assert all("_unlabelled" not in h for h in report["hooks"].values())
    json.dumps(report, default=str)


def test_models_absent_from_transcripts_ignores_context_window_tag(tmp_path):
    s = session(tmp_path, "a", cost=4.0)
    s.model_usage = {"claude-opus-5-5[1m]": {"costUSD": 3.0}, "claude-haiku-4-5": {"costUSD": 1.0}}
    sections, *_ = run([inp([s])])
    assert sections["cost"]["models_absent_from_transcripts"] == {"claude-haiku-4-5": 1.0}


def _ticket_entry(findings):
    runs = [{"findings_count": f, "iteration": i + 1, "qa_result": None, "end_ts": iso(T(2, i)),
             "model": "claude-opus-5-5", "run_tokens": None} for i, f in enumerate(findings)]
    rec = type("Rec", (), {"agent": "skeptic", "runs": runs, "start_ts": iso(T(2)), "model": None})()
    return {"recs": [rec], "ledger": [], "first_spawn_ts": T(2), "repos": {"/r"}}


def test_ticket_row_counts_every_skeptic_run_and_reports_findings_coverage():
    entry = _ticket_entry([{"critical": 0, "major": 1, "minor": 0}, None, None])
    row = ev._ticket_row("AUT-1", entry, [], [], "NOT_FETCHED", END, RATES)
    assert row["skeptic_reviews"] == 3 and row["skeptic_reviews_source"] == "telemetry"
    assert row["skeptic_reviews_with_findings"] == 1
    assert row["findings"] == {"critical": 0, "major": 1, "minor": 0}
    entry = _ticket_entry([])
    entry["ledger"] = [{"skeptic_rounds": 4}]
    row = ev._ticket_row("AUT-1", entry, [], [], "NOT_FETCHED", END, RATES)
    assert (row["skeptic_reviews"], row["skeptic_reviews_source"], row["skeptic_reviews_with_findings"]) == (
        4, "ledger", 0)


def _post_merge_row(findings, ledger_rounds=None):
    runs = [{"findings_count": f, "iteration": i + 1, "qa_result": None, "end_ts": iso(T(4, i)),
             "model": "claude-opus-5-5", "run_tokens": None} for i, f in enumerate(findings)]
    rec = type("Rec", (), {"agent": "skeptic", "runs": runs, "start_ts": iso(T(2)), "model": None})()
    entry = {"recs": [rec], "ledger": [{"skeptic_rounds": ledger_rounds}] if ledger_rounds else [],
             "first_spawn_ts": T(2), "repos": {"/r"}}
    credited = [{"repo": "/r", "number": 1, "merged_at": T(3)}]
    return ev._ticket_row("AUT-1", entry, [], credited, "OK", END, RATES)


def test_post_merge_findings_null_when_a_post_merge_run_lacks_findings_count():
    row = _post_merge_row([None, None, None], ledger_rounds=3)
    assert row["findings"] is None
    assert row["post_merge_findings"] is None
    row = _post_merge_row([{"critical": 1, "major": 2, "minor": 0}, None])
    assert row["post_merge_findings"] is None
    row = _post_merge_row([{"critical": 1, "major": 2, "minor": 0}, {"critical": 0, "major": 1, "minor": 5}])
    assert row["post_merge_findings"] == 4
    row = _post_merge_row([])
    assert row["post_merge_findings"] == 0 and row["skeptic_reviews"] == 0
    row = _post_merge_row([], ledger_rounds=3)
    assert row["skeptic_reviews_source"] == "ledger" and row["post_merge_findings"] is None


def test_multi_repo_table_prefixes_decisions_and_gaps_with_repo(monkeypatch, capsys):
    def denies(prefix):
        return [{"ts": iso(T(2) + timedelta(minutes=5 * i)), "hook": "enforce-x", "decision": "deny",
                 "session_id": f"{prefix}s", "tool_use_id": f"{prefix}{i}"} for i in range(10)]

    inputs = {"/r1": inp(repo="/r1", fires=denies("a"), prs=None), "/r2": inp(repo="/r2", fires=None, prs=None)}
    monkeypatch.setattr(ev, "_load_repo", lambda r, *a: inputs[str(r)])
    report = ev.evaluate(["/r1", "/r2"], START, END, use_gh=False, stores=[], rates=RATES)
    cli._print_table(report)
    out = capsys.readouterr().out
    decisions = out.split("[decisions]")[1].split("[gaps]")[0].strip().splitlines()
    gaps = out.split("[gaps]")[1].strip().splitlines()
    assert decisions and all(line.strip().startswith(("[/r1] ", "[/r2] ")) for line in decisions)
    assert any(line.strip().startswith("[/r1] D2") for line in decisions)
    assert gaps and all(line.strip().startswith(("[/r1] ", "[/r2] ")) for line in gaps)
    assert any(line.strip().startswith("[/r2] hooks.fire_log") for line in gaps)


def test_repeat_needs_same_session():
    rows = _denies(10, spacing=10, sessions=2)
    sections, *_ = run([inp(fires=rows)])
    assert sections["hooks"]["enforce-x"]["repeat_share"]["value"] == 0.0


def _label(key, verdict, ts="2026-10-09T00:00:00Z", hook="enforce-x"):
    return {"ts": ts, "status": "triaged", "fire_label": {"hook": hook, "fire_key": key,
                                                          "fire_ts": "x", "verdict": verdict}}


def test_labelled_fp_rate_latest_label_wins_and_unmatched_ignored():
    rows = _denies(6, spacing=30)
    labels = [_label("tu0", "true_positive", ts="2026-10-09T00:00:00Z"),
              _label("tu0", "false_positive", ts="2026-10-10T00:00:00Z"),
              _label("tu1", "false_positive", ts="2026-10-10T00:00:00Z"),
              _label("tu1", "true_positive", ts="2026-10-09T00:00:00Z"),
              _label("nope", "false_positive")]
    sections, *_ = run([inp(fires=rows, labels=labels)])
    h = sections["hooks"]["enforce-x"]
    assert h["labelled"] == {"n": 2, "fp": 2, "tp": 0}
    m = h["labelled_fp_rate"]
    assert (m["status"], m["value"], m["coverage"]) == ("PARTIAL", 1.0, round(2 / 6, 4))


@pytest.mark.parametrize("labelled,fp,status,fires", [
    (5, 3, "OK", True), (4, 4, "PARTIAL", False), (1, 1, "PARTIAL", False), (5, 2, "OK", False),
    (6, 3, "OK", True), (6, 2, "OK", False), (0, 0, "ABSENT", False)])
def test_d2_labelled_threshold_and_status(labelled, fp, status, fires):
    rows = _denies(6, spacing=30)
    labels = [_label(f"tu{i}", "false_positive" if i < fp else "true_positive") for i in range(labelled)]
    sections, _sp, decisions, gaps = run([inp(fires=rows, labels=labels)])
    m = sections["hooks"]["enforce-x"]["labelled_fp_rate"]
    assert m["status"] == status
    if status == "ABSENT":
        assert m["value"] is None and m["coverage"] == 0.0
    assert ("D2" in rules(decisions)) is fires
    if fires:
        assert next(d for d in decisions if d["rule"] == "D2")["evidence"]["figure"] == \
            "hooks[enforce-x].labelled_fp_rate"
    if status != "OK":
        assert any(g["input"] == "hooks[enforce-x].labelled_fp_rate" for g in gaps)


def test_unjoinable_denies_give_absent_repeat_share():
    rows = [{"ts": iso(T(2)), "hook": "enforce-y", "decision": "deny"}]
    sections, _sp, _d, gaps = run([inp(fires=rows)])
    h = sections["hooks"]["enforce-y"]
    assert h["deny"]["value"] == 1 and h["joinable_deny"] == 0
    assert h["repeat_share"]["status"] == "ABSENT" and h["repeat_share"]["value"] is None
    assert any(g["input"] == "hooks[enforce-y].repeat_share" for g in gaps)


# ---------------------------------------------------------------------------
# D3 and value signals
# ---------------------------------------------------------------------------


def _d3_fixture(tmp_path, iteration, follow_up_days=None, revert_days=None):
    k = sub("k", agent_type="skeptic", description="AUT-9 review")
    e = sub("e", description="AUT-9 build", output=200_000)
    s = session(tmp_path, "s", subs=[k, e])
    rows = [skeptic_row(T(2), "k", iteration=iteration)]
    prs = [pr(50, T(3), "feat(AUT-9): first (#50)")]
    if follow_up_days is not None:
        prs.append(pr(51, T(3) + timedelta(days=follow_up_days), "fix: follow (#51)", body="Refs AUT-9"))
    if revert_days is not None:
        prs.append(pr(52, T(3) + timedelta(days=revert_days), 'Revert "feat(AUT-9): first" (#52)'))
    return run([inp([s], hook_rows=rows, fires=[], prs=prs)])


@pytest.mark.parametrize("iteration,follow,revert,fires", [
    (3, 7, None, True), (2, 1, None, False), (3, 8, None, False), (3, None, 2, True), (3, None, None, False)])
def test_d3_threshold(tmp_path, iteration, follow, revert, fires):
    sections, _sp, decisions, _g = _d3_fixture(tmp_path, iteration, follow, revert)
    assert ("D3" in rules(decisions)) is fires
    if fires:
        d = next(d for d in decisions if d["rule"] == "D3")
        assert d["subject"] == "AUT-9" and d["evidence"]["count"] == 1
        assert d["rank_usd"] == 24.0


def test_d3_gap_when_no_merged_pr_history(tmp_path):
    s = session(tmp_path, "s", subs=[sub("e", description="AUT-9 x")])
    sections, _sp, decisions, gaps = run([inp([s], prs=None, fires=[])])
    assert sections["work_items"]["rework"]["status"] == "ABSENT"
    assert "merged-PR history" in sections["work_items"]["rework"]["missing"][0]
    assert any(g["input"] == "work_items.rework" and g["blocks"] == ["D3"] for g in gaps)


def test_engineer_value_own_pr_outcome_and_gh_partial(tmp_path):
    engs = [sub("m", prs=[("acme/w", 60, T(2, 1))]), sub("o", prs=[("acme/w", 61, T(2, 1))])]
    s = session(tmp_path, "s", subs=engs)
    prs = [pr(60, T(3), "feat(AUT-1): a (#60)"), pr(62, T(4), 'Revert "feat(AUT-1): a" (#62)')]
    sections, *_ = run([inp([s], prs=prs, fires=[])])
    own = sections["agents"]["engineer"]["value"]["own"]
    assert own["status"] == "PARTIAL" and own["value"]["merged"] == 1 and own["value"]["reverted"] == 1
    assert own["value"]["unknown"] == 1 and "gh" in own["missing"][0]
    sections, *_ = run([inp([s], prs=prs, fires=[], gh_states={61: "open"}, gh_status="ok")])
    own = sections["agents"]["engineer"]["value"]["own"]
    assert own["status"] == "OK" and own["value"]["open"] == 1 and own["coverage"] == 1.0


def test_value_signals_absent_and_correlational(tmp_path):
    s = session(tmp_path, "s", subs=[sub("a", agent_type="architect", description="AUT-1 plan"),
                                     sub("q", agent_type="qa-engineer", description="AUT-1 qa")])
    qa_rows = [{"ts": iso(T(2)), "event": "spawn_complete", "agent": "qa-engineer",
                "data": {"source": "hook", "agent_id": "q"}}]
    sections, *_ = run([inp([s], hook_rows=qa_rows, prs=[pr(70, T(3), "feat(AUT-1): x (#70)")], fires=[])])
    arch = sections["agents"]["architect"]["value"]
    assert arch["own"]["status"] == "ABSENT"
    assert arch["work_items"]["basis"] == "correlational"
    assert arch["work_items"]["value"]["with"] == {"n": 1, "merged_share": 1.0, "rework_share": 0.0,
                                                   "merged_n": 1}
    assert sections["agents"]["qa-engineer"]["value"]["own"]["status"] == "ABSENT"
    qa_rows[0]["data"]["qa_result"] = "FAIL"
    sections, *_ = run([inp([s], hook_rows=qa_rows, prs=[], fires=[])])
    qa = sections["agents"]["qa-engineer"]["value"]["own"]
    assert qa["status"] == "OK" and qa["value"]["fail_or_partial"] == 1


# ---------------------------------------------------------------------------
# Ordering, routes, gaps
# ---------------------------------------------------------------------------


def test_ordering_key_puts_priced_first_then_count():
    def d(rule, subject, rank, count):
        return ev._decision(rule, subject, "f", 0, count, rank, "/r")

    got = ev.order_decisions([d("D2", "b", None, 30), d("D3", "x", 5.0, 1), d("D1a", "s", 50.0, 2),
                              d("D2", "a", None, 30), d("D1b", "c", None, 40), d("D1c", "z", 5.0, 9)])
    assert [(x["rule"], x["subject"]) for x in got] == [
        ("D1a", "s"), ("D1c", "z"), ("D3", "x"), ("D1b", "c"), ("D2", "a"), ("D2", "b")]


def test_route_rule():
    assert ev.ROUTES == {"D1a": "update-agentic-engineering", "D1b": "update-agentic-engineering",
                         "D1c": "update-agentic-engineering", "D2": "prune-harness", "D3": "tracker-ticket"}
    assert ev._decision("D2", "h", "f", 1, 1, None, "/r")["route"] == "prune-harness"


def test_gaps_carry_no_route_and_no_rank(tmp_path):
    s = session(tmp_path, "s", cost=None, subs=[sub("e", description="AUT-1")])
    rows = [skeptic_row(T(2), "a", iteration=2)]
    _s, _sp, _d, gaps = run([inp([s], hook_rows=rows, fires=_denies(1) + [{"ts": iso(T(2)), "hook": "h2",
                                                                            "decision": "deny"}], prs=None)])
    assert gaps
    for g in gaps:
        assert set(g) == {"input", "status", "coverage", "blocks", "repo"}, g
        assert g["status"] in ("ABSENT", "PARTIAL")
    assert any(g["input"] == "cost.window_total" and g["blocks"] == [] for g in gaps)


# ---------------------------------------------------------------------------
# End to end: evaluate() and the CLI over real files (P-R4)
# ---------------------------------------------------------------------------


def _git(repo, *args, date=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.com")
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)


def _repo_with_history(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "remote", "add", "origin", "https://github.com/acme/w.git")
    for i, (subject, date) in enumerate([("feat(AUT-1): a (#10)", "2026-10-03T00:00:00Z"),
                                         ("chore: direct push", "2026-10-03T01:00:00Z"),
                                         ("fix(AUT-1): b (#11)", "2026-10-04T00:00:00Z"),
                                         ("feat(AUT-2): c (#12)", "2026-10-12T00:00:00Z")]):
        (repo / f"f{i}").write_text(str(i))
        _git(repo, "add", f"f{i}")
        _git(repo, "commit", "-q", "-m", subject, date=date)
    return repo


def test_git_merged_prs_reads_first_parent_pr_commits(tmp_path):
    repo = _repo_with_history(tmp_path)
    prs = ev.git_merged_prs(repo, "main", START, END + ev.LOOKAHEAD)
    assert [(p["number"], p["subject"]) for p in prs] == [
        (10, "feat(AUT-1): a (#10)"), (11, "fix(AUT-1): b (#11)"), (12, "feat(AUT-2): c (#12)")]
    assert ev.git_merged_prs(repo, "no-such-ref", START, END) is None
    assert ev._repo_slug(repo) == "acme/w"


def test_evaluate_missing_inputs_are_absent_with_reasons(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_feedback_items", lambda repo: None)
    repo = tmp_path / "bare"
    repo.mkdir()
    report = ev.evaluate([repo], START, END, base=None, use_gh=False, stores=[tmp_path / "nostore"], rates={})
    assert set(report) == {"meta", *ev.SECTIONS}
    assert report["cost"]["window_total"]["status"] == "ABSENT"
    assert report["cost"]["window_total"]["missing"] == ["no in-window sessions in any store"]
    assert report["skeptic_rounds"]["late_withheld_share"]["status"] == "ABSENT"
    assert report["work_items"]["coverage"]["status"] == "ABSENT"
    assert report["work_items"]["rework"]["status"] == "ABSENT"
    assert report["hooks"] == {} and report["decisions"] == []
    assert report["meta"]["gh"][str(repo)] == "disabled (--no-gh)"
    assert report["meta"]["inputs"][str(repo)] == {"events": False, "fires": False, "sessions": 0,
                                                   "merged_prs": None, "labels": None}
    assert {g["input"] for g in report["gaps"]} >= {"work_items.rework", f"hooks.{ev.ROUND_CAP_HOOK}.deny"}


def _write_store(tmp_path, repo):
    store = tmp_path / "store"
    pdir = store / tr.project_dir_prefix(repo)
    pdir.mkdir(parents=True)
    cwd = str(repo)

    def asst(mid, ts, out):
        return {"type": "assistant", "timestamp": ts, "cwd": cwd, "entrypoint": "cli", "version": "1",
                "message": {"id": mid, "model": "claude-opus-5-5", "usage": {"input_tokens": 0,
                                                                            "output_tokens": out}}}

    start_ms = int(T(2).timestamp() * 1000)
    main = [asst("m1", "2026-10-02T00:00:00Z", 100_000),
            {"type": "cost-state", "totalCostUSD": 3.5, "startTime": start_ms, "modelUsage": {}}]
    (pdir / "sess1.jsonl").write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in main))
    subdir = pdir / "sess1" / "subagents"
    subdir.mkdir(parents=True)
    (subdir / "agent-k1.jsonl").write_text(json.dumps(asst("s1", "2026-10-02T01:00:00Z", 50_000),
                                                      separators=(",", ":")) + "\n")
    (subdir / "agent-k1.meta.json").write_text(json.dumps({"agentType": "skeptic",
                                                           "description": "AUT-1 review"}))
    return store


def test_evaluate_end_to_end_and_cli_no_gh(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for var in tr._lib.CONFIG_DIR_ENV:
        monkeypatch.delenv(var, raising=False)
    repo = _repo_with_history(tmp_path)
    store = _write_store(tmp_path, repo)
    agentic = repo / ".agentic"
    agentic.mkdir()
    (agentic / "events.jsonl").write_text(json.dumps(skeptic_row(T(2, 1), "k1", iteration=1, signed_off=True))
                                          + "\n")
    (agentic / ".enforcement-fires.jsonl").write_text("")
    (agentic / "tasks.jsonl").write_text(json.dumps({"ticket_id": "AUT-1"}) + "\n")
    calls = []
    monkeypatch.setattr(ev, "_feedback_items", lambda r: [])
    monkeypatch.setattr(ev, "_gh_pr_states", lambda *a: calls.append(a))
    report = ev.evaluate([repo], START, END, base="main", use_gh=False, stores=[store], rates=RATES)
    assert calls == []
    assert report["cost"]["reconciled"] == {"status": "OK", "usd": 3.5, "sessions": 1, "session_ids": ["sess1"]}
    assert report["agents"]["skeptic"]["usd"]["value"] == 1.0
    assert report["work_items"]["coverage"]["value"]["1"] == 1
    assert report["work_items"]["items"]["value"][0]["pr_numbers"] == [10, 11]
    assert report["work_items"]["pr_outcome"]["value"]["merged_prs_in_window"] == 2
    assert report["meta"]["ticket_pattern"][str(repo)].startswith("(?<![A-Za-z0-9])(?:AUT)")
    monkeypatch.setattr(ev, "_gh_pr_states", lambda slug: None)
    report = ev.evaluate([repo], START, END, base="main", use_gh=True, stores=[store], rates=RATES)
    assert report["meta"]["gh"][str(repo)] == "unavailable: gh pr list failed"
    monkeypatch.setattr(ev, "_gh_pr_states", lambda *a: calls.append(a))

    monkeypatch.setattr(cli, "_EVAL", ev)
    rc = cli.main(["--repo", str(repo), "--since", "2026-10-01", "--until", "2026-10-08", "--no-gh",
                   "--store", str(store), "--json"])
    assert rc == 0 and calls == []
    out = json.loads(capsys.readouterr().out)
    assert out["meta"]["gh"][str(repo)] == "disabled (--no-gh)"
    assert [(e["path"], e["status"], e["sessions"]) for e in out["meta"]["stores"]] == [
        (os.path.realpath(store), "scanned", 1)]
    rc = cli.main(["--repo", str(repo), "--since", "7d", "--until", "2026-10-08", "--no-gh", "--store", str(store)])
    table = capsys.readouterr().out
    assert rc == 0
    for section in ("[cost]", "[agents]", "[skeptic_rounds]", "[work_items]", "[hooks]", "[mix]",
                    "[decisions]", "[gaps]"):
        assert section in table


def test_cli_store_replaces_defaults_and_reports_missing_as_absent(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    for var in tr._lib.CONFIG_DIR_ENV:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(ev, "_feedback_items", lambda r: [])
    monkeypatch.setattr(cli, "_EVAL", ev)
    repo = tmp_path / "repo"
    repo.mkdir()
    default_store = _write_store(home / ".claude" / "x", repo).rename(home / ".claude" / "projects")
    store = _write_store(tmp_path, repo)
    argv = ["--repo", str(repo), "--since", "2026-10-01", "--until", "2026-10-08", "--no-gh", "--json"]

    assert cli.main(argv) == 0
    meta = json.loads(capsys.readouterr().out)["meta"]
    assert [(e["path"], e["sessions"]) for e in meta["stores"]] == [(os.path.realpath(default_store), 1)]

    assert cli.main(argv + ["--store", str(store), str(tmp_path / "nope")]) == 0
    meta = json.loads(capsys.readouterr().out)["meta"]
    assert [(e["path"], e["status"], e["sessions"]) for e in meta["stores"]] == [
        (os.path.realpath(store), "scanned", 1), (str(tmp_path / "nope"), "missing", None)]
    assert meta["sessions"] == 1

    assert cli.main(argv[:-1] + ["--store", str(tmp_path / "nope")]) == 0
    table = capsys.readouterr().out
    assert "ABSENT (missing: does not exist)" in table


@pytest.mark.parametrize("argv", [["--since", "yesterday"], ["--since", "2026-10-09", "--until", "2026-10-08"],
                                  ["--ticket-pattern", "("]])
def test_cli_usage_errors_exit_2(tmp_path, argv):
    assert cli.main(["--repo", str(tmp_path), *argv]) == 2
    assert cli.main(["--repo", str(tmp_path / "missing")]) == 2


def test_session_summary_dominant_key_and_include_sessions(tmp_path, monkeypatch):
    s = session(tmp_path, "s1", cost=7.5)
    s.conductor[("claude-opus-5-5", "sdk-cli", "2.1.290")] = dict(s.conductor[("claude-opus-5-5", "cli", "2.1.287")],
                                                                   messages=3)
    row = ev.session_summary(s, "/r1")
    assert row == {"session_id": "s1", "repo": "/r1", "first_ts": T(2).isoformat(), "model": "claude-opus-5-5",
                   "entrypoint": "sdk-cli", "version": "2.1.290", "cost_usd": 7.5}
    bare = session(tmp_path, "s2", subs=[sub("a1")], cost=None)
    bare.conductor = tr.Usage()
    assert ev.session_summary(bare, "/r1")["entrypoint"] == "cli"
    bare.subagents = []
    empty = ev.session_summary(bare, "/r1")
    assert (empty["entrypoint"], empty["model"], empty["version"], empty["cost_usd"]) == (None, None, None, None)

    monkeypatch.setattr(ev, "_load_repo", lambda r, *a: inp([s], repo=str(r)))
    plain = ev.evaluate(["/r1"], START, END, use_gh=False, stores=[], rates=RATES)
    assert "session_rows" not in plain
    report = ev.evaluate(["/r1"], START, END, use_gh=False, stores=[], rates=RATES, include_sessions=True)
    assert report["session_rows"] == [row]


def test_gh_missing_from_path_degrades_instead_of_raising(tmp_path, monkeypatch):
    git = shutil.which("git")
    assert git
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "git").symlink_to(git)
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q"], ["remote", "add", "origin", "https://github.com/acme/w.git"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    monkeypatch.setattr(ev, "_feedback_items", lambda repo: None)
    monkeypatch.setenv("PATH", str(bindir))
    report = ev.evaluate([str(repo)], START, END, base="main", use_gh=True, stores=[], rates=RATES)
    assert report["meta"]["gh"] == {str(repo): "unavailable: gh pr list failed"}
    assert report["meta"]["repo_slug"] == {str(repo): "acme/w"}
