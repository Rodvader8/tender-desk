"""The same failure over a real socket, so the injected-fault tests above are not the only evidence.

A real portal runs in a thread on a real port. It applies the first request and then stalls longer than the client's
timeout, which is what a slow or overloaded supplier system does.
"""

import socket
import threading
import time

import httpx
import pytest
import uvicorn
from test_delivery import approved_quote

from tender_desk.delivery import PortalClient, deliver
from tender_desk.portal import Portal, create_portal_app


class StallsAfterApplyingOnce(Portal):
    def __init__(self):
        super().__init__()
        self.stalled = False

    def submit(self, key, payload):
        out = super().submit(key, payload)
        if not self.stalled:
            self.stalled = True
            time.sleep(1.0)  # applied, but the answer comes back after the client has given up
        return out


@pytest.fixture
def live_portal():
    portal = StallsAfterApplyingOnce()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_portal_app(portal), host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield portal, f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(timeout=5)


def test_a_real_timeout_after_the_portal_applied_the_request_is_settled_by_readback(conn, live_portal):
    portal, url = live_portal
    _, qid = approved_quote(conn)
    client = PortalClient(httpx.Client(timeout=0.3), base_url=url)
    out = deliver(conn, client, qid)
    assert out["state"] == "sent" and out["reference"] == "PRT-0001"
    assert len(portal.subs) == 1 and out["attempts"] == 1  # one booking, and no second request was ever made
