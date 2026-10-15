"""B10: science scenario ingest. Retraction Watch + OpenAlex raw files -> fixture JSON (CONTRACT section 8, v1.1).

    python -m data.science.ingest [--raw data/science/raw] [--out data/fixtures/science.json]

Inputs (written by data/science/fetch_science_raw.py, gitignored):
    <raw>/selection.json                 {"subject", "papers": [{openalex_id, doi, retraction_date,
                                          original_date, rw_reason, rw_record_id}]}
    <raw>/openalex/retracted/<W>.json    OpenAlex work (abstract_inverted_index, publication_date, ...)
    <raw>/openalex/citing/<W>.json       works that cite a retracted paper
    <raw>/openalex/topic/<W>.json        same-topic, non-retracted works (independent evidence; step 4 of the fetch)

Mapping (all deterministic, no model calls, so a run is reproducible and free):
    paper                -> Source        trust from the venue type; `retracted_at` / `rw_reason` from the dataset
    claim sentence       -> Observation   observed_at = the paper's publication date (up to CLAIMS_PER_PAPER)
    per-paper claim      -> Belief        extract; a paper that cites a retracted paper in the corpus rests on
                                          it too (AND with that paper's claim): its finding is not independent
    topic claim          -> Belief        OR over the papers in one OpenAlex primary topic

Ground truth is computed by an independent in-memory JTMS (`jtms_labels`) from the retracted set:
a claim is contaminated iff every supporting path ends at a retracted paper (the plan's definition,
which is exactly "OUT under the JTMS rule").

Modelling assumption, stated plainly: citing a retracted paper is treated as *relying on it*. That is a
proxy, not a reading of the paper; it can only over-retract a citing paper's claim from the topic claim,
never keep a contaminated one. Retractions are described only through the dataset's own reason field.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from data.science import claims

CLAIMS_PER_PAPER = 2
OA_PREFIX = "https://openalex.org/"

VENUE_TRUST = {"journal": 0.85, "conference": 0.8, "book series": 0.7, "ebook platform": 0.7,
               "repository": 0.55, "preprint": 0.55, "other": 0.6}

_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
_CUE = re.compile(r"\b(show|shown|found|find|demonstrat|reveal|indicat|suggest|identif|result|conclude|"
                  r"requir|essential|promot|inhibit|increase|decrease|regulat|associat|enhanc|reduc|"
                  r"contribut|mediat|induc|impair|protect|critical|necessary)", re.I)


# ---- text helpers -----------------------------------------------------------------------------

def abstract_text(inverted):
    """OpenAlex stores abstracts as {word: [positions]}; rebuild the text."""
    if not inverted:
        return ""
    words = {}
    for w, positions in inverted.items():
        for p in positions:
            words[p] = w
    return " ".join(words[i] for i in sorted(words))


def split_sentences(text):
    """Sentences, with splits after an abbreviation ("vs.", "et al.") glued back onto what follows."""
    text = re.sub(r"([a-z]{3}[.!?])([A-Z][a-z])", lambda m: m.group(1) + " " + m.group(2), text)  # "diseases.When"
    parts = [s.strip() for s in _SENT.split(re.sub(r"\s+", " ", text).strip()) if s.strip()]
    out = []
    for part in parts:
        if out and claims._ABBREV_END.search(out[-1]):
            out[-1] = out[-1] + " " + part
        else:
            out.append(part)
    return out


def pick_claims(text, n=CLAIMS_PER_PAPER):
    """The n most result-like *claims*, in reading order. Sentences that are not claims (author lists,
    source lists, aims, methods, fragments; see data.science.claims) are dropped before ranking, and a
    leading section label ("RESULTS:") is stripped. Ties go to the earlier sentence."""
    scored = []
    for i, raw in enumerate(split_sentences(text)):
        if claims.reject_reason(raw) is not None:
            continue
        s, label = claims.clean(raw)
        words = len(s.split())
        score = (2 if _CUE.search(s) else 0) + (1 if 8 <= words <= 45 else 0)             + (2 if label in ("results", "result", "findings", "conclusion", "conclusions") else 0)
        scored.append((-score, i, s))
    best = sorted(scored)[:n]
    return [s for _, _, s in sorted(best, key=lambda t: t[1])]


def rw_date(s):
    """Retraction Watch dates look like '3/14/2017 0:00'. Returns ISO 8601 date or None."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def iso(date):
    return f"{date}T00:00:00Z"


def short_id(url):
    return (url or "").rsplit("/", 1)[-1]


def venue_trust(work):
    src = ((work.get("primary_location") or {}).get("source") or {})
    kind = (src.get("type") or "other").lower()
    return VENUE_TRUST.get(kind, VENUE_TRUST["other"]), kind


def topic_of(work):
    t = work.get("primary_topic") or {}
    if t.get("id"):
        return short_id(t["id"]), t.get("display_name") or short_id(t["id"])
    concepts = sorted(work.get("concepts") or [], key=lambda c: -(c.get("score") or 0))
    if concepts:
        return short_id(concepts[0].get("id")), concepts[0].get("display_name") or "topic"
    return None, None


def _clip(s, n=140):
    s = s.strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# ---- ground truth -----------------------------------------------------------------------------

def jtms_labels(spec, dead_observations):
    """(live_ids, dead_ids): least fixpoint of 'IN iff some justification has all premises IN'."""
    live = {o["id"] for o in spec["observations"] if o["id"] not in dead_observations}
    just = [(d["premises"], d["conclusion"]["id"]) for d in spec["derivations"]]
    everything = {o["id"] for o in spec["observations"]} | {c for _, c in just}
    changed = True
    while changed:
        changed = False
        for prem, concl in just:
            if concl not in live and all(p in live for p in prem):
                live.add(concl)
                changed = True
    return live, everything - live


# ---- build -------------------------------------------------------------------------------------

def load_raw(raw):
    raw = Path(raw)
    sel = json.loads((raw / "selection.json").read_text(encoding="utf8"))
    works = {}
    for kind in ("retracted", "citing", "topic"):
        d = raw / "openalex" / kind
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            w = json.loads(p.read_text(encoding="utf8"))
            works.setdefault(short_id(w.get("id")) or p.stem, w)   # retracted wins if a paper is in both
    return sel, works


def build(selection, works, claims_per_paper=CLAIMS_PER_PAPER):
    retracted = {p["openalex_id"]: p for p in selection["papers"] if p["openalex_id"] in works}
    ids = sorted(works)
    spec = {
        "tenant": "science", "domain": "science",
        "description": (f"Retracted papers ({selection.get('subject', 'unknown subject')}) from the Retraction Watch "
                        f"dataset and the works that cite them (OpenAlex). Retraction reasons are the dataset's own."),
        "sources": [], "agents": [{"id": "reader", "role": "reader"}, {"id": "synthesizer", "role": "synthesizer"},
                                  {"id": "intake", "role": "intake"}],
        "observations": [], "derivations": [], "actions": [],
        "retractions": [],
        "meta": {"subject": selection.get("subject"), "retracted": len(retracted), "papers": len(ids),
                 "claims_per_paper": claims_per_paper},
    }
    claims = {}                                   # paper id -> [observation ids]
    for wid in ids:
        w = works[wid]
        trust, vkind = venue_trust(w)
        src = {"id": wid, "kind": "pdf", "trust": trust, "title": _clip(w.get("title") or wid, 160),
               "venue_type": vkind, "doi": w.get("doi"), "publication_date": w.get("publication_date")}
        if wid in retracted:
            r = retracted[wid]
            src["retracted_at"] = rw_date(r.get("retraction_date"))
            src["rw_reason"] = (r.get("rw_reason") or "").strip().strip(";").strip()   # dataset ends lists with ";"
        spec["sources"].append(src)
        pub = w.get("publication_date") or "1970-01-01"
        sents = pick_claims(abstract_text(w.get("abstract_inverted_index")), claims_per_paper)
        claims[wid] = []
        for k, s in enumerate(sents):
            oid = f"obs_{wid}_{k}"
            spec["observations"].append({"id": oid, "source": wid, "observed_at": iso(pub), "text": s})
            claims[wid].append(oid)
    # citation structure restricted to the corpus
    cites = {}
    for wid in ids:
        refs = {short_id(r) for r in (works[wid].get("referenced_works") or [])}
        cites[wid] = sorted(r for r in refs if r in retracted and r != wid and claims.get(r))

    belief_of = {}                                # paper id -> per-paper claim belief id (first claim)
    for wid in ids:
        for k, oid in enumerate(claims[wid]):
            bid = f"claim_{wid}_{k}"
            prem = [oid]
            if k == 0:
                prem += [claims[r][0] for r in cites[wid]]    # relies on the retracted work(s) it cites
            text = next(o["text"] for o in spec["observations"] if o["id"] == oid)
            spec["derivations"].append({
                "id": f"d_{bid}", "rule": "combine" if len(prem) > 1 else "extract", "agent": "reader",
                "premises": prem, "conclusion": {"id": bid, "kind": "belief", "mtype": "semantic", "text": text}})
            if k == 0:
                belief_of[wid] = bid
    # topic-level synthesized claims: OR over the papers in the topic
    topics = {}
    for wid in ids:
        tid, tname = topic_of(works[wid])
        if tid and wid in belief_of:
            topics.setdefault(tid, {"name": tname, "papers": []})["papers"].append(wid)
    for tid in sorted(topics):
        t = topics[tid]
        if len(t["papers"]) < 2:
            continue                              # a one-paper topic is just that paper's claim
        first = min(t["papers"], key=lambda w: (works[w].get("publication_date") or "", w))
        first_claim = next(o["text"] for o in spec["observations"] if o["id"] == claims[first][0])
        sid = "topic_" + hashlib.sha1(tid.encode()).hexdigest()[:10]
        text = f"Literature position on {t['name']}: {_clip(first_claim, 160)}"
        for wid in sorted(t["papers"]):
            spec["derivations"].append({
                "id": f"d_{sid}_{wid}", "rule": "infer", "agent": "synthesizer", "premises": [belief_of[wid]],
                "conclusion": {"id": sid, "kind": "belief", "mtype": "semantic", "text": text}})
    # retractions in chronological order (the replay trigger for A10): one distrust per paper
    for wid, r in sorted(retracted.items(), key=lambda kv: (rw_date(kv[1].get("retraction_date")) or "9999", kv[0])):
        pub = works[wid].get("publication_date") or "1970-01-01"
        spec["retractions"].append({"source": wid, "retracted_at": rw_date(r.get("retraction_date")),
                                    "from": iso(pub), "to": f"{pub}T23:59:59Z",
                                    "reason": (r.get("rw_reason") or "").strip().strip(";").strip()})
    dead_obs = {o["id"] for o in spec["observations"] if o["source"] in retracted}
    live, dead = jtms_labels(spec, dead_obs)
    spec["ground_truth"] = {"contaminated": sorted(dead), "truly_supported": sorted(live)}
    return spec


def validate(spec):
    """Referential integrity + the B10 acceptance shape. Returns a list of problems."""
    bad = []
    sources = {s["id"] for s in spec["sources"]}
    obs = {o["id"] for o in spec["observations"]}
    concl = {d["conclusion"]["id"] for d in spec["derivations"]}
    known = obs | concl
    for o in spec["observations"]:
        if o["source"] not in sources:
            bad.append(f"{o['id']}: unknown source")
    for d in spec["derivations"]:
        bad += [f"{d['id']}: unknown premise {p}" for p in d["premises"] if p not in known]
    gt = spec["ground_truth"]
    labelled = set(gt["contaminated"]) | set(gt["truly_supported"])
    if labelled != known:
        bad.append(f"ground truth misses {sorted(known - labelled)[:3]} / invents {sorted(labelled - known)[:3]}")
    if set(gt["contaminated"]) & set(gt["truly_supported"]):
        bad.append("a node is both contaminated and truly supported")
    for s in spec["sources"]:
        if s.get("retracted_at") is None and "rw_reason" in s:
            bad.append(f"{s['id']}: rw_reason without a parsable retraction date")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--raw", default="data/science/raw")
    ap.add_argument("--out", default="data/fixtures/science.json")
    ap.add_argument("--claims-per-paper", type=int, default=CLAIMS_PER_PAPER)
    a = ap.parse_args()
    selection, works = load_raw(a.raw)
    spec = build(selection, works, a.claims_per_paper)
    problems = validate(spec)
    if problems:
        raise SystemExit("invalid science scenario:\n" + "\n".join(problems[:10]))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf8")
    gt = spec["ground_truth"]
    n_ret = sum(1 for s in spec["sources"] if s.get("retracted_at"))
    mem = len(spec["observations"]) + len({d["conclusion"]["id"] for d in spec["derivations"]})
    print(f"wrote {a.out}: {len(spec['sources'])} sources ({n_ret} retracted), {mem} Mem nodes, "
          f"{len(gt['contaminated'])} contaminated, {len(gt['truly_supported'])} truly supported")


if __name__ == "__main__":
    main()
