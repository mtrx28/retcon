"""Q8: keystone sources (task A12). Which sources does the most memory rest on?

PageRank over the dependency projection (`DEPENDS_ON`: conclusion -> premise, observation -> source), so
rank accumulates on a source from everything built, directly or through other beliefs, on top of it.

Two orderings, because PageRank alone ties symmetric sources exactly (all vendor portals look alike):

    rank      pure PageRank. The systems of record (ERP, purchase orders) come first: nearly every invoice
              rests on them. Answers "what would hurt most if it were wrong".
    priority  rank x (1 - trust). Answers "what should be audited first": heavily depended on *and* not
              very trustworthy. A low-trust portal under many beliefs outranks its look-alikes.

`downstream` is the blast radius: distinct memories reachable from the source's observations
(`live_downstream` the ones still IN). It is exact reachability, not a rank.
"""
from core.retract.cascade import MAX_PATH_EDGES

ORDERS = ("priority", "rank", "downstream")


def keystones(g, top: int = 10, order: str = "priority") -> list[dict]:
    if order not in ORDERS:
        raise ValueError(f"order must be one of {ORDERS}")
    # algo.pageRank raises (`LAGr_PageRank failed: -1000`) when the graph has exactly ONE node, e.g. a fresh tenant
    # with a single source. A graph with any DEPENDS_ON edge has two or more nodes, so this guard avoids it;
    # with no edges rank is 0 for all. Known FalkorDB behaviour (already reported upstream by others); reproduction: scripts/falkordb_repro.py
    if g.query("MATCH ()-[r:DEPENDS_ON]->() RETURN count(r)").result_set[0][0]:
        ranks = {r[0]: (r[1], r[2], r[3]) for r in g.query(
            "CALL algo.pageRank(null, 'DEPENDS_ON') YIELD node, score "
            "WHERE 'Source' IN labels(node) RETURN node.id, node.kind, node.trust, score").result_set}
    else:
        ranks = {r[0]: (r[1], r[2], 0.0) for r in g.query(
            "MATCH (s:Source) RETURN s.id, s.kind, s.trust").result_set}
    if not ranks:
        return []
    reach = {r[0]: r[1:] for r in g.query(
        "MATCH (s:Source)-[:SUPPORTS]->(o:Observation) "
        f"OPTIONAL MATCH (o)-[:PREMISE_OF|JUSTIFIES*1..{MAX_PATH_EDGES}]->(x:Mem) "
        "RETURN s.id, count(DISTINCT o), count(DISTINCT x), "
        "count(DISTINCT CASE WHEN x.status = 'IN' THEN x END)").result_set}
    extra = {r[0]: r[1:] for r in g.query(
        "MATCH (s:Source) RETURN s.id, s.retracted_at, s.rw_reason").result_set}
    out = []
    for sid, (kind, trust, score) in ranks.items():
        obs, down, live = reach.get(sid, (0, 0, 0))
        trust = 0.5 if trust is None else float(trust)
        out.append({"id": sid, "kind": kind, "trust": trust, "rank": score,
                    "priority": score * (1.0 - trust), "observations": obs,
                    "downstream": down, "live_downstream": live,
                    "retracted_at": (extra.get(sid) or (None, None))[0]})
    key = {"priority": lambda s: (-s["priority"], -s["downstream"], s["id"]),
           "rank": lambda s: (-s["rank"], -s["downstream"], s["id"]),
           "downstream": lambda s: (-s["downstream"], -s["rank"], s["id"])}[order]
    out.sort(key=key)
    for i, s in enumerate(out, 1):
        s["position"] = i
    return out[:top]


def blast_radius(g, source: str) -> list[str]:
    """Ids of every memory downstream of the source's observations (for highlighting)."""
    rows = g.query(
        "MATCH (:Source {id:$s})-[:SUPPORTS]->(o:Observation) "
        f"OPTIONAL MATCH (o)-[:PREMISE_OF|JUSTIFIES*1..{MAX_PATH_EDGES}]->(x:Mem) "
        "WITH collect(DISTINCT o.id) + collect(DISTINCT x.id) AS ids UNWIND ids AS i "
        "RETURN DISTINCT i ORDER BY i", {"s": source}).result_set
    return [r[0] for r in rows if r[0]]
