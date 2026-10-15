"""Contract v1.1: optional mtype / domain / science source fields are additive."""
import copy
import json
from pathlib import Path

import pytest

from data.load_fixture import load, validate_spec

FIX = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "ap_tiny.json"


@pytest.fixture()
def spec():
    return json.loads(FIX.read_text(encoding="utf8"))


def test_ap_tiny_unchanged_and_valid_without_v11_fields(spec):
    assert "domain" not in spec
    validate_spec(spec, require_ground_truth=True)


def test_default_mtype_tagging(spec):
    g = load(spec, graph_name="test_v11")
    rows = g.query("MATCH (m:Mem) RETURN labels(m), m.mtype").result_set
    for labels, mtype in rows:
        if "Observation" in labels:
            assert mtype == "episodic"
        elif "Belief" in labels:
            assert mtype == "semantic"
        else:
            assert mtype is None  # plans and actions are untagged unless the fixture says so


def test_explicit_procedural_rule_and_science_source_fields(spec):
    spec = copy.deepcopy(spec)
    spec["domain"] = "science"
    spec["sources"][0].update(retracted_at="2026-09-01", rw_reason="Error in Data")
    spec["derivations"][0]["conclusion"]["mtype"] = "procedural"
    g = load(spec, graph_name="test_v11")
    src = g.query("MATCH (s:Source {id:$i}) RETURN s.retracted_at, s.rw_reason",
                  {"i": spec["sources"][0]["id"]}).result_set[0]
    assert src == ["2026-09-01", "Error in Data"]
    cid = spec["derivations"][0]["conclusion"]["id"]
    assert g.query("MATCH (m:Mem {id:$i}) RETURN m.mtype", {"i": cid}).result_set[0][0] == "procedural"


def test_invalid_values_rejected(spec):
    bad = copy.deepcopy(spec)
    bad["domain"] = "support-bot"
    with pytest.raises(ValueError):
        validate_spec(bad)
    bad = copy.deepcopy(spec)
    bad["derivations"][0]["conclusion"]["mtype"] = "emotional"
    with pytest.raises(ValueError):
        validate_spec(bad)
    bad = copy.deepcopy(spec)
    del bad["ground_truth"]["truly_supported"]
    with pytest.raises(ValueError):
        validate_spec(bad, require_ground_truth=True)
