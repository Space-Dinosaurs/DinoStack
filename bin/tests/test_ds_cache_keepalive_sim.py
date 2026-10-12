"""Tests for bin/ds-cache-keepalive-sim against synthetic stores whose
expected values are computed by hand in the comments below."""

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "ds-cache-keepalive-sim"
NOW = 2_000_000_000.0


def req(send, S=100000, ss=False, c1h=500, c5m=0):
    return {"send": send, "end": send + 5, "S": S, "c1h": c1h, "c5m": c5m, "ss": ss, "sched": False,
            "cc": 500, "out": 50, "cond": False}


def run(tmp_path, data, *args):
    p = tmp_path / "data.json"
    p.write_text(json.dumps(data))
    r = subprocess.run([sys.executable, str(TOOL), "--data", str(p), "--json", *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def store(*sessions):
    return {"now": NOW, "pings": [], "sessions": list(sessions)}


# One conductor return: gap g=5000 s at S=100000, P=1200, release 2h, cost cap on,
# cc=854 out=193 read=0.1 write=2 oratio=5, del-req 1, recreate-req 2, block-tok 80.
# c = 0.1*100000 + 2*854 + 5*193 = 12673. Base (g >= TTL) = 2*S = 200000.
# Phases t0 = 30 + 60k. A fire pings when L in [2280, 3480).
#   k=0..2  (t0<200):  blocked t0, t0+1200; ping t0+2400; blocked t0+3600; ping t0+4800,
#                      which is final (t+2400 >= 7200) -> self-delete.
#                      cost = 2c + c + 3*160 + R*S + 2*R*S = 68499 -> v = 131501
#   k=3..17:           blocked, blocked, ping t0+2400, blocked; return warm.
#                      cost = c + 480 + R*S = 23153 -> v = 176847
#   k=18,19:           blocked, ping t0+1200, blocked, ping t0+3600; return warm.
#                      cost = 2c + 320 + R*S = 35666 -> v = 164334
# mean = (3*131501 + 15*176847 + 2*164334) / 20 = 168793.8; minus one creation 2*R*S
# = 20000 -> keepalive_net = 148793.8. Not terminal (ended < 24h before now) -> abandon 0.
HAND_NET = 148793.8


def conductor_return():
    t = NOW - 20000
    return {"f": "a", "sub": True, "req": [req(t), req(t + 5000)]}


def test_hand_computed_keepalive_net(tmp_path):
    out = run(tmp_path, store(conductor_return()), "--periods", "1200", "--release-h", "2", "--wrap-req", "0")
    rel = out["periods"][0]["releases"][0]
    assert out["returns"] == 1 and out["terminal"] == 0 and out["sessions"] == 1
    assert rel["keepalive_net"] == pytest.approx(HAND_NET)
    assert rel["abandon"] == 0 and rel["ev"]["1.0"] == pytest.approx(HAND_NET)
    assert out["periods"][0]["verdict"] == "keep RELEASE_AFTER_S=7200"


def test_class_filter(tmp_path):
    other = dict(conductor_return(), sub=False)
    assert run(tmp_path, store(other), "--wrap-req", "0")["returns"] == 0
    assert run(tmp_path, store(other), "--class", "other", "--wrap-req", "0")["returns"] == 1
    tool = dict(conductor_return(), sub=False)
    tool["req"] = [dict(r, cond=True) for r in tool["req"]]
    assert run(tmp_path, store(tool), "--rule", "agenttool", "--wrap-req", "0")["returns"] == 1


def test_restart_and_5m_excluded(tmp_path):
    t = NOW - 20000
    # r1->r2 crosses a restart (excluded); r2->r3 counts; r3 is 5m-TTL, so r3->r4 is excluded.
    s = {"f": "a", "sub": True, "req": [req(t), req(t + 5000, ss=True), req(t + 9000, c1h=0, c5m=400),
                                        req(t + 15000)]}
    assert run(tmp_path, store(s), "--wrap-req", "0")["returns"] == 1
    s["req"][2] = req(t + 9000)
    assert run(tmp_path, store(s), "--wrap-req", "0")["returns"] == 2


def test_wrap_terms(tmp_path):
    # Gap 10000 >= release 7200 + effective interval 2400 -> one wrap episode.
    # wrap cost = 4*0.1*100000 + 2*20000 + 5*3000 = 95000; fresh saving = 2*(100000-60000) = 80000.
    t = NOW - 20000
    s = {"f": "a", "sub": True, "req": [req(t), req(t + 10000)]}
    rel = run(tmp_path, store(s))["periods"][0]["releases"][0]
    assert rel["returns_past_release"] == 1
    assert rel["wrap_returns"] == pytest.approx(95000) and rel["fresh_saving"] == pytest.approx(80000)
    resume = run(tmp_path, store(s), "--resume-mode", "resume")["periods"][0]["releases"][0]
    assert resume["fresh_saving"] == 0
    assert rel["ev"]["0.0"] - resume["ev"]["0.0"] == pytest.approx(80000)


def test_terminal_session_slope(tmp_path):
    # Ended more than 24h before now -> terminal; wrap at 4 requests costs 95000 per open terminal.
    t = NOW - 200000
    s = {"f": "a", "sub": True, "req": [req(t)]}
    rel = run(tmp_path, store(s))["periods"][0]["releases"][0]
    assert rel["wrap_terminals"] == pytest.approx(95000)
    assert rel["ev"]["1.0"] == pytest.approx(rel["ev"]["0.0"] - rel["abandon"] - 95000)


def test_line_arithmetic(tmp_path):
    per = {p["period_s"]: p for p in run(tmp_path, store(conductor_return()), "--periods", "720", "1200",
                                         "--wrap-req", "0")["periods"]}
    assert per[1200]["effective_interval_s"] == 2400
    assert per[1200]["lines_per_h_active"] == pytest.approx(6.0) and per[1200]["lines_per_h_idle"] == pytest.approx(7.5)
    assert per[720]["effective_interval_s"] == 2880
    assert per[720]["lines_per_h_active"] == pytest.approx(10.0) and per[720]["lines_per_h_idle"] == pytest.approx(11.25)


def test_opt_out_verdict(tmp_path):
    t = NOW - 200000
    s = {"f": "a", "sub": True, "req": [req(t)]}
    out = run(tmp_path, store(s), "--wrap-req", "0")
    assert out["periods"][0]["verdict"] == "opt-out (EV_worst<=0)"


def _iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def test_extract_from_store(tmp_path):
    import time
    now = time.time()
    home = tmp_path / "home"
    proj = home / ".claude-x" / "projects" / "p"
    proj.mkdir(parents=True)
    (proj / "s1" / "subagents").mkdir(parents=True)
    usage = {"input_tokens": 10, "cache_read_input_tokens": 99000, "cache_creation_input_tokens": 990,
             "cache_creation": {"ephemeral_1h_input_tokens": 990, "ephemeral_5m_input_tokens": 0}, "output_tokens": 5}
    recs = []
    for i, t in enumerate((now - 30000, now - 25000, now - 15000)):
        if i == 2:
            recs.append({"type": "attachment", "timestamp": _iso(t - 1), "attachment": {"hookEvent": "SessionStart"}})
        recs.append({"type": "user", "timestamp": _iso(t), "message": {"content": "go"}})
        recs.append({"type": "assistant", "timestamp": _iso(t + 3),
                     "message": {"id": "m%d" % i, "model": "claude-opus-5-5", "usage": usage, "content": []}})
    (proj / "s1.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
    env["HOME"] = str(home)
    r = subprocess.run([sys.executable, str(TOOL), "--json", "--wrap-req", "0"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["sessions"] == 1 and out["returns"] == 1
