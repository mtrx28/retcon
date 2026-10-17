# RetconBench: retraction strategies

**How to read this.** RETCON implements the retraction semantics exactly: its result is checked against an independent reference JTMS on random graphs (property and differential tests), so 0% residual and 0% collateral is a *correctness* statement, not a free win; ground truth and RETCON share one definition on purpose. The interesting columns are the baselines': they either leave contamination behind (delete the source, vector similarity, one-hop invalidation) or wipe out honest data and payments (coarse taint). Lower is better for residual contamination, collateral loss and wrongly flagged actions; higher for action recall. The baselines are our reimplementations of each approach's *behaviour* (no code from those projects).

## ap_tiny (ap, 24 nodes)

| strategy | residual contamination | collateral loss | action recall | action precision | blocked recall | legitimate actions wrongly flagged | out | ms |
|---|---|---|---|---|---|---|---|---|
| delete_source | 82% | 0% | 0% | n/a | 0% | n/a | 2 | 4.7 |
| vector_only | 82% | 8% | 0% | n/a | 0% | n/a | 3 | 1117.4 |
| edge_invalidation | 64% | 8% | 0% | n/a | 0% | n/a | 5 | 1.7 |
| coarse_taint | 0% | 8% | 100% | 100% | 100% | n/a | 12 | 1.4 |
| retcon | 0% | 0% | 100% | 100% | 100% | n/a | 11 | 27.3 |

**ap_tiny, by layer** (residual contamination / collateral loss; n = contaminated / truly supported nodes in the layer)

| strategy | observation (n=2/7) | belief (n=5/6) | plan (n=2/0) | action (n=2/0) |
|---|---|---|---|---|
| delete_source | 0% / 0% | 100% / 0% | 100% / n/a | 100% / n/a |
| vector_only | 0% / 0% | 100% / 17% | 100% / n/a | 100% / n/a |
| edge_invalidation | 0% / 0% | 60% / 17% | 100% / n/a | 100% / n/a |
| coarse_taint | 0% / 0% | 0% / 17% | 0% / n/a | 0% / n/a |
| retcon | 0% / 0% | 0% / 0% | 0% / n/a | 0% / n/a |

## ap_1k (ap, 1024 nodes)

| strategy | residual contamination | collateral loss | action recall | action precision | blocked recall | legitimate actions wrongly flagged | out | ms |
|---|---|---|---|---|---|---|---|---|
| delete_source | 94% | 0% | 0% | n/a | 0% | 0 of 180 ($0) | 2 | 0.9 |
| vector_only | 94% | 0% | 0% | n/a | 0% | 0 of 180 ($0) | 4 | 46.6 |
| edge_invalidation | 87% | 0% | 0% | n/a | 0% | 0 of 180 ($0) | 5 | 1.4 |
| coarse_taint | 0% | 0% | 100% | 100% | 100% | 0 of 180 ($0) | 32 | 1.5 |
| retcon | 0% | 0% | 100% | 100% | 100% | 0 of 180 ($0) | 31 | 11.7 |

**ap_1k, by layer** (residual contamination / collateral loss; n = contaminated / truly supported nodes in the layer)

| strategy | observation (n=2/302) | belief (n=5/331) | plan (n=12/180) | action (n=12/180) |
|---|---|---|---|---|
| delete_source | 0% / 0% | 100% / 0% | 100% / 0% | 100% / 0% |
| vector_only | 0% / 0% | 100% / 0% | 100% / 0% | 100% / 0% |
| edge_invalidation | 0% / 0% | 60% / 0% | 100% / 0% | 100% / 0% |
| coarse_taint | 0% / 0% | 0% / 0% | 0% / 0% | 0% / 0% |
| retcon | 0% / 0% | 0% / 0% | 0% / 0% | 0% / 0% |

## ap_prec_1k (ap, 1025 nodes)

| strategy | residual contamination | collateral loss | action recall | action precision | blocked recall | legitimate actions wrongly flagged | out | ms |
|---|---|---|---|---|---|---|---|---|
| delete_source | 87% | 0% | 0% | n/a | 0% | 0 of 168 ($0) | 10 | 2.3 |
| vector_only | 84% | 0% | 0% | n/a | 0% | 0 of 168 ($0) | 15 | 234.3 |
| edge_invalidation | 75% | 1% | 0% | n/a | 0% | 0 of 168 ($0) | 25 | 5.4 |
| coarse_taint | 0% | 9% | 100% | 40% | 100% | 36 of 168 ($1,163,150) | 160 | 5.3 |
| retcon | 0% | 0% | 100% | 100% | 100% | 0 of 168 ($0) | 76 | 50.8 |

**ap_prec_1k, by layer** (residual contamination / collateral loss; n = contaminated / truly supported nodes in the layer)

| strategy | observation (n=10/295) | belief (n=18/318) | plan (n=24/168) | action (n=24/168) |
|---|---|---|---|---|
| delete_source | 0% / 0% | 100% / 0% | 100% / 0% | 100% / 0% |
| vector_only | 0% / 0% | 89% / 1% | 100% / 0% | 100% / 0% |
| edge_invalidation | 0% / 0% | 50% / 2% | 100% / 0% | 100% / 0% |
| coarse_taint | 0% / 0% | 0% / 4% | 0% / 21% | 0% / 21% |
| retcon | 0% / 0% | 0% / 0% | 0% / 0% | 0% / 0% |

## science (science, 2164 nodes)

| strategy | residual contamination | collateral loss | action recall | action precision | blocked recall | legitimate actions wrongly flagged | out | ms |
|---|---|---|---|---|---|---|---|---|
| delete_source | 84% | 0% | n/a | n/a | n/a | n/a | 80 | 21.9 |
| vector_only | 68% | 0% | n/a | n/a | n/a | n/a | 160 | 5702.2 |
| edge_invalidation | 7% | 0% | n/a | n/a | n/a | n/a | 464 | 45.4 |
| coarse_taint | 0% | 1% | n/a | n/a | n/a | n/a | 524 | 54.2 |
| retcon | 0% | 0% | n/a | n/a | n/a | n/a | 500 | 387.3 |

**science, by layer** (residual contamination / collateral loss; n = contaminated / truly supported nodes in the layer)

| strategy | observation (n=80/972) | claim (n=384/668) | topic (n=36/24) |
|---|---|---|---|
| delete_source | 0% / 0% | 100% / 0% | 100% / 0% |
| vector_only | 0% / 0% | 79% / 0% | 100% / 0% |
| edge_invalidation | 0% / 0% | 0% / 0% | 100% / 0% |
| coarse_taint | 0% / 0% | 0% / 0% | 0% / 100% |
| retcon | 0% / 0% | 0% / 0% | 0% / 0% |
