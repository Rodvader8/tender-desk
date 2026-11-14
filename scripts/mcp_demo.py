"""Price one tender line with the agent over real MCP (stdio subprocess).
Usage: uv run python scripts/mcp_demo.py "N16 bar to the pile cages" [model]
"""

import asyncio
import sys

from tender_desk.llm import LLM, Limits
from tender_desk.mcp_agent import price_line


async def main() -> None:
    line = sys.argv[1]
    llm = LLM(model=sys.argv[2] if len(sys.argv) > 2 else None, limits=Limits(run_cap=0.05))
    r = await price_line(llm, line)
    print(f"Line: {line!r}\nModel: {llm.model}")
    for i, s in enumerate(r.steps, 1):
        print(
            f"  step {i}: {s['tool']}({', '.join(f'{k}={v!r}' for k, v in s['args'].items())}){'  [error]' if s['error'] else ''}"
        )
    print(f"Answer: sku={r.sku}  verified={r.verified}  {r.note}\nReason: {r.reason}\nCost: ${r.cost:.5f}")


asyncio.run(main())
