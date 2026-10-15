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
import re
import time
from pathlib import Path

from bench.api import STRATEGY_NAMES, layers, metrics, metrics_by_layer, record, windows
from bench.baselines import all_strategies
from data.load_fixture import load

ROOT = Path(__file__).resolve().parents[2]


def scenario(name):
    """-> (spec, meta). Names: ap_tiny, ap_<N>k (generated, seed 7), science, science_<N> (first N retractions)."""
    if name == "ap_tiny":
        spec = json.loads((ROOT / "data" / "fixtures" / "ap_tiny.json").read_text(encoding="utf8"))
        return spec, {"name": name, "domain": "ap", "seed": None}
    if re.fullmatch(r"ap_\d+k", name):
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
    try:                                   # Lane B's scenarios: ap_prec_1k, ap_prec_10k, ap_10k, ...
        from bench.harness.scenarios import build
        sc = build(name)
    except KeyError:
        raise ValueError(f"unknown scenario {name!r}") from None
    return sc.spec, {"name": name, "domain": sc.domain, "seed": sc.seed}


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
        by_layer = None if err else metrics_by_layer(spec["ground_truth"], out, layers(spec))
        rows.append(record(meta, sname, result, m, elapsed_ms=round(elapsed, 1), error=err, by_layer=by_layer))
    return rows


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


def _wrong(m):
    w = (m or {}).get("wrongly_flagged_actions")
    if not w or not w.get("legit_total"):
        return "n/a"
    return f"{w['count']} of {w['legit_total']} (${w['amount']:,})"


FRAMING = (
    "**How to read this.** RETCON implements the retraction semantics exactly: its result is checked against an "
    "independent reference JTMS on random graphs (property and differential tests), so 0% residual and 0% "
    "collateral is a *correctness* statement, not a free win; ground truth and RETCON share one definition on "
    "purpose. The interesting columns are the baselines': they either leave contamination behind (delete the "
    "source, vector similarity, one-hop invalidation) or wipe out honest data and payments (coarse taint). "
    "Lower is better for residual contamination, collateral loss and wrongly flagged actions; higher for action "
    "recall. The baselines are our reimplementations of each approach's *behaviour* (no code from those "
    "projects).\n")


def markdown(rows):
    out = ["# RetconBench: retraction strategies", "", FRAMING]
    for scen in dict.fromkeys(r["scenario"] for r in rows):
        sub = [r for r in rows if r["scenario"] == scen]
        out += [f"## {scen} ({sub[0]['domain']}, {sub[0]['nodes']} nodes)", "",
                "| strategy | residual contamination | collateral loss | action recall | action precision "
                "| blocked recall | legitimate actions wrongly flagged | out | ms |", "|---|---|---|---|---|---|---|---|---|"]
        for r in sub:
            m = r["metrics"] or {}
            out.append(f"| {r['strategy']} | {_pct(m.get('residual_contamination'))} | {_pct(m.get('collateral_loss'))} "
                       f"| {_pct(m.get('action_recall'))} | {_pct(m.get('action_precision'))} "
                       f"| {_pct(m.get('blocked_recall'))} | {_wrong(m)} | {r['out_count']} | {r['elapsed_ms']} |"
                       + (f" error: {r['error']}" if r["error"] else ""))
        out.append("")
        lay = [r for r in sub if r.get("by_layer")]
        if lay:
            names = [n for n in ("observation", "claim", "topic", "belief", "plan", "action")
                     if n in lay[0]["by_layer"]]
            out += [f"**{scen}, by layer** (residual contamination / collateral loss; n = contaminated / "
                    "truly supported nodes in the layer)", "",
                    "| strategy | " + " | ".join(
                        f"{n} (n={lay[0]['by_layer'][n]['contaminated']}/{lay[0]['by_layer'][n]['truly_supported']})"
                        for n in names) + " |",
                    "|---|" + "---|" * len(names)]
            for r in lay:
                out.append(f"| {r['strategy']} | " + " | ".join(
                    f"{_pct(r['by_layer'][n]['residual_contamination'])} / {_pct(r['by_layer'][n]['collateral_loss'])}"
                    for n in names) + " |")
            out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenarios", default="ap_tiny,ap_1k,ap_prec_1k,science")
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
