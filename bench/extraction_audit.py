"""Audit of the science claim extraction (task A10 follow-up).

The Reader's claims are the abstract sentences B10's extractor picked (`data.science.ingest.pick_claims`:
a deterministic, cue-word ranking; no LLM). The benchmark measures RETCON's logic; this audit measures the
quality of the real-world input that logic is fed, so "0% / 0%" is not circular.

    python -m bench.extraction_audit [--n 50] [--seed 7] [--raw data/science/raw] [--out FILE]

Automatic checks on a seeded random sample of claims:
  verbatim     the claim is a sentence of the abstract (rebuilt from OpenAlex's inverted index) of the
               paper it is attributed to
  attributed   the observation's source is that paper and `observed_at` is its publication date
  cue          the sentence carries a result cue (the extractor's own ranking signal)
A table for human review is written next to the JSON (one row per claim, verdict column empty).
Only papers whose raw abstract is on this machine can be audited; the coverage is reported.
"""
import argparse
import json
import random
import re
from pathlib import Path

from data.science import ingest


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


_STOPWORDS = set("""a an and are as at be by for from in into is it of on or that the their this to using via with
without between during after before among within across than towards toward study studies analysis effect
effects role roles review new novel based""".split())


def _content_words(text):
    return {w for w in re.findall(r"[a-z0-9\-]{4,}", text.lower()) if w not in _STOPWORDS}


def title_mismatch(work) -> bool:
    """True when the title shares no content word with the abstract: OpenAlex occasionally returns another
    paper's abstract for an id, which a "verbatim in the abstract" check cannot see."""
    t = _content_words(work.get("title") or "")
    a = _content_words(ingest.abstract_text(work.get("abstract_inverted_index")))
    return len(t) >= 2 and len(a) >= 5 and not (t & a)


def audit(spec, raw, n=50, seed=7):
    sel, works = ingest.load_raw(raw)
    retracted = {p["openalex_id"] for p in sel["papers"]}
    auditable = [o for o in spec["observations"] if o["source"] in works]
    rnd = random.Random(seed)
    sample = rnd.sample(sorted(auditable, key=lambda o: o["id"]), min(n, len(auditable)))
    rows = []
    for o in sorted(sample, key=lambda o: o["id"]):
        w = works[o["source"]]
        abstract = ingest.abstract_text(w.get("abstract_inverted_index"))
        sents = ingest.split_sentences(abstract)
        norm = [_norm(s) for s in sents]
        pos = norm.index(_norm(o["text"])) if _norm(o["text"]) in norm else None
        rows.append({
            "id": o["id"], "paper": o["source"], "title": (w.get("title") or "")[:90],
            "retracted": o["source"] in retracted, "claim": o["text"],
            "verbatim": pos is not None or _norm(o["text"]) in _norm(abstract),
            "sentence_index": pos, "abstract_sentences": len(sents),
            "attributed": (o["observed_at"][:10] == (w.get("publication_date") or "")[:10]),
            "cue": bool(ingest._CUE.search(o["text"])),
            "words": len(o["text"].split()),
        })
    k = len(rows) or 1
    used = {o["source"] for o in spec["observations"]}
    suspect = sorted(p for p, w in works.items() if p in used and title_mismatch(w))
    summary = {
        "suspect_abstracts": len(suspect), "suspect_paper_ids": suspect,
        "papers_checked": len(used & set(works)),
        "sampled": len(rows), "auditable_claims": len(auditable), "total_claims": len(spec["observations"]),
        "coverage": round(len(auditable) / len(spec["observations"]), 3),
        "verbatim_precision": round(sum(r["verbatim"] for r in rows) / k, 3),
        "attribution_precision": round(sum(r["attributed"] for r in rows) / k, 3),
        "with_result_cue": round(sum(r["cue"] for r in rows) / k, 3),
        "from_retracted_papers": sum(r["retracted"] for r in rows),
        "median_words": sorted(r["words"] for r in rows)[len(rows) // 2] if rows else None,
        "seed": seed,
    }
    return summary, rows


def markdown(summary, rows, review=None):
    labels = (review or {}).get("labels", {})
    rsum = (review or {}).get("summary")
    out = ["# Extraction audit: science claims", "",
           f"Seeded random sample of {summary['sampled']} claims (seed {summary['seed']}) out of "
           f"{summary['auditable_claims']} whose abstract is available locally "
           f"({summary['coverage']:.0%} of all {summary['total_claims']}).", "",
           f"- verbatim in the attributed paper's abstract: **{summary['verbatim_precision']:.0%}**",
           f"- correctly attributed (paper id and publication date): **{summary['attribution_precision']:.0%}**",
           f"- carries a result cue word: **{summary['with_result_cue']:.0%}**; "
           f"median length {summary['median_words']} words; {summary['from_retracted_papers']} from retracted papers",
           ]
    if rsum:
        extra = []
        if rsum.get("source_error"):
            extra.append(f"{rsum['source_error']} claim from a paper whose abstract OpenAlex returned for a different "
                         "paper (a source-data error no text check can see)")
        if rsum.get("truncated"):
            extra.append(f"{rsum['truncated']} truncated sentence")
        out += ["", f"Read through by a model reviewer ({(review or {}).get('reviewer')}): of {rsum['n']} claims, "
                f"**{rsum['finding']} findings** (a result or conclusion the paper reports), **{rsum['background']} "
                f"background assertions** (a statement of prior knowledge) and **{rsum['non_claim']} non-claims** "
                f"(author names, source lists, aims, methods)"
                + (", plus " + "; ".join(extra) if extra else "") + ". "
                f"Substantive assertion rate **{rsum['substantive_assertion_rate']:.0%}**. A sample of 50 gives "
                "roughly +/- 10 points; this is not a human review.", ""]
        hist = (review or {}).get("history")
        if hist:
            out += ["How the non-claim rate moved as the filter was built (each row is a separate 50-claim sample "
                    "read by the same reviewer; only the held-out rows are unbiased):", "",
                    "| sample | non-claims | findings | note |", "|---|---|---|---|"]
            out += [f"| {h['sample']} | {h['non_claim_rate']:.0%} | {h['finding_rate']:.0%} | {h['note']} |"
                    for h in hist]
            out += [""]
    hum = (review or {}).get("human")
    if hum:
        out += [f"**Human review: {hum['reviewed']} of {rsum['n'] if rsum else 50} claims reviewed, "
                f"{hum['agreement_with_model']:.0%} agreement with the model reviewer; human non-claim rate "
                f"{hum['non_claim_rate']:.0%}, substantive assertions {hum['substantive_assertion_rate']:.0%}.**", ""]
        for d in hum["disagreements"]:
            out.append(f"- disagreement `{d['id']}`: model {d['model']}, human {d['human']}: {d['claim']}")
        out.append("")
    if summary.get("suspect_abstracts") is not None:
        out += [f"Title/abstract mismatch screen over the whole corpus: **{summary['suspect_abstracts']} of "
                f"{summary.get('papers_checked', '?')}** papers have an abstract "
                "sharing no content word with their title (OpenAlex occasionally returns another paper's abstract). "
                "Most are real mix-ups; a few are false positives (e.g. abbreviations). Not filtered automatically.",
                f"Papers: {', '.join(summary.get('suspect_paper_ids', []))}", ""]
    out += ["| # | paper | claim | verbatim | attributed | cue | reviewer label |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        claim = r["claim"].replace("|", "/")
        out.append(f"| {i} | {r['paper']}{' (retracted)' if r['retracted'] else ''}: {r['title'][:50]} | {claim} | "
                   f"{'yes' if r['verbatim'] else 'NO'} | {'yes' if r['attributed'] else 'NO'} | "
                   f"{'yes' if r['cue'] else 'no'} | "
                   f"{(labels.get(r['id']) or {}).get('label', '')}"
                   f"{' (' + labels[r['id']]['note'] + ')' if (labels.get(r['id']) or {}).get('note') else ''} |")
    return "\n".join(out) + "\n"


HUMAN_TEMPLATE_NOTE = ("Fill in `human_label` for each row: finding | background | non-claim | source-error. "
                       "Leave a row null if you did not review it. Then run: "
                       "python -m bench.extraction_audit --apply-human <this file>")


def human_template(rows, review):
    labels = (review or {}).get("labels", {})
    return {"instructions": HUMAN_TEMPLATE_NOTE,
            "rows": [{"id": r["id"], "paper": r["paper"], "title": r["title"], "claim": r["claim"],
                      "model_label": (labels.get(r["id"]) or {}).get("label"), "human_label": None, "note": None}
                     for r in rows]}


def apply_human(review, human):
    """Merge a human's labels into the review: agreement with the model reviewer, and the human's own rates."""
    got = {r["id"]: r for r in human["rows"] if r.get("human_label")}
    valid = {"finding", "background", "non-claim", "source-error"}
    bad = [r["id"] for r in got.values() if r["human_label"] not in valid]
    if bad:
        raise ValueError(f"unknown human_label for {bad[:3]}; use one of {sorted(valid)}")
    n = len(got)
    agree = sum(1 for r in got.values() if r["human_label"] == r.get("model_label"))
    rates = {k: sum(1 for r in got.values() if r["human_label"] == k) for k in valid}
    review = dict(review)
    review["human"] = {"reviewed": n, "agreement_with_model": round(agree / n, 3) if n else None,
                       "disagreements": [{"id": r["id"], "model": r.get("model_label"), "human": r["human_label"],
                                          "claim": r["claim"][:120]}
                                         for r in got.values() if r["human_label"] != r.get("model_label")],
                       "counts": rates,
                       "substantive_assertion_rate": round((rates["finding"] + rates["background"]) / n, 3) if n else None,
                       "non_claim_rate": round(rates["non-claim"] / n, 3) if n else None}
    return review


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spec", default="data/fixtures/science.json")
    ap.add_argument("--raw", default="data/science/raw")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="bench/results/extraction_audit.json")
    ap.add_argument("--apply-human", metavar="FILE", help="merge a human's labels (the _human.json template)")
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text(encoding="utf8"))
    out = Path(a.out)
    rev = out.with_name(out.stem + "_review.json")
    if a.apply_human:
        human = json.loads(Path(a.apply_human).read_text(encoding="utf8"))
        review = apply_human(json.loads(rev.read_text(encoding="utf8")), human)
        rev.write_text(json.dumps(review, indent=1), encoding="utf8")
        print(json.dumps(review["human"], indent=1))
        return
    summary, rows = audit(spec, a.raw, a.n, a.seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf8")
    review = json.loads(rev.read_text(encoding="utf8")) if rev.exists() else None
    out.with_name(out.stem + "_human.json").write_text(
        json.dumps(human_template(rows, review), indent=1, ensure_ascii=False), encoding="utf8")
    out.with_suffix(".md").write_text(markdown(summary, rows, review), encoding="utf8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
