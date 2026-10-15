"""Baseline 3: invalidate the source's facts and what was extracted from them, no cascade.

Graphiti-style: a contradiction invalidates the edge of the fact it contradicts (and, since facts
extracted in the same episode are linked to it, those too). Nothing is propagated any further, so
summaries, plans and actions built on top keep being served.
"""
from bench.api import RetractionResult, Window
from bench.baselines.common import one_hop, seed_ids


class EdgeInvalidation:
    name = "edge_invalidation"

    def retract(self, graph, window: Window) -> RetractionResult:
        seeds = seed_ids(graph, window)
        return RetractionResult(set(seeds) | one_hop(graph, seeds))
