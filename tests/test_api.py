import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from test_workflow import SCOPE, FakeLLM, good_choices

from tender_desk.api import create_app
from tender_desk.llm import BudgetExceeded

TENDER = {"title": "TEST api tender", "text": "Build a rear extension. 10 m3 concrete. 40 hours framing."}


TOKEN = "test-token-not-a-real-secret"


def client(conn, llm, saver=None, **kw):
    app = create_app(
        llm_factory=lambda: llm, conn=conn, checkpointer=saver or MemorySaver(), api_token=kw.pop("api_token", TOKEN), **kw
    )
    return TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})


def test_full_flow_create_review_approve(conn):
    c = client(conn, FakeLLM(SCOPE, [good_choices(conn)]))
    r = c.post("/tenders", json=TENDER)
    assert r.status_code == 201 and r.json()["status"] == "awaiting_approval" and r.json()["draft"]["total"] > 0
    tid = r.json()["id"]
    assert tid in [t["id"] for t in c.get("/tenders").json()]
    detail = c.get(f"/tenders/{tid}").json()
    assert detail["draft"] and detail["quote"] is None
    d = c.post(f"/tenders/{tid}/decision", json={"approve": True, "by": "rod"})
    assert d.status_code == 200 and d.json()["status"] == "approved"
    after = c.get(f"/tenders/{tid}").json()
    assert after["draft"] is None and after["quote"]["status"] == "approved" and after["quote"]["decided_by"] == "rod"
    assert [a["event"] for a in after["audit"]][-1] == "finalized"
    assert c.post(f"/tenders/{tid}/decision", json={"approve": True, "by": "rod"}).status_code == 409


def test_bad_input_and_unknown_tender(conn):
    c = client(conn, FakeLLM(SCOPE, []))
    assert c.post("/tenders", json={"title": "TEST x", "text": "short"}).status_code == 422
    assert c.post("/tenders", json={"title": "", "text": "x" * 50}).status_code == 422
    assert c.post("/tenders", json={"title": "TEST big", "text": "x" * 20001}).status_code == 422
    assert c.get("/tenders/999999").status_code == 404
    assert c.post("/tenders/999999/decision", json={"approve": True, "by": "rod"}).status_code == 404


def test_reject_with_notes_returns_a_revised_draft_waiting(conn):
    c = client(conn, FakeLLM(SCOPE, [good_choices(conn), good_choices(conn)]))
    tid = c.post("/tenders", json=TENDER).json()["id"]
    d = c.post(f"/tenders/{tid}/decision", json={"approve": False, "by": "rod", "notes": "use 32MPa"}).json()
    assert d["status"] == "awaiting_approval" and d["draft"]
    final = c.post(f"/tenders/{tid}/decision", json={"approve": False, "by": "rod"}).json()
    assert final["status"] == "rejected"


class Exploding:
    def __init__(self, exc):
        self.exc = exc

    def structured(self, *a, **k):
        raise self.exc


def test_spend_limit_gives_503_and_marks_the_tender(conn):
    c = client(conn, Exploding(BudgetExceeded("Run cap reached: $0.25 of $0.25")))
    r = c.post("/tenders", json=TENDER)
    assert r.status_code == 503 and "spend limit" in r.json()["detail"]
    tid = conn.execute("SELECT id FROM tenders WHERE title='TEST api tender' ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert c.get(f"/tenders/{tid}").json()["status"] == "stopped_by_spend_limit"


def test_unexpected_errors_do_not_leak_details(conn):
    c = client(conn, Exploding(RuntimeError("secret internals dummy-token-xyz")))
    r = c.post("/tenders", json=TENDER)
    assert r.status_code == 500 and "secret" not in r.text and "dummy-token" not in r.text


def test_security_headers_and_no_unsafe_html_in_the_screen(conn):
    c = client(conn, FakeLLM(SCOPE, []))
    for path in ("/", "/health"):
        h = c.get(path).headers
        assert "default-src 'self'" in h["content-security-policy"] and h["x-content-type-options"] == "nosniff"
    static = Path(__file__).parents[1] / "src" / "tender_desk" / "static"
    js = (static / "app.js").read_text()
    assert "innerHTML" not in js.replace("never innerHTML", "") and "eval(" not in js and "document.write" not in js
    assert 'style="' not in (static / "index.html").read_text()


def test_paused_quote_survives_a_server_restart(conn):
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    from tender_desk.db import DSN

    def saver():
        pool = ConnectionPool(
            DSN, min_size=1, max_size=3, kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}, open=True
        )
        s = PostgresSaver(pool)
        s.setup()
        return s, pool

    s1, pool1 = saver()
    tid = client(conn, FakeLLM(SCOPE, [good_choices(conn)]), s1).post("/tenders", json=TENDER).json()["id"]
    pool1.close()  # the first server is gone
    s2, pool2 = saver()  # a new process: new pool, new graph, nothing in memory
    c2 = client(conn, FakeLLM(SCOPE, []), s2)
    try:
        assert c2.get(f"/tenders/{tid}").json()["draft"]["total"] > 0
        assert c2.post(f"/tenders/{tid}/decision", json={"approve": True, "by": "rod"}).json()["status"] == "approved"
    finally:
        thread = f"tender-{tid}"
        for t in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            conn.execute(f"DELETE FROM {t} WHERE thread_id=%s", (thread,))
        pool2.close()


def test_routes_need_the_token_but_health_and_the_screen_do_not(conn):
    c = client(conn, FakeLLM(SCOPE, []))
    bare = TestClient(c.app)  # no Authorization header
    assert bare.get("/health").status_code == 200 and bare.get("/").status_code == 200
    for method, path in [("get", "/tenders"), ("post", "/tenders"), ("get", "/tenders/1"), ("post", "/tenders/1/decision")]:
        r = getattr(bare, method)(path)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer", (method, path)
    wrong = TestClient(c.app, headers={"Authorization": "Bearer nope"})
    assert wrong.get("/tenders").status_code == 401
    assert TestClient(c.app, headers={"Authorization": f"Token {TOKEN}"}).get("/tenders").status_code == 401  # wrong scheme
    assert c.get("/tenders").status_code == 200


def test_a_wrong_token_never_reaches_the_workflow_or_spends_anything(conn):
    llm = FakeLLM(SCOPE, [])
    wrong = TestClient(client(conn, llm).app, headers={"Authorization": "Bearer nope"})
    assert wrong.post("/tenders", json=TENDER).status_code == 401 and llm.prompts == []


def test_it_refuses_to_exist_without_a_token_unless_told_to(conn):
    with pytest.raises(ValueError, match="api_token is required"):
        create_app(llm_factory=lambda: None, conn=conn, checkpointer=MemorySaver(), api_token=None)
    open_app = create_app(llm_factory=lambda: None, conn=conn, checkpointer=MemorySaver(), api_token=None, allow_no_auth=True)
    assert TestClient(open_app).get("/tenders").status_code == 200


def test_default_app_will_not_start_without_a_token(monkeypatch):
    from tender_desk.api import build_default_app

    monkeypatch.delenv("TENDER_DESK_API_TOKEN", raising=False)
    monkeypatch.delenv("TENDER_DESK_ALLOW_NO_AUTH", raising=False)
    with pytest.raises(RuntimeError, match="TENDER_DESK_API_TOKEN"):
        build_default_app()


def test_creating_tenders_is_rate_limited(conn):
    c = client(conn, FakeLLM(SCOPE, [good_choices(conn), good_choices(conn), good_choices(conn)]), max_tenders_per_minute=2)
    assert c.post("/tenders", json=TENDER).status_code == 201 and c.post("/tenders", json=TENDER).status_code == 201
    third = c.post("/tenders", json=TENDER)
    assert third.status_code == 429 and int(third.headers["retry-after"]) >= 1
    assert c.get("/tenders").status_code == 200  # reading is not limited


def test_rate_limiter_window_slides():
    from tender_desk.security import RateLimiter

    now = [0.0]
    rl = RateLimiter(2, 60, clock=lambda: now[0])
    rl.check()
    rl.check()
    with pytest.raises(HTTPException) as e:
        rl.check()
    assert e.value.status_code == 429
    now[0] = 61
    rl.check()  # the first two have aged out


def test_logs_are_json_with_a_request_id_and_never_contain_the_token_or_tender_text(conn, caplog):
    import json as _json
    import logging

    from tender_desk.observability import JsonFormatter

    c = client(conn, FakeLLM(SCOPE, [good_choices(conn)]))
    secret_text = "UNIQUE-TENDER-WORDS-12345 " + TENDER["text"]
    with caplog.at_level(logging.INFO, logger="tender_desk.api"):
        r = c.post("/tenders", json={"title": "TEST logs", "text": secret_text}, headers={"X-Request-ID": "abc-123"})
    assert r.status_code == 201 and r.headers["x-request-id"] == "abc-123"
    lines = [_json.loads(JsonFormatter().format(rec)) for rec in caplog.records if rec.name == "tender_desk.api"]
    req = next(ln for ln in lines if ln["msg"] == "request")
    assert req["request_id"] == "abc-123" and req["route"] == "/tenders" and req["status"] == 201 and req["method"] == "POST"
    blob = _json.dumps(lines)
    assert TOKEN not in blob and "UNIQUE-TENDER-WORDS" not in blob and "Authorization" not in blob


def test_a_forged_request_id_is_replaced(conn):
    c = client(conn, FakeLLM(SCOPE, []))
    r = c.get("/health", headers={"X-Request-ID": 'x"}\n{"level":"CRITICAL"'})
    assert re.fullmatch(r"[0-9a-f]{12}", r.headers["x-request-id"])


def test_metrics_endpoint_needs_the_token_and_counts_calls_cost_and_steps(conn):
    c = client(conn, FakeLLM(SCOPE, [good_choices(conn)]))
    assert TestClient(c.app).get("/metrics").status_code == 401
    c.post("/tenders", json=TENDER)
    text = c.get("/metrics").text
    assert 'tender_http_requests_total{method="POST",route="/tenders",status="201"}' in text
    assert (
        'tender_workflow_step_seconds_count{step="extract"}' in text and 'tender_workflow_events_total{event="created"}' in text
    )
    assert "UNIQUE" not in text and TOKEN not in text


def test_model_calls_are_recorded_with_cost_and_latency(tmp_path):
    import httpx

    from tender_desk.llm import LLM, Ledger
    from tender_desk.observability import REGISTRY

    def handler(req):
        if req.url.path.endswith(("/key", "/credits")):
            return httpx.Response(200, json={"data": {"limit_remaining": 50, "total_credits": 110, "total_usage": 10}})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "hi"}}], "usage": {"total_tokens": 12, "cost": 0.0042}}
        )

    llm = LLM(
        model="metric-test-model",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        ledger=Ledger(tmp_path / "l.jsonl"),
        key="dummy-key-for-tests-only",
    )
    llm.chat([{"role": "user", "content": "x"}], purpose="metric-test")
    assert REGISTRY.get_sample_value(
        "tender_llm_cost_usd_total", {"model": "metric-test-model", "purpose": "metric-test"}
    ) == pytest.approx(0.0042)
    assert REGISTRY.get_sample_value("tender_llm_calls_total", {"model": "metric-test-model", "purpose": "metric-test"}) == 1
    assert (
        REGISTRY.get_sample_value("tender_llm_call_seconds_count", {"model": "metric-test-model", "purpose": "metric-test"}) == 1
    )
