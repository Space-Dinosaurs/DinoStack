"""Unit tests for evals.auto.overfitting - verdict parser + fixture-ID detection."""
from __future__ import annotations

from evals.auto.overfitting import parse_verdict


def test_pass_verdict_clean_rationale():
    r = parse_verdict("Overfitting Rule verdict: yes because it clarifies the signoff format globally")
    assert r["verdict"] == "pass"
    assert r["fixture_ids"] == []


def test_fail_verdict_explicit():
    r = parse_verdict("Overfitting Rule verdict: no because it only helps one fixture pattern")
    assert r["verdict"] == "fail"


def test_missing_verdict_line_is_fail():
    r = parse_verdict("I propose a diff.\n```diff\n```\n")
    assert r["verdict"] == "fail"
    assert r["reason"] == "verdict_line_missing"


def test_fixture_id_in_rationale_overrides_pass():
    r = parse_verdict("Overfitting Rule verdict: yes because this would also improve sk-003 scores")
    assert r["verdict"] == "fail"
    assert "sk-003" in r["reason"]
    assert "sk-003" in r["fixture_ids"]


def test_fixture_id_in_diff_overrides_pass():
    diff = "--- a/content/agents/skeptic.md\n+++ b/content/agents/skeptic.md\n@@ -1 +1 @@\n-x\n+y (cf. ip-004)\n"
    r = parse_verdict("Overfitting Rule verdict: yes because improves general clarity", diff=diff)
    assert r["verdict"] == "fail"
    assert "ip-004" in r["fixture_ids"]


def test_pass_accepts_synonyms():
    assert parse_verdict("Overfitting Rule verdict: pass because ...")["verdict"] == "pass"
    assert parse_verdict("Overfitting Rule verdict: fail because ...")["verdict"] == "fail"


def test_all_component_prefixes_detected():
    for fid in ("sk-001", "ip-002", "wr-003", "co-004", "SK-005"):
        r = parse_verdict(f"Overfitting Rule verdict: yes because improves {fid}")
        assert r["verdict"] == "fail", fid
