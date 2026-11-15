"""One deployment, several companies. Each token belongs to one tenant and a tenant can only ever see its own tenders.

An id that belongs to another tenant answers 404, exactly like an id that does not exist, so it is not even confirmed
to be real."""

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from test_api import TENDER
from test_workflow import SCOPE, FakeLLM, good_choices

from tender_desk.api import create_app

A, B = "tenant-a-token-0123456789", "tenant-b-token-9876543210"


def two_tenants(conn, drafts=2, **kw):
    app = create_app(
        llm_factory=lambda: llm,
        conn=conn,
        checkpointer=MemorySaver(),
        api_token=None,
        tenant_tokens={A: "acme", B: "bolt"},
        **kw,
    )
    llm = FakeLLM(SCOPE, [good_choices(conn) for _ in range(drafts)])
    return (
        app,
        TestClient(app, headers={"Authorization": f"Bearer {A}"}),
        TestClient(app, headers={"Authorization": f"Bearer {B}"}),
    )


def test_a_tenant_cannot_read_decide_or_reconcile_another_tenants_tender(conn):
    app, a, b = two_tenants(conn)
    mine = a.post("/tenders", json=TENDER).json()
    tid = mine["id"]
    assert conn.execute("SELECT tenant FROM tenders WHERE id=%s", (tid,)).fetchone()[0] == "acme"
    assert b.get(f"/tenders/{tid}").status_code == 404
    stolen = {"approve": True, "by": "mallory", "draft_digest": mine["draft_digest"]}  # even holding the right digest
    assert b.post(f"/tenders/{tid}/decision", json=stolen).status_code == 404
    assert b.post(f"/tenders/{tid}/delivery/reconcile").status_code == 404
    assert conn.execute("SELECT count(*) FROM quotes WHERE tender_id=%s", (tid,)).fetchone()[0] == 0
    assert a.get(f"/tenders/{tid}").json()["status"] == "awaiting_approval"  # untouched, and still the owner's to decide
    ok = a.post(f"/tenders/{tid}/decision", json={**stolen, "by": "rod"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"


def test_each_tenant_lists_only_its_own_tenders(conn):
    _, a, b = two_tenants(conn)
    ta = a.post("/tenders", json=TENDER).json()["id"]
    tb = b.post("/tenders", json=TENDER).json()["id"]
    assert [t["id"] for t in a.get("/tenders").json() if t["id"] in (ta, tb)] == [ta]
    assert [t["id"] for t in b.get("/tenders").json() if t["id"] in (ta, tb)] == [tb]


def test_every_route_that_takes_a_tender_id_is_scoped(conn):
    """A guard for the future: a new /tenders/{tid} route that forgets the tenant check fails here."""
    app, a, b = two_tenants(conn)
    tid = a.post("/tenders", json=TENDER).json()["id"]
    routes = [r for r in app.routes if getattr(r, "path", "").startswith("/tenders/{tid}")]
    assert len(routes) >= 3
    for r in routes:
        for method in r.methods - {"HEAD", "OPTIONS"}:
            body = (
                {"approve": True, "by": "x", "draft_digest": "0" * 64}
                if method == "POST" and r.path.endswith("decision")
                else None
            )
            resp = b.request(method, r.path.replace("{tid}", str(tid)), json=body)
            assert resp.status_code == 404, f"{method} {r.path} answered {resp.status_code} to the wrong tenant"


def test_unknown_and_missing_tokens_are_refused(conn):
    app, a, _ = two_tenants(conn)
    assert TestClient(app).get("/tenders").status_code == 401
    assert TestClient(app, headers={"Authorization": "Bearer nope"}).get("/tenders").status_code == 401
    assert TestClient(app, headers={"Authorization": f"Bearer {A}x"}).get("/tenders").status_code == 401
    assert a.get("/tenders").status_code == 200


def test_the_rate_limit_is_per_tenant(conn):
    _, a, b = two_tenants(conn, max_tenders_per_minute=1)
    assert a.post("/tenders", json=TENDER).status_code == 201
    assert a.post("/tenders", json=TENDER).status_code == 429  # acme used its allowance...
    assert b.post("/tenders", json=TENDER).status_code == 201  # ...and that did not use up bolt's


def test_weak_or_clashing_tenant_tokens_are_refused_at_start_up(conn):
    def build(tokens):
        return create_app(llm_factory=lambda: None, conn=conn, checkpointer=MemorySaver(), api_token=None, tenant_tokens=tokens)

    with pytest.raises(ValueError, match="at least 16"):
        build({"short": "acme"})
    with pytest.raises(ValueError, match="at least one tenant"):
        build({})
    with pytest.raises(ValueError, match="not both"):
        create_app(llm_factory=lambda: None, conn=conn, checkpointer=MemorySaver(), api_token="x" * 20, tenant_tokens={A: "acme"})
