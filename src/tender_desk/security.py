"""API token check and a request limiter. Both exist to protect the model spend, not just the data."""

from __future__ import annotations

import hmac
import time
from collections import deque
from collections.abc import Callable

from fastapi import Header, HTTPException


def make_tenant_auth(tokens: dict[str, str] | None) -> Callable[..., str]:
    """Bearer-token dependency that returns the caller's tenant. `tokens` maps each token to its tenant.
    tokens=None means authentication is deliberately switched off (local development only): everyone is 'default'."""

    def auth(authorization: str | None = Header(default=None)) -> str:
        if tokens is None:
            return "default"
        supplied = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else ""
        found = None
        for token, tenant in tokens.items():  # no early exit, and each comparison is constant-time, so timing says nothing
            if hmac.compare_digest(supplied.encode(), token.encode()):
                found = tenant
        if found is None:
            raise HTTPException(401, "Missing or wrong API token", headers={"WWW-Authenticate": "Bearer"})
        return found

    return auth


def make_auth(token: str | None) -> Callable[..., str]:
    """One shared token, one tenant ('default'). token=None switches authentication off (local development only)."""
    return make_tenant_auth(None if token is None else {token: "default"})


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
