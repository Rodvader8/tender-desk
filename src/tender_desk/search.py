"""Retrieval: nearest price items and nearest past jobs by meaning, via pgvector."""

from __future__ import annotations

from .embed import embed


def price_candidates(conn, description: str, k: int = 4) -> list[dict]:
    v = embed([description])[0]
    rows = conn.execute(
        "SELECT id, sku, name, category, unit, unit_price, 1 - (embedding <=> %s) AS score, supplier "
        "FROM price_items ORDER BY embedding <=> %s LIMIT %s",
        (v, v, k),
    ).fetchall()
    return [
        dict(
            id=r[0],
            sku=r[1],
            name=r[2],
            category=r[3],
            unit=r[4],
            unit_price=float(r[5]),
            score=round(float(r[6]), 3),
            supplier=r[7],
        )
        for r in rows
    ]


def comparable_jobs(conn, description: str, k: int = 3) -> list[dict]:
    v = embed([description])[0]
    rows = conn.execute(
        "SELECT id, title, total, margin_pct, 1 - (embedding <=> %s) AS score "
        "FROM past_quotes ORDER BY embedding <=> %s LIMIT %s",
        (v, v, k),
    ).fetchall()
    return [dict(id=r[0], title=r[1], total=float(r[2]), margin_pct=float(r[3]), score=round(float(r[4]), 3)) for r in rows]
