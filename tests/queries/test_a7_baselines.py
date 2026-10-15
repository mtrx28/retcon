"""A7 acceptance: the five strategies against bench/api.py, and the shape the benchmark claims."""
import json
import os
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

os.environ.setdefault("RETCON_EMBEDDER", "hash")

from bench.api import STRATEGY_NAMES, Strategy, Window, metrics, windows  # noqa: E402
from bench.baselines import all_strategies  # noqa: E402
from bench.baselines.run import markdown, run_scenario  # noqa: E402
from data.load_fixture import load  # noqa: E402

pytestmark = pytest.mark.a7

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "data" / "fixtures" / "ap_tiny.json").read_text(encoding="utf8"))
GT = SPEC["ground_truth"]
W = Window.from_spec(SPEC)


def out_of(name, spec=SPEC, graph="a7_tiny", window=W):
    g = load(spec, graph_name=graph)
    return all_strategies()[name].retract(g, window).out_ids


def test_registry_has_the_five_named_strategies_in_order():
    s = all_strategies()
    assert tuple(s) == STRATEGY_NAMES
    assert all(isinstance(x, Strategy) and x.name == n for n, x in s.items())


def test_expected_out_sets_on_ap_tiny():
    obs = {"obs_portal_bank", "obs_portal_addr"}
    assert out_of("delete_source") == obs
    # one hop: the beliefs extracted straight from those observations (and the address belief too)
    assert out_of("edge_invalidation") == obs | {"b_bank_new", "b_circ_a", "b_addr"}
    contaminated = set(GT["contaminated"])
    assert out_of("retcon") == contaminated
    # any-ancestor: everything RETCON retracts, plus the belief it keeps alive by independent support
    assert out_of("coarse_taint") == contaminated | {"b_addr"}


def test_scores_match_the_story_the_benchmark_tells():
    m = {n: metrics(GT, out_of(n), SPEC["actions"]) for n in STRATEGY_NAMES}
    assert m["retcon"]["residual_contamination"] == 0 and m["retcon"]["collateral_loss"] == 0
    assert m["retcon"]["action_recall"] == 1 and m["retcon"]["action_precision"] == 1
    assert m["coarse_taint"]["residual_contamination"] == 0 and m["coarse_taint"]["collateral_loss"] > 0
    for n in ("delete_source", "vector_only", "edge_invalidation"):
        assert m[n]["residual_contamination"] > 0.5                    # most of the contamination stays
        assert m[n]["action_recall"] == 0                              # no executed payment is flagged


def test_strategies_are_deterministic():
    for n in STRATEGY_NAMES:
        assert out_of(n, graph="a7_det1") == out_of(n, graph="a7_det2")


def test_vector_only_threshold_trades_residual_for_collateral():
    g = load(SPEC, graph_name="a7_vec")
    from bench.baselines.vector_only import VectorOnly
    loose = VectorOnly(threshold=0.2).retract(g, W).out_ids
    tight = VectorOnly(threshold=0.99).retract(g, W).out_ids
    assert tight <= loose and tight == {"obs_portal_bank", "obs_portal_addr"} | (tight - {"x"})
    assert len(loose) > len(tight)


def test_laundering_probe_counts_echoes_for_baselines_and_sources_for_retcon():
    spec = {"tenant": "l", "sources": [{"id": "s0", "kind": "portal", "trust": 0.5}],
            "agents": [{"id": "a", "role": "x"}], "actions": [],
            "observations": [{"id": "o1", "source": "s0", "observed_at": "2026-10-05T00:00:00Z", "text": "claim"}],
            "derivations": [
                {"id": "d1", "rule": "extract", "agent": "a", "premises": ["o1"],
                 "conclusion": {"id": "n1", "kind": "belief", "text": "n1"}},
                {"id": "d2", "rule": "infer", "agent": "a", "premises": ["n1"],
                 "conclusion": {"id": "n2", "kind": "belief", "text": "echo by agent 2"}},
                {"id": "d3", "rule": "infer", "agent": "a", "premises": ["n1"],
                 "conclusion": {"id": "n3", "kind": "belief", "text": "echo by agent 3"}},
                {"id": "d4", "rule": "infer", "agent": "a", "premises": ["n2"],
                 "conclusion": {"id": "n4", "kind": "belief", "text": "settled"}},
                {"id": "d5", "rule": "infer", "agent": "a", "premises": ["n3"],
                 "conclusion": {"id": "n4", "kind": "belief", "text": "settled"}}],
            "ground_truth": {"contaminated": [], "truly_supported": []}}
    g = load(spec, graph_name="a7_launder")
    s = all_strategies()
    assert s["delete_source"].support_count(g, "n4") == 2      # counts justifications: inflated by echoes
    assert s["retcon"].support_count(g, "n4") == 1             # one real source


def test_windows_cover_both_domains():
    assert [(w.source, w.t_from, w.t_to) for w in windows(SPEC)] == [(W.source, W.t_from, W.t_to)]
    sci = json.loads((ROOT / "data" / "fixtures" / "science.json").read_text(encoding="utf8"))
    ws = windows(sci)
    assert len(ws) == len(sci["retractions"]) >= 30 and all(isinstance(w, Window) for w in ws)


@settings(max_examples=int(os.getenv("RETCON_BASELINE_N", "30")), deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(data=st.data())
def test_strategy_hierarchy_holds_on_random_graphs(data):
    """delete_source <= edge_invalidation <= coarse_taint, retcon <= coarse_taint, retcon == reference."""
    sys.path.insert(0, str(ROOT / "tests" / "differential"))
    from graphgen import SOURCES, iso, specs
    from jtms_ref import RefJTMS
    spec = data.draw(specs())
    src = data.draw(st.sampled_from(SOURCES))
    a = data.draw(st.integers(0, 9))
    b = data.draw(st.integers(a, 9))
    w = Window(src, iso(a), iso(b))
    o = {}
    for n, strat in all_strategies().items():
        o[n] = strat.retract(load(spec, graph_name=f"a7_prop_{n}"), w).out_ids
    assert o["delete_source"] <= o["edge_invalidation"] <= o["coarse_taint"]
    assert o["delete_source"] <= o["vector_only"]
    assert o["retcon"] <= o["coarse_taint"]
    ref = RefJTMS(spec)
    ref.distrust("r", src, iso(a), iso(b))
    assert o["retcon"] == {n for n, s in ref.labelling().items() if s == "OUT"}


def test_runner_produces_a_row_per_strategy_and_isolates_failures():
    class Boom:
        name = "coarse_taint"

        def retract(self, graph, window):
            raise RuntimeError("boom")
    strategies = all_strategies()
    strategies["coarse_taint"] = Boom()
    rows = run_scenario("ap_tiny", strategies, graph_prefix="a7_run")
    assert [r["strategy"] for r in rows] == list(STRATEGY_NAMES)
    bad = next(r for r in rows if r["strategy"] == "coarse_taint")
    assert bad["error"].startswith("RuntimeError") and bad["metrics"] is None
    good = next(r for r in rows if r["strategy"] == "retcon")
    assert good["metrics"]["residual_contamination"] == 0 and good["error"] is None
    md = markdown(rows)
    assert "ap_tiny" in md and "retcon" in md and "error: RuntimeError" in md


def test_science_slice_through_the_same_interface():
    rows = run_scenario("science_3", graph_prefix="a7_sci")
    by = {r["strategy"]: r["metrics"] for r in rows}
    assert by["retcon"]["residual_contamination"] == 0 and by["retcon"]["collateral_loss"] == 0
    assert by["coarse_taint"]["residual_contamination"] == 0 and by["coarse_taint"]["collateral_loss"] > 0
    assert by["delete_source"]["residual_contamination"] > by["retcon"]["residual_contamination"]
    assert all(r["domain"] == "science" for r in rows)
