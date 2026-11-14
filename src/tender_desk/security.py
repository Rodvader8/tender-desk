"""API token check and a request limiter. Both exist to protect the model spend, not just the data."""

from __future__ import annotations

import hmac
import time
from collections import deque
from collections.abc import Callable

from fastapi import Header, HTTPException


def make_auth(token: str | None) -> Callable[..., None]:
    """Bearer-token dependency. token=None means authentication is deliberately switched off (local development only)."""

    def auth(authorization: str | None = Header(default=None)) -> None:
        if token is None:
            return
        supplied = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else ""
        # constant-time comparison, so the check does not leak how much of a guess was right
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(401, "Missing or wrong API token", headers={"WWW-Authenticate": "Bearer"})

    return auth


class RateLimiter:
    """At most `limit` calls in any `window` seconds. Single process, in memory: fine for one instance."""

    def __init__(self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self.calls: deque[float] = deque()

    def check(self) -> None:
        now = self.clock()
        while self.calls and now - self.calls[0] >= self.window:
            self.calls.popleft()
        if len(self.calls) >= self.limit:
            wait = int(self.window - (now - self.calls[0])) + 1
            raise HTTPException(429, "Too many tenders submitted, slow down", headers={"Retry-After": str(wait)})
        self.calls.append(now)
