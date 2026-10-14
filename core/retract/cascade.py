"""Retraction cascade: distrust a source in a time window, then retract-then-re-derive (Q3-Q5).

Semantics (docs/CONTRACT.md section 4): a Mem is IN iff some Justification pointing at it has all
premises IN (Observations are the leaves, justified by their Source). Doyle-style well-founded
relabelling: everything downstream goes OUT tentatively, then any node with a fully IN justification
is brought back, looped to a fixpoint. Circular support between two OUT nodes can never resurrect them.

Nothing is deleted. Flipped nodes are linked from a :Retraction node so reinstate can reverse it.
Verified syntax and gotchas: docs/SPIKE.md.
"""
import time
from datetime import datetime

# Longest dependency chain followed, in edges. Each derivation is 2 edges (PREMISE_OF + JUSTIFIES).
MAX_PATH_EDGES = 40

KINDS = ("Observation", "Belief", "Plan", "Action")


def to_epoch(t) -> int:
    """Accept epoch seconds or an ISO 8601 string."""
    if isinstance(t, (int, float)):
        return int(t)
    return int(datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp())


def _next_retraction_id(g) -> str:
    n = g.query("MATCH (r:Retraction) RETURN count(r)").result_set[0][0]
    return f"ret_{n + 1:04d}"


def _rederive(g, run: str) -> int:
    """Q5 to a fixpoint. Returns how many nodes came back IN."""
    back = 0
    while True:
        rows = g.query(
            "MATCH (j:Justification)-[:JUSTIFIES]->(b:Mem {status:'OUT', run:$run}) "
            "OPTIONAL MATCH (p:Mem)-[:PREMISE_OF]->(j) "
            "WITH b, j, count(p) AS total, "
            "     sum(CASE WHEN p.status = 'OUT' THEN 1 ELSE 0 END) AS dead "
            "WHERE total > 0 AND dead = 0 "
            "WITH DISTINCT b SET b.status = 'IN', b.run = null, b.hop = null RETURN b.id",
            {"run": run}).result_set
        if not rows:
            return back
        back += len(rows)


def distrust(g, source: str, t_from, t_to, mode: str = "commit",
             operator: str = "system", reason: str | None = None) -> dict:
    """Retract everything that depended only on `source` observations learned in [t_from, t_to].

    Returns the `distrust` MCP payload (docs/CONTRACT.md section 5) plus `hops`, the flipped node
    ids grouped by cascade depth, which the UI animates.
    """
    if mode != "commit":
        raise NotImplementedError("mode='preview' is task A5 (GRAPH.COPY fork)")
    if not g.query("MATCH (s:Source {id:$s}) RETURN s.id", {"s": source}).result_set:
        raise LookupError(f"NOT_FOUND: source {source!r}")
    started = time.perf_counter()
    f, t = to_epoch(t_from), to_epoch(t_to)
    if f > t:
        raise ValueError("INVALID_ARGUMENT: window start is after window end")
    rid = _next_retraction_id(g)
    reason = reason or f"Source {source} distrusted {t_from}..{t_to}"

    # Q3: observations from the source inside the window go OUT (the cascade seeds).
    g.query(
        "MATCH (:Source {id:$s})-[:SUPPORTS]->(o:Observation) "
        "WHERE o.status = 'IN' AND o.observed_at >= $f AND o.observed_at <= $t "
        "SET o.status = 'OUT', o.run = $run, o.hop = 0",
        {"s": source, "f": f, "t": t, "run": rid})

    # Q4: everything downstream goes OUT tentatively; hop = derivation depth (2 edges per hop).
    g.query(
        f"MATCH p = (o:Observation {{run:$run}})-[:PREMISE_OF|JUSTIFIES*1..{MAX_PATH_EDGES}]->(x:Mem) "
        "WHERE x.status = 'IN' "
        "WITH x, min(length(p)) AS d "
        "SET x.status = 'OUT', x.run = $run, x.hop = toInteger(d / 2)",
        {"run": rid})

    # Q5: well-founded re-derivation. Independently supported nodes come back IN.
    _rederive(g, rid)

    # Audit trail: link the Retraction to everything that stayed OUT, then clear the cascade tags.
    g.query(
        "CREATE (:Retraction {id:$rid, source:$s, from:$f, to:$t, reason:$reason, operator:$op, "
        "at:$now, mode:'commit', reinstated:false})",
        {"rid": rid, "s": source, "f": f, "t": t, "reason": reason, "op": operator,
         "now": int(time.time())})
    g.query(
        "MATCH (r:Retraction {id:$rid}), (x:Mem {run:$rid}) WHERE x.status = 'OUT' "
        "CREATE (r)-[:RETRACTED {hop: x.hop}]->(x) SET x.run = null, x.hop = null",
        {"rid": rid})

    return _report(g, rid, (time.perf_counter() - started) * 1000)


def _report(g, rid: str, latency_ms: float) -> dict:
    from core.recall.recall_list import blocked_actions, recall_list  # local: avoid import cycle

    rows = g.query(
        "MATCH (:Retraction {id:$rid})-[e:RETRACTED]->(x:Mem) "
        "RETURN x.id, labels(x), e.hop ORDER BY e.hop, x.id", {"rid": rid}).result_set
    counts = {"observations": 0, "beliefs": 0, "plans": 0, "actions": 0}
    plural = {"Observation": "observations", "Belief": "beliefs", "Plan": "plans", "Action": "actions"}
    hops: dict[int, list[str]] = {}
    for node_id, labels, hop in rows:
        kind = next(k for k in KINDS if k in labels)
        counts[plural[kind]] += 1
        hops.setdefault(int(hop or 0), []).append(node_id)
    return {
        "retraction_id": rid,
        "flipped": counts,
        "flipped_ids": [r[0] for r in rows],
        "hops": hops,
        "blocked_action_ids": blocked_actions(g, rid),
        "recall_list": recall_list(g, rid),
        "latency_ms": round(latency_ms, 2),
    }


def reinstate(g, retraction_id: str) -> dict:
    """Reverse a retraction. Its observations go back IN; everything else it flipped is re-derived,
    so a node that still lacks well-founded support (e.g. owed to a different retraction) stays OUT.

    Known limitation: if a later retraction's window also covers an observation this one flipped,
    that observation was already OUT then and is not claimed by the later one, so it comes back here.
    """
    row = g.query("MATCH (r:Retraction {id:$rid}) RETURN r.reinstated", {"rid": retraction_id}).result_set
    if not row:
        raise LookupError(f"NOT_FOUND: retraction {retraction_id!r}")
    if row[0][0]:
        raise ValueError("INVALID_ARGUMENT: retraction already reinstated")
    run = f"{retraction_id}_undo"
    g.query(
        "MATCH (:Retraction {id:$rid})-[:RETRACTED]->(x:Mem) "
        "FOREACH (_ IN CASE WHEN x:Observation THEN [1] ELSE [] END | SET x.status = 'IN') "
        "SET x.run = CASE WHEN x:Observation THEN null ELSE $run END",
        {"rid": retraction_id, "run": run})
    _rederive(g, run)
    g.query("MATCH (x:Mem {run:$run}) SET x.run = null, x.hop = null", {"run": run})
    g.query("MATCH (r:Retraction {id:$rid}) SET r.reinstated = true, r.reinstated_at = $now",
            {"rid": retraction_id, "now": int(time.time())})
    restored = g.query(
        "MATCH (:Retraction {id:$rid})-[:RETRACTED]->(x:Mem {status:'IN'}) RETURN count(x)",
        {"rid": retraction_id}).result_set[0][0]
    return {"restored_count": restored}
