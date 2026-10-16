# Payments agent: Gemini function calling, recorded and replayable

**What it is.** The Payments agent can choose its own tool calls with Gemini function calling. It sees the task, the
policy and what it has done so far, and picks the next of `begin_turn`, `recall`, `remember`, `fragility`, `why`,
`act` or `finish`. The rule-based Payments agent stays as the default and as the fallback.

**What the model does not do.** It never decides what is believed. Whether a memory is IN or OUT, whether a payment
is allowed (the independent-source policy) and what a retraction flips are all decided by the graph and the gate.
A model that tries to pay anyway is stopped by the gate; the recorded run shows this.

## Modes

| `--brain` | What happens | Needs |
|---|---|---|
| `rules` (default) | rule-based agents, deterministic | nothing |
| `replay` | answers come from the recorded transcript; a missing answer ends that task, it never calls the API | nothing (no key, no network) |
| `live` | calls Gemini, and records every call into the transcript | `GEMINI_API_KEY` in `.env`, `pip install -e ".[llm]"` |
| `auto` | replay if a transcript is on disk, else live if a key is set, else rules (what the guided demo uses) | nothing |

```bash
python -m agents.demo --brain replay            # the recorded Gemini run, offline
python -m agents.demo --brain live              # records a new transcript into data/llm_cache/payments
python -m agents.demo --brain rules             # the rule-based day
```

The transcript is `data/llm_cache/payments/`: one JSON file per model call (49 calls for the seed-7 day, including the
retraction event), keyed by the SHA-256 of the prompt, committed to the repo. A test replays it
(`tests/queries/test_llm_payments.py`) and checks the same payments, holds, recall list and remediation as the
rule-based day.

The benchmark (RetconBench) is rule-based and does not use the model.

## What the recorded run looks like

Payments paying a small invoice (INV-COASTAL-1, 6,000 USD), each line one model-chosen tool call:

```
begin_turn {}
recall     {"k": 1, "query": "INV-COASTAL-1 (6000 USD) matches an open PO."}
recall     {"query": "Coastal Produce bank account IBAN", "contains": "Coastal Produce", "k": 4}
remember   {"kind": "plan", "text": "Pay INV-COASTAL-1 6000 USD to SYN-9000-5305."}
recall     {"query": "Pay INV-COASTAL-1 6000 USD to SYN-9000-5305.", "k": 1}
fragility  {"node_id": "mem_4745a5eb76b1"}  ->  {"independent_sources": 1, "cut_set": ["coastal-portal"], ...}
why        {"node_id": "mem_4745a5eb76b1"}
act        {"tool": "pay", ...}             ->  {"executed": true, "action_id": "act_e1934ffef625", ...}
```

The large invoice (INV-COASTAL-2, 34,500 USD) rests on one source, so the agent holds it and asks Comms for a callback
verification. After `distrust(coastal-portal, Oct 2 to 9)` the 6,000 payment, already sent, is on the recall list with a
drafted bank recall.

## Things to know (honest notes)

- **The model is not perfectly consistent.** In earlier recordings, with a looser prompt, Gemini once held a payment it
  should have made (it ignored the amount threshold) and once wrote "callback verification requested" without setting
  the flag that actually sends it. The prompt now spells out the numeric comparison and the flag, and the committed
  transcript is the run where the day came out correct. The behaviour was not hidden; it is why replay exists.
- **Model and quota.** Recorded with `gemini-3.5-flash-lite` (set `RETCON_GEMINI_MODEL` to change it). The free tier
  caps daily requests per model, so a fresh recording can hit a limit; the adapter backs off and retries.
- **Data sent to Google.** Only the synthetic accounts-payable data and the agent's own tool results. Free-tier prompts
  may be used by Google to improve its products, which is fine for synthetic data. The API key lives in `.env`, which is
  git-ignored.
- **What the model decides, and what it does not:** it decides the order and arguments of its tool calls and when to
  finish. The ledger (which plan, what it cost, whether it was paid) is derived from what actually happened in the tool
  results, not from what the model says.
