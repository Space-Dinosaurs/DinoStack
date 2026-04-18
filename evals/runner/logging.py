"""
Purpose: Configure stdlib logging and append structured JSON-lines run records
         to per-component runlog files under evals/results/.

Public API: get_logger(name: str) -> logging.Logger,
            write_runlog(component: str, record: dict) -> None,
            runlog_path(component: str) -> pathlib.Path

Upstream deps: stdlib logging, json, pathlib, datetime.

Downstream consumers: evals.runner.cli, evals.runner.invoker, evals.runner.isolator,
                      evals.runner.aggregator.

Failure modes: write_runlog creates the parent directory if missing; IOError
               propagates to the caller. Not safe for concurrent writers in
               the same process - serialize via the aggregator.

Performance: standard; append-only JSONL, one fsync per line.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def runlog_path(component: str) -> Path:
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return _RESULTS_DIR / f"{component}.runlog.jsonl"


def write_runlog(component: str, record: dict) -> None:
    record = dict(record)
    record.setdefault("ts", datetime.now(timezone.utc).isoformat())
    path = runlog_path(component)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
