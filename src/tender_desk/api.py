"""HTTP API and approval screen.

Every /tenders route needs `Authorization: Bearer <TENDER_DESK_API_TOKEN>`. The server refuses to start without a token unless
TENDER_DESK_ALLOW_NO_AUTH=1 (local development). Creating tenders is rate limited because each one spends money on a model.
There is one shared token and no user accounts: the reviewer name is typed in, not authenticated.
Everything shown on the screen is untrusted text (tender text, model output) and is rendered as text, never as HTML.

  uv run uvicorn tender_desk.api:build_default_app --factory --port 8000
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from .graph import audit, build_graph, create_tender, decide, start
from .llm import LLM, BudgetExceeded
from .observability import HTTP_REQUESTS, HTTP_SECONDS, REGISTRY, TENDERS, configure_logging
from .security import RateLimiter, make_auth

STATIC = Path(__file__).parent / "static"
log = logging.getLogger("tender_desk.api")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")  # an incoming id is only echoed if it is plain, so it cannot forge log lines


class TenderIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=20, max_length=20000)


class DecisionIn(BaseModel):
    approve: bool
    by: str = Field(min_length=1, max_length=80)
    notes: str = Field("", max_length=2000)


def create_app(
    *,
    llm_factory: Callable[[], object],
    conn,
    checkpointer,
    api_token: str | None,
    allow_no_auth: bool = False,
    max_tenders_per_minute: int = 10,
) -> FastAPI:
    if api_token is None and not allow_no_auth:
        raise ValueError("api_token is required (pass allow_no_auth=True only for local development)")
    app = FastAPI(title="Tender Desk", version="0.1.0")
    auth = Depends(make_auth(api_token))
    limiter = RateLimiter(max_tenders_per_minute)

    def graph():
        # a fresh LLM per request, so each tender gets its own per-run spend cap
        return build_graph(llm_factory(), conn, checkpointer)

    def pending_draft(g, cfg):
        for task in g.get_state(cfg).tasks:
            for intr in task.interrupts:
                return intr.value["draft"]
        return None

    def tender_row(tid: int):
        r = conn.execute("SELECT id, title, status, created_at FROM tenders WHERE id=%s", (tid,)).fetchone()
        if not r:
            raise HTTPException(404, "No such tender")
        return {"id": r[0], "title": r[1], "status": r[2], "created_at": r[3].isoformat()}

    def guarded(tid: int, fn):
        try:
            return fn()
        except BudgetExceeded as e:
            conn.execute("UPDATE tenders SET status='stopped_by_spend_limit' WHERE id=%s", (tid,))
            audit(conn, tid, "stopped", reason=str(e))
            TENDERS.labels("stopped").inc()
            log.warning("tender_stopped_by_spend_limit", extra={"tender_id": tid})
            raise HTTPException(503, f"Stopped by spend limit: {e}") from e
        except HTTPException:
            raise
        except Exception as e:  # never leak internals or keys to the browser
            conn.execute("UPDATE tenders SET status='failed' WHERE id=%s", (tid,))
            audit(conn, tid, "error", type=type(e).__name__)
            TENDERS.labels("failed").inc()
            log.error("tender_failed", extra={"tender_id": tid, "error_type": type(e).__name__})
            raise HTTPException(500, "The workflow failed. See the audit log.") from e

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def observe(request: Request, call_next):
        given = request.headers.get("x-request-id", "")
        rid = given if _REQUEST_ID.match(given) else uuid.uuid4().hex[:12]
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            route = getattr(request.scope.get("route"), "path", "unmatched")
            took = time.perf_counter() - started
            HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
            HTTP_SECONDS.labels(route).observe(took)
            # method, route template, status, timing and an id. Never headers, bodies or query strings.
            log.info(
                "request",
                extra={
                    "request_id": rid,
                    "method": request.method,
                    "route": route,
                    "status": status,
                    "ms": round(took * 1000, 1),
                },
            )

    @app.middleware("http")
    async def security_headers(request, call_next):
        r = await call_next(request)
        r.headers["Content-Security-Policy"] = "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["Referrer-Policy"] = "no-referrer"
        return r

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/metrics", dependencies=[auth], include_in_schema=False)
    def metrics():
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    @app.get("/health")
    def health():
        conn.execute("SELECT 1")
        return {"ok": True}

    @app.get("/tenders", dependencies=[auth])
    def list_tenders():
        rows = conn.execute(
            "SELECT t.id, t.title, t.status, t.created_at, q.total FROM tenders t "
            "LEFT JOIN LATERAL (SELECT total FROM quotes WHERE tender_id=t.id ORDER BY id DESC LIMIT 1) q ON true "
            "ORDER BY t.id DESC LIMIT 50"
        ).fetchall()
        return [
            {
                "id": r[0],
                "title": r[1],
                "status": r[2],
                "created_at": r[3].isoformat(),
                "total": float(r[4]) if r[4] is not None else None,
            }
            for r in rows
        ]

    @app.post("/tenders", status_code=201, dependencies=[auth])
    def create(body: TenderIn):
        limiter.check()
        tid = create_tender(conn, body.title, body.text)
        TENDERS.labels("created").inc()
        _, res = guarded(tid, lambda: start(graph(), tid, body.text))
        return {**tender_row(tid), "draft": res["__interrupt__"][0].value["draft"]}

    @app.get("/tenders/{tid}", dependencies=[auth])
    def get_tender(tid: int):
        t = tender_row(tid)
        cfg = {"configurable": {"thread_id": f"tender-{tid}"}}
        quote = conn.execute(
            "SELECT draft, total, status, decided_by, notes, decided_at FROM quotes WHERE tender_id=%s ORDER BY id DESC LIMIT 1",
            (tid,),
        ).fetchone()
        trail = conn.execute("SELECT at, event, detail FROM audit_log WHERE tender_id=%s ORDER BY id", (tid,)).fetchall()
        return {
            **t,
            "draft": pending_draft(graph(), cfg) if t["status"] == "awaiting_approval" else None,
            "quote": None
            if not quote
            else {
                "draft": quote[0],
                "total": float(quote[1]),
                "status": quote[2],
                "decided_by": quote[3],
                "notes": quote[4],
                "decided_at": quote[5].isoformat(),
            },
            "audit": [{"at": a[0].isoformat(), "event": a[1], "detail": a[2]} for a in trail],
        }

    @app.post("/tenders/{tid}/decision", dependencies=[auth])
    def decision(tid: int, body: DecisionIn):
        t = tender_row(tid)
        if t["status"] != "awaiting_approval":
            raise HTTPException(409, f"This tender is {t['status']}, not awaiting approval")
        cfg = {"configurable": {"thread_id": f"tender-{tid}"}}
        res = guarded(tid, lambda: decide(graph(), cfg, body.approve, body.by.strip(), body.notes.strip()))
        TENDERS.labels("approved" if body.approve else "rejected").inc()
        log.info("tender_decision", extra={"tender_id": tid, "approved": body.approve})
        out = tender_row(tid)
        if "__interrupt__" in res:  # rejected with notes: a revised draft is waiting
            out["draft"] = res["__interrupt__"][0].value["draft"]
        return out

    return app


def build_default_app() -> FastAPI:
    import os

    configure_logging()
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg import Connection
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    from .db import DSN, connect

    token = os.environ.get("TENDER_DESK_API_TOKEN") or None
    allow_no_auth = os.environ.get("TENDER_DESK_ALLOW_NO_AUTH") == "1"
    if token is None and not allow_no_auth:
        raise RuntimeError(
            "Set TENDER_DESK_API_TOKEN (any long random string). For local development only: TENDER_DESK_ALLOW_NO_AUTH=1."
        )

    pool: ConnectionPool[Connection[dict[str, Any]]] = ConnectionPool(
        DSN, min_size=1, max_size=5, kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}, open=True
    )
    saver = PostgresSaver(pool)
    saver.setup()
    return create_app(
        llm_factory=LLM,
        conn=connect(),
        checkpointer=saver,
        api_token=token,
        allow_no_auth=allow_no_auth,
        max_tenders_per_minute=int(os.environ.get("TENDER_DESK_MAX_TENDERS_PER_MIN", "10")),
    )
