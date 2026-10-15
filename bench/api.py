"""RetconBench interface (docs/CONTRACT.md, "v1.4 bench interface").

Lane A writes the strategies (`bench/baselines/`) and `metrics()`; Lane B writes the harness
(`bench/harness/`), scale runs, laundering probe, charts and the graph-off ablation. This module is
the whole seam: both sides import it, neither imports the other's package.

    result = strategy.retract(graph, window)          # -> RetractionResult
    m      = metrics(spec["ground_truth"], result.out_ids, spec["actions"])
    rec    = record(scenario, strategy.name, result, m)   # one JSON line per (scenario, strategy)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# Names are fixed so reports, charts and tests agree. Order = column order in tables.
STRATEGY_NAMES = ("delete_source", "vector_only", "edge_invalidation", "coarse_taint", "retcon")


@dataclass(frozen=True)
class Window:
    """Distrust window: observations of `source` with from <= observed_at <= to (inclusive).
    from/to are ISO 8601 strings, the same shape as `spec["window"]`."""
    source: str
    t_from: str
    t_to: str

    @classmethod
    def from_spec(cls, spec: dict) -> "Window":
        w = spec["window"]
        return cls(w["source"], w["from"], w["to"])


def windows(spec: dict) -> list[Window]:
    """The distrust windows of a scenario, in order. AP: the one `window`. Science: one per retracted
    paper (`retractions`, chronological). The harness calls `retract()` once per window on the SAME
    graph and takes the union of `out_ids`; for RETCON the last call already reports everything OUT."""
    if spec.get("retractions"):
        return [Window(r["source"], r["from"], r["to"]) for r in spec["retractions"]]
    if spec.get("windows"):                      # AP precision scenarios: one window per poisoned portal
        return [Window(w["source"], w["from"], w["to"]) for w in spec["windows"]]
    return [Window.from_spec(spec)]


@dataclass
class RetractionResult:
    """What a strategy believes is no longer usable after retracting the window.

    out_ids: ids of Mem nodes (observations, beliefs, plans, actions) that are NO LONGER retrievable
             by an agent. A strategy that never marks anything (e.g. a vector store that deletes
             chunks) reports the ids it deleted. Anything not in out_ids is, by definition, still
             served to agents.
    engine_ms: optional time the strategy itself measured (e.g. GRAPH.PROFILE). The harness always
             measures wall-clock around `retract()` separately.
    notes:   free-form, shown in reports (e.g. similarity threshold used).
    """
    out_ids: set[str]
    engine_ms: float | None = None
    notes: dict = field(default_factory=dict)


@runtime_checkable
class Strategy(Protocol):
    name: str  # one of STRATEGY_NAMES

    def retract(self, graph, window: Window) -> RetractionResult:
        """Retract `window` on `graph`. The harness gives every call its own freshly loaded copy of
        the scenario (data.load_fixture.load), so a strategy may mutate it freely. Must be
        deterministic (no unseeded randomness) and must not print or read files outside the graph."""

    # Optional, used by the laundering-resistance metric (Lane B). Number of independent
    # corroborations the strategy would report for `node_id` in the given (un-retracted) graph.
    # Strategies without a notion of support may omit it; the harness then skips that column.
    # def support_count(self, graph, node_id: str) -> int: ...


def _ratio(num: int, den: int):
    return None if den == 0 else num / den


def metrics(ground_truth: dict, out_ids, actions: list[dict] | None = None) -> dict:
    """The comparable numbers. All ratios are in [0, 1] or None when the denominator is empty.

    residual_contamination  share of truly contaminated nodes still retrievable   (lower is better)
    collateral_loss         share of truly supported nodes wrongly made OUT        (lower is better)
    action_recall           share of contaminated EXECUTED actions flagged for recall (higher is better)
    action_precision        share of flagged executed actions that really were contaminated (higher)
    blocked_recall          share of contaminated PENDING actions that were blocked (higher is better)
    wrongly_flagged_actions legitimate actions the strategy flagged anyway: {count, executed, pending,
                            amount, executed_amount, rate, ids}. Wrongly recalled / blocked payments are the
                            business cost of imprecision (lower is better; needs `actions`)
    """
    out = set(out_ids)
    contaminated = set(ground_truth["contaminated"])
    supported = set(ground_truth["truly_supported"])
    by_id = {a["id"]: a for a in (actions or [])}

    if "recall_list" in ground_truth:
        exe_bad = set(ground_truth["recall_list"])
    else:
        exe_bad = {i for i in contaminated if by_id.get(i, {}).get("executed")}
    if "blocked" in ground_truth:
        pend_bad = set(ground_truth["blocked"])
    else:
        pend_bad = {i for i in contaminated if i in by_id and not by_id[i].get("executed")}
    exe_all = {i for i, a in by_id.items() if a.get("executed")}
    flagged_exe = out & exe_all
    legit = {i for i in by_id if i not in contaminated}          # actions that were fine to keep
    wrong = sorted(i for i in legit if i in out)
    amt = lambda ids: sum(by_id[i].get("amount") or 0 for i in ids)  # noqa: E731
    wrong_exe = [i for i in wrong if by_id[i].get("executed")]

    return {
        "residual_contamination": _ratio(len(contaminated - out), len(contaminated)),
        "collateral_loss": _ratio(len(supported & out), len(supported)),
        "action_recall": _ratio(len(exe_bad & out), len(exe_bad)),
        "action_precision": _ratio(len(flagged_exe & exe_bad), len(flagged_exe)),
        "blocked_recall": _ratio(len(pend_bad & out), len(pend_bad)),
        "wrongly_flagged_actions": {
            "count": len(wrong), "executed": len(wrong_exe), "pending": len(wrong) - len(wrong_exe),
            "amount": amt(wrong), "executed_amount": amt(wrong_exe),
            "rate": _ratio(len(wrong), len(legit)), "legit_total": len(legit), "ids": wrong},
        "counts": {"contaminated": len(contaminated), "truly_supported": len(supported),
                   "out": len(out), "executed_contaminated": len(exe_bad),
                   "pending_contaminated": len(pend_bad)},
    }


def layers(spec: dict) -> dict[str, str]:
    """Node id -> layer name, for breaking a score down by kind of memory.
    observation | belief | plan | action; science splits beliefs into claim (one paper) and topic
    (a synthesized position over several papers, an OR of justifications)."""
    out = {o["id"]: "observation" for o in spec["observations"]}
    for d in spec["derivations"]:
        c = d["conclusion"]
        kind = "plan" if c.get("kind") == "plan" else "belief"
        if kind == "belief" and spec.get("domain") == "science":
            kind = "topic" if c["id"].startswith("topic_") else "claim"
        out[c["id"]] = kind
    for a in spec["actions"]:
        out[a["id"]] = "action"
    return out


def metrics_by_layer(ground_truth: dict, out_ids, layer_of: dict[str, str]) -> dict:
    """{layer: {contaminated, truly_supported, out, residual_contamination, collateral_loss}}.
    Same definitions as `metrics`, restricted to the nodes of one layer."""
    out = set(out_ids)
    res = {}
    for layer in sorted(set(layer_of.values())):
        c = {i for i in ground_truth["contaminated"] if layer_of.get(i) == layer}
        t = {i for i in ground_truth["truly_supported"] if layer_of.get(i) == layer}
        o = {i for i in out if layer_of.get(i) == layer}
        res[layer] = {"contaminated": len(c), "truly_supported": len(t), "out": len(o),
                      "residual_contamination": _ratio(len(c - o), len(c)),
                      "collateral_loss": _ratio(len(t & o), len(t)),
                      "collateral_nodes": len(t & o)}
    return res


def record(scenario: dict, strategy: str, result: RetractionResult | None, m: dict | None,
           elapsed_ms: float | None = None, error: str | None = None, by_layer: dict | None = None) -> dict:
    """One row of a results file (a JSON list of these). `scenario` = {name, domain, nodes, seed}."""
    return {
        "scenario": scenario["name"], "domain": scenario.get("domain", "ap"),
        "nodes": scenario.get("nodes"), "seed": scenario.get("seed"),
        "strategy": strategy,
        "out_count": None if result is None else len(result.out_ids),
        "metrics": m, "by_layer": by_layer, "elapsed_ms": elapsed_ms,
        "engine_ms": None if result is None else result.engine_ms,
        "notes": {} if result is None else result.notes, "error": error,
    }
