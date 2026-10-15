"""A5 acceptance: the preview returns the flip set a commit would, the live graph is untouched,
and the GRAPH.COPY fork is deleted."""
import copy
import json
import os
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from core.db import connect
from core.preview.preview import preview
from core.retract.cascade import distrust
from data.load_fixture import load
from mcp_server import tools_retract

pytestmark = pytest.mark.a5

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "data" / "fixtures" / "ap_tiny.json").read_text(encoding="utf8"))
W = SPEC["window"]


def extra_actions_spec():
    s = copy.deepcopy(SPEC)
    s["actions"].append({"id": "act_pay_3", "tool": "pay", "agent": "payments", "amount": 5000,
                         "executed": True, "executed_at": "2026-10-08T09:00:00Z", "premises": ["plan_pay_1"]})
    return s


def live_state(g):
    nodes = g.query("MATCH (m:Mem) RETURN m.id, m.status, m.run, m.hop ORDER BY m.id").result_set
    counts = g.query("MATCH (n) RETURN labels(n)[0] AS l, count(n) ORDER BY l").result_set
    edges = g.query("MATCH ()-[r]->() RETURN type(r), count(r) ORDER BY type(r)").result_set
    return nodes, counts, edges


def test_preview_flip_set_equals_commit_and_leaves_live_graph_untouched():
    g_prev = load(extra_actions_spec(), graph_name="a5_prev")
    g_commit = load(extra_actions_spec(), graph_name="a5_commit")
    before = live_state(g_prev)

    p = preview(g_prev, W["source"], W["from"], W["to"])
    c = distrust(g_commit, W["source"], W["from"], W["to"])

    assert live_state(g_prev) == before                       # not a node, edge or tag changed
    assert p["preview"] is True and p["mode"] == "preview"
    assert p["retraction_id"] == c["retraction_id"]           # the id a commit would get
    assert set(p["flipped_ids"]) == set(c["flipped_ids"])
    assert p["flipped"] == c["flipped"]
    assert p["blocked_action_ids"] == c["blocked_action_ids"]
    assert p["recall_list"] == c["recall_list"]
    assert p["survived_ids"] == c["survived_ids"] and "b_addr" in p["survived_ids"]
    assert {d["id"] for d in p["diff"]} == set(c["flipped_ids"])
    assert all(d["from"] == "IN" and d["to"] == "OUT" for d in p["diff"])
    assert {d["kind"] for d in p["diff"]} == {"observation", "belief", "plan", "action"}
    assert g_prev.query("MATCH (r:Retraction) RETURN count(r)").result_set[0][0] == 0
    assert g_prev.query("MATCH (r:Remediation) RETURN count(r)").result_set[0][0] == 0
    from agents import remediator
    drafted = remediator.remediate(g_commit, c["retraction_id"])   # what the commit path drafts
    assert [d["id"] for d in p["remediations"]] == [d["id"] for d in drafted]
    assert [d["status"] for d in p["remediations"]] == ["draft"] * len(drafted)


def test_fork_is_deleted():
    g = load(SPEC, graph_name="a5_fork")
    preview(g, W["source"], W["from"], W["to"])
    assert [n for n in connect().list_graphs() if n.startswith("a5_fork_preview")] == []


def test_fork_is_deleted_even_when_the_cascade_fails(monkeypatch):
    g = load(SPEC, graph_name="a5_fail")

    def boom(*a, **k):
        raise RuntimeError("cascade exploded")
    monkeypatch.setattr("core.preview.preview.cascade.distrust", boom)
    with pytest.raises(RuntimeError):
        preview(g, W["source"], W["from"], W["to"])
    assert [n for n in connect().list_graphs() if n.startswith("a5_fail_preview")] == []


def test_preview_then_commit_gives_the_previewed_result():
    g = load(SPEC, graph_name="a5_flow")
    p = preview(g, W["source"], W["from"], W["to"])
    preview(g, W["source"], W["from"], W["to"])               # previewing twice changes nothing
    c = distrust(g, W["source"], W["from"], W["to"])
    assert c["retraction_id"] == p["retraction_id"] == "ret_0001"
    assert set(c["flipped_ids"]) == set(p["flipped_ids"])


def test_preview_sees_previous_retractions():
    """Preview of a second distrust accounts for the first one already applied."""
    g = load(SPEC, graph_name="a5_second")
    distrust(g, W["source"], W["from"], W["to"])
    p = preview(g, "contract-pdf", "2026-10-01T00:00:00Z", "2026-10-04T00:00:00Z")
    assert p["retraction_id"] == "ret_0002"
    assert "b_addr" in p["flipped_ids"]                       # its last supporter is now the PDF
    assert g.query("MATCH (m:Mem {id:'b_addr'}) RETURN m.status").result_set[0][0] == "IN"


def test_profile_is_reported():
    g = load(SPEC, graph_name="a5_prof")
    res = preview(g, W["source"], W["from"], W["to"])
    assert res["profile"]["execution_ms"] is not None and res["profile"]["execution_ms"] >= 0
    assert res["profile"]["plan"]


def test_errors_keep_the_contract_shape_and_leave_no_fork():
    g = load(SPEC, graph_name="a5_err")
    tools_retract.configure(g)
    assert tools_retract.distrust("ghost", W["from"], W["to"], mode="preview")["error"]["code"] == "NOT_FOUND"
    assert tools_retract.distrust(W["source"], W["to"], W["from"], mode="preview")["error"]["code"] == "INVALID_ARGUMENT"
    assert [n for n in connect().list_graphs() if n.startswith("a5_err_preview")] == []


def test_mcp_tool_preview_mode():
    g = load(SPEC, graph_name="a5_mcp")
    tools_retract.configure(g)
    before = live_state(g)
    res = tools_retract.distrust(W["source"], W["from"], W["to"], mode="preview")
    assert res["preview"] is True and set(res["flipped_ids"]) == set(SPEC["ground_truth"]["contaminated"])
    assert live_state(g) == before


@settings(max_examples=int(os.getenv("RETCON_PREVIEW_N", "25")), deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(data=st.data())
def test_preview_matches_commit_on_random_graphs(data):
    import sys
    sys.path.insert(0, str(ROOT / "tests" / "differential"))
    from graphgen import SOURCES, iso, specs
    spec = data.draw(specs())
    src = data.draw(st.sampled_from(SOURCES))
    a = data.draw(st.integers(0, 9))
    b = data.draw(st.integers(a, 9))
    g1 = load(spec, graph_name="a5_prop_p")
    g2 = load(spec, graph_name="a5_prop_c")
    before = live_state(g1)
    p = preview(g1, src, iso(a), iso(b))
    c = distrust(g2, src, iso(a), iso(b))
    assert live_state(g1) == before
    assert set(p["flipped_ids"]) == set(c["flipped_ids"])
    assert p["survived_ids"] == c["survived_ids"]
    assert p["blocked_action_ids"] == c["blocked_action_ids"]
