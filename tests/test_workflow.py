import pytest
from langgraph.checkpoint.memory import MemorySaver

from tender_desk import graph as G
from tender_desk.db import connect
from tender_desk.graph import build_graph, decide, submit
from tender_desk.models import Choice, Choices, Scope, ScopeItem

pytest.importorskip("psycopg")


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
        c.execute("DELETE FROM quotes WHERE tender_id=%s", (t,))
        c.execute("DELETE FROM tenders WHERE id=%s", (t,))


class FakeLLM:
    """Returns scripted answers. Records every prompt so tests can inspect what the model was shown."""
    def __init__(self, scope, choices_list):
        self.scope, self.choices_list, self.prompts = scope, list(choices_list), []

    def structured(self, messages, cls, **kw):
        self.prompts.append(messages)
        return self.scope if cls is Scope else self.choices_list.pop(0)


def pid(conn, name):
    return conn.execute("SELECT id FROM price_items WHERE name=%s", (name,)).fetchone()[0]


SCOPE = Scope(job_summary="Rear extension with a concrete slab", items=[
    ScopeItem(description="supply and place 25MPa concrete for slab", qty=10, unit="m3"),
    ScopeItem(description="carpenter labour for framing", qty=40, unit="hour"),
])


def good_choices(conn):
    return Choices(choices=[
        Choice(item_index=0, price_item_id=pid(conn, "Concrete 25MPa ready-mix"), confidence="high", reason="exact"),
        Choice(item_index=1, price_item_id=pid(conn, "Carpenter labour"), confidence="high", reason="exact")])


def run(conn, llm):
    g = build_graph(llm, conn, MemorySaver())
    tid, cfg, res = submit(conn, g, "TEST tender", "Build a rear extension. 10 m3 concrete. 40 hours framing.")
    return g, tid, cfg, res


def test_pauses_for_a_person_and_code_does_the_maths(conn):
    g, tid, cfg, res = run(conn, FakeLLM(SCOPE, [good_choices(conn)]))
    draft = res["__interrupt__"][0].value["draft"]
    price = lambda n: float(conn.execute("SELECT unit_price FROM price_items WHERE name=%s", (n,)).fetchone()[0])
    expected_sub = round(10 * price("Concrete 25MPa ready-mix") + 40 * price("Carpenter labour"), 2)
    assert draft["subtotal"] == expected_sub
    assert draft["total"] == round(expected_sub * (1 + draft["margin_pct"] / 100), 2)
    assert conn.execute("SELECT count(*) FROM quotes WHERE tender_id=%s", (tid,)).fetchone()[0] == 0  # nothing saved yet


def test_approval_saves_quote_and_audit_trail(conn):
    g, tid, cfg, _ = run(conn, FakeLLM(SCOPE, [good_choices(conn)]))
    decide(g, cfg, approve=True, by="rod")
    assert conn.execute("SELECT status, decided_by FROM quotes WHERE tender_id=%s", (tid,)).fetchone() == ("approved", "rod")
    events = [r[0] for r in conn.execute("SELECT event FROM audit_log WHERE tender_id=%s ORDER BY id", (tid,)).fetchall()]
    assert events == ["tender_received", "scope_extracted", "draft_built", "decision", "finalized"]


def test_item_the_model_was_never_offered_is_rejected(conn):
    bad = Choices(choices=[
        Choice(item_index=0, price_item_id=pid(conn, "Kitchen cabinetry standard"), confidence="high", reason="made up"),
        Choice(item_index=1, price_item_id=pid(conn, "Carpenter labour"), confidence="high", reason="exact")])
    _, _, _, res = run(conn, FakeLLM(SCOPE, [bad]))
    draft = res["__interrupt__"][0].value["draft"]
    assert draft["lines"][0]["line_total"] == 0.0 and draft["lines"][0]["price_item_id"] is None
    assert any("not offered" in f for f in draft["flags"]) and draft["needs_attention"]


def test_unit_mismatch_and_no_match_are_flagged(conn):
    mism = Choices(choices=[
        Choice(item_index=0, price_item_id=pid(conn, "Concrete 25MPa ready-mix"), confidence="low", reason="guess"),
        Choice(item_index=1, price_item_id=None, confidence="low", reason="nothing fits")])
    scope = Scope(job_summary="x", items=[ScopeItem(description="supply 25MPa concrete", qty=5, unit="m2"),
                                          ScopeItem(description="carpenter labour", qty=8, unit="hour")])
    _, _, _, res = run(conn, FakeLLM(scope, [mism]))
    flags = res["__interrupt__"][0].value["draft"]["flags"]
    assert any("unit mismatch" in f for f in flags) and any("no matching" in f for f in flags)


def test_margin_below_policy_is_raised(conn, monkeypatch):
    monkeypatch.setattr(G, "comparable_jobs", lambda c, d: [{"id": 1, "title": "t", "total": 1.0, "margin_pct": 5.0, "score": 0.9}])
    _, _, _, res = run(conn, FakeLLM(SCOPE, [good_choices(conn)]))
    draft = res["__interrupt__"][0].value["draft"]
    assert draft["margin_pct"] == G.MIN_MARGIN and any("policy floor" in f for f in draft["flags"])


def test_rejection_with_notes_triggers_one_revision_with_the_feedback(conn):
    llm = FakeLLM(SCOPE, [good_choices(conn), good_choices(conn)])
    g, tid, cfg, _ = run(conn, llm)
    res = decide(g, cfg, approve=False, by="rod", notes="use the 32MPa concrete")
    assert "__interrupt__" in res  # back at the approval gate with a new draft
    assert "use the 32MPa concrete" in llm.prompts[-1][-1]["content"]
    decide(g, cfg, approve=True, by="rod")
    assert conn.execute("SELECT status FROM quotes WHERE tender_id=%s", (tid,)).fetchone()[0] == "approved"


def test_rejection_without_notes_is_final(conn):
    g, tid, cfg, _ = run(conn, FakeLLM(SCOPE, [good_choices(conn)]))
    decide(g, cfg, approve=False, by="rod")
    assert conn.execute("SELECT status FROM quotes WHERE tender_id=%s", (tid,)).fetchone()[0] == "rejected"


def test_unit_spellings_match_but_real_mismatches_still_flag(conn):
    from tender_desk.units import normalise_unit
    assert normalise_unit("m²") == normalise_unit("m2") and normalise_unit("lin m") == "m"
    assert normalise_unit("lump sum") == normalise_unit("each") and normalise_unit("sheets") == "sheet"
    assert normalise_unit("m2") != normalise_unit("m")
    scope = Scope(job_summary="x", items=[ScopeItem(description="25MPa concrete", qty=5, unit="m³")])
    ch = Choices(choices=[Choice(item_index=0, price_item_id=pid(conn, "Concrete 25MPa ready-mix"), confidence="high", reason="exact")])
    _, _, _, res = run(conn, FakeLLM(scope, [ch]))
    assert res["__interrupt__"][0].value["draft"]["flags"] == []


def test_wrong_size_is_not_priced_even_if_the_model_picks_it(conn):
    scope = Scope(job_summary="x", items=[ScopeItem(description="N16 reinforcing bar 12 m lengths", qty=20, unit="length")])
    ch = Choices(choices=[Choice(item_index=0, price_item_id=pid(conn, "Reinforcing bar N12 12m"), confidence="high", reason="closest")])
    # make sure the near-miss is actually among the candidates the model could pick
    _, _, _, res = run(conn, FakeLLM(scope, [ch]))
    line = res["__interrupt__"][0].value["draft"]["lines"][0]
    assert line["line_total"] == 0.0 and line["price_item_id"] is None
    assert any("spec differs" in f and "N12" in f for f in line["flags"])
