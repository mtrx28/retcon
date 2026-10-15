"""B10: science ingest (Retraction Watch + OpenAlex raw files -> fixture with ground truth).
Acceptance: python tasks.py accept B10

The synthetic corpus below follows the OpenAlex work schema, so the same code runs on the real pull.
If data/science/raw exists, the real-data test also checks the plan's acceptance shape (>= 30 retracted).
"""
import json
from pathlib import Path

import pytest

from core.retract.cascade import distrust
from data.load_fixture import load, validate_spec
from data.science import ingest

pytestmark = pytest.mark.b10
RAW_REAL = Path(__file__).resolve().parents[2] / "data" / "science" / "raw"


def inv(text):
    """OpenAlex abstract_inverted_index for `text`."""
    out = {}
    for i, w in enumerate(text.split()):
        out.setdefault(w, []).append(i)
    return out


def work(wid, title, abstract, date, topic, refs=(), venue="journal"):
    return {"id": f"https://openalex.org/{wid}", "title": title, "doi": f"https://doi.org/10.1/{wid}",
            "publication_date": date, "abstract_inverted_index": inv(abstract),
            "primary_location": {"source": {"type": venue}},
            "primary_topic": {"id": f"https://openalex.org/T{topic}", "display_name": f"Topic {topic}"},
            "referenced_works": [f"https://openalex.org/{r}" for r in refs]}


ABS = ("Background text sets the scene for the study. We show that protein {x} is required for membrane repair. "
       "Loss of {x} increases cell death after injury. Methods are described elsewhere.")


@pytest.fixture()
def raw(tmp_path):
    root = tmp_path / "raw"
    (root / "openalex" / "retracted").mkdir(parents=True)
    (root / "openalex" / "citing").mkdir(parents=True)
    sel = {"subject": "(BLS) Biology - Cellular", "papers": [
        {"openalex_id": "W1", "doi": "10.1/W1", "retraction_date": "3/14/2017 0:00", "original_date": "1/1/2015",
         "rw_reason": "+Error in Data;+Results Not Reproducible", "rw_record_id": "11"},
        {"openalex_id": "W2", "doi": "10.1/W2", "retraction_date": "11/2/2016 0:00", "original_date": "2/2/2014",
         "rw_reason": "+Falsification/Fabrication of Data", "rw_record_id": "12"}]}
    (root / "selection.json").write_text(json.dumps(sel))
    retracted = [work("W1", "Repair factor A", ABS.format(x="A"), "2015-01-10", 1),
                 work("W2", "Repair factor B", ABS.format(x="B"), "2014-03-05", 2)]
    citing = [work("W10", "Follow-up on A", ABS.format(x="A2"), "2016-02-01", 1, refs=["W1"], venue="repository"),
              work("W11", "Review of A and B", ABS.format(x="AB"), "2016-06-01", 3, refs=["W1", "W2"]),
              work("W12", "Independent study of A", ABS.format(x="A3"), "2016-09-09", 1, refs=["W99"]),
              work("W13", "Follow-up on B", ABS.format(x="B2"), "2015-05-05", 2, refs=["W2"])]
    for w in retracted:
        (root / "openalex" / "retracted" / f"{w['id'].rsplit('/', 1)[-1]}.json").write_text(json.dumps(w))
    for w in citing:
        (root / "openalex" / "citing" / f"{w['id'].rsplit('/', 1)[-1]}.json").write_text(json.dumps(w))
    return root


@pytest.fixture()
def spec(raw):
    return ingest.build(*ingest.load_raw(raw))


# ---- text and date helpers --------------------------------------------------------------------

def test_abstract_reconstruction_and_claim_picking_is_deterministic():
    text = ABS.format(x="A")
    assert ingest.abstract_text(inv(text)) == text
    claims = ingest.pick_claims(text, 2)
    assert claims == ingest.pick_claims(text, 2)
    assert claims == ["We show that protein A is required for membrane repair.",
                      "Loss of A increases cell death after injury."]
    assert ingest.pick_claims("", 2) == [] and ingest.abstract_text(None) == ""


def test_retraction_watch_dates_are_parsed_not_compared_as_strings():
    assert ingest.rw_date("3/14/2017 0:00") == "2017-03-14"
    assert ingest.rw_date("11/2/2016 0:00") == "2016-11-02"
    assert ingest.rw_date("") is None and ingest.rw_date("garbage") is None


# ---- mapping ----------------------------------------------------------------------------------

def test_papers_become_sources_with_dataset_fields(spec):
    src = {s["id"]: s for s in spec["sources"]}
    assert set(src) == {"W1", "W2", "W10", "W11", "W12", "W13"}
    assert src["W1"]["retracted_at"] == "2017-03-14" and src["W1"]["rw_reason"] == "+Error in Data;+Results Not Reproducible"
    assert "retracted_at" not in src["W10"]
    assert src["W10"]["trust"] < src["W12"]["trust"]            # repository/preprint < journal
    assert spec["domain"] == "science"
    validate_spec(spec, require_ground_truth=True)              # contract v1.1


def test_claims_are_observations_dated_by_publication(spec):
    obs = {o["id"]: o for o in spec["observations"]}
    assert obs["obs_W1_0"]["observed_at"] == "2015-01-10T00:00:00Z" and obs["obs_W1_0"]["source"] == "W1"
    assert len([o for o in obs.values() if o["source"] == "W1"]) == 2


def test_citing_a_retracted_paper_means_resting_on_it(spec):
    d = {x["id"]: x for x in spec["derivations"]}
    assert d["d_claim_W10_0"]["premises"] == ["obs_W10_0", "obs_W1_0"]
    assert d["d_claim_W11_0"]["premises"] == ["obs_W11_0", "obs_W1_0", "obs_W2_0"]
    assert d["d_claim_W12_0"]["premises"] == ["obs_W12_0"]       # cites something outside the corpus
    assert d["d_claim_W1_0"]["premises"] == ["obs_W1_0"]


def test_topic_claims_are_or_over_papers(spec):
    topic = {}
    for x in spec["derivations"]:
        if x["conclusion"]["id"].startswith("topic_"):
            topic.setdefault(x["conclusion"]["id"], []).append(x["premises"][0])
    assert len(topic) == 2                                       # topics 1 and 2; topic 3 has one paper
    sizes = sorted(len(v) for v in topic.values())
    assert sizes == [2, 3]


# ---- ground truth ------------------------------------------------------------------------------

def test_ground_truth_by_hand(spec):
    gt = spec["ground_truth"]
    dead, live = set(gt["contaminated"]), set(gt["truly_supported"])
    assert {"obs_W1_0", "obs_W1_1", "obs_W2_0", "claim_W1_0", "claim_W2_0"} <= dead
    assert "claim_W10_0" in dead and "claim_W11_0" in dead and "claim_W13_0" in dead   # laundered through citation
    assert {"obs_W10_0", "obs_W12_0", "claim_W12_0", "obs_W11_0"} <= live               # the papers' own words survive
    topics = {x["conclusion"]["id"]: [] for x in spec["derivations"] if x["conclusion"]["id"].startswith("topic_")}
    for x in spec["derivations"]:
        if x["conclusion"]["id"] in topics:
            topics[x["conclusion"]["id"]].append(x["premises"][0])
    t1 = next(t for t, ps in topics.items() if "claim_W12_0" in ps)     # topic with an independent paper
    t2 = next(t for t, ps in topics.items() if "claim_W2_0" in ps)      # topic where every path is retracted
    assert t1 in live and t2 in dead
    assert dead.isdisjoint(live)
    assert ingest.validate(spec) == []


def test_retractions_are_chronological_one_per_paper(spec):
    r = spec["retractions"]
    assert [x["source"] for x in r] == ["W2", "W1"]              # 2016-11-02 before 2017-03-14
    assert r[0]["retracted_at"] == "2016-11-02" and r[0]["reason"] == "+Falsification/Fabrication of Data"
    assert r[1]["from"] == "2015-01-10T00:00:00Z"


def test_ground_truth_equals_the_live_engine(spec):
    """Distrust each retracted paper by its real dates; FalkorDB's OUT set must equal the contaminated set."""
    g = load(spec, graph_name="test_b10")
    for r in spec["retractions"]:
        distrust(g, r["source"], r["from"], r["to"], reason=r["reason"])
    out = {row[0] for row in g.query("MATCH (m:Mem {status:'OUT'}) RETURN m.id").result_set}
    assert out == set(spec["ground_truth"]["contaminated"])
    src = g.query("MATCH (s:Source {id:'W1'}) RETURN s.retracted_at, s.rw_reason").result_set[0]
    assert src == ["2017-03-14", "+Error in Data;+Results Not Reproducible"]


def test_validate_catches_broken_scenarios(spec):
    bad = json.loads(json.dumps(spec))
    bad["derivations"][0]["premises"].append("nope")
    bad["ground_truth"]["truly_supported"].pop()
    problems = ingest.validate(bad)
    assert any("unknown premise" in p for p in problems) and any("ground truth" in p for p in problems)


def test_cli_writes_a_loadable_fixture(raw, tmp_path, monkeypatch, capsys):
    out = tmp_path / "science.json"
    monkeypatch.setattr("sys.argv", ["ingest", "--raw", str(raw), "--out", str(out)])
    ingest.main()
    assert "2 retracted" in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf8"))["domain"] == "science"


@pytest.mark.skipif(not (RAW_REAL / "selection.json").exists(), reason="real data not downloaded on this machine")
def test_real_data_meets_the_acceptance_shape():
    spec = ingest.build(*ingest.load_raw(RAW_REAL))
    assert ingest.validate(spec) == []
    retracted = [s for s in spec["sources"] if s.get("retracted_at")]
    assert len(retracted) >= 30
    assert all(s["rw_reason"] for s in retracted)
    gt = spec["ground_truth"]
    assert gt["contaminated"] and gt["truly_supported"]
    topics = {d["conclusion"]["id"] for d in spec["derivations"] if d["conclusion"]["id"].startswith("topic_")}
    # independent same-topic papers exist, so some topic claims survive and some do not (a real benchmark)
    assert topics & set(gt["contaminated"]) and topics & set(gt["truly_supported"])
    assert all(not s["rw_reason"].endswith(";") for s in retracted)


@pytest.mark.skipif(not (RAW_REAL / "selection.json").exists(), reason="real data not downloaded on this machine")
def test_real_data_ground_truth_equals_the_live_engine():
    """All real retractions, applied by their own dates, leave exactly the contaminated set OUT."""
    spec = ingest.build(*ingest.load_raw(RAW_REAL))
    g = load(spec, graph_name="test_b10_real")
    for r in spec["retractions"]:
        distrust(g, r["source"], r["from"], r["to"], reason=r["reason"])
    out = {row[0] for row in g.query("MATCH (m:Mem {status:'OUT'}) RETURN m.id").result_set}
    assert out == set(spec["ground_truth"]["contaminated"])
