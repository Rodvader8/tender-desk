"""Run one tender through the live workflow on a real model, stopping at the approval step.
Usage: uv run python scripts/demo.py examples/tender_rear_extension.txt [--approve]
Spend is capped by the guard in tender_desk.llm (see `uv run spend`).
"""

import sys
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from tender_desk.db import connect
from tender_desk.graph import build_graph, decide, submit
from tender_desk.llm import LLM, Limits


def main() -> None:
    path = Path(sys.argv[1])
    llm = LLM(limits=Limits(run_cap=0.05))
    conn = connect()
    g = build_graph(llm, conn, MemorySaver())
    tid, cfg, res = submit(conn, g, path.stem, path.read_text())
    draft = res["__interrupt__"][0].value["draft"]
    print(f"Tender {tid}: {draft['job_summary']}\n")
    for i, ln in enumerate(draft["lines"], 1):
        print(
            f"{i:>2}. {ln['description'][:52]:<52} {ln['qty']:>7} {ln['unit']:<5} -> {(ln['item_name'] or 'NO MATCH')[:34]:<34} ${ln['line_total']:>9,.2f}  {ln['confidence']}"
        )
        for f in ln["flags"]:
            print(f"      ! {f}")
    print(f"\nSubtotal ${draft['subtotal']:,.2f}  margin {draft['margin_pct']}%  TOTAL ${draft['total']:,.2f}")
    print(f"Waiting for a person. Run cost ${llm.guard.run_spent:.5f} over {llm.guard.calls} model calls.")
    if "--approve" in sys.argv:
        decide(g, cfg, approve=True, by="demo")
        print("Approved and saved.")


if __name__ == "__main__":
    main()
