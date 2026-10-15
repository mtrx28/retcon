"""Run the five strategies over scenarios and write the report (task A7 acceptance:
5 strategies x 2 scenarios).

    python -m bench.baselines.run [--scenarios ap_tiny,ap_1k,science] [--out bench/results/baselines.json]

This is the small runner A needs to produce the comparison table; Lane B's harness (scale runs,
latency percentiles, laundering probe, charts) consumes the same `bench.api` records and the same
results-file shape, so either can produce it.

Every (scenario, strategy) gets its own freshly loaded graph (ids equal fixture ids). Multi-window
scenarios (science) apply the windows in order on that graph and union the out sets.
"""
import argparse
import json
import os
import time
from pathlib import Path

from bench.api import STRATEGY_NAMES, metrics, record, windows
from bench.baselines import all_strategies
from data.load_fixture import load

ROOT = Path(__file__).resolve().parents[2]


def scenario(name):
    """-> (spec, meta). Names: ap_tiny, ap_<N>k (generated, seed 7), science, science_<N> (first N retractions)."""
    if name == "ap_tiny":
        spec = json.loads((ROOT / "data" / "fixtures" / "ap_tiny.json").read_text(encoding="utf8"))
        return spec, {"name": name, "domain": "ap", "seed": None}
    if name.startswith("ap_") and name.endswith("k"):
        from data.generator import generate, vendors_for_nodes
        nodes = int(name[3:-1]) * 1000
        spec = generate(seed=7, vendors=vendors_for_nodes(nodes, 2, 2))
        return spec, {"name": name, "domain": "ap", "seed": 7}
    if name.startswith("science"):
        spec = json.loads((ROOT / "data" / "fixtures" / "science.json").read_text(encoding="utf8"))
        if "_" in name:
            from agents.research.run import science_slice
            spec = science_slice(spec, int(name.split("_", 1)[1]))
        return spec, {"name": name, "domain": "science", "seed": None}
    raise ValueError(f"unknown scenario {name!r}")


def run_scenario(name, strategies=None, graph_prefix="bench"):
    spec, meta = scenario(name)
    n_nodes = len(spec["observations"]) + len({d["conclusion"]["id"] for d in spec["derivations"]}) \
        + len(spec["actions"])
    meta["nodes"] = n_nodes
    rows = []
    for sname, strat in (strategies or all_strategies()).items():
        g = load(spec, graph_name=f"{graph_prefix}_{name}_{sname}")
        out, engine, notes, err = set(), 0.0, {}, None
        t0 = time.perf_counter()
        try:
            for w in windows(spec):
                res = strat.retract(g, w)
                out |= set(res.out_ids)
                engine += res.engine_ms or 0.0
                notes = res.notes or notes
        except Exception as e:  # noqa: BLE001 - one strategy failing must not stop the table
            err = f"{type(e).__name__}: {e}"
        elapsed = (time.perf_counter() - t0) * 1000
        from bench.api import RetractionResult
        result = None if err else RetractionResult(out, engine_ms=engine or None, notes=notes)
        m = None if err else metrics(spec["ground_truth"], out, spec["actions"])
        rows.append(record(meta, sname, result, m, elapsed_ms=round(elapsed, 1), error=err))
    return rows


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


def markdown(rows):
    out = ["# RetconBench: retraction strategies", "",
           "Baselines are our reimplementations of the *behaviour* of each approach (no code from those "
           "projects). Lower is better for residual contamination and collateral loss; higher for action recall.", ""]
    for scen in dict.fromkeys(r["scenario"] for r in rows):
        sub = [r for r in rows if r["scenario"] == scen]
        out += [f"## {scen} ({sub[0]['domain']}, {sub[0]['nodes']} nodes)", "",
                "| strategy | residual contamination | collateral loss | action recall | action precision "
                "| blocked recall | out | ms |", "|---|---|---|---|---|---|---|---|"]
        for r in sub:
            m = r["metrics"] or {}
            out.append(f"| {r['strategy']} | {_pct(m.get('residual_contamination'))} | {_pct(m.get('collateral_loss'))} "
                       f"| {_pct(m.get('action_recall'))} | {_pct(m.get('action_precision'))} "
                       f"| {_pct(m.get('blocked_recall'))} | {r['out_count']} | {r['elapsed_ms']} |"
                       + (f" error: {r['error']}" if r["error"] else ""))
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenarios", default="ap_tiny,ap_1k,science")
    ap.add_argument("--out", default="bench/results/baselines.json")
    a = ap.parse_args()
    os.environ.setdefault("RETCON_EMBEDDER", "hash")
    rows = []
    for name in a.scenarios.split(","):
        print(f"running {name} ...", flush=True)
        rows += run_scenario(name.strip())
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2), encoding="utf8")
    md = markdown(rows)
    out.with_suffix(".md").write_text(md, encoding="utf8")
    print(md)


if __name__ == "__main__":
    main()


__all__ = ["scenario", "run_scenario", "markdown", "STRATEGY_NAMES"]
