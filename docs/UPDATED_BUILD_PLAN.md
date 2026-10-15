# RETCON: two-person build plan (v2, with upgrades)

Source spec: the "RETCON — Retractable Memory for Multi-Agent AI (Graph Hacks Spec)" doc.

This v2 replaces v1. It covers three things:

- what is already done;
- folds in all upgrades:
  - a real-data science scenario
  - Track 02 coverage (memory types, concurrency, tenancy)
  - a sharper Track 01 story (agents use graph algorithms as tools)
  - an MCP-client ecosystem demo
  - the new video hook
- rebalances the remaining work between the two lanes.

**Window:** Oct 15 to Oct 18 IST. Code freeze Oct 18, 12:00 noon. Submit by 9 PM Oct 18; the deadline is 11:59 PM.

**Tracks:** Track 02 Agent Memory and Coordination (primary) + Track 01 Agents That Act on Connected Data. Name both on the form.

**Read order for any Claude agent starting a session:** `CLAUDE.md` -> `docs/STATUS.md` -> `docs/CONTRACT.md` -> this file.

---

## 0. Where we are (as of Oct 15, 14:30 IST)

| Task | Owner | State |
|---|---|---|
| Phase 0 (0.1–0.5): skeleton, contract v1, spike, fixture, CLAUDE.md/STATUS.md | both | done |
| A1 Q3–Q5 cascade + re-derive + `:Retraction` node | A | done |
| A2 Property tests + JTMS reference + differential test | A | done |
| B1 Q1 justified write + premise-capture middleware | B | done |
| B2 Q2 grounded retrieval (vector, IN-only, support summary) | B | done |
| B4a Generator v1 (Northwind AP), fake portal, mock bank, sandbox inbox | B | done |
| A3 MCP `distrust` / `reinstate` / `why` | A | **next** |
| B3 Agent loop + four agents + handoffs + re-plan | B | **next** |

**Remaining budget:** about 37 h each, across roughly 78 wall-clock hours until submission. That's tight but fits if the cut list (section 7) is respected.

---

## 1. What changed from v1 (summary)

1. **Real-data scenario (new, must-ship).** Research agents build beliefs from real paper abstracts; real retractions from the Retraction Watch database trigger RETCON. This replaces the two extra synthetic domains (support-bot, dev-agent) from the spec, which are now **dropped**.
2. **Track 02 coverage.**
   - Memory types: an `mtype` property (episodic / semantic / procedural), plus a retractable procedural rule.
   - A concurrency load test.
   - A two-tenant isolation check.
   - A coverage table in the README.
3. **Track 01 story.** The Payments agent itself calls `fragility` and `why` through MCP, and decides to request verification when poisoning cost is below 2. The graph drives agent decisions, not just the operator console.
4. **Ecosystem demo.** RETCON used from a stock MCP client (e.g. Claude Code) with a config snippet and a 20-second clip.
5. **Video re-cut.**
   - Open on stakes: "Your agent paid $18,400 to a fraudster. Which of its other 2,000 memories are lies?"
   - Add a real-data beat.
6. **Rebalanced lanes.** PageRank/WCC and the MCP-client clip move to Lane A, because Lane B now owns the science ingest and the load test.
7. **Scope tiers and cut order updated** (section 7). The science scenario joins the never-cut list.

---

## 2. How the work is split

Two vertical lanes. Each owns a full slice: Cypher -> MCP tool -> UI panel -> benchmark metric. Both people touch FalkorDB, MCP, UI and eval, so both can explain Q4–Q7 (rules 12–13).

| | **Lane A: "Retract & Prove"** | **Lane B: "Remember & Foresee"** |
|---|---|---|
| Idea | What happens when a source goes bad | What agents believe, and how fragile it is before it goes bad |
| Queries | Q3–Q6, GRAPH.COPY preview, **Q8 PageRank, WCC** (moved from B) | Q1, Q2, Q7 min-cut, FLOW edges |
| Agents | Remediator, action gate, reinstate, **research agents (Reader, Synthesizer)** | Intake, Analyst, Payments, Comms, middleware, handoffs, re-plan, graph-off flag |
| MCP tools | `distrust`, `reinstate`, `why`, `recall_list` | `remember`, `recall`, `act`, `fragility` |
| UI | Cascade animation, preview diff, recall panel, latency badge, **keystone view** | Graph shell, live growth, fragility radar |
| Data / eval | Baselines 1–4, retract metrics, **science evaluation** | Generator, **science ingest**, harness, laundering metric, scale runs, **concurrency + tenancy test** |
| Ship | README, video, **MCP-client clip** | Deploy, DATA.md, blog |

**Remaining hours:** A ≈ 37 h, B ≈ 37 h (section 4 has the per-task estimates).

---

## 3. Pickup protocol (unchanged, still mandatory)

1. **`docs/CONTRACT.md` is the seam.** It is frozen; changes need both people in a PR. v1.1 is the only planned change (section 5).
2. **`docs/STATUS.md` is the baton.** One row per task: owner, state (todo / doing / done / blocked), last commit, next step, gotchas. Every Claude session updates it before ending.
3. **Tests are the spec.** Every task has `make accept T=<id>`. If it passes, the task is done, whoever finished it.
4. **Fixtures decouple us.**
   - `data/fixtures/ap_tiny.json` is the AP fixture.
   - `data/fixtures/science_tiny.json` (new, hand-written, about 30 nodes) lets A start research agents and eval before B10 lands.
5. **Directory ownership, not file ownership** (section 6). Shared files: `schema.cypher`, `CONTRACT.md`, `STATUS.md`.
6. **Trunk-based, small commits.**
   - Branch per task (`a/A4-gate`); merge to `main` only when acceptance passes. `main` is never red.
   - Commit messages start with the task id.
7. **Cross-review every merge.** The other person and their Claude read the diff.
8. **Task cards.** Every task in section 4 has files, an acceptance check and a "done means" line.

If someone falls behind, the *unstarted* task nearest the other lane moves over (section 8). Nothing in progress is swapped.

---

## 4. Remaining tasks, owners and finish order

Order numbers give the global finish sequence; the same number means the tasks run in parallel. Each card lists: owner, estimate, depends-on, acceptance, and "done means".

### Step 0: together, now (Oct 15 afternoon, ~45 min)

| # | Task | Output |
|---|---|---|
| 0.6 | **Contract v1.1 PR** (section 5): optional `mtype` on `:Mem`; optional `domain` in scenario JSON; `science` scenario ground-truth fields | `CONTRACT.md` v1.1 merged; STATUS.md seeded with every card below |
| 0.7 | B starts the **background data pull** (no LLM cost): clone the Retraction Watch repo; start OpenAlex fetches for candidate topics | Raw files under `data/science/raw/` (gitignored) |
| 0.8 | Both post a short progress note in the FalkorDB Discord, with one real technical question (e.g. `algo.maxFlow` on our FLOW projection) | Done (visibility counts) |

### Phase 1 (rest of Oct 15 -> Oct 16 midday)

| Order | Lane A | est | Lane B | est |
|---|---|---|---|---|
| 1 | **A3** MCP `distrust` / `reinstate` / `why` over A1, with audit trail | 3 h | **B1+** `mtype` tagging on the write path; Intake stores a procedural rule ("verify bank-detail changes by callback") justified by an episode | 1 h |
| 2 | **A4** Action gate + Q6 recall list + Remediator drafts the compensating action behind one-click approval | 5 h | **B3** Agent loop, four agents, handoff edges, retraction-event re-plan (LLM calls cached and seeded) **including B3+** | 8 h |

**A3**
- Acceptance: `make accept T=A3`. An MCP client calls `distrust(src, from, to, mode=commit)` on `ap_tiny`; the response lists flipped nodes; `why(node)` returns the justification tree; `reinstate(id)` restores the exact prior state (re-uses A2's property).
- Done means: an MCP-callable retraction with a full audit trail.

**B1+**
- Acceptance: `make accept T=B1+`. The Q1 test asserts all three `mtype` values exist after a seeded run, and that the procedural rule has a justification pointing to an episodic node.
- Done means: Track 02's "episodic, semantic, procedural memory" is literally true in the graph.

**A4**
- Acceptance: `make accept T=A4`. On `ap_tiny`, after distrust, the pending payment is blocked with a reason, the executed payment is in the recall list ranked by amount, and a draft recall request exists awaiting approval.
- Done means: the Track 01 "actions based on what the graph shows" box is ticked from the operator side.

**B3 (with B3+)**
- B3+ means: before `act(pay, …)` the Payments agent calls `fragility(payment)` and `why(payment)` via MCP. If the poisoning cost is below 2, it chooses to request callback verification instead of paying.
- Acceptance: `make accept T=B3`. A seeded run shows the agents' tool-call log; the $41,250 payment gets a verification request with no operator involvement; a retraction event makes the affected agent re-plan.
- Done means: agents use graph algorithms as tools to decide (Track 01), and share state through handoffs (Track 02).

### Gate: Oct 16 night, together (~1.5 h)

**End-to-end on the AP scenario:**

1. `distrust(Coastal portal, Oct 2–9)`
2. -> the cascade runs
3. -> the pending $41,250 payment is blocked
4. -> the executed $18,400 is on the recall list with a drafted recall
5. -> the address belief survives via the contract PDF
6. -> the Payments agent re-plans to the verified account.

Needs A3, A4, B1+, B3. If it fails, apply the cut list (section 7) before starting Phase 2.

| Order | Lane A | est | Lane B | est |
|---|---|---|---|---|
| 3 | (gate fixes) | — | **B6a** UI shell: graph canvas over FalkorDB, live node growth, status colours | 3 h |

### Phase 2: differentiators + upgrades (Oct 17)

| Order | Lane A | est | Lane B | est |
|---|---|---|---|---|
| 4 | **A5** `GRAPH.COPY` preview: Q3–Q5 on a fork, diff statuses, delete the fork; MCP `mode=preview` | 3 h | **B5** FLOW edges maintained on write; Q7 `algo.maxFlow` min-cut; `fragility` tool; gate policy "≥2 independent sources over $10k" | 3 h |
| 5 | **A6** UI: cascade hop-by-hop animation, preview diff, recall panel, `GRAPH.PROFILE` latency badge (function first, polish last) | 6 h | **B10** Science ingest (design below), emitting the fixture format with real ground truth | 4 h |
| 6 | **A10** Research agents (Reader, Synthesizer) on the B3 loop with new prompts; one distrust per retracted paper; science metrics. Start on `science_tiny.json`, switch to B10 output when merged | 4 h | **B6b** UI: fragility radar (Q7) | 2 h |
| 7 | **A7** Baselines 1–4 (delete-source, vector-only, edge-invalidation, coarse-taint) + residual contamination, collateral loss, action recall, on **both** AP and science | 6 h | **B7** RetconBench harness: generator at 1k/10k, laundering-resistance metric, cascade latency p50/p95, graph-off ablation flag, charts | 5 h |
| 8 | **A12** Q8 PageRank keystone view + `algo.WCC` over CONTRADICTS (moved from B5b) | 2 h | **B11** Concurrency + tenancy test: 20–50 concurrent writer agents while a cascade runs (p50/p95, error rate); two-tenant isolation check | 3 h |

**A5**
- Acceptance: `make accept T=A5`. The preview returns the same flip set a commit would, the live graph is unchanged afterwards, and the fork is deleted.

**B5**
- Acceptance: `make accept T=B5`. On `ap_tiny`, poisoning cost for the $41,250 payment = 1 and for the address belief = 2. README caveat drafted: flow treats AND as OR, so the score is exact for single-premise chains and an upper bound otherwise.

**A6**
- Acceptance: `make accept T=A6`, a Playwright smoke test. Distrust animates, the recall panel lists the $18,400, and the latency badge shows a GRAPH.PROFILE number.

**B10 — science ingest design**
1. Source of retractions: the Retraction Watch CSV (Crossref GitLab repo `crossref/retraction-watch-data`).
2. Pick **one subject area** with at least 30 retracted papers whose abstracts are available in OpenAlex. Choose by filtering the CSV's subject field; don't pick a case because it's famous.
3. Corpus = those about 30 retracted papers + about 200 non-retracted papers that cite them or share topics, with abstracts and references from OpenAlex.
4. Mapping:
   - paper -> `Source` (trust from venue type; `retracted_at` from RW);
   - claim from an abstract -> `Observation`, with `observed_at` = publication date.
5. Ground truth:
   - a synthesized claim is `contaminated` if every supporting path ends at a retracted paper;
   - it is `truly_supported` if at least one path ends at a non-retracted paper.
6. Cache every LLM extraction to `data/science/cache/`, so runs are deterministic and cheap.
7. Describe retractions only through the dataset's own reason field. Never characterise authors.
- Acceptance: `make accept T=B10`. `make fixture S=science` loads; at least 30 retracted sources; ground-truth labels present on every Mem node.

**A10**
- Acceptance: `make accept T=A10`. Research agents produce at least 100 synthesized claims; retracting the real retracted papers yields a science column in the bench report.
- The report compares RETCON against the baselines on residual contamination and collateral loss, using the real retraction dates as the distrust trigger.

**A7**
- Acceptance: `make accept T=A7`. Bench report table with 5 strategies x 2 scenarios.

**B7**
- Acceptance: `make accept T=B7`. Charts generated. With the graph-off flag, the AP run shows the agents still paying the attacker.

**A12** (Target tier; first to cut)
- Acceptance: `make accept T=A12`. The top-5 keystone sources in the AP scenario include the Coastal portal.

**B11** (Target tier)
- Acceptance: `make accept T=B11`.
  - Chart of p50/p95 write and retrieval latency under N concurrent writers, plus the error rate.
  - Tenant B's graph is byte-identical before and after a distrust in tenant A.
- Measure first and report honestly. Don't assume FalkorDB's per-graph write behaviour; describe what you observe.

### Phase 3: ship (Oct 18, freeze at 12:00 noon IST)

| Order | Lane A | est | Lane B | est |
|---|---|---|---|---|
| 9 | **A8** README (outline in section 10), incl. Track 02 and Track 01 coverage tables (A11 folded in) | 3.5 h | **B8** Deploy: docker-compose primary; FalkorDB Cloud + app host as bonus; `DATA.md` with seeds and licenses | 3 h |
| 10 | **A13** MCP-client clip: config snippet + 20-second recording of a stock MCP client (e.g. Claude Code) calling `recall`, `fragility`, `distrust` | 1 h | **B9** Blog post with real benchmark numbers (AirPods prize) | 3 h |
| 11 | **A9** Record and edit the 3-minute video (script in section 9) | 3 h | B: help A9 (screen captures, voiceover review) | — |
| 12 | Together: rehearse the 30-minute Q4–Q7 + JTMS walkthrough; final checklist (section 11); submit by 9 PM, naming Tracks 02 and 01 | | | |

### Hour totals (remaining)

- **Lane A:** A3 3 + A4 5 + A5 3 + A6 6 + A10 4 + A7 6 + A12 2 + A8 3.5 + A13 1 + A9 3 = **36.5 h**
- **Lane B:** B1+ 1 + B3 8 + B6a 3 + B5 3 + B10 4 + B6b 2 + B7 5 + B11 3 + B8 3 + B9 3 = **35 h** (+ helps A9)

---

## 5. Contract v1.1 (the only change after the freeze)

Additive and backward-compatible. `ap_tiny.json` and all existing code keep working.

- `:Mem.mtype` — optional enum `episodic | semantic | procedural`.
  - Observations are episodic by definition.
  - Beliefs default to semantic.
  - Learned rules are procedural.
- Scenario JSON gets an optional top-level `domain`: `"ap"` | `"science"`.
- Science sources carry an optional `retracted_at` (ISO date) and `rw_reason` (the string from the dataset).
- Ground-truth labels stay `contaminated` and `truly_supported`; they are required for both domains.
- Everything else from v1 is unchanged:
  - labels, edges and the status enum;
  - MCP signatures;
  - the retraction event payload `{retraction_id, agent, belief_id, reason, invalidated_plan_ids[]}`;
  - tenancy `tenant_<id>`.

---

## 6. Directory ownership (v2)

```
retcon/
  CLAUDE.md                 shared
  docs/                     BUILD_PLAN, CONTRACT, STATUS, SPIKE: shared
  docker-compose.yml        shared
  core/
    schema.cypher           shared, change only via both
    retract/ recall/ preview/ analytics/     <- A  (analytics = PageRank, WCC)
    write/ retrieve/ fragility/              <- B
  mcp_server/
    tools_retract.py                         <- A
    tools_memory.py                          <- B
  gate/                                      <- A
  agents/
    remediator.py                            <- A
    research/ (reader.py, synthesizer.py)    <- A   (reuses B's loop)
    loop/ intake/ analyst/ payments/ comms/  <- B
  data/
    fixtures/ap_tiny.json                    shared
    fixtures/science_tiny.json               A (hand-written, Step 0)
    generator/ portal/ bank/                 <- B
    science/ (ingest, cache/, raw/)          <- B   (raw/ gitignored)
  bench/
    baselines/ metrics_retract.py science_eval.py   <- A
    harness/ metrics_scale.py concurrency.py        <- B
  ui/
    shell/ radar/                            <- B
    cascade/ preview/ recall/ keystone/      <- A
  tests/
    property/ differential/                  <- A
    queries/ load/                           <- B
```

---

## 7. Scope tiers and cut order

**Commit: must ship (~75%).** Judged on these.

- Q1–Q7, JTMS re-derive, property + differential tests
- Four AP agents + Remediator, action gate, recall list, graph-off flag
- `mtype` memory types + the retractable procedural rule (B1+)
- Agents calling `fragility`/`why` as tools (B3+)
- `GRAPH.COPY` preview
- **Science real-data scenario:** B10 ingest + A10 agents and eval
- UI: live graph, cascade animation, recall panel, fragility radar, preview diff
- RetconBench: 4 baselines x 2 scenarios at 1k and 10k nodes
- README with coverage tables, 3-minute video, blog, docker-compose local setup, DATA.md, AI disclosure

**Target: ship if the gate passes on time (~20%).**

- B11 concurrency + tenancy test
- A12 PageRank keystones + WCC
- A13 MCP-client clip
- FalkorDB Cloud live deploy
- 100k-node benchmark run
- Latency badge polish

**Stretch: only with spare time (~5%), in order.**

1. Point-in-time replay ("what did Payments believe at 14:02 on Oct 7?"), which is cheap because we never delete.
2. Entrenchment-based auto-retraction when a higher-trust source contradicts a lower one.
3. Graphiti bridge.
4. Cross-tenant threat sharing.

**Dropped from the spec:** the support-bot and dev-agent synthetic domains. They are replaced by the real science scenario.

**Cut order if behind:** stretch -> 100k run -> Cloud deploy -> A12 WCC -> A12 PageRank -> A13 clip -> B11 load test -> A6 polish -> B6b radar polish (keep it functional).

**Never cut:**

- Q3–Q7
- the gate
- the recall list
- the graph-off flag
- B3+ (agents use graph tools)
- the science scenario
- property tests

---

## 8. Flex and swap rules

- If Lane A is behind at the gate: **B takes A5** (preview).
- If Lane B is behind: **A takes B6b** (radar) and **B8** (deploy).
- If B10 slips past Oct 17 18:00: A10 ships on `science_tiny.json` extended by hand to about 80 nodes, still built from real Retraction Watch entries. B finishes the full ingest only if time remains.
- Whoever has slack:
  - README sections beyond the data model and queries
  - chart styling
  - the cascade GIF
  - demo timing rehearsal
  - blog proofreading

---

## 9. Demo script (3 minutes, v2)

| Time | On screen | Track / criterion it proves |
|---|---|---|
| 0:00–0:15 | Hook: "Your agent paid $18,400 to a fraudster. Which of its other 2,000 memories are lies?" BEC loss stat | Stakes |
| 0:15–0:45 | AP agents working; live graph grows; each belief shows its justification edges; `mtype` colour key | T02 memory types; graph is the memory |
| 0:45–1:05 | Payments agent calls `fragility` -> cost 1 -> chooses to request verification on its own | T01 algorithms as agent tools, MCP tool selection |
| 1:05–1:20 | Operator: distrust Coastal portal, Oct 2–9 -> **Preview** on a GRAPH.COPY fork shows the diff | Explainability, safety |
| 1:20–1:50 | **Commit**: cascade animates hop by hop; latency badge; the address belief stays green | T02 memory that updates; precision |
| 1:50–2:10 | Recall list: $18,400 with a drafted recall; Comms blocked; Payments re-plans; the procedural rule shown with its episode | T01 actions from the graph; T02 shared state + handoffs |
| 2:10–2:35 | **Real data:** "Same engine, real retractions." Research agents' claims on real papers; retracting them -> science column of the benchmark | Real-world validation, rule 6 |
| 2:35–2:50 | Benchmark slide + graph-off toggle: vector-only memory still pays the attacker | Rule 3 on camera; rigour |
| 2:50–3:00 | "Drop it into any MCP agent" clip + repo URL | Ecosystem value |

Record the agent phases from seeded runs. Run the cascade, preview and recall live, since they're deterministic.

---

## 10. README outline (A8)

1. One-line pitch + cascade GIF
2. Quickstart: `docker compose up` (one command), then `make demo`
3. **Track coverage tables**:

   Track 02:

   | Focus | Feature |
   |---|---|
   | Episodic, semantic, procedural memory | `mtype` |
   | Persistent conversation history | Observations + sessions, never deleted |
   | Shared state and handoffs | Handoff justification edges + retraction events |
   | High-concurrency reads and writes | B11 results |
   | Separate memory per user or tenant | One FalkorDB graph per tenant + isolation test |

   Track 01:

   | Focus | Feature |
   |---|---|
   | Multi-hop reasoning | Cascade + `why` |
   | Graph queries and algorithms as agent tools | `fragility` (maxFlow), PageRank |
   | Tool selection through MCP | Agents choose `fragility`/`why`/`act` |
   | Actions based on what the graph shows | Gate, recall list, Remediator |
   | Explainable results | Justification trees, preview diff |

4. Graph data model (diagram from the spec doc)
5. **Queries we depend on**: Q1–Q8 verbatim, plus `GRAPH.COPY` usage and the min-cut caveat
6. Architecture + agent loop
7. RetconBench results: AP + science tables, latency, concurrency, graph-off ablation
8. Related work and novelty: the table from the spec (Graphiti, Veritas, MemLineage, MemTX), stated honestly
9. Data: link to DATA.md (synthetic AP; Retraction Watch + OpenAlex with licenses)
10. Limitations (min-cut upper bound; LLM extraction quality; measured concurrency limits)
11. **AI assistance disclosure** (rule 11)
12. Tracks entered: 02 and 01

---

## 11. Rules compliance checklist (verify before submitting)

- [ ] **Rule 2:** FalkorDB is the only memory store. No other DB anywhere in docker-compose.
- [ ] **Rule 3:** the graph-off ablation is in the repo and the video; core features have no non-graph fallback.
- [ ] **Rule 6:** AP data is fully synthetic. Science data is public (Retraction Watch, OpenAlex), and DATA.md states the licenses. No private, login-protected, paywalled or personal data. No real company names or IBANs in AP.
- [ ] **Rule 8:** first commit after Oct 15, 12:01 AM IST (already true). Keep the history intact; no force-push rewrites.
- [ ] **Rule 9:** no code copied from Veritas, MemLineage or MemTX; they are cited as related work only.
- [ ] **Rule 10:**
  - public repo
  - README with setup + data model
  - Cypher queries listed
  - demo video
  - live deployment or full local setup
  - tracks named
- [ ] **Rule 11:** AI assistance disclosed in the README.
- [ ] **Rules 12–13:** both of us can explain the graph model, Q4–Q7, the JTMS invariant, the min-cut caveat and the architecture. The 30-minute rehearsal is done.
- [ ] Attack payloads are synthetic and target only our sandboxed agents.

---

## 12. Daily rhythm

- **Start of every session:** read STATUS.md, pull `main`, run `make test`.
- **End of every session:** update STATUS.md (next step + gotchas), push, and make sure `main` is green.
- **Twice a day (about 10:00 and 22:00 IST):** 15-minute sync. Check against the gate/freeze timeline and apply cuts early rather than late.
- **Oct 17, 22:00 checkpoint:**
  - all Commit-tier tasks done or nearly done -> start Target tier;
  - otherwise cut, in section 7 order.
