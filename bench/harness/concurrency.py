"""B11: concurrency and tenancy.

`run_concurrency` starts N writer threads (each its own connection, agent and premise-capture context,
doing recall -> remember like a real agent) and, part-way through, runs a cascade (`distrust`) on the same
graph. It measures first and reports what it saw:
  - per-operation latency (p50/p95) for reads (`recall`) and writes (`remember`), and the cascade's
  - error rate and error types
  - consistency afterwards: every stored status compared with an independent least-fixpoint recomputed
    from the final graph. `stale_in` (stored IN, should be OUT) is the dangerous direction: a retracted
    claim still believed. `stale_out` (stored OUT, should be IN) loses a supported claim.

`tenant_isolation` loads two tenants, fingerprints B, does heavy work + a cascade in A, and checks B is
byte-identical and that A's retrieval never returns B's nodes.
"""
import threading
import time
from collections import Counter

from bench.harness.fingerprint import fingerprint
from bench.harness.loader import load_batched
from bench.harness.runner import stats
from core.db import connect, fetch_all
from core.memory import MemoryService
from core.retract.cascade import distrust
from core.retrieve.embed import get_embedder

QUERIES = ["bank account IBAN", "remit address", "invoice matches purchase order", "opening hours",
           "contract bank", "payment plan", "portal notice", "vendor confirmation"]


def reference_statuses(g):
    """Least fixpoint from the stored status of observations: {mem_id: 'IN'|'OUT'} for derived nodes."""
    obs = {r[0]: r[1] for r in fetch_all(g, "MATCH (o:Observation) RETURN o.id AS i, o.status", order_by="i")}
    derived = [r[0] for r in fetch_all(g, "MATCH (m:Mem) WHERE NOT m:Observation RETURN m.id AS i", order_by="i")]
    prem = {}
    for jid, concl, pid in fetch_all(
            g, "MATCH (j:Justification)-[:JUSTIFIES]->(c:Mem) OPTIONAL MATCH (p:Mem)-[:PREMISE_OF]->(j) "
               "RETURN j.id AS j, c.id AS c, p.id AS p", order_by="j, p"):
        prem.setdefault(jid, (concl, []))[1].append(pid)
    live = {o for o, s in obs.items() if s == "IN"}
    changed = True
    while changed:
        changed = False
        for concl, ps in prem.values():
            if concl not in live and ps and all(p in live for p in ps if p):
                live.add(concl)
                changed = True
    return {m: ("IN" if m in live else "OUT") for m in derived}


def consistency(g):
    ref = reference_statuses(g)
    stored = {r[0]: r[1] for r in fetch_all(
        g, "MATCH (m:Mem) WHERE NOT m:Observation RETURN m.id AS i, m.status", order_by="i")}
    stale_in = sorted(i for i, s in stored.items() if s == "IN" and ref.get(i) == "OUT")
    stale_out = sorted(i for i, s in stored.items() if s == "OUT" and ref.get(i) == "IN")
    orphans = [r[0] for r in fetch_all(
        g, "MATCH (m:Mem) WHERE NOT m:Observation AND NOT ()-[:JUSTIFIES]->(m) RETURN m.id AS i", order_by="i")]
    leftover = g.query("MATCH (m:Mem) WHERE m.run IS NOT NULL RETURN count(m)").result_set[0][0]
    return {"checked": len(stored), "stale_in": len(stale_in), "stale_out": len(stale_out),
            "stale_in_ids": stale_in[:5], "stale_out_ids": stale_out[:5],
            "unjustified": len(orphans), "run_tags_left": leftover}


QUEUE_FULL = "Max pending queries exceeded"       # FalkorDB MAX_QUEUED_QUERIES (default 25)
RETRIES, BACKOFF_MS = 8, 4.0


def _call(fn, results):
    """Run one operation as a well-behaved client: when the server's query queue is full (it rejects loudly,
    it does not drop work) back off and retry. Rejections are counted; latency includes the waiting, because
    that is what the caller experienced."""
    for attempt in range(RETRIES + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if QUEUE_FULL not in str(e) or attempt == RETRIES:
                raise
            results["rejected"] += 1
            time.sleep(BACKOFF_MS * (2 ** min(attempt, 4)) / 1000)


def _writer(idx, graph_name, ops, start, embedder, results, barrier):
    g = connect().select_graph(graph_name)
    mem = MemoryService(g, embedder)
    agent = f"writer_{idx}"
    barrier.wait()
    start.wait()
    for k in range(ops):
        q = QUERIES[(idx + k) % len(QUERIES)]
        try:
            mem.begin_turn(agent)
            t0 = time.perf_counter()
            hits = _call(lambda: mem.recall(q, agent, k=3), results)
            results["read"].append((time.perf_counter() - t0) * 1000)
            if not hits:
                results["empty_reads"] += 1
                continue
            t0 = time.perf_counter()
            _call(lambda: mem.remember(f"Writer {idx} note {k}: {q} reviewed.", "belief", agent), results)
            results["write"].append((time.perf_counter() - t0) * 1000)
        except Exception as e:  # noqa: BLE001 - errors are data here
            results["errors"][type(e).__name__ + ": " + str(e)[:80]] += 1


def run_concurrency(spec, n_writers=20, ops_per_writer=10, with_cascade=True, graph_name="bench_conc",
                    embedder=None, cascade_after=0.0):
    """One run. Returns a JSON-able report. `spec` needs a `window` (AP scenarios have one)."""
    embedder = embedder or get_embedder("hash")
    db = connect()
    g = load_batched(spec, db=db, graph_name=graph_name)
    # writers need embeddings on the existing nodes to retrieve anything
    from core.retrieve.q2 import embed_graph
    embed_graph(g, embedder)

    results = {"read": [], "write": [], "errors": Counter(), "empty_reads": 0, "rejected": 0}
    barrier = threading.Barrier(n_writers + 1)
    start = threading.Event()
    threads = [threading.Thread(target=_writer, args=(i, graph_name, ops_per_writer, start, embedder, results, barrier),
                                daemon=True) for i in range(n_writers)]
    for t in threads:
        t.start()
    barrier.wait()
    t_run = time.perf_counter()
    start.set()
    cascade = None
    if with_cascade:
        time.sleep(cascade_after)
        w = spec["window"]
        t0 = time.perf_counter()
        try:
            cg = connect().select_graph(graph_name)
            res = distrust(cg, w["source"], w["from"], w["to"])
            cascade = {"ms": round((time.perf_counter() - t0) * 1000, 2), "flipped": len(res["flipped_ids"])}
        except Exception as e:  # noqa: BLE001
            results["errors"]["cascade " + type(e).__name__ + ": " + str(e)[:80]] += 1
    for t in threads:
        t.join(timeout=300)
    wall = time.perf_counter() - t_run
    ops = len(results["read"]) + len(results["write"])
    attempted = n_writers * ops_per_writer * 2
    n_err = sum(results["errors"].values())
    return {
        "writers": n_writers, "ops_per_writer": ops_per_writer, "with_cascade": with_cascade,
        "nodes_before": spec_nodes(spec),
        "read_ms": stats(results["read"]), "write_ms": stats(results["write"]),
        "cascade": cascade, "wall_s": round(wall, 2), "throughput_ops_s": round(ops / wall, 1) if wall else None,
        "errors": dict(results["errors"]), "error_rate": round(n_err / attempted, 4) if attempted else 0.0,
        "rejected_by_server": results["rejected"],      # queue-full rejections, all retried with back-off
        "empty_reads": results["empty_reads"],
        "consistency": consistency(connect().select_graph(graph_name)),
    }


def spec_nodes(spec):
    return len(spec["observations"]) + len({d["conclusion"]["id"] for d in spec["derivations"]}) + len(spec["actions"])


def sweep(spec, writers=(1, 10, 20, 50), ops_per_writer=10, **kw):
    return [run_concurrency(spec, n, ops_per_writer, graph_name=f"bench_conc_{n}", **kw) for n in writers]


TENANT_B_MARK = " (tenant B)"


def tenant_isolation(spec_a, spec_b, n_writers=10, ops_per_writer=8, embedder=None):
    """Tenant B must be byte-identical after heavy work and a cascade in tenant A, and A's retrieval must
    never return B's content. Generated tenants reuse ids, so B's text is marked and a leak is any hit in A
    carrying the mark."""
    import copy
    embedder = embedder or get_embedder("hash")
    spec_b = copy.deepcopy(spec_b)
    for o in spec_b["observations"]:
        o["text"] += TENANT_B_MARK
    for d in spec_b["derivations"]:
        d["conclusion"]["text"] += TENANT_B_MARK
    db = connect()
    name_a, name_b = "bench_tenant_a", "bench_tenant_b"
    gb = load_batched(spec_b, db=db, graph_name=name_b)
    before = fingerprint(gb)
    report = run_concurrency(spec_a, n_writers, ops_per_writer, True, graph_name=name_a, embedder=embedder)
    after = fingerprint(db.select_graph(name_b))
    ga = db.select_graph(name_a)
    leaked = 0
    mem = MemoryService(ga, embedder)
    for q in QUERIES:
        leaked += sum(1 for h in mem.recall(q, "auditor", k=20) if TENANT_B_MARK in h["text"])
    retractions_b = db.select_graph(name_b).query("MATCH (r:Retraction) RETURN count(r)").result_set[0][0]
    return {"b_before": before, "b_after": after, "b_identical": before == after, "leaked_into_a": leaked,
            "retractions_in_b": retractions_b, "a": report}
