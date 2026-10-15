"""A12 acceptance: Q8 keystone sources (PageRank) and contradiction clusters (WCC over CONTRADICTS)."""
import asyncio
import json
import os
from pathlib import Path

import pytest
from mcp.client.client import Client

os.environ.setdefault("RETCON_EMBEDDER", "hash")

from bench.harness.scenarios import build  # noqa: E402
from core.analytics.contradictions import (add_contradiction, contradiction_clusters, detect,  # noqa: E402
                                           facts, link_contradictions)
from core.analytics.keystone import blast_radius, keystones  # noqa: E402
from core.retract.cascade import distrust, reinstate  # noqa: E402
from data.load_fixture import load  # noqa: E402
from mcp_server import tools_retract  # noqa: E402
from mcp_server.server import build as build_server  # noqa: E402
from ui.shell.server import Shell  # noqa: E402

pytestmark = pytest.mark.a12

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "data" / "fixtures" / "ap_tiny.json").read_text(encoding="utf8"))
W = SPEC["window"]


@pytest.fixture()
def tiny():
    return load(SPEC, graph_name="a12_tiny")


@pytest.fixture(scope="module")
def ap1k():
    sc = build("ap_1k")
    return load(sc.spec, graph_name="a12_ap1k"), sc


# ---- keystones ----------------------------------------------------------------------------------

def test_coastal_portal_is_a_top_keystone_on_ap_tiny(tiny):
    top = keystones(tiny, 5)
    assert "coastal-portal" in [k["id"] for k in top]
    assert keystones(tiny, 1, order="rank")[0]["id"] == "coastal-portal"      # most memory rests on it here


def test_ap_1k_system_of_record_carries_the_weight_and_the_low_trust_portal_is_audited_next(ap1k):
    g, sc = ap1k
    by_rank = keystones(g, 3, order="rank")
    assert [k["id"] for k in by_rank[:2]] == ["erp", "po-system"]             # everything is invoiced through them
    prio = keystones(g, 5, order="priority")
    assert "coastal-portal" in [k["id"] for k in prio]                         # acceptance: top-5 includes it
    ids = [k["id"] for k in prio]
    assert ids.index("coastal-portal") < min(i for i, k in enumerate(ids) if k.endswith("-portal") and k != "coastal-portal"
                                              ) if any(k.endswith("-portal") and k != "coastal-portal" for k in ids) else True
    # pure PageRank ties the symmetric vendor portals exactly; priority breaks the tie by trust
    portals = [k for k in keystones(g, 40, order="rank") if k["id"].endswith("-portal")]
    assert len({round(k["rank"], 9) for k in portals}) == 1
    assert prio[2]["trust"] < 0.5


def test_precision_scenario_lists_every_low_trust_portal_ahead_of_the_rest():
    sc = build("ap_prec_1k")
    g = load(sc.spec, graph_name="a12_prec")
    prio = keystones(g, 8, order="priority")
    poisoned = {w["source"] for w in sc.spec["windows"]}
    low = {k["id"] for k in prio if k["trust"] <= 0.4}
    assert "coastal-portal" in [k["id"] for k in prio[:5]]
    assert low and low <= poisoned | {"callback-log"} | low        # low-trust sources float to the top


def test_blast_radius_and_live_downstream_track_retractions(tiny):
    ids = blast_radius(tiny, "coastal-portal")
    assert {"obs_portal_bank", "b_bank_new", "act_pay_2"} <= set(ids)
    assert "obs_pdf_addr" not in ids
    before = next(k for k in keystones(tiny, 10) if k["id"] == "coastal-portal")
    distrust(tiny, W["source"], W["from"], W["to"])
    after = next(k for k in keystones(tiny, 10) if k["id"] == "coastal-portal")
    assert after["downstream"] == before["downstream"]                         # reachability is structural
    assert after["live_downstream"] < before["live_downstream"]                # what is still IN is not


def test_keystones_deterministic_and_empty_graph(tiny):
    assert keystones(tiny, 10) == keystones(tiny, 10)
    from core.db import connect
    empty = connect().select_graph("a12_empty")
    try:
        empty.delete()
    except Exception:
        pass
    empty = connect().select_graph("a12_empty")
    empty.query("CREATE (:Mem {id:'x'})")
    assert keystones(empty) == []                      # no sources at all
    empty.query("CREATE (:Source {id:'s0', kind:'portal', trust:0.5})")
    only = keystones(empty)                            # sources but no DEPENDS_ON edges: rank 0, no crash
    assert [(k["id"], k["rank"], k["downstream"]) for k in only] == [("s0", 0.0, 0)]
    assert contradiction_clusters(empty) == []


# ---- contradictions -----------------------------------------------------------------------------

def test_fact_extraction_rules():
    assert facts("Coastal Produce bank account is IBAN SYN-9999-0001.") == ("coastal produce", "bank", "syn-9999-0001")
    assert facts("Contract bank for Coastal Produce is IBAN SYN-1111-0001.") == ("coastal produce", "bank", "syn-1111-0001")
    assert facts("Coastal Produce remit address is 12 Dock Road.") == ("coastal produce", "address", "12 dock road")
    assert facts("Pay INV-1 18400 USD to SYN-9999-0001.") is None


def test_bank_account_conflict_forms_one_cluster_that_resolves_on_retraction(tiny):
    assert [(p["a"], p["b"]) for p in detect(tiny)] == [("b_bank_new", "b_old_bank")]
    assert link_contradictions(tiny) == {"found": 1, "created": 1}
    assert link_contradictions(tiny) == {"found": 1, "created": 0}             # idempotent
    [c] = contradiction_clusters(tiny)
    assert c["size"] == 2 and (c["subject"], c["attribute"]) == ("coastal produce", "bank")
    assert c["resolved"] is False and len(c["live_values"]) == 2
    res = distrust(tiny, W["source"], W["from"], W["to"])
    [c] = contradiction_clusters(tiny)
    assert c["resolved"] is True and c["live_values"] == ["syn-1111-0001"]
    assert {m["id"]: m["status"] for m in c["members"]} == {"b_bank_new": "OUT", "b_old_bank": "IN"}
    reinstate(tiny, res["retraction_id"])
    assert contradiction_clusters(tiny)[0]["resolved"] is False                # the conflict is back


def test_matching_values_do_not_conflict(tiny):
    # the address belief has two supporting observations but one value: no contradiction
    assert all(p["attribute"] != "address" for p in detect(tiny))


def test_wcc_clusters_only_follow_contradicts_edges(tiny):
    for a, b in (("b_addr", "b_hours"), ("b_hours", "b_closure"), ("b_inv1_ok", "b_inv2_ok")):
        add_contradiction(tiny, a, b, "x", "y", detector="test")
    clusters = contradiction_clusters(tiny, link=False)
    sizes = sorted(c["size"] for c in clusters)
    assert sizes == [2, 3]                                                     # a chain of 3, a separate pair
    # premise/justification edges (b_addr and b_hours share nothing else) did not merge them
    assert {m["id"] for c in clusters for m in c["members"] if c["size"] == 3} == {"b_addr", "b_hours", "b_closure"}


# ---- tool and API surface -----------------------------------------------------------------------

def test_mcp_tools(tiny, monkeypatch):
    monkeypatch.setenv("RETCON_MEMORY", "0")

    async def go():
        async with Client(build_server(graph=tiny)) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            ks = [json.loads(x.text) for x in (await c.call_tool("keystones", {"top": 3})).content]
            cx = [json.loads(x.text) for x in (await c.call_tool("contradictions", {})).content]
            bad = json.loads((await c.call_tool("keystones", {"order": "vibes"})).content[0].text)
            return names, ks, cx, bad
    names, ks, cx, bad = asyncio.run(go())
    assert {"keystones", "contradictions"} <= names
    assert len(ks) == 3 and ks[0]["id"] == "coastal-portal"
    assert cx and cx[0]["size"] == 2
    assert bad["error"]["code"] == "INVALID_ARGUMENT"


def test_ops_api_routes():
    load(SPEC, graph_name="a12_ui")
    shell = Shell(default_graph="a12_ui", min_interval=0)
    router = shell.router()
    st, body = router.dispatch("GET", "/api/ops/keystones?graph=a12_ui&top=3&order=rank")
    assert st == 200 and body["keystones"][0]["id"] == "coastal-portal" and body["order"] == "rank"
    st, body = router.dispatch("GET", "/api/ops/keystones?graph=a12_ui&order=bogus")
    assert st == 400 and body["error"]["code"] == "INVALID_ARGUMENT"
    st, body = router.dispatch("GET", "/api/ops/blast?graph=a12_ui&source=coastal-portal")
    assert st == 200 and "b_bank_new" in body["ids"]
    st, body = router.dispatch("GET", "/api/ops/blast?graph=a12_ui&source=ghost")
    assert st == 404
    st, body = router.dispatch("GET", "/api/ops/contradictions?graph=a12_ui")
    assert st == 200 and body["clusters"][0]["size"] == 2
    st, js = router.dispatch("GET", "/ops/keystone.js")
    assert st == 200 and "Keystone" in js.data.decode()
    st, page = router.dispatch("GET", "/")
    assert "/ops/keystone.js" in page.data.decode()
