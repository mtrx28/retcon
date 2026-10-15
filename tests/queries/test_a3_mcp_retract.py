"""A3 acceptance: an MCP client calls distrust / why / reinstate / recall_list on ap_tiny.

Two layers: in-process Client (fast, all behaviour) and one real stdio subprocess (the transport a
stock MCP client such as Claude Code would use).
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters

from data.load_fixture import connect, load
from mcp_server.server import build

pytestmark = pytest.mark.a3

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "data" / "fixtures" / "ap_tiny.json").read_text(encoding="utf8"))
W = SPEC["window"]
GT = SPEC["ground_truth"]


def run(coro):
    return asyncio.run(coro)


def payload(result, as_list=False):
    """MCP splits a list return into one TextContent per element (empty list -> no content)."""
    items = [json.loads(c.text) for c in result.content]
    if as_list and not (items and isinstance(items[0], dict) and "error" in items[0]):
        return items
    return items[0]


@pytest.fixture()
def graph(monkeypatch):
    monkeypatch.setenv("RETCON_MEMORY", "0")
    return load(SPEC, graph_name="a3_mcp")


def call(graph, name, args):
    async def go():
        async with Client(build(graph=graph)) as c:
            return payload(await c.call_tool(name, args), as_list=(name == "recall_list"))
    return run(go())


def statuses(g):
    return {r[0]: r[1] for r in g.query("MATCH (m:Mem) RETURN m.id, m.status").result_set}


def test_tools_are_listed(graph):
    async def go():
        async with Client(build(graph=graph)) as c:
            return {t.name for t in (await c.list_tools()).tools}
    assert {"distrust", "reinstate", "why", "recall_list"} <= run(go())


def test_distrust_response_lists_flipped_nodes(graph):
    res = call(graph, "distrust", {"source": W["source"], "from_": W["from"], "to": W["to"]})
    assert set(res["flipped_ids"]) == set(GT["contaminated"])
    assert res["blocked_action_ids"] == GT["blocked"]
    assert [a["action_id"] for a in res["recall_list"]] == GT["recall_list"]
    assert res["retraction_id"].startswith("ret_")
    assert {k for k, v in statuses(graph).items() if v == "OUT"} == set(GT["contaminated"])


def test_why_returns_justification_tree(graph):
    tree = call(graph, "why", {"node_id": "b_addr"})
    assert tree["id"] == "b_addr" and tree["status"] == "IN" and tree["mtype"] == "semantic"
    # OR of two single-premise justifications: portal copy and the signed contract PDF
    prem = {p["id"]: p for j in tree["justifications"] for p in j["premises"]}
    assert set(prem) == {"obs_portal_addr", "obs_pdf_addr"}
    assert prem["obs_pdf_addr"]["source"]["id"] == "contract-pdf"
    assert prem["obs_pdf_addr"]["mtype"] == "episodic"


def test_why_shows_retraction_and_handles_cycles(graph):
    call(graph, "distrust", {"source": W["source"], "from_": W["from"], "to": W["to"]})
    plan = call(graph, "why", {"node_id": "plan_pay_1"})
    assert plan["status"] == "OUT" and plan["retracted_by"] == ["ret_0001"]
    circ = json.dumps(call(graph, "why", {"node_id": "b_circ_a"}))
    assert '"cycle": true' in circ  # b_circ_a <- b_circ_b <- b_circ_a


def test_why_depth_limit_marks_truncation(graph):
    tree = call(graph, "why", {"node_id": "act_pay_1", "max_depth": 1})
    assert "truncated" in json.dumps(tree)


def test_reinstate_restores_exact_prior_state(graph):
    before = statuses(graph)
    res = call(graph, "distrust", {"source": W["source"], "from_": W["from"], "to": W["to"]})
    out = call(graph, "reinstate", {"retraction_id": res["retraction_id"]})
    assert out["restored_count"] == len(GT["contaminated"])
    assert statuses(graph) == before


def test_recall_list_tool(graph):
    assert call(graph, "recall_list", {}) == []
    res = call(graph, "distrust", {"source": W["source"], "from_": W["from"], "to": W["to"]})
    rows = call(graph, "recall_list", {"run": res["retraction_id"]})
    assert [r["action_id"] for r in rows] == ["act_pay_1"] and rows[0]["amount"] == 18400
    assert call(graph, "recall_list", {}) == rows
    call(graph, "reinstate", {"retraction_id": res["retraction_id"]})
    assert call(graph, "recall_list", {}) == []


@pytest.mark.parametrize("name,args,code", [
    ("distrust", {"source": "nope", "from_": "2026-10-01T00:00:00Z", "to": "2026-10-02T00:00:00Z"}, "NOT_FOUND"),
    ("distrust", {"source": "coastal-portal", "from_": "2026-10-09T00:00:00Z", "to": "2026-10-01T00:00:00Z"},
     "INVALID_ARGUMENT"),
    ("distrust", {"source": "coastal-portal", "from_": "2026-10-01T00:00:00Z", "to": "2026-10-09T00:00:00Z",
                  "mode": "dryrun"}, "INVALID_ARGUMENT"),
    ("reinstate", {"retraction_id": "ret_9999"}, "NOT_FOUND"),
    ("why", {"node_id": "ghost"}, "NOT_FOUND"),
    ("recall_list", {"run": "ret_9999"}, "NOT_FOUND"),
])
def test_errors_use_the_contract_shape(graph, name, args, code):
    res = call(graph, name, args)
    assert set(res) == {"error"} and res["error"]["code"] == code
    assert {"message", "details"} <= set(res["error"])


def test_real_stdio_server():
    """What Claude Code does: spawn `python -m mcp_server.server` and talk JSON-RPC over stdio."""
    load(SPEC, graph_name="tenant_a3stdio")
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "mcp_server.server"], cwd=str(ROOT),
        env={**os.environ, "RETCON_TENANT": "a3stdio", "RETCON_MEMORY": "0"})

    async def go():
        async with Client(params) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            res = payload(await c.call_tool(
                "distrust", {"source": W["source"], "from_": W["from"], "to": W["to"]}))
            return names, res
    names, res = run(go())
    assert {"distrust", "reinstate", "why", "recall_list"} <= names
    assert set(res["flipped_ids"]) == set(GT["contaminated"])
    connect().select_graph("tenant_a3stdio").delete()
