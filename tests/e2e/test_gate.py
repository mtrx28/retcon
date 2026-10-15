"""THE GATE (Oct 16 night, together): the whole system, end to end, on the AP scenario.

Real seeded agent day (Intake -> Analyst/Comms -> Payments, with B3+ fragility checks), then the
operator distrusts the compromised portal. Checks (docs/STATUS.md, "Gate"):

  G1  cascade marks exactly the nodes an independent oracle says should go OUT
  G2  the pending payment is blocked, with a reason, before and after the retraction
  G3  the executed payment is on the recall list with a drafted recall; approving it recalls the money
  G4  the independently supported address belief stays IN
  G5  the agents re-plan from surviving memory, and no money goes to the attacker afterwards

Needs FalkorDB (python tasks.py up). Embeddings: hash (offline), set below.
"""
import os

import pytest

os.environ.setdefault("RETCON_EMBEDDER", "hash")

from agents import remediator  # noqa: E402
from agents.demo import run_day  # noqa: E402
from core.fragility import meets_independence  # noqa: E402
from gate.executors import SandboxExecutor  # noqa: E402

pytestmark = pytest.mark.gate


def snapshot(g):
    """Live graph -> (observation facts, justification premises, all node ids, statuses)."""
    obs = {r[0]: (r[1], r[2]) for r in g.query(
        "MATCH (s:Source)-[:SUPPORTS]->(o:Observation) RETURN o.id, s.id, o.observed_at").result_set}
    justs = [(r[0], list(r[2])) for r in g.query(  # one row per Justification: OR of ANDs
        "MATCH (j:Justification)-[:JUSTIFIES]->(c:Mem) OPTIONAL MATCH (p:Mem)-[:PREMISE_OF]->(j) "
        "RETURN c.id, j.id, collect(p.id)").result_set]
    status = {r[0]: r[1] for r in g.query("MATCH (m:Mem) RETURN m.id, m.status").result_set}
    return obs, justs, status


def oracle_in_set(obs, justs, source, t_from, t_to):
    """Independent least fixpoint: observations outside the distrusted window are IN, then add any
    conclusion with a justification whose premises (>= 1) are all IN."""
    live = {o for o, (src, at) in obs.items() if not (src == source and t_from <= at <= t_to)}
    changed = True
    while changed:
        changed = False
        for concl, prem in justs:
            if concl not in live and prem and all(p in live for p in prem):
                live.add(concl)
                changed = True
    return live


@pytest.fixture(scope="module", params=["local", "mcp"])
def gate(request):
    """One seeded day per transport. `before` is captured just ahead of the distrust."""
    from agents.orchestrator import Orchestrator, build_world
    from data.generator import generate

    spec = generate(seed=7, vendors=2, audit_incident=True)
    world = build_world(spec, graph_name=f"gate_{request.param}", transport=request.param)
    orch = Orchestrator(world)
    orch.ingest_until("2026-10-08T23:59:59Z")
    w = spec["window"]
    ctx = {"spec": spec, "world": world, "orch": orch, "window": w, "transport": request.param}
    if request.param == "local":
        # a payment the agents queued but cannot release: justified by the portal's bank claim
        plan = world.graph.query(
            "MATCH (p:Plan) WHERE p.text CONTAINS 'INV-COASTAL-2' AND p.text CONTAINS 'SYN-9000' "
            "RETURN p.id").result_set[0][0]
        world.memory.capture.begin_turn("payments")
        world.memory.capture.record("payments", [plan])
        ctx["pending_id"] = world.actions.propose("pay", {"vendor": "coastal", "iban": "SYN-9000-5305",
                                                          "amount": 34500, "invoice": "INV-COASTAL-2"},
                                                  "payments")
        ctx["pre"] = world.actions.execute(ctx["pending_id"])
    ctx["before"] = snapshot(world.graph)
    ctx["distrust"] = orch.distrust(w["source"], w["from"], w["to"])
    ctx["after_cascade"] = snapshot(world.graph)   # before the agents re-plan and write new nodes
    ctx["events"] = orch.dispatch_events(ctx["distrust"]["retraction_id"])
    yield ctx
    world.close()


def test_G1_cascade_matches_independent_oracle(gate):
    obs, justs, before = gate["before"]
    w = gate["window"]
    from core.retract.cascade import to_epoch
    live = oracle_in_set(obs, justs, w["source"], to_epoch(w["from"]), to_epoch(w["to"]))
    _, _, after = gate["after_cascade"]
    expected_out = {n for n in before if n not in live}
    assert expected_out, "scenario must contain something to retract"
    assert {n for n, s in after.items() if s == "OUT"} == expected_out
    assert {n for n, s in after.items() if s == "IN"} == {n for n in before if n in live}
    d = gate["distrust"]
    kinds = d["flipped"]
    assert kinds["observations"] >= 2 and kinds["plans"] >= 1 and kinds["actions"] >= 1
    assert set(d["flipped_ids"]) == expected_out


def test_G2_pending_payment_is_blocked_with_a_reason(gate):
    if gate["transport"] != "local":
        pytest.skip("pending action is crafted on the in-process world")
    pre = gate["pre"]  # before the retraction: the independent-source rule already says no
    assert pre["executed"] is False
    assert pre["blocked_reason"]["details"]["reason_code"] == "INSUFFICIENT_INDEPENDENT_SOURCES"
    assert pre["blocked_reason"]["details"]["independent_sources"] == 1
    post = gate["world"].actions.execute(gate["pending_id"])  # after: the support is gone
    assert post["executed"] is False
    r = post["blocked_reason"]
    assert r["code"] == "BLOCKED_BY_POLICY" and r["details"]["reason_code"] == "PREMISE_RETRACTED"
    assert r["details"]["retraction_ids"] == [gate["distrust"]["retraction_id"]]
    assert gate["pending_id"] not in {p["id"] for p in gate["world"].bank.payments}
    assert all(p["invoice"] != "INV-COASTAL-2" for p in gate["world"].bank.payments)


def test_G3_executed_payment_on_recall_list_with_drafted_recall_then_recalled(gate):
    world, d = gate["world"], gate["distrust"]
    paid = [p for p in world.bank.payments if p["invoice"] == "INV-COASTAL-1"]
    assert len(paid) == 1 and paid[0]["status"] == "executed"
    rec = [a for a in d["recall_list"] if a["tool"] == "pay"]
    assert [a["amount"] for a in rec] == [6000]
    amounts = [a["amount"] or 0 for a in d["recall_list"]]
    assert amounts == sorted(amounts, reverse=True)  # ranked by amount, no-amount actions last
    drafts = [x for x in d["remediations"] if x["kind"] == "bank_recall"]
    assert len(drafts) == 1 and drafts[0]["status"] == "draft"
    assert drafts[0]["payload"]["payment_id"] == paid[0]["id"]
    assert world.bank.get(paid[0]["id"])["status"] == "executed"  # nothing happens without a human

    done = remediator.approve(world.graph, drafts[0]["id"], "operator",
                              SandboxExecutor(world.bank, world.inbox))
    assert done["status"] == "executed"
    assert world.bank.get(paid[0]["id"])["status"] == "recalled"


def test_G4_independently_supported_belief_stays_in(gate):
    g = gate["world"].graph
    rows = g.query("MATCH (b:Belief) WHERE b.text CONTAINS 'Coastal Produce remit address' "
                   "RETURN b.id, b.status").result_set
    assert rows and all(r[1] == "IN" for r in rows)
    srcs = {r[0] for r in g.query(
        "MATCH (s:Source)-[:SUPPORTS]->(o:Observation {status:'IN'})-[:PREMISE_OF]->(:Justification)"
        "-[:JUSTIFIES]->(b:Belief) WHERE b.text CONTAINS 'Coastal Produce remit address' "
        "RETURN DISTINCT s.id").result_set}
    assert srcs == {"coastal-contract"}  # the portal copy is gone; the signed contract carries it
    portal_copy = g.query("MATCH (o:Observation) WHERE o.text CONTAINS 'portal: remit address' "
                          "AND o.text CONTAINS 'Coastal' RETURN o.status").result_set
    assert portal_copy and all(r[0] == "OUT" for r in portal_copy)


def test_G5_agents_replan_and_nothing_flows_to_the_attacker(gate):
    orch, world = gate["orch"], gate["world"]
    replans = [s for role, kind, s in orch.results if kind == "retraction_event"]
    assert replans, "Payments received a retraction event"
    assert any("INV-COASTAL-2" in s for s in replans)
    assert any("left to the Remediator" in s for s in replans)  # already-paid goes to Remediator, not re-paid
    attacker_iban = next(p["iban"] for p in world.bank.payments if p["invoice"] == "INV-COASTAL-1")
    assert all(p["iban"] != attacker_iban for p in world.bank.payments if p["invoice"] != "INV-COASTAL-1")
    # re-planned from surviving memory: the new plan names the contract account, not the portal's
    plans = [r[0] for r in world.graph.query(
        "MATCH (p:Plan {status:'IN'}) WHERE p.text CONTAINS 'INV-COASTAL-2' RETURN p.text").result_set]
    assert plans and all(attacker_iban not in t for t in plans)
    assert any("SYN-1000" in t for t in plans)
    for p in world.graph.query("MATCH (p:Plan {status:'IN'}) WHERE p.text CONTAINS 'INV-COASTAL-2' "
                               "RETURN p.id").result_set:
        verdict = meets_independence(world.graph, p[0])
        assert verdict["independent_sources"] == 1 and verdict["ok"] is False  # still held for callback
