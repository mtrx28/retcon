# STATUS: the baton

Update your rows at the end of every session. States: `todo | doing | done | blocked`. Order = global finish sequence (same number runs in parallel). Acceptance command: `make accept T=<id>`.

Owner column: put the person's name once decided (A = lane "Retract & Prove", B = lane "Remember & Foresee").

Lane A person: _TBD_  ·  Lane B person: _TBD_

## Phase 0 (together)

| Id | Task | State | Last commit | Next step / gotchas |
|---|---|---|---|---|
| 0.1 | Repo skeleton, docker-compose, Makefile, test setup | todo | | |
| 0.2 | Freeze `docs/CONTRACT.md` + `core/schema.cypher` + indexes | todo | | |
| 0.3 | Cypher spike of Q1–Q8, vector index, maxFlow, GRAPH.COPY -> `docs/SPIKE.md` | todo | | |
| 0.4 | Hand-written `data/fixtures/ap_tiny.json` + loader | todo | | |
| 0.5 | CLAUDE.md / STATUS.md seeded | doing | | Skeletons written; fill Commands in CLAUDE.md after 0.1 |

## Lane A: Retract & Prove

| Order | Id | Task | Est | State | Last commit | Next step / gotchas |
|---|---|---|---|---|---|---|
| 1 | A1 | Q3–Q5 cascade + re-derive loop on fixture; `:Retraction` node | 5 h | todo | | |
| 2 | A2 | Property tests + in-memory JTMS reference + differential test | 4 h | todo | | |
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
| 1 | B1 | Q1 justified write + automatic premise-capture middleware | 4 h | todo | | |
| 2 | B2 | Q2 vector retrieval, IN-only, support summary | 3 h | todo | | |
| 2 | B4a | Generator v1 (seeded AP scenario) + fake portal + mock bank + sandbox inbox | 4 h | todo | | |
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

- _none yet_
