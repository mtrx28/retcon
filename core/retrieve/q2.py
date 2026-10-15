"""Q2: grounded retrieval (task B2).

Vector search over Mem.embedding, IN nodes only, with a support summary per hit:
which Sources the belief currently rests on and the weakest of their trust values.

`score` is the cosine DISTANCE (lower = closer), results are sorted ascending (docs/SPIKE.md).
The status filter runs after top-k inside the index, so we over-fetch and widen until k IN
nodes are found or the whole index has been seen.
"""
from core.retrieve.embed import DIM

INDEX_DDL = ("CREATE VECTOR INDEX FOR (m:Mem) ON (m.embedding) "
             f"OPTIONS {{dimension:{DIM}, similarityFunction:'cosine'}}")
MAX_DEPTH = 12  # same bound as the Q4 cascade
MAX_FETCH = 4096


def ensure_vector_index(g):
    try:
        g.query(INDEX_DDL)
    except Exception as e:  # FalkorDB raises when the index already exists
        if "already" not in str(e).lower():
            raise


def embed_graph(g, embedder, batch=64):
    """Embed every Mem that has no embedding yet (fixtures are loaded without vectors)."""
    ensure_vector_index(g)
    rows = g.query("MATCH (m:Mem) WHERE m.embedding IS NULL RETURN m.id, m.text").result_set
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        for (mid, _), vec in zip(chunk, embedder.embed([r[1] or "" for r in chunk])):
            g.query("MATCH (m:Mem {id:$id}) SET m.embedding = vecf32($v)", {"id": mid, "v": vec})
    return len(rows)


def search(g, vec, k, contains=None):
    """Top-k IN memories nearest to `vec`: [(id, text, labels, distance)].
    `contains` keeps only memories whose text includes that substring (case-insensitive), applied
    before top-k so the caller still gets k hits when they exist."""
    total = None
    n = max(k * 4, 16)
    while True:
        rows = g.query(
            "CALL db.idx.vector.queryNodes('Mem','embedding',$n,vecf32($v)) YIELD node, score "
            "WHERE node.status = 'IN' AND ($c IS NULL OR toLower(node.text) CONTAINS toLower($c)) "
            "RETURN node.id, node.text, labels(node), score ORDER BY score",
            {"n": n, "v": vec, "c": contains}).result_set
        if len(rows) >= k or n >= MAX_FETCH:
            return rows[:k]
        if total is None:
            total = g.query("MATCH (m:Mem) WHERE m.embedding IS NOT NULL RETURN count(m)").result_set[0][0]
        if n >= total:
            return rows[:k]
        n = min(n * 4, MAX_FETCH)


def ancestry(g, node_id):
    """Live structure under a node: (status, base, justs).

    status: {mem_id: 'IN'|'OUT'} for the node and its ancestors (depth MAX_DEPTH)
    base:   {observation_id: (source_id, trust)} for IN observations
    justs:  {justification_id: (conclusion_id, [premise_ids])}
    """
    anc = [r[0] for r in g.query(
        f"MATCH (n:Mem {{id:$id}})-[:DEPENDS_ON*0..{MAX_DEPTH}]->(a:Mem) RETURN DISTINCT a.id",
        {"id": node_id}).result_set]
    if not anc:
        return {}, {}, {}
    status = {r[0]: r[1] for r in g.query(
        "MATCH (a:Mem) WHERE a.id IN $ids RETURN a.id, a.status", {"ids": anc}).result_set}
    base = {}
    for oid, sid, trust in g.query(
            "MATCH (s:Source)-[:SUPPORTS]->(o:Observation) WHERE o.id IN $ids RETURN o.id, s.id, s.trust",
            {"ids": anc}).result_set:
        if status.get(oid) == "IN":
            base[oid] = (sid, trust)
    justs = {}
    for jid, concl, pid in g.query(
            "MATCH (j:Justification)-[:JUSTIFIES]->(c:Mem) WHERE c.id IN $ids "
            "OPTIONAL MATCH (p:Mem)-[:PREMISE_OF]->(j) RETURN j.id, c.id, p.id",
            {"ids": anc}).result_set:
        justs.setdefault(jid, (concl, []))[1].append(pid)
    return status, base, justs


def support(g, node_id):
    """Sources a node currently rests on, honouring AND-of-premises and ignoring circular support.

    Least fixpoint over *live* justifications (every premise IN), seeded by IN Observations, so a
    cycle contributes sources only if some member is grounded from outside it.
    Returns {source_id: trust}.
    """
    status, base, justs = ancestry(g, node_id)
    if not status:
        return {}
    src = {i: ({base[i][0]: base[i][1]} if i in base else {}) for i in status}
    changed = True
    while changed:
        changed = False
        for concl, prem in justs.values():
            if status.get(concl) != "IN" or not prem or any(status.get(p) != "IN" for p in prem):
                continue
            for p in prem:
                for sid, trust in src.get(p, {}).items():
                    if sid not in src[concl]:
                        src[concl][sid] = trust
                        changed = True
    return src.get(node_id, {})


def recall(g, vec, k=8, contains=None):
    """Contract shape: [{id, text, score, sources, weakest_trust}], IN only, nearest first."""
    out = []
    for nid, text, _labels, dist in search(g, vec, k, contains):
        s = support(g, nid)
        out.append({"id": nid, "text": text, "score": dist, "sources": sorted(s),
                    "weakest_trust": min(s.values()) if s else None})
    return out
