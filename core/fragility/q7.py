"""Q7: fragility = poisoning cost (task B5).

"How many independent sources must be compromised before this belief falls?" The answer is the
size of the smallest set of Sources whose removal makes the node lose all support under the JTMS
rule (a justification is an AND of premises, a node is IN iff some justification is fully IN).
Examples on ap_tiny: the $41,250 payment = 1 (one portal claim is enough), the address belief = 2
(portal OR signed contract, both must fall).

Three numbers come out, from three levels of machinery:

  independent_sources   the answer. Exact: the smallest cut, found by evaluating the real JTMS
                        fixpoint with candidate source sets removed (<= EXACT_MAX_SOURCES live
                        sources under the node). Above that it falls back to an AND/OR
                        decomposition that returns a valid cut, hence an UPPER bound.
  bound                 "exact" | "upper", reported with the number (CONTRACT section 5).
  flow_upper_bound      FalkorDB `algo.maxFlow` over the FLOW projection (docs/SPIKE.md). Max-flow
                        treats every justification as an OR of premises, so it is exact for
                        single-premise chains and otherwise an upper bound (ap_tiny: 3 for the
                        payment, whose true cost is 1). It counts gates per observation, over the
                        whole graph including already-retracted evidence, so it measures
                        historical redundancy, not live robustness.

Cycles are handled by the least fixpoint: circular support never keeps a node alive.
"""
from itertools import combinations

from core.errors import RetconError
from core.retrieve.q2 import ancestry

EXACT_MAX_SOURCES = 16
EXACT_MAX_SUBSETS = 200_000


def _survives(target, base, justs, removed):
    """Is `target` IN when every observation of the `removed` sources is gone? Least fixpoint."""
    live = {o for o, (s, _) in base.items() if s not in removed}
    if target in live:
        return True
    changed = True
    while changed:
        changed = False
        for concl, prem in justs.values():
            if concl not in live and prem and all(p in live for p in prem):
                live.add(concl)
                changed = True
                if concl == target:
                    return True
    return target in live


def _exact(target, base, justs, sources):
    total = 0
    for k in range(1, len(sources) + 1):
        for n_combo, combo in enumerate(combinations(sources, k)):
            total += 1
            if total > EXACT_MAX_SUBSETS:
                return None
            if not _survives(target, base, justs, set(combo)):
                return list(combo)
    return list(sources)


def _dp_cut(target, base, justs):
    """Valid (not necessarily minimal) cut: kill every live justification via its cheapest premise."""
    by_concl = {}
    for concl, prem in justs.values():
        by_concl.setdefault(concl, []).append(prem)

    def cut(n, stack):
        if n in base:
            return frozenset({base[n][0]})
        if n in stack:
            return None
        parts = []
        for prem in by_concl.get(n, []):
            opts = [c for c in (cut(p, stack | {n}) for p in prem) if c is not None]
            if len(opts) == len(prem) and prem:  # every premise is groundable without n
                parts.append(min(opts, key=lambda s: (len(s), sorted(s))))
        return frozenset().union(*parts) if parts else None

    c = cut(target, frozenset())
    return sorted(c) if c is not None else None


def flow_upper_bound(g, node_id):
    """Engine max-flow from all Sources to the node over FLOW edges (see module docstring)."""
    r = g.query(
        "MATCH (s:Source) WITH collect(s) AS srcs MATCH (t:Mem {id:$id}) "
        "CALL algo.maxFlow({sourceNodes: srcs, targetNodes: [t], relationshipTypes: ['FLOW'], "
        "capacityProperty: 'cap'}) YIELD maxFlow RETURN maxFlow", {"id": node_id}).result_set
    return float(r[0][0]) if r else None


def fragility(g, node_id, with_flow=True):
    """Poisoning cost of `node_id`. Raises RetconError(NOT_FOUND) for an unknown id.

    Returns {node_id, status, independent_sources, bound, cut_set, live_sources, flow_upper_bound}.
    An OUT node has nothing left to poison: independent_sources 0.
    """
    status, base, justs = ancestry(g, node_id)
    if node_id not in status:
        raise RetconError("NOT_FOUND", f"unknown node {node_id!r}", {"node_id": node_id})
    out = {"node_id": node_id, "status": status[node_id], "flow_upper_bound": None}
    if with_flow:
        out["flow_upper_bound"] = flow_upper_bound(g, node_id)
    if status[node_id] != "IN":
        return {**out, "independent_sources": 0, "bound": "exact", "cut_set": [], "live_sources": []}

    # sources actually reachable under the node through live structure
    reach, stack = set(), [node_id]
    seen = set()
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        if n in base:
            reach.add(base[n][0])
        for concl, prem in justs.values():
            if concl == n:
                stack.extend(prem)
    sources = sorted(reach)

    cut = _exact(node_id, base, justs, sources) if len(sources) <= EXACT_MAX_SOURCES else None
    bound = "exact"
    if cut is None:
        cut, bound = _dp_cut(node_id, base, justs), "upper"
        if cut is None:  # inconsistent statuses; be conservative about robustness
            cut = []
    return {**out, "independent_sources": len(cut), "bound": bound, "cut_set": cut, "live_sources": sources}


def meets_independence(g, node_id, required=2):
    """Gate-policy hook (CONTRACT section 7): is the node backed by at least `required` independent
    sources? Returns {ok, independent_sources, required, bound, cut_set}; when not ok, the
    {independent_sources, required} pair is exactly the BLOCKED_BY_POLICY `details` payload.
    Note: with bound == "upper" the true cost can only be lower, so `ok` may be optimistic."""
    f = fragility(g, node_id, with_flow=False)
    return {"ok": f["independent_sources"] >= required, "independent_sources": f["independent_sources"],
            "required": required, "bound": f["bound"], "cut_set": f["cut_set"]}
