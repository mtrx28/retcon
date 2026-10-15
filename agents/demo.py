"""The seeded agent day, end to end, printed as a transcript (task B3).

    python -m agents.demo [--seed 7] [--transport local|mcp] [--no-retract]

Needs FalkorDB (python tasks.py up) and RETCON_EMBEDDER=hash for an offline run.
"""
import argparse
import os

from agents.orchestrator import Orchestrator, build_world
from data.generator import generate


def run_day(seed=7, transport="local", retract=True, graph_name="b3_demo", brain=None, brains=None):
    """Ingest everything up to Oct 8, then (optionally) the operator distrusts the compromised portal
    and the agents receive the retraction events."""
    spec = generate(seed=seed, vendors=2, audit_incident=True)
    world = build_world(spec, graph_name=graph_name, transport=transport)
    orch = Orchestrator(world, brain=brain, brains=brains)
    orch.ingest_until("2026-10-08T23:59:59Z")
    out = {"spec": spec, "world": world, "orch": orch, "distrust": None, "events": []}
    if retract:
        w = spec["window"]
        out["distrust"] = orch.distrust(w["source"], w["from"], w["to"])
        out["events"] = orch.dispatch_events(out["distrust"]["retraction_id"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--transport", default="local", choices=["local", "mcp"])
    ap.add_argument("--no-retract", action="store_true")
    a = ap.parse_args()
    os.environ.setdefault("RETCON_EMBEDDER", "hash")
    r = run_day(a.seed, a.transport, not a.no_retract)
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
