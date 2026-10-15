"""A2: property-based tests of the JTMS invariants, run against FalkorDB through the real engine.

After ANY random sequence of writes (random graph) and distrust/reinstate operations:
  P1  every IN derived node has a justification whose premises are all IN
  P2  no OUT derived node has such a justification
  P3  an observation is OUT iff an active retraction covers it
  P4  cascade scratch tags (run, hop) are never left behind
  P5  the labelling equals the reference least fixpoint (well-foundedness; differential)
  P6  reinstating every retraction restores the exact initial labelling
"""
import os
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "differential"))
from graphgen import iso, op_scripts, specs  # noqa: E402
from jtms_ref import RefJTMS  # noqa: E402

from core.retract.cascade import distrust, reinstate  # noqa: E402
from data.load_fixture import load  # noqa: E402

pytestmark = pytest.mark.a2

N = int(os.getenv("RETCON_PROP_N", "60"))
GRAPH = "prop_a2"
SETTINGS = settings(max_examples=N, deadline=None, derandomize=False,
                    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])


def labelling(g):
    return {r[0]: r[1] for r in g.query("MATCH (m:Mem) RETURN m.id, m.status").result_set}


def check_invariants(g, ref):
    st = labelling(g)
    justs = g.query(
        "MATCH (j:Justification)-[:JUSTIFIES]->(c:Mem) "
        "MATCH (p:Mem)-[:PREMISE_OF]->(j) RETURN c.id, j.id, collect(p.id)").result_set
    supported = {c for c, _, ps in justs if ps and all(st[p] == "IN" for p in ps)}
    obs = {r[0] for r in g.query("MATCH (o:Observation) RETURN o.id").result_set}
    for n, s in st.items():
        if n in obs:
            continue
        assert (s == "IN") == (n in supported), f"P1/P2 violated at {n}: {s}, supported={n in supported}"
    gone = ref.retracted_observations()
    for o in obs:
        assert (st[o] == "OUT") == (o in gone), f"P3 violated at {o}"
    tags = g.query("MATCH (m:Mem) WHERE m.run IS NOT NULL OR m.hop IS NOT NULL RETURN count(m)").result_set[0][0]
    assert tags == 0, "P4: scratch tags left behind"
    assert st == ref.labelling(), "P5: engine disagrees with reference least fixpoint"


@SETTINGS
@given(spec=specs(), ops=op_scripts())
def test_invariants_hold_after_random_operations(spec, ops):
    g = load(spec, graph_name=GRAPH)
    ref = RefJTMS(spec)
    initial = labelling(g)
    assert all(v == "IN" for v in initial.values())
    check_invariants(g, ref)
    active: list[str] = []
    for op in ops:
        if op[0] == "distrust":
            _, src, a, b = op
            res = distrust(g, src, iso(a), iso(b))
            ref.distrust(res["retraction_id"], src, iso(a), iso(b))
            active.append(res["retraction_id"])
        elif active:
            rid = active.pop(op[1] % len(active))
            reinstate(g, rid)
            ref.reinstate(rid)
        check_invariants(g, ref)
    for rid in list(active):  # P6
        reinstate(g, rid)
        ref.reinstate(rid)
        check_invariants(g, ref)
    assert labelling(g) == initial, "P6: reinstating everything did not restore the initial state"
