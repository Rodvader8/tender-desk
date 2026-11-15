"""A stand-in for the outside system an approved quote is sent to (a client or supplier portal).

It keeps what it receives in memory and behaves the way a well-built API should: a request carries an Idempotency-Key,
repeating a key with the same content returns the original receipt, repeating it with different content is refused, and
GET /submissions/{key} says what it holds for a key. That last one is what the sender uses to find out what really
happened after a timeout.

  uv run tender-portal        # 127.0.0.1:8100, then set TENDER_DESK_PORTAL_URL=http://127.0.0.1:8100
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, Response
from pydantic import BaseModel, Field


class QuotePayload(BaseModel):
    tender_id: int
    quote_id: int
    total: float
    draft_digest: str = Field(min_length=64, max_length=64)


class Portal:
    def __init__(self) -> None:
        self.subs: dict[str, dict[str, Any]] = {}
        self.refuse_next = False  # tests and demos: answer the next submission with a 422

    def submit(self, key: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if self.refuse_next:
            self.refuse_next = False
            return 422, {"detail": "refused"}
        held = self.subs.get(key)
        if held is None:
            self.subs[key] = {**payload, "reference": f"PRT-{len(self.subs) + 1:04d}"}
            return 201, {**self.subs[key], "replayed": False}
        if {k: held[k] for k in payload} == payload:
            return 200, {**held, "replayed": True}
        return 409, {"detail": "this key was already used with different content"}

    def lookup(self, key: str) -> dict[str, Any] | None:
        return self.subs.get(key)


def create_portal_app(portal: Portal | None = None) -> FastAPI:
    portal = portal or Portal()
    app = FastAPI(title="Quote portal (stand-in)")

    @app.post("/submissions")
    def submit(body: QuotePayload, response: Response, idempotency_key: str = Header(min_length=1, max_length=200)):
        status, out = portal.submit(idempotency_key, body.model_dump())
        response.status_code = status
        return out

    @app.get("/submissions/{key}")
    def lookup(key: str, response: Response):
        held = portal.lookup(key)
        if held is None:
            response.status_code = 404
            return {"detail": "nothing held for this key"}
        return held

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(create_portal_app(), host="127.0.0.1", port=8100)
