# Use RETCON from a stock MCP client

RETCON is a normal MCP server over stdio. Any MCP client (Claude Code, Claude Desktop, Cursor, your own agent) can
give its agent retractable memory. Verified here by launching it as a subprocess with the `mcp` client library and
calling the tools below against a live FalkorDB graph (transcript at the end).

## 1. Prerequisites

```bash
python tasks.py up                       # FalkorDB (or: docker compose up -d falkordb)
python -m pip install -e ".[dev]"        # once; makes `mcp_server` importable from any directory
python -m agents.demo --graph tenant_demo --no-retract    # a graph worth talking to (agents work, nothing retracted)
```

The server uses one graph per tenant: it opens `tenant_<RETCON_TENANT>`. The line above builds `tenant_demo`.
If FalkorDB is not on 6379, set `FALKORDB_PORT`. For an offline run set `RETCON_EMBEDDER=hash` (the real model is
`minilm`, see below).

## 2. Register the server

**Claude Code** (one command; use the full path to the project's virtualenv Python):

```bash
claude mcp add retcon \
  -e RETCON_TENANT=demo -e FALKORDB_PORT=6379 -e RETCON_EMBEDDER=hash \
  -- /full/path/to/retcon/.venv/bin/python -m mcp_server.server
# Windows: -- C:\full\path\to\retcon\.venv\Scripts\python.exe -m mcp_server.server
```

**Claude Desktop and most other clients** (a JSON config; in Claude Desktop it is `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "retcon": {
      "command": "/full/path/to/retcon/.venv/bin/python",
      "args": ["-m", "mcp_server.server"],
      "env": { "RETCON_TENANT": "demo", "FALKORDB_PORT": "6379", "RETCON_EMBEDDER": "hash" }
    }
  }
}
```

No working directory is needed: the project is installed into its virtualenv in editable mode.
Restart the client, then ask it to list its tools.

## 3. What the agent can call (15 tools)

| Tool | What it does |
|---|---|
| `recall(query, agent, k, contains?)` | Search memory. Only beliefs that are still supported come back, each with the sources it rests on and the weakest trust among them. Everything returned becomes a premise of the agent's next write. |
| `remember(text, kind, agent, mtype?)` | Write a belief or plan. Its justification is whatever the agent just recalled: agents never name parents. |
| `observe(source, text, observed_at, agent)` | Record what a source said. |
| `fragility(node_id)` | Poisoning cost: how many sources would have to fail before this falls, with the cheapest set of them. |
| `why(node_id)` | The justification tree behind a node, down to the sources. |
| `distrust(source, from_, to, mode)` | Retract everything that rested on a source in a time window. `mode="preview"` runs on a copy and writes nothing; `commit` applies it. |
| `reinstate(retraction_id)` | Undo a retraction exactly. |
| `recall_list(run?)` | Actions already executed on retracted beliefs, largest first. |
| `act(tool, args, agent)` | Propose an action. A gate blocks it if a premise was retracted or the payment is too fragile. |
| `list_remediations`, `approve_remediation`, `reject_remediation` | Drafted compensations (bank recall, correction email). Nothing is sent until approved. |
| `keystones(top, order)` | Audit priority: sources ranked by how much memory rests on how little trust. |
| `contradictions()` | Clusters of beliefs that disagree (rule-based, accounts payable only). |
| `begin_turn(agent)` | Clear what an agent has read so far. |

Errors always come back as `{"error": {"code", "message", "details"}}`; a success never has an `error` key.

## 4. A 20-second demo to record

In the client, with the demo graph loaded, say:

1. "Use retcon to find what we know about Coastal Produce's bank account, as the auditor." (calls `recall`)
2. "How many sources would have to be wrong before the $34,500 payment plan falls?" (calls `fragility`, answer: one)
3. "Which source should I audit first?" (calls `keystones`; `coastal-portal`, trust 0.4, is at the top)
4. "Preview distrusting coastal-portal from 2026-10-02 to 2026-10-09." (calls `distrust` with `mode=preview`)

Step 4 changes nothing. Say "commit it" to apply it, `recall_list` to see which payment to recall, and `reinstate` to
take it all back.

## 5. What you should see (real output, abbreviated)

```
TOOLS: act, approve_remediation, begin_turn, contradictions, distrust, fragility, keystones,
       list_remediations, observe, recall, recall_list, reinstate, reject_remediation, remember, why

recall("bank account for Coastal Produce", agent="auditor", k=3)
  "Coastal Produce bank account is IBAN SYN-9000-5305."   sources ["coastal-portal"]    weakest_trust 0.4
  "Contract bank for Coastal Produce is IBAN SYN-1000-2471."  sources ["coastal-contract"]  weakest_trust 0.9

fragility(<the $34,500 payment plan>)
  {"independent_sources": 1, "bound": "exact", "cut_set": ["coastal-portal"], "flow_upper_bound": 4.0}

keystones(top=3)
  coastal-portal  trust 0.4  10 live memories rest on it   <- audit this first
  v001-portal     trust 0.7  10
  coastal-contract trust 0.9  7

distrust("coastal-portal", "2026-10-02T00:00:00Z", "2026-10-09T23:59:59Z", mode="preview")
  flipped: 2 observations, 4 beliefs, 2 plans, 2 actions; recall_list: the 6,000 payment; survived: 1 belief
```

The ranking is an audit priority, not a detection: RETCON does not know which source is compromised.

## 6. Using the real embedding model

`RETCON_EMBEDDER=hash` is a deterministic, offline stand-in. For semantic retrieval install the model once
(`python -m pip install -e ".[embed]"`) and use `RETCON_EMBEDDER=minilm`. A graph must be embedded with one
embedder only.
