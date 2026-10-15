"""Extraction audit (bench/extraction_audit.py) on a tiny synthetic corpus: no network, no raw data needed."""
import json

import pytest

from bench import extraction_audit as ea

pytestmark = pytest.mark.bench

ABSTRACT = ["Cells were grown in culture.", "Treatment reduced growth by 40% in all lines.",
            "These results suggest a role in proliferation."]


def inverted(text):
    inv = {}
    for i, w in enumerate(text.split()):
        inv.setdefault(w, []).append(i)
    return inv


@pytest.fixture()
def corpus(tmp_path):
    raw = tmp_path / "raw"
    (raw / "openalex" / "retracted").mkdir(parents=True)
    (raw / "openalex" / "citing").mkdir(parents=True)
    (raw / "selection.json").write_text(json.dumps({"subject": "x", "papers": [{"openalex_id": "W1"}]}))
    w = {"id": "https://openalex.org/W1", "title": "A paper", "publication_date": "2020-05-01",
         "abstract_inverted_index": inverted(" ".join(ABSTRACT))}
    (raw / "openalex" / "retracted" / "W1.json").write_text(json.dumps(w))
    spec = {"observations": [
        {"id": "obs_W1_0", "source": "W1", "observed_at": "2020-05-01T00:00:00Z", "text": ABSTRACT[1]},
        {"id": "obs_W1_1", "source": "W1", "observed_at": "2020-05-01T00:00:00Z", "text": "Invented sentence."},
        {"id": "obs_W1_2", "source": "W1", "observed_at": "2019-01-01T00:00:00Z", "text": ABSTRACT[2]},
        {"id": "obs_W9_0", "source": "W9", "observed_at": "2020-05-01T00:00:00Z", "text": "not on disk"}]}
    return spec, raw


def test_checks_flag_invented_and_misdated_claims(corpus):
    spec, raw = corpus
    summary, rows = ea.audit(spec, raw, n=10)
    by = {r["id"]: r for r in rows}
    assert by["obs_W1_0"]["verbatim"] and by["obs_W1_0"]["attributed"] and by["obs_W1_0"]["cue"]
    assert not by["obs_W1_1"]["verbatim"]                 # not in the abstract at all
    assert by["obs_W1_2"]["verbatim"] and not by["obs_W1_2"]["attributed"]   # wrong publication date
    assert "obs_W9_0" not in by                           # no raw abstract: reported as coverage, not scored
    assert summary["auditable_claims"] == 3 and summary["total_claims"] == 4
    assert summary["coverage"] == 0.75
    assert summary["verbatim_precision"] == pytest.approx(2 / 3, abs=1e-3)


def test_sampling_is_seeded_and_markdown_renders(corpus):
    spec, raw = corpus
    a = ea.audit(spec, raw, n=2, seed=3)[1]
    b = ea.audit(spec, raw, n=2, seed=3)[1]
    assert [r["id"] for r in a] == [r["id"] for r in b]
    summary, rows = ea.audit(spec, raw, n=3)
    md = ea.markdown(summary, rows, {"reviewer": "t", "summary": {"n": 3, "finding": 1, "background": 1,
                                                                   "non_claim": 1, "truncated": 0,
                                                                   "substantive_assertion_rate": 0.67},
                                     "labels": {"obs_W1_0": {"label": "finding", "note": None}}})
    assert "reviewer label" in md and "finding" in md and "67%" in md
