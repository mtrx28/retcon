"""Strategy 5: RETCON itself, through the same entry point operators use (`cascade.distrust`).

out_ids is every :Mem with status OUT after the call, not just the nodes this call flipped, so
sequential windows (science: one per retracted paper) accumulate correctly on one graph.
"""
from bench.api import RetractionResult, Window
from core.fragility import fragility
from core.retract import cascade


class Retcon:
    name = "retcon"

    def retract(self, graph, window: Window) -> RetractionResult:
        res = cascade.distrust(graph, window.source, window.t_from, window.t_to, operator="bench")
        out = {r[0] for r in graph.query("MATCH (m:Mem {status:'OUT'}) RETURN m.id").result_set}
        return RetractionResult(out, engine_ms=(res.get("profile") or {}).get("execution_ms"),
                                notes={"retraction_id": res["retraction_id"], "survived": len(res["survived_ids"])})

    def support_count(self, graph, node_id: str) -> int:
        """Independent sources: the exact min-cut, so echoes from one source count once."""
        return fragility(graph, node_id, with_flow=False)["independent_sources"]
