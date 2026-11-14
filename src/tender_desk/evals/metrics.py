from __future__ import annotations


def hit_at(ranked_ids: list[int], gold: int, k: int) -> bool:
    return gold in ranked_ids[:k]


def reciprocal_rank(ranked_ids: list[int], gold: int) -> float:
    return 1.0 / (ranked_ids.index(gold) + 1) if gold in ranked_ids else 0.0


def summarise(results: list[tuple[list[int], int]]) -> dict:
    """results: (ranked item ids, gold id) per positive query."""
    n = len(results)
    if n == 0:
        return {"n": 0}
    return {
        "n": n,
        **{f"hit@{k}": round(sum(hit_at(r, g, k) for r, g in results) / n, 3) for k in (1, 3, 4, 5)},
        "mrr": round(sum(reciprocal_rank(r, g) for r, g in results) / n, 3),
    }
