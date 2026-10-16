"""python -m bench.harness [--scenarios ap_tiny,ap_1k] [--repeats 5] [--launder] [--ablation] [--out FILE]

Runs every strategy that is present (Lane A's from bench/baselines, plus the stand-in `retcon`) over the
named scenarios and prints the results table. Needs FalkorDB (FALKORDB_PORT) and RETCON_EMBEDDER=hash
for an offline run.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from bench.harness.reference import with_reference
from bench.harness.runner import discover_strategies, run_matrix, table
from bench.harness.scenarios import build

RESULTS = Path(__file__).resolve().parents[1] / "results"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenarios", default="ap_tiny,ap_1k")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--launder", action="store_true", help="also run the laundering-depth probe")
    ap.add_argument("--ablation", action="store_true", help="also run the graph-off attacker experiment")
    ap.add_argument("--concurrency", action="store_true", help="also sweep 1/10/20/50 concurrent writers (B11)")
    ap.add_argument("--charts", metavar="DIR", help="write SVG charts here (default bench/results/charts when set to 'auto')")
    ap.add_argument("--out", default=str(RESULTS / "latest.json"))
    a = ap.parse_args(argv)
    os.environ.setdefault("RETCON_EMBEDDER", "hash")

    strategies = with_reference(discover_strategies())
    print(f"strategies: {', '.join(strategies)}", file=sys.stderr)
    scenarios = []
    for name in a.scenarios.split(","):
        try:
            scenarios.append(build(name.strip()))
        except FileNotFoundError as e:
            print(f"skip {name}: {e}", file=sys.stderr)
    t0 = time.time()
    rows = run_matrix(scenarios, strategies, a.repeats, out=a.out, progress=lambda s: print(s, file=sys.stderr))
    print(table(rows))
    extra = {}
    if a.launder:
        from bench.harness.laundering import laundering_curve
        c = laundering_curve(strategies)
        extra["laundering"] = {k: v for k, v in c.items() if k != "rows"}
        print("\nlaundering (residual contamination by restatement depth", c["depths"], ")")
        for s, vals in c["residual"].items():
            print(f"  {s:<19}" + "  ".join("  n/a" if v is None else f"{v * 100:5.1f}%" for v in vals))
    if a.ablation:
        from bench.harness.ablation import attacker_experiment, threshold_sweep
        extra["ablation"] = {"graph_on": attacker_experiment(False), "graph_off": attacker_experiment(True),
                             "sweep": threshold_sweep(vendors=6)}
        print("\ngraph-off ablation (attacker payments after the retraction):")
        for k in ("graph_on", "graph_off"):
            r = extra["ablation"][k]
            print(f"  {k:<10} paid attacker {r['paid_attacker_after_retraction']}x ({r['amount_to_attacker_after']} USD), "
                  f"retracted {r['contaminated_retracted']}/{r['contaminated_total']} contaminated, "
                  f"{r['clean_nodes_retracted']} clean lost")
    sweep_rows = None
    if a.concurrency:
        from bench.harness.concurrency import sweep
        ap = [sc for sc in scenarios if sc.domain == "ap"]   # the sweep needs a scenario with a window (not science)
        sweep_rows = sweep((ap[-1] if ap else build("ap_1k")).spec)
        extra["concurrency"] = sweep_rows
        print("\nconcurrency (writers: read p50/p95 ms | write p50/p95 ms | cascade ms | errors | stale in/out):")
        for r in sweep_rows:
            c = r["consistency"]
            print(f"  {r['writers']:>3}: {r['read_ms']['p50']}/{r['read_ms']['p95']} | {r['write_ms']['p50']}/"
                  f"{r['write_ms']['p95']} | {r['cascade']['ms'] if r['cascade'] else '-'} | "
                  f"{r['error_rate'] * 100:.1f}% | {c['stale_in']}/{c['stale_out']}")
    if a.charts:
        from bench.harness.charts import write_all
        d = str(RESULTS / "charts") if a.charts == "auto" else a.charts
        print(f"charts: {', '.join(write_all(rows, extra, sweep_rows, d))} -> {d}", file=sys.stderr)
    if extra:
        p = Path(a.out).with_suffix(".extra.json")
        p.write_text(json.dumps(extra, indent=1), encoding="utf8")
    print(f"\n{len(rows)} rows in {time.time() - t0:.1f}s -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
