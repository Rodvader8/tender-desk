"""Sending an approved quote to an outside system that can fail halfway.

The hard case is a timeout AFTER the other side has applied the request: from here it looks exactly like a request that
never arrived. The rule under test is that nothing is resent blind and nothing is marked sent without the other side's
own record of it (an authoritative readback).
"""

import httpx
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from test_workflow import SCOPE, FakeLLM, good_choices, run

from tender_desk.delivery import DeliveryRejected, PortalClient, deliver, reconcile
from tender_desk.graph import build_graph, decide, submit
from tender_desk.portal import Portal, create_portal_app


class Flaky:
    """Wraps an HTTP client and injects what a network does. `script` has one entry per call, then 'ok' forever.

    timeout_before  the request is lost on the way: the portal never sees it
    timeout_after   the portal applies it, then the response is lost
    503_after       the portal applies it, then a gateway in front answers 503
    """

    def __init__(self, inner, script=()):
        self.inner, self.script, self.calls = inner, list(script), []

    def request(self, method, url, **kw):
        step = self.script.pop(0) if self.script else "ok"
        self.calls.append((method, url.rsplit("/", 1)[-1] if method == "GET" else "submit", step))
        if step == "timeout_before":
            raise httpx.ConnectTimeout("lost on the way")
        resp = self.inner.request(method, url, **kw)
        if step == "timeout_after":
            raise httpx.ReadTimeout("response lost")
        if step == "503_after":
            return httpx.Response(503, text="bad gateway")
        return resp

    def submits(self):
        return [c for c in self.calls if c[1] == "submit"]


@pytest.fixture
def portal():
    return Portal()


def client_for(portal, script=()):
    flaky = Flaky(TestClient(create_portal_app(portal), base_url="http://portal.test"), script)
    return PortalClient(flaky, base_url="http://portal.test"), flaky


def approved_quote(conn):
    """A real approved quote, made by the real workflow (no portal attached, so nothing has been sent yet)."""
    g, tid, cfg, res = run(conn, FakeLLM(SCOPE, [good_choices(conn)]))
    decide(g, cfg, approve=True, by="rod", draft_digest=res["__interrupt__"][0].value["draft_digest"])
    return tid, conn.execute("SELECT id FROM quotes WHERE tender_id=%s", (tid,)).fetchone()[0]


def row(conn, quote_id):
    return conn.execute("SELECT state, reference, attempts, last_error FROM deliveries WHERE quote_id=%s", (quote_id,)).fetchone()


def test_happy_path_sends_once_and_records_the_portals_reference(conn, portal):
    _, qid = approved_quote(conn)
    c, flaky = client_for(portal)
    out = deliver(conn, c, qid)
    assert out["state"] == "sent" and out["reference"].startswith("PRT-")
    assert len(portal.subs) == 1 and len(flaky.submits()) == 1
    assert row(conn, qid)[:3] == ("sent", out["reference"], 1)


def test_response_lost_after_the_portal_applied_it_is_found_by_readback_not_resent(conn, portal):
    _, qid = approved_quote(conn)
    c, flaky = client_for(portal, ["timeout_after"])
    out = deliver(conn, c, qid)
    assert out["state"] == "sent"
    assert len(portal.subs) == 1  # exactly one booking on the other side
    assert len(flaky.submits()) == 1  # and we never sent a second request: we asked what it held instead
    assert [c[1] for c in flaky.calls] == ["submit", conn.execute("SELECT idempotency_key FROM deliveries").fetchone()[0]]


def test_a_gateway_503_after_the_portal_applied_it_is_the_same_story(conn, portal):
    _, qid = approved_quote(conn)
    c, flaky = client_for(portal, ["503_after"])
    assert deliver(conn, c, qid)["state"] == "sent"
    assert len(portal.subs) == 1 and len(flaky.submits()) == 1


def test_request_lost_before_it_arrived_is_retried_after_readback_finds_nothing(conn, portal):
    _, qid = approved_quote(conn)
    c, flaky = client_for(portal, ["timeout_before"])
    out = deliver(conn, c, qid)
    assert out["state"] == "sent" and out["attempts"] == 2
    assert len(portal.subs) == 1 and len(flaky.submits()) == 2  # a retry, but only because the readback came back empty


def test_if_even_the_readback_fails_the_state_is_unknown_never_sent(conn, portal):
    _, qid = approved_quote(conn)
    c, flaky = client_for(portal, ["timeout_after", "timeout_before"])  # submit applied but lost; readback lost too
    out = deliver(conn, c, qid)
    assert out["state"] == "unknown" and out["reference"] is None
    assert len(flaky.submits()) == 1  # no blind resend
    assert len(portal.subs) == 1  # (the portal does hold it; we just can't see that yet)
    events = [
        r[0]
        for r in conn.execute("SELECT event FROM audit_log WHERE tender_id=(SELECT tender_id FROM quotes WHERE id=%s)", (qid,))
    ]
    assert "delivery_unknown" in events
    # later, when the network is back, reconcile reads back and settles it without sending anything
    fixed = reconcile(conn, c, qid)
    assert fixed["state"] == "sent" and fixed["reference"] and len(portal.subs) == 1 and len(flaky.submits()) == 1


def test_a_crash_between_sending_and_recording_is_settled_by_reconcile(conn, portal):
    _, qid = approved_quote(conn)
    c, flaky = client_for(portal)
    key = f"tender-desk:crash:{qid}"
    # our process sent it, the portal applied it, and then the process died before writing 'sent'
    conn.execute(
        "INSERT INTO deliveries (quote_id, tender_id, idempotency_key, state, attempts) "
        "SELECT id, tender_id, %s, 'pending', 1 FROM quotes WHERE id=%s",
        (key, qid),
    )
    q = conn.execute("SELECT tender_id, total, draft_digest FROM quotes WHERE id=%s", (qid,)).fetchone()
    portal.submit(key, {"tender_id": q[0], "quote_id": qid, "total": float(q[1]), "draft_digest": q[2]})
    out = reconcile(conn, c, qid)
    assert out["state"] == "sent" and len(portal.subs) == 1 and flaky.submits() == []


def test_asking_to_deliver_a_sent_quote_again_does_nothing(conn, portal):
    _, qid = approved_quote(conn)
    c, flaky = client_for(portal)
    first = deliver(conn, c, qid)
    again = deliver(conn, c, qid)
    assert again["reference"] == first["reference"] and again["attempts"] == first["attempts"]
    assert len(flaky.calls) == 1 and len(portal.subs) == 1


def test_the_portal_treats_a_repeated_key_as_the_same_request(portal):
    c, _ = client_for(portal)
    payload = {"tender_id": 1, "quote_id": 1, "total": 10.0, "draft_digest": "a" * 64}
    one = c.submit("k1", payload)
    two = c.submit("k1", payload)
    assert one["reference"] == two["reference"] and two["replayed"] is True and len(portal.subs) == 1
    with pytest.raises(DeliveryRejected):  # same key, different content: refused, never silently overwritten
        c.submit("k1", {**payload, "total": 11.0})


def test_a_portal_record_that_does_not_match_what_was_approved_is_a_conflict(conn, portal):
    tid, qid = approved_quote(conn)
    key = f"tender-desk:{tid}:{qid}"
    q = conn.execute("SELECT total, draft_digest FROM quotes WHERE id=%s", (qid,)).fetchone()
    # something else already filed this key with a different total
    portal.submit(key, {"tender_id": tid, "quote_id": qid, "total": float(q[0]) + 100, "draft_digest": q[1]})
    conn.execute(
        "INSERT INTO deliveries (quote_id, tender_id, idempotency_key, state, attempts) VALUES (%s,%s,%s,'unknown',1)",
        (qid, tid, key),
    )
    c, _ = client_for(portal)
    out = reconcile(conn, c, qid)
    assert out["state"] == "conflict" and out["reference"] is None  # a person has to look; it is not called sent


def test_gives_up_after_max_attempts_when_readback_keeps_showing_nothing(conn, portal):
    _, qid = approved_quote(conn)
    c, flaky = client_for(portal, ["timeout_before", "ok"] * 3)  # each lost submit is followed by a readback that finds nothing
    out = deliver(conn, c, qid, max_attempts=3)
    assert out["state"] == "failed" and out["attempts"] == 3 and len(portal.subs) == 0


def test_a_refusal_is_not_retried(conn, portal):
    _, qid = approved_quote(conn)
    portal.refuse_next = True  # the portal answers 422
    c, flaky = client_for(portal)
    out = deliver(conn, c, qid)
    assert out["state"] == "failed" and "422" in out["last_error"] and len(flaky.submits()) == 1


def test_the_workflow_sends_after_approval_and_only_then(conn, portal):
    c, flaky = client_for(portal)
    g = build_graph(FakeLLM(SCOPE, [good_choices(conn), good_choices(conn)]), conn, MemorySaver(), portal=c)
    tid, cfg, res = submit(conn, g, "TEST tender", "Build a rear extension. 10 m3 concrete. 40 hours framing.")
    assert len(flaky.calls) == 0  # nothing leaves the building while it waits for a person
    shown = res["__interrupt__"][0].value["draft_digest"]
    decide(g, cfg, approve=True, by="rod", draft_digest=shown)
    assert len(portal.subs) == 1
    assert conn.execute("SELECT state FROM deliveries WHERE tender_id=%s", (tid,)).fetchone()[0] == "sent"
    # a rejected tender sends nothing
    tid2, cfg2, _ = submit(conn, g, "TEST tender", "Build a rear extension. 10 m3 concrete. 40 hours framing.")
    decide(g, cfg2, approve=False, by="rod")
    assert (
        len(portal.subs) == 1 and conn.execute("SELECT count(*) FROM deliveries WHERE tender_id=%s", (tid2,)).fetchone()[0] == 0
    )


def test_a_delivery_that_ends_unknown_does_not_undo_the_approval(conn, portal):
    c, _ = client_for(portal, ["timeout_after", "timeout_before"])
    g = build_graph(FakeLLM(SCOPE, [good_choices(conn)]), conn, MemorySaver(), portal=c)
    tid, cfg, res = submit(conn, g, "TEST tender", "Build a rear extension. 10 m3 concrete. 40 hours framing.")
    decide(g, cfg, approve=True, by="rod", draft_digest=res["__interrupt__"][0].value["draft_digest"])
    assert conn.execute("SELECT status FROM tenders WHERE id=%s", (tid,)).fetchone()[0] == "approved"
    assert conn.execute("SELECT state FROM deliveries WHERE tender_id=%s", (tid,)).fetchone()[0] == "unknown"
