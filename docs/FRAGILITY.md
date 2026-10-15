# Fragility (Q7): what the number means

**Poisoning cost** of a belief, plan or action = the size of the smallest set of *sources* that must be compromised (or distrusted) before it loses all support. Low cost means one bad source is enough. Computed by `core/fragility/q7.py`, exposed as the `fragility` MCP tool and as the gate hook `meets_independence`.

| Node on `ap_tiny` | Cost | Why |
|---|---|---|
| $41,250 payment (`act_pay_2`) | 1 | AND of the invoice, the PO and the bank-change claim: any one failing is enough |
| Address belief (`b_addr`) | 2 | OR of the portal claim and the signed contract: both must fall |
| Address belief after `distrust(coastal-portal)` | 1 | only the contract PDF is still live |

## How it is computed

1. Fetch the live structure under the node (justifications, premises, IN observations and their sources).
2. Find the smallest set of sources whose removal leaves the node unsupported, by evaluating the real JTMS fixpoint (a justification is an AND of premises; a node is IN iff some justification is fully IN) with candidate source sets removed, smallest first. This is **exact**, and circular support never counts as independent support.
3. With more than 16 live sources it falls back to an AND/OR decomposition that returns a valid cut. That number is an **upper bound** and the result says `bound: "upper"`.

## README caveat (draft for A8)

> `algo.maxFlow` over our FLOW projection treats every justification as an OR of its premises, so on its own it is exact for single-premise chains and an upper bound otherwise (on the demo graph it reports 3 for a payment whose true cost is 1). RETCON therefore reports the exact AND/OR-aware cost and returns the max-flow value separately as `flow_upper_bound`. Max-flow also counts retracted evidence, so it measures historical redundancy rather than live robustness.

## Gate policy

`pay` over $10,000 needs at least 2 independent sources (CONTRACT section 7). The hook returns `{ok, independent_sources, required, bound, cut_set}`. With `bound: "upper"` the real cost can only be lower, so `ok` may be optimistic.
