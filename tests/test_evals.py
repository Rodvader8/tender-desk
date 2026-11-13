import json
from pathlib import Path

import pytest

from tender_desk.evals.metrics import hit_at, reciprocal_rank, summarise


def test_metrics():
    assert hit_at([5, 2, 9], 2, 1) is False and hit_at([5, 2, 9], 2, 2) is True
    assert reciprocal_rank([5, 2, 9], 2) == 0.5 and reciprocal_rank([5, 2, 9], 7) == 0.0
    s = summarise([([1, 2, 3, 4], 1), ([9, 8, 1, 2], 1), ([7, 7, 7, 7], 1)])
    assert s["n"] == 3 and s["hit@1"] == 0.333 and s["hit@3"] == 0.667 and s["hit@4"] == 0.667


def test_eval_set_is_well_formed():
    rows = [json.loads(l) for l in (Path(__file__).parents[1] / "evals" / "retrieval_queries.jsonl").read_text().splitlines()]
    assert len({r["id"] for r in rows}) == len(rows)
    assert {r["split"] for r in rows} == {"dev", "test"}
    assert sum(r["gold"] is None for r in rows) == 8
    assert all((r["gold"] is None) == (r["kind"] == "negative") for r in rows)


def test_in_memory_search_matches_production_pgvector():
    from tender_desk.db import connect
    from tender_desk.evals.retrievers import Catalogue
    from tender_desk.search import price_candidates
    try:
        conn = connect()
    except Exception:
        pytest.skip("local database not running")
    cat = Catalogue(conn)
    for q in ["25 MPa concrete to the slab", "sparky hours", "franna crane hire"]:
        assert [c["id"] for c in price_candidates(conn, q, 4)] == cat.vec_current(q)[0][:4]
