"""Science claim filter (data/science/claims.py) against a hand-labelled corpus, plus the sentence
splitter it relies on. Pure Python, no database."""
import json
from pathlib import Path

import pytest

from data.science import claims, ingest

CASES = json.loads((Path(__file__).resolve().parents[1] / "data" / "claim_filter_cases.json")
                   .read_text(encoding="utf8"))["cases"]


def test_every_labelled_non_claim_is_rejected():
    missed = [c["text"][:90] for c in CASES if c["label"] == "non-claim" and claims.is_claim(c["text"])]
    assert missed == []


def test_findings_and_background_are_kept():
    """>= 98% of the claims a reviewer accepted survive the filter (recall of the filter on real text)."""
    good = [c for c in CASES if c["label"] in ("finding", "background")]
    kept = [c for c in good if claims.is_claim(c["text"])]
    assert len(good) >= 150
    assert len(kept) / len(good) >= 0.98, [c["text"][:80] for c in good if c not in kept]


def test_corpus_is_not_trivially_one_sided():
    labels = [c["label"] for c in CASES]
    assert labels.count("non-claim") >= 20 and labels.count("finding") >= 50 and labels.count("background") >= 50


@pytest.mark.parametrize("text,reason", [
    ("Knaus, William A.", "too_short"),
    ("Census, the Centers for Disease Control, the Health Care Financing Administration, and the American "
     "Hospital Association.", "author_list"),
    ("Department of Medicine, University of Somewhere, 12 Example Road, Cityville, Country.", "author_list"),
    ("The purpose of this investigation was to identify whether they have a prognostic signature.", "aim_framing"),
    ("METHODS: Twenty-four variables were identified as important factors in a disease activity index.",
     "section_label"),
    ("In this review, we describe common methods associated with gene methylation, including bisulfite "
     "sequencing.", "describes_itself"),
    ("Cells were incubated with the compound for 24 hours at 37 degrees before harvesting.", "methods"),
    ("Treatment reduced tumour growth by 40% compared with the control group and the effect was dose", "truncated"),
    ("PPARs, carcinogenesis, and control of the cell cycle IV.", "no_verb"),
])
def test_each_rule_fires_with_its_reason(text, reason):
    assert claims.reject_reason(text) == reason


@pytest.mark.parametrize("text", [
    "Here, we investigated the kinase involved and show that GSK-3beta is robustly activated in models of "
    "Parkinsonism.",
    "In this study, we found that the decreased miR-181a-5p expression plays a critical role in recovery.",
    "The present study shows that pre-exposure to chronic stress enhanced lung colonization by tumor cells.",
    "RESULTS: miR-130a-5p was diminished in NSCLC tissues and cells versus their counterparts.",
    "Osteoprotegerin (OPG) is a secreted protein that inhibits osteoclast formation.",
])
def test_findings_are_not_collateral(text):
    assert claims.is_claim(text), claims.reject_reason(text)


def test_labels_are_stripped_from_the_claim_text():
    assert claims.clean("RESULT(S): There was a delay of 6.7 years in diagnosis.")[0].startswith("There was")
    assert claims.clean("Result CD8 + T cells were positively correlated with prognosis.")[0].startswith("CD8")
    assert claims.clean("Abstract TNF-α mediates both protective and detrimental responses.")[0].startswith("TNF")
    # a sentence that merely begins with the word is left alone
    assert claims.clean("Results of the trial were published last year.")[1] is None


def test_splitter_keeps_abbreviations_and_glued_sentences_apart_correctly():
    sents = ingest.split_sentences(
        "Tumor control was increased (81.4% vs. 63.0%) in the combined group. It was well tolerated.")
    assert sents[0].endswith("63.0%) in the combined group.") and len(sents) == 2
    glued = ingest.split_sentences("This was found for many diseases.When scores are combined they stratify patients.")
    assert len(glued) == 2


def test_pick_claims_skips_non_claims_and_prefers_results():
    abstract = ("Knaus, William A. BACKGROUND: Cancer is a leading cause of death worldwide. "
                "METHODS: Cells were incubated for 24 hours. "
                "RESULTS: The compound reduced tumour volume by 40% in treated mice. "
                "The purpose of this study was to evaluate the compound. "
                "CONCLUSIONS: These data suggest the compound is a promising therapeutic candidate.")
    picked = ingest.pick_claims(abstract, n=2)
    assert picked == ["The compound reduced tumour volume by 40% in treated mice.",
                      "These data suggest the compound is a promising therapeutic candidate."]


HELDOUT = json.loads((Path(__file__).resolve().parents[1] / "data" / "claim_filter_heldout.json")
                     .read_text(encoding="utf8"))["cases"]


def test_heldout_sample_regression_guard():
    """A fresh 50-claim sample, labelled before any rule saw it. The filter must not let *more* of its
    non-claims through than when it was recorded (4 of 4 were missed then: procedure and document
    statements phrased in ways the rules do not know). Tune rules on tests/data/claim_filter_cases.json,
    not on this file; if the number improves, lower the bound and say why in the commit."""
    non = [c for c in HELDOUT if c["label"] == "non-claim"]
    leaked = [c for c in non if claims.is_claim(c["text"])]
    assert len(non) == 4 and len(leaked) <= 4
    good = [c for c in HELDOUT if c["label"] in ("finding", "background")]
    dropped = [c for c in good if not claims.is_claim(c["text"])]
    assert len(dropped) <= 1, [c["text"][:80] for c in dropped]
