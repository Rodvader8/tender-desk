"""Cost and latency per task: every workflow step is recorded against its tender, so one tender's whole run can be read back."""

import logging
from types import SimpleNamespace

from langgraph.checkpoint.memory import MemorySaver
from test_api import TENDER, Exploding, client
from test_workflow import SCOPE, FakeLLM, good_choices

from tender_desk.graph import build_graph, decide, submit


class CostedLLM(FakeLLM):
    """A FakeLLM that bills 0.1 cent per call, through the same guard fields the real client keeps."""

    def __init__(self, *a):
        super().__init__(*a)
        self.guard = SimpleNamespace(run_spent=0.0, calls=0)

    def structured(self, messages, cls, **kw):
        self.guard.run_spent += 0.001
        self.guard.calls += 1
        return super().structured(messages, cls, **kw)


def steps(conn, tid):
    return conn.execute(
        "SELECT step, ms, cost_usd, llm_calls, error FROM run_steps WHERE tender_id=%s ORDER BY id", (tid,)
    ).fetchall()


def test_each_step_is_recorded_with_its_own_time_and_cost(conn):
    g = build_graph(CostedLLM(SCOPE, [good_choices(conn)]), conn, MemorySaver())
    tid, cfg, res = submit(conn, g, "TEST tender", "Build a rear extension. 10 m3 concrete. 40 hours framing.")
    assert [s[0] for s in steps(conn, tid)] == [
        "redact",
        "extract",
        "retrieve",
        "estimate",
        "build_draft",
    ]  # the wait for a person is not a step
    by_step = {s[0]: s for s in steps(conn, tid)}
    assert float(by_step["extract"][2]) == 0.001 and by_step["extract"][3] == 1
    assert float(by_step["estimate"][2]) == 0.001 and by_step["estimate"][3] == 1
    assert float(by_step["retrieve"][2]) == 0 and float(by_step["build_draft"][2]) == 0  # code steps cost nothing
    assert all(s[1] >= 0 and s[4] is None for s in steps(conn, tid))
    decide(g, cfg, approve=True, by="rod", draft_digest=res["__interrupt__"][0].value["draft_digest"])
    assert [s[0] for s in steps(conn, tid)][-2:] == ["finalize", "send_quote"]


def test_a_revision_shows_up_as_extra_estimate_steps_and_extra_cost(conn):
    g = build_graph(CostedLLM(SCOPE, [good_choices(conn), good_choices(conn)]), conn, MemorySaver())
    tid, cfg, _ = submit(conn, g, "TEST tender", "Build a rear extension. 10 m3 concrete. 40 hours framing.")
    decide(g, cfg, approve=False, by="rod", notes="use 32MPa")
    names = [s[0] for s in steps(conn, tid)]
    assert (
        names.count("estimate") == 2
        and names.count("build_draft") == 2
        and names.count("extract") == 1
        and names.count("redact") == 1
    )
    assert round(sum(float(s[2]) for s in steps(conn, tid)), 6) == 0.003


def test_the_api_reports_the_run_for_one_tender(conn):
    c = client(conn, CostedLLM(SCOPE, [good_choices(conn)]))
    first = c.post("/tenders", json=TENDER).json()
    run = c.get(f"/tenders/{first['id']}").json()["run"]
    assert run["cost_usd"] == 0.002 and run["llm_calls"] == 2 and run["ms"] >= 0
    assert [s["step"] for s in run["steps"]] == ["redact", "extract", "retrieve", "estimate", "build_draft"]


def test_a_failing_step_is_recorded_with_its_error_type_and_no_message(conn):
    c = client(conn, Exploding(RuntimeError("secret internals dummy-token-xyz")))
    assert c.post("/tenders", json=TENDER).status_code == 500
    tid = conn.execute("SELECT id FROM tenders WHERE title='TEST api tender' ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert [(s[0], s[4]) for s in steps(conn, tid)] == [
        ("redact", None),
        ("extract", "RuntimeError"),
    ]  # the type, never the message (it can hold data)
    assert "secret" not in str(c.get(f"/tenders/{tid}").json())


def test_step_log_lines_carry_the_tender_id_for_correlation(conn, caplog):
    with caplog.at_level(logging.INFO, logger="tender_desk.graph"):
        g = build_graph(CostedLLM(SCOPE, [good_choices(conn)]), conn, MemorySaver())
        tid, _, _ = submit(conn, g, "TEST tender", "Build a rear extension. 10 m3 concrete. 40 hours framing.")
    recs = [r for r in caplog.records if r.getMessage() == "step"]
    assert [r.step for r in recs] == ["redact", "extract", "retrieve", "estimate", "build_draft"]
    assert all(r.tender_id == tid for r in recs)
