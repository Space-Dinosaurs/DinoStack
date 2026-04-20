"""Nightly rollup job. Aggregates the previous day's events into a
daily_stats table. Runs via cron at 02:00 UTC."""

import datetime as dt

from infra.metrics import fetch_events_in_window
from infra.db import upsert_daily


def run():
    now = dt.datetime.utcnow()
    # Window: previous calendar day in UTC.
    end = dt.datetime(now.year, now.month, now.day)
    start = end - dt.timedelta(days=1)
    events = fetch_events_in_window(start, end)
    counts = {}
    for e in events:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    upsert_daily(start.date(), counts)
