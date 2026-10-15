# STATUS: the baton

Plan of record: `docs/UPDATED_BUILD_PLAN.md` (v2). Contract: `docs/CONTRACT.md` (v1.1).

Update your rows at the end of every session. States: `todo | doing | done | blocked`. Order = global finish sequence (same number runs in parallel). Acceptance command: `python tasks.py accept <id>` (id is lower-cased into a pytest marker; `B1+` is marker `b1plus`).

Lane A person: _TBD_  ·  Lane B person: _TBD_  ·  Dev FalkorDB port: B uses 6380 (`FALKORDB_PORT=6380`), compose default is 6379.

## Step 0 (together)

| Id | Task | State | Last commit | Next step / gotchas |
|---|---|---|---|---|
| 0.1–0.5 | Skeleton, contract v1, spike, fixture, CLAUDE.md/STATUS.md | done | main | |
| 0.6 | Contract v1.1: optional `mtype`, `domain`, `retracted_at`/`rw_reason`; STATUS seeded | doing | branch `shared/0.6-contract-v1.1` | Additive only. Loader now stores the optional fields and validates `domain`/`mtype` (`validate_spec`). Test: `tests/queries/test_contract_v11.py`. Merge after both skim the diff. |
| 0.7 | B: background data pull (Retraction Watch clone, OpenAlex fetches) into `data/science/raw/` (gitignored) | done | | Subject `(BLS) Biology - Cellular`. `selection.json`: 40 retracted papers (all with retraction date + RW reason); `openalex/retracted/` 40 files, `openalex/citing/` 305 files. Script: `data/science/fetch_science_raw.py` (run with `python -I`). Gotchas for B10: `retraction_date` is `M/D/YYYY H:MM` (parse, don't string-compare); `rw_reason` is a `;`-joined list; no `OPENALEX_MAILTO` was set. |
| 0.8 | Both: progress note + one technical question in the FalkorDB Discord | todo | | |

## Lane A: Retract & Prove

| Order | Id | Owner | Task | Est | State | Last commit | Next step / gotchas |
|---|---|---|---|---|---|---|---|
| 1 | A1 | A | Q3–Q5 cascade + re-derive loop on fixture; `:Retraction` node | 5 h | done | main | `core/retract/cascade.py`: `distrust()`, `reinstate()`; `core/recall/recall_list.py` (Q6 query, used by `distrust`; A4 still owns gate + Remediator). 10 tests (`accept A1`), ~10 ms on 24 nodes. Preview mode raises NotImplementedError until A5. |
| 2 | A2 | A | Property tests + in-memory JTMS reference + differential test | 4 h | done | main | `tests/differential/jtms_ref.py` (least-fixpoint reference), `graphgen.py` (Hypothesis specs incl. cycles/OR/AND), `tests/property/test_jtms_properties.py` (P1–P6), `tests/differential/test_differential.py`, `tests/property/test_regressions.py`. `python tasks.py accept A2` = 1,000 differential + 300 property graphs, ~3.5 min; plain `test` runs 100/60. **Found and fixed 2 engine bugs:** overlapping distrusts could be undone by reinstating the first; reinstate did not revive nodes flipped by a different retraction. A retraction now claims every observation in its window (`RETRACTED {flipped}`), reinstate re-derives globally. |
| 0 | A0 | A | `data/fixtures/science_tiny.json`: hand-written ~30-node science fixture (plan §3.4, §6) so A10/A7 can start before B10 | 1 h | todo | | Not a numbered card in the plan; listed in §3.4 and §6 as A's Step 0. Needs `domain: science`, `retracted_at`, `rw_reason`, ground truth. Use real Retraction Watch entries, reason strings verbatim. |
| 1 | A3 | A | MCP `distrust` / `reinstate` / `why` + audit trail; also `mcp_server/server.py` entrypoint that registers both tool modules | 3 h | todo | | Not blocked. Errors use the contract `{error:{code,message,details}}` shape. `mode=preview` returns `NOT_IMPLEMENTED` until A5. |
| 2 | A4 | A | Action gate + Q6 recall list + Remediator drafts compensating action behind one-click approval | 5 h | todo | | Q6 query already exists in `core/recall/recall_list.py`. Gate policy hook is ready: `core.fragility.meets_independence(g, action_or_plan_id, required=2)` returns `{ok, independent_sources, required, bound, cut_set}`; on `ok: false` use `{independent_sources, required}` as `BLOCKED_BY_POLICY.details`. Premise check first, then this for `pay` over $10k (CONTRACT section 7). |
| 4 | A5 | A | `GRAPH.COPY` preview: Q3–Q5 on fork, diff statuses, delete fork; MCP `mode=preview` | 3 h | todo | |  |
| 5 | A6 | A | UI: cascade hop-by-hop animation, preview diff, recall panel, `GRAPH.PROFILE` latency badge (function first, polish last) | 6 h | todo | | `distrust()` already returns `hops` for the animation. |
| 6 | A10 | A | Research agents (Reader, Synthesizer) on the B3 loop; one distrust per retracted paper; science metrics | 4 h | todo | | Start on `science_tiny.json`; switch to B10 output when merged. |
| 7 | A7 | A | Baselines 1–4 + residual contamination / collateral loss / action recall on AP **and** science | 6 h | todo | |  |
| 8 | A12 | A | Q8 PageRank keystone view + `algo.WCC` over CONTRADICTS (moved from B5b) | 2 h | todo | | Target tier, first to cut. Syntax in `docs/SPIKE.md` (`algo.pageRank(null,'DEPENDS_ON')`). |
| 9 | A8 | A | README incl. Track 02 / Track 01 coverage tables (A11 folded in) | 3.5 h | todo | |  |
| 10 | A13 | A | MCP-client clip: config snippet + 20 s recording of a stock MCP client | 1 h | todo | | Target tier. |
| 11 | A9 | A | Record and edit the 3-minute video (script: plan §9) | 3 h | todo | |  |

## Lane B: Remember & Foresee

| Order | Id | Owner | Task | Est | State | Last commit | Next step / gotchas |
|---|---|---|---|---|---|---|---|
| 1 | B1 | B | Q1 justified write + automatic premise-capture middleware | 4 h | done | main | `python tasks.py accept B1` (7 tests). Code: `core/write/{q1,capture}.py`, `core/memory.py`. Ids are content-hashed, so re-asserting a claim from new premises adds a 2nd Justification (OR). Status is decided by the graph rule (IN iff all premises IN). Capture context persists within a turn; `begin_turn(agent)` clears it. Only `remember`/`recall` wrappers exist in `mcp_server/tools_memory.py` (not yet registered with a server). |
| 2 | B2 | B | Q2 vector retrieval, IN-only, support summary | 3 h | done | main | `python tasks.py accept B2` (8 tests). Code: `core/retrieve/{q2,embed}.py`. `score` is cosine **distance** (lower = closer). Support is an exact least-fixpoint over live justifications (cycles cannot self-ground), depth 12. Fixture graphs need `python tasks.py embed` before `recall` works. Embedder: `RETCON_EMBEDDER=minilm` (needs `pip install -e .[embed]`) or `hash` (offline, tests). Do not mix the two in one graph. |
| 2 | B4a | B | Generator v1 (seeded AP scenario) + fake portal + mock bank + sandbox inbox | 4 h | done | main | `python tasks.py accept B4A` (10 tests). `python tasks.py gen --vendors 3 -o f.json`, `--nodes 10000` for scale; `python tasks.py sandbox` serves /portal /bank /mail on :8100. Vendor 0 is Coastal Produce, sources `coastal-portal` / `coastal-contract`; other vendors `v001`.. Ground truth comes from an independent in-memory JTMS (`reference_labels`) and is tested equal to FalkorDB's Q3-Q5. Portal replays by clock (`?as_of=`). Bank ids are sequential, recall via `POST /payments/<id>/recall`. Output carries extra keys (`vendors`, `meta`) the loader ignores. Loading 100k nodes through `load_fixture` is one query per row: B7 will need a batched loader. |
| 1 | B1+ | B | `mtype` tagging on the write path; Intake stores a procedural rule justified by an episode | 1 h | done | uncommitted | `python tasks.py accept B1+` (6 tests; the runner maps `+` to marker `b1plus`). `remember(..., mtype=)` / `MemoryService.learn_rule(text, agent, episode_ids)`; beliefs default `semantic`, plans untagged, observations `episodic`. A `procedural` write must have an episodic premise (else `INVALID_ARGUMENT`), so retracting the episode retracts the rule. Generator `audit_incident=True` adds a trusted `audit-log` episode and `rule_verify_bank` (survives the Coastal cascade, retracted only if `audit-log` is distrusted). Off by default so existing node counts are unchanged. The optional `mtype` arg on MCP `remember` is additive; contract signatures otherwise unchanged. |
| 2 | B5 | B | FLOW edges maintained on write; Q7 `algo.maxFlow`; `fragility` tool; gate policy hook (**moved forward to Phase 1**, no dependency on A) | 3 h | done | uncommitted | `python tasks.py accept B5` (9 tests). `core/fragility/q7.py`: `fragility(g, node_id)` -> `{independent_sources, bound, cut_set, live_sources, flow_upper_bound}`; `meets_independence(g, node_id, required=2)` is the gate hook (its `{independent_sources, required}` is the `BLOCKED_BY_POLICY` details). ap_tiny: $41,250 payment = 1, address belief = 2. Cost is the exact smallest source set whose removal falsifies the node under the real JTMS fixpoint (<=16 live sources, else a valid-cut upper bound, `bound:"upper"`). **Raw `algo.maxFlow` treats AND as OR** (payment = 3), so it is reported only as `flow_upper_bound`, a per-observation, whole-graph bound. See `docs/FRAGILITY.md`. FLOW edges were already written by B1 (`write_observation`, `write_justified`) and the loader. |
| 2 | B3 | B | Agent loop, four agents, handoff edges, retraction-event re-plan (cached, seeded LLM) incl. **B3+**: Payments calls `fragility`+`why` via MCP and requests verification when cost < 2 | 8 h | todo | | B3+ can call the real `fragility` now (B5 is done): `mcp_server.tools_memory.fragility(node_id)` or `core.fragility.fragility`. `act` is not written yet: pass straight through until A4's gate lands behind the same signature. |
| 3 | B6a | B | UI shell: graph canvas over FalkorDB, live node growth, status colours | 3 h | todo | |  |
| 5 | B10 | B | Science ingest (Retraction Watch + OpenAlex) emitting the fixture format with real ground truth | 4 h | todo | | Design: plan §4 B10. Cache LLM extractions under `data/science/cache/`. Fallback if late: A extends `science_tiny.json` by hand. |
| 6 | B6b | B | UI: fragility radar (Q7) | 2 h | todo | |  |
| 7 | B7 | B | RetconBench harness 1k/10k, laundering metric, latency p50/p95, graph-off flag, charts | 5 h | todo | | Needs a batched loader for 10k+ (one query per row today). |
| 8 | B11 | B | Concurrency (20–50 writers during a cascade) + two-tenant isolation check | 3 h | todo | | Target tier. Measure and report honestly. |
| 9 | B8 | B | Deploy (compose primary, Cloud bonus) + `DATA.md` with seeds and licenses | 3 h | todo | |  |
| 10 | B9 | B | Blog post with real benchmark numbers | 3 h | todo | |  |

## Gate (Oct 16 night, together)

`distrust(Coastal portal, Oct 2–9)` -> cascade -> $41,250 payment blocked -> $18,400 on recall list with drafted recall -> address belief survives via contract PDF -> Payments agent re-plans to the verified account. Needs A3, A4, B1+, B3.

| Check | State |
|---|---|
| Cascade marks expected nodes OUT | todo |
| Pending payment blocked | todo |
| Executed payment on recall list with drafted recall | todo |
| Independently supported belief stays IN | todo |
| Agents re-plan from surviving memory | todo |

## Open questions / decisions log

- 2026-10-15 (B): B5 pulled forward into Phase 1 (own Phase 2 task, no dependency on A), so B3 uses real `fragility` and A4 gets a real policy hook. B5 numbers match the plan acceptance (payment 1, address 2) only because cost is AND-aware; raw max-flow would say 3. B10 and the benchmark keep Oct 17.
- 2026-10-15 (B): `tasks.py accept B1+` previously selected zero tests (marker `b1+` does not exist); runner now maps `+` to `plus`.
- 2026-10-15 (B): fixed `data/load_fixture.py` forward-reference bug: premises derived later in the list (the circular pair) were silently dropped, so `b_circ_a/b_circ_b` were not actually circular in the graph. Loader now creates all conclusions first. Lane A: your cycle test is meaningful now.
- 2026-10-15 (B): host port 6379 was taken by another local Redis, so FalkorDB for dev runs as container `retcon-falkordb` on 6380 (`FALKORDB_PORT=6380`). `docker-compose.yml` is unchanged.
