"""B7: the AP precision scenario. Several poisoned vendors with their own windows, corroborated facts, and
legitimate payments that route partly through a bad source. A coarse rule must show real collateral loss;
the justification-aware rule must not.

Acceptance: python tasks.py accept B7"""
import pytest

from bench.api import RetractionResult, Window
from bench.harness import runner
from bench.harness.reference import ReferenceRetcon
from bench.harness.scenarios import build, profile, windows_of

pytestmark = pytest.mark.b7


class CoarseTaint:
    """Any-ancestor rule in miniature: everything downstream of an in-window bad observation, no
    re-derivation. (Lane A's real coarse_taint plugs in through the same interface.)"""
    name = "coarse_taint"

    def retract(self, graph, window: Window):
        from core.retract.cascade import to_epoch
        f, t = to_epoch(window.t_from), to_epoch(window.t_to)
        seeds = {r[0] for r in graph.query(
            "MATCH (:Source {id:$s})-[:SUPPORTS]->(o:Observation) WHERE o.observed_at >= $f AND o.observed_at <= $t "
            "RETURN o.id", {"s": window.source, "f": f, "t": t}).result_set}
        down = {r[0] for r in graph.query(
            "MATCH (o:Observation)-[:PREMISE_OF|JUSTIFIES*1..40]->(x:Mem) WHERE o.id IN $ids RETURN DISTINCT x.id",
            {"ids": sorted(seeds)}).result_set}
        return RetractionResult(seeds | down)


class OneHop:
    name = "edge_invalidation"

    def retract(self, graph, window):
        from core.retract.cascade import to_epoch
        f, t = to_epoch(window.t_from), to_epoch(window.t_to)
        seeds = {r[0] for r in graph.query(
            "MATCH (:Source {id:$s})-[:SUPPORTS]->(o:Observation) WHERE o.observed_at >= $f AND o.observed_at <= $t "
            "RETURN o.id", {"s": window.source, "f": f, "t": t}).result_set}
        hop = {r[0] for r in graph.query(
            "MATCH (o:Observation)-[:PREMISE_OF]->(:Justification)-[:JUSTIFIES]->(x:Mem) WHERE o.id IN $ids "
            "RETURN DISTINCT x.id", {"ids": sorted(seeds)}).result_set}
        return RetractionResult(seeds | hop)


@pytest.fixture(scope="module")
def sc():
    return build("ap_prec_1k")


def test_scenario_has_the_requested_shape(sc):
    p = profile(sc)
    assert 5 <= p["poisoned_vendors"] <= 10
    assert p["distinct_windows"] == p["poisoned_vendors"]               # every poisoned vendor has its own window
    assert 0.30 <= p["corroborated_share"] <= 0.50, p                   # about 30-50% confirmed by a trusted source
    assert p["legit_payments"] >= 10 and p["legit_executed"] >= 1 and p["legit_pending"] >= 1
    gt = sc.spec["ground_truth"]
    assert len(gt["recall_list"]) >= 3 and len(gt["blocked"]) >= 3     # real contaminated payments exist too
    assert len(windows_of(sc.spec)) == p["poisoned_vendors"]


def test_windows_really_differ_and_leave_some_facts_outside(sc):
    ws = windows_of(sc.spec)
    assert len({(w.t_from, w.t_to) for w in ws}) == len(ws)
    # each portal also published facts outside its own window; those are untouched by the retraction
    dead = set(sc.spec["ground_truth"]["contaminated"])
    for w in ws:
        slug = w.source.rsplit("-", 1)[0]
        outside = [o["id"] for o in sc.spec["observations"]
                   if o["source"] == w.source and not (w.t_from <= o["observed_at"] <= w.t_to)]
        assert outside and not set(outside) & dead, w.source


def test_a_poisoned_vendor_can_have_a_correct_payment(sc):
    """Corroborated bank change: the payment rests partly on the bad portal and is still right."""
    acts = {a["id"]: a for a in sc.spec["actions"]}
    live = set(sc.spec["ground_truth"]["truly_supported"])
    poisoned = {w.source.rsplit("-", 1)[0] for w in windows_of(sc.spec)}
    good = [a for i, a in acts.items() if i in live and a["vendor"] in poisoned]
    bad = [a for i, a in acts.items() if i not in live and a["vendor"] in poisoned]
    assert good and bad                                                  # both kinds among poisoned vendors


def test_coarse_rule_loses_correct_facts_and_the_graph_rule_does_not(sc):
    rows = runner.run_scenario(sc, {"coarse_taint": CoarseTaint(), "edge_invalidation": OneHop(),
                                    "retcon": ReferenceRetcon()}, repeats=1, prefix="test_b7p")
    by = {r["strategy"]: r["metrics"] for r in rows}
    assert all(r["error"] is None for r in rows)
    ct, eh, rc = by["coarse_taint"], by["edge_invalidation"], by["retcon"]
    assert ct["residual_contamination"] == 0                             # it finds every contaminated node ...
    assert ct["collateral_loss"] > 0.05, ct                              # ... and destroys correct ones to do it
    assert rc["residual_contamination"] == 0 and rc["collateral_loss"] == 0
    assert rc["action_recall"] == 1 and rc["blocked_recall"] == 1
    assert eh["residual_contamination"] > 0                              # one hop cannot reach laundered copies
    # the coarse rule also flags correct EXECUTED payments for recall: precision is what suffers
    assert ct["action_precision"] < 1.0 and rc["action_precision"] == 1.0
    assert rows[0]["profile"]["poisoned_vendors"] == profile(sc)["poisoned_vendors"]


def test_default_scenarios_are_untouched_by_the_precision_options():
    spec = build("ap_tiny").spec
    assert "windows" not in spec or len(spec.get("windows", [])) <= 1
    one = build("ap_1k")
    assert len(windows_of(one.spec)) == 1 and one.spec["meta"].get("precision") is None
