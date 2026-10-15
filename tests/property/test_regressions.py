"""A2 regressions: bugs the property tests found in the A1 engine, pinned as small explicit cases."""
import pytest

from core.retract.cascade import distrust, reinstate
from data.load_fixture import load

pytestmark = pytest.mark.a2


def spec(observations, derivations):
    return {"tenant": "reg", "sources": [{"id": "s0", "kind": "portal", "trust": 0.5},
                                         {"id": "s1", "kind": "portal", "trust": 0.5}],
            "agents": [{"id": "a", "role": "x"}], "actions": [],
            "observations": [{"id": i, "source": s, "observed_at": "2026-10-05T00:00:00Z", "text": i}
                             for i, s in observations],
            "derivations": [{"id": f"d{k}", "rule": "infer", "agent": "a", "premises": p,
                             "conclusion": {"id": c, "kind": "belief", "text": c}}
                            for k, (c, p) in enumerate(derivations)]}


def st(g):
    return {r[0]: r[1] for r in g.query("MATCH (m:Mem) RETURN m.id, m.status").result_set}


W = ("2026-10-01T00:00:00Z", "2026-10-09T00:00:00Z")


def test_reinstating_first_retraction_keeps_overlapping_distrust():
    """Two retractions cover the same observation: undoing one must not resurrect it."""
    g = load(spec([("o0", "s0")], [("n0", ["o0"])]), graph_name="reg_a2")
    r1 = distrust(g, "s0", *W)["retraction_id"]
    distrust(g, "s0", *W)
    reinstate(g, r1)
    assert st(g) == {"o0": "OUT", "n0": "OUT"}


def test_reinstate_revives_node_flipped_by_a_different_retraction():
    """y is supported by x (killed by R1) OR o2 (killed by R2). Undoing R1 must bring y back even
    though R2 is what flipped y: y has a fully IN justification again."""
    g = load(spec([("o1", "s0"), ("o2", "s1")],
                  [("x", ["o1"]), ("y", ["o2"]), ("y", ["x"])]), graph_name="reg_a2")
    r1 = distrust(g, "s0", *W)["retraction_id"]   # o1, x OUT; y still IN via o2
    distrust(g, "s1", *W)                          # o2 OUT; y flips OUT (its x justification is dead)
    assert st(g)["y"] == "OUT"
    reinstate(g, r1)                               # o1, x IN again => y supported through x
    assert st(g) == {"o1": "IN", "o2": "OUT", "x": "IN", "y": "IN"}


def test_cycle_never_survives_and_comes_back_with_its_anchor():
    g = load(spec([("o0", "s0")], [("a", ["o0"]), ("a", ["b"]), ("b", ["a"])]), graph_name="reg_a2")
    r = distrust(g, "s0", *W)["retraction_id"]
    assert st(g) == {"o0": "OUT", "a": "OUT", "b": "OUT"}
    reinstate(g, r)
    assert set(st(g).values()) == {"IN"}


def test_loader_rejects_missing_premise():
    with pytest.raises(ValueError):
        load(spec([("o0", "s0")], [("n0", ["ghost"])]), graph_name="reg_a2")
