"""B5: Q7 poisoning cost (exact JTMS min-cut), engine max-flow upper bound, gate-policy hook.
Acceptance: python tasks.py accept B5"""
import json
from pathlib import Path

import pytest

from core.errors import RetconError
from core.fragility import fragility, meets_independence
from core.fragility import q7
from core.memory import MemoryService
from core.retract.cascade import distrust
from core.retrieve.embed import get_embedder
from core.retrieve.q2 import ancestry, embed_graph
from data.generator import generate
from data.load_fixture import load
from mcp_server import tools_memory

pytestmark = pytest.mark.b5
FIX = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "ap_tiny.json"
WINDOW = ("2026-10-02T00:00:00Z", "2026-10-09T23:59:59Z")


@pytest.fixture()
def g():
    return load(json.loads(FIX.read_text(encoding="utf8")), graph_name="test_b5")


def test_acceptance_payment_is_1_and_address_is_2(g):
    pay = fragility(g, "act_pay_2")
    assert pay["independent_sources"] == 1 and pay["bound"] == "exact"
    addr = fragility(g, "b_addr")
    assert addr["independent_sources"] == 2 and addr["bound"] == "exact"
    assert addr["cut_set"] == ["coastal-portal", "contract-pdf"]


def test_flow_is_an_upper_bound_that_treats_and_as_or(g):
    # single-premise chain: engine max-flow is exact
    assert fragility(g, "b_bank_new")["flow_upper_bound"] == 1 == fragility(g, "b_bank_new")["independent_sources"]
    assert fragility(g, "b_addr")["flow_upper_bound"] == 2
    # AND of three independent premises: flow says 3, one failure is enough
    pay = fragility(g, "act_pay_2")
    assert pay["flow_upper_bound"] == 3 and pay["independent_sources"] == 1


def test_circular_support_does_not_add_independence(g):
    f = fragility(g, "b_circ_a")
    assert f["independent_sources"] == 1 and f["cut_set"] == ["coastal-portal"]


def test_observation_and_unknown_node(g):
    assert fragility(g, "obs_pdf_addr")["independent_sources"] == 1
    with pytest.raises(RetconError) as e:
        fragility(g, "nope")
    assert e.value.code == "NOT_FOUND"


def test_out_node_has_nothing_left_to_poison_and_live_support_shrinks(g):
    distrust(g, "coastal-portal", *WINDOW)
    assert fragility(g, "act_pay_2")["independent_sources"] == 0
    addr = fragility(g, "b_addr")  # survives on the contract PDF alone
    assert addr["independent_sources"] == 1 and addr["cut_set"] == ["contract-pdf"]
    assert addr["live_sources"] == ["contract-pdf"]


def test_gate_policy_hook_matches_blocked_by_policy_details(g):
    r = meets_independence(g, "act_pay_2", required=2)
    assert r["ok"] is False
    assert {k: r[k] for k in ("independent_sources", "required")} == {"independent_sources": 1, "required": 2}
    assert meets_independence(g, "b_addr", required=2)["ok"] is True


def test_every_cut_is_valid_minimal_and_below_flow():
    spec = generate(seed=5, vendors=3, audit_incident=True)
    g = load(spec, graph_name="test_b5_gen")
    ids = [r[0] for r in g.query("MATCH (m:Mem) RETURN m.id").result_set]
    assert len(ids) > 70
    for nid in ids:
        f = fragility(g, nid)
        _, base, justs = ancestry(g, nid)
        cut = set(f["cut_set"])
        assert f["bound"] == "exact"
        assert not q7._survives(nid, base, justs, cut), f"{nid}: cut does not kill the node"
        for s in cut:  # minimal: dropping any source from the cut leaves the node alive
            assert q7._survives(nid, base, justs, cut - {s}), f"{nid}: {s} is not needed"
        assert f["independent_sources"] <= f["flow_upper_bound"], nid
        dp = q7._dp_cut(nid, base, justs)
        assert dp is not None and not q7._survives(nid, base, justs, set(dp))
        assert f["independent_sources"] <= len(dp)


def test_fallback_decomposition_is_a_valid_upper_bound(g, monkeypatch):
    monkeypatch.setattr(q7, "EXACT_MAX_SOURCES", 0)
    for nid in ("act_pay_2", "b_addr", "b_circ_b", "plan_pay_1"):
        f = fragility(g, nid)
        assert f["bound"] == "upper"
        _, base, justs = ancestry(g, nid)
        assert not q7._survives(nid, base, justs, set(f["cut_set"]))
    assert fragility(g, "act_pay_2")["independent_sources"] == 1
    assert fragility(g, "b_addr")["independent_sources"] == 2


def test_writes_maintain_flow_so_new_beliefs_are_scored():
    emb = get_embedder("hash")
    g = load(json.loads(FIX.read_text(encoding="utf8")), graph_name="test_b5_write")
    embed_graph(g, emb)
    m = MemoryService(g, emb)
    a = m.observe("erp", "Delivery note DN-77 received for Coastal Produce pallets.", 1760000000)
    b = m.observe("po-system", "Purchase order PO-91 covers Coastal Produce pallets delivery.", 1760000100)
    m.begin_turn("analyst")
    m.capture.record("analyst", [a["node_id"], b["node_id"]])
    both = m.remember("Pallet delivery is covered by a purchase order.", "belief", "analyst")
    f = fragility(g, both["node_id"])
    assert f["independent_sources"] == 1 and f["flow_upper_bound"] == 2  # AND of two sources
    # the same claim re-asserted from a different single source is an OR: now two sources must fall
    c = m.observe("contract-pdf", "Contract clause 4 covers Coastal Produce pallet deliveries.", 1760000200)
    m.begin_turn("analyst")
    m.capture.record("analyst", [c["node_id"]])
    again = m.remember("Pallet delivery is covered by a purchase order.", "belief", "analyst")
    assert again["node_id"] == both["node_id"]
    f = fragility(g, both["node_id"])
    assert f["independent_sources"] == 2 and f["bound"] == "exact"
    # MCP wrapper keeps the contract keys
    tools_memory.configure(m)
    out = tools_memory.fragility(both["node_id"])
    assert out["independent_sources"] == 2 and out["bound"] == "exact"
    assert tools_memory.fragility("nope")["error"]["code"] == "NOT_FOUND"
