"""Q1: justified write (task B1).

Every derived memory is written together with its Justification (an AND of premises) in one query,
so a belief can never exist without the edges the cascade (Q4/Q5) and the min-cut (Q7) rely on:
  (premise)-[:PREMISE_OF]->(Justification)-[:JUSTIFIES]->(node)
  (premise)-[:FLOW {cap}]->(node)      Q7 projection
  (node)-[:DEPENDS_ON]->(premise)      Q8 projection
  (Agent)-[:HOLDS]->(node)

Identity is content-addressed, so the same write is idempotent and a re-assertion of the same
claim from different premises adds a second Justification to the same node (the OR in
OR-of-ANDs: independent corroboration).
"""
import hashlib
import re
import time
from datetime import datetime

from core.errors import RetconError

FLOW_CAP = 1_000_000
KINDS = {"belief": "Belief", "plan": "Plan"}
MTYPES = ("episodic", "semantic", "procedural")  # contract v1.1


def _norm(text):
    return re.sub(r"\s+", " ", text.strip().lower())


def _digest(*parts):
    return hashlib.sha1("\x1f".join(parts).encode("utf8")).hexdigest()[:12]


def node_id(kind, text):
    return "mem_" + _digest(kind, _norm(text))


def justification_id(nid, premise_ids):
    return "j_" + _digest(nid, *sorted(premise_ids))


def to_epoch(t):
    """Epoch seconds from an int/float or an ISO 8601 string."""
    if isinstance(t, (int, float)):
        return int(t)
    return int(datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp())


def ensure_agent(g, agent):
    g.query("MERGE (a:Agent {id:$a}) ON CREATE SET a.role=$a", {"a": agent})


def write_observation(g, *, source, text, observed_at, agent="intake", obs_id=None, embedding=None):
    """An Observation is the only node a Source touches directly. `observed_at` is epoch seconds.
    Status follows the contract: IN iff its source is known (trust windows are applied by Q3)."""
    if not g.query("MATCH (s:Source {id:$s}) RETURN s.id", {"s": source}).result_set:
        raise RetconError("NOT_FOUND", f"unknown source {source!r}", {"source": source})
    oid = obs_id or "obs_" + _digest(source, str(to_epoch(observed_at)), _norm(text))
    ensure_agent(g, agent)
    g.query(
        "MATCH (s:Source {id:$src}), (a:Agent {id:$agent}) "
        "MERGE (o:Mem:Observation {id:$id}) "
        "ON CREATE SET o.text=$text, o.status='IN', o.observed_at=$at, o.agent=$agent, "
        "              o.created_at=$now, o.mtype='episodic', o.embedding=CASE WHEN $emb IS NULL THEN null ELSE vecf32($emb) END "
        "MERGE (s)-[:SUPPORTS]->(o) "
        "MERGE (s)-[f:FLOW]->(o) SET f.cap=1 "
        "MERGE (o)-[:DEPENDS_ON]->(s) "
        "MERGE (a)-[:HOLDS]->(o)",
        {"src": source, "agent": agent, "id": oid, "text": text, "at": to_epoch(observed_at),
         "now": int(time.time()), "emb": embedding})
    return {"node_id": oid, "source": source}


def write_justified(g, *, text, kind, agent, premise_ids, rule=None, embedding=None, now=None, mtype=None):
    """Write a belief/plan justified by `premise_ids` (all AND-ed in one Justification).

    Status is decided by the graph rule, not by the caller: IN iff every premise is IN right now
    (or the node was already IN). Returns {node_id, premise_ids, justification_id, status, created}.

    `mtype` (contract v1.1): beliefs default to "semantic", plans are untagged. A "procedural" rule
    must rest on at least one episodic premise (an Observation or an episodic node): a learned rule
    always points back at the episode it was learned from, so retracting the episode retracts it.
    """
    if kind not in KINDS:
        raise RetconError("INVALID_ARGUMENT", f"kind must be belief or plan, got {kind!r}", {"kind": kind})
    if not text or not text.strip():
        raise RetconError("INVALID_ARGUMENT", "text is empty", {})
    if mtype is not None and mtype not in MTYPES:
        raise RetconError("INVALID_ARGUMENT", f"mtype must be one of {MTYPES}, got {mtype!r}", {"mtype": mtype})
    if mtype is None and kind == "belief":
        mtype = "semantic"
    premises = sorted(set(premise_ids))
    if not premises:
        raise RetconError("INVALID_ARGUMENT",
                          "no premises: recall something first, or write an observation from a source",
                          {"agent": agent})

    rows = g.query("MATCH (p:Mem) WHERE p.id IN $ids RETURN p.id, p.mtype, labels(p), p.agent",
                   {"ids": premises}).result_set
    found = {r[0] for r in rows}
    missing = [p for p in premises if p not in found]
    if missing:
        raise RetconError("NOT_FOUND", f"unknown premise ids: {missing}", {"missing_ids": missing})
    if mtype == "procedural" and not any(r[1] == "episodic" or "Observation" in r[2] for r in rows):
        raise RetconError("INVALID_ARGUMENT",
                          "a procedural rule must be justified by at least one episodic premise",
                          {"premise_ids": premises})

    nid = node_id(kind, text)
    if nid in premises:
        raise RetconError("INVALID_ARGUMENT", "a node cannot be its own premise", {"node_id": nid})
    jid = justification_id(nid, premises)
    if rule is None:
        # a derivation built only from what other agents wrote is a handoff edge (shared state)
        if all(r[3] and r[3] != agent for r in rows):
            rule = "handoff"
        else:
            rule = "combine" if len(premises) > 1 else "infer"
    ensure_agent(g, agent)
    existed = bool(g.query("MATCH (m:Mem {id:$id}) RETURN m.id", {"id": nid}).result_set)

    g.query(
        f"MATCH (a:Agent {{id:$agent}}) "
        f"MATCH (p:Mem) WHERE p.id IN $premises "
        f"WITH a, collect(p) AS ps, all(x IN collect(p) WHERE x.status = 'IN') AS live "
        f"MERGE (m:Mem:{KINDS[kind]} {{id:$nid}}) "
        f"ON CREATE SET m.text=$text, m.status='OUT', m.agent=$agent, m.created_at=$now, m.mtype=$mtype, "
        f"             m.embedding=CASE WHEN $emb IS NULL THEN null ELSE vecf32($emb) END "
        f"SET m.status = CASE WHEN m.status = 'IN' OR live THEN 'IN' ELSE 'OUT' END "
        f"MERGE (j:Justification {{id:$jid}}) "
        f"ON CREATE SET j.rule=$rule, j.agent=$agent, j.at=$now "
        f"MERGE (j)-[:JUSTIFIES]->(m) "
        f"MERGE (a)-[:HOLDS]->(m) "
        f"WITH m, j, ps "
        f"UNWIND ps AS p "
        f"MERGE (p)-[:PREMISE_OF]->(j) "
        f"MERGE (p)-[f:FLOW]->(m) SET f.cap=$cap "
        f"MERGE (m)-[:DEPENDS_ON]->(p)",
        {"agent": agent, "premises": premises, "nid": nid, "text": text, "now": int(now or time.time()),
         "emb": embedding, "jid": jid, "rule": rule, "cap": FLOW_CAP, "mtype": mtype})

    status = g.query("MATCH (m:Mem {id:$id}) RETURN m.status", {"id": nid}).result_set[0][0]
    return {"node_id": nid, "premise_ids": premises, "justification_id": jid,
            "status": status, "created": not existed, "mtype": mtype}
