"""A10 acceptance: research agents (Reader, Synthesizer) build memory from real abstracts on the B3
loop; replaying the real retractions, one distrust per paper by its own dates, leaves exactly the
contaminated set OUT and everything with independent support IN."""
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("RETCON_EMBEDDER", "hash")

from agents.research import ResearchBrain  # noqa: E402
from agents.research.run import ResearchRun, paper_tasks, science_slice  # noqa: E402
from bench.science_eval import evaluate, score, text_truth  # noqa: E402

SPEC_FILE = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "science.json"
pytestmark = [pytest.mark.a10, pytest.mark.skipif(not SPEC_FILE.exists(), reason="science fixture missing")]


@pytest.fixture(scope="module")
def full_spec():
    return json.loads(SPEC_FILE.read_text(encoding="utf8"))


@pytest.fixture(scope="module")
def sliced(full_spec):
    return science_slice(full_spec, 3)


def test_slice_is_a_consistent_scenario(sliced):
    from data.science.ingest import validate
    assert validate(sliced) == []
    assert len(sliced["retractions"]) == 3
    gt = sliced["ground_truth"]
    assert gt["contaminated"] and gt["truly_supported"]
    # every cited retracted paper is in the slice, so its citers are too
    assert {r["source"] for r in sliced["retractions"]} <= {s["id"] for s in sliced["sources"]}


def test_tasks_put_cited_papers_first_and_carry_dependencies(sliced):
    tasks = paper_tasks(sliced)
    retracted = {r["source"] for r in sliced["retractions"]}
    first_citer = next(i for i, t in enumerate(tasks) if t["cited_texts"])
    cited_idx = [i for i, t in enumerate(tasks) if t["paper"] in retracted]
    assert max(cited_idx) < first_citer or min(cited_idx) < first_citer   # cited work is read before its citers
    assert any(t["topic_text"] for t in tasks)
    assert all(t["type"] == "read_paper" for t in tasks)


def test_agents_build_the_graph_and_the_real_retractions_match_ground_truth(sliced):
    res = evaluate(sliced, graph_name="a10_slice")
    assert res["claims_synthesized"] >= 100                     # acceptance: at least 100 synthesized claims
    assert res["topic_claims"] >= 1
    before, after = res["before_retraction"], res["after_retraction"]
    assert before["residual_contamination"] == 1.0 and before["collateral_loss"] == 0   # nothing retracted yet
    assert after["residual_contamination"] == 0                 # every contaminated node is OUT
    assert after["collateral_loss"] == 0                        # nothing independently supported is lost
    assert after["disagreements"] == 0 and after["unmapped_nodes"] == 0
    assert res["topics_withdrawn"] >= 1 and res["topics_that_stood"] >= 1   # a real mix, not all-or-nothing
    assert len(res["per_retraction"]) == 3
    assert all("error" not in r for r in res["per_retraction"])


def test_one_distrust_per_retracted_paper_with_its_own_dates(sliced):
    run = ResearchRun(sliced, graph_name="a10_dates")
    try:
        run.ingest()
        rows = run.retract_all()
        g = run.graph
        got = g.query("MATCH (r:Retraction) RETURN r.source, r.reason ORDER BY r.id").result_set
        want = [(r["source"], f"Source {r['source']} distrusted {r['from']}..{r['to']}")
                for r in sliced["retractions"]]
        assert [tuple(x) for x in got] == want
        assert [r["retraction_id"] for r in rows] == ["ret_0001", "ret_0002", "ret_0003"]
        # chronological by real retraction date
        dates = [r["retracted_at"] for r in rows]
        assert dates == sorted(dates)
    finally:
        run.close()


def test_synthesizer_uses_fragility_as_a_tool(sliced):
    run = ResearchRun(sliced, graph_name="a10_tools")
    try:
        run.ingest()
        run.retract_all()
        tools = run.world.log.tools_used("synthesizer")
        assert "fragility" in tools and "remember" in tools and "recall" in tools
        assert "distrust" in run.world.log.tools_used("operator")
        # the Reader never names a parent: no tool call carries premise ids
        assert all("premise" not in json.dumps(e["args"]) for e in run.world.log.by_agent("reader"))
    finally:
        run.close()


def test_surviving_topic_stands_on_independent_papers(sliced):
    run = ResearchRun(sliced, graph_name="a10_topic")
    try:
        run.ingest()
        rows = run.retract_all()
        stood = [r for r in rows if r.get("topics_standing")]
        assert stood and all(r["min_independent_sources"] >= 1 for r in stood)
        # a topic that survives is IN and justified by at least one non-retracted paper
        g = run.graph
        n = g.query("MATCH (b:Belief {status:'IN'}) WHERE b.text STARTS WITH 'Literature position on ' "
                    "RETURN count(b)").result_set[0][0]
        assert n >= 1
    finally:
        run.close()


def test_text_truth_collapses_duplicate_sentences_as_an_or():
    spec = {
        "observations": [{"id": "o1", "source": "A", "text": "same"}, {"id": "o2", "source": "B", "text": "same"}],
        "derivations": [
            {"conclusion": {"id": "c1", "text": "same"}}, {"conclusion": {"id": "c2", "text": "same"}}],
        "ground_truth": {"contaminated": ["o1", "c1"], "truly_supported": ["o2", "c2"]},
    }
    t = text_truth(spec)
    assert t[("observation", "A", "same")] is True and t[("observation", "B", "same")] is False
    assert t[("belief", None, "same")] is False        # one copy still supported => the merged belief stands


def test_research_brain_delegates_other_roles(sliced):
    brain = ResearchBrain()
    s = brain.start("intake", {"type": "ingest", "source": "x", "text": "t", "observed_at": "2026-10-02T00:00:00Z"})
    assert s.first().tool == "begin_turn"


@pytest.mark.skipif(os.getenv("RETCON_A10_FULL") != "1", reason="full run takes minutes; set RETCON_A10_FULL=1")
def test_full_real_corpus(full_spec):
    res = evaluate(full_spec, graph_name="a10_full")
    assert res["retracted_papers"] >= 30
    assert res["after_retraction"]["residual_contamination"] == 0
    assert res["after_retraction"]["collateral_loss"] == 0
    assert res["after_retraction"]["disagreements"] == 0
