"""Personal data in a tender never reaches the model, comes back in the draft and the quote, and is only ever counted in logs."""

import json
import logging

from langgraph.checkpoint.memory import MemorySaver
from test_api import client
from test_workflow import FakeLLM, good_choices

from tender_desk.graph import build_graph, decide, submit
from tender_desk.models import Scope, ScopeItem

SECRETS = ["Priya Nair", "Priya", "0491 570 123", "priya.nair@gmail.com", "12 Wattle Street", "Parramatta NSW 2150", "Tom Doyle"]
TENDER = (
    "Rear extension for the owner.\n"
    "Attn: Priya Nair\nPhone: 0491 570 123\nEmail: priya.nair@gmail.com\n"
    "Site: 12 Wattle Street, Parramatta NSW 2150\n"
    "Contact: Tom Doyle, then Priya Nair again.\n"
    "Allow 10 m3 concrete and 40 hours framing."
)

# What a model would plausibly write when it sees the redacted text: it repeats the placeholders.
SCOPE = Scope(
    job_summary="Rear extension at [ADDRESS_1] for [PERSON_1]",
    items=[
        ScopeItem(description="supply and place 25MPa concrete for slab at [ADDRESS_1]", qty=10, unit="m3"),
        ScopeItem(description="carpenter labour for framing, access via [PERSON_1] on [PHONE_1]", qty=40, unit="hour"),
    ],
)


def everything_the_model_saw(llm: FakeLLM) -> str:
    return json.dumps(llm.prompts)


def run(conn, llm):
    g = build_graph(llm, conn, MemorySaver())
    tid, cfg, res = submit(conn, g, "TEST pii tender", TENDER)
    return g, tid, cfg, res


def test_no_real_value_reaches_the_model(conn):
    llm = FakeLLM(SCOPE, [good_choices(conn), good_choices(conn)])
    g, _, cfg, _ = run(conn, llm)
    decide(g, cfg, approve=False, by="rod", notes="Priya Nair says use the 32MPa concrete, ring 0491 570 123")
    seen = everything_the_model_saw(llm)
    assert len(llm.prompts) == 3  # extract, estimate, and the revised estimate: the reviewer's note is checked too
    for secret in SECRETS:
        assert secret not in seen, secret
    assert "[PERSON_1]" in llm.prompts[0][-1]["content"] and "[PHONE_1]" in llm.prompts[0][-1]["content"]
    assert "10 m3 concrete" in llm.prompts[0][-1]["content"]  # the work itself is untouched


def test_the_reviewers_draft_and_the_saved_quote_hold_the_real_values(conn):
    llm = FakeLLM(SCOPE, [good_choices(conn)])
    g, tid, cfg, res = run(conn, llm)
    draft = res["__interrupt__"][0].value["draft"]
    assert draft["job_summary"] == "Rear extension at 12 Wattle Street, Parramatta NSW 2150 for Priya Nair"
    assert draft["lines"][1]["description"] == "carpenter labour for framing, access via Priya Nair on 0491 570 123"
    assert "[" not in json.dumps(draft["lines"][0]["description"])
    decide(g, cfg, approve=True, by="rod", draft_digest=res["__interrupt__"][0].value["draft_digest"])
    saved = conn.execute("SELECT draft FROM quotes WHERE tender_id=%s", (tid,)).fetchone()[0]
    assert saved["job_summary"].endswith("for Priya Nair") and "[PERSON_1]" not in json.dumps(saved)


def test_the_prices_and_arithmetic_do_not_change_with_redaction(conn):
    plain = Scope(job_summary="x", items=SCOPE.items)
    _, _, _, with_pii = run(conn, FakeLLM(plain, [good_choices(conn)]))
    g = build_graph(FakeLLM(plain, [good_choices(conn)]), conn, MemorySaver())
    _, _, without = submit(conn, g, "TEST pii tender", "Rear extension. Allow 10 m3 concrete and 40 hours framing.")
    a, b = with_pii["__interrupt__"][0].value["draft"], without["__interrupt__"][0].value["draft"]
    assert (a["subtotal"], a["total"]) == (b["subtotal"], b["total"])


def test_audit_and_run_trace_hold_counts_only(conn):
    llm = FakeLLM(SCOPE, [good_choices(conn)])
    g, tid, cfg, res = run(conn, llm)
    decide(g, cfg, approve=True, by="rod", draft_digest=res["__interrupt__"][0].value["draft_digest"])
    audit = conn.execute("SELECT event, detail FROM audit_log WHERE tender_id=%s ORDER BY id", (tid,)).fetchall()
    trace = conn.execute("SELECT step, ms, cost_usd, llm_calls, error FROM run_steps WHERE tender_id=%s", (tid,)).fetchall()
    dumped = json.dumps([[e, d] for e, d in audit], default=str) + json.dumps(trace, default=str)
    for secret in SECRETS:
        assert secret not in dumped, secret
    redacted = next(d for e, d in audit if e == "pii_redacted")
    assert redacted == {"person": 3, "phone": 1, "email": 1, "address": 1}  # Priya twice, Tom once
    assert "redact" in [t[0] for t in trace]


def test_logs_and_metrics_hold_counts_only(conn, caplog):
    with caplog.at_level(logging.DEBUG):
        c = client(conn, FakeLLM(SCOPE, [good_choices(conn)]))
        c.post("/tenders", json={"title": "TEST api tender Priya Nair", "text": TENDER})
    logged = "\n".join(r.getMessage() + json.dumps(r.__dict__, default=str) for r in caplog.records)
    metrics = c.get("/metrics").text
    for secret in SECRETS:
        assert secret not in logged and secret not in metrics, secret
    assert 'tender_pii_redactions_total{type="PERSON"}' in metrics and 'tender_pii_redactions_total{type="PHONE"}' in metrics


def test_a_title_with_a_name_is_redacted_in_the_audit_entry(conn):
    g = build_graph(FakeLLM(SCOPE, [good_choices(conn)]), conn, MemorySaver())
    tid, _, _ = submit(conn, g, "TEST Attn: Priya Nair extension", "10 m3 concrete")
    title = conn.execute(
        "SELECT detail->>'title' FROM audit_log WHERE tender_id=%s AND event='tender_received'", (tid,)
    ).fetchone()[0]
    assert "Priya" not in title and "[PERSON_1]" in title


def test_the_api_returns_real_values_to_the_reviewer_and_none_reach_the_model(conn):
    llm = FakeLLM(SCOPE, [good_choices(conn)])
    c = client(conn, llm)
    body = c.post("/tenders", json={"title": "TEST api tender", "text": TENDER}).json()
    assert "Priya Nair" in json.dumps(body["draft"])
    assert not any(s in everything_the_model_saw(llm) for s in SECRETS)


def test_a_tender_with_no_personal_data_is_unchanged_and_counts_zero(conn):
    llm = FakeLLM(Scope(job_summary="x", items=SCOPE.items), [good_choices(conn)])
    g = build_graph(llm, conn, MemorySaver())
    tid, _, _ = submit(conn, g, "TEST plain tender", "ABN 51 824 753 556. Call 1300 555 019. 10 m3 concrete. 40 hours framing.")
    assert "ABN 51 824 753 556" in llm.prompts[0][-1]["content"] and "1300 555 019" in llm.prompts[0][-1]["content"]
    detail = conn.execute("SELECT detail FROM audit_log WHERE tender_id=%s AND event='pii_redacted'", (tid,)).fetchone()[0]
    assert detail == {"person": 0, "phone": 0, "email": 0, "address": 0}
