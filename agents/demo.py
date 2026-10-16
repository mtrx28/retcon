"""The seeded agent day, end to end, printed as a transcript (task B3).

    python -m agents.demo [--seed 7] [--transport local|mcp] [--no-retract]

Needs FalkorDB (python tasks.py up) and RETCON_EMBEDDER=hash for an offline run.
"""
import argparse
import os
import time

from agents.orchestrator import Orchestrator, build_world
from data.generator import generate


def run_day(seed=7, transport="local", retract=True, graph_name="b3_demo", brain=None, brains=None,
            pace=0.0, pause=0.0):
    """Ingest everything up to Oct 8, then (optionally) the operator distrusts the compromised portal
    and the agents receive the retraction events."""
    spec = generate(seed=seed, vendors=2, audit_incident=True)
    world = build_world(spec, graph_name=graph_name, transport=transport)
    orch = Orchestrator(world, brain=brain, brains=brains, pace=pace)
    orch.ingest_until("2026-10-08T23:59:59Z")
    out = {"spec": spec, "world": world, "orch": orch, "distrust": None, "events": []}
    if retract:
        if pause:
            time.sleep(pause)   # let the audience look at the graph before the retraction
        w = spec["window"]
        out["distrust"] = orch.distrust(w["source"], w["from"], w["to"])
        out["events"] = orch.dispatch_events(out["distrust"]["retraction_id"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--transport", default="local", choices=["local", "mcp"])
    ap.add_argument("--no-retract", action="store_true")
    ap.add_argument("--graph", default="b3_demo", help="graph name to build (the UI lists every graph)")
    ap.add_argument("--pace", type=float, default=0.0, help="seconds between agent tasks, so the UI visibly grows")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds to wait before the operator distrusts")
    ap.add_argument("--brain", default="rules", choices=["rules", "auto", "replay", "live"],
                    help="Payments agent: rules (default), live Gemini function calling (records a transcript), "
                         "replay the recorded transcript (no key), auto (replay, else live if a key is set, else rules)")
    ap.add_argument("--llm-cache", default=None, help="transcript directory (default data/llm_cache/payments)")
    ap.add_argument("--live", action="store_true", help="shorthand for --pace 0.5 --pause 8")
    a = ap.parse_args()
    if a.live:
        a.pace, a.pause = a.pace or 0.5, a.pause or 8.0
    os.environ.setdefault("RETCON_EMBEDDER", "hash")
    from agents.gemini import payments_brains
    r = run_day(a.seed, a.transport, not a.no_retract, graph_name=a.graph, pace=a.pace, pause=a.pause,
                brains=payments_brains(a.brain, a.llm_cache))
    print(r["world"].log.render(120))
    print()
    print("== agent results")
    for role, kind, summary in r["orch"].results:
        print(f"  {role:<9} {kind:<20} {summary}")
    if r["distrust"]:
        d = r["distrust"]
        print()
        print(f"== {d['retraction_id']}: flipped {d['flipped']}")
        print("   recall list:", [(x["action_id"], x["amount"]) for x in d["recall_list"]])
        print("   remediations:", [(x["kind"], x["status"]) for x in d["remediations"]])
    print()
    print("== bank payments:", [(p["invoice"], p["amount"], p["status"]) for p in r["world"].bank.payments])
    r["world"].close()


if __name__ == "__main__":
    main()
