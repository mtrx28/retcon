import json
from pathlib import Path

import pytest

from data.load_fixture import load

FIX = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "ap_tiny.json"


@pytest.fixture(scope="module")
def graph():
    spec = json.loads(FIX.read_text(encoding="utf8"))
    return load(spec, graph_name="test_fixture_load"), spec


def test_all_mem_nodes_loaded_and_in(graph):
    g, spec = graph
    expected = (len(spec["observations"])
                + len({d["conclusion"]["id"] for d in spec["derivations"]})
                + len(spec["actions"]))
    row = g.query("MATCH (m:Mem) RETURN count(m), sum(CASE WHEN m.status='IN' THEN 1 ELSE 0 END)").result_set[0]
    assert row == [expected, expected]


def test_or_of_and_justifications(graph):
    g, _ = graph
    n = g.query("MATCH (j:Justification)-[:JUSTIFIES]->(:Mem {id:'b_addr'}) RETURN count(j)").result_set[0][0]
    assert n == 2  # independent support: portal OR contract pdf
    n = g.query("MATCH (p)-[:PREMISE_OF]->(:Justification {id:'d_plan_1'}) RETURN count(p)").result_set[0][0]
    assert n == 2  # AND of two premises


def test_ground_truth_ids_exist(graph):
    g, spec = graph
    ids = {r[0] for r in g.query("MATCH (m:Mem) RETURN m.id").result_set}
    for k in ("contaminated", "truly_supported", "recall_list", "blocked"):
        assert set(spec["ground_truth"][k]) <= ids, k
