"""The receipt: the correct payments a taint-everything rule would flag, itemised so the total can be checked.

    python -m bench.harness.receipt            # writes bench/results/receipt.json (and prints the total)

Runs Lane A's `coarse_taint` strategy on the precision scenario (several poisoned vendors, each with its own
window, many facts also confirmed by a trusted source) and lists every payment it flags although the
ground truth says it is still supported. RETCON flags none of them. The front page shows this as a receipt.
"""
import json
import os
import sys
from pathlib import Path

from bench.api import metrics
from bench.harness.loader import load_batched
from bench.harness.runner import _apply, discover_strategies
from bench.harness.scenarios import build
from core.db import connect

OUT = Path(__file__).resolve().parents[1] / "results" / "receipt.json"
TOP_PER_VENDOR = 3


def build_receipt(scenario_name="ap_prec_1k", strategy="coarse_taint", db=None):
    db = db or connect()
    sc = build(scenario_name)
    strategies = discover_strategies()
    tpl = load_batched(sc.spec, db=db, graph_name="receipt_tpl")
    try:
        fork = tpl.copy("receipt_run")
        try:
            out, _, _, _ = _apply(strategies[strategy], fork, sc.windows)
        finally:
            fork.delete()
        retcon_out = None
        fork = tpl.copy("receipt_run")
        try:
            retcon_out, _, _, _ = _apply(strategies["retcon"], fork, sc.windows)
        finally:
            fork.delete()
    finally:
        tpl.delete()
    m = metrics(sc.spec["ground_truth"], out, sc.spec["actions"])
    m_retcon = metrics(sc.spec["ground_truth"], retcon_out, sc.spec["actions"])
    wrong = set(m["wrongly_flagged_actions"]["ids"])
    names = {v["id"]: v["name"] for v in sc.spec["vendors"]}
    acts = [a for a in sc.spec["actions"] if a["id"] in wrong]
    groups = []
    for vid in sorted({a["vendor"] for a in acts}):
        mine = sorted((a for a in acts if a["vendor"] == vid), key=lambda a: -a["amount"])
        shown, rest = mine[:TOP_PER_VENDOR], mine[TOP_PER_VENDOR:]
        rows = [{"label": f"{a['invoice']} ({'paid' if a['executed'] else 'pending'})", "amount": a["amount"]} for a in shown]
        if rest:
            rows.append({"label": f"{len(rest)} smaller invoices", "amount": sum(a["amount"] for a in rest)})
        groups.append({"vendor": vid, "name": names[vid], "count": len(mine), "rows": rows,
                       "subtotal": sum(a["amount"] for a in mine)})
    total = sum(g["subtotal"] for g in groups)
    assert total == m["wrongly_flagged_actions"]["amount"], "receipt must add up to the metric"
    return {
        "scenario": scenario_name, "strategy": strategy, "nodes": sc.nodes,
        "poisoned_vendors": len(sc.windows), "profile": sc.spec["meta"].get("precision"),
        "count": len(acts), "executed": sum(1 for a in acts if a["executed"]),
        "executed_amount": sum(a["amount"] for a in acts if a["executed"]),
        "pending": sum(1 for a in acts if not a["executed"]),
        "total": total, "groups": groups,
        "collateral_loss": m["collateral_loss"], "action_precision": m["action_precision"],
        "retcon": {"count": m_retcon["wrongly_flagged_actions"]["count"], "collateral_loss": m_retcon["collateral_loss"],
                   "action_precision": m_retcon["action_precision"]},
    }


if __name__ == "__main__":
    os.environ.setdefault("RETCON_EMBEDDER", "hash")
    r = build_receipt()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(r, indent=1), encoding="utf8")
    print(f"wrote {OUT}: {r['count']} correct payments flagged by {r['strategy']}, total {r['total']:,} USD "
          f"({r['executed']} already paid = {r['executed_amount']:,}); RETCON flags {r['retcon']['count']}")
    sys.exit(0)
