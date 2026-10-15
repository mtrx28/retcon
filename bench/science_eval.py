"""Science evaluation (task A10): the research agents build memory from real abstracts, the real
retractions are replayed by their own dates, and the result is scored against ground truth.

    python -m bench.science_eval [--spec data/fixtures/science.json] [--retracted N] [--out FILE]

Ground truth comes from the fixture (a node is contaminated iff every support path ends at a
retracted paper). The agent-built graph has hashed ids, so truth is carried over by content: an
observation by (source, text), a belief by its text. Identical sentences from different papers are one
belief with several justifications (an OR), so such a belief is contaminated only if *all* the
fixture copies are. Scores use bench.api.metrics, the same definitions as the baselines.
"""
import argparse
import json
import os
import time
from collections import defaultdict
from pathlib import Path

from agents.research.run import ResearchRun, science_slice
from bench.api import metrics


def text_truth(spec):
    """{(kind, source_or_None, text): contaminated?} for every fixture node, copies collapsed (OR)."""
    gt = set(spec["ground_truth"]["contaminated"])
    group = defaultdict(list)
    for o in spec["observations"]:
        group[("observation", o["source"], o["text"])].append(o["id"])
    for d in spec["derivations"]:
        c = d["conclusion"]
        group[("belief", None, c["text"])].append(c["id"])
    return {k: all(i in gt for i in ids) for k, ids in group.items()}


def agent_nodes(g):
    """Every Mem node of the agent-built graph with its truth key and status."""
    rows = g.query(
        "MATCH (m:Mem) WHERE m:Observation OR m:Belief "
        "OPTIONAL MATCH (s:Source)-[:SUPPORTS]->(m) "
        "RETURN m.id, labels(m), m.text, s.id, m.status").result_set
    out = []
    for mid, labels, text, src, status in rows:
        key = ("observation", src, text) if "Observation" in labels else ("belief", None, text)
        out.append((mid, key, status))
    return out


def score(spec, g):
    truth = text_truth(spec)
    contaminated, supported, out, unknown = set(), set(), set(), 0
    for mid, key, status in agent_nodes(g):
        if key not in truth:
            unknown += 1                       # a node the fixture has no counterpart for
            continue
        (contaminated if truth[key] else supported).add(mid)
        if status == "OUT":
            out.add(mid)
    m = metrics({"contaminated": sorted(contaminated), "truly_supported": sorted(supported)}, out, [])
    m["unmapped_nodes"] = unknown
    m["disagreements"] = len(out ^ contaminated)
    return m


def evaluate(spec, n_retracted=None, graph_name="a10_science", review=True, ingest_limit=None):
    if n_retracted is not None:
        spec = science_slice(spec, n_retracted)
    run = ResearchRun(spec, graph_name=graph_name)
    try:
        t0 = time.perf_counter()
        tasks = run.ingest(limit=ingest_limit)
        ingest_s = time.perf_counter() - t0
        g = run.graph
        beliefs = g.query("MATCH (b:Belief) RETURN count(b)").result_set[0][0]
        topics = g.query("MATCH (b:Belief) WHERE b.text STARTS WITH 'Literature position on ' "
                         "RETURN count(b)").result_set[0][0]
        before = score(spec, g) if ingest_limit is None else None
        t1 = time.perf_counter()
        rows = run.retract_all(review=review)
        retract_s = time.perf_counter() - t1
        after = score(spec, g)
        final = dict(g.query("MATCH (b:Belief) WHERE b.text STARTS WITH 'Literature position on ' "
                             "RETURN b.status, count(b)").result_set)
        lat = sorted(r["latency_ms"] for r in rows if "latency_ms" in r)
        return {
            "domain": "science", "retracted_papers": len(spec["retractions"]),
            "papers": len(spec["sources"]), "tasks": tasks, "claims_synthesized": beliefs, "topic_claims": topics,
            "ingest_s": round(ingest_s, 1), "retract_s": round(retract_s, 1),
            "distrust_p50_ms": lat[len(lat) // 2] if lat else None,
            "distrust_p95_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
            "before_retraction": before, "after_retraction": after,
            "topics_final_in": final.get("IN", 0), "topics_final_out": final.get("OUT", 0),
            "topics_withdrawn": sum(r.get("topics_withdrawn") or 0 for r in rows),    # summed over retraction events
            "topics_that_stood": sum(r.get("topics_standing") or 0 for r in rows),
            "per_retraction": rows,
        }
    finally:
        run.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spec", default="data/fixtures/science.json")
    ap.add_argument("--retracted", type=int, help="use a slice with the first N retracted papers")
    ap.add_argument("--out", default="bench/results/science_agents.json")
    a = ap.parse_args()
    os.environ.setdefault("RETCON_EMBEDDER", "hash")
    spec = json.loads(Path(a.spec).read_text(encoding="utf8"))
    res = evaluate(spec, a.retracted)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=2), encoding="utf8")
    m = res["after_retraction"]
    print(f"science: {res['papers']} papers, {res['retracted_papers']} retracted, "
          f"{res['claims_synthesized']} claims ({res['topic_claims']} topic-level)")
    print(f"after replaying the retractions: residual contamination {m['residual_contamination']}, "
          f"collateral loss {m['collateral_loss']}, disagreements {m['disagreements']}")
    print(f"topic claims at the end: {res['topics_final_out']} withdrawn, {res['topics_final_in']} still stand on "
          f"independent papers; distrust p50 {res['distrust_p50_ms']} ms, p95 {res['distrust_p95_ms']} ms -> {a.out}")


if __name__ == "__main__":
    main()
