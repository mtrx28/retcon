# How to present the benchmark (README, blog, video)

Numbers are from `bench/results/baselines.md` (regenerate: `python -m bench.baselines.run`, or the full
harness `python tasks.py bench ...`). Baselines are our reimplementations of each approach's *behaviour*.

## 1. What the 0% / 0% means (and does not)

Say this, in this order:

1. **RETCON implements the retraction semantics exactly.** Its output is checked against an independent
   reference JTMS (least fixpoint, written separately, no cascade) on thousands of random graphs and operation
   sequences, plus a differential test. That is a correctness statement, not a benchmark win.
2. **Ground truth and RETCON share one definition on purpose:** a node is contaminated iff every support path
   ends at a distrusted source. The benchmark therefore cannot show RETCON being "better than the truth".
   What it shows is how far each *other* approach is from that definition, and what that costs.
3. **"Contaminated" means "rests only on a retracted source", not "is false".** A retracted paper's background
   sentence may be perfectly true. RETCON removes what depends on a source you no longer trust and keeps what
   has independent support; whether the claim is *true* is outside the model.

Do **not** present "RETCON scores 100%" as the headline. Lead with the baselines' failures and the cost.

## 2. The claims the data supports

| Claim | Evidence (where) |
|---|---|
| Delete-source, vector similarity and one-hop invalidation leave most contamination behind | AP: 82 / 82 / 64% residual (`ap_1k`); 87 / 84 / 75% (`ap_prec_1k`). Science: 84 / 68% for delete-source / vector; **one-hop invalidation 7% overall but 100% of the synthesized topic claims** |
| Their executed payments are never recalled | action recall 0% for all three, both AP scenarios |
| Coarse taint (wipe everything downstream) catches everything but destroys honest work | `ap_prec_1k`: **36 of 168 legitimate payments wrongly flagged ($1,163,150)**, precision 40% (60% of what it recalls is fine); RETCON 0 of 168 |
| ... and the loss is concentrated where the memory is *synthesized* | science, by layer: coarse taint loses **24 of 24 independently supported topic claims (100%)**, and 0 elsewhere. The overall 1% hides it |
| RETCON keeps what has a second source | topic layer: 0% collateral where coarse taint has 100%; plan/action layer 0% where coarse taint has 21% |

## 3. What not to claim (these are in the data)

- **On the plain AP scenario coarse taint ties RETCON** (`ap_1k`: 0% / 0% / 100% for both, 0 legitimate
  payments wrongly flagged). That scenario has one poisoned vendor and almost nothing corroborated. The
  difference only appears when legitimate payments have independent support, which is what the precision
  scenario (`ap_prec_*`) constructs. Say so; do not hide the plain row.
- **In real literature most claims rest on a single paper**, so retraction usually *should* remove them.
  Science overall collateral for coarse taint is 1% (24 of 1,691 supported nodes). RETCON's advantage there is
  that the synthesized, multi-paper positions are handled correctly (see above) and that every removal is
  explainable (`why`), reversible (`reinstate`) and previewable, not that it removes less.
- **RETCON is not faster than the naive rules.** Coarse taint: 1-6 ms; RETCON: 19-55 ms per scenario, ~14 ms
  per retraction on science (550 ms for all 40) because it re-derives. It is interactive, and the extra cost
  buys the precision. Do not put "fast" next to RETCON in a comparison with the baselines; "milliseconds" is
  accurate on its own.
- **The precision scenarios are constructed** (staggered windows, a stated share of facts also confirmed by a
  trusted source). They test a capability, they do not estimate how common it is in the wild.

## 4. Input quality (extraction audit)

The science claims are abstract sentences chosen by a deterministic extractor (`data/science/ingest.py` +
`data/science/claims.py`; **no LLM**). It ranks sentences by result cue words, after a filter drops what is not a
claim: author and affiliation lists, source lists, fragments and truncated sentences, aims ("this study
aims..."), methods ("cells were incubated..."), and descriptions of the document itself ("in this review we
describe..."). `bench/extraction_audit.py` samples claims from the 1,052 whose abstract is on disk.

- Every sampled claim appears verbatim in the attributed paper's abstract and carries that paper's id and
  publication date (100%, by construction; it is a regression check, not evidence of quality).
- **Quality**, read by a model reviewer (`bench/results/extraction_audit.md`; a human pass is still pending):
  on a fresh 50-claim sample the final rules had not been tuned on, **8% were non-claims** (4 of 50; roughly
  2-19% at this sample size), **32% findings** a paper reports, **60% background assertions**. Before the
  filter, 18% were non-claims. Earlier held-out samples read 6% and 18% as the rules were being built (the 18%
  exposed procedure statements, which then got their own rules), so treat the figure as "about one in ten".
- **Source-data errors:** OpenAlex sometimes returns another paper's abstract for an id (e.g. a paper titled
  "What's wrong with Bonferroni adjustments" carries an abstract about MyD88). A title-vs-abstract screen flags
  5 of 529 papers (about 1%; one is a retracted paper, a couple are false positives). They are reported, not
  removed.
- Filter effect on the benchmark: 2,192 -> 2,164 nodes; every percentage in section 2 is unchanged.

What this means: the retraction logic is fed real, correctly attributed sentences, but only about a third are
findings the paper reports and about one in ten is still not a claim. The dependency structure (which claim
rests on which paper) is real; the *content* of a claim node is a sentence, not a verified proposition. Say
"claims", not "facts". If a demo graph is clicked, expect an occasional method description.

## 5. Lines for the video (3 minutes, v2 script)

- 2:35, benchmark slide: "Delete the source and you keep 80 to 90 percent of the poison. Wipe everything
  downstream and you freeze a million dollars of honest payments. RETCON keeps exactly what has a second
  source."
- Same slide, caption: "RETCON's retraction is checked against an independent reference on random graphs."
- Do not say "100%", "perfect" or "fastest".

## 6. README text (drop-in)

> **Benchmark.** RetconBench compares five retraction strategies on synthetic accounts-payable scenarios and on
> 40 real retractions from Retraction Watch. RETCON implements the retraction semantics exactly (verified
> against a reference JTMS on random graphs), so we report what the *alternatives* cost: delete-source, vector
> similarity and one-hop invalidation leave 64-87% of contaminated memory in service and recall none of the
> payments made on it; wiping everything downstream catches it all but wrongly freezes 36 of 168 legitimate
> payments ($1.16M) in the precision scenario, and in the science corpus loses all 24 independently supported
> synthesized topics. On a scenario with one poisoned vendor and nothing corroborated, wiping everything
> ties RETCON, and we show that row too. RETCON is slower than the naive rules (about 14 ms per retraction) but
> interactive. Baselines are our reimplementations; ground truth is "rests only on a retracted source", not
> "is false".
