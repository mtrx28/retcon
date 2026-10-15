"""B1+: mtype tagging on the write path + a retractable procedural rule.
Acceptance: python tasks.py accept B1+   (marker b1plus)"""
import pytest

from core.errors import RetconError
from core.memory import MemoryService
from core.retract.cascade import distrust, reinstate
from core.retrieve.embed import get_embedder
from core.retrieve.q2 import embed_graph
from data.generator import generate, validate
from data.generator.scenario import EPISODE_ID, RULE_ID, RULE_TEXT
from data.load_fixture import load

pytestmark = pytest.mark.b1plus


@pytest.fixture()
def mem():
    spec = generate(seed=7, vendors=2, audit_incident=True)
    emb = get_embedder("hash")
    g = load(spec, graph_name="test_b1plus")
    embed_graph(g, emb)
    return MemoryService(g, emb), spec


def one(g, q, **p):
    return g.query(q, p).result_set[0][0]


def test_generator_option_is_valid_and_off_by_default():
    assert validate(generate(seed=7, vendors=2, audit_incident=True)) == []
    assert "audit_incident" not in generate(seed=7, vendors=2)["meta"]
    base, with_rule = generate(seed=7, vendors=2), generate(seed=7, vendors=2, audit_incident=True)
    assert len(with_rule["observations"]) == len(base["observations"]) + 1
    assert RULE_ID in with_rule["ground_truth"]["truly_supported"]
    assert RULE_ID not in with_rule["ground_truth"]["contaminated"]


def test_all_three_mtypes_exist_after_a_seeded_run(mem):
    m, _ = mem
    # runtime path: Intake recalls an episode and writes a plain belief; a rule is learned from the audit episode
    m.recall("bank-detail change caught by callback verification", "intake", k=1)
    m.remember("Callback verification has caught a bank-change attempt before.", "belief", "intake")
    types = {r[0] for r in m.g.query("MATCH (x:Mem) WHERE x.mtype IS NOT NULL RETURN DISTINCT x.mtype").result_set}
    assert types == {"episodic", "semantic", "procedural"}


def test_procedural_rule_is_justified_by_an_episodic_node(mem):
    m, _ = mem
    rows = m.g.query(
        "MATCH (e:Mem)-[:PREMISE_OF]->(:Justification)-[:JUSTIFIES]->(r:Mem {id:$r}) "
        "RETURN r.mtype, e.id, e.mtype, labels(e)", {"r": RULE_ID}).result_set
    assert rows and rows[0][0] == "procedural"
    assert rows[0][1] == EPISODE_ID and rows[0][2] == "episodic" and "Observation" in rows[0][3]


def test_runtime_write_path_tags_and_checks(mem):
    m, _ = mem
    hits = m.recall("callback verification audit", "intake", k=1)
    assert hits[0]["id"] == EPISODE_ID
    r = m.learn_rule("Call the vendor on the contract number before changing any payee.", "intake", [EPISODE_ID])
    assert r["mtype"] == "procedural" and r["status"] == "IN"
    assert r["premise_ids"] == [EPISODE_ID]
    assert one(m.g, "MATCH (x:Mem {id:$i}) RETURN x.mtype", i=r["node_id"]) == "procedural"
    # default for a belief is semantic; a plan stays untagged
    m.begin_turn("analyst")
    m.recall("remit address", "analyst", k=2)
    b = m.remember("Address is consistent across sources.", "belief", "analyst")
    p = m.remember("Pay once the address check clears.", "plan", "analyst")
    assert b["mtype"] == "semantic" and p["mtype"] is None
    assert one(m.g, "MATCH (x:Mem {id:$i}) RETURN x.mtype", i=p["node_id"]) is None


def test_procedural_rule_needs_an_episode(mem):
    m, _ = mem
    # a derived belief is not an episode
    with pytest.raises(RetconError) as e:
        m.learn_rule("Rule built only on a derived belief.", "intake", ["coastal_b_bank_new"])
    assert e.value.code == "INVALID_ARGUMENT"
    with pytest.raises(RetconError) as e:
        m.remember("x", "belief", "intake", mtype="emotional")
    assert e.value.code == "INVALID_ARGUMENT"


def test_rule_is_retractable_and_survives_an_unrelated_distrust(mem):
    m, _ = mem
    g = m.g
    # the poisoned portal does not touch the rule: its episode is the audit log
    distrust(g, "coastal-portal", "2026-10-02T00:00:00Z", "2026-10-09T23:59:59Z")
    assert one(g, "MATCH (x:Mem {id:$r}) RETURN x.status", r=RULE_ID) == "IN"
    # but distrusting the audit log retracts the rule, and reinstating restores it exactly
    r = distrust(g, "audit-log", "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z")
    assert one(g, "MATCH (x:Mem {id:$r}) RETURN x.status", r=RULE_ID) == "OUT"
    reinstate(g, r["retraction_id"])
    assert one(g, "MATCH (x:Mem {id:$r}) RETURN x.status", r=RULE_ID) == "IN"
    assert RULE_TEXT.startswith("Verify bank-detail changes by callback")
