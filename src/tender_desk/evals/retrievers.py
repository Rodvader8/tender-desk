"""Retrieval strategies compared by the eval. All run in memory over the same catalogue so the
comparison is fair; `pgvector_current` calls the production search to prove parity with `vec_current`."""
from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

from ..embed import embed, embed_query


def _tok(text: str) -> list[str]:
    return [t[:-1] if len(t) > 3 and t.endswith("s") else t for t in re.findall(r"[a-z0-9]+", text.lower())]


class Catalogue:
    def __init__(self, conn):
        rows = conn.execute("SELECT id, name, category FROM price_items ORDER BY id").fetchall()
        self.ids = [r[0] for r in rows]
        self.names = [r[1] for r in rows]
        self.cats = [r[2] for r in rows]
        self.with_cat = [f"{c} {n}" for n, c in zip(self.names, self.cats)]   # exactly what the DB embeds
        self.m_cat = np.vstack(embed(self.with_cat))
        self.m_name = np.vstack(embed(self.names))
        docs = [_tok(f"{n} {c}") for n, c in zip(self.names, self.cats)]
        self.rewrites: dict[str, str] = {}
        self._docs, self._avg = docs, sum(map(len, docs)) / len(docs)
        df = Counter(t for d in docs for t in set(d))
        self._idf = {t: math.log(1 + (len(docs) - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def _rank(self, scores) -> list[int]:
        return [self.ids[i] for i in np.argsort(-np.asarray(scores), kind="stable")]

    def _cos(self, q: np.ndarray, m: np.ndarray) -> np.ndarray:
        return (m @ q) / (np.linalg.norm(m, axis=1) * np.linalg.norm(q))

    def vec_current(self, query: str):          # what production did: same encoder for query and catalogue
        s = self._cos(embed([query])[0], self.m_cat); return self._rank(s), float(s.max())

    def vec_query_prefix(self, query: str):     # encoder's query instruction, category-prefixed catalogue
        s = self._cos(embed_query([query])[0], self.m_cat); return self._rank(s), float(s.max())

    def vec_name_only(self, query: str):        # query instruction, catalogue embedded by name alone
        s = self._cos(embed_query([query])[0], self.m_name); return self._rank(s), float(s.max())

    def bm25(self, query: str, k1: float = 1.5, b: float = 0.75):
        q = _tok(query); sc = []
        for d in self._docs:
            tf = Counter(d)
            sc.append(sum(self._idf.get(t, 0) * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / self._avg)) for t in q if t in tf))
        return self._rank(sc), max(sc)

    def hybrid(self, query: str, rrf_k: int = 60):   # reciprocal rank fusion of the best vector + BM25
        a, _ = self.vec_query_prefix(query); c, top = self.bm25(query)
        fused: dict[int, float] = {}
        for ranking in (a, c):
            for r, i in enumerate(ranking):
                fused[i] = fused.get(i, 0) + 1 / (rrf_k + r + 1)
        return [i for i, _ in sorted(fused.items(), key=lambda x: -x[1])], top

    def rewrite_only(self, query: str):         # search with the model's plain-terms rewrite
        return self.vec_current(self.rewrites.get(query, query))

    def rewrite_fused(self, query: str, rrf_k: int = 60):   # fuse the original ranking with the rewrite's ranking
        a, _ = self.vec_current(query); b, top = self.vec_current(self.rewrites.get(query, query))
        fused: dict[int, float] = {}
        for ranking in (a, b):
            for r, i in enumerate(ranking):
                fused[i] = fused.get(i, 0) + 1 / (rrf_k + r + 1)
        return [i for i, _ in sorted(fused.items(), key=lambda x: -x[1])], top

    STRATEGIES = ("vec_current", "vec_query_prefix", "vec_name_only", "bm25", "hybrid")
