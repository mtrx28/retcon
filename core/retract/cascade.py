"""Retraction cascade: distrust a source in a time window, then retract-then-re-derive (Q3-Q5).

Semantics (docs/CONTRACT.md section 4): a Mem is IN iff some Justification pointing at it has all
premises IN (Observations are the leaves, justified by their Source). Doyle-style well-founded
relabelling: everything downstream goes OUT tentatively, then any node with a fully IN justification
is brought back, looped to a fixpoint. Circular support between two OUT nodes can never resurrect them.

Nothing is deleted. Flipped nodes are linked from a :Retraction node so reinstate can reverse it.
Verified syntax and gotchas: docs/SPIKE.md.
"""
import re
import time
from datetime import datetime

from core.errors import RetconError


class NotFound(RetconError, LookupError):
    def __init__(self, message, details=None):
        super().__init__("NOT_FOUND", message, details)


class InvalidArgument(RetconError, ValueError):
    def __init__(self, message, details=None):
        super().__init__("INVALID_ARGUMENT", message, details)

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


def _rederive(g, run: str) -> list[str]:
    """Q5 to a fixpoint. Returns the ids that came back IN (independently supported)."""
    back: list[str] = []
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
        back += [r[0] for r in rows]


def distrust(g, source: str, t_from, t_to, mode: str = "commit",
             operator: str = "system", reason: str | None = None) -> dict:
    """Retract everything that depended only on `source` observations learned in [t_from, t_to].

    Returns the `distrust` MCP payload (docs/CONTRACT.md section 5) plus `hops`, the flipped node
    ids grouped by cascade depth, which the UI animates.
    """
    if mode != "commit":
        raise RetconError("NOT_IMPLEMENTED", "preview runs through core.preview.preview (GRAPH.COPY fork)", {"mode": mode})
    if not g.query("MATCH (s:Source {id:$s}) RETURN s.id", {"s": source}).result_set:
        raise NotFound(f"source {source!r}", {"source": source})
    started = time.perf_counter()
    f, t = to_epoch(t_from), to_epoch(t_to)
    if f > t:
        raise InvalidArgument("window start is after window end", {"from": str(t_from), "to": str(t_to)})
    rid = _next_retraction_id(g)
    reason = reason or f"Source {source} distrusted {t_from}..{t_to}"

    g.query(
        "CREATE (:Retraction {id:$rid, source:$s, from:$f, to:$t, reason:$reason, operator:$op, "
        "at:$now, mode:'commit', reinstated:false})",
        {"rid": rid, "s": source, "f": f, "t": t, "reason": reason, "op": operator,
         "now": int(time.time())})

    # Q3: the retraction claims EVERY observation of the source inside the window (standing
    # distrust, so reinstating an overlapping retraction cannot resurrect it). Those that were IN
    # are flipped OUT and seed the cascade; `flipped` records which ones this retraction changed.
    g.query(
        "MATCH (r:Retraction {id:$rid}), (:Source {id:$s})-[:SUPPORTS]->(o:Observation) "
        "WHERE o.observed_at >= $f AND o.observed_at <= $t "
        "CREATE (r)-[:RETRACTED {hop:0, flipped:(o.status = 'IN')}]->(o)",
        {"rid": rid, "s": source, "f": f, "t": t})
    g.query(
        "MATCH (:Source {id:$s})-[:SUPPORTS]->(o:Observation) "
        "WHERE o.status = 'IN' AND o.observed_at >= $f AND o.observed_at <= $t "
        "SET o.status = 'OUT', o.run = $run",
        {"s": source, "f": f, "t": t, "run": rid})

    # Q4: everything downstream goes OUT tentatively; hop = derivation depth (2 edges per hop).
    g.query(
        f"MATCH p = (o:Observation {{run:$run}})-[:PREMISE_OF|JUSTIFIES*1..{MAX_PATH_EDGES}]->(x:Mem) "
        "WHERE x.status = 'IN' "
        "WITH x, min(length(p)) AS d "
        "SET x.status = 'OUT', x.run = $run, x.hop = toInteger(d / 2)",
        {"run": rid})

    # Q5: well-founded re-derivation. Independently supported nodes come back IN.
    survived = _rederive(g, rid)

    # Audit trail: link the Retraction to every derived node that stayed OUT, then clear scratch tags.
    g.query(
        "MATCH (r:Retraction {id:$rid}), (x:Mem {run:$rid}) "
        "WHERE x.status = 'OUT' AND NOT x:Observation "
        "CREATE (r)-[:RETRACTED {hop: x.hop, flipped:true}]->(x)",
        {"rid": rid})
    g.query("MATCH (x:Mem {run:$rid}) SET x.run = null, x.hop = null", {"rid": rid})

    return _report(g, rid, (time.perf_counter() - started) * 1000, survived)


def _report(g, rid: str, latency_ms: float, survived=()) -> dict:
    from core.recall.recall_list import blocked_actions, recall_list  # local: avoid import cycle

    rows = g.query(
        "MATCH (:Retraction {id:$rid})-[e:RETRACTED]->(x:Mem) WHERE e.flipped = true "
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
        "survived_ids": sorted(survived),   # downstream of the source, kept by independent support
        "latency_ms": round(latency_ms, 2),
        "profile": profile_cascade(g, rid),
    }


_RID = re.compile(r"^[A-Za-z0-9_]+$")
_TIME = re.compile(r"Execution time: ([0-9.]+) ms")


def profile_cascade(g, rid: str) -> dict:
    """GRAPH.PROFILE of the Q4 traversal from this retraction's seed observations (read-only form of
    the cascade query), so the UI can show the engine's own number next to our wall clock."""
    if not _RID.match(rid):
        return {}
    q = (f"CYPHER rid='{rid}' MATCH (:Retraction {{id:$rid}})-[e:RETRACTED]->(o:Observation) "
         f"WHERE e.flipped = true "
         f"MATCH p = (o)-[:PREMISE_OF|JUSTIFIES*1..{MAX_PATH_EDGES}]->(x:Mem) "
         f"RETURN x.id, min(length(p)) AS d")
    try:
        lines = g.client.connection.execute_command("GRAPH.PROFILE", g.name, q)
    except Exception:  # noqa: BLE001 - profiling is informational, never fatal
        return {}
    lines = [l.decode() if isinstance(l, bytes) else str(l) for l in lines]
    times = [float(m.group(1)) for l in lines if (m := _TIME.search(l))]
    return {"query": "Q4 cascade traversal (read-only form)", "execution_ms": max(times) if times else None,
            "plan": [l.strip() for l in lines]}


def reinstate(g, retraction_id: str) -> dict:
    """Reverse a retraction without disturbing others.

    Observations it claimed go back IN unless another active (not reinstated) retraction still
    claims them. Then every OUT derived node is re-derived globally, so the labelling is exactly the
    well-founded one for the remaining distrusts, whatever order retractions were applied or undone in.
    """
    row = g.query("MATCH (r:Retraction {id:$rid}) RETURN r.reinstated", {"rid": retraction_id}).result_set
    if not row:
        raise NotFound(f"retraction {retraction_id!r}", {"retraction_id": retraction_id})
    if row[0][0]:
        raise InvalidArgument("retraction already reinstated", {"retraction_id": retraction_id})
    run = f"{retraction_id}_undo"
    g.query("MATCH (r:Retraction {id:$rid}) SET r.reinstated = true, r.reinstated_at = $now",
            {"rid": retraction_id, "now": int(time.time())})
    g.query(
        "MATCH (:Retraction {id:$rid})-[:RETRACTED]->(o:Observation {status:'OUT'}) "
        "WHERE NOT (o)<-[:RETRACTED]-(:Retraction {reinstated:false}) "
        "SET o.status = 'IN'",
        {"rid": retraction_id})
    g.query("MATCH (b:Mem {status:'OUT'}) WHERE NOT b:Observation SET b.run = $run", {"run": run})
    _rederive(g, run)
    g.query("MATCH (x:Mem {run:$run}) SET x.run = null, x.hop = null", {"run": run})
    restored = g.query(
        "MATCH (:Retraction {id:$rid})-[:RETRACTED]->(x:Mem {status:'IN'}) RETURN count(x)",
        {"rid": retraction_id}).result_set[0][0]
    return {"restored_count": restored}
