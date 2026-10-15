"""B11: concurrency (writers during a cascade) and tenant isolation. Acceptance: python tasks.py accept B11

The deterministic interleaving test pins a bug the concurrent run cannot reliably hit: a write that lands
between the cascade's tentative flip (Q4) and its re-derivation (Q5)."""
import json
from pathlib import Path

import pytest

from bench.harness.concurrency import consistency, run_concurrency, tenant_isolation
from bench.harness.scenarios import ap_generated
from core.memory import MemoryService
from core.retract import cascade
from core.retrieve.embed import get_embedder
from core.retrieve.q2 import embed_graph
from data.load_fixture import load

pytestmark = pytest.mark.b11
TINY = json.loads((Path(__file__).resolve().parents[2] / "data" / "fixtures" / "ap_tiny.json").read_text(encoding="utf8"))


def _mid_cascade_write(graph_name):
    g = load(TINY, graph_name=graph_name)
    emb = get_embedder("hash")
    embed_graph(g, emb)
    m = MemoryService(g, emb)
    w, rid = TINY["window"], "ret_race"
    f, t = cascade.to_epoch(w["from"]), cascade.to_epoch(w["to"])
    # Q3 + Q4 exactly as cascade.distrust issues them ...
    g.query("MATCH (:Source {id:$s})-[:SUPPORTS]->(o:Observation) WHERE o.status='IN' AND o.observed_at >= $f "
            "AND o.observed_at <= $t SET o.status='OUT', o.run=$run", {"s": w["source"], "f": f, "t": t, "run": rid})
    g.query("MATCH p = (o:Observation {run:$run})-[:PREMISE_OF|JUSTIFIES*1..40]->(x:Mem) WHERE x.status='IN' "
            "WITH x, min(length(p)) AS d SET x.status='OUT', x.run=$run, x.hop=toInteger(d/2)", {"run": rid})
    assert g.query("MATCH (m:Mem {id:'b_addr'}) RETURN m.status").result_set[0][0] == "OUT"   # tentative
    # ... an agent writes now, from a claim that is tentatively OUT but has independent support (the PDF) ...
    m.begin_turn("analyst")
    m.capture.record("analyst", ["b_addr"])
    r = m.remember("Remit address confirmed for the quarterly run.", "belief", "analyst")
    # ... and the cascade finishes
    cascade._rederive(g, rid)
    g.query("MATCH (x:Mem {run:$rid}) SET x.run = null, x.hop = null", {"rid": rid})
    return g, r


def test_a_write_landing_mid_cascade_is_rederived_with_its_premise():
    g, r = _mid_cascade_write("test_b11_race")
    assert r["status"] == "OUT"                                   # correct at write time: premise was tentatively OUT
    assert g.query("MATCH (m:Mem {id:'b_addr'}) RETURN m.status").result_set[0][0] == "IN"
    status = g.query("MATCH (m:Mem {id:$i}) RETURN m.status", {"i": r["node_id"]}).result_set[0][0]
    assert status == "IN", "supported claim written mid-cascade stayed OUT after re-derivation"
    c = consistency(g)
    assert c["stale_in"] == 0 and c["stale_out"] == 0 and c["run_tags_left"] == 0


def test_a_contaminated_write_mid_cascade_stays_out():
    """The inherited tag must not resurrect anything: a claim resting only on the poisoned source stays OUT."""
    g = load(TINY, graph_name="test_b11_race2")
    emb = get_embedder("hash")
    embed_graph(g, emb)
    m = MemoryService(g, emb)
    w, rid = TINY["window"], "ret_race"
    f, t = cascade.to_epoch(w["from"]), cascade.to_epoch(w["to"])
    g.query("MATCH (:Source {id:$s})-[:SUPPORTS]->(o:Observation) WHERE o.status='IN' AND o.observed_at >= $f "
            "AND o.observed_at <= $t SET o.status='OUT', o.run=$run", {"s": w["source"], "f": f, "t": t, "run": rid})
    g.query("MATCH p = (o:Observation {run:$run})-[:PREMISE_OF|JUSTIFIES*1..40]->(x:Mem) WHERE x.status='IN' "
            "WITH x, min(length(p)) AS d SET x.status='OUT', x.run=$run, x.hop=toInteger(d/2)", {"run": rid})
    m.begin_turn("analyst")
    m.capture.record("analyst", ["b_bank_new"])                     # only supported by the poisoned portal
    r = m.remember("Bank change confirmed by analyst.", "belief", "analyst")
    cascade._rederive(g, rid)
    g.query("MATCH (x:Mem {run:$rid}) SET x.run = null, x.hop = null", {"rid": rid})
    assert g.query("MATCH (m:Mem {id:$i}) RETURN m.status", {"i": r["node_id"]}).result_set[0][0] == "OUT"
    assert consistency(g)["stale_in"] == 0


def test_writers_during_a_cascade_are_correct_and_error_free():
    spec = ap_generated(1000, 7)
    r = run_concurrency(spec, n_writers=12, ops_per_writer=8, graph_name="test_b11_conc", cascade_after=0.2)
    assert r["errors"] == {} and r["error_rate"] == 0
    assert r["cascade"] and r["cascade"]["flipped"] > 0
    c = r["consistency"]
    assert c["stale_in"] == 0 and c["stale_out"] == 0 and c["unjustified"] == 0 and c["run_tags_left"] == 0
    assert r["write_ms"]["n"] >= 12 * 8 * 0.9                      # nearly every write completed
    assert r["read_ms"]["p50"] is not None and r["write_ms"]["p95"] is not None


def test_a_tenant_is_untouched_by_work_in_another():
    a = ap_generated(500, 7)
    b = ap_generated(500, 11)
    r = tenant_isolation(a, b, n_writers=6, ops_per_writer=5)
    assert r["b_identical"], (r["b_before"], r["b_after"])
    assert r["leaked_into_a"] == 0 and r["retractions_in_b"] == 0
    assert r["a"]["cascade"]["flipped"] > 0 and r["a"]["consistency"]["stale_in"] == 0
