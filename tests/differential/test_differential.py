"""A2: differential test. The Cypher engine must agree with the in-memory reference JTMS
(tests/differential/jtms_ref.py) on random graphs: same labelling, same set of nodes flipped,
same blocked and recall lists. `python tasks.py accept A2` runs 1,000 graphs (RETCON_DIFF_N)."""
import os
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from graphgen import SOURCES, iso, specs  # noqa: E402
from jtms_ref import RefJTMS  # noqa: E402

from core.retract.cascade import distrust  # noqa: E402
from data.load_fixture import load  # noqa: E402

pytestmark = pytest.mark.a2

N = int(os.getenv("RETCON_DIFF_N", "100"))


def labelling(g):
    return {r[0]: r[1] for r in g.query("MATCH (m:Mem) RETURN m.id, m.status").result_set}


@settings(max_examples=N, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(spec=specs(), src=st.sampled_from(SOURCES), a=st.integers(0, 9), width=st.integers(0, 9))
def test_engine_agrees_with_reference(spec, src, a, width):
    b = min(9, a + width)
    g = load(spec, graph_name="diff_a2")
    ref = RefJTMS(spec)
    before = ref.labelling()
    assert set(before.values()) == {"IN"}

    res = distrust(g, src, iso(a), iso(b))
    ref.distrust(res["retraction_id"], src, iso(a), iso(b))
    expected = ref.labelling()

    assert labelling(g) == expected
    assert set(res["flipped_ids"]) == {n for n in expected if expected[n] == "OUT"}

    actions = {x["id"]: x for x in spec["actions"]}
    exp_blocked = sorted(n for n in actions if expected[n] == "OUT" and not actions[n]["executed"])
    exp_recall = sorted(n for n in actions if expected[n] == "OUT" and actions[n]["executed"])
    assert sorted(res["blocked_action_ids"]) == exp_blocked
    assert sorted(a_["action_id"] for a_ in res["recall_list"]) == exp_recall
    amounts = [a_["amount"] for a_ in res["recall_list"]]
    assert amounts == sorted(amounts, reverse=True)
