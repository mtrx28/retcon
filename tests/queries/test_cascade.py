"""A1 acceptance: Q3-Q5 cascade on the ap_tiny fixture, Retraction audit node, reinstate."""
import json
from pathlib import Path

import pytest

from core.retract.cascade import distrust, reinstate
from data.load_fixture import load

pytestmark = pytest.mark.a1

FIX = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "ap_tiny.json"
SPEC = json.loads(FIX.read_text(encoding="utf8"))
W = SPEC["window"]


@pytest.fixture()
def g():
    return load(SPEC, graph_name="test_cascade")


def statuses(g):
    return {r[0]: r[1] for r in g.query("MATCH (m:Mem) RETURN m.id, m.status").result_set}


def out_ids(g):
    return {k for k, v in statuses(g).items() if v == "OUT"}


def run_distrust(g):
    return distrust(g, W["source"], W["from"], W["to"])


def test_cascade_matches_ground_truth_exactly(g):
    res = run_distrust(g)
    gt = SPEC["ground_truth"]
    assert out_ids(g) == set(gt["contaminated"])  # nothing missed
    assert {k for k, v in statuses(g).items() if v == "IN"} == set(gt["truly_supported"])  # no collateral
    assert set(res["flipped_ids"]) == set(gt["contaminated"])


def test_independent_support_survives(g):
    run_distrust(g)
    assert statuses(g)["b_addr"] == "IN"  # portal copy retracted, contract PDF still supports it


def test_circular_support_does_not_survive(g):
    run_distrust(g)
    s = statuses(g)
    assert s["b_circ_a"] == "OUT" and s["b_circ_b"] == "OUT"


def test_time_window_only(g):
    run_distrust(g)
    s = statuses(g)
    assert s["obs_portal_pre"] == "IN" and s["obs_portal_late"] == "IN"
    assert s["b_hours"] == "IN" and s["b_closure"] == "IN"


def test_actions_blocked_and_recalled(g):
    res = run_distrust(g)
    assert res["blocked_action_ids"] == SPEC["ground_truth"]["blocked"]
    assert [a["action_id"] for a in res["recall_list"]] == SPEC["ground_truth"]["recall_list"]
    assert res["recall_list"][0]["amount"] == 18400
    assert res["recall_list"][0]["agent"] == "payments"


def test_counts_hops_and_latency(g):
    res = run_distrust(g)
    assert res["flipped"] == {"observations": 2, "beliefs": 5, "plans": 2, "actions": 2}
    assert set(res["hops"][0]) == {"obs_portal_bank", "obs_portal_addr"}
    assert "act_pay_1" in res["hops"][max(res["hops"])] or "act_pay_2" in res["hops"][max(res["hops"])]
    assert res["latency_ms"] >= 0


def test_audit_trail_and_clean_tags(g):
    res = run_distrust(g)
    r = g.query("MATCH (r:Retraction {id:$id}) RETURN r.source, r.mode, r.reinstated",
                {"id": res["retraction_id"]}).result_set[0]
    assert r == [W["source"], "commit", False]
    n = g.query("MATCH (r:Retraction {id:$id})-[:RETRACTED]->(:Mem) RETURN count(*)",
                {"id": res["retraction_id"]}).result_set[0][0]
    assert n == len(SPEC["ground_truth"]["contaminated"])
    assert g.query("MATCH (m:Mem) WHERE m.run IS NOT NULL OR m.hop IS NOT NULL RETURN count(m)").result_set[0][0] == 0


def test_second_distrust_is_a_noop(g):
    run_distrust(g)
    again = run_distrust(g)
    assert again["flipped_ids"] == []
    assert out_ids(g) == set(SPEC["ground_truth"]["contaminated"])


def test_reinstate_restores_exact_prior_state(g):
    before = statuses(g)
    res = run_distrust(g)
    out = reinstate(g, res["retraction_id"])
    assert out["restored_count"] == len(SPEC["ground_truth"]["contaminated"])
    assert statuses(g) == before
    assert g.query("MATCH (m:Mem) WHERE m.run IS NOT NULL RETURN count(m)").result_set[0][0] == 0
    with pytest.raises(ValueError):
        reinstate(g, res["retraction_id"])


def test_unknown_source_and_bad_window(g):
    with pytest.raises(LookupError):
        distrust(g, "no-such-source", W["from"], W["to"])
    with pytest.raises(ValueError):
        distrust(g, W["source"], W["to"], W["from"])
