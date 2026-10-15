"""B7: RetconBench harness: loader equivalence, runner semantics, laundering probe, graph-off ablation.
Acceptance: python tasks.py accept B7

Strategies here are tiny fakes written against `bench.api`, so the harness is tested independently of
Lane A's baselines (which plug in through `bench.harness.runner.discover_strategies`)."""
import json
from pathlib import Path

import pytest

from bench.api import STRATEGY_NAMES, RetractionResult, Window
from bench.harness import ablation, laundering, runner
from bench.harness.fingerprint import fingerprint
from bench.harness.loader import load_batched
from bench.harness.reference import ReferenceRetcon
from bench.harness.scenarios import build, windows_of
from data.load_fixture import load

pytestmark = pytest.mark.b7
ROOT = Path(__file__).resolve().parents[2]
TINY = json.loads((ROOT / "data" / "fixtures" / "ap_tiny.json").read_text(encoding="utf8"))


class ObsOnly:
    """delete-source in miniature: only the window's observations."""
    name = "delete_source"

    def retract(self, graph, window: Window):
        from core.retract.cascade import to_epoch
        rows = graph.query(
            "MATCH (:Source {id:$s})-[:SUPPORTS]->(o:Observation) WHERE o.observed_at >= $f AND o.observed_at <= $t "
            "RETURN o.id", {"s": window.source, "f": to_epoch(window.t_from), "t": to_epoch(window.t_to)}).result_set
        return RetractionResult({r[0] for r in rows})


class Wipe:
    name = "coarse_taint"

    def retract(self, graph, window):
        return RetractionResult({r[0] for r in graph.query("MATCH (m:Mem) RETURN m.id").result_set})


class Boom:
    name = "vector_only"

    def retract(self, graph, window):
        raise RuntimeError("boom")


class Flaky:
    name = "edge_invalidation"

    def __init__(self):
        self.n = 0

    def retract(self, graph, window):
        self.n += 1
        return RetractionResult({"x"} if self.n % 2 else set())


# ---- loader -----------------------------------------------------------------------------------

def test_batched_loader_builds_the_identical_graph():
    a = load(TINY, graph_name="test_b7_a")
    b = load_batched(TINY, graph_name="test_b7_b")
    assert fingerprint(a) == fingerprint(b)


def test_batched_loader_matches_on_a_generated_scenario_with_retracted_sources():
    spec = build("ap_1k").spec
    assert fingerprint(load(spec, graph_name="test_b7_c")) == fingerprint(load_batched(spec, graph_name="test_b7_d"))


def test_loader_rejects_a_missing_premise():
    bad = json.loads(json.dumps(TINY))
    bad["derivations"][0]["premises"].append("ghost")
    with pytest.raises(ValueError, match="ghost"):
        load_batched(bad, graph_name="test_b7_bad")


# ---- statistics -------------------------------------------------------------------------------

def test_percentiles_are_nearest_rank():
    xs = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert runner.percentile(xs, 50) == 50 and runner.percentile(xs, 95) == 100 and runner.percentile(xs, 0) == 10
    assert runner.percentile([7], 95) == 7 and runner.percentile([], 50) is None
    s = runner.stats([3.0, 1.0, 2.0])
    assert (s["n"], s["p50"], s["min"], s["max"]) == (3, 2.0, 1.0, 3.0)


# ---- runner ------------------------------------------------------------------------------------

def test_runner_scores_with_the_shared_metrics_and_isolates_failures():
    sc = build("ap_tiny")
    rows = runner.run_scenario(sc, {"delete_source": ObsOnly(), "coarse_taint": Wipe(), "vector_only": Boom(),
                                    "retcon": ReferenceRetcon()}, repeats=3, prefix="test_b7")
    by = {r["strategy"]: r for r in rows}
    assert [r["strategy"] for r in rows] == ["delete_source", "vector_only", "coarse_taint", "retcon"]  # contract order
    assert by["vector_only"]["error"].startswith("RuntimeError") and by["vector_only"]["metrics"] is None
    ds, ct, rc = by["delete_source"]["metrics"], by["coarse_taint"]["metrics"], by["retcon"]["metrics"]
    assert ds["residual_contamination"] > 0.5 and ds["action_recall"] == 0 and ds["collateral_loss"] == 0
    assert ct["residual_contamination"] == 0 and ct["collateral_loss"] == 1
    assert rc["residual_contamination"] == 0 and rc["collateral_loss"] == 0 and rc["action_recall"] == 1
    for r in rows:
        if not r["error"]:
            assert r["latency_ms"]["n"] == 3 and r["latency_ms"]["p95"] >= r["latency_ms"]["p50"] >= 0
    json.dumps(rows)                                                    # the results file is plain JSON


def test_each_repeat_gets_a_fresh_graph_so_runs_are_comparable():
    sc = build("ap_tiny")
    row = runner.run_scenario(sc, {"retcon": ReferenceRetcon()}, repeats=4, prefix="test_b7")[0]
    assert row["error"] is None and "nondeterministic" not in row["notes"]    # retcon sees an unretracted graph every time


def test_nondeterministic_strategies_are_flagged():
    row = runner.run_scenario(build("ap_tiny"), {"edge_invalidation": Flaky()}, repeats=3, prefix="test_b7")[0]
    assert row["notes"].get("nondeterministic") is True


def test_science_windows_are_applied_in_order_and_unioned():
    spec = json.loads((ROOT / "data" / "fixtures" / "science.json").read_text(encoding="utf8")) \
        if (ROOT / "data" / "fixtures" / "science.json").exists() else None
    if spec is None:
        pytest.skip("science fixture not built (python tasks.py science)")
    ws = windows_of(spec)
    assert len(ws) == len(spec["retractions"]) and ws[0].source == spec["retractions"][0]["source"]
    sc = build("science")
    row = runner.run_scenario(sc, {"retcon": ReferenceRetcon()}, repeats=1, prefix="test_b7")[0]
    m = row["metrics"]
    assert row["windows"] == len(ws) and m["residual_contamination"] == 0 and m["collateral_loss"] == 0
    assert row["latency_per_window_ms"]["n"] == len(ws)


def test_scenarios_have_the_contract_shape():
    for name in ("ap_tiny", "ap_1k"):
        sc = build(name)
        assert sc.domain == "ap" and len(sc.windows) == 1
        gt = sc.spec["ground_truth"]
        assert gt["contaminated"] and gt["truly_supported"] and "recall_list" in gt and "blocked" in gt
    assert abs(build("ap_1k").nodes - 1000) < 100
    assert len(build("ap_1k").spec["ground_truth"]["recall_list"]) >= 2        # more than one executed contaminated action
    with pytest.raises(KeyError):
        build("nope")


# ---- laundering probe -------------------------------------------------------------------------

def test_laundering_curve_separates_a_graph_from_an_observation_only_rule():
    c = laundering.laundering_curve({"delete_source": ObsOnly(), "retcon": ReferenceRetcon()},
                                    depths=(0, 2, 4), repeats=1, prefix="test_b7")
    assert c["residual"]["retcon"] == [0.0, 0.0, 0.0]
    ds = c["residual"]["delete_source"]
    assert all(v is not None and v > 0.5 for v in ds)                   # never reaches a laundered copy


# ---- graph-off ablation -----------------------------------------------------------------------

def test_graph_on_never_pays_the_attacker_after_the_retraction():
    r = ablation.attacker_experiment(False, graph_name="test_b7_on")
    assert r["paid_attacker_after_retraction"] == 0 and r["amount_to_attacker_after"] == 0
    assert r["paid_verified_after_retraction"] == 1                    # the late invoice went to the contract account
    assert r["contaminated_retracted"] == r["contaminated_total"] and r["clean_nodes_retracted"] == 0


def test_graph_off_agents_still_pay_the_attacker():
    r = ablation.attacker_experiment(True, graph_name="test_b7_off")
    assert r["paid_attacker_after_retraction"] >= 1 and r["amount_to_attacker_after"] > 0
    assert r["verification_requests"] == 0                             # no fragility, so no self-check
    assert r["contaminated_retracted"] < r["contaminated_total"]       # the similarity rule missed laundered copies


def test_loosening_the_threshold_trades_the_attacker_for_collateral():
    tight = ablation.attacker_experiment(True, threshold=0.9, vendors=6, graph_name="test_b7_t9")
    loose = ablation.attacker_experiment(True, threshold=0.3, vendors=6, graph_name="test_b7_t3")
    assert loose["nodes_retracted"] > tight["nodes_retracted"]
    assert loose["clean_nodes_retracted"] > tight["clean_nodes_retracted"]     # the price of catching more


def test_api_names_are_the_contract_names():
    assert ReferenceRetcon.name in STRATEGY_NAMES
