# RETCON: two-person build plan

Source spec: the "RETCON — Retractable Memory for Multi-Agent AI (Graph Hacks Spec)" doc. This plan replaces its four-role build table (A/B/C/D) with a two-person split. Window: Oct 15 to Oct 18 IST, submit by 9 PM Oct 18 (deadline 11:59 PM).

**Read order for any Claude agent starting a session:** `CLAUDE.md` -> `docs/STATUS.md` -> `docs/CONTRACT.md` -> this file.

---

## 1. How the work is split

The spec's natural split (graph core + agents | UI + data/eval) is lopsided: one person would own all the Cypher and the other never touch it, and rules 12–13 say *both* of us must explain Q4–Q7.

So we split into **two vertical lanes**. Each lane owns a full slice, from Cypher query to MCP tool to UI panel to benchmark metric. Both of us touch FalkorDB, MCP, UI and eval.

| | **Lane A: "Retract & Prove"** | **Lane B: "Remember & Foresee"** |
|---|---|---|
| Idea | What happens when a source goes bad | What agents believe, and how fragile it is *before* it goes bad |
| Core queries | Q3 distrust, Q4 cascade, Q5 re-derive, Q6 recall list, GRAPH.COPY preview | Q1 justified write, Q2 grounded retrieval, Q7 min-cut, Q8 PageRank, WCC |
| Agents | Remediator, action gate, reinstate | Intake, Analyst, Payments, Comms, middleware, handoffs, re-plan, graph-off flag |
| MCP tools | `distrust`, `reinstate`, `why`, `recall_list` | `remember`, `recall`, `act`, `fragility` |
| UI | Cascade animation, preview diff, recall panel, latency badge | Graph canvas shell, live growth, fragility radar |
| Data / eval | Baselines 1–4, residual contamination, collateral loss, action recall | Scenario generator, fake portal, mock bank, harness, laundering metric, scale runs |
| Tests | Property tests + differential JTMS reference | Query-level tests for Q1/Q2/Q7 |
| Ship | README (data model, queries, related work), demo video | Deploy, DATA.md, blog |

**Weight (est. hours):** A ≈ 39 h, B ≈ 39 h. Detail in section 3.

**Why this doesn't strand anyone:** the lanes meet only at a small frozen contract (section 4). Either lane can be developed and tested against shared fixtures without the other lane's code existing yet.

---

## 2. Pickup protocol (what makes swapping painless)

1. **`docs/CONTRACT.md` is the seam.** Graph schema, node/edge/status enums, MCP tool signatures with JSON types, retraction event payload, scenario JSON format, error shapes. Written together in Phase 0, then frozen. Changes need both people to agree in a PR.
2. **`docs/STATUS.md` is the baton.** One row per task: owner, state (todo / doing / done / blocked), last commit, *next step*, known gotchas. Every Claude session must update it before ending. `CLAUDE.md` tells the agent to do this.
3. **Tests are the spec.** Every task has a one-line acceptance command (`make accept T=A3`). If it passes, the task is done, whoever finished it.
4. **Fixtures decouple us.** `data/fixtures/ap_tiny.json` is a hand-written ~40-node graph (one poisoned source, one laundered claim, one independently corroborated belief, one executed and one pending payment). Lane A develops the cascade on it. Lane B's generator must emit the same format. Neither waits for the other.
5. **Directory ownership, not file ownership.** Each lane has its own folders (section 5), so merges rarely conflict. `schema.cypher`, `CONTRACT.md` and `STATUS.md` are the only shared files.
6. **Trunk-based, small commits.** Branch per task (`a/A4-gate`, `b/B3-agents`), merge to `main` when acceptance passes, never leave main red. Commit message starts with the task id.
7. **Cross-review every merge.** The other person (and their Claude) reads the diff. This is how we both end up able to explain Q4–Q7 and the JTMS invariant, and it keeps context warm.
8. **Task cards.** Each task in section 3 lists files, acceptance check and a "done means" line, so a fresh Claude can pick it up cold.

If someone falls behind, the *unstarted* task nearest the other lane's work moves over (marked in section 7). Nothing in progress is swapped.

---

## 3. Task list, owners and finish order

Order numbers are the global finish sequence. Tasks with the same number run in parallel.

### Phase 0: together, ~3 h, Oct 15 morning (blocks everything)

| # | Task | Output |
|---|---|---|
| 0.1 | Repo skeleton, `docker-compose.yml` (FalkorDB + server + UI), Makefile, lint/test setup | `make up`, `make test` work |
| 0.2 | Write and freeze `docs/CONTRACT.md` + `schema.cypher` + indexes | Contract file merged |
| 0.3 | **Cypher spike:** run Q1–Q8 skeletons, vector index call, `algo.maxFlow`, `GRAPH.COPY` against live FalkorDB; record what differs from the spec | `docs/SPIKE.md` with working syntax |
| 0.4 | Hand-write `ap_tiny.json` fixture + loader | `make fixture` loads it |
| 0.5 | `CLAUDE.md` and `STATUS.md` seeded with every task below | Both Claudes can start from cold |

Do 0.3 together: the spec itself says to verify every query on Day 1, and the results shape both lanes.

### Phase 1: foundations, Oct 15 afternoon to Oct 16 midday (parallel)

| Order | Lane A | est | Lane B | est |
|---|---|---|---|---|
| 1 | **A1** Q3–Q5 cascade + re-derive loop on fixture; writes `:Retraction` node | 5 h | **B1** Q1 justified write + automatic premise capture middleware | 4 h |
| 2 | **A2** Property tests (every IN node has an all-IN justification; no OUT node does; reinstate restores exact state) + 60-line in-memory JTMS reference + differential test | 4 h | **B2** Q2 vector index retrieval, IN-only, support summary (source count, weakest trust) | 3 h |
| 2 | | | **B4a** Generator v1: Northwind AP scenario, seeded, emits fixture format; fake portal page; mock bank API; sandbox inbox | 4 h |
| 3 | **A3** MCP `distrust` / `reinstate` / `why` over A1; audit trail | 3 h | **B3** Agent loop + four agents + handoff edges + retraction-event re-plan (LLM calls cached/seeded) | 7 h |

### Gate: Oct 16 night, together (~1.5 h)

**End-to-end: `distrust(Coastal portal, Oct 2–9)` -> cascade -> pending $41,250 payment blocked -> executed $18,400 on the recall list -> address belief survives via the contract PDF.**

Needs A1, A3, A4 (below), B1, B2, B3. Both people sit on this. If it fails, apply the cut list in section 6.

| Order | Lane A | est | Lane B | est |
|---|---|---|---|---|
| 4 | **A4** Action gate + Q6 recall list + Remediator drafts compensating action behind one-click approval | 5 h | **B6a** UI shell: graph canvas over FalkorDB, live node growth, status colours | 3 h |

### Phase 2: differentiators, Oct 17 (parallel)

| Order | Lane A | est | Lane B | est |
|---|---|---|---|---|
| 5 | **A5** `GRAPH.COPY` preview: run Q3–Q5 on fork, diff statuses, delete fork; MCP `mode=preview` | 3 h | **B5** FLOW edges maintained on write; Q7 `algo.maxFlow` min-cut; `fragility` MCP tool; gate policy "≥2 independent sources over $10k" | 3 h |
| 6 | **A6** UI: cascade hop-by-hop animation, preview diff view, recall panel, `GRAPH.PROFILE` latency badge | 8 h | **B6b** UI: fragility radar (Q7), Q8 PageRank keystone view | 3 h |
| 6 | | | **B5b** Q8 PageRank + `algo.WCC` over CONTRADICTS | 2 h |
| 7 | **A7** Baselines 1–4 (delete-source, vector-only, edge-invalidation, coarse-taint) + metrics: residual contamination, collateral loss, action recall | 6 h | **B7** RetconBench harness, generator at 1k/10k/100k, laundering-resistance metric, cascade latency p50/p95, graph-off ablation flag, charts | 6 h |

### Phase 3: ship, Oct 18 (freeze at noon IST)

| Order | Lane A | est | Lane B | est |
|---|---|---|---|---|
| 8 | **A8** README: pitch, data model diagram, "Queries we depend on" Q1–Q8 verbatim, related-work/novelty table, limitations, AI disclosure, tracks | 3 h | **B8** Deploy (docker-compose primary; FalkorDB Cloud + app host as bonus), `DATA.md` with generator seed | 3 h |
| 9 | **A9** Record and edit 3-minute video (seeded agent phase, live cascade) | 3 h | **B9** Blog post with real benchmark numbers (AirPods side prize) | 3 h |
| 10 | Rehearse the 30-minute Q4–Q7 walkthrough together, submit form naming Tracks 02 and 01 by 9 PM | | | |

**Totals:** A ≈ 40 h (Phase 0 share excluded), B ≈ 40 h. Both ≈ 3 h shared in Phase 0 and ≈ 1.5 h at the gate.

---

## 4. Contract (frozen after Phase 0)

Written in `docs/CONTRACT.md`. Summary of what must be in it:

- **Node labels:** `Source, Observation, Justification, Mem (Belief|Plan|Action), Agent, Retraction`. Shared `:Mem` label for algorithm projections.
- **Edges:** `FROM_SOURCE/SUPPORTS`, `PREMISE_OF`, `HOLDS`, `DEPENDS_ON`, `FLOW`, `CONTRADICTS`, plus Retraction links.
- **Status enum:** `IN | OUT`, with `run` tag used only during a cascade.
- **MCP signatures:** `remember(text, kind, agent)`, `recall(query, agent, k)`, `act(tool, args, agent)`, `distrust(source, from, to, mode)`, `reinstate(retraction_id)`, `why(node_id)`, `fragility(node_id)`, `recall_list(run)`.
- **Retraction event payload:** `{retraction_id, agent, belief_id, reason, invalidated_plan_ids[]}`.
- **Scenario format:** fixture JSON schema (sources, observations, derivations, actions, with ground-truth labels `contaminated` and `truly_supported`).
- **Tenancy:** one graph per tenant, named `tenant_<id>`.

---

## 5. Directory ownership

```
retcon/
  CLAUDE.md               shared, conventions + "read STATUS.md first"
  docs/                   BUILD_PLAN, CONTRACT, STATUS, SPIKE: shared
  docker-compose.yml      shared (Phase 0)
  core/
    schema.cypher         shared, change only via both
    retract/   recall/   preview/        <- A
    write/     retrieve/ fragility/      <- B
  mcp_server/
    tools_retract.py                     <- A  (distrust, reinstate, why, recall_list)
    tools_memory.py                      <- B  (remember, recall, act, fragility)
  gate/                                  <- A
  agents/
    remediator.py                        <- A
    intake/analyst/payments/comms.py     <- B
  data/
    fixtures/ap_tiny.json                shared (Phase 0)
    generator/  portal/  bank/           <- B
  bench/
    baselines/  metrics_retract.py       <- A
    harness/    metrics_scale.py         <- B
  ui/
    shell/  radar/                       <- B
    cascade/ preview/ recall/            <- A
  tests/
    property/ differential/              <- A
    queries/                             <- B
```

---

## 6. What we commit to (scope)

Total effort is split 50/50 within each tier.

**Commit: must ship (about 75% of effort).** Judged on these.
- Q1–Q6, JTMS re-derive, property + differential tests
- Four agents + Remediator, action gate, recall list, graph-off flag
- Q7 min-cut (it is the demo's 0:50 moment and a novelty claim)
- `GRAPH.COPY` preview
- UI: live graph, cascade animation, recall panel, fragility radar, preview diff
- Generator, fake portal, mock bank; RetconBench with 4 baselines at 1k and 10k nodes
- README, 3-min video, blog, docker-compose local setup, DATA.md, AI disclosure

**Target: ship if the gate passes on time (about 20%).**
- Q8 PageRank, WCC clusters
- 100k-node benchmark run
- FalkorDB Cloud live deploy
- GRAPH.PROFILE badge polish

**Stretch: only with spare time (about 5%), in this order.**
1. Point-in-time replay (cheap, because we never delete)
2. Entrenchment-based auto-retraction on contradiction
3. Graphiti bridge
4. Cross-tenant threat sharing

**Cut list if the gate slips (cut in this order):** stretch -> Cloud deploy -> 100k run -> WCC -> PageRank -> preview diff polish. Never cut: Q3–Q7, the gate, recall list, the graph-off flag.

**Don't forget:** first commit after Oct 15 12:01 AM IST (rule 8); no copied code from Veritas/MemLineage/MemTX (rule 9); all data synthetic (rule 6).

---

## 7. Flex tasks (whoever has slack picks these up)

- README sections beyond data model and queries
- Chart styling and the cascade GIF for the README
- Demo-script timing rehearsal
- If Lane A is behind at the gate: **B takes A5** (preview). If Lane B is behind: **A takes B5b** (PageRank/WCC) and **B8** (deploy).
