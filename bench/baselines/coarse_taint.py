"""Baseline 4: coarse taint (any-ancestor rule).

Everything with the distrusted source anywhere in its ancestry is dropped. This is RETCON's
tentative cascade (Q4) without the re-derivation (Q5), so it never misses contamination but also
discards beliefs that have independent support (collateral loss), and cannot tell a corroborated
belief from a single-source one.
"""
from bench.api import RetractionResult, Window
from bench.baselines.common import descendants, seed_ids


class CoarseTaint:
    name = "coarse_taint"

    def retract(self, graph, window: Window) -> RetractionResult:
        seeds = seed_ids(graph, window)
        return RetractionResult(set(seeds) | descendants(graph, seeds))
