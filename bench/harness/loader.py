"""Batched scenario loader (task B7). Same graph as `data.load_fixture.load` (checked by
tests/bench/test_harness.py through `bench.harness.fingerprint`), built with UNWIND batches instead of one
query per row: ~100x fewer round trips, which is what makes 10k-node runs practical.

    g = load_batched(spec, graph_name="bench_ap_10k_tpl")
    fork = g.copy("bench_ap_10k_run")        # GRAPH.COPY: a strategy gets a private copy in milliseconds
"""
from data.load_fixture import FLOW_CAP, SCHEMA, connect, epoch, validate_spec

BATCH = 500


def _chunks(rows, n=BATCH):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def load_batched(spec, db=None, graph_name=None, batch=BATCH):
    validate_spec(spec)
    db = db or connect()
    name = graph_name or f"tenant_{spec['tenant']}"
    try:
        db.select_graph(name).delete()
    except Exception:  # noqa: BLE001 - nothing to drop
        pass
    g = db.select_graph(name)
    for line in SCHEMA.read_text().splitlines():
        if line.strip() and not line.startswith("//"):
            g.query(line)
    q = g.query

    def run(cypher, rows):
        for part in _chunks(rows, batch):
            q(cypher, {"rows": part})

    run("UNWIND $rows AS r CREATE (:Source {id:r.id, kind:r.kind, trust:r.trust, retracted_at:r.retracted_at, "
        "rw_reason:r.rw_reason, title:r.title, doi:r.doi})",
        [{"id": s["id"], "kind": s["kind"], "trust": s["trust"], "retracted_at": s.get("retracted_at"),
          "rw_reason": s.get("rw_reason"), "title": s.get("title"), "doi": s.get("doi")} for s in spec["sources"]])
    run("UNWIND $rows AS r CREATE (:Agent {id:r.id, role:r.role, tenant:r.tenant})",
        [{"id": a["id"], "role": a["role"], "tenant": spec["tenant"]} for a in spec["agents"]])

    obs = [{"src": o["source"], "id": o["id"], "text": o["text"], "at": epoch(o["observed_at"])}
           for o in spec["observations"]]
    run("UNWIND $rows AS r MATCH (s:Source {id:r.src}) "
        "CREATE (o:Mem:Observation {id:r.id, text:r.text, status:'IN', observed_at:r.at, agent:'intake', "
        "mtype:'episodic'}) "
        "CREATE (s)-[:SUPPORTS]->(o) CREATE (s)-[:FLOW {cap:1}]->(o) CREATE (o)-[:DEPENDS_ON]->(s)", obs)

    beliefs, plans, seen = [], [], set()
    for d in spec["derivations"]:
        c = d["conclusion"]
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        is_plan = c["kind"] == "plan"
        mtype = c.get("mtype") or (None if is_plan else "semantic")
        (plans if is_plan else beliefs).append({"id": c["id"], "text": c["text"], "agent": d["agent"], "mtype": mtype})
    run("UNWIND $rows AS r CREATE (:Mem:Belief {id:r.id, text:r.text, status:'IN', agent:r.agent, mtype:r.mtype})",
        beliefs)
    run("UNWIND $rows AS r CREATE (:Mem:Plan {id:r.id, text:r.text, status:'IN', agent:r.agent, mtype:r.mtype})",
        plans)
    run("UNWIND $rows AS r CREATE (:Mem:Action {id:r.id, tool:r.tool, amount:r.amount, executed:r.ex, "
        "executed_at:r.at, status:'IN', agent:r.agent, text:r.text})",
        [{"id": a["id"], "tool": a["tool"], "amount": a["amount"], "ex": a["executed"],
          "at": epoch(a["executed_at"]), "agent": a["agent"], "text": f"{a['tool']} {a['amount']}"}
         for a in spec["actions"]])

    known = {o["id"] for o in spec["observations"]} | seen | {a["id"] for a in spec["actions"]}
    just, prem, flow, holds = [], [], {}, set()
    triples = ([(d["id"], d["rule"], d["agent"], d["premises"], d["conclusion"]["id"]) for d in spec["derivations"]]
               + [(f"j_{a['id']}", "combine", a["agent"], a["premises"], a["id"]) for a in spec["actions"]])
    for jid, rule, agent, premises, concl in triples:
        just.append({"j": jid, "rule": rule, "agent": agent, "c": concl})
        holds.add((agent, concl))
        for p in premises:
            if p not in known:
                raise ValueError(f"fixture error: premise {p!r} of {jid!r} does not exist")
            prem.append({"p": p, "j": jid})
            flow[(p, concl)] = True            # MERGE semantics: one FLOW / DEPENDS_ON per (premise, conclusion)
    run("UNWIND $rows AS r MATCH (c:Mem {id:r.c}) "
        "CREATE (:Justification {id:r.j, rule:r.rule, agent:r.agent})-[:JUSTIFIES]->(c)", just)
    run("UNWIND $rows AS r MATCH (p:Mem {id:r.p}), (j:Justification {id:r.j}) CREATE (p)-[:PREMISE_OF]->(j)", prem)
    run("UNWIND $rows AS r MATCH (p:Mem {id:r.p}), (c:Mem {id:r.c}) "
        "CREATE (p)-[:FLOW {cap:r.cap}]->(c) CREATE (c)-[:DEPENDS_ON]->(p)",
        [{"p": p, "c": c, "cap": FLOW_CAP} for (p, c) in flow])
    run("UNWIND $rows AS r MATCH (a:Agent {id:r.a}), (m:Mem {id:r.m}) CREATE (a)-[:HOLDS]->(m)",
        [{"a": a, "m": m} for (a, m) in sorted(holds)])
    return g
