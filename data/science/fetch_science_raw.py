"""
Step 0.7 - background data pull for the science scenario (no LLM calls).

Usage:
  1) git clone https://gitlab.com/crossref/retraction-watch-data data/science/raw/rw
  2) python data/science/fetch_science_raw.py --list-subjects
       -> prints subjects with the most retractions that have a DOI
  3) python data/science/fetch_science_raw.py --subject "<exact subject string>" --max-retracted 40
       -> saves OpenAlex JSON for retracted papers + papers that cite them

Output (all gitignored):
  data/science/raw/openalex/retracted/<openalex_id>.json
  data/science/raw/openalex/citing/<openalex_id>.json
  data/science/raw/selection.json   (which RW records we picked, with reason + dates)

Set OPENALEX_MAILTO=you@example.com so requests go to OpenAlex's polite pool.
If OpenAlex rate-limits or asks for an API key, check https://docs.openalex.org and adjust.
"""
import argparse
import csv
import glob
import json
import os
import sys
import time
from collections import Counter

import requests

RAW = "data/science/raw"
OA = "https://api.openalex.org"
MAILTO = os.environ.get("OPENALEX_MAILTO", "")


def rw_csv_path():
    # The repo's CSV filename can change; take the first CSV we find.
    hits = glob.glob(f"{RAW}/rw/**/*.csv", recursive=True)
    if not hits:
        sys.exit("No CSV found. Clone the Retraction Watch repo into data/science/raw/rw first.")
    return hits[0]


def load_retractions():
    rows = []
    with open(rw_csv_path(), newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        print("CSV columns:", reader.fieldnames)  # check names match below
        for r in reader:
            nature = (r.get("RetractionNature") or "").strip()
            doi = (r.get("OriginalPaperDOI") or "").strip()
            if nature == "Retraction" and doi and doi.lower() not in ("unavailable", "0"):
                rows.append(r)
    return rows


def oa_get(path, params=None):
    params = dict(params or {})
    if MAILTO:
        params["mailto"] = MAILTO
    for attempt in range(5):
        resp = requests.get(f"{OA}{path}", params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            return None
        time.sleep(2 ** attempt)  # back off on 429 / 5xx
    return None


def save(obj, folder, name):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(obj, f)


def list_subjects(rows, top=30):
    c = Counter()
    for r in rows:
        for s in (r.get("Subject") or "").split(";"):
            s = s.strip()
            if s:
                c[s] += 1
    for subject, n in c.most_common(top):
        print(f"{n:6d}  {subject}")


def fetch(rows, subject, max_retracted, citing_per_paper):
    picked = [r for r in rows if subject in (r.get("Subject") or "")]
    print(f"{len(picked)} retractions with DOI in subject; fetching up to {max_retracted} that have abstracts")
    selection, kept = [], 0
    for r in picked:
        if kept >= max_retracted:
            break
        doi = r["OriginalPaperDOI"].strip()
        work = oa_get(f"/works/doi:{doi}")
        if not work or not work.get("abstract_inverted_index"):
            continue  # we need an abstract to extract claims
        wid = work["id"].rsplit("/", 1)[-1]
        save(work, f"{RAW}/openalex/retracted", wid)
        selection.append({
            "openalex_id": wid,
            "doi": doi,
            "rw_record_id": r.get("Record ID"),
            "retraction_date": r.get("RetractionDate"),
            "original_date": r.get("OriginalPaperDate"),
            "rw_reason": r.get("Reason"),
        })
        kept += 1
        # Papers that cite this retracted paper (the "laundering" layer).
        citing = oa_get("/works", {"filter": f"cites:{wid},has_abstract:true", "per-page": citing_per_paper})
        for c in (citing or {}).get("results", []):
            save(c, f"{RAW}/openalex/citing", c["id"].rsplit("/", 1)[-1])
        time.sleep(0.2)
    save({"subject": subject, "papers": selection}, RAW, "selection")
    print(f"Saved {kept} retracted papers and their citing works under {RAW}/openalex/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-subjects", action="store_true")
    ap.add_argument("--subject")
    ap.add_argument("--max-retracted", type=int, default=40)
    ap.add_argument("--citing-per-paper", type=int, default=10)
    a = ap.parse_args()
    rows = load_retractions()
    print(f"{len(rows)} retractions with a DOI")
    if a.list_subjects:
        list_subjects(rows)
    elif a.subject:
        fetch(rows, a.subject, a.max_retracted, a.citing_per_paper)
    else:
        ap.print_help()
