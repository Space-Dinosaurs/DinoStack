# src/workers/rates.py (relevant excerpt)
# Invoked from the asyncio scheduler in src/workers/scheduler.py every 60s.

import requests
import asyncio
from src.db.session import get_session
from src.rates.models import Rate

SYMBOLS = ["USD", "EUR", "JPY", "GBP"]
RATE_API = "https://api.example-fx.io/v1/latest"


def _fetch_symbol(symbol: str) -> dict:
    # BLOCKING: requests.get is synchronous, but refresh_rates() is
    # awaited from the asyncio scheduler loop.
    resp = requests.get(RATE_API, params={"base": symbol}, timeout=5)
    resp.raise_for_status()
    return resp.json()


async def refresh_rates():
    updates = []
    for sym in SYMBOLS:
        data = _fetch_symbol(sym)
        updates.append((sym, data["rate"]))
    commit_rates(updates)


def commit_rates(updates):
    session = get_session()
    for sym, rate in updates:
        session.merge(Rate(symbol=sym, value=rate))
    session.commit()
