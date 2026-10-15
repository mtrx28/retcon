"""Stand-in strategies so the harness runs before Lane A's baselines land (and as a cross-check after).

`ReferenceRetcon` is what the contract says `retcon` means: run `core.retract.cascade.distrust` on the
fork and report every Mem that is OUT. It is NOT a baseline; Lane A's `bench.baselines.retcon` wins when
present (the runner prefers discovered strategies and marks stand-ins in `notes`).
"""
from bench.api import RetractionResult, Window
from core.db import fetch_all
from core.retract import cascade


class ReferenceRetcon:
    name = "retcon"

    def retract(self, graph, window: Window):
        res = cascade.distrust(graph, window.source, window.t_from, window.t_to)
        out = {r[0] for r in fetch_all(graph, "MATCH (m:Mem {status:'OUT'}) RETURN m.id AS i", order_by="i")}
        return RetractionResult(out, engine_ms=res.get("latency_ms"), notes={"source": "harness stand-in"})

    def support_count(self, graph, node_id):
        from core.retrieve.q2 import support
        return len(support(graph, node_id))


def with_reference(strategies):
    """`strategies` plus the stand-in `retcon` when Lane A's is not there."""
    out = dict(strategies)
    out.setdefault("retcon", ReferenceRetcon())
    return out
