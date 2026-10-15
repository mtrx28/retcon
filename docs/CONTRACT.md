# CONTRACT: the seam between Lane A and Lane B

**Status: FROZEN (task 0.2, 2026-10-15).** Both team members agreed the three open decisions below. Changes now need both people's agreement in a PR. **v1.1 (2026-10-15) adds three optional fields, see the last section.**

## 1. Tenancy

- One FalkorDB graph per tenant, named `tenant_<id>`. Default demo tenant: `tenant_northwind`.
- Preview forks: `tenant_<id>_preview_<retraction_id>`, deleted after the diff is returned.

## 2. Node labels and properties

| Label | Properties | Notes |
|---|---|---|
| `Source` | `id, kind (portal\|pdf\|email\|agent\|user), url, trust (0–1)` | Trust drives entrenchment and the min-cut threshold |
| `Mem` | `id, text, status (IN\|OUT), created_at, agent, embedding, run` | Shared label for all memory nodes |
| `Observation` (also `Mem`) | `observed_at` | Only node type a Source touches directly |
| `Belief` / `Plan` (also `Mem`) | | Derived by an agent |
| `Action` (also `Mem`) | `tool, amount, executed (bool), executed_at` | |
| `Justification` | `id, rule (extract\|infer\|combine\|handoff), agent, at` | One per derivation; AND of its premises |
| `Agent` | `id, role, tenant` | Receives retraction events |
| `Retraction` | `id, source, from, to, reason, operator, at, mode (preview\|commit)` | Audit trail |

Indexes: `Mem(id)`, `Source(id)`, `Observation(observed_at)`, `Mem(status)`, vector index on `Mem.embedding`.
**Decision: embeddings are 384-dimensional**, produced locally by `sentence-transformers/all-MiniLM-L6-v2` (offline, free, deterministic, no API key). Index: `CREATE VECTOR INDEX FOR (m:Mem) ON (m.embedding) OPTIONS {dimension:384, similarityFunction:'cosine'}`. The dimension is baked into the index; changing it means rebuilding the graph. Query syntax and the "score is a distance, lower is closer" gotcha are in `docs/SPIKE.md`.

## 3. Edges

| Edge | Direction | Meaning |
|---|---|---|
| `SUPPORTS` | `(Source)->(Observation)` | Source asserted the observation |
| `PREMISE_OF` | `(Mem)->(Justification)` | Premise of a derivation |
| `JUSTIFIES` | `(Justification)->(Mem)` | Derivation concludes this node |
| `HOLDS` | `(Agent)->(Mem)` | Agent has this node in memory |
| `DEPENDS_ON` | `(conclusion)->(premise)`, `(Observation)->(Source)` | For PageRank (Q8) |
| `FLOW` | `(Source)->(Observation)` cap 1 (the gate); `(premise)->(conclusion)` cap 1000000 | Maintained on write; `algo.maxFlow` needs exactly one rel type |
| `CONTRADICTS` | `(Mem)-(Mem)` | For WCC clusters |
| `RETRACTED` / `REINSTATED` | `(Retraction)->(Mem)` | Which nodes flipped |

Edge names confirmed against the live engine in `docs/SPIKE.md`. Timestamps (`observed_at`, `executed_at`) are integer epoch seconds in the graph; fixtures use ISO 8601.

## 4. Status semantics (the JTMS invariant)

- A `Mem` is `IN` iff it is an `Observation` whose source is trusted for that window, **or** some `Justification` pointing at it has all premises `IN`.
- `run` is set only during a cascade (Q4) and cleared by re-derivation (Q5). It must be `null` outside a cascade.
- Nodes are never deleted. `reinstate(retraction_id)` restores the exact prior status of every node it flipped.

## 5. MCP tools

| Tool | Lane | Args | Returns |
|---|---|---|---|
| `remember` | B | `text, kind (belief\|plan), agent` | `{node_id, premise_ids[]}` |
| `recall` | B | `query, agent, k=8` | `[{id, text, score, sources, weakest_trust}]` (IN only) |
| `act` | B (calls A's gate) | `tool, args, agent` | `{executed: bool, action_id, blocked_reason?}` |
| `fragility` | B | `node_id` | `{independent_sources, bound: "exact"\|"upper"}` |
| `distrust` | A | `source, from, to, mode (preview\|commit)` | `{retraction_id, flipped: {observations, beliefs, plans, actions}, blocked_action_ids[], recall_list[], latency_ms}` |
| `reinstate` | A | `retraction_id` | `{restored_count}` |
| `why` | A | `node_id` | Justification tree (nested JSON) |
| `recall_list` | A | `run` | `[{action_id, tool, amount, executed_at, agent}]` ordered by amount |

**Python keyword note (A3):** `from` is a Python keyword, so the MCP argument of `distrust` is spelled `from_` (`to` unchanged). Extra codes in use: `NOT_IMPLEMENTED` (`mode=preview` until A5), `NOT_CONFIGURED`. A tool that returns a list (`recall_list`) is delivered by MCP as one text content item per element; an empty list is no content.

**Error shape (decision):** every MCP tool returns either its normal payload or exactly:

```json
{"error": {"code": "NOT_FOUND", "message": "human-readable", "details": {}}}
```

A success payload never has an `error` key, so callers check that one field. Codes: `NOT_FOUND`, `OUT_OF_WINDOW`, `BLOCKED_BY_POLICY`, `INVALID_ARGUMENT`. `BLOCKED_BY_POLICY.details` carries the reason, e.g. `{"out_premise_ids": [...]}` or `{"independent_sources": 1, "required": 2}`; the Remediator and the UI both display it.

## 6. Retraction event (pushed to agents)

```json
{
  "retraction_id": "ret_0001",
  "agent": "payments",
  "belief_id": "mem_123",
  "reason": "Source coastal-portal distrusted 2026-10-02..2026-10-09",
  "invalidated_plan_ids": ["mem_201", "mem_207"]
}
```

## 7. Gate policy (decision)

`act` succeeds only if every premise of the action is `IN` **and** the tool's policy is met. The policy is data, not logic: a dict in `gate/policy.py`, so adding a tool is one entry. Gate lives in Lane A (`gate/`); it calls Lane B's `fragility`.

| Tool | Rule |
|---|---|
| `pay` | All premises IN. If `amount > 10000`, also at least 2 independent sources (Q7 score). |
| `email`, `notify` | All premises IN. |
| any other tool | All premises IN. |

Note for the demo: under this rule the $41,250 payment (one portal behind it, fragility 1) is flagged before any attack. The already-executed $18,400 payment exists in the recorded seed run; a live agent run would have been stopped by the same gate.

## 8. Scenario / fixture format

`data/fixtures/ap_tiny.json` and the generator output share one schema:

```json
{
  "tenant": "northwind",
  "sources": [{"id": "coastal-portal", "kind": "portal", "trust": 0.6}],
  "agents": [{"id": "intake", "role": "intake"}],
  "observations": [{"id": "obs_1", "source": "coastal-portal", "text": "...", "observed_at": "2026-10-05T10:00:00Z"}],
  "derivations": [{"id": "d_1", "rule": "infer", "agent": "analyst", "premises": ["obs_1"], "conclusion": {"id": "mem_1", "kind": "belief", "text": "..."}}],
  "actions": [{"id": "act_1", "tool": "pay", "amount": 18400, "executed": true, "executed_at": "...", "premises": ["mem_1"]}],
  "ground_truth": {"contaminated": ["obs_1", "mem_1", "act_1"], "truly_supported": ["mem_addr"]}
}
```

Required fixture coverage: one poisoned source with a time window, one claim laundered through several agents, one belief with independent contract-PDF support, one executed and one pending payment, one circular support pair.

## v1.1 (Oct 15): additive, backward-compatible

Nothing from v1 is renamed or removed. `ap_tiny.json`, A1/A2, B1/B2/B4a and every existing test keep working unchanged.

- `:Mem.mtype` (optional): `"episodic" | "semantic" | "procedural"`
  - Observation = episodic (always)
  - Belief = semantic (default)
  - learned rule ("verify bank changes by callback") = procedural
- Scenario JSON: optional top-level `"domain": "ap" | "science"` (missing = `"ap"`)
- Science sources (optional fields): `"retracted_at": "YYYY-MM-DD"`, `"rw_reason": "<string from dataset>"`
- Ground-truth labels `contaminated` / `truly_supported` stay required for every domain

Notes:
- In a fixture, a derivation's `conclusion` may carry an optional `"mtype"`. Without it, the loader tags `semantic` for beliefs and leaves plans/actions untagged.
- No `schema.cypher` change: FalkorDB does not require declared properties. Add `CREATE INDEX FOR (m:Mem) ON (m.mtype)` only if a query filters by type.
- Describe retractions only through the dataset's own reason field (`rw_reason`); never characterise authors.

## v1.2 (A4, Oct 15): additive

- New node `:Remediation {id, kind (bank_recall|correction_email|manual_review), status (draft|approved|executed|rejected|withdrawn), title, payload(JSON), amount, reason, retraction_id, created_at, approved_by, approved_at, result, error}`.
  Edges: `(Retraction)-[:TRIGGERED]->(Remediation)-[:COMPENSATES]->(Action)`.
- `:Action` gains `args` (JSON string), `result` (JSON string), `gate_state` (`blocked|released`), `blocked_reason` (JSON). `executed` / `executed_at` as before.
- `distrust` response gains `remediations: [...]` (drafts, never executed on their own).
- New MCP tools (Lane A): `list_remediations(status?)`, `approve_remediation(remediation_id, operator)`, `reject_remediation(remediation_id, operator)`.
- `act(tool, args, agent)` is implemented in `gate/tools.py` + `core/actions.py` (Lane A, because the gate sits behind it) and registered by `mcp_server/server.py`. Signature unchanged. It justifies the action by the agent's captured recall context.
- Gate decision block reason (`BLOCKED_BY_POLICY`): `details.reason_code` is `PREMISE_RETRACTED` (with `out_premise_ids`, `retraction_ids`) or `INSUFFICIENT_INDEPENDENT_SOURCES` (with `independent_sources`, `required`). The independence rule calls Lane B's `fragility`; until it exists the gate adds a warning instead of guessing.

## v1.3 (A5/A6, Oct 15): additive

- `distrust` response gains `survived_ids` (nodes downstream of the source that stayed IN by independent support) and `profile: {query, execution_ms, plan[]}` (GRAPH.PROFILE of the cascade traversal; wall-clock, so scrubbed from deterministic transcripts).
- `distrust(mode="preview")` is implemented: same payload plus `preview: true` and `diff: [{id, kind, from, to, hop}]`. It runs on a `GRAPH.COPY` fork named `<graph>_preview_<retraction_id>`, which is deleted before returning. The live graph is not written (no Retraction, no Remediation). `retraction_id` is the id a commit would receive.
- Operator console HTTP API (UI only, not MCP): `/api/ops/*`, see `ui/ops/__init__.py`.

## v1.4 RetconBench interface (A7 / B7, Oct 15): additive, **proposed: B to confirm in review**

Executable form: `bench/api.py` (pinned by `tests/bench/test_interface.py`). Lane A writes strategies and
`metrics`; Lane B writes the harness, scale runs, laundering probe, charts and the graph-off ablation.
Neither imports the other's package; both import `bench.api`.

**Strategy** (one class per name; names are fixed and are the column order in every table):

```python
class Strategy(Protocol):
    name: str                                            # delete_source | vector_only | edge_invalidation | coarse_taint | retcon
    def retract(self, graph, window: Window) -> RetractionResult: ...
    # optional: def support_count(self, graph, node_id) -> int     (laundering probe, Lane B)

Window(source, t_from, t_to)            # from_spec(spec["window"]); inclusive; ISO 8601; same semantics as distrust
RetractionResult(out_ids: set[str], engine_ms: float | None, notes: dict)
```

Rules:
- `out_ids` = ids of `:Mem` nodes **no longer retrievable by an agent** after the retraction. A strategy
  that never writes statuses (vector store, edge invalidation) reports what it deleted or invalidated.
  Anything not in `out_ids` is still served. The harness reads the return value, never node statuses.
- The harness gives every call a **freshly loaded** graph (`data.load_fixture.load(spec, graph_name=...)`,
  ids equal spec ids), so a strategy may mutate it. Benchmarks load the spec directly; they do **not**
  run agents, because agent-built graphs have hashed ids and no ground truth.
- Deterministic: no unseeded randomness, no clock, no network. A strategy that needs embeddings uses
  `core.retrieve.embed.get_embedder()` (default `hash` for CI) on `Mem.text`.
- Errors: raise; the harness records `error` for that (scenario, strategy) and carries on.

**Windows.** `bench.api.windows(spec)`: AP scenarios have the single `window`; science scenarios have one
window per retracted paper (`retractions`, chronological). The harness calls `retract()` once per window on
the **same** graph and takes the union of `out_ids` (for `retcon`, `out_ids` is every OUT node, so the last
call already reports the accumulated result).

**Strategies (what each one means, so expectations are shared):**

| name | out_ids | expected shape |
|---|---|---|
| `delete_source` | observations of `source` in the window, nothing else | residual high, no action recall |
| `vector_only` | those observations plus every `Mem` whose cosine similarity to one of them is >= 0.75 (`notes.threshold`), no graph | residual high, noisy collateral; **also the graph-off ablation's retraction rule** (B7 imports it) |
| `edge_invalidation` | those observations plus nodes one hop downstream (Graphiti-style), no cascade | residual high |
| `coarse_taint` | every descendant of those observations by any path (any-ancestor rule), no re-derivation | residual ~0, **collateral high** |
| `retcon` | `core.retract.cascade.distrust` on the fork, then every `:Mem` with `status = 'OUT'` | residual 0, collateral 0 |

**Metrics** (`metrics(ground_truth, out_ids, actions)`; ratios in [0, 1], `None` when the denominator is empty):

| key | definition | better |
|---|---|---|
| `residual_contamination` | contaminated nodes not in `out_ids` / contaminated | lower |
| `collateral_loss` | truly_supported nodes in `out_ids` / truly_supported | lower |
| `action_recall` | executed contaminated actions in `out_ids` / executed contaminated actions | higher |
| `action_precision` | flagged executed actions that were contaminated / flagged executed actions | higher |
| `blocked_recall` | pending contaminated actions in `out_ids` / pending contaminated actions | higher |
| `counts` | `contaminated, truly_supported, out, executed_contaminated, pending_contaminated` | |

`ground_truth` keys: `contaminated`, `truly_supported` (required, both domains); `recall_list`, `blocked`
(optional; derived from `actions[].executed` when absent). Laundering resistance and cascade latency are
Lane B's columns: latency is measured by the harness around `retract()` (`elapsed_ms`), `engine_ms` is the
strategy's own number, and laundering uses the optional `support_count`.

**Results file** (`bench/results/<run>.json`, a JSON list, one row per scenario x strategy; `record()`):

```json
{"scenario": "ap_1k", "domain": "ap", "nodes": 1000, "seed": 7, "strategy": "coarse_taint",
 "out_count": 412, "metrics": {...}, "elapsed_ms": 31.2, "engine_ms": null, "notes": {}, "error": null}
```

Scenario names: `ap_tiny`, `ap_1k`, `ap_10k`, `ap_100k` (target tier), `science_tiny`, `science` (B10 output).
`domain` is the contract v1.1 field. A's science report and B's charts read this same file.
