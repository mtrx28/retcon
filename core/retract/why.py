"""why(node_id): the justification tree behind a memory (task A3).

  node
   |- justifications: [ {id, rule, agent, premises: [node, ...]} ]   (OR of ANDs)
   `- source (observations only)

Built level by level (one batched query per level), then assembled in Python. Cycle-safe: a node
already on the current path is returned as {"id", "cycle": true} instead of recursing.
"""
from core.errors import RetconError


def _node_info(g, ids):
    rows = g.query(
        "MATCH (n:Mem) WHERE n.id IN $ids "
        "OPTIONAL MATCH (s:Source)-[:SUPPORTS]->(n) "
        "RETURN n.id, labels(n), n.text, n.status, n.mtype, n.agent, n.observed_at, n.amount, "
        "       n.executed, s.id, s.kind, s.trust",
        {"ids": list(ids)}).result_set
    info = {}
    for nid, labels, text, status, mtype, agent, at, amount, executed, sid, skind, strust in rows:
        kind = next((k for k in ("Observation", "Belief", "Plan", "Action") if k in labels), "Mem")
        d = {"id": nid, "kind": kind.lower(), "text": text, "status": status}
        if mtype:
            d["mtype"] = mtype
        if agent:
            d["agent"] = agent
        if kind == "Observation":
            d["observed_at"] = at
            if sid:
                d["source"] = {"id": sid, "kind": skind, "trust": strust}
        if kind == "Action":
            d["amount"], d["executed"] = amount, executed
        info[nid] = d
    return info


def why(g, node_id: str, max_depth: int = 12) -> dict:
    if max_depth < 0:
        raise RetconError("INVALID_ARGUMENT", "max_depth must be >= 0", {"max_depth": max_depth})
    if not g.query("MATCH (n:Mem {id:$id}) RETURN n.id", {"id": node_id}).result_set:
        raise RetconError("NOT_FOUND", f"memory node {node_id!r}", {"node_id": node_id})

    info: dict[str, dict] = {}
    justs: dict[str, list[dict]] = {}
    frontier, depth = {node_id}, 0
    while frontier:
        info.update(_node_info(g, frontier - set(info)))
        if depth >= max_depth:
            break
        rows = g.query(
            "MATCH (j:Justification)-[:JUSTIFIES]->(c:Mem) WHERE c.id IN $ids "
            "OPTIONAL MATCH (p:Mem)-[:PREMISE_OF]->(j) "
            "RETURN c.id, j.id, j.rule, j.agent, collect(p.id) ORDER BY c.id, j.id",
            {"ids": list(frontier)}).result_set
        nxt = set()
        for cid, jid, rule, agent, premises in rows:
            premises = sorted(p for p in premises if p)
            justs.setdefault(cid, []).append({"id": jid, "rule": rule, "agent": agent, "premises": premises})
            nxt.update(premises)
        frontier = nxt - set(info)
        depth += 1

    retractions = {}
    for rid, nid in g.query(
            "MATCH (r:Retraction {reinstated:false})-[:RETRACTED]->(n:Mem) WHERE n.id IN $ids "
            "RETURN r.id, n.id", {"ids": list(info)}).result_set:
        retractions.setdefault(nid, []).append(rid)

    def build(nid, path):
        if nid in path:
            return {"id": nid, "cycle": True}
        node = dict(info.get(nid, {"id": nid}))
        if nid in retractions:
            node["retracted_by"] = sorted(retractions[nid])
        js = justs.get(nid)
        if js is None and node.get("kind") != "observation":
            node["truncated"] = True  # cut off by max_depth
            return node
        if js:
            node["justifications"] = [
                {"id": j["id"], "rule": j["rule"], "agent": j["agent"],
                 "premises": [build(p, path | {nid}) for p in j["premises"]]}
                for j in js]
        return node

    return build(node_id, frozenset())
