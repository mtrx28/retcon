"""Bench interface (bench/api.py): metric semantics are pinned here so A's baselines and B's harness
cannot drift apart. Pure Python, no database."""
import json
from pathlib import Path

import pytest

from bench.api import STRATEGY_NAMES, RetractionResult, Strategy, Window, metrics, record

pytestmark = pytest.mark.bench

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "data" / "fixtures" / "ap_tiny.json").read_text(encoding="utf8"))
GT = SPEC["ground_truth"]


def test_perfect_strategy_scores_perfectly():
    m = metrics(GT, set(GT["contaminated"]), SPEC["actions"])
    assert m["residual_contamination"] == 0 and m["collateral_loss"] == 0
    assert m["action_recall"] == 1 and m["action_precision"] == 1 and m["blocked_recall"] == 1


def test_doing_nothing_leaves_everything():
    m = metrics(GT, set(), SPEC["actions"])
    assert m["residual_contamination"] == 1 and m["collateral_loss"] == 0
    assert m["action_recall"] == 0 and m["blocked_recall"] == 0
    assert m["action_precision"] is None            # nothing flagged: precision undefined


def test_wipe_everything_has_full_recall_and_full_collateral():
    everything = set(GT["contaminated"]) | set(GT["truly_supported"])
    m = metrics(GT, everything, SPEC["actions"])
    assert m["residual_contamination"] == 0 and m["collateral_loss"] == 1
    assert m["action_recall"] == 1


def test_delete_source_only_removes_observations():
    obs = {i for i in GT["contaminated"] if i.startswith("obs_")}
    m = metrics(GT, obs, SPEC["actions"])
    n_c = len(GT["contaminated"])
    assert m["residual_contamination"] == pytest.approx((n_c - len(obs)) / n_c)
    assert m["action_recall"] == 0 and m["collateral_loss"] == 0


def test_precision_penalises_flagging_clean_executed_actions():
    spec_actions = SPEC["actions"] + [{"id": "act_clean", "tool": "pay", "executed": True, "amount": 1}]
    gt = {**GT, "truly_supported": GT["truly_supported"] + ["act_clean"]}
    m = metrics(gt, set(GT["contaminated"]) | {"act_clean"}, spec_actions)
    assert m["action_recall"] == 1 and m["action_precision"] == 0.5


def test_ground_truth_without_recall_keys_falls_back_to_actions():
    gt = {"contaminated": GT["contaminated"], "truly_supported": GT["truly_supported"]}
    assert metrics(gt, set(GT["contaminated"]), SPEC["actions"])["action_recall"] == 1


def test_empty_denominators_are_none_not_zero():
    m = metrics({"contaminated": [], "truly_supported": []}, {"x"}, [])
    assert m["residual_contamination"] is None and m["collateral_loss"] is None
    assert m["action_recall"] is None and m["blocked_recall"] is None


def test_window_from_spec_and_record_shape_roundtrips_json():
    w = Window.from_spec(SPEC)
    assert (w.source, w.t_from, w.t_to) == (SPEC["window"]["source"], SPEC["window"]["from"], SPEC["window"]["to"])
    res = RetractionResult({"a", "b"}, engine_ms=0.5, notes={"threshold": 0.75})
    rec = record({"name": "ap_tiny", "domain": "ap", "nodes": 24, "seed": None}, "retcon", res,
                 metrics(GT, res.out_ids, SPEC["actions"]), elapsed_ms=12.0)
    assert json.loads(json.dumps(rec))["strategy"] == "retcon" and rec["out_count"] == 2
    err = record({"name": "ap_tiny"}, "coarse_taint", None, None, error="boom")
    assert err["error"] == "boom" and err["metrics"] is None


def test_protocol_accepts_a_minimal_strategy_and_names_are_fixed():
    class Nothing:
        name = "delete_source"

        def retract(self, graph, window):
            return RetractionResult(set())
    assert isinstance(Nothing(), Strategy)
    assert STRATEGY_NAMES == ("delete_source", "vector_only", "edge_invalidation", "coarse_taint", "retcon")
