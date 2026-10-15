"""B3 / B3+: agent loop, four agents, handoffs, fragility-driven verification, re-plan on retraction.
Acceptance: python tasks.py accept B3

All runs are seeded and offline (hash embedder, rule brain). Seed 7: Coastal Produce invoices of
6,000 USD (under the gate threshold) and 34,500 USD (over it); Harbor Dairy is an unaffected vendor.
"""
import json
import os

import pytest

from agents.brain import RuleBrain
from agents.demo import run_day
from agents.llm_brain import LlmBrain
from agents.orchestrator import Orchestrator, build_world
from data.generator import generate

pytestmark = pytest.mark.b3

os.environ.setdefault("RETCON_EMBEDDER", "hash")


def q(g, cypher, **p):
    return g.query(cypher, p).result_set


@pytest.fixture(scope="module")
def day():
    r = run_day(seed=7, graph_name="b3_day")
    yield r
    r["world"].close()


@pytest.fixture(scope="module")
def pre_retraction():
    r = run_day(seed=7, retract=False, graph_name="b3_pre")
    yield r
    r["world"].close()


# ---- the working day (before any retraction) ------------------------------------------------

def test_each_agent_uses_its_tools_and_nothing_else(pre_retraction):
    log = pre_retraction["world"].log
    assert set(log.tools_used("intake")) == {"begin_turn", "observe", "remember"}
    assert set(log.tools_used("analyst")) == {"begin_turn", "recall", "remember"}
    assert set(log.tools_used("payments")) == {"begin_turn", "recall", "remember", "fragility", "why", "act"}
    assert set(log.tools_used("comms")) == {"begin_turn", "recall", "remember", "act"}
    assert not log.by_agent("operator")  # no operator involvement during the working day


def test_b3plus_over_threshold_invoice_gets_verification_not_payment(pre_retraction):
    w, orch = pre_retraction["world"], pre_retraction["orch"]
    paid = {p["invoice"]: p for p in w.bank.payments}
    assert "INV-COASTAL-2" not in paid and "INV-V001-2" not in paid     # 34,500 and 37,000: not paid
    assert paid["INV-COASTAL-1"]["amount"] == 6000                       # under the threshold: paid
    assert all(p["amount"] <= 10_000 for p in w.bank.payments)
    # the agent asked the graph first: fragility came before any act on that invoice
    calls = [(e["tool"], e["args"]) for e in w.log.by_agent("payments")]
    frag = max(i for i, (t, _) in enumerate(calls) if t == "fragility")
    assert not any(t == "act" and a["args"].get("invoice") == "INV-COASTAL-2" for t, a in calls)
    assert frag > 0
    ver = {v["invoice"]: v for v in orch.verifications}
    assert ver["INV-COASTAL-2"]["sent"] and ver["INV-V001-2"]["sent"]
    sent = [m for m in w.inbox.outbox if m["subject"].startswith("Callback verification")]
    assert {m["to"] for m in sent} == {"ar@coastal.example.test", "ar@v001.example.test"}


def test_fragility_result_is_what_drove_the_decision(pre_retraction):
    log = pre_retraction["world"].log
    results = [e["result"] for e in log.by_agent("payments") if e["tool"] == "fragility"]
    assert results and all(r["independent_sources"] == 1 and r["bound"] == "exact" for r in results)
    ledger = pre_retraction["orch"].ledger
    verify = [v for v in ledger.values() if v["decision"] == "verify"]
    assert {v["invoice"] for v in verify} == {"INV-COASTAL-2", "INV-V001-2"}
    assert all(v["cost"] == 1 for v in verify)


def test_handoffs_are_justification_edges_across_agents(pre_retraction):
    g = pre_retraction["world"].graph
    rows = q(g, "MATCH (j:Justification {rule:'handoff'})-[:JUSTIFIES]->(m:Mem) RETURN m.agent, count(j)")
    by_agent = {a: n for a, n in rows}
    assert by_agent.get("analyst", 0) >= 2     # bank-change review notes
    assert by_agent.get("comms", 0) >= 2       # vendor confirmations
    assert by_agent.get("payments", 0) >= 4    # plans and hold notes built from others' beliefs
    # laundering is real in the graph: the Comms note traces back to the portal observation
    row = q(g, "MATCH (n:Mem {agent:'comms'}) WHERE n.text STARTS WITH 'Comms note: vendor confirmed' "
               "RETURN n.id LIMIT 1")
    assert row


def test_all_three_mtypes_exist_and_the_rule_is_justified_by_an_episode(pre_retraction):
    g = pre_retraction["world"].graph
    assert {r[0] for r in q(g, "MATCH (m:Mem) WHERE m.mtype IS NOT NULL RETURN DISTINCT m.mtype")} == {
        "episodic", "semantic", "procedural"}
    rows = q(g, "MATCH (e:Observation)-[:PREMISE_OF]->(:Justification)-[:JUSTIFIES]->(r:Mem {mtype:'procedural'}) "
                "RETURN r.text, e.text")
    assert rows and rows[0][0].startswith("Verify bank-detail changes by callback")
    assert "callback verification" in rows[0][1]


# ---- retraction -> events -> re-plan ----------------------------------------------------------

def test_retraction_flips_the_laundered_chain_and_spares_the_rest(day):
    g, d = day["world"].graph, day["distrust"]
    assert d["flipped"]["observations"] == 2 and d["flipped"]["plans"] == 2 and d["flipped"]["actions"] == 2
    # the executed 6,000 payment is on the recall list, with a draft recall awaiting approval
    assert [a["amount"] for a in d["recall_list"] if a["amount"]] == [6000]
    assert any(r["kind"] == "bank_recall" and r["status"] == "draft" for r in d["remediations"])
    # the independently supported address and the other vendor are untouched
    assert q(g, "MATCH (m:Mem {text:'Coastal Produce remit address is ' + $a}) RETURN m.status",
             a=day["spec"]["vendors"][0]["address"] + ".")[0][0] == "IN"
    assert {r[0] for r in q(g, "MATCH (p:Plan) WHERE p.text CONTAINS 'V001' RETURN p.status")} == {"IN"}
    # the audit-log rule survives: its episode is independent of the portal
    assert q(g, "MATCH (r:Mem {mtype:'procedural'}) RETURN r.status")[0][0] == "IN"


def test_events_follow_holds_and_name_invalidated_plans(day):
    events = day["events"]
    pay = [e for e in events if e["agent"] == "payments" and e["invalidated_plan_ids"]]
    assert pay, "payments must receive an event with invalidated plans"
    e = pay[0]
    assert set(e) >= {"retraction_id", "agent", "belief_id", "reason", "invalidated_plan_ids"}
    assert e["retraction_id"] == day["distrust"]["retraction_id"]
    assert "coastal-portal" in e["reason"]
    assert len(e["invalidated_plan_ids"]) == 2 and len(e["invalidated_action_ids"]) == 1
    assert not [x for x in events if x["agent"] == "payments" and "V001" in str(x)]


def test_payments_replans_to_the_verified_account_and_does_not_repay(day):
    w, orch = day["world"], day["orch"]
    g = w.graph
    contract_iban = day["spec"]["vendors"][0]["iban_on_contract"]
    portal_iban = day["spec"]["vendors"][0]["iban_on_portal"]
    plans = [tuple(r) for r in q(g, "MATCH (p:Plan) WHERE p.text CONTAINS 'INV-COASTAL-2' RETURN p.text, p.status")]
    assert (f"Pay INV-COASTAL-2 34500 USD to {contract_iban}.", "IN") in plans
    assert (f"Pay INV-COASTAL-2 34500 USD to {portal_iban}.", "OUT") in plans
    assert any("re-planned" in s for _, t, s in orch.results if t == "retraction_event")
    assert any("left to the Remediator" in s for _, t, s in orch.results if t == "retraction_event")
    # no second payment was made for the invoice that already went out
    assert [p["invoice"] for p in w.bank.payments].count("INV-COASTAL-1") == 1
    # and the re-plan asked for verification again instead of paying 34,500
    assert all(p["amount"] <= 10_000 for p in w.bank.payments)
    last = [v for v in orch.verifications if v["invoice"] == "INV-COASTAL-2"][-1]
    assert contract_iban in last["plan_text"]


def test_replan_context_is_scoped_to_the_vendor(day):
    """No premise of Coastal's re-planned payment may come from another vendor's portal."""
    g = day["world"].graph
    contract_iban = day["spec"]["vendors"][0]["iban_on_contract"]
    pid = q(g, "MATCH (p:Plan {status:'IN'}) WHERE p.text = $t RETURN p.id",
            t=f"Pay INV-COASTAL-2 34500 USD to {contract_iban}.")[0][0]
    texts = [r[0] for r in q(g, "MATCH (x:Mem)-[:PREMISE_OF]->(:Justification)-[:JUSTIFIES]->(:Mem {id:$p}) "
                                "RETURN x.text", p=pid)]
    assert texts and not any("Harbor Dairy" in t for t in texts), texts


# ---- defence in depth, transports, determinism ----------------------------------------------

def test_gate_still_blocks_when_the_agent_skips_its_own_check():
    spec = generate(seed=7, vendors=2, audit_incident=True)
    world = build_world(spec, graph_name="b3_gate")
    try:
        orch = Orchestrator(world, brain=RuleBrain({"pay_rule": None}))
        orch.ingest_until("2026-10-08T23:59:59Z")
        led = {v["invoice"]: v for v in orch.ledger.values()}
        assert led["INV-COASTAL-2"]["decision"] == "blocked"
        why = led["INV-COASTAL-2"]["blocked"]["blocked_reason"]
        assert why["code"] == "BLOCKED_BY_POLICY"
        assert why["details"]["reason_code"] == "INSUFFICIENT_INDEPENDENT_SOURCES"
        assert why["details"]["independent_sources"] == 1 and why["details"]["required"] == 2
        assert all(p["amount"] <= 10_000 for p in world.bank.payments)
    finally:
        world.close()


def test_run_is_deterministic():
    a = run_day(seed=7, graph_name="b3_det_a")
    b = run_day(seed=7, graph_name="b3_det_b")
    assert a["world"].log.to_jsonl() == b["world"].log.to_jsonl()
    assert a["orch"].results == b["orch"].results
    a["world"].close(), b["world"].close()


def test_same_run_over_real_mcp(day):
    r = run_day(seed=7, transport="mcp", graph_name="b3_mcp")
    try:
        def shape(log):
            return [(e["agent"], e["tool"], json.dumps(e["args"], sort_keys=True)) for e in log.entries]
        assert shape(r["world"].log) == shape(day["world"].log)
        assert [(p["invoice"], p["amount"]) for p in r["world"].bank.payments] == \
               [(p["invoice"], p["amount"]) for p in day["world"].bank.payments]
        assert r["orch"].results == day["orch"].results
    finally:
        r["world"].close()


# ---- LLM brain plumbing (no network: the model is a function) ---------------------------------

def test_llm_brain_drives_a_task_caches_and_survives_garbage(tmp_path):
    replies = iter([
        '{"tool": "begin_turn", "args": {}}',
        'Sure! {"tool": "recall", "args": {"query": "Coastal Produce bank account IBAN", "k": 2}}',
        '{"done": true, "summary": "looked up the account", "handoffs": []}',
    ])
    calls = []

    def complete(prompt):
        calls.append(prompt)
        return next(replies)

    spec = generate(seed=7, vendors=2, audit_incident=True)
    world = build_world(spec, graph_name="b3_llm")
    try:
        brain = LlmBrain(complete, cache_dir=tmp_path)
        orch = Orchestrator(world, brains={"payments": brain})
        step = orch.run_task("payments", {"type": "anything"})
        assert step.summary == "looked up the account"
        assert world.log.tools_used("payments") == ["begin_turn", "recall"]
        assert len(calls) == 3 and "Tool calls so far" in calls[0]
        # replay: identical task, no model calls needed
        offline = LlmBrain(lambda p: 1 / 0, cache_dir=tmp_path, offline=True)
        step = Orchestrator(world, brains={"payments": offline}).run_task("payments", {"type": "anything"})
        assert step.summary == "looked up the account"
        # garbage and unknown tools end the task, they do not crash the loop
        for bad in ("no json at all", '{"tool": "drop_database", "args": {}}'):
            b = LlmBrain(lambda p, bad=bad: bad, cache_dir=tmp_path / "bad")
            s = Orchestrator(world, brains={"payments": b}).run_task("payments", {"type": "x"})
            assert s.summary.startswith("aborted")
    finally:
        world.close()
