"""Laundering-resistance probe (task B7).

A claim restated by agent after agent drifts away from the text that was retracted. How well a strategy
still finds the laundered copies is its laundering resistance. The probe varies the number of restatement
hops between the compromised portal and the payment (`launder_depth`), holds everything else fixed, and
records residual contamination per strategy per depth. Expected shapes: delete-source flat and high,
edge-invalidation improving only at depth <= 1, similarity-based depending on wording, graph-based flat zero.

    curve = laundering_curve(strategies)   ->  {"depths": [...], "residual": {strategy: [value per depth]},
                                                "collateral": {...}, "rows": [...]}
"""
from bench.harness.runner import run_scenario
from bench.harness.scenarios import build

DEPTHS = (0, 1, 2, 4, 8)


def laundering_curve(strategies, depths=DEPTHS, seed=7, repeats=1, db=None, prefix="bench"):
    rows = []
    for d in depths:
        rows += run_scenario(build(f"ap_launder_d{d}", seed), strategies, repeats, db, prefix)
    residual, collateral = {}, {}
    for d_i, d in enumerate(depths):
        for r in rows:
            if r["scenario"] != f"ap_launder_d{d}" or r.get("error"):
                continue
            residual.setdefault(r["strategy"], [None] * len(depths))[d_i] = r["metrics"]["residual_contamination"]
            collateral.setdefault(r["strategy"], [None] * len(depths))[d_i] = r["metrics"]["collateral_loss"]
    return {"depths": list(depths), "residual": residual, "collateral": collateral, "rows": rows}
