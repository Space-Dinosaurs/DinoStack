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
        Dirs whose name starts with project_dir_prefix(repo) AND whose first
        recorded `cwd` is the repo or under it (rejects `/Users/x/r2` for
        repo `/Users/x/r`).
    sessions(repo, start, end, stores) -> list[Session]
        Sessions whose [first_ts, last_ts] (the top-level transcript's own
        timestamps) overlaps [start, end]. Naive datetimes are read as UTC.
    Session: session_id, store, path, cost_usd, model_usage, conductor,
        subagents, first_ts, last_ts.
        cost_usd/model_usage come from the LAST `totalCostUSD` record; both
        are None when no such record exists (never 0 / never {}). conductor
        counts the top-level transcript's non-sidechain assistant records.
    Sub: agent_id, agent_type, description, tool_use_id, usage,
        wall_seconds, pr_created. Meta fields are None without a
        `.meta.json`; wall_seconds is None with fewer than one timestamp.
    Usage: dict keyed by (model, entrypoint, version) -> token dict
        (input, output, cache_read, cache_creation, cache_creation_5m,
        cache_creation_1h, messages). One assistant record per
        (file, message.id), keeping the MAX output_tokens (streaming
        partials repeat a message.id; the max is the complete one).
        Model `<synthetic>` is dropped.

Upstream deps: Python 3 stdlib; bin/_lib.py (CONFIG_DIR_ENV), loaded by
    resolved path. Transcript layout: <store>/<project-dir>/<session>.jsonl,
    subagents at <store>/<project-dir>/<session>/subagents/agent-<id>.jsonl
    plus agent-<id>.meta.json (agentType, description, toolUseId).

Downstream consumers: none yet (see Purpose); bin/tests/test_transcripts.py.

Failure modes: never raises on a missing store, an unreadable file, a
    malformed line or a missing field - each degrades to fewer records.
    Absent data is None or empty, never a fabricated zero. `cwd` and
    `timestamp` are read by substring/regex on the harness's compact JSON
    (`"key":"value"`, no spaces); a spaced writer would yield no sessions.

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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

_LIB_PATH = Path(__file__).resolve().parent / "_lib.py"
_lib_loader = importlib.machinery.SourceFileLoader("_transcripts_lib", str(_LIB_PATH))
_lib = importlib.util.module_from_spec(importlib.util.spec_from_loader(_lib_loader.name, _lib_loader))
_lib_loader.exec_module(_lib)

SYNTHETIC_MODEL = "<synthetic>"
_TS_KEY = '"timestamp":"'
_CWD_RE = re.compile(r'"cwd":"((?:[^"\\]|\\.)*)"')
_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]")
_PR_URL_RE = re.compile(r"https://github\.com/[^/\s\"]+/[^/\s\"]+/pull/(\d+)")
_GH_PR_CREATE_RE = re.compile(
    r"(?:^|[;&(\n]|&&|\|\|)\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*gh\s+pr\s+create\b"
)


class Usage(dict):
    """(model, entrypoint, version) -> token counts."""

    def add(self, key: tuple, usage: dict) -> None:
        bucket = self.setdefault(key, {
            "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
            "cache_creation_5m": 0, "cache_creation_1h": 0, "messages": 0,
        })
        raw_split = usage.get("cache_creation")
        split: dict = raw_split if isinstance(raw_split, dict) else {}
        bucket["input"] += _int(usage.get("input_tokens"))
        bucket["output"] += _int(usage.get("output_tokens"))
        bucket["cache_read"] += _int(usage.get("cache_read_input_tokens"))
        bucket["cache_creation"] += _int(usage.get("cache_creation_input_tokens"))
        bucket["cache_creation_5m"] += _int(split.get("ephemeral_5m_input_tokens"))
        bucket["cache_creation_1h"] += _int(split.get("ephemeral_1h_input_tokens"))
        bucket["messages"] += 1


@dataclass
class Sub:
    agent_id: str
    agent_type: Optional[str]
    description: Optional[str]
    tool_use_id: Optional[str]
    usage: Usage
    wall_seconds: Optional[float]
    pr_created: list[int] = field(default_factory=list)


@dataclass
class Session:
    session_id: str
    store: Path
    path: Path
    cost_usd: Optional[float]
    model_usage: Optional[dict]
    conductor: Usage
    subagents: list[Sub]
    first_ts: Optional[datetime]
    last_ts: Optional[datetime]


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _parse_ts(raw: str) -> Optional[datetime]:
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _aware(ts)


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _line_ts(line: str) -> Optional[datetime]:
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


def stores(extra: Optional[Iterable] = None) -> list[Path]:
    candidates: list[Path] = [Path(p) for p in sorted(glob.glob(os.path.expanduser("~/.claude*/projects")))]
    for var in _lib.CONFIG_DIR_ENV:
        raw = os.environ.get(var, "").strip()
        if raw:
            candidates.append(Path(os.path.abspath(os.path.expanduser(raw))) / "projects")
    for p in extra or ():
        p = Path(os.path.abspath(os.path.expanduser(str(p))))
        candidates.append(p / "projects" if (p / "projects").is_dir() else p)
    seen: set[str] = set()
    out: list[Path] = []
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


def _dir_cwd(project_dir: Path) -> Optional[str]:
    files = sorted(project_dir.glob("*.jsonl")) or sorted(project_dir.glob("*/subagents/agent-*.jsonl"))
    for f in files:
        cwd = _first_cwd(f)
        if cwd:
            return cwd
    return None


def _under(path: str, repo: str) -> bool:
    path = os.path.normpath(path)
    return path == repo or path.startswith(repo.rstrip("/") + "/")


def project_dirs(repo, stores: Iterable[Path]) -> list[Path]:
    repo_abs = os.path.normpath(os.path.abspath(str(repo)))
    prefix = project_dir_prefix(repo_abs)
    out: list[Path] = []
    for store in stores:
        try:
            names = sorted(os.listdir(store))
        except OSError:
            continue
        for name in names:
            d = Path(store) / name
            if not name.startswith(prefix) or not d.is_dir():
                continue
            cwd = _dir_cwd(d)
            if cwd and _under(cwd, repo_abs):
                out.append(d)
    return out


def _scan(path: Path, want_cost: bool, want_prs: bool, skip_sidechain: bool) -> dict:
    """One pass over a transcript: deduped usage, timestamps, cost, PRs."""
    best: dict[str, tuple[int, tuple, dict]] = {}
    first = last = None
    cost_rec = None
    pr_uses: set[str] = set()
    prs: list[int] = []
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
                    if model and model != SYNTHETIC_MODEL:
                        mid = msg.get("id") or rec.get("uuid") or f"line-{n}"
                        out_tok = _int(msg["usage"].get("output_tokens"))
                        prev = best.get(mid)
                        if prev is None or out_tok >= prev[0]:
                            key = (model, rec.get("entrypoint"), rec.get("version"))
                            best[mid] = (out_tok, key, msg["usage"])
            if want_cost and "totalCostUSD" in line:
                rec = _loads(line)
                if rec and isinstance(rec.get("totalCostUSD"), (int, float)) and not isinstance(rec.get("totalCostUSD"), bool):
                    cost_rec = rec
            if want_prs and ("pr create" in line or pr_uses and '"tool_use_id"' in line):
                rec = _loads(line)
                if rec:
                    prs.extend(_pr_numbers(rec, pr_uses))
    usage = Usage()
    for _out, key, u in best.values():
        usage.add(key, u)
    return {"usage": usage, "first": first, "last": last, "cost": cost_rec, "prs": prs}


def _pr_numbers(rec: dict, pr_uses: set[str]) -> list[int]:
    content = (rec.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    found: list[int] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            cmd = (block.get("input") or {}).get("command")
            if isinstance(cmd, str) and _GH_PR_CREATE_RE.search(cmd) and block.get("id"):
                pr_uses.add(block["id"])
        elif block.get("type") == "tool_result" and block.get("tool_use_id") in pr_uses:
            pr_uses.discard(block["tool_use_id"])
            if block.get("is_error"):
                continue
            git_op = (rec.get("toolUseResult") or {}).get("gitOperation") if isinstance(rec.get("toolUseResult"), dict) else None
            pr = (git_op or {}).get("pr") if isinstance(git_op, dict) else None
            if isinstance(pr, dict) and isinstance(pr.get("number"), int) and pr.get("action") in (None, "created"):
                found.append(pr["number"])
                continue
            m = _PR_URL_RE.search(json.dumps(block.get("content")))
            if m:
                found.append(int(m.group(1)))
    return found


def _read_meta(path: Path) -> dict:
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


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


def sessions(repo, start: datetime, end: datetime, stores: Iterable[Path]) -> list[Session]:
    start, end = _aware(start), _aware(end)
    start_epoch = start.timestamp()
    out: list[Session] = []
    for store in stores:
        for pdir in project_dirs(repo, [store]):
            for main in sorted(pdir.glob("*.jsonl")):
                sub_files = sorted((pdir / main.stem / "subagents").glob("agent-*.jsonl"))
                if max([_mtime(main)] + [_mtime(f) for f in sub_files]) < start_epoch:
                    continue
                scan = _scan(main, want_cost=True, want_prs=False, skip_sidechain=True)
                first, last = scan["first"], scan["last"]
                if first is None or first > end or last < start:
                    continue
                subs = [_sub(f) for f in sub_files]
                cost = scan["cost"]
                model_usage = cost.get("modelUsage") if cost else None
                out.append(Session(
                    session_id=main.stem, store=Path(store), path=main,
                    cost_usd=float(cost["totalCostUSD"]) if cost else None,
                    model_usage=model_usage if isinstance(model_usage, dict) else None,
                    conductor=scan["usage"], subagents=subs, first_ts=first, last_ts=last,
                ))
    return out
