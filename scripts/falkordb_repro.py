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
