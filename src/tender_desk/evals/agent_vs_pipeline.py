"""Agent (MCP tools) against the fixed pipeline on evals/holdout3.jsonl. See evals/PREREGISTRATION_MCP_AGENT.md.
  uv run python -m tender_desk.evals.agent_vs_pipeline --model deepseek/deepseek-v4-flash --write
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from ..db import connect
from ..llm import LLM, Limits
from ..mcp_agent import price_line
from ..mcp_server import mcp
from . import selection
from .retrieval import load

ROOT = Path(__file__).resolve().parents[3]


async def run_agent(model: str, rows: list[dict], sku_to_name: dict) -> list[dict]:
    out = []
    for r in rows:
        llm = LLM(model=model, limits=Limits(run_cap=0.05))
        res = await price_line(llm, r["query"], target=mcp)
        name = sku_to_name.get(res.sku) if res.sku else None
        out.append(dict(id=r["id"], kind=r["kind"], query=r["query"], gold=r["gold"], pick=name, note=res.note, steps=len(res.steps),
                        searches=sum(s["tool"] == "search_price_items" for s in res.steps), cost=res.cost,
                        correct=(name == r["gold"]) if r["gold"] else name is None))
    return out


def summarise(recs: list[dict]) -> dict:
    pos = [r for r in recs if r["gold"]]; neg = [r for r in recs if not r["gold"]]
    slang = [r for r in pos if r["kind"] == "jargon"]
    f = lambda xs: f"{sum(r['correct'] for r in xs)}/{len(xs)}"
    return dict(all=f(recs), slang=f(slang), plain=f([r for r in pos if r["kind"] == "plain"]), not_in_catalogue=f(neg),
                wrong_pick=sum(1 for r in recs if r["gold"] and r["pick"] and not r["correct"]),
                false_match=sum(1 for r in neg if r["pick"]), no_answer_step_limit=sum(r.get("note") == "step_limit" for r in recs))


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--model", required=True); ap.add_argument("--write", action="store_true"); a = ap.parse_args()
    conn = connect(); rows = load("holdout3")
    sku_to_name = {s: n for s, n in conn.execute("SELECT sku, name FROM price_items").fetchall()}
    pipe = selection.run(a.model, 0.10, "holdout3", "vec_current")
    pipe_recs = [dict(id=r["id"], kind=r["kind"], query=r["query"], gold=r["gold"], pick=r["pick"], correct=r["correct"]) for r in pipe["records"]]
    agent_recs = asyncio.run(run_agent(a.model, rows, sku_to_name))
    out = dict(model=a.model, pipeline=dict(summary=summarise(pipe_recs), cost=pipe["cost_usd"], records=pipe_recs),
               agent=dict(summary=summarise(agent_recs), cost=round(sum(r["cost"] for r in agent_recs), 5),
                          avg_tool_calls=round(sum(r["steps"] for r in agent_recs) / len(agent_recs), 2),
                          avg_searches=round(sum(r["searches"] for r in agent_recs) / len(agent_recs), 2), records=agent_recs))
    print(f"{a.model}")
    for k in ("pipeline", "agent"):
        print(f"  {k:<9}", out[k]["summary"], f"cost ${out[k]['cost']}", "" if k == "pipeline" else f"avg tool calls {out[k]['avg_tool_calls']}")
    for k in ("pipeline", "agent"):
        for r in out[k]["records"]:
            if not r["correct"]: print(f"    {k} MISS: {r['query']!r} wanted {r['gold']!r} got {r['pick']!r}", r.get("note", ""))
    if a.write:
        (ROOT / "results").mkdir(exist_ok=True)
        (ROOT / "results" / f"agent_vs_pipeline_{a.model.replace('/', '_')}.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
