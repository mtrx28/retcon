> **Do not claim this as our finding.** Someone else already opened an issue for this FalkorDB behaviour (decided Oct 16). We only work around it (guards in `core/analytics/`). Do not mention it as a discovery in the README, video or blog. This file is kept as an internal note.

# FalkorDB issue draft (copy from here into GitHub)

Nothing in this file has been posted. Paste the title and the body below into a new issue.
Before posting: search the repo's issues for `LAGr_PageRank failed` and `LAGr_ConnectedComponents failed`
(open and closed) and stop if it is already reported.

---

## Title

`algo.pageRank` and `algo.WCC` (with `nodeLabels`) fail with `LAGr_...: -1000` when the node set has exactly one node

## Body

### What happens

`algo.pageRank` and `algo.WCC` raise an error with an internal LAGraph status code instead of returning a result
when the set of nodes they run on contains exactly one node. Zero nodes and two or more nodes work.

It is easy to hit by accident: a freshly created tenant or graph with a single node, or a label filter
(`nodeLabels:['A']`) that selects exactly one node in a larger graph.

### Reproduction (no client library, three lines)

```
GRAPH.QUERY g "CREATE (:A {id:1})"
GRAPH.QUERY g "CALL algo.pageRank('A', 'R') YIELD node, score RETURN node.id, score"
GRAPH.QUERY g "CALL algo.WCC({nodeLabels:['A']}) YIELD node, componentId RETURN node.id, componentId"
```

Actual:

```
LAGr_PageRank failed: -1000
LAGr_ConnectedComponents failed: -1000
```

Expected: one row each (`id 1, score 1.0`; `id 1, componentId 0`), the same kind of result you get with two nodes, or at
least a clear error message.

### What I tried (same server, same image)

| nodes the algorithm sees | `pageRank('A','R')` | `pageRank(null,null)` | `WCC({nodeLabels:['A']})` | `WCC()` (no filter) |
|---|---|---|---|---|
| 0 | ok, 0 rows | ok, 0 rows | ok, 0 rows | ok, 0 rows |
| **1** | **error** | **error** | **error** | ok, 1 row |
| 2 | ok | ok | ok | ok |
| 3 | ok | ok | ok | ok |

More observations:

- The relationship type does not matter: with `R` never created, with `R` present elsewhere, and with a self-loop of type `R`
  on the single node, the result is the same.
- A label filter that selects one node out of a larger graph (`CREATE (:A), (:B), (:B)` then `nodeLabels:['A']`) also fails.
- Unfiltered `algo.WCC()` on a one-node graph works, while `algo.pageRank(null, null)` on the same graph fails. So the
  two procedures behave differently for the same input.

A runnable version of the whole table (Python client) is in the collapsed section at the end of this issue.

### Environment

- Image: `falkordb/falkordb@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6` (the `latest` tag as of 2026-10-09)
- `MODULE LIST`: `graph ver 60002`; Redis `8.10.2`; Linux on Docker Desktop (WSL2)
- Client: `falkordb` Python package (also reproduced with `redis-cli` inside the container)

### Impact and workaround

We use `algo.pageRank` and `algo.WCC` to rank sources by how much memory rests on them, and to find clusters of
contradicting beliefs, in an application where each tenant is its own graph. A new tenant with one node hits this.
Workaround: count nodes first and skip the call when there is fewer than two. That works, but a one-node graph is a
valid input with an obvious answer, so returning it (or a descriptive error) would be friendlier.

I have not looked at the cause; the `-1000` status comes from the LAGraph call, so I don't know whether the fix
belongs in FalkorDB's wrapper or upstream. Happy to test a fix.


<details>
<summary>falkordb_repro.py (runs every row of the table above)</summary>

```python
"""Minimal reproduction for FalkorDB: algo.pageRank and algo.WCC fail with an opaque `LAGr_...: -1000` error when
the node set they run on has exactly one node. Zero nodes and two-or-more nodes work. Needs only the `falkordb`
Python client and a running server.

    python scripts/falkordb_repro.py            # uses FALKORDB_HOST / FALKORDB_PORT (default localhost:6379)

Every case prints PASS or the exact error, so the output can be pasted into an issue as-is. The same thing in
three redis-cli lines is in docs/FALKORDB_ISSUE.md.
"""
import os

from falkordb import FalkorDB

db = FalkorDB(host=os.getenv("FALKORDB_HOST", "localhost"), port=int(os.getenv("FALKORDB_PORT", "6379")))
try:
    mods = [dict(zip(m[::2], m[1::2])) for m in db.connection.execute_command("MODULE", "LIST")]
    print("server redis_version:", db.connection.info().get("redis_version"),
          "| modules:", [f"{m.get('name')} ver {m.get('ver')}" for m in mods])
except Exception as e:  # noqa: BLE001 - version banner is best effort
    print("server version unavailable:", e)

PAGERANK = "CALL algo.pageRank('A', 'R') YIELD node, score RETURN node.id, score"
PAGERANK_NOARGS = "CALL algo.pageRank(null, null) YIELD node, score RETURN node.id, score"
WCC_LABEL = "CALL algo.WCC({nodeLabels:['A']}) YIELD node, componentId RETURN node.id, componentId"
WCC_PLAIN = "CALL algo.WCC() YIELD node, componentId RETURN node.id, componentId"


def run(title, create, query):
    g = db.select_graph("falkordb_repro")
    try:
        g.delete()
    except Exception:  # noqa: BLE001
        pass
    g = db.select_graph("falkordb_repro")
    if create:
        g.query(create)
    try:
        print(f"PASS  {title}: {len(g.query(query).result_set)} row(s)")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL  {title}\n      {type(e).__name__}: {e}")
    finally:
        try:
            g.delete()
        except Exception:  # noqa: BLE001
            pass


def nodes(n):
    return "CREATE " + ", ".join(f"(:A {{id:{i}}})" for i in range(1, n + 1))


for n in (0, 1, 2, 3):
    print(f"\n--- {n} node(s), no relationships at all ---")
    run("algo.pageRank('A','R')", nodes(n) if n else None, PAGERANK)
    run("algo.pageRank(null, null)", nodes(n) if n else None, PAGERANK_NOARGS)
    run("algo.WCC({nodeLabels:['A']})", nodes(n) if n else None, WCC_LABEL)
    run("algo.WCC()  (no filter)", nodes(n) if n else None, WCC_PLAIN)

print("\n--- one node WITH a relationship (a self-loop) ---")
run("algo.pageRank('A','R')", "CREATE (a:A {id:1})-[:R]->(a)", PAGERANK)
run("algo.WCC({nodeLabels:['A']})", "CREATE (a:A {id:1})-[:R]->(a)", WCC_LABEL)

print("\n--- one node labelled A in a bigger graph (the label filter selects a single node) ---")
run("algo.WCC({nodeLabels:['A']})", "CREATE (:A {id:1}), (:B {id:2}), (:B {id:3})", WCC_LABEL)
```

</details>

---

## Optional second post (GitHub Discussions, not an issue)

This one is a suggestion, not a bug: the 10,000-row cap is documented configuration, but the truncation is silent.

**Title:** Suggestion: signal when `RESULTSET_SIZE` truncates a result

**Body:** With the default `RESULTSET_SIZE` (10000), a query that matches more rows returns exactly 10,000 and no error or
warning, so client code can't tell a complete answer from a truncated one:

```
GRAPH.QUERY g "UNWIND range(1, 25000) AS i CREATE (:N {i:i})"
GRAPH.QUERY g "MATCH (n:N) RETURN n.i"        -> 10000 rows, no indication that 15000 were dropped
```

We hit this when a consistency checker reported thousands of false inconsistencies at 10k nodes (it had received 10,000
of 11,076 rows). We now page with `SKIP/LIMIT`. Would a flag in the response statistics (for example "Result set truncated")
be reasonable, so drivers can surface it?
