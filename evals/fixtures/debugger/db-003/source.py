"""Async token bucket with periodic refill.

Two callers may trigger refill concurrently via allow(); the intent was
that only one refill runs at a time. An asyncio.Lock was added around
the refill section during code review but there are reports of intermittent
burst-through where more requests pass than the budget allows.
"""
import asyncio
import time


class TokenBucket:
    def __init__(self, capacity: int, refill_rate_per_sec: float):
        self.capacity = capacity
        self.refill_rate = refill_rate_per_sec
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def _refill(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            added = elapsed * self.refill_rate
            self.tokens = min(self.capacity, self.tokens + added)
            self.last_refill = now

    async def allow(self, cost: int = 1) -> bool:
        # Refill happens outside the lock protecting the decrement below.
        await self._refill()
        # The read of self.tokens and the decrement are not inside the
        # same critical section as the refill; two concurrent coroutines
        # can both observe tokens >= cost, both decrement, and the net
        # consumption exceeds capacity within a refill window.
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False
