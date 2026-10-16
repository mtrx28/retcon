"""Graph-off ablation (task B7, rule 3 on camera): the same agents, the same attack, memory without the
graph's rules.

"Graph off" means exactly three things are taken away from the agents' memory, nothing else:
  1. retraction is similarity-only: the window's observations plus anything whose embedding is within a
     cosine threshold of them go OUT (the vector-store retraction rule, `bench.baselines.vector_only` when
     Lane A's version is present, otherwise the local rule below). No cascade, no re-derivation.
  2. no `fragility` / `why`: Payments cannot ask how many sources a payment rests on.
  3. no gate: `act` executes whatever is proposed (no premise check, no independent-source rule).
The memory itself, retrieval, agents, brain and bank are unchanged, so any difference is the graph.

    attacker_experiment(graph_off=False|True) -> what was paid to whom, before and after the retraction
"""
import copy
import math
import os
import time

from agents.brain import RuleBrain
from agents.orchestrator import Orchestrator, build_world
from agents.toolbox import LocalToolbox
from core.actions import ActionService
from core.retrieve.embed import get_embedder
from data.generator import generate
from gate.executors import SandboxExecutor

THRESHOLD = 0.75           # the contract's vector_only default (notes.threshold)
LATE = {"id": "late_inv", "source": "erp", "observed_at": "2026-10-10T11:00:00Z",
        "text": "Invoice INV-COASTAL-9 from Coastal Produce, 4000 USD."}
LATE_AMOUNT = 4000         # under the gate threshold: only the bank-account belief can stop a bad payment


def _cos(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return 0.0 if not na or not nb else sum(x * y for x, y in zip(a, b)) / (na * nb)


def vector_retract(graph, source, t_from, t_to, threshold=THRESHOLD):
    """Mark OUT the window's observations of `source` and every Mem within `threshold` cosine of one of them.
    Returns the set of ids made OUT. No graph traversal.

    The rule IS Lane A's `vector_only` baseline (CONTRACT v1.4: "the graph-off ablation's retraction rule"),
    so the ablation and the benchmark cannot drift apart. The local copy below is only a fallback for a
    checkout without bench/baselines."""
    try:
        from bench.api import Window
        from bench.baselines.vector_only import VectorOnly
    except ImportError:
        return _local_vector_retract(graph, source, t_from, t_to, threshold)
    out = set(VectorOnly(threshold=threshold).retract(graph, Window(source, t_from, t_to)).out_ids)
    if out:
        graph.query("MATCH (m:Mem) WHERE m.id IN $ids SET m.status = 'OUT'", {"ids": sorted(out)})
    return out


def _local_vector_retract(graph, source, t_from, t_to, threshold=THRESHOLD):
    from core.retract.cascade import to_epoch
    seeds = {r[0] for r in graph.query(
        "MATCH (:Source {id:$s})-[:SUPPORTS]->(o:Observation) WHERE o.observed_at >= $f AND o.observed_at <= $t "
        "RETURN o.id", {"s": source, "f": to_epoch(t_from), "t": to_epoch(t_to)}).result_set}
    vec = {r[0]: r[1] for r in graph.query(
        "MATCH (m:Mem) WHERE m.embedding IS NOT NULL RETURN m.id, m.embedding").result_set}
    out = set(seeds)
    for i, v in vec.items():
        if i in out:
            continue
        if any(s in vec and _cos(v, vec[s]) >= threshold for s in seeds):
            out.add(i)
    if out:
        graph.query("MATCH (m:Mem) WHERE m.id IN $ids SET m.status = 'OUT'", {"ids": sorted(out)})
    return out


class FlatActionService(ActionService):
    """`act` without a gate: record the action and execute it."""

    def execute(self, action_id):
        row = self.g.query("MATCH (a:Mem:Action {id:$id}) RETURN a.tool, a.args, a.executed",
                           {"id": action_id}).result_set
        tool, args_json, executed = row[0]
        if executed:
            return {"executed": True, "action_id": action_id, "already_executed": True}
        import json
        result = self.executor.execute(tool, json.loads(args_json or "{}"))
        self.g.query("MATCH (a:Mem:Action {id:$id}) SET a.executed = true, a.executed_at = $now, "
                     "a.gate_state = 'released', a.result = $res",
                     {"id": action_id, "now": int(time.time()), "res": json.dumps(result, default=str)})
        return {"executed": True, "action_id": action_id, "result": result, "warnings": ["graph off: no gate"]}


class FlatToolbox(LocalToolbox):
    def __init__(self, *a, threshold=THRESHOLD, **kw):
        super().__init__(*a, **kw)
        self.threshold = threshold
        self.removed = set()

    def _invoke(self, tool, args):
        if tool in ("fragility", "why", "recall_list", "reinstate", "list_remediations"):
            return {"error": {"code": "NOT_AVAILABLE", "message": f"{tool}: graph algorithms are off",
                              "details": {"graph_off": True}}}
        if tool == "distrust":
            out = vector_retract(self.graph, args["source"], args["from_"], args["to"], self.threshold)
            self.removed |= out
            return {"retraction_id": None, "mode": "vector_only", "flipped_ids": sorted(out),
                    "flipped": {"total": len(out)}, "threshold": self.threshold}
        return super()._invoke(tool, args)


def make_graph_off(world, threshold=THRESHOLD):
    """Swap a built world's gate and toolbox for the flat ones (in place)."""
    executor = SandboxExecutor(world.bank, world.inbox)
    world.actions = FlatActionService(world.graph, world.memory.capture, executor=executor, fragility_fn=None)
    flat = FlatToolbox(world.graph, world.memory, world.actions, executor, world.log, threshold=threshold)
    flat.graph = world.graph
    world.toolbox = flat
    return flat


def _truth_out(graph, window, tag):
    """What a correct retraction would make OUT in THIS graph: the real cascade on a GRAPH.COPY taken before
    anything is retracted. (The generator's ground-truth ids do not apply here: agents write content-hashed
    ids. The cascade itself is validated against an independent JTMS by tests/differential.)"""
    from core.retract import cascade
    name = f"{graph.name}_truth"
    try:
        graph.client.select_graph(name).delete()
    except Exception:  # noqa: BLE001
        pass
    fork = graph.copy(name)
    try:
        cascade.distrust(fork, window["source"], window["from"], window["to"])
        from core.db import fetch_all
        return {r[0] for r in fetch_all(fork, "MATCH (m:Mem {status:'OUT'}) RETURN m.id AS i", order_by="i")}
    finally:
        fork.delete()


def attacker_experiment(graph_off, seed=7, graph_name="bench_attack", threshold=THRESHOLD, embedder=None, vendors=2):
    """The seeded AP day, the portal compromise, the retraction, then one more invoice arrives.

    "Attacker" is precise: a payment to the portal-supplied account of a vendor whose portal was compromised.
    A legitimate account change at an uncompromised vendor is not an attack and is not counted.
    `vendors` > 2 adds look-alike clean vendors, which is what a similarity threshold pays for."""
    spec = generate(seed=seed, vendors=vendors, audit_incident=True)
    spec = copy.deepcopy(spec)
    spec["observations"].append(dict(LATE))
    attacker_iban = {v["id"]: v["iban_on_portal"] for v in spec["vendors"] if v["compromised"]}
    world = build_world(spec, graph_name=graph_name,
                        embedder=embedder or get_embedder(os.getenv("RETCON_EMBEDDER", "hash")))
    try:
        flat = make_graph_off(world, threshold) if graph_off else None
        orch = Orchestrator(world, brain=RuleBrain())
        orch.ingest_until("2026-10-08T23:59:59Z")
        n_before = len(world.bank.payments)
        w = spec["window"]
        truth = _truth_out(world.graph, w, graph_name)
        res = orch.distrust(w["source"], w["from"], w["to"])
        if not graph_off:
            orch.dispatch_events(res["retraction_id"])
        n_after_retraction = len(world.bank.payments)
        orch.ingest_until("2026-10-11T23:59:59Z")                 # the late invoice arrives and is processed
        vendor_of = {p["invoice"]: p["vendor"] for p in world.bank.payments}

        def bad(p):
            return p["iban"] == attacker_iban.get(vendor_of[p["invoice"]])

        after = world.bank.payments[n_after_retraction:]
        paid_before = world.bank.payments[:n_before]
        removed = flat.removed if flat else set(res.get("flipped_ids", []))
        # graph-derived truth: contaminated = OUT under a correct cascade; everything else was supported
        clean_removed = len(removed - truth)
        ver = [v for v in orch.verifications if v["sent"]]
        return {
            "graph_off": graph_off, "threshold": threshold if graph_off else None,
            "paid_attacker_before_retraction": sum(1 for p in paid_before if bad(p)),
            "paid_attacker_after_retraction": sum(1 for p in after if bad(p)),
            "amount_to_attacker_after": sum(p["amount"] for p in after if bad(p)),
            "paid_verified_after_retraction": sum(1 for p in after if not bad(p)),
            "payments_after_retraction": [{"invoice": p["invoice"], "amount": p["amount"], "to_attacker": bad(p)}
                                          for p in after],
            "verification_requests": len(ver),
            "nodes_retracted": len(removed),
            "contaminated_total": len(truth),
            "contaminated_retracted": len(removed & truth),
            "clean_nodes_retracted": clean_removed,
        }
    finally:
        world.close()


def threshold_sweep(thresholds=(0.3, 0.45, 0.6, 0.75, 0.9), **kw):
    """Does a looser similarity threshold rescue the vector-only memory? Reports the attacker payments it
    prevents against the clean nodes it destroys, so a good-looking number cannot hide its collateral."""
    rows = []
    for t in thresholds:
        r = attacker_experiment(True, threshold=t, graph_name=f"bench_attack_t{int(t * 100)}", **kw)
        rows.append({"threshold": t, "paid_attacker_after": r["paid_attacker_after_retraction"],
                     "contaminated_retracted": r["contaminated_retracted"], "contaminated_total": r["contaminated_total"],
                     "clean_nodes_retracted": r["clean_nodes_retracted"], "nodes_retracted": r["nodes_retracted"]})
    return rows
