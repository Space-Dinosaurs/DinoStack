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
         bin/_eval.py (ds-eval) consumes it; ds-cost and ds-change-delta
         are wired by later units of the ds-eval telemetry program.

Public API:
    stores(extra=None, include_default=True) -> list[Path]
        Realpath-deduped union of existing `~/.claude*/projects` dirs, the
        `projects` dir under each dir named by `_lib.CONFIG_DIR_ENV`, and each
        `extra` path (a config dir with a `projects` child, or a projects dir).
        include_default=False keeps only the `extra` paths (a `--store` flag
        that replaces the default set).
    resolve_stores(requested=None) -> StoreSet
        stores(requested, include_default=not requested), split into
        `readable`, `unreadable` ((path, reason) for a store that exists but
        cannot be listed or traversed - never to be reported as an empty
        store) and `missing` ((path, reason) for each requested path that
        does not exist or is not a directory).
        problem_entries(count_key="sessions") renders the last two as
        {path, status "unreadable"|"missing"|"invalid", <count_key> None,
        reason, unreadable_dirs None, unreadable_dir_paths []}.
    listdir_checked(path) -> (names, reason)
        Sorted names, or ([], reason) when the directory does not exist, is
        not a directory, or cannot be listed or traversed (checked in that
        order). jsonl_files(dir) -> (paths, reason) filters it to `*.jsonl`.
    store_entry(store, count, unreadable_dirs, count_key="sessions") -> dict
        A scanned store's report: status "scanned", or "partial" when any
        subdirectory could not be read (`unreadable_dirs` N plus
        `unreadable_dir_paths`); a partial count is a floor, and a partial
        store that counted nothing reports None. store_line(entry, ...)
        renders any entry as one text line: the count, ">= N ... (partial:
        ..., count is a floor)", or "ABSENT (<status>: <reason>)".
    project_dir_prefix(repo) -> str
        Claude Code's project-dir name for an absolute path: every
        non-alphanumeric character becomes "-" (`/Users/x/r` -> `-Users-x-r`,
        `/r/.agentic` -> `-r--agentic`). Older Claude Code replaced only "/"
        (`-r-.agentic`); project-dir matching accepts both prefixes.
    project_dirs_checked(repo, store) -> (dirs, unreadable)
        Within one store: dirs whose name starts with either prefix for the
        repo and that hold at least one session whose first recorded `cwd`
        is the repo or under it (rejects `/Users/x/r2` for repo
        `/Users/x/r`), plus (dir, reason) for each prefix-matching dir that
        cannot be read, so it can never be confirmed or rejected. The repo
        is matched both as given and as its realpath (`/tmp/x` is
        `/private/tmp/x` on macOS).
    project_dirs(repo, stores) -> list[Path]
        project_dirs_checked's readable dirs across stores.
    sessions(repo, start, end, stores) -> list[Session]
        Sessions whose own first `cwd` is the repo or under it (checked per
        session file: `/x/r-foo` and `/x/r/foo` share one dir name; a session
        whose top-level file records no cwd falls back to its subagents') and
        whose [first_ts, last_ts] overlaps [start, end]. Naive datetimes are
        UTC.
    Session: session_id, store, path, cost_usd, cost_state_usd,
        cost_covers_session, cost_start_ts, model_usage, conductor,
        subagents, first_ts, last_ts, pr_created, keepalive, turns.
        first_ts/last_ts are the top-level records' own `timestamp` values
        (a file-history-snapshot's nested snapshot time is not one).
        cost_state_usd/model_usage are the raw figures from the LAST
        `totalCostUSD` record; both are None when no such record exists. That
        record is written per harness PROCESS (cost_start_ts is its
        `startTime`), so after a resume it covers only the last process.
        cost_covers_session is True only when cost_start_ts is no more than
        COST_START_TOLERANCE_S (5 s) after the session's first counted
        assistant record (or there is no such record). cost_usd equals
        cost_state_usd when it covers the session and is None otherwise -
        never a 0 standing in for spend an earlier process made.
        conductor counts the top-level transcript's non-sidechain assistant
        records outside keepalive ping turns; keepalive counts those inside
        them (the two never overlap). pr_created lists the conductor's own PR
        creations.
    Turn: kind ("ping" | "human" | "other"), ts, gated, wrap, cron_delete,
        requests, first ({model, cache_read, cache_creation} of the
        turn's first request, or None), last_ts, usage. A turn opens at every
        user record cache_keepalive's LG.starts_turn accepts (human, task
        notification, agent hand-back, scheduled), not only at human ones;
        a ping is LG.is_ping_record. outcome (pings only): dropped (no
        request), wrapped (WRAP_MARKER in its UserPromptSubmit hook output),
        passed (LG.GATE_NOTE there), deleted (a CronDelete tool_use), else
        unclassified. A request belongs to the turn its first record falls
        in; requests before any turn opener form an "other" turn.
    Sub: agent_id, agent_type, description, tool_use_id, usage,
        wall_seconds, pr_created. Meta fields are None without a
        `.meta.json`; wall_seconds is None without a timestamp.
    pr_created (Session and Sub): list of (repo, number, ts), repo
        `owner/name` or None, ts the tool_result record's timestamp, one entry
        per (repo, number). Only the result of a command that really runs
        `gh pr create` counts - a non-error result, or an error result that
        still printed a PR URL (a later command in the chain failed) and is
        not gh's "a pull request ... already exists: <url>" refusal. Number
        and repo come from the result's `toolUseResult.gitOperation.pr`
        ("created") when present, else from the PR URL it printed.
        gitOperation alone never counts: the harness also records one for a
        command that merely contains the text "gh pr create" and prints a URL.
    Usage: dict keyed by (model, entrypoint, version) -> token dict
        (input, output, cache_read, cache_creation, cache_creation_5m,
        cache_creation_1h, messages). One assistant record per
        (file, message.id), keeping the MAX output_tokens; on a tie the later
        record wins (streaming partials repeat a message.id; the last, largest
        one is complete). Model `<synthetic>` is dropped.
        cache_creation_5m/_1h are None once any record in the bucket lacks
        the 5m/1h split.

Upstream deps: Python 3 stdlib; bin/_lib.py (CONFIG_DIR_ENV) and
    hooks/lib/cache_keepalive.py (its LG ping and turn predicates, GATE_NOTE,
    WRAP_MARKER), both loaded by resolved path. Transcript layout: <store>/<project-dir>/<session>.jsonl,
    subagents at <store>/<project-dir>/<session>/subagents/agent-<id>.jsonl
    plus agent-<id>.meta.json (agentType, description, toolUseId).

Downstream consumers: bin/ds-skill-load-rate, bin/ds-learnings-retrieval-rate,
    bin/ds-measure-conductor-tool-calls (store set and repo-to-dir mapping);
    bin/_eval.py (ds-eval: resolve_stores, store_entry, project_dirs_checked,
    sessions, Session.keepalive and Session.turns); bin/tests/test_transcripts.py.

Failure modes: never raises on a missing store, an unreadable file, a
    malformed line or a missing or wrongly-typed field - such a record is
    skipped. Absent data is None or empty, never a fabricated zero.
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
_CK_PATH = Path(__file__).resolve().parent.parent / "hooks" / "lib" / "cache_keepalive.py"
_ck_loader = importlib.machinery.SourceFileLoader("_transcripts_cache_keepalive", str(_CK_PATH))
_ck = importlib.util.module_from_spec(importlib.util.spec_from_loader(_ck_loader.name, _ck_loader))
_ck_loader.exec_module(_ck)

SYNTHETIC_MODEL = "<synthetic>"
COST_START_TOLERANCE_S = 5.0
_TS_KEY = '"timestamp":"'
_SNAPSHOT_MARK = '"type":"file-history-snapshot"'
_CWD_RE = re.compile(r'"cwd":"((?:[^"\\]|\\.)*)"')
_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]")
_PR_URL_RE = re.compile(r"https://github\.com/([^/\s\"']+/[^/\s\"']+)/pull/(\d+)")
_SHELL_SEPARATORS = set("();<>|&\n")
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# What may precede `gh pr create` within one simple command. The shlex path
# (_strip_wrappers) and the fallback regex below are both built from these.
_BARE_WRAPPERS = ("command", "exec", "nohup", "time", "then", "do", "else")
_FLAG_WRAPPERS = ("env",)
_TIMEOUT_ARG_OPTS = ("-k", "-s", "--kill-after", "--signal")
_LINE_GH_PR_CREATE_RE = re.compile(
    r"(?:^|&&|\|\||;)\s*(?:"
    r"[A-Za-z_][A-Za-z0-9_]*=(?:\$\([^)]*\)|\"[^\"]*\"|'[^']*'|\S+)\s+"
    r"|(?:" + "|".join(_FLAG_WRAPPERS) + r")(?:\s+-\S+)*\s+"
    r"|timeout(?:\s+(?:" + "|".join(_TIMEOUT_ARG_OPTS) + r")\s+\S+|\s+-\S+)*\s+\S+\s+"
    r"|direnv\s+exec\s+\S+\s+"
    r"|(?:" + "|".join(_BARE_WRAPPERS) + r")\s+"
    r")*(?:\S*/)?gh\s+pr\s+create\b",
    re.MULTILINE,
)

PrRef = Tuple[Optional[str], int, Optional[datetime]]


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
class Turn:
    """One main-chain turn: a user record that opens a turn (LG.starts_turn)
    and the assistant requests after it, up to the next such record."""
    kind: str
    ts: Optional[datetime]
    gated: bool = False
    wrap: bool = False
    cron_delete: bool = False
    requests: int = 0
    first: Optional[dict] = None
    last_ts: Optional[datetime] = None
    usage: Usage = field(default_factory=Usage)

    @property
    def outcome(self) -> Optional[str]:
        """A ping turn's outcome; None for any other turn."""
        if self.kind != "ping":
            return None
        if not self.requests:
            return "dropped"
        if self.wrap:
            return "wrapped"
        if self.gated:
            return "passed"
        return "deleted" if self.cron_delete else "unclassified"


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
    cost_state_usd: Optional[float]
    cost_covers_session: bool
    cost_start_ts: Optional[datetime]
    model_usage: Optional[dict]
    conductor: Usage
    subagents: List[Sub]
    first_ts: Optional[datetime]
    last_ts: Optional[datetime]
    pr_created: List[PrRef] = field(default_factory=list)
    keepalive: Usage = field(default_factory=Usage)
    turns: List[Turn] = field(default_factory=list)


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


def stores(extra: Optional[Iterable] = None, include_default: bool = True) -> List[Path]:
    candidates: List[Path] = []
    if include_default:
        candidates.extend(Path(p) for p in sorted(glob.glob(os.path.expanduser("~/.claude*/projects"))))
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


Unreadable = List[Tuple[Path, str]]


def listdir_checked(path) -> Tuple[List[str], Optional[str]]:
    """(sorted names, None) for a directory that can be listed and
    traversed, else ([], reason). Existence is decided before permission."""
    try:
        names = os.listdir(path)
    except FileNotFoundError:
        return [], "does not exist"
    except NotADirectoryError:
        return [], "not a directory"
    except OSError as exc:
        return [], (exc.strerror or type(exc).__name__).lower()
    if not os.access(path, os.X_OK):
        return [], "permission denied"
    return sorted(names), None


def jsonl_files(directory: Path) -> Tuple[List[Path], Optional[str]]:
    names, reason = listdir_checked(directory)
    return [Path(directory) / n for n in names if n.endswith(".jsonl") and not n.startswith(".")], reason


def _empty_problem(path: str, status: str, reason: str, count_key: str) -> dict:
    return {"path": path, "status": status, count_key: None, "reason": reason,
            "unreadable_dirs": None, "unreadable_dir_paths": []}


@dataclass
class StoreSet:
    readable: List[Path]
    unreadable: Unreadable
    missing: List[Tuple[str, str]]

    def problem_entries(self, count_key: str = "sessions") -> List[dict]:
        return ([_empty_problem(str(p), "unreadable", r, count_key) for p, r in self.unreadable]
                + [_empty_problem(p, "missing" if r == "does not exist" else "invalid", r, count_key)
                   for p, r in self.missing])


def resolve_stores(requested: Optional[Iterable] = None) -> StoreSet:
    requested = list(requested or ())
    readable: List[Path] = []
    unreadable: Unreadable = []
    for store in stores(requested, include_default=not requested):
        reason = listdir_checked(store)[1]
        if reason is None:
            readable.append(store)
        else:
            unreadable.append((store, reason))
    missing = []
    for p in requested:
        full = Path(os.path.abspath(os.path.expanduser(str(p))))
        if not full.is_dir():
            missing.append((str(p), "not a directory" if full.exists() else "does not exist"))
    return StoreSet(readable, unreadable, missing)


def store_entry(store: Path, count: int, unreadable_dirs: Unreadable,
                count_key: str = "sessions") -> dict:
    """A scanned store's report. With any unreadable subdirectory it is
    `partial` and its count is a floor; a partial store that counted
    nothing reports None (ABSENT), never 0."""
    partial = bool(unreadable_dirs)
    return {
        "path": str(store),
        "status": "partial" if partial else "scanned",
        count_key: None if partial and count == 0 else count,
        "reason": None,
        "unreadable_dirs": len(unreadable_dirs),
        "unreadable_dir_paths": [{"path": str(p), "reason": r} for p, r in unreadable_dirs],
    }


def store_line(entry: dict, count_key: str = "sessions", unit: str = "sessions") -> str:
    path, count = entry["path"], entry[count_key]
    if entry["status"] == "scanned":
        return f"  {path}: {count} {unit}"
    if entry["status"] == "partial":
        note = f"partial: {entry['unreadable_dirs']} unreadable dirs"
        if count is None:
            return f"  {path}: ABSENT ({note})"
        return f"  {path}: >= {count} {unit} ({note}, count is a floor)"
    return f"  {path}: ABSENT ({entry['status']}: {entry['reason']})"


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


def _repo_forms(repo) -> List[str]:
    given = os.path.normpath(os.path.abspath(str(repo)))
    return list(dict.fromkeys([given, os.path.realpath(given)]))


def _under(path: str, repos: List[str]) -> bool:
    forms = {os.path.normpath(path), os.path.realpath(path)}
    return any(p == r or p.startswith(r.rstrip("/") + "/") for p in forms for r in repos)


def _session_in_repo(main: Path, repos: List[str]) -> bool:
    cwd = _first_cwd(main)
    if cwd is None:
        subs = sorted((main.parent / main.stem / "subagents").glob("agent-*.jsonl"))
        cwd = next((c for c in map(_first_cwd, subs) if c), None)
    return bool(cwd) and _under(cwd, repos)


def _legacy_prefix(repo: str) -> str:
    return os.path.abspath(repo).replace("/", "-")


def _candidate_dirs(repos: List[str], stores: Iterable[Path]) -> List[Path]:
    prefixes = tuple(dict.fromkeys(p for r in repos for p in (project_dir_prefix(r), _legacy_prefix(r))))
    out: List[Path] = []
    for store in stores:
        try:
            names = sorted(os.listdir(store))
        except OSError:
            continue
        out.extend(Path(store) / n for n in names if n.startswith(prefixes) and (Path(store) / n).is_dir())
    return out


def project_dirs_checked(repo, store: Path) -> Tuple[List[Path], Unreadable]:
    repos = _repo_forms(repo)
    readable: List[Path] = []
    unreadable: Unreadable = []
    for d in _candidate_dirs(repos, [store]):
        mains, reason = jsonl_files(d)
        if reason is not None:
            unreadable.append((d, reason))
        elif any(_session_in_repo(f, repos) for f in mains):
            readable.append(d)
    return readable, unreadable


def project_dirs(repo, stores: Iterable[Path]) -> List[Path]:
    return [d for store in stores for d in project_dirs_checked(repo, store)[0]]


def _strip_wrappers(words: List[str]) -> List[str]:
    i = 0
    while i < len(words):
        w = words[i]
        if _ASSIGN_RE.match(w) or w in _BARE_WRAPPERS:
            i += 1
        elif w in _FLAG_WRAPPERS or w == "timeout":
            i += 1
            while i < len(words) and words[i].startswith("-"):
                i += 2 if w == "timeout" and words[i] in _TIMEOUT_ARG_OPTS else 1
            if w == "timeout":
                i += 1
        elif w == "direnv" and words[i + 1:i + 2] == ["exec"]:
            i += 3
        else:
            break
    return words[i:]


def _is_gh_pr_create(cmd: str) -> bool:
    """True when some simple command in `cmd` runs `gh pr create`, directly or
    behind env assignments and the wrappers above (`timeout 100 gh pr
    create`, `direnv exec . gh pr create`). Quoted text (`grep 'gh pr
    create'`) is one token and never matches. When shlex cannot tokenize (a
    heredoc body with a lone apostrophe), fall back to a per-line match
    anchored at line start or a `&&`/`||`/`;`, over the same wrapper set."""
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
            words = _strip_wrappers(segment)
            if len(words) >= 3 and os.path.basename(words[0]) == "gh" and words[1:3] == ["pr", "create"]:
                return True
            segment = []
        else:
            segment.append(tok)
    return False


def _pr_from_git_operation(rec: dict, ts: Optional[datetime]) -> Optional[PrRef]:
    pr = _dict(_dict(_dict(rec.get("toolUseResult")).get("gitOperation")).get("pr"))
    number = pr.get("number")
    if pr.get("action") != "created" or not isinstance(number, int) or isinstance(number, bool):
        return None
    texts = [pr.get("url") if isinstance(pr.get("url"), str) else "",
             json.dumps(_dict(rec.get("message")).get("content"))]
    repo = next((m.group(1) for t in texts for m in _PR_URL_RE.finditer(t) if int(m.group(2)) == number), None)
    return (repo, number, ts)


def _pr_refs(rec: dict, pr_uses: set) -> List[PrRef]:
    content = _dict(rec.get("message")).get("content")
    if not isinstance(content, list):
        return []
    ts = _parse_ts(rec["timestamp"]) if isinstance(rec.get("timestamp"), str) else None
    found: List[PrRef] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            cmd = _dict(block.get("input")).get("command")
            if isinstance(cmd, str) and isinstance(block.get("id"), str) and _is_gh_pr_create(cmd):
                pr_uses.add(block["id"])
        elif (block.get("type") == "tool_result" and isinstance(block.get("tool_use_id"), str)
              and block["tool_use_id"] in pr_uses):
            pr_uses.discard(block["tool_use_id"])
            text = json.dumps(block.get("content"))
            m = _PR_URL_RE.search(text)
            if block.get("is_error") and (not m or "already exists" in text):
                continue
            git_pr = _pr_from_git_operation(rec, ts)
            if git_pr is not None:
                found.append(git_pr)
            elif m:
                found.append((m.group(1), int(m.group(2)), ts))
    return found


def _dedupe_prs(prs: List[PrRef]) -> List[PrRef]:
    seen: dict = {}
    for repo, number, ts in prs:
        seen.setdefault((repo, number), (repo, number, ts))
    return list(seen.values())


def _turn_kind(rec: dict) -> str:
    if _ck.LG.is_ping_record(rec):
        return "ping"
    return "human" if rec.get("turnOrigin") == "human" else "other"


def _scan(path: Path, want_cost: bool, skip_sidechain: bool) -> dict:
    """One pass over a transcript: deduped usage, timestamps, cost, PRs.
    The main transcript (skip_sidechain) is also split into turns; usage of
    keepalive ping turns goes to `keepalive`, never to `usage`."""
    best: dict = {}
    first = last = first_assistant = None
    cost_rec = None
    pr_uses: set = set()
    prs: List[PrRef] = []
    turns: List[Turn] = []
    turn_of: dict = {}
    first_ts: dict = {}
    empty: dict = {"usage": Usage(), "first": None, "last": None, "first_assistant": None, "cost": None, "prs": [],
                   "keepalive": Usage(), "turns": []}
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return empty
    with handle:
        for n, line in enumerate(handle):
            ts = _line_ts(line)
            if ts is not None:
                if first is None or ts < first:
                    first = ts
                if last is None or ts > last:
                    last = ts
            if skip_sidechain and '"type":"user"' in line and '"type":"tool_result"' not in line:
                rec = _loads(line) or {}
                if rec.get("type") == "user" and rec.get("isSidechain") is not True and _ck.LG.starts_turn(rec):
                    turns.append(Turn(_turn_kind(rec), ts))
            elif turns and turns[-1].kind == "ping" and '"UserPromptSubmit"' in line:
                att = _dict((_loads(line) or {}).get("attachment"))
                if att.get("hookEvent") == "UserPromptSubmit":
                    blob = json.dumps(att)
                    turns[-1].wrap = turns[-1].wrap or _ck.WRAP_MARKER in blob
                    turns[-1].gated = turns[-1].gated or _ck.LG.GATE_NOTE in blob
            if '"usage"' in line and '"assistant"' in line:
                rec = _loads(line) or {}
                msg = rec.get("message")
                if (isinstance(msg, dict) and isinstance(msg.get("usage"), dict)
                        and not (skip_sidechain and rec.get("isSidechain") is True)):
                    model = msg.get("model")
                    mid = msg.get("id") or rec.get("uuid") or f"line-{n}"
                    key = (model, rec.get("entrypoint"), rec.get("version"))
                    if (isinstance(model, str) and model and model != SYNTHETIC_MODEL and isinstance(mid, str)
                            and all(v is None or isinstance(v, str) for v in key[1:])):
                        if ts is not None and (first_assistant is None or ts < first_assistant):
                            first_assistant = ts
                        if skip_sidechain:
                            if not turns:
                                turns.append(Turn("other", None))
                            turn_of.setdefault(mid, len(turns) - 1)
                            first_ts.setdefault(mid, ts)
                            if turns[turn_of[mid]].kind == "ping" and '"CronDelete"' in line:
                                turns[turn_of[mid]].cron_delete = turns[turn_of[mid]].cron_delete or any(
                                    _dict(b).get("type") == "tool_use" and _dict(b).get("name") == "CronDelete"
                                    for b in (msg.get("content") if isinstance(msg.get("content"), list) else []))
                        out_tok = _int(msg["usage"].get("output_tokens"))
                        prev = best.get(mid)
                        if prev is None or out_tok >= prev[0]:
                            best[mid] = (out_tok, key, msg["usage"])
            if want_cost and "totalCostUSD" in line:
                rec = _loads(line)
                total = rec.get("totalCostUSD") if rec else None
                if isinstance(total, (int, float)) and not isinstance(total, bool):
                    cost_rec = rec
            if "pr create" in line or pr_uses and '"tool_use_id"' in line:
                rec = _loads(line)
                if rec:
                    prs.extend(_pr_refs(rec, pr_uses))
    usage, keepalive = Usage(), Usage()
    for mid, (_out, key, u) in best.items():
        turn = turns[turn_of[mid]] if mid in turn_of else None
        (keepalive if turn is not None and turn.kind == "ping" else usage).add(key, u)
        if turn is None:
            continue
        turn.usage.add(key, u)
        turn.requests += 1
        ts = first_ts.get(mid)
        if turn.first is None:
            turn.first = {"model": key[0], "cache_read": _int(u.get("cache_read_input_tokens")),
                          "cache_creation": _int(u.get("cache_creation_input_tokens"))}
        if ts is not None and (turn.last_ts is None or ts > turn.last_ts):
            turn.last_ts = ts
    return {"usage": usage, "first": first, "last": last, "first_assistant": first_assistant,
            "cost": cost_rec, "prs": _dedupe_prs(prs), "keepalive": keepalive, "turns": turns}


def _read_meta(path: Path) -> dict:
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return _dict(meta)


def _sub(path: Path) -> Sub:
    agent_id = path.stem[len("agent-"):]
    meta = _read_meta(path.with_name(path.stem + ".meta.json"))
    scan = _scan(path, want_cost=False, skip_sidechain=False)
    wall = (scan["last"] - scan["first"]).total_seconds() if scan["first"] and scan["last"] else None
    return Sub(agent_id, meta.get("agentType"), meta.get("description"), meta.get("toolUseId"),
               scan["usage"], wall, scan["prs"])


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


def _cost_covers(cost_start: Optional[datetime], first_assistant: Optional[datetime]) -> bool:
    if cost_start is None:
        return False
    if first_assistant is None:
        return True
    return (cost_start - first_assistant).total_seconds() <= COST_START_TOLERANCE_S


def sessions(repo, start: datetime, end: datetime, stores: Iterable[Path]) -> List[Session]:
    start, end = _aware(start), _aware(end)
    start_epoch = start.timestamp()
    repos = _repo_forms(repo)
    out: List[Session] = []
    for store in stores:
        for pdir in _candidate_dirs(repos, [store]):
            for main in sorted(pdir.glob("*.jsonl")):
                sub_files = sorted((pdir / main.stem / "subagents").glob("agent-*.jsonl"))
                if max([_mtime(main)] + [_mtime(f) for f in sub_files]) < start_epoch:
                    continue
                if not _session_in_repo(main, repos):
                    continue
                scan = _scan(main, want_cost=True, skip_sidechain=True)
                first, last = scan["first"], scan["last"]
                if first is None or first > end or last < start:
                    continue
                cost = scan["cost"]
                state_usd = float(cost["totalCostUSD"]) if cost else None
                cost_start = _epoch_ms(cost.get("startTime")) if cost else None
                covers = _cost_covers(cost_start, scan["first_assistant"])
                model_usage = cost.get("modelUsage") if cost else None
                out.append(Session(
                    session_id=main.stem, store=Path(store), path=main,
                    cost_usd=state_usd if covers else None, cost_state_usd=state_usd,
                    cost_covers_session=covers, cost_start_ts=cost_start,
                    model_usage=model_usage if isinstance(model_usage, dict) else None,
                    conductor=scan["usage"], subagents=[_sub(f) for f in sub_files],
                    first_ts=first, last_ts=last, pr_created=scan["prs"],
                    keepalive=scan["keepalive"], turns=scan["turns"],
                ))
    return out
