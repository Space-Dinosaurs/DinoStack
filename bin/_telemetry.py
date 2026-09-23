"""
Purpose: DS-246 shared spawn-telemetry reader for bin/ds-cost, bin/ds-calibrate
         and bin/ds-change-delta. Folds hook-emitted spawn_start /
         spawn_complete rows into one record per spawn with one entry per
         run (a resumed agent's k-th completion is run k), prices tokens
         against a rate table with the 5m/1h cache-write split, and merges
         spawn rows the hooks wrote to the PRIMARY checkout when a bin tool
         runs from inside a linked worktree.

Public API:
    DEFAULT_RATES: dict - built-in USD-per-MTok table from the DS-246 ticket
        (platform.claude.com pricing, 2026-09-22). Haiku 4.5 and Fable 5.1
        cache_read are 0.1x input (the ticket lists no cache-read price).
    load_rates(include_defaults, pricing_path=PRICING_PATH) -> (rates, source)
        `~/.agentic/pricing.yml` `models:` entries override DEFAULT_RATES.
        include_defaults=False returns pricing.yml entries only.
    resolve_rates(model, rates) -> (rate | None, 'exact' | 'family' | None)
        Exact id first (a trailing `[...]` context tag and `-YYYYMMDD` date
        suffix are ignored), then the opus/sonnet/haiku/fable family.
    price_tokens(model, tokens, rates) -> {total, by_kind, match, missing} | None
        None when no rate resolves. total is None when a band with nonzero
        tokens has no rate (listed in `missing`). Cache writes default to
        1.25x input (5m) and 2x input (1h); tokens without the split are 5m.
    normalize_hook_spawns(events, include_legacy) -> list[SpawnRec]
        include_legacy=False keeps only `data.telemetry_v == 2` rows.
        A complete with no visible start becomes a SpawnRec with
        start_ts=None (callers that count spawns skip it).
    primary_root(start) -> Path
    merge_primary_spawn_rows(cwd_events_path, events, primary_events_path=None) -> list
        Appends the primary root's hook spawn_start/spawn_complete rows when
        the primary events file differs from cwd_events_path.

Upstream deps: Python 3 stdlib; optional pyyaml for pricing.yml;
    hooks/lib/repo_root.py and hooks/lib/git_worktree.py, loaded by
    resolved path (DS-66 symlink-invocation class). Row schema: see
    content/references/events-log.md (hook spawn rows, telemetry_v 2).

Downstream consumers: bin/ds-cost, bin/ds-calibrate, bin/ds-change-delta,
    bin/tests/test_telemetry.py. Loaded via SourceFileLoader.

Failure modes: never raises on malformed rows, a missing or unparseable
    pricing.yml, or an unresolvable git layout - each degrades to fewer rows,
    built-in rates, or the cwd root respectively.

Performance: O(N events); one read of the primary events file per merge.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import re
from pathlib import Path

PRICING_PATH = Path(os.path.expanduser("~/.agentic/pricing.yml"))

DEFAULT_RATES: dict[str, dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.20},
    "claude-sonnet-5": {"input": 2.0, "output": 10.0, "cache_read": 0.20},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cache_read": 0.10},
    "claude-fable-5-1": {"input": 10.0, "output": 50.0, "cache_read": 1.00},
}
_FAMILY_DEFAULT_KEY = {
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
    "fable": "claude-fable-5-1",
}
_CACHE_5M_MULTIPLIER = 1.25
_CACHE_1H_MULTIPLIER = 2.0
_UNRESOLVED_MODELS = {"<synthetic>", "inherit"}
_MODEL_SUFFIX_RE = re.compile(r"(?:\[[^\]]*\])?$")
_DATE_SUFFIX_RE = re.compile(r"-\d{8}$")

BANDS = ("input", "output", "cache_creation_5m", "cache_creation_1h", "cache_read")


def _num(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def load_rates(include_defaults: bool, pricing_path: Path | None = None) -> tuple[dict, str | None]:
    """Rates keyed by model id. `source` names what was used, including a
    pricing.yml that exists but could not be read."""
    path = PRICING_PATH if pricing_path is None else pricing_path
    rates: dict = {k: dict(v) for k, v in DEFAULT_RATES.items()} if include_defaults else {}
    source = "built-in (DS-246, 2026-09-22)" if include_defaults else None
    if not path.is_file():
        return rates, source
    try:
        import yaml
    except ImportError:
        return rates, _join_source(source, "pricing.yml ignored: install pyyaml")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception:  # yaml raises several unrelated error types
        return rates, _join_source(source, "pricing.yml ignored: parse error")
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, dict):
        return rates, _join_source(source, "pricing.yml ignored: no models map")
    for model, entry in models.items():
        if isinstance(entry, dict):
            rates[str(model)] = entry
    return rates, _join_source(source, str(path))


def _join_source(base: str | None, extra: str) -> str:
    return f"{base}; {extra}" if base else extra


def _canonical_model(model: str) -> str:
    return _DATE_SUFFIX_RE.sub("", _MODEL_SUFFIX_RE.sub("", model))


def resolve_rates(model, rates: dict) -> tuple[dict | None, str | None]:
    if not model or not isinstance(model, str) or model in _UNRESOLVED_MODELS:
        return None, None
    for candidate in (model, _canonical_model(model)):
        entry = rates.get(candidate)
        if isinstance(entry, dict):
            return entry, "exact"
    lowered = model.lower()
    for family, default_key in _FAMILY_DEFAULT_KEY.items():
        if family not in lowered:
            continue
        if isinstance(rates.get(default_key), dict):
            return rates[default_key], "family"
        for key in sorted(rates):
            if family in key.lower() and isinstance(rates[key], dict):
                return rates[key], "family"
    return None, None


def token_bands(tokens) -> dict[str, int]:
    """Split a tokens object into the five priced bands. A cache_creation
    total larger than the recorded 5m+1h split is treated as 5m."""
    tokens = tokens if isinstance(tokens, dict) else {}
    one_hour = _num(tokens.get("cache_creation_1h"))
    total_cc = max(_num(tokens.get("cache_creation")),
                   _num(tokens.get("cache_creation_5m")) + one_hour)
    return {
        "input": _num(tokens.get("input")),
        "output": _num(tokens.get("output")),
        "cache_creation_5m": total_cc - one_hour,
        "cache_creation_1h": one_hour,
        "cache_read": _num(tokens.get("cache_read")),
    }


def _band_rate(rate: dict, band: str) -> float | None:
    def f(key):
        value = rate.get(key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    if band == "cache_creation_5m":
        explicit = f("cache_creation_5m")
        if explicit is None:
            explicit = f("cache_creation")
        base = f("input")
        return explicit if explicit is not None else (base * _CACHE_5M_MULTIPLIER if base is not None else None)
    if band == "cache_creation_1h":
        explicit = f("cache_creation_1h")
        base = f("input")
        return explicit if explicit is not None else (base * _CACHE_1H_MULTIPLIER if base is not None else None)
    return f(band)


def price_tokens(model, tokens, rates: dict) -> dict | None:
    rate, match = resolve_rates(model, rates)
    if rate is None:
        return None
    bands = token_bands(tokens)
    by_kind: dict[str, float] = {}
    missing: list[str] = []
    for band in BANDS:
        count = bands[band]
        per_mtok = _band_rate(rate, band)
        if per_mtok is None:
            by_kind[band] = 0.0
            if count:
                missing.append(band)
            continue
        by_kind[band] = count / 1_000_000 * per_mtok
    total = None if missing else sum(by_kind.values())
    return {"total": total, "by_kind": by_kind, "match": match, "missing": missing}


class SpawnRec:
    """One spawn: identity from its spawn_start (or its first complete
    when no start is visible), tokens = the last cumulative value, wall =
    the sum of known run walls, runs[] = one dict per spawn_complete in
    end_ts order. A plain class, not a dataclass: dataclasses need the
    module registered in sys.modules, which SourceFileLoader does not do."""

    def __init__(self, spawn_id: str, agent: str, session_uuid, task_id, start_ts, telemetry_v):
        self.spawn_id = spawn_id
        self.agent = agent
        self.session_uuid = session_uuid
        self.task_id = task_id
        self.start_ts = start_ts
        self.telemetry_v = telemetry_v
        self.model: str | None = None
        self.tokens: dict | None = None
        self.wall_seconds: float | None = None
        self.wall_null_runs = 0
        self.runs: list[dict] = []


def _is_v2(data: dict) -> bool:
    return data.get("telemetry_v") == 2


def _run_from_complete(ev: dict, data: dict) -> dict:
    v2 = _is_v2(data)
    wall = data.get("wall_seconds") if v2 else None
    model = data.get("model")
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else None
    run_tokens = data.get("run_tokens") if v2 and isinstance(data.get("run_tokens"), dict) else None
    if v2 and run_tokens is None and data.get("run_index") == 1:
        run_tokens = tokens
    return {
        "run_index": data.get("run_index") if v2 else None,
        "end_ts": ev.get("ts"),
        "start_ts": data.get("run_start_ts"),
        "wall_seconds": float(wall) if isinstance(wall, (int, float)) and not isinstance(wall, bool) else None,
        "tokens": tokens,
        "run_tokens": run_tokens,
        "model": model if isinstance(model, str) and model not in _UNRESOLVED_MODELS else None,
        "pair_method": data.get("pair_method"),
        "task_id": ev.get("task_id"),
        "qa_result": data.get("qa_result"),
        "qa_blocking_count": data.get("qa_blocking_count"),
        "findings_count": data.get("findings_count") if isinstance(data.get("findings_count"), dict) else None,
        "signed_off": data.get("signed_off"),
        "iteration": data.get("iteration"),
    }


def normalize_hook_spawns(events: list[dict], include_legacy: bool) -> list[SpawnRec]:
    recs: dict[str, SpawnRec] = {}
    legacy_seq = 0
    completes: list[tuple[dict, dict]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        data = ev.get("data")
        if not isinstance(data, dict) or data.get("source") != "hook":
            continue
        if not include_legacy and not _is_v2(data):
            continue
        kind = ev.get("event")
        if kind == "spawn_complete":
            completes.append((ev, data))
            continue
        if kind != "spawn_start":
            continue
        sid = data.get("spawn_id")
        if not sid:
            legacy_seq += 1
            sid = f"__legacy_{legacy_seq}__"
        if sid in recs:
            continue
        recs[sid] = SpawnRec(
            spawn_id=sid,
            agent=ev.get("agent") or "(unknown)",
            session_uuid=data.get("session_uuid"),
            task_id=ev.get("task_id"),
            start_ts=ev.get("ts"),
            telemetry_v=data.get("telemetry_v"),
        )

    for ev, data in completes:
        paired = data.get("paired_spawn_id")
        rec = recs.get(paired) if paired else None
        if rec is None:
            key = paired or data.get("tool_use_id") or data.get("agent_id")
            if not key:
                legacy_seq += 1
                key = f"__legacy_{legacy_seq}__"
            orphan_id = f"orphan:{key}"
            rec = recs.get(orphan_id)
            if rec is None:
                rec = recs[orphan_id] = SpawnRec(
                    spawn_id=orphan_id,
                    agent=ev.get("agent") or "(unknown)",
                    session_uuid=data.get("session_uuid"),
                    task_id=ev.get("task_id"),
                    start_ts=None,
                    telemetry_v=data.get("telemetry_v"),
                )
        rec.runs.append(_run_from_complete(ev, data))
        if rec.agent == "(unknown)" and ev.get("agent"):
            rec.agent = ev["agent"]

    for rec in recs.values():
        rec.runs.sort(key=lambda r: str(r["end_ts"] or ""))
        if rec.task_id is None:
            rec.task_id = next((r["task_id"] for r in rec.runs if r["task_id"]), None)
        known_walls = [r["wall_seconds"] for r in rec.runs if r["wall_seconds"] is not None]
        rec.wall_seconds = sum(known_walls) if known_walls else None
        rec.wall_null_runs = len(rec.runs) - len(known_walls)
        for run in rec.runs:
            if run["tokens"] is not None:
                rec.tokens = run["tokens"]
            if run["model"]:
                rec.model = run["model"]
    return list(recs.values())


def _load_hooks_lib(name: str):
    try:
        path = Path(__file__).resolve().parent.parent / "hooks" / "lib" / f"{name}.py"
        loader = importlib.machinery.SourceFileLoader(f"_telemetry_{name}", str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod
    except Exception:  # any load failure degrades to the unresolved cwd root
        return None


_REPO_ROOT = _load_hooks_lib("repo_root")
_GIT_WORKTREE = _load_hooks_lib("git_worktree")


def primary_root(start) -> Path:
    cwd_root = str(start)
    if _REPO_ROOT is not None:
        try:
            cwd_root = _REPO_ROOT.resolve_agentic_cwd(str(start))
        except Exception:  # resolver failure keeps the given start dir
            cwd_root = str(start)
    if _GIT_WORKTREE is not None:
        try:
            primary = _GIT_WORKTREE.resolve_worktree_primary_root(cwd_root)
        except Exception:  # resolver failure keeps the cwd root
            primary = None
        if primary:
            return Path(primary)
    return Path(cwd_root)


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return str(a) == str(b)


def merge_primary_spawn_rows(cwd_events_path: Path, events: list[dict],
                             primary_events_path: Path | None = None) -> list[dict]:
    if primary_events_path is None:
        primary_events_path = primary_root(cwd_events_path.parent.parent) / ".agentic" / "events.jsonl"
    if _same_file(cwd_events_path, primary_events_path) or not primary_events_path.is_file():
        return events
    merged = list(events)
    try:
        with primary_events_path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(ev, dict) or ev.get("event") not in ("spawn_start", "spawn_complete"):
                    continue
                data = ev.get("data")
                if isinstance(data, dict) and data.get("source") == "hook":
                    merged.append(ev)
    except OSError:
        return events
    return merged
