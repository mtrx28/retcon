"""Baseline 1: delete the source's records and nothing else."""
from bench.api import RetractionResult, Window
from bench.baselines.common import seed_ids


class DeleteSource:
    name = "delete_source"

    def retract(self, graph, window: Window) -> RetractionResult:
        return RetractionResult(set(seed_ids(graph, window)))

    def support_count(self, graph, node_id: str) -> int:
        """Counts justifications, so a claim echoed by N agents from one source scores N."""
        return graph.query("MATCH (j:Justification)-[:JUSTIFIES]->(:Mem {id:$id}) RETURN count(j)",
                           {"id": node_id}).result_set[0][0]
