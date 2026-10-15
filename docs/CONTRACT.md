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
