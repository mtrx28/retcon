# RetconBench: retraction strategies

Baselines are our reimplementations of the *behaviour* of each approach (no code from those projects). Lower is better for residual contamination and collateral loss; higher for action recall.

## ap_1k (ap, 1008 nodes)

| strategy | residual contamination | collateral loss | action recall | action precision | blocked recall | out | ms |
|---|---|---|---|---|---|---|---|
| delete_source | 82% | 0% | 0% | n/a | 0% | 2 | 1.1 |
| vector_only | 82% | 0% | 0% | n/a | 0% | 3 | 300.5 |
| edge_invalidation | 64% | 0% | 0% | n/a | 0% | 5 | 1.5 |
| coarse_taint | 0% | 0% | 100% | 100% | 100% | 12 | 2.5 |
| retcon | 0% | 0% | 100% | 100% | 100% | 11 | 69.3 |

## science (science, 2192 nodes)

| strategy | residual contamination | collateral loss | action recall | action precision | blocked recall | out | ms |
|---|---|---|---|---|---|---|---|
| delete_source | 84% | 0% | n/a | n/a | n/a | 80 | 27.6 |
| vector_only | 68% | 0% | n/a | n/a | n/a | 160 | 9367.9 |
| edge_invalidation | 7% | 0% | n/a | n/a | n/a | 465 | 58.9 |
| coarse_taint | 0% | 1% | n/a | n/a | n/a | 525 | 56.5 |
| retcon | 0% | 0% | n/a | n/a | n/a | 501 | 2388.3 |
