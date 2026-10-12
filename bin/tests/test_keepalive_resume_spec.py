"""Pins the single canonical spec site of the cache-keepalive in-session wrap
(content/commands/ds-wrap-deferred.md, In-session mode) against the
constants in hooks/lib/cache_keepalive.py, and the operator fallback prompt
across the command doc, the docs page and the library."""

import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CMD = REPO / "content" / "commands" / "ds-wrap-deferred.md"
DOC = REPO / "docs" / "configuration-reference.md"


def _ck():
    spec = importlib.util.spec_from_file_location("cache_keepalive", REPO / "hooks" / "lib" / "cache_keepalive.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _section():
    text = CMD.read_text()
    m = re.search(r"^## In-session mode\n(.*?)(?=^## )", text, re.S | re.M)
    assert m, "ds-wrap-deferred.md has no '## In-session mode' section"
    return m.group(1)


def test_resume_headings_in_order():
    sec = _section()
    heads = ["# Resume: <sid>", "## Goal", "## Next step", "## Pending operator decisions", "## Work state",
             "## Artifacts", "## Agents", "## Watch out"]
    block = re.search(r"```\n[ \t]*(# Resume: <sid>\n.*?)```", sec, re.S)
    assert block, "resume heading block missing"
    lines = [l.strip() for l in block.group(1).splitlines() if l.strip().startswith("#")]
    assert lines == heads, lines


def test_constants_match_library():
    ck = _ck()
    sec = _section()
    assert str(ck.RESUME_MAX_BYTES) in sec and ck.RESUME_MAX_BYTES == 8192
    assert "-mtime +%d" % ck.RESUME_RETENTION_DAYS in sec and ck.RESUME_RETENTION_DAYS == 14
    assert ".agentic/resume/consumed/" in sec
    assert ck.RESUME_DIR == ".agentic/resume"
    assert "Session wrapped (idle 2h). Run /exit, then resume with: <kickoff>" in sec
    assert "ds-session-close" not in sec
    assert "DS_WRAP_EOF" not in sec, "a fixed heredoc delimiter can be ended early by conversation text"
    assert "`DSW_<nonce>_<n>`" in sec and "tr -dc 'a-f0-9'" in sec
    assert "four requests" in sec and "one Read of this file" in sec


def test_fallback_prompt_identical_everywhere():
    ck = _ck()
    assert ("`" + ck.FALLBACK_PROMPT + "`") in _section()
    assert ("`" + ck.FALLBACK_PROMPT + "`") in DOC.read_text()


def test_kickoff_prompt_documented():
    ck = _ck()
    first = ck.KICKOFF_PROMPT.split("{sid}")[0]
    assert first == "Resume wrapped session "
    assert "Resume wrapped session <id>" in DOC.read_text()
