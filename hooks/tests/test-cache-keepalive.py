# Run with: python3 hooks/tests/test-cache-keepalive.py
"""
Tests for hooks/cache-keepalive.py and hooks/lib/cache_keepalive.py.

Library cases load the module from a hooks tree; hook cases run the hook
as a subprocess with HOME pointed at a scratch dir, the way the Claude Code
hook runner does. After every case passes against the real tree, each named
mutation is applied to a copy of the tree and the case it targets is re-run
against the copy; the suite fails if a mutation does not redden its case.
"""

import datetime
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REAL_HOOKS = os.path.dirname(HERE)
REPO = os.path.dirname(REAL_HOOKS)
FIXTURE = os.path.join(HERE, "fixtures", "cache-keepalive-ping-record.json")
SCRATCH = tempfile.mkdtemp(prefix="cka-test-")
NOW = time.time()


def load(hooks_dir, name="cache_keepalive"):
    spec = importlib.util.spec_from_file_location(name + str(id(hooks_dir)) + str(time.time()),
                                                  os.path.join(hooks_dir, "lib", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ---------------------------------------------------------------------------
# Transcript builders
# ---------------------------------------------------------------------------

_n = [0]


def _id():
    _n[0] += 1
    return "msg_%06d" % _n[0]


def user(t, text="hi", origin="human"):
    return {"type": "user", "timestamp": iso(t), "turnOrigin": origin, "message": {"role": "user", "content": text}}


def ping(t, ck):
    return {"type": "user", "timestamp": iso(t), "isMeta": True, "turnOrigin": "scheduled",
            "message": {"role": "user", "content": ck.LG.PING_PROMPT}}


def blocked_fire(t, ck):
    """What a BLOCK_OUTPUT fire writes (measured, t2 evidence)."""
    return [ping(t, ck), {"type": "user", "timestamp": iso(t), "isMeta": True,
                          "message": {"role": "user", "content": "Operation stopped by hook"}}]


def asst(t, S=100000, c1h=500, c5m=0, content=None, model="claude-opus-5-5"):
    return {"type": "assistant", "timestamp": iso(t), "message": {
        "id": _id(), "model": model, "role": "assistant", "content": content or [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 10, "cache_read_input_tokens": S - 10 - c1h - c5m,
                  "cache_creation_input_tokens": c1h + c5m,
                  "cache_creation": {"ephemeral_1h_input_tokens": c1h, "ephemeral_5m_input_tokens": c5m},
                  "output_tokens": 50}}}


def rate_limit(t):
    return {"type": "assistant", "timestamp": iso(t), "error": "rate_limit", "isApiErrorMessage": True,
            "message": {"id": _id(), "model": "<synthetic>", "role": "assistant", "content": [], "usage": {}}}


def tool_use(t, name, inp, tid):
    return {"type": "assistant", "timestamp": iso(t), "message": {
        "id": _id(), "model": "claude-opus-5-5", "role": "assistant",
        "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}],
        "usage": {"input_tokens": 10, "cache_read_input_tokens": 100000, "cache_creation_input_tokens": 100,
                  "cache_creation": {"ephemeral_1h_input_tokens": 100, "ephemeral_5m_input_tokens": 0},
                  "output_tokens": 20}}}


def tool_result(t, tid, text):
    return {"type": "user", "timestamp": iso(t), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text}]}}


def create(t, ck, job="aaaa1111"):
    tid = "toolu_c_" + job
    return [tool_use(t, "CronCreate", {"cron": ck.CRON_EXPR, "recurring": True, "durable": False,
                                       "prompt": ck.LG.PING_PROMPT}, tid),
            tool_result(t, tid, "Scheduled recurring job %s (%s). Session-only." % (job, ck.CRON_EXPR))]


def delete(t, job="aaaa1111"):
    tid = "toolu_d_" + job
    return [tool_use(t, "CronDelete", {"id": job}, tid), tool_result(t, tid, "Cancelled job %s." % job)]


def session_start(t):
    return {"type": "attachment", "timestamp": iso(t), "attachment": {"type": "hook_success", "hookEvent": "SessionStart"}}


def injection(t, ck):
    return {"type": "attachment", "timestamp": iso(t), "attachment": {
        "type": "hook_additional_context", "hookEvent": "UserPromptSubmit", "content": [ck.create_note(False)]}}


def warm_idle(ck, idle_s, last_s=None):
    """A real request idle_s ago; optional later ping request last_s ago."""
    recs = [user(NOW - idle_s), asst(NOW - idle_s + 1)]
    if last_s is not None:
        recs += [ping(NOW - last_s, ck), asst(NOW - last_s + 1)]
    return recs


def write_transcript(records, conductor=True, name=None):
    d = tempfile.mkdtemp(dir=SCRATCH)
    path = os.path.join(d, (name or "sess") + ".jsonl")
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    if conductor:
        os.makedirs(os.path.join(d, (name or "sess"), "subagents"))
    return path


# ---------------------------------------------------------------------------
# Library cases (each takes a hooks dir)
# ---------------------------------------------------------------------------

def t_constants(h):
    ck = load(h)
    assert ck.PERIOD_S == 1200 and ck.COLD_AFTER_S == 3480 and ck.RELEASE_AFTER_S == 7200
    assert ck.EFFECTIVE_INTERVAL_S == (ck.COLD_AFTER_S // ck.PERIOD_S) * ck.PERIOD_S == 2400
    assert ck.ACTIVE_WINDOW_S == ck.COLD_AFTER_S - ck.PERIOD_S == 2280
    assert ck.CRON_EXPR == "7,27,47 * * * *"
    assert ck.max_pings(50000) == 12
    assert ck.BLOCK_OUTPUT == {"continue": False, "suppressOutput": True, "stopReason": ""}


def t_decide_actions(h):
    ck = load(h)
    warm = {"ttl": "1h", "prefix_tokens": 100000, "last_request_start": NOW - ck.ACTIVE_WINDOW_S - 60,
            "idle_since": NOW - 3000, "pings_since_idle": 0, "ping_rate_limited": False}
    cold = dict(warm, last_request_start=NOW - ck.COLD_AFTER_S)
    d = lambda s, **kw: ck.decide(s, NOW, **dict({"enabled": True, "conductor": True,
                                                  "in_flight": lambda: False, "wrap_ok": True}, **kw))
    for state, kw, reason in ((warm, {"enabled": False}, "disabled"),
                              (dict(warm, ttl="5m"), {}, "ttl-not-1h"),
                              (dict(warm, ttl=None), {}, "ttl-not-1h"),
                              (dict(warm, prefix_tokens=ck.MIN_PREFIX_TOKENS - 1), {}, "small-prefix"),
                              (warm, {"conductor": False}, "not-conductor")):
        assert d(state, **kw) == ("delete", reason), (reason, d(state, **kw))
        cold_state = dict(state, last_request_start=cold["last_request_start"])
        assert d(cold_state, **kw) == ("block", reason), reason
    assert d(dict(warm, ping_rate_limited=True)) == ("block", "rate-limited")
    assert d(cold) == ("block", "cache-presumed-cold")
    assert d(dict(warm, last_request_start=NOW - ck.ACTIVE_WINDOW_S + 1)) == ("block", "recently-active")
    assert d(warm) == ("ping", "pass")
    assert d(dict(warm, last_request_start=NOW - ck.ACTIVE_WINDOW_S)) == ("ping", "pass")
    assert d(dict(warm, last_request_start=None)) == ("block", "cache-presumed-cold")


def t_release_wrap(h):
    ck = load(h)
    base = {"ttl": "1h", "prefix_tokens": 100000, "last_request_start": NOW - 600,
            "pings_since_idle": 2, "ping_rate_limited": False}
    d = lambda s, fl, ok=True: ck.decide(s, NOW, True, True, lambda: fl, ok)
    at = dict(base, idle_since=NOW - ck.RELEASE_AFTER_S)
    before = dict(base, idle_since=NOW - ck.RELEASE_AFTER_S + 1)
    assert d(at, False) == ("wrap", "release-wrap")
    assert d(before, False) == ("block", "recently-active")
    assert d(at, True) == ("block", "recently-active")
    assert d(dict(at, last_request_start=NOW - ck.ACTIVE_WINDOW_S), True) == ("ping", "pass")
    assert d(at, False, ok=False) == ("delete", "release-wrap-unavailable")
    capped = dict(at, pings_since_idle=ck.max_pings(100000))
    assert d(capped, True) == ("delete", "cost-capped")
    assert d(dict(capped, pings_since_idle=ck.max_pings(100000) - 1, last_request_start=NOW - ck.ACTIVE_WINDOW_S),
             True) == ("ping", "pass")


def t_session_state(h):
    ck = load(h)
    recs = [user(NOW - 9000), asst(NOW - 8999), ping(NOW - 6000, ck), asst(NOW - 5999), ping(NOW - 3600, ck),
            asst(NOW - 3599)]
    st = ck.session_state(recs)
    assert st["idle_since"] == ck._ts(iso(NOW - 9000)), st
    assert st["last_request_start"] == ck._ts(iso(NOW - 3600))
    assert st["pings_since_idle"] == 2 and st["ttl"] == "1h" and st["prefix_tokens"] == 100000
    note = recs + [user(NOW - 100, "<task-notification><task-id>x</task-id></task-notification>", "task_notification"),
                   asst(NOW - 99)]
    st2 = ck.session_state(note)
    assert st2["idle_since"] == ck._ts(iso(NOW - 100)) and st2["pings_since_idle"] == 0
    assert ck.session_state([user(NOW - 10)])["ttl"] is None
    assert ck.session_state([user(NOW - 10), asst(NOW - 9, c1h=0, c5m=400)])["ttl"] == "5m"


def t_blocked_fire_records(h):
    ck = load(h)
    lg = ck.LG
    recs = [user(NOW - 3000), asst(NOW - 2999)]
    after = recs + blocked_fire(NOW - 1000, ck) + blocked_fire(NOW - 10, ck)
    assert ck.session_state(after) == ck.session_state(recs)
    assert [lg.genuine_user_text(r) for r in after[2:]] == [None, None, None, None]
    with open(FIXTURE) as f:
        fixture = json.load(f)
    assert lg.is_ping_record(fixture)


def t_rate_limit(h):
    ck = load(h)
    recs = [user(NOW - 9000), asst(NOW - 8999), ping(NOW - 5000, ck), rate_limit(NOW - 4999)]
    assert ck.session_state(recs)["ping_rate_limited"] is True
    assert ck.session_state(recs + [user(NOW - 100), asst(NOW - 99)])["ping_rate_limited"] is False
    real_rl = [user(NOW - 9000), asst(NOW - 8999), user(NOW - 5000), rate_limit(NOW - 4999)]
    assert ck.session_state(real_rl)["ping_rate_limited"] is False


def t_is_ping_record(h):
    lg = load(h, "loop_guard")
    good = {"type": "user", "isMeta": True, "turnOrigin": "scheduled", "message": {"content": lg.PING_PROMPT}}
    assert lg.is_ping_record(good)
    assert lg.is_ping_record(dict(good, message={"content": [{"type": "text", "text": lg.PING_PROMPT}]}))
    assert not lg.is_ping_record(dict(good, isMeta=False))
    assert not lg.is_ping_record(dict(good, turnOrigin="human"))
    assert not lg.is_ping_record(dict(good, message={"content": lg.PING_PROMPT + " "}))
    assert not lg.is_ping_record(dict(good, message={"content": lg.MARKER}))


def t_cron_status(h):
    ck = load(h)
    t = NOW - 5000
    live = [user(t)] + create(t + 1, ck)
    assert ck.cron_status(live) == "unknown"
    assert ck.cron_status([session_start(t - 1)] + live) == "live"
    assert ck.cron_status(live, started_at=t - 100, complete=True) == "live"
    assert ck.cron_status([session_start(t - 1)] + live + delete(t + 50)) == "absent"
    assert ck.cron_status([session_start(t - 1)] + live + delete(t + 50, job="bbbb2222")) == "live"
    assert ck.cron_status(live + [session_start(t + 60)]) == "absent"
    assert ck.cron_status(live + [user(t + 100)], started_at=t + 90) == "absent"
    assert ck.cron_status([session_start(t), user(t + 1)]) == "absent"
    assert ck.cron_status([user(t + 1)], started_at=t, complete=True) == "absent"
    assert ck.cron_status([user(t + 1)], started_at=t, complete=False) == "unknown"


def t_creation_due(h):
    ck = load(h)
    t = NOW - 5000
    base = [session_start(t), user(t + 1), asst(t + 2)]
    st = ck.session_state(base)
    assert ck.creation_due(base, st, True, True) == (True, False)
    assert ck.creation_due(base, st, True, False) == (False, False)
    assert ck.creation_due(base, st, False, True) == (False, False)
    small = [session_start(t), user(t + 1), asst(t + 2, S=1000)]
    assert ck.creation_due(small, ck.session_state(small), True, True) == (False, False)
    declined = base + [injection(t + 3, ck), user(t + 3), asst(t + 4)]
    assert ck.creation_due(declined, st, True, True) == (False, False)
    accepted = base + [injection(t + 3, ck), user(t + 3)] + create(t + 4, ck)
    assert ck.creation_due(accepted, st, True, True) == (False, False)
    deleted = accepted + delete(t + 60)
    assert ck.creation_due(deleted, st, True, True) == (True, False)
    no_anchor = [user(t + 1), asst(t + 2)]
    assert ck.creation_due(no_anchor, ck.session_state(no_anchor), True, True) == (True, True)


def _launch(t, aid):
    return tool_result(t, "toolu_" + aid, "Async agent launched successfully.\nagentId: %s (internal ID)" % aid)


def _note(t, aid, status):
    return user(t, "<task-notification>\n<task-id>%s</task-id>\n<status>%s</status>\n</task-notification>"
                % (aid, status), "task_notification")


def t_in_flight(h):
    ck = load(h)
    t = NOW - 1000
    f = lambda recs: ck.in_flight(write_transcript(recs, conductor=False))
    assert f([_launch(t, "a1")]) is True
    assert f([_launch(t, "a1"), _note(t + 5, "a1", "completed")]) is False
    for st in ("failed", "killed", "stopped"):
        assert f([_launch(t, "a1"), _note(t + 5, "a1", st)]) is False, st
    resumed = [_launch(t, "a1"), _note(t + 5, "a1", "completed"),
               tool_use(t + 6, "SendMessage", {"to": "a1", "message": "again"}, "toolu_sm")]
    assert f(resumed) is True
    assert f(resumed + [_note(t + 9, "a1", "completed")]) is False
    assert f([_launch(t, "a1"), _note(t + 5, "a1", "(s)")]) is True
    assert f([tool_use(t, "SendMessage", {"to": "peer", "message": "x"}, "toolu_x")]) is False
    assert f([tool_result(t, "toolu_b", "Command running in background with ID: bhq1chvyo. Output is being written to: /tmp/x")]) is True
    assert f([_note(t, "unknown", "running")]) is False
    assert ck.in_flight(os.path.join(SCRATCH, "missing.jsonl")) is True
    bad = write_transcript([_launch(t, "a1")], conductor=False)
    with open(bad, "a") as fh:
        fh.write("{not json launched successfully\n")
    assert ck.in_flight(bad) is True


def t_is_conductor(h):
    ck = load(h)
    assert ck.is_conductor(write_transcript([user(NOW)], conductor=True)) is True
    assert ck.is_conductor(write_transcript([user(NOW)], conductor=False)) is False
    assert ck.is_conductor("") is False


def t_kickoff(h):
    ck = load(h)
    cmd = ck.kickoff_command("SID-1")
    argv = shlex.split(cmd)
    assert argv == ["claude", ck.KICKOFF_PROMPT.format(sid="SID-1")], argv
    assert "SID-1" in argv[1] and ".agentic/resume/SID-1.md" in argv[1]
    quoted = shlex.split(ck.kickoff_command("it's-SID"))
    assert quoted == ["claude", ck.KICKOFF_PROMPT.format(sid="it's-SID")], quoted
    note = ck.wrap_note("/repo", "SID-1", "/proj")
    assert note.startswith(ck.WRAP_MARKER) and ck.LG.GATE_NOTE in note
    assert "/proj/.agentic/resume/SID-1.md" in note and "/repo/content/commands/ds-wrap-deferred.md" in note
    assert "Project root: /proj " in note and "write only under /proj/.agentic/" in note and "/repo/bin/" in note
    assert note.count(cmd) == 1 and note.endswith("KICKOFF: " + cmd)
    assert "Session wrapped (idle 2h). Run /exit, then resume with: <KICKOFF>" in note


def t_rates_parity(h):
    ck = load(h)
    spec = importlib.util.spec_from_file_location("telemetry", os.path.join(REPO, "bin", "_telemetry.py"))
    tel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tel)
    rates = tel.DEFAULT_RATES.values()
    assert ck.DERIVATION_RATES["write_1h"] == tel._CACHE_1H_MULTIPLIER
    assert ck.DERIVATION_RATES["read_max"] == max(r["cache_read"] / r["input"] for r in rates)
    assert ck.DERIVATION_RATES["output"] == max(r["output"] / r["input"] for r in rates)


def t_skill_regex(h):
    lg = load(h, "loop_guard")
    home = tempfile.mkdtemp(dir=SCRATCH)
    os.makedirs(os.path.join(home, ".claude"))
    with open(os.path.join(home, ".claude", "agentic-engineering.json"), "w") as f:
        json.dump({"skill_auto_load": True}, f)
    script = os.path.join(h, "skill-auto-load-check.sh")
    run = lambda p: subprocess.run(["bash", script], input=json.dumps({"prompt": p}), capture_output=True,
                                   text=True, env=dict(os.environ, HOME=home, AE_ADAPTER="claude")).stdout
    assert "SKILL CHECK" in run("please fix the hook")
    assert run(lg.PING_PROMPT) == ""


# ---------------------------------------------------------------------------
# Hook (subprocess) cases
# ---------------------------------------------------------------------------

def _home(wrap_file=True, global_cfg=None):
    home = tempfile.mkdtemp(dir=SCRATCH)
    repo = os.path.join(home, "dinostack")
    os.makedirs(os.path.join(repo, "content", "commands"))
    if wrap_file:
        open(os.path.join(repo, "content", "commands", "ds-wrap-deferred.md"), "w").write("x")
    os.makedirs(os.path.join(home, ".agentic"))
    json.dump({"repo_dir": repo}, open(os.path.join(home, ".agentic", "agentic-engineering-config.json"), "w"))
    if global_cfg is not None:
        os.makedirs(os.path.join(home, ".claude"))
        json.dump(global_cfg, open(os.path.join(home, ".claude", "agentic-engineering.json"), "w"))
    return home, repo


def run_hook(h, prompt, transcript, home, env=None, cwd=None, extra=None):
    payload = {"hook_event_name": "UserPromptSubmit", "prompt": prompt, "transcript_path": transcript,
               "cwd": cwd or SCRATCH, "session_id": "11111111-2222-3333-4444-555555555555"}
    payload.update(extra or {})
    e = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "AE_CACHE"))}
    e.update({"HOME": home, "PATH": os.environ.get("PATH", "")})
    e.update(env or {})
    r = subprocess.run([sys.executable, os.path.join(h, "cache-keepalive.py")], input=json.dumps(payload),
                       capture_output=True, text=True, env=e, timeout=20)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def _ctx(out):
    return (out or {}).get("hookSpecificOutput", {}).get("additionalContext")


def t_hook_ping_actions(h):
    ck = load(h)
    home, repo = _home()
    ping_ok = write_transcript(warm_idle(ck, 3000))
    assert _ctx(run_hook(h, ck.LG.PING_PROMPT, ping_ok, home)) == ck.LG.GATE_NOTE
    recent = write_transcript(warm_idle(ck, 600))
    assert run_hook(h, ck.LG.PING_PROMPT, recent, home) == ck.BLOCK_OUTPUT
    not_cond = write_transcript(warm_idle(ck, 3000), conductor=False)
    assert run_hook(h, ck.LG.PING_PROMPT, not_cond, home) is None
    wrap = write_transcript(warm_idle(ck, ck.RELEASE_AFTER_S + 100, last_s=1200))
    proj = tempfile.mkdtemp(dir=SCRATCH)
    note = _ctx(run_hook(h, ck.LG.PING_PROMPT, wrap, home, cwd=proj))
    assert note and note.startswith(ck.WRAP_MARKER) and repo in note, note
    assert "Project root: " + os.path.realpath(proj) + " " in note, note
    home2, _ = _home(wrap_file=False)
    assert run_hook(h, ck.LG.PING_PROMPT, wrap, home2) is None
    assert run_hook(h, ck.LG.MARKER + " other", ping_ok, home) == ck.BLOCK_OUTPUT
    assert run_hook(h, "text with " + ck.LG.MARKER + " inside", ping_ok, home) is None
    assert run_hook(h, ck.LG.PING_PROMPT, os.path.join(SCRATCH, "missing.jsonl"), home) == ck.BLOCK_OUTPUT


def t_hook_disabled(h):
    ck = load(h)
    path = write_transcript(warm_idle(ck, 3000))
    home, _ = _home()
    assert run_hook(h, ck.LG.PING_PROMPT, path, home, env={"AE_CACHE_KEEPALIVE_DISABLE": "1"}) is None
    home_g, _ = _home(global_cfg={"cache_keepalive": False})
    assert run_hook(h, ck.LG.PING_PROMPT, path, home_g) is None
    proj = tempfile.mkdtemp(dir=SCRATCH)
    os.makedirs(os.path.join(proj, ".agentic"))
    json.dump({"cache_keepalive": False}, open(os.path.join(proj, ".agentic", "config.json"), "w"))
    assert run_hook(h, ck.LG.PING_PROMPT, path, home, cwd=proj) is None
    json.dump({"cache_keepalive": True}, open(os.path.join(proj, ".agentic", "config.json"), "w"))
    assert _ctx(run_hook(h, ck.LG.PING_PROMPT, path, home_g, cwd=proj)) == ck.LG.GATE_NOTE
    att = {"CLAUDE_CODE_SESSION_ATTENDED": "1"}
    fresh = write_transcript([session_start(NOW - 100), user(NOW - 90), asst(NOW - 89)])
    assert run_hook(h, "next", fresh, home, env=dict(att, AE_CACHE_KEEPALIVE_DISABLE="1")) is None


def t_hook_create(h):
    ck = load(h)
    home, _ = _home()
    att = {"CLAUDE_CODE_SESSION_ATTENDED": "1"}
    fresh = write_transcript([session_start(NOW - 100), user(NOW - 90), asst(NOW - 89)])
    note = _ctx(run_hook(h, "please continue", fresh, home, env=att))
    assert note == ck.create_note(False), note
    assert ck.CRON_EXPR in note and json.dumps(ck.LG.PING_PROMPT) in note and "CronList and stop" not in note
    assert "every 20 minutes" in note and ck.CONFIG_KEY in note and ck.KILL_SWITCH_ENV in note
    assert run_hook(h, "please continue", fresh, home) is None
    assert run_hook(h, "please continue", fresh, home, env={"CLAUDE_CODE_SESSION_ATTENDED": "0"}) is None
    assert run_hook(h, "please continue", fresh, home, env=att, extra={"agent_id": "a1"}) is None
    not_cond = write_transcript([session_start(NOW - 100), user(NOW - 90), asst(NOW - 89)], conductor=False)
    assert run_hook(h, "please continue", not_cond, home, env=att) is None
    live = write_transcript([session_start(NOW - 100), user(NOW - 90)] + create(NOW - 89, ck))
    assert run_hook(h, "please continue", live, home, env=att) is None
    unknown = write_transcript([user(NOW - 90), asst(NOW - 89)])
    assert _ctx(run_hook(h, "please continue", unknown, home, env=att)) == ck.create_note(True)


CASES = [t_constants, t_decide_actions, t_release_wrap, t_session_state, t_blocked_fire_records, t_rate_limit,
         t_is_ping_record, t_cron_status, t_creation_due, t_in_flight, t_is_conductor, t_kickoff, t_rates_parity,
         t_skill_regex, t_hook_ping_actions, t_hook_disabled, t_hook_create]

# (name, file under hooks/, old, new, case it must redden)
MUTATIONS = [
    ("gate-note-on-delete", "cache-keepalive.py", 'elif action == "block":',
     'elif action == "delete":\n        _context(lib.LG.GATE_NOTE)\n    elif action == "block":', t_hook_ping_actions),
    ("kickoff-unquoted", "lib/cache_keepalive.py", 'return "claude " + shlex.quote(KICKOFF_PROMPT.format(sid=session_id))',
     'return "claude " + KICKOFF_PROMPT.format(sid=session_id)', t_kickoff),
    ("note-without-root", "lib/cache_keepalive.py", '". Project root: " + root + " - run every "',
     '". Run every "', t_kickoff),
    ("idle-since-counts-pings", "lib/cache_keepalive.py", 'real = [r for r in requests if not r["ping"]]',
     "real = list(requests)", t_session_state),
    ("in-flight-ignores-resume", "lib/cache_keepalive.py", "if to in launched:", "if False:", t_in_flight),
    ("in-flight-fails-open", "lib/cache_keepalive.py", "    except Exception:\n        return True",
     "    except Exception:\n        return False", t_in_flight),
    ("wrap-before-cold", "lib/cache_keepalive.py", "    if not warm:\n        return (\"block\", \"cache-presumed-cold\")\n",
     "", t_decide_actions),
    ("ineligible-cold-deletes", "lib/cache_keepalive.py", 'return ("delete" if warm else "block", reason)',
     'return ("delete", reason)', t_decide_actions),
    ("block-uses-decision", "lib/cache_keepalive.py",
     'BLOCK_OUTPUT = {"continue": False, "suppressOutput": True, "stopReason": ""}',
     'BLOCK_OUTPUT = {"decision": "block", "reason": "x"}', t_constants),
    ("no-attended-check", "cache-keepalive.py", 'if env.get("CLAUDE_CODE_SESSION_ATTENDED") != "1" or payload.get("agent_id"):',
     'if payload.get("agent_id"):', t_hook_create),
    ("declined-injection-repeats", "lib/cache_keepalive.py", "            return (False, False)\n    return (True, status",
     "            pass\n    return (True, status", t_creation_due),
    ("no-cost-cap", "lib/cache_keepalive.py", 'return ("delete", "cost-capped")', 'pass', t_release_wrap),
    ("ping-prompt-says-hook", "lib/loop_guard.py", "If a DinoStack note in THIS turn", "If a hook note in THIS turn",
     t_skill_regex),
]


def main():
    failures = 0
    for case in CASES:
        try:
            case(REAL_HOOKS)
            print("PASS", case.__name__)
        except AssertionError as exc:
            failures += 1
            print("FAIL", case.__name__, exc)
    for name, rel, old, new, case in MUTATIONS:
        copy = os.path.join(tempfile.mkdtemp(dir=SCRATCH), "hooks")
        shutil.copytree(REAL_HOOKS, copy, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        target = os.path.join(copy, rel)
        src = open(target).read()
        if old not in src:
            failures += 1
            print("FAIL mutation %s: anchor not found" % name)
            continue
        open(target, "w").write(src.replace(old, new, 1))
        try:
            case(copy)
            failures += 1
            print("FAIL mutation %s survived %s" % (name, case.__name__))
        except Exception:
            print("PASS mutation %s reddens %s" % (name, case.__name__))
    shutil.rmtree(SCRATCH, ignore_errors=True)
    print("%d failure(s)" % failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
