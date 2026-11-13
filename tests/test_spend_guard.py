import json
import httpx
import pytest

from tender_desk.llm import LLM, BudgetExceeded, Ledger, Limits

SECRET = "dummy-key-for-tests-only"


def fake_api(cost=0.01, account_remaining=100.0, key_remaining=50.0, calls=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(req.url.path)
        if req.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"limit_remaining": key_remaining, "usage_monthly": 1, "usage": 2}})
        if req.url.path.endswith("/credits"):
            return httpx.Response(200, json={"data": {"total_credits": account_remaining + 10, "total_usage": 10}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}],
                                         "usage": {"total_tokens": 100, "cost": cost}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def make(tmp_path, **kw):
    limits = kw.pop("limits", Limits(project_cap=5, run_cap=0.25, account_floor=20, key_floor=8))
    return LLM(model="m", limits=limits, client=fake_api(**kw), ledger=Ledger(tmp_path / "l.jsonl"), key=SECRET)


def test_records_cost_and_never_writes_the_key(tmp_path):
    llm = make(tmp_path)
    llm.chat([{"role": "user", "content": "x"}])
    ledger_text = (tmp_path / "l.jsonl").read_text()
    assert json.loads(ledger_text)["cost"] == 0.01
    assert SECRET not in ledger_text


def test_run_cap_stops_a_loop(tmp_path):
    llm = make(tmp_path, cost=0.1)
    with pytest.raises(BudgetExceeded, match="Run cap"):
        for _ in range(10):
            llm.chat([{"role": "user", "content": "x"}])
    assert llm.guard.calls == 3  # 0.1 x 3 >= 0.25, so the 4th call is refused


def test_project_cap_is_shared_across_runs(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(model="m", cost=4.99, tokens=1, purpose="earlier")
    llm = LLM(model="m", limits=Limits(project_cap=5, run_cap=10, account_floor=20, key_floor=8),
              client=fake_api(cost=0.02), ledger=ledger, key=SECRET)
    llm.chat([{"role": "user", "content": "x"}])
    with pytest.raises(BudgetExceeded, match="Project cap"):
        llm.chat([{"role": "user", "content": "x"}])


def test_account_floor_protects_other_tools(tmp_path):
    llm = make(tmp_path, account_remaining=19.99)
    with pytest.raises(BudgetExceeded, match="Account balance"):
        llm.chat([{"role": "user", "content": "x"}])
    assert llm.guard.calls == 0  # refused before any model call


def test_key_floor(tmp_path):
    llm = make(tmp_path, key_remaining=7.5)
    with pytest.raises(BudgetExceeded, match="Key limit"):
        llm.chat([{"role": "user", "content": "x"}])


def test_missing_cost_falls_back_to_pessimistic_estimate(tmp_path):
    def handler(req):
        if req.url.path.endswith(("/key", "/credits")):
            return httpx.Response(200, json={"data": {"limit_remaining": 50, "total_credits": 110, "total_usage": 10}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}], "usage": {"total_tokens": 1000}})
    llm = LLM(model="m", limits=Limits(), client=httpx.Client(transport=httpx.MockTransport(handler)),
              ledger=Ledger(tmp_path / "l.jsonl"), key=SECRET)
    out = llm.chat([{"role": "user", "content": "x"}])
    assert out["cost"] == pytest.approx(0.01)


def test_balance_recheck_happens_every_n_calls(tmp_path):
    calls = []
    llm = LLM(model="m", limits=Limits(project_cap=99, run_cap=99, recheck_every=3),
              client=fake_api(cost=0.001, calls=calls), ledger=Ledger(tmp_path / "l.jsonl"), key=SECRET)
    for _ in range(4):
        llm.chat([{"role": "user", "content": "x"}])
    assert sum(p.endswith("/credits") for p in calls) == 2  # before call 1 and before call 4
