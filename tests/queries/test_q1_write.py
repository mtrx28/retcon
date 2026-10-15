"""B1: Q1 justified write + automatic premise capture. Acceptance: python tasks.py accept B1"""
import json
from pathlib import Path

import pytest

from core.errors import RetconError
from core.memory import MemoryService
from core.retrieve.embed import get_embedder
from core.retrieve.q2 import embed_graph
from data.load_fixture import load

pytestmark = pytest.mark.b1
FIX = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "ap_tiny.json"


@pytest.fixture()
def mem():
    emb = get_embedder("hash")
    g = load(json.loads(FIX.read_text(encoding="utf8")), graph_name="test_b1")
    embed_graph(g, emb)
    return MemoryService(g, emb)


def one(g, q, **p):
    return g.query(q, p).result_set[0][0]


def test_observation_has_all_edges(mem):
    r = mem.observe("erp", "Invoice INV-2000 from Coastal Produce, 500 USD.", 1760000000)
    g = mem.g
    assert one(g, "MATCH (:Source {id:'erp'})-[:SUPPORTS]->(o {id:$i}) RETURN o.status", i=r["node_id"]) == "IN"
    assert one(g, "MATCH (:Source {id:'erp'})-[f:FLOW]->(o {id:$i}) RETURN f.cap", i=r["node_id"]) == 1
    assert one(g, "MATCH (o {id:$i})-[:DEPENDS_ON]->(:Source {id:'erp'}) RETURN count(*)", i=r["node_id"]) == 1


def test_remember_captures_exactly_the_recalled_context(mem):
    hits = mem.recall("Coastal Produce address", "analyst", k=3)
    ids = {h["id"] for h in hits}
    r = mem.remember("Remit address confirmed for vendor run.", "belief", "analyst")
    assert set(r["premise_ids"]) == ids and r["status"] == "IN" and r["created"]
    g = mem.g
    jid = r["justification_id"]
    assert one(g, "MATCH (p)-[:PREMISE_OF]->(:Justification {id:$j}) RETURN count(p)", j=jid) == len(ids)
    assert one(g, "MATCH (:Justification {id:$j})-[:JUSTIFIES]->(m {id:$m}) RETURN count(m)", j=jid, m=r["node_id"]) == 1
    assert one(g, "MATCH (:Agent {id:'analyst'})-[:HOLDS]->(m {id:$m}) RETURN count(m)", m=r["node_id"]) == 1
    assert one(g, "MATCH (p)-[f:FLOW]->(m {id:$m}) RETURN count(f)", m=r["node_id"]) == len(ids)
    assert one(g, "MATCH (m {id:$m})-[:DEPENDS_ON]->(p) RETURN count(p)", m=r["node_id"]) == len(ids)


def test_write_is_idempotent(mem):
    mem.recall("bank IBAN", "analyst", k=2)
    a = mem.remember("Bank detail check pending.", "plan", "analyst")
    b = mem.remember("Bank detail check pending.", "plan", "analyst")
    assert a["node_id"] == b["node_id"] and a["justification_id"] == b["justification_id"] and not b["created"]
    assert one(mem.g, "MATCH (m {id:$m}) RETURN count(m)", m=a["node_id"]) == 1
    assert one(mem.g, "MATCH (j:Justification)-[:JUSTIFIES]->(m {id:$m}) RETURN count(j)", m=a["node_id"]) == 1


def test_second_justification_is_an_or(mem):
    mem.recall("opening hours", "analyst", k=1)
    a = mem.remember("Vendor depot opens early morning.", "belief", "analyst")
    mem.begin_turn("analyst")
    mem.recall("holiday closure notice", "analyst", k=1)
    b = mem.remember("Vendor depot opens early morning.", "belief", "analyst")
    assert a["node_id"] == b["node_id"] and a["justification_id"] != b["justification_id"]
    assert one(mem.g, "MATCH (j:Justification)-[:JUSTIFIES]->(m {id:$m}) RETURN count(j)", m=a["node_id"]) == 2


def test_out_premise_makes_new_node_out(mem):
    mem.recall("bank IBAN new account", "analyst", k=1)
    pid = mem.capture.context("analyst")[0]
    mem.g.query("MATCH (m:Mem {id:$i}) SET m.status='OUT'", {"i": pid})  # retracted after retrieval
    r = mem.remember("Stale-context conclusion.", "belief", "analyst")
    assert r["status"] == "OUT"


def test_errors_use_contract_codes(mem):
    with pytest.raises(RetconError) as e:
        mem.remember("No context at all.", "belief", "payments")
    assert e.value.as_payload()["error"]["code"] == "INVALID_ARGUMENT"
    mem.capture.record("payments", ["does_not_exist"])
    with pytest.raises(RetconError) as e:
        mem.remember("Ghost premise.", "belief", "payments")
    assert e.value.code == "NOT_FOUND"
    with pytest.raises(RetconError) as e:
        mem.remember("x", "action", "payments")
    assert e.value.code == "INVALID_ARGUMENT"


def test_new_belief_is_reached_by_lane_a_cascade(mem):
    """Edges written by Q1 must be walkable by the Q3/Q4 queries from docs/SPIKE.md."""
    mem.recall("portal bank details changed", "analyst", k=1)
    r = mem.remember("Derived from the tainted portal bank claim.", "belief", "analyst")
    mem.g.query("MATCH (s:Source {id:'coastal-portal'})-[:SUPPORTS]->(o:Observation) "
                "SET o.status='OUT', o.run='r1'")
    mem.g.query("MATCH (o:Observation {run:'r1'})-[:PREMISE_OF|JUSTIFIES*1..12]->(x:Mem) "
                "WHERE x.status='IN' WITH DISTINCT x SET x.status='OUT', x.run='r1'")
    assert one(mem.g, "MATCH (m {id:$m}) RETURN m.status", m=r["node_id"]) == "OUT"
