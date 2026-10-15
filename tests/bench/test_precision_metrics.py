"""Wrongly flagged actions, per-layer breakdown and windows(): pure Python, no database."""
import json
from pathlib import Path

import pytest

from bench.api import layers, metrics, metrics_by_layer, windows

pytestmark = pytest.mark.bench

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "data" / "fixtures" / "ap_tiny.json").read_text(encoding="utf8"))
GT = SPEC["ground_truth"]

ACTIONS = [
    {"id": "bad_paid", "tool": "pay", "executed": True, "amount": 18400},
    {"id": "bad_pending", "tool": "pay", "executed": False, "amount": 41250},
    {"id": "ok_paid", "tool": "pay", "executed": True, "amount": 12000},
    {"id": "ok_paid2", "tool": "pay", "executed": True, "amount": 800},
    {"id": "ok_pending", "tool": "pay", "executed": False, "amount": 5000},
]
TRUTH = {"contaminated": ["bad_paid", "bad_pending"],
         "truly_supported": ["ok_paid", "ok_paid2", "ok_pending"]}


def test_wrongly_flagged_counts_executed_pending_and_dollars():
    m = metrics(TRUTH, {"bad_paid", "bad_pending", "ok_paid", "ok_pending"}, ACTIONS)
    w = m["wrongly_flagged_actions"]
    assert (w["count"], w["executed"], w["pending"]) == (2, 1, 1)
    assert w["amount"] == 17000 and w["executed_amount"] == 12000
    assert w["legit_total"] == 3 and w["rate"] == pytest.approx(2 / 3)
    assert w["ids"] == ["ok_paid", "ok_pending"]


def test_a_precise_strategy_wrongly_flags_nothing():
    w = metrics(TRUTH, {"bad_paid", "bad_pending"}, ACTIONS)["wrongly_flagged_actions"]
    assert w["count"] == 0 and w["amount"] == 0 and w["rate"] == 0


def test_no_legitimate_actions_means_rate_is_none_not_zero():
    w = metrics(GT, set(GT["contaminated"]), SPEC["actions"])["wrongly_flagged_actions"]
    assert w["legit_total"] == 0 and w["rate"] is None


def test_wipe_everything_flags_every_legitimate_action():
    everything = set(TRUTH["contaminated"]) | set(TRUTH["truly_supported"])
    w = metrics(TRUTH, everything, ACTIONS)["wrongly_flagged_actions"]
    assert w["count"] == 3 and w["amount"] == 17800 and w["rate"] == 1


def test_layers_split_science_beliefs_into_claims_and_topics():
    sci = {"domain": "science", "observations": [{"id": "obs_1"}], "actions": [],
           "derivations": [{"conclusion": {"id": "claim_1", "kind": "belief"}},
                           {"conclusion": {"id": "topic_ab", "kind": "belief"}},
                           {"conclusion": {"id": "plan_1", "kind": "plan"}}]}
    assert layers(sci) == {"obs_1": "observation", "claim_1": "claim", "topic_ab": "topic", "plan_1": "plan"}
    ap = {"observations": [{"id": "o"}], "actions": [{"id": "a"}],
          "derivations": [{"conclusion": {"id": "b", "kind": "belief"}}, {"conclusion": {"id": "p", "kind": "plan"}}]}
    assert layers(ap) == {"o": "observation", "b": "belief", "p": "plan", "a": "action"}


def test_by_layer_localises_the_collateral():
    layer_of = {"c1": "claim", "c2": "claim", "t1": "topic", "t2": "topic", "t3": "topic"}
    gt = {"contaminated": ["c1", "t1"], "truly_supported": ["c2", "t2", "t3"]}
    out = {"c1", "t1", "t2"}                       # wiped a supported topic, left nothing contaminated
    by = metrics_by_layer(gt, out, layer_of)
    assert by["claim"]["collateral_loss"] == 0 and by["claim"]["residual_contamination"] == 0
    assert by["topic"]["collateral_loss"] == pytest.approx(1 / 2) and by["topic"]["collateral_nodes"] == 1
    assert by["topic"]["truly_supported"] == 2 and by["topic"]["contaminated"] == 1


def test_by_layer_none_when_a_layer_has_no_nodes_of_that_class():
    by = metrics_by_layer({"contaminated": ["a"], "truly_supported": []}, {"a"}, {"a": "action"})
    assert by["action"]["collateral_loss"] is None and by["action"]["residual_contamination"] == 0


def test_windows_handles_all_three_scenario_shapes():
    sci = {"retractions": [{"source": "P1", "from": "a", "to": "b"}, {"source": "P2", "from": "c", "to": "d"}]}
    assert [w.source for w in windows(sci)] == ["P1", "P2"]
    prec = {"windows": [{"source": "v1-portal", "from": "a", "to": "b"}, {"source": "v2-portal", "from": "c", "to": "d"}]}
    assert [w.source for w in windows(prec)] == ["v1-portal", "v2-portal"]
    assert [w.source for w in windows(SPEC)] == [SPEC["window"]["source"]]
