"""Load a scenario/fixture JSON (docs/CONTRACT.md section 8) into graph tenant_<tenant>.

Usage: python -m data.load_fixture [path]   (default: data/fixtures/ap_tiny.json)
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from falkordb import FalkorDB

SCHEMA = Path(__file__).resolve().parent.parent / "core" / "schema.cypher"
FLOW_CAP = 1_000_000


def epoch(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) if iso else None


def connect():
    return FalkorDB(host=os.getenv("FALKORDB_HOST", "localhost"),
                    port=int(os.getenv("FALKORDB_PORT", "6379")))


def load(spec, db=None, graph_name=None):
    """Recreate the tenant graph from spec and return it."""
    db = db or connect()
    name = graph_name or f"tenant_{spec['tenant']}"
    try:
        db.select_graph(name).delete()
    except Exception:
        pass
    g = db.select_graph(name)
    for line in SCHEMA.read_text().splitlines():
        if line.strip() and not line.startswith("//"):
            g.query(line)
    q = g.query

    for s in spec["sources"]:
        q("CREATE (:Source {id:$id, kind:$kind, trust:$trust})", s)
    for a in spec["agents"]:
        q("CREATE (:Agent {id:$id, role:$role, tenant:$t})", {**a, "t": spec["tenant"]})
    for o in spec["observations"]:
        q("MATCH (s:Source {id:$src}) "
          "CREATE (o:Mem:Observation {id:$id, text:$text, status:'IN', observed_at:$at, agent:'intake'}) "
          "CREATE (s)-[:SUPPORTS]->(o) "
          "CREATE (s)-[:FLOW {cap:1}]->(o) "
          "CREATE (o)-[:DEPENDS_ON]->(s)",
          {"src": o["source"], "id": o["id"], "text": o["text"], "at": epoch(o["observed_at"])})

    # Create every conclusion first: a premise may be derived later in the list (circular support),
    # and a MATCH on a missing node would silently drop that PREMISE_OF edge.
    seen = set()
    for d in spec["derivations"]:
        c = d["conclusion"]
        label = "Plan" if c["kind"] == "plan" else "Belief"
        if c["id"] not in seen:
            q(f"CREATE (:Mem:{label} {{id:$id, text:$text, status:'IN', agent:$agent}})",
              {"id": c["id"], "text": c["text"], "agent": d["agent"]})
            seen.add(c["id"])
    for d in spec["derivations"]:
        c = d["conclusion"]
        _justify(q, d["id"], d["rule"], d["agent"], d["premises"], c["id"])
        q("MATCH (a:Agent {id:$a}), (m:Mem {id:$m}) MERGE (a)-[:HOLDS]->(m)",
          {"a": d["agent"], "m": c["id"]})

    for a in spec["actions"]:
        q("CREATE (:Mem:Action {id:$id, tool:$tool, amount:$amount, executed:$ex, executed_at:$at, "
          "status:'IN', agent:$agent, text:$text})",
          {"id": a["id"], "tool": a["tool"], "amount": a["amount"], "ex": a["executed"],
           "at": epoch(a["executed_at"]), "agent": a["agent"], "text": f"{a['tool']} {a['amount']}"})
        _justify(q, f"j_{a['id']}", "combine", a["agent"], a["premises"], a["id"])
        q("MATCH (a:Agent {id:$a}), (m:Mem {id:$m}) MERGE (a)-[:HOLDS]->(m)",
          {"a": a["agent"], "m": a["id"]})
    return g


def _justify(q, jid, rule, agent, premises, conclusion):
    q("MATCH (c:Mem {id:$c}) "
      "CREATE (j:Justification {id:$j, rule:$rule, agent:$agent})-[:JUSTIFIES]->(c)",
      {"j": jid, "rule": rule, "agent": agent, "c": conclusion})
    for p in premises:
        q("MATCH (p:Mem {id:$p}), (j:Justification {id:$j}), (c:Mem {id:$c}) "
          "CREATE (p)-[:PREMISE_OF]->(j) "
          "MERGE (p)-[f:FLOW]->(c) SET f.cap = $cap "
          "MERGE (c)-[:DEPENDS_ON]->(p)",
          {"p": p, "j": jid, "c": conclusion, "cap": FLOW_CAP})


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = Path(args[0]) if args else Path(__file__).parent / "fixtures" / "ap_tiny.json"
    spec = json.loads(path.read_text(encoding="utf8"))
    g = load(spec)
    n = g.query("MATCH (m:Mem) RETURN count(m)").result_set[0][0]
    print(f"loaded tenant_{spec['tenant']}: {n} Mem nodes")
