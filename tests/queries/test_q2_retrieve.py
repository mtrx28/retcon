"""B2: Q2 vector retrieval, IN-only, support summary. Acceptance: python tasks.py accept B2"""
import json
from pathlib import Path

import pytest

from core.memory import MemoryService
from core.retrieve.embed import get_embedder
from core.retrieve.q2 import embed_graph, support
from data.load_fixture import load

pytestmark = pytest.mark.b2
FIX = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "ap_tiny.json"
BANK_Q = "Coastal Produce bank account IBAN SYN-9999-0001"
BANK_IDS = ["obs_portal_bank", "b_bank_new", "b_bank_echo_analyst", "b_bank_echo_comms"]


@pytest.fixture()
def mem():
    emb = get_embedder("hash")
    g = load(json.loads(FIX.read_text(encoding="utf8")), graph_name="test_b2")
    embed_graph(g, emb)
    return MemoryService(g, emb)


def test_nearest_first_and_contract_shape(mem):
    hits = mem.recall(BANK_Q, "payments", k=5)
    assert hits and set(hits[0]) == {"id", "text", "score", "sources", "weakest_trust"}
    assert [h["score"] for h in hits] == sorted(h["score"] for h in hits)
    assert hits[0]["id"] in BANK_IDS


def test_only_in_nodes_returned_even_when_out_nodes_are_nearest(mem):
    mem.g.query("MATCH (m:Mem) WHERE m.id IN $ids SET m.status='OUT'", {"ids": BANK_IDS})
    hits = mem.recall(BANK_Q, "payments", k=3)
    assert len(hits) == 3
    assert not {h["id"] for h in hits} & set(BANK_IDS)


def test_k_is_respected_through_overfetch(mem):
    # 20 OUT nodes nearer than anything IN: the first top-n must widen to still return 3 IN hits.
    v = mem.embedder.embed(["zebra quartz"])[0]
    for i in range(20):
        mem.g.query("CREATE (:Mem {id:$i, text:'zebra quartz', status:'OUT', embedding:vecf32($v)})",
                    {"i": f"junk_{i}", "v": v})
    assert len(mem.recall("zebra quartz", "a", k=3)) == 3


def test_support_summary_independent_sources(mem):
    assert support(mem.g, "b_addr") == {"coastal-portal": 0.4, "contract-pdf": 0.9}
    assert support(mem.g, "b_bank_new") == {"coastal-portal": 0.4}
    hit = next(h for h in mem.recall("remit address 12 Dock Road", "a", k=10) if h["id"] == "b_addr")
    assert hit["sources"] == ["coastal-portal", "contract-pdf"] and hit["weakest_trust"] == 0.4


def test_laundered_belief_traces_to_poisoned_source(mem):
    assert support(mem.g, "plan_pay_1") == {"coastal-portal": 0.4, "erp": 0.95, "po-system": 0.9}


def test_circular_support_does_not_ground_itself(mem):
    assert support(mem.g, "b_circ_b") == {"coastal-portal": 0.4}
    mem.g.query("MATCH (m:Mem {id:'obs_portal_bank'}) SET m.status='OUT'")
    assert support(mem.g, "b_circ_b") == {}


def test_dead_justification_does_not_count(mem):
    mem.g.query("MATCH (m:Mem {id:'obs_portal_addr'}) SET m.status='OUT'")
    assert support(mem.g, "b_addr") == {"contract-pdf": 0.9}


def test_recall_records_context_for_the_agent(mem):
    hits = mem.recall("opening hours", "intake", k=2)
    assert mem.capture.context("intake") == [h["id"] for h in hits]
    assert mem.capture.context("payments") == []
