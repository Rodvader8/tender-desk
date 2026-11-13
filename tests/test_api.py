from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from test_workflow import SCOPE, FakeLLM, good_choices
from tender_desk.api import create_app
from tender_desk.llm import BudgetExceeded

TENDER = {"title": "TEST api tender", "text": "Build a rear extension. 10 m3 concrete. 40 hours framing."}


def client(conn, llm, saver=None):
    return TestClient(create_app(llm_factory=lambda: llm, conn=conn, checkpointer=saver or MemorySaver()))


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
    def __init__(self, exc): self.exc = exc
    def structured(self, *a, **k): raise self.exc


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
        pool = ConnectionPool(DSN, min_size=1, max_size=3, kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}, open=True)
        s = PostgresSaver(pool); s.setup(); return s, pool

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
