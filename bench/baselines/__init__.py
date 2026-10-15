"""The five retraction strategies compared by RetconBench (task A7), against bench/api.py.

    delete_source      what most stacks do today: remove the source's records, nothing else
    vector_only        no graph: also delete chunks similar to the removed ones (cosine >= 0.75)
    edge_invalidation  Graphiti-style: invalidate the source's facts and what was extracted from them
    coarse_taint       MemLineage-style any-ancestor rule: everything downstream goes, no re-derivation
    retcon             JTMS: retract, then re-derive what still has independent support

Reimplementations, clearly labelled as such in every report (rule 9: no code from those projects).
"""
from bench.api import STRATEGY_NAMES, RetractionResult, Strategy, Window  # noqa: F401
from bench.baselines.coarse_taint import CoarseTaint
from bench.baselines.delete_source import DeleteSource
from bench.baselines.edge_invalidation import EdgeInvalidation
from bench.baselines.retcon import Retcon
from bench.baselines.vector_only import VectorOnly


def all_strategies(**kw) -> dict[str, Strategy]:
    """Fresh instances in the fixed column order of STRATEGY_NAMES."""
    made = {"delete_source": DeleteSource(), "vector_only": VectorOnly(**kw), "edge_invalidation": EdgeInvalidation(),
            "coarse_taint": CoarseTaint(), "retcon": Retcon()}
    return {n: made[n] for n in STRATEGY_NAMES}
