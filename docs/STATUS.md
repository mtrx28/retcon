# STATUS: the baton

Update your rows at the end of every session. States: `todo | doing | done | blocked`. Order = global finish sequence (same number runs in parallel). Acceptance command: `python tasks.py accept <id>`.

Owner column: put the person's name once decided (A = lane "Retract & Prove", B = lane "Remember & Foresee").

Lane A person: _TBD_  ·  Lane B person: _TBD_

## Phase 0 (together)

| Id | Task | State | Last commit | Next step / gotchas |
|---|---|---|---|---|
| 0.1 | Repo skeleton, docker-compose, task runner, test setup | done | | `tasks.py` replaces Makefile (no make on Windows). Python venv on 3.13 |
| 0.2 | Freeze `docs/CONTRACT.md` + `core/schema.cypher` + indexes | done | | Decisions: 384-dim MiniLM embeddings, uniform `{error:{code,message,details}}`, data-driven gate policy. Contract frozen. |
| 0.3 | Cypher spike of Q1–Q8, vector index, maxFlow, GRAPH.COPY -> `docs/SPIKE.md` | done | | All probes pass; see SPIKE.md for syntax changes vs spec |
| 0.4 | Hand-written `data/fixtures/ap_tiny.json` + loader | done | | 24 Mem nodes; `python tasks.py fixture`; 3 tests pass |
| 0.5 | CLAUDE.md / STATUS.md seeded | done | | |

## Lane A: Retract & Prove

| Order | Id | Task | Est | State | Last commit | Next step / gotchas |
|---|---|---|---|---|---|---|
| 1 | A1 | Q3–Q5 cascade + re-derive loop on fixture; `:Retraction` node | 5 h | done | (uncommitted, branch `a/A1-cascade`) | `core/retract/cascade.py`: `distrust()`, `reinstate()`; `core/recall/recall_list.py` (Q6 query, used by `distrust`; A4 still owns gate + Remediator). 10 tests (`accept A1`), ~10 ms on 24 nodes. Preview mode raises NotImplementedError until A5. |
| 2 | A2 | Property tests + in-memory JTMS reference + differential test | 4 h | done | (uncommitted, branch `a/A2-property-tests`) | `tests/differential/jtms_ref.py` (least-fixpoint reference), `graphgen.py` (Hypothesis specs incl. cycles/OR/AND), `tests/property/test_jtms_properties.py` (P1–P6), `tests/differential/test_differential.py`, `tests/property/test_regressions.py`. `python tasks.py accept A2` = 1,000 differential + 300 property graphs, ~3.5 min; plain `test` runs 100/60. **Found and fixed 2 engine bugs:** overlapping distrusts could be undone by reinstating the first; reinstate did not revive nodes flipped by a different retraction. A retraction now claims every observation in its window (`RETRACTED {flipped}`), reinstate re-derives globally. |
| 3 | A3 | MCP `distrust` / `reinstate` / `why`; audit trail | 3 h | todo | | |
| 4 | A4 | Action gate + Q6 recall list + Remediator (one-click compensation) | 5 h | todo | | |
| 5 | A5 | `GRAPH.COPY` preview + status diff; `mode=preview` | 3 h | todo | | |
| 6 | A6 | UI: cascade animation, preview diff, recall panel, latency badge | 8 h | todo | | |
| 7 | A7 | Baselines 1–4 + residual / collateral / action-recall metrics | 6 h | todo | | |
| 8 | A8 | README: data model, Q1–Q8 verbatim, related work, limitations, AI disclosure | 3 h | todo | | |
| 9 | A9 | 3-minute video | 3 h | todo | | |

## Lane B: Remember & Foresee

| Order | Id | Task | Est | State | Last commit | Next step / gotchas |
|---|---|---|---|---|---|---|
| 1 | B1 | Q1 justified write + automatic premise-capture middleware | 4 h | done | uncommitted | `python tasks.py accept B1` (7 tests). Code: `core/write/{q1,capture}.py`, `core/memory.py`. Ids are content-hashed, so re-asserting a claim from new premises adds a 2nd Justification (OR). Status is decided by the graph rule (IN iff all premises IN). Capture context persists within a turn; `begin_turn(agent)` clears it. Only `remember`/`recall` wrappers exist in `mcp_server/tools_memory.py` (not yet registered with a server). |
| 2 | B2 | Q2 vector retrieval, IN-only, support summary | 3 h | done | uncommitted | `python tasks.py accept B2` (8 tests). Code: `core/retrieve/{q2,embed}.py`. `score` is cosine **distance** (lower = closer). Support is an exact least-fixpoint over live justifications (cycles cannot self-ground), depth 12. Fixture graphs need `python tasks.py embed` before `recall` works. Embedder: `RETCON_EMBEDDER=minilm` (needs `pip install -e .[embed]`) or `hash` (offline, tests). Do not mix the two in one graph. |
| 2 | B4a | Generator v1 (seeded AP scenario) + fake portal + mock bank + sandbox inbox | 4 h | done | uncommitted | `python tasks.py accept B4A` (10 tests). `python tasks.py gen --vendors 3 -o f.json`, `--nodes 10000` for scale; `python tasks.py sandbox` serves /portal /bank /mail on :8100. Vendor 0 is Coastal Produce, sources `coastal-portal` / `coastal-contract`; other vendors `v001`.. Ground truth comes from an independent in-memory JTMS (`reference_labels`) and is tested equal to FalkorDB's Q3-Q5. Portal replays by clock (`?as_of=`). Bank ids are sequential, recall via `POST /payments/<id>/recall`. Output carries extra keys (`vendors`, `meta`) the loader ignores. Loading 100k nodes through `load_fixture` is one query per row: B7 will need a batched loader. |
| 3 | B3 | Agent loop, four agents, handoff edges, re-plan on retraction event | 7 h | todo | | |
| 4 | B6a | UI shell: graph canvas, live growth, status colours | 3 h | todo | | |
| 5 | B5 | FLOW edges + Q7 min-cut + `fragility` MCP + gate policy hook | 3 h | todo | | |
| 6 | B6b | UI: fragility radar + keystone view | 3 h | todo | | |
| 6 | B5b | Q8 PageRank + WCC | 2 h | todo | | |
| 7 | B7 | RetconBench harness, 1k/10k/100k, laundering metric, latency, graph-off flag, charts | 6 h | todo | | |
| 8 | B8 | Deploy + `DATA.md` | 3 h | todo | | |
| 9 | B9 | Blog post | 3 h | todo | | |

## Gate (Oct 16 night, together)

`distrust(Coastal portal, Oct 2–9)` -> cascade -> $41,250 payment blocked -> $18,400 on recall list -> address belief survives via contract PDF.

| Check | State |
|---|---|
| Cascade marks expected nodes OUT | todo |
| Pending payment blocked | todo |
| Executed payment on recall list | todo |
| Independently supported belief stays IN | todo |
| Agents re-plan from surviving memory | todo |

## Open questions / decisions log

- 2026-10-15 (B): fixed `data/load_fixture.py` forward-reference bug: premises derived later in the list (the circular pair) were silently dropped, so `b_circ_a/b_circ_b` were not actually circular in the graph. Loader now creates all conclusions first. Lane A: your cycle test is meaningful now.
- 2026-10-15 (B): host port 6379 was taken by another local Redis, so FalkorDB for dev runs as container `retcon-falkordb` on 6380 (`FALKORDB_PORT=6380`). `docker-compose.yml` is unchanged.
