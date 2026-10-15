# SPIKE: FalkorDB syntax verified on the live engine

Engine: `falkordb/falkordb:latest`, graph module `ver 60002`. Probe script: `scripts/spike.py` (`python tasks.py spike`). All probes pass. Tiny graph: 2 sources, 2 observations, 2 beliefs; `b1` has independent support from both sources, `b2` only from the portal.

## Verified

| Capability | Working syntax / finding |
|---|---|
| Q3 distrust in window | `MATCH (s:Source {id:$s})-[:SUPPORTS]->(o:Observation) WHERE o.observed_at >= $f AND o.observed_at <= $t SET o.status='OUT', o.run=$run RETURN o.id` |
| Q4 tentative cascade | `MATCH (o:Observation {run:$run})-[:PREMISE_OF\|JUSTIFIES*1..12]->(x:Mem) WHERE x.status='IN' WITH DISTINCT x SET x.status='OUT', x.run=$run RETURN x.id`. Mixed rel types in a var-length path work. Marks b1 OUT too (tentative). |
| Q5 re-derive | **`WHERE NOT EXISTS { MATCH ... }` is NOT supported** (parse error). Use `MATCH (j:Justification)-[:JUSTIFIES]->(b:Mem {status:'OUT', run:$run}) OPTIONAL MATCH (p:Mem {status:'OUT'})-[:PREMISE_OF]->(j) WITH b, j, count(p) AS dead WHERE dead = 0 WITH DISTINCT b SET b.status='IN', b.run=null RETURN b.id`, looped from Python until it returns no rows. **Guard against vacuous justifications:** count total premises too (`WHERE total > 0 AND dead = 0`), otherwise a justification whose premise edge is missing is trivially satisfied. Final form is in `core/retract/cascade.py::_rederive`. Result: b1 back IN (independent support), b2 stays OUT. |
| Vector index | `CREATE VECTOR INDEX FOR (m:Mem) ON (m.embedding) OPTIONS {dimension:4, similarityFunction:'cosine'}`; write with `SET m.embedding = vecf32([...])`; query `CALL db.idx.vector.queryNodes('Mem','embedding',k,vecf32([...])) YIELD node, score WHERE node.status='IN' RETURN node.id, score`. **`score` is a distance (lower = closer)**. The status filter is applied after top-k, so ask for k larger than needed. |
| Q7 max flow | `algo.maxFlow` requires **exactly one** relationship type. Use dedicated `FLOW` edges: `(Source)-[:FLOW {cap:1}]->(Observation)` (gate) and `(premise)-[:FLOW {cap:1000000}]->(conclusion)`. `MATCH (s:Source) WITH collect(s) AS srcs MATCH (t:Belief) CALL algo.maxFlow({sourceNodes: srcs, targetNodes: [t], relationshipTypes: ['FLOW'], capacityProperty: 'cap'}) YIELD maxFlow RETURN t.id, maxFlow`. Result b1=2, b2=1, as expected. |
| Q8 PageRank | `CALL algo.pageRank(null,'DEPENDS_ON') YIELD node, score RETURN labels(node)[0], node.id, score`. Pass `null` as label so Sources are included. `algo.pageRank('Mem','PREMISE_OF')` is useless: PREMISE_OF goes to `Justification`, so there are no Mem-to-Mem edges. |
| WCC | `CALL algo.WCC({nodeLabels:['Mem']}) YIELD node, componentId`. Uses all edges between the labelled nodes, so the FLOW/DEPENDS_ON edges connect components; for disagreement clusters run it on a CONTRADICTS-only projection. |
| GRAPH.COPY | `db.connection.execute_command("GRAPH.COPY", src, dst)`; then `db.select_graph(dst).delete()`. |
| GRAPH.PROFILE | `db.connection.execute_command("GRAPH.PROFILE", graph, "<cypher>")`. Returns plan lines with execution time. |

## Consequences for the contract

- Add `FLOW` Source-to-Observation gate edges (cap 1), not only premise-to-conclusion.
- `DEPENDS_ON` runs conclusion -> premise and Observation -> Source.
- `observed_at` and `executed_at` are stored as integer epoch seconds in the graph (ISO strings in fixtures).
- Re-derivation is a Python-driven loop of Q5, not a single query.

## Still to check (owner)

- A: Q5 loop on a cycle (`b_circ_a` / `b_circ_b` in `ap_tiny.json`) stays OUT. Done in A1/A2.
- B: confirm `GRAPH.PROFILE` output is parseable for the latency badge. (Embedding decided: 384-dim MiniLM, see CONTRACT.md.)
- ~~Pin the FalkorDB image digest~~ done in `docker-compose.yml`.

## Addendum (B5): max-flow vs poisoning cost

`algo.maxFlow` over the FLOW projection counts every justification as an OR of its premises, and counts per `Source->Observation` gate over the whole graph (OUT nodes included). On `ap_tiny`: `act_pay_2` = 3 (erp, po-system, portal), `b_addr` = 2, `b_bank_new` = 1. The true poisoning cost of `act_pay_2` is 1 (any one of the three claims failing kills the AND). So max-flow is an **upper bound**, exact only for single-premise chains. `core/fragility/q7.py` computes the exact cost from the JTMS fixpoint and keeps max-flow as `flow_upper_bound`. See `docs/FRAGILITY.md`.

## Addendum (B7/B11): server limits that silently or loudly change results

Read from `GRAPH.CONFIG GET` on the pinned image, found by running at 10k nodes:

| Setting | Default | What it does | What we do |
|---|---|---|---|
| `RESULTSET_SIZE` | **10000** | A query returning more rows is **silently truncated**: no error, no warning. | `core.db.fetch_all(g, cypher, params, order_by=...)` pages with `SKIP/LIMIT`. Use it for any read that can exceed 10k rows. |
| `MAX_QUEUED_QUERIES` | **25** | The 26th pending query gets `ResponseError: Max pending queries exceeded`: loud, nothing is lost. | Clients back off and retry (`bench/harness/concurrency._call`). At 50 concurrent writers 4 of 1,000 operations were rejected once and succeeded on retry. |
| `TIMEOUT` | **1000 ms** | Reads and writes are aborted after 1 s. | Not hit in any run so far (a 10k-node cascade is ~50 ms); keep an eye on it at 100k. |

How it was found: a consistency checker that read all justifications reported 1,076 "stale" nodes at 10k that
were not stale: it had received exactly 10,000 of 11,076 rows. Paging fixed the checker; the cascade was right.
Places to check for the same hazard (Lane A, not changed here): `core/retract/cascade._report` (flipped nodes),
`core/recall/recall_list`, the Remediator's action scan, and any strategy's `out_ids` query in `bench/baselines`.
