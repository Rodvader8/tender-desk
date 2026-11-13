"""Selection evaluation: given the top-4 candidates retrieval offers, does the model pick the right item?

Uses the production prompt (pricing.choose_prices) and production retrieval (vec_current top 4).
  uv run python -m tender_desk.evals.selection --model deepseek/deepseek-v4-flash --run-cap 0.10 --write
Reports: end-to-end accuracy, accuracy when the right item WAS offered, wrong picks, wrong abstentions,
and the false-match rate on items that are not in the catalogue.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..db import connect
from ..llm import LLM, Limits
from ..pricing import build_offer, choose_prices
from .retrievers import Catalogue
from .retrieval import load

ROOT = Path(__file__).resolve().parents[3]
BATCH = 10


def run(model: str, run_cap: float, split: str = "all", retrieval: str = "vec_current") -> dict:
    conn = connect(); cat = Catalogue(conn); rows = load(split)
    if retrieval.startswith("rewrite"):
        from .retrieval import attach_rewrites
        attach_rewrites(cat, rows)
    search = getattr(cat, retrieval)
    name_to_id = {n: i for n, i in conn.execute("SELECT name, id FROM price_items").fetchall()}
    info = {r[0]: dict(id=r[0], name=r[1], unit=r[2], unit_price=float(r[3])) for r in
            conn.execute("SELECT id, name, unit, unit_price FROM price_items").fetchall()}
    llm = LLM(model=model, limits=Limits(run_cap=run_cap))
    recs = []
    for b in range(0, len(rows), BATCH):
        chunk = rows[b:b + BATCH]
        items = [{"description": r["query"], "qty": 1, "unit": "unspecified"} for r in chunk]
        cands = {str(i): [info[x] for x in search(r["query"])[0][:4]] for i, r in enumerate(chunk)}
        picks = {c.item_index: c.price_item_id for c in choose_prices(llm, build_offer(items, cands), purpose="eval-selection").choices}
        for i, r in enumerate(chunk):
            offered = [c["id"] for c in cands[str(i)]]
            gold = name_to_id.get(r["gold"]) if r["gold"] else None
            pick = picks.get(i)
            recs.append(dict(id=r["id"], kind=r["kind"], query=r["query"], gold=r["gold"], offered=gold in offered if gold else None,
                             pick=info[pick]["name"] if pick in info else None, invalid=pick is not None and pick not in offered,
                             correct=(pick == gold and not (pick is not None and pick not in offered)) if gold else pick is None))
    pos = [r for r in recs if r["gold"]]; neg = [r for r in recs if not r["gold"]]
    offered = [r for r in pos if r["offered"]]
    out = dict(model=model, retrieval=retrieval, split=split, queries=len(recs), cost_usd=round(llm.guard.run_spent, 5),
               end_to_end_accuracy=round(sum(r["correct"] for r in pos) / len(pos), 3),
               accuracy_when_offered=round(sum(r["correct"] for r in offered) / len(offered), 3),
               right_item_not_offered=len(pos) - len(offered),
               wrong_pick=sum(1 for r in offered if r["pick"] and not r["correct"]),
               wrongly_abstained=sum(1 for r in offered if r["pick"] is None),
               invalid_ids=sum(r["invalid"] for r in recs),  # picks outside the offered candidates; production rejects them and scores them wrong here
               invalid_but_right=sum(1 for r in pos if r["invalid"] and r["pick"] == r["gold"]),
               negatives=len(neg), false_match_rate=round(sum(1 for r in neg if r["pick"] is not None) / len(neg), 3),
               errors=[r for r in recs if not r["correct"]], records=recs)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--model", required=True); ap.add_argument("--run-cap", type=float, default=0.10)
    ap.add_argument("--split", default="all"); ap.add_argument("--retrieval", default="vec_current"); ap.add_argument("--write", action="store_true"); a = ap.parse_args()
    o = run(a.model, a.run_cap, a.split, a.retrieval)
    print(f"{o['model']} / {o['retrieval']} / {o['split']}: {o['queries']} queries, cost ${o['cost_usd']}")
    for k in ("end_to_end_accuracy", "accuracy_when_offered", "right_item_not_offered", "wrong_pick", "wrongly_abstained", "invalid_ids", "false_match_rate"):
        print(f"  {k:<24}{o[k]}")
    for e in o["errors"]:
        print(f"   ! {e['query']!r}: wanted {e['gold']!r}, picked {e['pick']!r}, offered={e['offered']}")
    if a.write:
        (ROOT / "results").mkdir(exist_ok=True)
        (ROOT / "results" / f"selection_{a.split}_{a.retrieval}_{a.model.replace('/', '_')}.json").write_text(json.dumps(o, indent=2))


if __name__ == "__main__":
    main()
