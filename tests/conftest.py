import pytest

from tender_desk.db import connect


@pytest.fixture
def conn():
    try:
        c = connect()
    except Exception:
        pytest.skip("local database not running (docker compose up -d)")
    yield c
    ids = [r[0] for r in c.execute("SELECT id FROM tenders WHERE title LIKE 'TEST %'").fetchall()]
    for t in ids:
        c.execute("DELETE FROM audit_log WHERE tender_id=%s", (t,))
        c.execute("DELETE FROM run_steps WHERE tender_id=%s", (t,))
        c.execute("DELETE FROM deliveries WHERE tender_id=%s", (t,))
        c.execute("DELETE FROM quotes WHERE tender_id=%s", (t,))
        c.execute("DELETE FROM tenders WHERE id=%s", (t,))
