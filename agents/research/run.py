"""Replay a science scenario through the research agents, then retract the real retractions.

    run = ResearchRun(spec)            # spec: data/fixtures/science.json (contract v1.1, domain=science)
    run.ingest()                       # Reader / Synthesizer build memory paper by paper
    rows = run.retract_all()           # one distrust per retracted paper, by its own real dates

The spec is the *script*: abstract sentences are the documents, `derivations` say which papers a
claim relied on and which topic it supports. The agents write everything through the tools, so the
graph they build has hashed ids (not the fixture's), exactly like the AP run.
"""
import copy
from collections import defaultdict

from agents.orchestrator import Orchestrator, build_world
from agents.research import TOPIC_PREFIX, ResearchBrain


def science_slice(spec, n_retracted):
    """The first n retracted papers (in retraction order) plus every paper that cites one of them and
    every paper that supports a topic one of those papers supports. Ground truth is recomputed."""
    from data.science.ingest import jtms_labels
    ret = [r["source"] for r in spec["retractions"]][:n_retracted]
    obs_src = {o["id"]: o["source"] for o in spec["observations"]}
    keep = set(ret)
    topic_members = defaultdict(set)              # topic id -> papers
    claim_paper = {}
    for d in spec["derivations"]:
        cid = d["conclusion"]["id"]
        if cid.startswith("claim_"):
            claim_paper[cid] = obs_src[d["premises"][0]]
            if any(obs_src[p] in keep for p in d["premises"][1:]):     # cites a kept retracted paper
                keep.add(obs_src[d["premises"][0]])
    for d in spec["derivations"]:
        if d["conclusion"]["id"].startswith("topic_"):
            topic_members[d["conclusion"]["id"]].add(claim_paper[d["premises"][0]])
    for members in topic_members.values():
        if members & keep:
            keep |= members
    out = copy.deepcopy(spec)
    out["sources"] = [s for s in spec["sources"] if s["id"] in keep]
    out["observations"] = [o for o in spec["observations"] if o["source"] in keep]
    known = {o["id"] for o in out["observations"]}
    derivs = []
    for d in spec["derivations"]:                  # claims first (their premises are observations)
        if d["conclusion"]["id"].startswith("claim_") and d["premises"][0] in known:
            kept = [p for p in d["premises"] if p in known]   # a citation outside the slice is dropped
            derivs.append({**d, "premises": kept, "rule": "combine" if len(kept) > 1 else "extract"})
    known |= {d["conclusion"]["id"] for d in derivs}
    for d in spec["derivations"]:
        if d["conclusion"]["id"].startswith("topic_") and all(p in known for p in d["premises"]):
            derivs.append(d)
    out["derivations"] = derivs
    out["retractions"] = [r for r in spec["retractions"] if r["source"] in ret]
    dead = {o["id"] for o in out["observations"] if o["source"] in ret}
    live, gone = jtms_labels(out, dead)
    out["ground_truth"] = {"contaminated": sorted(gone), "truly_supported": sorted(live)}
    out["meta"] = {**spec.get("meta", {}), "slice_of": len(spec["retractions"]), "retracted": len(ret)}
    return out


def paper_tasks(spec):
    """One `read_paper` task per abstract sentence, cited papers first so a citing paper can recall
    the claim it relies on."""
    text = {o["id"]: o["text"] for o in spec["observations"]}
    topic_of_claim = {}
    for d in spec["derivations"]:
        if d["conclusion"]["id"].startswith("topic_"):
            topic_of_claim[d["premises"][0]] = d["conclusion"]["text"]
    claim_of_obs, cites = {}, defaultdict(list)
    for d in spec["derivations"]:
        if d["conclusion"]["id"].startswith("claim_"):
            own = d["premises"][0]
            claim_of_obs[own] = d["conclusion"]["id"]
            cites[own] = d["premises"][1:]
    obs_src = {o["id"]: o["source"] for o in spec["observations"]}
    cited_papers = {obs_src[c] for v in cites.values() for c in v}
    src = {s["id"]: s for s in spec["sources"]}
    by_paper = defaultdict(list)
    for o in spec["observations"]:
        by_paper[o["source"]].append(o)
    order = sorted(by_paper, key=lambda p: (p not in cited_papers, src[p].get("publication_date") or "", p))
    tasks = []
    for p in order:
        for k, o in enumerate(sorted(by_paper[p], key=lambda x: x["id"])):
            cid = claim_of_obs.get(o["id"])
            tasks.append({"type": "read_paper", "paper": p, "index": k, "source": p, "text": o["text"],
                          "observed_at": o["observed_at"],
                          "cited_texts": [text[c] for c in cites.get(o["id"], [])],
                          "topic_text": topic_of_claim.get(cid)})
    return tasks


class ResearchRun:
    def __init__(self, spec, graph_name="a10_science", transport="local"):
        self.spec = spec
        seed = copy.deepcopy(spec)
        seed.setdefault("vendors", [])                  # the AP sandbox services expect the key
        self.world = build_world(seed, graph_name=graph_name, transport=transport)
        brain = ResearchBrain()
        self.orch = Orchestrator(self.world, brains={"reader": brain, "synthesizer": brain})

    @property
    def graph(self):
        return self.world.graph

    def ingest(self, limit=None):
        n = 0
        for i, t in enumerate(paper_tasks(self.spec)):
            if limit is not None and i >= limit:
                break
            self.orch.run_task("reader", t)
            self.orch.drain()
            n += 1
        return n

    def _topic_nodes(self, ids):
        if not ids:
            return []
        rows = self.graph.query("MATCH (b:Belief) WHERE b.id IN $ids AND b.text STARTS WITH $p "
                                "RETURN b.id, b.text", {"ids": list(ids), "p": TOPIC_PREFIX}).result_set
        return [(r[0], r[1]) for r in rows]

    def retract_all(self, review=True):
        """One distrust per retracted paper, by that paper's own publication window, in the order the
        retractions happened. After each, the Synthesizer reviews the topics it holds that the
        retraction touched (flipped or kept alive) using `fragility`."""
        rows = []
        for r in self.spec["retractions"]:
            res = self.orch.distrust(r["source"], r["from"], r["to"])
            if "error" in res:
                rows.append({"source": r["source"], "error": res["error"]})
                continue
            touched = self._topic_nodes(set(res["flipped_ids"]) | set(res["survived_ids"]))
            standing = withdrawn = None
            if review and touched:
                step = self.orch.run_task("synthesizer", {"type": "review_topics",
                                                           "topic_texts": [t for _, t in touched]})
                standing, withdrawn = step.data["standing"], step.data["withdrawn"]
            rows.append({"source": r["source"], "retracted_at": r["retracted_at"], "reason": r["reason"],
                         "retraction_id": res["retraction_id"], "flipped": res["flipped"],
                         "survived": len(res["survived_ids"]), "latency_ms": res["latency_ms"],
                         "topics_withdrawn": None if withdrawn is None else len(withdrawn),
                         "topics_standing": None if standing is None else len(standing),
                         "min_independent_sources": (min((s["independent_sources"] or 0) for s in standing)
                                                     if standing else None)})
        return rows

    def close(self):
        self.world.close()
