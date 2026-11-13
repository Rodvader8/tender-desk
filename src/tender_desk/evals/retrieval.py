"""Retrieval evaluation.  uv run python -m tender_desk.evals.retrieval --split dev|test|all [--write]"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from ..db import connect
from .metrics import summarise
from .retrievers import Catalogue

ROOT = Path(__file__).resolve().parents[3]


def load(split: str) -> list[dict]:
    if split == "holdout2":
        return [json.loads(l) for l in (ROOT / "evals" / "holdout2.jsonl").read_text().splitlines()]
    rows = [json.loads(l) for l in (ROOT / "evals" / "retrieval_queries.jsonl").read_text().splitlines()]
    return rows if split == "all" else [r for r in rows if r["split"] == split]


REWRITE_CACHE = ROOT / "evals" / "rewrite_cache.json"


def attach_rewrites(cat, rows: list[dict], model: str = "deepseek/deepseek-v4-flash") -> float:
    """Rewrite every query (cached), attach to the catalogue, return the spend."""
    from ..llm import LLM, Limits
    from ..rewrite import rewrite_queries
    llm = LLM(model=model, limits=Limits(run_cap=0.05))
    cat.rewrites.update(rewrite_queries(llm, [r["query"] for r in rows], cache_path=REWRITE_CACHE))
    return llm.guard.run_spent


def evaluate(cat: Catalogue, rows: list[dict], conn, strategies=Catalogue.STRATEGIES) -> dict:
    name_to_id = {n: i for n, i in conn.execute("SELECT name, id FROM price_items").fetchall()}
    out = {}
    for s in strategies:
        fn = getattr(cat, s)
        pos, neg_top, pos_top, by_kind, fails, ms = [], [], [], {}, [], []
        for r in rows:
            t = time.perf_counter(); ranked, top = fn(r["query"]); ms.append((time.perf_counter() - t) * 1000)
            if r["gold"] is None:
                neg_top.append(top); continue
            gold = name_to_id[r["gold"]]
            pos.append((ranked, gold)); pos_top.append(top)
            by_kind.setdefault(r["kind"], []).append((ranked, gold))
            if ranked[0] != gold:
                fails.append({"id": r["id"], "query": r["query"], "gold": r["gold"], "got": cat.names[cat.ids.index(ranked[0])],
                              "gold_rank": ranked.index(gold) + 1})
        out[s] = {"overall": summarise(pos), "by_kind": {k: summarise(v) for k, v in sorted(by_kind.items())},
                  "median_ms": round(statistics.median(ms), 2), "top1_misses": fails,
                  "top_score_positive_mean": round(statistics.mean(pos_top), 3) if pos_top else None,
                  "top_score_negative_mean": round(statistics.mean(neg_top), 3) if neg_top else None}
    return out


def table(res: dict) -> str:
    lines = ["| strategy | n | hit@1 | hit@3 | hit@4 (what the model sees) | hit@5 | MRR | median ms |", "|---|---|---|---|---|---|---|---|"]
    for s, r in res.items():
        o = r["overall"]
        lines.append(f"| {s} | {o['n']} | {o['hit@1']:.0%} | {o['hit@3']:.0%} | {o['hit@4']:.0%} | {o['hit@5']:.0%} | {o['mrr']:.3f} | {r['median_ms']} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--split", default="dev"); ap.add_argument("--write", action="store_true")
    ap.add_argument("--rewrite", action="store_true", help="compare rewrite strategies against plain vector search")
    a = ap.parse_args()
    conn = connect(); cat = Catalogue(conn); rows = load(a.split)
    strategies = Catalogue.STRATEGIES
    if a.rewrite:
        print(f"rewrite cost ${attach_rewrites(cat, rows):.5f}")
        strategies = ("vec_current", "rewrite_only", "rewrite_fused")
    res = evaluate(cat, rows, conn, strategies)
    print(f"split={a.split}  queries={len(rows)}\n"); print(table(res))
    for s, r in res.items():
        print(f"\n{s}: top-1 misses {len(r['top1_misses'])}")
        for m in r["top1_misses"][:8]:
            print(f"   {m['query']!r}: wanted {m['gold']!r} (rank {m['gold_rank']}), got {m['got']!r}")
    if a.write:
        (ROOT / "results").mkdir(exist_ok=True)
        (ROOT / "results" / f"retrieval_{a.split}{'_rewrite' if a.rewrite else ''}.json").write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
