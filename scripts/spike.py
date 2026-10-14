"""Phase 0.3: probe every FalkorDB feature RETCON depends on against the live engine.
Prints PASS/FAIL per probe so docs/SPIKE.md can record the working syntax."""
import sys, traceback
from falkordb import FalkorDB

db = FalkorDB(host="localhost", port=6379)
G = "spike"
try:
    db.select_graph(G).delete()
except Exception:
    pass
g = db.select_graph(G)
results = []


def probe(name, fn):
    try:
        out = fn()
        results.append((name, "PASS", out))
    except Exception as e:  # noqa
        results.append((name, "FAIL", f"{type(e).__name__}: {e}"))


def q(cypher, params=None):
    return g.query(cypher, params or {}).result_set


probe("module list", lambda: db.connection.execute_command("MODULE", "LIST"))

# --- tiny graph: Source -SUPPORTS-> Obs -PREMISE_OF-> Just -JUSTIFIES-> Belief (chain), plus a second
# independent source supporting the same belief via its own justification.
def build():
    q("""CREATE (s1:Source {id:'portal', trust:0.5}), (s2:Source {id:'contract', trust:0.9}),
         (o1:Mem:Observation {id:'o1', status:'IN', observed_at:5, text:'new bank'}),
         (o2:Mem:Observation {id:'o2', status:'IN', observed_at:6, text:'new bank pdf'}),
         (b1:Mem:Belief {id:'b1', status:'IN', text:'vendor bank is X'}),
         (b2:Mem:Belief {id:'b2', status:'IN', text:'derived only from portal'}),
         (j1:Justification {id:'j1'}), (j2:Justification {id:'j2'}), (j3:Justification {id:'j3'}),
         (s1)-[:SUPPORTS]->(o1), (s2)-[:SUPPORTS]->(o2),
         (o1)-[:PREMISE_OF]->(j1), (j1)-[:JUSTIFIES]->(b1),
         (o2)-[:PREMISE_OF]->(j2), (j2)-[:JUSTIFIES]->(b1),
         (o1)-[:PREMISE_OF]->(j3), (j3)-[:JUSTIFIES]->(b2)""")
    return "built"
probe("create graph", build)

# Q3 distrust in window
probe("Q3 distrust window", lambda: q(
    "MATCH (s:Source {id:$s})-[:SUPPORTS]->(o:Observation) WHERE o.observed_at >= $f AND o.observed_at <= $t "
    "SET o.status='OUT', o.run=$run RETURN o.id", {"s": "portal", "f": 2, "t": 9, "run": "r1"}))

# Q4 tentative cascade (variable length, mixed rel types)
probe("Q4 cascade varlen", lambda: q(
    "MATCH (o:Observation {run:$run})-[:PREMISE_OF|JUSTIFIES*1..12]->(x:Mem) WHERE x.status='IN' "
    "WITH DISTINCT x SET x.status='OUT', x.run=$run RETURN x.id", {"run": "r1"}))

# Q5 re-derive loop: EXISTS{} subquery is unsupported -> OPTIONAL MATCH + count; loop to fixpoint
def rederive():
    total = []
    while True:
        r = q("MATCH (j:Justification)-[:JUSTIFIES]->(b:Mem {status:'OUT', run:$run}) "
              "OPTIONAL MATCH (p:Mem {status:'OUT'})-[:PREMISE_OF]->(j) "
              "WITH b, j, count(p) AS dead WHERE dead = 0 "
              "WITH DISTINCT b SET b.status='IN', b.run=null RETURN b.id", {"run": "r1"})
        if not r:
            return total
        total += [x[0] for x in r]
probe("Q5 rederive loop", rederive)

probe("status after cascade", lambda: q("MATCH (m:Mem) RETURN m.id, m.status ORDER BY m.id"))

# Vector index + query
def vec():
    q("CREATE VECTOR INDEX FOR (m:Mem) ON (m.embedding) OPTIONS {dimension:4, similarityFunction:'cosine'}")
    q("MATCH (m:Mem {id:'b1'}) SET m.embedding = vecf32([1.0,0.0,0.0,0.0])")
    q("MATCH (m:Mem {id:'b2'}) SET m.embedding = vecf32([0.0,1.0,0.0,0.0])")
    return q("CALL db.idx.vector.queryNodes('Mem','embedding',2,vecf32([1.0,0.1,0.0,0.0])) YIELD node, score "
             "WHERE node.status='IN' RETURN node.id, score")
probe("vector index+query", vec)

# Max flow (min-cut surrogate)
def flow():
    # maxFlow takes exactly ONE relationship type -> dedicated FLOW edges (maintained on write).
    q("MATCH (s:Source)-[:SUPPORTS]->(o:Observation) MERGE (s)-[f:FLOW]->(o) SET f.cap = 1")
    q("MATCH (p:Mem)-[:PREMISE_OF]->(:Justification)-[:JUSTIFIES]->(c:Mem) MERGE (p)-[f:FLOW]->(c) SET f.cap = 1000000")
    return q("MATCH (s:Source) WITH collect(s) AS srcs MATCH (t:Belief) "
             "CALL algo.maxFlow({sourceNodes: srcs, targetNodes: [t], "
             "relationshipTypes: ['FLOW'], capacityProperty: 'cap'}) "
             "YIELD maxFlow RETURN t.id, maxFlow ORDER BY t.id")
probe("algo.maxFlow", flow)

probe("algo.pageRank", lambda: q(
    "CALL algo.pageRank('Mem','PREMISE_OF') YIELD node, score RETURN node.id, score LIMIT 5"))
def pr():
    q("MATCH (c:Mem)-[:PREMISE_OF]->(:Justification)-[:JUSTIFIES]->(p:Mem) MERGE (p)-[:DEPENDS_ON]->(c)")
    # conclusion->premise direction for DEPENDS_ON: premise node gains rank from its dependents
    q("MATCH (c:Mem)-[:PREMISE_OF]->(:Justification)-[:JUSTIFIES]->(p:Mem) MATCH (p)-[d:DEPENDS_ON]->(c) DELETE d")
    q("MATCH (p:Mem)-[:PREMISE_OF]->(:Justification)-[:JUSTIFIES]->(c:Mem) MERGE (c)-[:DEPENDS_ON]->(p)")
    q("MATCH (s:Source)-[:SUPPORTS]->(o:Observation) MERGE (o)-[:DEPENDS_ON]->(s)")
    return q("CALL algo.pageRank(null,'DEPENDS_ON') YIELD node, score RETURN labels(node)[0], node.id, score ORDER BY score DESC LIMIT 4")
probe("algo.pageRank DEPENDS_ON incl Sources", pr)
probe("algo.WCC", lambda: q("CALL algo.WCC({nodeLabels:['Mem']}) YIELD node, componentId RETURN node.id, componentId LIMIT 5"))

def copy():
    db.connection.execute_command("GRAPH.COPY", G, G + "_copy")
    n = db.select_graph(G + "_copy").query("MATCH (m:Mem) RETURN count(m)").result_set
    db.select_graph(G + "_copy").delete()
    return n
probe("GRAPH.COPY", copy)

probe("GRAPH.PROFILE", lambda: db.connection.execute_command(
    "GRAPH.PROFILE", G, "MATCH (m:Mem) RETURN count(m)"))

for n, s, o in results:
    print(f"[{s}] {n}\n      {str(o)[:400]}")
g.delete()
sys.exit(0 if all(s == "PASS" for _, s, _ in results) else 1)
