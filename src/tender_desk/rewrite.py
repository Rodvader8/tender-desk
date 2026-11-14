"""Rewrite tender lines into plain standard terms before searching, so slang can find the right price item.

No glossary and no per-item hints: the model has to bring the slang knowledge itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

SYSTEM = (
    "You rewrite lines from a construction tender so they match a supplier price list. Replace trade slang, "
    "abbreviations and colloquial Australian terms with the plain standard term. Keep every number, size and "
    "spec exactly. Do not add anything that is not implied. Return exactly one rewrite per input line, in order."
)


class Rewrites(BaseModel):
    rewrites: list[str]


def rewrite_queries(llm, queries: list[str], batch: int = 15, cache_path: Path | None = None) -> dict[str, str]:
    cache: dict[str, str] = json.loads(cache_path.read_text()) if cache_path and cache_path.exists() else {}

    def key(q: str) -> str:
        return f"{llm.model}|{q}"

    todo = [q for q in dict.fromkeys(queries) if key(q) not in cache]
    for b in range(0, len(todo), batch):
        chunk = todo[b : b + batch]
        out = llm.structured(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(chunk)}], Rewrites, purpose="rewrite"
        ).rewrites
        for i, q in enumerate(chunk):
            # if the model returns the wrong number of lines, keep the original rather than misalign
            cache[key(q)] = out[i] if len(out) == len(chunk) else q
    if cache_path and todo:
        cache_path.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    return {q: cache[key(q)] for q in queries}
