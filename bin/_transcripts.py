"""
Purpose: Shared read-only reader over Claude Code session transcripts across
         EVERY config-dir store on the machine, not only the active one.
         Catches two failures of the existing evaluation tools: they read
         only the active CLAUDE_CONFIG_DIR, while ~73% of measured spend
         (2026-10-04) sits in another profile's store (`~/.claude-moment8`),
         and they see subagent spawn rows but never the conductor's own
         token spend, which lives only in the top-level session transcript.
         Retire this module when the harness ships a cost export that
         covers all profiles (per-session cost and per-agent usage); the
         transcript shapes it parses are undocumented harness internals.
         Intentionally unwired when added: later units of the ds-eval
         telemetry program (bin/_eval.py / ds-eval, ds-cost, ds-change-delta,
         ds-skill-load-rate) are its consumers.

Public API:
    stores(extra=None) -> list[Path]
        Realpath-deduped union of existing `~/.claude*/projects` dirs, the
        `projects` dir under each dir named by `_lib.CONFIG_DIR_ENV`, and each
        `extra` path (a config dir with a `projects` child, or a projects dir).
    project_dir_prefix(repo) -> str
        Claude Code's project-dir name for an absolute path: every
        non-alphanumeric character becomes "-" (`/Users/x/r` -> `-Users-x-r`,
        `/r/.agentic` -> `-r--agentic`).
    project_dirs(repo, stores) -> list[Path]
        Dirs whose name starts with project_dir_prefix(repo) and holding at
        least one session whose first recorded `cwd` is the repo or under it
        (rejects `/Users/x/r2` for repo `/Users/x/r`).
    sessions(repo, start, end, stores) -> list[Session]
        Sessions whose own first `cwd` is the repo or under it (checked per
        session file: `/x/r-foo` and `/x/r/foo` share one dir name) and whose
        [first_ts, last_ts] overlaps [start, end]. Naive datetimes are UTC.
    Session: session_id, store, path, cost_usd, cost_start_ts, model_usage,
        conductor, subagents, first_ts, last_ts.
        first_ts/last_ts are the top-level records' own `timestamp` values
        (a file-history-snapshot's nested snapshot time is not one).
        cost_usd/model_usage come from the LAST `totalCostUSD` record; both
        are None when no such record exists (never 0 / never {}). That record
        is written per harness PROCESS: cost_usd covers the lifetime of the
        last process that wrote the session (from cost_start_ts, its
        `startTime`), not necessarily the whole session - a resumed session
        can start well before cost_start_ts. conductor counts the top-level
        transcript's non-sidechain assistant records.
    Sub: agent_id, agent_type, description, tool_use_id, usage,
        wall_seconds, pr_created. Meta fields are None without a
        `.meta.json`; wall_seconds is None without a timestamp.
        pr_created: list of (repo, number), repo `owner/name` or None. A
        tool_result whose `toolUseResult.gitOperation.pr.action` is
        "created" is authoritative whatever the command text; otherwise a
        non-error result of a `gh pr create` command contributes the PR URL
        it printed.
    Usage: dict keyed by (model, entrypoint, version) -> token dict
        (input, output, cache_read, cache_creation, cache_creation_5m,
        cache_creation_1h, messages). One assistant record per
        (file, message.id), keeping the MAX output_tokens (streaming
        partials repeat a message.id; the max is the complete one).
        Model `<synthetic>` is dropped. cache_creation_5m/_1h are None once
        any record in the bucket lacks the 5m/1h split.

Upstream deps: Python 3 stdlib; bin/_lib.py (CONFIG_DIR_ENV), loaded by
    resolved path. Transcript layout: <store>/<project-dir>/<session>.jsonl,
    subagents at <store>/<project-dir>/<session>/subagents/agent-<id>.jsonl
    plus agent-<id>.meta.json (agentType, description, toolUseId).

Downstream consumers: none yet (see Purpose); bin/tests/test_transcripts.py.

Failure modes: never raises on a missing store, an unreadable file, a
    malformed line or a missing or wrongly-typed field - each degrades to
    fewer records. Absent data is None or empty, never a fabricated zero.
    `cwd` and `timestamp` are read by substring/regex on the harness's
    compact JSON (`"key":"value"`, no spaces); a spaced writer would yield
    no sessions.

Performance: one streaming pass per transcript file. Lines are prefiltered
    by substring before json parsing; a session whose files were all last
    modified before `start` is skipped without opening it.
"""

import glob
import importlib.machinery
import importlib.util
import json
import os
import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

_LIB_PATH = Path(__file__).resolve().parent / "_lib.py"
_lib_loader = importlib.machinery.SourceFileLoader("_transcripts_lib", str(_LIB_PATH))
_lib = importlib.util.module_from_spec(importlib.util.spec_from_loader(_lib_loader.name, _lib_loader))
_lib_loader.exec_module(_lib)

SYNTHETIC_MODEL = "<synthetic>"
_TS_KEY = '"timestamp":"'
_SNAPSHOT_MARK = '"type":"file-history-snapshot"'
_CWD_RE = re.compile(r'"cwd":"((?:[^"\\]|\\.)*)"')
_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]")
_PR_URL_RE = re.compile(r"https://github\.com/([^/\s\"']+/[^/\s\"']+)/pull/(\d+)")
_SHELL_SEPARATORS = set("();<>|&\n")
_LINE_GH_PR_CREATE_RE = re.compile(
    r"(?:^|&&|\|\||;)\s*(?:[A-Za-z_][A-Za-z0-9_]*=(?:\$\([^)]*\)|\"[^\"]*\"|'[^']*'|\S+)\s+)*"
    r"(?:direnv\s+exec\s+\S+\s+|env\s+)?(?:\S*/)?gh\s+pr\s+create\b",
    re.MULTILINE,
)

PrRef = Tuple[Optional[str], int]


class Usage(dict):
    """(model, entrypoint, version) -> token counts."""

    def add(self, key: tuple, usage: dict) -> None:
        bucket = self.setdefault(key, {
            "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
            "cache_creation_5m": 0, "cache_creation_1h": 0, "messages": 0,
        })
        bucket["input"] += _int(usage.get("input_tokens"))
        bucket["output"] += _int(usage.get("output_tokens"))
        bucket["cache_read"] += _int(usage.get("cache_read_input_tokens"))
        bucket["cache_creation"] += _int(usage.get("cache_creation_input_tokens"))
        split = usage.get("cache_creation")
        for name, src in (("cache_creation_5m", "ephemeral_5m_input_tokens"),
                          ("cache_creation_1h", "ephemeral_1h_input_tokens")):
            value = split.get(src) if isinstance(split, dict) else None
            if bucket[name] is None or not isinstance(value, int) or isinstance(value, bool):
                bucket[name] = None
            else:
                bucket[name] += value
        bucket["messages"] += 1


@dataclass
class Sub:
    agent_id: str
    agent_type: Optional[str]
    description: Optional[str]
    tool_use_id: Optional[str]
    usage: Usage
    wall_seconds: Optional[float]
    pr_created: List[PrRef] = field(default_factory=list)


@dataclass
class Session:
    session_id: str
    store: Path
    path: Path
    cost_usd: Optional[float]
    cost_start_ts: Optional[datetime]
    model_usage: Optional[dict]
    conductor: Usage
    subagents: List[Sub]
    first_ts: Optional[datetime]
    last_ts: Optional[datetime]


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _parse_ts(raw: str) -> Optional[datetime]:
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _aware(ts)


def _line_ts(line: str) -> Optional[datetime]:
    """The record's own top-level timestamp. A file-history-snapshot has no
    top-level timestamp, only a nested snapshot one, so it yields None."""
    if _SNAPSHOT_MARK in line:
        return None
    i = line.rfind(_TS_KEY)
    if i < 0:
        return None
    j = line.find('"', i + len(_TS_KEY))
    return _parse_ts(line[i + len(_TS_KEY):j]) if j > 0 else None


def _loads(line: str) -> Optional[dict]:
    try:
        rec = json.loads(line)
    except (ValueError, TypeError):
        return None
    return rec if isinstance(rec, dict) else None


def stores(extra: Optional[Iterable] = None) -> List[Path]:
    candidates: List[Path] = [Path(p) for p in sorted(glob.glob(os.path.expanduser("~/.claude*/projects")))]
    for var in _lib.CONFIG_DIR_ENV:
        raw = os.environ.get(var, "").strip()
        if raw:
            candidates.append(Path(os.path.abspath(os.path.expanduser(raw))) / "projects")
    for p in extra or ():
        p = Path(os.path.abspath(os.path.expanduser(str(p))))
        candidates.append(p / "projects" if (p / "projects").is_dir() else p)
    seen = set()
    out: List[Path] = []
    for p in candidates:
        if not p.is_dir():
            continue
        real = os.path.realpath(p)
        if real not in seen:
            seen.add(real)
            out.append(Path(real))
    return out


def project_dir_prefix(repo) -> str:
    return _NON_ALNUM_RE.sub("-", os.path.abspath(str(repo)))


def _first_cwd(path: Path) -> Optional[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"cwd"' not in line:
                    continue
                m = _CWD_RE.search(line)
                if m:
                    try:
                        return json.loads('"' + m.group(1) + '"')
                    except ValueError:
                        return None
    except OSError:
        return None
    return None


def _under(path: str, repo: str) -> bool:
    path = os.path.normpath(path)
    return path == repo or path.startswith(repo.rstrip("/") + "/")


def _session_in_repo(main: Path, repo_abs: str) -> bool:
    cwd = _first_cwd(main)
    if cwd is None:
        subs = sorted((main.parent / main.stem / "subagents").glob("agent-*.jsonl"))
        cwd = next((c for c in map(_first_cwd, subs) if c), None)
    return bool(cwd) and _under(cwd, repo_abs)


def _candidate_dirs(repo_abs: str, stores: Iterable[Path]) -> List[Path]:
    prefix = project_dir_prefix(repo_abs)
    out: List[Path] = []
    for store in stores:
        try:
            names = sorted(os.listdir(store))
        except OSError:
            continue
        out.extend(Path(store) / n for n in names if n.startswith(prefix) and (Path(store) / n).is_dir())
    return out


def project_dirs(repo, stores: Iterable[Path]) -> List[Path]:
    repo_abs = os.path.normpath(os.path.abspath(str(repo)))
    return [d for d in _candidate_dirs(repo_abs, stores)
            if any(_session_in_repo(f, repo_abs) for f in sorted(d.glob("*.jsonl")))]


def _is_gh_pr_create(cmd: str) -> bool:
    """True when some simple command in `cmd` runs `gh pr create`, directly or
    behind env assignments or a wrapper (`direnv exec . gh pr create`).
    Quoted text (`grep 'gh pr create'`) is one token and never matches.
    When shlex cannot tokenize (a heredoc body with a lone apostrophe), fall
    back to a per-line match anchored at line start or a `&&`/`||`/`;`."""
    try:
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars="();<>|&\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return bool(_LINE_GH_PR_CREATE_RE.search(cmd))
    segment: List[str] = []
    for tok in tokens + [";"]:
        if tok and set(tok) <= _SHELL_SEPARATORS:
            if any(os.path.basename(segment[i]) == "gh" and segment[i + 1:i + 3] == ["pr", "create"]
                   for i in range(len(segment) - 2)):
                return True
            segment = []
        else:
            segment.append(tok)
    return False


def _pr_from_git_operation(rec: dict) -> Optional[PrRef]:
    pr = _dict(_dict(_dict(rec.get("toolUseResult")).get("gitOperation")).get("pr"))
    number = pr.get("number")
    if pr.get("action") != "created" or not isinstance(number, int) or isinstance(number, bool):
        return None
    texts = [pr.get("url") if isinstance(pr.get("url"), str) else "",
             json.dumps(_dict(rec.get("message")).get("content"))]
    repo = next((m.group(1) for t in texts for m in _PR_URL_RE.finditer(t) if int(m.group(2)) == number), None)
    return (repo, number)


def _pr_refs(rec: dict, pr_uses: set) -> List[PrRef]:
    content = _dict(rec.get("message")).get("content")
    if not isinstance(content, list):
        return []
    found: List[PrRef] = []
    git_pr = _pr_from_git_operation(rec)
    if git_pr is not None:
        found.append(git_pr)
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            cmd = _dict(block.get("input")).get("command")
            if isinstance(cmd, str) and isinstance(block.get("id"), str) and _is_gh_pr_create(cmd):
                pr_uses.add(block["id"])
        elif block.get("type") == "tool_result" and block.get("tool_use_id") in pr_uses:
            pr_uses.discard(block["tool_use_id"])
            if block.get("is_error") or git_pr is not None:
                continue
            m = _PR_URL_RE.search(json.dumps(block.get("content")))
            if m:
                found.append((m.group(1), int(m.group(2))))
    return found


def _scan(path: Path, want_cost: bool, want_prs: bool, skip_sidechain: bool) -> dict:
    """One pass over a transcript: deduped usage, timestamps, cost, PRs."""
    best: dict = {}
    first = last = None
    cost_rec = None
    pr_uses: set = set()
    prs: List[PrRef] = []
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return {"usage": Usage(), "first": None, "last": None, "cost": None, "prs": []}
    with handle:
        for n, line in enumerate(handle):
            ts = _line_ts(line)
            if ts is not None:
                if first is None or ts < first:
                    first = ts
                if last is None or ts > last:
                    last = ts
            if '"usage"' in line and '"assistant"' in line:
                rec = _loads(line) or {}
                msg = rec.get("message")
                if (isinstance(msg, dict) and isinstance(msg.get("usage"), dict)
                        and not (skip_sidechain and rec.get("isSidechain") is True)):
                    model = msg.get("model")
                    if isinstance(model, str) and model and model != SYNTHETIC_MODEL:
                        mid = msg.get("id") or rec.get("uuid") or f"line-{n}"
                        out_tok = _int(msg["usage"].get("output_tokens"))
                        prev = best.get(mid)
                        if prev is None or out_tok >= prev[0]:
                            key = (model, rec.get("entrypoint"), rec.get("version"))
                            best[mid] = (out_tok, key, msg["usage"])
            if want_cost and "totalCostUSD" in line:
                rec = _loads(line)
                total = rec.get("totalCostUSD") if rec else None
                if isinstance(total, (int, float)) and not isinstance(total, bool):
                    cost_rec = rec
            if want_prs and ("pr create" in line or '"gitOperation"' in line
                             or pr_uses and '"tool_use_id"' in line):
                rec = _loads(line)
                if rec:
                    prs.extend(_pr_refs(rec, pr_uses))
    usage = Usage()
    for _out, key, u in best.values():
        usage.add(key, u)
    return {"usage": usage, "first": first, "last": last, "cost": cost_rec, "prs": prs}


def _read_meta(path: Path) -> dict:
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return _dict(meta)


def _sub(path: Path) -> Sub:
    agent_id = path.stem[len("agent-"):]
    meta = _read_meta(path.with_name(path.stem + ".meta.json"))
    scan = _scan(path, want_cost=False, want_prs=True, skip_sidechain=False)
    wall = (scan["last"] - scan["first"]).total_seconds() if scan["first"] and scan["last"] else None
    prs = list(dict.fromkeys(scan["prs"]))
    return Sub(agent_id, meta.get("agentType"), meta.get("description"), meta.get("toolUseId"),
               scan["usage"], wall, prs)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _epoch_ms(value) -> Optional[datetime]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def sessions(repo, start: datetime, end: datetime, stores: Iterable[Path]) -> List[Session]:
    start, end = _aware(start), _aware(end)
    start_epoch = start.timestamp()
    repo_abs = os.path.normpath(os.path.abspath(str(repo)))
    out: List[Session] = []
    for store in stores:
        for pdir in _candidate_dirs(repo_abs, [store]):
            for main in sorted(pdir.glob("*.jsonl")):
                sub_files = sorted((pdir / main.stem / "subagents").glob("agent-*.jsonl"))
                if max([_mtime(main)] + [_mtime(f) for f in sub_files]) < start_epoch:
                    continue
                if not _session_in_repo(main, repo_abs):
                    continue
                scan = _scan(main, want_cost=True, want_prs=False, skip_sidechain=True)
                first, last = scan["first"], scan["last"]
                if first is None or first > end or last < start:
                    continue
                cost = scan["cost"]
                model_usage = cost.get("modelUsage") if cost else None
                out.append(Session(
                    session_id=main.stem, store=Path(store), path=main,
                    cost_usd=float(cost["totalCostUSD"]) if cost else None,
                    cost_start_ts=_epoch_ms(cost.get("startTime")) if cost else None,
                    model_usage=model_usage if isinstance(model_usage, dict) else None,
                    conductor=scan["usage"], subagents=[_sub(f) for f in sub_files],
                    first_ts=first, last_ts=last,
                ))
    return out
