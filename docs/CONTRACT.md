# CONTRACT: the seam between Lane A and Lane B

**Status: DRAFT.** Finalise in Phase 0 task 0.2 (after the Cypher spike, 0.3), then freeze. After freezing, changes need both people's agreement in a PR. Items marked `TODO(0.2)` are decisions to make in that session.

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
`TODO(0.2)`: embedding dimension and model; confirm vector index call syntax from `docs/SPIKE.md`.

## 3. Edges

| Edge | Direction | Meaning |
|---|---|---|
| `SUPPORTS` | `(Source)->(Observation)` | Source asserted the observation |
| `PREMISE_OF` | `(Mem)->(Justification)` | Premise of a derivation |
| `JUSTIFIES` | `(Justification)->(Mem)` | Derivation concludes this node |
| `HOLDS` | `(Agent)->(Mem)` | Agent has this node in memory |
| `DEPENDS_ON` | `(conclusion)->(premise)` | For PageRank (Q8) |
| `FLOW` | premise -> conclusion, `cap` | Maintained on write for Q7 min-cut |
| `CONTRADICTS` | `(Mem)-(Mem)` | For WCC clusters |
| `RETRACTED` / `REINSTATED` | `(Retraction)->(Mem)` | Which nodes flipped |

`TODO(0.2)`: confirm exact edge names against the Q1–Q8 skeletons after the spike.

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

`TODO(0.2)`: error shape, e.g. `{error: {code, message}}`; codes `NOT_FOUND`, `OUT_OF_WINDOW`, `BLOCKED_BY_POLICY`.

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

## 7. Gate policy

`act` succeeds only if every premise of the action is `IN` **and** the tool's policy is met. Default policy table (`TODO(0.2)` confirm): `pay` over $10,000 requires >= 2 independent sources (Q7 score); other tools require only all-IN premises. Gate lives in Lane A (`gate/`); it calls Lane B's `fragility`.

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
