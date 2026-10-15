"""Baseline 2: vector-only memory (no graph).

The store keeps chunks and embeddings and nothing about why a chunk exists. Retraction deletes the
source's chunks and every chunk whose embedding is within `threshold` cosine similarity of one of
them. Same text embedder as the rest of the system (`core.retrieve.embed`, `hash` offline).

This is also the graph-off ablation's retraction rule (Lane B imports it): with the graph removed,
this is all a memory layer can do.
"""
import time

from bench.api import RetractionResult, Window
from bench.baselines.common import seed_ids
from core.retrieve.embed import get_embedder

DEFAULT_THRESHOLD = 0.75


class VectorOnly:
    name = "vector_only"

    def __init__(self, threshold: float = DEFAULT_THRESHOLD, embedder=None):
        self.threshold = threshold
        self._embedder = embedder

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    def retract(self, graph, window: Window) -> RetractionResult:
        seeds = seed_ids(graph, window)
        t0 = time.perf_counter()
        rows = graph.query("MATCH (m:Mem) WHERE m.text IS NOT NULL RETURN m.id, m.text ORDER BY m.id").result_set
        ids = [r[0] for r in rows]
        vecs = self._matrix([r[1] for r in rows])
        index = {i: k for k, i in enumerate(ids)}
        out = set(seeds)
        seed_rows = [index[s] for s in seeds if s in index]
        if seed_rows and len(ids):
            sims = vecs @ vecs[seed_rows].T                    # cosine (rows are unit length)
            hit = (sims >= self.threshold).any(axis=1)
            out |= {ids[k] for k in range(len(ids)) if hit[k]}
        return RetractionResult(out, engine_ms=(time.perf_counter() - t0) * 1000,
                                notes={"threshold": self.threshold, "embedder": self.embedder.name})

    def _matrix(self, texts):
        import numpy as np
        v = np.asarray(self.embedder.embed(texts), dtype="float32")
        n = np.linalg.norm(v, axis=1, keepdims=True)
        return v / np.where(n == 0, 1.0, n)
