"""Shared graph queries for the baseline strategies (task A7).

All of them start from the same seed: the observations of the distrusted source inside the window
(`SUPPORTS` edges, `observed_at` inclusive), exactly what RETCON's Q3 selects.
"""
from core.retract.cascade import MAX_PATH_EDGES, to_epoch


def seed_ids(g, window) -> list[str]:
    rows = g.query(
        "MATCH (:Source {id:$s})-[:SUPPORTS]->(o:Observation) "
        "WHERE o.observed_at >= $f AND o.observed_at <= $t RETURN o.id ORDER BY o.id",
        {"s": window.source, "f": to_epoch(window.t_from), "t": to_epoch(window.t_to)}).result_set
    return [r[0] for r in rows]


def one_hop(g, ids) -> set[str]:
    """Nodes with a justification that lists one of `ids` as a premise (direct conclusions only)."""
    if not ids:
        return set()
    rows = g.query(
        "MATCH (o:Mem)-[:PREMISE_OF]->(:Justification)-[:JUSTIFIES]->(x:Mem) WHERE o.id IN $ids "
        "RETURN DISTINCT x.id", {"ids": list(ids)}).result_set
    return {r[0] for r in rows}


def descendants(g, ids) -> set[str]:
    """Everything reachable downstream by any path (the any-ancestor rule)."""
    if not ids:
        return set()
    rows = g.query(
        f"MATCH (o:Mem)-[:PREMISE_OF|JUSTIFIES*1..{MAX_PATH_EDGES}]->(x:Mem) WHERE o.id IN $ids "
        "RETURN DISTINCT x.id", {"ids": list(ids)}).result_set
    return {r[0] for r in rows}
