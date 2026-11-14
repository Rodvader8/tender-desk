"""Local embeddings (no API cost): BAAI/bge-small-en-v1.5, 384 dimensions."""

from functools import lru_cache

import numpy as np


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding("BAAI/bge-small-en-v1.5")


def embed(texts: list[str]) -> list[np.ndarray]:
    return [np.asarray(v, dtype=np.float32) for v in _model().embed(texts)]


def embed_query(texts: list[str]) -> list[np.ndarray]:
    """BGE models are trained to see search queries with an instruction prefix; fastembed adds it here."""
    return [np.asarray(v, dtype=np.float32) for v in _model().query_embed(texts)]
